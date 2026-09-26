//! Exact retained C-Gate 3.4 parent-command help envelopes.
//!
//! These endpoints are local command discovery only. They never imply that
//! every child command has a physical or repository backend; each child keeps
//! its own capability-matrix classification and fail-closed boundary.

use super::*;

const CLOCK_HELP: &[&str] = &[
    "Help: CLOCK commands:",
    "Help:  CLOCK ? Help for these commands",
    "Help:  CLOCK DATE - Set or get the date for this network",
    "Help:  CLOCK REQUEST_REFRESH - Send a REQUEST REFRESH command on a network",
    "Help:  CLOCK TIME - Set or get the time for this network",
];

const ENABLE_HELP: &[&str] = &[
    "Help: ENABLE commands:",
    "Help:  ENABLE ? Help for these commands",
    "Help:  ENABLE LABEL - Send label information for this application",
    "Help:  ENABLE REMOVE - Remove any reference to this network variable",
    "Help:  ENABLE SET - Set an enable variable to the given value",
];

const LIGHTING_HELP: &[&str] = &[
    "Help: LIGHTING commands:",
    "Help:  LIGHTING ? Help for these commands",
    "Help:  LIGHTING LABEL - Send label information for this application",
    "Help:  LIGHTING OFF - ",
    "Help:  LIGHTING ON - ",
    "Help:  LIGHTING RAMP - ",
    "Help:  LIGHTING TERMINATERAMP - ",
    "Help:  LIGHTING UNICODELABEL - ",
];

const TEMPERATURE_HELP: &[&str] = &[
    "Help: TEMPERATURE commands:",
    "Help:  TEMPERATURE ? Help for these commands",
    "Help:  TEMPERATURE BROADCAST - Broadcast a temperature value to the given temperature group",
];

const TRIGGER_HELP: &[&str] = &[
    "Help: TRIGGER commands:",
    "Help:  TRIGGER ? Help for these commands",
    "Help:  TRIGGER EVENT - Send a trigger event command to the network",
    "Help:  TRIGGER INDICATORKILL - Send a trigger indicator-kill command to the network",
    "Help:  TRIGGER LABEL - Send label information for this application",
    "Help:  TRIGGER UNICODELABEL - ",
];

const SHORTMESSAGE_HELP: &[&str] = &[
    "Help: SHORTMESSAGE commands:",
    "Help:  SHORTMESSAGE ? Help for these commands",
    "Help:  SHORTMESSAGE REFRESH - Transmit the information message on the given service class as soon as possible",
    "Help:  SHORTMESSAGE SEND - Send a short message",
];

const EREPORT_HELP: &[&str] = &[
    "Help: EREPORT commands:",
    "Help:  EREPORT ? Help for these commands",
    "Help:  EREPORT MESSAGE - Send an error reporting event",
];

const TEST_SPAM_HELP: &[&str] = &[
    "Help: TEST_SPAM commands:",
    "Help:  TEST_SPAM ? Help for these commands",
    "Help:  TEST_SPAM EREPORT - Generate random error reporting messages on a network",
    "Help:  TEST_SPAM LIGHTING - Generate random lighting messages on a network",
    "Help:  TEST_SPAM LIST - List active generation sessions.",
    "Help:  TEST_SPAM STOP - Stop an active generation session.",
];

const CGL_HELP: &[&str] = &[
    "Help: CGL commands:",
    "Help:  CGL ? Help for these commands",
    "Help:  CGL EXPORT - Export a project to CGL format",
    "Help:  CGL IMPORT - Import to a project from CGL",
];

const TRANSFORM_HELP: &[&str] = &[
    "Help: TRANSFORM commands:",
    "Help:  TRANSFORM ? Help for these commands",
    "Help:  TRANSFORM MIGRATE_SQL - Migrate a SQLite (DB) Project file to the latest Schema version",
    "Help:  TRANSFORM PROJECT - Transform a Project database using a transform (XSLT script)",
    "Help:  TRANSFORM SQL_TO_XML - Transform a SQLite (DB) Project file to an XML Project file",
    "Help:  TRANSFORM SQL_TO_XML_CGATE2 - Transform a SQLite (DB) Project file to an cgate2 XML Project file, converted project file should not include any tags introduced in cgate3 ",
    "Help:  TRANSFORM XML_TO_SQL - Transform an XML Project file to a SQLite (DB) Project file",
];

const IDENTIFY_HELP: &[&str] = &[
    "Help: IDENTIFY commands:",
    "Help:  IDENTIFY ? Help for these commands",
    "Help:  IDENTIFY OFF - ",
    "Help:  IDENTIFY ON - ",
    "Help:  IDENTIFY RAMP - ",
    "Help:  IDENTIFY TERMINATERAMP - ",
];

const APPLICATIONS_HELP: &[&str] = &[
    "Help: APPLICATIONS commands:",
    "Help:  APPLICATIONS ? Help for these commands",
    "Help:  APPLICATIONS GET_CATALOG - Get the Application Catalog file as XML",
];

const CALCULATOR_HELP: &[&str] = &[
    "Help: CALCULATOR commands:",
    "Help:  CALCULATOR ? Help for these commands",
    "Help:  CALCULATOR TEST - Run the calculator for this network",
];

const REPOSITORY_HELP: &[&str] = &[
    "Help: REPOSITORY commands:",
    "Help:  REPOSITORY ? Help for these commands",
    "Help:  REPOSITORY LIST - Return a list of project repositories on the C-Gate Server",
    "Help:  REPOSITORY USE - Set the current project repository to be used by this command session",
];

fn rows(family: &str) -> Option<&'static [&'static str]> {
    Some(match family {
        "CLOCK" => CLOCK_HELP,
        "ENABLE" => ENABLE_HELP,
        "LIGHTING" => LIGHTING_HELP,
        "TEMPERATURE" => TEMPERATURE_HELP,
        "TRIGGER" => TRIGGER_HELP,
        "SHORTMESSAGE" => SHORTMESSAGE_HELP,
        "EREPORT" => EREPORT_HELP,
        "TEST_SPAM" => TEST_SPAM_HELP,
        "CGL" => CGL_HELP,
        "TRANSFORM" => TRANSFORM_HELP,
        "IDENTIFY" => IDENTIFY_HELP,
        "APPLICATIONS" => APPLICATIONS_HELP,
        "CALCULATOR" => CALCULATOR_HELP,
        "REPOSITORY" => REPOSITORY_HELP,
        _ => return None,
    })
}

/// Serve a bare/`?` family root or `HELP <family>` when retained evidence
/// exists. Any extra token is left to the family dispatcher or 502 boundary.
pub(super) fn response(tag: &str, words: &[&str], upper: &[String]) -> Option<Response> {
    let family = upper.first()?.as_str();
    if let Some(help) = rows(family) {
        if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
            return Some(command_help(tag, help));
        }
    }
    if family == "HELP" && words.len() == 2 {
        return rows(upper.get(1)?.as_str()).map(|help| command_help(tag, help));
    }
    None
}
