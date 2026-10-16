#!/usr/bin/env node
/**
 * Build the client half.
 *
 * The client half is hand-written in the format the browser module table expects:
 *
 *   window.__ModuleLoader__.load({ id: '<package>', factory(require) { ... return { inject, apply } } })
 *
 * so there is nothing to transpile. This script verifies the source parses and
 * copies it to lib/client.js, which package.json exports as "./client".
 */
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const source = join(root, 'src', 'client', 'index.js')
const target = join(root, 'lib', 'client.js')

execFileSync(process.execPath, ['--check', source], { stdio: 'inherit' })
mkdirSync(dirname(target), { recursive: true })
copyFileSync(source, target)

const bytes = readFileSync(target)
const sha = createHash('sha256').update(bytes).digest('hex')
console.log(`built lib/client.js  ${bytes.length} bytes`)
console.log(`sha256 ${sha}`)

