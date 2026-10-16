#!/usr/bin/env python3
"""Validate a DSH profile after the plugin rows were written.

Fail-closed gate: the installer must run this BEFORE restarting DSH. A profile
that does not parse makes the Host refuse to start ("DeepSeek Harness is
unavailable"), which is exactly what happened when the overlay was appended with
a 2-space indent:

    dsh: failed to parse overlay .../cordis.patch.yml:
    YAMLParseException: bad indentation of a sequence entry (64:3)

Usage
    python validate-profile.py <profile-dir> [plugin-name]
Exit 0 = valid; non-zero prints the reason and the installer restores its backup.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with the bundled runtime
    yaml = None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: validate-profile.py <profile-dir> [plugin-name]")
        return 2
    profile = Path(sys.argv[1])
    plugin = sys.argv[2] if len(sys.argv) > 2 else None

    pkg_path = profile / "package.json"
    yml_path = profile / "cordis.patch.yml"

    # ── package.json ────────────────────────────────────────────────────────
    if not pkg_path.is_file():
        print(f"FAIL missing {pkg_path}")
        return 1
    raw = pkg_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        print("FAIL package.json has a UTF-8 BOM; the Host uses JSON.parse")
        return 1
    try:
        pkg = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"FAIL package.json is not valid JSON: {error}")
        return 1
    bundles = pkg.get("dsh", {}).get("profile", {}).get("bundles")
    if not isinstance(bundles, list) or not bundles:
        print("FAIL package.json has no dsh.profile.bundles list")
        return 1
    if plugin and plugin not in bundles:
        print(f"FAIL {plugin} is not in dsh.profile.bundles")
        return 1

    # ── cordis.patch.yml ────────────────────────────────────────────────────
    if not yml_path.is_file():
        print(f"FAIL missing {yml_path}")
        return 1
    text = yml_path.read_text(encoding="utf-8")
    if yaml is None:
        # structural fallback: every top-level entry starts at column 1
        for number, line in enumerate(text.splitlines(), 1):
            if line.startswith(" ") and line.lstrip().startswith("- ") and line.strip().startswith("- id:"):
                print(f"FAIL line {number} nests a sequence entry; top-level entries start at column 1")
                return 1
    else:
        try:
            overlay = yaml.safe_load(text)
        except yaml.YAMLError as error:
            print(f"FAIL cordis.patch.yml does not parse: {str(error).splitlines()[0]}")
            for line in str(error).splitlines()[:6]:
                print(f"     {line}")
            return 1
        if not isinstance(overlay, list):
            print(f"FAIL cordis.patch.yml must be a top-level list, got {type(overlay).__name__}")
            return 1
        # The installer deliberately does NOT edit the profile overlay: a bundle is
        # loaded because its name is in `dsh.profile.bundles`, and that bundle's own
        # cordis.patch.yml then applies. So the plugin is NOT expected to appear
        # here - only the overlay's own validity is checked. (An earlier revision did
        # require the id here and wrongly aborted a perfectly good install.)
        ids = [entry.get("id") for entry in overlay if isinstance(entry, dict)]
        print(f"ok   cordis.patch.yml parses: {len(overlay)} entries"
              + (f", includes {plugin}" if plugin and plugin in ids else ""))

    print("ok   package.json parses"
          + (f", bundles={len(bundles)}" if isinstance(bundles, list) else ""))
    print("VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

