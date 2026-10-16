#!/usr/bin/env python3
"""Refresh plugin digests in MANIFEST.json without changing any profile."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

KIT = Path(__file__).resolve().parent
R2 = KIT / "work" / "r2"
PLUGIN = KIT / "plugin" / "dsh-session-window-client"
MANIFEST = R2 / "MANIFEST.json"
SHIPPED = ["package.json", "cordis.patch.yml", "README.md", "lib/index.js", "lib/client.js"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    print("=== C-04 plugin digests ===")
    per_file: dict[str, str] = {}
    for rel in SHIPPED:
        path = PLUGIN / rel
        if not path.is_file():
            print(f"  [FAIL] missing {rel}")
            return 1
        per_file[rel] = sha256(path)
        print(f"  {rel:<22} {per_file[rel][:16]}...")

    # deterministic directory digest: sha256 over "path:hash" lines in sorted order
    bundle = hashlib.sha256(
        "\n".join(f"{rel}:{per_file[rel]}" for rel in sorted(per_file)).encode("utf-8")
    ).hexdigest()
    print(f"  bundle digest        {bundle}")

    pkg = json.loads((PLUGIN / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["plugin_name"] = pkg["name"]
    manifest["plugin_version"] = pkg["version"]
    manifest["plugin_sha256"] = bundle
    manifest["plugin_files"] = per_file
    manifest["plugin_client_sha256"] = per_file["lib/client.js"]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  manifest updated: plugin_{pkg['version']} {bundle[:16]}...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

