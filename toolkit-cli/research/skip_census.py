#!/usr/bin/env python3
"""Statically classify every Toolkit test module's skip gates by provisioning.

Each ``unittest``/pytest skip site (decorators, ``pytestmark``, and
``skipTest``/``SkipTest``/``pytest.skip`` calls with their enclosing ``if``
conditions) is parsed without importing the test module.  Its condition is
evaluated by a small three-valued interpreter under the native release-gate
profile: an owned JDK, the original C-Gate application directory, decoded unit
specifications, ``CBUS_NATIVE_SERVICE_BACKEND=local`` and the loopback
``CBUS_CGATE_TEST_HOST`` that ``tests/conftest.py`` publishes for its owned
LocalCGate, plus the built cmqttd binary (``CBUS_CMQTTD_BIN``) that the
native/cmqttd project archive interchange needs.  Nothing else (original
Toolkit, Windows, hardware, vendor firmware, other Rust binaries or private
evidence inputs) is provisioned.

The committed census records every gated site and why each test node is or is
not runnable under that profile.  ``--check`` also fails when a node that the
profile can run is missing from ``research/release-gates/native.json``, or
when that selection covers a node the profile would skip.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
CENSUS_PATH = ROOT / "research" / "release-gates" / "skip-census.json"
NATIVE_MANIFEST = ROOT / "research" / "release-gates" / "native.json"
FORMAT = "cbus-test-skip-census-v1"
ENV_NAME = re.compile(r"CBUS_[A-Z0-9_]+")
PROVIDED = "<provisioned>"

# Values present in the native gate.  The loopback host, port, simulator
# routing and catalogue are published by tests/conftest.py for the owned
# LocalCGate; they are never an externally supplied endpoint.
NATIVE_ENVIRONMENT = {
    "CBUS_CGATE_JAVA": PROVIDED,
    "CBUS_CGATE_JAVAC": PROVIDED,
    "CBUS_LOCAL_CGATE_VENDOR": PROVIDED,
    "CBUS_UNITSPEC_DIR": PROVIDED,
    "CBUS_NATIVE_SERVICE_BACKEND": "local",
    "CBUS_NATIVE_TLS_TEST": "1",
    "CBUS_SCENE_NATIVE": "1",
    "CBUS_CGATE_TEST_HOST": "127.0.0.1",
    "CBUS_CGATE_TEST_PORT": PROVIDED,
    "CBUS_CGATE_SIMULATOR_HOST": "127.0.0.1",
    "CBUS_CGATE_SIMULATOR_BIND": "127.0.0.1",
    "CBUS_CATALOG_PATH": PROVIDED,
}
PLATFORM = {"sys.platform": "darwin", "os.name": "posix", "platform.system": "Darwin"}
HOST_TOOLS = {"openssl", "lsof", "sqlite3"}
INSTALLED_EXTRAS = {"serial", "usb", "cryptography", "pefile", "unicorn"}

CATEGORIES = {
    "native_cgate_local": "owned original C-Gate 3.4.0.2001 process (JDK, C-Gate application directory, local backend)",
    "cgate_test_host": "C-Gate test host; in the native gate this is the owned loopback LocalCGate from tests/conftest.py",
    "unit_specs": "decoded vendor unit specifications or the matching C-Gate unit catalogue",
    "native_opt_in": "explicit opt-in flag for an owned native TLS or scene oracle",
    "external_cgate_project": "separately provisioned C-Gate host or pre-existing project outside the owned service",
    "original_toolkit": "original Toolkit executable, DLLs, help or dialog maps",
    "original_model_runtime": "Mono or Windows runtime for original .NET model probes",
    "windows": "Windows host or Windows bridge/provenance",
    "private_vendor_tree": "private vendor/decompiled tree at a fixed checkout or volume path",
    "private_evidence_input": "private evidence, case list, backup or captured-output input",
    "vendor_firmware": "vendor firmware updater, DFU DLL or firmware oracle backend",
    "hardware": "physical C-Bus hardware acceptance",
    "rust_binaries": "built Rust cgate-mock, cmqttd or simulator binary (interop gates)",
    "installed_wheel": "installed Toolkit wheel artifact",
    "host_platform": "operating-system family check satisfied by the macOS native runner",
    "host_tool": "host tool or optional Python extra",
    "runtime_capability": "runtime condition observed only while the test runs",
    "unclassified": "condition the static interpreter cannot attribute",
}
NATIVE_CATEGORIES = {"native_cgate_local", "cgate_test_host", "unit_specs", "native_opt_in"}

ENV_CATEGORIES = [
    (re.compile(r"CBUS_(CGATE_TEST_HOST|CGATE_TEST_PORT|CGATE_SIMULATOR_HOST|CGATE_SIMULATOR_BIND)$"), "cgate_test_host"),
    (re.compile(r"CBUS_(LOCAL_CGATE_VENDOR|CGATE_JAVAC?|NATIVE_SERVICE_BACKEND)$"), "native_cgate_local"),
    (re.compile(r"CBUS_(UNITSPEC_DIR|CATALOG_PATH|UNIT_CATALOG)$"), "unit_specs"),
    (re.compile(r"CBUS_(NATIVE_TLS_TEST|SCENE_NATIVE|SCENE_PORT)$"), "native_opt_in"),
    (re.compile(r"CBUS_TEMPLATE_TRANSACTION_TEST_(HOST|PORT)$"), "external_cgate_project"),
    (re.compile(r"CBUS_TOOLKIT_(EXE|HELP_DIR|MAP)$"), "original_toolkit"),
    (re.compile(r"CBUS_(MONO_MACOS_ROOT|ORIGINAL_MODEL_BACKEND|EDLT_LIFECYCLE_ORIGINAL_BACKEND)$"), "original_model_runtime"),
    (re.compile(r"CBUS_WINDOWS_"), "windows"),
    (re.compile(r"CBUS_(HARDWARE_ACCEPTANCE|CNI_ENDPOINT)$"), "hardware"),
    (re.compile(r"CBUS_(DFU_DLL|FIRMWARE_UPDATER|FIRMWARE_ORACLE_BACKEND)$"), "vendor_firmware"),
    (re.compile(r"CBUS_(CGATE_MOCK_BIN|CMQTTD_BIN|SIMULATOR_BIN)$"), "rust_binaries"),
    (re.compile(r"CBUS_TOOLKIT_WHEEL$"), "installed_wheel"),
    (re.compile(r"CBUS_EDLT_.*_METADATA_|_ACCEPTANCE$|_CASES$|_EVIDENCE$|_OUTPUT$|_PROFILES$"),
     "private_evidence_input"),
]
REPORT_ONLY = re.compile(r"_REPORT(_DIR)?$")

# Nodes the profile can run that are deliberately not in the native gate.
# Each needs a precise reason; product failures stay visible here.
NATIVE_EXCLUSIONS: dict[str, str] = {
}

# Review notes for modules the native profile deliberately does not provision.
_PRE_PROVISIONED = ("Operates on an explicitly named, pre-provisioned eDLT unit in an existing project on the "
                    "C-Gate host plus a named backup project; the owned LocalCGate starts with no projects.")
NOT_NATIVE_NOTES: dict[str, str] = {
    "tests/test_template_transaction_native.py": (
        "Its separate CBUS_TEMPLATE_TRANSACTION_TEST_HOST gate targets a C-Gate-compatible service, not "
        "the original server. A 2026-09-30 trial against the owned native C-Gate 3.4.0.2001 failed with "
        "'425 Lock failed' and '408 Unable to delete file', so tests/conftest.py does not publish it."),
    "tests/test_edlt_parent_metadata.py": _PRE_PROVISIONED,
    "tests/test_edlt_parent_scene_metadata.py": _PRE_PROVISIONED,
    "tests/test_edlt_parent_auto_cache.py": _PRE_PROVISIONED,
    "tests/test_edlt_scene_metadata.py": _PRE_PROVISIONED,
}

# Static conditions the interpreter reports as unknown, resolved by review.
# Keys are a test node, a class/function scope or a module path.
_RUST_BINARIES = ("skips", "Rust binaries are provisioned by make check-interop, not by the native gate")
UNKNOWN_RESOLUTIONS: dict[str, tuple[str, str]] = {
    "tests/test_hardware_fixture_matrix.py::CommittedMatrixTests::"
    "test_committed_matrix_regenerates_from_private_inputs": (
        "runs", "build_hardware_fixture_matrix.default_inputs() reads CBUS_UNITSPEC_DIR and the "
                "catalogue under CBUS_LOCAL_CGATE_VENDOR"),
    "tests/test_edlt_dltp_index.py::DltpIndexTests::test_pinned_vendor_index_fact": (
        "skips", "requires a private original Toolkit installation"),
    "tests/test_cgate_dbgetxml_framing_interop.py": _RUST_BINARIES,
    "tests/test_cmqtt_interop.py": _RUST_BINARIES,
    "tests/test_cmqtt_programming_methods_interop.py": _RUST_BINARIES,
    "tests/test_cmqtt_dali_commissioning_interop.py": _RUST_BINARIES,
    "tests/test_rust_cgate_interop.py": _RUST_BINARIES,
    "tests/test_toolkit_database_csv_project_interop.py": _RUST_BINARIES,
    "tests/test_conversion_pairs_native.py::RustConversionPairTests": _RUST_BINARIES,
    "tests/test_native_pp_method_transcripts.py::test_cmqttd_replay_matches_committed_transcript": (
        "runs", "the native gate provisions the cmqttd binary as CBUS_CMQTTD_BIN; the replay also needs "
                "the native catalogue and decoded unit specifications that gate provides"),
    "tests/test_native_cgate_project_interchange.py": (
        "runs", "the native gate provisions the cmqttd binary as CBUS_CMQTTD_BIN for this cross-server "
                "PROJECT ARCHIVE/RESTORE interchange; other Rust interop stays with make check-interop"),
}


class _Unknown:
    def __repr__(self):
        return "UNKNOWN"


UNKNOWN = _Unknown()


@dataclass(frozen=True)
class PathValue:
    """A filesystem path whose existence is decided by provisioning."""
    exists: bool | None


def _truth(value):
    if value is UNKNOWN:
        return None
    if isinstance(value, PathValue):
        return True
    return bool(value)


def env_category(name: str) -> str | None:
    if REPORT_ONLY.search(name):
        return None
    for pattern, category in ENV_CATEGORIES:
        if pattern.search(name):
            return category
    return "unclassified"


class Interpreter:
    """Three-valued evaluation of a skip condition under one profile."""

    def __init__(self, module: "ModuleInfo", environment: dict[str, str]):
        self.module = module
        self.environment = environment

    def evaluate(self, node, local=None, depth=0):
        try:
            return self._evaluate(node, local or {}, depth)
        except RecursionError:
            return UNKNOWN

    def _env(self, node, local, depth):
        key = self._evaluate(node, local, depth)
        return self.environment.get(key) if isinstance(key, str) else UNKNOWN

    def _call_name(self, node):
        try:
            return ast.unparse(node.func)
        except Exception:  # pragma: no cover - defensive
            return ""

    def _evaluate(self, node, local, depth):
        if depth > 40:
            return UNKNOWN
        ev = lambda child, scope=local: self._evaluate(child, scope, depth + 1)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Tuple, ast.List)):
            values = tuple(ev(item) for item in node.elts)
            return UNKNOWN if any(value is UNKNOWN for value in values) else values
        if isinstance(node, ast.Name):
            if node.id in local:
                return ev(local[node.id], {})
            if node.id in self.module.bindings:
                return ev(self.module.bindings[node.id], {})
            if node.id == "__file__":
                return PathValue(True)
            if node.id in self.module.imported:
                other, name = self.module.imported[node.id]
                return Interpreter(other, self.environment)._evaluate(ast.Name(name, ast.Load()), {}, depth + 1)
            return UNKNOWN
        if isinstance(node, ast.Attribute):
            dotted = ast.unparse(node)
            if dotted in PLATFORM:
                return PLATFORM[dotted]
            if isinstance(node.value, ast.Name) and node.value.id in self.module.aliases:
                other = self.module.aliases[node.value.id]
                return Interpreter(other, self.environment)._evaluate(ast.Name(node.attr, ast.Load()), {}, depth + 1)
            if dotted.startswith("ssl.HAS_"):
                return True
            base = ev(node.value)
            if isinstance(base, PathValue) and node.attr in ("parent", "parents"):
                return base
            return UNKNOWN
        if isinstance(node, ast.Subscript):
            if ast.unparse(node.value) == "os.environ":
                return self._env(node.slice, local, depth + 1)
            base = ev(node.value)
            return base if isinstance(base, PathValue) else UNKNOWN
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = ev(node.left)
            if isinstance(left, PathValue):
                right = node.right
                if isinstance(right, ast.Constant) and isinstance(right.value, str) and _private_path(right.value):
                    return PathValue(False)
                return left
            return UNKNOWN
        if isinstance(node, ast.BoolOp):
            values = [ev(value) for value in node.values]
            truths = [_truth(value) for value in values]
            if isinstance(node.op, ast.And):
                for value, truth in zip(values, truths):
                    if truth is False:
                        return value
                return UNKNOWN if None in truths else values[-1]
            for value, truth in zip(values, truths):
                if truth is True:
                    return value
            return UNKNOWN if None in truths else values[-1]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            truth = _truth(ev(node.operand))
            return UNKNOWN if truth is None else not truth
        if isinstance(node, ast.IfExp):
            truth = _truth(ev(node.test))
            if truth is None:
                return UNKNOWN
            return ev(node.body if truth else node.orelse)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = ev(comparator)
                if left is UNKNOWN or right is UNKNOWN or isinstance(left, PathValue) or isinstance(right, PathValue):
                    return UNKNOWN
                try:
                    if isinstance(operator, ast.Eq):
                        result = left == right
                    elif isinstance(operator, ast.NotEq):
                        result = left != right
                    elif isinstance(operator, ast.In):
                        result = left in right
                    elif isinstance(operator, ast.NotIn):
                        result = left not in right
                    elif isinstance(operator, ast.Is):
                        result = left is right
                    elif isinstance(operator, ast.IsNot):
                        result = left is not right
                    else:
                        return UNKNOWN
                except TypeError:
                    return UNKNOWN
                if not result:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            return self._evaluate_call(node, local, depth)
        return UNKNOWN

    def _evaluate_call(self, node, local, depth):
        ev = lambda child, scope=local: self._evaluate(child, scope, depth + 1)
        name = self._call_name(node)
        args = node.args
        if name in ("os.environ.get", "os.getenv", "environ.get"):
            if not args:
                return UNKNOWN
            value = self._env(args[0], local, depth + 1)
            if value is None and len(args) > 1:
                return ev(args[1])
            return value
        if name == "platform.system":
            return PLATFORM["platform.system"]
        if name in ("Path", "pathlib.Path", "Path.home"):
            if not args:
                return PathValue(None)
            value = ev(args[0])
            if isinstance(value, PathValue):
                return value
            if value == PROVIDED:
                return PathValue(True)
            if value is None or value == "":
                return PathValue(False)
            if isinstance(value, str):
                return PathValue(False if _private_path(value) else None)
            return UNKNOWN
        if name == "bool" and len(args) == 1:
            truth = _truth(ev(args[0]))
            return UNKNOWN if truth is None else truth
        if name in ("all", "any") and len(args) == 1:
            return self._all_any(name, args[0], local, depth)
        if name == "shutil.which" and args:
            tool = ev(args[0])
            return True if tool in HOST_TOOLS else UNKNOWN
        if name in ("importlib.util.find_spec", "util.find_spec") and args:
            module = ev(args[0])
            return True if module in INSTALLED_EXTRAS else UNKNOWN
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            base = ev(node.func.value)
            if isinstance(base, PathValue):
                if method in ("exists", "is_file", "is_dir"):
                    return UNKNOWN if base.exists is None else base.exists
                if method in ("resolve", "expanduser", "absolute", "joinpath", "with_name"):
                    return base
            return UNKNOWN
        if name == "hasattr" and len(args) == 2 and ast.unparse(args[0]) == "os":
            return True  # the native runner is POSIX
        if isinstance(node.func, ast.Name) and node.func.id in self.module.functions:
            return self._evaluate_function(self.module.functions[node.func.id], depth)
        if isinstance(node.func, ast.Name) and node.func.id in self.module.imported:
            other, function = self.module.imported[node.func.id]
            if function in other.functions:
                return Interpreter(other, self.environment)._evaluate_function(other.functions[function], depth + 1)
        return UNKNOWN

    def _all_any(self, name, argument, local, depth):
        if isinstance(argument, (ast.GeneratorExp, ast.ListComp)) and len(argument.generators) == 1:
            generator = argument.generators[0]
            iterable = self._evaluate(generator.iter, local, depth + 1)
            if not isinstance(iterable, tuple) or not isinstance(generator.target, ast.Name) or generator.ifs:
                return UNKNOWN
            truths = [_truth(self._evaluate(argument.elt, {**local, generator.target.id: ast.Constant(item)},
                                            depth + 1)) for item in iterable]
        else:
            iterable = self._evaluate(argument, local, depth + 1)
            if not isinstance(iterable, tuple):
                return UNKNOWN
            truths = [_truth(item) for item in iterable]
        if name == "all":
            return False if False in truths else (UNKNOWN if None in truths else True)
        return True if True in truths else (UNKNOWN if None in truths else False)

    def _evaluate_function(self, function: ast.FunctionDef, depth):
        """Evaluate a module-level predicate made of assignments, ifs and returns."""
        if function.args.args or function.args.vararg or function.args.kwarg:
            return UNKNOWN
        local: dict[str, ast.AST] = {}

        def run(statements):
            for statement in statements:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                    continue
                if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                        and isinstance(statement.targets[0], ast.Name):
                    local[statement.targets[0].id] = statement.value
                    continue
                if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                        and isinstance(statement.targets[0], ast.Tuple) and isinstance(statement.value, ast.Tuple) \
                        and len(statement.targets[0].elts) == len(statement.value.elts) \
                        and all(isinstance(item, ast.Name) for item in statement.targets[0].elts):
                    for target, value in zip(statement.targets[0].elts, statement.value.elts):
                        local[target.id] = value
                    continue
                if isinstance(statement, ast.Return):
                    return ("return", UNKNOWN if statement.value is None and False else
                            (None if statement.value is None else
                             self._evaluate(statement.value, dict(local), depth + 1)))
                if isinstance(statement, ast.If):
                    truth = _truth(self._evaluate(statement.test, dict(local), depth + 1))
                    if truth is None:
                        return ("return", UNKNOWN)
                    result = run(statement.body if truth else statement.orelse)
                    if result is not None:
                        return result
                    continue
                return ("return", UNKNOWN)
            return None

        result = run(function.body)
        return None if result is None else result[1]


def _private_path(text: str) -> bool:
    """Private trees and absolute paths are never part of a gate checkout."""
    lowered = text.replace("\\", "/").lower()
    return "vendor" in lowered or "research/runtime" in lowered or lowered.startswith("/")


@dataclass
class Site:
    scope: str
    kind: str
    condition: ast.AST | None
    skip_when_true: bool
    reason: str
    local: dict = field(default_factory=dict)
    # Environment names read by the enclosing body, for in-body skip calls.
    context: tuple[str, ...] = ()


@dataclass
class ModuleInfo:
    path: str
    tree: ast.Module
    bindings: dict[str, ast.AST] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    imported: dict[str, tuple["ModuleInfo", str]] = field(default_factory=dict)
    aliases: dict[str, "ModuleInfo"] = field(default_factory=dict)


_MODULES: dict[str, ModuleInfo] = {}


def _test_module(name: str) -> ModuleInfo | None:
    """Bindings of another test module imported by name (no execution)."""
    stem = name.removeprefix("tests.")
    path = TESTS / (stem + ".py")
    if not stem.startswith("test_") or "." in stem or not path.is_file():
        return None
    relative = path.relative_to(ROOT).as_posix()
    if relative not in _MODULES:
        module = ModuleInfo(relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative))
        _MODULES[relative] = module
        _bind(module)
    return _MODULES[relative]


def _bind(module: ModuleInfo) -> None:
    for statement in module.tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    module.bindings[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
            module.bindings[statement.target.id] = statement.value
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions[statement.name] = statement
        elif isinstance(statement, ast.ImportFrom) and statement.module and statement.level == 0:
            other = _test_module(statement.module)
            if other is not None:
                for alias in statement.names:
                    module.imported[alias.asname or alias.name] = (other, alias.name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                other = _test_module(alias.name)
                if other is not None and alias.asname:
                    module.aliases[alias.asname] = other


SKIP_DECORATORS = {
    "unittest.skipUnless": False, "skipUnless": False,
    "unittest.skipIf": True, "skipIf": True,
    "pytest.mark.skipif": True, "mark.skipif": True,
}
ALWAYS_SKIP_DECORATORS = {"unittest.skip", "skip", "pytest.mark.skip", "mark.skip"}
SKIP_CALLS = {"self.skipTest", "cls.skipTest", "pytest.skip", "unittest.SkipTest", "SkipTest",
              "unittest.case.SkipTest", "pytest.importorskip"}


def _reason(call: ast.Call, index: int) -> str:
    candidates = list(call.args[index:index + 1]) + [kw.value for kw in call.keywords if kw.arg in ("reason", "msg")]
    for candidate in candidates:
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
        if isinstance(candidate, ast.JoinedStr):
            return "".join(part.value for part in candidate.values
                           if isinstance(part, ast.Constant) and isinstance(part.value, str))
        if isinstance(candidate, ast.BinOp):
            return "".join(item.value for item in ast.walk(candidate)
                           if isinstance(item, ast.Constant) and isinstance(item.value, str))
    return ""


def _decorator_sites(decorators, scope) -> list[Site]:
    sites = []
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            if ast.unparse(decorator) in ALWAYS_SKIP_DECORATORS:
                sites.append(Site(scope, "decorator.skip", None, True, ""))
            continue
        name = ast.unparse(decorator.func)
        if name in SKIP_DECORATORS and decorator.args:
            sites.append(Site(scope, "decorator." + name.rsplit(".", 1)[-1], decorator.args[0],
                              SKIP_DECORATORS[name], _reason(decorator, 1)))
        elif name in ALWAYS_SKIP_DECORATORS:
            sites.append(Site(scope, "decorator.skip", None, True, _reason(decorator, 0)))
    return sites


def _pytestmark_sites(value, scope) -> list[Site]:
    items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
    return _decorator_sites(items, scope)


class _BodySkips(ast.NodeVisitor):
    """Collect skip calls in one function body with their guarding conditions."""

    def __init__(self, scope: str, kind: str, context: tuple[str, ...]):
        self.scope = scope
        self.kind = kind
        self.context = context
        self.guards: list[tuple[ast.AST, bool]] = []
        self.in_handler = 0
        self.local: dict[str, ast.AST] = {}
        self.sites: list[Site] = []

    def visit_FunctionDef(self, node):  # nested functions are not the body
        if self.guards or self.local or self.sites or getattr(self, "_entered", False):
            return
        self._entered = True
        for statement in node.body:
            self.visit(statement)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            self.local[node.targets[0].id] = node.value
        self.generic_visit(node)

    def visit_If(self, node):
        self.visit(node.test)
        self.guards.append((node.test, True))
        for statement in node.body:
            self.visit(statement)
        self.guards[-1] = (node.test, False)
        for statement in node.orelse:
            self.visit(statement)
        self.guards.pop()

    def visit_ExceptHandler(self, node):
        self.in_handler += 1
        self.generic_visit(node)
        self.in_handler -= 1

    def visit_Call(self, node):
        name = ast.unparse(node.func)
        if name in SKIP_CALLS:
            self._record(node, name)
        self.generic_visit(node)

    def _record(self, node, name):
        if self.in_handler:
            self.sites.append(Site(self.scope, self.kind + ".runtime", None, True, _reason(node, 0),
                                   context=self.context))
            return
        if name == "pytest.importorskip":
            self.sites.append(Site(self.scope, self.kind + ".importorskip", node.args[0] if node.args else None,
                                   False, ""))
            return
        condition = None
        for test, positive in self.guards:
            term = test if positive else ast.UnaryOp(op=ast.Not(), operand=test)
            condition = term if condition is None else ast.BoolOp(op=ast.And(), values=[condition, term])
        self.sites.append(Site(self.scope, self.kind + ".call", condition, True, _reason(node, 0),
                               dict(self.local), self.context))


def _env_names(node) -> tuple[str, ...]:
    return tuple(sorted({name for child in ast.walk(node)
                         if isinstance(child, ast.Constant) and isinstance(child.value, str)
                         for name in ENV_NAME.findall(child.value)}))


def _body_sites(function, scope, kind, context=None) -> list[Site]:
    visitor = _BodySkips(scope, kind, _env_names(function) if context is None else context)
    visitor.visit(function)
    return visitor.sites


def _is_test_class(node: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> bool:
    if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")
           for item in node.body):
        return True
    return any(isinstance(base, ast.Name) and base.id in classes and _is_test_class(classes[base.id], classes)
               for base in node.bases)


def analyse_module(path: Path) -> tuple[ModuleInfo, dict[str, list[Site]], list[str]]:
    relative = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    module = ModuleInfo(relative, tree)
    _MODULES[relative] = module
    _bind(module)
    classes: dict[str, ast.ClassDef] = {}
    module_sites: list[Site] = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    module_sites.extend(_pytestmark_sites(statement.value, relative))
        elif isinstance(statement, ast.ClassDef):
            classes[statement.name] = statement
        elif isinstance(statement, ast.If):
            module_sites.extend(site for site in _body_sites(
                ast.FunctionDef(name="<module>", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                                kw_defaults=[], defaults=[]), body=[statement], decorator_list=[]),
                relative, "module") if "module-level" in site.reason or site.kind.endswith(".call"))
    nodes: dict[str, list[Site]] = {}
    helper_sites = []
    for name, function in module.functions.items():
        if name == "setUpModule":
            module_sites.extend(_body_sites(function, relative, "setUpModule"))
        elif not name.startswith("test"):
            helper_sites.extend(_body_sites(function, relative, "helper." + name))
    for name, function in module.functions.items():
        if name.startswith("test"):
            node = f"{relative}::{name}"
            nodes[node] = (module_sites + _decorator_sites(function.decorator_list, node)
                           + _body_sites(function, node, "body") + helper_sites)

    def class_sites(cls: ast.ClassDef, scope: str, seen=()) -> list[Site]:
        sites = []
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id in classes and base.id not in seen:
                sites.extend(class_sites(classes[base.id], scope, (*seen, cls.name)))
        sites.extend(_decorator_sites(cls.decorator_list, scope))
        for item in cls.body:
            if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                                                    for t in item.targets):
                sites.extend(_pytestmark_sites(item.value, scope))
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("test"):
                kind = item.name if item.name in ("setUp", "setUpClass", "asyncSetUp") else "helper." + item.name
                sites.extend(_body_sites(item, scope, kind, _env_names(cls)))
        return sites

    def methods(cls: ast.ClassDef, seen=()) -> dict[str, ast.FunctionDef]:
        found = {}
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id in classes and base.id not in seen:
                found.update(methods(classes[base.id], (*seen, cls.name)))
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                found[item.name] = item
        return found

    for name, cls in classes.items():
        if not _is_test_class(cls, classes):
            continue
        scope = f"{relative}::{name}"
        shared = module_sites + helper_sites + class_sites(cls, scope)
        for method_name, method in methods(cls).items():
            node = f"{scope}::{method_name}"
            nodes[node] = shared + _decorator_sites(method.decorator_list, node) + _body_sites(method, node, "body")
    return module, nodes, sorted(classes)


def _references(module: ModuleInfo, site: Site) -> tuple[set[str], set[str]]:
    """Return environment names and categories that a site's condition reaches."""
    names: set[str] = set(ENV_NAME.findall(site.reason)) | set(site.context)
    categories: set[str] = set()
    pending = [(module, site.condition)] if site.condition is not None else []
    pending.extend((module, value) for value in site.local.values())
    seen: set[int] = set()
    while pending:
        owner, node = pending.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                names.update(ENV_NAME.findall(child.value))
                if _private_path(child.value) and "/" in child.value:
                    categories.add("private_vendor_tree")
                if "CBusToolkit" in child.value:
                    categories.add("original_toolkit")
                if child.value in ("nt", "win32"):
                    categories.add("windows")
            elif isinstance(child, ast.Name):
                if child.id in owner.bindings:
                    pending.append((owner, owner.bindings[child.id]))
                elif child.id in owner.functions:
                    pending.append((owner, owner.functions[child.id]))
                elif child.id in owner.imported:
                    other, name = owner.imported[child.id]
                    pending.append((other, other.bindings.get(name) or other.functions.get(name)))
            elif isinstance(child, ast.Attribute):
                dotted = ast.unparse(child)
                if dotted in ("os.name", "sys.platform"):
                    categories.add("host_platform")
                elif isinstance(child.value, ast.Name) and child.value.id in owner.aliases:
                    other = owner.aliases[child.value.id]
                    pending.append((other, other.bindings.get(child.attr) or other.functions.get(child.attr)))
            elif isinstance(child, ast.Call):
                call = ast.unparse(child.func)
                if call in ("shutil.which", "importlib.util.find_spec", "hasattr") or call.startswith("ssl."):
                    categories.add("host_tool")
                if call == "platform.system":
                    categories.add("host_platform")
    for name in names:
        category = env_category(name)
        if category:
            categories.add(category)
    if site.kind.endswith(".runtime"):
        categories.add("runtime_capability")
    if not categories:
        categories.add("unclassified")
    return {name for name in names if not REPORT_ONLY.search(name)}, categories


def _source(node) -> str:
    return "" if node is None else ast.unparse(node)


def _outcome(module: ModuleInfo, site: Site, environment: dict[str, str]) -> str:
    """Return skips, runs or unknown for one site."""
    if site.kind.endswith(".runtime"):
        return "runtime"
    if site.condition is None:
        return "skips" if site.skip_when_true else "runs"
    if site.kind.endswith(".importorskip"):
        value = Interpreter(module, environment).evaluate(site.condition, site.local)
        return "runs" if value in INSTALLED_EXTRAS else "unknown"
    truth = _truth(Interpreter(module, environment).evaluate(site.condition, site.local))
    if truth is None:
        return "unknown"
    return "skips" if truth == site.skip_when_true else "runs"


def _covered(node: str, selectors: list[str]) -> bool:
    return any(node == selector or node.startswith(selector + "::") for selector in selectors)


def build(selection: list[str]) -> tuple[dict, list[str], list[str]]:
    """Return the census, required native nodes, and coverage errors."""
    modules: dict[str, dict] = {}
    required: list[str] = []
    errors: list[str] = []
    all_nodes: list[str] = []
    ungated_modules = 0
    for path in sorted(TESTS.glob("test_*.py")):
        module, nodes, _ = analyse_module(path)
        all_nodes.extend(nodes)
        site_records: dict[tuple, dict] = {}
        node_status: dict[str, dict] = {}
        for node, sites in nodes.items():
            status = "ungated"
            blocking: set[str] = set()
            native_categories: set[str] = set()
            for site in sites:
                names, categories = _references(module, site)
                native = _outcome(module, site, NATIVE_ENVIRONMENT)
                offline = _outcome(module, site, {})
                key = (site.scope, site.kind, _source(site.condition), site.reason)
                record = site_records.setdefault(key, {
                    "scope": site.scope, "kind": site.kind,
                    "condition": _source(site.condition) or None,
                    "reason": site.reason or None,
                    "environment": sorted(names), "categories": sorted(categories),
                    "offline": offline, "native": native})
                if native == "unknown":
                    resolution = (UNKNOWN_RESOLUTIONS.get(node) or UNKNOWN_RESOLUTIONS.get(site.scope)
                                  or UNKNOWN_RESOLUTIONS.get(module.path))
                    if resolution:
                        native = resolution[0]
                        record["native"] = native
                        record["native_resolution"] = resolution[1]
                if native == "runtime":
                    continue
                if offline != "runs" or native != "runs":
                    native_categories |= categories & NATIVE_CATEGORIES
                if native in ("skips", "unknown"):
                    blocking |= categories - NATIVE_CATEGORIES or {"unclassified"}
                    status = "unknown" if native == "unknown" and status != "skips" else "skips"
                elif status == "ungated" and offline != "runs":
                    status = "runs"
            node_status[node] = {"status": status, "blocking": sorted(blocking),
                                 "native": bool(native_categories)}
        gated = {node: value for node, value in node_status.items() if value["status"] != "ungated"}
        if not site_records:
            ungated_modules += 1
            continue
        candidates = sorted(node for node, value in gated.items()
                            if value["status"] == "runs" and value["native"])
        excluded = {node: reason for node, reason in NATIVE_EXCLUSIONS.items()
                    if node in nodes or any(key.startswith(node + "::") for key in nodes)}
        module_required = [node for node in candidates if not any(
            node == key or node.startswith(key + "::") for key in excluded)]
        required.extend(module_required)
        skipped = {node: value["blocking"] for node, value in gated.items() if value["status"] != "runs"}
        categories = sorted({category for record in site_records.values() for category in record["categories"]})
        if not candidates:
            native = "none"
        elif len(candidates) == len(gated):
            native = "all"
        else:
            native = "partial"
        entry: dict[str, object] = {
            "categories": categories,
            "native": native,
            "gated_tests": len(gated),
            "native_runnable_tests": len(candidates),
            "native_selected_tests": sum(_covered(node, selection) for node in nodes),
            "sites": sorted(site_records.values(), key=lambda item: (item["scope"], item["kind"],
                                                                     item["condition"] or "",
                                                                     item["reason"] or "")),
        }
        if skipped:
            # Group the reasons a node cannot run in the native gate.
            reasons: dict[str, list[str]] = {}
            for node, blocking in sorted(skipped.items()):
                reasons.setdefault(", ".join(blocking), []).append(node.split("::", 1)[1])
            entry["not_native"] = [{"requires": key.split(", "), "tests": value}
                                   for key, value in sorted(reasons.items())]
        if excluded:
            entry["excluded_from_native_gate"] = excluded
        if module.path in NOT_NATIVE_NOTES:
            entry["note"] = NOT_NATIVE_NOTES[module.path]
        modules[module.path] = entry
    for node in required:
        if not _covered(node, selection):
            errors.append(f"native-runnable test is not selected by native.json: {node}")
    for selector in selection:
        covered = [node for node in all_nodes if _covered(node, [selector])]
        if not covered:
            errors.append(f"native.json selector matches no statically discovered test: {selector}")
    required_set = set(required)
    for node in all_nodes:
        if _covered(node, selection):
            module = node.split("::", 1)[0]
            entry = modules.get(module)
            if node in required_set:
                continue
            # Ungated nodes may run beside gated ones; anything else would skip or is excluded.
            if entry is not None and any(node in group["tests"] or node.split("::", 1)[1] in group["tests"]
                                         for group in entry.get("not_native", [])):
                errors.append(f"native.json selects a test the native profile skips: {node}")
            if any(node == key or node.startswith(key + "::")
                   for key in NATIVE_EXCLUSIONS):
                errors.append(f"native.json selects an excluded test: {node}")
    by_category: dict[str, int] = {}
    for entry in modules.values():
        for category in entry["categories"]:
            by_category[category] = by_category.get(category, 0) + 1
    census = {
        "format": FORMAT,
        "generator": "research/skip_census.py",
        "native_profile": {
            "provisioned_environment": sorted(NATIVE_ENVIRONMENT),
            "owned_test_host": "tests/conftest.py publishes CBUS_CGATE_TEST_HOST/PORT, loopback simulator "
                               "routing and CBUS_CATALOG_PATH for one owned LocalCGate",
            "platform": PLATFORM,
            "native_categories": sorted(NATIVE_CATEGORIES),
        },
        "categories": CATEGORIES,
        "summary": {
            "test_modules": len(list(TESTS.glob("test_*.py"))),
            "modules_without_skip_sites": ungated_modules,
            "modules_with_skip_sites": len(modules),
            "modules_by_category": dict(sorted(by_category.items())),
            "native_modules": {state: sum(entry["native"] == state for entry in modules.values())
                               for state in ("all", "partial", "none")},
            "native_runnable_tests": len(required) + sum(
                1 for node in all_nodes if any(node == key or node.startswith(key + "::") for key in NATIVE_EXCLUSIONS)),
            "native_selected_required_tests": sum(_covered(node, selection) for node in required),
            "native_excluded": len(NATIVE_EXCLUSIONS),
            "native_selection_selectors": len(selection),
        },
        "modules": modules,
    }
    return census, required, errors


def suggested_selection(required: list[str]) -> list[str]:
    """Collapse required test nodes to the widest selectors that skip nothing."""
    blocked: set[str] = set()
    all_nodes: dict[str, list[str]] = {}
    census, _, _ = build([])
    for module, entry in census["modules"].items():
        for group in entry.get("not_native", []):
            blocked.update(f"{module}::{test}" for test in group["tests"])
    for path in sorted(TESTS.glob("test_*.py")):
        _, nodes, _ = analyse_module(path)
        all_nodes[path.relative_to(ROOT).as_posix()] = list(nodes)
    excluded = set(NATIVE_EXCLUSIONS)
    required_set = set(required)
    selection: list[str] = []
    for module, nodes in sorted(all_nodes.items()):
        wanted = [node for node in nodes if node in required_set]
        if not wanted:
            continue
        unsafe = [node for node in nodes if node in blocked
                  or any(node == key or node.startswith(key + "::") for key in excluded)]
        if not unsafe:
            selection.append(module)
            continue
        classes: dict[str, list[str]] = {}
        for node in nodes:
            parts = node.split("::")
            if len(parts) == 3:
                classes.setdefault("::".join(parts[:2]), []).append(node)
        for node in wanted:
            parts = node.split("::")
            if len(parts) == 2:
                selection.append(node)
        for cls, members in classes.items():
            if not any(node in required_set for node in members):
                continue
            if any(node in unsafe for node in members):
                selection.extend(node for node in members if node in required_set)
            else:
                selection.append(cls)
    return selection


def render(census: dict) -> str:
    return json.dumps(census, indent=2, sort_keys=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail when the committed census is stale or native.json misses a runnable test")
    parser.add_argument("--write-selection", action="store_true",
                        help="rewrite native.json tests to cover every native-runnable test")
    args = parser.parse_args(argv)
    manifest = json.loads(NATIVE_MANIFEST.read_text())
    if args.write_selection:
        _, required, _ = build(manifest["tests"])
        manifest["tests"] = suggested_selection(required)
        NATIVE_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    census, _, errors = build(manifest["tests"])
    text = render(census)
    if args.check:
        if not CENSUS_PATH.is_file() or CENSUS_PATH.read_text() != text:
            errors.append(f"{CENSUS_PATH.relative_to(ROOT)} is stale; run research/skip_census.py")
    else:
        CENSUS_PATH.write_text(text)
    for error in errors:
        print(error, file=sys.stderr)
    summary = census["summary"]
    print(json.dumps({key: summary[key] for key in ("test_modules", "modules_with_skip_sites",
                                                    "native_modules", "native_runnable_tests",
                                                    "native_selected_required_tests")}, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
