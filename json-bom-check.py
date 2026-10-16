#!/usr/bin/env python3
"""Detect (and optionally strip) a UTF-8 BOM in JSON files the Host parses.

Why this exists: PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM, and
the DSH Host reads a profile manifest with plain `JSON.parse`, which rejects a
leading U+FEFF. That produced:

    DesktopHostFatalError: Unexpected token '﻿', "﻿{ "name"... is not valid JSON
      at readProfileManifest

Removing a BOM is an encoding fix, not character stripping, so it stays inside the
B-07 rule ("never discard characters"). The check is a guard for every JSON file
the Host or the shell has to parse.

Usage
    python json-bom-check.py [--fix] [paths...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"
HERE = Path(__file__).resolve().parent
DEFAULT_TARGETS = [
    HERE,
    HERE / "work" / "r2",
    HERE / "plugin",
    Path.home() / "AppData" / "Local" / "dsh-r2-private",
]


def collect(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for target in paths:
        if target.is_file() and target.suffix == ".json":
            out.append(target)
        elif target.is_dir():
            out.extend(sorted(p for p in target.rglob("*.json")
                              if "\\extract\\" not in str(p) and "\\build\\pkg\\" not in str(p)
                              and "node_modules" not in str(p)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] or DEFAULT_TARGETS
    files = collect(targets)
    bad = []
    for path in files:
        raw = path.read_bytes()
        if raw.startswith(BOM):
            bad.append(path)
            if args.fix:
                path.write_bytes(raw[len(BOM):])
                print(f"[fixed] {path}  (BOM removed, {len(raw)} -> {len(raw) - 3} bytes)")
            else:
                print(f"[FAIL]  {path}  has a UTF-8 BOM; JSON.parse will reject it")

    print(f"\nscanned {len(files)} json file(s); {len(bad)} with a BOM")
    if bad and not args.fix:
        print("re-run with --fix to remove them")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

