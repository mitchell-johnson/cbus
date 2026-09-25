"""C-Gate event-stream filter/router spec (issue #11 box 10, bead cbus-pix).

Spec-first offline scaffold only. Pure filtering, routing, and
deduplication over caller-supplied event dicts; no sockets, no
sessions, no endpoints, no credentials.

Event shape (caller-supplied): ``{"application": int, "group": int,
"kind": str, ...}`` with extra keys preserved opaquely. Filter shape:
``{"application": int|None, "group": int|None, "kind": str|None}``
where ``None`` matches anything.

Honesty boundary: matching/routing/dedup are structural. Live stream
timing, ordering, reconnect replay, and server-side subscription
effects require owned-server acceptance and remain open; every
behavioral slot starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class RouteResult:
    routes: dict[str, tuple[int, ...]]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DedupResult:
    unique: tuple[dict[str, Any], ...]
    duplicate_indices: tuple[int, ...]
    behavioral_comparison: str = UNASSESSED


def _check_event(event: Any, pos: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise TypeError(f"event {pos} must be dict")
    for key in ("application", "group", "kind"):
        if key not in event:
            raise ValueError(f"event {pos} missing {key!r}")
    app, grp, kind = event["application"], event["group"], event["kind"]
    if isinstance(app, bool) or not isinstance(app, int):
        raise ValueError(f"event {pos} application must be int")
    if isinstance(grp, bool) or not isinstance(grp, int):
        raise ValueError(f"event {pos} group must be int")
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"event {pos} kind must be a non-empty str")
    return event


def _check_filter(flt: Any, pos: Any) -> dict[str, Any]:
    if not isinstance(flt, dict):
        raise TypeError(f"filter {pos} must be dict")
    out: dict[str, Any] = {}
    for key in ("application", "group", "kind"):
        val = flt.get(key, None)
        if val is None:
            out[key] = None
            continue
        if key == "kind":
            if not isinstance(val, str) or not val:
                raise ValueError(f"filter {pos} kind must be str or None")
        elif isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(f"filter {pos} {key} must be int or None")
        out[key] = val
    return out


def match_filter(event: Any, flt: Any) -> bool:
    """Return True when an event dict satisfies a filter dict."""
    ev = _check_event(event, "event")
    f = _check_filter(flt, "filter")
    for key in ("application", "group", "kind"):
        if f[key] is not None and ev[key] != f[key]:
            return False
    return True


def route_events(
    events: Any, filters: Any, extra: dict[str, Any] | None = None
) -> RouteResult:
    """Route events to named filters, returning matching indices.

    ``filters`` maps name (non-empty str) to filter dict. Output routes
    map each name to the tuple of event indices matching it (an event
    may match several). Names and index order are deterministic
    (insertion order of ``filters``, ascending indices).
    """
    if isinstance(events, (str, bytes)) or not hasattr(events, "__iter__"):
        raise TypeError("events must be a sequence of dicts")
    if not isinstance(filters, dict) or not filters:
        raise ValueError("filters must be a non-empty dict")
    evs = [_check_event(e, pos) for pos, e in enumerate(events)]
    flts: dict[str, dict[str, Any]] = {}
    for name, flt in filters.items():
        if not isinstance(name, str) or not name:
            raise ValueError("filter name must be a non-empty str")
        if name in flts:
            raise ValueError(f"duplicate filter name: {name!r}")
        flts[name] = _check_filter(flt, name)
    routes: dict[str, tuple[int, ...]] = {}
    for name, flt in flts.items():
        routes[name] = tuple(
            idx
            for idx, ev in enumerate(evs)
            if match_filter(ev, flt)
        )
    return RouteResult(
        routes=routes,
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )


def deduplicate(events: Any, key_fields: Any = ("application", "group", "kind")) -> DedupResult:
    """Drop exact duplicates first-wins on key fields (global, stable).

    ``key_fields`` is a non-empty sequence of field names; events
    missing a key field raise ``ValueError``. Returns unique events
    (deep-copied) plus the indices of dropped duplicates.
    """
    if isinstance(events, (str, bytes)) or not hasattr(events, "__iter__"):
        raise TypeError("events must be a sequence of dicts")
    if (
        isinstance(key_fields, (str, bytes))
        or not hasattr(key_fields, "__iter__")
        or not list(key_fields)
    ):
        raise ValueError("key_fields must be a non-empty field sequence")
    fields = list(key_fields)
    for f in fields:
        if not isinstance(f, str) or not f:
            raise ValueError("key field names must be non-empty strs")
    seen: dict[tuple, int] = {}
    unique: list[dict[str, Any]] = []
    dups: list[int] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise TypeError(f"event {idx} must be dict")
        try:
            key = tuple(ev[f] for f in fields)
        except KeyError as exc:
            raise ValueError(f"event {idx} missing {exc}") from exc
        if key in seen:
            dups.append(idx)
        else:
            seen[key] = idx
            unique.append(copy.deepcopy(ev))
    return DedupResult(unique=tuple(unique), duplicate_indices=tuple(dups))
