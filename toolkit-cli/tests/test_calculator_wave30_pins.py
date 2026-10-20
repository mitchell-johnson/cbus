"""Wave 30 offline pins for calculator guards with zero prior refs.

Covers: empty-string catalogue lookup, non-CBusUnits root rejection,
single-sided switchable fields falling back to normal currents, and the
impedance >= 10 boundary.
"""
from pathlib import Path

import pytest

from cbus_toolkit.calculator import CalculatorCatalog, CalculatorError, CalculatorUnit


LIMITS = (
    "<Calculator><MinImpedance>400</MinImpedance>"
    "<MaxImpedance>1500</MaxImpedance>"
    "<MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator>"
)


def make_catalog(tmp_path: Path, body: str) -> CalculatorCatalog:
    path = tmp_path / "cbusunits.xml"
    path.write_text("<CBusUnits>" + LIMITS + "<Units>" + body + "</Units></CBusUnits>")
    return CalculatorCatalog.load(path)


def row(catalog: str, drawn: int = 0, supplied: int = 0, impedance: int = 100000, extra: str = "") -> str:
    return (
        f"<Unit><CatalogNumber>{catalog}</CatalogNumber>"
        f"<CurrentDrawn>{drawn}</CurrentDrawn>"
        f"<CurrentSupplied>{supplied}</CurrentSupplied>"
        f"<Impedance>{impedance}</Impedance>{extra}</Unit>"
    )


def test_empty_catalog_number_counts_as_not_calculated(tmp_path):
    catalog = make_catalog(tmp_path, row("A", impedance=1000))
    result = catalog.calculate([CalculatorUnit("A", "ANY"), CalculatorUnit("", "ANY")])
    assert (result.units_calculated, result.units_not_calculated) == (1, 1)
    assert not result.passed
    assert result.reasons == ("Some catalogue numbers were not found",)


def test_non_cbusunits_root_rejected(tmp_path):
    path = tmp_path / "cbusunits.xml"
    path.write_text("<NotUnits/>")
    with pytest.raises(CalculatorError, match="CBusUnits"):
        CalculatorCatalog.load(path)


def test_single_sided_switchable_fields_use_normal_currents(tmp_path):
    extra = (
        "<CurrentDrawnSwitchablePowerSupply>20</CurrentDrawnSwitchablePowerSupply>"
        "<FirmwareRevisions><Revision><UnitType>HALFSW</UnitType></Revision></FirmwareRevisions>"
    )
    catalog = make_catalog(tmp_path, row("HALF", drawn=88, supplied=99, extra=extra))
    assert "HALFSW" not in catalog.switchable_unit_types
    for flag in (False, True):
        result = catalog.calculate([CalculatorUnit("HALF", "HALFSW", switchable_supply_enabled=flag)])
        assert (result.current_supply_ma, result.current_consumption_ma) == (99, 88)


def test_impedance_boundary_ten_contributes(tmp_path):
    catalog = make_catalog(tmp_path, row("TEN", impedance=10))
    result = catalog.calculate([CalculatorUnit("TEN", "ANY")])
    assert result.impedance_ohms == 10
    assert result.exact_impedance_ohms == pytest.approx(10.0)
    assert result.reasons == ("Impedance is below the catalogue minimum",)
