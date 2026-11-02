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

Wave 2 (issues #166/#167/#168/#169 and #164) adds the recorded checks for
the dispatching client classes that #160 left open:

- the PP session family: ``PP GET``/``PP QUICKGET``, lock/start/end,
  list/units, load/save, ``LOAD_FROM_FILE`` and ``RESET_TO_DEFAULTS``;
- ``NET SYNC``'s captured ``120-Net Sync: …`` progress family, the
  ``SYNCNEW`` recorded 408 finishes, and the unravel accepted rows;
- ``LABEL KFISET``/``CLEAREDLT``/``CLEAR`` and the recorder's EVENT envelopes;
- the ``TRANSFORM PROJECT --xslt-file/--output-file`` edge shapes bound to
  ``research/fixtures/project-legacy-transform-versions-native-receipt.json``
  (the owned native runs) and ``docs/project-legacy-transform.md``.

Recorded fragments whose native shape needs a physical peer (the unravels of
``service``) or the vendor XSLT engine stay out: they are listed in the
report as gaps and their cases still assert every recorded fragment the
model surface can produce. Nothing in this suite invents reply text; every
assertion quotes the issue's recorded fragments, the committed native
fixtures or the shipped #160 record.
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

    def test_port_list_streams_125_rows_and_finishes_on_the_125_row(self):
        # A populated list completes on `125 ` rows; the native empty-list
        # completion is the recovered `126 no ports found` row.
        response = self.command("port list")
        self.assertIn(response.status, (125, 126), response.final)
        if response.status == 126:
            self.assertIn("no ports", response.final, response.final)
            self.assertFalse([row for row in response.lines
                              if row.startswith("125-")], response.lines)
        else:
            self.assertTrue(response.final.startswith("125"), response.final)
            self.assertTrue(all(row.startswith("125-") or row.startswith("125 ")
                                for row in response.lines), response.lines)

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

    # -- PPGet / PPQuickGet (#167; inventory PPGetPPQuickGet) -------------------

    def test_pp_get_after_sets_streams_315_rows_and_ends_on_the_315_row(self):
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        self.assertEqual(self.command("PP SET S1 UnitName Alice").status, 200)
        self.assertEqual(self.client.command('PP SET S1 Note "Hello World"').status, 200)
        response = self.command("PP GET S1 *")
        self.assertEqual(response.status, 315, response.final)
        # The recovered final-row shape: the table completes on a `315 ` row
        # after `315-` continuation rows.
        self.assertTrue(response.final.startswith("315 UnitName="), response.final)
        self.assertIn("315-Note=Hello World", response.lines, response.lines)

    def test_pp_get_single_value_completes_on_the_315_row(self):
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        self.assertEqual(self.command("PP SET S1 UnitName Alice").status, 200)
        response = self.command("PP GET S1 UnitName")
        self.assertEqual(response.status, 315, response.final)
        self.assertEqual(list(response.lines), ["315 UnitName=Alice"], response.lines)

    def test_pp_get_missing_parameter_reports_the_recorded_no_such_parameter_text(self):
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        response = self.refusal("PP GET S1 NoParameter")
        # Toolkit's own class rejects exactly this text (issue #167). The
        # 460 code is the OKSuccessClasses reject-family code the #160
        # record adopts for this fragment; the PP class records the text.

        self.assertEqual(response.status, 460, response.final)
        self.assertIn("No such parameter", response.final)

    def test_pp_quickget_streams_the_cached_database_row_until_the_315_row(self):
        response = self.command("PP QUICKGET //TEST/254/p/20 UnitName")
        self.assertEqual(response.status, 315, response.final)
        self.assertEqual(response.final, "315 UnitName=Lounge", response.final)

    def test_pp_quickget_missing_parameter_reports_the_recorded_parameter_text(self):
        response = self.refusal("PP QUICKGET //TEST/254/p/20 Nope")
        self.assertIn("Parameter not found", response.final)

    def test_pp_quickget_missing_unit_reports_the_recorded_401_element_row(self):
        response = self.refusal("PP QUICKGET //TEST/254/p/21 UnitName")
        # The recorded NP reject fragment: `401 Element … not found`; the
        # mock phrases it with the canonical "Bad object or device ID" family
        # the DB records capture (native_cgate_cross_kind_oid_mutations.json).
        self.assertTrue(response.final.startswith("401"), response.final)
        self.assertIn("Element", response.final)
        self.assertIn("not found", response.final)

    def test_managed_pp_get_462_rows_are_recorded_but_not_modelled_here(self):
        # issue #167: "Managed PPGet also accepts 462". The mock emits 462
        # rows only as PP LOAD range advisories, which need a configured
        # unitspec directory (manual.rs has no 462 emitter of its own), so no
        # case is drivable in this suite and none is invented.
        self.skipTest(
            "462 advisory rows are PP LOAD catalogue warnings; unreachable "
            "without a unitspec directory, so not driven (inventory note)")

    # -- PP lock/start/end/cancel/list/units family (#167) ----------------------

    def test_pp_lock_second_lock_reports_the_recorded_425_text(self):
        self.assertEqual(self.command("PP LOCK L1 //TEST/254").status, 200)
        response = self.refusal("PP LOCK L1 //TEST/254")
        self.assertEqual(response.final, "425 Lock failed", response.final)

    def test_pp_unlock_missing_lock_reports_the_recorded_426_text(self):
        response = self.refusal("PP UNLOCK missing")
        self.assertEqual(response.status, 426, response.final)
        self.assertIn("Unlock failed", response.final)

    def test_pp_lock_start_end_cancel_hold_the_recorded_200_rows(self):
        self.assertEqual(self.command("PP LOCK L1 //TEST/254").status, 200)
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        self.assertEqual(self.command("PP END S1").status, 200)
        self.assertEqual(self.client.command("PP CANCEL_LOCK //TEST/254").status, 200)

    def test_pp_list_lock_streams_the_121_rows(self):
        # The 121 completion/row count is recorded; the `name=… address=…`
        # row text is a mock-surface pin (no native capture records the row
        # serialization; captures only record `122 no open locks`).
        self.assertEqual(self.command("PP LOCK L2 //TEST/254").status, 200)
        response = self.client.command("PP LIST_LOCK")
        self.assertEqual(response.status, 121, response.final)
        self.assertTrue(any("name=L2 address=//TEST/254" in row
                            for row in response.lines), response.lines)

    def test_pp_units_reports_121_rows_then_the_recorded_no_open_sessions_case(self):
        # The 121 completion and the recorded `no open sessions` case are
        # captured; success-row text stays a mock-surface pin.
        self.assertEqual(self.command("PP LOCK L1 //TEST/254").status, 200)
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        opened = self.client.command("PP UNITS")
        self.assertEqual(opened.status, 121, opened.final)
        self.assertTrue(any("name=S1 address=//TEST/254" in row
                            for row in opened.lines), opened.lines)
        self.command("PP END S1")
        closed = self.client.command("PP UNITS")
        self.assertEqual(closed.status, 122, closed.final)
        self.assertIn("no open sessions", closed.final)

    def test_pp_load_from_file_keeps_the_recorded_missing_session_row(self):
        # The suite runs without a unitspec directory, so the recovered 200 OK
        # success (issue #167: OKSuccessClasses) belongs to the unitspec
        # suites; the record's missing-session row is drivable here.
        response = self.refusal("PP LOAD_FROM_FILE missing missing.xml")
        self.assertEqual(response.status, 408, response.final)
        self.assertIn("Programming session not found", response.final)

    def test_pp_load_failures_of_the_new_session_fall_in_the_recovered_rows(self):
        # The deterministic workspace unit carries no unit type, so the
        # database-seeded load refuses exactly like native (the "408
        # Operation failed: …" row Toolkit's PPLoad class would classify).
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        response = self.refusal("PP LOAD S1 /db//TEST/254/p/20")
        self.assertEqual(response.status, 408, response.final)

    def test_pp_save_completes_on_the_save_family_200_rows(self):
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        self.assertEqual(self.command("PP SET S1 Note Staged").status, 200)
        self.assertEqual(self.command("PP SAVE S1 /db//TEST/254/p/20").status, 200)
        self.assertEqual(self.command("PP SAVE_TO_SOURCE S1").status, 200)

    def test_pp_load_save_progress_fragments_stay_physical_pp_cases(self):
        # The recorded PPLoad/PPSave fragments (`120-read a/b`,
        # `120-saved a/b`) are the physical programming-method peer replies
        # (issue #167, and the owned native transcripts in
        # rust/testdata/fixtures/native_cgate_pp_method_transcripts.json
        # bind the exact rows to physical sessions). The model's session is
        # database/staged: it has no device read/write channel and inventing
        # byte counts would fabricate device state, so these fragments stay
        # on the physical surface.
        self.skipTest(
            "read/saved byte progress rows are physical programming-method "
            "peer replies; the model surface never invents the counts")

    def test_pp_reset_to_defaults_replies_the_recovered_rows(self):
        self.command("PP LOCK L1 //TEST/254")
        self.assertEqual(self.command("PP START S1 L1").status, 200)
        # issue #167's reset flow: `pp load`, `pp reset_to_defaults`, `pp get`
        # — the reset answer is the OKSuccessClasses 200 OK. The recorded
        # missing-session probe row (native programming probe) is drivable
        # before that:
        self.assertEqual(
            self.refusal("PP RESET_TO_DEFAULTS missing").final,
            "408 Operation failed: Programming session not found")
        self.assertEqual(self.command("PP RESET_TO_DEFAULTS S1").status, 200)

    # -- NET SYNC (issue #166 NetSync fragments) ---------------------------------

    def test_net_sync_streams_the_recorded_rows_then_the_captured_200_end(self):
        self.assertEqual(self.command("NET OPEN //TEST/254").status, 200)
        response = self.command("NET SYNC //TEST/254 fast")
        self.assertEqual(response.code, 200, response.final)
        rows = [*response.lines, response.final]
        # The exact recorded fragments of issue #166, streamed as `120-`
        # progress rows in the order the owned runs captured:
        self.assertTrue(rows[0].startswith("120-Net Sync: started at "), rows)
        self.assertTrue(any("Unit error count: " in row for row in rows), rows)
        self.assertTrue(any("Unit errors at: " in row for row in rows), rows)
        self.assertTrue(any("Units at: 20" in row for row in rows), rows)
        # The owned capture (docs/native-duplicate-discovery-acceptance.json,
        # rust/testdata/fixtures/native_cgate_unravel_cases.json) ends this
        # family on the plain `200 OK.` row, which both Toolkit's class and
        # the shared parser accept. (The client's `lines` include the final
        # row, so the progress rows are `lines[:-1]`.)
        self.assertEqual(response.final, "200 OK.", response.final)
        self.assertTrue(
            all(row.startswith("120-") for row in response.lines[:-1]),
            response.lines,
        )

    def test_net_sync_rety_fragment_rows_are_stable_across_retries(self):
        self.assertEqual(self.command("NET OPEN //TEST/254").status, 200)
        for retries in (None, "2"):
            with self.subTest(retries=retries):
                command = "NET SYNC //TEST/254" + (f" {retries}" if retries else "")
                response = self.command(command)
                self.assertEqual(response.code, 200, response.final)
                self.assertTrue(any("Unit error count: " in row
                                    for row in response.lines), response.lines)

    def test_net_sync_duplicate_marker_rows_stay_pci_peer_cases(self):
        # issue #166 also records a DUPLICATE marker for NET SYNC. No owned
        # capture pins a mocked row shape for it (the duplicate-aware runs
        # report it via the checkunit rows and the syncnew 303 family), and
        # the model surface cannot express two units at one address.
        self.skipTest(
            "net sync DUPLICATE rows need a duplicate physical inventory; not modelled")

    # -- NET SYNCNEW (issue #166 NetSyncNew fragments) ----------------------------

    def test_net_syncnew_selected_unit_in_the_model_answers_in_the_model_record(self):
        # The one recorded SYNCNEW finish this model surface answers itself:
        # a modeled address is claimed before any discovery, exactly as the
        # service crate's own pre-check returns it (issue #166).
        response = self.refusal("NET SYNCNEW //TEST/254 20")
        self.assertEqual(response.status, 408, response.final)
        self.assertEqual(response.final, "408 Operation failed: Unit already in model",
                         response.final)

    def test_net_syncnew_staged_discovery_finishes_stay_service_cases(self):
        # `Unit at given address not found`, `No new units found`, the `New
        # Unit Found` and `303 Duplicate Units Found` rows are reached after
        # the installation-MMI scan (and cmqttd's peer tests assert their
        # exact rows there). The service crate stages SYNCNEW through this
        # model before its own discovery, so this surface keeps the 200
        # staged acceptance and cannot answer those rows without hanging the
        # shared flow.
        self.skipTest(
            "recorded finishes need the install-MMI scan; service.rs owns them")

    # -- NET UNRAVEL (issue #166 NetUnravel checks) -------------------------------

    def test_net_unravel_completes_on_the_accepted_200_ok_row(self):
        for command in ("NET UNRAVEL //TEST/254",
                        "NET UNRAVEL //TEST/254 20",
                        "NET UNRAVEL //TEST/254 MATCHDB"):
            with self.subTest(command=command):
                self.assertEqual(self.command(command).status, 200)

    def test_net_unravelunit_completes_on_the_captured_200_ok_row(self):
        # rust/testdata/fixtures/native_cgate_unravel_cases.json pins every
        # native UNRAVELUNIT capture at "200 OK."; the model answer stays
        # inside that captured completion.
        response = self.command("NET UNRAVELUNIT //TEST/254 20")
        self.assertEqual(response.status, 200, response.final)

    def test_unravel_progress_and_error_rows_are_pci_peer_cases(self):
        self.skipTest(
            "120-Unravel rows and the recorded MMI-budget/refusal rows use the "
            "UnravelBusFixture peer; the model surface has no MMI scan")

    # -- LABEL KFISET / CLEAREDLT / CLEAR (issues #168, #169) ---------------------

    def test_label_kfiset_replies_the_200_ok_success_class(self):
        self.assertEqual(self.command("LABEL KFISET //TEST/254 8").status, 200)

    def test_label_clear_reports_the_recorded_200_ok_row(self):
        self.assertEqual(self.command("LABEL CLEAR //TEST/254/56 20").status, 200)

    def test_label_clearedlt_reports_the_200_ok_row(self):
        response = self.command("LABEL CLEAREDLT //TEST/254/p/20")
        self.assertEqual(response.status, 200, response.final)
        self.assertEqual(response.final, "200 OK.", response.final)

    # -- TRANSFORM PROJECT --xslt-file/--output-file edges (#164) -----------------

    def _stage_stylesheet(self):
        """Stage a server-side stylesheet name in the mock's virtual FILE root.

        The recorded native run resolved its stylesheet from the server
        working directory (`transform/v22tov23.xslt`); the mock binds server
        side paths to its process-local virtual FILE namespace, which the
        suite stages with FILE MKDIR/UPLOAD exactly like the recorded
        harness staged the vendor file.
        """
        self.assertEqual(self.command("FILE MKDIR transform").status, 200)
        upload = self.client.command_document(
            "FILE UPLOAD transform/v22tov23.xslt",
            "dGVzdC1zdHlsaXNoZWV0LWV2aWRlbmNl")
        self.assertEqual(upload.status, 200, upload.final)

    def _stage_output(self):
        """Stage the pre-existing server-side output file the record requires."""
        self.assertEqual(self.command("FILE MKDIR output").status, 200)
        upload = self.client.command_document(
            "FILE UPLOAD output/VOUT.xml", "b3duZWQtb3V0cHV0LXNlbnRpbmVs")
        self.assertEqual(upload.status, 200, upload.final)

    def test_transform_explicit_stylesheet_test_plan_replies_the_recorded_rows(self):
        # project-legacy-transform-versions-native-receipt.json
        # `custom_stylesheet_output.preview`: the exact 199 rows and `200 OK.`
        self._stage_stylesheet()
        response = self.command(
            "TRANSFORM PROJECT --test TEST transform/v22tov23.xslt")
        self.assertEqual(list(response.lines[:-1]),
                         ["199-Calculated transform list:",
                          "199-Transform with XSLT file: transform/v22tov23.xslt"],
                         response.lines)
        self.assertEqual(response.final, "200 OK.", response.final)

    def test_transform_explicit_stylesheet_save_records_the_accepted_run(self):
        # The recorded shape is exactly one 200 row for a pre-existing
        # output file; the mock's virtual namespace has no file engine, so
        # the output bytes stay unmutated here and only the reply shape is
        # pinned (the byte-overwrite lives in the native/service engine).
        self._stage_stylesheet()
        self._stage_output()
        response = self.command(
            "TRANSFORM PROJECT TEST transform/v22tov23.xslt output/VOUT.xml")
        self.assertEqual(list(response.lines[:-1]), [], response.lines)
        self.assertEqual(response.final, "200 OK.", response.final)
        # The recorded run created no source backup and left the source; the
        # mock's virtual namespace still names the original output file, and
        # no `.0` side artifact appeared.
        self.assertFalse(
            [row for row in self.client.command("file dir output").lines
             if re.search(r'name="VOUT\.xml\.0"', row)],
            self.client.command("file dir output").lines)

    def test_transform_missing_stylesheet_reports_the_recorded_408_fragment(self):
        response = self.refusal("TRANSFORM PROJECT TEST no-such.xslt")
        self.assertTrue(response.final.startswith("408"), response.final)
        self.assertIn("xslt file not found", response.final)

    def test_transform_missing_output_reports_the_recorded_no_write_permission_row(self):
        self._stage_stylesheet()
        response = self.refusal(
            "TRANSFORM PROJECT TEST transform/v22tov23.xslt output/ABSENT.xml")
        self.assertTrue(response.final.startswith("408"), response.final)
        self.assertIn("No write permission for output file", response.final)

    def test_transform_extra_tokens_keep_the_400_syntax_family_row(self):
        self._stage_stylesheet()
        response = self.refusal(
            "TRANSFORM PROJECT TEST transform/v22tov23.xslt output/VOUT.xml extra")
        self.assertTrue(response.final.startswith("400"), response.final)
        self.assertIn("Syntax Error", response.final)

    # -- LOGIN quirk (documented; no behavior change asserted) ------------------

    # The LOGIN native 211 quirk stays unmodelled in this mock: Toolkit's own
    # parser only knows 210/400/422 while native C-Gate answers
    # `LOGIN user password` with 211. cgate-mock keeps the native spelling;
    # the Toolkit-friendly shape belongs to the separate LOGIN/#159 slice.


DRIVEN_CLASSES = (
    # reply checks driven case by case above, ordered per inventory.json
    "ConfigGet", "ConfigGetSetOB", "PortProbe", "KFIGet", "Download",
    "FileDir", "PortCNIScan", "Shutdown", "ShutdownConfirm",
    "DBRenameNet", "PPGetUnitSpecCatalog", "TreeXML", "APIver",
    "TransformReplyFamily", "PortList", "PPGetPPQuickGet", "PPUnlock",
    "PPUnits", "PPLoadPPSave", "PPListLock", "NetSync", "NetSyncNew",
    "NetUnravel", "NetClock", "NetTextFamily", "OKSuccessClasses",
)

# Classes with a recorded `command_text` outside #160's tables. TcgcIdentify's
# reply shape belongs to the LOGIN/ID/#159 slice, whose native rows are not
# in this worktree yet; pinning the pre-#159 400 row here would mislabel the
# mock. TreeXML and APIver are driven below.
EXEMPT_CLASSES = ("TcgcIdentify",)


if __name__ == "__main__":
    unittest.main()
