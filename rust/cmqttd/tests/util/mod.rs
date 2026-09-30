//! Shared setup for the cmqttd full-system tests: spawns the real cmqttd
//! binary against the in-process mini MQTT broker and scripted fake PCI,
//! with committed behavioral expectations as the oracle.
#![allow(dead_code)]

use cbus_protocol::common::add_cbus_checksum;
use cbus_test_support::broker::MiniBroker;
use cbus_test_support::pci::FakePci;
use cbus_test_support::proc::Daemon;
use serde_json::Value;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::io::{AsyncBufRead, AsyncBufReadExt};

pub use cbus_test_support::wait::require;

/// The actual binary under test.
pub const BIN: &str = env!("CARGO_BIN_EXE_cmqttd");

/// Generous ceiling for startup milestones (condition-polled, so tests
/// only pay this on failure).
pub const STARTUP: Duration = Duration::from_secs(20);

/// Ceiling for a /set command to reach the PCI. Commands get priority
/// over queued status-sweep traffic in the flow controller, so this is
/// normally sub-second (condition-polled: tests only pay it on failure).
pub const COMMAND_DRAIN: Duration = Duration::from_secs(60);

/// The CONFIG restart effects add native 761/766/767 command trace events,
/// and command sessions add 803/804 lifecycle and 899/999 admission rows, to an enabled EVENT
/// stream. Application tests read past those independently covered rows so
/// their next assertion still targets the injected SAL.
/// A C-Gate event line with its native timestamp replaced by `<timestamp>`
/// and line ending removed, for comparison with captured native rows.
pub fn untimed_event(line: &str) -> String {
    let line = line.trim_end_matches(['\r', '\n']);
    match line
        .strip_prefix("#e# ")
        .and_then(|body| body.split_once(' '))
    {
        Some((stamp, rest)) if stamp.starts_with(|c: char| c.is_ascii_digit()) => {
            format!("#e# <timestamp> {rest}")
        }
        _ => line.to_string(),
    }
}

pub async fn read_cgate_nontrace_into<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    line: &mut String,
) -> std::io::Result<usize> {
    loop {
        line.clear();
        let read = reader.read_line(line).await?;
        if read == 0 || !is_cgate_command_trace(line) {
            return Ok(read);
        }
    }
}

fn is_cgate_command_trace(line: &str) -> bool {
    if line.starts_with("#e# ")
        && (line.contains(" 999 sys Socket accepted.")
            || line.contains(" 899 sys Debug: New Command Context: cc"))
    {
        return true;
    }
    let mut words = line.split_whitespace();
    words.next() == Some("#e#")
        && words.next().is_some()
        && matches!(words.next(), Some("761" | "766" | "767" | "803" | "804"))
        && words.next().is_some_and(|session| {
            session.strip_prefix("cmd").is_some_and(|number| {
                !number.is_empty() && number.bytes().all(|byte| byte.is_ascii_digit())
            })
        })
        && words.next() == Some("-")
}

pub fn testdata_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../testdata")
}

pub fn project_file() -> String {
    testdata_dir()
        .join("fixtures/project.xml")
        .to_string_lossy()
        .into_owned()
}

/// The committed behavioral expectations.
pub fn expectations() -> &'static Value {
    static EXP: OnceLock<Value> = OnceLock::new();
    EXP.get_or_init(|| {
        let path = testdata_dir().join("fixtures/behavioral_expectations.json");
        serde_json::from_str(&std::fs::read_to_string(&path).expect("read expectations"))
            .expect("expectations json")
    })
}

pub struct System {
    pub broker: MiniBroker,
    pub pci: FakePci,
    pub daemon: Daemon,
}

pub struct Options {
    pub project: bool,
    pub withhold_first_conf: bool,
    /// The fake PCI echoes basic-mode lines with a bare CR.
    pub basic_echo: bool,
    /// Value for `-T` (timesync period; "0" disables like the harness).
    pub timesync: String,
    pub extra: Vec<String>,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            project: true,
            withhold_first_conf: false,
            basic_echo: false,
            timesync: "0".into(),
            extra: Vec::new(),
        }
    }
}

/// Start broker + fake PCI + cmqttd with the standard behavioral-suite
/// arguments (`-T 0`, DEBUG, TLS disabled) plus `opts.extra`.
pub async fn start_with(opts: Options) -> System {
    let broker = MiniBroker::start().await;
    let pci = if opts.basic_echo {
        FakePci::start_basic_echo(opts.withhold_first_conf).await
    } else {
        FakePci::start(opts.withhold_first_conf).await
    };
    let broker_port = broker.port().to_string();
    let pci_addr = format!("127.0.0.1:{}", pci.port());
    let project = project_file();
    let mut args: Vec<String> = [
        "-b",
        "127.0.0.1",
        "-p",
        &broker_port,
        "--broker-disable-tls",
        "-t",
        &pci_addr,
        "-T",
        &opts.timesync,
        "-v",
        "DEBUG",
    ]
    .map(String::from)
    .to_vec();
    if opts.project {
        args.push("-P".into());
        args.push(project);
    }
    args.extend(opts.extra);
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    let daemon = Daemon::spawn(BIN, &arg_refs);
    System {
        broker,
        pci,
        daemon,
    }
}

pub async fn start_default() -> System {
    start_with(Options::default()).await
}

pub async fn start_no_project() -> System {
    start_with(Options {
        project: false,
        ..Default::default()
    })
    .await
}

/// Body bytes -> a from-PCI wire frame (checksum, uppercase hex, CRLF).
pub fn pci_wire(body: &[u8]) -> Vec<u8> {
    let mut w = hex::encode_upper(add_cbus_checksum(body)).into_bytes();
    w.extend_from_slice(b"\r\n");
    w
}

/// The basic-mode DM frames of the PCI init sequence, in arrival order.
/// (Nothing may interleave: all non-init traffic waits for the init
/// sequence to finish, like the deployed daemon.)
pub fn dm_init_frames(sys: &System) -> Vec<cbus_test_support::pci::ClientFrame> {
    sys.pci
        .frames()
        .into_iter()
        .filter(|f| f.payload.starts_with("A3"))
        .collect()
}

/// Binary (`05FF007A...`) or level (`05FF0073...`) status request.
pub fn is_status_request(payload: &str) -> bool {
    payload.starts_with("05FF0073") || payload.starts_with("05FF007A")
}

/// The exact configured status sweep for the fixture project: apps
/// ascending (48 then 56), block 0x00 each, binary before level.
pub fn configured_sweep() -> Vec<String> {
    expectations()["configured_sweep"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect()
}

/// Block until cmqttd finished its PCI init and subscribed the command
/// wildcard — the common "fully up" baseline. (Runs without a project
/// file send no status requests, so the sweep is not waited on here.)
pub async fn wait_started(sys: &System) {
    require(STARTUP, "PCI init DM sequence", || {
        dm_init_frames(sys).len() >= 4
    })
    .await;
    require(STARTUP, "MQTT wildcard subscription", || {
        sys.broker.has_subscription("homeassistant/light/+/set")
    })
    .await;
}

pub fn parse_json(payload: &[u8]) -> Value {
    serde_json::from_slice(payload).expect("payload is JSON")
}
