//! Native C-Gate 3.4 configuration catalogue and bounded state helpers.
//!
//! The metadata below is retained from the pinned 3.4.0.2001 daemon. Runtime
//! effects belong to the native daemon and are not inferred from these values.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ConfigScope {
    Global,
    Project,
    Network,
}

impl ConfigScope {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Global => "global",
            Self::Project => "project",
            Self::Network => "network",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ConfigParameter {
    pub(crate) name: &'static str,
    pub(crate) default: &'static str,
    pub(crate) description: &'static str,
    pub(crate) scope: ConfigScope,
    pub(crate) effective: &'static str,
    pub(crate) listed: bool,
    pub(crate) obsolete: bool,
}

pub(crate) const CONFIG_HELP: &[&str] = &[
    "Help: CONFIG commands:",
    "Help:  CONFIG ? Help for these commands",
    "Help:  CONFIG GET - ",
    "Help:  CONFIG INFO - ",
    "Help:  CONFIG LOAD - ",
    "Help:  CONFIG OBGET - ",
    "Help:  CONFIG OBRESET - ",
    "Help:  CONFIG OBSET - ",
    "Help:  CONFIG SAVE - ",
    "Help:  CONFIG SET - ",
];

pub(crate) const CONFIG_PARAMETERS: &[ConfigParameter] = &[
    ConfigParameter { name: "accept-connections-from", default: "all", description: "Space separated list of IP addresses or hostnames from which to accept command connections", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "access-control-file", default: "access.txt", description: "Name of this access control file relative to the config directory", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "allow-fast-start", default: "no", description: "Allow networks to use database for fast startup", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "allow-recall-write", default: "yes", description: "Enable the recall from command sessions", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "allow-v3-pci", default: "yes", description: "Allow network to use version 3 or later PCI advanced features", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "application.catalog.directory", default: "unitspec", description: "directory where application catalog is stored", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "application.catalog.filename", default: "applications.xml", description: "application catalog filename", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "application.model-change-events", default: "yes", description: "show events indicating model updates from sync processes", scope: ConfigScope::Project, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "application.show-command-failure", default: "yes", description: "Show SAL command failures in SCP and event port", scope: ConfigScope::Project, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "auto-reopen", default: "yes", description: "Automatically attempt to re-open networks that have been closed due to failures.", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "cbus-application", default: "56", description: "The default application number for this network. This should be left set to 56", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "cbus-tx-delay", default: "250", description: "Time in milliseconds between commands sent to the network if there is no other mechanism in use (flow control, pci-sync)", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "cbus.tx-cache", default: "yes", description: "Cache outgoing identical commands", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "cbus.tx-compress", default: "yes", description: "Perform header compression on outgoing commands", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "ccp.display-oids", default: "yes", description: "Display OIDs in the config change port (CCP)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "ccp.display-state", default: "yes", description: "Display object state changes in the config change port (CCP)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "cgate-name", default: "Schneider Electric C-Gate", description: "Name of this server", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "cgroups-file", default: "cgroups.txt", description: "Name of the C-Groups file in the config directory", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "clock.master", default: "no", description: "Operate the clock application in master mode", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "clock.mastermode", default: "secondary", description: "Selects primary or secondard master mode", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "clock.update-interval", default: "30", description: "Interval in minutes between clock and timekeeping messages", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "command-local-address", default: "", description: "If set, gives the IP address that the command interface server will be started on", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "command-port", default: "20023", description: "TCP port number for the command interface", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "command.encoding", default: "utf-8", description: "character encoding used for command, event, SCP and CCP ports", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "command.show-responses", default: "yes", description: "produce an event for each response to a command", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "command.show-time", default: "no", description: "show execution time events for commands", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "comms-debug", default: "no", description: "Enable write of comms debug log", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "config-change-port", default: "20026", description: "Port number to use for the config change port", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "config-path", default: "config", description: "Path to directory where configuration files are held", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "console.enable-commands", default: "yes", description: "allow command input on the console", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "dali.catalogue.dir.sys", default: "dali_catalogue/", description: "Base directory for Dali Catalogue definitions by Schneider Electric", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "dali.catalogue.dir.user", default: "Dali Catalogue/", description: "Base directory for Custom Dali Catalogue definitions by Users", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "default-tag-db", default: "", description: "(DEPRECATED -- only supported to prevent errors for old configs", scope: ConfigScope::Global, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "enable-xml-to-sql-background-job", default: "yes", description: "Enable the background job of converting XML to SQL.", scope: ConfigScope::Global, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "enable.save-state", default: "no", description: "Allow the Control Enable application to save state to disk and restore it", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.asynchronous", default: "yes", description: "Enable asynchronous logging to the event file.", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "event-file.buffer-size", default: "2000", description: "Maximum number of lines in the event-file buffer", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.event-level", default: "9", description: "Event level to log to the event file.", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.keep-days", default: "30", description: "Number of days worth of event files to keep", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.split", default: "yes", description: "Determines whether the event-file will be split", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.split-count", default: "50", description: "Maximum number of split event-files", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.split-size", default: "5000000", description: "Size in bytes at which to split the event-file", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-file.startup-dump", default: "yes", description: "Dump useful information to the event file on startup", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-filename", default: "event.log", description: "Filename for the event log (if enabled by use-event-file)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-host", default: "localhost", description: "Hostname to send events to, if event-mode is set to socket", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-millis", default: "yes", description: "Show milliseconds in event outout displayed as .xxx after time", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-mode", default: "server", description: "Set to server to run an event server, or as socket to deliver events to another host/port", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-port", default: "20024", description: "TCP port number for the event interface", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-printer", default: "", description: "Name of device to use as event printer (eg. LPT1)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event-sink.buffer-size", default: "500", description: "Maximum number of lines in each event-sink by default", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "event.display-oids", default: "yes", description: "Display OIDs in event output if OID is available", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "file.base", default: ".", description: "Root directory for FILE commands", scope: ConfigScope::Global, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "global-event-level", default: "5", description: "Global event reporting level (events <= event level will be reported (range 0-9)", scope: ConfigScope::Global, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "heartbeat-time", default: "0", description: "Number of seconds between heartbeat events", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "hide-project-names", default: "no", description: "Do not show project names in any output from the server", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "instance.lock-file", default: "cgate.lock", description: "filename for the lock to ensure one instance of C-Gate only", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "instance.lock-timeout", default: "20", description: "stale timeout for instance lock file, in seconds", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "lighting.auto-phantom-groups", default: "yes", description: "Automatically create phantom groups when lighting commands received from the network", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "lighting.learn-update", default: "no", description: "Allow the Lighting Application to perform database updates from Learn mode", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "load-change-port", default: "20025", description: "TCPIP port to use for load change port", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "load-change.buffer-size", default: "500", description: "Maximum number of lines in the load change event buffer", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "local-flow-control", default: "no", description: "Perform flow control in the server rather than the serial port", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "macro-path", default: "macros", description: "Path to directory where macro files are stored", scope: ConfigScope::Global, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "memory-report", default: "no", description: "Write memory reports along with heartbeat", scope: ConfigScope::Global, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.application-connect", default: "yes", description: "Model application connect and forwarding for bridges", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.auto-phantom-bridge", default: "yes", description: "Automatically create phantom bridge units and networks when messages are received", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.bridge.mmi-failure-ceiling", default: "10", description: "Max number of failed MMIs in a row before aborting net check_unravel on a bridged network", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "network.bridge.mmi-fallback-delay", default: "1000", description: "Delay after failed bridge installation MMI when performing net check_unravel (milliseconds)", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "network.error.commands-failed", default: "3", description: "Number of times commands should fail before the network is deemed to be in error", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.error.units-failed", default: "3", description: "Number of units to fail during sync before the network is deemed to be in error", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.error.units-failed-hysteresis", default: "0", description: "Number of units to recover during sync before the network is deemed OK again", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.pci.poll-interval", default: "60", description: "Interval to poll gateway to check the connection", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.retries", default: "2", description: "Number of times commands are retried before the command is deemed to have failed", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.retries.pci-check", default: "1", description: "PCI Checking begins at this number of retries", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "network.simultaneous-identifies", default: "5", description: "Simultaneous Identify command being sent out during network scan (must be 1 to 5)", scope: ConfigScope::Network, effective: "closeopen", listed: false, obsolete: false },
    ConfigParameter { name: "network.source", default: "db", description: "The default source of networks definitions.  Valid values are db or file", scope: ConfigScope::Project, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "network.state-interval", default: "0", description: "Interval (seconds) between network status events being sent for all networks", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "networks-file", default: "networks.txt", description: "The base name of the networks file, which will be prefixedby the project name to make the network filename ", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "patchset.file", default: "patchset.zip", description: "name of the file containing patch sets", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "pci-flow-control", default: "yes", description: "Enable XON/XOFF flow control by the PCI", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "pci.local-sal", default: "yes", description: "Send Application-Connect compatible messages via this PCI", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "pp.spec-base-directory", default: "unitspec/", description: "Base directory for unit specifications", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "prerelease.custom-version", default: "", description: "Produce a custom version string (prerelease only)", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "prerelease.use-api-file", default: "no", description: "Load api versions from api.txt in the config directory (prerelease only)", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "project.default", default: "", description: "Name of the default project", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "project.default.archive-dir", default: "Projects/archived/", description: "Directory where archived projects are stored", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "project.default.dir", default: "Projects/", description: "Default directory holding project files", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "project.start", default: "", description: "Space-separated list of projects to start on server startup", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "reopen-delay", default: "15000", description: "Delay time in milliseconds between attempted re-opens of a network", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "report-new-objects", default: "no", description: "Sends events indicating when new units are located on the network", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "response-delay", default: "5500", description: "Time in milliseconds to wait for a response before errors or resending", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "scene-base", default: "scene", description: "Path to scene files (relative to server base directory)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "secure.bind-address", default: "", description: "hostname or ip address of local interfaces to bind secure interfaces to", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "secure.client-auth", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.enable", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.key-password", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.keystore-dir", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.keystore-file", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.keystore-password", default: "", description: "", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: true },
    ConfigParameter { name: "secure.port-base", default: "20123", description: "Base port number for SSL secured ports", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "serial.fixbaud", default: "yes", description: "Serial network connection will attempt to fix buad rate if no response", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "serial.plugin-id", default: "jserialcomm", description: "Name of the serial port plugin library to use", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-file", default: "event9.sil", description: "The file to send the SmartInspect messages to", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-file-max", default: "100MB", description: "The maximum size (if any) to use in SmartInspect file mode", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-file-rotate", default: "none", description: "The rotation (if any) to use in SmartInspect file mode", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-mode", default: "none", description: "SmartInspect mode", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-tcp-host", default: "localhost", description: "The host to send messages to in SmartInspect tcp mode", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "smartinspect-tcp-port", default: "4228", description: "The port to send messages to in SmartInspect tcp mode", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "speed-write", default: "yes", description: "Enable fast writing of on/off/ramp commands with instant returns", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "startup-delay", default: "0", description: "(DEPRECATED) Delay (in seconds) before opening a network", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sweep-timeout", default: "2000", description: "Time in milliseconds between executions of the queue sweeper", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync-fast-pci", default: "yes", description: "Operate PCI in a synchronous mode (wait for response before sending)", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync-time", default: "3600", description: "Time in seconds between the beginnings of successive sync operations", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.app-stage.psync", default: "yes", description: "If yes, performs a final psync of all units", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.gateway-pool-size", default: "3", description: "Maximum number of concurrent background syncs per local gateway", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "sync.global-pool-size", default: "25", description: "Maximum number of concurrent background syncs", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "sync.padding.enabled", default: "yes", description: "Whether sync padding is enabled.", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.padding.maximum", default: "300", description: "The maximum padding distance between networks, in seconds.", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.padding.minimum", default: "5", description: "The minimum padding distance between networks, in seconds.", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.padding.sync-time-factor", default: "0.75", description: "A factor (0.1 to 1.0) applied to the project's sync-time to determine the overall padding period.", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.sync-free.periods", default: "", description: "Periods during which to avoid performing background syncs.", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.areaaddress", default: "5", description: "Sync level for a unit's AreaAddress parameter", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.currentsenselevels", default: "5", description: "Sync level for a unit's CurrentSenseLevels parameter.", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.patchversion", default: "5", description: "Sync level for a unit's PatchVersion parameter", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.physicaloutputlevels", default: "5", description: "Sync level for a unit's PhysicalOutputLevels parameter.", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.project", default: "5", description: "Sync level for a unit's Project parameter", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.targetlevels", default: "5", description: "Sync level for a unit's TargetLevels parameter.", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "sync.unit-parameter.unitsummary", default: "5", description: "Sync level for a unit's UnitSummary parameter.", scope: ConfigScope::Global, effective: "restart", listed: false, obsolete: false },
    ConfigParameter { name: "tag-autosave", default: "no", description: "If project (tag) database is updated by learn mode, then automatically save the database to disk", scope: ConfigScope::Global, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "tag-name-output", default: "no", description: "Show tag names in any output from the server", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "tag-use-zip", default: "no", description: "Store tag databases as zip files", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "tag-validate-db", default: "yes", description: "Perform XML validation on tag databases", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "tagname-prefix", default: "yes", description: "Require prefix before tag names in address paths", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "transform.base", default: "transform/", description: "base directory for xslt transforms", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "unit-auto-delete", default: "no", description: "Units are automatically deleted from the server if they are not found on the network", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "unit-auto-update-db", default: "no", description: "Units parameters are automatically updated to the project database", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "unit.template.default.dir", default: "Assets/Device Template Files/", description: "Default directory holding device template files", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "unitcatalog.directory", default: "unitspec", description: "Directory where the unit catalog is stored (relative to server home directory)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "unitcatalog.filename", default: "cbusunits.xml", description: "Name of the unit catalog file", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "unravel.readdress-bridge", default: "yes", description: "During an unravel, automatically readdress the bridge to match the near side network", scope: ConfigScope::Network, effective: "immediate", listed: true, obsolete: false },
    ConfigParameter { name: "use-1.0-addressing", default: "no", description: "Use C-Gate 1.0-style addresses in any output from the server", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "use-cgroups", default: "no", description: "Use C-Groups", scope: ConfigScope::Project, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "use-config-change-port", default: "yes", description: "Enable the config change port operation", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "use-event-file", default: "yes", description: "Save events to a file (filename specified in event-filename)", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "use-load-change-port", default: "yes", description: "Start the load change port", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "use-queue-sweeper", default: "yes", description: "Run the queue sweeper to remove stale commands", scope: ConfigScope::Network, effective: "closeopen", listed: true, obsolete: false },
    ConfigParameter { name: "use-scenes", default: "no", description: "Enable CGate server scenes", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
    ConfigParameter { name: "use-tags", default: "yes", description: "Use tag databases", scope: ConfigScope::Global, effective: "restart", listed: true, obsolete: false },
];

pub(crate) fn parameter(name: &str) -> Option<&'static ConfigParameter> {
    CONFIG_PARAMETERS
        .binary_search_by_key(&name, |parameter| parameter.name)
        .ok()
        .map(|index| &CONFIG_PARAMETERS[index])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_catalog_is_sorted_and_has_pinned_counts() {
        assert!(CONFIG_PARAMETERS
            .windows(2)
            .all(|pair| pair[0].name < pair[1].name));
        assert_eq!(CONFIG_PARAMETERS.len(), 148);
        assert_eq!(
            CONFIG_PARAMETERS
                .iter()
                .filter(|entry| entry.listed)
                .count(),
            122
        );
        assert_eq!(
            CONFIG_PARAMETERS
                .iter()
                .filter(|entry| entry.obsolete)
                .count(),
            6
        );
        assert_eq!(parameter("sync-time").unwrap().scope, ConfigScope::Network);
        assert!(parameter("SYNC-TIME").is_none());
    }

    #[test]
    fn native_catalog_matches_retained_oracle_fixture_field_for_field() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/fixtures/native_cgate_config.json"
        ))
        .expect("retained native CONFIG evidence must remain valid JSON");
        let parameters = fixture["parameters"]
            .as_array()
            .expect("fixture parameters must be an array");
        assert_eq!(parameters.len(), CONFIG_PARAMETERS.len());
        for (actual, retained) in CONFIG_PARAMETERS.iter().zip(parameters) {
            assert_eq!(retained["name"], actual.name, "name for {}", actual.name);
            assert_eq!(
                retained["listed"], actual.listed,
                "listed flag for {}",
                actual.name
            );
            assert_eq!(
                retained["obsolete"], actual.obsolete,
                "obsolete flag for {}",
                actual.name
            );
            // Native INFO deliberately withholds all metadata for obsolete
            // registrations, so the fixture can only pin their name/flags.
            if !actual.obsolete {
                assert_eq!(
                    retained["value"], actual.default,
                    "value for {}",
                    actual.name
                );
                assert_eq!(
                    retained["default"], actual.default,
                    "default for {}",
                    actual.name
                );
                assert_eq!(
                    retained["description"], actual.description,
                    "description for {}",
                    actual.name
                );
                assert_eq!(
                    retained["scope"],
                    actual.scope.as_str(),
                    "scope for {}",
                    actual.name
                );
                assert_eq!(
                    retained["effective"], actual.effective,
                    "effective for {}",
                    actual.name
                );
            }
        }
    }
}
