#!/usr/bin/env python3
"""Report whether the live shell archive is patched, and how its header compares.

Read-only. Prints, for the installed archive and any backups:

* size and SHA-256
* the four prefix fields and the payload base
* whether the two patch markers are present (i.e. it is the patched build)
* how the regenerated header compares with the shipped one
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

RESOURCES = Path(r"E:\Software\DeepSeek Harness\resources")
LIVE = RESOURCES / "app.asar"
PATCHED = Path(r"E:\Software\DSH Desktop\dsh-session-window\work\app.asar.patched")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def describe(path: Path) -> dict:
    with path.open("rb") as f:
        prefix = f.read(16)
        comment, pickle_length, header_size, json_size = struct.unpack("<4I", prefix)
        f.seek(16)
        raw = f.read(json_size)
        header = json.loads(raw.decode("utf-8"))
        node = header
        for part in "lib/main.js".strip("/").split("/"):
            node = node["files"][part]
        f.seek(header_size + 12 + int(node["offset"]))
        main_tail = f.read(int(node["size"]))
    return {
        "size": path.stat().st_size,
        "sha256": digest(path),
        "comment": comment,
        "pickle_length": pickle_length,
        "header_size": header_size,
        "json_size": json_size,
        "json_bytes_stored": len(raw),
        "patched": b"__dshWindows" in main_tail,
        "open_session_marker": b"dsh-desktop:open-session-window" in main_tail,
    }


def show(label: str, path: Path) -> dict | None:
    if not path.is_file():
        print(f"\n=== {label}: MISSING  {path}")
        return None
    info = describe(path)
    print(f"\n=== {label}: {path.name}")
    print(f"  size          {info['size']:,} bytes")
    print(f"  sha256        {info['sha256'][:24]}")
    print(f"  prefix        comment={info['comment']} pickle_length={info['pickle_length']} "
          f"header_size={info['header_size']} json_size={info['json_size']}")
    print(f"  json bytes stored = {info['json_bytes_stored']} "
          f"(json_size says {info['json_size']}, delta {info['json_bytes_stored'] - info['json_size']:+d})")
    print(f"  payload base  header_size+12 = {info['header_size'] + 12} = "
          f"16 + json_size = {16 + info['json_size']}")
    print(f"  PATCHED?      __dshWindows={info['patched']} "
          f"open-session-ipc={info['open_session_marker']}")
    return info


def main() -> int:
    live = show("INSTALLED (live)", LIVE)
    built = show("BUILT PATCH", PATCHED)

    backups = sorted(RESOURCES.glob("app.asar.original-*"))
    print(f"\n=== backups found: {len(backups)}")
    for backup in backups:
        info = describe(backup) if backup.is_file() else None
        if info:
            print(f"  {backup.name}  {info['size']:,} bytes  sha256={info['sha256'][:16]}  "
                  f"patched={info['patched']}")

    print("\n=== verdict")
    if live is None:
        print("  ! live archive missing - the install was interrupted mid-copy")
    elif live["patched"]:
        print("  ! live archive IS the patched build")
    else:
        print("  live archive is the ORIGINAL build (patch not installed)")

    if live and built:
        same = live["sha256"] == built["sha256"]
        print(f"  live == built patch: {same}")
        if live["header_size"] != built["header_size"]:
            print(f"  header differs: live {live['header_size']} vs built {built['header_size']}")
    return 0


if __name__ == "__main__":
    if not LIVE.is_file() and not PATCHED.is_file():
        sys.exit("nothing to inspect")
    sys.exit(main())

