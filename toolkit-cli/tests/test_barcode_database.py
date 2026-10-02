"""Fault boundaries for the loaded-project barcode adapter on a fake client."""
from dataclasses import replace
from types import SimpleNamespace
import json
import sys

import pytest

from cbus_toolkit import barcode_database as adapter
from cbus_toolkit.barcode_scanner import BarcodeCatalog
from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.project import ProjectDocument
from test_barcode_native_policy import oid, snapshot
from test_barcode_scanner import CATALOG_XML, CONFIG


def reply(text):
    return CGateResponse((text,), text, int(text[:3]))


def xml_reply(raw):
    lines = tuple("347-" + line for line in raw.decode("utf-8").splitlines()) + ("200 OK",)
    return CGateResponse(lines, lines[-1], 200)


@pytest.fixture
def prepared(tmp_path):
    path = tmp_path / "catalog.xml"
    path.write_text(CATALOG_XML, encoding="utf-8")
    return adapter.PreparedScan("LAB", "//LAB/Local", CONFIG, path,
                                BarcodeCatalog.load(path), None, None, True, None, None)


class FakeDatabase:
    def __init__(self, *, receipt=None, direct_edit=None, final_edit=None):
        self.before = snapshot()
        self.after = self.before
        self.oid = oid(9999)
        self.receipt = receipt or "301 OID=" + self.oid
        self.direct_edit = direct_edit
        self.final_edit = final_edit
        self.commands = []
        self.initializers = []
        self.unit = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def command(self, command):
        self.commands.append(command)
        if command == "PROJECT USE LAB":
            return reply("200 OK")
        if command == "DBGETXML //LAB":
            raw = self.after
            if self.unit is not None and self.final_edit:
                raw = self.final_edit(raw)
            return xml_reply(raw)
        if command.startswith("DBADDSAFE "):
            return reply(self.receipt)
        if command == "DBGETXML //LAB/Local/p/2":
            raw = self.unit or ("<Unit><OID>" + self.oid + "</OID></Unit>").encode("utf-8")
            if self.direct_edit:
                raw = self.direct_edit(raw)
            return xml_reply(raw)
        if command == "DBGET !" + self.oid + "/OID":
            return reply("342 !" + self.oid + "/OID=" + self.oid)
        if command.startswith("DBGET //LAB/Local/p/2/"):
            field = command.rsplit("/", 1)[1]
            value = self.oid if self.unit is None else adapter.minidom.parseString(self.unit).getElementsByTagName(field)[0].firstChild.data
            return reply("342 " + command[6:] + "=" + value)
        raise AssertionError(command)

    def command_document(self, command, document):
        self.initializers.append((command, document))
        self.unit = document.encode("utf-8")
        complete = ProjectDocument.from_bytes(self.before)
        network = complete.resolve("/network/Local")
        network.appendChild(complete.document.importNode(adapter.minidom.parseString(document).documentElement, True))
        self.after = complete.to_xml_bytes()
        return reply("301 OID=" + self.oid)


def test_complete_adapter_binds_identity_and_preserves_whole_project(prepared):
    fake = FakeDatabase()
    state = adapter._initial("apply")
    result, status = adapter.run(prepared, fake, state)
    assert status == 0 and result["accepted"] is True
    assert result["phase"] == "complete" and all(result["readback"].values())
    assert result["database_write"]["outcome_uncertain"] is False
    assert len(fake.initializers) == 1
    assert fake.commands.count("PROJECT USE LAB") == 1
    assert sum(command.startswith("DBADDSAFE ") for command in fake.commands) == 1
    assert not any(command.startswith(("PP ", "DBDELETE ", "PROJECT SAVE ")) for command in fake.commands)


@pytest.mark.parametrize("receipt", ["301 OID=" + oid(1000), "301 OID=" + oid(1000).upper(), "301 OID=bad"])
def test_unbound_or_reused_creation_receipt_never_initializes(prepared, receipt):
    fake = FakeDatabase(receipt=receipt)
    with pytest.raises(RuntimeError) as caught:
        adapter.run(prepared, fake, adapter._initial("apply"))
    state = caught.value.details["barcode_database_evidence"]
    assert state["phase"] == "create_identity"
    assert state["created"] is True and state["database_write"]["outcome_uncertain"] is True
    assert fake.initializers == []
    assert not any(command.startswith("DBDELETE") for command in fake.commands)


@pytest.mark.parametrize("edit", [
    lambda raw: raw.replace(b"</Unit>", b"<!--unexpected--></Unit>"),
    lambda raw: raw.replace(b"</Unit>", b"<?extra value?></Unit>"),
    lambda raw: raw.replace(b"</UnitName>", b"</UnitName>mixed text"),
    lambda raw: raw.replace(b"<Unit>", b"<Unit injected='yes'>"),
])
def test_direct_unit_readback_keeps_markup_and_mixed_text(prepared, edit):
    fake = FakeDatabase(direct_edit=edit)
    with pytest.raises(RuntimeError, match="New Unit XML differs") as caught:
        adapter.run(prepared, fake, adapter._initial("apply"))
    state = caught.value.details["barcode_database_evidence"]
    assert state["applied"] is True and state["accepted"] is False
    assert state["database_write"]["document_confirmed"] is True
    assert state["database_write"]["outcome_uncertain"] is False
    assert len(fake.initializers) == 1


def test_final_whole_project_rechecks_new_unit_fields(prepared):
    fake = FakeDatabase(final_edit=lambda raw: raw.replace(b"<UnitName>NEWUNIT</UnitName>", b"<UnitName>Changed</UnitName>"))
    with pytest.raises(RuntimeError, match="New Unit differs in whole-project") as caught:
        adapter.run(prepared, fake, adapter._initial("apply"))
    state = caught.value.details["barcode_database_evidence"]
    assert state["readback"]["unit_verified"] is True
    assert state["readback"]["scalars_verified"] is True
    assert state["readback"]["unrelated_project_preserved"] is False
    assert state["accepted"] is False


def test_final_project_rechecks_opaque_unrelated_data(prepared):
    fake = FakeDatabase(final_edit=lambda raw: raw.replace(b"opaque", b"changed"))
    with pytest.raises(RuntimeError, match="Unrelated project data changed"):
        adapter.run(prepared, fake, adapter._initial("apply"))
    assert len(fake.initializers) == 1


def test_login_echo_never_leaks_credential_in_operator_evidence(prepared):
    token = "synthetic-recovery-token"
    calls = []

    class Denied:
        def command(self, command):
            calls.append(command)
            raise CGateError(reply("401 Denied " + token))

    with pytest.raises(RuntimeError, match="Authentication did not complete") as caught:
        adapter.run(replace(prepared, auth_token=token), Denied(), adapter._initial("apply"))
    assert calls == ["LOGIN " + token]
    assert token not in str(caught.value)
    assert token not in repr(caught.value.details)
    assert caught.value.details["barcode_database_evidence"]["commands"] == ["LOGIN <redacted>"]


def test_connection_and_output_failures_retain_independent_evidence():
    args = SimpleNamespace(action="database", remote_action="barcode-add", apply=True)
    with pytest.raises(OSError) as caught:
        with adapter.connection_guard(args):
            raise OSError("Cannot connect")
    assert caught.value.details["barcode_database_evidence"]["database_write"]["add_attempted"] is False
    args._barcode_database_evidence["created"] = True
    args._barcode_database_evidence["phase"] = "complete"
    output = BrokenPipeError("output closed")
    adapter.record_output_error(args, output)
    args._barcode_database_evidence["created"] = False
    assert output.details["barcode_database_evidence"]["created"] is True
    assert output.details["barcode_database_evidence"]["failure_phase"] == "output"


def test_unit_parser_rejects_dtd_before_entity_expansion():
    raw = b'<!DOCTYPE Unit [<!ENTITY a "expanded">]><Unit><TagName>&a;</TagName></Unit>'
    with pytest.raises(ValueError, match="DTD"):
        adapter._unit_shape(raw)


@pytest.mark.skipif(not hasattr(adapter.os, "mkfifo"), reason="POSIX FIFO input guard")
def test_regular_file_check_cannot_block_on_a_fifo(tmp_path):
    path = tmp_path / "fifo"
    adapter.os.mkfifo(path)
    with pytest.raises(ValueError, match="regular file"):
        adapter._snapshot(path, 2048)


def cli_arguments(prepared):
    return ["cgate", "database", "barcode-add", prepared.network, "--project", "LAB",
            "--catalog", str(prepared.catalog_path), "--barcode", CONFIG,
            "--apply", "--exclusive-project"]


def test_public_main_output_loss_reports_confirmed_database_edit(prepared, monkeypatch, capsys):
    from cbus_toolkit import cgate, cli
    fake = FakeDatabase()
    monkeypatch.setattr(cgate, "CGateClient", lambda *_args, **_kwargs: fake)

    def closed_output(value, **kwargs):
        if kwargs.get("file") is sys.stderr:
            sys.stderr.write(value + "\n")
        else:
            raise BrokenPipeError("closed output")

    monkeypatch.setattr(cli, "print", closed_output, raising=False)
    assert cli.main(cli_arguments(prepared)) == 1
    value = json.loads(capsys.readouterr().err)
    state = value["barcode_database_evidence"]
    assert state["failure_phase"] == "output" and state["phase"] == "complete"
    assert state["created"] is True and state["applied"] is True and state["accepted"] is True
    assert state["database_write"]["document_confirmed"] is True
    assert len(fake.initializers) == 1


def test_public_main_cleanup_failure_reports_confirmed_database_edit(prepared, monkeypatch, capsys):
    from cbus_toolkit import cgate, cli

    class CleanupFailure(FakeDatabase):
        def __exit__(self, *_args):
            raise OSError("connection cleanup failed")

    fake = CleanupFailure()
    monkeypatch.setattr(cgate, "CGateClient", lambda *_args, **_kwargs: fake)
    assert cli.main(cli_arguments(prepared)) == 1
    state = json.loads(capsys.readouterr().err)["barcode_database_evidence"]
    assert state["failure_phase"] == "connection_cleanup" and state["phase"] == "complete"
    assert state["accepted"] is True and all(state["readback"].values())
    assert len(fake.initializers) == 1


@pytest.mark.parametrize("extra", ["unexpected row", "200-unexpected continued status"])
def test_scalar_readback_rejects_unaccounted_or_extra_reply_rows(prepared, extra):
    class InvalidScalar(FakeDatabase):
        def command(self, command):
            result = super().command(command)
            if command.endswith("/TagName"):
                lines = (result.final.replace("342 ", "342-", 1), extra, "200 OK")
                return CGateResponse(lines, lines[-1], 200)
            return result

    fake = InvalidScalar()
    with pytest.raises(RuntimeError, match="Expected one native database scalar reply") as caught:
        adapter.run(prepared, fake, adapter._initial("apply"))
    state = caught.value.details["barcode_database_evidence"]
    assert state["applied"] is True and state["accepted"] is False
    assert state["readback"]["scalars_verified"] is False
    assert len(fake.initializers) == 1


def test_numeric_scalar_continuation_and_terminal200_are_admitted(prepared):
    class NumericScalar(FakeDatabase):
        def command(self, command):
            result = super().command(command)
            if command.startswith("DBGET //"):
                lines = (result.final.replace("342 ", "342-", 1), "200 OK")
                return CGateResponse(lines, lines[-1], 200)
            return result

    result, status = adapter.run(prepared, NumericScalar(), adapter._initial("apply"))
    assert status == 0 and result["accepted"] is True


@pytest.mark.parametrize("invalid", ["KEY\tBL5", "KEY\u0085BL5"])
def test_catalogue_control_characters_refuse_before_scaffold_creation(prepared, invalid):
    catalog = BarcodeCatalog.from_snapshot(CATALOG_XML.replace("KEYBL5", invalid).encode("utf-8"))
    fake = FakeDatabase()
    with pytest.raises(ValueError, match="control characters"):
        adapter.run(replace(prepared, catalog=catalog), fake, adapter._initial("apply"))
    assert not any(command.startswith("DBADDSAFE") for command in fake.commands)
    assert fake.initializers == []


def test_untransmittable_unit_document_refuses_before_scaffold_creation(prepared):
    fake = FakeDatabase()
    scan = "5031NL          " + "1" * adapter.MAX_SCAN_CHARS
    with pytest.raises(ValueError, match="document limit"):
        adapter.run(replace(prepared, barcode=scan), fake, adapter._initial("apply"))
    assert not any(command.startswith("DBADDSAFE") for command in fake.commands)
    assert fake.initializers == []
