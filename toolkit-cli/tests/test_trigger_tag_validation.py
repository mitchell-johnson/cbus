"""P7.03 slice: Trigger level-tag resolution guards without I/O.

NativeTrigger.resolve_level_tag reads one database Group/NetVar before any
TRIGGER EVENT with a named selector. This pins the offline rejection edges
over a fake client: blank/control-character/oversize names, forbidden XML
declarations, malformed XML, non-Group roots, zero/multiple matches, and
missing or non-byte Values. One positive exact match (names with spaces
included) proves the accepted path. No server or database is involved.
"""
import unittest

from cbus_toolkit.applications import ApplicationError, NativeTrigger


class Reply:
    def __init__(self, *lines):
        self.lines = lines


class FakeClient:
    def __init__(self, xml):
        self.xml = xml
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        if command.startswith("DBGETXML "):
            return Reply("343-Begin XML snippet", "347-" + self.xml, "344 End XML snippet")
        return Reply("200 OK.")


def trigger(xml):
    return NativeTrigger(FakeClient(xml))


class LevelTagGuardTests(unittest.TestCase):
    GOOD = '<NetVar><Level Value="17"><TagName>Evening Scene</TagName></Level></NetVar>'

    def test_exact_match_with_spaces_resolves(self):
        client_trigger = trigger(self.GOOD)
        self.assertEqual(client_trigger.resolve_level_tag("//TEST/254/202/1", "Evening Scene"), 17)
        self.assertEqual(client_trigger.client.commands, ["DBGETXML //TEST/254/202/1"])

    def test_named_event_resolves_before_sending_numeric(self):
        client_trigger = trigger(self.GOOD)
        client_trigger.event("//TEST/254/202/1", "Evening Scene")
        self.assertEqual(client_trigger.client.commands,
                         ["DBGETXML //TEST/254/202/1", "TRIGGER EVENT //TEST/254/202/1 17"])

    def test_invalid_names_rejected_before_lookup(self):
        client_trigger = trigger(self.GOOD)
        for name in ("", "   ", "a\x01b", "a\x7fb", "x" * 1025, 17, None, "  "):
            with self.subTest(name=repr(name)):
                with self.assertRaises(ApplicationError):
                    client_trigger.resolve_level_tag("//TEST/254/202/1", name)
        self.assertEqual(client_trigger.client.commands, [])

    def test_forbidden_declarations_rejected(self):
        for xml in ('<!DOCTYPE Group [<!ENTITY x "y">]><Group/>',
                    '<Group><!ENTITY x "y"><Level Value="1"><TagName>a</TagName></Level></Group>'):
            with self.subTest(xml=xml[:20]):
                with self.assertRaises(ApplicationError):
                    trigger(xml).resolve_level_tag("//TEST/254/202/1", "a")

    def test_malformed_and_misshapen_documents_rejected(self):
        cases = [
            "<Group><Level>",
            "<Unit><Level Value=\"1\"><TagName>a</TagName></Level></Unit>",
            "<Group/>",
            "<Group><Level Value=\"1\"><TagName>b</TagName></Level></Group>",
            "<Group><Level Value=\"1\"><TagName>a</TagName></Level>"
            "<Level Value=\"2\"><TagName>a</TagName></Level></Group>",
            "<Group><Level><TagName>a</TagName></Level></Group>",
            "<Group><Level Value=\"abc\"><TagName>a</TagName></Level></Group>",
            "<Group><Level Value=\"256\"><TagName>a</TagName></Level></Group>",
            "<Group><Level Value=\"-1\"><TagName>a</TagName></Level></Group>",
        ]
        for xml in cases:
            with self.subTest(xml=xml):
                with self.assertRaises(ApplicationError):
                    trigger(xml).resolve_level_tag("//TEST/254/202/1", "a")


if __name__ == "__main__":
    unittest.main()
