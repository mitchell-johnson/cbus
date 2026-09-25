//! Shared-PCI serial snapshot classification against a selected-serial plan.
//!
//! Original plan bytes are scanned and validated before any I/O. A fresh pair
//! of MMI bookends and one IDENTIFY4 window per present address are compared with
//! the plan's before/expected snapshots. IDENTIFY1/2 are never requested.
//!
//! This is not the Python coordinator's transport proof. The supplied client
//! cannot be bound here to the plan's endpoint, local PCI serial, or transport
//! settings. The caller establishes those facts and the client's lifetime.
//! Caller options bound the entire observation, including lane acquisition and
//! closing MMI; shared PCI correlation, checksums and quiet windows still apply.
//! Cancelled queued requests are skipped before writing, but an already-started
//! write or an in-flight retry cannot be retracted. An unconfirmed cancelled
//! write keeps its confirmation code reserved until its acknowledgement or a
//! 30-second reservation timeout; queued retries are cancelled with their read.
//! Started retransmissions keep the generation reserved even after an ACK,
//! through 30 seconds after the latest retry completion/ACK and never while
//! any retry is still writing.
//! Wire quiescence after return
//! is not verified. After a deadline or cancellation, stop using this client,
//! close its transport, and establish a fresh connection before further I/O.
//!
//! Both local MMI and programming lanes stay held across the observation.
//! Ordinary non-commissioning traffic can interleave, and external bus traffic
//! is not excluded: the snapshot remains non-atomic. Raw sends and resets remain
//! caller-controlled and must not be used for concurrent commissioning.
//! No address-changing request
//! or journal write is made. The whole operation is never replayed, but the
//! underlying client may retry confirmed read packets. Matching state proves
//! neither movement cause nor persistence, and no raw transport proof is emitted.

use crate::inventory::{parse_serial_number, InventoryOptions};
use crate::pci::PciClient;
use crate::plan::{validate_plan_document_with_value, PlanError};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// Fresh-inventory classification, mirroring the oracle outcome strings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerifyOutcome {
    /// Fresh inventory equals the embedded `expected_after`.
    ObservedExpectedChange,
    /// Fresh inventory equals the embedded `before`.
    ObservedUnchanged,
    /// Fresh inventory equals neither embedded snapshot.
    ObservedUnexpectedChange,
    /// The observation is incomplete or cannot establish a consistent,
    /// healthy identity snapshot.
    Uncertain,
}

impl VerifyOutcome {
    /// Oracle evidence string for this outcome.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ObservedExpectedChange => "observed_expected_change",
            Self::ObservedUnchanged => "observed_unchanged",
            Self::ObservedUnexpectedChange => "observed_unexpected_change",
            Self::Uncertain => "uncertain",
        }
    }
}

/// Per-address difference against the embedded expectation, mirroring the
/// oracle `unexpected_changes` rows.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PerAddressDiff {
    /// Unit address that differs.
    pub address: u8,
    /// Serial list the plan expects at this address (empty when absent).
    pub expected_serials: Vec<String>,
    /// Serial list freshly observed at this address (empty when absent).
    pub observed_serials: Vec<String>,
    /// MMI state the plan expects at this address.
    pub expected_state: u64,
    /// MMI state freshly observed at this address.
    pub observed_state: u64,
}

/// Identities + MMI states in oracle `_expected` proof shape.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BusSnapshot {
    /// 256 MMI states in ascending address order.
    pub states: Vec<u64>,
    /// Address-sorted `(address, serials)` rows; serials sorted by their
    /// numeric `first.second` key.
    pub identities: Vec<(u8, Vec<String>)>,
}

/// Failure to extract embedded snapshots from a plan document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SnapshotError {
    message: String,
}

impl SnapshotError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }

    /// Human-readable detail.
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl std::fmt::Display for SnapshotError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "snapshot: {}", self.message)
    }
}

impl std::error::Error for SnapshotError {}

/// Read-only verify evidence, mirroring the oracle `_base` defaults:
/// `outcome` defaults to `uncertain`, `after_collection_complete` is false
/// until a complete collection exists, `expected_identity_change` is set
/// only on the expected change, `atomic_observation` is always false,
/// `firmware_persistence_verified` and `physical_compatibility_verified`
/// are always false, and `exclusive_ownership_required` is always true.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifyEvidence {
    /// Classified outcome.
    pub outcome: VerifyOutcome,
    /// True only when the fresh inventory equals the embedded expectation.
    pub expected_identity_change: bool,
    /// Per-address diffs against the embedded expectation (empty exactly
    /// when the fresh inventory equals it; also empty when uncertain).
    pub unexpected_changes: Vec<PerAddressDiff>,
    /// All identity probes and both complete MMI reads finished. This can be
    /// true even when consistency or MMI health checks reject the snapshot.
    pub after_collection_complete: bool,
    /// Phase errors (collection, MMI, membership, snapshot mismatch).
    pub errors: Vec<String>,
    /// Always false: observations are sequential, never atomic.
    pub atomic_observation: bool,
    /// Always false: serial inventories never verify firmware persistence.
    pub firmware_persistence_verified: bool,
    /// Always false: serial inventories never verify physical compatibility.
    pub physical_compatibility_verified: bool,
    /// Always true: the caller must exclusively own the PCI and all
    /// commissioning activity.
    pub exclusive_ownership_required: bool,
    /// Always false: verify observes bus state, never proves movement cause.
    pub movement_verified: bool,
    /// Always false: verify observes bus state, never proves persistence.
    pub persistence_verified: bool,
    /// Always false: caller timing and shared-client wire behavior replace the
    /// validated plan's transport settings.
    pub plan_transport_settings_enforced: bool,
    /// Always false: the supplied client has no verified plan endpoint binding.
    pub endpoint_binding_verified: bool,
    /// Always false: a plan serial does not establish the supplied PCI identity.
    pub local_serial_binding_verified: bool,
    /// Always false: no Python-equivalent raw transport receipt is produced.
    pub raw_transport_evidence_verified: bool,
    /// Always true: the existing client may retry confirmed read packets.
    pub underlying_read_retries_possible: bool,
    /// Always zero: the entire verification observation is never replayed.
    pub whole_operation_replays: u32,
    /// Always true: ordinary SAL traffic is outside the commissioning lanes.
    pub non_commissioning_traffic_may_interleave: bool,
    /// Always false: return does not prove all in-flight wire activity stopped.
    pub wire_quiescence_after_return_verified: bool,
    /// Always true: after a deadline or external cancellation, close the old
    /// transport and establish a new client before further I/O.
    pub discard_client_after_deadline_or_cancellation: bool,
}

impl VerifyEvidence {
    fn uncertain(errors: Vec<String>, after_collection_complete: bool) -> Self {
        Self {
            outcome: VerifyOutcome::Uncertain,
            expected_identity_change: false,
            unexpected_changes: Vec::new(),
            after_collection_complete,
            errors,
            atomic_observation: false,
            firmware_persistence_verified: false,
            physical_compatibility_verified: false,
            exclusive_ownership_required: true,
            movement_verified: false,
            persistence_verified: false,
            plan_transport_settings_enforced: false,
            endpoint_binding_verified: false,
            local_serial_binding_verified: false,
            raw_transport_evidence_verified: false,
            underlying_read_retries_possible: true,
            whole_operation_replays: 0,
            non_commissioning_traffic_may_interleave: true,
            wire_quiescence_after_return_verified: false,
            discard_client_after_deadline_or_cancellation: true,
        }
    }
}

/// Failure to validate the plan document or extract its embedded
/// snapshots before any bus observation. Callers fix the document and
/// retry; no `VerifyEvidence` exists because no after-observation ran.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VerifyInitError {
    /// The plan document failed [`crate::plan::validate_plan_document`].
    Plan(String),
    /// Snapshot extraction ([`extract_snapshots`]) failed.
    Snapshot(String),
}

impl std::fmt::Display for VerifyInitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Plan(message) => write!(f, "plan: {message}"),
            Self::Snapshot(message) => write!(f, "snapshot: {message}"),
        }
    }
}

impl std::error::Error for VerifyInitError {}

impl From<PlanError> for VerifyInitError {
    fn from(error: PlanError) -> Self {
        Self::Plan(error.to_string())
    }
}

impl From<SnapshotError> for VerifyInitError {
    fn from(error: SnapshotError) -> Self {
        Self::Snapshot(error.message().to_string())
    }
}

/// Options for [`verify_plan`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct VerifyOptions {
    /// Caller-selected bounds, replacing plan timing. `total_deadline` covers
    /// lane acquisition, opening MMI, serial windows, and closing MMI (maximum
    /// one hour); `per_address_timeout` bounds IDENTIFY4 (maximum five minutes).
    /// Both must be positive. Shared-client shorter internal limits still apply.
    pub inventory: InventoryOptions,
}

fn sort_key(serial: &str) -> (u64, u64) {
    let mut parts = serial.split('.');
    (
        parts
            .next()
            .and_then(|p| p.parse().ok())
            .unwrap_or(u64::MAX),
        parts
            .next()
            .and_then(|p| p.parse().ok())
            .unwrap_or(u64::MAX),
    )
}

fn normalize_identities(mut identities: Vec<(u8, Vec<String>)>) -> Vec<(u8, Vec<String>)> {
    for (_, serials) in &mut identities {
        serials.sort_by_key(|s| sort_key(s));
        serials.dedup();
    }
    identities.sort_by_key(|(address, _)| *address);
    identities
}

fn parse_states(value: &Value) -> Result<Vec<u64>, SnapshotError> {
    let fail = || SnapshotError::new("snapshot states must be 256 integers");
    let items = value.as_array().ok_or_else(fail)?;
    if items.len() != 256 {
        return Err(fail());
    }
    items
        .iter()
        .map(|item| item.as_u64().ok_or_else(fail))
        .collect()
}

fn parse_identities(value: &Value) -> Result<Vec<(u8, Vec<String>)>, SnapshotError> {
    let fail = || SnapshotError::new("snapshot identities must be address/serials rows");
    let items = value.as_array().ok_or_else(fail)?;
    let mut rows = Vec::with_capacity(items.len());
    for item in items {
        let obj = item.as_object().ok_or_else(fail)?;
        let address = obj
            .get("address")
            .and_then(Value::as_u64)
            .filter(|a| *a <= 255)
            .ok_or_else(fail)? as u8;
        let serials = obj
            .get("serials")
            .and_then(Value::as_array)
            .ok_or_else(fail)?;
        let mut list = Vec::with_capacity(serials.len());
        for serial in serials {
            list.push(serial.as_str().ok_or_else(fail)?.to_string());
        }
        rows.push((address, list));
    }
    Ok(normalize_identities(rows))
}

/// Extract the embedded `(before, expected_after)` snapshots from a
/// validated plan document value.
///
/// Reads `before` from its final MMI and serial observations, and
/// `expected_after` from its snapshot fields. This helper only extracts
/// summaries; call [`crate::plan::validate_plan_document`] first to prove their wire evidence.
pub fn extract_snapshots(
    plan_document: &Value,
) -> Result<(BusSnapshot, BusSnapshot), SnapshotError> {
    let doc = plan_document
        .as_object()
        .ok_or_else(|| SnapshotError::new("plan document must be an object"))?;
    let before_doc = doc
        .get("before")
        .and_then(Value::as_object)
        .ok_or_else(|| SnapshotError::new("plan document is missing its before observation"))?;
    let final_mmi = before_doc
        .get("final_mmi")
        .and_then(Value::as_object)
        .ok_or_else(|| SnapshotError::new("before observation is missing its final MMI"))?;
    let before = BusSnapshot {
        states: parse_states(final_mmi.get("states").unwrap_or(&Value::Null))?,
        identities: {
            let observations = before_doc
                .get("serial_observations")
                .and_then(Value::as_array)
                .ok_or_else(|| {
                    SnapshotError::new("before observation is missing serial observations")
                })?;
            let mut rows = Vec::with_capacity(observations.len());
            for item in observations {
                let obj = item
                    .as_object()
                    .ok_or_else(|| SnapshotError::new("serial observation must be an object"))?;
                let address = obj
                    .get("address")
                    .and_then(Value::as_u64)
                    .filter(|a| *a <= 255)
                    .ok_or_else(|| SnapshotError::new("serial observation address out of range"))?
                    as u8;
                let serials = obj
                    .get("serials")
                    .and_then(Value::as_array)
                    .ok_or_else(|| SnapshotError::new("serial observation is missing serials"))?;
                let mut list = Vec::with_capacity(serials.len());
                for serial in serials {
                    list.push(
                        serial
                            .as_str()
                            .ok_or_else(|| SnapshotError::new("serial must be a string"))?
                            .to_string(),
                    );
                }
                rows.push((address, list));
            }
            normalize_identities(rows)
        },
    };
    let expected_doc = doc
        .get("expected_after")
        .and_then(Value::as_object)
        .ok_or_else(|| SnapshotError::new("plan document is missing its expected_after"))?;
    let expected = BusSnapshot {
        states: parse_states(expected_doc.get("states").unwrap_or(&Value::Null))?,
        identities: parse_identities(expected_doc.get("identities").unwrap_or(&Value::Null))?,
    };
    Ok((before, expected))
}

fn unexpected_changes(expected: &BusSnapshot, observed: &BusSnapshot) -> Vec<PerAddressDiff> {
    let wanted: HashMap<u8, &[String]> = expected
        .identities
        .iter()
        .map(|(address, serials)| (*address, serials.as_slice()))
        .collect();
    let actual: HashMap<u8, &[String]> = observed
        .identities
        .iter()
        .map(|(address, serials)| (*address, serials.as_slice()))
        .collect();
    let mut diffs = Vec::new();
    for address in 0u8..=255u8 {
        let index = usize::from(address);
        let wanted_serials = wanted.get(&address).map_or(&[][..], |s| s);
        let actual_serials = actual.get(&address).map_or(&[][..], |s| s);
        if wanted_serials != actual_serials || expected.states[index] != observed.states[index] {
            diffs.push(PerAddressDiff {
                address,
                expected_serials: wanted_serials.to_vec(),
                observed_serials: actual_serials.to_vec(),
                expected_state: expected.states[index],
                observed_state: observed.states[index],
            });
        }
    }
    diffs
}

/// Validate original plan bytes, then classify a bounded shared-PCI observation.
///
/// Raw duplicate keys and both original/canonical size limits are checked before
/// I/O. The complete observation uses only IDENTIFY4 and MMI, holding both local
/// commissioning lanes throughout. A confirmed quiet serial window with no
/// replies is complete but cannot establish a known identity.
///
/// This function does not enforce the plan's transport settings or bind the
/// supplied client's endpoint/local identity. See the module-level limitations
/// and the explicit evidence flags; caller options replace plan timing.
/// After a deadline or external cancellation, close the old transport and
/// reconnect before further I/O; dropping this future does not prove wire
/// quiescence or close the client's background tasks.
pub async fn verify_plan(
    raw_plan: &[u8],
    pci: &PciClient,
    options: VerifyOptions,
) -> Result<VerifyEvidence, VerifyInitError> {
    let (plan, document) = validate_plan_document_with_value(raw_plan)?;
    let (before, expected) = extract_snapshots(&document)?;
    let bounds = options.inventory;
    if bounds.total_deadline.is_zero()
        || bounds.per_address_timeout.is_zero()
        || bounds.total_deadline > std::time::Duration::from_secs(3600)
        || bounds.per_address_timeout > std::time::Duration::from_secs(300)
    {
        return Ok(VerifyEvidence::uncertain(vec![
            "after_collection: deadlines must be positive; total <= 3600s and per-address <= 300s".into(),
        ], false));
    }
    let deadline = tokio::time::Instant::now() + bounds.total_deadline;
    let result = tokio::time::timeout_at(
        deadline,
        observe(pci, bounds, plan.local_unit, &before, &expected),
    )
    .await;
    // A ready I/O future may win the runtime's poll at the deadline. Do not
    // publish successful classification after the caller's absolute boundary.
    Ok(if tokio::time::Instant::now() >= deadline {
        VerifyEvidence::uncertain(
            vec!["after_collection: total observation deadline elapsed".into()],
            false,
        )
    } else {
        result.unwrap_or_else(|_| {
            VerifyEvidence::uncertain(
                vec!["after_collection: total observation deadline elapsed".into()],
                false,
            )
        })
    })
}

async fn observe(
    pci: &PciClient,
    bounds: InventoryOptions,
    local_unit: u8,
    before: &BusSnapshot,
    expected: &BusSnapshot,
) -> VerifyEvidence {
    let observation = match pci.commissioning_observation().await {
        Ok(guard) => guard,
        Err(error) => {
            return VerifyEvidence::uncertain(vec![format!("after_collection: {error}")], false)
        }
    };
    let opening = match observation.install_mmi().await {
        Ok(states) => states,
        Err(error) => {
            return VerifyEvidence::uncertain(vec![format!("initial_mmi: {error}")], false)
        }
    };
    let local = usize::from(local_unit);
    if opening.len() != 256 || opening[local] == 0 {
        return VerifyEvidence::uncertain(
            vec!["initial_mmi: incomplete coverage or absent plan local address".into()],
            false,
        );
    }
    let mut identities = Vec::new();
    for (address, state) in opening.iter().enumerate() {
        if *state == 0 {
            continue;
        }
        let address = address as u8;
        let replies = match tokio::time::timeout(
            bounds.per_address_timeout,
            observation.identify_serials(address),
        )
        .await
        {
            Ok(Ok(replies)) => replies,
            Ok(Err(error)) => {
                return VerifyEvidence::uncertain(
                    vec![format!("address {address} IDENTIFY4: {error}")],
                    false,
                )
            }
            Err(_) => {
                return VerifyEvidence::uncertain(
                    vec![format!("address {address} IDENTIFY4 deadline elapsed")],
                    false,
                )
            }
        };
        let serials = match serials_at(address, &replies) {
            Ok(serials) => serials,
            Err(error) => return VerifyEvidence::uncertain(vec![error], false),
        };
        identities.push((address, serials));
    }
    let closing = match observation.install_mmi().await {
        Ok(states) => states,
        Err(error) => return VerifyEvidence::uncertain(vec![format!("after_mmi: {error}")], false),
    };
    if closing.len() != 256 || closing[local] == 0 {
        return VerifyEvidence::uncertain(
            vec!["after_mmi: incomplete coverage or absent plan local address".into()],
            false,
        );
    }
    // A clean quiet serial window may contain no replies. Acquisition completed;
    // lack of a known identity is a semantic failure rather than a transport one.
    let uncertain = |message: String| VerifyEvidence::uncertain(vec![message], true);
    for (address, serials) in &identities {
        if serials.is_empty() {
            return uncertain(format!(
                "after_collection: address {address} has no known serial"
            ));
        }
    }
    if opening.contains(&3) || closing.contains(&3) {
        return uncertain("after_mmi: MMI reports an error state".into());
    }
    if opening != closing {
        return uncertain("after_membership: MMI bookends disagree".into());
    }
    let mut seen = HashSet::new();
    for (_, serials) in &identities {
        for serial in serials {
            if !seen.insert(serial) {
                return uncertain(format!(
                    "after_collection: serial {serial} appears at multiple addresses"
                ));
            }
        }
    }
    let observed = BusSnapshot {
        states: closing.into_iter().map(u64::from).collect(),
        identities,
    };
    let mut evidence = VerifyEvidence::uncertain(Vec::new(), true);
    evidence.outcome = if &observed == expected {
        evidence.expected_identity_change = true;
        VerifyOutcome::ObservedExpectedChange
    } else if &observed == before {
        VerifyOutcome::ObservedUnchanged
    } else {
        VerifyOutcome::ObservedUnexpectedChange
    };
    evidence.unexpected_changes = unexpected_changes(expected, &observed);
    evidence
}

fn serials_at(address: u8, replies: &[Vec<u8>]) -> Result<Vec<String>, String> {
    let mut raw_by_serial = HashMap::new();
    for raw in replies {
        let serial = parse_serial_number(raw)
            .map_err(|error| format!("address {address} IDENTIFY4: {error}"))?
            .ok_or_else(|| format!("address {address} IDENTIFY4: unknown serial"))?;
        if let Some(previous) = raw_by_serial.insert(serial, raw) {
            if previous != raw {
                return Err(format!(
                    "address {address} IDENTIFY4: conflicting identity blocks"
                ));
            }
        }
    }
    let mut serials: Vec<String> = raw_by_serial.into_keys().collect();
    serials.sort_by_key(|serial| sort_key(serial));
    Ok(serials)
}
