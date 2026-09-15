# Local native TLS and scene acceptance

The TLS and filesystem scene harnesses support an explicitly selected local
Java11 process. Docker remains their default. The local runner creates fresh
temporary state and verifies that all six listeners belong to its child process
and bind only to `127.0.0.1`. It never adopts an existing service or project.

The combined suite passed **35 tests with zero skips** on Python **3.13.14**
(14.466s) and **3.10.20** (14.637s), with identical, unchanged source hashes.
See [the compact acceptance record](../research/fixtures/local-native-services-acceptance.json).

TLS exercises eight cases with generated disposable certificates, including
verified command/project use and five certificate or hostname rejections.
Independent TLS-layer errors confirm that rejection came from authentication.
Each process and its generated keys were removed after testing.

Scene acceptance compiles the owned Java probe against the original C-Gate jar,
then compares the original parser and serializer with the Python scene format.
Playback, recording, an active ramp, a changed scene file and persisted levels
are checked against an independent loopback CNI simulator. The original named
`SCENE PLAY` and `SCENE RECORD` commands still return401; these are reported as
unsupported independently of the working Python scene workflow.

```sh
export CBUS_NATIVE_SERVICE_BACKEND=local
export CBUS_CGATE_JAVA=/absolute/path/to/your/jdk11/bin/java
export CBUS_LOCAL_CGATE_VENDOR=/absolute/path/to/toolkit-cli/research/vendor/cgate/app
export CBUS_NATIVE_TLS_TEST=1
export CBUS_SCENE_NATIVE=1
PYTHONPATH=src python -m unittest \
  tests.test_local_cgate tests.test_native_tls tests.test_scenes -v
```

TLS needs the research `cryptography` dependency and the selected runtime's
`keytool`. Scenes also need `javac`; the default is beside the selected Java
binary, or it can be explicitly supplied through `CBUS_CGATE_JAVAC`.
`lsof` verifies native listener ownership. These runs used the portable
Temurin11.0.32.1+1 JDK with archive hash recorded in the acceptance fixture;
nothing was installed globally.

`CBUS_NATIVE_TLS_REPORT`, `CBUS_SCENE_REPORT` and `CBUS_LOCAL_CGATE_REPORT`
select distinct JSON report paths. Local service ports are assigned to each
fresh process. The scene harness's fixed `--port` applies to its Docker backend.

This is focused native acceptance outside the previous frozen wheel checkpoint.
It does not establish real device behavior or complete Toolkit parity. The
[local process contract](local-native-oracle.md) describes cleanup failures and
the cases where the runner retains its work directory for inspection.

The separately accepted [local network runner](local-native-network.md) adds
original C-Gate discovery and independent simulator write/disk-restoration
checks. Its two tests pass on both Python versions; they are separate from
the 35-test TLS/scene/service checkpoint described above.
