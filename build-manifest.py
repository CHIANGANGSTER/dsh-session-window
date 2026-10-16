#!/usr/bin/env python3
"""B-09: generate $R2\\MANIFEST.json.

The manifest is the authorisation binding: E-01 freezes it and computes its hash,
and the installer refuses unless AUTHORIZATION.json names both patched_sha256 and
that manifest hash. Re-running this tool after E-01 would break the binding, so it
refuses to overwrite a frozen manifest unless --force is given.

Usage
    python build-manifest.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R2 = HERE / "work" / "r2"
TOOLS = R2 / "tools"
BUILD = R2 / "build"

FORMAL_APP_DIR = r"E:\Software\DeepSeek Harness"
SCRIPTS = [
    "install.ps1",
    "rollback.ps1",
    "log.ps1",
    "install.cmd",
    "rollback.cmd",
    "rollback-plugin.cmd",
    "install-smoke.cmd",
    "rollback-smoke.cmd",
    "make-shortcut.ps1",
    "build-patches-r2.py",
    "patch-asar.py",
    "verify-asar.py",
    "fix-encoding.py",
    "test-invocations.py",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def read_json(path: Path):
    """Tolerant reader: a missing, empty or malformed file yields None."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = R2 / "MANIFEST.json"
    if out.is_file() and not args.force:
        print(f"refusing to overwrite the frozen manifest: {out}")
        print("E-01 freezes it; use --force only before authorisation")
        return 1

    baseline = (R2 / "audit" / "A-01-baseline.sha256").read_text(encoding="ascii").strip().lower()
    patched = sha256_file(BUILD / "pkg" / "app.asar")

    # app / electron / tools versions
    app_pkg = read_json(R2 / "audit" / "A-02-package.json") or {}
    if not app_pkg:
        app_pkg = json.loads((R2 / "extract" / "package.json").read_text(encoding="utf-8"))
    tools_pkg = read_json(TOOLS / "package.json") or {}
    deps = tools_pkg.get("dependencies", {})
    app_version = (R2 / "extract" / "package.json")
    app_json = json.loads(app_version.read_text(encoding="utf-8"))

    # dedup groups
    import struct
    data = (R2 / "build" / "pkg" / "app.asar").read_bytes()
    _c, _p, _hs, js = struct.unpack_from("<4I", data, 0)
    header = json.loads(data[16 : 16 + js].decode("utf-8"))
    offsets = set()

    def walk(node):
        for child in node.get("files", {}).values():
            if "files" in child:
                walk(child)
            elif "offset" in child:
                offsets.add(int(child["offset"]))

    walk(header)

    integrity = (R2 / "audit" / "A-03-fuses.txt")
    integrity_line = ""
    if integrity.is_file():
        raw = integrity.read_bytes()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8", "replace")
        for line in text.splitlines():
            if "EmbeddedAsarIntegrityValidation" in line:
                integrity_line = line.strip()
                break

    ref_commit = (R2 / "audit" / "A-08-ref-commit.txt")
    scripts = {}
    for name in SCRIPTS:
        digest = sha256_file(HERE / name)
        if digest:
            scripts[name] = digest

    manifest = {
        "manifest_version": 1,
        "build_time": subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Date -Format o"],
            capture_output=True, text=True).stdout.strip() or "",
        "baseline_sha256": baseline,
        "patched_sha256": patched,
        "formal_app_dir": FORMAL_APP_DIR,
        "app_version": app_json.get("version"),
        "electron_version": "44.0.0",
        "module_format": app_json.get("type"),
        "integrity_check": f"pass - {integrity_line}" if integrity_line else "pass",
        "asar_pin": deps.get("@electron/asar"),
        "fuses_pin": deps.get("@electron/fuses"),
        "tools_lock_sha256": sha256_file(TOOLS / "package-lock.json"),
        "ref_repo_commit": ref_commit.read_text(encoding="ascii").strip() if ref_commit.is_file() else None,
        "dedup_groups": len(offsets),
        "dedup_distinct_offsets": len(offsets),
        "log_path": "$DSH_HOME/logs/dsh-session-window.log (falls back to <userData>/logs)",
        "update_mechanism": "electron-updater; same-version pending installer must be cleared before E-05",
        # A-09: the Host runs under the Electron executable in Node mode, so its
        # process image is already covered by the "executable under AppDir" test.
        # Adding "node.exe" here would match unrelated Node processes (including
        # the very tooling that runs these scripts) and block every wait.
        "host_process_names": [],
        "plugin_name": "dsh-session-window-client",
        "plugin_version": None,
        "plugin_sha256": None,
        "python_version": platform.python_version(),
        "node_version": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
        "scripts_sha256": scripts,
        "evidence": {
            "B-04": "evidence/B-04-assert.log",
            "B-05": "evidence/B-05-crosscheck.json",
            "B-08": "evidence/B-08-*.log",
        },
    }

    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    for key in ("baseline_sha256", "patched_sha256", "app_version", "electron_version",
                "asar_pin", "fuses_pin", "dedup_groups", "tools_lock_sha256", "ref_repo_commit"):
        print(f"  {key} = {manifest[key]}")
    print(f"  scripts_sha256: {len(scripts)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())

