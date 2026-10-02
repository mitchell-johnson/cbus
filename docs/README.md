# Documentation

The repository contains the Python Toolkit CLI and a Rust workspace for MQTT bridging, protocols, and testing. These documents describe how the components fit together.

- [Toolkit CLI guide](../toolkit-cli/README.md): installation, project editing, commissioning, and detailed command examples.
- [Toolkit feature status](../toolkit-cli/docs/implementation-status.md): completed functions, device profiles, acceptance evidence, and outstanding parity work.
- [eDLT selector callbacks](../toolkit-cli/docs/edlt-scene-selector-control.md): complete ordered choice views and explicit retained application, trigger, action and dynamic-label bindings.
- [eDLT selector database limits](../toolkit-cli/docs/edlt-scene-selector-metadata.md): actual inventories, parent Add ordering, creation timeline refusals and separate save boundaries.
- [Functional parity register](../toolkit-cli/docs/parity-register.md): versioned source accounting, obligation/evidence schema, validation rules and evidence-derived completion semantics.
- [Toolkit executable surface](../toolkit-cli/docs/toolkit-executable-surface.json): sanitized Toolkit 1.18.0 form, control and event inventory with pinned EXE/MAP provenance.
- [Implementation review and path to 100%](parity-review-and-roadmap.md): independent review, all 40 ledger areas, 59 tracked work items, the first delivery batch and explicit gates to 100% acceptance.
- [Technical findings and evidence index — 30 September 2026](technical-findings-2026-09-30.md): published and queued work, source-recovery corrections, canonical domain contracts, test evidence and remaining acceptance gaps.
- [Integrated Toolkit controls batch](../toolkit-cli/docs/feature-batch-2026-09-30-toolkit-controls.md): conversion, wireless, DLT, thermostat and documentor functions, firmware codec admission, source/wheel evidence and historical receipt corrections.
- [IOPE, templates and firmware diagnostics](../toolkit-cli/docs/feature-batch-2026-10-01-iope-templates-recovery.md): controller components, local template stages, lifecycle error projection and focused acceptance.
- [Routed commissioning and documentors](../toolkit-cli/docs/feature-batch-2026-10-01-routed-commissioning-documentors.md): Rust routed apply/verify, independently validated offline reconciliation and bounded Bytecraft/SceneModify reports.
- [Native database conversion and PP persistence](../toolkit-cli/docs/feature-batch-2026-10-01-conversion-pp.md): 30 original conversion results per Rust server, independent scalar/PP namespaces, schema-ordered saves and LOAD advisories.

- [Status](status.md): completed functionality, known limits, and remaining validation.
- [Architecture](architecture.md): data flow and crate responsibilities.
- [Commands](commands.md): installed binaries and examples.
- [C-Gate](cgate.md): command coverage, state model, wire behavior, and limits.
- [Protocol](protocol.md): packets, PCI/CNI transport, MQTT, and project files.
- [Configuration](configuration.md): `cmqttd`, TLS, Docker, and project labels.
- [Testing](testing.md): local checks, test data, CI, and adding coverage.

AI agents should start with the repository's [C-Bus CLI skill](../.agents/skills/cbus-cli/SKILL.md). Its reference set provides command selection, system context, C-Gate wire behavior, and repeatable operating and validation workflows. [AGENTS.md](../AGENTS.md) contains repository-wide agent guidance.
