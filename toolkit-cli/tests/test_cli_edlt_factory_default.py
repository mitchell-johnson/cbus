"""CLI preflight, durable intent and one-shot eDLT factory reset receipt."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.cgate import CGateClient, CGateError
from tests.test_edlt_factory_default import FactoryClient, NET, reply


class ContextClient(FactoryClient):
    _close_preserving = CGateClient._close_preserving
    __exit__ = CGateClient.__exit__

    def __init__(self):
        super().__init__()
        self.close_error = None

    def __enter__(self):
        return self

    def close(self):
        self.connected = False
        if self.close_error is not None:
            raise self.close_error


class EdltFactoryDefaultCliTests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def args(self, action="request", *extra):
        return (
            "cgate",
            "edlt-factory-default",
            action,
            NET + "/p/5",
            "--serial",
            "101183.1666",
            *extra,
        )

    def test_plan_only_and_fsynced_request_intent_precede_one_control(self):
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            client = ContextClient()
            with patch("cbus_toolkit.cgate.CGateClient", return_value=client):
                plan = self.invoke(self.args("plan", "--plan-output", plan_path))
            self.assertEqual(json.loads(plan_path.read_text()), plan)
            self.assertFalse(any(command.startswith("DO ") for command in client.commands))

            request_path = Path(directory) / "request.json"
            client = ContextClient()
            command = client.command
            fsynced = []
            original_fsync = os.fsync

            def sync(descriptor):
                original_fsync(descriptor)
                fsynced.append(True)

            def request(text):
                if text.startswith("DO "):
                    self.assertTrue(fsynced)
                    self.assertEqual(json.loads(request_path.read_text())["native_command"], text)
                return command(text)

            client.command = request
            with patch("cbus_toolkit.cgate.CGateClient", return_value=client), patch.object(
                cli.os, "fsync", side_effect=sync
            ):
                result = self.invoke(self.args("request", "--plan-output", request_path))
            self.assertEqual(result["outcome"], "native_accepted")
            self.assertFalse(result["physical_factory_reset_verified"])
            self.assertEqual(sum(command.startswith("DO ") for command in client.commands), 1)

    def test_invalid_preflight_does_not_connect(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("must not connect")
        ):
            existing = Path(directory) / "exists"
            existing.write_text("original")
            self.assertIn("already exists", self.invoke(self.args("request", "--plan-output", existing), status=1)["error"])
            self.assertIn(
                "//PROJECT/NETWORK/p/UNIT",
                self.invoke(
                    (
                        "cgate",
                        "edlt-factory-default",
                        "request",
                        "/db" + NET + "/p/5",
                        "--serial",
                        "101183.1666",
                    ),
                    status=1,
                )["error"],
            )

    def test_rejection_uncertainty_and_close_interruption_export_evidence(self):
        for failure, outcome in (
            (CGateError(reply("502 eDLT factory default failed: unit rejected")), "native_rejected"),
            (ConnectionError("lost reset reply"), "outcome_uncertain"),
        ):
            client = ContextClient()
            client.factory_exception = failure
            with patch("cbus_toolkit.cgate.CGateClient", return_value=client):
                result = self.invoke(self.args(), status=1)
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(sum(command.startswith("DO ") for command in client.commands), 1)
        client = ContextClient()
        client.close_error = KeyboardInterrupt("secondary close")
        with patch("cbus_toolkit.cgate.CGateClient", return_value=client):
            result = self.invoke(self.args(), status=130)
        evidence = result["edlt_factory_default_evidence"]
        self.assertEqual(evidence["outcome"], "native_accepted")
        self.assertFalse(evidence["physical_factory_reset_verified"])
        self.assertEqual(result["error"], "Interrupted")


if __name__ == "__main__":
    unittest.main()
