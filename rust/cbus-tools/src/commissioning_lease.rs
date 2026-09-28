//! Host-local advisory lease shared with Python selected-serial commissioning.
//!
//! The Python coordinator uses `/tmp/cbus-toolkit-selected-serial-UID` on
//! POSIX (the process temp directory on Windows) and a SHA-256 digest of
//! `host + NUL + decimal-port` as its lock filename. Keep that namespace and
//! a nonblocking OS file lock so the two CLIs cannot commission the same
//! endpoint concurrently when both cooperate. This does not exclude cmqttd,
//! another host, or a controller that ignores the lease. The OS drops the
//! lock on process death; a durable apply journal still forbids replay.

use ring::digest::{digest, SHA256};
use std::fs::{self, File, OpenOptions};
use std::io::ErrorKind;
use std::path::PathBuf;

#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};

pub struct EndpointLease {
    _file: File,
}

impl EndpointLease {
    /// Refuse immediately if a cooperating process owns this endpoint.
    pub fn acquire(host: &str, port: u16) -> Result<Self, String> {
        if host.is_empty() || port == 0 {
            return Err("a validated nonempty endpoint and nonzero port are required".into());
        }
        let path = lease_path(host, port)?;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true);
        #[cfg(unix)]
        {
            options
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
        }
        let file = options
            .open(&path)
            .map_err(|error| format!("cannot open {}: {error}", path.display()))?;
        check_private_file(&file)?;
        #[cfg(windows)]
        if file.metadata().map_err(|error| error.to_string())?.len() == 0 {
            // Python's msvcrt.locking reserves byte zero, including on an
            // otherwise empty lease file.
            file.set_len(1)
                .map_err(|error| format!("cannot initialize {}: {error}", path.display()))?;
        }
        file.try_lock().map_err(|error| match error {
            fs::TryLockError::WouldBlock => {
                "another process is commissioning this endpoint".to_string()
            }
            fs::TryLockError::Error(error) if error.kind() == ErrorKind::PermissionDenied => {
                "another process is commissioning this endpoint".to_string()
            }
            fs::TryLockError::Error(error) => {
                format!("cannot lock {}: {error}", path.display())
            }
        })?;
        #[cfg(unix)]
        {
            // A replacement between open and lock must not create a second
            // lock inode for the same endpoint namespace.
            let held = file.metadata().map_err(|error| error.to_string())?;
            let named = fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
            if held.dev() != named.dev() || held.ino() != named.ino() {
                return Err("commissioning lease path changed during acquisition".into());
            }
        }
        Ok(Self { _file: file })
    }
}

fn lease_path(host: &str, port: u16) -> Result<PathBuf, String> {
    let key = format!("{host}\0{port}");
    let name = format!(
        "{}.lock",
        hex::encode(digest(&SHA256, key.as_bytes()).as_ref())
    );
    Ok(lease_directory()?.join(name))
}

fn lease_directory() -> Result<PathBuf, String> {
    #[cfg(unix)]
    let path = PathBuf::from("/tmp").join(format!(
        "cbus-toolkit-selected-serial-{}",
        // Match Python os.getuid(), rather than effective uid or TMPDIR.
        unsafe { libc::getuid() }
    ));
    #[cfg(not(unix))]
    let path = std::env::temp_dir().join("cbus-toolkit-selected-serial-current-user");

    #[cfg(unix)]
    let created = fs::DirBuilder::new().mode(0o700).create(&path);
    #[cfg(not(unix))]
    let created = fs::create_dir(&path);
    match created {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
        Err(error) => return Err(format!("cannot create {}: {error}", path.display())),
    }
    let metadata = fs::symlink_metadata(&path)
        .map_err(|error| format!("cannot inspect {}: {error}", path.display()))?;
    if !metadata.is_dir() {
        return Err("commissioning lease directory is not a directory".into());
    }
    #[cfg(unix)]
    if metadata.uid() != unsafe { libc::getuid() } || metadata.mode() & 0o077 != 0 {
        return Err("commissioning lease directory is not private to this user".into());
    }
    Ok(path)
}

fn check_private_file(file: &File) -> Result<(), String> {
    let metadata = file
        .metadata()
        .map_err(|error| format!("cannot inspect commissioning lease file: {error}"))?;
    if !metadata.is_file() {
        return Err("commissioning lease file is not a regular file".into());
    }
    #[cfg(unix)]
    if metadata.uid() != unsafe { libc::getuid() } || metadata.mode() & 0o077 != 0 {
        return Err("commissioning lease file is not private to this user".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    use std::os::fd::AsRawFd;

    #[test]
    fn lease_path_matches_python_coordinator_key() {
        let path = lease_path("127.0.0.1", 10001).unwrap();
        assert_eq!(
            path.file_name().unwrap().to_string_lossy(),
            "b92015b9b84faaac4ab017d815e0cf27a84c0eb588e7a45830e42e907b85f833.lock"
        );
    }

    #[test]
    fn second_open_refuses_until_first_lease_drops() {
        let endpoint = format!("127.0.0.1-{}", std::process::id());
        let first = EndpointLease::acquire(&endpoint, 10001).unwrap();
        let error = EndpointLease::acquire(&endpoint, 10001).err().unwrap();
        assert!(
            error.contains("another process is commissioning"),
            "{error}"
        );
        drop(first);
        EndpointLease::acquire(&endpoint, 10001).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn python_style_flock_blocks_rust_lease() {
        let endpoint = format!("127.0.0.2-{}", std::process::id());
        EndpointLease::acquire(&endpoint, 10001).unwrap();
        let path = lease_path(&endpoint, 10001).unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .unwrap();
        // Python fcntl.flock(LOCK_EX | LOCK_NB) uses this same OS operation.
        assert_eq!(
            unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
            0
        );
        let error = EndpointLease::acquire(&endpoint, 10001).err().unwrap();
        assert!(
            error.contains("another process is commissioning"),
            "{error}"
        );
        drop(file);
        EndpointLease::acquire(&endpoint, 10001).unwrap();
    }
}
