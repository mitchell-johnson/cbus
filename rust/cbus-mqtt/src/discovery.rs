//! HA discovery payload builders. Port of
//! `cbus/daemon/mqtt_gateway.py::MqttClient.publish_light` /
//! `publish_all_lights` (payload construction only, no I/O).

use crate::topics::{
    bin_sensor_conf_topic, bin_sensor_state_topic, conf_topic, ga_string, set_topic, state_topic,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// `{app_addr: (app_name, {group: label})}`
pub type AppLabels = BTreeMap<i64, (String, BTreeMap<u8, String>)>;

pub const SW_VERSION: &str = "cmqttd https://github.com/mitchell-johnson/cbus";

pub fn default_light_name(group_addr: u8, app_addr: i64) -> String {
    format!("C-Bus Light {}", ga_string(group_addr, app_addr, true))
}

#[derive(Debug, Clone)]
pub struct LightDiscovery {
    /// set topic to subscribe (qos 2)
    pub subscribe_topic: String,
    pub light_config_topic: String,
    pub light_config: Value,
    pub sensor_config_topic: String,
    pub sensor_config: Value,
}

pub fn light_discovery(group_addr: u8, app_addr: i64, app_labels: Option<&AppLabels>) -> LightDiscovery {
    let default_name = default_light_name(group_addr, app_addr);
    let uid = format!("cbus_light_{}", ga_string(group_addr, app_addr, false));
    let mut name = default_name.clone();
    if let Some(labels) = app_labels {
        if let Some((_, groups)) = labels.get(&app_addr) {
            if let Some(label) = groups.get(&group_addr) {
                name = label.clone();
            }
        }
    }
    let connections = json!([
        ["cbus_group_address", group_addr.to_string()],
        ["cbus_application_address", app_addr.to_string()]
    ]);
    let light_config = json!({
        "name": name,
        "unique_id": uid,
        "cmd_t": set_topic(group_addr, app_addr),
        "stat_t": state_topic(group_addr, app_addr),
        "schema": "json",
        "brightness": true,
        "device": {
            "identifiers": [uid],
            "connections": connections,
            "sw_version": SW_VERSION,
            "name": default_name,
            "manufacturer": "Clipsal",
            "model": "C-Bus Lighting Application",
            "via_device": "cmqttd",
        },
    });
    let sensor_uid = format!(
        "cbus_bin_sensor_{}",
        ga_string(group_addr, app_addr, false)
    );
    let sensor_config = json!({
        "name": format!("{name} (as binary sensor)"),
        "unique_id": sensor_uid,
        "stat_t": bin_sensor_state_topic(group_addr, app_addr),
        "device": {
            "identifiers": [sensor_uid],
            "connections": connections,
            "sw_version": SW_VERSION,
            "name": default_name,
            "manufacturer": "Clipsal",
            "model": "C-Bus Lighting Application",
            "via_device": "cmqttd",
        },
    });
    LightDiscovery {
        subscribe_topic: set_topic(group_addr, app_addr),
        light_config_topic: conf_topic(group_addr, app_addr),
        light_config,
        sensor_config_topic: bin_sensor_conf_topic(group_addr, app_addr),
        sensor_config,
    }
}

/// The `cbus_cmqttd` root device config: (topic, payload).
pub fn meta_discovery() -> (String, Value) {
    let meta_topic = "homeassistant/binary_sensor/cbus_cmqttd";
    (
        format!("{meta_topic}/config"),
        json!({
            "~": meta_topic,
            "name": "cmqttd",
            "unique_id": "cmqttd",
            "stat_t": "~/state",
            "device": {
                "identifiers": ["cmqttd"],
                "sw_version": SW_VERSION,
                "name": "cmqttd",
                "manufacturer": "micolous",
                "model": "libcbus",
            },
        }),
    )
}
