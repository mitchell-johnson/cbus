"""Source-pinned, offline projection of the documentor's status-report minimum.

Factory/interface membership is independent of stored PP availability. The
native documentor loads each unit and omits failed loads; saved XML cannot
observe those success/failure flags. This module projects successful loads
only when every potentially participating unit has an admitted PP mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Iterable

from .toolkit_database_csv_registry import registrations_for

if TYPE_CHECKING:
    from .project_documentation import Unit

STATUS_REPORT_BASIS = (
    "stored_pp_snapshot; original programming-load success/failure not observed"
)
ICBUS_INPUT_UNIT_GUID = "b9f6b2d7-40ec-4399-883d-f40f76931f58"
SENTINEL = 99999

# All 334 registered concrete classes, independently checked against original
# inherited Delphi interface tables by project_documentor_status_static.py.
INPUT_CLASSES = frozenset("""
TBCI4A TBCN2B TBCN4B TBCNC4A TBCNC4B TCLK2 TDINAUX4 TIOPE1R1 TIOPE2C4 TIOPE2R2 TKEYA1 TKEYA1_A
TKEYA3 TKEYA3_A TKEYA6 TKEYA6_A TKEYA8 TKEYA8_A TKEYAUX4 TKEYAV2 TKEYAV2_A TKEYAV4 TKEYAV4_A TKEYB2
TKEYB2_A TKEYB4 TKEYB4_A TKEYB6 TKEYB6_A TKEYBC2 TKEYBC4 TKEYBIR2 TKEYBIR4 TKEYBIR6 TKEYBL5 TKEYC1
TKEYC2 TKEYC4 TKEYCIR1 TKEYCIR4 TKEYDL4 TKEYDV1 TKEYDV2 TKEYDV3 TKEYDV4 TKEYEx TKEYGL5 TKEYH1
TKEYH1_A TKEYH2 TKEYH2_A TKEYH3 TKEYH3_A TKEYH4 TKEYH4_A TKEYIR1 TKEYIR4 TKEYM2 TKEYM2_A TKEYM4
TKEYM4_A TKEYM8 TKEYM8_A TKEYML5 TKEYP2 TKEYP4 TKEYP6 TKEYSCEN4 TKEYV1 TKEYV1SP TKEYV2 TKEYV2SP
TKEYV3 TKEYV3SP TKey1 TKey2 TKey4 TPC_GIM TSCNCTL5 TSENCT4 TSENLL TSENLLA TSENPILL TSENPILLA TSENPIR
TSENPIRIC TSENPIROA TSENPIRSS TSENTEMP TSENTEMPPro TST7SENLL TST7SENPILL TST7SENPIROA TST7SENPIRSS
""".split())

NONINPUT_CLASSES = frozenset("""
TANODN4 TANOMB8 TAN_OUT4 TBridge1 TBridge2 TCBusBurden TCBusCable TCBusEDLTUnit
TCBusWGUnitNoRepeatSALTransmission TCBusWGUnitNoSynchroniseToWired TCBusWirelessGatewayAdvancedUnit
TCBusWirelessGatewayUnit TCBusWirelessPCIUnit TDIMAR12 TDIMAR3 TDIMAR6 TDIMDD4 TDIMDD4F TDIMDD8
TDIMDD8F TDIMDN4 TDIMDN4F TDIMDN8 TDIMDN8F TDIMDS8 TDIMDU4 TDIMMER4 TDIMPR1 TDIMPR12 TDIMPR12A
TDIMPR12L1 TDIMPR2 TDIMPR3A TDIMPR4 TDIMPR6A TDMXDO12 TDSIMB8 TNCCInputUnit TNCCOutputUnit TPCI2
TPCI3 TPCI4 TPCI4DALI TPCI4NoBurden TPCI4PC_CTA TPCI4_PC_CTB TPCI4_PC_CTBL TPCIMIND2 TPCSHAC
TPC_DAL2B TPC_DAL2C TPC_PACA TPC_RDTS TPC_TSA TPC_TSA5 TPC_TSB TPC_TSB5 TPC_WHAD TPC_WHAM TPC_WHAR
TPC_WHARB TPowerSupply TRELAY1 TRELAY2 TRELAY4 TRELDB1 TRELDC4 TRELDF1 TRELDN12 TRELDN4 TRELDN8
TRELDN8B TRELDN8SP TRELMB8 TRELSM8 TSYSDAL2 TWGWiresSide TWPA2D1 TWPA2D1NoKeySets
TWPA2D1NoSceneToggle TWPA2D1_2Remotes TWPA2D1_2Remotes_CycleContinuous TWPA2R1 TWPA2R1NoKeySets
TWPA2R1NoSceneToggle TWPA2R1_2Remotes TWPA2R1_2Remotes_CycleContinuous TWPAD1D1 TWPAD1R1 TWPAP2D1
TWPAP2D1_2Remotes TWPAP2R1 TWPAP2R1_2Remotes TWRB2D1 TWRB2D1NoKeySets TWRB2D1NoSceneToggle
TWRB2D1_2Remotes TWRB2D1_2Remotes_CycleContinuous TWRB2R1 TWRB2R1NoKeySets TWRB2R1NoSceneToggle
TWRB2R1_2Remotes TWRB2R1_2Remotes_CycleContinuous TWRB4D1 TWRB4D1NoKeySets TWRB4D1NoSceneToggle
TWRB4D1_2Remotes TWRB4D1_2Remotes_CycleContinuous TWRB4D2 TWRB4D2NoKeySets TWRB4D2NoSceneToggle
TWRB4D2_2Remotes TWRB4D2_2Remotes_CycleContinuous TWRB4R1 TWRB4R1NoKeySets TWRB4R1NoSceneToggle
TWRB4R1_2Remotes TWRB4R1_2Remotes_CycleContinuous TWRB4R2 TWRB4R2NoKeySets TWRB4R2NoSceneToggle
TWRB4R2_2Remotes TWRB4R2_2Remotes_CycleContinuous TWRB6D1 TWRB6D1NoKeySets TWRB6D1NoSceneToggle
TWRB6D1_2Remotes TWRB6D1_2Remotes_CycleContinuous TWRB6D2 TWRB6D2NoKeySets TWRB6D2NoSceneToggle
TWRB6D2_2Remotes TWRB6D2_2Remotes_CycleContinuous TWRB6R1 TWRB6R1NoKeySets TWRB6R1NoSceneToggle
TWRB6R1_2Remotes TWRB6R1_2Remotes_CycleContinuous TWRB6R2 TWRB6R2NoKeySets TWRB6R2NoSceneToggle
TWRB6R2_2Remotes TWRB6R2_2Remotes_CycleContinuous TWRD0D1 TWRD0R1 TWRD1D1 TWRD1R1 TWRD2D1 TWRD2R1
TWRD3D1 TWRD3R1 TWRD4D1 TWRD4F1 TWRD4R1 TWRM1R1EZ TWRM2D1 TWRM2D1EZ TWRM2D1NoKeySets
TWRM2D1NoSceneToggle TWRM2D1_2Remotes TWRM2D1_2Remotes_CycleContinuous TWRM2R1 TWRM2R1NoKeySets
TWRM2R1NoSceneToggle TWRM2R1_2Remotes TWRM2R1_2Remotes_CycleContinuous TWRM2R2EZ TWRM4D1
TWRM4D1NoKeySets TWRM4D1NoSceneToggle TWRM4D1_2Remotes TWRM4D1_2Remotes_CycleContinuous TWRM4D2
TWRM4D2EZ TWRM4D2NoKeySets TWRM4D2NoSceneToggle TWRM4D2_2Remotes TWRM4D2_2Remotes_CycleContinuous
TWRM4R1 TWRM4R1NoKeySets TWRM4R1NoSceneToggle TWRM4R1_2Remotes TWRM4R1_2Remotes_CycleContinuous
TWRM4R2 TWRM4R2NoKeySets TWRM4R2NoSceneToggle TWRM4R2_2Remotes TWRM4R2_2Remotes_CycleContinuous
TWRM8D1 TWRM8D1NoKeySets TWRM8D1NoSceneToggle TWRM8D1_2Remotes TWRM8D1_2Remotes_CycleContinuous
TWRM8D2 TWRM8D2NoKeySets TWRM8D2NoSceneToggle TWRM8D2_2Remotes TWRM8D2_2Remotes_CycleContinuous
TWRM8R1 TWRM8R1NoKeySets TWRM8R1NoSceneToggle TWRM8R1_2Remotes TWRM8R1_2Remotes_CycleContinuous
TWRM8R2 TWRM8R2NoKeySets TWRM8R2NoSceneToggle TWRM8R2_2Remotes TWRM8R2_2Remotes_CycleContinuous
TWRP2D1 TWRP2D1_2Remotes TWRP2D1_2Remotes_CycleContinuous TWRP2R1 TWRP2R1_2Remotes
TWRP2R1_2Remotes_CycleContinuous TWRP4D1 TWRP4D1_2Remotes TWRP4D1_2Remotes_CycleContinuous TWRP4D2
TWRP4D2_2Remotes TWRP4D2_2Remotes_CycleContinuous TWRP4R1 TWRP4R1_2Remotes
TWRP4R1_2Remotes_CycleContinuous TWRP4R2 TWRP4R2_2Remotes TWRP4R2_2Remotes_CycleContinuous TWRP6D1
TWRP6D1_2Remotes TWRP6D1_2Remotes_CycleContinuous TWRP6D2 TWRP6D2_2Remotes
TWRP6D2_2Remotes_CycleContinuous TWRP6R1 TWRP6R1_2Remotes TWRP6R1_2Remotes_CycleContinuous TWRP6R2
TWRP6R2_2Remotes TWRP6R2_2Remotes_CycleContinuous TWTXU TWTXUP
""".split())

# These inherited input-interface implementations have no recovered PP loader.
# Do not mistake the interface, class name, or a similarly named PP for mapping.
UNMAPPED_INPUT_CLASSES = frozenset({"TPC_GIM", "TSENCT4", "TKEYGL5"})


@dataclass(frozen=True)
class StatusReportResult:
    known: bool
    seconds: int | None = None
    unit: Unit | None = None
    issues: tuple[str, ...] = ()
    basis: str = STATUS_REPORT_BASIS


def input_interface(unit_type: str, firmware: str) -> tuple[bool | None, str | None]:
    """Return first matching factory class membership, or unknown for missing facts.

    Requiring a numeric firmware is a bounded offline admission rule. The
    original's general VersionStringCompare also accepts malformed strings.
    """
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", firmware) is None or any(
            len(part) > 10 or int(part) > 2147483647 for part in firmware.split(".")):
        return None, None
    rows = registrations_for(unit_type, firmware)
    if not rows:
        return None, None
    selected = rows[0][3]
    if selected in INPUT_CLASSES:
        return True, selected
    if selected in NONINPUT_CLASSES:
        return False, selected
    return None, selected


def _interval(value: str | None) -> int | None:
    if value is None:
        return None
    token = value.strip()
    if len(token) > 32:
        return None
    if re.fullmatch(r"[+-]?[0-9]+", token):
        result = int(token, 10)
    elif re.fullmatch(r"(?:\$|0[xX])[0-9a-fA-F]+", token):
        result = int(token.removeprefix("$") if token.startswith("$") else token[2:], 16)
    else:
        return None
    return result if -(2 ** 31) <= result < 2 ** 31 else None


def minimum_status_report(units: Iterable[Unit]) -> StatusReportResult:
    """Project the native strict minimum in supplied unit-manager order.

    No clamp, time multiplier, zero special case, or UI minimum-three-seconds
    formatting is applied: both recovered getters return the integer attribute
    verbatim. Values >=99999 never replace the original sentinel. Ties retain
    the first encountered unit. Unknown candidates invalidate the whole minimum.
    """
    minimum, selected, issues = SENTINEL, None, []
    for unit in units:
        supported, klass = input_interface(unit.unit_type, unit.firmware)
        label = f"Unit {unit.address} ({unit.unit_type} {unit.firmware})"
        if supported is None:
            issues.append(f"{label}: input-interface membership is unknown")
        elif supported:
            if klass in UNMAPPED_INPUT_CLASSES:
                issues.append(f"{label}: status-report PP mapping is unrecovered")
                continue
            interval = _interval(unit.parameters.get("StatusReportInterval"))
            if interval is None:
                issues.append(f"{label}: missing or invalid StatusReportInterval PP")
            elif interval < minimum:
                minimum, selected = interval, unit
    if issues:
        return StatusReportResult(False, issues=tuple(issues))
    if selected is None:
        return StatusReportResult(True)
    return StatusReportResult(True, minimum, selected)
