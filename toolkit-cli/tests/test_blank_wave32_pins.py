"""Wave32 offline pins for eDLT Blank slot/plan guards (no hardware, no I/O).

Pins Blank guards in toolkit-cli/src/cbus_toolkit/edlt_blank.py that had
zero prior references in tests/ at the time of writing (verified via
``grep -rl`` over tests/*.py):
- non-canonical NavWidgetType layout rejection in ``EdltBlankWidget._slot``
- single-page layout page restriction in ``_slot``
- navigation-position Blank exclusion in ``_slot``
- ``apply`` rejection of non-BlankPlan plans
"""
import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_blank import EdltBlankWidget


def test_blank_slot_rejects_non_canonical_layout():
    with pytest.raises(EdltError, match="canonical single or multiple page layout"):
        EdltBlankWidget._slot({"NavWidgetType": (2,)}, 1, 1)


def test_blank_slot_rejects_non_page1_single_page_layout():
    with pytest.raises(EdltError, match="Single-page layout exposes only functional page1"):
        EdltBlankWidget._slot({"NavWidgetType": (0,)}, 2, 1)


def test_blank_slot_rejects_navigation_position():
    with pytest.raises(EdltError, match="no Blank widget choice"):
        EdltBlankWidget._slot({"NavWidgetType": (1,)}, 1, 5)


def test_blank_apply_rejects_non_blank_plan():
    widget = EdltBlankWidget.__new__(EdltBlankWidget)
    with pytest.raises(EdltError, match="Use a Blank plan returned"):
        widget.apply(None, None)
