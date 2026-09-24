//! Hardware-backed C-Gate service embedded by cmqttd. The in-memory mock is
//! deliberately not the fallback for unimplemented physical operations.

use super::*;
use cbus_protocol::{
    packet::{Meta, Packet},
    sal::Sal,
};
use cbus_transport::pci::{CBusEvent, PciClient};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
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
            CBusEvent::ConnectionLost => {
                net.levels.clear();
                net.physical.clear();
                net.state = NetworkState::Closed;
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
    }

    fn bound_group(&self, address: &str) -> Option<(u8, u8)> {
        let (p, n, a, g) = Server::split_lighting(address)?;
        (p == self.project && n == self.network).then_some((a, g))
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
                "full_cgate_compatibility":false, "memory_read":true, "memory_write":false,
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
        // Database additions must not invent physical presence.
        for project in model.projects.values_mut() {
            for network in project.networks.values_mut() {
                network.physical.clear();
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
        "GET" => {
            words.len() == 3
                && (words[1].eq_ignore_ascii_case("CGATE")
                    || upper[2] == "STATE"
                    || upper[2] == "TARGETINTERFACESTATE")
        }
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
