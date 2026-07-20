//! cmqttd: MQTT connector for C-Bus. Port of `cbus/daemon/cmqttd.py`.

mod cli;
mod gateway;
mod throttle;

use cbus_mqtt::cbz::read_cbz_labels;
use cbus_mqtt::discovery::AppLabels;
use cbus_transport::conn::{self, Endpoint};
use cbus_transport::pci::{CBusEvent, PciClient};
use clap::Parser;
use cli::Options;
use gateway::Gateway;
use rumqttc::{AsyncClient, Event, MqttOptions, Packet as MqttPacket, Transport};
use std::path::Path;
use std::time::Duration;
use tokio::sync::mpsc;

fn init_logging(opts: &Options) {
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
                .expect("cannot open log file");
            tracing_subscriber::fmt()
                .with_env_filter(filter)
                .with_ansi(false)
                .with_writer(move || file.try_clone().expect("log file clone"))
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

fn load_labels(opts: &Options) -> Option<AppLabels> {
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

struct ConnSpec {
    endpoint: Endpoint,
    reconnect: bool,
    reconnect_interval: Duration,
    max_reconnect: u32,
}

fn conn_spec(opts: &Options) -> ConnSpec {
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
    } else {
        eprintln!("one of -t / --esp32-wifi / --esp32-serial is required");
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
    Ok(rumqttc::TlsConfiguration::Rustls(std::sync::Arc::new(
        config,
    )))
}

fn mqtt_options(opts: &Options) -> Result<MqttOptions, String> {
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

#[tokio::main]
async fn main() {
    let opts = Options::parse();
    init_logging(&opts);

    let labels = load_labels(&opts);
    let spec = conn_spec(&opts);

    // C-Bus connection + PCI client
    let (ev_tx, mut ev_rx) = mpsc::unbounded_channel::<CBusEvent>();
    let (rd, wr) = match conn::connect(&spec.endpoint).await {
        Ok(x) => x,
        Err(e) => {
            tracing::error!("cannot connect to C-Bus endpoint: {e}");
            std::process::exit(1);
        }
    };
    let pci = PciClient::new(rd, wr, ev_tx.clone());
    {
        // connection_made: reset the PCI (init sequence)
        let pci = pci.clone();
        tokio::spawn(async move {
            if let Err(e) = pci.pci_reset().await {
                tracing::error!("PCI reset failed: {e}");
            }
        });
    }

    // MQTT client + gateway
    let mqtt_opts = mqtt_options(&opts).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1);
    });
    let (client, mut eventloop) = AsyncClient::new(mqtt_opts, 100);
    let gateway = Gateway::new(client, pci, labels, opts.no_clock);

    // timesync loop (every -T seconds); 0 disables
    if opts.timesync > 0 {
        let gw = gateway.clone();
        let freq = opts.timesync;
        tokio::spawn(async move {
            loop {
                let pci = gw.pci.read().await.clone();
                let _ = pci.clock_datetime().await;
                tokio::time::sleep(Duration::from_secs(freq)).await;
            }
        });
    }

    // C-Bus event pump (incl. reconnect handling for esp32 modes)
    {
        let gw = gateway.clone();
        tokio::spawn(async move {
            while let Some(ev) = ev_rx.recv().await {
                if let CBusEvent::ConnectionLost = ev {
                    gw.on_cbus_event(ev).await;
                    if !spec.reconnect {
                        tracing::error!("C-Bus connection lost; shutting down");
                        std::process::exit(0);
                    }
                    tracing::warn!("C-Bus connection lost; reconnecting...");
                    match conn::connect_with_retry(
                        &spec.endpoint,
                        spec.reconnect_interval,
                        spec.max_reconnect,
                    )
                    .await
                    {
                        Ok((rd, wr)) => {
                            let new_pci = PciClient::new(rd, wr, ev_tx.clone());
                            {
                                let p = new_pci.clone();
                                tokio::spawn(async move {
                                    let _ = p.pci_reset().await;
                                });
                            }
                            *gw.pci.write().await = new_pci;
                            // CBusHandler.connection_made re-queues the
                            // status requests once the MQTT api is bound
                            gw.queue_status_requests();
                            tracing::info!("reconnected; MQTT bridge re-bound");
                        }
                        Err(e) => {
                            tracing::error!("reconnection exhausted ({e}); shutting down");
                            std::process::exit(1);
                        }
                    }
                } else {
                    gw.on_cbus_event(ev).await;
                }
            }
        });
    }

    // MQTT event loop
    loop {
        match eventloop.poll().await {
            Ok(Event::Incoming(MqttPacket::ConnAck(_))) => {
                tracing::info!("connected to MQTT broker");
                let gw = gateway.clone();
                tokio::spawn(async move {
                    gw.on_connected().await;
                });
            }
            Ok(Event::Incoming(MqttPacket::Publish(p))) => {
                let gw = gateway.clone();
                let topic = p.topic.clone();
                let payload = p.payload.to_vec();
                gw.handle_publish(&topic, &payload);
            }
            Ok(_) => {}
            Err(e) => {
                tracing::warn!("MQTT connection error: {e}; retrying");
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        }
    }
}

#[cfg(test)]
mod tls_tests {
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
