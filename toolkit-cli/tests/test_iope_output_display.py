"""Numeric inspection is separate from historical native editor acceptance."""
from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import patch
from cbus_toolkit import cli, iope_workflow_cli
from cbus_toolkit.iope_output_display import restrike_delay_choices, restrike_delay_time
from cbus_toolkit.pp_editor import PPEditError


class IopeOutputDisplayTest(unittest.TestCase):
    def test_literal_time_boundaries_and_inventory(self):
        for ordinal, minutes, seconds in ((0, 0, 0), (1, 0, 10), (5, 0, 50), (6, 1, 0),
                                           (7, 1, 10), (60, 10, 0), (254, 42, 20), (255, 42, 30)):
            with self.subTest(ordinal=ordinal):
                self.assertEqual(restrike_delay_time(ordinal), {"minutes": minutes, "seconds": seconds})
        choices = restrike_delay_choices()
        self.assertEqual([row["ordinal"] for row in choices], list(range(1, 255)))
        self.assertEqual(choices[0], {"ordinal": 1, "minutes": 0, "seconds": 10})
        self.assertEqual(choices[-1], {"ordinal": 254, "minutes": 42, "seconds": 20})
        for value in (-1, 256, True, "6", 6.0):
            with self.subTest(value=value), self.assertRaises(PPEditError):
                restrike_delay_time(value)

    def test_public_actions_read_no_files_and_open_no_connection(self):
        with patch("cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("unexpected connection")), \
                patch.object(iope_workflow_cli, "read_json", side_effect=AssertionError("unexpected file read")), \
                patch.object(iope_workflow_cli, "run", side_effect=AssertionError("unexpected legacy dispatch")):
            choices, status = cli.run(cli.build_parser().parse_args(
                ["iope-workflow", "output", "restrike-delay-choices"]))
            self.assertEqual(status, 0)
            self.assertEqual(len(choices["choices"]), 254)
            self.assertFalse(choices["localized_display_verified"])
            for ordinal, listed in ((0, False), (6, True), (255, False)):
                result, status = cli.run(cli.build_parser().parse_args(
                    ["iope-workflow", "output", "restrike-delay-time", str(ordinal)]))
                self.assertEqual(status, 0)
                self.assertEqual(result["listed"], listed)
                self.assertEqual(result["ordinal"], ordinal)
            with self.assertRaises(PPEditError):
                cli.run(cli.build_parser().parse_args(["iope-workflow", "output", "restrike-delay-time", "256"]))

    def test_standalone_native_parser_keeps_original_surface(self):
        for action in ("restrike-delay-choices", "restrike-delay-time"):
            with self.subTest(action=action), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                iope_workflow_cli.parser().parse_args(["output", action])

    def test_legacy_output_dispatch_is_unchanged(self):
        args = cli.build_parser().parse_args(["iope-workflow", "output", "show", "snapshot.json"])
        with patch.object(iope_workflow_cli, "run", return_value=({"legacy": True}, 0)) as legacy:
            self.assertEqual(cli.run(args), ({"legacy": True}, 0))
        legacy.assert_called_once_with(args)
