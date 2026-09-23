"""Read-only descriptions of C-Gate's server-wide project repositories.

REPOSITORY LIST ends with a 123 line, without an additional 200. Its current
flags may identify zero or several entries; neither case chooses a default.
No repository selector is exposed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .cgate import CGateResponse


_ENTRY = re.compile(r"123([- ])index=([1-9][0-9]{0,5}) type=([^\s=]+) path=(.*) current=(yes|no)")
_MAX_ENTRIES = 4096
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RepositoryDescriptor:
    index: int
    type: str
    path: str
    current: bool

    def __post_init__(self):
        if type(self.index) is not int or not 1 <= self.index <= _MAX_ENTRIES:
            raise ValueError("Repository index must be a positive bounded integer")
        if type(self.type) is not str or not self.type or any(c.isspace() or c == '=' for c in self.type):
            raise ValueError("Repository type must be one nonempty native token")
        if type(self.path) is not str or type(self.current) is not bool:
            raise ValueError("Repository path and current flag have invalid types")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.type + self.path):
            raise ValueError("Repository descriptor contains control characters")

    def as_dict(self):
        return {"index": self.index, "type": self.type, "path": self.path, "current": self.current}


@dataclass(frozen=True)
class RepositoryInventory:
    repositories: tuple[RepositoryDescriptor, ...]
    response: CGateResponse

    @property
    def current_indices(self) -> tuple[int, ...]:
        return tuple(item.index for item in self.repositories if item.current)

    @property
    def current_state(self) -> str:
        count = len(self.current_indices)
        return "unique" if count == 1 else "unknown" if count == 0 else "multiple"

    @property
    def current_index(self) -> int | None:
        indices = self.current_indices
        return indices[0] if len(indices) == 1 else None

    def as_dict(self):
        return {
            "format": "cbus-cgate-repositories-v1",
            "repositories": [item.as_dict() for item in self.repositories],
            "current_state": self.current_state,
            "current_indices": list(self.current_indices),
            "current_index": self.current_index,
            "read_only": True,
            "repository_changed": False,
            "selection_scope": "server",
            "native_response": {"code": self.response.code, "final": self.response.final,
                                "lines": list(self.response.lines)},
        }


def parse_repository_list(response: CGateResponse) -> RepositoryInventory:
    """Validate one complete native LIST reply, preserving paths verbatim.

    Only the final literal `` current=yes|no`` suffix is a flag delimiter.
    Spaces, equals signs and earlier flag-like text remain part of the path.
    Numbering and continuation markers must match the original ordered list.
    """
    if (type(response) is not CGateResponse or type(response.lines) is not tuple
            or not response.lines or len(response.lines) > _MAX_ENTRIES
            or any(type(line) is not str for line in response.lines)
            or type(response.status) is not int or type(response.final) is not str
            or response.final != response.lines[-1]):
        raise ValueError("Repository listing is not one complete native response")
    try:
        size = sum(len(line.encode("utf-8")) + 2 for line in response.lines)
    except UnicodeError:
        raise ValueError("Repository listing contains invalid Unicode") from None
    if size > _MAX_RESPONSE_BYTES or any(ord(c) < 32 or ord(c) == 127 for line in response.lines for c in line):
        raise ValueError("Repository listing exceeds its bounds or contains control characters")
    if response.code == 124 and response.lines == ("124 no repositories found",):
        return RepositoryInventory((), response)
    if response.code != 123:
        raise ValueError("Repository listing requires native 123 records or the exact empty 124 reply")
    entries = []
    for position, line in enumerate(response.lines, 1):
        match = _ENTRY.fullmatch(line)
        marker = ' ' if position == len(response.lines) else '-'
        if match is None or match[1] != marker or int(match[2]) != position:
            raise ValueError("Repository listing has invalid grammar, numbering or continuation markers")
        entries.append(RepositoryDescriptor(position, match[3], match[4], match[5] == 'yes'))
    return RepositoryInventory(tuple(entries), response)


class NativeRepositories:
    """Issue a single read-only LIST using an already connected CGateClient."""

    def __init__(self, client):
        self.client = client

    def list(self) -> RepositoryInventory:
        return parse_repository_list(self.client.command("REPOSITORY LIST"))
