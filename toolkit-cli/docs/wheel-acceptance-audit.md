# Installed-wheel report audit

`research/audit_wheel_acceptance.py` checks completed reports against an immutable wheel snapshot. It verifies every recorded snapshot path and hash, wheel/package correspondence, imported module hashes, required native gates, exact test/input maps, and matching successful Python 3.13/3.10 reports. This is an evidence check; it does not run tests or establish complete Toolkit parity.

A snapshot may additionally pin direct `docs/*.md` files. Those documents are still required to exist within the snapshot and match their recorded hashes. They are excluded only from the expected *test report* input map because `research/acceptance.py` does not select documentation as executable acceptance inputs. The exclusion does not cover nested documentation or other suffixes, and does not permit extra report inputs.

The external v7 snapshots remain unchanged, including their historical auditor. The separately reviewed live auditor can check their completed reports after the full runs finish. The documentation correction does not turn an incomplete or failed full run into a pass.

[Focused acceptance](../research/fixtures/wheel-audit-documentation-acceptance.json) records 13 local synthetic tests passing on both Python 3.13.14 and 3.10.20 with no skips: the previous eight guard tests plus five regressions for documentation, external snapshot roots, path traversal, changed/missing files, external symlinks, extra inputs and mismatched dual reports. No Windows or C-Gate job is part of this focused acceptance.
