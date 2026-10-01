"""Catalogue commands reject malformed inputs and uncertain replies before retry."""
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.network_definitions import NativeNetworkDefinitions, definition_command


class Capture:
    def __init__(self, code=200):
        self.commands = []
        self.code = code

    def command(self, command):
        self.commands.append(command)
        code = 200 if command.startswith("PROJECT USE") else self.code
        return CGateResponse((), f"{code} fixture response", code)


class NetworkDefinitionTests(unittest.TestCase):
    def test_all_catalogue_operations_use_the_explicit_project_and_native_shapes(self):
        rows = (
            ("list", {}, "NET LIST LAB", 132),
            ("create", {"name": "GARAGE", "interface_type": "CNI", "interface_address": "127.0.0.1:1", "options": ["alpha=beta", "baud=9600"]}, "NET CREATE GARAGE cni 127.0.0.1:1 alpha=beta baud=9600", 200),
            ("delete", {"name": "GARAGE"}, "NET DELETE GARAGE", 200),
            ("rename", {"name": "GARAGE", "new_name": "SHED", "fix_references": False}, "NET RENAME GARAGE SHED nofixrefs", 200),
            ("load", {"selector": "db"}, "NET LOAD DB LAB", 200),
            ("save", {"selector": "file"}, "NET SAVE FILE LAB", 200),
            ("flush", {"name": "254"}, "NET FLUSH 254", 200),
        )
        for action, arguments, command, code in rows:
            with self.subTest(action=action):
                client = Capture(code)
                response = NativeNetworkDefinitions(client).execute(action, project="LAB", **arguments)
                self.assertEqual(response.code, code)
                self.assertEqual(client.commands, ["PROJECT USE LAB", command])

    def test_malformed_or_irrelevant_arguments_refuse_before_project_selection(self):
        cases = (
            ("create", {"name": "Garage room", "interface_type": "cni", "interface_address": "127.0.0.1:1"}),
            ("create", {"name": "Garage", "interface_type": "cni", "interface_address": "x\r\nSHUTDOWN"}),
            ("create", {"name": "Garage", "interface_type": "cni", "interface_address": "x", "options": ["a=1\nNET OPEN 254"]}),
            ("create", {"name": "Garage", "interface_type": "cni", "interface_address": "x", "options": "a=1"}),
            ("create", {"name": "Garage", "interface_type": "invalid", "interface_address": "x"}),
            ("create", {"name": "Garage", "interface_type": None, "interface_address": "x"}),
            ("delete", {"name": "//OTHER/254"}),
            ("delete", {"name": "a\\b"}),
            ("delete", {"name": 'a"b'}),
            ("delete", {"name": "é" * 128}),
            ("delete", {"name": "Garage", "selector": "DB"}),
            ("rename", {"name": "Garage", "new_name": None}),
            ("rename", {"name": "Garage", "new_name": "New", "fix_references": 0}),
            ("list", {"name": "Garage"}),
            ("list", {"new_name": "Garage"}),
            ("list", {"interface_address": "x"}),
            ("save", {"selector": "/tmp/networks"}),
            ("load", {"selector": None}),
            ("open", {}),
        )
        client = Capture()
        for action, arguments in cases:
            with self.subTest(action=action, arguments=arguments):
                with self.assertRaises(ValueError):
                    NativeNetworkDefinitions(client).execute(action, project="LAB", **arguments)
        for project in (True, None, "NINECHARS", "../LAB", "LAB\nNOOP"):
            with self.subTest(project=project):
                with self.assertRaises(ValueError):
                    NativeNetworkDefinitions(client).execute("list", project=project)
        self.assertEqual(client.commands, [])

    def test_noncompletion_and_lost_reply_never_replay_a_mutation(self):
        for code in (101, 131, 132, 202, 301, 408, 600):
            with self.subTest(code=code):
                client = Capture(code)
                with self.assertRaisesRegex(RuntimeError, "did not complete"):
                    NativeNetworkDefinitions(client).execute("load", project="LAB", selector="DB")
                self.assertEqual(client.commands, ["PROJECT USE LAB", "NET LOAD DB LAB"])

        class Lost(Capture):
            def command(self, command):
                if command.startswith("NET"):
                    self.commands.append(command)
                    raise OSError("reply lost")
                return super().command(command)

        client = Lost()
        with self.assertRaisesRegex(OSError, "reply lost"):
            NativeNetworkDefinitions(client).execute("delete", project="LAB", name="Garage")
        self.assertEqual(client.commands, ["PROJECT USE LAB", "NET DELETE Garage"])

    def test_unconfirmed_selection_stops_before_catalogue_command(self):
        class Selection(Capture):
            def command(self, command):
                self.commands.append(command)
                return CGateResponse((), "202 Selection pending", 202)

        client = Selection()
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            NativeNetworkDefinitions(client).execute("save", project="LAB", selector="DB")
        self.assertEqual(client.commands, ["PROJECT USE LAB"])

    def test_plan_is_pure_and_carries_both_empty_and_nonempty_list_codes(self):
        plan = definition_command("list", project="LAB")
        self.assertEqual(plan.command, "NET LIST LAB")
        self.assertEqual(plan.expected_codes, (131, 132))

    def test_cli_preflight_rejects_unsafe_fields_without_connecting(self):
        from cbus_toolkit.cli import _cgate, build_parser

        cases = (
            ("create", "--project", "LAB", "Garage", "cni", "bad\nNOOP"),
            ("create", "--project", "LAB", "Garage", "cni", "x", "--option", 'a="b"'),
            ("delete", "--project", "LAB", "//OTHER/254"),
            ("list", "--project", "../LAB"),
            ("rename", "--project", "LAB", "Garage", "name two"),
        )
        for fields in cases:
            with self.subTest(fields=fields), patch("cbus_toolkit.cgate.CGateClient") as client:
                args = build_parser().parse_args(["cgate", "network", "definition", *fields])
                with self.assertRaises(ValueError):
                    _cgate(args)
                client.assert_not_called()
