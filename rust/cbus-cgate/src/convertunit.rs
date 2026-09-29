//! Native C-Gate 3.4 `CONVERTUNIT` database parameter mapping.
//!
//! Admission follows the fixed source-to-target table in C-Gate class `dg`.
//! A converted unit is rebuilt in target specification order: the first
//! `ConvertUnitMappingTable.xml` pair for a target name runs its rules when the
//! source has stored PP values, otherwise the same-named source value is
//! copied, otherwise the target session default is used. Empty results are
//! omitted. The operator supplies the private mapping table beside the decoded
//! unit specifications; cmqttd never bundles it.

use std::path::Path;

use crate::unitspec::{self, SpecParam};

/// Mapping-table filename inside the configured specification directory.
pub const MAPPING_TABLE: &str = "ConvertUnitMappingTable.xml";
/// Serial number written by a catalogue (mode 1) conversion.
pub const CATALOG_SERIAL_NUMBER: &str = "00000000.0000";

const COMPATIBLE: &[(&str, &[&str])] = &[
    (
        "DIMDU4",
        &["DIMDN8", "DIMDN8F", "DIMDN4", "DIMDN4F", "DIMDD4"],
    ),
    ("DIMDN4F", &["DIMDU4"]),
    ("DIMDN4", &["DIMDU4", "DIMDN8", "DIMDD4"]),
    ("DIMDN8F", &["DIMDU4"]),
    ("DIMDN8", &["DIMDU4", "DIMDD8"]),
    ("RELDN4", &["RELDN4A"]),
    ("RELDN8", &["RELDN8A"]),
    ("RELDN12", &["RELDN16A"]),
];

const RULES: &[&str] = &[
    "extractByte",
    "oneBitToThreeBitAndInverse",
    "mapToIndex",
    "mapThreeParamToOne",
    "channelProperties",
    "setDefaultValue",
    "resetToZero",
    "mapTo2Byte",
    "changePropertyName",
    "convertDimChannelProfileSelection",
    "convertDimChProfileData",
    "convertErrorReportInterval",
    "mapInterlockMask",
    "mapInterlockPriority",
    "mapRestrikeDelay",
    "mapTurnOnThreshold",
    "toggleGlobalParam",
];

/// Native `dg` admission: identity, or a listed target. The source key is
/// matched case-insensitively and target membership case-sensitively.
pub fn compatible(source: &str, target: &str) -> bool {
    if source.eq_ignore_ascii_case(target) {
        return true;
    }
    COMPATIBLE
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(source))
        .is_some_and(|(_, targets)| targets.contains(&target))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rule {
    pub name: String,
    pub param1: Option<String>,
    pub param2: Option<String>,
    pub param3: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pair {
    pub new: String,
    pub old: Vec<String>,
    pub rules: Vec<Rule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Conversion {
    pub old_type: String,
    pub new_type: String,
    pub pairs: Vec<Pair>,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct MappingTable {
    pub conversions: Vec<Conversion>,
}

impl MappingTable {
    /// Load the private table from the configured specification directory.
    pub fn load(dir: &Path) -> Result<Self, String> {
        let text = unitspec::read_xml_file(dir, MAPPING_TABLE)?;
        Self::parse(&text)
    }

    pub fn parse(text: &str) -> Result<Self, String> {
        let document = roxmltree::Document::parse(text)
            .map_err(|error| format!("Malformed mapping table: {error}"))?;
        let root = document.root_element();
        if root.tag_name().name() != "UnitConversions" {
            return Err("Expected a UnitConversions mapping table".to_string());
        }
        let mut conversions = Vec::new();
        for element in root
            .children()
            .filter(|node| node.has_tag_name("UnitConversion"))
        {
            let text_of = |name: &str| {
                element
                    .children()
                    .find(|node| node.has_tag_name(name))
                    .and_then(|node| node.text())
                    .map(str::trim)
                    .unwrap_or("")
                    .to_string()
            };
            let (old_type, new_type) = (text_of("Unit_type_Old"), text_of("Unit_type_New"));
            if old_type.is_empty() || new_type.is_empty() {
                return Err("Each UnitConversion requires old and new unit types".to_string());
            }
            let mut pairs = Vec::new();
            for pair in element
                .children()
                .filter(|node| node.has_tag_name("Parameters"))
                .flat_map(|node| node.children().filter(|child| child.has_tag_name("Pair")))
            {
                let (Some(new), Some(old)) = (pair.attribute("new"), pair.attribute("old")) else {
                    return Err("Each Pair requires new and old attributes".to_string());
                };
                let mut rules = Vec::new();
                for rule in pair
                    .children()
                    .filter(|node| node.has_tag_name("rules"))
                    .flat_map(|node| node.children().filter(|child| child.has_tag_name("rule")))
                {
                    let name = rule.text().unwrap_or("").trim();
                    if !RULES.contains(&name) {
                        return Err(format!("Unsupported conversion rule {name:?}"));
                    }
                    rules.push(Rule {
                        name: name.to_string(),
                        param1: rule.attribute("param1").map(str::to_string),
                        param2: rule.attribute("param2").map(str::to_string),
                        param3: rule.attribute("param3").map(str::to_string),
                    });
                }
                pairs.push(Pair {
                    new: new.to_string(),
                    old: old.split(',').map(str::to_string).collect(),
                    rules,
                });
            }
            conversions.push(Conversion {
                old_type,
                new_type,
                pairs,
            });
        }
        Ok(Self { conversions })
    }

    /// First matching entry; native C-Gate ignores later duplicates.
    pub fn find(&self, source: &str, target: &str) -> Option<&Conversion> {
        self.conversions.iter().find(|conversion| {
            conversion.old_type.eq_ignore_ascii_case(source)
                && conversion.new_type.eq_ignore_ascii_case(target)
        })
    }
}

/// Java `String.split(" ")`: leading empties stay, trailing empties go.
fn split(value: &str) -> Vec<String> {
    if value.is_empty() {
        return vec![String::new()];
    }
    let mut parts = value.split(' ').map(str::to_string).collect::<Vec<_>>();
    while parts.last().is_some_and(String::is_empty) {
        parts.pop();
    }
    parts
}

/// Java `Integer.parseInt(value, radix)`.
fn parse_int(value: Option<&str>, radix: u32) -> Result<i64, String> {
    let text = value.ok_or("Missing rule parameter")?;
    let digits = text.strip_prefix(['+', '-']).unwrap_or(text);
    if digits.is_empty() || !digits.chars().all(|c| c.is_digit(radix)) {
        return Err(format!(
            "Rule parameter {text:?} is not a base-{radix} integer"
        ));
    }
    i64::from_str_radix(text, radix).map_err(|error| error.to_string())
}

fn index(value: Option<&str>) -> Result<usize, String> {
    usize::try_from(parse_int(value, 10)?).map_err(|_| "Negative rule index".to_string())
}

/// Java `Integer.decode` for the decimal, hex and octal forms.
fn decode(value: &str) -> Option<i64> {
    let (sign, text) = match value.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, value.strip_prefix('+').unwrap_or(value)),
    };
    let (radix, digits) = if let Some(hex) = text
        .strip_prefix("0x")
        .or_else(|| text.strip_prefix("0X"))
        .or_else(|| text.strip_prefix('#'))
    {
        (16, hex)
    } else if text.len() > 1 && text.starts_with('0') {
        (8, &text[1..])
    } else {
        (10, text)
    };
    if digits.is_empty() || !digits.chars().all(|c| c.is_digit(radix)) {
        return None;
    }
    i64::from_str_radix(digits, radix).ok().map(|n| sign * n)
}

/// Java `Integer.toHexString`.
fn hex(number: i64) -> String {
    format!("{:x}", (number as i32) as u32)
}

fn convert_to_hex(text: &str) -> String {
    match text.len() {
        2 => format!("0x{text} 0x0"),
        n if n >= 3 => format!("0x{} 0x{}", &text[n - 2..], &text[..n - 2]),
        _ => text.to_string(),
    }
}

fn hex_to_int(text: &str) -> Result<i64, String> {
    match text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
        Some(digits) => parse_int(Some(digits), 16),
        None => Ok(0),
    }
}

fn at(values: &[String], position: usize) -> Result<&String, String> {
    values
        .get(position)
        .ok_or_else(|| "Rule index is outside the stored value".to_string())
}

fn first(old: &[String]) -> Vec<String> {
    old.first().map(|value| split(value)).unwrap_or_default()
}

fn source_value<'a>(name: &str, source: &'a [(String, String)]) -> Option<&'a str> {
    source
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .map(|(_, value)| value.as_str())
}

/// Execute one `ConvertUnitRulesUtility` method.
fn rule(
    rule: &Rule,
    old: &[String],
    baseline: &str,
    source: &[(String, String)],
) -> Result<Option<String>, String> {
    let p1 = rule.param1.as_deref();
    let p2 = rule.param2.as_deref();
    let values = first(old);
    let mut target = split(baseline);
    let join = |parts: &[String]| parts.join(" ");
    let result = match rule.name.as_str() {
        "extractByte" => match p1.ok_or("extractByte requires param1")? {
            "" => String::new(),
            raw => {
                let position = index(Some(raw))?;
                values
                    .get(position)
                    .cloned()
                    .unwrap_or_else(|| baseline.to_string())
            }
        },
        "oneBitToThreeBitAndInverse" => {
            let (p1, p2) = (
                p1.ok_or("oneBitToThreeBitAndInverse requires param1")?,
                p2.ok_or("oneBitToThreeBitAndInverse requires param2")?,
            );
            let selected = if !p1.is_empty() && !values.is_empty() {
                at(&values, index(Some(p1))?)?.clone()
            } else {
                String::new()
            };
            let bit = if selected.is_empty() {
                0
            } else {
                parse_int(selected.get(2..), 2)?
            };
            let position = if p2.is_empty() { 0 } else { index(Some(p2))? };
            let slot = target
                .get_mut(position)
                .ok_or("Rule index is outside the target value")?;
            *slot = if bit == 1 { "0" } else { "1" }.to_string();
            join(&target)
        }
        "mapToIndex" => {
            let (from, to) = (index(p1)?, index(p2)?);
            if let (Some(value), true) = (values.get(from), to < target.len()) {
                target[to] = value.clone();
            }
            join(&target)
        }
        "mapThreeParamToOne" => {
            let position = index(p1)?;
            for (slot, value) in old.iter().enumerate() {
                let parts = split(value);
                let selected = at(&parts, position)?;
                let character = selected
                    .chars()
                    .nth(2)
                    .ok_or("mapThreeParamToOne input is shorter than C-Gate requires")?;
                *target
                    .get_mut(slot)
                    .ok_or("Rule index is outside the target value")? = character.to_string();
            }
            join(&target)
        }
        "channelProperties" => {
            if values.len() > target.len() {
                join(&values[..target.len()])
            } else if values.len() < target.len() {
                let mut output = values.clone();
                output.extend_from_slice(&target[values.len()..]);
                join(&output)
            } else {
                // Native equal-length result is empty, so the PP is omitted.
                String::new()
            }
        }
        "setDefaultValue" => baseline.to_string(),
        "resetToZero" => {
            if values.len() > target.len() {
                join(&vec!["0x0".to_string(); target.len()])
            } else if values.len() < target.len() {
                let mut output = vec!["0x0".to_string(); values.len()];
                output.extend_from_slice(&target[values.len()..]);
                join(&output)
            } else {
                String::new()
            }
        }
        "mapTo2Byte" => match p1.ok_or("mapTo2Byte requires param1")? {
            "" => String::new(),
            raw => match values.get(index(Some(raw))?) {
                None => baseline.to_string(),
                Some(selected) => {
                    let digits = selected
                        .strip_prefix("0x")
                        .or_else(|| selected.strip_prefix("0X"))
                        .unwrap_or(selected);
                    let number = parse_int(Some(digits), 16)?;
                    if number >= 60 {
                        convert_to_hex(&hex((number - 60) * 10 + 60))
                    } else {
                        format!("{selected} 0x0")
                    }
                }
            },
        },
        "changePropertyName" => values
            .first()
            .cloned()
            .unwrap_or_else(|| baseline.to_string()),
        "convertDimChannelProfileSelection" => {
            if old.is_empty() {
                "0 0 0".to_string()
            } else {
                let position = index(p1)?;
                let selected = decode(at(&values, position)?).unwrap_or(0);
                if selected != 1 {
                    baseline.to_string()
                } else {
                    match position {
                        0 => "0 0 1",
                        1 => "1 0 1",
                        2 => "0 1 1",
                        3 => "1 1 1",
                        _ => "",
                    }
                    .to_string()
                }
            }
        }
        "convertDimChProfileData" => {
            let position = index(p1)?;
            let selector = source_value(p2.unwrap_or(""), source);
            let selected = match selector {
                Some(value) => at(&split(value), position)?.eq_ignore_ascii_case("0x1"),
                None => false,
            };
            if !selected {
                baseline.to_string()
            } else if !rule
                .param3
                .as_deref()
                .is_some_and(|value| value.eq_ignore_ascii_case("OldUnitValue"))
            {
                // A missing literal is a null method result, which C-Gate rejects.
                rule.param3
                    .clone()
                    .ok_or("convertDimChProfileData requires param3")?
            } else if let Some(value) = old.first() {
                let digits = value
                    .strip_prefix("0x")
                    .or_else(|| value.strip_prefix("0X"))
                    .unwrap_or(value);
                let number = parse_int(Some(digits), 16)?;
                // Java Math.round(double): floor(x + 0.5).
                let scaled = (number as f64 / 62.195 * 100.0 + 0.5).floor() as i64;
                convert_to_hex(&hex(scaled))
            } else {
                baseline.to_string()
            }
        }
        "convertErrorReportInterval" => match values.first().map(String::as_str) {
            None => baseline.to_string(),
            Some("0x1" | "0x2" | "0x3" | "0x4" | "0x5") => "0x1".to_string(),
            Some("0x6") => "0x2".to_string(),
            Some("0x7") => "0x4".to_string(),
            Some(_) => String::new(),
        },
        "mapInterlockMask" => {
            let channel = parse_int(p2, 10)?;
            match values.first() {
                None => baseline.to_string(),
                Some(value) => {
                    let count = parse_int(value.get(2..), 16)?;
                    if channel > count {
                        baseline.to_string()
                    } else {
                        match value.as_str() {
                            "0x0" => "0x0 0x0",
                            "0x1" => "0x3 0x0",
                            "0x2" => "0x7 0x0",
                            "0x3" => "0xf 0x0",
                            "0x4" => "0x1f 0x0",
                            "0x5" => "0x3f 0x0",
                            "0x6" => "0x7f 0x0",
                            "0x7" => "0xff 0x0",
                            _ => "",
                        }
                        .to_string()
                    }
                }
            }
        }
        "mapInterlockPriority" => match values.first() {
            None => baseline.to_string(),
            Some(value) => {
                let count = parse_int(value.get(2..), 16)?;
                let (highest, channel) = (parse_int(p1, 10)?, parse_int(p2, 10)?);
                if channel > count {
                    baseline.to_string()
                } else {
                    let number = highest - count + channel;
                    let bits = format!("{:b}", (number as i32) as u32);
                    let padded = format!("{bits:0>4}");
                    padded
                        .chars()
                        .rev()
                        .map(|c| c.to_string())
                        .collect::<Vec<_>>()
                        .join(" ")
                }
            }
        },
        "mapRestrikeDelay" => {
            let delay = source_value(p2.unwrap_or(""), source);
            match p1.ok_or("mapRestrikeDelay requires param1")? {
                "" => baseline.to_string(),
                raw => {
                    let position = index(Some(raw))?;
                    match (values.get(position), delay) {
                        (Some(flag), Some(delay)) if hex_to_int(flag)? == 1 => {
                            convert_to_hex(&hex(hex_to_int(delay)? * 10))
                        }
                        _ => baseline.to_string(),
                    }
                }
            }
        }
        "mapTurnOnThreshold" => {
            if values.is_empty() {
                baseline.to_string()
            } else {
                at(&values, index(p1)?)?.clone()
            }
        }
        "toggleGlobalParam" => match values.first() {
            None => baseline.to_string(),
            Some(value) if value.eq_ignore_ascii_case("1") => "0".to_string(),
            Some(_) => "1".to_string(),
        },
        other => return Err(format!("Unsupported conversion rule {other:?}")),
    };
    Ok(Some(result))
}

/// Run a pair's rules against the same inputs; the last result wins.
pub fn apply_rules(
    rules: &[Rule],
    old: &[String],
    baseline: &str,
    source: &[(String, String)],
) -> Result<Option<String>, String> {
    let mut result = None;
    for item in rules {
        result = rule(item, old, baseline, source)?;
    }
    Ok(result)
}

fn array_size(param: &SpecParam) -> usize {
    param
        .get("ArraySize")
        .and_then(unitspec::parse_integer)
        .unwrap_or(1)
        .max(0) as usize
}

/// Native PP GET rendering of one stored value: `0x` hex integers and bit
/// digits. Values outside the specification grammar are returned unchanged.
pub fn render_value(param: &SpecParam, value: &str) -> String {
    let kind = param.get("Type").unwrap_or("").trim().to_ascii_lowercase();
    match kind.as_str() {
        "int" | "long" | "bit" => {
            let numbers = value
                .split_whitespace()
                .map(unitspec::parse_integer)
                .collect::<Option<Vec<_>>>();
            match numbers {
                Some(numbers) if !numbers.is_empty() && numbers.len() <= array_size(param) => {
                    numbers
                        .into_iter()
                        .map(|number| {
                            if kind == "bit" {
                                number.to_string()
                            } else {
                                format!("0x{}", hex(number))
                            }
                        })
                        .collect::<Vec<_>>()
                        .join(" ")
                }
                _ => value.to_string(),
            }
        }
        "sixbit" => {
            let size = array_size(param);
            format!("{:<size$}", value.to_ascii_uppercase())
        }
        _ => value.to_string(),
    }
}

/// Render stored PP strings the way native C-Gate stores them.
pub fn render_parameters(spec: &[SpecParam], values: &[(String, String)]) -> Vec<(String, String)> {
    values
        .iter()
        .map(|(name, value)| {
            let rendered = spec
                .iter()
                .find(|param| param.name == *name)
                .map(|param| render_value(param, value))
                .unwrap_or_else(|| value.clone());
            (name.clone(), rendered)
        })
        .collect()
}

/// Native PP GET rendering of a declared default, or empty when undeclared.
pub fn session_default(param: &SpecParam) -> Result<String, String> {
    let Some(default) = param.get("DefaultValue").filter(|value| !value.is_empty()) else {
        return Ok(String::new());
    };
    let kind = param.get("Type").unwrap_or("").trim().to_ascii_lowercase();
    if matches!(kind.as_str(), "int" | "long" | "bit")
        && default
            .split_whitespace()
            .any(|token| unitspec::parse_integer(token).is_none())
    {
        return Err(format!("Invalid declared default for {}", param.name));
    }
    Ok(render_value(param, default))
}

/// Predict the PP list stored on the converted unit, in target spec order.
pub fn convert_parameters(
    table: &MappingTable,
    source_type: &str,
    source: &[(String, String)],
    target: &[SpecParam],
    target_type: &str,
) -> Result<Vec<(String, String)>, String> {
    if source_type.eq_ignore_ascii_case(target_type) {
        return Ok(source.to_vec());
    }
    let pairs = table
        .find(source_type, target_type)
        .map(|conversion| conversion.pairs.as_slice())
        .unwrap_or_default();
    let mut result = Vec::new();
    for param in target {
        let baseline = session_default(param)?;
        let pair = pairs
            .iter()
            .find(|pair| pair.new.eq_ignore_ascii_case(&param.name));
        let value = match pair {
            Some(pair) if !source.is_empty() => {
                let old = pair
                    .old
                    .iter()
                    .filter_map(|name| source_value(name, source).map(str::to_string))
                    .collect::<Vec<_>>();
                apply_rules(&pair.rules, &old, &baseline, source)?
            }
            _ => Some(
                source_value(&param.name, source)
                    .filter(|value| !value.is_empty())
                    .map(str::to_string)
                    .unwrap_or(baseline),
            ),
        };
        if let Some(value) = value.filter(|value| !value.is_empty()) {
            result.push((param.name.clone(), value));
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(name: &str, p1: Option<&str>, p2: Option<&str>, p3: Option<&str>) -> Rule {
        Rule {
            name: name.to_string(),
            param1: p1.map(str::to_string),
            param2: p2.map(str::to_string),
            param3: p3.map(str::to_string),
        }
    }

    fn run(rule: Rule, old: &[&str], baseline: &str, source: &[(&str, &str)]) -> Option<String> {
        let old = old.iter().map(|v| v.to_string()).collect::<Vec<_>>();
        let source = source
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect::<Vec<_>>();
        apply_rules(&[rule], &old, baseline, &source).unwrap()
    }

    #[test]
    fn admission_matches_native_table() {
        assert!(compatible("DIMDN4", "DIMDN4"));
        assert!(compatible("dimdn4", "DIMDU4"));
        assert!(!compatible("DIMDN4", "dimdu4"));
        assert!(!compatible("DIMDD4", "DIMDN4"));
        assert!(!compatible("RELDN4A", "RELDN4"));
        let count: usize = COMPATIBLE.iter().map(|(_, targets)| targets.len()).sum();
        assert_eq!(count, 15);
    }

    #[test]
    fn length_rules_omit_equal_lengths() {
        let cp = || r("channelProperties", None, None, None);
        assert_eq!(
            run(cp(), &["0x9 0x8 0x7"], "0x1 0x2", &[]).unwrap(),
            "0x9 0x8"
        );
        assert_eq!(
            run(cp(), &["0x9"], "0x1 0x2 0x3", &[]).unwrap(),
            "0x9 0x2 0x3"
        );
        assert_eq!(run(cp(), &["0x9 0x8"], "0x1 0x2", &[]).unwrap(), "");
        let zero = || r("resetToZero", None, None, None);
        assert_eq!(
            run(zero(), &["0x9"], "0x1 0x2 0x3", &[]).unwrap(),
            "0x0 0x2 0x3"
        );
        assert_eq!(run(zero(), &["0x9 0x8"], "0x1 0x2", &[]).unwrap(), "");
    }

    #[test]
    fn numeric_rules_follow_java_rendering() {
        let two = |i| r("mapTo2Byte", Some(i), Some(""), None);
        let delays = ["0x3 0x46 0x5a 0xff"];
        assert_eq!(run(two("0"), &delays, "", &[]).unwrap(), "0x3 0x0");
        assert_eq!(run(two("1"), &delays, "", &[]).unwrap(), "0xa0 0x0");
        assert_eq!(run(two("2"), &delays, "", &[]).unwrap(), "0x68 0x1");
        assert_eq!(run(two("3"), &delays, "", &[]).unwrap(), "0xda 0x7");
        let source = [("RestrikeChannel", "0x1 0x0"), ("RestrikeDelay", "0x7")];
        let data = r(
            "convertDimChProfileData",
            Some("0"),
            Some("RestrikeChannel"),
            Some("OldUnitValue"),
        );
        assert_eq!(run(data, &["0x7"], "0x0 0x0", &source).unwrap(), "b");
        let restrike = r("mapRestrikeDelay", Some("0"), Some("RestrikeDelay"), None);
        assert_eq!(
            run(restrike, &["0x1 0x0"], "0x0 0x0", &source).unwrap(),
            "0x46 0x0"
        );
        let priority = r("mapInterlockPriority", Some("15"), Some("1"), None);
        assert_eq!(run(priority, &["0x2"], "1 1 1 1", &[]).unwrap(), "0 1 1 1");
        let mask = r("mapInterlockMask", Some(""), Some("1"), None);
        assert_eq!(run(mask, &["0x2"], "0xff 0xff", &[]).unwrap(), "0x7 0x0");
        let inverse = r("oneBitToThreeBitAndInverse", Some("0"), Some("2"), None);
        assert_eq!(run(inverse, &["0x0 0x1"], "0 0 0", &[]).unwrap(), "0 0 1");
        let three = r("mapThreeParamToOne", Some("0"), Some(""), None);
        assert_eq!(
            run(three, &["0x1 0x0", "0x0", "0x1"], "0 0 0 0", &[]).unwrap(),
            "1 0 1 0"
        );
    }

    #[test]
    fn table_rejects_unknown_rules_and_uses_first_duplicate() {
        let table = "<UnitConversions>\
            <UnitConversion><Unit_type_New>B</Unit_type_New><Unit_type_Old>A</Unit_type_Old>\
            <Parameters><Pair old=\"X\" new=\"X\"><rules><rule>setDefaultValue</rule></rules></Pair></Parameters></UnitConversion>\
            <UnitConversion><Unit_type_New>B</Unit_type_New><Unit_type_Old>A</Unit_type_Old>\
            <Parameters/></UnitConversion></UnitConversions>";
        let parsed = MappingTable::parse(table).unwrap();
        assert_eq!(parsed.find("a", "b").unwrap().pairs.len(), 1);
        assert!(MappingTable::parse(&table.replace("setDefaultValue", "executeRule")).is_err());
    }

    fn fixture() -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "cbus-cgate-convertunit-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("create fixture directory");
        let unit = |catalog: &str, kind: &str, version: &str| {
            format!(
                "<Unit><CatalogNumber>{catalog}</CatalogNumber><FirmwareRevisions><Revision>\
                 <UnitType>{kind}</UnitType><MinVersion>{version}</MinVersion>\
                 <MaxVersion>{version}</MaxVersion><UnitSpecName>{kind}.xml</UnitSpecName>\
                 <IsDefault>true</IsDefault></Revision></FirmwareRevisions></Unit>"
            )
        };
        std::fs::write(
            dir.join("cbusunits.xml"),
            format!(
                "<CBusUnits><Units>{}{}</Units></CBusUnits>",
                unit("CAT-N4", "DIMDN4", "2.7.00"),
                unit("CAT-D4", "DIMDD4", "1.3.0")
            ),
        )
        .expect("write catalogue");
        let param = |name: &str, kind: &str, size: u8, default: &str| {
            format!(
                "<Param><Name>{name}</Name><Type>{kind}</Type><Address>$10</Address>\
                 <ArraySize>{size}</ArraySize><DefaultValue>{default}</DefaultValue></Param>"
            )
        };
        let spec = |params: Vec<String>| {
            format!(
                "<UnitSpecification><Parameters>{}</Parameters></UnitSpecification>",
                params.join("")
            )
        };
        std::fs::write(
            dir.join("DIMDN4.xml"),
            spec(vec![
                param("GroupAddress", "int", 3, "$FF $FF $FF"),
                param("Toggle", "bit", 1, "1"),
                param("UnitName", "sixbit", 8, "NEWUNIT"),
            ]),
        )
        .expect("write source spec");
        std::fs::write(
            dir.join("DIMDD4.xml"),
            spec(vec![
                param("Ch1GroupAddress", "int", 1, "$FF"),
                param("Keep", "int", 1, "$04"),
                param("ToggleDisable", "bit", 1, "0"),
                param("UnitName", "sixbit", 8, "NEWUNIT"),
                param("UnitType", "int", 2, "$FF $FF"),
            ]),
        )
        .expect("write target spec");
        std::fs::write(
            dir.join(MAPPING_TABLE),
            "(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved\n<UnitConversions>\
             <UnitConversion><Unit_type_New>DIMDD4</Unit_type_New><Unit_type_Old>DIMDN4</Unit_type_Old>\
             <Parameters><Pair old=\"GroupAddress\" new=\"Ch1GroupAddress\"><rules>\
             <rule param1=\"1\" param2=\"$FF\">extractByte</rule></rules></Pair>\
             <Pair old=\"Keep\" new=\"Keep\"><rules><rule>setDefaultValue</rule></rules></Pair>\
             <Pair old=\"Toggle\" new=\"ToggleDisable\"><rules>\
             <rule param1=\"\" param2=\"\">toggleGlobalParam</rule></rules></Pair>\
             </Parameters></UnitConversion></UnitConversions>",
        )
        .expect("write mapping table");
        dir
    }

    fn add_source(server: &mut crate::Server, address: u8, groups: &str) {
        let path = format!("//T/254/p/{address}");
        for command in [
            format!("DBADDSAFE //T/254 Unit {address} Old{address}"),
            format!("DBSETSAFE {path}/UnitType DIMDN4"),
            format!("DBSETSAFE {path}/FirmwareVersion 2.7.00"),
            format!("DBSETSAFE {path}/CatalogNumber CAT-N4"),
            "PP LOCK L //T/254".to_string(),
            "PP START S L".to_string(),
            format!("PP LOAD S /db{path}"),
            format!("PP SET S GroupAddress \"{}\"", groups.replace(' ', "\\ ")),
            "PP SET S Toggle 1".to_string(),
            "PP SAVE_TO_SOURCE S".to_string(),
            "PP END S".to_string(),
            "PP UNLOCK L".to_string(),
        ] {
            let response = server.handle(&format!("[f] {command}"));
            assert!(response.status < 400, "{command}: {response:?}");
        }
    }

    #[test]
    fn server_converts_catalogue_and_move_targets_from_the_mapping_table() {
        let dir = fixture();
        let mut server = crate::Server::new(crate::AccessLevel::Program)
            .with_programming(true)
            .with_unitspec_dir(dir.clone());
        for command in [
            "PROJECT NEW T",
            "PROJECT USE T",
            "DBCREATENET 254 Net Cni 127.0.0.1:1",
        ] {
            assert_eq!(server.handle(&format!("[p] {command}")).status, 200);
        }
        add_source(&mut server, 20, "5 6 7");
        let check = server.handle("[1] CONVERTUNIT CHECK 1 //T/254/p/20 DIMDD4 CAT-D4");
        assert_eq!(check.final_text, "200 OK: yes");
        let convert = server.handle("[2] CONVERTUNIT CONVERT 1 //T/254/p/20 DIMDD4 CAT-D4");
        assert_eq!(convert.final_text, "200 OK.");
        let xml = crate::format_response(&server.handle("[3] DBGETXML //T/254/p/20"));
        for expected in [
            "<TagName>Old20</TagName>",
            "<UnitType>DIMDD4</UnitType>",
            "<SerialNumber>00000000.0000</SerialNumber>",
            "<FirmwareVersion>1.3.0</FirmwareVersion>",
            "<CatalogNumber>CAT-D4</CatalogNumber>",
            "<PP Name=\"Ch1GroupAddress\" Value=\"0x6\"/>",
            "<PP Name=\"Keep\" Value=\"0x4\"/>",
            "<PP Name=\"ToggleDisable\" Value=\"0\"/>",
        ] {
            assert!(xml.contains(expected), "{expected} missing from {xml}");
        }
        assert!(!xml.contains("Name=\"GroupAddress\""), "{xml}");

        // Native admission and CONVERT-only identity refusal.
        for (command, text) in [
            ("CHECK 1 //T/254/p/20 DIMDN4 CAT-N4", "301 no"),
            (
                "CHECK 1 //T/254/p/20 DIMDD4 NOSUCH",
                "301 no:Unexpected Catalog number",
            ),
            ("CHECK 1 //T/254/p/20 DIMDD4 CAT-D4", "200 OK: yes"),
            ("CONVERT 1 //T/254/p/20 DIMDD4 CAT-D4", "301 no"),
            (
                "CHECK 1 //T/254/p/99 DIMDD4 CAT-D4",
                "401 Bad object or device ID: Element 99 not found.",
            ),
            ("CHECK 4 //T/254/p/20 DIMDD4 CAT-D4", "400 Syntax Error."),
            ("CHECK 2 //T/254/p/20 //T/254/p/98", "301 no"),
            (
                "CONVERT 2 //T/254/p/20 //T/254/p/98",
                "301 no:Unable to read data from DBElement 98 not found.",
            ),
        ] {
            assert_eq!(
                server
                    .handle(&format!("[n] CONVERTUNIT {command}"))
                    .final_text,
                text,
                "{command}"
            );
        }

        // Move: the destination keeps its identity, gains source PP and the
        // source record is deleted.
        add_source(&mut server, 21, "1 2 3");
        for command in [
            "DBADDSAFE //T/254 Unit 22 Replacement",
            "DBSETSAFE //T/254/p/22/UnitType DIMDD4",
            "DBSETSAFE //T/254/p/22/FirmwareVersion 1.3.0",
            "DBSETSAFE //T/254/p/22/CatalogNumber CAT-D4",
            "DBSETSAFE //T/254/p/22/SerialNumber 01234567.0001",
        ] {
            assert!(
                server.handle(&format!("[m] {command}")).status < 400,
                "{command}"
            );
        }
        let moved = server.handle("[4] CONVERTUNIT CONVERT 2 //T/254/p/21 //T/254/p/22");
        assert_eq!(
            (moved.lines.as_slice(), moved.final_text.as_str()),
            (&["200-OK.".to_string()][..], "200 OK.")
        );
        assert_eq!(server.handle("[5] DBGET //T/254/p/21").status, 401);
        let xml = crate::format_response(&server.handle("[6] DBGETXML //T/254/p/22"));
        for expected in [
            "<TagName>Replacement</TagName>",
            "<SerialNumber>01234567.0001</SerialNumber>",
            "<UnitType>DIMDD4</UnitType>",
            "<PP Name=\"Ch1GroupAddress\" Value=\"0x2\"/>",
        ] {
            assert!(xml.contains(expected), "{expected} missing from {xml}");
        }

        // Without the private mapping table, conversion fails closed.
        add_source(&mut server, 23, "1 2 3");
        std::fs::remove_file(dir.join(MAPPING_TABLE)).expect("remove table");
        assert_eq!(
            server
                .handle("[7] CONVERTUNIT CONVERT 1 //T/254/p/23 DIMDD4 CAT-D4")
                .final_text,
            "301 no:Convert Unit mapping table ConvertUnitMappingTable.xml not found"
        );
        assert!(
            crate::format_response(&server.handle("[8] DBGETXML //T/254/p/23"))
                .contains("<UnitType>DIMDN4</UnitType>")
        );
        std::fs::remove_dir_all(dir).expect("remove fixture");
    }
}
