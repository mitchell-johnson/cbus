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
            sub @ ("CREATE" | "DELETE" | "LOAD" | "RENAME" | "SAVE") => {
                self.net_catalog_mutation(client, tag, words, sub).await
            }
            _ => err(tag, 400, "400 Syntax Error."),
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
