"""Pin historical CLI bytes; prove scoped project source carry-forward only.

Historical execution is not current native acceptance. Other receipt source
bindings stay strictly current; this archive changes no historical receipt.
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
