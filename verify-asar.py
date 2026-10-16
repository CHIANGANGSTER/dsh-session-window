#!/usr/bin/env python3
"""Verify a patched DSH shell archive against the shipped one.

Checks, in order:
  1. the 16-byte prefix and header blob match the layout the shell expects;
  2. every packed node's declared SHA-256 matches the bytes at its offset
     (the ground truth for the payload base, which is ``header_size + 12``);
  3. the two patched sources parse (``node --check``), so a syntax error cannot
     reach a running shell;
  4. the expected patch markers are present.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path

ORIGINAL = Path(r"E:\Software\DeepSeek Harness\resources\app.asar")
PATCHED = Path(r"E:\Software\DSH Desktop\dsh-session-window\work\app.asar.patched")


def probe(path: Path, label: str) -> tuple[dict, int, int]:
    with path.open("rb") as f:
        prefix = f.read(16)
        comment, pickle_length, header_size, json_size = struct.unpack("<4I", prefix)
        f.seek(16)
        header = json.loads(f.read(json_size).decode("utf-8"))
        payload_start = header_size + 12

        packed, unpacked = [], 0

        def walk(node):
            nonlocal unpacked
            for name, child in node.get("files", {}).items():
                if "files" in child:
                    walk(child)
                elif "offset" in child:
                    packed.append(child)
                else:
                    unpacked += 1

        walk(header)

        total = len(packed)
        out_of_bounds = 0
        mismatched = 0
        size = path.stat().st_size
        for node in packed:
            start = payload_start + int(node["offset"])
            length = int(node["size"])
            if start < payload_start or start + length > size:
                out_of_bounds += 1
                continue
            integrity = node.get("integrity")
            if not isinstance(integrity, dict):
                continue
            f.seek(start)
            if hashlib.sha256(f.read(length)).hexdigest() != integrity.get("hash"):
                mismatched += 1

        print(f"\n=== {label}: {path.name}")
        print(f"  comment={comment} pickle_length={pickle_length} "
              f"header_size={header_size} json_size={json_size}")
        print(f"  payload_start = header_size + 12 = {payload_start}")
        print(f"  packed={total} unpacked={unpacked}")
        print(f"  out-of-bounds payloads: {out_of_bounds}")
        print(f"  integrity mismatches:   {mismatched} / {total}")

        for asar_path in ("/lib/main.js", "/lib/preload-app.cjs"):
            node = header
            for part in asar_path.strip("/").split("/"):
                node = node["files"][part]
            f.seek(payload_start + int(node["offset"]))
            data = f.read(int(node["size"]))
            digest = hashlib.sha256(data).hexdigest()
            reported = (node.get("integrity") or {}).get("hash")
            print(f"  {asar_path}: size={node['size']} sha256={digest[:12]} "
                  f"integrity_ok={reported == digest}")
        return header, header_size, payload_start


probe(ORIGINAL, "ORIGINAL")
new_header, new_header_size, base = probe(PATCHED, "PATCHED")

with PATCHED.open("rb") as f:
    for asar_path, suffix in (("/lib/main.js", ".mjs"), ("/lib/preload-app.cjs", ".cjs")):
        node = new_header
        for part in asar_path.strip("/").split("/"):
            node = node["files"][part]
        f.seek(base + int(node["offset"]))
        data = f.read(int(node["size"]))
        tmp = Path(tempfile.gettempdir()) / f"dsh-verify{suffix}"
        tmp.write_bytes(data)
        proc = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
        print(f"\n--- node --check {asar_path} ({len(data)} bytes): exit {proc.returncode}")
        for stream in (proc.stdout, proc.stderr):
            if stream.strip():
                print("   ", stream.strip()[:1200])

with PATCHED.open("rb") as f:
    for asar_path, marker in (
        ("/lib/main.js", b"__dshWindows"),
        ("/lib/main.js", b"dsh-desktop:open-session-window"),
        ("/lib/main.js", b"dsh-desktop:show-session-menu"),
        ("/lib/main.js", b"WebContents.fromId(details.webContentsId)"),
        ("/lib/preload-app.cjs", b"dshSessionWindow"),
        ("/lib/preload-app.cjs", b"dsh-desktop:show-session-menu"),
        ("/lib/preload-app.cjs", b"dsh-desktop:open-session"),
    ):
        node = new_header
        for part in asar_path.strip("/").split("/"):
            node = node["files"][part]
        f.seek(base + int(node["offset"]))
        data = f.read(int(node["size"]))
        print(f"marker {marker.decode():<44} in {asar_path}: {marker in data}")

