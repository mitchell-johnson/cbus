//! Native-compatible database network electrical calculator.
//!
//! The arithmetic mirrors the independently accepted Python Toolkit
//! implementation and consumes an operator-supplied `cbusunits.xml`. It uses
//! database records only; no PCI traffic or physical measurement is involved.

use std::{collections::HashMap, path::Path};

use crate::{err, unitspec, Response, Server, Unit};

const MAX_UNITS: usize = 10_000;

#[derive(Debug, Clone)]
struct ElectricalUnit {
    current_drawn: i32,
    current_supplied: i32,
    switchable_drawn: i32,
    switchable_supplied: i32,
    impedance: i32,
    switchable_declared: bool,
    unit_types: Vec<String>,
}

#[derive(Debug, Clone, Copy)]
struct Limits {
    min_impedance: i32,
    max_impedance: i32,
    max_supply_current: i32,
}

struct Catalog {
    entries: HashMap<String, ElectricalUnit>,
    switchable_unit_types: std::collections::HashSet<String>,
    limits: Option<Limits>,
}

#[derive(Debug, Clone, Copy)]
struct ResultValues {
    passed: bool,
    supply: i32,
    consumption: i32,
    impedance: i64,
    known: usize,
    unknown: usize,
}

fn child<'a, 'input>(
    node: roxmltree::Node<'a, 'input>,
    name: &str,
) -> Option<roxmltree::Node<'a, 'input>> {
    node.children()
        .find(|child| child.is_element() && child.tag_name().name() == name)
}

fn text(node: roxmltree::Node<'_, '_>, name: &str) -> String {
    child(node, name)
        .and_then(|child| child.text())
        .unwrap_or("")
        .to_string()
}

fn number(node: roxmltree::Node<'_, '_>, name: &str) -> Result<i32, String> {
    let Some(value) = child(node, name).and_then(|child| child.text()) else {
        return Ok(0);
    };
    value
        .trim()
        .parse::<i32>()
        .map_err(|_| format!("Invalid catalogue integer field {name}"))
}

fn add_unit(
    node: roxmltree::Node<'_, '_>,
    entries: &mut HashMap<String, ElectricalUnit>,
) -> Result<(), String> {
    if let Some(subunits) = child(node, "SubUnits") {
        for unit in subunits
            .children()
            .filter(|node| node.is_element() && node.tag_name().name() == "Unit")
        {
            add_unit(unit, entries)?;
        }
        return Ok(());
    }
    let switchable_drawn = child(node, "CurrentDrawnSwitchablePowerSupply").is_some();
    let switchable_supplied = child(node, "CurrentSuppliedSwitchablePowerSupply").is_some();
    let unit_types = child(node, "FirmwareRevisions")
        .into_iter()
        .flat_map(|revisions| {
            revisions
                .children()
                .filter(|node| node.is_element() && node.tag_name().name() == "Revision")
        })
        .map(|revision| text(revision, "UnitType"))
        .collect::<Vec<_>>();
    let record = ElectricalUnit {
        current_drawn: number(node, "CurrentDrawn")?,
        current_supplied: number(node, "CurrentSupplied")?,
        switchable_drawn: number(node, "CurrentDrawnSwitchablePowerSupply")?,
        switchable_supplied: number(node, "CurrentSuppliedSwitchablePowerSupply")?,
        impedance: number(node, "Impedance")?,
        switchable_declared: switchable_drawn && switchable_supplied,
        unit_types,
    };
    let catalog_number = text(node, "CatalogNumber");
    if !catalog_number.is_empty() {
        entries.insert(catalog_number, record.clone());
    }
    for alternative in text(node, "AlternativeCatalogNumbers").split(';') {
        if !alternative.is_empty() {
            entries.insert(alternative.to_string(), record.clone());
        }
    }
    Ok(())
}

fn load_catalog(directory: &Path) -> Result<Catalog, String> {
    let xml = unitspec::read_xml_file(directory, "cbusunits.xml")?;
    let document = roxmltree::Document::parse(&xml)
        .map_err(|error| format!("Malformed calculator catalogue: {error}"))?;
    let root = document.root_element();
    if root.tag_name().name() != "CBusUnits" {
        return Err("cbusunits.xml is not a CBusUnits catalogue".to_string());
    }
    let mut entries = HashMap::new();
    if let Some(units) = child(root, "Units") {
        for unit in units
            .children()
            .filter(|node| node.is_element() && node.tag_name().name() == "Unit")
        {
            add_unit(unit, &mut entries)?;
        }
    }
    let switchable_unit_types = entries
        .values()
        .filter(|record| record.switchable_declared)
        .flat_map(|record| record.unit_types.iter().cloned())
        .collect();
    let limits = match child(root, "Calculator") {
        Some(calculator)
            if ["MinImpedance", "MaxImpedance", "MaxSupplyCurrent"]
                .iter()
                .all(|name| child(calculator, name).is_some()) =>
        {
            Some(Limits {
                min_impedance: number(calculator, "MinImpedance")?,
                max_impedance: number(calculator, "MaxImpedance")?,
                max_supply_current: number(calculator, "MaxSupplyCurrent")?,
            })
        }
        _ => None,
    };
    Ok(Catalog {
        entries,
        switchable_unit_types,
        limits,
    })
}

impl Catalog {
    fn lookup(&self, catalog_number: &str) -> Option<&ElectricalUnit> {
        if catalog_number.is_empty() {
            return None;
        }
        if let Some(record) = self.entries.get(catalog_number) {
            return Some(record);
        }
        let mut prefix = catalog_number.to_string();
        while !prefix.is_empty() {
            if let Some(record) = self.entries.get(&format!("{prefix}*")) {
                return Some(record);
            }
            prefix.pop();
        }
        None
    }

    fn calculate<'a>(&self, units: impl IntoIterator<Item = &'a Unit>) -> Option<ResultValues> {
        let mut supply = 0i32;
        let mut consumption = 0i32;
        let mut known = 0usize;
        let mut unknown = 0usize;
        let mut conductance = 0.0f64;
        for (index, unit) in units.into_iter().enumerate() {
            if index >= MAX_UNITS {
                return None;
            }
            let catalog_number = unit
                .fields
                .get("CatalogNumber")
                .map(String::as_str)
                .unwrap_or("");
            let Some(record) = self.lookup(catalog_number) else {
                unknown += 1;
                continue;
            };
            let unit_type = unit
                .fields
                .get("UnitType")
                .filter(|value| !value.is_empty())
                .map(String::as_str)
                .unwrap_or(&unit.unit_type);
            if self.switchable_unit_types.contains(unit_type) {
                let enabled = unit
                    .fields
                    .get("SwitchablePowerSupplyEnabled")
                    .is_some_and(|value| value.eq_ignore_ascii_case("true"));
                if enabled {
                    supply = supply.wrapping_add(record.switchable_supplied);
                } else {
                    consumption = consumption.wrapping_add(record.switchable_drawn);
                }
            } else {
                consumption = consumption.wrapping_add(record.current_drawn);
                supply = supply.wrapping_add(record.current_supplied);
            }
            if record.impedance >= 10 {
                conductance += 1.0 / f64::from(record.impedance);
            }
            let burden = unit
                .fields
                .get("Burden")
                .or_else(|| unit.fields.get("HardwareBurdenMarker"));
            if !matches!(
                unit_type.to_ascii_uppercase().as_str(),
                "KEYGL5" | "SENTEMP4"
            ) && burden.is_some_and(|value| value != "0")
            {
                conductance += 0.001;
            }
            known += 1;
        }
        if conductance == 0.0 {
            return None;
        }
        let exact_impedance = 1.0 / conductance;
        let impedance = (exact_impedance + 0.5).floor() as i64;
        let passed = self.limits.is_some_and(|limits| {
            consumption <= supply
                && supply <= limits.max_supply_current
                && exact_impedance >= f64::from(limits.min_impedance)
                && exact_impedance <= f64::from(limits.max_impedance)
                && unknown == 0
        });
        Some(ResultValues {
            passed,
            supply,
            consumption,
            impedance,
            known,
            unknown,
        })
    }
}

fn resolve_network<'a>(model: &'a Server, target: &'a str) -> Option<(&'a str, u8)> {
    if target.starts_with("//") {
        let parts = target
            .trim_start_matches('/')
            .split('/')
            .collect::<Vec<_>>();
        let [project, network] = parts.as_slice() else {
            return None;
        };
        return Some((project, network.parse().ok()?));
    }
    let network = target.parse().ok()?;
    Some((model.current.as_deref()?, network))
}

pub(crate) fn command(model: &Server, tag: &str, words: &[&str]) -> Response {
    if words.len() < 3 {
        return err(tag, 400, "400 Syntax Error.");
    }
    let Some(directory) = model.unitspec_dir.as_deref() else {
        return err(
            tag,
            408,
            "408 Operation failed: Calculation failed: No unit catalog available",
        );
    };
    let catalog = match load_catalog(directory) {
        Ok(catalog) => catalog,
        Err(_) => {
            return err(
                tag,
                408,
                "408 Operation failed: Calculation failed: No unit catalog available",
            )
        }
    };
    let Some((project_name, network_address)) = resolve_network(model, words[2]) else {
        return err(tag, 400, "400 Syntax Error.");
    };
    if model.current.as_deref() != Some(project_name) {
        return err(tag, 404, "404 Project not selected");
    }
    let Some(project) = model.projects.get(project_name) else {
        return err(
            tag,
            408,
            "408 Operation failed: Calculation failed: Can't find project",
        );
    };
    let Some(network) = project.networks.get(&network_address) else {
        return err(
            tag,
            408,
            "408 Operation failed: Calculation failed: Can't find network",
        );
    };
    let mut units = network.units.values().collect::<Vec<_>>();
    units.sort_by_key(|unit| unit.address);
    let Some(values) = catalog.calculate(units) else {
        return err(tag, 500, "500 Internal error.");
    };
    Response {
        tag: tag.to_string(),
        lines: vec![
            format!(
                "134-result: {}",
                if values.passed { "OK" } else { "FAILED" }
            ),
            format!("134-current_supply(mA)={}", values.supply),
            format!("134-current_consumption(mA)={}", values.consumption),
            format!("134-impedance(ohms)={:.1}", values.impedance as f64),
            format!("134-units_calculated={}", values.known),
        ],
        final_text: format!("134 units_not_calculated={}", values.unknown),
        status: 134,
    }
}
