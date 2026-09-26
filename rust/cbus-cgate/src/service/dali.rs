//! Native-evidenced C-Gate 3.4 DALI core and emergency commands.

use super::*;
use cbus_protocol::dali::{parse_mask, DaliCalMode, DaliLine};
use cbus_protocol::serial_address::parse_native_serial;

const DEVICE_TYPE_DALI: u8 = 0xda;

#[derive(Debug, Clone, Copy)]
enum PayloadKind {
    None,
    Short,
    OptionalAddress,
    Mask64,
    PairShort,
    Reassign,
    Wink,
    TriggerScene,
    ValueMask { max: u8 },
    AddressMask,
    SceneLevelMask,
    Common,
    Led,
    ColourTemperature,
    ColourPowerFail,
    SetColourPowerFail,
    FactoryReset,
    EmergencyParams,
}

#[derive(Debug, Clone, Copy)]
struct CommandSpec {
    path: &'static str,
    display: &'static str,
    operation: u8,
    payload: PayloadKind,
}

const CORE: &[CommandSpec] = &[
    spec("ADDRESS_UNKNOWN", 2, PayloadKind::None),
    spec("BROKEN", 10, PayloadKind::None),
    spec("CHECK_FOR_UNKNOWN", 13, PayloadKind::None),
    spec("COLOUR_POWER_FAIL_PARAMS", 98, PayloadKind::ColourPowerFail),
    spec("COLOUR_TEMPERATURE", 97, PayloadKind::Short),
    spec("COLOUR_TYPE", 96, PayloadKind::Short),
    spec("COMMON_PARAMS", 17, PayloadKind::Short),
    spec("COMMON_READ_ONLY_PARAMS", 18, PayloadKind::Short),
    spec("CONFLICTING", 9, PayloadKind::None),
    spec("DISCOVER_GTIN_SERIAL", 27, PayloadKind::Short),
    spec("DISCOVER_KNOWN_FULL_INFO", 4, PayloadKind::None),
    spec("DISCOVER_KNOWN_TYPE_INFO", 3, PayloadKind::None),
    spec("DISCOVER_STATUS_INFO", 26, PayloadKind::Short),
    spec("FACTORY_RESET", 1, PayloadKind::FactoryReset),
    spec("GTIN", 21, PayloadKind::Short),
    spec("KNOWN", 7, PayloadKind::None),
    spec("KNOWN_TYPE_INFO", 16, PayloadKind::Short),
    spec("LED_PARAMS", 25, PayloadKind::Short),
    spec("MISSING", 11, PayloadKind::None),
    spec("REASSIGN_ONE", 6, PayloadKind::Reassign),
    spec("RECALL_MAX", 65, PayloadKind::OptionalAddress),
    spec("RECALL_MAX_MANY", 64, PayloadKind::Mask64),
    spec("RECALL_MIN", 70, PayloadKind::OptionalAddress),
    spec("RECALL_OFF", 67, PayloadKind::OptionalAddress),
    spec("RECALL_OFF_MANY", 66, PayloadKind::Mask64),
    spec("REMOVE_GROUP_MANY", 53, PayloadKind::ValueMask { max: 15 }),
    spec("REMOVE_MANY", 8, PayloadKind::Mask64),
    spec("REPLACE_BAD", 12, PayloadKind::PairShort),
    spec("RESCAN", 14, PayloadKind::None),
    spec("SCENE_VALUES_HIGH", 20, PayloadKind::Short),
    spec("SCENE_VALUES_LOW", 19, PayloadKind::Short),
    spec("SERIAL", 22, PayloadKind::Short),
    spec(
        "SET_COLOUR_POWER_FAIL_PARAMS",
        100,
        PayloadKind::SetColourPowerFail,
    ),
    spec("SET_COLOUR_TEMPERATURE", 99, PayloadKind::ColourTemperature),
    spec("SET_COMMON_PARAMS", 32, PayloadKind::Common),
    spec("SET_FAILURE_MANY", 51, PayloadKind::ValueMask { max: 255 }),
    spec("SET_GROUP_MANY", 52, PayloadKind::ValueMask { max: 15 }),
    spec("SET_LED_PARAMS", 40, PayloadKind::Led),
    spec("SET_MAX_MANY", 49, PayloadKind::ValueMask { max: 255 }),
    spec("SET_MIN_MANY", 48, PayloadKind::ValueMask { max: 255 }),
    spec("SET_RECOVERY_MANY", 50, PayloadKind::ValueMask { max: 255 }),
    spec("SET_SCENE_LEVEL_MANY", 54, PayloadKind::SceneLevelMask),
    spec("SET_SCENE_VALUES_HIGH", 35, PayloadKind::AddressMask),
    spec("SET_SCENE_VALUES_LOW", 34, PayloadKind::AddressMask),
    spec("SWAP_TWO", 5, PayloadKind::PairShort),
    spec("TRIGGER_SCENE", 71, PayloadKind::TriggerScene),
    spec("WINK_ECG_OFF", 69, PayloadKind::None),
    spec("WINK_ECG_ON", 68, PayloadKind::Wink),
];

const EMERGENCY: &[CommandSpec] = &[
    emergency(
        "INHIBIT",
        "EMERGENCY_INHIBIT",
        84,
        PayloadKind::OptionalAddress,
    ),
    emergency("PARAMS", "EMERGENCY_PARAMS", 23, PayloadKind::Short),
    emergency(
        "RELIGHT",
        "EMERGENCY_RELIGHT",
        85,
        PayloadKind::OptionalAddress,
    ),
    // The retained command enum calls the public REST operation RESET.
    emergency("REST", "EMERGENCY_RESET", 83, PayloadKind::OptionalAddress),
    emergency(
        "SET_LEVEL_MANY",
        "SET_EMERGENCY_LEVEL_MANY",
        55,
        PayloadKind::ValueMask { max: 255 },
    ),
    emergency(
        "SET_PARAMS",
        "SET_EMERGENCY_PARAMS",
        38,
        PayloadKind::EmergencyParams,
    ),
    emergency(
        "SET_PROLONG_MANY",
        "SET_EMERGENCY_PROLONG_MANY",
        56,
        PayloadKind::ValueMask { max: 255 },
    ),
    emergency(
        "SET_TEST_TIMEOUT_MANY",
        "SET_EMERGENCY_TEST_TIMEOUT_MANY",
        57,
        PayloadKind::ValueMask { max: 255 },
    ),
    emergency(
        "START_DURATION_TEST",
        "EMERGENCY_START_DURATION_TEST",
        81,
        PayloadKind::OptionalAddress,
    ),
    emergency(
        "START_FUNCTION_TEST",
        "EMERGENCY_START_FUNCTION_TEST",
        80,
        PayloadKind::OptionalAddress,
    ),
    emergency("STATUS", "EMERGENCY_STATUS", 24, PayloadKind::Short),
    emergency(
        "STOP_TEST",
        "EMERGENCY_STOP_TEST",
        82,
        PayloadKind::OptionalAddress,
    ),
    emergency(
        "TEST_STATUS",
        "EMERGENCY_TEST_STATUS",
        87,
        PayloadKind::Short,
    ),
    emergency(
        "UPDATE_TEST_STATUS",
        "EMERGENCY_UPDATE_TEST_STATUS",
        86,
        PayloadKind::Short,
    ),
];

const fn spec(path: &'static str, operation: u8, payload: PayloadKind) -> CommandSpec {
    CommandSpec {
        path,
        display: path,
        operation,
        payload,
    }
}

const fn emergency(
    path: &'static str,
    display: &'static str,
    operation: u8,
    payload: PayloadKind,
) -> CommandSpec {
    CommandSpec {
        path,
        display,
        operation,
        payload,
    }
}

#[derive(Deserialize)]
struct HelpFixture {
    paths: BTreeMap<String, Vec<String>>,
}

fn help_rows() -> &'static BTreeMap<String, Vec<String>> {
    static HELP: OnceLock<BTreeMap<String, Vec<String>>> = OnceLock::new();
    HELP.get_or_init(|| {
        serde_json::from_str::<HelpFixture>(include_str!(
            "../../../testdata/fixtures/native_cgate_dali_help.json"
        ))
        .expect("committed native DALI help fixture must parse")
        .paths
    })
}

pub(super) fn help(tag: &str, path_words: &[String]) -> Option<Response> {
    let path = path_words.join(" ");
    let rows = help_rows().get(&path)?.clone();
    Some(help_response(tag, rows))
}

fn help_response(tag: &str, mut rows: Vec<String>) -> Response {
    let final_text = rows
        .pop()
        .expect("native DALI help entries always contain a final row");
    Response {
        tag: tag.to_string(),
        lines: rows
            .into_iter()
            .map(|row| row.strip_prefix("101-").unwrap_or(&row).to_string())
            .collect(),
        final_text,
        status: 101,
    }
}

impl Service {
    pub(super) async fn dali(
        &self,
        tag: &str,
        body: &str,
        words: &[&str],
        upper: &[String],
    ) -> Response {
        if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
            return dali_root_help(tag);
        }

        let (spec, argument_start) = if upper.get(1).is_some_and(|word| word == "EMERGENCY") {
            if words.len() == 2 || (words.len() == 3 && words[2] == "?") {
                return help(tag, &["DALI".to_string(), "EMERGENCY".to_string()])
                    .expect("emergency help is committed");
            }
            let Some(name) = upper.get(2) else {
                return err(tag, 400, "400 Syntax Error: Invalid number of parameters");
            };
            let Some(spec) = EMERGENCY.iter().find(|spec| spec.path == name) else {
                return known_or_unknown(tag, upper);
            };
            (*spec, 3)
        } else {
            let Some(name) = upper.get(1) else {
                return err(tag, 400, "400 Syntax Error: Invalid number of parameters");
            };
            if is_group(name) {
                if words.len() == 2 || (words.len() == 3 && words[2] == "?") {
                    return help(tag, &["DALI".to_string(), name.clone()])
                        .expect("DALI group help is committed");
                }
                return self.dali_specialized(tag, body, upper).await;
            }
            let Some(spec) = CORE.iter().find(|spec| spec.path == name) else {
                return known_or_unknown(tag, upper);
            };
            (*spec, 2)
        };

        let args = &words[argument_start..];
        let Some(parsed) = parse_invocation(tag, spec, args) else {
            return err(tag, 400, "400 Syntax Error: Invalid number of parameters");
        };
        let parsed = match parsed {
            Ok(parsed) => parsed,
            Err(response) => return response,
        };
        // C-Gate 3.4 advertises STATUS but its retained builder never supplies
        // the mandatory status selector. It therefore fails before I/O. Keep
        // that observable boundary instead of inventing a selector value.
        if parsed.mode == DaliCalMode::Status {
            return err(tag, 400, "400 dali cal status must be set");
        }
        let (unit, serial) = match self.dali_gateway(tag, parsed.target).await {
            Ok(target) => target,
            Err(response) => return response,
        };
        let payload = if matches!(parsed.mode, DaliCalMode::Auto | DaliCalMode::Execute) {
            match build_payload(tag, spec.payload, parsed.payload, serial.as_deref()) {
                Ok(payload) => payload,
                Err(response) => return response,
            }
        } else {
            Vec::new()
        };
        let operation = parsed.line.operation(DEVICE_TYPE_DALI, spec.operation);
        let (generation, pci) = self.current_pci_epoch().await;
        let result = pci
            .dali_command(unit, parsed.mode, DEVICE_TYPE_DALI, operation, &payload)
            .await;
        let result = match result {
            Ok(result) => result,
            Err(error) => return err(tag, 502, &format!("502 DALI command failed: {error}")),
        };
        let Some(_commit_guard) = self.pci_commit_guard(generation, &pci).await else {
            return err(
                tag,
                502,
                "502 PCI connection changed during DALI command; outcome is uncertain",
            );
        };
        response(tag, spec, parsed.line, &payload, result)
    }

    pub(super) async fn dali_gateway(
        &self,
        tag: &str,
        target: &str,
    ) -> Result<(u8, Option<String>), Response> {
        let model = self.model.lock().await;
        let project = model.projects.get(&self.project);
        let network = project.and_then(|project| project.networks.get(&self.network));
        let unit = if let Some(oid) = target.strip_prefix('!') {
            network.and_then(|network| network.units.values().find(|unit| unit.oid == oid))
        } else {
            Server::split_unit(target)
                .filter(|(project, network, _)| {
                    project == &self.project && *network == self.network
                })
                .and_then(|(_, _, address)| network.and_then(|network| network.units.get(&address)))
        };
        let Some(unit) = unit.filter(|unit| unit.unit_type.eq_ignore_ascii_case("SYS_DAL2")) else {
            return Err(err(
                tag,
                401,
                &format!("401 Bad object or device ID: {target} (Unit not found)"),
            ));
        };
        Ok((
            unit.address,
            (!unit.serial.is_empty()).then(|| unit.serial.clone()),
        ))
    }
}

fn known_or_unknown(tag: &str, upper: &[String]) -> Response {
    let path = upper.iter().take(3).cloned().collect::<Vec<_>>().join(" ");
    if help_rows().contains_key(&path) {
        err(
            tag,
            502,
            "502 Command requires a physical backend that is not implemented",
        )
    } else {
        err(tag, 400, "400 Syntax Error: SubCommand not found")
    }
}

fn is_group(value: &str) -> bool {
    matches!(
        value,
        "CATALOG" | "GATEWAY" | "ERROR_REPORTING" | "MEASUREMENT" | "SESSION"
    )
}

fn dali_root_help(tag: &str) -> Response {
    let rows = [
        "101-Help: DALI commands:",
        "101-Help:  DALI ? Help for these commands",
        "101-Help:  DALI CATALOG - DALI catalogue commands",
        "101-Help:  DALI EMERGENCY - DALI emergency commands",
        "101-Help:  DALI ERROR_REPORTING - DALI error reporting commands",
        "101-Help:  DALI GATEWAY - DALI gateway commands",
        "101-Help:  DALI MEASUREMENT - DALI measurement commands",
        "101 Help:  DALI SESSION - DALI commissioning session commands",
    ];
    help_response(tag, rows.into_iter().map(str::to_string).collect())
}

struct ParsedInvocation<'a> {
    mode: DaliCalMode,
    target: &'a str,
    line: DaliLine,
    payload: &'a [&'a str],
}

fn parse_invocation<'a>(
    tag: &str,
    _spec: CommandSpec,
    args: &'a [&'a str],
) -> Option<Result<ParsedInvocation<'a>, Response>> {
    let mut index = 0usize;
    let mode = match args.first().copied() {
        Some(value) if value.eq_ignore_ascii_case("AUTO") => {
            index += 1;
            DaliCalMode::Auto
        }
        Some(value) if DaliCalMode::parse(value).is_some() => {
            index += 1;
            DaliCalMode::parse(value).expect("guard established parsed DALI mode")
        }
        _ => DaliCalMode::Auto,
    };
    let target = args.get(index).copied()?;
    let line_text = args.get(index + 1).copied()?;
    let line = match DaliLine::parse(line_text) {
        Ok(line) => line,
        Err(_) => {
            return Some(Err(err(
                tag,
                400,
                &format!("400 Syntax Error: Invalid parameter <line>: {line_text}"),
            )))
        }
    };
    let payload = &args[index + 2..];
    if !matches!(mode, DaliCalMode::Auto | DaliCalMode::Execute) && !payload.is_empty() {
        return Some(Err(err(tag, 400, "400 Syntax Error: Too many parameters")));
    }
    Some(Ok(ParsedInvocation {
        mode,
        target,
        line,
        payload,
    }))
}

fn build_payload(
    tag: &str,
    kind: PayloadKind,
    args: &[&str],
    serial: Option<&str>,
) -> Result<Vec<u8>, Response> {
    let exact = |count: usize| {
        if args.len() == count {
            Ok(())
        } else {
            Err(err(
                tag,
                400,
                "400 Syntax Error: Invalid number of parameters",
            ))
        }
    };
    match kind {
        PayloadKind::None => {
            exact(0)?;
            Ok(Vec::new())
        }
        PayloadKind::Short => {
            exact(1)?;
            Ok(vec![integer(tag, args[0], "<ecg-address>", 0, 63)? as u8])
        }
        PayloadKind::OptionalAddress => {
            if args.len() > 1 {
                return Err(err(tag, 400, "400 Syntax Error: Too many parameters"));
            }
            Ok(vec![address(
                tag,
                args.first().copied().unwrap_or("80"),
                false,
            )?])
        }
        PayloadKind::Mask64 => {
            exact(1)?;
            mask(tag, args[0], 8)
        }
        PayloadKind::PairShort => {
            exact(2)?;
            Ok(vec![
                integer(tag, args[0], "<ecg-address-1>", 0, 63)? as u8,
                integer(tag, args[1], "<ecg-address-2>", 0, 63)? as u8,
            ])
        }
        PayloadKind::Reassign => {
            exact(2)?;
            let new = integer(tag, args[1], "<ecg-address-new>", 0, 255)?;
            if new > 63 && new != 255 {
                return Err(invalid(tag, "<ecg-address-new>", args[1]));
            }
            Ok(vec![
                integer(tag, args[0], "<ecg-address-existing>", 0, 63)? as u8,
                new as u8,
            ])
        }
        PayloadKind::Wink => {
            if args.len() > 2 {
                return Err(err(tag, 400, "400 Syntax Error: Too many parameters"));
            }
            Ok(vec![
                address(tag, args.first().copied().unwrap_or("80"), false)?,
                integer(
                    tag,
                    args.get(1).copied().unwrap_or("255"),
                    "[timeout]",
                    0,
                    255,
                )? as u8,
            ])
        }
        PayloadKind::TriggerScene => {
            if args.len() > 2 {
                return Err(err(tag, 400, "400 Syntax Error: Too many parameters"));
            }
            Ok(vec![
                address(tag, args.first().copied().unwrap_or("80"), false)?,
                integer(
                    tag,
                    args.get(1).copied().unwrap_or("0"),
                    "<scene-num>",
                    0,
                    15,
                )? as u8,
            ])
        }
        PayloadKind::ValueMask { max } => {
            exact(2)?;
            let mut out = vec![integer(tag, args[0], "<value>", 0, u32::from(max))? as u8];
            out.extend(mask(tag, args[1], 8)?);
            Ok(out)
        }
        PayloadKind::AddressMask => {
            exact(2)?;
            let mut out = vec![address(tag, args[0], false)?];
            out.extend(mask(tag, args[1], 8)?);
            Ok(out)
        }
        PayloadKind::SceneLevelMask => {
            exact(3)?;
            let mut out = vec![
                integer(tag, args[0], "<scene-num>", 0, 15)? as u8,
                integer(tag, args[1], "<scene-level>", 0, 255)? as u8,
            ];
            out.extend(mask(tag, args[2], 8)?);
            Ok(out)
        }
        PayloadKind::Common => {
            exact(6)?;
            let mut out = vec![integer(tag, args[0], "<ecg-address>", 0, 63)? as u8];
            out.extend(mask(tag, args[1], 2)?);
            for (value, name) in args[2..].iter().zip(["<min>", "<max>", "<rec>", "<fail>"]) {
                out.push(integer(tag, value, name, 0, 255)? as u8);
            }
            Ok(out)
        }
        PayloadKind::Led => {
            exact(2)?;
            Ok(vec![
                integer(tag, args[0], "<ecg-address>", 0, 63)? as u8,
                integer(tag, args[1], "<dimm-curve>", 0, 1)? as u8,
            ])
        }
        PayloadKind::ColourTemperature => {
            exact(3)?;
            let coolest = integer(tag, args[1], "<coolest-short>", 0, 65535)? as u16;
            let warmest = integer(tag, args[2], "<warmest-short>", 0, 65535)? as u16;
            let mut out = vec![integer(tag, args[0], "<ecg-address>", 0, 63)? as u8];
            out.extend_from_slice(&coolest.to_le_bytes());
            out.extend_from_slice(&warmest.to_le_bytes());
            Ok(out)
        }
        PayloadKind::ColourPowerFail => {
            exact(2)?;
            Ok(vec![
                integer(tag, args[0], "<ecg-address>", 0, 63)? as u8,
                integer(tag, args[1], "<param-type>", 0, 1)? as u8,
            ])
        }
        PayloadKind::SetColourPowerFail => {
            exact(9)?;
            let mut out = vec![
                integer(tag, args[0], "<ecg-address>", 0, 63)? as u8,
                integer(tag, args[1], "<param-type>", 0, 1)? as u8,
                integer(tag, args[2], "<colour-type>", 0, 3)? as u8,
            ];
            for (index, value) in args[3..].iter().enumerate() {
                out.push(integer(tag, value, &format!("<param-{}>", index + 1), 0, 255)? as u8);
            }
            Ok(out)
        }
        PayloadKind::FactoryReset => {
            if args.len() > 1 {
                return Err(err(tag, 400, "400 Syntax Error: Too many parameters"));
            }
            let selected = serial
                .ok_or_else(|| err(tag, 408, "408 DALI gateway serial number is unavailable"))
                .and_then(|serial| {
                    parse_native_serial(serial)
                        .map_err(|_| err(tag, 408, "408 DALI gateway serial number is invalid"))
                })?;
            if !selected.known {
                return Err(err(tag, 408, "408 DALI gateway serial number is unknown"));
            }
            let mut out = vec![address(tag, args.first().copied().unwrap_or("80"), false)?];
            out.extend(selected.packed.into_iter().rev());
            Ok(out)
        }
        PayloadKind::EmergencyParams => {
            exact(4)?;
            Ok(vec![
                integer(tag, args[0], "<ecg-address>", 0, 63)? as u8,
                integer(tag, args[1], "<emerg-level>", 0, 255)? as u8,
                integer(tag, args[2], "<prolong-time>", 0, 255)? as u8,
                integer(tag, args[3], "<timeout>", 0, 255)? as u8,
            ])
        }
    }
}

fn mask(tag: &str, value: &str, bytes: usize) -> Result<Vec<u8>, Response> {
    parse_mask(value, bytes).map_err(|_| invalid(tag, "<bitmask>", value))
}

fn address(tag: &str, value: &str, allow_unassigned: bool) -> Result<u8, Response> {
    let value_num = integer(tag, value, "<ecg-address>", 0, 255)?;
    if value_num <= 80 || (allow_unassigned && value_num == 255) {
        Ok(value_num as u8)
    } else {
        Err(invalid(tag, "<ecg-address>", value))
    }
}

fn integer(tag: &str, value: &str, name: &str, min: u32, max: u32) -> Result<u32, Response> {
    let parsed = value
        .strip_prefix('$')
        .map_or_else(|| value.parse::<u32>(), |hex| u32::from_str_radix(hex, 16));
    match parsed {
        Ok(parsed) if (min..=max).contains(&parsed) => Ok(parsed),
        _ => Err(invalid(tag, name, value)),
    }
}

fn invalid(tag: &str, name: &str, value: &str) -> Response {
    err(
        tag,
        400,
        &format!("400 Syntax Error: Invalid parameter {name}: {value}"),
    )
}

fn response(
    tag: &str,
    spec: CommandSpec,
    line: DaliLine,
    payload: &[u8],
    result: cbus_transport::pci::DaliCommandResult,
) -> Response {
    let mut rows = Vec::new();
    for (index, exchange) in result.exchanges.iter().enumerate() {
        if index != 0 {
            rows.push(format!("120-=========== #{index} =============="));
        }
        rows.push(format!(
            "120-DaliCommand={}: ${:02X} ({})",
            spec.display,
            if line == DaliLine::A {
                spec.operation
            } else {
                spec.operation | 0x80
            },
            exchange.mode.name()
        ));
        rows.push(format!("120-Line={}", line.name()));
        rows.push(format!(
            "120-Payload=${}",
            hex::encode_upper(if exchange.mode == DaliCalMode::Execute {
                payload
            } else {
                &[]
            })
        ));
        rows.push(format!("100-SendCommand={}", exchange.request_wire));
        rows.push(format!(
            "300-Response={}",
            hex::encode_upper(&exchange.response_wire)
        ));
        rows.push(format!(
            "320-ResponseStatus={}",
            status_name(exchange.status)
        ));
        rows.push(format!(
            "320-ResponsePayload={}",
            if exchange.nak {
                "null".to_string()
            } else {
                hex::encode_upper(&exchange.data)
            }
        ));
    }
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text: "200 OK.".to_string(),
        status: 200,
    }
}

fn status_name(status: u8) -> &'static str {
    match status {
        0 => "SUCCESS",
        1 => "IN_PROGRESS",
        2 => "FAIL_BUSY",
        3 => "FAIL_INVALID_COMMAND",
        4 => "FAIL_INVALID_PARAMETER",
        5 => "FAIL_INCORRECT_LENGTH",
        6 => "FAIL_INVALID_DEVICE_TYPE",
        _ => "FAIL_CATASTROPHE",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    fn fixture() -> String {
        include_str!("../../../testdata/fixtures/project.xml").replace(
            "</Network>",
            r#"<Unit oid="dali-gateway-20"><Address>20</Address><TagName>DALI Gateway</TagName><UnitType>SYS_DAL2</UnitType><FirmwareVersion>1.10.0</FirmwareVersion><SerialNumber>101136.1558</SerialNumber></Unit></Network>"#,
        )
    }

    fn state_path() -> PathBuf {
        static ID: AtomicU64 = AtomicU64::new(0);
        std::env::temp_dir().join(format!(
            "cmqttd-dali-service-{}-{}.json",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ))
    }

    async fn setup() -> (Arc<Service>, BufReader<tokio::io::DuplexStream>, PathBuf) {
        let (client, remote) = tokio::io::duplex(8192);
        let (reader, writer) = tokio::io::split(client);
        let (events, _) = tokio::sync::mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(reader), Box::new(writer), events);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut init = Vec::new();
            remote.read_until(b'\r', &mut init).await.unwrap();
        }
        let path = state_path();
        let service = Service::new(&fixture(), None, path.clone(), pci, None).unwrap();
        (service, remote, path)
    }

    async fn line(remote: &mut BufReader<tokio::io::DuplexStream>) -> Vec<u8> {
        let mut bytes = Vec::new();
        remote.read_until(b'\r', &mut bytes).await.unwrap();
        bytes
    }

    async fn direct_reply(
        remote: &mut BufReader<tokio::io::DuplexStream>,
        source: u8,
        cal: &[u8],
    ) -> String {
        let mut bytes = vec![0x86, source, 0x10, 0x00];
        bytes.extend(cal);
        let sum = bytes.iter().fold(0u8, |acc, byte| acc.wrapping_add(*byte));
        bytes.push(0u8.wrapping_sub(sum));
        let encoded = hex::encode_upper(&bytes);
        remote
            .get_mut()
            .write_all(format!("{encoded}\r\n").as_bytes())
            .await
            .unwrap();
        encoded
    }

    #[test]
    fn every_implemented_path_has_native_help_evidence() {
        for spec in CORE {
            assert!(help_rows().contains_key(&format!("DALI {}", spec.path)));
        }
        for spec in EMERGENCY {
            assert!(help_rows().contains_key(&format!("DALI EMERGENCY {}", spec.path)));
        }
        assert_eq!(CORE.len(), 48);
        assert_eq!(EMERGENCY.len(), 14);
    }

    #[test]
    fn payloads_pin_native_byte_order() {
        assert_eq!(
            build_payload(
                "",
                PayloadKind::ColourTemperature,
                &["3", "3000", "6500"],
                None
            )
            .unwrap(),
            [3, 0xb8, 0x0b, 0x64, 0x19]
        );
        assert_eq!(
            build_payload(
                "",
                PayloadKind::Common,
                &["3", "0102", "1", "254", "255", "0"],
                None
            )
            .unwrap(),
            [3, 1, 2, 1, 254, 255, 0]
        );
        assert_eq!(
            build_payload("", PayloadKind::FactoryReset, &[], Some("101136.1558")).unwrap(),
            [80, 0x16, 0x06, 0xb1, 0x18]
        );
    }

    #[test]
    fn auth_boundary_is_mutation_and_mode_aware() {
        let words = |text: &str| {
            text.split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>()
        };
        assert!(dali_requires_programming_auth(&words(
            "DALI FACTORY_RESET //HARNESS/254/p/20 A"
        )));
        assert!(!dali_requires_programming_auth(&words(
            "DALI FACTORY_RESET POLL //HARNESS/254/p/20 A"
        )));
        assert!(!dali_requires_programming_auth(&words(
            "DALI KNOWN EXEC //HARNESS/254/p/20 A"
        )));
        assert!(dali_requires_programming_auth(&words(
            "DALI EMERGENCY INHIBIT EXEC //HARNESS/254/p/20 A"
        )));
    }

    #[tokio::test(start_paused = true)]
    async fn service_emits_native_execute_envelope_and_exact_wire() {
        let (service, mut remote, path) = setup().await;
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[d] DALI KNOWN EXEC //HARNESS/254/p/20 B",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E381DA87\r");
        let response_wire =
            direct_reply(&mut remote, 20, &[0xe6, 0x83, 0xda, 0x87, 0, 0xaa, 0x55]).await;
        let response = request.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response.lines,
            [
                "120-DaliCommand=KNOWN: $87 (EXECUTE)".to_string(),
                "120-Line=B".to_string(),
                "120-Payload=$".to_string(),
                "100-SendCommand=\\061400E381DA87".to_string(),
                format!("300-Response={response_wire}"),
                "320-ResponseStatus=SUCCESS".to_string(),
                "320-ResponsePayload=AA55".to_string(),
            ]
        );
        assert_eq!(response.final_text, "200 OK.");
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn service_preserves_emergency_enum_name_nak_and_pre_io_failures() {
        let (service, mut remote, path) = setup().await;
        let emergency = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[e] DALI EMERGENCY REST EXEC !dali-gateway-20 A",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut remote).await, b"\\061400E481DA5350\r");
        let response_wire = direct_reply(&mut remote, 20, &[0x3b, 0, 0x53, 2]).await;
        let response = emergency.await.unwrap();
        assert_eq!(response.status, 200, "{response:?}");
        assert_eq!(
            response.lines[0],
            "120-DaliCommand=EMERGENCY_RESET: $53 (EXECUTE)"
        );
        assert!(response
            .lines
            .contains(&format!("300-Response={response_wire}")));
        assert!(response
            .lines
            .contains(&"320-ResponseStatus=FAIL_CATASTROPHE".to_string()));
        assert!(response
            .lines
            .contains(&"320-ResponsePayload=null".to_string()));

        let before = remote.buffer().len();
        let status = service
            .handle(
                &mut ClientState::default(),
                "[s] DALI KNOWN STATUS //HARNESS/254/p/20 A",
            )
            .await;
        assert_eq!(status.final_text, "400 dali cal status must be set");
        let invalid = service
            .handle(
                &mut ClientState::default(),
                "[i] DALI KNOWN EXEC //HARNESS/254/p/20 C",
            )
            .await;
        assert_eq!(invalid.status, 400);
        assert_eq!(
            remote.buffer().len(),
            before,
            "pre-I/O failures wrote bytes"
        );
        std::fs::remove_file(path).unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn reconnect_generation_makes_completed_old_write_uncertain_without_replay() {
        let (service, mut old_remote, path) = setup().await;
        let request = tokio::spawn({
            let service = service.clone();
            async move {
                service
                    .handle(
                        &mut ClientState::default(),
                        "[g] DALI KNOWN EXEC //HARNESS/254/p/20 A",
                    )
                    .await
            }
        });
        assert_eq!(line(&mut old_remote).await, b"\\061400E381DA07\r");

        let (replacement_stream, replacement_remote) = tokio::io::duplex(8192);
        let (reader, writer) = tokio::io::split(replacement_stream);
        let (events, _) = tokio::sync::mpsc::unbounded_channel();
        let replacement = PciClient::new(Box::new(reader), Box::new(writer), events);
        service.set_pci(replacement).await;
        direct_reply(&mut old_remote, 20, &[0xe4, 0x83, 0xda, 7, 0]).await;

        let response = request.await.unwrap();
        assert_eq!(response.status, 502, "{response:?}");
        assert_eq!(
            response.final_text,
            "502 PCI connection changed during DALI command; outcome is uncertain"
        );
        let mut replacement_remote = BufReader::new(replacement_remote);
        assert!(
            tokio::time::timeout(Duration::from_millis(1), line(&mut replacement_remote))
                .await
                .is_err()
        );
        std::fs::remove_file(path).unwrap();
    }
}
