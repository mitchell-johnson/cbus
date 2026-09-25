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
        min_args: 6,
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
        min_args: 6,
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
        min_args: 6,
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
    err, network_path, ok, status, valid_name, valid_target, AccessLevel, Network, NetworkState,
    Response, Server,
};

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

        // The wire server cannot express a command with no response through
        // `Response`; comments therefore complete locally with 200 and never
        // mutate state. TCP clients normally strip them before sending.
        if first == "#" || first == "//" {
            return Some(ok(tag, vec![], "200 Comment ignored"));
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
            if words.len() != 1 {
                return Some(err(tag, status::BAD_REQUEST, "400 OID takes no arguments"));
            }
            return Some(Response {
                tag: tag.to_string(),
                lines: vec![],
                final_text: format!("302 OID={}", self.issue_oid()),
                status: 302,
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
            if words.len() != 2 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 REPORT requires a network",
                ));
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
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 BROADCAST_EVENT requires a class",
                ));
            }
            self.push_event(format!("#e# {}", words[1..].join(" ")));
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

        if first == "PORT" && words.len() >= 2 {
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
            "LIST" | "IFLIST" if words.len() == 2 => {
                envelope(tag, 121, ["interface=loopback address=127.0.0.1"])
            }
            "REFRESH" if words.len() == 2 => ok(tag, vec![], "200 OK"),
            "CNISCAN" if (2..=4).contains(&words.len()) => ok(tag, vec![], "200 OK"),
            "CNISCAN2" if (2..=5).contains(&words.len()) => ok(tag, vec![], "200 OK"),
            "PROBE" if words.len() == 4 => {
                let kind = words[2].to_ascii_uppercase();
                if matches!(
                    kind.as_str(),
                    "SERIAL" | "SOCKET" | "CNI" | "WISER" | "ETHERLITE"
                ) {
                    envelope(
                        tag,
                        121,
                        [format!(
                            "type={} address={} reachable=false",
                            words[2], words[3]
                        )],
                    )
                } else {
                    err(tag, status::BAD_REQUEST, "400 Unknown port type")
                }
            }
            _ => err(tag, status::BAD_REQUEST, "400 Invalid PORT command"),
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
        if words.len() < 2 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 SHOW requires an object identifier",
            );
        }
        let mut get_words = Vec::with_capacity(words.len());
        get_words.push("GET");
        get_words.extend_from_slice(&words[1..]);
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
        if words.len() < 3
            || !matches!(
                words[1].to_ascii_uppercase().as_str(),
                "UNIT" | "GROUP" | "PHANTOM"
            )
            || !valid_target(words[2])
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NEW requires UNIT, GROUP or PHANTOM and an identifier",
            );
        }
        self.application_state
            .insert(format!("NEW {}", words[2]), words[1..].join(" "));
        ok(tag, vec![], "200 OK.")
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
        let Some(address) = (0_u16..=255)
            .map(|n| n as u8)
            .find(|n| !project.networks.contains_key(n))
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
                units: Default::default(),
                physical: Default::default(),
                levels: Default::default(),
            },
        );
        self.known_oids.insert(oid);
        envelope(tag, 301, [format!("network={address}")])
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
            "DBCREATE" | "DBNEW" => Some(self.db_new(tag, words)),
            "DBLOAD" => Some(self.db_load(tag, words)),
            "DBSAVE" => Some(self.db_save(tag, words)),
            "DBNETWORKPATH" => Some(self.db_network_path(tag, words)),
            "DBRENAMENET" => {
                let mut alias = words.to_vec();
                alias[0] = "DBRENAMENETSAFE";
                Some(self.dbrename_net(tag, &alias))
            }
            "DBSET" => {
                let mut alias = words.to_vec();
                alias[0] = "DBSETSAFE";
                Some(self.dbset(tag, &alias))
            }
            "DBTAGLIST" => Some(self.db_tag_list(tag, words)),
            "DBUPDATE" => Some(self.db_update(tag, words)),
            "DBVERIFY" => Some(self.db_verify(tag, words)),
            _ => None,
        }
    }

    fn dbadd_unsafe(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_target(words[1]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBADD requires a parent and element type",
            );
        }
        let element = words[2].to_ascii_uppercase();
        if element == "PROJECT" {
            let name = format!("PROJECT{}", self.projects.len() + 1);
            let args = ["PROJECT", "NEW", name.as_str()];
            return self.project_new(tag, &args);
        }
        let Some((project, net)) = self.network_of(words[1]) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        let network = self
            .projects
            .get(&project)
            .and_then(|p| p.networks.get(&net))
            .expect("network resolved");
        let address = if element == "UNIT" {
            (0_u16..=255)
                .map(|n| n as u8)
                .find(|n| !network.units.contains_key(n))
        } else {
            (0_u16..=255).map(|n| n as u8).find(|n| {
                !self
                    .objects
                    .contains(&format!("{}-{element}-{n}", words[1]))
            })
        };
        let Some(address) = address else {
            return err(
                tag,
                status::CONFLICT_EXISTS,
                "409 No element address available",
            );
        };
        let name = format!("{element}{address}");
        let args = [
            "DBADDSAFE",
            words[1],
            element.as_str(),
            &address.to_string(),
            name.as_str(),
        ];
        self.dbadd(tag, &args)
    }

    fn dbcopy_unsafe(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_target(words[1]) || !valid_target(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBCOPY requires a source and destination parent",
            );
        }
        let address = Server::split_unit(words[1])
            .map(|(_, _, address)| address)
            .unwrap_or(0);
        let name = Server::split_unit(words[1])
            .and_then(|(project, net, address)| {
                self.projects
                    .get(&project)?
                    .networks
                    .get(&net)?
                    .units
                    .get(&address)
            })
            .and_then(|unit| unit.fields.get("UnitName"))
            .cloned()
            .unwrap_or_else(|| format!("COPY{address}"));
        let address_text = address.to_string();
        let args = [
            "DBCOPYSAFE",
            words[1],
            words[2],
            address_text.as_str(),
            name.as_str(),
        ];
        self.dbcopy(tag, &args)
    }

    fn db_new(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 1 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBCREATE/DBNEW takes no arguments",
            );
        }
        let Some(name) = self.current.clone() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        if let Some(project) = self.projects.get_mut(&name) {
            project.networks.clear();
        }
        let prefix = format!("//{name}/");
        self.db_fields.retain(|key, _| !key.starts_with(&prefix));
        self.objects.retain(|key| !key.starts_with(&prefix));
        self.db_levels
            .retain(|_, level| !level.parent.starts_with(&prefix));
        ok(tag, vec![], "200 OK.")
    }

    fn db_save(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || words[1].is_empty() {
            return err(tag, status::BAD_REQUEST, "400 DBSAVE requires a filename");
        }
        let Some(project) = self
            .current
            .as_ref()
            .and_then(|name| self.projects.get(name))
            .cloned()
        else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
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
                "400 DBTAGLIST takes one optional pattern",
            );
        }
        let pattern = words.get(1).map(|p| p.to_ascii_lowercase());
        let mut rows = Vec::new();
        for (project_name, project) in &self.projects {
            for (net, network) in &project.networks {
                rows.push(format!("//{project_name}/{net}/TagName={}", network.name));
                for (address, unit) in &network.units {
                    let name = unit.fields.get("UnitName").cloned().unwrap_or_default();
                    rows.push(format!("//{project_name}/{net}/p/{address}/TagName={name}"));
                }
            }
        }
        rows.retain(|row| {
            pattern
                .as_ref()
                .is_none_or(|p| row.to_ascii_lowercase().contains(p))
        });
        rows.sort();
        envelope(tag, 342, rows)
    }

    fn db_update(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(2..=3).contains(&words.len())
            || words
                .get(2)
                .is_some_and(|word| !word.eq_ignore_ascii_case("UNITDELETE"))
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBUPDATE requires a network and optional UnitDelete",
            );
        }
        let (project, net) = match self.require_network(tag, words[1]) {
            Ok(value) => value,
            Err(response) => return response,
        };
        let network = self
            .projects
            .get_mut(&project)
            .and_then(|p| p.networks.get_mut(&net))
            .expect("network resolved");
        if words.len() == 3 {
            network
                .units
                .retain(|address, _| network.physical.contains_key(address));
        }
        for (address, unit) in network.physical.clone() {
            network.units.insert(address, unit);
        }
        ok(tag, vec![], "200 OK.")
    }

    fn db_verify(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 1 {
            return err(tag, status::BAD_REQUEST, "400 DBVERIFY takes no arguments");
        }
        let Some(project) = self
            .current
            .as_ref()
            .and_then(|name| self.projects.get(name))
        else {
            return err(tag, status::NOT_FOUND, "440 There is no tag database");
        };
        let mut differences = Vec::new();
        for (net, network) in &project.networks {
            for address in network
                .units
                .keys()
                .filter(|address| !network.physical.contains_key(address))
            {
                differences.push(format!(
                    "Difference: //{}/{net}/p/{address} missing from network",
                    project.name
                ));
            }
            for address in network
                .physical
                .keys()
                .filter(|address| !network.units.contains_key(address))
            {
                differences.push(format!(
                    "Difference: //{}/{net}/p/{address} missing from database",
                    project.name
                ));
            }
        }
        if differences.is_empty() {
            ok(tag, vec![], "200 OK.")
        } else {
            Response {
                tag: tag.to_string(),
                lines: differences
                    .into_iter()
                    .map(|line| format!("345-{line}"))
                    .collect(),
                final_text: "408 Operation failed: Verify found differences".to_string(),
                status: status::CONFLICT_STATE,
            }
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

        if root == "FILE" {
            return Some(self.file_command(tag, &sub, args));
        }
        if root == "ACCESS" {
            return Some(self.access_command(tag, &sub, args));
        }
        if root == "PP" {
            return self.pp_private_command(tag, &sub, args);
        }
        if root == "REPOSITORY" && sub == "USE" {
            if args.len() != 1 {
                return Some(err(
                    tag,
                    status::BAD_REQUEST,
                    "400 REPOSITORY USE requires a name",
                ));
            }
            self.application_state
                .insert("REPOSITORY".to_string(), args[0].to_string());
            return Some(ok(tag, vec![], "200 OK"));
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

        if root == "APPLICATIONS" && sub == "GET_CATALOG" {
            return Some(envelope(
                tag,
                315,
                [
                    "56=Lighting",
                    "172=Air Conditioning",
                    "192=Media Transport",
                    "205=Audio",
                ],
            ));
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

    fn file_command(&mut self, tag: &str, sub: &str, args: &[&str]) -> Response {
        match sub {
            "UPLOAD" if args.len() >= 2 && safe_server_path(args[0]) => {
                self.file_store
                    .insert(args[0].to_string(), args[1..].join(" ").into_bytes());
                ok(tag, vec![], "200 OK")
            }
            "DOWNLOAD" if args.len() == 1 && safe_server_path(args[0]) => {
                if let Some(bytes) = self.file_store.get(args[0]) {
                    envelope(tag, 347, [String::from_utf8_lossy(bytes).to_string()])
                } else {
                    err(tag, status::NOT_FOUND, "404 File not found")
                }
            }
            "SHA256" if args.len() == 1 && safe_server_path(args[0]) => {
                if let Some(bytes) = self.file_store.get(args[0]) {
                    envelope(tag, 300, [sha256_hex(bytes)])
                } else {
                    err(tag, status::NOT_FOUND, "404 File not found")
                }
            }
            "DIR" | "LS" if args.len() <= 1 => {
                let prefix = args.first().copied().unwrap_or("");
                let mut rows: Vec<String> = self
                    .file_store
                    .keys()
                    .filter(|path| path.starts_with(prefix))
                    .cloned()
                    .collect();
                rows.sort();
                envelope(tag, 123, rows)
            }
            "DELETE" if args.len() == 1 && safe_server_path(args[0]) => {
                if self.file_store.remove(args[0]).is_some() {
                    ok(tag, vec![], "200 OK")
                } else {
                    err(tag, status::NOT_FOUND, "404 File not found")
                }
            }
            "MKDIR" if args.len() == 1 && safe_server_path(args[0]) => {
                self.file_store
                    .entry(format!("{}/", args[0].trim_end_matches('/')))
                    .or_default();
                ok(tag, vec![], "200 OK")
            }
            _ => err(tag, status::BAD_REQUEST, "400 Invalid FILE command"),
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

fn safe_server_path(path: &str) -> bool {
    !path.is_empty()
        && !path.starts_with(['/', '\\'])
        && !path.contains('\0')
        && !path.split(['/', '\\']).any(|part| part == "..")
}

/// Dependency-free SHA-256 for the private FILE SHA256 command.
fn sha256_hex(input: &[u8]) -> String {
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
        assert_eq!(server.handle("[10] DBADD //TEST/254 Unit").status, 200);
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
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(
            server.handle("[1] FILE UPLOAD macros/test.txt abc").status,
            200
        );
        assert_eq!(
            server.handle("[2] FILE SHA256 macros/test.txt").final_text,
            "300 ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert!(server
            .handle("[3] FILE DOWNLOAD macros/test.txt")
            .final_text
            .ends_with("abc"));
        assert_eq!(
            server.handle("[4] DEPLOY_QUEUE ADD job1 payload").status,
            200
        );
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
