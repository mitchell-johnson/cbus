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
//! for a later trusted client. (c) missing cert/key files fail closed at
//! startup is covered by `cmqttd` `cgate_tls_config` unit tests.

use cbus_cgate::service::Service;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
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
