#!/usr/bin/env python3
"""B-07: encoding checker and LOSSLESS transcoder for the R2 scripts.

Contract (R2-RUNBOOK.md B-07)

* ``.ps1``: accept either a BOM or none, write back UTF-8 with BOM and CRLF.
* ``.cmd``: must stay pure ASCII. A non-ASCII byte is reported with its
  characters and line numbers and the file is left untouched - cmd.exe reads
  batch files in the console OEM code page.
* No character is ever discarded. The previous implementation ran
  ``ascii_only()`` which silently dropped every byte above 0x7F; that logic is
  gone, and ``--check`` fails if any .ps1 would lose a character.

Usage

    python fix-encoding.py [--check] [paths...]

With no paths it walks the kit root and work/r2/build.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOM = b"\xef\xbb\xbf"
DEFAULT_TARGETS = [HERE, HERE / "work" / "r2" / "build"]


def decode_body(raw: bytes) -> tuple[str, str, str]:
    """Return (text, source_encoding, note). Never loses characters."""
    had_bom = raw.startswith(BOM)
    body = raw[len(BOM):] if had_bom else raw
    try:
        return body.decode("utf-8"), "utf-8" + ("+bom" if had_bom else ""), ""
    except UnicodeDecodeError as error:
        # A legacy code page file. Decode it so the bytes survive the round trip
        # rather than being dropped.
        text = body.decode("cp936", "replace")
        return text, "cp936", f"decoded from cp936 ({error.start})"


def crlf(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n").encode("utf-8")


def handle_ps1(path: Path, apply: bool) -> tuple[bool, str]:
    raw = path.read_bytes()
    text, source, note = decode_body(raw)
    wanted = BOM + crlf(text)
    detail = f"{source} -> utf-8+bom+crlf"
    if note:
        detail += f"; {note}"
    if raw == wanted:
        return True, f"[ok]   {path.name}: already correct ({detail})"
    if not apply:
        return True, f"[fix]  {path.name}: would write {len(wanted)} bytes ({detail})"
    path.write_bytes(wanted)
    return True, f"[ok]   {path.name}: {len(raw)} -> {len(wanted)} bytes ({detail})"


def handle_cmd(path: Path, apply: bool = True) -> tuple[bool, str]:
    raw = path.read_bytes()
    if raw.startswith(BOM):
        return False, (f"[FAIL] {path.name}: has a UTF-8 BOM; cmd.exe shows it as garbage. "
                       "Remove the BOM (do not strip characters).")
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as error:
        line = raw[: error.start].count(b"\n") + 1
        offenders = sorted({chr(b) for b in raw if b > 0x7F})
        return False, (f"[FAIL] {path.name}: non-ASCII byte at line {line} "
                       f"(chars {' '.join(repr(c) for c in offenders[:12])}). "
                       "cmd.exe would mis-read them; the file was NOT modified.")
    if b"\r\n" not in raw and b"\n" in raw:
        fixed = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
        if not apply:
            return True, f"[fix]  {path.name}: bare LF; would convert to CRLF"
        path.write_bytes(fixed)
        return True, f"[ok]   {path.name}: LF -> CRLF, {len(raw)} -> {len(fixed)} bytes, still pure ASCII"
    return True, f"[ok]   {path.name}: pure ASCII, {len(raw)} bytes"


def collect(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for target in paths:
        if target.is_file():
            out.append(target)
        elif target.is_dir():
            out.extend(sorted(p for p in target.iterdir() if p.suffix in {".ps1", ".cmd"}))
    seen = set()
    unique = []
    for path in out:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report only, change nothing")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] or DEFAULT_TARGETS
    files = collect(targets)
    if not files:
        print("no .ps1/.cmd files found")
        return 0

    failures = 0
    apply = not args.check
    for path in files:
        if path.suffix == ".ps1":
            ok, message = handle_ps1(path, apply)
        else:
            ok, message = handle_cmd(path, apply)
        print(message)
        if not ok:
            failures += 1

    print(f"\n{len(files)} file(s), {failures} problem(s)"
          + ("" if apply else "  [--check: nothing written]"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

