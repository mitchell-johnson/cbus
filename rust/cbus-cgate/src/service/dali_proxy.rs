//! Native DALI CDG extended-proxy configuration. Complete recalled families
//! are serialized in native order, including reserved-bit normalization.
use super::{ExtendedMap, EXT_START};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[path = "dali_proxy_lines.rs"]
mod lines;

#[derive(Clone)]
struct Field {
    path: String,
    address: u32,
    shift: u8,
    width: u8,
    boolean: bool,
}

fn fields() -> Vec<Field> {
    let mut fields = Vec::new();
    let mut field = |path: &str, address, shift, width, boolean| {
        fields.push(Field {
            path: path.to_string(),
            address,
            shift,
            width,
            boolean,
        });
    };
    for (path, address) in [
        ("configVersion/major", 256),
        ("configVersion/minor", 257),
        ("deviceID/id", 556),
        ("errorReportingEnableGroup/group", 632),
        ("errorReportingTriggerGroup/group", 633),
        ("errorReportingResendActionSelector/selector", 634),
        ("errorReportingAcknowledgeAllActionSelector/selector", 635),
        ("errorReportingMode/mode", 636),
        ("errorReportingRegularReportInterval/interval", 637),
        ("measurementRequestTriggerGroup/group", 558),
        ("measurementClearTriggerGroup/group", 559),
        ("measurementRegularBroadcastInterval/interval", 644),
        ("cbusVoltageThresholds/warningSetThreshold", 656),
        ("cbusVoltageThresholds/warningClearThreshold", 657),
        ("cbusVoltageThresholds/criticalSetThreshold", 658),
        ("cbusVoltageThresholds/criticalClearThreshold", 659),
        ("cbusOverTemperatureThresholds/unitSetThreshold", 660),
        ("cbusOverTemperatureThresholds/unitClearThreshold", 661),
        ("cbusOverTemperatureThresholds/lineASetThreshold", 662),
        ("cbusOverTemperatureThresholds/lineBSetThreshold", 663),
        ("cbusOverTemperatureThresholds/lineAClearThreshold", 664),
        ("cbusOverTemperatureThresholds/lineBClearThreshold", 665),
    ] {
        field(path, address, 0, 8, false);
    }
    for i in 0..4 {
        field(
            &format!("lightingApplications/app{}", i + 1),
            512 + i,
            0,
            8,
            false,
        );
    }
    for i in 0..6 {
        field(
            &format!("networkPathErrorReportAndMeasurements/path/{i}"),
            638 + i,
            0,
            8,
            false,
        );
    }
    for i in 0..16 {
        field(
            &format!("logicGroups/{i}/groupAddress"),
            522 + 2 * i,
            0,
            8,
            false,
        );
        field(
            &format!("logicGroups/{i}/applicationIndex"),
            523 + 2 * i,
            0,
            2,
            false,
        );
        field(
            &format!("logicGroups/{i}/restoreToPreviousLevel"),
            523 + 2 * i,
            2,
            1,
            true,
        );
        field(
            &format!("logicGroupRestoreLevel/{i}/level"),
            616 + i,
            0,
            8,
            false,
        );
    }
    for (family, address, names) in [
        (
            "frontPanelUiControl",
            518,
            &[
                "localToggleDisabledA",
                "localToggleDisabledB",
                "commissioningDisabledA",
                "commissioningDisabledB",
                "cbusPriorityDisabledA",
                "cbusPriorityDisabledB",
                "factoryResetDisabled",
            ][..],
        ),
        (
            "enableGroupLevelStoreOptions",
            521,
            &[
                "wboEnableA",
                "wboEnableB",
                "errorReportingEnable",
                "colourModeA",
                "colourModeB",
            ][..],
        ),
        (
            "measurementRegularBroadcastOptions",
            645,
            &[
                "lampHours",
                "channelMetering",
                "daliMacTemperature",
                "daliCurrent",
                "daliVoltage",
                "cbusVoltage",
                "unitTemperature",
            ][..],
        ),
        (
            "brokenDeviceDefinitionMask",
            608,
            &[
                "controlGearFailure",
                "lampFailure",
                "circuitFailure",
                "batteryDurationFailure",
                "batteryFailure",
                "emergencyLampFailure",
                "functionTestMaxDelayExceeded",
                "durationTestMaxDelayExceeded",
                "functionTestFailed",
                "durationTestFailed",
                "openCircuit",
                "shortCircuit",
                "loadDecrease",
                "loadIncrease",
                "currentProtectorActive",
                "thermalShutdown",
                "thermalOverloadWithLightLevelReduction",
                "referenceMeasurementFailed",
            ][..],
        ),
    ] {
        for (i, name) in names.iter().enumerate() {
            field(
                &format!("{family}/{name}"),
                address + i as u32 / 8,
                i as u8 % 8,
                1,
                true,
            );
        }
    }
    fields
}

fn family(path: &str) -> &str {
    path.split('/').next().unwrap_or(path)
}

fn get(map: &ExtendedMap, address: u32) -> Option<u8> {
    map.values
        .get((address - EXT_START) as usize)
        .copied()
        .flatten()
}

fn insert(root: &mut Value, path: &str, value: Value) {
    let parts: Vec<_> = path.split('/').collect();
    let mut current = root;
    for (index, part) in parts.iter().enumerate() {
        if index + 1 == parts.len() {
            if let Some(array) = current.as_array_mut() {
                let i = part.parse::<usize>().unwrap();
                while array.len() <= i {
                    array.push(Value::Null);
                }
                array[i] = value;
            } else {
                current
                    .as_object_mut()
                    .unwrap()
                    .insert((*part).to_string(), value);
            }
            return;
        }
        let next_is_index = parts[index + 1].parse::<usize>().is_ok();
        if current.is_array() {
            let i = part.parse::<usize>().unwrap();
            let array = current.as_array_mut().unwrap();
            while array.len() <= i {
                array.push(Value::Null);
            }
            if array[i].is_null() {
                array[i] = if next_is_index { json!([]) } else { json!({}) };
            }
            current = &mut array[i];
        } else {
            let object = current.as_object_mut().unwrap();
            current = object.entry((*part).to_string()).or_insert_with(|| {
                if next_is_index {
                    json!([])
                } else {
                    json!({})
                }
            });
        }
    }
}

pub(super) fn decode(map: &ExtendedMap) -> Value {
    let mut proxy = json!({});
    for field in fields() {
        let value = get(map, field.address)
            .map(|byte| {
                let value = (byte >> field.shift) & ((1u16 << field.width) - 1) as u8;
                if field.boolean {
                    json!(value != 0)
                } else {
                    json!(value)
                }
            })
            .unwrap_or(Value::Null);
        insert(&mut proxy, &field.path, value);
    }
    proxy["line"] = lines::decode(&map.values);
    proxy
}

/// Validate and compile a changed family from one complete recalled image.
/// Target bytes cannot overlap that family: raw and typed owners are separate.
pub(super) fn compile(map: &ExtendedMap, proxy: &Value) -> Result<Vec<(u32, u8)>, String> {
    let baseline = decode(map);
    let fields = fields();
    fn shape(value: &Value, baseline: &Value) -> bool {
        match baseline {
            Value::Object(expected) => value.as_object().is_some_and(|actual| {
                actual.len() == expected.len()
                    && expected.iter().all(|(key, before)| {
                        actual.get(key).is_some_and(|after| shape(after, before))
                    })
            }),
            Value::Array(expected) => value.as_array().is_some_and(|actual| {
                actual.len() == expected.len()
                    && actual
                        .iter()
                        .zip(expected)
                        .all(|(after, before)| shape(after, before))
            }),
            _ => !value.is_object() && !value.is_array(),
        }
    }
    let actual = proxy.as_object().ok_or("proxy must be an object")?;
    let expected = baseline.as_object().unwrap();
    if actual.len() != expected.len()
        || expected
            .iter()
            .filter(|(key, _)| *key != "line")
            .any(|(key, before)| actual.get(key).is_none_or(|after| !shape(after, before)))
    {
        return Err("proxy global fields do not match the native schema".to_string());
    }
    let changed: BTreeSet<_> = fields
        .iter()
        .filter(|field| {
            proxy.pointer(&format!("/{}", field.path))
                != baseline.pointer(&format!("/{}", field.path))
        })
        .map(|field| family(&field.path).to_string())
        .collect();
    let admitted: BTreeSet<_> = fields
        .iter()
        .map(|field| family(&field.path))
        .filter(|name| {
            fields
                .iter()
                .filter(|field| family(&field.path) == *name)
                .all(|field| get(map, field.address).is_some())
        })
        .collect();
    for name in &changed {
        if !admitted.contains(name.as_str()) {
            return Err(format!(
                "proxy family {name} requires a complete recalled image"
            ));
        }
    }
    let mut bytes = BTreeMap::new();
    for field in fields
        .iter()
        .filter(|field| admitted.contains(family(&field.path)))
    {
        let current = get(map, field.address).unwrap();
        let value = proxy
            .pointer(&format!("/{}", field.path))
            .ok_or_else(|| format!("proxy field {} is absent", field.path))?;
        let value = if field.boolean {
            u64::from(
                value
                    .as_bool()
                    .ok_or_else(|| format!("proxy field {} needs a Boolean", field.path))?,
            )
        } else {
            value
                .as_u64()
                .filter(|value| *value < (1u64 << field.width))
                .ok_or_else(|| {
                    format!(
                        "proxy field {} needs an integer in 0..{}",
                        field.path,
                        (1u64 << field.width) - 1
                    )
                })?
        };
        let mask = (((1u16 << field.width) - 1) as u8) << field.shift;
        let byte = bytes.entry(field.address).or_insert(current);
        *byte = (*byte & !mask) | ((value as u8) << field.shift);
    }
    if admitted.contains("frontPanelUiControl") {
        *bytes.get_mut(&518).unwrap() &= 0x7f;
    }
    if admitted.contains("enableGroupLevelStoreOptions") {
        *bytes.get_mut(&521).unwrap() |= 0xe0;
    }
    if admitted.contains("measurementRegularBroadcastOptions") {
        *bytes.get_mut(&645).unwrap() |= 0x80;
    }
    if admitted.contains("brokenDeviceDefinitionMask") {
        *bytes.get_mut(&610).unwrap() &= 3;
    }
    // gU reads reserved bits from targets; UNSET target (-1) yields 0xf8.
    if admitted.contains("logicGroups") {
        for i in 0..16 {
            let address = 523 + 2 * i;
            *bytes.get_mut(&address).unwrap() = (*bytes.get(&address).unwrap() & 7)
                | (map.targets.get(&address).copied().unwrap_or(255) & 0xf8);
        }
    }
    let version = (
        bytes.get(&256).copied().or_else(|| get(map, 256)),
        bytes.get(&257).copied().or_else(|| get(map, 257)),
    );
    let version = match version {
        (Some(major), Some(minor)) => Some((major, minor)),
        _ => None,
    };
    let line_model = proxy.get("line").ok_or("proxy line is absent")?;
    for (address, value) in lines::compile(&map.values, line_model, version)? {
        bytes.insert(address, value);
    }
    for (&address, &value) in &bytes {
        if map
            .targets
            .get(&address)
            .is_some_and(|target| *target != value)
        {
            return Err(format!(
                "raw extended edit at {address} conflicts with the native proxy serializer"
            ));
        }
    }
    Ok(bytes.into_iter().collect())
}

pub(super) fn validate_edit(proxy: &Value, path: &str) -> Result<(), String> {
    let prefix = "/cdg/extParams/proxy/";
    let suffix = path
        .strip_prefix(prefix)
        .ok_or_else(|| "invalid proxy property path".to_string())?;
    if suffix.contains("/utilitySaToOidMap") {
        return Err("utilitySaToOidMap is a computed read-only property".to_string());
    }
    if !suffix.starts_with("line/") && !fields().iter().any(|field| field.path == suffix) {
        return Err(format!("unsupported writable proxy field: {suffix}"));
    }
    if proxy.pointer(&format!("/{suffix}")).is_none() {
        return Err("proxy field is absent".to_string());
    }
    Ok(())
}

/// Original DaliGatewayExtParamMap dirty-byte exclusion (static and dynamic).
pub(super) fn excluded(map: &ExtendedMap, address: u32) -> bool {
    if address == 557
        || (646..648).contains(&address)
        || (6976..7040).contains(&address)
        || (8616..8800).contains(&address)
        || (666..768).contains(&address)
        || (592..608).contains(&address)
        || (612..614).contains(&address)
        || (8816..11376).contains(&address)
    {
        return true;
    }
    let byte = |address| {
        map.targets
            .get(&address)
            .copied()
            .or_else(|| get(map, address))
            .unwrap_or(255)
    };
    let store = byte(521);
    if address == 554 {
        return store & 1 != 0;
    }
    if address == 555 {
        return store & 2 != 0;
    }
    if address == 636 {
        return byte(632) != 255 && store & 4 != 0;
    }
    if (616..632).contains(&address) {
        return byte(523 + (address - 616) * 2) & 4 != 0;
    }
    if (7424..7936).contains(&address) {
        return map.targets.get(&address) != Some(&0);
    }
    let offset = if (768..3872).contains(&address) {
        Some(address - 768)
    } else if (3872..6976).contains(&address) {
        Some(address - 3872)
    } else {
        None
    };
    if let Some(offset) = offset {
        let index = offset % 32;
        if index == 7 || index >= 10 {
            return true;
        }
        if index == 6 {
            let version = map
                .targets
                .get(&256)
                .copied()
                .zip(map.targets.get(&257).copied())
                .or_else(|| get(map, 256).zip(get(map, 257)));
            return !version.is_some_and(|(major, minor)| major > 1 || major == 1 && minor > 5);
        }
    }
    false
}

pub(super) fn capabilities() -> Value {
    let fields = fields();
    let families: BTreeSet<_> = fields.iter().map(|field| family(&field.path)).collect();
    let schema: Vec<_> = fields
        .iter()
        .map(|field| {
            json!({
                "path": format!("/cdg/extParams/proxy/{}", field.path), "address": field.address,
                "type": if field.boolean { "boolean" } else { "integer" },
                "minimum": 0, "maximum": (1u64 << field.width) - 1,
                "bit_shift": field.shift, "bit_width": field.width,
            })
        })
        .collect();
    json!({"families": families, "leaf_count": fields.len(), "writable_global_fields": schema,
        "line_families": 15, "whole_recalled_families": true,
        "catalogue_projection": false, "native_reserved_bits": true, "excluded_bytes": true,
        "raw_proxy_conflict_refused": true, "unknown_source_families_preserved": true,
        "raw_ext_only_proxy_serialized": false, "whole_proxy_replacement": false})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn original_zero_map_roundtrip_normalizes_native_reserved_bits() {
        let mut map = ExtendedMap::default();
        map.replace(vec![0; 11120]);
        let compiled: BTreeMap<_, _> = compile(&map, &decode(&map)).unwrap().into_iter().collect();
        // Observed by original C-Gate classes, not a Rust roundtrip oracle.
        assert_eq!(
            (compiled[&518], compiled[&521], compiled[&645]),
            (0, 224, 128)
        );
        for index in 0..16 {
            assert_eq!(compiled[&(523 + 2 * index)], 248);
        }
        assert_eq!((compiled[&7040], compiled[&7103]), (255, 0));
        assert!(!compiled.contains_key(&557));
    }

    #[test]
    fn original_four_family_edit_emits_exact_native_bytes() {
        let mut map = ExtendedMap::default();
        map.replace(vec![0; 11120]);
        let mut proxy = decode(&map);
        proxy["lightingApplications"]["app1"] = json!(57);
        proxy["frontPanelUiControl"]["localToggleDisabledA"] = json!(true);
        proxy["enableGroupLevelStoreOptions"]["errorReportingEnable"] = json!(true);
        proxy["deviceID"]["id"] = json!(42);
        let compiled: BTreeMap<_, _> = compile(&map, &proxy).unwrap().into_iter().collect();
        assert_eq!(
            (
                compiled[&512],
                compiled[&518],
                compiled[&521],
                compiled[&556]
            ),
            (57, 1, 228, 42)
        );
    }

    #[test]
    fn incomplete_sources_invalid_fields_and_raw_conflicts_refuse_atomically() {
        let mut map = ExtendedMap::default();
        let mut proxy = decode(&map);
        assert!(compile(&map, &proxy).unwrap().is_empty());
        proxy["deviceID"]["id"] = json!(42);
        assert!(compile(&map, &proxy)
            .unwrap_err()
            .contains("complete recalled image"));
        map.replace(vec![0; 11120]);
        let mut proxy = decode(&map);
        proxy["lightingApplications"]["app1"] = json!(256);
        assert!(compile(&map, &proxy).unwrap_err().contains("0..255"));
        proxy = decode(&map);
        proxy["deviceID"]["extra"] = json!(4);
        assert!(compile(&map, &proxy).unwrap_err().contains("native schema"));
        map.stage(556, &[42]).unwrap();
        assert!(compile(&map, &decode(&map))
            .unwrap_err()
            .contains("conflicts"));
        assert_eq!(map.targets[&556], 42);
    }

    #[test]
    fn original_dynamic_exclusions_respect_complete_version_and_effective_targets() {
        let mut map = ExtendedMap::default();
        assert!(excluded(&map, 557));
        assert!(excluded(&map, 775));
        assert!(excluded(&map, 778));
        assert!(excluded(&map, 774));
        map.values[0] = Some(1);
        map.values[1] = Some(5);
        map.stage(256, &[2]).unwrap();
        assert!(
            excluded(&map, 774),
            "one staged version byte does not establish a target version"
        );
        map.stage(257, &[0]).unwrap();
        assert!(!excluded(&map, 774));
        map.stage(521, &[7]).unwrap();
        map.stage(632, &[1]).unwrap();
        assert!(excluded(&map, 554));
        assert!(excluded(&map, 555));
        assert!(excluded(&map, 636));
        map.stage(521, &[0]).unwrap();
        assert!(!excluded(&map, 554));
        assert!(!excluded(&map, 555));
        assert!(!excluded(&map, 636));
        assert!(excluded(&map, 7424));
        map.stage(7424, &[0]).unwrap();
        assert!(!excluded(&map, 7424));
    }

    #[test]
    fn complete_proxy_and_excluded_byte_effects_match_all_executed_original_vectors() {
        let receipt: Value = serde_json::from_str(include_str!(
            "../../../../toolkit-cli/research/fixtures/dali-ext-proxy-original-vectors.json"
        ))
        .unwrap();
        assert_eq!(
            receipt["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        for (name, case) in receipt["cases"].as_object().unwrap() {
            let mut map = ExtendedMap::default();
            map.replace(vec![
                case["input"]["default_current_byte"].as_u64().unwrap()
                    as u8;
                11120
            ]);
            for (address, value) in case["input"]["current_overrides"].as_object().unwrap() {
                map.values[address.parse::<usize>().unwrap() - 256] =
                    Some(value.as_u64().unwrap() as u8);
            }
            let mut expected_before = case["global_model_before"].clone();
            expected_before["line"] = case["line_model_before"].clone();
            assert_eq!(
                decode(&map),
                expected_before,
                "{name}: original global and line decoding"
            );
            let mut staged = case["global_model_staged"].clone();
            staged["line"] = case["line_model_staged"].clone();
            let encoded: BTreeMap<_, _> = compile(&map, &staged).unwrap().into_iter().collect();
            let expected: BTreeMap<_, _> = case["target_bytes"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(address, value)| {
                    (
                        address.parse::<u32>().unwrap(),
                        value.as_u64().unwrap() as u8,
                    )
                })
                .collect();
            assert_eq!(encoded, expected, "{name}: every native proxy-owned byte");
            let mut original_final = map.values.clone();
            for (index, data) in case["dirty_chunks"].as_object().unwrap() {
                let index = index.parse::<usize>().unwrap();
                for (offset, value) in data.as_array().unwrap().iter().enumerate() {
                    original_final[index + offset] = Some(value.as_u64().unwrap() as u8);
                }
            }
            map.targets = encoded;
            let mut rust_final = map.values.clone();
            for (address, data) in map.dirty_chunks() {
                for (offset, value) in data.into_iter().enumerate() {
                    rust_final[address as usize - 256 + offset] = Some(value);
                }
            }
            assert_eq!(
                rust_final, original_final,
                "{name}: complete native dirty-write byte effects including exclusions"
            );
        }
    }
}
