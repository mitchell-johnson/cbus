//! Pure move planner for `NET UNRAVEL`, `NET UNRAVELUNIT` and `DO UNRAVEL`.
//!
//! The rules follow owned C-Gate 3.4.0 build 2001 captures against the
//! research bus fixture (`testdata/fixtures/native_cgate_unravel_cases.json`):
//! selected addresses are processed in ascending order; a healthy singleton
//! stays put; address 255 is cleared; an ordinary duplicate keeps the local
//! PCI at its own address, else with MATCHDB the serial the database places
//! there (none when no serial matches), else the numerically lowest serial.
//! Moving serials are processed in descending numeric order. MATCHDB sends a
//! serial with one database address there, first displacing a single
//! physically present occupant to a free address. Free addresses are the
//! lowest in 2..=254 absent from the network and the database, then absent
//! from the network only.
//!
//! Deliberate refusals where native behavior is unobserved or unsafe: an
//! occupied database target holding several units, a target that is the
//! local PCI, or an occupant that is itself a planned arrival.

use super::*;

/// One address write, in execution order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct UnravelMove {
    /// The selected address whose processing produced this move.
    pub(super) group: u8,
    pub(super) source: u8,
    pub(super) serial: String,
    pub(super) destination: u8,
    /// Set on a database move whose destination was occupied at planning:
    /// the occupant that an earlier displacement move must have removed.
    pub(super) displaced: Option<String>,
}

#[derive(Debug, Default, PartialEq, Eq)]
pub(super) struct UnravelPlan {
    pub(super) moves: Vec<UnravelMove>,
    /// Duplicate addresses whose keeper remains, as (address, serial); the
    /// local PCI kept at its own address is not listed.
    pub(super) kept: Vec<(u8, String)>,
}

pub(super) struct UnravelInputs<'a> {
    pub(super) before: &'a BTreeMap<u8, Vec<String>>,
    /// Target-network database units as (address, serial text).
    pub(super) database: &'a [(u8, String)],
    pub(super) selection: Option<&'a HashSet<u8>>,
    pub(super) match_database: bool,
    pub(super) local: u8,
    pub(super) direct: bool,
    pub(super) local_serial: Option<&'a str>,
}

fn serial_order(serial: &str) -> (u32, u32) {
    parse_native_serial(serial)
        .map(|parsed| (parsed.first, parsed.second))
        .unwrap_or((u32::MAX, u32::MAX))
}

/// Plan every move or return the 409 refusal text.
pub(super) fn plan_unravel(inputs: &UnravelInputs<'_>) -> Result<UnravelPlan, String> {
    let database_addresses = |serial: &str| {
        inputs
            .database
            .iter()
            .filter(|(_, candidate)| {
                parse_native_serial(candidate)
                    .ok()
                    .is_some_and(|parsed| parsed.known && parsed.canonical == serial)
            })
            .map(|(address, _)| *address)
            .collect::<Vec<_>>()
    };
    let assigned = inputs
        .database
        .iter()
        .map(|(address, _)| *address)
        .collect::<HashSet<_>>();
    let excluded = |address: u8| inputs.direct && address == inputs.local;
    let free = |occupants: &BTreeMap<u8, Vec<String>>| {
        (2u8..=254)
            .find(|candidate| {
                !excluded(*candidate)
                    && !occupants.contains_key(candidate)
                    && !assigned.contains(candidate)
            })
            .or_else(|| {
                (2u8..=254)
                    .find(|candidate| !excluded(*candidate) && !occupants.contains_key(candidate))
            })
            .ok_or_else(|| "409 No free unit address is available for unravel".to_string())
    };
    fn relocate(
        occupants: &mut BTreeMap<u8, Vec<String>>,
        serial: &str,
        source: u8,
        destination: u8,
    ) {
        if let Some(serials) = occupants.get_mut(&source) {
            serials.retain(|candidate| candidate != serial);
            if serials.is_empty() {
                occupants.remove(&source);
            }
        }
        occupants
            .entry(destination)
            .or_default()
            .push(serial.to_string());
    }

    let mut occupants = inputs.before.clone();
    let mut moved = HashSet::<String>::new();
    let mut plan = UnravelPlan::default();
    let selected = inputs
        .before
        .keys()
        .copied()
        .filter(|address| {
            inputs
                .selection
                .is_none_or(|chosen| chosen.contains(address))
        })
        .collect::<Vec<_>>();
    for group in selected {
        let Some(serials) = occupants.get(&group).cloned() else {
            continue;
        };
        if group != 255 && serials.len() == 1 {
            continue;
        }
        let keeper = if group == 255 {
            None
        } else if inputs.direct && group == inputs.local {
            inputs.local_serial.map(str::to_string)
        } else if inputs.match_database {
            serials
                .iter()
                .find(|serial| database_addresses(serial) == [group])
                .cloned()
        } else {
            serials
                .iter()
                .min_by_key(|serial| serial_order(serial))
                .cloned()
        };
        let mut moving = serials
            .into_iter()
            .filter(|serial| keeper.as_ref() != Some(serial))
            .collect::<Vec<_>>();
        moving.sort_by_key(|serial| std::cmp::Reverse(serial_order(serial)));
        for serial in moving {
            let targets = if inputs.match_database {
                database_addresses(&serial)
            } else {
                Vec::new()
            };
            let database_target = match targets.as_slice() {
                [target] if (2..=254).contains(target) && *target != group => Some(*target),
                _ => None,
            };
            let mut displaced = None;
            let destination = if let Some(target) = database_target {
                if excluded(target) {
                    return Err(format!(
                        "409 Database address {target} for serial {serial} is the local PCI"
                    ));
                }
                match occupants.get(&target).map(Vec::as_slice) {
                    None => {}
                    Some([occupant])
                        if !moved.contains(occupant)
                            && inputs
                                .before
                                .get(&target)
                                .is_some_and(|present| present.contains(occupant)) =>
                    {
                        // Native clears the database target by moving its
                        // occupant to the lowest free address first.
                        let occupant = occupant.clone();
                        let spare = free(&occupants)?;
                        relocate(&mut occupants, &occupant, target, spare);
                        moved.insert(occupant.clone());
                        plan.moves.push(UnravelMove {
                            group,
                            source: target,
                            serial: occupant.clone(),
                            destination: spare,
                            displaced: None,
                        });
                        displaced = Some(occupant);
                    }
                    Some(_) => {
                        return Err(format!(
                            "409 Database address {target} for serial {serial} cannot be cleared unambiguously"
                        ))
                    }
                }
                target
            } else {
                free(&occupants)?
            };
            let source = group;
            relocate(&mut occupants, &serial, source, destination);
            moved.insert(serial.clone());
            plan.moves.push(UnravelMove {
                group,
                source,
                serial,
                destination,
                displaced,
            });
        }
        // Native reports no "left in place" line for the local PCI itself.
        if let Some(keeper) = keeper.filter(|_| !(inputs.direct && group == inputs.local)) {
            plan.kept.push((group, keeper));
        }
    }
    Ok(plan)
}

#[cfg(test)]
mod native_capture_tests {
    use super::*;

    const PCI_SERIAL: &str = "100966.1187";

    fn fixture() -> serde_json::Value {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../testdata/fixtures/native_cgate_unravel_cases.json"
        );
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
    }

    /// Replays every owned native capture through the pure planner: the
    /// final topology and the native move order must match exactly.
    #[test]
    fn planner_matches_every_native_unravel_capture() {
        let captured = fixture();
        let cases = captured["cases"].as_object().unwrap();
        assert_eq!(cases.len(), 14);
        for (name, case) in cases {
            let setup = &case["setup"];
            let mut before = BTreeMap::<u8, Vec<String>>::new();
            before.insert(16, vec![PCI_SERIAL.to_string()]);
            for node in setup["nodes"].as_array().unwrap() {
                before
                    .entry(node["address"].as_u64().unwrap() as u8)
                    .or_default()
                    .push(node["serial"].as_str().unwrap().to_string());
            }
            for serials in before.values_mut() {
                serials.sort();
            }
            let database = setup["database"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(address, serial)| {
                    (
                        address.parse::<u8>().unwrap(),
                        serial.as_str().unwrap().to_string(),
                    )
                })
                .collect::<Vec<_>>();
            let words = setup["command"]
                .as_str()
                .unwrap()
                .split_whitespace()
                .collect::<Vec<_>>();
            let selection = words[3]
                .split(',')
                .map(|unit| unit.parse::<u8>().unwrap())
                .collect::<HashSet<_>>();
            let plan = plan_unravel(&UnravelInputs {
                before: &before,
                database: &database,
                selection: Some(&selection),
                match_database: words.get(4) == Some(&"MATCHDB"),
                local: 16,
                direct: true,
                local_serial: Some(PCI_SERIAL),
            })
            .unwrap_or_else(|error| panic!("{name}: {error}"));

            let mut after = before.clone();
            for planned in &plan.moves {
                after
                    .get_mut(&planned.source)
                    .unwrap()
                    .retain(|serial| *serial != planned.serial);
                after
                    .entry(planned.destination)
                    .or_default()
                    .push(planned.serial.clone());
            }
            let observed = after
                .iter()
                .flat_map(|(address, serials)| {
                    serials
                        .iter()
                        .filter(|serial| *serial != PCI_SERIAL)
                        .map(move |serial| (serial.clone(), *address))
                })
                .collect::<BTreeMap<_, _>>();
            let expected = case["after_topology"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(serial, address)| (serial.clone(), address.as_u64().unwrap() as u8))
                .collect::<BTreeMap<_, _>>();
            assert_eq!(observed, expected, "{name}");

            let native_moves = case["reply"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(|line| {
                    let line = line.as_str().unwrap();
                    let rest = line.strip_prefix("120-Unravel: Readdressed unit ")?;
                    let (_, rest) = rest.split_once("from address ")?;
                    let (source, rest) = rest.split_once(' ')?;
                    let (_, rest) = rest.split_once("to address ")?;
                    let destination = rest.split_once(' ')?.0;
                    Some((source.parse::<u8>().ok()?, destination.parse::<u8>().ok()?))
                })
                .collect::<Vec<_>>();
            assert_eq!(
                plan.moves
                    .iter()
                    .map(|planned| (planned.source, planned.destination))
                    .collect::<Vec<_>>(),
                native_moves,
                "{name}"
            );
            let native_kept = case["reply"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|line| line.as_str().unwrap().ends_with("left in place."))
                .count();
            assert_eq!(plan.kept.len(), native_kept, "{name}");
        }
    }

    #[test]
    fn unobserved_or_unsafe_targets_are_refused() {
        let mut before = BTreeMap::new();
        before.insert(6, vec!["1.2".to_string(), "1.3".to_string()]);
        before.insert(255, vec!["1.1".to_string()]);
        let database = [(6, "1.1".to_string())];
        let only_255 = HashSet::from([255]);
        let inputs = UnravelInputs {
            before: &before,
            database: &database,
            selection: Some(&only_255),
            match_database: true,
            local: 16,
            direct: true,
            local_serial: None,
        };
        assert!(plan_unravel(&inputs)
            .unwrap_err()
            .contains("cannot be cleared unambiguously"));
        let database = [(16, "1.1".to_string())];
        let inputs = UnravelInputs {
            database: &database,
            ..inputs
        };
        assert!(plan_unravel(&inputs).unwrap_err().contains("local PCI"));
        // Without MATCHDB an ordinary duplicate keeps the numerically lowest
        // serial, not the lexicographically lowest.
        let mut before = BTreeMap::new();
        before.insert(20, vec!["5.1000".to_string(), "5.999".to_string()]);
        let plan = plan_unravel(&UnravelInputs {
            before: &before,
            database: &[],
            selection: None,
            match_database: false,
            local: 16,
            direct: true,
            local_serial: None,
        })
        .unwrap();
        assert_eq!(plan.kept, vec![(20, "5.999".to_string())]);
        assert_eq!(plan.moves[0].serial, "5.1000");
        assert_eq!(plan.moves[0].destination, 2);
    }
}
