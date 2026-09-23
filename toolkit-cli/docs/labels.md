# Dynamic label commands

The typed label API and CLI implement the native `LIGHTING LABEL`, `TRIGGER LABEL`, `ENABLE LABEL`, `LIGHTING UNICODELABEL`, and `TRIGGER UNICODELABEL` command families. The label forms are ASCII text, UTF-8 Unicode, built-in icon, uploaded bitmap, language selection, and raw options/data. Each validates its fields before sending the command. C-Gate 3.4 has no `ENABLE UNICODELABEL` command; that combination raises an explicit error.

```sh
cbus-toolkit cgate label text //TEST/254/56 1 'Lounge' --variant 2
cbus-toolkit cgate label unicode //TEST/254/56 1 'Māori' --variant 1
cbus-toolkit cgate label icon //TEST/254/56 1 --icon 258 --variant 3
cbus-toolkit cgate label dynamic //TEST/254/56 1 01020408102040 --icon 65535 --width 8 --height 7 --vertical-offset 2
cbus-toolkit cgate label language //TEST/254/56 1 --language 3
cbus-toolkit cgate label --family trigger text //TEST/254/202 7 'Scene' --action-selector 9
cbus-toolkit cgate label --family enable text //TEST/254/203 9 'Enable' --action-selector 0
cbus-toolkit cgate label clear //TEST/254/56 1 --unicode --variant 1
cbus-toolkit cgate label clear //TEST/254/56 1 --variant 2
```

The application must exist on the selected network. Sending labels can communicate with devices; the CLI does not open networks implicitly. A successful native reply produces `queued: true, device_verified: false`. The acceptance capture proves why this distinction matters: C-Gate returned `200 OK` even when the independent interface initially rejected an unsupported SAL packet. No automatic retry is performed after an error.

`--language` and `--action-selector` are bytes in 0–255. An omitted action selector sends native `-`; variants are integers 0–3. ASCII labels are limited to 14 bytes and preserve spaces and punctuation by using the equivalent options-zero raw form. `text ''` and ASCII `clear` send the native NUL representation. Unicode strings are encoded as UTF-8 and always sent through native `RAW`, avoiding the server's platform-dependent text decoding. `unicode ''` and Unicode `clear` send an empty Unicode label. Native documentation specifies that an existing Unicode label takes precedence over an ASCII replacement until the Unicode label is cleared.

Current native bitmap grammar differs from the old command help's colon-separated rows. It accepts contiguous hexadecimal bytes with exactly `ceil(width × height / 8)` bytes, width 1–240, height 1–60, icon selector 0–65535, and vertical offset 0–255. The sender emits start, metadata, six-byte chunks and commit messages. The independent receiver rejects missing stages, overlong chunks and incomplete commits. It stores a new bitmap only after the complete transfer.

The Unicode sender splits data into 13-byte fragments, or 12 bytes with an action selector. UTF-8 characters may cross fragment boundaries and are decoded after reassembly. C-Gate's internal map overwrites a prior middle fragment beyond 18 fragments; the API rejects payloads exceeding 234 bytes without an action selector or 216 bytes with one. The native acceptance test verifies the full 234-byte boundary. Individual physical devices can impose smaller capacities; those limits and display rendering are not established by the synthetic fixture.

Python uses `NativeLabels(client, family="lighting")`. Methods `text`, `unicode`, `unicode_raw`, `raw`, `icon`, `dynamic`, and `set_language` take application and group first; optional fields use the CLI names with underscores. `raw(application, group, options, data)` accepts bytes, and `dynamic(application, group, icon, width, height, data)` accepts packed bitmap bytes. Pure `encode_label`, `encode_unicode_label`, and `encode_dynamic_icon` functions return SAL payloads without PCI/application framing. The simulator receiver is independently implemented and does not import these encoders.

Nineteen tests pass: nine typed API/encoding tests, nine independent receiver tests using literal native vectors, and one native-to-simulator acceptance test exercising twelve commands. The native test creates a unique project and its own temporary synthetic interface, verifies nine exact stored labels plus language selection, clears both text types, verifies reload from disk, and removes the project. It also verifies native rejection of ENABLE Unicode and obsolete colon-form bitmap input. The two CLI tests cover exact generated commands, queued semantics, and native error handling.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
  CBUS_LABEL_REPORT=research/runtime/labels-acceptance.json \
  .venv/bin/python -m unittest discover -s tests -p '*labels.py' -v
```

`CBUS_CGATE_SIMULATOR_HOST` overrides `host.docker.internal` when the disposable oracle uses another route to the test process. No existing physical network is adopted. The local report from C-Gate 3.4.0 build 2001 has SHA-256 `6f41621193e096e29c883a12866a4fab6e2c65ab0af4feb51fa1597d59fba526`. Its exact command responses, outgoing packets and final state remain in `research/runtime/labels-acceptance.json`.

This evidence establishes native outgoing encoding and synthetic payload persistence. It does not establish physical display rendering, label requests/annunciation, arbitrary raw-option semantics, all device capacities, physical flash behavior, scene recording/playback, or overall Toolkit parity.
