//! MQTT-to-C-Bus event relays and command handling built on rumqttc.
//!
//! Outbound C-Bus traffic runs through ordered command, command-readback,
//! and status-sweep lanes instead of the old single 0.2 s throttle queue.
//! Each worker processes strictly in order, and the adaptive flow controller
//! in cbus-transport paces the wire (giving command frames priority over
//! status traffic).

use cbus_mqtt::command::{parse_set_command, CommandError, SetCommand};
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
use tokio::sync::{mpsc, watch, Mutex as AsyncMutex, RwLock};

/// One status request of a sweep batch: (app, block, level_request).
type StatusProbe = (u8, u8, bool);
/// One post-command physical level readback: (app, block, group-for-log).
type CommandReadback = (u8, u8, u8);

#[derive(Clone, Copy)]
enum LightUpdate {
    On,
    Off,
    Binary(bool),
    Ramp { duration: u32, level: u8 },
}

/// State topic advertised by [`meta_discovery`]. `ON` means the current
/// C-Bus transport is connected; `OFF` means its live caches were invalidated.
const BRIDGE_STATE_TOPIC: &str = "homeassistant/binary_sensor/cbus_cmqttd/state";

/// Non-retained operational receipts for MQTT lighting commands. The regular
/// light state topic remains the Home Assistant compatibility contract.
const COMMAND_RESULT_TOPIC: &str = "cmqttd/cbus/command_result";

pub struct Gateway {
    mqtt: AsyncClient,
    pci: RwLock<Arc<PciClient>>,
    /// Changes whenever reconnect installs a fresh transport. Command workers
    /// use this as a barrier instead of submitting queued commands to a dead
    /// client during the reconnect window.
    pci_generation: watch::Sender<u64>,
    /// Ordered lane for /set commands (FIFO, one at a time).
    commands: mpsc::UnboundedSender<SetCommand>,
    /// Ordered lane for post-command level readbacks. Kept separate from a
    /// potentially long configured sweep so live commands are re-observed
    /// promptly even while startup discovery is still draining.
    readbacks: mpsc::UnboundedSender<CommandReadback>,
    /// Ordered lane for status-sweep batches (FIFO, one batch at a time,
    /// so an overlapping resync can never interleave two sweeps).
    sweeps: mpsc::UnboundedSender<Vec<StatusProbe>>,
    labels: AppLabels,
    no_clock: bool,
    /// groupDB: app -> group -> discovery-config-published
    group_db: Mutex<HashMap<i64, HashMap<u8, bool>>>,
    /// Latest physical-observation sequence per application/group. The guard
    /// stays held while a state publish is queued so a command echo and a bus
    /// observation cannot pass each other between the freshness check and the
    /// MQTT request channel.
    observation_sequences: AsyncMutex<HashMap<(i64, u8), u64>>,
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
        let (commands, cmd_rx) = mpsc::unbounded_channel();
        let (readbacks, readback_rx) = mpsc::unbounded_channel();
        let (sweeps, sweep_rx) = mpsc::unbounded_channel();
        let (pci_generation, _) = watch::channel(0);
        let gw = Arc::new(Gateway {
            mqtt,
            pci: RwLock::new(pci),
            pci_generation,
            commands,
            readbacks,
            sweeps,
            labels,
            no_clock,
            group_db: Mutex::new(HashMap::new()),
            observation_sequences: AsyncMutex::new(HashMap::new()),
            status_requests_queued: AtomicBool::new(false),
        });
        gw.clone().spawn_workers(cmd_rx, readback_rx, sweep_rx);
        gw
    }

    /// The three ordered outbound lanes. MQTT commands wait for their correlated
    /// PCI delivery confirmation before the next command is taken. Physical
    /// readback and status sweeps remain ordered background traffic.
    fn spawn_workers(
        self: Arc<Self>,
        mut cmd_rx: mpsc::UnboundedReceiver<SetCommand>,
        mut readback_rx: mpsc::UnboundedReceiver<CommandReadback>,
        mut sweep_rx: mpsc::UnboundedReceiver<Vec<StatusProbe>>,
    ) {
        let gw = self.clone();
        tokio::spawn(async move {
            while let Some(cmd) = cmd_rx.recv().await {
                gw.switch_light(cmd).await;
            }
        });
        let gw = self.clone();
        tokio::spawn(async move {
            while let Some((app, block, group)) = readback_rx.recv().await {
                tracing::info!(
                    "requesting post-command level status for app={app} block={block} group={group}"
                );
                if let Err(error) = gw
                    .connected_pci()
                    .await
                    .request_status(block, app, true)
                    .await
                {
                    tracing::error!(
                        "MQTT lighting readback request failed for app={app} \
                         block={block} group={group}: {error}"
                    );
                }
            }
        });
        tokio::spawn(async move {
            while let Some(batch) = sweep_rx.recv().await {
                for (app, block, level_request) in batch {
                    let kind = if level_request { "level" } else { "binary" };
                    tracing::info!("requesting {kind} status for app={app} block={block}");
                    if let Err(error) = self
                        .pci()
                        .await
                        .request_status(block, app, level_request)
                        .await
                    {
                        tracing::error!(
                            "{kind} status request failed for app={app} block={block}: {error}"
                        );
                    }
                }
            }
        });
    }

    /// The current PCI client (swapped out on reconnect).
    pub async fn pci(&self) -> Arc<PciClient> {
        self.pci.read().await.clone()
    }

    /// Swap in a fresh PCI client after a reconnect.
    pub async fn set_pci(&self, pci: Arc<PciClient>) {
        *self.pci.write().await = pci;
        self.pci_generation.send_modify(|generation| {
            *generation = generation.wrapping_add(1);
        });
    }

    /// Wait for a connected transport. An MQTT command that was already sent
    /// when the old connection failed reports an uncertain outcome and is not
    /// replayed; only later, unsent commands wait on this reconnect barrier.
    async fn connected_pci(&self) -> Arc<PciClient> {
        let mut generation = self.pci_generation.subscribe();
        loop {
            let pci = self.pci().await;
            if pci.is_connected() {
                return pci;
            }
            // The sender lives as long as Gateway, so closure is unreachable.
            let _ = generation.changed().await;
        }
    }

    // ------------------------------------------------------------- startup

    /// `MqttClient.__aenter__`: subscribe the /set command wildcard,
    /// publish the meta config, publish discovery for every labelled
    /// group, then queue the configured status sweep.
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

        self.publish_bridge_state(self.pci().await.is_connected())
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

    /// Publish that reconnect installed a fresh live transport. Retained light
    /// state is refreshed separately by the forced configured status sweep.
    pub async fn on_cbus_reconnected(&self) {
        self.publish_bridge_state(true).await;
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

        // one batch per invocation: binary status first (reliable ON/OFF
        // presence), then level status so dimmer brightness can overwrite
        // the binary fallback, per block, apps ascending
        let mut batch: Vec<StatusProbe> = Vec::new();
        for app in apps {
            let blocks = self.configured_status_blocks(app);
            if blocks.is_empty() {
                tracing::debug!("skipping status requests for app {app}; no real groups");
                continue;
            }
            for &block in &blocks {
                for level_request in [false, true] {
                    batch.push((app as u8, block, level_request));
                }
            }
        }
        if !batch.is_empty() && self.sweeps.send(batch).is_err() {
            tracing::warn!("sweep worker gone; status requests dropped");
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

    async fn publish_bridge_state(&self, connected: bool) {
        let payload = if connected { "ON" } else { "OFF" };
        if let Err(error) = self
            .mqtt
            .publish(BRIDGE_STATE_TOPIC, QoS::AtLeastOnce, true, payload)
            .await
        {
            tracing::error!("cannot publish C-Bus connection state {payload}: {error}");
        }
    }

    async fn publish_command_result(
        &self,
        command: &SetCommand,
        delivery: &str,
        readback: &str,
        error: Option<&str>,
    ) {
        let mut payload = json!({
            "application": command.app_addr,
            "group": command.group_addr,
            "requested_state": if command.light_on { "ON" } else { "OFF" },
            "brightness": command.brightness,
            "transition": command.transition,
            "delivery": delivery,
            "readback": readback,
        });
        if let Some(error) = error {
            payload["error"] = Value::String(error.to_string());
        }
        if let Err(error) = self
            .mqtt
            .publish(
                COMMAND_RESULT_TOPIC,
                QoS::AtLeastOnce,
                false,
                payload.to_string(),
            )
            .await
        {
            tracing::error!("cannot publish MQTT command result: {error}");
        }
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

    async fn mqtt_light_on(&self, source: Option<u8>, group_addr: u8, app_addr: i64) {
        self.check_published(group_addr, app_addr).await;
        self.publish_state(
            state_topic(group_addr, app_addr),
            json!({"state": "ON", "brightness": 255, "transition": 0,
                   "cbus_source_addr": source}),
        )
        .await;
        self.publish_binary_sensor(group_addr, app_addr, true).await;
    }

    async fn mqtt_light_off(&self, source: Option<u8>, group_addr: u8, app_addr: i64) {
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
    async fn mqtt_light_binary_state(
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

    async fn mqtt_light_ramp(
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

    async fn publish_light_update(
        &self,
        source: Option<u8>,
        group_addr: u8,
        app_addr: i64,
        update: LightUpdate,
    ) {
        match update {
            LightUpdate::On => self.mqtt_light_on(source, group_addr, app_addr).await,
            LightUpdate::Off => self.mqtt_light_off(source, group_addr, app_addr).await,
            LightUpdate::Binary(state) => {
                self.mqtt_light_binary_state(source, group_addr, app_addr, state)
                    .await
            }
            LightUpdate::Ramp { duration, level } => {
                self.mqtt_light_ramp(source, group_addr, app_addr, duration, level)
                    .await
            }
        }
    }

    /// Record and publish one genuine bus observation. Holding the sequence
    /// guard until both retained state requests are queued gives a concurrent
    /// requested-state echo a deterministic before/after relationship.
    async fn publish_observed_light(
        &self,
        source: Option<u8>,
        group_addr: u8,
        app_addr: i64,
        update: LightUpdate,
    ) {
        let mut sequences = self.observation_sequences.lock().await;
        let sequence = sequences.entry((app_addr, group_addr)).or_default();
        *sequence = sequence.wrapping_add(1);
        self.publish_light_update(source, group_addr, app_addr, update)
            .await;
    }

    async fn observation_sequence(&self, group_addr: u8, app_addr: i64) -> u64 {
        self.observation_sequences
            .lock()
            .await
            .get(&(app_addr, group_addr))
            .copied()
            .unwrap_or_default()
    }

    /// Publish the compatibility echo only if no same-group physical evidence
    /// arrived after this command began delivery. Unrelated groups have their
    /// own sequence and never suppress the echo.
    async fn publish_command_echo_if_fresh(
        &self,
        observed_before_send: u64,
        group_addr: u8,
        app_addr: i64,
        update: LightUpdate,
    ) -> bool {
        let sequences = self.observation_sequences.lock().await;
        let observed_now = sequences
            .get(&(app_addr, group_addr))
            .copied()
            .unwrap_or_default();
        if observed_now != observed_before_send {
            return false;
        }
        self.publish_light_update(None, group_addr, app_addr, update)
            .await;
        true
    }

    // ------------------------------------------------------- C-Bus events

    /// `CBusHandler` event relays -> MQTT.
    pub async fn on_cbus_event(self: &Arc<Self>, event: CBusEvent) {
        match event {
            CBusEvent::LightingOn { source, app, group } => {
                self.publish_observed_light(source, group, app as i64, LightUpdate::On)
                    .await;
            }
            CBusEvent::LightingOff { source, app, group } => {
                self.publish_observed_light(source, group, app as i64, LightUpdate::Off)
                    .await;
            }
            CBusEvent::LightingRamp {
                source,
                app,
                group,
                duration,
                level,
            } => {
                self.publish_observed_light(
                    source,
                    group,
                    app as i64,
                    LightUpdate::Ramp { duration, level },
                )
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
                            self.publish_observed_light(
                                Some(0),
                                start,
                                app as i64,
                                LightUpdate::Binary(true),
                            )
                            .await
                        }
                        2 => {
                            self.publish_observed_light(
                                Some(0),
                                start,
                                app as i64,
                                LightUpdate::Binary(false),
                            )
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
                        let update = if v == 0 {
                            LightUpdate::Off
                        } else if v == 255 {
                            LightUpdate::On
                        } else {
                            LightUpdate::Ramp {
                                duration: 0,
                                level: v,
                            }
                        };
                        self.publish_observed_light(Some(0), start, app as i64, update)
                            .await;
                    }
                    start = start.wrapping_add(1);
                }
            }
            CBusEvent::ClockRequest { .. } => {
                if !self.no_clock {
                    let _ = self.pci().await.clock_datetime().await;
                }
            }
            CBusEvent::AirconCommand { .. }
            | CBusEvent::AirconStatus { .. }
            | CBusEvent::AudioCommand { .. }
            | CBusEvent::AudioEvent { .. }
            | CBusEvent::SecurityCommand { .. }
            | CBusEvent::SecurityEvent { .. }
            | CBusEvent::TriggerEvent { .. }
            | CBusEvent::TriggerIndicatorKill { .. }
            | CBusEvent::EnableSet { .. }
            | CBusEvent::DynamicLabel { .. }
            | CBusEvent::TemperatureBroadcast { .. }
            | CBusEvent::ClockDate { .. }
            | CBusEvent::ClockTime { .. } => {
                // These application events are consumed by the embedded
                // C-Gate service. MQTT's lighting contract is unchanged.
            }
            CBusEvent::ConnectionLost => {
                self.group_db.lock().unwrap().clear();
                self.publish_bridge_state(false).await;
            }
        }
    }

    // ------------------------------------------------------- MQTT commands

    /// `MqttClient._handle_message`: parse a /set command and hand it to
    /// the ordered command lane (user commands outrank queued status
    /// sweeps on the wire). Retained commands are stale broker state,
    /// not user intent — acting on them would replay old switch commands
    /// on every (re)subscribe.
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
        if self.commands.send(cmd).is_err() {
            tracing::warn!("command worker gone; dropping command");
        }
    }

    /// `MqttClient.switchLight`: C-Bus send then MQTT echo
    /// (`cbus_source_addr: null`).
    async fn switch_light(&self, command: SetCommand) {
        let group_addr = command.group_addr;
        let app_addr = command.app_addr;
        let light_on = command.light_on;
        let brightness = command.brightness;
        let transition = command.transition;
        // LightingSAL raises for apps outside 0x30..=0x5F before any send
        if !(0x30..=0x5f).contains(&app_addr) {
            tracing::error!("invalid lighting application address {app_addr}");
            self.publish_command_result(
                &command,
                "rejected-before-send",
                "not-requested",
                Some("invalid lighting application address"),
            )
            .await;
            return;
        }
        let app8 = app_addr as u8;
        let pci = self.connected_pci().await;
        // Observations received while this command was merely waiting for a
        // replacement transport precede its delivery and must not suppress
        // the newer request. Start the comparison at actual submission.
        let observed_before_send = self.observation_sequence(group_addr, app_addr).await;
        let delivery = if light_on {
            if brightness == 255 && transition == 0 {
                pci.lighting_group_on_confirmed(&[group_addr], app8).await
            } else {
                pci.lighting_group_ramp_confirmed(group_addr, app8, transition, brightness)
                    .await
            }
        } else {
            pci.lighting_group_off_confirmed(&[group_addr], app8).await
        };
        if let Err(error) = delivery {
            let detail = error.to_string();
            let outcome = if detail == "PCI rejected command" {
                "rejected"
            } else {
                // A timeout or lost socket cannot prove whether bytes already
                // reached the interface. Never replay that command implicitly.
                "uncertain"
            };
            tracing::error!(
                "MQTT lighting delivery {outcome} for app={app_addr} group={group_addr} \
                 state={}: {error}",
                if light_on { "ON" } else { "OFF" }
            );
            self.publish_command_result(&command, outcome, "not-requested", Some(&detail))
                .await;
            return;
        }

        // Compatibility echo: this records the requested value only. It does
        // not populate C-Gate's physical cache; the following level request
        // supplies the authoritative observation when the network replies.
        let requested_update = if light_on {
            if brightness == 255 && transition == 0 {
                LightUpdate::On
            } else {
                LightUpdate::Ramp {
                    duration: transition,
                    level: brightness,
                }
            }
        } else {
            LightUpdate::Off
        };
        if !self
            .publish_command_echo_if_fresh(
                observed_before_send,
                group_addr,
                app_addr,
                requested_update,
            )
            .await
        {
            tracing::info!(
                "suppressing requested-state echo for app={app_addr} group={group_addr}; \
                 newer physical observation already published"
            );
        }

        if self
            .readbacks
            .send((app8, group_addr & 0xe0, group_addr))
            .is_err()
        {
            tracing::error!(
                "MQTT lighting readback queue failed for app={app_addr} group={group_addr}"
            );
            self.publish_command_result(
                &command,
                "confirmed",
                "queue-failed",
                Some("status worker unavailable"),
            )
            .await;
            return;
        }
        self.publish_command_result(&command, "confirmed", "queued", None)
            .await;
    }
}
