//! MQTT <-> C-Bus glue. Port of `cbus/daemon/mqtt_gateway.py`
//! (`CBusHandler` event relays + `MqttClient` helpers) onto rumqttc.

use crate::throttle::Throttle;
use cbus_mqtt::discovery::{light_discovery, meta_discovery, AppLabels};
use cbus_mqtt::topics::{
    bin_sensor_state_topic, state_topic, topic_group_address, LIGHT_TOPIC_PREFIX,
    TOPIC_SET_SUFFIX,
};
use cbus_transport::pci::{CBusEvent, PciClient};
use rumqttc::{AsyncClient, QoS};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::RwLock;

pub struct Gateway {
    pub mqtt: AsyncClient,
    pub pci: RwLock<Arc<PciClient>>,
    pub throttle: Throttle,
    pub labels: AppLabels,
    pub no_clock: bool,
    /// groupDB: app -> group -> discovery-config-published
    group_db: Mutex<HashMap<i64, HashMap<u8, bool>>>,
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
        })
    }

    async fn pci(&self) -> Arc<PciClient> {
        self.pci.read().await.clone()
    }

    // ------------------------------------------------------------- startup

    /// `MqttClient.__aenter__`: subscribe the wildcard, publish the meta
    /// config, publish discovery for every labelled group, then enqueue the
    /// 384 throttled level status requests (apps 0x30..=0x5F, blocks
    /// 0,32..224).
    pub async fn on_connected(self: &Arc<Self>) {
        let _ = self
            .mqtt
            .subscribe("homeassistant/light/#", QoS::AtMostOnce)
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

        self.queue_status_requests();
    }

    pub fn queue_status_requests(self: &Arc<Self>) {
        for app in 0x30..=0x5fu8 {
            for block in (0u16..256).step_by(32) {
                let gw = self.clone();
                let block = block as u8;
                self.throttle.enqueue(async move {
                    let _ = gw.pci().await.request_status(block, app).await;
                });
            }
        }
    }

    // ----------------------------------------------------------- discovery

    /// `MqttClient.publish_light`
    pub async fn publish_light(&self, group_addr: u8, app_addr: i64, with_labels: bool) {
        let labels = if with_labels { Some(&self.labels) } else { None };
        let d = light_discovery(group_addr, app_addr, labels);
        let _ = self.mqtt.subscribe(d.subscribe_topic, QoS::ExactlyOnce).await;
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
        self.publish_binary_sensor(group_addr, app_addr, false).await;
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
        self.publish_binary_sensor(group_addr, app_addr, level > 0).await;
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
    pub fn handle_publish(self: &Arc<Self>, topic: &str, payload: &[u8]) {
        if !(topic.starts_with(LIGHT_TOPIC_PREFIX) && topic.ends_with(TOPIC_SET_SUFFIX)) {
            return;
        }
        let (group_addr, app_addr) = match topic_group_address(topic) {
            Ok(x) => x,
            Err(e) => {
                tracing::error!("invalid group address in topic {topic}: {e}");
                return;
            }
        };
        let v: Value = match serde_json::from_slice(payload) {
            Ok(v) => v,
            Err(e) => {
                tracing::error!("JSON parse error in {topic}: {e}");
                return;
            }
        };
        let state = match v.get("state").and_then(Value::as_str) {
            Some(s) => s,
            None => {
                tracing::error!("missing 'state' field in payload for topic {topic}");
                return;
            }
        };
        let light_on = state.to_uppercase() == "ON";

        // brightness: default 255, int-cast, clamped 0..=255
        let brightness = match v.get("brightness") {
            Some(b) if b.is_number() => {
                let f = b.as_f64().unwrap_or(255.0);
                (f.trunc().clamp(0.0, 255.0)) as u8
            }
            _ => 255,
        };
        // transition: default 0, int-cast, clamped >= 0
        let transition = match v.get("transition") {
            Some(t) if t.is_number() => {
                let f = t.as_f64().unwrap_or(0.0);
                f.trunc().max(0.0) as u32
            }
            _ => 0,
        };
        tracing::info!(
            "command parsed: GA={group_addr}, App={app_addr}, state={}, \
             brightness={brightness}, transition={transition}",
            if light_on { "ON" } else { "OFF" }
        );
        let gw = self.clone();
        self.throttle.enqueue(async move {
            gw.switch_light(group_addr, app_addr, light_on, brightness, transition)
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
