"""Occupied-address chain recovery edges for #30 (P3.03).

Pins the refusal and fallback paths of the recursive displacement planner in
``cbus_toolkit.duplicate_resolution`` that the native-capture replays and the
two/three-link chain tests do not cover: a chain occupant whose own database
target is vacant, a crowded deeper link, a deeper link naming the local PCI,
a cycle back through the selected address, and the native-method taxonomy of
chain moves. Pure prediction over caller-supplied facts; no bus I/O.
"""
import unittest

from cbus_toolkit.duplicate_resolution import LEGACY_ADDRESS, SELECTED_SERIAL, plan_unravel


class ChainRecoveryEdgeTests(unittest.TestCase):
    def test_occupant_with_vacant_own_target_is_displaced_to_free(self):
        # 1.2's only database address (9) is vacant, so the chain clears 6 by
        # moving 1.2 to the lowest free address rather than to 9, matching the
        # observed native single-link rule inside a deeper chain.
        plan = plan_unravel({20: ["1.1", "1.10"], 6: ["1.2"]},
                            {20: "1.1", 6: "1.10", 9: "1.2"},
                            selection=[20], match_database=True)
        self.assertIsNone(plan.refusal)
        self.assertEqual([(m.serial, m.source, m.destination, m.reason) for m in plan.moves],
                         [("1.2", 6, 2, "displacement"),
                          ("1.10", 20, 6, "database_match")])
        self.assertEqual(plan.final, {"1.1": 20, "1.10": 6, "1.2": 2})
        self.assertEqual(plan.kept, ((20, "1.1"),))

    def test_crowded_deeper_link_names_the_deeper_address(self):
        plan = plan_unravel({20: ["1.1", "1.10"], 6: ["1.2"], 7: ["1.3", "1.4"]},
                            {20: "1.1", 6: "1.10", 7: "1.2"},
                            selection=[20], match_database=True)
        self.assertEqual(plan.moves, ())
        self.assertRegex(plan.refusal, "Database address 7 for 1\\.2 holds several units")

    def test_deeper_link_naming_the_local_pci_is_refused(self):
        plan = plan_unravel({20: ["1.1", "1.10"], 6: ["1.2"], 16: ["9.9"]},
                            {20: "1.1", 6: "1.10", 16: "1.2"},
                            selection=[20], match_database=True,
                            local_unit=16, local_serial="9.9")
        self.assertEqual(plan.moves, ())
        self.assertRegex(plan.refusal, "Database address 16 for 1\\.2 is the local PCI")

    def test_cycle_back_through_the_selected_address_is_refused(self):
        # 1.2's database address is the selected address itself, so clearing 6
        # would chase the chain back to where planning started.
        plan = plan_unravel({20: ["1.1", "1.10"], 6: ["1.2"]},
                            {20: "1.2", 6: "1.10"},
                            selection=[20], match_database=True)
        self.assertEqual(plan.moves, ())
        self.assertEqual(plan.kept, ())
        self.assertRegex(plan.refusal, "cyclic at address 20")

    def test_chain_moves_keep_native_method_taxonomy(self):
        # The duplicate source held two serials when scanned, so the database
        # move uses the selected-serial broadcast; every cleared singleton
        # link uses the legacy protected STORE.
        plan = plan_unravel({20: ["1.1", "1.10"], 6: ["1.2"], 7: ["1.3"]},
                            {20: "1.1", 6: "1.10", 7: "1.2"},
                            selection=[20], match_database=True)
        self.assertIsNone(plan.refusal)
        self.assertEqual([(m.serial, m.native_method) for m in plan.moves],
                         [("1.3", LEGACY_ADDRESS),
                          ("1.2", LEGACY_ADDRESS),
                          ("1.10", SELECTED_SERIAL)])


if __name__ == "__main__":
    unittest.main()
