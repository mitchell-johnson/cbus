//! Pure validation of `cbus-selected-serial-plan-v1` intent documents.
//!
//! Mirrors the Python oracle `SelectedSerialPlan.from_dict`
//! (`toolkit-cli/src/cbus_toolkit/pci_selected_serial.py`, ~lines 219-260)
//! plus every helper it calls (`_keys`, `_same`, `_selected_serial`,
//! `_inventory_proof`, `_raw_mmi`, `_raw_serials`, `_options_proof`,
//! `_expected`, `encode_serial_address`, and the coordinator constructor
//! validation). This enables cross-implementation interop: Python-produced
//! plans validate identically in Rust.
//!
//! Pure function only: no I/O, no clock reads. Timing fields are validated
//! as ranges at most (`received_after_seconds` must be finite and
//! non-negative, like the oracle); exact timing values are never compared.
//! Journal/apply/verify orchestration is explicitly out of scope: a valid
//! plan is a validated intent document, never proof of movement or
//! persistence.

use cbus_protocol::cal::Cal;
use cbus_protocol::pci_observation::{
    identify_request, installation_mmi_request, parse_capture, parse_mmi_capture, recall_request,
    MmiEvent, PciEvent, PciFrame,
};
use cbus_protocol::serial_address::{encode_serial_address, parse_native_serial};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::fmt;

/// Raw-document size bound, mirroring `MAX_PLAN_BYTES` (4 MiB).
pub const MAX_PLAN_BYTES: usize = 4 * 1024 * 1024;

/// A plan document that passed full consistency verification.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedPlan {
    /// Canonical selected serial (e.g. `101136.1558`).
    pub serial: String,
    /// Explicit empty destination address.
    pub destination: u8,
    /// Lowercase hex of the re-encoded address request.
    pub request_hex: String,
    /// Re-encoded address request wire bytes.
    pub request_bytes: Vec<u8>,
    /// Whether the validated plan requires the outer SRCHK checksum.
    pub command_checksum: bool,
    /// Always 255: only source 255 is supported.
    pub source: u8,
    /// Known local PCI unit address.
    pub local_unit: u8,
    /// Pinned canonical local PCI serial.
    pub expected_local_serial: String,
    /// Numeric-IP endpoint host.
    pub host: String,
    /// Endpoint port.
    pub port: u16,
}

/// Precise failure class for every rejection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlanError {
    reason: &'static str,
    message: String,
}

impl PlanError {
    fn new(reason: &'static str, message: impl Into<String>) -> Self {
        Self {
            reason,
            message: message.into(),
        }
    }

    /// Machine-stable failure class (see the vector `reason` column).
    pub fn reason(&self) -> &'static str {
        self.reason
    }

    /// Human-readable detail.
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for PlanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.reason, self.message)
    }
}

impl std::error::Error for PlanError {}

// ---------------------------------------------------------------------------
// Raw-document load: size bound, duplicate fields, non-finite constants.
// ---------------------------------------------------------------------------

/// CPython's default decimal integer conversion limit. The Python oracle uses
/// the interpreter default when `json.loads` constructs integers.
const PYTHON_INT_MAX_STR_DIGITS: usize = 4_300;

/// A JSON string used only inside the sanitized serde input for Python
/// integers too large for a finite binary64 conversion. Required numeric
/// fields reject the string type; ignored evidence remains acceptable because
/// the validator never consumes its numeric value.
const BIG_INTEGER_SENTINEL_JSON: &[u8] = br#""__cbus_python_big_integer__""#;

/// Finite numeric surrogates for Python integers outside serde_json's integer
/// range. They remain numbers for fields such as arrival timing, preserve the
/// original sign, and sit outside every bounded integer/timeout field.
const POSITIVE_BIG_INTEGER_SURROGATE_JSON: &[u8] = b"1e300";
const NEGATIVE_BIG_INTEGER_SURROGATE_JSON: &[u8] = b"-1e300";

#[derive(Debug)]
struct RawScan {
    sanitized: Vec<u8>,
    python_canonical_size: usize,
}

/// Scan raw JSON for duplicate object keys and unquoted non-finite
/// constants (`NaN`, `Infinity`), mirroring `_load`/`_unique_pairs` plus the
/// `parse_constant` guard. The scan also validates JSON number grammar,
/// computes the size of CPython's compact canonical rendering, and creates a
/// serde-safe parse buffer. `serde_json` silently takes the last duplicate by
/// default, so duplicates must be detected explicitly.
fn scan_raw(text: &[u8]) -> Result<RawScan, PlanError> {
    std::str::from_utf8(text).map_err(|_| PlanError::new("invalid_json", "Invalid UTF-8"))?;
    let mut parser = Scanner {
        bytes: text,
        pos: 0,
        sanitized: Vec::with_capacity(text.len()),
    };
    parser.skip_ws();
    let python_canonical_size = parser.parse_value(&mut Vec::new())?;
    parser.skip_ws();
    if parser.pos != text.len() {
        return Err(PlanError::new(
            "invalid_json",
            "Trailing data after document",
        ));
    }
    Ok(RawScan {
        sanitized: parser.sanitized,
        python_canonical_size,
    })
}

/// Parse arbitrary JSON with the plan scanner's duplicate-key, number, and
/// nesting checks. This is also used before reading an embedded plan from a
/// recovery journal so ordinary `serde_json` parsing cannot erase ambiguity.
pub(crate) fn parse_strict_json_value(raw: &[u8]) -> Result<(Value, usize), PlanError> {
    let scan = scan_raw(raw)?;
    let value: Value = serde_json::from_slice(&scan.sanitized)
        .map_err(|e| PlanError::new("invalid_json", format!("Invalid JSON: {e}")))?;
    Ok((value, scan.python_canonical_size))
}

struct Scanner<'a> {
    bytes: &'a [u8],
    pos: usize,
    sanitized: Vec<u8>,
}

impl Scanner<'_> {
    const MAX_DEPTH: usize = 127;

    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len()
            && matches!(self.bytes[self.pos], b' ' | b'\t' | b'\n' | b'\r')
        {
            self.pos += 1;
        }
    }

    fn literal(
        &mut self,
        word: &[u8],
        reason: &'static str,
        message: &str,
    ) -> Result<(), PlanError> {
        if self.bytes.get(self.pos..self.pos + word.len()) == Some(word) {
            self.pos += word.len();
            self.sanitized.extend_from_slice(word);
            Ok(())
        } else {
            Err(PlanError::new(reason, message))
        }
    }

    fn parse_value(
        &mut self,
        stack: &mut Vec<Option<HashSet<String>>>,
    ) -> Result<usize, PlanError> {
        self.skip_ws();
        let byte = *self
            .bytes
            .get(self.pos)
            .ok_or(PlanError::new("invalid_json", "Truncated JSON value"))?;
        if matches!(byte, b'{' | b'[') && stack.len() >= Self::MAX_DEPTH {
            return Err(PlanError::new(
                "invalid_json",
                "JSON nesting exceeds the supported depth",
            ));
        }
        match byte {
            b'{' => self.parse_object(stack),
            b'[' => self.parse_array(stack),
            b'"' => {
                let (_, canonical_size) = self.parse_string()?;
                Ok(canonical_size)
            }
            b't' => {
                self.literal(b"true", "invalid_json", "Invalid literal")?;
                Ok(4)
            }
            b'f' => {
                self.literal(b"false", "invalid_json", "Invalid literal")?;
                Ok(5)
            }
            b'n' => {
                self.literal(b"null", "invalid_json", "Invalid literal")?;
                Ok(4)
            }
            b'N' => {
                self.literal(b"NaN", "nonfinite_json", "Nonfinite JSON value")?;
                Err(PlanError::new("nonfinite_json", "Nonfinite JSON value"))
            }
            b'I' => {
                self.literal(b"Infinity", "nonfinite_json", "Nonfinite JSON value")?;
                Err(PlanError::new("nonfinite_json", "Nonfinite JSON value"))
            }
            b'-' => {
                if self.bytes.get(self.pos + 1..self.pos + 9) == Some(b"Infinity") {
                    return Err(PlanError::new("nonfinite_json", "Nonfinite JSON value"));
                }
                self.parse_number()
            }
            b'0'..=b'9' => self.parse_number(),
            _ => Err(PlanError::new("invalid_json", "Unexpected JSON value")),
        }
    }

    fn parse_object(
        &mut self,
        stack: &mut Vec<Option<HashSet<String>>>,
    ) -> Result<usize, PlanError> {
        self.pos += 1; // '{'
        self.sanitized.push(b'{');
        stack.push(Some(HashSet::new()));
        let mut canonical_size = 2usize;
        let mut entries = 0usize;
        loop {
            self.skip_ws();
            let byte = *self
                .bytes
                .get(self.pos)
                .ok_or(PlanError::new("invalid_json", "Truncated JSON object"))?;
            if byte == b'}' {
                self.pos += 1;
                self.sanitized.push(b'}');
                stack.pop();
                return Ok(canonical_size);
            }
            if byte != b'"' {
                return Err(PlanError::new(
                    "invalid_json",
                    "Object keys must be strings",
                ));
            }
            let (key, key_size) = self.parse_string()?;
            if let Some(Some(keys)) = stack.last_mut() {
                if !keys.insert(key.clone()) {
                    return Err(PlanError::new(
                        "duplicate_field",
                        format!("Duplicate JSON field: {key}"),
                    ));
                }
            }
            self.skip_ws();
            if self.bytes.get(self.pos) != Some(&b':') {
                return Err(PlanError::new("invalid_json", "Object key without colon"));
            }
            self.pos += 1;
            self.sanitized.push(b':');
            let value_size = self.parse_value(stack)?;
            canonical_size = canonical_size
                .saturating_add(key_size)
                .saturating_add(1)
                .saturating_add(value_size)
                .saturating_add(usize::from(entries != 0));
            entries += 1;
            self.skip_ws();
            match self.bytes.get(self.pos) {
                Some(b',') => {
                    self.pos += 1;
                    self.sanitized.push(b',');
                }
                Some(b'}') => {
                    self.pos += 1;
                    self.sanitized.push(b'}');
                    stack.pop();
                    return Ok(canonical_size);
                }
                _ => return Err(PlanError::new("invalid_json", "Truncated JSON object")),
            }
        }
    }

    fn parse_array(
        &mut self,
        stack: &mut Vec<Option<HashSet<String>>>,
    ) -> Result<usize, PlanError> {
        self.pos += 1; // '['
        self.sanitized.push(b'[');
        stack.push(None);
        let mut canonical_size = 2usize;
        let mut entries = 0usize;
        loop {
            self.skip_ws();
            let byte = *self
                .bytes
                .get(self.pos)
                .ok_or(PlanError::new("invalid_json", "Truncated JSON array"))?;
            if byte == b']' {
                self.pos += 1;
                self.sanitized.push(b']');
                stack.pop();
                return Ok(canonical_size);
            }
            let value_size = self.parse_value(stack)?;
            canonical_size = canonical_size
                .saturating_add(value_size)
                .saturating_add(usize::from(entries != 0));
            entries += 1;
            self.skip_ws();
            match self.bytes.get(self.pos) {
                Some(b',') => {
                    self.pos += 1;
                    self.sanitized.push(b',');
                }
                Some(b']') => {
                    self.pos += 1;
                    self.sanitized.push(b']');
                    stack.pop();
                    return Ok(canonical_size);
                }
                _ => return Err(PlanError::new("invalid_json", "Truncated JSON array")),
            }
        }
    }

    /// Parse one strict RFC 8259 number and append a serde-safe equivalent.
    fn parse_number(&mut self) -> Result<usize, PlanError> {
        let start = self.pos;
        if self.bytes.get(self.pos) == Some(&b'-') {
            self.pos += 1;
        }

        let integer_start = self.pos;
        match self.bytes.get(self.pos) {
            Some(b'0') => {
                self.pos += 1;
                if self.bytes.get(self.pos).is_some_and(u8::is_ascii_digit) {
                    return Err(PlanError::new(
                        "invalid_json",
                        "Leading zero in JSON number",
                    ));
                }
            }
            Some(b'1'..=b'9') => {
                self.pos += 1;
                while self.bytes.get(self.pos).is_some_and(u8::is_ascii_digit) {
                    self.pos += 1;
                }
            }
            _ => return Err(PlanError::new("invalid_json", "Invalid JSON number")),
        }
        let integer_digits = self.pos - integer_start;

        let mut is_float = false;
        if self.bytes.get(self.pos) == Some(&b'.') {
            is_float = true;
            self.pos += 1;
            let fraction_start = self.pos;
            while self.bytes.get(self.pos).is_some_and(u8::is_ascii_digit) {
                self.pos += 1;
            }
            if self.pos == fraction_start {
                return Err(PlanError::new("invalid_json", "Invalid JSON fraction"));
            }
        }
        if matches!(self.bytes.get(self.pos), Some(b'e' | b'E')) {
            is_float = true;
            self.pos += 1;
            if matches!(self.bytes.get(self.pos), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            let exponent_start = self.pos;
            while self.bytes.get(self.pos).is_some_and(u8::is_ascii_digit) {
                self.pos += 1;
            }
            if self.pos == exponent_start {
                return Err(PlanError::new("invalid_json", "Invalid JSON exponent"));
            }
        }

        let raw = std::str::from_utf8(&self.bytes[start..self.pos])
            .expect("JSON number grammar is ASCII");
        if is_float {
            let parsed = raw.parse::<f64>().map_err(|_| {
                PlanError::new("invalid_json", "Invalid JSON floating-point number")
            })?;
            if !parsed.is_finite() {
                return Err(PlanError::new(
                    "nonfinite_json",
                    "Recovery evidence must be finite JSON data",
                ));
            }
            self.sanitized.extend_from_slice(raw.as_bytes());
            return Ok(python_float_size(parsed));
        }

        if integer_digits > PYTHON_INT_MAX_STR_DIGITS {
            return Err(PlanError::new(
                "invalid_json",
                "JSON integer exceeds CPython's default digit limit",
            ));
        }
        if raw == "-0" {
            self.sanitized.push(b'0');
            return Ok(1);
        }
        let fits_serde = if raw.starts_with('-') {
            raw.parse::<i64>().is_ok()
        } else {
            raw.parse::<u64>().is_ok()
        };
        if fits_serde {
            self.sanitized.extend_from_slice(raw.as_bytes());
        } else {
            let finite = raw.parse::<f64>().is_ok_and(f64::is_finite);
            if finite {
                let surrogate = if raw.starts_with('-') {
                    NEGATIVE_BIG_INTEGER_SURROGATE_JSON
                } else {
                    POSITIVE_BIG_INTEGER_SURROGATE_JSON
                };
                self.sanitized.extend_from_slice(surrogate);
            } else {
                // Do not interpret this string anywhere in validation. It is
                // deliberately nonnumeric so Python integers that would make
                // `math.isfinite` raise OverflowError fail numeric fields;
                // a user-authored string or object cannot spoof acceptance.
                self.sanitized.extend_from_slice(BIG_INTEGER_SENTINEL_JSON);
            }
        }
        Ok(raw.len())
    }

    /// Parse a JSON string, decoding escapes for duplicate-key comparison.
    fn parse_string(&mut self) -> Result<(String, usize), PlanError> {
        debug_assert_eq!(self.bytes.get(self.pos), Some(&b'"'));
        let start = self.pos;
        self.pos += 1;
        let mut out = String::new();
        loop {
            let byte = *self
                .bytes
                .get(self.pos)
                .ok_or(PlanError::new("invalid_json", "Truncated JSON string"))?;
            match byte {
                b'"' => {
                    self.pos += 1;
                    self.sanitized
                        .extend_from_slice(&self.bytes[start..self.pos]);
                    let canonical_size = python_string_size(&out);
                    return Ok((out, canonical_size));
                }
                b'\\' => {
                    self.pos += 1;
                    let esc = *self
                        .bytes
                        .get(self.pos)
                        .ok_or(PlanError::new("invalid_json", "Truncated JSON escape"))?;
                    self.pos += 1;
                    match esc {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{0008}'),
                        b'f' => out.push('\u{000C}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let code = self.parse_hex4()?;
                            let ch = if (0xD800..0xDC00).contains(&code) {
                                if self.bytes.get(self.pos..self.pos + 2) != Some(b"\\u") {
                                    return Err(PlanError::new(
                                        "invalid_json",
                                        "Lone surrogate in JSON string",
                                    ));
                                }
                                self.pos += 2;
                                let low = self.parse_hex4()?;
                                if !(0xDC00..0xE000).contains(&low) {
                                    return Err(PlanError::new(
                                        "invalid_json",
                                        "Lone surrogate in JSON string",
                                    ));
                                }
                                let full = 0x10000
                                    + ((u32::from(code) - 0xD800) << 10)
                                    + (u32::from(low) - 0xDC00);
                                char::from_u32(full).ok_or(PlanError::new(
                                    "invalid_json",
                                    "Invalid Unicode escape",
                                ))?
                            } else {
                                char::from_u32(u32::from(code)).ok_or(PlanError::new(
                                    "invalid_json",
                                    "Invalid Unicode escape",
                                ))?
                            };
                            out.push(ch);
                        }
                        _ => {
                            return Err(PlanError::new("invalid_json", "Invalid JSON escape"));
                        }
                    }
                }
                0x00..=0x1F => {
                    return Err(PlanError::new(
                        "invalid_json",
                        "Unescaped control in JSON string",
                    ));
                }
                0x20..=0x7f => {
                    out.push(char::from(byte));
                    self.pos += 1;
                }
                _ => {
                    // The complete document was validated as UTF-8 once in
                    // `scan_raw`; consume only this code point so a long
                    // string remains linear rather than revalidating its
                    // entire suffix for every character.
                    let width = match byte {
                        0xc2..=0xdf => 2,
                        0xe0..=0xef => 3,
                        0xf0..=0xf4 => 4,
                        _ => {
                            return Err(PlanError::new("invalid_json", "Invalid UTF-8"));
                        }
                    };
                    let encoded = self
                        .bytes
                        .get(self.pos..self.pos + width)
                        .ok_or(PlanError::new("invalid_json", "Truncated JSON string"))?;
                    let ch = std::str::from_utf8(encoded)
                        .expect("the complete document was already validated as UTF-8")
                        .chars()
                        .next()
                        .expect("a UTF-8 code point is nonempty");
                    out.push(ch);
                    self.pos += width;
                }
            }
        }
    }

    fn parse_hex4(&mut self) -> Result<u16, PlanError> {
        let digits = self
            .bytes
            .get(self.pos..self.pos + 4)
            .ok_or(PlanError::new("invalid_json", "Truncated Unicode escape"))?;
        if !digits.iter().all(|b| b.is_ascii_hexdigit()) {
            return Err(PlanError::new("invalid_json", "Invalid Unicode escape"));
        }
        let value = u16::from_str_radix(std::str::from_utf8(digits).unwrap(), 16).unwrap();
        self.pos += 4;
        Ok(value)
    }
}

/// Length of one string in CPython's default `ensure_ascii=True` rendering.
fn python_string_size(value: &str) -> usize {
    2 + value
        .chars()
        .map(|character| match character {
            '"' | '\\' | '\u{0008}' | '\u{000c}' | '\n' | '\r' | '\t' => 2,
            '\u{0000}'..='\u{001f}' => 6,
            '\u{0020}'..='\u{007e}' => 1,
            '\u{007f}'..='\u{ffff}' => 6,
            _ => 12,
        })
        .sum::<usize>()
}

/// Length of CPython's shortest round-trip float representation. serde_json
/// with `float_roundtrip` supplies the same binary64 shortest digits; Python
/// differs only in exponent thresholds/sign/padding handled below.
fn python_float_size(numeric: f64) -> usize {
    let rendered = serde_json::Number::from_f64(numeric)
        .expect("a finite Python float is a JSON number")
        .to_string();
    if let Some(separator) = rendered.find(['e', 'E']) {
        let exponent = rendered[separator + 1..]
            .parse::<i32>()
            .expect("serde_json emits a decimal exponent");
        let exponent_digits = exponent.unsigned_abs().to_string().len().max(2);
        return separator + 1 + 1 + exponent_digits;
    }
    if numeric != 0.0 && numeric.abs() < 0.0001 {
        let sign = usize::from(rendered.starts_with('-'));
        let unsigned = rendered.trim_start_matches('-');
        let fractional = unsigned
            .strip_prefix("0.")
            .expect("serde_json uses fixed notation below 0.0001 only as 0.xxx");
        let leading_zeroes = fractional.bytes().take_while(|byte| *byte == b'0').count();
        let significant = &fractional[leading_zeroes..];
        let mantissa = if significant.len() == 1 {
            1
        } else {
            significant.len() + 1
        };
        let exponent_digits = (leading_zeroes + 1).to_string().len().max(2);
        return sign + mantissa + 2 + exponent_digits;
    }
    rendered.len()
}

// ---------------------------------------------------------------------------
// Small JSON helpers mirroring `_keys`, `_same`, `_hex`.
// ---------------------------------------------------------------------------

fn check_keys(
    obj: &Map<String, Value>,
    expected: &[&str],
    reason: &'static str,
    name: &str,
) -> Result<(), PlanError> {
    let want: HashSet<&str> = expected.iter().copied().collect();
    let have: HashSet<&str> = obj.keys().map(String::as_str).collect();
    if have != want {
        return Err(PlanError::new(
            reason,
            format!("{name} has unsupported or missing fields"),
        ));
    }
    Ok(())
}

/// Bounded canonical lowercase hex, mirroring `_hex`.
fn canonical_hex(
    value: &Value,
    limit_bytes: usize,
    reason: &'static str,
) -> Result<Vec<u8>, PlanError> {
    let fail = || PlanError::new(reason, "Expected bounded canonical hexadecimal evidence");
    let text = value.as_str().ok_or_else(fail)?;
    if text.len() > limit_bytes * 2 || text.len() % 2 != 0 {
        return Err(fail());
    }
    if !text
        .bytes()
        .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return Err(fail());
    }
    hex::decode(text).map_err(|_| fail())
}

fn as_u64_in(value: &Value, lo: u64, hi: u64) -> Option<u64> {
    let n = value.as_u64()?;
    (lo..=hi).contains(&n).then_some(n)
}

/// Finite JSON number (ints and floats); JSON has no NaN/Infinity literals.
fn as_finite_f64(value: &Value) -> Option<f64> {
    let n = value.as_f64()?;
    n.is_finite().then_some(n)
}

/// Canonical comparison mirroring `_same` (booleans distinct from integers).
fn same(
    actual: &Value,
    expected: &Value,
    reason: &'static str,
    name: &str,
) -> Result<(), PlanError> {
    if actual != expected {
        return Err(PlanError::new(
            reason,
            format!("{name} is inconsistent with its evidence"),
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Endpoint / settings validation mirroring the coordinator constructors.
// ---------------------------------------------------------------------------

const SETTINGS_KEYS: [&str; 12] = [
    "overall_timeout",
    "observation_timeout",
    "confirmation_timeout",
    "mmi_response_timeout",
    "quiet_period",
    "options_response_timeout",
    "address_response_timeout",
    "max_mmi_frames",
    "max_serial_frames",
    "max_unrelated",
    "max_bytes",
    "command_checksum",
];

fn seconds(value: &Value, name: &str) -> Result<f64, PlanError> {
    match value {
        Value::Number(_) => {
            let n = as_finite_f64(value).ok_or_else(|| {
                PlanError::new("invalid_settings", format!("{name} must be finite"))
            })?;
            if n > 0.0 && n <= 60.0 {
                Ok(n)
            } else {
                Err(PlanError::new(
                    "invalid_settings",
                    format!("{name} must be finite and in (0,60] seconds"),
                ))
            }
        }
        _ => Err(PlanError::new(
            "invalid_settings",
            format!("{name} must be finite and in (0,60] seconds"),
        )),
    }
}

fn int_in(value: &Value, lo: u64, hi: u64, name: &str) -> Result<u64, PlanError> {
    as_u64_in(value, lo, hi).ok_or_else(|| {
        PlanError::new(
            "invalid_settings",
            format!("{name} must be an integer in {lo}..{hi}"),
        )
    })
}

/// Validate endpoint + settings + local identity, mirroring
/// `SelectedSerialCoordinator.__init__` (which validates without I/O via
/// `PCIInventoryCollector`, `PCILocalOptionsReader`, and
/// `PCISerialAddressTransport`).
fn validate_coordinator(
    endpoint: &Value,
    local_unit: &Value,
    expected_local_serial: &Value,
    settings: &Value,
) -> Result<(String, u16, u8, String, bool), PlanError> {
    let endpoint = endpoint.as_object().ok_or_else(|| {
        PlanError::new(
            "invalid_endpoint",
            "Endpoint has unsupported or missing fields",
        )
    })?;
    check_keys(endpoint, &["host", "port"], "invalid_endpoint", "Endpoint")?;
    let host_raw = endpoint["host"]
        .as_str()
        .ok_or_else(|| PlanError::new("invalid_endpoint", "Endpoint host must be a string"))?;
    if host_raw.contains('%') {
        return Err(PlanError::new(
            "invalid_endpoint",
            "Endpoint requires a numeric IP address without a scope suffix",
        ));
    }
    let host: std::net::IpAddr = host_raw.parse().map_err(|_| {
        PlanError::new(
            "invalid_endpoint",
            "Endpoint requires a numeric IP address; DNS is not deadline-bounded",
        )
    })?;
    let port = endpoint["port"]
        .as_u64()
        .filter(|p| (1..=65535).contains(p))
        .ok_or_else(|| PlanError::new("invalid_endpoint", "port must be an integer in 1..65535"))?
        as u16;

    let local_unit = local_unit.as_u64().filter(|u| *u <= 255).ok_or_else(|| {
        PlanError::new(
            "invalid_local_unit",
            "local_unit must be an integer in 0..255",
        )
    })? as u8;

    let expected_local_serial = expected_local_serial
        .as_str()
        .ok_or_else(|| PlanError::new("noncanonical_serial", "Plan serials must be canonical"))?;
    let parsed = parse_native_serial(expected_local_serial)
        .map_err(|_| PlanError::new("noncanonical_serial", "Plan serials must be canonical"))?;
    if !parsed.known || parsed.canonical != expected_local_serial {
        return Err(PlanError::new(
            "noncanonical_serial",
            "Plan serials must be canonical",
        ));
    }

    let settings = settings.as_object().ok_or_else(|| {
        PlanError::new(
            "invalid_settings",
            "Settings has unsupported or missing fields",
        )
    })?;
    check_keys(settings, &SETTINGS_KEYS, "invalid_settings", "Settings")?;
    let overall = match &settings["overall_timeout"] {
        Value::Number(_) => {
            let n = as_finite_f64(&settings["overall_timeout"]).ok_or_else(|| {
                PlanError::new("invalid_settings", "overall_timeout must be finite")
            })?;
            if n > 0.0 && n <= 3600.0 {
                n
            } else {
                return Err(PlanError::new(
                    "invalid_settings",
                    "overall_timeout must be finite and in (0,3600] seconds",
                ));
            }
        }
        _ => {
            return Err(PlanError::new(
                "invalid_settings",
                "overall_timeout must be finite and in (0,3600] seconds",
            ));
        }
    };
    let observation = seconds(&settings["observation_timeout"], "observation_timeout")?;
    let confirmation = seconds(&settings["confirmation_timeout"], "confirmation_timeout")?;
    let mmi_response = seconds(&settings["mmi_response_timeout"], "mmi_response_timeout")?;
    let quiet = seconds(&settings["quiet_period"], "quiet_period")?;
    let options_response = seconds(
        &settings["options_response_timeout"],
        "options_response_timeout",
    )?;
    let address_response = seconds(
        &settings["address_response_timeout"],
        "address_response_timeout",
    )?;
    // Cross-checks from the child constructors (overall_timeout there is the
    // shared observation_timeout here).
    if confirmation.max(mmi_response) > observation {
        return Err(PlanError::new(
            "invalid_settings",
            "Overall timeout must include the confirmation and response timeouts",
        ));
    }
    if observation <= quiet || confirmation > observation {
        return Err(PlanError::new(
            "invalid_settings",
            "overall_timeout must exceed quiet_period and include confirmation_timeout",
        ));
    }
    if observation <= options_response {
        return Err(PlanError::new(
            "invalid_settings",
            "overall_timeout must strictly exceed response_timeout",
        ));
    }
    if observation <= address_response {
        return Err(PlanError::new(
            "invalid_settings",
            "overall_timeout must strictly exceed response_timeout",
        ));
    }
    int_in(&settings["max_mmi_frames"], 1, 256, "max_mmi_frames")?;
    int_in(&settings["max_serial_frames"], 1, 256, "max_serial_frames")?;
    int_in(&settings["max_unrelated"], 1, 1024, "max_unrelated")?;
    int_in(&settings["max_bytes"], 1, 1048576, "max_bytes")?;
    let command_checksum = settings["command_checksum"]
        .as_bool()
        .ok_or_else(|| PlanError::new("invalid_settings", "command_checksum must be boolean"))?;
    let _ = overall;
    let _ = host;
    Ok((
        host.to_string(),
        port,
        local_unit,
        expected_local_serial.to_string(),
        command_checksum,
    ))
}

/// Canonical known serial, mirroring `_selected_serial` plus the plan-level
/// canonical-equality check.
fn canonical_serial(value: &Value) -> Result<String, PlanError> {
    let text = value
        .as_str()
        .ok_or_else(|| PlanError::new("noncanonical_serial", "Plan serials must be canonical"))?;
    let parsed = parse_native_serial(text)
        .map_err(|_| PlanError::new("noncanonical_serial", "Plan serials must be canonical"))?;
    if !parsed.known || parsed.canonical != text {
        return Err(PlanError::new(
            "noncanonical_serial",
            "Plan serials must be canonical",
        ));
    }
    Ok(text.to_string())
}

/// Reparse captured protocol bytes for one observation, mirroring `_capture`:
/// summaries never supply absence.
fn capture(
    document: &Value,
    expected_request: &[u8],
    reason: &'static str,
) -> Result<Vec<u8>, PlanError> {
    let fail = |msg: &str| PlanError::new(reason, msg.to_string());
    let doc = document
        .as_object()
        .ok_or_else(|| fail("Missing complete observation"))?;
    for key in ["complete", "connection_closed"] {
        if doc.get(key) != Some(&Value::Bool(true)) {
            return Err(fail("Observation is incomplete or unclosed"));
        }
    }
    if doc.get("errors") != Some(&Value::Array(vec![]))
        || doc.get("unrelated") != Some(&Value::Array(vec![]))
    {
        return Err(fail(
            "Commissioning requires an observation without errors or unrelated traffic",
        ));
    }
    let request_hex = doc
        .get("request_hex")
        .and_then(Value::as_str)
        .ok_or_else(|| fail("Observation request is inconsistent with its evidence"))?;
    if request_hex != hex::encode(expected_request) {
        return Err(fail(
            "Observation request is inconsistent with its evidence",
        ));
    }
    let raw = canonical_hex(
        doc.get("received_hex").unwrap_or(&Value::Null),
        65536,
        reason,
    )
    .map_err(|_| fail("Expected bounded canonical hexadecimal evidence"))?;
    match doc.get("bytes_received").and_then(Value::as_u64) {
        Some(n) if n as usize == raw.len() => Ok(raw),
        _ => Err(fail(
            "Captured byte count is inconsistent with its evidence",
        )),
    }
}

// ---------------------------------------------------------------------------
// MMI proof, mirroring `_raw_mmi`.
// ---------------------------------------------------------------------------

fn raw_mmi(document: &Value, local: u8, command_checksum: bool) -> Result<Vec<u64>, PlanError> {
    let reason = "mmi_proof";
    let fail = |msg: &str| PlanError::new(reason, msg.to_string());
    let raw = capture(
        document,
        &installation_mmi_request(command_checksum),
        reason,
    )?;
    let doc = document
        .as_object()
        .ok_or_else(|| fail("Unsupported MMI observation"))?;
    if doc.get("format") != Some(&Value::from("cbus-pci-mmi-observation-v1"))
        || doc.get("termination") != Some(&Value::from("coverage_complete"))
    {
        return Err(fail("Unsupported MMI observation"));
    }
    let (events, leftover) = parse_mmi_capture(&raw).map_err(|e| fail(&e))?;
    if !leftover.is_empty() || events.is_empty() || events[0] != MmiEvent::Confirmation(b'g', '.') {
        return Err(fail("MMI confirmation/framing is incomplete"));
    }
    let mut states: Vec<u64> = Vec::new();
    let mut blocks: Vec<Value> = Vec::new();
    for event in events.into_iter().skip(1) {
        let MmiEvent::Block(block) = event else {
            return Err(fail(
                "MMI blocks must independently cover the whole range without gaps or overlap",
            ));
        };
        let start = usize::from(block.start);
        let block_states: Vec<u64> = block.states.iter().map(|state| u64::from(*state)).collect();
        if block.application != 255 || start != states.len() {
            return Err(fail(
                "MMI blocks must independently cover the whole range without gaps or overlap",
            ));
        }
        let end = start + block_states.len();
        blocks.push(Value::Object(Map::from_iter([
            (
                "application".to_string(),
                Value::from(u64::from(block.application)),
            ),
            ("start".to_string(), Value::from(start as u64)),
            ("end_exclusive".to_string(), Value::from(end as u64)),
            (
                "states".to_string(),
                Value::Array(block_states.iter().map(|s| Value::from(*s)).collect()),
            ),
            ("marker".to_string(), Value::from(u64::from(block.marker))),
            ("raw_hex".to_string(), Value::from(hex::encode(&block.raw))),
        ])));
        states.extend(block_states);
    }
    if states.len() != 256 || states[usize::from(local)] == 0 || states.contains(&3) {
        return Err(fail(
            "MMI coverage, known local presence or healthy states are missing",
        ));
    }
    same(
        doc.get("local_unit").unwrap_or(&Value::Null),
        &Value::from(u64::from(local)),
        reason,
        "MMI local address",
    )?;
    same(
        doc.get("states").unwrap_or(&Value::Null),
        &Value::Array(states.iter().map(|s| Value::from(*s)).collect()),
        reason,
        "MMI state vector",
    )?;
    same(
        doc.get("blocks").unwrap_or(&Value::Null),
        &Value::Array(blocks),
        reason,
        "MMI blocks",
    )?;
    same(
        doc.get("confirmation").unwrap_or(&Value::Null),
        &Value::from("."),
        reason,
        "MMI confirmation",
    )?;
    Ok(states)
}

// ---------------------------------------------------------------------------
// Serial proof, mirroring `_raw_serials`.
// ---------------------------------------------------------------------------

fn sort_key(serial: &str) -> (u64, u64) {
    let mut parts = serial.split('.');
    (
        parts
            .next()
            .and_then(|p| p.parse().ok())
            .unwrap_or(u64::MAX),
        parts
            .next()
            .and_then(|p| p.parse().ok())
            .unwrap_or(u64::MAX),
    )
}

fn raw_serials(
    document: &Value,
    local: u8,
    command_checksum: bool,
    check_stored_serials: bool,
) -> Result<(u8, Vec<String>), PlanError> {
    let reason = "serial_proof";
    let fail = |msg: &str| PlanError::new(reason, msg.to_string());
    let doc = document
        .as_object()
        .ok_or_else(|| fail("Invalid inventory address"))?;
    let address = doc
        .get("address")
        .and_then(Value::as_u64)
        .filter(|a| *a <= 255)
        .ok_or_else(|| fail("Invalid inventory address"))? as u8;
    let raw = capture(
        document,
        &identify_request(address, 4, command_checksum),
        reason,
    )?;
    if doc.get("format") != Some(&Value::from("cbus-pci-serial-observation-v1"))
        || doc.get("termination") != Some(&Value::from("quiet"))
    {
        return Err(fail("Serial collection did not complete its quiet window"));
    }
    same(
        doc.get("local_unit").unwrap_or(&Value::Null),
        &Value::from(u64::from(local)),
        reason,
        "Serial local address",
    )?;
    let (events, leftover) = parse_capture(&raw).map_err(|e| fail(&e))?;
    if !leftover.is_empty() || events.is_empty() || events[0] != PciEvent::Confirmation(b'g', '.') {
        return Err(fail("Serial confirmation/framing is incomplete"));
    }
    let mut found: HashMap<String, Vec<u8>> = HashMap::new();
    let mut replies: Vec<(PciFrame, String)> = Vec::new();
    for event in events.into_iter().skip(1) {
        let PciEvent::Frame(frame) = event else {
            return Err(fail("Unexpected serial capture event"));
        };
        if frame.cals.len() != 1 {
            return Err(fail("Unexpected serial capture event"));
        }
        if !frame.raw.iter().all(|b| b.is_ascii_hexdigit()) {
            return Err(fail("Unexpected serial frame prefix"));
        }
        if frame.bare() {
            if address != local {
                return Err(fail("Remote bare serial cannot be attributed"));
            }
        } else if frame.source != Some(address)
            || frame.destination != Some(local)
            || frame.route != vec![0x00]
        {
            return Err(fail("Serial frame source/destination/route mismatch"));
        }
        let Cal::Reply { parameter, data } = &frame.cals[0] else {
            return Err(fail("IDENTIFY4 must contain twelve bytes"));
        };
        if *parameter != 4 || data.len() != 12 {
            return Err(fail("IDENTIFY4 must contain twelve bytes"));
        }
        let packed = u32::from_be_bytes(data[5..9].try_into().unwrap());
        if packed == 0 || packed == u32::MAX {
            return Err(fail("The same serial has conflicting identity blocks"));
        }
        let canonical = format!("{}.{}", packed >> 12, packed & 4095);
        if let Some(previous) = found.get(&canonical) {
            if previous != data {
                return Err(fail("The same serial has conflicting identity blocks"));
            }
        }
        found.insert(canonical.clone(), data.clone());
        replies.push((frame, canonical));
    }
    let mut serials: Vec<String> = found.keys().cloned().collect();
    serials.sort_by_key(|s| sort_key(s));
    if serials.is_empty() {
        return Err(fail("A present address has no known serial"));
    }
    if check_stored_serials {
        same(
            doc.get("serials").unwrap_or(&Value::Null),
            &Value::Array(serials.iter().map(|s| Value::from(s.clone())).collect()),
            reason,
            "Serial list",
        )?;
    }
    same(
        doc.get("confirmation").unwrap_or(&Value::Null),
        &Value::from("."),
        reason,
        "Serial confirmation",
    )?;
    let recorded = doc
        .get("replies")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("Serial reply evidence differs from the capture"))?;
    if recorded.len() != replies.len() {
        return Err(fail("Serial reply evidence differs from the capture"));
    }
    for (actual, (frame, serial)) in recorded.iter().zip(replies.iter()) {
        let actual_obj = actual
            .as_object()
            .ok_or_else(|| fail("Serial reply evidence differs from the capture"))?;
        check_keys(
            actual_obj,
            &[
                "source",
                "destination",
                "serial",
                "known",
                "data_hex",
                "raw_hex",
                "received_after_seconds",
            ],
            reason,
            "Serial reply",
        )?;
        let Cal::Reply { data, .. } = &frame.cals[0] else {
            return Err(fail("IDENTIFY4 must contain twelve bytes"));
        };
        let mut expected = Map::new();
        expected.insert(
            "source".to_string(),
            frame
                .source
                .map_or(Value::Null, |s| Value::from(u64::from(s))),
        );
        expected.insert(
            "destination".to_string(),
            frame
                .destination
                .map_or(Value::Null, |d| Value::from(u64::from(d))),
        );
        expected.insert("serial".to_string(), Value::from(serial.clone()));
        expected.insert("known".to_string(), Value::Bool(true));
        expected.insert("data_hex".to_string(), Value::from(hex::encode(data)));
        expected.insert("raw_hex".to_string(), Value::from(hex::encode(&frame.raw)));
        expected.insert(
            "received_after_seconds".to_string(),
            actual_obj["received_after_seconds"].clone(),
        );
        same(actual, &Value::Object(expected), reason, "Serial reply")?;
        match &actual_obj["received_after_seconds"] {
            Value::Number(_) => {
                let elapsed = as_finite_f64(&actual_obj["received_after_seconds"])
                    .ok_or_else(|| fail("Invalid serial arrival time"))?;
                if elapsed < 0.0 {
                    return Err(fail("Invalid serial arrival time"));
                }
            }
            _ => return Err(fail("Invalid serial arrival time")),
        }
    }
    Ok((address, serials))
}

// ---------------------------------------------------------------------------
// Inventory / options / expected proofs.
// ---------------------------------------------------------------------------

struct BeforeProof {
    states: Vec<u64>,
    identities: AddressIdentities,
}

/// Address-sorted `(address, serials)` identity rows.
type AddressIdentities = Vec<(u8, Vec<String>)>;

fn inventory_proof(
    document: &Value,
    endpoint: &Value,
    local: u8,
    command_checksum: bool,
) -> Result<BeforeProof, PlanError> {
    let fail = |msg: &str| PlanError::new("inventory_proof", msg.to_string());
    let doc = document
        .as_object()
        .ok_or_else(|| fail("Unsupported inventory format"))?;
    if doc.get("format") != Some(&Value::from("cbus-pci-inventory-observation-v1")) {
        return Err(fail("Unsupported inventory format"));
    }
    same(
        doc.get("endpoint").unwrap_or(&Value::Null),
        endpoint,
        "inventory_proof",
        "Inventory endpoint",
    )?;
    same(
        doc.get("local_unit").unwrap_or(&Value::Null),
        &Value::from(u64::from(local)),
        "inventory_proof",
        "Inventory local address",
    )?;
    for key in [
        "complete",
        "collection_complete",
        "consistent",
        "membership_unchanged",
        "connection_closed",
        "mmi_healthy",
    ] {
        if doc.get(key) != Some(&Value::Bool(true)) {
            return Err(fail("Full consistent healthy inventory is required"));
        }
    }
    if doc.get("termination") != Some(&Value::from("sequence_complete"))
        || doc.get("errors") != Some(&Value::Array(vec![]))
    {
        return Err(fail("Inventory collection did not complete"));
    }
    let first = raw_mmi(
        doc.get("initial_mmi").unwrap_or(&Value::Null),
        local,
        command_checksum,
    )?;
    let last = raw_mmi(
        doc.get("final_mmi").unwrap_or(&Value::Null),
        local,
        command_checksum,
    )?;
    if first != last {
        return Err(PlanError::new("mmi_proof", "Full MMI bookends"));
    }
    let observations = doc
        .get("serial_observations")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("Missing serial observations"))?;
    let mut identities = Vec::new();
    for item in observations {
        identities.push(raw_serials(item, local, command_checksum, true)?);
    }
    let addresses: Vec<u64> = first
        .iter()
        .enumerate()
        .filter_map(|(address, state)| (*state != 0).then_some(address as u64))
        .collect();
    same(
        &Value::Array(
            identities
                .iter()
                .map(|(address, _)| Value::from(u64::from(*address)))
                .collect(),
        ),
        &Value::Array(addresses.iter().map(|a| Value::from(*a)).collect()),
        "inventory_proof",
        "Serial coverage",
    )?;
    same(
        doc.get("planned_addresses").unwrap_or(&Value::Null),
        &Value::Array(addresses.iter().map(|a| Value::from(*a)).collect()),
        "inventory_proof",
        "Planned coverage",
    )?;
    same(
        doc.get("unattempted_addresses").unwrap_or(&Value::Null),
        &Value::Array(vec![]),
        "inventory_proof",
        "Unattempted addresses",
    )?;
    let mut seen: HashSet<String> = HashSet::new();
    for (_, serials) in &identities {
        for serial in serials {
            if !seen.insert(serial.clone()) {
                return Err(fail("A serial appears at multiple addresses"));
            }
        }
    }
    let duplicates: Vec<Value> = identities
        .iter()
        .filter_map(|(address, serials)| {
            (serials.len() > 1).then_some(Value::from(u64::from(*address)))
        })
        .collect();
    same(
        doc.get("duplicate_addresses").unwrap_or(&Value::Null),
        &Value::Array(duplicates),
        "inventory_proof",
        "Duplicate-address summary",
    )?;
    for key in [
        "serial_conflicts",
        "missing_serial_addresses",
        "changed_states",
        "error_addresses",
    ] {
        same(
            doc.get(key).unwrap_or(&Value::Null),
            &Value::Array(vec![]),
            "inventory_proof",
            key,
        )?;
    }
    Ok(BeforeProof {
        states: first,
        identities,
    })
}

fn parse_local_options(received: &[u8], local: u8) -> Result<u8, String> {
    if received.len() > 4096 {
        return Err("Local options capture must be at most 4096 bytes".to_string());
    }
    let (events, leftover) = parse_capture(received)?;
    if !leftover.is_empty() || events.len() != 2 {
        return Err("Local options require one whole confirmation and one whole reply".to_string());
    }
    if events[0] != PciEvent::Confirmation(b'g', '.') {
        return Err("Local options require the successful expected confirmation first".to_string());
    }
    let PciEvent::Frame(frame) = &events[1] else {
        return Err("Only the proven bare local RECALL reply is supported".to_string());
    };
    if !frame.bare() || frame.cals.len() != 1 {
        return Err("Only the proven bare local RECALL reply is supported".to_string());
    }
    if !frame.raw.iter().all(|b| b.is_ascii_hexdigit()) {
        return Err("Local options require exactly parameter 66 and one byte".to_string());
    }
    let Cal::Reply { parameter, data } = &frame.cals[0] else {
        return Err("Local options require exactly parameter 66 and one byte".to_string());
    };
    if *parameter != 66 || data.len() != 1 {
        return Err("Local options require exactly parameter 66 and one byte".to_string());
    }
    let _ = local;
    Ok(data[0])
}

fn options_proof(document: &Value, local: u8, command_checksum: bool) -> Result<(), PlanError> {
    let reason = "local_options_proof";
    let fail = |msg: &str| PlanError::new(reason, msg.to_string());
    let doc = document
        .as_object()
        .ok_or_else(|| fail("Unsupported local options observation"))?;
    check_keys(
        doc,
        &[
            "format",
            "local_unit",
            "request_hex",
            "received_hex",
            "value",
            "send_attempted",
            "capture_complete",
            "complete",
            "termination",
            "connection_closed",
            "errors",
            "timing",
            "bare_reply_attribution",
            "identity_verified",
            "options_changed",
            "automatic_retries",
        ],
        reason,
        "Local options observation",
    )?;
    // The strict 16-field set mirrors the oracle `_keys` tuple exactly.
    same(
        &doc["request_hex"],
        &Value::from(hex::encode(recall_request(local, 66, 1, command_checksum))),
        reason,
        "Local options request",
    )?;
    same(
        &doc["local_unit"],
        &Value::from(u64::from(local)),
        reason,
        "Options local address",
    )?;
    if doc.get("format") != Some(&Value::from("cbus-pci-local-options-observation-v1"))
        || [
            "complete",
            "capture_complete",
            "send_attempted",
            "connection_closed",
        ]
        .iter()
        .any(|key| doc.get(*key) != Some(&Value::Bool(true)))
        || doc.get("errors") != Some(&Value::Array(vec![]))
        || doc.get("termination") != Some(&Value::from("response_window_elapsed"))
    {
        return Err(fail(
            "A complete fresh local options observation is required",
        ));
    }
    let received = canonical_hex(
        doc.get("received_hex").unwrap_or(&Value::Null),
        4096,
        reason,
    )
    .map_err(|_| fail("Expected bounded canonical hexadecimal evidence"))?;
    let value = parse_local_options(&received, local).map_err(|e| fail(&e))?;
    same(
        &doc["value"],
        &Value::from(u64::from(value)),
        reason,
        "Local options value",
    )?;
    if value != 5 {
        return Err(fail(
            "The bounded coordinator requires freshly observed local option byte 05",
        ));
    }
    Ok(())
}

fn expected_after_value(states: &[u64], identities: &AddressIdentities) -> Value {
    Value::Object(Map::from_iter([
        (
            "states".to_string(),
            Value::Array(states.iter().map(|s| Value::from(*s)).collect()),
        ),
        (
            "identities".to_string(),
            Value::Array(
                identities
                    .iter()
                    .map(|(address, serials)| {
                        Value::Object(Map::from_iter([
                            ("address".to_string(), Value::from(u64::from(*address))),
                            (
                                "serials".to_string(),
                                Value::Array(
                                    serials.iter().map(|s| Value::from(s.clone())).collect(),
                                ),
                            ),
                        ]))
                    })
                    .collect(),
            ),
        ),
    ]))
}

/// Recompute the expected selected-serial change identically to `_expected`.
fn expected_change(
    before: &BeforeProof,
    serial: &str,
    destination: u8,
    local_serial: &str,
    local: u8,
) -> Result<(Vec<u64>, AddressIdentities), PlanError> {
    let fail = |msg: &str| PlanError::new("expected_after_mismatch", msg.to_string());
    let mut identities: HashMap<u8, Vec<String>> = HashMap::new();
    for (address, serials) in &before.identities {
        identities.insert(*address, serials.clone());
    }
    if identities.get(&local) != Some(&vec![local_serial.to_string()]) {
        return Err(fail("Pinned local PCI serial does not match"));
    }
    match identities.get(&255) {
        Some(serials) if serials.len() == 2 && serials.contains(&serial.to_string()) => {}
        _ => {
            return Err(fail(
                "Source 255 must contain exactly two distinct serials including the selected serial",
            ));
        }
    }
    if identities
        .iter()
        .any(|(address, serials)| *address != 255 && serials.len() != 1)
    {
        return Err(fail(
            "Other duplicate addresses are outside the supported scope",
        ));
    }
    if destination == local
        || identities.contains_key(&destination)
        || before.states[usize::from(destination)] != 0
    {
        return Err(fail("Destination must be independently empty and nonlocal"));
    }
    if before.states[255] != 2 {
        return Err(fail("The supported source fixture must have MMI state 2"));
    }
    let entry = identities.get_mut(&255).unwrap();
    entry.retain(|s| s != serial);
    identities.insert(destination, vec![serial.to_string()]);
    let mut states = before.states.clone();
    states[usize::from(destination)] = states[255];
    let mut sorted: AddressIdentities = identities.into_iter().collect();
    sorted.sort_by_key(|(address, _)| *address);
    Ok((states, sorted))
}

// ---------------------------------------------------------------------------
// Top-level document validation, mirroring `SelectedSerialPlan.from_dict`.
// ---------------------------------------------------------------------------

const PLAN_KEYS: [&str; 17] = [
    "format",
    "endpoint",
    "local_unit",
    "expected_local_serial",
    "source",
    "serial",
    "destination",
    "settings",
    "before",
    "local_identity",
    "local_options",
    "expected_after",
    "request_hex",
    "scope",
    "atomic_observation",
    "firmware_persistence_verified",
    "exclusive_ownership_required",
];

fn validate_plan(doc: &Map<String, Value>) -> Result<ValidatedPlan, PlanError> {
    check_keys(doc, &PLAN_KEYS, "plan_fields", "Plan")?;
    if doc.get("format") != Some(&Value::from("cbus-selected-serial-plan-v1")) {
        return Err(PlanError::new(
            "unsupported_format",
            "Unsupported selected-serial plan",
        ));
    }
    let (host, port, local_unit, expected_local_serial, command_checksum) = validate_coordinator(
        &doc["endpoint"],
        &doc["local_unit"],
        &doc["expected_local_serial"],
        &doc["settings"],
    )?;
    let serial = canonical_serial(&doc["serial"])?;
    if serial != doc["serial"].as_str().unwrap_or_default()
        || expected_local_serial != doc["expected_local_serial"].as_str().unwrap_or_default()
    {
        return Err(PlanError::new(
            "noncanonical_serial",
            "Plan serials must be canonical",
        ));
    }
    if doc.get("source").and_then(Value::as_u64) != Some(255) {
        return Err(PlanError::new(
            "unsupported_source",
            "Only source 255 is supported",
        ));
    }
    let destination = doc
        .get("destination")
        .and_then(Value::as_u64)
        .filter(|d| (2..=254).contains(d))
        .ok_or_else(|| {
            PlanError::new(
                "invalid_destination",
                "Selected-serial destination must be an integer in the supported range 2..254",
            )
        })? as u8;
    let request_bytes = encode_serial_address(&serial, destination, command_checksum, b'g')
        .map_err(|_| {
            PlanError::new(
                "invalid_destination",
                "Selected-serial destination must be an integer in the supported range 2..254",
            )
        })?;
    same(
        doc.get("request_hex").unwrap_or(&Value::Null),
        &Value::from(hex::encode(&request_bytes)),
        "request_mismatch",
        "Address request",
    )?;
    let proof = inventory_proof(
        &doc["before"],
        &doc["endpoint"],
        local_unit,
        command_checksum,
    )?;
    // Fresh local identity must match the pinned serial. The stored serial
    // list is compared against the re-parsed bytes here (rather than inside
    // the serial reparse) so a swapped serial list reports
    // `local_identity_mismatch` instead of `serial_proof`; accept/reject
    // verdicts are identical to the oracle either way.
    let (observed_local, observed_serials) =
        raw_serials(&doc["local_identity"], local_unit, command_checksum, false).map_err(|e| {
            PlanError::new(e.reason, format!("Local identity reparse: {}", e.message))
        })?;
    if observed_local != local_unit || observed_serials != vec![expected_local_serial.clone()] {
        return Err(PlanError::new(
            "local_identity_mismatch",
            "Fresh local identity does not match the pinned serial",
        ));
    }
    if doc["local_identity"]
        .get("serials")
        .map(|s| s != &Value::Array(vec![Value::from(expected_local_serial.clone())]))
        .unwrap_or(true)
    {
        return Err(PlanError::new(
            "local_identity_mismatch",
            "Fresh local identity does not match the pinned serial",
        ));
    }
    options_proof(&doc["local_options"], local_unit, command_checksum)?;
    let (states, identities) = expected_change(
        &proof,
        &serial,
        destination,
        &expected_local_serial,
        local_unit,
    )?;
    same(
        doc.get("expected_after").unwrap_or(&Value::Null),
        &expected_after_value(&states, &identities),
        "expected_after_mismatch",
        "Expected selected-serial change",
    )?;
    same(
        doc.get("scope").unwrap_or(&Value::Null),
        &Value::from("two_known_serials_at_255_explicit_empty_destination"),
        "scope_mismatch",
        "Scope",
    )?;
    same(
        doc.get("atomic_observation").unwrap_or(&Value::Null),
        &Value::Bool(false),
        "atomicity_mismatch",
        "Atomicity",
    )?;
    same(
        doc.get("firmware_persistence_verified")
            .unwrap_or(&Value::Null),
        &Value::Bool(false),
        "persistence_mismatch",
        "Persistence",
    )?;
    same(
        doc.get("exclusive_ownership_required")
            .unwrap_or(&Value::Null),
        &Value::Bool(true),
        "ownership_mismatch",
        "Ownership prerequisite",
    )?;
    Ok(ValidatedPlan {
        serial,
        destination,
        request_hex: hex::encode(&request_bytes),
        request_bytes,
        command_checksum,
        source: 255,
        local_unit,
        expected_local_serial,
        host,
        port,
    })
}

/// Parse and fully verify one `cbus-selected-serial-plan-v1` document.
///
/// Pure: no I/O, no clock reads. Every failure carries a machine-stable
/// [`PlanError::reason`] per failure class.
pub fn validate_plan_document(raw: &[u8]) -> Result<ValidatedPlan, PlanError> {
    validate_plan_document_with_value(raw).map(|(plan, _)| plan)
}

/// Return the validated plan and the same sanitized value used to validate it.
///
/// Consumers must use this value rather than reparsing the raw input: the
/// scanner enforces raw/canonical size bounds and duplicate-key rejection,
/// and normalizes Python numbers outside serde_json's supported range.
pub fn validate_plan_document_with_value(raw: &[u8]) -> Result<(ValidatedPlan, Value), PlanError> {
    if raw.len() > MAX_PLAN_BYTES {
        return Err(PlanError::new(
            "oversize",
            "Recovery file exceeds its size bound",
        ));
    }
    let (value, python_canonical_size) = parse_strict_json_value(raw)?;
    if python_canonical_size > MAX_PLAN_BYTES {
        return Err(PlanError::new(
            "canonical_oversize",
            "Recovery evidence exceeds its size bound",
        ));
    }
    let doc = value.as_object().ok_or_else(|| {
        PlanError::new(
            "non_object_document",
            "Plan has unsupported or missing fields",
        )
    })?;
    let plan = validate_plan(doc)?;
    Ok((plan, value))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_plan_document_value() -> Value {
        let outer: Value = serde_json::from_str(
            include_str!("../../testdata/vectors/selected_serial_plan.jsonl")
                .lines()
                .next()
                .unwrap(),
        )
        .unwrap();
        outer["document"].clone()
    }

    fn inject_raw_number(mut document: Value, pointer: &str, raw_number: &str) -> Vec<u8> {
        const PLACEHOLDER: &str = "__raw_python_integer_for_test__";
        *document
            .pointer_mut(pointer)
            .expect("test JSON pointer must exist") = Value::from(PLACEHOLDER);
        let encoded = serde_json::to_string(&document).unwrap();
        let quoted = format!("\"{PLACEHOLDER}\"");
        assert_eq!(encoded.matches(&quoted).count(), 1);
        encoded.replacen(&quoted, raw_number, 1).into_bytes()
    }

    #[test]
    fn validated_document_returns_the_scanned_value() {
        let mut document = valid_plan_document_value();
        document["before"]["timing"]["ignored_python_integer"] = Value::Null;
        let raw = inject_raw_number(
            document,
            "/before/timing/ignored_python_integer",
            &format!("1{}", "0".repeat(1_000)),
        );
        let (plan, value) = validate_plan_document_with_value(&raw).unwrap();

        assert_eq!(plan, validate_plan_document(&raw).unwrap());
        assert_eq!(value["serial"].as_str(), Some(plan.serial.as_str()));
        assert_eq!(
            value["before"]["timing"]["ignored_python_integer"],
            serde_json::from_slice::<Value>(BIG_INTEGER_SENTINEL_JSON).unwrap()
        );
    }

    #[test]
    fn validated_document_requires_raw_and_semantic_validation() {
        assert_eq!(
            validate_plan_document_with_value(br#"{"a":{"b":1,"b":2}}"#)
                .unwrap_err()
                .reason(),
            "duplicate_field"
        );
        assert_eq!(
            validate_plan_document_with_value(&vec![b' '; MAX_PLAN_BYTES + 1])
                .unwrap_err()
                .reason(),
            "oversize"
        );

        let mut document = valid_plan_document_value();
        document["request_hex"] = Value::from("00");
        assert_eq!(
            validate_plan_document_with_value(&serde_json::to_vec(&document).unwrap())
                .unwrap_err()
                .reason(),
            "request_mismatch"
        );
    }

    #[test]
    fn validated_document_requires_canonical_size_validation() {
        let mut document = valid_plan_document_value();
        document["before"]["timing"]["ignored_text"] = Value::from("é".repeat(MAX_PLAN_BYTES / 6));
        let raw = serde_json::to_vec(&document).unwrap();
        assert!(raw.len() < MAX_PLAN_BYTES);
        assert_eq!(
            validate_plan_document_with_value(&raw)
                .unwrap_err()
                .reason(),
            "canonical_oversize"
        );
    }

    #[test]
    fn duplicate_scanner_rejects_nested_duplicates() {
        let raw = br#"{"a":{"b":1,"b":2}}"#;
        assert_eq!(
            validate_plan_document(raw).unwrap_err().reason(),
            "duplicate_field"
        );
    }

    #[test]
    fn nonfinite_constants_rejected_before_parse() {
        for raw in [br#"{"value":NaN}"#.as_slice(), br#"[Infinity]"#.as_slice()] {
            assert_eq!(
                validate_plan_document(raw).unwrap_err().reason(),
                "nonfinite_json"
            );
        }
    }

    #[test]
    fn oversize_rejected_before_parse() {
        let big = vec![b' '; MAX_PLAN_BYTES + 1];
        assert_eq!(
            validate_plan_document(&big).unwrap_err().reason(),
            "oversize"
        );
    }

    #[test]
    fn canonical_size_matches_python_exponents_and_ascii_escaping() {
        for (raw, expected) in [
            ("1e-7", 5),
            ("1e-5", 5),
            ("1e-4", 6),
            ("1e16", 5),
            ("-0.0", 4),
            ("4.03e217", 9),
            (r#""\u007f""#, 8),
            (r#""é😀\n""#, 22),
        ] {
            assert_eq!(
                scan_raw(raw.as_bytes()).unwrap().python_canonical_size,
                expected,
                "{raw}"
            );
        }
    }

    #[test]
    fn python_big_integer_is_accepted_when_ignored_and_rejected_when_required() {
        let mut document = valid_plan_document_value();
        let placeholder = "__raw_python_big_integer_for_test__";
        document["before"]["timing"]["ignored_python_integer"] = Value::from(placeholder);
        let encoded = serde_json::to_string(&document).unwrap();
        let big = format!("1{}", "0".repeat(1_000));
        let raw = encoded.replace(&format!("\"{placeholder}\""), &big);
        validate_plan_document(raw.as_bytes()).unwrap();

        document["source"] = Value::from(placeholder);
        let encoded = serde_json::to_string(&document).unwrap();
        let raw = encoded.replace(&format!("\"{placeholder}\""), &big);
        assert_eq!(
            validate_plan_document(raw.as_bytes()).unwrap_err().reason(),
            "unsupported_source"
        );

        assert_eq!(
            scan_raw(big.as_bytes()).unwrap().python_canonical_size,
            1_001
        );
        assert_eq!(
            validate_plan_document(big.as_bytes()).unwrap_err().reason(),
            "non_object_document"
        );
    }

    #[test]
    fn python_big_integer_arrival_timing_matches_finite_conversion() {
        const TIMING: &str = "/before/serial_observations/0/replies/0/received_after_seconds";

        let positive =
            inject_raw_number(valid_plan_document_value(), TIMING, "18446744073709551616");
        validate_plan_document(&positive).unwrap();

        let negative =
            inject_raw_number(valid_plan_document_value(), TIMING, "-9223372036854775809");
        assert_eq!(
            validate_plan_document(&negative).unwrap_err().reason(),
            "serial_proof"
        );

        let huge = format!("1{}", "0".repeat(1_000));
        let overflowing = inject_raw_number(valid_plan_document_value(), TIMING, &huge);
        assert_eq!(
            validate_plan_document(&overflowing).unwrap_err().reason(),
            "serial_proof"
        );
    }

    #[test]
    fn integer_digit_limit_and_negative_zero_match_cpython() {
        let at_limit = format!("1{}", "0".repeat(PYTHON_INT_MAX_STR_DIGITS - 1));
        assert!(scan_raw(at_limit.as_bytes()).is_ok());
        let over_limit = format!("1{}", "0".repeat(PYTHON_INT_MAX_STR_DIGITS));
        assert_eq!(
            scan_raw(over_limit.as_bytes()).unwrap_err().reason(),
            "invalid_json"
        );

        let scan = scan_raw(b"-0").unwrap();
        assert_eq!(scan.sanitized, b"0");
        assert_eq!(scan.python_canonical_size, 1);
        assert_eq!(
            validate_plan_document(b"-0").unwrap_err().reason(),
            "non_object_document"
        );
    }

    #[test]
    fn strict_number_grammar_is_checked_before_sanitizing() {
        for raw in ["-", "01", "-01", "1.", "1e", "1e+", "+1"] {
            assert_eq!(
                scan_raw(raw.as_bytes()).unwrap_err().reason(),
                "invalid_json",
                "{raw}"
            );
        }
    }

    #[test]
    fn python_float_roundtrip_preserves_long_edge() {
        let raw = b"0.09999999999999999";
        let scan = scan_raw(raw).unwrap();
        assert_eq!(scan.python_canonical_size, raw.len());
        let parsed: Value = serde_json::from_slice(&scan.sanitized).unwrap();
        assert_eq!(parsed.as_f64(), Some(0.09999999999999999));
    }

    #[test]
    fn python_float_roundtrip_does_not_create_false_oversize() {
        let mut raw = Vec::with_capacity(2_200_001);
        raw.push(b'[');
        for index in 0..200_000 {
            if index != 0 {
                raw.push(b',');
            }
            raw.extend_from_slice(b"4.03e217");
        }
        raw.push(b']');
        assert!(raw.len() < MAX_PLAN_BYTES);
        assert_eq!(scan_raw(&raw).unwrap().python_canonical_size, 2_000_001);
        assert_eq!(
            validate_plan_document(&raw).unwrap_err().reason(),
            "non_object_document"
        );
    }

    #[test]
    fn canonical_reserialization_size_is_bounded() {
        // Compact `1e-7` tokens fit in the raw 4 MiB envelope, while
        // CPython canonicalizes each to `1e-07` and crosses the same bound.
        let mut raw = Vec::with_capacity(3_500_001);
        raw.push(b'[');
        for index in 0..700_000 {
            if index != 0 {
                raw.push(b',');
            }
            raw.extend_from_slice(b"1e-7");
        }
        raw.push(b']');
        assert!(raw.len() < MAX_PLAN_BYTES);
        assert_eq!(
            validate_plan_document(&raw).unwrap_err().reason(),
            "canonical_oversize"
        );
    }

    #[test]
    fn scanner_bounds_nesting_and_handles_a_near_limit_string() {
        let nested = format!("{}0{}", "[".repeat(10_000), "]".repeat(10_000));
        assert_eq!(
            validate_plan_document(nested.as_bytes())
                .unwrap_err()
                .reason(),
            "invalid_json"
        );

        let at_limit = format!(
            "{}0{}",
            "[".repeat(Scanner::MAX_DEPTH),
            "]".repeat(Scanner::MAX_DEPTH)
        );
        assert_eq!(
            validate_plan_document(at_limit.as_bytes())
                .unwrap_err()
                .reason(),
            "non_object_document"
        );
        let over_limit = format!("[{at_limit}]");
        assert_eq!(
            validate_plan_document(over_limit.as_bytes())
                .unwrap_err()
                .reason(),
            "invalid_json"
        );

        let long = format!("\"{}é\"", "a".repeat(MAX_PLAN_BYTES - 8));
        assert!(long.len() < MAX_PLAN_BYTES);
        assert_eq!(
            validate_plan_document(long.as_bytes())
                .unwrap_err()
                .reason(),
            "non_object_document"
        );
    }
}
