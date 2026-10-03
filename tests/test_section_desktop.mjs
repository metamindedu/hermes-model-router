import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const route = (provider, model, reasoning = 'high') => ({ provider, model, reasoning })
const timeoutDto = (revision, delegateTotalSeconds, routedTotalSeconds, editable = true) => ({
  schema: 1, revision, delegate_total_seconds: delegateTotalSeconds,
  routed_total_seconds: routedTotalSeconds, editable, warnings: []
})
const profile = (name, timeouts) => ({
  name,
  models: {
    main: route('fixture-provider', `${name}-main`),
    delegation: route('fixture-provider', `${name}-delegate`),
    compression: route('fixture-provider', `${name}-compression`),
    title: route('fixture-provider', `${name}-title`, 'none')
  },
  actual_models: { main: route('fixture-provider', `${name}-main`), delegation: route('fixture-provider', `${name}-delegate`) },
  routing: {
    enabled: name === 'claire',
    heavy: { follow: 'main', custom: null },
    light: { follow: 'delegation', custom: null },
    fallback: {
      enabled: true,
      heavy: route('saved-heavy-fallback', `${name}-heavy-fallback`),
      light: route('saved-light-fallback', `${name}-light-fallback`)
    }
  },
  fallbacks: {
    native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null },
    routing: { editable: true, enabled: false, heavy: null, light: null, consent: null },
    delegation: { managed: true, editable: true, mode: 'default', chain: [], actual_mode: 'default', actual_chain: [], drift: false, warnings: [], consent: null }
  },
  drift: [], timeouts
})
const statusFixture = () => ({
  revision: 12,
  current_profile: 'claire',
  fallback_capabilities: {
    native_trigger: 'hermes_runtime', native_execution: 'continue_conversation', native_reasoning: 'profile_overrides',
    routing_trigger: 'subscription_exhaustion_before_tools', routing_execution: 'fresh_task', routing_max_retries: 1
  },
  profiles: [
    profile('default', timeoutDto(3, 0, 1800)),
    profile('claire', timeoutDto(8, 0, 3600)),
    profile('other', timeoutDto(11, 12, 7200))
  ]
})

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

function harness(initial = statusFixture()) {
  let data = initial, cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = []
  const state = Object.fromEntries(Object.entries({ profile: 'claire', connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  let responder = operation => operation === 'preview'
    ? { plan_id: 'section-plan', changes: [], warnings: [] }
    : { status: 'applied', revision: 13 }
  const host = { state, request: async (method, args) => {
    const index = args.argv.indexOf('model-router')
    const operation = args.argv[index + 1]
    const body = JSON.parse(args.argv.at(-1))
    calls.push({ method, operation, body, profile: args.profile })
    const result = await responder(operation, body)
    return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(result)}\n` }
  } }
  const useState = initialValue => {
    const index = cursor++
    if (!(index in hooks)) hooks[index] = typeof initialValue === 'function' ? initialValue() : initialValue
    return [hooks[index], value => {
      const next = typeof value === 'function' ? value(hooks[index]) : value
      if (!Object.is(hooks[index], next)) { hooks[index] = next; dirty = true }
    }]
  }
  const useRef = initialValue => { const index = cursor++; return hooks[index] ??= { current: initialValue } }
  const useEffect = (fn, deps) => {
    const index = cursor++, previous = hooks[index]
    if (!previous || !deps || deps.some((value, at) => !Object.is(value, previous[at]))) {
      hooks[index] = deps
      effects.push(fn)
    }
  }
  const query = { get data() { return data }, isPending: false, isError: false, isFetching: false,
    refetch: async () => ({ data }) }
  const jsx = (type, props = {}) => typeof type === 'function' ? type(props) : { type, props }
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
    for (const name of match[1].split(',').map(value => value.trim()).filter(Boolean)) imports[name] = name
  }
  Object.assign(imports, { useState, useRef, useEffect, jsx, jsxs: jsx, host,
    useValue: atom => atom.get(), useQuery: () => query })
  const executable = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const RouterPage = new Function(...Object.keys(imports), `${executable}\nreturn RouterPage`)(...Object.values(imports))
  const render = () => {
    for (let attempt = 0; attempt < 30; attempt++) {
      dirty = false; cursor = 0; tree = RouterPage({ ctx: {} })
      for (const effect of effects.splice(0)) effect()
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  const find = predicate => {
    const node = [...walk(tree)].find(predicate)
    assert.ok(node, 'Control not found')
    return node
  }
  const byId = id => find(node => node.props?.id === id)
  const flush = async () => { for (let index = 0; index < 40; index++) await Promise.resolve(); render() }
  const click = id => {
    const node = byId(id)
    assert.ok(!node.props.disabled, `${id} should be enabled`)
    const result = node.props.onClick?.()
    render()
    return result
  }
  const clickLabel = label => {
    const node = find(item => item.type === 'Button' && text(item).includes(label))
    assert.ok(!node.props.disabled, `${label} should be enabled`)
    const result = node.props.onClick?.()
    render()
    return result
  }
  const input = (id, value) => {
    const node = byId(id)
    assert.ok(!node.props.disabled, `${id} should be enabled`)
    node.props.onChange({ target: { value } })
    render()
  }
  const check = (id, checked) => {
    const node = byId(id)
    assert.ok(!node.props.disabled, `${id} should be enabled`)
    node.props.onCheckedChange(checked)
    render()
  }
  const select = (id, value) => {
    const node = find(item => item.type === 'Select' && [...walk(item)].some(child => child.props?.id === id))
    node.props.onValueChange(value)
    render()
  }
  const selectProfile = name => select('profile-select', name)
  render()
  return {
    calls, state, render, byId, click, clickLabel, input, check, select, selectProfile, flush,
    get tree() { return tree },
    data: () => data,
    setData(value) { data = value },
    setResponder(fn) { responder = fn }
  }
}

function profileRow(h, name) { return h.data().profiles.find(row => row.name === name) }
function lastPreview(h) { return h.calls.filter(call => call.operation === 'preview').at(-1) }
function expectedTimeout(profileName, revision, delegate, routed) {
  return { profile: profileName, expected_revision: revision, delegate_total_seconds: delegate, routed_total_seconds: routed }
}


test('timeout targets default to eligible profiles and manual empty selection survives profile changes and refresh without copy intent', async () => {
  const h = harness()
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`timeout-target-${name}`).props.checked, true)
  h.click('timeout-target-none')
  h.selectProfile('other')
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`timeout-target-${name}`).props.checked, false)
  h.setData(structuredClone(h.data()))
  await h.clickLabel('상태 새로고침')
  await h.flush()
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`timeout-target-${name}`).props.checked, false)
  assert.doesNotMatch(text(h.tree), /전체 저장에 복사 의도 포함/)
  h.input('model-main-model', 'models-only-after-refresh')
  await h.click('global-save')
  await h.flush()
  assert.equal('timeout_updates' in lastPreview(h).body, false)
})

test('timeout target eligibility is DTO-backed; source-only and manual nonempty subset survive source changes and refresh', async () => {
  const data = statusFixture()
  data.profiles.push(profile('readonly', timeoutDto(15, 99, 99, false)))
  data.profiles.push(profile('unsupported', undefined))
  const h = harness(data)
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`timeout-target-${name}`).props.checked, true)
  assert.equal(h.byId('timeout-target-readonly').props.checked, false)
  assert.equal(h.byId('timeout-target-readonly').props.disabled, true)
  assert.equal(h.byId('timeout-target-unsupported').props.checked, false)
  assert.equal(h.byId('timeout-target-unsupported').props.disabled, true)

  h.click('timeout-target-source')
  for (const name of ['default', 'other', 'readonly']) assert.equal(h.byId(`timeout-target-${name}`).props.checked, false)
  assert.equal(h.byId('timeout-target-claire').props.checked, true)
  h.selectProfile('other')
  assert.equal(h.byId('timeout-target-claire').props.checked, true)

  h.click('timeout-target-none')
  h.check('timeout-target-default', true)
  h.check('timeout-target-other', true)
  h.selectProfile('claire')
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'other').timeouts.revision = 12
  h.setData(refreshed)
  await h.clickLabel('상태 새로고침')
  await h.flush()
  assert.equal(h.byId('timeout-target-default').props.checked, true)
  assert.equal(h.byId('timeout-target-claire').props.checked, false)
  assert.equal(h.byId('timeout-target-other').props.checked, true)
  assert.doesNotMatch(text(h.tree), /전체 저장에 복사 의도 포함/)
})

test('models-only save ignores dirty routing, timeout, and fallback drafts and uses stored routing baselines', async () => {
  const h = harness()
  h.input('model-main-model', 'unsaved-model-draft')
  h.input('routed-total-seconds', '9999')
  h.check('routing-profile-other', true)
  h.select('heavy-follow', 'custom')
  h.input('heavy-custom-model', 'unsaved-heavy-draft')
  h.check('routing-fallback-enabled', true)
  await h.click('models-save')
  await h.flush()
  const body = lastPreview(h).body
  assert.equal(body.save_scope, 'models')
  assert.deepEqual(body.model_targets, ['default', 'claire', 'other'])
  assert.deepEqual(body.routing_targets, [])
  assert.deepEqual(body.routing_profiles, ['claire'])
  assert.equal(body.models.main.model, 'unsaved-model-draft')
  assert.equal(body.routing.heavy.follow, 'main')
  assert.deepEqual(body.routing.fallback, profileRow(h, 'claire').routing.fallback)
  assert.equal('timeout_updates' in body, false)
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
  assert.equal(h.calls.filter(call => call.operation === 'preview').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
})

test('routing-only save applies activation membership and explicit Heavy/Light targets, but baseline models/timeouts/fallback only', async () => {
  const h = harness()
  const sourceModels = structuredClone(profileRow(h, 'claire').models)
  h.input('model-main-model', 'dirty-unsaved-model')
  h.input('delegate-total-seconds', '12345')
  h.select('heavy-follow', 'custom')
  h.input('heavy-custom-model', 'routing-only-heavy')
  h.check('routing-profile-other', true)
  h.check('routing-fallback-enabled', true)
  await h.click('routing-save')
  await h.flush()
  const body = lastPreview(h).body
  assert.equal(body.save_scope, 'routing')
  assert.deepEqual(body.model_targets, [])
  assert.deepEqual(body.routing_targets, ['default', 'claire', 'other'])
  assert.deepEqual(body.routing_profiles, ['claire', 'other'])
  assert.deepEqual(body.models, sourceModels)
  assert.equal(body.routing.heavy.follow, 'custom')
  assert.equal(body.routing.heavy.custom.model, 'routing-only-heavy')
  assert.deepEqual(body.routing.fallback, profileRow(h, 'claire').routing.fallback)
  assert.equal('timeout_updates' in body, false)
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
  assert.equal(h.calls.filter(call => call.operation === 'preview').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
})

test('an explicit timeout target action gives whole-page save one-time permission to copy unchanged source values', async () => {
  const h = harness()
  h.click('timeout-target-none')
  h.check('timeout-target-default', true)
  h.check('timeout-target-other', true)
  await h.click('global-save')
  await h.flush()
  assert.deepEqual(lastPreview(h).body.timeout_updates, [
    expectedTimeout('default', 3, 0, 3600),
    expectedTimeout('other', 11, 0, 3600)
  ])
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
})

test('timeout-only save copies unchanged values to a frozen manual subset and omits dirty model/routing/fallback drafts', async () => {
  const h = harness()
  const sourceModels = structuredClone(profileRow(h, 'claire').models)
  const sourceRouting = structuredClone(profileRow(h, 'claire').routing)
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  h.input('model-main-model', 'dirty-model')
  h.check('routing-profile-other', true)
  h.select('heavy-follow', 'custom')
  h.input('heavy-custom-model', 'dirty-routing')
  h.check('routing-fallback-enabled', true)
  await h.click('timeouts-save')
  await h.flush()
  const body = lastPreview(h).body
  assert.equal(body.save_scope, 'timeouts')
  assert.deepEqual(body.model_targets, [])
  assert.deepEqual(body.routing_targets, [])
  assert.deepEqual(body.routing_profiles, ['claire'])
  assert.deepEqual(body.models, sourceModels)
  assert.deepEqual(body.routing, sourceRouting)
  assert.deepEqual(body.timeout_updates, [expectedTimeout('other', 11, 0, 3600)])
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
  assert.equal(h.calls.filter(call => call.operation === 'preview').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
})

test('non-source timeout revision drift blocks preview before request using the immutable loaded target revision', async () => {
  const h = harness()
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  const drifted = structuredClone(h.data())
  drifted.profiles.find(row => row.name === 'other').timeouts.revision = 12
  h.setData(drifted)
  h.render()
  assert.equal(h.byId('timeouts-save').props.disabled, true)
  h.byId('timeouts-save').props.onClick()
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
})

test('non-source timeout revision drift during preview cancels apply for the entire captured target set', async () => {
  const h = harness()
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  const save = h.click('timeouts-save')
  const captured = structuredClone(h.calls[0].body)
  assert.deepEqual(captured.timeout_updates, [expectedTimeout('other', 11, 0, 3600)])
  const drifted = structuredClone(h.data())
  drifted.profiles.find(row => row.name === 'other').timeouts.revision = 12
  h.setData(drifted)
  h.render()
  resolvePreview({ plan_id: 'stale-target-plan', changes: [] })
  await save
  await h.flush()
  assert.deepEqual(h.calls[0].body, captured)
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.match(text(h.tree), /대상 프로필의 시간 제한 revision이 바뀌었습니다/)
})

test('unknown scoped apply result is one-shot and never triggers a blind preview/apply retry', async () => {
  const h = harness()
  h.input('model-main-model', 'candidate-model')
  h.setResponder(operation => operation === 'preview'
    ? { plan_id: 'one-shot-section-plan', changes: [] }
    : { status: 'unknown', error: 'apply response unavailable' })
  await h.click('models-save')
  await h.flush()
  assert.equal(h.calls.filter(call => call.operation === 'preview').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
  assert.equal(h.byId('models-save').props.disabled, true)
  h.byId('models-save').props.onClick()
  await h.flush()
  assert.equal(h.calls.filter(call => call.operation === 'preview').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
  assert.match(text(h.tree), /적용 결과를 확인할 수 없습니다/)
})

for (const kind of ['readonly', 'unsupported']) {
  test(`a selected timeout target becoming ${kind} stays selected and blocks the complete save`, async () => {
    const h = harness()
    h.click('timeout-target-none')
    h.check('timeout-target-claire', true)
    h.check('timeout-target-other', true)
    const changed = structuredClone(h.data())
    const target = changed.profiles.find(row => row.name === 'other')
    if (kind === 'readonly') target.timeouts.editable = false
    else delete target.timeouts
    h.setData(changed)
    h.render()
    assert.equal(h.byId('timeout-target-other').props.checked, true)
    assert.equal(h.byId('timeouts-save').props.disabled, true)
    h.byId('timeouts-save').props.onClick()
    await h.flush()
    assert.equal(h.calls.some(call => call.operation === 'preview'), false)
  })
}
