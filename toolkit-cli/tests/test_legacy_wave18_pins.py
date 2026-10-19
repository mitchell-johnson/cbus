"""Wave-18 offline pins for legacy transform guards (P8.01 #55).

Narrow scope: guard semantics in
cbus_toolkit.project_legacy_transform.transform_repaired_legacy_project
only (no Rust, dali_extended_proxy, firmware_ncc, or parity register).
Each pinned guard phrase has zero prior references in tests/.
Fully offline: synthetic byte documents, no fixtures, network, or vendor
software.
"""

import pytest

from cbus_toolkit.project_legacy_transform import (
    LegacyProjectTransformError,
    transform_repaired_legacy_project,
)

BASE = (b'<?xml version="1.0" encoding="utf-8"?><Installation>'
        b'<DBVersion>2.2</DBVersion><Project></Project></Installation>\n')


def test_wave18_input_size_and_type_guards():
    with pytest.raises(ValueError, match="max_bytes must be"):
        transform_repaired_legacy_project(BASE, max_bytes=0)
    with pytest.raises(ValueError, match="max_bytes must be"):
        transform_repaired_legacy_project(BASE, max_bytes="4096")
    with pytest.raises(TypeError, match="XML input must be bytes"):
        transform_repaired_legacy_project("<xml/>")
    with pytest.raises(LegacyProjectTransformError,
                       match="Source exceeds max_bytes"):
        transform_repaired_legacy_project(BASE, max_bytes=len(BASE) - 1)
    # Control: the same document converts at an exact-size budget.
    result = transform_repaired_legacy_project(BASE, max_bytes=len(BASE))
    assert result.source_db_version == "2.2"


def test_wave18_project_cardinality_guard():
    for source in (
        BASE.replace(b"<Project></Project>", b""),
        BASE.replace(b"<Project></Project>",
                     b"<Project></Project><Project></Project>"),
    ):
        with pytest.raises(LegacyProjectTransformError,
                           match="Expected exactly one direct Project element"):
            transform_repaired_legacy_project(source)


def test_wave18_dbversion_placement_guard():
    nested = (b'<?xml version="1.0" encoding="utf-8"?><Installation>'
              b'<Project><DBVersion>2.2</DBVersion></Project>'
              b'</Installation>\n')
    assert nested.count(b"<DBVersion>2.2</DBVersion>") == 1
    with pytest.raises(
        LegacyProjectTransformError,
        match="Expected one direct DBVersion element with the selected "
              "source version",
    ):
        transform_repaired_legacy_project(nested)


def test_wave18_malformed_source_guard():
    malformed = (b'<?xml version="1.0" encoding="utf-8"?><Installation>'
                 b'<DBVersion>2.2</DBVersion><Project></Installation>\n')
    with pytest.raises(LegacyProjectTransformError,
                       match="Source is not well-formed, bounded UTF-8 XML"):
        transform_repaired_legacy_project(malformed)
