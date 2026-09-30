"""Cross-reference every Toolkit 1.18 preference object to its runtime consumers.

Reads the pinned original EXE/MAP locally and, optionally, the decompiled
eDLT/.NET assemblies. It never loads or executes vendor code. The committed
receipt contains only hashes, addresses, symbol names, short literals and the
curated classification below; it is the denominator for "preference runtime
effects" (issue #61, P9.02).

Delphi code does not reference the preference globals directly outside their
unit initializers: every other unit loads a pointer slot in .data that holds
the variable address (``mov eax, [slot]; mov eax, [eax]``) and then reads the
typed value field (+0x18 string, +0x1a boolean, +0x20 integer). This scan
finds those slots, every code reference to them and the owning MAP routine.

Usage:
    python research/preference_runtime_consumers_static.py \
        --exe CBusToolkit.exe --map CBusToolkit.map [--app-dir APP] [--edlt-decompiled DIR] \
        > research/experiments/2026-09-30/preference-runtime-consumers.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from csv_factory_registry_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from cbus_toolkit.toolkit_preferences_store import PREFERENCE_DEFINITIONS  # noqa: E402

FORMAT = 'cbus-toolkit-preference-runtime-consumers-v1'
DIALOG = ('CIS_TfrmKipperPreferences.TfrmKipperPreferences.',)
KIND_CLASSES = {'boolean': 'CIS_Preferences..TBooleanPreference',
                'integer': 'CIS_Preferences..TIntegerPreference',
                'string': 'CIS_Preferences..TStringPreference'}
VALUE_FIELDS = {0x18: 'string', 0x1a: 'boolean', 0x20: 'integer'}
SET_VALUE = 'CIS_Preferences.TStringPreference.SetValue'

# Registered name -> (MAP variable, status, runtime feature, observed effect, CLI surface/reason).
# Status: cli-honored | gui-only | not-implemented | no-runtime-consumer.
CURATED = {
    'LoadChangePortDisable': ('CIS_CBusPreferences.PrefCGateLoadChangePortDisable', 'gui-only',
        'Scene Manager capture/live actions',
        'OnUpdate handlers disable the Capture Scene and Live Scene actions when set.',
        'The CLI has no Scene Manager action list; C-Gate load-change port configuration is not managed.'),
    'ApplicationLogDisable': ('CIS_CBusPreferences.PrefCGateApplicationLogDisable', 'gui-only',
        'Application Log view and load-change event processing',
        'Suppresses Application Log load-change entries and changes the log heading/pause action state.',
        'The CLI streams C-Gate events verbatim (cgate events); it has no Application Log view.'),
    'TemperatureUnit': ('CIS_CBusPreferences.PrefTemperatureUnit', 'cli-honored',
        'Thermostat/SENTEMP conversions, dialogs, documentor HTML and network-log text',
        'All reads test the low byte of the integer (+0x20); non-zero selects Fahrenheit conversions.',
        'thermostat-temperature convert --preferences FILE applies the same low-byte rule to the 14 '
        'scalar conversions. Unit dialogs are GUI-only; the CLI documentor does not emit temperatures.'),
    'DoNotPauseEventsWhileLoadingProject': ('CIS_CBusPreferences.PrefDoNotPauseEventsWhileLoadingProject',
        'not-implemented', 'C-Gate PROJECT LOAD, DBGETXML and unit-catalogue commands',
        'Copied into TcgcProjectLoad/TcgcDBGetXML/TcgcPPGetUnitSpecCatalog. Their begin/end hooks test it '
        'with no dependent action (the pause is compiled out). Only TcgcDBGetXML.OnProcessResults acts: '
        'when false, a completed DBGETXML re-enables event monitoring (TcgcEvent level 6 = "event e5s1c1").',
        'CLI C-Gate sessions never pause or enable event monitoring around DBGETXML; adding the re-enable '
        'would change session event levels for every database read, so it is recorded, not emulated.'),
    'ShowProjectManager': ('CIS_TKipperPreferences.PrefShowProjectManager', 'gui-only',
        'Main form create/close', 'Shows the project manager pane and stores its visibility on close.',
        'Window layout only.'),
    'RememberProjectManagerVisibleState': ('CIS_TKipperPreferences.PrefRememberProjectManagerVisibleState',
        'gui-only', 'Main form create/close', 'Selects whether pane visibility is remembered.',
        'Window layout only.'),
    'Default Site': ('CIS_TKipperPreferences.PrefDefaultSite', 'cli-honored',
        'Startup site selection and site-open write-back',
        'Startup reads the string; empty becomes LOCAL. UpperCase(site)=LOCAL opens the local C-Gate; '
        'other names resolve through the Toolkit C-Gate site list. Opening a site writes LOCAL for a '
        'localhost/127.0.0.1 site, otherwise the site name.',
        'cgate --preferences FILE selects 127.0.0.1 for empty/LOCAL when --host is omitted and rejects a '
        'named site (the site list is not modelled). The write-back is not performed.'),
    'Default COM Port': ('CIS_TKipperPreferences.PrefDefaultCOMPort', 'not-implemented',
        'Discover Project default interface, Setup Default Interface, installation HTML, units-node scan',
        'Supplies the serial port for the default-interface project and TCBusNetwork.ScanPhysicalNetwork.',
        'CLI interface/network commands take explicit ports; the default-interface project workflow is absent.'),
    'Default Interface Type': ('CIS_TKipperPreferences.PrefDefaultInterfaceType', 'not-implemented',
        'Discover Project default interface and Setup Default Interface',
        'Selects serial versus CNI for the default-interface project.',
        'The default-interface project workflow is absent; CLI commands take an explicit interface.'),
    'Default CNI Address': ('CIS_TKipperPreferences.PrefDefaultCNIAddress', 'not-implemented',
        'Discover Project default interface and Setup Default Interface',
        'Supplies the CNI address for the default-interface project and CNI tree highlighting.',
        'The default-interface project workflow is absent; CLI commands take an explicit address.'),
    'AutoInvokeMacroFunctionDialog': ('CIS_TKipperPreferences.PrefAutoInvokeMacroFunctionDialog', 'gui-only',
        'Key/IO unit dialog extension clicks', 'Opens the macro-function dialog automatically.',
        'Dialog navigation only.'),
    'AutoInvokeDatabaseUnitDialog': ('CIS_TKipperPreferences.PrefAutoInvokeDatabaseUnitDialog', 'gui-only',
        'Add Unit actions', 'Opens the new database unit dialog after adding a unit.',
        'Dialog navigation only; CLI unit creation returns JSON.'),
    'SynchroniseFilters': ('CIS_TKipperPreferences.PrefSynchroniseFilters', 'gui-only',
        'Units node display-all actions', 'Keeps database/network unit grid filters synchronised.',
        'Grid filter state only.'),
    'CGateShutdownOnExit': ('CIS_TKipperPreferences.PrefCGateShutdownOnExit', 'not-implemented',
        'Application exit', 'With the Ask/Decision values, selects C-Gate server shutdown on Toolkit exit '
        '(refused when other clients are connected, then projects are closed).',
        'The CLI has no application-exit lifecycle; project close and shutdown are explicit commands.'),
    'CGateShutdownOnExitAsk': ('CIS_TKipperPreferences.PrefCGateShutdownOnExitAsk', 'not-implemented',
        'Application exit and close query', 'Asks at exit and routes the remembered decision.',
        'No application-exit lifecycle or prompt in the CLI.'),
    'CloseProjectsOnExit': ('CIS_TKipperPreferences.PrefCloseAllProjectsOnExit', 'not-implemented',
        'Application exit', 'Closes all C-Gate projects (PROJECT LIST then normal close) on exit.',
        'No application-exit lifecycle in the CLI.'),
    'CGateShutdownDecision': ('CIS_TKipperPreferences.PrefCGateShutdownDecision', 'not-implemented',
        'Application exit and close query', 'Stores the answer used when Ask is set.',
        'No application-exit lifecycle in the CLI.'),
    'UnitDialogOverride': ('CIS_TKipperPreferences.PrefUnitDialogModeOverride', 'gui-only',
        'Unit dialog selection', 'Forces the configured simple/advanced unit dialog mode.',
        'Dialog selection only.'),
    'UnitDialogModeAdvanced': ('CIS_TKipperPreferences.PrefUnitDialogModeAdvanced', 'gui-only',
        'Unit dialog selection', 'Chooses advanced unit dialog mode.', 'Dialog selection only.'),
    'UnitDialogAlwaysClassic': ('CIS_TKipperPreferences.PrefUnitDialogModeAlwaysClassic', 'gui-only',
        'Unit grid double-click', 'Opens the classic unit dialog.', 'Dialog selection only.'),
    'FeedbackLog': ('CIS_TKipperPreferences.PrefFeedbackLogEnable', 'not-implemented',
        'Application feedback log (TZippedLog) at start-up', 'Enables the zipped feedback log.',
        'The CLI has no Toolkit feedback log.'),
    'FeedbackLogFile': ('CIS_TKipperPreferences.PrefFeedbackLogFile', 'not-implemented',
        'Application feedback log at start-up', 'Supplies the log file name (combined with the program path).',
        'The CLI has no Toolkit feedback log.'),
    'FeedbackLogSize': ('CIS_TKipperPreferences.PrefFeedbackLogSize', 'not-implemented',
        'Application feedback log at start-up', 'Sets the zip size limit.', 'The CLI has no Toolkit feedback log.'),
    'JavaHeapMin': ('CIS_TKipperPreferences.PrefJavaHeapMin', 'not-implemented',
        'Preferences action follow-up', 'A heap change while a site is open raises a restart notice.',
        'The CLI does not manage C-Gate service JVM configuration or restarts.'),
    'JavaHeapMax': ('CIS_TKipperPreferences.PrefJavaHeapMax', 'not-implemented',
        'Preferences action follow-up', 'A heap change while a site is open raises a restart notice.',
        'The CLI does not manage C-Gate service JVM configuration or restarts.'),
    'IlluminanceMeasurementUnit': ('CIS_TKipperPreferences.PrefIlluminanceMeasurementUnit',
        'no-runtime-consumer', None, 'Registered and persisted only.', 'No consumer to honor.'),
    'ClipsalWebsiteURL': ('CIS_TKipperPreferences.PrefClipsalWebsite', 'gui-only',
        'Help menu web-site action', 'ShellExecute opens the URL.', 'Browser launch only.'),
    'CISDownloadsURL': ('CIS_TKipperPreferences.PrefCISDownloads', 'gui-only',
        'Check New Version action', 'ShellExecute opens the downloads URL; no version metadata is read.',
        'Browser launch only; CLI update commands use explicit metadata inputs.'),
    'AllowLegacyApplicationCreation': ('CIS_TKipperPreferences.PrefAllowLegacyApplicationCreation',
        'not-implemented', 'Application dialog allowlist and main-form control visibility',
        'TCBUSApplicationManager.IsAllowedApplication: legacy allows 0x30-0x7F/0x88 with the dialog flag, '
        'otherwise any address below 0xFF.',
        'CLI project/database application creation does not apply the dialog allowlist; the dialog flag '
        '(TfrmApplication+0x3F1, copied from its owner) is not resolved.'),
    'AllowUserDefinedApplicationCreation': ('CIS_TKipperPreferences.PrefAllowUserDefinedApplicationCreation',
        'not-implemented', 'Application dialog allowlist',
        'Without legacy: user-defined allows 0x30-0x7F/0x88 with the dialog flag, otherwise 1-15; '
        '0x30-0x5F, 0x70-0x72 and 0x88 are always allowed.',
        'Same as AllowLegacyApplicationCreation.'),
    'LegacyDuplicateUnitsDetection': ('CIS_TKipperPreferences.PrefLegacyDuplicateUnitsDetection',
        'no-runtime-consumer', None, 'Registered and persisted only.', 'No consumer to honor.'),
    'ShowDatabaseLabelsOption': ('CIS_TKipperPreferences.PrefShowDatabaseLabelsOption',
        'no-runtime-consumer', None, 'Registered and persisted only.', 'No consumer to honor.'),
}
for _index in range(1, 9):
    CURATED[f'Default Language {_index}'] = (
        f'CIS_DLTPreferences.PrefDefaultNetworkLanguage{_index}', 'not-implemented',
        'New network language list (TCBusNetwork.InitialiseLanguages)',
        'PopulateNetworkDefaults adds the eight languages in order; language 1 is added as primary.',
        'CLI project/network creation does not synthesize Toolkit network language lists.')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sections(image):
    return {section.Name.rstrip(b'\0').decode(): section for section in image.pe.sections}


def _variables(image, map_bytes):
    bss = image.base + _sections(image)['.bss'].VirtualAddress
    found = {}
    for line in map_bytes.decode('ascii').splitlines():
        match = re.match(r'^\s+0004:([0-9A-Fa-f]{8})\s+(CIS_\w+Preferences\.Pref\w+)\s*$', line)
        if match:
            found[match[2]] = bss + int(match[1], 16)
    return found


def _find(data, start, value):
    return [start + m.start() for m in re.finditer(re.escape(struct.pack('<I', value)), data)]


def _instruction_at(image, operand):
    """Decode the instruction whose 32-bit absolute operand starts at ``operand``."""
    for back in (1, 2):
        rows = list(image.disassembler.disasm(image.raw(operand - back, 16), operand - back, 1))
        if rows and rows[0].size == back + 4:
            return rows[0]
    raise ValueError(f'Cannot decode preference slot reference at {operand:#x}')


def _access(image, first):
    """Follow ``mov r,[slot]; mov r2,[r]`` to the typed value access or setter call."""
    rows = list(image.disassembler.disasm(image.raw(first.address, 64), first.address, 8))
    register = first.op_str.split(',')[0].strip()
    for row in rows[1:]:
        if row.mnemonic == 'mov' and row.op_str.endswith(f'dword ptr [{register}]'):
            register = row.op_str.split(',')[0].strip()
            continue
        match = re.search(rf'\[{register} \+ (0x[0-9a-f]+)\]', row.op_str)
        if match is None and row.op_str.startswith(register + ',') and row.mnemonic in ('mov', 'lea', 'xor', 'movzx'):
            break  # the object pointer was replaced before any typed field access
        if match:
            offset = int(match[1], 16)
            write = row.op_str.startswith(('byte ptr', 'dword ptr', 'word ptr')) and row.mnemonic == 'mov'
            return {'instruction': f'{row.mnemonic} {row.op_str}', 'field': VALUE_FIELDS.get(offset, hex(offset)),
                    'write': write}
        if row.mnemonic == 'call':
            target = image.name(int(row.op_str, 16)) if row.op_str.startswith('0x') else None
            return {'instruction': f'call {target or row.op_str}', 'field': None, 'write': target == SET_VALUE}
    return {'instruction': None, 'field': None, 'write': None}


def _initializer_kind(image, variable):
    """Return the preference class stored into ``variable`` by its unit initializer."""
    itext = _sections(image)['.itext']
    start, data = image.base + itext.VirtualAddress, itext.get_data()
    for operand in _find(data, start, variable):
        store = _instruction_at(image, operand)
        if store.mnemonic == 'mov' and store.op_str.startswith('eax, 0x'):
            # DLT languages pass the variable address to RegInt, which creates the object.
            following = list(image.disassembler.disasm(image.raw(store.address, 16), store.address, 3))
            call = next((row for row in following if row.mnemonic == 'call'), None)
            if call is not None and image.name(int(call.op_str, 16)) == 'CIS_DLTPreferences.RegInt':
                helper = _method_text(image, 'CIS_DLTPreferences.RegInt', 0xa0)
                for index, (_, mnemonic, op) in enumerate(helper):
                    if mnemonic == 'call' and image.name(int(op, 16)) == 'CIS_Preferences.TCISPreference.create':
                        load = next(row for row in reversed(helper[:index])
                                    if row[1] == 'mov' and row[2].startswith('eax, dword ptr [0x'))
                        return image.name(int(load[2][16:-1], 16))
        if store.mnemonic != 'mov' or not store.op_str.startswith('dword ptr [0x'):
            continue
        for back in range(12, 30):
            rows = list(image.disassembler.disasm(image.raw(store.address - back, back), store.address - back))
            if rows and sum(row.size for row in rows) == back:
                for row in reversed(rows):
                    match = re.fullmatch(r'eax, dword ptr \[(0x[0-9a-f]+)\]', row.op_str)
                    if row.mnemonic == 'mov' and match:
                        return image.name(int(match[1], 16))
    raise ValueError(f'No initializer store for {variable:#x}')


def _method_text(image, name, limit=0x800):
    rows = []
    for address in sorted(image.by_name[name]):
        rows += [(row.address, row.mnemonic, row.op_str)
                 for row in image.disassembler.disasm(image.raw(address, limit), address)]
    return rows


def _wide_literal(image, address):
    try:
        length = struct.unpack('<i', image.raw(address - 4, 4))[0]
        return image.raw(address, 2 * length).decode('utf-16-le') if 0 < length < 128 else None
    except Exception:  # pefile raises its own error for BSS/unmapped addresses
        return None


def _literals(image, name, limit=0x800):
    found = []
    for _, _, op in _method_text(image, name, limit):
        for token in re.findall(r'0x[0-9a-f]{6,}', op):
            text = _wide_literal(image, int(token, 16))
            if text and text.isprintable() and text not in found:
                found.append(text)
    return found


def _behavior_checks(image, consumers):
    checks = {}
    temperature = [site for site in consumers['TemperatureUnit']
                   if not site['function'].startswith(DIALOG)]
    checks['temperature_unit_low_byte_nonzero'] = bool(temperature) and all(
        re.fullmatch(r'cmp byte ptr \[e[a-z]x \+ 0x20\], 0', site['access']['instruction'] or '')
        for site in temperature if 'TCBusThermostatCGateAgent' in site['function'])
    thermostat = {site['function'].rsplit('.', 1)[1] for site in temperature
                  if 'TCBusThermostatCGateAgent' in site['function']}
    from cbus_toolkit.thermostat_temperature import METHODS
    checks['temperature_unit_thermostat_methods_match_cli'] = thermostat == set(METHODS)
    startup = _method_text(image, 'CIS_TddKipper.TddKipper.ProcessCommandLineParams', 0x200)
    checks['default_site_empty_becomes_local'] = 'LOCAL' in _literals(
        image, 'CIS_TddKipper.TddKipper.ProcessCommandLineParams', 0x200) and any(
        m == 'call' and image.name(int(op, 16)) == 'CIS_TddKipper.OpenSite'
        for _, m, op in startup if op.startswith('0x'))
    open_site = _method_text(image, 'CIS_TddKipper.OpenSite', 0x140)
    names = {image.name(int(op, 16)) for _, m, op in open_site if m == 'call' and op.startswith('0x')}
    checks['default_site_uppercase_local_else_site_list'] = (
        {'SysUtils.UpperCase', 'CIS_TCGateSite.TCGateSiteManager.ItemBySiteName'} <= names
        and 'LOCAL' in _literals(image, 'CIS_TddKipper.OpenSite', 0x140))
    checks['local_host_literals'] = {'localhost', '127.0.0.1'} <= set(
        _literals(image, 'CIS_TCGateSite.TCGateSite.IsLocalHost', 0xa0))
    resume = _method_text(image, 'CIS_TcgcDBGetXML.TcgcDBGetXML.OnProcessResults', 0x200)
    checks['dbgetxml_resumes_event_monitoring'] = any(
        m == 'call' and image.name(int(op, 16)) == 'CIS_TCGateCommunicator.TCGateCommunicator.SetEventMonitoring'
        for _, m, op in resume if op.startswith('0x'))
    event = _literals(image, 'CIS_TcgcEvent.TcgcEvent.GenerateCommandText', 0x1a0)
    checks['event_command_literals'] = {'event e5', 's1', 'c1'} <= set(event)
    dead = True
    for name, flag in (('CIS_TcgcProjectLoad.TcgcProjectLoad.CommandExecuteBegin', '0x98'),
                       ('CIS_TcgcDBGetXML.TcgcDBGetXML.CommandExecuteBegin', '0x99'),
                       ('CIS_TcgcPPGetUnitSpecCatalog.TcgcPPGetUnitSpecCatalog.CommandExecuteBegin', '0x98')):
        rows = _method_text(image, name, 0x40)
        index = next(i for i, (_, m, op) in enumerate(rows) if m == 'cmp' and f'+ {flag}]' in op)
        dead = dead and not rows[index + 1][1].startswith('j')
    checks['pause_hooks_have_no_dependent_branch'] = dead
    return checks


def _dotnet(app_dir, edlt_dir):
    names = [spec.name for spec in PREFERENCE_DEFINITIONS]
    result = {'assemblies': {}, 'decompiled_sources': None}
    if app_dir is not None:
        for path in sorted(list(app_dir.glob('*.dll')) + list(app_dir.glob('*.exe'))):
            if path.name == 'CBusToolkit.exe':
                continue
            data = path.read_bytes()
            hits = [name for name in names if name.encode('utf-16-le') in data]
            if hits:
                result['assemblies'][path.name] = {'sha256': _sha(data), 'utf16_substring_hits': hits}
    if edlt_dir is not None:
        literal = {name: 0 for name in names}
        files = sorted(edlt_dir.rglob('*.cs'))
        for path in files:
            text = path.read_text(encoding='utf-8', errors='replace')
            for name in names:
                literal[name] += text.count(f'"{name}"')
        display = files and any(path.name == 'GlobalSoftwareParameters.cs' for path in files)
        result['decompiled_sources'] = {
            'files_scanned': len(files),
            'exact_string_literal_hits': {name: count for name, count in literal.items() if count},
            'registry_reader': 'CBusLogicModel.GlobalSoftwareParameters' if display else None,
            'registry_values_read': ['DisplayHexAddress', 'DisplayAddressValue', 'SortModeApplications',
                                     'SortModeGroups', 'SortModeLevels'] if display else [],
        }
    return result


def inspect(exe_path, map_path, app_dir=None, edlt_dir=None):
    exe, map_bytes = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe) != EXE_SHA256 or _sha(map_bytes) != MAP_SHA256:
        raise ValueError('Original EXE/MAP hashes differ from the pinned Toolkit 1.18 files')
    image = _Image(exe, map_bytes)
    variables = _variables(image, map_bytes)
    if set(variables) != {row[0] for row in CURATED.values()} or len(variables) != 40:
        raise ValueError('MAP preference variables differ from the curated forty')
    sections = _sections(image)
    data_start = image.base + sections['.data'].VirtualAddress
    data = sections['.data'].get_data()
    code = [(image.base + sections[name].VirtualAddress, sections[name].get_data()) for name in ('.text', '.itext')]
    rows, consumers = [], {}
    for spec in PREFERENCE_DEFINITIONS:
        symbol, status, feature, effect, cli = CURATED[spec.name]
        variable = variables[symbol]
        kind = _initializer_kind(image, variable)
        if kind != KIND_CLASSES[spec.kind]:
            raise ValueError(f'{spec.name} initializer class {kind} differs from {spec.kind}')
        direct = sorted({image.owner(ref) for start, blob in code for ref in _find(blob, start, variable)})
        slots = _find(data, data_start, variable)
        sites = []
        for slot in slots:
            for start, blob in code:
                for operand in _find(blob, start, slot):
                    instruction = _instruction_at(image, operand)
                    sites.append({'address': hex(instruction.address), 'function': image.owner(operand),
                                  'access': _access(image, instruction)})
        sites.sort(key=lambda site: int(site['address'], 16))
        consumers[spec.name] = sites
        runtime = sorted({site['function'] for site in sites if not site['function'].startswith(DIALOG)})
        dialog = sorted({site['function'] for site in sites if site['function'].startswith(DIALOG)})
        if (status == 'no-runtime-consumer') != (not runtime):
            raise ValueError(f'{spec.name} classification disagrees with its consumers')
        rows.append({
            'name': spec.name, 'kind': spec.kind, 'map_variable': symbol, 'variable': hex(variable),
            'initializer_class': kind, 'direct_reference_owners': direct,
            'pointer_slots': [hex(slot) for slot in slots],
            'preferences_dialog_consumers': dialog, 'runtime_consumers': runtime,
            'sites': sites, 'status': status, 'feature': feature, 'effect': effect, 'cli': cli,
        })
    checks = _behavior_checks(image, consumers)
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError('Original behavior differs from the curated classification: ' + ', '.join(failed))
    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    return {
        'format': FORMAT,
        'original_exe_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_executed': False,
        'script_sha256': _sha(Path(__file__).read_bytes()),
        'preferences': rows,
        'status_counts': dict(sorted(counts.items())),
        'checks': {name: True for name in sorted(checks)},
        'dotnet': _dotnet(app_dir, edlt_dir),
        'limit': ('Static cross-reference of the pinned Delphi EXE. Preference objects reached only through '
                  'TPreferenceManager load/save are counted as persistence, not runtime effects. Effects are '
                  'read from disassembly, not executed; GUI rendering, dialog event dispatch and the '
                  'Toolkit site list are not exercised. .NET results are UTF-16 substring and decompiled '
                  'literal scans: the eDLT hit is the HVAC widget "TemperatureUnits" list, not this preference.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--app-dir', type=Path)
    parser.add_argument('--edlt-decompiled', type=Path)
    args = parser.parse_args()
    result = inspect(args.exe, args.map, args.app_dir, args.edlt_decompiled)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
