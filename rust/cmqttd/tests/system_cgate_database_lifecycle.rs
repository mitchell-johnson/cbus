//! Real-daemon coverage for durable legacy database creation/copy/clear.

mod util;

use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

async fn connect(
    sys: &System,
) -> (
    BufReader<tokio::net::tcp::OwnedReadHalf>,
    tokio::net::tcp::OwnedWriteHalf,
) {
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
    assert_eq!(greeting, "201 cmqttd C-Gate service ready\r\n");
    (reader, writer)
}

async fn command(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    text: &str,
) -> Vec<String> {
    writer
        .write_all(format!("[{tag}] {text}\r\n").as_bytes())
        .await
        .unwrap();
    let prefix = format!("[{tag}] ");
    let mut reply = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']).to_string();
        let payload = line.strip_prefix(&prefix).expect("tagged C-Gate reply");
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(payload.to_string());
        if complete {
            return reply;
        }
    }
}

fn oid(reply: &[String]) -> String {
    reply
        .last()
        .and_then(|line| line.strip_prefix("301 OID="))
        .expect("301 OID reply")
        .to_string()
}

fn options(state: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

#[tokio::test]
async fn database_add_copy_and_new_are_atomic_and_durable_across_daemon_restart() {
    let state = cbus_test_support::proc::temp_path("cgate-database-lifecycle.json");
    let mut sys = start_with(options(&state)).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;

    for (tag, text) in [
        ("1", "PROJECT NEW AUX"),
        ("2", "DBCREATENET 1 Auxiliary Cni loopback"),
        ("3", "DBADDSAFE //AUX/1 Unit 20 Original"),
        ("4", "DBSET //AUX/1/p/20/UnitType KEYM4"),
    ] {
        assert!(
            command(&mut reader, &mut writer, tag, text)
                .await
                .last()
                .is_some_and(|line| line.starts_with("200") || line.starts_with("301")),
            "{text}"
        );
    }
    let pending = oid(&command(&mut reader, &mut writer, "5", "DBADD //AUX/1 Unit").await);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "6",
            &format!("DBSET !{pending}/UnitType RELAY4"),
        )
        .await,
        ["200 OK."]
    );
    let copied = oid(&command(
        &mut reader,
        &mut writer,
        "7",
        "DBCOPY //AUX/1/p/20 //AUX/1 trailing",
    )
    .await);
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "8",
            &format!("DBGET !{copied}/Address"),
        )
        .await,
        ["401 Bad object or device ID: Object is null"]
    );
    drop(reader);
    drop(writer);
    drop(sys);

    sys = start_with(options(&state)).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;
    assert_eq!(
        command(&mut reader, &mut writer, "9", "PROJECT USE AUX").await,
        ["200 OK."]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "10",
            &format!("DBGET !{pending}/UnitType"),
        )
        .await,
        [format!("342 !{pending}/UnitType=RELAY4")]
    );
    assert_eq!(
        command(
            &mut reader,
            &mut writer,
            "11",
            &format!("DBGET !{copied}/UnitType"),
        )
        .await,
        [format!("342 !{copied}/UnitType=KEYM4")]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "12", "DBNEW trailing").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "13", "DBTAGLIST").await,
        ["342 AUX/TagName=AUX"]
    );
    drop(reader);
    drop(writer);
    drop(sys);

    sys = start_with(options(&state)).await;
    wait_started(&sys).await;
    let (mut reader, mut writer) = connect(&sys).await;
    assert_eq!(
        command(&mut reader, &mut writer, "14", "PROJECT USE AUX").await,
        ["200 OK."]
    );
    assert_eq!(
        command(&mut reader, &mut writer, "15", "DBTAGLIST").await,
        ["342 AUX/TagName=AUX"]
    );
    drop(sys);
    std::fs::remove_file(state).unwrap();
}
