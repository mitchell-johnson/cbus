//! Native C-Gate SHOW/GET object discovery and cached object views.
//!
//! The parameter order and descriptions are retained from C-Gate 3.4 build
//! 2001. Value tables remain deterministic projections of this server's
//! durable database and observed runtime state; no SHOW call performs bus I/O.

use std::collections::BTreeSet;

use chrono::{Duration, Local};

use super::{err, status, Network, NetworkState, Response, Server, Unit};

#[derive(Clone, Copy)]
struct ShowParameter {
    name: &'static str,
    description: &'static str,
}

#[derive(Debug)]
enum ShowObject {
    Cgate,
    Projects,
    Cbus {
        project: String,
    },
    Project {
        project: String,
    },
    Network {
        project: String,
        network: u8,
    },
    Application {
        project: String,
        network: u8,
        application: u8,
    },
    Group {
        project: String,
        network: u8,
        application: u8,
        group: u8,
    },
    Unit {
        project: String,
        network: u8,
        unit: u8,
    },
    Terminal {
        project: String,
        network: u8,
        unit: u8,
        terminal: u8,
    },
    Invalid {
        canonical: String,
        reason: &'static str,
    },
}

fn wire_scalar(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '\r' => output.push_str("\\r"),
            '\n' => output.push_str("\\n"),
            character if character.is_control() => {
                use std::fmt::Write as _;
                let _ = write!(output, "\\u{{{:x}}}", character as u32);
            }
            character => output.push(character),
        }
    }
    output
}

fn property(tag: &str, address: &str, name: &str, value: &str) -> Response {
    Response {
        tag: tag.to_string(),
        lines: Vec::new(),
        final_text: format!("300 {address}: {name}={}", wire_scalar(value)),
        status: 300,
    }
}

fn discovery(tag: &str, address: &str, schema: &[ShowParameter], detailed: bool) -> Response {
    if !detailed {
        return property(
            tag,
            address,
            "Parameters",
            &schema
                .iter()
                .map(|parameter| parameter.name)
                .collect::<Vec<_>>()
                .join(","),
        );
    }
    let mut values = schema
        .iter()
        .map(|parameter| format!("{address}: {} - {}", parameter.name, parameter.description))
        .collect::<Vec<_>>();
    let final_value = values.pop().expect("every SHOW object has parameters");
    Response {
        tag: tag.to_string(),
        lines: values,
        final_text: format!("102 {final_value}"),
        status: 102,
    }
}

fn property_table(tag: &str, address: &str, mut fields: Vec<(String, String)>) -> Response {
    fields.sort_by(|left, right| {
        left.0
            .to_ascii_lowercase()
            .cmp(&right.0.to_ascii_lowercase())
    });
    let mut rows = fields
        .into_iter()
        .map(|(name, value)| format!("300-{address}: {name}={}", wire_scalar(&value)))
        .collect::<Vec<_>>();
    let final_text = rows
        .pop()
        .expect("every SHOW object has readable fields")
        .replacen("300-", "300 ", 1);
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text,
        status: 300,
    }
}

fn requested_field(
    tag: &str,
    address: &str,
    attribute: &str,
    fields: Vec<(String, String)>,
) -> Response {
    if attribute == "*" {
        return property_table(tag, address, fields);
    }
    if let Some((_, value)) = fields
        .into_iter()
        .find(|(name, _)| name.eq_ignore_ascii_case(attribute))
    {
        // Native C-Gate resolves property names case-insensitively but echoes
        // the spelling supplied by the caller in the 300 envelope.
        return property(tag, address, attribute, &value);
    }
    err(
        tag,
        402,
        &format!(
            "402 Operation not supported by: {address} (Parameter {} not found)",
            attribute.to_ascii_lowercase()
        ),
    )
}

fn state(network: &Network, activated: bool) -> &'static str {
    match network.state {
        NetworkState::Closed
            if !activated && network.physical.is_empty() && network.units.is_empty() =>
        {
            "new"
        }
        NetworkState::Closed => "error",
        NetworkState::Open => "open",
        NetworkState::Syncing => "syncing",
        NetworkState::Ok => "ok",
    }
}

fn byte_values(value: Option<&str>) -> BTreeSet<u8> {
    value
        .into_iter()
        .flat_map(|value| {
            value
                .split(|character: char| !character.is_ascii_digit())
                .filter_map(|part| part.parse::<u8>().ok())
        })
        .collect()
}

fn terminal_count(unit: &Unit) -> Option<u8> {
    unit.fields
        .get("TerminalCount")
        .and_then(|value| value.parse::<u8>().ok())
        .or_else(|| {
            unit.fields.get("ClassName").and_then(|class_name| {
                (class_name.ends_with("CBusDimmerUnit") || class_name.ends_with("CBusRelayUnit"))
                    .then_some(4)
            })
        })
}

const NETWORK_PARAMETERS: &[ShowParameter] = &[
    ShowParameter { name: "DBUnitAddressesNew", description: "List of units on this network but not in database" },
    ShowParameter { name: "DBUnitAddressesMissing", description: "List of units not on this network but in database" },
    ShowParameter { name: "Retries", description: "The number of retries made before a command fails" },
    ShowParameter { name: "DBUnitAddressesDuplicate", description: "List of units on this network and also in database and in duplicates" },
    ShowParameter { name: "Groups", description: "The list of groups in the DEFAULT application" },
    ShowParameter { name: "TxQ", description: "List of the commands in the transmit queue" },
    ShowParameter { name: "Name", description: "Name of this network" },
    ShowParameter { name: "Applications", description: "List of applications on this network" },
    ShowParameter { name: "InterfaceState", description: "The current state of this interface" },
    ShowParameter { name: "FreeApplication", description: "The next free application address on this network" },
    ShowParameter { name: "DBUnitAddressesOnline", description: "List of units on this network and also in database and not in error" },
    ShowParameter { name: "EventLevel", description: "The level of displayed events for this object" },
    ShowParameter { name: "RxQ", description: "List of the commands waiting for responses" },
    ShowParameter { name: "Options", description: "The interface options for this interface" },
    ShowParameter { name: "NextSyncTime", description: "The next scheduled sync time for this network" },
    ShowParameter { name: "FreeUnit", description: "The next free unit address on this network" },
    ShowParameter { name: "TargetInterfaceState", description: "The current state of this interface" },
    ShowParameter { name: "TxEnable", description: "True if the transmitter is enabled" },
    ShowParameter { name: "NetworkType", description: "Type of C-Bus Network" },
    ShowParameter { name: "InterfaceAddress", description: "Address of the interface for this network" },
    ShowParameter { name: "AutoSync", description: "If set to yes, will perform automatic network synchronisations." },
    ShowParameter { name: "LastSyncTime", description: "The last sync time of this network" },
    ShowParameter { name: "SyncSubState", description: "Get the sync sub-state for this network" },
    ShowParameter { name: "AutoUnravel", description: "If set to yes, will perform automatic unravels when errors are detected in sync operations." },
    ShowParameter { name: "FastResponse", description: "If set to yes, retries and timeouts are shortened to give quick responses." },
    ShowParameter { name: "ResponseDelay", description: "Time in ms to delay before a command is retried." },
    ShowParameter { name: "QuickDetect", description: "If set to yes, perform continuous install MMIs looking for new units." },
    ShowParameter { name: "ShortSync", description: "If set to yes, perform only sync to type-version-serial." },
    ShowParameter { name: "LSP", description: "The count of Lost Sync Packets" },
    ShowParameter { name: "SyncTime", description: "The time  between full network sync operations" },
    ShowParameter { name: "SyncState", description: "Get the sync state for this network" },
    ShowParameter { name: "DBUnitAddressesError", description: "List of units on this network and also in database and in error" },
    ShowParameter { name: "Interface", description: "Address of the interface for this network" },
    ShowParameter { name: "Stats", description: "List of statistics for this interface" },
    ShowParameter { name: "Units", description: "The list of units that are in this network" },
    ShowParameter { name: "XState", description: "Get the extended state for this network" },
    ShowParameter { name: "DefaultApplication", description: "The default application for this network" },
    ShowParameter { name: "AutoUpdate", description: "If set to yes, automatically update the tag database for a new unit." },
    ShowParameter { name: "State", description: "The state of connection of this object" },
    ShowParameter { name: "Type", description: "Type of network interface" },
];

const KEYE1_UNIT_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "LearnEnable",
        description: "The state of the learn enable flag in the unit.",
    },
    ShowParameter {
        name: "ProjectName",
        description: "The user-defined project name of this C-Bus unit.",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Type",
        description: "The device type string for this unit",
    },
    ShowParameter {
        name: "Address",
        description: "The address of this unit",
    },
    ShowParameter {
        name: "Version",
        description: "The version of this C-Bus unit",
    },
    ShowParameter {
        name: "Serial",
        description: "The serial number of this unit",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Application2",
        description: "The secondary C-Bus Application for this device",
    },
    ShowParameter {
        name: "Application",
        description: "The primary C-Bus Application for this device",
    },
    ShowParameter {
        name: "GeneratingClock",
        description: "Flag indicating that the unit is generating a C-Bus clock.",
    },
    ShowParameter {
        name: "SerialNumber",
        description: "The serial number of this unit",
    },
    ShowParameter {
        name: "PSyncTime",
        description: "The time between parameter syncs for this unit",
    },
    ShowParameter {
        name: "BlockGroups",
        description: "List of groups belonging to blocks",
    },
    ShowParameter {
        name: "ClockGenActive",
        description: "Flag indicating that the unit Clock Generation is Active.",
    },
    ShowParameter {
        name: "BlockApplications",
        description: "Flags indicating primary (0) or secondary (1) application on block",
    },
    ShowParameter {
        name: "NetVoltage",
        description: "The voltage of the C-Bus network at this unit",
    },
    ShowParameter {
        name: "UnitBlock",
        description: "Unit blocks for this unit.",
    },
    ShowParameter {
        name: "BurdenActive",
        description: "Flag indicating that the unit has an active network burden.",
    },
    ShowParameter {
        name: "PatchVersion",
        description: "The version of patch in this unit",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "ErrorFlags",
        description: "Unit error flags",
    },
    ShowParameter {
        name: "PartName",
        description: "The user-defined part name of this C-Bus unit.",
    },
    ShowParameter {
        name: "Version2",
        description: "The version of the micro in the unit",
    },
    ShowParameter {
        name: "SlotGroups",
        description: "List of groups used by this unit",
    },
    ShowParameter {
        name: "Area",
        description: "The area address for this unit",
    },
    ShowParameter {
        name: "LearnActive",
        description: "Flag indicating that learn mode is active for this unit.",
    },
    ShowParameter {
        name: "Groups",
        description: "List of groups used by this unit",
    },
    ShowParameter {
        name: "SummaryFlags",
        description: "Unit summary flags",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "CatalogNumber",
        description: "The catalog number of this unit.",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
];

const GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Units",
        description: "List of unit that this group is used by.",
    },
    ShowParameter {
        name: "RampTime",
        description: "The stored ramp time for this group - only impacts CI command",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Protected",
        description: "If set, protects group from allon/alloff operations",
    },
    ShowParameter {
        name: "Type",
        description: "Returns either group or area if this is an area",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Level",
        description: "The current level of this group",
    },
];

const APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "LearnGroup",
        description: "The group currently involved in learning",
    },
    ShowParameter {
        name: "FreeGroup",
        description: "The next free group address in this application",
    },
    ShowParameter {
        name: "Groups",
        description: "List of groups in this application",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Learning",
        description: "The state of learning in this application",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
];

const GROUPED_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Groups",
        description: "List of groups in this application",
    },
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "FreeGroup",
        description: "The next free group address in this application",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
];

const AIRCON_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "Wards",
        description: "List of wards in this application",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
];

const SIMPLE_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
];

const SECURITY_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "ChargingState",
        description: "The battery charging state of the security system",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "ArmState",
        description: "The arm state of this security application",
    },
    ShowParameter {
        name: "LowBatteryState",
        description: "The low battery state of the security system",
    },
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "MainsState",
        description: "The main power state of the security system",
    },
    ShowParameter {
        name: "PassEntryState",
        description: "The pass entry state of this security application",
    },
    ShowParameter {
        name: "Zones",
        description: "List of zones in this application",
    },
    ShowParameter {
        name: "FireAlarmState",
        description: "Alarm flag indicating that a fire has been detected",
    },
    ShowParameter {
        name: "OtherAlarmState",
        description: "An alarm flag indicating that a special alarm condition has been detected",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "LineCutState",
        description: "Alarm flag indicating the attached phone line has been cut",
    },
    ShowParameter {
        name: "GasAlarmState",
        description: "An alarm flag indicating that the presence of gas has been detected",
    },
    ShowParameter {
        name: "ArmFailedState",
        description: "Alarm flag indicating that the security system failed to arm",
    },
    ShowParameter {
        name: "AlarmState",
        description: "The alarm state of the security system",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "PanicState",
        description: "The panic state of the security system",
    },
    ShowParameter {
        name: "TamperState",
        description: "The alarm state of the security system",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
];

const CLOCK_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "Offset",
        description: "Offset from the system time to the network time",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "PrimaryMasterEnabled",
        description: "True if C-Gate is the primary master clock",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "PrimaryMasterNextUpdateTime",
        description: "The next scheduled primary master clock update",
    },
];

const MEASUREMENT_APPLICATION_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Address",
        description: "The C-Bus Address of this device",
    },
    ShowParameter {
        name: "Devices",
        description: "List of measurement devices in this application",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
];

const TEMPERATURE_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Temperature",
        description: "The current temperature for this temperature group",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
];

const AIRCON_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Zones",
        description: "List of zones in this ward",
    },
    ShowParameter {
        name: "Schedules",
        description: "List of Schedule types in this zone",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
];

const TRIGGER_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
];

const ENABLE_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Level",
        description: "The current level of this network variable",
    },
];

const SECURITY_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "ZoneState",
        description: "The state of this Zone",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "ZoneIsolated",
        description: "The isolation state of this Zone",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "ZoneName",
        description: "The name of this zone",
    },
];

const MEASUREMENT_GROUP_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Channels",
        description: "List of channels on this measurement device",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ApplicationKind {
    Temperature,
    Lighting,
    Aircon,
    MediaTransport,
    Trigger,
    Enable,
    Audio,
    Security,
    Clock,
    Telephony,
    Measurement,
    GenericLighting,
}

fn application_kind(application: u8) -> Option<ApplicationKind> {
    Some(match application {
        25 => ApplicationKind::Temperature,
        48..=95 => ApplicationKind::Lighting,
        172 => ApplicationKind::Aircon,
        192 => ApplicationKind::MediaTransport,
        202 => ApplicationKind::Trigger,
        203 => ApplicationKind::Enable,
        205 => ApplicationKind::Audio,
        208 => ApplicationKind::Security,
        223 => ApplicationKind::Clock,
        224 => ApplicationKind::Telephony,
        228 => ApplicationKind::Measurement,
        238 => ApplicationKind::GenericLighting,
        _ => return None,
    })
}

fn application_schema(kind: ApplicationKind) -> &'static [ShowParameter] {
    match kind {
        ApplicationKind::Lighting
        | ApplicationKind::Trigger
        | ApplicationKind::Audio
        | ApplicationKind::GenericLighting => APPLICATION_PARAMETERS,
        ApplicationKind::Temperature | ApplicationKind::Enable => GROUPED_APPLICATION_PARAMETERS,
        ApplicationKind::Aircon => AIRCON_APPLICATION_PARAMETERS,
        ApplicationKind::MediaTransport | ApplicationKind::Telephony => {
            SIMPLE_APPLICATION_PARAMETERS
        }
        ApplicationKind::Security => SECURITY_APPLICATION_PARAMETERS,
        ApplicationKind::Clock => CLOCK_APPLICATION_PARAMETERS,
        ApplicationKind::Measurement => MEASUREMENT_APPLICATION_PARAMETERS,
    }
}

fn group_schema(kind: ApplicationKind) -> Option<&'static [ShowParameter]> {
    match kind {
        ApplicationKind::Temperature => Some(TEMPERATURE_GROUP_PARAMETERS),
        ApplicationKind::Lighting | ApplicationKind::Audio | ApplicationKind::GenericLighting => {
            Some(GROUP_PARAMETERS)
        }
        ApplicationKind::Aircon => Some(AIRCON_GROUP_PARAMETERS),
        ApplicationKind::Trigger => Some(TRIGGER_GROUP_PARAMETERS),
        ApplicationKind::Enable => Some(ENABLE_GROUP_PARAMETERS),
        ApplicationKind::Security => Some(SECURITY_GROUP_PARAMETERS),
        ApplicationKind::Measurement => Some(MEASUREMENT_GROUP_PARAMETERS),
        ApplicationKind::MediaTransport | ApplicationKind::Clock | ApplicationKind::Telephony => {
            None
        }
    }
}

const TERMINAL_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "Groups",
        description: "List of groups used by this terminal",
    },
    ShowParameter {
        name: "Logic",
        description: "Logic setting for this terminal",
    },
    ShowParameter {
        name: "Name",
        description: "Name of this terminal",
    },
    ShowParameter {
        name: "Power",
        description: "The power output level of this terminal",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "Load",
        description: "The power rating of the load connected to this terminal",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Level",
        description: "The output level of this terminal",
    },
];

const CGATE_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "ProjectFreeSpace",
        description: "Free space in the project directory",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "DatabaseVersion",
        description: "Tag Database Version Number",
    },
    ShowParameter {
        name: "MemoryFree",
        description: "Free memory in bytes",
    },
    ShowParameter {
        name: "ServerMode",
        description: "The ServerMode compile flag is set",
    },
    ShowParameter {
        name: "LogFreeSpace",
        description: "Free space in the log directory",
    },
    ShowParameter {
        name: "KCount",
        description: "KCount",
    },
    ShowParameter {
        name: "MemoryUsed",
        description: "Used memory in bytes",
    },
    ShowParameter {
        name: "Version",
        description: "C-Gate Version Number",
    },
    ShowParameter {
        name: "MemoryMaximum",
        description: "Limit of available memory in bytes",
    },
    ShowParameter {
        name: "JavaArguments",
        description: "Command line arguments passed to the Java VM",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "IsPrerelease",
        description: "The prerelease compile flag is set",
    },
    ShowParameter {
        name: "MemoryTotal",
        description: "Available memory in bytes",
    },
    ShowParameter {
        name: "Threads",
        description: "Number of active threads in this application",
    },
    ShowParameter {
        name: "IPAddress",
        description: "IP address of the C-Gate server",
    },
    ShowParameter {
        name: "ComputerName",
        description: "Name of the Computer",
    },
];

const PROJECTS_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "NetStateInterval",
        description: "The interval between network status being output as an event",
    },
];

const CBUS_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Networks",
        description: "List of available C-Bus networks",
    },
];

const PROJECT_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "AccessContextLocks",
        description: "List of access contexts using this project",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Networks",
        description: "List of networks for this project",
    },
];

const OUTPUT_UNIT_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "LearnEnable",
        description: "The state of the learn enable flag in the unit.",
    },
    ShowParameter {
        name: "ProjectName",
        description: "The user-defined project name of this C-Bus unit.",
    },
    ShowParameter {
        name: "TerminalCount",
        description: "Count of terminals provided by this unit",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Type",
        description: "The device type string for this unit",
    },
    ShowParameter {
        name: "Address",
        description: "The address of this unit",
    },
    ShowParameter {
        name: "Version",
        description: "The version of this C-Bus unit",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Application2",
        description: "The secondary C-Bus Application for this device",
    },
    ShowParameter {
        name: "Application",
        description: "The primary C-Bus Application for this device",
    },
    ShowParameter {
        name: "PSyncTime",
        description: "The time between parameter syncs for this unit",
    },
    ShowParameter {
        name: "Terminals",
        description: "List of terminals provided by this unit",
    },
    ShowParameter {
        name: "UnitBlock",
        description: "Unit blocks for this unit.",
    },
    ShowParameter {
        name: "PatchVersion",
        description: "The version of patch in this unit",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "ErrorFlags",
        description: "Unit error flags",
    },
    ShowParameter {
        name: "PartName",
        description: "The user-defined part name of this C-Bus unit.",
    },
    ShowParameter {
        name: "Version2",
        description: "The version of the micro in the unit",
    },
    ShowParameter {
        name: "SlotGroups",
        description: "List of groups used by this unit",
    },
    ShowParameter {
        name: "Area",
        description: "The area address for this unit",
    },
    ShowParameter {
        name: "Groups",
        description: "List of groups used by this unit",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "CatalogNumber",
        description: "The catalog number of this unit.",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
];

const GENERIC_UNIT_PARAMETERS: &[ShowParameter] = &[
    ShowParameter {
        name: "LearnEnable",
        description: "The state of the learn enable flag in the unit.",
    },
    ShowParameter {
        name: "ProjectName",
        description: "The user-defined project name of this C-Bus unit.",
    },
    ShowParameter {
        name: "ShortName",
        description: "The name of this object",
    },
    ShowParameter {
        name: "Type",
        description: "The device type string for this unit",
    },
    ShowParameter {
        name: "Address",
        description: "The address of this unit",
    },
    ShowParameter {
        name: "Version",
        description: "The version of this C-Bus unit",
    },
    ShowParameter {
        name: "State",
        description: "The state of connection of this object",
    },
    ShowParameter {
        name: "Application2",
        description: "The secondary C-Bus Application for this device",
    },
    ShowParameter {
        name: "Application",
        description: "The primary C-Bus Application for this device",
    },
    ShowParameter {
        name: "PSyncTime",
        description: "The time between parameter syncs for this unit",
    },
    ShowParameter {
        name: "UnitBlock",
        description: "Unit blocks for this unit.",
    },
    ShowParameter {
        name: "PatchVersion",
        description: "The version of patch in this unit",
    },
    ShowParameter {
        name: "EventLevel",
        description: "The level of displayed events for this object",
    },
    ShowParameter {
        name: "ErrorFlags",
        description: "Unit error flags",
    },
    ShowParameter {
        name: "PartName",
        description: "The user-defined part name of this C-Bus unit.",
    },
    ShowParameter {
        name: "Version2",
        description: "The version of the micro in the unit",
    },
    ShowParameter {
        name: "SlotGroups",
        description: "List of groups used by this unit",
    },
    ShowParameter {
        name: "ClassName",
        description: "The name of the class that implements this unit or application",
    },
    ShowParameter {
        name: "CatalogNumber",
        description: "The catalog number of this unit.",
    },
    ShowParameter {
        name: "Name",
        description: "The name of this object",
    },
];
impl Server {
    fn parse_show_object(&self, raw: &str) -> Option<ShowObject> {
        if raw.eq_ignore_ascii_case("cgate") {
            return Some(ShowObject::Cgate);
        }
        if raw.eq_ignore_ascii_case("projects") {
            return Some(ShowObject::Projects);
        }
        if raw.eq_ignore_ascii_case("cbus") {
            return Some(ShowObject::Cbus {
                project: self.current.clone().unwrap_or_default(),
            });
        }

        let explicit_project = raw.starts_with("//");
        let parts = raw
            .trim_matches('/')
            .split('/')
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>();
        if parts.is_empty() {
            return None;
        }
        let (project, rest) = if explicit_project {
            (parts[0].to_string(), &parts[1..])
        } else {
            (self.current.clone()?, parts.as_slice())
        };
        if rest.is_empty() {
            return Some(ShowObject::Project { project });
        }
        if rest.len() == 1 && rest[0].eq_ignore_ascii_case("cbus") {
            return Some(ShowObject::Cbus { project });
        }

        let invalid = |canonical: String, reason| ShowObject::Invalid { canonical, reason };
        let byte = |value: &str| {
            value
                .parse::<u16>()
                .ok()
                .filter(|value| *value <= 255)
                .map(|value| value as u8)
        };

        // Native also accepts the older physical ordering //P/p/N/U[/T].
        if rest[0].eq_ignore_ascii_case("p") && matches!(rest.len(), 3 | 4) {
            let canonical = format!("//{project}/{}/p/{}", rest[1], rest[2]);
            let Some(network) = byte(rest[1]) else {
                return Some(invalid(canonical, "Invalid network address"));
            };
            let Some(unit) = byte(rest[2]) else {
                return Some(invalid(canonical, "Invalid unit address"));
            };
            if rest.len() == 3 {
                return Some(ShowObject::Unit {
                    project,
                    network,
                    unit,
                });
            }
            let terminal_canonical = format!("//{project}/{network}/p/{unit}/{}", rest[3]);
            let Some(terminal) = byte(rest[3]) else {
                return Some(invalid(terminal_canonical, "Invalid terminal address"));
            };
            return Some(ShowObject::Terminal {
                project,
                network,
                unit,
                terminal,
            });
        }

        let Some(network) = byte(rest[0]) else {
            return Some(invalid(
                format!("//{project}/{}", rest[0]),
                "Invalid network address",
            ));
        };
        match rest {
            [_] => Some(ShowObject::Network { project, network }),
            [_, application] => {
                let canonical = format!("//{project}/{network}/{application}");
                byte(application).map_or_else(
                    || Some(invalid(canonical, "Invalid application address")),
                    |application| {
                        Some(ShowObject::Application {
                            project,
                            network,
                            application,
                        })
                    },
                )
            }
            [_, marker, unit] if marker.eq_ignore_ascii_case("p") => {
                let canonical = format!("//{project}/{network}/p/{unit}");
                byte(unit).map_or_else(
                    || Some(invalid(canonical, "Invalid unit address")),
                    |unit| {
                        Some(ShowObject::Unit {
                            project,
                            network,
                            unit,
                        })
                    },
                )
            }
            [_, marker, unit, terminal] if marker.eq_ignore_ascii_case("p") => {
                let canonical = format!("//{project}/{network}/p/{unit}/{terminal}");
                let Some(unit) = byte(unit) else {
                    return Some(invalid(canonical, "Invalid unit address"));
                };
                byte(terminal).map_or_else(
                    || Some(invalid(canonical, "Invalid terminal address")),
                    |terminal| {
                        Some(ShowObject::Terminal {
                            project,
                            network,
                            unit,
                            terminal,
                        })
                    },
                )
            }
            [_, application, group] => {
                let canonical = format!("//{project}/{network}/{application}/{group}");
                let Some(application) = byte(application) else {
                    return Some(invalid(canonical, "Invalid application address"));
                };
                byte(group).map_or_else(
                    || Some(invalid(canonical, "Invalid group address")),
                    |group| {
                        Some(ShowObject::Group {
                            project,
                            network,
                            application,
                            group,
                        })
                    },
                )
            }
            _ => None,
        }
    }

    fn selected_show_network<'a>(
        &'a self,
        tag: &str,
        project: &str,
        network: u8,
    ) -> Result<&'a Network, Response> {
        let Some(project_record) = self.projects.get(project) else {
            return Err(err(tag, status::ABSENT, "401 Bad object or device ID."));
        };
        project_record.networks.get(&network).ok_or_else(|| {
            err(
                tag,
                status::ABSENT,
                &format!("401 Bad object or device ID: //{project}/{network} (Network not found)"),
            )
        })
    }

    fn show_applications(
        &self,
        project: &str,
        network_number: u8,
        network: &Network,
    ) -> BTreeSet<u8> {
        let mut applications = network
            .levels
            .keys()
            .map(|(application, _)| *application)
            .filter(|application| *application != 255)
            .collect::<BTreeSet<_>>();
        let prefix = format!("//{project}/{network_number}/");
        for object in &self.objects {
            let Some(rest) = object.strip_prefix(&prefix) else {
                continue;
            };
            let application = rest.split('/').next().unwrap_or_default();
            if let Ok(application) = application.parse::<u8>() {
                if application != 255 {
                    applications.insert(application);
                }
            }
        }
        for field in self.db_fields.keys() {
            let Some(rest) = field.strip_prefix(&prefix) else {
                continue;
            };
            let Some((application, _)) = rest.split_once('/') else {
                continue;
            };
            if let Ok(application) = application.parse::<u8>() {
                if application != 255 {
                    applications.insert(application);
                }
            }
        }
        for unit in network.physical.values().chain(network.units.values()) {
            for name in ["Application", "Application2"] {
                if let Some(application) = unit
                    .fields
                    .get(name)
                    .and_then(|value| value.parse::<u8>().ok())
                {
                    if application != 255 {
                        applications.insert(application);
                    }
                }
            }
        }
        applications
    }

    fn show_groups(
        &self,
        project: &str,
        network_number: u8,
        application: u8,
        network: &Network,
    ) -> BTreeSet<u8> {
        let mut groups = network
            .levels
            .keys()
            .filter_map(|(candidate_application, group)| {
                (*candidate_application == application).then_some(*group)
            })
            .collect::<BTreeSet<_>>();
        let prefix = format!("//{project}/{network_number}/{application}/");
        for object in &self.objects {
            if let Some(group) = object
                .strip_prefix(&prefix)
                .and_then(|value| value.parse::<u8>().ok())
            {
                groups.insert(group);
            }
        }
        for field in self.db_fields.keys() {
            let Some(rest) = field.strip_prefix(&prefix) else {
                continue;
            };
            if let Some(group) = rest
                .split('/')
                .next()
                .and_then(|value| value.parse::<u8>().ok())
            {
                groups.insert(group);
            }
        }
        for unit in network.physical.values().chain(network.units.values()) {
            let primary = unit
                .fields
                .get("Application")
                .and_then(|value| value.parse::<u8>().ok());
            if primary == Some(application) {
                groups.extend(byte_values(
                    unit.fields
                        .get("WidgetGroups")
                        .or_else(|| unit.fields.get("Groups"))
                        .map(String::as_str),
                ));
            }
        }
        groups
    }

    fn network_fields(
        &self,
        project: &str,
        network_number: u8,
        network: &Network,
    ) -> Vec<(String, String)> {
        let applications = self.show_applications(project, network_number, network);
        let groups = self.show_groups(project, network_number, 56, network);
        let units = network
            .physical
            .keys()
            .chain(network.units.keys())
            .copied()
            .collect::<BTreeSet<_>>();
        let free_unit = (0_u16..=255)
            .map(|value| value as u8)
            .find(|value| !units.contains(value))
            .unwrap_or(255);
        let free_application = (0_u16..=255)
            .map(|value| value as u8)
            .find(|value| !applications.contains(value))
            .unwrap_or(255);
        let interface_state = match network.state {
            NetworkState::Closed => "closed",
            NetworkState::Open | NetworkState::Ok => "running",
            NetworkState::Syncing => "opening",
        };
        let sync_state = if network.state == NetworkState::Syncing {
            "units"
        } else {
            "idle"
        };
        let activated = self
            .activated_networks
            .contains(&(project.to_string(), network_number));
        let object_state = state(network, activated);
        let wired = matches!(
            network.iface_type.to_ascii_lowercase().as_str(),
            "cni" | "serial" | "socket" | "wiser" | "etherlite"
        );
        vec![
            (
                "Applications".into(),
                applications
                    .iter()
                    .map(u8::to_string)
                    .collect::<Vec<_>>()
                    .join(","),
            ),
            ("AutoSync".into(), "yes".into()),
            ("AutoUnravel".into(), "no".into()),
            ("AutoUpdate".into(), "no".into()),
            ("DBUnitAddressesDuplicate".into(), String::new()),
            ("DBUnitAddressesError".into(), String::new()),
            ("DBUnitAddressesMissing".into(), String::new()),
            ("DBUnitAddressesNew".into(), String::new()),
            ("DBUnitAddressesOnline".into(), String::new()),
            ("DefaultApplication".into(), "56".into()),
            ("EventLevel".into(), "9".into()),
            ("FastResponse".into(), "no".into()),
            ("FreeApplication".into(), free_application.to_string()),
            ("FreeUnit".into(), free_unit.to_string()),
            (
                "Groups".into(),
                groups
                    .iter()
                    .map(u8::to_string)
                    .collect::<Vec<_>>()
                    .join(","),
            ),
            ("Interface".into(), network.iface_addr.clone()),
            ("InterfaceAddress".into(), network.iface_addr.clone()),
            ("InterfaceState".into(), interface_state.into()),
            ("LastSyncTime".into(), String::new()),
            ("LSP".into(), "0".into()),
            ("Name".into(), network.name.clone()),
            (
                "NetworkType".into(),
                if wired { "Wired" } else { "Bridge" }.into(),
            ),
            (
                "NextSyncTime".into(),
                (Local::now() + Duration::seconds(300))
                    .format("%Y%m%d-%H%M%S")
                    .to_string(),
            ),
            ("Options".into(), "null".into()),
            ("QuickDetect".into(), "no".into()),
            ("ResponseDelay".into(), "3000".into()),
            ("Retries".into(), "2".into()),
            ("RxQ".into(), "null".into()),
            ("ShortSync".into(), "no".into()),
            ("State".into(), object_state.into()),
            ("Stats".into(), String::new()),
            ("SyncState".into(), sync_state.into()),
            ("SyncSubState".into(), sync_state.into()),
            ("SyncTime".into(), "300".into()),
            (
                "TargetInterfaceState".into(),
                if network.state == NetworkState::Closed {
                    "closed"
                } else {
                    "running"
                }
                .into(),
            ),
            (
                "TxEnable".into(),
                if network.state == NetworkState::Closed {
                    "no"
                } else {
                    "yes"
                }
                .into(),
            ),
            ("TxQ".into(), "null".into()),
            ("Type".into(), network.iface_type.clone()),
            (
                "Units".into(),
                units
                    .iter()
                    .map(u8::to_string)
                    .collect::<Vec<_>>()
                    .join(","),
            ),
            ("XState".into(), format!("{object_state}+{sync_state}")),
        ]
    }

    fn application_fields(
        &self,
        project: &str,
        network_number: u8,
        application: u8,
        network: &Network,
    ) -> Vec<(String, String)> {
        let kind = application_kind(application).unwrap_or(ApplicationKind::GenericLighting);
        let groups = self.show_groups(project, network_number, application, network);
        let free_group = (0_u16..=255)
            .map(|value| value as u8)
            .find(|value| !groups.contains(value))
            .unwrap_or(255);
        let address = format!("//{project}/{network_number}/{application}");
        let name = self
            .db_fields
            .get(&format!("{address}/Name"))
            .or_else(|| self.db_fields.get(&format!("{address}/TagName")))
            .cloned()
            .unwrap_or_default();
        let (class_name, short_name) = match kind {
            ApplicationKind::Temperature => (
                "com.clipsal.cgate.cbus.app.temperature.CBusTemperatureBroadcastApplication",
                "temperature",
            ),
            ApplicationKind::Lighting => (
                "com.clipsal.cgate.cbus.app.lighting.CBusLightingApplication",
                "lighting",
            ),
            ApplicationKind::Aircon => (
                "com.clipsal.cgate.cbus.app.aircon.CBusAirConditioningApplication",
                "aircon",
            ),
            ApplicationKind::MediaTransport => (
                "com.clipsal.cgate.cbus.app.mediatransport.CBusMediaTransportApplication",
                "mediatransport",
            ),
            ApplicationKind::Trigger => (
                "com.clipsal.cgate.cbus.app.triggercontrol.CBusTriggerControlApplication",
                "trigger",
            ),
            ApplicationKind::Enable => (
                "com.clipsal.cgate.cbus.app.enablecontrol.CBusEnableControlApplication",
                "enable",
            ),
            ApplicationKind::Audio => (
                "com.clipsal.cgate.cbus.app.audio.CBusAudioApplication",
                "audio",
            ),
            ApplicationKind::Security => (
                "com.clipsal.cgate.cbus.app.security.CBusSecurityApplication",
                "security",
            ),
            ApplicationKind::Clock => (
                "com.clipsal.cgate.cbus.app.clock.CBusClockApplication",
                "clock",
            ),
            ApplicationKind::Telephony => (
                "com.clipsal.cgate.cbus.app.telephony.CBusTelephonyApplication",
                "telephony",
            ),
            ApplicationKind::Measurement => (
                "com.clipsal.cgate.cbus.app.measurement.CBusMeasurementApplication",
                "measurement",
            ),
            ApplicationKind::GenericLighting => (
                "com.clipsal.cgate.cbus.app.lighting.CBusLightingApplication",
                "application",
            ),
        };
        let group_list = groups
            .iter()
            .map(u8::to_string)
            .collect::<Vec<_>>()
            .join(",");
        let activated = self
            .activated_networks
            .contains(&(project.to_string(), network_number));
        let state = state(network, activated).to_string();
        let mut fields = vec![
            ("Address".into(), application.to_string()),
            ("ClassName".into(), class_name.into()),
            ("EventLevel".into(), "9".into()),
            ("Name".into(), name),
            ("ShortName".into(), short_name.into()),
            ("State".into(), state),
        ];
        match kind {
            ApplicationKind::Lighting
            | ApplicationKind::Trigger
            | ApplicationKind::Audio
            | ApplicationKind::GenericLighting => fields.extend([
                ("FreeGroup".into(), free_group.to_string()),
                ("Groups".into(), group_list),
                ("LearnGroup".into(), "255".into()),
                ("Learning".into(), "no".into()),
            ]),
            ApplicationKind::Temperature | ApplicationKind::Enable => fields.extend([
                ("FreeGroup".into(), free_group.to_string()),
                ("Groups".into(), group_list),
            ]),
            ApplicationKind::Aircon => fields.push(("Wards".into(), group_list)),
            ApplicationKind::Security => {
                fields.extend([
                    ("AlarmState".into(), "unknown".into()),
                    ("ArmFailedState".into(), "unknown".into()),
                    ("ArmState".into(), "-1".into()),
                    ("ChargingState".into(), "unknown".into()),
                    ("FireAlarmState".into(), "unknown".into()),
                    ("GasAlarmState".into(), "unknown".into()),
                    ("LineCutState".into(), "unknown".into()),
                    ("LowBatteryState".into(), "unknown".into()),
                    ("MainsState".into(), "unknown".into()),
                    ("OtherAlarmState".into(), "unknown".into()),
                    ("PanicState".into(), "unknown".into()),
                    ("PassEntryState".into(), "-1".into()),
                    ("TamperState".into(), "unknown".into()),
                    ("Zones".into(), group_list),
                ]);
            }
            ApplicationKind::Clock => fields.extend([
                ("Offset".into(), "0".into()),
                ("PrimaryMasterEnabled".into(), "no".into()),
                (
                    "PrimaryMasterNextUpdateTime".into(),
                    "19700101-120000".into(),
                ),
            ]),
            ApplicationKind::Measurement => fields.push(("Devices".into(), group_list)),
            ApplicationKind::MediaTransport | ApplicationKind::Telephony => {}
        }
        fields
    }

    fn group_fields(
        &self,
        project: &str,
        network_number: u8,
        application: u8,
        group: u8,
        network: &Network,
    ) -> Vec<(String, String)> {
        let kind = application_kind(application).unwrap_or(ApplicationKind::GenericLighting);
        let address = format!("//{project}/{network_number}/{application}/{group}");
        let units = network
            .physical
            .iter()
            .chain(network.units.iter())
            .filter_map(|(unit_address, unit)| {
                let primary = unit
                    .fields
                    .get("Application")
                    .and_then(|value| value.parse::<u8>().ok());
                let groups = byte_values(
                    unit.fields
                        .get("WidgetGroups")
                        .or_else(|| unit.fields.get("Groups"))
                        .map(String::as_str),
                );
                (primary == Some(application) && groups.contains(&group)).then_some(*unit_address)
            })
            .collect::<BTreeSet<_>>();
        let level = network
            .levels
            .get(&(application, group))
            .copied()
            .or_else(|| {
                self.db_fields
                    .get(&format!("{address}/Level"))
                    .and_then(|value| value.parse::<u8>().ok())
            })
            .unwrap_or(0);
        let name = self
            .db_fields
            .get(&format!("{address}/Name"))
            .or_else(|| self.db_fields.get(&format!("{address}/TagName")))
            .cloned()
            .unwrap_or_default();
        let activated = self
            .activated_networks
            .contains(&(project.to_string(), network_number));
        let state = state(network, activated).to_string();
        let unit_list = units
            .iter()
            .map(u8::to_string)
            .collect::<Vec<_>>()
            .join(" ");
        match kind {
            ApplicationKind::Temperature => vec![
                ("EventLevel".into(), "9".into()),
                ("Name".into(), name),
                ("State".into(), state),
                ("Temperature".into(), "0.0".into()),
            ],
            ApplicationKind::Lighting
            | ApplicationKind::Audio
            | ApplicationKind::GenericLighting => vec![
                ("EventLevel".into(), "9".into()),
                ("Level".into(), level.to_string()),
                ("Name".into(), name),
                ("Protected".into(), "no".into()),
                ("RampTime".into(), "0".into()),
                ("State".into(), state),
                ("Type".into(), "group".into()),
                ("Units".into(), unit_list),
            ],
            ApplicationKind::Aircon => vec![
                ("EventLevel".into(), "9".into()),
                ("Name".into(), name),
                ("Schedules".into(), "T,H".into()),
                ("State".into(), state),
                ("Zones".into(), String::new()),
            ],
            ApplicationKind::Trigger => vec![
                ("EventLevel".into(), "9".into()),
                ("Name".into(), name),
                ("State".into(), state),
            ],
            ApplicationKind::Enable => vec![
                ("EventLevel".into(), "9".into()),
                ("Level".into(), level.to_string()),
                ("Name".into(), name),
                ("State".into(), state),
            ],
            ApplicationKind::Security => vec![
                ("EventLevel".into(), "9".into()),
                ("Name".into(), name),
                ("State".into(), state),
                ("ZoneIsolated".into(), "no".into()),
                ("ZoneName".into(), "unknown".into()),
                ("ZoneState".into(), "-1".into()),
            ],
            ApplicationKind::Measurement => vec![
                ("Channels".into(), String::new()),
                ("EventLevel".into(), "9".into()),
                ("Name".into(), name),
                ("State".into(), state),
            ],
            ApplicationKind::MediaTransport
            | ApplicationKind::Clock
            | ApplicationKind::Telephony => Vec::new(),
        }
    }

    fn unit_response(
        &self,
        tag: &str,
        address: &str,
        attribute: &str,
        network: &Network,
        unit_address: u8,
    ) -> Response {
        let Some(unit) = network
            .physical
            .get(&unit_address)
            .or_else(|| network.units.get(&unit_address))
        else {
            return err(
                tag,
                status::ABSENT,
                &format!("401 Bad object or device ID: {address} (Unit not found)"),
            );
        };
        let schema = if terminal_count(unit).is_some() {
            OUTPUT_UNIT_PARAMETERS
        } else if unit
            .fields
            .get("ClassName")
            .is_some_and(|value| value.ends_with("CBusNeoInputUnit"))
        {
            KEYE1_UNIT_PARAMETERS
        } else {
            GENERIC_UNIT_PARAMETERS
        };
        if matches!(attribute, "?" | "??") {
            return discovery(tag, address, schema, attribute == "??");
        }
        let value = |name: &str| {
            unit.fields
                .iter()
                .find(|(candidate, _)| candidate.eq_ignore_ascii_case(name))
                .map(|(_, value)| value.clone())
                .unwrap_or_else(|| unit.field(name))
        };
        if attribute == "*" {
            let new_database_object =
                unit.created_by_new && !network.physical.contains_key(&unit_address);
            let mut names = schema
                .iter()
                .map(|parameter| parameter.name)
                .collect::<Vec<_>>();
            names.sort_by_key(|left| left.to_ascii_lowercase());
            let mut rows = Vec::with_capacity(names.len() + usize::from(new_database_object));
            for name in names {
                if new_database_object
                    && name.eq_ignore_ascii_case("LearnEnable")
                    && !unit
                        .fields
                        .keys()
                        .any(|candidate| candidate.eq_ignore_ascii_case(name))
                {
                    rows.push(format!(
                        "408-Operation failed: {address} (Can not get parameter from unit)"
                    ));
                    continue;
                }
                rows.push(format!(
                    "300-{address}: {name}={}",
                    wire_scalar(&value(name))
                ));
            }
            let final_text = rows
                .pop()
                .expect("unit fields are nonempty")
                .replacen("300-", "300 ", 1);
            return Response {
                tag: tag.to_string(),
                lines: rows,
                final_text,
                status: 300,
            };
        }
        if let Some(parameter) = schema
            .iter()
            .find(|parameter| parameter.name.eq_ignore_ascii_case(attribute))
        {
            // Application recalls are optional physical observations.  A
            // failed or deliberately skipped eDLT recall must stay absent;
            // returning an empty value here would manufacture a successful
            // read and erase the distinction used by NET SYNC's attribution
            // guards.  Native NEW UNIT records seed both fields explicitly,
            // so their captured SHOW/GET defaults still take this path.
            if matches!(parameter.name, "Application" | "Application2")
                && !unit
                    .fields
                    .keys()
                    .any(|candidate| candidate.eq_ignore_ascii_case(parameter.name))
            {
                return err(
                    tag,
                    402,
                    &format!(
                        "402 Operation not supported by: {address} (Parameter {} not found)",
                        attribute.to_ascii_lowercase()
                    ),
                );
            }
            if parameter.name.eq_ignore_ascii_case("LearnEnable")
                && !unit
                    .fields
                    .keys()
                    .any(|candidate| candidate.eq_ignore_ascii_case(parameter.name))
            {
                return err(
                    tag,
                    408,
                    &format!("408 Operation failed: {address} (Can not get parameter from unit)"),
                );
            }
            return property(tag, address, attribute, &value(parameter.name));
        }
        // The eDLT metadata recalls performed by NET SYNC are vendor-class
        // properties outside the base CBusUnit SHOW catalogue. They remain
        // addressable by name from the volatile observation snapshot, which
        // is how Toolkit reads the optional OEM values after a sync. Missing
        // recalls stay 402 rather than being manufactured from defaults.
        if unit.unit_type.eq_ignore_ascii_case("KEYGL5")
            && matches!(
                attribute.to_ascii_lowercase().as_str(),
                "widgetgroups" | "firmwareversion"
            )
        {
            if let Some((_, observed)) = unit
                .fields
                .iter()
                .find(|(candidate, _)| candidate.eq_ignore_ascii_case(attribute))
            {
                return property(tag, address, attribute, observed);
            }
        }
        if network.physical.contains_key(&unit_address)
            && attribute.eq_ignore_ascii_case("SerialNumber")
        {
            return property(tag, address, attribute, &unit.serial);
        }
        err(
            tag,
            402,
            &format!(
                "402 Operation not supported by: {address} (Parameter {} not found)",
                attribute.to_ascii_lowercase()
            ),
        )
    }

    fn cgate_fields(&self) -> Vec<(String, String)> {
        vec![
            ("ComputerName".into(), "null".into()),
            ("DatabaseVersion".into(), "2.3".into()),
            ("EventLevel".into(), "9".into()),
            ("IPAddress".into(), "127.0.0.1".into()),
            ("IsPrerelease".into(), "no".into()),
            ("JavaArguments".into(), "[]".into()),
            ("LogFreeSpace".into(), "unknown".into()),
            ("MemoryFree".into(), "0".into()),
            ("MemoryMaximum".into(), "0".into()),
            ("MemoryTotal".into(), "0".into()),
            ("MemoryUsed".into(), "0".into()),
            ("ProjectFreeSpace".into(), "unknown".into()),
            ("ServerMode".into(), "no".into()),
            ("State".into(), "new".into()),
            ("Threads".into(), "1".into()),
            ("Version".into(), "v3.4.0 (build 2001)".into()),
        ]
    }

    fn cgate_response(&self, tag: &str, attribute: &str) -> Response {
        if matches!(attribute, "?" | "??") {
            return discovery(tag, "cgate", CGATE_PARAMETERS, attribute == "??");
        }
        if attribute.eq_ignore_ascii_case("KCount") {
            return err(
                tag,
                status::ACCESS_DENIED,
                "420 Access denied: cgate (Insufficient access level for read)",
            );
        }
        if attribute != "*" {
            return requested_field(tag, "cgate", attribute, self.cgate_fields());
        }
        let response = property_table(tag, "cgate", self.cgate_fields());
        let mut lines = response.lines;
        let insert_at = lines
            .iter()
            .position(|line| line.contains(": JavaArguments="))
            .map_or(lines.len(), |index| index + 1);
        lines.insert(
            insert_at,
            "420-Access denied: cgate (Insufficient access level for read)".into(),
        );
        Response { lines, ..response }
    }

    pub(super) fn show_object(
        &self,
        tag: &str,
        raw_address: &str,
        attribute: &str,
    ) -> Option<Response> {
        let object = self.parse_show_object(raw_address)?;
        let response = match object {
            ShowObject::Invalid { canonical, reason } => err(
                tag,
                status::ABSENT,
                &format!("401 Bad object or device ID: {canonical} ({reason})"),
            ),
            ShowObject::Cgate => self.cgate_response(tag, attribute),
            ShowObject::Projects => {
                if matches!(attribute, "?" | "??") {
                    discovery(tag, "projects", PROJECTS_PARAMETERS, attribute == "??")
                } else {
                    requested_field(
                        tag,
                        "projects",
                        attribute,
                        vec![
                            ("EventLevel".into(), "9".into()),
                            ("NetStateInterval".into(), "0".into()),
                            ("State".into(), "new".into()),
                        ],
                    )
                }
            }
            ShowObject::Cbus { project } => {
                let Some(project_record) = self.projects.get(&project) else {
                    return Some(err(tag, status::ABSENT, "401 Bad object or device ID."));
                };
                let address = format!("//{project}/cbus");
                if matches!(attribute, "?" | "??") {
                    discovery(tag, &address, CBUS_PARAMETERS, attribute == "??")
                } else {
                    let networks = project_record
                        .networks
                        .keys()
                        .copied()
                        .collect::<BTreeSet<_>>();
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        vec![
                            ("EventLevel".into(), "9".into()),
                            (
                                "Networks".into(),
                                networks
                                    .iter()
                                    .map(u8::to_string)
                                    .collect::<Vec<_>>()
                                    .join(","),
                            ),
                            ("State".into(), "new".into()),
                        ],
                    )
                }
            }
            ShowObject::Project { project } => {
                let Some(project_record) = self.projects.get(&project) else {
                    return Some(err(tag, status::ABSENT, "401 Bad object or device ID."));
                };
                let address = format!("//{project}");
                if matches!(attribute, "?" | "??") {
                    discovery(tag, &address, PROJECT_PARAMETERS, attribute == "??")
                } else {
                    let networks = project_record
                        .networks
                        .keys()
                        .copied()
                        .collect::<BTreeSet<_>>();
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        vec![
                            ("AccessContextLocks".into(), String::new()),
                            ("EventLevel".into(), "9".into()),
                            (
                                "Networks".into(),
                                networks
                                    .iter()
                                    .map(u8::to_string)
                                    .collect::<Vec<_>>()
                                    .join(","),
                            ),
                            ("State".into(), "new".into()),
                        ],
                    )
                }
            }
            ShowObject::Network { project, network } => {
                let network_record = match self.selected_show_network(tag, &project, network) {
                    Ok(network) => network,
                    Err(response) => return Some(response),
                };
                let address = format!("//{project}/{network}");
                if matches!(attribute, "?" | "??") {
                    discovery(tag, &address, NETWORK_PARAMETERS, attribute == "??")
                } else {
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        self.network_fields(&project, network, network_record),
                    )
                }
            }
            ShowObject::Application {
                project,
                network,
                application,
            } => {
                let network_record = match self.selected_show_network(tag, &project, network) {
                    Ok(network) => network,
                    Err(response) => return Some(response),
                };
                let groups = self.show_groups(&project, network, application, network_record);
                let applications = self.show_applications(&project, network, network_record);
                if groups.is_empty() && !applications.contains(&application) {
                    let address = format!("//{project}/{network}/{application}");
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {address} (Object not found)"),
                    ));
                }
                let address = format!("//{project}/{network}/{application}");
                let kind =
                    application_kind(application).unwrap_or(ApplicationKind::GenericLighting);
                if matches!(attribute, "?" | "??") {
                    discovery(tag, &address, application_schema(kind), attribute == "??")
                } else {
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        self.application_fields(&project, network, application, network_record),
                    )
                }
            }
            ShowObject::Group {
                project,
                network,
                application,
                group,
            } => {
                let network_record = match self.selected_show_network(tag, &project, network) {
                    Ok(network) => network,
                    Err(response) => return Some(response),
                };
                let kind =
                    application_kind(application).unwrap_or(ApplicationKind::GenericLighting);
                if kind == ApplicationKind::MediaTransport {
                    let address = format!("//{project}/{network}/{application}/{group}");
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!(
                            "401 Bad object or device ID: {address} (Address not supported by application)"
                        ),
                    ));
                }
                if matches!(kind, ApplicationKind::Clock | ApplicationKind::Telephony) {
                    let address = format!("//{project}/{network}/{application}/{group}");
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {address} (Object not found)"),
                    ));
                }
                if !self
                    .show_groups(&project, network, application, network_record)
                    .contains(&group)
                {
                    let address = format!("//{project}/{network}/{application}/{group}");
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {address} (Object not found)"),
                    ));
                }
                let address = format!("//{project}/{network}/{application}/{group}");
                if matches!(attribute, "?" | "??") {
                    discovery(
                        tag,
                        &address,
                        group_schema(kind).expect("addressable application has a child schema"),
                        attribute == "??",
                    )
                } else {
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        self.group_fields(&project, network, application, group, network_record),
                    )
                }
            }
            ShowObject::Unit {
                project,
                network,
                unit,
            } => {
                let network_record = match self.selected_show_network(tag, &project, network) {
                    Ok(network) => network,
                    Err(response) => return Some(response),
                };
                let address = format!("//{project}/{network}/p/{unit}");
                self.unit_response(tag, &address, attribute, network_record, unit)
            }
            ShowObject::Terminal {
                project,
                network,
                unit,
                terminal,
            } => {
                let network_record = match self.selected_show_network(tag, &project, network) {
                    Ok(network) => network,
                    Err(response) => return Some(response),
                };
                let address = format!("//{project}/{network}/p/{unit}/{terminal}");
                let Some(unit_record) = network_record
                    .physical
                    .get(&unit)
                    .or_else(|| network_record.units.get(&unit))
                else {
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {address} (Unit not found)"),
                    ));
                };
                let Some(count) = terminal_count(unit_record) else {
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!(
                            "401 Bad object or device ID: {address} (Unit does not have terminals)"
                        ),
                    ));
                };
                if terminal == 0 || terminal > count {
                    return Some(err(
                        tag,
                        status::ABSENT,
                        &format!(
                            "401 Bad object or device ID: {address} (Invalid terminal address)"
                        ),
                    ));
                }
                if matches!(attribute, "?" | "??") {
                    discovery(tag, &address, TERMINAL_PARAMETERS, attribute == "??")
                } else {
                    requested_field(
                        tag,
                        &address,
                        attribute,
                        vec![
                            ("EventLevel".into(), "9".into()),
                            ("Groups".into(), String::new()),
                            ("Level".into(), "255".into()),
                            ("Load".into(), "0".into()),
                            ("Logic".into(), "lesser".into()),
                            ("Name".into(), "null".into()),
                            ("Power".into(), "0".into()),
                            ("State".into(), "unknown".into()),
                        ],
                    )
                }
            }
        };
        Some(response)
    }
}
