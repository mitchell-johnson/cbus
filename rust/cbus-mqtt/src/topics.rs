//! Port of `cbus/daemon/topics.py` and
//! `cbus/daemon/mqtt_gateway.py::get_topic_group_address`.

/// Prefix of every cmqttd light topic.
pub const LIGHT_TOPIC_PREFIX: &str = "homeassistant/light/cbus_";
/// Prefix of every cmqttd binary-sensor topic.
pub const BINSENSOR_TOPIC_PREFIX: &str = "homeassistant/binary_sensor/cbus_";
/// Command topic suffix.
pub const TOPIC_SET_SUFFIX: &str = "/set";
/// Discovery-config topic suffix.
pub const TOPIC_CONF_SUFFIX: &str = "/config";
/// State topic suffix.
pub const TOPIC_STATE_SUFFIX: &str = "/state";

/// The default lighting application (0x38), whose topics keep the
/// historic bare-group-number format.
pub const DEFAULT_LIGHTING_APP: i64 = 0x38;

/// Textual representation of a C-Bus (application, group) pair.
/// Default lighting app keeps the historic 3-digit / bare formats; other
/// apps get `<app:03>_<ga:03>` in both.
pub fn ga_string(group_addr: u8, app_addr: i64, zeros: bool) -> String {
    if app_addr == DEFAULT_LIGHTING_APP {
        if zeros {
            format!("{:03}", group_addr)
        } else {
            format!("{}", group_addr)
        }
    } else {
        format!("{:03}_{:03}", app_addr, group_addr)
    }
}

/// Command (`/set`) topic for a light.
pub fn set_topic(group_addr: u8, app_addr: i64) -> String {
    format!(
        "{}{}{}",
        LIGHT_TOPIC_PREFIX,
        ga_string(group_addr, app_addr, false),
        TOPIC_SET_SUFFIX
    )
}

/// State topic for a light.
pub fn state_topic(group_addr: u8, app_addr: i64) -> String {
    format!(
        "{}{}{}",
        LIGHT_TOPIC_PREFIX,
        ga_string(group_addr, app_addr, false),
        TOPIC_STATE_SUFFIX
    )
}

/// Discovery-config topic for a light.
pub fn conf_topic(group_addr: u8, app_addr: i64) -> String {
    format!(
        "{}{}{}",
        LIGHT_TOPIC_PREFIX,
        ga_string(group_addr, app_addr, false),
        TOPIC_CONF_SUFFIX
    )
}

/// State topic for the paired binary sensor.
pub fn bin_sensor_state_topic(group_addr: u8, app_addr: i64) -> String {
    format!(
        "{}{}{}",
        BINSENSOR_TOPIC_PREFIX,
        ga_string(group_addr, app_addr, false),
        TOPIC_STATE_SUFFIX
    )
}

/// Discovery-config topic for the paired binary sensor.
pub fn bin_sensor_conf_topic(group_addr: u8, app_addr: i64) -> String {
    format!(
        "{}{}{}",
        BINSENSOR_TOPIC_PREFIX,
        ga_string(group_addr, app_addr, false),
        TOPIC_CONF_SUFFIX
    )
}

/// Error from [`topic_group_address`].
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum TopicError {
    /// The topic does not start with [`LIGHT_TOPIC_PREFIX`].
    #[error("invalid topic {0:?}, must start with \"homeassistant/light/cbus_\"")]
    InvalidPrefix(String),
    /// An app/group segment was not a base-10 integer.
    #[error("invalid literal for int(): {0:?}")]
    BadInteger(String),
    /// The group address parsed but is outside 0..=255.
    #[error("group address out of range (0..255), got {0}")]
    GroupOutOfRange(i64),
}

/// Python `int()` (base 10): optional sign, digits, surrounding whitespace,
/// leading zeros allowed.
fn py_int(s: &str) -> Result<i64, TopicError> {
    let t = s.trim();
    t.parse::<i64>()
        .map_err(|_| TopicError::BadInteger(s.to_string()))
}

/// Extract `(group_addr, app_addr)` from a command topic. Port of
/// `get_topic_group_address` — note the app address is *not* range-checked
/// (only the group address is, via `check_ga`).
pub fn topic_group_address(topic: &str) -> Result<(u8, i64), TopicError> {
    let rest = topic
        .strip_prefix(LIGHT_TOPIC_PREFIX)
        .ok_or_else(|| TopicError::InvalidPrefix(topic.to_string()))?;
    let seg = rest.split('/').next().unwrap_or("");
    let parts: Vec<&str> = seg.split('_').collect();
    let (aa, ga) = if parts.len() >= 2 {
        (py_int(parts[0])?, py_int(parts[1])?)
    } else {
        (DEFAULT_LIGHTING_APP, py_int(parts[0])?)
    };
    if !(0..=255).contains(&ga) {
        return Err(TopicError::GroupOutOfRange(ga));
    }
    Ok((ga as u8, aa))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ga_strings() {
        assert_eq!(ga_string(10, 56, true), "010");
        assert_eq!(ga_string(10, 56, false), "10");
        assert_eq!(ga_string(11, 48, true), "048_011");
        assert_eq!(ga_string(11, 48, false), "048_011");
    }

    #[test]
    fn parse() {
        assert_eq!(
            topic_group_address("homeassistant/light/cbus_10/set").unwrap(),
            (10, 56)
        );
        assert_eq!(
            topic_group_address("homeassistant/light/cbus_048_011/set").unwrap(),
            (11, 48)
        );
        assert_eq!(
            topic_group_address("homeassistant/light/cbus_56_001/set").unwrap(),
            (1, 56)
        );
        assert!(topic_group_address("homeassistant/switch/cbus_1/set").is_err());
        assert!(topic_group_address("homeassistant/light/cbus_999/set").is_err());
        assert!(topic_group_address("homeassistant/light/cbus_xx/set").is_err());
    }
}
