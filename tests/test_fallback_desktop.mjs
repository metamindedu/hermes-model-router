import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helperSource = source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')
const helpers = new Function(`${helperSource}\nreturn {
  MODEL_PRESETS, NATIVE_FALLBACK_PRESETS, ROUTING_FALLBACK_PRESETS, SUPPORTED_FALLBACK_CAPABILITIES,
  deepClone, sameValue, applyModelPresetDraft, copyProfileDraft,
  fallbackCapabilitiesSupported, copyNativeFallbackDraft, copyRoutingFallbackDraft,
  applyNativeFallbackPresetDraft, applyRoutingFallbackPresetDraft,
  selectFallbackTargets, selectFallbackSourceTarget, reconcileFallbackTargets,
  fallbackConsentReady, fallbackTargetNeedsConsent, nativeFallbackValidation,
  routeIdentity, primaryRouteForFallback, routingFallbackValidation,
  buildFallbackPreviewBody, fallbackPreviewMatchesScope,
  DELEGATION_FALLBACK_MODES, validDelegationFallbackState, copyDelegationFallbackDraft, delegationFallbackValidation
}`)()

const route = (provider, model, reasoning = 'max') => ({ provider, model, reasoning })
const consent = scope => ({
  policy_version: 1,
  selection_digest: `digest-${scope}`,
  source: 'explicit',
  allow_additional_cost: true,
  allow_task_rerun: scope === 'routing'
})
const nativeState = (overrides = {}) => ({
  managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null,
  ...overrides
})
const routingState = (overrides = {}) => ({ enabled: false, heavy: null, light: null, consent: null, ...overrides })
const profile = (name, overrides = {}) => ({
  name,
  models: {
    main: route('primary', `${name}-main`, 'high'),
    delegation: route('primary', `${name}-light`, 'medium'),
    compression: route('primary', `${name}-compress`, 'medium'),
    title: route('primary', `${name}-title`, 'none')
  },
  actual_models: {
    main: route('primary', `${name}-main`, 'high'),
    delegation: route('primary', `${name}-light`, 'medium')
  },
  routing: {
    enabled: true,
    heavy: { follow: 'main', custom: null },
    light: { follow: 'delegation', custom: null },
    fallback: { enabled: false, heavy: null, light: null }
  },
  fallbacks: { native: nativeState(), routing: routingState() },
  drift: [],
  ...overrides
})
const statusFixture = (overrides = {}) => ({
  revision: 12,
  current_profile: 'claire',
  fallback_capabilities: { ...helpers.SUPPORTED_FALLBACK_CAPABILITIES },
  profiles: [profile('default'), profile('claire'), profile('other')],
  ...overrides
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
  let responder = operation => operation === 'fallback-preview'
    ? { plan_id: 'fallback-plan', changes: [{ profile: 'claire', field: 'fallbacks.native', before: 'off', after: 'on' }], warnings: [] }
    : { status: 'applied', revision: 13 }
  const host = { state, request: async (method, args) => {
    const index = args.argv.indexOf('model-router'), operation = args.argv[index + 1]
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
  const flush = async () => { for (let index = 0; index < 10; index++) await Promise.resolve(); render() }
  const click = id => {
    const node = byId(id)
    assert.ok(!node.props.disabled, `${id} should be enabled`)
    const result = node.props.onClick?.()
    render()
    return result
  }
  const check = (id, checked) => {
    const node = byId(id)
    assert.ok(!node.props.disabled, `${id} should be enabled`)
    node.props.onCheckedChange(checked)
    render()
  }
  const selectProfile = name => {
    const select = find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'profile-select'))
    select.props.onValueChange(name)
    render()
  }
  render()
  return {
    calls, state, render, byId, click, check, selectProfile, flush,
    get tree() { return tree },
    setResponder(fn) { responder = fn },
    setData(value) { data = value }
  }
}

test('phase1 presets remain exact while fallback presets only fill drafts and never enable', () => {
  assert.deepEqual(helpers.MODEL_PRESETS.map(item => item.id), ['openai', 'non-openai'])
  const nativeOff = { enabled: false, chain: [] }
  const nativeDraft = helpers.applyNativeFallbackPresetDraft(nativeOff, 'audited-non-openai')
  assert.deepEqual(nativeDraft, { enabled: false, chain: [
    { provider: 'xiaomi', model: 'mimo-v2.6-pro' },
    { provider: 'deepseek', model: 'deepseek-flash' }
  ] })
  assert.deepEqual(nativeOff, { enabled: false, chain: [] })
  const routeOff = { enabled: false, heavy: null, light: null }
  const routeDraft = helpers.applyRoutingFallbackPresetDraft(routeOff, 'non-openai')
  assert.equal(routeDraft.enabled, false)
  assert.deepEqual(routeDraft.heavy, route('xiaomi', 'mimo-v2.6-pro'))
  assert.deepEqual(routeDraft.light, route('deepseek', 'deepseek-flash'))
  assert.equal(helpers.applyNativeFallbackPresetDraft(nativeOff, 'openai-api').chain[0].provider, 'openai-api')
  assert.deepEqual(helpers.applyRoutingFallbackPresetDraft(routeOff, 'openai-api'), {
    enabled: false,
    heavy: route('openai-api', 'gpt-6-astra'),
    light: route('openai-api', 'gpt-5.6-luna')
  })
  assert.equal(helpers.applyRoutingFallbackPresetDraft(routeOff, 'openai-api').light.model, 'gpt-5.6-luna')
})

test('fallback targets start with the source only and preserve explicit all, subset, or empty selection', () => {
  const names = ['default', 'claire', 'other', 'claire']
  assert.deepEqual(helpers.selectFallbackTargets(null, 'claire', names), ['claire'])
  assert.deepEqual(helpers.selectFallbackTargets([], 'other', names), [])
  assert.deepEqual(helpers.selectFallbackTargets(['other', 'removed', 'other'], 'claire', names), ['other'])
  assert.deepEqual(helpers.selectFallbackSourceTarget('default', names), ['default'])
  assert.deepEqual(helpers.reconcileFallbackTargets(['claire', 'removed'], names), ['claire'])
  assert.equal(helpers.reconcileFallbackTargets(null, names), null)
})

test('new/changed, external-ownership, legacy-approved, and off changes get exact consent behavior', () => {
  const currentNative = { fallbacks: { native: nativeState({ enabled: true, chain: [{ provider: 'x', model: 'm' }], consent: consent('native') }) } }
  const sameNative = { enabled: true, chain: [{ provider: 'x', model: 'm' }] }
  assert.equal(helpers.fallbackTargetNeedsConsent('native', currentNative, sameNative), false)
  assert.equal(helpers.fallbackTargetNeedsConsent('native', { fallbacks: { native: nativeState({ managed: false, enabled: true, chain: sameNative.chain, consent: consent('native') }) } }, sameNative), true)
  assert.equal(helpers.fallbackTargetNeedsConsent('native', currentNative, { enabled: true, chain: [{ provider: 'x', model: 'new' }] }), true)
  assert.equal(helpers.fallbackTargetNeedsConsent('native', currentNative, { enabled: false, chain: [] }), false)
  const routeValue = { enabled: true, heavy: route('a', 'heavy'), light: route('b', 'light') }
  const approvedRouting = { fallbacks: { routing: routingState({ ...routeValue, consent: consent('routing') }) } }
  assert.equal(helpers.fallbackTargetNeedsConsent('routing', approvedRouting, routeValue), false)
  assert.equal(helpers.fallbackTargetNeedsConsent('routing', { fallbacks: { routing: routingState(routeValue) } }, routeValue), true)
  assert.equal(helpers.fallbackTargetNeedsConsent('routing', approvedRouting, { ...routeValue, enabled: false }), false)
  assert.equal(helpers.fallbackConsentReady({ ...consent('routing'), allow_task_rerun: false }, 'routing'), false)
})

test('fallback preview DTO updates exactly one scope and requires scope-specific consent', () => {
  const changedNative = profile('changed')
  const retainedNative = profile('retained', { fallbacks: { native: nativeState({ enabled: true, chain: [{ provider: 'x', model: 'm' }], consent: consent('native') }), routing: routingState() } })
  const nativeValue = { enabled: true, chain: [{ provider: 'x', model: 'm' }] }
  const nativeBody = helpers.buildFallbackPreviewBody(9, 'native', ['changed', 'retained'], nativeValue, [changedNative, retainedNative], true, false)
  assert.deepEqual(nativeBody, {
    expected_revision: 9,
    updates: [
      { profile: 'changed', native_fallback: nativeValue },
      { profile: 'retained', native_fallback: nativeValue }
    ],
    confirmations: [{ profile: 'changed', scope: 'native', allow_additional_cost: true, allow_task_rerun: false }]
  })
  const routingValue = { enabled: true, heavy: route('api', 'heavy'), light: route('api', 'light') }
  const routingBody = helpers.buildFallbackPreviewBody(10, 'routing', ['changed'], routingValue, [changedNative], true, true)
  assert.deepEqual(routingBody, {
    expected_revision: 10,
    updates: [{ profile: 'changed', routing_fallback: routingValue }],
    confirmations: [{ profile: 'changed', scope: 'routing', allow_additional_cost: true, allow_task_rerun: true }]
  })
  assert.deepEqual(Object.keys(routingBody), ['expected_revision', 'updates', 'confirmations'])
  assert.equal('native_fallback' in routingBody.updates[0], false)
})

test('fixed capabilities, chain constraints, role IDs, and stale scope matching are fail-closed', () => {
  assert.equal(helpers.fallbackCapabilitiesSupported(helpers.SUPPORTED_FALLBACK_CAPABILITIES), true)
  assert.equal(helpers.fallbackCapabilitiesSupported({ ...helpers.SUPPORTED_FALLBACK_CAPABILITIES, routing_max_retries: 2 }), false)
  assert.equal(helpers.fallbackCapabilitiesSupported(null), false)
  assert.equal(helpers.nativeFallbackValidation({ enabled: true, chain: [] }).length > 0, true)
  assert.equal(helpers.nativeFallbackValidation({ enabled: true, chain: Array.from({ length: 6 }, (_, index) => ({ provider: `p${index}`, model: `m${index}` })) }).includes('최대 5개'), true)
  assert.equal(helpers.nativeFallbackValidation({ enabled: false, chain: [{ provider: 'x', model: 'm' }, { provider: 'x', model: 'm' }] }).includes('중복'), true)
  const baseRow = profile('claire')
  const primary = profile('claire').actual_models.main
  assert.match(helpers.routingFallbackValidation({ enabled: true, heavy: primary, light: route('other', 'light') }, [profile('claire')]), /Heavy 기본 모델/)
  assert.match(helpers.routingFallbackValidation({ enabled: true, heavy: route('a', 'same'), light: route('a', 'same') }), /서로 달라야/)
  assert.deepEqual(helpers.primaryRouteForFallback(baseRow, 'heavy'), baseRow.actual_models.main)
  const preview = { scopeKey: 'A', generation: 4, profile: 'claire', scope: 'native' }
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'A', 4, 'claire', 'native'), true)
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'A', 4, 'claire', 'routing'), false)
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'B', 4, 'claire', 'native'), false)
})

test('native scope handler sends exact fallback-preview payload, requires consent, and shares apply lock', async () => {
  const h = harness()
  assert.equal(h.calls.length, 0)
  assert.deepEqual(h.selected ? h.selected('model-target-') : [], [])
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  assert.equal(h.byId('native-fallback-preview').props.disabled, true)
  h.check('native-fallback-cost-consent', true)
  await h.click('native-fallback-preview')
  await h.flush()
  const request = h.calls.find(call => call.operation === 'fallback-preview')
  assert.deepEqual(request.body, {
    expected_revision: 12,
    updates: [{ profile: 'claire', native_fallback: { enabled: true, chain: [
      { provider: 'xiaomi', model: 'mimo-v2.6-pro' },
      { provider: 'deepseek', model: 'deepseek-flash' }
    ] } }],
    confirmations: [{ profile: 'claire', scope: 'native', allow_additional_cost: true, allow_task_rerun: false }]
  })
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
  assert.throws(() => h.byId('routing-fallback-apply'))
  h.check('native-fallback-review', true)
  const applying = h.click('native-fallback-apply')
  assert.equal(h.calls.some(call => call.operation === 'apply'), true)
  await applying
  await h.flush()
  assert.deepEqual(h.calls.filter(call => call.operation === 'apply').map(call => call.body), [{ plan_id: 'fallback-plan' }])
  assert.equal(h.byId('native-fallback-enabled').props.disabled, true)
})

test('coding fallback handler sends only routing scope with both cost and fresh-task consent', async () => {
  const h = harness()
  h.click('routing-fallback-preset-openai-api')
  h.check('routing-fallback-enabled', true)
  assert.equal(h.byId('routing-fallback-preview').props.disabled, true)
  h.check('routing-fallback-cost-consent', true)
  assert.equal(h.byId('routing-fallback-preview').props.disabled, true)
  h.check('routing-fallback-rerun-consent', true)
  await h.click('routing-fallback-preview')
  await h.flush()
  const request = h.calls.find(call => call.operation === 'fallback-preview')
  assert.deepEqual(request.body, {
    expected_revision: 12,
    updates: [{ profile: 'claire', routing_fallback: {
      enabled: true,
      heavy: route('openai-api', 'gpt-6-astra'),
      light: route('openai-api', 'gpt-5.6-luna')
    } }],
    confirmations: [{ profile: 'claire', scope: 'routing', allow_additional_cost: true, allow_task_rerun: true }]
  })
  assert.equal('routing_profiles' in request.body, false)
  assert.equal(request.body.updates[0].native_fallback, undefined)
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
})

test('native fallback preview cannot return after source-profile change and unsupported capabilities stay readonly', async () => {
  const h = harness()
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  h.check('native-fallback-cost-consent', true)
  let resolvePreview
  h.setResponder(operation => operation === 'fallback-preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied' })
  const pending = h.click('native-fallback-preview')
  h.selectProfile('default')
  resolvePreview({ plan_id: 'stale-plan', changes: [{ profile: 'claire', field: 'fallbacks.native' }] })
  await pending
  await h.flush()
  assert.throws(() => h.byId('native-fallback-apply'))
  const unsupported = harness(statusFixture({ fallback_capabilities: { ...helpers.SUPPORTED_FALLBACK_CAPABILITIES, native_execution: 'unknown' } }))
  assert.match(text(unsupported.tree), /읽기 전용/)
  assert.throws(() => unsupported.byId('native-fallback-enabled'))
  assert.throws(() => unsupported.byId('routing-fallback-enabled'))
})

test('routing details exposes readonly fallback summary/navigation; no legacy editable fallback path remains', () => {
  assert.match(source, /legacy-routing-fallback-summary/)
  assert.match(source, /href: '#fallback-management'/)
  assert.doesNotMatch(source, /id: 'fallback-enabled'/)
  assert.doesNotMatch(source, /updateFallback\s*=/)
  assert.match(source, /ctx\.rest\('\/fallback-preview', \{ method: 'POST', body \}\)/)
  assert.match(source, /selectedProfileRef\.current !== capturedProfile/)
  assert.match(source, /applyPendingRef\.current = true/)
  assert.match(source, /needsReloadRef\.current = true/)
  assert.match(source, /role: 'alert'/)
  assert.match(source, /실제 적용 경로/)
  assert.match(source, /주 경로:/)
  assert.match(source, /대체 경로:/)
  assert.doesNotMatch(source, /window\.hermesDesktop|child_process|node:fs|localStorage|\bfetch\s*\(/)
})


const delegationState = (overrides = {}) => ({
  managed: false, editable: true, mode: 'default', chain: [], actual_mode: 'default', actual_chain: [],
  drift: false, warnings: [], consent: null, ...overrides
})
function delegationStatus() {
  const status = statusFixture()
  status.profiles.forEach(row => { row.fallbacks.delegation = delegationState() })
  return status
}
function selectDelegationMode(h, mode) {
  const node = [...walk(h.tree)].find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'delegation-fallback-mode'))
  assert.ok(node)
  node.props.onValueChange(mode)
  h.render()
}

test('delegation DTO distinguishes default/off/custom and fails closed for older backend or malformed DTO', () => {
  assert.deepEqual(helpers.DELEGATION_FALLBACK_MODES.map(x => x.value), ['default', 'off', 'custom'])
  assert.equal(helpers.copyDelegationFallbackDraft(undefined), null)
  for (const mode of ['default', 'off', 'custom']) {
    const chain = mode === 'custom' ? [{ provider: 'xiaomi', model: 'test' }] : []
    assert.deepEqual(helpers.copyDelegationFallbackDraft(delegationState({ mode, chain })), { mode, chain })
  }
  assert.equal(helpers.copyDelegationFallbackDraft(delegationState({ mode: 'inherit-everything' })), null)
  assert.equal(helpers.copyDelegationFallbackDraft(delegationState({ mode: 'custom', chain: [] })), null)
  assert.ok(helpers.delegationFallbackValidation({ mode: 'off', chain: [{ provider: 'x', model: 'm' }] }))
  assert.ok(helpers.delegationFallbackValidation({ mode: 'custom', chain: Array(6).fill({ provider: 'x', model: 'm' }) }))
  const h = harness(statusFixture())
  assert.ok(text(h.tree).includes('위임 폴백 설정을 확인할 수 없어 편집을 잠갔습니다.'))
  assert.ok(![...walk(h.tree)].some(n => n.props?.id === 'delegation-fallback-preview'))
  assert.equal(h.calls.length, 0)
})

test('delegation consent binds non-off modes, has no fresh-task flag, and payload writes only delegation', () => {
  const status = delegationStatus()
  for (const mode of ['default', 'custom']) {
    const value = { mode, chain: mode === 'custom' ? [{ provider: 'xiaomi', model: 'test' }] : [] }
    const body = helpers.buildFallbackPreviewBody(12, 'delegation', ['claire'], value, status.profiles, true, false)
    assert.deepEqual(body.updates, [{ profile: 'claire', delegation_fallback: value }])
    assert.deepEqual(body.confirmations, [{ profile: 'claire', scope: 'delegation', allow_additional_cost: true, allow_task_rerun: false }])
  }
  const body = helpers.buildFallbackPreviewBody(12, 'delegation', ['claire'], { mode: 'off', chain: [] }, status.profiles, false, false)
  assert.deepEqual(body.confirmations, [])
})

test('delegation custom draft/template preserves other scopes and requires explicit cost consent before preview', async () => {
  const h = harness(delegationStatus())
  assert.equal(h.byId('delegation-fallback-target-claire').props.checked, true)
  assert.equal(h.byId('delegation-fallback-target-default').props.checked, false)
  assert.equal(h.byId('model-target-default').props.checked, true)
  selectDelegationMode(h, 'custom')
  h.click('delegation-fallback-template-non-openai')
  assert.equal(h.calls.length, 0)
  assert.equal(h.byId('delegation-fallback-preview').props.disabled, true)
  h.check('delegation-fallback-cost-consent', true)
  h.click('delegation-fallback-preview')
  await h.flush()
  assert.equal(h.calls.length, 1)
  const call = h.calls[0]
  assert.equal(call.operation, 'fallback-preview')
  assert.deepEqual(call.body.updates.map(x => Object.keys(x).sort()), [['delegation_fallback', 'profile']])
  assert.equal(call.body.updates[0].profile, 'claire')
  assert.equal(call.body.updates[0].delegation_fallback.mode, 'custom')
  assert.equal(call.body.confirmations[0].allow_task_rerun, false)
  assert.ok(!h.calls.some(call => call.operation === 'apply'))
})

test('delegation off preview needs no cost consent and stale response cannot follow a profile switch', async () => {
  const h = harness(delegationStatus())
  selectDelegationMode(h, 'off')
  let resolve
  h.setResponder(() => new Promise(r => { resolve = r }))
  h.click('delegation-fallback-preview')
  assert.deepEqual(h.calls[0].body.confirmations, [])
  h.selectProfile('other')
  resolve({ plan_id: 'obsolete-delegation-plan', changes: [], warnings: [] })
  await h.flush()
  assert.ok(!text(h.tree).includes('obsolete-delegation-plan'))
  assert.ok(!h.calls.some(call => call.operation === 'apply'))
})
