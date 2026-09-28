"""Guard the pinned generic-GET eDLT property-inheritance finding."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from research.verify_edlt_get_inheritance import (
    FIXTURE,
    _registrations,
    check_fixture,
)


def test_pinned_inherited_property_set_remains_bounded() -> None:
    check_fixture(json.loads(FIXTURE.read_text()))


@pytest.mark.parametrize("edit", [
    lambda row: row["decision"].update(physical_device_cache_readback=True),
    lambda row: row["decision"].update(generic_get_open_unit_oracle_completed=True),
    lambda row: row["source"]["class_chain"][-1]["properties"].append("LabelCache"),
    lambda row: row["source"]["class_chain"][-1].update(property_insertions=2),
])
def test_fixture_rejects_forged_native_get_or_device_claim(edit) -> None:
    changed = deepcopy(json.loads(FIXTURE.read_text()))
    edit(changed)
    with pytest.raises(ValueError):
        check_fixture(changed)


def test_runtime_registration_is_not_misclassified_as_constructor() -> None:
    disassembly = """Compiled from \"ProGuard\"
public class Example extends Base {
  public Example();
    Code:
       0: return
  public void addProperty();
    Code:
       0: new #1 // class Cn
       3: ldc #2 // String LabelCache
       5: invokevirtual #3 // Method Cl.a:(LCk;)V
       8: return
}
"""
    with pytest.raises(ValueError, match="non-constructor property insertion"):
        _registrations(disassembly, "Example")
