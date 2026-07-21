//! HA discovery payload construction with project labels: label lookup,
//! the device-name-stays-default quirk, sensor naming and the meta config.

use cbus_mqtt::discovery::{
    default_light_name, light_discovery, meta_discovery, AppLabels, SW_VERSION,
};
use std::collections::BTreeMap;

fn labels(app: i64, group: u8, label: &str) -> AppLabels {
    let mut groups = BTreeMap::new();
    groups.insert(group, label.to_string());
    let mut l = AppLabels::new();
    l.insert(app, ("Lighting".to_string(), groups));
    l
}

#[test]
fn label_replaces_entity_name() {
    let l = labels(56, 10, "Lounge");
    let d = light_discovery(10, 56, Some(&l));
    assert_eq!(d.light_config["name"], "Lounge");
    assert_eq!(d.sensor_config["name"], "Lounge (as binary sensor)");
}

#[test]
fn device_name_stays_default_even_when_labelled() {
    // Python quirk: the device block keeps "C-Bus Light NNN" regardless
    let l = labels(56, 10, "Lounge");
    let d = light_discovery(10, 56, Some(&l));
    assert_eq!(d.light_config["device"]["name"], "C-Bus Light 010");
    assert_eq!(d.sensor_config["device"]["name"], "C-Bus Light 010");
}

#[test]
fn label_for_other_group_does_not_apply() {
    let l = labels(56, 11, "Deck");
    let d = light_discovery(10, 56, Some(&l));
    assert_eq!(d.light_config["name"], "C-Bus Light 010");
}

#[test]
fn label_for_other_app_does_not_leak() {
    // group 10 labelled on app 48 must not label group 10 on app 56
    let l = labels(48, 10, "Deck");
    let d = light_discovery(10, 56, Some(&l));
    assert_eq!(d.light_config["name"], "C-Bus Light 010");
}

#[test]
fn alt_app_label_applies_with_padded_identity() {
    let l = labels(48, 11, "Deck");
    let d = light_discovery(11, 48, Some(&l));
    assert_eq!(d.light_config["name"], "Deck");
    assert_eq!(d.light_config["unique_id"], "cbus_light_048_011");
    assert_eq!(d.light_config["device"]["name"], "C-Bus Light 048_011");
}

#[test]
fn no_labels_and_empty_labels_agree() {
    let empty = AppLabels::new();
    let d1 = light_discovery(3, 56, None);
    let d2 = light_discovery(3, 56, Some(&empty));
    assert_eq!(d1.light_config, d2.light_config);
    assert_eq!(d1.sensor_config, d2.sensor_config);
}

#[test]
fn default_name_padding_forms() {
    assert_eq!(default_light_name(7, 56), "C-Bus Light 007");
    assert_eq!(default_light_name(255, 56), "C-Bus Light 255");
    assert_eq!(default_light_name(7, 48), "C-Bus Light 048_007");
}

#[test]
fn device_connections_carry_both_addresses() {
    let d = light_discovery(11, 48, None);
    let conns = &d.light_config["device"]["connections"];
    assert_eq!(conns[0][0], "cbus_group_address");
    assert_eq!(conns[0][1], "11");
    assert_eq!(conns[1][0], "cbus_application_address");
    assert_eq!(conns[1][1], "48");
}

#[test]
fn light_config_advertises_json_schema_brightness() {
    let d = light_discovery(1, 56, None);
    assert_eq!(d.light_config["schema"], "json");
    assert_eq!(d.light_config["brightness"], true);
    // the paired binary sensor has neither
    assert!(d.sensor_config.get("schema").is_none());
    assert!(d.sensor_config.get("brightness").is_none());
}

#[test]
fn sw_version_advertised_everywhere() {
    let d = light_discovery(1, 56, None);
    assert_eq!(d.light_config["device"]["sw_version"], SW_VERSION);
    assert_eq!(d.sensor_config["device"]["sw_version"], SW_VERSION);
    let (_, meta) = meta_discovery();
    assert_eq!(meta["device"]["sw_version"], SW_VERSION);
}

#[test]
fn meta_discovery_identity() {
    let (topic, config) = meta_discovery();
    assert_eq!(topic, "homeassistant/binary_sensor/cbus_cmqttd/config");
    assert_eq!(config["~"], "homeassistant/binary_sensor/cbus_cmqttd");
    assert_eq!(config["unique_id"], "cmqttd");
    assert_eq!(config["stat_t"], "~/state");
    assert_eq!(config["device"]["manufacturer"], "micolous");
}
