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
}
