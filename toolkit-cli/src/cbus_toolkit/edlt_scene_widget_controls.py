"""Owner-issued SceneWidget explicit bindings and button callbacks.

Choice rows come from the actual ordered parent scene model. Reset requests
and CurrencyManager position expressions are journaled; no host selection or
implicit SceneCycle read is synthesized from them.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
from weakref import WeakKeyDictionary, ref

from .edlt import EdltError, _field
from .edlt_scene_name_control import normalize_events, run_scene_name_control
from .edlt_scene_names import assign_name, checked_names, load_names, save_names, scene_name
from .edlt_scene_names import FIXED_SUGGESTION_NAMES
from .edlt_scene_widget_properties import (LABEL_CHOICES, MACRO_CHOICES, STATUS_CHOICES,
    VARIANT_CHOICES, SceneWidgetProperties, add_cycle_scene, delete_cycle_scene,
    move_cycle_scene, read_scene_cycle, set_cycle_row, set_cycle_variant,
    set_display_type, set_index, set_macro, set_scene_item)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise EdltError("Scene widget binding requires Unicode JSON facts") from error


def _digest(value):
    return sha256(_json(value)).hexdigest()


def _int(value, name, high=8):
    if type(value) is not int or not 0 <= value <= high:
        raise EdltError(f"Scene control {name} must be an integer in 0..{high}")
    return value


def _choice(row, extra=()):
    if set(row) != {"event", "index", "identity", "value", *extra}:
        raise EdltError("Scene control choice requires exact ordinal/identity/value")
    _int(row["index"], "choice ordinal", 7)
    if type(row["identity"]) is not str or not row["identity"]:
        raise EdltError("Scene choice needs a nonempty identity")
    return dict(row)


def normalize_controls(controls):
    if not isinstance(controls, (list, tuple)) or not 1 <= len(controls) <= 512:
        raise EdltError("scene_controls require 1..512 explicit ordered events")
    result = []
    for row in controls:
        if not isinstance(row, Mapping):
            raise EdltError("Scene controls require event records")
        kind = row.get("event")
        if kind in ("get-view", "set-widget", "get-cycle", "get-can-add", "get-can-remove", "cycle-add", "cycle-delete", "cycle-delete-key", "cycle-data-error") and set(row) == {"event"}:
            item = dict(row)
        elif kind == "cycle-dirty" and set(row) == {"event", "dirty"} and type(row["dirty"]) is bool:
            item = dict(row)
        elif kind in ("type-selected", "variant-selected"):
            item = _choice(row, ("target",))
            if row["target"] not in ("label", "status") or type(row["value"]) is not int:
                raise EdltError("Scene label/status choice target or value is invalid")
        elif kind in ("scene-selected", "macro-selected"):
            item = _choice(row)
            if ((kind == "scene-selected" and (type(row["value"]) is not int or not 0 <= row["value"] <= 7))
                    or (kind == "macro-selected" and type(row["value"]) is not str)):
                raise EdltError("Scene property choice value has the wrong source type")
        elif kind == "cycle-row-selected":
            item = _choice(row, ("slot",)); _int(row["slot"], "cycle slot")
            _int(row["value"], "scene value", 7)
        elif kind == "cycle-current":
            if row.get("index") is None and set(row) == {"event", "index"}:
                item = dict(row)
            else:
                if set(row) != {"event", "index", "identity", "value"}:
                    raise EdltError("Current cycle row needs an exact observed row or null")
                _int(row["index"], "current cycle ordinal"); _int(row["value"], "current cycle value")
                if type(row["identity"]) is not str:
                    raise EdltError("Current cycle row needs its identity")
                item = dict(row)
        elif kind in ("cycle-move-up", "cycle-move-down"):
            if row.get("index") is None and set(row) == {"event", "index"}:
                item = dict(row)
            else:
                if set(row) != {"event", "index", "identity"}:
                    raise EdltError("Scene cycle current cell needs an observed ordinal/identity or null")
                _int(row["index"], "cell ordinal")
                if type(row["identity"]) is not str:
                    raise EdltError("Scene cycle cell needs its PPAttribute identity")
                item = dict(row)
        elif kind == "cycle-variant-checked" and set(row) == {"event", "radio", "checked"}:
            if row["radio"] not in ("cycle", "select") or type(row["checked"]) is not bool:
                raise EdltError("Scene cycle radio needs its source name and boolean Checked")
            item = dict(row)
        elif kind == "status-text" and set(row) == {"event", "events"}:
            item = {"event": kind, "events": normalize_events(row["events"])}
        else:
            raise EdltError("Unsupported SceneWidget control event")
        result.append(item)
    return tuple(result)


class _Seal:
    pass


_ISSUED = WeakKeyDictionary()


@dataclass(frozen=True)
class SceneWidgetBinding:
    operation_number: int
    source_sha256: str
    operation_sha256: str
    provider_sha256: str | None
    project_sha256: str | None
    retained_names_sha256: str
    _rows_json: str = field(repr=False)
    _owner: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def _payload(self):
        return {"operation_number": self.operation_number, "source_sha256": self.source_sha256,
                "operation_sha256": self.operation_sha256, "provider_sha256": self.provider_sha256,
                "project_sha256": self.project_sha256, "retained_names_sha256": self.retained_names_sha256,
                "scene_rows": json.loads(self._rows_json)}

    def as_dict(self):
        return {"format": "cbus-edlt-scene-widget-binding-v1", **self._payload(),
                "snapshot_owned": True, "receipt_can_resume": False}


def _rows(scene_rows):
    if type(scene_rows) is not tuple or len(scene_rows) != 8:
        raise EdltError("SceneWidget requires a complete ordered tuple of actual scene rows")
    result = []
    for index, row in enumerate(scene_rows):
        if (not isinstance(row, Mapping) or set(row) != {"identity", "value", "name"}
                or row["identity"] != f"scene:{index + 1}" or type(row["value"]) is not int
                or row["value"] != index or type(row["name"]) is not str):
            raise EdltError("SceneWidget rows must preserve exact scene identity/value/name order")
        result.append(dict(row))
    _json(result)
    return result


def issue_scene_widget_binding(owner, *, operation_number, operation, source_values,
                               scene_rows, provider_sha256=None, project_sha256=None,
                               retained_names=None):
    if (owner is None or type(operation_number) is not int or operation_number < 1
            or not isinstance(operation, Mapping) or operation.get("op") != "scene"):
        raise EdltError("SceneWidget needs a non-null owning scene operation")
    normalize_controls(operation.get("scene_controls"))
    for digest in (provider_sha256, project_sha256):
        if digest is not None and (type(digest) is not str or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise EdltError("SceneWidget provider/project digest must name exact owning bytes")
    if retained_names is None:
        from .edlt_static_grid import current
        grid = current(source_values)
        retained_names = tuple(grid.names) if grid is not None else load_names(source_values)
    checked_names(retained_names)
    rows = _rows(scene_rows); seal = _Seal()
    binding = SceneWidgetBinding(operation_number, _digest(source_values), _digest(operation),
        provider_sha256, project_sha256, _digest(retained_names), _json(rows).decode("utf8"), owner, seal)
    _ISSUED[seal] = (owner, _digest(binding._payload()), ref(binding))
    return binding


def _check(binding, owner, values, operation, number):
    if type(binding) is not SceneWidgetBinding or owner is None or type(binding._seal) is not _Seal:
        raise EdltError("Scene controls require an owner-issued typed binding")
    issued = _ISSUED.get(binding._seal)
    try:
        payload_hash = _digest(binding._payload())
    except (TypeError, ValueError, UnicodeError) as error:
        raise EdltError("SceneWidget binding differs from its issued payload") from error
    if (issued is None or issued[0] is not owner or binding._owner is not owner or issued[2]() is not binding
            or issued[1] != payload_hash or binding.operation_number != number
            or binding.source_sha256 != _digest(values) or binding.operation_sha256 != _digest(operation)):
        raise EdltError("SceneWidget binding differs from its exact issuer/source/history")
    return _rows(tuple(json.loads(binding._rows_json)))


def _fixed(choices, prefix):
    return [{"identity": f"{prefix}:{value}", "value": value, "name": name} for name, value in choices]


def _member(event, rows):
    index = event["index"]
    if index >= len(rows) or event["identity"] != rows[index]["identity"] or event["value"] != rows[index]["value"]:
        raise EdltError("Scene control selection does not match the current exact ordinal/identity/value")
    return rows[index]


def project_scene_widget_controls(owner, binding, *, operation_number, operation, values,
                                  record, common):
    events = normalize_controls(operation["scene_controls"])
    scenes = _check(binding, owner, values, operation, operation_number)
    state = SceneWidgetProperties(record)
    page, position = operation.get("page"), operation.get("position")
    if type(page) is not int or type(position) is not int or not 1 <= page <= 4 or not 1 <= position <= 5:
        raise EdltError("SceneWidget owning page/position is invalid")
    widget = 6 + (page - 1) * 4 + position - 1
    if widget > 21 or bytes(values[_field(widget, i)][0] for i in range(32)) != record:
        raise EdltError("Scene controls require the exact post-ordinary-widget PP record")
    from .edlt_static_grid import current, adopt_retained_names
    grid = current(values)
    names = list(grid.names if grid is not None else load_names(values))
    if binding.retained_names_sha256 != _digest(tuple(names)):
        raise EdltError("SceneWidget retained Names differ from the owning full cache")
    projected = dict(values); journal = []; views = []; allocations = []
    cycle_rows = None; current_slot = None; text_state = None

    def install(new):
        nonlocal state
        state = new
        for offset, value in enumerate(state.record):
            projected[_field(widget, offset)] = (value,)

    def record_action(index, event, action, **facts):
        journal.append({"event_index": index, "event": event, "action": action, **facts})

    def read_cycle(index, event):
        nonlocal cycle_rows
        result = read_scene_cycle(state); install(result.state)
        cycle_rows = result.as_dict()["rows"]
        record_action(index, event, "ReadSceneCycle", result=result.as_dict())
        return result

    def observed_cycle(event, *, value=False):
        if cycle_rows is None:
            raise EdltError("Scene cycle row identity needs an earlier explicit SceneCycle read")
        index = event["index"]
        if index >= len(cycle_rows) or event["identity"] != cycle_rows[index]["identity"]:
            raise EdltError("Scene cycle row is not in the explicitly observed binding list")
        row = cycle_rows[index]
        if value and event["value"] != state.record[13 + row["slot"]]:
            raise EdltError("Scene cycle current value differs from its actual PPAttribute")
        return row

    for index, event in enumerate(events):
        kind = event["event"]
        if kind == "get-view":
            view = {**state.as_dict(), "scenes_available": bool(scenes), "scene_choices": scenes,
                    "label_types": _fixed(LABEL_CHOICES, "label-type"),
                    "status_types": _fixed(STATUS_CHOICES, "status-type"),
                    "label_variants": _fixed(VARIANT_CHOICES, "label-variant"),
                    "status_variants": _fixed(VARIANT_CHOICES, "status-variant")}
            views.append(view); record_action(index, kind, "ReadNonmutatingView", view=view)
        elif kind == "set-widget":
            # Explicit managed SetUpDataSource saves/restores these properties.
            text_state = None
            record_action(index, kind, "SetUpDataSource", saved_label_variant=state.index("label"),
                saved_status_variant=state.index("status"), saved_status_index=state.index("status"),
                saved_status_text=scene_name(tuple(names), state.index("status")),
                restored_status_index=state.index("status"),
                binding_requests=["ClearSceneSelectedValueBindings", "BaseSetUpDataSource",
                    "BindSceneItemOnPropertyChanged", "BindSingleVisibilityNever", "BindScenesAvailableNever",
                    "SnapshotVariantsAndStatusText", "SetSceneDataSource", "RestoreVariantSelectedValues",
                    "BindScenesNameValueTwice", "ResetScenes1False", "ResetScenesFalse", "ResetStatusVariantsTrue",
                    "RestoreStatusValueIndex", "RestoreStatusText"], implicit_callbacks_inferred=False)
        elif kind in ("get-cycle", "get-can-add", "get-can-remove"):
            result = read_cycle(index, kind)
            if kind != "get-cycle":
                answer = len(result.slots) < 9 if kind == "get-can-add" else bool(result.slots)
                record_action(index, kind, "ReadCanAddScene" if kind == "get-can-add" else "ReadCanRemoveScene", value=answer)
        elif kind == "type-selected":
            choices = _fixed(LABEL_CHOICES if event["target"] == "label" else STATUS_CHOICES,
                             event["target"] + "-type")
            _member(event, choices)
            result = set_display_type(state, target=event["target"], value=event["value"])
            install(result.state); record_action(index, kind, "WriteDisplayType", result=result.as_dict())
        elif kind == "variant-selected":
            _member(event, _fixed(VARIANT_CHOICES, event["target"] + "-variant"))
            enabled = state.display_type(event["target"]) in ((1, 2) if event["target"] == "label" else (6, 7))
            if not enabled:
                raise EdltError("Scene variant selection requires its currently visible dynamic control")
            result = set_index(state, target=event["target"], value=event["value"])
            install(result.state); record_action(index, kind, "WriteSelectedVariant", result=result.as_dict())
        elif kind == "scene-selected":
            _member(event, scenes)
            if not state.as_dict()["single_selection_editable"]:
                raise EdltError("Single SceneItem selection is not visible in the current cycle mode")
            result = set_scene_item(state, event["value"]); install(result.state)
            record_action(index, kind, "WriteSceneItem", result=result.as_dict())
        elif kind == "macro-selected":
            _member(event, _fixed(MACRO_CHOICES, "scene-macro"))
            result = set_macro(state, event["value"]); install(result.state)
            record_action(index, kind, "WriteDualButtonMacrofunction", result=result.as_dict())
        elif kind == "cycle-variant-checked":
            if not state.as_dict()["cycle_selection_editable"]:
                raise EdltError("Scene cycle radio requires the currently visible cycle mode")
            result = set_cycle_variant(state, radio=event["radio"], checked=event["checked"])
            install(result.state); record_action(index, kind, "WriteCheckedBinding", result=result.as_dict())
        elif kind == "cycle-current":
            current_slot = None if event["index"] is None else observed_cycle(event, value=True)["slot"]
            record_action(index, kind, "ObserveBindingCurrent", slot=current_slot)
        elif kind == "cycle-row-selected":
            _member(event, scenes)
            if cycle_rows is None or event["slot"] not in [r["slot"] for r in cycle_rows]:
                raise EdltError("Cycle cell needs an explicitly observed active PPAttribute row")
            install(set_cycle_row(state, slot=event["slot"], value=event["value"]))
            record_action(index, kind, "WriteCycleCellValueAsInt", slot=event["slot"], value=event["value"])
        elif kind == "cycle-add":
            new, inserted = add_cycle_scene(state); install(new)
            record_action(index, kind, "AddSceneItem", inserted_slot=inserted,
                source_requests=["Position=List.Count", "ResetCurrentItem", "ResetCycleBindingsFalse",
                                 "Position=List.Count", "ResetSceneBindingsFalse"],
                automatic_position_or_cycle_read_inferred=False)
        elif kind in ("cycle-delete", "cycle-delete-key"):
            new, getter = delete_cycle_scene(state, current_slot=current_slot); install(new)
            if getter is not None:
                # IndexOf obtains the same mutable SceneCycle list through its
                # getter. Its PPAttribute objects survive the following shifts.
                cycle_rows = getter.as_dict()["rows"]
            record_action(index, kind, "DeleteSceneItem", current_slot=current_slot,
                getter=None if getter is None else getter.as_dict(),
                source_requests=[] if getter is None else ["ResetCycleBindingsFalse", "ResetSceneBindingsFalse"])
            if kind == "cycle-delete-key":
                record_action(index, kind, "SetKeyHandled", value=True, key_code=46)
        elif kind == "cycle-dirty":
            record_action(index, kind, "CommitEditRequest" if event["dirty"] else "NoCommitEditRequest",
                          error_context=512 if event["dirty"] else None,
                          implicit_cell_write_inferred=False)
        elif kind == "cycle-data-error":
            record_action(index, kind, "SetDataErrorCancel", value=False)
        elif kind in ("cycle-move-up", "cycle-move-down"):
            if event["index"] is not None:
                observed_cycle({**event, "value": 0})
            new, moved = move_cycle_scene(state, index=event["index"],
                row_count=0 if cycle_rows is None else len(cycle_rows), direction="up" if kind.endswith("up") else "down")
            install(new); record_action(index, kind, "MoveSceneItem", target_position=moved,
                source_requests=[] if moved is None else ["ResetCurrentItem", "ResetCycleBindingsFalse",
                                                         f"Position={moved}", "ResetSceneBindingsFalse"])
        elif kind == "status-text":
            if state.display_type("status") != 5:
                raise EdltError("Scene status text requires its currently visible static text binding")

            def get_text():
                return scene_name(tuple(names), state.index("status"))

            def set_text(text):
                if text == get_text():
                    return {"changed": False, "index": state.index("status"), "static_allocator_invoked": False}
                # The old status reference remains reserved during allocation.
                used = common.static_references(projected)
                assignment = assign_name(tuple(names), state.index("status"), text,
                    values=projected, used_indices=lambda: tuple(used))
                names[:] = assignment.names; projected.update(assignment.changes)
                known[:] = names + list(FIXED_SUGGESTION_NAMES)
                result = set_index(state, target="status", value=assignment.index); install(result.state)
                allocations.append(assignment.as_dict())
                return {"static_assignment": assignment.as_dict(), "index_setter": result.as_dict()}

            # Membership is ordinal string equality; native culture ordering
            # and equal-name sort winners are not manufactured here.
            known = names + list(FIXED_SUGGESTION_NAMES)
            result = run_scene_name_control(event["events"], get_name=get_text, set_name=set_text,
                known_names=known, initial_state=text_state)
            text_state = result.state
            record_action(index, kind, "StaticStatusControl", result=result.as_dict())
    changes, setters = save_names(projected, tuple(names)); projected.update(changes)
    changed = {name: value for name, value in projected.items() if value != values[name]}
    pending = bool(text_state is not None and text_state.pending)
    # A later refused event cannot install a speculative earlier allocation.
    adopt_retained_names(projected, tuple(names))
    return state.record, changed, {"format": "cbus-edlt-scene-widget-controls-v1",
        "binding": binding.as_dict(), "journal": journal, "views": views, "state": state.as_dict(),
        "static_names": names, "static_setter_indices": list(setters), "allocations": allocations,
        "pending": pending, "automatic_framework_dispatch_inferred": False,
        "original_host_executed": False, "physical_device_verified": False}
