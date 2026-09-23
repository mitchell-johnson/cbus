//! Loopback interop: real TCP framing against the `cgate-mock` binary.
//!
//! Speaks manual 4.3.1.5 over a socket exactly like the Python
//! `CGateClient`: `[tag] COMMAND`, `-` continuations, space-terminated
//! final lines, untagged `#e#` events ahead of replies, and `<< DELIMITER`
//! here-documents.

use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

struct Mock {
    child: Child,
    port: u16,
}

impl Mock {
    fn spawn() -> Self {
        Self::spawn_with(&["--bind", "127.0.0.1:0"])
    }

    fn spawn_with(extra: &[&str]) -> Self {
        let bin = env!("CARGO_BIN_EXE_cgate-mock");
        let mut child = Command::new(bin)
            .args(extra)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn cgate-mock");
        let mut first = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut first)
            .expect("read listening line");
        // `cgate-mock listening on 127.0.0.1:PORT`
        let port: u16 = first
            .trim()
            .rsplit(':')
            .next()
            .expect("port suffix")
            .parse()
            .expect("numeric port");
        // Give the listener a moment; connect retries cover the rest.
        Self { child, port }
    }

    fn connect(&self) -> Session {
        let mut last = None;
        for _ in 0..50 {
            match TcpStream::connect(("127.0.0.1", self.port)) {
                Ok(s) => {
                    s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
                    s.set_write_timeout(Some(Duration::from_secs(5))).unwrap();
                    return Session {
                        tag: 0,
                        reader: BufReader::new(s.try_clone().unwrap()),
                        writer: s,
                    };
                }
                Err(e) => last = Some(e),
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        panic!("connect failed: {:?}", last);
    }
}

impl Drop for Mock {
    fn drop(&mut self) {
        self.child.kill().ok();
        self.child.wait().ok();
    }
}

struct Session {
    tag: u32,
    reader: BufReader<TcpStream>,
    writer: TcpStream,
}

struct Reply {
    status: u16,
    lines: Vec<String>,
    events: Vec<String>,
}

impl Session {
    fn greeting(&mut self) -> String {
        let mut line = String::new();
        self.reader.read_line(&mut line).unwrap();
        line.trim().to_string()
    }

    fn command(&mut self, body: &str) -> Reply {
        self.tag += 1;
        let tag = self.tag.to_string();
        self.writer
            .write_all(format!("[{tag}] {body}\n").as_bytes())
            .unwrap();
        self.read_reply(&tag)
    }

    fn document(&mut self, body: &str, delimiter: &str, doc: &str) -> Reply {
        self.tag += 1;
        let tag = self.tag.to_string();
        self.writer
            .write_all(format!("[{tag}] {body} << {delimiter}\n").as_bytes())
            .unwrap();
        self.writer.write_all(doc.as_bytes()).unwrap();
        self.writer
            .write_all(format!("{delimiter}\n").as_bytes())
            .unwrap();
        self.read_reply(&tag)
    }

    fn read_reply(&mut self, tag: &str) -> Reply {
        let mut lines = Vec::new();
        let mut events = Vec::new();
        let status = loop {
            let mut line = String::new();
            self.reader.read_line(&mut line).unwrap();
            let line = line.trim().to_string();
            // Event shape, never tag: reuse the library matcher so the
            // timestamped and overflow forms stay covered here too.
            if cbus_cgate::is_event_line(&line) {
                events.push(line);
                continue;
            }
            let payload = line
                .strip_prefix(&format!("[{tag}] "))
                .unwrap_or_else(|| panic!("missing tag in {line:?}"));
            let code: u16 = payload[..3].parse().expect("status code");
            let sep = payload.as_bytes()[3];
            lines.push(payload.to_string());
            if sep == b' ' {
                break code;
            }
        };
        Reply {
            status,
            lines,
            events,
        }
    }
}

#[test]
fn tcp_project_network_lighting_cycle() {
    let mock = Mock::spawn();
    let mut s = mock.connect();
    assert!(s.greeting().starts_with("201 "));
    assert_eq!(s.command("NOOP").status, 200);
    assert_eq!(s.command("PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    let open = s.command("NET OPEN //TEST/254");
    assert_eq!(open.status, 200);
    // The open event arrives ahead of its own reply.
    assert!(open.events.iter().any(|e| e.contains("net 254 open")));
    let sync = s.command("NET SYNC //TEST/254");
    assert_eq!(sync.status, 200);
    assert_eq!(s.command("LIGHTING ON //TEST/254/56/1").status, 200);
    assert_eq!(
        s.command("LIGHTING RAMP //TEST/254/56/1 128 20").status,
        200
    );
    assert_eq!(s.command("TRIGGER EVENT //TEST/254/56 42").status, 200);
    assert_eq!(s.command("DBGET //TEST/254/56").status, 200);
    assert_eq!(s.command("PROJECT SAVE").status, 200);
}

/// Cross-connection broadcast: a subscribed reader observes another
/// session's project creation asynchronously, then stops after OFF.
#[test]
fn tcp_cross_connection_broadcast() {
    let mock = Mock::spawn();
    let mut reader = mock.connect();
    let mut writer = mock.connect();
    assert!(reader.greeting().starts_with("201 "));
    assert!(writer.greeting().starts_with("201 "));
    assert_eq!(reader.command("EVENT e8s1c1").status, 200);
    assert_eq!(writer.command("PROJECT NEW BCAST1").status, 200);
    let mut found = false;
    for _ in 0..20 {
        let poll = reader.command("NOOP");
        assert_eq!(poll.status, 200);
        if poll.events.iter().any(|e| e.contains("BCAST1")) {
            found = true;
            break;
        }
    }
    assert!(found, "subscribed reader never saw the project event");
    // After OFF the reader goes quiet.
    assert_eq!(reader.command("EVENT OFF").status, 200);
    assert_eq!(writer.command("PROJECT NEW BCAST2").status, 200);
    let mut leaked = false;
    for _ in 0..5 {
        let poll = reader.command("NOOP");
        if poll.events.iter().any(|e| e.contains("BCAST2")) {
            leaked = true;
            break;
        }
    }
    assert!(!leaked, "unsubscribed reader received broadcast events");
    // Selection isolation: the writer closing its own project must not
    // clear the reader's selection (session state, not server state).
    assert_eq!(reader.command("PROJECT NEW RPROJ").status, 200);
    assert_eq!(writer.command("PROJECT NEW WPROJ").status, 200);
    assert_eq!(writer.command("PROJECT CLOSE").status, 200);
    assert_eq!(reader.command("PROJECT SAVE").status, 200);
}

#[test]
fn tcp_deny_programming_posture() {
    let mock = Mock::spawn_with(&["--bind", "127.0.0.1:0", "--deny-programming"]);
    let mut s = mock.connect();
    assert!(s.greeting().starts_with("201 "));
    assert_eq!(s.command("PROJECT NEW TEST").status, 200);
    // Programming sessions stay denied; everything else still works.
    assert_eq!(s.command("PP LOCK //TEST/254").status, 420);
    assert_eq!(s.command("PROJECT LIST").status, 200);
}

#[test]
fn tcp_documents_and_oid_flow() {
    let mock = Mock::spawn();
    let mut s = mock.connect();
    assert!(s.greeting().starts_with("201 "));
    assert_eq!(s.command("PROJECT NEW TEST").status, 200);
    assert_eq!(
        s.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
            .status,
        200
    );
    // Here-document field store.
    let set = s.document("DBSETXML //TEST/254/p/20/UnitName", "ENDDOC1", "LOUNGE\n");
    assert_eq!(set.status, 200);
    // CGL import metric counts non-blank lines.
    let import = s.document("CGL IMPORT TEST", "ENDDOC2", "a\n\nb\nc\n");
    assert_eq!(import.status, 200);
    assert!(import.lines.iter().any(|l| l.contains("imported=3")));
    // Level OID dance: 301 answer, 342 resolution.
    let add = s.command("DBADDSAFE //TEST/254/56 Level 1 Evening");
    assert_eq!(add.status, 301);
    let oid = add.lines[0].rsplit('=').next().unwrap().to_string();
    let resolve = s.command(&format!("DBGET !{oid}/OID"));
    assert_eq!(resolve.status, 342);
    assert!(resolve.lines[0].ends_with(&oid));
}

#[test]
fn tcp_truncated_document_delivers_error_before_close() {
    let mock = Mock::spawn();
    let mut s = mock.connect();
    assert!(s.greeting().starts_with("201 "));
    s.writer
        .write_all(b"[123] DBSETXML //TEST/254/p/20/UnitName << END\npartial\n")
        .unwrap();
    s.writer.shutdown(std::net::Shutdown::Write).unwrap();
    let reply = s.read_reply("123");
    assert_eq!(reply.status, 400);
    assert_eq!(reply.lines, ["400 truncated here-document"]);
    let mut next = String::new();
    assert_eq!(s.reader.read_line(&mut next).unwrap(), 0);
}

#[test]
fn tcp_parameters_complete_with_315_and_keep_next_reply_synchronized() {
    let mock = Mock::spawn();
    let mut s = mock.connect();
    assert!(s.greeting().starts_with("201 "));
    for command in [
        "PROJECT NEW TEST",
        "DBCREATENET 254 Local Cni 127.0.0.1:10001",
        "DBADDSAFE //TEST/254 Unit 20 Lounge",
        "PP LOCK L //TEST/254",
        "PP START S L",
        "PP NEW S KEY1 1.2.67",
        "PP SET S A first",
        "PP SET S B second",
    ] {
        assert_eq!(s.command(command).status, 200, "{command}");
    }
    let all = s.command("PP GET S *");
    assert_eq!(all.status, 315);
    assert_eq!(all.lines, ["315-A=first", "315 B=second"]);
    let single = s.command("PP GET S A");
    assert_eq!(single.status, 315);
    assert_eq!(single.lines, ["315 A=first"]);
    assert_eq!(s.command("PP SAVE S /db//TEST/254/p/20").status, 200);
    let quick = s.command("PP QUICKGET //TEST/254/p/20 A");
    assert_eq!(quick.status, 315);
    assert_eq!(quick.lines, ["315 A=first"]);
    assert_eq!(s.command("NOOP").status, 200);
}

/// Event modes (manual 4.5.83): a bare query reports `306 <mode>`,
/// sets echo through the query, `EVENTS` aliases `EVENT`, modes are
/// per-connection, and fan-out honors the `e` gate.
#[test]
fn tcp_event_modes_query_isolation_and_filtering() {
    let mock = Mock::spawn();
    let mut a = mock.connect();
    let mut b = mock.connect();
    assert!(a.greeting().starts_with("201 "));
    assert!(b.greeting().starts_with("201 "));
    // Native console default on a fresh connection.
    let query = a.command("EVENT");
    assert_eq!(query.status, 306);
    assert_eq!(query.lines, vec!["306 e+s0c0".to_string()]);
    // The `EVENTS` alias sets; the query echoes the stored mode.
    assert_eq!(a.command("EVENTS e5s1c1").status, 200);
    let query = a.command("EVENTS");
    assert_eq!(query.status, 306);
    assert_eq!(query.lines, vec!["306 e5s1c1".to_string()]);
    // Modes are per-connection: b still reports the default.
    let query = b.command("EVENT");
    assert_eq!(query.lines, vec!["306 e+s0c0".to_string()]);
    // An `e0` reader stays silent on fan-out.
    assert_eq!(b.command("EVENT e0s0c0").status, 200);
    assert_eq!(a.command("PROJECT NEW EFILT").status, 200);
    let mut leaked = false;
    for _ in 0..5 {
        let poll = b.command("NOOP");
        if poll.events.iter().any(|e| e.contains("EFILT")) {
            leaked = true;
            break;
        }
    }
    assert!(!leaked, "e0 reader received broadcast events");
    // OFF reports the off mode back.
    assert_eq!(b.command("EVENT OFF").status, 200);
    let query = b.command("EVENT");
    assert_eq!(query.lines, vec!["306 e0s0c0".to_string()]);
}
