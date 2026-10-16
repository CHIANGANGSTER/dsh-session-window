#!/usr/bin/env python3
"""B-02: R2 ASAR patcher for the DSH Desktop shell.

Contract (R2-RUNBOOK.md B-02)

1. Refuse any input whose SHA-256 is not ``--expect-sha256`` (BASELINE).
2. Rebuild the header per the Pickle rules: with L = JSON byte count and L' the
   same padded up to a multiple of 4, write ``L`` at offset 12, ``4 + L'`` at 8
   and ``8 + L'`` at 4; the payload region starts at ``16 + L'``. No
   "header length must not change" assertion exists any more.
3. Touch only the target nodes' ``size``/``offset``/``integrity`` plus every node
   whose payload starts after a target's original offset, which shifts by that
   target's length delta. Never add a field; ``unpacked`` nodes are copied
   through untouched.
4. Content de-duplication survives: entries that share an offset stay grouped at
   one offset. A target whose offset is shared with another entry is refused.
5. Integrity is recomputed as SHA-256 using the node's original block size.

Usage

    python patch-asar.py --asar <in.asar> --spec patches/r2 --check
    python patch-asar.py --asar <in.asar> --spec patches/r2 --out <out.asar> \
        --expect-sha256 <BASELINE> --src-out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

DEFAULT_BLOCK_SIZE = 4_194_304


class Refuse(Exception):
    """A contract violation: nothing may be written."""


class Asar:
    """Reader for the packed layout (payload base = 16 + json_size)."""

    def __init__(self, data: bytes):
        self.data = data
        comment, pickle_length, header_size, json_size = struct.unpack_from("<4I", data, 0)
        self.comment = comment
        self.pickle_length = pickle_length
        self.header_size = header_size
        self.json_size = json_size
        raw = data[16 : 16 + json_size]
        if len(raw) != json_size:
            raise Refuse("asar: truncated header")
        try:
            self.header = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise Refuse(f"asar: header is not valid JSON ({error})")
        self.payload_start = 16 + json_size

    def path_node(self, asar_path: str) -> dict:
        node = self.header
        for part in asar_path.strip("/").split("/"):
            try:
                node = node["files"][part]
            except KeyError:
                raise Refuse(f"asar: {asar_path} not present")
        if "files" in node:
            raise Refuse(f"asar: {asar_path} is a directory")
        return node

    def packed(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []

        def walk(node: dict, prefix: str = "") -> None:
            for name, child in node.get("files", {}).items():
                path = f"{prefix}/{name}"
                if "files" in child:
                    walk(child, path)
                elif "offset" in child:
                    out.append((path, child))

        walk(self.header)
        return out

    def read(self, node: dict) -> bytes:
        start = self.payload_start + int(node["offset"])
        return self.data[start : start + int(node["size"])]


def build_header(header: dict) -> bytes:
    """Serialise the header with the Pickle prefix, padding JSON to a 4-byte multiple."""
    raw = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    length = len(raw)
    padded = length + (-length) % 4
    raw += b" " * (padded - length)
    return struct.pack("<4I", 4, 8 + padded, 4 + padded, length) + raw


def apply_edits(text: str, edits: list[dict], where: str) -> tuple[str, list[tuple[str, int]]]:
    seen: list[tuple[str, int]] = []
    for edit in edits:
        count = text.count(edit["find"])
        seen.append((edit["id"], count))
        if count != 1:
            raise Refuse(f"{where}: anchor {edit['id']!r} matched {count}x (need exactly 1)")
        if "replace" in edit:
            text = text.replace(edit["find"], edit["replace"], 1)
        elif "insert_before" in edit:
            text = text.replace(edit["find"], edit["insert_before"] + edit["find"], 1)
        elif "insert_after" in edit:
            text = text.replace(edit["find"], edit["find"] + edit["insert_after"], 1)
        else:
            raise Refuse(f"{where}: edit {edit['id']!r} has no action")
    return text, seen


def recompute_integrity(node: dict, data: bytes) -> None:
    integrity = node.get("integrity")
    if not isinstance(integrity, dict):
        return
    block_size = int(integrity.get("blockSize") or DEFAULT_BLOCK_SIZE)
    blocks = [hashlib.sha256(data[i : i + block_size]).hexdigest()
              for i in range(0, len(data), block_size)]
    integrity["algorithm"] = integrity.get("algorithm") or "SHA256"
    integrity["hash"] = hashlib.sha256(data).hexdigest()
    integrity["blockSize"] = block_size
    integrity["blocks"] = blocks or [hashlib.sha256(b"").hexdigest()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asar", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out")
    parser.add_argument("--src-out")
    parser.add_argument("--expect-sha256")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    asar_path = Path(args.asar)
    if not asar_path.is_file():
        print(f"ABORT: asar not found: {asar_path}")
        return 2

    original_bytes = asar_path.read_bytes()
    actual_sha = hashlib.sha256(original_bytes).hexdigest()
    if args.expect_sha256 and actual_sha.lower() != args.expect_sha256.lower():
        print(f"ABORT: input SHA-256 mismatch\n  expected {args.expect_sha256}\n  actual   {actual_sha}")
        return 2
    print(f"input  sha256 {actual_sha}")

    spec_dir = Path(args.spec)
    specs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(spec_dir.glob("*.json"))]
    if not specs:
        print(f"ABORT: no patch specs in {spec_dir}")
        return 2

    try:
        archive = Asar(original_bytes)
        print(f"header comment={archive.comment} pickle={archive.pickle_length} "
              f"header_size={archive.header_size} json_size={archive.json_size} "
              f"payload_start={archive.payload_start}")

        replacements: dict[str, bytes] = {}
        for spec in specs:
            target = spec["asar_path"]
            node = archive.path_node(target)
            before = archive.read(node).decode("utf-8")
            after, anchors = apply_edits(before, spec["edits"], target)
            for edit_id, count in anchors:
                print(f"  [ok] {target}  {edit_id}  matched 1x")
            replacements[target] = after.encode("utf-8")
            print(f"  {target}: {len(before):,} -> {len(after):,} bytes "
                  f"({len(after) - len(before):+,})")

        if args.check:
            print("\n--check passed; nothing written")
            return 0
        if not args.out:
            print("ABORT: --out is required unless --check")
            return 2

        # ── de-dup guard: which paths share each offset ─────────────────────
        by_offset: dict[int, list[str]] = {}
        for path, node in archive.packed():
            by_offset.setdefault(int(node["offset"]), []).append(path)

        targets: list[dict] = []
        for target in replacements:
            node = archive.path_node(target)
            old_offset = int(node["offset"])
            sharers = by_offset.get(old_offset, [])
            if len(sharers) > 1:
                raise Refuse(f"target {target} shares offset {old_offset} with {sharers} - "
                             "refusing, de-duplication would break")
            targets.append({"path": target, "node": node, "old_offset": old_offset,
                            "old_size": int(node["size"]), "new": replacements[target]})
        targets.sort(key=lambda t: t["old_offset"])

        print("\ntargets (ascending old offset):")
        for t in targets:
            print(f"  {t['path']}: old_offset={t['old_offset']:,} "
                  f"{t['old_size']:,} -> {len(t['new']):,} B "
                  f"({len(t['new']) - t['old_size']:+,})")

        def delta_for(old_offset: int) -> int:
            """Sum of length deltas of targets that start strictly before old_offset."""
            total = 0
            for t in targets:
                if t["old_offset"] >= old_offset:
                    break
                total += len(t["new"]) - t["old_size"]
            return total

        # ── rewrite: stream payloads in old-offset order, assign real cursors ─
        #
        # Offsets are NOT derived from delta arithmetic: the payload region is
        # rewritten sequentially, so each group's offset is simply the cursor at
        # which its bytes were written. Deriving offsets independently of the
        # write order desynchronises the two (it silently broke an unrelated
        # koffi/doc/values.md entry in the first attempt). Grouping by old offset
        # keeps de-duplicated entries sharing a single new offset.
        groups: dict[int, list[str]] = {}
        for path, node in archive.packed():
            groups.setdefault(int(node["offset"]), []).append(path)

        # pass 1: cache each group's original bytes, then simulate the stream to
        # learn every node's new offset.
        #
        # Two traps this avoids:
        #   * blobs must be captured BEFORE offsets are mutated, because
        #     archive.read() resolves through the live node.
        #   * a shared offset does NOT imply identical content or identical size.
        #     The shipped archive pairs koffi/doc/values.md (6324 B) with
        #     unions.md (0 B) at one offset, so the stored region is the LONGEST
        #     member's, and each node still reads its own length from that start.
        blobs: dict[int, bytes] = {}
        cursor = 0
        for old_offset in sorted(groups):
            members = groups[old_offset]
            span = max(int(archive.path_node(path)["size"]) for path in members)
            data = replacements.get(members[0])
            if data is None or span != len(data):
                stored = archive.data[archive.payload_start + old_offset
                                      : archive.payload_start + old_offset + span]
                if data is None:
                    data = stored
                else:
                    data = data + stored[len(data):]
            blobs[old_offset] = data
            for path in members:
                node = archive.path_node(path)
                node["offset"] = str(cursor)
                if path in replacements:
                    node["size"] = len(replacements[path])
                    recompute_integrity(node, replacements[path])
            cursor += len(data)
        total_payload = cursor

        # pass 2: serialise the header, then stream header + cached payloads
        header_bytes = build_header(archive.header)
        json_size = struct.unpack_from("<I", header_bytes, 12)[0]
        if 16 + json_size != len(header_bytes):
            raise Refuse(f"asar: header self-check failed "
                         f"(stored {len(header_bytes)}, computed {16 + json_size})")

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as out:
            out.write(header_bytes)
            written = 0
            for old_offset in sorted(groups):
                data = blobs[old_offset]
                out.write(data)
                written += len(data)
            if written != total_payload:
                raise Refuse(f"asar: payload length drift ({written} != {total_payload})")

        # 3. re-read the result and confirm every node still points at its bytes
        patched = Asar(out_path.read_bytes())
        verified = 0
        for path, node in patched.packed():
            data = patched.read(node)
            integrity = node.get("integrity")
            if isinstance(integrity, dict):
                expected = integrity.get("hash")
                came_from = replacements.get(path)
                if came_from is not None and data != came_from:
                    raise Refuse(f"asar: post-write content mismatch for {path}")
                if expected and hashlib.sha256(data).hexdigest() != expected:
                    raise Refuse(f"asar: integrity hash mismatch for {path}")
                verified += 1

        final_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
        size = out_path.stat().st_size
        print(f"\nwrote {out_path}")
        print(f"  size   {size:,} bytes")
        print(f"  PATCHED sha256 {final_sha}")
        print(f"  integrity verified on {verified} node(s)")

        # 4. de-dup preserved?
        before_groups = len({int(n["offset"]) for _p, n in Asar(original_bytes).packed()})
        after_groups = len({int(n["offset"]) for _p, n in patched.packed()})
        print(f"  distinct offsets: {before_groups} -> {after_groups}")

        if args.src_out:
            src_dir = Path(args.src_out)
            src_dir.mkdir(parents=True, exist_ok=True)
            for target, data in replacements.items():
                (src_dir / Path(target).name).write_bytes(data)
            print(f"  source copies -> {src_dir}")
        return 0
    except Refuse as error:
        print(f"ABORT: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

