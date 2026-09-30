"""Original build-2001 ownership for admitted global CDG proxy edits."""
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
