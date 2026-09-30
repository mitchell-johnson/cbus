//! One-shot selected-serial apply: precondition-gated send plus post-send verify.
//!
//! This is the write path beside the transport `verify` module. The order
//! mirrors the Python oracle coordinator
//! (`toolkit-cli/src/cbus_toolkit/pci_selected_serial.py`,
//! `SelectedSerialCoordinator.apply`): validate the plan, check preconditions
//! (a fresh complete inventory proved equal to the plan's `before`, followed
//! immediately by live local option 66 equal to `05`), create the recovery
//! journal, send exactly once, then run a post-send observation. There is no
//! automatic rollback or automatic replay.
//!
//! Ordering contract (validate → fresh inventory → option 66 → journal → send):
//!
//! 1. The raw plan document is validated with no I/O. A rejection is
//!    [`ApplyError::Plan`]: no journal exists and no address command is sent.
//! 2. Preconditions reuse [`crate::verify::verify_plan_bound`] for a fresh observation held
//!    across both local commissioning lanes: opening MMI, one IDENTIFY4
//!    window for every present address, and a closing MMI that must match the
//!    opening state vector. Only `observed_unchanged` is accepted, proving the
//!    complete bookended snapshot exactly equals the embedded plan `before`.
//!    The strict validator has already recomputed `expected_after` from that
//!    `before` snapshot. Any collection failure, incomplete/mismatched
//!    bookend, or divergence is [`ApplyError::Preconditions`]: still no
//!    journal and still no send, mirroring oracle `preconditions_failed`
//!    (never post-send `Uncertain`: nothing was sent yet).
//! 3. Immediately after that potentially long inventory, preconditions
//!    re-read the live local option with `recall_parameter(local, 66, 1)` and
//!    require the single byte `05`, mirroring the oracle `_before` options
//!    check and the `NET UNRAVELUNIT` precedent in `cbus-cgate`. A recall
//!    failure or any other value is [`ApplyError::Preconditions`]: still no
//!    journal and still no send.
//! 4. The recovery journal is created and the attempt is durably marked
//!    before any send. Journal creation or write failures are
//!    [`ApplyError::Journal`].
//! 5. Exactly one broadcast is submitted through the caller's existing
//!    [`PciClient`] connection. This matters because a CNI admits one client
//!    connection at a time. The strict plan's checksum setting, fixed `g`
//!    confirmation, and exact request bytes are revalidated before that
//!    single no-retry submission. The bounded capture records whether a
//!    positive confirmation plus exact direct or routed receipt correlated, but a
//!    complete nonmatching capture still proceeds to independent inventory.
//!    Malformed, lost, or incomplete shared-session I/O lands on the
//!    journal-backed [`ApplyError::Send`] path.
//! 6. The post-send observation runs `verify_plan`. Any post-send failure —
//!    a verify init error or any outcome other than the expected change — is
//!    [`ApplyError::PostSendObservation`], never [`ApplyError::Plan`]:
//!    one exact send completed by then, and the error evidence is written
//!    to the journal when it exists. Success ([`ApplySuccess`]) requires the
//!    fresh observation to equal the plan's `expected_after`.
//!
//! Trust gap (inherited from `verify.rs`): the plan endpoint (host/port),
//! local unit, and expected local serial are not bound by the legacy direct
//! API. The routed bound API independently checks local identity and project
//! freshness. The caller must connect the client to the plan's endpoint
//! and own all commissioning activity
//! exclusively for the whole call. The same connection is used sequentially
//! for preconditions, the address transaction, and verification. Caller
//! options separately bound the fresh and after observations.
//!
//! Direct journals retain the summary-only `cbus-selected-serial-apply-v1`
//! format. Routed journals use `cbus-selected-serial-apply-v2`, adding bounded
//! original/parser frame pairs that the Python offline reconciliation validator
//! independently reparses. This does not establish complete connection capture
//! or physical acceptance. Python coordinator journals
//! (`cbus-selected-serial-result-v1`) are neither read nor written here. The durable
//! attempt marker (`cbus-selected-serial-attempt-v1`) is shared instead: the
//! Python coordinator reproduces the fingerprint bytes, filename, directory
//! rule and envelope, so either implementation's marker refuses the other's
//! replay of the same plan file and resumes read-only recovery on both.
//!
//! No-replay design: [`ApplyOnce`] claims its single use before any PCI I/O,
//! and [`apply_plan`] keeps canonical fingerprints of sanitized, validated
//! plan values for the lifetime of this process. Whitespace, object-key order,
//! and equivalent JSON string encodings therefore cannot bypass the in-process
//! guard. Concurrent free-function calls can both finish their read-only
//! preconditions and create separate intent journals, but only the fingerprint
//! claimant may send; every loser records a conservative refusal and performs
//! no send. A poisoned guard fails closed.
//!
//! The fingerprint guard is deliberately only a same-process defense. Its set
//! is not persisted, retains one canonical document per journaled intent for
//! the process lifetime, and treats non-equivalent canonical plan values as
//! distinct. Across processes or restarts, the CLI additionally reserves a
//! durable SHA-256 plan identity. By default it lives beside the journal and
//! prevents a cooperative caller using that directory from replaying an
//! identical canonical plan with a different journal name. Callers can choose one
//! shared durable store via [`ApplyOptions::attempt_store`], so different
//! journal directories still contend for the same canonical plan marker.
//! Deleted markers, different stores, changed plans, and independent
//! controllers are not globally deduplicated. Library callers opt in via
//! [`ApplyOptions::durable_attempt_identity`]. Every created
//! apply journal records
//! `send_intent_recorded` and conservative `send_attempted=true` before the
//! shared-session send primitive is invoked. A journal without a complete
//! post-send observation is therefore uncertain regardless of receipt status;
//! recovery authorizes read-only verification only, never another send.
//!
//! Recovery readback: [`load_recovery`] performs a bounded guarded read of a
//! journal file (via `RecoveryJournal::read_current`) and strictly
//! revalidates the embedded sanitized plan, returning a bounded
//! [`RecoveryRecord`] or an error on corrupt/ambiguous content.
//!
use crate::commissioning_route::RouteBinding;
use crate::journal::RecoveryJournal;
use crate::plan::{
    parse_strict_json_value, refuse_routed_execution, validate_plan_document_with_value,
    ValidatedPlan,
};
use crate::verify::{verify_plan_bound, VerifyEvidence, VerifyOptions, VerifyOutcome};
use crate::PciClient;
use ring::digest::{digest, SHA256};
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex, OnceLock,
};

/// Rust-local journal format written by [`apply_plan`].
const JOURNAL_FORMAT: &str = "cbus-selected-serial-apply-v1";
const ROUTED_JOURNAL_FORMAT: &str = "cbus-selected-serial-apply-v2";
const ATTEMPT_FORMAT: &str = "cbus-selected-serial-attempt-v1";

/// Tunables for [`apply_plan`].
#[derive(Debug, Clone, Copy, Default)]
pub struct ApplyOptions<'a> {
    /// Caller bounds used independently for the fresh-before and post-send
    /// observations, replacing plan timing for both reads.
    pub verify: VerifyOptions,
    /// Reserve a durable canonical-plan marker before any address send. It
    /// lives in the journal's existing parent directory unless `attempt_store`
    /// selects a shared directory. The CLI always enables this; library
    /// callers must opt in and retain the marker for recovery.
    pub durable_attempt_identity: bool,
    /// Optional existing shared directory for the durable attempt marker.
    /// Cooperating processes must use the same resolved directory. The
    /// recovery journal remains at `recovery_path`. Requires
    /// `durable_attempt_identity`; otherwise apply refuses before PCI I/O.
    pub attempt_store: Option<&'a Path>,
}

/// Successful apply: one exact send completed and the fresh observation
/// equals the plan's `expected_after`.
#[derive(Debug, Clone)]
pub struct ApplySuccess {
    /// Canonical selected serial that was sent.
    pub serial: String,
    /// Destination address that was sent.
    pub destination: u8,
    /// Whether the bounded shared-session capture correlates with the request.
    /// Recorded, never gated: only the after-observation classifies movement.
    pub receipt_matched: bool,
    /// The post-send classification (always the expected change on success).
    pub verify: VerifyEvidence,
    /// Recovery journal holding the full evidence trail.
    pub journal_path: PathBuf,
}

/// How one [`apply_plan`] attempt ended.
///
/// `Plan` and a preflight `AlreadyApplied` perform no PCI I/O. `Preconditions`
/// performed read-only PCI I/O but created no journal and sent no address
/// command. A `Journal`, `Send`, or `PostSendObservation` after durable intent
/// must be treated conservatively: use [`load_recovery`] plus read-only verify,
/// never replay. `PostSendObservation` documents that one send completed before
/// the after-observation failed or diverged.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApplyError {
    /// Raw plan validation failed. No journal exists and nothing was sent.
    Plan(String),
    /// Live preconditions failed: the fresh bookended MMI/IDENTIFY4
    /// observation failed or diverged, the immediately following local option
    /// recall errored, or option 66 was not `05`. No journal exists and no
    /// address command was sent.
    Preconditions(String),
    /// Recovery-journal creation or a journal write failed. The message says
    /// which phase failed; if the intent record may exist, preserve it and do
    /// not replay.
    Journal(String),
    /// The journaled shared-PCI address transaction failed. Error evidence was
    /// written to the journal when possible; this variant is never used for
    /// journal failures. Because durable intent preceded invocation, recovery
    /// must remain uncertain and must not replay. Discard the supplied
    /// [`PciClient`]: malformed/lost capture input or a write that may have
    /// started faults its programming lane.
    Send(String),
    /// One exact send completed, then the post-send observation failed
    /// to classify the expected change. Error evidence was written to the
    /// journal when it existed.
    PostSendObservation(String),
    /// A repeat apply of a plan that already recorded a journaled attempt
    /// (or whose fingerprint guard is poisoned, which fails closed the same
    /// way). Guarantee is NO SEND by this call. In the pre-I/O guard path no
    /// journal was created by this call; in the post-journal race-loser path
    /// the caller's journal file already exists and carries this refusal as
    /// error evidence.
    AlreadyApplied(String),
}

impl std::fmt::Display for ApplyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Plan(message) => write!(f, "plan: {message}"),
            Self::Preconditions(message) => write!(f, "preconditions: {message}"),
            Self::Journal(message) => write!(f, "journal: {message}"),
            Self::Send(message) => write!(f, "send: {message}"),
            Self::AlreadyApplied(message) => write!(f, "already_applied: {message}"),
            Self::PostSendObservation(message) => {
                write!(f, "post_send_observation: {message}")
            }
        }
    }
}

impl std::error::Error for ApplyError {}

/// Mutable journal evidence accumulated across the attempt.
#[derive(Debug, Clone)]
struct Evidence {
    route_binding: Option<Value>,
    before_frames: Option<Value>,
    local_identity_frames: Option<Value>,
    local_options_frames: Option<Value>,
    exchange_frames: Option<Value>,
    after_frames: Option<Value>,
    state: String,
    outcome: String,
    serial: String,
    destination: u8,
    local_unit: u8,
    endpoint_host: String,
    endpoint_port: u16,
    options_verified: Option<Vec<u8>>,
    send_intent_recorded: bool,
    attempt_recorded: bool,
    attempt_durability_verified: bool,
    send_attempted: bool,
    exchange_send_attempted: Option<bool>,
    send_completed: bool,
    sends: u32,
    receipt_matched: Option<bool>,
    exchange_termination: Option<String>,
    exchange_errors: Vec<String>,
    after_outcome: Option<String>,
    after_collection_complete: Option<bool>,
    after_unexpected_changes: Vec<Value>,
    after_errors: Vec<String>,
    errors: Vec<String>,
    attempt_identity: Option<String>,
    /// The full validated plan document, embedded so [`load_recovery`] can
    /// strictly revalidate the intent this journal records.
    plan: Value,
}

impl Evidence {
    fn new(plan: &ValidatedPlan, plan_value: Value) -> Self {
        Self {
            route_binding: None,
            before_frames: None,
            local_identity_frames: None,
            local_options_frames: None,
            exchange_frames: None,
            after_frames: None,
            state: "validated".to_string(),
            outcome: "uncertain".to_string(),
            serial: plan.serial.clone(),
            destination: plan.destination,
            local_unit: plan.local_unit,
            endpoint_host: plan.host.clone(),
            endpoint_port: plan.port,
            options_verified: None,
            send_intent_recorded: false,
            attempt_recorded: false,
            attempt_durability_verified: false,
            send_attempted: false,
            exchange_send_attempted: None,
            send_completed: false,
            sends: 0,
            receipt_matched: None,
            exchange_termination: None,
            exchange_errors: Vec::new(),
            after_outcome: None,
            after_collection_complete: None,
            after_unexpected_changes: Vec::new(),
            after_errors: Vec::new(),
            errors: Vec::new(),
            attempt_identity: None,
            plan: plan_value,
        }
    }

    fn to_value(&self, journal_path: Option<&Path>) -> Value {
        let mut value = json!({
            "format": JOURNAL_FORMAT,
            "operation": "apply",
            "state": self.state,
            "outcome": self.outcome,
            "serial": self.serial,
            "destination": self.destination,
            "local_unit": self.local_unit,
            "endpoint": {"host": self.endpoint_host, "port": self.endpoint_port},
            "options_verified": self.options_verified,
            "send_intent_recorded": self.send_intent_recorded,
            "attempt_recorded": self.attempt_recorded,
            "attempt_durability_verified": self.attempt_durability_verified,
            "send_attempted": self.send_attempted,
            "exchange_send_attempted": self.exchange_send_attempted,
            "send_completed": self.send_completed,
            "sends": self.sends,
            "receipt_matched": self.receipt_matched,
            "exchange_termination": self.exchange_termination,
            "exchange_errors": self.exchange_errors,
            "after_outcome": self.after_outcome,
            "after_collection_complete": self.after_collection_complete,
            "after_unexpected_changes": self.after_unexpected_changes,
            "after_errors": self.after_errors,
            "errors": self.errors,
            "attempt_identity": self.attempt_identity,
            "plan": self.plan,
            "route_binding": self.route_binding,
            "journal": journal_path.map(|path| path.to_string_lossy().into_owned()),
        });
        if self.plan.get("route").is_some() {
            value["format"] = Value::from(ROUTED_JOURNAL_FORMAT);
            value["reconciliation_evidence"] = json!({
                "format": "cbus-rust-selected-serial-reconciliation-v1",
                "source": "cbus-transport-routed-selected-serial",
                "frame_capture_scope": "commissioning_frames",
                "raw_connection_capture": false,
                "before": self.before_frames,
                "local_identity": self.local_identity_frames,
                "local_options": self.local_options_frames,
                "exchange": self.exchange_frames,
                "after": self.after_frames,
            });
        }
        value
    }
}

/// Record a post-journal failure: push the labeled detail, best-effort write
/// the error evidence to the existing journal (mirroring the oracle `_error`
/// writes-when-journal-exists rule), and keep any secondary journal failure
/// as a note on the primary error instead of replacing it.
fn fail_with_journal(
    journal: &mut RecoveryJournal,
    evidence: &Evidence,
    detail: String,
    wrap: impl FnOnce(String) -> ApplyError,
) -> ApplyError {
    let mut evidence = evidence.clone();
    evidence.state = "failed".to_string();
    // A complete post-send observation is already a definitive classified
    // result. Keep that classification at the top level as well as in
    // `after_outcome`; only an incomplete observation (or a failure before
    // verification could start) remains uncertain.
    evidence.outcome = match (
        evidence.after_collection_complete,
        evidence.after_outcome.as_deref(),
    ) {
        (Some(true), Some(outcome @ ("observed_unchanged" | "observed_unexpected_change"))) => {
            outcome.to_string()
        }
        _ => "uncertain".to_string(),
    };
    evidence.errors.push(detail.clone());
    match journal.write(&evidence.to_value(Some(journal.path()))) {
        Ok(()) => wrap(detail),
        Err(error) => wrap(format!("{detail}; recovery_update: {error}")),
    }
}

/// Normalize accepted JSON equivalences and sort object keys before
/// serializing a sanitized plan value.
///
/// `serde_json::Map` currently sorts without its optional `preserve_order`
/// feature, but explicit sorting keeps the fingerprint stable if workspace
/// features change later. The validator has already normalized JSON escapes.
/// Integral finite floats in JSON fields accepted as generic numbers are
/// normalized to integers inside f64's exact-integer range, and numeric IP
/// endpoint spellings are normalized when an object carries both `host` and
/// `port`. Thus accepted forms such as `5`, `5.0`, and alternate IPv6 text
/// cannot bypass the same-process guard.
fn canonical_plan_fingerprint(value: &Value) -> Vec<u8> {
    fn canonical(value: &Value) -> Value {
        match value {
            Value::Array(items) => Value::Array(items.iter().map(canonical).collect()),
            Value::Object(object) => {
                let mut keys: Vec<&String> = object.keys().collect();
                keys.sort_unstable();
                let mut normalized = Map::new();
                for key in keys {
                    normalized.insert(key.clone(), canonical(&object[key]));
                }
                if normalized.contains_key("port") {
                    let canonical_host = normalized
                        .get("host")
                        .and_then(Value::as_str)
                        .and_then(|host| host.parse::<std::net::IpAddr>().ok())
                        .map(|host| host.to_string());
                    if let Some(host) = canonical_host {
                        normalized.insert("host".to_string(), Value::from(host));
                    }
                }
                Value::Object(normalized)
            }
            Value::Number(number) if number.is_f64() => {
                let numeric = number
                    .as_f64()
                    .expect("a sanitized JSON float is representable as f64");
                let integer = if numeric.fract() != 0.0 {
                    None
                } else if numeric >= 0.0 && numeric < u64::MAX as f64 {
                    let integer = numeric as u64;
                    (integer as f64 == numeric).then(|| Value::from(integer))
                } else if numeric < 0.0 && numeric >= i64::MIN as f64 {
                    let integer = numeric as i64;
                    (integer as f64 == numeric).then(|| Value::from(integer))
                } else {
                    None
                };
                integer.unwrap_or_else(|| value.clone())
            }
            _ => value.clone(),
        }
    }

    serde_json::to_vec(&canonical(value))
        .expect("a validated serde_json::Value is always serializable")
}

fn attempt_id(fingerprint: &[u8]) -> String {
    hex::encode(digest(&SHA256, fingerprint).as_ref())
}

fn resolved_recovery_path(recovery_path: &Path) -> Result<PathBuf, ApplyError> {
    let file_name = recovery_path.file_name().ok_or_else(|| {
        ApplyError::Journal("attempt identity: recovery path must name a file".to_string())
    })?;
    let parent = recovery_path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let directory = fs::canonicalize(parent).map_err(|error| {
        ApplyError::Journal(format!(
            "attempt identity: cannot resolve recovery directory {}: {error}",
            parent.display()
        ))
    })?;
    if !directory.is_dir() {
        return Err(ApplyError::Journal(format!(
            "attempt identity: recovery parent is not a directory: {}",
            directory.display()
        )));
    }
    Ok(directory.join(file_name))
}

fn identity_path(
    fingerprint: &[u8],
    recovery_path: &Path,
    attempt_store: Option<&Path>,
) -> Result<PathBuf, ApplyError> {
    let resolved_journal = resolved_recovery_path(recovery_path)?;
    let directory = match attempt_store {
        Some(store) => fs::canonicalize(store).map_err(|error| {
            ApplyError::Journal(format!(
                "attempt identity: cannot resolve shared store {}: {error}",
                store.display()
            ))
        })?,
        None => resolved_journal
            .parent()
            .expect("resolved journal has a parent")
            .to_path_buf(),
    };
    if !directory.is_dir() {
        return Err(ApplyError::Journal(format!(
            "attempt identity: shared store is not a directory: {}",
            directory.display()
        )));
    }
    let path = directory.join(format!(
        ".cbus-selected-serial-attempt-sha256-{}.json",
        attempt_id(fingerprint)
    ));
    if resolved_journal == path {
        return Err(ApplyError::Journal(
            "attempt identity: recovery journal must not use the identity path".to_string(),
        ));
    }
    Ok(path)
}

/// Deterministic same-directory identity path for a strictly validated plan.
///
/// The path is a SHA-256 digest of canonical sanitized plan semantics in the
/// journal's resolved parent directory. It is not a global deduplication key:
/// callers must preserve and reuse the same directory. This function never
/// touches PCI and does not create the marker.
pub fn attempt_identity_path(raw_plan: &[u8], recovery_path: &Path) -> Result<PathBuf, ApplyError> {
    let (_, value) = validate_plan_document_with_value(raw_plan)
        .map_err(|error| ApplyError::Plan(error.to_string()))?;
    identity_path(&canonical_plan_fingerprint(&value), recovery_path, None)
}

/// Canonical plan marker path in an existing operator-selected shared store.
///
/// The same validated plan and resolved store produce one exclusive marker
/// even when cooperating callers use different recovery-journal directories.
/// This is a local/shared-filesystem guard, not external-controller exclusion.
pub fn attempt_identity_path_in_store(
    raw_plan: &[u8],
    recovery_path: &Path,
    attempt_store: &Path,
) -> Result<PathBuf, ApplyError> {
    let (_, value) = validate_plan_document_with_value(raw_plan)
        .map_err(|error| ApplyError::Plan(error.to_string()))?;
    identity_path(
        &canonical_plan_fingerprint(&value),
        recovery_path,
        Some(attempt_store),
    )
}

fn refuse_existing_identity(path: &Path) -> Result<(), ApplyError> {
    match fs::symlink_metadata(path) {
        Ok(_) => Err(ApplyError::AlreadyApplied(format!(
            "attempt identity already exists at {}; read-only recovery only",
            path.display()
        ))),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(ApplyError::Journal(format!(
            "attempt identity: cannot inspect {}: {error}",
            path.display()
        ))),
    }
}

fn reserve_attempt_identity(
    path: &Path,
    fingerprint: &[u8],
    plan: &Value,
    recovery_path: &Path,
) -> Result<(), ApplyError> {
    let mut marker = RecoveryJournal::new(path)
        .map_err(|error| ApplyError::Journal(format!("attempt identity: {error}")))?;
    let journal = resolved_recovery_path(recovery_path)?;
    let scope = if journal.parent() == path.parent() {
        "resolved_journal_directory"
    } else {
        "operator_selected_attempt_store"
    };
    let record = json!({
        "format": ATTEMPT_FORMAT,
        "operation": "apply",
        "attempt_id": format!("sha256:{}", attempt_id(fingerprint)),
        "scope": scope,
        "journal": journal.to_string_lossy(),
        "plan": plan,
        "send_may_have_occurred": true,
        "read_only_recovery_only": true,
    });
    match marker.write(&record) {
        Ok(()) => Ok(()),
        Err(error) if error.reason() == "exclusive_exists" => {
            Err(ApplyError::AlreadyApplied(format!(
                "attempt identity already exists at {}; read-only recovery only",
                path.display()
            )))
        }
        Err(error) => Err(ApplyError::Journal(format!(
            "attempt identity reservation at {} failed: {error}; no address request sent",
            path.display()
        ))),
    }
}
/// Process-wide canonical fingerprints of plans that already recorded a
/// journaled send intent. Populated only after a journal write durably marks
/// a possible send, so `Plan` and `Preconditions` rejections (no journal, no
/// send) never poison retries.
fn applied_plans() -> &'static Mutex<HashSet<Vec<u8>>> {
    static APPLIED: OnceLock<Mutex<HashSet<Vec<u8>>>> = OnceLock::new();
    APPLIED.get_or_init(|| Mutex::new(HashSet::new()))
}

/// Fingerprint-guard outcome. `Duplicate` and `Poisoned` must both stop
/// before any send: a poisoned lock fails closed (treated as
/// already-applied) and is reported as such, never swallowed to proceed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FingerprintState {
    Fresh,
    Duplicate,
    Poisoned,
}

fn check_fingerprint(fingerprint: &[u8]) -> FingerprintState {
    match applied_plans().lock() {
        Ok(set) => {
            if set.contains(fingerprint) {
                FingerprintState::Duplicate
            } else {
                FingerprintState::Fresh
            }
        }
        Err(_) => FingerprintState::Poisoned,
    }
}

/// Claim a journaled attempt. Returns `Fresh` when this call claimed the
/// plan, `Duplicate` when the plan was already recorded (a replay race
/// lost; the loser must stop before any send), and `Poisoned` when the
/// guard lock is poisoned (fail closed: stop before any send).
fn claim_fingerprint(fingerprint: Vec<u8>) -> FingerprintState {
    match applied_plans().lock() {
        Ok(mut set) => {
            if set.insert(fingerprint) {
                FingerprintState::Fresh
            } else {
                FingerprintState::Duplicate
            }
        }
        Err(_) => FingerprintState::Poisoned,
    }
}

/// One-shot coordinator owning a single plan document.
///
/// The atomic claim happens before validation or PCI I/O and refuses every
/// concurrent or later `apply`, including calls with a different journal
/// path. One object represents one operator decision; create a new object
/// only after a definite no-send result and a fresh decision to retry.
#[derive(Debug)]
pub struct ApplyOnce {
    plan: Vec<u8>,
    applied: AtomicBool,
}

impl ApplyOnce {
    /// Own the raw plan document for a single apply.
    pub fn new(raw_plan: &[u8]) -> Self {
        Self {
            plan: raw_plan.to_vec(),
            applied: AtomicBool::new(false),
        }
    }

    /// Apply the owned plan once. A second call fails with
    /// [`ApplyError::AlreadyApplied`] before any I/O.
    pub async fn apply(
        &self,
        pci: &PciClient,
        recovery_path: &Path,
        options: ApplyOptions<'_>,
    ) -> Result<ApplySuccess, ApplyError> {
        self.apply_bound(pci, recovery_path, options, None).await
    }

    /// Apply once with a project binding for a routed selected-serial plan.
    /// The binding is revalidated before I/O and again before durable intent/send.
    pub async fn apply_bound(
        &self,
        pci: &PciClient,
        recovery_path: &Path,
        options: ApplyOptions<'_>,
        binding: Option<&RouteBinding>,
    ) -> Result<ApplySuccess, ApplyError> {
        if self
            .applied
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(ApplyError::AlreadyApplied(
                "apply: plan was already applied; replay refused without send".to_string(),
            ));
        }
        apply_plan_bound(&self.plan, pci, recovery_path, options, binding).await
    }
}

/// Bounded recovery record for read-only follow-up.
///
/// The embedded plan is strictly validated. Other evidence fields are an
/// unauthenticated historical record and must never authorize another send.
#[derive(Debug, Clone)]
pub struct RecoveryRecord {
    /// Strictly validated embedded plan.
    pub plan: ValidatedPlan,
    /// Canonical sanitized plan bytes suitable for [`crate::verify::verify_plan_bound`].
    pub plan_document: Vec<u8>,
    /// Complete bounded journal or attempt-marker document for diagnosis.
    pub evidence: Value,
    /// Always true for an accepted apply journal or attempt marker: a crash
    /// may have happened after bytes reached the endpoint.
    pub send_may_have_occurred: bool,
}

/// Read back a journal for independent read-only verification.
///
/// The single guarded read refuses symlinks, non-regular files, and content
/// beyond the journal size bound. An apply journal must have durable send
/// intent and conservative `send_attempted=true`. A durable attempt marker
/// may also be used if interruption preceded journal creation. Neither
/// record ever authorizes replay, regardless of later observation.
/// The embedded plan is revalidated from the journal bytes. Envelope problems are
/// [`ApplyError::Journal`]; an invalid embedded plan is [`ApplyError::Plan`].
pub fn load_recovery(journal_path: &Path) -> Result<RecoveryRecord, ApplyError> {
    let probe = RecoveryJournal::new(journal_path)
        .map_err(|error| ApplyError::Journal(format!("recovery open: {error}")))?;
    let raw = probe
        .read_current()
        .map_err(|error| ApplyError::Journal(format!("recovery read: {error}")))?;
    let (value, _) = parse_strict_json_value(&raw)
        .map_err(|error| ApplyError::Journal(format!("recovery corrupt: {error}")))?;
    let document = value.as_object().ok_or_else(|| {
        ApplyError::Journal("recovery corrupt: journal must be a JSON object".to_string())
    })?;
    if document.get("operation") != Some(&Value::from("apply")) {
        return Err(ApplyError::Journal(
            "recovery corrupt: journal is not an apply operation".to_string(),
        ));
    }
    match document.get("format").and_then(Value::as_str) {
        Some(JOURNAL_FORMAT | ROUTED_JOURNAL_FORMAT) => {
            for field in ["send_intent_recorded", "attempt_recorded", "send_attempted"] {
                if document.get(field) != Some(&Value::Bool(true)) {
                    return Err(ApplyError::Journal(format!(
                        "recovery ambiguous: apply journal lacks durable {field} evidence"
                    )));
                }
            }
        }
        Some(ATTEMPT_FORMAT) => {
            for field in ["send_may_have_occurred", "read_only_recovery_only"] {
                if document.get(field) != Some(&Value::Bool(true)) {
                    return Err(ApplyError::Journal(format!(
                        "recovery ambiguous: attempt marker lacks {field}"
                    )));
                }
            }
            if !matches!(
                document.get("scope").and_then(Value::as_str),
                Some("resolved_journal_directory" | "operator_selected_attempt_store")
            ) || !document.get("journal").is_some_and(Value::is_string)
            {
                return Err(ApplyError::Journal(
                    "recovery ambiguous: invalid attempt marker scope or journal".to_string(),
                ));
            }
        }
        _ => {
            return Err(ApplyError::Journal(format!(
                "recovery corrupt: expected {JOURNAL_FORMAT}, {ROUTED_JOURNAL_FORMAT} or {ATTEMPT_FORMAT}"
            )));
        }
    }
    let plan_value = document.get("plan").ok_or_else(|| {
        ApplyError::Journal("recovery ambiguous: journal carries no embedded plan".to_string())
    })?;
    let plan_raw = serde_json::to_vec(plan_value).map_err(|error| {
        ApplyError::Journal(format!(
            "recovery corrupt: embedded plan unencodable: {error}"
        ))
    })?;
    let (plan, sanitized) = validate_plan_document_with_value(&plan_raw)
        .map_err(|error| ApplyError::Plan(format!("recovery plan: {error}")))?;
    if document.get("format") == Some(&Value::from(ATTEMPT_FORMAT)) {
        let expected = format!(
            "sha256:{}",
            attempt_id(&canonical_plan_fingerprint(&sanitized))
        );
        if document.get("attempt_id") != Some(&Value::from(expected)) {
            return Err(ApplyError::Journal(
                "recovery corrupt: attempt ID does not match embedded plan".to_string(),
            ));
        }
    }
    Ok(RecoveryRecord {
        plan,
        plan_document: canonical_plan_fingerprint(&sanitized),
        evidence: value,
        send_may_have_occurred: true,
    })
}

/// Require a complete fresh bookended observation equal to the plan's
/// embedded `before` snapshot.
///
/// Reusing [`crate::verify::verify_plan_bound`] keeps both local commissioning lanes held across the
/// opening MMI, all IDENTIFY4 windows, and the closing MMI. Only
/// [`VerifyOutcome::ObservedUnchanged`] is a valid precondition result. Invalid
/// caller bounds, collection errors, bookend drift, an already-applied plan,
/// or any other divergence all stop before journal creation and before the
/// address command.
async fn check_fresh_preconditions(
    raw_plan: &[u8],
    pci: &PciClient,
    options: VerifyOptions,
    binding: Option<&RouteBinding>,
) -> Result<VerifyEvidence, ApplyError> {
    let fresh = verify_plan_bound(raw_plan, pci, options, binding)
        .await
        .map_err(|error| ApplyError::Preconditions(format!("fresh_before: {error}")))?;
    if fresh.after_collection_complete && fresh.outcome == VerifyOutcome::ObservedUnchanged {
        return Ok(fresh);
    }
    let errors = if fresh.errors.is_empty() {
        "none".to_string()
    } else {
        fresh.errors.join("; ")
    };
    Err(ApplyError::Preconditions(format!(
        "fresh_before: fresh bookended inventory classified {} (complete={}, errors={errors})",
        fresh.outcome.as_str(),
        fresh.after_collection_complete,
    )))
}

/// Validate a plan, gate on live local options plus a fresh inventory, journal one send, and verify.
///
/// See the module docs for the ordering contract, the trust gap, and the
/// error-variant guarantees.
pub async fn apply_plan(
    raw_plan: &[u8],
    pci: &PciClient,
    recovery_path: &Path,
    options: ApplyOptions<'_>,
) -> Result<ApplySuccess, ApplyError> {
    apply_plan_bound(raw_plan, pci, recovery_path, options, None).await
}

/// Execute one topology-bound routed attempt, preserving the one-shot journal contract.
/// Missing or stale bindings refuse before any PCI byte, marker, or journal.
/// An uncertain send is never retried; use [`crate::verify::verify_plan_bound`] for recovery.
pub async fn apply_plan_bound(
    raw_plan: &[u8],
    pci: &PciClient,
    recovery_path: &Path,
    options: ApplyOptions<'_>,
    binding: Option<&RouteBinding>,
) -> Result<ApplySuccess, ApplyError> {
    // No I/O yet: a rejection here is Plan and implies no journal and no send.
    let (plan, plan_value) = validate_plan_document_with_value(raw_plan)
        .map_err(|error| ApplyError::Plan(error.to_string()))?;
    match binding {
        Some(binding) => binding
            .validate_plan(&plan)
            .map_err(|error| ApplyError::Plan(error.to_string()))?,
        None => {
            refuse_routed_execution(&plan).map_err(|error| ApplyError::Plan(error.to_string()))?
        }
    }
    let fingerprint = canonical_plan_fingerprint(&plan_value);
    // The durable identity is scoped to the resolved journal directory or
    // explicit shared store. An existing path (including a symlink or corrupt
    // record) fails closed before this API observes the bus.
    if options.attempt_store.is_some() && !options.durable_attempt_identity {
        return Err(ApplyError::Journal(
            "attempt identity: shared store requires durable_attempt_identity".to_string(),
        ));
    }
    let identity = if options.durable_attempt_identity {
        let path = identity_path(&fingerprint, recovery_path, options.attempt_store)?;
        refuse_existing_identity(&path)?;
        Some(path)
    } else {
        None
    };
    // Replay guard before any I/O: a plan that already recorded a journaled
    // attempt is refused regardless of the journal path offered this time.
    // A poisoned guard fails closed with the same refusal before any I/O.
    match check_fingerprint(&fingerprint) {
        FingerprintState::Fresh => {}
        FingerprintState::Duplicate => {
            return Err(ApplyError::AlreadyApplied(
                "apply: plan was already applied; replay refused without send".to_string(),
            ));
        }
        FingerprintState::Poisoned => {
            return Err(ApplyError::AlreadyApplied(
                "apply: fingerprint guard poisoned; replay refused without send".to_string(),
            ));
        }
    }
    // Embed exactly the validator's sanitized value. This retains every
    // validated semantic field without reparsing raw numeric forms that the
    // strict scanner deliberately normalizes before serde decoding.
    let mut evidence = Evidence::new(&plan, plan_value.clone());
    evidence.route_binding = binding.map(RouteBinding::evidence);

    // A complete MMI/IDENTIFY4/MMI observation must prove the live bus still
    // equals the plan's embedded `before`. The observation's deadline also
    // validates caller options before any address command can be sent.
    let before = check_fresh_preconditions(raw_plan, pci, options.verify, binding).await?;
    evidence.before_frames = before.reconciliation_inventory;

    // Re-read the local option immediately after the potentially long
    // inventory walk and immediately before journal creation. Any failure
    // leaves no journal behind and sends no address command.
    let read_options = async {
        let mut identity_capture = None;
        if plan.is_routed() {
            // The remote walk can be long. Re-pin the direct PCI identity
            // immediately before the local option check and durable intent.
            let (replies, capture) = pci
                .selected_serial_local_identity_guarded_captured(plan.local_unit)
                .await?;
            if replies.len() != 1
                || crate::inventory::parse_serial_number(&replies[0])
                    .ok()
                    .flatten()
                    != Some(plan.expected_local_serial.clone())
            {
                return Err(std::io::Error::new(
                    ErrorKind::InvalidData,
                    "local PCI serial changed before selected-serial send",
                ));
            }
            identity_capture = Some(capture);
        }
        if plan.is_routed() {
            pci.selected_serial_local_options_guarded_captured(plan.local_unit)
                .await
                .map(|(options, capture)| (options, identity_capture, Some(capture)))
        } else {
            pci.recall_parameter(plan.local_unit, 66, 1)
                .await
                .map(|options| (options, None, None))
        }
    };
    let (observed, identity_capture, options_capture) = if plan.is_routed() {
        match tokio::time::timeout(options.verify.inventory.total_deadline, read_options).await {
            Ok(result) => result,
            Err(_) => {
                pci.shutdown().await;
                Err(std::io::Error::new(
                    ErrorKind::TimedOut,
                    "local pre-send identity/options deadline elapsed",
                ))
            }
        }
    } else {
        read_options.await
    }
    .map_err(|error| ApplyError::Preconditions(format!("local_options: {error}")))?;
    if observed != [5] {
        return Err(ApplyError::Preconditions(format!(
            "local_options: local PCI parameter 66 must equal 05, observed {observed:02X?}"
        )));
    }
    evidence.options_verified = Some(observed);
    evidence.local_identity_frames = identity_capture;
    evidence.local_options_frames = options_capture;
    if let Some(binding) = binding {
        binding
            .assert_fresh()
            .map_err(|error| ApplyError::Preconditions(error.to_string()))?;
    }
    // Reserve an independent recovery handle before journal creation and
    // before the one-shot address request. A crash after this point may leave
    // only the marker; it embeds the validated plan for read-only verify.
    if let Some(path) = identity.as_deref() {
        reserve_attempt_identity(path, &fingerprint, &plan_value, recovery_path)?;
        evidence.attempt_identity = Some(path.to_string_lossy().into_owned());
    }
    // Durably mark a possible send before invoking the shared-PCI one-shot. The
    // first and therefore exclusive journal record is already conservative:
    // after it exists, recovery must assume the send may have reached the
    // endpoint even when no receipt or later update exists.
    evidence.state = "send_intent_recorded".to_string();
    evidence.send_intent_recorded = true;
    evidence.attempt_recorded = true;
    evidence.send_attempted = true;
    let mut journal = RecoveryJournal::new(recovery_path)
        .map_err(|error| ApplyError::Journal(format!("journal create: {error}")))?;
    journal
        .write(&evidence.to_value(Some(journal.path())))
        .map_err(|error| ApplyError::Journal(format!("journal send intent: {error}")))?;

    // Claim the plan fingerprint after durable intent exists. A later call
    // with the same canonical sanitized value — any journal path — stops
    // here. A lost race fails without touching the wire; its journal already
    // carries conservative intent evidence.
    match claim_fingerprint(fingerprint) {
        FingerprintState::Fresh => {}
        FingerprintState::Duplicate => {
            return Err(fail_with_journal(
                &mut journal,
                &evidence,
                "already_applied: plan was already applied; replay refused without send"
                    .to_string(),
                ApplyError::AlreadyApplied,
            ));
        }
        FingerprintState::Poisoned => {
            return Err(fail_with_journal(
                &mut journal,
                &evidence,
                "already_applied: fingerprint guard poisoned; replay refused without send"
                    .to_string(),
                ApplyError::AlreadyApplied,
            ));
        }
    }

    // Persist that the preceding intent record completed its durability
    // checks. Failure still stops before invoking the send primitive; the first
    // record remains conservative and the in-process fingerprint stays
    // claimed, so neither path authorizes replay.
    evidence.attempt_durability_verified = true;
    journal
        .write(&evidence.to_value(Some(journal.path())))
        .map_err(|error| ApplyError::Journal(format!("journal send intent proof: {error}")))?;

    // Invoke the existing shared-session programming transaction only after
    // durable intent. The method re-encodes the plan fields, requires exact
    // equality with request_bytes, atomically reserves the literal `g`, and
    // submits those supplied bytes exactly once outside the retry table.
    if let Some(binding) = binding {
        if let Err(error) = binding.assert_fresh() {
            evidence.exchange_send_attempted = Some(false);
            evidence.exchange_termination = Some("write_not_started".into());
            return Err(fail_with_journal(
                &mut journal,
                &evidence,
                format!("pre_send_route_binding: {error}"),
                ApplyError::Send,
            ));
        }
    }
    let exchange = match if let Some(route) = plan.route.as_deref() {
        pci.send_selected_serial_plan_once_routed(
            route,
            &plan.serial,
            plan.destination,
            plan.command_checksum,
            b'g',
            &plan.request_bytes,
        )
        .await
    } else {
        pci.send_selected_serial_plan_once(
            &plan.serial,
            plan.destination,
            plan.command_checksum,
            b'g',
            &plan.request_bytes,
        )
        .await
    } {
        Ok(exchange) => exchange,
        Err(error) => {
            evidence.exchange_send_attempted = Some(error.send_attempted);
            evidence.send_completed = error.send_completed;
            evidence.sends = u32::from(error.send_completed);
            evidence.exchange_termination = Some(
                if error.send_completed {
                    "capture_error"
                } else if error.send_attempted {
                    "write_completion_uncertain"
                } else {
                    "write_not_started"
                }
                .to_string(),
            );
            evidence.exchange_errors.push(error.to_string());
            return Err(fail_with_journal(
                &mut journal,
                &evidence,
                format!("send: shared PCI selected-serial transaction: {error}"),
                ApplyError::Send,
            ));
        }
    };
    if exchange.request != plan.request_bytes || !exchange.send_completed {
        return Err(fail_with_journal(
            &mut journal,
            &evidence,
            "send: shared PCI exchange did not complete the exact validated request".to_string(),
            ApplyError::Send,
        ));
    }
    evidence.exchange_send_attempted = Some(true);
    evidence.send_completed = true;
    evidence.sends = 1;
    evidence.receipt_matched = Some(exchange.receipt_matched);
    evidence.exchange_frames = exchange.frame_capture;
    evidence.exchange_termination = Some("response_window_elapsed".to_string());
    evidence.state = "receipt_collected".to_string();
    journal
        .write(&evidence.to_value(Some(journal.path())))
        .map_err(|error| ApplyError::Journal(format!("journal receipt: {error}")))?;

    // Post-send observation: any failure or divergence is a distinct variant
    // documenting that one exact send already completed.
    let after = match verify_plan_bound(raw_plan, pci, options.verify, binding).await {
        Ok(after) => after,
        Err(error) => {
            return Err(fail_with_journal(
                &mut journal,
                &evidence,
                format!("post_send_observation: verify init: {error}"),
                ApplyError::PostSendObservation,
            ));
        }
    };
    evidence.after_outcome = Some(after.outcome.as_str().to_string());
    evidence.after_collection_complete = Some(after.after_collection_complete);
    evidence.after_unexpected_changes = after
        .unexpected_changes
        .iter()
        .map(|diff| {
            json!({
                "address": diff.address,
                "expected_serials": diff.expected_serials,
                "observed_serials": diff.observed_serials,
                "expected_state": diff.expected_state,
                "observed_state": diff.observed_state,
            })
        })
        .collect();
    evidence.after_errors = after.errors.clone();
    evidence.after_frames = after.reconciliation_inventory.clone();
    if after.outcome != VerifyOutcome::ObservedExpectedChange {
        return Err(fail_with_journal(
            &mut journal,
            &evidence,
            format!(
                "post_send_observation: after_observation {} (complete={}): {}",
                after.outcome.as_str(),
                after.after_collection_complete,
                after.errors.join("; "),
            ),
            ApplyError::PostSendObservation,
        ));
    }
    evidence.state = "after_observed".to_string();
    evidence.outcome = "observed_expected_change".to_string();
    journal
        .write(&evidence.to_value(Some(journal.path())))
        .map_err(|error| ApplyError::Journal(format!("journal after: {error}")))?;
    Ok(ApplySuccess {
        serial: plan.serial.clone(),
        destination: plan.destination,
        receipt_matched: exchange.receipt_matched,
        verify: after,
        journal_path: journal.path().to_path_buf(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Golden vector shared with the Python coordinator
    /// (`test_canonical_bytes_match_rust_fingerprint_encoder`): any drift in
    /// either encoder splits the cross-implementation attempt-marker
    /// namespace, so both suites pin these exact bytes.
    #[test]
    fn canonical_fingerprint_bytes_match_python_vector() {
        let raw = br#"{"z":[1.0,-0.0,30.0,0.1,1e-5,1e-6,1.5e-7,1e15,1000000000000000.5,1e16,1.5e20,-2.5,5e-324,1.7976931348623157e308,123456.789,-1e-300],"big":123456789012345678901234567890,"negbig":-123456789012345678901234567890,"u64":18446744073709551615,"i64":-9223372036854775808,"text":"\u00e9\ud83d\ude00\u0000\u001f\u007f\n\t\b\f\r\"\\\/","endpoint":{"port":10001,"host":"::FFFF:10.0.0.1"},"v6":{"host":"2001:DB8:0:0:1:0:0:1","port":1},"named":{"host":"localhost","port":1},"nohost":{"host":"127.000.0.1","port":1},"noport":{"host":"::FFFF:10.0.0.1"},"flags":[true,false,null]}"#;
        let (value, _) = parse_strict_json_value(raw).unwrap();
        let expected = concat!(
            r#"{"big":1e+300,"endpoint":{"host":"::ffff:10.0.0.1","port":10001},"#,
            r#""flags":[true,false,null],"i64":-9223372036854775808,"#,
            r#""named":{"host":"localhost","port":1},"negbig":-1e+300,"#,
            r#""nohost":{"host":"127.000.0.1","port":1},"noport":{"host":"::FFFF:10.0.0.1"},"#,
            "\"text\":\"\u{e9}\u{1f600}\\u0000\\u001f\u{7f}\\n\\t\\b\\f\\r\\\"\\\\/\",",
            r#""u64":18446744073709551615,"v6":{"host":"2001:db8::1:0:0:1","port":1},"#,
            r#""z":[1,0,30,0.1,0.00001,1e-6,1.5e-7,1000000000000000,1000000000000000.5,"#,
            r#"10000000000000000,1.5e+20,-2.5,5e-324,1.7976931348623157e+308,123456.789,-1e-300]}"#,
        );
        assert_eq!(
            String::from_utf8(canonical_plan_fingerprint(&value)).unwrap(),
            expected
        );
    }
}
