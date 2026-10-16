import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const id = 'session-07a30b2c-662f-43e3-9384-60172f255d92'
let api
class Element {
  constructor(row) { this.row = row }
  closest() { return this.row }
}
const context = vm.createContext({
  Element, AbortController, setTimeout, clearTimeout,
  dshSessionWindow: { version: 2 },
  window: { __ModuleLoader__: { load(module) {
    api = module.factory(() => ({}))
  } } }
})
const source = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8')
vm.runInContext(source.replace('return { inject, apply }',
  'return { inject, apply, openNativeMenu, runLanding }'), context)
const sessions = { list: { getSnapshot: () => ({ byId: { [id]: {} } }) } }
let clicks = 0
let prevented = 0
const button = { focus() {}, click() { clicks++ } }
const row = {
  className: 'hIlkoa_sessionRow',
  getAttribute: () => `session:${id}`,
  querySelector: () => button
}
const event = {
  target: new Element(row),
  preventDefault() { prevented++ }, stopImmediatePropagation() {}
}
api.openNativeMenu(event, sessions)
assert.equal(clicks, 1, 'right click delegates to the existing native menu')
assert.equal(prevented, 1)
row.getAttribute = () => `workspace:${id}`
api.openNativeMenu(event, sessions)
row.getAttribute = () => `session:${id}`
row.className = 'hIlkoa_projectRow'
api.openNativeMenu(event, sessions)
row.className = 'hIlkoa_sessionRow'
api.openNativeMenu(event, { list: { getSnapshot: () => ({ byId: {} }) } })
button.disabled = true
api.openNativeMenu(event, sessions)
assert.equal(clicks, 1, 'project, missing session and disabled buttons are untouched')

const acknowledgements = []
let selected
let opens = 0
const workspace = {
  openSession(target) { opens++; selected = target },
  selection: { getSnapshot: () => ({ sessionId: selected }) }
}
const ctx = { get: (name) => name === 'sessions' ? sessions : workspace }
const life = new AbortController()
context.dshSessionWindow.getPendingTarget = async () => null
context.dshSessionWindow.ackPendingTarget = async (...args) => acknowledgements.push(args)
await api.runLanding(ctx, life.signal)
assert.equal(opens, 0, 'primary window has no pending target')
context.dshSessionWindow.getPendingTarget = async () => ({ requestId: 'r1', sessionId: id })
await api.runLanding(ctx, life.signal)
assert.equal(selected, id)
assert.deepEqual(acknowledgements.pop(), ['r1', 'opened'])
context.dshSessionWindow.getPendingTarget = async () => ({ requestId: 'r2', sessionId: id, expired: true })
await api.runLanding(ctx, life.signal)
assert.deepEqual(acknowledgements.pop(), ['r2', 'failed', 'TIMEOUT'])
assert.equal(opens, 1, 'expired targets never navigate')
workspace.openSession = () => { selected = 'different-session' }
context.dshSessionWindow.getPendingTarget = async () => ({ requestId: 'r3', sessionId: id })
await api.runLanding(ctx, life.signal)
assert.deepEqual(acknowledgements.pop(), ['r3', 'failed', 'OPEN_FAILED'])
console.log('PASS native right-click and target landing (including rejection paths)')

