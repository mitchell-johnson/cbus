//! Owned daemon/TLS/MQTT acceptance while a scripted programming STORE is
//! outstanding. Certificates exist only in temporary storage. This does not
//! claim original C-Gate, host GUI or physical hardware acceptance.

mod util;

use cbus_test_support::pci::FakePci;
use cbus_test_support::proc::temp_path;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use util::*;

struct Scratch(PathBuf);
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn fixture() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_tls_programming_liveness.json"
    ))
    .unwrap()
}

fn certificate() -> (Scratch, Arc<rustls::ClientConfig>) {
    let scratch = Scratch(temp_path("tls-liveness"));
    std::fs::create_dir(&scratch.0).unwrap();
    let cert = scratch.0.join("cert.pem");
    let key = scratch.0.join("key.pem");
    let result = std::process::Command::new("openssl")
        .args([
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-out",
        ])
        .arg(&cert)
        .arg("-keyout")
        .arg(&key)
        .output()
        .expect("ephemeral certificate generator");
    assert!(
        result.status.success(),
        "ephemeral certificate generation failed"
    );
    let bytes = std::fs::read(cert).unwrap();
    let certs = rustls_pemfile::certs(&mut bytes.as_slice())
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let mut roots = rustls::RootCertStore::empty();
    roots.add(certs[0].clone()).unwrap();
    let config = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();
    (scratch, Arc::new(config))
}

type Stream = tokio_rustls::client::TlsStream<TcpStream>;
type Reader = BufReader<tokio::io::ReadHalf<Stream>>;
type Writer = tokio::io::WriteHalf<Stream>;

async fn connect(sys: &System, config: Arc<rustls::ClientConfig>) -> (Reader, Writer) {
    require(STARTUP, "TLS C-Gate listener", || {
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
    let name = rustls::pki_types::ServerName::try_from("127.0.0.1")
        .unwrap()
        .to_owned();
    let stream = tokio_rustls::TlsConnector::from(config)
        .connect(name, TcpStream::connect(address).await.unwrap())
        .await
        .unwrap();
    let (reader, writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader);
    let mut greeting = String::new();
    reader.read_line(&mut greeting).await.unwrap();
    assert!(greeting.starts_with("201 "));
    (reader, writer)
}

async fn command(reader: &mut Reader, writer: &mut Writer, command: &str) {
    writer
        .write_all(format!("[setup] {command}\r\n").as_bytes())
        .await
        .unwrap();
    writer.flush().await.unwrap();
    let result = tokio::time::timeout(STARTUP, async {
        let mut rows = String::new();
        loop {
            let mut row = String::new();
            assert_ne!(reader.read_line(&mut row).await.unwrap(), 0);
            rows.push_str(&row);
            if row.starts_with("[setup]") && row.as_bytes().get(11) == Some(&b' ') {
                return rows;
            }
        }
    })
    .await
    .unwrap();
    assert!(result.contains("[setup] 200"), "{command}: {result:?}");
}

struct Unit {
    memory: [u8; 256],
    held: Option<(Vec<u8>, u8, Vec<u8>)>,
    release: bool,
    stores: usize,
}

impl Unit {
    fn respond(&mut self, payload: &str) -> Option<Vec<u8>> {
        let cal = hex::decode(payload.strip_prefix("460500")?).ok()?;
        let reply = |data: &[u8]| {
            let mut body = vec![0x86, 5, 0x10, 1, 0];
            body.extend_from_slice(data);
            pci_wire(&body)
        };
        match *cal.first()? {
            0x21 => {
                let attr = *cal.get(1)?;
                let text: &[u8] = match attr {
                    1 => b"TESTUNIT",
                    2 => b"1.2.03",
                    _ => return None,
                };
                let mut answer = vec![0x80 | (text.len() as u8 + 1), attr];
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
                let (parameter, tag) = (*cal.get(1)?, *cal.get(2)?);
                let data = cal.get(3..1 + usize::from(header & 0x1F))?.to_vec();
                self.stores += 1;
                // Model an uncertain write: the peer applies it but withholds
                // its receipt. Neither success nor retry may be fabricated.
                let start = usize::from(parameter);
                self.memory[start..start + data.len()].copy_from_slice(&data);
                self.held = Some((reply(&[0x32, parameter, tag]), parameter, data));
                None
            }
            _ => None,
        }
    }
}

struct Task(tokio::task::JoinHandle<()>);
impl Drop for Task {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn run_unit(pci: FakePci, unit: Arc<Mutex<Unit>>, mut cursor: usize) {
    loop {
        let frames = pci.frames();
        let replies = {
            let mut unit = unit.lock().unwrap();
            let mut replies = Vec::new();
            for frame in &frames[cursor..] {
                replies.extend(unit.respond(&frame.payload));
            }
            if unit.release {
                if let Some((ack, _, _)) = unit.held.take() {
                    replies.push(ack);
                }
            }
            replies
        };
        cursor = frames.len();
        for wire in replies {
            pci.inject(&wire);
        }
        tokio::time::sleep(Duration::from_millis(2)).await;
    }
}

async fn journey(release: bool) {
    let literal = fixture();
    let (scratch, config) = certificate();
    let specs = scratch.0.join("unitspec");
    std::fs::create_dir(&specs).unwrap();
    std::fs::write(specs.join("TESTUNIT.xml"), "<UnitSpecification><Parameters><Param><Name>Block</Name><Type>int</Type><Address>$20</Address><ArraySize>12</ArraySize><ProgramMethod>direct</ProgramMethod><Protection>none</Protection><Tag>Core</Tag></Param></Parameters></UnitSpecification>").unwrap();
    let mut extra = vec!["--cgate-bind".into(), "127.0.0.1:0".into()];
    for (flag, path) in [
        ("--cgate-state", scratch.0.join("state.json")),
        ("--cgate-unitspec", specs),
        ("--cgate-tls-cert", scratch.0.join("cert.pem")),
        ("--cgate-tls-key", scratch.0.join("key.pem")),
    ] {
        extra.push(flag.into());
        extra.push(path.to_string_lossy().into_owned());
    }
    let sys = start_with(Options {
        extra,
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys, config).await;
    for text in [
        "PROJECT USE HARNESS",
        "PP LOCK L //HARNESS/254",
        "PP START S L",
        "PP NEW S TESTUNIT 1.2.03",
        "PP SET S Block 1 2 3 4 5 6 7 8 9 10 11 12",
        "EVENT e7s1c0",
    ] {
        command(&mut reader, &mut writer, text).await;
    }
    let unit = Arc::new(Mutex::new(Unit {
        memory: [0; 256],
        held: None,
        release: false,
        stores: 0,
    }));
    let driver = Task(tokio::spawn(run_unit(
        sys.pci.clone(),
        unit.clone(),
        sys.pci.frames().len(),
    )));
    let rows = Arc::new(Mutex::new(Vec::<String>::new()));
    let collector = Task(tokio::spawn({
        let rows = rows.clone();
        async move {
            loop {
                let mut row = String::new();
                if reader.read_line(&mut row).await.unwrap_or(0) == 0 {
                    break;
                }
                rows.lock().unwrap().push(row);
            }
        }
    }));
    writer
        .write_all(b"[save] PP SAVE S //HARNESS/254/p/5 Core\r\n[after] NOOP\r\n")
        .await
        .unwrap();
    writer.flush().await.unwrap();
    require(STARTUP, "unacknowledged STORE", || {
        unit.lock().unwrap().held.is_some()
    })
    .await;
    let topic = literal["mqtt_command"]["topic"].as_str().unwrap();
    sys.broker.inject_qos1(topic, br#"{"state":"ON"}"#);
    sys.pci.inject(
        literal["observation"]["pci_wire"]
            .as_str()
            .unwrap()
            .as_bytes(),
    );
    require(STARTUP, "MQTT command confirmed during programming", || {
        sys.broker
            .find_publishes("cmqttd/cbus/command_result")
            .iter()
            .any(|p| {
                let result = parse_json(&p.payload);
                result["group"] == 1 && result["delivery"] == literal["mqtt_command"]["delivery"]
            })
    })
    .await;
    require(STARTUP, "bus observation published to MQTT", || {
        sys.broker
            .find_publishes(literal["observation"]["mqtt_topic"].as_str().unwrap())
            .iter()
            .any(|p| {
                let state = parse_json(&p.payload);
                state["state"] == literal["observation"]["state"]
                    && state["cbus_source_addr"] == literal["observation"]["source_unit"]
            })
    })
    .await;
    let event = literal["observation"]["cgate_status"].as_str().unwrap();
    assert!(
        cbus_test_support::wait::wait_until(STARTUP, || {
            rows.lock().unwrap().iter().any(|row| row == event)
        })
        .await,
        "TLS event before programming terminal; received {:?}",
        rows.lock().unwrap()
    );
    {
        let captured = rows.lock().unwrap();
        assert!(
            !captured
                .iter()
                .any(|row| row.starts_with("[save] ") || row.starts_with("[after] ")),
            "{captured:?}"
        );
        let mut peer = unit.lock().unwrap();
        assert_eq!(peer.stores, 1);
        assert!(peer.held.is_some());
        peer.release = release;
    }
    let after = literal["terminal"]["next_command"].as_str().unwrap();
    require(
        COMMAND_DRAIN,
        "ordered programming and pipelined NOOP terminals",
        || rows.lock().unwrap().iter().any(|row| row == after),
    )
    .await;
    let captured = rows.lock().unwrap().clone();
    let prefix = literal["terminal"][if release {
        "success_prefix"
    } else {
        "uncertain_prefix"
    }]
    .as_str()
    .unwrap();
    let save = captured
        .iter()
        .position(|row| row.starts_with(prefix))
        .expect("programming outcome");
    let event_index = captured.iter().position(|row| row == event).unwrap();
    let after_index = captured.iter().position(|row| row == after).unwrap();
    assert!(event_index < save && save < after_index, "{captured:?}");
    assert_eq!(captured.iter().filter(|row| *row == event).count(), 1);
    assert_eq!(
        captured
            .iter()
            .filter(|row| row.starts_with("[save] "))
            .count(),
        1
    );
    assert_eq!(captured.iter().filter(|row| *row == after).count(), 1);
    assert_eq!(
        unit.lock().unwrap().stores,
        literal["programming"]["store_count"].as_u64().unwrap() as usize
    );
    let payloads = sys.pci.payloads();
    assert_eq!(
        payloads
            .iter()
            .filter(|payload| payload
                .starts_with(literal["programming"]["store_prefix"].as_str().unwrap()))
            .count(),
        1,
        "no uncertain STORE may be replayed"
    );
    assert_eq!(
        &unit.lock().unwrap().memory[0x20..0x2C],
        &[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    );
    assert!(sys
        .pci
        .payloads()
        .iter()
        .any(|p| p == literal["mqtt_command"]["pci_payload"].as_str().unwrap()));
    println!(
        "TLS_LIVENESS {}",
        serde_json::json!({"released":release,"daemon_pid":sys.daemon.pid(),"wire":captured,"pci_payloads":sys.pci.payloads(),"mqtt_receipts":sys.broker.find_publishes("cmqttd/cbus/command_result").iter().map(|p|parse_json(&p.payload)).collect::<Vec<_>>() })
    );
    drop(collector);
    drop(driver);
    drop(writer);
    drop(sys);
    drop(scratch);
}

#[tokio::test]
async fn tls_events_and_mqtt_continue_before_programming_success_and_next_terminal() {
    journey(true).await;
}

#[tokio::test]
async fn tls_events_and_mqtt_continue_before_uncertain_store_failure_without_replay() {
    journey(false).await;
}
