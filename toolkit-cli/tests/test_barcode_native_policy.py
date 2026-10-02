"""Pure barcode policy on synthetic complete native project snapshots."""
import hashlib
from xml.sax.saxutils import escape

import pytest

from cbus_toolkit.barcode_scanner import (
    BarcodeCatalog, BarcodeError, add_unit, plan_add_unit, plan_native_add_unit,
)
from cbus_toolkit.project import ProjectDocument
from test_barcode_scanner import CATALOG_XML, CONFIG, PROJECT_XML, unit as catalog_unit


def oid(number):
    return f"00000000-0000-4000-8000-{number:012x}"


def native_unit(address, *, serial="", kind="KEYE1", object_id=None, extra=""):
    identity = oid(address + 1) if object_id is None else object_id
    return (f"<Unit><Address>{address}</Address><TagName>Unit {address}</TagName>"
            f"<OID>{identity}</OID><UnitType>{kind}</UnitType>"
            f"<SerialNumber>{escape(serial)}</SerialNumber><FirmwareVersion>1.0.00</FirmwareVersion>"
            f"<UnitName>Existing</UnitName>{extra}</Unit>")


def network(address="Local", units=(), *, number=11, extra=""):
    return (f"<Network><Address>{address}</Address><TagName>Local &amp; Test</TagName>"
            f"<OID>{oid(1000 + number)}</OID><NetworkNumber>{number}</NetworkNumber>"
            + "".join(units) + extra + "</Network>")


def snapshot(networks=None, *, project_root=False):
    networks = networks if networks is not None else [network(units=[native_unit(1), native_unit(3)])]
    project = (f"<Project><Address>LAB</Address><TagName>Policy fixture</TagName><OID>{oid(1000)}</OID>"
               + "".join(networks) + "<Unknown keep='yes'><Nested>opaque</Nested></Unknown></Project>")
    text = project if project_root else "<Installation><DBVersion>2.3</DBVersion>" + project + "</Installation>"
    return text.encode("utf-8")


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.xml"
    path.write_text(CATALOG_XML, encoding="utf-8")
    return BarcodeCatalog.load(path)


def test_catalogue_snapshot_binds_exact_bytes_and_preserves_load_behavior(tmp_path):
    raw = CATALOG_XML.encode("utf-8")
    path = tmp_path / "catalog.xml"
    path.write_bytes(raw)
    parsed = BarcodeCatalog.from_snapshot(raw)
    loaded = BarcodeCatalog.load(path)
    assert parsed.types == loaded.types and parsed.sha256 == loaded.sha256 == hashlib.sha256(raw).hexdigest()
    # Semantically irrelevant formatting is still part of the consumed input.
    reformatted = b"\n" + raw + b"\n"
    path.write_bytes(reformatted)
    assert parsed.sha256 == hashlib.sha256(raw).hexdigest()
    reloaded = BarcodeCatalog.load(path)
    assert reloaded.types == parsed.types and reloaded.sha256 == hashlib.sha256(reformatted).hexdigest()
    assert reloaded.sha256 != parsed.sha256
    assert parsed.find("SC5031NL").unit_code == "KEYBL5" and parsed.default_firmware("keybl5") == "1.2.00"


@pytest.mark.parametrize("raw", [b"", b"<broken", b"<Other/>", "<CBusUnits/>", bytearray(b"<CBusUnits/>")])
def test_catalogue_snapshot_refuses_malformed_xml_wrong_root_and_mutable_input(raw):
    with pytest.raises(BarcodeError) as caught:
        BarcodeCatalog.from_snapshot(raw)
    assert caught.value.details["code"] == "invalid_catalog"


def test_native_creation_is_pure_and_has_native_fields(catalog):
    raw = snapshot()
    result = plan_native_add_unit(raw, "//LAB/Local", CONFIG, catalog, tag_name="Hall & Café")
    assert (result["action"], result["changed"], result["would_change"]) == ("add", False, True)
    assert (result["project"], result["network"], result["unit"]) == ("LAB", "//LAB/Local", "//LAB/Local/p/2")
    assert (result["automatic_address"], result["address"], result["tag_name"]) == (2, 2, "Hall & Café")
    assert result["fields"] == {
        "UnitType": "KEYBL5", "SerialNumber": "12345678.9012", "CatalogNumber": "5031NL",
        "FirmwareVersion": "1.2.00", "UnitName": "NEWUNIT",
    }
    assert result["snapshot_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["catalog_sha256"] == catalog.sha256
    assert "oid" not in result and result["warnings"] == []
    assert raw == snapshot()
    document = ProjectDocument.from_bytes(raw)
    before = document.to_xml_bytes()
    assert plan_add_unit(document, "/network/Local", CONFIG, catalog)["fields"] == result["fields"]
    assert document.to_xml_bytes() == before
    # The offline editor still owns its legacy State field and result shape.
    applied = add_unit(document, "/network/Local", CONFIG, catalog)
    assert applied["action"] == "added" and applied["changed"] is True
    assert "would_change" not in applied and applied["fields"]["State"] == "New"


def test_existing_minimal_safe_unit_is_counted_without_requiring_replacement_fields(catalog):
    minimal = f"<Unit><Address>4</Address><TagName>Minimal</TagName><OID>{oid(4)}</OID><UnitName>Existing</UnitName></Unit>"
    raw = snapshot([network(units=[native_unit(1), native_unit(3), minimal],
                            extra="<UnknownUnitMetadata preserve='yes'/>")])
    result = plan_native_add_unit(raw, "//LAB/Local", CONFIG, catalog)
    assert result["address"] == 2 and result["fields"]["UnitType"] == "KEYBL5"
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(raw, "//LAB/Local", "5031RDTSL       123456789012", catalog)
    assert caught.value.details["code"] == "wireless_unit_on_wired_network"
    assert raw == snapshot([network(units=[native_unit(1), native_unit(3), minimal],
                                   extra="<UnknownUnitMetadata preserve='yes'/>")])


@pytest.mark.parametrize("project_root", [False, True])
def test_native_normalization_preserves_independent_network_names(catalog, project_root):
    raw = snapshot([network("011"), network("11"), network("+11")], project_root=project_root)
    for selected in ("011", "11", "+11"):
        result = plan_native_add_unit(raw, "//LAB/" + selected, CONFIG, catalog)
        assert result["network"] == "//LAB/" + selected
        assert result["unit"] == "//LAB/" + selected + "/p/1"
    assert raw == snapshot([network("011"), network("11"), network("+11")], project_root=project_root)


def test_duplicate_selection_uses_project_xml_order_before_catalogue_and_dialog(catalog):
    first = native_unit(9, serial="990001.2", object_id=oid(90))
    later = native_unit(1, serial="00990001.0002", object_id=oid(10))
    raw = snapshot([network("Zed", [first]), network("Local", [later])])
    result = plan_native_add_unit(raw, "//LAB/Local", "UNKNOWN         009900010002", catalog,
                                  address=999, tag_name="ignored\x01")
    assert (result["action"], result["unit"], result["oid"]) == ("selected_existing", "//LAB/Zed/p/9", oid(90))
    assert result["duplicate_serial"] is True and result["would_change"] is False
    assert result["warnings"] == [] and "fields" not in result and "address" not in result
    serial = plan_native_add_unit(raw, "//LAB/Local", "009900010002", catalog)
    assert serial["unit"] == result["unit"] and serial["oid"] == result["oid"]
    assert serial["serial_lookup"]["found"] == "//LAB/Zed/p/9"


def test_second_serial_branch_sees_conceptual_created_unit(tmp_path):
    path = tmp_path / "zero-catalog.xml"
    path.write_text("<CBusUnits><Units>" + catalog_unit("0", "SENS") + "</Units></CBusUnits>")
    catalog = BarcodeCatalog.load(path)
    scan = "0               7           "
    raw = snapshot()
    result = plan_native_add_unit(raw, "//LAB/Local", scan, catalog)
    assert result["action"] == "add" and result["serial_lookup"]["found"] == "//LAB/Local/p/2"
    assert result["fields"]["SerialNumber"] == "00000000.0007" and result["warnings"] == []
    document = ProjectDocument.from_bytes(raw)
    applied = add_unit(document, "/network/Local", scan, catalog)
    assert applied["action"] == "added" and applied["serial_lookup"]["found"] == "/network/Local/unit/2"


def test_second_branch_warning_order_and_selected_path_are_preserved(catalog):
    units = [native_unit(address) for address in range(1, 101)]
    raw = snapshot([network(units=units)])
    result = plan_native_add_unit(raw, "//LAB/Local", "0SENSOR         000000000077", catalog)
    assert result["unit"] == "//LAB/Local/p/101" and result["serial_lookup"]["found"] is None
    assert [warning["toolkit_message_id"] for warning in result["warnings"]] == [45141, 2096]
    assert '"Local & Test"' in result["warnings"][0]["message"]
    duplicate = snapshot([network("Other", [native_unit(9, serial="77", object_id=oid(90))]), network()])
    result = plan_native_add_unit(duplicate, "//LAB/Local", "0SENSOR         000000000077", catalog)
    assert result["action"] == "selected_existing" and result["unit"] == "//LAB/Other/p/9"
    assert result["serial_lookup"]["found"] is None
    assert [warning["toolkit_message_id"] for warning in result["warnings"]] == [2096]


def test_serial_only_miss_and_placeholder_do_not_select(catalog):
    raw = snapshot([network(units=[native_unit(1, serial="00000000.0000")])])
    result = plan_native_add_unit(raw, "//LAB/Local", "000000000000", catalog)
    assert (result["action"], result["would_change"], result["serial_lookup"]["found"]) == ("not_found", False, None)
    assert [warning["toolkit_message_id"] for warning in result["warnings"]] == [2096]
    document = ProjectDocument.from_bytes(raw)
    before = document.to_xml_bytes()
    offline = add_unit(document, "/network/Local", "000000000000", catalog)
    assert "action" not in offline and "would_change" not in offline and not offline["changed"]
    assert document.to_xml_bytes() == before
    added = plan_native_add_unit(raw, "//LAB/Local", "5031NL          000000000000", catalog)
    assert added["action"] == "add" and added["address"] == 2


@pytest.mark.parametrize("address,expected", [(0, 0), (2, 2), (254, 254)])
def test_free_dialog_addresses(catalog, address, expected):
    result = plan_native_add_unit(snapshot(), "//LAB/Local", CONFIG, catalog, address=address)
    assert result["address"] == expected and result["automatic_address"] == 2


@pytest.mark.parametrize("address", [3, 255, -1, 256])
def test_occupied_or_unoffered_address_refused(catalog, address):
    raw = snapshot()
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(raw, "//LAB/Local", CONFIG, catalog, address=address)
    assert caught.value.details["code"] == "address_unavailable"
    assert raw == snapshot()


def test_automatic_255_is_admitted_but_full_255_units_refused(catalog):
    raw = snapshot([network(units=[native_unit(address) for address in range(1, 255)])])
    result = plan_native_add_unit(raw, "//LAB/Local", CONFIG, catalog, address=255)
    assert result["address"] == result["automatic_address"] == 255
    assert [warning["toolkit_message_id"] for warning in result["warnings"]] == [45141]
    full = snapshot([network(units=[native_unit(address) for address in range(1, 256)])])
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(full, "//LAB/Local", CONFIG, catalog)
    assert (caught.value.details["code"], caught.value.details["toolkit_message_id"]) == ("database_full", 2066)


@pytest.mark.parametrize("barcode,kind,code", [
    (CONFIG, "WKEY", "wired_unit_on_wireless_network"),
    ("5031RDTSL       123456789012", "KEYE1", "wireless_unit_on_wired_network"),
    ("UNKNOWN         123456789012", "KEYE1", "unknown_unit_type"),
    ("NOREV           123456789012", "KEYE1", "catalog_entry_without_type"),
    ("123456789012", "KEYE1", "wrong_barcode"),
])
def test_family_unknown_and_ignored_scan_boundaries(catalog, barcode, kind, code):
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(snapshot([network(units=[native_unit(1, kind=kind)])]), "//LAB/Local", barcode, catalog)
    assert caught.value.details["code"] == code


@pytest.mark.parametrize("barcode", ["", CONFIG + "\n" + CONFIG, "\r\n"])
def test_native_entry_requires_one_scan(catalog, barcode):
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(snapshot(), "//LAB/Local", barcode, catalog)
    assert caught.value.details["code"] == "invalid_input"


@pytest.mark.parametrize("change", [
    lambda raw: raw.replace(b"<Address>LAB</Address>", b"<Address>ELSE</Address>"),
    lambda raw: raw.replace(b"<UnitType>KEYE1</UnitType>", b"<UnitType>KEYE1</UnitType><UnitType>KEYE1</UnitType>", 1),
    lambda raw: raw.replace(b"<SerialNumber></SerialNumber>", b"<SerialNumber><Nested/></SerialNumber>", 1),
    lambda raw: raw.replace(b"<UnitType>KEYE1</UnitType>", b"<x:UnitType xmlns:x='urn:opaque'>KEYE1</x:UnitType>", 1),
    lambda raw: raw.replace(b"<Address>1</Address>", b"<Address>01</Address>", 1),
    lambda raw: raw.replace(b"<Address>3</Address>", b"<Address>1</Address>", 1),
    lambda raw: raw.replace(b"<OID>00000000-0000-4000-8000-000000000002</OID>", b"<OID>bad</OID>"),
    lambda raw: raw.replace(b"<Unit>", b"<x:Unit xmlns:x='urn:opaque'>", 1).replace(b"</Unit>", b"</x:Unit>", 1),
])
def test_ambiguous_consumed_native_inventory_is_refused(catalog, change):
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(change(snapshot()), "//LAB/Local", CONFIG, catalog)
    assert caught.value.details["code"] == "invalid_native_snapshot"


def test_selected_unit_requires_oid_and_new_xml_text_is_representable(catalog):
    raw = snapshot([network(units=[native_unit(1, serial="42")])])
    missing = raw.replace(b"<OID>00000000-0000-4000-8000-000000000002</OID>", b"")
    with pytest.raises(BarcodeError, match="requires a valid OID"):
        plan_native_add_unit(missing, "//LAB/Local", "5031NL          000000000042", catalog)
    with pytest.raises(BarcodeError) as caught:
        plan_native_add_unit(raw, "//LAB/Local", CONFIG, catalog, tag_name="bad\ufffe")
    assert caught.value.details["code"] == "invalid_native_snapshot"


def test_legacy_project_planning_retains_original_bytes(catalog):
    document = ProjectDocument.from_bytes(PROJECT_XML.encode())
    before = document.to_xml_bytes()
    result = plan_add_unit(document, "/network/254", CONFIG, catalog)
    assert result["unit"] == "/network/254/unit/2" and result["action"] == "add"
    assert document.to_xml_bytes() == before
