"""Original build-2001 ownership for admitted CDG proxy edits.

Global leaves mirror the service's advertised schema. Line leaves mirror
``rust/cbus-cgate/src/service/dali_proxy_lines.rs`` and are admitted only where
``research/fixtures/dali-ext-proxy-original-vectors.json`` (case
``all_line_families``) executed the original serializer on that leaf shape and
native rules neither exclude nor overwrite its dirty-write effect.
"""
from __future__ import annotations

PREFIX = "/cdg/extParams/proxy/"


def _fields():
    fields = {}
    for path, address in (
        ("configVersion/major", 256), ("configVersion/minor", 257),
        ("deviceID/id", 556), ("errorReportingEnableGroup/group", 632),
        ("errorReportingTriggerGroup/group", 633),
        ("errorReportingResendActionSelector/selector", 634),
        ("errorReportingAcknowledgeAllActionSelector/selector", 635),
        ("errorReportingMode/mode", 636),
        ("errorReportingRegularReportInterval/interval", 637),
        ("measurementRequestTriggerGroup/group", 558),
        ("measurementClearTriggerGroup/group", 559),
        ("measurementRegularBroadcastInterval/interval", 644),
        ("cbusVoltageThresholds/warningSetThreshold", 656),
        ("cbusVoltageThresholds/warningClearThreshold", 657),
        ("cbusVoltageThresholds/criticalSetThreshold", 658),
        ("cbusVoltageThresholds/criticalClearThreshold", 659),
        ("cbusOverTemperatureThresholds/unitSetThreshold", 660),
        ("cbusOverTemperatureThresholds/unitClearThreshold", 661),
        ("cbusOverTemperatureThresholds/lineASetThreshold", 662),
        ("cbusOverTemperatureThresholds/lineBSetThreshold", 663),
        ("cbusOverTemperatureThresholds/lineAClearThreshold", 664),
        ("cbusOverTemperatureThresholds/lineBClearThreshold", 665),
    ):
        fields[path] = (address, 255, False)
    for index in range(4):
        fields[f"lightingApplications/app{index + 1}"] = (512 + index, 255, False)
    for index in range(6):
        fields[f"networkPathErrorReportAndMeasurements/path/{index}"] = (638 + index, 255, False)
    for index in range(16):
        fields[f"logicGroups/{index}/groupAddress"] = (522 + index * 2, 255, False)
        fields[f"logicGroups/{index}/applicationIndex"] = (523 + index * 2, 3, False)
        fields[f"logicGroups/{index}/restoreToPreviousLevel"] = (523 + index * 2, 1, True)
        fields[f"logicGroupRestoreLevel/{index}/level"] = (616 + index, 255, False)
    for family, address, names in (
        ("frontPanelUiControl", 518, (
            "localToggleDisabledA", "localToggleDisabledB", "commissioningDisabledA",
            "commissioningDisabledB", "cbusPriorityDisabledA", "cbusPriorityDisabledB",
            "factoryResetDisabled")),
        ("enableGroupLevelStoreOptions", 521, (
            "wboEnableA", "wboEnableB", "errorReportingEnable", "colourModeA", "colourModeB")),
        ("measurementRegularBroadcastOptions", 645, (
            "lampHours", "channelMetering", "daliMacTemperature", "daliCurrent", "daliVoltage",
            "cbusVoltage", "unitTemperature")),
        ("brokenDeviceDefinitionMask", 608, (
            "controlGearFailure", "lampFailure", "circuitFailure", "batteryDurationFailure",
            "batteryFailure", "emergencyLampFailure", "functionTestMaxDelayExceeded",
            "durationTestMaxDelayExceeded", "functionTestFailed", "durationTestFailed",
            "openCircuit", "shortCircuit", "loadDecrease", "loadIncrease", "currentProtectorActive",
            "thermalShutdown", "thermalOverloadWithLightLevelReduction", "referenceMeasurementFailed")),
    ):
        for index, name in enumerate(names):
            fields[f"{family}/{name}"] = (address + index // 8, 1, True)
    return fields


FIELDS = _fields()
FAMILIES = frozenset(path.split("/")[0] for path in FIELDS)


def edit_disposition(edit):
    path = edit["path"]
    suffix = path.removeprefix(PREFIX)
    if suffix.startswith("line/"):
        return line_edit_disposition(edit)
    if suffix not in FIELDS:
        raise ValueError("DALI proxy property is not an admitted native writable field")
    address, limit, boolean = FIELDS[suffix]
    value = edit["value"]
    if boolean:
        if type(value) is not bool:
            raise ValueError("DALI proxy field requires a Boolean")
    elif type(value) is not int or not 0 <= value <= limit:
        raise ValueError(f"DALI proxy field requires an integer in 0..{limit}")
    family = suffix.split("/")[0]
    addresses = sorted({row[0] for key, row in FIELDS.items() if key.split("/")[0] == family})
    return {"kind": "proxy", "path": path, "family": family, "address": address,
            "family_addresses": addresses, "step": "WRITE_GATEWAY_EXT_FULL",
            "disposition": "planned-native-gateway-proxy-field"}


def check_effective_field(model, disposition):
    proxy = model.get("cdg", {}).get("extParams", {}).get("proxy", {})
    suffix = disposition["path"][len(PREFIX):]
    if suffix.startswith("line/"):
        _check_effective_line_field(proxy, disposition)
        return
    if suffix == "errorReportingMode/mode":
        enable = proxy.get("errorReportingEnableGroup", {}).get("group")
        stored = proxy.get("enableGroupLevelStoreOptions", {}).get("errorReportingEnable")
        if enable != 255 and stored is True:
            raise ValueError("Native error reporting mode byte is excluded while its enable group stores mode")
    if suffix.startswith("logicGroupRestoreLevel/"):
        index = int(suffix.split("/")[1])
        groups = proxy.get("logicGroups", [])
        if len(groups) <= index or groups[index].get("restoreToPreviousLevel") is not False:
            raise ValueError("Native logic restore level byte is excluded when restore-to-previous is enabled")


# Native line layout (gateway extended addresses; line L is 0 for A, 1 for B).
# The executed original vector edits the first and last slot of each indexed
# family; its whole-family zero serialization pins every slot's ownership.
_OBJECT_FIELDS = {
    # field: (byte offsets in the 32-byte slot, kind, maximum)
    "groupAddress": ((0,), "integer", 255),
    "warnBeforeOffLevel": ((1,), "integer", 255),
    "logicAssignmentBitmask16": ((2, 3), "integer", 65535),
    "applicationIndex": ((4,), "integer", 3),
    "disableDaliToCbus": ((4,), "boolean", 1),
    "minLogic": ((4,), "boolean", 1),
    "warnBeforeOffTime": ((4,), "integer", 15),
    "colourZone": ((5,), "integer", 15),
    "colourType": ((5,), "integer", 3),
    "fadeInstantOff": ((5, 6), "integer", 7),
    "fadeInstantMax": ((6,), "integer", 7),
    "fadeInstantLvl": ((6,), "integer", 7),
    "secondaryGroupAddress": ((8,), "integer", 255),
    "tertiaryGroupAddress": ((9,), "integer", 255),
}
_OBJECT_OWNED = (0, 1, 2, 3, 4, 5, 6, 8, 9)  # native never writes byte 7 or 10..31
_FADE_FIELDS = frozenset(("fadeInstantOff", "fadeInstantMax", "fadeInstantLvl"))
LINE_FAMILY_COUNT = 15
# Recalled families whose edits native rules make ineffective, or whose
# effective write no executed original vector establishes.
LINE_REFUSALS = {
    "statusCorrectionMask": "Native line statusCorrectionMask bytes 592..607 are statically excluded from dirty writes",
    "statusCorrectionInterval": "Native line statusCorrectionInterval bytes 612..613 are statically excluded from dirty writes",
    "lampRunningTime": ("Native lamp running-time bytes are excluded unless their target is zero, and no executed "
                        "original vector establishes a zero reset write; the leaf is not admitted"),
    "oidToShortAddress": ("Native serialization writes shortAddressToOid after oidToShortAddress over the same "
                          "bytes, so a forward-map edit is never the effective writer; edit shortAddressToOid/map"),
}


def _line_fields():
    fields = {}
    for line in range(2):
        def add(suffix, family, addresses, kind, limit, owned):
            fields[f"line/{line}/{suffix}"] = {
                "family": f"line/{line}/{family}", "line_index": line, "addresses": tuple(addresses),
                "kind": kind, "limit": limit, "family_addresses": tuple(owned)}
        groups = range(7168 + line * 128, 7168 + line * 128 + 128)
        for slot in range(16):
            base = 7168 + line * 128 + slot * 8
            add(f"virtualGroups/{slot}/members", "virtualGroups", range(base, base + 8), "members", 63, groups)
        for family, base in (("usedDevices", 8800), ("remoteOnMask", 560), ("remoteOffMask", 576)):
            start = base + line * 8
            add(f"{family}/members", family, range(start, start + 8), "members", 63, range(start, start + 8))
        objects = [768 + line * 3104 + slot * 32 + offset for slot in range(97) for offset in _OBJECT_OWNED]
        for slot in range(97):
            base = 768 + line * 3104 + slot * 32
            for field, (offsets, kind, limit) in _OBJECT_FIELDS.items():
                add(f"objectProperties/{slot}/{field}", "objectProperties",
                    [base + offset for offset in offsets], kind, limit, objects)
        maps = range(7040 + line * 64, 7040 + line * 64 + 64)
        add("shortAddressToOid/map", "shortAddressToOid", maps, "inverse-map", 63, maps)
        for family, field, address in (("missingDeviceThreshold", "threshold", 519),
                                       ("wboEnableGroup", "group", 516),
                                       ("wboEnableGroupRestoreLevel", "level", 554),
                                       ("statusUpdatingInterval", "interval", 614)):
            add(f"{family}/{field}", family, (address + line,), "integer", 255, (address + line,))
        triggers = range(7936 + line * 340, 7936 + line * 340 + 340)
        for slot in range(17):
            base = 7936 + line * 340 + slot * 20
            add(f"sceneTriggerMap/{slot}/triggerGroup", "sceneTriggerMap", (base + 2,), "integer", 255, triggers)
            add(f"sceneTriggerMap/{slot}/actionSelector", "sceneTriggerMap",
                (base, base + 1, *range(base + 3, base + 19)), "selectors", 255, triggers)
    return fields


LINE_FIELDS = _line_fields()


def _canonical_key(key, maximum):
    return key.isdecimal() and str(int(key)) == key and int(key) <= maximum


def _line_value(spec, value):
    kind, limit = spec["kind"], spec["limit"]
    if kind == "boolean":
        if type(value) is not bool:
            raise ValueError("DALI line proxy field requires a Boolean")
    elif kind == "integer":
        if type(value) is not int or not 0 <= value <= limit:
            raise ValueError(f"DALI line proxy field requires an integer in 0..{limit}")
    elif kind == "members":
        # Owned canonical form: the native decoder returns ascending members,
        # so staged and freshly recovered values compare exactly.
        if (not isinstance(value, list) or any(type(item) is not int or not 0 <= item <= 63 for item in value)
                or value != sorted(set(value))):
            raise ValueError("DALI line mask members must be strictly ascending integers in 0..63")
    elif kind == "inverse-map":
        if not isinstance(value, dict):
            raise ValueError("DALI shortAddressToOid map must be an object")
        if any(not _canonical_key(key, 254) for key in value):
            raise ValueError("DALI shortAddressToOid keys must be canonical short addresses 0..254")
        if any(type(oid) is not int or not 0 <= oid <= 63 for oid in value.values()):
            raise ValueError("DALI shortAddressToOid values must be OIDs in 0..63")
        if len(set(value.values())) != len(value):
            raise ValueError("DALI shortAddressToOid map must be one-to-one")
    elif kind == "selectors":
        if not isinstance(value, dict):
            raise ValueError("DALI sceneTriggerMap actionSelector must be an object")
        if any(not _canonical_key(key, 15) for key in value):
            raise ValueError("DALI actionSelector keys must be canonical scene indices 0..15")
        if any(type(selector) is not int or not 0 <= selector <= 255 for selector in value.values()):
            raise ValueError("DALI actionSelector values must be integers in 0..255")


def line_edit_disposition(edit):
    path = edit["path"]
    suffix = path.removeprefix(PREFIX)
    spec = LINE_FIELDS.get(suffix)
    if spec is None:
        parts = suffix.split("/")
        if "utilitySaToOidMap" in parts:
            raise ValueError("DALI utilitySaToOidMap is a computed read-only native property")
        if len(parts) < 3 or parts[1] not in ("0", "1"):
            raise ValueError("DALI proxy line property needs line index 0 (A) or 1 (B) and a family")
        if parts[2] in LINE_REFUSALS:
            raise ValueError(LINE_REFUSALS[parts[2]])
        raise ValueError("DALI proxy line property is not an evidenced native writable leaf; only leaf "
                         "shapes executed by the original line serializer are admitted")
    _line_value(spec, edit["value"])
    return {"kind": "proxy", "path": path, "family": spec["family"], "line_index": spec["line_index"],
            "address": spec["addresses"][0], "addresses": list(spec["addresses"]),
            "family_addresses": sorted(spec["family_addresses"]), "step": "WRITE_GATEWAY_EXT_FULL",
            "server_leaf_schema_advertised": False,
            "disposition": "planned-native-gateway-proxy-line-field"}


def _check_effective_line_field(proxy, disposition):
    parts = disposition["path"][len(PREFIX):].split("/")
    if parts[2] == "wboEnableGroupRestoreLevel":
        option = "wboEnableA" if disposition["line_index"] == 0 else "wboEnableB"
        if (proxy.get("enableGroupLevelStoreOptions") or {}).get(option) is not False:
            raise ValueError("Native WBO restore level byte is excluded while its enable group stores the level")
    if parts[2] == "objectProperties" and parts[-1] in _FADE_FIELDS:
        version = proxy.get("configVersion") or {}
        major, minor = version.get("major"), version.get("minor")
        if not (type(major) is int and type(minor) is int and (major > 1 or major == 1 and minor > 5)):
            raise ValueError("Native ObjectProperties fade controls need a staged ConfigVersion greater than 1.5")


def static_excluded(address):
    if (address == 557 or 646 <= address < 648 or 6976 <= address < 7040
            or 8616 <= address < 8800 or 666 <= address < 768 or 592 <= address < 608
            or 612 <= address < 614 or 8816 <= address < 11376):
        return True
    if 768 <= address < 6976:
        offset = (address - (768 if address < 3872 else 3872)) % 32
        return offset == 7 or offset >= 10
    return False


def byte_excluded(model, address):
    if static_excluded(address):
        return True
    memory = model.get("extParams", {})
    targets, values = memory.get("targetValues", {}), memory.get("values", {})
    def byte(location):
        return targets.get(str(location), values.get(str(location), 255))
    options = byte(521)
    if address in (554, 555):
        return bool(options & (1 << (address - 554)))
    if address == 636:
        return byte(632) != 255 and bool(options & 4)
    if 616 <= address < 632:
        return bool(byte(523 + (address - 616) * 2) & 4)
    if 7424 <= address < 7936:
        return targets.get(str(address)) != 0
    if 768 <= address < 6976 and (address - (768 if address < 3872 else 3872)) % 32 == 6:
        source = targets if "256" in targets and "257" in targets else values
        major, minor = source.get("256"), source.get("257")
        return not (type(major) is int and type(minor) is int and (major > 1 or major == 1 and minor > 5))
    return False
