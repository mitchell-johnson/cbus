//! `cmqttd`: MQTT connector for C-Bus.

mod cli;
mod discover;
mod gateway;
mod setup;

use cbus_cgate::service::StartupEventTransport;
use cbus_transport::conn::{self};
use cbus_transport::pci::{CBusEvent, PciClient};
use clap::Parser;
use cli::Options;
use gateway::Gateway;
use rumqttc::{AsyncClient, Event, Packet as MqttPacket};
use setup::ConnSpec;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;

/// Queue a clean MQTT DISCONNECT behind any preceding publish, then give the
/// still-running event loop a bounded opportunity to write both to the broker.
async fn flush_mqtt_before_exit(client: &AsyncClient) {
    // rumqttc only drains its request channel while a broker connection is up;
    // if the channel is full, disconnect() can block forever, so bound the wait.
    match tokio::time::timeout(Duration::from_secs(2), client.disconnect()).await {
        Ok(Ok(())) => tokio::time::sleep(Duration::from_millis(250)).await,
        _ => tracing::warn!("MQTT disconnect not flushed; exiting anyway"),
    }
}

/// On SIGINT/SIGTERM: send a clean MQTT DISCONNECT (the main loop keeps
/// polling so it actually flushes), then exit.
fn spawn_shutdown_handler(client: AsyncClient) {
    tokio::spawn(async move {
        let ctrl_c = tokio::signal::ctrl_c();
        #[cfg(unix)]
        {
            let term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate());
            match term {
                Ok(mut term) => {
                    tokio::select! {
                        _ = ctrl_c => {}
                        _ = term.recv() => {}
                    }
                }
                Err(_) => {
                    let _ = ctrl_c.await;
                }
            }
        }
        #[cfg(not(unix))]
        {
            let _ = ctrl_c.await;
        }
        tracing::info!("shutdown signal received; disconnecting from MQTT");
        flush_mqtt_before_exit(&client).await;
        std::process::exit(0);
    });
}

/// Connect a fresh PCI client over the endpoint and kick off its init
/// sequence (`connection_made` → `pci_reset`).
fn start_pci_reset(pci: &Arc<PciClient>) {
    let pci = pci.clone();
    tokio::spawn(async move {
        if let Err(e) = pci.pci_reset().await {
            tracing::error!("PCI reset failed: {e}");
        }
    });
}

/// Work for the MQTT gateway, applied strictly in bus order.
enum GatewayWork {
    Event(CBusEvent),
    Reconnected,
    /// Signals once every earlier item has been handed to MQTT.
    Drained(tokio::sync::oneshot::Sender<()>),
}

/// Apply C-Bus events to the MQTT gateway on their own task. MQTT publishes
/// wait on rumqttc's bounded request queue, which only drains while the
/// broker is connected; running them here keeps a broker outage from
/// stalling the event pump, and with it the embedded C-Gate event stream,
/// transport reconnects and programming observers. The queue is unbounded
/// like the pump's own inbound channel; it drains in order once MQTT is back.
fn spawn_gateway_worker(gw: Arc<Gateway>) -> mpsc::UnboundedSender<GatewayWork> {
    let (tx, mut rx) = mpsc::unbounded_channel::<GatewayWork>();
    tokio::spawn(async move {
        while let Some(work) = rx.recv().await {
            match work {
                GatewayWork::Event(ev) => gw.on_cbus_event(ev).await,
                GatewayWork::Reconnected => gw.on_cbus_reconnected().await,
                GatewayWork::Drained(done) => {
                    let _ = done.send(());
                }
            }
        }
    });
    tx
}

/// Pump C-Bus events to the C-Gate service and the MQTT gateway; on
/// connection loss, reconnect (discovery modes) or shut down (plain `-t`).
async fn cbus_event_pump(
    gw: Arc<Gateway>,
    mqtt: AsyncClient,
    mut ev_rx: mpsc::UnboundedReceiver<CBusEvent>,
    ev_tx: mpsc::UnboundedSender<CBusEvent>,
    spec: ConnSpec,
    cgate: Option<Arc<cbus_cgate::service::Service>>,
) {
    let gateway = spawn_gateway_worker(gw.clone());
    while let Some(ev) = ev_rx.recv().await {
        if let Some(service) = &cgate {
            service.observe(&ev).await;
        }
        if let CBusEvent::ConnectionLost = ev {
            let _ = gateway.send(GatewayWork::Event(ev));
            if !spec.reconnect {
                // Queue the retained OFF state behind every earlier event
                // before the final MQTT flush. A broker outage cannot hold
                // shutdown open indefinitely.
                let (done, drained) = tokio::sync::oneshot::channel();
                let _ = gateway.send(GatewayWork::Drained(done));
                let _ = tokio::time::timeout(Duration::from_secs(5), drained).await;
                tracing::error!("C-Bus connection lost; shutting down");
                flush_mqtt_before_exit(&mqtt).await;
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
                    start_pci_reset(&new_pci);
                    if let Some(service) = &cgate {
                        service.set_pci(new_pci.clone()).await;
                    }
                    gw.set_pci(new_pci).await;
                    let _ = gateway.send(GatewayWork::Reconnected);
                    // Every cached observation was invalidated on transport
                    // loss. Force a fresh configured sweep instead of relying
                    // on the startup-only deduplication or a later timer.
                    gw.queue_configured_status_requests(true);
                    tracing::info!("reconnected; MQTT bridge re-bound");
                }
                Err(e) => {
                    tracing::error!("reconnection exhausted ({e}); shutting down");
                    std::process::exit(1);
                }
            }
        } else {
            let _ = gateway.send(GatewayWork::Event(ev));
        }
    }
}

#[tokio::main]
async fn main() {
    let opts = Options::parse();
    setup::init_logging(&opts);

    let labels = setup::load_labels(&opts);
    let spec = setup::conn_spec(&opts);

    // C-Bus connection + PCI client
    let (ev_tx, ev_rx) = mpsc::unbounded_channel::<CBusEvent>();
    let (rd, wr) = match conn::connect(&spec.endpoint).await {
        Ok(x) => x,
        Err(e) => {
            tracing::error!("cannot connect to C-Bus endpoint: {e}");
            std::process::exit(1);
        }
    };
    let pci = PciClient::new(rd, wr, ev_tx.clone());
    start_pci_reset(&pci);

    let cgate = if let Some(bind) = &opts.cgate_bind {
        let result = async {
            let xml = cbus_mqtt::cbz::load_xml(std::path::Path::new(
                opts.project_file.as_ref().expect("clap requires project"),
            ))
            .map_err(std::io::Error::other)?;
            // TLS config loads FIRST inside prepare_cgate_service, before
            // Service::new creates the state file: a bad cert exits before
            // listener bind and before state-file creation.
            let (service, tls) = setup::prepare_cgate_service(&opts, &xml, pci.clone())
                .map_err(std::io::Error::other)?;
            if service.global_event_listener_invalid() {
                tracing::error!(
                    "C-Gate listener disabled: saved CONFIG global-event-level is not a valid integer"
                );
                return Ok::<_, std::io::Error>(None);
            }
            service
                .set_port_endpoint(spec.endpoint.clone())
                .map_err(|_| {
                    std::io::Error::other("C-Gate PORT endpoint was already configured")
                })?;
            let listener = tokio::net::TcpListener::bind(bind).await?;
            tracing::info!("C-Gate service listening on {}", listener.local_addr()?);
            match service.startup_event_transport() {
                StartupEventTransport::Server { port } => {
                    // Test deployments with an ephemeral command bind also
                    // receive an ephemeral event port when CONFIG retains its
                    // native default. A configured nondefault port is exact.
                    let port = if port == 20024 && bind.ends_with(":0") { 0 } else { port };
                    let command_ip = listener.local_addr()?.ip();
                    let event_ip = if tls.is_some() {
                        tracing::warn!(
                            "C-Gate event server restricted to loopback because command TLS is enabled"
                        );
                        match command_ip {
                            std::net::IpAddr::V4(_) => std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST),
                            std::net::IpAddr::V6(_) => std::net::IpAddr::V6(std::net::Ipv6Addr::LOCALHOST),
                        }
                    } else {
                        command_ip
                    };
                    let address = std::net::SocketAddr::new(event_ip, port);
                    match tokio::net::TcpListener::bind(address).await {
                        Ok(event_listener) => {
                            tracing::info!("C-Gate event service listening on {}", event_listener.local_addr()?);
                            let events = service.clone();
                            tokio::spawn(async move {
                                if let Err(error) = events.serve_event_server(event_listener).await {
                                    tracing::error!("C-Gate event listener failed: {error}");
                                }
                            });
                        }
                        Err(error) => tracing::error!("C-Gate event listener disabled: {error}"),
                    }
                }
                StartupEventTransport::Socket { host, port } => {
                    let events = service.clone();
                    tokio::spawn(async move { events.serve_event_socket(host, port).await });
                }
                StartupEventTransport::Disabled { reason } => {
                    tracing::error!("C-Gate event transport disabled: {reason}");
                }
            }
            let running = service.clone();
            tokio::spawn(async move {
                let result = match tls {
                    Some(config) => running.serve_tls(listener, config).await,
                    None => running.serve(listener).await,
                };
                if let Err(e) = result {
                    tracing::error!("C-Gate listener failed: {e}");
                    std::process::exit(1);
                }
            });
            Ok::<_, std::io::Error>(Some(service))
        }
        .await;
        result.unwrap_or_else(|e| {
            tracing::error!("cannot start C-Gate service: {e}");
            std::process::exit(1);
        })
    } else {
        None
    };

    // MQTT client + gateway
    let mqtt_opts = setup::mqtt_options(&opts).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1);
    });
    let (client, mut eventloop) = AsyncClient::new(mqtt_opts, 100);
    spawn_shutdown_handler(client.clone());
    if let Some(service) = &cgate {
        let mut shutdown = service.subscribe_shutdown();
        let shutdown_client = client.clone();
        tokio::spawn(async move {
            if shutdown.recv().await.is_ok() {
                // Let the command listener flush the native 206 reply before
                // terminating the process, then drain MQTT in the same way as
                // SIGINT/SIGTERM.
                tokio::time::sleep(Duration::from_millis(100)).await;
                tracing::info!("confirmed C-Gate SHUTDOWN received; disconnecting from MQTT");
                flush_mqtt_before_exit(&shutdown_client).await;
                std::process::exit(0);
            }
        });
    }
    let gateway = Gateway::new(client.clone(), pci, labels, opts.no_clock);

    // timesync loop (every -T seconds); 0 disables
    if opts.timesync > 0 {
        let gw = gateway.clone();
        let freq = opts.timesync;
        tokio::spawn(async move {
            loop {
                let _ = gw.pci().await.clock_datetime().await;
                tokio::time::sleep(Duration::from_secs(freq)).await;
            }
        });
    }

    // periodic status resync (every -S seconds); 0 disables
    if opts.status_resync > 0 {
        let gw = gateway.clone();
        let freq = opts.status_resync;
        tracing::info!("periodic C-Bus status resync enabled every {freq} seconds");
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_secs(freq)).await;
                tracing::info!("queueing periodic C-Bus status resync");
                gw.queue_configured_status_requests(true);
            }
        });
    }

    tokio::spawn(cbus_event_pump(
        gateway.clone(),
        client,
        ev_rx,
        ev_tx,
        spec,
        cgate,
    ));

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
                gateway.handle_publish(&p.topic, &p.payload, p.retain);
            }
            Ok(_) => {}
            Err(e) => {
                tracing::warn!("MQTT connection error: {e}; retrying");
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        }
    }
}
