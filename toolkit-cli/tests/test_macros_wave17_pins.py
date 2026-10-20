"""Wave-17 offline pins for ExtendedKeys macro guards (P7.02 #52).

Narrow scope: only exercises pre-snapshot guards in
``cbus_toolkit.extended_macros.ExtendedKeys.plan`` so no native session,
spec XML, broker, or hardware is required.
"""

import pytest

from cbus_toolkit.extended_macros import ExtendedKeys
from cbus_toolkit.macros import MacroError


def _keys():
    keys = ExtendedKeys.__new__(ExtendedKeys)
    keys.unit_type = "KEYM4"
    keys.key_count = 4
    keys.family = "Neo"
    return keys


def test_key_out_of_range_guard():
    with pytest.raises(MacroError, match="supported physical"):
        _keys().plan({}, key=5, preset="toggle")


def test_unknown_preset_guard():
    with pytest.raises(MacroError, match="Unknown standard wired preset"):
        _keys().plan({}, key=1, preset="no-such-preset")


def test_application_selection_guard():
    with pytest.raises(MacroError, match="primary or secondary"):
        _keys().plan({}, key=1, preset="toggle", application="tertiary")


def test_allow_shared_block_type_guard():
    with pytest.raises(MacroError, match="allow_shared_block must be boolean"):
        _keys().plan({}, key=1, preset="toggle", allow_shared_block="yes")
