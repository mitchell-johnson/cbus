"""JSON inputs for retained Toolkit preferences and explicit control plans."""
from __future__ import annotations
import json
from pathlib import Path

from .toolkit_preferences_controls import ToolkitPreferenceControls
from .toolkit_preferences_store import (
    DISPLAY_DEFINITIONS, PREFERENCE_DEFINITIONS, validate_values, validate_display_values,
)

STATE_FORMAT = 'cbus-toolkit-preferences-state-v1'


def options(commands):
    parser = commands.add_parser('preferences', help='Inspect retained Toolkit settings and plan ordered preference control edits')
    operations = parser.add_subparsers(dest='action', required=True)
    operations.add_parser('schema', help='List all 40 registered settings and five display values')
    operations.add_parser('initial-state', help='Emit observed constructor values and display fallbacks; no current settings are read')
    reset = operations.add_parser('reset-dont-ask-again', help='Delete the original Windows DontAskAgain preference subtree')
    reset.add_argument('--dry-run', action='store_true', help='Show the exact subtree and bounds without registry access')
    reset.add_argument('--max-keys', type=int, default=256)
    reset.add_argument('--max-depth', type=int, default=32)
    reset.add_argument('--max-name-units', type=int, default=1024)
    show = operations.add_parser('controls', help='Load preference controls from an explicit retained state')
    show.add_argument('file', type=Path)
    plan = operations.add_parser('plan', help='Plan ordered control edits and the original OK-handler assignments')
    plan.add_argument('file', type=Path)
    plan.add_argument('--edit', action='append', default=[], metavar='CONTROL=JSON',
                      help='Repeat in execution order; values are JSON booleans, integers or strings')
    load = operations.add_parser('registry-load', help='Load Windows settings with original copy/default behavior; this can write missing values')
    load.add_argument('file', type=Path, help='Explicit full retained state used when values cannot be loaded')
    save = operations.add_parser('registry-save', help='Save explicit retained values to the Windows registry in original order')
    save.add_argument('file', type=Path)
    save.add_argument('--dry-run', action='store_true', help='Show planned writes assuming machine-hive writes succeed, without registry access')
    for operation in (show, plan, load):
        operation.add_argument('--numeric-locale', choices=('dot', 'comma'),
            help='Use bounded original numeric conversion with an explicit decimal separator; default is canonical integers')



def _json(raw):
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def nonfinite(value): raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def read_state(path):
    with path.open('rb') as stream: raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024: raise ValueError('Preference state exceeds 1 MiB')
    document=_json(raw)
    if not isinstance(document,dict) or set(document)!={'format','values','display_values'} or document['format']!=STATE_FORMAT:
        raise ValueError('Expected a complete cbus-toolkit-preferences-state-v1 document')
    if not isinstance(document['values'], dict) or not isinstance(document['display_values'], dict):
        raise ValueError('Preference values and display values must be JSON objects')
    return validate_values(document['values']),validate_display_values(document['display_values'])


def edits(arguments):
    if len(arguments)>1024: raise ValueError('At most 1024 ordered control edits are supported')
    result=[]
    for text in arguments:
        if len(text)>8192: raise ValueError('Preference control edit exceeds 8192 characters')
        name,separator,value=text.partition('=')
        if not separator or not name: raise ValueError('Preference edits use CONTROL=JSON')
        result.append((name,_json(value)))
    return tuple(result)


def _locale(args):
    selected = getattr(args, 'numeric_locale', None)
    return {None: None, 'dot': ('.', ','), 'comma': (',', '.')}[selected]


def run(args):
    if args.action=='initial-state':
        from .toolkit_preferences_initial_state import constructor_state
        return constructor_state(),0
    if args.action=='reset-dont-ask-again':
        return reset_operation(args)
    if args.action=='schema':
        return {'registered_preferences':[{'name':d.name,'kind':d.kind,'machine_first':d.machine_first,
            'skip_save':d.skip_save,'alternate_key':d.alternate_key,'key':d.key} for d in PREFERENCE_DEFINITIONS],
            'display_preferences':[{'name':name,'registry_name':registry} for name,registry in DISPLAY_DEFINITIONS],
            'state_format':STATE_FORMAT,'startup_defaults_inferred':False,'registry_accessed':False},0
    values,display=read_state(args.file)
    if args.action in ('registry-load','registry-save'):
        return registry_operation(args,values,display)
    # The retained UI model accepts the canonical boolean subset of stored DWORDs.
    if any(value not in (0,1) for value in display.values()):
        raise ValueError('Control loading currently requires display values equal to 0 or 1')
    editor=ToolkitPreferenceControls(values,{key:bool(value) for key,value in display.items()},
                                     numeric_locale=_locale(args))
    if args.action=='controls': return editor.as_dict(),0
    operations=edits(args.edit)
    for name,value in operations: editor.set_control(name,value)
    plan=editor.plan_save().as_dict()
    plan['controls']=editor.as_dict()
    plan['ordered_edits']=[{'control':name,'value':value} for name,value in operations]
    plan['state']={'format':STATE_FORMAT,'values':plan['values'],'display_values':plan['display_values']}
    return plan,0


def registry_backend():
    from .windows_preferences import WindowsPreferenceRegistry
    return WindowsPreferenceRegistry()


class _PlannedRegistry:
    def read_value(self,*args):
        raise AssertionError('Save preview must not read the registry')
    def write_value(self,*args): pass
    def write_default_string(self,*args): return 0


def registry_operation(args,values,display):
    from .toolkit_preferences_store import ToolkitPreferencesStore
    if args.action=='registry-save' and args.dry_run:
        planned=ToolkitPreferencesStore(_PlannedRegistry()).save(values,display)
        if not planned.complete: raise RuntimeError('Could not construct the preference save preview')
        operations=[{k:v for k,v in operation.items() if k not in ('completed','return_code','write_succeeded')}
                    for operation in planned.operations]
        return {'format':'cbus-toolkit-preferences-registry-plan-v1','dry_run':True,
            'registry_accessed':False,'writes_applied':False,'operations':operations,
            'assumptions':['Machine-hive writes succeed; FeedbackLogSize falls back to HKCU after an OS write error'],
            'transactional':False,'runtime_effects_applied':False},0
    store=ToolkitPreferencesStore(registry_backend(), numeric_locale=_locale(args))
    args._preferences_store=store
    outcome=store.load(values) if args.action=='registry-load' else store.save(values,display)
    result=outcome.as_dict()
    result['registry_accessed']=True
    result['backend']='windows-32bit-view'
    result['state']={'format':STATE_FORMAT,'values':dict(outcome.values),'display_values':dict(outcome.display_values)}
    return result,0 if outcome.complete else 1


def _attached_evidence(error,name):
    # Evidence is optional; a hostile getter must not replace the first error.
    try:
        evidence=getattr(error,name,None)
        return evidence if isinstance(evidence,dict) else None
    except BaseException:
        return None


def error_payload(error,args):
    if getattr(args,'area',None)!='preferences': return {}
    if getattr(args,'action',None)=='reset-dont-ask-again':
        evidence=_attached_evidence(error,'toolkit_preferences_reset_evidence')
        reset=getattr(args,'_preferences_reset',None)
        if not isinstance(evidence,dict) and reset is not None and reset.last_error is error:
            evidence=reset.last_evidence
        return {'toolkit_preferences_reset_evidence':evidence} if isinstance(evidence,dict) else {}
    evidence=_attached_evidence(error,'toolkit_preferences_evidence')
    if not isinstance(evidence,dict):
        store=getattr(args,'_preferences_store',None)
        if store is not None and store.last_error is error: evidence=store.last_evidence
    return {'toolkit_preferences_evidence':evidence} if isinstance(evidence,dict) else {}


def reset_registry_backend():
    from .windows_preferences_reset import WindowsDontAskAgainRegistry
    return WindowsDontAskAgainRegistry()


def reset_operation(args):
    from .toolkit_preferences_reset import HKCU,DONT_ASK_AGAIN_KEY,ToolkitDontAskAgainReset
    limits={name:getattr(args,name) for name in ('max_keys','max_depth','max_name_units')}
    # Reject malformed bounds before constructing a Windows backend.
    for name,value in limits.items():
        if type(value) is not int or not 1<=value<=1000000:
            raise ValueError(f'{name} must be an integer from 1 to 1000000')
    if args.dry_run:
        return {'operation':'reset-dont-ask-again','dry_run':True,'hive':HKCU,
            'key':DONT_ASK_AGAIN_KEY,'recursive':True,'limits':limits,
            'registry_accessed':False,'writes_applied':False,'transactional':False},0
    reset=ToolkitDontAskAgainReset(reset_registry_backend(),**limits)
    args._preferences_reset=reset
    outcome=reset.run()
    result=outcome.as_dict()
    result.update(registry_accessed=True,backend='windows-32bit-view')
    return result,0 if outcome.complete else 1
