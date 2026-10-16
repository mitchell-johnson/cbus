"""CI results must distinguish executed calls, setup skips, and subtests."""
import ast
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from research.ci_test_results import AuditError, audit, main


FIRST = "tests/test_first.py::test_with_subtests"
SECOND = "tests/test_second.py::test_setup_skip"


class NewInteropSelectionTests(unittest.TestCase):
    """A green backend job must retain every newly accepted public journey."""

    def test_scene_selector_exact_backend_rosters_and_offline_modules(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_scene_selector_interop.py'
        profiles = ('application-secondary-selector-one','trigger-callback-action-valid-in-both',
            'action-selected-duplicate-name-exact-identity','null-current-retains-stale-action-binding',
            'scene-two-rebinding-does-not-leak-first-labels','label-selection-3')
        refusals = ('cache-injection','future-parent-action')
        for backend,target,selection in (('mock','check-cgate-interop','cgate-mock'),
                                          ('daemon','check-cmqtt-interop','cmqttd')):
            expected = {module+'::test_public_selectors_preview_apply_fresh_complete_graph['+case+'-'+backend+']' for case in profiles}
            expected |= {module+'::test_public_selector_refusals_precede_database_writes['+case+'-'+backend+']' for case in refusals}
            expected |= {module+'::test_public_selector_lost_successful_save_never_replayed['+case+'-'+backend+']' for case in ('pp-save','project-save')}
            expected.add(module+'::test_public_prior_parent_add_visible_later_add_excluded['+backend+']')
            body = make.split(target+': compile\n',1)[1].split('\n\n',1)[0]
            actual = [row for row in re.findall(r"'(tests/test_[^']+)'",body) if row.startswith(module+'::')]
            self.assertEqual(len(actual),11)
            self.assertEqual(len(actual),len(set(actual)))
            self.assertEqual(set(actual),expected)
            audit = workflow.split('--selection '+selection+'\n',1)[1].split('\n      - name:',1)[0]
            self.assertEqual(audit.count('--require-module '+module),1)
        pure = {'tests/test_edlt_scene_selectors.py','tests/test_edlt_scene_selector_control.py',
                'tests/test_edlt_scene_selector_static.py','tests/test_edlt_scene_selector_metadata.py'}
        offline = workflow.split('--selection offline\n',1)[1].split('\n      - name:',1)[0]
        for name in pure: self.assertEqual(offline.count('--require-module '+name),1)
        manifest = root/'toolkit-cli/docs/edlt-scene-selector-release-test-modules.txt'
        selected = [line.strip() for line in manifest.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(len(selected),len(set(selected)))
        self.assertEqual(len(selected),10)
        self.assertEqual(set(selected),pure | {module,'tests/test_ci_test_results.py',
            'tests/test_cli_edlt_scene_manager.py','tests/test_edlt_scene_metadata.py',
            'tests/test_edlt_parent_scene_metadata.py','tests/test_cli_edlt_parent_transaction.py'})

    def test_scene_inventory_exact_backend_rosters_and_offline_modules(self):
        root = Path(__file__).resolve().parents[2]
        make = (root/'toolkit-cli/Makefile').read_text()
        workflow = (root/'.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_scene_inventory_interop.py'
        profiles = ('action-add-explicit-rebind-sees-new-generation',
            'action-add-current-getter-view-new-old-binding-separate',
            'canceled-action-add-keeps-bound-generation','trigger-add-then-explicit-callback',
            'canceled-trigger-add-keeps-current-and-inventory','old42-choice-writes-current43-setter',
            'old42-existing-choice-current43-existing-labels','trigger-callback-creates-missing-retained-action',
            'missing-trigger-getter-requested-not-first-free','initial-loader-reserves-before-first-dialog',
            'all-eight-loader-getters-reserve-before-first-dialog',
            'later-initial-getter-keeps-earlier-label-generation','terminal-fallback-zero-not-borrowed-early')
        standalone = ('action-add-explicit-rebind-sees-new-generation',
            'missing-trigger-getter-requested-not-first-free','terminal-fallback-zero-not-borrowed-early')
        refusals = ('new-choice-stale-bound-generation','divergent-action-add-combo-target',
                    'pending-name-wrong-bound-target')
        for backend,target,selection in (('mock','check-cgate-interop','cgate-mock'),
                                        ('daemon','check-cmqtt-interop','cmqttd')):
            expected = {module+'::test_public_inventory_preview_apply_fresh_complete_graph['+case+'-'+backend+']' for case in profiles}
            expected |= {module+'::test_public_inventory_standalone_owner['+case+'-'+backend+']' for case in standalone}
            expected |= {module+'::test_public_inventory_refusal_before_creation['+case+'-'+backend+']' for case in refusals}
            expected |= {module+'::test_public_inventory_lost_successful_save_never_replayed['+case+'-'+backend+']' for case in ('pp-save','project-save')}
            expected.add(module+'::test_public_inventory_known_failure_rolls_back_created_graph['+backend+']')
            expected.add(module+'::test_public_inventory_ordered_parent_add99_scene_add2_later_add100['+backend+']')
            body = make.split(target+': compile\n',1)[1].split('\n\n',1)[0]
            actual = [row for row in re.findall(r"'(tests/test_[^']+)'",body) if row.startswith(module+'::')]
            self.assertEqual(len(actual),23)
            self.assertEqual(len(actual),len(set(actual)))
            self.assertEqual(set(actual),expected)
            section = workflow.split('--selection '+selection+'\n',1)[1].split('\n      - name:',1)[0]
            self.assertEqual(section.count('--require-module '+module),1)
        pure = {'tests/test_edlt_scene_inventory_timeline.py',
            'tests/test_edlt_scene_inventory_native_plan.py','tests/test_edlt_parent_scene_inventory.py',
            'tests/test_edlt_scene_inventory_model.py','tests/test_edlt_scene_inventory_static.py'}
        offline = workflow.split('--selection offline\n',1)[1].split('\n      - name:',1)[0]
        for name in pure: self.assertEqual(offline.count('--require-module '+name),1)
        manifest = root/'toolkit-cli/docs/edlt-scene-inventory-release-test-modules.txt'
        selected = [line.strip() for line in manifest.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        previous = root/'toolkit-cli/docs/edlt-scene-selector-release-test-modules.txt'
        retained = {line.strip() for line in previous.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')}
        self.assertEqual(len(selected),len(set(selected)))
        self.assertEqual(len(selected),16)
        self.assertEqual(set(selected),retained | pure | {module})

    def test_scene_buttons_language_reconciliation_owning_modules_and_rosters(self):
        root = Path(__file__).resolve().parents[2]
        make = (root/'toolkit-cli/Makefile').read_text()
        workflow = (root/'.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_scene_controls_language_interop.py'
        profiles = ('action-new-retains-old-items', 'action-old-selected-trigger-new-raw-trigger',
            'action-cancel', 'trigger-new-explicit-write', 'trigger-cancel',
            'lighting-zero-address', 'lighting-one-address', 'lighting-two-address',
            'lighting-secondary-zero-address', 'lighting-no-selected-row',
            'lighting-multiple-selected-rows', 'language-valid-getter-retains-old-labels',
            'language-explicit-setter', 'language-explicit-refresh', 'language-cancel',
            'language-noop', 'later-language-cannot-enter-earlier-view', 'language-and-action-old-binding')
        fault_names = ('action-new-retains-old-items', 'language-explicit-setter')
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                           ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {module+'::test_public_controls_language_preview_apply_fresh['+name+'-'+backend+']'
                        for name in profiles}
            expected |= {module+'::test_public_controls_language_known_failure_restores_source['+name+'-'+backend+']'
                         for name in fault_names}
            expected |= {module+'::test_public_controls_language_lost_success_never_replayed['+phase+'-'+name+'-'+backend+']'
                         for phase in ('pp-save', 'project-save') for name in fault_names}
            body = make.split(target+': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/test_[^']+)'", body)
                      if row.startswith(module+'::')]
            self.assertEqual(len(actual), 24)
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            section = workflow.split('--selection '+selection+'\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(section.count('--require-module '+module), 1)
        pure = {'tests/test_edlt_scene_button_control.py', 'tests/test_edlt_scene_button_model.py',
            'tests/test_edlt_scene_button_native.py', 'tests/test_edlt_scene_language_initializer.py',
            'tests/test_edlt_scene_language_native.py', 'tests/test_edlt_parent_scene_language.py',
            'tests/test_toolkit_obligation_reconcile.py', 'tests/test_cli_coverage_reconcile.py'}
        offline = workflow.split('--selection offline\n', 1)[1].split('\n      - name:', 1)[0]
        for name in pure:
            self.assertEqual(offline.count('--require-module '+name), 1)
        def names(path):
            return [line.strip() for line in path.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        selected = names(root/'toolkit-cli/docs/edlt-scene-controls-language-release-test-modules.txt')
        retained = names(root/'toolkit-cli/docs/edlt-scene-inventory-release-test-modules.txt')
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(len(selected), 25)
        self.assertEqual(set(selected), set(retained) | pure | {module})

    def test_make_and_ci_retain_exact_new_backend_rosters(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / "toolkit-cli/Makefile").read_text()
        workflow = (root / ".github/workflows/ci.yml").read_text()
        modules = ("test_cgate_toolkit_tweaker_remaining_interop.py",
                   "test_cgate_csv_completion_interop.py",
                   "test_cgate_edlt_parent_add_dialog_interop.py")
        cases = (
            "neo-secondary-mask-removal-before-area-reshape",
            "neo-matching-application-object-removes-primary-too",
            "neo-unused-secondary-keeps-lexical-application",
            "neo-all-secondary-area-is-independent",
            "dali-forward-swap-decimal", "dali-catalogue-alias-forward",
            "dali-reverse-swap", "dali-alias-reverse-swap",
            "older-pir-six-default-fields-and-polarity-aligned",
            "older-pir-self-retains-fresh-learning-history",
            "older-light-level-self-no-st7-lux-rewrite",
            "older-light-level-to-multisensor-rename-and-fresh-unassigned-groups",
            "older-multisensor-self-input-flag-overridden-and-join-reset",
        )
        remaining = "tests/" + modules[0] + "::"
        csv = "tests/" + modules[1] + "::"
        parent = "tests/" + modules[2] + "::"
        for backend, target, selection in (
                ("mock", "check-cgate-interop", "cgate-mock"),
                ("daemon", "check-cmqtt-interop", "cmqttd")):
            with self.subTest(backend=backend):
                expected = {
                    remaining + "test_public_remaining_conversion_literal_and_lifecycle["
                    + case + "-" + operation + "-" + backend + "]"
                    for case in cases for operation in ("create", "replace")}
                expected.update(remaining + "test_public_remaining_conversion_lost_success_never_replays["
                                + action + "-" + backend + "]"
                                for action in ("create-PP SAVE_TO_SOURCE", "replace-DBDELETE"))
                expected.update(csv + name + "[" + suffix + backend + "]" for name, suffix in (
                    ("test_public_csv_completion_all_templates_and_ordered_selection", ""),
                    ("test_public_csv_completion_late_refusal_is_atomic", "bad-profile-"),
                    ("test_public_csv_completion_late_refusal_is_atomic", "missing-application-"),
                    ("test_public_csv_completion_lost_snapshot_is_not_retried", "")))
                expected.update(parent + "test_public_parent_add_history_one_save_and_full_preservation["
                                + case + "-" + backend + "]"
                                for case in ("corridor-and-activation", "cancel-repeat",
                                             "preceding-enable", "scene-interleave",
                                             "initial-scene-getter", "corridor-future-absence",
                                             "application-switch-future-absence"))
                expected.add(parent + "test_public_parent_add_lost_save_success_is_not_replayed["
                             + backend + "]")
                body = make.split(target + ": compile\n", 1)[1].split("\n\n", 1)[0]
                selected = re.findall(r"'(tests/test_[^']+)'", body)
                actual = [node for node in selected
                          if any(node.startswith("tests/" + module + "::") for module in modules)]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 40)
                aliases = {"tests/test_cgate_toolkit_tweaker_dlt_interop.py::"
                           "test_public_dlt_tweaker_profile_create_and_replace["
                           "keybir2-literal-keyb2-catalogue-alias-" + operation + "-" + backend + "]"
                           for operation in ("create", "replace")}
                self.assertTrue(aliases <= set(selected))
                audit_body = workflow.split("--selection " + selection + "\n", 1)[1].split(
                    "\n      - name:", 1)[0]
                for module in modules:
                    self.assertEqual(audit_body.count("--require-module tests/" + module), 1)

    def test_final_csv_and_documentation_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        csv = 'tests/test_cgate_csv_last_profiles_interop.py'
        document = 'tests/test_cgate_project_documentation_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                            ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {
                    csv + '::test_public_csv_last_profiles_all_literals_and_ordered_selection[' + backend + ']',
                    csv + '::test_public_csv_last_profiles_lost_snapshot_is_terminal_without_replay[' + backend + ']',
                }
                expected.update(csv + '::test_public_csv_last_profiles_refusal_is_atomic[' + fault + '-'
                                + backend + ']' for fault in ('bad-profile', 'missing-application',
                                    'missing-secondary-input-group', 'missing-unused-temperature-group', 'bad-fan-route'))
                expected.update(document + '::' + name + '[' + backend + ']' for name in (
                    'test_public_database_document_snapshot_and_literal_bodies',
                    'test_public_database_document_absent_network_is_atomic',
                    'test_public_database_document_lost_snapshot_has_no_output_or_retry'))
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((csv + '::', document + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 10)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (csv, document):
                    self.assertEqual(audit.count('--require-module ' + module), 1)

    def test_application_reset_add_public_roster_is_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_application_reset_add_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                            ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {module + '::test_public_application_reset_add_complete_history[' + case + '-'
                            + backend + ']' for case in ('application-description-group',
                                'cancel-repeated-primary-secondary', 'reset-application-group',
                                'reset-cancelled-application-fresh-primary',
                                'reset-initial-scene-before-action', 'reset-application-scene-corridor',
                                'preceding-and-future-owner', 'expanded-reserved-confirmed')}
                expected.update(module + '::' + name + '[' + backend + ']' for name in (
                    'test_public_application_reset_add_lost_save_is_not_replayed',
                    'test_public_application_add_guards_refuse_without_persistent_send'))
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith(module + '::')]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                self.assertEqual(len(expected), 10)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                self.assertEqual(audit.count('--require-module ' + module), 1)

    def test_static_language_and_recovered_report_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        parent = 'tests/test_cgate_edlt_static_language_add_interop.py'
        sensors = 'tests/test_cgate_project_documentation_sensors_interop.py'
        wireless = 'tests/test_cgate_project_documentation_wireless_interop.py'
        l1 = 'tests/test_cgate_project_documentation_l1_interop.py'
        architectural = 'tests/test_cgate_project_documentation_architectural_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                           ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {parent + '::test_public_static_language_parent_complete_history[' + case
                            + '-' + backend + ']' for case in ('default-repair-grid-before-widget',
                                'cancel-repeated-selected-list', 'absent-collection-chinese',
                                'zero-default-first-selected', 'allocated-widget-then-grid',
                                'language-parent-and-scene-add')}
                expected.update(parent + '::test_public_static_language_lost_success_stops_without_replay['
                                + stage + '-' + backend + ']' for stage in ('add', 'set', 'pp-save'))
                expected.add(parent + '::test_public_static_language_invalid_history_never_writes[' + backend + ']')
                if backend == 'daemon':
                    expected.update(parent + '::test_public_static_language_authentication_stops_before_write['
                                    + failure + ']' for failure in ('missing', 'wrong'))
                expected.add(sensors + '::test_public_database_document_sensor_families_preserves_snapshot[' + backend + ']')
                expected.add(wireless + '::test_public_database_document_wireless_families_preserves_snapshot[' + backend + ']')
                expected.add(l1 + '::test_public_database_document_l1_preserves_snapshot_and_literal_body[' + backend + ']')
                expected.add(architectural + '::test_public_database_document_architectural_families_preserves_snapshot[' + backend + ']')
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((parent + '::', sensors + '::', wireless + '::', l1 + '::', architectural + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (parent, sensors, wireless, l1, architectural):
                    self.assertEqual(audit_body.count('--require-module ' + module), 1)

    def test_grid_native_address_and_st7_public_rosters_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        grid = 'tests/test_cgate_edlt_static_grid_editor_interop.py'
        native = 'tests/test_cgate_project_documentation_native_addresses_interop.py'
        st7 = 'tests/test_cgate_project_documentation_st7_light_level_interop.py'
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {grid + '::test_public_static_grid_history_preview_apply_and_preservation['
                            + case + '-' + backend + ']' for case in
                            ('cell-transactions', 'cached-split-name', 'malformed-preserved')}
                expected.update(grid + '::' + name + '[' + backend + ']' for name in
                                ('test_public_pending_cell_close_refuses_without_write',
                                 'test_public_static_grid_lost_successful_save_is_not_replayed'))
                expected.update(native + '::test_public_native_report_exact_named_identity_and_physical_references['
                                + backend + '-' + kind + ']' for kind in ('thermostat', 'wireless'))
                expected.add(st7 + '::test_public_database_document_st7_zero_timers_stored_scenes_and_direct_roles['
                             + backend + ']')
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith((grid + '::', native + '::', st7 + '::'))]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                for module in (grid, native, st7):
                    self.assertEqual(audit.count('--require-module ' + module), 1)

    def test_scene_name_control_exact_thirty_public_parents_are_required(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgate_edlt_scene_name_control_interop.py'
        # Independent roster of the frozen literal profiles; do not derive
        # expectations from Make, pytest collection, or a replacement producer.
        profiles = ('ascii64', 'multibyte64', 'split63', 'astral64',
                    'old63-reserved-new62', 'unicode-blank-clear',
                    'u001c-is-not-dotnet-blank', 'bom-is-not-dotnet-blank',
                    'u180e-with-known-nonblank', 'malformed-exact-reuse',
                    'ordered-grid-control-widget')
        refusals = ('pending-name', 'cache-injection')
        faults = ('pp-save', 'project-save')
        fixture = json.loads((root / 'toolkit-cli/research/fixtures/'
                              'cgate-edlt-scene-name-control-owned.json').read_text())
        self.assertEqual(tuple(row['id'] for row in fixture['cases']), profiles)
        self.assertEqual(tuple(row['id'] for row in fixture['refusals']), refusals)
        self.assertEqual(fixture['fault_phases'], ['PP SAVE_TO_SOURCE', 'PROJECT SAVE'])
        public_source = (root / 'toolkit-cli' / module).read_text()
        self.assertEqual(public_source.count("@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))"), 3)
        self.assertEqual(public_source.count("@pytest.mark.parametrize('case', FACTS['cases'], ids=lambda row:row['id'])"), 1)
        self.assertEqual(public_source.count("@pytest.mark.parametrize('case', FACTS['refusals'], ids=lambda row:row['id'])"), 1)
        self.assertEqual(public_source.count("@pytest.mark.parametrize('phase', FACTS['fault_phases'], ids=('pp-save','project-save'))"), 1)
        all_selected = []
        for backend, target, selection in [('mock', 'check-cgate-interop', 'cgate-mock'),
                                           ('daemon', 'check-cmqtt-interop', 'cmqttd')]:
            with self.subTest(backend=backend):
                expected = {module + '::test_public_scene_name_control_preview_apply_and_fresh_names['
                            + profile + '-' + backend + ']' for profile in profiles}
                expected.update(module + '::test_public_pending_scene_name_and_cache_injection_refuse_without_write['
                                + refusal + '-' + backend + ']' for refusal in refusals)
                expected.update(module + '::test_public_scene_name_control_lost_successful_save_not_replayed['
                                + fault + '-' + backend + ']' for fault in faults)
                body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
                actual = [node for node in re.findall(r"'(tests/test_[^']+)'", body)
                          if node.startswith(module + '::')]
                self.assertEqual(len(expected), 15)
                self.assertEqual(len(actual), 15)
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)
                all_selected.extend(actual)
                audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
                self.assertEqual(audit_body.count('--require-module ' + module), 1)
        self.assertEqual(len(all_selected), 30)
        self.assertEqual(len(set(all_selected)), 30)

    def test_scene_name_pure_modules_and_chunk_manifest_are_required(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/ci.yml').read_text()
        pure = ('tests/test_edlt_scene_name_control.py', 'tests/test_edlt_scene_names.py',
                'tests/test_edlt_scene_name_static.py', 'tests/test_edlt_parent_scene_names.py')
        offline = workflow.split('--selection offline\n', 1)[1].split('\n      - name:', 1)[0]
        for module in pure:
            self.assertEqual(offline.count('--require-module ' + module), 1)
        manifest = root / 'toolkit-cli/docs/edlt-scene-name-control-release-test-modules.txt'
        selected = [line.strip() for line in manifest.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(set(selected), set(pure) | {
            'tests/test_cli_edlt_scene_manager.py',
            'tests/test_cgate_edlt_scene_name_control_interop.py', 'tests/test_ci_test_results.py'})
        self.assertTrue(all((root / 'toolkit-cli' / module).is_file() for module in selected))


    def test_thermostat_stack_exact_backend_roster_body_gates_and_inherited_selection(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        # Literal cases from the reviewed source dictionaries and test shapes.
        # The inherited selection is pinned separately to published main1cc79977.
        templates = (
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSA-show-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSA-relay-warnings-master-independent-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSA5-show-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSA5-relay-warnings-master-independent-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSB-show-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSB-relay-warnings-master-independent-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSB5-show-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[PC_TSB5-relay-warnings-master-independent-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-mask-only-no-inferred-update-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[inactive-caches-before-unused-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[expansion-shrink-reexpand-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[bit-zero-not-a-damper-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[only-zone-1-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[only-zone-2-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[only-zone-3-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[only-zone-4-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[first-free-not-old-source-byte-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[four-first-free-source-order-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[same-generated-tag-existing-reuse-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[generated-tag-at-unused-no-create-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[slave-missing-remains-nil-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[slave-existing-stays-model-bound-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[reopen-does-not-clear-cache-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[after-show-help-only-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[click-true-alert-without-model-write-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[click-false-no-alert-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[setup-checked-does-not-click-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-0-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-1-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-2-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-3-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-6-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-save-factor-10-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[binding-and-click-separate-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_explicit_damper_zone_history[graph-only-created-zones-retained-without-pp-change-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_damper_history_refuses_before_backup[group-callback-requires-form-show-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_damper_lost_successful_save_never_replays[PP SAVE_TO_SOURCE-binding-save-factor-6-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_damper_lost_successful_save_never_replays[PROJECT SAVE-binding-save-factor-6-{backend}]',
            'tests/test_thermostat_damper_controls_backends.py::test_public_damper_opaque_level_stale_refuses_before_backup[{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_load_and_Edit_preserve_Unicode_and_opaque_Values[unique-ASCII-default-reuse-then-omitted-Edit-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_load_and_Edit_preserve_Unicode_and_opaque_Values[missing-ASCII-default-create-amid-Unicode-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_load_and_Edit_preserve_Unicode_and_opaque_Values[distinct-Unicode-Edits-after-ASCII-default-reuse-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_load_and_Edit_preserve_Unicode_and_opaque_Values[programmable-damper-ASCII-default-reuse-amid-Unicode-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_ambiguity_and_duplicate_Edit_refuse_before_backup[ambiguous-ASCII-default-still-refused-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_ambiguity_and_duplicate_Edit_refuse_before_backup[ASCII-duplicate-Edit-still-refused-{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_snapshot_keeps_unrelated_opaque_Value_freshness[{backend}]',
            'tests/test_thermostat_output_default_unicode_backends.py::test_public_ASCII_default_then_lost_quoted_Unicode_Edit_never_replays[{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_histories_preserve_identity_and_graph[shared-object-repeated-quoted-edits-{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_histories_preserve_identity_and_graph[nbsp-temporary-name-swap-{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_histories_preserve_identity_and_graph[add-edit-issued-identity-and-reselect-original-{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_histories_preserve_identity_and_graph[cancel-and-omitted-long-name-noop-{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_histories_preserve_identity_and_graph[shared-object-edits-preserve-opaque-existing-value-{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_duplicate_refused_before_backup[{backend}]',
            'tests/test_thermostat_output_edit_backends.py::test_public_output_edit_lost_successful_set_never_replays[{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[basic-alias-shared-enable-and-accepted-levels-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[basic-interleaved-add-retained-after-reselection-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[cancel-provisional-name-collision-noop-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[fan-adds-use-evolving-numeric-inventory-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[ordered-history-preserves-opaque-level-value-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_histories_and_one_save[slave-damper-add-retains-group-and-normalizes-plant-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_history_refused_before_backup[accepted-add-then-final-reference-collision-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_history_refused_before_backup[later-add-sees-earlier-name-{backend}]',
            'tests/test_thermostat_output_add_backends.py::test_public_output_add_lost_successful_creation_never_replays[{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_load_and_ordered_selections[basic-alias-create-prefix-and-reassign-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_load_and_ordered_selections[basic-generated-peer-and-unused-damper-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_load_and_ordered_selections[programmable-alias-shared-load-order-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_load_and_ordered_selections[programmable-temporary-unused-fan-swap-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_load_and_ordered_selections[resolve-only-rename-without-pp-change-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_lost_successful_rename_never_replays[{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_refusal_before_backup[ambiguous-generated-peer-{backend}]',
            'tests/test_thermostat_output_groups_backends.py::test_public_output_group_refusal_before_backup[direct-excluded-fan-swap-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[accept-both-new-groups-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[accept-setback-decline-schedule-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[accept-setback-preserve-opaque-used-value-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[basic-accept-complete-addresses-noop-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[basic-alias-accept-group-zero-skip-unused-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[decline-both-missing-levels-noop-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[decline-both-preserve-opaque-existing-value-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_accepted_remote_level_choices[decline-setback-accept-schedule-graph-only-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_lost_successful_level_set_never_deletes_or_replays[schedule-tag-{backend}]',
            'tests/test_thermostat_remote_levels_backends.py::test_public_lost_successful_level_set_never_deletes_or_replays[setback-value-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_lost_successful_save_never_replays[PP SAVE_TO_SOURCE-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_lost_successful_save_never_replays[PROJECT SAVE-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_reference_collision_refused_before_mutation[{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[already-present-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[basic-alias-one-unused-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[basic-lighting-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[disable-still-creates-enable-application-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[graph-only-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[programmable-alias-cross-application-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[programmable-joined-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_stale_snapshot_refused_before_backup[pp-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_stale_snapshot_refused_before_backup[unrelated-graph-{backend}]',
        )
        public_modules = ('tests/test_thermostat_remote_references_backends.py', 'tests/test_thermostat_remote_levels_backends.py', 'tests/test_thermostat_output_groups_backends.py', 'tests/test_thermostat_output_add_backends.py', 'tests/test_thermostat_output_edit_backends.py', 'tests/test_thermostat_output_default_unicode_backends.py', 'tests/test_thermostat_damper_controls_backends.py')
        complete_ids = re.findall(r"'(tests/[^']+::[^']+)'", make)
        # New owner-temperature registrations do not alter inherited identities.
        complete_ids = [row for row in complete_ids
                        if not row.startswith(('tests/test_thermostat_temperature_owner_backends.py::',
                                               'tests/test_cgl_application_order_backends.py::',
                                               'tests/test_application_copy_safe_backends.py::',
                                               'tests/test_application_safe_set_backends.py::',
                                               'tests/test_ordinary_level_value_backends.py::',
                                               'tests/test_ordinary_level_value_followon_backends.py::',
                                               'tests/test_conversion_xml_preservation_backends.py::', 'tests/test_thermostat_zone_controls_backends.py::', 'tests/test_conversion_xml_restart_backends.py::'))]
        self.assertEqual(len(complete_ids), 945)
        self.assertEqual(len(set(complete_ids)), 945)
        inherited_945 = '\n'.join(sorted(complete_ids)) + '\n'
        self.assertEqual(hashlib.sha256(inherited_945.encode()).hexdigest(), '86fe25ab6de68f773b8130bd198631dc0a4a8dc939597aaf590c9b5ab1eea850')
        quick_zone_ids = {row for row in complete_ids
                          if row.startswith('tests/test_thermostat_quick_zone_controls_backends.py::')}
        self.assertEqual(len(quick_zone_ids), 38)
        # Preserve the exact inherited identities and their earlier digests.
        all_ids = [row for row in complete_ids if row not in quick_zone_ids]
        self.assertEqual(len(all_ids), 907)
        self.assertEqual(len(set(all_ids)), 907)
        new_ids = set()
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                            ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {row.format(backend=backend) for row in templates}
            self.assertEqual(len(expected), 93)
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.split('::', 1)[0] in public_modules]
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            new_ids |= {row for row in expected
                        if not row.startswith('tests/test_thermostat_remote_references_backends.py::')}
            audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in public_modules:
                self.assertEqual(audit_body.count('--require-module ' + module + '\n'), 1)
        self.assertEqual(len(new_ids), 162)
        damper_ids = {row for row in all_ids if row.startswith('tests/test_thermostat_damper_controls_backends.py::')}
        self.assertEqual(len(damper_ids), 78)
        prior_829 = '\n'.join(sorted(set(all_ids) - damper_ids)) + '\n'
        self.assertEqual(len(set(all_ids) - damper_ids), 829)
        self.assertEqual(hashlib.sha256(prior_829.encode()).hexdigest(), '23ed7add09cabc63c5068070e69b44d7f9004a155a822305cec3287a10975afb')
        unicode_ids = {row for row in all_ids if row.startswith('tests/test_thermostat_output_default_unicode_backends.py::')}
        self.assertEqual(len(unicode_ids), 16)
        prior_813 = '\n'.join(sorted(set(all_ids) - unicode_ids - damper_ids)) + '\n'
        self.assertEqual(len(set(all_ids) - unicode_ids - damper_ids), 813)
        self.assertEqual(hashlib.sha256(prior_813.encode()).hexdigest(), 'ec379cc24fe3e9e8935d2165cefdf6099e9b3ce0128b755070a2d564dac83ab0')
        inherited = '\n'.join(sorted(set(all_ids) - new_ids)) + '\n'
        self.assertEqual(len(set(all_ids) - new_ids), 745)
        self.assertEqual(hashlib.sha256(inherited.encode()).hexdigest(), '1c530f89c4780322fffe47f24ef9aa6943ce387d58b5829ea181c31c741928d8')
        pure_modules = ('tests/test_thermostat_remote_levels.py', 'tests/test_thermostat_output_groups.py', 'tests/test_thermostat_output_add.py', 'tests/test_thermostat_output_add_native.py', 'tests/test_thermostat_output_edit.py', 'tests/test_thermostat_output_edit_native.py', 'tests/test_thermostat_output_edit_opaque_values.py', 'tests/test_thermostat_output_default_unicode.py', 'tests/test_thermostat_output_default_ascii_static.py', 'tests/test_thermostat_damper_controls.py', 'tests/test_cli_thermostat_damper_controls.py')
        for selection in ('offline', 'installed-wheel'):
            audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in pure_modules:
                self.assertEqual(audit_body.count('--require-module ' + module + '\n'), 1)
            self.assertNotIn('--require-module tests/test_thermostat_settings_native.py\n', audit_body)

    def test_cgl_order_literal_backend_roster_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_cgl_application_order_backends.py'
        names = (
            'test_public_cgl_retained_native_prefix_order_filters_and_routes',
            'test_public_cgl_saved_load_runtime_reannouncement_preserves_order',
            'test_public_cgl_typed_replace_readdress_copy_delete_recreate',
            'test_public_cgl_complete_network_replacement_retains_and_appends',
            'test_public_cgl_project_copy_native_archive_and_graph_isolation',
            'test_public_cgl_lost_import_success_is_not_replayed_or_rolled_back',
            'test_public_cgl_invalid_python_document_has_no_prefix_mutation',
        )
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {module + '::' + name + '[' + backend + ']' for name in names}
            if backend == 'daemon':
                expected |= {module + '::test_public_cmqttd_cgl_durable_restart_and_explicit_legacy_fallback[' + mode + ']'
                             for mode in ('recorded-restart', 'legacy-missing-field')}
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.startswith(module + '::')]
            self.assertEqual(len(actual), 7 if backend == 'mock' else 9)
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(len(total), len(set(total)))
        self.assertEqual(len(total), 16)

    def test_application_database_safe_exact_roster_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        copy_module = 'tests/test_application_copy_safe_backends.py'
        set_module = 'tests/test_application_safe_set_backends.py'
        copy_names = (
            'test_public_numeric_application_copy_complete_save_reload_isolation',
            'test_public_application_oid_copy_to_network_oid',
            'test_public_application_cross_project_copy_preserves_source',
            'test_public_application_copy_sibling_conflicts_do_not_mutate',
            'test_public_application_copy_wrong_parent_and_raw_level_refuse',
            'test_public_application_copy_unsaved_close_drops_only_destination',
            'test_public_application_copy_lost_301_no_replay_or_inverse_cleanup',
            'test_public_application_copy_lost_project_save_preserves_complete_copy',
        )
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {copy_module + '::' + name + '[' + backend + ']' for name in copy_names}
            expected |= {set_module + '::test_public_application_safe_move_preserves_full_graph[' + backend + '-' + mode + ']'
                         for mode in ('numeric', 'oid')}
            expected |= {set_module + '::test_public_application_safe_refusal_is_atomic[' + backend + '-' + reason + ']'
                         for reason in ('plus', 'minus', 'hex', 'overflow', 'text', 'occupied', 'name-collision', 'blank-name')}
            expected.add(set_module + '::test_public_application_safe_noop_rename_and_replacement_share_identity[' + backend + ']')
            expected |= {set_module + '::test_public_application_safe_lost_success_is_not_replayed[' + backend + '-' + phase + ']'
                         for phase in ('lost-move', 'lost-save')}
            if backend == 'daemon':
                expected.add(set_module + '::test_public_application_safe_cmqttd_restart_preserves_address_and_oid')
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.split('::', 1)[0] in (copy_module, set_module)]
            self.assertEqual(len(actual), 21 if backend == 'mock' else 22)
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in (copy_module, set_module):
                self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(len(total), 43)
        self.assertEqual(len(set(total)), 43)
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(total)) + '\n').encode()).hexdigest(),
                         '51dba3a00aedf0bbfb01dcc41d27d1fcc65d7e1178b4b3b421e25773f057a734')



    def test_prepared_zone_literal_roster_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_thermostat_zone_controls_backends.py'
        expected = {'daemon': ['tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-UIAllocatedZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-InternalPlantZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-InternalPlantModes-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-MeasuredZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-CoolingPlantInstalledZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-VentingPlantInstalledZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-HeatingPlantInstalledZones-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[empty-heating-callback-chain-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[vent-mode-family-fan-save-tail-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[basic-operation-zone-tail-pc_tsb-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[basic-operation-zone-tail-pc_tsb5-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_refuses_before_backup[unsettled-profile-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_refuses_before_backup[pending-queue-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_failed_stage_never_saves_or_inverts[daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_lost_successful_save_never_replays[PP SAVE_TO_SOURCE-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_lost_successful_save_never_replays[PROJECT SAVE-daemon]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_schema_refuses_before_connection[unprepared-schedule]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_schema_refuses_before_connection[unprepared-standby]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_schema_refuses_before_connection[nonboolean]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_schema_refuses_before_connection[missing-celsius]'], 'mock': ['tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-UIAllocatedZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-InternalPlantZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-InternalPlantModes-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-MeasuredZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-CoolingPlantInstalledZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-VentingPlantInstalledZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[all-prepared-HeatingPlantInstalledZones-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[empty-heating-callback-chain-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[vent-mode-family-fan-save-tail-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[basic-operation-zone-tail-pc_tsb-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_history[basic-operation-zone-tail-pc_tsb5-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_refuses_before_backup[unsettled-profile-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_refuses_before_backup[pending-queue-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_failed_stage_never_saves_or_inverts[mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_lost_successful_save_never_replays[PP SAVE_TO_SOURCE-mock]', 'tests/test_thermostat_zone_controls_backends.py::test_public_prepared_binding_lost_successful_save_never_replays[PROJECT SAVE-mock]']}
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [n for n in re.findall(r"'(tests/[^']+::[^']+)'", body) if n.startswith(module + '::')]
            self.assertEqual(actual, expected[backend])
            self.assertEqual(len(actual), len(set(actual)))
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(len(total), 36)
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(total)) + '\n').encode()).hexdigest(), 'd6e87f155befaa872c9059a14a0a59a399afb0f748f9e0b86bd79317ef98f175')
        for selection in ('offline', 'installed-wheel'):
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module tests/test_thermostat_zone_controls.py\n'), 1)
        focused = make.split('check-thermostat-zone-controls:\n', 1)[1].split('\n\n', 1)[0]
        self.assertNotIn('cargo ', focused)
        self.assertIn('tests/test_thermostat_zone_controls.py', focused)
        self.assertIn('tests/test_thermostat_zone_controls_backends.py', focused)


    def test_conversion_xml_restart_exact_daemon_roster_and_body_requirement(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_conversion_xml_restart_backends.py'
        expected = ['tests/test_conversion_xml_restart_backends.py::test_public_conversion_completed_journal_daemon_restart_preserves_xml', 'tests/test_conversion_xml_restart_backends.py::test_public_conversion_lost_save_daemon_restart_keeps_uncertainty']
        for target, selection, wanted in (('check-cgate-interop', 'cgate-mock', []),
                                           ('check-cmqtt-interop', 'cmqttd', expected)):
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [n for n in re.findall(r"'(tests/[^']+::[^']+)'", body) if n.startswith(module + '::')]
            self.assertEqual(actual, wanted)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), int(selection == 'cmqttd'))
        self.assertEqual(len(expected), len(set(expected)))
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(expected)) + '\n').encode()).hexdigest(), 'ad24e6438d1d100ecd8d13cda2a4b66cd0360bce1b42a5afb54fcbff25c2c4c6')
        focused = make.split('check-conversion-xml-preservation:\n', 1)[1].split('\n\n', 1)[0]
        self.assertIn(module, focused)
        self.assertNotIn('cargo ', focused)

    def test_conversion_xml_preservation_exact_roster_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_conversion_xml_preservation_backends.py'
        names = ('test_public_conversion_creation_preserve_and_default_reset', 'test_public_conversion_replace_backup_reopen_and_recovery_preserve', 'test_public_conversion_creation_mixed_separator_loss_refuses', 'test_public_conversion_backup_preserved_separator_loss_stops_before_add', 'test_public_conversion_predelete_preserve_parent_tail_loss_keeps_source', 'test_public_conversion_reopen_cdata_loss_refuses_completed_receipt', 'test_public_conversion_recovery_current_or_backup_space_loss_read_only', 'test_public_conversion_save_refusal_retains_preserved_graph', 'test_public_conversion_lost_save_200_retains_graph_without_replay')
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {module + '::' + name + '[' + backend + ']' for name in names}
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [n for n in re.findall(r"'(tests/[^']+::[^']+)'", body) if n.startswith(module + '::')]
            self.assertEqual(len(actual), 9)
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(total)) + '\n').encode()).hexdigest(), 'e209733d197dbdbb1c799bd2997ab4cd8504c4744ad5bde5f3c9b25bbf3a191c')
        for selection in ('offline', 'installed-wheel'):
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module tests/test_conversion_xml_preservation.py\n'), 1)
        focused = make.split('check-conversion-xml-preservation:\n', 1)[1].split('\n\n', 1)[0]
        self.assertNotIn('cargo ', focused)
        self.assertIn('tests/test_conversion_xml_preservation.py', focused)
        self.assertIn('tests/test_conversion_xml_preservation_backends.py', focused)

    def test_ordinary_level_value_literal_roster_digest_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_ordinary_level_value_backends.py'
        names = (
            'test_public_numeric_level_byte_edit_readbacks_save_reload',
            'test_public_invalid_numeric_level_bytes_refuse_atomically',
            'test_public_plain_and_copied_null_levels_become_bytes',
            'test_public_numeric_then_issued_oid_keeps_coherent_aliases',
            'test_public_selected_project_copy_retained_oid_bytes_are_isolated',
            'test_public_associated_raw_level_owner_keeps_its_lexemes',
        )
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {module + '::' + name + '[' + backend + ']' for name in names}
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.startswith(module + '::')]
            self.assertEqual(len(actual), 6)
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(len(total), 12)
        self.assertEqual(len(set(total)), 12)
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(total)) + '\n').encode()).hexdigest(),
                         'd2fd44cc1299cbe3422fac58d406551640e8ff0271e4ca87036f575eb99d6cdb')

    def test_ordinary_level_value_followon_literal_roster_and_required_bodies(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_ordinary_level_value_followon_backends.py'
        expected = {
            'mock': {
                module + '::test_public_numeric_level_lost_success_is_not_replayed[mock-value]',
                module + '::test_public_numeric_level_lost_success_is_not_replayed[mock-save]',
            },
            'daemon': {
                module + '::test_public_numeric_level_lost_success_is_not_replayed[daemon-value]',
                module + '::test_public_numeric_level_lost_success_is_not_replayed[daemon-save]',
                module + '::test_public_numeric_group_and_netvar_levels_survive_cmqttd_restart',
            },
        }
        total = []
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [n for n in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if n.startswith(module + '::')]
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected[backend])
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
            total.extend(actual)
        self.assertEqual(len(total), 5)
        self.assertEqual(len(set(total)), 5)
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(total)) + '\n').encode()).hexdigest(), 'b14d154114f2583ead0aa02d1f8941dd2e2ea164525597d4cc2d20e17559451d')
        inherited = [n for n in re.findall(r"'(tests/[^']+::[^']+)'", make)
                     if not n.startswith((module + '::', 'tests/test_conversion_xml_preservation_backends.py::', 'tests/test_thermostat_zone_controls_backends.py::', 'tests/test_conversion_xml_restart_backends.py::'))]
        self.assertEqual(len(inherited), 1056)
        self.assertEqual(len(inherited), len(set(inherited)))
        self.assertEqual(hashlib.sha256(('\n'.join(sorted(inherited)) + '\n').encode()).hexdigest(), '3a5b0584311acab115319254599a580f254062391c7b42108fcb93b15ea81a05')

    def test_temperature_owner_exact_backend_roster_and_body_requirements(self):
        # Literal declared acceptance profiles; never generated from Make or production.
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_thermostat_temperature_owner_backends.py'
        templates = (
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsa-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsa5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsb-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_chained_saves[pc_tsb5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-pp-save-pc_tsa-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-pp-save-pc_tsa5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-pp-save-pc_tsb-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-pp-save-pc_tsb5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-project-save-pc_tsa-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-project-save-pc_tsa5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-project-save-pc_tsb-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_lost_successful_save[lost-project-save-pc_tsb5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[raw-set-rewritten-pc_tsa-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[raw-set-rewritten-pc_tsa5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[raw-set-rewritten-pc_tsb-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[raw-set-rewritten-pc_tsb5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[unsigned-overflow-pc_tsa-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[unsigned-overflow-pc_tsa5-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[unsigned-overflow-pc_tsb-{backend}]',
            'tests/test_thermostat_temperature_owner_backends.py::test_public_temperature_owner_refuses_before_backup[unsigned-overflow-pc_tsb5-{backend}]',
        )
        complete = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", make)
                    if not row.startswith(('tests/test_cgl_application_order_backends.py::',
                                           'tests/test_application_copy_safe_backends.py::',
                                           'tests/test_application_safe_set_backends.py::',
                                           'tests/test_ordinary_level_value_backends.py::',
                                           'tests/test_ordinary_level_value_followon_backends.py::',
                                               'tests/test_conversion_xml_preservation_backends.py::', 'tests/test_thermostat_zone_controls_backends.py::', 'tests/test_conversion_xml_restart_backends.py::'))]
        self.assertEqual(len(complete), 985)
        self.assertEqual(len(set(complete)), 985)
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {row.format(backend=backend) for row in templates}
            self.assertEqual(len(expected), 20)
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.startswith(module + '::')]
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
        for selection in ('offline', 'installed-wheel'):
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in ('tests/test_thermostat_temperature_model.py',
                           'tests/test_thermostat_temperature_owner.py'):
                self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)

        focused = make.split('check-thermostat-temperature-owner:\n', 1)[1].split('\n\n', 1)[0]
        self.assertNotIn('cargo ', focused)
        self.assertIn('test -x "$${CBUS_CGATE_MOCK_BIN}"', focused)
        self.assertIn('test -x "$${CBUS_CMQTTD_BIN}"', focused)
        focused_modules = re.findall(r'tests/[a-z0-9_]+\.py', focused)
        self.assertEqual(focused_modules, [
            'tests/test_thermostat_temperature_model.py',
            'tests/test_thermostat_temperature_owner.py',
            'tests/test_thermostat_temperature_owner_backends.py',
            'tests/test_thermostat_temperature.py',
            'tests/test_thermostat_settings_temperature_vectors.py',
            'tests/test_thermostat_quick_zone_controls.py',
            'tests/test_thermostat_settings.py',
            'tests/test_thermostat_settings_guard.py',
            'tests/test_thermostat_remote_references.py',
            'tests/test_thermostat_quick_zone_controls_backends.py',
            'tests/test_ci_test_results.py',
        ])

    def test_quick_zone_owner_exact_backend_roster_and_body_requirements(self):
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        module = 'tests/test_thermostat_quick_zone_controls_backends.py'
        histories = (
            'basic-master-live-display-and-tail-pc_tsb',
            'basic-retained-disabled-flags-pc_tsb',
            'basic-slave-live-display-four-pc_tsb',
            'basic-master-live-display-and-tail-pc_tsb5',
            'basic-retained-disabled-flags-pc_tsb5',
            'basic-slave-live-display-four-pc_tsb5',
            'programmable-include-exclude-live-pc_tsa',
            'ordered-plant-one-reuse-pc_tsa',
            'ordered-plant-one-allocate-pc_tsa',
            'programmable-include-exclude-live-pc_tsa5',
            'ordered-plant-one-reuse-pc_tsa5',
            'ordered-plant-one-allocate-pc_tsa5',
        )
        refusals = ('changed-loaded-role', 'pending-source-message',
                    'consumed-source-message', 'invalid-display-before-master-setup')
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                          ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            expected = {module + '::test_public_full_owner_history[' + case + '-' + backend + ']'
                        for case in histories}
            expected |= {module + '::test_public_full_owner_refuses_before_backup[' + case + '-' + backend + ']'
                         for case in refusals}
            expected |= {module + '::test_public_full_owner_lost_successful_save_never_replays[' + case + '-' + backend + ']'
                         for case in ('PP SAVE_TO_SOURCE', 'PROJECT SAVE')}
            expected.add(module + '::test_public_full_owner_opaque_level_stale_refuses[' + backend + ']')
            self.assertEqual(len(expected), 19)
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = [row for row in re.findall(r"'(tests/[^']+::[^']+)'", body)
                      if row.startswith(module + '::')]
            self.assertEqual(len(actual), 19)
            self.assertEqual(set(actual), expected)
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module ' + module + '\n'), 1)
        for selection in ('offline', 'installed-wheel'):
            audit = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            self.assertEqual(audit.count('--require-module tests/test_thermostat_quick_zone_controls.py\n'), 1)

    def test_combined_cli_exact_backend_rosters_and_body_requirements(self):
        # Independent literal identities from the reviewed feature shapes;
        # neither production output nor the Makefile defines the expectation.
        root = Path(__file__).resolve().parents[2]
        make = (root / 'toolkit-cli/Makefile').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        new_patterns = (
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[primary-collision-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[secondary-collision-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[same-boolean-duplicate-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[missing-secondary-load-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[hidden-enable-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[ordered-return-to-retained-group-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[dual-join-lookup-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_ordered_controls_save_and_reopen[pir-enable-lookup-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_lost_save_is_not_replayed[{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_refusal_is_read_only[missing-destination-{backend}]',
            'tests/test_cgate_senll_controls_interop.py::test_public_senll_refusal_is_read_only[excluded-after-collision-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[RELDN4-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[RELDN8-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[RELDN8B-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[RELDN12-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[DIMDN4-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[DIMDN4F-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[DIMDN8-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_ordered_controls_all_profiles[DIMDN8F-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_controls_lost_successful_save_is_not_replayed[DIMDN8-{backend}]',
            'tests/test_cgate_din_controls_interop.py::test_public_din_controls_lost_successful_save_is_not_replayed[RELDN8-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[neo-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[reflection-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[classic-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[saturn-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[decorator-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[avanti-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_all_contexts[catalogue-red-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_lost_successful_save_is_not_replayed[reflection-{backend}]',
            'tests/test_neo_indicator_editor_backends.py::test_public_neo_indicator_editor_lost_successful_save_is_not_replayed[saturn-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[area-before-refresh-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[area-select-not-reserved-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[scene-after-refresh-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[scene-select-not-reserved-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[scene-padding-walk-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-duplicate-first-level-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-duplicate-across-boundary-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-compatible-hole-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-compact-hole-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-single-scene-eleven-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-first-sentinel-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[enabled-odd-pointer-blocks-later-boundaries-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_save_and_reopen[flat-enabled-compatible-hole-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_refusal_before_staging[late-scene-cannot-help-refresh-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_inventory_refusal_before_staging[first-sentinel-suppresses-getter-{backend}]',
            'tests/test_cgate_senll_inventory_interop.py::test_public_senll_enabled_scene_lost_save_is_not_replayed[{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[programmable-joined-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[programmable-alias-cross-application-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[basic-lighting-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[basic-alias-one-unused-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[graph-only-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[already-present-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_settings_combined_save[disable-still-creates-enable-application-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_reference_collision_refused_before_mutation[{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_stale_snapshot_refused_before_backup[unrelated-graph-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_stale_snapshot_refused_before_backup[pp-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_lost_successful_save_never_replays[PP SAVE_TO_SOURCE-{backend}]',
            'tests/test_thermostat_remote_references_backends.py::test_public_remote_lost_successful_save_never_replays[PROJECT SAVE-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-0-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-0-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-1-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-1-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-2-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[stored-2-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[preserved-3-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[preserved-3-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[preserved-255-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[preserved-255-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[override-0-to-17-legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_save_and_reopen[override-0-to-17-complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_invalid_override_is_read_only[legacy43-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_invalid_override_is_read_only[complete47-{backend}]',
            'tests/test_cgate_senll_global_interop.py::test_public_senll_global_lost_save_is_not_replayed[{backend}]',
        )
        preserved_patterns = (
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[RELDN4-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[RELDN8-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[RELDN8B-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[RELDN12-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[DIMDN4-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[DIMDN4F-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[DIMDN8-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_toolkit_save_all_profiles[DIMDN8F-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_successful_save_lost_response_is_not_replayed[DIMDN8-{backend}]',
            'tests/test_cgate_din_save_interop.py::test_public_din_successful_save_lost_response_is_not_replayed[RELDN8-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[retained-raw-readonly-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[functional-all-bindings-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[standby-one-grow-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[standby-four-grow-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[standby-same-double-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[standby-shrink-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[standby-already-blank-neighbor-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[ordinary-conversion-then-display-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[scalar-grow-callback-shrink-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[source-setup-explicit-read-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_callbacks_one_save_and_preservation[two-controls-same-global-value-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_preconnection_refusals[caller-state-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_preconnection_refusals[wrong-ordinal-{backend}]',
            'tests/test_cgate_edlt_time_date_controls_interop.py::test_public_time_date_lost_successful_save_is_not_replayed[{backend}]',
        )
        new_modules = (
            'tests/test_cgate_din_controls_interop.py',
            'tests/test_cgate_senll_controls_interop.py',
            'tests/test_cgate_senll_global_interop.py',
            'tests/test_cgate_senll_inventory_interop.py',
            'tests/test_neo_indicator_editor_backends.py',
            'tests/test_thermostat_remote_references_backends.py',
        )
        preserved_modules = ('tests/test_cgate_edlt_time_date_controls_interop.py',
                             'tests/test_cgate_din_save_interop.py')
        for backend, target, selection in (('mock', 'check-cgate-interop', 'cgate-mock'),
                                           ('daemon', 'check-cmqtt-interop', 'cmqttd')):
            body = make.split(target + ': compile\n', 1)[1].split('\n\n', 1)[0]
            actual = re.findall(r"'(tests/test_[^']+)'", body)
            for modules, patterns, count in ((new_modules, new_patterns, 73),
                                             (preserved_modules, preserved_patterns, 24)):
                selected = [node for node in actual if node.split('::', 1)[0] in modules]
                expected = {pattern.format(backend=backend) for pattern in patterns}
                self.assertEqual(len(selected), count)
                self.assertEqual(len(selected), len(set(selected)))
                self.assertEqual(set(selected), expected)
            audit_body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in (*new_modules, *preserved_modules, 'tests/test_cgate_named_database_interop.py'):
                self.assertEqual(audit_body.count('--require-module ' + module + '\n'), 1)

    def test_combined_cli_offline_and_wheel_modules_and_senlla_readonly_cases(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/ci.yml').read_text()
        pure_modules = (
            'tests/test_application_events.py',
            'tests/test_cli_din_controls.py',
            'tests/test_cli_firmware_ncc.py',
            'tests/test_cli_neo_indicator_editor.py',
            'tests/test_cli_senll_controls.py',
            'tests/test_cli_senlla_surface.py',
            'tests/test_cli_sensors.py',
            'tests/test_din_output_controls.py',
            'tests/test_firmware_diagnostics.py',
            'tests/test_firmware_ncc.py',
            'tests/test_input_options.py',
            'tests/test_light_level_sensors.py',
            'tests/test_native_sensor_scenes.py',
            'tests/test_neo_indicator_editor.py',
            'tests/test_senll_control_history.py',
            'tests/test_senll_global_status.py',
            'tests/test_senll_source_inventory.py',
            'tests/test_senlla_surface.py',
            'tests/test_thermostat_remote_references.py',
            'tests/test_thermostat_settings.py',
        )
        for selection in ('offline', 'installed-wheel'):
            body = workflow.split('--selection ' + selection + '\n', 1)[1].split('\n      - name:', 1)[0]
            for module in pure_modules:
                self.assertEqual(body.count('--require-module ' + module + '\n'), 1)
            self.assertNotIn('--require-module tests/test_thermostat_settings_native.py\n', body)
        expected = (
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_exact_profile_and_canonical_firmware_boundaries',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_thirteen_independent_layouts_and_types',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_missing_or_invalid_raw_fields_refuse_without_input_mutation',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_raw_numeric_spellings_preserve_the_original_consumed_values',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_raw_unsigned_domain_survives_permissive_schema_ranges',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_target_group_precedes_margin_group_and_copies_target_power',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_independent_margin_group_loads_nine_and_serializes_target_byte',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_unused_groups_clear_store_flags_but_preserve_all_presets',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_power_state_uses_original_group_before_margin_precedence',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_fixed_margin_roundtrip_uses_x87_and_all_raw_target_byte_values',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_source_projection_outside_native_byte_refuses_without_clipping',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_all_bank_behaviours_and_eight_usage_bits',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_unused_bank_group_or_no_usage_clears_usage_and_behaviour',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_bank_usage_does_not_consume_block_switch_active',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_logical_bank_serializer_low_then_high_precedence',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_logical_bank_level_vectors_are_explicit_and_independent_of_raw_loader',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_current_level_display_literals_and_half_even_ties',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_masked_component_bytes_preserve_unrelated_neighbours',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_eight_keys_scenes_global_and_all_unconsumed_inputs_are_untouched',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_view_is_deeply_detached_and_immutable',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_schema_drift_after_construction_is_refused',
            'tests/test_cli_senlla_surface.py::SENLLASurfaceCLITests::test_public_view_routes_source_pinned_component_without_mutating_inputs',
            'tests/test_cli_senlla_surface.py::SENLLASurfaceCLITests::test_identity_and_bare_mapping_refuse_before_loading_schema',
            'tests/test_cli_senlla_surface.py::SENLLASurfaceCLITests::test_new_view_has_no_edit_flags_and_does_not_broaden_senll_save_gate',
            'tests/test_cli_senlla_surface.py::SENLLASurfaceCLITests::test_public_view_accepts_authored_spec_without_bit_width_or_skip',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_ignored_bit_width_and_skip_preserve_view_and_unsigned_guard',
            'tests/test_senlla_surface.py::SENLLASurfaceTests::test_omitted_bit_metadata_uses_native_one_bit_layout',
        )
        actual = set()
        for module in ('tests/test_senlla_surface.py', 'tests/test_cli_senlla_surface.py'):
            tree = ast.parse((root / 'toolkit-cli' / module).read_text())
            for cls in tree.body:
                if isinstance(cls, ast.ClassDef):
                    for method in cls.body:
                        if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                            actual.add(module + '::' + cls.name + '::' + method.name)
        self.assertEqual(len(expected), 27)
        self.assertEqual(actual, set(expected))


class CITestResultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.junit = self.folder / "result.xml"
        self.trace = self.folder / "trace.json"
        self.write_junit()
        self.write_trace()

    def write_junit(self, *, tests=4, skipped=1, omit_nodeid=False):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests=str(tests), failures="0",
                              errors="0", skipped=str(skipped))
        first = ET.SubElement(suite, "testcase", classname="tests.test_first",
                              name="test_with_subtests")
        second = ET.SubElement(suite, "testcase", classname="tests.test_second",
                               name="test_setup_skip")
        ET.SubElement(second, "skipped", message="private fixture unavailable")
        for case, nodeid in ((first, FIRST), (second, SECOND)):
            properties = ET.SubElement(case, "properties")
            if not omit_nodeid:
                ET.SubElement(properties, "property", name="cbus_ci_nodeid", value=nodeid)
        self.junit.write_bytes(ET.tostring(root))

    def write_trace(self, *, started=None, calls=None, exitstatus=0):
        value = {
            "format": "cbus-ci-pytest-trace-v1",
            "collected": [FIRST, SECOND], "deselected": [],
            "started": [FIRST, SECOND] if started is None else started,
            "call_events": ([{"id": FIRST, "outcome": "passed"}] * 3
                            if calls is None else calls),
            "session_exitstatus": exitstatus,
        }
        self.trace.write_text(json.dumps(value))

    def test_receipt_counts_executed_subtests_and_setup_skip(self):
        receipt = audit(self.junit, self.trace, ["tests/test_first.py"])
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["counts"], {"tests": 4, "passed": 3,
                                               "skipped": 1, "failures": 0, "errors": 0})
        self.assertEqual(receipt["unitemized_subtests"]["reported"], 2)
        self.assertEqual([event["ordinal"] for event in receipt["call_events"]], [1, 2, 3])
        self.assertEqual([case["outcome"] for case in receipt["cases"]],
                         ["passed", "skipped"])

    def test_required_module_with_only_skips_fails_but_preserves_counts(self):
        receipt = audit(self.junit, self.trace, ["tests/test_second.py"])
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_modules"], ["tests/test_second.py"])
        self.assertEqual(receipt["counts"]["skipped"], 1)

    def test_an_entirely_skipped_selection_is_not_green(self):
        root = ET.parse(self.junit).getroot()
        suite = root.find("testsuite")
        suite.set("tests", "2")
        suite.set("skipped", "2")
        ET.SubElement(suite.findall("testcase")[0], "skipped", message="missing binary")
        self.junit.write_bytes(ET.tostring(root))
        self.write_trace(calls=[])
        receipt = audit(self.junit, self.trace, [])
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["counts"]["skipped"], 2)

    def test_junit_counter_must_match_calls_and_setup_only_cases(self):
        self.write_junit(tests=5)
        with self.assertRaisesRegex(AuditError, "counter does not match"):
            audit(self.junit, self.trace, [])

    def test_junit_cases_need_trace_identity(self):
        self.write_junit(omit_nodeid=True)
        with self.assertRaisesRegex(AuditError, "lacks one CI trace node ID"):
            audit(self.junit, self.trace, [])

    def test_every_collected_test_must_start(self):
        self.write_trace(started=[FIRST])
        with self.assertRaisesRegex(AuditError, "did not start"):
            audit(self.junit, self.trace, [])

    def test_junit_skip_total_must_match_actual_skip_events(self):
        self.write_trace(calls=[{"id": FIRST, "outcome": "passed"},
                                {"id": FIRST, "outcome": "skipped"},
                                {"id": FIRST, "outcome": "passed"}])
        with self.assertRaisesRegex(AuditError, "skipped counter does not match"):
            audit(self.junit, self.trace, [])

    def test_failures_do_not_create_green_receipt(self):
        self.write_trace(exitstatus=1)
        self.assertFalse(audit(self.junit, self.trace, ["tests/test_first.py"])["passed"])

    def test_failed_and_errored_junit_cases_keep_detailed_red_receipts(self):
        for outcome, counter, calls in (
            ("failure", "failures", [{"id": FIRST, "outcome": "failed"}]),
            ("error", "errors", []),
        ):
            with self.subTest(outcome=outcome):
                root = ET.parse(self.junit).getroot()
                suite = root.find("testsuite")
                suite.set("tests", "2")
                suite.set(counter, "1")
                ET.SubElement(suite.findall("testcase")[0], outcome,
                              message="owned synthetic failure")
                self.junit.write_bytes(ET.tostring(root))
                self.write_trace(calls=calls, exitstatus=1)
                receipt = audit(self.junit, self.trace, [])
                self.assertFalse(receipt["passed"])
                self.assertEqual(receipt["counts"][counter], 1)
                self.assertEqual(receipt["cases"][0]["outcome"], outcome)
                self.assertEqual(receipt["unitemized_subtests"][counter], 0)
                self.write_junit()

    def test_missing_input_writes_a_path_free_failure_receipt(self):
        output = self.folder / "receipt.json"
        arguments = ["ci_test_results.py", "--junit", str(self.folder / "private.xml"),
                     "--trace", str(self.trace), "--output", str(output),
                     "--selection", "offline"]
        with patch("sys.argv", arguments):
            self.assertEqual(main(), 1)
        receipt = json.loads(output.read_text())
        self.assertEqual(receipt["error"], "Cannot audit CI test result: FileNotFoundError")
        self.assertNotIn(str(self.folder), output.read_text())


if __name__ == "__main__":
    unittest.main()
