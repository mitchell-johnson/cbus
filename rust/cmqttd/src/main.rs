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

fn mqtt_options(opts: &Options) -> MqttOptions {
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
        let ca = match &opts.broker_ca {
            Some(path) => std::fs::read(path).unwrap_or_else(|e| {
                eprintln!("cannot read CA file {path}: {e}");
                std::process::exit(1);
            }),
            None => {
                eprintln!(
                    "TLS enabled but no --broker-ca given; supply -c CA.pem or \
                     use --broker-disable-tls"
                );
                std::process::exit(1);
            }
        };
        let client_auth = match (&opts.broker_client_cert, &opts.broker_client_key) {
            (Some(cert), Some(key)) => Some((
                std::fs::read(cert).expect("client cert"),
                std::fs::read(key).expect("client key"),
            )),
            (None, None) => None,
            _ => {
                eprintln!(
                    "To use client certificates, both --broker-client-cert (-k) \
                     and --broker-client-key (-K) must be specified."
                );
                std::process::exit(1);
            }
        };
        mo.set_transport(Transport::Tls(rumqttc::TlsConfiguration::Simple {
            ca,
            alpn: None,
            client_auth,
        }));
    }
    if let Some(auth_file) = &opts.broker_auth {
        let content = std::fs::read_to_string(auth_file).unwrap_or_else(|e| {
            eprintln!("cannot read auth file {auth_file}: {e}");
            std::process::exit(1);
        });
        let mut lines = content.lines();
        let user = lines.next().unwrap_or("").trim().to_string();
        let pass = lines.next().unwrap_or("").trim().to_string();
        mo.set_credentials(user, pass);
    }
    mo
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
    let (client, mut eventloop) = AsyncClient::new(mqtt_options(&opts), 100);
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
