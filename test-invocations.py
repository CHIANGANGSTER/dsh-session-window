#!/usr/bin/env python3
"""R2 invocation surface test (B-08).

Proves the command lines a user would actually type resolve, parse and reach the
expected exit code, without touching any real installation:

  * every R2 script parses under PowerShell 5.1
  * each entry (.cmd) is pure ASCII with CRLF and names the script it calls
  * the placeholder entries exit 9
  * rollback-plugin refuses with exit 8 while nothing is bound
  * install.ps1 -WhatIf exits 0 without changing a file
  * the ring of exit codes 0/2/3/5/7/8/9 is documented in the kit README/runbook

Exit code 0 means every check passed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
R2 = KIT / "work" / "r2"

SCRIPTS = [
    "install.ps1",
    "rollback.ps1",
    "log.ps1",
    "work/r2/build/rollback-plugin.ps1",
    "work/r2/build/restore-baseline.ps1",
    "work/r2/build/b08_selftest.ps1",
]

ENTRIES = {
    "install.cmd": {"exit": 9, "calls": None},
    "rollback.cmd": {"exit": 9, "calls": None},
    "install-smoke.cmd": {"exit": None, "calls": "install.ps1"},
    "rollback-smoke.cmd": {"exit": None, "calls": "rollback.ps1"},
    "rollback-plugin.cmd": {"exit": None, "calls": "rollback-plugin.ps1"},
    "work/r2/build/install-formal.cmd": {"exit": None, "calls": "install.ps1"},
    "work/r2/build/rollback-formal.cmd": {"exit": None, "calls": "rollback.ps1"},
}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'[ok]  ' if ok else '[FAIL]'} {label}  {detail}")
    if not ok:
        failures.append(label)


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


print("=== 1. scripts parse under PowerShell 5.1 ===")
PARSE = ("$t=$null;$e=$null;"
         "[void][System.Management.Automation.Language.Parser]::ParseFile('{p}',[ref]$t,[ref]$e);"
         "if($e.Count -eq 0){{exit 0}};$e[0].Message;exit 1")
for rel in SCRIPTS:
    path = KIT / rel
    if not path.is_file():
        check(f"1 parse {rel}", False, "missing")
        continue
    proc = run(["powershell.exe", "-NoProfile", "-Command", PARSE.format(p=path)])
    detail = proc.stdout.strip().splitlines()
    check(f"1 parse {rel}", proc.returncode == 0, detail[0][:90] if detail else "")

print("\n=== 2. entry files are ASCII + CRLF and call the right script ===")
for rel, spec in ENTRIES.items():
    path = KIT / rel
    if not path.is_file():
        check(f"2 {rel}", False, "missing")
        continue
    raw = path.read_bytes()
    ascii_ok = all(b < 0x80 for b in raw)
    crlf = raw.count(b"\r\n")
    bare_lf = raw.count(b"\n") - crlf
    calls_ok = True if spec["calls"] is None else (spec["calls"] in raw.decode("ascii", "replace"))
    check(f"2 {rel} ascii+crlf+calls", ascii_ok and bare_lf == 0 and calls_ok,
          f"ascii={ascii_ok} crlf={crlf} bareLF={bare_lf} calls={calls_ok}")

print("\n=== 3. placeholder entries exit 9 ===")
for rel in ("install.cmd", "rollback.cmd"):
    proc = run(["cmd.exe", "/c", str(KIT / rel)], timeout=60)
    check(f"3 {rel} -> 9", proc.returncode == 9, f"exit={proc.returncode}")

print("\n=== 4. rollback-plugin refuses while unbound (exit 8) ===")
binding = Path.home() / "AppData" / "Local" / "dsh-r2-pipre" / "unused.json"
proc = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(R2 / "build" / "rollback-plugin.ps1"),
            "-BindingFile", str(R2 / "selftest" / "definitely-missing.json")])
check("4 rollback-plugin unbound -> 8", proc.returncode == 8, f"exit={proc.returncode}")

print("\n=== 5. install.ps1 --WhatIf is read-only ===")
probe = R2 / "selftest" / "invocation" / "resources"
probe.mkdir(parents=True, exist_ok=True)
baseline = R2 / "backup" / "baseline" / "app.asar"
target = probe / "app.asar"
target.write_bytes(baseline.read_bytes())
before = target.stat().st_size
proc = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(KIT / "install.ps1"),
            "-AppDir", str(probe.parent), "-WhatIf"])
check("5 -WhatIf exit 0", proc.returncode == 0, f"exit={proc.returncode}")
check("5 -WhatIf unchanged", target.stat().st_size == before)

print("\n=== 6. exit-code table documented ===")
doc = (KIT / "R2-RUNBOOK.md")
text = doc.read_text(encoding="utf-8", errors="replace") if doc.is_file() else ""
for code in ("| 0 |", "| 2 |", "| 3 |", "| 5 |", "| 7 |", "| 8 |", "| 9 |"):
    check(f"6 runbook documents {code.strip('| ')}", code in text)

print(f"\n=== test-invocations: {'PASS' if not failures else 'FAIL'} "
      f"({len(failures)} failure(s)) ===")
for item in failures:
    print(f"  FAILED: {item}")
sys.exit(1 if failures else 0)

