//! Native-evidenced NET catalogue lifecycle and network-management commands.
//!
//! Network definitions are command-layer state.  They are deliberately kept
//! separate from the imported tag database and from cmqttd's one live PCI
//! binding: native `NET RENAME` changes the runtime definition but does not
//! rename the database object.  The catalogue and its DB/FILE snapshots live
//! inside the atomic cmqttd JSON repository and never name host files.

use super::*;
use cbus_protocol::sal::network_management::{LearnMode, LocateTarget, NetworkLocate};

const CATALOG_PREFIX: &str = "@cmqttd/net-catalog/v1/";

const NET_HELP: &[&str] = &[
    "Help: NET commands:",
    "Help:  NET ? Help for these commands",
    "Help:  NET CHECKUNIT - Test a unit address to see whether an unravel is required",
    "Help:  NET CHECK_UNRAVEL - Test a network as to whether an unravel is required",
    "Help:  NET CLOCKS - Optimise the number of clocks enabled on a network",
    "Help:  NET CLOSE - Close a network in the current project, or all networks in all projects",
    "Help:  NET CREATE - Create a new network definition in the current project",
    "Help:  NET DELETE - Delete a network definition in the current project",
    "Help:  NET FLUSH - Flush the objects for the given network",
    "Help:  NET LEARN - Enable or disable learn command for given network and application",
    "Help:  NET LIST - Return a list of networks defined in the project",
    "Help:  NET LIST_ALL - Return a list of all networks defined in ALL projects",
    "Help:  NET LOAD - Load network definitions into the project",
    "Help:  NET OPEN - Open a network in the current project",
    "Help:  NET PINGU - Perform a quick single-MMI network ping returning a list of unit addresses",
    "Help:  NET PROJECT_IDENTIFY - Identify the project present on this interface",
    "Help:  NET RENAME - Change the network name of the given network",
    "Help:  NET SAVE - Save network definitions into the current project",
    "Help:  NET SET_PROJECT_IDENTIFY - Set the project identify string for this network",
    "Help:  NET STATE_INTERVAL - Set network status event interval",
    "Help:  NET SYNC - Synchronize a network",
    "Help:  NET SYNCNEW - Find and get details of new units on this network",
    "Help:  NET UNRAVEL - Unravel a network.",
    "Help:  NET UNRAVELUNIT - Unravel a unit address.",
];

const NET_CLOSE_HELP: &[&str] = &["Help: No help is available for this command."];
const NET_CREATE_HELP: &[&str] = &[
    "Help: syntax: NET CREATE <name> <type> <interface-address> [<options>]",
    "Help: Create a new network definition in the current project.",
    "Help:  <name> is a valid network name.",
    "Help:  <type> is the interface type (such as serial, cni, bridge, ..)",
    "Help:  <interface-address> is the address of the port for this network",
    "Help:  <options> (optional) depend on the network type.",
];
const NET_DELETE_HELP: &[&str] = &[
    "Help: syntax: NET DELETE <name>",
    "Help: Delete a network definition in the current project.",
    "Help:  <name> is a valid network name.",
];
const NET_FLUSH_HELP: &[&str] = &[
    "Help: syntax: NET FLUSH <net-address>",
    "Help: Flush the objects from a network.",
    "Help:  <net-address> is a valid network address.",
];
const NET_LEARN_HELP: &[&str] = &[
    "Help: syntax: NET LEARN <net-address> <app-number> <grade> <group>",
    "Help: Return a list of networks defined in the current project.",
    "Help:  <net-address> is the address of the network",
    "Help:  <app-number> is the application to send the command for",
    "Help:  <grade> is the learn operation to perform given as an integer:",
    "Help:    init relay $1",
    "Help:    init dim   $2",
    "Help:    cancel     $80",
    "Help:    exit relay $81",
    "Help:    exit dim   $82",
    "Help:    exit area  $83",
    "Help:  <group> is the group number to learn.",
];
const NET_LOAD_HELP: &[&str] = &[
    "Help: syntax: NET LOAD 'DB' | 'FILE' [<project>]",
    "Help: Loads network definitions from the tag database or from a networks file",
];
const NET_OPEN_HELP: &[&str] = &[
    "Help: syntax: NET OPEN <net-address>",
    "Help: Open a network.",
    "Help:  <net-address> is a valid network address.",
];
const NET_RENAME_HELP: &[&str] = &[
    "Help: syntax: NET RENAME <net-address> <new-name> [\"nofixrefs\"]",
    "Help: Change a network name.",
    "Help:  <net-address> is a valid network name.",
    "Help:  <new-name> is the new network name",
    "Help:  \"nofixrefs\" (optional) prevents the command from changing bridge definitions",
    "Help:  in other networks in this project to support the new network name.",
];
const NET_SAVE_HELP: &[&str] = &[
    "Help: syntax: NET SAVE 'DB' | 'FILE'",
    "Help: Save network definitions to the tag database of to a networks file",
];
const NET_STATE_INTERVAL_HELP: &[&str] = &[
    "Help: syntax: NET STATE_INTERVAL <state-interval>",
    "Help: Sets network state event interval in seconds.",
    "Help:  <state-interval> is the time in seconds between state events for all networks",
    "Help:   A value of 0 disables state events",
];
const NET_UNRAVEL_HELP: &[&str] = &[
    "Help: syntax: NET UNRAVEL <net-address> [MATCHDB]",
    "Help: Unravel a network, placing all units at unique addresses. <net-address> is a valid network address. if MATCHDB is specified then the units where possible will move to their addresses in the database.",
];
const NETWORK_HELP: &[&str] = &[
    "Help: NETWORK commands:",
    "Help:  NETWORK ? Help for these commands",
    "Help:  NETWORK LOCATE - Send a locate message on the network application",
];
const NETWORK_LOCATE_HELP: &[&str] = &[
    "Help: syntax: NETWORK LOCATE <application> <options> <mode>",
    "Help: Sends a locate yourself message to the matched units",
    "Help:  <application> must resolve to a valid Network application address.",
    "Help:  <options> is one of the following:",
    "Help:    UNIT <unit-number>",
    "Help:    APP <app-number>",
    "Help:    GROUP <app-number> <group-number>",
    "Help:    SERIAL <manufacturer> <serial-number>",
    "Help:  <mode> is ON, OFF, or a number in the range 0 through 255",
];
const TOPOLOGY_HELP: &[&str] = &[
    "Help: TOPOLOGY commands:",
    "Help:  TOPOLOGY ? Help for these commands",
    "Help:  TOPOLOGY EXPLORE - Explore the topology of a set of network connections",
];
const TOPOLOGY_EXPLORE_HELP: &[&str] = &[
    "Help: syntax: TOPOLOGY EXPLORE <addresses>",
    "Help: Explore the topology of a set of network connections",
    "Help: <addresses> is a list of space-separated addresses in the form",
    "Help: <type>@address;option=value;option=value",
    "Help:   some examples are: serial@COM1 cni@192.168.1.40:10001",
    "Help:   modem@COM2;number=85431111;username=222;password=2345",
];

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
struct NetDefinition {
    name: String,
    interface_type: String,
    interface_address: String,
    options: Vec<String>,
    #[serde(default)]
    bound_network: Option<u8>,
}

pub(super) fn help(tag: &str, words: &[&str], upper: &[String]) -> Option<Response> {
    let verb = upper.first().map(String::as_str)?;
    if matches!(verb, "NET" | "NETWORK" | "TOPOLOGY")
        && (words.len() == 1 || (words.len() == 2 && words[1] == "?"))
    {
        return Some(command_help(
            tag,
            match verb {
                "NET" => NET_HELP,
                "NETWORK" => NETWORK_HELP,
                _ => TOPOLOGY_HELP,
            },
        ));
    }
    if verb != "HELP" {
        return None;
    }
    let family = upper.get(1).map(String::as_str)?;
    let sub = upper.get(2).map(String::as_str).unwrap_or("");
    let rows = match (family, sub, words.len()) {
        ("NET", "", 2) => NET_HELP,
        ("NET", "CLOSE", 3) => NET_CLOSE_HELP,
        ("NET", "CREATE", 3) => NET_CREATE_HELP,
        ("NET", "DELETE", 3) => NET_DELETE_HELP,
        ("NET", "FLUSH", 3) => NET_FLUSH_HELP,
        ("NET", "LEARN", 3) => NET_LEARN_HELP,
        ("NET", "LOAD", 3) => NET_LOAD_HELP,
        ("NET", "OPEN", 3) => NET_OPEN_HELP,
        ("NET", "RENAME", 3) => NET_RENAME_HELP,
        ("NET", "SAVE", 3) => NET_SAVE_HELP,
        ("NET", "STATE_INTERVAL", 3) => NET_STATE_INTERVAL_HELP,
        ("NET", "UNRAVEL", 3) => NET_UNRAVEL_HELP,
        ("NETWORK", "", 2) => NETWORK_HELP,
        ("NETWORK", "LOCATE", 3) => NETWORK_LOCATE_HELP,
        ("TOPOLOGY", "", 2) => TOPOLOGY_HELP,
        ("TOPOLOGY", "EXPLORE", 3) => TOPOLOGY_EXPLORE_HELP,
        _ => return None,
    };
    Some(command_help(tag, rows))
}

fn project_component(project: &str) -> String {
    hex::encode(project.as_bytes())
}

fn active_key(project: &str) -> String {
    format!("{CATALOG_PREFIX}{}/active", project_component(project))
}

fn snapshot_key(project: &str, source: &str) -> String {
    format!(
        "{CATALOG_PREFIX}{}/snapshot/{}",
        project_component(project),
        source.to_ascii_lowercase()
    )
}

fn imported_definitions(project: &Project) -> Vec<NetDefinition> {
    let mut definitions = project
        .networks
        .iter()
        .map(|(address, network)| NetDefinition {
            name: address.to_string(),
            interface_type: network.iface_type.clone(),
            interface_address: network.iface_addr.clone(),
            options: Vec::new(),
            bound_network: Some(*address),
        })
        .collect::<Vec<_>>();
    definitions.sort_by(|left, right| left.name.cmp(&right.name));
    definitions
}

fn encode_catalog(definitions: &[NetDefinition]) -> io::Result<String> {
    serde_json::to_string(definitions).map_err(io::Error::other)
}

fn decode_catalog(value: &str) -> Result<Vec<NetDefinition>, String> {
    serde_json::from_str(value).map_err(|error| format!("invalid network catalogue: {error}"))
}

/// Seed command-layer active/DB catalogues from imported tag-database rows.
pub(super) fn seed_catalogs(model: &mut Server) -> io::Result<bool> {
    let projects = model
        .projects
        .iter()
        .map(|(name, project)| (name.clone(), imported_definitions(project)))
        .collect::<Vec<_>>();
    let mut changed = false;
    for (project, definitions) in projects {
        let encoded = encode_catalog(&definitions)?;
        for key in [active_key(&project), snapshot_key(&project, "db")] {
            if let std::collections::hash_map::Entry::Vacant(entry) = model.config_values.entry(key)
            {
                entry.insert(encoded.clone());
                changed = true;
            }
        }
    }
    Ok(changed)
}

fn catalog(model: &Server, project: &str) -> Result<Vec<NetDefinition>, String> {
    match model.config_values.get(&active_key(project)) {
        Some(value) => decode_catalog(value),
        None => model
            .projects
            .get(project)
            .map(imported_definitions)
            .ok_or_else(|| "project not found".to_string()),
    }
}

fn put_catalog(
    model: &mut Server,
    project: &str,
    definitions: &[NetDefinition],
) -> Result<(), String> {
    let value = serde_json::to_string(definitions).map_err(|error| error.to_string())?;
    model.config_values.insert(active_key(project), value);
    Ok(())
}

fn current_project(service: &Service, client: &ClientState) -> String {
    client
        .current
        .clone()
        .unwrap_or_else(|| service.project.clone())
}

fn split_network_address(value: &str, current: &str) -> Option<(String, String)> {
    let parts = value
        .trim_start_matches('/')
        .split('/')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    if value.starts_with("//") {
        let [project, network] = parts.as_slice() else {
            return None;
        };
        Some(((*project).to_string(), (*network).to_string()))
    } else {
        let [network] = parts.as_slice() else {
            return None;
        };
        Some((current.to_string(), (*network).to_string()))
    }
}

fn network_definition(
    model: &Server,
    address: &str,
    current: &str,
) -> Result<(String, NetDefinition), String> {
    let (project, name) = split_network_address(address, current)
        .ok_or_else(|| format!("{address} (Object not found)"))?;
    let definition = catalog(model, &project)?
        .into_iter()
        .find(|definition| definition.name == name)
        .ok_or_else(|| format!("{address} (Object not found)"))?;
    Ok((project, definition))
}

fn valid_network_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 255
        && !name.contains(['/', '\\'])
        && !name
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
}

fn parse_byte(value: &str) -> Option<u8> {
    value.strip_prefix('$').map_or_else(
        || value.parse::<u8>().ok(),
        |hex| u8::from_str_radix(hex, 16).ok(),
    )
}

fn parse_mode(value: &str) -> Option<u8> {
    if value.eq_ignore_ascii_case("ON") {
        Some(1)
    } else if value.eq_ignore_ascii_case("OFF") {
        Some(0)
    } else {
        parse_byte(value)
    }
}

impl Service {
    pub(super) async fn net_lifecycle(
        &self,
        client: &ClientState,
        tag: &str,
        words: &[&str],
        upper: &[String],
    ) -> Response {
        match upper.get(1).map(String::as_str).unwrap_or("") {
            "LIST" => self.net_catalog_list(client, tag, words).await,
            "LEARN" => self.net_learn(client, tag, words).await,
            "FLUSH" => self.net_catalog_flush(client, tag, words).await,
            "OPEN" | "CLOSE" => self.net_open_close(client, tag, words).await,
            sub @ ("CREATE" | "DELETE" | "LOAD" | "RENAME" | "SAVE") => {
                self.net_catalog_mutation(client, tag, words, sub).await
            }
            _ => err(tag, 400, "400 Syntax Error."),
        }
    }

    /// Start or stop one catalogue network without stealing cmqttd's shared
    /// PCI transport from MQTT.  Imported/bound definitions own a concrete
    /// runtime network; CREATE-only definitions remain closed until a future
    /// multi-interface daemon instance binds them.
    async fn net_open_close(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        let opening = words
            .get(1)
            .is_some_and(|word| word.eq_ignore_ascii_case("OPEN"));
        if words.len() != 3 {
            return if words.len() < 3 {
                err(tag, 400, "400 Syntax Error: Missing parameter : <network>")
            } else {
                err(tag, 400, "400 Syntax Error: Too many parameters")
            };
        }
        if opening && words[2] == "*" {
            return err(
                tag,
                401,
                "401 Bad object or device ID: * (Object not found)",
            );
        }

        let _commands = self.commands.lock().await;
        // Read transport liveness before taking the model lock. Reconnect
        // replaces the PCI and then clears model caches, so holding these in
        // the opposite order could deadlock the lifecycle command with it.
        let configured_pci_connected = if opening {
            self.pci.read().await.is_connected()
        } else {
            true
        };
        let current = current_project(self, client);
        let mut model = self.model.lock().await;
        let targets = if words[2] == "*" {
            let mut targets = Vec::new();
            let mut projects = model.projects.keys().cloned().collect::<Vec<_>>();
            projects.sort();
            for project in projects {
                let Ok(definitions) = catalog(&model, &project) else {
                    continue;
                };
                for definition in definitions {
                    targets.push((project.clone(), definition));
                }
            }
            targets
        } else {
            match network_definition(&model, words[2], &current) {
                Ok((project, definition)) => vec![(project, definition)],
                Err(_) => {
                    return err(
                        tag,
                        401,
                        &format!(
                            "401 Bad object or device ID: {} (Object not found)",
                            words[2]
                        ),
                    )
                }
            }
        };
        if targets.is_empty() {
            return err(tag, 132, "132 no networks found");
        }

        if opening {
            for (project, definition) in &targets {
                if definition.bound_network.is_none() {
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 //{project}/{}: network definition has no runtime binding",
                            definition.name
                        ),
                    );
                }
                if project == &self.project
                    && definition.bound_network == Some(self.network)
                    && !configured_pci_connected
                {
                    return err(
                        tag,
                        408,
                        &format!(
                            "408 //{project}/{}: configured shared PCI is not connected",
                            definition.name
                        ),
                    );
                }
            }
        }

        let mut paths = Vec::with_capacity(targets.len());
        for (project, definition) in &targets {
            if let Some(address) = definition.bound_network {
                if let Some(network) = model
                    .projects
                    .get_mut(project)
                    .and_then(|project| project.networks.get_mut(&address))
                {
                    if opening {
                        network.state = NetworkState::Open;
                    } else {
                        network.state = NetworkState::Closed;
                        network.physical.clear();
                        network.levels.clear();
                    }
                }
            }
            paths.push(format!("//{project}/{}", definition.name));
        }
        if opening {
            // Imported bridge children reachable from the shared interface
            // participate in the same runtime, just as they do after daemon
            // startup and reconnect.  No new transport is opened here.
            if targets.iter().any(|(project, definition)| {
                project == &self.project && definition.bound_network == Some(self.network)
            }) {
                open_reachable_networks(&mut model, &self.project, self.network);
            }
        }
        drop(model);

        for path in &paths {
            let _ = self.events.send(format!(
                "#e# net {} {}",
                path,
                if opening { "open" } else { "closed" }
            ));
        }
        let final_path = paths.pop().expect("nonempty lifecycle target");
        let mut lines = paths
            .into_iter()
            .map(|path| format!("OK: {path}"))
            .collect::<Vec<_>>();
        if opening {
            lines.extend([
                "120-initializing".to_string(),
                "120-opening port".to_string(),
                "120-starting network threads".to_string(),
                "120-pci reset".to_string(),
                "120-checking connection".to_string(),
                "120-relinking to bridged networks".to_string(),
                "120-open complete".to_string(),
            ]);
        }
        Response {
            tag: tag.to_string(),
            lines,
            final_text: format!("200 OK: {final_path}"),
            status: 200,
        }
    }

    async fn net_catalog_list(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        if words.len() > 3 {
            return err(tag, 400, "400 Syntax Error.");
        }
        let project = words.get(2).map_or_else(
            || current_project(self, client),
            |value| (*value).to_string(),
        );
        let model = self.model.lock().await;
        let Ok(definitions) = catalog(&model, &project) else {
            return err(tag, 404, "404 Project not found");
        };
        if definitions.is_empty() {
            return Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                final_text: "132 no networks found".to_string(),
                status: 132,
            };
        }
        let mut rows =
            definitions
                .into_iter()
                .map(|definition| {
                    let (state, interface_state) =
                        definition
                            .bound_network
                            .and_then(|address| {
                                model.projects.get(&project)?.networks.get(&address).map(
                                    |network| match network.state {
                                        NetworkState::Closed => ("new", "closed"),
                                        NetworkState::Open => ("open", "open"),
                                        NetworkState::Syncing => ("syncing", "open"),
                                        NetworkState::Ok => ("ok", "open"),
                                    },
                                )
                            })
                            .unwrap_or(("new", "closed"));
                    format!(
                        "network={} State={state} InterfaceState={interface_state}",
                        definition.name
                    )
                })
                .collect::<Vec<_>>();
        rows.sort();
        let final_text = rows.pop().expect("nonempty network catalogue");
        Response {
            tag: tag.to_string(),
            lines: rows,
            final_text,
            status: 131,
        }
    }

    async fn net_catalog_mutation(
        &self,
        client: &ClientState,
        tag: &str,
        words: &[&str],
        sub: &str,
    ) -> Response {
        let _commands = self.commands.lock().await;
        let current = current_project(self, client);
        let mut model = self.model.lock().await;
        if !model.projects.contains_key(&current) {
            return err(tag, 408, "408 Operation failed: No project specified");
        }
        let before = model.clone();
        let response = match sub {
            "CREATE" => {
                if words.len() < 5 || !valid_network_name(words[2]) {
                    err(tag, 400, "400 Syntax Error.")
                } else if !matches!(
                    words[3].to_ascii_lowercase().as_str(),
                    "serial" | "cni" | "etherlite" | "socket" | "bridge" | "modem" | "wiser"
                ) {
                    err(
                        tag,
                        408,
                        "408 Operation failed: Unsupported network interface type",
                    )
                } else {
                    match catalog(&model, &current) {
                        Err(error) => err(tag, 500, &format!("500 {error}")),
                        Ok(mut definitions) => {
                            if definitions
                                .iter()
                                .any(|definition| definition.name == words[2])
                            {
                                err(
                                    tag,
                                    408,
                                    "408 Operation failed: Network name already in use",
                                )
                            } else {
                                definitions.push(NetDefinition {
                                    name: words[2].to_string(),
                                    interface_type: words[3].to_string(),
                                    interface_address: words[4].to_string(),
                                    options: words[5..]
                                        .iter()
                                        .map(|word| (*word).to_string())
                                        .collect(),
                                    bound_network: None,
                                });
                                definitions.sort_by(|left, right| left.name.cmp(&right.name));
                                match put_catalog(&mut model, &current, &definitions) {
                                    Ok(()) => ok(tag, vec![], "200 OK."),
                                    Err(error) => err(tag, 500, &format!("500 {error}")),
                                }
                            }
                        }
                    }
                }
            }
            "DELETE" => {
                if words.len() != 3 {
                    err(tag, 400, "400 Syntax Error.")
                } else {
                    match split_network_address(words[2], &current) {
                        None => err(
                            tag,
                            401,
                            &format!(
                                "401 Bad object or device ID: {} (Object not found)",
                                words[2]
                            ),
                        ),
                        Some((project, name)) => {
                            match catalog(&model, &project) {
                                Err(_) => err(
                                    tag,
                                    401,
                                    &format!(
                                        "401 Bad object or device ID: {} (Object not found)",
                                        words[2]
                                    ),
                                ),
                                Ok(mut definitions) => match definitions
                                    .iter()
                                    .position(|definition| definition.name == name)
                                {
                                    None => err(
                                        tag,
                                        401,
                                        &format!(
                                            "401 Bad object or device ID: {} (Object not found)",
                                            words[2]
                                        ),
                                    ),
                                    Some(index) => {
                                        let open = definitions[index]
                                            .bound_network
                                            .and_then(|address| {
                                                model.projects.get(&project)?.networks.get(&address)
                                            })
                                            .is_some_and(|network| {
                                                network.state != NetworkState::Closed
                                            });
                                        if open {
                                            err(tag, 468, "468 Can not delete open network: network is operating")
                                        } else {
                                            definitions.remove(index);
                                            match put_catalog(&mut model, &project, &definitions) {
                                                Ok(()) => ok(tag, vec![], "200 OK."),
                                                Err(error) => {
                                                    err(tag, 500, &format!("500 {error}"))
                                                }
                                            }
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            }
            "RENAME" => {
                if !(words.len() == 4
                    || (words.len() == 5 && words[4].eq_ignore_ascii_case("nofixrefs")))
                    || !valid_network_name(words.get(3).copied().unwrap_or(""))
                {
                    err(tag, 400, "400 Syntax Error.")
                } else {
                    match split_network_address(words[2], &current) {
                        None => err(
                            tag,
                            401,
                            &format!(
                                "401 Bad object or device ID: {} (Object not found)",
                                words[2]
                            ),
                        ),
                        Some((project, name)) => {
                            match catalog(&model, &project) {
                                Err(_) => err(
                                    tag,
                                    401,
                                    &format!(
                                        "401 Bad object or device ID: {} (Object not found)",
                                        words[2]
                                    ),
                                ),
                                Ok(mut definitions) => {
                                    if definitions
                                        .iter()
                                        .any(|definition| definition.name == words[3])
                                    {
                                        err(tag, 408, "408 Operation failed: New name is in use")
                                    } else if let Some(definition) = definitions
                                        .iter_mut()
                                        .find(|definition| definition.name == name)
                                    {
                                        definition.name = words[3].to_string();
                                        definitions
                                            .sort_by(|left, right| left.name.cmp(&right.name));
                                        match put_catalog(&mut model, &project, &definitions) {
                                            Ok(()) => ok(tag, vec![], "200 OK."),
                                            Err(error) => err(tag, 500, &format!("500 {error}")),
                                        }
                                    } else {
                                        err(tag, 401, &format!("401 Bad object or device ID: {} (Object not found)", words[2]))
                                    }
                                }
                            }
                        }
                    }
                }
            }
            "SAVE" => {
                if !(3..=4).contains(&words.len()) {
                    err(tag, 400, "400 Syntax Error.")
                } else if !matches!(words[2].to_ascii_uppercase().as_str(), "DB" | "FILE") {
                    err(
                        tag,
                        400,
                        "400 Syntax Error: <destination> must be 'DB' or 'FILE'.",
                    )
                } else {
                    let target = words.get(3).copied().unwrap_or(&current);
                    if !model.projects.contains_key(target) {
                        return err(
                            tag,
                            401,
                            &format!("401 Bad object or device ID: {target} (Network not found)"),
                        );
                    }
                    match catalog(&model, target) {
                        Err(error) => err(tag, 500, &format!("500 {error}")),
                        Ok(definitions) => match serde_json::to_string(&definitions) {
                            Err(error) => err(tag, 500, &format!("500 {error}")),
                            Ok(value) => {
                                model
                                    .config_values
                                    .insert(snapshot_key(target, words[2]), value);
                                ok(tag, vec![], "200 OK.")
                            }
                        },
                    }
                }
            }
            "LOAD" => {
                if !(3..=4).contains(&words.len()) {
                    err(tag, 400, "400 Syntax Error.")
                } else if !matches!(words[2].to_ascii_uppercase().as_str(), "DB" | "FILE") {
                    err(
                        tag,
                        400,
                        "400 Syntax Error: <source> must be 'DB' or 'FILE'.",
                    )
                } else {
                    let target = words.get(3).copied().unwrap_or(&current);
                    if !model.projects.contains_key(target) {
                        return err(
                            tag,
                            401,
                            &format!("401 Bad object or device ID: {target} (Network not found)"),
                        );
                    }
                    let saved = model
                        .config_values
                        .get(&snapshot_key(target, words[2]))
                        .cloned();
                    match saved.as_deref().map(decode_catalog) {
                        None => err(
                            tag,
                            408,
                            "408 Operation failed: Network definitions file not found",
                        ),
                        Some(Err(error)) => err(tag, 500, &format!("500 {error}")),
                        Some(Ok(saved)) => match catalog(&model, target) {
                            Err(error) => err(tag, 500, &format!("500 {error}")),
                            Ok(mut active) => {
                                if saved.iter().any(|candidate| {
                                    active
                                        .iter()
                                        .any(|definition| definition.name == candidate.name)
                                }) {
                                    err(tag, 408, "408 Operation failed: Problem loading: Network name already in use")
                                } else {
                                    active.extend(saved);
                                    active.sort_by(|left, right| left.name.cmp(&right.name));
                                    match put_catalog(&mut model, target, &active) {
                                        Ok(()) => ok(tag, vec![], "200 OK."),
                                        Err(error) => err(tag, 500, &format!("500 {error}")),
                                    }
                                }
                            }
                        },
                    }
                }
            }
            _ => unreachable!("caller restricts lifecycle subcommands"),
        };
        if response.status >= 400 {
            *model = before;
            return response;
        }
        let after = Database::from_server(&model);
        if let Err(error) = after.save(&self.state_path) {
            *model = before;
            tracing::error!("C-Gate NET catalogue commit failed: {error}");
            return err(tag, 500, "500 Database commit failed; change rolled back");
        }
        response
    }

    async fn net_catalog_flush(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(tag, 400, "400 Syntax Error.");
        }
        let _commands = self.commands.lock().await;
        let current = current_project(self, client);
        let mut model = self.model.lock().await;
        let (project, definition) = match network_definition(&model, words[2], &current) {
            Ok(value) => value,
            Err(_) => {
                return err(
                    tag,
                    401,
                    &format!(
                        "401 Bad object or device ID: {} (Object not found)",
                        words[2]
                    ),
                )
            }
        };
        if let Some(network) = definition
            .bound_network
            .and_then(|address| model.projects.get_mut(&project)?.networks.get_mut(&address))
        {
            network.physical.clear();
            network.levels.clear();
        }
        ok(tag, vec![], "200 OK.")
    }

    async fn net_learn(&self, client: &ClientState, tag: &str, words: &[&str]) -> Response {
        if words.len() != 6 {
            return err(tag, 400, "400 Syntax Error.");
        }
        let Some(application) = parse_byte(words[3]) else {
            return err(tag, 400, "400 Syntax Error.");
        };
        let Some(grade) = parse_byte(words[4]) else {
            return err(tag, 400, "400 Syntax Error.");
        };
        let Some(group) = parse_byte(words[5]) else {
            return err(tag, 400, "400 Syntax Error.");
        };
        let command = LearnMode {
            application,
            grade,
            group,
        };
        if command.encode().is_err() {
            return err(
                tag,
                400,
                "400 Syntax Error: Integer parameter is out of range : <grade>",
            );
        }
        let current = current_project(self, client);
        let direct = {
            let model = self.model.lock().await;
            network_definition(&model, words[2], &current)
                .ok()
                .is_some_and(|(project, definition)| {
                    project == self.project && definition.bound_network == Some(self.network)
                })
        };
        if !direct {
            return err(
                tag,
                502,
                "502 NET LEARN requires the directly bound shared PCI network",
            );
        }
        let _commands = self.commands.lock().await;
        self.send_application_once(
            tag,
            Sal::LearnMode(command),
            ok(tag, vec![], "200 OK."),
            "NET LEARN",
        )
        .await
    }

    pub(super) async fn network_locate(
        &self,
        client: &ClientState,
        tag: &str,
        words: &[&str],
    ) -> Response {
        if !(words.len() == 6 || words.len() == 7) {
            return err(tag, 400, "400 Syntax Error.");
        }
        let current = current_project(self, client);
        let (project, network_name, application) =
            match split_application_address(words[2], &current) {
                Some(value) => value,
                None => {
                    return err(
                        tag,
                        401,
                        &format!(
                            "401 Bad object or device ID: {} (Object not found)",
                            words[2]
                        ),
                    )
                }
            };
        if application != 208 {
            return err(
                tag,
                402,
                &format!("402 Operation not supported by: {}", words[2]),
            );
        }
        let direct = {
            let model = self.model.lock().await;
            catalog(&model, &project)
                .ok()
                .and_then(|definitions| {
                    definitions
                        .into_iter()
                        .find(|definition| definition.name == network_name)
                })
                .is_some_and(|definition| {
                    project == self.project && definition.bound_network == Some(self.network)
                })
        };
        if !direct {
            return err(
                tag,
                502,
                "502 NETWORK LOCATE requires the directly bound shared PCI network",
            );
        }
        let selector = words[3].to_ascii_uppercase();
        let command = match selector.as_str() {
            "UNIT" if words.len() == 6 => match (parse_byte(words[4]), parse_mode(words[5])) {
                (Some(unit), Some(mode)) => NetworkLocate {
                    target: LocateTarget::Unit(unit),
                    mode,
                },
                _ => return err(tag, 400, "400 Syntax Error."),
            },
            "APP" if words.len() == 6 => match (parse_byte(words[4]), parse_mode(words[5])) {
                (Some(application), Some(mode)) => NetworkLocate {
                    target: LocateTarget::Application(application),
                    mode,
                },
                _ => return err(tag, 400, "400 Syntax Error."),
            },
            "GROUP" if words.len() == 7 => match (
                parse_byte(words[4]),
                parse_byte(words[5]),
                parse_mode(words[6]),
            ) {
                (Some(application), Some(group), Some(mode)) => NetworkLocate {
                    target: LocateTarget::Group { application, group },
                    mode,
                },
                _ => return err(tag, 400, "400 Syntax Error."),
            },
            "SERIAL" if words.len() == 7 => match (
                parse_byte(words[4]),
                parse_native_serial(words[5]),
                parse_mode(words[6]),
            ) {
                (Some(manufacturer), Ok(serial), Some(mode)) => NetworkLocate {
                    target: LocateTarget::Serial {
                        manufacturer,
                        serial,
                    },
                    mode,
                },
                _ => return err(tag, 400, "400 Syntax Error."),
            },
            _ => return err(tag, 400, "400 Syntax Error."),
        };
        if command.encode().is_err() {
            return err(tag, 400, "400 Syntax Error.");
        }
        let _commands = self.commands.lock().await;
        self.send_application_once(
            tag,
            Sal::NetworkLocate(command),
            ok(tag, vec![], "200 OK."),
            "NETWORK LOCATE",
        )
        .await
    }

    /// Native PROJECT START/STOP are runtime operations.  They do not rewrite
    /// the project repository.  For the configured project STOP releases the
    /// C-Gate runtime caches while cmqttd deliberately keeps its already-owned
    /// PCI and MQTT bridge alive; START reattaches that runtime to the same
    /// connected PCI and restores reachable bridge-network state.
    pub(super) async fn project_start_stop(
        &self,
        client: &ClientState,
        tag: &str,
        words: &[&str],
    ) -> Response {
        let starting = words
            .get(1)
            .is_some_and(|word| word.eq_ignore_ascii_case("START"));
        let current = current_project(self, client);
        let requested = words.get(2).copied().unwrap_or(&current);
        let project = if requested.starts_with('@') || requested.starts_with("//@") {
            current
        } else {
            requested.to_string()
        };
        if project.is_empty() {
            return err(
                tag,
                408,
                &format!(
                    "408 Project {} failed: No project specified",
                    if starting { "start" } else { "stop" }
                ),
            );
        }

        let _commands = self.commands.lock().await;
        if starting && project == self.project && !self.pci.read().await.is_connected() {
            return err(
                tag,
                408,
                "408 Project start failed: configured shared PCI is not connected",
            );
        }
        let mut model = self.model.lock().await;
        let Some(selected) = model.projects.get_mut(&project) else {
            return err(
                tag,
                408,
                &format!(
                    "408 Project {} failed: Project not found: {project}",
                    if starting { "start" } else { "stop" }
                ),
            );
        };
        for network in selected.networks.values_mut() {
            if starting {
                network.state = NetworkState::Open;
            } else {
                network.state = NetworkState::Closed;
                network.physical.clear();
                network.levels.clear();
            }
        }
        if starting && project == self.project {
            open_reachable_networks(&mut model, &self.project, self.network);
        }
        drop(model);
        let _ = self.events.send(format!(
            "#e# project {project} {}",
            if starting { "started" } else { "stopped" }
        ));
        ok(tag, vec![], "200 OK.")
    }

    /// Explore one or more explicit interfaces. The configured interface is
    /// inspected through cmqttd's shared PCI so MQTT never loses ownership;
    /// other CNI/socket/serial descriptors are opened transiently, reset,
    /// inventoried, and closed before this command returns.
    pub(super) async fn topology_explore(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 {
            return err(tag, 408, "408 Operation failed: No interfaces to explore");
        }
        let _commands = self.commands.lock().await;
        let configured = {
            let model = self.model.lock().await;
            let network = &model.projects[&self.project].networks[&self.network];
            (
                network.iface_type.clone(),
                network.iface_addr.clone(),
                network
                    .units
                    .values()
                    .filter(|unit| looks_like_bridge(&unit.unit_type))
                    .count(),
            )
        };
        let mut rows = Vec::new();
        for (index, specification) in words[2..].iter().enumerate() {
            let name = format!("NET{index}");
            let descriptor = match parse_topology_interface(specification) {
                Ok(descriptor) => descriptor,
                Err(()) => {
                    return Response {
                        tag: tag.to_string(),
                        lines: vec![format!(
                            "470-Bad interface specification for {name} {specification}"
                        )],
                        final_text: "408 Operation failed: bad interface specification".to_string(),
                        status: 408,
                    }
                }
            };
            let configured_descriptor_match = configured
                .0
                .eq_ignore_ascii_case(&descriptor.interface_type)
                && configured.1 == descriptor.address;
            let configured_endpoint_match =
                match (descriptor.endpoint.as_ref(), self.port_endpoint.get()) {
                    (Some(requested), Some(active)) => {
                        crate::port::endpoints_equal(requested, active).await
                    }
                    _ => false,
                };
            let uses_shared = configured_descriptor_match || configured_endpoint_match;
            let (states, project_identity, bridge_count) = if uses_shared {
                let (generation, pci) = self.current_pci_epoch().await;
                let explored = explore_pci(&pci).await;
                let Some(_guard) = self.pci_commit_guard(generation, &pci).await else {
                    return err(
                        tag,
                        408,
                        "408 Operation failed: PCI reconnected during topology exploration",
                    );
                };
                match explored {
                    Ok((states, identity)) => (states, identity, configured.2),
                    Err(error) => {
                        return err(tag, 473, &format!("473 MMI failed: {name} ({error})"))
                    }
                }
            } else {
                let endpoint = match descriptor.endpoint {
                    Some(endpoint) => endpoint,
                    None => {
                        return err(
                            tag,
                            472,
                            &format!(
                                "472 Can not open network: {name} {} (unsupported interface type)",
                                descriptor.address
                            ),
                        )
                    }
                };
                let (reader, writer) = match conn::connect(&endpoint).await {
                    Ok(streams) => streams,
                    Err(error) => {
                        return err(
                            tag,
                            472,
                            &format!(
                                "472 Can not open network: {name} {} ({error})",
                                descriptor.address
                            ),
                        )
                    }
                };
                let (events, mut event_rx) = mpsc::unbounded_channel();
                let pci = PciClient::new(reader, writer, events);
                let drain = tokio::spawn(async move { while event_rx.recv().await.is_some() {} });
                let explored = async {
                    pci.pci_reset().await?;
                    explore_pci(&pci).await
                }
                .await;
                pci.shutdown().await;
                drain.abort();
                let _ = drain.await;
                match explored {
                    Ok((states, identity)) => (states, identity, 0),
                    Err(error) => {
                        return err(tag, 473, &format!("473 MMI failed: {name} ({error})"))
                    }
                }
            };
            debug_assert_eq!(states.len(), 256);
            rows.push(format!("323-Network Found {name} {}", descriptor.address));
            rows.push(format!(
                "321-Network Serial {name} {}",
                project_identity.unwrap_or_else(|| "[unknown]".to_string())
            ));
            rows.push(format!("324-Bridges Found {name} {bridge_count}"));
        }
        let final_text = rows
            .pop()
            .expect("TOPOLOGY EXPLORE has at least one interface")
            .replacen("324-", "324 ", 1);
        Response {
            tag: tag.to_string(),
            lines: rows,
            final_text,
            status: 324,
        }
    }
}

struct TopologyInterface {
    interface_type: String,
    address: String,
    endpoint: Option<Endpoint>,
}

fn parse_topology_interface(specification: &str) -> Result<TopologyInterface, ()> {
    let (interface_type, tail) = specification.split_once('@').ok_or(())?;
    if interface_type.is_empty() || tail.is_empty() || tail.contains('@') {
        return Err(());
    }
    let mut pieces = tail.split(';');
    let address = pieces.next().filter(|value| !value.is_empty()).ok_or(())?;
    let mut baud = 9_600u32;
    for option in pieces {
        let (name, value) = option.split_once('=').ok_or(())?;
        if name.is_empty() || value.is_empty() || value.contains('=') {
            return Err(());
        }
        if name.eq_ignore_ascii_case("baud") {
            baud = value.parse().map_err(|_| ())?;
        }
    }
    let kind = interface_type.to_ascii_lowercase();
    let endpoint = match kind.as_str() {
        "cni" | "socket" | "wiser" => Some(Endpoint::parse_tcp(address).map_err(|_| ())?),
        "serial" => Some(Endpoint::serial(address, baud)),
        _ => None,
    };
    Ok(TopologyInterface {
        interface_type: interface_type.to_string(),
        address: address.to_string(),
        endpoint,
    })
}

fn looks_like_bridge(unit_type: &str) -> bool {
    let unit_type = unit_type.to_ascii_uppercase();
    unit_type.contains("BRIDGE")
        || unit_type.starts_with("5500NB")
        || unit_type.starts_with("CNI_BR")
}

async fn explore_pci(pci: &Arc<PciClient>) -> io::Result<(Vec<u8>, Option<String>)> {
    let states = pci.install_mmi().await?;
    if states.len() != 256 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "installation MMI returned incomplete address coverage",
        ));
    }
    let mut identity = None;
    for address in 1u16..=255 {
        let address = address as u8;
        if states[usize::from(address)] == 0
            || project_identify_candidate(pci, address).await.is_err()
        {
            continue;
        }
        let Ok(encoded) = pci.recall_parameter(address, 35, 6).await else {
            continue;
        };
        let Ok(decoded) = cbus_protocol::project_identity::decode_project_identity(&encoded) else {
            continue;
        };
        identity = Some(decoded.trim().to_string());
        break;
    }
    Ok((states, identity))
}

fn split_application_address(value: &str, current: &str) -> Option<(String, String, u8)> {
    let parts = value
        .trim_start_matches('/')
        .split('/')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    if value.starts_with("//") {
        let [project, network, application] = parts.as_slice() else {
            return None;
        };
        Some((
            (*project).to_string(),
            (*network).to_string(),
            parse_byte(application)?,
        ))
    } else {
        let [network, application] = parts.as_slice() else {
            return None;
        };
        Some((
            current.to_string(),
            (*network).to_string(),
            parse_byte(application)?,
        ))
    }
}
