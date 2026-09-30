"""Version-comparator half of ``probe_sesu_trust_policy.py``.

Builds owned library files whose Win32 version resource holds selected text,
runs ``NativeSesuVersionProbe.cs`` and writes the committed vector fixture.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent

COMPONENTS = ("0", "1", "2", "01", "007", "10", "65535", "2147483647", "2147483648", "4294967296",
              "99999999999", "-0", "-1", "+1", "+0", " 1", "1 ", "\t1", "1\n", "a", "1a", "0x1", "",
              "١", "１", " 1", "1 ", "1_0", "1e2", "+", "-", " ", " 1", "\v1", "1\r")


def strings():
    """Deterministic matrix of whole strings and structured two-to-five-part forms."""
    values = ["", " ", "1", "1.", ".1", "1..2", "1.2.", "1.2.3.4.", "1.2.3.4.5", "1,2", "1.2.3.4 5", "v1.2",
              "1.18.0.2754", "1.18.0", "1.18", "1.18.1.2774", "3.4.0.2001", "0.0", "0.0.0.0",
              " 1.2", "1.2 ", " 1.2 ", "1 .2", "1. 2", "\t1.2", "1.2\n", "\r\n1.2\r\n", "+1.2", "1.+2",
              "-1.2", "1.-2", "-0.0", "+0.+0", "- 0.0", "+ 1.2", "1.2.3.-0", "1.2.3.+4",
              "2147483647.2147483647.2147483647.2147483647", "2147483648.0", "1.2147483648",
              "00000000000000000001.2", "1.2.3.00000000000000000004", "١.٢", "１.２",
              " 1.2", "1.2 ", " 1.2", "1.2\u0000", "\u00001.2", "0x1.2", "1e2.3", "(1).2",
              "1.2.3.4.5.6", "1.2.3.4..", "1.2.3.4.5 ", "1.2", "1.2。"]
    for component in COMPONENTS:
        values.extend([component + ".0", "0." + component, "1.2." + component, "1.2.3." + component])
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


RIGHTS = ("1.2.3.4", "1.2.3.5", "1.2.3.3", "1.2", "1.2.3", "1.2.0", "1.2.3.4.5", "01.002.3", "1.18.0.2754",
          "1.18.0.2755", "1.19", " 1.2.3 ", "+1.2", "-0.1", "1", "abc", "", "1.2.3.4a", "0.0.0.0", "2147483648.1")
HOWS = (1, 2, 10, 11, 12, 13, 14, 15, 16, 17)
FILE_VERSIONS = ("1.2.3.4", "1.2", " 1.2.3 ", "01.002.3", "+1.2", "1.18.0.2754", "abc")


def build_files(destination, mono, env):
    files = []
    for index, text in enumerate(FILE_VERSIONS, 1):
        source = destination / f"version-{index}.cs"
        source.write_text(f'[assembly: System.Reflection.AssemblyFileVersion({json.dumps(text)})]\nclass V{index} {{}}\n')
        output = destination / f"version-{index}.dll"
        subprocess.run([str(mono / "bin/mono-sgen64"), str(mono / "lib/mono/4.5/mcs.exe"), "-target:library",
                        "-out:" + str(output), str(source)], env=env, check=True, capture_output=True, timeout=120)
        files.append({"label": f"resource:{text}", "path": str(output), "resource_text": text})
    plain = destination / "no-version-resource.txt"
    plain.write_text("owned file without a version resource\n")
    files.append({"label": "no-version-resource", "path": str(plain), "resource_text": None})
    files.append({"label": "missing-file", "path": str(destination / "missing.dll"), "resource_text": None})
    return files


def run(args, destination: Path, assembly_hashes, run_probe):
    from probe_sesu_trust_policy import mono_environment, sha
    destination.mkdir(parents=True)
    mono, _, _, env = mono_environment(args.runtime)
    files = build_files(destination, mono, env)
    plan = {"strings": strings(), "rights": list(RIGHTS), "hows": list(HOWS), "files": files}
    plan_path = destination / "plan.json"
    plan_path.write_text(json.dumps(plan))
    probe = HERE / "NativeSesuVersionProbe.cs"
    report, lines = run_probe(args.runtime, destination, probe, "NativeSesuVersionProbe", lambda _port: [str(plan_path)])
    labels = {row["label"]: row for row in files}
    observed = {}
    parse, compare, original = [], [], []
    for line in lines:
        stage = line.get("stage")
        if stage == "runtime-version-parse":
            parse.append({"text": line["text"], "parsed": line["parsed"]})
        elif stage == "runtime-version-compare":
            compare.append([line["left"], line["right"], line["result"]])
        elif stage == "original-file-fixture":
            observed[line["label"]] = {"exists": line["exists"], "observed_file_version": line["observed_file_version"]}
        elif stage == "original-file-version":
            row = {"file": line["file"], "right": line["right"], "how": line["how"]}
            if "error" in line:
                row.update(error=line["error"], message=line["message"].replace("'probe'", "'<name>'"))
            else:
                row["result"] = line["result"]
            original.append(row)
    fixture = {
        "format": "cbus-toolkit-update-version-vectors-v1",
        "scope": ("Unchanged SESU 3.0.7 ClientConditionChecker.EvaluateFileVersion (SE.DAD.SESU.Common RVA 0x26A8) "
                  "on owned Mono 6.12 over runner-built version-resource files, plus the same runtime's "
                  "System.Version.TryParse/CompareTo that it calls. Windows .NET Framework was not run."),
        "original_assembly_sha256": assembly_hashes,
        "se_dad_sesu_common_sha256": sha((args.runtime / "toolkit-update-check/sesu-files/se.dad.sesu.common.dll").read_bytes()),
        "probe_source_sha256": sha(probe.read_bytes()),
        "generator_source_sha256": sha(Path(__file__).read_bytes()),
        "run_report": report,
        "private_run_directory": str(destination.relative_to(args.runtime)),
        "files": [{"label": label, "resource_text": labels[label]["resource_text"], **observed[label]} for label in observed],
        "runtime_parse": parse,
        "runtime_compare": compare,
        "original_file_version": original,
    }
    (args.out_dir / "toolkit-update-version-vectors.json").write_text(json.dumps(fixture, indent=0, ensure_ascii=True) + "\n")
