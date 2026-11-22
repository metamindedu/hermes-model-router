import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Hermes-native model settings (status `model_settings_schema: 1`) through the real RouterPage
// handlers with in-memory hooks and a fake transport only. No DOM, profile, settings or Hermes write.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const slotIds = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use']
const slotTiers = Object.fromEntries(slotIds.map(id => [id, ['design', 'verify-complex'].includes(id) ? 'heavy' : 'light']))
const offSlots = () => Object.fromEntries(slotIds.map(id => [id, { mode: 'off', chain: [] }]))
const declarations = () => Object.fromEntries(slotIds.map(id => [id, { follow: 'main', custom: null }]))
const role = (state = 'verified', source = 'explicit', editable = true, reason = '') => ({ state, source, editable, reason })
const nativeFallback = () => ({ managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null })
const rowModels = name => ({
  main: route('openai-codex', `${name}-main`, 'medium'),
  delegation: route('openai-codex', `${name}-delegate`, 'max'),
  compression: route('openai-codex', `${name}-compression`, 'medium'),
  title: route('openai-codex', `${name}-main`, 'medium')
})
// One native projection for `models` and `actual_models`; the title role is inherited from main.
const nativeRow = name => ({ name, models: rowModels(name), actual_models: rowModels(name),
  model_roles: { main: role(), delegation: role(), compression: role(), title: role('verified', 'inherited') },
  routing: { enabled: name === 'claire', heavy: { follow: 'main', custom: null }, light: { follow: 'main', custom: null }, fallback: { enabled: false, heavy: null, light: null } },
  drift: [], slots: { schema: 1, capable: true, stored: [], declarations: declarations() },
  fallbacks: { native: nativeFallback() },
  native_delegation: { schema: 1, supported: true, editable: true, backend: 'default', digest: 'a'.repeat(64),
    policy: { heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } },
    slot_policy: offSlots(), auto_slot_policy: offSlots(), policy_schema: 0, auto_policy_schema: 0, slot_policy_supported: true,
    profile_routes: { profiles: [], default: null }, role_intro_inheritance: { schema: 1, supported: true, code_identity: 'e'.repeat(64), activation: 'new_session_or_supported_rebuild' }, warnings: [] },
  role_intro: { schema: 1, state: 'available', default_description: `Role of ${name}`, default_source: 'profile_metadata', description_auto: false, digest: 'f'.repeat(64) } })
const nativeStatus = () => ({ model_settings_schema: 1, revision: 7, current_profile: 'claire', recent_apply: null,
  readiness_context: { schema: 1, base_identity: 'd'.repeat(64), source_profile: 'claire', release: null },
  fallback_capabilities: { native_trigger: 'hermes_runtime', native_execution: 'continue_conversation', native_reasoning: 'profile_overrides',
    routing_trigger: 'subscription_exhaustion_before_tools', routing_execution: 'fresh_task', routing_max_retries: 1 },
  slot_capabilities: { schema: 1, slots: slotIds, tiers: slotTiers, purposes: {}, follows: ['main', 'delegation', 'custom'], blocking_profiles: [] },
  profiles: ['default', 'claire', 'other'].map(nativeRow) })
// The same rows from a service before Hermes-native model settings: no root key, no role metadata.
const olderStatus = () => {
  const data = nativeStatus()
  delete data.model_settings_schema
  for (const row of data.profiles) delete row.model_roles
  return data
}

function* walk(node) {
  if (Array.isArray(node)) { for (const item of node) yield* walk(item); return }
  if (!node || typeof node !== 'object') return
  yield node
  yield* walk(node.props?.children)
}
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(text).join(' ')
  return node?.props ? text(node.props.children) : ''
}
function setupStorage() {
  const values = new Map()
  return { get(key, fallback = null) { return values.has(key) ? structuredClone(values.get(key)) : fallback }, set(key, value) { values.set(key, structuredClone(value)) } }
}
function harness(initial = nativeStatus()) {
  const pluginContext = { storage: setupStorage() }
  let data = structuredClone(initial), cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = [], cleanups = new Map()
  const state = Object.fromEntries(Object.entries({ profile: 'claire', connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  let responder = operation => operation === 'apply' ? { status: 'applied', revision: 8 } : { plan_id: `${operation}-plan`, changes: [], warnings: [] }
  const host = { state, request: async (method, args) => {
    const index = args.argv.indexOf('model-router'), operation = args.argv[index + 1]
    const body = JSON.parse(args.argv.at(-1))
    calls.push({ method, operation, body })
    const result = await (operation === 'status' ? structuredClone(data) : responder(operation, body))
    return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(result)}\n` }
  } }
  const gatewayInstance = { request: (method, args) => host.request(method, args) }
  host.getGateway = () => gatewayInstance
  host.profileRoutes = async () => ['default', 'claire', 'other'].map(profile => ({ mode: 'local', connectionId: 'local', profile, targetProfile: profile, primary: profile === 'claire' }))
  host.requestProfile = async (descriptor, method, args) => host.request(method, args)
  const useState = value => {
    const index = cursor++
    if (!(index in hooks)) hooks[index] = typeof value === 'function' ? value() : value
    return [hooks[index], next => {
      const resolved = typeof next === 'function' ? next(hooks[index]) : next
      if (!Object.is(hooks[index], resolved)) { hooks[index] = resolved; dirty = true }
    }]
  }
  const useRef = value => { const index = cursor++; return hooks[index] ??= { current: value } }
  const useEffect = (fn, deps) => {
    const index = cursor++, before = hooks[index]
    if (!before || !deps || deps.some((value, at) => !Object.is(value, before[at]))) {
      hooks[index] = deps; effects.push(() => {
        cleanups.get(index)?.()
        const cleanup = fn()
        if (typeof cleanup === 'function') cleanups.set(index, cleanup)
        else cleanups.delete(index)
      })
    }
  }
  const query = { get data() { return data }, isPending: false, isError: false, isFetching: false, refetch: async () => ({ data }) }
  const jsx = (type, props = {}) => typeof type === 'function' ? type(props) : { type, props }
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
    for (const name of match[1].split(',').map(item => item.trim()).filter(Boolean)) imports[name] = name
  }
  Object.assign(imports, { DesktopSDK: {}, useState, useRef, useEffect, jsx, jsxs: jsx, host, useValue: atom => atom.get(), useQuery: () => query })
  const executable = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
    .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const moduleApi = new Function(...Object.keys(imports), `${executable}\nreturn { RouterPage, pluginDefinition, refreshCleanModelState, pageExpectationsFor, buildPreviewBody }`)(...Object.values(imports))
  moduleApi.pluginDefinition.register({ ...pluginContext, registerSettingsPage() {}, registerMany() {} })
  const render = () => {
    for (let attempt = 0; attempt < 20; attempt++) {
      dirty = false; cursor = 0; tree = moduleApi.RouterPage({ ctx: pluginContext })
      for (const effect of effects.splice(0)) effect()
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  const find = predicate => { const node = [...walk(tree)].find(predicate); assert.ok(node, 'Control not found'); return node }
  const byId = id => find(node => node.props?.id === id)
  const flush = async () => { for (let at = 0; at < 40; at++) await Promise.resolve(); render() }
  render()
  return { calls, api: moduleApi, render, byId, flush, get tree() { return tree }, data: () => data,
    setData(next) { data = next }, setResponder(fn) { responder = fn },
    click(id) { const node = byId(id); assert.ok(!node.props.disabled, `${id} should be enabled`); node.props.onClick(); render() },
    input(id, value) { byId(id).props.onChange({ target: { value } }); render() },
    selectValue(id) { return find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.value },
    select(id, value) { find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.onValueChange(value); render() } }
}
// An external change made somewhere else at the same store revision (Hermes config is not the store).
function changeElsewhere(h, edit) {
  const next = structuredClone(h.data())
  edit(next, name => next.profiles.find(row => row.name === name))
  h.setData(next); h.render()
}
const setRole = (row, roleId, value) => { row.models[roleId] = structuredClone(value); row.actual_models[roleId] = structuredClone(value) }
const ops = h => h.calls.map(call => call.operation)
const previews = h => h.calls.filter(call => call.operation === 'preview').map(call => call.body)

test('an older gateway without the capability keeps the whole-mapping wire and whole frozen expectations', async () => {
  const h = harness(olderStatus())
  const frozen = structuredClone(h.data().profiles.find(row => row.name === 'claire'))
  h.input('model-compression-model', 'compression-edit')
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(ops(h).slice(0, 2), ['preview', 'apply'])
  const [body] = previews(h)
  assert.equal('model_settings_schema' in body, false)
  assert.deepEqual(Object.keys(body.models).sort(), ['compression', 'main', 'title'])
  assert.equal(body.models.compression.model, 'compression-edit')
  const expected = body.expected.find(item => item.profile === 'claire')
  assert.deepEqual(expected.models, frozen.models, 'every role, as loaded')
  assert.deepEqual(expected.actual_models, frozen.actual_models)
  // ...and an external change on an unedited role still blocks, as before.
  const g = harness(olderStatus())
  g.input('model-compression-model', 'compression-edit')
  changeElsewhere(g, (_, row) => setRole(row('claire'), 'main', route('elsewhere', 'other-main', 'high')))
  assert.equal(g.byId('model-section-save').props.disabled, true)
  assert.match(text(g.byId('live-drift-alert')), /claire 프로필의 대화·작업 모델/)
})

test('a clean draft follows a newer native status by itself, with nothing to save and no request', () => {
  const h = harness()
  assert.equal(h.byId('model-section-save').props.disabled, true, 'nothing edited')
  changeElsewhere(h, (_, row) => {
    setRole(row('claire'), 'main', route('elsewhere', 'new-main', 'high'))
    setRole(row('other'), 'compression', route('elsewhere', 'other-compression', 'low'))
  })
  assert.equal(h.byId('model-main-model').props.value, 'new-main')
  assert.equal(h.byId('model-main-provider').props.value, 'elsewhere')
  assert.throws(() => h.byId('live-drift-alert'), 'an ordinary external edit is not a conflict')
  assert.equal(h.byId('model-section-save').props.disabled, true, 'following the status is not an edit')
  assert.doesNotMatch(text(h.tree), /저장 설정과 실제 설정이 다릅니다/)
  assert.deepEqual(h.calls, [])
})

test('an external change of the edited role blocks before any request, also through a retained callback', async () => {
  const h = harness()
  h.input('model-compression-model', 'compression-edit')
  const retained = h.byId('model-section-save').props.onClick
  const retainedAll = h.byId('global-save').props.onClick
  changeElsewhere(h, (_, row) => setRole(row('claire'), 'compression', route('elsewhere', 'external-compression', 'low')))
  assert.equal(h.byId('model-compression-model').props.value, 'compression-edit', 'the edit is never rebased')
  assert.match(text(h.byId('live-drift-alert')), /claire 프로필의 압축 모델/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.equal(h.byId('global-save').props.disabled, true)
  retained(); retainedAll(); await h.flush()
  assert.deepEqual(h.calls, [], 'nothing sent')
})

test('an unrelated role changed elsewhere neither blocks the edited role nor is sent', async () => {
  const h = harness()
  const frozenCompression = structuredClone(h.data().profiles.find(row => row.name === 'claire').models.compression)
  h.input('model-compression-model', 'compression-edit')
  const retained = h.byId('model-section-save').props.onClick
  changeElsewhere(h, (_, row) => setRole(row('claire'), 'main', route('elsewhere', 'new-main', 'high')))
  assert.equal(h.byId('model-main-model').props.value, 'new-main', 'the clean role follows the status')
  assert.throws(() => h.byId('live-drift-alert'))
  assert.equal(h.byId('model-section-save').props.disabled, false)
  // The callback kept from before the change still sends only the edited role.
  retained(); await h.flush()
  assert.deepEqual(ops(h).slice(0, 2), ['preview', 'apply'])
  const [body] = previews(h)
  assert.equal(body.model_settings_schema, 1)
  assert.deepEqual(body.models, { compression: { ...frozenCompression, model: 'compression-edit' } })
  assert.deepEqual(body.model_targets, ['claire'])
  assert.deepEqual(body.expected, [{ profile: 'claire', models: { compression: frozenCompression }, actual_models: { compression: frozenCompression } }])
  assert.deepEqual(h.calls[1].body, { plan_id: 'preview-plan' }, 'the apply token is sent unchanged')
  assert.equal('fallback_updates' in body, false)
  // The whole-page save sends the same partial mapping and per-role expectation.
  const w = harness()
  w.input('model-compression-model', 'compression-edit')
  changeElsewhere(w, (_, row) => setRole(row('claire'), 'title', route('elsewhere', 'new-title', 'none')))
  w.click('global-save'); await w.flush()
  const [whole] = previews(w)
  assert.equal(whole.model_settings_schema, 1)
  assert.deepEqual(Object.keys(whole.models), ['compression'])
  assert.deepEqual(whole.expected.find(item => item.profile === 'claire').models, { compression: frozenCompression })
  // A slot save is not blocked by an unrelated role either.
  const slotData = nativeStatus()
  for (const row of slotData.profiles) row.native_delegation.backend = 'model-router'
  const g = harness(slotData)
  g.select('slot-design-follow', 'custom')
  changeElsewhere(g, (_, row) => setRole(row('claire'), 'title', route('elsewhere', 'new-title', 'none')))
  assert.throws(() => g.byId('live-drift-alert'))
  assert.equal(g.byId('model-section-save').props.disabled, false)
})

test('explicit copy sends every copyable role with per-target frozen subsets; no edit and no copy sends nothing', async () => {
  const data = nativeStatus()
  // An unverified role is not copied without an edit; title is inherited.
  data.profiles.find(row => row.name === 'claire').model_roles.compression = role('unverified')
  const h = harness(data)
  assert.equal(h.byId('model-section-save').props.disabled, true, 'no-op: nothing to save')
  h.click('model-target-all')
  h.click('model-section-save'); await h.flush()
  const [body] = previews(h)
  assert.equal(body.model_settings_schema, 1)
  assert.deepEqual(Object.keys(body.models), ['main'])
  assert.deepEqual(body.model_targets, ['default', 'claire', 'other'])
  const expected = Object.fromEntries(body.expected.map(item => [item.profile, item]))
  for (const name of ['default', 'claire', 'other']) {
    const loaded = data.profiles.find(row => row.name === name)
    assert.deepEqual(expected[name].models, { main: loaded.models.main }, `${name}: its own frozen value, main only`)
    assert.deepEqual(expected[name].actual_models, { main: loaded.actual_models.main })
  }
  // During copy intent every copied role stays frozen in every target: a change elsewhere blocks.
  const g = harness(data)
  g.click('model-target-all')
  changeElsewhere(g, (_, row) => setRole(row('other'), 'main', route('elsewhere', 'other-new-main', 'high')))
  assert.match(text(g.byId('live-drift-alert')), /other 프로필의 대화 모델/)
  assert.equal(g.byId('model-section-save').props.disabled, true)
})

test('an edited inherited role is sent explicitly; unresolved and managed roles are shown truthfully and read-only', async () => {
  const data = nativeStatus()
  const claire = data.profiles.find(row => row.name === 'claire')
  claire.model_roles.compression = role('verified', 'explicit', false, 'managed_overlay')
  delete claire.models.main; delete claire.actual_models.main; delete claire.model_roles.main
  claire.drift = ['models.title']
  const h = harness(data)
  assert.equal(h.byId('model-main-model').props.value || '', '', 'no placeholder for an unresolved role')
  assert.equal(h.byId('model-main-model').props.disabled, true)
  assert.match(text(h.byId('model-main-native-state')), /확인할 수 없습니다/)
  assert.equal(h.byId('model-compression-model').props.disabled, true)
  assert.match(text(h.byId('model-compression-native-state')), /바꿀 수 없는 설정입니다\(managed_overlay\)/)
  assert.match(text(h.byId('model-title-native-state')), /물려받은 값/)
  assert.doesNotMatch(text(h.tree), /저장 설정과 실제 설정이 다릅니다/, 'no false re-save notice')
  h.input('model-title-model', 'explicit-title')
  h.click('model-section-save'); await h.flush()
  const [body] = previews(h)
  assert.deepEqual(Object.keys(body.models), ['title'])
  assert.equal(body.models.title.model, 'explicit-title')
})

test('a clean conversation spare-model chain follows the status without a write, consent or blocking', async () => {
  const h = harness()
  assert.equal(h.selectValue('native-fallback-mode'), 'off')
  changeElsewhere(h, (_, row) => {
    const native = row('claire').fallbacks.native
    native.enabled = true; native.chain = [route('elsewhere', 'spare-elsewhere')]; native.actual_chain = structuredClone(native.chain)
    delete native.chain[0].reasoning; delete native.actual_chain[0].reasoning
  })
  assert.equal(h.selectValue('native-fallback-mode'), 'custom')
  assert.equal(h.byId('native-chain-0-model').props.value, 'spare-elsewhere')
  assert.throws(() => h.byId('live-drift-alert'))
  assert.equal(h.byId('model-section-save').props.disabled, true, 'following the chain is not an edit')
  h.input('model-compression-model', 'compression-edit')
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(ops(h).slice(0, 2), ['preview', 'apply'], 'no spare-model step')
  const [body] = previews(h)
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
  assert.deepEqual(body.expected.map(item => Object.keys(item).sort()), [['actual_models', 'models', 'profile']])
})

test('an edited spare-model chain stays frozen; a change elsewhere blocks only that save', () => {
  const h = harness()
  h.select('native-fallback-mode', 'custom')
  h.input('native-chain-0-provider', 'mine'); h.input('native-chain-0-model', 'my-spare')
  changeElsewhere(h, (_, row) => {
    const native = row('claire').fallbacks.native
    native.enabled = true; native.chain = [{ provider: 'elsewhere', model: 'external-spare' }]; native.actual_chain = structuredClone(native.chain)
  })
  assert.equal(h.byId('native-chain-0-model').props.value, 'my-spare', 'never rebased')
  assert.match(text(h.byId('live-drift-alert')), /대화 예비 모델/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.deepEqual(h.calls, [])
})

test('a refresh during a pending save changes neither the captured roles nor the frozen expectations', async () => {
  const h = harness()
  const frozen = structuredClone(h.data().profiles.find(row => row.name === 'claire').models.compression)
  let finish
  h.setResponder(operation => operation === 'preview' ? new Promise(resolve => { finish = resolve }) : { status: 'applied', revision: 8 })
  h.input('model-compression-model', 'compression-edit')
  h.click('model-section-save'); await h.flush()
  changeElsewhere(h, (_, row) => setRole(row('claire'), 'main', route('elsewhere', 'new-main', 'high')))
  finish({ plan_id: 'captured-plan', changes: [], warnings: [] }); await h.flush()
  assert.deepEqual(ops(h).slice(0, 2), ['preview', 'apply'])
  assert.deepEqual(previews(h)[0].models, { compression: { ...frozen, model: 'compression-edit' } })
  assert.deepEqual(h.calls[1].body, { plan_id: 'captured-plan' })
})

test('helpers: the refresh holds edited roles in every profile and the expectation covers exactly the sent roles', () => {
  const h = harness()
  const rows = nativeStatus().profiles
  const baselines = Object.fromEntries(rows.map(row => [row.name, { models: structuredClone(row.models), routing: structuredClone(row.routing) }]))
  const expectations = Object.fromEntries(rows.map(row => [row.name, { models: structuredClone(row.models), actual_models: structuredClone(row.actual_models), routing: {} }]))
  const live = structuredClone(rows)
  for (const row of live) { setRole(row, 'main', route('x', `${row.name}-live-main`, 'low')); setRole(row, 'compression', route('x', `${row.name}-live-compression`, 'low')) }
  const draft = { models: { ...structuredClone(rows[1].models), compression: route('mine', 'edit', 'low') }, routing: {} }
  const next = h.api.refreshCleanModelState({ rows: live, selected: 'claire', draft, profileBaselines: baselines, expectationBaselines: expectations, heldRoles: ['compression'] })
  assert.equal(next.draft.models.main.model, 'claire-live-main')
  assert.equal(next.draft.models.compression.model, 'edit')
  for (const row of rows) {
    assert.equal(next.profileBaselines[row.name].models.compression.model, `${row.name}-compression`, 'held role frozen')
    assert.equal(next.expectationBaselines[row.name].actual_models.main.model, `${row.name}-live-main`, 'clean role refreshed')
  }
  const same = h.api.refreshCleanModelState({ rows: live, selected: 'claire', draft: next.draft, profileBaselines: next.profileBaselines, expectationBaselines: next.expectationBaselines, heldRoles: ['compression'] })
  assert.equal(same.changed, false, 'settles without another change')
  const body = h.api.buildPreviewBody(7, 'claire', next.draft, ['claire', 'other'], ['claire'], undefined, ['compression'])
  assert.equal(body.model_settings_schema, 1)
  assert.deepEqual(Object.keys(body.models), ['compression'])
  const expected = h.api.pageExpectationsFor('/preview', { ...body, save_scope: 'models' }, next.expectationBaselines, [])
  assert.deepEqual(expected.map(item => [item.profile, Object.keys(item.models), Object.keys(item.actual_models)]),
    [['claire', ['compression'], ['compression']], ['other', ['compression'], ['compression']]])
  const withoutModels = h.api.buildPreviewBody(7, 'claire', next.draft, [], ['claire'], undefined, ['compression'])
  assert.equal(withoutModels.model_settings_schema, 1)
  assert.deepEqual(withoutModels.models, {}, 'a native non-model save carries no incidental roles')
})

// Hidden endpoint protection lives in the service (no compare token on the wire): the page never
// sends token fields, even when a status row carries stray ones, and the role-scoped CAS still holds.
test('a native save sends no token fields; a stale edited role blocks and an unrelated role does not', async () => {
  const data = nativeStatus()
  data.model_role_token_schema = 1
  for (const row of data.profiles) row.model_role_tokens = { main: `mrt1.${'1'.repeat(64)}` }
  const h = harness(data)
  h.input('model-compression-model', 'compression-edit')
  const retained = h.byId('model-section-save').props.onClick
  changeElsewhere(h, (_, row) => { row('claire').models.compression = { ...row('claire').models.compression, model: 'outside' }; row('claire').actual_models.compression = { ...row('claire').models.compression } })
  assert.match(text(h.byId('live-drift-alert')), /claire 프로필의 압축 모델/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  retained(); await h.flush()
  assert.deepEqual(h.calls, [], 'nothing sent over a changed edited role')

  const g = harness(nativeStatus())
  g.input('model-compression-model', 'compression-edit')
  changeElsewhere(g, (_, row) => { row('claire').models.main = { ...row('claire').models.main, model: 'outside-main' }; row('claire').actual_models.main = { ...row('claire').models.main } })
  assert.throws(() => g.byId('live-drift-alert'))
  g.click('model-section-save'); await g.flush()
  const [body] = previews(g)
  assert.equal('model_role_token_schema' in body, false)
  assert.deepEqual(Object.keys(body.models), ['compression'])
  const expected = body.expected.find(item => item.profile === 'claire')
  assert.equal('model_role_tokens' in expected, false)
  assert.deepEqual(Object.keys(expected.models), ['compression'])
})
