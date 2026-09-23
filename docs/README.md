# Documentation

The repository is a Rust-only C-Bus implementation. These documents describe the maintained code and its current behavior.

- [Status](status.md): completed functionality, known limits, and remaining validation.
- [Architecture](architecture.md): data flow and crate responsibilities.
- [Commands](commands.md): installed binaries and examples.
- [C-Gate](cgate.md): command coverage, state model, wire behavior, and limits.
- [Protocol](protocol.md): packets, PCI/CNI transport, MQTT, and project files.
- [Configuration](configuration.md): `cmqttd`, TLS, Docker, and project labels.
- [Testing](testing.md): local checks, test data, CI, and adding coverage.

AI agents should start with the repository's [C-Bus CLI skill](../.agents/skills/cbus-cli/SKILL.md). Its reference set provides command selection, system context, C-Gate wire behavior, and repeatable operating and validation workflows. [AGENTS.md](../AGENTS.md) contains repository-wide agent guidance.
