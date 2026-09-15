# Prepared CSV backend harness — no original/native execution

This is a byte-identical source snapshot of the reviewed candidate prepared under the external `backend-pilot-v1` directory. It preserves all earlier experiment snapshots. The scripts retain their original fixed research paths and ownership/admission guards; this directory is an archive, not an automatic execution entrypoint.

**Status:** 15 host-only guard tests passed on Python 3.13 and 3.10 with exact inputs archived before execution. Static preparation built 104 original instruction spans and recorded 54 actually loaded Python wrapper modules. It executed zero original instructions. The eight original cases, four native fixtures and replay of those four native captures have not run. No admission file is included or has been issued for this snapshot.

The [PLAN](PLAN.md) describes original QuickGet command/parser/Area observations, a fresh loopback-only C-Gate capture, and later network-denied replay of captured responses. Expected replay outcomes include one partial metadata-save stop; it must not be reported as a successful save. Original whole constructors, cold XML/cache loading and a complete native CSV export remain outside this prepared stage.

The current production CSV command still exports explicitly supplied captured-report JSON. Outstanding work is reviewed original/native admission and capture, followed by original cold-load/class/cache/application/group/association composition and full database-to-report verification. This snapshot adds no production API or CLI command.

The [local manifest](manifest.json) records every archived file's source path and SHA-256. [review-manifest-v2.json](review-manifest-v2.json) pins the final candidate and external host-guard/source-preparation reports. Vendor executables, native libraries/runtimes, input archives, raw execution output, Windows files, credentials and private user project data are excluded. The task ownership token and authorization names appearing in source are fixture labels, not credentials.

External evidence (not copied):

- `backend-pilot-v1/host-guards-v2/report.json`: SHA-256 `4bfd395faad1168115fd381766dd9022d8e14f35bbfb264956e89e60ff60663f`.
- `backend-pilot-v1/host-guards-v2/inputs.tar.gz`: exact pre-execution guard inputs; hash in the review manifest.
- `backend-pilot-v1/prepare-v3/report.json`: zero original instruction entries; hash in the review manifest.

The external base is `/Volumes/external/cbus-toolkit-research-20260915-document-database`. The new harness depends on the prior pinned cached-projection helper, already archived under [csv-projection](../csv-projection/), and on repository research helpers plus separately supplied original binaries/runtime. Source graph and registration findings remain under [csv-backend-proposal](../csv-backend-proposal/).
