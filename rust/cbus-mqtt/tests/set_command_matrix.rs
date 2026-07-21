//! The `/set` payload matrix: state spellings x brightness types/ranges x
//! transition types/ranges x topic forms x malformed JSON. Pins the exact
//! Python `_handle_message` field-extraction semantics (truncation toward
//! zero, clamping, type-fallback to defaults, booleans counting as ints).

use cbus_mqtt::command::{parse_set_command, CommandError, SetCommand};

const T: &str = "homeassistant/light/cbus_10/set";

/// One named test per (topic, payload) -> full expected command.
macro_rules! ok_case {
    ($name:ident, $topic:expr, $payload:expr,
     ga=$ga:expr, app=$app:expr, on=$on:expr, b=$b:expr, t=$t:expr) => {
        #[test]
        fn $name() {
            assert_eq!(
                parse_set_command($topic, $payload.as_bytes()),
                Ok(SetCommand {
                    group_addr: $ga,
                    app_addr: $app,
                    light_on: $on,
                    brightness: $b,
                    transition: $t,
                })
            );
        }
    };
}

/// One named test per (topic, payload) -> expected error shape.
macro_rules! err_case {
    ($name:ident, $topic:expr, $payload:expr, $pat:pat) => {
        #[test]
        fn $name() {
            let r = parse_set_command($topic, $payload.as_bytes());
            assert!(matches!(r, Err($pat)), "got {r:?}");
        }
    };
}

// ------------------------------------------------------------------ state

ok_case!(
    state_on_upper,
    T,
    r#"{"state":"ON"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    state_on_lower,
    T,
    r#"{"state":"on"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    state_on_mixed,
    T,
    r#"{"state":"On"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    state_off_upper,
    T,
    r#"{"state":"OFF"}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);
ok_case!(
    state_off_lower,
    T,
    r#"{"state":"off"}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);
ok_case!(
    state_toggle_treated_as_off,
    T,
    r#"{"state":"toggle"}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);
ok_case!(
    state_onn_typo_treated_as_off,
    T,
    r#"{"state":"ONN"}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);
ok_case!(
    state_empty_string_treated_as_off,
    T,
    r#"{"state":""}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);
ok_case!(
    state_with_whitespace_not_on,
    T,
    r#"{"state":" ON"}"#,
    ga = 10,
    app = 56,
    on = false,
    b = 255,
    t = 0
);

// ------------------------------------------------------------- brightness

ok_case!(
    brightness_absent_defaults_255,
    T,
    r#"{"state":"ON"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_zero,
    T,
    r#"{"state":"ON","brightness":0}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 0,
    t = 0
);
ok_case!(
    brightness_one,
    T,
    r#"{"state":"ON","brightness":1}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 1,
    t = 0
);
ok_case!(
    brightness_254,
    T,
    r#"{"state":"ON","brightness":254}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 254,
    t = 0
);
ok_case!(
    brightness_255,
    T,
    r#"{"state":"ON","brightness":255}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_256_clamps_to_255,
    T,
    r#"{"state":"ON","brightness":256}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_big_float_clamps,
    T,
    r#"{"state":"ON","brightness":300.9}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_negative_clamps_to_0,
    T,
    r#"{"state":"ON","brightness":-5}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 0,
    t = 0
);
ok_case!(
    brightness_float_truncates,
    T,
    r#"{"state":"ON","brightness":127.9}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 127,
    t = 0
);
ok_case!(
    brightness_half_truncates_to_0,
    T,
    r#"{"state":"ON","brightness":0.5}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 0,
    t = 0
);
ok_case!(
    brightness_true_is_1,
    T,
    r#"{"state":"ON","brightness":true}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 1,
    t = 0
);
ok_case!(
    brightness_false_is_0,
    T,
    r#"{"state":"ON","brightness":false}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 0,
    t = 0
);
ok_case!(
    brightness_string_falls_back_255,
    T,
    r#"{"state":"ON","brightness":"high"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_null_falls_back_255,
    T,
    r#"{"state":"ON","brightness":null}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_array_falls_back_255,
    T,
    r#"{"state":"ON","brightness":[128]}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_object_falls_back_255,
    T,
    r#"{"state":"ON","brightness":{"v":9}}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);

// ------------------------------------------------------------- transition

ok_case!(
    transition_absent_defaults_0,
    T,
    r#"{"state":"ON","brightness":128}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 128,
    t = 0
);
ok_case!(
    transition_four_seconds,
    T,
    r#"{"state":"ON","transition":4}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 4
);
ok_case!(
    transition_negative_clamps_to_0,
    T,
    r#"{"state":"ON","transition":-3}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    transition_float_truncates,
    T,
    r#"{"state":"ON","transition":2.9}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 2
);
ok_case!(
    transition_exponent_notation,
    T,
    r#"{"state":"ON","transition":1e3}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 1000
);
ok_case!(
    transition_beyond_ramp_table,
    T,
    r#"{"state":"ON","transition":4000}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 4000
);
ok_case!(
    transition_true_is_1,
    T,
    r#"{"state":"ON","transition":true}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 1
);
ok_case!(
    transition_string_falls_back_0,
    T,
    r#"{"state":"ON","transition":"fast"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    transition_null_falls_back_0,
    T,
    r#"{"state":"ON","transition":null}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    brightness_and_transition_together,
    T,
    r#"{"state":"ON","brightness":128,"transition":12}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 128,
    t = 12
);
ok_case!(
    extra_fields_ignored,
    T,
    r#"{"state":"ON","brightness":9,"color_temp":300,"effect":"x"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 9,
    t = 0
);

// ---------------------------------------------------------------- topics

ok_case!(
    topic_group_zero,
    "homeassistant/light/cbus_0/set",
    r#"{"state":"ON"}"#,
    ga = 0,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_group_255,
    "homeassistant/light/cbus_255/set",
    r#"{"state":"ON"}"#,
    ga = 255,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_alt_app_form,
    "homeassistant/light/cbus_048_011/set",
    r#"{"state":"ON"}"#,
    ga = 11,
    app = 48,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_default_app_padded_form,
    "homeassistant/light/cbus_056_001/set",
    r#"{"state":"ON"}"#,
    ga = 1,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_extra_underscore_segments_ignored,
    "homeassistant/light/cbus_048_011_junk/set",
    r#"{"state":"ON"}"#,
    ga = 11,
    app = 48,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_app_not_range_checked,
    "homeassistant/light/cbus_999_010/set",
    r#"{"state":"ON"}"#,
    ga = 10,
    app = 999,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_negative_app_accepted,
    "homeassistant/light/cbus_-48_010/set",
    r#"{"state":"ON"}"#,
    ga = 10,
    app = -48,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_plus_signed_group,
    "homeassistant/light/cbus_+10/set",
    r#"{"state":"ON"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_whitespace_group_python_int,
    "homeassistant/light/cbus_ 10/set",
    r#"{"state":"ON"}"#,
    ga = 10,
    app = 56,
    on = true,
    b = 255,
    t = 0
);
ok_case!(
    topic_leading_zeros_group,
    "homeassistant/light/cbus_007/set",
    r#"{"state":"ON"}"#,
    ga = 7,
    app = 56,
    on = true,
    b = 255,
    t = 0
);

// ---------------------------------------------------------------- errors

err_case!(
    state_topic_is_not_a_command,
    "homeassistant/light/cbus_10/state",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    config_topic_is_not_a_command,
    "homeassistant/light/cbus_10/config",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    switch_component_is_not_a_command,
    "homeassistant/switch/cbus_10/set",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    binary_sensor_is_not_a_command,
    "homeassistant/binary_sensor/cbus_10/set",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    missing_set_suffix_is_not_a_command,
    "homeassistant/light/cbus_10",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    trailing_segment_is_not_a_command,
    "homeassistant/light/cbus_10/set/extra",
    r#"{"state":"ON"}"#,
    CommandError::NotACommandTopic
);
err_case!(
    group_256_bad_topic,
    "homeassistant/light/cbus_256/set",
    r#"{"state":"ON"}"#,
    CommandError::BadTopic(_)
);
err_case!(
    group_negative_bad_topic,
    "homeassistant/light/cbus_-1/set",
    r#"{"state":"ON"}"#,
    CommandError::BadTopic(_)
);
err_case!(
    group_hex_notation_bad_topic,
    "homeassistant/light/cbus_0x10/set",
    r#"{"state":"ON"}"#,
    CommandError::BadTopic(_)
);
err_case!(
    group_non_numeric_bad_topic,
    "homeassistant/light/cbus_kitchen/set",
    r#"{"state":"ON"}"#,
    CommandError::BadTopic(_)
);
err_case!(
    group_empty_bad_topic,
    "homeassistant/light/cbus_/set",
    r#"{"state":"ON"}"#,
    CommandError::BadTopic(_)
);
err_case!(not_json_payload, T, "not json", CommandError::BadJson(_));
err_case!(empty_payload, T, "", CommandError::BadJson(_));
err_case!(
    json_array_payload_missing_state,
    T,
    r#"["ON"]"#,
    CommandError::MissingState
);
err_case!(
    json_string_payload_missing_state,
    T,
    r#""ON""#,
    CommandError::MissingState
);
err_case!(
    empty_object_missing_state,
    T,
    r#"{}"#,
    CommandError::MissingState
);
err_case!(
    numeric_state_missing_state,
    T,
    r#"{"state":1}"#,
    CommandError::MissingState
);
err_case!(
    object_state_missing_state,
    T,
    r#"{"state":{"on":true}}"#,
    CommandError::MissingState
);
err_case!(
    null_state_missing_state,
    T,
    r#"{"state":null}"#,
    CommandError::MissingState
);

#[test]
fn invalid_utf8_payload_is_bad_json() {
    let r = parse_set_command(T, &[0xff, 0xfe, 0x00]);
    assert!(matches!(r, Err(CommandError::BadJson(_))), "got {r:?}");
}
