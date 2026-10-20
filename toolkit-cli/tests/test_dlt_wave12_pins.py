"""Wave-12 narrow pins for P6.03 (#47): DLT profile refusal/admission edges.

Offline only: exercises ``cbus_toolkit.dlt_profiles.refusal`` with no I/O,
no vendor fixtures and no network. Each edge below had zero prior refs in
``tests/test_dlt_profiles.py`` and
``tests/test_p5p6_round13_narrow_slices.py`` (only neighbouring inputs or
bare non-None assertions existed).
"""

from cbus_toolkit.dlt_profiles import admits, refusal


def test_serial_population_ignores_firmware_and_catalog():
    # 'serial-population' identity is ('unit_type',) only: extra firmware /
    # catalogue arguments must not change the admission decision.
    assert refusal("serial-population", "KEYGL5", "9.9.99", "ANYTHING") is None
    assert refusal("serial-population", "KEYGL5", None, None) is None
    assert admits("serial-population", "KEYGL5", "9.9.99", "ANYTHING")


def test_zero_padded_database_firmware_refused_as_non_canonical():
    # '05.05.00' is refused by the database workflow (exact-string ranges),
    # with the canonical-spelling reason -- prior tests only asserted
    # non-None for this input, pinning the reason only for '5.5.1'.
    reason = refusal("edlt-database-widgets", "KEYGL5", "05.05.00", "5055EDL")
    assert "canonical catalogue spelling" in reason


def test_missing_catalog_number_refusal_names_catalogue():
    # A missing catalogue number is not silently admitted when the admitted
    # rows name an exact catalogue ('5055EDL', not '*'): prior tests only
    # asserted non-None for catalog=None, never the reason.
    reason = refusal("edlt-database-widgets", "KEYGL5", "5.5.00", None)
    assert "not a C-Gate catalogue number" in reason


def test_database_widget_range_boundaries():
    # Boundary firmware of each public database revision range is admitted;
    # the neighbouring internal revisions refuse with their exact ranges.
    for firmware in ("1.6.00", "1.7.99", "5.4.99"):
        assert refusal("edlt-database-widgets", "KEYGL5", firmware, "5055EDL") is None, firmware
    assert "1.5.01..1.5.99" in refusal("edlt-database-widgets", "KEYGL5", "1.5.99", "5055EDL")
    assert "IsInternal" in refusal("edlt-database-widgets", "KEYGL5", "1.5.99", "5055EDL")
    assert "5.6.00..9" in refusal("edlt-database-widgets", "KEYGL5", "5.6.00", "5055EDL")


def test_classic_non_canonical_spelling_has_no_evidence():
    # '2.0.0' denotes the same version as admitted '2.0.00' but is not the
    # exact admitted string, so it reaches the terminal classic refusal
    # branch instead of the MinVersion or IsInternal branches.
    reason = refusal("classic-dlt-label-variants", "KEYBL5", "2.0.0", "5085DL")
    assert "has no retained evidence" in reason
