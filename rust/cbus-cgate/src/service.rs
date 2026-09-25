//! Hardware-backed C-Gate service embedded by cmqttd. The in-memory mock is
//! deliberately not the fallback for unimplemented physical operations.

use super::*;
use crate::auth;
use cbus_protocol::{
    packet::{Meta, Packet},
    sal::{aircon::AirconCommand, label, Sal},
    serial_address::parse_native_serial,
};
use cbus_transport::pci::{CBusEvent, GocProgramming, PciClient};
use chrono::{Datelike, Local, NaiveDate, NaiveTime, Timelike};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashMap, HashSet, VecDeque},
    io::{self, Write},
    path::Path,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, OnceLock,
    },
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    sync::{broadcast, Mutex, RwLock, Semaphore},
};

const MAX_LINE: usize = 1024 * 1024;
const MAX_DOCUMENT: usize = 16 * 1024 * 1024;
const MAX_STATE: usize = 32 * 1024 * 1024;
const MAX_LABEL_OBSERVATIONS: usize = 4096;

const AIRCON_HELP: &[&str] = &[
    "Help: AIRCON commands:",
    "Help:  AIRCON ? Help for these commands",
    "Help:  AIRCON REFRESH - Send a refresh request to the air-conditioning ward",
    "Help:  AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT - Sets the absolute minimum humidity allowed in the Zone.",
    "Help:  AIRCON SET_HUMIDITY_SETBACK_LIMIT - Sets the error allowed in the set humidity for the Zone. ",
    "Help:  AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT - Sets the absolute maximum humidity allowed in the Zone.",
    "Help:  AIRCON SET_HVAC_LOWER_GUARD_LIMIT - Sets the absolute minimum temperature allowed in the Zone.",
    "Help:  AIRCON SET_HVAC_SETBACK_LIMIT - Sets the error allowed in the set temperature for the Zone. ",
    "Help:  AIRCON SET_HVAC_UPPER_GUARD_LIMIT - Sets the absolute maximum temperature allowed in the Zone.",
    "Help:  AIRCON SET_WARD_OFF - Switches off all plant in all of the zones of the specific ward.",
    "Help:  AIRCON SET_WARD_ON - Returns the ward to its previous operational state.",
    "Help:  AIRCON SET_ZONE_HUMIDITY_MODE - Broadcast of Humidity mode and level required for a Zone or Zones.",
    "Help:  AIRCON SET_ZONE_HVAC_MODE - Broadcast of HVAC mode and level required for a Zone or Zones.",
];

/// Default bound for the TLS pre-handshake accept (matches the existing
/// 10s per-write deadlines). A stalled pre-handshake connection must not
/// hold a 64-slot semaphore permit forever.
pub const TLS_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(10);

fn goc_programming(param: &unitspec::SpecParam) -> Option<GocProgramming> {
    match param
        .get("ProgramMethod")
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase()
        .as_str()
    {
        "goc" => Some(GocProgramming::Goc),
        "gocbyt" => Some(GocProgramming::GocByt),
        "goc2" => Some(GocProgramming::Goc2),
        _ => None,
    }
}

#[cfg(test)]
mod tests;

/// Durable database only. Connections, locks, staged PP sessions and observed
/// bus levels are deliberately excluded and cannot masquerade as live on boot.
#[derive(Serialize, Deserialize, PartialEq)]
struct Database {
    version: u32,
    projects: HashMap<String, Project>,
    db_fields: HashMap<String, String>,
    objects: HashSet<String>,
    known_oids: HashSet<String>,
    db_levels: HashMap<String, DbLevel>,
    config_values: HashMap<String, String>,
    scene_snapshots: HashMap<String, Vec<(String, u8)>>,
    database_files: HashMap<String, Project>,
    file_store: HashMap<String, Vec<u8>>,
}

impl Database {
    fn from_server(s: &Server) -> Self {
        Self {
            version: 1,
            projects: s.projects.clone(),
            db_fields: s.db_fields.clone(),
            objects: s.objects.clone(),
            known_oids: s.known_oids.clone(),
            db_levels: s.db_levels.clone(),
            config_values: s.config_values.clone(),
            scene_snapshots: s.scene_snapshots.clone(),
            database_files: s.database_files.clone(),
            file_store: s.file_store.clone(),
        }
    }

    fn restore(mut self, s: &mut Server) -> io::Result<bool> {
        if self.version != 1 {
            return Err(io::Error::other("unsupported C-Gate database version"));
        }
        let mut used_oids = self.known_oids.clone();
        for project in self.projects.values().chain(self.database_files.values()) {
            for network in project.networks.values() {
                if !network.oid.is_empty() {
                    used_oids.insert(network.oid.clone());
                }
            }
        }
        let mut migrated_network_oids = false;
        for project in self
            .projects
            .values_mut()
            .chain(self.database_files.values_mut())
        {
            for network in project.networks.values_mut() {
                if network.oid.is_empty() {
                    loop {
                        let oid = fresh_oid();
                        if used_oids.insert(oid.clone()) {
                            network.oid = oid;
                            migrated_network_oids = true;
                            break;
                        }
                    }
                }
            }
        }
        s.projects = self.projects;
        s.db_fields = self.db_fields;
        s.objects = self.objects;
        // Network OIDs are first-class database identities. Legacy state did
        // not list them in known_oids, so use the union assembled above for
        // both migrated and already-populated network records.
        s.known_oids = used_oids;
        s.db_levels = self.db_levels;
        s.config_values = self.config_values;
        s.scene_snapshots = self.scene_snapshots;
        s.database_files = self.database_files;
        s.file_store = self.file_store;
        Ok(migrated_network_oids)
    }

    fn save(&self, path: &Path) -> io::Result<()> {
        let data = serde_json::to_vec(self)?;
        if data.len() > MAX_STATE {
            return Err(io::Error::other("C-Gate database exceeds 32 MiB"));
        }
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        std::fs::create_dir_all(parent)?;
        static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let temp = parent.join(format!(
            ".cmqttd-{}-{}.tmp",
            std::process::id(),
            SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let result = (|| {
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&temp)?;
            file.write_all(&data)?;
            file.sync_all()?;
            std::fs::rename(&temp, path)?;
            #[cfg(unix)]
            std::fs::File::open(parent)?.sync_all()?;
            Ok(())
        })();
        if result.is_err() {
            let _ = std::fs::remove_file(temp);
        }
        result
    }
}

/// State private to one command connection.
#[derive(Default)]
pub struct ClientState {
    current: Option<String>,
    locks: HashSet<String>,
    sessions: HashSet<String>,
    /// Native-style command-session identifier assigned by the TCP/TLS
    /// listener. Direct `Service::handle` callers have no command session.
    command_session: Option<u64>,
    /// Session-local LOGIN flag for the optional shared-secret gate (auth
    /// first-slice). `false` until a correct `LOGIN` on this connection;
    /// cleared by `LOGOUT` or a failed `LOGIN`. Dormant (`false` forever
    /// and never consulted) when no auth file is configured.
    authenticated: bool,
    /// Consecutive failed LOGIN attempts on this connection (saturating).
    /// Recorded for future rate-limiting; no cap is enforced in this slice.
    login_attempts: u32,
}

/// One real, explicitly selected C-Bus network, shared with the MQTT gateway.
pub struct Service {
    model: Mutex<Server>,
    pci: RwLock<Arc<PciClient>>,
    /// Replacement epoch for operations that build a live snapshot outside
    /// the model lock. A reconnect invalidates every in-flight snapshot.
    pci_generation: AtomicU64,
    /// Serializes PCI replacement with the final generation check and commit.
    pci_generation_gate: Mutex<()>,
    project: String,
    network: u8,
    state_path: PathBuf,
    events: broadcast::Sender<String>,
    observed_labels: Mutex<ObservedLabels>,
    command_sessions: Mutex<CommandSessions>,
    // Serialize command intents without preventing readback/event processing.
    commands: Mutex<()>,
    /// SHA-256 digest of the optional shared-secret LOGIN token. `None`
    /// (unset) means the gate is dormant and `handle` is byte-identical to
    /// the pre-auth behavior. Set once at startup from
    /// `--cgate-auth-file` via [`Service::set_auth_token_hash`].
    auth_token_hash: OnceLock<[u8; 32]>,
}

#[derive(Clone, Serialize)]
struct LabelObservation {
    sequence: u64,
    direction: String,
    source_unit: Option<u8>,
    application: u8,
    payload_hex: String,
}

#[derive(Default)]
struct ObservedLabels {
    next_sequence: u64,
    observations: VecDeque<LabelObservation>,
}

#[derive(Clone)]
struct CommandSession {
    origin: String,
    connected_at: String,
    tag: Option<String>,
}

/// Live command sessions are endpoint state, not durable C-Gate database
/// state. Native C-Gate allocates odd-numbered `cmdN` identifiers to command
/// connections (the intervening identifiers belong to its other interfaces),
/// so this service preserves that externally visible sequence shape.
struct CommandSessions {
    next_id: u64,
    sessions: BTreeMap<u64, CommandSession>,
}

impl Default for CommandSessions {
    fn default() -> Self {
        Self {
            // Native C-Gate reserves cmd1 for its internal console. cmqttd has
            // no console session to report, so the first real client is cmd3.
            next_id: 3,
            sessions: BTreeMap::new(),
        }
    }
}

impl CommandSessions {
    fn register(&mut self, origin: String) -> u64 {
        loop {
            let id = self.next_id;
            self.next_id = self.next_id.checked_add(2).unwrap_or(3);
            if let std::collections::btree_map::Entry::Vacant(slot) = self.sessions.entry(id) {
                slot.insert(CommandSession {
                    origin,
                    connected_at: Local::now().format("%Y%m%d-%H%M%S").to_string(),
                    tag: None,
                });
                return id;
            }
        }
    }
}

#[derive(Clone, Copy)]
struct ClockSummary {
    address: u8,
    enabled: bool,
    active: bool,
    burden: bool,
}

impl Service {
    /// Import the supplied project on first start; thereafter load the atomic
    /// database. A corrupt or mismatched database is an error, never reset.
    pub fn new(
        xml: &str,
        network_name: Option<&str>,
        state_path: PathBuf,
        pci: Arc<PciClient>,
        unitspec: Option<PathBuf>,
    ) -> io::Result<Arc<Self>> {
        let (mut model, project, network) = import_project(xml, network_name)?;
        if let Some(dir) = unitspec {
            model = model.with_unitspec_dir(dir);
        }
        match std::fs::read(&state_path) {
            Ok(data) => {
                if data.len() > MAX_STATE {
                    return Err(io::Error::other("C-Gate database exceeds 32 MiB"));
                }
                let migrated = serde_json::from_slice::<Database>(&data)?.restore(&mut model)?;
                if migrated {
                    Database::from_server(&model).save(&state_path)?;
                }
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                Database::from_server(&model).save(&state_path)?
            }
            Err(e) => return Err(e),
        }
        let selected = model
            .projects
            .get_mut(&project)
            .and_then(|p| p.networks.get_mut(&network))
            .ok_or_else(|| {
                io::Error::other("configured network is absent from persisted C-Gate database")
            })?;
        selected.state = NetworkState::Open;
        open_reachable_networks(&mut model, &project, network);
        Ok(Arc::new(Self {
            model: Mutex::new(model),
            pci: RwLock::new(pci),
            pci_generation: AtomicU64::new(0),
            pci_generation_gate: Mutex::new(()),
            project,
            network,
            state_path,
            events: broadcast::channel(512).0,
            observed_labels: Mutex::new(ObservedLabels::default()),
            command_sessions: Mutex::new(CommandSessions::default()),
            commands: Mutex::new(()),
            auth_token_hash: OnceLock::new(),
        }))
    }

    /// Arm the optional shared-secret LOGIN gate with the SHA-256 digest of
    /// the configured token (see [`auth::load_token_hash`]). Called once at
    /// startup after the auth file has loaded fail-closed and before the
    /// listener binds. Fails if a hash was already installed.
    pub fn set_auth_token_hash(&self, hash: [u8; 32]) -> Result<(), [u8; 32]> {
        self.auth_token_hash.set(hash)
    }

    /// Replace the shared PCI after cmqttd reconnects; invalidate all live data.
    pub async fn set_pci(&self, pci: Arc<PciClient>) {
        let _generation_gate = self.pci_generation_gate.lock().await;
        self.pci_generation.fetch_add(1, Ordering::AcqRel);
        self.observe(&CBusEvent::ConnectionLost).await;
        *self.pci.write().await = pci;
        let mut model = self.model.lock().await;
        open_reachable_networks(&mut model, &self.project, self.network);
    }

    /// Feed genuine bus observations to C-Gate clients as well as MQTT.
    pub async fn observe(&self, event: &CBusEvent) {
        match event {
            CBusEvent::DynamicLabel {
                source,
                application,
                payload,
            } => {
                self.record_label("received", *source, *application, payload)
                    .await;
            }
            CBusEvent::ConnectionLost => self.observed_labels.lock().await.observations.clear(),
            _ => {}
        }
        let mut model = self.model.lock().await;
        if matches!(event, CBusEvent::ConnectionLost) {
            if let Some(project) = model.projects.get_mut(&self.project) {
                for network in project.networks.values_mut() {
                    network.levels.clear();
                    network.physical.clear();
                    network.state = NetworkState::Closed;
                }
            }
            model.application_state.clear();
            return;
        }
        let Some(net) = model
            .projects
            .get_mut(&self.project)
            .and_then(|p| p.networks.get_mut(&self.network))
        else {
            return;
        };
        let mut updates = Vec::new();
        let mut application_update = None;
        match event {
            CBusEvent::AirconCommand { source, command } => {
                let source = source.unwrap_or(0);
                let _ = self.events.send(format!(
                    "#e# aircon {} //{}/{}/172 {} sourceUnit={source}",
                    command.event_name(),
                    self.project,
                    self.network,
                    command.event_arguments()
                ));
            }
            CBusEvent::AirconStatus { source, status } => {
                let source = source.unwrap_or(0);
                let _ = self.events.send(format!(
                    "#e# aircon {} //{}/{}/172 {} sourceUnit={source}",
                    status.event_name(),
                    self.project,
                    self.network,
                    status.event_arguments()
                ));
            }
            CBusEvent::LightingOn {
                source: Some(_),
                app,
                group,
            } => updates.push((*app, *group, 255)),
            CBusEvent::LightingOff {
                source: Some(_),
                app,
                group,
            } => updates.push((*app, *group, 0)),
            CBusEvent::LightingRamp {
                source: Some(_),
                app,
                group,
                duration: 0,
                level,
            } => updates.push((*app, *group, *level)),
            CBusEvent::LightingRamp {
                source: Some(_),
                app,
                group,
                ..
            } => {
                net.levels.remove(&(*app, *group));
            }
            CBusEvent::LevelReport {
                app,
                block_start,
                levels,
            } => {
                for (i, value) in levels.iter().enumerate() {
                    if let (Some(group), Some(value)) = (
                        usize::from(*block_start)
                            .checked_add(i)
                            .filter(|g| *g <= 255),
                        value,
                    ) {
                        updates.push((*app, group as u8, *value));
                    }
                }
            }
            CBusEvent::BinaryReport {
                app,
                block_start,
                states,
            } => {
                for (i, value) in states.iter().enumerate() {
                    if usize::from(*block_start) + i <= 255 {
                        let group = block_start.wrapping_add(i as u8);
                        if *value == 2 {
                            updates.push((*app, group, 0));
                        } else if *value == 1 && net.levels.get(&(*app, group)) == Some(&0) {
                            net.levels.remove(&(*app, group));
                        }
                    }
                }
            }
            CBusEvent::TriggerEvent {
                source: Some(source),
                group,
                selector,
            } => {
                net.levels.insert((202, *group), *selector);
                let _ = self.events.send(format!(
                    "#e# trigger //{}/{}/202/{group} event action={selector} sourceUnit={source}",
                    self.project, self.network
                ));
            }
            CBusEvent::TriggerIndicatorKill {
                source: Some(source),
                group,
            } => {
                let _ = self.events.send(format!(
                    "#e# trigger //{}/{}/202/{group} indicatorkill action=-1 sourceUnit={source}",
                    self.project, self.network
                ));
            }
            CBusEvent::EnableSet {
                source: Some(source),
                variable,
                value,
            } => {
                net.levels.insert((203, *variable), *value);
                let _ = self.events.send(format!(
                    "#e# enable //{}/{}/203/{variable} set value={value} sourceUnit={source}",
                    self.project, self.network
                ));
            }
            CBusEvent::ClockDate {
                year, month, day, ..
            } => {
                application_update = Some((
                    "CLOCK DATE".to_string(),
                    format!("{year:04}-{month:02}-{day:02}"),
                ));
            }
            CBusEvent::ClockTime {
                hour,
                minute,
                second,
                ..
            } => {
                application_update = Some((
                    "CLOCK TIME".to_string(),
                    format!("{hour:02}:{minute:02}:{second:02}"),
                ));
            }
            CBusEvent::TemperatureBroadcast {
                source,
                group,
                temperature,
            } => {
                let address = format!("//{}/{}/25/{group}", self.project, self.network);
                let value = format_temperature(*temperature);
                application_update = Some((
                    "TEMPERATURE BROADCAST".to_string(),
                    format!("{address} {value}"),
                ));
                let source = source.map_or_else(|| "0".to_string(), |value| value.to_string());
                let _ = self.events.send(format!(
                    "#e# temperature broadcast {address} {value} sourceUnit={source}"
                ));
            }
            _ => {}
        }
        for (app, group, value) in updates {
            net.levels.insert((app, group), value);
            let _ = self.events.send(format!(
                "#e# lighting //{}/{}/{app}/{group} level={value}",
                self.project, self.network
            ));
        }
        if let Some((key, value)) = application_update {
            model.application_state.insert(key, value);
        }
    }

    async fn record_label(
        &self,
        direction: &str,
        source_unit: Option<u8>,
        application: u8,
        payload: &[u8],
    ) {
        let mut labels = self.observed_labels.lock().await;
        let sequence = labels.next_sequence;
        labels.next_sequence = labels.next_sequence.wrapping_add(1);
        if labels.observations.len() == MAX_LABEL_OBSERVATIONS {
            labels.observations.pop_front();
        }
        labels.observations.push_back(LabelObservation {
            sequence,
            direction: direction.to_string(),
            source_unit,
            application,
            payload_hex: hex::encode(payload),
        });
    }

    fn bound_group(&self, address: &str) -> Option<(u8, u8)> {
        if address.starts_with('!') {
            return None;
        }
        let parts: Vec<_> = address.trim_start_matches('/').split('/').collect();
        let [project, network, application, group] = parts.as_slice() else {
            return None;
        };
        let network = network.parse::<u8>().ok()?;
        let application = parse_application(application)?;
        let group = group.parse::<u8>().ok()?;
        (*project == self.project && network == self.network).then_some((application, group))
    }

    fn bound_network(&self, address: &str) -> bool {
        let parts: Vec<_> = address.trim_start_matches('/').split('/').collect();
        match parts.as_slice() {
            [network] => network.parse::<u8>() == Ok(self.network),
            [project, network] => {
                *project == self.project && network.parse::<u8>() == Ok(self.network)
            }
            _ => false,
        }
    }

    fn addressed_network(&self, address: &str) -> Option<u8> {
        if address.starts_with('!') {
            return None;
        }
        let parts = address
            .trim_start_matches('/')
            .split('/')
            .collect::<Vec<_>>();
        match parts.as_slice() {
            [network] => network.parse::<u8>().ok(),
            [project, network] if *project == self.project => network.parse::<u8>().ok(),
            _ => None,
        }
    }

    async fn route_to_network(&self, target: u8) -> Result<Vec<u8>, String> {
        let model = self.model.lock().await;
        let project = model
            .projects
            .get(&self.project)
            .ok_or_else(|| "configured project is absent".to_string())?;
        network_path(project, self.network, target)
    }

    /// Execute a tagged command. Hardware work releases the database mutex.
    pub async fn handle(&self, client: &mut ClientState, line: &str) -> Response {
        let cmd = match parse_command(line) {
            Ok(c) => c,
            Err(e) => return err("", 400, &format!("400 {e}")),
        };
        let words: Vec<&str> = cmd.body.split_whitespace().collect();
        let upper: Vec<String> = words.iter().map(|s| s.to_ascii_uppercase()).collect();
        let tag = &cmd.tag;
        let verb = upper.first().map(String::as_str).unwrap_or("");
        let sub = upper.get(1).map(String::as_str).unwrap_or("");
        if verb == "SESSION_ID" {
            return self.session_id(client, tag, &words, &upper).await;
        }
        if verb == "QUIT" || verb == "EXIT" {
            return if words.len() == 1 {
                Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: "204 Closing connection.".to_string(),
                    status: 204,
                }
            } else {
                err(tag, 400, "400 Syntax Error.")
            };
        }
        // Optional cmqttd-local shared-secret gate (auth first-slice).
        // Dormant when no --cgate-auth-file is configured: LOGIN/LOGOUT
        // fall through to the generic 502 exactly as before, and no verb
        // is gated. Armed: LOGIN/LOGOUT are session-local (no PCI I/O)
        // and the mutating set in requires_programming_auth() needs the
        // per-connection flag. NOT native access.txt parity.
        if self.auth_token_hash.get().is_some() {
            if verb == "LOGIN" || verb == "LOGOUT" {
                return self.session_auth(client, tag, &words);
            }
            if !client.authenticated && requires_programming_auth(verb, sub, &upper) {
                return err(tag, 420, "420 LOGIN required");
            }
        }
        if verb == "CMQTT" && sub == "CAPABILITIES" && words.len() == 2 {
            let mut capabilities = serde_json::json!({"service":"cmqttd", "physical_bus":true,
                "full_cgate_compatibility":false, "memory_read":true, "memory_write":true,
                "physical_pp_load":true, "physical_pp_save":true,
                "physical_pp_save_cbus3_nvm":true,
                "physical_pp_save_methods":["dali","direct","edlt","giu","goc","goc2","gocbyt","ncc","paged","sgiu"],
                "physical_pp_save_protection":["none","checksum","lock"],
                "physical_pp_save_lock_methods":["direct","ncc","paged"],
                "pp_reset_to_defaults":true,
                "trigger_control":true, "enable_control":true, "clock_control":true,
                "temperature_broadcast":true,
                "dynamic_labels":true,
                "dynamic_label_observation":true,
                "dynamic_label_device_readback":false,
                "dynamic_label_families":["enable","lighting","trigger"],
                "dynamic_label_modes":["dynamic_icon","icon","language","raw","unicode"],
                "edlt_label_clear":true,
                "edlt_factory_default":true,
                "named_scenes":true,
                "do_methods":["factorydefault","lighting","sync"],
                "network_clocks":true,
                "install_mmi":true, "network_pingu":true,
                "network_sync":true, "network_syncnew":true,
                "network_set_project_identify":true, "network_checkunit":true,
                "unit_readdress":true,
                "net_unravelunit_matchdb_duplicate_255":true,
                "event_subscriptions":true,
                "session_id":true,
                "quit":true,
                "project":self.project,"network":self.network,"persistent_database":true,
                // Opt-in command-layer LOGIN gate (see Service::set_auth_token_hash):
                // false with the dormant default, true once armed.
                "cgate_auth":self.auth_token_hash.get().is_some()});
            // Keep the new flat flag out of the already recursion-deep json!
            // invocation while retaining one static capability document.
            capabilities["label_kfi"] = serde_json::Value::Bool(true);
            capabilities["network_project_identify"] = serde_json::Value::Bool(true);
            capabilities["label_clear"] = serde_json::Value::Bool(true);
            capabilities["edlt_widget_groups"] = serde_json::Value::Bool(true);
            capabilities["edlt_extended_firmware"] = serde_json::Value::Bool(true);
            capabilities["edlt_applications"] = serde_json::Value::Bool(true);
            capabilities["document_framing"] = serde_json::Value::Bool(true);
            capabilities["database_documents"] = serde_json::Value::Bool(false);
            capabilities["project_archive_restore"] =
                serde_json::Value::String("cmqttd-internal".to_string());
            capabilities["project_rename_secondary"] = serde_json::Value::Bool(true);
            capabilities["project_copy"] = serde_json::Value::String("cmqttd-internal".to_string());
            capabilities["project_delete_secondary"] =
                serde_json::Value::String("cmqttd-internal".to_string());
            capabilities["repository_list"] = serde_json::Value::Bool(true);
            capabilities["repository_type"] = serde_json::Value::String("cmqttd-json".to_string());
            capabilities["cgl_import"] = serde_json::Value::Bool(false);
            capabilities["cgl_export"] = serde_json::Value::Bool(false);
            capabilities["bridged_read_only_discovery"] = serde_json::Value::Bool(true);
            capabilities["bridged_read_only_commands"] = serde_json::json!([
                "DBNETWORKPATH",
                "NET PINGU",
                "NET SYNC",
                "NET CHECKUNIT",
                "DO SYNC"
            ]);
            capabilities["bridged_network_max_hops"] = serde_json::Value::from(6);
            capabilities["aircon_control"] = serde_json::Value::Bool(true);
            capabilities["aircon_application"] = serde_json::Value::from(172);
            capabilities["aircon_delivery_semantics"] =
                serde_json::Value::String("pci-confirmed-broadcast".to_string());
            capabilities["aircon_commands"] = serde_json::json!([
                "refresh",
                "set_ward_off",
                "set_ward_on",
                "set_zone_hvac_mode",
                "set_zone_humidity_mode",
                "set_hvac_upper_guard_limit",
                "set_hvac_lower_guard_limit",
                "set_hvac_setback_limit",
                "set_humidity_upper_guard_limit",
                "set_humidity_lower_guard_limit",
                "set_humidity_setback_limit"
            ]);
            capabilities["aircon_reports"] = serde_json::json!([
                "hvac_schedule_entry",
                "humidity_schedule_entry",
                "zone_hvac_plant_status",
                "zone_humidity_plant_status",
                "zone_temperature",
                "zone_humidity",
                "set_plant_hvac_level",
                "set_plant_humidity_level"
            ]);
            capabilities["aircon_event_fanout"] = serde_json::Value::Bool(true);
            capabilities["aircon_mqtt_state"] = serde_json::Value::Bool(false);
            return ok(tag, vec![capabilities.to_string()], "200 OK");
        }
        if verb == "AIRCON" {
            if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
                return aircon_help(tag);
            }
            if !is_aircon_subcommand(sub) {
                return err(tag, 400, "400 Syntax Error.");
            }
            return self.aircon(tag, &words, sub).await;
        }
        if verb == "REPOSITORY" && sub == "LIST" {
            return self.repository_list(tag, &words);
        }
        if verb == "CMQTT" && sub == "LABELS" && words.len() == 3 {
            let address = words[2];
            // split_unit also matches attribute paths (//P/N/p/U/field), which
            // are not a network or unit scope, so require exactly four parts.
            let valid = self.bound_network(address)
                || (address.trim_start_matches('/').split('/').count() == 4
                    && Server::split_unit(address).is_some_and(|(project, network, _)| {
                        project == self.project && network == self.network
                    }));
            if !valid {
                return err(
                    tag,
                    400,
                    "400 CMQTT LABELS requires the configured network or unit",
                );
            }
            let labels = self.observed_labels.lock().await;
            return ok(
                tag,
                vec![serde_json::json!({
                    "format":"cmqttd-observed-dynamic-labels-v1",
                    "address":address,
                    "requested_address":address,
                    "project":self.project,
                    "network":self.network,
                    "source":"observed-sal-traffic",
                    "observation_scope":"network",
                    "recipient_verified":false,
                    "complete":false,
                    "device_readback":false,
                    "reset_on_reconnect":true,
                    "capacity":MAX_LABEL_OBSERVATIONS,
                    "observations":labels.observations,
                })
                .to_string()],
                "200 OK",
            );
        }
        if verb == "UNIT" && sub == "READMEM" {
            return self.read_memory(tag, &words).await;
        }
        if verb == "UNIT" && sub == "IDENTIFY" {
            if words.len() != 4 {
                return err(tag, 400, "400 UNIT IDENTIFY //PROJECT/NET/p/UNIT attribute");
            }
            let target = Server::split_unit(words[2])
                .filter(|(p, n, _)| *p == self.project && *n == self.network);
            let (Some((_, _, unit)), Ok(attribute)) = (target, words[3].parse::<u8>()) else {
                return err(tag, 400, "400 Invalid unit or attribute");
            };
            let pci = self.pci.read().await.clone();
            return match pci.identify(unit,attribute).await {
                Ok(bytes) => ok(tag,vec![serde_json::json!({"address":words[2],"attribute":attribute,"data_hex":hex::encode(bytes),"source":"physical"}).to_string()],"200 OK"),
                Err(e) => err(tag,502,&format!("502 Identify failed: {e}")),
            };
        }
        if verb == "PP"
            && sub == "LOAD"
            && words
                .get(3)
                .is_some_and(|source| !source.to_ascii_lowercase().starts_with("/db/"))
        {
            return self.pp_load_physical(client, line, tag, &words).await;
        }
        if verb == "PP"
            && sub == "SAVE"
            && words
                .get(3)
                .is_some_and(|source| !source.to_ascii_lowercase().starts_with("/db/"))
        {
            return self.pp_save_physical(client, tag, &words).await;
        }
        if verb == "PP" && sub == "SAVE_TO_SOURCE" {
            let physical = {
                let model = self.model.lock().await;
                words
                    .get(2)
                    .and_then(|name| model.sessions.get(*name))
                    .and_then(|session| session.source.as_deref())
                    .is_some_and(|source| !source.to_ascii_lowercase().starts_with("/db/"))
            };
            if physical {
                return self.pp_save_physical(client, tag, &words).await;
            }
        }
        if verb == "CMQTT" && sub == "UNIT" && words.len() == 3 {
            let model = self.model.lock().await;
            let unit = Server::split_unit(words[2])
                .filter(|(p, n, _)| *p == self.project && *n == self.network)
                .and_then(|(p, n, u)| model.projects.get(&p)?.networks.get(&n)?.units.get(&u));
            return match unit {
                Some(u) => ok(tag, vec![serde_json::json!({"address":words[2],"unit_type":u.unit_type,"firmware":u.firmware,"serial":u.serial,"name":u.fields.get("TagName"),"source":"database"}).to_string()], "200 OK"),
                None => err(tag,404,"404 Unit is not in the configured project"),
            };
        }
        if matches!(verb, "LIGHTING" | "TRIGGER" | "ENABLE")
            && matches!(sub, "LABEL" | "UNICODELABEL")
        {
            return self.label(client, line, tag, &words, &upper).await;
        }
        if verb == "LABEL" && sub == "CLEAR" {
            return self.clear_dynamic_label_cache(tag, &words).await;
        }
        if verb == "LABEL" && matches!(sub, "KFIGET" | "KFISET") {
            return self.label_kfi(tag, &words, &upper).await;
        }
        if verb == "LABEL" && sub == "CLEAREDLT" {
            return self.clear_edlt_labels(client, line, tag, &words).await;
        }
        if verb == "TRIGGER" && matches!(sub, "EVENT" | "INDICATORKILL") {
            return self.trigger(client, line, tag, &words).await;
        }
        if verb == "ENABLE" && matches!(sub, "SET" | "REMOVE") {
            return self.enable(client, line, tag, &words).await;
        }
        if verb == "CLOCK" && matches!(sub, "DATE" | "TIME" | "REQUEST_REFRESH") {
            return self.clock(client, line, tag, &words).await;
        }
        if verb == "TEMPERATURE" && sub == "BROADCAST" {
            return self.temperature(client, line, tag, &words).await;
        }
        if verb == "NET" && sub == "PINGU" {
            return self.net_pingu(client, line, tag, &words).await;
        }
        if verb == "NET" && sub == "PROJECT_IDENTIFY" {
            return self.net_project_identify(tag, &words).await;
        }
        if verb == "NET" && sub == "SET_PROJECT_IDENTIFY" {
            return self
                .net_set_project_identify(client, line, tag, &words)
                .await;
        }
        if verb == "NET" && sub == "SYNCNEW" {
            return self.net_syncnew(client, line, tag, &words).await;
        }
        if verb == "NET" && sub == "SYNC" {
            return self.net_sync(client, line, tag, &words).await;
        }
        if verb == "NET" && sub == "CHECKUNIT" {
            return self.net_checkunit(client, line, tag, &words).await;
        }
        if verb == "NET" && matches!(sub, "UNRAVEL" | "UNRAVELUNIT") {
            return self.net_unravel(client, line, tag, &words).await;
        }
        // Native C-Gate declares CHECK_UNRAVEL obsolete and returns 400
        // without running it. Answer likewise: no physical I/O exists.
        if verb == "NET" && sub == "CHECK_UNRAVEL" {
            return err(tag, 400, "400 NET CHECK_UNRAVEL is obsolete");
        }
        if verb == "SET"
            && words
                .get(2)
                .is_some_and(|field| field.eq_ignore_ascii_case("Address"))
        {
            return self.readdress_unit(tag, &words).await;
        }
        if verb == "SCENE" {
            return self.scene(client, line, tag, &words).await;
        }
        if verb == "DO" {
            return self.do_method(client, tag, &words).await;
        }
        if verb == "NET" && sub == "CLOCKS" {
            return self.net_clocks(tag, &words).await;
        }
        if matches!(verb, "ON" | "OFF" | "RAMP" | "TERMINATERAMP")
            || (verb == "LIGHTING"
                && matches!(sub, "ON" | "OFF" | "RAMP" | "STOP" | "TERMINATERAMP"))
        {
            return self.lighting(client, line, tag).await;
        }
        if verb == "PROJECT"
            && matches!(sub, "ARCHIVE" | "RESTORE")
            && words.len() == 4
            && !valid_internal_archive_key(words[3])
        {
            return err(
                tag,
                408,
                "408 Schneider archive files are not supported; use a cmqttd: archive key",
            );
        }
        // The selected project names the network bound to the shared PCI and
        // MQTT gateway for this Service instance. Renaming it would leave the
        // immutable hardware binding pointing at a project that no longer
        // exists. Other durable projects can be renamed locally.
        if verb == "PROJECT" && sub == "RENAME" && words.len() == 4 && words[2] == self.project {
            return err(
                tag,
                408,
                "408 The configured hardware project cannot be renamed while the service is running",
            );
        }
        if verb == "PROJECT" && sub == "DELETE" && words.len() == 3 && words[2] == self.project {
            return err(
                tag,
                408,
                "408 The configured hardware project cannot be deleted while the service is running",
            );
        }
        let mut model = self.model.lock().await;
        model.current = client
            .current
            .clone()
            .or_else(|| Some(self.project.clone()));
        if verb == "GET" && words.len() == 3 {
            if let Some(response) = self.application_get(&model, tag, words[1], words[2]) {
                return response;
            }
        }
        if matches!(verb, "GET" | "GETSTATE")
            && words
                .last()
                .is_some_and(|x| x.eq_ignore_ascii_case("level"))
        {
            let Some(address) = words.get(1).and_then(|a| model.qualify_group(a)) else {
                return err(tag, 400, "400 Invalid group");
            };
            let Some((a, g)) = self.bound_group(&address) else {
                return err(tag, 404, "404 Network is not connected to this service");
            };
            if !(48..=95).contains(&a) {
                return err(tag, 402, "402 Parameter not found");
            }
            let value = model
                .projects
                .get(&self.project)
                .and_then(|p| p.networks.get(&self.network))
                .and_then(|n| n.levels.get(&(a, g)));
            return match value {
                Some(v) => Server::property(tag, &address, "level", &v.to_string()),
                None => err(tag, 408, "408 No live level has been observed"),
            };
        }
        // Never allow a simulator-only success to stand in for physical I/O.
        if !local_command(&words, &upper, &model) {
            return err(
                tag,
                502,
                "502 Command requires a physical backend that is not implemented",
            );
        }
        if verb == "PP" {
            let name = words.get(2).copied().unwrap_or("");
            if model.sessions.contains_key(name) && !client.sessions.contains(name)
                || model.locks.contains_key(name) && !client.locks.contains(name)
            {
                return err(
                    tag,
                    420,
                    "420 Programming object belongs to another connection",
                );
            }
            if sub == "START"
                && words
                    .get(3)
                    .is_some_and(|lock| !client.locks.contains(*lock))
            {
                return err(tag, 420, "420 Lock belongs to another connection");
            }
            if sub == "RESET_TO_DEFAULTS" && words.len() == 3 {
                // The mock has a deterministic identity-only fallback when no
                // catalogue exists. The real service must never erase staged
                // parameters under that approximation: only an exact parsed
                // specification can define the native defaults.
                if let Some(session) = model.sessions.get(name) {
                    let Some(unit_type) = session.unit_type.clone() else {
                        return err(
                            tag,
                            408,
                            "408 RESET_TO_DEFAULTS requires a loaded unit specification",
                        );
                    };
                    if model.spec_for(&unit_type).is_none() {
                        return err(
                            tag,
                            408,
                            "408 RESET_TO_DEFAULTS requires a loaded unit specification",
                        );
                    }
                }
            }
        }
        let before = model.clone();
        let before_db = Database::from_server(&model);
        let response = model.handle(line);
        if response.status >= 400 {
            *model = before;
            return response;
        }
        if verb == "PROJECT" && sub == "ARCHIVE" {
            if let Some(snapshot) = words
                .get(3)
                .and_then(|archive_key| model.database_files.get_mut(*archive_key))
            {
                clear_project_runtime(snapshot);
            }
        }
        if verb == "PROJECT" && sub == "COPY" {
            if let Some(copy) = words
                .get(3)
                .and_then(|project_name| model.projects.get_mut(*project_name))
            {
                clear_project_runtime(copy);
            }
        }
        // The in-memory compatibility model makes some database verbs affect
        // its synthetic physical layer. The hardware service must preserve
        // the independently observed bus inventory across every local command,
        // including read-only GETs, and must never let a database edit invent
        // physical presence.
        preserve_physical_state(&before, &mut model);
        let after_db = Database::from_server(&model);
        if before_db != after_db {
            if let Err(error) = after_db.save(&self.state_path) {
                *model = before;
                tracing::error!("C-Gate database commit failed: {error}");
                return err(tag, 500, "500 Database commit failed; change rolled back");
            }
        }
        if verb == "PP" {
            if let Some(name) = words.get(2) {
                match sub {
                    "LOCK" => {
                        client.locks.insert((*name).to_string());
                    }
                    "START" => {
                        client.sessions.insert((*name).to_string());
                    }
                    "UNLOCK" => {
                        client.locks.remove(*name);
                    }
                    "END" => {
                        client.sessions.remove(*name);
                    }
                    _ => {}
                }
            }
        }
        client.current = model.current.clone();
        for event in model.drain_events() {
            let _ = self.events.send(event);
        }
        response
    }

    /// Gate a C-Gate here-document after the connection has bounded and
    /// collected it. Framing support is deliberately separate from document
    /// semantics: native DBSETXML replaces typed objects and returns a 301 OID
    /// envelope, while CGL has a vendor exchange format. The in-memory mock's
    /// opaque store/count behavior cannot stand in for either operation, so the
    /// hardware service keeps both fail-closed.
    pub async fn handle_document(
        &self,
        client: &mut ClientState,
        line: &str,
        document: &str,
    ) -> Response {
        let cmd = match parse_command(line) {
            Ok(command) => command,
            Err(error) => return err("", 400, &format!("400 {error}")),
        };
        let words: Vec<&str> = cmd.body.split_whitespace().collect();
        let upper: Vec<String> = words.iter().map(|word| word.to_ascii_uppercase()).collect();
        let tag = &cmd.tag;
        let verb = upper.first().map(String::as_str).unwrap_or("");
        let sub = upper.get(1).map(String::as_str).unwrap_or("");

        if self.auth_token_hash.get().is_some()
            && !client.authenticated
            && requires_programming_auth(verb, sub, &upper)
        {
            return err(tag, 420, "420 LOGIN required");
        }
        let _ = (line, document);
        err(
            tag,
            502,
            "502 Document command semantics are not implemented",
        )
    }

    /// Read-only native repository-list envelope for cmqttd's one durable
    /// JSON state repository. The type token is intentionally cmqttd-specific;
    /// this is not presented as a Schneider SQLite/XML repository.
    fn repository_list(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(tag, 400, "400 REPOSITORY LIST takes no arguments");
        }
        let Some(path) = self.state_path.to_str() else {
            return err(tag, 500, "500 Repository path cannot be represented");
        };
        if path.chars().any(|character| character.is_control()) {
            return err(tag, 500, "500 Repository path cannot be represented");
        }
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("123 index=1 type=cmqttd-json path={path} current=yes"),
            status: 123,
        }
    }

    /// Native C-Gate command-session inspection. The registry is populated
    /// only by real TCP/TLS connections, remains independent of project and
    /// PCI state, and is discarded when the connection ends.
    async fn session_id(
        &self,
        client: &ClientState,
        response_tag: &str,
        words: &[&str],
        upper: &[String],
    ) -> Response {
        let Some(id) = client.command_session else {
            return err(response_tag, 500, "500 no session found");
        };
        match upper.get(1).map(String::as_str) {
            None if words.len() == 1 => Response {
                tag: response_tag.to_string(),
                lines: Vec::new(),
                final_text: format!("300 sessionID=cmd{id}"),
                status: 300,
            },
            Some("ALL") => {
                // C-Gate 3.4 ignores words after ALL. Preserve that observed
                // behavior even though the public syntax documents no tail.
                let sessions = self.command_sessions.lock().await;
                let mut rows = sessions
                    .sessions
                    .iter()
                    .map(|(session_id, session)| {
                        let tag = session
                            .tag
                            .as_ref()
                            .map_or_else(String::new, |value| format!(" tag={value}"));
                        format!(
                            "sessionID=cmd{session_id} origin={} from={}{}",
                            session.origin, session.connected_at, tag
                        )
                    })
                    .collect::<Vec<_>>();
                let Some(last) = rows.pop() else {
                    return err(response_tag, 500, "500 no session found");
                };
                Response {
                    tag: response_tag.to_string(),
                    lines: rows.into_iter().map(|row| format!("300-{row}")).collect(),
                    final_text: format!("300 {last}"),
                    status: 300,
                }
            }
            Some("TAG") if words.len() >= 3 => {
                let mut sessions = self.command_sessions.lock().await;
                let Some(session) = sessions.sessions.get_mut(&id) else {
                    return err(response_tag, 500, "500 no session found");
                };
                if session.tag.is_some() {
                    return err(
                        response_tag,
                        408,
                        "408 Operation failed: tag name has already been set",
                    );
                }
                // Native C-Gate collapses command whitespace, retains quote
                // characters literally, and publishes the joined tail.
                session.tag = Some(words[2..].join(" "));
                ok(response_tag, vec![], "200 OK.")
            }
            Some("TAG") => err(response_tag, 400, "400 Syntax Error: tag name not supplied"),
            _ => err(response_tag, 400, "400 Syntax Error."),
        }
    }

    /// Session-local LOGIN/LOGOUT for the optional shared-secret gate.
    /// Only reached when an auth hash is configured; the dormant service
    /// never routes here (LOGIN/LOGOUT stay generic-502).
    ///
    /// `LOGIN <token>` hashes the candidate with SHA-256 and compares
    /// digests in constant time, setting the per-connection flag on a
    /// match. Any failure (bad arity or mismatch) clears the flag, as does
    /// `LOGOUT` (which always answers 200). Nothing here performs PCI I/O,
    /// and neither the token nor the candidate ever enters logs, events,
    /// or responses.
    ///
    /// Failure status TBD: native LOGIN behavior is uncaptured, so 420
    /// mirrors this service's session-scoped denial family (PP ownership
    /// conflicts already use 420). It must NOT be read as native parity,
    /// and 401 is deliberately avoided: 401 already means
    /// absent-object/model-denied readings in this codebase.
    fn session_auth(&self, client: &mut ClientState, tag: &str, words: &[&str]) -> Response {
        let Some(expected) = self.auth_token_hash.get() else {
            // Unreachable: handle() routes here only when configured.
            return err(
                tag,
                502,
                "502 Command requires a physical backend that is not implemented",
            );
        };
        if words[0].eq_ignore_ascii_case("LOGOUT") {
            client.authenticated = false;
            return ok(tag, vec![], "200 OK");
        }
        if words.len() != 2 {
            // Fail-safe: a malformed LOGIN de-authenticates, matching the
            // documented "any failure clears the flag" contract.
            client.authenticated = false;
            return err(tag, 400, "400 LOGIN requires a token");
        }
        let candidate = auth::sha256(words[1].as_bytes());
        if auth::constant_time_eq(&candidate, expected) {
            client.authenticated = true;
            client.login_attempts = 0;
            ok(tag, vec![], "200 OK")
        } else {
            client.authenticated = false;
            client.login_attempts = client.login_attempts.saturating_add(1);
            err(tag, 420, "420 LOGIN failed")
        }
    }

    fn application_path(&self, address: &str) -> Option<u8> {
        let parts: Vec<_> = address
            .trim_start_matches('/')
            .split('/')
            .filter(|part| !part.is_empty())
            .collect();
        let (project, network, application) = match parts.as_slice() {
            [network, application] => (self.project.as_str(), *network, *application),
            [project, network, application] => (*project, *network, *application),
            _ => return None,
        };
        let network = network.parse::<u8>().ok()?;
        let application = parse_application(application)?;
        (project == self.project && network == self.network).then_some(application)
    }

    fn application_get(
        &self,
        model: &Server,
        tag: &str,
        address: &str,
        attribute: &str,
    ) -> Option<Response> {
        if let Some(application) = self.application_path(address) {
            if !matches!(application, 202 | 203) {
                return None;
            }
            if !attribute.eq_ignore_ascii_case("Groups") {
                return Some(err(tag, 402, "402 Parameter not found"));
            }
            let mut groups = HashSet::new();
            if let Some(network) = model
                .projects
                .get(&self.project)
                .and_then(|p| p.networks.get(&self.network))
            {
                groups.extend(
                    network
                        .levels
                        .keys()
                        .filter_map(|(app, group)| (*app == application).then_some(*group)),
                );
            }
            let prefix = format!("//{}/{}/{application}/", self.project, self.network);
            for key in model.db_fields.keys() {
                if let Some(rest) = key
                    .strip_prefix(&prefix)
                    .and_then(|value| value.strip_suffix("/TagName"))
                {
                    if let Ok(group) = rest.parse::<u8>() {
                        groups.insert(group);
                    }
                }
            }
            let mut groups: Vec<_> = groups.into_iter().collect();
            groups.sort_unstable();
            let value = groups
                .into_iter()
                .map(|group| group.to_string())
                .collect::<Vec<_>>()
                .join(",");
            return Some(Server::property(tag, address, "Groups", &value));
        }
        let (application, group) = self.bound_group(address)?;
        if !matches!(application, 202 | 203) {
            return None;
        }
        let level = model
            .projects
            .get(&self.project)
            .and_then(|p| p.networks.get(&self.network))
            .and_then(|n| n.levels.get(&(application, group)))
            .copied();
        let name = model
            .db_fields
            .get(&format!("{address}/TagName"))
            .cloned()
            .unwrap_or_default();
        let known = level.is_some() || !name.is_empty();
        if !known {
            return Some(err(
                tag,
                408,
                "408 No live application state has been observed",
            ));
        }
        let response = if attribute.eq_ignore_ascii_case("Level") {
            if application == 202 {
                err(tag, 402, "402 Parameter not found")
            } else if let Some(level) = level {
                Server::property(tag, address, "Level", &level.to_string())
            } else {
                err(tag, 408, "408 No live Enable level has been observed")
            }
        } else if attribute.eq_ignore_ascii_case("State") {
            Server::property(tag, address, "State", "ok")
        } else if attribute.eq_ignore_ascii_case("Name") {
            Server::property(tag, address, "Name", &name)
        } else if application == 202 && attribute.eq_ignore_ascii_case("EventLevel") {
            Server::property(tag, address, "EventLevel", "5")
        } else if attribute == "*" {
            let mut fields = if application == 202 {
                vec![
                    ("EventLevel", "5".to_string()),
                    ("Name", name),
                    ("State", "ok".to_string()),
                ]
            } else {
                vec![("Name", name), ("State", "ok".to_string())]
            };
            if application == 203 {
                if let Some(level) = level {
                    fields.insert(0, ("Level", level.to_string()));
                }
            }
            let mut rows: Vec<_> = fields
                .into_iter()
                .map(|(name, value)| format!("300-{address}: {name}={value}"))
                .collect();
            let final_text = rows
                .pop()
                .expect("application wildcard has fields")
                .replacen("300-", "300 ", 1);
            Response {
                tag: tag.to_string(),
                lines: rows,
                final_text,
                status: 300,
            }
        } else {
            err(tag, 402, "402 Parameter not found")
        };
        Some(response)
    }

    async fn net_pingu(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        if words.len() != 3 || self.addressed_network(words[2]).is_none() {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            return staged.handle(line);
        }
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 {
            return validation;
        }
        let target = self
            .addressed_network(words[2])
            .expect("validated network address");
        let route = match self.route_to_network(target).await {
            Ok(route) => route,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical network route unavailable: {error}"),
                )
            }
        };
        let pci_generation = self.pci_generation.load(Ordering::Acquire);
        let pci = self.pci.read().await.clone();
        let states = match if route.is_empty() {
            pci.install_mmi().await
        } else {
            pci.install_mmi_routed(&route).await
        } {
            Ok(states) => states,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical installation MMI failed: {error}"),
                )
            }
        };
        let addresses: Vec<u8> = states
            .iter()
            .enumerate()
            .filter_map(|(address, state)| (*state != 0).then_some(address as u8))
            .collect();
        let _generation_gate = self.pci_generation_gate.lock().await;
        let current_pci = self.pci.read().await;
        if self.pci_generation.load(Ordering::Acquire) != pci_generation
            || !Arc::ptr_eq(&current_pci, &pci)
            || !pci.is_connected()
        {
            return err(
                tag,
                408,
                "408 Physical installation MMI invalidated by PCI reconnect",
            );
        }
        drop(current_pci);
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&target))
        {
            let previous = std::mem::take(&mut network.physical);
            network.physical = addresses
                .iter()
                .map(|address| {
                    let unit = previous
                        .get(address)
                        .cloned()
                        .unwrap_or_else(|| Unit::blank(*address, ""));
                    (*address, unit)
                })
                .collect();
        }
        let list = addresses
            .iter()
            .map(u8::to_string)
            .collect::<Vec<_>>()
            .join(", ");
        ok(tag, vec![format!("302-Units={list}")], "200 OK.")
    }

    async fn net_sync(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        if words.len() < 3 || self.addressed_network(words[2]).is_none() {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            return staged.handle(line);
        }
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 {
            return validation;
        }
        let target = self
            .addressed_network(words[2])
            .expect("validated network address");
        let route = match self.route_to_network(target).await {
            Ok(route) => route,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical network route unavailable: {error}"),
                )
            }
        };
        self.set_network_state(target, NetworkState::Syncing).await;
        let pci_generation = self.pci_generation.load(Ordering::Acquire);
        let pci = self.pci.read().await.clone();
        let (interface_units, configured_keygl5) = {
            let model = self.model.lock().await;
            let project = &model.projects[&self.project];
            let interface_units = project.networks[&self.network]
                .units
                .values()
                .filter(|unit| {
                    let unit_type = unit.unit_type.to_ascii_uppercase();
                    unit_type.starts_with("PC_CNI") || unit_type.starts_with("PC_PCI")
                })
                .map(|unit| unit.address)
                .collect::<Vec<_>>();
            let configured_keygl5 = project.networks[&target]
                .units
                .values()
                .filter(|unit| unit.unit_type.eq_ignore_ascii_case("KEYGL5"))
                .map(|unit| unit.address)
                .collect::<HashSet<_>>();
            (interface_units, configured_keygl5)
        };
        let local = match interface_units.as_slice() {
            [address] => pci.set_local_unit_hint(*address).map(|()| *address),
            [] => pci.discover_local_unit().await,
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "configured network has multiple local-interface units",
            )),
        };
        if let Err(error) = local {
            self.set_network_state(target, NetworkState::Open).await;
            return err(
                tag,
                408,
                &format!("408 Physical interface discovery failed: {error}"),
            );
        }
        let states = match if route.is_empty() {
            pci.install_mmi().await
        } else {
            pci.install_mmi_routed(&route).await
        } {
            Ok(states) => states,
            Err(error) => {
                self.set_network_state(target, NetworkState::Open).await;
                return err(
                    tag,
                    408,
                    &format!("408 Physical network synchronization failed: {error}"),
                );
            }
        };
        let addresses: Vec<u8> = states
            .iter()
            .enumerate()
            .filter_map(|(address, state)| (*state != 0).then_some(address as u8))
            .collect();
        struct SyncedIdentity {
            address: u8,
            mmi_state: u8,
            unit_type: String,
            identify_version: String,
            serial: String,
            serial_alternates: Vec<String>,
            has_exactly_one_known_serial_reply: bool,
            extended_firmware: Option<String>,
            applications: Option<[u8; 2]>,
            widget_groups: Option<String>,
        }

        let mut identities = Vec::with_capacity(addresses.len());
        let mut duplicate_events = Vec::new();
        for address in addresses {
            let unit_type = match if route.is_empty() {
                pci.identify_first(address, 1).await
            } else {
                pci.identify_first_routed(&route, address, 1).await
            } {
                Ok(Some(data)) => match identity_text(&data, "unit type") {
                    Ok(value) => value,
                    Err(error) => {
                        self.set_network_state(target, NetworkState::Open).await;
                        return err(
                            tag,
                            408,
                            &format!(
                                "408 Physical identity synchronization failed at address {address}: {error}"
                            ),
                        );
                    }
                },
                Ok(None) => String::new(),
                Err(error) => {
                    self.set_network_state(target, NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical identity synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let firmware = match if route.is_empty() {
                pci.identify_first(address, 2).await
            } else {
                pci.identify_first_routed(&route, address, 2).await
            } {
                Ok(Some(data)) => match identity_text(&data, "firmware version") {
                    Ok(value) => value,
                    Err(error) => {
                        self.set_network_state(target, NetworkState::Open).await;
                        return err(
                            tag,
                            408,
                            &format!(
                                "408 Physical identity synchronization failed at address {address}: {error}"
                            ),
                        );
                    }
                },
                Ok(None) => String::new(),
                Err(error) => {
                    self.set_network_state(target, NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical identity synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let serial_replies = match if route.is_empty() {
                pci.identify_all(address, 4).await
            } else {
                pci.identify_all_routed(&route, address, 4).await
            } {
                Ok(replies) => replies,
                Err(error) => {
                    self.set_network_state(target, NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical serial synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let serials = match known_serials(&serial_replies) {
                Ok(serials) => serials,
                Err(error) => {
                    self.set_network_state(target, NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical serial synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let has_exactly_one_known_serial_reply =
                serial_replies.len() == 1 && serials.len() == 1;
            // P3d: surface duplicate-address conflicts on the event channel
            // and retain the observed set in the volatile snapshot. The scalar
            // `serial` keeps "" on conflict (SerialNumber getter/SET
            // semantics unchanged); the sorted `serial_alternates` carry
            // the evidence. The event names the address and every observed
            // serial, sorted for deterministic output:
            // `#e# net {network} sync duplicate {address} {serial...}`.
            // Single observations store the serial with empty alternates;
            // zero observations store "" with empty alternates as before.
            let (serial, serial_alternates) = if serials.len() == 1 {
                (serials.into_iter().next().unwrap(), Vec::new())
            } else if serials.len() > 1 {
                let mut duplicates: Vec<_> = serials.into_iter().collect();
                duplicates.sort();
                duplicate_events.push(format!(
                    "#e# net {} sync duplicate {address} {}",
                    target,
                    duplicates.join(" ")
                ));
                (String::new(), duplicates)
            } else {
                (String::new(), Vec::new())
            };
            identities.push(SyncedIdentity {
                address,
                mmi_state: states[usize::from(address)],
                unit_type,
                identify_version: firmware,
                serial,
                serial_alternates,
                has_exactly_one_known_serial_reply,
                extended_firmware: None,
                applications: None,
                widget_groups: None,
            });
        }

        // Complete every required identity transaction before the optional
        // KEYGL5 reads. Retained C-Gate classfile bytecode proves this order:
        // CBusOEMUnit.o() dispatches CBusEdlt.t() (OEM-routed 0xFB/9), then
        // CBusEdlt.n() reads OEM memory address 16/2 before invoking the
        // ignored-result OEM-routed 0xFA/44 WidgetGroups helper. The reads
        // remain optional for overall identity SYNC. An incomplete read
        // faults the programming lane, so later optional calls fail closed
        // without replay; every unavailable
        // value remains None and is invalidated at commit. These addressed
        // replies carry no serial identity, so only a non-error present MMI
        // state (one or two) with exactly one raw IDENTIFY4 reply carrying a
        // known serial is eligible. Live direct networks legitimately report
        // unique units in both states, and the bounded IDENTIFY4 collection
        // supplies the independent uniqueness guard. State three and zero or
        // multiple raw replies (including repeated known replies or mixed
        // known/unknown replies) remain ambiguous and must not be queried or
        // exposed as one device's metadata.
        for identity in &mut identities {
            if route.is_empty()
                && identity.unit_type.eq_ignore_ascii_case("KEYGL5")
                && configured_keygl5.contains(&identity.address)
                && mmi_state_is_present_non_error(identity.mmi_state)
                && identity.has_exactly_one_known_serial_reply
            {
                identity.extended_firmware =
                    pci.read_edlt_extended_firmware(identity.address).await.ok();
                identity.applications = pci.read_edlt_applications(identity.address).await.ok();
                identity.widget_groups = pci.read_edlt_widget_groups(identity.address).await.ok();
            }
        }

        // A reconnect or transport loss invalidates everything collected by
        // this command. Serialize the check with set_pci so a stale task can
        // neither repopulate the cleared cache nor emit a false sync-ok after
        // replacement starts.
        let _generation_gate = self.pci_generation_gate.lock().await;
        let current_pci = self.pci.read().await;
        if self.pci_generation.load(Ordering::Acquire) != pci_generation
            || !Arc::ptr_eq(&current_pci, &pci)
        {
            return err(
                tag,
                408,
                "408 Physical network synchronization invalidated by PCI reconnect",
            );
        }
        if !pci.is_connected() {
            drop(current_pci);
            if let Some(network) = self
                .model
                .lock()
                .await
                .projects
                .get_mut(&self.project)
                .and_then(|project| project.networks.get_mut(&target))
            {
                network.physical.clear();
                network.state = NetworkState::Closed;
            }
            return err(
                tag,
                408,
                "408 Physical network synchronization lost the PCI connection",
            );
        }
        let mut model = self.model.lock().await;
        if let Some(network) = model
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&target))
        {
            let previous = std::mem::take(&mut network.physical);
            network.physical = identities
                .into_iter()
                .map(|identity| {
                    let mut unit = previous
                        .get(&identity.address)
                        .cloned()
                        .unwrap_or_else(|| Unit::blank(identity.address, ""));
                    unit.unit_type = identity.unit_type;
                    // Version remains the ordinary IDENTIFY2 value. The
                    // separate native 0xFB result is a volatile field override
                    // for FirmwareVersion only; database records are untouched.
                    unit.firmware = identity.identify_version;
                    unit.serial = identity.serial;
                    unit.serial_alternates = identity.serial_alternates;
                    for field in [
                        "Version",
                        "FirmwareVersion",
                        "Application",
                        "Application2",
                        "WidgetGroups",
                    ] {
                        unit.fields.remove(field);
                    }
                    if let Some(firmware) = identity.extended_firmware {
                        unit.fields.insert("FirmwareVersion".into(), firmware);
                    }
                    if let Some([primary, secondary]) = identity.applications {
                        unit.fields
                            .insert("Application".into(), primary.to_string());
                        unit.fields
                            .insert("Application2".into(), secondary.to_string());
                    }
                    if let Some(widget_groups) = identity.widget_groups {
                        unit.fields.insert("WidgetGroups".into(), widget_groups);
                    }
                    (identity.address, unit)
                })
                .collect();
            network.state = NetworkState::Ok;
        }
        drop(model);
        for event in duplicate_events {
            let _ = self.events.send(event);
        }
        let _ = self.events.send(format!("#e# net {target} sync ok"));
        validation
    }

    async fn net_syncnew(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 || !(3..=4).contains(&words.len()) {
            return validation;
        }
        if !self.bound_network(words[2]) {
            return validation;
        }
        let selected = words.get(3).map(|unit| {
            unit.parse::<u8>()
                .expect("the staged C-Gate model validated the unit address")
        });

        if let Some(address) = selected {
            let already_modeled = {
                let model = self.model.lock().await;
                let network = &model.projects[&self.project].networks[&self.network];
                network.units.contains_key(&address) || network.physical.contains_key(&address)
            };
            if already_modeled {
                return syncnew_response(tag, vec![(408, "Unit already in model".to_string())]);
            }
        }

        let pci = self.pci.read().await.clone();
        let interface_units = {
            let model = self.model.lock().await;
            model.projects[&self.project].networks[&self.network]
                .units
                .values()
                .filter(|unit| {
                    let unit_type = unit.unit_type.to_ascii_uppercase();
                    unit_type.starts_with("PC_CNI") || unit_type.starts_with("PC_PCI")
                })
                .map(|unit| unit.address)
                .collect::<Vec<_>>()
        };
        let local = match interface_units.as_slice() {
            [address] => pci.set_local_unit_hint(*address).map(|()| *address),
            [] => pci.discover_local_unit().await,
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "configured network has multiple local-interface units",
            )),
        };
        if let Err(error) = local {
            return syncnew_response(
                tag,
                vec![(408, format!("Interface discovery failed:{error}"))],
            );
        }

        let mut statuses = Vec::new();
        let mut merged = vec![0u8; 256];
        for pass in 1..=5 {
            let states = match pci.install_mmi().await {
                Ok(states) => states,
                Err(error) => {
                    statuses.push((408, format!("Installation MMI failure:{error}")));
                    return syncnew_response(tag, statuses);
                }
            };
            if states.len() != merged.len() {
                statuses.push((
                    408,
                    "Installation MMI failure:incomplete address coverage".to_string(),
                ));
                return syncnew_response(tag, statuses);
            }
            for (combined, observed) in merged.iter_mut().zip(states) {
                if *combined != 3 && observed != 0 {
                    *combined = observed;
                }
            }
            statuses.push((120, format!("completed MMI {pass} of 5.")));
        }

        if let Some(address) = selected {
            if merged[address as usize] == 0 {
                statuses.push((408, "Unit at given address not found".to_string()));
                return syncnew_response(tag, statuses);
            }
            statuses.push((120, "unit found".to_string()));
            for attempt in 0..3 {
                statuses.push((120, format!("duplicate test {}/3", attempt + 1)));
                let count = match pci.duplicate_address_probe(address, attempt).await {
                    Ok(count) => count,
                    Err(error) => {
                        statuses.push((408, format!("Duplicate test failed:{error}")));
                        return syncnew_response(tag, statuses);
                    }
                };
                if count > 1 {
                    self.remove_physical_unit(address).await;
                    let _ = self.events.send(format!(
                        "#e# net {} syncnew duplicate {address}",
                        self.network
                    ));
                    statuses.push((408, format!("Duplicate units at address {address}")));
                    return syncnew_response(tag, statuses);
                }
            }
            statuses.push((120, "no duplicate found".to_string()));
            statuses.push((120, "identifying unit".to_string()));
            match syncnew_identity(&pci, address).await {
                Ok(unit) => {
                    let detail = syncnew_unit_detail(&unit);
                    self.store_physical_unit(unit).await;
                    let _ = self
                        .events
                        .send(format!("#e# net {} syncnew unit {address}", self.network));
                    statuses.push((303, detail));
                }
                Err(error) => statuses.push((
                    408,
                    format!("Identify failed for unit at address {address}: {error}"),
                )),
            }
            return syncnew_response(tag, statuses);
        }

        let modeled_identity = {
            let model = self.model.lock().await;
            let network = &model.projects[&self.project].networks[&self.network];
            (0u16..=255)
                .map(|address| {
                    let address = address as u8;
                    let modeled = network.units.contains_key(&address)
                        || network.physical.contains_key(&address);
                    let identified = network
                        .physical
                        .get(&address)
                        .or_else(|| network.units.get(&address))
                        .is_some_and(|unit| !unit.serial.is_empty());
                    (modeled, identified)
                })
                .collect::<Vec<_>>()
        };
        let mut found = false;
        for (address, state) in merged.into_iter().enumerate() {
            let address = address as u8;
            if state == 3 {
                self.remove_physical_unit(address).await;
                let _ = self.events.send(format!(
                    "#e# net {} syncnew duplicate {address}",
                    self.network
                ));
                statuses.push((303, format!("Duplicate Units Found: address={address}")));
                found = true;
                continue;
            }
            if state == 0
                || (modeled_identity[address as usize].0 && modeled_identity[address as usize].1)
            {
                continue;
            }
            match syncnew_identity(&pci, address).await {
                Ok(unit) => {
                    let detail = syncnew_unit_detail(&unit);
                    self.store_physical_unit(unit).await;
                    let _ = self
                        .events
                        .send(format!("#e# net {} syncnew unit {address}", self.network));
                    statuses.push((303, detail));
                }
                Err(_) => statuses.push((
                    408,
                    format!("Identify failed for unit at address {address}"),
                )),
            }
            found = true;
        }
        if !found {
            statuses.push((408, "No new units found".to_string()));
        }
        syncnew_response(tag, statuses)
    }

    /// Identify the project attached to the service's one shared physical
    /// interface. Native C-Gate creates a temporary network for the supplied
    /// interface, runs one installation MMI, counts every non-zero address,
    /// then reads parameter 35 from the first identifiable non-zero unit.
    ///
    /// cmqttd deliberately owns one PCI/CNI connection for MQTT and C-Gate.
    /// Consequently only the imported interface that backs that connection
    /// is admitted; another otherwise-valid interface remains fail-closed
    /// instead of opening a second transport behind MQTT's back.
    async fn net_project_identify(&self, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        let Some(interface) = words.get(2) else {
            return err(
                tag,
                400,
                "400 Syntax Error: Missing parameter : <interface>",
            );
        };
        if words.len() > 3 {
            return err(tag, 400, "400 Syntax Error: Too many parameters");
        }
        let Some((interface_type, interface_address)) = parse_interface_spec(interface) else {
            return Response {
                tag: tag.to_string(),
                lines: vec![format!(
                    "470-Bad interface specification for NET0 {interface}"
                )],
                final_text:
                    "408 Operation failed: Can not open network (bad interface specification"
                        .to_string(),
                status: 408,
            };
        };

        let matches_shared_interface = {
            let model = self.model.lock().await;
            let network = &model.projects[&self.project].networks[&self.network];
            network.iface_type.eq_ignore_ascii_case(interface_type)
                && network.iface_addr == interface_address
        };
        if !matches_shared_interface {
            return err(
                tag,
                502,
                "502 Command requires the configured shared physical interface",
            );
        }

        let generation = self.pci_generation.load(Ordering::Acquire);
        let pci = self.pci.read().await.clone();
        let states = match pci.install_mmi().await {
            Ok(states) if states.len() == 256 => states,
            Ok(_) => {
                return err(
                    tag,
                    408,
                    "408 Operation failed: Installation MMI returned incomplete address coverage",
                );
            }
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Operation failed: Installation MMI failed: {error}"),
                );
            }
        };
        let unit_count = states.iter().filter(|state| **state != 0).count();
        let mut project = None;
        for address in 1u16..=255 {
            let address = address as u8;
            if states[address as usize] == 0 {
                continue;
            }
            // Native creates a level-zero unit before asking it for
            // ProjectName: IDENTIFY1, then IDENTIFY2 plus parameter 33. Keep
            // those prerequisites so a stray parameter-35 reply from an
            // address that cannot be identified cannot become the result.
            if project_identify_candidate(&pci, address).await.is_err() {
                continue;
            }
            let Ok(encoded) = pci.recall_parameter(address, 35, 6).await else {
                continue;
            };
            let Ok(decoded) = cbus_protocol::project_identity::decode_project_identity(&encoded)
            else {
                continue;
            };
            project = Some(decoded.trim().to_string());
            break;
        }

        let _generation_gate = self.pci_generation_gate.lock().await;
        if self.pci_generation.load(Ordering::Acquire) != generation {
            return err(
                tag,
                408,
                "408 Operation failed: PCI reconnected during project discovery",
            );
        }
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!(
                "305 Project={} UnitCount={unit_count}",
                project.as_deref().unwrap_or("null")
            ),
            status: 305,
        }
    }

    async fn net_set_project_identify(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 {
            return validation;
        }
        let Some(address) = words.get(2) else {
            return err(tag, 400, "400 NET SET_PROJECT_IDENTIFY requires a network");
        };
        if !self.bound_network(address) {
            return err(
                tag,
                502,
                "502 Command requires a physical backend that is not implemented",
            );
        }
        let identity = match parse_command(line)
            .ok()
            .and_then(|command| project_identity_argument(&command.body).ok())
        {
            Some(identity) => identity,
            None => {
                return err(
                    tag,
                    400,
                    "400 NET SET_PROJECT_IDENTIFY requires a project identity",
                );
            }
        };
        let encoded = match cbus_protocol::project_identity::encode_project_identity(&identity) {
            Ok(encoded) => encoded,
            Err(error) => {
                return err(tag, 408, &format!("408 Operation failed: {error}"));
            }
        };

        let pci = self.pci.read().await.clone();
        let interface_units = {
            let model = self.model.lock().await;
            model.projects[&self.project].networks[&self.network]
                .units
                .values()
                .filter(|unit| {
                    let unit_type = unit.unit_type.to_ascii_uppercase();
                    unit_type.starts_with("PC_CNI") || unit_type.starts_with("PC_PCI")
                })
                .map(|unit| unit.address)
                .collect::<Vec<_>>()
        };
        let local = match interface_units.as_slice() {
            [address] => pci.set_local_unit_hint(*address).map(|()| *address),
            [] => pci.discover_local_unit().await,
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "configured network has multiple local-interface units",
            )),
        };
        if let Err(error) = local {
            return err(
                tag,
                408,
                &format!("408 Physical interface discovery failed: {error}"),
            );
        }
        let states = match pci.install_mmi().await {
            Ok(states) => states,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical installation MMI failed: {error}"),
                );
            }
        };

        let mut selected = None;
        for (address, state) in states.iter().enumerate().skip(1) {
            // Native C-Gate chooses the first present nonzero unit. Admit both
            // non-error present states, then require exactly one valid serial
            // reply in a complete quiet-bounded IDENTIFY4 observation. Neither
            // MMI state is a uniqueness proof: the fresh serial window is.
            if !mmi_state_is_present_non_error(*state) {
                continue;
            }
            let address = address as u8;
            match pci.identify_first(address, 1).await {
                Ok(Some(unit_type)) => match identity_text(&unit_type, "unit type") {
                    Ok(unit_type) => {
                        let serial_replies = match pci.identify_all(address, 4).await {
                            Ok(replies) => replies,
                            Err(error) => {
                                return err(
                                    tag,
                                    408,
                                    &format!(
                                        "408 Project identify serial selection failed: {error}"
                                    ),
                                );
                            }
                        };
                        if let [reply] = serial_replies.as_slice() {
                            if serial_number(reply).is_ok_and(|serial| serial.is_some()) {
                                selected = Some((address, unit_type));
                                break;
                            }
                        }
                    }
                    Err(_) => continue,
                },
                Ok(None) => continue,
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!("408 Project identify unit selection failed: {error}"),
                    );
                }
            }
        }
        let Some((address, unit_type)) = selected else {
            return err(
                tag,
                408,
                "408 Operation failed: Can't find unit to set project name in",
            );
        };
        if let Err(error) = pci.set_project_identity_verified(address, &encoded).await {
            // Once STORE has been admitted, a transport failure or mismatched
            // readback makes any previous cached value unsafe to serve. A
            // definitive NAK is also cleared conservatively; a later SYNC or
            // successful write may repopulate the volatile field.
            self.clear_physical_project_name(address).await;
            let detail = if error
                .to_string()
                .contains("unit rejected programming selector")
            {
                "project name save failed - Negative Acknowledge response from unit"
            } else if error.kind() == io::ErrorKind::TimedOut {
                "project name save failed - no response from unit"
            } else {
                "project name save failed - store to unit failed"
            };
            return err(tag, 408, &format!("408 Operation failed: {detail}"));
        }

        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            let unit = network
                .physical
                .entry(address)
                .or_insert_with(|| Unit::blank(address, ""));
            unit.unit_type = unit_type;
            unit.fields.insert(
                "ProjectName".to_string(),
                cbus_protocol::project_identity::decode_project_identity(&encoded)
                    .expect("a six-byte project identity always decodes"),
            );
        }
        validation
    }

    async fn clear_physical_project_name(&self, address: u8) {
        if let Some(unit) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
            .and_then(|network| network.physical.get_mut(&address))
        {
            unit.fields.remove("ProjectName");
        }
    }

    async fn remove_physical_unit(&self, address: u8) {
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            network.physical.remove(&address);
        }
    }

    async fn store_physical_unit(&self, unit: Unit) {
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            network.physical.insert(unit.address, unit);
        }
    }

    async fn net_checkunit(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        if words.len() != 4 || self.addressed_network(words[2]).is_none() {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            return staged.handle(line);
        }
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 {
            return validation;
        }
        let target = self
            .addressed_network(words[2])
            .expect("validated network address");
        let route = match self.route_to_network(target).await {
            Ok(route) => route,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical network route unavailable: {error}"),
                )
            }
        };
        let pci_generation = self.pci_generation.load(Ordering::Acquire);
        let pci = self.pci.read().await.clone();
        let selected = if words[3] == "*" {
            let states = match if route.is_empty() {
                pci.install_mmi().await
            } else {
                pci.install_mmi_routed(&route).await
            } {
                Ok(states) => states,
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!("408 Physical unit discovery failed: {error}"),
                    )
                }
            };
            states
                .iter()
                .enumerate()
                .filter_map(|(address, state)| (*state != 0).then_some(address as u8))
                .collect::<Vec<_>>()
        } else {
            words[3]
                .split(',')
                .map(|part| part.parse::<u8>().expect("model validated unit selection"))
                .collect::<Vec<_>>()
        };
        let mut lines = Vec::with_capacity(selected.len());
        for address in selected {
            let replies = match if route.is_empty() {
                pci.identify_all(address, 4).await
            } else {
                pci.identify_all_routed(&route, address, 4).await
            } {
                Ok(replies) => replies,
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!("408 Physical unit check failed at address {address}: {error}"),
                    )
                }
            };
            let serials = match known_serials(&replies) {
                Ok(serials) => serials,
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!("408 Physical unit check failed at address {address}: {error}"),
                    )
                }
            };
            let unknown = replies.len()
                - replies
                    .iter()
                    .filter(|reply| serial_number(reply).ok().flatten().is_some())
                    .count();
            let status = match (serials.len(), unknown) {
                (0, 0) => "No units detected",
                (1, 0) => "Single unit detected",
                (n, 0) if n > 1 => "Duplicate units detected",
                (0, 1) => "Single unit with error detected",
                _ => "One or more units with error detected",
            };
            lines.push(format!("120-{status} at address: {address}"));
        }
        let _generation_gate = self.pci_generation_gate.lock().await;
        let current_pci = self.pci.read().await;
        if self.pci_generation.load(Ordering::Acquire) != pci_generation
            || !Arc::ptr_eq(&current_pci, &pci)
            || !pci.is_connected()
        {
            return err(
                tag,
                408,
                "408 Physical unit check invalidated by PCI reconnect",
            );
        }
        drop(current_pci);
        let _ = self
            .events
            .send(format!("#e# net {target} checkunit {}", words[3]));
        ok(tag, lines, "200 OK.")
    }

    async fn net_unravel(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let validation = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if validation.status >= 400 {
            return validation;
        }
        if words.len() != 5
            || !words[1].eq_ignore_ascii_case("UNRAVELUNIT")
            || !self.bound_network(words[2])
            || words[3] != "255"
            || !words[4].eq_ignore_ascii_case("MATCHDB")
        {
            return err(
                tag,
                502,
                "502 Physical unravel currently requires NET UNRAVELUNIT on address 255 with MATCHDB",
            );
        }

        let pci = self.pci.read().await.clone();
        let (database_units, interface_units) = {
            let model = self.model.lock().await;
            let network = &model.projects[&self.project].networks[&self.network];
            let units = network.units.values().cloned().collect::<Vec<_>>();
            let interfaces = units
                .iter()
                .filter(|unit| {
                    let unit_type = unit.unit_type.to_ascii_uppercase();
                    unit_type.starts_with("PC_CNI") || unit_type.starts_with("PC_PCI")
                })
                .map(|unit| unit.address)
                .collect::<Vec<_>>();
            (units, interfaces)
        };
        let local = match interface_units.as_slice() {
            [address] => pci.set_local_unit_hint(*address).map(|()| *address),
            [] => pci.discover_local_unit().await,
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "configured network has multiple local-interface units",
            )),
        };
        let local = match local {
            Ok(local) if local != 255 => local,
            Ok(_) => return err(tag, 409, "409 Local PCI cannot be part of address 255"),
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical interface discovery failed: {error}"),
                )
            }
        };

        let before_states = match pci.install_mmi().await {
            Ok(states) => states,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Initial unravel inventory failed: {error}"),
                )
            }
        };
        let before = match physical_serial_inventory(&pci, &before_states).await {
            Ok(inventory) => inventory,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Initial unravel identity inventory failed: {error}"),
                )
            }
        };
        let Some(source_serials) = before.get(&255) else {
            return err(tag, 401, "401 No units detected at address 255");
        };
        if source_serials.len() != 2
            || before
                .iter()
                .any(|(address, serials)| *address != 255 && serials.len() != 1)
        {
            return err(
                tag,
                409,
                "409 Bounded unravel requires exactly two known serials at address 255 and no other duplicates",
            );
        }

        let mut plan = Vec::with_capacity(2);
        for serial in source_serials {
            let matching = database_units
                .iter()
                .filter(|unit| {
                    parse_native_serial(&unit.serial)
                        .ok()
                        .is_some_and(|value| value.known && value.canonical == *serial)
                })
                .collect::<Vec<_>>();
            let [unit] = matching.as_slice() else {
                return err(
                    tag,
                    409,
                    &format!("409 Serial {serial} must have exactly one database destination"),
                );
            };
            if !(2..=254).contains(&unit.address)
                || unit.address == local
                || before_states[usize::from(unit.address)] != 0
            {
                return err(
                    tag,
                    409,
                    &format!(
                        "409 Database destination {} for serial {serial} is not independently empty",
                        unit.address
                    ),
                );
            }
            plan.push((serial.clone(), unit.address));
        }
        plan.sort_by_key(|(_, destination)| *destination);
        if plan[0].1 == plan[1].1 {
            return err(tag, 409, "409 Database destinations are not unique");
        }

        let local_options = match pci.recall_parameter(local, 66, 1).await {
            Ok(value) => value,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Local PCI option check failed: {error}"),
                )
            }
        };
        if local_options != [5] {
            return err(
                tag,
                409,
                "409 Bounded unravel requires local PCI parameter 66 to equal 05",
            );
        }

        // MMI absence is necessary but not sufficient for an irreversible
        // address broadcast. Actively probe every target before the first
        // mutation so a hidden responder aborts the whole plan with zero
        // selected-serial sends.
        for (serial, destination) in &plan {
            match pci.identify_all(*destination, 4).await {
                Ok(replies) if replies.is_empty() => {}
                Ok(_) => {
                    return err(
                        tag,
                        409,
                        &format!(
                            "409 Database destination {destination} for serial {serial} answered the independent emptiness check"
                        ),
                    )
                }
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Database destination {destination} emptiness check failed: {error}"
                        ),
                    )
                }
            }
        }

        let source_state = before_states[255];
        let mut expected_states = before_states.clone();
        expected_states[255] = 0;
        let mut expected = before.clone();
        expected.remove(&255);
        let total = plan.len();
        let mut completed = 0usize;
        for (serial, destination) in &plan {
            if let Err(error) = pci.address_selected_serial(serial, *destination).await {
                return err(
                    tag,
                    408,
                    &format!(
                        "408 Unravel outcome uncertain after {completed} of {total} verified movement(s): {error}"
                    ),
                );
            }
            let replies = match pci.identify_all(*destination, 4).await {
                Ok(replies) => replies,
                Err(error) => {
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Unravel verification failed after {completed} of {total} verified movement(s): {error}"
                        ),
                    )
                }
            };
            let verified = replies.len() == 1
                && serial_number(&replies[0])
                    .ok()
                    .flatten()
                    .is_some_and(|observed| observed == *serial);
            if !verified {
                return err(
                    tag,
                    408,
                    &format!(
                        "408 Unravel verification failed after {completed} of {total} verified movement(s)"
                    ),
                );
            }
            completed += 1;
            expected_states[usize::from(*destination)] = source_state;
            expected.insert(*destination, vec![serial.clone()]);
            let _ = self
                .events
                .send(format!("#e# unit moved serial={serial} 255 {destination}"));
        }

        let after_states = match pci.install_mmi().await {
            Ok(states) => states,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!(
                        "408 Final unravel inventory failed after {completed} move(s): {error}"
                    ),
                )
            }
        };
        let after = match physical_serial_inventory(&pci, &after_states).await {
            Ok(inventory) => inventory,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!(
                        "408 Final unravel identity inventory failed after {completed} move(s): {error}"
                    ),
                )
            }
        };
        let final_options = match pci.recall_parameter(local, 66, 1).await {
            Ok(value) => value,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Final local PCI option check failed: {error}"),
                )
            }
        };
        if after_states != expected_states || after != expected || final_options != [5] {
            return err(
                tag,
                408,
                "408 Final unravel inventory differs from the exact planned change",
            );
        }

        let mut model = self.model.lock().await;
        if let Some(network) = model
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            let previous = std::mem::take(&mut network.physical);
            network.physical = after
                .iter()
                .map(|(address, serials)| {
                    let serial = &serials[0];
                    let mut unit = database_units
                        .iter()
                        .find(|unit| {
                            parse_native_serial(&unit.serial)
                                .ok()
                                .is_some_and(|value| value.known && value.canonical == *serial)
                        })
                        .cloned()
                        .or_else(|| previous.get(address).cloned())
                        .unwrap_or_else(|| Unit::blank(*address, ""));
                    unit.address = *address;
                    unit.serial = serial.clone();
                    (*address, unit)
                })
                .collect();
            network.state = NetworkState::Ok;
        }
        drop(model);
        let _ = self
            .events
            .send(format!("#e# net {} unravel ok", self.network));
        validation
    }

    async fn readdress_unit(&self, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        if words.len() != 4 || !words[2].eq_ignore_ascii_case("Address") {
            return err(
                tag,
                400,
                "400 SET requires a source path and Address destination",
            );
        }
        let Some((project, network, source)) = Server::split_unit(words[1]) else {
            return err(tag, 400, "400 Invalid source path");
        };
        if project != self.project || network != self.network {
            return err(tag, 404, "404 Network is not connected to this service");
        }
        let Ok(destination) = words[3].parse::<u8>() else {
            return err(tag, 400, "400 Invalid destination address");
        };
        if source == 0 || !(1..=254).contains(&destination) || source == destination {
            return err(tag, 400, "400 Invalid destination address");
        }

        let pci = self.pci.read().await.clone();
        let source_replies = match pci.identify_all(source, 4).await {
            Ok(replies) => replies,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Source address check failed: {error}"),
                )
            }
        };
        match source_replies.len() {
            0 => return err(tag, 401, "401 Unit not found"),
            1 => {}
            _ => return err(tag, 409, "409 Source address contains multiple units"),
        }
        let destination_replies = match pci.identify_all(destination, 4).await {
            Ok(replies) => replies,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Destination address check failed: {error}"),
                )
            }
        };
        if !destination_replies.is_empty() {
            return err(tag, 409, "409 Destination occupied");
        }
        if let Err(error) = pci.readdress_unit(source, destination).await {
            let code = if error.to_string().contains("unit rejected") {
                409
            } else {
                408
            };
            return err(tag, code, &format!("{code} Readdress failed: {error}"));
        }

        let destination_path = format!("//{project}/{network}/p/{destination}");
        let mut model = self.model.lock().await;
        if let Some(physical) = model
            .projects
            .get_mut(&project)
            .and_then(|project| project.networks.get_mut(&network))
            .map(|network| &mut network.physical)
        {
            if let Some(mut unit) = physical.remove(&source) {
                unit.address = destination;
                physical.insert(destination, unit);
            }
        }
        drop(model);
        let _ = self
            .events
            .send(format!("#e# unit moved {source} {destination}"));
        ok(tag, vec![], &format!("200 OK: {destination_path}"))
    }

    async fn set_network_state(&self, network_address: u8, state: NetworkState) {
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&network_address))
        {
            network.state = state;
        }
    }

    async fn aircon(&self, tag: &str, words: &[&str], sub: &str) -> Response {
        let parameters: &[&str] = match sub {
            "REFRESH" | "SET_WARD_OFF" | "SET_WARD_ON" => &["application", "ward"],
            "SET_ZONE_HVAC_MODE" | "SET_ZONE_HUMIDITY_MODE" => &[
                "application",
                "ward",
                "zone-list",
                "mode",
                "rawlevel",
                "setbackenabled",
                "guardenabled",
                "useauxlevel",
                "type",
                "level",
                "auxlevel",
            ],
            "SET_HVAC_UPPER_GUARD_LIMIT"
            | "SET_HVAC_LOWER_GUARD_LIMIT"
            | "SET_HVAC_SETBACK_LIMIT"
            | "SET_HUMIDITY_UPPER_GUARD_LIMIT"
            | "SET_HUMIDITY_LOWER_GUARD_LIMIT"
            | "SET_HUMIDITY_SETBACK_LIMIT" => &[
                "application",
                "ward",
                "zone-list",
                "limit",
                "mode",
                "rawlevel",
            ],
            _ => return err(tag, 400, "400 Syntax Error."),
        };
        let supplied = words.len().saturating_sub(2);
        if supplied < parameters.len() {
            return err(
                tag,
                400,
                &format!(
                    "400 Syntax Error: Missing parameter : <{}>",
                    parameters[supplied]
                ),
            );
        }
        if supplied > parameters.len() {
            return err(tag, 400, "400 Syntax Error: Too many parameters");
        }

        let target = words[2];
        let Some(application) = self.application_path(target) else {
            return err(tag, 404, "404 Network is not connected to this service");
        };
        if application != 172 {
            return err(
                tag,
                402,
                &format!("402 Operation not supported by: {target}"),
            );
        }
        let ward = match parse_aircon_ward(tag, target, words[3]) {
            Ok(value) => value,
            Err(response) => return response,
        };

        let command = match sub {
            "REFRESH" => AirconCommand::Refresh { ward },
            "SET_WARD_OFF" => AirconCommand::WardOff { ward },
            "SET_WARD_ON" => AirconCommand::WardOn { ward },
            "SET_ZONE_HVAC_MODE" | "SET_ZONE_HUMIDITY_MODE" => {
                let zones = match parse_aircon_zones(tag, target, words[4]) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let mode = match parse_aircon_integer(tag, words[5], "mode", None) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let humidity = sub == "SET_ZONE_HUMIDITY_MODE";
                let maximum = if humidity { 3 } else { 4 };
                if !(0..=maximum).contains(&mode) {
                    let family = if humidity { "Humidity" } else { "HVAC" };
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Operation failed: {target} ({family} Plant Mode is out of range: {mode})"
                        ),
                    );
                }
                let raw_level = match parse_aircon_boolean(tag, words[6], "rawlevel") {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let setback_enabled = match parse_aircon_boolean(tag, words[7], "setbackenabled") {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let guard_enabled = match parse_aircon_boolean(tag, words[8], "guardenabled") {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let use_aux_level = match parse_aircon_boolean(tag, words[9], "useauxlevel") {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let plant_type = match parse_aircon_integer(tag, words[10], "type", None) {
                    Ok(value) if value >= 0 => value.min(i32::from(u8::MAX)) as u8,
                    Ok(value) => {
                        let family = if humidity { "Humidity" } else { "HVAC" };
                        return err(
                            tag,
                            408,
                            &format!(
                                "408 Operation failed: {target} ({family} Plant Type is out of range: {value})"
                            ),
                        );
                    }
                    Err(response) => return response,
                };
                let level = match parse_aircon_integer(tag, words[11], "level", Some((0, 65535))) {
                    Ok(value) => value as u16,
                    Err(response) => return response,
                };
                let aux_level =
                    match parse_aircon_integer(tag, words[12], "auxlevel", Some((0, 255))) {
                        Ok(value) => value as u8,
                        Err(response) => return response,
                    };
                if humidity {
                    AirconCommand::ZoneHumidityMode {
                        ward,
                        zones,
                        mode: mode as u8,
                        raw_level,
                        setback_enabled,
                        guard_enabled,
                        use_aux_level,
                        plant_type,
                        level,
                        aux_level,
                    }
                } else {
                    AirconCommand::ZoneHvacMode {
                        ward,
                        zones,
                        mode: mode as u8,
                        raw_level,
                        setback_enabled,
                        guard_enabled,
                        use_aux_level,
                        plant_type,
                        level,
                        aux_level,
                    }
                }
            }
            _ => {
                let zones = match parse_aircon_zones(tag, target, words[4]) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let limit = match parse_aircon_integer(tag, words[5], "limit", Some((0, 65535))) {
                    Ok(value) => value as u16,
                    Err(response) => return response,
                };
                let mode = match parse_aircon_integer(tag, words[6], "mode", Some((0, 7))) {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                let humidity = sub.starts_with("SET_HUMIDITY_");
                let maximum = if humidity { 3 } else { 4 };
                if mode > maximum {
                    let family = if humidity { "Humidity" } else { "HVAC" };
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Operation failed: {target} ({family} Plant Mode is out of range: {mode})"
                        ),
                    );
                }
                let raw_level = match parse_aircon_boolean(tag, words[7], "rawlevel") {
                    Ok(value) => value,
                    Err(response) => return response,
                };
                match sub {
                    "SET_HVAC_UPPER_GUARD_LIMIT" => AirconCommand::HvacUpperGuardLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    "SET_HVAC_LOWER_GUARD_LIMIT" => AirconCommand::HvacLowerGuardLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    "SET_HVAC_SETBACK_LIMIT" => AirconCommand::HvacSetbackLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    "SET_HUMIDITY_UPPER_GUARD_LIMIT" => AirconCommand::HumidityUpperGuardLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    "SET_HUMIDITY_LOWER_GUARD_LIMIT" => AirconCommand::HumidityLowerGuardLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    "SET_HUMIDITY_SETBACK_LIMIT" => AirconCommand::HumiditySetbackLimit {
                        ward,
                        zones,
                        limit,
                        mode: mode as u8,
                        raw_level,
                    },
                    _ => unreachable!(),
                }
            }
        };

        let _commands = self.commands.lock().await;
        self.send_application(
            tag,
            Sal::Aircon(command),
            ok(tag, vec![], "200 OK."),
            "Air-Conditioning delivery",
        )
        .await
    }

    async fn trigger(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if response.status >= 400 {
            return response;
        }
        let Some(address) = words.get(2) else {
            return err(tag, 400, "400 Invalid Trigger Control address");
        };
        let Some((application, group)) = self.bound_group(address) else {
            return err(tag, 404, "404 Network is not connected to this service");
        };
        if application != 202 {
            return err(tag, 400, "400 Trigger Control application must be 202");
        }
        let (sal, selector) = if words[1].eq_ignore_ascii_case("EVENT") {
            let selector = words[3].parse::<u8>().expect("model validated selector");
            (
                Sal::TriggerEvent {
                    group_address: group,
                    action_selector: selector,
                },
                Some(selector),
            )
        } else {
            (
                Sal::TriggerIndicatorKill {
                    group_address: group,
                },
                None,
            )
        };
        let packet = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application,
            sals: vec![sal],
        };
        let pci = self.pci.read().await.clone();
        match pci.send_confirmed(&packet).await {
            Ok(()) => {
                if let Some(selector) = selector {
                    if let Some(network) = self
                        .model
                        .lock()
                        .await
                        .projects
                        .get_mut(&self.project)
                        .and_then(|p| p.networks.get_mut(&self.network))
                    {
                        network.levels.insert((202, group), selector);
                    }
                    let _ = self.events.send(format!(
                        "#e# trigger {address} event action={selector} sourceUnit=0"
                    ));
                } else {
                    let _ = self.events.send(format!(
                        "#e# trigger {address} indicatorkill action=-1 sourceUnit=0"
                    ));
                }
                response
            }
            Err(error) => err(tag, 502, &format!("502 Trigger delivery failed: {error}")),
        }
    }

    async fn label(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
        upper: &[String],
    ) -> Response {
        use std::sync::atomic::{AtomicU8, Ordering};
        static UNICODE_SEQUENCE: AtomicU8 = AtomicU8::new(0);

        let _commands = self.commands.lock().await;
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if response.status >= 400 {
            return response;
        }
        if words.len() < 8 {
            return err(
                tag,
                400,
                "400 Label command requires application, language, group, action, variant and mode",
            );
        }
        let Some(application) = self.application_path(words[2]) else {
            return err(tag, 404, "404 Label application is not on this network");
        };
        let expected = match upper[0].as_str() {
            "LIGHTING" if (48..=95).contains(&application) => true,
            "TRIGGER" if application == 202 => true,
            "ENABLE" if application == 203 => true,
            _ => false,
        };
        if !expected {
            return err(tag, 400, "400 Label family does not match the application");
        }
        if upper[0] == "ENABLE" && upper[1] == "UNICODELABEL" {
            return err(tag, 400, "400 ENABLE has no UNICODELABEL command");
        }
        let (Ok(language), Ok(group)) = (words[3].parse::<u8>(), words[4].parse::<u8>()) else {
            return err(tag, 400, "400 Invalid label language or group");
        };
        let action_selector = if words[5] == "-" {
            None
        } else {
            let Ok(action) = words[5].parse::<u8>() else {
                return err(tag, 400, "400 Invalid label action selector");
            };
            Some(action)
        };
        let Some(variant_text) = words[6]
            .strip_prefix('F')
            .or_else(|| words[6].strip_prefix('f'))
        else {
            return err(tag, 400, "400 Label variant must be F0..F3");
        };
        let Ok(variant) = variant_text.parse::<u8>() else {
            return err(tag, 400, "400 Label variant must be F0..F3");
        };
        if variant > 3 {
            return err(tag, 400, "400 Label variant must be F0..F3");
        }
        let decode_hex = |value: &str| {
            hex::decode(value).map_err(|_| "Label data must be contiguous hexadecimal bytes")
        };
        let encoded = if upper[1] == "UNICODELABEL" {
            if upper[7] != "RAW" || words.len() > 9 {
                return err(
                    tag,
                    400,
                    "400 UNICODELABEL requires RAW and optional hex data",
                );
            }
            let data = match words.get(8).map(|value| decode_hex(value)) {
                Some(Ok(data)) => data,
                Some(Err(error)) => return err(tag, 400, &format!("400 {error}")),
                None => Vec::new(),
            };
            let sequence = UNICODE_SEQUENCE.fetch_add(1, Ordering::Relaxed) & 15;
            match label::encode_unicode(
                application,
                group,
                language,
                &data,
                action_selector,
                variant,
                sequence,
            ) {
                Ok(encoded) => encoded,
                Err(error) => return err(tag, 400, &format!("400 {error}")),
            }
        } else {
            match upper[7].as_str() {
                "ICON" if words.len() == 9 => {
                    let Ok(icon) = words[8].parse::<u16>() else {
                        return err(tag, 400, "400 Invalid label icon selector");
                    };
                    let [high, low] = icon.to_be_bytes();
                    match label::encode_standard(
                        application,
                        group,
                        language,
                        2,
                        &[1, high, low],
                        action_selector,
                        variant,
                    ) {
                        Ok(payload) => vec![payload],
                        Err(error) => return err(tag, 400, &format!("400 {error}")),
                    }
                }
                "DYNAMIC" if words.len() == 13 => {
                    let (Ok(icon), Ok(width), Ok(height), Ok(vertical_offset)) = (
                        words[8].parse::<u16>(),
                        words[9].parse::<u8>(),
                        words[10].parse::<u8>(),
                        words[11].parse::<u8>(),
                    ) else {
                        return err(tag, 400, "400 Invalid dynamic icon metadata");
                    };
                    let data = match decode_hex(words[12]) {
                        Ok(data) => data,
                        Err(error) => return err(tag, 400, &format!("400 {error}")),
                    };
                    match label::encode_dynamic_icon(
                        application,
                        group,
                        language,
                        icon,
                        width,
                        height,
                        vertical_offset,
                        &data,
                        action_selector,
                        variant,
                    ) {
                        Ok(encoded) => encoded,
                        Err(error) => return err(tag, 400, &format!("400 {error}")),
                    }
                }
                "SET_LANGUAGE" if words.len() == 8 => {
                    match label::encode_standard(
                        application,
                        group,
                        language,
                        6,
                        &[],
                        action_selector,
                        variant,
                    ) {
                        Ok(payload) => vec![payload],
                        Err(error) => return err(tag, 400, &format!("400 {error}")),
                    }
                }
                _ if words.len() <= 9 => {
                    let Ok(options) = words[7].parse::<u8>() else {
                        return err(tag, 400, "400 Invalid label mode");
                    };
                    let data = match words.get(8).map(|value| decode_hex(value)) {
                        Some(Ok(data)) => data,
                        Some(Err(error)) => return err(tag, 400, &format!("400 {error}")),
                        None => Vec::new(),
                    };
                    match label::encode_standard(
                        application,
                        group,
                        language,
                        options,
                        &data,
                        action_selector,
                        variant,
                    ) {
                        Ok(payload) => vec![payload],
                        Err(error) => return err(tag, 400, &format!("400 {error}")),
                    }
                }
                _ => return err(tag, 400, "400 Invalid label command"),
            }
        };

        let pci = self.pci.read().await.clone();
        for payload in encoded {
            let packet = Packet::PointToMultipoint {
                meta: Meta::new(true, 0),
                application,
                sals: vec![Sal::DynamicLabel {
                    application,
                    payload: payload.clone(),
                }],
            };
            if let Err(error) = pci.send_confirmed(&packet).await {
                return err(tag, 502, &format!("502 Label delivery failed: {error}"));
            }
            self.record_label("sent-confirmed", None, application, &payload)
                .await;
        }
        response
    }

    async fn clear_edlt_labels(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if response.status >= 400 {
            return response;
        }
        let Some((project, network, unit)) = words
            .get(2)
            .and_then(|address| Server::split_unit(address))
            .filter(|(project, network, unit)| {
                *project == self.project && *network == self.network && (1..=254).contains(unit)
            })
        else {
            return err(tag, 404, "404 eDLT is not on this network");
        };
        let unit_type = self
            .model
            .lock()
            .await
            .projects
            .get(&project)
            .and_then(|project| project.networks.get(&network))
            .and_then(|network| network.units.get(&unit))
            .map(|record| record.unit_type.clone());
        match unit_type {
            None => return err(tag, 401, "401 Unit not found"),
            Some(unit_type) if !unit_type.eq_ignore_ascii_case("KEYGL5") => {
                return err(tag, 402, "402 Target is not a supported eDLT")
            }
            Some(_) => {}
        }

        let pci = self.pci.read().await.clone();
        match pci.clear_edlt_dynamic_labels(unit).await {
            Ok(()) => {
                // The clear operation is unit-specific while observed SAL is
                // network-wide. Discard the cache rather than return entries
                // that may now be stale for the requested display.
                self.observed_labels.lock().await.observations.clear();
                let _ = self.events.send(format!("#e# labels cleared {}", words[2]));
                response
            }
            Err(error) => err(tag, 502, &format!("502 eDLT label clear failed: {error}")),
        }
    }

    /// Native `LABEL CLEAR <application> <unit-id> [<key-number>]`.
    ///
    /// This is the standard point-to-point label-cache command, distinct
    /// from both an empty dynamic-label SAL and the OEM eDLT `CLEAREDLT`
    /// operation. Native accepts units 0..255 and keys 1..8. Completion is
    /// based only on the correlated PCI confirmation; there is no unit ACK
    /// or device readback, so a successful response does not prove that the
    /// target erased or persisted anything.
    async fn clear_dynamic_label_cache(&self, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        if !matches!(words.len(), 4 | 5) {
            return err(
                tag,
                400,
                "400 LABEL CLEAR requires an application, unit-id and optional key-number",
            );
        }
        let Some(application) = self.application_path(words[2]) else {
            return err(tag, 404, "404 Label application is not on this network");
        };
        if !((48..=95).contains(&application) || matches!(application, 202 | 203)) {
            return err(tag, 402, "402 Application does not support labels");
        }
        let Ok(unit) = words[3].parse::<u8>() else {
            return err(tag, 400, "400 Invalid label unit-id");
        };
        let key = match words.get(4) {
            Some(word) => match word.parse::<u8>() {
                Ok(key @ 1..=8) => Some(key),
                _ => return err(tag, 400, "400 Label key-number must be in 1..8"),
            },
            None => None,
        };

        let pci = self.pci.read().await.clone();
        match pci.clear_dynamic_label_cache(unit, key).await {
            Ok(()) => {
                // Observed dynamic-label traffic is network-wide and cannot
                // be attributed to a recipient. Any accepted cache clear can
                // therefore make every retained observation stale.
                self.observed_labels.lock().await.observations.clear();
                ok(tag, vec![], "200 OK")
            }
            Err(error) => err(
                tag,
                408,
                &format!("408 {} (command failed: {error})", words[2]),
            ),
        }
    }

    async fn label_kfi(&self, tag: &str, words: &[&str], upper: &[String]) -> Response {
        let _commands = self.commands.lock().await;
        let set = upper.get(1).is_some_and(|sub| sub == "KFISET");
        let expected_words = if set { 12 } else { 4 };
        if words.len() != expected_words {
            let syntax = if set {
                "400 LABEL KFISET requires an application, unit-id and eight KFI values"
            } else {
                "400 LABEL KFIGET requires an application and unit-id"
            };
            return err(tag, 400, syntax);
        }
        let Some(application) = self.application_path(words[2]) else {
            return err(tag, 404, "404 Label application is not on this network");
        };
        // Native kz uses the requested application only to resolve an object
        // and require `LabelSupportingApplication`. It passes the transport,
        // base network and unit to kv/kw; the application ID never enters the
        // KFI transaction, whose selector write is deliberately fixed at
        // `00 82 00 1C`. Mirror that class gate with the native label-capable
        // application families rather than rewriting 0x1C from this path.
        if !((48..=95).contains(&application) || matches!(application, 202 | 203)) {
            return err(tag, 402, "402 Application does not support labels");
        }
        let Ok(unit) = words[3].parse::<u8>() else {
            return err(tag, 400, "400 Invalid KFI unit-id");
        };
        let pci = self.pci.read().await.clone();
        if set {
            let mut values = [0u8; cbus_protocol::kfi::COUNT];
            for (value, word) in values.iter_mut().zip(&words[4..]) {
                let Ok(parsed) = word.parse::<u8>() else {
                    return err(tag, 400, "400 KFI values must be in 0..15");
                };
                if parsed > 15 {
                    return err(tag, 400, "400 KFI values must be in 0..15");
                }
                *value = parsed;
            }
            return match pci.set_key_function_indicators(unit, values).await {
                Ok(()) => ok(tag, vec![], "200 OK"),
                Err(error) => err(
                    tag,
                    408,
                    &format!("408 {} (command failed: {error})", words[2]),
                ),
            };
        }

        match pci.get_key_function_indicators(unit).await {
            Ok(replies) if replies.is_empty() => err(tag, 524, "524 No response."),
            Ok(replies) if replies.len() > 1 => err(tag, 524, "524 Too many responses."),
            Ok(replies) => {
                let values = replies[0];
                let mut rows = values
                    .iter()
                    .enumerate()
                    .map(|(index, value)| format!("kfi{}={value}", index + 1))
                    .collect::<Vec<_>>();
                let final_row = rows.pop().expect("KFI reply always has eight values");
                Response {
                    tag: tag.to_string(),
                    lines: rows.into_iter().map(|row| format!("300-{row}")).collect(),
                    final_text: format!("300 {final_row}"),
                    status: 300,
                }
            }
            Err(error) => err(
                tag,
                408,
                &format!("408 {} (command failed: {error})", words[2]),
            ),
        }
    }

    async fn enable(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(line)
        };
        if response.status >= 400 {
            return response;
        }
        let Some(address) = words.get(2) else {
            return err(tag, 400, "400 Invalid Enable Control address");
        };
        let Some((application, variable)) = self.bound_group(address) else {
            return err(tag, 404, "404 Network is not connected to this service");
        };
        if application != 203 {
            return err(tag, 400, "400 Enable Control application must be 203");
        }
        if words[1].eq_ignore_ascii_case("REMOVE") {
            // C-Gate's REMOVE is a server-side saved-value request. cmqttd
            // has no such file and preserves the live observed cache.
            return response;
        }
        let value = words[3].parse::<u8>().expect("model validated value");
        let packet = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application,
            sals: vec![Sal::EnableSetNetworkVariable { variable, value }],
        };
        let pci = self.pci.read().await.clone();
        match pci.send_confirmed(&packet).await {
            Ok(()) => {
                if let Some(network) = self
                    .model
                    .lock()
                    .await
                    .projects
                    .get_mut(&self.project)
                    .and_then(|p| p.networks.get_mut(&self.network))
                {
                    network.levels.insert((203, variable), value);
                }
                let _ = self.events.send(format!(
                    "#e# enable {address} set value={value} sourceUnit=0"
                ));
                response
            }
            Err(error) => err(tag, 502, &format!("502 Enable delivery failed: {error}")),
        }
    }

    async fn clock(&self, client: &ClientState, line: &str, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        let target = words.get(2).copied().unwrap_or("");
        if self.application_path(target) != Some(223) {
            return err(tag, 404, "404 Clock application is not on this network");
        }
        if words[1].eq_ignore_ascii_case("REQUEST_REFRESH") {
            let response = {
                let mut staged = self.model.lock().await.clone();
                staged.current = client
                    .current
                    .clone()
                    .or_else(|| Some(self.project.clone()));
                staged.handle(line)
            };
            if response.status >= 400 {
                return response;
            }
            return self
                .send_application(tag, Sal::ClockRequest, response, "Clock request")
                .await;
        }
        if words.len() == 3 {
            let mut model = self.model.lock().await;
            model.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            return model.handle(line);
        }
        if words.len() != 4 {
            let mut staged = self.model.lock().await.clone();
            return staged.handle(line);
        }
        let now = Local::now();
        let resolved = if words[3].eq_ignore_ascii_case("SYSTEM") {
            if words[1].eq_ignore_ascii_case("DATE") {
                format!("{:04}-{:02}-{:02}", now.year(), now.month(), now.day())
            } else {
                format!("{:02}:{:02}:{:02}", now.hour(), now.minute(), now.second())
            }
        } else {
            words[3].to_string()
        };
        let normalized = format!("[{tag}] CLOCK {} {target} {resolved}", words[1]);
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(&normalized)
        };
        if response.status >= 400 {
            return response;
        }
        let (key, sal) = if words[1].eq_ignore_ascii_case("DATE") {
            let date = NaiveDate::parse_from_str(&resolved, "%Y-%m-%d")
                .expect("model validated clock date");
            (
                "CLOCK DATE",
                Sal::ClockUpdateDate {
                    year: date.year() as u16,
                    month: date.month() as u8,
                    day: date.day() as u8,
                },
            )
        } else {
            let time = NaiveTime::parse_from_str(&resolved, "%H:%M:%S")
                .expect("model validated clock time");
            (
                "CLOCK TIME",
                Sal::ClockUpdateTime {
                    hour: time.hour() as u8,
                    minute: time.minute() as u8,
                    second: time.second() as u8,
                },
            )
        };
        let result = self
            .send_application(tag, sal, response, "Clock update")
            .await;
        if result.status < 400 {
            self.model
                .lock()
                .await
                .application_state
                .insert(key.to_string(), resolved);
        }
        result
    }

    async fn temperature(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let (response, address) = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            let response = staged.handle(line);
            let address = words
                .get(2)
                .and_then(|address| staged.qualify_group(address));
            (response, address)
        };
        if response.status >= 400 {
            return response;
        }
        if words
            .get(4)
            .is_some_and(|option| !option.eq_ignore_ascii_case("FORCE"))
        {
            return err(tag, 400, "400 Invalid TEMPERATURE BROADCAST option");
        }
        let Some(address) = address else {
            return err(tag, 400, "400 Invalid temperature group address");
        };
        let Some((application, group)) = self.bound_group(&address) else {
            return err(tag, 404, "404 Network is not connected to this service");
        };
        if application != 25 {
            return err(tag, 400, "400 Temperature application must be 25");
        }
        let Some(temperature) = words.get(3).and_then(|value| parse_temperature(value)) else {
            return err(tag, 405, "405 Temperature is out of range");
        };
        let temperature = f64::from((temperature * 4.0) as u8) / 4.0;
        let result = self
            .send_application(
                tag,
                Sal::TemperatureBroadcast {
                    group_address: group,
                    temperature,
                },
                response,
                "Temperature broadcast",
            )
            .await;
        if result.status < 400 {
            let address = format!("//{}/{}/25/{group}", self.project, self.network);
            let value = format_temperature(temperature);
            self.model.lock().await.application_state.insert(
                "TEMPERATURE BROADCAST".to_string(),
                format!("{address} {value}"),
            );
            let _ = self.events.send(format!(
                "#e# temperature broadcast {address} {value} sourceUnit=0"
            ));
        }
        result
    }

    async fn send_application(
        &self,
        tag: &str,
        sal: Sal,
        response: Response,
        operation: &str,
    ) -> Response {
        let packet = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: sal.application(),
            sals: vec![sal],
        };
        let pci = self.pci.read().await.clone();
        match pci.send_confirmed(&packet).await {
            Ok(()) => response,
            Err(error) => err(tag, 502, &format!("502 {operation} failed: {error}")),
        }
    }

    async fn read_memory(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 5 {
            return err(
                tag,
                400,
                "400 UNIT READMEM //PROJECT/NET/p/UNIT physical-address count",
            );
        }
        let Some((project, network, unit)) = Server::split_unit(words[2]) else {
            return err(tag, 400, "400 Invalid unit address");
        };
        if project != self.project || network != self.network {
            return err(tag, 404, "404 Network is not connected to this service");
        }
        let (Ok(address), Ok(count)) = (words[3].parse::<u32>(), words[4].parse::<usize>()) else {
            return err(tag, 400, "400 Invalid memory range");
        };
        if !(1..=4096).contains(&count) {
            return err(tag, 400, "400 Memory range must contain 1..4096 bytes");
        }
        {
            let model = self.model.lock().await;
            if !model
                .projects
                .get(&project)
                .and_then(|p| p.networks.get(&network))
                .is_some_and(|n| n.units.contains_key(&unit))
            {
                return err(tag, 404, "404 Unit is not in the configured project");
            }
        }
        let pci = self.pci.read().await.clone();
        match pci.read_memory(unit, address, count).await {
            Ok(bytes) => ok(tag, vec![serde_json::json!({"address":words[2],"physical_address":address,"data_hex":hex::encode(bytes),"source":"physical"}).to_string()], "200 OK"),
            Err(e) => err(tag, 502, &format!("502 Memory read failed: {e}")),
        }
    }

    async fn pp_load_physical(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        const MAX_PARAMETERS: usize = 4096;
        const MAX_UNIQUE_BYTES: usize = 1024 * 1024;

        let _commands = self.commands.lock().await;
        if words.len() < 4 {
            return err(tag, 400, "400 PP LOAD requires a session and source");
        }
        let Some((project, network, unit)) = Server::split_unit(words[3]) else {
            return err(tag, 400, "400 Invalid physical unit source");
        };
        if project != self.project || network != self.network {
            return err(tag, 404, "404 Network is not connected to this service");
        }
        let (session_name, session_lock) = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            let name = words[2];
            if staged.sessions.contains_key(name) && !client.sessions.contains(name) {
                return err(
                    tag,
                    420,
                    "420 Programming object belongs to another connection",
                );
            }
            let response = staged.handle(line);
            if response.status >= 400 {
                return response;
            }
            let Some(session) = staged.sessions.get(name) else {
                return err(tag, 404, "404 Session not found");
            };
            let Some(lock_address) = staged.locks.get(&session.lock) else {
                return err(tag, 409, "409 Lock not held");
            };
            if !self.bound_network(lock_address) {
                return err(
                    tag,
                    409,
                    "409 Session lock does not cover the physical network",
                );
            }
            (session.name.clone(), session.lock.clone())
        };

        let pci = self.pci.read().await.clone();
        let unit_type = match pci.identify_first(unit, 1).await {
            Ok(Some(bytes)) => match identity_text(&bytes, "unit type") {
                Ok(value) => value,
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP identity failed: {error}"),
                    )
                }
            },
            Ok(None) => return err(tag, 401, "401 Physical unit did not answer IDENTIFY"),
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 Physical PP identity failed: {error}"),
                )
            }
        };
        let firmware = match pci.identify_first(unit, 2).await {
            Ok(Some(bytes)) => match identity_text(&bytes, "firmware version") {
                Ok(value) => value,
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP identity failed: {error}"),
                    )
                }
            },
            Ok(None) => return err(tag, 408, "408 Physical unit provided no firmware identity"),
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 Physical PP identity failed: {error}"),
                )
            }
        };

        let tags = words[4..]
            .iter()
            .map(|value| dequote_value(value).to_ascii_lowercase())
            .collect::<HashSet<_>>();
        let spec = {
            let mut model = self.model.lock().await;
            match model.spec_for(&unit_type) {
                Some(spec) => spec,
                None => {
                    return err(
                        tag,
                        502,
                        &format!("502 No decoded unit specification is configured for {unit_type}"),
                    )
                }
            }
        };
        let selected = spec
            .iter()
            .filter(|param| {
                tags.is_empty()
                    || param
                        .tags
                        .iter()
                        .any(|candidate| tags.contains(&candidate.to_ascii_lowercase()))
            })
            .collect::<Vec<_>>();
        if selected.len() > MAX_PARAMETERS {
            return err(
                tag,
                502,
                "502 Unit specification exceeds the PP parameter limit",
            );
        }
        let mut layouts = Vec::with_capacity(selected.len());
        let mut recalls = HashMap::<u8, usize>::new();
        let mut paged_ranges = Vec::<(u32, u32)>::new();
        let mut memory_ranges = Vec::<(u32, u32)>::new();
        let mut goc_ranges = Vec::<(GocProgramming, u32, u32)>::new();
        for param in &selected {
            let layout = match unitspec::ParameterLayout::for_param(param) {
                Ok(layout) => layout,
                Err(error) => return err(tag, 502, &format!("502 {error}")),
            };
            match layout.transfer {
                unitspec::ParameterTransfer::Recall { parameter, count } => {
                    recalls
                        .entry(parameter)
                        .and_modify(|current| *current = (*current).max(count))
                        .or_insert(count);
                }
                unitspec::ParameterTransfer::Paged { address, count } => {
                    paged_ranges.push((address, address + count as u32));
                }
                unitspec::ParameterTransfer::Memory { address, count } => {
                    memory_ranges.push((address, address + count as u32));
                }
                unitspec::ParameterTransfer::GocMemory { address, count } => {
                    let Some(dialect) = goc_programming(param) else {
                        return err(tag, 502, "502 GOC parameter has no programming dialect");
                    };
                    goc_ranges.push((dialect, address, address + count as u32));
                }
            }
            layouts.push((*param, layout));
        }
        paged_ranges.sort_unstable();
        let mut paged_merged = Vec::<(u32, u32)>::new();
        for (start, end) in paged_ranges {
            if let Some(last) = paged_merged.last_mut() {
                if start <= last.1 {
                    last.1 = last.1.max(end);
                    continue;
                }
            }
            paged_merged.push((start, end));
        }
        memory_ranges.sort_unstable();
        let mut merged = Vec::<(u32, u32)>::new();
        for (start, end) in memory_ranges {
            if let Some(last) = merged.last_mut() {
                if start <= last.1 {
                    last.1 = last.1.max(end);
                    continue;
                }
            }
            merged.push((start, end));
        }
        goc_ranges.sort_unstable();
        let mut goc_merged = Vec::<(GocProgramming, u32, u32)>::new();
        for (dialect, start, end) in goc_ranges {
            if let Some(last) = goc_merged.last_mut() {
                if last.0 == dialect && start <= last.2 {
                    last.2 = last.2.max(end);
                    continue;
                }
            }
            goc_merged.push((dialect, start, end));
        }
        let unique_bytes = recalls.values().sum::<usize>()
            + paged_merged
                .iter()
                .map(|(start, end)| (*end - *start) as usize)
                .sum::<usize>()
            + merged
                .iter()
                .map(|(start, end)| (*end - *start) as usize)
                .sum::<usize>()
            + goc_merged
                .iter()
                .map(|(_, start, end)| (*end - *start) as usize)
                .sum::<usize>();
        if unique_bytes > MAX_UNIQUE_BYTES {
            return err(
                tag,
                502,
                "502 Unit specification exceeds the PP transfer limit",
            );
        }

        let mut recalled = HashMap::<u8, Vec<u8>>::new();
        let mut ordered_recalls = recalls.into_iter().collect::<Vec<_>>();
        ordered_recalls.sort_unstable_by_key(|(parameter, _)| *parameter);
        for (parameter, count) in ordered_recalls {
            match pci.recall_parameter(unit, parameter, count).await {
                Ok(bytes) => {
                    recalled.insert(parameter, bytes);
                }
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP parameter {parameter} read failed: {error}"),
                    )
                }
            }
        }
        let mut paged = Vec::<(u32, Vec<u8>)>::with_capacity(paged_merged.len());
        for (start, end) in paged_merged {
            match pci
                .recall_paged_parameter(unit, start, (end - start) as usize)
                .await
            {
                Ok(bytes) => paged.push((start, bytes)),
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP paged read failed: {error}"),
                    )
                }
            }
        }
        let mut memory = Vec::<(u32, Vec<u8>)>::with_capacity(merged.len());
        for (start, end) in merged {
            let mut bytes = Vec::with_capacity((end - start) as usize);
            while bytes.len() < (end - start) as usize {
                let address = start + bytes.len() as u32;
                let count = ((end - address) as usize).min(65_536);
                match pci.read_memory(unit, address, count).await {
                    Ok(chunk) => bytes.extend(chunk),
                    Err(error) => {
                        return err(
                            tag,
                            502,
                            &format!("502 Physical PP memory read failed: {error}"),
                        )
                    }
                }
            }
            memory.push((start, bytes));
        }
        let mut goc = Vec::<(GocProgramming, u32, Vec<u8>)>::with_capacity(goc_merged.len());
        for (dialect, start, end) in goc_merged {
            match pci
                .read_goc_memory(unit, start, (end - start) as usize, dialect)
                .await
            {
                Ok(bytes) => goc.push((dialect, start, bytes)),
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP GOC read failed: {error}"),
                    )
                }
            }
        }

        let mut params = HashMap::with_capacity(layouts.len());
        for (param, layout) in layouts {
            let data = match layout.transfer {
                unitspec::ParameterTransfer::Recall { parameter, count } => {
                    &recalled[&parameter][..count]
                }
                unitspec::ParameterTransfer::Paged { address, count } => {
                    let Some((start, bytes)) = paged.iter().find(|(start, bytes)| {
                        address >= *start
                            && u64::from(address) + count as u64
                                <= u64::from(*start) + bytes.len() as u64
                    }) else {
                        return err(tag, 500, "500 Physical PP paged plan was incomplete");
                    };
                    let offset = (address - *start) as usize;
                    &bytes[offset..offset + count]
                }
                unitspec::ParameterTransfer::Memory { address, count } => {
                    let Some((start, bytes)) = memory.iter().find(|(start, bytes)| {
                        address >= *start
                            && u64::from(address) + count as u64
                                <= u64::from(*start) + bytes.len() as u64
                    }) else {
                        return err(tag, 500, "500 Physical PP memory plan was incomplete");
                    };
                    let offset = (address - *start) as usize;
                    &bytes[offset..offset + count]
                }
                unitspec::ParameterTransfer::GocMemory { address, count } => {
                    let Some(dialect) = goc_programming(param) else {
                        return err(tag, 502, "502 GOC parameter has no programming dialect");
                    };
                    let Some((_, start, bytes)) = goc.iter().find(|(candidate, start, bytes)| {
                        *candidate == dialect
                            && address >= *start
                            && u64::from(address) + count as u64
                                <= u64::from(*start) + bytes.len() as u64
                    }) else {
                        return err(tag, 500, "500 Physical PP GOC plan was incomplete");
                    };
                    let offset = (address - *start) as usize;
                    &bytes[offset..offset + count]
                }
            };
            let value = match layout.decode(param, data) {
                Ok(value) => value,
                Err(error) => return err(tag, 502, &format!("502 {error}")),
            };
            params.insert(param.name.clone(), value);
        }

        let mut model = self.model.lock().await;
        let lock_held = model.locks.contains_key(&session_lock);
        let Some(session) = model.sessions.get_mut(&session_name) else {
            return err(
                tag,
                409,
                "409 Programming session ended during physical load",
            );
        };
        if session.lock != session_lock || !lock_held || !client.sessions.contains(&session_name) {
            return err(
                tag,
                409,
                "409 Programming session changed during physical load",
            );
        }
        session.source = Some(words[3].to_string());
        session.unit_type = Some(unit_type);
        session.firmware = Some(firmware);
        session.catalog_number = None;
        session.params = params;
        session.dirty.clear();
        ok(tag, vec![], "200 OK")
    }

    async fn pp_save_physical(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        const MAX_PARAMETERS: usize = 4096;
        const MAX_UNIQUE_BYTES: usize = 1024 * 1024;

        #[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
        enum Space {
            Standard,
            Paged,
            Memory,
            Giu,
            Sgiu,
            Dali,
            Goc,
            GocByt,
            Goc2,
        }
        struct Pending<'a> {
            param: &'a unitspec::SpecParam,
            layout: unitspec::ParameterLayout,
            value: String,
            space: Space,
            start: u32,
            end: u32,
            locked: bool,
        }
        struct Region {
            space: Space,
            start: u32,
            original: Vec<u8>,
            modified: Vec<u8>,
        }

        let _commands = self.commands.lock().await;
        let save_to_source = words
            .get(1)
            .is_some_and(|verb| verb.eq_ignore_ascii_case("SAVE_TO_SOURCE"));
        if (save_to_source && words.len() < 3) || (!save_to_source && words.len() < 4) {
            return err(tag, 400, "400 PP SAVE requires a session and destination");
        }
        let (session_name, session_lock, target, expected_type, expected_firmware, params, dirty) = {
            let model = self.model.lock().await;
            let name = words[2];
            if model.sessions.contains_key(name) && !client.sessions.contains(name) {
                return err(
                    tag,
                    420,
                    "420 Programming object belongs to another connection",
                );
            }
            let Some(session) = model.sessions.get(name) else {
                return err(tag, 404, "404 Session not found");
            };
            let Some(lock_address) = model.locks.get(&session.lock) else {
                return err(tag, 409, "409 Lock not held");
            };
            if !self.bound_network(lock_address) {
                return err(
                    tag,
                    409,
                    "409 Session lock does not cover the physical network",
                );
            }
            let target = if save_to_source {
                let Some(source) = session.source.clone() else {
                    return err(tag, 408, "408 Session has no loaded source");
                };
                source
            } else {
                words[3].to_string()
            };
            let Some(unit_type) = session.unit_type.clone() else {
                return err(tag, 408, "408 Session has no unit type");
            };
            let Some(firmware) = session.firmware.clone() else {
                return err(tag, 408, "408 Session has no firmware version");
            };
            (
                session.name.clone(),
                session.lock.clone(),
                target,
                unit_type,
                firmware,
                session.params.clone(),
                session.dirty.clone(),
            )
        };
        let Some((project, network, unit)) = Server::split_unit(&target) else {
            return err(tag, 400, "400 Invalid physical unit destination");
        };
        if project != self.project || network != self.network {
            return err(tag, 404, "404 Network is not connected to this service");
        }

        let tag_start = if save_to_source { 3 } else { 4 };
        let tags = words[tag_start..]
            .iter()
            .map(|value| dequote_value(value).to_ascii_lowercase())
            .collect::<HashSet<_>>();
        let spec = {
            let mut model = self.model.lock().await;
            match model.spec_for(&expected_type) {
                Some(spec) => spec,
                None => {
                    return err(
                        tag,
                        502,
                        &format!(
                            "502 No decoded unit specification is configured for {expected_type}"
                        ),
                    )
                }
            }
        };
        let requires_nvm_commit = unitspec::requires_nvm_commit(&spec);
        let pci = self.pci.read().await.clone();
        let live_type = match pci.identify_first(unit, 1).await {
            Ok(Some(bytes)) => match identity_text(&bytes, "unit type") {
                Ok(value) => value,
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP identity failed: {error}"),
                    )
                }
            },
            Ok(None) => return err(tag, 401, "401 Physical unit did not answer IDENTIFY"),
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 Physical PP identity failed: {error}"),
                )
            }
        };
        let live_firmware = match pci.identify_first(unit, 2).await {
            Ok(Some(bytes)) => match identity_text(&bytes, "firmware version") {
                Ok(value) => value,
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP identity failed: {error}"),
                    )
                }
            },
            Ok(None) => return err(tag, 408, "408 Physical unit provided no firmware identity"),
            Err(error) => {
                return err(
                    tag,
                    502,
                    &format!("502 Physical PP identity failed: {error}"),
                )
            }
        };
        if live_type != expected_type || live_firmware != expected_firmware {
            return err(
                tag,
                409,
                "409 Physical destination identity does not match the programming session",
            );
        }

        let mut pending = Vec::new();
        let mut cleared = HashSet::new();
        for name in &dirty {
            if !spec.iter().any(|candidate| candidate.name == *name) {
                return err(
                    tag,
                    502,
                    &format!("502 No schema exists for parameter {name:?}"),
                );
            }
        }
        // Unit-spec order is significant when several logical parameters
        // share one physical byte. Never let HashSet iteration choose which
        // staged value is applied last.
        for param in spec.iter().filter(|param| dirty.contains(&param.name)) {
            let name = &param.name;
            if !tags.is_empty()
                && !param
                    .tags
                    .iter()
                    .any(|candidate| tags.contains(&candidate.to_ascii_lowercase()))
            {
                continue;
            }
            let protection = param
                .get("Protection")
                .unwrap_or("none")
                .trim()
                .to_ascii_lowercase();
            if matches!(protection.as_str(), "factory" | "special") {
                cleared.insert(name.clone());
                continue;
            }
            if !matches!(protection.as_str(), "none" | "checksum" | "lock") {
                return err(
                    tag,
                    502,
                    &format!("502 Unsupported protection {protection:?} for {name:?}"),
                );
            }
            let layout = match unitspec::ParameterLayout::for_param(param) {
                Ok(layout) => layout,
                Err(error) => return err(tag, 502, &format!("502 {error}")),
            };
            let mut method = param
                .get("ProgramMethod")
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if method.is_empty() {
                method = "direct".to_string();
            }
            let locked = protection == "lock";
            let (space, start, count) = match layout.transfer {
                unitspec::ParameterTransfer::Recall { parameter, count }
                    if matches!(
                        method.as_str(),
                        "direct" | "giu" | "sgiu" | "dali" | "goc" | "gocbyt" | "goc2"
                    ) =>
                {
                    (Space::Standard, u32::from(parameter), count)
                }
                unitspec::ParameterTransfer::Paged { address, count }
                    if matches!(method.as_str(), "paged" | "ncc") =>
                {
                    (Space::Paged, address, count)
                }
                unitspec::ParameterTransfer::Memory { address, count }
                    if method == "edlt" && !locked =>
                {
                    (Space::Memory, address, count)
                }
                unitspec::ParameterTransfer::Memory { address, count }
                    if method == "giu" && !locked =>
                {
                    (Space::Giu, address, count)
                }
                unitspec::ParameterTransfer::Memory { address, count }
                    if method == "sgiu" && !locked =>
                {
                    (Space::Sgiu, address, count)
                }
                unitspec::ParameterTransfer::Memory { address, count }
                    if method == "dali" && !locked =>
                {
                    (Space::Dali, address, count)
                }
                unitspec::ParameterTransfer::GocMemory { address, count }
                    if method == "goc" && !locked =>
                {
                    (Space::Goc, address, count)
                }
                unitspec::ParameterTransfer::GocMemory { address, count }
                    if method == "gocbyt" && !locked =>
                {
                    (Space::GocByt, address, count)
                }
                unitspec::ParameterTransfer::GocMemory { address, count }
                    if method == "goc2" && !locked =>
                {
                    (Space::Goc2, address, count)
                }
                _ => {
                    return err(
                        tag,
                        502,
                        &format!("502 Unsupported program method {method:?} for {name:?}"),
                    )
                }
            };
            let Some(value) = params.get(name).cloned() else {
                return err(
                    tag,
                    502,
                    &format!("502 No staged value exists for {name:?}"),
                );
            };
            pending.push(Pending {
                param,
                layout,
                value,
                space,
                start,
                end: start + count as u32,
                locked,
            });
            cleared.insert(name.clone());
        }
        if pending.len() > MAX_PARAMETERS {
            return err(tag, 502, "502 PP save exceeds the parameter limit");
        }

        let mut ranges = pending
            .iter()
            .map(|item| (item.space, item.start, item.end))
            .collect::<Vec<_>>();
        ranges.sort_unstable();
        let mut merged = Vec::<(Space, u32, u32)>::new();
        for (space, start, end) in ranges {
            if let Some(last) = merged.last_mut() {
                if last.0 == space && start <= last.2 {
                    last.2 = last.2.max(end);
                    continue;
                }
            }
            merged.push((space, start, end));
        }
        let unique_bytes = merged
            .iter()
            .map(|(_, start, end)| (*end - *start) as usize)
            .sum::<usize>();
        if unique_bytes > MAX_UNIQUE_BYTES {
            return err(tag, 502, "502 PP save exceeds the transfer limit");
        }
        let mut regions = Vec::with_capacity(merged.len());
        for (space, start, end) in merged {
            let count = (end - start) as usize;
            let original = match space {
                Space::Standard if count <= u8::MAX as usize && end <= 256 => {
                    pci.recall_parameter(unit, start as u8, count).await
                }
                Space::Standard => return err(tag, 502, "502 Standard PP save range is too large"),
                Space::Paged => pci.recall_paged_parameter(unit, start, count).await,
                Space::Memory | Space::Giu | Space::Sgiu | Space::Dali => {
                    pci.read_memory(unit, start, count).await
                }
                Space::Goc => {
                    pci.read_goc_memory(unit, start, count, GocProgramming::Goc)
                        .await
                }
                Space::GocByt => {
                    pci.read_goc_memory(unit, start, count, GocProgramming::GocByt)
                        .await
                }
                Space::Goc2 => {
                    pci.read_goc_memory(unit, start, count, GocProgramming::Goc2)
                        .await
                }
            };
            let original = match original {
                Ok(bytes) => bytes,
                Err(error) => {
                    return err(
                        tag,
                        502,
                        &format!("502 Physical PP pre-read failed: {error}"),
                    )
                }
            };
            regions.push(Region {
                space,
                start,
                modified: original.clone(),
                original,
            });
        }
        let mut wrote_any = false;
        let mut confirmed: u32 = 0;
        for item in &pending {
            let Some(region) = regions.iter_mut().find(|region| {
                region.space == item.space
                    && item.start >= region.start
                    && item.end <= region.start + region.modified.len() as u32
            }) else {
                return err(tag, 500, "500 Physical PP save plan was incomplete");
            };
            let offset = (item.start - region.start) as usize;
            let count = (item.end - item.start) as usize;
            if let Err(error) = item.layout.encode_into(
                item.param,
                &item.value,
                &mut region.modified[offset..offset + count],
            ) {
                return err(tag, 502, &format!("502 {error}"));
            }
        }

        for item in &pending {
            let Some(region) = regions.iter().find(|region| {
                region.space == item.space
                    && item.start >= region.start
                    && item.end <= region.start + region.modified.len() as u32
            }) else {
                return err(tag, 500, "500 Physical PP save plan was incomplete");
            };
            let offset = (item.start - region.start) as usize;
            let count = (item.end - item.start) as usize;
            let original = &region.original[offset..offset + count];
            let modified = &region.modified[offset..offset + count];
            if modified == original {
                continue;
            }
            let result = match item.space {
                Space::Standard if item.locked => {
                    pci.store_locked_parameter_verified(unit, item.start as u8, modified)
                        .await
                }
                Space::Standard => {
                    pci.store_parameter_verified(unit, item.start as u8, modified)
                        .await
                }
                Space::Paged => {
                    pci.store_paged_parameter_verified(unit, item.start, modified, item.locked)
                        .await
                }
                Space::Memory => pci.write_memory_verified(unit, item.start, modified).await,
                Space::Giu => {
                    pci.write_giu_memory_verified(unit, item.start, modified)
                        .await
                }
                Space::Sgiu => {
                    pci.write_sgiu_memory_verified(unit, item.start, modified)
                        .await
                }
                Space::Dali => {
                    pci.write_dali_memory_verified(unit, item.start, modified)
                        .await
                }
                Space::Goc => {
                    pci.write_goc_memory_verified(unit, item.start, modified, GocProgramming::Goc)
                        .await
                }
                Space::GocByt => {
                    pci.write_goc_memory_verified(
                        unit,
                        item.start,
                        modified,
                        GocProgramming::GocByt,
                    )
                    .await
                }
                Space::Goc2 => {
                    pci.write_goc_memory_verified(unit, item.start, modified, GocProgramming::Goc2)
                        .await
                }
            };
            if let Err(error) = result {
                return err(
                    tag,
                    502,
                    &format!(
                        "502 Physical PP save failed after {confirmed} confirmed write(s): {error}"
                    ),
                );
            }
            wrote_any = true;
            confirmed += 1;
        }
        if wrote_any && requires_nvm_commit {
            if let Err(error) = pci.save_to_nvm(unit).await {
                return err(
                    tag,
                    502,
                    &format!(
                        "502 Physical PP Save-to-NVM failed after {confirmed} confirmed write(s): {error}"
                    ),
                );
            }
        }

        let mut model = self.model.lock().await;
        let lock_held = model.locks.contains_key(&session_lock);
        let Some(session) = model.sessions.get_mut(&session_name) else {
            return err(
                tag,
                409,
                "409 Programming session ended during physical save",
            );
        };
        if session.lock != session_lock || !lock_held || !client.sessions.contains(&session_name) {
            return err(
                tag,
                409,
                "409 Programming session changed during physical save",
            );
        }
        session.source = Some(target);
        session.dirty.retain(|name| !cleared.contains(name));
        // Bare 200 covers the tag-selected subset only: tag-filtered params
        // stay dirty for a later matching-tags SAVE, discoverable via dirty.
        ok(tag, vec![], "200 OK")
    }

    async fn lighting(&self, client: &ClientState, line: &str, tag: &str) -> Response {
        let _commands = self.commands.lock().await;
        let (response, event) = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.drain_events();
            // STOP is valid even if no brightness was observed. Seed only
            // the disposable validation model; this is never a live level.
            if let Ok(command) = parse_command(line) {
                let parts: Vec<_> = command.body.split_whitespace().collect();
                let index = if parts
                    .first()
                    .is_some_and(|s| s.eq_ignore_ascii_case("TERMINATERAMP"))
                {
                    Some(1)
                } else if parts
                    .first()
                    .is_some_and(|s| s.eq_ignore_ascii_case("LIGHTING"))
                    && parts.get(1).is_some_and(|s| {
                        s.eq_ignore_ascii_case("STOP") || s.eq_ignore_ascii_case("TERMINATERAMP")
                    })
                {
                    Some(2)
                } else {
                    None
                };
                if let Some((app, group)) = index
                    .and_then(|i| parts.get(i))
                    .and_then(|a| staged.qualify_group(a))
                    .and_then(|a| self.bound_group(&a))
                {
                    if let Some(net) = staged
                        .projects
                        .get_mut(&self.project)
                        .and_then(|p| p.networks.get_mut(&self.network))
                    {
                        net.levels.entry((app, group)).or_insert(0);
                    }
                }
            }
            let response = staged.handle(line);
            let event = staged
                .drain_events()
                .into_iter()
                .find(|e| e.starts_with("#e# lighting "));
            (response, event)
        };
        if response.status >= 400 {
            return response;
        }
        let Some(event) = event else {
            return err(tag, 408, "408 No live group state available");
        };
        let words: Vec<_> = event.split_whitespace().collect();
        let Some((app, group)) = self.bound_group(words[2]) else {
            return err(tag, 404, "404 Network is not connected to this service");
        };
        if !(48..=95).contains(&app) {
            return err(tag, 400, "400 Not a lighting application");
        }
        let sal = match words[3] {
            "ON" => Sal::LightingOn {
                application: app,
                group_address: group,
            },
            "OFF" => Sal::LightingOff {
                application: app,
                group_address: group,
            },
            "RAMP" => Sal::LightingRamp {
                application: app,
                group_address: group,
                level: words[4].parse().unwrap(),
                duration: words[5].parse().unwrap(),
            },
            "STOP" => Sal::LightingTerminateRamp {
                application: app,
                group_address: group,
            },
            _ => return err(tag, 502, "502 Unsupported lighting operation"),
        };
        let packet = Packet::PointToMultipoint {
            meta: Meta::new(true, 0),
            application: app,
            sals: vec![sal],
        };
        let pci = self.pci.read().await.clone();
        // The previous observation predates this command. Invalidate it before
        // sending so a report arriving ahead of the confirmation is retained.
        if let Some(net) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|p| p.networks.get_mut(&self.network))
        {
            net.levels.remove(&(app, group));
        }
        match pci.send_confirmed(&packet).await {
            Ok(()) => {
                let _ = self.events.send(event);
                // Queue physical readback through the existing background lane.
                tokio::spawn(async move {
                    let _ = pci.request_status(group & 0xe0, app, true).await;
                });
                response
            }
            Err(e) => err(tag, 502, &format!("502 Lighting delivery failed: {e}")),
        }
    }

    async fn scene(&self, client: &ClientState, line: &str, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        let (response, snapshot) = {
            let mut model = self.model.lock().await;
            model.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));

            // Let the compatibility model own the command grammar and the
            // native 401 response for an unknown scene. RECORD must use only
            // genuine observations from this service's configured network.
            if words.len() == 4 && words[1].eq_ignore_ascii_case("RECORD") {
                let key = format!("{}/{}", words[2], words[3]);
                let snapshot = model
                    .projects
                    .get(&self.project)
                    .and_then(|project| project.networks.get(&self.network))
                    .map(|network| {
                        let mut values = network
                            .levels
                            .iter()
                            .filter(|((application, _), _)| (48..=95).contains(application))
                            .map(|((application, group), level)| {
                                (
                                    format!(
                                        "//{}/{}/{application}/{group}",
                                        self.project, self.network
                                    ),
                                    *level,
                                )
                            })
                            .collect::<Vec<_>>();
                        values.sort();
                        values
                    })
                    .unwrap_or_default();
                let before = model.scene_snapshots.insert(key.clone(), snapshot);
                let database = Database::from_server(&model);
                if let Err(error) = database.save(&self.state_path) {
                    if let Some(before) = before {
                        model.scene_snapshots.insert(key, before);
                    } else {
                        model.scene_snapshots.remove(&key);
                    }
                    tracing::error!("C-Gate scene commit failed: {error}");
                    return err(tag, 500, "500 Database commit failed; scene not recorded");
                }
                (ok(tag, vec![], "200 OK."), None)
            } else {
                let mut staged = model.clone();
                staged.current = model.current.clone();
                let response = staged.handle(line);
                let snapshot = if response.status < 400
                    && words.len() == 4
                    && words[1].eq_ignore_ascii_case("PLAY")
                {
                    model
                        .scene_snapshots
                        .get(&format!("{}/{}", words[2], words[3]))
                        .cloned()
                } else {
                    None
                };
                (response, snapshot)
            }
        };
        if response.status >= 400
            || words
                .get(1)
                .is_some_and(|word| word.eq_ignore_ascii_case("RECORD"))
        {
            return response;
        }
        let Some(snapshot) = snapshot else {
            return response;
        };

        let mut actions = Vec::with_capacity(snapshot.len());
        for (address, level) in snapshot {
            let Some((application, group)) = self.bound_group(&address) else {
                return err(
                    tag,
                    409,
                    "409 Scene contains an address outside this network",
                );
            };
            if !(48..=95).contains(&application) {
                return err(tag, 409, "409 Scene contains a non-lighting address");
            }
            actions.push((address, application, group, level));
        }

        let pci = self.pci.read().await.clone();
        let total = actions.len();
        let mut status_blocks = HashSet::new();
        for (delivered, (address, application, group, level)) in actions.into_iter().enumerate() {
            if let Some(network) = self
                .model
                .lock()
                .await
                .projects
                .get_mut(&self.project)
                .and_then(|project| project.networks.get_mut(&self.network))
            {
                network.levels.remove(&(application, group));
            }
            let packet = Packet::PointToMultipoint {
                meta: Meta::new(true, 0),
                application,
                sals: vec![Sal::LightingRamp {
                    application,
                    group_address: group,
                    level,
                    duration: 0,
                }],
            };
            if let Err(error) = pci.send_confirmed(&packet).await {
                return err(
                    tag,
                    502,
                    &format!(
                        "502 Scene delivery failed after {delivered} of {total} actions: {error}"
                    ),
                );
            }
            status_blocks.insert((application, group & 0xe0));
            let _ = self
                .events
                .send(format!("#e# lighting {address} RAMP {level} 0"));
        }
        for (application, block) in status_blocks {
            let pci = pci.clone();
            tokio::spawn(async move {
                let _ = pci.request_status(block, application, true).await;
            });
        }
        response
    }

    async fn do_method(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 {
            return err(tag, 400, "400 DO requires an object and method");
        }
        let method = words[2].to_ascii_uppercase();
        let response = if matches!(method.as_str(), "ON" | "OFF" | "RAMP" | "TERMINATERAMP") {
            let mut command = vec![method, words[1].to_string()];
            command.extend(words[3..].iter().map(|word| (*word).to_string()));
            let line = format!("[{tag}] {}", command.join(" "));
            self.lighting(client, &line, tag).await
        } else if method == "SYNC" {
            let command = ["NET", "SYNC", words[1]];
            let line = format!("[{tag}] NET SYNC {}", words[1]);
            self.net_sync(client, &line, tag, &command).await
        } else if method == "UNRAVEL" {
            return err(
                tag,
                502,
                "502 DO UNRAVEL requires a physical backend that is not implemented",
            );
        } else if method == "FACTORYDEFAULT" {
            self.factory_default_edlt(client, tag, words).await
        } else {
            return err(tag, 402, "402 Method not supported by object");
        };
        if response.status >= 400 {
            response
        } else {
            Response {
                tag: tag.to_string(),
                lines: response.lines,
                final_text: format!("202 Done: {}", words[1]),
                status: 202,
            }
        }
    }

    async fn factory_default_edlt(
        &self,
        client: &ClientState,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        let response = {
            let mut staged = self.model.lock().await.clone();
            staged.current = client
                .current
                .clone()
                .or_else(|| Some(self.project.clone()));
            staged.handle(&format!("[{tag}] {}", words.join(" ")))
        };
        if response.status >= 400 {
            return response;
        }
        let Some((project, network, unit)) = words
            .get(1)
            .and_then(|address| Server::split_unit(address))
            .filter(|(project, network, unit)| {
                *project == self.project && *network == self.network && (1..=254).contains(unit)
            })
        else {
            return err(tag, 404, "404 eDLT is not on this network");
        };
        let unit_type = self
            .model
            .lock()
            .await
            .projects
            .get(&project)
            .and_then(|project| project.networks.get(&network))
            .and_then(|network| network.units.get(&unit))
            .map(|record| record.unit_type.clone());
        match unit_type {
            None => return err(tag, 401, "401 Unit not found"),
            Some(unit_type) if !unit_type.eq_ignore_ascii_case("KEYGL5") => {
                return err(tag, 402, "402 Target is not a supported eDLT")
            }
            Some(_) => {}
        }

        let pci = self.pci.read().await.clone();
        match pci.factory_default_edlt(unit).await {
            Ok(()) => {
                // FactoryDefault can invalidate every cached display label.
                // It does not change the saved database representation here.
                self.observed_labels.lock().await.observations.clear();
                let _ = self
                    .events
                    .send(format!("#e# factory default accepted {}", words[1]));
                ok(tag, vec![], "200 OK")
            }
            Err(error) => err(
                tag,
                502,
                &format!("502 eDLT factory default failed: {error}"),
            ),
        }
    }

    async fn clock_summaries(&self) -> Result<(Vec<ClockSummary>, Vec<String>), String> {
        let mut addresses = {
            let model = self.model.lock().await;
            model.projects[&self.project].networks[&self.network]
                .physical
                .keys()
                .copied()
                .collect::<Vec<_>>()
        };
        if addresses.is_empty() {
            return Err(
                "network has no synchronized physical inventory; run NET SYNC first".into(),
            );
        }
        addresses.sort_unstable();
        let pci = self.pci.read().await.clone();
        let mut summaries = Vec::new();
        let mut failures = Vec::new();
        for address in addresses {
            match pci.identify_first(address, 16).await {
                Ok(Some(data)) if data.len() == 4 => {
                    summaries.push(ClockSummary {
                        address,
                        active: data[0] & 0x01 != 0,
                        enabled: data[0] & 0x02 != 0,
                        burden: data[0] & 0x80 != 0,
                    });
                }
                Ok(_) => failures.push(format!(
                    "120-Failed to obtain output unit summary from address {address}."
                )),
                Err(error) => {
                    return Err(format!(
                        "output unit summary failed at address {address}: {error}"
                    ));
                }
            }
        }
        Ok((summaries, failures))
    }

    async fn set_clock_enabled(&self, address: u8, enabled: bool) -> Result<bool, String> {
        let unit_type = {
            let model = self.model.lock().await;
            model.projects[&self.project].networks[&self.network]
                .physical
                .get(&address)
                .map(|unit| unit.unit_type.clone())
                .filter(|value| !value.is_empty())
                .ok_or_else(|| "physical unit type is unknown; run NET SYNC first".to_string())?
        };
        let (param, layout) = {
            let mut model = self.model.lock().await;
            let spec = model.spec_for(&unit_type).ok_or_else(|| {
                format!("no decoded unit specification is configured for {unit_type}")
            })?;
            let param = spec
                .into_iter()
                .find(|param| param.name == "ClockGenEnable")
                .ok_or_else(|| format!("{unit_type} has no ClockGenEnable parameter"))?;
            let method = param
                .get("ProgramMethod")
                .unwrap_or("direct")
                .trim()
                .to_ascii_lowercase();
            if !method.is_empty() && method != "direct" {
                return Err(format!(
                    "ClockGenEnable uses unsupported programming method {method:?}"
                ));
            }
            let layout = unitspec::ParameterLayout::for_param(&param)?;
            (param, layout)
        };
        let unitspec::ParameterTransfer::Recall { parameter, count } = layout.transfer else {
            return Err("ClockGenEnable is not a direct CAL parameter".into());
        };
        let pci = self.pci.read().await.clone();
        let mut data = pci
            .recall_parameter(address, parameter, count)
            .await
            .map_err(|error| format!("ClockGenEnable read failed: {error}"))?;
        let before = data.clone();
        layout.encode_into(&param, if enabled { "1" } else { "0" }, &mut data)?;
        if data == before {
            return Ok(false);
        }
        match param
            .get("Protection")
            .unwrap_or("none")
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "none" | "checksum" => {
                pci.store_parameter_verified(address, parameter, &data)
                    .await
            }
            "lock" => {
                pci.store_locked_parameter_verified(address, parameter, &data)
                    .await
            }
            protection => {
                return Err(format!(
                    "ClockGenEnable uses unsupported protection {protection:?}"
                ));
            }
        }
        .map_err(|error| format!("ClockGenEnable write failed: {error}"))?;
        Ok(true)
    }

    async fn net_clocks(&self, tag: &str, words: &[&str]) -> Response {
        let _commands = self.commands.lock().await;
        if !(3..=4).contains(&words.len()) || !self.bound_network(words[2]) {
            return err(tag, 400, "400 NET CLOCKS requires the configured network");
        }
        enum Action {
            Inspect,
            Target(usize),
            Recover,
        }
        let action = match words.get(3) {
            None => Action::Inspect,
            Some(value) if value.eq_ignore_ascii_case("R") => Action::Recover,
            Some(value) => match value.parse::<usize>() {
                Ok(target @ 1..=10) => Action::Target(target),
                _ => return err(tag, 400, "400 Clock target must be in 1..10"),
            },
        };
        let (summaries, mut lines) = match self.clock_summaries().await {
            Ok(value) => value,
            Err(error) => {
                return err(
                    tag,
                    408,
                    &format!("408 Physical clock query failed: {error}"),
                )
            }
        };
        for summary in &summaries {
            lines.push(format!(
                "120-address={} output_units=1 clocks_enabled={} clocks_active={} burdens_enabled={}",
                summary.address,
                u8::from(summary.enabled),
                u8::from(summary.active),
                u8::from(summary.burden)
            ));
        }
        match action {
            Action::Inspect => {}
            Action::Recover => {
                let gateways = {
                    let model = self.model.lock().await;
                    model.projects[&self.project].networks[&self.network]
                        .units
                        .values()
                        .filter(|unit| {
                            let unit_type = unit.unit_type.to_ascii_uppercase();
                            unit_type.starts_with("PC_CNI") || unit_type.starts_with("PC_PCI")
                        })
                        .map(|unit| unit.address)
                        .collect::<Vec<_>>()
                };
                let [gateway] = gateways.as_slice() else {
                    return err(tag, 408, "408 Physical gateway identity is not unique");
                };
                match self.set_clock_enabled(*gateway, true).await {
                    Ok(true) => lines.push(format!(
                        "120-Gateway clock at address {gateway} is now enabled."
                    )),
                    Ok(false) => {}
                    Err(error) => lines.push(format!(
                        "120-Clock at address {gateway} could NOT be enabled: {error}"
                    )),
                }
            }
            Action::Target(target) => {
                let enabled = summaries.iter().filter(|summary| summary.enabled).count();
                let changes = if enabled < target {
                    summaries
                        .iter()
                        .filter(|summary| !summary.enabled)
                        .map(|summary| (summary.address, true))
                        .take(target - enabled)
                        .collect::<Vec<_>>()
                } else {
                    let mut candidates = summaries
                        .iter()
                        .filter(|summary| summary.enabled)
                        .copied()
                        .collect::<Vec<_>>();
                    candidates.sort_by_key(|summary| summary.active);
                    candidates
                        .into_iter()
                        .map(|summary| (summary.address, false))
                        .take(enabled - target)
                        .collect::<Vec<_>>()
                };
                for (address, value) in changes {
                    let operation = if value { "enabled" } else { "disabled" };
                    match self.set_clock_enabled(address, value).await {
                        Ok(true) => lines.push(format!(
                            "120-Clock at address {address} is now {operation}."
                        )),
                        Ok(false) => {}
                        Err(error) => lines.push(format!(
                            "120-Clock at address {address} could NOT be {operation}: {error}"
                        )),
                    }
                }
            }
        }
        ok(tag, lines, "200 OK.")
    }

    /// Run a bounded listener. The caller owns binding and task supervision.
    pub async fn serve(self: Arc<Self>, listener: TcpListener) -> io::Result<()> {
        let slots = Arc::new(Semaphore::new(64));
        loop {
            let permit = slots
                .clone()
                .acquire_owned()
                .await
                .map_err(io::Error::other)?;
            let (stream, _) = listener.accept().await?;
            let service = self.clone();
            tokio::spawn(async move {
                let _permit = permit;
                if let Err(e) = service.connection(stream).await {
                    tracing::debug!("C-Gate connection ended: {e}");
                }
            });
        }
    }

    /// TLS variant of [`Service::serve`]: each accepted connection
    /// completes a rustls server handshake before entering the shared
    /// per-connection handler. A failed handshake drops only that
    /// connection; the listener stays up. No TLS client authentication
    /// is performed here (P4b is transport-only); the
    /// optional command-layer LOGIN gate (see [`Service::set_auth_token_hash`])
    /// is independent of TLS.
    /// The caller owns binding and task supervision.
    ///
    /// The pre-handshake accept is bounded by
    /// [`TLS_HANDSHAKE_TIMEOUT`] so a stalled client cannot hold a
    /// 64-slot semaphore permit forever. Use
    /// [`Service::serve_tls_with_timeout`] in tests for a short bound.
    pub async fn serve_tls(
        self: Arc<Self>,
        listener: TcpListener,
        tls: Arc<rustls::ServerConfig>,
    ) -> io::Result<()> {
        self.serve_tls_with_timeout(listener, tls, TLS_HANDSHAKE_TIMEOUT)
            .await
    }

    /// [`Service::serve_tls`] with an explicit handshake bound.
    pub async fn serve_tls_with_timeout(
        self: Arc<Self>,
        listener: TcpListener,
        tls: Arc<rustls::ServerConfig>,
        timeout: Duration,
    ) -> io::Result<()> {
        let acceptor = tokio_rustls::TlsAcceptor::from(tls);
        let slots = Arc::new(Semaphore::new(64));
        loop {
            let permit = slots
                .clone()
                .acquire_owned()
                .await
                .map_err(io::Error::other)?;
            let (stream, _) = listener.accept().await?;
            let acceptor = acceptor.clone();
            let service = self.clone();
            tokio::spawn(async move {
                let _permit = permit;
                match tokio::time::timeout(timeout, acceptor.accept(stream)).await {
                    Ok(Ok(tls_stream)) => {
                        if let Err(e) = service.connection_tls(tls_stream).await {
                            tracing::debug!("C-Gate TLS connection ended: {e}");
                        }
                    }
                    Ok(Err(e)) => {
                        tracing::debug!("C-Gate TLS handshake failed: {e}");
                    }
                    Err(_) => {
                        tracing::debug!("C-Gate TLS handshake timed out");
                    }
                }
            });
        }
    }

    async fn connection(&self, stream: TcpStream) -> io::Result<()> {
        let origin = format!("/{}", stream.peer_addr()?);
        let (reader, writer) = stream.into_split();
        self.connection_io(BufReader::new(reader), writer, origin)
            .await
    }

    async fn connection_tls(
        &self,
        stream: tokio_rustls::server::TlsStream<TcpStream>,
    ) -> io::Result<()> {
        let origin = format!("/{}", stream.get_ref().0.peer_addr()?);
        let (reader, writer) = tokio::io::split(stream);
        self.connection_io(BufReader::new(reader), writer, origin)
            .await
    }

    /// Shared per-connection handler for plaintext and TLS streams alike.
    async fn connection_io<R, W>(
        &self,
        mut reader: BufReader<R>,
        mut writer: W,
        origin: String,
    ) -> io::Result<()>
    where
        R: tokio::io::AsyncRead + Unpin,
        W: tokio::io::AsyncWrite + Unpin,
    {
        let mut events = self.events.subscribe();
        let mut mode = EventMode::OFF;
        let mut client = ClientState::default();
        let command_session = self.command_sessions.lock().await.register(origin);
        client.command_session = Some(command_session);
        let mut pending_line = Vec::new();
        let mut graceful_close = false;
        let result = async {
            writer.write_all(b"201 cmqttd C-Gate service ready\r\n").await?;
            loop {
                tokio::select! {
                    result = bounded_line(&mut reader, &mut pending_line) => {
                        let Some(line) = result? else { return Ok(()); };
                        let tagged = line.starts_with('[');
                        if let Some((head, delimiter)) = split_heredoc(&line) {
                            let command = if tagged { head } else { format!("[untagged] {head}") };
                            let (mut response, close_after_reply) = match bounded_document(&mut reader, &delimiter).await? {
                                DocumentRead::Complete(document) => {
                                    (self.handle_document(&mut client, &command, &document).await, false)
                                }
                                DocumentRead::Exceeded => {
                                    let tag = parse_command(&command).map_or_else(|_| String::new(), |c| c.tag);
                                    (err(&tag, 400, "400 document exceeded configured limit"), false)
                                }
                                DocumentRead::Truncated => {
                                    let tag = parse_command(&command).map_or_else(|_| String::new(), |c| c.tag);
                                    (err(&tag, 400, "400 truncated here-document"), true)
                                }
                            };
                            if !tagged { response.tag.clear(); }
                            tokio::time::timeout(Duration::from_secs(10), writer.write_all(format_response(&response).replace('\n', "\r\n").as_bytes())).await
                                .map_err(|_| io::Error::new(io::ErrorKind::TimedOut,"C-Gate client is not reading"))??;
                            if close_after_reply {
                                return Ok(());
                            }
                            continue;
                        }
                        let command = if tagged {line} else {format!("[untagged] {line}")};
                        let parsed = parse_command(&command).ok();
                        let close = parsed.as_ref().is_some_and(|c| {
                            let words: Vec<_> = c.body.split_whitespace().collect();
                            words.len() == 1 && matches!(words[0].to_ascii_uppercase().as_str(), "QUIT" | "EXIT")
                        });
                        let mut response = if let Some(c) = parsed.as_ref().filter(|c| c.body.split_whitespace().next().is_some_and(|w| w.eq_ignore_ascii_case("EVENT") || w.eq_ignore_ascii_case("EVENTS"))) {
                            let words: Vec<_> = c.body.split_whitespace().collect();
                            if words.len() == 1 { Response {tag:c.tag.clone(), lines:vec![], final_text:format!("306 {}", mode), status:306} }
                            else if words.len() == 2 {
                                if let Some(new) = EventMode::parse(words[1]) { mode = new; ok(&c.tag, vec![], "200 OK.") }
                                else { err(&c.tag, 400, "400 Invalid event mode") }
                            } else { err(&c.tag, 400, "400 Invalid event command") }
                        } else { self.handle(&mut client, &command).await };
                        if !tagged { response.tag.clear(); }
                        tokio::time::timeout(Duration::from_secs(10), writer.write_all(format_response(&response).replace('\n', "\r\n").as_bytes())).await
                            .map_err(|_| io::Error::new(io::ErrorKind::TimedOut,"C-Gate client is not reading"))??;
                        if close && response.status == 204 {
                            // `write_all` only guarantees that the plaintext
                            // was accepted by the AsyncWrite implementation.
                            // In particular, rustls may still hold the final
                            // TLS record, so flush it before dropping the
                            // connection and making the 204 observable.
                            tokio::time::timeout(Duration::from_secs(10), writer.flush()).await
                                .map_err(|_| io::Error::new(io::ErrorKind::TimedOut,"C-Gate closing reply did not flush"))??;
                            graceful_close = true;
                            return Ok(());
                        }
                    }
                    event = events.recv() => match event {
                        Ok(event) if mode.delivers(event_category(&event)) => {
                            tokio::time::timeout(Duration::from_secs(10), writer.write_all(format!("{event}\r\n").as_bytes())).await
                                .map_err(|_| io::Error::new(io::ErrorKind::TimedOut,"C-Gate event client is not reading"))??;
                        }
                        Err(broadcast::error::RecvError::Lagged(_)) if !mode.is_off() => return Err(io::Error::other("C-Gate event queue overflow")),
                        _ => {},
                    }
                }
            }
        }.await;
        self.command_sessions
            .lock()
            .await
            .sessions
            .remove(&command_session);
        let mut model = self.model.lock().await;
        for name in client.sessions {
            model.sessions.remove(&name);
        }
        for name in client.locks {
            model.locks.remove(&name);
        }
        drop(model);
        if graceful_close {
            tokio::time::timeout(Duration::from_secs(10), writer.shutdown())
                .await
                .map_err(|_| {
                    io::Error::new(
                        io::ErrorKind::TimedOut,
                        "C-Gate connection did not close cleanly",
                    )
                })??;
        }
        result
    }
}

enum DocumentLine {
    Line(String),
    Exceeded,
    Eof,
}

enum DocumentRead {
    Complete(String),
    Exceeded,
    Truncated,
}

/// Collect a normalized LF-separated here-document without allocating an
/// unbounded line. Once a limit is exceeded the rest of the document is still
/// drained through its delimiter, keeping the command stream synchronized.
async fn bounded_document<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
    delimiter: &str,
) -> io::Result<DocumentRead> {
    let mut document = String::new();
    let mut exceeded = false;
    loop {
        match bounded_document_line(reader).await? {
            DocumentLine::Line(line) if line == delimiter => {
                return Ok(if exceeded {
                    DocumentRead::Exceeded
                } else {
                    DocumentRead::Complete(document)
                });
            }
            DocumentLine::Line(line) => {
                if exceeded || document.len() + line.len() + 1 > MAX_DOCUMENT {
                    exceeded = true;
                } else {
                    document.push_str(&line);
                    document.push('\n');
                }
            }
            DocumentLine::Exceeded => exceeded = true,
            DocumentLine::Eof => return Ok(DocumentRead::Truncated),
        }
    }
}

async fn bounded_document_line<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
) -> io::Result<DocumentLine> {
    let mut line = Vec::new();
    let mut exceeded = false;
    loop {
        let buf = reader.fill_buf().await?;
        if buf.is_empty() {
            return Ok(DocumentLine::Eof);
        }
        let count = buf
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(buf.len(), |position| position + 1);
        if !exceeded && line.len() + count <= MAX_LINE {
            line.extend_from_slice(&buf[..count]);
        } else {
            exceeded = true;
        }
        let done = buf[count - 1] == b'\n';
        reader.consume(count);
        if !done {
            continue;
        }
        if exceeded {
            return Ok(DocumentLine::Exceeded);
        }
        line.pop();
        if line.last() == Some(&b'\r') {
            line.pop();
        }
        return String::from_utf8(line)
            .map(DocumentLine::Line)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error));
    }
}

/// Split a native `[tag] COMMAND << DELIMITER` header. Delimiters are short,
/// visible, single tokens; malformed headers remain ordinary commands and are
/// rejected by their command handler.
fn split_heredoc(line: &str) -> Option<(String, String)> {
    let (head, delimiter) = line.split_once(" << ")?;
    let delimiter = delimiter.trim();
    if delimiter.is_empty() || delimiter.len() > 128 || delimiter.contains([' ', '\t', '\r', '\n'])
    {
        return None;
    }
    Some((head.to_string(), delimiter.to_string()))
}

fn preserve_physical_state(before: &Server, model: &mut Server) {
    for (project_name, project) in &mut model.projects {
        for (network_address, network) in &mut project.networks {
            network.physical = before
                .projects
                .get(project_name)
                .and_then(|project| project.networks.get(network_address))
                .map(|network| network.physical.clone())
                .unwrap_or_default();
        }
    }
}

fn clear_project_runtime(project: &mut Project) {
    for network in project.networks.values_mut() {
        network.state = NetworkState::Closed;
        network.physical.clear();
        network.levels.clear();
    }
}

fn valid_internal_archive_key(value: &str) -> bool {
    value
        .strip_prefix("cmqttd:")
        .is_some_and(|key| !key.is_empty() && !key.contains('#'))
}

async fn bounded_line<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
    line: &mut Vec<u8>,
) -> io::Result<Option<String>> {
    loop {
        let buf = reader.fill_buf().await?;
        if buf.is_empty() {
            return if line.is_empty() {
                Ok(None)
            } else {
                Err(io::Error::other("unterminated C-Gate line"))
            };
        }
        let count = buf
            .iter()
            .position(|b| *b == b'\n')
            .map_or(buf.len(), |p| p + 1);
        if line.len() + count > MAX_LINE {
            return Err(io::Error::other("C-Gate line exceeds 1 MiB"));
        }
        let done = buf[count - 1] == b'\n';
        line.extend_from_slice(&buf[..count]);
        reader.consume(count);
        if done {
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            return String::from_utf8(std::mem::take(line))
                .map(Some)
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e));
        }
    }
}

fn is_aircon_subcommand(sub: &str) -> bool {
    matches!(
        sub,
        "REFRESH"
            | "SET_WARD_OFF"
            | "SET_WARD_ON"
            | "SET_ZONE_HVAC_MODE"
            | "SET_ZONE_HUMIDITY_MODE"
            | "SET_HVAC_UPPER_GUARD_LIMIT"
            | "SET_HVAC_LOWER_GUARD_LIMIT"
            | "SET_HVAC_SETBACK_LIMIT"
            | "SET_HUMIDITY_UPPER_GUARD_LIMIT"
            | "SET_HUMIDITY_LOWER_GUARD_LIMIT"
            | "SET_HUMIDITY_SETBACK_LIMIT"
    )
}

fn aircon_help(tag: &str) -> Response {
    let mut rows = AIRCON_HELP
        .iter()
        .map(|row| (*row).to_string())
        .collect::<Vec<_>>();
    let final_text = format!("101 {}", rows.pop().expect("AIRCON help is nonempty"));
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text,
        status: 101,
    }
}

fn parse_aircon_ward(tag: &str, target: &str, value: &str) -> Result<u8, Response> {
    match value.parse::<i32>() {
        Ok(value) => u8::try_from(value).map_err(|_| {
            err(
                tag,
                408,
                &format!("408 Operation failed: {target} (bad ward number: {value})"),
            )
        }),
        Err(_) => Err(err(
            tag,
            405,
            &format!("405 Parameter out of range: {target} (For input string: \"{value}\")"),
        )),
    }
}

fn parse_aircon_zones(tag: &str, target: &str, value: &str) -> Result<u8, Response> {
    let mut zones = 0u8;
    for token in value.split(',').filter(|token| !token.is_empty()) {
        let zone = token.parse::<i32>().map_err(|_| {
            err(
                tag,
                408,
                &format!(
                    "408 Operation failed: {target} (Zone List token is not a valid integer: {token})"
                ),
            )
        })?;
        if !(0..=6).contains(&zone) {
            return Err(err(
                tag,
                408,
                &format!("408 Operation failed: {target} (Zone index is out of range: {token})"),
            ));
        }
        zones |= 1 << zone;
    }
    Ok(zones)
}

fn parse_aircon_integer(
    tag: &str,
    value: &str,
    parameter: &str,
    range: Option<(i32, i32)>,
) -> Result<i32, Response> {
    let parsed = value.parse::<i32>().map_err(|_| {
        err(
            tag,
            400,
            &format!("400 Syntax Error: Invalid integer parameter : <{parameter}>"),
        )
    })?;
    if range.is_some_and(|(minimum, maximum)| !(minimum..=maximum).contains(&parsed)) {
        return Err(err(
            tag,
            400,
            &format!("400 Syntax Error: Integer parameter is out of range : <{parameter}>"),
        ));
    }
    Ok(parsed)
}

fn parse_aircon_boolean(tag: &str, value: &str, parameter: &str) -> Result<bool, Response> {
    match value {
        "0" => Ok(false),
        "1" => Ok(true),
        _ => Err(err(
            tag,
            400,
            &format!("400 Syntax Error: Invalid boolean parameter : <{parameter}>"),
        )),
    }
}

/// Session-gate predicate for the optional shared-secret LOGIN gate: true
/// when the (verb, sub) path mutates durable state, unit memory, or the
/// session/lock tables, and therefore needs the per-connection LOGIN flag
/// while the gate is armed. Read-only verbs (GET/INFO/LIST/QUICKGET/scans/
/// serials/observed-label reads), most bus-control verbs (lighting/trigger/enable/clock/
/// temperature/label writes, DO methods, NET scans) and session-local
/// LOGIN/LOGOUT stay open.
///
/// Gated set, chosen against Service::handle dispatch + local_command:
/// - PP mutating verbs: LOCK/UNLOCK/CANCEL_LOCK/START/END/NEW/LOAD/
///   LOAD_FROM_FILE/SAVE/SAVE_TO_SOURCE/SET/RESET(_TO_DEFAULTS)/COPY.
///   Open: GET/INFO/LIST/LIST_LOCK/UNITS/QUICKGET/LIST_CATALOG_NUMBERS.
///   The check runs before dispatch, so the physical PP LOAD/SAVE/
///   SAVE_TO_SOURCE pre-gate branches are covered before any PCI I/O.
/// - PROJECT lifecycle verbs: NEW/LOAD/SAVE/CLOSE/DELETE/COPY/RENAME/
///   ARCHIVE/RESTORE/REPAIR. Open: LIST/USE/DIR. (Verbs outside the
///   local_command PROJECT arm already 502 when dormant; gating them keeps
///   the armed reading uniform.)
/// - DB mutating verbs: DBSETSAFE/DBSETXML/DBADDSAFE/DBCOPYSAFE/DBDELETE/
///   DBSAVE/DBLOAD/DBCREATE*/DBRENAMENETSAFE. Open: DBGET*/DBVALIDATE.
///   DB verbs mutate the same durable database PP SAVE persists to, so
///   leaving them open would bypass the gate.
/// - SET in all forms (unit readdress via the pre-gate Address branch and
///   scalar database sets via the model): every form mutates.
/// - LABEL CLEAR/CLEAREDLT (clear label caches/unit labels) and LABEL
///   KFIGET/KFISET. KFIGET is
///   operational rather than read-only: native C-Gate sends three parameter-
///   `0xFF` writes before its IDENTIFY. LIGHTING/TRIGGER/ENABLE label
///   writes stay open: they are bus-control SAL traffic with MQTT
///   equivalents, like lighting ON/OFF — gating them without gating MQTT
///   would be theater, while programming verbs have no MQTT equivalent.
/// - The ten state-changing AIRCON subcommands. HVAC control has no MQTT
///   equivalent in cmqttd. REFRESH is a read/state request and remains open,
///   as do the parent help endpoint and unknown syntax.
/// - SCENE RECORD (persists snapshots to the state file). SCENE PLAY stays
///   open (snapshot read plus bus control).
/// - DO ... FactoryDefault (destructive KEYGL5 OEM programming control).
///   Other DO methods remain ordinary bus-control operations.
///
/// NET LOAD/SAVE need no entry: the local_command NET arm admits only
/// LIST|LIST_ALL|STATE, so they already fail closed with 502.
fn requires_programming_auth(verb: &str, sub: &str, words: &[String]) -> bool {
    match verb {
        "AIRCON" => is_aircon_subcommand(sub) && sub != "REFRESH",
        "PP" => matches!(
            sub,
            "LOCK"
                | "UNLOCK"
                | "CANCEL_LOCK"
                | "START"
                | "END"
                | "NEW"
                | "LOAD"
                | "LOAD_FROM_FILE"
                | "SAVE"
                | "SAVE_TO_SOURCE"
                | "SET"
                | "RESET"
                | "RESET_TO_DEFAULTS"
                | "COPY"
        ),
        "PROJECT" => matches!(
            sub,
            "NEW"
                | "LOAD"
                | "SAVE"
                | "CLOSE"
                | "DELETE"
                | "COPY"
                | "RENAME"
                | "ARCHIVE"
                | "RESTORE"
                | "REPAIR"
        ),
        "CGL" => sub == "IMPORT",
        "REPOSITORY" => sub == "USE",
        "SET" => true,
        "NET" => matches!(sub, "SET_PROJECT_IDENTIFY" | "UNRAVEL" | "UNRAVELUNIT"),
        "LABEL" => matches!(sub, "CLEAR" | "CLEAREDLT" | "KFIGET" | "KFISET"),
        "SCENE" => sub == "RECORD",
        "DO" => words
            .get(2)
            .is_some_and(|method| method == "FACTORYDEFAULT"),
        "DBSETSAFE" | "DBSETXML" | "DBADDSAFE" | "DBCOPYSAFE" | "DBDELETE" | "DBSAVE"
        | "DBLOAD" | "DBCREATENET" | "DBCREATEAPP" | "DBCREATEGROUP" | "DBCREATEUNIT"
        | "DBRENAMENETSAFE" => true,
        _ => false,
    }
}

fn local_command(words: &[&str], upper: &[String], model: &Server) -> bool {
    let verb = upper.first().map(String::as_str).unwrap_or("");
    let sub = upper.get(1).map(String::as_str).unwrap_or("");
    match verb {
        "NOOP" | "APIVER" | "HELP" | "COMMANDS" | "DBGET" | "DBGETXML" | "DBNETWORKPATH"
        | "DBSETSAFE" | "DBSETXML" | "DBADDSAFE" | "DBCOPYSAFE" | "DBDELETE" | "DBVALIDATE"
        | "DBSAVE" | "DBLOAD" | "DBGETNET" | "DBGETAPP" | "DBGETGROUP" | "DBGETUNIT"
        | "DBCREATENET" | "DBCREATEAPP" | "DBCREATEGROUP" | "DBCREATEUNIT" => true,
        "PROJECT" => matches!(
            sub,
            "LIST"
                | "USE"
                | "LOAD"
                | "SAVE"
                | "DIR"
                | "NEW"
                | "CLOSE"
                | "COPY"
                | "DELETE"
                | "RENAME"
                | "ARCHIVE"
                | "RESTORE"
        ),
        // GET is read-only. Application and live-lighting special cases are
        // handled above; the model supplies cached network and unit fields.
        "GET" => words.len() == 3,
        "NET" => matches!(sub, "LIST" | "LIST_ALL" | "STATE"),
        "PP" => match sub {
            "LOAD" | "SAVE" => words.get(3).is_some_and(|p| p.starts_with("/db/")),
            "SAVE_TO_SOURCE" => words
                .get(2)
                .and_then(|s| model.sessions.get(*s))
                .and_then(|s| s.source.as_ref())
                .is_some_and(|p| p.starts_with("/db/")),
            "LOCK" | "UNLOCK" | "START" | "END" | "NEW" | "GET" | "SET" | "INFO"
            | "RESET_TO_DEFAULTS" | "LIST" | "QUICKGET" | "COPY" => true,
            _ => false,
        },
        _ => false,
    }
}

fn parse_application(value: &str) -> Option<u8> {
    value.strip_prefix('$').map_or_else(
        || value.parse().ok(),
        |hex| u8::from_str_radix(hex, 16).ok(),
    )
}

fn open_reachable_networks(model: &mut Server, project_name: &str, root: u8) {
    let Some(project) = model.projects.get(project_name) else {
        return;
    };
    let reachable = project
        .networks
        .keys()
        .copied()
        .filter(|target| network_path(project, root, *target).is_ok())
        .collect::<Vec<_>>();
    if let Some(project) = model.projects.get_mut(project_name) {
        for address in reachable {
            if let Some(network) = project.networks.get_mut(&address) {
                network.state = NetworkState::Open;
            }
        }
    }
}

fn parse_temperature(value: &str) -> Option<f64> {
    let unsigned = value.strip_prefix('+').unwrap_or(value);
    let mut parts = unsigned.split('.');
    let whole = parts.next()?;
    let fraction = parts.next();
    if parts.next().is_some()
        || whole.is_empty()
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || fraction
            .is_some_and(|part| part.len() != 1 || !part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return None;
    }
    let temperature = value.parse::<f64>().ok()?;
    (temperature.is_finite() && (0.0..=63.75).contains(&temperature)).then_some(temperature)
}

fn format_temperature(value: f64) -> String {
    let mut value = format!("{value:.2}");
    while value.contains('.') && value.ends_with('0') {
        value.pop();
    }
    if value.ends_with('.') {
        value.pop();
    }
    value
}

fn identity_text(data: &[u8], field: &str) -> io::Result<String> {
    let value = std::str::from_utf8(data)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, format!("invalid {field}")))?
        .trim_matches([' ', '\0'])
        .to_string();
    if value.is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("empty {field}"),
        ));
    }
    Ok(value)
}

fn serial_number(data: &[u8]) -> io::Result<Option<String>> {
    if data.len() != 12 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "IDENTIFY4 reply must contain exactly twelve bytes",
        ));
    }
    let packed = u32::from_be_bytes(data[5..9].try_into().unwrap());
    if matches!(packed, 0 | u32::MAX) {
        return Ok(None);
    }
    Ok(Some(format!("{}.{}", packed >> 12, packed & 0xfff)))
}

fn known_serials(replies: &[Vec<u8>]) -> io::Result<HashSet<String>> {
    replies
        .iter()
        .filter_map(|reply| serial_number(reply).transpose())
        .collect()
}

fn mmi_state_is_present_non_error(state: u8) -> bool {
    matches!(state, 1 | 2)
}

fn parse_interface_spec(specification: &str) -> Option<(&str, &str)> {
    let (interface_type, address) = specification.split_once('@')?;
    if interface_type.is_empty() || address.is_empty() || address.contains('@') {
        return None;
    }
    Some((interface_type, address))
}

async fn project_identify_candidate(pci: &Arc<PciClient>, address: u8) -> io::Result<()> {
    pci.identify_first(address, 1)
        .await?
        .ok_or_else(|| io::Error::other("unit type did not reply"))
        .and_then(|data| identity_text(&data, "unit type"))?;
    pci.identify_first(address, 2)
        .await?
        .ok_or_else(|| io::Error::other("firmware version did not reply"))
        .and_then(|data| identity_text(&data, "firmware version"))?;
    let _applications = pci.recall_parameter(address, 33, 2).await?;
    Ok(())
}

async fn syncnew_identity(pci: &Arc<PciClient>, address: u8) -> io::Result<Unit> {
    let unit_type = pci
        .identify_first(address, 1)
        .await?
        .ok_or_else(|| io::Error::other("unit type did not reply"))
        .and_then(|data| identity_text(&data, "unit type"))?;
    let firmware = pci
        .identify_first(address, 2)
        .await?
        .ok_or_else(|| io::Error::other("firmware version did not reply"))
        .and_then(|data| identity_text(&data, "firmware version"))?;
    let replies = pci.identify_all(address, 4).await?;
    if replies.len() > 1 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "multiple serial identity replies",
        ));
    }
    let serial = replies
        .first()
        .map(|reply| serial_number(reply))
        .transpose()?
        .flatten()
        .unwrap_or_default();
    let mut unit = Unit::blank(address, "");
    unit.unit_type = unit_type;
    unit.firmware = firmware;
    unit.serial = serial;
    Ok(unit)
}

fn syncnew_unit_detail(unit: &Unit) -> String {
    let serial = if unit.serial.is_empty() {
        "{none}"
    } else {
        &unit.serial
    };
    format!(
        "New Unit Found: address={} type={} version={} serial={serial}",
        unit.address, unit.unit_type, unit.firmware
    )
}

fn syncnew_response(tag: &str, mut statuses: Vec<(u16, String)>) -> Response {
    let (status, detail) = statuses
        .pop()
        .expect("NET SYNCNEW always emits a final status");
    let lines = statuses
        .into_iter()
        .map(|(code, detail)| format!("{code}-{}", syncnew_status_text(code, &detail)))
        .collect();
    Response {
        tag: tag.to_string(),
        lines,
        final_text: format!("{status} {}", syncnew_status_text(status, &detail)),
        status,
    }
}

fn syncnew_status_text(status: u16, detail: &str) -> String {
    if status == 408 {
        format!("Operation failed: {detail}")
    } else {
        detail.to_string()
    }
}

async fn physical_serial_inventory(
    pci: &Arc<PciClient>,
    states: &[u8],
) -> io::Result<BTreeMap<u8, Vec<String>>> {
    if states.len() != 256 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "installation MMI must cover all 256 addresses",
        ));
    }
    let mut inventory = BTreeMap::new();
    for (address, state) in states.iter().enumerate() {
        if *state == 0 {
            continue;
        }
        let address = address as u8;
        let replies = pci.identify_all(address, 4).await?;
        let mut serials = replies
            .iter()
            .map(|reply| {
                serial_number(reply)?.ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("address {address} returned an unknown serial"),
                    )
                })
            })
            .collect::<io::Result<Vec<_>>>()?;
        serials.sort();
        if serials.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("address {address} did not return a serial"),
            ));
        }
        if serials.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("address {address} returned a duplicate serial response"),
            ));
        }
        inventory.insert(address, serials);
    }
    Ok(inventory)
}

fn import_project(xml: &str, network_name: Option<&str>) -> io::Result<(Server, String, u8)> {
    let doc = roxmltree::Document::parse(xml)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let field = |n: roxmltree::Node<'_, '_>, name: &str| -> String {
        n.children()
            .find(|c| c.has_tag_name(name))
            .and_then(|c| c.text())
            .or_else(|| n.attribute(name))
            .unwrap_or("")
            .to_string()
    };
    let p = doc
        .descendants()
        .find(|n| n.has_tag_name("Project"))
        .ok_or_else(|| io::Error::other("project XML has no Project"))?;
    let name = field(p, "TagName");
    if !valid_name(&name) {
        return Err(io::Error::other("invalid project name"));
    }
    let selected = p
        .children()
        .filter(|n| n.has_tag_name("Network"))
        .find(|n| network_name.is_none_or(|wanted| field(*n, "TagName") == wanted))
        .ok_or_else(|| io::Error::other("configured network absent from project"))?;
    let address = field(selected, "Address")
        .parse::<u8>()
        .map_err(io::Error::other)?;
    let mut model = Server::new(AccessLevel::Program).with_programming(true);
    let mut networks = HashMap::new();
    for node in p.children().filter(|n| n.has_tag_name("Network")) {
        let net = field(node, "Address")
            .parse::<u8>()
            .map_err(io::Error::other)?;
        let mut units = HashMap::new();
        for u in node.children().filter(|n| n.has_tag_name("Unit")) {
            let addr = field(u, "Address")
                .parse::<u8>()
                .map_err(io::Error::other)?;
            let mut fields = HashMap::new();
            for child in u.children().filter(|c| c.is_element()) {
                if child.has_tag_name("PP") {
                    if let (Some(key), Some(value)) =
                        (child.attribute("Name"), child.attribute("Value"))
                    {
                        fields.insert(key.to_string(), value.to_string());
                    }
                } else if child.children().all(|c| !c.is_element()) {
                    fields.insert(
                        child.tag_name().name().to_string(),
                        child.text().unwrap_or("").to_string(),
                    );
                }
            }
            let oid = u
                .attribute("oid")
                .map(str::to_string)
                .unwrap_or_else(fresh_oid);
            model.known_oids.insert(oid.clone());
            model.objects.insert(format!("//{name}/{net}/p/{addr}"));
            units.insert(
                addr,
                Unit {
                    address: addr,
                    unit_type: field(u, "UnitType"),
                    serial: field(u, "SerialNumber"),
                    serial_alternates: Vec::new(),
                    firmware: field(u, "FirmwareVersion"),
                    fields,
                    oid,
                },
            );
        }
        for app in node.children().filter(|n| n.has_tag_name("Application")) {
            let a = field(app, "Address")
                .parse::<u8>()
                .map_err(io::Error::other)?;
            model
                .db_fields
                .insert(format!("//{name}/{net}/{a}/TagName"), field(app, "TagName"));
            for group in app.children().filter(|n| n.has_tag_name("Group")) {
                let g = field(group, "Address")
                    .parse::<u8>()
                    .map_err(io::Error::other)?;
                model.db_fields.insert(
                    format!("//{name}/{net}/{a}/{g}/TagName"),
                    field(group, "TagName"),
                );
            }
        }
        let interface = node.children().find(|n| n.has_tag_name("Interface"));
        let network_oid = node
            .attribute("oid")
            .map(str::to_string)
            .unwrap_or_else(fresh_oid);
        model.known_oids.insert(network_oid.clone());
        networks.insert(
            net,
            Network {
                oid: network_oid,
                address: net,
                name: field(node, "TagName"),
                iface_type: interface
                    .map(|n| field(n, "InterfaceType"))
                    .unwrap_or_default(),
                iface_addr: interface
                    .map(|n| field(n, "InterfaceAddress"))
                    .unwrap_or_default(),
                state: NetworkState::Closed,
                units,
                physical: HashMap::new(),
                levels: HashMap::new(),
            },
        );
    }
    model.projects.insert(
        name.clone(),
        Project {
            name: name.clone(),
            networks,
        },
    );
    model.current = Some(name.clone());
    Ok((model, name, address))
}
