//! mqtt_topics.jsonl / ha_discovery.jsonl vector evaluation (used by the
//! cbus-vector-check binary).

use crate::discovery::{light_discovery, meta_discovery, AppLabels};
use crate::topics::{
    bin_sensor_conf_topic, bin_sensor_state_topic, conf_topic, ga_string, set_topic, state_topic,
    topic_group_address,
};
use serde_json::Value;

fn need_str<'a>(v: &'a Value, k: &str) -> Result<&'a str, String> {
    v.get(k)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("vector missing {k}"))
}

fn need_i64(v: &Value, k: &str) -> Result<i64, String> {
    v.get(k)
        .and_then(Value::as_i64)
        .ok_or_else(|| format!("vector missing {k}"))
}

/// Evaluate one `mqtt_topics.jsonl` vector.
pub fn check_topic(v: &Value) -> Result<(), String> {
    match need_str(v, "kind")? {
        "format" => {
            let ga = need_i64(v, "group_addr")? as u8;
            let app = need_i64(v, "app_addr")?;
            let checks: [(&str, String); 7] = [
                ("expect_ga_string_padded", ga_string(ga, app, true)),
                ("expect_ga_string_unpadded", ga_string(ga, app, false)),
                ("expect_set_topic", set_topic(ga, app)),
                ("expect_state_topic", state_topic(ga, app)),
                ("expect_conf_topic", conf_topic(ga, app)),
                (
                    "expect_bin_sensor_state_topic",
                    bin_sensor_state_topic(ga, app),
                ),
                (
                    "expect_bin_sensor_conf_topic",
                    bin_sensor_conf_topic(ga, app),
                ),
            ];
            for (key, got) in checks {
                let expect = need_str(v, key)?;
                if got != expect {
                    return Err(format!("{key}: {got:?} != {expect:?}"));
                }
            }
            Ok(())
        }
        "parse" => {
            let expect_error = v
                .get("expect_error")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            match topic_group_address(need_str(v, "topic")?) {
                Err(_) => {
                    if expect_error {
                        Ok(())
                    } else {
                        Err("unexpected parse error".into())
                    }
                }
                Ok((g, a)) => {
                    if expect_error {
                        return Err(format!("expected error, parsed ({g}, {a})"));
                    }
                    let eg = need_i64(v, "expect_group")?;
                    let ea = need_i64(v, "expect_app")?;
                    if g as i64 != eg || a != ea {
                        return Err(format!("parsed ({g},{a}) != ({eg},{ea})"));
                    }
                    Ok(())
                }
            }
        }
        other => Err(format!("unknown topic kind {other}")),
    }
}

fn labels_from_json(v: &Value) -> Result<Option<AppLabels>, String> {
    match v.get("labels") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(apps)) => {
            let mut out = AppLabels::new();
            for (app_str, entry) in apps {
                let app: i64 = app_str.parse().map_err(|_| "bad app key")?;
                let arr = entry.as_array().ok_or("bad labels entry")?;
                let name = arr
                    .first()
                    .and_then(Value::as_str)
                    .ok_or("bad app name")?
                    .to_string();
                let groups_obj = arr.get(1).and_then(Value::as_object).ok_or("bad groups")?;
                let mut groups = std::collections::BTreeMap::new();
                for (g_str, label) in groups_obj {
                    let g: u8 = g_str.parse().map_err(|_| "bad group key")?;
                    groups.insert(g, label.as_str().ok_or("bad label")?.to_string());
                }
                out.insert(app, (name, groups));
            }
            Ok(Some(out))
        }
        Some(other) => Err(format!("bad labels {other}")),
    }
}

/// Evaluate one `ha_discovery.jsonl` vector.
pub fn check_ha(v: &Value) -> Result<(), String> {
    let expect_qos = need_i64(v, "expect_qos")?;
    let expect_retain = v
        .get("expect_retain")
        .and_then(Value::as_bool)
        .ok_or("vector missing expect_retain")?;
    // config+state publishes are always qos 1 retain true in the gateway
    if expect_qos != 1 || !expect_retain {
        return Err(format!(
            "unexpected qos/retain {expect_qos}/{expect_retain}"
        ));
    }

    if v.get("meta").and_then(Value::as_bool).unwrap_or(false) {
        let (topic, config) = meta_discovery();
        let et = need_str(v, "expect_topic")?;
        if topic != et {
            return Err(format!("meta topic {topic:?} != {et:?}"));
        }
        let ec = v.get("expect_config").ok_or("missing expect_config")?;
        if &config != ec {
            return Err("meta config mismatch".into());
        }
        return Ok(());
    }

    let ga = need_i64(v, "group_addr")? as u8;
    let app = need_i64(v, "app_addr")?;
    let labels = labels_from_json(v)?;
    let d = light_discovery(ga, app, labels.as_ref());

    let es = need_str(v, "expect_subscribe")?;
    if d.subscribe_topic != es {
        return Err(format!("subscribe {:?} != {es:?}", d.subscribe_topic));
    }
    let esq = need_i64(v, "expect_subscribe_qos")?;
    if esq != 2 {
        return Err(format!("subscribe qos {esq} != 2"));
    }
    let elt = need_str(v, "expect_light_config_topic")?;
    if d.light_config_topic != elt {
        return Err(format!("light topic {:?} != {elt:?}", d.light_config_topic));
    }
    let elc = v.get("expect_light_config").ok_or("missing light config")?;
    if &d.light_config != elc {
        return Err(format!(
            "light config mismatch: {} != {}",
            d.light_config, elc
        ));
    }
    let est = need_str(v, "expect_sensor_config_topic")?;
    if d.sensor_config_topic != est {
        return Err(format!(
            "sensor topic {:?} != {est:?}",
            d.sensor_config_topic
        ));
    }
    let esc = v
        .get("expect_sensor_config")
        .ok_or("missing sensor config")?;
    if &d.sensor_config != esc {
        return Err(format!(
            "sensor config mismatch: {} != {}",
            d.sensor_config, esc
        ));
    }
    Ok(())
}
