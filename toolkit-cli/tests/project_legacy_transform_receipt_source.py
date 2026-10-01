"""Pin historical CLI/native bytes; prove scoped project source carry-forward.

Historical execution is not current native acceptance. The original CLI and
NativeProjects dependency closure are compared by strict AST; every other
receipt source binding stays strictly current. Archives change no old receipt.
"""
from __future__ import annotations
import ast
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'research/fixtures/project-legacy-transform-historical-cli-d217b0d2.zip'
ARCHIVE_SHA256 = '69938493f146f6edf1fbfcc416bbc31d9198a88aaa47692d38a60d66936bbb51'
CLI_SHA256 = '4557eeba0294b373d13d3ecab27470192084ed664e2fddfcd4cdb295ed495f67'
COMMIT = 'd217b0d29dc01392f5a14e3770fe438b3abe3439'
MEMBER = 'src/cbus_toolkit/cli.py'


def historical_cli() -> bytes:
    assert sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_SHA256
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.namelist() == [MEMBER]
        source = archive.read(MEMBER)
    assert sha256(source).hexdigest() == CLI_SHA256
    return source


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _one(nodes):
    assert len(nodes) == 1, 'Scoped project source must have exactly one match'
    return _dump(nodes[0])


def project_source_contract(source: bytes) -> dict[str, str]:
    tree = ast.parse(source)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    result = {}
    for name, condition in (('_project', 'args.action == "transform-legacy"'),
                            ('_cgate', 'args.action == "project"'),
                            ('run', 'args.area == "project"'),
                            ('run', 'args.area == "cgate"')):
        test = _dump(ast.parse(condition, mode='eval').body)
        result[name + ':' + condition] = _one([n for n in ast.walk(functions[name])
                                             if isinstance(n, ast.If) and _dump(n.test) == test
                                             and (name != 'run' or len(n.body) == 1
                                                  and isinstance(n.body[0], ast.Return))])
    parser = functions['build_parser']
    result['native-project-arguments'] = _one([
        n for n in ast.walk(parser) if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)
        and any(isinstance(v, ast.Constant) and v.value == 'transform' for v in n.iter.elts)])
    result['portable-registration-import'] = _one([
        n for n in ast.walk(parser) if isinstance(n, ast.ImportFrom)
        and n.module == 'project_legacy_transform_cli'])
    result['portable-registration-call'] = _one([
        n for n in ast.walk(parser) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id == 'project_legacy_transform_options'])
    for variable in ('projects', 'prop'):
        result['native-parser-' + variable] = _one([
            n for n in ast.walk(parser) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == variable for t in n.targets)])
    return result


def assert_current_project_carry_forward() -> None:
    historical = project_source_contract(historical_cli())
    assert len(historical) == 9
    assert project_source_contract((ROOT / MEMBER).read_bytes()) == historical


NATIVE_ARCHIVE = ROOT / 'research/fixtures/project-legacy-transform-historical-native-d217b0d2.zip'
NATIVE_ARCHIVE_SHA256 = 'bf3d03465dd59196b3f518693e640b5bf6d33619dc38e65d56bc0705852eeb80'
NATIVE_SHA256 = 'e72a5f5569c35b2de2e9802fa6e458343208216561632ea7a5aa3334aefcb36a'
NATIVE_MEMBER = 'src/cbus_toolkit/native.py'


def historical_native() -> bytes:
    assert sha256(NATIVE_ARCHIVE.read_bytes()).hexdigest() == NATIVE_ARCHIVE_SHA256
    with zipfile.ZipFile(NATIVE_ARCHIVE) as archive:
        assert archive.namelist() == [NATIVE_MEMBER]
        source = archive.read(NATIVE_MEMBER)
    assert sha256(source).hexdigest() == NATIVE_SHA256
    return source


def native_source_contract(source: bytes) -> dict[str, str]:
    """Bind complete NativeProjects and its module dependency closure.

    Include every referenced module helper/import/constant recursively, so an
    unchanged operation method cannot hide changed token/project validation.
    Builtins and method-local names remain bound by the complete node AST.
    """
    tree = ast.parse(source)
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            definitions.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    definitions.setdefault(target.id, []).append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                definitions.setdefault(alias.asname or alias.name.split('.')[0], []).append(node)
    assert 'NativeProjects' in definitions
    pending = ['NativeProjects']
    included = {}
    while pending:
        name = pending.pop()
        if name in included:
            continue
        assert len(definitions[name]) == 1, 'Scoped dependency has duplicate definitions: ' + name
        node = definitions[name][0]
        included[name] = _dump(node)
        pending.extend(n.id for n in ast.walk(node)
                       if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                       and n.id in definitions and n.id not in included)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            included['__future__'] = _dump(node)
    assert set(included) == {'NativeProjects', '_command', '_project', '_token', 're', '__future__'}, 'NativeProjects dependency boundary changed'
    side_effects = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            # Module-level execution can dynamically monkeypatch the scoped
            # route even when its source contains no direct dependency name.
            side_effects.append(_dump(node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if names & set(included):
                side_effects.append(_dump(node))
    included['module-scoped-side-effects'] = repr(side_effects)
    return included


def assert_current_native_carry_forward() -> None:
    assert native_source_contract((ROOT / NATIVE_MEMBER).read_bytes()) == native_source_contract(historical_native())
