import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const strip = code => code.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
  .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
  .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
const api = new Function('DesktopSDK', `${strip(source)}\nreturn { copyProfileDraft, slotFollowDeclaration, slotRoutingForSave, copyNativeDelegationDraft, readPagedStatus, STATUS_CHANGED_MESSAGE, STATUS_PAGE_LIMIT, TASK_SLOTS, SLOT_FOLLOWS, SLOT_FOLLOW_OPTIONS }`)({})
const ids = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use', 'advise']
const model = { provider: 'fixture', model: 'example', reasoning: 'high' }
const slots = Object.fromEntries(ids.map(id => [id, { follow: 'main', custom: null }]))
const routing = { enabled: true, slots: { design: { follow: 'custom', custom: model } } }

test('a spare model ID may end in one bracketed variant tag, nothing looser', () => {
  const start = source.indexOf('const nativePolicyEntryError')
  const end = source.slice(start).search(/\r?\n}\r?\n/)
  const body = source.slice(start, start + end) + '\n}'
  const check = new Function(`${body}; return nativePolicyEntryError`)()
  const policy = model => ({ mode: 'custom', chain: [{ provider: 'claude-subscription', model }] })
  for (const model of ['claude-opus-5-5[1m]', 'vendor/model:tag[beta.2]', 'plain-model']) assert.equal(check(policy(model)), '', model)
  for (const model of ['[1m]', 'model[]', 'model[1m]x', 'model[1m][2m]', 'model[1 m]', 'model]', 'model[1m']) assert.match(check(policy(model)), /제공자와 모델 ID/, model)
})

test('status is read in pages, joined only when every page describes the same state', async () => {
  const { readPagedStatus, STATUS_CHANGED_MESSAGE, STATUS_PAGE_LIMIT } = api
  const names = ['default', 'a', 'b', 'c', 'd']
  const head = { revision: 7, current_profile: 'default', readiness_context: { base_identity: 'x'.repeat(64) }, slot_capabilities: { schema: 1 }, profile_names: names }
  const row = name => ({ name, models: {} })
  const backend = (overrides = {}) => {
    const sent = []
    const send = async body => {
      sent.push(structuredClone(body))
      const wanted = body.profiles || names
      const page = { ...head, profiles: wanted.slice(0, 2).map(row), pending_profiles: wanted.slice(2) }
      return overrides[sent.length] ? overrides[sent.length](page) : page
    }
    return { sent, send }
  }
  const ok = backend()
  const joined = await readPagedStatus(ok.send)
  assert.deepEqual(ok.sent, [{ paged: true }, { paged: true, profiles: ['b', 'c', 'd'] }, { paged: true, profiles: ['d'] }])
  assert.deepEqual(joined.profiles.map(item => item.name), names)
  assert.equal('pending_profiles' in joined, false); assert.equal('profile_names' in joined, false)
  assert.equal(joined.revision, 7); assert.deepEqual(joined.slot_capabilities, { schema: 1 })
  // A reply that is not paged (one page holds everything, or a test double) is returned as it is.
  const whole = { revision: 1, profiles: [row('default')] }
  assert.equal(await readPagedStatus(async () => whole), whole)
  // An older backend refuses any status body: it is asked once more the old way. Other errors are not retried.
  const old = []
  assert.deepEqual(await readPagedStatus(async body => { old.push(body); if (body.paged) throw Object.assign(new Error('status does not accept a body'), { backendError: 'ValueError' }); return whole }), whole)
  assert.deepEqual(old, [{ paged: true }, {}])
  let attempts = 0
  await assert.rejects(readPagedStatus(async () => { attempts++; throw Object.assign(new Error('boom'), { backendError: 'ServiceError' }) }), /boom/)
  await assert.rejects(readPagedStatus(async () => { attempts++; throw new Error('cut') }), /cut/)
  assert.equal(attempts, 2)
  // Any page that describes a different state, or does not move forward, joins nothing.
  const broken = {
    revision: page => ({ ...page, revision: 8 }),
    installation: page => ({ ...page, readiness_context: { base_identity: 'y'.repeat(64) } }),
    'profile list': page => ({ ...page, profile_names: [...names, 'new'] }),
    'other rows': page => ({ ...page, profiles: [row('a'), row('b')] }),
    'empty page': page => ({ ...page, profiles: [], pending_profiles: ['b', 'c', 'd'] }),
    'lost profile': page => ({ ...page, pending_profiles: [] }),
    'no pending list': page => ({ ...page, pending_profiles: undefined }),
    'null reply': () => null
  }
  for (const [label, change] of Object.entries(broken)) {
    const bad = backend({ 2: change })
    await assert.rejects(readPagedStatus(bad.send), error => error.message === STATUS_CHANGED_MESSAGE, label)
    assert.equal(bad.sent.length, 2, label)
  }
  const firstBad = backend({ 1: page => ({ ...page, pending_profiles: ['c', 'd'] }) })
  await assert.rejects(readPagedStatus(firstBad.send), error => error.message === STATUS_CHANGED_MESSAGE)
  assert.equal(firstBad.sent.length, 1)
  // A backend that never finishes is cut off.
  let calls = 0
  const many = Array.from({ length: STATUS_PAGE_LIMIT + 5 }, (_, index) => 'p' + index)
  await assert.rejects(readPagedStatus(async body => { calls++; const wanted = body.profiles || many; return { revision: 1, profile_names: many, profiles: [row(wanted[0])], pending_profiles: wanted.slice(1) } }), error => error.message === STATUS_CHANGED_MESSAGE)
  assert.equal(calls, STATUS_PAGE_LIMIT + 1)
})

test('slot draft seeding clones all declarations independently of loaded status', () => {
  const row = { models: { main: model }, routing, slots: { declarations: slots } }
  const draft = api.copyProfileDraft(row)
  assert.deepEqual(draft.slots, slots)
  assert.deepEqual(draft.routing, routing)
  draft.slots.design.follow = 'custom'
  draft.routing.slots.design.custom.model = 'changed'
  assert.equal(row.slots.declarations.design.follow, 'main')
  assert.equal(row.routing.slots.design.custom.model, 'example')
})

test('a slot follows the main model or a model set here, nothing else', () => {
  assert.deepEqual(api.SLOT_FOLLOWS, ['main', 'custom'])
  assert.deepEqual(api.SLOT_FOLLOW_OPTIONS.map(option => option.value), ['main', 'custom'])
  const custom = api.slotFollowDeclaration({ follow: 'main', custom: null }, 'custom', { main: model })
  assert.deepEqual(custom, { follow: 'custom', custom: model })
  assert.notEqual(custom.custom, model)
  assert.deepEqual(api.slotFollowDeclaration(custom, 'main', { main: model }), { follow: 'main', custom: null })
  for (const follow of ['delegation', 'other', '']) assert.throws(() => api.slotFollowDeclaration(custom, follow, { main: model }), /invalid slot basis/)
})

test('the routing a save sends is {enabled, slots} only', () => {
  const draft = { routing, slots }
  // full form: the drafted declarations while editable, otherwise the stored slots as loaded
  assert.deepEqual(api.slotRoutingForSave(draft, true), { enabled: true, slots })
  assert.deepEqual(api.slotRoutingForSave(draft, false), { enabled: true, slots: routing.slots })
  assert.deepEqual(api.slotRoutingForSave({ routing: { enabled: false } }, false), { enabled: false, slots: {} })
  // partial form: only the named slots, none leaves the key out
  assert.deepEqual(api.slotRoutingForSave(draft, true, ['code-simple']), { enabled: true, slots: { 'code-simple': slots['code-simple'] } })
  assert.deepEqual(api.slotRoutingForSave(draft, true, []), { enabled: true })
  assert.deepEqual(api.slotRoutingForSave(draft, false, ['design']), { enabled: true })
  const sent = api.slotRoutingForSave(draft, true)
  sent.slots.design.follow = 'custom'
  assert.equal(slots.design.follow, 'main', 'a copy, never the draft itself')
})

test('native spare-model drafts are per slot only', () => {
  const policy = Object.fromEntries(ids.map(id => [id, { mode: 'off', chain: [] }]))
  const dto = { schema: 1, supported: true, digest: 'fake', backend: 'model-router', profile_routes: { profiles: [], default: null }, slot_policy: policy, auto_slot_policy: policy, policy_schema: 2 }
  const draft = api.copyNativeDelegationDraft(dto)
  assert.deepEqual(Object.keys(draft).sort(), ['allowProfileAccess', 'autoSlotPolicy', 'backend', 'descriptionEdits', 'expectedDigest', 'profile_routes', 'slotPolicy'])
  draft.slotPolicy.design.mode = 'custom'
  assert.equal(dto.slot_policy.design.mode, 'off')
  assert.equal(draft.autoSlotPolicy.design.mode, 'off')
})

test('the advisor slot is the last and labelled with its own fixed limit; a slot has only its own fields', () => {
  assert.deepEqual(api.TASK_SLOTS.map(slot => slot.id), ids)
  for (const slot of api.TASK_SLOTS) assert.deepEqual(Object.keys(slot).filter(key => !['id', 'label', 'description', 'limitLabel', 'fixedLimit'].includes(key)), [], slot.id)
  const advise = api.TASK_SLOTS.at(-1)
  assert.equal(advise.limitLabel, '5분 고정 제한')
  assert.equal(advise.fixedLimit, true)
  assert.match(advise.description, /ask_advisor/)
  assert.ok(api.TASK_SLOTS.slice(0, -1).every(slot => slot.limitLabel === undefined && slot.fixedLimit === undefined))
  // A card's badge is the slot's own saved limit (or the 2-hour default), from the time-limit section.
  assert.match(source, /const limit = slot\.limitLabel \|\| slots\.limitText\?\.\(slot\.id\) \|\| ''/)
})
