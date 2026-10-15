"""P7.01 slice: DALI mutation certainty classification without I/O.

_drives DaliCommissioning._mutating_issue_ directly with a recording fake
client. The native contract under test: only an explicit device/transport
rejection marks the physical outcome definite; every other failure retains
``outcome_uncertain=True`` so interrupted reconciliation never replays a
mutation. This pins the failure taxonomy in
``dali_commissioning.py`` (400/408/440/501, 502 NAK/FAIL_*, "no bus command
was sent") plus the fail-safe default (unknown 502 tokens, 503, transport
loss stay uncertain). No daemon, journal, or hardware is involved.
"""
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.dali_commissioning import DaliCommissioning


def reply(*lines, status):
    lines = lines or (f"{status} reply",)
    return CGateResponse(tuple(lines), lines[-1], status)


class FakeClient:
    def __init__(self, action):
        self.action = action
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        return self.action(command)


class MutationCertaintyTests(unittest.TestCase):
    def run_issue(self, action):
        workflow = DaliCommissioning(FakeClient(action))
        evidence = {"receipts": []}
        try:
            workflow._mutating_issue(evidence, "deploy", "TEST DEPLOY session")
        except (CGateError, RuntimeError) as error:
            return evidence, error
        return evidence, None

    def test_definite_rejections(self):
        cases = [
            reply("400 bad request", status=400),
            reply("408 conflict", status=408),
            reply("440 locked", status=440),
            reply("501 not implemented", status=501),
            reply("502 reply status error: error response: NAK during SET", status=502),
            reply("502 reply status error: error response: NAK", status=502),
            reply("502 reply status error: error response: FAIL_INVALID_DEVICE_TYPE during SET", status=502),
            reply("502 reply status error: error response: FAIL_INVALID_COMMAND during SET_SCENE_VALUES", status=502),
            reply("502 reply status error: error response: FAIL_INVALID_PARAMETER during SET", status=502),
            reply("502 reply status error: error response: FAIL_INCORRECT_LENGTH", status=502),
            reply("502 no bus command was sent; request refused before I/O", status=502),
        ]
        for response in cases:
            with self.subTest(final=response.final):
                def fail(_command, response=response):
                    raise CGateError(response)

                evidence, error = self.run_issue(fail)
                self.assertIsInstance(error, CGateError)
                self.assertFalse(evidence["outcome_uncertain"])
                self.assertTrue(evidence["mutation_terminal_received"])
                self.assertTrue(evidence["mutating_command_issued"])
                self.assertEqual(len(evidence["receipts"]), 1)

    def test_uncertain_failures_are_never_replayed(self):
        cases = [
            CGateError(reply("503 network error: timed out", status=503)),
            CGateError(reply("502 reply status error: error response: IN_PROGRESS during SET", status=502)),
            CGateError(reply("502 reply status error: error response: FAIL_BUSY during SET", status=502)),
            # Unknown 502 tokens fail safe toward uncertainty, never definite.
            CGateError(reply("502 reply status error: error response: TIMEOUT during SET", status=502)),
            CGateError(reply("500 internal error", status=500)),
        ]
        for error in cases:
            with self.subTest(error=str(error)):
                def fail(_command, error=error):
                    raise error

                evidence, caught = self.run_issue(fail)
                self.assertIs(type(caught), type(error))
                self.assertTrue(evidence["outcome_uncertain"])
                self.assertTrue(evidence["mutation_terminal_received"])

    def test_transport_loss_propagates_without_a_certainty_claim(self):
        # A bare transport failure is not a CGateError receipt, so
        # _mutating_issue records no certainty verdict; the deploy-level
        # journal (covered in test_dali_commissioning.py) treats it as
        # uncertain and never replays it.
        def fail(_command):
            raise RuntimeError("connection closed; outcome unknown")

        evidence, caught = self.run_issue(fail)
        self.assertIsInstance(caught, RuntimeError)
        self.assertNotIn("outcome_uncertain", evidence)
        self.assertNotIn("mutation_terminal_received", evidence)

    def test_accepted_mutation_is_certain(self):
        evidence, error = self.run_issue(lambda _command: reply("200 OK.", status=200))
        self.assertIsNone(error)
        self.assertFalse(evidence["outcome_uncertain"])
        self.assertTrue(evidence["mutation_terminal_received"])


if __name__ == "__main__":
    unittest.main()
