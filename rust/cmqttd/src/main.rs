//! cmqttd: MQTT connector for C-Bus. Port of `cbus/daemon/cmqttd.py`.

mod cli;
mod discover;
mod gateway;
mod setup;
mod throttle;

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
        // rumqttc only drains its request channel while a broker connection
        // is up; if the channel is full (broker down, busy C-Bus network)
        // disconnect() would block forever, so bound the wait.
        match tokio::time::timeout(Duration::from_secs(2), client.disconnect()).await {
            Ok(Ok(())) => tokio::time::sleep(Duration::from_millis(250)).await,
            _ => tracing::warn!("MQTT disconnect not flushed; exiting anyway"),
        }
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

/// Pump C-Bus events into the gateway; on connection loss, reconnect
/// (esp32 modes) or shut down (plain `-t`, like the Python daemon).
async fn cbus_event_pump(
    gw: Arc<Gateway>,
    mut ev_rx: mpsc::UnboundedReceiver<CBusEvent>,
    ev_tx: mpsc::UnboundedSender<CBusEvent>,
    spec: ConnSpec,
) {
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
                    start_pci_reset(&new_pci);
                    gw.set_pci(new_pci).await;
                    // CBusHandler.connection_made re-queues the status
                    // requests once the MQTT api is bound
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

    // MQTT client + gateway
    let mqtt_opts = setup::mqtt_options(&opts).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1);
    });
    let (client, mut eventloop) = AsyncClient::new(mqtt_opts, 100);
    spawn_shutdown_handler(client.clone());
    let gateway = Gateway::new(client, pci, labels, opts.no_clock);

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

    tokio::spawn(cbus_event_pump(gateway.clone(), ev_rx, ev_tx, spec));

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
                gateway.handle_publish(&p.topic, &p.payload);
            }
            Ok(_) => {}
            Err(e) => {
                tracing::warn!("MQTT connection error: {e}; retrying");
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        }
    }
}
