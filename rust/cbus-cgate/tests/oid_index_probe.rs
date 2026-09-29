//! Replays the seeded owned-native shared-OID index probe.
//!
//! The `units` profile places 2-16 Units, and at most one leaf Application,
//! in one Network, drawing OIDs from a three-OID pool. The `cross` profile
//! creates two Networks in a random order, each holding one object per
//! shared OID; the later-created Network's object wins. Native C-Gate selects the
//! object registered last in its OID index: Applications before Units, each
//! in submission order. DBDELETE removes only the deleted key, and the next
//! DBSET, DBSETXML, SAVE or load rebuilds the index.

use cbus_cgate::{AccessLevel, Server};
use serde_json::{json, Value};

fn network_xml(network: &Value, number: u64, network_oid: &str, interface_oid: &str) -> String {
    let applications = network["applications"]
        .as_array()
        .unwrap()
        .iter()
        .map(|app| {
            assert!(app["groups"].as_array().unwrap().is_empty());
            format!(
                "<Application><OID>{}</OID><TagName>{}</TagName><Address>{}</Address></Application>",
                app["oid"].as_str().unwrap(),
                app["tag"].as_str().unwrap(),
                app["address"]
            )
        })
        .collect::<String>();
    let units = network["units"]
        .as_array()
        .unwrap()
        .iter()
        .map(|unit| {
            format!(
                "<Unit><OID>{}</OID><TagName>{}</TagName><Address>{}</Address><UnitType>KEYE1</UnitType><UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion><PP Name=\"UnitAddress\" Value=\"{}\"/></Unit>",
                unit["oid"].as_str().unwrap(),
                unit["tag"].as_str().unwrap(),
                unit["address"],
                unit["address"]
            )
        })
        .collect::<String>();
    format!(
        "<Network><OID>{network_oid}</OID><TagName>Local{number}</TagName><Address>{number}</Address><NetworkNumber>{number}</NetworkNumber><Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{applications}{units}</Network>"
    )
}

fn child(node: roxmltree::Node<'_, '_>, name: &str) -> String {
    node.children()
        .find(|child| child.has_tag_name(name))
        .and_then(|child| child.text())
        .unwrap_or_default()
        .to_string()
}

fn selected(server: &mut Server, oid: &str) -> Value {
    let response = server.handle(&format!("[q] DBGETXML !{oid}"));
    if response.status != 200 {
        return json!({"status": response.status});
    }
    let document =
        roxmltree::Document::parse(response.lines[0].strip_prefix("347-").unwrap()).unwrap();
    let root = document.root_element();
    json!({"status": 344, "element": root.tag_name().name(), "tag": child(root, "TagName")})
}

fn replay(native: &Value, profile: &str) {
    assert_eq!(native["schema"], "cgate-oid-index-probe-v1");
    assert_eq!(native["profile"], profile);
    let pool = native["shared_oids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|oid| oid.as_str().unwrap().to_string())
        .collect::<Vec<_>>();
    let seeds = native["seeds"].as_array().unwrap();
    assert_eq!(seeds.len(), 12);
    for seed in seeds {
        let plan = &seed["plan"];
        let project = plan["project"].as_str().unwrap();
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(
            server.handle(&format!("[1] PROJECT NEW {project}")).status,
            200
        );
        assert_eq!(
            server.handle(&format!("[2] PROJECT USE {project}")).status,
            200
        );
        for network in plan["create_order"].as_array().unwrap() {
            let created = server.handle(&format!(
                "[3] DBCREATENET {network} Local{network} Cni 127.0.0.1:1"
            ));
            assert_eq!(created.status, 200, "{created:?}");
        }
        let mut observed = Vec::new();
        let mut statuses = Vec::new();
        for network in plan["submit_order"].as_array().unwrap() {
            let number = network.as_u64().unwrap();
            let base = server.handle(&format!("[4] DBGETXML //{project}/{number}"));
            let parsed =
                roxmltree::Document::parse(base.lines[0].strip_prefix("347-").unwrap()).unwrap();
            let network_oid = child(parsed.root_element(), "OID");
            let interface_oid = child(
                parsed
                    .descendants()
                    .find(|node| node.has_tag_name("Interface"))
                    .unwrap(),
                "OID",
            );
            let document = network_xml(
                &plan["networks"][number.to_string()],
                number,
                &network_oid,
                &interface_oid,
            );
            let submitted =
                server.handle_document(&format!("[5] DBSETXML //{project}/{number}"), &document);
            statuses.push(submitted.status);
        }
        observed.push(json!({"step": "submit", "statuses": statuses}));
        let query = |server: &mut Server, step: &str| {
            let selections = pool
                .iter()
                .map(|oid| (oid.clone(), selected(server, oid)))
                .collect::<serde_json::Map<_, _>>();
            json!({"step": step, "selected": selections})
        };
        let lifecycle = |server: &mut Server| {
            for verb in ["SAVE", "CLOSE", "LOAD", "USE"] {
                assert_eq!(
                    server
                        .handle(&format!("[l] PROJECT {verb} {project}"))
                        .status,
                    200
                );
            }
        };
        observed.push(query(&mut server, "submitted"));
        lifecycle(&mut server);
        observed.push(query(&mut server, "reloaded"));
        let deletes = pool
            .iter()
            .map(|oid| {
                let status = server.handle(&format!("[d] DBDELETE !{oid}")).status;
                (oid.clone(), json!(status))
            })
            .collect::<serde_json::Map<_, _>>();
        observed.push(json!({"step": "delete", "statuses": deletes}));
        observed.push(query(&mut server, "deleted"));
        let first = &plan["submit_order"][0];
        let status = server
            .handle(&format!(
                "[s] DBSET //{project}/{first}/TagName Renamed{first}"
            ))
            .status;
        observed.push(json!({"step": "unrelated-dbset", "status": status}));
        observed.push(query(&mut server, "after-unrelated-dbset"));
        lifecycle(&mut server);
        observed.push(query(&mut server, "deleted-reloaded"));
        assert_eq!(
            Value::Array(observed),
            seed["steps"],
            "{profile} seed {}",
            seed["seed"]
        );
    }
}

#[test]
fn seeded_same_network_unit_oid_probe_matches_owned_native_capture() {
    replay(
        &serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_oid_index_probe_units.json"
        ))
        .unwrap(),
        "units",
    );
}

#[test]
fn seeded_cross_network_oid_probe_follows_native_network_creation_order() {
    replay(
        &serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_oid_index_probe_cross.json"
        ))
        .unwrap(),
        "cross",
    );
}
