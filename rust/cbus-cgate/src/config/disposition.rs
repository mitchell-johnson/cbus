//! Per-setting runtime disposition for the native C-Gate 3.4 CONFIG catalogue.
//!
//! Every one of the 148 catalogued names has exactly one row. `native` names
//! where the pinned 3.4.0.2001 daemon reads the value: class and line in the
//! case-sensitive CFR 0.152 decompilation of `cgate.jar` (SHA-256
//! `3ec48394...d630`), plus any owned loopback capture. `pl.java` is the
//! catalogue registration itself, so a row citing only that line has no
//! native reader. For `live` and `restart` rows, `cmqttd` names the code that
//! applies the value and `tests` names the tests that demonstrate the effect;
//! the unit tests below check both against the source.

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum ConfigDisposition {
    /// SET/LOAD changes the running service for new work immediately.
    Live,
    /// The value is sampled when cmqttd starts.
    Restart,
    /// The value is applied when a network is closed and reopened.
    CloseOpen,
    /// Native effect belongs to host/process integration that the cmqttd
    /// deployment (container, CLI options, log collector) owns instead.
    External,
    /// No native effect exists for cmqttd to reproduce: the native reader is
    /// absent or the feature is outside cmqttd's scope.
    NotApplicable,
    /// cmqttd deliberately does not let CONFIG steer this effect.
    SecureDeviation,
    /// Native has an effect that cmqttd does not apply yet.
    Unimplemented,
}

impl ConfigDisposition {
    pub(crate) const ALL: [Self; 7] = [
        Self::Live,
        Self::Restart,
        Self::CloseOpen,
        Self::External,
        Self::NotApplicable,
        Self::SecureDeviation,
        Self::Unimplemented,
    ];

    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Live => "live",
            Self::Restart => "restart",
            Self::CloseOpen => "closeopen",
            Self::External => "external",
            Self::NotApplicable => "not_applicable",
            Self::SecureDeviation => "secure_deviation",
            Self::Unimplemented => "unimplemented",
        }
    }
}

/// Evidence fields are rendered into the generated documentation table and
/// checked by tests; `CMQTT CAPABILITIES` reports only the disposition.
#[derive(Clone, Copy, Debug)]
#[cfg_attr(not(test), allow(dead_code))]
pub(crate) struct ConfigDispositionEntry {
    pub(crate) name: &'static str,
    pub(crate) disposition: ConfigDisposition,
    pub(crate) native: &'static str,
    pub(crate) cmqttd: &'static str,
    pub(crate) tests: &'static [&'static str],
    pub(crate) note: &'static str,
}

use ConfigDisposition::{External, Live, NotApplicable, Restart, SecureDeviation, Unimplemented};

const fn row(
    name: &'static str,
    disposition: ConfigDisposition,
    native: &'static str,
    note: &'static str,
) -> ConfigDispositionEntry {
    ConfigDispositionEntry {
        name,
        disposition,
        native,
        cmqttd: "",
        tests: &[],
        note,
    }
}

const fn effect(
    name: &'static str,
    disposition: ConfigDisposition,
    native: &'static str,
    cmqttd: &'static str,
    tests: &'static [&'static str],
    note: &'static str,
) -> ConfigDispositionEntry {
    ConfigDispositionEntry {
        name,
        disposition,
        native,
        cmqttd,
        tests,
        note,
    }
}

const NET: &str = "Native network driver setting; cmqttd's PCI/CNI transport uses its own fixed policy and does not read it.";
const EVENT_FILE: &str = "Native host event-log file; cmqttd logs through tracing to stdout/stderr for the container runtime.";
const SMARTINSPECT: &str =
    "SmartInspect diagnostic sink of the vendor JVM service; not part of the cmqttd deployment.";
const SYNC: &str = "Native background unit sync scheduler; cmqttd has no background sync process.";
const UNITSPEC: &str = "cmqttd reads unit specifications and catalogues from the --cgate-unitspec deployment directory; CONFIG does not relocate it.";
const NO_READER: &str = "Catalogue registration only; the pinned native jar never reads it, so stored-only behavior matches native.";
const OBSOLETE_SECURE: &str = "Obsolete registration with no native reader (native hard-codes key/cis.ks in Ba.java); cmqttd TLS material comes from --cgate-tls-* options.";
const EVENT_TRANSPORT: &[&str] = &["cmqttd/tests/system_cgate_event_transport.rs::config_event_server_and_outbound_socket_stream_without_interrupting_mqtt"];

pub(crate) const CONFIG_DISPOSITIONS: &[ConfigDispositionEntry] = &[
    effect("accept-connections-from", Live, "oG.java:53 (read per accepted connection); native_cgate_config_connection_admission.json; native_cgate_config_hostname_tls_admission.json", "service.rs Service::accepts_command_peer", &["cmqttd/tests/system_cgate_config_admission.rs::config_admission_changes_new_sessions_and_preserves_mqtt_pci"], "Native INFO says restart, but captured SET/LOAD effects on new command connections are immediate."),
    effect("access-control-file", Live, "u.java:107,359 (read per default ACCESS LOAD/SAVE); native_cgate_access.json", "service.rs access_snapshot_name", &["cbus-cgate/src/service/tests.rs::config_access_control_file_selects_default_access_snapshot_immediately"], "The name selects a bounded cmqttd-json snapshot, never a host file under config-path."),
    row("allow-fast-start", Unimplemented, "CBusBaseNetwork.java:555", "Database fast-start on network open is not modeled."),
    row("allow-recall-write", Unimplemented, "nx.java:376 (CI SET); nN.java:25 (STORE), read per command", "cmqttd does not implement the native STORE and CI commands this gates."),
    row("allow-v3-pci", Unimplemented, "CBusPCILocal.java:29,38; CBus2PCILocalable.java:23,29", NET),
    row("application.catalog.directory", External, "R.java:42", UNITSPEC),
    row("application.catalog.filename", External, "R.java:40", UNITSPEC),
    row("application.model-change-events", Unimplemented, "bq.java:75", "Sync-process model-update events are not emitted."),
    row("application.show-command-failure", Unimplemented, "CBusBaseApplication.java:249", "SAL command-failure event suppression is not modeled."),
    row("auto-reopen", Unimplemented, "CBusBaseNetwork.java:525", NET),
    row("cbus-application", Unimplemented, "CBusBaseNetwork.java:477", NET),
    row("cbus-tx-delay", Unimplemented, "CBusBaseNetwork.java:517", NET),
    row("cbus.tx-cache", Unimplemented, "cl.java:50", NET),
    row("cbus.tx-compress", Unimplemented, "cl.java:42", NET),
    row("ccp.display-oids", Unimplemented, "BA.java:79", "cmqttd has no config change port."),
    row("ccp.display-state", Unimplemented, "BA.java:80", "cmqttd has no config change port."),
    row("cgate-name", NotApplicable, "pl.java:78 (catalogue only)", NO_READER),
    row("cgroups-file", Unimplemented, "CGate.java:188; CGateManager.java:251,280", "C-Groups are not modeled."),
    row("clock.master", Unimplemented, "CBusClockApplication.java:80,451", "Clock master operation is not modeled."),
    row("clock.mastermode", Unimplemented, "CBusClockApplication.java:65 (application-prefixed read)", "Clock master operation is not modeled."),
    row("clock.update-interval", Unimplemented, "CBusClockApplication.java:541 (application-prefixed read)", "Clock master operation is not modeled."),
    row("command-local-address", External, "Ba.java:37-38", "cmqttd binds its command listener from the --cgate-bind deployment option."),
    row("command-port", External, "oG.java:38", "cmqttd binds its command listener from the --cgate-bind deployment option."),
    row("command.encoding", Unimplemented, "BB.java:21; BF.java:32; BM.java:32", "cmqttd always uses UTF-8, the native default."),
    effect("command.show-responses", Restart, "Response.java:688; native_cgate_config_command_show_responses.json", "service.rs Service::new command_show_responses", &["cbus-cgate/src/service/tests.rs::config_command_show_responses_uses_native_multiline_events_and_restart_boundary"], ""),
    effect("command.show-time", Restart, "Response.java:687; native_cgate_config_command_show_time.json", "service.rs Service::new command_show_time", &["cbus-cgate/src/service/tests.rs::config_command_show_time_activates_only_after_restart_and_preserves_running_state"], ""),
    row("comms-debug", Unimplemented, "CBusBaseNetwork.java:538", "Per-network comms debug log under the project directory is not written."),
    row("config-change-port", Unimplemented, "CGateManager.java:233,497", "cmqttd has no config change port."),
    row("config-path", SecureDeviation, "bW.java:113,405; BJ.java:245,251; DV.java:21; kR.java:69", "CONFIG, snapshots and ACCESS persist in the deployment-selected cmqttd-json state file; CONFIG cannot redirect host file I/O."),
    row("console.enable-commands", External, "CGate.java:128; CGateManager.java:167,264", "cmqttd runs as a daemon without an interactive console."),
    row("dali.catalogue.dir.sys", Unimplemented, "gk.java:69-70", "DALI CATALOG serves durable cmqttd-json entries; catalogue directories are not loaded."),
    row("dali.catalogue.dir.user", Unimplemented, "gk.java:78-79", "DALI CATALOG serves durable cmqttd-json entries; catalogue directories are not loaded."),
    row("default-tag-db", NotApplicable, "pl.java:87 (catalogue only; deprecated)", NO_READER),
    row("enable-xml-to-sql-background-job", NotApplicable, "CGateManager.java:517", "Native XML-to-SQLite migration job; cmqttd's repository is cmqttd-json."),
    row("enable.save-state", Unimplemented, "CBusEnableControlApplication.java:420", "Enable Control state is not saved to or restored from disk."),
    row("event-file.asynchronous", External, "SysEvent.java:288,405", EVENT_FILE),
    row("event-file.buffer-size", External, "BC.java:73; CGateManager.java:417", EVENT_FILE),
    row("event-file.event-level", External, "SysEvent.java:293,410", EVENT_FILE),
    row("event-file.keep-days", External, "SysEvent.java:346,463", EVENT_FILE),
    row("event-file.split", External, "BC.java:21; CGateManager.java:365", EVENT_FILE),
    row("event-file.split-count", External, "BC.java:35; CGateManager.java:379", EVENT_FILE),
    row("event-file.split-size", External, "BC.java:28; SysEvent.java:340,457; CGateManager.java:372", EVENT_FILE),
    row("event-file.startup-dump", External, "CGate.java:195; CGateManager.java:258", EVENT_FILE),
    row("event-filename", External, "CGateManager.java:132,362,618", EVENT_FILE),
    effect("event-host", Restart, "CGateManager.java:135,428; native_cgate_config_event_transport.json", "service.rs Service::new startup_event_transport", EVENT_TRANSPORT, ""),
    effect("event-millis", Restart, "SysEvent.java:394; native_cgate_config_event_millis.json", "service.rs Service::new event_millis", &["cbus-cgate/src/service/tests.rs::config_event_millis_follows_native_restart_precision_for_traces_and_broadcast", "cmqttd/tests/system_cgate_config.rs::event_millis_changes_only_after_daemon_restart"], ""),
    effect("event-mode", Restart, "CGateManager.java:134,427; native_cgate_config_event_transport.json", "service.rs Service::new startup_event_transport", EVENT_TRANSPORT, ""),
    effect("event-port", Restart, "CGateManager.java:137,430; native_cgate_config_event_transport.json", "service.rs Service::new startup_event_transport", EVENT_TRANSPORT, ""),
    row("event-printer", External, "CGateManager.java:150,454", "Host event printer device; not part of the cmqttd deployment."),
    row("event-sink.buffer-size", Unimplemented, "BG.java:46", "Per-sink native event buffer sizing is not applied."),
    effect(
        "event.display-oids",
        Restart,
        "SysEvent.java:110,395; native_cgate_config_event_display_oids.json",
        "service.rs Service::new event_display_oids; event_oid_column",
        &["cbus-cgate/src/service/tests.rs::config_event_display_oids_drops_oid_column_only_after_restart"],
        "Startup `no` removes the `-` OID column after the event source on command-socket and event-server delivery; `sys` rows have none.",
    ),
    row("file.base", SecureDeviation, "pM.java:50,91 (read per FILE command)", "FILE uses a sandboxed virtual filesystem in cmqttd-json; CONFIG cannot re-root it onto the host."),
    effect("global-event-level", Restart, "CGate.java:112; native_cgate_config_global_event_level.json", "service.rs Service::new global_event_level", &["cbus-cgate/src/service/tests.rs::config_global_event_level_samples_native_boundaries_only_at_startup", "cmqttd/tests/system_cgate_config.rs::config_global_event_level_filters_only_cgate_delivery_after_restart"], "Native INFO says immediate, but captured delivery is sampled at startup."),
    effect("heartbeat-time", Restart, "CGateManager.java:156,467; native_cgate_config_heartbeat.json", "service.rs Service::new heartbeat_interval; Service::start_heartbeat", &["cbus-cgate/src/service/tests.rs::config_heartbeat_time_is_snapshot_at_start_and_bounded", "cmqttd/tests/system_cgate_config.rs::heartbeat_time_uses_native_envelope_and_changes_only_on_restart"], "Values outside 1..86400 seconds disable the timer."),
    row("hide-project-names", Unimplemented, "ObjectSignature.java:173", "Address rendering option is not applied."),
    row("instance.lock-file", External, "q.java:19,45; s.java:15", "Single-instance ownership belongs to the container or service manager."),
    row("instance.lock-timeout", External, "q.java:22,48", "Single-instance ownership belongs to the container or service manager."),
    row("lighting.auto-phantom-groups", Unimplemented, "CBusLightingApplication.java:774", "Observed groups are cached unconditionally; the switch is not applied."),
    row("lighting.learn-update", Unimplemented, "CBusLightingApplication.java:532 (application-prefixed read)", "Learn-mode database updates are not modeled."),
    row("load-change-port", Unimplemented, "CGateManager.java:220,482", "cmqttd has no load change port."),
    row("load-change.buffer-size", Unimplemented, "BL.java:15", "cmqttd has no load change port."),
    row("local-flow-control", Unimplemented, "CBusBaseNetwork.java:536", NET),
    row("macro-path", Unimplemented, "pc.java:47-48", "Native macro files are not supported."),
    row("memory-report", External, "BK.java:19", "JVM memory report written with heartbeats; cmqttd has no JVM."),
    row("network.application-connect", Unimplemented, "CBusBaseNetwork.java:556", NET),
    row("network.auto-phantom-bridge", Unimplemented, "CBusBaseNetwork.java:3532", NET),
    row("network.bridge.mmi-failure-ceiling", Unimplemented, "dk.java:42", "Bridge check_unravel MMI policy is fixed in cmqttd."),
    row("network.bridge.mmi-fallback-delay", Unimplemented, "dk.java:36", "Bridge check_unravel MMI policy is fixed in cmqttd."),
    row("network.error.commands-failed", Unimplemented, "CBusBaseNetwork.java:501", NET),
    row("network.error.units-failed", Unimplemented, "nb.java:91; bO.java:31", SYNC),
    row("network.error.units-failed-hysteresis", Unimplemented, "nb.java:99", SYNC),
    row("network.pci.poll-interval", Unimplemented, "CBusBaseNetwork.java:571", NET),
    row("network.retries", Unimplemented, "CBusBaseNetwork.java:493", NET),
    row("network.retries.pci-check", Unimplemented, "CBusBaseNetwork.java:509", NET),
    row("network.simultaneous-identifies", Unimplemented, "CBusBaseNetwork.java:558", NET),
    row("network.source", Unimplemented, "bW.java:352", "Project network definitions always come from the cmqttd-json model."),
    row("network.state-interval", Unimplemented, "qf.java:52,99; CBusBaseNetwork.java:4695 (level-3 704 event)", "Periodic network state events are not emitted."),
    row("networks-file", SecureDeviation, "Project.java:139", "NET SAVE/LOAD FILE snapshots live in cmqttd-json; no host networks file is opened."),
    row("patchset.file", NotApplicable, "me.java:103", "The proprietary patchset.zip is not shipped; cmqttd uses its own %P%/patchsets manifest."),
    row("pci-flow-control", Unimplemented, "CBusBaseNetwork.java:535; CBusPCILocal.java:30,39; CBus2PCILocalable.java:24,30", NET),
    row("pci.local-sal", Unimplemented, "CBus2PCILocalable.java:45; CBusLoraxPciUnit.java:75; CBusOEMDazzaUnit.java:77", NET),
    row("pp.spec-base-directory", External, "md.java:73; lY.java:37; me.java:107; pv.java:306; CBusNetworkUnraveller.java:1660", UNITSPEC),
    row("prerelease.custom-version", NotApplicable, "DX.java:29", "Native prerelease-build option only."),
    row("prerelease.use-api-file", NotApplicable, "DW.java:14 (gated by prerelease build)", "Native prerelease-build option only."),
    effect("project.default", Restart, "Bk.java:109,276; qf.java:49,96; native_cgate_config_project_default.json", "service.rs Service::new startup_project_default", &["cmqttd/tests/system_cgate_config.rs::project_default_selects_loaded_project_only_after_restart_without_interrupting_mqtt"], ""),
    row("project.default.archive-dir", SecureDeviation, "Ag.java:260; dD.java:623; AT.java:569; AS.java:196; Ah.java:35; native_cgate_project_archive.json", "Relative PROJECT ARCHIVE/RESTORE names resolve under the native default Projects/archived/ inside the sandboxed virtual FILE namespace; CONFIG cannot relocate it to a host directory. cmqttd:KEY tokens address cmqttd-json snapshots instead."),
    row("project.default.dir", Unimplemented, "dD.java:615; AT.java:561; Ah.java:31; ql.java:22,40,58; CBusBaseNetwork.java:542", "Schneider project-file repository directory is not used; projects live in cmqttd-json."),
    effect("project.start", Restart, "qf.java:50,97; native_cgate_config_project_start.json", "service.rs Service::new startup_projects", &["cbus-cgate/src/service/tests.rs::config_project_start_samples_durable_names_and_runtime_lifecycle_at_restart", "cmqttd/tests/system_cgate_config.rs::project_start_samples_valid_durable_names_at_restart_and_keeps_mqtt_live"], "Only projects already in the cmqttd-json repository can be started."),
    row("reopen-delay", Unimplemented, "CBusBaseNetwork.java:527", NET),
    row("report-new-objects", Unimplemented, "CBusBaseNetwork.java:524", "New-object events are not emitted."),
    row("response-delay", Unimplemented, "CBusBaseNetwork.java:485", NET),
    row("scene-base", Unimplemented, "AZ.java:25; CGateManager.java:335", "Server scene files are not supported."),
    row("secure.bind-address", SecureDeviation, "Ba.java:40-41", "cmqttd's TLS command listener uses --cgate-bind and operator-supplied --cgate-tls-* certificates, never a CONFIG-selected listener with the vendor keystore."),
    row("secure.client-auth", NotApplicable, "pl.java:139 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.enable", NotApplicable, "pl.java:134 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.key-password", NotApplicable, "pl.java:137 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.keystore-dir", NotApplicable, "pl.java:132 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.keystore-file", NotApplicable, "pl.java:133 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.keystore-password", NotApplicable, "pl.java:136 (catalogue only; obsolete)", OBSOLETE_SECURE),
    row("secure.port-base", SecureDeviation, "Ba.java:29-30", "cmqttd's TLS command listener uses --cgate-bind and operator-supplied --cgate-tls-* certificates, never a CONFIG-selected listener with the vendor keystore."),
    row("serial.fixbaud", Unimplemented, "CBusSerialNetwork.java:96", NET),
    row("serial.plugin-id", External, "lg.java:49", "Java serial plugin library selection; cmqttd has its own serial transport."),
    row("smartinspect-file", External, "Bc.java:38", SMARTINSPECT),
    row("smartinspect-file-max", External, "Bc.java:39", SMARTINSPECT),
    row("smartinspect-file-rotate", External, "Bc.java:40", SMARTINSPECT),
    row("smartinspect-mode", External, "Bc.java:18", SMARTINSPECT),
    row("smartinspect-tcp-host", External, "Bc.java:27", SMARTINSPECT),
    row("smartinspect-tcp-port", External, "Bc.java:22", SMARTINSPECT),
    row("speed-write", Unimplemented, "CBusBaseNetwork.java:534", NET),
    row("startup-delay", Unimplemented, "CBusBaseNetwork.java:469", NET),
    row("sweep-timeout", Unimplemented, "aZ.java:19", NET),
    row("sync-fast-pci", Unimplemented, "CBusBaseNetwork.java:537", NET),
    row("sync-time", Unimplemented, "Project.java:400; mY.java:176,247,303,408; CBusBaseNetwork.java:461", SYNC),
    row("sync.app-stage.psync", Unimplemented, "nb.java:333,588,754,798", SYNC),
    row("sync.gateway-pool-size", Unimplemented, "mW.java:57-58", SYNC),
    row("sync.global-pool-size", Unimplemented, "mW.java:50-51", SYNC),
    row("sync.padding.enabled", Unimplemented, "Project.java:405; mY.java:164,235,292,396", SYNC),
    row("sync.padding.maximum", Unimplemented, "Project.java:427; mY.java:192,263,319,424", SYNC),
    row("sync.padding.minimum", Unimplemented, "Project.java:422; mY.java:189,260,316,421", SYNC),
    row("sync.padding.sync-time-factor", Unimplemented, "Project.java:411; mY.java:179,250,306,411", SYNC),
    row("sync.sync-free.periods", Unimplemented, "bN.java:94; mY.java:149,220,381", SYNC),
    row("sync.unit-parameter.areaaddress", Unimplemented, "CBusBaseNetwork.java:597", SYNC),
    row("sync.unit-parameter.currentsenselevels", Unimplemented, "CBusBaseNetwork.java:613", SYNC),
    row("sync.unit-parameter.patchversion", Unimplemented, "CBusBaseNetwork.java:605", SYNC),
    row("sync.unit-parameter.physicaloutputlevels", Unimplemented, "CBusBaseNetwork.java:629", SYNC),
    row("sync.unit-parameter.project", Unimplemented, "CBusBaseNetwork.java:589", SYNC),
    row("sync.unit-parameter.targetlevels", Unimplemented, "CBusBaseNetwork.java:637", SYNC),
    row("sync.unit-parameter.unitsummary", Unimplemented, "CBusBaseNetwork.java:621", SYNC),
    row("tag-autosave", Unimplemented, "Dc.java:123", "Learn-mode tag database autosave is not modeled."),
    row("tag-name-output", Unimplemented, "ObjectSignature.java:175", "Address rendering option is not applied."),
    row("tag-use-zip", NotApplicable, "pl.java:85 (catalogue only)", "Catalogue registration only; the pinned native jar never reads it, and native_cgate_project_archive.json shows identical PROJECT ARCHIVE payloads for yes and no, so stored-only behavior matches native."),
    row("tag-validate-db", Unimplemented, "CI.java:79; Dt.java:228; pw.java:99; dg.java:124; Dh.java:119,221; Cz.java:55", "Tag-database XML schema validation switch is not applied."),
    row("tagname-prefix", Unimplemented, "CT.java:143", "Tag-name address prefix rule is not applied."),
    row("transform.base", SecureDeviation, "Dk.java:26-27", "TRANSFORM resolves inside the sandboxed virtual FILE namespace; CONFIG cannot expose a host directory."),
    row("unit-auto-delete", Unimplemented, "CBusUnit.java:325", "Automatic unit deletion after sync is not modeled."),
    row("unit-auto-update-db", Unimplemented, "nb.java:1158", SYNC),
    row("unit.template.default.dir", Unimplemented, "Dt.java:468-469", "Host device template directory is not used."),
    row("unitcatalog.directory", External, "CBusUnitSpecification.java:107", UNITSPEC),
    row("unitcatalog.filename", External, "CBusUnitSpecification.java:105", UNITSPEC),
    row("unravel.readdress-bridge", Unimplemented, "CBusBaseNetwork.java:665", "Unravel bridge readdress switch is not applied."),
    row("use-1.0-addressing", Unimplemented, "ObjectSignature.java:174", "Address rendering option is not applied."),
    row("use-cgroups", Unimplemented, "CGate.java:186; CGateManager.java:249,276", "C-Groups are not modeled."),
    row("use-config-change-port", Unimplemented, "CGateManager.java:230,494", "cmqttd has no config change port."),
    row("use-event-file", External, "SysEvent.java:280,401; CGateManager.java:130,359", EVENT_FILE),
    row("use-load-change-port", Unimplemented, "CGateManager.java:217,479", "cmqttd has no load change port."),
    row("use-queue-sweeper", Unimplemented, "CBusBaseNetwork.java:554", NET),
    row("use-scenes", Unimplemented, "CGate.java:191; CGateManager.java:254,331", "Server scene files are not supported."),
    row("use-tags", Unimplemented, "CGate.java:171; CGateManager.java:210,509", "Tag databases are always enabled."),
];

/// Names whose disposition is `disposition`, in catalogue order.
pub(crate) fn names_with(disposition: ConfigDisposition) -> Vec<&'static str> {
    CONFIG_DISPOSITIONS
        .iter()
        .filter(|entry| entry.disposition == disposition)
        .map(|entry| entry.name)
        .collect()
}

/// Render the generated Markdown table kept in `docs/cmqttd-cgate.md`.
#[cfg(test)]
pub(crate) fn markdown_table() -> String {
    let mut out = String::from(
        "| Setting | Disposition | Native reader (3.4.0.2001) | cmqttd effect and tests | Note |\n|---|---|---|---|---|\n",
    );
    for entry in CONFIG_DISPOSITIONS {
        let mut effect = entry.cmqttd.to_string();
        for test in entry.tests {
            if !effect.is_empty() {
                effect.push_str("; ");
            }
            effect.push_str(test);
        }
        let cells = [
            format!("`{}`", entry.name),
            entry.disposition.as_str().to_string(),
            entry.native.to_string(),
            effect,
            entry.note.to_string(),
        ];
        out.push_str("| ");
        out.push_str(
            &cells
                .iter()
                .map(|cell| cell.replace('|', "\\|"))
                .collect::<Vec<_>>()
                .join(" | "),
        );
        out.push_str(" |\n");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::CONFIG_PARAMETERS;
    use std::collections::BTreeSet;

    const TEST_SOURCES: &[(&str, &str)] = &[
        (
            "cbus-cgate/src/service/tests.rs",
            include_str!("../service/tests.rs"),
        ),
        (
            "cmqttd/tests/system_cgate_config.rs",
            include_str!("../../../cmqttd/tests/system_cgate_config.rs"),
        ),
        (
            "cmqttd/tests/system_cgate_config_admission.rs",
            include_str!("../../../cmqttd/tests/system_cgate_config_admission.rs"),
        ),
        (
            "cmqttd/tests/system_cgate_event_transport.rs",
            include_str!("../../../cmqttd/tests/system_cgate_event_transport.rs"),
        ),
    ];
    const SERVICE_SOURCE: &str = include_str!("../service.rs");
    const DOC: &str = include_str!("../../../../docs/cmqttd-cgate.md");
    const DOC_BEGIN: &str = "<!-- BEGIN GENERATED CONFIG DISPOSITIONS -->\n";
    const DOC_END: &str = "<!-- END GENERATED CONFIG DISPOSITIONS -->";

    #[test]
    fn config_dispositions_cover_every_catalogue_name_exactly_once() {
        assert_eq!(CONFIG_DISPOSITIONS.len(), 148);
        assert_eq!(CONFIG_DISPOSITIONS.len(), CONFIG_PARAMETERS.len());
        for (entry, parameter) in CONFIG_DISPOSITIONS.iter().zip(CONFIG_PARAMETERS) {
            assert_eq!(entry.name, parameter.name, "catalogue order");
        }
        let unique = CONFIG_DISPOSITIONS
            .iter()
            .map(|entry| entry.name)
            .collect::<BTreeSet<_>>();
        assert_eq!(unique.len(), 148);
        let total = ConfigDisposition::ALL
            .iter()
            .map(|disposition| names_with(*disposition).len())
            .sum::<usize>();
        assert_eq!(total, 148, "each row has exactly one disposition");
    }

    #[test]
    fn config_dispositions_carry_native_evidence_and_reasons() {
        for entry in CONFIG_DISPOSITIONS {
            assert!(!entry.native.trim().is_empty(), "{} native", entry.name);
            let catalogue_only = entry.native.contains("catalogue only");
            assert_eq!(
                catalogue_only,
                entry.native.starts_with("pl.java:"),
                "{} catalogue-only rows cite only the registration",
                entry.name
            );
            if catalogue_only {
                assert_eq!(entry.disposition, NotApplicable, "{}", entry.name);
            }
            match entry.disposition {
                Live | Restart => {
                    assert!(!entry.cmqttd.is_empty(), "{} cmqttd location", entry.name);
                    assert!(!entry.tests.is_empty(), "{} effect test", entry.name);
                }
                _ => {
                    assert!(entry.cmqttd.is_empty(), "{} claims no effect", entry.name);
                    assert!(entry.tests.is_empty(), "{} claims no effect", entry.name);
                    assert!(!entry.note.is_empty(), "{} needs a reason", entry.name);
                }
            }
        }
    }

    #[test]
    fn config_disposition_effect_claims_are_backed_by_code_and_existing_tests() {
        for entry in CONFIG_DISPOSITIONS
            .iter()
            .filter(|entry| matches!(entry.disposition, Live | Restart))
        {
            assert!(
                SERVICE_SOURCE.contains(&format!("config_parameter(\"{}\")", entry.name)),
                "{} is not read by service.rs",
                entry.name
            );
            for test in entry.tests {
                let (file, function) = test.split_once("::").expect("file::function");
                let (_, source) = TEST_SOURCES
                    .iter()
                    .find(|(path, _)| *path == file)
                    .unwrap_or_else(|| panic!("{test}: unknown test source"));
                assert!(
                    source.contains(&format!("async fn {function}("))
                        || source.contains(&format!("fn {function}(")),
                    "{test}: test function is missing"
                );
                assert!(
                    source.contains(entry.name),
                    "{test}: source never mentions {}",
                    entry.name
                );
            }
        }
    }

    #[test]
    fn config_disposition_doc_table_is_generated() {
        let expected = markdown_table();
        let start = DOC.find(DOC_BEGIN).expect("doc begin marker") + DOC_BEGIN.len();
        let end = DOC.find(DOC_END).expect("doc end marker");
        if std::env::var_os("CBUS_UPDATE_CONFIG_DISPOSITIONS").is_some() {
            let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../docs/cmqttd-cgate.md");
            let updated = format!("{}{expected}{}", &DOC[..start], &DOC[end..]);
            std::fs::write(path, updated).unwrap();
            return;
        }
        assert_eq!(
            &DOC[start..end],
            expected,
            "regenerate with CBUS_UPDATE_CONFIG_DISPOSITIONS=1 cargo test -p cbus-cgate config_disposition_doc"
        );
    }
}
