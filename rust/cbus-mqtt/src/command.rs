//! Parsing of Home Assistant `/set` command payloads. Port of the field
//! extraction in `cbus/daemon/mqtt_gateway.py::MqttClient._handle_message`
//! (pure logic only — no I/O).

use crate::topics::{topic_group_address, LIGHT_TOPIC_PREFIX, TOPIC_SET_SUFFIX};
use serde_json::Value;

/// A parsed light command from a `homeassistant/light/cbus_*/set` publish.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetCommand {
    /// C-Bus group address.
    pub group_addr: u8,
    /// C-Bus application address (not range-checked, like Python).
    pub app_addr: i64,
    /// `state` was (case-insensitively) `"ON"`.
    pub light_on: bool,
    /// `brightness`, default 255, truncated and clamped to 0..=255.
    pub brightness: u8,
    /// `transition` seconds, default 0, truncated and clamped to >= 0.
    pub transition: u32,
}

/// Why a `/set` publish produced no command.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum CommandError {
    /// Not a `homeassistant/light/cbus_*/set` topic; silently ignored.
    #[error("not a cbus light set topic")]
    NotACommandTopic,
    /// The topic's group segment did not parse (`get_topic_group_address`).
    #[error("invalid group address in topic: {0}")]
    BadTopic(String),
    /// The payload was not valid JSON.
    #[error("JSON parse error: {0}")]
    BadJson(String),
    /// The payload had no usable `state` field.
    #[error("missing 'state' field in payload")]
    MissingState,
}

/// Python `isinstance(x, (int, float))` + `int(x)`: numbers truncate toward
/// zero; booleans count as ints (`True` → 1). Anything else is `None`.
fn py_number(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        _ => None,
    }
}

/// Parse a `/set` command publish. Mirrors `_handle_message`: bad
/// brightness/transition *types* fall back to their defaults (255 / 0)
/// rather than failing the whole command.
///
/// Divergence from Python: a non-string `state` returns
/// [`CommandError::MissingState`] instead of raising `AttributeError`
/// (which crashes the Python dispatcher task).
pub fn parse_set_command(topic: &str, payload: &[u8]) -> Result<SetCommand, CommandError> {
    if !(topic.starts_with(LIGHT_TOPIC_PREFIX) && topic.ends_with(TOPIC_SET_SUFFIX)) {
        return Err(CommandError::NotACommandTopic);
    }
    let (group_addr, app_addr) =
        topic_group_address(topic).map_err(|e| CommandError::BadTopic(e.to_string()))?;
    let v: Value =
        serde_json::from_slice(payload).map_err(|e| CommandError::BadJson(e.to_string()))?;
    let state = v
        .get("state")
        .and_then(Value::as_str)
        .ok_or(CommandError::MissingState)?;
    let light_on = state.to_uppercase() == "ON";

    let brightness = v
        .get("brightness")
        .and_then(py_number)
        .map_or(255, |f| f.trunc().clamp(0.0, 255.0) as u8);
    let transition = v
        .get("transition")
        .and_then(py_number)
        .map_or(0, |f| f.trunc().max(0.0) as u32);

    Ok(SetCommand {
        group_addr,
        app_addr,
        light_on,
        brightness,
        transition,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(topic: &str, payload: &str) -> Result<SetCommand, CommandError> {
        parse_set_command(topic, payload.as_bytes())
    }

    const T: &str = "homeassistant/light/cbus_10/set";

    #[test]
    fn basic_on_off() {
        let c = parse(T, r#"{"state": "ON"}"#).unwrap();
        assert_eq!(
            c,
            SetCommand {
                group_addr: 10,
                app_addr: 56,
                light_on: true,
                brightness: 255,
                transition: 0
            }
        );
        assert!(!parse(T, r#"{"state": "off"}"#).unwrap().light_on);
        // any other state string is treated as OFF, like Python
        assert!(!parse(T, r#"{"state": "toggle"}"#).unwrap().light_on);
        // case-insensitive ON
        assert!(parse(T, r#"{"state": "on"}"#).unwrap().light_on);
    }

    #[test]
    fn alt_app_topic() {
        let c = parse(
            "homeassistant/light/cbus_048_011/set",
            r#"{"state": "ON", "brightness": 128, "transition": 4}"#,
        )
        .unwrap();
        assert_eq!((c.group_addr, c.app_addr), (11, 48));
        assert_eq!((c.brightness, c.transition), (128, 4));
    }

    #[test]
    fn brightness_transition_clamping() {
        // floats truncate toward zero; out-of-range clamps
        let c = parse(T, r#"{"state": "ON", "brightness": 300.9}"#).unwrap();
        assert_eq!(c.brightness, 255);
        let c = parse(T, r#"{"state": "ON", "brightness": -5}"#).unwrap();
        assert_eq!(c.brightness, 0);
        let c = parse(T, r#"{"state": "ON", "brightness": 127.9}"#).unwrap();
        assert_eq!(c.brightness, 127);
        let c = parse(T, r#"{"state": "ON", "transition": -3}"#).unwrap();
        assert_eq!(c.transition, 0);
        // Python isinstance(True, int): booleans are numbers
        let c = parse(T, r#"{"state": "ON", "brightness": true}"#).unwrap();
        assert_eq!(c.brightness, 1);
        // wrong types fall back to the defaults (Python warns + defaults)
        let c = parse(
            T,
            r#"{"state": "ON", "brightness": "high", "transition": null}"#,
        )
        .unwrap();
        assert_eq!((c.brightness, c.transition), (255, 0));
    }

    #[test]
    fn errors() {
        assert_eq!(
            parse("homeassistant/light/cbus_10/state", r#"{"state":"ON"}"#),
            Err(CommandError::NotACommandTopic)
        );
        assert_eq!(
            parse("homeassistant/switch/cbus_10/set", r#"{"state":"ON"}"#),
            Err(CommandError::NotACommandTopic)
        );
        assert!(matches!(
            parse("homeassistant/light/cbus_999/set", r#"{"state":"ON"}"#),
            Err(CommandError::BadTopic(_))
        ));
        assert!(matches!(
            parse(T, "not json"),
            Err(CommandError::BadJson(_))
        ));
        assert_eq!(parse(T, r#"{}"#), Err(CommandError::MissingState));
        // non-string state: divergence — error, not a crash
        assert_eq!(parse(T, r#"{"state": 1}"#), Err(CommandError::MissingState));
    }
}
