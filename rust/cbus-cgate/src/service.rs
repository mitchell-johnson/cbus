//! Hardware-backed C-Gate service embedded by cmqttd. The in-memory mock is
//! deliberately not the fallback for unimplemented physical operations.

use super::*;
use cbus_protocol::{
    packet::{Meta, Packet},
    sal::{label, Sal},
};
use cbus_transport::pci::{CBusEvent, GocProgramming, PciClient};
use chrono::{Datelike, Local, NaiveDate, NaiveTime, Timelike};
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    io::{self, Write},
    path::Path,
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    sync::{broadcast, Mutex, RwLock, Semaphore},
};

const MAX_LINE: usize = 1024 * 1024;
const MAX_STATE: usize = 32 * 1024 * 1024;

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

    fn restore(self, s: &mut Server) -> io::Result<()> {
        if self.version != 1 {
            return Err(io::Error::other("unsupported C-Gate database version"));
        }
        s.projects = self.projects;
        s.db_fields = self.db_fields;
        s.objects = self.objects;
        s.known_oids = self.known_oids;
        s.db_levels = self.db_levels;
        s.config_values = self.config_values;
        s.scene_snapshots = self.scene_snapshots;
        s.database_files = self.database_files;
        s.file_store = self.file_store;
        Ok(())
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
}

/// One real, explicitly selected C-Bus network, shared with the MQTT gateway.
pub struct Service {
    model: Mutex<Server>,
    pci: RwLock<Arc<PciClient>>,
    project: String,
    network: u8,
    state_path: PathBuf,
    events: broadcast::Sender<String>,
    // Serialize command intents without preventing readback/event processing.
    commands: Mutex<()>,
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
                serde_json::from_slice::<Database>(&data)?.restore(&mut model)?;
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
        Ok(Arc::new(Self {
            model: Mutex::new(model),
            pci: RwLock::new(pci),
            project,
            network,
            state_path,
            events: broadcast::channel(512).0,
            commands: Mutex::new(()),
        }))
    }

    /// Replace the shared PCI after cmqttd reconnects; invalidate all live data.
    pub async fn set_pci(&self, pci: Arc<PciClient>) {
        self.observe(&CBusEvent::ConnectionLost).await;
        *self.pci.write().await = pci;
        if let Some(net) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|p| p.networks.get_mut(&self.network))
        {
            net.state = NetworkState::Open;
        }
    }

    /// Feed genuine bus observations to C-Gate clients as well as MQTT.
    pub async fn observe(&self, event: &CBusEvent) {
        let mut model = self.model.lock().await;
        let Some(net) = model
            .projects
            .get_mut(&self.project)
            .and_then(|p| p.networks.get_mut(&self.network))
        else {
            return;
        };
        let mut updates = Vec::new();
        let mut application_update = None;
        let mut clear_application_state = false;
        match event {
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
            CBusEvent::ConnectionLost => {
                net.levels.clear();
                net.physical.clear();
                net.state = NetworkState::Closed;
                clear_application_state = true;
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
        if clear_application_state {
            model.application_state.clear();
        } else if let Some((key, value)) = application_update {
            model.application_state.insert(key, value);
        }
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
        if verb == "CMQTT" && sub == "CAPABILITIES" && words.len() == 2 {
            return ok(
                tag,
                vec![serde_json::json!({"service":"cmqttd", "physical_bus":true,
                "full_cgate_compatibility":false, "memory_read":true, "memory_write":true,
                "physical_pp_load":true, "physical_pp_save":true,
                "physical_pp_save_cbus3_nvm":true,
                "physical_pp_save_methods":["dali","direct","edlt","giu","goc","goc2","gocbyt","ncc","paged","sgiu"],
                "physical_pp_save_protection":["none","checksum","lock"],
                "physical_pp_save_lock_methods":["direct","ncc","paged"],
                "trigger_control":true, "enable_control":true, "clock_control":true,
                "temperature_broadcast":true,
                "dynamic_labels":true,
                "dynamic_label_families":["enable","lighting","trigger"],
                "dynamic_label_modes":["dynamic_icon","icon","language","raw","unicode"],
                "edlt_label_clear":true,
                "named_scenes":true,
                "do_methods":["lighting","sync"],
                "install_mmi":true, "network_pingu":true,
                "network_sync":true, "network_checkunit":true,
                "unit_readdress":true,
                "project":self.project,"network":self.network,"persistent_database":true})
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
        if verb == "NET" && sub == "SYNC" {
            return self.net_sync(client, line, tag, &words).await;
        }
        if verb == "NET" && sub == "CHECKUNIT" {
            return self.net_checkunit(client, line, tag, &words).await;
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
        if matches!(verb, "ON" | "OFF" | "RAMP" | "TERMINATERAMP")
            || (verb == "LIGHTING"
                && matches!(sub, "ON" | "OFF" | "RAMP" | "STOP" | "TERMINATERAMP"))
        {
            return self.lighting(client, line, tag).await;
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
        }
        let before = model.clone();
        let before_db = Database::from_server(&model);
        let response = model.handle(line);
        if response.status >= 400 {
            *model = before;
            return response;
        }
        // The in-memory compatibility model makes some database verbs affect
        // its synthetic physical layer. The hardware service must preserve
        // the independently observed bus inventory across every local command,
        // including read-only GETs, and must never let a database edit invent
        // physical presence.
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
        if words.len() != 3 || !self.bound_network(words[2]) {
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
        let pci = self.pci.read().await.clone();
        let states = match pci.install_mmi().await {
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
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
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
        if words.len() < 3 || !self.bound_network(words[2]) {
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
        self.set_network_state(NetworkState::Syncing).await;
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
            self.set_network_state(NetworkState::Open).await;
            return err(
                tag,
                408,
                &format!("408 Physical interface discovery failed: {error}"),
            );
        }
        let states = match pci.install_mmi().await {
            Ok(states) => states,
            Err(error) => {
                self.set_network_state(NetworkState::Open).await;
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
        let mut identities = Vec::with_capacity(addresses.len());
        for address in addresses {
            let unit_type = match pci.identify_first(address, 1).await {
                Ok(Some(data)) => match identity_text(&data, "unit type") {
                    Ok(value) => value,
                    Err(error) => {
                        self.set_network_state(NetworkState::Open).await;
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
                    self.set_network_state(NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical identity synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let firmware = match pci.identify_first(address, 2).await {
                Ok(Some(data)) => match identity_text(&data, "firmware version") {
                    Ok(value) => value,
                    Err(error) => {
                        self.set_network_state(NetworkState::Open).await;
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
                    self.set_network_state(NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical identity synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let serial_replies = match pci.identify_all(address, 4).await {
                Ok(replies) => replies,
                Err(error) => {
                    self.set_network_state(NetworkState::Open).await;
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
                    self.set_network_state(NetworkState::Open).await;
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 Physical serial synchronization failed at address {address}: {error}"
                        ),
                    );
                }
            };
            let serial = if serials.len() == 1 {
                serials.into_iter().next().unwrap()
            } else {
                String::new()
            };
            identities.push((address, unit_type, firmware, serial));
        }

        let mut model = self.model.lock().await;
        if let Some(network) = model
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            let previous = std::mem::take(&mut network.physical);
            network.physical = identities
                .into_iter()
                .map(|(address, unit_type, firmware, serial)| {
                    let mut unit = previous
                        .get(&address)
                        .cloned()
                        .unwrap_or_else(|| Unit::blank(address, ""));
                    unit.unit_type = unit_type;
                    unit.firmware = firmware;
                    unit.serial = serial;
                    (address, unit)
                })
                .collect();
            network.state = NetworkState::Ok;
        }
        drop(model);
        let _ = self
            .events
            .send(format!("#e# net {} sync ok", self.network));
        validation
    }

    async fn net_checkunit(
        &self,
        client: &ClientState,
        line: &str,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let _commands = self.commands.lock().await;
        if words.len() != 4 || !self.bound_network(words[2]) {
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
        let pci = self.pci.read().await.clone();
        let selected = if words[3] == "*" {
            let states = match pci.install_mmi().await {
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
            let replies = match pci.identify_all(address, 4).await {
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
        let _ = self
            .events
            .send(format!("#e# net {} checkunit {}", self.network, words[3]));
        ok(tag, lines, "200 OK.")
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

    async fn set_network_state(&self, state: NetworkState) {
        if let Some(network) = self
            .model
            .lock()
            .await
            .projects
            .get_mut(&self.project)
            .and_then(|project| project.networks.get_mut(&self.network))
        {
            network.state = state;
        }
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
                    payload,
                }],
            };
            if let Err(error) = pci.send_confirmed(&packet).await {
                return err(tag, 502, &format!("502 Label delivery failed: {error}"));
            }
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
                let _ = self.events.send(format!("#e# labels cleared {}", words[2]));
                response
            }
            Err(error) => err(tag, 502, &format!("502 eDLT label clear failed: {error}")),
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
                return err(tag, 502, &format!("502 Physical PP save failed: {error}"));
            }
            wrote_any = true;
        }
        if wrote_any && requires_nvm_commit {
            if let Err(error) = pci.save_to_nvm(unit).await {
                return err(
                    tag,
                    502,
                    &format!("502 Physical PP Save-to-NVM failed: {error}"),
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

    async fn connection(&self, stream: TcpStream) -> io::Result<()> {
        let (reader, mut writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut events = self.events.subscribe();
        let mut mode = EventMode::OFF;
        let mut client = ClientState::default();
        let mut pending_line = Vec::new();
        let result = async {
            writer.write_all(b"201 cmqttd C-Gate service ready\r\n").await?;
            loop {
                tokio::select! {
                    result = bounded_line(&mut reader, &mut pending_line) => {
                        let Some(line) = result? else { return Ok(()); };
                        let tagged = line.starts_with('[');
                        let command = if tagged {line} else {format!("[untagged] {line}")};
                        let parsed = parse_command(&command).ok();
                        let mut response = if let Some(c) = parsed.as_ref().filter(|c| c.body.split_whitespace().next().is_some_and(|w| w.eq_ignore_ascii_case("EVENT"))) {
                            let words: Vec<_> = c.body.split_whitespace().collect();
                            if words.len() == 1 { Response {tag:c.tag.clone(), lines:vec![], final_text:format!("306 {}", mode), status:306} }
                            else if words.len() == 2 {
                                if let Some(new) = EventMode::parse(words[1]) { mode = new; ok(&c.tag, vec![], "200 OK") }
                                else { err(&c.tag, 400, "400 Invalid event mode") }
                            } else { err(&c.tag, 400, "400 Invalid event command") }
                        } else { self.handle(&mut client, &command).await };
                        if !tagged { response.tag.clear(); }
                        tokio::time::timeout(Duration::from_secs(10), writer.write_all(format_response(&response).replace('\n', "\r\n").as_bytes())).await
                            .map_err(|_| io::Error::new(io::ErrorKind::TimedOut,"C-Gate client is not reading"))??;
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
        let mut model = self.model.lock().await;
        for name in client.sessions {
            model.sessions.remove(&name);
        }
        for name in client.locks {
            model.locks.remove(&name);
        }
        result
    }
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

fn local_command(words: &[&str], upper: &[String], model: &Server) -> bool {
    let verb = upper.first().map(String::as_str).unwrap_or("");
    let sub = upper.get(1).map(String::as_str).unwrap_or("");
    match verb {
        "NOOP" | "APIVER" | "HELP" | "COMMANDS" | "DBGET" | "DBGETXML" | "DBSETSAFE"
        | "DBSETXML" | "DBADDSAFE" | "DBCOPYSAFE" | "DBDELETE" | "DBVALIDATE" | "DBSAVE"
        | "DBLOAD" | "DBGETNET" | "DBGETAPP" | "DBGETGROUP" | "DBGETUNIT" | "DBCREATENET"
        | "DBCREATEAPP" | "DBCREATEGROUP" | "DBCREATEUNIT" => true,
        "PROJECT" => matches!(
            sub,
            "LIST" | "USE" | "LOAD" | "SAVE" | "DIR" | "NEW" | "CLOSE"
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
            "LOCK" | "UNLOCK" | "START" | "END" | "NEW" | "GET" | "SET" | "INFO" | "RESET"
            | "LIST" | "QUICKGET" | "COPY" => true,
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
        networks.insert(
            net,
            Network {
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
