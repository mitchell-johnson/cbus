# Native repository listing

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 repositories
```

This sends one read-only `REPOSITORY LIST` command. It lists the server's
repositories in their original order, preserving each index, type, path and
current flag. Existing C-Gate TLS and timeout options also apply.

`current_state` is `unique`, `unknown` or `multiple`. Only `unique` supplies a
`current_index`; the other states return `null` and preserve every reported
`current_indices` value. An empty native list is `unknown` with no entries. All
three states are successful observations; malformed replies, native rejection
and transport failure return a nonzero exit status.

Paths retain spaces, equals signs, Unicode, leading/trailing spaces and embedded
flag-like text. The parser recognizes only the last ` current=yes|no` suffix.
It validates original sequential numbering and continued/final response markers,
with bounds of 4,096 entries and 4 MiB of decoded UTF-8 response data. The output
also retains the complete native reply without command tags.

```python
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.repositories import NativeRepositories

with CGateClient("127.0.0.1", 20023) as client:
    observed = NativeRepositories(client).list()
    print(observed.current_state, observed.current_index)
    print(observed.as_dict())
```

The module exposes no selector. Original C-Gate repository selection affects a
server singleton even though its help calls it a session setting. An earlier
isolated native startup returned all current flags as `no`; this API preserves
that result rather than choosing the first repository. It does not imply that
another client cannot change selection after the observation.

Original bytecode and isolated native repair/listing evidence are recorded in
`research/runtime/project-repair-research/native-protocol-proposal.md` and
`native-acceptance.json`. They pin C-Gate 3.4.0 build 2001 and show `sqlite-file`,
`file` and `db` descriptors. Other nonempty native type tokens are preserved
without assuming that they support any project operation. The repository path
is descriptive data, not an instruction to open or modify that path.

Acceptance is pinned in `research/fixtures/repositories-acceptance.json`:
13 tests passed on each of Python 3.13.14 and 3.10.20, with no skips. Both runs
used a fresh original C-Gate child, verified the path containing spaces and an
equals sign, left its project directory empty, and confirmed process cleanup.
The 34 loaded package sources and six test/helper inputs matched across both
runs; their exact bytes are archived with the reports. These checks do not
establish repository selection, project repair or physical-device behavior.

## Project archives per repository

Native `PROJECT ARCHIVE` copies the current repository's project file, so the
archive payload depends on the repository type rather than the archive name.
The container follows the case-insensitive suffix: `.zip` holds one deflated
entry, `.gz` one GZIP member, and any other name raw bytes. Relative names land
under `Projects/archived/`. In the default `sqlite-file` repository every form
carries the private Schneider SQLite database (schema version 14), in a
`tagdb.db` entry for ZIP. Only the legacy `file` repository (`REPOSITORY USE 2`)
carries Installation XML, in a `tagdb.xml` entry. `CONFIG SET tag-use-zip yes`
leaves both the payload and the saved project unchanged, and `DBSAVE` returns
`441 Error writing tag database: null`. A `sqlite-file` repository refuses an XML
archive on `PROJECT RESTORE` with `Zip entry tagdb.db not found`; restore XML
archives into the `file` repository instead.

These facts come from one run of
`rust/cbus-cgate/research/native_project_archive_probe.py` against an owned
C-Gate 3.4.0.2001 child, recorded in
`rust/testdata/fixtures/native_cgate_project_archive.json`. The database and
schema text are not committed. `tests/test_native_cgate_project_interchange.py`
exchanges these archives with cmqttd in both directions and is part of the
native release gate.
