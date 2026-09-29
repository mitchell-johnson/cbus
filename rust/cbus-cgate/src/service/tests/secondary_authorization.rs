//! Replays of `native_cgate_secondary_authorization_probe.json`, the owned
//! C-Gate 3.4.0.2001 capture of event-port ACCESS admission and the LOGIN,
//! LOGOUT and live-ACCESS transition matrix. Native credentials were random
//! per capture and are redacted; these tests supply their own.

use super::*;
use crate::access::native_minimum_for;

fn capture() -> serde_json::Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../testdata/fixtures/native_cgate_secondary_authorization_probe.json"
    );
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn native_reply(value: &serde_json::Value) -> String {
    value
        .as_array()
        .and_then(|lines| lines.last())
        .and_then(serde_json::Value::as_str)
        .unwrap()
        .to_string()
}

fn untimestamped(line: &str) -> String {
    let (stamp, rest) = line.split_once(' ').unwrap();
    chrono::NaiveDateTime::parse_from_str(stamp, "%Y%m%d-%H%M%S%.3f").unwrap();
    rest.to_string()
}

async fn interface_line(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
) -> Option<String> {
    command_lines(reader, writer, "list", "ACCESS LIST")
        .await
        .iter()
        .find_map(|line| {
            let (_, entry) = line.split_once("line=")?;
            let (number, entry) = entry.split_once(' ')?;
            entry
                .starts_with("entry=interface ")
                .then(|| number.to_string())
        })
}

/// Read one event-port line, or `None` at EOF. Times out loudly.
async fn event_line(reader: &mut BufReader<TcpStream>) -> Option<String> {
    let mut line = String::new();
    let read = tokio::time::timeout(Duration::from_secs(5), reader.read_line(&mut line))
        .await
        .expect("event-port read timed out")
        .unwrap();
    (read != 0).then(|| line.trim_end_matches(['\r', '\n']).to_string())
}

#[tokio::test]
async fn event_port_admission_replays_native_live_access_levels() {
    let native = capture();
    let steps = native["event_admission"]["steps"].as_array().unwrap();
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let commands = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let command_address = commands.local_addr().unwrap();
    let events = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let event_address = events.local_addr().unwrap();
    let command_server = tokio::spawn(service.clone().serve(commands));
    let event_server = tokio::spawn(service.clone().serve_event_server(events));

    // Reproduce the capture's starting table: loopback interface at Program.
    let (mut admin_reader, mut admin_writer) = connect_command_session(command_address).await;
    let default_row = interface_line(&mut admin_reader, &mut admin_writer)
        .await
        .unwrap();
    for (tag, body) in [
        ("add", "ACCESS ADD interface 127.0.0.1 Program".to_string()),
        ("delete-default", format!("ACCESS DELETE {default_row}")),
    ] {
        assert_eq!(
            command_lines(&mut admin_reader, &mut admin_writer, tag, &body).await,
            [format!("[{tag}] 200 OK.")]
        );
    }
    let mut watcher = BufReader::new(TcpStream::connect(event_address).await.unwrap());

    for step in steps {
        let case = step["case"].as_str().unwrap();
        if let Some(line) = interface_line(&mut admin_reader, &mut admin_writer).await {
            command_lines(
                &mut admin_reader,
                &mut admin_writer,
                "delete",
                &format!("ACCESS DELETE {line}"),
            )
            .await;
        }
        if step.get("add").is_some() {
            let level = step["access_list"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(serde_json::Value::as_str)
                .find_map(|row| row.split("entry=interface 127.0.0.1 ").nth(1))
                .unwrap();
            command_lines(
                &mut admin_reader,
                &mut admin_writer,
                "add",
                &format!("ACCESS ADD interface 127.0.0.1 {level}"),
            )
            .await;
        }
        let mut probe = BufReader::new(TcpStream::connect(event_address).await.unwrap());
        let marker = format!("secondary-admission-{}", case.to_ascii_lowercase());
        let refused = step["new_event_peer"]["eof"].as_bool().unwrap();
        if refused {
            assert_eq!(event_line(&mut probe).await, None, "{case}: native closes");
        } else {
            // The accept task runs concurrently with the next command.
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        command_lines(
            &mut admin_reader,
            &mut admin_writer,
            "broadcast",
            &format!("BROADCAST_EVENT SP class {marker}"),
        )
        .await;
        if !refused {
            let line = event_line(&mut probe).await.unwrap();
            assert!(line.ends_with(&marker), "{case}: {line}");
        }

        // The pre-existing admitted peer is never re-evaluated and receives
        // native event 805 for each refused peer before the marker.
        let expected = step["existing_event_peer"]["rows"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(serde_json::Value::as_str)
            .filter(|row| row.starts_with("805 null - "))
            .map(str::to_string)
            .collect::<Vec<_>>();
        let mut observed = Vec::new();
        loop {
            let line = untimestamped(&event_line(&mut watcher).await.unwrap());
            if line.ends_with(&marker) {
                break;
            }
            if line.starts_with("805 ") {
                observed.push(line);
            }
        }
        assert_eq!(observed, expected, "{case}");

        // A new command peer receives the live level. cmqttd deliberately keeps
        // loopback reachable when no row admits it; native returns 421.
        let (mut reader, mut writer) = connect_command_session(command_address).await;
        let query = command_lines(&mut reader, &mut writer, "query", "LOGIN").await;
        let native_query = native_reply(&step["new_command_session"]["login_query"]);
        // The refused native socket read either EOF or a reset.
        if native_query.starts_with('<') {
            assert_eq!(query, ["[query] 210 Access level: Clipsal"], "{case}");
        } else {
            assert_eq!(query, [format!("[query] {native_query}")], "{case}");
        }
        assert_eq!(
            command_lines(&mut admin_reader, &mut admin_writer, "level", "LOGIN").await,
            [format!(
                "[level] {}",
                native_reply(&step["admin_level_after"])
            )]
        );
    }

    // EVENT subscription state belongs to the connection, not the level: a
    // LOGIN or LOGOUT swap leaves the captured e7s0c0 mode in place.
    let session = &native["login_matrix"]["session_matrix"];
    let (mut reader, mut writer) = connect_command_session(command_address).await;
    for (tag, body, key) in [
        ("subscribe", "EVENT e7s0c0", "event_subscribe"),
        ("before", "EVENT", "event_query_before"),
        ("logout", "LOGOUT", "logout_after_state"),
        ("after", "EVENT", "event_query_after_logout"),
    ] {
        let reply = command_lines(&mut reader, &mut writer, tag, body).await;
        // The final live interface row is Operate, as in the native matrix.
        let expected = native_reply(&session[key]);
        assert_eq!(reply, [format!("[{tag}] {expected}")], "{key}");
    }
    command_server.abort();
    event_server.abort();
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn unmatched_command_peer_is_refused_with_native_805_event() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut admin = ClientState::default();
    for command in ["ACCESS ADD interface 192.0.2.1 Operate", "ACCESS DELETE 1"] {
        assert_eq!(
            service
                .handle(&mut admin, &format!("[a] {command}"))
                .await
                .status,
            200
        );
    }
    let mut events = service.events.subscribe();
    let (server, client) = tokio::io::duplex(1024);
    let (read, write) = tokio::io::split(server);
    let peer: std::net::IpAddr = "198.51.100.7".parse().unwrap();
    service
        .connection_io(
            BufReader::new(read),
            write,
            "/198.51.100.7:4000".to_string(),
            "198.51.100.1".parse().unwrap(),
            peer,
            4000,
        )
        .await
        .unwrap();
    let mut reply = String::new();
    BufReader::new(client)
        .read_to_string(&mut reply)
        .await
        .unwrap();
    assert_eq!(reply, "421 Connection refused.\r\n");
    let event = events.recv().await.unwrap();
    let body = event.strip_prefix("#e# ").unwrap();
    let text = untimestamped(body);
    let (session, rest) = text
        .strip_prefix("805 cmd")
        .and_then(|text| text.split_once(' '))
        .unwrap();
    session.parse::<u64>().unwrap();
    assert_eq!(
        rest,
        "- Access control refused connection from /198.51.100.7"
    );
    std::fs::remove_file(path).unwrap();
}

/// Replay the captured session transitions through one handler. Each native
/// row is an exact single-line reply; the few selectors whose cmqttd reply is a
/// recorded deviation are asserted separately below.
#[tokio::test]
async fn login_transition_matrix_replays_native_capture() {
    let native = capture();
    let matrix = &native["login_matrix"];
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let loopback: std::net::IpAddr = "127.0.0.1".parse().unwrap();
    let peer = |_: &Arc<Service>| ClientState {
        local_address: Some(loopback),
        remote_address: Some(loopback),
        ..ClientState::default()
    };
    let levels = ["None", "Monitor", "Program", "Debug", "Clipsal", "Max"];
    let mut setup = ClientState::default();
    let mut commands = vec!["ACCESS ADD interface 127.0.0.1 Operate".to_string()];
    commands.extend(levels.iter().map(|level| {
        format!(
            "ACCESS ADD user sec-{} pw-{level} {level}",
            level.to_lowercase()
        )
    }));
    commands.push("ACCESS DELETE 1".to_string());
    for command in commands {
        assert_eq!(
            service
                .handle(&mut setup, &format!("[s] {command}"))
                .await
                .status,
            200,
            "{command}"
        );
    }
    let login = |level: &str| format!("LOGIN sec-{} pw-{level}", level.to_lowercase());

    let session = &matrix["session_matrix"];
    let mut s1 = peer(&service);
    let steps: Vec<(&str, String)> = vec![
        ("query_initial", "LOGIN".into()),
        (
            "wrong_password",
            "LOGIN sec-program not-the-password".into(),
        ),
        ("query_after_wrong_password", "LOGIN".into()),
        ("unknown_user", "LOGIN sec-unknown pw-Program".into()),
        ("username_case", "LOGIN SEC-PROGRAM pw-Program".into()),
        ("missing_password", "LOGIN sec-program".into()),
        ("query_after_failures", "LOGIN".into()),
        ("above_interface", login("Clipsal")),
        ("query_above_interface", "LOGIN".into()),
        ("repeated_downgrade", login("Monitor")),
        ("operate_command_at_monitor", "LOCK cgate".into()),
        ("none_user", login("None")),
        ("query_none_user", "LOGIN".into()),
        ("connect_command_at_none", "NOOP".into()),
        ("login_from_none", login("Program")),
        ("logout", "LOGOUT".into()),
        ("query_after_logout", "LOGIN".into()),
        ("logout_again", "LOGOUT".into()),
        ("login_after_state", login("Clipsal")),
        ("logout_after_state", "LOGOUT".into()),
    ];
    let mut mismatches = Vec::new();
    for (key, body) in steps {
        let reply = service.handle(&mut s1, &format!("[m] {body}")).await;
        let expected = native_reply(&session[key]);
        if reply.final_text != expected {
            mismatches.push(format!("{key}: {} != {expected}", reply.final_text));
        }
    }

    // Live ACCESS edits: existing sessions keep their connect-time or LOGIN
    // level; LOGOUT and reconnect read the live table.
    let live = &matrix["live_access"];
    let mut admin = peer(&service);
    let mut existing = peer(&service);
    let mut programmed = peer(&service);
    let mut reconnect = peer(&service);
    for (who, key, body) in [
        ("admin", "admin_login", login("Clipsal")),
        ("existing", "existing_query", "LOGIN".into()),
        ("programmed", "programmed_login", login("Program")),
        ("admin", "delete_interface", "ACCESS DELETE 1".into()),
        (
            "admin",
            "add_monitor_interface",
            "ACCESS ADD interface 127.0.0.1 Monitor".into(),
        ),
        ("existing", "existing_query_after_change", "LOGIN".into()),
        ("existing", "existing_logout", "LOGOUT".into()),
        ("reconnect", "reconnect_query", "LOGIN".into()),
        // The Clipsal view lists None, Monitor, Program, Debug, Clipsal and
        // then the re-added interface row; sec-program is line 3.
        ("admin", "delete_program_user", "ACCESS DELETE 3".into()),
        (
            "programmed",
            "programmed_query_after_delete",
            "LOGIN".into(),
        ),
        ("programmed", "programmed_logout", "LOGOUT".into()),
        (
            "programmed",
            "programmed_relogin_after_delete",
            login("Program"),
        ),
    ] {
        let client = match who {
            "admin" => &mut admin,
            "existing" => &mut existing,
            "programmed" => &mut programmed,
            _ => &mut reconnect,
        };
        let reply = service.handle(client, &format!("[l] {body}")).await;
        let expected = native_reply(&live[key]);
        if reply.final_text != expected {
            mismatches.push(format!("{key}: {} != {expected}", reply.final_text));
        }
    }
    assert!(mismatches.is_empty(), "{mismatches:#?}");
    std::fs::remove_file(path).unwrap();
}

/// Native advisory locks belong to the AccessContext that LOGIN or LOGOUT
/// replaces, so a swap releases them; relocking is never idempotent. cmqttd
/// keeps these statuses on a project object because it does not resolve the
/// root `cgate` object as a LOCK target.
#[tokio::test]
async fn advisory_lock_ownership_follows_native_login_swaps() {
    let native = capture();
    let matrix = &native["login_matrix"];
    let lock = &matrix["advisory_lock"];
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut setup = ClientState::default();
    assert_eq!(
        service
            .handle(&mut setup, "[s] ACCESS ADD user sec-program pw Program")
            .await
            .status,
        200
    );
    let mut owner = ClientState::default();
    let mut other = ClientState::default();
    for (owner_turn, body, key) in [
        (true, "LOCK //HARNESS", "lock"),
        (true, "LOCK //HARNESS", "relock_same_session"),
        (false, "LOCK //HARNESS", "other_session_lock"),
        (true, "LOGIN sec-program pw", "owner_login"),
        (true, "LOCK //HARNESS", "owner_relock_after_login"),
        (true, "UNLOCK //HARNESS", "owner_unlock_after_login"),
        (false, "LOCK //HARNESS", "other_lock_after_owner_login"),
        (false, "UNLOCK //HARNESS", "other_unlock"),
        (true, "LOGOUT", "owner_logout"),
        (true, "LOCK //HARNESS", "owner_lock_after_logout"),
    ] {
        let client = if owner_turn { &mut owner } else { &mut other };
        let reply = service.handle(client, &format!("[k] {body}")).await;
        // cmqttd releases at the swap itself: the earlier native run, whose
        // collector had already cleared the replaced context, shows the same.
        let row = if matches!(key, "owner_relock_after_login" | "owner_unlock_after_login") {
            &matrix["advisory_lock_earlier_run"]["rows"][key]
        } else {
            &lock[key]
        };
        let expected = native_reply(row);
        assert_eq!(
            reply.status.to_string(),
            expected[..3],
            "{key}: {} versus native {expected}",
            reply.final_text
        );
    }
    std::fs::remove_file(path).unwrap();
}

/// Per-parameter levels on the root object after the GET/SET handler floors.
#[tokio::test]
async fn cgate_object_parameter_levels_replay_native_capture() {
    let native = capture();
    let objects = native["login_matrix"]["cgate_object"].as_object().unwrap();
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut setup = ClientState::default();
    for level in objects.keys() {
        let body = format!("[s] ACCESS ADD user sec-{level} pw {level}");
        assert_eq!(service.handle(&mut setup, &body).await.status, 200);
    }
    for (level, rows) in objects {
        let mut client = ClientState::default();
        let login = service
            .handle(&mut client, &format!("[l] LOGIN sec-{level} pw"))
            .await;
        assert_eq!(
            login.final_text,
            format!("211 Access level set to: {level}")
        );
        for (key, body) in [
            ("get_kcount", "GET cgate KCount"),
            ("set_eventlevel", "SET cgate EventLevel 5"),
            ("set_state", "SET cgate State new"),
        ] {
            let reply = service.handle(&mut client, &format!("[o] {body}")).await;
            let expected = native_reply(&rows[key]);
            if expected.starts_with("420 ") {
                assert_eq!(reply.final_text, expected, "{level} {key}");
            } else if key == "get_kcount" {
                // The native counter value is internal and varies per child.
                assert!(expected.starts_with("300 cgate: KCount="), "{expected}");
                assert_eq!(reply.final_text, "300 cgate: KCount=0", "{level}");
            } else {
                // Recorded deviation: cmqttd admits the write level, then
                // reports that root-object SET is not implemented.
                assert_eq!(reply.status, 502, "{level} {key}: {}", reply.final_text);
            }
        }
    }
    std::fs::remove_file(path).unwrap();
}

/// Clipsal-floor command roots leave no 761/766 trace for other watchers.
#[tokio::test]
async fn clipsal_floor_roots_leave_no_command_trace_like_native() {
    let native = capture();
    let captured = &native["command_events"];
    let rows = captured["watcher_rows"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(serde_json::Value::as_str)
        .collect::<Vec<_>>();
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(service.clone().serve(listener));
    let (mut watcher, mut watcher_writer) = connect_command_session(address).await;
    assert_eq!(
        command_lines(&mut watcher, &mut watcher_writer, "mode", "EVENT e9s0c0").await,
        ["[mode] 200 OK."]
    );
    let (mut actor, mut actor_writer) = connect_command_session(address).await;
    let commands = captured["commands"].as_array().unwrap();
    for (index, body) in commands
        .iter()
        .filter_map(serde_json::Value::as_str)
        .enumerate()
    {
        if body == "LOGIN" {
            continue;
        }
        let tag = format!("c{index}");
        command_lines(&mut actor, &mut actor_writer, &tag, body).await;
        let traced = rows
            .iter()
            .any(|row| row.ends_with(&format!("] {body}")) && row.starts_with("761 "));
        assert_eq!(!traced, native_hides_command_trace(body), "{body}");
    }
    command_lines(&mut actor, &mut actor_writer, "end", "NOOP").await;
    let mut seen = Vec::new();
    loop {
        let mut line = String::new();
        let read = tokio::time::timeout(Duration::from_secs(5), watcher.read_line(&mut line)).await;
        assert!(read.is_ok(), "no end marker: {seen:#?}");
        if line.contains(" 761 ") || line.contains(" 766 ") {
            seen.push(line.trim_end().to_string());
        }
        if line.contains("Command: [end] NOOP") {
            break;
        }
    }
    for body in ["ACCESS LIST", "LOG", "PP LIST_LOCK"] {
        assert!(
            !seen.iter().any(|line| line.contains(&format!("] {body}"))),
            "{body}: {seen:#?}"
        );
    }
    for body in ["NOOP", "EVENT", "CONFIG GET cgate-name"] {
        assert!(
            seen.iter().any(|line| line.ends_with(&format!("] {body}"))),
            "{body}: {seen:#?}"
        );
    }
    server.abort();
    std::fs::remove_file(path).unwrap();
}

/// Dispositions for the eleven inventory paths without a native handler-entry
/// gradient: six take a documented cmqttd floor, five keep native no-floor
/// semantics. Invocations stop at argument validation, before PCI I/O.
#[tokio::test]
async fn unobserved_paths_keep_documented_dispositions() {
    let native = capture();
    // Native registers no fresh-child ACCESSCONTROL root: 400 at every role.
    for (role, row) in native["access_control_roles"]["roles"].as_object().unwrap() {
        for reply in row["replies"].as_object().unwrap().values() {
            assert_eq!(reply, "400 Syntax Error.", "{role}");
        }
    }
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let levels = [
        CgateAccessLevel::None,
        CgateAccessLevel::Connect,
        CgateAccessLevel::Monitor,
        CgateAccessLevel::Operate,
        CgateAccessLevel::Admin,
        CgateAccessLevel::Program,
        CgateAccessLevel::Max,
    ];
    let mut setup = ClientState::default();
    for level in levels {
        let body = format!("[s] ACCESS ADD user u-{0} pw {0}", level.name());
        assert_eq!(service.handle(&mut setup, &body).await.status, 200);
    }
    let floors = [
        ("ACCESS_CONTROL CLOSE", CgateAccessLevel::Operate),
        ("ACCESSCONTROL LOCK", CgateAccessLevel::Operate),
        ("UNIT IDENTIFY", CgateAccessLevel::Operate),
        ("UNIT READMEM", CgateAccessLevel::Program),
        ("CMQTT LABELS", CgateAccessLevel::Monitor),
        ("CMQTT CAPABILITIES", CgateAccessLevel::Connect),
    ];
    for level in levels {
        let mut client = ClientState::default();
        let login = format!("[l] LOGIN u-{0} pw", level.name());
        assert_eq!(service.handle(&mut client, &login).await.status, 211);
        for (body, floor) in floors {
            let upper = body
                .split_whitespace()
                .map(str::to_string)
                .collect::<Vec<_>>();
            assert_eq!(command_minimum_for(&upper), Some(floor), "{body}");
            assert_eq!(
                native_minimum_for(&upper),
                None,
                "{body} has no native floor"
            );
            let reply = service.handle(&mut client, &format!("[f] {body}")).await;
            if level < floor {
                assert_eq!(
                    reply.final_text, "420 Access denied.",
                    "{body} at {level:?}"
                );
            } else {
                assert_ne!(
                    reply.status, 420,
                    "{body} at {level:?}: {}",
                    reply.final_text
                );
            }
        }
        // Parser-level forms and CONFIRM without a pending SHUTDOWN answer
        // alike at every role, as the native sweep recorded.
        for body in ["# comment", "// comment", "CONFIRM"] {
            let reply = service.handle(&mut client, &format!("[p] {body}")).await;
            assert_eq!(
                reply.status, 400,
                "{body} at {level:?}: {}",
                reply.final_text
            );
        }
        // LOGIN and LOGOUT bypass the handler gate even at None.
        assert_eq!(
            service.handle(&mut client, "[q] LOGIN").await.final_text,
            format!("210 Access level: {}", level.name())
        );
        assert_eq!(service.handle(&mut client, "[o] LOGOUT").await.status, 211);
    }
    std::fs::remove_file(path).unwrap();
}

/// Exposed object methods keep their source-declared level after DO's
/// Operate handler floor, so DO cannot reach NET UNRAVEL or SYNC below the
/// level those operations need. Denials occur before any PCI I/O.
#[tokio::test]
async fn do_methods_apply_source_declared_levels_before_dispatch() {
    let path = state_path();
    let (pci, _remote) = pci();
    let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
    let mut setup = ClientState::default();
    for level in ["Operate", "Admin"] {
        let body = format!("[s] ACCESS ADD user u-{level} pw {level}");
        assert_eq!(service.handle(&mut setup, &body).await.status, 200);
    }
    for (level, denied) in [
        (
            "Operate",
            &["SYNC", "PSYNC", "UNRAVEL", "FACTORYDEFAULT"][..],
        ),
        ("Admin", &["UNRAVEL", "FACTORYDEFAULT"][..]),
    ] {
        let mut client = ClientState::default();
        let login = format!("[l] LOGIN u-{level} pw");
        assert_eq!(service.handle(&mut client, &login).await.status, 211);
        for method in denied {
            let reply = service
                .handle(&mut client, &format!("[d] DO //HARNESS/254 {method}"))
                .await;
            assert_eq!(
                reply.final_text,
                "420 Access denied: //HARNESS/254 (Insufficient access level to run method)",
                "{method} at {level}"
            );
        }
        let unknown = service
            .handle(&mut client, "[u] DO //HARNESS/254 NoSuchMethod")
            .await;
        assert_eq!(unknown.status, 402, "{level}");
    }
    std::fs::remove_file(path).unwrap();
}
