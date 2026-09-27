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

/// Longest matching native-observed command path. The caller supplies
/// uppercase whitespace-delimited words from the C-Gate parser.
pub(crate) fn native_minimum_for(upper: &[String]) -> Option<CgateAccessLevel> {
    for len in (1..=upper.len().min(3)).rev() {
        let path = upper[..len].join(" ");
        if let Some((_, level)) = NATIVE_PROBED_COMMANDS
            .iter()
            .find(|(candidate, _)| *candidate == path)
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
}
