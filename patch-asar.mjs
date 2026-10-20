#!/usr/bin/env node
// Port of patch-asar.py, so the installer needs no Python and no prebuilt
// 182 MB archive: the patch travels as diffs and is applied on the user's own
// machine. Run it with the app itself when Node is absent:
//
//   ELECTRON_RUN_AS_NODE=1 "DeepSeek Harness.exe" patch-asar.mjs --asar ... --spec patches/r2 --check
//
// Contract (same as the Python original)
//   1. Refuse any input whose SHA-256 is not --expect-sha256 (the pristine BASELINE).
//   2. Rebuild the header per the Pickle rules: with L the JSON byte count and L'
//      that padded to a multiple of 4, write L at 12, 4+L' at 8, 8+L' at 4; the
//      payload region starts at 16+L'.
//   3. Touch only the target nodes' size/offset/integrity, plus every node whose
//      payload starts at a target's old offset (it moves as a group). Never add a
//      field.
//   4. Content de-duplication survives: entries sharing an offset stay grouped.
//   5. Integrity is re-computed as SHA-256 with the node's original block size.
//
// Usage
//   node patch-asar.mjs --asar <in.asar> --spec patches/r2 --check
//   node patch-asar.mjs --asar <in.asar> --spec patches/r2 --out <out.asar> \
//        --expect-sha256 <BASELINE> [--src-out <dir>]

import { createHash } from 'node:crypto'
import * as nodeFs from 'node:fs'
import { join, basename, dirname } from 'node:path'

// Electron patches `fs` so that a path ending in .asar is treated as a package
// and validated on open - which makes writing a freshly built archive fail with
// "Invalid package". `original-fs` is the unpatched module Electron exposes for
// exactly this case. Plain Node has no such module, so fall back to node:fs.
let fs = nodeFs
try {
  const original = await import('original-fs')
  fs = original.default ?? original
} catch {
  // not running under Electron; node:fs is already unpatched
}
const readFileSync = fs.readFileSync.bind(fs)
const writeFileSync = fs.writeFileSync.bind(fs)
const mkdirSync = fs.mkdirSync.bind(fs)
const readdirSync = fs.readdirSync.bind(fs)
const existsSync = fs.existsSync.bind(fs)
const statSync = fs.statSync.bind(fs)

const DEFAULT_BLOCK_SIZE = 4_194_304
const sha256 = (buf) => createHash('sha256').update(buf).digest('hex')

class Refuse extends Error {}

class Asar {
  constructor(data) {
    this.data = data
    this.comment = data.readUInt32LE(0)
    this.pickleLength = data.readUInt32LE(4)
    this.headerSize = data.readUInt32LE(8)
    this.jsonSize = data.readUInt32LE(12)
    const raw = data.subarray(16, 16 + this.jsonSize)
    if (raw.length !== this.jsonSize) throw new Refuse('asar: truncated header')
    try {
      this.header = JSON.parse(raw.toString('utf8'))
    } catch (error) {
      throw new Refuse(`asar: header is not valid JSON (${error.message})`)
    }
    this.payloadStart = 16 + this.jsonSize
  }

  pathNode(asarPath) {
    let node = this.header
    for (const part of asarPath.replace(/^\/+|\/+$/g, '').split('/')) {
      if (!node.files || !(part in node.files)) throw new Refuse(`asar: ${asarPath} not present`)
      node = node.files[part]
    }
    if (node.files) throw new Refuse(`asar: ${asarPath} is a directory`)
    return node
  }

  packed() {
    const out = []
    const walk = (node, prefix) => {
      for (const [name, child] of Object.entries(node.files ?? {})) {
        const path = `${prefix}/${name}`
        if (child.files) walk(child, path)
        else if (child.offset !== undefined) out.push([path, child])
      }
    }
    walk(this.header, '')
    return out
  }

  read(node) {
    const start = this.payloadStart + Number(node.offset)
    return this.data.subarray(start, start + Number(node.size))
  }
}

function buildHeader(header) {
  const raw = Buffer.from(JSON.stringify(header), 'utf8')
  const length = raw.length
  const padded = length + ((4 - (length % 4)) % 4)
  const body = Buffer.concat([raw, Buffer.alloc(padded - length, 0x20)])
  const pre = Buffer.alloc(16)
  pre.writeUInt32LE(4, 0)
  pre.writeUInt32LE(8 + padded, 4)
  pre.writeUInt32LE(4 + padded, 8)
  pre.writeUInt32LE(length, 12)
  return Buffer.concat([pre, body])
}

function applyEdits(text, edits, where) {
  const seen = []
  for (const edit of edits) {
    const count = text.split(edit.find).length - 1
    seen.push([edit.id, count])
    if (count !== 1) throw new Refuse(`${where}: anchor ${edit.id} matched ${count}x (need exactly 1)`)
    if (edit.replace !== undefined) text = text.replace(edit.find, () => edit.replace)
    else if (edit.insert_before !== undefined) text = text.replace(edit.find, () => edit.insert_before + edit.find)
    else if (edit.insert_after !== undefined) text = text.replace(edit.find, () => edit.find + edit.insert_after)
    else throw new Refuse(`${where}: edit ${edit.id} has no action`)
  }
  return [text, seen]
}

function recomputeIntegrity(node, data) {
  const integrity = node.integrity
  if (!integrity || typeof integrity !== 'object') return
  const blockSize = Number(integrity.blockSize) || DEFAULT_BLOCK_SIZE
  const blocks = []
  for (let i = 0; i < data.length; i += blockSize) blocks.push(sha256(data.subarray(i, i + blockSize)))
  integrity.algorithm = integrity.algorithm || 'SHA256'
  integrity.hash = sha256(data)
  integrity.blockSize = blockSize
  integrity.blocks = blocks.length ? blocks : [sha256(Buffer.alloc(0))]
}

function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i]
    if (!key.startsWith('--')) continue
    const name = key.slice(2)
    if (name === 'check') args.check = true
    else args[name] = argv[++i]
  }
  return args
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.asar || !args.spec) {
    console.error('ABORT: --asar and --spec are required')
    return 2
  }
  if (!existsSync(args.asar)) {
    console.error(`ABORT: asar not found: ${args.asar}`)
    return 2
  }

  const originalBytes = readFileSync(args.asar)
  const actualSha = sha256(originalBytes)
  if (args['expect-sha256'] && actualSha.toLowerCase() !== args['expect-sha256'].toLowerCase()) {
    console.error(`ABORT: input SHA-256 mismatch\n  expected ${args['expect-sha256']}\n  actual   ${actualSha}`)
    return 2
  }
  console.log(`input  sha256 ${actualSha}`)

  if (!existsSync(args.spec)) {
    console.error(`ABORT: spec directory missing: ${args.spec}`)
    return 2
  }
  const specFiles = readdirSync(args.spec).filter((f) => f.endsWith('.json')).sort()
  if (specFiles.length === 0) {
    console.error(`ABORT: no patch specs in ${args.spec}`)
    return 2
  }
  const specs = specFiles.map((f) => JSON.parse(readFileSync(join(args.spec, f), 'utf8')))

  try {
    const archive = new Asar(originalBytes)
    console.log(
      `header comment=${archive.comment} pickle=${archive.pickleLength} ` +
        `header_size=${archive.headerSize} json_size=${archive.jsonSize} payload_start=${archive.payloadStart}`,
    )

    const replacements = new Map()
    for (const spec of specs) {
      const target = spec.asar_path
      const node = archive.pathNode(target)
      const before = archive.read(node).toString('utf8')
      const [after, anchors] = applyEdits(before, spec.edits, target)
      for (const [editId] of anchors) console.log(`  [ok] ${target}  ${editId}  matched 1x`)
      replacements.set(target, Buffer.from(after, 'utf8'))
      console.log(`  ${target}: ${before.length.toLocaleString('en-US')} -> ${after.length.toLocaleString('en-US')} bytes`)
    }

    if (args.check) {
      console.log('\n--check passed; nothing written')
      return 0
    }
    if (!args.out) {
      console.error('ABORT: --out is required unless --check')
      return 2
    }

    // de-dup guard: refuse a target that shares its offset with another entry
    const byOffset = new Map()
    for (const [path, node] of archive.packed()) {
      const off = Number(node.offset)
      if (!byOffset.has(off)) byOffset.set(off, [])
      byOffset.get(off).push(path)
    }
    for (const target of replacements.keys()) {
      const node = archive.pathNode(target)
      const sharers = byOffset.get(Number(node.offset)) ?? []
      if (sharers.length > 1) {
        throw new Refuse(`target ${target} shares offset ${node.offset} with ${sharers.join(', ')}`)
      }
    }

    const groups = new Map()
    for (const [path, node] of archive.packed()) {
      const off = Number(node.offset)
      if (!groups.has(off)) groups.set(off, [])
      groups.get(off).push(path)
    }

    const blobs = new Map()
    let cursor = 0
    for (const oldOffset of [...groups.keys()].sort((a, b) => a - b)) {
      const members = groups.get(oldOffset)
      const span = Math.max(...members.map((p) => Number(archive.pathNode(p).size)))
      let data = replacements.get(members[0])
      if (data === undefined || span !== data.length) {
        const stored = archive.data.subarray(
          archive.payloadStart + oldOffset,
          archive.payloadStart + oldOffset + span,
        )
        if (data === undefined) data = stored
        else data = Buffer.concat([data, stored.subarray(data.length)])
      }
      blobs.set(oldOffset, data)
      for (const path of members) {
        const node = archive.pathNode(path)
        node.offset = String(cursor)
        if (replacements.has(path)) {
          const replacement = replacements.get(path)
          node.size = replacement.length
          recomputeIntegrity(node, replacement)
        }
      }
      cursor += data.length
    }
    const totalPayload = cursor

    const headerBytes = buildHeader(archive.header)
    const jsonSize = headerBytes.readUInt32LE(12)
    if (16 + jsonSize !== headerBytes.length) {
      throw new Refuse(`asar: header self-check failed (${headerBytes.length} vs ${16 + jsonSize})`)
    }

    mkdirSync(dirname(args.out), { recursive: true })
    const parts = [headerBytes]
    for (const oldOffset of [...groups.keys()].sort((a, b) => a - b)) parts.push(blobs.get(oldOffset))
    const output = Buffer.concat(parts)
    if (output.length - headerBytes.length !== totalPayload) {
      throw new Refuse(`asar: payload length drift (${output.length - headerBytes.length} != ${totalPayload})`)
    }
    writeFileSync(args.out, output)

    // re-read and verify every node still points at its bytes
    const patched = new Asar(readFileSync(args.out))
    let verified = 0
    for (const [path, node] of patched.packed()) {
      const data = patched.read(node)
      const integrity = node.integrity
      if (integrity && typeof integrity === 'object') {
        const cameFrom = replacements.get(path)
        if (cameFrom !== undefined && !data.equals(cameFrom)) {
          throw new Refuse(`asar: post-write content mismatch for ${path}`)
        }
        if (integrity.hash && sha256(data) !== integrity.hash) {
          throw new Refuse(`asar: integrity hash mismatch for ${path}`)
        }
        verified += 1
      }
    }

    const finalSha = sha256(readFileSync(args.out))
    console.log(`\nwrote ${args.out}`)
    console.log(`  size   ${statSync(args.out).size.toLocaleString('en-US')} bytes`)
    console.log(`  PATCHED sha256 ${finalSha}`)
    console.log(`  integrity verified on ${verified} node(s)`)
    const beforeGroups = new Set(new Asar(originalBytes).packed().map(([, n]) => Number(n.offset)))
    const afterGroups = new Set(patched.packed().map(([, n]) => Number(n.offset)))
    console.log(`  distinct offsets: ${beforeGroups.size} -> ${afterGroups.size}`)

    if (args['src-out']) {
      mkdirSync(args['src-out'], { recursive: true })
      for (const [target, data] of replacements) writeFileSync(join(args['src-out'], basename(target)), data)
      console.log(`  source copies -> ${args['src-out']}`)
    }
    return 0
  } catch (error) {
    if (error instanceof Refuse) {
      console.error(`ABORT: ${error.message}`)
      return 2
    }
    throw error
  }
}

process.exit(main())
