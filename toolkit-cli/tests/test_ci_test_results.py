"""CI results must distinguish executed calls, setup skips, and subtests."""
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

    def write_selection(self, cases, calls, *, installed_configuration=None):
        """Build consistent synthetic JUnit/trace identities without running tests."""
        nodeids = [nodeid for nodeid, _ in cases]
        called = {event["id"] for event in calls}
        setup_skips = sum(outcome == "skipped" and nodeid not in called
                          for nodeid, outcome in cases)
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite",
                              tests=str(len(calls) + len(set(nodeids) - called)),
                              failures="0", errors="0",
                              skipped=str(setup_skips + sum(
                                  event["outcome"] == "skipped" for event in calls)))
        for nodeid, outcome in cases:
            module, name = nodeid.split("::", 1)
            case = ET.SubElement(suite, "testcase",
                                 classname=module.removesuffix(".py").replace("/", "."),
                                 name=name)
            if outcome == "skipped":
                ET.SubElement(case, "skipped", message="synthetic unavailable installation")
            properties = ET.SubElement(case, "properties")
            ET.SubElement(properties, "property", name="cbus_ci_nodeid", value=nodeid)
        self.junit.write_bytes(ET.tostring(root))
        trace = {"format": "cbus-ci-pytest-trace-v1", "collected": nodeids,
                 "deselected": [], "started": nodeids, "call_events": calls,
                 "session_exitstatus": 0}
        if installed_configuration is not None:
            trace["installed_offline_configuration"] = installed_configuration
        self.trace.write_text(json.dumps(trace))

    def test_identifier_nested_required_modules_are_admitted(self):
        for module in ("tests/offline_workflows/test_cli_installed.py",
                       "tests/offline_workflows/synthetic_cases_2/test_installed.py"):
            with self.subTest(module=module):
                nodeid = module + "::test_installed_command"
                self.write_selection([(nodeid, "passed")],
                                     [{"id": nodeid, "outcome": "passed"}])
                receipt = audit(self.junit, self.trace, [module])
                self.assertTrue(receipt["passed"])
                self.assertEqual(receipt["missing_required_modules"], [])

    def test_required_modules_reject_unsafe_raw_paths_and_non_test_basenames(self):
        for module in ("/tests/offline_workflows/test_installed.py",
                       "./tests/offline_workflows/test_installed.py",
                       "tests/./test_installed.py", "tests/../test_installed.py",
                       "tests/offline_workflows/../test_installed.py",
                       "tests//test_installed.py",
                       "tests/offline_workflows//test_installed.py",
                       "tests\\offline_workflows\\test_installed.py",
                       "tests/offline-workflows/test_installed.py",
                       "tests/offline_workflows/helpers.py",
                       "tests/offline_workflows/test_installed.txt",
                       "tests/offline_workflows/test_installed.py/",
                       "test_installed.py"):
            with self.subTest(module=module), self.assertRaises(AuditError):
                audit(self.junit, self.trace, [module])

    def test_exact_installed_prefix_and_configuration_have_positive_receipt(self):
        module = "tests/offline_workflows/test_cli_installed.py"
        prefix = module + "::test_installed_offline"
        nodeids = [prefix + "[copy-paste]", prefix + "[transfer-restore]"]
        self.write_selection([(nodeid, "passed") for nodeid in nodeids],
                             [{"id": nodeid, "outcome": "passed"} for nodeid in nodeids],
                             installed_configuration={"target_declared": True,
                                                      "console_declared": True})
        receipt = audit(self.junit, self.trace, [module],
                        required_passing_prefixes={prefix: 2},
                        require_installed_configuration=True)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [])
        self.assertEqual({case["id"] for case in receipt["cases"]}, set(nodeids))
        self.assertEqual(receipt["unitemized_subtests"]["reported"], 0)

    def test_green_source_cannot_substitute_for_skipped_installed_case(self):
        module = "tests/offline_workflows/test_cli_installed.py"
        source = module + "::test_source_offline[transfer-restore]"
        installed_prefix = module + "::test_installed_offline"
        installed = installed_prefix + "[transfer-restore]"
        self.write_selection([(source, "passed"), (installed, "skipped")],
                             [{"id": source, "outcome": "passed"}],
                             installed_configuration={"target_declared": True,
                                                      "console_declared": True})
        self.assertTrue(audit(self.junit, self.trace, [module])["passed"])
        receipt = audit(self.junit, self.trace, [module],
                        required_passing_prefixes={installed_prefix: 1},
                        require_installed_configuration=True)
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_modules"], [])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [installed_prefix])
        self.assertEqual(receipt["counts"]["passed"], 1)
        self.assertEqual(receipt["counts"]["skipped"], 1)

    def test_missing_required_unique_case_count_is_red(self):
        prefix = "tests/offline_workflows/test_cli_installed.py::test_installed_offline"
        nodeid = prefix + "[copy-paste]"
        self.write_selection([(nodeid, "passed")],
                             [{"id": nodeid, "outcome": "passed"}])
        receipt = audit(self.junit, self.trace, [],
                        required_passing_prefixes={prefix: 2})
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [prefix])
        self.assertEqual(receipt["counts"]["passed"], 1)

    def test_extra_passing_cases_do_not_satisfy_an_exact_smaller_quota(self):
        prefix = "tests/offline_workflows/test_cli_installed.py::test_installed_offline"
        nodeids = [prefix + "[copy-paste]", prefix + "[transfer-restore]"]
        self.write_selection([(nodeid, "passed") for nodeid in nodeids],
                             [{"id": nodeid, "outcome": "passed"} for nodeid in nodeids])
        receipt = audit(self.junit, self.trace, [],
                        required_passing_prefixes={prefix: 1})
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [prefix])

    def test_passed_subtests_cannot_inflate_unique_required_case_count(self):
        one = audit(self.junit, self.trace, [], required_passing_prefixes={FIRST: 1})
        inflated = audit(self.junit, self.trace, [], required_passing_prefixes={FIRST: 3})
        self.assertTrue(one["passed"])
        self.assertEqual(one["missing_required_passing_prefixes"], [])
        self.assertEqual(one["counts"]["passed"], 3)
        self.assertFalse(inflated["passed"])
        self.assertEqual(inflated["missing_required_passing_prefixes"], [FIRST])
        self.assertEqual(len(inflated["cases"]), 2)
        self.assertEqual(len(inflated["call_events"]), 3)

    def test_skipped_subtest_cannot_hide_behind_a_passed_junit_parent(self):
        self.write_junit(skipped=2)
        self.write_trace(calls=[{"id": FIRST, "outcome": "passed"},
                                {"id": FIRST, "outcome": "skipped"},
                                {"id": FIRST, "outcome": "passed"}])
        self.assertTrue(audit(self.junit, self.trace, ["tests/test_first.py"])["passed"])
        receipt = audit(self.junit, self.trace, ["tests/test_first.py"],
                        required_passing_prefixes={FIRST: 1})
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["cases"][0]["outcome"], "passed")
        self.assertEqual(receipt["missing_required_modules"], [])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [FIRST])
        self.assertEqual(receipt["counts"]["skipped"], 2)

    def test_required_passing_counts_must_be_positive_exact_integers(self):
        for count in (True, False, 0, -1, 1.0, "1"):
            with self.subTest(count=count), self.assertRaises(AuditError):
                audit(self.junit, self.trace, [], required_passing_prefixes={FIRST: count})

    def test_required_installed_configuration_is_exact_true_for_both_declarations(self):
        configurations = (None, {}, {"target_declared": True}, {"console_declared": True},
                          {"target_declared": False, "console_declared": True},
                          {"target_declared": True, "console_declared": False},
                          {"target_declared": 1, "console_declared": True},
                          {"target_declared": True, "console_declared": 1},
                          {"target_declared": "true", "console_declared": True})
        for configuration in configurations:
            with self.subTest(configuration=configuration):
                value = json.loads(self.trace.read_text())
                value.pop("installed_offline_configuration", None)
                if configuration is not None:
                    value["installed_offline_configuration"] = configuration
                self.trace.write_text(json.dumps(value))
                self.assertTrue(audit(self.junit, self.trace, ["tests/test_first.py"])["passed"])
                with self.assertRaisesRegex(AuditError, "configured target and console"):
                    audit(self.junit, self.trace, ["tests/test_first.py"],
                          require_installed_configuration=True)

    def test_cli_appended_passing_prefixes_and_installed_guard_are_applied(self):
        module = "tests/offline_workflows/test_cli_installed.py"
        source_prefix = module + "::test_source_offline"
        installed_prefix = module + "::test_installed_offline"
        source = source_prefix + "[copy-paste]"
        installed = installed_prefix + "[transfer-restore]"
        self.write_selection([(source, "passed"), (installed, "passed")],
                             [{"id": source, "outcome": "passed"},
                              {"id": installed, "outcome": "passed"}],
                             installed_configuration={"target_declared": True,
                                                      "console_declared": True})
        output = self.folder / "prefix-receipt.json"
        arguments = ["ci_test_results.py", "--junit", str(self.junit), "--trace", str(self.trace),
                     "--output", str(output), "--selection", "offline",
                     "--require-module", module,
                     "--require-passing-prefix", source_prefix, "1",
                     "--require-passing-prefix", installed_prefix, "1",
                     "--require-installed-configuration"]
        with patch("sys.argv", arguments):
            self.assertEqual(main(), 0)
        receipt = json.loads(output.read_text())
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [])
        self.write_selection([(source, "passed"), (installed, "skipped")],
                             [{"id": source, "outcome": "passed"}],
                             installed_configuration={"target_declared": True,
                                                      "console_declared": True})
        with patch("sys.argv", arguments):
            self.assertEqual(main(), 1)
        receipt = json.loads(output.read_text())
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["missing_required_passing_prefixes"], [installed_prefix])

    def test_cli_missing_installed_configuration_prevents_green_receipt(self):
        output = self.folder / "configuration-receipt.json"
        arguments = ["ci_test_results.py", "--junit", str(self.junit), "--trace", str(self.trace),
                     "--output", str(output), "--selection", "offline",
                     "--require-module", "tests/test_first.py", "--require-installed-configuration"]
        with patch("sys.argv", arguments):
            self.assertEqual(main(), 1)
        receipt = json.loads(output.read_text())
        self.assertFalse(receipt["passed"])
        self.assertRegex(receipt["error"], "configured target and console")
        self.assertNotIn("counts", receipt)

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
