//! Native per-object parameter and method access levels.
//!
//! C-Gate 3.4 checks an exposed parameter's read or write level (`Ck`) and a
//! method's run level (`Ch`) after the GET/SET/DO handler floor. The levels
//! come from one generated table, derived from the class hierarchy recorded in
//! `research/secondary-authorization-inventory.json` and replayed against
//! `native_cgate_object_authorization_probe.json`.

use crate::access::CgateAccessLevel;

#[path = "object_access_table.rs"]
mod table;

/// The cmqttd object kinds that native per-object levels apply to.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ObjectKind {
    Root,
    Project,
    Network,
    Application,
    Group,
    Unit,
}

/// A resolved object path. Components are borrowed from the command text.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ObjectPath<'a> {
    pub(crate) kind: ObjectKind,
    pub(crate) project: &'a str,
    pub(crate) network: Option<u8>,
    pub(crate) unit: Option<u8>,
}

/// Classify a native object path (`cgate`, `//P`, `//P/N`, `//P/N/A`,
/// `//P/N/A/G` or `//P/N/p/U`). Like the cmqttd unit handlers, leading
/// slashes are optional and a deeper unit child path (a terminal) resolves to
/// its unit, so an action on the unit can never bypass the unit's levels.
/// Other deeper child objects are not modeled by cmqttd and yield `None`.
pub(crate) fn object_path(path: &str) -> Option<ObjectPath<'_>> {
    if path.eq_ignore_ascii_case("cgate") {
        return Some(ObjectPath {
            kind: ObjectKind::Root,
            project: "",
            network: None,
            unit: None,
        });
    }
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').collect();
    if parts.iter().any(|part| part.is_empty()) {
        return None;
    }
    let number = |text: &str| text.parse::<u8>().ok();
    let network = match parts.get(1) {
        Some(text) => Some(number(text)?),
        None => None,
    };
    let (kind, unit) = match parts.as_slice() {
        [_] => (ObjectKind::Project, None),
        [_, _] => (ObjectKind::Network, None),
        [_, _, p, unit, ..] if p.eq_ignore_ascii_case("p") => {
            (ObjectKind::Unit, Some(number(unit)?))
        }
        [_, _, application] => {
            number(application)?;
            (ObjectKind::Application, None)
        }
        [_, _, application, group] => {
            number(application)?;
            number(group)?;
            (ObjectKind::Group, None)
        }
        _ => return None,
    };
    Some(ObjectPath {
        kind,
        project: parts[0],
        network,
        unit,
    })
}

fn parameter(kind: ObjectKind, name: &str) -> Option<(CgateAccessLevel, CgateAccessLevel)> {
    table::PARAMETERS
        .iter()
        .find(|(object, parameter, _, _)| *object == kind && parameter.eq_ignore_ascii_case(name))
        .map(|(_, _, read, write)| (*read, *write))
}

fn method(kind: ObjectKind, name: &str) -> Option<CgateAccessLevel> {
    table::METHODS
        .iter()
        .find(|(object, method, _)| *object == kind && method.eq_ignore_ascii_case(name))
        .map(|(_, _, level)| *level)
}

/// A method another object kind exposes. cmqttd DO dispatches by method name,
/// so a method sent to the wrong kind keeps the highest level it has anywhere
/// (fail closed) instead of reaching its handler unchecked.
fn foreign_method(name: &str) -> Option<CgateAccessLevel> {
    table::METHODS
        .iter()
        .filter(|(_, method, _)| method.eq_ignore_ascii_case(name))
        .map(|(_, _, level)| *level)
        .max()
}

/// The native denial for `GET`, `SET` or `DO` on `kind` at `level`, if any.
///
/// `words` is the whitespace-split command; `words[1]` is echoed exactly as
/// native C-Gate does. Parameters and methods outside the table are left to
/// the handler, which answers its own unknown-name error.
pub(crate) fn denial(
    kind: ObjectKind,
    verb: &str,
    words: &[&str],
    level: CgateAccessLevel,
) -> Option<String> {
    let target = words.get(1)?;
    let (required, action) = match verb {
        "GET" => words
            .iter()
            .skip(2)
            .flat_map(|word| word.split(','))
            .filter_map(|name| parameter(kind, name).map(|(read, _)| read))
            .max()
            .map(|read| (read, "for read"))?,
        "SET" if words.len() >= 4 => (parameter(kind, words[2])?.1, "for write"),
        "DO" if words.len() >= 3 => (
            method(kind, words[2]).or_else(|| foreign_method(words[2]))?,
            "to run method",
        ),
        _ => return None,
    };
    (level < required)
        .then(|| format!("420 Access denied: {target} (Insufficient access level {action})"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use CgateAccessLevel::{Admin, Connect, Max, Monitor, Operate, Program};

    #[test]
    fn paths_resolve_to_native_object_kinds() {
        let kind = |path| object_path(path).map(|path| path.kind);
        assert_eq!(kind("cgate"), Some(ObjectKind::Root));
        assert_eq!(kind("//P"), Some(ObjectKind::Project));
        assert_eq!(kind("//P/254"), Some(ObjectKind::Network));
        assert_eq!(kind("//P/254/56"), Some(ObjectKind::Application));
        assert_eq!(kind("//P/254/56/1"), Some(ObjectKind::Group));
        assert_eq!(kind("//P/254/p/4"), Some(ObjectKind::Unit));
        assert_eq!(object_path("//P/254/p/4").unwrap().unit, Some(4));
        // Unit handlers accept these spellings, so the levels must too.
        assert_eq!(kind("P/254/p/4"), Some(ObjectKind::Unit));
        assert_eq!(object_path("//P/254/p/4/1").unwrap().unit, Some(4));
        for unmodeled in ["//P/254/56/1/2", "//P/x", "//P//254", "//P/254/p", ""] {
            assert_eq!(kind(unmodeled), None, "{unmodeled}");
        }
    }

    #[test]
    fn table_levels_follow_the_native_class_hierarchy() {
        // CBusUnit overrides the base object's Max Address write with Program;
        // an application keeps the base Max.
        assert_eq!(
            parameter(ObjectKind::Unit, "address"),
            Some((Monitor, Program))
        );
        assert_eq!(
            parameter(ObjectKind::Application, "Address"),
            Some((Monitor, Max))
        );
        // `Bo` parameters apply to every object kind.
        for kind in [
            ObjectKind::Root,
            ObjectKind::Project,
            ObjectKind::Network,
            ObjectKind::Application,
            ObjectKind::Group,
            ObjectKind::Unit,
        ] {
            assert_eq!(parameter(kind, "EventLevel"), Some((Monitor, Operate)));
            assert_eq!(parameter(kind, "State"), Some((Monitor, Max)));
        }
        // Computed network names resolve from their static initializer.
        assert_eq!(
            parameter(ObjectKind::Network, "DBUnitAddressesNew"),
            Some((Monitor, Max))
        );
        assert_eq!(method(ObjectKind::Network, "unravel"), Some(Program));
        assert_eq!(method(ObjectKind::Unit, "PSync"), Some(Admin));
        assert_eq!(method(ObjectKind::Group, "On"), Some(Operate));
        // A unit method sent to a network keeps its unit level.
        assert_eq!(method(ObjectKind::Network, "PSync"), None);
        assert_eq!(foreign_method("psync"), Some(Admin));
    }

    #[test]
    fn denial_text_names_the_object_as_sent() {
        let words = ["GET", "//P/254", "Name,TxQ"];
        assert_eq!(
            denial(ObjectKind::Network, "GET", &words, Admin).as_deref(),
            Some("420 Access denied: //P/254 (Insufficient access level for read)")
        );
        assert_eq!(denial(ObjectKind::Network, "GET", &words, Program), None);
        let words = ["SET", "//P/254/p/5", "Address", "40"];
        assert_eq!(
            denial(ObjectKind::Unit, "SET", &words, Admin).as_deref(),
            Some("420 Access denied: //P/254/p/5 (Insufficient access level for write)")
        );
        let words = ["DO", "//P/254/p/4", "PSync"];
        assert_eq!(
            denial(ObjectKind::Unit, "DO", &words, Operate).as_deref(),
            Some("420 Access denied: //P/254/p/4 (Insufficient access level to run method)")
        );
        // Unknown names fall through to the handler.
        let words = ["SET", "//P/254/p/5", "Colour", "1"];
        assert_eq!(denial(ObjectKind::Unit, "SET", &words, Connect), None);
    }

    /// The generated table is exactly the inventory's derived `object_levels`.
    #[test]
    fn generated_table_matches_the_inventory() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/research/secondary-authorization-inventory.json"
        );
        let inventory: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let kind = |name: &str| match name {
            "cgate" => ObjectKind::Root,
            "project" => ObjectKind::Project,
            "network" => ObjectKind::Network,
            "application" => ObjectKind::Application,
            "group" => ObjectKind::Group,
            "unit" => ObjectKind::Unit,
            other => panic!("unknown object kind {other}"),
        };
        let (mut parameters, mut methods) = (0, 0);
        for row in inventory["object_levels"].as_array().unwrap() {
            let object = kind(row["object"].as_str().unwrap());
            let name = row["name"].as_str().unwrap();
            let level = CgateAccessLevel::parse(row["required_level"].as_str().unwrap());
            match row["access"].as_str().unwrap() {
                "run" => {
                    methods += 1;
                    assert_eq!(method(object, name), Some(level), "{name}");
                }
                "read" => {
                    parameters += 1;
                    assert_eq!(parameter(object, name).unwrap().0, level, "{name}");
                }
                _ => assert_eq!(parameter(object, name).unwrap().1, level, "{name}"),
            }
        }
        assert_eq!(parameters, table::PARAMETERS.len());
        assert_eq!(methods, table::METHODS.len());
    }
}
