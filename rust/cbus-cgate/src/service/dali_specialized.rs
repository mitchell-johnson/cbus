//! Native-evidenced C-Gate 3.4 DALI gateway, parameter, catalogue, and
//! commissioning-session commands.
//!
//! Direct memory commands use the shared PCI programming lane. The volatile
//! extended-parameter maps and active sessions are committed only after the
//! PCI generation is revalidated, so a reconnect can never make an old read
//! look current or replay an uncertain write.

use super::*;
use cbus_protocol::dali::{parse_mask, DaliCalMode, DaliLine};
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

    fn commit_chunk(&mut self, address: u32, bytes: &[u8]) {
        for (offset, byte) in bytes.iter().copied().enumerate() {
            let logical = address + offset as u32;
            self.values[(logical - EXT_START) as usize] = Some(byte);
            self.targets.remove(&logical);
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
    name: String,
    project: String,
    source_cdg: Option<String>,
    source_unit: Option<String>,
    target_cdg: Option<String>,
    target_unit: Option<String>,
    model: Value,
    ext: ExtendedMap,
    model_dirty: bool,
}

impl DaliSession {
    fn new(name: &str, project: &str, oid: &str) -> Self {
        Self {
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
            model_dirty: false,
        }
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
        })
    }

    fn load_saved(&mut self, saved: &Value) {
        if let Some(model) = saved.get("model") {
            self.model = model.clone();
            self.ext = model
                .get("extParams")
                .map(ExtendedMap::from_json)
                .unwrap_or_default();
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
            session.ext.values.fill(None);
            // A reconnect while a verified write is crossing the service
            // commit boundary makes the remaining staged set ambiguous.
            // Dropping it is the only safe no-replay behavior.
            session.ext.targets.clear();
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
        match session.ext.stage(address, &bytes) {
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
        if let Err(response) = session_line(tag, &args[2]) {
            return response;
        }
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
        if let Some(range) = args.get(4) {
            if let Err(response) = ecg_range(tag, range) {
                return response;
            }
        }
        if extract_type != "EXT_ONLY" {
            return err(
                tag,
                502,
                "502 DALI session extraction plan is not evidenced for this selector; no bus command was sent",
            );
        }
        if !self.dali_state.lock().await.sessions.contains_key(&args[0]) {
            return err(
                tag,
                501,
                &format!("501 session name does not exist: {}", args[0]),
            );
        }
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
        session.ext.replace(bytes);
        session.source_cdg = Some(args[1].clone());
        session.model_dirty = false;
        ok(tag, vec!["120-start extraction".to_string()], "200 OK.")
    }

    async fn dali_session_deploy(&self, tag: &str, args: &[String]) -> Response {
        if !(4..=5).contains(&args.len()) {
            return syntax(tag);
        }
        if let Err(response) = session_line(tag, &args[2]) {
            return response;
        }
        let deploy_type = args[3].to_ascii_uppercase();
        if !matches!(deploy_type.as_str(), "EXT_ONLY" | "DALI_ONLY" | "FULL") {
            return err(
                tag,
                400,
                &format!("400 failed parse <deploy-type>: {}", args[3]),
            );
        }
        if let Some(range) = args.get(4) {
            if let Err(response) = ecg_range(tag, range) {
                return response;
            }
        }
        if deploy_type != "EXT_ONLY" {
            return err(
                tag,
                502,
                "502 DALI session deployment plan is not evidenced for this selector; no bus command was sent",
            );
        }
        let (chunks, model_dirty) = {
            let state = self.dali_state.lock().await;
            let Some(session) = state.sessions.get(&args[0]) else {
                return err(
                    tag,
                    501,
                    &format!("501 session name does not exist: {}", args[0]),
                );
            };
            (session.ext.dirty_chunks(), session.model_dirty)
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
            session.ext.commit_chunk(*address, bytes);
        }
        if let Some(session) = self.dali_state.lock().await.sessions.get_mut(&args[0]) {
            session.target_cdg = Some(args[1].clone());
        }
        ok(tag, vec!["120-start deploy".to_string()], "200 OK.")
    }
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
    async fn unevidenced_typed_session_plan_refuses_before_io() {
        let (service, mut remote, path) = setup().await;
        let mut client = ClientState::default();
        assert_eq!(
            service
                .handle(&mut client, "[n] DALI SESSION NEW work")
                .await
                .status,
            200
        );
        let response = service
            .handle(
                &mut client,
                "[x] DALI SESSION EXTRACT work !dali-gateway-20 A FULL",
            )
            .await;
        assert_eq!(response.status, 502);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut remote))
                .await
                .is_err(),
            "unsupported selector emitted PCI bytes"
        );
        std::fs::remove_file(path).unwrap();
    }
}
