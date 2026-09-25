//! Durable recovery-journal primitive for selected-serial commissioning.
//!
//! Mirrors the Python oracle `_Journal`
//! (`toolkit-cli/src/cbus_toolkit/pci_selected_serial.py`, ~lines 282-372)
//! plus the `_json` write bound (`MAX_JOURNAL_BYTES` 16 MiB):
//!
//! * Exclusive initial creation (`O_CREAT | O_EXCL`, mode `0600`); later
//!   writes only via temp-file + fsync + atomic rename after re-reading the
//!   current bytes (external-change detection fails instead of overwriting).
//! * `fsync` of the file descriptor after every write; `fsync` of the parent
//!   directory after both create and replace.
//! * Per-phase evidence mirroring the oracle `last_update` vocabulary:
//!   `initial_creation`, `file_synced`, `replacement_attempted`,
//!   `replacement_completed`, `directory_synced`, `disk_matches_proposed`,
//!   plus `probe_error`, `cleanup_errors`, and the journal-level `failed`
//!   flag.
//! * Bounded guarded reads (16 MiB + 1); symlinks and non-regular files are
//!   refused (`O_NOFOLLOW`); a substituted FIFO can never block the reader
//!   (`O_NONBLOCK` plus a pre-open file-type check).
//! * Python-compatible finite-JSON encoding: sorted keys, compact separators,
//!   ASCII escapes and float formatting. Values outside `serde_json::Value`'s
//!   representable number range, or beyond the size/depth bounds, are rejected
//!   before any I/O is attempted.
//!
//! A failed directory sync leaves the new record visible without proving
//! crash durability: the journal reports that distinction via
//! [`LastUpdate::directory_synced`] `== false` with [`RecoveryJournal::failed`]
//! `== true`. The caller must STOP before any bus request in that state.
//! Bus-request gating itself belongs to the later apply slice, not here.
//!
//! Scope: standalone primitive only. No plan/inventory/serial reuse, no
//! apply/verify orchestration, no PCI, no clock reads. Only the filesystem
//! under the journal path is touched.
//!
//! Portability notes (oracle parity boundaries): close-failure bookkeeping
//! inside `_read_current` / `_write_descriptor` / `_sync_directory` has no
//! Rust equivalent because `File` close-on-drop cannot report errors, unlike
//! the oracle which appends to `cleanup_errors`. Only temp-file cleanup
//! failures are recorded here. `serde_json::Value` cannot hold NaN,
//! infinities, or reference cycles (its float constructors coerce
//! non-finite inputs), so the finite/nesting walk is defense-in-depth
//! mirroring `allow_nan=False` and the oracle nesting guard. Atomic replacement
//! uses the host `rename` contract; the currently verified implementation is
//! macOS/Linux. The fallback reader on other hosts performs pre-open type
//! checks but cannot provide the same `O_NOFOLLOW` race guarantee.

use serde_json::Value;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

/// On-disk size bound, mirroring `MAX_JOURNAL_BYTES` (16 MiB).
pub const MAX_JOURNAL_BYTES: usize = 16 * 1024 * 1024;

/// Maximum JSON nesting depth accepted at write, mirroring the oracle
/// `MAX_JSON_DEPTH` (127) rejection for unencodable recovery evidence.
pub const MAX_JOURNAL_DEPTH: usize = 127;

/// Machine-stable failure class for every journal rejection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JournalError {
    reason: &'static str,
    message: String,
}

impl JournalError {
    fn new(reason: &'static str, message: impl Into<String>) -> Self {
        Self {
            reason,
            message: message.into(),
        }
    }

    /// Machine-stable failure class (`oversize`, `unencodable_value`,
    /// `exclusive_exists`, `external_change`, `symlink_refused`,
    /// `not_regular_file`, `journal_too_large`, `not_found`, `io_error`,
    /// `directory_sync_failed`).
    pub fn reason(&self) -> &'static str {
        self.reason
    }

    /// Human-readable detail.
    pub fn message(&self) -> &str {
        &self.message
    }

    fn io(context: &str, error: &std::io::Error) -> Self {
        Self::new("io_error", format!("{context}: {error}"))
    }

    fn exclusive_exists() -> Self {
        Self::new(
            "exclusive_exists",
            "Recovery journal already exists; exclusive creation refused",
        )
    }

    fn external_changed() -> Self {
        Self::new(
            "external_change",
            "Recovery journal changed outside this exclusive writer",
        )
    }
}

impl fmt::Display for JournalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.reason, self.message)
    }
}

impl std::error::Error for JournalError {}

/// Cleanup failure attached to [`LastUpdate::cleanup_errors`], mirroring the
/// oracle `{'type': ..., 'message': ...}` entries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CleanupError {
    /// Error type name.
    pub kind: String,
    /// Human-readable detail.
    pub message: String,
}

/// Read probe failure attached to [`LastUpdate::probe_error`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProbeError {
    /// Error type name.
    pub kind: String,
    /// Human-readable detail.
    pub message: String,
}

/// Per-write evidence mirroring the oracle `last_update` vocabulary.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct LastUpdate {
    /// True when this write attempted the exclusive initial creation.
    pub initial_creation: bool,
    /// True once the file descriptor was written and fsynced.
    pub file_synced: bool,
    /// True once a replacement temp file was installed via atomic rename
    /// (attempted; see `replacement_completed`).
    pub replacement_attempted: bool,
    /// True once the atomic rename completed.
    pub replacement_completed: bool,
    /// True once the parent directory was fsynced. False after a directory
    /// sync failure: the record may be visible without proven crash
    /// durability — STOP before any bus request.
    pub directory_synced: bool,
    /// Whether the bytes on disk match the proposed record after the write
    /// (or after the failure probe). `None` when the probe itself failed.
    pub disk_matches_proposed: Option<bool>,
    /// The probe failure, when `disk_matches_proposed` is `None`.
    pub probe_error: Option<ProbeError>,
    /// Temp-file cleanup failures (close-failure bookkeeping has no Rust
    /// equivalent; see the module docs).
    pub cleanup_errors: Vec<CleanupError>,
}

/// Durable recovery journal: exclusive create, checked atomic replacements,
/// fsync, and bounded guarded reads.
#[derive(Debug)]
pub struct RecoveryJournal {
    path: PathBuf,
    expected: Option<Vec<u8>>,
    failed: bool,
    last_update: LastUpdate,
}

impl RecoveryJournal {
    /// Create a journal handle for `path` (stored absolute, like the
    /// oracle). No journal-file I/O is performed until
    /// [`RecoveryJournal::write`]. Resolving a relative path fails closed if
    /// the process working directory is unavailable.
    pub fn new(path: impl AsRef<Path>) -> Result<Self, JournalError> {
        let path = path.as_ref();
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|error| {
                    JournalError::io("Recovery journal path resolution failed", &error)
                })?
                .join(path)
        };
        Ok(Self {
            path: absolute,
            expected: None,
            failed: false,
            last_update: LastUpdate::default(),
        })
    }

    /// The absolute journal path.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// True once any update has failed (encode failures excluded: like the
    /// oracle, a value rejected before I/O leaves this flag untouched).
    pub fn failed(&self) -> bool {
        self.failed
    }

    /// Evidence from the most recent write attempt.
    pub fn last_update(&self) -> &LastUpdate {
        &self.last_update
    }

    /// Re-read the current journal bytes with bounds and file-type guards.
    /// macOS/Linux enforce no-follow at open; every host rejects a path that
    /// is already a symlink or non-regular file during its metadata check.
    pub fn read_current(&self) -> Result<Vec<u8>, JournalError> {
        guarded_read(&self.path)
    }

    /// Durably record `value`, mirroring `_Journal.write` exactly:
    /// exclusive creation first, then checked atomic replacements.
    pub fn write(&mut self, value: &Value) -> Result<(), JournalError> {
        // Finite-JSON encoding happens before any state is touched: like the
        // oracle, a rejected value leaves `failed` and `last_update` alone.
        let raw = encode_value(value)?;
        let initial = self.expected.is_none();
        let mut state = LastUpdate {
            initial_creation: initial,
            ..LastUpdate::default()
        };
        self.last_update = state.clone();
        let mut temp_path: Option<PathBuf> = None;
        let outcome = if initial {
            exclusive_create(&self.path, &raw).map(|()| {
                state.file_synced = true;
                self.last_update = state.clone();
            })
        } else {
            self.checked_replace(&raw, &mut state, &mut temp_path)
        }
        .and_then(|()| {
            sync_parent_dir(&self.path)?;
            state.directory_synced = true;
            self.expected = Some(raw.clone());
            state.disk_matches_proposed = Some(true);
            self.last_update = state.clone();
            Ok(())
        });
        match outcome {
            Ok(()) => Ok(()),
            Err(error) => {
                self.failed = true;
                match guarded_read(&self.path) {
                    Ok(current) => state.disk_matches_proposed = Some(current == raw),
                    Err(probe) if probe.reason() == "not_found" => {
                        state.disk_matches_proposed = Some(false);
                    }
                    Err(probe) => {
                        state.disk_matches_proposed = None;
                        state.probe_error = Some(ProbeError {
                            kind: "JournalError".to_string(),
                            message: probe.to_string(),
                        });
                    }
                }
                self.last_update = state.clone();
                if let Some(temp) = temp_path {
                    if let Err(cleanup) = fs::remove_file(&temp) {
                        state.cleanup_errors.push(CleanupError {
                            kind: "IoError".to_string(),
                            message: cleanup.to_string(),
                        });
                        self.last_update = state.clone();
                    }
                }
                Err(error)
            }
        }
    }

    /// Replacement path: re-read current bytes, refuse external changes,
    /// then install via temp-file + fsync + atomic rename.
    fn checked_replace(
        &mut self,
        raw: &[u8],
        state: &mut LastUpdate,
        temp_path: &mut Option<PathBuf>,
    ) -> Result<(), JournalError> {
        let current = guarded_read(&self.path)?;
        if Some(&current) != self.expected.as_ref() {
            return Err(JournalError::external_changed());
        }
        let temp = create_temp_sibling(&self.path, raw, state)?;
        *temp_path = Some(temp);
        state.file_synced = true;
        state.replacement_attempted = true;
        self.last_update = state.clone();
        fs::rename(
            temp_path.as_ref().expect("temp path was just installed"),
            &self.path,
        )
        .map_err(|error| JournalError::io("Atomic journal replacement failed", &error))?;
        *temp_path = None;
        state.replacement_completed = true;
        self.last_update = state.clone();
        Ok(())
    }
}

/// Python-compatible finite-JSON encoding with the journal size bound,
/// mirroring `_json` (`ensure_ascii=True`, `sort_keys=True`, compact
/// separators, `allow_nan=False`) plus the trailing newline the oracle appends
/// before writing.
fn encode_value(value: &Value) -> Result<Vec<u8>, JournalError> {
    check_depth(value)?;
    check_finite(value)?;
    // The Python oracle bounds `_json` to MAX_JOURNAL_BYTES - 1 before adding
    // the newline. Keep the writer bounded while it runs so an attacker cannot
    // make a small journal operation allocate an unbounded encoded buffer.
    let mut writer = CanonicalWriter::default();
    writer.write_value(value)?;
    writer.output.push(b'\n');
    Ok(writer.output)
}

#[derive(Default)]
struct CanonicalWriter {
    output: Vec<u8>,
}

impl CanonicalWriter {
    const PAYLOAD_LIMIT: usize = MAX_JOURNAL_BYTES - 1;

    fn oversize() -> JournalError {
        JournalError::new("oversize", "Recovery evidence exceeds its size bound")
    }

    fn push_byte(&mut self, byte: u8) -> Result<(), JournalError> {
        if self.output.len() == Self::PAYLOAD_LIMIT {
            return Err(Self::oversize());
        }
        self.output.push(byte);
        Ok(())
    }

    fn push_ascii(&mut self, text: &str) -> Result<(), JournalError> {
        debug_assert!(text.is_ascii());
        if text.len() > Self::PAYLOAD_LIMIT.saturating_sub(self.output.len()) {
            return Err(Self::oversize());
        }
        self.output.extend_from_slice(text.as_bytes());
        Ok(())
    }

    fn write_value(&mut self, value: &Value) -> Result<(), JournalError> {
        match value {
            Value::Null => self.push_ascii("null"),
            Value::Bool(true) => self.push_ascii("true"),
            Value::Bool(false) => self.push_ascii("false"),
            Value::Number(number) => {
                if number.is_i64() {
                    self.push_ascii(
                        &number
                            .as_i64()
                            .expect("is_i64 guaranteed an i64")
                            .to_string(),
                    )
                } else if number.is_u64() {
                    self.push_ascii(
                        &number
                            .as_u64()
                            .expect("is_u64 guaranteed a u64")
                            .to_string(),
                    )
                } else if number.is_f64() {
                    let value = number.as_f64().ok_or_else(unencodable_value)?;
                    if !value.is_finite() {
                        return Err(unencodable_value());
                    }
                    self.push_ascii(&python_float(value))
                } else {
                    // This can only arise if another crate unifies
                    // serde_json's arbitrary_precision feature and supplies a
                    // number outside Value's documented i64/u64/f64 scope.
                    Err(unencodable_value())
                }
            }
            Value::String(text) => self.write_string(text),
            Value::Array(items) => {
                self.push_byte(b'[')?;
                for (index, item) in items.iter().enumerate() {
                    if index != 0 {
                        self.push_byte(b',')?;
                    }
                    self.write_value(item)?;
                }
                self.push_byte(b']')
            }
            Value::Object(fields) => {
                self.push_byte(b'{')?;
                // Python sorts Unicode keys by scalar value. UTF-8 preserves
                // scalar ordering, so Rust's string ordering is identical for
                // every valid Value key.
                let mut keys: Vec<_> = fields.keys().collect();
                keys.sort_unstable();
                for (index, key) in keys.into_iter().enumerate() {
                    if index != 0 {
                        self.push_byte(b',')?;
                    }
                    self.write_string(key)?;
                    self.push_byte(b':')?;
                    self.write_value(&fields[key])?;
                }
                self.push_byte(b'}')
            }
        }
    }

    /// Match `json.dumps(..., ensure_ascii=True)` string escaping. JSON's five
    /// named control escapes are used, other controls and all non-ASCII code
    /// points use lower-case `\u` escapes, and supplementary characters use a
    /// UTF-16 surrogate pair.
    fn write_string(&mut self, text: &str) -> Result<(), JournalError> {
        self.push_byte(b'"')?;
        for character in text.chars() {
            match character {
                '"' => self.push_ascii("\\\"")?,
                '\\' => self.push_ascii("\\\\")?,
                '\u{0008}' => self.push_ascii("\\b")?,
                '\t' => self.push_ascii("\\t")?,
                '\n' => self.push_ascii("\\n")?,
                '\u{000c}' => self.push_ascii("\\f")?,
                '\r' => self.push_ascii("\\r")?,
                '\u{0020}'..='\u{007e}' => self.push_byte(character as u8)?,
                character if (character as u32) <= 0xffff => {
                    self.push_unicode_escape(character as u16)?;
                }
                character => {
                    let codepoint = character as u32 - 0x1_0000;
                    self.push_unicode_escape(0xd800 | ((codepoint >> 10) as u16))?;
                    self.push_unicode_escape(0xdc00 | ((codepoint & 0x03ff) as u16))?;
                }
            }
        }
        self.push_byte(b'"')
    }

    fn push_unicode_escape(&mut self, code_unit: u16) -> Result<(), JournalError> {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let escaped = [
            b'\\',
            b'u',
            HEX[((code_unit >> 12) & 0x0f) as usize],
            HEX[((code_unit >> 8) & 0x0f) as usize],
            HEX[((code_unit >> 4) & 0x0f) as usize],
            HEX[(code_unit & 0x0f) as usize],
        ];
        if escaped.len() > Self::PAYLOAD_LIMIT.saturating_sub(self.output.len()) {
            return Err(Self::oversize());
        }
        self.output.extend_from_slice(&escaped);
        Ok(())
    }
}

fn unencodable_value() -> JournalError {
    JournalError::new(
        "unencodable_value",
        "Recovery evidence must be finite JSON data",
    )
}

/// Adapt serde_json's shortest-roundtrip float representation to CPython's
/// representation used by `json.dumps`:
///
/// * CPython uses scientific notation below `1e-4`; zmij/ryu keeps decimal
///   exponent -5 in fixed notation.
/// * CPython pads a one-digit exponent with a leading zero.
fn python_float(value: f64) -> String {
    debug_assert!(value.is_finite());
    let rendered = serde_json::Number::from_f64(value)
        .expect("finite f64 must be representable")
        .to_string();
    if let Some(exponent_index) = rendered.find('e') {
        return pad_python_exponent(&rendered, exponent_index);
    }

    let (sign, unsigned) = rendered
        .strip_prefix('-')
        .map_or(("", rendered.as_str()), |unsigned| ("-", unsigned));
    let Some(fraction) = unsigned.strip_prefix("0.") else {
        return rendered;
    };
    let leading_zeroes = fraction.bytes().take_while(|byte| *byte == b'0').count();
    if leading_zeroes < 4 || leading_zeroes == fraction.len() {
        return rendered;
    }

    let significant = &fraction[leading_zeroes..];
    let exponent = leading_zeroes + 1;
    if significant.len() == 1 {
        format!("{sign}{significant}e-{exponent:02}")
    } else {
        format!(
            "{sign}{}.{}e-{exponent:02}",
            &significant[..1],
            &significant[1..]
        )
    }
}

fn pad_python_exponent(rendered: &str, exponent_index: usize) -> String {
    let mantissa = &rendered[..exponent_index];
    let exponent = &rendered[exponent_index + 1..];
    let (sign, magnitude) = exponent.strip_prefix('-').map_or_else(
        || {
            exponent
                .strip_prefix('+')
                .map_or(("+", exponent), |value| ("+", value))
        },
        |value| ("-", value),
    );
    if magnitude.len() >= 2 {
        format!("{mantissa}e{sign}{magnitude}")
    } else {
        format!("{mantissa}e{sign}0{magnitude}")
    }
}

/// Reject nesting deeper than [`MAX_JOURNAL_DEPTH`], mirroring the oracle
/// `RecursionError` rejection. Iterative so the guard itself cannot overflow.
fn check_depth(value: &Value) -> Result<(), JournalError> {
    let mut stack: Vec<(&Value, usize)> = vec![(value, 0)];
    while let Some((node, depth)) = stack.pop() {
        match node {
            Value::Array(items) => {
                let depth = depth + 1;
                if depth > MAX_JOURNAL_DEPTH {
                    return Err(unencodable_value());
                }
                stack.extend(items.iter().map(|item| (item, depth)));
            }
            Value::Object(fields) => {
                let depth = depth + 1;
                if depth > MAX_JOURNAL_DEPTH {
                    return Err(unencodable_value());
                }
                stack.extend(fields.values().map(|item| (item, depth)));
            }
            _ => {}
        }
    }
    Ok(())
}

/// Reject non-finite numbers, mirroring `allow_nan=False`. `serde_json`
/// constructors coerce non-finite `f64`s, so this is defense-in-depth.
fn check_finite(value: &Value) -> Result<(), JournalError> {
    let mut stack = vec![value];
    while let Some(node) = stack.pop() {
        match node {
            Value::Number(number) => {
                if number.as_f64().is_none_or(|n| !n.is_finite()) {
                    return Err(unencodable_value());
                }
            }
            Value::Array(items) => stack.extend(items.iter()),
            Value::Object(fields) => stack.extend(fields.values()),
            _ => {}
        }
    }
    Ok(())
}

/// Bounded guarded read mirroring `_read_current`: refuse symlinks and
/// non-regular files, never block on a FIFO, enforce the size bound.
fn guarded_read(path: &Path) -> Result<Vec<u8>, JournalError> {
    let file_type = fs::symlink_metadata(path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                JournalError::new("not_found", format!("Recovery journal is missing: {error}"))
            } else {
                JournalError::io("Recovery journal metadata read failed", &error)
            }
        })?
        .file_type();
    if file_type.is_symlink() {
        return Err(JournalError::new(
            "symlink_refused",
            "Recovery journal is not a regular file",
        ));
    }
    if !file_type.is_file() {
        // Directories, FIFOs, sockets: never opened, so a substituted FIFO
        // can never block the reader.
        return Err(JournalError::new(
            "not_regular_file",
            "Recovery journal is not a regular file",
        ));
    }
    let file = open_nofollow_nonblock(path)?;
    if !file
        .metadata()
        .map_err(|error| JournalError::io("Recovery journal metadata read failed", &error))?
        .is_file()
    {
        return Err(JournalError::new(
            "not_regular_file",
            "Recovery journal is not a regular file",
        ));
    }
    let mut raw = Vec::new();
    file.take(MAX_JOURNAL_BYTES as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|error| JournalError::io("Recovery journal read failed", &error))?;
    if raw.len() > MAX_JOURNAL_BYTES {
        return Err(JournalError::new(
            "journal_too_large",
            "Recovery journal exceeds its size bound",
        ));
    }
    Ok(raw)
}

/// Open for reading with `O_NOFOLLOW | O_NONBLOCK` on Unix so a symlinked or
/// FIFO-substituted path cannot escape the guards (a symlink races to
/// `ELOOP`, a FIFO opens without blocking and is rejected by `fstat`).
#[cfg(any(target_os = "macos", target_os = "linux"))]
fn open_nofollow_nonblock(path: &Path) -> Result<File, JournalError> {
    use std::os::unix::fs::OpenOptionsExt;
    #[cfg(target_os = "macos")]
    const FLAGS: i32 = 0x4 | 0x100; // O_NONBLOCK | O_NOFOLLOW
    #[cfg(target_os = "linux")]
    const FLAGS: i32 = 0o4000 | 0o400000; // O_NONBLOCK | O_NOFOLLOW
    match OpenOptions::new().read(true).custom_flags(FLAGS).open(path) {
        Ok(file) => Ok(file),
        Err(error) if error.raw_os_error() == Some(ELOOP) => Err(JournalError::new(
            "symlink_refused",
            "Recovery journal is not a regular file",
        )),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Err(JournalError::new(
            "not_found",
            format!("Recovery journal is missing: {error}"),
        )),
        Err(error) => Err(JournalError::io("Recovery journal open failed", &error)),
    }
}

/// Fallback for non-macOS/Linux Unix without `O_NOFOLLOW`/`O_NONBLOCK`:
/// the pre-open type checks still refuse symlinks and FIFOs, but a swap
/// between the check and the open leaves a residual TOCTOU window
/// (documented, accepted); the macOS/Linux path above is immune.
#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn open_nofollow_nonblock(path: &Path) -> Result<File, JournalError> {
    match File::open(path) {
        Ok(file) => Ok(file),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Err(JournalError::new(
            "not_found",
            format!("Recovery journal is missing: {error}"),
        )),
        Err(error) => Err(JournalError::io("Recovery journal open failed", &error)),
    }
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
#[cfg(target_os = "macos")]
const ELOOP: i32 = 62;
#[cfg(any(target_os = "macos", target_os = "linux"))]
#[cfg(target_os = "linux")]
const ELOOP: i32 = 40;

/// Exclusive initial creation (`O_CREAT | O_EXCL`, mode `0600`) followed by
/// write + `fsync`, mirroring the oracle create path.
fn exclusive_create(path: &Path, raw: &[u8]) -> Result<(), JournalError> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = match options.open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            return Err(JournalError::exclusive_exists());
        }
        Err(error) => {
            return Err(JournalError::io(
                "Recovery journal exclusive creation failed",
                &error,
            ));
        }
    };
    file.write_all(raw)
        .map_err(|error| JournalError::io("Recovery journal write failed", &error))?;
    file.sync_all()
        .map_err(|error| JournalError::io("Recovery journal file sync failed", &error))?;
    Ok(())
}

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

/// Write `raw` to a uniquely named sibling temp file and `fsync` it,
/// mirroring `tempfile.mkstemp` in the journal parent directory.
/// Predictable temp names are DoS-only under the directory owner (no
/// leak/overwrite: `create_new` + `0600`).
fn create_temp_sibling(
    path: &Path,
    raw: &[u8],
    state: &mut LastUpdate,
) -> Result<PathBuf, JournalError> {
    let parent = path.parent().ok_or_else(|| {
        JournalError::new("io_error", "Recovery journal path has no parent directory")
    })?;
    let name = path
        .file_name()
        .ok_or_else(|| JournalError::new("io_error", "Recovery journal path has no file name"))?;
    for _ in 0..100 {
        let unique = TEMP_COUNTER.fetch_add(1, Ordering::SeqCst);
        let temp = parent.join(format!(
            ".{}.{}.{}.tmp",
            name.to_string_lossy(),
            std::process::id(),
            unique
        ));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = match options.open(&temp) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(JournalError::io(
                    "Recovery journal temp file creation failed",
                    &error,
                ));
            }
        };
        let outcome = write_and_sync(file, raw);
        if outcome.is_ok() {
            return Ok(temp);
        }
        if let Err(cleanup) = fs::remove_file(&temp) {
            state.cleanup_errors.push(CleanupError {
                kind: "IoError".to_string(),
                message: cleanup.to_string(),
            });
        }
        return outcome.map(|()| temp);
    }
    Err(JournalError::new(
        "io_error",
        "Recovery journal temp file creation failed: no unique name",
    ))
}

fn write_and_sync(mut file: File, raw: &[u8]) -> Result<(), JournalError> {
    file.write_all(raw)
        .map_err(|error| JournalError::io("Recovery journal write failed", &error))?;
    file.sync_all()
        .map_err(|error| JournalError::io("Recovery journal file sync failed", &error))?;
    Ok(())
}

/// `fsync` the journal parent directory after create and replace. A failure
/// here reports `directory_sync_failed`: the record may be visible without
/// proven crash durability, so the caller must STOP before any bus request.
fn sync_parent_dir(path: &Path) -> Result<(), JournalError> {
    let parent = path.parent().ok_or_else(|| {
        JournalError::new("io_error", "Recovery journal path has no parent directory")
    })?;
    let directory = File::open(parent).map_err(|error| {
        JournalError::new(
            "directory_sync_failed",
            format!("Recovery journal directory sync failed: {error}"),
        )
    })?;
    directory.sync_all().map_err(|error| {
        JournalError::new(
            "directory_sync_failed",
            format!("Recovery journal directory sync failed: {error}"),
        )
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finite_walk_accepts_plain_values() {
        assert!(encode_value(&serde_json::json!({"a": [1, 2.5, "x", true, null]})).is_ok());
    }

    #[test]
    fn canonical_encoding_matches_python_unicode_and_float_rules() {
        let value = serde_json::json!({
            "é": "é",
            "😀": "😀",
            "small": 1e-5,
            "scientific": 1e-6,
            "large": 1e16,
            "negative_zero": -0.0,
            "control": "\u{0000}\u{001f}\u{007f}\n\"\\/",
        });
        let expected = concat!(
            r#"{"control":"\u0000\u001f\u007f\n\"\\/","large":1e+16,"negative_zero":-0.0,"scientific":1e-06,"small":1e-05,"\u00e9":"\u00e9","\ud83d\ude00":"\ud83d\ude00"}"#,
            "\n"
        );
        assert_eq!(encode_value(&value).unwrap(), expected.as_bytes());
    }

    #[test]
    fn depth_guard_counts_empty_containers_at_the_boundary() {
        let mut accepted = Value::Array(Vec::new());
        for _ in 1..MAX_JOURNAL_DEPTH {
            accepted = Value::Array(vec![accepted]);
        }
        assert!(encode_value(&accepted).is_ok());

        let mut rejected = Value::Array(Vec::new());
        for _ in 0..MAX_JOURNAL_DEPTH {
            rejected = Value::Array(vec![rejected]);
        }
        assert_eq!(
            encode_value(&rejected).unwrap_err().reason(),
            "unencodable_value"
        );
    }
}
