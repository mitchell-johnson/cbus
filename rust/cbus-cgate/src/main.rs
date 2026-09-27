//! `cgate-mock`: loopback C-Gate 3.4 test double over TCP.
//!
//! One shared [`cbus_cgate::Server`] serves every connection on the
//! listener, so model state (projects, networks, units, levels, locks,
//! sessions) is visible to all sessions — like the native server. Project
//! *selection*, in contrast, is session state: the hub swaps each
//! connection's selection in and out around its own commands, so one
//! session's `PROJECT USE` never retargets another. Drained command events
//! reach the originating connection synchronously ahead of its reply
//! (preserving single-session ordering) and fan out to other connections
//! holding an enabling `EVENT` subscription, which is what makes blocking
//! `read_event()` streams and the two-client (writer + subscribed reader)
//! flows work. Both paths filter by the connection's event mode
//! (`EVENT ON|OFF|e[+0-9]s[0-9]c[0-9]`, manual 4.5.83; `ON` is `e+s0c0`,
//! `OFF` is `e0s0c0`, a bare `EVENT` reports `306 <mode>`); every event
//! unlevelled model events pass any `e` but `e0`; native timestamped events
//! such as `BROADCAST_EVENT` also honor their encoded reporting level.
//!
//! Test-double limits, stated plainly: fanout channels are unbounded, so a
//! subscribed connection that stops reading while a writer stays chatty
//! grows memory without backpressure.
//!
//! Programming-lock rights are granted (this is a test double, not an
//! access model); pass `--deny-programming` to reproduce the default-deny
//! native posture.
//!
//! ```sh
//! cgate-mock --bind 127.0.0.1:0   # ephemeral port, prints the address
//! ```

use cbus_cgate::{
    format_native_dbgetxml_wire_response, format_response, parse_command, EventMode, Response,
    Server,
};
use chrono::Local;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{mpsc, Mutex};

const MAX_LINE_BYTES: usize = 1024 * 1024;
/// Cap for a single here-document body.
const MAX_DOCUMENT_BYTES: usize = 16 * 1024 * 1024;

fn usage() -> ! {
    eprintln!("usage: cgate-mock [--bind ADDR] [--deny-programming] [--unitspec DIR]");
    std::process::exit(2);
}

/// One connected session's delivery state.
struct HubSub {
    /// Whether an enabling `EVENT` subscription is held (`OFF`-equivalent
    /// modes hold none, per manual 4.5.83).
    subscribed: bool,
    /// This session's event mode (native console default `e+s0c0`);
    /// filters both synchronous own-events and broadcast fan-out.
    mode: EventMode,
    /// This session's selected project (session state — never shared).
    current: Option<String>,
    /// Native `SESSION_ID ALL` reports each command connection's peer and
    /// connection time; a tag may be set exactly once for that connection.
    peer: SocketAddr,
    connected_at: String,
    session_tag: Option<String>,
    /// Outbound lines (events and replies alike, in order).
    tx: mpsc::UnboundedSender<Outbound>,
}

enum Outbound {
    Line(String),
    Wire(String),
}

/// Shared model plus per-connection subscriptions.
struct Hub {
    server: Server,
    subs: HashMap<u64, HubSub>,
    next: u64,
    console_connected_at: String,
}

impl Hub {
    fn new(programming: bool, unitspec: Option<std::path::PathBuf>) -> Self {
        let mut server =
            Server::new(cbus_cgate::AccessLevel::Program).with_programming(programming);
        if let Some(dir) = unitspec {
            server = server.with_unitspec_dir(dir);
        }
        Self {
            server,
            subs: HashMap::new(),
            next: 1,
            console_connected_at: Local::now().format("%Y%m%d-%H%M%S").to_string(),
        }
    }

    /// Deliver a reply: the originator gets its own events synchronously
    /// ahead of the reply; every other *subscribed* connection gets the
    /// events asynchronously (native broadcast shape). Both paths honor
    /// the connection's event mode.
    fn emit(&mut self, origin: u64, resp: &Response, events: &[String], native_xml: bool) {
        if let Some(sub) = self.subs.get(&origin) {
            for event in events {
                if sub.mode.delivers_line(event) {
                    let _ = sub.tx.send(Outbound::Line(event.clone()));
                }
            }
            if let Some(wire) = native_xml
                .then(|| format_native_dbgetxml_wire_response(resp))
                .flatten()
            {
                let _ = sub.tx.send(Outbound::Wire(wire));
            } else {
                for line in format_response(resp).lines() {
                    let _ = sub.tx.send(Outbound::Line(line.to_string()));
                }
            }
        }
        for (id, sub) in self.subs.iter() {
            if *id != origin && sub.subscribed {
                for event in events {
                    if sub.mode.delivers_line(event) {
                        let _ = sub.tx.send(Outbound::Line(event.clone()));
                    }
                }
            }
        }
    }

    /// Run one command line against the shared model as one session:
    /// swap this connection's project selection in, handle, drain, save
    /// the selection back, and emit. The hub lock is held throughout, so
    /// sessions never observe each other's selection.
    fn dispatch(
        &mut self,
        origin: u64,
        native_xml: bool,
        op: impl FnOnce(&mut Server) -> Response,
    ) -> Response {
        let current = self.subs.get(&origin).and_then(|s| s.current.clone());
        self.server.set_current_project(current);
        self.server
            .set_command_session(Some(origin.saturating_mul(2).saturating_add(1)));
        let resp = op(&mut self.server);
        self.server.set_command_session(None);
        let events: Vec<String> = self.server.drain_events();
        let back = self.server.current_project();
        if let Some(sub) = self.subs.get_mut(&origin) {
            sub.current = back;
        }
        self.emit(origin, &resp, &events, native_xml);
        resp
    }

    /// `SESSION_ID` is command-connection state, not shared project state.
    /// Handle it at the TCP hub so ALL sees live peers and TAG cannot leak
    /// from one client to another. Ordinary commands still use `Server`.
    fn session_identity(&mut self, origin: u64, raw: &str) -> Option<Response> {
        let command = parse_command(raw).ok()?;
        let words: Vec<&str> = command.body.split_whitespace().collect();
        if !words.first()?.eq_ignore_ascii_case("SESSION_ID") {
            return None;
        }
        let tag = command.tag;
        let reply = |status, final_text: &str| Response {
            tag: tag.clone(),
            lines: Vec::new(),
            final_text: final_text.to_string(),
            status,
        };
        let response = match words.get(1).map(|word| word.to_ascii_uppercase()) {
            None => reply(300, &format!("300 sessionID=cmd{}", origin * 2 + 1)),
            Some(selector) if selector == "ALL" => {
                let mut sessions: Vec<_> = self.subs.iter().collect();
                sessions.sort_by_key(|(id, _)| **id);
                let mut rows = vec![format!(
                    "sessionID=cmd1 origin=internal from={} tag=Console",
                    self.console_connected_at
                )];
                rows.extend(sessions.into_iter().map(|(id, sub)| {
                    let mut row = format!(
                        "sessionID=cmd{} origin=/{} from={}",
                        id * 2 + 1,
                        sub.peer,
                        sub.connected_at
                    );
                    if let Some(session_tag) = &sub.session_tag {
                        row.push_str(" tag=");
                        row.push_str(session_tag);
                    }
                    row
                }));
                let (last, preceding) = rows.split_last().expect("origin session is live");
                Response {
                    tag,
                    lines: preceding.iter().map(|row| format!("300-{row}")).collect(),
                    final_text: format!("300 {last}"),
                    status: 300,
                }
            }
            Some(selector) if selector == "TAG" => {
                let value = words.get(2..).unwrap_or(&[]).join(" ");
                if value.is_empty() {
                    reply(400, "400 Syntax Error: tag name not supplied")
                } else if self
                    .subs
                    .get(&origin)
                    .is_some_and(|sub| sub.session_tag.is_some())
                {
                    reply(408, "408 Operation failed: tag name has already been set")
                } else {
                    self.subs
                        .get_mut(&origin)
                        .expect("origin session is live")
                        .session_tag = Some(value);
                    reply(200, "200 OK.")
                }
            }
            _ => reply(400, "400 Syntax Error."),
        };
        self.emit(origin, &response, &[], false);
        Some(response)
    }
}

#[tokio::main]
async fn main() {
    let mut bind = "127.0.0.1:20033".to_string();
    let mut deny_programming = false;
    let mut unitspec: Option<std::path::PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--bind" => bind = args.next().unwrap_or_else(|| usage()),
            "--deny-programming" => deny_programming = true,
            "--unitspec" => {
                unitspec = Some(args.next().unwrap_or_else(|| usage()).into());
            }
            _ => usage(),
        }
    }
    let listener = TcpListener::bind(&bind).await.unwrap_or_else(|e| {
        eprintln!("cgate-mock: cannot bind {bind}: {e}");
        std::process::exit(1);
    });
    println!("cgate-mock listening on {}", listener.local_addr().unwrap());
    let hub = Arc::new(Mutex::new(Hub::new(!deny_programming, unitspec)));
    loop {
        let Ok((stream, _)) = listener.accept().await else {
            continue;
        };
        tokio::spawn(serve(stream, Arc::clone(&hub)));
    }
}

async fn serve(stream: TcpStream, hub: Arc<Mutex<Hub>>) {
    let (tx, mut rx) = mpsc::unbounded_channel::<Outbound>();
    let peer = stream
        .peer_addr()
        .expect("accepted TCP connection has a peer");
    let id = {
        let mut hub = hub.lock().await;
        let id = hub.next;
        hub.next += 1;
        hub.subs.insert(
            id,
            HubSub {
                subscribed: false,
                mode: EventMode::DEFAULT,
                current: None,
                peer,
                connected_at: Local::now().format("%Y%m%d-%H%M%S").to_string(),
                session_tag: None,
                tx,
            },
        );
        id
    };
    let (reader, mut writer) = stream.into_split();
    // Single ordered writer: everything the session sends, replies and
    // broadcast events alike, flows through this task.
    let mut pump = tokio::spawn(async move {
        while let Some(outbound) = rx.recv().await {
            let (text, terminator) = match outbound {
                Outbound::Line(line) => (line, true),
                Outbound::Wire(wire) => (wire, false),
            };
            if writer.write_all(text.as_bytes()).await.is_err() {
                break;
            }
            if terminator && writer.write_all(b"\r\n").await.is_err() {
                break;
            }
        }
    });
    {
        let hub = hub.lock().await;
        if let Some(sub) = hub.subs.get(&id) {
            let _ = sub.tx.send(Outbound::Line("201 Service ready".to_string()));
        }
    }
    let mut lines = BufReader::new(reader).lines();
    loop {
        let mut raw = match lines.next_line().await {
            Ok(Some(l)) => l,
            _ => break,
        };
        if raw.len() > MAX_LINE_BYTES {
            // Untagged: the tag itself may be the overlong/malformed part,
            // so no command ID can be echoed. The connection closes with a
            // close-on-framing-error posture; the client
            // must reconnect rather than reuse this stream.
            let _ = send_raw(&hub, id, "400 C-Gate line exceeded configured limit").await;
            break;
        }
        if raw.ends_with('\r') {
            raw.pop();
        }
        let untagged_body = raw.trim_start();
        if !untagged_body.starts_with('[')
            && (untagged_body.starts_with('#') || untagged_body.starts_with("//"))
        {
            continue;
        }
        let tagged_hash_comment = raw
            .strip_prefix('[')
            .and_then(|line| line.split_once(']'))
            .is_some_and(|(_, body)| body.trim_start().starts_with('#'));
        if tagged_hash_comment {
            if send_raw(&hub, id, "400 Syntax Error.").await.is_err() {
                break;
            }
            continue;
        }
        // Here-document: `[tag] COMMAND << DELIMITER` + body + DELIMITER.
        if let Some((head, delimiter)) = split_heredoc(&raw) {
            let mut document = String::new();
            let mut truncated = false;
            let closed = loop {
                match lines.next_line().await {
                    Ok(Some(mut l)) => {
                        if l.ends_with('\r') {
                            l.pop();
                        }
                        if l == delimiter {
                            break true;
                        }
                        if l.len() > MAX_LINE_BYTES
                            || document.len() + l.len() + 1 > MAX_DOCUMENT_BYTES
                        {
                            truncated = true;
                        } else if !truncated {
                            document.push_str(&l);
                            document.push('\n');
                        }
                    }
                    // EOF before the delimiter: answer on the command's own
                    // tag (known from the head line) instead of vanishing,
                    // so the client sees a synchronized error, then close.
                    _ => break false,
                }
            };
            if !closed {
                let tag = head_tag(&head);
                let reply = if tag.is_empty() {
                    "400 truncated here-document".to_string()
                } else {
                    format!("[{tag}] 400 truncated here-document")
                };
                let _ = send_raw(&hub, id, &reply).await;
                break;
            }
            if truncated {
                // Never process a truncated body as if it were complete:
                // answer 400 on the command's own tag, then continue.
                let tag = head_tag(&head);
                let reply = if tag.is_empty() {
                    "400 document exceeded configured limit".to_string()
                } else {
                    format!("[{tag}] 400 document exceeded configured limit")
                };
                if send_raw(&hub, id, &reply).await.is_err() {
                    break;
                }
                continue;
            }
            let resp = {
                let mut hub = hub.lock().await;
                hub.dispatch(id, false, |server| server.handle_document(&head, &document))
            };
            track_subscription(&hub, id, &head, &resp).await;
            continue;
        }
        let head = raw.clone();
        // A bare `EVENT`/`EVENTS` query reports the connection's mode
        // (`306 <mode>`, manual 4.5.83) from hub session state — the
        // shared model holds no per-connection modes.
        if let Some(reply) = event_mode_query(&hub, id, &head).await {
            if send_raw(&hub, id, &reply).await.is_err() {
                break;
            }
            continue;
        }
        let native_xml = parse_command(&raw).ok().is_some_and(|command| {
            command
                .body
                .split_whitespace()
                .next()
                .is_some_and(|word| word.eq_ignore_ascii_case("DBGETXML"))
        });
        let resp = {
            let mut hub = hub.lock().await;
            hub.session_identity(id, &raw)
                .unwrap_or_else(|| hub.dispatch(id, native_xml, |server| server.handle(&raw)))
        };
        track_subscription(&hub, id, &head, &resp).await;
        if resp.status == 204 {
            break;
        }
    }
    hub.lock().await.subs.remove(&id);
    // Dropping the last sender lets the writer drain the final reply.
    // Aborting immediately used to discard the queued 400 on truncated
    // documents and could discard ordinary replies after a half-close.
    // A peer that no longer reads must not retain this task indefinitely.
    if tokio::time::timeout(std::time::Duration::from_secs(1), &mut pump)
        .await
        .is_err()
    {
        pump.abort();
        let _ = pump.await;
    }
}

/// Record the native incremental `EVENT`/`EVENTS` mode mutation. A rejected
/// later component can still change earlier levels on this connection.
async fn track_subscription(hub: &Arc<Mutex<Hub>>, id: u64, head: &str, resp: &Response) {
    if resp.status != 200
        && !(resp.status == 408 && resp.final_text.starts_with("408 Operation failed: Bad "))
    {
        return;
    }
    let body = head
        .strip_prefix('[')
        .and_then(|s| s.split_once(']'))
        .map(|(_, rest)| rest.trim_start())
        .unwrap_or("");
    let mut words = body.split_whitespace();
    let is_event = words
        .next()
        .is_some_and(|w| w.eq_ignore_ascii_case("EVENT") || w.eq_ignore_ascii_case("EVENTS"));
    if is_event {
        if let Some(word) = words.next() {
            let mut hub = hub.lock().await;
            if let Some(sub) = hub.subs.get_mut(&id) {
                let _ = sub.mode.apply_native(word);
                sub.subscribed = !sub.mode.is_off();
            }
        }
    }
}

/// Answer a bare `EVENT`/`EVENTS` mode query (`306 <mode>`, manual
/// 4.5.83) from hub session state; `None` for anything else, including
/// untagged lines (which normal handling rejects).
async fn event_mode_query(hub: &Arc<Mutex<Hub>>, id: u64, head: &str) -> Option<String> {
    let tag = head_tag(head);
    if tag.is_empty() {
        return None;
    }
    let body = head
        .strip_prefix('[')
        .and_then(|s| s.split_once(']'))
        .map(|(_, rest)| rest.trim_start())?;
    let mut words = body.split_whitespace();
    let verb = words.next()?;
    if !(verb.eq_ignore_ascii_case("EVENT") || verb.eq_ignore_ascii_case("EVENTS"))
        || words.next().is_some()
    {
        return None;
    }
    let hub = hub.lock().await;
    let mode = hub
        .subs
        .get(&id)
        .map(|sub| sub.mode)
        .unwrap_or(EventMode::DEFAULT);
    Some(format!("[{tag}] 306 {mode}"))
}

async fn send_raw(hub: &Arc<Mutex<Hub>>, id: u64, line: &str) -> Result<(), ()> {
    let hub = hub.lock().await;
    hub.subs.get(&id).ok_or(()).and_then(|sub| {
        sub.tx
            .send(Outbound::Line(line.to_string()))
            .map_err(|_| ())
    })
}

/// Split a `[tag] COMMAND << DELIMITER` line; `None` for ordinary commands.
///
/// Delimiters are short visible tokens such as `CBUS_END_<hex>`;
/// overlong delimiters fall back to ordinary command
/// handling, which rejects the line.
fn split_heredoc(line: &str) -> Option<(String, String)> {
    let (head, delimiter) = line.split_once(" << ")?;
    let delimiter = delimiter.trim();
    if delimiter.is_empty() || delimiter.len() > 128 || delimiter.contains([' ', '\t', '\r', '\n'])
    {
        return None;
    }
    Some((head.to_string(), delimiter.to_string()))
}

/// Best-effort tag of a `[tag] ...` head line for error replies.
fn head_tag(head: &str) -> &str {
    head.strip_prefix('[')
        .and_then(|s| s.split_once(']'))
        .map(|(t, _)| t)
        .unwrap_or("")
}
