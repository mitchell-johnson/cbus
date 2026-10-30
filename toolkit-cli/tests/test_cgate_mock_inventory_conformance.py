"""cgate-mock conformance against the recovered Toolkit client checks (#160).

Every dispatching Toolkit client class in
``research/toolkit-client/inventory.json`` must be able to drive cgate-mock
and classify the mock's final row with the check the class itself performs.
This suite drives the same ``CGateClient`` transport the CLI uses, so the
assertions pin exactly what Toolkit's parser would read, not helper-level
convenience.

Cases map one to one to the issue #160 gap and confirmation tables:

- typed reply shapes: ``port probe``, ``transform project``/``TRANSFORM
  MIGRATE_SQL``, ``config obget``/``obset``, ``AIRCON`` methods,
  ``net checkunit``, ``dbrenamenet``, ``PP GET_UNIT_CATALOG``,
  ``calculator test``, ``event`` modes, ``label kfiget``, ``send``,
  ``START_BACKGROUND_JOB``, ``shutdown``/``confirm``, ``NET CLOCKS``,
  ``port cniscan``, ``file dir``/``file download``;
- the native console envelopes that must stay native (uppercase AIRCON);
- the deliberate mock/model boundaries (KFI dataset, catalog absences,
  the LOGIN quirk, which belongs to the separate LOGIN/#159 slice and is
  noted, not asserted, because that slice's shape is not in this tree).

Known co-update outside this suite's scope: ``NET CHECKUNIT`` now finishes
with Toolkit's recovered ``200 ok`` row (the NetTextFamily fragment in
``inventory.json``). The Python serial-multiplicity wrapper in
``src/cbus_toolkit/serials.py`` still hops over the older ``200 OK.`` row,
so the three mock-driven multiplicity interop tests need the wrapper row
added there before they are green again against this mock.

The mock binary is located the same way the other interop suites do it
(``CBUS_CGATE_MOCK_BIN`` or a fresh sibling ``rust/target/debug/cgate-mock``)
and the whole module skips cleanly when it is absent.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateClient, CGateError

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "toolkit-cli" / "research" / "toolkit-client" / "inventory.json"


def find_mock():
    # Same discovery as tests/test_rust_cgate_interop.py: an explicit
    # CBUS_CGATE_MOCK_BIN wins, then the sibling debug build, which is
    # rejected when it is older than the mock sources.
    override = os.environ.get("CBUS_CGATE_MOCK_BIN")
    if override and Path(override).is_file():
        return override
    candidate = ROOT / "rust" / "target" / "debug" / "cgate-mock"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        sources = ROOT / "rust" / "cbus-cgate"
        try:
            newest = max(
                entry.stat().st_mtime
                for entry in list(sources.rglob("*.rs")) + [sources / "Cargo.toml"])
        except (OSError, ValueError):
            newest = 0
        try:
            if candidate.stat().st_mtime < newest:
                return None
        except OSError:
            return None
        return str(candidate)
    return None


MOCK_BIN = find_mock()


@unittest.skipUnless(MOCK_BIN, "cgate-mock binary is not built")
class CgateMockInventoryConformance(unittest.TestCase):
    """Drive one deterministic mock session through #160's command tables."""

    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(INVENTORY.read_text())
        cls.classes_by_name = {
            entry["class"]: entry for entry in cls.inventory["classes"]}

    def setUp(self):
        # No --unitspec: the catalogue-backed PP/casework belongs to the
        # unitspec suites; catalogue absence is #160's exact "408 No Catalog
        # Available" model.
        command = [MOCK_BIN, "--bind", "127.0.0.1:0"]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(self._stop_process)
        lines = queue.Queue()
        startup = threading.Thread(
            target=lambda: lines.put(self.process.stdout.readline(512)),
            daemon=True)
        startup.start()
        try:
            line = lines.get(timeout=10.0)
        except queue.Empty:
            self.fail("cgate-mock did not report its port within 10 seconds")
        match = re.fullmatch(r"cgate-mock listening on 127\.0\.0\.1:(\d+)\s*", line)
        if not match:
            self.fail(f"cgate-mock did not report a port: {line!r}")
        self.client = CGateClient("127.0.0.1", int(match[1]), timeout=20.0)
        self.addCleanup(self.client.close)
        self.client.connect()
        # Deterministic workspace: one selected project, one network with one
        # database unit. This mirrors Toolkit's own session setup against a
        # fresh server (PROJECT NEW / USE, DBCREATENET, DB ADD).
        for command, status in (
                ("PROJECT NEW TEST", 200),
                ("PROJECT USE TEST", 200),
                ("DBCREATENET 254 Local Cni 127.0.0.1:10001", 200)):
            self.assertEqual(self.client.command(command).status, status)
        # One database unit in the deterministic workspace drives the
        # NET CHECKUNIT and NET CLOCKS unit rows.
        self.client.command("DBADDSAFE //TEST/254 Unit 20 Lounge")

    def _stop_process(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5.0)
        finally:
            self.process.stdout.close()
            if hasattr(self, "startup_reader"):
                getattr(self, "startup_reader").join(timeout=1.0)

    def command(self, text):
        return self.client.command(text)

    def refusal(self, text):
        """A complete server error reply, as Toolkit's parser would admit.

        Toolkit's shared parser completes every tagged row and the class
        classifies the final row by text/fragment; the transport raises for
        4xx/5xx finals, so the check compares against the caught reply.
        """
        try:
            self.client.command(text)
        except CGateError as error:
            return error.response
        self.fail(f"{text!r} did not produce a complete error reply")

    # -- inventory coverage bookkeeping ---------------------------------------

    def test_every_dispatching_inventory_class_has_a_conformance_case(self):
        driven = set(DRIVEN_CLASSES)
        recorded = {
            name for name, entry in self.classes_by_name.items()
            if entry.get("command_text")
        }
        self.assertLessEqual(recorded - set(EXEMPT_CLASSES), driven,
                             "dispatching classes without a driven case")

    # -- TreeXML / APIver (recorded fragment shapes) ---------------------------

    def test_treexml_completes_on_the_snippet_wrapper(self):
        # The derived TreeXML class appends 347 rows; a network without a
        # modeled snapshot wraps its unsupported row and still completes on
        # the 344 End row Toolkit parses (its own "everything else ignored"
        # policy yields an empty XML document).
        response = self.command("TREEXML //TEST")
        self.assertEqual(response.status, 344, response.final)
        self.assertTrue(response.final.startswith("344 "), response.final)
        self.assertFalse([row for row in response.lines[:-1]
                          if row.startswith("347-")], response.lines)

    def test_apiver_reports_the_recovered_138_x_equals_a_b_fragments(self):
        response = self.command("apiver")
        self.assertEqual(response.status, 138, response.final)
        rows = list(response.lines) + [response.final]
        self.assertTrue(any(row.startswith("138-cmd-syntax=") for row in rows),
                        rows)

    def test_transform_migrate_sql_streams_199_rows_then_200_ok(self):
        response = self.command("TRANSFORM MIGRATE_SQL TEST")
        self.assertEqual(response.status, 200, response.final)
        joined = "\n".join(response.lines)
        self.assertIn("DBVersions match", joined, response.lines)
        self.assertTrue(response.final.startswith("200 OK"), response.final)
        # Toolkit starts an upgrade flow only when the success body names
        # dbversion/schemaversion (issue #161 OKSuccessClasses); the mock
        # migration body must stay free of both tokens.
        self.assertNotIn("dbversion", joined)
        self.assertNotIn("schemaversion", joined)

    # -- PortProbe (230 ok) ----------------------------------------------------

    def test_port_probe_bare_name_replies_230_ok(self):
        response = self.command("port probe COM1")
        self.assertEqual(response.status, 230, response.final)
        self.assertEqual(response.final, "230 ok", response.final)

    # -- Transform project / migrate_sql (199 rows then 200 OK) ----------------

    def test_transform_project_streams_199_rows_then_200_ok(self):
        response = self.command("transform project --test TEST")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 OK.", response.final)
        for row in response.lines[:-1]:
            self.assertTrue(row.startswith("199-"), row)
            self.assertTrue(("DBVersions match" in row)
                            or row.startswith("199-Transform from"), row)
        self.assertTrue(any("DBVersions match" in row
                            for row in response.lines), response.lines)

    def test_transform_project_without_test_flag_uses_the_same_shape(self):
        response = self.command("transform project TEST")
        self.assertEqual(response.status, 200, response.final)
        self.assertTrue(any("DBVersions match" in row for row in response.lines))

    def test_transform_project_success_bodies_avoid_upgrade_tokens(self):
        # Toolkit starts its DB upgrade flow when a 200 OK body mentions
        # dbversion/schemaversion; the successful transform's 200 row must
        # not. The recorded `199-DBVersions match` data row is separate.
        response = self.command("transform project --test TEST")
        self.assertNotIn("dbversion", response.final.lower())
        self.assertNotIn("schemaversion", response.final.lower())

    def test_transform_new_verb_replies_an_unknown_project_refusal(self):
        response = self.refusal("transform project --test NOSUCHPROJECT")
        self.assertTrue(response.final.startswith("408"), response.final)

    def test_transform_migrate_sql_uses_the_logged_transform_shape(self):
        response = self.command("TRANSFORM MIGRATE_SQL TEST")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 OK.", response.final)
        self.assertTrue(any("DBVersions match" in row for row in response.lines))

    # -- ConfigGet / ConfigGetSetOB (value rows then 303 finish) ---------------

    def test_config_obget_streams_a_value_row_and_finishes_on_303(self):
        response = self.command("config obget cgate command-port")
        self.assertEqual(response.status, 303, response.final)
        self.assertTrue(response.final.startswith("303"), response.final)
        self.assertTrue(any(row.startswith("300-command-port=")
                            for row in response.lines), response.lines)

    def test_config_obget_terminates_so_toolkit_sees_the_303_finish(self):
        # The final row must be a 303 row with nothing after the code: the
        # class reads the value rows as continuations and completes on 303.
        response = self.command("config obget cgate command-port")
        self.assertEqual(response.final, "303 ", response.final)
        self.assertTrue(all(row.startswith("300-")
                            for row in response.lines[:-1]), response.lines)

    def test_config_obset_writes_the_value_and_finishes_on_303(self):
        response = self.command("config obset cgate event-millis 250")
        self.assertEqual(response.status, 303, response.final)
        self.assertEqual(response.final, "303 ", response.final)
        self.assertTrue(any(row == "300-event-millis=250"
                            for row in response.lines), response.lines)
        readback = self.command("config obget cgate event-millis")
        self.assertTrue(any(row == "300-event-millis=250"
                            for row in readback.lines), readback.lines)

    def test_config_obget_refuses_an_unresolvable_object(self):
        response = self.refusal("config obget //MISSING/254 command-port")
        self.assertTrue(response.final.startswith("401"), response.final)
        self.assertIn("Bad object or device ID", response.final)

    def test_config_obget_syntax_error_fails_the_recovered_way(self):
        response = self.refusal("config obget cgate")
        self.assertTrue(response.final.startswith("400"), response.final)
        self.assertTrue(response.final.startswith("400 Syntax Error"),
                        response.final)

    # -- AIRCON methods (queued for sending / method not found) ----------------

    def test_aircon_lowercase_method_surface_is_queued_for_sending(self):
        #Toolkit's method facade spells the aircon method in lowercase; its
        # parser searches for the recovered fragment in the reply row.
        response = self.command("AIRCON set_ward_off 254/172 1")
        self.assertEqual(response.status, 200, response.final)
        self.assertIn("queued for sending", response.final, response.final)

    def test_aircon_set_zone_hvac_mode_method_surface_is_queued_too(self):
        response = self.command(
            "AIRCON set_zone_hvac_mode 254/172 1 0,1,2 3 0 1 0 1 255 23 64")
        self.assertEqual(response.status, 200, response.final)
        self.assertIn("queued for sending", response.final, response.final)

    def test_aircon_unknown_method_reports_the_recovered_text(self):
        response = self.refusal("AIRCON set_bogus_thing 254/172 1")
        self.assertEqual(response.status, 402, response.final)
        self.assertIn("method set_bogus_thing not found", response.final)

    def test_aircon_uppercase_console_grammar_stays_native(self):
        # The captured console envelope (native_cgate_aircon.json) must keep
        # its native shape; only Toolkit's method facade packs its own text.
        known = self.command("AIRCON SET_WARD_OFF 254/172 1")
        self.assertEqual(known.status, 200, known.final)
        self.assertEqual(known.final, "200 OK.", known.final)
        unknown_ward = self.refusal("AIRCON SET_WARD_OFF 254/172")
        self.assertTrue(unknown_ward.final.startswith("400"), unknown_ward.final)

    # -- NetTextFamily: checkunit ("200 ok") -----------------------------------

    def test_net_checkunit_final_row_matches_the_200_ok_text(self):
        response = self.command("net checkunit //TEST/254 20,21")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 ok", response.final)
        rows = response.lines[:-1]
        self.assertTrue(all(row.startswith("120-") for row in rows),
                        response.lines)
        self.assertTrue("120-Single unit detected at address: 20" in rows,
                        response.lines)

    def test_net_checkunit_empty_network_selection_fails_closed(self):
        response = self.refusal("net checkunit //TEST/254 300")
        self.assertTrue(response.final.startswith("400"), response.final)

    # -- DBRenameNet ("200 ok" / "bad object") ---------------------------------

    def test_dbrenamenet_success_reports_the_recovered_200_ok_text(self):
        # Ordered late: the rename retargets the deterministic workspace.
        response = self.command("dbrenamenet 254 253")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 ok", response.final)

    def test_dbrenamenet_refuses_unknown_networks_as_recorded(self):
        response = self.refusal("dbrenamenet 299 300")
        self.assertEqual(response.status, 401, response.final)
        self.assertIn("Bad object or device ID", response.final)

    def test_dbrenamenet_refuses_non_numeric_sources(self):
        response = self.refusal("dbrenamenet NOPE 253")
        self.assertEqual(response.status, 401, response.final)
        self.assertIn("Bad object or device ID", response.final)

    # -- PPGetUnitSpecCatalog (408 No Catalog Available / 347 rows) -------------

    def test_pp_get_unit_catalog_without_catalogue_reports_the_recorded_408(self):
        response = self.refusal("PP GET_UNIT_CATALOG")
        self.assertEqual(response.status, 408, response.final)
        self.assertEqual(response.final, "408 No Catalog Available", response.final)

    # -- calculator test (failure stays reachable; capture pending) ------------

    def test_calculator_test_failure_classifies_as_a_408_catalog_refusal(self):
        # A native capture for the success shape is still pending (issue
        # #160); only the recorded failure class (408 with a catalogue cause)
        # is asserted. Toolkit's own calculator client checks this class of
        # reply in its catch-all branch today.
        response = self.refusal("calculator test //TEST/254")
        self.assertEqual(response.status, 408, response.final)
        self.assertIn("catalog", response.final.lower())

    # -- Event (200 / 306 for the accepted modes; 408 stays for bad strings) ---

    def test_event_mode_words_accepted_by_toolkit_replay_200(self):
        for word in ("c0", "c1", "s0", "s1", "e+", "e0", "e9", "e0s1c1"):
            with self.subTest(word=word):
                response = self.command(f"event {word}")
                self.assertEqual(response.status, 200, response.final)

    def test_event_genuinely_bad_mode_strings_keep_the_408_row(self):
        response = self.refusal("event x9")
        self.assertEqual(response.status, 408, response.final)
        self.assertIn("Bad mode string", response.final)

    # -- KFIGet ("300-kfi…" rows then "300 kfi…") -------------------------------

    def test_label_kfiget_without_dataset_replies_the_final_kfi_row(self):
        response = self.command("label kfiget //TEST/254 8")
        self.assertEqual(response.status, 300, response.final)
        # The recovered final-row fragment shape: the last row begins
        # "300 kfi" and the dataset keyed by this group is empty, so the
        # reply is the single final row for that group.
        self.assertEqual(response.final, "300 kfi8", response.final)
        self.assertEqual(list(response.lines), [("300 kfi8")], response.lines)

    def test_label_kfiget_streams_kfi_continuation_rows_then_the_final_row(self):
        # A prior KFISET round-trip writes the mock's own (target, group)
        # dataset; its words become the kfi continuation rows and the final
        # row still identifies the group. No native KFI word content is
        # modelled beyond this own-data round trip.
        self.assertEqual(self.command("LABEL KFISET //TEST/254 8 1 2 3").status, 200)
        response = self.command("label kfiget //TEST/254 8")
        self.assertEqual(response.status, 300, response.final)
        self.assertEqual(response.final, "300 kfi8", response.final)
        self.assertEqual(list(response.lines[:-1]),
                         ["300-kfi1", "300-kfi2", "300-kfi3"], response.lines)

    def test_label_kfiget_syntax_refuses_when_the_group_is_missing(self):
        response = self.refusal("label kfiget //TEST/254")
        self.assertTrue(response.final.startswith("400"), response.final)

    # -- SendCALIdentify ("300 … Response=" final row) --------------------------

    def test_send_literal_completes_on_a_response_row(self):
        response = self.command("send 254 0021")
        self.assertEqual(response.status, 300, response.final)
        self.assertEqual(response.final, "300 Response=", response.final)
        # A closed network reports the native send-error row first; the
        # reply still completes on the 300 Response= row Toolkit expects.
        self.assertTrue(any(row.startswith("524-") for row in response.lines[:-1]),
                        response.lines)

    # -- StartBackgroundJob -----------------------------------------------------

    def test_start_background_job_known_job_replies_200_ok(self):
        response = self.command("START_BACKGROUND_JOB XmlToSqlTransformJob")
        self.assertEqual(response.status, 200, response.final)

    def test_start_background_job_unknown_job_refuses_the_recovered_syntax(self):
        response = self.refusal("START_BACKGROUND_JOB Nope")
        self.assertEqual(response.status, 400, response.final)
        self.assertIn("background job is not defined", response.final.lower())

    # -- Shutdown / ShutdownConfirm ---------------------------------------------

    def test_shutdown_and_confirm_reply_their_recorded_rows(self):
        self.assertEqual(self.client.command("shutdown").status, 600)
        response = self.command("confirm")
        self.assertEqual(response.status, 206, response.final)

    # -- NetClock (120- rows with address=, final 200 OK) -----------------------

    def test_net_clocks_streams_address_rows_and_finishes_on_200_ok(self):
        response = self.command("NET CLOCKS //TEST/254 3")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 OK", response.final)
        rows = response.lines[:-1]
        self.assertTrue(rows, response.lines)
        for row in rows:
            self.assertTrue(row.startswith("120-"), row)
            self.assertIn("address=", row)

    # -- PortCNIScan (129 rows, "130 " finishes) --------------------------------

    def test_port_cniscan_streams_129_rows_and_finishes_on_the_130_row(self):
        try:
            response = self.command("port cniscan 192.0.2.255")
        except CGateError:
            self.fail("port cniscan did not complete on the 130 row")
        self.assertEqual(response.status, 130, response.final)
        for row in response.lines[:-1]:
            self.assertTrue(row.startswith("129-"), row)
            self.assertTrue(("status=" in row) or ("type=" in row), row)

    # -- FileDir / Download (304/305 and 345 rows) ------------------------------

    def test_file_dir_lists_directory_rows_for_the_virtual_root(self):
        first = self.command("file dir")
        self.assertEqual(first.status, 304, first.final)
        self.assertTrue(first.final.startswith("304 "), first.final)
        self.command("FILE MKDIR paperwork")
        listed = self.command("file dir")
        self.assertIn(listed.status, (304, 305), listed.final)
        self.assertTrue(any('name="paperwork/"' in row for row in listed.lines),
                         listed.lines)

    def test_file_download_streams_the_345_envelope_after_an_upload(self):
        # The retained native FILE round-trip envelope: a 345 start row, 347
        # base64 data rows and the 346 end row (native_cgate_file.json).
        upload = self.client.command_document(
            "FILE UPLOAD conformance.txt",
            "Y2dhdGUtbW9jay1jb25mb3JtYW5jZS1wYXlsb2Fk",
        )
        self.assertEqual(upload.status, 200, upload.final)
        response = self.command("file download conformance.txt")
        self.assertEqual(response.status, 346, response.final)
        self.assertTrue(any(row.startswith("345-") for row in response.lines[:-1]),
                        list(response.lines))

    def test_file_download_of_a_missing_file_reports_an_operation_failure(self):
        response = self.refusal("file download missing.xml")
        self.assertEqual(response.status, 408, response.final)

    # -- LOGIN quirk (documented; no behavior change asserted) ------------------

    def test_native_login_quirk_is_commented_not_reverted(self):
        # Toolkit's own parser only knows 210/400/422 while native C-Gate
        # answers `LOGIN user password` with 211. The mock keeps native
        # behavior; conformance only requires that no code has been flipped
        # to a Toolkit-friendly spelling here (that belongs to the separate
        # LOGIN/#159 slice).
        self.skipTest("LOGIN's native 211 quirk is owned by the LOGIN/#159 slice")


DRIVEN_CLASSES = (
    # reply checks driven case by case above, ordered per inventory.json
    "ConfigGet", "ConfigGetSetOB", "PortProbe", "KFIGet", "Download",
    "FileDir", "PortCNIScan", "Shutdown", "ShutdownConfirm",
    "DBRenameNet", "PPGetUnitSpecCatalog", "TreeXML", "APIver",
    "TransformReplyFamily",
)

# Classes with a recorded `command_text` outside #160's tables. TcgcIdentify's
# reply shape belongs to the LOGIN/ID/#159 slice, whose native rows are not
# in this worktree yet; pinning the pre-#159 400 row here would mislabel the
# mock. TreeXML and APIver are driven below.
EXEMPT_CLASSES = ("TcgcIdentify",)


if __name__ == "__main__":
    unittest.main()
