//! Durable journal for cmqttd's physical readdressing backends.
//!
//! `NET UNRAVEL`, `NET UNRAVELUNIT` (including MATCHDB and the `DO UNRAVEL`
//! alias) and scalar `SET ... Address` write unit addresses. A process that
//! stops after an address STORE but before its post-move observation cannot
//! otherwise know whether a unit moved, and a restarted caller could issue the
//! same move again against a changed network.
//!
//! Before the first physical write of a move plan the service exclusively
//! creates and fsyncs one journal record (the transport crate's
//! [`RecoveryJournal`], the same primitive used by selected-serial
//! commissioning). The record is conservative from creation:
//! `send_may_have_occurred` is already true. It is replaced atomically after
//! each confirmed store, after the final verified inventory, and on
//! completion. An incomplete record blocks every later physical move on its
//! network, including after restart, until an operator runs the read-only
//! `CMQTT MOVE-JOURNAL VERIFY` observation and then `CLEAR`. Nothing in this
//! module ever replays a move.
//!
//! The journal is a cooperating-process guard for one state directory. It
//! does not exclude other controllers on the bus.

use super::*;
use cbus_transport::journal::RecoveryJournal;
use std::ffi::OsString;
use std::path::PathBuf;

pub(super) const MOVE_JOURNAL_FORMAT: &str = "cmqttd-move-journal-v1";
const MOVE_JOURNAL_LIST_FORMAT: &str = "cmqttd-move-journal-list-v1";
const MOVE_JOURNAL_VERIFY_FORMAT: &str = "cmqttd-move-journal-verify-v1";
/// Finished (complete or cleared) records retained per network. Incomplete
/// records are never pruned.
const RETAINED_FINISHED_PER_NETWORK: usize = 16;
/// Bound the directory scan so a polluted directory cannot stall commands.
const MAX_JOURNAL_FILES: usize = 4096;
/// Serial placeholder for an address-scoped observation whose IDENTIFY4
/// reply carried no known serial number.
pub(super) const UNKNOWN_SERIAL: &str = "unknown";

/// `<state file name>.move-journal`, beside the durable C-Gate database.
pub(super) fn journal_directory(state_path: &Path) -> PathBuf {
    let mut name = state_path
        .file_name()
        .map(OsString::from)
        .unwrap_or_else(|| OsString::from("cgate"));
    name.push(".move-journal");
    state_path.with_file_name(name)
}

/// One planned address move.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct PlannedMove {
    pub(super) source: u8,
    pub(super) serial: String,
    pub(super) destination: u8,
}

/// Fresh observation recorded by `CMQTT MOVE-JOURNAL VERIFY`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct MoveVerification {
    pub(super) outcome: String,
    pub(super) verified_unix_ms: i64,
    pub(super) pci_generation: u64,
    pub(super) observed: Option<BTreeMap<u8, Vec<String>>>,
    /// Per planned move: true at its destination, false still at its source,
    /// `None` when the observation does not place it at either.
    pub(super) moved: Vec<Option<bool>>,
    pub(super) error: Option<String>,
}

/// Durable journal document. Unknown fields are rejected so a record from an
/// incompatible writer blocks instead of being misread.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MoveJournalRecord {
    pub(super) format: String,
    pub(super) journal_id: String,
    pub(super) attempt_id: String,
    pub(super) operation: String,
    pub(super) command: String,
    pub(super) project: String,
    pub(super) network: u8,
    pub(super) route: Vec<u8>,
    pub(super) pci_generation: u64,
    pub(super) created_unix_ms: i64,
    pub(super) updated_unix_ms: i64,
    /// `full_inventory` (whole-network MMI + IDENTIFY4) or `addresses`
    /// (IDENTIFY4 at `scope_addresses` only).
    pub(super) verification_scope: String,
    pub(super) scope_addresses: Vec<u8>,
    pub(super) moves: Vec<PlannedMove>,
    pub(super) before: BTreeMap<u8, Vec<String>>,
    pub(super) expected_after: BTreeMap<u8, Vec<String>>,
    /// `send_pending`, `moving`, `store_confirmed`, `final_verified`,
    /// `outcome_uncertain`, `complete` or `cleared`.
    pub(super) state: String,
    pub(super) send_may_have_occurred: bool,
    pub(super) read_only_recovery_only: bool,
    pub(super) confirmed_moves: usize,
    pub(super) final_inventory_verified: bool,
    pub(super) completion_evidence: Option<String>,
    pub(super) complete: bool,
    pub(super) cleared: bool,
    pub(super) last_error: Option<String>,
    pub(super) verification: Option<MoveVerification>,
}

impl MoveJournalRecord {
    /// An incomplete record blocks new physical moves on its network.
    pub(super) fn blocking(&self) -> bool {
        !(self.complete || self.cleared)
    }

    fn summary(&self) -> serde_json::Value {
        serde_json::json!({
            "id": self.journal_id,
            "attempt_id": self.attempt_id,
            "operation": self.operation,
            "command": self.command,
            "network": self.network,
            "route": self.route,
            "state": self.state,
            "blocking": self.blocking(),
            "moves": self.moves,
            "confirmed_moves": self.confirmed_moves,
            "final_inventory_verified": self.final_inventory_verified,
            "send_may_have_occurred": self.send_may_have_occurred,
            "created_unix_ms": self.created_unix_ms,
            "updated_unix_ms": self.updated_unix_ms,
            "last_error": self.last_error,
            "verification": self.verification,
        })
    }
}

/// Inputs that identify one move plan.
pub(super) struct MovePlanIdentity<'a> {
    pub(super) operation: &'a str,
    pub(super) command: String,
    pub(super) project: &'a str,
    pub(super) network: u8,
    pub(super) route: &'a [u8],
    pub(super) pci_generation: u64,
    pub(super) verification_scope: &'a str,
    pub(super) scope_addresses: Vec<u8>,
    pub(super) moves: Vec<PlannedMove>,
    pub(super) before: BTreeMap<u8, Vec<String>>,
    pub(super) expected_after: BTreeMap<u8, Vec<String>>,
}

/// Writer for the one record owned by an executing move.
pub(super) struct ActiveMoveJournal {
    journal: RecoveryJournal,
    record: MoveJournalRecord,
}

fn now_unix_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn sync_directory(directory: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        std::fs::File::open(directory)?.sync_all()
    }
    #[cfg(not(unix))]
    {
        let _ = directory;
        Ok(())
    }
}

fn ensure_directory(directory: &Path) -> io::Result<()> {
    match std::fs::symlink_metadata(directory) {
        Ok(metadata) if metadata.is_dir() => return Ok(()),
        Ok(_) => {
            return Err(io::Error::other(format!(
                "{} is not a directory",
                directory.display()
            )))
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    std::fs::create_dir_all(directory)?;
    // Make the new directory entry itself durable before a record in it is
    // relied upon across a crash.
    let parent = directory
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    sync_directory(parent)
}

impl ActiveMoveJournal {
    /// Exclusively create and fsync the record before any physical write.
    /// Any error means the caller must not send.
    pub(super) fn create(directory: &Path, plan: MovePlanIdentity<'_>) -> Result<Self, String> {
        static NONCE: AtomicU64 = AtomicU64::new(0);
        ensure_directory(directory)
            .map_err(|error| format!("journal directory {}: {error}", directory.display()))?;
        let created = now_unix_ms();
        let identity = serde_json::json!({
            "format": MOVE_JOURNAL_FORMAT,
            "operation": plan.operation,
            "project": plan.project,
            "network": plan.network,
            "route": plan.route,
            "pci_generation": plan.pci_generation,
            "moves": plan.moves,
            "before": plan.before,
            "expected_after": plan.expected_after,
            "created_unix_ms": created,
            "process": std::process::id(),
            "nonce": NONCE.fetch_add(1, Ordering::Relaxed),
        });
        let digest = hex::encode(crate::auth::sha256(identity.to_string().as_bytes()));
        let journal_id = format!("{:03}-{}", plan.network, &digest[..16]);
        let record = MoveJournalRecord {
            format: MOVE_JOURNAL_FORMAT.to_string(),
            journal_id: journal_id.clone(),
            attempt_id: format!("sha256:{digest}"),
            operation: plan.operation.to_string(),
            command: plan.command,
            project: plan.project.to_string(),
            network: plan.network,
            route: plan.route.to_vec(),
            pci_generation: plan.pci_generation,
            created_unix_ms: created,
            updated_unix_ms: created,
            verification_scope: plan.verification_scope.to_string(),
            scope_addresses: plan.scope_addresses,
            moves: plan.moves,
            before: plan.before,
            expected_after: plan.expected_after,
            state: "send_pending".to_string(),
            send_may_have_occurred: true,
            read_only_recovery_only: true,
            confirmed_moves: 0,
            final_inventory_verified: false,
            completion_evidence: None,
            complete: false,
            cleared: false,
            last_error: None,
            verification: None,
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

    fn update(&mut self, change: impl FnOnce(&mut MoveJournalRecord)) -> Result<(), String> {
        let mut next = self.record.clone();
        change(&mut next);
        next.updated_unix_ms = now_unix_ms();
        let value = serde_json::to_value(&next).map_err(|error| error.to_string())?;
        self.journal
            .write(&value)
            .map_err(|error| error.to_string())?;
        self.record = next;
        Ok(())
    }

    /// Record one move whose destination readback (or unit store ACK for
    /// scalar SET) confirmed it.
    pub(super) fn confirm_move(&mut self, state: &str) -> Result<(), String> {
        self.update(|record| {
            record.confirmed_moves += 1;
            record.state = state.to_string();
        })
    }

    /// Record the fresh whole-network inventory that equals the plan.
    pub(super) fn final_verified(&mut self) -> Result<(), String> {
        self.update(|record| {
            record.final_inventory_verified = true;
            record.state = "final_verified".to_string();
        })
    }

    /// Mark the physical outcome established. A later cache-commit or
    /// option-check failure is retained as `last_error`; it does not make
    /// the already verified physical outcome uncertain.
    pub(super) fn complete(&mut self, evidence: &str, note: Option<&str>) -> Result<(), String> {
        self.update(|record| {
            record.complete = true;
            record.state = "complete".to_string();
            record.completion_evidence = Some(evidence.to_string());
            record.last_error = note.map(str::to_string);
        })
    }

    /// Best effort: annotate an uncertain stop. The record already blocks
    /// the network whether or not this annotation reaches the disk.
    pub(super) fn uncertain(&mut self, error: &str) {
        if let Err(write) = self.update(|record| {
            record.state = "outcome_uncertain".to_string();
            record.last_error = Some(error.to_string());
        }) {
            tracing::warn!(
                journal = %self.record.journal_id,
                "move journal uncertainty annotation failed: {write}"
            );
        }
    }
}

/// A move whose durable intent could not be recorded sends nothing.
pub(super) fn journal_refused(tag: &str, error: &str) -> Response {
    err(
        tag,
        408,
        &format!("408 Move journal could not be recorded: {error}; no address request sent"),
    )
}

fn journal_path(directory: &Path, journal_id: &str) -> PathBuf {
    directory.join(format!("move-{journal_id}.json"))
}

fn valid_journal_id(id: &str) -> bool {
    id.len() == 20
        && id.as_bytes()[3] == b'-'
        && id[..3].bytes().all(|byte| byte.is_ascii_digit())
        && id[4..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Guarded read and strict parse of one record.
fn load_record(path: &Path) -> Result<MoveJournalRecord, String> {
    let raw = RecoveryJournal::new(path)
        .and_then(|journal| journal.read_current())
        .map_err(|error| error.to_string())?;
    let record = serde_json::from_slice::<MoveJournalRecord>(&raw)
        .map_err(|error| format!("corrupt record: {error}"))?;
    if record.format != MOVE_JOURNAL_FORMAT {
        return Err(format!("unsupported format {}", record.format));
    }
    let expected_name = format!("move-{}.json", record.journal_id);
    if !valid_journal_id(&record.journal_id)
        || path.file_name().and_then(|name| name.to_str()) != Some(expected_name.as_str())
    {
        return Err("record identity does not match its file name".to_string());
    }
    Ok(record)
}

/// Directory scan result: readable records, and files that cannot be
/// trusted. An unreadable file blocks every network because its network is
/// unknown.
#[derive(Default)]
pub(super) struct JournalScan {
    pub(super) records: Vec<MoveJournalRecord>,
    pub(super) unreadable: Vec<(String, String)>,
}

pub(super) fn scan(directory: &Path) -> JournalScan {
    let mut result = JournalScan::default();
    let entries = match std::fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return result,
        Err(error) => {
            result
                .unreadable
                .push((directory.display().to_string(), error.to_string()));
            return result;
        }
    };
    let mut names = Vec::new();
    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(error) => {
                result
                    .unreadable
                    .push((directory.display().to_string(), error.to_string()));
                continue;
            }
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        // Atomic-replacement temp files are dot-prefixed and never records.
        if name.starts_with('.') || !name.starts_with("move-") || !name.ends_with(".json") {
            continue;
        }
        names.push(name);
        if names.len() > MAX_JOURNAL_FILES {
            result.unreadable.push((
                directory.display().to_string(),
                format!("more than {MAX_JOURNAL_FILES} journal files"),
            ));
            return result;
        }
    }
    names.sort();
    for name in names {
        match load_record(&directory.join(&name)) {
            Ok(record) => result.records.push(record),
            Err(error) => result.unreadable.push((name, error)),
        }
    }
    result
}

impl JournalScan {
    /// Explicit refusal text when `network` must not start a new move.
    pub(super) fn refusal(&self, network: u8) -> Option<String> {
        if let Some((name, error)) = self.unreadable.first() {
            return Some(format!(
                "409 Move journal {name} is unreadable ({error}); no physical move is attempted until an operator inspects and removes it"
            ));
        }
        self.records
            .iter()
            .find(|record| record.network == network && record.blocking())
            .map(|record| {
                format!(
                    "409 Move journal {} for network {} is incomplete ({}); run CMQTT MOVE-JOURNAL VERIFY {} then CLEAR before any new physical move",
                    record.journal_id, record.network, record.state, record.journal_id
                )
            })
    }

    pub(super) fn blocked_networks(&self) -> Vec<u8> {
        let mut networks = self
            .records
            .iter()
            .filter(|record| record.blocking())
            .map(|record| record.network)
            .collect::<Vec<_>>();
        networks.sort_unstable();
        networks.dedup();
        networks
    }

    pub(super) fn incomplete_ids(&self) -> Vec<String> {
        self.records
            .iter()
            .filter(|record| record.blocking())
            .map(|record| record.journal_id.clone())
            .collect()
    }
}

/// Remove the oldest finished records beyond the retention bound. Only
/// complete or cleared records are candidates; failures are logged.
pub(super) fn prune_finished(directory: &Path, network: u8) {
    let mut finished = scan(directory)
        .records
        .into_iter()
        .filter(|record| record.network == network && !record.blocking())
        .collect::<Vec<_>>();
    if finished.len() <= RETAINED_FINISHED_PER_NETWORK {
        return;
    }
    finished.sort_by(|left, right| {
        (left.created_unix_ms, &left.journal_id).cmp(&(right.created_unix_ms, &right.journal_id))
    });
    let excess = finished.len() - RETAINED_FINISHED_PER_NETWORK;
    for record in finished.into_iter().take(excess) {
        let path = journal_path(directory, &record.journal_id);
        if let Err(error) = std::fs::remove_file(&path) {
            tracing::warn!("move journal prune of {} failed: {error}", path.display());
        }
    }
}

/// Apply the subset of planned moves selected by `moved` to `before`.
fn apply_moves(
    before: &BTreeMap<u8, Vec<String>>,
    moves: &[PlannedMove],
    moved: &[bool],
) -> BTreeMap<u8, Vec<String>> {
    let mut inventory = before.clone();
    for (planned, moved) in moves.iter().zip(moved) {
        if !moved {
            continue;
        }
        if let Some(serials) = inventory.get_mut(&planned.source) {
            serials.retain(|serial| serial != &planned.serial);
            if serials.is_empty() {
                inventory.remove(&planned.source);
            }
        }
        let destination = inventory.entry(planned.destination).or_default();
        destination.push(planned.serial.clone());
        destination.sort();
    }
    inventory
}

/// Classify one fresh observation against the recorded plan. Outcomes:
/// `observed_expected_change`, `observed_unchanged`, `observed_mixed` (a
/// strict nonempty subset of moves happened and nothing else changed) and
/// `observed_unexpected_change`. None of them authorizes a replay.
pub(super) fn classify(
    record: &MoveJournalRecord,
    observed: &BTreeMap<u8, Vec<String>>,
) -> (&'static str, Vec<Option<bool>>) {
    let located = record
        .moves
        .iter()
        .map(|planned| {
            let at = |address: u8| {
                observed
                    .get(&address)
                    .is_some_and(|serials| serials.contains(&planned.serial))
            };
            match (at(planned.source), at(planned.destination)) {
                (false, true) => Some(true),
                (true, false) => Some(false),
                _ => None,
            }
        })
        .collect::<Vec<_>>();
    if *observed == record.expected_after {
        return ("observed_expected_change", located);
    }
    if *observed == record.before {
        return ("observed_unchanged", located);
    }
    if located.iter().all(Option::is_some) {
        let moved = located
            .iter()
            .map(|entry| entry.expect("all located"))
            .collect::<Vec<_>>();
        if moved.iter().any(|entry| *entry)
            && moved.iter().any(|entry| !*entry)
            && apply_moves(&record.before, &record.moves, &moved) == *observed
        {
            return ("observed_mixed", located);
        }
    }
    ("observed_unexpected_change", located)
}

impl Service {
    /// Explicit refusal while an incomplete journal exists for `network`.
    pub(super) fn move_journal_refusal(&self, network: u8) -> Option<String> {
        scan(&self.move_journal_dir).refusal(network)
    }

    /// Capability/status fields for `CMQTT CAPABILITIES`.
    pub(super) fn move_journal_capabilities(&self, capabilities: &mut serde_json::Value) {
        let scan = scan(&self.move_journal_dir);
        capabilities["move_journal"] = serde_json::Value::Bool(true);
        capabilities["move_journal_format"] = serde_json::json!(MOVE_JOURNAL_FORMAT);
        capabilities["move_journal_backends"] =
            serde_json::json!(["net_unravel", "net_unravelunit", "set_address"]);
        capabilities["move_journal_replay"] = serde_json::Value::Bool(false);
        capabilities["move_journal_incomplete"] = serde_json::json!(scan.incomplete_ids());
        capabilities["move_journal_blocked_networks"] = serde_json::json!(scan.blocked_networks());
        capabilities["move_journal_unreadable"] = serde_json::json!(scan
            .unreadable
            .iter()
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>());
    }

    /// Warn at startup about every record that will refuse new moves.
    pub(super) fn log_move_journal_startup(directory: &Path) {
        let scan = scan(directory);
        for record in scan.records.iter().filter(|record| record.blocking()) {
            tracing::warn!(
                journal = %record.journal_id,
                network = record.network,
                state = %record.state,
                "incomplete physical move journal: new moves on this network are refused until CMQTT MOVE-JOURNAL VERIFY and CLEAR"
            );
        }
        for (name, error) in &scan.unreadable {
            tracing::warn!(
                "unreadable physical move journal {name}: {error}; all physical moves are refused"
            );
        }
    }

    /// `CMQTT MOVE-JOURNAL LIST|VERIFY <id>|CLEAR <id>`.
    pub(super) async fn move_journal_command(&self, tag: &str, words: &[&str]) -> Response {
        let action = words.get(2).map(|word| word.to_ascii_uppercase());
        match (action.as_deref(), words.len()) {
            (Some("LIST"), 3) => {
                let scan = scan(&self.move_journal_dir);
                let journals = scan
                    .records
                    .iter()
                    .map(MoveJournalRecord::summary)
                    .collect::<Vec<_>>();
                ok(
                    tag,
                    vec![serde_json::json!({
                        "format": MOVE_JOURNAL_LIST_FORMAT,
                        "directory": self.move_journal_dir.display().to_string(),
                        "journals": journals,
                        "incomplete": scan.incomplete_ids(),
                        "blocked_networks": scan.blocked_networks(),
                        "unreadable": scan.unreadable.iter().map(|(name, error)| {
                            serde_json::json!({"name": name, "error": error})
                        }).collect::<Vec<_>>(),
                    })
                    .to_string()],
                    "200 OK",
                )
            }
            (Some("VERIFY"), 4) => self.move_journal_verify(tag, words[3]).await,
            (Some("CLEAR"), 4) => self.move_journal_clear(tag, words[3]).await,
            _ => err(
                tag,
                400,
                "400 CMQTT MOVE-JOURNAL requires LIST, VERIFY <id> or CLEAR <id>",
            ),
        }
    }

    fn load_blocking_journal(&self, tag: &str, id: &str) -> Result<MoveJournalRecord, Response> {
        if !valid_journal_id(id) {
            return Err(err(tag, 400, "400 Invalid move journal id"));
        }
        let path = journal_path(&self.move_journal_dir, id);
        match std::fs::symlink_metadata(&path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Err(err(tag, 404, "404 Move journal not found"));
            }
            _ => {}
        }
        let record = load_record(&path).map_err(|error| {
            err(
                tag,
                409,
                &format!("409 Move journal {id} is unreadable: {error}"),
            )
        })?;
        if !record.blocking() {
            return Err(err(
                tag,
                409,
                &format!("409 Move journal {id} is already {}", record.state),
            ));
        }
        Ok(record)
    }

    /// Fresh read-only observation of an incomplete journal. The outcome is
    /// recorded in the journal; no address request is ever sent.
    async fn move_journal_verify(&self, tag: &str, id: &str) -> Response {
        let _commands = self.commands.lock().await;
        let record = match self.load_blocking_journal(tag, id) {
            Ok(record) => record,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let observed = if record.verification_scope == "full_inventory" {
            match install_mmi_for_route(&pci, &record.route).await {
                Ok(states) => physical_serial_inventory(&pci, &states, &record.route).await,
                Err(error) => Err(error),
            }
        } else {
            let mut observed = BTreeMap::new();
            let mut failure = None;
            for address in &record.scope_addresses {
                match identify_all_for_route(&pci, &record.route, *address, 4).await {
                    Ok(replies) if replies.is_empty() => {}
                    Ok(replies) => {
                        let serials = replies
                            .iter()
                            .map(|reply| {
                                serial_number(reply).map(|serial| {
                                    serial.unwrap_or_else(|| UNKNOWN_SERIAL.to_string())
                                })
                            })
                            .collect::<io::Result<Vec<_>>>();
                        match serials {
                            Ok(mut serials) => {
                                serials.sort();
                                observed.insert(*address, serials);
                            }
                            Err(error) => {
                                failure = Some(error);
                                break;
                            }
                        }
                    }
                    Err(error) => {
                        failure = Some(error);
                        break;
                    }
                }
            }
            match failure {
                Some(error) => Err(error),
                None => Ok(observed),
            }
        };
        let current_generation = self.pci_commit_guard(generation, &pci).await.is_some();
        let verification = match observed {
            Ok(observed) if current_generation => {
                let (outcome, moved) = classify(&record, &observed);
                MoveVerification {
                    outcome: outcome.to_string(),
                    verified_unix_ms: now_unix_ms(),
                    pci_generation: generation,
                    observed: Some(observed),
                    moved,
                    error: None,
                }
            }
            observed => MoveVerification {
                outcome: "uncertain".to_string(),
                verified_unix_ms: now_unix_ms(),
                pci_generation: generation,
                observed: None,
                moved: Vec::new(),
                error: Some(match observed {
                    Err(error) => error.to_string(),
                    Ok(_) => "PCI connection generation changed during observation".to_string(),
                }),
            },
        };
        let mut updated = record.clone();
        updated.verification = Some(verification.clone());
        updated.updated_unix_ms = now_unix_ms();
        let written = RecoveryJournal::resume(journal_path(&self.move_journal_dir, id))
            .map_err(|error| error.to_string())
            .and_then(|mut journal| {
                serde_json::to_value(&updated)
                    .map_err(|error| error.to_string())
                    .and_then(|value| journal.write(&value).map_err(|error| error.to_string()))
            });
        if let Err(error) = written {
            return err(
                tag,
                408,
                &format!("408 Move journal {id} verification could not be recorded: {error}"),
            );
        }
        let status = if verification.outcome == "uncertain" {
            408
        } else {
            200
        };
        let line = serde_json::json!({
            "format": MOVE_JOURNAL_VERIFY_FORMAT,
            "id": id,
            "network": record.network,
            "outcome": verification.outcome,
            "moves": record.moves,
            "moved": verification.moved,
            "before": record.before,
            "expected_after": record.expected_after,
            "observed": verification.observed,
            "error": verification.error,
            "replay_authorized": false,
            "clear_permitted": status == 200,
        })
        .to_string();
        if status == 200 {
            ok(tag, vec![line], "200 OK")
        } else {
            Response {
                tag: tag.to_string(),
                lines: vec![format!("408-{line}")],
                final_text: format!("408 Move journal {id} verification was inconclusive"),
                status: 408,
            }
        }
    }

    /// Release an incomplete journal only after a conclusive VERIFY.
    async fn move_journal_clear(&self, tag: &str, id: &str) -> Response {
        let _commands = self.commands.lock().await;
        let record = match self.load_blocking_journal(tag, id) {
            Ok(record) => record,
            Err(response) => return response,
        };
        let Some(verification) = record
            .verification
            .as_ref()
            .filter(|verification| verification.outcome != "uncertain")
        else {
            return err(
                tag,
                409,
                &format!(
                    "409 Move journal {id} requires a conclusive CMQTT MOVE-JOURNAL VERIFY before CLEAR"
                ),
            );
        };
        let outcome = verification.outcome.clone();
        let mut updated = record.clone();
        updated.cleared = true;
        updated.state = "cleared".to_string();
        updated.updated_unix_ms = now_unix_ms();
        let written = RecoveryJournal::resume(journal_path(&self.move_journal_dir, id))
            .map_err(|error| error.to_string())
            .and_then(|mut journal| {
                serde_json::to_value(&updated)
                    .map_err(|error| error.to_string())
                    .and_then(|value| journal.write(&value).map_err(|error| error.to_string()))
            });
        if let Err(error) = written {
            return err(
                tag,
                408,
                &format!("408 Move journal {id} could not be cleared: {error}"),
            );
        }
        ok(
            tag,
            vec![serde_json::json!({
                "id": id,
                "network": record.network,
                "state": "cleared",
                "verified_outcome": outcome,
                "replay_authorized": false,
            })
            .to_string()],
            "200 OK",
        )
    }
}

#[cfg(test)]
mod unit_tests {
    use super::*;

    fn record(
        moves: Vec<PlannedMove>,
        before: &[(u8, &[&str])],
        after: &[(u8, &[&str])],
    ) -> MoveJournalRecord {
        let map = |rows: &[(u8, &[&str])]| {
            rows.iter()
                .map(|(address, serials)| {
                    (
                        *address,
                        serials.iter().map(|serial| serial.to_string()).collect(),
                    )
                })
                .collect::<BTreeMap<_, Vec<String>>>()
        };
        MoveJournalRecord {
            format: MOVE_JOURNAL_FORMAT.to_string(),
            journal_id: "254-0123456789abcdef".to_string(),
            attempt_id: "sha256:0".to_string(),
            operation: "net_unravelunit".to_string(),
            command: String::new(),
            project: "HARNESS".to_string(),
            network: 254,
            route: Vec::new(),
            pci_generation: 0,
            created_unix_ms: 0,
            updated_unix_ms: 0,
            verification_scope: "full_inventory".to_string(),
            scope_addresses: Vec::new(),
            moves,
            before: map(before),
            expected_after: map(after),
            state: "send_pending".to_string(),
            send_may_have_occurred: true,
            read_only_recovery_only: true,
            confirmed_moves: 0,
            final_inventory_verified: false,
            completion_evidence: None,
            complete: false,
            cleared: false,
            last_error: None,
            verification: None,
        }
    }

    fn observed(rows: &[(u8, &[&str])]) -> BTreeMap<u8, Vec<String>> {
        rows.iter()
            .map(|(address, serials)| {
                (
                    *address,
                    serials.iter().map(|serial| serial.to_string()).collect(),
                )
            })
            .collect()
    }

    #[test]
    fn classification_distinguishes_expected_unchanged_mixed_and_unexpected() {
        let moves = vec![
            PlannedMove {
                source: 255,
                serial: "1.1".to_string(),
                destination: 6,
            },
            PlannedMove {
                source: 255,
                serial: "1.2".to_string(),
                destination: 7,
            },
        ];
        let plan = record(
            moves,
            &[(16, &["9.9"]), (255, &["1.1", "1.2"])],
            &[(6, &["1.1"]), (7, &["1.2"]), (16, &["9.9"])],
        );
        let (outcome, moved) = classify(
            &plan,
            &observed(&[(6, &["1.1"]), (7, &["1.2"]), (16, &["9.9"])]),
        );
        assert_eq!(outcome, "observed_expected_change");
        assert_eq!(moved, [Some(true), Some(true)]);
        let (outcome, moved) =
            classify(&plan, &observed(&[(16, &["9.9"]), (255, &["1.1", "1.2"])]));
        assert_eq!(outcome, "observed_unchanged");
        assert_eq!(moved, [Some(false), Some(false)]);
        let (outcome, moved) = classify(
            &plan,
            &observed(&[(6, &["1.1"]), (16, &["9.9"]), (255, &["1.2"])]),
        );
        assert_eq!(outcome, "observed_mixed");
        assert_eq!(moved, [Some(true), Some(false)]);
        // A partial move plus an unrelated change is not a clean mix.
        let (outcome, _) = classify(
            &plan,
            &observed(&[(6, &["1.1"]), (255, &["1.2"]), (17, &["9.9"])]),
        );
        assert_eq!(outcome, "observed_unexpected_change");
        let (outcome, moved) = classify(&plan, &observed(&[(16, &["9.9"])]));
        assert_eq!(outcome, "observed_unexpected_change");
        assert_eq!(moved, [None, None]);
    }

    #[test]
    fn journal_directory_is_beside_the_state_file() {
        assert_eq!(
            journal_directory(Path::new("/data/cgate.json")),
            PathBuf::from("/data/cgate.json.move-journal")
        );
        assert!(valid_journal_id("254-0123456789abcdef"));
        assert!(!valid_journal_id("254-0123456789ABCDEF"));
        assert!(!valid_journal_id("../0123456789abcdef"));
    }
}
