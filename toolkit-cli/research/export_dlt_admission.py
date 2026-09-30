"""Export the Python DLT/eDLT profile registry for the Rust cmqttd gates.

Writes two committed files from ``cbus_toolkit.dlt_profiles``:

- ``rust/cbus-cgate/src/dlt_profiles.json``: the admission table the Rust
  ``dlt_profiles`` module embeds (profiles, revisions, workflows, findings);
- ``rust/testdata/vectors/dlt_profile_admission.jsonl``: exact Python
  admission decisions and refusal reasons that the Rust port must reproduce.

``--check`` fails without writing when either file differs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'toolkit-cli/src'))

from cbus_toolkit.dlt_profiles import PROFILES, WORKFLOWS, admission_table, refusal  # noqa: E402

TABLE = ROOT / 'rust/cbus-cgate/src/dlt_profiles.json'
VECTORS = ROOT / 'rust/testdata/vectors/dlt_profile_admission.jsonl'

# Identities chosen to exercise every refusal branch the Rust port implements.
_FIRMWARE = ('5.5.00', '5.5.99', '5.5.1', '05.05.00', '1.5.01', '1.6.00', '1.7.99', '5.4.00', '5.6.00', '9',
             '9.0.00', '10.0.00', '1.1', '1.4.00', '1.4.08', '2.0.00', '2.0.50', '2.1.00', '3.0.57', '3.0.5',
             '3.1.00', 'bad', '', None)
_CATALOG = (None, '5055EDL', '5085EDL', 'R5045EDL', '5505ED', '5085DL', '5055DL', 'E5084DL', '5084DL',
            'SLC5055DL', 'X', "it's")
_TYPES = (*PROFILES, 'KEYH5', 'KEYL5', 'KEYE1', 'keygl5', "O'Brien")


def vectors():
    """At most two identities per workflow, type and distinct decision, plus every admission."""
    rows, seen = [], {}
    for workflow in WORKFLOWS:
        for unit_type in _TYPES:
            for firmware in _FIRMWARE:
                catalogs = _CATALOG if 'catalog_number' in WORKFLOWS[workflow].identity else (None,)
                for catalog in catalogs:
                    reason = refusal(workflow, unit_type, firmware, catalog)
                    key = (workflow, unit_type, reason)
                    seen[key] = seen.get(key, 0) + 1
                    if reason is None or seen[key] <= 2:
                        rows.append({'workflow': workflow, 'unit_type': unit_type, 'firmware': firmware,
                                     'catalog_number': catalog, 'reason': reason})
    return rows


def render():
    table = json.dumps(admission_table(), indent=2, ensure_ascii=False) + '\n'
    lines = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in vectors())
    return {TABLE: table, VECTORS: lines}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='Fail if the committed files differ')
    args = parser.parse_args(argv)
    stale = []
    for path, text in render().items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(text, encoding='utf-8')
    if stale:
        print('Stale DLT admission exports: ' + ', '.join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
