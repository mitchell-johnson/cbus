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
    // `-N` may be multiple words; Python joins with spaces
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
        // the Python daemon also blocks its startup for the same window.
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
/// `--broker-ca` is given — the system trust store, matching the Python
/// daemon's `ssl.create_default_context()`.
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
}
