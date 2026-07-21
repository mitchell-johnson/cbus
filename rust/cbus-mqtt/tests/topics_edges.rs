//! Topic parsing edges beyond the golden parse vectors: prefix handling,
//! segment splitting and the exact error variants.

use cbus_mqtt::topics::{ga_string, topic_group_address, TopicError};

#[test]
fn parse_does_not_require_a_suffix() {
    // get_topic_group_address only looks at the first segment
    assert_eq!(
        topic_group_address("homeassistant/light/cbus_10").unwrap(),
        (10, 56)
    );
}

#[test]
fn parse_ignores_everything_after_first_slash() {
    assert_eq!(
        topic_group_address("homeassistant/light/cbus_10/set/extra/deep").unwrap(),
        (10, 56)
    );
}

#[test]
fn wrong_component_prefix_error_variant() {
    let e = topic_group_address("homeassistant/switch/cbus_10/set").unwrap_err();
    assert!(matches!(e, TopicError::InvalidPrefix(_)));
}

#[test]
fn bare_ga_segment_has_invalid_prefix() {
    let e = topic_group_address("cbus_10/set").unwrap_err();
    assert!(matches!(e, TopicError::InvalidPrefix(_)));
}

#[test]
fn prefix_is_case_sensitive() {
    let e = topic_group_address("Homeassistant/light/cbus_10/set").unwrap_err();
    assert!(matches!(e, TopicError::InvalidPrefix(_)));
}

#[test]
fn out_of_range_group_reports_value() {
    let e = topic_group_address("homeassistant/light/cbus_00256/set").unwrap_err();
    assert_eq!(e, TopicError::GroupOutOfRange(256));
}

#[test]
fn deeply_negative_group_out_of_range() {
    let e = topic_group_address("homeassistant/light/cbus_048_-11/set").unwrap_err();
    assert_eq!(e, TopicError::GroupOutOfRange(-11));
}

#[test]
fn float_group_is_bad_integer() {
    let e = topic_group_address("homeassistant/light/cbus_1.5/set").unwrap_err();
    assert!(matches!(e, TopicError::BadInteger(_)));
}

#[test]
fn empty_app_segment_is_bad_integer() {
    // "cbus__10" splits into ["", "10"]: the app segment is empty
    let e = topic_group_address("homeassistant/light/cbus__10/set").unwrap_err();
    assert!(matches!(e, TopicError::BadInteger(_)));
}

#[test]
fn ga_string_group_boundaries_default_app() {
    assert_eq!(ga_string(0, 56, true), "000");
    assert_eq!(ga_string(0, 56, false), "0");
    assert_eq!(ga_string(255, 56, true), "255");
    assert_eq!(ga_string(255, 56, false), "255");
}

#[test]
fn ga_string_non_lighting_app_uses_padded_form() {
    // even a wild app id (not a lighting app at all) gets app_ga form
    assert_eq!(ga_string(3, 200, true), "200_003");
    assert_eq!(ga_string(3, 200, false), "200_003");
}

#[test]
fn ga_string_app_wider_than_three_digits() {
    // {:03} is a minimum width, not a cap — parity with Python %03d
    assert_eq!(ga_string(3, 1234, false), "1234_003");
}
