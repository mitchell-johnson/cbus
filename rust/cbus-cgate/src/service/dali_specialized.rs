//! Native-evidenced C-Gate 3.4 DALI gateway, parameter, catalogue, and
//! commissioning-session commands.
//!
//! Direct memory commands use the shared PCI programming lane. The volatile
//! extended-parameter maps and active sessions are committed only after the
//! PCI generation is revalidated, so a reconnect can never make an old read
//! look current or replay an uncertain write.

use super::dali_journal::{self, ActiveDaliJournal, DaliJournalPlan, DaliJournalWrite};
use super::*;
use cbus_protocol::dali::{parse_mask, DaliCalMode, DaliLine};
use cbus_transport::pci::DaliPollBudget;
use serde_json::{json, Map, Value};

const EXT_START: u32 = 256;
const EXT_END: u32 = 11_376;
const EXT_LEN: usize = (EXT_END - EXT_START) as usize;

#[derive(Clone)]
struct ExtendedMap {
    values: Vec<Option<u8>>,
    targets: BTreeMap<u32, u8>,
}

impl Default for ExtendedMap {
    fn default() -> Self {
        Self {
            values: vec![None; EXT_LEN],
            targets: BTreeMap::new(),
        }
    }
}

impl ExtendedMap {
    fn replace(&mut self, bytes: Vec<u8>) {
        self.values = bytes.into_iter().map(Some).collect();
        self.targets.clear();
    }

    fn stage(&mut self, address: u32, bytes: &[u8]) -> Result<(), &'static str> {
        if address < EXT_START
            || address
                .checked_add(bytes.len() as u32)
                .is_none_or(|end| end > EXT_END)
        {
            return Err("extended parameter address is outside 256..11375");
        }
        for (offset, byte) in bytes.iter().copied().enumerate() {
            self.targets.insert(address + offset as u32, byte);
        }
        Ok(())
    }

    fn dirty_chunks(&self) -> Vec<(u32, Vec<u8>)> {
        let mut result = Vec::new();
        let mut current_address = None;
        let mut current = Vec::new();
        let mut previous = 0u32;
        for (&address, &value) in &self.targets {
            let unchanged = self
                .values
                .get((address - EXT_START) as usize)
                .and_then(|value| *value)
                == Some(value);
            if unchanged {
                continue;
            }
            let contiguous = current_address.is_some()
                && address == previous + 1
                && current.len() < 12
                && address >> 8 == previous >> 8;
            if !contiguous && !current.is_empty() {
                result.push((
                    current_address.expect("nonempty chunk has address"),
                    current,
                ));
                current = Vec::new();
                current_address = None;
            }
            if current_address.is_none() {
                current_address = Some(address);
            }
            current.push(value);
            previous = address;
        }
        if !current.is_empty() {
            result.push((
                current_address.expect("nonempty chunk has address"),
                current,
            ));
        }
        result
    }

    /// Record freshly recalled current values without touching staged
    /// targets, like native partial `DaliGatewayExtParamMap` recalls.
    fn update_values(&mut self, address: u32, bytes: &[u8]) {
        for (offset, byte) in bytes.iter().copied().enumerate() {
            let logical = address + offset as u32;
            if let Some(value) = logical
                .checked_sub(EXT_START)
                .and_then(|index| self.values.get_mut(index as usize))
            {
                *value = Some(byte);
            }
        }
    }

    fn commit_chunk(&mut self, address: u32, bytes: &[u8]) {
        for (offset, byte) in bytes.iter().copied().enumerate() {
            let logical = address + offset as u32;
            self.values[(logical - EXT_START) as usize] = Some(byte);
            if self.targets.get(&logical) == Some(&byte) {
                self.targets.remove(&logical);
            }
        }
    }

    fn as_json(&self) -> Value {
        let values = self
            .values
            .iter()
            .enumerate()
            .filter_map(|(index, value)| {
                value.map(|value| ((EXT_START + index as u32).to_string(), json!(value)))
            })
            .collect::<Map<_, _>>();
        let targets = self
            .targets
            .iter()
            .map(|(address, value)| (address.to_string(), json!(value)))
            .collect::<Map<_, _>>();
        json!({"values": values, "targetValues": targets})
    }

    fn from_json(value: &Value) -> Self {
        let mut result = Self::default();
        if let Some(values) = value.get("values").and_then(Value::as_object) {
            for (address, value) in values {
                if let (Ok(address), Some(value)) = (address.parse::<u32>(), value.as_u64()) {
                    if (EXT_START..EXT_END).contains(&address) && value <= 255 {
                        result.values[(address - EXT_START) as usize] = Some(value as u8);
                    }
                }
            }
        }
        if let Some(values) = value.get("targetValues").and_then(Value::as_object) {
            for (address, value) in values {
                if let (Ok(address), Some(value)) = (address.parse::<u32>(), value.as_u64()) {
                    if (EXT_START..EXT_END).contains(&address) && value <= 255 {
                        result.targets.insert(address, value as u8);
                    }
                }
            }
        }
        result
    }
}

#[derive(Clone)]
struct DaliSession {
    instance_id: String,
    name: String,
    project: String,
    source_cdg: Option<String>,
    source_unit: Option<String>,
    target_cdg: Option<String>,
    target_unit: Option<String>,
    model: Value,
    ext: ExtendedMap,
    ext_revision: u64,
    ext_epoch: u64,
    model_dirty: bool,
    /// Catalogue edits change native's typed extended proxy, which FULL
    /// re-serializes before its extended write. cmqttd has no such
    /// serializer, so FULL refuses before I/O while this is set.
    catalog_dirty: bool,
}

#[derive(Clone, Debug)]
struct TypedSessionTarget {
    line_index: usize,
    ecg_index: usize,
    line: DaliLine,
    address: u8,
    emergency: bool,
    led: bool,
    has_common_read_only: bool,
    has_emergency_params: bool,
    has_led_params: bool,
    has_gtin_serial: bool,
    gtin: Option<u64>,
    serial: Option<u64>,
}

#[derive(Default)]
struct TypedSessionUpdate {
    common_read_only: Option<Value>,
    emergency_params: Option<Value>,
    emergency_status: Option<Value>,
    led_params: Option<Value>,
    gtin: Option<u64>,
    serial: Option<u64>,
}

#[derive(Clone, Copy)]
enum ReadOnlyExtractStep {
    CheckForUnknown,
    PollKnown,
    Broken,
    Missing,
    Conflicting,
    DiscoverKnownTypeInfo,
    DiscoverKnownFullInfo,
    DiscoverStatusInfoEcg,
    GetKnownTypeInfoEcg,
    GetCommonParamsEcg,
    GetCommonReadOnlyParamsEcg,
    GetSceneValuesEcg,
    DiscoverGtinSerialEcg,
    GetGtinEcg,
    GetSerialEcg,
    GetLedParamsEcg,
    GetEmergencyParamsEcg,
    GetEmergencyStatusEcg,
    ReadGatewayExtFull,
}

/// Steps of the three native conditional extraction plans (`jY`/`ka`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ConditionalExtractStep {
    Rescan,
    PollFinishDiscoverKnownFullInfo,
    Missing,
    AddressUnknown,
    CondDiscoverKnownTypeInfo,
    CondDiscoverKnownFullInfo,
    Broken,
    Conflicting,
    GetKnownTypeInfoEcg,
    CondGetCommonReadOnlyParamsEcg,
    GetEmergencyParamsEcg,
    CondBrokenGetCommonReadOnlyParamsEcg,
    CondBrokenGetEmergencyStatusEcg,
    ReadGatewayExtCondQuick,
    GetCommonParamsEcg,
}

impl ConditionalExtractStep {
    const fn name(self) -> &'static str {
        match self {
            Self::Rescan => "RESCAN",
            Self::PollFinishDiscoverKnownFullInfo => "POLL_FINISH_DISCOVER_KNOWN_FULL_INFO",
            Self::Missing => "MISSING",
            Self::AddressUnknown => "ADDRESS_UNKNOWN",
            Self::CondDiscoverKnownTypeInfo => "COND_DISCOVER_KNOWN_TYPE_INFO",
            Self::CondDiscoverKnownFullInfo => "COND_DISCOVER_KNOWN_FULL_INFO",
            Self::Broken => "BROKEN",
            Self::Conflicting => "CONFLICTING",
            Self::GetKnownTypeInfoEcg => "GET_KNOWN_TYPE_INFO_ECG",
            Self::CondGetCommonReadOnlyParamsEcg => "COND_GET_COMMON_READ_ONLY_PARAMS_ECG",
            Self::GetEmergencyParamsEcg => "GET_EMERGENCY_PARAMS_ECG",
            Self::CondBrokenGetCommonReadOnlyParamsEcg => {
                "COND_BROKEN_GET_COMMON_READ_ONLY_PARAMS_ECG"
            }
            Self::CondBrokenGetEmergencyStatusEcg => "COND_BROKEN_GET_EMERGENCY_STATUS_ECG",
            Self::ReadGatewayExtCondQuick => "READ_GATEWAY_EXT_COND_QUICK",
            Self::GetCommonParamsEcg => "GET_COMMON_PARAMS_ECG",
        }
    }
}

const COND_QUICK_EXTRACT_PLAN: &[ConditionalExtractStep] = &[
    ConditionalExtractStep::PollFinishDiscoverKnownFullInfo,
    ConditionalExtractStep::Missing,
    ConditionalExtractStep::AddressUnknown,
    ConditionalExtractStep::CondDiscoverKnownTypeInfo,
    ConditionalExtractStep::CondDiscoverKnownFullInfo,
    ConditionalExtractStep::Broken,
    ConditionalExtractStep::Conflicting,
    ConditionalExtractStep::GetKnownTypeInfoEcg,
    ConditionalExtractStep::CondGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::GetEmergencyParamsEcg,
    ConditionalExtractStep::CondBrokenGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::CondBrokenGetEmergencyStatusEcg,
    ConditionalExtractStep::ReadGatewayExtCondQuick,
];

const COND_EXTENDED_EXTRACT_PLAN: &[ConditionalExtractStep] = &[
    ConditionalExtractStep::PollFinishDiscoverKnownFullInfo,
    ConditionalExtractStep::Missing,
    ConditionalExtractStep::AddressUnknown,
    ConditionalExtractStep::CondDiscoverKnownTypeInfo,
    ConditionalExtractStep::CondDiscoverKnownFullInfo,
    ConditionalExtractStep::Broken,
    ConditionalExtractStep::Conflicting,
    ConditionalExtractStep::GetKnownTypeInfoEcg,
    ConditionalExtractStep::CondGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::GetEmergencyParamsEcg,
    ConditionalExtractStep::CondBrokenGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::CondBrokenGetEmergencyStatusEcg,
    ConditionalExtractStep::ReadGatewayExtCondQuick,
    ConditionalExtractStep::GetCommonParamsEcg,
];

const RESCAN_FAULT_EXTRACT_PLAN: &[ConditionalExtractStep] = &[
    ConditionalExtractStep::Rescan,
    ConditionalExtractStep::PollFinishDiscoverKnownFullInfo,
    ConditionalExtractStep::Missing,
    ConditionalExtractStep::AddressUnknown,
    ConditionalExtractStep::CondDiscoverKnownTypeInfo,
    ConditionalExtractStep::CondDiscoverKnownFullInfo,
    ConditionalExtractStep::Broken,
    ConditionalExtractStep::Conflicting,
    ConditionalExtractStep::GetKnownTypeInfoEcg,
    ConditionalExtractStep::CondGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::GetEmergencyParamsEcg,
    ConditionalExtractStep::CondBrokenGetCommonReadOnlyParamsEcg,
    ConditionalExtractStep::CondBrokenGetEmergencyStatusEcg,
    ConditionalExtractStep::ReadGatewayExtCondQuick,
];

const fn native_budget(first: DaliCalMode, max_polls: usize, interval_ms: u64) -> DaliPollBudget {
    DaliPollBudget {
        first,
        max_polls,
        interval: Duration::from_millis(interval_ms),
    }
}

/// `oL` budget overrides set by the build-2001 extraction executor `ka`.
const POLL_FINISH_BUDGET: DaliPollBudget = native_budget(DaliCalMode::Poll, 57, 3000);
const DISCOVER_FULL_BUDGET: DaliPollBudget = native_budget(DaliCalMode::Execute, 57, 3000);
const DISCOVER_TYPE_BUDGET: DaliPollBudget = native_budget(DaliCalMode::Execute, 17, 1000);
const RESCAN_BUDGET: DaliPollBudget = native_budget(DaliCalMode::Execute, 60, 5000);
const ADDRESS_UNKNOWN_BUDGET: DaliPollBudget = native_budget(DaliCalMode::Execute, 67, 3000);

/// Status flags `DaliEcg.c()` clears before POLL_FINISH applies its mask.
const ECG_STATUS_FLAGS: [&str; 7] = [
    "isKnown",
    "isFullyKnown",
    "isAddressKnown",
    "isBroken",
    "isPreviouslyBroken",
    "isMissing",
    "isConflicting",
];

/// Half-open extended ranges recalled by `READ_GATEWAY_EXT_COND_QUICK`.
fn cond_quick_ext_ranges(lines: (bool, bool)) -> Vec<(u32, u32)> {
    let mut ranges = vec![(256, 258), (512, 516)];
    match lines {
        (true, false) => ranges.extend([(7040, 7104), (8800, 8808)]),
        (false, true) => ranges.extend([(7104, 7168), (8808, 8816)]),
        _ => ranges.extend([(7040, 7168), (8800, 8816)]),
    }
    ranges
}

/// One typed deployment exchange: an AUTO setter for one ECG.
#[derive(Clone, Debug, PartialEq, Eq)]
struct TypedDeployWrite {
    step: &'static str,
    operation: u8,
    line: DaliLine,
    address: u8,
    payload: Vec<u8>,
}

/// One native deploy step. The scene step has two phases (operation 34 for
/// every ECG, then operation 35), each of which warns when it sends nothing.
#[derive(Clone, Debug)]
struct TypedDeployStep {
    name: &'static str,
    phases: Vec<Vec<TypedDeployWrite>>,
}

const TYPED_DEPLOY_STEPS: [&str; 4] = [
    "SET_COMMON_PARAMS_ECG",
    "SET_SCENE_VALUES_ECG",
    "SET_LED_PARAMS_ECG",
    "SET_EMERGENCY_PARAMS_ECG",
];

impl ReadOnlyExtractStep {
    const fn name(self) -> &'static str {
        match self {
            Self::CheckForUnknown => "CHECK_FOR_UNKNOWN",
            Self::PollKnown => "POLL_KNOWN",
            Self::Broken => "BROKEN",
            Self::Missing => "MISSING",
            Self::Conflicting => "CONFLICTING",
            Self::DiscoverKnownTypeInfo => "DISCOVER_KNOWN_TYPE_INFO",
            Self::DiscoverKnownFullInfo => "DISCOVER_KNOWN_FULL_INFO",
            Self::DiscoverStatusInfoEcg => "DISCOVER_STATUS_INFO_ECG",
            Self::GetKnownTypeInfoEcg => "GET_KNOWN_TYPE_INFO_ECG",
            Self::GetCommonParamsEcg => "GET_COMMON_PARAMS_ECG",
            Self::GetCommonReadOnlyParamsEcg => "GET_COMMON_READ_ONLY_PARAMS_ECG",
            Self::GetSceneValuesEcg => "GET_SCENE_VALUES_ECG",
            Self::DiscoverGtinSerialEcg => "DISCOVER_GTIN_SERIAL_ECG",
            Self::GetGtinEcg => "GET_GTIN_ECG",
            Self::GetSerialEcg => "GET_SERIAL_ECG",
            Self::GetLedParamsEcg => "GET_LED_PARAMS_ECG",
            Self::GetEmergencyParamsEcg => "GET_EMERGENCY_PARAMS_ECG",
            Self::GetEmergencyStatusEcg => "GET_EMERGENCY_STATUS_ECG",
            Self::ReadGatewayExtFull => "READ_GATEWAY_EXT_FULL",
        }
    }
}

const DALI_ONLY_EXTRACT_PLAN: &[ReadOnlyExtractStep] = &[
    ReadOnlyExtractStep::CheckForUnknown,
    ReadOnlyExtractStep::PollKnown,
    ReadOnlyExtractStep::Broken,
    ReadOnlyExtractStep::Missing,
    ReadOnlyExtractStep::Conflicting,
    ReadOnlyExtractStep::DiscoverKnownTypeInfo,
    ReadOnlyExtractStep::DiscoverKnownFullInfo,
    ReadOnlyExtractStep::DiscoverStatusInfoEcg,
    ReadOnlyExtractStep::GetKnownTypeInfoEcg,
    ReadOnlyExtractStep::GetCommonParamsEcg,
    ReadOnlyExtractStep::GetCommonReadOnlyParamsEcg,
    ReadOnlyExtractStep::GetSceneValuesEcg,
    ReadOnlyExtractStep::GetLedParamsEcg,
    ReadOnlyExtractStep::GetEmergencyParamsEcg,
    ReadOnlyExtractStep::GetEmergencyStatusEcg,
];

const FULL_EXTRACT_PLAN: &[ReadOnlyExtractStep] = &[
    ReadOnlyExtractStep::PollKnown,
    ReadOnlyExtractStep::Broken,
    ReadOnlyExtractStep::Missing,
    ReadOnlyExtractStep::Conflicting,
    ReadOnlyExtractStep::DiscoverKnownTypeInfo,
    ReadOnlyExtractStep::DiscoverKnownFullInfo,
    ReadOnlyExtractStep::DiscoverStatusInfoEcg,
    ReadOnlyExtractStep::GetKnownTypeInfoEcg,
    ReadOnlyExtractStep::GetCommonParamsEcg,
    ReadOnlyExtractStep::GetCommonReadOnlyParamsEcg,
    ReadOnlyExtractStep::GetSceneValuesEcg,
    ReadOnlyExtractStep::DiscoverGtinSerialEcg,
    ReadOnlyExtractStep::GetGtinEcg,
    ReadOnlyExtractStep::GetSerialEcg,
    ReadOnlyExtractStep::GetLedParamsEcg,
    ReadOnlyExtractStep::GetEmergencyParamsEcg,
    ReadOnlyExtractStep::GetEmergencyStatusEcg,
    ReadOnlyExtractStep::ReadGatewayExtFull,
];

impl DaliSession {
    fn new(name: &str, project: &str, oid: &str) -> Self {
        Self {
            instance_id: oid.to_string(),
            name: name.to_string(),
            project: project.to_string(),
            source_cdg: None,
            source_unit: None,
            target_cdg: None,
            target_unit: None,
            model: json!({
                "OID": oid,
                "catalog": {"catalogueLines": [{"lineId": 0, "devices": []}, {"lineId": 1, "devices": []}]},
                "cdg": {"daliLines": [{"lineId": 0, "daliEcgs": []}, {"lineId": 1, "daliEcgs": []}]},
                "oids": []
            }),
            ext: ExtendedMap::default(),
            ext_revision: 0,
            ext_epoch: 0,
            model_dirty: false,
            catalog_dirty: false,
        }
    }

    fn stage_ext(&mut self, address: u32, bytes: &[u8]) -> Result<(), &'static str> {
        self.ext.stage(address, bytes)?;
        self.ext_revision = self.ext_revision.wrapping_add(1);
        Ok(())
    }

    fn replace_ext(&mut self, bytes: Vec<u8>) {
        self.ext.replace(bytes);
        self.ext_revision = self.ext_revision.wrapping_add(1);
        self.ext_epoch = self.ext_epoch.wrapping_add(1);
    }

    fn replace_ext_map(&mut self, ext: ExtendedMap) {
        self.ext = ext;
        self.ext_revision = self.ext_revision.wrapping_add(1);
        self.ext_epoch = self.ext_epoch.wrapping_add(1);
    }

    fn commit_ext_chunk(&mut self, address: u32, bytes: &[u8]) {
        self.ext.commit_chunk(address, bytes);
        self.ext_revision = self.ext_revision.wrapping_add(1);
    }

    fn invalidate_ext(&mut self) {
        self.ext.values.fill(None);
        self.ext.targets.clear();
        self.ext_revision = self.ext_revision.wrapping_add(1);
        self.ext_epoch = self.ext_epoch.wrapping_add(1);
    }

    fn summary(&self) -> Value {
        json!({
            "name": self.name,
            "project": self.project,
            "srcCdg": self.source_cdg,
            "srcUnit": self.source_unit,
            "targetCdg": self.target_cdg,
            "targetUnit": self.target_unit,
            "modelDirty": self.model_dirty,
        })
    }

    fn saved(&self) -> Value {
        let mut model = self.model.clone();
        if let Some(root) = model.as_object_mut() {
            root.insert("extParams".to_string(), self.ext.as_json());
        }
        json!({
            "project": self.project,
            "model": model,
            "sourceCdg": self.source_cdg,
            "sourceUnit": self.source_unit,
            "targetCdg": self.target_cdg,
            "targetUnit": self.target_unit,
            "modelDirty": self.model_dirty,
            "catalogDirty": self.catalog_dirty,
        })
    }

    fn load_saved(&mut self, saved: &Value) {
        if let Some(model) = saved.get("model") {
            self.model = model.clone();
            let ext = model
                .get("extParams")
                .map(ExtendedMap::from_json)
                .unwrap_or_default();
            self.replace_ext_map(ext);
        }
        self.source_cdg = saved
            .get("sourceCdg")
            .and_then(Value::as_str)
            .map(str::to_string);
        self.source_unit = saved
            .get("sourceUnit")
            .and_then(Value::as_str)
            .map(str::to_string);
        self.target_cdg = saved
            .get("targetCdg")
            .and_then(Value::as_str)
            .map(str::to_string);
        self.target_unit = saved
            .get("targetUnit")
            .and_then(Value::as_str)
            .map(str::to_string);
        self.model_dirty = saved
            .get("modelDirty")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        // A snapshot saved before this flag existed is conservative.
        self.catalog_dirty = saved
            .get("catalogDirty")
            .and_then(Value::as_bool)
            .unwrap_or(self.model_dirty);
    }
}

#[derive(Clone)]
struct CatalogEntry {
    name: String,
    spec: Value,
    summary: Value,
}

/// Volatile native-style DALI service state. The saved session repository is
/// held separately in [`Server`] and included in its atomic database.
#[derive(Default)]
pub(super) struct DaliState {
    gateway_ext: HashMap<u8, ExtendedMap>,
    sessions: BTreeMap<String, DaliSession>,
    catalog: BTreeMap<String, CatalogEntry>,
    next_oid: u64,
    /// Test hook: replaces every native DALI poll interval so long budgets
    /// (67 polls at 3 s) can be exercised quickly. Never set in production.
    poll_interval_override: Option<Duration>,
}

impl DaliState {
    pub(super) fn from_server(server: &Server, project: &str) -> Self {
        let mut state = Self::default();
        state.reload_catalog(server, project);
        state
    }

    fn reload_catalog(&mut self, server: &Server, project: &str) -> usize {
        self.catalog.clear();
        let prefix = format!("%{project}%/dali_catalogue/devices/");
        for (path, bytes) in &server.file_store {
            if !path.starts_with(&prefix) || !path.ends_with(".json") {
                continue;
            }
            let Ok(spec) = serde_json::from_slice::<Value>(bytes) else {
                continue;
            };
            let name = spec
                .get("name")
                .and_then(Value::as_str)
                .map(str::to_string)
                .or_else(|| {
                    path.rsplit('/')
                        .next()
                        .and_then(|name| name.strip_suffix(".json"))
                        .map(str::to_string)
                });
            let Some(name) = name else { continue };
            let description = spec
                .get("desc")
                .or_else(|| spec.get("description"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let author = spec.get("author").and_then(Value::as_str).unwrap_or("");
            let channel_count = spec
                .get("channels")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            let summary = json!({
                "name": name,
                "description": description,
                "author": author,
                "channelsFeatureTypes": vec![Vec::<String>::new(); channel_count],
            });
            self.catalog.insert(
                name.clone(),
                CatalogEntry {
                    name,
                    spec,
                    summary,
                },
            );
        }
        self.catalog.len()
    }

    fn fresh_oid(&mut self) -> String {
        self.next_oid = self.next_oid.wrapping_add(1).max(1);
        format!("dali-session-{:016X}", self.next_oid)
    }

    pub(super) fn invalidate_physical(&mut self) {
        self.gateway_ext.clear();
        for session in self.sessions.values_mut() {
            // A reconnect while a verified write is crossing the service
            // commit boundary makes the remaining staged set ambiguous.
            // Dropping it is the only safe no-replay behavior.
            session.invalidate_ext();
        }
    }
}

impl Service {
    pub(super) async fn dali_specialized(
        &self,
        tag: &str,
        body: &str,
        upper: &[String],
    ) -> Response {
        let tokens = tokens(body);
        let Some(group) = upper.get(1).map(String::as_str) else {
            return syntax(tag);
        };
        let Some(command) = upper.get(2).map(String::as_str) else {
            return syntax(tag);
        };
        let args = tokens.get(3..).unwrap_or(&[]);
        match group {
            "CATALOG" => self.dali_catalog(tag, command, args).await,
            "GATEWAY" => self.dali_gateway_command(tag, command, args).await,
            "ERROR_REPORTING" => {
                self.dali_parameter_command(tag, command, args, ParameterFamily::ErrorReporting)
                    .await
            }
            "MEASUREMENT" => {
                self.dali_parameter_command(tag, command, args, ParameterFamily::Measurement)
                    .await
            }
            "SESSION" => self.dali_session_command(tag, command, args).await,
            _ => syntax(tag),
        }
    }

    async fn dali_catalog(&self, tag: &str, command: &str, args: &[String]) -> Response {
        match command {
            "LIST" => {
                if !args.is_empty() {
                    return syntax(tag);
                }
                let state = self.dali_state.lock().await;
                if state.catalog.is_empty() {
                    return err(tag, 450, "450 no loaded catalog devices.");
                }
                rows(
                    tag,
                    130,
                    state
                        .catalog
                        .values()
                        .map(|entry| entry.summary.to_string())
                        .collect(),
                )
            }
            "GET_SPEC" => {
                if args.len() != 1 {
                    return syntax(tag);
                }
                let state = self.dali_state.lock().await;
                match state.catalog.get(&args[0]) {
                    Some(entry) => Response {
                        tag: tag.to_string(),
                        lines: vec![format!("100-{}", entry.spec)],
                        final_text: "200 OK.".to_string(),
                        status: 200,
                    },
                    None => err(
                        tag,
                        501,
                        &format!("501 catalogue device spec not found: {}", args[0]),
                    ),
                }
            }
            "RELOAD" => {
                if args.len() > 1 {
                    return syntax(tag);
                }
                let project = args.first().map_or(self.project.as_str(), String::as_str);
                let model = self.model.lock().await;
                if !model.projects.contains_key(project) {
                    return err(
                        tag,
                        440,
                        "440 There is no tag database to perform this operation on",
                    );
                }
                let mut state = self.dali_state.lock().await;
                state.reload_catalog(&model, project);
                ok(tag, vec![], "200 OK.")
            }
            _ => syntax(tag),
        }
    }

    async fn dali_gateway_command(&self, tag: &str, command: &str, args: &[String]) -> Response {
        match command {
            "FACTORY_RESET" | "LOAD_PRESET" | "RESTART" | "SAVE_TO_NVM" => {
                self.dali_gateway_cal(tag, command, args).await
            }
            "PAGED_RECALL" => {
                if args.len() != 3 {
                    return syntax(tag);
                }
                let address = match number(tag, &args[1], "<address>", 0, EXT_END) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let count = match number(tag, &args[2], "<count>", 0, 255) {
                    Ok(value) => value as usize,
                    Err(response) => return response,
                };
                match self
                    .dali_recall(tag, &args[0], address, count, "paged recall")
                    .await
                {
                    Ok(bytes) => paged_rows(tag, &args[0], address, &bytes),
                    Err(response) => response,
                }
            }
            "PAGED_STORE" => {
                if !(3..=18).contains(&args.len()) {
                    return syntax(tag);
                }
                let address = match number(tag, &args[1], "<address>", 0, EXT_END) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let mut bytes = Vec::with_capacity(args.len() - 2);
                for (index, value) in args[2..].iter().enumerate() {
                    match number(tag, value, &format!("<value-{}>", index + 1), 0, 255) {
                        Ok(value) => bytes.push(value as u8),
                        Err(response) => return response,
                    }
                }
                match self
                    .dali_store(tag, &args[0], address, &bytes, "paged store")
                    .await
                {
                    Ok(()) => ok(
                        tag,
                        vec![format!("120-{}: Address$={address:04X}", args[0])],
                        "200 OK.",
                    ),
                    Err(response) => response,
                }
            }
            "PRIMARY_ADDRESS" => self.dali_primary_address(tag, args, false).await,
            "SET_PRIMARY_ADDRESS" => self.dali_primary_address(tag, args, true).await,
            "VIRTUAL_GROUP" => self.dali_virtual_group(tag, args, false).await,
            "SET_VIRTUAL_GROUP" => self.dali_virtual_group(tag, args, true).await,
            "SHORT_MAP" => {
                if args.len() != 2 {
                    return syntax(tag);
                }
                let line = match line_arg(tag, &args[1]) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let address = if line == DaliLine::A { 7040 } else { 7104 };
                match self
                    .dali_recall(tag, &args[0], address, 16, "short-map recall")
                    .await
                {
                    Ok(bytes) => paged_rows(tag, &args[0], address, &bytes),
                    Err(response) => response,
                }
            }
            "READ_EXTENDED_PARAMETERS" => self.dali_read_extended(tag, args).await,
            "SET_EXTENDED_PARAMETERS" => self.dali_set_extended(tag, args).await,
            "WRITE_EXTENDED_PARAMETERS" => self.dali_write_extended(tag, args).await,
            "LIST" => self.dali_gateway_list(tag, args).await,
            "DEVICE_ID_LIST" => self.dali_gateway_device_ids(tag, args).await,
            "NAC_SUMMARY_LIST" => self.dali_gateway_nac(tag, args).await,
            "PROJECT_CUSTOM" => self.dali_project_custom(tag, args).await,
            _ => syntax(tag),
        }
    }

    async fn dali_gateway_cal(&self, tag: &str, command: &str, args: &[String]) -> Response {
        let mut index = 0usize;
        let mode = args
            .first()
            .and_then(|value| DaliCalMode::parse(value))
            .inspect(|_| index += 1)
            .unwrap_or(DaliCalMode::Auto);
        let Some(target) = args.get(index) else {
            return syntax(tag);
        };
        index += 1;
        let preset = if command == "LOAD_PRESET" {
            match args.get(index) {
                Some(value) => match number(tag, value, "<preset>", 0, 3) {
                    Ok(value) => {
                        index += 1;
                        value as u8
                    }
                    Err(response) => return response,
                },
                None => 0,
            }
        } else {
            0
        };
        if index != args.len() {
            return syntax(tag);
        }
        if mode == DaliCalMode::Status {
            return err(tag, 400, "400 dali cal status must be set");
        }
        let (unit, serial) = match self.dali_gateway(tag, target).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (operation, mut payload) = match command {
            "FACTORY_RESET" => (1, Vec::new()),
            "RESTART" => (2, Vec::new()),
            "LOAD_PRESET" => (3, vec![preset]),
            "SAVE_TO_NVM" => (4, Vec::new()),
            _ => unreachable!(),
        };
        if matches!(mode, DaliCalMode::Auto | DaliCalMode::Execute)
            && matches!(command, "FACTORY_RESET" | "RESTART")
        {
            let selected = match serial
                .as_deref()
                .ok_or(())
                .and_then(|serial| parse_native_serial(serial).map_err(|_| ()))
            {
                Ok(selected) if selected.known => selected,
                _ => return err(tag, 408, "408 DALI gateway serial number is unavailable"),
            };
            payload = selected.packed.into_iter().rev().collect();
        }
        if !matches!(mode, DaliCalMode::Auto | DaliCalMode::Execute) {
            payload.clear();
        }
        let (generation, pci) = self.current_pci_epoch().await;
        let result = match pci.dali_command(unit, mode, 0, operation, &payload).await {
            Ok(result) => result,
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 DALI gateway command failed: {error}"),
                )
            }
        };
        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                502,
                "502 PCI connection changed during DALI gateway command; outcome is uncertain",
            );
        };
        gateway_cal_rows(tag, command, operation, &payload, result)
    }

    async fn dali_primary_address(&self, tag: &str, args: &[String], set: bool) -> Response {
        if args.len() != if set { 4 } else { 3 } {
            return syntax(tag);
        }
        let line = match line_arg(tag, &args[1]) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let oid = match number(tag, &args[2], "<object-id>", 0, 128) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let address = if line == DaliLine::A { 768 } else { 3872 } + (oid << 5);
        if set {
            let primary = match number(tag, &args[3], "<primary-address>", 0, 255) {
                Ok(value) => value as u8,
                Err(response) => return response,
            };
            match self
                .dali_store(tag, &args[0], address, &[primary], "primary-address store")
                .await
            {
                Ok(()) => ok(
                    tag,
                    vec![
                        format!("120-{}: Address$={address:04X}", args[0]),
                        format!("120-{}: Primary$={primary:02X}", args[0]),
                    ],
                    "200 OK.",
                ),
                Err(response) => response,
            }
        } else {
            match self
                .dali_recall(tag, &args[0], address, 1, "primary-address recall")
                .await
            {
                Ok(bytes) => ok(
                    tag,
                    vec![
                        format!("120-{}: Address$={address:04X}", args[0]),
                        format!("120-{}: ${:02X}", args[0], bytes[0]),
                    ],
                    "200 OK.",
                ),
                Err(response) => response,
            }
        }
    }

    async fn dali_virtual_group(&self, tag: &str, args: &[String], set: bool) -> Response {
        if args.len() != if set { 4 } else { 3 } {
            return syntax(tag);
        }
        let line = match line_arg(tag, &args[1]) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let group = match number(tag, &args[2], "<virtual-group-id>", 0, 15) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let address = if line == DaliLine::A { 7168 } else { 7296 } + group * 8;
        if set {
            let bytes = match bytes_arg(tag, &args[3], 8, "<bitmask64>") {
                Ok(bytes) => bytes,
                Err(response) => return response,
            };
            match self
                .dali_store(tag, &args[0], address, &bytes, "virtual-group store")
                .await
            {
                Ok(()) => memory_rows(tag, &args[0], address, &bytes),
                Err(response) => response,
            }
        } else {
            match self
                .dali_recall(tag, &args[0], address, 8, "virtual-group recall")
                .await
            {
                Ok(bytes) => memory_rows(tag, &args[0], address, &bytes),
                Err(response) => response,
            }
        }
    }

    async fn dali_recall(
        &self,
        tag: &str,
        target: &str,
        address: u32,
        count: usize,
        operation: &str,
    ) -> Result<Vec<u8>, Response> {
        let (unit, _) = self.dali_gateway(tag, target).await?;
        let (generation, pci) = self.current_pci_epoch().await;
        let bytes = pci
            .recall_paged_parameter(unit, address, count)
            .await
            .map_err(|error| {
                err(
                    tag,
                    522,
                    &format!("522 {target}: {operation} failed: {error}"),
                )
            })?;
        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return Err(err(
                tag,
                522,
                &format!("522 {target}: PCI connection changed during {operation}"),
            ));
        };
        Ok(bytes)
    }

    async fn dali_store(
        &self,
        tag: &str,
        target: &str,
        address: u32,
        bytes: &[u8],
        operation: &str,
    ) -> Result<(), Response> {
        let (unit, _) = self.dali_gateway(tag, target).await?;
        let (generation, pci) = self.current_pci_epoch().await;
        pci.store_paged_parameter_verified(unit, address, bytes, false)
            .await
            .map_err(|error| {
                err(
                    tag,
                    522,
                    &format!("522 {target}: {operation} failed: {error}"),
                )
            })?;
        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return Err(err(
                tag,
                522,
                &format!(
                    "522 {target}: PCI connection changed during {operation}; outcome is uncertain"
                ),
            ));
        };
        Ok(())
    }

    async fn dali_read_extended(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 1 {
            return syntax(tag);
        }
        let (unit, _) = match self.dali_gateway(tag, &args[0]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let bytes = match pci.recall_paged_parameter(unit, EXT_START, EXT_LEN).await {
            Ok(bytes) => bytes,
            Err(error) => {
                return err(
                    tag,
                    522,
                    &format!("522 {}: extended parameter read failed: {error}", args[0]),
                )
            }
        };
        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                522,
                "522 PCI connection changed during extended parameter read",
            );
        };
        self.dali_state
            .lock()
            .await
            .gateway_ext
            .entry(unit)
            .or_default()
            .replace(bytes);
        ok(tag, vec![format!("200-{}: completed", args[0])], "200 OK.")
    }

    async fn dali_set_extended(&self, tag: &str, args: &[String]) -> Response {
        if !(3..=18).contains(&args.len()) {
            return syntax(tag);
        }
        let (unit, _) = match self.dali_gateway(tag, &args[0]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let address = match number(tag, &args[1], "<address>", 0, EXT_END) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let mut bytes = Vec::new();
        for (index, value) in args[2..].iter().enumerate() {
            match number(tag, value, &format!("<value-{}>", index + 1), 0, 255) {
                Ok(value) => bytes.push(value as u8),
                Err(response) => return response,
            }
        }
        let mut state = self.dali_state.lock().await;
        if let Err(error) = state
            .gateway_ext
            .entry(unit)
            .or_default()
            .stage(address, &bytes)
        {
            return err(
                tag,
                522,
                &format!("522 {}: Failed set @ <value-0> :{error}", args[0]),
            );
        }
        ok(tag, vec![], "200 OK.")
    }

    async fn dali_write_extended(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 1 {
            return syntax(tag);
        }
        let (unit, _) = match self.dali_gateway(tag, &args[0]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let chunks = self
            .dali_state
            .lock()
            .await
            .gateway_ext
            .entry(unit)
            .or_default()
            .dirty_chunks();
        let (generation, pci) = self.current_pci_epoch().await;
        for (index, (address, bytes)) in chunks.iter().enumerate() {
            if let Err(error) = pci
                .store_paged_parameter_verified(unit, *address, bytes, false)
                .await
            {
                return err(
                    tag,
                    522,
                    &format!(
                        "522 {}: extended parameter write failed after {index} confirmed chunk(s): {error}",
                        args[0]
                    ),
                );
            }
            let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
                return err(
                    tag,
                    522,
                    "522 PCI connection changed during extended parameter write; outcome is uncertain",
                );
            };
            self.dali_state
                .lock()
                .await
                .gateway_ext
                .entry(unit)
                .or_default()
                .commit_chunk(*address, bytes);
        }
        ok(tag, vec![format!("200-{}: completed", args[0])], "200 OK.")
    }

    async fn dali_gateway_list(&self, tag: &str, args: &[String]) -> Response {
        if args.len() > 1 {
            return syntax(tag);
        }
        let project_name = args.first().map_or(self.project.as_str(), String::as_str);
        let model = self.model.lock().await;
        let Some(project) = model.projects.get(project_name) else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let mut result = Vec::new();
        for (network_number, network) in &project.networks {
            for unit in network
                .units
                .values()
                .filter(|unit| unit.unit_type.eq_ignore_ascii_case("SYS_DAL2"))
            {
                let saved = model.dali_saved_sessions.get(&unit.oid);
                result.push(
                    json!({
                        "name": unit.fields.get("UnitName").cloned(),
                        "oid": unit.oid,
                        "unitAddress": unit.address,
                        "networkNumber": network_number,
                        "modified": Value::Null,
                        "hasSession": saved.is_some(),
                        "lines": [Value::Null, Value::Null],
                    })
                    .to_string(),
                );
            }
        }
        if result.is_empty() {
            err(tag, 450, "450 no dali gateways found.")
        } else {
            rows(tag, 130, result)
        }
    }

    async fn dali_gateway_device_ids(&self, tag: &str, args: &[String]) -> Response {
        if !(1..=2).contains(&args.len()) {
            return syntax(tag);
        }
        let network_number = match number(tag, &args[0], "<network-address>", 0, 254) {
            Ok(value) => value as u8,
            Err(response) => return response,
        };
        let project_name = args.get(1).map_or(self.project.as_str(), String::as_str);
        let model = self.model.lock().await;
        let Some(network) = model
            .projects
            .get(project_name)
            .and_then(|project| project.networks.get(&network_number))
        else {
            return err(tag, 450, "450 no dali gateways found.");
        };
        let mut ids = std::collections::BTreeSet::new();
        for unit in network
            .units
            .values()
            .filter(|unit| unit.unit_type.eq_ignore_ascii_case("SYS_DAL2"))
        {
            let Some(saved) = model.dali_saved_sessions.get(&unit.oid) else {
                continue;
            };
            if let Some(value) = saved
                .pointer("/model/extParams/values/556")
                .and_then(Value::as_u64)
                .filter(|value| *value <= 255)
            {
                ids.insert(value as u8);
            }
        }
        if ids.is_empty() {
            err(tag, 450, "450 no dali gateways found.")
        } else {
            rows(
                tag,
                130,
                ids.into_iter().map(|value| value.to_string()).collect(),
            )
        }
    }

    async fn dali_gateway_nac(&self, tag: &str, args: &[String]) -> Response {
        if !(1..=2).contains(&args.len()) {
            return syntax(tag);
        }
        let network_number = match number(tag, &args[0], "<network-address>", 0, 254) {
            Ok(value) => value as u8,
            Err(response) => return response,
        };
        let project_name = args.get(1).map_or(self.project.as_str(), String::as_str);
        let model = self.model.lock().await;
        let Some(network) = model
            .projects
            .get(project_name)
            .and_then(|project| project.networks.get(&network_number))
        else {
            return err(tag, 450, "450 no dali gateways found.");
        };
        let result = network
            .units
            .values()
            .filter(|unit| unit.unit_type.eq_ignore_ascii_case("SYS_DAL2"))
            .map(|unit| {
                json!({
                    "gatewayName": unit.fields.get("UnitName").cloned(),
                    "gatewayUnitOid": unit.oid,
                    "gatewayUnitAddress": unit.address,
                    "lines": [
                        {"lineName": Value::Null, "channels": []},
                        {"lineName": Value::Null, "channels": []}
                    ]
                })
                .to_string()
            })
            .collect::<Vec<_>>();
        if result.is_empty() {
            err(tag, 450, "450 no dali gateways found.")
        } else {
            rows(tag, 130, result)
        }
    }

    async fn dali_project_custom(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 2 {
            return syntax(tag);
        }
        if let Err(response) = line_arg(tag, &args[1]) {
            return response;
        }
        let (unit_address, _) = match self.dali_gateway(tag, &args[0]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let model = self.model.lock().await;
        let Some(unit) = model
            .projects
            .get(&self.project)
            .and_then(|project| project.networks.get(&self.network))
            .and_then(|network| network.units.get(&unit_address))
        else {
            return err(tag, 500, "500 DALI gateway database object is unavailable");
        };
        let mut properties = unit.fields.iter().collect::<Vec<_>>();
        properties.sort_by(|left, right| left.0.cmp(right.0));
        let mut lines = vec!["100-====".to_string()];
        lines.extend(
            properties
                .into_iter()
                .map(|(name, value)| format!("100-{name}={value}")),
        );
        lines.push("100-====".to_string());
        Response {
            tag: tag.to_string(),
            lines,
            final_text: "200 OK.".to_string(),
            status: 200,
        }
    }

    async fn dali_parameter_command(
        &self,
        tag: &str,
        command: &str,
        args: &[String],
        family: ParameterFamily,
    ) -> Response {
        let (set, base_name) = command
            .strip_prefix("SET_")
            .map_or((false, command), |name| (true, name));
        let spec = match (family, base_name) {
            (ParameterFamily::ErrorReporting, "USED_DEVICE_MASK") => {
                MemorySpec::lined(8800, 8808, 8, 0)
            }
            (ParameterFamily::ErrorReporting, "STORE_OPTION") => MemorySpec::scalar(521),
            (ParameterFamily::ErrorReporting, "INTERVAL") => MemorySpec::scalar(637),
            (ParameterFamily::ErrorReporting, "MODE") => MemorySpec::scalar(636),
            (ParameterFamily::ErrorReporting, "ENABLE_GROUP") => MemorySpec::scalar(632),
            (ParameterFamily::ErrorReporting, "DEVICE_ID") => MemorySpec::scalar(556),
            (ParameterFamily::ErrorReporting, "TRIGGER_REPORT_GROUP") => MemorySpec::scalar(633),
            (ParameterFamily::ErrorReporting, "RESEND_ACTION_SELECTOR") => MemorySpec::scalar(634),
            (ParameterFamily::ErrorReporting, "ACK_ALL_ERRORS_ACTION_SELECTOR") => {
                MemorySpec::scalar(635)
            }
            (ParameterFamily::ErrorReporting, "NETWORK_PATH") => MemorySpec::bytes(638, 6),
            (ParameterFamily::Measurement, "LAMP_RUNNING_TIME") => {
                MemorySpec::lined(7424, 7680, 4, 4)
            }
            (ParameterFamily::Measurement, "REQUEST_TRIGGER_GROUP") => MemorySpec::scalar(558),
            (ParameterFamily::Measurement, "CLEAR_TRIGGER_GROUP") => MemorySpec::scalar(559),
            _ => return syntax(tag),
        };
        let expected = 1 + usize::from(spec.line) + usize::from(spec.indexed) + usize::from(set);
        if args.len() != expected {
            return syntax(tag);
        }
        let target = &args[0];
        let mut index = 1usize;
        let line = if spec.line {
            let parsed = match line_arg(tag, &args[index]) {
                Ok(value) => value,
                Err(response) => return response,
            };
            index += 1;
            parsed
        } else {
            DaliLine::A
        };
        let object = if spec.indexed {
            let parsed = match number(tag, &args[index], "<short-address-lamp>", 0, 63) {
                Ok(value) => value,
                Err(response) => return response,
            };
            index += 1;
            parsed
        } else {
            0
        };
        let address = if line == DaliLine::A {
            spec.address_a
        } else {
            spec.address_b
        } + object * spec.stride;
        if set {
            let value = if spec.length == 1 {
                match number(
                    tag,
                    &args[index],
                    spec.value_name(family, base_name),
                    0,
                    255,
                ) {
                    Ok(value) => vec![value as u8],
                    Err(response) => return response,
                }
            } else {
                match bytes_arg(
                    tag,
                    &args[index],
                    spec.length,
                    spec.value_name(family, base_name),
                ) {
                    Ok(value) => value,
                    Err(response) => return response,
                }
            };
            match self
                .dali_store(tag, target, address, &value, "DALI parameter store")
                .await
            {
                Ok(()) => memory_rows(tag, target, address, &value),
                Err(response) => response,
            }
        } else {
            match self
                .dali_recall(tag, target, address, spec.length, "DALI parameter recall")
                .await
            {
                Ok(value) => memory_rows(tag, target, address, &value),
                Err(response) => response,
            }
        }
    }

    async fn dali_session_command(&self, tag: &str, command: &str, args: &[String]) -> Response {
        match command {
            "LIST" => self.dali_session_list(tag, args).await,
            "NEW" => self.dali_session_new(tag, args).await,
            "END" => self.dali_session_end(tag, args).await,
            "GET" => self.dali_session_get(tag, args, false).await,
            "MULTIGET" => self.dali_session_get(tag, args, true).await,
            "SET" => self.dali_session_set(tag, args).await,
            "SET_EXT_PARAMS" => self.dali_session_set_ext(tag, args).await,
            "CATALOG_DEVICE_ADD" => self.dali_session_catalog_add(tag, args).await,
            "CATALOG_DEVICE_REMOVE" => self.dali_session_catalog_remove(tag, args).await,
            "LOAD" => self.dali_session_load(tag, args).await,
            "SAVE" => self.dali_session_save(tag, args).await,
            "EXTRACT" => self.dali_session_extract(tag, args).await,
            "DEPLOY" => self.dali_session_deploy(tag, args).await,
            _ => syntax(tag),
        }
    }

    async fn dali_session_list(&self, tag: &str, args: &[String]) -> Response {
        if !args.is_empty() {
            return syntax(tag);
        }
        let state = self.dali_state.lock().await;
        if state.sessions.is_empty() {
            return err(tag, 450, "450 no active sessions.");
        }
        rows(
            tag,
            130,
            state
                .sessions
                .values()
                .map(|session| session.summary().to_string())
                .collect(),
        )
    }

    async fn dali_session_new(&self, tag: &str, args: &[String]) -> Response {
        if !(1..=2).contains(&args.len()) || args[0].is_empty() {
            return syntax(tag);
        }
        let project = args.get(1).map_or(self.project.as_str(), String::as_str);
        if !self.model.lock().await.projects.contains_key(project) {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        }
        let mut state = self.dali_state.lock().await;
        if state.sessions.contains_key(&args[0]) {
            return err(
                tag,
                501,
                &format!("501 session name already exists: {}", args[0]),
            );
        }
        let oid = state.fresh_oid();
        state
            .sessions
            .insert(args[0].clone(), DaliSession::new(&args[0], project, &oid));
        ok(
            tag,
            vec![
                format!("120-using project: {project}"),
                format!("120-created new session: {}", args[0]),
            ],
            "200 OK.",
        )
    }

    async fn dali_session_end(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 1 {
            return syntax(tag);
        }
        if self
            .dali_state
            .lock()
            .await
            .sessions
            .remove(&args[0])
            .is_some()
        {
            ok(
                tag,
                vec![format!("120-ended session: {}", args[0])],
                "200 OK.",
            )
        } else {
            err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            )
        }
    }

    async fn dali_session_get(&self, tag: &str, args: &[String], multiple: bool) -> Response {
        if args.len() != 2 {
            return syntax(tag);
        }
        let state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        let model = session_model(session);
        let selected = select_json(&model, &args[1]);
        if selected.is_empty() {
            return err(tag, 502, "502 jxpath not found");
        }
        if multiple {
            ok(
                tag,
                selected
                    .into_iter()
                    .map(|(_, value)| format!("120-{value}"))
                    .collect(),
                "200 OK.",
            )
        } else {
            let (path, value) = &selected[0];
            ok(
                tag,
                vec![format!("120-{path}"), format!("120-{value}")],
                "200 OK.",
            )
        }
    }

    async fn dali_session_set(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 3 {
            return syntax(tag);
        }
        let value = match serde_json::from_str::<Value>(&args[2]) {
            Ok(value) => value,
            Err(error) => return err(tag, 503, &format!("503 bad json: {error}")),
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        let path = match set_json(&mut session.model, &args[1], value) {
            Ok(path) => path,
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 jxpath writeclass exception: {error}"),
                )
            }
        };
        session.model_dirty = true;
        if path.starts_with("/catalog") || path.is_empty() {
            session.catalog_dirty = true;
        }
        let value = session.model.pointer(&path).cloned().unwrap_or(Value::Null);
        ok(
            tag,
            vec![format!("120-{path}"), format!("120-{value}")],
            "200 OK.",
        )
    }

    async fn dali_session_set_ext(&self, tag: &str, args: &[String]) -> Response {
        if !(3..=18).contains(&args.len()) {
            return syntax(tag);
        }
        let address = match number(tag, &args[1], "<address>", 0, EXT_END) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let mut bytes = Vec::with_capacity(args.len() - 2);
        for (index, value) in args[2..].iter().enumerate() {
            match number(tag, value, &format!("<value-{}>", index + 1), 0, 255) {
                Ok(value) => bytes.push(value as u8),
                Err(response) => return response,
            }
        }
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        match session.stage_ext(address, &bytes) {
            Ok(()) => ok(tag, vec![], "200 OK."),
            Err(error) => err(tag, 522, &format!("522 Failed set @ <value-0> :{error}")),
        }
    }

    async fn dali_session_catalog_add(&self, tag: &str, args: &[String]) -> Response {
        if !(3..=4).contains(&args.len()) {
            return syntax(tag);
        }
        let line = match line_arg(tag, &args[2]) {
            Ok(line) => line,
            Err(response) => return response,
        };
        let requested = match args.get(3) {
            None => None,
            Some(value) if value == "-1" => None,
            Some(value) => match number(tag, value, "<dali-OID>", 0, 63) {
                Ok(value) => Some(value as u8),
                Err(response) => return response,
            },
        };
        let mut state = self.dali_state.lock().await;
        let Some(entry) = state.catalog.get(&args[1]).cloned() else {
            return err(
                tag,
                501,
                &format!("501 catalog exception: unknown device {}", args[1]),
            );
        };
        let oid = state.fresh_oid();
        let channel_names = entry
            .spec
            .get("channels")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_else(|| vec![json!("ECG_GENERIC")]);
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        let line_id = usize::from(line == DaliLine::B);
        let devices = session
            .model
            .pointer_mut(&format!("/catalog/catalogueLines/{line_id}/devices"))
            .and_then(Value::as_array_mut)
            .expect("new session always has two catalogue lines");
        let used = devices
            .iter()
            .filter_map(|device| device.get("daliOid").and_then(Value::as_u64))
            .collect::<HashSet<_>>();
        let dali_oid = requested
            .map(u64::from)
            .or_else(|| (0..64).find(|candidate| !used.contains(candidate)));
        let Some(dali_oid) = dali_oid else {
            return err(tag, 502, "502 session catalog exception: no free DALI OID");
        };
        if used.contains(&dali_oid) {
            return err(
                tag,
                502,
                "502 session catalog exception: DALI OID already used",
            );
        }
        let mut channels = Vec::new();
        let mut session_oids = Vec::new();
        for (index, name) in channel_names.into_iter().enumerate() {
            let channel_oid = format!("{oid}-channel-{}", index + 1);
            session_oids.push(channel_oid.clone());
            channels.push(json!({
                "OID": channel_oid,
                "name": name,
                "daliOid": dali_oid + index as u64,
                "shortAddress": dali_oid + index as u64,
            }));
        }
        devices.push(json!({
            "OID": oid,
            "name": entry.name,
            "lineId": line_id,
            "daliOid": dali_oid,
            "channels": channels,
        }));
        session.model_dirty = true;
        session.catalog_dirty = true;
        let dali_oids = (0..session_oids.len())
            .map(|index| (dali_oid + index as u64).to_string())
            .collect::<Vec<_>>()
            .join(",");
        let session_oids = session_oids.join(",");
        ok(
            tag,
            vec![format!(
                "120-created: {oid} with daliOIDs: [{dali_oids}] with daliSAs: [{dali_oids}] with sessionOIDs: [{session_oids}]"
            )],
            "200 OK.",
        )
    }

    async fn dali_session_catalog_remove(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 2 {
            return syntax(tag);
        }
        let sought = args[1].trim_start_matches('!');
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        for line in 0..2 {
            let devices = session
                .model
                .pointer_mut(&format!("/catalog/catalogueLines/{line}/devices"))
                .and_then(Value::as_array_mut)
                .expect("session catalogue lines remain arrays");
            if let Some(index) = devices.iter().position(|device| {
                device
                    .get("OID")
                    .and_then(Value::as_str)
                    .is_some_and(|oid| oid.trim_start_matches('!') == sought)
            }) {
                let removed = devices.remove(index);
                let channels = removed
                    .get("channels")
                    .and_then(Value::as_array)
                    .map_or(0, Vec::len);
                session.model_dirty = true;
                session.catalog_dirty = true;
                return ok(
                    tag,
                    vec![format!("120-removed channelCount: {channels}")],
                    "200 OK.",
                );
            }
        }
        err(
            tag,
            501,
            &format!("501 dali catalogue device not found for: {}", args[1]),
        )
    }

    async fn dali_session_save(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 2 {
            return syntax(tag);
        }
        let (_, oid) = match self.dali_gateway_identity(tag, &args[1]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let saved = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(&args[0]) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {}", args[0]),
                );
            };
            let mut snapshot = session.clone();
            snapshot.target_unit = Some(args[1].clone());
            snapshot.saved()
        };
        let mut model = self.model.lock().await;
        let previous = model.dali_saved_sessions.insert(oid.clone(), saved);
        if let Err(error) = Database::from_server(&model).save(&self.state_path) {
            if let Some(previous) = previous {
                model.dali_saved_sessions.insert(oid, previous);
            } else {
                model.dali_saved_sessions.remove(&oid);
            }
            tracing::error!("DALI session database commit failed: {error}");
            return err(
                tag,
                500,
                "500 Database commit failed; DALI session not saved",
            );
        }
        drop(model);
        if let Some(session) = self.dali_state.lock().await.sessions.get_mut(&args[0]) {
            session.target_unit = Some(args[1].clone());
        }
        ok(tag, vec!["120-start save".to_string()], "200 OK.")
    }

    async fn dali_session_load(&self, tag: &str, args: &[String]) -> Response {
        if args.len() != 2 {
            return syntax(tag);
        }
        let (_, oid) = match self.dali_gateway_identity(tag, &args[1]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let saved = self
            .model
            .lock()
            .await
            .dali_saved_sessions
            .get(&oid)
            .cloned();
        let Some(saved) = saved else {
            return err(
                tag,
                501,
                "501 load error: Invalid dali session: No dali session found",
            );
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        };
        session.load_saved(&saved);
        session.source_unit = Some(args[1].clone());
        ok(tag, vec!["120-start load".to_string()], "200 OK.")
    }

    async fn dali_gateway_identity(
        &self,
        tag: &str,
        target: &str,
    ) -> Result<(u8, String), Response> {
        let (unit, _) = self.dali_gateway(tag, target).await?;
        let model = self.model.lock().await;
        let oid = model
            .projects
            .get(&self.project)
            .and_then(|project| project.networks.get(&self.network))
            .and_then(|network| network.units.get(&unit))
            .map(|unit| unit.oid.clone())
            .ok_or_else(|| err(tag, 442, "442 database DALI gateway unit is not available"))?;
        Ok((unit, oid))
    }

    async fn dali_session_extract(&self, tag: &str, args: &[String]) -> Response {
        if !(4..=5).contains(&args.len()) {
            return syntax(tag);
        }
        let lines = match session_line(tag, &args[2]) {
            Ok(lines) => lines,
            Err(response) => return response,
        };
        let extract_type = args[3].to_ascii_uppercase();
        if !matches!(
            extract_type.as_str(),
            "EXT_ONLY"
                | "DALI_ONLY"
                | "COND_QUICK"
                | "COND_EXTENDED"
                | "FULL"
                | "RESCAN_FAULT"
                | "REFRESH_STATUS_INFO"
                | "RETRIEVE_RECONCILE"
        ) {
            return err(
                tag,
                400,
                &format!("400 failed parse <extract-type>: {}", args[3]),
            );
        }
        let range = match args.get(4).map(|range| ecg_range(tag, range)) {
            Some(Ok(range)) => Some(range),
            Some(Err(response)) => return response,
            None => None,
        };
        if matches!(
            extract_type.as_str(),
            "REFRESH_STATUS_INFO" | "RETRIEVE_RECONCILE"
        ) {
            return self
                .dali_session_extract_typed(
                    tag,
                    &args[0],
                    &args[1],
                    lines,
                    range.as_deref(),
                    &extract_type,
                )
                .await;
        }
        if matches!(extract_type.as_str(), "DALI_ONLY" | "FULL") {
            return self
                .dali_session_extract_read_only(
                    tag,
                    &args[0],
                    &args[1],
                    lines,
                    range.as_deref(),
                    &extract_type,
                )
                .await;
        }
        if matches!(
            extract_type.as_str(),
            "COND_QUICK" | "COND_EXTENDED" | "RESCAN_FAULT"
        ) {
            return self
                .dali_session_extract_conditional(
                    tag,
                    &args[0],
                    &args[1],
                    lines,
                    range.as_deref(),
                    &extract_type,
                )
                .await;
        }
        if extract_type != "EXT_ONLY" {
            return err(
                tag,
                502,
                "502 DALI session extraction plan is not evidenced for this selector; no bus command was sent",
            );
        }
        let (session_instance, ext_revision, original_source_cdg) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(&args[0]) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {}", args[0]),
                );
            };
            (
                session.instance_id.clone(),
                session.ext_revision,
                session.source_cdg.clone(),
            )
        };
        let (unit, _) = match self.dali_gateway(tag, &args[1]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let bytes = match pci.recall_paged_parameter(unit, EXT_START, EXT_LEN).await {
            Ok(bytes) => bytes,
            Err(error) => return err(tag, 503, &format!("503 network error: {error}")),
        };
        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                503,
                "503 network error: PCI connection changed during extraction",
            );
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(tag, 501, "501 session ended during extraction");
        };
        if session.instance_id != session_instance
            || session.ext_revision != ext_revision
            || session.source_cdg != original_source_cdg
        {
            return err(tag, 501, "501 session changed during extraction");
        }
        session.replace_ext(bytes);
        session.source_cdg = Some(args[1].clone());
        ok(tag, vec!["120-start extraction".to_string()], "200 OK.")
    }

    async fn dali_session_deploy(&self, tag: &str, args: &[String]) -> Response {
        if !(4..=5).contains(&args.len()) {
            return syntax(tag);
        }
        let lines = match session_line(tag, &args[2]) {
            Ok(lines) => lines,
            Err(response) => return response,
        };
        let deploy_type = args[3].to_ascii_uppercase();
        if !matches!(deploy_type.as_str(), "EXT_ONLY" | "DALI_ONLY" | "FULL") {
            return err(
                tag,
                400,
                &format!("400 failed parse <deploy-type>: {}", args[3]),
            );
        }
        let range = match args.get(4).map(|range| ecg_range(tag, range)) {
            Some(Ok(range)) => Some(range),
            Some(Err(response)) => return response,
            None => None,
        };
        if deploy_type != "EXT_ONLY" {
            return self
                .dali_session_deploy_typed(
                    tag,
                    &args[0],
                    &args[1],
                    lines,
                    range.as_deref(),
                    &deploy_type,
                )
                .await;
        }
        let (session_instance, ext_epoch, chunks, model_dirty) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(&args[0]) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {}", args[0]),
                );
            };
            (
                session.instance_id.clone(),
                session.ext_epoch,
                session.ext.dirty_chunks(),
                session.model_dirty,
            )
        };
        if model_dirty {
            return err(
                tag,
                501,
                "501 gateway model mismatch: model changes require an evidenced DALI deployment plan",
            );
        }
        let (unit, _) = match self.dali_gateway(tag, &args[1]).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        for (index, (address, bytes)) in chunks.iter().enumerate() {
            if let Err(error) = pci
                .store_paged_parameter_verified(unit, *address, bytes, false)
                .await
            {
                return err(
                    tag,
                    503,
                    &format!("503 network error after {index} confirmed chunk(s): {error}"),
                );
            }
            let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
                return err(
                    tag,
                    503,
                    "503 network error: PCI connection changed during deploy; outcome is uncertain",
                );
            };
            let mut state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get_mut(&args[0]) else {
                return err(tag, 501, "501 session ended during deploy");
            };
            if session.instance_id != session_instance || session.ext_epoch != ext_epoch {
                return err(tag, 501, "501 session changed during deploy");
            }
            session.commit_ext_chunk(*address, bytes);
        }
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(&args[0]) else {
            return err(tag, 501, "501 session ended during deploy");
        };
        if session.instance_id != session_instance || session.ext_epoch != ext_epoch {
            return err(tag, 501, "501 session changed during deploy");
        }
        session.target_cdg = Some(args[1].clone());
        ok(tag, vec!["120-start deploy".to_string()], "200 OK.")
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_session_deploy_typed(
        &self,
        tag: &str,
        session_name: &str,
        target: &str,
        lines: (bool, bool),
        range: Option<&[u8]>,
        deploy_type: &str,
    ) -> Response {
        let full = deploy_type == "FULL";
        let (instance, model, catalog_dirty, ext_epoch, chunks, project) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(session_name) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {session_name}"),
                );
            };
            if let Err(error) = typed_session_targets(session, lines, range) {
                return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
            }
            (
                session.instance_id.clone(),
                session.model.clone(),
                session.catalog_dirty,
                session.ext_epoch,
                session.ext.dirty_chunks(),
                session.project.clone(),
            )
        };
        let (unit, _) = match self.dali_gateway(tag, target).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        if full && catalog_dirty {
            return err(
                tag,
                501,
                "501 gateway model mismatch: catalogue edits require native typed extended-proxy serialization before WRITE_GATEWAY_EXT_FULL, which cmqttd does not implement; no bus command was sent",
            );
        }
        // Every payload is derived from one model snapshot before I/O, so a
        // missing or invalid field refuses the whole plan instead of stopping
        // after earlier ECGs were written (a deliberate native deviation).
        let steps = match typed_deploy_plan(&model, lines, range) {
            Ok(steps) => steps,
            Err(warning) => {
                return Response {
                    tag: tag.to_string(),
                    // The formatter adds the native `501-` envelope.
                    lines: vec![warning.clone()],
                    final_text: format!(
                        "501 gateway model mismatch: {warning}; no bus command was sent"
                    ),
                    status: 501,
                };
            }
        };
        let mut planned = steps
            .iter()
            .flat_map(|step| step.phases.iter().flatten())
            .map(|write| DaliJournalWrite {
                step: write.step.to_string(),
                operation: Some(write.operation),
                line: Some(write.line.name().to_string()),
                address: Some(u32::from(write.address)),
                payload_hex: hex::encode_upper(&write.payload),
            })
            .collect::<Vec<_>>();
        if full {
            planned.extend(chunks.iter().map(|(address, bytes)| DaliJournalWrite {
                step: "WRITE_GATEWAY_EXT_FULL".to_string(),
                operation: None,
                line: None,
                address: Some(*address),
                payload_hex: hex::encode_upper(bytes),
            }));
        }
        let (generation, pci) = self.current_pci_epoch().await;
        let mut journal = None;
        if !planned.is_empty() {
            match ActiveDaliJournal::create(
                &dali_journal::journal_directory(&self.state_path),
                DaliJournalPlan {
                    command: format!("DALI SESSION DEPLOY {deploy_type}"),
                    session: session_name,
                    project: &project,
                    gateway_unit: unit,
                    pci_generation: generation,
                    planned,
                },
            ) {
                Ok(created) => journal = Some(created),
                Err(error) => return dali_journal::journal_refused(tag, &error),
            }
        }
        // Native records the command's CDG as the session target before the
        // plan runs, whatever its outcome.
        {
            let mut state = self.dali_state.lock().await;
            if let Some(session) = state.sessions.get_mut(session_name) {
                if session.instance_id == instance {
                    session.target_cdg = Some(target.to_string());
                }
            }
        }
        let mut response_lines = vec!["120-start deploy".to_string()];
        let total = steps.len() + usize::from(full);
        let stop = |journal: &mut Option<ActiveDaliJournal>,
                    lines: Vec<String>,
                    failure: Response,
                    uncertain: bool| {
            let mut failure = failure;
            let mut all = lines;
            all.append(&mut failure.lines);
            failure.lines = all;
            if let Some(journal) = journal.as_mut() {
                journal.stopped(uncertain, &failure.final_text);
                failure.final_text = format!("{} ({})", failure.final_text, journal.summary());
            }
            failure
        };
        for (index, step) in steps.iter().enumerate() {
            response_lines.push(format!(
                "120-progress: {}/{total}, plan: {}",
                index + 1,
                step.name
            ));
            for phase in &step.phases {
                if phase.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for write in phase {
                    let exchange = match self
                        .dali_session_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            write.line,
                            DaliCalMode::Auto,
                            write.operation,
                            &write.payload,
                            write.step,
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => {
                            return stop(&mut journal, response_lines, response, true);
                        }
                    };
                    if exchange.nak || exchange.status != 0 {
                        // A gateway still reporting IN_PROGRESS/FAIL_BUSY after
                        // the poll budget may yet complete the write.
                        let uncertain = !exchange.nak && matches!(exchange.status, 1 | 2);
                        let status = if exchange.nak {
                            "NAK"
                        } else {
                            dali_status_name(exchange.status)
                        };
                        let failure = err(
                            tag,
                            502,
                            &format!(
                                "502 reply status error: error response: {status} during {} for ecg: {}",
                                write.step, write.address
                            ),
                        );
                        return stop(&mut journal, response_lines, failure, uncertain);
                    }
                    if let Some(active) = journal.as_mut() {
                        if let Err(error) = active.confirm(dali_status_name(exchange.status)) {
                            let failure = err(
                                tag,
                                503,
                                &format!("503 network error: DALI journal update failed after a confirmed write: {error}"),
                            );
                            return stop(&mut journal, response_lines, failure, false);
                        }
                    }
                }
            }
        }
        if full {
            response_lines.push(format!(
                "120-progress: {total}/{total}, plan: WRITE_GATEWAY_EXT_FULL"
            ));
            for (address, bytes) in &chunks {
                if let Err(error) = pci
                    .store_paged_parameter_verified(unit, *address, bytes, false)
                    .await
                {
                    let failure = err(
                        tag,
                        503,
                        &format!("503 network error during WRITE_GATEWAY_EXT_FULL: {error}"),
                    );
                    return stop(&mut journal, response_lines, failure, true);
                }
                let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
                    let failure = err(
                        tag,
                        503,
                        "503 network error: PCI connection changed during deploy; outcome is uncertain",
                    );
                    return stop(&mut journal, response_lines, failure, true);
                };
                if let Some(active) = journal.as_mut() {
                    if let Err(error) = active.confirm("VERIFIED") {
                        let failure = err(
                            tag,
                            503,
                            &format!("503 network error: DALI journal update failed after a confirmed write: {error}"),
                        );
                        return stop(&mut journal, response_lines, failure, false);
                    }
                }
                let mut state = self.dali_state.lock().await;
                let Some(session) = state.sessions.get_mut(session_name).filter(|session| {
                    session.instance_id == instance && session.ext_epoch == ext_epoch
                }) else {
                    drop(state);
                    let failure = err(tag, 501, "501 session changed during deploy");
                    return stop(&mut journal, response_lines, failure, false);
                };
                session.commit_ext_chunk(*address, bytes);
            }
        }
        if let Some(active) = journal.as_mut() {
            if let Err(error) = active.complete() {
                tracing::warn!(journal = %active.id(), "DALI journal completion failed: {error}");
            }
            dali_journal::prune_finished(&dali_journal::journal_directory(&self.state_path));
        }
        let mut state = self.dali_state.lock().await;
        if let Some(session) = state.sessions.get_mut(session_name) {
            // The deployed snapshot now matches the gateway's typed state;
            // a concurrent edit or a catalogue change keeps the model dirty.
            if session.instance_id == instance && session.model == model && !session.catalog_dirty {
                session.model_dirty = false;
            }
        }
        ok(tag, response_lines, "200 OK.")
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_session_extract_conditional(
        &self,
        tag: &str,
        session_name: &str,
        target: &str,
        lines: (bool, bool),
        range: Option<&[u8]>,
        extract_type: &str,
    ) -> Response {
        let (original_model, original_ext, original_source_cdg, project, mut staged_model) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(session_name) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {session_name}"),
                );
            };
            (
                session.model.clone(),
                session.ext.as_json(),
                session.source_cdg.clone(),
                session.project.clone(),
                session.model.clone(),
            )
        };
        if let Err(error) = ensure_read_only_extract_model(&mut staged_model, lines) {
            return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
        }
        let (unit, _) = match self.dali_gateway(tag, target).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let plan = match extract_type {
            "RESCAN_FAULT" => RESCAN_FAULT_EXTRACT_PLAN,
            "COND_EXTENDED" => COND_EXTENDED_EXTRACT_PLAN,
            _ => COND_QUICK_EXTRACT_PLAN,
        };
        let mut run = ConditionalRun {
            lines: vec!["120-start extraction".to_string()],
            staged_ext: Vec::new(),
            journal: None,
            address_unknown_uncertain: false,
        };
        let context = ConditionalContext {
            tag,
            generation,
            pci: &pci,
            unit,
            lines,
            range,
            session_name,
            project: &project,
            extract_type,
        };
        let outcome = self
            .run_conditional_plan(&context, plan, &mut staged_model, &mut run)
            .await;
        let commit = |run: &ConditionalRun, staged_model: Value| {
            self.dali_conditional_commit(
                tag,
                generation,
                &pci,
                session_name,
                target,
                (&original_model, &original_ext, &original_source_cdg),
                staged_model,
                run.staged_ext.clone(),
            )
        };
        match outcome {
            Ok(()) => {
                if let Err(mut failure) = commit(&run, staged_model).await {
                    // ADDRESS_UNKNOWN already ran; the journal is complete
                    // because every device-changing exchange was answered.
                    if let Some(journal) = run.journal.as_mut() {
                        let _ = journal.complete();
                        failure.final_text =
                            format!("{} ({})", failure.final_text, journal.summary());
                    }
                    return failure;
                }
                if let Some(journal) = run.journal.as_mut() {
                    if run.address_unknown_uncertain {
                        // Native only warns, but the gateway may still be
                        // assigning addresses: keep the record open.
                        journal.stopped(
                            true,
                            "ADDRESS_UNKNOWN still running after the native poll budget",
                        );
                    } else if let Err(error) = journal.complete() {
                        tracing::warn!(journal = %journal.id(), "DALI journal completion failed: {error}");
                    }
                    dali_journal::prune_finished(&dali_journal::journal_directory(
                        &self.state_path,
                    ));
                }
                ok(tag, run.lines, "200 OK.")
            }
            Err(mut failure) => {
                let mut all = std::mem::take(&mut run.lines);
                all.append(&mut failure.lines);
                failure.lines = all;
                if run.journal.is_none() {
                    // Nothing that can change a device was sent: keep the
                    // atomic read-only contract and commit nothing.
                    return failure;
                }
                // ADDRESS_UNKNOWN was sent, so the bus may have changed.
                // Native mutates its model step by step; keep everything
                // learned before the failure rather than discard it.
                let note = match commit(&run, staged_model).await {
                    Ok(()) => "session model through the failed step was committed because ADDRESS_UNKNOWN was sent".to_string(),
                    Err(response) => format!("session was not updated: {}", response.final_text),
                };
                let journal = run.journal.as_mut().expect("checked above");
                if run.address_unknown_uncertain
                    || journal.record().confirmed_writes < journal.record().planned.len()
                {
                    journal.stopped(run.address_unknown_uncertain, &failure.final_text);
                } else if let Err(error) = journal.complete() {
                    tracing::warn!(journal = %journal.id(), "DALI journal completion failed: {error}");
                }
                failure.final_text =
                    format!("{}; {note} ({})", failure.final_text, journal.summary());
                failure
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_conditional_commit(
        &self,
        tag: &str,
        generation: u64,
        pci: &Arc<PciClient>,
        session_name: &str,
        target: &str,
        original: (&Value, &Value, &Option<String>),
        staged_model: Value,
        staged_ext: Vec<(u32, Vec<u8>)>,
    ) -> Result<(), Response> {
        let (original_model, original_ext, original_source_cdg) = original;
        let Some(_guard) = self.pci_commit_guard(generation, pci).await else {
            return Err(err(
                tag,
                503,
                "503 network error: PCI connection changed during conditional extraction",
            ));
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(session_name) else {
            return Err(err(tag, 501, "501 session ended during extraction"));
        };
        if session.model != *original_model
            || session.source_cdg != *original_source_cdg
            || (!staged_ext.is_empty() && session.ext.as_json() != *original_ext)
        {
            return Err(err(tag, 501, "501 session changed during extraction"));
        }
        session.model = staged_model;
        if !staged_ext.is_empty() {
            for (address, bytes) in &staged_ext {
                session.ext.update_values(*address, bytes);
            }
            session.ext_revision = session.ext_revision.wrapping_add(1);
            session.ext_epoch = session.ext_epoch.wrapping_add(1);
        }
        session.source_cdg = Some(target.to_string());
        Ok(())
    }

    async fn run_conditional_plan(
        &self,
        context: &ConditionalContext<'_>,
        plan: &[ConditionalExtractStep],
        model: &mut Value,
        run: &mut ConditionalRun,
    ) -> Result<(), Response> {
        let tag = context.tag;
        let mismatch = |error: &str| err(tag, 501, &format!("501 gateway model mismatch: {error}"));
        for (index, step) in plan.iter().copied().enumerate() {
            let step_name = step.name();
            run.lines.push(format!(
                "120-progress: {}/{}, plan: {step_name}",
                index + 1,
                plan.len()
            ));
            match step {
                ConditionalExtractStep::Rescan => {
                    for (_, line) in selected_dali_lines(context.lines) {
                        let exchange = self
                            .dali_session_budgeted_exchange(
                                context,
                                line,
                                RESCAN_BUDGET,
                                14,
                                step_name,
                            )
                            .await?;
                        if exchange.nak || exchange.status != 0 {
                            run.lines
                                .push("300-[WARN] rescan replyStatus ignored".to_string());
                        }
                    }
                }
                ConditionalExtractStep::PollFinishDiscoverKnownFullInfo => {
                    for (line_index, line) in selected_dali_lines(context.lines) {
                        let exchange = self
                            .dali_session_budgeted_exchange(
                                context,
                                line,
                                POLL_FINISH_BUDGET,
                                4,
                                step_name,
                            )
                            .await?;
                        let payload = line_success_payload(tag, step_name, &exchange, 8)?;
                        clear_ecg_status_flags(model, line_index, context.range)
                            .map_err(mismatch)?;
                        apply_line_mask(
                            model,
                            line_index,
                            context.range,
                            "isFullyKnown",
                            payload,
                            true,
                        )
                        .map_err(mismatch)?;
                    }
                }
                ConditionalExtractStep::Missing
                | ConditionalExtractStep::Broken
                | ConditionalExtractStep::Conflicting => {
                    let (operation, field) = match step {
                        ConditionalExtractStep::Missing => (11, "isMissing"),
                        ConditionalExtractStep::Broken => (10, "isBroken"),
                        _ => (9, "isConflicting"),
                    };
                    for (line_index, line) in selected_dali_lines(context.lines) {
                        let exchange = self
                            .dali_session_budgeted_exchange(
                                context,
                                line,
                                DaliPollBudget::NATIVE_DEFAULT,
                                operation,
                                step_name,
                            )
                            .await?;
                        let payload = line_success_payload(tag, step_name, &exchange, 8)?;
                        apply_line_mask(model, line_index, context.range, field, payload, false)
                            .map_err(mismatch)?;
                    }
                }
                ConditionalExtractStep::AddressUnknown => {
                    let selected = selected_dali_lines(context.lines);
                    if run.journal.is_none() {
                        let planned = selected
                            .iter()
                            .map(|(_, line)| DaliJournalWrite {
                                step: step_name.to_string(),
                                operation: Some(2),
                                line: Some(line.name().to_string()),
                                address: None,
                                payload_hex: String::new(),
                            })
                            .collect();
                        let journal = ActiveDaliJournal::create(
                            &dali_journal::journal_directory(&self.state_path),
                            DaliJournalPlan {
                                command: format!("DALI SESSION EXTRACT {}", context.extract_type),
                                session: context.session_name,
                                project: context.project,
                                gateway_unit: context.unit,
                                pci_generation: context.generation,
                                planned,
                            },
                        )
                        .map_err(|error| dali_journal::journal_refused(tag, &error))?;
                        run.journal = Some(journal);
                    }
                    for (line_index, line) in selected {
                        let exchange = match self
                            .dali_session_budgeted_exchange(
                                context,
                                line,
                                ADDRESS_UNKNOWN_BUDGET,
                                2,
                                step_name,
                            )
                            .await
                        {
                            Ok(exchange) => exchange,
                            Err(response) => {
                                // Operation 2 may have assigned addresses.
                                // It is never replayed.
                                run.address_unknown_uncertain = true;
                                return Err(response);
                            }
                        };
                        let success = !exchange.nak && exchange.status == 0;
                        let note = if exchange.nak {
                            "NAK".to_string()
                        } else {
                            format!(
                                "{} {}",
                                dali_status_name(exchange.status),
                                hex::encode_upper(&exchange.data)
                            )
                        };
                        if let Some(journal) = run.journal.as_mut() {
                            journal.confirm(note.trim_end()).map_err(|error| {
                                err(
                                    tag,
                                    503,
                                    &format!("503 network error: DALI journal update failed after ADDRESS_UNKNOWN: {error}"),
                                )
                            })?;
                        }
                        if !success {
                            // A still-running gateway may finish assigning
                            // after the budget; native only warns.
                            run.address_unknown_uncertain |= matches!(exchange.status, 1 | 2);
                            run.lines
                                .push("300-[WARN] address unknown incomplete".to_string());
                            continue;
                        }
                        set_line_property(model, line_index, "containsUnaddressed", json!(false))
                            .map_err(mismatch)?;
                        if exchange.data.len() != 8 {
                            return Err(err(
                                tag,
                                504,
                                &format!(
                                    "504 dali sync error: {step_name} has invalid payload {}",
                                    hex::encode_upper(&exchange.data)
                                ),
                            ));
                        }
                        apply_line_mask(
                            model,
                            line_index,
                            context.range,
                            "isAddressKnown",
                            &exchange.data,
                            false,
                        )
                        .map_err(mismatch)?;
                    }
                }
                ConditionalExtractStep::CondDiscoverKnownTypeInfo
                | ConditionalExtractStep::CondDiscoverKnownFullInfo => {
                    let type_step = step == ConditionalExtractStep::CondDiscoverKnownTypeInfo;
                    let needed = conditional_discovery_needed(model, context.lines);
                    run.lines.push(format!(
                        "125-[COND] discovery{}: {needed}",
                        if type_step { 1 } else { 2 }
                    ));
                    if !needed {
                        continue;
                    }
                    for (line_index, line) in selected_dali_lines(context.lines) {
                        if type_step {
                            let exchange = self
                                .dali_session_budgeted_exchange(
                                    context,
                                    line,
                                    DISCOVER_TYPE_BUDGET,
                                    3,
                                    step_name,
                                )
                                .await?;
                            line_success(tag, step_name, &exchange)?;
                        } else {
                            let exchange = self
                                .dali_session_budgeted_exchange(
                                    context,
                                    line,
                                    DISCOVER_FULL_BUDGET,
                                    4,
                                    step_name,
                                )
                                .await?;
                            let payload = line_success_payload(tag, step_name, &exchange, 8)?;
                            apply_line_mask(
                                model,
                                line_index,
                                context.range,
                                "isFullyKnown",
                                payload,
                                true,
                            )
                            .map_err(mismatch)?;
                        }
                    }
                }
                ConditionalExtractStep::ReadGatewayExtCondQuick => {
                    for (start, end) in cond_quick_ext_ranges(context.lines) {
                        let bytes = context
                            .pci
                            .recall_paged_parameter(context.unit, start, (end - start) as usize)
                            .await
                            .map_err(|error| {
                                err(
                                    tag,
                                    503,
                                    &format!("503 network error during {step_name}: {error}"),
                                )
                            })?;
                        if self
                            .pci_commit_guard(context.generation, context.pci)
                            .await
                            .is_none()
                        {
                            return Err(err(
                                tag,
                                503,
                                &format!(
                                    "503 network error: PCI connection changed during {step_name}"
                                ),
                            ));
                        }
                        run.staged_ext.push((start, bytes));
                    }
                }
                point_step => {
                    let read_step = match point_step {
                        ConditionalExtractStep::GetKnownTypeInfoEcg => {
                            ReadOnlyExtractStep::GetKnownTypeInfoEcg
                        }
                        ConditionalExtractStep::CondGetCommonReadOnlyParamsEcg
                        | ConditionalExtractStep::CondBrokenGetCommonReadOnlyParamsEcg => {
                            ReadOnlyExtractStep::GetCommonReadOnlyParamsEcg
                        }
                        ConditionalExtractStep::GetEmergencyParamsEcg => {
                            ReadOnlyExtractStep::GetEmergencyParamsEcg
                        }
                        ConditionalExtractStep::CondBrokenGetEmergencyStatusEcg => {
                            ReadOnlyExtractStep::GetEmergencyStatusEcg
                        }
                        _ => ReadOnlyExtractStep::GetCommonParamsEcg,
                    };
                    let targets = typed_model_targets(model, context.lines, context.range)
                        .map_err(mismatch)?
                        .into_iter()
                        .filter(|target| {
                            let broken = || {
                                target_flag(model, target, "isBroken")
                                    || target_flag(model, target, "isPreviouslyBroken")
                            };
                            match point_step {
                                ConditionalExtractStep::CondGetCommonReadOnlyParamsEcg
                                | ConditionalExtractStep::GetEmergencyParamsEcg => target.emergency,
                                ConditionalExtractStep::CondBrokenGetCommonReadOnlyParamsEcg => {
                                    broken() && (!target.emergency || !target.has_common_read_only)
                                }
                                ConditionalExtractStep::CondBrokenGetEmergencyStatusEcg => {
                                    broken() && target.emergency
                                }
                                _ => true,
                            }
                        })
                        .collect::<Vec<_>>();
                    if targets.is_empty() {
                        run.lines
                            .push("300-[WARN] no commands sent - no known ecgs".to_string());
                    }
                    for target_model in targets {
                        self.dali_read_only_point_step(
                            tag,
                            context.generation,
                            context.pci,
                            context.unit,
                            model,
                            &target_model,
                            read_step,
                            &mut run.lines,
                        )
                        .await?;
                    }
                }
            }
        }
        Ok(())
    }

    async fn dali_session_budgeted_exchange(
        &self,
        context: &ConditionalContext<'_>,
        line: DaliLine,
        budget: DaliPollBudget,
        operation: u8,
        step: &str,
    ) -> Result<cbus_transport::pci::DaliExchange, Response> {
        self.dali_session_exchange_with(
            context.tag,
            context.generation,
            context.pci,
            context.unit,
            line,
            Some(budget),
            DaliCalMode::Auto,
            operation,
            &[],
            step,
        )
        .await
    }

    async fn dali_session_extract_read_only(
        &self,
        tag: &str,
        session_name: &str,
        target: &str,
        lines: (bool, bool),
        range: Option<&[u8]>,
        extract_type: &str,
    ) -> Response {
        let (original_model, original_ext, original_source_cdg, mut staged_model) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(session_name) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {session_name}"),
                );
            };
            (
                session.model.clone(),
                session.ext.as_json(),
                session.source_cdg.clone(),
                session.model.clone(),
            )
        };
        if let Err(error) = ensure_read_only_extract_model(&mut staged_model, lines) {
            return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
        }
        let (unit, _) = match self.dali_gateway(tag, target).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let plan = if extract_type == "DALI_ONLY" {
            DALI_ONLY_EXTRACT_PLAN
        } else {
            FULL_EXTRACT_PLAN
        };
        let mut response_lines = vec!["120-start extraction".to_string()];
        let mut staged_ext = None;

        for (index, step) in plan.iter().copied().enumerate() {
            let step_name = step.name();
            response_lines.push(format!(
                "120-progress: {}/{}, plan: {step_name}",
                index + 1,
                plan.len()
            ));
            match step {
                ReadOnlyExtractStep::CheckForUnknown => {
                    for (line_index, line) in selected_dali_lines(lines) {
                        let exchange = match self
                            .dali_session_exchange(
                                tag,
                                generation,
                                &pci,
                                unit,
                                line,
                                DaliCalMode::Auto,
                                13,
                                &[],
                                step_name,
                            )
                            .await
                        {
                            Ok(exchange) => exchange,
                            Err(response) => return response,
                        };
                        let payload = match line_success_payload(tag, step_name, &exchange, 1) {
                            Ok(payload) => payload,
                            Err(response) => return response,
                        };
                        if let Err(error) = set_line_property(
                            &mut staged_model,
                            line_index,
                            "containsUnaddressed",
                            json!(payload[0] == 1),
                        ) {
                            return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
                        }
                    }
                }
                ReadOnlyExtractStep::PollKnown
                | ReadOnlyExtractStep::Broken
                | ReadOnlyExtractStep::Missing
                | ReadOnlyExtractStep::Conflicting
                | ReadOnlyExtractStep::DiscoverKnownFullInfo => {
                    let (mode, operation, field) = match step {
                        ReadOnlyExtractStep::PollKnown => (DaliCalMode::Poll, 7, "isKnown"),
                        ReadOnlyExtractStep::Broken => (DaliCalMode::Auto, 10, "isBroken"),
                        ReadOnlyExtractStep::Missing => (DaliCalMode::Auto, 11, "isMissing"),
                        ReadOnlyExtractStep::Conflicting => (DaliCalMode::Auto, 9, "isConflicting"),
                        ReadOnlyExtractStep::DiscoverKnownFullInfo => {
                            (DaliCalMode::Auto, 4, "isFullyKnown")
                        }
                        _ => unreachable!(),
                    };
                    // Native overrides DISCOVER_KNOWN_FULL_INFO's budget.
                    let budget = match (step, mode) {
                        (ReadOnlyExtractStep::DiscoverKnownFullInfo, _) => {
                            Some(DISCOVER_FULL_BUDGET)
                        }
                        (_, DaliCalMode::Auto) => Some(DaliPollBudget::NATIVE_DEFAULT),
                        _ => None,
                    };
                    for (line_index, line) in selected_dali_lines(lines) {
                        let exchange = match self
                            .dali_session_exchange_with(
                                tag,
                                generation,
                                &pci,
                                unit,
                                line,
                                budget,
                                mode,
                                operation,
                                &[],
                                step_name,
                            )
                            .await
                        {
                            Ok(exchange) => exchange,
                            Err(response) => return response,
                        };
                        let payload = match line_success_payload(tag, step_name, &exchange, 8) {
                            Ok(payload) => payload,
                            Err(response) => return response,
                        };
                        if let Err(error) = apply_line_mask(
                            &mut staged_model,
                            line_index,
                            range,
                            field,
                            payload,
                            matches!(step, ReadOnlyExtractStep::DiscoverKnownFullInfo),
                        ) {
                            return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
                        }
                    }
                }
                ReadOnlyExtractStep::DiscoverKnownTypeInfo => {
                    for (_, line) in selected_dali_lines(lines) {
                        let exchange = match self
                            .dali_session_exchange_with(
                                tag,
                                generation,
                                &pci,
                                unit,
                                line,
                                Some(DISCOVER_TYPE_BUDGET),
                                DaliCalMode::Auto,
                                3,
                                &[],
                                step_name,
                            )
                            .await
                        {
                            Ok(exchange) => exchange,
                            Err(response) => return response,
                        };
                        if let Err(response) = line_success(tag, step_name, &exchange) {
                            return response;
                        }
                    }
                }
                ReadOnlyExtractStep::ReadGatewayExtFull => {
                    staged_ext = match pci.recall_paged_parameter(unit, EXT_START, EXT_LEN).await {
                        Ok(bytes) => Some(bytes),
                        Err(error) => {
                            return err(
                                tag,
                                503,
                                &format!("503 network error during {step_name}: {error}"),
                            )
                        }
                    };
                }
                point_step => {
                    let targets = match typed_model_targets(&staged_model, lines, range) {
                        Ok(targets) => targets,
                        Err(error) => {
                            return err(tag, 501, &format!("501 gateway model mismatch: {error}"))
                        }
                    };
                    let targets = targets
                        .into_iter()
                        .filter(|target| match point_step {
                            ReadOnlyExtractStep::GetLedParamsEcg => target.led,
                            ReadOnlyExtractStep::GetEmergencyParamsEcg
                            | ReadOnlyExtractStep::GetEmergencyStatusEcg => target.emergency,
                            _ => true,
                        })
                        .collect::<Vec<_>>();
                    if targets.is_empty() {
                        response_lines
                            .push("300-[WARN] no commands sent - no known ecgs".to_string());
                    }
                    for target_model in targets {
                        if let Err(response) = self
                            .dali_read_only_point_step(
                                tag,
                                generation,
                                &pci,
                                unit,
                                &mut staged_model,
                                &target_model,
                                point_step,
                                &mut response_lines,
                            )
                            .await
                        {
                            return response;
                        }
                    }
                }
            }
        }

        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                503,
                "503 network error: PCI connection changed during typed extraction",
            );
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(session_name) else {
            return err(tag, 501, "501 session ended during extraction");
        };
        if session.model != original_model || session.source_cdg != original_source_cdg {
            return err(tag, 501, "501 session changed during extraction");
        }
        if staged_ext.is_some() && session.ext.as_json() != original_ext {
            return err(tag, 501, "501 session changed during extraction");
        }
        session.model = staged_model;
        if let Some(bytes) = staged_ext {
            session.replace_ext(bytes);
        }
        session.source_cdg = Some(target.to_string());
        ok(tag, response_lines, "200 OK.")
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_read_only_point_step(
        &self,
        tag: &str,
        generation: u64,
        pci: &Arc<PciClient>,
        unit: u8,
        model: &mut Value,
        target: &TypedSessionTarget,
        step: ReadOnlyExtractStep,
        response_lines: &mut Vec<String>,
    ) -> Result<(), Response> {
        let step_name = step.name();
        let (operation, payload) = match step {
            ReadOnlyExtractStep::DiscoverStatusInfoEcg => (26, vec![target.address]),
            ReadOnlyExtractStep::GetKnownTypeInfoEcg => (16, vec![target.address]),
            ReadOnlyExtractStep::GetCommonParamsEcg => (17, vec![target.address]),
            ReadOnlyExtractStep::GetCommonReadOnlyParamsEcg => (18, vec![target.address]),
            ReadOnlyExtractStep::GetSceneValuesEcg => (19, vec![target.address]),
            ReadOnlyExtractStep::DiscoverGtinSerialEcg => (27, vec![target.address]),
            ReadOnlyExtractStep::GetGtinEcg => (21, vec![target.address]),
            ReadOnlyExtractStep::GetSerialEcg => (22, vec![target.address]),
            ReadOnlyExtractStep::GetLedParamsEcg => (25, vec![target.address]),
            ReadOnlyExtractStep::GetEmergencyParamsEcg => (23, vec![target.address]),
            ReadOnlyExtractStep::GetEmergencyStatusEcg => (24, vec![target.address]),
            _ => unreachable!("line and extended steps are handled by the plan executor"),
        };
        let exchange = self
            .dali_session_exchange(
                tag,
                generation,
                pci,
                unit,
                target.line,
                DaliCalMode::Auto,
                operation,
                &payload,
                step_name,
            )
            .await?;

        if matches!(
            step,
            ReadOnlyExtractStep::DiscoverGtinSerialEcg
                | ReadOnlyExtractStep::GetGtinEcg
                | ReadOnlyExtractStep::GetSerialEcg
        ) && (exchange.nak || exchange.status != 0)
        {
            let kind = match step {
                ReadOnlyExtractStep::DiscoverGtinSerialEcg => "discover gtin serial",
                ReadOnlyExtractStep::GetGtinEcg => "gtin",
                ReadOnlyExtractStep::GetSerialEcg => "serial",
                _ => unreachable!(),
            };
            response_lines.push(format!(
                "300-[WARN] {kind} not supported: for ecg: {}",
                target.address
            ));
            return Ok(());
        }

        match step {
            ReadOnlyExtractStep::DiscoverStatusInfoEcg
            | ReadOnlyExtractStep::DiscoverGtinSerialEcg => {
                typed_success_payload(tag, step_name, target.address, &exchange, None)?;
            }
            ReadOnlyExtractStep::GetKnownTypeInfoEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(9))?;
                apply_known_type_info(model, target, bytes).map_err(|error| {
                    err(tag, 501, &format!("501 gateway model mismatch: {error}"))
                })?;
            }
            ReadOnlyExtractStep::GetCommonParamsEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(9))?;
                set_target_property(
                    model,
                    target,
                    "commonParams102",
                    json!({
                        "groupMembershipBitmask16": little_endian_u16(&bytes[1..3]),
                        "sceneMembershipBitmask16": little_endian_u16(&bytes[3..5]),
                        "minimumLevel": bytes[5],
                        "maximumLevel": bytes[6],
                        "recoveryLevel": bytes[7],
                        "failureLevel": bytes[8],
                    }),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetCommonReadOnlyParamsEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(4))?;
                set_target_property(
                    model,
                    target,
                    "commonReadOnlyParams102",
                    json!({
                        "daliVersionSupported": bytes[1],
                        "physicalMinimumLevel": bytes[2],
                        "statusBitmask8": bytes[3],
                    }),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetSceneValuesEcg => {
                let low =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(9))?;
                let high_exchange = self
                    .dali_session_exchange(
                        tag,
                        generation,
                        pci,
                        unit,
                        target.line,
                        DaliCalMode::Auto,
                        20,
                        &[target.address],
                        step_name,
                    )
                    .await?;
                let high =
                    typed_success_payload(tag, step_name, target.address, &high_exchange, Some(9))?;
                let mut levels = low[1..]
                    .iter()
                    .chain(&high[1..])
                    .map(|value| json!({"level": value}))
                    .collect::<Vec<_>>();
                let scene_mask = levels
                    .iter()
                    .enumerate()
                    .fold(0u16, |mask, (index, value)| {
                        if value.get("level").and_then(Value::as_u64) != Some(255) {
                            mask | (1 << index)
                        } else {
                            mask
                        }
                    });
                set_target_property(
                    model,
                    target,
                    "scene",
                    Value::Array(std::mem::take(&mut levels)),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
                set_nested_target_property(
                    model,
                    target,
                    "commonParams102",
                    "sceneMembershipBitmask16",
                    json!(scene_mask),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetGtinEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(7))?;
                set_nested_target_property(
                    model,
                    target,
                    "gtinSerial",
                    "gtin",
                    json!(little_endian_u64(&bytes[1..])),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetSerialEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(9))?;
                set_nested_target_property(
                    model,
                    target,
                    "gtinSerial",
                    "serial",
                    json!(little_endian_u64(&bytes[1..])),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetLedParamsEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(3))?;
                let curve = match bytes[1] {
                    0 => "LOGARITHMIC",
                    1 => "LINEAR",
                    value => {
                        return Err(err(
                            tag,
                            504,
                            &format!(
                                "504 dali sync error: invalid LED dimming curve {value} for ECG {}",
                                target.address
                            ),
                        ))
                    }
                };
                set_target_property(
                    model,
                    target,
                    "ledParams207",
                    json!({"dimmCurve": curve, "statusByte": bytes[2]}),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetEmergencyParamsEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(8))?;
                set_target_property(
                    model,
                    target,
                    "emergencyParams202",
                    json!({
                        "emergencyLevel": bytes[1],
                        "emergencyMin": bytes[4],
                        "emergencyMax": bytes[5],
                        "prolongTime": bytes[2],
                        "timeout": bytes[3],
                        "ratedDuration": bytes[6],
                        "featuresByte": bytes[7],
                        "switched": bytes[7] & (1 << 2) != 0,
                        "maintained": bytes[7] & (1 << 1) != 0,
                    }),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            ReadOnlyExtractStep::GetEmergencyStatusEcg => {
                let bytes =
                    typed_success_payload(tag, step_name, target.address, &exchange, Some(8))?;
                set_target_property(
                    model,
                    target,
                    "emergencyStatus202",
                    json!({
                        "emergencyMode": bytes[1],
                        "emergencyStatus": bytes[2],
                        "failureStatus": bytes[3],
                        "batteryCharge": bytes[4],
                        "durationTestResult": bytes[5],
                        "lampEmergencyTime": bytes[6],
                        "lampTotalTime": bytes[7],
                    }),
                )
                .map_err(|error| err(tag, 501, &format!("501 gateway model mismatch: {error}")))?;
            }
            _ => unreachable!("line and extended steps are handled by the plan executor"),
        }
        Ok(())
    }

    async fn dali_session_extract_typed(
        &self,
        tag: &str,
        session_name: &str,
        target: &str,
        lines: (bool, bool),
        range: Option<&[u8]>,
        extract_type: &str,
    ) -> Response {
        let (original_model, original_source_cdg, targets) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(session_name) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {session_name}"),
                );
            };
            let targets = match typed_session_targets(session, lines, range) {
                Ok(targets) => targets,
                Err(error) => {
                    return err(tag, 501, &format!("501 gateway model mismatch: {error}"))
                }
            };
            (session.model.clone(), session.source_cdg.clone(), targets)
        };
        let (unit, _) = match self.dali_gateway(tag, target).await {
            Ok(value) => value,
            Err(response) => return response,
        };
        let (generation, pci) = self.current_pci_epoch().await;
        let mut updates = BTreeMap::<(usize, usize, u8), TypedSessionUpdate>::new();
        let mut response_lines = vec!["120-start extraction".to_string()];

        match extract_type {
            "REFRESH_STATUS_INFO" => {
                response_lines
                    .push("120-progress: 1/3, plan: DISCOVER_STATUS_INFO_ECG".to_string());
                if targets.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in &targets {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            26,
                            &[target.address],
                            "DISCOVER_STATUS_INFO_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    if let Err(response) = typed_success_payload(
                        tag,
                        "DISCOVER_STATUS_INFO_ECG",
                        target.address,
                        &exchange,
                        None,
                    ) {
                        return response;
                    }
                }

                response_lines
                    .push("120-progress: 2/3, plan: GET_COMMON_READ_ONLY_PARAMS_ECG".to_string());
                if targets.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in &targets {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            18,
                            &[target.address],
                            "GET_COMMON_READ_ONLY_PARAMS_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    let payload = match typed_success_payload(
                        tag,
                        "GET_COMMON_READ_ONLY_PARAMS_ECG",
                        target.address,
                        &exchange,
                        Some(4),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .common_read_only = Some(json!({
                        "daliVersionSupported": payload[1],
                        "physicalMinimumLevel": payload[2],
                        "statusBitmask8": payload[3],
                    }));
                }

                response_lines
                    .push("120-progress: 3/3, plan: GET_EMERGENCY_STATUS_ECG".to_string());
                let emergency = targets
                    .iter()
                    .filter(|target| target.emergency)
                    .collect::<Vec<_>>();
                if emergency.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in emergency {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            24,
                            &[target.address],
                            "GET_EMERGENCY_STATUS_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    let payload = match typed_success_payload(
                        tag,
                        "GET_EMERGENCY_STATUS_ECG",
                        target.address,
                        &exchange,
                        Some(8),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .emergency_status = Some(json!({
                        "emergencyMode": payload[1],
                        "emergencyStatus": payload[2],
                        "failureStatus": payload[3],
                        "batteryCharge": payload[4],
                        "durationTestResult": payload[5],
                        "lampEmergencyTime": payload[6],
                        "lampTotalTime": payload[7],
                    }));
                }
            }
            "RETRIEVE_RECONCILE" => {
                response_lines.push(
                    "120-progress: 1/6, plan: COND_UNREAD_GET_COMMON_READ_ONLY_PARAMS_ECG"
                        .to_string(),
                );
                let common = targets
                    .iter()
                    .filter(|target| !target.has_common_read_only)
                    .collect::<Vec<_>>();
                if common.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in common {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            18,
                            &[target.address],
                            "COND_UNREAD_GET_COMMON_READ_ONLY_PARAMS_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    let payload = match typed_success_payload(
                        tag,
                        "COND_UNREAD_GET_COMMON_READ_ONLY_PARAMS_ECG",
                        target.address,
                        &exchange,
                        Some(4),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .common_read_only = Some(json!({
                        "daliVersionSupported": payload[1],
                        "physicalMinimumLevel": payload[2],
                        "statusBitmask8": payload[3],
                    }));
                }

                response_lines.push(
                    "120-progress: 2/6, plan: COND_UNREAD_GET_EMERGENCY_PARAMS_ECG".to_string(),
                );
                let emergency = targets
                    .iter()
                    .filter(|target| target.emergency && !target.has_emergency_params)
                    .collect::<Vec<_>>();
                if emergency.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in emergency {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            23,
                            &[target.address],
                            "COND_UNREAD_GET_EMERGENCY_PARAMS_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    let payload = match typed_success_payload(
                        tag,
                        "COND_UNREAD_GET_EMERGENCY_PARAMS_ECG",
                        target.address,
                        &exchange,
                        Some(8),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .emergency_params = Some(json!({
                        "emergencyLevel": payload[1],
                        "emergencyMin": payload[4],
                        "emergencyMax": payload[5],
                        "prolongTime": payload[2],
                        "timeout": payload[3],
                        "ratedDuration": payload[6],
                        "featuresByte": payload[7],
                        "switched": payload[7] & (1 << 2) != 0,
                        "maintained": payload[7] & (1 << 1) != 0,
                    }));
                }

                response_lines
                    .push("120-progress: 3/6, plan: COND_UNREAD_GET_LED_PARAMS_ECG".to_string());
                let led = targets
                    .iter()
                    .filter(|target| target.led && !target.has_led_params)
                    .collect::<Vec<_>>();
                if led.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in led {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            25,
                            &[target.address],
                            "COND_UNREAD_GET_LED_PARAMS_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    let payload = match typed_success_payload(
                        tag,
                        "COND_UNREAD_GET_LED_PARAMS_ECG",
                        target.address,
                        &exchange,
                        Some(3),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    let curve = match payload[1] {
                        0 => "LOGARITHMIC",
                        1 => "LINEAR",
                        value => {
                            return err(
                                tag,
                                504,
                                &format!(
                                "504 dali sync error: invalid LED dimming curve {value} for ECG {}",
                                target.address
                            ),
                            )
                        }
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .led_params = Some(json!({
                        "dimmCurve": curve,
                        "statusByte": payload[2],
                    }));
                }

                response_lines.push(
                    "120-progress: 4/6, plan: COND_UNREAD_DISCOVER_GTIN_SERIAL_ECG".to_string(),
                );
                let discover = targets
                    .iter()
                    .filter(|target| !target.has_gtin_serial)
                    .collect::<Vec<_>>();
                if discover.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in discover {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            27,
                            &[target.address],
                            "COND_UNREAD_DISCOVER_GTIN_SERIAL_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    if exchange.nak || exchange.status != 0 {
                        response_lines.push(format!(
                            "300-[WARN] discover gtin serial not supported: for ecg: {}",
                            target.address
                        ));
                    }
                }

                response_lines
                    .push("120-progress: 5/6, plan: COND_UNREAD_GET_GTIN_ECG".to_string());
                let gtin = targets
                    .iter()
                    .filter(|target| target.gtin.unwrap_or(0) == 0)
                    .collect::<Vec<_>>();
                if gtin.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in gtin {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            21,
                            &[target.address],
                            "COND_UNREAD_GET_GTIN_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    if exchange.nak || exchange.status != 0 {
                        response_lines.push(format!(
                            "300-[WARN] gtin not supported: for ecg: {}",
                            target.address
                        ));
                        continue;
                    }
                    let payload = match typed_success_payload(
                        tag,
                        "COND_UNREAD_GET_GTIN_ECG",
                        target.address,
                        &exchange,
                        Some(7),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .gtin = Some(little_endian_u64(&payload[1..]));
                }

                response_lines
                    .push("120-progress: 6/6, plan: COND_UNREAD_GET_SERIAL_ECG".to_string());
                let serial = targets
                    .iter()
                    .filter(|target| target.serial.unwrap_or(0) == 0)
                    .collect::<Vec<_>>();
                if serial.is_empty() {
                    response_lines.push("300-[WARN] no commands sent - no known ecgs".to_string());
                }
                for target in serial {
                    let exchange = match self
                        .dali_session_typed_exchange(
                            tag,
                            generation,
                            &pci,
                            unit,
                            target.line,
                            22,
                            &[target.address],
                            "COND_UNREAD_GET_SERIAL_ECG",
                        )
                        .await
                    {
                        Ok(exchange) => exchange,
                        Err(response) => return response,
                    };
                    if exchange.nak || exchange.status != 0 {
                        response_lines.push(format!(
                            "300-[WARN] serial not supported: for ecg: {}",
                            target.address
                        ));
                        continue;
                    }
                    let payload = match typed_success_payload(
                        tag,
                        "COND_UNREAD_GET_SERIAL_ECG",
                        target.address,
                        &exchange,
                        Some(9),
                    ) {
                        Ok(payload) => payload,
                        Err(response) => return response,
                    };
                    updates
                        .entry((target.line_index, target.ecg_index, target.address))
                        .or_default()
                        .serial = Some(little_endian_u64(&payload[1..]));
                }
            }
            _ => unreachable!("caller admits only implemented typed extraction plans"),
        }

        let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                503,
                "503 network error: PCI connection changed during typed extraction",
            );
        };
        let mut state = self.dali_state.lock().await;
        let Some(session) = state.sessions.get_mut(session_name) else {
            return err(tag, 501, "501 session ended during extraction");
        };
        if session.model != original_model || session.source_cdg != original_source_cdg {
            return err(tag, 501, "501 session changed during extraction");
        }
        let mut model = session.model.clone();
        if let Err(error) = apply_typed_session_updates(&mut model, updates) {
            return err(tag, 501, &format!("501 gateway model mismatch: {error}"));
        }
        session.model = model;
        session.source_cdg = Some(target.to_string());
        ok(tag, response_lines, "200 OK.")
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_session_typed_exchange(
        &self,
        tag: &str,
        generation: u64,
        pci: &Arc<PciClient>,
        unit: u8,
        line: DaliLine,
        operation: u8,
        payload: &[u8],
        step: &str,
    ) -> Result<cbus_transport::pci::DaliExchange, Response> {
        self.dali_session_exchange(
            tag,
            generation,
            pci,
            unit,
            line,
            DaliCalMode::Auto,
            operation,
            payload,
            step,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn dali_session_exchange(
        &self,
        tag: &str,
        generation: u64,
        pci: &Arc<PciClient>,
        unit: u8,
        line: DaliLine,
        mode: DaliCalMode,
        operation: u8,
        payload: &[u8],
        step: &str,
    ) -> Result<cbus_transport::pci::DaliExchange, Response> {
        let budget = (mode == DaliCalMode::Auto).then_some(DaliPollBudget::NATIVE_DEFAULT);
        self.dali_session_exchange_with(
            tag, generation, pci, unit, line, budget, mode, operation, payload, step,
        )
        .await
    }

    /// One session exchange. AUTO runs `budget` (native default unless a
    /// step overrides it); other modes send exactly one request.
    #[allow(clippy::too_many_arguments)]
    async fn dali_session_exchange_with(
        &self,
        tag: &str,
        generation: u64,
        pci: &Arc<PciClient>,
        unit: u8,
        line: DaliLine,
        budget: Option<DaliPollBudget>,
        mode: DaliCalMode,
        operation: u8,
        payload: &[u8],
        step: &str,
    ) -> Result<cbus_transport::pci::DaliExchange, Response> {
        let operation = line.operation(0xda, operation);
        let result = match budget {
            Some(mut budget) => {
                if let Some(interval) = self.dali_state.lock().await.poll_interval_override {
                    budget.interval = interval;
                }
                pci.dali_auto_command(unit, budget, 0xda, operation, payload)
                    .await
            }
            None => pci.dali_command(unit, mode, 0xda, operation, payload).await,
        };
        let result = result.map_err(|error| {
            err(
                tag,
                503,
                &format!("503 network error during {step}: {error}"),
            )
        })?;
        let exchange = result.exchanges.last().cloned().ok_or_else(|| {
            err(
                tag,
                504,
                &format!("504 dali sync error: {step} returned no exchange"),
            )
        })?;
        let Some(_guard) = self.pci_commit_guard(generation, pci).await else {
            return Err(err(
                tag,
                503,
                &format!("503 network error: PCI connection changed during {step}"),
            ));
        };
        Ok(exchange)
    }
}

/// Fixed inputs of one conditional extraction.
struct ConditionalContext<'a> {
    tag: &'a str,
    generation: u64,
    pci: &'a Arc<PciClient>,
    unit: u8,
    lines: (bool, bool),
    range: Option<&'a [u8]>,
    session_name: &'a str,
    project: &'a str,
    extract_type: &'a str,
}

/// Mutable progress of one conditional extraction.
struct ConditionalRun {
    lines: Vec<String>,
    staged_ext: Vec<(u32, Vec<u8>)>,
    /// Created immediately before the first ADDRESS_UNKNOWN; its presence
    /// means the bus may have changed.
    journal: Option<ActiveDaliJournal>,
    /// An ADDRESS_UNKNOWN exchange ended without a definite final status.
    address_unknown_uncertain: bool,
}

/// `DaliEcg.c()`: clear the seven status flags of each selected ECG.
fn clear_ecg_status_flags(
    model: &mut Value,
    line_index: usize,
    range: Option<&[u8]>,
) -> Result<(), &'static str> {
    let selected = range.map(|range| range.iter().copied().collect::<HashSet<_>>());
    let ecgs = line_object_mut(model, line_index)?
        .get_mut("daliEcgs")
        .and_then(Value::as_array_mut)
        .ok_or("selected DALI line has no ECG model")?;
    for (address, ecg) in ecgs.iter_mut().enumerate() {
        if selected
            .as_ref()
            .is_some_and(|selected| !u8::try_from(address).is_ok_and(|a| selected.contains(&a)))
        {
            continue;
        }
        let ecg = ecg
            .as_object_mut()
            .ok_or("session ECG changed during extraction")?;
        for flag in ECG_STATUS_FLAGS {
            ecg.remove(flag);
        }
    }
    Ok(())
}

/// `ka.m()`: some ECG on a selected line is address-known but has
/// `isFullyKnown` exactly false. The address filter does not apply.
fn conditional_discovery_needed(model: &Value, lines: (bool, bool)) -> bool {
    selected_dali_lines(lines)
        .into_iter()
        .any(|(line_index, _)| {
            model
                .pointer(&format!("/cdg/daliLines/{line_index}/daliEcgs"))
                .and_then(Value::as_array)
                .is_some_and(|ecgs| {
                    ecgs.iter().any(|ecg| {
                        ecg.get("isFullyKnown") == Some(&Value::Bool(false))
                            && ecg.get("isAddressKnown") == Some(&Value::Bool(true))
                    })
                })
        })
}

fn target_flag(model: &Value, target: &TypedSessionTarget, flag: &str) -> bool {
    model
        .pointer(&format!(
            "/cdg/daliLines/{}/daliEcgs/{}/{flag}",
            target.line_index, target.ecg_index
        ))
        .and_then(Value::as_bool)
        == Some(true)
}

fn json_u8(object: &Map<String, Value>, field: &str) -> Option<u8> {
    object
        .get(field)
        .and_then(Value::as_u64)
        .and_then(|value| u8::try_from(value).ok())
}

/// Build the complete native `DALI_ONLY` write sequence (`gq`/`go`) from one
/// session snapshot. Steps visit the selected lines A then B, then each
/// line's ECGs in model order, and write only ECGs that are known, not
/// missing, not conflicting and in the optional address set. An `Err` is the
/// native 501 warning text for the first ECG whose model cannot be encoded.
fn typed_deploy_plan(
    model: &Value,
    lines: (bool, bool),
    range: Option<&[u8]>,
) -> Result<Vec<TypedDeployStep>, String> {
    let selected = range.map(|range| range.iter().copied().collect::<HashSet<_>>());
    let mut eligible = Vec::new();
    for (line_index, line) in selected_dali_lines(lines) {
        let Some(ecgs) = model
            .pointer(&format!("/cdg/daliLines/{line_index}/daliEcgs"))
            .and_then(Value::as_array)
        else {
            continue;
        };
        for (index, ecg) in ecgs.iter().enumerate() {
            let Some(ecg) = ecg.as_object() else {
                continue;
            };
            let flag = |name: &str| ecg.get(name).and_then(Value::as_bool) == Some(true);
            if !flag("isKnown") || flag("isMissing") || flag("isConflicting") {
                continue;
            }
            let address = ecg
                .get("shortAddress")
                .and_then(Value::as_u64)
                .unwrap_or(index as u64);
            let Some(address) = u8::try_from(address).ok().filter(|address| *address < 64) else {
                return Err(format!("invalid short address for ecg: {address}"));
            };
            if selected
                .as_ref()
                .is_some_and(|selected| !selected.contains(&address))
            {
                continue;
            }
            eligible.push((line, address, ecg));
        }
    }
    let present =
        |ecg: &Map<String, Value>, field: &str| ecg.get(field).and_then(Value::as_object).cloned();
    let write = |step, operation, line, address, payload: Vec<u8>| TypedDeployWrite {
        step,
        operation,
        line,
        address,
        payload,
    };

    let mut common = Vec::new();
    for (line, address, ecg) in &eligible {
        let Some(params) = present(ecg, "commonParams102") else {
            return Err(format!("common parameters not set for ecg: {address}"));
        };
        let groups = params
            .get("groupMembershipBitmask16")
            .and_then(Value::as_u64)
            .and_then(|value| u16::try_from(value).ok());
        let levels = [
            "minimumLevel",
            "maximumLevel",
            "recoveryLevel",
            "failureLevel",
        ]
        .map(|field| json_u8(&params, field));
        let (Some(groups), [Some(min), Some(max), Some(recovery), Some(failure)]) =
            (groups, levels)
        else {
            return Err(format!("common parameters invalid for ecg: {address}"));
        };
        let [low, high] = groups.to_le_bytes();
        common.push(write(
            "SET_COMMON_PARAMS_ECG",
            32,
            *line,
            *address,
            vec![*address, low, high, min, max, recovery, failure],
        ));
    }

    let mut scene_phases = vec![Vec::new(), Vec::new()];
    for (phase, operation) in [(0usize, 34u8), (1, 35)] {
        for (line, address, ecg) in &eligible {
            let params = present(ecg, "commonParams102");
            let membership = params
                .as_ref()
                .and_then(|params| params.get("sceneMembershipBitmask16"))
                .and_then(Value::as_u64)
                .unwrap_or(0);
            let scenes = ecg.get("scene").and_then(Value::as_array);
            let mut payload = vec![*address];
            for offset in 0..8 {
                let scene = phase * 8 + offset;
                let stored = scenes
                    .and_then(|scenes| scenes.get(scene))
                    .filter(|scene| !scene.is_null());
                let byte = match stored {
                    Some(stored) if params.is_some() && membership & (1 << scene) != 0 => stored
                        .get("level")
                        .and_then(Value::as_u64)
                        .and_then(|level| u8::try_from(level).ok())
                        .ok_or_else(|| format!("scene parameters invalid for ecg: {address}"))?,
                    _ => 0xff,
                };
                payload.push(byte);
            }
            scene_phases[phase].push(write(
                "SET_SCENE_VALUES_ECG",
                operation,
                *line,
                *address,
                payload,
            ));
        }
    }

    let mut led = Vec::new();
    for (line, address, ecg) in eligible
        .iter()
        .filter(|(_, _, ecg)| ecg_has_device_type(ecg, "LED"))
    {
        let curve = present(ecg, "ledParams207")
            .and_then(|params| params.get("dimmCurve").cloned())
            .filter(|curve| !curve.is_null())
            .ok_or_else(|| format!("led parameters not set for ecg: {address}"))?;
        let curve = match curve.as_str() {
            Some("LOGARITHMIC") => 0,
            Some("LINEAR") => 1,
            _ => return Err(format!("led parameters invalid for ecg: {address}")),
        };
        led.push(write(
            "SET_LED_PARAMS_ECG",
            40,
            *line,
            *address,
            vec![*address, curve],
        ));
    }

    let mut emergency = Vec::new();
    for (line, address, ecg) in eligible
        .iter()
        .filter(|(_, _, ecg)| ecg_has_device_type(ecg, "EMERGENCY"))
    {
        // `getEmergencySubType()` needs both structures.
        let (Some(params), Some(_)) = (
            present(ecg, "emergencyParams202"),
            present(ecg, "commonReadOnlyParams102"),
        ) else {
            return Err(format!("emergency parameters not set for ecg: {address}"));
        };
        let (Some(level), Some(prolong), Some(timeout)) = (
            json_u8(&params, "emergencyLevel"),
            json_u8(&params, "prolongTime"),
            json_u8(&params, "timeout"),
        ) else {
            return Err(format!("emergency parameters invalid for ecg: {address}"));
        };
        emergency.push(write(
            "SET_EMERGENCY_PARAMS_ECG",
            38,
            *line,
            *address,
            vec![*address, level, prolong, timeout],
        ));
    }

    Ok(vec![
        TypedDeployStep {
            name: TYPED_DEPLOY_STEPS[0],
            phases: vec![common],
        },
        TypedDeployStep {
            name: TYPED_DEPLOY_STEPS[1],
            phases: scene_phases,
        },
        TypedDeployStep {
            name: TYPED_DEPLOY_STEPS[2],
            phases: vec![led],
        },
        TypedDeployStep {
            name: TYPED_DEPLOY_STEPS[3],
            phases: vec![emergency],
        },
    ])
}

fn selected_dali_lines(lines: (bool, bool)) -> Vec<(usize, DaliLine)> {
    let mut selected = Vec::with_capacity(2);
    if lines.0 {
        selected.push((0, DaliLine::A));
    }
    if lines.1 {
        selected.push((1, DaliLine::B));
    }
    selected
}

fn ensure_read_only_extract_model(
    model: &mut Value,
    lines: (bool, bool),
) -> Result<(), &'static str> {
    let dali_lines = model
        .pointer_mut("/cdg/daliLines")
        .and_then(Value::as_array_mut)
        .ok_or("session has no DALI line model")?;
    if dali_lines.len() < 2 {
        return Err("session has fewer than two DALI lines");
    }
    for (line_index, _) in selected_dali_lines(lines) {
        let line = dali_lines
            .get_mut(line_index)
            .and_then(Value::as_object_mut)
            .ok_or("selected DALI line is not an object")?;
        let ecgs = line
            .get_mut("daliEcgs")
            .and_then(Value::as_array_mut)
            .ok_or("selected DALI line has no ECG model")?;
        if ecgs.len() > 64 {
            return Err("selected DALI line contains more than 64 ECGs");
        }
        ecgs.resize(64, Value::Null);
        for (address, ecg) in ecgs.iter_mut().enumerate() {
            if ecg.is_null() {
                *ecg = json!({"shortAddress": address});
                continue;
            }
            let ecg = ecg.as_object_mut().ok_or("session ECG is not an object")?;
            let actual = ecg
                .get("shortAddress")
                .and_then(Value::as_u64)
                .unwrap_or(address as u64);
            if actual != address as u64 {
                return Err("session ECG address does not match its native model slot");
            }
            ecg.insert("shortAddress".to_string(), json!(address));
        }
    }
    Ok(())
}

fn line_success_payload<'a>(
    tag: &str,
    step: &str,
    exchange: &'a cbus_transport::pci::DaliExchange,
    expected_length: usize,
) -> Result<&'a [u8], Response> {
    if exchange.nak || exchange.status != 0 {
        return Err(err(
            tag,
            502,
            &format!(
                "502 reply status error during {step}: status {}",
                exchange.status
            ),
        ));
    }
    if exchange.data.len() != expected_length {
        return Err(err(
            tag,
            504,
            &format!(
                "504 dali sync error: {step} has invalid payload {}",
                hex::encode_upper(&exchange.data)
            ),
        ));
    }
    Ok(&exchange.data)
}

fn line_success(
    tag: &str,
    step: &str,
    exchange: &cbus_transport::pci::DaliExchange,
) -> Result<(), Response> {
    if exchange.nak || exchange.status != 0 {
        return Err(err(
            tag,
            502,
            &format!(
                "502 reply status error during {step}: status {}",
                exchange.status
            ),
        ));
    }
    Ok(())
}

fn line_object_mut(
    model: &mut Value,
    line_index: usize,
) -> Result<&mut Map<String, Value>, &'static str> {
    model
        .pointer_mut(&format!("/cdg/daliLines/{line_index}"))
        .and_then(Value::as_object_mut)
        .ok_or("selected DALI line changed during extraction")
}

fn set_line_property(
    model: &mut Value,
    line_index: usize,
    name: &str,
    value: Value,
) -> Result<(), &'static str> {
    line_object_mut(model, line_index)?.insert(name.to_string(), value);
    Ok(())
}

fn apply_line_mask(
    model: &mut Value,
    line_index: usize,
    range: Option<&[u8]>,
    field: &str,
    mask: &[u8],
    also_known: bool,
) -> Result<(), &'static str> {
    if mask.len() != 8 {
        return Err("DALI address mask is not 64 bits");
    }
    let selected = range.map(|range| range.iter().copied().collect::<HashSet<_>>());
    let ecgs = line_object_mut(model, line_index)?
        .get_mut("daliEcgs")
        .and_then(Value::as_array_mut)
        .ok_or("selected DALI line has no ECG model")?;
    for address in 0u8..64 {
        if selected
            .as_ref()
            .is_some_and(|selected| !selected.contains(&address))
        {
            continue;
        }
        let value = mask[usize::from(address / 8)] & (1 << (address % 8)) != 0;
        let ecg = ecgs
            .get_mut(usize::from(address))
            .and_then(Value::as_object_mut)
            .ok_or("session ECG changed during extraction")?;
        if field == "isBroken" {
            if let Some(previous) = ecg.get("isBroken").cloned() {
                ecg.insert("isPreviouslyBroken".to_string(), previous);
            } else {
                ecg.remove("isPreviouslyBroken");
            }
        }
        ecg.insert(field.to_string(), json!(value));
        if also_known {
            ecg.insert("isKnown".to_string(), json!(value));
        }
    }
    Ok(())
}

fn target_object_mut<'a>(
    model: &'a mut Value,
    target: &TypedSessionTarget,
) -> Result<&'a mut Map<String, Value>, &'static str> {
    let ecg = model
        .pointer_mut(&format!(
            "/cdg/daliLines/{}/daliEcgs/{}",
            target.line_index, target.ecg_index
        ))
        .and_then(Value::as_object_mut)
        .ok_or("session ECG changed during extraction")?;
    if ecg
        .get("shortAddress")
        .and_then(Value::as_u64)
        .unwrap_or(target.ecg_index as u64)
        != u64::from(target.address)
    {
        return Err("session ECG address changed during extraction");
    }
    Ok(ecg)
}

fn set_target_property(
    model: &mut Value,
    target: &TypedSessionTarget,
    name: &str,
    value: Value,
) -> Result<(), &'static str> {
    target_object_mut(model, target)?.insert(name.to_string(), value);
    Ok(())
}

fn set_nested_target_property(
    model: &mut Value,
    target: &TypedSessionTarget,
    parent: &str,
    name: &str,
    value: Value,
) -> Result<(), &'static str> {
    let ecg = target_object_mut(model, target)?;
    let parent = ecg
        .entry(parent.to_string())
        .or_insert_with(|| Value::Object(Map::new()))
        .as_object_mut()
        .ok_or("session ECG nested model changed during extraction")?;
    parent.insert(name.to_string(), value);
    Ok(())
}

fn apply_known_type_info(
    model: &mut Value,
    target: &TypedSessionTarget,
    bytes: &[u8],
) -> Result<(), &'static str> {
    if bytes.len() != 9 || bytes[0] != target.address {
        return Err("known-type response has invalid payload");
    }
    let mut types = Vec::new();
    let mut unmatched = Vec::new();
    for value in bytes[1..].iter().copied() {
        let name = match value {
            0 => Some("LAMP"),
            1 => Some("EMERGENCY"),
            6 => Some("LED"),
            8 => Some("COLOUR_CONTROL"),
            0xff => None,
            value => {
                if !unmatched.contains(&value) {
                    unmatched.push(value);
                }
                None
            }
        };
        if let Some(name) = name {
            if !types.contains(&name) {
                types.push(name);
            }
        }
    }
    let emergency = types.contains(&"EMERGENCY");
    let led = types.contains(&"LED");
    let colour = types.contains(&"COLOUR_CONTROL");
    let ecg = target_object_mut(model, target)?;
    ecg.insert("deviceTypes".to_string(), json!({"deviceTypes": types}));
    ecg.insert(
        "unmatchedDeviceTypes".to_string(),
        json!({"unmatchedDeviceTypes": unmatched}),
    );
    if emergency {
        ecg.insert("emergencyParams202".to_string(), Value::Null);
        ecg.insert("emergencyStatus202".to_string(), Value::Null);
    }
    if led {
        ecg.insert("ledParams207".to_string(), Value::Null);
    }
    if colour {
        for field in [
            "colourType209",
            "colourTemperature209",
            "colourPower209",
            "colourFail209",
        ] {
            ecg.insert(field.to_string(), Value::Null);
        }
    }
    Ok(())
}

fn little_endian_u16(bytes: &[u8]) -> u16 {
    u16::from(bytes[0]) | (u16::from(bytes[1]) << 8)
}

fn typed_session_targets(
    session: &DaliSession,
    lines: (bool, bool),
    range: Option<&[u8]>,
) -> Result<Vec<TypedSessionTarget>, &'static str> {
    typed_model_targets(&session.model, lines, range)
}

fn typed_model_targets(
    model: &Value,
    lines: (bool, bool),
    range: Option<&[u8]>,
) -> Result<Vec<TypedSessionTarget>, &'static str> {
    let dali_lines = model
        .pointer("/cdg/daliLines")
        .and_then(Value::as_array)
        .ok_or("session has no DALI line model")?;
    let range = range.map(|values| values.iter().copied().collect::<HashSet<_>>());
    let mut seen = HashSet::new();
    let mut targets = Vec::new();
    for line_index in 0..2 {
        if (line_index == 0 && !lines.0) || (line_index == 1 && !lines.1) {
            continue;
        }
        let Some(ecgs) = dali_lines
            .get(line_index)
            .and_then(|line| line.get("daliEcgs"))
            .and_then(Value::as_array)
        else {
            return Err("selected DALI line has no ECG model");
        };
        for (ecg_index, ecg) in ecgs.iter().enumerate() {
            let Some(ecg) = ecg.as_object() else {
                continue;
            };
            if ecg.get("isKnown").and_then(Value::as_bool) != Some(true) {
                continue;
            }
            let address = ecg
                .get("shortAddress")
                .and_then(Value::as_u64)
                .unwrap_or(ecg_index as u64);
            let Ok(address) = u8::try_from(address) else {
                return Err("session ECG address is outside 0..63");
            };
            if address > 63 {
                return Err("session ECG address is outside 0..63");
            }
            if range
                .as_ref()
                .is_some_and(|selected| !selected.contains(&address))
            {
                continue;
            }
            if !seen.insert((line_index, address)) {
                return Err("session contains duplicate ECG addresses on one line");
            }
            let gtin_serial = ecg.get("gtinSerial").filter(|value| !value.is_null());
            targets.push(TypedSessionTarget {
                line_index,
                ecg_index,
                line: if line_index == 0 {
                    DaliLine::A
                } else {
                    DaliLine::B
                },
                address,
                emergency: ecg_has_device_type(ecg, "EMERGENCY"),
                led: ecg_has_device_type(ecg, "LED"),
                has_common_read_only: ecg
                    .get("commonReadOnlyParams102")
                    .is_some_and(|value| !value.is_null()),
                has_emergency_params: ecg
                    .get("emergencyParams202")
                    .is_some_and(|value| !value.is_null()),
                has_led_params: ecg
                    .get("ledParams207")
                    .is_some_and(|value| !value.is_null()),
                has_gtin_serial: gtin_serial.is_some(),
                gtin: gtin_serial
                    .and_then(|value| value.get("gtin"))
                    .and_then(Value::as_u64),
                serial: gtin_serial
                    .and_then(|value| value.get("serial"))
                    .and_then(Value::as_u64),
            });
        }
    }
    Ok(targets)
}

fn ecg_has_device_type(ecg: &Map<String, Value>, sought: &str) -> bool {
    let Some(types) = ecg.get("deviceTypes") else {
        return false;
    };
    let types = types.get("deviceTypes").unwrap_or(types);
    types.as_array().is_some_and(|types| {
        types
            .iter()
            .filter_map(Value::as_str)
            .any(|value| value.eq_ignore_ascii_case(sought))
    })
}

fn typed_success_payload<'a>(
    tag: &str,
    step: &str,
    address: u8,
    exchange: &'a cbus_transport::pci::DaliExchange,
    expected_length: Option<usize>,
) -> Result<&'a [u8], Response> {
    if exchange.nak || exchange.status != 0 {
        return Err(err(
            tag,
            502,
            &format!(
                "502 reply status error during {step}: status {}",
                exchange.status
            ),
        ));
    }
    if let Some(expected_length) = expected_length {
        if exchange.data.len() != expected_length || exchange.data.first() != Some(&address) {
            return Err(err(
                tag,
                504,
                &format!(
                    "504 dali sync error: {step} response for ECG {address} has invalid payload {}",
                    hex::encode_upper(&exchange.data)
                ),
            ));
        }
    }
    Ok(&exchange.data)
}

fn little_endian_u64(bytes: &[u8]) -> u64 {
    bytes
        .iter()
        .copied()
        .enumerate()
        .fold(0u64, |value, (index, byte)| {
            value | (u64::from(byte) << (index * 8))
        })
}

fn apply_typed_session_updates(
    model: &mut Value,
    updates: BTreeMap<(usize, usize, u8), TypedSessionUpdate>,
) -> Result<(), &'static str> {
    for ((line_index, ecg_index, address), update) in updates {
        let ecg = model
            .pointer_mut(&format!("/cdg/daliLines/{line_index}/daliEcgs/{ecg_index}"))
            .and_then(Value::as_object_mut)
            .ok_or("session ECG changed during extraction")?;
        if ecg
            .get("shortAddress")
            .and_then(Value::as_u64)
            .unwrap_or(ecg_index as u64)
            != u64::from(address)
        {
            return Err("session ECG address changed during extraction");
        }
        if let Some(value) = update.common_read_only {
            ecg.insert("commonReadOnlyParams102".to_string(), value);
        }
        if let Some(value) = update.emergency_params {
            ecg.insert("emergencyParams202".to_string(), value);
        }
        if let Some(value) = update.emergency_status {
            ecg.insert("emergencyStatus202".to_string(), value);
        }
        if let Some(value) = update.led_params {
            ecg.insert("ledParams207".to_string(), value);
        }
        if update.gtin.is_some() || update.serial.is_some() {
            let gtin_serial = ecg
                .entry("gtinSerial".to_string())
                .or_insert_with(|| json!({"gtin": 0, "serial": 0}));
            let Some(gtin_serial) = gtin_serial.as_object_mut() else {
                return Err("session ECG GTIN/serial model changed during extraction");
            };
            if let Some(gtin) = update.gtin {
                gtin_serial.insert("gtin".to_string(), json!(gtin));
            }
            if let Some(serial) = update.serial {
                gtin_serial.insert("serial".to_string(), json!(serial));
            }
        }
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum ParameterFamily {
    ErrorReporting,
    Measurement,
}

#[derive(Clone, Copy)]
struct MemorySpec {
    address_a: u32,
    address_b: u32,
    length: usize,
    stride: u32,
    line: bool,
    indexed: bool,
}

impl MemorySpec {
    const fn scalar(address: u32) -> Self {
        Self::bytes(address, 1)
    }

    const fn bytes(address: u32, length: usize) -> Self {
        Self {
            address_a: address,
            address_b: address,
            length,
            stride: 0,
            line: false,
            indexed: false,
        }
    }

    const fn lined(address_a: u32, address_b: u32, length: usize, stride: u32) -> Self {
        Self {
            address_a,
            address_b,
            length,
            stride,
            line: true,
            indexed: stride != 0,
        }
    }

    fn value_name(self, family: ParameterFamily, name: &str) -> &'static str {
        match (family, name) {
            (ParameterFamily::ErrorReporting, "USED_DEVICE_MASK") => "<bitmask64>",
            (ParameterFamily::ErrorReporting, "STORE_OPTION") => "<store-option>",
            (ParameterFamily::ErrorReporting, "INTERVAL") => "<report-interval>",
            (ParameterFamily::ErrorReporting, "MODE") => "<error-mode>",
            (ParameterFamily::ErrorReporting, "ENABLE_GROUP") => "<reporting-enable-group>",
            (ParameterFamily::ErrorReporting, "DEVICE_ID") => "<device-id>",
            (ParameterFamily::ErrorReporting, "TRIGGER_REPORT_GROUP") => "<trigger-report-group>",
            (ParameterFamily::ErrorReporting, "RESEND_ACTION_SELECTOR") => {
                "<resend-action-selector>"
            }
            (ParameterFamily::ErrorReporting, "ACK_ALL_ERRORS_ACTION_SELECTOR") => {
                "<ack-action-selector>"
            }
            (ParameterFamily::ErrorReporting, "NETWORK_PATH") => "<network-path>",
            (ParameterFamily::Measurement, "LAMP_RUNNING_TIME") => "<running-time32>",
            (ParameterFamily::Measurement, "REQUEST_TRIGGER_GROUP") => "<request-trigger-group>",
            (ParameterFamily::Measurement, "CLEAR_TRIGGER_GROUP") => "<clear-trigger-group>",
            _ => "<data-byte>",
        }
    }
}

fn tokens(raw: &str) -> Vec<String> {
    let mut values = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    let mut chars = raw.chars().peekable();
    while let Some(character) = chars.next() {
        match character {
            '"' => quoted = !quoted,
            '\\' if matches!(chars.peek(), Some('\\' | '"' | ' ')) => {
                current.push(chars.next().expect("peeked escape"));
            }
            value if value.is_whitespace() && !quoted => {
                if !current.is_empty() {
                    values.push(std::mem::take(&mut current));
                }
            }
            value => current.push(value),
        }
    }
    if !current.is_empty() {
        values.push(current);
    }
    values
}

fn syntax(tag: &str) -> Response {
    err(tag, 400, "400 Syntax Error: Invalid number of parameters")
}

fn rows(tag: &str, status: u16, values: Vec<String>) -> Response {
    Response {
        tag: tag.to_string(),
        lines: values
            .into_iter()
            .map(|value| format!("{status}-{value}"))
            .collect(),
        final_text: "200 OK.".to_string(),
        status: 200,
    }
}

fn number(tag: &str, value: &str, name: &str, min: u32, max: u32) -> Result<u32, Response> {
    let value_num = value
        .strip_prefix('$')
        .or_else(|| value.strip_prefix("0x"))
        .or_else(|| value.strip_prefix("0X"))
        .map_or_else(|| value.parse(), |hex| u32::from_str_radix(hex, 16));
    match value_num {
        Ok(value_num) if (min..=max).contains(&value_num) => Ok(value_num),
        _ => Err(err(
            tag,
            400,
            &format!("400 Syntax Error: Invalid parameter {name}: {value}"),
        )),
    }
}

fn bytes_arg(tag: &str, value: &str, length: usize, name: &str) -> Result<Vec<u8>, Response> {
    parse_mask(
        value.trim_start_matches("0x").trim_start_matches("0X"),
        length,
    )
    .map_err(|_| {
        err(
            tag,
            400,
            &format!("400 Syntax Error: Invalid parameter {name}: {value}"),
        )
    })
}

fn line_arg(tag: &str, value: &str) -> Result<DaliLine, Response> {
    DaliLine::parse(value).map_err(|_| {
        err(
            tag,
            400,
            &format!("400 Syntax Error: Invalid parameter <line>: {value}"),
        )
    })
}

fn memory_rows(tag: &str, target: &str, address: u32, bytes: &[u8]) -> Response {
    ok(
        tag,
        vec![
            format!("120-{target}: Address=${address:04X}"),
            format!("120-{target}: ${}", hex::encode_upper(bytes)),
        ],
        "200 OK.",
    )
}

fn paged_rows(tag: &str, target: &str, address: u32, bytes: &[u8]) -> Response {
    let mut formatted = String::new();
    for (index, byte) in bytes.iter().enumerate() {
        formatted.push_str(&format!("{byte:02X} "));
        if index % 4 == 3 {
            formatted.push(' ');
        }
        if index % 8 == 7 {
            formatted.push('\n');
        }
    }
    ok(
        tag,
        vec![
            format!("120-{target}: Address$={address:04X}"),
            format!("120-{target}: Recall=$"),
            format!("120-{target}: {formatted}"),
        ],
        "200 OK.",
    )
}

fn gateway_cal_rows(
    tag: &str,
    command: &str,
    operation: u8,
    payload: &[u8],
    result: cbus_transport::pci::DaliCommandResult,
) -> Response {
    let mut lines = Vec::new();
    for (index, exchange) in result.exchanges.iter().enumerate() {
        if index != 0 {
            lines.push(format!("120-=========== #{index} =============="));
        }
        lines.push(format!(
            "120-DaliCommand={command}: ${operation:02X} ({})",
            exchange.mode.name()
        ));
        lines.push(format!(
            "120-Payload=${}",
            hex::encode_upper(if exchange.mode == DaliCalMode::Execute {
                payload
            } else {
                &[]
            })
        ));
        lines.push(format!("100-SendCommand={}", exchange.request_wire));
        lines.push(format!(
            "300-Response={}",
            hex::encode_upper(&exchange.response_wire)
        ));
        lines.push(format!(
            "320-ResponseStatus={}",
            dali_status_name(exchange.status)
        ));
        lines.push(format!(
            "320-ResponsePayload={}",
            if exchange.nak {
                "null".to_string()
            } else {
                hex::encode_upper(&exchange.data)
            }
        ));
    }
    Response {
        tag: tag.to_string(),
        lines,
        final_text: "200 OK.".to_string(),
        status: 200,
    }
}

fn dali_status_name(status: u8) -> &'static str {
    match status {
        0 => "SUCCESS",
        1 => "IN_PROGRESS",
        2 => "FAIL_BUSY",
        3 => "FAIL_INVALID_COMMAND",
        4 => "FAIL_INVALID_PARAMETER",
        5 => "FAIL_INCORRECT_LENGTH",
        6 => "FAIL_INVALID_DEVICE_TYPE",
        _ => "FAIL_CATASTROPHE",
    }
}

fn session_model(session: &DaliSession) -> Value {
    let mut model = session.model.clone();
    if let Some(root) = model.as_object_mut() {
        root.insert("extParams".to_string(), session.ext.as_json());
    }
    model
}

#[derive(Debug)]
enum Selector {
    Index(usize),
    Match(String, String),
    All,
}

fn segment(value: &str) -> (String, Option<Selector>) {
    let Some(open) = value.find('[') else {
        return (value.to_string(), None);
    };
    if !value.ends_with(']') {
        return (value.to_string(), None);
    }
    let name = value[..open].to_string();
    let selector = &value[open + 1..value.len() - 1];
    if selector == "*" {
        return (name, Some(Selector::All));
    }
    if let Ok(index) = selector.parse::<usize>() {
        return (name, Some(Selector::Index(index)));
    }
    if let Some(predicate) = selector.strip_prefix('@') {
        if let Some((property, expected)) = predicate.split_once('=') {
            return (
                name,
                Some(Selector::Match(
                    property.to_string(),
                    expected.trim_matches(['\'', '"']).to_string(),
                )),
            );
        }
    }
    (value.to_string(), None)
}

fn pointer_component(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

fn select_json(root: &Value, path: &str) -> Vec<(String, Value)> {
    if path.is_empty() || path == "/" {
        return vec![("/".to_string(), root.clone())];
    }
    let pieces = path
        .trim_start_matches('/')
        .split('/')
        .filter(|piece| !piece.is_empty())
        .collect::<Vec<_>>();
    let mut current = vec![(String::new(), root.clone())];
    for piece in pieces {
        let (name, selector) = segment(piece);
        let mut next = Vec::new();
        for (pointer, value) in current {
            let (selected, base) = if name.is_empty() {
                (value, pointer)
            } else if let (Some(values), Ok(index)) = (value.as_array(), name.parse::<usize>()) {
                let Some(value) = values.get(index).cloned() else {
                    continue;
                };
                (value, format!("{pointer}/{index}"))
            } else {
                let Some(value) = value.get(&name).cloned() else {
                    continue;
                };
                (value, format!("{pointer}/{}", pointer_component(&name)))
            };
            match selector.as_ref() {
                None => next.push((base, selected)),
                Some(Selector::Index(index)) => {
                    if let Some(value) = selected.get(*index).cloned() {
                        next.push((format!("{base}/{index}"), value));
                    }
                }
                Some(Selector::All) => {
                    if let Some(values) = selected.as_array() {
                        next.extend(
                            values
                                .iter()
                                .cloned()
                                .enumerate()
                                .map(|(index, value)| (format!("{base}/{index}"), value)),
                        );
                    }
                }
                Some(Selector::Match(property, expected)) => {
                    if let Some(values) = selected.as_array() {
                        next.extend(values.iter().cloned().enumerate().filter_map(
                            |(index, value)| {
                                let matches = value
                                    .get(property)
                                    .or_else(|| value.get(property.to_ascii_uppercase()))
                                    .and_then(Value::as_str)
                                    .is_some_and(|value| {
                                        value.trim_start_matches('!')
                                            == expected.trim_start_matches('!')
                                    });
                                matches.then(|| (format!("{base}/{index}"), value))
                            },
                        ));
                    }
                }
            }
        }
        current = next;
    }
    current
}

fn set_json(root: &mut Value, path: &str, value: Value) -> Result<String, &'static str> {
    let selected = select_json(root, path);
    let Some((pointer, _)) = selected.first() else {
        return Err("pointer is not reachable");
    };
    if selected.len() != 1 || pointer == "/" {
        return Err("pointer is not a single write-able property");
    }
    let pointer = pointer.clone();
    let Some(target) = root.pointer_mut(&pointer) else {
        return Err("pointer is not reachable");
    };
    *target = value;
    Ok(pointer)
}

fn session_line(tag: &str, value: &str) -> Result<(bool, bool), Response> {
    if value.is_empty() {
        return Err(err(tag, 400, "400 Syntax Error: Invalid parameter <line>"));
    }
    Ok(if value.eq_ignore_ascii_case("A") {
        (true, false)
    } else if value.eq_ignore_ascii_case("B") {
        (false, true)
    } else {
        (true, true)
    })
}

fn ecg_range(tag: &str, value: &str) -> Result<Vec<u8>, Response> {
    value
        .split(',')
        .map(|part| number(tag, part, "[ecg-address-range]", 0, 63).map(|value| value as u8))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    fn fixture() -> String {
        include_str!("../../../testdata/fixtures/project.xml").replace(
            "</Network>",
            r#"<Unit oid="dali-gateway-20"><Address>20</Address><TagName>DALI Gateway</TagName><UnitType>SYS_DAL2</UnitType><FirmwareVersion>1.10.0</FirmwareVersion><SerialNumber>101136.1558</SerialNumber></Unit></Network>"#,
        )
    }

    fn state_path() -> PathBuf {
        static ID: AtomicU64 = AtomicU64::new(0);
        std::env::temp_dir().join(format!(
            "cmqttd-dali-specialized-{}-{}.json",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ))
    }

    async fn setup() -> (Arc<Service>, BufReader<tokio::io::DuplexStream>, PathBuf) {
        let (client, remote) = tokio::io::duplex(65_536);
        let (reader, writer) = tokio::io::split(client);
        let (events, _) = tokio::sync::mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(reader), Box::new(writer), events);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut init = Vec::new();
            remote.read_until(b'\r', &mut init).await.unwrap();
        }
        let path = state_path();
        let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        (service, remote, path)
    }

    async fn line(remote: &mut BufReader<tokio::io::DuplexStream>) -> Vec<u8> {
        let mut bytes = Vec::new();
        remote.read_until(b'\r', &mut bytes).await.unwrap();
        bytes
    }

    async fn reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, cal: &[u8]) {
        let mut bytes = vec![0x86, unit, 0x10, 0x00];
        bytes.extend(cal);
        let checksum = bytes.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(checksum));
        remote
            .get_mut()
            .write_all(format!("{}\r\n", hex::encode_upper(bytes)).as_bytes())
            .await
            .unwrap();
    }

    async fn dali_success(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        operation: u8,
        data: &[u8],
    ) {
        let mut cal = vec![
            0xe4 + u8::try_from(data.len()).unwrap(),
            0x83,
            0xda,
            operation,
            0,
        ];
        cal.extend_from_slice(data);
        reply(remote, 20, &cal).await;
    }

    async fn drive_dali_only_prefix_to_known_type(remote: &mut BufReader<tokio::io::DuplexStream>) {
        let known = [0x08, 0, 0, 0, 0, 0, 0, 0];
        let clear = [0; 8];

        assert_eq!(line(remote).await, b"\\061400E381DA0D\r");
        dali_success(remote, 13, &[1]).await;
        assert_eq!(line(remote).await, b"\\061400E382DA07\r");
        dali_success(remote, 7, &known).await;
        assert_eq!(line(remote).await, b"\\061400E381DA0A\r");
        dali_success(remote, 10, &known).await;
        assert_eq!(line(remote).await, b"\\061400E381DA0B\r");
        dali_success(remote, 11, &clear).await;
        assert_eq!(line(remote).await, b"\\061400E381DA09\r");
        dali_success(remote, 9, &known).await;
        assert_eq!(line(remote).await, b"\\061400E381DA03\r");
        // Native ignores this operation's reply data; accepting it proves the
        // codec checks status without inventing a payload contract.
        dali_success(remote, 3, &[0xaa]).await;
        assert_eq!(line(remote).await, b"\\061400E381DA04\r");
        dali_success(remote, 4, &known).await;
        assert_eq!(line(remote).await, b"\\061400E481DA1A03\r");
        dali_success(remote, 26, &[3]).await;
        assert_eq!(line(remote).await, b"\\061400E481DA1003\r");
    }

    async fn drive_mutation_preflight(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        rescan: bool,
    ) {
        if rescan {
            assert_eq!(line(remote).await, b"\\061400E381DA0E\r");
            dali_success(remote, 14, &[]).await;
        }
        assert_eq!(line(remote).await, b"\\061400E382DA04\r");
        dali_success(remote, 4, &[0x08, 0, 0, 0, 0, 0, 0, 0]).await;
        assert_eq!(line(remote).await, b"\\061400E381DA0B\r");
        dali_success(remote, 11, &[0; 8]).await;
    }

    async fn expect_ext_recall_request(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        consumed: usize,
    ) -> usize {
        let logical = EXT_START + consumed as u32;
        let page = (logical >> 8) as u8;
        let parameter = logical as u8;
        let count = (EXT_LEN - consumed)
            .min(256 - usize::from(parameter))
            .min(255);
        assert_eq!(
            line(remote).await,
            format!("\\4614001B{page:02X}{parameter:02X}{count:02X}\r").as_bytes()
        );
        count
    }

    async fn reply_ext_recall_block(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        consumed: usize,
        count: usize,
        value: u8,
    ) {
        let parameter = (EXT_START + consumed as u32) as u8;
        let block = vec![value; count];
        // Native C-Gate's `L` recall (also used by the ef/eh/ep DALI paged
        // readers) names each fragment by the parameter of its first byte.
        for (index, fragment) in block.chunks(16).enumerate() {
            let mut cal = vec![
                0x80 | (u8::try_from(fragment.len()).unwrap() + 1),
                parameter.wrapping_add((index * 16) as u8),
            ];
            cal.extend_from_slice(fragment);
            reply(remote, 20, &cal).await;
        }
    }

    async fn drive_ext_recall(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        mut consumed: usize,
        value: u8,
    ) {
        while consumed < EXT_LEN {
            let count = expect_ext_recall_request(remote, consumed).await;
            reply_ext_recall_block(remote, consumed, count, value).await;
            consumed += count;
        }
    }

    async fn drive_one_byte_ext_store_to_readback(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        value: u8,
    ) {
        assert_eq!(line(remote).await, b"\\4614003901\r");
        reply(remote, 20, &[0x81, 1]).await;
        let store = line(remote).await;
        let prefix = format!("\\461400A30000{value:02X}");
        assert!(store.starts_with(prefix.as_bytes()), "{store:?}");
        reply(remote, 20, &[0x32, 0, 0]).await;
        assert_eq!(line(remote).await, b"\\4614001B010001\r");
    }

    #[test]
    fn evidence_fixture_pins_all_sixty_specialized_paths() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../testdata/fixtures/native_cgate_dali_specialized.json"
        ))
        .unwrap();
        assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
        assert_eq!(fixture["inventory"]["physical_paths"], 41);
        assert_eq!(fixture["inventory"]["local_paths"], 19);
        assert_eq!(fixture["inventory"]["whole_path_fail_closed"], 0);
        assert_eq!(fixture["physical"].as_object().unwrap().len(), 41);
        assert_eq!(fixture["local"].as_object().unwrap().len(), 19);
        assert_eq!(
            fixture["physical"]["SESSION EXTRACT"]["evidenced_selectors"],
            json!([
                "EXT_ONLY",
                "DALI_ONLY",
                "FULL",
                "REFRESH_STATUS_INFO",
                "RETRIEVE_RECONCILE",
                "COND_QUICK",
                "COND_EXTENDED",
                "RESCAN_FAULT"
            ])
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["extract_plan_class_sha256"],
            "5f6308a20c449b76e6a0ed9f3927383c107cb345749101052c3c056c30455e49"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["typed_model_class_sha256"]
                ["DaliStruct202Params"],
            "a643f64e786526aca6f627968045726f9bccfcaf932ed1b2d4cc141a902c7607"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["extract_type_enum_sha256"],
            "5626928bc99258de3454643fc26bee3e398c5290d7f203bb007152d41a3d1876"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["typed_model_class_sha256"]
                ["DaliStruct102Params"],
            "ce3f81438e4f5307e9d6b79aab5ce5f3c58bd69cf902f0d69a6b8e0f145513f6"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["typed_model_class_sha256"]
                ["DaliEcg"],
            "50dd3d30d0794fe00bc0004ea26f125b50f7547b7cdff53a625692a4bbe00f13"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["operation_command_class_sha256"]
                ["DISCOVER_KNOWN_FULL_INFO:dS"],
            "d65991b377597efccb49fc87a67d3358e12d800e0d714558dcb06fad64b14909"
        );
        assert_eq!(
            fixture["safety_boundary"]["native_plan_evidence"]["operation_command_class_sha256"]
                ["ADDRESS_UNKNOWN:dG"],
            "c97241786bdd497017f5e72f4abec5338d6b082dafe27d753a9616e22f6c4c59"
        );
        assert_eq!(
            fixture["safety_boundary"]["implemented_read_only_typed_session_operations"]
                ["COND_UNREAD_GET_EMERGENCY_PARAMS_ECG"],
            23
        );
        assert_eq!(
            fixture["safety_boundary"]["implemented_conditional_session_plans"]["RESCAN_FAULT"]
                ["first_mutating_step"],
            "ADDRESS_UNKNOWN"
        );
        assert_eq!(
            fixture["safety_boundary"]["remaining_typed_session_plans"],
            json!([])
        );
        assert_eq!(
            fixture["safety_boundary"]["remaining_typed_deploy_plans"],
            json!([])
        );
        assert_eq!(
            fixture["safety_boundary"]["address_unknown_evidence_audit"]["execute_payload_bytes"],
            0
        );
        assert_eq!(
            fixture["safety_boundary"]["address_unknown_evidence_audit"]["success_payload_bytes"],
            8
        );
        assert_eq!(
            fixture["safety_boundary"]["typed_deploy_evidence_audit"]
                ["individually_evidenced_wire_operations"]["SET_COMMON_PARAMS"]["operation"],
            32
        );
        assert_eq!(
            fixture["safety_boundary"]["typed_deploy_evidence_audit"]
                ["individually_evidenced_wire_operations"]["SET_COMMON_PARAMS"]
                ["readback_operation"],
            17
        );
        assert_eq!(
            fixture["physical"]["SESSION DEPLOY"]["evidenced_selectors"],
            json!(["EXT_ONLY", "DALI_ONLY", "FULL"])
        );

        // The case-sensitive re-decompilation must describe the same class
        // bytes that the plan evidence already pins.
        let recovered = &fixture["safety_boundary"]["recovered_native_source"];
        let evidence = &fixture["safety_boundary"]["native_plan_evidence"];
        assert_eq!(
            recovered["decompilation"]["cgate_jar_sha256"],
            evidence["cgate_jar_sha256"]
        );
        for (class, pinned) in [
            ("ka", "executor_class_sha256"),
            ("kc", "selection_class_sha256"),
            ("jY", "extract_plan_class_sha256"),
            ("DaliSyncSteps", "step_enum_sha256"),
        ] {
            assert_eq!(
                recovered["classes"][class]["class_sha256"], evidence[pinned],
                "{class}"
            );
        }
        assert_eq!(
            recovered["classes"]["dG"]["class_sha256"],
            evidence["operation_command_class_sha256"]["ADDRESS_UNKNOWN:dG"]
        );
        assert_eq!(
            recovered["typed_deploy"]["plans"]["FULL"],
            json!([
                "SET_COMMON_PARAMS_ECG",
                "SET_SCENE_VALUES_ECG",
                "SET_LED_PARAMS_ECG",
                "SET_EMERGENCY_PARAMS_ECG",
                "WRITE_GATEWAY_EXT_FULL"
            ])
        );
        assert_eq!(
            recovered["cal_sequence"]["step_overrides"]["ADDRESS_UNKNOWN"]["max_polls"],
            67
        );
        let conditional = &fixture["safety_boundary"]["implemented_conditional_session_plans"];
        for (plan, steps) in [
            ("COND_QUICK", COND_QUICK_EXTRACT_PLAN),
            ("COND_EXTENDED", COND_EXTENDED_EXTRACT_PLAN),
            ("RESCAN_FAULT", RESCAN_FAULT_EXTRACT_PLAN),
        ] {
            assert_eq!(
                conditional[plan]["native_plan"],
                json!(steps.iter().map(|step| step.name()).collect::<Vec<_>>()),
                "{plan}"
            );
            for step in conditional[plan]["native_plan"].as_array().unwrap() {
                assert!(
                    recovered["conditional_extraction_steps"]
                        .get(step.as_str().unwrap())
                        .is_some(),
                    "{plan}: {step}"
                );
            }
        }
    }

    #[test]
    fn native_read_only_extract_plans_have_the_exact_pinned_step_order() {
        assert_eq!(
            DALI_ONLY_EXTRACT_PLAN
                .iter()
                .map(|step| step.name())
                .collect::<Vec<_>>(),
            [
                "CHECK_FOR_UNKNOWN",
                "POLL_KNOWN",
                "BROKEN",
                "MISSING",
                "CONFLICTING",
                "DISCOVER_KNOWN_TYPE_INFO",
                "DISCOVER_KNOWN_FULL_INFO",
                "DISCOVER_STATUS_INFO_ECG",
                "GET_KNOWN_TYPE_INFO_ECG",
                "GET_COMMON_PARAMS_ECG",
                "GET_COMMON_READ_ONLY_PARAMS_ECG",
                "GET_SCENE_VALUES_ECG",
                "GET_LED_PARAMS_ECG",
                "GET_EMERGENCY_PARAMS_ECG",
                "GET_EMERGENCY_STATUS_ECG",
            ]
        );
        assert_eq!(
            FULL_EXTRACT_PLAN
                .iter()
                .map(|step| step.name())
                .collect::<Vec<_>>(),
            [
                "POLL_KNOWN",
                "BROKEN",
                "MISSING",
                "CONFLICTING",
                "DISCOVER_KNOWN_TYPE_INFO",
                "DISCOVER_KNOWN_FULL_INFO",
                "DISCOVER_STATUS_INFO_ECG",
                "GET_KNOWN_TYPE_INFO_ECG",
                "GET_COMMON_PARAMS_ECG",
                "GET_COMMON_READ_ONLY_PARAMS_ECG",
                "GET_SCENE_VALUES_ECG",
                "DISCOVER_GTIN_SERIAL_ECG",
                "GET_GTIN_ECG",
                "GET_SERIAL_ECG",
                "GET_LED_PARAMS_ECG",
                "GET_EMERGENCY_PARAMS_ECG",
                "GET_EMERGENCY_STATUS_ECG",
                "READ_GATEWAY_EXT_FULL",
            ]
        );
        assert_eq!(COND_QUICK_EXTRACT_PLAN.len(), 13);
        assert_eq!(
            COND_EXTENDED_EXTRACT_PLAN[..13],
            COND_QUICK_EXTRACT_PLAN[..]
        );
        assert_eq!(
            COND_EXTENDED_EXTRACT_PLAN[13],
            ConditionalExtractStep::GetCommonParamsEcg
        );
        assert_eq!(RESCAN_FAULT_EXTRACT_PLAN[0], ConditionalExtractStep::Rescan);
        assert_eq!(RESCAN_FAULT_EXTRACT_PLAN[1..], COND_QUICK_EXTRACT_PLAN[..]);
        let recovered: Value = serde_json::from_str(include_str!(
            "../../../testdata/fixtures/native_cgate_dali_specialized.json"
        ))
        .unwrap();
        let overrides = &recovered["safety_boundary"]["recovered_native_source"]["cal_sequence"]
            ["step_overrides"];
        for (step, budget) in [
            ("POLL_FINISH_DISCOVER_KNOWN_FULL_INFO", POLL_FINISH_BUDGET),
            ("COND_DISCOVER_KNOWN_FULL_INFO", DISCOVER_FULL_BUDGET),
            ("DISCOVER_KNOWN_FULL_INFO", DISCOVER_FULL_BUDGET),
            ("COND_DISCOVER_KNOWN_TYPE_INFO", DISCOVER_TYPE_BUDGET),
            ("DISCOVER_KNOWN_TYPE_INFO", DISCOVER_TYPE_BUDGET),
            ("RESCAN", RESCAN_BUDGET),
            ("ADDRESS_UNKNOWN", ADDRESS_UNKNOWN_BUDGET),
        ] {
            assert_eq!(overrides[step]["first"], budget.first.name(), "{step}");
            assert_eq!(overrides[step]["max_polls"], budget.max_polls, "{step}");
            assert_eq!(
                overrides[step]["poll_interval_ms"],
                budget.interval.as_millis() as u64,
                "{step}"
            );
        }
    }

    #[test]
    fn native_broken_and_full_discovery_preserve_the_retained_flag_semantics() {
        let mut model = DaliSession::new("work", "HARNESS", "session-work").model;
        ensure_read_only_extract_model(&mut model, (true, false)).unwrap();
        model.pointer_mut("/cdg/daliLines/0/daliEcgs/3").unwrap()["isBroken"] = json!(true);

        apply_line_mask(&mut model, 0, Some(&[3]), "isBroken", &[0; 8], false).unwrap();
        let ecg = model.pointer("/cdg/daliLines/0/daliEcgs/3").unwrap();
        assert_eq!(ecg["isPreviouslyBroken"], true);
        assert_eq!(ecg["isBroken"], false);

        apply_line_mask(
            &mut model,
            0,
            Some(&[3]),
            "isFullyKnown",
            &[0x08, 0, 0, 0, 0, 0, 0, 0],
            true,
        )
        .unwrap();
        let ecg = model.pointer("/cdg/daliLines/0/daliEcgs/3").unwrap();
        assert_eq!(ecg["isKnown"], true);
        assert_eq!(ecg["isFullyKnown"], true);
        assert_eq!(ecg["isPreviouslyBroken"], true);
        assert_eq!(ecg["isBroken"], false);
    }

    #[test]
    fn dirty_extended_writes_are_page_bounded_and_twelve_bytes_maximum() {
        let mut map = ExtendedMap::default();
        map.stage(0x01f8, &[1; 16]).unwrap();
        assert_eq!(
            map.dirty_chunks()
                .iter()
                .map(|(address, bytes)| (*address, bytes.len()))
                .collect::<Vec<_>>(),
            [(0x01f8, 8), (0x0200, 8)]
        );
        map.commit_chunk(0x01f8, &[1; 8]);
        assert_eq!(map.dirty_chunks()[0].0, 0x0200);
        map.targets.insert(0x0210, 2);
        map.targets.insert(0x0211, 3);
        assert!(map
            .dirty_chunks()
            .iter()
            .all(|(_, bytes)| bytes.len() <= 12));
    }

    #[tokio::test(start_paused = true)]
    async fn error_reporting_recall_uses_exact_native_address_and_envelope() {
        let (service, mut remote, path) = setup().await;
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[e] DALI ERROR_REPORTING STORE_OPTION //HARNESS/254/p/20",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\4614001B020901\r");
        reply(&mut remote, 20, &[0x82, 0x09, 0xab]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response.lines,
            [
                "120-//HARNESS/254/p/20: Address=$0209".to_string(),
                "120-//HARNESS/254/p/20: $AB".to_string(),
            ]
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn gateway_factory_reset_uses_group_zero_and_reversed_serial() {
        let (service, mut remote, path) = setup().await;
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[g] DALI GATEWAY FACTORY_RESET EXEC !dali-gateway-20",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E78100011606B118\r");
        reply(&mut remote, 20, &[0xe4, 0x83, 0, 1, 0]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response.lines[0],
            "120-DaliCommand=FACTORY_RESET: $01 (EXECUTE)"
        );
        assert_eq!(response.lines[1], "120-Payload=$1606B118");
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn verified_store_on_retired_pci_generation_fails_without_replay() {
        let (service, mut remote, path) = setup().await;
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[w] DALI ERROR_REPORTING SET_STORE_OPTION //HARNESS/254/p/20 170",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\4614003902\r");
        reply(&mut remote, 20, &[0x81, 0x02]).await;
        let store = line(&mut remote).await;
        assert!(store.starts_with(b"\\461400A30900AA"), "{store:?}");
        reply(&mut remote, 20, &[0x32, 0x09, 0x00]).await;
        assert_eq!(line(&mut remote).await, b"\\4614001B020901\r");
        service.pci_generation.fetch_add(1, Ordering::AcqRel);
        reply(&mut remote, 20, &[0x82, 0x09, 0xaa]).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 522, "{response:?}");
        assert!(response.final_text.contains("outcome is uncertain"));
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "retired-generation store was replayed"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn local_session_lifecycle_and_json_access_do_not_touch_pci() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        let created = service
            .handle(&mut client, "[n] DALI SESSION NEW work")
            .await;
        assert_eq!(created.status, 200, "{created:?}");
        let set = service
            .handle(
                &mut client,
                "[s] DALI SESSION SET work /cdg/daliLines/0/lineId 7",
            )
            .await;
        assert_eq!(set.status, 200, "{set:?}");
        let get = service
            .handle(
                &mut client,
                "[q] DALI SESSION GET work /cdg/daliLines/0/lineId",
            )
            .await;
        assert_eq!(get.lines[1], "120-7");
        let listed = service.handle(&mut client, "[l] DALI SESSION LIST").await;
        assert_eq!(listed.status, 200);
        assert!(listed.lines[0].contains("\"name\":\"work\""));
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "local session operations emitted PCI bytes"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn ext_only_deploy_keeps_a_newer_concurrent_byte_dirty() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut ClientState::default(),
                    "[s] DALI SESSION SET_EXT_PARAMS work 256 170",
                )
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[d] DALI SESSION DEPLOY work !dali-gateway-20 A EXT_ONLY",
                    )
                    .await
            }
        });

        drive_one_byte_ext_store_to_readback(&mut remote, 0xaa).await;
        let newer = service
            .handle(
                &mut ClientState::default(),
                "[s2] DALI SESSION SET_EXT_PARAMS work 256 187",
            )
            .await;
        assert_eq!(newer.status, 200, "{newer:?}");
        reply(&mut remote, 20, &[0x82, 0, 0xaa]).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        let ext = session.ext.as_json();
        assert_eq!(ext["values"]["256"], json!(0xaa));
        assert_eq!(ext["targetValues"]["256"], json!(0xbb));
        assert_eq!(session.target_cdg.as_deref(), Some("!dali-gateway-20"));
        drop(state);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "the confirmed snapshot byte was replayed"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn ext_only_deploy_rejects_a_stale_commit_after_end_and_new() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut ClientState::default(),
                    "[s] DALI SESSION SET_EXT_PARAMS work 256 170",
                )
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[d] DALI SESSION DEPLOY work !dali-gateway-20 A EXT_ONLY",
                    )
                    .await
            }
        });

        drive_one_byte_ext_store_to_readback(&mut remote, 0xaa).await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[e] DALI SESSION END work",)
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n2] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        reply(&mut remote, 20, &[0x82, 0, 0xaa]).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 501, "{response:?}");
        assert_eq!(response.final_text, "501 session changed during deploy");
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(
            session.ext.as_json(),
            json!({"values": {}, "targetValues": {}})
        );
        assert!(session.target_cdg.is_none());
        drop(state);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "the stale deploy was replayed"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn ext_only_extract_rejects_a_concurrent_extended_edit() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A EXT_ONLY",
                    )
                    .await
            }
        });

        let first = expect_ext_recall_request(&mut remote, 0).await;
        let edited = service
            .handle(
                &mut ClientState::default(),
                "[s] DALI SESSION SET_EXT_PARAMS work 256 187",
            )
            .await;
        assert_eq!(edited.status, 200, "{edited:?}");
        reply_ext_recall_block(&mut remote, 0, first, 0x5a).await;
        drive_ext_recall(&mut remote, first, 0x5a).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 501, "{response:?}");
        assert_eq!(response.final_text, "501 session changed during extraction");
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        let ext = session.ext.as_json();
        assert_eq!(ext["values"], json!({}));
        assert_eq!(ext["targetValues"]["256"], json!(0xbb));
        assert!(session.source_cdg.is_none());
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn ext_only_extract_preserves_typed_model_and_dirty_flag() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut ClientState::default(),
                    "[s] DALI SESSION SET work /cdg/daliLines/0/lineId 77",
                )
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A EXT_ONLY",
                    )
                    .await
            }
        });
        drive_ext_recall(&mut remote, 0, 0x5a).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        let listed = service
            .handle(&mut ClientState::default(), "[l] DALI SESSION LIST")
            .await;
        assert_eq!(listed.status, 200, "{listed:?}");
        assert!(
            listed
                .lines
                .iter()
                .any(|line| line.contains("\"modelDirty\":true")),
            "{listed:?}"
        );
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(
            session.model.pointer("/cdg/daliLines/0/lineId"),
            Some(&json!(77))
        );
        assert!(session.model_dirty);
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        assert_eq!(session.ext.as_json()["values"]["256"], json!(0x5a));
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn every_specialized_inventory_path_reaches_its_implemented_dispatch() {
        let (service, mut remote, path) = setup().await;
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../testdata/fixtures/native_cgate_dali_specialized.json"
        ))
        .unwrap();
        let paths = fixture["physical"]
            .as_object()
            .unwrap()
            .keys()
            .chain(fixture["local"].as_object().unwrap().keys())
            .cloned()
            .collect::<Vec<_>>();
        assert_eq!(paths.len(), 60);

        let mut client = ClientState::default();
        for command in paths {
            let response = service
                .handle(&mut client, &format!("[all] DALI {command}"))
                .await;
            let rendered = response
                .lines
                .iter()
                .chain(std::iter::once(&response.final_text))
                .cloned()
                .collect::<Vec<_>>()
                .join("\n");
            assert!(
                !rendered.contains("SubCommand not found")
                    && !rendered
                        .contains("Command requires a physical backend that is not implemented"),
                "{command} missed specialized dispatch: {response:?}"
            );
        }
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "syntax-only dispatch inventory emitted PCI bytes"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn virtual_file_catalog_and_saved_session_round_trip_without_pci() {
        let (service, mut remote, path) = setup().await;
        service.model.lock().await.file_store.insert(
            "%HARNESS%/dali_catalogue/devices/test-driver.json".to_string(),
            br#"{"name":"TEST_DRIVER","description":"fixture","channels":["ECG_GENERIC"]}"#
                .to_vec(),
        );
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[r] DALI CATALOG RELOAD")
                .await
                .status,
            200
        );
        let catalog = service
            .handle(&mut client, "[c] DALI CATALOG GET_SPEC TEST_DRIVER")
            .await;
        assert_eq!(catalog.status, 200, "{catalog:?}");
        assert!(catalog.lines[0].contains("TEST_DRIVER"));

        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut client,
                    "[a] DALI SESSION CATALOG_DEVICE_ADD work TEST_DRIVER A 7",
                )
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut client,
                    "[s] DALI SESSION SET work /cdg/daliLines/0/lineId 9",
                )
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(&mut client, "[v] DALI SESSION SAVE work !dali-gateway-20",)
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(
                    &mut client,
                    "[s2] DALI SESSION SET work /cdg/daliLines/0/lineId 3",
                )
                .await
                .status,
            200
        );
        assert_eq!(
            service
                .handle(&mut client, "[l] DALI SESSION LOAD work !dali-gateway-20",)
                .await
                .status,
            200
        );
        let restored = service
            .handle(
                &mut client,
                "[g] DALI SESSION GET work /cdg/daliLines/0/lineId",
            )
            .await;
        assert_eq!(restored.lines[1], "120-9");
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "catalogue/session persistence emitted PCI bytes"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn refresh_status_info_runs_native_three_step_plan_and_commits_atomically() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        {
            let mut state = service.dali_state.lock().await;
            let ecgs = state
                .sessions
                .get_mut("work")
                .unwrap()
                .model
                .pointer_mut("/cdg/daliLines/0/daliEcgs")
                .unwrap();
            *ecgs = json!([
                null,
                null,
                null,
                {
                    "shortAddress": 3,
                    "isKnown": true,
                    "deviceTypes": {"deviceTypes": ["EMERGENCY"]}
                },
                {"shortAddress": 4, "isKnown": true}
            ]);
        }

        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A REFRESH_STATUS_INFO 3",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1A03\r");
        reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 0x1a, 0, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1203\r");
        reply(&mut remote, 20, &[0xe8, 0x83, 0xda, 0x12, 0, 3, 2, 5, 0xa0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1803\r");
        reply(
            &mut remote,
            20,
            &[0xec, 0x83, 0xda, 0x18, 0, 3, 1, 2, 3, 4, 5, 6, 7],
        )
        .await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response.lines,
            [
                "120-start extraction",
                "120-progress: 1/3, plan: DISCOVER_STATUS_INFO_ECG",
                "120-progress: 2/3, plan: GET_COMMON_READ_ONLY_PARAMS_ECG",
                "120-progress: 3/3, plan: GET_EMERGENCY_STATUS_ECG",
            ]
        );
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(
            session
                .model
                .pointer("/cdg/daliLines/0/daliEcgs/3/commonReadOnlyParams102"),
            Some(&json!({
                "daliVersionSupported": 2,
                "physicalMinimumLevel": 5,
                "statusBitmask8": 160,
            }))
        );
        assert_eq!(
            session
                .model
                .pointer("/cdg/daliLines/0/daliEcgs/3/emergencyStatus202"),
            Some(&json!({
                "emergencyMode": 1,
                "emergencyStatus": 2,
                "failureStatus": 3,
                "batteryCharge": 4,
                "durationTestResult": 5,
                "lampEmergencyTime": 6,
                "lampTotalTime": 7,
            }))
        );
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        assert!(session
            .model
            .pointer("/cdg/daliLines/0/daliEcgs/4/commonReadOnlyParams102")
            .is_none());
        drop(state);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "address-range filtering emitted an extra DALI command"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn typed_extract_rejects_a_concurrent_session_edit_and_preserves_it() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work",)
                .await
                .status,
            200
        );
        {
            let mut state = service.dali_state.lock().await;
            *state
                .sessions
                .get_mut("work")
                .unwrap()
                .model
                .pointer_mut("/cdg/daliLines/0/daliEcgs")
                .unwrap() = json!([{
                "shortAddress": 0,
                "isKnown": true,
                "deviceTypes": {"deviceTypes": ["EMERGENCY"]}
            }]);
        }

        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A REFRESH_STATUS_INFO",
                    )
                    .await
            }
        });

        // The extraction has captured its snapshot and is blocked on the first
        // PCI response. SESSION SET keeps the session OID unchanged, so the
        // commit guard must compare the complete model rather than only OID.
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1A00\r");
        let edited = service
            .handle(
                &mut ClientState::default(),
                "[set] DALI SESSION SET work /cdg/daliLines/0/lineId 77",
            )
            .await;
        assert_eq!(edited.status, 200, "{edited:?}");

        reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 0x1a, 0, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1200\r");
        reply(&mut remote, 20, &[0xe8, 0x83, 0xda, 0x12, 0, 0, 1, 2, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1800\r");
        reply(
            &mut remote,
            20,
            &[0xec, 0x83, 0xda, 0x18, 0, 0, 1, 2, 3, 4, 5, 6, 7],
        )
        .await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 501, "{response:?}");
        assert_eq!(response.final_text, "501 session changed during extraction");
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(
            session.model.pointer("/cdg/daliLines/0/lineId"),
            Some(&json!(77))
        );
        let ecg = session
            .model
            .pointer("/cdg/daliLines/0/daliEcgs/0")
            .unwrap();
        assert!(ecg.get("commonReadOnlyParams102").is_none());
        assert!(ecg.get("emergencyStatus202").is_none());
        assert!(session.source_cdg.is_none());
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn retrieve_reconcile_runs_native_conditional_plan_and_skips_cached_fields() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        {
            let mut state = service.dali_state.lock().await;
            let ecgs = state
                .sessions
                .get_mut("work")
                .unwrap()
                .model
                .pointer_mut("/cdg/daliLines/1/daliEcgs")
                .unwrap();
            *ecgs = json!([{
                "shortAddress": 0,
                "isKnown": true,
                "deviceTypes": {"deviceTypes": ["EMERGENCY", "LED"]}
            }]);
        }

        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[r] DALI SESSION EXTRACT work !dali-gateway-20 B RETRIEVE_RECONCILE 0",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9200\r");
        reply(&mut remote, 20, &[0xe8, 0x83, 0xda, 0x92, 0, 0, 3, 6, 0x44]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9700\r");
        reply(
            &mut remote,
            20,
            &[0xec, 0x83, 0xda, 0x97, 0, 0, 1, 2, 3, 4, 5, 6, 7],
        )
        .await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9900\r");
        reply(&mut remote, 20, &[0xe7, 0x83, 0xda, 0x99, 0, 0, 1, 0x55]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9B00\r");
        reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 0x9b, 0, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9500\r");
        reply(
            &mut remote,
            20,
            &[0xeb, 0x83, 0xda, 0x95, 0, 0, 1, 2, 3, 4, 5, 6],
        )
        .await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA9600\r");
        reply(
            &mut remote,
            20,
            &[0xed, 0x83, 0xda, 0x96, 0, 0, 8, 7, 6, 5, 4, 3, 2, 1],
        )
        .await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert!(response
            .lines
            .iter()
            .any(|line| line.contains("6/6, plan: COND_UNREAD_GET_SERIAL_ECG")));
        {
            let state = service.dali_state.lock().await;
            let ecg = state
                .sessions
                .get("work")
                .unwrap()
                .model
                .pointer("/cdg/daliLines/1/daliEcgs/0")
                .unwrap();
            assert_eq!(ecg["commonReadOnlyParams102"]["daliVersionSupported"], 3);
            assert_eq!(ecg["emergencyParams202"]["emergencyLevel"], 1);
            assert_eq!(ecg["emergencyParams202"]["emergencyMin"], 4);
            assert_eq!(ecg["emergencyParams202"]["emergencyMax"], 5);
            assert_eq!(ecg["emergencyParams202"]["prolongTime"], 2);
            assert_eq!(ecg["emergencyParams202"]["timeout"], 3);
            assert_eq!(ecg["emergencyParams202"]["ratedDuration"], 6);
            assert_eq!(ecg["emergencyParams202"]["featuresByte"], 7);
            assert_eq!(ecg["emergencyParams202"]["switched"], true);
            assert_eq!(ecg["emergencyParams202"]["maintained"], true);
            assert_eq!(ecg["ledParams207"]["dimmCurve"], "LINEAR");
            assert_eq!(ecg["ledParams207"]["statusByte"], 0x55);
            assert_eq!(ecg["gtinSerial"]["gtin"], 0x0605_0403_0201u64);
            assert_eq!(ecg["gtinSerial"]["serial"], 0x0102_0304_0506_0708u64);
        }

        let cached = service
            .handle(
                &mut ClientState::default(),
                "[c] DALI SESSION EXTRACT work !dali-gateway-20 B RETRIEVE_RECONCILE 0",
            )
            .await;
        assert_eq!(cached.status, 200, "{cached:?}");
        assert_eq!(
            cached
                .lines
                .iter()
                .filter(|line| line.as_str() == "300-[WARN] no commands sent - no known ecgs")
                .count(),
            6
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "the conditional plan reread fields that were already populated"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn typed_extract_does_not_commit_a_partial_snapshot_after_bad_payload() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        {
            let mut state = service.dali_state.lock().await;
            *state
                .sessions
                .get_mut("work")
                .unwrap()
                .model
                .pointer_mut("/cdg/daliLines/0/daliEcgs")
                .unwrap() = json!([{
                "shortAddress": 0,
                "isKnown": true,
                "deviceTypes": {"deviceTypes": ["EMERGENCY"]}
            }]);
        }
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A REFRESH_STATUS_INFO",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1A00\r");
        reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 0x1a, 0, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1200\r");
        reply(&mut remote, 20, &[0xe8, 0x83, 0xda, 0x12, 0, 0, 1, 2, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1800\r");
        reply(&mut remote, 20, &[0xe5, 0x83, 0xda, 0x18, 0, 0]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 504, "{response:?}");
        let state = service.dali_state.lock().await;
        let ecg = state
            .sessions
            .get("work")
            .unwrap()
            .model
            .pointer("/cdg/daliLines/0/daliEcgs/0")
            .unwrap();
        assert!(ecg.get("commonReadOnlyParams102").is_none());
        assert!(ecg.get("emergencyStatus202").is_none());
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn dali_only_extract_uses_exact_wire_plan_and_decodes_the_native_model() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A DALI_ONLY 3",
                    )
                    .await
            }
        });

        drive_dali_only_prefix_to_known_type(&mut remote).await;
        dali_success(&mut remote, 16, &[3, 0, 1, 6, 8, 0xff, 0xff, 0xff, 0xff]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1103\r");
        dali_success(&mut remote, 17, &[3, 0x34, 0x12, 0, 0, 4, 250, 128, 7]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1203\r");
        dali_success(&mut remote, 18, &[3, 2, 3, 0x55]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1303\r");
        dali_success(&mut remote, 19, &[3, 1, 2, 3, 4, 5, 6, 7, 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1403\r");
        dali_success(&mut remote, 20, &[3, 9, 10, 11, 12, 13, 14, 15, 0xff]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1903\r");
        dali_success(&mut remote, 25, &[3, 1, 0x44]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1703\r");
        dali_success(&mut remote, 23, &[3, 10, 20, 30, 40, 50, 60, 6]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1803\r");
        dali_success(&mut remote, 24, &[3, 1, 2, 3, 4, 5, 6, 7]).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert!(response
            .lines
            .iter()
            .any(|line| line == "120-progress: 15/15, plan: GET_EMERGENCY_STATUS_ECG"));

        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        assert_eq!(
            session
                .model
                .pointer("/cdg/daliLines/0/containsUnaddressed"),
            Some(&json!(true))
        );
        let ecg = session
            .model
            .pointer("/cdg/daliLines/0/daliEcgs/3")
            .unwrap();
        assert_eq!(ecg["isKnown"], true);
        assert_eq!(ecg["isFullyKnown"], true);
        assert_eq!(ecg["isBroken"], true);
        assert_eq!(ecg["isMissing"], false);
        assert_eq!(ecg["isConflicting"], true);
        assert!(ecg.get("isPreviouslyBroken").is_none());
        assert_eq!(
            ecg["deviceTypes"]["deviceTypes"],
            json!(["LAMP", "EMERGENCY", "LED", "COLOUR_CONTROL"])
        );
        assert_eq!(ecg["commonParams102"]["groupMembershipBitmask16"], 0x1234);
        assert_eq!(ecg["commonParams102"]["sceneMembershipBitmask16"], 0x7fff);
        assert_eq!(ecg["commonReadOnlyParams102"]["statusBitmask8"], 0x55);
        assert_eq!(ecg["scene"].as_array().unwrap().len(), 16);
        assert_eq!(ecg["scene"][15]["level"], 0xff);
        assert_eq!(ecg["ledParams207"]["dimmCurve"], "LINEAR");
        assert_eq!(ecg["emergencyParams202"]["emergencyLevel"], 10);
        assert_eq!(ecg["emergencyParams202"]["switched"], true);
        assert_eq!(ecg["emergencyParams202"]["maintained"], true);
        assert_eq!(ecg["emergencyStatus202"]["lampTotalTime"], 7);
        assert!(session
            .model
            .pointer("/cdg/daliLines/0/daliEcgs/2/isKnown")
            .is_none());
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn dali_only_extract_rolls_back_every_staged_field_after_bad_payload() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        let before = service
            .dali_state
            .lock()
            .await
            .sessions
            .get("work")
            .unwrap()
            .model
            .clone();
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A DALI_ONLY 3",
                    )
                    .await
            }
        });

        drive_dali_only_prefix_to_known_type(&mut remote).await;
        dali_success(&mut remote, 16, &[4, 0, 1, 6, 8, 0xff, 0xff, 0xff, 0xff]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 504, "{response:?}");
        assert!(response.final_text.contains("invalid payload"));
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(session.model, before);
        assert!(session.source_cdg.is_none());
        drop(state);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "failed extraction continued after the malformed typed reply"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn full_extract_commits_the_complete_extended_map_with_the_typed_snapshot() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A FULL 3",
                    )
                    .await
            }
        });

        let clear = [0; 8];
        assert_eq!(line(&mut remote).await, b"\\061400E382DA07\r");
        dali_success(&mut remote, 7, &clear).await;
        for (wire, operation) in [
            (b"\\061400E381DA0A\r".as_slice(), 10),
            (b"\\061400E381DA0B\r".as_slice(), 11),
            (b"\\061400E381DA09\r".as_slice(), 9),
        ] {
            assert_eq!(line(&mut remote).await, wire);
            dali_success(&mut remote, operation, &clear).await;
        }
        assert_eq!(line(&mut remote).await, b"\\061400E381DA03\r");
        dali_success(&mut remote, 3, &[]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA04\r");
        dali_success(&mut remote, 4, &clear).await;

        let mut consumed = 0usize;
        while consumed < EXT_LEN {
            let logical = EXT_START + consumed as u32;
            let page = (logical >> 8) as u8;
            let parameter = logical as u8;
            let count = (EXT_LEN - consumed)
                .min(256 - usize::from(parameter))
                .min(255);
            assert_eq!(
                line(&mut remote).await,
                format!("\\4614001B{page:02X}{parameter:02X}{count:02X}\r").as_bytes()
            );
            let block = (0..count)
                .map(|offset| ((logical + offset as u32) as u8) ^ 0x5a)
                .collect::<Vec<_>>();
            // Native `L` fragments name their own first byte's parameter.
            for (index, fragment) in block.chunks(16).enumerate() {
                let mut cal = vec![
                    0x80 | (u8::try_from(fragment.len()).unwrap() + 1),
                    parameter.wrapping_add((index * 16) as u8),
                ];
                cal.extend_from_slice(fragment);
                reply(&mut remote, 20, &cal).await;
            }
            consumed += count;
        }

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert!(response
            .lines
            .iter()
            .any(|line| line == "120-progress: 18/18, plan: READ_GATEWAY_EXT_FULL"));
        let state = service.dali_state.lock().await;
        let session = state.sessions.get("work").unwrap();
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        assert_eq!(
            session.model.pointer("/cdg/daliLines/0/daliEcgs/3/isKnown"),
            Some(&json!(false))
        );
        let ext = session.ext.as_json();
        assert_eq!(ext["values"]["256"], json!(0x5a));
        assert_eq!(ext["values"]["11375"], json!(((11_375u32 as u8) ^ 0x5a)));
        assert_eq!(ext["values"].as_object().unwrap().len(), EXT_LEN);
        assert_eq!(ext["targetValues"], json!({}));
        drop(state);
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn mutation_preflight_stops_on_a_retired_generation_without_replay() {
        let (service, mut remote, path) = setup().await;
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[x] DALI SESSION EXTRACT work !dali-gateway-20 A COND_QUICK",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E382DA04\r");
        service.pci_generation.fetch_add(1, Ordering::AcqRel);
        dali_success(&mut remote, 4, &[0; 8]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 503, "{response:?}");
        assert!(response.final_text.contains("PCI connection changed"));
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "retired-generation mutation preflight was replayed or continued"
        );
        let session = service.dali_state.lock().await.sessions["work"].clone();
        assert!(session.source_cdg.is_none());
        std::fs::remove_file(path).unwrap();
    }

    fn journals(path: &Path) -> Vec<Value> {
        let directory = dali_journal::journal_directory(path);
        let Ok(entries) = std::fs::read_dir(&directory) else {
            return Vec::new();
        };
        let mut records = entries
            .flatten()
            .map(|entry| {
                serde_json::from_slice::<Value>(&std::fs::read(entry.path()).unwrap()).unwrap()
            })
            .collect::<Vec<_>>();
        records.sort_by_key(|record| record["created_unix_ms"].as_i64());
        records
    }

    fn cleanup(path: PathBuf) {
        let _ = std::fs::remove_dir_all(dali_journal::journal_directory(&path));
        std::fs::remove_file(path).unwrap();
    }

    async fn no_more_frames(remote: &mut BufReader<tokio::io::DuplexStream>, context: &str) {
        assert!(
            tokio::time::timeout(Duration::from_secs(600), line(remote))
                .await
                .is_err(),
            "{context}"
        );
    }

    /// Answer one partial extended recall of `length` bytes at `address`.
    async fn drive_partial_recall(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        address: u32,
        length: usize,
        value: u8,
    ) {
        let mut consumed = (address - EXT_START) as usize;
        let end = consumed + length;
        while consumed < end {
            let logical = EXT_START + consumed as u32;
            let parameter = logical as u8;
            let count = (end - consumed).min(256 - usize::from(parameter)).min(255);
            assert_eq!(
                line(remote).await,
                format!("\\4614001B{:02X}{parameter:02X}{count:02X}\r", logical >> 8).as_bytes()
            );
            reply_ext_recall_block(remote, consumed, count, value).await;
            consumed += count;
        }
    }

    async fn drive_cond_quick_ext_line_a(remote: &mut BufReader<tokio::io::DuplexStream>) {
        for (start, end) in cond_quick_ext_ranges((true, false)) {
            drive_partial_recall(remote, start, (end - start) as usize, 0x5a).await;
        }
    }

    async fn new_session(service: &Arc<Service>) {
        assert_eq!(
            service
                .handle(&mut ClientState::default(), "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
    }

    fn spawn_command(service: &Arc<Service>, command: &str) -> tokio::task::JoinHandle<Response> {
        let service = service.clone();
        let command = command.to_string();
        tokio::spawn(async move { service.handle(&mut ClientState::default(), &command).await })
    }

    #[tokio::test(start_paused = true)]
    async fn cond_quick_assigns_addresses_once_and_runs_the_recovered_conditional_plan() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        service.dali_state.lock().await.poll_interval_override = Some(Duration::from_millis(1));
        let request = spawn_command(
            &service,
            "[x] DALI SESSION EXTRACT work !dali-gateway-20 A COND_QUICK",
        );
        // POLL_FINISH starts with POLL and clears the seven flags first.
        assert_eq!(line(&mut remote).await, b"\\061400E382DA04\r");
        dali_success(&mut remote, 4, &[0x08, 0, 0, 0, 0, 0, 0, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0B\r");
        dali_success(&mut remote, 11, &[0; 8]).await;
        // ADDRESS_UNKNOWN: no payload, EXECUTE then POLL while running.
        assert_eq!(line(&mut remote).await, b"\\061400E381DA02\r");
        assert_eq!(
            journals(&path).len(),
            1,
            "journal must exist before operation 2"
        );
        assert_eq!(journals(&path)[0]["state"], "send_pending");
        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 2, 1]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E382DA02\r");
        dali_success(&mut remote, 2, &[0x28, 0, 0, 0, 0, 0, 0, 0]).await;
        // ECG 5 is now address-known but not fully known: both COND steps run.
        assert_eq!(line(&mut remote).await, b"\\061400E381DA03\r");
        dali_success(&mut remote, 3, &[]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA04\r");
        dali_success(&mut remote, 4, &[0x28, 0, 0, 0, 0, 0, 0, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0A\r");
        dali_success(&mut remote, 10, &[0; 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA09\r");
        dali_success(&mut remote, 9, &[0; 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1003\r");
        dali_success(
            &mut remote,
            16,
            &[3, 1, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff],
        )
        .await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1005\r");
        dali_success(
            &mut remote,
            16,
            &[5, 0, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff],
        )
        .await;
        // Read-only and emergency parameters only for the EMERGENCY ECG.
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1203\r");
        dali_success(&mut remote, 18, &[3, 1, 5, 0xa0]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E481DA1703\r");
        dali_success(&mut remote, 23, &[3, 200, 2, 3, 100, 254, 7, 0x04]).await;
        drive_cond_quick_ext_line_a(&mut remote).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        let progress = response
            .lines
            .iter()
            .filter(|line| line.starts_with("120-progress"))
            .count();
        assert_eq!(progress, 13);
        for expected in [
            "120-progress: 3/13, plan: ADDRESS_UNKNOWN",
            "125-[COND] discovery1: true",
            "125-[COND] discovery2: true",
            "120-progress: 13/13, plan: READ_GATEWAY_EXT_COND_QUICK",
        ] {
            assert!(
                response.lines.iter().any(|line| line == expected),
                "{expected}: {response:?}"
            );
        }
        // Neither ECG is broken: both COND_BROKEN steps warn and send nothing.
        assert_eq!(
            response
                .lines
                .iter()
                .filter(|line| *line == "300-[WARN] no commands sent - no known ecgs")
                .count(),
            2
        );
        let state = service.dali_state.lock().await;
        let session = &state.sessions["work"];
        let line_a = session.model.pointer("/cdg/daliLines/0").unwrap();
        assert_eq!(line_a["containsUnaddressed"], false);
        assert_eq!(line_a["daliEcgs"][5]["isAddressKnown"], true);
        assert_eq!(line_a["daliEcgs"][5]["isFullyKnown"], true);
        assert_eq!(line_a["daliEcgs"][5]["isKnown"], true);
        assert_eq!(line_a["daliEcgs"][4]["isAddressKnown"], false);
        assert_eq!(
            line_a["daliEcgs"][3]["commonReadOnlyParams102"]["physicalMinimumLevel"],
            5
        );
        assert_eq!(
            line_a["daliEcgs"][3]["emergencyParams202"]["emergencyLevel"],
            200
        );
        let ext = session.ext.as_json();
        assert_eq!(ext["values"]["256"], 0x5a);
        assert_eq!(ext["values"]["8807"], 0x5a);
        assert!(ext["values"].get("258").is_none());
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        drop(state);
        let journal = &journals(&path)[0];
        assert_eq!(journal["state"], "complete");
        assert_eq!(journal["confirmed_writes"], 1);
        assert_eq!(journal["confirmed_notes"][0], "SUCCESS 2800000000000000");
        no_more_frames(&mut remote, "COND_QUICK continued after completion").await;
        cleanup(path);
    }

    #[tokio::test(start_paused = true)]
    async fn address_unknown_uses_the_67_poll_budget_and_rescan_failure_only_warns() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        service.dali_state.lock().await.poll_interval_override = Some(Duration::from_millis(1));
        let request = spawn_command(
            &service,
            "[x] DALI SESSION EXTRACT work !dali-gateway-20 A RESCAN_FAULT",
        );
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0E\r");
        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 14, 3]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E382DA04\r");
        dali_success(&mut remote, 4, &[0; 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0B\r");
        dali_success(&mut remote, 11, &[0; 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA02\r");
        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 2, 1]).await;
        for _ in 0..67 {
            assert_eq!(line(&mut remote).await, b"\\061400E382DA02\r");
            reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 2, 1]).await;
        }
        // Budget exhausted: native warns, applies no mask and continues.
        // No ECG is address-known, so neither COND discovery step runs.
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0A\r");
        dali_success(&mut remote, 10, &[0; 8]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA09\r");
        dali_success(&mut remote, 9, &[0; 8]).await;
        drive_cond_quick_ext_line_a(&mut remote).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        for expected in [
            "300-[WARN] rescan replyStatus ignored",
            "300-[WARN] address unknown incomplete",
            "125-[COND] discovery1: false",
            "125-[COND] discovery2: false",
        ] {
            assert!(
                response.lines.iter().any(|line| line == expected),
                "{expected}"
            );
        }
        let state = service.dali_state.lock().await;
        let line_a = state.sessions["work"]
            .model
            .pointer("/cdg/daliLines/0")
            .unwrap()
            .clone();
        drop(state);
        assert!(line_a.get("containsUnaddressed").is_none());
        assert!(line_a["daliEcgs"][5].get("isAddressKnown").is_none());
        // The gateway may still be assigning: the journal stays open.
        let journal = &journals(&path)[0];
        assert_eq!(journal["state"], "outcome_uncertain");
        assert_eq!(journal["confirmed_notes"][0], "IN_PROGRESS");
        no_more_frames(
            &mut remote,
            "ADDRESS_UNKNOWN was polled past 67 or replayed",
        )
        .await;
        cleanup(path);
    }

    #[tokio::test(start_paused = true)]
    async fn address_unknown_reconnect_is_uncertain_and_never_replayed() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        let before = service.dali_state.lock().await.sessions["work"]
            .model
            .clone();
        let request = spawn_command(
            &service,
            "[x] DALI SESSION EXTRACT work !dali-gateway-20 A COND_QUICK",
        );
        drive_mutation_preflight(&mut remote, false).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA02\r");
        service.pci_generation.fetch_add(1, Ordering::AcqRel);
        dali_success(&mut remote, 2, &[0x08, 0, 0, 0, 0, 0, 0, 0]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 503, "{response:?}");
        assert!(response
            .final_text
            .contains("PCI connection changed during ADDRESS_UNKNOWN"));
        assert!(response.final_text.contains("session was not updated"));
        assert!(response
            .final_text
            .contains("0 of 1 planned device writes confirmed"));
        assert!(response
            .final_text
            .contains("nothing was rolled back or replayed"));
        assert_eq!(
            service.dali_state.lock().await.sessions["work"].model,
            before
        );
        assert_eq!(journals(&path)[0]["state"], "outcome_uncertain");
        no_more_frames(&mut remote, "uncertain ADDRESS_UNKNOWN was replayed").await;
        cleanup(path);
    }

    #[tokio::test(start_paused = true)]
    async fn failure_after_address_unknown_commits_the_learned_model_without_replay() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        let request = spawn_command(
            &service,
            "[x] DALI SESSION EXTRACT work !dali-gateway-20 A COND_EXTENDED",
        );
        drive_mutation_preflight(&mut remote, false).await;
        assert_eq!(line(&mut remote).await, b"\\061400E381DA02\r");
        dali_success(&mut remote, 2, &[0x08, 0, 0, 0, 0, 0, 0, 0]).await;
        // ECG 3 is fully known: no COND discovery. BROKEN then fails.
        assert_eq!(line(&mut remote).await, b"\\061400E381DA0A\r");
        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 10, 4]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 502, "{response:?}");
        assert!(response
            .final_text
            .contains("committed because ADDRESS_UNKNOWN was sent"));
        assert!(response
            .final_text
            .contains("1 of 1 planned device writes confirmed"));
        assert!(response
            .lines
            .iter()
            .any(|line| line == "120-progress: 6/14, plan: BROKEN"));
        let session = service.dali_state.lock().await.sessions["work"].clone();
        let line_a = session.model.pointer("/cdg/daliLines/0").unwrap();
        assert_eq!(line_a["containsUnaddressed"], false);
        assert_eq!(line_a["daliEcgs"][3]["isAddressKnown"], true);
        assert_eq!(session.source_cdg.as_deref(), Some("!dali-gateway-20"));
        assert_eq!(journals(&path)[0]["state"], "complete");
        no_more_frames(
            &mut remote,
            "COND_EXTENDED continued or replayed after a fault",
        )
        .await;
        cleanup(path);
    }

    fn deploy_model() -> Value {
        json!([
            null, null, null,
            {
                "shortAddress": 3, "isKnown": true,
                "deviceTypes": {"deviceTypes": ["EMERGENCY"]},
                "commonParams102": {
                    "groupMembershipBitmask16": 0x0201, "sceneMembershipBitmask16": 0x0201,
                    "minimumLevel": 1, "maximumLevel": 254, "recoveryLevel": 253, "failureLevel": 200
                },
                "scene": [{"level": 10}, {"level": 20}, null, null, null, null, null, null,
                          null, {"level": 30}],
                "commonReadOnlyParams102": {"daliVersionSupported": 1, "physicalMinimumLevel": 5, "statusBitmask8": 0},
                "emergencyParams202": {"emergencyLevel": 180, "prolongTime": 4, "timeout": 7}
            },
            null,
            {
                "shortAddress": 5, "isKnown": true,
                "deviceTypes": {"deviceTypes": ["LED"]},
                "commonParams102": {
                    "groupMembershipBitmask16": 0, "sceneMembershipBitmask16": 0,
                    "minimumLevel": 2, "maximumLevel": 250, "recoveryLevel": 255, "failureLevel": 255
                },
                "ledParams207": {"dimmCurve": "LINEAR", "statusByte": 0}
            },
            {"shortAddress": 6, "isKnown": true, "isMissing": true},
            {"shortAddress": 7, "isKnown": true, "isConflicting": true},
            {"shortAddress": 8, "isKnown": false}
        ])
    }

    #[test]
    fn typed_deploy_plan_builds_native_payloads_in_native_order() {
        let mut model = DaliSession::new("work", "HARNESS", "s").model;
        *model.pointer_mut("/cdg/daliLines/0/daliEcgs").unwrap() = deploy_model();
        *model.pointer_mut("/cdg/daliLines/1/daliEcgs").unwrap() = json!([
            null, null,
            {"shortAddress": 2, "isKnown": true, "deviceTypes": {"deviceTypes": ["LAMP"]},
             "commonParams102": {"groupMembershipBitmask16": 0x8000, "sceneMembershipBitmask16": 0,
                                 "minimumLevel": 0, "maximumLevel": 254, "recoveryLevel": 254, "failureLevel": 254}}
        ]);
        let plan = typed_deploy_plan(&model, (true, true), None).unwrap();
        let flat = plan
            .iter()
            .map(|step| {
                (
                    step.name,
                    step.phases
                        .iter()
                        .map(|phase| {
                            phase
                                .iter()
                                .map(|write| {
                                    format!(
                                        "{}{}:{}",
                                        write.line.name(),
                                        write.operation,
                                        hex::encode_upper(&write.payload)
                                    )
                                })
                                .collect::<Vec<_>>()
                        })
                        .collect::<Vec<_>>(),
                )
            })
            .collect::<Vec<_>>();
        assert_eq!(
            flat,
            vec![
                (
                    "SET_COMMON_PARAMS_ECG",
                    vec![vec![
                        "A32:03010201FEFDC8".to_string(),
                        "A32:05000002FAFFFF".to_string(),
                        "B32:02008000FEFEFE".to_string(),
                    ]]
                ),
                (
                    "SET_SCENE_VALUES_ECG",
                    vec![
                        vec![
                            // Scene 1 has a level but no membership bit.
                            "A34:030AFFFFFFFFFFFFFF".to_string(),
                            "A34:05FFFFFFFFFFFFFFFF".to_string(),
                            "B34:02FFFFFFFFFFFFFFFF".to_string(),
                        ],
                        vec![
                            "A35:03FF1EFFFFFFFFFFFF".to_string(),
                            "A35:05FFFFFFFFFFFFFFFF".to_string(),
                            "B35:02FFFFFFFFFFFFFFFF".to_string(),
                        ],
                    ]
                ),
                ("SET_LED_PARAMS_ECG", vec![vec!["A40:0501".to_string()]]),
                (
                    "SET_EMERGENCY_PARAMS_ECG",
                    vec![vec!["A38:03B40407".to_string()]]
                ),
            ]
        );
        // The optional address set filters every step.
        let ranged = typed_deploy_plan(&model, (true, false), Some(&[5])).unwrap();
        assert!(ranged[3].phases[0].is_empty());
        assert_eq!(ranged[2].phases[0].len(), 1);

        for (pointer, value, warning) in [
            (
                "/cdg/daliLines/0/daliEcgs/5/commonParams102",
                Value::Null,
                "common parameters not set for ecg: 5",
            ),
            (
                "/cdg/daliLines/0/daliEcgs/5/ledParams207",
                Value::Null,
                "led parameters not set for ecg: 5",
            ),
            (
                "/cdg/daliLines/0/daliEcgs/5/ledParams207/dimmCurve",
                json!("SQUARE"),
                "led parameters invalid for ecg: 5",
            ),
            (
                "/cdg/daliLines/0/daliEcgs/3/commonReadOnlyParams102",
                Value::Null,
                "emergency parameters not set for ecg: 3",
            ),
            (
                "/cdg/daliLines/0/daliEcgs/3/commonParams102/minimumLevel",
                json!(256),
                "common parameters invalid for ecg: 3",
            ),
        ] {
            let mut broken = model.clone();
            *broken.pointer_mut(pointer).unwrap() = value;
            assert_eq!(
                typed_deploy_plan(&broken, (true, true), None).unwrap_err(),
                warning
            );
        }
    }

    /// Wire request for one typed setter on line A.
    fn setter_wire(operation: u8, payload: &[u8]) -> Vec<u8> {
        let mut cal = vec![0xe0 + 3 + payload.len() as u8, 0x81, 0xda, operation];
        cal.extend_from_slice(payload);
        format!("\\061400{}\r", hex::encode_upper(cal)).into_bytes()
    }

    async fn install_deploy_model(service: &Arc<Service>) {
        let mut state = service.dali_state.lock().await;
        let session = state.sessions.get_mut("work").unwrap();
        *session
            .model
            .pointer_mut("/cdg/daliLines/0/daliEcgs")
            .unwrap() = deploy_model();
        session.model_dirty = true;
    }

    const DEPLOY_WIRE: [(u8, &str); 7] = [
        (32, "03010201FEFDC8"),
        (32, "05000002FAFFFF"),
        (34, "030AFFFFFFFFFFFFFF"),
        (34, "05FFFFFFFFFFFFFFFF"),
        (35, "03FF1EFFFFFFFFFFFF"),
        (35, "05FFFFFFFFFFFFFFFF"),
        (40, "0501"),
    ];

    #[tokio::test(start_paused = true)]
    async fn dali_only_deploy_writes_the_native_sequence_once_and_clears_model_dirty() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        install_deploy_model(&service).await;
        let request = spawn_command(
            &service,
            "[d] DALI SESSION DEPLOY work !dali-gateway-20 A DALI_ONLY",
        );
        for (operation, payload) in DEPLOY_WIRE {
            assert_eq!(
                line(&mut remote).await,
                setter_wire(operation, &hex::decode(payload).unwrap())
            );
            dali_success(&mut remote, operation, &[]).await;
        }
        assert_eq!(line(&mut remote).await, setter_wire(38, &[3, 180, 4, 7]));
        // A busy gateway is polled with the default budget, never re-executed.
        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, 38, 2]).await;
        assert_eq!(line(&mut remote).await, b"\\061400E382DA26\r");
        dali_success(&mut remote, 38, &[]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response
                .lines
                .iter()
                .filter(|line| line.starts_with("120-progress"))
                .cloned()
                .collect::<Vec<_>>(),
            [
                "120-progress: 1/4, plan: SET_COMMON_PARAMS_ECG",
                "120-progress: 2/4, plan: SET_SCENE_VALUES_ECG",
                "120-progress: 3/4, plan: SET_LED_PARAMS_ECG",
                "120-progress: 4/4, plan: SET_EMERGENCY_PARAMS_ECG",
            ]
        );
        let session = service.dali_state.lock().await.sessions["work"].clone();
        assert!(!session.model_dirty);
        assert_eq!(session.target_cdg.as_deref(), Some("!dali-gateway-20"));
        let journal = &journals(&path)[0];
        assert_eq!(journal["state"], "complete");
        assert_eq!(journal["confirmed_writes"], 8);
        assert_eq!(journal["planned"][7]["payload_hex"], "03B40407");
        no_more_frames(&mut remote, "typed deploy read back or replayed a write").await;
        cleanup(path);
    }

    #[tokio::test(start_paused = true)]
    async fn typed_deploy_stops_at_each_fault_without_rollback_or_replay() {
        for fault in 0..=DEPLOY_WIRE.len() {
            // Alternate a definite rejection with an exhausted IN_PROGRESS
            // (uncertain) reply and a reconnect (uncertain).
            let kind = fault % 3;
            let (service, mut remote, path) = setup().await;
            new_session(&service).await;
            install_deploy_model(&service).await;
            let request = spawn_command(
                &service,
                "[d] DALI SESSION DEPLOY work !dali-gateway-20 A DALI_ONLY",
            );
            let wire = DEPLOY_WIRE
                .iter()
                .map(|(operation, payload)| (*operation, hex::decode(payload).unwrap()))
                .chain([(38, vec![3, 180, 4, 7])])
                .collect::<Vec<_>>();
            for (index, (operation, payload)) in wire.iter().enumerate() {
                assert_eq!(line(&mut remote).await, setter_wire(*operation, payload));
                if index < fault {
                    dali_success(&mut remote, *operation, &[]).await;
                    continue;
                }
                match kind {
                    0 => reply(&mut remote, 20, &[0xe4, 0x83, 0xda, *operation, 4]).await,
                    1 => {
                        reply(&mut remote, 20, &[0xe4, 0x83, 0xda, *operation, 1]).await;
                        for _ in 0..10 {
                            line(&mut remote).await;
                            reply(&mut remote, 20, &[0xe4, 0x83, 0xda, *operation, 1]).await;
                        }
                    }
                    _ => {
                        service.pci_generation.fetch_add(1, Ordering::AcqRel);
                        dali_success(&mut remote, *operation, &[]).await;
                    }
                }
                break;
            }
            let response = request.await.unwrap();
            let expected_status = if kind == 2 { 503 } else { 502 };
            assert_eq!(
                response.status, expected_status,
                "fault {fault}: {response:?}"
            );
            assert!(
                response
                    .final_text
                    .contains(&format!("{fault} of 8 planned device writes confirmed")),
                "fault {fault}: {response:?}"
            );
            assert!(response
                .final_text
                .contains("nothing was rolled back or replayed"));
            let journal = &journals(&path)[0];
            assert_eq!(journal["confirmed_writes"], fault);
            assert_eq!(
                journal["state"],
                if kind == 0 {
                    "failed"
                } else {
                    "outcome_uncertain"
                },
                "fault {fault}"
            );
            let session = service.dali_state.lock().await.sessions["work"].clone();
            assert!(
                session.model_dirty,
                "a partial deploy must keep the model dirty"
            );
            no_more_frames(
                &mut remote,
                "typed deploy continued, rolled back or replayed",
            )
            .await;
            cleanup(path);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn typed_deploy_refuses_invalid_models_before_io() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        install_deploy_model(&service).await;
        {
            let mut state = service.dali_state.lock().await;
            let session = state.sessions.get_mut("work").unwrap();
            // The first ECG is valid; native would write it before failing.
            session.model["cdg"]["daliLines"][0]["daliEcgs"][5]["commonParams102"] = Value::Null;
        }
        let response = service
            .handle(
                &mut ClientState::default(),
                "[d] DALI SESSION DEPLOY work !dali-gateway-20 A DALI_ONLY",
            )
            .await;
        assert_eq!(response.status, 501, "{response:?}");
        assert_eq!(response.lines, ["common parameters not set for ecg: 5"]);
        assert!(response.final_text.contains("no bus command was sent"));

        {
            let mut state = service.dali_state.lock().await;
            let session = state.sessions.get_mut("work").unwrap();
            *session
                .model
                .pointer_mut("/cdg/daliLines/0/daliEcgs")
                .unwrap() =
                json!([{"shortAddress": 3, "isKnown": true}, {"shortAddress": 3, "isKnown": true}]);
        }
        let duplicate = service
            .handle(
                &mut ClientState::default(),
                "[d] DALI SESSION DEPLOY work !dali-gateway-20 A FULL",
            )
            .await;
        assert_eq!(duplicate.status, 501);
        assert!(duplicate.final_text.contains("duplicate ECG addresses"));

        install_deploy_model(&service).await;
        service
            .dali_state
            .lock()
            .await
            .sessions
            .get_mut("work")
            .unwrap()
            .catalog_dirty = true;
        let catalogue = service
            .handle(
                &mut ClientState::default(),
                "[d] DALI SESSION DEPLOY work !dali-gateway-20 A FULL",
            )
            .await;
        assert_eq!(catalogue.status, 501, "{catalogue:?}");
        assert!(catalogue
            .final_text
            .contains("extended-proxy serialization"));
        assert!(journals(&path).is_empty());
        no_more_frames(&mut remote, "a refused typed deploy emitted PCI bytes").await;
        cleanup(path);
    }

    #[tokio::test(start_paused = true)]
    async fn full_deploy_runs_the_extended_writer_after_the_typed_steps() {
        let (service, mut remote, path) = setup().await;
        new_session(&service).await;
        {
            let mut state = service.dali_state.lock().await;
            let session = state.sessions.get_mut("work").unwrap();
            *session
                .model
                .pointer_mut("/cdg/daliLines/0/daliEcgs")
                .unwrap() = json!([null, null, null, null, null, deploy_model()[5].clone()]);
            session.stage_ext(256, &[0xaa]).unwrap();
        }
        let request = spawn_command(
            &service,
            "[d] DALI SESSION DEPLOY work !dali-gateway-20 A FULL",
        );
        for (operation, payload) in [
            (32, "05000002FAFFFF"),
            (34, "05FFFFFFFFFFFFFFFF"),
            (35, "05FFFFFFFFFFFFFFFF"),
            (40, "0501"),
        ] {
            assert_eq!(
                line(&mut remote).await,
                setter_wire(operation, &hex::decode(payload).unwrap())
            );
            dali_success(&mut remote, operation, &[]).await;
        }
        drive_one_byte_ext_store_to_readback(&mut remote, 0xaa).await;
        reply(&mut remote, 20, &[0x82, 0, 0xaa]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert!(response
            .lines
            .iter()
            .any(|line| line == "300-[WARN] no commands sent - no known ecgs"));
        assert!(response
            .lines
            .iter()
            .any(|line| line == "120-progress: 5/5, plan: WRITE_GATEWAY_EXT_FULL"));
        let session = service.dali_state.lock().await.sessions["work"].clone();
        assert_eq!(session.ext.as_json()["values"]["256"], 0xaa);
        assert!(session.ext.dirty_chunks().is_empty());
        let journal = &journals(&path)[0];
        assert_eq!(journal["confirmed_writes"], 5);
        assert_eq!(journal["planned"][4]["step"], "WRITE_GATEWAY_EXT_FULL");
        no_more_frames(&mut remote, "FULL deploy replayed a write").await;
        cleanup(path);
    }
}
