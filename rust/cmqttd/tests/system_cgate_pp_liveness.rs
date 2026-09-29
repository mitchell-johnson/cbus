//! Real cmqttd process: a long physical `PP SAVE` shares the PCI with live
//! MQTT and C-Gate traffic. MQTT commands keep a bounded wire latency and
//! their order while programming exchanges are outstanding, MQTT state is
//! only published from PCI-confirmed commands or bus observations, and
//! C-Gate load-change events keep bus order. A PCI loss mid-save reports a
//! failure without replaying any write, and a broker outage mid-save leaves
//! programming and C-Gate events untouched until MQTT reconnects.
//!
//! The PCI peer is scripted: a small emulated unit at address 5 answers
//! IDENTIFY, RECALL and STORE from its own memory, so the save is a real
//! multi-chunk transaction (2 identities, 16 pre-read blocks, 16 STOREs and
//! 16 readbacks) rather than a hand-played transcript.

mod util;

use cbus_protocol::common::add_cbus_checksum;
use cbus_test_support::broker::MiniBroker;
use cbus_test_support::pci::FakePci;
use cbus_test_support::proc::{temp_path, Daemon};
use cbus_transport::flow::FlowConfig;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use util::*;

/// Unit address of the emulated programmable unit.
const UNIT: u8 = 5;
/// Direct parameter blocks in the synthetic unit specification. Each block
/// is one twelve-byte STORE chunk (the native `cg` limit) plus its readback.
const BLOCKS: usize = 16;
const BLOCK_BYTES: usize = 12;
const FIRST_PARAMETER: u8 = 0x20;
/// Unit that originates bus observations injected during the save.
const OBSERVER: u8 = 7;
const BRIDGE_STATE: &str = "homeassistant/binary_sensor/cbus_cmqttd/state";
const BRIDGE_CONFIG: &str = "homeassistant/binary_sensor/cbus_cmqttd/config";
const COMMAND_RESULT: &str = "cmqttd/cbus/command_result";
const COMMAND_WILDCARD: &str = "homeassistant/light/+/set";

/// Upper bound on the time from an MQTT /set command becoming eligible to
/// send (published, and its predecessor in the ordered MQTT lane already on
/// the wire) to its frame reaching the PCI, while a PP save is running.
///
/// Derived from the flow controller in `cbus-transport/src/flow.rs`:
/// lighting commands and programming CALs share the `Command` class, which
/// is FIFO and always ahead of `Background` status traffic. The programming
/// lane serialises exchanges, so at most one programming frame is queued
/// ahead of a command, and that frame is `Silent` (slot held `silent_hold`).
/// The command may then wait for one window slot held by an in-flight frame
/// until its response or its timeout (at most `rto_max`), a `!` pause
/// (`error_pause`) and the inter-frame floor (`min_gap`, before each of the
/// two frames). One second of scheduling slack covers a loaded test host.
fn command_latency_bound() -> Duration {
    let flow = FlowConfig::default();
    flow.rto_max + flow.silent_hold + flow.error_pause + flow.min_gap * 2 + Duration::from_secs(1)
}

fn unitspec_dir(tag: &str) -> PathBuf {
    let specs = temp_path(tag);
    std::fs::create_dir_all(&specs).unwrap();
    let params = (0..BLOCKS)
        .map(|block| {
            format!(
                "<Param><Name>Block{block:02}</Name><Type>int</Type><Address>${:02X}</Address>\
                 <ArraySize>{BLOCK_BYTES}</ArraySize><ProgramMethod>direct</ProgramMethod>\
                 <Protection>none</Protection><Tag>Core</Tag></Param>",
                usize::from(FIRST_PARAMETER) + block * BLOCK_BYTES
            )
        })
        .collect::<String>();
    std::fs::write(
        specs.join("TESTUNIT.xml"),
        format!("<UnitSpecification><Parameters>{params}</Parameters></UnitSpecification>"),
    )
    .unwrap();
    specs
}

/// The staged value of one block: distinct, nonzero bytes, so every block
/// differs from the unit's zeroed memory and needs its own STORE.
fn block_value(block: usize) -> Vec<u8> {
    (0..BLOCK_BYTES)
        .map(|byte| (block * BLOCK_BYTES + byte + 1) as u8)
        .collect()
}

fn store_payload_prefix(block: usize) -> String {
    let parameter = usize::from(FIRST_PARAMETER) + block * BLOCK_BYTES;
    format!("460500{:02X}{parameter:02X}00", 0xA0 | (BLOCK_BYTES + 2))
}

fn is_store(payload: &str) -> bool {
    (0..BLOCKS).any(|block| payload.starts_with(&store_payload_prefix(block)))
}

/// A confirmed lighting frame for app 56, as the fake PCI records it.
fn lighting_payload(group: u8, on: bool) -> String {
    let command = if on { 0x79 } else { 0x01 };
    hex::encode_upper(add_cbus_checksum(&[0x05, 0x38, 0x00, command, group]))
}

fn is_lighting_command(payload: &str) -> bool {
    payload.starts_with("053800")
}

/// A lighting observation from [`OBSERVER`], as the bus would deliver it.
fn observation(group: u8, on: bool) -> Vec<u8> {
    pci_wire(&[
        0x05,
        OBSERVER,
        0x38,
        0x00,
        if on { 0x79 } else { 0x01 },
        group,
    ])
}

fn reply(cal: &[u8]) -> Vec<u8> {
    let mut body = vec![0x86, UNIT, 0x10, 0x01, 0x00];
    body.extend_from_slice(cal);
    pci_wire(&body)
}

/// Scripted programmable unit. It answers direct programming requests to
/// [`UNIT`] from its own memory, and can withhold the ACK of one STORE so a
/// test controls what happens while that exchange is outstanding.
struct EmulatedUnit {
    memory: Vec<u8>,
    /// 1-based STORE number whose ACK is withheld.
    hold_store: Option<usize>,
    /// The withheld ACK and the write it acknowledges.
    held: Option<(Vec<u8>, u8, Vec<u8>)>,
    release: bool,
    stores: usize,
    stop: bool,
}

impl EmulatedUnit {
    fn new(hold_store: Option<usize>) -> Arc<Mutex<EmulatedUnit>> {
        Arc::new(Mutex::new(EmulatedUnit {
            memory: vec![0; 256],
            hold_store,
            held: None,
            release: false,
            stores: 0,
            stop: false,
        }))
    }

    fn respond(&mut self, payload: &str) -> Option<Vec<u8>> {
        let cal = hex::decode(payload.strip_prefix(&format!("46{UNIT:02X}00")[..])?).ok()?;
        match *cal.first()? {
            0x21 => {
                let attribute = *cal.get(1)?;
                let text: &[u8] = match attribute {
                    1 => b"TESTUNIT",
                    2 => b"1.2.03",
                    _ => return None,
                };
                let mut answer = vec![0x80 | (text.len() as u8 + 1), attribute];
                answer.extend_from_slice(text);
                Some(reply(&answer))
            }
            0x1A => {
                let (parameter, count) = (*cal.get(1)?, *cal.get(2)?);
                let start = usize::from(parameter);
                let mut answer = vec![0x80 | (count + 1), parameter];
                answer.extend_from_slice(&self.memory[start..start + usize::from(count)]);
                Some(reply(&answer))
            }
            header if header & 0xE0 == 0xA0 => {
                let length = usize::from(header & 0x1F);
                let (parameter, tag) = (*cal.get(1)?, *cal.get(2)?);
                let data = cal.get(3..1 + length)?.to_vec();
                self.stores += 1;
                let ack = reply(&[0x32, parameter, tag]);
                if self.hold_store == Some(self.stores) {
                    self.held = Some((ack, parameter, data));
                    return None;
                }
                let start = usize::from(parameter);
                self.memory[start..start + data.len()].copy_from_slice(&data);
                Some(ack)
            }
            _ => None,
        }
    }
}

/// Serve [`EmulatedUnit`] from PCI frames recorded after `cursor` until it is
/// stopped. Status requests and lighting frames are left unanswered.
async fn run_unit(pci: &FakePci, unit: &Mutex<EmulatedUnit>, mut cursor: usize) {
    loop {
        let frames = pci.frames();
        let mut replies = Vec::new();
        {
            let mut unit = unit.lock().unwrap();
            if unit.stop {
                return;
            }
            for frame in &frames[cursor..] {
                replies.extend(unit.respond(&frame.payload));
            }
            if unit.release {
                if let Some((ack, parameter, data)) = unit.held.take() {
                    let start = usize::from(parameter);
                    unit.memory[start..start + data.len()].copy_from_slice(&data);
                    replies.push(ack);
                }
            }
        }
        cursor = frames.len();
        for wire in replies {
            pci.inject(&wire);
        }
        tokio::time::sleep(Duration::from_millis(2)).await;
    }
}

type Reader = BufReader<tokio::net::tcp::OwnedReadHalf>;
type Writer = tokio::net::tcp::OwnedWriteHalf;

async fn cgate_connect(sys: &System) -> (Reader, Writer) {
    require(STARTUP, "C-Gate listener", || {
        sys.daemon.stderr().contains("C-Gate service listening on ")
    })
    .await;
    let address = sys
        .daemon
        .stderr()
        .lines()
        .find_map(|line| line.split_once("C-Gate service listening on "))
        .map(|(_, address)| address.trim().to_string())
        .unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (reader, writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "), "{greeting:?}");
    (reader, writer)
}

async fn command(reader: &mut Reader, writer: &mut Writer, text: &str) -> String {
    writer
        .write_all(format!("[5] {text}\r\n").as_bytes())
        .await
        .unwrap();
    let mut result = String::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0, "{text}");
        result.push_str(&line);
        if line.starts_with("[5]") && line.as_bytes().get(7) == Some(&b' ') {
            return result;
        }
    }
}

/// Subscribe a second C-Gate connection to load-change events and collect
/// every row it receives, in arrival order.
async fn collect_events(sys: &System) -> Arc<Mutex<Vec<String>>> {
    let (mut reader, mut writer) = cgate_connect(sys).await;
    assert!(command(&mut reader, &mut writer, "EVENT e7s1c0")
        .await
        .contains("200"));
    let rows = Arc::new(Mutex::new(Vec::new()));
    tokio::spawn({
        let rows = rows.clone();
        async move {
            let _keep = writer;
            loop {
                let mut line = String::new();
                if reader.read_line(&mut line).await.unwrap_or(0) == 0 {
                    break;
                }
                rows.lock().unwrap().push(line.trim_end().to_string());
            }
        }
    });
    rows
}

fn observation_rows(rows: &Mutex<Vec<String>>) -> Vec<String> {
    rows.lock()
        .unwrap()
        .iter()
        .filter(|row| {
            row.starts_with("#s# lighting ") && row.contains(&format!("#sourceunit={OBSERVER} "))
        })
        .cloned()
        .collect()
}

fn expected_observation_row(group: u8, on: bool) -> String {
    format!(
        "#s# lighting {} //HARNESS/254/56/{group} ",
        if on { "on" } else { "off" }
    )
}

/// Open a programming session and stage every block for a physical save.
async fn stage_session(reader: &mut Reader, writer: &mut Writer) {
    for text in [
        "PROJECT USE HARNESS",
        "PP LOCK L //HARNESS/254",
        "PP START S L",
        "PP NEW S TESTUNIT 1.2.03",
    ] {
        let reply = command(reader, writer, text).await;
        assert!(reply.contains("200 OK"), "{text}: {reply:?}");
    }
    for block in 0..BLOCKS {
        let values = block_value(block)
            .iter()
            .map(|byte| format!("0x{byte:02X}"))
            .collect::<Vec<_>>()
            .join(" ");
        let text = format!("PP SET S Block{block:02} {values}");
        let reply = command(reader, writer, &text).await;
        assert!(reply.contains("200 OK"), "{text}: {reply:?}");
    }
}

fn cgate_args(state: &Path, specs: &Path) -> Vec<String> {
    vec![
        "--cgate-bind".into(),
        "127.0.0.1:0".into(),
        "--cgate-state".into(),
        state.to_string_lossy().into_owned(),
        "--cgate-unitspec".into(),
        specs.to_string_lossy().into_owned(),
    ]
}

/// cmqttd over a reconnecting ESP32-WiFi endpoint (plain `-t` exits on PCI
/// loss by design), with the embedded C-Gate service enabled.
async fn start_reconnecting(state: &Path, specs: &Path) -> System {
    let broker = MiniBroker::start().await;
    let pci = FakePci::start(false).await;
    let broker_port = broker.port().to_string();
    let wifi = format!("127.0.0.1:{}", pci.port());
    let project = project_file();
    let mut args: Vec<String> = [
        "-b",
        "127.0.0.1",
        "-p",
        &broker_port,
        "--broker-disable-tls",
        "--esp32-wifi",
        &wifi,
        "--esp32-reconnect-interval",
        "1",
        "-P",
        &project,
        "-T",
        "0",
        "-v",
        "DEBUG",
    ]
    .map(String::from)
    .to_vec();
    args.extend(cgate_args(state, specs));
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    let daemon = Daemon::spawn(BIN, &arg_refs);
    System {
        broker,
        pci,
        daemon,
    }
}

fn command_results(sys: &System) -> Vec<serde_json::Value> {
    sys.broker
        .find_publishes(COMMAND_RESULT)
        .iter()
        .map(|publish| parse_json(&publish.payload))
        .collect()
}

/// A long physical save with concurrent MQTT commands and bus observations:
/// every command reaches the wire within [`command_latency_bound`] and in
/// publish order while a programming exchange is outstanding; requested
/// state is echoed only after PCI confirmation; bus observations reach MQTT
/// and the C-Gate event stream in bus order; and the save completes with
/// each chunk stored exactly once.
#[tokio::test]
async fn long_pp_save_keeps_mqtt_commands_bounded_ordered_and_unfabricated() {
    let state = temp_path("pp-liveness-save.json");
    let specs = unitspec_dir("pp-liveness-save-unitspec");
    let sys = start_with(Options {
        extra: cgate_args(&state, &specs),
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let rows = collect_events(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_session(&mut reader, &mut writer).await;

    let unit = EmulatedUnit::new(Some(4));
    let cursor = sys.pci.frames().len();
    // (group, on) for each MQTT command, in publish order. The first eight
    // are published while STORE 4 is unacknowledged; the rest after release.
    let commands: Vec<(u8, bool)> = (0..12)
        .map(|index| (if index % 2 == 0 { 1 } else { 10 }, index % 4 < 2))
        .collect();
    let observations: Vec<(u8, bool)> = (0..6).map(|index| (20 + index, index % 2 == 0)).collect();
    let mut published = Vec::new();

    let save = async {
        let reply = command(
            &mut reader,
            &mut writer,
            &format!("PP SAVE S //HARNESS/254/p/{UNIT} Core"),
        )
        .await;
        unit.lock().unwrap().stop = true;
        reply
    };
    let driver = async {
        require(COMMAND_DRAIN, "STORE 4 outstanding", || {
            unit.lock().unwrap().held.is_some()
        })
        .await;
        for (index, &(group, on)) in commands.iter().enumerate().take(8) {
            published.push(Instant::now());
            sys.broker.inject_qos1(
                &format!("homeassistant/light/cbus_{group}/set"),
                if on {
                    br#"{"state":"ON"}"#
                } else {
                    br#"{"state":"OFF"}"#
                },
            );
            if index % 2 == 1 {
                let (group, on) = observations[index / 2];
                sys.pci.inject(&observation(group, on));
            }
            tokio::time::sleep(Duration::from_millis(60)).await;
        }
        for &(group, on) in &observations[4..] {
            sys.pci.inject(&observation(group, on));
        }
        require(COMMAND_DRAIN, "commands on the wire during STORE 4", || {
            sys.pci
                .payloads()
                .iter()
                .filter(|payload| is_lighting_command(payload))
                .count()
                >= 8
        })
        .await;
        require(STARTUP, "C-Gate observation events during STORE 4", || {
            observation_rows(&rows).len() >= observations.len()
        })
        .await;
        {
            let mut unit = unit.lock().unwrap();
            assert!(unit.held.is_some(), "STORE 4 must still be outstanding");
            assert_eq!(unit.stores, 4, "no later STORE may pass the held one");
            unit.release = true;
        }
        for &(group, on) in &commands[8..] {
            published.push(Instant::now());
            sys.broker.inject_qos1(
                &format!("homeassistant/light/cbus_{group}/set"),
                if on {
                    br#"{"state":"ON"}"#
                } else {
                    br#"{"state":"OFF"}"#
                },
            );
            tokio::time::sleep(Duration::from_millis(60)).await;
        }
    };
    let (saved, (), ()) = tokio::join!(save, run_unit(&sys.pci, &unit, cursor), driver);
    assert!(saved.contains("[5] 200 OK"), "{saved:?}");

    // Programming: every chunk stored exactly once and verified in memory.
    let expected_memory = (0..BLOCKS).flat_map(block_value).collect::<Vec<_>>();
    let start = usize::from(FIRST_PARAMETER);
    assert_eq!(
        unit.lock().unwrap().memory[start..start + BLOCKS * BLOCK_BYTES],
        expected_memory[..]
    );
    let payloads = sys.pci.payloads();
    for block in 0..BLOCKS {
        let prefix = store_payload_prefix(block);
        assert_eq!(
            payloads.iter().filter(|p| p.starts_with(&prefix)).count(),
            1,
            "block {block} STORE must be exact-once"
        );
    }

    // MQTT commands: each exactly once, in publish order, interleaved with
    // the save, within the flow-derived latency bound.
    require(COMMAND_DRAIN, "all MQTT commands on the wire", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|payload| is_lighting_command(payload))
            .count()
            >= commands.len()
    })
    .await;
    let frames = sys.pci.frames();
    let lighting = frames
        .iter()
        .enumerate()
        .filter(|(_, frame)| is_lighting_command(&frame.payload))
        .collect::<Vec<_>>();
    assert_eq!(
        lighting
            .iter()
            .map(|(_, frame)| frame.payload.clone())
            .collect::<Vec<_>>(),
        commands
            .iter()
            .map(|&(group, on)| lighting_payload(group, on))
            .collect::<Vec<_>>(),
        "MQTT commands must reach the PCI once each, in publish order"
    );
    assert!(lighting.iter().all(|(_, frame)| frame.conf.is_some()));
    let bound = command_latency_bound();
    let mut previous_wire: Option<Instant> = None;
    for (index, (_, frame)) in lighting.iter().enumerate() {
        let eligible = previous_wire.map_or(published[index], |wire| wire.max(published[index]));
        let latency = frame.ts.saturating_duration_since(eligible);
        assert!(
            latency <= bound,
            "command {index} took {latency:?} to reach the PCI (bound {bound:?})"
        );
        previous_wire = Some(frame.ts);
    }
    let store_positions = frames
        .iter()
        .enumerate()
        .filter(|(_, frame)| is_store(&frame.payload))
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    let (first_store, last_store) = (store_positions[0], *store_positions.last().unwrap());
    assert!(
        lighting
            .iter()
            .filter(|(index, _)| *index > first_store && *index < last_store)
            .count()
            >= 8,
        "MQTT commands must interleave with the programming STOREs"
    );

    // MQTT state: every requested-state echo follows its PCI confirmation
    // and matches its command; nothing else is published for those groups
    // (no status report answered them), and every command is confirmed.
    require(COMMAND_DRAIN, "command results", || {
        command_results(&sys).len() >= commands.len()
    })
    .await;
    let results = command_results(&sys);
    assert_eq!(
        results
            .iter()
            .map(|result| (
                result["group"].as_u64().unwrap() as u8,
                result["requested_state"] == "ON",
                result["delivery"].as_str().unwrap().to_string()
            ))
            .collect::<Vec<_>>(),
        commands
            .iter()
            .map(|&(group, on)| (group, on, "confirmed".to_string()))
            .collect::<Vec<_>>()
    );
    for group in [1u8, 10] {
        let wires = lighting
            .iter()
            .filter(|(_, frame)| {
                frame.payload == lighting_payload(group, true)
                    || frame.payload == lighting_payload(group, false)
            })
            .map(|(_, frame)| frame.ts)
            .collect::<Vec<_>>();
        let echoes = sys
            .broker
            .find_publishes(&format!("homeassistant/light/cbus_{group}/state"));
        let requested = commands
            .iter()
            .filter(|(commanded, _)| *commanded == group)
            .map(|&(_, on)| if on { "ON" } else { "OFF" })
            .collect::<Vec<_>>();
        assert_eq!(
            echoes
                .iter()
                .map(|publish| {
                    let payload = parse_json(&publish.payload);
                    assert!(payload["cbus_source_addr"].is_null(), "{payload}");
                    payload["state"].as_str().unwrap().to_string()
                })
                .collect::<Vec<_>>(),
            requested,
            "group {group} state must be exactly the confirmed command echoes"
        );
        for (echo, wire) in echoes.iter().zip(&wires) {
            assert!(echo.ts >= *wire, "group {group} echo preceded its command");
        }
    }

    // Bus observations during the save: MQTT carries each with its source,
    // and the C-Gate event stream carries them in bus order.
    for &(group, on) in &observations {
        let topic = format!("homeassistant/light/cbus_{group}/state");
        require(STARTUP, "observed state in MQTT", || {
            sys.broker.retained(&topic).is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["state"] == if on { "ON" } else { "OFF" }
                    && payload["cbus_source_addr"] == OBSERVER
            })
        })
        .await;
    }
    let events = observation_rows(&rows);
    assert_eq!(events.len(), observations.len(), "{events:?}");
    for (row, &(group, on)) in events.iter().zip(&observations) {
        assert!(
            row.starts_with(&expected_observation_row(group, on)),
            "{events:?}"
        );
    }
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_dir_all(specs).unwrap();
}

/// A PCI loss while a STORE is unacknowledged fails the save with its
/// confirmed-write count and never replays the uncertain write. The bridge
/// follows the existing reconnect contract (OFF, fresh connection and init,
/// ON, forced status sweep), MQTT commands work on the new connection, a
/// late ACK for the lost STORE completes nothing, and only an explicit new
/// save writes the remaining chunks, each once.
#[tokio::test]
async fn pci_loss_mid_save_fails_without_replay_and_mqtt_recovers() {
    let state = temp_path("pp-liveness-pci.json");
    let specs = unitspec_dir("pp-liveness-pci-unitspec");
    let sys = start_reconnecting(&state, &specs).await;
    wait_started(&sys).await;
    require(STARTUP, "initial connected state", || {
        sys.broker.retained(BRIDGE_STATE).as_deref() == Some(b"ON")
    })
    .await;
    let rows = collect_events(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_session(&mut reader, &mut writer).await;

    let unit = EmulatedUnit::new(Some(3));
    let cursor = sys.pci.frames().len();
    let mut kicked_at = 0;
    let save = async {
        let reply = command(
            &mut reader,
            &mut writer,
            &format!("PP SAVE S //HARNESS/254/p/{UNIT} Core"),
        )
        .await;
        unit.lock().unwrap().stop = true;
        reply
    };
    let driver = async {
        require(COMMAND_DRAIN, "STORE 3 outstanding", || {
            unit.lock().unwrap().held.is_some()
        })
        .await;
        // Still live before the fault: an MQTT command and an observation.
        sys.broker
            .inject_qos1("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
        sys.pci.inject(&observation(20, true));
        require(COMMAND_DRAIN, "MQTT command during STORE 3", || {
            sys.pci.count_payload(&lighting_payload(1, true)) == 1
        })
        .await;
        require(STARTUP, "C-Gate event during STORE 3", || {
            observation_rows(&rows).len() == 1
        })
        .await;
        kicked_at = sys.pci.frames().len();
        sys.pci.kick();
    };
    let (failed, (), ()) = tokio::join!(save, run_unit(&sys.pci, &unit, cursor), driver);
    assert!(
        failed.contains("[5] 502 Physical PP save failed after 2 confirmed write(s)"),
        "{failed:?}"
    );

    // Existing reconnect semantics: OFF, a second connection with a full
    // init, ON again, and a forced configured status sweep.
    require(Duration::from_secs(15), "PCI reconnection", || {
        sys.pci.connections() >= 2
    })
    .await;
    require(
        Duration::from_secs(15),
        "disconnect and reconnect state",
        || {
            let states = sys
                .broker
                .find_publishes(BRIDGE_STATE)
                .into_iter()
                .map(|publish| publish.payload)
                .collect::<Vec<_>>();
            states
                .windows(2)
                .any(|window| window == [b"OFF".to_vec(), b"ON".to_vec()])
        },
    )
    .await;
    require(
        Duration::from_secs(15),
        "forced post-reconnect sweep",
        || {
            // The pre-fault sweep may not have finished behind programming
            // traffic, so count only frames written after the fault.
            let frames = sys.pci.frames();
            configured_sweep().iter().all(|payload| {
                frames[kicked_at..]
                    .iter()
                    .any(|frame| frame.payload == *payload)
            })
        },
    )
    .await;

    // A late ACK for the lost STORE arrives on the new connection. It must
    // not complete the failed save or clear its staged changes: the explicit
    // retry below still finds every unwritten block dirty and stores it.
    let (stale_ack, _, _) = unit.lock().unwrap().held.clone().unwrap();
    sys.pci.inject(&stale_ack);

    // MQTT commands and observations work again on the new connection.
    let before = command_results(&sys).len();
    sys.broker
        .inject_qos1("homeassistant/light/cbus_10/set", br#"{"state":"OFF"}"#);
    require(COMMAND_DRAIN, "MQTT command after reconnect", || {
        command_results(&sys)
            .get(before)
            .is_some_and(|result| result["group"] == 10 && result["delivery"] == "confirmed")
    })
    .await;
    sys.pci.inject(&observation(21, false));
    require(STARTUP, "C-Gate event after reconnect", || {
        observation_rows(&rows).len() == 2
    })
    .await;
    let events = observation_rows(&rows);
    assert!(events[0].starts_with(&expected_observation_row(20, true)));
    assert!(events[1].starts_with(&expected_observation_row(21, false)));

    // Nothing was replayed: no STORE was written since the fault.
    assert!(
        !sys.pci.frames()[kicked_at..]
            .iter()
            .any(|frame| is_store(&frame.payload)),
        "an uncertain programming write was replayed"
    );

    // Only an explicit new save writes again. The unit applied STOREs 1-2
    // but not the lost STORE 3, so blocks 2..16 are written once each.
    let retry_from = sys.pci.frames().len();
    let retry_unit = EmulatedUnit::new(None);
    retry_unit.lock().unwrap().memory = unit.lock().unwrap().memory.clone();
    let retry = async {
        let reply = command(
            &mut reader,
            &mut writer,
            &format!("PP SAVE S //HARNESS/254/p/{UNIT} Core"),
        )
        .await;
        retry_unit.lock().unwrap().stop = true;
        reply
    };
    let (saved, ()) = tokio::join!(retry, run_unit(&sys.pci, &retry_unit, retry_from));
    assert!(saved.contains("[5] 200 OK"), "{saved:?}");
    let retried = sys.pci.frames();
    for block in 0..BLOCKS {
        let prefix = store_payload_prefix(block);
        let expected = usize::from(block >= 2);
        assert_eq!(
            retried[retry_from..]
                .iter()
                .filter(|frame| frame.payload.starts_with(&prefix))
                .count(),
            expected,
            "block {block} STORE count in the explicit retry"
        );
    }
    let expected_memory = (0..BLOCKS).flat_map(block_value).collect::<Vec<_>>();
    let start = usize::from(FIRST_PARAMETER);
    assert_eq!(
        retry_unit.lock().unwrap().memory[start..start + BLOCKS * BLOCK_BYTES],
        expected_memory[..]
    );

    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_dir_all(specs).unwrap();
}

/// A broker outage in the middle of a save does not disturb programming or
/// the C-Gate event stream: the save completes and every bus observation
/// reaches C-Gate in order while MQTT is down. When the broker returns,
/// cmqttd reconnects, resubscribes, republishes discovery and bridge state
/// as on first connect, delivers the observations made during the outage,
/// and accepts MQTT commands again.
#[tokio::test]
async fn broker_outage_mid_save_keeps_programming_and_cgate_events() {
    let state = temp_path("pp-liveness-broker.json");
    let specs = unitspec_dir("pp-liveness-broker-unitspec");
    let sys = start_with(Options {
        extra: cgate_args(&state, &specs),
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(STARTUP, "initial connected state", || {
        sys.broker.retained(BRIDGE_STATE).as_deref() == Some(b"ON")
    })
    .await;
    let rows = collect_events(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_session(&mut reader, &mut writer).await;
    let light_config = "homeassistant/light/cbus_1/config";
    let first_connect = (
        sys.broker.connections(),
        sys.broker.find_publishes(BRIDGE_CONFIG).len(),
        sys.broker.find_publishes(light_config).len(),
        sys.broker.find_publishes(BRIDGE_STATE).len(),
    );

    // More observations than the MQTT client's request queue holds, so a
    // bridge that stalled bus events behind MQTT would be caught.
    let observations: Vec<(u8, bool)> = (0..80)
        .map(|index| (100 + index as u8, index % 3 != 0))
        .collect();
    let unit = EmulatedUnit::new(Some(3));
    let cursor = sys.pci.frames().len();
    let save = async {
        let reply = command(
            &mut reader,
            &mut writer,
            &format!("PP SAVE S //HARNESS/254/p/{UNIT} Core"),
        )
        .await;
        unit.lock().unwrap().stop = true;
        reply
    };
    let driver = async {
        require(COMMAND_DRAIN, "STORE 3 outstanding", || {
            unit.lock().unwrap().held.is_some()
        })
        .await;
        sys.broker.set_refusing(true);
        sys.broker.disconnect_clients();
        require(STARTUP, "cmqttd retries the unavailable broker", || {
            sys.broker.refused_connections() >= 1
        })
        .await;
        for &(group, on) in &observations {
            sys.pci.inject(&observation(group, on));
        }
        require(STARTUP, "C-Gate events during the broker outage", || {
            observation_rows(&rows).len() >= observations.len()
        })
        .await;
        unit.lock().unwrap().release = true;
    };
    let (saved, (), ()) = tokio::join!(save, run_unit(&sys.pci, &unit, cursor), driver);
    assert!(saved.contains("[5] 200 OK"), "{saved:?}");
    assert_eq!(
        sys.broker.connections(),
        first_connect.0,
        "the save completed while the broker was still down"
    );
    let events = observation_rows(&rows);
    assert_eq!(events.len(), observations.len());
    for (row, &(group, on)) in events.iter().zip(&observations) {
        assert!(
            row.starts_with(&expected_observation_row(group, on)),
            "{row:?}"
        );
    }
    let payloads = sys.pci.payloads();
    for block in 0..BLOCKS {
        let prefix = store_payload_prefix(block);
        assert_eq!(
            payloads.iter().filter(|p| p.starts_with(&prefix)).count(),
            1,
            "block {block} STORE must be exact-once"
        );
    }

    // Broker restart: cmqttd reconnects and repeats its connect sequence.
    sys.broker.set_refusing(false);
    require(Duration::from_secs(15), "MQTT reconnection", || {
        sys.broker.connections() > first_connect.0
    })
    .await;
    require(STARTUP, "resubscribed command wildcard", || {
        sys.broker
            .subscriptions()
            .iter()
            .filter(|filter| *filter == COMMAND_WILDCARD)
            .count()
            >= 2
    })
    .await;
    require(STARTUP, "republished discovery and bridge state", || {
        sys.broker.find_publishes(BRIDGE_CONFIG).len() > first_connect.1
            && sys.broker.find_publishes(light_config).len() > first_connect.2
            && sys
                .broker
                .find_publishes(BRIDGE_STATE)
                .iter()
                .skip(first_connect.3)
                .any(|publish| publish.payload == b"ON")
    })
    .await;
    for &(group, on) in &observations {
        let topic = format!("homeassistant/light/cbus_{group}/state");
        require(STARTUP, "outage observation delivered to MQTT", || {
            sys.broker.retained(&topic).is_some_and(|payload| {
                let payload = parse_json(&payload);
                payload["state"] == if on { "ON" } else { "OFF" }
                    && payload["cbus_source_addr"] == OBSERVER
            })
        })
        .await;
    }

    let before = command_results(&sys).len();
    sys.broker
        .inject_qos1("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command after broker restart", || {
        command_results(&sys)
            .get(before)
            .is_some_and(|result| result["group"] == 1 && result["delivery"] == "confirmed")
    })
    .await;
    assert_eq!(sys.pci.count_payload(&lighting_payload(1, true)), 1);
    assert_eq!(sys.pci.connections(), 1);

    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_dir_all(specs).unwrap();
}
