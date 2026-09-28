"""Capture bounded internal-DTD repair cases from the pinned original methods."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.project_repair_original import run_original


SOURCES = {
    "no-subset": '<!DOCTYPE Project><Project><TagName>A</TagName></Project>',
    "empty-subset": '<!DOCTYPE Project []><Project><TagName>A</TagName></Project>',
    "one-text": '<!DOCTYPE Project [<!ENTITY x "safe">]><Project><TagName>&x;</TagName></Project>',
    "multi-text": '<!DOCTYPE Project [<!ENTITY x "A"><!ENTITY y "B">]><Project><TagName>&x;&y;</TagName></Project>',
    "nested-text": '<!DOCTYPE Project [<!ENTITY x "A"><!ENTITY y "&x;B">]><Project><TagName>&y;</TagName></Project>',
    "attribute": '<!DOCTYPE Project [<!ENTITY x "A&amp;B">]><Project a="&x;"/>',
    "markup": '<!DOCTYPE Project [<!ENTITY x "<TagName>A</TagName>">]><Project>&x;</Project>',
    "character-reference": '<!DOCTYPE Project [<!ENTITY x "A&#13;B">]><Project><TagName>&x;</TagName></Project>',
    "element-declaration": '<!DOCTYPE Project [<!ELEMENT Project ANY>]><Project><TagName>A</TagName></Project>',
    "attribute-default": '<!DOCTYPE Project [<!ATTLIST Project a CDATA "default">]><Project/>',
    "duplicate-entity": '<!DOCTYPE Project [<!ENTITY x "first"><!ENTITY x "second">]><Project><TagName>&x;</TagName></Project>',
    "dtd-comment": '<!DOCTYPE Project [<!-- hi --><!ENTITY x "A">]><Project><TagName>&x;</TagName></Project>',
}


def capture(*, java: str, javac: str, vendor: str) -> dict:
    cases = [{"id": f"{name}-{operation}", "operation": operation,
              "input_hex": source.encode("utf-8").hex()}
             for name, source in SOURCES.items()
             for operation in ("repair", "tidy", "full")]
    original = run_original(cases, java=java, javac=javac, vendor=vendor)
    pins = {}
    for source, digest in original.pop("inputs").items():
        name = Path(source).name
        key = "transform/" + name if name.endswith(".xslt") else name
        if key in pins:
            raise AssertionError("Ambiguous original source pin")
        pins[key] = digest
    if set(pins) != {"RepairStageProbe.java", "project_repair_original.py",
                     "java", "javac", "cgate.jar", "transform/repair.xslt",
                     "transform/tidyduplicategroups.xslt"}:
        raise AssertionError("Incomplete original source pins")
    original["source_pins"] = pins
    rows = [{**case, **result} for case, result in zip(cases, original.pop("rows"), strict=True)]
    return {"target": "original C-Gate 3.4.0.2001 repair methods", "original": original,
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", required=True)
    parser.add_argument("--javac", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(capture(java=args.java, javac=args.javac,
                                               vendor=args.vendor), indent=2) + "\n")
