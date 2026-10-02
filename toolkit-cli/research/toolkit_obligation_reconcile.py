#!/usr/bin/env python3
"""Thin offline driver for the packaged obligation reconciliation diagnostic."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cbus_toolkit.toolkit_obligation_reconcile import (
    ReconciliationError, collect_source_records, reconcile_bundle_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path,
                        help="Read artifact IDs as relative files under this trusted directory")
    parser.add_argument("--require-complete", action="store_true",
                        help="Require completeness only for the explicitly declared input surface")
    args = parser.parse_args()
    try:
        report = reconcile_bundle_file(args.bundle, artifact_root=args.artifact_root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return int(args.require_complete and not report["complete_for_declared_surface"])
    except (OSError, ReconciliationError) as error:
        # Local paths and raw source data are deliberately excluded from errors.
        message = str(error) if isinstance(error, ReconciliationError) else "artifact read failed"
        print(json.dumps({"format": "cbus-toolkit-obligation-reconciliation-error-v1",
                          "error": message, "full_toolkit_parity": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
