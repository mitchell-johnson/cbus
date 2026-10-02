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
    start_reconnecting_project(state, specs, &project_file()).await
}

async fn start_reconnecting_project(state: &Path, specs: &Path, project: &str) -> System {
    let broker = MiniBroker::start().await;
    let pci = FakePci::start(false).await;
    let broker_port = broker.port().to_string();
    let wifi = format!("127.0.0.1:{}", pci.port());
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
        project,
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

// Independent scripted peers for every currently admitted routed PP method.
// The JSON roster is an owned scheduling contract, not a native transcript.
struct RoutedUnit {
    case: serde_json::Value,
    memory: Vec<u8>,
    page: usize,
    pointer: usize,
    stores: Vec<(usize, Vec<u8>)>,
    held: Option<(Vec<u8>, usize, Vec<u8>)>,
    polls: usize,
    executes: usize,
    release: bool,
    stop: bool,
}

fn liveness_vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_pp_programming_liveness.json"
    ))
    .unwrap()
}

impl RoutedUnit {
    fn new(case: &serde_json::Value) -> Arc<Mutex<Self>> {
        Arc::new(Mutex::new(Self {
            case: case.clone(),
            memory: vec![0; 1024],
            page: 0,
            pointer: 0,
            stores: Vec::new(),
            held: None,
            polls: 0,
            executes: 0,
            release: false,
            stop: false,
        }))
    }

    fn route(&self) -> Vec<u8> {
        self.case["route"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_u64().unwrap() as u8)
            .collect()
    }

    fn response(&self, cal: &[u8]) -> Vec<u8> {
        let route = self.route();
        let mut body = vec![0x86, route[0], 0x10, route.len() as u8];
        body.extend_from_slice(&route[1..]);
        body.push(UNIT);
        body.extend_from_slice(cal);
        pci_wire(&body)
    }

    fn read(&self, parameter: u8, address: usize, count: usize) -> Vec<Vec<u8>> {
        self.memory[address..address + count]
            .chunks(30)
            .enumerate()
            .map(|(index, chunk)| {
                let parameter = if matches!(self.case["method"].as_str(), Some("paged" | "ncc")) {
                    parameter.wrapping_add((index * 30) as u8)
                } else {
                    parameter
                };
                let mut cal = vec![0x80 | (chunk.len() as u8 + 1), parameter];
                cal.extend_from_slice(chunk);
                self.response(&cal)
            })
            .collect()
    }

    fn respond(&mut self, payload: &str) -> Vec<Vec<u8>> {
        let Some(bytes) = hex::decode(payload).ok() else {
            return Vec::new();
        };
        let route = self.route();
        let prefix = [
            vec![0x46, route[0], route.len() as u8 * 9],
            route[1..].to_vec(),
            vec![UNIT],
        ]
        .concat();
        let Some(cal) = bytes.strip_prefix(&prefix[..]) else {
            return Vec::new();
        };
        let method = self.case["method"].as_str().unwrap();
        match cal[0] {
            0x21 => {
                let text: &[u8] = if cal[1] == 1 { b"TESTUNIT" } else { b"1.2.03" };
                let mut answer = vec![0x80 | (text.len() as u8 + 1), cal[1]];
                answer.extend_from_slice(text);
                vec![self.response(&answer)]
            }
            0x1A => {
                let address = match method {
                    "edlt" | "giu" | "sgiu" | "dali" | "goc" | "gocbyt" | "goc2" => self.pointer,
                    _ => usize::from(cal[1]),
                };
                self.read(cal[1], address, usize::from(cal[2]))
            }
            0x1B => self.read(
                cal[2],
                usize::from(cal[1]) * 256 + usize::from(cal[2]),
                usize::from(cal[3]),
            ),
            0x39 => {
                self.page = usize::from(cal[1]);
                vec![self.response(&[0x81, cal[1]])]
            }
            0xE3 if cal[1..4] == [0x81, 0, 4] => {
                self.executes += 1;
                vec![self.response(&[0xE4, 0x83, 0, 4, 1])]
            }
            0xE3 if cal[1..4] == [0x82, 0, 4] => {
                self.polls += 1;
                vec![self.response(&[0xE4, 0x83, 0, 4, u8::from(!self.release)])]
            }
            header if header & 0xE0 == 0xA0 => {
                let parameter = cal[1];
                let data = &cal[2..1 + usize::from(header & 0x1F)];
                if parameter == 0xFC && method == "giu" {
                    return vec![self.response(&[0x32, parameter, data[0]])];
                }
                if parameter == 0
                    && data[0] == 0x41
                    && matches!(method, "edlt" | "giu" | "sgiu" | "dali")
                {
                    self.pointer = usize::from(data[1]) | usize::from(data[2]) << 8;
                    return vec![self.response(&[0x32, parameter, 0x41])];
                }
                let (address, ack_parameter, stored) = match method {
                    "edlt" | "giu" | "sgiu" | "dali" => {
                        (self.pointer, parameter, data[1..].to_vec())
                    }
                    "goc" | "gocbyt" | "goc2" => {
                        let address = usize::from(data[1]) << 8 | usize::from(data[2]);
                        let ack_parameter = if method == "goc2" {
                            address as u8
                        } else {
                            parameter
                        };
                        if data[0] == 0x42 {
                            self.pointer = address;
                            return vec![self.response(&[0x32, ack_parameter, 0x42])];
                        }
                        (address, ack_parameter, data[3..].to_vec())
                    }
                    "paged" | "ncc" => (
                        self.page * 256 + usize::from(parameter),
                        parameter,
                        data[1..].to_vec(),
                    ),
                    _ => (usize::from(parameter), parameter, data[1..].to_vec()),
                };
                self.stores.push((address, stored.clone()));
                let ack = self.response(&[0x32, ack_parameter, data[0]]);
                if self.stores.len() == 3 && self.case["hold"] == "store-3" {
                    self.held = Some((ack, address, stored));
                    return Vec::new();
                }
                self.memory[address..address + stored.len()].copy_from_slice(&stored);
                vec![ack]
            }
            _ => Vec::new(),
        }
    }
}

async fn run_routed_unit(pci: &FakePci, unit: &Mutex<RoutedUnit>, mut cursor: usize) {
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
                if let Some((ack, address, data)) = unit.held.take() {
                    unit.memory[address..address + data.len()].copy_from_slice(&data);
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

fn routed_fixture(case: &serde_json::Value, tag: &str) -> (PathBuf, PathBuf, PathBuf) {
    let state = temp_path(&format!("pp-liveness-{tag}.json"));
    let specs = temp_path(&format!("pp-liveness-{tag}-spec"));
    let project = temp_path(&format!("pp-liveness-{tag}-project.xml"));
    std::fs::create_dir_all(&specs).unwrap();
    std::fs::write(specs.join("TESTUNIT.xml"), format!(
        "<UnitSpecification><Parameters><Param><Name>Block</Name><Type>int</Type><Address>${:X}</Address><ArraySize>48</ArraySize><ProgramMethod>{}</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param></Parameters></UnitSpecification>",
        case["logical_address"].as_u64().unwrap(), case["method"].as_str().unwrap()
    )).unwrap();
    let route = case["route"].as_array().unwrap();
    let networks = std::iter::once(254u8)
        .chain(route.iter().map(|v| v.as_u64().unwrap() as u8))
        .collect::<Vec<_>>();
    let mut xml =
        String::from("<Installation><Project oid=\"liveness-project\"><TagName>HARNESS</TagName>");
    for (index, &network) in networks.iter().enumerate() {
        xml.push_str(&format!("<Network oid=\"network-{network}\"><TagName>Network{network}</TagName><Address>{network}</Address>"));
        if index == 0 {
            xml.push_str("<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Application><Address>56</Address><TagName>Lighting</TagName><Group><Address>1</Address><TagName>One</TagName></Group><Group><Address>10</Address><TagName>Ten</TagName></Group></Application>");
        } else {
            xml.push_str(&format!("<Interface><InterfaceType>Bridge</InterfaceType><InterfaceAddress>{}/p/{network}</InterfaceAddress></Interface><Unit><Address>{}</Address><UnitType>BRIDGE2N</UnitType></Unit>", networks[index - 1], networks[index - 1]));
        }
        if let Some(next) = networks.get(index + 1) {
            xml.push_str(&format!(
                "<Unit><Address>{next}</Address><UnitType>BRIDGE2N</UnitType></Unit>"
            ));
        }
        xml.push_str("</Network>");
    }
    xml.push_str("</Project></Installation>");
    std::fs::write(&project, xml).unwrap();
    (state, specs, project)
}

async fn stage_routed_session(reader: &mut Reader, writer: &mut Writer, case: &serde_json::Value) {
    let network = case["network"].as_u64().unwrap();
    for text in [
        "PROJECT USE HARNESS".into(),
        format!("PP LOCK L //HARNESS/{network}"),
        "PP START S L".into(),
        "PP NEW S TESTUNIT 1.2.03".into(),
        format!(
            "PP SET S Block {}",
            (1..=48)
                .map(|v| format!("0x{v:02X}"))
                .collect::<Vec<_>>()
                .join(" ")
        ),
        "EVENT e7s1c0".into(),
    ] {
        let response = command(reader, writer, &text).await;
        assert!(response.contains("200 OK"), "{text}: {response}");
    }
}

async fn routed_method_liveness(id: &str) {
    let vector = liveness_vector();
    let case = vector["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == id)
        .unwrap();
    let (state, specs, project) = routed_fixture(case, id);
    let mut extra = cgate_args(&state, &specs);
    extra.extend(["-P".into(), project.to_string_lossy().into_owned()]);
    let sys = start_with(Options {
        project: false,
        extra,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let observer_rows = collect_events(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_routed_session(&mut reader, &mut writer, case).await;
    let unit = RoutedUnit::new(case);
    let cursor = sys.pci.frames().len();
    let rows = Arc::new(Mutex::new(Vec::<String>::new()));
    let queued = vector["queued_commands"].as_u64().unwrap() as usize;
    writer
        .write_all(
            format!(
                "[save] {}\r\n{}[done] NOOP\r\n",
                case["save"].as_str().unwrap(),
                (0..queued)
                    .map(|i| format!("[queue-{i}] NOOP\r\n"))
                    .collect::<String>()
            )
            .as_bytes(),
        )
        .await
        .unwrap();
    let saving = async {
        loop {
            let mut row = String::new();
            assert_ne!(reader.read_line(&mut row).await.unwrap(), 0, "{id}");
            let done = row.starts_with("[done] ");
            rows.lock().unwrap().push(row.trim_end().to_string());
            if done {
                break;
            }
        }
        unit.lock().unwrap().stop = true;
    };
    let commands: Vec<_> = (0..vector["mqtt_commands"].as_u64().unwrap())
        .map(|i| (if i % 2 == 0 { 1u8 } else { 10 }, i % 4 < 2))
        .collect();
    let observations: Vec<_> = (0..vector["observations"].as_u64().unwrap())
        .map(|i| (100 + i as u8, i % 3 != 0))
        .collect();
    let mut published = Vec::new();
    let driver = async {
        require(COMMAND_DRAIN, "routed programming held", || {
            let unit = unit.lock().unwrap();
            unit.held.is_some() || unit.polls >= 2
        })
        .await;
        if case["method"] == "ncc" {
            // Earlier/direct and incorrectly correlated completions cannot
            // release this routed save while its NVM poll remains busy.
            sys.pci.inject(&reply(&[0xE4, 0x83, 0, 4, 0]));
            sys.pci
                .inject(&unit.lock().unwrap().response(&[0xE4, 0x83, 0, 5, 0]));
            let route = unit.lock().unwrap().route();
            let mut wrong_route = vec![0x86, route[0] - 1, 0x10, route.len() as u8];
            wrong_route.extend_from_slice(&route[1..]);
            wrong_route.extend_from_slice(&[UNIT, 0xE4, 0x83, 0, 4, 0]);
            sys.pci.inject(&pci_wire(&wrong_route));
        }
        for &(group, on) in &commands {
            published.push(Instant::now());
            sys.broker.inject_qos1(
                &format!("homeassistant/light/cbus_{group}/set"),
                if on {
                    br#"{"state":"ON"}"#
                } else {
                    br#"{"state":"OFF"}"#
                },
            );
        }
        for &(group, on) in &observations {
            sys.pci.inject(&observation(group, on));
        }
        require(
            Duration::from_secs(3),
            "same command socket events while SAVE is pending",
            || observation_rows(&rows).len() == observations.len(),
        )
        .await;
        require(
            Duration::from_secs(3),
            "independent socket events while SAVE is pending",
            || observation_rows(&observer_rows).len() == observations.len(),
        )
        .await;
        require(
            command_latency_bound() * commands.len() as u32,
            "MQTT commands during routed save",
            || {
                sys.pci
                    .payloads()
                    .iter()
                    .filter(|p| is_lighting_command(p))
                    .count()
                    == commands.len()
            },
        )
        .await;
        assert!(
            !rows
                .lock()
                .unwrap()
                .iter()
                .any(|row| row.starts_with("[save]")
                    || row.starts_with("[queue-")
                    || row.starts_with("[done]")),
            "serial command receipts escaped before SAVE completion"
        );
        unit.lock().unwrap().release = true;
    };
    tokio::time::timeout(Duration::from_secs(60), async {
        tokio::join!(saving, run_routed_unit(&sys.pci, &unit, cursor), driver);
    })
    .await
    .expect("routed save must complete with bounded scheduling");
    let all_rows = rows.lock().unwrap().clone();
    let receipt_rows: Vec<_> = all_rows
        .iter()
        .filter(|row| row.starts_with('['))
        .cloned()
        .collect();
    let expected = std::iter::once(case["expected_final"].as_str().unwrap().to_string())
        .chain((0..queued).map(|i| format!("[queue-{i}] 200 OK.")))
        .chain(std::iter::once("[done] 200 OK.".to_string()))
        .collect::<Vec<_>>();
    assert_eq!(receipt_rows, expected, "{id}: serial pipelined receipts");
    for received in [&rows, &observer_rows] {
        let events = observation_rows(received);
        assert_eq!(events.len(), observations.len(), "{id}");
        for (row, &(group, on)) in events.iter().zip(&observations) {
            assert!(
                row.starts_with(&expected_observation_row(group, on)),
                "{id}: {row}"
            );
        }
    }
    let frames = sys.pci.frames();
    let lighting: Vec<_> = frames
        .iter()
        .filter(|frame| is_lighting_command(&frame.payload))
        .collect();
    assert_eq!(
        lighting
            .iter()
            .map(|frame| frame.payload.clone())
            .collect::<Vec<_>>(),
        commands
            .iter()
            .map(|&(group, on)| lighting_payload(group, on))
            .collect::<Vec<_>>(),
        "{id}: command order and no replay"
    );
    let mut previous = None::<Instant>;
    for (i, frame) in lighting.iter().enumerate() {
        let eligible = previous.map_or(published[i], |last| last.max(published[i]));
        assert!(
            frame.ts.saturating_duration_since(eligible) <= command_latency_bound(),
            "{id}: command {i} latency"
        );
        previous = Some(frame.ts);
    }
    require(STARTUP, "all confirmed MQTT receipts", || {
        command_results(&sys).len() == commands.len()
    })
    .await;
    assert!(command_results(&sys)
        .iter()
        .all(|r| r["delivery"] == "confirmed"));
    for &(group, on) in &observations {
        require(STARTUP, "routed-save observation fanout to MQTT", || {
            sys.broker
                .retained(&format!("homeassistant/light/cbus_{group}/state"))
                .is_some_and(|payload| {
                    let payload = parse_json(&payload);
                    payload["state"] == if on { "ON" } else { "OFF" }
                        && payload["cbus_source_addr"] == OBSERVER
                })
        })
        .await;
    }
    {
        let unit = unit.lock().unwrap();
        let start = case["memory_address"].as_u64().unwrap() as usize;
        assert_eq!(
            &unit.memory[start..start + 48],
            &(1..=48).collect::<Vec<_>>()[..],
            "{id}: verified memory"
        );
        let mut addresses = std::collections::HashSet::new();
        assert!(
            unit.stores
                .iter()
                .all(|(address, _)| addresses.insert(*address)),
            "{id}: no STORE replay"
        );
        assert!(
            frames.iter().any(|frame| frame
                .payload
                .starts_with(case["identify_request"].as_str().unwrap())),
            "exact route"
        );
        assert_eq!(unit.executes, usize::from(case["method"] == "ncc"));
        if case["method"] == "ncc" {
            assert!(unit.polls >= 3);
            assert_eq!(
                frames
                    .iter()
                    .filter(|frame| frame
                        .payload
                        .starts_with(case["execute_request"].as_str().unwrap()))
                    .count(),
                1
            );
            assert_eq!(
                frames
                    .iter()
                    .filter(|frame| frame
                        .payload
                        .starts_with(case["poll_request"].as_str().unwrap()))
                    .count(),
                unit.polls
            );
        }
    }
    // Mode changes stay serial behind the completed SAVE and do not affect
    // its earlier event prefix. A later observation still reaches MQTT and
    // independent subscribers, but cannot leak into this disabled stream.
    assert!(command(&mut reader, &mut writer, "EVENT e0s0c0")
        .await
        .contains("200 OK"));
    sys.pci.inject(&observation(210, true));
    require(STARTUP, "observation after same-socket EVENT OFF", || {
        sys.broker
            .retained("homeassistant/light/cbus_210/state")
            .is_some_and(|payload| parse_json(&payload)["cbus_source_addr"] == OBSERVER)
    })
    .await;
    let mut disabled = String::new();
    assert!(
        tokio::time::timeout(Duration::from_millis(100), reader.read_line(&mut disabled))
            .await
            .is_err(),
        "mode OFF leaked {disabled:?}"
    );
    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}

macro_rules! routed_liveness_case {
    ($name:ident, $id:literal) => {
        #[tokio::test]
        async fn $name() {
            routed_method_liveness($id).await;
        }
    };
}
routed_liveness_case!(
    routed_direct_one_hop_keeps_same_socket_events_and_fifo_receipts,
    "direct-1-hop"
);
routed_liveness_case!(
    routed_direct_six_hops_keeps_same_socket_events_and_fifo_receipts,
    "direct-6-hop"
);
routed_liveness_case!(
    routed_paged_save_keeps_same_socket_events_and_fifo_receipts,
    "paged-1-hop"
);
routed_liveness_case!(
    routed_ncc_nvm_save_keeps_same_socket_events_and_fifo_receipts,
    "ncc-6-hop"
);
routed_liveness_case!(
    routed_edlt_save_keeps_same_socket_events_and_fifo_receipts,
    "edlt-1-hop"
);
routed_liveness_case!(
    routed_giu_save_keeps_same_socket_events_and_fifo_receipts,
    "giu-6-hop"
);
routed_liveness_case!(
    routed_sgiu_save_keeps_same_socket_events_and_fifo_receipts,
    "sgiu-1-hop"
);
routed_liveness_case!(
    routed_dali_save_keeps_same_socket_events_and_fifo_receipts,
    "dali-6-hop"
);
routed_liveness_case!(
    routed_goc_save_keeps_same_socket_events_and_fifo_receipts,
    "goc-1-hop"
);
routed_liveness_case!(
    routed_gocbyt_save_keeps_same_socket_events_and_fifo_receipts,
    "gocbyt-6-hop"
);
routed_liveness_case!(
    routed_goc2_save_keeps_same_socket_events_and_fifo_receipts,
    "goc2-1-hop"
);

#[tokio::test]
async fn routed_nvm_pci_loss_never_replays_or_accepts_stale_completion() {
    let vector = liveness_vector();
    let case = vector["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "ncc-6-hop")
        .unwrap();
    let (state, specs, project) = routed_fixture(case, "nvm-pci-loss");
    let sys = start_reconnecting_project(&state, &specs, &project.to_string_lossy()).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_routed_session(&mut reader, &mut writer, case).await;
    let staged = command(&mut reader, &mut writer, "PP GET S Block").await;
    let unit = RoutedUnit::new(case);
    let cursor = sys.pci.frames().len();
    let saving = async { command(&mut reader, &mut writer, case["save"].as_str().unwrap()).await };
    let driver = async {
        require(
            COMMAND_DRAIN,
            "routed NVM busy poll before PCI loss",
            || unit.lock().unwrap().polls >= 2,
        )
        .await;
        unit.lock().unwrap().stop = true;
        sys.pci.kick();
    };
    let (failed, (), ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(saving, run_routed_unit(&sys.pci, &unit, cursor), driver)
    })
    .await
    .unwrap();
    assert!(
        failed
            .lines()
            .filter(|line| line.starts_with("[5]"))
            .eq(std::iter::once(
                vector["nvm_pci_loss_receipt"].as_str().unwrap()
            )),
        "{failed}"
    );
    let before = sys.pci.payloads();
    let executes = before
        .iter()
        .filter(|p| p.starts_with(case["execute_request"].as_str().unwrap()))
        .count();
    assert_eq!(executes, 1);
    require(STARTUP, "fresh PCI connection after NVM loss", || {
        sys.pci.connections() == 2
            && sys
                .daemon
                .stderr()
                .contains("reconnected; MQTT bridge re-bound")
    })
    .await;
    let stale = unit.lock().unwrap().response(&[0xE4, 0x83, 0, 4, 0]);
    sys.pci.inject(&stale);
    sys.pci.inject(&observation(210, true));
    require(
        STARTUP,
        "new generation observation after stale NVM completion",
        || {
            sys.broker
                .retained("homeassistant/light/cbus_210/state")
                .is_some_and(|p| parse_json(&p)["cbus_source_addr"] == OBSERVER)
        },
    )
    .await;
    let after_stale = command(&mut reader, &mut writer, "PP GET S Block").await;
    assert_eq!(after_stale.lines().filter(|line| line.starts_with("[5]")).collect::<Vec<_>>(), staged.lines().filter(|line| line.starts_with("[5]")).collect::<Vec<_>>(), "stale NVM reply cannot clear or rewrite staged values; separate subscribed events remain eligible");
    sys.broker
        .inject_qos1("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
    require(COMMAND_DRAIN, "MQTT command on fresh generation", || {
        command_results(&sys)
            .iter()
            .any(|r| r["delivery"] == "confirmed")
    })
    .await;
    assert_eq!(sys.pci.count_payload(&lighting_payload(1, true)), 1);
    let after = sys.pci.payloads();
    let routed_prefix = case["identify_request"]
        .as_str()
        .unwrap()
        .strip_suffix("2101")
        .unwrap();
    assert_eq!(
        after
            .iter()
            .filter(|p| p.starts_with(routed_prefix))
            .cloned()
            .collect::<Vec<_>>(),
        before
            .iter()
            .filter(|p| p.starts_with(routed_prefix))
            .cloned()
            .collect::<Vec<_>>(),
        "reconnect and late completion never replay any routed request"
    );
    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}

#[tokio::test]
async fn routed_nvm_broker_outage_preserves_same_socket_events_and_save_completion() {
    let vector = liveness_vector();
    let case = vector["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == "ncc-6-hop")
        .unwrap();
    let (state, specs, project) = routed_fixture(case, "nvm-broker-outage");
    let mut extra = cgate_args(&state, &specs);
    extra.extend(["-P".into(), project.to_string_lossy().into_owned()]);
    let sys = start_with(Options {
        project: false,
        extra,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_routed_session(&mut reader, &mut writer, case).await;
    let unit = RoutedUnit::new(case);
    let cursor = sys.pci.frames().len();
    let rows = Arc::new(Mutex::new(Vec::<String>::new()));
    writer
        .write_all(format!("[save] {}\r\n", case["save"].as_str().unwrap()).as_bytes())
        .await
        .unwrap();
    let save = async {
        loop {
            let mut row = String::new();
            assert_ne!(reader.read_line(&mut row).await.unwrap(), 0);
            let done = row.starts_with("[save] ");
            rows.lock().unwrap().push(row.trim_end().to_string());
            if done {
                break;
            }
        }
        unit.lock().unwrap().stop = true;
    };
    let first = sys.broker.connections();
    let driver = async {
        require(COMMAND_DRAIN, "NVM poll before broker loss", || {
            unit.lock().unwrap().polls >= 2
        })
        .await;
        sys.broker.set_refusing(true);
        sys.broker.disconnect_clients();
        require(STARTUP, "broker refuses reconnect", || {
            sys.broker.refused_connections() >= 1
        })
        .await;
        for i in 0..80u8 {
            sys.pci.inject(&observation(100 + i, i % 3 != 0));
        }
        require(
            Duration::from_secs(3),
            "same socket events during NVM and broker outage",
            || observation_rows(&rows).len() == 80,
        )
        .await;
        assert!(!rows.lock().unwrap().iter().any(|r| r.starts_with("[save]")));
        unit.lock().unwrap().release = true;
    };
    tokio::time::timeout(Duration::from_secs(40), async {
        tokio::join!(save, run_routed_unit(&sys.pci, &unit, cursor), driver);
    })
    .await
    .unwrap();
    assert_eq!(
        rows.lock()
            .unwrap()
            .iter()
            .filter(|r| r.starts_with("[save]"))
            .cloned()
            .collect::<Vec<_>>(),
        ["[save] 200 OK"]
    );
    assert_eq!(
        sys.broker.connections(),
        first,
        "save finished while broker remained unavailable"
    );
    assert_eq!(unit.lock().unwrap().executes, 1);
    sys.broker.set_refusing(false);
    require(STARTUP, "broker reconnect after NVM completion", || {
        sys.broker.connections() > first
            && sys
                .broker
                .subscriptions()
                .iter()
                .filter(|s| *s == COMMAND_WILDCARD)
                .count()
                >= 2
    })
    .await;
    for i in 0..80u8 {
        require(STARTUP, "queued outage observation reaches MQTT", || {
            sys.broker
                .retained(&format!("homeassistant/light/cbus_{}/state", 100 + i))
                .is_some_and(|p| {
                    let p = parse_json(&p);
                    p["cbus_source_addr"] == OBSERVER
                        && p["state"] == if i % 3 != 0 { "ON" } else { "OFF" }
                })
        })
        .await;
    }
    let cgate = observation_rows(&rows);
    for (i, row) in cgate.iter().enumerate() {
        assert!(row.starts_with(&expected_observation_row(100 + i as u8, i % 3 != 0)));
    }
    assert_eq!(sys.pci.connections(), 1);
    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}

/// A real subscriber that stops reading cannot hold its physical save or
/// lock ownership indefinitely. Its event write has a finite timeout; the
/// live programming transaction is dropped and the PCI lane requires a
/// reconnect before any later programming, even after a late ACK.
#[tokio::test]
async fn subscribed_slow_socket_retires_routed_programming_without_replay() {
    let vector = liveness_vector();
    let case = vector["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "direct-1-hop")
        .unwrap();
    let (state, specs, project) = routed_fixture(case, "slow-subscriber");
    let sys = start_reconnecting_project(&state, &specs, &project.to_string_lossy()).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = cgate_connect(&sys).await;
    stage_routed_session(&mut reader, &mut writer, case).await;
    writer
        .write_all(format!("[save] {}\r\n", case["save"].as_str().unwrap()).as_bytes())
        .await
        .unwrap();
    let unit = RoutedUnit::new(case);
    let cursor = sys.pci.frames().len();
    let (mut producer_reader, mut producer_writer) = cgate_connect(&sys).await;
    let driver = async {
        require(
            COMMAND_DRAIN,
            "slow subscriber has outstanding STORE",
            || unit.lock().unwrap().held.is_some(),
        )
        .await;
        // Keep its read half alive without consuming it. Each owned local
        // broadcast exceeds its small receive window; no PCI IO is involved.
        #[cfg(unix)]
        {
            use std::os::fd::AsRawFd;
            let bytes: libc::c_int = 1024;
            let result = unsafe {
                libc::setsockopt(
                    reader.get_ref().as_ref().as_raw_fd(),
                    libc::SOL_SOCKET,
                    libc::SO_RCVBUF,
                    (&bytes as *const libc::c_int).cast(),
                    std::mem::size_of_val(&bytes) as libc::socklen_t,
                )
            };
            assert_eq!(result, 0);
        }
        let payload = "x".repeat(vector["slow_client"]["payload_bytes"].as_u64().unwrap() as usize);
        for _ in 0..vector["slow_client"]["broadcasts"].as_u64().unwrap() {
            let response = command(
                &mut producer_reader,
                &mut producer_writer,
                &format!("BROADCAST_EVENT SP class {payload}"),
            )
            .await;
            assert!(response.contains("[5] 200 OK."));
        }
        require(
            Duration::from_secs(vector["slow_client"]["deadline_seconds"].as_u64().unwrap()),
            "slow event subscriber connection retired",
            || {
                sys.daemon
                    .stderr()
                    .contains("C-Gate event client is not reading")
                    || sys.daemon.stderr().contains("C-Gate event queue overflow")
            },
        )
        .await;
        require(
            STARTUP,
            "cancelled programming retires PCI and establishes a fresh generation",
            || {
                sys.pci.connections()
                    == vector["slow_client"]["fresh_connections"].as_u64().unwrap() as usize
                    && sys
                        .daemon
                        .stderr()
                        .contains("C-Bus connection lost; reconnecting")
                    && sys
                        .daemon
                        .stderr()
                        .contains("reconnected; MQTT bridge re-bound")
            },
        )
        .await;
        let caps = command(
            &mut producer_reader,
            &mut producer_writer,
            "CMQTT CAPABILITIES",
        )
        .await;
        assert!(
            caps.contains("\"pci_generation\":1")
                && caps.contains(&format!(
                    "\"programming_lane_state\":\"{}\"",
                    vector["slow_client"]["fresh_lane_state"].as_str().unwrap()
                )),
            "{caps}"
        );
        assert_eq!(
            unit.lock().unwrap().stores.len(),
            3,
            "no write followed the cancelled outstanding exchange"
        );
        // Connection cleanup releases only this former owner's PP names.
        for text in [
            format!("PP LOCK L //HARNESS/{}", case["network"]),
            "PP START S L".into(),
            "PP NEW S TESTUNIT 1.2.03".into(),
            "PP SET S Block 1".into(),
        ] {
            assert!(
                command(&mut producer_reader, &mut producer_writer, &text)
                    .await
                    .contains("200 OK"),
                "{text}"
            );
        }
        let staged = command(&mut producer_reader, &mut producer_writer, "PP GET S Block").await;
        let stale = unit.lock().unwrap().held.as_ref().unwrap().0.clone();
        sys.pci.inject(&stale);
        sys.pci.inject(&observation(210, true));
        require(STARTUP, "new generation remains live after old ACK", || {
            sys.broker
                .retained("homeassistant/light/cbus_210/state")
                .is_some()
        })
        .await;
        let current = command(&mut producer_reader, &mut producer_writer, "PP GET S Block").await;
        assert_eq!(
            staged, current,
            "late ACK cannot rewrite a new owner's session"
        );
        assert_eq!(
            unit.lock().unwrap().stores.len(),
            3,
            "old generation and reconnect never replay its uncertain STORE"
        );
        unit.lock().unwrap().stop = true;
    };
    tokio::time::timeout(Duration::from_secs(40), async {
        tokio::join!(run_routed_unit(&sys.pci, &unit, cursor), driver);
    })
    .await
    .unwrap();
    drop(reader);
    drop(writer);
    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}

/// A separate physical C-Gate command queued on the service's FIFO mutex
/// must still receive events while another connection programs a unit.
/// Physical actions execute after SAVE, in receipt order and exactly once;
/// MQTT lighting can independently use its live command lane during SAVE.
#[tokio::test]
async fn queued_physical_cgate_commands_receive_events_without_overtaking_save() {
    let vector = liveness_vector();
    let case = vector["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "direct-1-hop")
        .unwrap();
    let (state, specs, project) = routed_fixture(case, "queued-physical");
    let mut extra = cgate_args(&state, &specs);
    extra.extend(["-P".into(), project.to_string_lossy().into_owned()]);
    let sys = start_with(Options {
        project: false,
        extra,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let (mut save_reader, mut save_writer) = cgate_connect(&sys).await;
    stage_routed_session(&mut save_reader, &mut save_writer, case).await;
    let (mut queued_reader, mut queued_writer) = cgate_connect(&sys).await;
    assert!(
        command(&mut queued_reader, &mut queued_writer, "EVENT e7s1c0")
            .await
            .contains("200 OK")
    );
    let unit = RoutedUnit::new(case);
    let cursor = sys.pci.frames().len();
    let rows = Arc::new(Mutex::new(Vec::<String>::new()));
    let saving = async {
        let reply = command(
            &mut save_reader,
            &mut save_writer,
            case["save"].as_str().unwrap(),
        )
        .await;
        unit.lock().unwrap().stop = true;
        assert!(reply.lines().any(|line| line == "[5] 200 OK"));
    };
    let reading = async {
        loop {
            let mut row = String::new();
            assert_ne!(queued_reader.read_line(&mut row).await.unwrap(), 0);
            let done = row.starts_with("[off] ");
            rows.lock().unwrap().push(row.trim_end().to_string());
            if done {
                break;
            }
        }
    };
    let driver = async {
        require(COMMAND_DRAIN, "SAVE owns physical command lane", || {
            unit.lock().unwrap().held.is_some()
        })
        .await;
        for request in vector["queued_physical"]["requests"].as_array().unwrap() {
            queued_writer
                .write_all(format!("{}\r\n", request.as_str().unwrap()).as_bytes())
                .await
                .unwrap();
        }
        for i in 0..vector["queued_physical"]["observations"].as_u64().unwrap() {
            sys.pci.inject(&observation(100 + i as u8, i % 2 == 0));
        }
        sys.broker
            .inject_qos1("homeassistant/light/cbus_1/set", br#"{"state":"ON"}"#);
        require(
            Duration::from_secs(3),
            "events reach queued physical command socket",
            || observation_rows(&rows).len() == 6,
        )
        .await;
        require(
            command_latency_bound(),
            "MQTT remains live beside queued C-Gate command",
            || sys.pci.count_payload(&lighting_payload(1, true)) == 1,
        )
        .await;
        assert!(!rows
            .lock()
            .unwrap()
            .iter()
            .any(|r| r.starts_with("[on]") || r.starts_with("[off]")));
        assert_eq!(sys.pci.count_payload(&lighting_payload(30, true)), 0);
        assert_eq!(sys.pci.count_payload(&lighting_payload(31, false)), 0);
        unit.lock().unwrap().release = true;
    };
    tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(
            saving,
            reading,
            run_routed_unit(&sys.pci, &unit, cursor),
            driver
        );
    })
    .await
    .unwrap();
    let actual = rows
        .lock()
        .unwrap()
        .iter()
        .filter(|r| r.starts_with('['))
        .cloned()
        .collect::<Vec<_>>();
    assert_eq!(
        actual,
        vector["queued_physical"]["responses"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r.as_str().unwrap())
            .collect::<Vec<_>>()
    );
    let frames = sys.pci.frames();
    let on = frames
        .iter()
        .position(|f| f.payload == lighting_payload(30, true))
        .unwrap();
    let off = frames
        .iter()
        .position(|f| f.payload == lighting_payload(31, false))
        .unwrap();
    assert!(on < off);
    assert_eq!(sys.pci.count_payload(&lighting_payload(30, true)), 1);
    assert_eq!(sys.pci.count_payload(&lighting_payload(31, false)), 1);
    let route_prefix = case["identify_request"]
        .as_str()
        .unwrap()
        .strip_suffix("2101")
        .unwrap();
    assert!(
        frames
            .iter()
            .enumerate()
            .filter(|(_, f)| f.payload.starts_with(route_prefix))
            .all(|(i, _)| i < on),
        "every programming readback precedes queued physical actions"
    );
    drop(sys);
    let _ = std::fs::remove_file(state);
    std::fs::remove_file(project).unwrap();
    std::fs::remove_dir_all(specs).unwrap();
}
