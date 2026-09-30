//! Pure CDG line proxy mapping recovered from the pinned C-Gate classes.
//! Unknown source families remain unknown; this module does not issue I/O,
//! decide dynamic exclusions, or project catalogue objects into the CDG.

use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

const FAMILIES: [&str; 15] = [
    "virtualGroups",
    "usedDevices",
    "objectProperties",
    "oidToShortAddress",
    "shortAddressToOid",
    "missingDeviceThreshold",
    "wboEnableGroup",
    "lampRunningTime",
    "wboEnableGroupRestoreLevel",
    "remoteOnMask",
    "remoteOffMask",
    "statusCorrectionMask",
    "statusCorrectionInterval",
    "statusUpdatingInterval",
    "sceneTriggerMap",
];
const OBJECT_FIELDS: [&str; 14] = [
    "groupAddress",
    "warnBeforeOffLevel",
    "logicAssignmentBitmask16",
    "applicationIndex",
    "disableDaliToCbus",
    "minLogic",
    "warnBeforeOffTime",
    "colourZone",
    "colourType",
    "fadeInstantOff",
    "fadeInstantMax",
    "fadeInstantLvl",
    "secondaryGroupAddress",
    "tertiaryGroupAddress",
];

fn bytes(values: &[Option<u8>], address: u32, count: usize) -> Option<Vec<u8>> {
    let start = usize::try_from(address.checked_sub(256)?).ok()?;
    values
        .get(start..start.checked_add(count)?)?
        .iter()
        .copied()
        .collect()
}

fn modern(version: Option<(u8, u8)>) -> bool {
    version.is_some_and(|(major, minor)| major > 1 || major == 1 && minor > 5)
}

fn mask(values: &[Option<u8>], address: u32) -> Value {
    bytes(values, address, 8).map_or(Value::Null, |data| {
        json!({"members": (0..64).filter(|bit| data[bit / 8] & (1 << (bit % 8)) != 0)
            .collect::<Vec<_>>()})
    })
}

fn scalar(values: &[Option<u8>], address: u32, field: &str) -> Value {
    bytes(values, address, 1).map_or(Value::Null, |data| json!({field: data[0]}))
}

fn object(values: &[Option<u8>], address: u32, version: Option<(u8, u8)>) -> Value {
    bytes(values, address, 10).map_or(Value::Null, |data| {
        let (off, max, level) = if modern(version) {
            (
                (data[5] >> 6) | ((data[6] & 1) << 2),
                (data[6] >> 1) & 7,
                (data[6] >> 4) & 7,
            )
        } else {
            (0, 0, 4)
        };
        json!({
            "groupAddress": data[0], "warnBeforeOffLevel": data[1],
            "logicAssignmentBitmask16": u16::from_le_bytes([data[2], data[3]]),
            "applicationIndex": data[4] & 3, "disableDaliToCbus": data[4] & 4 != 0,
            "minLogic": data[4] & 8 != 0, "warnBeforeOffTime": data[4] >> 4,
            "colourZone": data[5] & 15, "colourType": (data[5] >> 4) & 3,
            "fadeInstantOff": off, "fadeInstantMax": max, "fadeInstantLvl": level,
            "secondaryGroupAddress": data[8], "tertiaryGroupAddress": data[9]
        })
    })
}

/// Native indexed `ExtProxy.getLine(int)` projection, using address-minus-256 storage.
pub(super) fn decode(values: &[Option<u8>]) -> Value {
    let version = bytes(values, 256, 2).map(|v| (v[0], v[1]));
    Value::Array((0..2).map(|line| {
        let maps = 7040 + line * 64;
            let forward = bytes(values, maps, 64).map_or(Value::Null, |data| {
                let mut utility = Map::new();
                for (index, value) in data.iter().enumerate() {
                    if *value != 255 { utility.insert(value.to_string(), json!(index)); }
                }
                json!({"map": data, "utilitySaToOidMap": utility})
            });
        let inverse = bytes(values, maps, 64).map_or(Value::Null, |data| {
            let mut map = Map::new();
            for (index, value) in data.into_iter().enumerate() {
                if value != 255 { map.insert(value.to_string(), json!(index)); }
            }
            json!({"map": map})
        });
        json!({
            "virtualGroups": (0..16).map(|slot| mask(values, 7168 + line * 128 + slot * 8)).collect::<Vec<_>>(),
            "usedDevices": mask(values, 8800 + line * 8),
            "objectProperties": (0..97).map(|slot| object(values, 768 + line * 3104 + slot * 32, version)).collect::<Vec<_>>(),
            "oidToShortAddress": forward, "shortAddressToOid": inverse,
            "missingDeviceThreshold": scalar(values, 519 + line, "threshold"),
            "wboEnableGroup": scalar(values, 516 + line, "group"),
            "lampRunningTime": (0..64).map(|slot| {
                bytes(values, 7424 + line * 256 + slot * 4, 4).map_or(Value::Null, |data| {
                    let time = i32::from_le_bytes(data.try_into().expect("four-byte read"));
                    if time == -1 { Value::Null } else { json!({"time": time}) }
                })
            }).collect::<Vec<_>>(),
            "wboEnableGroupRestoreLevel": scalar(values, 554 + line, "level"),
            "remoteOnMask": mask(values, 560 + line * 8), "remoteOffMask": mask(values, 576 + line * 8),
            "statusCorrectionMask": mask(values, 592 + line * 8),
            "statusCorrectionInterval": scalar(values, 612 + line, "interval"),
            "statusUpdatingInterval": scalar(values, 614 + line, "interval"),
            "sceneTriggerMap": (0..17).map(|slot| {
                bytes(values, 7936 + line * 340 + slot * 20, 20).map_or(Value::Null, |data| {
                    let mask = u16::from_le_bytes([data[0], data[1]]);
                    let selectors: Map<String, Value> = (0..16).filter(|bit| mask & (1 << bit) != 0)
                        .map(|bit| (bit.to_string(), json!(data[bit + 3]))).collect();
                    json!({"triggerGroup": data[2], "actionSelector": selectors})
                })
            }).collect::<Vec<_>>()
        })
    }).collect())
}

fn exact<'a>(
    value: &'a Value,
    fields: &[&str],
    context: &str,
) -> Result<&'a Map<String, Value>, String> {
    let map = value
        .as_object()
        .ok_or_else(|| format!("{context} must be an object"))?;
    if map.len() != fields.len() || fields.iter().any(|field| !map.contains_key(*field)) {
        return Err(format!("{context} must contain exactly its native fields"));
    }
    Ok(map)
}

fn number(value: &Value, max: u64, context: &str) -> Result<u64, String> {
    value
        .as_u64()
        .filter(|n| *n <= max)
        .ok_or_else(|| format!("{context} needs an integer in 0..{max}"))
}

fn array<'a>(value: &'a Value, count: usize, context: &str) -> Result<&'a [Value], String> {
    let items = value
        .as_array()
        .filter(|items| items.len() == count)
        .ok_or_else(|| format!("{context} needs exactly {count} entries"))?;
    Ok(items)
}

fn known(value: &Value, baseline: &Value, context: &str) -> Result<bool, String> {
    if baseline.is_null() {
        if value.is_null() {
            return Ok(false);
        }
        return Err(format!("{context} has no complete recalled source family"));
    }
    if value.is_null() {
        return Err(format!("{context} cannot erase a recalled native family"));
    }
    Ok(true)
}

fn put(output: &mut Vec<(u32, u8)>, address: u32, data: impl IntoIterator<Item = u8>) {
    output.extend(
        data.into_iter()
            .enumerate()
            .map(|(offset, value)| (address + offset as u32, value)),
    );
}

fn compile_mask(
    value: &Value,
    baseline: &Value,
    address: u32,
    output: &mut Vec<(u32, u8)>,
) -> Result<(), String> {
    if !known(value, baseline, "line mask")? {
        return Ok(());
    }
    let map = exact(value, &["members"], "line mask")?;
    let members = map["members"]
        .as_array()
        .ok_or("line mask members must be an array")?;
    let mut data = [0; 8];
    let mut used = BTreeSet::new();
    for member in members {
        let bit = number(member, 63, "line mask member")? as usize;
        if !used.insert(bit) {
            return Err("line mask members must not repeat".into());
        }
        data[bit / 8] |= 1 << (bit % 8);
    }
    put(output, address, data);
    Ok(())
}

fn compile_scalar(
    value: &Value,
    baseline: &Value,
    address: u32,
    field: &str,
    output: &mut Vec<(u32, u8)>,
) -> Result<(), String> {
    if !known(value, baseline, field)? {
        return Ok(());
    }
    let map = exact(value, &[field], field)?;
    put(output, address, [number(&map[field], 255, field)? as u8]);
    Ok(())
}

fn compile_object(
    value: &Value,
    baseline: &Value,
    address: u32,
    version: Option<(u8, u8)>,
    output: &mut Vec<(u32, u8)>,
) -> Result<(), String> {
    if !known(value, baseline, "objectProperties")? {
        return Ok(());
    }
    let map = exact(value, &OBJECT_FIELDS, "objectProperties")?;
    let n = |key: &str, max| number(&map[key], max, key).map(|v| v as u16);
    let b = |key: &str| {
        map[key]
            .as_bool()
            .ok_or_else(|| format!("{key} must be Boolean"))
    };
    let logic = n("logicAssignmentBitmask16", 65535)?.to_le_bytes();
    let off = n("fadeInstantOff", 7)? as u8;
    let max = n("fadeInstantMax", 7)? as u8;
    let level = n("fadeInstantLvl", 7)? as u8;
    if !modern(version)
        && ["fadeInstantOff", "fadeInstantMax", "fadeInstantLvl"]
            .iter()
            .any(|field| map[*field] != baseline[*field])
    {
        return Err("ObjectProperties fade controls need ConfigVersion greater than 1.5".into());
    }
    let byte4 = n("applicationIndex", 3)? as u8
        | (u8::from(b("disableDaliToCbus")?) << 2)
        | (u8::from(b("minLogic")?) << 3)
        | ((n("warnBeforeOffTime", 15)? as u8) << 4);
    let byte5 = n("colourZone", 15)? as u8
        | ((n("colourType", 3)? as u8) << 4)
        | if modern(version) { (off & 3) << 6 } else { 0 };
    put(
        output,
        address,
        [
            n("groupAddress", 255)? as u8,
            n("warnBeforeOffLevel", 255)? as u8,
            logic[0],
            logic[1],
            byte4,
            byte5,
        ],
    );
    if modern(version) {
        put(
            output,
            address + 6,
            [0x80 | ((off >> 2) & 1) | (max << 1) | (level << 4)],
        );
    }
    // Native always leaves byte7 and bytes10..31 unset; the caller excludes them.
    put(
        output,
        address + 8,
        [
            n("secondaryGroupAddress", 255)? as u8,
            n("tertiaryGroupAddress", 255)? as u8,
        ],
    );
    Ok(())
}

/// Compile all complete recalled line families in native serializer order.
/// `version` must be the effective global target version after global compilation.
/// Duplicate address entries intentionally retain forward-then-inverse map order.
pub(super) fn compile(
    values: &[Option<u8>],
    proxy: &Value,
    version: Option<(u8, u8)>,
) -> Result<Vec<(u32, u8)>, String> {
    let baseline = decode(values);
    let lines = array(proxy, 2, "proxy line")?;
    let baseline = baseline.as_array().expect("decode returns two lines");
    let mut output = Vec::new();
    for (index, line) in lines.iter().enumerate() {
        let map = exact(line, &FAMILIES, "proxy line")?;
        let before = &baseline[index];
        let line = index as u32;
        for (slot, value) in array(&map["virtualGroups"], 16, "virtualGroups")?
            .iter()
            .enumerate()
        {
            compile_mask(
                value,
                &before["virtualGroups"][slot],
                7168 + line * 128 + slot as u32 * 8,
                &mut output,
            )?;
        }
        compile_mask(
            &map["usedDevices"],
            &before["usedDevices"],
            8800 + line * 8,
            &mut output,
        )?;
        for (slot, value) in array(&map["objectProperties"], 97, "objectProperties")?
            .iter()
            .enumerate()
        {
            compile_object(
                value,
                &before["objectProperties"][slot],
                768 + line * 3104 + slot as u32 * 32,
                version,
                &mut output,
            )?;
        }
        let address = 7040 + line * 64;
        if known(
            &map["oidToShortAddress"],
            &before["oidToShortAddress"],
            "oidToShortAddress",
        )? {
            // The utility map is a native computed getter, not a second
            // physical owner. The command admission layer rejects edits
            // to it; only the forward map supplies these target bytes.
            let forward = exact(
                &map["oidToShortAddress"],
                &["map", "utilitySaToOidMap"],
                "oidToShortAddress",
            )?;
            let bytes = array(&forward["map"], 64, "oidToShortAddress map")?
                .iter()
                .map(|v| number(v, 255, "oidToShortAddress value").map(|v| v as u8))
                .collect::<Result<Vec<_>, _>>()?;
            put(&mut output, address, bytes);
        }
        if known(
            &map["shortAddressToOid"],
            &before["shortAddressToOid"],
            "shortAddressToOid",
        )? {
            let inverse = exact(&map["shortAddressToOid"], &["map"], "shortAddressToOid")?;
            let inverse = inverse["map"]
                .as_object()
                .ok_or("shortAddressToOid map must be an object")?;
            let mut bytes = [255; 64];
            let mut used = BTreeSet::new();
            for (key, value) in inverse {
                let short: u8 = key
                    .parse()
                    .ok()
                    .filter(|n: &u8| *n != 255)
                    .ok_or("shortAddressToOid keys must be canonical 0..254")?;
                if key != &short.to_string() {
                    return Err("shortAddressToOid keys must be canonical".into());
                }
                let oid = number(value, 63, "shortAddressToOid OID")? as usize;
                if !used.insert(oid) {
                    return Err("shortAddressToOid must be one-to-one".into());
                }
                bytes[oid] = short;
            }
            put(&mut output, address, bytes);
        }
        compile_scalar(
            &map["missingDeviceThreshold"],
            &before["missingDeviceThreshold"],
            519 + line,
            "threshold",
            &mut output,
        )?;
        compile_scalar(
            &map["wboEnableGroup"],
            &before["wboEnableGroup"],
            516 + line,
            "group",
            &mut output,
        )?;
        for (slot, value) in array(&map["lampRunningTime"], 64, "lampRunningTime")?
            .iter()
            .enumerate()
        {
            if !known(value, &before["lampRunningTime"][slot], "lampRunningTime")? {
                continue;
            }
            let map = exact(value, &["time"], "lampRunningTime")?;
            let time = map["time"]
                .as_i64()
                .and_then(|n| i32::try_from(n).ok())
                .filter(|n| *n != -1)
                .ok_or("lampRunningTime needs a signed 32-bit time other than -1")?;
            put(
                &mut output,
                7424 + line * 256 + slot as u32 * 4,
                time.to_le_bytes(),
            );
        }
        compile_scalar(
            &map["wboEnableGroupRestoreLevel"],
            &before["wboEnableGroupRestoreLevel"],
            554 + line,
            "level",
            &mut output,
        )?;
        for (family, base) in [
            ("remoteOnMask", 560),
            ("remoteOffMask", 576),
            ("statusCorrectionMask", 592),
        ] {
            compile_mask(&map[family], &before[family], base + line * 8, &mut output)?;
        }
        compile_scalar(
            &map["statusCorrectionInterval"],
            &before["statusCorrectionInterval"],
            612 + line,
            "interval",
            &mut output,
        )?;
        compile_scalar(
            &map["statusUpdatingInterval"],
            &before["statusUpdatingInterval"],
            614 + line,
            "interval",
            &mut output,
        )?;
        for (slot, value) in array(&map["sceneTriggerMap"], 17, "sceneTriggerMap")?
            .iter()
            .enumerate()
        {
            if !known(value, &before["sceneTriggerMap"][slot], "sceneTriggerMap")? {
                continue;
            }
            let map = exact(
                value,
                &["triggerGroup", "actionSelector"],
                "sceneTriggerMap",
            )?;
            let selectors = map["actionSelector"]
                .as_object()
                .ok_or("actionSelector must be an object")?;
            let mut mask = 0_u16;
            let mut bytes = [255; 20];
            bytes[2] = number(&map["triggerGroup"], 255, "triggerGroup")? as u8;
            bytes[19] = 0;
            for (key, value) in selectors {
                let bit = key
                    .parse::<usize>()
                    .ok()
                    .filter(|n| *n < 16)
                    .ok_or("actionSelector keys must be canonical 0..15")?;
                if key != &bit.to_string() {
                    return Err("actionSelector keys must be canonical".into());
                }
                mask |= 1 << bit;
                bytes[3 + bit] = number(value, 255, "actionSelector value")? as u8;
            }
            [bytes[0], bytes[1]] = mask.to_le_bytes();
            put(&mut output, 7936 + line * 340 + slot as u32 * 20, bytes);
        }
    }
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn native_line_layout_and_reserved_bits_are_independent_literals() {
        let values = vec![Some(0); 11120];
        let mut proxy = decode(&values);
        proxy[0]["objectProperties"][0]["groupAddress"] = json!(91);
        proxy[0]["objectProperties"][0]["logicAssignmentBitmask16"] = json!(0x1234);
        proxy[0]["objectProperties"][0]["fadeInstantOff"] = json!(5);
        proxy[0]["objectProperties"][0]["fadeInstantMax"] = json!(3);
        proxy[0]["objectProperties"][0]["fadeInstantLvl"] = json!(6);
        proxy[0]["virtualGroups"][15]["members"] = json!([0, 7, 8, 63]);
        proxy[1]["statusUpdatingInterval"]["interval"] = json!(29);
        proxy[1]["sceneTriggerMap"][16] =
            json!({"triggerGroup": 202, "actionSelector": {"0": 11, "15": 22}});
        let compiled: BTreeMap<_, _> = compile(&values, &proxy, Some((1, 6)))
            .unwrap()
            .into_iter()
            .collect();
        assert_eq!(
            (compiled[&768], compiled[&770], compiled[&771]),
            (91, 0x34, 0x12)
        );
        assert_eq!((compiled[&773], compiled[&774]), (0x40, 0xE7));
        assert!(!compiled.contains_key(&775));
        assert_eq!(
            (compiled[&7288], compiled[&7289], compiled[&7295]),
            (0x81, 1, 0x80)
        );
        assert_eq!(compiled[&615], 29);
        assert_eq!(
            (
                compiled[&8596],
                compiled[&8597],
                compiled[&8598],
                compiled[&8599],
                compiled[&8614],
                compiled[&8615]
            ),
            (1, 0x80, 202, 11, 22, 0)
        );
    }

    #[test]
    fn unknown_source_and_ignored_old_version_edits_fail_closed() {
        let unknown = vec![None; 11120];
        let mut proxy = decode(&unknown);
        assert!(compile(&unknown, &proxy, None).unwrap().is_empty());
        proxy[0]["wboEnableGroup"] = json!({"group": 4});
        assert!(compile(&unknown, &proxy, None)
            .unwrap_err()
            .contains("recalled source"));
        let values = vec![Some(0); 11120];
        let mut proxy = decode(&values);
        proxy[0]["objectProperties"][0]["fadeInstantLvl"] = json!(5);
        assert!(compile(&values, &proxy, Some((1, 5)))
            .unwrap_err()
            .contains("greater than 1.5"));
    }

    #[test]
    fn native_inverse_mapping_overwrites_forward_and_time_is_signed_little_endian() {
        let mut values = vec![Some(0); 11120];
        values[7424 - 256..7428 - 256].copy_from_slice(&[
            Some(0xFE),
            Some(0xFF),
            Some(0xFF),
            Some(0xFF),
        ]);
        let proxy = decode(&values);
        assert_eq!(proxy[0]["lampRunningTime"][0]["time"], -2);
        let compiled: BTreeMap<_, _> = compile(&values, &proxy, Some((1, 5)))
            .unwrap()
            .into_iter()
            .collect();
        assert_eq!((compiled[&7040], compiled[&7103]), (255, 0));
        assert_eq!((compiled[&7424], compiled[&7427]), (0xFE, 0xFF));
    }

    #[test]
    fn every_recalled_line_family_matches_executed_original_classes() {
        let receipt: Value = serde_json::from_str(include_str!(
            "../../../../toolkit-cli/research/fixtures/dali-ext-proxy-original-vectors.json"
        ))
        .unwrap();
        assert_eq!(
            receipt["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        for (name, case) in receipt["cases"].as_object().unwrap() {
            let mut values =
                vec![Some(case["input"]["default_current_byte"].as_u64().unwrap() as u8); 11120];
            for (address, value) in case["input"]["current_overrides"].as_object().unwrap() {
                values[address.parse::<usize>().unwrap() - 256] =
                    Some(value.as_u64().unwrap() as u8);
            }
            assert_eq!(
                decode(&values),
                case["line_model_before"],
                "{name}: original decoded model"
            );
            let version = case["global_model_staged"]["configVersion"]
                .as_object()
                .unwrap();
            let compiled: BTreeMap<_, _> = compile(
                &values,
                &case["line_model_staged"],
                Some((
                    version["major"].as_u64().unwrap() as u8,
                    version["minor"].as_u64().unwrap() as u8,
                )),
            )
            .unwrap()
            .into_iter()
            .collect();
            let expected: BTreeSet<u32> = case["target_bytes"]
                .as_object()
                .unwrap()
                .keys()
                .map(|address| address.parse::<u32>().unwrap())
                .filter(|address| {
                    !matches!(address,
                    256..=257 | 512..=515 | 518 | 521..=553 | 556 | 558..=559 |
                    608..=610 | 616..=645 | 656..=665)
                })
                .collect();
            assert_eq!(
                compiled.keys().copied().collect::<BTreeSet<_>>(),
                expected,
                "{name}: exact native line byte ownership"
            );
            // Original targets include globals too. Every line-owned target
            // must agree, including both writers of the shared maps after the
            // inverse model has replaced the forward model's bytes.
            for (address, byte) in compiled {
                assert_eq!(
                    case["target_bytes"][address.to_string()],
                    byte,
                    "{name}: original target address {address}"
                );
            }
        }
    }
}
