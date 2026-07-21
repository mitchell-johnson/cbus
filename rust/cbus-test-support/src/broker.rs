//! In-process MQTT 3.1.1 mini broker: a Rust-native port of
//! `rust-migration-harness/lib/mini_broker.py`.
//!
//! Supports exactly what cmqttd needs: CONNECT/CONNACK (protocol level 4
//! enforced), PUBLISH QoS 0/1/2 (with PUBACK / PUBREC+PUBREL+PUBCOMP),
//! SUBSCRIBE/SUBACK, UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP and
//! DISCONNECT. Records every inbound PUBLISH and subscription, and can
//! inject a PUBLISH to subscribed clients (wildcard matching), which is
//! how tests play the part of Home Assistant.

use std::sync::{Arc, Mutex};
use std::time::Instant;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::mpsc;

/// MQTT topic-filter matching (`#`, `+`).
pub fn topic_matches(filter: &str, topic: &str) -> bool {
    let fp: Vec<&str> = filter.split('/').collect();
    let tp: Vec<&str> = topic.split('/').collect();
    for (i, seg) in fp.iter().enumerate() {
        if *seg == "#" {
            return true;
        }
        if i >= tp.len() {
            return false;
        }
        if *seg == "+" {
            continue;
        }
        if *seg != tp[i] {
            return false;
        }
    }
    fp.len() == tp.len()
}

/// One PUBLISH received by the broker.
#[derive(Debug, Clone)]
pub struct PublishRecord {
    /// Topic of the publish.
    pub topic: String,
    /// Raw payload bytes.
    pub payload: Vec<u8>,
    /// QoS of the publish (0..=2).
    pub qos: u8,
    /// Retain flag.
    pub retain: bool,
    /// When the broker received it.
    pub ts: Instant,
}

struct ClientHandle {
    tx: mpsc::UnboundedSender<Vec<u8>>,
    subscriptions: Vec<String>,
}

#[derive(Default)]
struct State {
    publishes: Vec<PublishRecord>,
    subscriptions: Vec<String>,
    retained: std::collections::HashMap<String, Vec<u8>>,
    errors: Vec<String>,
    clients: Vec<ClientHandle>,
    connections: usize,
    clean_disconnects: usize,
}

/// The broker: `start()` binds an ephemeral port; queries are snapshots.
pub struct MiniBroker {
    state: Arc<Mutex<State>>,
    port: u16,
}

fn encode_remaining(mut n: usize) -> Vec<u8> {
    let mut out = Vec::new();
    loop {
        let b = (n % 128) as u8;
        n /= 128;
        if n > 0 {
            out.push(b | 0x80);
        } else {
            out.push(b);
            return out;
        }
    }
}

fn publish_packet(topic: &str, payload: &[u8], qos: u8, retain: bool) -> Vec<u8> {
    let tb = topic.as_bytes();
    let mut var = (tb.len() as u16).to_be_bytes().to_vec();
    var.extend_from_slice(tb);
    if qos > 0 {
        var.extend_from_slice(&1u16.to_be_bytes()); // fixed pid for injections
    }
    var.extend_from_slice(payload);
    let hdr = 0x30 | (qos << 1) | u8::from(retain);
    let mut out = vec![hdr];
    out.extend(encode_remaining(var.len()));
    out.extend(var);
    out
}

impl MiniBroker {
    /// Bind 127.0.0.1 on an ephemeral port and start accepting clients.
    pub async fn start() -> MiniBroker {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind broker");
        let port = listener.local_addr().unwrap().port();
        let state: Arc<Mutex<State>> = Default::default();
        let st = state.clone();
        tokio::spawn(async move {
            loop {
                let Ok((stream, _)) = listener.accept().await else {
                    break;
                };
                let st = st.clone();
                tokio::spawn(handle_client(stream, st));
            }
        });
        MiniBroker { state, port }
    }

    /// The bound TCP port.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Every PUBLISH received so far, in order.
    pub fn publishes(&self) -> Vec<PublishRecord> {
        self.state.lock().unwrap().publishes.clone()
    }

    /// The PUBLISHes on exactly `topic`, in order.
    pub fn find_publishes(&self, topic: &str) -> Vec<PublishRecord> {
        self.publishes()
            .into_iter()
            .filter(|p| p.topic == topic)
            .collect()
    }

    /// Every topic filter any client subscribed to.
    pub fn subscriptions(&self) -> Vec<String> {
        self.state.lock().unwrap().subscriptions.clone()
    }

    /// Whether some client subscribed with exactly this filter.
    pub fn has_subscription(&self, filter: &str) -> bool {
        self.subscriptions().iter().any(|s| s == filter)
    }

    /// Protocol errors the broker flagged (e.g. wrong MQTT version).
    pub fn errors(&self) -> Vec<String> {
        self.state.lock().unwrap().errors.clone()
    }

    /// Latest retained payload on `topic`.
    pub fn retained(&self, topic: &str) -> Option<Vec<u8>> {
        self.state.lock().unwrap().retained.get(topic).cloned()
    }

    /// Number of TCP connections accepted.
    pub fn connections(&self) -> usize {
        self.state.lock().unwrap().connections
    }

    /// Number of clean MQTT DISCONNECTs received.
    pub fn clean_disconnects(&self) -> usize {
        self.state.lock().unwrap().clean_disconnects
    }

    /// Deliver a message to subscribed clients as if published by an
    /// external client (e.g. Home Assistant sending a /set command).
    pub fn inject(&self, topic: &str, payload: &[u8]) {
        let st = self.state.lock().unwrap();
        let pkt = publish_packet(topic, payload, 0, false);
        for c in &st.clients {
            if c.subscriptions.iter().any(|f| topic_matches(f, topic)) {
                let _ = c.tx.send(pkt.clone());
            }
        }
    }
}

async fn read_packet(
    stream: &mut tokio::net::tcp::OwnedReadHalf,
) -> std::io::Result<(u8, Vec<u8>)> {
    let hdr = stream.read_u8().await?;
    let mut mult: usize = 1;
    let mut rem: usize = 0;
    for i in 0.. {
        let b = stream.read_u8().await?;
        rem += (b & 0x7f) as usize * mult;
        if b & 0x80 == 0 {
            break;
        }
        mult *= 128;
        if i > 3 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "bad remaining length",
            ));
        }
    }
    let mut body = vec![0u8; rem];
    stream.read_exact(&mut body).await?;
    Ok((hdr, body))
}

async fn handle_client(stream: tokio::net::TcpStream, state: Arc<Mutex<State>>) {
    let (mut rd, mut wr) = stream.into_split();
    let (tx, mut rx) = mpsc::unbounded_channel::<Vec<u8>>();
    let client_index;
    {
        let mut st = state.lock().unwrap();
        st.connections += 1;
        client_index = st.clients.len();
        st.clients.push(ClientHandle {
            tx: tx.clone(),
            subscriptions: Vec::new(),
        });
    }
    tokio::spawn(async move {
        while let Some(data) = rx.recv().await {
            if wr.write_all(&data).await.is_err() {
                break;
            }
        }
    });

    loop {
        let Ok((hdr, body)) = read_packet(&mut rd).await else {
            break;
        };
        let kind = hdr >> 4;
        match kind {
            1 => {
                // CONNECT: protocol name (len-prefixed) then level byte
                let nlen = u16::from_be_bytes([body[0], body[1]]) as usize;
                let level = body[2 + nlen];
                if level != 4 {
                    state.lock().unwrap().errors.push(format!(
                        "client used MQTT protocol level {level}; \
                         this harness requires 3.1.1 (level 4)"
                    ));
                    let _ = tx.send(vec![0x20, 0x02, 0x00, 0x01]);
                    break;
                }
                let _ = tx.send(vec![0x20, 0x02, 0x00, 0x00]);
            }
            3 => {
                // PUBLISH
                let qos = (hdr >> 1) & 0x03;
                let retain = hdr & 0x01 != 0;
                let tlen = u16::from_be_bytes([body[0], body[1]]) as usize;
                let topic = String::from_utf8_lossy(&body[2..2 + tlen]).into_owned();
                let mut off = 2 + tlen;
                let mut pid = [0u8; 2];
                if qos > 0 {
                    pid = [body[off], body[off + 1]];
                    off += 2;
                }
                let payload = body[off..].to_vec();
                let pkt = publish_packet(&topic, &payload, 0, false);
                {
                    let mut st = state.lock().unwrap();
                    st.publishes.push(PublishRecord {
                        topic: topic.clone(),
                        payload: payload.clone(),
                        qos,
                        retain,
                        ts: Instant::now(),
                    });
                    if retain {
                        st.retained.insert(topic.clone(), payload.clone());
                    }
                    if qos == 1 {
                        let _ = tx.send(vec![0x40, 0x02, pid[0], pid[1]]);
                    } else if qos == 2 {
                        let _ = tx.send(vec![0x50, 0x02, pid[0], pid[1]]);
                    }
                    // deliver to all matching subscribers (incl. sender),
                    // like a real broker; delivered at qos 0.
                    for c in &st.clients {
                        if c.subscriptions.iter().any(|f| topic_matches(f, &topic)) {
                            let _ = c.tx.send(pkt.clone());
                        }
                    }
                }
            }
            6 => {
                // PUBREL (qos2 completion)
                let _ = tx.send(vec![0x70, 0x02, body[0], body[1]]);
            }
            8 => {
                // SUBSCRIBE
                let pid = [body[0], body[1]];
                let mut off = 2;
                let mut granted = Vec::new();
                while off < body.len() {
                    let tlen = u16::from_be_bytes([body[off], body[off + 1]]) as usize;
                    let topic =
                        String::from_utf8_lossy(&body[off + 2..off + 2 + tlen]).into_owned();
                    let rq = body[off + 2 + tlen];
                    off += 3 + tlen;
                    let mut st = state.lock().unwrap();
                    st.subscriptions.push(topic.clone());
                    st.clients[client_index].subscriptions.push(topic);
                    granted.push(rq.min(1));
                }
                let mut pkt = vec![0x90];
                pkt.extend(encode_remaining(2 + granted.len()));
                pkt.extend_from_slice(&pid);
                pkt.extend(granted);
                let _ = tx.send(pkt);
            }
            10 => {
                // UNSUBSCRIBE
                let _ = tx.send(vec![0xb0, 0x02, body[0], body[1]]);
            }
            12 => {
                // PINGREQ
                let _ = tx.send(vec![0xd0, 0x00]);
            }
            14 => {
                // DISCONNECT
                state.lock().unwrap().clean_disconnects += 1;
                break;
            }
            4 => { /* PUBACK for our injected qos1: ignore */ }
            _ => {
                state
                    .lock()
                    .unwrap()
                    .errors
                    .push(format!("unhandled MQTT packet type {kind}"));
            }
        }
    }
}
