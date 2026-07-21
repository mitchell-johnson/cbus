//! MQTT <-> C-Bus glue. Port of `cbus/daemon/mqtt_gateway.py`
//! (`CBusHandler` event relays + `MqttClient` helpers) onto rumqttc.

use crate::throttle::Throttle;
use cbus_mqtt::command::{parse_set_command, CommandError};
use cbus_mqtt::discovery::{light_discovery, meta_discovery, AppLabels};
use cbus_mqtt::topics::{
    bin_sensor_state_topic, state_topic, LIGHT_TOPIC_PREFIX, TOPIC_SET_SUFFIX,
};
use cbus_transport::pci::{CBusEvent, PciClient};
use rumqttc::{AsyncClient, QoS};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::RwLock;

pub struct Gateway {
    mqtt: AsyncClient,
    pci: RwLock<Arc<PciClient>>,
    throttle: Throttle,
    labels: AppLabels,
    no_clock: bool,
    /// groupDB: app -> group -> discovery-config-published
    group_db: Mutex<HashMap<i64, HashMap<u8, bool>>>,
    /// `MqttClient._status_requests_queued`: the configured sweep runs
    /// once per process; only the periodic resync forces repeats.
    status_requests_queued: AtomicBool,
}

impl Gateway {
    pub fn new(
        mqtt: AsyncClient,
        pci: Arc<PciClient>,
        labels: Option<AppLabels>,
        no_clock: bool,
    ) -> Arc<Gateway> {
        // CBusHandler default: {56: ("Lighting", {})}
        let labels = labels.unwrap_or_else(|| {
            let mut l = AppLabels::new();
            l.insert(56, ("Lighting".to_string(), Default::default()));
            l
        });
        Arc::new(Gateway {
            mqtt,
            pci: RwLock::new(pci),
            throttle: Throttle::new(),
            labels,
            no_clock,
            group_db: Mutex::new(HashMap::new()),
            status_requests_queued: AtomicBool::new(false),
        })
    }

    /// The current PCI client (swapped out on reconnect).
    pub async fn pci(&self) -> Arc<PciClient> {
        self.pci.read().await.clone()
    }

    /// Swap in a fresh PCI client after a reconnect.
    pub async fn set_pci(&self, pci: Arc<PciClient>) {
        *self.pci.write().await = pci;
    }

    // ------------------------------------------------------------- startup

    /// `MqttClient.__aenter__`: subscribe the /set command wildcard,
    /// publish the meta config, publish discovery for every labelled
    /// group, then enqueue the configured throttled status sweep.
    pub async fn on_connected(self: &Arc<Self>) {
        let _ = self
            .mqtt
            .subscribe("homeassistant/light/+/set", QoS::ExactlyOnce)
            .await;

        let (topic, config) = meta_discovery();
        let _ = self
            .mqtt
            .publish(topic, QoS::AtLeastOnce, true, config.to_string())
            .await;

        let pairs: Vec<(u8, i64)> = self
            .labels
            .iter()
            .flat_map(|(&app, (_, groups))| groups.keys().map(move |&ga| (ga, app)))
            .collect();
        for (ga, app) in pairs {
            self.publish_light(ga, app, true).await;
        }

        self.queue_configured_status_requests(false);
    }

    /// `MqttClient._configured_status_blocks`: block starts to sweep for
    /// one app — the blocks holding its labelled groups (255 is the
    /// project files' pseudo-group and is ignored), the full range when
    /// the app has no labels entry, nothing when it has one but no real
    /// groups.
    fn configured_status_blocks(&self, app: i64) -> Vec<u8> {
        let Some((_, groups)) = self.labels.get(&app) else {
            return (0u16..256).step_by(32).map(|b| b as u8).collect();
        };
        let mut blocks: Vec<u8> = groups
            .keys()
            .filter(|&&ga| ga != 255)
            .map(|&ga| ga & 0xe0)
            .collect();
        blocks.sort_unstable();
        blocks.dedup();
        blocks
    }

    /// `MqttClient.queue_configured_status_requests`: sweep only the
    /// configured apps/blocks (all apps when no labels exist), once per
    /// process unless forced by the periodic resync.
    pub fn queue_configured_status_requests(self: &Arc<Self>, force: bool) {
        if !force && self.status_requests_queued.swap(true, Ordering::SeqCst) {
            tracing::debug!("configured status requests already queued; skipping duplicate");
            return;
        }

        let configured: Vec<i64> = self
            .labels
            .keys()
            .copied()
            .filter(|app| (0x30..=0x5f).contains(app))
            .collect();
        // no labels at all: preserve the old full-discovery behaviour
        let apps = if configured.is_empty() {
            (0x30..=0x5fi64).collect()
        } else {
            configured
        };

        for app in apps {
            let blocks = self.configured_status_blocks(app);
            if blocks.is_empty() {
                tracing::debug!("skipping status requests for app {app}; no real groups");
                continue;
            }
            self.queue_status_requests(app as u8, &blocks);
        }
    }

    /// `MqttClient.queue_status_requests`: binary status first (reliable
    /// ON/OFF presence), then level status so dimmer brightness can
    /// overwrite the binary fallback, per block.
    fn queue_status_requests(self: &Arc<Self>, app: u8, blocks: &[u8]) {
        for &block in blocks {
            for level_request in [false, true] {
                let gw = self.clone();
                self.throttle.enqueue(async move {
                    let kind = if level_request { "level" } else { "binary" };
                    tracing::info!("requesting {kind} status for app={app} block={block}");
                    let _ = gw
                        .pci()
                        .await
                        .request_status(block, app, level_request)
                        .await;
                });
            }
        }
    }

    // ----------------------------------------------------------- discovery

    /// `MqttClient.publish_light`
    pub async fn publish_light(&self, group_addr: u8, app_addr: i64, with_labels: bool) {
        let labels = if with_labels {
            Some(&self.labels)
        } else {
            None
        };
        // commands arrive via the homeassistant/light/+/set wildcard;
        // no per-light subscription (matches the deployed daemon)
        let d = light_discovery(group_addr, app_addr, labels);
        let _ = self
            .mqtt
            .publish(
                d.light_config_topic,
                QoS::AtLeastOnce,
                true,
                d.light_config.to_string(),
            )
            .await;
        let _ = self
            .mqtt
            .publish(
                d.sensor_config_topic,
                QoS::AtLeastOnce,
                true,
                d.sensor_config.to_string(),
            )
            .await;
        self.group_db
            .lock()
            .unwrap()
            .entry(app_addr)
            .or_default()
            .insert(group_addr, true);
    }

    /// `MqttClient.check_published`: lazy discovery config for unknown groups.
    pub async fn check_published(&self, group_addr: u8, app_addr: i64) {
        let published = self
            .group_db
            .lock()
            .unwrap()
            .entry(app_addr)
            .or_default()
            .get(&group_addr)
            .copied()
            .unwrap_or(false);
        if !published {
            self.publish_light(group_addr, app_addr, false).await;
        }
    }

    // ------------------------------------------------------ state publishes

    async fn publish_state(&self, topic: String, payload: Value) {
        let _ = self
            .mqtt
            .publish(topic, QoS::AtLeastOnce, true, payload.to_string())
            .await;
    }

    async fn publish_binary_sensor(&self, group_addr: u8, app_addr: i64, state: bool) {
        let payload = if state { "ON" } else { "OFF" };
        let _ = self
            .mqtt
            .publish(
                bin_sensor_state_topic(group_addr, app_addr),
                QoS::AtLeastOnce,
                true,
                payload,
            )
            .await;
    }

    pub async fn mqtt_light_on(&self, source: Option<u8>, group_addr: u8, app_addr: i64) {
        self.check_published(group_addr, app_addr).await;
        self.publish_state(
            state_topic(group_addr, app_addr),
            json!({"state": "ON", "brightness": 255, "transition": 0,
                   "cbus_source_addr": source}),
        )
        .await;
        self.publish_binary_sensor(group_addr, app_addr, true).await;
    }

    pub async fn mqtt_light_off(&self, source: Option<u8>, group_addr: u8, app_addr: i64) {
        self.check_published(group_addr, app_addr).await;
        self.publish_state(
            state_topic(group_addr, app_addr),
            json!({"state": "OFF", "brightness": 0, "transition": 0,
                   "cbus_source_addr": source}),
        )
        .await;
        self.publish_binary_sensor(group_addr, app_addr, false)
            .await;
    }

    /// `MqttClient.lighting_group_binary_state`: state derived from a
    /// binary status report — no brightness on ON (a binary report has
    /// no level), brightness 0 on OFF, no transition either way.
    pub async fn mqtt_light_binary_state(
        &self,
        source: Option<u8>,
        group_addr: u8,
        app_addr: i64,
        light_on: bool,
    ) {
        self.check_published(group_addr, app_addr).await;
        let payload = if light_on {
            json!({"state": "ON", "cbus_source_addr": source})
        } else {
            json!({"state": "OFF", "cbus_source_addr": source, "brightness": 0})
        };
        self.publish_state(state_topic(group_addr, app_addr), payload)
            .await;
        self.publish_binary_sensor(group_addr, app_addr, light_on)
            .await;
    }

    pub async fn mqtt_light_ramp(
        &self,
        source: Option<u8>,
        group_addr: u8,
        app_addr: i64,
        duration: u32,
        level: u8,
    ) {
        self.check_published(group_addr, app_addr).await;
        self.publish_state(
            state_topic(group_addr, app_addr),
            json!({"state": "ON", "brightness": level, "transition": duration,
                   "cbus_source_addr": source}),
        )
        .await;
        self.publish_binary_sensor(group_addr, app_addr, level > 0)
            .await;
    }

    // ------------------------------------------------------- C-Bus events

    /// `CBusHandler` event relays -> MQTT.
    pub async fn on_cbus_event(self: &Arc<Self>, event: CBusEvent) {
        match event {
            CBusEvent::LightingOn { source, app, group } => {
                self.mqtt_light_on(source, group, app as i64).await;
            }
            CBusEvent::LightingOff { source, app, group } => {
                self.mqtt_light_off(source, group, app as i64).await;
            }
            CBusEvent::LightingRamp {
                source,
                app,
                group,
                duration,
                level,
            } => {
                self.mqtt_light_ramp(source, group, app as i64, duration, level)
                    .await;
            }
            CBusEvent::BinaryReport {
                app,
                block_start,
                states,
            } => {
                // `CBusHandler.on_binary_report`: only definite ON/OFF
                // states publish; missing/error slots are skipped but
                // still advance the group counter; events use source 0.
                let mut start = block_start;
                for state in states {
                    match state {
                        1 => {
                            self.mqtt_light_binary_state(Some(0), start, app as i64, true)
                                .await
                        }
                        2 => {
                            self.mqtt_light_binary_state(Some(0), start, app as i64, false)
                                .await
                        }
                        _ => {}
                    }
                    start = start.wrapping_add(1);
                }
            }
            CBusEvent::LevelReport {
                app,
                block_start,
                levels,
            } => {
                // `CBusHandler.on_level_report`: null slots are skipped but
                // still advance the group counter; events use source 0.
                let mut start = block_start;
                for val in levels {
                    if let Some(v) = val {
                        self.check_published(start, app as i64).await;
                        if v == 0 {
                            self.mqtt_light_off(Some(0), start, app as i64).await;
                        } else if v == 255 {
                            self.mqtt_light_on(Some(0), start, app as i64).await;
                        } else {
                            self.mqtt_light_ramp(Some(0), start, app as i64, 0, v).await;
                        }
                    }
                    start = start.wrapping_add(1);
                }
            }
            CBusEvent::ClockRequest { .. } => {
                if !self.no_clock {
                    let _ = self.pci().await.clock_datetime().await;
                }
            }
            CBusEvent::ConnectionLost => {
                self.group_db.lock().unwrap().clear();
            }
        }
    }

    // ------------------------------------------------------- MQTT commands

    /// `MqttClient._handle_message`: parse a /set command and enqueue the
    /// C-Bus send on the throttle (behind any queued status requests).
    /// Retained commands are stale broker state, not user intent — acting
    /// on them would replay old switch commands on every (re)subscribe.
    pub fn handle_publish(self: &Arc<Self>, topic: &str, payload: &[u8], retain: bool) {
        if retain && topic.starts_with(LIGHT_TOPIC_PREFIX) && topic.ends_with(TOPIC_SET_SUFFIX) {
            tracing::warn!("ignoring retained command on topic '{topic}'");
            return;
        }
        let cmd = match parse_set_command(topic, payload) {
            Ok(cmd) => cmd,
            Err(CommandError::NotACommandTopic) => return,
            Err(e) => {
                tracing::error!("ignoring publish on {topic}: {e}");
                return;
            }
        };
        tracing::info!(
            "command parsed: GA={}, App={}, state={}, brightness={}, transition={}",
            cmd.group_addr,
            cmd.app_addr,
            if cmd.light_on { "ON" } else { "OFF" },
            cmd.brightness,
            cmd.transition
        );
        let gw = self.clone();
        self.throttle.enqueue(async move {
            gw.switch_light(
                cmd.group_addr,
                cmd.app_addr,
                cmd.light_on,
                cmd.brightness,
                cmd.transition,
            )
            .await;
        });
    }

    /// `MqttClient.switchLight`: C-Bus send then MQTT echo
    /// (`cbus_source_addr: null`).
    async fn switch_light(
        &self,
        group_addr: u8,
        app_addr: i64,
        light_on: bool,
        brightness: u8,
        transition: u32,
    ) {
        // LightingSAL raises for apps outside 0x30..=0x5F before any send
        if !(0x30..=0x5f).contains(&app_addr) {
            tracing::error!("invalid lighting application address {app_addr}");
            return;
        }
        let app8 = app_addr as u8;
        let pci = self.pci().await;
        if light_on {
            if brightness == 255 && transition == 0 {
                if pci.lighting_group_on(&[group_addr], app8).await.is_ok() {
                    self.mqtt_light_on(None, group_addr, app_addr).await;
                }
            } else if pci
                .lighting_group_ramp(group_addr, app8, transition, brightness)
                .await
                .is_ok()
            {
                self.mqtt_light_ramp(None, group_addr, app_addr, transition, brightness)
                    .await;
            }
        } else if pci.lighting_group_off(&[group_addr], app8).await.is_ok() {
            self.mqtt_light_off(None, group_addr, app_addr).await;
        }
    }
}
