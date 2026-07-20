//! Port of `cbus/constants.py`: timings and thresholds.

/// Confirmation codes time out after this long.
pub const CONFIRMATION_TIMEOUT_SECONDS: f64 = 30.0;
/// Total transmission attempts for an unconfirmed frame.
pub const MAX_PACKET_RETRIES: u32 = 3;
/// Interval of the retransmit sweep.
pub const PACKET_RETRY_INTERVAL_SECONDS: f64 = 1.0;
/// Warn when this many confirmations are outstanding.
pub const PENDING_CONFIRMATION_WARNING_THRESHOLD: usize = 20;
/// Force-release codes when this fraction of the pool is in use.
pub const CONFIRMATION_CODE_FORCE_CLEANUP_THRESHOLD: f64 = 0.9;
/// Fraction of the pool force-released during cleanup.
pub const CONFIRMATION_CODE_FORCE_CLEANUP_PERCENTAGE: f64 = 0.25;

/// Pause before every transport write.
pub const PACKET_SEND_DELAY_SECONDS: f64 = 0.1;
/// Default timesync period.
pub const DEFAULT_TIMESYNC_FREQUENCY_SECONDS: u64 = 10;
/// Command throttler period.
pub const DEFAULT_THROTTLE_PERIOD_SECONDS: f64 = 0.2;

/// Groups covered per status-request block.
pub const STATUS_REQUEST_BLOCK_SIZE: u16 = 32;
/// Highest group address.
pub const MAX_GROUP_ADDRESS: u16 = 255;

/// Cap on outstanding confirmations.
pub const MAX_PENDING_CONFIRMATIONS: usize = 50;

/// Default MQTT-over-TLS port.
pub const MQTT_DEFAULT_TLS_PORT: u16 = 8883;
/// Default plaintext MQTT port.
pub const MQTT_DEFAULT_PLAIN_PORT: u16 = 1883;
/// Default MQTT keepalive.
pub const MQTT_DEFAULT_KEEPALIVE_SECONDS: u16 = 60;
