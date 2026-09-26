//! C-Gate 3.4 manual command inventory and declarative bus-command syntax.
//!
//! The names are the 224 entries in manual section 4.5 (2024 edition).
//! Parent entries are help commands; aliases and leaf commands are retained
//! as separate entries because clients discover them independently.

/// Every command heading in C-Gate Manual 3.4 section 4.5, in document order.
pub const DOCUMENTED_COMMANDS: &[&str] = &[
    "#",
    "//",
    "AIRCON",
    "AIRCON REFRESH",
    "AIRCON SET_HUMIDITY_SETBACK_LIMIT",
    "AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT",
    "AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT",
    "AIRCON SET_HVAC_LOWER_GUARD_LIMIT",
    "AIRCON SET_HVAC_SETBACK_LIMIT",
    "AIRCON SET_HVAC_UPPER_GUARD_LIMIT",
    "AIRCON SET_WARD_OFF",
    "AIRCON SET_WARD_ON",
    "AIRCON SET_ZONE_HUMIDITY_MODE",
    "AIRCON SET_ZONE_HVAC_MODE",
    "APIVER",
    "AUDIO",
    "AUDIO CURRENT_FEED",
    "AUDIO DYNAMIC_1",
    "AUDIO DYNAMIC_2",
    "AUDIO HIGH_PRIORITY",
    "AUDIO MUTE",
    "AUDIO NEXT_FEED",
    "AUDIO NEXT_LANGUAGE",
    "AUDIO OFF",
    "AUDIO ON",
    "AUDIO OUTPUT_COMMON_CONTROL",
    "AUDIO OUTPUT_DEVICE_STATUS_REQUEST",
    "AUDIO OUTPUT_ERROR_CODE",
    "AUDIO PREVIOUS_FEED",
    "AUDIO RAMP",
    "AUDIO REQUEST_CURRENT_FEED",
    "AUDIO SET_FEED",
    "AUDIO TERMINATERAMP",
    "AUDIO ZONE_DESCRIPTOR_REQUEST",
    "AUDIO ZONE_FEED_LABEL_REQUEST",
    "BROADCAST_EVENT",
    "CGL",
    "CGL EXPORT",
    "CGL IMPORT",
    "CLOCK",
    "CLOCK DATE",
    "CLOCK REQUEST_REFRESH",
    "CLOCK TIME",
    "CONFIG",
    "CONFIG GET",
    "CONFIG INFO",
    "CONFIG LOAD",
    "CONFIG SAVE",
    "CONFIG SET",
    "CONFIG OBGET",
    "CONFIG OBSET",
    "CONFIG OBRESET",
    "CONFIRM",
    "DBADD",
    "DBADDSAFE",
    "DBCOPY",
    "DBCOPYSAFE",
    "DBCREATE",
    "DBCREATENET",
    "DBDELETE",
    "DBGET",
    "DBGETXML",
    "DBLOAD",
    "DBNETWORKPATH",
    "DBNEW",
    "DBRENAMENET",
    "DBRENAMENETSAFE",
    "DBSAVE",
    "DBSET",
    "DBSETSAFE",
    "DBSETXML",
    "DBTAGLIST",
    "DBUPDATE",
    "DBVALIDATE",
    "DBVERIFY",
    "DO",
    "ENABLE",
    "ENABLE LABEL",
    "ENABLE REMOVE",
    "ENABLE SET",
    "EREPORT",
    "EREPORT MESSAGE",
    "EVENT",
    "GET",
    "GETSTATE",
    "HELP",
    "LIGHTING",
    "LIGHTING LABEL",
    "LIGHTING UNICODELABEL",
    "LIGHTING OFF",
    "LIGHTING ON",
    "LIGHTING RAMP",
    "LIGHTING TERMINATERAMP",
    "LOCK",
    "LOGIN",
    "LOGOUT",
    "MEASUREMENT",
    "MEASUREMENT DATA",
    "MEDIATRANSPORT",
    "MEDIATRANSPORT CATEGORY_NAME",
    "MEDIATRANSPORT ENUMERATE",
    "MEDIATRANSPORT ENUMERATION_SIZE",
    "MEDIATRANSPORT FORWARD",
    "MEDIATRANSPORT NEXT_CATEGORY",
    "MEDIATRANSPORT NEXT_SELECTION",
    "MEDIATRANSPORT NEXT_TRACK",
    "MEDIATRANSPORT PAUSE",
    "MEDIATRANSPORT PLAY",
    "MEDIATRANSPORT REPEAT",
    "MEDIATRANSPORT REWIND",
    "MEDIATRANSPORT SELECTION_NAME",
    "MEDIATRANSPORT SET_CATEGORY",
    "MEDIATRANSPORT SET_SELECTION",
    "MEDIATRANSPORT SET_TRACK",
    "MEDIATRANSPORT SHUFFLE",
    "MEDIATRANSPORT SOURCE_POWER",
    "MEDIATRANSPORT STATUS_REQUEST",
    "MEDIATRANSPORT STOP",
    "MEDIATRANSPORT TOTAL_TRACKS",
    "MEDIATRANSPORT TRACK_NAME",
    "NET",
    "NET CHECKUNIT",
    "NET CLOCKS",
    "NET CLOSE",
    "NET CREATE",
    "NET DELETE",
    "NET FLUSH",
    "NET LEARN",
    "NET LIST",
    "NET LIST_ALL",
    "NET LOAD",
    "NET OPEN",
    "NET PINGU",
    "NET PROJECT_IDENTIFY",
    "NET RENAME",
    "NET SAVE",
    "NET SET_PROJECT_IDENTIFY",
    "NET SYNC",
    "NET SYNCNEW",
    "NET UNRAVELUNIT",
    "NET UNRAVEL",
    "NETWORK",
    "NETWORK LOCATE",
    "NEW",
    "NOOP",
    "OFF",
    "OID",
    "ON",
    "PORT",
    "PORT CNISCAN",
    "PORT CNISCAN2",
    "PORT IFLIST",
    "PORT LIST",
    "PORT PROBE",
    "PORT REFRESH",
    "PROJECT",
    "PROJECT CLOSE",
    "PROJECT COPY",
    "PROJECT DELETE",
    "PROJECT DIR",
    "PROJECT LIST",
    "PROJECT LOAD",
    "PROJECT NEW",
    "PROJECT RENAME",
    "PROJECT REPAIR",
    "PROJECT RESTORE",
    "PROJECT SAVE",
    "PROJECT START",
    "PROJECT STOP",
    "PROJECT USE",
    "QUIT",
    "RAMP",
    "REPORT",
    "RUN",
    "SCENE",
    "SECURITY",
    "SECURITY ARM",
    "SECURITY DISPLAY_MESSAGE",
    "SECURITY EMULATE_KEYPAD",
    "SECURITY RAISE_ALARM",
    "SECURITY REQUEST_ZONE_NAME",
    "SECURITY STATUS_REQUEST",
    "SECURITY TAMPER",
    "SESSION_ID",
    "SESSION_ID ALL",
    "SESSION_ID TAG",
    "SET",
    "SHOW",
    "SHUTDOWN",
    "SHORTMESSAGE",
    "SHORTMESSAGE REFRESH",
    "SHORTMESSAGE SEND",
    "STOP",
    "TELEPHONY",
    "TELEPHONY CLEAR_DIVERSION",
    "TELEPHONY DIVERT",
    "TELEPHONY ISOLATE_SECONDARY_OUTLET",
    "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
    "TELEPHONY REJECT_INCOMING_CALL",
    "TEMPERATURE",
    "TEMPERATURE BROADCAST",
    "TERMINATERAMP",
    "TEST_SPAM",
    "TEST_SPAM EREPORT",
    "TEST_SPAM LIGHTING",
    "TEST_SPAM LIST",
    "TEST_SPAM STOP",
    "TOPOLOGY",
    "TOPOLOGY EXPLORE",
    "TREE",
    "TREEXML",
    "TREEXMLDETAIL",
    "TRIGGER",
    "TRIGGER EVENT",
    "TRIGGER LABEL",
    "TRIGGER UNICODELABEL",
    "UNLOCK",
    "CONVERTUNIT CHECK",
    "CONVERTUNIT CONVERT",
    "DBGETJSON NAC_ROUTING_TABLE",
    "DBGETJSON",
    "DBGETJSON NAC_TAGMAP",
    "DBGETJSON NAC_OBJECTS_LIST",
    "LOG EXTRACT",
];

/// Commands whose bare form (or `?`) returns sub-command help.
pub const HELP_ROOTS: &[&str] = &[
    "AIRCON",
    "AUDIO",
    "CGL",
    "CLOCK",
    "CONFIG",
    "ENABLE",
    "EREPORT",
    "LIGHTING",
    "MEASUREMENT",
    "MEDIATRANSPORT",
    "NET",
    "NETWORK",
    "PORT",
    "PROJECT",
    "SECURITY",
    "SHORTMESSAGE",
    "TELEPHONY",
    "TEMPERATURE",
    "TEST_SPAM",
    "TOPOLOGY",
    "TRIGGER",
    "DBGETJSON",
];

/// Command sets present in the Toolkit 1.18 C-Gate 3.4 bytecode but not
/// completely described by public manual section 4.5. These names come
/// from the decompiled `*CommandSet` registration tables.
pub const DECOMPILED_COMMAND_GROUPS: &[(&str, &[&str])] = &[
    ("CALCULATOR", &["TEST"]),
    ("CGL", &["EXPORT", "IMPORT"]),
    (
        "CONFIG",
        &[
            "OBGET", "OBSET", "OBRESET", "GET", "SET", "INFO", "SAVE", "LOAD",
        ],
    ),
    (
        "PROJECT",
        &[
            "DIR", "DIRFULL", "LIST", "DELETE", "USE", "LOAD", "SAVE", "CLOSE", "START", "STOP",
            "RENAME", "COPY", "ARCHIVE", "RESTORE", "REPAIR", "NEW",
        ],
    ),
    ("REPOSITORY", &["LIST", "USE"]),
    ("LOG", &["EXTRACT"]),
    ("TOPOLOGY", &["EXPLORE"]),
    (
        "PP",
        &[
            "LOCK",
            "UNLOCK",
            "CANCEL_LOCK",
            "START",
            "END",
            "UNITS",
            "NEW",
            "DEBUG",
            "LOAD",
            "SAVE",
            "SAVE_TO_SOURCE",
            "SET",
            "GET",
            "INFO",
            "LIST_LOCK",
            "LOAD_FROM_FILE",
            "GET_UNIT_SPEC",
            "GET_UNIT_CATALOG",
            "RELOAD_CATALOG",
            "CATALOG_INFO",
            "LIST_CATALOG_NUMBERS",
            "GET_RAW_DATA",
            "SET_RAW_DATA",
            "COPY",
            "QUICKGET",
            "RESET_TO_DEFAULTS",
            "PATCH_VERSION",
            "WRITE_PATCH",
        ],
    ),
    (
        "NET",
        &[
            "LIST",
            "CREATE",
            "DELETE",
            "OPEN",
            "CLOSE",
            "LOAD",
            "SAVE",
            "PROJECT_IDENTIFY",
            "SET_PROJECT_IDENTIFY",
            "SYNC",
            "FLUSH",
            "CHECK_UNRAVEL",
            "CHECKUNIT",
            "LEARN",
            "PINGU",
            "SYNCNEW",
            "RENAME",
            "LIST_ALL",
            "STATE_INTERVAL",
            "UNRAVEL",
            "UNRAVELUNIT",
            "CLOCKS",
        ],
    ),
    ("LABEL", &["CLEAR", "CLEAREDLT", "KFIGET", "KFISET"]),
    ("TEST_SPAM", &["LIST", "LIGHTING", "EREPORT", "STOP"]),
    (
        "PORT",
        &["IFLIST", "LIST", "CNISCAN", "CNISCAN2", "PROBE", "REFRESH"],
    ),
    ("CONVERTUNIT", &["CHECK", "CONVERT"]),
    (
        "DBGETJSON",
        &["NAC_ROUTING_TABLE", "NAC_TAGMAP", "NAC_OBJECTS_LIST"],
    ),
    ("ACCESS", &["LIST", "DELETE", "ADD", "LOAD", "SAVE"]),
    ("APPLICATIONS", &["GET_CATALOG"]),
    ("IDENTIFY", &["ON", "OFF", "RAMP", "TERMINATERAMP"]),
    ("ACCESS_CONTROL", &["CLOSE", "LOCK"]),
    (
        "DEPLOY_QUEUE",
        &["ADD", "LIST", "DELETE", "DELETE_ALL", "RETRY"],
    ),
    (
        "PROGRAMMER",
        &[
            "CREATE",
            "LIST",
            "STATUS",
            "DELETE",
            "TRIGGER",
            "TEST",
            "ADD_INSTRUCTION",
            "CANCEL_INSTRUCTION",
        ],
    ),
    ("EVENT_CHANNEL", &["SUB", "UNSUB", "LIST"]),
    (
        "FILE",
        &[
            "UPLOAD", "DOWNLOAD", "SHA256", "DIR", "LS", "DELETE", "MKDIR",
        ],
    ),
    (
        "TRANSFORM",
        &[
            "PROJECT",
            "MIGRATE_SQL",
            "SQL_TO_XML",
            "SQL_TO_XML_CGATE2",
            "XML_TO_SQL",
        ],
    ),
    (
        "DALI",
        &[
            "FACTORY_RESET",
            "ADDRESS_UNKNOWN",
            "DISCOVER_KNOWN_TYPE_INFO",
            "KNOWN_TYPE_INFO",
            "KNOWN",
            "CHECK_FOR_UNKNOWN",
            "BROKEN",
            "MISSING",
            "CONFLICTING",
            "RESCAN",
            "REASSIGN_ONE",
            "SWAP_TWO",
            "REPLACE_BAD",
            "REMOVE_MANY",
            "WINK_ECG_ON",
            "WINK_ECG_OFF",
            "RECALL_MAX",
            "RECALL_MIN",
            "RECALL_OFF",
            "RECALL_MAX_MANY",
            "RECALL_OFF_MANY",
            "TRIGGER_SCENE",
            "DISCOVER_KNOWN_FULL_INFO",
            "COMMON_PARAMS",
            "COMMON_READ_ONLY_PARAMS",
            "LED_PARAMS",
            "SCENE_VALUES_HIGH",
            "SCENE_VALUES_LOW",
            "COLOUR_TYPE",
            "COLOUR_TEMPERATURE",
            "COLOUR_POWER_FAIL_PARAMS",
            "DISCOVER_GTIN_SERIAL",
            "GTIN",
            "SERIAL",
            "DISCOVER_STATUS_INFO",
            "SET_SCENE_VALUES_LOW",
            "SET_SCENE_VALUES_HIGH",
            "SET_SCENE_LEVEL_MANY",
            "SET_MIN_MANY",
            "SET_MAX_MANY",
            "SET_RECOVERY_MANY",
            "SET_FAILURE_MANY",
            "SET_GROUP_MANY",
            "REMOVE_GROUP_MANY",
            "SET_COMMON_PARAMS",
            "SET_LED_PARAMS",
            "SET_COLOUR_TEMPERATURE",
            "SET_COLOUR_POWER_FAIL_PARAMS",
            "GATEWAY",
            "EMERGENCY",
            "ERROR_REPORTING",
            "MEASUREMENT",
            "SESSION",
            "CATALOG",
        ],
    ),
    (
        "DALI GATEWAY",
        &[
            "FACTORY_RESET",
            "LOAD_PRESET",
            "RESTART",
            "SAVE_TO_NVM",
            "PAGED_RECALL",
            "PAGED_STORE",
            "READ_EXTENDED_PARAMETERS",
            "WRITE_EXTENDED_PARAMETERS",
            "SET_EXTENDED_PARAMETERS",
            "PRIMARY_ADDRESS",
            "SET_PRIMARY_ADDRESS",
            "VIRTUAL_GROUP",
            "SET_VIRTUAL_GROUP",
            "SHORT_MAP",
            "PROJECT_CUSTOM",
            "LIST",
            "DEVICE_ID_LIST",
            "NAC_SUMMARY_LIST",
        ],
    ),
    (
        "DALI EMERGENCY",
        &[
            "PARAMS",
            "STATUS",
            "SET_PARAMS",
            "SET_LEVEL_MANY",
            "SET_PROLONG_MANY",
            "SET_TEST_TIMEOUT_MANY",
            "START_FUNCTION_TEST",
            "START_DURATION_TEST",
            "STOP_TEST",
            "REST",
            "INHIBIT",
            "RELIGHT",
            "TEST_STATUS",
            "UPDATE_TEST_STATUS",
        ],
    ),
    (
        "DALI ERROR_REPORTING",
        &[
            "USED_DEVICE_MASK",
            "STORE_OPTION",
            "INTERVAL",
            "MODE",
            "ENABLE_GROUP",
            "DEVICE_ID",
            "TRIGGER_REPORT_GROUP",
            "RESEND_ACTION_SELECTOR",
            "ACK_ALL_ERRORS_ACTION_SELECTOR",
            "NETWORK_PATH",
            "SET_USED_DEVICE_MASK",
            "SET_STORE_OPTION",
            "SET_INTERVAL",
            "SET_MODE",
            "SET_ENABLE_GROUP",
            "SET_DEVICE_ID",
            "SET_TRIGGER_REPORT_GROUP",
            "SET_RESEND_ACTION_SELECTOR",
            "SET_ACK_ALL_ERRORS_ACTION_SELECTOR",
            "SET_NETWORK_PATH",
        ],
    ),
    (
        "DALI MEASUREMENT",
        &[
            "LAMP_RUNNING_TIME",
            "REQUEST_TRIGGER_GROUP",
            "CLEAR_TRIGGER_GROUP",
            "SET_LAMP_RUNNING_TIME",
            "SET_REQUEST_TRIGGER_GROUP",
            "SET_CLEAR_TRIGGER_GROUP",
        ],
    ),
    (
        "DALI SESSION",
        &[
            "LIST",
            "NEW",
            "END",
            "GET",
            "SET",
            "MULTIGET",
            "SET_EXT_PARAMS",
            "CATALOG_DEVICE_ADD",
            "CATALOG_DEVICE_REMOVE",
            "EXTRACT",
            "LOAD",
            "DEPLOY",
            "SAVE",
        ],
    ),
    ("DALI CATALOG", &["LIST", "RELOAD", "GET_SPEC"]),
];

/// A declaratively emulated application command.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ApplicationSpec {
    pub name: &'static str,
    /// Arguments following the command name.
    pub min_args: usize,
    /// `None` permits a trailing free-text field.
    pub max_args: Option<usize>,
}

/// Commands that encode one C-Bus application message. The model records
/// their last value and emits an event; real packet transport remains the
/// responsibility of a physical C-Gate/PCI connection.
pub const APPLICATION_COMMANDS: &[ApplicationSpec] = &[
    ApplicationSpec {
        name: "AIRCON REFRESH",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "AIRCON SET_HUMIDITY_SETBACK_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_HVAC_LOWER_GUARD_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_HVAC_SETBACK_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_HVAC_UPPER_GUARD_LIMIT",
        min_args: 6,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AIRCON SET_WARD_OFF",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "AIRCON SET_WARD_ON",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "AIRCON SET_ZONE_HUMIDITY_MODE",
        min_args: 11,
        max_args: Some(11),
    },
    ApplicationSpec {
        name: "AIRCON SET_ZONE_HVAC_MODE",
        min_args: 11,
        max_args: Some(11),
    },
    ApplicationSpec {
        name: "AUDIO CURRENT_FEED",
        min_args: 4,
        max_args: Some(5),
    },
    ApplicationSpec {
        name: "AUDIO DYNAMIC_1",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO DYNAMIC_2",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO HIGH_PRIORITY",
        min_args: 4,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO MUTE",
        min_args: 4,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO NEXT_FEED",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO NEXT_LANGUAGE",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO OFF",
        min_args: 3,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO ON",
        min_args: 3,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO OUTPUT_COMMON_CONTROL",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "AUDIO OUTPUT_DEVICE_STATUS_REQUEST",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "AUDIO OUTPUT_ERROR_CODE",
        min_args: 4,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO PREVIOUS_FEED",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO RAMP",
        min_args: 5,
        max_args: Some(6),
    },
    ApplicationSpec {
        name: "AUDIO REQUEST_CURRENT_FEED",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO SET_FEED",
        min_args: 4,
        max_args: Some(5),
    },
    ApplicationSpec {
        name: "AUDIO TERMINATERAMP",
        min_args: 3,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "AUDIO ZONE_DESCRIPTOR_REQUEST",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "AUDIO ZONE_FEED_LABEL_REQUEST",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "CLOCK REQUEST_REFRESH",
        min_args: 1,
        max_args: Some(1),
    },
    ApplicationSpec {
        name: "EREPORT MESSAGE",
        min_args: 8,
        max_args: Some(10),
    },
    ApplicationSpec {
        name: "MEASUREMENT DATA",
        min_args: 4,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "NETWORK LOCATE",
        min_args: 3,
        max_args: None,
    },
    ApplicationSpec {
        name: "SECURITY ARM",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SECURITY DISPLAY_MESSAGE",
        min_args: 1,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SECURITY EMULATE_KEYPAD",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SECURITY RAISE_ALARM",
        min_args: 1,
        max_args: Some(1),
    },
    ApplicationSpec {
        name: "SECURITY REQUEST_ZONE_NAME",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SECURITY STATUS_REQUEST",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SECURITY TAMPER",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SHORTMESSAGE REFRESH",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "SHORTMESSAGE SEND",
        min_args: 7,
        max_args: None,
    },
    ApplicationSpec {
        name: "TELEPHONY CLEAR_DIVERSION",
        min_args: 1,
        max_args: Some(1),
    },
    ApplicationSpec {
        name: "TELEPHONY DIVERT",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "TELEPHONY ISOLATE_SECONDARY_OUTLET",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "TELEPHONY REJECT_INCOMING_CALL",
        min_args: 1,
        max_args: Some(1),
    },
    ApplicationSpec {
        name: "TEMPERATURE BROADCAST",
        min_args: 2,
        max_args: Some(3),
    },
];

/// Media transport has a regular application/group prefix and a small
/// command-specific tail. Kept separate to make its constraints readable.
pub const MEDIA_COMMANDS: &[ApplicationSpec] = &[
    ApplicationSpec {
        name: "MEDIATRANSPORT CATEGORY_NAME",
        min_args: 5,
        max_args: None,
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT ENUMERATE",
        min_args: 4,
        max_args: Some(4),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT ENUMERATION_SIZE",
        min_args: 5,
        max_args: Some(5),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT FORWARD",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT NEXT_CATEGORY",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT NEXT_SELECTION",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT NEXT_TRACK",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT PAUSE",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT PLAY",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT REPEAT",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT REWIND",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SELECTION_NAME",
        min_args: 5,
        max_args: None,
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SET_CATEGORY",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SET_SELECTION",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SET_TRACK",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SHUFFLE",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT SOURCE_POWER",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT STATUS_REQUEST",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT STOP",
        min_args: 2,
        max_args: Some(2),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT TOTAL_TRACKS",
        min_args: 3,
        max_args: Some(3),
    },
    ApplicationSpec {
        name: "MEDIATRANSPORT TRACK_NAME",
        min_args: 5,
        max_args: None,
    },
];

/// Match a two-word application command exactly.
pub fn application_spec(words: &[&str]) -> Option<ApplicationSpec> {
    if words.len() < 2 {
        return None;
    }
    APPLICATION_COMMANDS
        .iter()
        .chain(MEDIA_COMMANDS)
        .copied()
        .find(|spec| {
            let mut name = spec.name.split_whitespace();
            words[0].eq_ignore_ascii_case(name.next().unwrap_or_default())
                && words[1].eq_ignore_ascii_case(name.next().unwrap_or_default())
                && name.next().is_none()
        })
}

pub fn is_help_root(word: &str) -> bool {
    HELP_ROOTS
        .iter()
        .any(|root| word.eq_ignore_ascii_case(root))
}

pub fn help_lines(root: &str) -> Vec<String> {
    let prefix = format!("{} ", root.to_ascii_uppercase());
    DOCUMENTED_COMMANDS
        .iter()
        .filter(|name| name.starts_with(&prefix) && !name[prefix.len()..].contains(' '))
        .map(|name| format!("101-Help: {name}"))
        .collect()
}

use super::{
    err, fresh_oid, network_path, ok, status, valid_name, valid_target, AccessLevel, DbLevel,
    DbPendingObject, Network, NetworkState, Response, Server, Unit,
};

#[derive(Clone)]
struct DatabaseCopyNode {
    element: String,
    fields: std::collections::HashMap<String, String>,
    children: Vec<DatabaseCopyNode>,
}

fn pending_key(project: &str, oid: &str) -> String {
    format!("{project}\u{1f}{oid}")
}

fn database_path_project(path: &str) -> Option<&str> {
    path.strip_prefix("//")?.split('/').next()
}

fn database_network_parent(path: &str) -> Option<(&str, u8)> {
    let parts = path.strip_prefix("//")?.split('/').collect::<Vec<_>>();
    let [project, network] = parts.as_slice() else {
        return None;
    };
    Some((*project, network.parse().ok()?))
}

fn canonical_database_element(raw: &str) -> String {
    match raw.to_ascii_uppercase().as_str() {
        "PROJECT" => "Project",
        "INSTALLATIONDETAIL" => "InstallationDetail",
        "NETWORK" => "Network",
        "INTERFACE" => "Interface",
        "UNIT" => "Unit",
        "APPLICATION" => "Application",
        "GROUP" => "Group",
        "LEVEL" => "Level",
        "NETVAR" => "NetVar",
        _ => "",
    }
    .to_string()
}

fn database_child_allowed(parent: &str, child: &str) -> bool {
    matches!(
        (parent.to_ascii_uppercase().as_str(), child),
        ("INSTALLATION", "Project")
            | ("INSTALLATION", "InstallationDetail")
            | ("PROJECT", "Network")
            | ("NETWORK", "Unit")
            | ("NETWORK", "Application")
            | ("NETWORK", "Interface")
            | ("APPLICATION", "Group")
            | ("APPLICATION", "NetVar")
            | ("GROUP", "Level")
            | ("NETVAR", "Level")
    )
}

fn database_unit_node(unit: &Unit) -> DatabaseCopyNode {
    let mut fields = unit.fields.clone();
    fields.insert("Address".to_string(), unit.address.to_string());
    fields
        .entry("TagName".to_string())
        .or_insert_with(|| unit.fields.get("UnitName").cloned().unwrap_or_default());
    if !unit.unit_type.is_empty() {
        fields.insert("UnitType".to_string(), unit.unit_type.clone());
    }
    if !unit.firmware.is_empty() {
        fields.insert("FirmwareVersion".to_string(), unit.firmware.clone());
    }
    if !unit.serial.is_empty() {
        fields.insert("SerialNumber".to_string(), unit.serial.clone());
    }
    DatabaseCopyNode {
        element: "Unit".to_string(),
        fields,
        children: Vec::new(),
    }
}

fn database_level_node(level: &DbLevel) -> DatabaseCopyNode {
    let mut fields = std::collections::HashMap::new();
    fields.insert("Address".to_string(), level.address.to_string());
    fields.insert("TagName".to_string(), level.tag.clone());
    if let Some(value) = level.value {
        fields.insert("Value".to_string(), value.to_string());
    }
    DatabaseCopyNode {
        element: if level.netvar { "NetVar" } else { "Level" }.to_string(),
        fields,
        children: Vec::new(),
    }
}

fn normalize_update_target(raw: &str, project: &str) -> String {
    if raw.starts_with("//") {
        raw.trim_end_matches('/').to_string()
    } else {
        format!("//{project}/{}", raw.trim_matches('/'))
    }
}

fn parse_update_target(
    target: &str,
    project: &str,
    record: &super::Project,
) -> Option<(u8, Option<u8>)> {
    let parts = target.strip_prefix("//")?.split('/').collect::<Vec<_>>();
    let resolve_network = |value: &str| {
        value.parse::<u8>().ok().or_else(|| {
            record
                .networks
                .iter()
                .find(|(_, network)| network.name.eq_ignore_ascii_case(value))
                .map(|(address, _)| *address)
        })
    };
    let resolve_unit = |network: u8, value: &str| {
        value.parse::<u8>().ok().or_else(|| {
            record.networks.get(&network).and_then(|network| {
                network
                    .units
                    .iter()
                    .find(|(_, unit)| {
                        unit.fields
                            .get("TagName")
                            .or_else(|| unit.fields.get("UnitName"))
                            .is_some_and(|name| name.eq_ignore_ascii_case(value))
                    })
                    .map(|(address, _)| *address)
            })
        })
    };
    match parts.as_slice() {
        [target_project, network] if *target_project == project => {
            Some((resolve_network(network)?, None))
        }
        [target_project, network, marker, unit]
            if *target_project == project && marker.eq_ignore_ascii_case("p") =>
        {
            let network = resolve_network(network)?;
            Some((network, Some(resolve_unit(network, unit)?)))
        }
        // The manual's abbreviated unit example is `p/1/22`.
        [target_project, marker, network, unit]
            if *target_project == project && marker.eq_ignore_ascii_case("p") =>
        {
            let network = resolve_network(network)?;
            Some((network, Some(resolve_unit(network, unit)?)))
        }
        _ => None,
    }
}

fn update_database_unit_from_physical(
    known_oids: &mut std::collections::HashSet<String>,
    units: &mut std::collections::HashMap<u8, Unit>,
    address: u8,
    mut physical: Unit,
) {
    let existing = units.get(&address).cloned();
    physical.address = address;
    physical
        .fields
        .insert("Address".to_string(), address.to_string());
    physical.serial_alternates.clear();
    if let Some(existing) = existing {
        physical.oid = existing.oid;
        for field in ["TagName", "UnitName", "Description", "Location"] {
            if let Some(value) = existing.fields.get(field) {
                physical.fields.insert(field.to_string(), value.clone());
            }
        }
    } else {
        physical.oid = loop {
            let candidate = fresh_oid();
            if known_oids.insert(candidate.clone()) {
                break candidate;
            }
        };
        let default_name = physical
            .fields
            .get("TagName")
            .or_else(|| physical.fields.get("UnitName"))
            .filter(|name| !name.is_empty())
            .cloned()
            .unwrap_or_else(|| "[default]".to_string());
        physical
            .fields
            .insert("TagName".to_string(), default_name.clone());
        physical
            .fields
            .entry("UnitName".to_string())
            .or_insert(default_name);
    }
    known_oids.insert(physical.oid.clone());
    units.insert(address, physical);
}

fn mirror_materialized_unit(
    pending: &mut std::collections::HashMap<String, DbPendingObject>,
    project: &str,
    path: &str,
    unit: &Unit,
) {
    let Some(object) = pending
        .values_mut()
        .find(|object| object.project == project && object.path.as_deref() == Some(path))
    else {
        return;
    };
    object
        .fields
        .insert("Address".to_string(), unit.address.to_string());
    for field in ["TagName", "UnitName", "Description", "Location"] {
        if let Some(value) = unit.fields.get(field) {
            object.fields.insert(field.to_string(), value.clone());
        }
    }
    for (field, value) in [
        ("UnitType", unit.unit_type.as_str()),
        ("FirmwareVersion", unit.firmware.as_str()),
        ("SerialNumber", unit.serial.as_str()),
    ] {
        if value.is_empty() {
            object.fields.remove(field);
        } else {
            object.fields.insert(field.to_string(), value.to_string());
        }
    }
}

fn remove_materialized_pending_path(
    pending: &mut std::collections::HashMap<String, DbPendingObject>,
    project: &str,
    path: &str,
) -> Vec<String> {
    let prefix = format!("{path}/");
    let removed = pending
        .iter()
        .filter(|(_, object)| {
            object.project == project
                && object
                    .path
                    .as_deref()
                    .is_some_and(|candidate| candidate == path || candidate.starts_with(&prefix))
        })
        .map(|(key, object)| (key.clone(), object.oid.clone()))
        .collect::<Vec<_>>();
    for (key, _) in &removed {
        pending.remove(key);
    }
    removed.into_iter().map(|(_, oid)| oid).collect()
}

/// Return the command tail after `count` whitespace-delimited arguments using
/// C-Gate's `remainingArgsAsDequotedString` rules. Quote delimiters disappear,
/// and the three native escapes (`\\`, `\"`, and `\ `) decode; unknown
/// escapes retain their backslash.
fn remaining_dequoted(body: &str, count: usize) -> String {
    let bytes = body.as_bytes();
    let mut offset = 0;
    for _ in 0..count {
        while offset < bytes.len() && bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
        while offset < bytes.len() && !bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
    }
    while offset < bytes.len() && bytes[offset].is_ascii_whitespace() {
        offset += 1;
    }

    let mut value = String::with_capacity(body.len() - offset);
    let mut chars = body[offset..].chars();
    while let Some(character) = chars.next() {
        match character {
            '"' => {}
            '\\' => match chars.clone().next() {
                Some(next @ ('\\' | '"' | ' ')) => {
                    chars.next();
                    value.push(next);
                }
                _ => value.push('\\'),
            },
            _ => value.push(character),
        }
    }
    value
}

impl Server {
    /// Handle commands whose implementation is defined by the manual
    /// registry rather than one of the richer database/network handlers.
    /// `None` means the name is not a documented command and lets the main
    /// dispatcher produce its normal 400 response.
    pub(crate) fn handle_manual_command(
        &mut self,
        tag: &str,
        words: &[&str],
        body: &str,
    ) -> Option<Response> {
        let first = words.first()?.to_ascii_uppercase();

        // Wire frontends consume untagged comments before dispatch. Once a
        // marker is tagged, native C-Gate treats it as command text and
        // rejects it.
        if first.starts_with('#') || first.starts_with("//") {
            return Some(err(tag, status::BAD_REQUEST, "400 Syntax Error."));
        }

        if first == "GET" && words.len() >= 2 {
            if let Some(response) = self.legacy_get(tag, words) {
                return Some(response);
            }
        }
        if first == "SHOW" {
            return Some(self.show_command(tag, words));
        }
        if matches!(first.as_str(), "ON" | "OFF" | "RAMP" | "TERMINATERAMP")
            || (first == "LIGHTING"
                && words.get(1).is_some_and(|word| {
                    matches!(
                        word.to_ascii_uppercase().as_str(),
                        "ON" | "OFF" | "RAMP" | "TERMINATERAMP"
                    )
                }))
        {
            return Some(self.legacy_lighting(tag, words));
        }
        if first == "DO" {
            return Some(self.do_command(tag, words));
        }
        if first == "OID" {
            // Native C-Gate 3.4 ignores trailing tokens and returns 301.  The
            // generated identity is not registered as a database object;
            // OID is only a UUID factory.
            return Some(Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: format!("301 OID={}", fresh_command_oid()),
                status: 301,
            });
        }
        if first == "NEW" {
            return Some(self.new_object(tag, words));
        }
        if first == "PROJECT" && words.len() >= 2 {
            let op = words[1].to_ascii_uppercase();
            if op == "START" || op == "STOP" {
                return Some(self.project_start_stop(tag, words, op == "START"));
            }
        }
        if first == "NET" && words.len() >= 2 {
            if let Some(response) = self.net_extension(tag, words) {
                return Some(response);
            }
        }
        if first.starts_with("DB") {
            if let Some(response) = self.database_extension(tag, words) {
                return Some(response);
            }
        }
        if first == "REPORT" {
            if words.len() < 2 {
                return Some(err(tag, status::BAD_REQUEST, "400 Syntax Error."));
            }
            let tree = ["TREE", words[1]];
            return Some(self.net_tree(tag, &tree));
        }
        if first == "RUN" {
            return Some(self.run_macro(tag, words));
        }
        if first == "SCENE" {
            return Some(self.scene_command(tag, words));
        }
        if first == "STOP" {
            return Some(self.stop_command(tag, words));
        }
        if first == "CONVERTUNIT" {
            return Some(self.convert_unit(tag, words));
        }
        if first == "FILE" {
            return Some(crate::file::command(self, tag, body, None));
        }
        if let Some(response) = self.hidden_command(tag, words) {
            return Some(response);
        }

        // Parent commands are discoverable help endpoints. Extra tokens
        // never silently become help: only the bare form and literal `?`.
        if is_help_root(&first) && (words.len() == 1 || (words.len() == 2 && words[1] == "?")) {
            return Some(help_response(tag, &first));
        }

        if first == "APIVER" {
            if words.len() > 2 || (words.len() == 2 && !words[1].eq_ignore_ascii_case("details")) {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 APIVER accepts only DETAILS",
                ));
            }
            let mut versions = vec![
                "event=1.0",
                "schema-tag=1.1",
                "schema-unitspec=1.0",
                "cmd-syntax=1.0",
                "cmd-project=1.1",
                "cmd-pp=1.1",
                "cmd-net=1.0",
                "cmd-port=1.0",
                "cmd-general=1.0",
                "cmd-cbus=1.0",
                "cmd-db=1.1",
                "scene=1.0",
            ];
            if words.len() == 2 {
                versions.push("rust-cbus-cgate=manual-3.4");
            }
            return Some(envelope(tag, 138, versions));
        }

        if first == "HELP" {
            if words.len() > 2 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 HELP takes one optional topic",
                ));
            }
            if let Some(topic) = words.get(1) {
                if let Some(rows) = general_object_help(&topic.to_ascii_uppercase()) {
                    return Some(fixed_help_response(tag, rows));
                }
            }
            let names: Vec<&str> = if let Some(topic) = words.get(1) {
                let topic = topic.to_ascii_uppercase();
                DOCUMENTED_COMMANDS
                    .iter()
                    .copied()
                    .filter(|name| *name == topic || name.starts_with(&format!("{topic} ")))
                    .collect()
            } else {
                DOCUMENTED_COMMANDS.to_vec()
            };
            if names.is_empty() {
                return Some(err(tag, status::NOT_FOUND, "404 Help topic not found"));
            }
            return Some(envelope(
                tag,
                101,
                names.into_iter().map(|n| format!("Help: {n}")),
            ));
        }

        if first == "BROADCAST_EVENT" {
            if words.len() < 2 {
                return Some(err(tag, status::BAD_REQUEST, "400 Syntax Error."));
            }
            self.push_event(self.broadcast_event_line(words[1], &remaining_dequoted(body, 2)));
            return Some(ok(tag, vec![], "200 OK."));
        }

        if first == "CLOCK" && words.len() >= 2 {
            match words[1].to_ascii_uppercase().as_str() {
                "DATE" => return Some(self.clock_value(tag, words, true)),
                "TIME" => return Some(self.clock_value(tag, words, false)),
                _ => {}
            }
        }

        if first == "CONFIG" && words.len() >= 2 {
            return Some(self.config_command(tag, words));
        }

        if first == "SESSION_ID" {
            return Some(self.session_id_command(tag, words, body));
        }

        if first == "LOCK" || first == "UNLOCK" {
            return Some(self.advisory_lock_command(tag, words, first == "LOCK"));
        }

        if first == "SHUTDOWN" {
            if words.len() != 1 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 SHUTDOWN takes no arguments",
                ));
            }
            self.shutdown_pending = true;
            return Some(Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: "600 Confirm shutdown with CONFIRM".to_string(),
                status: 600,
            });
        }
        if first == "CONFIRM" {
            if words.len() != 1 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 CONFIRM takes no arguments",
                ));
            }
            if !self.shutdown_pending {
                return Some(err(
                    tag,
                    status::CONFLICT_STATE,
                    "408 No operation awaiting confirmation",
                ));
            }
            self.shutdown_pending = false;
            return Some(Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: "206 Shutdown confirmed (model remains available)".to_string(),
                status: 206,
            });
        }

        if first == "PORT" {
            if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
                return Some(crate::port::help(tag));
            }
            return Some(self.port_command(tag, words));
        }
        if first == "TOPOLOGY" && words.len() >= 2 {
            return Some(self.topology_command(tag, words));
        }
        if first == "TEST_SPAM" && words.len() >= 2 {
            return Some(self.test_spam_command(tag, words));
        }
        if first == "DBGETJSON" {
            return Some(self.dbgetjson_command(tag, words));
        }
        if first == "LOG"
            && words
                .get(1)
                .is_some_and(|w| w.eq_ignore_ascii_case("EXTRACT"))
        {
            return Some(self.log_extract(tag, words, body));
        }

        if let Some(spec) = application_spec(words) {
            let args = &words[2..];
            if args.len() < spec.min_args || spec.max_args.is_some_and(|max| args.len() > max) {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    &format!("400 {} has invalid arguments", spec.name),
                ));
            }
            if args.first().is_some_and(|v| !valid_target(v)) {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 Invalid application address",
                ));
            }
            self.application_state
                .insert(spec.name.to_string(), args.join(" "));
            self.push_event(format!(
                "#e# {} {}",
                spec.name.to_ascii_lowercase(),
                args.join(" ")
            ));
            return Some(ok(tag, vec![], "200 OK."));
        }

        None
    }

    fn clock_value(&mut self, tag: &str, words: &[&str], date: bool) -> Response {
        if !(3..=4).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 CLOCK command requires an application and optional value",
            );
        }
        let key = if date { "CLOCK DATE" } else { "CLOCK TIME" };
        let value = if let Some(value) = words.get(3) {
            let value = if value.eq_ignore_ascii_case("system") {
                if date {
                    "1970-01-01"
                } else {
                    "00:00:00"
                }
            } else {
                value
            };
            if (date && !valid_date(value)) || (!date && !valid_time(value)) {
                return err(tag, status::BAD_REQUEST, "405 Parameter out of range");
            }
            self.application_state
                .insert(key.to_string(), value.to_string());
            value.to_string()
        } else {
            self.application_state.get(key).cloned().unwrap_or_else(|| {
                if date {
                    "1970-01-01".to_string()
                } else {
                    "00:00:00".to_string()
                }
            })
        };
        Response {
            tag: tag.to_string(),
            lines: vec![],
            final_text: format!("232 {} set to: {value}", if date { "Date" } else { "Time" }),
            status: 232,
        }
    }

    fn config_command(&mut self, tag: &str, words: &[&str]) -> Response {
        let op = words[1].to_ascii_uppercase();
        match op.as_str() {
            "GET" | "INFO" if words.len() == 3 => {
                let key = words[2];
                if key == "*" {
                    let mut rows: Vec<String> = self
                        .config_values
                        .iter()
                        .map(|(k, v)| format!("{k}={v}"))
                        .collect();
                    rows.sort();
                    if rows.is_empty() {
                        rows.push("model=rust-cbus-cgate".to_string());
                    }
                    envelope(tag, 303, rows)
                } else if let Some(value) = self.config_values.get(key) {
                    envelope(tag, 303, [format!("{key}={value}")])
                } else if op == "INFO" {
                    envelope(tag, 303, [format!("{key}: unset model parameter")])
                } else {
                    err(
                        tag,
                        status::CONFLICT_STATE,
                        "408 Config parameter not found",
                    )
                }
            }
            "SET" if words.len() >= 3 => {
                self.config_values.insert(
                    words[2].to_string(),
                    words.get(3..).unwrap_or_default().join(" "),
                );
                ok(tag, vec![], "200 OK")
            }
            "OBGET" if words.len() == 4 => {
                let key = format!("{}:{}", words[2], words[3]);
                if words[3] == "*" {
                    let prefix = format!("{}:", words[2]);
                    let rows: Vec<String> = self
                        .config_values
                        .iter()
                        .filter(|(k, _)| k.starts_with(&prefix))
                        .map(|(k, v)| format!("{}={v}", &k[prefix.len()..]))
                        .collect();
                    envelope(tag, 303, rows)
                } else if let Some(value) = self.config_values.get(&key) {
                    envelope(tag, 303, [format!("{}={value}", words[3])])
                } else {
                    err(
                        tag,
                        status::CONFLICT_STATE,
                        "408 Config parameter not found",
                    )
                }
            }
            "OBSET" if words.len() >= 4 => {
                let key = format!("{}:{}", words[2], words[3]);
                self.config_values
                    .insert(key, words.get(4..).unwrap_or_default().join(" "));
                ok(tag, vec![], "200 OK")
            }
            "OBRESET" if (3..=4).contains(&words.len()) => {
                let prefix = format!("{}:", words[2]);
                if let Some(key) = words.get(3) {
                    self.config_values.remove(&format!("{prefix}{key}"));
                } else {
                    self.config_values.retain(|k, _| !k.starts_with(&prefix));
                }
                ok(tag, vec![], "200 OK")
            }
            "LOAD" | "SAVE"
                if (3..=4).contains(&words.len())
                    && matches!(
                        words[2].to_ascii_uppercase().as_str(),
                        "PROJECT" | "GLOBAL" | "ALL"
                    ) =>
            {
                ok(tag, vec![], "200 OK")
            }
            _ => err(tag, status::BAD_REQUEST, "400 Invalid CONFIG command"),
        }
    }

    fn session_id_command(&mut self, tag: &str, words: &[&str], body: &str) -> Response {
        match words.get(1).map(|w| w.to_ascii_uppercase()) {
            None if words.len() == 1 => envelope(
                tag,
                316,
                [format!(
                    "session={} tag={}",
                    tag,
                    self.session_tag.as_deref().unwrap_or("")
                )],
            ),
            Some(op) if op == "ALL" && words.len() == 2 => envelope(
                tag,
                316,
                [format!(
                    "session={} tag={}",
                    tag,
                    self.session_tag.as_deref().unwrap_or("")
                )],
            ),
            Some(op) if op == "TAG" && words.len() >= 3 => {
                let marker = body.to_ascii_uppercase().find("TAG").unwrap_or(0) + 3;
                self.session_tag = Some(body[marker..].trim().to_string());
                ok(tag, vec![], "200 OK")
            }
            _ => err(tag, status::BAD_REQUEST, "400 Invalid SESSION_ID command"),
        }
    }

    fn advisory_lock_command(&mut self, tag: &str, words: &[&str], lock: bool) -> Response {
        if words.len() != 2 || !valid_target(words[1]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 LOCK/UNLOCK requires an object identifier",
            );
        }
        if lock {
            if !self.advisory_locks.insert(words[1].to_string()) {
                return err(tag, 425, "425 Object already locked");
            }
            Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: format!("225 {}: Locked", words[1]),
                status: 225,
            }
        } else if self.advisory_locks.remove(words[1]) {
            Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: format!("226 {}: Unlocked", words[1]),
                status: 226,
            }
        } else {
            err(tag, status::NOT_FOUND, "401 Object is not locked")
        }
    }

    fn port_command(&self, tag: &str, words: &[&str]) -> Response {
        match words[1].to_ascii_uppercase().as_str() {
            "LIST" if words.len() == 2 => envelope(tag, 126, ["no ports found"]),
            "IFLIST" if words.len() == 2 => envelope(tag, 128, ["no interfaces found"]),
            "REFRESH" if words.len() == 2 => err(
                tag,
                status::CONFLICT_STATE,
                "408 Operation failed: This command is not applicable.  The list of ports is automatically updated.",
            ),
            "CNISCAN" if crate::port::parse_scan_args(words, false).is_some() => {
                envelope(tag, 130, ["no CNIs found"])
            }
            "CNISCAN2" if crate::port::parse_scan_args(words, true).is_some() => {
                envelope(tag, 130, ["no CNIs found"])
            }
            // Native PROBE consumes type/address and ignores later tokens.
            "PROBE" if words.len() >= 4 => {
                match crate::port::validate_probe_target(words[2], words[3]) {
                    Ok(()) => err(
                        tag,
                        status::CONFLICT_STATE,
                        "408 Operation failed: No response/timeout",
                    ),
                    Err((status, response)) => err(tag, status, &response),
                }
            }
            _ => err(tag, status::BAD_REQUEST, "400 Syntax Error."),
        }
    }

    fn topology_command(&self, tag: &str, words: &[&str]) -> Response {
        if words[1].eq_ignore_ascii_case("EXPLORE") && words.len() >= 3 {
            // An empty discovery is a valid result in a hardware-free model.
            ok(tag, vec![], "200 OK")
        } else {
            err(
                tag,
                status::BAD_REQUEST,
                "400 TOPOLOGY EXPLORE requires interfaces",
            )
        }
    }

    fn test_spam_command(&mut self, tag: &str, words: &[&str]) -> Response {
        match words[1].to_ascii_uppercase().as_str() {
            "EREPORT" | "LIGHTING" if (4..=5).contains(&words.len()) => {
                let id = self.application_state.len() + 1;
                self.application_state
                    .insert(format!("TEST_SPAM {id}"), words[1..].join(" "));
                ok(tag, vec![format!("id={id}")], "200 OK.")
            }
            "LIST" if words.len() == 2 => {
                let mut rows: Vec<_> = self
                    .application_state
                    .iter()
                    .filter(|(k, _)| k.starts_with("TEST_SPAM "))
                    .map(|(k, v)| format!("{}={v}", k.replace(' ', "_")))
                    .collect();
                rows.sort();
                ok(tag, rows, "200 OK.")
            }
            "STOP" if (2..=3).contains(&words.len()) => {
                if let Some(id) = words.get(2) {
                    self.application_state.remove(&format!("TEST_SPAM {id}"));
                } else {
                    self.application_state
                        .retain(|k, _| !k.starts_with("TEST_SPAM "));
                }
                ok(tag, vec![], "200 OK.")
            }
            _ => err(tag, status::BAD_REQUEST, "400 Invalid TEST_SPAM command"),
        }
    }

    fn dbgetjson_command(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3
            || !matches!(
                words[1].to_ascii_uppercase().as_str(),
                "NAC_ROUTING_TABLE" | "NAC_TAGMAP" | "NAC_OBJECTS_LIST"
            )
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBGETJSON requires a NAC query and unit address",
            );
        }
        Response {
            tag: tag.to_string(),
            lines: vec!["345-Begin JSON".to_string(), "346-[]".to_string()],
            final_text: "346 End JSON".to_string(),
            status: 346,
        }
    }

    fn log_extract(&self, tag: &str, words: &[&str], body: &str) -> Response {
        if words.len() < 4 || words[2].parse::<u32>().is_err() {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 LOG EXTRACT requires days and destination path",
            );
        }
        // Paths may contain spaces; validate that the original tail exists.
        if body
            .splitn(4, ' ')
            .nth(3)
            .is_none_or(|p| p.trim().is_empty())
        {
            return err(tag, status::BAD_REQUEST, "400 Destination path is required");
        }
        ok(tag, vec![], "200 OK.")
    }

    fn legacy_get(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        if words.len() == 3
            && words[1].eq_ignore_ascii_case("CBUS")
            && words[2].eq_ignore_ascii_case("NETWORKS")
        {
            let current = self.current.clone()?;
            let mut nets: Vec<u8> = self
                .projects
                .get(&current)?
                .networks
                .keys()
                .copied()
                .collect();
            nets.sort_unstable();
            return Some(envelope(
                tag,
                300,
                nets.into_iter().map(|net| format!("//{current}/{net}")),
            ));
        }
        if words.len() != 3 {
            return None;
        }
        // Fully qualified addresses use the modern GET property envelope;
        // the legacy collection spelling is the bare-network form only.
        if words[1].starts_with("//") {
            return None;
        }
        let attribute = words[2].to_ascii_uppercase();
        if !matches!(
            attribute.as_str(),
            "GROUP" | "GROUPS" | "APPLICATION" | "APPLICATIONS" | "UNIT" | "UNITS"
        ) {
            return None;
        }
        let current = match self.current.clone() {
            Some(name) => name,
            None => return Some(err(tag, status::NOT_FOUND, "404 No project selected")),
        };
        let raw = words[1].trim_matches('/');
        let net = raw
            .rsplit('/')
            .next()
            .and_then(|value| value.parse::<u8>().ok());
        let Some(network) = net.and_then(|net| self.projects.get(&current)?.networks.get(&net))
        else {
            return Some(err(tag, status::NOT_FOUND, "404 Network not found"));
        };
        let mut values = Vec::new();
        match attribute.as_str() {
            "UNIT" | "UNITS" => {
                let mut addresses: Vec<u8> = network.physical.keys().copied().collect();
                addresses.sort_unstable();
                values.extend(
                    addresses
                        .into_iter()
                        .map(|address| format!("unit={address}")),
                );
            }
            "APPLICATION" | "APPLICATIONS" => {
                let mut applications: Vec<u8> =
                    network.levels.keys().map(|(app, _)| *app).collect();
                applications.sort_unstable();
                applications.dedup();
                values.extend(
                    applications
                        .into_iter()
                        .map(|app| format!("application={app}")),
                );
            }
            _ => {
                let mut groups: Vec<(u8, u8)> = network.levels.keys().copied().collect();
                groups.sort_unstable();
                values.extend(
                    groups
                        .into_iter()
                        .map(|(app, group)| format!("group={app}/{group}")),
                );
            }
        }
        Some(envelope(tag, 300, values))
    }

    fn show_command(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        }
        let mut get_words = Vec::with_capacity(3);
        get_words.push("GET");
        get_words.extend_from_slice(&words[1..3]);
        if let Some(response) = self.legacy_get(tag, &get_words) {
            response
        } else {
            self.get(tag, &get_words)
        }
    }

    pub(crate) fn qualify_group(&self, raw: &str) -> Option<String> {
        if raw.starts_with("//") {
            return Some(raw.to_string());
        }
        let current = self.current.as_ref()?;
        let trimmed = raw.trim_start_matches('/');
        if trimmed.split('/').count() == 3 {
            Some(format!("//{current}/{trimmed}"))
        } else {
            None
        }
    }

    /// Resolve the local value of a durable group created/imported in the
    /// database. This lets the hardware service distinguish a database-backed
    /// zero from the absence of any live bus observation.
    pub(crate) fn durable_group_level(&self, raw: &str) -> Option<(String, u8)> {
        let path = self.qualify_group(raw)?;
        let durable = self.objects.contains(&path)
            || self
                .db_fields
                .keys()
                .any(|field| field.starts_with(&format!("{path}/")));
        if !durable {
            return None;
        }
        let (project, network, application, group) = Self::split_lighting(&path)?;
        let level = self
            .projects
            .get(&project)
            .and_then(|project| project.networks.get(&network))
            .and_then(|network| network.levels.get(&(application, group)))
            .copied()
            .or_else(|| {
                self.db_fields
                    .get(&format!("{path}/Level"))
                    .and_then(|level| level.parse::<u8>().ok())
            })
            .unwrap_or(0);
        Some((path, level))
    }

    fn legacy_lighting(&mut self, tag: &str, words: &[&str]) -> Response {
        let (verb, address_index, tail_index) = if words[0].eq_ignore_ascii_case("LIGHTING") {
            if words.len() < 3 {
                return err(
                    tag,
                    status::BAD_REQUEST,
                    "400 LIGHTING command requires an address",
                );
            }
            (words[1].to_ascii_uppercase(), 2, 3)
        } else {
            (words[0].to_ascii_uppercase(), 1, 2)
        };
        let Some(raw_address) = words.get(address_index) else {
            return err(tag, status::BAD_REQUEST, "400 Lighting address required");
        };
        let Some(address) = self.qualify_group(raw_address) else {
            return err(tag, status::BAD_REQUEST, "400 Invalid lighting address");
        };
        let mut command = vec!["LIGHTING".to_string()];
        match verb.as_str() {
            "ON" | "OFF" => {
                if words.len() > tail_index + 1
                    || words
                        .get(tail_index)
                        .is_some_and(|w| !w.eq_ignore_ascii_case("FORCE"))
                {
                    return err(tag, status::BAD_REQUEST, "400 Invalid lighting option");
                }
                command.push(verb);
                command.push(address);
            }
            "TERMINATERAMP" => {
                if words.len() > tail_index + 1
                    || words
                        .get(tail_index)
                        .is_some_and(|w| !w.eq_ignore_ascii_case("FORCE"))
                {
                    return err(tag, status::BAD_REQUEST, "400 Invalid TERMINATERAMP option");
                }
                command.push("STOP".to_string());
                command.push(address);
            }
            "RAMP" => {
                let Some(level_text) = words.get(tail_index) else {
                    return err(tag, status::BAD_REQUEST, "400 RAMP requires a level");
                };
                let level = if let Some(percent) = level_text.strip_suffix('%') {
                    let percent: i64 = percent.parse().unwrap_or(-1);
                    if !(0..=100).contains(&percent) {
                        return err(tag, status::BAD_REQUEST, "405 Parameter out of range");
                    }
                    ((percent * 255 + 50) / 100) as u8
                } else {
                    let value: i64 = level_text.parse().unwrap_or(-1);
                    if !(0..=255).contains(&value) {
                        return err(tag, status::BAD_REQUEST, "405 Parameter out of range");
                    }
                    value as u8
                };
                let ramp = match words.get(tail_index + 1) {
                    None => 0_i64,
                    Some(value) if value.eq_ignore_ascii_case("FORCE") => 0,
                    Some(value) => match parse_duration(value) {
                        Some(seconds) => seconds,
                        None => return err(tag, status::BAD_REQUEST, "405 Invalid ramp time"),
                    },
                };
                if let Some(force) = words.get(tail_index + 2) {
                    if !force.eq_ignore_ascii_case("FORCE") || words.len() != tail_index + 3 {
                        return err(tag, status::BAD_REQUEST, "400 Invalid RAMP option");
                    }
                }
                command.extend([
                    "RAMP".to_string(),
                    address,
                    level.to_string(),
                    ramp.to_string(),
                ]);
            }
            _ => return err(tag, status::BAD_REQUEST, "400 Unknown lighting verb"),
        }
        let refs: Vec<&str> = command.iter().map(String::as_str).collect();
        self.lighting(tag, &refs)
    }

    fn do_command(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DO requires an object and method",
            );
        }
        let method = words[2].to_ascii_uppercase();
        let mut alias = vec![method.clone(), words[1].to_string()];
        alias.extend(words[3..].iter().map(|word| (*word).to_string()));
        let refs: Vec<&str> = alias.iter().map(String::as_str).collect();
        let response = if matches!(method.as_str(), "ON" | "OFF" | "RAMP" | "TERMINATERAMP") {
            self.legacy_lighting(tag, &refs)
        } else if method == "SYNC" {
            let args = ["NET", "SYNC", words[1]];
            self.net_sync(tag, &args)
        } else if method == "UNRAVEL" {
            let args = ["NET", "UNRAVEL", words[1]];
            self.net_unravel(tag, &args)
        } else if method == "FACTORYDEFAULT" {
            if words.len() != 3 || !valid_target(words[1]) {
                return err(
                    tag,
                    status::BAD_REQUEST,
                    "400 FactoryDefault requires one unit object",
                );
            }
            let Some((project, network, unit)) = self.unit_of(words[1]) else {
                return err(tag, status::ABSENT, "401 Unit not found");
            };
            if project != self.current.clone().unwrap_or_default() {
                return err(tag, status::NOT_FOUND, "404 Project not selected");
            }
            let Some(record) = self
                .projects
                .get(&project)
                .and_then(|project| project.networks.get(&network))
                .and_then(|network| network.units.get(&unit))
            else {
                return err(tag, status::ABSENT, "401 Unit not found");
            };
            if !record.unit_type.eq_ignore_ascii_case("KEYGL5") {
                return err(tag, 402, "402 Method not supported by object");
            }
            // Deterministic mock acceptance only. The hardware-backed service
            // intercepts this method and sends the native OEM control; without
            // a UnitSpec the mock must not invent post-reset PP values.
            ok(tag, vec![], "200 OK")
        } else {
            return err(tag, 402, "402 Method not supported by object");
        };
        if response.status >= 400 {
            response
        } else {
            Response {
                tag: tag.to_string(),
                lines: response.lines,
                final_text: format!("202 Done: {}", words[1]),
                status: 202,
            }
        }
    }

    fn new_object(&mut self, tag: &str, words: &[&str]) -> Response {
        if matches!(self.access, AccessLevel::Admin | AccessLevel::Monitor) {
            return err(tag, status::ACCESS_DENIED, "420 Access denied");
        }
        let Some(kind) = words.get(1).map(|kind| kind.to_ascii_uppercase()) else {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        };
        let Some(target) = words.get(2).copied() else {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        };
        if !valid_target(target) {
            return err(tag, status::BAD_REQUEST, "400 Invalid object identifier");
        }
        match kind.as_str() {
            "NETWORK" => err(
                tag,
                402,
                "402 Operation not supported by: C-Gate. Define networks with NET CREATE",
            ),
            "CGROUP" => err(
                tag,
                402,
                "402 Operation not supported by: Define cgroups in the startup igroups file",
            ),
            "AREA" => err(
                tag,
                402,
                "402 Operation not supported by: Define areas with the area suffix in a new group definition",
            ),
            "IGROUP" => err(tag, status::BAD_REQUEST, "400 Syntax Error."),
            "UNIT" => {
                let (Some(unit_type), Some(firmware)) = (words.get(3), words.get(4)) else {
                    return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
                };
                let unit_type = unit_type.trim_matches('"').to_string();
                let firmware = firmware.trim_matches('"').to_string();
                let numeric_components = || {
                    firmware
                        .split('.')
                        .all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
                };
                let keye1_version = || {
                    firmware.as_bytes().first().is_some_and(u8::is_ascii_digit)
                        && firmware
                            .bytes()
                            .all(|byte| byte.is_ascii_digit() || byte == b'.')
                };
                let invalid_firmware = match unit_type.as_str() {
                    "DIMMER4" | "RELAY4" => !numeric_components(),
                    "KEYE1" => !keye1_version(),
                    _ => false,
                };
                if invalid_firmware {
                    return err(tag, 500, "500 Internal error.");
                }
                #[derive(Clone, Copy)]
                enum NativeUnitClass {
                    Generic,
                    NeoInput,
                    Dimmer4,
                    Relay4,
                }
                let native_class = match (unit_type.as_str(), firmware.as_str()) {
                    ("KEYE1", "2.5.00") => NativeUnitClass::NeoInput,
                    ("DIMMER4", "1.0.00") => NativeUnitClass::Dimmer4,
                    ("RELAY4", "1.0.00") => NativeUnitClass::Relay4,
                    _ => NativeUnitClass::Generic,
                };
                let catalog_number = if matches!(native_class, NativeUnitClass::NeoInput) {
                    self.catalog()
                        .ok()
                        .and_then(|catalog| {
                            catalog
                                .matching(&unit_type, &firmware)
                                .first()
                                .map(|entry| entry.catalog_number.clone())
                        })
                        .unwrap_or_else(|| "5031NMML".to_string())
                } else {
                    String::new()
                };
                let Some(path) = self.qualify_unit(target) else {
                    return err(tag, status::BAD_REQUEST, "400 Invalid unit address");
                };
                let unit_parts = path
                    .trim_start_matches('/')
                    .split('/')
                    .collect::<Vec<_>>();
                if unit_parts.len() != 4 || !unit_parts[2].eq_ignore_ascii_case("p") {
                    return err(tag, status::BAD_REQUEST, "400 Invalid unit address");
                }
                let Some((project, network, address)) = self.unit_of(&path) else {
                    return err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {target} (Network not found)"),
                    );
                };
                if self.current.as_deref() != Some(project.as_str()) {
                    return err(tag, status::NOT_FOUND, "404 Project not selected");
                }
                let network = self
                    .projects
                    .get_mut(&project)
                    .and_then(|project| project.networks.get_mut(&network))
                    .expect("unit_of established the network");
                if network.units.contains_key(&address) {
                    return ok(tag, vec![], "200 OK.");
                }
                let mut unit = super::Unit::blank(address, "");
                unit.unit_type = unit_type;
                unit.firmware = firmware;
                unit.created_by_new = true;
                unit.fields.clear();
                for (name, value) in [
                    ("Address", address.to_string()),
                    ("Application", "255".to_string()),
                    ("Application2", "255".to_string()),
                    (
                        "ClassName",
                        match native_class {
                            NativeUnitClass::Generic => "com.clipsal.cgate.cbus.core.CBusUnit",
                            NativeUnitClass::NeoInput => {
                                "com.clipsal.cgate.cbus.dev.CBusNeoInputUnit"
                            }
                            NativeUnitClass::Dimmer4 => {
                                "com.clipsal.cgate.cbus.dev.CBusDimmerUnit"
                            }
                            NativeUnitClass::Relay4 => {
                                "com.clipsal.cgate.cbus.dev.CBusRelayUnit"
                            }
                        }
                        .to_string(),
                    ),
                    ("CatalogNumber", catalog_number),
                    ("ErrorFlags", "0".to_string()),
                    ("EventLevel", "9".to_string()),
                    ("Name", String::new()),
                    ("PartName", String::new()),
                    ("PatchVersion", "255".to_string()),
                    ("ProjectName", String::new()),
                    ("PSyncTime", "300".to_string()),
                    ("ShortName", String::new()),
                    ("SlotGroups", String::new()),
                    ("State", "new".to_string()),
                    ("Type", unit.unit_type.clone()),
                    ("UnitBlock", String::new()),
                    ("Version", unit.firmware.clone()),
                    ("Version2", "null".to_string()),
                ] {
                    unit.fields.insert(name.to_string(), value);
                }
                match native_class {
                    NativeUnitClass::NeoInput => {
                        for (name, value) in [
                            ("Area", "255"),
                            ("BlockApplications", "0,0,0,0,0,0,0,0,0"),
                            ("BlockGroups", "255,255,255,255,255,255,255,255,255"),
                            ("BurdenActive", "no"),
                            ("ClockGenActive", "no"),
                            ("GeneratingClock", "no"),
                            ("Groups", ""),
                            ("LearnActive", "no"),
                            ("NetVoltage", "0.5"),
                            ("Serial", "0.0"),
                            ("SerialNumber", "0.0"),
                            ("SlotGroups", "255,255,255,255,255,255,255,255,255"),
                            ("State", "error"),
                            ("SummaryFlags", "0"),
                        ] {
                            unit.fields.insert(name.to_string(), value.to_string());
                        }
                    }
                    NativeUnitClass::Dimmer4 | NativeUnitClass::Relay4 => {
                        for (name, value) in [
                            ("Area", "255"),
                            ("Groups", ""),
                            ("SlotGroups", "255,255,255,255,255,255"),
                            ("TerminalCount", "4"),
                            ("Terminals", "1,2,3,4"),
                        ] {
                            unit.fields.insert(name.to_string(), value.to_string());
                        }
                    }
                    NativeUnitClass::Generic => {}
                }
                self.known_oids.insert(unit.oid.clone());
                network.units.insert(address, unit);
                ok(tag, vec![], "200 OK.")
            }
            "GROUP" | "PHANTOM" => {
                let Some(path) = self.qualify_group(target) else {
                    return err(tag, status::BAD_REQUEST, "400 Invalid group address");
                };
                let parts = path
                    .trim_start_matches('/')
                    .split('/')
                    .collect::<Vec<_>>();
                let [project, network, application, group] = parts.as_slice() else {
                    return err(tag, status::BAD_REQUEST, "400 Invalid group address");
                };
                let (Ok(network), Ok(application), Ok(_group)) = (
                    network.parse::<u8>(),
                    application.parse::<u8>(),
                    group.parse::<u8>(),
                ) else {
                    return err(tag, status::BAD_REQUEST, "400 Invalid group address");
                };
                if self.current.as_deref() != Some(*project)
                    || !self
                        .projects
                        .get(*project)
                        .is_some_and(|project| project.networks.contains_key(&network))
                {
                    return err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {target} (Network not found)"),
                    );
                }
                let application_path = format!("//{project}/{network}/{application}");
                if matches!(application, 192 | 223 | 224) {
                    // Native creates the application object while rejecting
                    // child-address creation for these objectless classes.
                    self.objects.insert(application_path.clone());
                }
                if matches!(application, 192 | 255) {
                    return err(
                        tag,
                        status::ABSENT,
                        &format!(
                            "401 Bad object or device ID: {path} (Address not supported by application)"
                        ),
                    );
                }
                if matches!(application, 223 | 224) {
                    return err(
                        tag,
                        status::ABSENT,
                        &format!("401 Bad object or device ID: {path} (Object not found)"),
                    );
                }
                self.objects.insert(application_path);
                if self.objects.contains(&path)
                    || self
                        .db_fields
                        .keys()
                        .any(|field| field.starts_with(&format!("{path}/")))
                {
                    return ok(tag, vec![], "200 OK.");
                }
                let initial_level = if kind == "PHANTOM" {
                    match words.get(3) {
                        None => {
                            return err(
                                tag,
                                status::ABSENT,
                                &format!(
                                    "401 Bad object or device ID: {target} (Bad initial level for phantom)"
                                ),
                            )
                        }
                        Some(value) => match value.parse::<u8>() {
                            Ok(value) => value,
                            Err(_) => {
                                return err(
                                    tag,
                                    status::ABSENT,
                                    &format!(
                                        "401 Bad object or device ID: {target} (Bad initial level for phantom)"
                                    ),
                                )
                            }
                        },
                    }
                } else {
                    0
                };
                self.objects.insert(path.clone());
                self.db_fields
                    .insert(format!("{path}/Type"), "group".to_string());
                self.db_fields
                    .insert(format!("{path}/Level"), "0".to_string());
                if kind == "PHANTOM" {
                    self.db_fields.insert(
                        format!("{path}/PhantomInitialLevel"),
                        initial_level.to_string(),
                    );
                }
                self.db_fields
                    .insert(format!("{path}/State"), "new".to_string());
                // Keep the variables used above intentionally validated and
                // documented in the stored canonical address.
                let _ = (application, group);
                ok(tag, vec![], "200 OK.")
            }
            _ => err(tag, status::BAD_REQUEST, "400 Syntax Error."),
        }
    }

    fn project_start_stop(&mut self, tag: &str, words: &[&str], start: bool) -> Response {
        if words.len() > 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT START/STOP takes one optional name",
            );
        }
        if start {
            if let Some(name) = words.get(2) {
                let args = ["PROJECT", "USE", *name];
                self.project_use(tag, &args)
            } else if self.current.is_some() {
                ok(tag, vec![], "200 OK")
            } else {
                err(tag, status::NOT_FOUND, "404 No project selected")
            }
        } else {
            if let Some(name) = words.get(2) {
                if self.current.as_deref() != Some(*name) || !self.projects.contains_key(*name) {
                    return err(tag, status::NOT_FOUND, "404 Project not open");
                }
            }
            self.project_close(tag)
        }
    }

    fn net_extension(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let op = words[1].to_ascii_uppercase();
        if matches!(op.as_str(), "LOAD" | "SAVE")
            && matches!(self.access, AccessLevel::Admin | AccessLevel::Monitor)
        {
            return Some(err(tag, status::ACCESS_DENIED, "420 Access denied"));
        }
        match op.as_str() {
            "CREATE" => Some(self.net_create(tag, words)),
            "DELETE" => Some(self.net_delete(tag, words)),
            "FLUSH" => Some(if words.len() == 3 {
                match self.require_network(tag, words[2]) {
                    Ok(_) => ok(tag, vec![], "200 OK"),
                    Err(response) => response,
                }
            } else {
                err(tag, status::BAD_REQUEST, "400 NET FLUSH requires a network")
            }),
            "LEARN" => Some(if words.len() == 6 {
                self.push_event(format!("#e# net learn {}", words[2..].join(" ")));
                ok(tag, vec![], "200 OK")
            } else {
                err(
                    tag,
                    status::BAD_REQUEST,
                    "400 NET LEARN requires network, application, grade and group",
                )
            }),
            "LOAD" | "SAVE" => Some(
                if (3..=4).contains(&words.len())
                    && matches!(words[2].to_ascii_uppercase().as_str(), "DB" | "FILE")
                {
                    ok(tag, vec![], "200 OK")
                } else {
                    err(
                        tag,
                        status::BAD_REQUEST,
                        "400 NET LOAD/SAVE requires DB or FILE",
                    )
                },
            ),
            "PROJECT_IDENTIFY" => Some(if words.len() == 3 {
                envelope(
                    tag,
                    302,
                    [format!(
                        "interface={} project={}",
                        words[2],
                        self.current.as_deref().unwrap_or("")
                    )],
                )
            } else {
                err(
                    tag,
                    status::BAD_REQUEST,
                    "400 NET PROJECT_IDENTIFY requires an interface",
                )
            }),
            _ => None,
        }
    }

    fn net_create(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 5 || !valid_name(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET CREATE requires name, type and interface address",
            );
        }
        let Some(project) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(address) = words[2]
            .parse::<u8>()
            .ok()
            .filter(|address| !project.networks.contains_key(address))
            .or_else(|| {
                (0_u16..=255)
                    .map(|n| n as u8)
                    .find(|n| !project.networks.contains_key(n))
            })
        else {
            return err(
                tag,
                status::CONFLICT_EXISTS,
                "409 No network address available",
            );
        };
        let oid = super::fresh_oid();
        project.networks.insert(
            address,
            Network {
                oid: oid.clone(),
                address,
                name: words[2].to_string(),
                iface_type: words[3].to_string(),
                iface_addr: words[4..].join(" "),
                state: NetworkState::Closed,
                retries: 2,
                units: Default::default(),
                physical: Default::default(),
                levels: Default::default(),
            },
        );
        self.known_oids.insert(oid);
        ok(tag, vec![], "200 OK.")
    }

    fn net_delete(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET DELETE requires a network",
            );
        }
        let (project_name, net) = match self.require_network(tag, words[2]) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let removed = self
            .projects
            .get_mut(&project_name)
            .expect("network resolved")
            .networks
            .remove(&net);
        if let Some(network) = removed {
            let in_use = self.projects.values().any(|project| {
                project
                    .networks
                    .values()
                    .any(|candidate| candidate.oid == network.oid)
            });
            if !in_use {
                self.known_oids.remove(&network.oid);
            }
        }
        ok(tag, vec![], "200 OK")
    }

    fn database_extension(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let op = words[0].to_ascii_uppercase();
        match op.as_str() {
            "DBADD" => Some(self.dbadd_unsafe(tag, words)),
            "DBCOPY" => Some(self.dbcopy_unsafe(tag, words)),
            "DBCREATE" => Some(self.db_create(tag, words)),
            "DBNEW" => Some(self.db_new(tag, words)),
            "DBLOAD" => Some(self.db_load(tag, words)),
            "DBSAVE" => Some(self.db_save(tag, words)),
            "DBNETWORKPATH" => Some(self.db_network_path(tag, words)),
            "DBRENAMENET" => Some(self.dbrename_net(tag, words)),
            "DBSET" => Some(self.dbset_unsafe(tag, words)),
            "DBTAGLIST" => Some(self.db_tag_list(tag, words)),
            "DBUPDATE" => Some(self.db_update(tag, words)),
            "DBVERIFY" => Some(self.db_verify(tag, words)),
            _ => None,
        }
    }

    fn dbadd_unsafe(&mut self, tag: &str, words: &[&str]) -> Response {
        // Native consumes only parent and element type; trailing tokens are
        // ignored (they are not the SAFE command's address/name arguments).
        if words.len() < 3 {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        }
        let Some(project) = self.current.clone() else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        if !self.projects.contains_key(&project) {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        }
        let Some(parent) = self.canonical_database_add_parent(words[1], &project) else {
            return err(
                tag,
                status::ABSENT,
                &format!(
                    "401 Bad object or device ID: Element {} not found.",
                    words[1]
                ),
            );
        };
        let element = canonical_database_element(words[2]);
        if element.is_empty() || !self.database_parent_accepts(&project, &parent, &element) {
            return err(
                tag,
                status::ABSENT,
                &format!(
                    "401 Bad object or device ID: Unable to add element: Field '{}' not found in {}.",
                    words[2], words[1]
                ),
            );
        }
        let oid = self.issue_oid();
        let key = pending_key(&project, &oid);
        self.db_pending.insert(
            key,
            DbPendingObject {
                oid: oid.clone(),
                project,
                parent,
                element,
                fields: Default::default(),
                path: None,
            },
        );
        self.objects.insert(format!("!{oid}"));
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("301 OID={oid}"),
            status: 301,
        }
    }

    fn dbcopy_unsafe(&mut self, tag: &str, words: &[&str]) -> Response {
        // Like native, only the first two operands belong to DBCOPY; later
        // words are ignored rather than reinterpreted as SAFE arguments.
        if words.len() < 3 {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        }
        let Some(selected) = self.current.clone() else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let (source_project, source) = match self.database_copy_source(words[1], &selected) {
            Ok(value) => value,
            Err(reason) => {
                return err(
                    tag,
                    status::ABSENT,
                    &format!("401 Bad object or device ID: Bad source address: {reason}"),
                )
            }
        };
        let Some(destination) = self.canonical_database_copy_parent(words[2], &selected) else {
            return err(
                tag,
                status::ABSENT,
                &format!(
                    "401 Bad object or device ID: Bad destination address: Element {} not found.",
                    words[2]
                ),
            );
        };
        let Some(destination_project) = database_path_project(&destination) else {
            return err(
                tag,
                status::ABSENT,
                "401 Bad object or device ID: Bad destination address",
            );
        };
        if !self.projects.contains_key(destination_project)
            || !self.database_parent_accepts(destination_project, &destination, &source.element)
        {
            return err(
                tag,
                408,
                "408 Operation failed: Source and destination element types do not match",
            );
        }
        let clear_identity = source_project == destination_project;
        let before = self.clone();
        let oid = match self.insert_database_copy(
            destination_project,
            &destination,
            &source,
            clear_identity,
        ) {
            Ok(oid) => oid,
            Err(reason) => {
                *self = before;
                return err(tag, 408, &format!("408 Operation failed: {reason}"));
            }
        };
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("301 OID={oid}"),
            status: 301,
        }
    }

    fn db_new(&mut self, tag: &str, words: &[&str]) -> Response {
        // Native ignores trailing words.  Build 2001 can throw 500 after it
        // has already made this change for a generated PROJECT NEW database;
        // cmqttd performs the documented operation atomically instead.
        let _ = words;
        let Some(project) = self.current.clone() else {
            return err(tag, 408, "408 Operation failed: Project not found");
        };
        if !self.projects.contains_key(&project) {
            return err(tag, 408, "408 Operation failed: Project not found");
        }
        self.clear_project_database(&project);
        if let Some(record) = self.projects.get_mut(&project) {
            record.networks.clear();
        }
        ok(tag, vec![], "200 OK.")
    }

    fn db_create(&mut self, tag: &str, words: &[&str]) -> Response {
        // Native ignores trailing words.  The service refreshes physical
        // inventory before reaching this model operation.
        let _ = words;
        let Some(project_name) = self.current.clone() else {
            return err(tag, 443, "443 Error creating tag database");
        };
        let Some(previous) = self.projects.get(&project_name).cloned() else {
            return err(tag, 443, "443 Error creating tag database");
        };
        self.clear_project_database(&project_name);
        let mut networks = std::collections::HashMap::new();
        for (address, old) in previous.networks {
            let network_oid = self.issue_oid();
            let mut units = std::collections::HashMap::new();
            for (unit_address, physical) in &old.physical {
                let mut unit = physical.clone();
                unit.address = *unit_address;
                unit.oid = self.issue_oid();
                unit.serial_alternates.clear();
                let default_name = unit
                    .fields
                    .get("TagName")
                    .or_else(|| unit.fields.get("UnitName"))
                    .filter(|name| !name.is_empty())
                    .cloned()
                    .unwrap_or_else(|| "[default]".to_string());
                unit.fields
                    .insert("TagName".to_string(), default_name.clone());
                unit.fields
                    .entry("UnitName".to_string())
                    .or_insert(default_name);
                self.objects
                    .insert(format!("//{project_name}/{address}/p/{unit_address}"));
                units.insert(*unit_address, unit);
            }
            networks.insert(
                address,
                Network {
                    oid: network_oid,
                    address,
                    name: if old.name.is_empty() {
                        "[default]".to_string()
                    } else {
                        old.name
                    },
                    iface_type: old.iface_type,
                    iface_addr: old.iface_addr,
                    state: old.state,
                    retries: 2,
                    units,
                    physical: old.physical,
                    levels: old.levels,
                },
            );
        }
        self.projects.insert(
            project_name.clone(),
            super::Project {
                name: project_name,
                networks,
            },
        );
        ok(tag, vec![], "200 OK.")
    }

    fn canonical_database_address(&self, raw: &str, selected: &str) -> Option<String> {
        if let Some(oid) = raw.strip_prefix('!') {
            let oid = oid.split('/').next().unwrap_or("");
            return self.pending_for_project(selected, oid).or_else(|| {
                self.oid_in_project(selected, oid)
                    .then_some(format!("!{oid}"))
            });
        }
        let qualified = if raw.starts_with("//") {
            raw.trim_end_matches('/').to_string()
        } else {
            format!("//{selected}/{}", raw.trim_matches('/'))
        };
        self.database_address_exists(&qualified)
            .then_some(qualified)
    }

    fn canonical_database_add_parent(&self, raw: &str, selected: &str) -> Option<String> {
        let relative = raw.trim_start_matches('/');
        if relative.eq_ignore_ascii_case("Installation") {
            return Some(format!("//{selected}/Installation"));
        }
        if relative.eq_ignore_ascii_case("Installation/Project") {
            return Some(format!("//{selected}/Installation/Project"));
        }
        self.canonical_database_address(raw, selected)
    }

    fn canonical_database_copy_parent(&self, raw: &str, selected: &str) -> Option<String> {
        let relative = raw.trim_start_matches('/');
        if relative.eq_ignore_ascii_case("Installation") {
            return Some(format!("//{selected}/Installation"));
        }
        if relative.eq_ignore_ascii_case("Installation/Project") {
            return Some(format!("//{selected}/Installation/Project"));
        }
        if !raw.contains('/') && self.projects.contains_key(raw) {
            // Native's documented network-copy spelling names a project
            // directly (`DBCOPY //source/network destination-project`).  The
            // corresponding DBADD parent is Installation/Project.
            return Some(format!("//{raw}/Installation/Project"));
        }
        self.canonical_database_address(raw, selected)
    }

    pub(crate) fn database_address_exists(&self, path: &str) -> bool {
        if let Some(oid) = path.strip_prefix('!') {
            let Some(project) = self.current.as_deref() else {
                return false;
            };
            return self.oid_in_project(project, oid);
        }
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        let Some(project) = parts.first().copied() else {
            return false;
        };
        let Some(record) = self.projects.get(project) else {
            return false;
        };
        match parts.as_slice() {
            [_] | [_, "@root"] | [_, "Installation"] | [_, "Installation", "Project"] => true,
            [_, network] => network
                .parse::<u8>()
                .ok()
                .is_some_and(|network| record.networks.contains_key(&network)),
            [_, network, marker, unit] if marker.eq_ignore_ascii_case("p") => network
                .parse::<u8>()
                .ok()
                .zip(unit.parse::<u8>().ok())
                .is_some_and(|(network, unit)| {
                    record
                        .networks
                        .get(&network)
                        .is_some_and(|network| network.units.contains_key(&unit))
                }),
            [_, network, application] => network
                .parse::<u8>()
                .ok()
                .zip(application.parse::<u8>().ok())
                .is_some_and(|(network, application)| {
                    self.db_fields
                        .contains_key(&format!("//{project}/{network}/{application}/TagName"))
                        || self
                            .objects
                            .contains(&format!("//{project}/{network}-APPLICATION-{application}"))
                        || self
                            .db_pending
                            .values()
                            .any(|object| object.path.as_deref() == Some(path))
                }),
            [_, network, application, group] => network
                .parse::<u8>()
                .ok()
                .zip(application.parse::<u8>().ok())
                .zip(group.parse::<u8>().ok())
                .is_some_and(|((network, application), group)| {
                    self.db_fields.contains_key(&format!(
                        "//{project}/{network}/{application}/{group}/TagName"
                    )) || self.objects.contains(&format!(
                        "//{project}/{network}/{application}-GROUP-{group}"
                    )) || self
                        .db_pending
                        .values()
                        .any(|object| object.path.as_deref() == Some(path))
                }),
            [_, network, application, group, level] => {
                let parent = format!("//{project}/{network}/{application}/{group}");
                level.parse::<u8>().ok().is_some_and(|address| {
                    self.db_levels
                        .values()
                        .any(|candidate| candidate.parent == parent && candidate.address == address)
                })
            }
            _ => false,
        }
    }

    fn database_parent_accepts(&self, project: &str, parent: &str, element: &str) -> bool {
        if let Some(oid) = parent.strip_prefix('!') {
            let Some(parent) = self.pending_object(project, oid) else {
                return false;
            };
            return database_child_allowed(&parent.element, element);
        }
        if !self.database_address_exists(parent) {
            return false;
        }
        let parts = parent
            .trim_start_matches('/')
            .split('/')
            .collect::<Vec<_>>();
        if parts.first().copied() != Some(project) {
            return false;
        }
        let parent_element = match parts.as_slice() {
            [_] => return false,
            [_, "@root"] | [_, "Installation"] => "Installation",
            [_, "Installation", "Project"] => "Project",
            [_, _] => "Network",
            [_, _, marker, _] if marker.eq_ignore_ascii_case("p") => "Unit",
            [_, _, _] => "Application",
            [_, _, _, _] => "Group",
            [_, _, _, _, _] => "Level",
            _ => return false,
        };
        database_child_allowed(parent_element, element)
    }

    fn pending_for_project(&self, project: &str, oid: &str) -> Option<String> {
        self.db_pending
            .contains_key(&pending_key(project, oid))
            .then_some(format!("!{oid}"))
    }

    pub(crate) fn pending_object(&self, project: &str, oid: &str) -> Option<&DbPendingObject> {
        self.db_pending.get(&pending_key(project, oid))
    }

    fn oid_in_project(&self, project: &str, oid: &str) -> bool {
        self.pending_object(project, oid).is_some()
            || self.projects.get(project).is_some_and(|record| {
                record.networks.values().any(|network| {
                    network.oid == oid || network.units.values().any(|unit| unit.oid == oid)
                })
            })
            || self.db_levels.values().any(|level| {
                level.oid == oid && database_path_project(&level.parent) == Some(project)
            })
    }

    /// Apply a field to an incomplete object.  `Ok(true)` means the OID was
    /// handled; `Ok(false)` lets the ordinary OID resolver continue.
    pub(crate) fn set_pending_database_field(
        &mut self,
        project: &str,
        oid: &str,
        field: &str,
        value: String,
    ) -> Result<bool, String> {
        let key = pending_key(project, oid);
        let Some(existing) = self.db_pending.get(&key).cloned() else {
            return Ok(false);
        };
        let before = self.clone();
        if existing.path.is_some() {
            // Once addressable, the ordinary typed maps own moves and field
            // writes.  Keep the metadata mirror current for OID reads.
            if let Some(object) = self.db_pending.get_mut(&key) {
                object.fields.insert(field.to_string(), value);
            }
            return Ok(false);
        }
        self.db_pending
            .get_mut(&key)
            .expect("pending object exists")
            .fields
            .insert(field.to_string(), value);
        if matches!(
            existing.element.as_str(),
            "InstallationDetail" | "Interface"
        ) {
            if existing.element == "Interface" {
                if let Some((parent_project, network)) = database_network_parent(&existing.parent) {
                    if parent_project == project {
                        if let Some(network) = self
                            .projects
                            .get_mut(project)
                            .and_then(|record| record.networks.get_mut(&network))
                        {
                            let value = self
                                .db_pending
                                .get(&key)
                                .and_then(|object| object.fields.get(field))
                                .cloned()
                                .unwrap_or_default();
                            match field {
                                "InterfaceType" => network.iface_type = value,
                                "InterfaceAddress" => network.iface_addr = value,
                                _ => {}
                            }
                        }
                    }
                }
            }
            return Ok(true);
        }
        if let Err(error) = self.materialize_pending(project, oid) {
            // A complete parent can recursively materialize complete
            // descendants. Roll the entire subtree back if any descendant
            // conflicts instead of leaving an addressable partial parent.
            *self = before;
            return Err(error);
        }
        Ok(true)
    }

    pub(crate) fn sync_pending_database_field(
        &mut self,
        project: &str,
        oid: &str,
        field: &str,
        value: &str,
    ) {
        if let Some(object) = self.db_pending.get_mut(&pending_key(project, oid)) {
            object.fields.insert(field.to_string(), value.to_string());
        }
    }

    fn materialize_pending(&mut self, project: &str, oid: &str) -> Result<bool, String> {
        let key = pending_key(project, oid);
        let Some(object) = self.db_pending.get(&key).cloned() else {
            return Ok(false);
        };
        if object.path.is_some() {
            return Ok(true);
        }
        let parent = if let Some(parent_oid) = object.parent.strip_prefix('!') {
            let Some(path) = self
                .pending_object(project, parent_oid)
                .and_then(|parent| parent.path.clone())
            else {
                return Ok(false);
            };
            path
        } else {
            object.parent.clone()
        };
        let address = object
            .fields
            .get("Address")
            .or_else(|| object.fields.get("NetworkNumber"))
            .map(String::as_str);
        let tag_name = object.fields.get("TagName").map(String::as_str);
        let element = object.element.as_str();
        if matches!(element, "InstallationDetail" | "Interface") {
            // These native typed containers have OIDs but no Address or
            // TagName identity. They remain OID-addressable and carry their
            // scalar fields in the pending-object store.
            return Ok(true);
        }
        let requires_address = matches!(
            element,
            "Network" | "Unit" | "Application" | "Group" | "Level" | "NetVar"
        );
        let requires_tag = matches!(
            element,
            "Project" | "Network" | "Unit" | "Application" | "Group" | "Level" | "NetVar"
        );
        if requires_address && address.is_none() || requires_tag && tag_name.is_none() {
            return Ok(false);
        }
        let address = if requires_address {
            Some(
                address
                    .expect("checked")
                    .parse::<u8>()
                    .map_err(|_| format!("{element} Address must be a byte"))?,
            )
        } else {
            None
        };
        let tag_name = tag_name.unwrap_or("").to_string();
        let path = match element {
            "Project" => {
                // A Project element belongs to the selected tag database; it
                // does not load a new C-Gate repository project. Native keeps
                // its address NULL and DBTAGLIST renders `null/TagName=...`.
                let path = format!("//{project}/null");
                self.db_fields.insert(format!("{path}/TagName"), tag_name);
                self.objects.insert(path.clone());
                path
            }
            "Network" => {
                let address = address.expect("required");
                let record = self
                    .projects
                    .get_mut(project)
                    .ok_or_else(|| "Project not found".to_string())?;
                if record.networks.contains_key(&address) {
                    return Err("Network Address is already in use".to_string());
                }
                record.networks.insert(
                    address,
                    Network {
                        oid: oid.to_string(),
                        address,
                        name: tag_name,
                        iface_type: object
                            .fields
                            .get("InterfaceType")
                            .cloned()
                            .unwrap_or_default(),
                        iface_addr: object
                            .fields
                            .get("InterfaceAddress")
                            .cloned()
                            .unwrap_or_default(),
                        state: NetworkState::Closed,
                        retries: 2,
                        units: Default::default(),
                        physical: Default::default(),
                        levels: Default::default(),
                    },
                );
                format!("//{project}/{address}")
            }
            "Unit" => {
                let address = address.expect("required");
                let Some((parent_project, network)) = database_network_parent(&parent) else {
                    return Err("Unit parent is not a network".to_string());
                };
                if parent_project != project {
                    return Err("Unit parent belongs to another project".to_string());
                }
                let network = self
                    .projects
                    .get_mut(project)
                    .and_then(|project| project.networks.get_mut(&network))
                    .ok_or_else(|| "Unit parent network not found".to_string())?;
                if network.units.contains_key(&address) {
                    return Err("Unit Address is already in use".to_string());
                }
                let mut unit = Unit::blank(address, &tag_name);
                unit.oid = oid.to_string();
                unit.fields.extend(object.fields.clone());
                unit.fields.insert("TagName".to_string(), tag_name.clone());
                unit.fields
                    .entry("UnitName".to_string())
                    .or_insert(tag_name);
                unit.unit_type = unit
                    .fields
                    .get("UnitType")
                    .or_else(|| unit.fields.get("Type"))
                    .cloned()
                    .unwrap_or_default();
                unit.firmware = unit
                    .fields
                    .get("FirmwareVersion")
                    .or_else(|| unit.fields.get("Version"))
                    .cloned()
                    .unwrap_or_default();
                unit.serial = unit.fields.get("SerialNumber").cloned().unwrap_or_default();
                network.units.insert(address, unit);
                format!("{parent}/p/{address}")
            }
            "Application" | "Group" => {
                let address = address.expect("required");
                let path = format!("{parent}/{address}");
                if self.database_address_exists(&path) {
                    return Err(format!("{element} Address is already in use"));
                }
                self.db_fields.insert(format!("{path}/TagName"), tag_name);
                self.objects.insert(path.clone());
                if element == "Application" {
                    self.objects
                        .insert(format!("{parent}-APPLICATION-{address}"));
                } else {
                    self.objects.insert(format!("{parent}-GROUP-{address}"));
                }
                path
            }
            "Level" | "NetVar" => {
                let address = address.expect("required");
                if self
                    .db_levels
                    .values()
                    .any(|level| level.parent == parent && level.address == address)
                {
                    return Err(format!("{element} Address is already in use"));
                }
                let value = object
                    .fields
                    .get("Value")
                    .filter(|value| !value.is_empty())
                    .map(|value| {
                        value
                            .parse::<u8>()
                            .map_err(|_| format!("{element} Value must be a byte"))
                    })
                    .transpose()?;
                self.db_levels.insert(
                    key.clone(),
                    DbLevel {
                        oid: oid.to_string(),
                        parent: parent.clone(),
                        address,
                        tag: tag_name,
                        value,
                        netvar: element == "NetVar",
                    },
                );
                format!("{parent}/{address}")
            }
            _ => return Err(format!("unsupported database element {element}")),
        };
        self.db_pending
            .get_mut(&key)
            .expect("pending object exists")
            .path = Some(path);

        // A cross-project subtree may already have complete descendants.
        // Materialize them only after the parent has an address.
        let children = self
            .db_pending
            .values()
            .filter(|candidate| {
                candidate.project == project && candidate.parent == format!("!{oid}")
            })
            .map(|candidate| candidate.oid.clone())
            .collect::<Vec<_>>();
        for child in children {
            self.materialize_pending(project, &child)?;
        }
        Ok(true)
    }

    fn database_copy_source(
        &self,
        raw: &str,
        selected: &str,
    ) -> Result<(String, DatabaseCopyNode), String> {
        if let Some(oid) = raw.strip_prefix('!') {
            let oid = oid.split('/').next().unwrap_or("");
            if let Some(object) = self.pending_object(selected, oid) {
                return Ok((
                    selected.to_string(),
                    self.copy_pending_node(selected, object),
                ));
            }
            if let Some(level) = self.db_levels.values().find(|level| {
                level.oid == oid && database_path_project(&level.parent) == Some(selected)
            }) {
                return Ok((selected.to_string(), database_level_node(level)));
            }
            if let Some(project) = self.projects.get(selected) {
                for network in project.networks.values() {
                    if network.oid == oid {
                        return Ok((
                            selected.to_string(),
                            self.copy_network_node(selected, network.address),
                        ));
                    }
                    if let Some(unit) = network.units.values().find(|unit| unit.oid == oid) {
                        return Ok((selected.to_string(), database_unit_node(unit)));
                    }
                }
            }
            return Err(format!("Element {raw} not found."));
        }
        let path = if raw.starts_with("//") {
            raw.trim_end_matches('/').to_string()
        } else if raw.eq_ignore_ascii_case(selected) {
            format!("//{selected}")
        } else {
            format!("//{selected}/{}", raw.trim_matches('/'))
        };
        let parts = path.trim_start_matches('/').split('/').collect::<Vec<_>>();
        let Some(project_name) = parts.first().copied() else {
            return Err(format!("Element {raw} not found."));
        };
        let Some(project) = self.projects.get(project_name) else {
            return Err(format!("Element {raw} not found."));
        };
        let node = match parts.as_slice() {
            [_] => {
                let mut fields = std::collections::HashMap::new();
                fields.insert("TagName".to_string(), project.name.clone());
                let mut children = project
                    .networks
                    .keys()
                    .copied()
                    .map(|network| self.copy_network_node(project_name, network))
                    .collect::<Vec<_>>();
                children.extend(
                    self.db_pending
                        .values()
                        .filter(|object| {
                            object.project == project_name
                                && object.element == "InstallationDetail"
                                && matches!(
                                    object.parent.as_str(),
                                    parent if parent == format!("//{project_name}/Installation")
                                        || parent == format!("//{project_name}/@root")
                                )
                        })
                        .map(|object| self.copy_pending_node(project_name, object)),
                );
                DatabaseCopyNode {
                    element: "Project".to_string(),
                    fields,
                    children,
                }
            }
            [_, network] => {
                let network = network
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                if !project.networks.contains_key(&network) {
                    return Err(format!("Element {network} not found."));
                }
                self.copy_network_node(project_name, network)
            }
            [_, network, marker, unit] if marker.eq_ignore_ascii_case("p") => {
                let network = network
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let unit = unit
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let unit = project
                    .networks
                    .get(&network)
                    .and_then(|network| network.units.get(&unit))
                    .ok_or_else(|| format!("Element {unit} not found."))?;
                database_unit_node(unit)
            }
            [_, network, application] => {
                let network = network
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let application = application
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                self.copy_application_node(project_name, network, application)
                    .ok_or_else(|| format!("Element {application} not found."))?
            }
            [_, network, application, group] => {
                let network = network
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let application = application
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let group = group
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                self.copy_netvar_node(project_name, network, application, group)
                    .or_else(|| self.copy_group_node(project_name, network, application, group))
                    .ok_or_else(|| format!("Element {group} not found."))?
            }
            [_, network, application, group, level] => {
                let parent = format!("//{project_name}/{network}/{application}/{group}");
                let level = level
                    .parse::<u8>()
                    .map_err(|_| format!("Element {raw} not found."))?;
                let record = self
                    .db_levels
                    .values()
                    .find(|record| record.parent == parent && record.address == level)
                    .ok_or_else(|| format!("Element {level} not found."))?;
                database_level_node(record)
            }
            _ => return Err(format!("Element {raw} not found.")),
        };
        Ok((project_name.to_string(), node))
    }

    fn copy_pending_node(&self, project: &str, object: &DbPendingObject) -> DatabaseCopyNode {
        DatabaseCopyNode {
            element: object.element.clone(),
            fields: object.fields.clone(),
            children: self
                .db_pending
                .values()
                .filter(|child| {
                    child.project == project && child.parent == format!("!{}", object.oid)
                })
                .map(|child| self.copy_pending_node(project, child))
                .collect(),
        }
    }

    fn copy_network_node(&self, project: &str, address: u8) -> DatabaseCopyNode {
        let network = &self.projects[project].networks[&address];
        let mut fields = std::collections::HashMap::new();
        fields.insert("Address".to_string(), address.to_string());
        fields.insert("NetworkNumber".to_string(), address.to_string());
        fields.insert("TagName".to_string(), network.name.clone());
        fields.insert("InterfaceType".to_string(), network.iface_type.clone());
        fields.insert("InterfaceAddress".to_string(), network.iface_addr.clone());
        let mut children = network
            .units
            .values()
            .map(database_unit_node)
            .collect::<Vec<_>>();
        let network_path = format!("//{project}/{address}");
        children.extend(
            self.db_pending
                .values()
                .filter(|object| {
                    object.project == project
                        && object.element == "Interface"
                        && object.parent == network_path
                })
                .map(|object| self.copy_pending_node(project, object)),
        );
        let prefix = format!("//{project}/{address}/");
        let mut applications = std::collections::BTreeSet::new();
        for path in self.db_fields.keys() {
            let Some(rest) = path.strip_prefix(&prefix) else {
                continue;
            };
            let Some(application) = rest
                .split('/')
                .next()
                .and_then(|part| part.parse::<u8>().ok())
            else {
                continue;
            };
            applications.insert(application);
        }
        for application in applications {
            if let Some(node) = self.copy_application_node(project, address, application) {
                children.push(node);
            }
        }
        DatabaseCopyNode {
            element: "Network".to_string(),
            fields,
            children,
        }
    }

    fn copy_application_node(
        &self,
        project: &str,
        network: u8,
        application: u8,
    ) -> Option<DatabaseCopyNode> {
        let path = format!("//{project}/{network}/{application}");
        let tag = self.db_fields.get(&format!("{path}/TagName"))?.clone();
        let mut fields = std::collections::HashMap::new();
        fields.insert("Address".to_string(), application.to_string());
        fields.insert("TagName".to_string(), tag);
        let prefix = format!("{path}/");
        let netvars = self
            .db_levels
            .values()
            .filter(|level| level.parent == path && level.netvar)
            .map(|level| level.address)
            .collect::<std::collections::BTreeSet<_>>();
        let mut groups = std::collections::BTreeSet::new();
        for candidate in self.db_fields.keys() {
            let Some(rest) = candidate.strip_prefix(&prefix) else {
                continue;
            };
            if let Some(group) = rest
                .split('/')
                .next()
                .and_then(|part| part.parse::<u8>().ok())
            {
                groups.insert(group);
            }
        }
        for level in self
            .db_levels
            .values()
            .filter(|level| level.parent.starts_with(&prefix))
        {
            if let Some(group) = level
                .parent
                .strip_prefix(&prefix)
                .and_then(|rest| rest.split('/').next())
                .and_then(|part| part.parse::<u8>().ok())
            {
                if !netvars.contains(&group) {
                    groups.insert(group);
                }
            }
        }
        let mut children = groups
            .into_iter()
            .filter_map(|group| self.copy_group_node(project, network, application, group))
            .collect::<Vec<_>>();
        children.extend(
            netvars
                .into_iter()
                .filter_map(|netvar| self.copy_netvar_node(project, network, application, netvar)),
        );
        Some(DatabaseCopyNode {
            element: "Application".to_string(),
            fields,
            children,
        })
    }

    fn copy_group_node(
        &self,
        project: &str,
        network: u8,
        application: u8,
        group: u8,
    ) -> Option<DatabaseCopyNode> {
        let path = format!("//{project}/{network}/{application}/{group}");
        let tag = self.db_fields.get(&format!("{path}/TagName"))?.clone();
        let mut fields = std::collections::HashMap::new();
        fields.insert("Address".to_string(), group.to_string());
        fields.insert("TagName".to_string(), tag);
        let mut levels = self
            .db_levels
            .values()
            .filter(|level| level.parent == path)
            .map(database_level_node)
            .collect::<Vec<_>>();
        levels.sort_by_key(|level| {
            level
                .fields
                .get("Address")
                .and_then(|value| value.parse::<u8>().ok())
                .unwrap_or(0)
        });
        Some(DatabaseCopyNode {
            element: "Group".to_string(),
            fields,
            children: levels,
        })
    }

    fn copy_netvar_node(
        &self,
        project: &str,
        network: u8,
        application: u8,
        address: u8,
    ) -> Option<DatabaseCopyNode> {
        let application_path = format!("//{project}/{network}/{application}");
        let record = self.db_levels.values().find(|level| {
            level.parent == application_path && level.address == address && level.netvar
        })?;
        let mut node = database_level_node(record);
        let child_parent = format!("{application_path}/{address}");
        node.children = self
            .db_levels
            .values()
            .filter(|level| level.parent == child_parent)
            .map(database_level_node)
            .collect();
        node.children.sort_by_key(|level| {
            level
                .fields
                .get("Address")
                .and_then(|value| value.parse::<u8>().ok())
                .unwrap_or(0)
        });
        Some(node)
    }

    fn insert_database_copy(
        &mut self,
        project: &str,
        parent: &str,
        node: &DatabaseCopyNode,
        clear_identity: bool,
    ) -> Result<String, String> {
        let oid = self.issue_oid();
        let mut fields = node.fields.clone();
        if clear_identity {
            fields.remove("Address");
            fields.remove("NetworkNumber");
            fields.remove("TagName");
        }
        self.db_pending.insert(
            pending_key(project, &oid),
            DbPendingObject {
                oid: oid.clone(),
                project: project.to_string(),
                parent: parent.to_string(),
                element: node.element.clone(),
                fields,
                path: None,
            },
        );
        self.objects.insert(format!("!{oid}"));
        self.materialize_pending(project, &oid)?;
        for child in &node.children {
            self.insert_database_copy(project, &format!("!{oid}"), child, clear_identity)?;
        }
        // The parent may have materialized only after a cross-project copy;
        // give complete children a second chance now that every sibling has
        // been registered.
        self.materialize_pending(project, &oid)?;
        Ok(oid)
    }

    fn clear_project_database(&mut self, project: &str) {
        let prefix = format!("//{project}/");
        self.db_fields.retain(|path, _| !path.starts_with(&prefix));
        self.objects.retain(|path| {
            if path.starts_with('!') {
                true
            } else {
                !path.starts_with(&prefix)
            }
        });
        let removed_pending = self
            .db_pending
            .iter()
            .filter(|(_, object)| object.project == project)
            .map(|(key, object)| (key.clone(), object.oid.clone()))
            .collect::<Vec<_>>();
        let mut removed_oids = removed_pending
            .iter()
            .map(|(_, oid)| oid.clone())
            .collect::<std::collections::HashSet<_>>();
        removed_oids.extend(
            self.db_levels
                .values()
                .filter(|level| database_path_project(&level.parent) == Some(project))
                .map(|level| level.oid.clone()),
        );
        removed_oids.extend(
            self.projects
                .get(project)
                .into_iter()
                .flat_map(|record| record.networks.values())
                .flat_map(|network| {
                    std::iter::once(network.oid.clone())
                        .chain(network.units.values().map(|unit| unit.oid.clone()))
                }),
        );
        for (key, _) in &removed_pending {
            self.db_pending.remove(key);
        }
        self.db_levels
            .retain(|_, level| database_path_project(&level.parent) != Some(project));
        if let Some(record) = self.projects.get_mut(project) {
            record.networks.clear();
        }
        for oid in removed_oids {
            if !self.oid_used_anywhere(&oid) {
                self.known_oids.remove(&oid);
                self.objects.remove(&format!("!{oid}"));
                let oid_prefix = format!("!{oid}/");
                self.db_fields
                    .retain(|path, _| !path.starts_with(&oid_prefix));
            }
        }
    }

    pub(crate) fn oid_used_anywhere(&self, oid: &str) -> bool {
        self.db_pending.values().any(|object| object.oid == oid)
            || self.db_levels.values().any(|level| level.oid == oid)
            || self.projects.values().any(|project| {
                project.networks.values().any(|network| {
                    network.oid == oid || network.units.values().any(|unit| unit.oid == oid)
                })
            })
            || self.database_files.values().any(|project| {
                project.networks.values().any(|network| {
                    network.oid == oid || network.units.values().any(|unit| unit.oid == oid)
                })
            })
    }

    fn db_save(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || words[1].is_empty() {
            return err(tag, status::BAD_REQUEST, "400 DBSAVE requires a filename");
        }
        let Some(mut project) = self
            .current
            .as_ref()
            .and_then(|name| self.projects.get(name))
            .cloned()
        else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        Self::reset_project_retries(&mut project);
        self.database_files.insert(words[1].to_string(), project);
        ok(tag, vec![], "200 OK.")
    }

    fn db_load(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || words[1].is_empty() {
            return err(tag, status::BAD_REQUEST, "400 DBLOAD requires a filename");
        }
        let Some(mut snapshot) = self.database_files.get(words[1]).cloned() else {
            return err(tag, 442, "442 Error reading tag database");
        };
        Self::reset_project_retries(&mut snapshot);
        let Some(current) = self.current.clone() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        snapshot.name = current.clone();
        self.projects.insert(current, snapshot);
        ok(tag, vec![], "200 OK.")
    }

    fn db_network_path(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() == 1 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Syntax Error: No starting network given",
            );
        }
        if words.len() == 2 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Syntax Error: No ending address given",
            );
        }
        let start = words[1]
            .trim_matches('/')
            .rsplit('/')
            .next()
            .and_then(|n| n.parse::<u8>().ok());
        let end = words[2]
            .trim_matches('/')
            .rsplit('/')
            .next()
            .and_then(|n| n.parse::<u8>().ok());
        let (Some(start), Some(end)) = (start, end) else {
            return err(tag, status::BAD_REQUEST, "400 Invalid network address");
        };
        let Some(project) = self
            .current
            .as_ref()
            .and_then(|name| self.projects.get(name))
        else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        if !project.networks.contains_key(&start) || !project.networks.contains_key(&end) {
            return err(tag, status::NOT_FOUND, "401 Network not found");
        }
        // Native 3.4 treats a zero-hop lookup as no path in every output mode.
        // It resolves the path before interpreting the optional mode token, so
        // even an unknown token retains this exact 408 for START == END.
        if start == end {
            return err(
                tag,
                408,
                "408 Operation failed: Network path discovery failed: No path found",
            );
        }
        // Native 3.4 selects COMPACT only for that literal option. Any other
        // fourth token uses the default OID form, and later tokens are ignored.
        let compact = words
            .get(3)
            .is_some_and(|mode| mode.eq_ignore_ascii_case("COMPACT"));
        let path = match network_path(project, start, end) {
            Ok(path) => path,
            Err(_) => {
                return err(
                    tag,
                    408,
                    "408 Operation failed: Network path discovery failed: No path found",
                )
            }
        };
        if compact {
            envelope(
                tag,
                136,
                [path
                    .iter()
                    .map(|address| format!("{address:02X}"))
                    .collect::<String>()],
            )
        } else {
            envelope(
                tag,
                137,
                path.into_iter().map(|address| {
                    let oid = &project.networks[&address].oid;
                    if oid.is_empty() {
                        format!("network-{address}")
                    } else {
                        oid.clone()
                    }
                }),
            )
        }
    }

    fn db_tag_list(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() > 2 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Syntax Error: Too many parameters",
            );
        }
        let Some(project_name) = self.current.as_deref() else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let Some(project) = self.projects.get(project_name) else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let pattern = words.get(1).map(|p| p.to_ascii_lowercase());
        let mut rows = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut push = |row: String| {
            if seen.insert(row.clone()) {
                rows.push(row);
            }
        };
        push(format!("{project_name}/TagName={project_name}"));
        let mut networks = project.networks.iter().collect::<Vec<_>>();
        networks.sort_by_key(|(address, _)| std::cmp::Reverse(**address));
        for (net, network) in networks {
            if !network.name.is_empty() {
                push(format!("{net}/TagName={}", network.name));
            }
            let mut units = network.units.iter().collect::<Vec<_>>();
            units.sort_by_key(|(address, _)| **address);
            for (address, unit) in units {
                let name = unit
                    .fields
                    .get("TagName")
                    .or_else(|| unit.fields.get("UnitName"))
                    .cloned()
                    .unwrap_or_default();
                if !name.is_empty() {
                    push(format!("{net}/p/{address}/TagName={name}"));
                }
            }

            let network_prefix = format!("//{project_name}/{net}/");
            let mut descendants = std::collections::BTreeSet::new();
            for (path, value) in &self.db_fields {
                if value.is_empty() || !path.ends_with("/TagName") {
                    continue;
                }
                if let Some(relative) = path.strip_prefix(&network_prefix) {
                    descendants.insert(format!("{net}/{relative}={value}"));
                }
            }
            for level in self.db_levels.values() {
                let Some(parent) = level.parent.strip_prefix(&network_prefix) else {
                    continue;
                };
                if !level.tag.is_empty() {
                    descendants.insert(format!(
                        "{net}/{parent}/{}/TagName={}",
                        level.address, level.tag
                    ));
                }
            }
            for row in descendants {
                push(row);
            }
        }
        let rows = rows
            .into_iter()
            .filter(|row| {
                pattern
                    .as_ref()
                    .is_none_or(|p| row.to_ascii_lowercase().contains(p))
            })
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return err(
                tag,
                status::ABSENT,
                "401 Bad object or device ID: No objects found.",
            );
        }
        envelope(tag, 342, rows)
    }

    fn db_update(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 2 {
            return err(tag, status::BAD_REQUEST, "400 Syntax Error.");
        }
        let delete_missing = words
            .get(2)
            .is_some_and(|value| value.eq_ignore_ascii_case("UnitDelete"));
        let Some(project_name) = self.current.clone() else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        if !self.projects.contains_key(&project_name) {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        }
        let target = normalize_update_target(words[1], &project_name);
        let parsed = self
            .projects
            .get(&project_name)
            .and_then(|record| parse_update_target(&target, &project_name, record));
        let Some((network_address, unit_address)) = parsed else {
            return err(
                tag,
                status::ABSENT,
                &format!(
                    "401 Bad object or device ID: {} (Network not found)",
                    words[1]
                ),
            );
        };
        let mut removed_oids = std::collections::HashSet::new();
        let Some(network) = self
            .projects
            .get_mut(&project_name)
            .and_then(|project| project.networks.get_mut(&network_address))
        else {
            return err(
                tag,
                status::ABSENT,
                &format!(
                    "401 Bad object or device ID: {} (Network not found)",
                    words[1]
                ),
            );
        };
        if network.state != NetworkState::Ok && network.physical.is_empty() {
            return err(
                tag,
                408,
                "408 Operation failed: Physical inventory has not been synchronized",
            );
        }

        if let Some(address) = unit_address {
            let physical = network.physical.get(&address).cloned();
            let path = format!("//{project_name}/{network_address}/p/{address}");
            match physical {
                Some(physical) => {
                    update_database_unit_from_physical(
                        &mut self.known_oids,
                        &mut network.units,
                        address,
                        physical,
                    );
                    self.objects.insert(path.clone());
                    if let Some(unit) = network.units.get(&address) {
                        mirror_materialized_unit(&mut self.db_pending, &project_name, &path, unit);
                    }
                }
                None if delete_missing => {
                    if let Some(unit) = network.units.remove(&address) {
                        removed_oids.insert(unit.oid);
                    }
                    for oid in
                        remove_materialized_pending_path(&mut self.db_pending, &project_name, &path)
                    {
                        removed_oids.insert(oid);
                    }
                    self.db_fields.retain(|candidate, _| {
                        candidate != &path && !candidate.starts_with(&format!("{path}/"))
                    });
                    self.objects.retain(|candidate| {
                        candidate != &path && !candidate.starts_with(&format!("{path}/"))
                    });
                }
                None => {
                    return err(
                        tag,
                        status::ABSENT,
                        &format!(
                            "401 Bad object or device ID: {} (Unit not found on physical network)",
                            words[1]
                        ),
                    )
                }
            }
        } else {
            let physical = network.physical.clone();
            for (address, unit) in physical {
                update_database_unit_from_physical(
                    &mut self.known_oids,
                    &mut network.units,
                    address,
                    unit,
                );
                let path = format!("//{project_name}/{network_address}/p/{address}");
                self.objects.insert(path.clone());
                if let Some(unit) = network.units.get(&address) {
                    mirror_materialized_unit(&mut self.db_pending, &project_name, &path, unit);
                }
            }
            if delete_missing {
                let absent = network
                    .units
                    .keys()
                    .filter(|address| !network.physical.contains_key(address))
                    .copied()
                    .collect::<Vec<_>>();
                for address in absent {
                    if let Some(unit) = network.units.remove(&address) {
                        removed_oids.insert(unit.oid);
                    }
                    let prefix = format!("//{project_name}/{network_address}/p/{address}");
                    for oid in remove_materialized_pending_path(
                        &mut self.db_pending,
                        &project_name,
                        &prefix,
                    ) {
                        removed_oids.insert(oid);
                    }
                    self.db_fields.retain(|path, _| {
                        path != &prefix && !path.starts_with(&format!("{prefix}/"))
                    });
                    self.objects
                        .retain(|path| path != &prefix && !path.starts_with(&format!("{prefix}/")));
                }
            }
        }
        for oid in removed_oids {
            if !self.oid_used_anywhere(&oid) {
                self.known_oids.remove(&oid);
                self.objects.remove(&format!("!{oid}"));
                let oid_prefix = format!("!{oid}/");
                self.db_fields
                    .retain(|path, _| !path.starts_with(&oid_prefix));
            }
        }
        self.push_event(format!("#e# db update {target}"));
        ok(tag, vec![], "200 OK.")
    }

    fn db_verify(&self, tag: &str, _words: &[&str]) -> Response {
        let Some(project_name) = self.current.as_deref() else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let Some(project) = self.projects.get(project_name) else {
            return err(
                tag,
                440,
                "440 There is no tag database to perform this operation on",
            );
        };
        let mut differences = Vec::new();
        let mut networks = project.networks.iter().collect::<Vec<_>>();
        networks.sort_by_key(|(address, _)| **address);
        for (network_address, network) in networks {
            if network.state != NetworkState::Ok && network.physical.is_empty() {
                differences.push(format!(
                    "network {network_address} has no synchronized physical inventory"
                ));
                continue;
            }
            let mut addresses = network
                .units
                .keys()
                .chain(network.physical.keys())
                .copied()
                .collect::<std::collections::BTreeSet<_>>();
            for address in std::mem::take(&mut addresses) {
                match (network.units.get(&address), network.physical.get(&address)) {
                    (None, Some(_)) => differences.push(format!(
                        "//{project_name}/{network_address}/p/{address} is present on the physical network but absent from the database"
                    )),
                    (Some(_), None) => differences.push(format!(
                        "//{project_name}/{network_address}/p/{address} is present in the database but absent from the physical network"
                    )),
                    (Some(database), Some(physical)) => {
                        for (field, database_value, physical_value) in [
                            ("UnitType", database.unit_type.as_str(), physical.unit_type.as_str()),
                            ("FirmwareVersion", database.firmware.as_str(), physical.firmware.as_str()),
                            ("SerialNumber", database.serial.as_str(), physical.serial.as_str()),
                        ] {
                            if !database_value.is_empty()
                                && !physical_value.is_empty()
                                && database_value != physical_value
                            {
                                differences.push(format!(
                                    "//{project_name}/{network_address}/p/{address}/{field} database={database_value} physical={physical_value}"
                                ));
                            }
                        }
                    }
                    (None, None) => unreachable!(),
                }
            }
        }
        if differences.is_empty() {
            return ok(tag, vec![], "200 OK.");
        }
        let count = differences.len();
        Response {
            tag: tag.to_string(),
            lines: differences
                .into_iter()
                .map(|difference| format!("345-Difference: {difference}"))
                .collect(),
            final_text: format!("408 Operation failed: Verify failed: {count} differences"),
            status: 408,
        }
    }

    fn run_macro(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(2..=3).contains(&words.len())
            || words
                .get(2)
                .is_some_and(|word| !word.eq_ignore_ascii_case("QUIET"))
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 RUN requires a filename and optional QUIET",
            );
        }
        let source = match std::fs::read_to_string(words[1]) {
            Ok(source) => source,
            Err(error) => return err(tag, 410, &format!("410 Macro command error: {error}")),
        };
        let quiet = words.len() == 3;
        let mut output = Vec::new();
        for (index, line) in source.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') || line.starts_with("//") {
                continue;
            }
            if line
                .split_whitespace()
                .next()
                .is_some_and(|word| word.eq_ignore_ascii_case("RUN"))
            {
                return err(tag, 412, "412 Macro loop detected");
            }
            let response = self.handle(&format!("[macro-{index}] {line}"));
            if response.status >= 400 {
                return err(
                    tag,
                    410,
                    &format!(
                        "410 Macro command error on line {}: {}",
                        index + 1,
                        response.final_text
                    ),
                );
            }
            if !quiet {
                output.push(format!("line {}: {}", index + 1, response.final_text));
            }
        }
        Response {
            tag: tag.to_string(),
            lines: output,
            final_text: "203 Run complete.".to_string(),
            status: 203,
        }
    }

    fn scene_command(&mut self, tag: &str, words: &[&str]) -> Response {
        // Toolkit's older address-only named-scene spelling is recognized
        // but cannot resolve a scene module name, matching native 401.
        if words.len() == 3 {
            return err(tag, status::ABSENT, "401 Scene not found");
        }
        if words.len() != 4 || !matches!(words[1].to_ascii_uppercase().as_str(), "PLAY" | "RECORD")
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 SCENE requires PLAY or RECORD, set and scene",
            );
        }
        let key = format!("{}/{}", words[2], words[3]);
        if words[1].eq_ignore_ascii_case("RECORD") {
            let Some(project_name) = self.current.clone() else {
                return err(tag, status::NOT_FOUND, "401 Project not selected");
            };
            let mut snapshot = Vec::new();
            if let Some(project) = self.projects.get(&project_name) {
                for (net, network) in &project.networks {
                    for ((app, group), level) in &network.levels {
                        snapshot.push((format!("//{project_name}/{net}/{app}/{group}"), *level));
                    }
                }
            }
            snapshot.sort();
            self.scene_snapshots.insert(key, snapshot);
            return ok(tag, vec![], "200 OK.");
        }
        let Some(snapshot) = self.scene_snapshots.get(&key).cloned() else {
            return err(tag, status::ABSENT, "401 Scene not found");
        };
        for (address, level) in snapshot {
            let level_text = level.to_string();
            let args = [
                "LIGHTING",
                "RAMP",
                address.as_str(),
                level_text.as_str(),
                "0",
            ];
            let response = self.lighting(tag, &args);
            if response.status >= 400 {
                return response;
            }
        }
        ok(tag, vec![], "200 OK.")
    }

    fn stop_command(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(tag, status::BAD_REQUEST, "400 STOP requires a command id");
        }
        self.application_state
            .remove(&format!("TEST_SPAM {}", words[1]));
        Response {
            tag: tag.to_string(),
            lines: vec![],
            final_text: "207 Stopped.".to_string(),
            status: 207,
        }
    }

    fn convert_unit(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 4 || !matches!(words[1].to_ascii_uppercase().as_str(), "CHECK" | "CONVERT")
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 CONVERTUNIT requires CHECK or CONVERT and a mode",
            );
        }
        let mode = words[2].parse::<u8>().ok();
        if !matches!(mode, Some(1..=3)) {
            return err(tag, status::BAD_REQUEST, "405 Conversion mode out of range");
        }
        let Some(old_path) = self.qualify_unit(words[3]) else {
            return err(tag, status::BAD_REQUEST, "400 Invalid unit address");
        };
        let Some((project, net, old_address)) = self.unit_of(&old_path) else {
            return Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: "301 no".to_string(),
                status: 301,
            };
        };
        let exists = self
            .projects
            .get(&project)
            .and_then(|p| p.networks.get(&net))
            .is_some_and(|n| n.units.contains_key(&old_address));
        if !exists {
            return Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: "301 no".to_string(),
                status: 301,
            };
        }
        if words[1].eq_ignore_ascii_case("CHECK") {
            return ok(tag, vec![], "200 yes");
        }
        match mode.expect("validated") {
            1 if words.len() == 6 => {
                let network = self
                    .projects
                    .get_mut(&project)
                    .and_then(|p| p.networks.get_mut(&net))
                    .expect("unit resolved");
                for unit in [
                    network.units.get_mut(&old_address),
                    network.physical.get_mut(&old_address),
                ]
                .into_iter()
                .flatten()
                {
                    unit.unit_type = words[4].trim_matches('"').to_string();
                    unit.fields.insert(
                        "CatalogNumber".to_string(),
                        words[5].trim_matches('"').to_string(),
                    );
                }
                ok(tag, vec![], "200 OK")
            }
            2 if words.len() == 5 => {
                let Some(new_path) = self.qualify_unit(words[4]) else {
                    return err(
                        tag,
                        status::BAD_REQUEST,
                        "400 Invalid destination unit address",
                    );
                };
                let Some((new_project, new_net, new_address)) = self.unit_of(&new_path) else {
                    return Response {
                        tag: tag.to_string(),
                        lines: vec![],
                        final_text: "301 no".to_string(),
                        status: 301,
                    };
                };
                let source = self
                    .projects
                    .get(&project)
                    .and_then(|p| p.networks.get(&net))
                    .and_then(|n| n.units.get(&old_address))
                    .cloned()
                    .expect("unit resolved");
                let Some(destination) = self
                    .projects
                    .get_mut(&new_project)
                    .and_then(|p| p.networks.get_mut(&new_net))
                    .and_then(|n| n.units.get_mut(&new_address))
                else {
                    return Response {
                        tag: tag.to_string(),
                        lines: vec![],
                        final_text: "301 no".to_string(),
                        status: 301,
                    };
                };
                destination.fields.extend(source.fields);
                ok(tag, vec![], "200 OK")
            }
            3 if words.len() == 4 => ok(tag, vec![], "200 OK"),
            _ => err(
                tag,
                status::BAD_REQUEST,
                "400 Invalid arguments for conversion mode",
            ),
        }
    }

    fn qualify_unit(&self, raw: &str) -> Option<String> {
        if raw.starts_with("//") {
            return Some(raw.trim_matches('"').to_string());
        }
        let current = self.current.as_ref()?;
        let raw = raw.trim_matches('"').trim_start_matches('/');
        if raw.split('/').count() == 3 {
            Some(format!("//{current}/{raw}"))
        } else {
            None
        }
    }

    fn hidden_command(&mut self, tag: &str, words: &[&str]) -> Option<Response> {
        let (root, root_len, subcommands) = hidden_group(words)?;
        if words.len() == root_len || (words.len() == root_len + 1 && words[root_len] == "?") {
            return Some(envelope(
                tag,
                101,
                subcommands.iter().map(|sub| format!("Help: {root} {sub}")),
            ));
        }
        let sub = words[root_len].to_ascii_uppercase();
        if !subcommands.contains(&sub.as_str()) {
            return None;
        }
        let args = &words[root_len + 1..];

        if root == "ACCESS" {
            return Some(self.access_command(tag, &sub, args));
        }
        if root == "PP" {
            return self.pp_private_command(tag, &sub, args);
        }
        if root == "REPOSITORY" && sub == "USE" {
            if args.len() != 1 {
                return Some(err(tag, status::BAD_REQUEST, "400 Syntax Error."));
            }
            return Some(err(
                tag,
                502,
                "502 REPOSITORY USE requires unsupported server-global repository selection",
            ));
        }
        if root == "TRANSFORM" {
            return Some(err(
                tag,
                502,
                &format!(
                    "502 TRANSFORM {sub} requires proprietary repository transformation machinery"
                ),
            ));
        }
        if root == "PROJECT" && sub == "DIRFULL" {
            let mut rows: Vec<String> = self
                .projects
                .keys()
                .map(|name| format!("project={name} repository=memory state=loaded"))
                .collect();
            rows.sort();
            return Some(envelope(tag, 123, rows));
        }
        if root == "NET" && sub == "CHECK_UNRAVEL" {
            if args.len() != 1 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 NET CHECK_UNRAVEL requires a network",
                ));
            }
            return Some(match self.require_network(tag, args[0]) {
                Ok(_) => envelope(tag, 120, ["unravel_required=false"]),
                Err(response) => response,
            });
        }
        if root == "NET" && sub == "STATE_INTERVAL" {
            if args.len() != 2 || args[1].parse::<u32>().is_err() {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 NET STATE_INTERVAL requires a network and interval",
                ));
            }
            self.application_state.insert(
                format!("NET STATE_INTERVAL {}", args[0]),
                args[1].to_string(),
            );
            return Some(ok(tag, vec![], "200 OK"));
        }
        if root == "LABEL" && matches!(sub.as_str(), "KFIGET" | "KFISET") {
            let key = format!("LABEL {}", args.first().copied().unwrap_or(""));
            if sub == "KFIGET" {
                return Some(envelope(
                    tag,
                    300,
                    [self
                        .application_state
                        .get(&key)
                        .cloned()
                        .unwrap_or_default()],
                ));
            }
            if args.len() < 2 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 LABEL KFISET requires a target and value",
                ));
            }
            self.application_state.insert(key, args[1..].join(" "));
            return Some(ok(tag, vec![], "200 OK"));
        }

        // Detailed public handlers retain control of overlapping command
        // sets. This branch implements the private state-machine families.
        if !matches!(
            root,
            "APPLICATIONS"
                | "IDENTIFY"
                | "ACCESS_CONTROL"
                | "DEPLOY_QUEUE"
                | "PROGRAMMER"
                | "EVENT_CHANNEL"
                | "TRANSFORM"
        ) && !root.starts_with("DALI")
        {
            return None;
        }

        let state_prefix = format!("{root} {sub}");
        if sub == "LIST" || sub == "STATUS" {
            let mut rows: Vec<String> = self
                .application_state
                .iter()
                .filter(|(key, _)| key.starts_with(root))
                .map(|(key, value)| format!("{key}={value}"))
                .collect();
            rows.sort();
            return Some(ok(tag, rows, "200 OK"));
        }
        if matches!(sub.as_str(), "DELETE_ALL" | "RELOAD") {
            self.application_state
                .retain(|key, _| !key.starts_with(root));
            return Some(ok(tag, vec![], "200 OK"));
        }
        if args.is_empty() {
            return Some(err(
                tag,
                status::BAD_REQUEST,
                &format!("400 {state_prefix} requires arguments"),
            ));
        }
        let identity = args.first().copied().unwrap_or("default");
        let key = format!("{state_prefix} {identity}");
        if matches!(
            sub.as_str(),
            "DELETE" | "END" | "UNSUB" | "CANCEL_INSTRUCTION"
        ) {
            self.application_state.remove(&key);
        } else {
            self.application_state.insert(key, args.join(" "));
        }
        self.push_event(format!(
            "#e# {} {}",
            state_prefix.to_ascii_lowercase(),
            args.join(" ")
        ));
        Some(ok(tag, vec![], "200 OK"))
    }

    fn access_command(&mut self, tag: &str, sub: &str, args: &[&str]) -> Response {
        match sub {
            "LIST" if args.is_empty() => {
                let mut rows: Vec<String> = self
                    .application_state
                    .iter()
                    .filter(|(key, _)| key.starts_with("ACCESS "))
                    .map(|(key, value)| format!("{}={value}", &key[7..]))
                    .collect();
                rows.sort();
                envelope(tag, 303, rows)
            }
            "ADD" if args.len() >= 2 => {
                self.application_state
                    .insert(format!("ACCESS {}", args[0]), args[1..].join(" "));
                ok(tag, vec![], "200 OK")
            }
            "DELETE" if args.len() == 1 => {
                if self
                    .application_state
                    .remove(&format!("ACCESS {}", args[0]))
                    .is_some()
                {
                    ok(tag, vec![], "200 OK")
                } else {
                    err(tag, status::NOT_FOUND, "404 Access entry not found")
                }
            }
            "LOAD" | "SAVE" if args.len() <= 1 => ok(tag, vec![], "200 OK"),
            _ => err(tag, status::BAD_REQUEST, "400 Invalid ACCESS command"),
        }
    }

    fn pp_private_command(&mut self, tag: &str, sub: &str, args: &[&str]) -> Option<Response> {
        if !matches!(
            sub,
            "DEBUG"
                | "GET_UNIT_SPEC"
                | "GET_UNIT_CATALOG"
                | "RELOAD_CATALOG"
                | "CATALOG_INFO"
                | "LIST_CATALOG_NUMBERS"
                | "GET_RAW_DATA"
                | "SET_RAW_DATA"
                | "PATCH_VERSION"
                | "WRITE_PATCH"
        ) {
            return None;
        }
        if !self.allow_programming
            || matches!(self.access, AccessLevel::Admin | AccessLevel::Monitor)
        {
            return Some(err(tag, status::ACCESS_DENIED, "420 Access denied"));
        }
        Some(match sub {
            "RELOAD_CATALOG" if args.is_empty() => {
                self.spec_cache.clear();
                ok(tag, vec![], "200 OK")
            }
            "CATALOG_INFO" if args.is_empty() => envelope(
                tag,
                315,
                [format!(
                    "unitspec_dir={}",
                    self.unitspec_dir
                        .as_ref()
                        .map(|p| p.display().to_string())
                        .unwrap_or_default()
                )],
            ),
            "GET_UNIT_SPEC" | "GET_UNIT_CATALOG" | "LIST_CATALOG_NUMBERS" if !args.is_empty() => {
                let unit_type = args[0];
                if let Some(spec) = self.spec_for(unit_type) {
                    let rows: Vec<String> = spec
                        .into_iter()
                        .map(|param| {
                            format!("{}={}", param.name, param.get("Default").unwrap_or(""))
                        })
                        .collect();
                    envelope(tag, 315, rows)
                } else {
                    err(tag, status::NOT_FOUND, "404 Unit specification not found")
                }
            }
            "SET_RAW_DATA" if args.len() >= 2 => {
                self.application_state
                    .insert(format!("PP RAW {}", args[0]), args[1..].join(" "));
                ok(tag, vec![], "200 OK")
            }
            "GET_RAW_DATA" if args.len() == 1 => envelope(
                tag,
                315,
                [self
                    .application_state
                    .get(&format!("PP RAW {}", args[0]))
                    .cloned()
                    .unwrap_or_default()],
            ),
            "DEBUG" | "PATCH_VERSION" | "WRITE_PATCH" if !args.is_empty() => {
                self.application_state
                    .insert(format!("PP {sub}"), args.join(" "));
                ok(tag, vec![], "200 OK")
            }
            _ => err(
                tag,
                status::BAD_REQUEST,
                &format!("400 Invalid PP {sub} command"),
            ),
        })
    }
}

fn help_response(tag: &str, root: &str) -> Response {
    let rows = help_lines(root);
    envelope(
        tag,
        101,
        rows.into_iter()
            .map(|row| row.trim_start_matches("101-").to_string()),
    )
}

fn envelope<I, S>(tag: &str, code: u16, values: I) -> Response
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    let mut values: Vec<String> = values.into_iter().map(Into::into).collect();
    let final_value = values.pop().unwrap_or_else(|| "OK".to_string());
    Response {
        tag: tag.to_string(),
        lines: values,
        final_text: format!("{code} {final_value}"),
        status: code,
    }
}

fn fixed_help_response(tag: &str, rows: &[&str]) -> Response {
    let (final_text, intermediate) = rows
        .split_last()
        .expect("fixed native help always has a final row");
    Response {
        tag: tag.to_string(),
        lines: intermediate
            .iter()
            .map(|row| row.strip_prefix("101-").unwrap_or(row).to_string())
            .collect(),
        final_text: (*final_text).to_string(),
        status: 101,
    }
}

fn general_object_help(topic: &str) -> Option<&'static [&'static str]> {
    Some(match topic {
        "OID" => &[
            "101-Help: Syntax:  OID",
            "101 Help: Generate a unique Object ID (OID or uuid).",
        ],
        "TREE" | "TREEXML" | "TREEXMLDETAIL" | "REPORT" => {
            &["101 Help: No help is available for this command."]
        }
        "SHOW" => &[
            "101-Help: syntax: GET <object-id> <param-name>",
            "101-Help: or:     SHOW  <object-id> <param-name>",
            "101-Help: Show the parameter given in <param-name> for the object",
            "101-Help: given in <object-id>.",
            "101-Help: <object-id> is a network, group, unit, application, terminal or system entity",
            "101-Help: <param-name> is a named parameter or '*' to show all parameters, ",
            "101-Help: '?' to get a list of parameters, or '??' to get a list of parameters with",
            "101 Help: descriptions.",
        ],
        "NEW" => &[
            "101-Help: syntax: NEW <object-type> <object-id> <parameter>",
            "101-Help: Creates a new object of the specified object type",
            "101-Help:   <object-type>s are: UNIT | GROUP | IGROUP | PHANTOM",
            "101-Help:   <object-id> is a network, group, unit, or system entity",
            "101-Help: <param> is a parameter appropriate to the object type",
            "101-Help: In the case of a UNIT type, then there is a second parameter defining",
            "101 Help: the version of the unit to be created.",
        ],
        "BROADCAST_EVENT" => &[
            "101-Help: Syntax:  BROADCAST_EVENT SP event-class [event-text]",
            "101-Help: Send a broadcast event to the event and status change ports.",
            "101-Help:  event-class is the class of this event.",
            "101 Help:  event-text (optional) is the text that will be sent as an event.",
        ],
        _ => return None,
    })
}

fn valid_date(value: &str) -> bool {
    let parts: Vec<_> = value.split('-').collect();
    parts.len() == 3
        && parts[0].len() == 4
        && parts[1].parse::<u8>().is_ok_and(|v| (1..=12).contains(&v))
        && parts[2].parse::<u8>().is_ok_and(|v| (1..=31).contains(&v))
}

fn valid_time(value: &str) -> bool {
    let parts: Vec<_> = value.split(':').collect();
    parts.len() == 3
        && parts[0].parse::<u8>().is_ok_and(|v| v <= 23)
        && parts[1].parse::<u8>().is_ok_and(|v| v <= 59)
        && parts[2].parse::<u8>().is_ok_and(|v| v <= 59)
}

/// Generate a standards-shaped version-1 UUID for the public `OID` command.
///
/// Native C-Gate returns a time UUID.  Database identities keep their
/// deterministic test-friendly source in `fresh_oid`; this public factory is
/// intentionally independent and does not make the result resolvable.
fn fresh_command_oid() -> String {
    use std::sync::{
        atomic::{AtomicU16, Ordering},
        OnceLock,
    };
    use std::time::{SystemTime, UNIX_EPOCH};

    // Number of 100 ns intervals between 1582-10-15 and 1970-01-01.
    const UUID_EPOCH_OFFSET: u128 = 0x01b2_1dd2_1381_4000;
    static CLOCK_SEQUENCE: AtomicU16 = AtomicU16::new(0);
    static NODE: OnceLock<u64> = OnceLock::new();

    let unix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        / 100;
    let timestamp = ((UUID_EPOCH_OFFSET + unix) & ((1_u128 << 60) - 1)) as u64;
    let time_low = timestamp as u32;
    let time_mid = (timestamp >> 32) as u16;
    let time_high = ((timestamp >> 48) as u16 & 0x0fff) | 0x1000;
    let sequence = (CLOCK_SEQUENCE.fetch_add(1, Ordering::Relaxed) & 0x3fff) | 0x8000;
    // RFC 4122 permits a locally generated node when the multicast bit is
    // set.  Mix process identity with the time field without exposing a host
    // MAC address.
    let node = *NODE.get_or_init(|| {
        0x0100_0000_0000_u64
            | (((u64::from(std::process::id()) << 16) ^ timestamp) & 0x00ff_ffff_ffff)
    });
    format!("{time_low:08x}-{time_mid:04x}-{time_high:04x}-{sequence:04x}-{node:012x}")
}

fn parse_duration(value: &str) -> Option<i64> {
    let (number, multiplier) = if let Some(number) = value.strip_suffix(['s', 'S']) {
        (number, 1_i64)
    } else if let Some(number) = value.strip_suffix(['m', 'M']) {
        (number, 60_i64)
    } else {
        (value, 1_i64)
    };
    number
        .parse::<i64>()
        .ok()?
        .checked_mul(multiplier)
        .filter(|v| (0..=i32::MAX as i64).contains(v))
}

fn hidden_group(words: &[&str]) -> Option<(&'static str, usize, &'static [&'static str])> {
    DECOMPILED_COMMAND_GROUPS
        .iter()
        .filter_map(|(root, subcommands)| {
            let root_words: Vec<&str> = root.split_whitespace().collect();
            (words.len() >= root_words.len()
                && words
                    .iter()
                    .zip(&root_words)
                    .all(|(actual, expected)| actual.eq_ignore_ascii_case(expected)))
            .then_some((*root, root_words.len(), *subcommands))
        })
        .max_by_key(|(_, length, _)| *length)
}

/// Dependency-free SHA-256 for the private FILE SHA256 command.
pub(crate) fn sha256_hex(input: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut hash = [
        0x6a09e667_u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (input.len() as u64).wrapping_mul(8);
    let mut data = input.to_vec();
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0);
    }
    data.extend_from_slice(&bit_len.to_be_bytes());
    for block in data.as_chunks::<64>().0 {
        let mut words = [0_u32; 64];
        for (index, bytes) in block.as_chunks::<4>().0.iter().enumerate() {
            words[index] = u32::from_be_bytes(*bytes);
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = hash;
        for index in 0..64 {
            let sum1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(sum1)
                .wrapping_add(choose)
                .wrapping_add(K[index])
                .wrapping_add(words[index]);
            let sum0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = sum0.wrapping_add(majority);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        for (slot, value) in hash.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *slot = slot.wrapping_add(value);
        }
    }
    hash.iter().map(|word| format!("{word:08x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::format_response;
    use std::collections::HashSet;

    #[test]
    fn manual_inventory_is_complete_and_unique() {
        assert_eq!(DOCUMENTED_COMMANDS.len(), 224);
        assert_eq!(
            DOCUMENTED_COMMANDS
                .iter()
                .copied()
                .collect::<HashSet<_>>()
                .len(),
            224
        );
        assert_eq!(DOCUMENTED_COMMANDS.first(), Some(&"#"));
        assert_eq!(DOCUMENTED_COMMANDS.last(), Some(&"LOG EXTRACT"));
    }

    #[test]
    fn application_specs_are_documented_and_unique() {
        let specs: Vec<_> = APPLICATION_COMMANDS.iter().chain(MEDIA_COMMANDS).collect();
        assert_eq!(
            specs.iter().map(|s| s.name).collect::<HashSet<_>>().len(),
            specs.len()
        );
        for spec in specs {
            assert!(DOCUMENTED_COMMANDS.contains(&spec.name), "{}", spec.name);
            assert!(spec.max_args.is_none_or(|max| max >= spec.min_args));
        }
    }

    #[test]
    fn every_manual_heading_reaches_a_named_handler() {
        for (index, name) in DOCUMENTED_COMMANDS.iter().enumerate() {
            let mut server = Server::new(AccessLevel::Program).with_programming(true);
            let response = server.handle(&format!("[{index}] {name}"));
            assert_ne!(
                response.final_text, "400 Unknown command",
                "manual command has no dispatcher: {name}"
            );
        }
    }

    #[test]
    fn application_and_general_commands_are_stateful_and_validated() {
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(server.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            server
                .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(server.handle("[3] AIRCON REFRESH 254/172 1").status, 200);
        assert_eq!(server.handle("[4] AIRCON REFRESH 254/172").status, 400);
        assert_eq!(
            server.handle("[5] MEDIATRANSPORT PLAY 254/192 1").status,
            200
        );
        assert_eq!(server.handle("[6] CONFIG SET sync-time 250").status, 200);
        assert!(server
            .handle("[7] CONFIG GET sync-time")
            .final_text
            .ends_with("sync-time=250"));
        assert_eq!(server.handle("[8] LOCK //TEST/254").status, 225);
        assert_eq!(server.handle("[9] UNLOCK //TEST/254").status, 226);
        assert_eq!(
            server.handle("[10] CLOCK DATE 254/223 2026-09-24").status,
            232
        );
        assert_eq!(
            server.handle("[11] CLOCK TIME 254/223 25:00:00").status,
            400
        );
    }

    #[test]
    fn legacy_lighting_scene_and_database_commands_round_trip() {
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(server.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            server
                .handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(server.handle("[3] ON 254/56/1").status, 200);
        assert_eq!(server.handle("[4] RAMP 254/56/2 50% 2m").status, 200);
        let snapshot = server.handle("[5] GETSTATE //TEST/254");
        assert!(snapshot.lines.iter().any(|line| line == "level=56/1=255"));
        assert!(snapshot.lines.iter().any(|line| line == "level=56/2=128"));
        assert_eq!(server.handle("[6] SCENE RECORD lounge evening").status, 200);
        assert_eq!(server.handle("[7] OFF 254/56/1").status, 200);
        assert_eq!(server.handle("[8] SCENE PLAY lounge evening").status, 200);
        assert!(server
            .handle("[9] GETSTATE //TEST/254")
            .lines
            .iter()
            .any(|line| line == "level=56/1=255"));
        let added = server.handle("[10] DBADD //TEST/254 Unit");
        assert_eq!(added.status, 301);
        let oid = added.final_text.trim_start_matches("301 OID=");
        assert_eq!(
            server
                .handle(&format!("[10a] DBSET !{oid}/Address 20"))
                .status,
            200
        );
        assert_eq!(
            server
                .handle(&format!("[10b] DBSET !{oid}/TagName Legacy"))
                .status,
            200
        );
        assert_eq!(server.handle("[11] DBSAVE memory.db").status, 200);
        assert_eq!(server.handle("[12] DBNEW").status, 200);
        assert_eq!(server.handle("[13] DBLOAD memory.db").status, 200);
        assert!(server.handle("[14] GET 254 UNITS").status < 400);
    }

    #[test]
    fn decompiled_registry_is_complete_unique_and_dispatched() {
        let count: usize = DECOMPILED_COMMAND_GROUPS
            .iter()
            .map(|(_, subcommands)| subcommands.len())
            .sum();
        assert_eq!(count, 268);
        let names: HashSet<String> = DECOMPILED_COMMAND_GROUPS
            .iter()
            .flat_map(|(root, subcommands)| {
                subcommands
                    .iter()
                    .map(move |subcommand| format!("{root} {subcommand}"))
            })
            .collect();
        assert_eq!(names.len(), 268);
        for (index, name) in names.iter().enumerate() {
            let mut server = Server::new(AccessLevel::Program).with_programming(true);
            let response = server.handle(&format!("[hidden-{index}] {name}"));
            assert_ne!(
                response.final_text, "400 Unknown command",
                "decompiled command has no dispatcher: {name}"
            );
        }
    }

    #[test]
    fn private_file_and_queue_families_round_trip() {
        let mut server = Server::new(AccessLevel::Program).with_programming(true);
        assert_eq!(server.handle("[0] FILE MKDIR macros").status, 200);
        assert_eq!(
            server
                .handle_document("[1] FILE UPLOAD macros/test.txt", "YWJj\n")
                .status,
            200
        );
        assert_eq!(
            server.handle("[2] FILE SHA256 macros/test.txt").final_text,
            "302 File=macros/test.txt SHA256Hash=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert!(server
            .handle("[3] FILE DOWNLOAD macros/test.txt")
            .lines
            .iter()
            .any(|line| line == "347-YWJj"));
        assert_eq!(
            server
                .handle("[4a] PROGRAMMER CREATE job1 \"Task\" \"Local\"")
                .status,
            200
        );
        assert_eq!(server.handle("[4] DEPLOY_QUEUE ADD job1").status, 200);
        assert!(server
            .handle("[5] DEPLOY_QUEUE LIST")
            .lines
            .iter()
            .any(|line| line.contains("job1")));
        assert_eq!(server.handle("[6] DALI GATEWAY LIST").status, 200);
    }

    #[test]
    fn new_multi_status_envelopes_remain_parseable_on_the_wire() {
        let mut server = Server::new(AccessLevel::Program);
        let json =
            format_response(&server.handle("[json] DBGETJSON NAC_ROUTING_TABLE //TEST/254/p/1"));
        assert!(json.contains("[json] 345-Begin JSON\n"), "{json}");
        assert!(json.contains("[json] 346-[]\n"), "{json}");
        assert!(json.ends_with("[json] 346 End JSON\n"), "{json}");

        let help = format_response(&server.handle("[help] DALI GATEWAY"));
        assert!(help.contains("[help] 101-Help: DALI GATEWAY FACTORY_RESET\n"));
        assert!(help.ends_with("[help] 101 Help: DALI GATEWAY NAC_SUMMARY_LIST\n"));
    }
}
