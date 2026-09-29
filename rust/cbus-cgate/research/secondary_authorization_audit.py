#!/usr/bin/env python3
"""Inventory C-Gate 3.4 access-level checks that run outside handler entry.

Reads a private, case-sensitive CFR decompile of the pinned build-2001 jar and
writes a sanitized JSON inventory. No decompiled text is retained: each row
names the obfuscated class and method, the required level, the effect and the
SHA-256 of the owning source file and of the whitespace-normalized anchor
statement, so a reviewer holding the same private decompile can re-locate it.

The curated sites below were found by enumerating every use of the access
level holder (`Cb`), `AccessContext`, `Command.enforceAccess/canAccess`, and
the exposed parameter (`Ck`) and method (`Ch`) security classes. Generated rows
cover every `Cn/Cf/Cc/Cg/Cd` parameter and `Ch` method registration.

The class hierarchy (`extends` chains) maps each registering class to the
cmqttd object kind it backs (root `cgate`, project, network, application,
group or unit). `object_levels` is the per-kind table derived from those rows;
`--rust-table` renders it as `src/object_access_table.rs`, the single table
cmqttd enforces for GET/SET/DO. That step reads only the inventory, so the
table can be re-rendered without the private decompile.
"""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

LEVELS = ['None', 'Connect', 'Monitor', 'Operate', 'Admin', 'Program', 'Debug', 'Clipsal', 'Max']
CAPTURE = 'rust/testdata/fixtures/native_cgate_secondary_authorization_probe.json'

OBJECT_CAPTURE = 'rust/testdata/fixtures/native_cgate_object_authorization_probe.json'
# cmqttd object kinds and the native class whose subclasses back them. A
# registering class maps to every kind whose marker appears in its chain, or
# whose concrete classes inherit from it (for example `Bo` backs every kind).
KINDS = [('cgate', 'CGateManager'), ('project', 'Project'), ('network', 'CBusBaseNetwork'),
         ('application', 'N'), ('group', 'bV'), ('unit', 'CBusUnit')]

# (id, file, method, anchor regex, required level or None, effect, classification, cmqttd, evidence)
CURATED = [
    ('event-port-admission', 'BF.java', 'run', r'\.a >= 2\)', 'Monitor',
     'New event-port peer below the live ACCESS level Monitor is closed at once; event 805 (level 4) '
     '"Access control refused event connection from /IP" is logged.',
     'implemented', 'Service::serve_event_server via admits_event_peer and peer_access_level; 805 event.',
     f'{CAPTURE}#event_admission'),
    ('load-change-port-admission', 'BM.java', 'run', r'\.a >= 2\)', 'Monitor',
     'Load-change listener refuses peers below Monitor and logs 805.',
     'not_applicable', 'cmqttd provides no load-change listener; use-load-change-port is catalogue state only.',
     'source only'),
    ('config-change-port-admission', 'BB.java', 'run', r'\.a >= 2\)', 'Monitor',
     'Config-change listener refuses peers below Monitor and logs 806.',
     'not_applicable', 'cmqttd provides no config-change listener; use-config-change-port is catalogue state only.',
     'source only'),
    ('command-address-admission', 'oG.java', 'run', r'accept-connections-from', None,
     'accept-connections-from list checked per accept; refused command peers stay connected but silent; '
     'event 806 (level 5) is logged.',
     'partial', 'Implemented by accepts_command_peer/hold_silent (native_cgate_config_* receipts); the 806 '
     'event is not emitted. cmqttd also applies the list to its event port (deliberate tightening).',
     'rust/testdata/fixtures/native_cgate_config_event_listener_admission.json'),
    ('command-session-level', 'oE.java', 'a', r'AccessContext\.a\(this\.a\)', 'Connect',
     'Session level is the highest live interface/remote row at connect; no match is level None and the '
     'native session answers 421 and logs "805 cmdN - Access control refused connection from /IP".',
     'implemented', 'connection_io 421 path now logs the numbered 805 event. Deliberate: loopback peers keep '
     'Clipsal when no row admits them, and the optional recovery token admits a LOGIN-only session.',
     f'{CAPTURE}#event_admission.steps[None-row,unmatched]'),
    ('tls-certificate-promotion', 'com/clipsal/cgate/sys/AccessContext.java', 'a(Socket,int)',
     r'getExtensionValue\("2\.5\.29\.35"\)', 'Clipsal',
     'An SSL peer already at Program or above is promoted to Clipsal when the last certificate in its '
     'chain carries one of two embedded vendor authority-key identifiers.',
     'not_applicable', 'Requires Schneider/Clipsal CA-issued certificates. cmqttd never maps certificate '
     'identities to ACCESS (deliberate; --cgate-tls-client-ca is transport admission only).',
     'rust/testdata/fixtures/native_cgate_tls_authorization_probe.json (owned CA: no promotion)'),
    ('login-logout-bypass-floor', 'oI.java', 'a', r'equalsIgnoreCase\("login"\)', None,
     'LOGIN and LOGOUT are dispatched without checkRunCommand, so they work at None.',
     'implemented', 'session_auth runs before handler floors.', f'{CAPTURE}#login_matrix.session_matrix'),
    ('login-user-lookup', 'oT.java', 'a', r'new AccessContext\(8\)', 'Max',
     'LOGIN searches every row with an internal Max context; exact-case username and password; 422 on no '
     'match, 400 without a password; success installs a new AccessContext at the row level, even above '
     'the interface level or at None.',
     'implemented', 'session_auth; one-word LOGIN now returns 400 when no recovery token is configured.',
     f'{CAPTURE}#login_matrix.session_matrix'),
    ('logout-recompute', 'oU.java', 'a', r'\(\(oE\)object\)\.a\(\)', None,
     'LOGOUT re-reads the live ACCESS table for the socket; existing sessions keep their level until then.',
     'implemented', 'session_auth LOGOUT uses connection_access_level.', f'{CAPTURE}#login_matrix.live_access'),
    ('access-row-visibility', 'u.java', 'a(AccessContext)', r'cb2\.b\(', None,
     'ACCESS LIST shows, and ACCESS DELETE numbers, only rows at or below the session level.',
     'implemented', 'Service::access LIST/DELETE filter entry.level() <= level.',
     f'{CAPTURE}#login_matrix.live_access.admin_self_downgrade_list'),
    ('address-match', 'u.java', 'a(InetAddress,InetAddress)', r'for \(int i2 = 0; i2 < 4; \+\+i2\)', None,
     'Row address octet 255 is a wildcard; only the first four address bytes are compared (IPv6 truncated).',
     'partial', 'IPv4 wildcard implemented in access::address_matches; IPv6 compares whole addresses '
     '(deliberate; native truncation not captured).', 'source only'),
    ('peer-level-max', 'u.java', 'a(Socket)', r'if \(n2 < w2\.e\)', None,
     'Level is the maximum of matching interface/remote rows; a row whose name no longer resolves throws '
     'and the caller falls back to level 0 for every peer.',
     'partial', 'Maximum implemented by peer_access_level; cmqttd rejects unresolved names at ACCESS ADD '
     'rather than failing every later admission (deliberate).', 'source only'),
    ('command-trace-visibility', 'com/clipsal/cgate/cmd/Command.java', 'sendCommandEvent',
     r'this\.canAccess\(6\)', 'Debug',
     'Command event 761 and response events 766 are logged only for top-level commands whose floor is '
     'Debug or lower; ACCESS, LOG, PP, SAVE_TO_NVM and START_BACKGROUND_JOB leave no trace.',
     'implemented', 'native_hides_command_trace in publish_command_entry/publish_command_responses.',
     f'{CAPTURE}#command_events'),
    ('login-trace-redaction', 'oT.java', 'sendCommandEvent', r'arguments hidden', None,
     'LOGIN is logged as "Command: LOGIN [arguments hidden]"; LOGOUT as "Command: LOGOUT".',
     'partial', 'cmqttd keeps its established "<redacted command>" and "<redacted>" response text.',
     f'{CAPTURE}#command_events.watcher_rows'),
    ('help-below-floor', 'com/clipsal/cgate/cmd/Command.java', 'displayHelp', r'Command\.syntaxError\(response\)',
     None, 'HELP <command> below the command floor answers a syntax error instead of help or 420.',
     'missing', 'Not compared; cmqttd family help applies the handler floor and answers 420.', 'source only'),
    ('family-subcommand-dispatch', 'oO.java', 'runCommand', r'\.runCommand\(\(AccessContext\)object2',
     None, 'Family commands call a leaf runCommand directly, so a leaf accessControl is not re-checked; only '
     'the family floor and explicit enforceAccess calls apply.',
     'implemented', 'cmqttd enforces the per-path floors observed on the original, which include this effect.',
     'native_cgate_*authorization*_probe.json'),
    ('dali-plan-step-recheck', 'ka.java', 'a', r'enforceAccess\(\(\(ka\)object2\)\.d', 'Program',
     'Each DALI session plan step re-checks its Program-level command against the AccessContext retained '
     'when the plan started; a later LOGIN swap does not affect it.',
     'implemented', 'Redundant with the Program DALI entry floors enforced before a plan starts.', 'source only'),
    ('dali-plan-reset-recheck', 'ka.java', 'b', r'object\.enforceAccess\(this\.d', 'Program',
     'DALI plan reset step re-check, as above.', 'implemented', 'As dali-plan-step-recheck.', 'source only'),
    ('dali-line-recheck', 'kc.java', 'a', r'oL2\.enforceAccess\(this\.d', 'Program',
     'Per-line and per-ECG DALI sub-command re-checks with the retained context.',
     'implemented', 'As dali-plan-step-recheck.', 'source only'),
    ('dali-injected-response', 'mG.java', 'mG', r'enforceAccess\(', 'Program',
     'An injected DALI response step re-checks the retained context and throws CBusCommandException.',
     'implemented', 'As dali-plan-step-recheck.', 'source only'),
    ('programmer-instruction-recheck', 'mu.java', 'runCommand', r'll2\.enforceAccess', 'Clipsal',
     'PROGRAMMER ADD_INSTRUCTION re-checks the instruction class (base lk declares Clipsal; DALI sub-command '
     'classes Program). The obfuscated AddInstType constants make every named instruction type fail parse '
     'first in build 2001, so the Clipsal branch is unreachable.',
     'not_applicable', 'Unreachable natively; cmqttd keeps the observed PROGRAMMER Program entry floor.',
     'source only'),
    ('advisory-lock-owner', 'BN.java', 'lock', r'new WeakReference', None,
     'LOCK owner is a weak reference to the session AccessContext; LOGIN/LOGOUT replace the context, so its '
     'locks release when the collector clears it; relocking is never idempotent.',
     'implemented', 'release_advisory_locks on LOGIN/LOGOUT (deterministic; native release timing varies).',
     f'{CAPTURE}#login_matrix.advisory_lock'),
    ('parameter-read-level', 'Ck.java', 'd', r'Insufficient access level for read', None,
     'GET/SHOW of an exposed parameter below its read level answers "420 Access denied: <object> '
     '(Insufficient access level for read)".', 'implemented',
     'service::object_access applies object_access_table before GET dispatch; <object> is the path as sent.',
     f'{CAPTURE}#login_matrix.cgate_object; {OBJECT_CAPTURE}#matrix'),
    ('parameter-write-level', 'Ck.java', 'e', r'Insufficient access level for write', None,
     'SET below the parameter write level answers "420 Access denied: <object> (Insufficient access level '
     'for write)".', 'implemented',
     'service::object_access applies object_access_table before SET dispatch or PCI I/O.',
     f'{CAPTURE}#login_matrix.cgate_object; {OBJECT_CAPTURE}#matrix'),
    ('method-level', 'Ch.java', 'a', r'Insufficient access level to run method', None,
     'DO/ON/OFF/RAMP/TERMINATERAMP of an exposed method below its level answers 420 "(Insufficient access '
     'level to run method)".', 'implemented',
     'service::object_access applies object_access_table before DO dispatch; ON/OFF/RAMP keep the Operate '
     'handler floor, equal to every group method level.', f'{OBJECT_CAPTURE}#matrix'),
    ('internal-admin-contexts', 'qf.java', 'a', r'new AccessContext\(4\)', 'Admin',
     'Project start/default-project operations run with an internal Admin context.',
     'not_applicable', 'cmqttd has no internal command scripts; project startup is not ACCESS-gated.',
     'source only'),
    ('startup-script-context', 'com/clipsal/cgate/CGateManager.java', 'a', r'new AccessContext\(4\)', 'Admin',
     'Startup command files run with an internal Admin context.', 'not_applicable',
     'cmqttd runs no startup command files.', 'source only'),
    ('console-context', 'oE.java', 'a', r'new AccessContext\(5\)', 'Program',
     'The local console session runs at Program.', 'not_applicable', 'cmqttd has no interactive console.',
     'source only'),
]

REGISTRATION = re.compile(
    r'new (Cg|Cf|Cc|Cn|Cd)\(\s*("[^"]*"|[^,]+),\s*"(?:[^"\\]|\\.)*",\s*(\d+),\s*(\d+),')
METHOD = re.compile(r'new Ch\(\s*("[^"]*"|[^,]+),\s*"(?:[^"\\]|\\.)*",\s*(\d+),')


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized(text):
    return ' '.join(text.split())


def class_index(root):
    """Map simple class names to files; obfuscated root-package names win."""
    index = {}
    for path in sorted(root.rglob('*.java'), key=lambda p: (len(p.relative_to(root).parts), str(p))):
        index.setdefault(path.stem, path)
    return index


def chain_of(name, index):
    chain = [name]
    while chain[-1] in index:
        text = index[chain[-1]].read_text(errors='replace')
        match = re.search(r'class\s+' + re.escape(chain[-1]) + r'\b[^{]*?\bextends\s+([\w.]+)', text)
        parent = match.group(1).split('.')[-1] if match else None
        if not parent or parent in chain:
            break
        chain.append(parent)
    return chain


def resolve_name(expression, text):
    """Resolve `array[i]` parameter names from a static String[] initializer."""
    match = re.fullmatch(r'(\w+)\[(\d+)\]', expression)
    if not match:
        return expression.strip('"')
    init = re.search(re.escape(match.group(1)) + r' = new String\[\]\{([^}]*)\}', text)
    if not init:
        return expression
    values = re.findall(r'"([^"]*)"', init.group(1))
    return values[int(match.group(2))]


def object_levels(rows, chains):
    """Derive the per-kind effective level of every parameter and method.

    Each concrete class of a kind takes the definition from the most derived
    class in its chain. cmqttd cannot tell unit or application subclasses
    apart, so when concrete classes of one kind disagree the table keeps the
    lowest level (never denying what some native class allows) and the higher
    rows stay partial.
    """
    defined = collections.defaultdict(dict)
    for row in rows:
        defined[row['class']][(row['kind'], row['access'], row['name'])] = row['required_level']
    table = {}
    used = collections.defaultdict(set)
    for kind, marker in KINDS:
        concrete = [name for name, chain in chains.items() if marker in chain]
        for name in concrete:
            seen = set()
            for owner in chains[name]:
                for key, level in defined.get(owner, {}).items():
                    if key in seen:
                        continue
                    seen.add(key)
                    table.setdefault((kind,) + key, set()).add(level)
                    used[(owner,) + key].add(kind)
    levels = []
    for (kind, row_kind, access, name), found in sorted(table.items()):
        chosen = min(found, key=LEVELS.index)
        levels.append({'object': kind, 'kind': row_kind, 'access': access, 'name': name,
                       'required_level': chosen, 'native_levels': sorted(found, key=LEVELS.index)})
    return levels, used


def classify(rows, levels, used):
    effective = {(row['object'], row['kind'], row['access'], row['name']): row['required_level']
                 for row in levels}
    for row in rows:
        kinds = sorted(used.get((row['class'], row['kind'], row['access'], row['name']), ()))
        if not kinds:
            row['classification'] = 'not_applicable'
            row['cmqttd'] = ('cmqttd does not model this native child class. Unit terminal paths '
                             '(//P/N/p/U/T) take their unit\'s levels (fail closed); other child paths '
                             'do not resolve to an object.')
            continue
        applied = {effective[(kind, row['kind'], row['access'], row['name'])] for kind in kinds}
        if applied == {row['required_level']}:
            row['classification'] = 'implemented'
            row['cmqttd'] = f"object_access_table ({', '.join(kinds)}) enforced before dispatch."
        else:
            row['classification'] = 'partial'
            row['cmqttd'] = (f"object_access_table ({', '.join(kinds)}) applies "
                             f"{'/'.join(sorted(applied, key=LEVELS.index))}: cmqttd does not resolve the "
                             'native subclass, so the lowest level among sibling classes is enforced.')
        row['object_kinds'] = kinds


def rust_table(inventory):
    variants = {'cgate': 'Root', 'project': 'Project', 'network': 'Network',
                'application': 'Application', 'group': 'Group', 'unit': 'Unit'}
    parameters = collections.defaultdict(dict)
    methods = []
    for row in inventory['object_levels']:
        if row['kind'] == 'method':
            methods.append((row['object'], row['name'], row['required_level']))
        else:
            parameters[(row['object'], row['name'])][row['access']] = row['required_level']
    out = ['// @generated by rust/cbus-cgate/research/secondary_authorization_audit.py --rust-table.',
           '// Do not edit: regenerate from secondary-authorization-inventory.json `object_levels`.',
           '',
           'use super::ObjectKind::{self, *};',
           'use crate::access::CgateAccessLevel::{self, *};',
           '',
           '/// (object, parameter, read level, write level).',
           'pub(crate) const PARAMETERS: &[(ObjectKind, &str, CgateAccessLevel, CgateAccessLevel)] = &[']
    for (kind, name), access in sorted(parameters.items(), key=lambda item: (variants[item[0][0]], item[0][1])):
        out.append(f'    ({variants[kind]}, "{name}", {access["read"]}, {access["write"]}),')
    out += ['];', '', '/// (object, method, run level).',
            'pub(crate) const METHODS: &[(ObjectKind, &str, CgateAccessLevel)] = &[']
    for kind, name, level in sorted(methods, key=lambda item: (variants[item[0]], item[1])):
        out.append(f'    ({variants[kind]}, "{name}", {level}),')
    out.append('];')
    return '\n'.join(out) + '\n'


def audit(root):
    curated = []
    for (ident, rel, method, anchor, level, effect, status, cmqttd, evidence) in CURATED:
        path = root / rel
        text = path.read_text(errors='replace')
        lines = [line for line in text.splitlines() if re.search(anchor, line)]
        if not lines:
            raise SystemExit(f'anchor not found for {ident} in {rel}')
        curated.append({
            'id': ident, 'class': path.stem, 'method': method, 'required_level': level,
            'effect': effect, 'classification': status, 'cmqttd': cmqttd, 'native_evidence': evidence,
            'evidence': {'file_sha256': digest(text), 'anchor_sha256': digest(normalized(lines[0])),
                         'anchor_occurrences': len(lines)},
        })
    objects = []
    for path in sorted(root.rglob('*.java')):
        text = path.read_text(errors='replace')
        file_hash = None
        for match in REGISTRATION.finditer(text):
            file_hash = file_hash or digest(text)
            name = resolve_name(match.group(2), text)
            read, write = int(match.group(3)), int(match.group(4))
            for access, level in (('read', read), ('write', write)):
                objects.append({
                    'kind': 'parameter', 'access': access, 'class': path.stem, 'name': name,
                    'required_level': LEVELS[level],
                    'evidence': {'file_sha256': file_hash, 'anchor_sha256': digest(normalized(match.group(0)))},
                })
        for match in METHOD.finditer(text):
            file_hash = file_hash or digest(text)
            objects.append({
                'kind': 'method', 'access': 'run', 'class': path.stem, 'name': resolve_name(match.group(1), text),
                'required_level': LEVELS[int(match.group(2))],
                'evidence': {'file_sha256': file_hash, 'anchor_sha256': digest(normalized(match.group(0)))},
            })
    index = class_index(root)
    chains = {name: chain_of(name, index) for name in sorted({row['class'] for row in objects})}
    for _, marker in KINDS:
        chains.setdefault(marker, chain_of(marker, index))
    levels, used = object_levels(objects, chains)
    classify(objects, levels, used)
    counts = collections.Counter(row['classification'] for row in curated + objects)
    return {
        'schema': 'cbus-cgate-secondary-authorization-inventory-v1',
        'target': 'C-Gate 3.4.0 build 2001 (cgate.jar sha256 '
                  '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630)',
        'source': 'private case-sensitive CFR 0.152 decompile; no decompiled text retained',
        'generator_sha256': digest(Path(__file__).read_text()),
        'counts': dict(sorted(counts.items())),
        'sites': curated,
        'object_model': objects,
        'class_chains': chains,
        'object_levels': levels,
        'native_evidence': OBJECT_CAPTURE,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decompile', type=Path, help='CFR src directory')
    parser.add_argument('--output', type=Path, required=True, help='inventory JSON (read with --rust-table only)')
    parser.add_argument('--rust-table', type=Path, help='render object_levels from the inventory to this .rs file')
    args = parser.parse_args()
    if args.decompile is None:
        if args.rust_table is None:
            parser.error('--decompile or --rust-table is required')
        args.rust_table.write_text(rust_table(json.loads(args.output.read_text())))
        raise SystemExit(0)
    result = audit(args.decompile.resolve())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.rust_table is not None:
        args.rust_table.write_text(rust_table(result))
    print(json.dumps({'sites': len(result['sites']), 'object_rows': len(result['object_model']),
                      'counts': result['counts']}))
