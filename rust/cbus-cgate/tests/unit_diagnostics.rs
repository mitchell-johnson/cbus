//! Native C-Gate 3.4.0.2001 replies used by the Toolkit Diagnostics dialog
//! (P8.05), replayed against the mock model. The mock has no bus, so its
//! present-unit values are the native zero-summary state; exact rows must
//! match byte for byte and "shape" rows must keep the native envelope.
use cbus_cgate::{AccessLevel, Server};
use serde_json::Value;

fn vectors() -> Vec<Value> {
    include_str!("../../testdata/vectors/cgate_unit_diagnostics.jsonl")
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn server() -> Server {
    let mut server = Server::new(AccessLevel::Program).with_programming(true);
    for (index, command) in [
        "PROJECT NEW DIAGNOSE",
        "PROJECT USE DIAGNOSE",
        "DBCREATENET 254 Diag Cni 127.0.0.1:10001",
        "DBADDSAFE //DIAGNOSE/254 Unit 16 U16",
        "DBSETSAFE //DIAGNOSE/254/p/16/UnitType PC_CNIED",
        "DBADDSAFE //DIAGNOSE/254 Unit 99 U99",
        "DBSETSAFE //DIAGNOSE/254/p/99/UnitType KEYE1",
        "MOCK BUS-DEL //DIAGNOSE/254 99",
        "NET OPEN //DIAGNOSE/254",
    ]
    .into_iter()
    .enumerate()
    {
        let response = server.handle(&format!("[s{index}] {command}"));
        assert!(response.status < 400, "{command}: {response:?}");
    }
    server
}

fn lines(response: &cbus_cgate::Response) -> Vec<String> {
    let mut all = response.lines.clone();
    all.push(response.final_text.clone());
    all
}

#[test]
fn diagnostic_commands_match_native_envelopes() {
    let rows = vectors();
    assert_eq!(rows.len(), 8);
    let mut server = server();
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let native: Vec<String> = row["native_lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line.as_str().unwrap().to_string())
            .collect();
        let contract = row["mock_contract"].as_str().unwrap();
        if contract == "service-silent-unit" {
            continue; // needs a PCI peer; covered by the cmqttd service tests
        }
        let command = row["command"].as_str().unwrap();
        let response = if command.starts_with("PP GET <session>") {
            for setup in [
                "PP LOCK dl //DIAGNOSE/254",
                "PP START ds dl",
                "PP LOAD ds //DIAGNOSE/254/p/16",
            ] {
                let reply = server.handle(&format!("[pp] {setup}"));
                assert!(reply.status < 400, "{setup}: {reply:?}");
            }
            server.handle(&format!("[{index}] PP GET ds ClockGenEnable"))
        } else {
            server.handle(&format!("[{index}] {command}"))
        };
        let observed = lines(&response);
        match contract {
            "exact" => assert_eq!(observed, native, "{name}"),
            "shape" => {
                let (prefix, _value) = native[0].split_once('=').unwrap();
                assert_eq!(observed.len(), 1, "{name}: {observed:?}");
                assert!(
                    observed[0].starts_with(&format!("{prefix}=")),
                    "{name}: {observed:?}"
                );
            }
            other => panic!("unknown contract {other}"),
        }
    }
    // Present units without an observed summary keep the native zero state.
    let voltage = server.handle("[v] GET //DIAGNOSE/254/p/16 NetVoltage");
    assert_eq!(
        voltage.final_text,
        "300 //DIAGNOSE/254/p/16: NetVoltage=0.5"
    );
}
