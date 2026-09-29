//! Differential replay of the native PROGRAMMER/DEPLOY_QUEUE lifecycle.
//!
//! `native_cgate_programmer_lifecycle.json` was captured from owned C-Gate
//! 3.4.0.2001 driving real PP_SET/PP_SAVE instructions against a simulated
//! KEY4 unit, including an injected no-reply mid-run, cancellation, STOP,
//! PAUSE, deletion while running, serial queueing, explicit RETRY and a
//! daemon restart. This test replays the same steps against the real cmqttd
//! binary. A scripted Rust PCI peer answers the physical unit (and withholds
//! STORE acknowledgements while the fault is armed); PP payloads are mapped
//! from the KEY4 `UnitName` to the fixture unit's one-byte `First`.
//!
//! PROGRAMMER and DEPLOY_QUEUE replies are compared exactly. PP-family reply
//! text is outside this differential. Unsolicited instruction echoes are
//! compared by tag and success/failure, and deploy-queue events (other than
//! the implementation-specific debug channel) as multisets. The deliberate
//! deviations are listed in `DEVIATIONS` and docs/cmqttd-cgate.md.

mod util;

use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::sync::Notify;
use util::*;

const UNIT: u8 = 5;

/// Native steps cmqttd deliberately does not reproduce, by (scenario, step).
const DEVIATIONS: &[(&str, &str, &str)] = &[(
    "started_pause_resume_deadlock",
    "PROGRAMMER TRIGGER W1 RESUME",
    "C-Gate 3.4.0.2001 deadlocks: its paused worker holds the monitor RESUME needs. cmqttd resumes.",
)];

fn value_for(text: &str) -> u8 {
    match text {
        "PQA1" => 17,
        "PQB2" => 34,
        "PQC3" => 51,
        "PQD4" => 68,
        "PQE5" => 85,
        "PQE6" => 102,
        other => panic!("unmapped native UnitName value {other}"),
    }
}

/// Map a native command onto the harness project and fixture unit.
fn translate(command: &str) -> String {
    let command = command
        .replace("<project>", "HARNESS")
        .replace("/254/p/4", &format!("/254/p/{UNIT}"));
    let words: Vec<&str> = command.split(' ').collect();
    match words.as_slice() {
        [.., "UnitName", value] if value.starts_with("PQ") => {
            let prefix = &command[..command.len() - "UnitName ".len() - value.len()];
            format!("{prefix}First {}", value_for(value))
        }
        // Native rejects an unknown parameter name (460). cmqttd deliberately
        // stages ad-hoc names in a session, so the replay faults the same
        // instruction through a missing session instead.
        [.., "PP_SET", "S", "NoSuchParam", _] => {
            command.replace("PP_SET S NoSuchParam", "PP_SET Missing First")
        }
        _ => command.replace("PP GET S UnitName", "PP GET S First"),
    }
}

/// Only PROGRAMMER/DEPLOY_QUEUE replies are part of the differential.
fn compared(command: &str) -> bool {
    command.starts_with("PROGRAMMER ")
        || command.starts_with("DEPLOY_QUEUE ")
        || command == "PP UNITS"
        || command == "PP LIST_LOCK"
}

fn normalize(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(index) = [
        "\"createdTime\":\"",
        "\"startedTime\":\"",
        "\"endedTime\":\"",
    ]
    .iter()
    .filter_map(|key| rest.find(key).map(|at| (at, key.len())))
    .min()
    {
        let (at, len) = index;
        out.push_str(&rest[..at + len]);
        rest = &rest[at + len..];
        let end = rest.find('"').unwrap();
        out.push_str("<timestamp>");
        rest = &rest[end..];
    }
    out.push_str(rest);
    out
}

/// A tagged C-Gate command connection whose unsolicited lines are kept.
struct Connection {
    writer: tokio::net::tcp::OwnedWriteHalf,
    lines: Arc<Mutex<Vec<String>>>,
    notify: Arc<Notify>,
    unsolicited: Vec<String>,
}

impl Connection {
    async fn open(address: &str) -> Connection {
        let stream = TcpStream::connect(address).await.unwrap();
        let (reader, writer) = stream.into_split();
        let mut reader = BufReader::new(reader);
        let mut greeting = String::new();
        reader.read_line(&mut greeting).await.unwrap();
        assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
        let lines = Arc::new(Mutex::new(Vec::new()));
        let notify = Arc::new(Notify::new());
        let (sink, wake) = (Arc::clone(&lines), Arc::clone(&notify));
        tokio::spawn(async move {
            loop {
                let mut line = String::new();
                if reader.read_line(&mut line).await.unwrap_or(0) == 0 {
                    return;
                }
                sink.lock()
                    .unwrap()
                    .push(line.trim_end_matches(['\r', '\n']).to_string());
                wake.notify_waiters();
            }
        });
        Connection {
            writer,
            lines,
            notify,
            unsolicited: Vec::new(),
        }
    }

    async fn send(&mut self, tag: &str, text: &str) -> Vec<String> {
        self.writer
            .write_all(format!("[{tag}] {text}\r\n").as_bytes())
            .await
            .unwrap();
        let prefix = format!("[{tag}] ");
        let mut reply = Vec::new();
        let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
        loop {
            let pending = std::mem::take(&mut *self.lines.lock().unwrap());
            let mut remainder = Vec::new();
            let mut done = false;
            for line in pending {
                if done {
                    remainder.push(line);
                } else if let Some(body) = line.strip_prefix(&prefix) {
                    reply.push(body.to_string());
                    done = body.as_bytes().get(3) == Some(&b' ');
                } else {
                    self.unsolicited.push(line);
                }
            }
            if !remainder.is_empty() {
                let mut lines = self.lines.lock().unwrap();
                remainder.append(&mut lines);
                *lines = remainder;
            }
            if done {
                return reply;
            }
            let notified = self.notify.notified();
            if !self.lines.lock().unwrap().is_empty() {
                continue;
            }
            assert!(
                tokio::time::timeout_at(deadline, notified).await.is_ok(),
                "no reply to {text}: {reply:?}"
            );
        }
    }

    fn drain(&mut self) -> Vec<String> {
        let mut lines = std::mem::take(&mut self.unsolicited);
        lines.append(&mut self.lines.lock().unwrap());
        lines
    }
}

/// Scripted physical unit on the fake PCI: IDENTIFY, RECALL and STORE for
/// direct requests to `UNIT`. Once armed, the unit acknowledges the given
/// number of STOREs and then stops replying to everything, so the next
/// PP_SAVE meets a no-reply mid-run.
///
/// Native C-Gate's capture withheld the STORE acknowledgement itself. cmqttd
/// deliberately retires its PCI generation after an unacknowledged
/// programming STORE (an uncertain write is never replayed and late
/// fragments cannot be attributed), which ends a plain `-t` daemon; that
/// boundary is covered by the transport tests. Silencing the unit before its
/// next IDENTIFY keeps the same partial outcome (first save durable, second
/// save failed, later work unexecuted) observable through RETRY.
struct Unit {
    memory: Arc<Mutex<HashMap<u8, u8>>>,
    fault: Arc<AtomicBool>,
    stores_before_fault: Arc<Mutex<Option<usize>>>,
    task: tokio::task::JoinHandle<()>,
}

impl Unit {
    fn spawn(system: &System) -> Unit {
        let memory = Arc::new(Mutex::new(HashMap::from([(0u8, 1u8), (9, 0xff)])));
        let fault = Arc::new(AtomicBool::new(false));
        let stores_before_fault = Arc::new(Mutex::new(None::<usize>));
        let pci = system.pci.clone();
        let (mem, armed, budget) = (
            Arc::clone(&memory),
            Arc::clone(&fault),
            Arc::clone(&stores_before_fault),
        );
        let task = tokio::spawn(async move {
            let mut seen = 0;
            loop {
                let frames = pci.frames();
                for frame in &frames[seen..] {
                    let Ok(bytes) = hex::decode(&frame.payload) else {
                        continue;
                    };
                    if bytes.len() < 5 || bytes[..3] != [0x46, UNIT, 0x00] {
                        continue;
                    }
                    let cal = &bytes[3..bytes.len() - 1];
                    // The unit goes silent from the IDENTIFY that opens the
                    // next save once its STORE budget is spent, leaving the
                    // previous save's readback answered.
                    if cal[0] == 0x21 && *budget.lock().unwrap() == Some(0) {
                        armed.store(true, Ordering::SeqCst);
                    }
                    if armed.load(Ordering::SeqCst) {
                        continue;
                    }
                    let reply: Option<Vec<u8>> = match cal[0] {
                        0x21 => {
                            let data: &[u8] = match cal[1] {
                                1 => b"TEST    ",
                                2 => b"1.2.3   ",
                                _ => continue,
                            };
                            let mut reply = vec![0x80 | (data.len() as u8 + 1), cal[1]];
                            reply.extend_from_slice(data);
                            Some(reply)
                        }
                        0x1a => {
                            let (parameter, count) = (cal[1], cal[2]);
                            let memory = mem.lock().unwrap();
                            let mut reply = vec![0x80 | (count + 1), parameter];
                            reply.extend((0..count).map(|offset| {
                                *memory.get(&parameter.wrapping_add(offset)).unwrap_or(&0)
                            }));
                            Some(reply)
                        }
                        opcode if opcode & 0xe0 == 0xa0 => {
                            let (parameter, tag) = (cal[1], cal[2]);
                            let mut memory = mem.lock().unwrap();
                            for (offset, byte) in cal[3..].iter().enumerate() {
                                memory.insert(parameter.wrapping_add(offset as u8), *byte);
                            }
                            let mut remaining = budget.lock().unwrap();
                            if let Some(left) = remaining.as_mut() {
                                *left = left.saturating_sub(1);
                            }
                            Some(vec![0x32, parameter, tag])
                        }
                        _ => None,
                    };
                    if let Some(reply) = reply {
                        let mut body = vec![0x86, UNIT, 0x10, 0x01, 0x00];
                        body.extend(reply);
                        pci.inject(&pci_wire(&body));
                    }
                }
                seen = frames.len();
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        });
        Unit {
            memory,
            fault,
            stores_before_fault,
            task,
        }
    }

    fn arm(&self, stores: usize) {
        *self.stores_before_fault.lock().unwrap() = Some(stores);
    }

    fn disarm(&self) {
        *self.stores_before_fault.lock().unwrap() = None;
        self.fault.store(false, Ordering::SeqCst);
    }

    fn first(&self) -> u8 {
        self.memory.lock().unwrap()[&0]
    }
}

fn final_outcomes(lines: &[String]) -> BTreeMap<(String, bool), usize> {
    let mut outcomes = BTreeMap::new();
    for line in lines {
        let Some((tag, body)) = line
            .strip_prefix('[')
            .and_then(|line| line.split_once("] "))
        else {
            panic!("untagged unsolicited line {line:?}");
        };
        if body.as_bytes().get(3) == Some(&b' ') {
            let ok = body.starts_with('1') || body.starts_with('2') || body.starts_with('3');
            *outcomes.entry((tag.to_string(), ok)).or_default() += 1;
        }
    }
    outcomes
}

fn events_without_debug(lines: &[String]) -> BTreeMap<String, usize> {
    let mut events = BTreeMap::new();
    for line in lines {
        let Some(json) = line.strip_prefix("#event ") else {
            continue;
        };
        let value: Value = serde_json::from_str(json).unwrap();
        if value["name"] != "deploy-queue.debug" {
            *events.entry(value.to_string()).or_default() += 1;
        }
    }
    events
}

fn native_events(scenario: &Value) -> BTreeMap<String, usize> {
    scenario["events"]
        .as_object()
        .unwrap()
        .iter()
        .filter_map(|(event, count)| {
            let value: Value = serde_json::from_str(event).unwrap();
            (value["name"] != "deploy-queue.debug")
                .then(|| (value.to_string(), count.as_u64().unwrap() as usize))
        })
        .collect()
}

/// The fixture's projection of a reply that races a native worker tick:
/// each programmer's state and whether it has an end time, plus the final
/// status code.
fn projection(reply: &[String]) -> Value {
    let states = reply
        .iter()
        .filter_map(|line| line.strip_prefix("130-"))
        .map(|json| {
            let row: Value = serde_json::from_str(json).unwrap();
            let ended = match row.get("endedTime") {
                None => Value::from("<absent>"),
                Some(Value::Null) => Value::Null,
                Some(_) => Value::from("<timestamp>"),
            };
            serde_json::json!({
                "progName": row.get("progName").cloned().unwrap_or(Value::Null),
                "progState": row["progState"],
                "endedTime": ended,
            })
        })
        .collect::<Vec<_>>();
    serde_json::json!({
        "volatile": true,
        "states": states,
        "final_code": reply.last().map(|line| line[..3].to_string()),
    })
}

fn options(state: &std::path::Path, unitspec: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-unitspec".into(),
            unitspec.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

fn write_catalogue(directory: &std::path::Path) {
    std::fs::create_dir_all(directory).unwrap();
    std::fs::write(
        directory.join("cbusunits.xml"),
        r#"<?xml version="1.0" encoding="utf-8"?>
<CBusUnits><Units><Unit><Description>System Fixture</Description><CatalogNumber>SYS-1</CatalogNumber><FirmwareRevisions><Revision><UnitType>TEST</UnitType><MinVersion>1.0</MinVersion><MaxVersion>1.9.99</MaxVersion><UnitSpecName>TEST.xml</UnitSpecName></Revision></FirmwareRevisions></Unit></Units><FileVersion>1.0</FileVersion><Author>Fixture</Author><Status>Released</Status><ApprovalDate>Today</ApprovalDate></CBusUnits>"#,
    )
    .unwrap();
    std::fs::write(
        directory.join("TEST.xml"),
        r#"<UnitSpecification><Parameters><Param><Name>First</Name><Type>int</Type><Address>$00</Address><DefaultValue>$01</DefaultValue></Param><Param><Name>Tenth</Name><Type>int</Type><Address>$09</Address><DefaultValue>$FF</DefaultValue></Param></Parameters></UnitSpecification>"#,
    )
    .unwrap();
}

async fn listener(system: &System) -> String {
    require(STARTUP, "C-Gate listener", || {
        system
            .daemon
            .stderr()
            .contains("C-Gate service listening on ")
    })
    .await;
    system
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap()
}

async fn subscribe(address: &str) -> Connection {
    let mut events = Connection::open(address).await;
    for channel in [
        "deploy-queue.updated-entries",
        "deploy-queue.debug",
        "deploy-queue.started",
        "deploy-queue.ended",
    ] {
        assert_eq!(
            events
                .send("sub", &format!("EVENT_CHANNEL SUB {channel}"))
                .await,
            ["200 OK: added"]
        );
    }
    events
}

#[tokio::test]
async fn native_programmer_lifecycle_replays_against_cmqttd() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../testdata/fixtures/native_cgate_programmer_lifecycle.json"
    ))
    .unwrap();
    assert_eq!(fixture["oracle"]["version"], "3.4.0.2001");
    let state = cbus_test_support::proc::temp_path("cgate-programmer-lifecycle.json");
    let unitspec = cbus_test_support::proc::temp_path("cgate-programmer-lifecycle-unitspec");
    write_catalogue(&unitspec);

    let mut system = Some(start_with(options(&state, &unitspec)).await);
    wait_started(system.as_ref().unwrap()).await;
    let mut address = listener(system.as_ref().unwrap()).await;
    let unit = Unit::spawn(system.as_ref().unwrap());
    let mut deviations_seen = Vec::new();
    // Native PP locks and sessions survive their command connection; cmqttd
    // releases them on disconnect (a documented PP ownership boundary). The
    // replay therefore keeps each labelled connection open across scenarios
    // where the native capture reconnected, until the daemon restart.
    let mut connections: BTreeMap<String, Connection> = BTreeMap::new();

    for scenario in fixture["scenarios"].as_array().unwrap() {
        let name = scenario["name"].as_str().unwrap();
        if name == "restart_volatility" {
            drop(system.take());
            let restarted = start_with(options(&state, &unitspec)).await;
            wait_started(&restarted).await;
            address = listener(&restarted).await;
            connections.clear();
            // The scripted unit belongs to the previous fake PCI; after the
            // restart only runtime-registry commands are replayed.
            system = Some(restarted);
        }
        let mut events = subscribe(&address).await;
        // Once cmqttd deliberately departs from a native step, later replies
        // in the same scenario describe a different (non-deadlocked) state.
        let mut diverged = false;
        for (index, step) in scenario["steps"].as_array().unwrap().iter().enumerate() {
            if let Some(label) = step["simulator_unit_name_bytes"].as_str() {
                let expected = match label {
                    "before" => 1,
                    "after_P1" => value_for("PQA1"),
                    "after_partial_P2" => value_for("PQB2"),
                    "after_retry_P2" | "after_restart" => value_for("PQC3"),
                    other => panic!("unmapped memory checkpoint {other}"),
                };
                assert_eq!(unit.first(), expected, "{name}: unit memory {label}");
                continue;
            }
            let native_command = step["command"].as_str().unwrap();
            if name == "setup" && !compared(native_command) {
                continue;
            }
            if native_command.starts_with("PROJECT ") && name == "restart_volatility" {
                continue;
            }
            if native_command == "DEPLOY_QUEUE ADD P2" {
                unit.arm(1);
            }
            if native_command == "DEPLOY_QUEUE RETRY P2" {
                unit.disarm();
            }
            let command = translate(native_command);
            let label = step["connection"].as_str().unwrap().to_string();
            if !connections.contains_key(&label) {
                connections.insert(label.clone(), Connection::open(&address).await);
            }
            let connection = connections.get_mut(&label).unwrap();
            let native: Vec<String> = match &step["reply"] {
                Value::Array(lines) => lines
                    .iter()
                    .map(|line| line.as_str().unwrap().to_string())
                    .collect(),
                _ => Vec::new(),
            };
            let volatile = step["reply"]["volatile"] == true;
            let matches = |reply: &[String]| {
                if volatile {
                    projection(reply) == step["reply"]
                } else {
                    reply.iter().map(|line| normalize(line)).collect::<Vec<_>>() == native
                }
            };
            if let Some(until) = step["until"].as_str() {
                let deadline = tokio::time::Instant::now() + Duration::from_secs(60);
                let mut poll = 0;
                loop {
                    let reply = connection.send(&format!("w{poll}"), &command).await;
                    poll += 1;
                    let matched = matches(&reply);
                    if matched {
                        break;
                    }
                    assert!(
                        tokio::time::Instant::now() < deadline,
                        "{name}: {until}: native {native:?}, cmqttd {reply:?}, unsolicited {:?}",
                        connection.unsolicited
                    );
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
                continue;
            }
            if step.get("no_reply_within_seconds").is_some() {
                let deviation = DEVIATIONS
                    .iter()
                    .find(|(scenario, command, _)| *scenario == name && *command == native_command);
                if deviation.is_some() || diverged {
                    let reply = connection
                        .send(&format!("{}{index}", label.to_lowercase()), &command)
                        .await;
                    assert_eq!(reply, ["200 OK: triggered"], "{deviation:?}");
                    if deviation.is_some() {
                        diverged = true;
                        deviations_seen.push(native_command.to_string());
                    }
                    continue;
                }
                panic!(
                    "{name}: native gave no reply to {native_command} without a declared deviation"
                );
            }
            let reply = connection
                .send(&format!("{}{index}", label.to_lowercase()), &command)
                .await;
            if compared(native_command) && !diverged {
                assert!(
                    matches(&reply),
                    "{name} step {index}: {command}: native {}, cmqttd {reply:?}",
                    step["reply"]
                );
            }
            if native_command.starts_with("PROGRAMMER TRIGGER I1 RESUME") {
                // Mirror the native capture's fixed wait before STATUS.
                tokio::time::sleep(Duration::from_secs(4)).await;
            }
        }
        // Let asynchronous echoes and events for this scenario arrive.
        tokio::time::sleep(Duration::from_millis(1_500)).await;
        for (label, connection) in &mut connections {
            let lines = connection.drain();
            let native = scenario["unsolicited"][label.as_str()]
                .as_array()
                .map(|lines| {
                    lines
                        .iter()
                        .map(|line| line.as_str().unwrap().to_string())
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            assert_eq!(
                final_outcomes(&lines),
                final_outcomes(&native),
                "{name}: instruction replies echoed to connection {label}: {lines:?}"
            );
        }
        let lines = events.drain();
        if name != "setup" {
            assert_eq!(
                events_without_debug(&lines),
                native_events(scenario),
                "{name}: deploy-queue events {lines:?}"
            );
        }
        if name == "deploy_fault_partial_and_retry" {
            let debug = lines
                .iter()
                .filter(|line| line.contains("\"deploy-queue.debug\""))
                .collect::<Vec<_>>();
            assert_eq!(debug.len(), 1, "{debug:?}");
            assert!(debug[0].contains("\"instructionId\":4"), "{debug:?}");
            assert!(debug[0].contains("\"automaticReplay\":false"), "{debug:?}");
        }
    }
    assert_eq!(deviations_seen, ["PROGRAMMER TRIGGER W1 RESUME"]);

    let mut system = system.take().unwrap();
    assert!(system.daemon.is_running());
    unit.task.abort();
    drop(system);
    std::fs::remove_file(state).unwrap();
    std::fs::remove_dir_all(unitspec).unwrap();
}
