//! Real cmqttd process: the complete maintained C-Gate FILE family provides
//! authenticated, atomic and durable binary storage without PCI or host-file
//! access.

mod util;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::TcpStream,
};
use util::*;

const TOKEN: &str = "throwaway-file-system-token-0123456789abcdef";

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
    response(reader, tag).await
}

async fn document(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    writer: &mut tokio::net::tcp::OwnedWriteHalf,
    tag: &str,
    text: &str,
    body: &str,
) -> Vec<String> {
    let delimiter = format!("FILE_END_{tag}");
    let line_end = if body.ends_with('\n') { "" } else { "\r\n" };
    writer
        .write_all(
            format!("[{tag}] {text} << {delimiter}\r\n{body}{line_end}{delimiter}\r\n").as_bytes(),
        )
        .await
        .unwrap();
    response(reader, tag).await
}

async fn response(
    reader: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
    tag: &str,
) -> Vec<String> {
    let prefix = format!("[{tag}] ");
    let mut reply = Vec::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).await.unwrap(), 0);
        let line = line.trim_end_matches(['\r', '\n']);
        let payload = line
            .strip_prefix(&prefix)
            .unwrap_or_else(|| panic!("expected {prefix:?}, got {line:?}"));
        let complete = payload.as_bytes().get(3) == Some(&b' ');
        reply.push(payload.to_string());
        if complete {
            return reply;
        }
    }
}

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

fn options(state: &std::path::Path, token: &std::path::Path) -> Options {
    Options {
        extra: vec![
            "--cgate-bind".into(),
            "127.0.0.1:0".into(),
            "--cgate-state".into(),
            state.to_string_lossy().into_owned(),
            "--cgate-auth-file".into(),
            token.to_string_lossy().into_owned(),
        ],
        ..Default::default()
    }
}

#[tokio::test]
async fn file_family_is_binary_authenticated_durable_and_never_touches_pci() {
    let state = cbus_test_support::proc::temp_path("cgate-file.json");
    let token = cbus_test_support::proc::temp_path("cgate-file.token");
    std::fs::write(&token, format!("{TOKEN}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&token, std::fs::Permissions::from_mode(0o600)).unwrap();
    }

    let bytes = (0_u8..=255).collect::<Vec<_>>();
    let encoded = STANDARD.encode(&bytes);
    {
        let mut sys = start_with(options(&state, &token)).await;
        wait_started(&sys).await;
        let (mut reader, mut writer) = connect(&sys).await;

        let help = [
            "101-Help: FILE commands:",
            "101-Help:  FILE ? Help for these commands",
            "101-Help:  FILE DELETE - Remove a file or directory from the server",
            "101-Help:  FILE DIR - Return a list of directory contents for the given directory",
            "101-Help:  FILE DOWNLOAD - Download a copy of a file as a base-64 encoded chunk of data",
            "101-Help:  FILE LS - Return a list of directory contents for the given directory",
            "101-Help:  FILE MKDIR - Return a list of directory contents for the given directory",
            "101-Help:  FILE SHA256 - Calculate an SHA256 hash of a project file on the server",
            "101 Help:  FILE UPLOAD - Upload  a file to the server as a base-64 encoded chunk of data ",
        ];
        assert_eq!(
            command(&mut reader, &mut writer, "help", "FILE").await,
            help
        );
        assert_eq!(
            command(&mut reader, &mut writer, "root", "FILE DIR").await,
            ["304 directory=\"cmqttd:/\" files=0"]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "locked", "FILE MKDIR fixtures").await,
            ["420 LOGIN required"]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "login", &format!("LOGIN {TOKEN}")).await,
            ["200 OK"]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "mkdir",
                "FILE MKDIR fixtures/deep"
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "project-mkdir",
                "FILE MKDIR %HARNESS%/exports",
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            document(
                &mut reader,
                &mut writer,
                "project-upload",
                "FILE UPLOAD %HARNESS%/exports/data.bin",
                "cHJvamVjdA==",
            )
            .await,
            ["200 OK."]
        );
        let project_listing = command(
            &mut reader,
            &mut writer,
            "project-dir",
            "FILE DIR %HARNESS%/exports",
        )
        .await;
        assert_eq!(project_listing.len(), 2);
        assert_eq!(
            project_listing[0],
            "304-directory=\"cmqttd-project://HARNESS/exports\" files=1"
        );
        assert!(project_listing[1].starts_with("305 name=\"data.bin\" size=7 modified="));

        let frames_before = sys
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count();
        assert_eq!(
            document(
                &mut reader,
                &mut writer,
                "upload",
                "FILE UPLOAD fixtures/deep/all.bin",
                &encoded,
            )
            .await,
            ["200 OK."]
        );
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "hash",
                "FILE SHA256 fixtures/deep/all.bin",
            )
            .await,
            ["302 File=fixtures/deep/all.bin SHA256Hash=40aff2e9d2d8922e47afd4648e6967497158785fbd1da870e7110266bf944880"]
        );
        let download = command(
            &mut reader,
            &mut writer,
            "download",
            "FILE DOWNLOAD fixtures/deep/all.bin",
        )
        .await;
        assert_eq!(
            download.first().unwrap(),
            "345-Start file download for file: fixtures/deep/all.bin"
        );
        assert_eq!(download.last().unwrap(), "346 End file download");
        let decoded = STANDARD
            .decode(
                download[1..download.len() - 1]
                    .iter()
                    .map(|line| line.strip_prefix("347-").unwrap())
                    .collect::<String>(),
            )
            .unwrap();
        assert_eq!(decoded, bytes);
        assert!(download[1..download.len() - 1]
            .iter()
            .all(|line| line.len() <= 80));

        let listing = command(&mut reader, &mut writer, "dir", "FILE LS fixtures/deep").await;
        assert_eq!(listing.len(), 2);
        assert_eq!(
            listing[0],
            "304-directory=\"cmqttd:/fixtures/deep\" files=1"
        );
        assert!(listing[1].starts_with("305 name=\"all.bin\" size=256 modified="));

        assert_eq!(
            document(
                &mut reader,
                &mut writer,
                "replace",
                "FILE UPLOAD fixtures/deep/all.bin",
                "cmVwbGFjZWQ=",
            )
            .await,
            ["200 OK."]
        );
        let hashes = command(
            &mut reader,
            &mut writer,
            "hashes",
            "FILE SHA256 fixtures/deep/all.bin fixtures/deep/all.bin.0",
        )
        .await;
        assert_eq!(hashes[0], "302-File=fixtures/deep/all.bin SHA256Hash=6c1aa50442a93e42c0eb2907cf4e017cd19547891fa190f3ea473582b0479290");
        assert_eq!(hashes[1], "302 File=fixtures/deep/all.bin.0 SHA256Hash=40aff2e9d2d8922e47afd4648e6967497158785fbd1da870e7110266bf944880");
        assert_eq!(
            command(
                &mut reader,
                &mut writer,
                "nonempty",
                "FILE DELETE fixtures/deep"
            )
            .await,
            ["408 Operation failed: Delete failed"]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "escape", "FILE DIR ../private").await,
            ["408 Operation failed: Unable to read directory: Illegal path element in filename ../private"]
        );
        assert_eq!(
            document(
                &mut reader,
                &mut writer,
                "bad64",
                "FILE UPLOAD fixtures/deep/bad.bin",
                "%%%",
            )
            .await,
            ["408 Operation failed: Invalid character in Base64 data."]
        );
        assert_eq!(
            command(&mut reader, &mut writer, "alive", "FILE SHA256 fixtures/deep/all.bin").await,
            ["302 File=fixtures/deep/all.bin SHA256Hash=6c1aa50442a93e42c0eb2907cf4e017cd19547891fa190f3ea473582b0479290"]
        );
        let frames_after = sys
            .pci
            .frames()
            .iter()
            .filter(|frame| !is_status_request(&frame.payload))
            .count();
        assert_eq!(frames_after, frames_before);

        let caps = command(&mut reader, &mut writer, "caps", "CMQTT CAPABILITIES").await;
        let caps: serde_json::Value =
            serde_json::from_str(caps[0].strip_prefix("200-").unwrap()).unwrap();
        assert_eq!(caps["file_commands"].as_array().unwrap().len(), 7);
        assert_eq!(caps["file_storage"], "cmqttd-json");
        assert_eq!(caps["file_host_filesystem"], false);
        assert!(sys.daemon.is_running());
    }

    // The byte content and native replacement backup survive a real daemon
    // restart, while reads remain open under the optional LOGIN gate.
    {
        let mut sys = start_with(options(&state, &token)).await;
        wait_started(&sys).await;
        let (mut reader, mut writer) = connect(&sys).await;
        let hashes = command(
            &mut reader,
            &mut writer,
            "restart",
            "FILE SHA256 fixtures/deep/all.bin fixtures/deep/all.bin.0",
        )
        .await;
        assert_eq!(hashes.len(), 2);
        assert!(
            hashes[0].contains("6c1aa50442a93e42c0eb2907cf4e017cd19547891fa190f3ea473582b0479290")
        );
        assert!(
            hashes[1].contains("40aff2e9d2d8922e47afd4648e6967497158785fbd1da870e7110266bf944880")
        );
        assert!(sys.daemon.is_running());
    }

    std::fs::remove_file(state).unwrap();
    std::fs::remove_file(token).unwrap();
}
