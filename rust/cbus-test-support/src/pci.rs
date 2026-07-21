//! Scripted fake C-Bus PCI (TCP server): a Rust-native port of
//! `rust-migration-harness/lib/fake_pci.py`.
//!
//! Accepts cmqttd connections, records every frame the client sends,
//! auto-acknowledges confirmation codes (like a real PCI in smart mode)
//! and lets the test inject raw server->client wire bytes. Optionally
//! withholds the confirmation for the first confirmed frame of any kind
//! to exercise the client's retransmission logic.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::AsyncReadExt;
use tokio::net::TcpListener;
use tokio::sync::mpsc;

const HEX_CHARS: &[u8] = b"0123456789ABCDEF";

/// One CR-terminated command received from the C-Bus client, split the
/// way `rust-migration-harness/lib/wire.py` does (independent of the
/// production framing code on purpose).
#[derive(Debug, Clone)]
pub struct ClientFrame {
    /// The raw frame bytes (without the CR).
    pub raw: Vec<u8>,
    /// `~` reset token.
    pub is_reset: bool,
    /// `|` / `||` smart-connect shortcut.
    pub is_smart_connect: bool,
    /// Frame had no `\` prefix (basic mode).
    pub basic: bool,
    /// Trailing confirmation character, when present.
    pub conf: Option<u8>,
    /// The base16 command text (prefix and confirmation stripped).
    pub payload: String,
    /// When the frame arrived.
    pub ts: Instant,
}

impl ClientFrame {
    fn parse(raw: &[u8]) -> ClientFrame {
        let is_reset = raw == b"~";
        let is_smart_connect = raw == b"|" || raw == b"||";
        let basic = !raw.starts_with(b"\\");
        let mut body: &[u8] = if basic { raw } else { &raw[1..] };
        if body.starts_with(b"@") {
            body = &body[1..];
        }
        let mut conf = None;
        if !body.is_empty() && !is_reset && !is_smart_connect {
            let last = body[body.len() - 1];
            if !HEX_CHARS.contains(&last) {
                conf = Some(last);
                body = &body[..body.len() - 1];
            }
        }
        ClientFrame {
            raw: raw.to_vec(),
            is_reset,
            is_smart_connect,
            basic,
            conf,
            payload: String::from_utf8_lossy(body).into_owned(),
            ts: Instant::now(),
        }
    }
}

#[derive(Default)]
struct State {
    frames: Vec<ClientFrame>,
    reset_count: usize,
    smart_connect_count: usize,
    connections: usize,
    withhold_first_conf: bool,
    withheld: Option<(String, u8)>,
    withheld_seen: usize,
    /// Auto-confirmations are delayed by this much (slow-CNI emulation).
    conf_delay: Option<Duration>,
    writer: Option<mpsc::UnboundedSender<Vec<u8>>>,
    writer_abort: Option<tokio::task::AbortHandle>,
}

/// The fake PCI server; `start()` binds an ephemeral port.
pub struct FakePci {
    state: Arc<Mutex<State>>,
    port: u16,
}

impl FakePci {
    /// Bind 127.0.0.1 on an ephemeral port. `withhold_first_conf` makes
    /// the server swallow the confirmation of the first frame carrying a
    /// confirmation char (and all its byte-identical retries).
    pub async fn start(withhold_first_conf: bool) -> FakePci {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind pci");
        let port = listener.local_addr().unwrap().port();
        let state = Arc::new(Mutex::new(State {
            withhold_first_conf,
            ..Default::default()
        }));
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
        FakePci { state, port }
    }

    /// The bound TCP port.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Every frame received so far, in order.
    pub fn frames(&self) -> Vec<ClientFrame> {
        self.state.lock().unwrap().frames.clone()
    }

    /// Payloads of the non-special frames, in order.
    pub fn payloads(&self) -> Vec<String> {
        self.frames()
            .into_iter()
            .filter(|f| !f.is_reset && !f.is_smart_connect)
            .map(|f| f.payload)
            .collect()
    }

    /// How many frames carried exactly this payload.
    pub fn count_payload(&self, payload: &str) -> usize {
        self.frames()
            .into_iter()
            .filter(|f| f.payload == payload)
            .count()
    }

    /// `~` resets seen.
    pub fn reset_count(&self) -> usize {
        self.state.lock().unwrap().reset_count
    }

    /// `|` smart-connects seen.
    pub fn smart_connect_count(&self) -> usize {
        self.state.lock().unwrap().smart_connect_count
    }

    /// TCP connections accepted.
    pub fn connections(&self) -> usize {
        self.state.lock().unwrap().connections
    }

    /// How many times the withheld frame (original + identical retries)
    /// has been seen.
    pub fn withheld_seen(&self) -> usize {
        self.state.lock().unwrap().withheld_seen
    }

    /// Delay every subsequent auto-confirmation by `delay` (emulates a
    /// slow/loaded CNI withholding confirmations).
    pub fn set_conf_delay(&self, delay: Duration) {
        self.state.lock().unwrap().conf_delay = Some(delay);
    }

    /// Write raw server->client bytes (a from-PCI frame incl. CRLF).
    /// Panics if no client is connected.
    pub fn inject(&self, wire: &[u8]) {
        let st = self.state.lock().unwrap();
        let tx = st.writer.as_ref().expect("no client connected");
        tx.send(wire.to_vec()).expect("client writer gone");
    }

    /// Drop the current client connection (for reconnect tests): aborting
    /// the writer task drops the socket's write half, sending a FIN the
    /// daemon sees as EOF on its next read.
    pub fn kick(&self) {
        let mut st = self.state.lock().unwrap();
        st.writer = None;
        if let Some(h) = st.writer_abort.take() {
            h.abort();
        }
    }
}

async fn handle_client(stream: tokio::net::TcpStream, state: Arc<Mutex<State>>) {
    let (mut rd, mut wr) = stream.into_split();
    let (tx, mut rx) = mpsc::unbounded_channel::<Vec<u8>>();
    let writer_task = tokio::spawn(async move {
        use tokio::io::AsyncWriteExt as _;
        while let Some(data) = rx.recv().await {
            if wr.write_all(&data).await.is_err() {
                break;
            }
        }
        let _ = wr.shutdown().await;
    });
    {
        let mut st = state.lock().unwrap();
        st.connections += 1;
        st.writer = Some(tx.clone());
        st.writer_abort = Some(writer_task.abort_handle());
    }

    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        let n = match rd.read(&mut chunk).await {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        buf.extend_from_slice(&chunk[..n]);
        for frame in split_client_frames(&mut buf) {
            handle_frame(&state, &tx, frame);
        }
    }
    writer_task.abort();
}

fn handle_frame(state: &Arc<Mutex<State>>, tx: &mpsc::UnboundedSender<Vec<u8>>, f: ClientFrame) {
    let mut st = state.lock().unwrap();
    if f.is_reset {
        st.reset_count += 1;
        st.frames.push(f);
        return;
    }
    if f.is_smart_connect {
        st.smart_connect_count += 1;
        st.frames.push(f);
        return;
    }
    let conf = f.conf;
    let payload = f.payload.clone();
    st.frames.push(f);
    let Some(conf) = conf else {
        return;
    };
    if st.withhold_first_conf && st.withheld.is_none() {
        // withhold this one; count repeats of the exact same frame
        st.withheld = Some((payload, conf));
        st.withheld_seen = 1;
        return;
    }
    if let Some(withheld) = &st.withheld {
        if withheld == &(payload.clone(), conf) {
            st.withheld_seen += 1;
            return; // keep withholding: client should retry then abandon
        }
    }
    // ordinary confirmation: `<code>.` with no CR/LF (s4.3.3.3)
    match st.conf_delay {
        None => {
            let _ = tx.send(vec![conf, b'.']);
        }
        Some(delay) => {
            let tx = tx.clone();
            tokio::spawn(async move {
                tokio::time::sleep(delay).await;
                let _ = tx.send(vec![conf, b'.']);
            });
        }
    }
}

/// Consume complete CR-terminated frames (and bare `~` tokens) from `buf`.
fn split_client_frames(buf: &mut Vec<u8>) -> Vec<ClientFrame> {
    let mut frames = Vec::new();
    loop {
        let Some(idx) = buf.iter().position(|&b| b == b'\r') else {
            // handle a bare '~' with nothing else pending
            if buf == b"~" {
                frames.push(ClientFrame::parse(b"~"));
                buf.clear();
            }
            break;
        };
        let mut chunk: Vec<u8> = buf[..idx].to_vec();
        buf.drain(..idx + 1);
        if chunk.is_empty() {
            continue;
        }
        // a chunk may contain multiple bare '~' before a command
        while chunk.first() == Some(&b'~') {
            frames.push(ClientFrame::parse(b"~"));
            chunk.remove(0);
        }
        if !chunk.is_empty() {
            frames.push(ClientFrame::parse(&chunk));
        }
    }
    frames
}
