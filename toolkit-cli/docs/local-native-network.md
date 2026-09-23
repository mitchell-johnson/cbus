# Local network oracle

The research network runner can start its own original C-Gate 3.4.0 build 2001
process and connect it only to its own PCI simulator:

```sh
export CBUS_CGATE_JAVA=/path/to/owned/jdk11/bin/java
export CBUS_LOCAL_CGATE_VENDOR=/path/to/original/cgate/app
PYTHONPATH=src:. python research/verify_network.py \
  --backend local --duration 10 --output-dir research/runtime/my-network-run
```

The default backend remains Docker unless `CBUS_NATIVE_SERVICE_BACKEND=local`
or `--backend local` is supplied. The local path always starts a fresh service
through [LocalCGate](local-native-oracle.md); it does not adopt an existing
process, project or endpoint. The simulator and six native listeners bind to
127.0.0.1. The runner creates a unique project, opens only its simulator network,
records original replies and wire bytes, then closes/deletes the project and
terminates the owned native process. The Docker path now also checks the
existing service's explicit disposable-oracle label before using it.

[Acceptance](../research/fixtures/local-native-network-acceptance.json) records
two tests passing on Python 3.13.14 and 3.10.20 with identical source hashes.
The native test discovers the three declared fixture units, verifies the healthy
network state, changes simulated programming bytes from `38ff` to `39ff`, reads
them from the active peer and a new server loaded from disk, then restores
`38ff`. All six listeners and completed service cleanup are checked. The other
test verifies that invalid requests perform no service launch or inspection.

The first test attempt used a three-second observation window and did not reach
the accepted result. The final ten-second observation window matches the
successful standalone pilot. Those failures remain in the research history.

This evidence covers a synthetic network and the PCI programming-memory
transport. It does not establish a physical write, firmware checksum behavior,
complete scanner equivalence or native PP SAVE on the eDLT. The pre-existing
`--fixture key4` research path retains its separate incomplete checksum status;
it was not part of this two-test acceptance.
