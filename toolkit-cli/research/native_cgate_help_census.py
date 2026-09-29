#!/usr/bin/env python3
"""Capture the maintained C-Gate command matrix with HELP requests only.

The direct backend opens one fresh TCP connection per command.  The Windows
backend uploads one hash-verified PowerShell job to the repository's owned UTM
guest directory and executes it once through ``utmctl``.  Both backends send
only ``HELP <path>`` plus ``HELP *``; they never select a project, authenticate,
or issue a network/database/programming command.

Raw reports contain volatile timestamps and should be retained separately.
Committed acceptance fixtures may remove only the deterministic command tag.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
DEFAULT_MATRIX = REPOSITORY / "rust/cbus-cgate/src/capability_matrix.rs"
RUN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


def matrix_paths(path: Path) -> tuple[str, ...]:
    """Read only the primary 431-row matrix, excluding supplemental routes."""
    source = path.read_text()
    primary, separator, _ = source.partition("pub const SUPPLEMENT_ROUTING:")
    if not separator:
        raise ValueError("Capability matrix has no SUPPLEMENT_ROUTING boundary")
    paths = tuple(sorted(re.findall(
        r'CapabilityEntry\s*\{\s*path:\s*"([^"]+)"', primary
    )))
    if len(paths) != 431 or len(set(paths)) != 431:
        raise ValueError(
            f"Expected 431 unique primary paths, got {len(paths)} rows / "
            f"{len(set(paths))} unique"
        )
    if any("\r" in path or "\n" in path for path in paths):
        raise ValueError("Command paths must remain single-line text")
    return paths


def _terminal(line: str, prefix: str) -> bool:
    body = line[len(prefix):] if line.startswith(prefix) else ""
    return len(body) >= 4 and body[:3].isdigit() and body[3] == " "


def _exchange(host: str, port: int, command: str, tag: str,
              timeout: float) -> dict:
    lines: list[str] = []
    banner = None
    error = None
    terminal = False
    try:
        with socket.create_connection((host, port), timeout=timeout) as stream:
            stream.settimeout(timeout)
            file = stream.makefile("rwb", buffering=0)
            banner = file.readline().decode("utf-8").rstrip("\r\n")
            stream.sendall(f"[{tag}] {command}\r\n".encode("ascii"))
            prefix = f"[{tag}] "
            for _ in range(512):
                raw = file.readline()
                if not raw:
                    raise EOFError("Connection closed before a terminal response")
                line = raw.decode("utf-8").rstrip("\r\n")
                lines.append(line)
                if _terminal(line, prefix):
                    terminal = True
                    break
            else:
                raise RuntimeError("Response exceeded the 512-line bound")
    except Exception as cause:  # Retain partial evidence instead of hiding it.
        error = f"{type(cause).__name__}: {cause}"
    return {
        "command": command,
        "tag": tag,
        "banner": banner,
        "terminal": terminal,
        "lines": lines,
        "error": error,
    }


def direct_capture(paths: tuple[str, ...], host: str, port: int,
                   timeout: float, profile: str) -> dict:
    rows = []
    for index, path in enumerate(paths):
        row = _exchange(host, port, "HELP " + path, f"hc{index:04d}", timeout)
        row.update(index=index, path=path)
        rows.append(row)
    help_star = _exchange(host, port, "HELP *", "helpstar", timeout)
    return {
        "format": "native-cgate-help-census-raw-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint_profile": profile,
        "command_count": len(paths),
        "rows": rows,
        "help_star": help_star,
        "read_only": True,
        "project_commands_sent": 0,
        "mutation_commands_sent": 0,
    }


def _guest_script(prefix: str) -> str:
    commands = rf"C:\CBusCliOracle118-88d8\{prefix}.commands.json"
    output = rf"C:\CBusCliOracle118-88d8\{prefix}.json"
    return rf"""$ErrorActionPreference='Stop'
$commands=Get-Content -Raw -LiteralPath '{commands}'|ConvertFrom-Json
function Invoke-Help($command,$tag){{
  $lines=@();$banner=$null;$errorText=$null;$terminal=$false
  $client=$null;$reader=$null;$writer=$null
  try{{
    $client=[Net.Sockets.TcpClient]::new()
    $client.ReceiveTimeout=3000;$client.SendTimeout=3000
    $client.Connect('127.0.0.1',20023)
    $stream=$client.GetStream()
    $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$false,4096,$true)
    $writer=[IO.StreamWriter]::new($stream,[Text.Encoding]::ASCII,4096,$true)
    $writer.NewLine="`r`n";$writer.AutoFlush=$true
    $banner=$reader.ReadLine();$writer.WriteLine('['+$tag+'] '+$command)
    $linePrefix='['+$tag+'] '
    for($n=0;$n -lt 512;$n++){{
      $line=$reader.ReadLine()
      if($null -eq $line){{throw 'connection closed before terminal response'}}
      $lines+=,$line
      if($line.StartsWith($linePrefix)-and $line.Length-ge($linePrefix.Length+4)-and
         $line.Substring($linePrefix.Length,3)-match '^[0-9]{{3}}$'-and
         $line[$linePrefix.Length+3]-eq ' '){{$terminal=$true;break}}
      if($n-eq511){{throw 'response line bound exceeded'}}
    }}
  }}catch{{$errorText=$_.Exception.GetType().FullName+': '+$_.Exception.Message}}
  finally{{if($writer){{$writer.Dispose()}};if($reader){{$reader.Dispose()}};if($client){{$client.Dispose()}}}}
  [ordered]@{{command=$command;tag=$tag;banner=$banner;terminal=$terminal;lines=$lines;error=$errorText}}
}}
$rows=@()
for($i=0;$i -lt $commands.Count;$i++){{
  $path=[string]$commands[$i]
  $row=Invoke-Help ('HELP '+$path) ('hc{{0:d4}}'-f $i)
  $row.index=$i;$row.path=$path;$rows+=,$row
}}
$star=Invoke-Help 'HELP *' 'helpstar'
$result=[ordered]@{{
  format='native-cgate-help-census-raw-v1'
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  endpoint_profile='owned UTM guest loopback, HELP only'
  command_count=$commands.Count
  rows=$rows
  help_star=$star
  read_only=$true
  project_commands_sent=0
  mutation_commands_sent=0
}}
[IO.File]::WriteAllText('{output}',($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
"""


def windows_capture(paths: tuple[str, ...], run_id: str,
                    timeout: float) -> bytes:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("run-id must be 1..32 lower-case letters, digits, or hyphens")
    sys.path.insert(0, str(ROOT))
    from research.windows_bridge import WindowsBridge, UTMCTL, VM_UUID

    bridge = WindowsBridge()
    prefix = "native-help-" + run_id
    script = _guest_script(prefix).replace("\n", "\r\n").encode()
    commands = (json.dumps(list(paths), separators=(",", ":")) + "\n").encode()
    command = (
        "@echo off\r\n"
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f"-File {bridge.path(prefix + '.ps1')}\r\n"
        f"> {bridge.path(prefix + '.exit.txt')} echo %errorlevel%\r\n"
    ).encode()
    names = [prefix + suffix for suffix in (
        ".commands.json", ".ps1", ".cmd", ".exit.txt", ".json"
    )]
    if any(bridge.pull(name, missing_ok=True) is not None for name in names):
        raise ValueError("run-id already has a durable guest artifact; never replay it")
    bridge.push(prefix + ".commands.json", commands)
    bridge.push(prefix + ".ps1", script)
    bridge.push(prefix + ".cmd", command)
    result = subprocess.run([
        UTMCTL, "exec", "--debug", VM_UUID, "--cmd",
        r"C:\Windows\System32\cmd.exe", "/d", "/c",
        bridge.path(prefix + ".cmd"),
    ], capture_output=True, timeout=90)
    if result.returncode or result.stderr:
        raise RuntimeError(result.stderr.decode(errors="replace") or
                           f"utmctl status {result.returncode}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = bridge.pull(prefix + ".json", missing_ok=True)
        exit_data = bridge.pull(prefix + ".exit.txt", missing_ok=True)
        if data is not None and exit_data is not None:
            if exit_data.strip() != b"0":
                raise RuntimeError("Guest HELP capture returned " +
                                   exit_data.decode(errors="replace").strip())
            return data
        time.sleep(.5)
    raise TimeoutError("Guest capture outcome is uncertain; inspect the same run-id")


def _positive(value: str) -> float:
    number = float(value)
    if not 0 < number <= 600:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 600")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=_positive, default=180.0)
    sub = parser.add_subparsers(dest="backend", required=True)
    direct = sub.add_parser("direct")
    direct.add_argument("--host", required=True)
    direct.add_argument("--port", type=int, required=True)
    direct.add_argument("--profile", required=True)
    windows = sub.add_parser("windows")
    windows.add_argument("--run-id", required=True)
    args = parser.parse_args()

    paths = matrix_paths(args.matrix)
    if args.backend == "direct":
        if not 1 <= args.port <= 65535:
            parser.error("port must be 1..65535")
        report = direct_capture(paths, args.host, args.port,
                                min(args.timeout, 30), args.profile)
        data = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    else:
        data = windows_capture(paths, args.run_id, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(json.dumps({
        "output": str(args.output),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "commands": len(paths),
        "read_only": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
