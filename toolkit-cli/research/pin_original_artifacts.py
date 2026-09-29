#!/usr/bin/env python3
"""Pin and verify private original Toolkit/C-Gate inputs without copying them.

The public manifest records only relative package locations, sizes, digests and
version facts. The supplied roots and all vendor bytes stay outside the repo.
It also pins the owned JDK and Mono runtimes that run the native and original
oracles, and proves that the decoded specifications are a byte-identical fresh
decode of the pinned encrypted originals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


FORMAT = "cbus-original-artifact-provenance-v1"
TARGET = "Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001"
EXPECTED_VERSIONS = {
    "toolkit": {"artifact": "toolkit-exe", "source": "PE fixed FileVersion", "value": "1.18.0.2754"},
    "cgate": {"artifact": "cgate-jar", "source": "JAR META-INF/MANIFEST.MF Implementation-Version", "value": "3.4.0_2001", "build_number": "2001"},
    "jre": {"artifact": "cgate-jre", "source": "bundled JRE release JAVA_RUNTIME_VERSION", "value": "11.0.24+8", "implementor": "Temurin-11.0.24+8"},
    "firmware_updater": {"artifact": "firmware-updater", "source": "PE fixed FileVersion", "value": "1.16.3.0"},
    "native_jdk": {"artifact": "native-jdk-release", "source": "owned JDK release JAVA_RUNTIME_VERSION", "value": "11.0.32.1+1", "implementor": "Temurin-11.0.32.1+1", "os_arch": "aarch64", "image_type": "JDK"},
    "native_mono": {"artifact": "native-mono-runtime", "source": "owned Mono framework VERSION file", "value": "6.12.0.206"},
}
# A fixed recipe prevents a missing or renamed input from silently disappearing
# from a freshly generated manifest. The flat binary selection excludes the
# installer's certificate/key and logging files in the same application folder.
ARTIFACTS = (
    ("toolkit-installer", "installer", "setup.exe", "file"),
    ("toolkit-exe", "installer", "extracted-20260926/app/CBusToolkit.exe", "file"),
    ("toolkit-map", "installer", "extracted-20260926/app/CBusToolkit.map", "file"),
    ("toolkit-binaries", "installer", "extracted-20260926/app", "flat-exe-dll"),
    ("toolkit-help-chm", "installer", "extracted-20260926/app/Toolkit Help.chm", "file"),
    ("toolkit-help-extracted", "installer", "help-20260926", "tree"),
    ("cgate-installer", "installer", "extracted-20260926/tmp/cgate-3.4.0_2001-JRE-11.0.24_8-setup.exe", "file"),
    ("cgate-launcher", "installer", "cgate-extracted-20260926/app/cgate.exe", "file"),
    ("cgate-jar", "installer", "cgate-extracted-20260926/app/cgate.jar", "file"),
    ("cgate-libraries", "installer", "cgate-extracted-20260926/app/lib", "tree"),
    ("cgate-jre", "installer", "cgate-extracted-20260926/app/openjdk_jre_11.0.24_8_x64", "tree"),
    ("cgate-encrypted-specs", "installer", "cgate-extracted-20260926/app/unitspec", "tree"),
    ("cgate-dali-catalogue", "installer", "cgate-extracted-20260926/app/dali_catalogue", "tree"),
    ("decoded-specs", "decoded_specs", ".", "tree"),
    ("firmware-updater", "installer", "extracted-20260926/app/FirmwareUpdater.exe", "file"),
    ("edlt-firmware", "installer", "extracted-20260926/app/Firmware/eDLTFirmware", "tree"),
    ("sesu-installer", "installer", "extracted-20260926/tmp/SESU_3.0.7_setup_sfx.exe", "file"),
    ("sesu-toolkit-config", "installer", "extracted-20260926/commoncf32/Schneider Electric Shared/Schneider Electric Software Update/Config/luSettingsC-Bus Toolkit.xml", "file"),
    # The owned native runner: CBUS_CGATE_JAVA/CBUS_CGATE_JAVAC are these
    # launchers, and research/release-gates/native.json pins the same digests.
    ("native-jdk-java", "native_jdk", "bin/java", "file"),
    ("native-jdk-javac", "native_jdk", "bin/javac", "file"),
    ("native-jdk-release", "native_jdk", "release", "file"),
    ("native-jdk-home", "native_jdk", ".", "tree"),
    # CBUS_MONO_MACOS_ROOT for the original FirmwareUpdater oracle. The Apple
    # package payload contains relative and absolute framework symlinks, which
    # are pinned by their literal targets and never followed.
    ("native-mono-launcher", "native_mono", "bin/mono-sgen64", "file"),
    ("native-mono-compiler", "native_mono", "lib/mono/4.5/mcs.exe", "file"),
    ("native-mono-runtime", "native_mono", ".", "tree-links"),
)
ROOTS = {
    "installer": "private extracted installer audit",
    "decoded_specs": "private decoded C-Gate unit specification directory",
    "native_jdk": "owned macOS Temurin JDK home (Contents/Home) used by the native gate",
    "native_mono": "owned macOS Mono framework version root used by the original firmware oracle",
}
DECODER = Path(__file__).with_name("decode_unitspec.py")
MANIFEST = Path(__file__).with_name("original-artifact-provenance.json")


class PinError(ValueError):
    pass


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PinError("Unsafe relative artifact path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", "..") for part in path.parts):
        raise PinError("Unsafe relative artifact path")
    return path


def _ordinary(path: Path, *, directory: bool) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise PinError("Required private input is absent") from error
    if (directory and not stat.S_ISDIR(mode)) or (not directory and not stat.S_ISREG(mode)):
        raise PinError("Private input must be an ordinary file or directory, without symlinks")


def _member(root: Path, relative: str, *, directory: bool) -> Path:
    _safe_relative(relative)
    _ordinary(root, directory=True)
    candidate = root
    for component in PurePosixPath(relative).parts:
        if component == ".":
            continue
        candidate = candidate / component
        _ordinary(candidate, directory=directory if candidate == root.joinpath(*PurePosixPath(relative).parts) else True)
    _ordinary(candidate, directory=directory)
    return candidate


def _sha_file(path: Path) -> tuple[int, str]:
    _ordinary(path, directory=False)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise PinError("Private input changed during hashing")
    return after.st_size, digest.hexdigest()


def _is_link(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except FileNotFoundError as error:
        raise PinError("Required private input is absent") from error


def _tree(path: Path, *, flat_binaries: bool = False, links: bool = False) -> dict[str, int | str]:
    """Digest a tree; with ``links``, record symlink targets without following them."""
    _ordinary(path, directory=True)
    files: list[Path] = []
    symlinks: list[Path] = []
    def traversal_error(_error: OSError) -> None:
        raise PinError("Cannot enumerate private artifact tree")

    for current, dirs, names in os.walk(path, followlinks=False, onerror=traversal_error):
        base = Path(current)
        if flat_binaries and base != path:
            raise PinError("Flat binary selector unexpectedly descended")
        for name in list(dirs):
            if links and _is_link(base / name):
                symlinks.append(base / name)
                dirs.remove(name)
            else:
                _ordinary(base / name, directory=True)
        if flat_binaries:
            dirs.clear()
        for name in names:
            candidate = base / name
            if links and _is_link(candidate):
                symlinks.append(candidate)
                continue
            _ordinary(candidate, directory=False)
            if not flat_binaries or (base == path and candidate.suffix.lower() in (".exe", ".dll")):
                files.append(candidate)
    if not files:
        raise PinError("Required private artifact tree is empty")
    lines: list[tuple[str, bytes]] = []
    total = 0
    for file in files:
        size, file_digest = _sha_file(file)
        total += size
        relative = file.relative_to(path).as_posix()
        lines.append((relative, relative.encode("utf-8") + b"\x00" + str(size).encode("ascii") + b"\x00" + file_digest.encode("ascii") + b"\n"))
    for link in symlinks:
        relative = link.relative_to(path).as_posix()
        lines.append((relative, relative.encode("utf-8") + b"\x00link\x00" + os.fsencode(os.readlink(link)) + b"\n"))
    lines.sort(key=lambda item: item[0])
    # Link-free trees keep the original v1 digest so earlier pins stay valid.
    digest = hashlib.sha256(b"cbus-original-artifact-tree-links-v1\n" if links else b"cbus-original-artifact-tree-v1\n")
    for _relative, line in lines:
        digest.update(line)
    result: dict[str, int | str] = {"file_count": len(files), "total_bytes": total, "sha256": digest.hexdigest()}
    if links:
        result["link_count"] = len(symlinks)
    return result


def _pe_version(path: Path) -> str:
    try:
        import pefile
    except ImportError as error:
        raise PinError("Install the Toolkit research extra to read PE version resources") from error
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        fixed = pe.VS_FIXEDFILEINFO
        if len(fixed) != 1:
            raise PinError("PE must contain exactly one fixed version resource")
        value = fixed[0]
        return ".".join(str(part) for part in (
            value.FileVersionMS >> 16, value.FileVersionMS & 0xffff,
            value.FileVersionLS >> 16, value.FileVersionLS & 0xffff,
        ))
    except (AttributeError, KeyError, pefile.PEFormatError) as error:
        raise PinError("Cannot read required PE fixed version resource") from error


def _jar_manifest_version(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        entry = archive.getinfo("META-INF/MANIFEST.MF")
        if entry.file_size > 64 * 1024:
            raise PinError("JAR manifest exceeds the bounded version input")
        raw = archive.read(entry).decode("utf-8")
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith(" "):
            if not fields:
                raise PinError("Malformed JAR manifest continuation")
            last = next(reversed(fields))
            fields[last] += line[1:]
        elif ": " in line:
            key, value = line.split(": ", 1)
            if key in fields:
                raise PinError("Duplicate JAR manifest field")
            fields[key] = value
    return fields.get("Implementation-Version", ""), fields.get("Build-Number", "")


def _jre_version(path: Path) -> tuple[str, str]:
    if path.stat().st_size > 64 * 1024:
        raise PinError("JRE release metadata exceeds the bounded version input")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip('"')
    return fields.get("JAVA_RUNTIME_VERSION", ""), fields.get("IMPLEMENTOR_VERSION", "")


def _release_fields(path: Path) -> dict[str, str]:
    if path.stat().st_size > 64 * 1024:
        raise PinError("Runtime release metadata exceeds the bounded version input")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip('"')
    return fields


def _mono_version(path: Path) -> str:
    if path.stat().st_size > 256:
        raise PinError("Mono VERSION metadata exceeds the bounded version input")
    return path.read_text(encoding="ascii").strip()


def _versions(roots: dict[str, Path]) -> dict[str, dict[str, str]]:
    installer = roots["installer"]
    toolkit = _member(installer, "extracted-20260926/app/CBusToolkit.exe", directory=False)
    cgate = _member(installer, "cgate-extracted-20260926/app/cgate.jar", directory=False)
    jre = _member(installer, "cgate-extracted-20260926/app/openjdk_jre_11.0.24_8_x64/release", directory=False)
    updater = _member(installer, "extracted-20260926/app/FirmwareUpdater.exe", directory=False)
    cgate_version, build = _jar_manifest_version(cgate)
    jre_version, implementor = _jre_version(jre)
    jdk = _release_fields(_member(roots["native_jdk"], "release", directory=False))
    mono = _mono_version(_member(roots["native_mono"], "VERSION", directory=False))
    observed = {
        "toolkit": {**EXPECTED_VERSIONS["toolkit"], "value": _pe_version(toolkit)},
        "cgate": {**EXPECTED_VERSIONS["cgate"], "value": cgate_version, "build_number": build},
        "jre": {**EXPECTED_VERSIONS["jre"], "value": jre_version, "implementor": implementor},
        "firmware_updater": {**EXPECTED_VERSIONS["firmware_updater"], "value": _pe_version(updater)},
        "native_jdk": {**EXPECTED_VERSIONS["native_jdk"], "value": jdk.get("JAVA_RUNTIME_VERSION", ""),
                       "implementor": jdk.get("IMPLEMENTOR_VERSION", ""), "os_arch": jdk.get("OS_ARCH", ""),
                       "image_type": jdk.get("IMAGE_TYPE", "")},
        "native_mono": {**EXPECTED_VERSIONS["native_mono"], "value": mono},
    }
    if observed != EXPECTED_VERSIONS:
        raise PinError("Original input version differs from the declared target")
    return observed


def _spec_alignment(roots: dict[str, Path]) -> dict[str, int | bool]:
    encoded = _member(roots["installer"], "cgate-extracted-20260926/app/unitspec", directory=True)
    decoded = _member(roots["decoded_specs"], ".", directory=True)
    encrypted = {entry.name[:-3] for entry in encoded.iterdir() if entry.name.endswith(".xml.es") and entry.is_file()}
    clear = {entry.name for entry in decoded.iterdir() if entry.name.endswith(".xml") and entry.is_file()}
    if len(encrypted) != 280 or encrypted != clear:
        raise PinError("Decoded specification names do not match the 280 encrypted originals")
    return {"encrypted_count": len(encrypted), "decoded_count": len(clear), "names_match": True}


def _spec_derivation(roots: dict[str, Path]) -> dict[str, object]:
    """Re-run the committed decoder and require a byte-identical decoded catalogue.

    The receipt binds each encrypted input digest to its decoded output digest
    without publishing names or content.
    """
    encoded = _member(roots["installer"], "cgate-extracted-20260926/app/unitspec", directory=True)
    decoded = _member(roots["decoded_specs"], ".", directory=True)
    _ordinary(DECODER, directory=False)
    with tempfile.TemporaryDirectory(prefix="cbus-unitspec-derivation-") as temporary:
        output = Path(temporary) / "decoded"
        result = subprocess.run([sys.executable, str(DECODER), str(encoded), str(output)],
                                capture_output=True, check=False)
        if result.returncode:
            raise PinError("Committed decoder could not authenticate and decode every encrypted specification")
        derived = _tree(output)
        if derived != _tree(decoded):
            raise PinError("Decoded specifications are not a byte-identical fresh decode of the encrypted originals")
        pairs = hashlib.sha256(b"cbus-unitspec-derivation-v1\n")
        names = sorted(entry.name for entry in output.iterdir())
        for name in names:
            _encrypted_size, encrypted_digest = _sha_file(encoded / (name + ".es"))
            _decoded_size, decoded_digest = _sha_file(decoded / name)
            pairs.update(encrypted_digest.encode("ascii") + b"\x00" + decoded_digest.encode("ascii") + b"\n")
    return {
        "decoder": "research/decode_unitspec.py",
        "decoder_sha256": _sha_file(DECODER)[1],
        "method": "AES-GCM authenticated fresh decode; byte-identical to decoded_specs",
        "decoded_count": len(names),
        "byte_identical": True,
        "pairs_sha256": pairs.hexdigest(),
    }


def collect(roots: dict[str, Path]) -> dict:
    records = []
    for artifact_id, root_id, relative, kind in ARTIFACTS:
        path = _member(roots[root_id], relative, directory=kind != "file")
        record: dict[str, object] = {"id": artifact_id, "root": root_id, "path": relative, "kind": kind}
        if kind == "file":
            record["size_bytes"], record["sha256"] = _sha_file(path)
        else:
            record.update(_tree(path, flat_binaries=kind == "flat-exe-dll", links=kind == "tree-links"))
        records.append(record)
    return {
        "format": FORMAT,
        "target": TARGET,
        "roots": dict(ROOTS),
        "versions": _versions(roots),
        "specification_alignment": _spec_alignment(roots),
        "specification_derivation": _spec_derivation(roots),
        "artifacts": records,
    }


def verify(manifest: dict, roots: dict[str, Path]) -> None:
    if type(manifest) is not dict or set(manifest) != {"format", "target", "roots", "versions", "specification_alignment", "specification_derivation", "artifacts"}:
        raise PinError("Invalid original artifact manifest schema")
    if manifest["format"] != FORMAT or manifest["target"] != TARGET:
        raise PinError("Original artifact manifest target changed")
    records = manifest["artifacts"]
    if type(records) is not list or len(records) != len(ARTIFACTS):
        raise PinError("Original artifact manifest recipe is incomplete")
    for actual, recipe in zip(records, ARTIFACTS, strict=True):
        if type(actual) is not dict or tuple(actual.get(key) for key in ("id", "root", "path", "kind")) != recipe:
            raise PinError("Original artifact manifest recipe changed")
        required = ({"id", "root", "path", "kind", "size_bytes", "sha256"} if recipe[3] == "file"
                    else {"id", "root", "path", "kind", "file_count", "total_bytes", "sha256"}
                    | ({"link_count"} if recipe[3] == "tree-links" else set()))
        if set(actual) != required or not re.fullmatch(r"[0-9a-f]{64}", str(actual["sha256"])):
            raise PinError("Original artifact manifest record is invalid")
    fresh = collect(roots)
    if fresh != manifest:
        mismatched = [a["id"] for a, b in zip(records, fresh["artifacts"], strict=True) if a != b]
        mismatched += [key for key in fresh if key != "artifacts" and manifest[key] != fresh[key]]
        raise PinError("Original artifact pin mismatch: " + ", ".join(mismatched))


def _strict_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PinError("Duplicate manifest key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(PinError("Non-finite manifest number")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("--installer-root", required=True, type=Path)
    parser.add_argument("--decoded-spec-dir", required=True, type=Path)
    parser.add_argument("--native-jdk-home", required=True, type=Path,
                        help="owned JDK home whose bin/java and bin/javac are CBUS_CGATE_JAVA/JAVAC")
    parser.add_argument("--native-mono-root", required=True, type=Path,
                        help="owned Mono.framework/Versions/6.12.0 root (CBUS_MONO_MACOS_ROOT)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args(argv)
    roots = {"installer": args.installer_root, "decoded_specs": args.decoded_spec_dir,
             "native_jdk": args.native_jdk_home, "native_mono": args.native_mono_root}
    try:
        if args.command == "create":
            result = collect(roots)
            args.manifest.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        else:
            verify(_strict_json(args.manifest), roots)
    except OSError:
        print("artifact pin failed: a private input could not be read", file=sys.stderr)
        return 1
    except (PinError, KeyError, zipfile.BadZipFile, UnicodeError) as error:
        print(f"artifact pin failed: {error}", file=sys.stderr)
        return 1
    print(f"artifact pin {args.command} passed: {len(ARTIFACTS)} artifacts; 280 decoded specifications "
          f"re-derived byte-identically; owned JDK and Mono runtimes; {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
