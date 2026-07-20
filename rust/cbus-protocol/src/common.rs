//! Port of `cbus/common.py`: protocol constants, checksums, ramp rates.

/// The only hex alphabet the decoder accepts (uppercase).
pub const HEX_CHARS: &[u8] = b"0123456789ABCDEF";
/// Client command terminator.
pub const END_COMMAND: &[u8] = b"\r";
/// PCI response terminator.
pub const END_RESPONSE: &[u8] = b"\r\n";
/// Smallest possible from-PCI message (a confirmation).
pub const MIN_MESSAGE_SIZE: usize = 2;
/// Receive-buffer cap; overflow drops the whole buffer.
pub const MAX_BUFFER_SIZE: usize = 256;

/// Valid confirmation codes, in allocation order (h first, g last).
pub const CONFIRMATION_CODES: &[u8] = b"hijklmnopqrstuvwxyzg";

/// Lowest valid group address.
pub const MIN_GROUP_ADDR: u8 = 0;
/// Highest valid group address.
pub const MAX_GROUP_ADDR: u8 = 255;

// DestinationAddressType (Serial Interface Guide s3.4)
/// Destination address type: point-to-point-to-multipoint.
pub const DAT_POINT_TO_POINT_TO_MULTIPOINT: u8 = 0x03;
/// Destination address type: point-to-multipoint.
pub const DAT_POINT_TO_MULTIPOINT: u8 = 0x05;
/// Destination address type: point-to-point.
pub const DAT_POINT_TO_POINT: u8 = 0x06;

// PriorityClass
/// Lowest priority (default for most packets).
pub const PRIORITY_CLASS_4: u8 = 0x00; // lowest (default for most packets)
/// Priority class 2 (default for DeviceManagement).
pub const PRIORITY_CLASS_2: u8 = 0x02; // default for DeviceManagement

// Applications
/// Temperature broadcast application.
pub const APP_TEMPERATURE: u8 = 0x19;
/// First lighting application address.
pub const APP_LIGHTING_FIRST: u8 = 0x30;
/// The default lighting application.
pub const APP_LIGHTING: u8 = 0x38;
/// Last lighting application address.
pub const APP_LIGHTING_LAST: u8 = 0x5f;
/// Clock and timekeeping application.
pub const APP_CLOCK: u8 = 0xdf;
/// Enable control application.
pub const APP_ENABLE: u8 = 0xcb;
/// Status request pseudo-application.
pub const APP_STATUS_REQUEST: u8 = 0xff;

// CAL command codes
/// CAL command: reset.
pub const CAL_RESET: u8 = 0x08;
/// CAL command: recall.
pub const CAL_RECALL: u8 = 0x1a;
/// CAL command: identify.
pub const CAL_IDENTIFY: u8 = 0x21;
/// CAL command: get status.
pub const CAL_GET_STATUS: u8 = 0x2a;
/// CAL command: acknowledge.
pub const CAL_ACKNOWLEDGE: u8 = 0x32;
// bit-masks
/// CAL command mask: reply (0x80..0x9F).
pub const CAL_REPLY: u8 = 0x80;
/// CAL command mask: standard status (0xC0..0xDF).
pub const CAL_STANDARD_STATUS: u8 = 0xc0;
/// CAL command mask: extended status (0xE0..0xFF).
pub const CAL_EXTENDED_STATUS: u8 = 0xe0;

// ExtendedCALType
/// Extended status coding: binary report.
pub const EXTENDED_CAL_BINARY: u8 = 0x00;
/// Extended status coding: level report.
pub const EXTENDED_CAL_LEVEL: u8 = 0x07;

// GroupState
/// Binary report state: unit missing.
pub const GROUP_STATE_MISSING: u8 = 0x00;
/// Binary report state: on.
pub const GROUP_STATE_ON: u8 = 0x01;
/// Binary report state: off.
pub const GROUP_STATE_OFF: u8 = 0x02;
/// Binary report state: error.
pub const GROUP_STATE_ERROR: u8 = 0x03;

// Lighting application commands
/// Lighting SAL command: on.
pub const LIGHT_ON: u8 = 0x79;
/// Lighting SAL command: off.
pub const LIGHT_OFF: u8 = 0x01;
/// Lighting SAL command: terminate ramp.
pub const LIGHT_TERMINATE_RAMP: u8 = 0x09;
/// Fastest ramp rate code (instant).
pub const LIGHT_RAMP_FASTEST: u8 = 0x02;
/// Slowest ramp rate code (1020 s).
pub const LIGHT_RAMP_SLOWEST: u8 = 0x7a;

// Enable control application commands
/// Enable SAL command: set network variable.
pub const ENABLE_SET_NETWORK_VARIABLE: u8 = 0x02;

// Temperature broadcast command
/// Temperature SAL command: broadcast.
pub const TEMPERATURE_BROADCAST: u8 = 0x02;

// Clock application
/// Clock update variable: time.
pub const CLOCK_ATTR_TIME: u8 = 0x01;
/// Clock update variable: date.
pub const CLOCK_ATTR_DATE: u8 = 0x02;
/// Clock SAL command: update network variable.
pub const CLOCK_UPDATE_NETWORK_VARIABLE: u8 = 0x08;
/// Clock SAL command: request refresh.
pub const CLOCK_REQUEST_REFRESH: u8 = 0x11;

/// Ramp rate table, (command code, duration seconds), ordered by duration.
pub const LIGHT_RAMP_RATES: &[(u8, u32)] = &[
    (0x02, 0),
    (0x0a, 4),
    (0x12, 8),
    (0x1a, 12),
    (0x22, 20),
    (0x2a, 30),
    (0x32, 40),
    (0x3a, 60),
    (0x42, 90),
    (0x4a, 120),
    (0x52, 180),
    (0x5a, 300),
    (0x62, 420),
    (0x6a, 600),
    (0x72, 900),
    (0x7a, 1020),
];

/// Snap a duration (seconds) up to the smallest ramp-rate command code whose
/// duration is >= it; durations beyond 1020 s snap to 0x7A.
pub fn duration_to_ramp_rate(seconds: i64) -> u8 {
    for &(cmd, d) in LIGHT_RAMP_RATES {
        if seconds <= d as i64 {
            return cmd;
        }
    }
    LIGHT_RAMP_SLOWEST
}

/// Exact lookup of a ramp rate command code to its duration in seconds.
pub fn ramp_rate_to_duration(rate: u8) -> Option<u32> {
    LIGHT_RAMP_RATES
        .iter()
        .find(|&&(cmd, _)| cmd == rate)
        .map(|&(_, d)| d)
}

/// bridge length codes for bridged point-to-point packets
pub fn bridge_length(code: u8) -> Option<usize> {
    match code {
        0x09 => Some(0),
        0x12 => Some(1),
        0x1b => Some(2),
        0x24 => Some(3),
        0x2d => Some(4),
        0x36 => Some(5),
        _ => None,
    }
}

/// `((~sum(i) & 0xff) + 1) & 0xff` — two's complement of the byte sum.
/// Empty input -> 0.
pub fn cbus_checksum(data: &[u8]) -> u8 {
    let sum: u32 = data.iter().map(|&b| b as u32).sum();
    (((!sum & 0xff) + 1) & 0xff) as u8
}

/// Append the checksum byte to `data`.
pub fn add_cbus_checksum(data: &[u8]) -> Vec<u8> {
    let mut out = data.to_vec();
    out.push(cbus_checksum(data));
    out
}

/// True if the last byte is the checksum of the rest. Empty input -> false
/// (Python raises IndexError; callers never pass empty data).
pub fn validate_cbus_checksum(data: &[u8]) -> bool {
    match data.split_last() {
        Some((&last, rest)) => last == cbus_checksum(rest),
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checksum_basics() {
        // \0538007901 sums to 0 after checksum append
        let data = [0x05u8, 0x38, 0x00, 0x79, 0x01];
        let ck = cbus_checksum(&data);
        let full = add_cbus_checksum(&data);
        assert_eq!(*full.last().unwrap(), ck);
        assert!(validate_cbus_checksum(&full));
        assert_eq!(cbus_checksum(&[]), 0);
        assert_eq!(cbus_checksum(&[0, 0, 0]), 0);
    }

    #[test]
    fn ramp_rates() {
        assert_eq!(duration_to_ramp_rate(0), 0x02);
        assert_eq!(duration_to_ramp_rate(1), 0x0a);
        assert_eq!(duration_to_ramp_rate(4), 0x0a);
        assert_eq!(duration_to_ramp_rate(5), 0x12);
        assert_eq!(duration_to_ramp_rate(1020), 0x7a);
        assert_eq!(duration_to_ramp_rate(1021), 0x7a);
        assert_eq!(ramp_rate_to_duration(0x02), Some(0));
        assert_eq!(ramp_rate_to_duration(0x7a), Some(1020));
        assert_eq!(ramp_rate_to_duration(0x03), None);
    }
}
