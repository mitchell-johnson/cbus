//! Regression checks whose result depends on the complete `cmqttd` Cargo
//! feature graph rather than on `cbus-mqtt` in isolation.

use cbus_mqtt::command::{parse_set_command, CommandError};

#[test]
fn nonfinite_brightness_is_rejected_with_the_daemon_feature_graph() {
    let result = parse_set_command(
        "homeassistant/light/cbus_10/set",
        br#"{"state":"ON","brightness":1e400}"#,
    );

    assert!(
        matches!(result, Err(CommandError::BadJson(_))),
        "a JSON number outside finite f64 range must not become a default full-brightness command: {result:?}"
    );
}
