"""Census every template in the original C-Gate project migration stylesheets.

The vendor stylesheets are read from an explicitly selected C-Gate app
directory and are never copied. The committed census carries hashes, stable
template IDs, short match identifiers and mechanically extracted unit type,
firmware-prefix and PP names. Long match patterns are represented by hashes.
``portable_coverage`` comes from the explicit mapping table in
``cbus_toolkit.project_legacy_transform``.

    python -m research.legacy_transform_template_census \
        --vendor "$CBUS_LOCAL_CGATE_VENDOR" \
        --output research/fixtures/project-legacy-transform-template-census.json
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from cbus_toolkit.project_legacy_transform import NATIVE_TEMPLATE_COVERAGE


FORMAT = "cbus-project-legacy-transform-template-census-v1"
XSL = "{http://www.w3.org/1999/XSL/Transform}"
MIGRATION_STYLESHEETS = ("v2tov21.xslt", "v21tov22.xslt", "v22tov23.xslt")
OUT_OF_SCOPE = {
    "repair.xslt": "PROJECT REPAIR stylesheet; see project-repair.md",
    "tidyduplicategroups.xslt": "PROJECT REPAIR tidy stylesheet; see project-repair.md",
}
SHORT_MATCH = 64
_UNIT_TYPE = re.compile(r"UnitType\s*=\s*'([^']+)'")
_PREFIX = re.compile(r"starts-with\(\s*FirmwareVersion\s*,\s*'([^']+)'\s*\)")
_PP_NAME = re.compile(r"PP\[\s*@Name\s*=\s*'([^']+)'")
_SELECTED_PP = re.compile(r"@Name\s*=\s*'([^']+)'")


def _normal(text: str | None) -> str:
    return " ".join((text or "").split())


def _sorted_unique(values) -> list[str]:
    return sorted(set(values))


def _created(template: ET.Element) -> list[str]:
    """Names of elements a template creates; PP elements as ``PP:Name``."""
    created = []
    for element in template.iter(XSL + "element"):
        name = element.get("name")
        if name == "PP":
            names = [attribute for attribute in element.iter(XSL + "attribute")
                     if attribute.get("name") == "Name"]
            if len(names) != 1:
                raise AssertionError("Created PP has no literal Name")
            created.append("PP:" + _normal(names[0].text))
        else:
            created.append(name)
    return created


def _classify(match: str, priority: str | None, created: list[str], body_empty: bool) -> str:
    tail = match.rsplit("/", 1)[-1]
    if priority == "-2" and "@*" in match:
        return "identity"
    if "DBVersion" in created:
        return "version"
    if "FirmwareVersion" in created:
        return "firmware-rename"
    if re.fullmatch(r"(?:cis:)?Unit", match) and any(c.startswith("PP:") for c in created):
        return "namespace-parameter-addition" if match.startswith("cis:") else "parameter-addition"
    if tail.startswith("PP[") and body_empty:
        return "conditional-parameter-removal" if "/" in match else "parameter-removal"
    if match.startswith("PP[") and created:
        selected = _SELECTED_PP.findall(match)
        if len(created) == 1 and created[0] != "PP:" + selected[0]:
            return "parameter-rename"
        if "PP:" + selected[0] in created:
            return "parameter-expansion"
    raise AssertionError(f"Unclassified template {match!r}")


def template_id(stylesheet: str, ordinal: int, match: str, name: str, mode: str) -> str:
    signature = sha256(f"match={match}\nname={name}\nmode={mode}".encode()).hexdigest()[:8]
    return f"{stylesheet.removesuffix('.xslt')}#{ordinal:02d}-{signature}"


def census(vendor: Path) -> dict:
    transform = Path(vendor) / "transform"
    versions = (transform / "projectversions.xml").read_bytes()
    chain = [[node.findtext("FromVersion"), node.findtext("ToVersion"), node.findtext("XSLTFile")]
             for node in ET.fromstring(versions).findall("Transform")]
    if [row[2] for row in chain] != list(MIGRATION_STYLESHEETS):
        raise AssertionError("Unexpected original migration chain")
    sources = {"projectversions.xml": sha256(versions).hexdigest()}
    templates = []
    summary = {}
    for stylesheet in MIGRATION_STYLESHEETS:
        raw = (transform / stylesheet).read_bytes()
        sources[stylesheet] = sha256(raw).hexdigest()
        counts = {"templates": 0, "covered": 0, "full": 0, "bounded": 0}
        root = ET.fromstring(raw)
        for ordinal, template in enumerate(root.findall(XSL + "template"), 1):
            match = _normal(template.get("match"))
            name = _normal(template.get("name"))
            mode = _normal(template.get("mode"))
            priority = template.get("priority")
            created = _created(template)
            tests = " ".join(_normal(node.get("test")) for node in template.iter(XSL + "if"))
            conditions = match + " " + tests
            tail = match.rsplit("/", 1)[-1]
            body_empty = len(template) == 0 and not _normal(template.text)
            classification = _classify(match, priority, created, body_empty)
            selected = (_SELECTED_PP.findall(tail) if tail.startswith("PP[") else [])
            ident = template_id(stylesheet, ordinal, match, name, mode)
            row = {"id": ident, "stylesheet": stylesheet, "ordinal": ordinal}
            if len(match) <= SHORT_MATCH:
                row["match"] = match
            row["match_sha256"] = sha256(match.encode()).hexdigest()
            row["template_sha256"] = sha256(ET.tostring(template)).hexdigest()
            row.update({
                "name": name or None, "mode": mode or None, "priority": priority,
                "classification": classification,
                "namespace_gated": ":" in match.split("[", 1)[0],
                "unit_types": _sorted_unique(_UNIT_TYPE.findall(conditions)),
                "firmware_prefixes": _sorted_unique(_PREFIX.findall(conditions)),
                "selected_pp": selected,
                "condition_pp": _sorted_unique(
                    name for name in _PP_NAME.findall(conditions) if name not in selected),
                "created": created,
            })
            coverage = NATIVE_TEMPLATE_COVERAGE.get(ident)
            row["portable_coverage"] = coverage is not None
            row["portable_extent"] = coverage[0] if coverage else None
            row["portable_scope"] = coverage[1] if coverage else None
            counts["templates"] += 1
            if coverage:
                counts["covered"] += 1
                counts[coverage[0]] += 1
            templates.append(row)
        summary[stylesheet] = counts
    summary["total"] = {key: sum(summary[s][key] for s in MIGRATION_STYLESHEETS)
                        for key in ("templates", "covered", "full", "bounded")}
    unknown = set(NATIVE_TEMPLATE_COVERAGE) - {row["id"] for row in templates}
    if unknown:
        raise AssertionError(f"Coverage mapping names unknown templates: {sorted(unknown)}")
    return {
        "format": FORMAT,
        "target": "original C-Gate 3.4.0 build 2001 transform/ migration stylesheets",
        "sources": sources,
        "out_of_scope": {name: {"sha256": sha256((transform / name).read_bytes()).hexdigest(),
                                "reason": reason} for name, reason in OUT_OF_SCOPE.items()},
        "chain": chain,
        "coverage_source": "src/cbus_toolkit/project_legacy_transform.py:NATIVE_TEMPLATE_COVERAGE",
        "summary": summary,
        "templates": templates,
    }


def render(vendor: Path) -> str:
    return json.dumps(census(vendor), indent=2) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render(args.vendor))
