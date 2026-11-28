// Cases for tests/test_custom_slots_ui.mjs, loaded only when HERMES_DESKTOP_SOURCE_ROOT names a Desktop
// source checkout (jsdom and React come from it). Element checks compare `=== null` as booleans: an
// assertion that carries a React-owned jsdom node as `actual` makes node:assert walk the whole fiber graph.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const source = readFileSync(new URL('../../desktop/plugin.js', import.meta.url), 'utf8')
const require = createRequire(path.join(core, 'apps/desktop/package.json'))
const { JSDOM } = require('jsdom')
const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://fixture.invalid/' })
globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true
const React = require('react'), { createRoot } = require('react-dom/client')
const { jsx, jsxs } = require('react/jsx-runtime')
const imports = {}
for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(v => v.trim()).filter(Boolean)) imports[name] = () => null
const Button = ({ id, disabled, onClick, children }) => jsx('button', { id, disabled: Boolean(disabled), onClick, children })
const Input = ({ id, value, onChange, disabled }) => jsx('input', { id, value, onChange, disabled: Boolean(disabled) })
const Badge = ({ children }) => jsx('span', { 'data-badge': true, children })
const Select = ({ children }) => jsx('div', { children })
const pass = ({ children }) => jsx('span', { children })
Object.assign(imports, { DesktopSDK: {}, host: {}, jsx, jsxs, Button, Input, Badge, Select, SelectTrigger: ({ id }) => jsx('span', { id }), SelectValue: () => null, SelectContent: () => null, SelectItem: () => null,
  useState: React.useState, useRef: React.useRef, useEffect: React.useEffect })
const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
const api = new Function(...Object.keys(imports), code + '\nreturn { CustomSlotsSection, ExecutionRow, setCustomTaskSlots, taskSlots, executionLabel };')(...Object.values(imports))
const threeD = { id: 'custom:3d-graphics', label: '3D·그래픽', description: 'Blender Python·Three.js 코드와 렌더 결과 검수' }
const writing = { id: 'custom:ko-writing', label: '한국어 글쓰기', description: '자연스러운 한국어 원고 작성과 윤문' }
const status = (revision, list, blocking = [], extra = {}) => ({ revision, slot_capabilities: { schema: 1, custom_slots_supported: true, custom_slots: list, blocking_profiles: blocking, ...extra } })
const $ = sel => document.querySelector(sel)
const sleep = ms => new Promise(r => setTimeout(r, ms))
const tick = () => React.act(async () => { await sleep(5) })
const click = async sel => { const el = $(sel); assert.ok(el, 'missing ' + sel); assert.equal(el.disabled, false, sel + ' is disabled'); await React.act(async () => { el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })) }); await tick() }
const type = async (sel, value) => { const el = $(sel); assert.ok(el, 'missing ' + sel)
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set
  await React.act(async () => { setter.call(el, value); el.dispatchEvent(new dom.window.Event('input', { bubbles: true })) }); await tick() }
async function mount(initial, restImpl) {
  document.getElementById('root').innerHTML = ''
  const host = document.createElement('div'); document.getElementById('root').appendChild(host)
  const root = createRoot(host)
  const calls = []
  const rest = async (p, options) => { calls.push({ path: p, body: options.body }); return restImpl ? restImpl(p, options) : (p === '/apply' ? { status: 'applied' } : { plan_id: 'plan-' + calls.length, changes: [] }) }
  let applied = 0
  const render = async (st, disabled = false) => { await React.act(async () => root.render(jsx(api.CustomSlotsSection, { status: st, rest, disabled, onApplied: async () => { applied++ } }))); await tick() }
  await render(initial)
  return { render, calls, applied: () => applied, close: () => React.act(async () => root.unmount()) }
}
const errors = []
const origError = console.error
console.error = (...a) => { errors.push(a.map(String).join(' ').slice(0, 300)) }
test('A1 recovery: blocked profile, remove every slot -> check enabled, sends []', async () => {
  const m = await mount(status(7, [threeD, writing], ['old-profile']))
  assert.ok($('#custom-slots-blocked'), 'blocked note')
  assert.match($('#custom-slots-blocked').textContent, /모든 슬롯을 지우는 저장은 지금도/)
  await click('#custom-slot-1-remove')
  assert.equal($('#custom-slots-check').disabled, true, 'partial removal must stay disabled while blocked')
  await click('#custom-slot-0-remove')
  assert.equal($('#custom-slots-check').disabled, false, 'remove-all must be enabled')
  await click('#custom-slots-check')
  assert.deepEqual(m.calls, [{ path: '/custom-slots-preview', body: { expected_revision: 7, custom_slots: [] } }])
  assert.ok($('#custom-slots-preview'))
  assert.deepEqual([...document.querySelectorAll('#custom-slots-preview li')].map(li => li.textContent), ['삭제: 3D·그래픽 (custom:3d-graphics)', '삭제: 한국어 글쓰기 (custom:ko-writing)'])
  await click('#custom-slots-apply')
  assert.equal(m.calls.at(-1).path, '/apply'); assert.equal(m.applied(), 1)
  await m.close()
})
test('A2 blocked: adding/editing stays disabled', async () => {
  const m = await mount(status(7, [threeD], ['old-profile']))
  await type('#custom-slot-0-label', '3D 작업')
  assert.equal($('#custom-slots-check').disabled, true)
  await m.close()
})
test('A3 not blocked: edit enabled', async () => {
  const m = await mount(status(7, [threeD], []))
  await type('#custom-slot-0-label', '3D 작업')
  assert.equal($('#custom-slots-check').disabled, false)
  await m.close()
})
test('B1 unreadable stored list locks editing', async () => {
  const m = await mount(status(7, [{ ...threeD, label: 'x'.repeat(30) }]))
  assert.ok($('#custom-slots-unreadable'), 'unreadable alert'); assert.equal($('#custom-slot-add') === null, true); assert.equal($('#custom-slots-check') === null, true)
  await m.close()
})
test('B2 five stored (over limit) locks; non-array is not locked', async () => {
  const m = await mount(status(7, Array.from({ length: 5 }, (_, n) => ({ ...threeD, id: 'custom:s-' + n, label: 'L' + n }))))
  assert.ok($('#custom-slots-unreadable'))
  // A non-list is not a definition list: shown as none, the service refuses any save that disagrees.
  await m.render(status(7, { 'custom:x': threeD }))
  assert.equal($('#custom-slots-unreadable') === null, true)
  await m.close()
})
test('B3 unreadable -> readable transition keeps hooks stable', async () => {
  const m = await mount(status(7, [{ ...threeD, label: 'x'.repeat(25) }]))
  assert.ok($('#custom-slots-unreadable'))
  await m.render(status(8, [threeD]))
  assert.equal($('#custom-slots-unreadable') === null, true); assert.ok($('#custom-slot-0-label'))
  await m.render(status(9, [threeD], [], { custom_slots_supported: false }))
  assert.equal($('#custom-slots') === null, true)
  await m.render(status(10, [threeD]))
  assert.ok($('#custom-slot-0-label'))
  await m.close()
})
test('C1 stale draft dropped when the stored definitions change', async () => {
  const m = await mount(status(7, [threeD]))
  await click('#custom-slot-add'); await type('#custom-slot-1-id', 'video'); await type('#custom-slot-1-label', '영상')
  assert.ok($('#custom-slot-reset'), 'editing')
  await m.render(status(8, [threeD, writing]))
  assert.equal($('#custom-slot-reset') === null, true, 'draft should be dropped')
  assert.equal($('#custom-slot-1-label').value, writing.label)
  assert.equal($('#custom-slot-1-id') === null, true, 'stored row has no id field')
  await m.close()
})
test('C2 preview dropped when the revision changes (same definitions)', async () => {
  const m = await mount(status(7, [threeD]))
  await type('#custom-slot-0-label', '3D 작업'); await click('#custom-slots-check')
  assert.ok($('#custom-slots-apply'))
  await m.render(status(8, [threeD]))
  assert.equal($('#custom-slots-apply') === null, true, 'preview should be dropped'); assert.equal($('#custom-slot-reset') === null, true)
  assert.equal($('#custom-slot-0-label').value, threeD.label)
  await m.close()
})
test('C3 same status object re-rendered keeps the draft', async () => {
  const m = await mount(status(7, [threeD]))
  await type('#custom-slot-0-label', '3D 작업')
  await m.render(status(7, [threeD]))
  assert.equal($('#custom-slot-0-label').value, '3D 작업'); assert.ok($('#custom-slot-reset'))
  await m.close()
})
test('C4 success message survives the reload after apply', async () => {
  const m = await mount(status(7, [threeD]))
  await type('#custom-slot-0-label', '3D 작업'); await click('#custom-slots-check'); await click('#custom-slots-apply')
  await m.render(status(8, [{ ...threeD, label: '3D 작업' }]))
  assert.match($('#custom-slots-message')?.textContent || '', /저장했습니다/)
  assert.equal($('#custom-slot-0-label').value, '3D 작업'); assert.equal($('#custom-slot-reset') === null, true)
  await m.close()
})
test('C5 a check in flight while the status reloads (race)', async () => {
  let release
  const m = await mount(status(7, [threeD]), (p) => p === '/apply' ? { status: 'applied' } : new Promise(r => { release = () => r({ plan_id: 'late-plan', changes: [] }) }))
  await type('#custom-slot-0-label', '3D 작업')
  const el = $('#custom-slots-check'); await React.act(async () => { el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })) })
  await m.render(status(8, [threeD, writing]))
  await React.act(async () => { release(); await sleep(5) }); await tick()
  // The late plan belonged to the dropped draft: no preview, the reloaded definitions shown.
  assert.equal($('#custom-slots-apply') === null, true)
  assert.equal(document.querySelectorAll('article').length, 2)
  await m.close()
})
test('E1 with no saved custom slots the section is editable and adds a slot', async () => {
  const m = await mount(status(3, []))
  assert.equal($('#custom-slots-unreadable') === null, true, 'an empty list is not unreadable')
  await click('#custom-slot-add')
  // A definition is an ID, a name and a description: there is nothing else to choose.
  const inputs = [...document.querySelectorAll('#custom-slot-0 input')].map(el => el.id)
  assert.deepEqual(inputs, ['custom-slot-0-id', 'custom-slot-0-label', 'custom-slot-0-description'])
  assert.doesNotMatch(document.getElementById('root').textContent, /Heavy|Light|긴 작업|짧은 작업/)
  await type('#custom-slot-0-id', 'video-edit'); await type('#custom-slot-0-label', '영상 편집'); await type('#custom-slot-0-description', 'FFmpeg 조립과 자막 검수')
  await click('#custom-slots-check')
  assert.deepEqual(m.calls, [{ path: '/custom-slots-preview', body: { expected_revision: 3, custom_slots: [{ id: 'custom:video-edit', label: '영상 편집', description: 'FFmpeg 조립과 자막 검수' }] } }])
  await m.close()
})
test('D1 ExecutionRow names a model run by its slot: a custom one by its label, an unknown one as such', async () => {
  document.getElementById('root').innerHTML = ''
  const host = document.createElement('div'); document.getElementById('root').appendChild(host); const root = createRoot(host)
  const row = { id: 'r1', execution_mode: 'native', status: 'running',
    requested: { kind: 'model', profile: null, purpose: threeD.id, slot: threeD.id, slot_label: threeD.label, evidence: 'unknown' },
    observed: { kind: 'model', profile: null, slot: threeD.id, backend: 'model-router', model: null, provider: null, evidence: 'runtime_reported' } }
  await React.act(async () => root.render(jsx(api.ExecutionRow, { row })))
  assert.equal(host.querySelector('article span').textContent, '모델 · 3D·그래픽')
  const builtin = { ...row, requested: { kind: 'model', profile: null, purpose: 'plan', slot: 'design', evidence: 'unknown' },
    observed: { ...row.observed, slot: 'design' } }
  await React.act(async () => root.render(jsx(api.ExecutionRow, { row: builtin })))
  assert.equal(host.querySelector('article span').textContent, '모델 · 설계')
  const unknownSlot = { ...row, requested: { kind: 'model', profile: null, purpose: null, slot: null, evidence: 'unknown' },
    observed: { kind: 'unknown', profile: null, slot: null, backend: null, model: null, provider: null, evidence: 'unknown' } }
  await React.act(async () => root.render(jsx(api.ExecutionRow, { row: unknownSlot })))
  assert.equal(host.querySelector('article span').textContent, '모델 · 슬롯 미확인')
  const profileRun = { ...row, requested: { kind: 'profile', profile: 'researcher', purpose: null, slot: null, evidence: 'unknown' }, observed: unknownSlot.observed }
  await React.act(async () => root.render(jsx(api.ExecutionRow, { row: profileRun })))
  assert.equal(host.querySelector('article span').textContent, '프로필 · researcher')
  // No rendered row speaks of the old two-role split.
  for (const item of [row, builtin, unknownSlot, profileRun]) {
    await React.act(async () => root.render(jsx(api.ExecutionRow, { row: item })))
    assert.doesNotMatch(host.textContent, /Heavy|Light/)
  }
  await React.act(async () => root.unmount())
})
test('no React errors while the section renders', () => {
  console.error = origError
  assert.deepEqual(errors, [])
})
