//! Native-shaped C-Gate ACCESS state with cmqttd safety boundaries.
//!
//! The vendor daemon stores user passwords in clear text and prints them from
//! `ACCESS LIST`.  cmqttd deliberately stores only a one-way credential
//! digest and renders the password field as `<redacted>`.  Address entries
//! retain the operator's spelling for native-shaped listings while keeping a
//! validated, resolved address set for connection matching.

use crate::auth;
use serde::{Deserialize, Serialize};
use std::net::{IpAddr, Ipv4Addr};

/// Ordered native C-Gate access levels.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
pub(crate) enum CgateAccessLevel {
    #[default]
    None,
    Connect,
    Monitor,
    Operate,
    Admin,
    Program,
    Debug,
    Clipsal,
    Max,
}

impl CgateAccessLevel {
    pub(crate) fn parse(value: &str) -> Self {
        match value.to_ascii_lowercase().as_str() {
            "connect" => Self::Connect,
            "monitor" => Self::Monitor,
            "operate" => Self::Operate,
            "admin" => Self::Admin,
            "program" => Self::Program,
            "debug" => Self::Debug,
            "clipsal" => Self::Clipsal,
            "max" => Self::Max,
            _ => Self::None,
        }
    }

    pub(crate) const fn name(self) -> &'static str {
        match self {
            Self::None => "None",
            Self::Connect => "Connect",
            Self::Monitor => "Monitor",
            Self::Operate => "Operate",
            Self::Admin => "Admin",
            Self::Program => "Program",
            Self::Debug => "Debug",
            Self::Clipsal => "Clipsal",
            Self::Max => "Max",
        }
    }

    pub(crate) fn can_manage_access(self) -> bool {
        self >= Self::Clipsal
    }
}

/// Handler-level floors observed on an owned C-Gate 3.4.0.2001 loopback
/// oracle. These entries name only the commands probed with a syntactically
/// useful invocation in `native_cgate_authorization_probe.json`. A 420 on
/// admitted lower sessions and a non-420 response at the floor establish
/// dispatch order (the native None session has earlier parser quirks for DB
/// verbs). These probes do not prove that an absent project/device would
/// have completed the
/// handler's later authorization and physical checks.
///
/// Keep this a partial matrix until the remaining native handlers have
/// independent cases. The recovery-token gate is a separate cmqttd policy.
pub(crate) const NATIVE_PROBED_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    ("NOOP", CgateAccessLevel::Connect),
    ("APIVER", CgateAccessLevel::Monitor),
    ("HELP", CgateAccessLevel::Monitor),
    ("EVENT", CgateAccessLevel::Monitor),
    ("GET", CgateAccessLevel::Monitor),
    ("DBGET", CgateAccessLevel::Monitor),
    ("DBGETXML", CgateAccessLevel::Monitor),
    ("BROADCAST_EVENT", CgateAccessLevel::Operate),
    ("SESSION_ID", CgateAccessLevel::Operate),
    ("DBSET", CgateAccessLevel::Operate),
    ("LIGHTING ON", CgateAccessLevel::Operate),
    ("LIGHTING OFF", CgateAccessLevel::Operate),
    ("LIGHTING LABEL", CgateAccessLevel::Operate),
    ("SCENE PLAY", CgateAccessLevel::Operate),
    ("AIRCON REFRESH", CgateAccessLevel::Operate),
    ("AUDIO CURRENT_FEED", CgateAccessLevel::Operate),
    ("SECURITY STATUS_REQUEST", CgateAccessLevel::Operate),
    ("EREPORT MESSAGE", CgateAccessLevel::Operate),
    ("PROJECT LIST", CgateAccessLevel::Admin),
    ("PROJECT USE", CgateAccessLevel::Admin),
    ("PROJECT NEW", CgateAccessLevel::Admin),
    ("CONFIG GET", CgateAccessLevel::Admin),
    ("CONFIG SET", CgateAccessLevel::Admin),
    ("DBSETXML", CgateAccessLevel::Admin),
    ("NET LIST", CgateAccessLevel::Program),
    ("NET PINGU", CgateAccessLevel::Program),
    ("FILE DIR", CgateAccessLevel::Program),
    ("FILE MKDIR", CgateAccessLevel::Program),
    ("CGL EXPORT", CgateAccessLevel::Program),
    ("DALI SESSION LIST", CgateAccessLevel::Program),
    ("PP LOCK", CgateAccessLevel::Clipsal),
];

/// Additional independent 2026-09-28 native-role invocations. The retained
/// fixture records all nine admitted roles for each path, including a useful
/// non-420 handler response at the floor. Missing objects prevent bus I/O;
/// they do not establish the access level for a later successful device send.
pub(crate) const NATIVE_PROBED_ADDITIONAL_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    ("PROJECT DIR", CgateAccessLevel::Admin),
    ("PROJECT DIRFULL", CgateAccessLevel::Admin),
    ("PROJECT COPY", CgateAccessLevel::Admin),
    ("PROJECT DELETE", CgateAccessLevel::Admin),
    ("PROJECT LOAD", CgateAccessLevel::Admin),
    ("PROJECT RENAME", CgateAccessLevel::Admin),
    ("PROJECT REPAIR", CgateAccessLevel::Admin),
    ("PROJECT SAVE", CgateAccessLevel::Admin),
    ("PROJECT START", CgateAccessLevel::Admin),
    ("PROJECT STOP", CgateAccessLevel::Admin),
    ("CONFIG INFO", CgateAccessLevel::Admin),
    ("CONFIG OBGET", CgateAccessLevel::Admin),
    ("DBTAGLIST", CgateAccessLevel::Admin),
    ("DBSAVE", CgateAccessLevel::Admin),
    ("DBLOAD", CgateAccessLevel::Operate),
    ("DBVALIDATE", CgateAccessLevel::Operate),
    ("DBVERIFY", CgateAccessLevel::Admin),
    ("DBNETWORKPATH", CgateAccessLevel::Admin),
    ("DBSETSAFE", CgateAccessLevel::Operate),
    ("DBUPDATE", CgateAccessLevel::Admin),
    ("DBCOPY", CgateAccessLevel::Operate),
    ("DBDELETE", CgateAccessLevel::Operate),
    ("DBCREATE", CgateAccessLevel::Admin),
    ("NET LIST_ALL", CgateAccessLevel::Program),
    ("NET OPEN", CgateAccessLevel::Program),
    ("NET CLOSE", CgateAccessLevel::Program),
    ("NET SYNC", CgateAccessLevel::Program),
    ("NET CLOCKS", CgateAccessLevel::Program),
    ("NET CHECKUNIT", CgateAccessLevel::Program),
    ("NET SET_PROJECT_IDENTIFY", CgateAccessLevel::Program),
    ("PORT LIST", CgateAccessLevel::Program),
    ("PORT IFLIST", CgateAccessLevel::Program),
    ("TREE", CgateAccessLevel::Monitor),
    ("TREEXML", CgateAccessLevel::Monitor),
    ("TREEXMLDETAIL", CgateAccessLevel::Monitor),
    ("SHOW OBJECTS", CgateAccessLevel::Monitor),
    ("CGL IMPORT", CgateAccessLevel::Program),
    ("DALI CATALOG LIST", CgateAccessLevel::Program),
    ("FILE LS", CgateAccessLevel::Program),
    ("FILE SHA256", CgateAccessLevel::Program),
    ("REPOSITORY LIST", CgateAccessLevel::Admin),
    ("REPOSITORY USE", CgateAccessLevel::Admin),
    ("LOCK", CgateAccessLevel::Operate),
    ("UNLOCK", CgateAccessLevel::Operate),
    ("GETSTATE", CgateAccessLevel::Monitor),
    ("SET", CgateAccessLevel::Operate),
    ("DO", CgateAccessLevel::Operate),
    ("LIGHTING RAMP", CgateAccessLevel::Operate),
    ("TRIGGER EVENT", CgateAccessLevel::Program),
    ("ENABLE SET", CgateAccessLevel::Operate),
    ("CLOCK TIME", CgateAccessLevel::Operate),
    ("TEMPERATURE BROADCAST", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT STATUS_REQUEST", CgateAccessLevel::Operate),
    ("SHORTMESSAGE REFRESH", CgateAccessLevel::Operate),
    ("SESSION_ID ALL", CgateAccessLevel::Operate),
    ("EVENT_CHANNEL LIST", CgateAccessLevel::Program),
    ("EVENT_CHANNEL SUB", CgateAccessLevel::Program),
    ("EVENT_CHANNEL UNSUB", CgateAccessLevel::Program),
];

/// Programming/session/queue entry floors captured independently on the pinned
/// native service. Missing session/unit probes never attach a physical network.
/// These floors do not establish successful device programming at that role.
pub(crate) const NATIVE_PROBED_PROGRAMMING_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    ("PP UNLOCK", CgateAccessLevel::Clipsal),
    ("PP CANCEL_LOCK", CgateAccessLevel::Clipsal),
    ("PP START", CgateAccessLevel::Clipsal),
    ("PP END", CgateAccessLevel::Clipsal),
    ("PP UNITS", CgateAccessLevel::Clipsal),
    ("PP NEW", CgateAccessLevel::Clipsal),
    ("PP DEBUG", CgateAccessLevel::Clipsal),
    ("PP LOAD", CgateAccessLevel::Clipsal),
    ("PP SAVE", CgateAccessLevel::Clipsal),
    ("PP SAVE_TO_SOURCE", CgateAccessLevel::Clipsal),
    ("PP SET", CgateAccessLevel::Clipsal),
    ("PP GET", CgateAccessLevel::Clipsal),
    ("PP INFO", CgateAccessLevel::Clipsal),
    ("PP LIST_LOCK", CgateAccessLevel::Clipsal),
    ("PP LOAD_FROM_FILE", CgateAccessLevel::Clipsal),
    ("PP GET_UNIT_SPEC", CgateAccessLevel::Clipsal),
    ("PP GET_UNIT_CATALOG", CgateAccessLevel::Clipsal),
    ("PP RELOAD_CATALOG", CgateAccessLevel::Clipsal),
    ("PP CATALOG_INFO", CgateAccessLevel::Clipsal),
    ("PP LIST_CATALOG_NUMBERS", CgateAccessLevel::Clipsal),
    ("PP GET_RAW_DATA", CgateAccessLevel::Clipsal),
    ("PP SET_RAW_DATA", CgateAccessLevel::Clipsal),
    ("PP COPY", CgateAccessLevel::Clipsal),
    ("PP QUICKGET", CgateAccessLevel::Clipsal),
    ("PP RESET_TO_DEFAULTS", CgateAccessLevel::Clipsal),
    ("PP PATCH_VERSION", CgateAccessLevel::Clipsal),
    ("PP WRITE_PATCH", CgateAccessLevel::Clipsal),
    ("PROGRAMMER CREATE", CgateAccessLevel::Program),
    ("PROGRAMMER LIST", CgateAccessLevel::Program),
    ("PROGRAMMER STATUS", CgateAccessLevel::Program),
    ("PROGRAMMER DELETE", CgateAccessLevel::Program),
    ("PROGRAMMER TRIGGER", CgateAccessLevel::Program),
    ("PROGRAMMER TEST", CgateAccessLevel::Program),
    ("PROGRAMMER ADD_INSTRUCTION", CgateAccessLevel::Program),
    ("PROGRAMMER CANCEL_INSTRUCTION", CgateAccessLevel::Program),
    ("DEPLOY_QUEUE ADD", CgateAccessLevel::Program),
    ("DEPLOY_QUEUE LIST", CgateAccessLevel::Program),
    ("DEPLOY_QUEUE DELETE", CgateAccessLevel::Program),
    ("DEPLOY_QUEUE DELETE_ALL", CgateAccessLevel::Program),
    ("DEPLOY_QUEUE RETRY", CgateAccessLevel::Program),
];

/// Entry floors captured for exact media and security invocations on the
/// owned native loopback oracle. Each target names an absent project, so this
/// establishes the handler gate without claiming a successful C-Bus send.
pub(crate) const NATIVE_PROBED_MEDIA_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    ("AUDIO DYNAMIC_1", CgateAccessLevel::Operate),
    ("AUDIO DYNAMIC_2", CgateAccessLevel::Operate),
    ("AUDIO HIGH_PRIORITY", CgateAccessLevel::Operate),
    ("AUDIO MUTE", CgateAccessLevel::Operate),
    ("AUDIO NEXT_FEED", CgateAccessLevel::Operate),
    ("AUDIO NEXT_LANGUAGE", CgateAccessLevel::Operate),
    ("AUDIO OFF", CgateAccessLevel::Operate),
    ("AUDIO ON", CgateAccessLevel::Operate),
    ("AUDIO OUTPUT_COMMON_CONTROL", CgateAccessLevel::Operate),
    (
        "AUDIO OUTPUT_DEVICE_STATUS_REQUEST",
        CgateAccessLevel::Operate,
    ),
    ("AUDIO OUTPUT_ERROR_CODE", CgateAccessLevel::Operate),
    ("AUDIO PREVIOUS_FEED", CgateAccessLevel::Operate),
    ("AUDIO RAMP", CgateAccessLevel::Operate),
    ("AUDIO REQUEST_CURRENT_FEED", CgateAccessLevel::Operate),
    ("AUDIO SET_FEED", CgateAccessLevel::Operate),
    ("AUDIO TERMINATERAMP", CgateAccessLevel::Operate),
    ("AUDIO ZONE_DESCRIPTOR_REQUEST", CgateAccessLevel::Operate),
    ("AUDIO ZONE_FEED_LABEL_REQUEST", CgateAccessLevel::Operate),
    ("SECURITY ARM", CgateAccessLevel::Operate),
    ("SECURITY DISPLAY_MESSAGE", CgateAccessLevel::Operate),
    ("SECURITY EMULATE_KEYPAD", CgateAccessLevel::Operate),
    ("SECURITY RAISE_ALARM", CgateAccessLevel::Operate),
    ("SECURITY REQUEST_ZONE_NAME", CgateAccessLevel::Operate),
    ("SECURITY TAMPER", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT CATEGORY_NAME", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT ENUMERATE", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT ENUMERATION_SIZE", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT FORWARD", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT NEXT_CATEGORY", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT NEXT_SELECTION", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT NEXT_TRACK", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT PAUSE", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT PLAY", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT REPEAT", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT REWIND", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SELECTION_NAME", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SET_CATEGORY", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SET_SELECTION", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SET_TRACK", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SHUFFLE", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT SOURCE_POWER", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT STOP", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT TOTAL_TRACKS", CgateAccessLevel::Operate),
    ("MEDIATRANSPORT TRACK_NAME", CgateAccessLevel::Operate),
];

/// Additional configuration, file, project, network, label and measurement
/// handler floors captured on the pinned native loopback service. Missing
/// objects prevent physical I/O; a non-420 response at the floor proves only
/// that this invocation reached the later parser or handler stage.
pub(crate) const NATIVE_PROBED_ADMIN_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    ("CONFIG OBSET", CgateAccessLevel::Admin),
    ("CONFIG OBRESET", CgateAccessLevel::Admin),
    ("CONFIG LOAD", CgateAccessLevel::Admin),
    ("CONFIG SAVE", CgateAccessLevel::Admin),
    ("FILE DELETE", CgateAccessLevel::Program),
    ("FILE DOWNLOAD", CgateAccessLevel::Program),
    ("PROJECT CLOSE", CgateAccessLevel::Admin),
    ("PROJECT RESTORE", CgateAccessLevel::Admin),
    ("NET DELETE", CgateAccessLevel::Program),
    ("NET FLUSH", CgateAccessLevel::Program),
    ("NET LEARN", CgateAccessLevel::Program),
    ("NET LOAD", CgateAccessLevel::Program),
    ("NET RENAME", CgateAccessLevel::Program),
    ("NET SAVE", CgateAccessLevel::Program),
    ("NET SYNCNEW", CgateAccessLevel::Program),
    ("NET UNRAVEL", CgateAccessLevel::Program),
    ("NET UNRAVELUNIT", CgateAccessLevel::Program),
    ("LABEL CLEAR", CgateAccessLevel::Program),
    ("LABEL CLEAREDLT", CgateAccessLevel::Program),
    ("LABEL KFIGET", CgateAccessLevel::Program),
    ("LABEL KFISET", CgateAccessLevel::Program),
    ("MEASUREMENT DATA", CgateAccessLevel::Operate),
];

/// Complete bounded application invocations captured on an absent native
/// project. These are entry floors only; no application message reached a bus.
pub(crate) const NATIVE_PROBED_APPLICATION_COMMANDS: &[(&str, CgateAccessLevel)] = &[
    (
        "AIRCON SET_HUMIDITY_SETBACK_LIMIT",
        CgateAccessLevel::Operate,
    ),
    (
        "AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT",
        CgateAccessLevel::Operate,
    ),
    (
        "AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT",
        CgateAccessLevel::Operate,
    ),
    (
        "AIRCON SET_HVAC_LOWER_GUARD_LIMIT",
        CgateAccessLevel::Operate,
    ),
    ("AIRCON SET_HVAC_SETBACK_LIMIT", CgateAccessLevel::Operate),
    (
        "AIRCON SET_HVAC_UPPER_GUARD_LIMIT",
        CgateAccessLevel::Operate,
    ),
    ("AIRCON SET_WARD_OFF", CgateAccessLevel::Operate),
    ("AIRCON SET_WARD_ON", CgateAccessLevel::Operate),
    ("AIRCON SET_ZONE_HUMIDITY_MODE", CgateAccessLevel::Operate),
    ("AIRCON SET_ZONE_HVAC_MODE", CgateAccessLevel::Operate),
    ("CLOCK DATE", CgateAccessLevel::Operate),
    ("CLOCK REQUEST_REFRESH", CgateAccessLevel::Operate),
    ("ENABLE LABEL", CgateAccessLevel::Operate),
    ("ENABLE REMOVE", CgateAccessLevel::Operate),
    ("LIGHTING UNICODELABEL", CgateAccessLevel::Operate),
    ("LIGHTING TERMINATERAMP", CgateAccessLevel::Operate),
    ("SHORTMESSAGE SEND", CgateAccessLevel::Operate),
    ("TELEPHONY CLEAR_DIVERSION", CgateAccessLevel::Operate),
    ("TELEPHONY DIVERT", CgateAccessLevel::Operate),
    (
        "TELEPHONY ISOLATE_SECONDARY_OUTLET",
        CgateAccessLevel::Operate,
    ),
    (
        "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
        CgateAccessLevel::Operate,
    ),
    ("TELEPHONY REJECT_INCOMING_CALL", CgateAccessLevel::Operate),
    ("TRIGGER LABEL", CgateAccessLevel::Program),
    ("TRIGGER UNICODELABEL", CgateAccessLevel::Program),
];

pub(crate) fn native_probed_commands(
) -> impl Iterator<Item = &'static (&'static str, CgateAccessLevel)> {
    NATIVE_PROBED_COMMANDS
        .iter()
        .chain(NATIVE_PROBED_ADDITIONAL_COMMANDS.iter())
        .chain(NATIVE_PROBED_PROGRAMMING_COMMANDS.iter())
        .chain(NATIVE_PROBED_MEDIA_COMMANDS.iter())
        .chain(NATIVE_PROBED_ADMIN_COMMANDS.iter())
        .chain(NATIVE_PROBED_APPLICATION_COMMANDS.iter())
}

/// Longest matching native-observed command path. The caller supplies
/// uppercase whitespace-delimited words from the C-Gate parser.
pub(crate) fn native_minimum_for(upper: &[String]) -> Option<CgateAccessLevel> {
    for len in (1..=upper.len().min(3)).rev() {
        let path = upper[..len].join(" ");
        if let Some((_, level)) = native_probed_commands().find(|(candidate, _)| *candidate == path)
        {
            return Some(*level);
        }
    }
    None
}

/// One durable access-list row. User credentials are never retained in
/// plaintext. The digest is bound to the case-sensitive username so equal
/// passwords do not have equal stored values across users.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) enum AccessEntry {
    User {
        username: String,
        credential_digest: [u8; 32],
        level: CgateAccessLevel,
    },
    Interface {
        address: String,
        #[serde(default)]
        resolved: Vec<IpAddr>,
        level: CgateAccessLevel,
    },
    Remote {
        address: String,
        #[serde(default)]
        resolved: Vec<IpAddr>,
        level: CgateAccessLevel,
    },
}

impl AccessEntry {
    pub(crate) const fn level(&self) -> CgateAccessLevel {
        match self {
            Self::User { level, .. }
            | Self::Interface { level, .. }
            | Self::Remote { level, .. } => *level,
        }
    }

    pub(crate) fn list_text(&self) -> String {
        match self {
            Self::User {
                username, level, ..
            } => format!("user {username} <redacted> {}", level.name()),
            Self::Interface { address, level, .. } => {
                format!("interface {address} {}", level.name())
            }
            Self::Remote { address, level, .. } => {
                format!("remote {address} {}", level.name())
            }
        }
    }

    pub(crate) fn authenticates(&self, username: &str, password: &str) -> bool {
        let Self::User {
            username: expected_user,
            credential_digest,
            ..
        } = self
        else {
            return false;
        };
        if expected_user != username {
            return false;
        }
        let candidate = credential_digest_for(username, password);
        auth::constant_time_eq(&candidate, credential_digest)
    }

    pub(crate) fn matches_interface(&self, address: IpAddr) -> bool {
        matches!(self, Self::Interface { resolved, .. } if resolved.iter().any(|candidate| address_matches(*candidate, address)))
    }

    pub(crate) fn matches_remote(&self, address: IpAddr) -> bool {
        matches!(self, Self::Remote { resolved, .. } if resolved.iter().any(|candidate| address_matches(*candidate, address)))
    }
}

pub(crate) fn credential_digest_for(username: &str, password: &str) -> [u8; 32] {
    let mut material = Vec::with_capacity(username.len() + password.len() + 24);
    material.extend_from_slice(b"cmqttd-access-v1\0");
    material.extend_from_slice(username.as_bytes());
    material.push(0);
    material.extend_from_slice(password.as_bytes());
    auth::sha256(&material)
}

/// Bootstrap row for new and pre-ACCESS cmqttd repositories. It matches the
/// retained oracle's administrator fixture without creating a native
/// plaintext file. Service admission remains in compatibility mode until an
/// operator explicitly changes interface/remote policy.
pub(crate) fn default_access_entries() -> Vec<AccessEntry> {
    vec![AccessEntry::Interface {
        address: "127.0.0.1".to_string(),
        resolved: vec![IpAddr::V4(Ipv4Addr::LOCALHOST)],
        level: CgateAccessLevel::Clipsal,
    }]
}

fn address_matches(candidate: IpAddr, actual: IpAddr) -> bool {
    match (candidate, actual) {
        (IpAddr::V4(candidate), IpAddr::V4(actual)) => candidate
            .octets()
            .into_iter()
            .zip(actual.octets())
            .all(|(expected, observed)| expected == u8::MAX || expected == observed),
        _ => candidate == actual,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn levels_parse_case_insensitively_and_unknown_is_none() {
        assert_eq!(
            CgateAccessLevel::parse("pRoGrAm"),
            CgateAccessLevel::Program
        );
        assert_eq!(CgateAccessLevel::parse("unknown"), CgateAccessLevel::None);
        assert!(CgateAccessLevel::Clipsal.can_manage_access());
        assert!(!CgateAccessLevel::Debug.can_manage_access());
    }

    #[test]
    fn credentials_are_case_sensitive_and_never_rendered() {
        let entry = AccessEntry::User {
            username: "alice".to_string(),
            credential_digest: credential_digest_for("alice", "Secret"),
            level: CgateAccessLevel::Admin,
        };
        assert!(entry.authenticates("alice", "Secret"));
        assert!(!entry.authenticates("Alice", "Secret"));
        assert!(!entry.authenticates("alice", "secret"));
        assert_eq!(entry.list_text(), "user alice <redacted> Admin");
    }

    #[test]
    fn ipv4_ff_octets_retain_native_wildcard_matching() {
        assert!(address_matches(
            "192.168.255.255".parse().unwrap(),
            "192.168.20.44".parse().unwrap()
        ));
        assert!(!address_matches(
            "192.168.255.255".parse().unwrap(),
            "192.169.20.44".parse().unwrap()
        ));
    }

    #[test]
    fn probed_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_authorization_probe.json"
        ))
        .unwrap();
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        assert_eq!(evidence["oracle"]["cleanup_complete"], true);
        let roles = evidence["roles"].as_object().unwrap();
        for (path, minimum) in NATIVE_PROBED_COMMANDS {
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                let responses = record["responses"].as_object().unwrap();
                let (_, reply) = responses
                    .iter()
                    .find(|(command, _)| {
                        command.as_str() == *path || command.starts_with(&format!("{path} "))
                    })
                    .unwrap_or_else(|| panic!("missing native probe for {path}"));
                let reply = reply.as_str().unwrap();
                // The native None session applies an earlier syntax check
                // to DB verbs; the handler-level floor is still visible on
                // the admitted Connect..Max sessions.
                if level == CgateAccessLevel::None && matches!(*path, "DBGET" | "DBSET") {
                    continue;
                }
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {path} at {role}: {reply}"
                );
                let command = responses
                    .keys()
                    .find(|command| {
                        command.as_str() == *path || command.starts_with(&format!("{path} "))
                    })
                    .unwrap();
                let upper = command
                    .split_whitespace()
                    .map(str::to_ascii_uppercase)
                    .collect::<Vec<_>>();
                assert_eq!(native_minimum_for(&upper), Some(*minimum));
            }
        }
        assert_eq!(native_minimum_for(&["UNPROBED".into()]), None);
    }

    #[test]
    fn expanded_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_authorization_expansion_probe.json"
        ))
        .unwrap();
        assert_eq!(
            evidence["format"],
            "native-cgate-authorization-expansion-v1"
        );
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        assert_eq!(evidence["oracle"]["listener_ownership_verified"], true);
        assert_eq!(evidence["oracle"]["cleanup_complete"], true);
        assert_eq!(evidence["oracle"]["process_exit_confirmed"], true);
        assert_eq!(evidence["oracle"]["work_removed"], true);
        assert_eq!(
            evidence["capture_script_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_authorization_matrix_expansion.py"
            )))
        );
        assert_eq!(
            evidence["local_cgate_harness_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../../../toolkit-cli/research/local_cgate.py"
            )))
        );
        let commands = evidence["commands"].as_array().unwrap();
        assert_eq!(commands.len(), NATIVE_PROBED_ADDITIONAL_COMMANDS.len());
        let roles = evidence["roles"].as_object().unwrap();
        assert_eq!(roles.len(), 9);
        for (path, minimum) in NATIVE_PROBED_ADDITIONAL_COMMANDS {
            let matches = commands
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|command| *command == *path || command.starts_with(&format!("{path} ")))
                .collect::<Vec<_>>();
            assert_eq!(matches.len(), 1, "native invocation for {path}");
            let command = matches[0];
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                assert_eq!(record["query"], format!("210 Access level: {role}"));
                let reply = record["responses"][command].as_str().unwrap();
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {command} at {role}: {reply}"
                );
            }
            let upper = command
                .split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>();
            assert_eq!(native_minimum_for(&upper), Some(*minimum));
        }
    }
    #[test]
    fn programming_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_programming_authorization_probe.json"
        ))
        .unwrap();
        assert_eq!(
            evidence["format"],
            "native-cgate-programming-authorization-v1"
        );
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        assert_eq!(evidence["oracle"]["listener_ownership_verified"], true);
        assert_eq!(evidence["oracle"]["cleanup_complete"], true);
        assert_eq!(evidence["oracle"]["process_exit_confirmed"], true);
        assert_eq!(evidence["oracle"]["work_removed"], true);
        assert_eq!(
            evidence["capture_script_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_programming_authorization_probe.py"
            )))
        );
        assert_eq!(
            evidence["local_cgate_harness_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../../../toolkit-cli/research/local_cgate.py"
            )))
        );
        let commands = evidence["commands"].as_array().unwrap();
        assert_eq!(commands.len(), NATIVE_PROBED_PROGRAMMING_COMMANDS.len());
        let roles = evidence["roles"].as_object().unwrap();
        assert_eq!(roles.len(), 9);
        for (path, minimum) in NATIVE_PROBED_PROGRAMMING_COMMANDS {
            let matches = commands
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|command| *command == *path || command.starts_with(&format!("{path} ")))
                .collect::<Vec<_>>();
            assert_eq!(matches.len(), 1, "native invocation for {path}");
            let command = matches[0];
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                assert_eq!(record["query"], format!("210 Access level: {role}"));
                let reply = record["responses"][command].as_str().unwrap();
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {command} at {role}: {reply}"
                );
            }
            let upper = command
                .split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>();
            assert_eq!(native_minimum_for(&upper), Some(*minimum));
        }
    }

    #[test]
    fn media_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_media_authorization_probe.json"
        ))
        .unwrap();
        assert_eq!(evidence["format"], "native-cgate-media-authorization-v1");
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        for field in [
            "listener_ownership_verified",
            "cleanup_complete",
            "process_exit_confirmed",
            "work_removed",
        ] {
            assert_eq!(evidence["oracle"][field], true, "{field}");
        }
        assert_eq!(
            evidence["capture_script_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_media_authorization_probe.py"
            )))
        );
        assert_eq!(
            evidence["local_cgate_harness_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../../../toolkit-cli/research/local_cgate.py"
            )))
        );
        let commands = evidence["commands"].as_array().unwrap();
        assert_eq!(commands.len(), NATIVE_PROBED_MEDIA_COMMANDS.len());
        let roles = evidence["roles"].as_object().unwrap();
        assert_eq!(roles.len(), 9);
        for (path, minimum) in NATIVE_PROBED_MEDIA_COMMANDS {
            let matches = commands
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|command| *command == *path || command.starts_with(&format!("{path} ")))
                .collect::<Vec<_>>();
            assert_eq!(matches.len(), 1, "native invocation for {path}");
            let command = matches[0];
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                assert_eq!(record["query"], format!("210 Access level: {role}"));
                let reply = record["responses"][command].as_str().unwrap();
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {command} at {role}: {reply}"
                );
            }
            let upper = command
                .split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>();
            assert_eq!(native_minimum_for(&upper), Some(*minimum));
        }
    }

    #[test]
    fn admin_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_admin_authorization_probe.json"
        ))
        .unwrap();
        assert_eq!(evidence["format"], "native-cgate-admin-authorization-v1");
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        for field in [
            "listener_ownership_verified",
            "cleanup_complete",
            "process_exit_confirmed",
            "work_removed",
        ] {
            assert_eq!(evidence["oracle"][field], true, "{field}");
        }
        assert_eq!(
            evidence["capture_script_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_admin_authorization_probe.py"
            )))
        );
        assert_eq!(
            evidence["local_cgate_harness_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../../../toolkit-cli/research/local_cgate.py"
            )))
        );
        let commands = evidence["commands"].as_array().unwrap();
        assert_eq!(commands.len(), NATIVE_PROBED_ADMIN_COMMANDS.len());
        let roles = evidence["roles"].as_object().unwrap();
        assert_eq!(roles.len(), 9);
        for (path, minimum) in NATIVE_PROBED_ADMIN_COMMANDS {
            let matches = commands
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|command| *command == *path || command.starts_with(&format!("{path} ")))
                .collect::<Vec<_>>();
            assert_eq!(matches.len(), 1, "native invocation for {path}");
            let command = matches[0];
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                assert_eq!(record["query"], format!("210 Access level: {role}"));
                let reply = record["responses"][command].as_str().unwrap();
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {command} at {role}: {reply}"
                );
            }
            let upper = command
                .split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>();
            assert_eq!(native_minimum_for(&upper), Some(*minimum));
        }
    }

    #[test]
    fn application_handler_floors_match_owned_native_role_responses() {
        let evidence: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_application_authorization_probe.json"
        ))
        .unwrap();
        assert_eq!(
            evidence["format"],
            "native-cgate-application-authorization-v1"
        );
        assert_eq!(
            evidence["oracle"]["jar_sha256"],
            "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
        );
        for field in [
            "listener_ownership_verified",
            "cleanup_complete",
            "process_exit_confirmed",
            "work_removed",
        ] {
            assert_eq!(evidence["oracle"][field], true, "{field}");
        }
        assert_eq!(
            evidence["capture_script_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_application_authorization_probe.py"
            )))
        );
        assert_eq!(
            evidence["capture_engine_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../research/native_admin_authorization_probe.py"
            )))
        );
        assert_eq!(
            evidence["local_cgate_harness_sha256"],
            hex::encode(auth::sha256(include_bytes!(
                "../../../toolkit-cli/research/local_cgate.py"
            )))
        );
        let commands = evidence["commands"].as_array().unwrap();
        assert_eq!(commands.len(), NATIVE_PROBED_APPLICATION_COMMANDS.len());
        let roles = evidence["roles"].as_object().unwrap();
        assert_eq!(roles.len(), 9);
        for (path, minimum) in NATIVE_PROBED_APPLICATION_COMMANDS {
            let matches = commands
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|command| *command == *path || command.starts_with(&format!("{path} ")))
                .collect::<Vec<_>>();
            assert_eq!(matches.len(), 1, "native invocation for {path}");
            let command = matches[0];
            for (role, record) in roles {
                let level = CgateAccessLevel::parse(role);
                assert_eq!(record["query"], format!("210 Access level: {role}"));
                let reply = record["responses"][command].as_str().unwrap();
                assert_eq!(
                    reply == "420 Access denied.",
                    level < *minimum,
                    "native {command} at {role}: {reply}"
                );
            }
            let upper = command
                .split_whitespace()
                .map(str::to_ascii_uppercase)
                .collect::<Vec<_>>();
            assert_eq!(native_minimum_for(&upper), Some(*minimum));
        }
    }
}
