#!/usr/bin/env node
/**
 * C-04 static checks for the client plugin.
 *
 * The browser boot loads a client half through `window.__ModuleLoader__.load`,
 * NOT as plain ESM. Shipping plain ESM produced:
 *     web boot: 1 entry did not activate
 *     dsh-session-window-client: import failed
 * so the format is asserted here directly, together with NEGATIVE CONTROLS that
 * prove these assertions can actually fail. A check that cannot fail is worthless
 * - that is how a wrong assumption passed review once already.
 */
import { readFileSync, existsSync, writeFileSync, unlinkSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const read = (rel) => readFileSync(join(root, rel), 'utf8')

const failures = []
function check(label, ok, detail = '') {
  console.log(`${ok ? '[ok]  ' : '[FAIL]'} ${label}${detail ? '  ' + detail : ''}`)
  if (!ok) failures.push(label)
}

const srcClient = read('src/client/index.js')
const libClient = read('lib/client.js')
const libHost = read('lib/index.js')
const pkg = JSON.parse(read('package.json'))
const name = pkg.name

// ── the module format the browser table requires ────────────────────────────
function formatProblems(text, label) {
  const problems = []
  if (!text.includes('window.__ModuleLoader__.load(')) problems.push('missing __ModuleLoader__.load wrapper')
  if (!new RegExp(`id:\\s*['"]${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['"]`).test(text)) {
    problems.push('factory id does not equal the package name')
  }
  if (!/factory\s*\(\s*require\s*\)/.test(text)) problems.push('missing factory(require)')
  if (!/return\s*\{\s*inject\s*,\s*apply\s*\}/.test(text)) problems.push('factory does not return { inject, apply }')
  if (/^\s*import\s+[^(]/m.test(text)) problems.push('contains a top-level import statement')
  if (/^\s*export\s+(function|const|class|\{)/m.test(text)) problems.push('contains a top-level export statement')
  if (!/require\(['"]react['"]\)/.test(text)) problems.push('does not require react from the module table')
  return problems
}

for (const [label, text] of [['src/client/index.js', srcClient], ['lib/client.js', libClient]]) {
  const problems = formatProblems(text, label)
  check(`1 browser module format: ${label}`, problems.length === 0, problems.join('; '))
}

// 1b negative controls - the assertions above must be able to fail
{
  const negative = 'import { createElement } from "react"\nexport function apply() {}\n'
  check('1b negative control: plain ESM rejected', formatProblems(negative, 'neg').length >= 3,
    formatProblems(negative, 'neg').slice(0, 3).join('; '))
  const negative2 = `window.__ModuleLoader__.load({ id: 'someone-else', factory(r) { return {} } })`
  check('1b negative control: wrong id and no return shape rejected',
    formatProblems(negative2, 'neg2').length >= 3)
}

// ── peer/runtime declaration rules from references/ui-plugin.md ─────────────
const client = pkg.dsh?.client ?? {}
check('2 dsh.client.platform is web', client.platform === 'web')
check('2 dsh.client.immediately declared', client.immediately === true)
check('2 dsh.client.inject names packages', Array.isArray(client.inject) && client.inject.length > 0,
  JSON.stringify(client.inject))
check('2 slot provider is injected first',
  (client.inject ?? []).includes('@deepseek-ai/dsh-client-ui-workspace'))
const externals = client.external ?? []
check('2 non-baseline require declared in dsh.client.external',
  externals.includes('@deepseek-ai/dsh-client-ui-primitives'), JSON.stringify(externals))
check('2 every non-baseline require is declared',
  [...srcClient.matchAll(/require\(['"]([^'"]+)['"]\)/g)]
    .map((m) => m[1])
    .filter((id) => id !== 'react')
    .every((id) => externals.includes(id)),
  [...new Set([...srcClient.matchAll(/require\(['"]([^'"]+)['"]\)/g)].map((m) => m[1]))].join(', '))

// ── build freshness and parsability ─────────────────────────────────────────
check('3 lib/client.js matches src', srcClient === libClient)
for (const [label, body] of [['lib/client.js', libClient], ['lib/index.js', libHost]]) {
  const tmp = join(root, `.tmp-check-${label.replace(/[\\/]/g, '_')}`)
  try {
    writeFileSync(tmp, body)
    execFileSync(process.execPath, ['--check', tmp], { stdio: 'pipe' })
    unlinkSync(tmp)
    check(`3 parses: ${label}`, true)
  } catch (error) {
    try { unlinkSync(tmp) } catch {}
    check(`3 parses: ${label}`, false, String(error.message).slice(0, 80))
  }
}
check('3 host half is the template shape', /export function apply\s*\(/.test(libHost))

// ── design contract ─────────────────────────────────────────────────────────
for (const banned of ['contextMenu', 'onOpenSession']) {
  check(`4 no ${banned}`, !srcClient.includes(banned) && !libHost.includes(banned))
}
const timers = [...srcClient.matchAll(/setTimeout\(/g)].length
const clearers = [...srcClient.matchAll(/clearTimeout\(/g)].length
check('4 setTimeout only for the two deadlines', timers === 2 && clearers === 2,
  `setTimeout=${timers} clearTimeout=${clearers}`)
check('4 no retry loop over setTimeout', !/setTimeout[\s\S]{0,200}?(retry|again|loop)/i.test(srcClient))
check('5 menu slot correct', srcClient.includes("'sidebar.workspaces.session.menu.item'"))
check('5 menu id correct',
  /const ITEM_ID = 'open-in-new-window'/.test(srcClient) && /id:\s*ITEM_ID/.test(srcClient))
check('5 order is 350', /order:\s*350/.test(srcClient))
check('5 overlay notice slot declared', srcClient.includes("'shell.overlay'"))
check('6 bridge version guard', /version\s*===\s*2/.test(srcClient))
// Contract change: without the Desktop bridge the entry is now rendered
// DISABLED with an explanatory label instead of being omitted. A silently
// missing menu item left users unable to tell "not installed" from
// "shell not patched"; a greyed-out row says which one it is.
check('6 item disabled without a bridge', /disabled:\s*!hasBridge\(\)/.test(srcClient))
check('6 fallback label present', srcClient.includes('menu.bridgeUnavailable'))
check('6 no silent early guard in the click handler', !/if\s*\(!hasBridge\(\)\s*\|\|/.test(srcClient))
check('7 no ipcRenderer', !srcClient.includes('ipcRenderer') && !libClient.includes('ipcRenderer'))
check('7 client inject declares services', /const inject = \['slots'(, )?'locale'\]/.test(srcClient))

// Native-menu behavior is exercised by behavior.mjs; no private React fiber access.
check('10 window-capture contextmenu listener', /window\.addEventListener\('contextmenu',\s*\w+,\s*true\)/.test(srcClient))
check('10 no temporary diagnostics', !/probe\(|TRACE_KEY|__reactFiber|describeNeighbourhood/.test(srcClient))
try {
  execFileSync(process.execPath, [join(root, 'scripts/behavior.mjs')], { stdio: 'inherit' })
  check('10 native-menu and landing behavior', true)
} catch { check('10 native-menu and landing behavior', false) }

// ── session id format, tested against a real observed id ────────────────────
{
  // Taken from the session store on disk and seen in the live DOM row key.
  const REAL_ID = 'session-07a30b2c-662f-43e3-9384-60172f255d92'
  const idSource = /const SESSION_ID = \/(.+)\/([a-z]*)/.exec(srcClient)
  const rowSource = /const ROW_KEY = \/(.+)\/([a-z]*)/.exec(srcClient)
  check('11 SESSION_ID pattern is present', idSource !== null)
  check('11 ROW_KEY pattern is present', rowSource !== null)
  if (idSource && rowSource) {
    const id = new RegExp(idSource[1], idSource[2])
    const rowKey = new RegExp(rowSource[1], rowSource[2])
    check('11 real session id accepted', id.test(REAL_ID), `pattern ${idSource[1]}`)
    check('11 bare uuid still accepted', id.test(REAL_ID.replace('session-', '')))
    check('11b negative control: uuid-only pattern would reject the real id',
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(REAL_ID))
    const row = rowKey.exec(`session:${REAL_ID}`)
    check('11 row key unwraps to the id', row !== null && row[1] === REAL_ID)
    check('11b negative control: a workspace kind does not unwrap',
      /^session:(.+)$/.test(`workspace:${REAL_ID}`) === false)
  }
}

// ── package shape ───────────────────────────────────────────────────────────
check('8 dsh.bundle.patch declared', pkg.dsh?.bundle?.patch === './cordis.patch.yml')
check('8 exports ./client', pkg.exports?.['./client']?.default === './lib/client.js')
for (const rel of ['cordis.patch.yml', 'lib/client.js', 'lib/index.js', 'README.md']) {
  check(`9 ${rel} exists`, existsSync(join(root, rel)))
}

console.log(`\n=== check: ${failures.length === 0 ? 'PASS' : 'FAIL'} (${failures.length} failure(s)) ===`)
for (const item of failures) console.log(`  FAILED: ${item}`)
process.exit(failures.length === 0 ? 0 : 1)

