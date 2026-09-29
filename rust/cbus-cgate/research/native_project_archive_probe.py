#!/usr/bin/env python3
"""Capture C-Gate 3.4.0.2001 PROJECT ARCHIVE/RESTORE container formats.

One owned loopback child builds the same synthetic two-network project in the
default ``sqlite-file`` repository and in the legacy ``file`` (XML)
repository, then archives each one as ``.zip``, ``.gz`` and a raw copy. Every
archive is fetched through native ``FILE DOWNLOAD`` and checked against the
owned work directory. The committed report records container structure,
payload identity and schema facts; it never commits the Schneider SQLite
bytes or its DDL text. Host-specific InstallationDetail values and generated
OIDs/timestamps in the synthetic XML are normalized.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import socket
import sqlite3
import sys
from xml.etree import ElementTree as ET
import zipfile

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "toolkit-cli/research"))

from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402

SQLITE_MAGIC = b"SQLite format 3\x00"
EXTRA = '<x:Extra xmlns:x="urn:synthetic:extra">synthetic unknown metadata</x:Extra>'
OID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SYNTHETIC_OID = re.compile(r"^([0-9a-f])\1{7}-")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Session:
    def __init__(self, service: LocalCGate):
        self.peer = socket.create_connection(("127.0.0.1", service.port), timeout=10)
        self.peer.settimeout(60)
        self.stream = self.peer.makefile("rwb", buffering=0)
        self.greeting = self.stream.readline().decode().rstrip("\r\n")
        assert self.greeting.startswith(
            "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
        ), self.greeting
        self.tag = 100
        self.rows: list[dict] = []

    def close(self) -> None:
        self.peer.close()

    def call(self, command: str, document: str | None = None, *, record: bool = True) -> list[str]:
        self.tag += 1
        tag = self.tag
        request = f"[{tag}] {command}"
        if document is not None:
            request += f" << END{tag}\r\n{document}\r\nEND{tag}"
        self.stream.write((request + "\r\n").encode())
        lines = []
        final = re.compile(rf"^\[{tag}\] \d{{3}} ")
        while True:
            line = self.stream.readline().decode()
            if not line:
                raise EOFError(command)
            lines.append(line.rstrip("\r\n"))
            if final.match(lines[-1]):
                break
        if record:
            self.rows.append({"command": command, "response": [strip(line, tag) for line in lines]})
        return [strip(line, tag) for line in lines]

    def expect(self, command: str, final: str, document: str | None = None) -> list[str]:
        lines = self.call(command, document)
        assert lines[-1] == final, (command, lines)
        return lines

    def xml(self, command: str) -> str:
        lines = self.call(command, record=False)
        assert lines[-1].startswith("344 "), (command, lines)
        return "".join(line[4:] for line in lines if line.startswith("347-")).split("\n", 1)[-1]

    def download(self, path: str) -> bytes:
        lines = self.call(f"FILE DOWNLOAD {path}", record=False)
        assert lines[0].startswith("345-"), lines[:2]
        assert lines[-1].startswith("346 "), lines[-1]
        return base64.b64decode("".join(line[4:] for line in lines if line.startswith("347-")))


def strip(line: str, tag: int) -> str:
    return line.removeprefix(f"[{tag}] ")


def network_document(session: Session, project: str, address: int, name: str) -> None:
    session.call(f"DBCREATENET {address} {name} Cni 127.0.0.1:{address}")
    baseline = ET.fromstring(session.xml(f"DBGETXML //{project}/{address}"))
    network_oid = baseline.findtext("OID")
    interface_oid = baseline.findtext("Interface/OID")
    document = (
        f"<Network><OID>{network_oid}</OID><TagName>{name}</TagName><Address>{address}</Address>"
        f"<NetworkNumber>{address}</NetworkNumber><Interface><OID>{interface_oid}</OID>"
        f"<InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:{address}</InterfaceAddress></Interface>"
        f"<Unit><OID>11111111-1111-4111-8111-111111111{address}</OID><TagName>Bedroom {address}</TagName>"
        "<Address>20</Address><UnitType>KEYE1</UnitType><CatalogNumber>5031N</CatalogNumber>"
        '<SerialNumber>123.4</SerialNumber><PP Name="UnitAddress" Value="20"/>'
        f'<PP Name="Project" Value="{project}"/><UnitName>Room</UnitName>'
        f"<FirmwareVersion>1.2.67</FirmwareVersion>{EXTRA}</Unit>"
        f"<Application><OID>22222222-2222-4222-8222-222222222{address}</OID><TagName>Lighting</TagName>"
        f"<Address>56</Address><Group><OID>33333333-3333-4333-8333-333333333{address}</OID>"
        "<TagName>Kitchen</TagName><Address>1</Address><TagsDLT><TagDLT>"
        f"<OID>44444444-4444-4444-8444-444444444{address}</OID><LanguageID>1</LanguageID>"
        "<FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Synthetic label</TagValue>"
        "</TagDLT></TagsDLT></Group></Application></Network>"
    )
    reply = session.call(f"DBSETXML //{project}/{address}", document)
    assert reply[-1].startswith("301 OID="), reply


def build_project(session: Session, project: str) -> dict:
    session.expect(f"PROJECT NEW {project}", "200 OK.")
    session.expect(f"PROJECT USE {project}", "200 OK.")
    network_document(session, project, 254, "Local")
    network_document(session, project, 253, "Second")
    readback = {str(address): session.xml(f"DBGETXML //{project}/{address}") for address in (254, 253)}
    return {
        "readback_before_save": {key: normalize_xml(value) for key, value in readback.items()},
        "unknown_namespaced_unit_metadata_retained": any("urn:synthetic:extra" in value for value in readback.values()),
    }


def normalize_xml(text: str) -> str:
    """Replace native-generated OIDs, timestamps and host facts."""
    names: dict[str, str] = {}

    def oid(match: re.Match[str]) -> str:
        value = match[0]
        if SYNTHETIC_OID.match(value):
            return value
        return names.setdefault(value, f"<generated-oid-{len(names) + 1}>")

    text = OID.sub(oid, text)
    text = re.sub(r"<Modified>[^<]*</Modified>", "<Modified><timestamp></Modified>", text)
    for field in ("Hostname", "OSName", "OSVersion"):
        text = re.sub(rf"<{field}>[^<]*</{field}>", f"<{field}><host></{field}>", text)
    return text


def zip_facts(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        entries = []
        for info in infos:
            payload = archive.read(info)
            entries.append({
                "name": info.filename,
                "compress_type": {zipfile.ZIP_DEFLATED: "deflated", zipfile.ZIP_STORED: "stored"}.get(info.compress_type, info.compress_type),
                "compressed_size": info.compress_size,
                "uncompressed_size": info.file_size,
                "data_descriptor_flag": bool(info.flag_bits & 0x08),
                "encrypted": bool(info.flag_bits & 0x01),
                "create_system": info.create_system,
                "create_version": info.create_version,
                "extract_version": info.extract_version,
                "extra_length": len(info.extra),
                "comment_length": len(info.comment),
                "crc_verified": (zipfile.crc32(payload) & 0xFFFFFFFF) == info.CRC,
                "payload_magic": payload_kind(payload),
                "payload_sha256": sha256(payload),
            })
        return {"archive_bytes": len(data), "comment_length": len(archive.comment), "entries": entries}


def gzip_facts(data: bytes) -> dict:
    payload = gzip.decompress(data)
    return {
        "archive_bytes": len(data),
        "header_hex": data[:10].hex(),
        "magic": data[:2].hex(),
        "method": data[2],
        "flags": data[3],
        "mtime": int.from_bytes(data[4:8], "little"),
        "xfl": data[8],
        "os": data[9],
        "isize": int.from_bytes(data[-4:], "little"),
        "members": 1,
        "payload_magic": payload_kind(payload),
        "payload_sha256": sha256(payload),
    }


def payload_kind(payload: bytes) -> str:
    if payload.startswith(SQLITE_MAGIC):
        return "sqlite"
    if payload.lstrip().startswith(b"<?xml"):
        return "xml"
    return "other"


def schema_facts(path: Path) -> dict:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        def scalar(sql: str):
            return connection.execute(sql).fetchone()[0]

        master = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = [name for kind, name, _, _ in master if kind == "table" and not name.startswith("sqlite_")]
        columns = {
            table: [
                {"name": row[1], "type": row[2], "not_null": bool(row[3]), "primary_key": bool(row[5])}
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            for table in tables
        }
        counts = {table: scalar(f'SELECT count(*) FROM "{table}"') for table in tables}
        schema_sql = "\n".join(sql for _, _, _, sql in master if sql)
        return {
            "sqlite_magic": path.read_bytes()[:16] == SQLITE_MAGIC,
            "user_version": scalar("PRAGMA user_version"),
            "application_id": scalar("PRAGMA application_id"),
            "page_size": scalar("PRAGMA page_size"),
            "encoding": scalar("PRAGMA encoding"),
            "journal_mode": scalar("PRAGMA journal_mode"),
            "migrations": [
                {"version": row[0], "filename": row[1], "hash": row[2]}
                for row in connection.execute("SELECT version, filename, hash FROM _schema ORDER BY version")
            ],
            "object_counts": {
                kind: sum(1 for row in master if row[0] == kind) for kind in ("table", "index", "trigger", "view")
            },
            "schema_sql_sha256": sha256(schema_sql.encode()),
            "schema_sql_committed": False,
            "tables": columns,
            "nonempty_tables": {table: count for table, count in counts.items() if count},
        }
    finally:
        connection.close()


def capture(vendor: Path, java: Path) -> dict:
    service = LocalCGate(vendor, java=java)
    report: dict = {}
    with service:
        session = Session(service)
        try:
            archived = service.work / "Projects/archived"
            sqlite_setup = build_project(session, "XARC")
            session.expect("PROJECT SAVE XARC", "200 OK.")
            project_file = service.work / "Projects/XARC/XARC.db"
            saved = project_file.read_bytes()
            default_zip = session.call("CONFIG GET tag-use-zip")
            archives: dict[str, bytes] = {}
            for name in ("no.zip", "no.gz", "no.db", "case.Zip", "sub/nested.zip", "no.ZIP2"):
                session.expect(f"PROJECT ARCHIVE XARC {name}", "200 OK.")
            # Archive both settings from one unchanged saved file so any
            # payload difference could only come from tag-use-zip.
            session.expect("CONFIG SET tag-use-zip yes", "200 OK.")
            for name in ("yes.zip", "yes.gz", "yes.db"):
                session.expect(f"PROJECT ARCHIVE XARC {name}", "200 OK.")
            session.expect("PROJECT SAVE XARC", "200 OK.")
            resaved_magic = payload_kind(project_file.read_bytes())
            session.call("DBSAVE")
            session.expect("CONFIG SET tag-use-zip no", "200 OK.")
            session.call("PROJECT ARCHIVE XARC no.zip")
            for name in ("no.zip", "no.gz", "no.db", "case.Zip", "sub/nested.zip", "no.ZIP2", "yes.zip", "yes.gz", "yes.db"):
                archives[name] = session.download(f"Projects/archived/{name}")
                assert archives[name] == (archived / name).read_bytes(), name
            session.call("FILE SHA256 Projects/archived/no.zip")
            for command in (
                "PROJECT RESTORE XR1 no.zip",
                "PROJECT RESTORE XR2 no.gz",
                "PROJECT RESTORE XR3 no.db",
                "PROJECT RESTORE XR1 no.zip",
                "PROJECT RESTORE XARC no.zip",
                "PROJECT RESTORE XR9 missing.zip",
            ):
                session.call(command)
            restored_identical = {
                name: (service.work / f"Projects/{name}/{name}.db").read_bytes() == archives["no.db"]
                for name in ("XR1", "XR2", "XR3")
            }
            session.expect("PROJECT LOAD XR1", "200 OK.")
            session.expect("PROJECT USE XR1", "200 OK.")
            sqlite_restored = {
                str(address): normalize_xml(session.xml(f"DBGETXML //XR1/{address}")) for address in (254, 253)
            }
            original_readback = {
                str(address): session.xml(f"DBGETXML //XARC/{address}") for address in (254, 253)
            }
            restored_raw = {
                str(address): session.xml(f"DBGETXML //XR1/{address}") for address in (254, 253)
            }
            for command in ("PROJECT CLOSE XR1", "PROJECT CLOSE XARC"):
                session.expect(command, "200 OK.")
            schema = schema_facts(archived / "no.db")

            session.expect("REPOSITORY USE 2", "200 OK.")
            session.call("REPOSITORY LIST")
            file_setup = build_project(session, "XFILE")
            session.expect("PROJECT SAVE XFILE", "200 OK.")
            xml_project = (service.work / "Projects/XFILE.xml").read_bytes()
            for name in ("f.zip", "f.gz", "f.xml"):
                session.expect(f"PROJECT ARCHIVE XFILE {name}", "200 OK.")
                archives[name] = session.download(f"Projects/archived/{name}")
                assert archives[name] == (archived / name).read_bytes(), name
            for command in ("PROJECT RESTORE XF1 f.zip", "PROJECT RESTORE XF2 f.gz", "PROJECT RESTORE XS1 no.zip"):
                session.call(command)
            session.expect("PROJECT LOAD XF1", "200 OK.")
            session.expect("PROJECT USE XF1", "200 OK.")
            file_restored = {
                str(address): normalize_xml(session.xml(f"DBGETXML //XF1/{address}")) for address in (254, 253)
            }
            for command in ("PROJECT CLOSE XF1", "PROJECT CLOSE XFILE"):
                session.expect(command, "200 OK.")
            session.expect("REPOSITORY USE 1", "200 OK.")
            session.call("PROJECT RESTORE XS2 f.zip")
            greeting = session.greeting
            rows = session.rows
        finally:
            session.close()

    assert service.report["listener_ownership_verified"]
    assert service.report["cleanup_complete"]
    sqlite_payload = gzip.decompress(archives["no.gz"])
    report = {
        "schema": "native-cgate-project-archive-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "version": "3.4.0 build 2001",
            "greeting": greeting,
            "jar_sha256": JAR_SHA256,
            "java_sha256": sha256(java.read_bytes()),
            "harness_sha256": sha256((REPOSITORY / "toolkit-cli/research/local_cgate.py").read_bytes()),
            "capture_script_sha256": sha256(Path(__file__).read_bytes()),
            "physical_endpoint": False,
            "listeners_owned": service.report["listener_ownership_verified"],
            "process_exit_confirmed": service.report["process_exit_confirmed"],
            "cleanup_complete": service.report["cleanup_complete"],
            "work_removed": service.report["work_removed"],
        },
        "scope": (
            "Owned loopback C-Gate; synthetic two-network project; sqlite-file and file "
            "repositories. Private SQLite bytes and DDL are not committed."
        ),
        "source_setup": {"sqlite_file": sqlite_setup, "file": file_setup},
        "archive_directory": {
            "config_key": "project.default.archive-dir",
            "relative_root": "Projects/archived/",
            "subdirectories_created": True,
            "suffix_rule": "case-insensitive trailing .zip selects ZIP, .gz selects GZIP, anything else is a raw copy",
        },
        "tag_use_zip": {
            "default_reply": default_zip,
            "project_file_after_yes_and_save": resaved_magic,
            "archive_payload_identical": {
                kind: payload_identity(archives[f"no.{kind}"], archives[f"yes.{kind}"], kind)
                for kind in ("zip", "gz", "db")
            },
            "disposition": "No observable effect on PROJECT SAVE or PROJECT ARCHIVE containers or payloads.",
        },
        "sqlite_file_repository": {
            "project_file_magic": payload_kind(saved),
            "project_file_bytes": len(saved),
            "zip": zip_facts(archives["no.zip"]),
            "gzip": gzip_facts(archives["no.gz"]),
            "raw": {"payload_magic": payload_kind(archives["no.db"]), "identical_to_project_file": archives["no.db"] == saved},
            "uppercase_zip_suffix_is_zip": zipfile.is_zipfile(io.BytesIO(archives["case.Zip"])),
            "nested_directory_zip_identical": archives["sub/nested.zip"][30:38] == b"tagdb.db",
            "other_suffix_is_raw_copy": archives["no.ZIP2"] == saved,
            "payload_sha256_matches_project_file": sha256(sqlite_payload) == sha256(saved),
            "restored_project_files_identical": restored_identical,
            "restored_readback": sqlite_restored,
            "restored_oids_preserved": all(
                set(OID.findall(original_readback[key])) == set(OID.findall(restored_raw[key]))
                for key in original_readback
            ),
            "schema": schema,
        },
        "file_repository": {
            "project_file_magic": payload_kind(xml_project),
            "zip": zip_facts(archives["f.zip"]),
            "gzip": gzip_facts(archives["f.gz"]),
            "raw": {"payload_magic": payload_kind(archives["f.xml"]), "identical_to_project_file": archives["f.xml"] == xml_project},
            "payload_xml": normalize_xml(xml_project.decode("utf-8")),
            "restored_readback": file_restored,
        },
        "exchanges": [
            {"command": row["command"], "response": [sanitize(line) for line in row["response"]]}
            for row in rows
        ],
    }
    return report


def payload_identity(first: bytes, second: bytes, kind: str) -> bool:
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(first)) as a, zipfile.ZipFile(io.BytesIO(second)) as b:
            return [i.filename for i in a.infolist()] == [i.filename for i in b.infolist()] and a.read("tagdb.db") == b.read("tagdb.db")
    if kind == "gz":
        return gzip.decompress(first) == gzip.decompress(second)
    return first == second


def sanitize(line: str) -> str:
    line = re.sub(r"(/private)?/(var|tmp)/[^ ]*cbus-owned-native-[^/ ]+", "<owned-work>", line)
    line = re.sub(r"modified=.*$", "modified=<timestamp>", line)
    line = re.sub(r"OID=[0-9a-f-]{36}", "OID=<generated>", line)
    return re.sub(r"SHA256Hash=[0-9a-f]{64}", "SHA256Hash=<archive-sha256>", line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"exchanges": len(result["exchanges"]), "cleanup": result["oracle"]["cleanup_complete"]}))
