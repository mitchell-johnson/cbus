"""P6.01 wave-16 narrow offline pins for eDLT template guards (issue #45).

Narrow scope: only toolkit-cli/src/cbus_toolkit/edlt_templates.py guards.
No Rust, DIN, light-level, display, controls, topology, or parity-register
coverage. Every pinned message had zero prior refs (verified via
``grep -rn`` across toolkit-cli/tests/ before writing). Pure offline:
no hardware, vendor EXE, C-Gate server, or decoded spec.
"""

from __future__ import annotations

import pytest

from cbus_toolkit.edlt_templates import (
    EdltTemplate,
    EdltTemplateError,
    edlt_template_crc,
    export_edlt_template,
    preview_edlt_template,
)


def _valid_template(payload=(("Application", "48 202"), ("UnitName", "TEST"), ("Value", "0x12"))):
    header = (("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"))
    crc = str(edlt_template_crc(value for _, value in payload))
    return EdltTemplate(header + (("CRC", crc),) + tuple(payload))


def test_wave16_plain_text_guards_pin_messages():
    template = _valid_template()
    with pytest.raises(EdltTemplateError, match="Whitespace-only"):
        EdltTemplate(template.fields[:2] + (("Value", "   "),) + template.fields[2:])
    with pytest.raises(EdltTemplateError, match="Markup, entities"):
        EdltTemplate(template.fields[:2] + (("CRC", template.fields[2][1]),) +
                     (("Value", "A&B"), ("UnitName", "TEST"), ("Value", "0x12")))
    with pytest.raises(EdltTemplateError, match="Template field values must be raw strings"):
        EdltTemplate((("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"),
                      ("CRC", "0"), ("Value", 123)))


def test_wave16_field_shape_guards_pin_messages():
    header = (("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"))
    payload = (("Application", "48 202"),)
    crc = str(edlt_template_crc(value for _, value in payload))
    with pytest.raises(EdltTemplateError, match="Fields must be ordered"):
        EdltTemplate({"UnitType": "KEYGL5"})
    with pytest.raises(EdltTemplateError, match="Unsupported plain XML field name"):
        EdltTemplate(header + (("CRC", crc),) + (("9bad", "x"),))
    with pytest.raises(EdltTemplateError, match="Fields must be ordered"):
        EdltTemplate([["only-one-element"]])


def test_wave16_identity_and_crc_shape_guards_pin_messages():
    payload = (("Application", "48 202"), ("UnitName", "TEST"))
    crc = str(edlt_template_crc(value for _, value in payload))
    header = (("UnitType", "KEYGL5"), ("FirmwareVersion", "5.5.00"))
    with pytest.raises(EdltTemplateError, match="Exactly one CRC"):
        EdltTemplate(header + tuple(payload))
    with pytest.raises(EdltTemplateError, match="Exactly one pre-CRC"):
        EdltTemplate((("FirmwareVersion", "5.5.00"), ("CRC", crc)) + tuple(payload))
    with pytest.raises(EdltTemplateError, match="decimal UInt16"):
        EdltTemplate(header + (("CRC", "99999"),) + tuple(payload))
    with pytest.raises(EdltTemplateError, match="Conflicting template"):
        bad_crc_payload = (("Application", "48 202"), ("UnitName", "TEST"),
                           ("UnitType", "KEYGL4"))
        bad_crc = str(edlt_template_crc(value for _, value in bad_crc_payload))
        EdltTemplate(header + (("CRC", bad_crc),) + tuple(bad_crc_payload))


def test_wave16_xml_export_preview_guards_pin_messages():
    xml = _valid_template().to_xml()
    with pytest.raises(EdltTemplateError, match="plain UnitTemplate"):
        EdltTemplate.from_xml(xml.replace("<UnitTemplate>", "<Other>").replace(
            "</UnitTemplate>", "</Other>"))
    with pytest.raises(EdltTemplateError, match="flat fields"):
        EdltTemplate.from_xml(xml.replace("<UnitName>", '<UnitName id="1">'))
    with pytest.raises(EdltTemplateError, match="DTD, entities"):
        EdltTemplate.from_xml(xml.replace("<UnitTemplate>", "<UnitTemplate><!--c-->"))
    with pytest.raises(EdltTemplateError, match="unique ordered"):
        export_edlt_template(description="d", firmware="5.5.00", unit_name="T",
                             primary_application=48, secondary_application=202,
                             pp_attributes=[("Value", "1"), ("Value", "2")])
    with pytest.raises(EdltTemplateError, match="collides with template"):
        export_edlt_template(description="d", firmware="5.5.00", unit_name="T",
                             primary_application=48, secondary_application=202,
                             pp_attributes=[("CRC", "1")])
    with pytest.raises(EdltTemplateError, match="Parse an EdltTemplate"):
        preview_edlt_template("not-a-template", pp_attribute_names=[])
    with pytest.raises(EdltTemplateError, match="complete ordered original"):
        preview_edlt_template(_valid_template(), pp_attribute_names={"Value": "1"})
    with pytest.raises(EdltTemplateError, match="must be valid and unique"):
        preview_edlt_template(_valid_template(), pp_attribute_names=["Value", "Value"])
