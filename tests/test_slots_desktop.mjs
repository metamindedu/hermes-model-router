import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const strip = code => code.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
  .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
  .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
const api = new Function('DesktopSDK', `${strip(source)}\nreturn { copyProfileDraft, slotFollowDeclaration, slotRoutingForSave, copyNativeDelegationDraft }`)({})
const ids = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use']
const model = { provider: 'fixture', model: 'example', reasoning: 'high' }
const slots = Object.fromEntries(ids.map(id => [id, { follow: 'main', custom: null }]))
const routing = { enabled: true, heavy: { follow: 'main', custom: null }, light: { follow: 'delegation', custom: null }, fallback: { enabled: false, heavy: null, light: null } }

test('slot draft seeding clones all declarations independently of loaded status', () => {
  const row = { models: { main: model }, routing, slots: { declarations: slots } }
  const draft = api.copyProfileDraft(row)
  assert.deepEqual(draft.slots, slots)
  draft.slots.design.follow = 'delegation'
  assert.equal(row.slots.declarations.design.follow, 'main')
})

test('slot basis switching prefills followed model and clears custom when switching away', () => {
  const custom = api.slotFollowDeclaration({ follow: 'main', custom: null }, 'custom', { main: model })
  assert.deepEqual(custom, { follow: 'custom', custom: model })
  assert.notEqual(custom.custom, model)
  assert.deepEqual(api.slotFollowDeclaration(custom, 'delegation', { main: model }), { follow: 'delegation', custom: null })
})

test('slot routing projection preserves legacy routes and omits slots when blocked', () => {
  const draft = { routing: { ...routing, slots: { design: slots.design } }, slots }
  const enabled = api.slotRoutingForSave(draft, true)
  assert.deepEqual(enabled.slots, slots)
  assert.deepEqual(enabled.heavy, routing.heavy)
  assert.deepEqual(enabled.light, routing.light)
  assert.equal(Object.hasOwn(api.slotRoutingForSave(draft, false), 'slots'), false)
})

test('native slot policy drafts are cloned separately from legacy policies', () => {
  const policy = Object.fromEntries(ids.map(id => [id, { mode: 'off', chain: [] }]))
  const dto = { schema: 1, supported: true, digest: 'fake', backend: 'default', policy: { heavy: {}, light: {} }, profile_routes: {}, slot_policy: policy, auto_slot_policy: policy }
  const draft = api.copyNativeDelegationDraft(dto)
  draft.slotPolicy.design.mode = 'custom'
  assert.equal(dto.slot_policy.design.mode, 'off')
  assert.equal(draft.autoSlotPolicy.design.mode, 'off')
})
