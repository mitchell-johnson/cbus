"""P6 eDLT wave-11 narrow offline pins (issue #45).

One narrow slice of ``edlt_parent_transaction.normalize_operations`` shape
and ordering gates. Every pinned message had zero prior refs (verified via
``grep -rn`` across tests/ before writing; the grammar test in
test_edlt_parent_transaction.py exercises the same inputs only with a
generic assertRaises, never the message). Pure offline: shape checks only,
no spec fixture, hardware, vendor EXE, C-Gate server, or decoded spec.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_transaction import (
    MAX_OPERATIONS,
    normalize_operations,
)


def measurement(**overrides):
    operation = {
        "op": "measurement", "page": 1, "position": 1,
        "device_id": 42, "channel": 3,
    }
    operation.update(overrides)
    return operation


def lighting(**overrides):
    operation = {
        "op": "lighting", "page": 1, "position": 2,
        "group": 12, "mode": "dimmer",
    }
    operation.update(overrides)
    return operation


def reset(**overrides):
    operation = {
        "op": "reset", "active_tab": "a", "binding_variant": "b",
    }
    operation.update(overrides)
    return operation


class P6Wave11ParentTransactionPins(unittest.TestCase):
    """Issue #45: parent-transaction shape/ordering guard messages."""

    def test_array_and_count_guards_pin_messages(self):
        for bad in ("x", None, {}, 42):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                EdltError, "Parent transaction operations must be an array"
            ):
                normalize_operations(bad)
        for operations in (
            [],
            [measurement()],
            [measurement()] * (MAX_OPERATIONS + 1),
        ):
            with self.subTest(length=len(operations)), self.assertRaisesRegex(
                EdltError, r"Parent transaction requires 2\.\.22 operations"
            ):
                normalize_operations(operations)
        self.assertEqual(
            [row["op"] for row in normalize_operations(
                [{"op": "activation"}, measurement()])],
            ["activation", "measurement"],
        )

    def test_native_dialog_gates_refuse_before_any_io(self):
        cases = (
            ({"op": "add-corridor-dialog", "field": "link_group"},
             "Parent Add dialogs require the automatic"),
            ({"op": "add-dialog", "field": "ProximityGroup"},
             "add-dialog creates project metadata"),
            ({"op": "add-language-dialog"},
             "Language Add requires automatic complete native project metadata"),
        )
        for gate, message in cases:
            with self.subTest(gate=gate), self.assertRaisesRegex(
                EdltError, message
            ):
                normalize_operations([gate, measurement()])
        with self.assertRaisesRegex(
            EdltError, "Parent transaction op must be one of"
        ):
            normalize_operations([{"op": "invented"}, measurement()])
        with self.assertRaisesRegex(
            EdltError, "Parent transaction operation must be a mapping"
        ):
            normalize_operations([["not-a-mapping"], measurement()])

    def test_reset_blank_and_widget_presence_ordering(self):
        with self.assertRaisesRegex(
            EdltError, "Parent transaction permits only one reset operation"
        ):
            normalize_operations([reset(), reset()])
        with self.assertRaisesRegex(
            EdltError, "Blank operations after Reset must immediately follow"
        ):
            normalize_operations(
                [reset(), measurement(), {"op": "blank", "page": 1, "position": 1}])
        with self.assertRaisesRegex(
            EdltError, "Parent transaction requires at least one widget"
        ):
            normalize_operations([{"op": "activation"}, {"op": "general"}])
        with self.assertRaisesRegex(
            EdltError, "Invalid lowered parent Add binding"
        ):
            normalize_operations(
                [{"op": "parent-add-binding", "panel": "nope",
                  "option": "x", "value": 1}, measurement()])

    def test_per_operation_shape_guards_pin_messages(self):
        with self.assertRaisesRegex(
            EdltError, "mra-globals operation requires multiplexer"
        ):
            normalize_operations([{"op": "mra-globals"}, measurement()])
        with self.assertRaisesRegex(
            EdltError, "scene-manager operation requires 1\\.\\.256 nested"
        ):
            normalize_operations(
                [{"op": "scene-manager", "operations": []}, measurement()])
        incomplete = dict(measurement())
        del incomplete["channel"]
        with self.assertRaisesRegex(
            EdltError, "measurement operation requires"
        ):
            normalize_operations([incomplete, lighting()])
        with self.assertRaisesRegex(
            EdltError, "lighting operation contains unsupported fields"
        ):
            normalize_operations(
                [{**lighting(), "unknown": 1}, measurement()])


if __name__ == "__main__":
    unittest.main()
