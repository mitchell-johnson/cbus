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
//! 2. Preconditions reuse [`verify_plan`] for a fresh observation held
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
//!    positive confirmation plus exact direct receipt correlated, but a
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
//! local unit, and expected local serial are never bound here to the
//! supplied client. The caller must connect the client to the plan's endpoint,
//! establish its local identity, and own all commissioning activity
//! exclusively for the whole call. The same connection is used sequentially
//! for preconditions, the address transaction, and verification. Caller
//! options separately bound the fresh and after observations.
//!
//! Journal recovery is a Rust-local format (`cbus-selected-serial-apply-v1`)
//! with no cross-implementation guarantee: Python coordinator journals
//! (`cbus-selected-serial-result-v1`) are neither read nor written here, and
//! these journals are not readable by the Python coordinator.
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
//! distinct. Across processes or restarts, replay prevention is the
//! operator-selected stable journal path, its exclusive creation
//! (`O_CREAT | O_EXCL`), and preservation of that file. A caller that chooses
//! a different path after restart is not globally deduplicated. Every created
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
use crate::journal::RecoveryJournal;
use crate::plan::{parse_strict_json_value, validate_plan_document_with_value, ValidatedPlan};
use crate::verify::{verify_plan, VerifyEvidence, VerifyOptions, VerifyOutcome};
use crate::PciClient;
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex, OnceLock,
};

/// Rust-local journal format written by [`apply_plan`].
const JOURNAL_FORMAT: &str = "cbus-selected-serial-apply-v1";

/// Tunables for [`apply_plan`].
#[derive(Debug, Clone, Copy, Default)]
pub struct ApplyOptions {
    /// Caller bounds used independently for the fresh-before and post-send
    /// observations, replacing plan timing for both reads.
    pub verify: VerifyOptions,
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
    /// The full validated plan document, embedded so [`load_recovery`] can
    /// strictly revalidate the intent this journal records.
    plan: Value,
}

impl Evidence {
    fn new(plan: &ValidatedPlan, plan_value: Value) -> Self {
        Self {
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
            plan: plan_value,
        }
    }

    fn to_value(&self, journal_path: Option<&Path>) -> Value {
        json!({
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
            "plan": self.plan,
            "journal": journal_path.map(|path| path.to_string_lossy().into_owned()),
        })
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
        options: ApplyOptions,
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
        apply_plan(&self.plan, pci, recovery_path, options).await
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
    /// Canonical sanitized plan bytes suitable for [`verify_plan`].
    pub plan_document: Vec<u8>,
    /// Complete bounded journal document for reporting and diagnosis.
    pub evidence: Value,
    /// Always true for an accepted apply journal: the durable send intent
    /// means a crash may have happened after bytes reached the endpoint.
    pub send_may_have_occurred: bool,
}

/// Read back a journal for independent read-only verification.
///
/// The single guarded read refuses symlinks, non-regular files, and content
/// beyond the journal size bound. The envelope must be an apply record with
/// durable send intent and conservative `send_attempted=true`; that marker
/// never authorizes replay, regardless of any later classified observation.
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
    if document.get("format") != Some(&Value::from(JOURNAL_FORMAT)) {
        return Err(ApplyError::Journal(format!(
            "recovery corrupt: expected journal format {JOURNAL_FORMAT}"
        )));
    }
    if document.get("operation") != Some(&Value::from("apply")) {
        return Err(ApplyError::Journal(
            "recovery corrupt: journal is not an apply operation".to_string(),
        ));
    }
    for field in ["send_intent_recorded", "attempt_recorded", "send_attempted"] {
        if document.get(field) != Some(&Value::Bool(true)) {
            return Err(ApplyError::Journal(format!(
                "recovery ambiguous: apply journal lacks durable {field} evidence"
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
/// Reusing [`verify_plan`] keeps both local commissioning lanes held across the
/// opening MMI, all IDENTIFY4 windows, and the closing MMI. Only
/// [`VerifyOutcome::ObservedUnchanged`] is a valid precondition result. Invalid
/// caller bounds, collection errors, bookend drift, an already-applied plan,
/// or any other divergence all stop before journal creation and before the
/// address command.
async fn check_fresh_preconditions(
    raw_plan: &[u8],
    pci: &PciClient,
    options: VerifyOptions,
) -> Result<(), ApplyError> {
    let fresh = verify_plan(raw_plan, pci, options)
        .await
        .map_err(|error| ApplyError::Preconditions(format!("fresh_before: {error}")))?;
    if fresh.after_collection_complete && fresh.outcome == VerifyOutcome::ObservedUnchanged {
        return Ok(());
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
    options: ApplyOptions,
) -> Result<ApplySuccess, ApplyError> {
    // No I/O yet: a rejection here is Plan and implies no journal and no send.
    let (plan, plan_value) = validate_plan_document_with_value(raw_plan)
        .map_err(|error| ApplyError::Plan(error.to_string()))?;
    let fingerprint = canonical_plan_fingerprint(&plan_value);
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

    // A complete MMI/IDENTIFY4/MMI observation must prove the live bus still
    // equals the plan's embedded `before`. The observation's deadline also
    // validates caller options before any address command can be sent.
    check_fresh_preconditions(raw_plan, pci, options.verify).await?;

    // Re-read the local option immediately after the potentially long
    // inventory walk and immediately before journal creation. Any failure
    // leaves no journal behind and sends no address command.
    let observed = pci
        .recall_parameter(plan.local_unit, 66, 1)
        .await
        .map_err(|error| {
            ApplyError::Preconditions(format!(
                "local_options: local PCI parameter 66 recall failed: {error}"
            ))
        })?;
    if observed != [5] {
        return Err(ApplyError::Preconditions(format!(
            "local_options: local PCI parameter 66 must equal 05, observed {observed:02X?}"
        )));
    }
    evidence.options_verified = Some(observed);
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
    let exchange = match pci
        .send_selected_serial_plan_once(
            &plan.serial,
            plan.destination,
            plan.command_checksum,
            b'g',
            &plan.request_bytes,
        )
        .await
    {
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
    evidence.exchange_termination = Some("response_window_elapsed".to_string());
    evidence.state = "receipt_collected".to_string();
    journal
        .write(&evidence.to_value(Some(journal.path())))
        .map_err(|error| ApplyError::Journal(format!("journal receipt: {error}")))?;

    // Post-send observation: any failure or divergence is a distinct variant
    // documenting that one exact send already completed.
    let after = match verify_plan(raw_plan, pci, options.verify).await {
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
