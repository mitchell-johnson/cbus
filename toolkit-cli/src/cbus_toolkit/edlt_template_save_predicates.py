"""Pure source projections of Save predicates, not original runtime execution.

Callers supply already resolved getter values. No model lookup, getter mutation,
dialog, culture-dependent parsing, or persistence occurs here.
"""

from dataclasses import dataclass
from typing import Literal, Sequence


@dataclass(frozen=True)
class SerialResult:
    outcome: Literal["accepted", "rejected", "unproven_parse"]
    last_four: str | None
    value: int | None


@dataclass(frozen=True)
class ResolvedScene:
    slot: int
    item_count: int
    name_index: int
    trigger: int
    action: int


@dataclass(frozen=True)
class KeyGroup:
    application: int
    address: int
    tag_name: str


@dataclass(frozen=True)
class SceneWarnings:
    valid: bool
    errors: tuple[str, ...]
    warning_ids: tuple[str, ...]
    skipped_scene_indices: tuple[int, ...]


def validate_serial_text(text: str) -> SerialResult:
    """Conservatively admit ASCII parsing of the final four UTF-16 units."""
    units = text.encode("utf-16-le", errors="surrogatepass")
    if len(units) < 8:
        return SerialResult("accepted", None, None)
    tail = units[-8:].decode("utf-16-le", errors="surrogatepass")
    if not all("0" <= char <= "9" for char in tail):
        return SerialResult("unproven_parse", tail, None)
    value = int(tail)
    return SerialResult("accepted" if value <= 4095 else "rejected", tail, value)


_SCENE_CLAUSES = (
    ("duplicate-trigger-action", "Multiple scenes have been assigned with identical Trigger Group and Action Selector combinations."),
    ("populated-missing-trigger-action", "One or more scenes have been populated with items but have not been assigned a Trigger Group and/or Action Selector."),
    ("populated-missing-name", "One or more scenes have been populated with items but have not been assigned a scene label."),
    ("duplicate-name", "Multiple scenes have been assigned identical scene labels."),
)


def validate_unit(
    primary_application: int,
    corridor_link: int,
    ordered_key_groups: Sequence[KeyGroup],
    scenes: Sequence[ResolvedScene],
) -> SceneWarnings:
    """Project corridor then scene checks using resolved, immutable facts.

    Skips refer to zero-based collection indices, rather than scene slot values.
    Scene pairs include empty scenes and action -1; action 255 is excluded.
    """
    errors: list[str] = []
    if corridor_link != 255:
        for group in ordered_key_groups:
            if group.address == corridor_link and group.application == primary_application:
                errors.append(
                    f'The selected Corridor Link Group "{group.tag_name}" is also being used in at least one key function. '
                    "To resolve this error, either change the Corridor Link Group or remove it's associated key functions."
                )
                break
    duplicate_trigger = duplicate_name = missing_trigger = missing_name = False
    skipped: list[int] = []
    for index, scene in enumerate(scenes):
        if missing_name and missing_trigger:
            skipped.append(index)
            continue
        if scene.item_count > 0:
            if scene.name_index == 255:
                missing_name = True
            if scene.trigger == 255 or scene.action < 0:
                missing_trigger = True
        for later in scenes[index + 1:]:
            if scene.name_index != 255 and scene.name_index == later.name_index:
                duplicate_name = True
            if (scene.trigger != 255 and scene.trigger == later.trigger
                    and scene.action != 255 and scene.action == later.action):
                duplicate_trigger = True
    flags = (duplicate_trigger, missing_trigger, missing_name, duplicate_name)
    warnings = tuple(identifier for (identifier, _), present in zip(_SCENE_CLAUSES, flags) if present)
    if warnings:
        errors.append("The following problems were detected with the scene configurations: " + "".join(
            "\n\n" + clause for (_, clause), present in zip(_SCENE_CLAUSES, flags) if present
        ))
    return SceneWarnings(not errors, tuple(errors), warnings, tuple(skipped))


@dataclass(frozen=True)
class SceneWidgetResult:
    outcome: Literal["checked", "skipped_null_name", "expected_index_exception"]
    label_inconsistent: bool = False
    status_inconsistent: bool = False


def check_scene_widget_variants(
    label_mode: str | None,
    status_mode: str | None,
    label_variant: int,
    status_variant: int,
    dynamic_variants: tuple[tuple[str | None, bool], ...],
    level_present: bool,
) -> SceneWidgetResult:
    """Project one resolved cycle entry; represent original bad-index exceptions.

    Modes are ``text``, ``icon``, or None. A present level always checks label
    Name first, including status-only configurations. Empty names are checked.
    """
    if label_mode not in (None, "text", "icon") or status_mode not in (None, "text", "icon"):
        raise ValueError("dynamic mode must be text, icon, or None")
    if label_mode is None and status_mode is None:
        return SceneWidgetResult("checked")
    if not level_present:
        return SceneWidgetResult("checked", label_mode is not None, status_mode is not None)
    if not 0 <= label_variant < len(dynamic_variants):
        return SceneWidgetResult("expected_index_exception")
    if dynamic_variants[label_variant][0] is None:
        return SceneWidgetResult("skipped_null_name")
    label_bad = False
    if label_mode is not None:
        image = dynamic_variants[label_variant][1]
        label_bad = image if label_mode == "text" else not image
    if status_mode is not None:
        if not 0 <= status_variant < len(dynamic_variants):
            return SceneWidgetResult("expected_index_exception", label_bad)
        image = dynamic_variants[status_variant][1]
        return SceneWidgetResult("checked", label_bad, image if status_mode == "text" else not image)
    return SceneWidgetResult("checked", label_bad)
