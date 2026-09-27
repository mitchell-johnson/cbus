//! Sequential, bounded CNI discovery across explicit or OS-derived IPv4 routes.

use cbus_protocol::cni_discovery::DISCOVERY_QUERY;
use cbus_transport::cni_discovery::MAX_DISCOVERY_DATAGRAMS;
use if_addrs::IfAddr;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::net::Ipv4Addr;

const MAX_ROUTES: usize = 16;
const MAX_ADAPTERS: usize = 256;
const MAX_SCAN_SECONDS: f64 = 300.0;

pub(crate) struct ScanArgs {
    pub probes: Vec<String>,
    pub auto_adapters: bool,
    pub interfaces: Vec<String>,
    pub plan_only: bool,
    pub listen_port: u16,
    pub discovery_port: u16,
    pub timeout: f64,
    pub max_datagrams: usize,
    pub include_hidden: bool,
}

#[derive(Clone, Debug)]
struct Candidate {
    name: String,
    up: bool,
    point_to_point: bool,
    ipv4: Option<(Ipv4Addr, Ipv4Addr, Option<Ipv4Addr>)>,
}

#[derive(Clone, Debug, Serialize)]
struct AdapterRoute {
    interface: String,
    bind: Ipv4Addr,
    destination: Ipv4Addr,
    netmask: Ipv4Addr,
    prefix_length: u32,
    reported_broadcast: Option<Ipv4Addr>,
}

fn host_candidates() -> Result<Vec<Candidate>, String> {
    let interfaces = if_addrs::get_if_addrs()
        .map_err(|error| format!("CNI adapter inventory failed: {error}"))?;
    Ok(interfaces
        .into_iter()
        .map(|interface| {
            let up = interface.is_oper_up();
            let point_to_point = interface.is_p2p();
            let ipv4 = match interface.addr {
                IfAddr::V4(address) => Some((address.ip, address.netmask, address.broadcast)),
                IfAddr::V6(_) => None,
            };
            Candidate {
                name: interface.name,
                up,
                point_to_point,
                ipv4,
            }
        })
        .collect())
}

fn directed_broadcast(ip: Ipv4Addr, netmask: Ipv4Addr) -> Result<(Ipv4Addr, u32), &'static str> {
    let mask = u32::from(netmask);
    let prefix = mask.leading_ones();
    let contiguous = if prefix == 0 {
        0
    } else {
        u32::MAX << (32 - prefix)
    };
    if mask != contiguous {
        return Err("invalid_ipv4_or_netmask");
    }
    if !(1..=30).contains(&prefix) {
        return Err("no_usable_directed_broadcast");
    }
    let network = u32::from(ip) & mask;
    let broadcast = network | !mask;
    if u32::from(ip) == network || u32::from(ip) == broadcast {
        return Err("no_usable_directed_broadcast");
    }
    Ok((Ipv4Addr::from(broadcast), prefix))
}

fn plan_adapters(
    candidates: Vec<Candidate>,
    requested: &[String],
) -> Result<(Vec<AdapterRoute>, Value), String> {
    let mut groups: BTreeMap<String, Vec<Candidate>> = BTreeMap::new();
    for candidate in candidates {
        if candidate.name.is_empty() {
            return Err("CNI adapter inventory contains an invalid name".into());
        }
        groups
            .entry(candidate.name.clone())
            .or_default()
            .push(candidate);
    }
    if groups.len() > MAX_ADAPTERS {
        return Err("CNI host adapter inventory exceeds its bound".into());
    }
    let requested_set: BTreeSet<&str> = requested.iter().map(String::as_str).collect();
    if requested.iter().any(String::is_empty) || requested_set.len() != requested.len() {
        return Err("CNI adapter names must be a nonempty unique sequence".into());
    }
    for name in &requested_set {
        if !groups.contains_key(*name) {
            return Err(format!("CNI requested adapter is absent: {name}"));
        }
    }
    let names: Vec<String> = if requested.is_empty() {
        groups.keys().cloned().collect()
    } else {
        requested_set.into_iter().map(str::to_owned).collect()
    };
    let mut selected = Vec::new();
    let mut skipped = Vec::new();
    let mut seen = BTreeSet::new();
    for name in names {
        let entries = &groups[&name];
        if !entries.iter().any(|entry| entry.up) {
            skipped.push(json!({"interface": name, "reason": "down_or_status_unavailable"}));
            continue;
        }
        let mut ipv4_found = false;
        for entry in entries {
            let Some((ip, netmask, reported)) = entry.ipv4 else {
                continue;
            };
            ipv4_found = true;
            if !entry.up {
                skipped.push(json!({"interface": name, "address": ip, "reason": "down_or_status_unavailable"}));
                continue;
            }
            if ip.is_loopback() || ip.is_multicast() || ip.is_unspecified() || entry.point_to_point
            {
                skipped.push(json!({"interface": name, "address": ip, "reason": "loopback_multicast_or_point_to_point"}));
                continue;
            }
            let (destination, prefix_length) = match directed_broadcast(ip, netmask) {
                Ok(value) => value,
                Err(reason) => {
                    skipped.push(json!({"interface": name, "address": ip, "reason": reason}));
                    continue;
                }
            };
            if let Some(reported) = reported {
                if reported != destination && reported != Ipv4Addr::BROADCAST {
                    skipped.push(json!({"interface": name, "address": ip, "reason": "reported_broadcast_mismatch"}));
                    continue;
                }
            }
            if !seen.insert((ip, destination)) {
                skipped
                    .push(json!({"interface": name, "address": ip, "reason": "duplicate_route"}));
                continue;
            }
            selected.push(AdapterRoute {
                interface: name.clone(),
                bind: ip,
                destination,
                netmask,
                prefix_length,
                reported_broadcast: reported,
            });
        }
        if !ipv4_found {
            skipped.push(json!({"interface": name, "reason": "no_ipv4_address"}));
        }
    }
    selected.sort_by_key(|route| (route.interface.clone(), route.bind));
    for name in requested {
        if !selected.iter().any(|route| &route.interface == name) {
            return Err(format!(
                "CNI requested adapter has no usable broadcast route: {name}"
            ));
        }
    }
    if selected.is_empty() {
        return Err("No active broadcast-capable IPv4 adapter was found".into());
    }
    if selected.len() > MAX_ROUTES {
        return Err(format!(
            "CNI automatic scan exceeds {MAX_ROUTES} route limit"
        ));
    }
    let plan = json!({
        "source": "if-addrs.get_if_addrs",
        "requested_interfaces": if requested.is_empty() { Value::Null } else { json!(requested) },
        "selected": selected,
        "skipped": skipped,
        "probe_count": selected.len(),
        "network_state_snapshot_atomic": false,
        "egress_interface_verified": false,
        "absence_proven": false,
    });
    Ok((selected, plan))
}

fn explicit_routes(probes: &[String]) -> Result<Vec<(Ipv4Addr, Ipv4Addr)>, String> {
    if !(1..=MAX_ROUTES).contains(&probes.len()) {
        return Err(format!("CNI discovery requires 1..={MAX_ROUTES} probes"));
    }
    let mut routes = Vec::new();
    let mut seen = BTreeSet::new();
    for probe in probes {
        let (bind, destination) = probe
            .split_once('@')
            .ok_or_else(|| "CNI discovery probe must be BIND_IPV4@DESTINATION_IPV4".to_string())?;
        let bind: Ipv4Addr = bind
            .parse()
            .map_err(|_| "CNI discovery probe bind must be IPv4")?;
        let destination: Ipv4Addr = destination
            .parse()
            .map_err(|_| "CNI discovery probe destination must be IPv4")?;
        if !seen.insert((bind, destination)) {
            return Err("CNI discovery probes must be unique".into());
        }
        routes.push((bind, destination));
    }
    Ok(routes)
}

pub(crate) async fn scan(args: ScanArgs) -> Result<Value, String> {
    if !args.auto_adapters && (!args.interfaces.is_empty() || args.plan_only) {
        return Err("--interface and --plan-only require --auto-adapters".into());
    }
    if !args.timeout.is_finite() || args.timeout <= 0.0 || args.timeout > MAX_SCAN_SECONDS {
        return Err("CNI discovery timeout must be finite and in (0, 300]".into());
    }
    if !(1..=MAX_DISCOVERY_DATAGRAMS).contains(&args.max_datagrams) {
        return Err(format!(
            "CNI discovery max_datagrams must be in 1..={MAX_DISCOVERY_DATAGRAMS}"
        ));
    }
    if args.discovery_port == 0 {
        return Err("CNI discovery destination port must be in 1..=65535".into());
    }
    let (routes, plan) = if args.auto_adapters {
        let (adapters, plan) = plan_adapters(host_candidates()?, &args.interfaces)?;
        (
            adapters
                .iter()
                .map(|route| (route.bind, route.destination))
                .collect(),
            Some((adapters, plan)),
        )
    } else {
        (explicit_routes(&args.probes)?, None)
    };
    if args.timeout * routes.len() as f64 > MAX_SCAN_SECONDS {
        return Err(format!(
            "CNI discovery configured scan window must be <= {MAX_SCAN_SECONDS} seconds"
        ));
    }
    if args.plan_only {
        return Ok(plan.expect("auto mode required for plan-only").1);
    }
    let mut observations = Vec::new();
    for (index, (bind, destination)) in routes.iter().enumerate() {
        let mut probe = match crate::cni_discover_report(
            *bind,
            args.listen_port,
            *destination,
            args.discovery_port,
            args.timeout,
            args.max_datagrams,
            args.include_hidden,
        )
        .await
        {
            Ok(observation) => {
                let outcome = if observation["collection_complete"] == false {
                    "datagram_limit"
                } else if observation["devices"]
                    .as_array()
                    .is_some_and(|items| !items.is_empty())
                {
                    "devices_observed"
                } else if observation["hidden_ignored"].as_u64().unwrap_or(0) > 0
                    && observation["malformed"]
                        .as_array()
                        .is_some_and(|items| !items.is_empty())
                {
                    "filtered_replies_by_deadline"
                } else if observation["hidden_ignored"].as_u64().unwrap_or(0) > 0 {
                    "hidden_replies_by_deadline"
                } else if observation["malformed"]
                    .as_array()
                    .is_some_and(|items| !items.is_empty())
                {
                    "no_valid_reply_by_deadline"
                } else {
                    "no_reply_by_deadline"
                };
                json!({"route": {"bind": bind, "destination": destination}, "outcome": outcome,
                       "query_sent_once": true, "error": null, "observation": observation})
            }
            Err(error) => json!({"route": {"bind": bind, "destination": destination},
                                 "outcome": "transport_error", "query_sent_once": null,
                                 "error": error, "observation": null}),
        };
        if let Some((adapters, _)) = &plan {
            probe["adapter"] = json!(adapters[index]);
        }
        observations.push(probe);
    }
    let scan_complete = observations
        .iter()
        .all(|probe| probe["observation"]["collection_complete"] == true);
    let mut report = json!({
        "format": "cbus-cni-multi-discovery-v1",
        "query_hex": hex::encode(DISCOVERY_QUERY),
        "probes": observations,
        "probe_count": observations.len(),
        "scan_complete": scan_complete,
        "absence_proven": false,
        "ownership_checked": false,
        "tcp_connection_opened": false,
    });
    if let Some((_, plan)) = plan {
        report["automatic_adapter_enumeration"] = json!(true);
        report["adapter_enumeration"] = plan;
        report["egress_interface_verified"] = json!(false);
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(name: &str, ip: Ipv4Addr, netmask: Ipv4Addr) -> Candidate {
        Candidate {
            name: name.into(),
            up: true,
            point_to_point: false,
            ipv4: Some((ip, netmask, None)),
        }
    }

    #[test]
    fn plans_directed_broadcast_and_skips_unsafe_adapters() {
        let inputs = vec![
            candidate(
                "zlan",
                Ipv4Addr::new(192, 168, 10, 20),
                Ipv4Addr::new(255, 255, 255, 0),
            ),
            candidate(
                "alan",
                Ipv4Addr::new(10, 2, 2, 10),
                Ipv4Addr::new(255, 255, 254, 0),
            ),
            candidate("loop", Ipv4Addr::LOCALHOST, Ipv4Addr::new(255, 0, 0, 0)),
            candidate(
                "badmask",
                Ipv4Addr::new(10, 0, 1, 2),
                Ipv4Addr::new(255, 0, 255, 0),
            ),
        ];
        let (routes, plan) = plan_adapters(inputs, &[]).unwrap();
        assert_eq!(routes.len(), 2);
        assert_eq!(routes[0].interface, "alan");
        assert_eq!(routes[0].destination, Ipv4Addr::new(10, 2, 3, 255));
        assert_eq!(routes[1].destination, Ipv4Addr::new(192, 168, 10, 255));
        assert_eq!(plan["probe_count"], 2);
        assert_eq!(plan["egress_interface_verified"], false);
        assert_eq!(plan["absence_proven"], false);
        assert_eq!(plan["skipped"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn rejects_requested_unusable_adapter_and_duplicate_explicit_routes() {
        let inputs = vec![candidate(
            "loop",
            Ipv4Addr::LOCALHOST,
            Ipv4Addr::new(255, 0, 0, 0),
        )];
        assert!(plan_adapters(inputs, &["loop".into()])
            .unwrap_err()
            .contains("no usable"));
        assert!(
            explicit_routes(&["127.0.0.1@127.0.0.1".into(), "127.0.0.1@127.0.0.1".into()])
                .unwrap_err()
                .contains("unique")
        );
    }
}
