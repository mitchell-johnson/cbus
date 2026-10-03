//! Bounded streaming I/O for the existing version-one durable repository.
//!
//! The wire here-document limit remains independent. The larger repository
//! budget allows retained project backups without allocating a second full
//! encoded database during every commit. Mutation rollback remains owned by
//! Service; an unsuccessful pre-rename write cannot replace the old image.

use serde::{de::DeserializeOwned, Serialize};
use std::{
    fs::{File, OpenOptions},
    io::{self, BufReader, BufWriter, Read, Write},
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
};

pub(super) const MAX_BYTES: u64 = 256 * 1024 * 1024;

fn capacity_error(limit: u64) -> io::Error {
    io::Error::other(format!("C-Gate database exceeds {limit} bytes"))
}

struct LimitedReader<R> {
    inner: R,
    remaining: u64,
    limit: u64,
}

impl<R: Read> Read for LimitedReader<R> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if bytes.is_empty() {
            return Ok(0);
        }
        if self.remaining == 0 {
            // Unlike Take, do not turn a growing oversized file into a
            // successful EOF. JSON must also consume its trailing whitespace.
            let mut extra = [0];
            return match self.inner.read(&mut extra)? {
                0 => Ok(0),
                _ => Err(capacity_error(self.limit)),
            };
        }
        let count = bytes.len().min(self.remaining as usize);
        let read = self.inner.read(&mut bytes[..count])?;
        self.remaining -= read as u64;
        Ok(read)
    }
}

struct LimitedWriter<W> {
    inner: W,
    written: u64,
    limit: u64,
}

impl<W: Write> Write for LimitedWriter<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() as u64 > self.limit - self.written {
            return Err(capacity_error(self.limit));
        }
        let written = self.inner.write(bytes)?;
        self.written += written as u64;
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

pub(super) fn load<T: DeserializeOwned>(path: &Path) -> io::Result<T> {
    load_with_limit(path, MAX_BYTES)
}

fn load_with_limit<T: DeserializeOwned>(path: &Path, limit: u64) -> io::Result<T> {
    let file = File::open(path)?;
    if file.metadata()?.len() > limit {
        return Err(capacity_error(limit));
    }
    let reader = BufReader::new(LimitedReader {
        inner: file,
        remaining: limit,
        limit,
    });
    serde_json::from_reader(reader).map_err(io::Error::other)
}

pub(super) fn save<T: Serialize>(path: &Path, value: &T) -> io::Result<()> {
    save_with_limit(path, value, MAX_BYTES)
}

fn save_with_limit<T: Serialize>(path: &Path, value: &T, limit: u64) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent)?;
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    let temp = parent.join(format!(
        ".cmqttd-{}-{}.tmp",
        std::process::id(),
        SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut created = false;
    let result = (|| {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(&temp)?;
        created = true;
        let mut writer = BufWriter::new(LimitedWriter {
            inner: file,
            written: 0,
            limit,
        });
        serde_json::to_writer(&mut writer, value).map_err(io::Error::other)?;
        writer.flush()?;
        writer.get_ref().inner.sync_all()?;
        // Opening the directory before rename makes an invalid parent fail
        // before replacing the image. A post-rename sync error, as previously,
        // is an uncertain durability boundary and is not safe to replay.
        #[cfg(unix)]
        let directory = File::open(parent)?;
        std::fs::rename(&temp, path)?;
        #[cfg(unix)]
        directory.sync_all()?;
        Ok(())
    })();
    if result.is_err() && created {
        let _ = std::fs::remove_file(temp);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn directory() -> std::path::PathBuf {
        static SEQUENCE: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "cbus-repository-stream-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn exact_encoded_limit_is_accepted_and_overflow_preserves_previous_image() {
        let directory = directory();
        let path = directory.join("state.json");
        let old = json!({"saved": "old"});
        save(&path, &old).unwrap();
        let baseline = std::fs::read(&path).unwrap();
        let value = json!({"unicode": "é\n\""});
        let bytes = serde_json::to_vec(&value).unwrap();
        assert!(save_with_limit(&path, &value, bytes.len() as u64 - 1).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), baseline);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        save_with_limit(&path, &value, bytes.len() as u64).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        let loaded: serde_json::Value = load_with_limit(&path, bytes.len() as u64).unwrap();
        assert_eq!(loaded, value);
        assert!(load_with_limit::<serde_json::Value>(&path, bytes.len() as u64 - 1).is_err());
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn reader_rejects_growth_past_limit_including_trailing_whitespace() {
        let mut reader = LimitedReader {
            inner: io::Cursor::new(b"{} "),
            remaining: 2,
            limit: 2,
        };
        assert!(serde_json::from_reader::<_, serde_json::Value>(&mut reader).is_err());
        let mut reader = LimitedReader {
            inner: io::Cursor::new(b"{}"),
            remaining: 2,
            limit: 2,
        };
        assert_eq!(
            serde_json::from_reader::<_, serde_json::Value>(&mut reader).unwrap(),
            json!({})
        );
    }

    #[test]
    fn malformed_or_trailing_json_is_never_reset_or_replaced() {
        let directory = directory();
        let path = directory.join("state.json");
        for bytes in [br#"{"version":1"#.as_slice(), b"{} {}", b"not-json"] {
            std::fs::write(&path, bytes).unwrap();
            assert!(load::<serde_json::Value>(&path).is_err());
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
        }
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn rename_failure_cleans_temp_without_destroying_previous_destination() {
        let directory = directory();
        let path = directory.join("destination");
        std::fs::create_dir(&path).unwrap();
        std::fs::write(path.join("retained"), b"old").unwrap();
        assert!(save(&path, &json!({"new": true})).is_err());
        assert_eq!(std::fs::read(path.join("retained")).unwrap(), b"old");
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn committed_repository_keeps_owner_only_permissions() {
        use std::os::unix::fs::PermissionsExt;
        let directory = directory();
        let path = directory.join("state.json");
        save(&path, &json!({})).unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        std::fs::remove_dir_all(directory).unwrap();
    }
}
