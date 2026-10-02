//! Owned mock TCP bounds; not original C-Gate or physical acceptance.
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Shutdown, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};

fn vector() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../testdata/vectors/cgate_mock_delivery_bounds.json"
    ))
    .unwrap()
}

struct Mock {
    child: Child,
    port: u16,
    errors: Arc<Mutex<String>>,
    logger: Option<std::thread::JoinHandle<()>>,
}

impl Mock {
    fn spawn() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_cgate-mock"))
            .args(["--bind", "127.0.0.1:0"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut first = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut first)
            .unwrap();
        let port = first.trim().rsplit(':').next().unwrap().parse().unwrap();
        let errors = Arc::new(Mutex::new(String::new()));
        let capture = errors.clone();
        let stderr = child.stderr.take().unwrap();
        let logger = std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                capture.lock().unwrap().push_str(&format!("{line}\n"));
            }
        });
        Self {
            child,
            port,
            errors,
            logger: Some(logger),
        }
    }

    fn connect(&self) -> Session {
        let writer = TcpStream::connect(("127.0.0.1", self.port)).unwrap();
        writer
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        writer
            .set_write_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut session = Session {
            reader: BufReader::new(writer.try_clone().unwrap()),
            writer,
            tag: 0,
        };
        assert_eq!(session.line(), "201 Service ready\r\n");
        session
    }
}

impl Drop for Mock {
    fn drop(&mut self) {
        self.child.kill().ok();
        self.child.wait().ok();
        if let Some(logger) = self.logger.take() {
            logger.join().unwrap();
        }
    }
}

struct Session {
    reader: BufReader<TcpStream>,
    writer: TcpStream,
    tag: usize,
}
impl Session {
    fn line(&mut self) -> String {
        let mut line = String::new();
        assert_ne!(
            self.reader.read_line(&mut line).unwrap(),
            0,
            "unexpected EOF"
        );
        line
    }
    fn request(&mut self, command: &str) -> (u16, Vec<String>) {
        self.tag += 1;
        let tag = self.tag.to_string();
        writeln!(self.writer, "[{tag}] {command}").unwrap();
        self.reply(&tag)
    }
    fn reply(&mut self, tag: &str) -> (u16, Vec<String>) {
        let mut rows = Vec::new();
        loop {
            let line = self.line();
            let final_row = line.strip_prefix(&format!("[{tag}] ")).and_then(|body| {
                (body.as_bytes().get(3) == Some(&b' ')).then(|| body[..3].parse::<u16>().unwrap())
            });
            rows.push(line);
            if let Some(status) = final_row {
                return (status, rows);
            }
        }
    }
}

fn slow_subscriber_case(key: &str, reason: &str) {
    let v = vector();
    let mock = Mock::spawn();
    let mut slow = mock.connect();
    assert_eq!(slow.request("SESSION_ID TAG NONREADING").0, 200);
    assert_eq!(slow.request("EVENT e3s0c0").0, 200);
    if key == "slow_count" {
        slow.writer
            .write_all(b"[partial] FILE UPLOAD cancelled << END\nYWJj\n")
            .unwrap();
    }
    let mut producer = mock.connect();
    assert_eq!(producer.request("EVENT OFF").0, 200);
    let mut filtered = mock.connect();
    assert_eq!(filtered.request("EVENT e2s0c0").0, 200);
    assert!(producer
        .request("SESSION_ID ALL")
        .1
        .iter()
        .any(|row| row.contains("NONREADING")));
    let payload = "X".repeat(v[key]["payload_bytes"].as_u64().unwrap() as usize);
    let started = Instant::now();
    let mut worst = Duration::ZERO;
    for index in 0..v[key]["commands"].as_u64().unwrap() {
        let before = Instant::now();
        assert_eq!(
            producer
                .request(&format!("BROADCAST_EVENT SP {index} {payload}"))
                .0,
            200
        );
        worst = worst.max(before.elapsed());
        if index % 32 == 0 {
            let before = Instant::now();
            let (status, rows) = filtered.request("NOOP");
            assert_eq!(status, 200);
            assert_eq!(rows.len(), 1, "filtered events consume no queue budget");
            assert!(
                before.elapsed() < Duration::from_secs(2),
                "lagging client stalled filtered peer"
            );
        }
    }
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        let (_, rows) = producer.request("SESSION_ID ALL");
        if !rows.iter().any(|row| row.contains("NONREADING")) {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "overflow left a live session entry"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    assert!(
        worst < Duration::from_secs(2),
        "lagging client stalled an unrelated command"
    );
    println!(
        "{key}: total={:?}, worst producer receipt={worst:?}",
        started.elapsed()
    );
    let deadline = Instant::now() + Duration::from_secs(1);
    while !mock.errors.lock().unwrap().contains(reason) {
        assert!(
            Instant::now() < deadline,
            "missing explicit overflow diagnostic: {:?}",
            mock.errors.lock().unwrap()
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    assert!(mock
        .errors
        .lock()
        .unwrap()
        .contains("pending receipts are unconfirmed"));
    assert_eq!(producer.request("PROJECT NEW AFTER_OVERFLOW").0, 200);
    assert_eq!(producer.request("NOOP").0, 200);
    if key == "slow_count" {
        assert_eq!(producer.request("FILE DOWNLOAD cancelled").0, 408);
    }
    // The peer observes a buffered prefix followed by EOF/reset. No new
    // fabricated overflow status is inserted into an uncertain stream.
    let mut buffer = [0u8; 65536];
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        match slow.reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(_) => assert!(Instant::now() < deadline, "closed peer kept writing"),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::BrokenPipe
                ) =>
            {
                break
            }
            Err(error) => panic!("expected disconnect: {error}"),
        }
    }
    drop(slow);
}

#[test]
fn nonreading_subscriber_hits_count_cap_without_stalling_other_clients() {
    let v = vector();
    slow_subscriber_case(
        "slow_count",
        v["overflow"]["count_reason"].as_str().unwrap(),
    );
}

#[test]
fn nonreading_subscriber_hits_byte_cap_before_count_cap() {
    let v = vector();
    slow_subscriber_case("slow_bytes", v["overflow"]["byte_reason"].as_str().unwrap());
}

#[test]
fn continuous_fanout_preserves_source_order_and_cannot_starve_terminal_reply() {
    let v = vector();
    let mock = Mock::spawn();
    let mut subscriber = mock.connect();
    assert_eq!(subscriber.request("EVENT e3s0c0").0, 200);
    let mut producer = mock.connect();
    assert_eq!(producer.request("EVENT OFF").0, 200);
    let running = Arc::new(AtomicBool::new(true));
    let done = running.clone();
    let count = v["continuous"]["commands"].as_u64().unwrap();
    let payload = "Y".repeat(v["continuous"]["payload_bytes"].as_u64().unwrap() as usize);
    let publisher = std::thread::spawn(move || {
        for index in 0..count {
            assert_eq!(
                producer
                    .request(&format!(
                        "BROADCAST_EVENT SOURCE sequence={index} {payload}"
                    ))
                    .0,
                200
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        done.store(false, Ordering::SeqCst);
    });
    let mut seen = Vec::new();
    for _ in 0..v["continuous"]["poll_after"].as_u64().unwrap() {
        seen.push(subscriber.line());
    }
    let started = Instant::now();
    let (status, rows) = subscriber.request("NOOP");
    assert_eq!(status, 200);
    assert!(
        started.elapsed() < Duration::from_secs(v["continuous"]["reply_seconds"].as_u64().unwrap())
    );
    assert!(
        running.load(Ordering::SeqCst),
        "terminal arrived only after fanout stopped"
    );
    seen.extend(rows.into_iter().filter(|row| row.starts_with("#e#")));
    while seen.len() < count as usize {
        seen.push(subscriber.line());
    }
    publisher.join().unwrap();
    for (index, row) in seen.iter().enumerate() {
        assert!(
            row.contains(&format!(
                " 703 cmd5 - broadcast_event SOURCE sequence={index} "
            )),
            "wrong source/order: {row}"
        );
        assert!(row.ends_with("\r\n"));
    }
    let (status, rows) = subscriber.request("EVENT OFF");
    assert_eq!((status, rows.len()), (200, 1));
    assert_eq!(subscriber.request("EVENT").1, ["[4] 306 e0s0c0\r\n"]);
}

#[test]
fn command_events_xml_envelope_and_pipelined_terminal_remain_contiguous() {
    let v = vector();
    let mock = Mock::spawn();
    let mut session = mock.connect();
    for row in v["ordering"].as_array().unwrap().iter().take(2) {
        let (status, rows) = session.request(row["command"].as_str().unwrap());
        assert_eq!(status as u64, row["status"].as_u64().unwrap());
        assert!(rows[0].contains(row["event_contains"].as_str().unwrap()));
        assert!(rows
            .last()
            .unwrap()
            .ends_with(&format!("{}\r\n", row["terminal"].as_str().unwrap())));
    }
    session
        .writer
        .write_all(b"[xml] DBGETXML //ORDERED/11\r\n[after] NOOP\r\n")
        .unwrap();
    let (status, rows) = session.reply("xml");
    assert_eq!(status, 344);
    assert_eq!(rows.len(), 4);
    for (row, code) in rows
        .iter()
        .zip(v["ordering"][2]["wire_statuses"].as_array().unwrap())
    {
        assert!(row.starts_with(&format!("[xml] {}", code.as_u64().unwrap())));
    }
    assert!(rows[0].ends_with("\r\n"));
    assert!(rows[1].ends_with('\n') && !rows[1].ends_with("\r\n"));
    assert!(rows[2].ends_with("\r\n"));
    assert_eq!(session.reply("after").1, ["[after] 200 OK.\r\n"]);
}

#[test]
fn bounded_input_rejects_overlong_rows_resynchronizes_docs_and_preserves_eof_reply() {
    let v = vector();
    let mock = Mock::spawn();
    let mut overlong = mock.connect();
    overlong
        .writer
        .write_all(
            "Z".repeat(v["bounds"]["line_bytes"].as_u64().unwrap() as usize + 2)
                .as_bytes(),
        )
        .unwrap();
    assert_eq!(
        overlong.line(),
        format!("{}\r\n", v["input"]["overlong_command"].as_str().unwrap())
    );
    let mut eof = String::new();
    assert_eq!(overlong.reader.read_line(&mut eof).unwrap(), 0);
    let mut document = mock.connect();
    document
        .writer
        .write_all(b"[doc] FILE UPLOAD too-long << END\r\n")
        .unwrap();
    document
        .writer
        .write_all(
            "A".repeat(v["bounds"]["line_bytes"].as_u64().unwrap() as usize + 2)
                .as_bytes(),
        )
        .unwrap();
    document
        .writer
        .write_all(b"\r\nEND\r\n[next] NOOP\r\n")
        .unwrap();
    assert_eq!(
        document.reply("doc").1,
        [format!(
            "[doc] {}\r\n",
            v["input"]["overlong_document"].as_str().unwrap()
        )]
    );
    assert_eq!(document.reply("next").1, ["[next] 200 OK.\r\n"]);
    document
        .writer
        .write_all(b"[aggregate] FILE UPLOAD aggregate << END\n")
        .unwrap();
    let row = format!(
        "{}\n",
        "A".repeat(v["bounds"]["line_bytes"].as_u64().unwrap() as usize)
    );
    for _ in 0..v["bounds"]["document_bytes"].as_u64().unwrap()
        / v["bounds"]["line_bytes"].as_u64().unwrap()
    {
        document.writer.write_all(row.as_bytes()).unwrap();
    }
    document.writer.write_all(b"END\n[next2] NOOP\n").unwrap();
    assert_eq!(
        document.reply("aggregate").1,
        [format!(
            "[aggregate] {}\r\n",
            v["input"]["overlong_document"].as_str().unwrap()
        )]
    );
    assert_eq!(document.reply("next2").1, ["[next2] 200 OK.\r\n"]);
    document
        .writer
        .write_all(b"[eof] FILE UPLOAD partial << END\r\nYWJj\r\n")
        .unwrap();
    document.writer.shutdown(Shutdown::Write).unwrap();
    assert_eq!(
        document.reply("eof").1,
        [format!(
            "[eof] {}\r\n",
            v["input"]["truncated_document"].as_str().unwrap()
        )]
    );
    assert_eq!(document.reader.read_line(&mut eof).unwrap(), 0);
}

#[test]
fn large_multiline_file_response_is_one_bounded_batch_without_row_limit_regression() {
    let v = vector();
    let mock = Mock::spawn();
    let mut session = mock.connect();
    let size = v["input"]["large_base64_bytes"].as_u64().unwrap() as usize;
    session
        .writer
        .write_all(b"[upload] FILE UPLOAD large << END\n")
        .unwrap();
    for _ in 0..size / 65536 {
        session
            .writer
            .write_all(format!("{}\n", "A".repeat(65536)).as_bytes())
            .unwrap();
    }
    session.writer.write_all(b"END\n").unwrap();
    assert_eq!(session.reply("upload").0, 200);
    let (status, rows) = session.request("FILE DOWNLOAD large");
    assert_eq!(status, 346);
    let encoded: String = rows
        .iter()
        .filter_map(|row| row.strip_prefix("[1] 347-"))
        .map(|row| row.trim_end_matches(['\r', '\n']))
        .collect();
    assert_eq!(encoded.len(), size);
    assert!(encoded.bytes().all(|byte| byte == b'A'));
    assert!(rows.len() > v["bounds"]["outbound_batches"].as_u64().unwrap() as usize);
    assert_eq!(session.request("NOOP").0, 200);
}

#[test]
fn pipelined_input_stops_after_output_failure_and_reconnect_does_not_replay() {
    let v = vector();
    let mock = Mock::spawn();
    let mut seed = mock.connect();
    seed.writer
        .write_all(b"[upload] FILE UPLOAD large << END\n")
        .unwrap();
    for _ in 0..v["input"]["large_base64_bytes"].as_u64().unwrap() / 65536 {
        seed.writer
            .write_all(format!("{}\n", "A".repeat(65536)).as_bytes())
            .unwrap();
    }
    seed.writer.write_all(b"END\n").unwrap();
    assert_eq!(seed.reply("upload").0, 200);
    let mut slow = mock.connect();
    assert_eq!(slow.request("SESSION_ID TAG PIPELINED").0, 200);
    let mut pipeline = String::new();
    for index in 0..v["backlog"]["downloads"].as_u64().unwrap() {
        pipeline.push_str(&format!("[download{index}] FILE DOWNLOAD large\n"));
    }
    pipeline.push_str(&format!(
        "[tail] {}\n",
        v["backlog"]["tail_command"].as_str().unwrap()
    ));
    slow.writer.write_all(pipeline.as_bytes()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        if !seed
            .request("SESSION_ID ALL")
            .1
            .iter()
            .any(|row| row.contains("PIPELINED"))
        {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "pipelined failed connection not retired"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        seed.request(v["backlog"]["tail_readback"].as_str().unwrap())
            .0 as u64,
        v["backlog"]["readback_status"].as_u64().unwrap()
    );
    let mut fresh = mock.connect();
    assert_eq!(fresh.request("EVENT ON").0, 200);
    assert_eq!(fresh.request("NOOP").1, ["[2] 200 OK.\r\n"]);
    assert_eq!(
        fresh
            .request(v["backlog"]["tail_readback"].as_str().unwrap())
            .0,
        404
    );
    drop(slow);
}
