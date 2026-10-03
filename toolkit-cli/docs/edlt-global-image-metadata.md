# Image-aware eDLT Global Programming

Global Programming can now derive its ordinary source lifecycle from one exact
native project snapshot and explicit image providers. This profile admits
**KEYGL5 / 5055EDL firmware 5.5.00 with all 874 stored PP parameters**. It prepares
the source once, then copies the existing selected categories to independently
checked destinations. The manual `--metadata` workflow remains available.

## Offline preparation

```sh
cbus-toolkit edlt --spec-dir decoded-specs global-plan \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --project-images-export images.json --project-images-sha256 SHA256 \
  --category key-settings --category colour
```

`project.xml` must contain one complete native `Installation/Project` document.
The selected unit must have an exact identity, complete stored PP and the
admitted profile. The source parameter order comes from its XML PP rows. A
positional PP file is optional on this automatic path; if supplied, every value
must match the selected snapshot. `--parameter-order` cannot reorder this
source. Automatic metadata cannot be combined with `--factory-context`.

The source uses the network's current default Language and its actual
applications, groups, scene levels and dynamic tags. Required applications
must already exist. The projection creates no database objects. Consumed scene
Level Address and Value must agree within the admitted source alias profile.
The existing lifecycle handles missing group facts according to its retained
rules; they are not silently replaced by caller image Booleans.

## Native preparation and application

```sh
cbus-toolkit cgate --host SERVER edlt-project-images PROJECT --output images.json

cbus-toolkit cgate --host SERVER edlt-global \
  --spec-dir decoded-specs --auto-metadata \
  --source-database //PROJECT/254/p/20 \
  --destination //PROJECT/253/p/21 --destination //PROJECT/252/p/22 \
  --project-images-export images.json --project-images-sha256 SHA256 \
  --exclusive-project --category key-settings --category colour --dry-run
```

Use the image export's reported SHA-256 in place of `SHA256`. Keep project
snapshots, exports and decoded specifications private. See
[the image export guide](edlt-label-controls-images.md) for the supported byte
formats and virtual FILE repository profile.

`--auto-metadata` requires an exact `--source-database` path. Preparation obtains
one full-project `DBGETXML` snapshot and runs one source lifecycle load and
terminal preparation. The source is excluded from destinations. Select 1..64
distinct existing targets in the same project, including targets on other
networks. Every project network must already be closed and synchronization
idle. `--exclusive-project` is the caller's ownership declaration; it does not
prove server-wide exclusivity.

Dry-run reads the source and destination preconditions without saving a target
or creating a backup. Remove `--dry-run` to apply. Application retains the
existing new backup project, per-target PP save, project save, close/load and
fresh verification sequence. `--backup-project NAME` can choose a new backup
name. A unit requiring initial materialization is refused rather than
initialized implicitly.

## Image facts and source lifecycle

Project image facts come from a complete `cbus-edlt-project-images-v1` export
whose exact bytes match the supplied SHA-256 and project. Matching follows the
retained ordered, case-sensitive first match. FONT uses the TagValue prefix
before its first comma; TEXT and other non-ICON types can also match project
images. The selected Language controls which tags are consumed. An explicitly
complete empty export can establish no matches; a missing or failed export
cannot establish absence for consumed nonempty text/font facts.

Consumed ICON facts require the decoded DLTP provider:

```sh
cbus-toolkit edlt --spec-dir decoded-specs global-plan \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --toolkit-dltp-dir toolkit-directory --toolkit-dltp-sha256 INDEX_SHA256 \
  --toolkit-dltp-decode --category general
```

Supply both provider pairs when the source consumes both kinds of image facts.
The decoder has the bounded BMP profile described in the image export guide.
SHA binding identifies the consumed input; it does not prove an authentic
native directory, GDI rendering or device image contents.

The source follows the retained ordinary `AfterLoad` and `BeforeSave` model
phases, including widget, scene and MRA normalization and source CRCs. Its
issued context records the exact original XML, raw PP, ordered parameters,
Language, derived metadata and original provider identities. Changed, replaced
or stale contexts/providers refuse admission. Diagnostic JSON exports cannot
resume or authorize application.

## Categories and destination preservation

The existing four categories remain unchanged: key-settings has 7 fields,
standby 14, colour 18 and general 9. Their 16 possible masks include the empty
mask. Every selected field is written even when unchanged. The payload retains
the source attribute order, includes source OverallCRC and ends with literal
zero GlobalParameterCRC. The empty mask still writes those two CRC parameters.

Each destination keeps its own unselected PP, all 64 static rows, widget/scene
state, Language, labels, identities and metadata. No destination lifecycle is
loaded. No images or labels are transferred, no source or target Language is
changed, and no factory/template initialization is inferred. The destination
keeps its own WidgetsCRC, StaticTextCRC and ScenesCheckSum. A copied source
OverallCRC does **not** establish a valid full mixed destination CRC or physical
firmware behavior.

Native plans bind a separate preservation baseline for each target. They also
compare the complete project graph, allowing only the selected destination PP
Value attributes to change. This parsed XML comparison retains element order,
attributes, comments and text leaves. It ignores whitespace-only text around
child elements, including indentation and tails, and does not interpret
`xml:space`. It is not arbitrary XML byte equality or a general vendor XML
extension/repository admission claim. Exact original source XML and source Unit
XML checks are retained separately.

The batch is not atomic. A known staging failure discards its session before
save; a save that loses its terminal response is uncertain. Later destinations
stop, and no save, rollback or retry is replayed automatically. Inspect retained
evidence and the backup before deciding on recovery. See
[Global Programming](edlt-global-programming.md) for the underlying CRC,
verification and failure contract.

## Python API and evidence

```python
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming
from cbus_toolkit.native_global_programming import NativeEdltGlobalProgramming
from cbus_toolkit.edlt_scene_label_images import load_project_images

images = load_project_images(export_path, expected_sha256=export_sha256)
engine = EdltGlobalProgramming(spec)
source = engine.prepare_project_source(project_xml, "//PROJECT/254/p/20",
                                       project_images=images)
payload = engine.select(source, categories=("key-settings", "colour"))

manager = NativeEdltGlobalProgramming(client, spec)
source = manager.prepare_project_source("//PROJECT/254/p/20",
                                        project_images=images)
payload = manager.engine.select(source, categories=("key-settings", "colour"))
plan = manager.plan(payload, ("//PROJECT/253/p/21", "//PROJECT/252/p/22"),
                    source_database=source.image_context.unit_path,
                    exclusive_project=True)
```

`research/fixtures/edlt-global-image-source-annex.json` pins 19 managed spans,
13 decompiled declarations and 16 static checks without publishing vendor
instructions or source bodies. `edlt-global-image-vectors.json` independently
records complete source phases, all 16 payload masks and two divergent complete
target baselines. The dedicated pure and native fake-client tests cover image
lookup, provider/source authority, preservation, stale inputs and save loss.
Owned-server CLI acceptance is recorded separately by the batch release.
Historical fixtures remain unchanged. This annex adds source-backed software
coverage; it establishes no new original GUI, framework host or physical-device
acceptance and does not close full Toolkit parity.
