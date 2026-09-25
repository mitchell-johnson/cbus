//! P4b RED: TLS transport for the embedded C-Gate listener.
//!
//! Fixtures are committed TEST-ONLY throwaway keys
//! (`testdata/fixtures/cgate-tls-test-*`); never trust or deploy them.
//! Provenance: `openssl req -x509 -newkey rsa:2048 -days 3650 -nodes
//! -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1,DNS:localhost`.
//!
//! Covers: (a) TLS handshake + NOOP round-trip over TLS on a loopback
//! listener; (b) the plaintext `serve` path is unchanged; (d) a client
//! with an untrusted cert fails the handshake while the server stays up
//! for a later trusted client; (e) QUIT and EXIT flush their exact 204 reply
//! before the TLS connection reaches EOF. (c) missing cert/key files fail
//! closed at startup is covered by `cmqttd` `cgate_tls_config` unit tests.

use cbus_cgate::service::Service;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../testdata/fixtures")
        .join(name)
}

fn state_path() -> PathBuf {
    static ID: AtomicU64 = AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "cgate-tls-test-{}-{}.json",
        std::process::id(),
        ID.fetch_add(1, Ordering::Relaxed)
    ))
}

/// Service with a scripted/dummy PCI, mirroring `service::tests::pci()`.
fn test_service() -> (Arc<Service>, tokio::io::DuplexStream, PathBuf) {
    let xml = std::fs::read_to_string(fixture("project.xml")).expect("project fixture");
    let (client, remote) = tokio::io::duplex(8192);
    let (rd, wr) = tokio::io::split(client);
    let (tx, _) = tokio::sync::mpsc::unbounded_channel();
    let pci = cbus_transport::pci::PciClient::new(Box::new(rd), Box::new(wr), tx);
    let state = state_path();
    let service = Service::new(&xml, None, state.clone(), pci, None).expect("service");
    (service, remote, state)
}

fn test_server_config() -> Arc<rustls::ServerConfig> {
    let cert_data = std::fs::read(fixture("cgate-tls-test-cert.pem")).expect("test cert");
    let key_data = std::fs::read(fixture("cgate-tls-test-key.pem")).expect("test key");
    let certs: Vec<_> = rustls_pemfile::certs(&mut cert_data.as_slice())
        .collect::<Result<_, _>>()
        .expect("parse test cert");
    assert!(!certs.is_empty());
    let key = rustls_pemfile::private_key(&mut key_data.as_slice())
        .expect("parse test key")
        .expect("test key present");
    Arc::new(
        rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(certs, key)
            .expect("test server config"),
    )
}

fn trusted_roots() -> Arc<rustls::RootCertStore> {
    let cert_data = std::fs::read(fixture("cgate-tls-test-cert.pem")).expect("test cert");
    let certs: Vec<_> = rustls_pemfile::certs(&mut cert_data.as_slice())
        .collect::<Result<_, _>>()
        .expect("parse test cert");
    let mut roots = rustls::RootCertStore::empty();
    for cert in certs {
        roots.add(cert).expect("trust test cert");
    }
    Arc::new(roots)
}

fn client_config(roots: Arc<rustls::RootCertStore>) -> Arc<rustls::ClientConfig> {
    Arc::new(
        rustls::ClientConfig::builder()
            .with_root_certificates((*roots).clone())
            .with_no_client_auth(),
    )
}

async fn tls_connect(
    port: u16,
    config: Arc<rustls::ClientConfig>,
) -> tokio::io::Result<tokio_rustls::client::TlsStream<TcpStream>> {
    let connector = tokio_rustls::TlsConnector::from(config);
    let stream = TcpStream::connect(("127.0.0.1", port)).await?;
    let name = rustls::pki_types::ServerName::try_from("127.0.0.1")
        .expect("server name")
        .to_owned();
    connector.connect(name, stream).await
}

async fn read_greeting<R: tokio::io::AsyncBufRead + Unpin>(reader: &mut R) -> String {
    let mut line = String::new();
    reader.read_line(&mut line).await.expect("greeting");
    line.trim().to_string()
}

/// Send one tagged command; return the final status code.
async fn command<R, W>(reader: &mut R, writer: &mut W, tag: &str, body: &str) -> u16
where
    R: tokio::io::AsyncBufRead + Unpin,
    W: tokio::io::AsyncWrite + Unpin,
{
    writer
        .write_all(format!("[{tag}] {body}\n").as_bytes())
        .await
        .expect("write command");
    loop {
        let mut line = String::new();
        reader.read_line(&mut line).await.expect("reply");
        let line = line.trim().to_string();
        if cbus_cgate::is_event_line(&line) {
            continue;
        }
        let payload = line
            .strip_prefix(&format!("[{tag}] "))
            .unwrap_or_else(|| panic!("missing tag in {line:?}"));
        let code: u16 = payload[..3].parse().expect("status code");
        if payload.as_bytes()[3] == b' ' {
            return code;
        }
    }
}

#[tokio::test]
async fn tls_handshake_and_noop_round_trip() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let running = service.clone();
    let tls = test_server_config();
    tokio::spawn(async move {
        running.serve_tls(listener, tls).await.expect("serve_tls");
    });
    let stream = tls_connect(port, client_config(trusted_roots()))
        .await
        .expect("TLS handshake");
    let (rd, wr) = tokio::io::split(stream);
    let mut reader = BufReader::new(rd);
    let mut writer = wr;
    assert!(read_greeting(&mut reader).await.starts_with("201 "));
    assert_eq!(command(&mut reader, &mut writer, "1", "NOOP").await, 200);
    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn tls_quit_and_exit_flush_reply_before_eof() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let running = service.clone();
    let tls = test_server_config();
    tokio::spawn(async move {
        running.serve_tls(listener, tls).await.expect("serve_tls");
    });

    for (tag, verb) in [("q", "QUIT"), ("e", "EXIT")] {
        let stream = tls_connect(port, client_config(trusted_roots()))
            .await
            .expect("TLS handshake");
        let (rd, mut writer) = tokio::io::split(stream);
        let mut reader = BufReader::new(rd);
        assert!(read_greeting(&mut reader).await.starts_with("201 "));
        writer
            .write_all(format!("[{tag}] {verb}\r\n").as_bytes())
            .await
            .expect("write close command");

        let mut reply = String::new();
        tokio::time::timeout(Duration::from_secs(3), reader.read_line(&mut reply))
            .await
            .expect("closing reply deadline")
            .expect("closing reply");
        assert_eq!(reply, format!("[{tag}] 204 Closing connection.\r\n"));

        let mut tail = String::new();
        let read = tokio::time::timeout(Duration::from_secs(3), reader.read_line(&mut tail))
            .await
            .expect("TLS EOF deadline")
            .expect("TLS EOF");
        assert_eq!(read, 0, "{verb} left TLS connection open: {tail:?}");
    }

    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn plaintext_serve_path_unchanged() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    tokio::spawn(async move {
        service.serve(listener).await.expect("serve");
    });
    let stream = TcpStream::connect(("127.0.0.1", port))
        .await
        .expect("connect");
    let (rd, wr) = stream.into_split();
    let mut reader = BufReader::new(rd);
    let mut writer = wr;
    assert!(read_greeting(&mut reader).await.starts_with("201 "));
    assert_eq!(command(&mut reader, &mut writer, "1", "NOOP").await, 200);
    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn tls_handshake_with_untrusted_cert_fails_but_server_stays_up() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let running = service.clone();
    let tls = test_server_config();
    tokio::spawn(async move {
        running.serve_tls(listener, tls).await.expect("serve_tls");
    });
    // Empty trust store: the handshake must fail.
    let empty = Arc::new(rustls::RootCertStore::empty());
    assert!(tls_connect(port, client_config(empty)).await.is_err());
    // The server stays up: a trusted client still gets a NOOP round-trip.
    let stream = tls_connect(port, client_config(trusted_roots()))
        .await
        .expect("TLS handshake after failed attempt");
    let (rd, wr) = tokio::io::split(stream);
    let mut reader = BufReader::new(rd);
    let mut writer = wr;
    assert!(read_greeting(&mut reader).await.starts_with("201 "));
    assert_eq!(command(&mut reader, &mut writer, "1", "NOOP").await, 200);
    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn tls_stalled_handshake_times_out_and_listener_stays_up() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let running = service.clone();
    let tls = test_server_config();
    tokio::spawn(async move {
        running
            .serve_tls_with_timeout(listener, tls, Duration::from_millis(200))
            .await
            .expect("serve_tls");
    });
    let start = Instant::now();
    let mut stream = TcpStream::connect(("127.0.0.1", port))
        .await
        .expect("connect");
    // Send nothing: the server must drop/close within the bound.
    // Ceiling is 2s = 10x the 200ms handshake bound: generous enough to stay
    // flake-safe on loaded CI while still proving the timeout fires promptly
    // instead of lingering unbounded with no handshake bound.
    let mut buf = [0u8; 64];
    let n = tokio::time::timeout(Duration::from_secs(2), stream.read(&mut buf))
        .await
        .expect("server closes stalled handshake within ceiling")
        .expect("read stalled handshake");
    let elapsed = start.elapsed();
    assert_eq!(n, 0, "stalled pre-handshake connection must be terminated");
    assert!(
        elapsed < Duration::from_secs(2),
        "stalled handshake took {elapsed:?}, exceeding ceiling"
    );
    // The 64-slot permit must be freed and the listener still serving: a
    // second connection completes a full TLS handshake plus NOOP round-trip.
    let stream = tls_connect(port, client_config(trusted_roots()))
        .await
        .expect("TLS handshake after stalled attempt");
    let (rd, wr) = tokio::io::split(stream);
    let mut reader = BufReader::new(rd);
    let mut writer = wr;
    assert!(read_greeting(&mut reader).await.starts_with("201 "));
    assert_eq!(command(&mut reader, &mut writer, "1", "NOOP").await, 200);
    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn plaintext_client_to_tls_port_gets_no_greeting() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let running = service.clone();
    let tls = test_server_config();
    tokio::spawn(async move {
        running.serve_tls(listener, tls).await.expect("serve_tls");
    });
    let stream = TcpStream::connect(("127.0.0.1", port))
        .await
        .expect("connect");
    let (rd, wr) = stream.into_split();
    let mut reader = BufReader::new(rd);
    let mut writer = wr;
    writer.write_all(b"[1] NOOP\n").await.expect("write");
    // Garbage fails the handshake fast: the server answers with a TLS
    // alert (never a C-Gate greeting) and then drops the connection.
    let mut line = String::new();
    match tokio::time::timeout(Duration::from_secs(3), reader.read_line(&mut line)).await {
        Ok(Ok(_)) => assert!(
            !line.trim_start().starts_with("201 "),
            "plaintext client must not receive a C-Gate greeting from a TLS port"
        ),
        Ok(Err(_)) => {} // reset / non-UTF8 alert bytes: also no greeting
        Err(_) => panic!("TLS server never answered plaintext garbage; handshake must fail fast"),
    }
    // The failed-handshake connection must then close (EOF or reset).
    let mut buf = [0u8; 64];
    match tokio::time::timeout(Duration::from_secs(3), reader.read(&mut buf)).await {
        Ok(Ok(0)) => {}
        Ok(Ok(n)) => panic!("expected close after failed handshake, got {n} more bytes"),
        Ok(Err(_)) => {} // RST is also a close
        Err(_) => panic!("failed-handshake connection stayed open"),
    }
    std::fs::remove_file(state).ok();
}

#[tokio::test]
async fn tls_client_to_plaintext_port_fails_handshake() {
    let (service, _remote, state) = test_service();
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    tokio::spawn(async move {
        service.serve(listener).await.expect("serve");
    });
    let result = tls_connect(port, client_config(trusted_roots())).await;
    assert!(
        result.is_err(),
        "TLS handshake against a plaintext port must fail"
    );
    std::fs::remove_file(state).ok();
}
