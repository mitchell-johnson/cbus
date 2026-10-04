"""Owned fresh-venv guard; observes installed imports without changing resolution."""
from __future__ import annotations

import atexit
import hashlib
import importlib.abc
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def activate(config_path):
    raw = Path(config_path).read_bytes()
    config = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    guard_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    existing = getattr(sys, "_cbus_installed_guard", None)
    if existing is not None:
        if existing.get("config_sha256") == digest and existing.get("guard_sha256") == guard_digest:
            return  # CPython may process the owned venv site directory twice.
        raise RuntimeError("Installed interop guard changed during activation")
    package = Path(config["installed_package"]).resolve()
    root = Path(config["origin_directory"])
    root.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    origins = root / f"origins-{pid}.jsonl"
    launches = root / f"launches-{pid}.jsonl"
    admitted = config["package_files"]
    loaded = {}
    children = []

    def write(path, row):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def emit(kind, **values):
        write(origins, {"kind": kind, "pid": pid, "config_sha256": digest,
                        "ppid": os.getppid(), "monotonic_ns": time.monotonic_ns(), **values})

    def reject(reason):
        emit("violation", reason=reason)
        raise ImportError("Installed interop import authority failed: " + reason)

    def file_identity(path):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            reject("non-regular product source")
        resolved = path.resolve()
        if not resolved.is_relative_to(package):
            reject("product source fallback outside installed package")
        relative = resolved.relative_to(package).as_posix()
        content = resolved.read_bytes()
        item = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        if admitted.get(relative) != item:
            reject("product source bytes are outside frozen package")
        return {"path": str(resolved), **item}, content

    def reject_caches():
        for path in package.rglob("*"):
            if path.is_symlink() or "__pycache__" in path.relative_to(package).parts or path.suffix in {".pyc", ".pyo"}:
                reject("product symlink or bytecode cache")

    class SourceLoader(importlib.abc.Loader):
        def __init__(self, original, fullname, origin):
            self.original, self.fullname, self.origin = original, fullname, origin

        def create_module(self, spec):
            return self.original.create_module(spec)

        def exec_module(self, module):
            code = self.get_code(self.fullname)
            exec(code, module.__dict__)

        def get_code(self, fullname):
            reject_caches()
            item, content = file_identity(self.origin)
            # Compile the checked source directly; never read a substituted timestamp pyc.
            code = compile(content, self.origin, "exec", dont_inherit=True)
            loaded[self.fullname] = self
            emit("module", modules={self.fullname: item})
            return code

        def get_source(self, fullname):
            return file_identity(self.origin)[1].decode("utf-8")

        def get_filename(self, fullname):
            return self.origin

        def is_package(self, fullname):
            return Path(self.origin).name == "__init__.py"

        def get_resource_reader(self, fullname):
            file_identity(self.origin)
            return self.original.get_resource_reader(fullname)

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "cbus_toolkit" and not fullname.startswith("cbus_toolkit."):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None or not isinstance(spec.loader, importlib.machinery.SourceFileLoader) or not spec.origin:
                reject("product must resolve through a source-file loader")
            file_identity(spec.origin)
            spec.loader = SourceLoader(spec.loader, fullname, spec.origin)
            return spec

    finder = Finder()
    original_popen = subprocess.Popen

    def launch_role(args, kwargs):
        argv = list(args) if isinstance(args, (list, tuple)) else [str(args)]
        argv = [os.fsdecode(arg) for arg in argv]
        executable = os.fsdecode(kwargs.get("executable") or argv[0])
        env = kwargs.get("env")
        env = os.environ if env is None else env
        executable = shutil.which(executable, path=env.get("PATH", os.defpath)) or executable
        resolved = str(Path(executable).resolve())
        basename = Path(executable).name
        python = (re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", basename) is not None or
                  basename == "cbus-toolkit" or resolved == str(Path(config["python"]).resolve()))
        if kwargs.get("shell") and any(re.search(r"(?:python|cbus-toolkit)", arg) for arg in argv):
            reject("shell Python launch cannot establish child identity")
        if python:
            return "python", argv, basename == "cbus-toolkit" or "cbus_toolkit" in argv
        if resolved in config["binary_resolved"]:
            return "owned-rust", argv, False
        return None, argv, False

    class ObservedPopen(original_popen):
        def __init__(self, args, *positional, **kwargs):
            bound = inspect.signature(original_popen).bind_partial(args, *positional, **kwargs)
            role, argv, product_cli = launch_role(args, bound.arguments)
            super().__init__(args, *positional, **kwargs)
            if role:
                self._cbus_row = {"pid": self.pid, "owner_pid": pid, "role": role,
                                  "product_cli": product_cli, "argv": argv,
                                  "returncode": None, "event": "launch"}
                children.append(self)
                write(launches, self._cbus_row)

    def modules():
        result = {}
        for name, module in list(sys.modules.items()):
            if name != "cbus_toolkit" and not name.startswith("cbus_toolkit."):
                continue
            origin = getattr(module, "__file__", None)
            if not origin or loaded.get(name) is not getattr(module, "__loader__", None):
                reject("product module bypassed checked source loader")
            item, _ = file_identity(origin)
            if getattr(module, "__cached__", None) and Path(module.__cached__).exists():
                reject("product cached loader artifact appeared")
            result[name] = item
        return result

    def finish():
        try:
            reject_caches()
            snapshot = modules()
            active = finder in sys.meta_path and subprocess.Popen is ObservedPopen
        except (Exception, SystemExit) as error:
            snapshot, active = {}, False
            emit("violation", reason="terminal guard: " + type(error).__name__)
        for child in children:
            original_outcome = child.poll()
            row = {**child._cbus_row, "event": "terminal", "returncode": original_outcome}
            write(launches, row)
            if original_outcome is None:
                cleanup = {"pid": child.pid, "owner_pid": pid, "original_returncode": None,
                           "role": child._cbus_row["role"]}
                try:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                    cleanup.update(reaped=True, cleanup_returncode=child.returncode)
                except Exception as error:
                    cleanup.update(reaped=False, error=type(error).__name__)
                write(root / f"cleanup-{pid}.jsonl", cleanup)
        emit("terminal", executable=sys.executable, prefix=sys.prefix, modules=snapshot,
             guard_active=active)

    reject_caches()
    if any(name == "cbus_toolkit" or name.startswith("cbus_toolkit.") for name in sys.modules):
        reject("product imported before owned guard startup")
    sys.meta_path.insert(0, finder)
    subprocess.Popen = ObservedPopen
    sys._cbus_installed_guard = {"config_sha256": digest, "guard_sha256": guard_digest, "finder": finder}
    atexit.register(finish)
    emit("startup", executable=sys.executable, prefix=sys.prefix, modules={})
