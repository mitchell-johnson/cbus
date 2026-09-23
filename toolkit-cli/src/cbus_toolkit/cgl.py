"""CGL 1.1 exchange through the vendor's native routing/import rules."""
from __future__ import annotations

import json

from .native import NativeProjects, _address, _project


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate CGL field: {key}")
        result[key] = value
    return result


def parse_document(text: str) -> dict:
    """Validate JSON structure before import; C-Gate validates route semantics."""
    def invalid(value):
        raise ValueError(f"Invalid JSON number: {value}")
    document = json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)
    if not isinstance(document, dict) or document.get("cglVersion") != "1.1":
        raise ValueError("Expected a CGL 1.1 JSON document")
    _address(document.get("localNetwork"))

    def entities(items, kind):
        if not isinstance(items, list):
            raise ValueError(f"CGL {kind} must be an array")
        seen = set()
        child = {"networks": "applications", "applications": "groups", "groups": "levels"}.get(kind)
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"CGL {kind} entries must be objects")
            address = _address(item.get("address"))
            if address in seen:
                raise ValueError(f"Duplicate CGL {kind} address: {address}")
            seen.add(address)
            if "name" in item and not isinstance(item["name"], str):
                raise ValueError("CGL names must be strings")
            if kind == "networks" and "route" in item:
                if not isinstance(item["route"], list):
                    raise ValueError("CGL route must be an array")
                for step in item["route"]:
                    _address(step)
            if kind == "applications" and "type" in item:
                _address(item["type"])
            if child:
                entities(item.get(child, []), child)
    entities(document.get("networks"), "networks")
    return document


def summary(document: dict) -> dict:
    counts = {kind: 0 for kind in ("networks", "applications", "groups", "levels")}
    def count(node, kinds):
        if kinds:
            items = node.get(kinds[0], [])
            counts[kinds[0]] += len(items)
            for item in items:
                count(item, kinds[1:])
    count(document, list(counts))
    return {"version": document["cglVersion"], "local_network": document["localNetwork"], **counts}


def _selection(values):
    if values is None:
        return "*"
    values = list(values)
    if not values:
        raise ValueError("CGL selection cannot be empty; omit it for all")
    return ",".join(_address(value) for value in values)


class NativeCGL:
    def __init__(self, client):
        self.client = client

    def export(self, project, *, networks=None, applications=None) -> dict:
        command = f"CGL EXPORT {_project(project)} {_selection(networks)} {_selection(applications)}"
        response = self.client.command(command)
        if response.code != 344 or not response.lines[0].startswith("343-"):
            raise RuntimeError("C-Gate did not return a complete CGL snippet")
        parts = []
        for line in response.lines[1:-1]:
            if line.startswith("347-"):
                parts.append(line[4:])
            elif len(line) >= 4 and line[:3].isdigit() and line[3] in " -":
                raise RuntimeError(f"Unexpected CGL snippet status: {line[:4]}")
            else:
                parts.append(line)
        return parse_document("\n".join(parts))

    def import_document(self, project, text, *, backup_project=None) -> dict:
        project = _project(project)
        document = parse_document(text)
        if backup_project is not None:
            backup_project = _project(backup_project)
            if backup_project.upper() == project.upper():
                raise ValueError("Backup project must differ from the import destination")
            projects = NativeProjects(self.client)
            projects.operation("save", project)
            projects.operation("copy", project, backup_project)
        try:
            response = self.client.command_document(f"CGL IMPORT {project}",
                                                    json.dumps(document, ensure_ascii=False))
        except (RuntimeError, OSError) as error:
            if backup_project:
                raise RuntimeError(f"CGL import failed; backup is project {backup_project}: {error}") from error
            raise
        # Native C-Gate uses final 380 for skipped/non-routable networks, which
        # is a complete protocol reply but an incomplete import operation.
        complete = response.code == 200 and not any(
            "SKIPPED" in line or "not completed" in line for line in response.lines)
        return {"complete": complete, "backup_project": backup_project,
                "document": summary(document), "response": response}
