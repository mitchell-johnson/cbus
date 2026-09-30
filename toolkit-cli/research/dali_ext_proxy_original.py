"""Capture bounded DALI proxy bytes by invoking owned original Java classes.

No C-Gate daemon, PCI, broker or C-Bus endpoint is opened. The probe exercises
the 21 global proxy families, the 15 families on both line mappings and native
dirty-byte exclusions. It does not execute the deploy executor, a Toolkit
dialog, gateway programming, or physical persistence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


PINNED_JAR = "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
PINNED_CLASS_HASHES = {
    "com/clipsal/cgate/cbus/dali/model/DaliGatewayExtParamMap.class": "f94b23ade9dc8d0ab6219ce3096914c62efaa7292b7f3b1d09a612017cecf07d",
    "gT.class": "78388e81ec780d762285a9579c1413e9c7425c9960ea414523648ba421b23750",
    "gR.class": "ec7143d080260cd6bc0e4201a18e7355a5a5c29595fa83c18d1ee94f74812264",
    "gK.class": "c6eb760375c5172ba33782c62ba6ec242d8b20eb46b6d232940838681bb29e8a",
    "gJ.class": "73d7648c7a79fcc1d4743bc0302f0d0c7a0cd07bc63d07c47899d0c430705f22",
}
CLASSES = (
    "com/clipsal/cgate/cbus/dali/model/DaliGatewayExtParamMap.class",
    "com/clipsal/cgate/cbus/dali/model/ext/ExtProxy.class",
    "gT.class", "gR.class", "gK.class", "gJ.class",
    "hm.class", "hl.class", "hc.class", "hd.class", "hh.class", "ha.class",
    "hn.class", "gS.class", "ho.class", "hf.class", "he.class", "hj.class",
    "hi.class", "hk.class", "hg.class",
)
INPUT = {"512": 56, "513": 255, "514": 255, "515": 255,
         "518": 128, "521": 0, "556": 17,
         "557": 239, "613": 33, "10000": 171}
EDITS = [
    {"path": "/cdg/extParams/proxy/lightingApplications/app1", "value": 57},
    {"path": "/cdg/extParams/proxy/frontPanelUiControl/localToggleDisabledA", "value": True},
    {"path": "/cdg/extParams/proxy/enableGroupLevelStoreOptions/errorReportingEnable", "value": True},
    {"path": "/cdg/extParams/proxy/deviceID/id", "value": 42},
]


def _leaves(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, path + "/" + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, path + "/" + str(index))
    else:
        yield path, value


def _global_edits(model, high):
    edits = []
    for path, value in _leaves(model):
        if type(value) is bool:
            selected = high
        elif type(value) is int:
            selected = 3 if high and path.endswith("/applicationIndex") else 255 if high else 0
            if path == "/configVersion/major":
                selected = 2 if high else 0
            elif path == "/configVersion/minor":
                selected = 9 if high else 0
        else:
            raise ValueError(f"Unexpected native global leaf {path}: {value!r}")
        edits.append({"path": "/cdg/extParams/proxy" + path, "value": selected})
    return edits


def _line_edits():
    edits = []
    for line in range(2):
        prefix = f"/cdg/extParams/proxy/line/{line}/"
        for family in ("usedDevices", "remoteOnMask", "remoteOffMask", "statusCorrectionMask"):
            edits.append({"path": prefix + family + "/members", "value": [0, 7, 8, 31, 32, 63]})
        for slot in (0, 15):
            edits.append({"path": prefix + f"virtualGroups/{slot}/members", "value": [0, 7, 8, 63]})
        for family, field in (("missingDeviceThreshold", "threshold"), ("wboEnableGroup", "group"),
                              ("wboEnableGroupRestoreLevel", "level"),
                              ("statusCorrectionInterval", "interval"), ("statusUpdatingInterval", "interval")):
            edits.append({"path": prefix + family + "/" + field, "value": 255 - line})
        for slot, time in ((0, 0x12345678), (63, -2)):
            edits.append({"path": prefix + f"lampRunningTime/{slot}/time", "value": time})
        # Inverse is the final native writer of the shared address-map bytes.
        forward = [255] * 64
        forward[0], forward[63] = 7, 63
        edits.extend([
            {"path": prefix + "oidToShortAddress/map", "value": forward},
            {"path": prefix + "shortAddressToOid/map", "value": {"8": 0, "63": 63}},
        ])
        for slot in (0, 96):
            controls = {"groupAddress": 91, "warnBeforeOffLevel": 254,
                        "logicAssignmentBitmask16": 0x1234, "applicationIndex": 3,
                        "disableDaliToCbus": True, "minLogic": True,
                        "warnBeforeOffTime": 15, "colourZone": 15, "colourType": 3,
                        "fadeInstantOff": 5, "fadeInstantMax": 3, "fadeInstantLvl": 6,
                        "secondaryGroupAddress": 92, "tertiaryGroupAddress": 93}
            for field, value in controls.items():
                edits.append({"path": prefix + f"objectProperties/{slot}/" + field, "value": value})
        for slot in (0, 16):
            edits.extend([
                {"path": prefix + f"sceneTriggerMap/{slot}/triggerGroup", "value": 202},
                {"path": prefix + f"sceneTriggerMap/{slot}/actionSelector", "value": {"0": 11, "15": 22}},
            ])
    return edits


def capture(vendor_root: Path, java_home: Path) -> dict:
    app = vendor_root / "cgate/app"
    jar = app / "cgate.jar"
    source = Path(__file__).with_name("NativeDaliExtProxyProbe.java")
    jar_hash = hashlib.sha256(jar.read_bytes()).hexdigest()
    if jar_hash != PINNED_JAR:
        raise ValueError("Original C-Gate jar does not match the pinned 3.4.0.2001 artifact")
    with zipfile.ZipFile(jar) as archive:
        class_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in CLASSES}
    if any(class_hashes[name] != digest for name, digest in PINNED_CLASS_HASHES.items()):
        raise ValueError("An original class does not match the pinned artifact")
    classpath = f"{jar}:{app / 'lib/*'}"
    java = java_home / "bin/java"
    version = subprocess.run([str(java), "-version"], capture_output=True,
                             text=True, check=True, timeout=20)
    with tempfile.TemporaryDirectory(prefix="cbus-native-dali-proxy-") as temporary:
        # Only our class belongs on this directory's classpath. Extracting
        # obfuscated vendor classes here breaks Java's case-sensitive names
        # when the host filesystem is case-insensitive.
        subprocess.run([str(java_home / "bin/javac"), "-cp", classpath,
                        "-d", temporary, str(source)], capture_output=True,
                       text=True, check=True, timeout=60)
        if any(path.name != "NativeDaliExtProxyProbe.class" for path in Path(temporary).glob("*.class")):
            raise ValueError("The probe class directory contains an unexpected class")
        def execute(configuration):
            raw = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
            input_path = Path(temporary) / "input.json"
            input_path.write_bytes(raw)
            result = subprocess.run([str(java), "-cp", f"{temporary}:{classpath}",
                                     "NativeDaliExtProxyProbe", str(input_path)], capture_output=True,
                                    text=True, check=True, timeout=60)
            if len(result.stdout.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("Original probe output exceeds 2 MiB")
            original = json.loads(result.stdout)
            return {"input": configuration, "input_sha256": hashlib.sha256(raw).hexdigest(),
                    "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
                    "global_model_before": original["model_before"],
                    "global_model_staged": original["model_staged"],
                    "target_bytes": original["target_bytes"],
                    "dirty_chunks": original["dirty_chunks"],
                    "line_model_before": original["line_before"],
                    "line_model_staged": original["line_staged"]}
        four = execute({"default_current_byte": 0, "current_overrides": INPUT, "edits": EDITS})
        cases = {"four_family_reserved_bits": four}
        for high in (False, True):
            configuration = {"default_current_byte": 0,
                             "current_overrides": {"256": 2 if high else 0, "257": 9 if high else 0}, "edits": []}
            native_model = execute(configuration)["global_model_before"]
            configuration["edits"] = _global_edits(native_model, high)
            cases["all_globals_high" if high else "all_globals_low"] = execute(configuration)
            if high:
                physical = json.loads(json.dumps(configuration))
                # Retained restore-level controls are physically writable only
                # when their corresponding restore-to-previous flags are off.
                for edit in physical["edits"]:
                    if edit["path"].endswith("/restoreToPreviousLevel"):
                        edit["value"] = False
                cases["all_globals_physical"] = execute(physical)
        cases["all_line_families"] = execute({"default_current_byte": 0,
            "current_overrides": {"256": 1, "257": 6}, "edits": _line_edits()})
    return {
        "format": "cbus-dali-ext-proxy-original-vectors-v1",
        "original_version": "C-Gate 3.4.0.2001",
        "jar_sha256": jar_hash,
        "class_sha256": class_hashes,
        "probe_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "research_runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
        "javac_sha256": hashlib.sha256((java_home / "bin/javac").read_bytes()).hexdigest(),
        "java_version": version.stderr.strip().splitlines(),
        "input": {"default_current_byte": 0, "current_overrides": INPUT},
        "edits": EDITS,
        "expected_target_bytes": {address: four["target_bytes"][address]
                                  for address in ("512", "513", "514", "515", "518", "521", "556")},
        "stdout_sha256": four["stdout_sha256"],
        "cases": cases,
        "dirty_chunk_address_basis": "array index; add 256 for gateway extended address",
        "acceptance": {
            "original_classes_executed": True,
            "original_full_proxy_serializer_executed": True,
            "compared_scope": "21 global families, both DALI line mappings, all 15 line families; complete source image only",
            "cmqttd_policy": "serialize whole complete recalled proxy; preserve unmapped/excluded current bytes",
            "gateway_io": False,
            "toolkit_gui_executed": False,
            "physical_effect_verified": False,
            "persistence_verified": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = capture(args.vendor_root, args.java_home)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(document, output, indent=2, sort_keys=True)
        output.write("\n")


if __name__ == "__main__":
    main()
