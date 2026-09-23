# Original thermostat CreateLevels pilot — prepared, not executed

Root requested a bounded original-instruction pilot before any implementation. This directory is external and task-owned. No original instructions, Windows jobs, C-Gate requests, registry actions, UI handlers or hardware calls have run. Only source reads, literal case generation and Python AST parsing have occurred.

The proposed release token is `root-reviewed-thermostat-levels-pilot-v1`; the driver refuses to launch without it. Parent review/approval is still pending. The first proposed invocation uses the supported local3.13 interpreter and a fresh direct child output directory, under the OS network-denial sandbox. A separate process receives the exact prearchived12-case JSON and probe source. Its interpreter, Unicorn/Capstone native libraries and every package Python source file are archived and hashed before launch; original EXE/MAP/source report hashes are pinned and rechecked afterward. Inputs are descriptor-read with nonblocking regular-file and size checks. The driver never retries an original process, uses file-backed output and preserves the first failure over cleanup/reporting errors.

## Exact methods and fixture boundary

The full mapped original x86 PE is read/execute only. Every executed original instruction must match predecoded bytes in a finite method allowlist. No PE entrypoint, initializer, import or general call is admitted. The key original ranges are:

- CreateLevels01130944..01130b09, including normal finally-return paths.
- FindLevelByAddress00f2742c..00f275f8, including original default label creation, save and ProjectSave request.
- LevelToZones00fda610..00fda706, for1..31 only.
- Project BeginSaveLock00f2d370..00f2d382, EndSaveLock00f2d384..00f2d3f5, StorageSave00f2dac8..00f2db28.
- Original LevelManager.Add/GetItem wrappers, address getter/cached integer getter, address setter and Level.SetValue.

The exact original receiver/unit/group/network identities are represented by separately owned fixture objects. Object constructors, collection callbacks, attribute variant setters, Unicode-string/variant RTL, the single `%s %d` Format operation, chain getters and bottom storage writer are **providers**, not claimed original constructor/database execution. Original Add retains its manager assignment, original setters invoke the owned attribute callback, and the original Find loop selects by the retained ordered level collection. Existing level object IDs and values remain explicit.

The project object's actual `+0xc8` save-lock count and `+0xcd` pending flag are modified by original instructions. The virtual project save slot targets actual ProjectStorageSave. Its filter provider is restricted to the observed literal single `ProjectSave` input and returns true; the actual deferral, decrement, pending flush and pending-clear control flow execute in the original methods. The level-save and bottom storage providers record state snapshots and may deny one planned call. A denial stops emulation at that provider boundary: **no original Delphi exception dispatch/unwind or user-facing error manager is emulated or claimed**. In particular a denied final flush can leave pending=true after EndSaveLock has decremented the count to0.

The object/heap/stack/SEH fixtures are bounded and all original writes must fall inside those owned regions. Events/provider callbacks are capped at100,000 per case, and the final report at32MiB. Normal returns require exact ESP restoration and the original SEH word0. Child actual loaded Python/native library paths and hashes are recorded before/after and associated against the driver archive. Each action has a3-second emulation and5-million-instruction cap; the full probe has a60-second observed bound and75-second process wait. These are harness bounds, not product limits.

## Twelve prewritten cases

1. Standalone LevelToZones for each integer1..31.
2. Empty group, Enable:31 new levels.
3. Empty group, Disable:31 new levels.
4. Empty group, Overrd:31 new levels.
5. Existing31 levels with distinct retained labels and nonmatching values: no replacement.
6. Existing odd-address levels, Overrd: only missing even addresses created.
7. Enable→Disable→Overrd against the same retained group: first-created Enable labels remain.
8. Initial lock2: CreateLevels preserves the outer lock and defers storage; two separately invoked original EndSaveLock calls then flush.
9. Initial pending=true with all31 existing: normal final EndSaveLock flushes that prior request even though no level was created.
10. Initial lock1 without an outer release: final lock1/pending=true, no bottom storage call.
11. Denied first bottom storage call at final flush: all31 levels have been retagged/saved, lock0/pending=true retained; original unwind unexecuted.
12. Denied third level-save callback: first level fully retagged; second has original default label/value; lock1/pending=true retained; original unwind unexecuted.

Case1 compares independently composed literal `Zone:`/`Zones:` strings, with comma-separated `unsw,1,2,3,4` membership. The three action labels are exact original literals `Enable`, `Disable`, `Overrd`; final labels use `Sched ` + action + space + zone text. For each newly created level, the trace must show the default `Level N`/ValueN save before the final scheduling-label save. ProjectSave requests happen once per default-created level, again after a changed CreateLevels action, and once more when a pending request is flushed by the original EndSaveLock. All scalar/collection final expectations are written into cases.json before execution.

## Deliberate limits

This first pilot calls CreateLevels with an explicitly selected owned group. It does not execute CreateRemoteScheduleLevels selection/unused checks, scheduling flag handlers, cursor/delay/UI logic, original service factories or whole-application startup. It does not establish EnableControl application203 creation semantics or native database OID/Value initialization. Parent's separately owned backend probe may corroborate those later. Existing duplicate-address levels, arbitrary actions/Unicode formatting, invalid lock states and original exception unwind remain outside this12-case proposal.

No production or shared CLI file has changed. After review, successful original observations can motivate a separate native corroboration and public API proposal; this prepared harness is not acceptance evidence.
