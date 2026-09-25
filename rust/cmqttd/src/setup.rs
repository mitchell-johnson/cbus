//! Startup plumbing for cmqttd: logging, project-file labels, C-Bus
//! endpoint selection and MQTT/TLS configuration. Everything here runs
//! before the daemon's event loops; failures print a message and exit.

use crate::cli::Options;
use cbus_mqtt::cbz::read_cbz_labels;
use cbus_mqtt::discovery::AppLabels;
use cbus_transport::conn::Endpoint;
use rumqttc::{MqttOptions, Transport};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

pub fn init_logging(opts: &Options) {
    let level = if opts.debug {
        "debug"
    } else {
        match opts.verbosity.as_str() {
            "DEBUG" => "debug",
            "INFO" => "info",
            "WARNING" => "warn",
            "ERROR" | "CRITICAL" => "error",
            _ => "info",
        }
    };
    let filter = tracing_subscriber::EnvFilter::new(level);
    match &opts.log {
        Some(path) => {
            let file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
                .unwrap_or_else(|e| {
                    eprintln!("cannot open log file {path}: {e}");
                    std::process::exit(1);
                });
            tracing_subscriber::fmt()
                .with_env_filter(filter)
                .with_ansi(false)
                .with_writer(Arc::new(file))
                .init();
        }
        None => {
            tracing_subscriber::fmt()
                .with_env_filter(filter)
                .with_ansi(false)
                .with_writer(std::io::stderr)
                .init();
        }
    }
}

pub fn load_labels(opts: &Options) -> Option<AppLabels> {
    let path = opts.project_file.as_ref()?;
    // `-N` may contain multiple words.
    let network = if opts.cbus_network.is_empty() {
        None
    } else {
        Some(opts.cbus_network.join(" "))
    };
    match read_cbz_labels(Path::new(path), network.as_deref()) {
        Ok(labels) => Some(labels),
        Err(e) => {
            eprintln!("error reading project file {path}: {e}");
            std::process::exit(1);
        }
    }
}

/// The C-Bus connection to establish, plus its reconnect policy.
pub struct ConnSpec {
    pub endpoint: Endpoint,
    pub reconnect: bool,
    pub reconnect_interval: Duration,
    pub max_reconnect: u32,
}

pub fn conn_spec(opts: &Options) -> ConnSpec {
    if let Some(tcp) = &opts.tcp {
        ConnSpec {
            endpoint: Endpoint::parse_tcp(tcp).unwrap_or_else(|e| {
                eprintln!("{e}");
                std::process::exit(2);
            }),
            reconnect: false,
            reconnect_interval: Duration::from_secs(5),
            max_reconnect: 0,
        }
    } else if let Some(wifi) = &opts.esp32_wifi {
        ConnSpec {
            endpoint: Endpoint::parse_esp32_wifi(wifi).unwrap_or_else(|e| {
                eprintln!("{e}");
                std::process::exit(2);
            }),
            reconnect: true,
            reconnect_interval: Duration::from_secs(opts.esp32_reconnect_interval.max(1)),
            max_reconnect: opts.esp32_max_reconnect,
        }
    } else if let Some(dev) = &opts.esp32_serial {
        ConnSpec {
            endpoint: Endpoint::serial(dev, opts.esp32_baudrate),
            reconnect: true,
            reconnect_interval: Duration::from_secs(opts.esp32_reconnect_interval.max(1)),
            max_reconnect: opts.esp32_max_reconnect,
        }
    } else if opts.esp32_discover {
        // Blocking browse is fine here: nothing else is running yet, and
        // Startup waits for the same bounded discovery window.
        eprintln!("Discovering ESP32 C-Bus bridges via mDNS...");
        let (host, port) = crate::discover::discover_esp32(crate::discover::DISCOVER_TIMEOUT)
            .unwrap_or_else(|e| {
                eprintln!("{e}");
                std::process::exit(1);
            });
        ConnSpec {
            endpoint: Endpoint::Tcp { host, port },
            reconnect: true,
            reconnect_interval: Duration::from_secs(opts.esp32_reconnect_interval.max(1)),
            max_reconnect: opts.esp32_max_reconnect,
        }
    } else {
        eprintln!("one of -t / --esp32-wifi / --esp32-serial / --esp32-discover is required");
        std::process::exit(2);
    }
}

/// Parse every certificate in a PEM file.
fn pem_certs(path: &Path) -> Result<Vec<rustls::pki_types::CertificateDer<'static>>, String> {
    let data = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    rustls_pemfile::certs(&mut data.as_slice())
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("bad PEM in {}: {e}", path.display()))
}

/// CA roots for the broker connection: a PEM file, a directory of PEM files
/// (the Docker entrypoint passes `/etc/cmqttd/certificates`), or — when no
/// `--broker-ca` is given — the system trust store.
fn ca_roots(broker_ca: Option<&str>) -> Result<rustls::RootCertStore, String> {
    let mut roots = rustls::RootCertStore::empty();
    match broker_ca {
        Some(path) => {
            let path = Path::new(path);
            let files: Vec<std::path::PathBuf> = if path.is_dir() {
                let mut fs: Vec<_> = std::fs::read_dir(path)
                    .map_err(|e| format!("cannot read {}: {e}", path.display()))?
                    .filter_map(|e| e.ok())
                    .map(|e| e.path())
                    .filter(|p| p.is_file())
                    .collect();
                fs.sort();
                fs
            } else {
                vec![path.to_path_buf()]
            };
            for file in files {
                for cert in pem_certs(&file)? {
                    roots
                        .add(cert)
                        .map_err(|e| format!("bad CA cert in {}: {e}", file.display()))?;
                }
            }
            if roots.is_empty() {
                return Err(format!("no CA certificates found in {}", path.display()));
            }
        }
        None => {
            let certs = rustls_native_certs::load_native_certs()
                .map_err(|e| format!("cannot load system trust store: {e}"))?;
            // tolerate the odd unparsable platform cert, like OpenSSL does
            for cert in certs {
                let _ = roots.add(cert);
            }
            if roots.is_empty() {
                return Err("system trust store is empty; supply -c CA.pem".into());
            }
        }
    }
    Ok(roots)
}

fn tls_configuration(opts: &Options) -> Result<rumqttc::TlsConfiguration, String> {
    let builder = rustls::ClientConfig::builder()
        .with_root_certificates(ca_roots(opts.broker_ca.as_deref())?);
    let config = match (&opts.broker_client_cert, &opts.broker_client_key) {
        (Some(cert), Some(key)) => {
            let certs = pem_certs(Path::new(cert))?;
            let key_data =
                std::fs::read(key).map_err(|e| format!("cannot read client key {key}: {e}"))?;
            let key = rustls_pemfile::private_key(&mut key_data.as_slice())
                .map_err(|e| format!("bad client key {key}: {e}"))?
                .ok_or_else(|| format!("no private key found in {key}"))?;
            builder
                .with_client_auth_cert(certs, key)
                .map_err(|e| format!("bad client certificate/key: {e}"))?
        }
        (None, None) => builder.with_no_client_auth(),
        _ => {
            return Err(
                "To use client certificates, both --broker-client-cert (-k) \
                 and --broker-client-key (-K) must be specified."
                    .into(),
            )
        }
    };
    Ok(rumqttc::TlsConfiguration::Rustls(Arc::new(config)))
}

/// TLS server configuration for the embedded C-Gate listener. `None`
/// keeps the byte-identical plaintext path. Both cert and key are
/// required together; any load failure is fatal at startup (no listener
/// is opened). No client authentication is requested (P4b transport-only).
pub fn cgate_tls_config(opts: &Options) -> Result<Option<Arc<rustls::ServerConfig>>, String> {
    match (&opts.cgate_tls_cert, &opts.cgate_tls_key) {
        (None, None) => Ok(None),
        (Some(cert_path), Some(key_path)) => {
            let certs = pem_certs(cert_path)?;
            if certs.is_empty() {
                return Err(format!("no certificates found in {}", cert_path.display()));
            }
            let key_data = std::fs::read(key_path)
                .map_err(|e| format!("cannot read {}: {e}", key_path.display()))?;
            let key = rustls_pemfile::private_key(&mut key_data.as_slice())
                .map_err(|e| format!("bad PEM in {}: {e}", key_path.display()))?
                .ok_or_else(|| format!("no private key found in {}", key_path.display()))?;
            rustls::ServerConfig::builder()
                .with_no_client_auth()
                .with_single_cert(certs, key)
                .map(Arc::new)
                .map(Some)
                .map_err(|e| format!("bad C-Gate TLS cert/key: {e}"))
        }
        _ => Err("both --cgate-tls-cert and --cgate-tls-key must be specified together".into()),
    }
}

/// Optional cmqttd-local C-Gate LOGIN token gate (auth first-slice;
/// loopback only, NOT native access.txt parity). `None` keeps the
/// byte-identical dormant path. A configured file must hold a
/// high-entropy token (see `cbus_cgate::auth`); any load failure is fatal
/// at startup (no listener is opened, no state file is created).
pub fn cgate_auth_token(opts: &Options) -> Result<Option<[u8; 32]>, String> {
    match &opts.cgate_auth_file {
        None => Ok(None),
        Some(path) => cbus_cgate::auth::load_token_hash(path)
            .map(Some)
            .map_err(|e| format!("cannot load C-Gate auth file {}: {e}", path.display())),
    }
}

/// Prepare the embedded C-Gate service with fail-closed TLS ordering.
///
/// Loads [`cgate_tls_config`] FIRST, before [`Service::new`] creates the
/// state file. A bad cert therefore exits before listener bind and before
/// state-file creation. `xml` is the already-loaded project XML.
pub fn prepare_cgate_service(
    opts: &Options,
    xml: &str,
    pci: Arc<cbus_transport::pci::PciClient>,
) -> Result<
    (
        Arc<cbus_cgate::service::Service>,
        Option<Arc<rustls::ServerConfig>>,
    ),
    String,
> {
    // Fail closed before bind and state-file creation: unreadable/invalid
    // TLS files must never create the state file nor leave a listener behind.
    let tls = cgate_tls_config(opts)?;
    // Same ordering for the auth gate: a bad auth file exits before
    // Service::new creates the state file and before any listener binds.
    let auth = cgate_auth_token(opts)?;
    let network_name = opts.cbus_network.join(" ");
    let service = cbus_cgate::service::Service::new(
        xml,
        (!network_name.is_empty()).then_some(network_name.as_str()),
        opts.cgate_state.clone(),
        pci,
        opts.cgate_unitspec.clone(),
    )
    .map_err(|e| e.to_string())?;
    if let Some(hash) = auth {
        service
            .set_auth_token_hash(hash)
            .map_err(|_| "C-Gate auth already configured".to_string())?;
    }
    Ok((service, tls))
}

pub fn mqtt_options(opts: &Options) -> Result<MqttOptions, String> {
    let port = if opts.broker_port != 0 {
        opts.broker_port
    } else if opts.broker_disable_tls {
        1883
    } else {
        8883
    };
    let client_id = format!("cmqttd-{}", std::process::id());
    let mut mo = MqttOptions::new(client_id, opts.broker_address.clone(), port);
    mo.set_keep_alive(Duration::from_secs(opts.broker_keepalive.max(5) as u64));
    if !opts.broker_disable_tls {
        mo.set_transport(Transport::Tls(tls_configuration(opts)?));
    }
    if let Some(auth_file) = &opts.broker_auth {
        let content = std::fs::read_to_string(auth_file)
            .map_err(|e| format!("cannot read auth file {auth_file}: {e}"))?;
        let mut lines = content.lines();
        let user = lines.next().unwrap_or("").trim().to_string();
        let pass = lines.next().unwrap_or("").trim().to_string();
        mo.set_credentials(user, pass);
    }
    Ok(mo)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_trust_store_loads() {
        let roots = ca_roots(None).expect("system trust store");
        assert!(!roots.is_empty());
    }

    #[test]
    fn missing_ca_file_errors() {
        assert!(ca_roots(Some("/nonexistent/ca.pem")).is_err());
    }

    #[test]
    fn empty_ca_dir_errors() {
        let dir = std::env::temp_dir().join(format!("cmqttd-ca-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let r = ca_roots(Some(dir.to_str().unwrap()));
        std::fs::remove_dir_all(&dir).ok();
        assert!(r.is_err());
    }

    fn tls_fixture(name: &str) -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../testdata/fixtures")
            .join(name)
    }

    fn tls_opts(cert: Option<std::path::PathBuf>, key: Option<std::path::PathBuf>) -> Options {
        Options {
            debug: false,
            log: None,
            verbosity: "INFO".into(),
            broker_address: "127.0.0.1".into(),
            broker_port: 0,
            broker_keepalive: 60,
            broker_disable_tls: true,
            broker_auth: None,
            broker_ca: None,
            broker_client_cert: None,
            broker_client_key: None,
            tcp: Some("127.0.0.1:10001".into()),
            esp32_wifi: None,
            esp32_serial: None,
            esp32_discover: false,
            esp32_baudrate: 9600,
            esp32_reconnect_interval: 5,
            esp32_max_reconnect: 0,
            timesync: 0,
            no_clock: false,
            status_resync: 0,
            project_file: None,
            cbus_network: vec![],
            cgate_bind: None,
            cgate_state: std::path::PathBuf::from("cmqttd-data/cgate.json"),
            cgate_unitspec: None,
            cgate_tls_cert: cert,
            cgate_tls_key: key,
            cgate_auth_file: None,
        }
    }

    #[test]
    fn cgate_tls_disabled_by_default() {
        assert!(cgate_tls_config(&tls_opts(None, None)).unwrap().is_none());
    }

    #[test]
    fn cgate_tls_loads_test_fixtures() {
        let opts = tls_opts(
            Some(tls_fixture("cgate-tls-test-cert.pem")),
            Some(tls_fixture("cgate-tls-test-key.pem")),
        );
        assert!(cgate_tls_config(&opts).unwrap().is_some());
    }

    #[test]
    fn cgate_tls_missing_files_fail_closed() {
        let opts = tls_opts(
            Some(std::path::PathBuf::from("/nonexistent/cgate-cert.pem")),
            Some(std::path::PathBuf::from("/nonexistent/cgate-key.pem")),
        );
        assert!(cgate_tls_config(&opts).is_err());
    }

    #[test]
    fn cgate_tls_half_config_fails_closed() {
        let opts = tls_opts(Some(tls_fixture("cgate-tls-test-cert.pem")), None);
        assert!(cgate_tls_config(&opts).is_err());
        let opts = tls_opts(None, Some(tls_fixture("cgate-tls-test-key.pem")));
        assert!(cgate_tls_config(&opts).is_err());
    }

    #[test]
    fn cgate_tls_garbage_pem_fails_closed() {
        let dir = std::env::temp_dir();
        let cert = dir.join(format!("cgate-garbage-{}-cert.pem", std::process::id()));
        let key = dir.join(format!("cgate-garbage-{}-key.pem", std::process::id()));
        std::fs::write(&cert, "not a certificate\n").unwrap();
        std::fs::write(&key, "not a key\n").unwrap();
        let opts = tls_opts(Some(cert.clone()), Some(key.clone()));
        assert!(cgate_tls_config(&opts).is_err());
        std::fs::remove_file(cert).ok();
        std::fs::remove_file(key).ok();
    }

    fn auth_opts(path: Option<std::path::PathBuf>) -> Options {
        let mut opts = tls_opts(None, None);
        opts.cgate_auth_file = path;
        opts
    }

    #[cfg(unix)]
    fn token_file(contents: &str, mode: u32) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;
        static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "cmqttd-cgate-auth-{}-{}.token",
            std::process::id(),
            ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::write(&path, contents).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        path
    }

    #[test]
    fn cgate_auth_disabled_by_default() {
        assert!(cgate_auth_token(&auth_opts(None)).unwrap().is_none());
    }

    #[test]
    fn cgate_auth_missing_file_fails_closed() {
        let opts = auth_opts(Some(std::path::PathBuf::from("/nonexistent/cgate.token")));
        assert!(cgate_auth_token(&opts).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn cgate_auth_loads_locked_down_token_file() {
        let path = token_file("throwaway-setup-token-0123456789abcdef\n", 0o400);
        let hash = cgate_auth_token(&auth_opts(Some(path.clone())))
            .expect("0400 token file loads")
            .expect("hash present");
        assert_eq!(
            hash,
            cbus_cgate::auth::sha256(b"throwaway-setup-token-0123456789abcdef")
        );
        std::fs::remove_file(path).ok();
    }

    #[cfg(unix)]
    #[test]
    fn cgate_auth_group_readable_file_fails_closed() {
        let path = token_file("throwaway-setup-token-0123456789abcdef\n", 0o640);
        assert!(cgate_auth_token(&auth_opts(Some(path.clone()))).is_err());
        std::fs::remove_file(path).ok();
    }

    #[cfg(unix)]
    #[test]
    fn cgate_auth_short_token_fails_closed() {
        let path = token_file("tiny\n", 0o400);
        assert!(cgate_auth_token(&auth_opts(Some(path.clone()))).is_err());
        std::fs::remove_file(path).ok();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn cgate_startup_bad_auth_creates_no_state_file() {
        // Auth config must load BEFORE Service::new creates the state file.
        let state = unique_state_path("bad-auth");
        assert!(!state.exists());
        let mut opts = auth_opts(Some(std::path::PathBuf::from("/nonexistent/cgate.token")));
        opts.cgate_state = state.clone();
        let xml = std::fs::read_to_string(tls_fixture("project.xml")).expect("project fixture");
        let err = match prepare_cgate_service(&opts, &xml, dummy_pci()) {
            Ok(_) => panic!("bad auth file must fail"),
            Err(e) => e,
        };
        assert!(!err.is_empty());
        assert!(
            !state.exists(),
            "bad auth file must not create the C-Gate state file"
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn cgate_startup_valid_auth_arms_login_gate() {
        use cbus_cgate::service::ClientState;
        let state = unique_state_path("good-auth");
        assert!(!state.exists());
        let token_path = token_file("throwaway-e2e-token-0123456789abcdef\n", 0o400);
        let mut opts = auth_opts(Some(token_path.clone()));
        opts.cgate_state = state.clone();
        let xml = std::fs::read_to_string(tls_fixture("project.xml")).expect("project fixture");
        let (service, _) = prepare_cgate_service(&opts, &xml, dummy_pci()).expect("valid auth");
        let mut client = ClientState::default();
        // Wrong secret is denied; the gate is armed end-to-end.
        assert_eq!(
            service
                .handle(&mut client, "[1] LOGIN wrong-secret-value")
                .await
                .status,
            420
        );
        assert_eq!(
            service
                .handle(
                    &mut client,
                    "[2] LOGIN throwaway-e2e-token-0123456789abcdef"
                )
                .await
                .status,
            200
        );
        drop(service);
        assert!(state.exists(), "valid startup creates the state file");
        std::fs::remove_file(state).ok();
        std::fs::remove_file(token_path).ok();
    }

    fn dummy_pci() -> Arc<cbus_transport::pci::PciClient> {
        let (client, _remote) = tokio::io::duplex(8192);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = tokio::sync::mpsc::unbounded_channel();
        cbus_transport::pci::PciClient::new(Box::new(rd), Box::new(wr), tx)
    }

    fn unique_state_path(tag: &str) -> std::path::PathBuf {
        static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        std::env::temp_dir().join(format!(
            "cmqttd-cgate-order-{}-{}-{}.json",
            std::process::id(),
            ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            tag
        ))
    }

    #[tokio::test]
    async fn cgate_startup_bad_cert_creates_no_state_file() {
        // TLS config must load BEFORE Service::new creates the state file.
        let state = unique_state_path("bad-cert");
        assert!(!state.exists());
        let mut opts = tls_opts(
            Some(std::path::PathBuf::from("/nonexistent/cgate-cert.pem")),
            Some(std::path::PathBuf::from("/nonexistent/cgate-key.pem")),
        );
        opts.cgate_state = state.clone();
        let xml = std::fs::read_to_string(tls_fixture("project.xml")).expect("project fixture");
        let err = match prepare_cgate_service(&opts, &xml, dummy_pci()) {
            Ok(_) => panic!("bad cert must fail"),
            Err(e) => e,
        };
        assert!(!err.is_empty());
        assert!(
            !state.exists(),
            "bad TLS cert must not create the C-Gate state file"
        );
    }

    #[tokio::test]
    async fn cgate_startup_valid_tls_creates_service() {
        let state = unique_state_path("good-cert");
        assert!(!state.exists());
        let mut opts = tls_opts(
            Some(tls_fixture("cgate-tls-test-cert.pem")),
            Some(tls_fixture("cgate-tls-test-key.pem")),
        );
        opts.cgate_state = state.clone();
        let xml = std::fs::read_to_string(tls_fixture("project.xml")).expect("project fixture");
        let (service, tls) =
            prepare_cgate_service(&opts, &xml, dummy_pci()).expect("valid TLS startup");
        assert!(tls.is_some());
        drop(service);
        assert!(state.exists(), "valid startup creates the state file");
        std::fs::remove_file(state).ok();
    }
}
