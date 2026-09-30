//! Durable journal for DALI commissioning operations that change devices.
//!
//! Typed `DALI SESSION DEPLOY DALI_ONLY`/`FULL` writes ECG parameters and
//! gateway extended memory one exchange at a time, and the conditional
//! extraction selectors send `ADDRESS_UNKNOWN`, which lets the gateway assign
//! DALI short addresses. Native C-Gate 3.4 has no rollback for either: a
//! fault leaves every earlier write in place. Before the first such exchange
//! the service exclusively creates and fsyncs one record naming the complete
//! planned write sequence (the transport crate's [`RecoveryJournal`], also
//! used by the physical move journal). The record is conservative from
//! creation: `send_may_have_occurred` is already true. It is replaced
//! atomically after each confirmed write and on the terminal outcome, so
//! after a crash `planned[confirmed_writes]` is the one exchange whose
//! outcome is unknown and every later entry was never sent.
//!
//! The record is evidence for the operator. It does not block later
//! commissioning, and nothing in this module ever resumes or replays a plan.

use super::*;
use cbus_transport::journal::RecoveryJournal;
use std::ffi::OsString;
use std::path::PathBuf;

pub(super) const DALI_JOURNAL_FORMAT: &str = "cmqttd-dali-commissioning-journal-v1";
/// Finished records retained per state directory. Incomplete records are
/// never pruned.
const RETAINED_FINISHED: usize = 32;
const MAX_JOURNAL_FILES: usize = 4096;

/// `<state file name>.dali-journal`, beside the durable C-Gate database.
pub(super) fn journal_directory(state_path: &Path) -> PathBuf {
    let mut name = state_path
        .file_name()
        .map(OsString::from)
        .unwrap_or_else(|| OsString::from("cgate"));
    name.push(".dali-journal");
    state_path.with_file_name(name)
}

/// One planned device-changing exchange, in execution order.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct DaliJournalWrite {
    pub(super) step: String,
    /// Base operation before the line-B bit, or `None` for an extended-map
    /// chunk.
    pub(super) operation: Option<u8>,
    pub(super) line: Option<String>,
    /// ECG short address, or the extended-map address for a chunk.
    pub(super) address: Option<u32>,
    pub(super) payload_hex: String,
}

impl DaliJournalWrite {
    pub(super) fn describe(&self) -> String {
        let mut text = self.step.clone();
        if let Some(operation) = self.operation {
            text.push_str(&format!(" op {operation}"));
        }
        match (&self.line, self.address) {
            (Some(line), Some(address)) => text.push_str(&format!(" {line}/{address}")),
            (Some(line), None) => text.push_str(&format!(" line {line}")),
            (None, Some(address)) => text.push_str(&format!(" @{address}")),
            (None, None) => {}
        }
        text
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct DaliJournalRecord {
    pub(super) format: String,
    pub(super) journal_id: String,
    pub(super) command: String,
    pub(super) session: String,
    pub(super) project: String,
    pub(super) gateway_unit: u8,
    pub(super) pci_generation: u64,
    pub(super) created_unix_ms: i64,
    pub(super) updated_unix_ms: i64,
    pub(super) planned: Vec<DaliJournalWrite>,
    /// Number of leading `planned` entries whose reply was received.
    pub(super) confirmed_writes: usize,
    /// Per-confirmed-write gateway status notes, in order.
    pub(super) confirmed_notes: Vec<String>,
    /// `send_pending`, `in_progress`, `complete`, `failed` (a definite
    /// gateway reply or a model fault stopped the plan), or
    /// `outcome_uncertain` (the in-flight exchange may have reached the bus).
    pub(super) state: String,
    pub(super) send_may_have_occurred: bool,
    pub(super) rolled_back: bool,
    pub(super) complete: bool,
    pub(super) last_error: Option<String>,
}

/// Identity of a new journal record.
pub(super) struct DaliJournalPlan<'a> {
    pub(super) command: String,
    pub(super) session: &'a str,
    pub(super) project: &'a str,
    pub(super) gateway_unit: u8,
    pub(super) pci_generation: u64,
    pub(super) planned: Vec<DaliJournalWrite>,
}

/// Writer for the one record owned by an executing plan.
pub(super) struct ActiveDaliJournal {
    journal: RecoveryJournal,
    record: DaliJournalRecord,
}

impl ActiveDaliJournal {
    /// Exclusively create and fsync the record before any device-changing
    /// exchange. Any error means the caller must not send.
    pub(super) fn create(directory: &Path, plan: DaliJournalPlan<'_>) -> Result<Self, String> {
        static NONCE: AtomicU64 = AtomicU64::new(0);
        super::move_journal::ensure_directory(directory)
            .map_err(|error| format!("journal directory {}: {error}", directory.display()))?;
        let created = super::move_journal::now_unix_ms();
        let identity = serde_json::json!({
            "format": DALI_JOURNAL_FORMAT,
            "command": plan.command,
            "session": plan.session,
            "project": plan.project,
            "gateway_unit": plan.gateway_unit,
            "pci_generation": plan.pci_generation,
            "planned": plan.planned,
            "created_unix_ms": created,
            "process": std::process::id(),
            "nonce": NONCE.fetch_add(1, Ordering::Relaxed),
        });
        let digest = hex::encode(crate::auth::sha256(identity.to_string().as_bytes()));
        let journal_id = format!("{created:013}-{}", &digest[..16]);
        let record = DaliJournalRecord {
            format: DALI_JOURNAL_FORMAT.to_string(),
            journal_id: journal_id.clone(),
            command: plan.command,
            session: plan.session.to_string(),
            project: plan.project.to_string(),
            gateway_unit: plan.gateway_unit,
            pci_generation: plan.pci_generation,
            created_unix_ms: created,
            updated_unix_ms: created,
            planned: plan.planned,
            confirmed_writes: 0,
            confirmed_notes: Vec::new(),
            state: "send_pending".to_string(),
            send_may_have_occurred: true,
            rolled_back: false,
            complete: false,
            last_error: None,
        };
        let mut journal = RecoveryJournal::new(journal_path(directory, &journal_id))
            .map_err(|error| error.to_string())?;
        let value = serde_json::to_value(&record).map_err(|error| error.to_string())?;
        journal.write(&value).map_err(|error| error.to_string())?;
        if !journal.last_update().directory_synced {
            return Err("journal directory sync was not confirmed".to_string());
        }
        Ok(Self { journal, record })
    }

    pub(super) fn id(&self) -> &str {
        &self.record.journal_id
    }

    pub(super) fn record(&self) -> &DaliJournalRecord {
        &self.record
    }

    fn update(&mut self, change: impl FnOnce(&mut DaliJournalRecord)) -> Result<(), String> {
        let mut next = self.record.clone();
        change(&mut next);
        next.updated_unix_ms = super::move_journal::now_unix_ms();
        let value = serde_json::to_value(&next).map_err(|error| error.to_string())?;
        self.journal
            .write(&value)
            .map_err(|error| error.to_string())?;
        self.record = next;
        Ok(())
    }

    /// Record that `planned[confirmed_writes]` received its reply.
    pub(super) fn confirm(&mut self, note: &str) -> Result<(), String> {
        self.update(|record| {
            record.confirmed_writes += 1;
            record.confirmed_notes.push(note.to_string());
            record.state = "in_progress".to_string();
        })
    }

    pub(super) fn complete(&mut self) -> Result<(), String> {
        self.update(|record| {
            record.complete = true;
            record.state = "complete".to_string();
        })
    }

    /// Best effort terminal annotation. `uncertain` is true when the
    /// in-flight exchange may have reached the bus without a reply.
    pub(super) fn stopped(&mut self, uncertain: bool, error: &str) {
        if let Err(write) = self.update(|record| {
            record.state = if uncertain {
                "outcome_uncertain"
            } else {
                "failed"
            }
            .to_string();
            record.last_error = Some(error.to_string());
        }) {
            tracing::warn!(
                journal = %self.record.journal_id,
                "DALI journal stop annotation failed: {write}"
            );
        }
    }

    /// One-line operator summary of the confirmed prefix and the stop point.
    pub(super) fn summary(&self) -> String {
        let record = &self.record;
        let mut text = format!(
            "DALI journal {}: {} of {} planned device writes confirmed",
            record.journal_id,
            record.confirmed_writes,
            record.planned.len()
        );
        if let Some(last) = record
            .confirmed_writes
            .checked_sub(1)
            .and_then(|index| record.planned.get(index))
        {
            text.push_str(&format!("; last confirmed {}", last.describe()));
        }
        if !record.complete {
            if let Some(next) = record.planned.get(record.confirmed_writes) {
                text.push_str(&format!("; stopped at {}", next.describe()));
            }
            text.push_str("; nothing was rolled back or replayed");
        }
        text
    }
}

fn journal_path(directory: &Path, journal_id: &str) -> PathBuf {
    directory.join(format!("dali-{journal_id}.json"))
}

/// Remove the oldest finished records beyond the retention bound.
pub(super) fn prune_finished(directory: &Path) {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return;
    };
    let mut finished = Vec::new();
    for entry in entries.flatten().take(MAX_JOURNAL_FILES) {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with("dali-") || !name.ends_with(".json") {
            continue;
        }
        let Ok(bytes) = RecoveryJournal::new(&path).and_then(|journal| journal.read_current())
        else {
            continue;
        };
        let Ok(record) = serde_json::from_slice::<DaliJournalRecord>(&bytes) else {
            continue;
        };
        if record.complete {
            finished.push((record.created_unix_ms, name, path));
        }
    }
    if finished.len() <= RETAINED_FINISHED {
        return;
    }
    finished.sort();
    let excess = finished.len() - RETAINED_FINISHED;
    for (_, _, path) in finished.into_iter().take(excess) {
        if let Err(error) = std::fs::remove_file(&path) {
            tracing::warn!("DALI journal prune of {} failed: {error}", path.display());
        }
    }
}

/// A plan whose durable intent could not be recorded sends nothing.
pub(super) fn journal_refused(tag: &str, error: &str) -> Response {
    err(
        tag,
        503,
        &format!("503 network error: DALI journal could not be recorded: {error}; no bus command was sent"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn journal_records_the_confirmed_prefix_and_stop_point() {
        let directory = std::env::temp_dir().join(format!(
            "cmqttd-dali-journal-{}-{}",
            std::process::id(),
            super::super::move_journal::now_unix_ms()
        ));
        let write = |address| DaliJournalWrite {
            step: "SET_COMMON_PARAMS_ECG".to_string(),
            operation: Some(32),
            line: Some("A".to_string()),
            address: Some(address),
            payload_hex: "00".to_string(),
        };
        let mut journal = ActiveDaliJournal::create(
            &directory,
            DaliJournalPlan {
                command: "DALI SESSION DEPLOY DALI_ONLY".to_string(),
                session: "work",
                project: "HARNESS",
                gateway_unit: 20,
                pci_generation: 1,
                planned: vec![write(3), write(5)],
            },
        )
        .unwrap();
        let path = journal_path(&directory, journal.id());
        let on_disk = |path: &Path| {
            serde_json::from_slice::<DaliJournalRecord>(&std::fs::read(path).unwrap()).unwrap()
        };
        let created = on_disk(&path);
        assert!(created.send_may_have_occurred);
        assert_eq!(created.state, "send_pending");
        journal.confirm("SUCCESS").unwrap();
        journal.stopped(true, "reply timed out");
        let stopped = on_disk(&path);
        assert_eq!(stopped.confirmed_writes, 1);
        assert_eq!(stopped.state, "outcome_uncertain");
        assert!(!stopped.rolled_back && !stopped.complete);
        let summary = journal.summary();
        assert!(summary.contains("1 of 2 planned device writes confirmed"));
        assert!(summary.contains("last confirmed SET_COMMON_PARAMS_ECG op 32 A/3"));
        assert!(summary.contains("stopped at SET_COMMON_PARAMS_ECG op 32 A/5"));
        std::fs::remove_dir_all(directory).unwrap();
    }
}
