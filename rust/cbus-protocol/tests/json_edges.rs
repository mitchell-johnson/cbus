//! Canonical-JSON codec error paths and quirks: unknown discriminators,
//! missing fields, the empty-confirmation-string rule and round trips of
//! representative complex packets.

use cbus_protocol::json::{packet_from_json, packet_to_json, sal_from_json, JsonObject};
use cbus_protocol::packet::Packet;
use serde_json::json;

#[test]
fn packet_to_json_none_is_null() {
    assert_eq!(packet_to_json(None), serde_json::Value::Null);
}

#[test]
fn invalid_packet_to_json() {
    assert_eq!(
        packet_to_json(Some(&Packet::Invalid)),
        json!({"type": "invalid"})
    );
}

#[test]
fn unknown_packet_type_rejected() {
    assert!(packet_from_json(&json!({"type": "warp_drive"})).is_err());
}

#[test]
fn missing_type_field_rejected() {
    assert!(packet_from_json(&json!({"application": 56})).is_err());
}

#[test]
fn pm_with_no_sals_cannot_be_built() {
    // Python derives the packet application from the SALs; empty = error
    let v = json!({
        "type": "point_to_multipoint", "checksum": true,
        "priority_class": 0, "source_address": null,
        "confirmation": null, "application": 56, "sals": []});
    assert!(packet_from_json(&v).is_err());
}

#[test]
fn empty_confirmation_string_means_none() {
    // Python: conf.encode('ascii') if conf else None — "" is falsy
    let v = json!({
        "type": "point_to_multipoint", "checksum": true,
        "priority_class": 0, "source_address": null,
        "confirmation": "", "application": 56,
        "sals": [{"sal": "lighting_on", "application": 56,
                  "group_address": 1}]});
    let obj = packet_from_json(&v).unwrap();
    let JsonObject::Packet(p) = obj else {
        panic!("expected packet");
    };
    assert_eq!(p.meta().unwrap().confirmation, None);
}

#[test]
fn non_string_confirmation_rejected() {
    let v = json!({
        "type": "point_to_multipoint", "checksum": true,
        "priority_class": 0, "source_address": null,
        "confirmation": 104, "application": 56,
        "sals": [{"sal": "lighting_on", "application": 56,
                  "group_address": 1}]});
    assert!(packet_from_json(&v).is_err());
}

#[test]
fn unknown_sal_discriminator_rejected() {
    assert!(sal_from_json(&json!({"sal": "lighting_disco"})).is_err());
}

#[test]
fn sal_missing_group_address_rejected() {
    assert!(sal_from_json(&json!({"sal": "lighting_on", "application": 56})).is_err());
}

#[test]
fn unknown_cal_discriminator_rejected() {
    let v = json!({"type": "cal", "cal": "teleport"});
    assert!(packet_from_json(&v).is_err());
}

#[test]
fn reply_cal_bad_hex_rejected() {
    let v = json!({"type": "cal", "cal": "reply", "parameter": 1,
                   "data_hex": "zz"});
    assert!(packet_from_json(&v).is_err());
}

#[test]
fn unknown_report_discriminator_rejected() {
    let v = json!({"type": "point_to_point", "checksum": true,
        "priority_class": 0, "source_address": null, "confirmation": null,
        "unit_address": 1,
        "cals": [{"cal": "extended_status", "externally_initiated": false,
                  "child_application": 56, "block_start": 0,
                  "report": {"report": "hologram"}}]});
    assert!(packet_from_json(&v).is_err());
}

#[test]
fn bare_sal_has_no_encode_packet() {
    let obj = packet_from_json(&json!({"type": "sal", "sal": "clock_request"})).unwrap();
    assert_eq!(obj.encode().unwrap(), vec![0x11, 0x03]);
    assert!(obj.encode_packet().is_err());
}

#[test]
fn level_report_with_nulls_roundtrips() {
    let v = json!({
        "type": "point_to_point", "checksum": true, "priority_class": 2,
        "source_address": 153, "confirmation": null,
        "unit_address": 153, "bridged": false, "hops": [],
        "cals": [{"cal": "extended_status", "externally_initiated": false,
                  "child_application": 56, "block_start": 0,
                  "report": {"report": "level",
                             "levels": [255, 0, null, 128]}}]});
    let obj = packet_from_json(&v).unwrap();
    let JsonObject::Packet(p) = obj else {
        panic!("expected packet");
    };
    assert_eq!(packet_to_json(Some(&p)), v);
}

#[test]
fn confirmation_packet_roundtrips() {
    let v = json!({"type": "confirmation", "code": "z", "success": false});
    let obj = packet_from_json(&v).unwrap();
    let JsonObject::Packet(p) = obj else {
        panic!("expected packet");
    };
    assert_eq!(packet_to_json(Some(&p)), v);
}

#[test]
fn device_management_roundtrips() {
    let v = json!({"type": "device_management", "checksum": false,
        "priority_class": 2, "source_address": null, "confirmation": "h",
        "parameter": 48, "value": 121});
    let obj = packet_from_json(&v).unwrap();
    let JsonObject::Packet(p) = obj else {
        panic!("expected packet");
    };
    assert_eq!(packet_to_json(Some(&p)), v);
}

#[test]
fn binary_report_object_encodes_standalone() {
    let obj = packet_from_json(&json!({"type": "binary_report",
                                       "group_states": [0, 1, 2, 3]}))
    .unwrap();
    assert_eq!(obj.encode().unwrap(), vec![0b11100100]);
}

#[test]
fn temperature_json_keeps_float_precision() {
    let v = json!({"sal": "temperature_broadcast", "group_address": 7,
                   "temperature": 0.25});
    let s = sal_from_json(&v).unwrap();
    assert_eq!(cbus_protocol::json::sal_to_json(&s), v);
}
