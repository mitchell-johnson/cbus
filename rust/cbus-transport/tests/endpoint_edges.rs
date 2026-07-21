//! Endpoint parsing and connection error paths.

use cbus_transport::conn::{connect, connect_with_retry, Endpoint};
use std::time::Duration;

#[test]
fn tcp_spec_requires_colon() {
    assert!(Endpoint::parse_tcp("192.0.2.1").is_err());
}

#[test]
fn tcp_spec_rejects_non_numeric_port() {
    assert!(Endpoint::parse_tcp("192.0.2.1:abc").is_err());
}

#[test]
fn tcp_spec_rejects_port_above_u16() {
    assert!(Endpoint::parse_tcp("192.0.2.1:65536").is_err());
}

#[test]
fn tcp_spec_accepts_port_zero() {
    assert_eq!(
        Endpoint::parse_tcp("192.0.2.1:0").unwrap(),
        Endpoint::Tcp {
            host: "192.0.2.1".into(),
            port: 0
        }
    );
}

#[test]
fn tcp_spec_splits_at_first_colon_so_ipv6_fails() {
    // split_once(':') makes bare IPv6 addresses unusable — pinned so a
    // future "fix" is a conscious decision
    assert!(Endpoint::parse_tcp("::1:10001").is_err());
}

#[test]
fn esp32_wifi_splits_at_last_colon() {
    assert_eq!(
        Endpoint::parse_esp32_wifi("fe80::1:2000").unwrap(),
        Endpoint::Tcp {
            host: "fe80::1".into(),
            port: 2000
        }
    );
}

#[test]
fn esp32_wifi_trailing_colon_is_error() {
    assert!(Endpoint::parse_esp32_wifi("10.0.0.5:").is_err());
}

#[test]
fn esp32_wifi_hostname_defaults_port_10001() {
    assert_eq!(
        Endpoint::parse_esp32_wifi("bridge.local").unwrap(),
        Endpoint::Tcp {
            host: "bridge.local".into(),
            port: 10001
        }
    );
}

#[test]
fn serial_constructor_keeps_fields() {
    assert_eq!(
        Endpoint::serial("/dev/ttyUSB0", 115200),
        Endpoint::Serial {
            device: "/dev/ttyUSB0".into(),
            baud: 115200
        }
    );
}

#[tokio::test]
async fn serial_connect_to_missing_device_errors() {
    let ep = Endpoint::Serial {
        device: "/nonexistent/tty-cbus-test".into(),
        baud: 9600,
    };
    assert!(connect(&ep).await.is_err());
}

#[tokio::test]
async fn retry_single_attempt_fails_fast() {
    // a port nothing listens on: one attempt, no retry sleep
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let ep = Endpoint::Tcp {
        host: "127.0.0.1".into(),
        port,
    };
    let start = std::time::Instant::now();
    let r = connect_with_retry(&ep, Duration::from_millis(500), 1).await;
    assert!(r.is_err());
    assert!(
        start.elapsed() < Duration::from_millis(400),
        "single-attempt retry must not sleep"
    );
}

#[tokio::test]
async fn retry_counts_attempts_not_sleeps() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let ep = Endpoint::Tcp {
        host: "127.0.0.1".into(),
        port,
    };
    let start = std::time::Instant::now();
    let r = connect_with_retry(&ep, Duration::from_millis(50), 3).await;
    assert!(r.is_err());
    // 3 attempts -> exactly 2 sleeps of 50 ms between them
    let elapsed = start.elapsed();
    assert!(
        elapsed >= Duration::from_millis(100),
        "expected two retry sleeps, got {elapsed:?}"
    );
}
