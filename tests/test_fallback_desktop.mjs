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
  selectFallbackTargets, selectFallbackSourceTarget, reconcileFallbackTargets, editableFallbackTargets,
  fallbackConsentReady, fallbackTargetNeedsConsent, nativeFallbackValidation,
  routeIdentity, primaryRouteForFallback, routingFallbackValidation,
  buildFallbackPreviewBody, fallbackPreviewMatchesScope, buildCombinedPreviewBody, previewFieldLabel, fallbackScopeTitle,
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
  let responder = operation => (operation === 'fallback-preview' || operation === 'preview')
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
  Object.assign(imports, { DesktopSDK: {}, useState, useRef, useEffect, jsx, jsxs: jsx, host,
    useValue: atom => atom.get(), useQuery: () => query })
  const executable = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
    .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
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
  const flush = async () => { for (let index = 0; index < 20; index++) await Promise.resolve(); render() }
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

test('recovery and Fast inheritance notes are readonly and do not claim provider success', () => {
  const h = harness()
  const recovery = h.byId('native-fallback-recovery-note')
  assert.match(text(recovery), /다음 응답/)
  assert.match(text(recovery), /사용 제한이 풀리면/)
  assert.match(text(recovery), /정상 응답을 확인했다는 뜻은 아닙니다/)
  const fast = h.byId('fast-inheritance-note')
  assert.match(text(fast), /작업 슬롯으로 맡기는 새 작업/)
  assert.doesNotMatch(text(fast), /기본 위임/)
  assert.match(text(fast), /시작할 때/)
  assert.match(text(fast), /지원하지 않는/)
  assert.match(text(fast), /추가 요금|크레딧/)
  assert.throws(() => h.byId('routing-fallback-recovery-note'), 'the retired routed-job spare models are no longer on the page')
  assert.equal(recovery.props.onClick, undefined)
  assert.equal(fast.props.onClick, undefined)
  assert.equal(h.calls.length, 0)
})

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

test('fallback targets start with all and preserve explicit subset or empty selection', () => {
  const names = ['default', 'claire', 'other', 'claire']
  assert.deepEqual(helpers.selectFallbackTargets(null, 'claire', names), ['default', 'claire', 'other'])
  assert.deepEqual(helpers.selectFallbackTargets(null, 'claire', names, ['other']), ['other'])
  assert.deepEqual(helpers.selectFallbackTargets([], 'other', names), [])
  assert.deepEqual(helpers.selectFallbackTargets(['other', 'removed', 'other'], 'claire', names), ['other'])
  assert.deepEqual(helpers.selectFallbackSourceTarget('default', names), ['default'])
  assert.deepEqual(helpers.reconcileFallbackTargets(['claire', 'removed'], names), ['claire'])
  assert.equal(helpers.reconcileFallbackTargets(null, names), null)
})

test('fallback target groups default to every editable profile, model targets to the loaded one, without enabling or saving routing', async () => {
  const data = delegationStatus()
  data.profiles.find(row => row.name === 'other').routing.enabled = false
  const h = harness(data)
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`native-fallback-target-${name}`).props.checked, true)
  for (const prefix of ['routing-fallback-target', 'delegation-fallback-target']) assert.throws(() => h.byId(`${prefix}-claire`))
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`model-target-${name}`).props.checked, name === 'claire')
  assert.equal(h.byId('routing-reenable-other').props.checked, false)
  assert.equal(h.calls.length, 0)
  h.setResponder(() => ({ plan_id: 'models-only', changes: [], warnings: [] }))
  globalButton(h, '저장')
  await h.flush()
  assert.equal('fallback_updates' in h.calls.find(c => c.operation === 'preview').body, false)
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_profiles, ['default', 'claire'])
})

test('initial selection excludes readonly or unsupported profiles without hiding explicit later invalid selections', () => {
  const data = delegationStatus()
  const other = data.profiles.find(row => row.name === 'other')
  other.fallbacks.native.editable = false
  other.fallbacks.routing.readonly = true
  other.fallbacks.delegation.editable = false
  const h = harness(data)
  assert.equal(h.byId('native-fallback-target-other').props.checked, false)
  assert.equal(h.byId('native-fallback-target-other').props.disabled, true)
  for (const scope of ['native', 'routing', 'delegation']) {
    assert.deepEqual(helpers.editableFallbackTargets(scope, data.profiles), ['default', 'claire'])
    assert.deepEqual(helpers.selectFallbackTargets(['other'], 'claire', ['default', 'claire', 'other'], ['default', 'claire']), ['other'])
  }
  assert.equal(h.byId('model-target-other').props.checked, false)
  assert.equal(h.byId('model-target-other').props.disabled, false)
})

test('source-only button narrows selection without saving and manual subsets survive source change and refresh', async () => {
  const h = harness(delegationStatus())
  h.selectProfile('other')
  h.click('native-fallback-target-source')
  assert.equal(text(h.byId('native-fallback-target-source')), '불러온 프로필만')
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`native-fallback-target-${name}`).props.checked, name === 'other')
  assert.equal(h.calls.length, 0)
  h.selectProfile('claire')
  assert.equal(h.byId('native-fallback-target-other').props.checked, true)
  assert.equal(h.byId('native-fallback-target-claire').props.checked, false)
  globalButton(h, '상태 새로고침')
  await h.flush()
  assert.equal(h.byId('native-fallback-target-other').props.checked, true, 'a manual subset survives a refresh')
  h.click('native-fallback-target-none')
  globalButton(h, '상태 새로고침')
  await h.flush()
  for (const name of ['default', 'claire', 'other']) assert.equal(h.byId(`native-fallback-target-${name}`).props.checked, false)
})

test('edited fallback uses all initially selected targets and default target selection never replays a copy', async () => {
  const h = harness(delegationStatus())
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  h.setResponder(() => ({ plan_id: 'all-native', changes: [], warnings: [] }))
  globalButton(h, '저장')
  await h.flush()
  const body = h.calls.find(c => c.operation === 'preview').body
  assert.deepEqual(body.fallback_updates.map(row => row.profile), ['default', 'claire', 'other'])
  assert.ok(body.fallback_updates.every(row => Object.keys(row).sort().join(',') === 'native_fallback,profile'))
  assert.deepEqual(body.fallback_confirmations.map(row => [row.profile, row.scope]), [['default', 'native'], ['claire', 'native'], ['other', 'native']])
})

test('a page-made default follows newly eligible profiles; a hand-picked list never widens; new connection starts all selected', async () => {
  const data = delegationStatus()
  const h = harness(data)
  const added = profile('added')
  added.fallbacks.delegation = delegationState()
  data.profiles.push(added)
  globalButton(h, '상태 새로고침')
  await h.flush()
  assert.equal(h.byId('native-fallback-target-added').props.checked, true, 'the default is every eligible profile, live')
  h.click('native-fallback-target-none')
  const later = profile('later')
  later.fallbacks.delegation = delegationState()
  data.profiles.push(later)
  h.render()
  assert.equal(h.byId('native-fallback-target-later').props.checked, false, 'a hand-picked list is not widened')
  h.state.connectionId.value = 'new-connection'
  h.render()
  for (const row of data.profiles) assert.equal(h.byId(`native-fallback-target-${row.name}`).props.checked, true)
  assert.equal(h.calls.length, 0)
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
  assert.match(helpers.routingFallbackValidation({ enabled: true, heavy: primary, light: route('other', 'light') }, [profile('claire')]), /Heavy 기본 경로/)
  assert.match(helpers.routingFallbackValidation({ enabled: true, heavy: route('a', 'same'), light: route('a', 'same') }), /서로 달라야/)
  assert.deepEqual(helpers.primaryRouteForFallback(baseRow, 'heavy'), baseRow.actual_models.main)
  const preview = { scopeKey: 'A', generation: 4, profile: 'claire', scope: 'native' }
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'A', 4, 'claire', 'native'), true)
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'A', 4, 'claire', 'routing'), false)
  assert.equal(helpers.fallbackPreviewMatchesScope(preview, 'B', 4, 'claire', 'native'), false)
})

test('native scope handler sends exact fallback-preview payload, uses notice instead of consent checkboxes and shares apply lock', async () => {
  const h = harness()
  assert.equal(h.calls.length, 0)
  assert.deepEqual(h.selected ? h.selected('model-target-') : [], [])
  h.click('native-fallback-target-source')
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  assert.equal(h.byId('native-fallback-save').props.disabled, false)
  assert.throws(() => h.byId('native-fallback-cost-consent'))
  await h.click('native-fallback-save')
  await h.flush()
  const request = h.calls.find(call => call.operation === 'fallback-preview')
  assert.deepEqual(request.body, {
    expected_revision: 12,
    updates: [{ profile: 'claire', native_fallback: { enabled: true, chain: [
      { provider: 'xiaomi', model: 'mimo-v2.6-pro' },
      { provider: 'deepseek', model: 'deepseek-flash' }
    ] } }],
    confirmations: [{ profile: 'claire', scope: 'native', allow_additional_cost: true, allow_task_rerun: false }],
    // The conversation spare models claire showed when the page loaded (compare-and-set).
    expected: [{ profile: 'claire', native_fallback: { enabled: false, chain: [], actual_chain: [] } }]
  })
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
  assert.throws(() => h.byId('routing-fallback-apply'))
  assert.throws(() => h.byId('native-fallback-review'))
  assert.equal(h.calls.some(call => call.operation === 'apply'), true)
  assert.deepEqual(h.calls.filter(call => call.operation === 'apply').map(call => call.body), [{ plan_id: 'fallback-plan' }])
  assert.equal(h.byId('native-fallback-enabled').props.disabled, false, 'a confirmed save reloads the saved state and unlocks by itself')
})

test('the routed-job and default-delegation spare-model panels and the old fallback section are gone from the page', async () => {
  const data = delegationStatus()
  const claire = data.profiles.find(row => row.name === 'claire')
  claire.fallbacks.routing = routingState({ enabled: true, heavy: route('api', 'kept-heavy'), light: route('api', 'kept-light'), consent: consent('routing') })
  claire.fallbacks.delegation = delegationState({ mode: 'custom', chain: [{ provider: 'kept', model: 'kept-spare' }], actual_mode: 'custom', actual_chain: [{ provider: 'kept', model: 'kept-spare' }] })
  const h = harness(data)
  for (const id of ['fallback-management', 'routing-fallback-enabled', 'routing-fallback-save', 'routing-fallback-target-claire', 'routing-fallback-preset-openai-api',
    'delegation-fallback-save', 'delegation-fallback-target-claire', 'delegation-fallback-template-non-openai', 'delegation-chain-0-provider']) assert.throws(() => h.byId(id), id)
  assert.equal([...walk(h.tree)].some(node => node.props?.id === 'delegation-fallback-mode'), false)
  const page = text(h.tree)
  for (const removed of ['작업·검증 라우팅 폴백', '기본 위임 방식의 예비 모델', '다른 작업 방식의 예비 모델', '예비 모델(폴백) 설정', '기본 위임 모델 사용']) assert.equal(page.includes(removed), false, removed)
  // Saving the conversation spare models and the whole page never writes the stored routing/delegation values.
  h.click('native-fallback-target-source'); h.click('native-fallback-preset-audited-non-openai'); h.check('native-fallback-enabled', true)
  globalButton(h, '저장'); await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(body.fallback_updates.map(update => Object.keys(update).sort()), [['native_fallback', 'profile']])
  assert.deepEqual(body.fallback_confirmations.map(row => row.scope), ['native'])
  assert.equal(JSON.stringify(h.calls).includes('routing_fallback') || JSON.stringify(h.calls).includes('delegation_fallback'), false)
})

test('native fallback preview cannot return after source-profile change and unsupported capabilities stay readonly', async () => {
  const h = harness()
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  let resolvePreview
  h.setResponder(operation => (operation === 'fallback-preview' || operation === 'preview')
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied' })
  const pending = h.click('native-fallback-save')
  h.state.connectionId.value = 'other-source'; h.render()
  resolvePreview({ plan_id: 'stale-plan', changes: [{ profile: 'claire', field: 'fallbacks.native' }] })
  await pending
  await h.flush()
  assert.throws(() => h.byId('native-fallback-apply'))
  const unsupported = harness(statusFixture({ fallback_capabilities: { ...helpers.SUPPORTED_FALLBACK_CAPABILITIES, native_execution: 'unknown' } }))
  assert.match(text(unsupported.tree), /읽기 전용/)
  assert.throws(() => unsupported.byId('native-fallback-enabled'))
  assert.throws(() => unsupported.byId('routing-fallback-enabled'))
})

test('the conversation spare models sit in the model section; no legacy editable fallback path remains', () => {
  const h = harness()
  const ids = [...walk(h.tree)].map(node => node.props?.id).filter(Boolean)
  const at = id => { const index = ids.indexOf(id); assert.ok(index >= 0, id); return index }
  assert.ok(at('conversation-models') < at('conversation-fallback'), 'under the conversation models')
  assert.ok(at('conversation-fallback') < at('native-delegation-settings'), 'above the task models')
  assert.ok(at('native-delegation-settings') < at('model-section-targets'))
  assert.ok(at('model-section-targets') < at('profile-delegation'), 'profile delegation is its own section after the model section')
  assert.ok(at('profile-delegation') < at('timeout-targets'))
  assert.match(text(h.byId('conversation-fallback')), /대화 예비 모델/)
  assert.ok(at('conversation-fallback') < at('native-fallback-save') && at('native-fallback-save') < at('native-delegation-settings'), 'with its own save button')
  assert.doesNotMatch(source, /id: 'fallback-management'|id: 'routing-fallback-|id: 'delegation-fallback-|delegation-chain-/)
  assert.match(source, /id: 'native-delegation-settings'/)
  assert.doesNotMatch(source, /id: 'fallback-enabled'/)
  assert.doesNotMatch(source, /updateFallback\s*=/)
  assert.match(source, /operation: '\/fallback-preview'/)
  assert.match(source, /selectedProfileRef\.current === snapshot\.profile/)
  assert.match(source, /applyPendingRef\.current = true/)
  assert.match(source, /needsReloadRef\.current = true/)
  assert.match(source, /role: 'alert'/)
  assert.match(source, /실제 적용 경로/)
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
  assert.ok(![...walk(h.tree)].some(n => n.props?.id === 'delegation-fallback-save'))
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

test('stored routing and delegation fallback drafts are never part of a combined body, even when changed and copied', () => {
  const status = delegationStatus()
  const draft = helpers.copyProfileDraft(status.profiles[1])
  const routing = { enabled: true, heavy: route('api', 'heavy'), light: route('api', 'light') }
  const delegation = { mode: 'custom', chain: [{ provider: 'xiaomi', model: 'test' }] }
  const result = helpers.buildCombinedPreviewBody(12, 'claire', draft, [], ['default', 'claire', 'other'],
    { native: null, routing, delegation }, { native: null, routing: { enabled: false, heavy: null, light: null }, delegation: { mode: 'default', chain: [] } },
    { routing: ['claire', 'other'], delegation: ['other'] }, status.profiles, true, { routing: true, delegation: true })
  assert.deepEqual(result.errors, [])
  assert.equal('fallback_updates' in result.body, false)
  assert.equal('fallback_confirmations' in result.body, false)
  assert.equal(helpers.fallbackScopeTitle('native'), '대화 예비 모델')
  assert.equal(helpers.previewFieldLabel('native_fallback'), '대화 예비 모델')
  for (const field of ['routing.fallback', 'delegation_fallback', 'fallback_consent.routing']) assert.match(helpers.previewFieldLabel(field), /이전/)
})

function globalButton(h, label) {
  const node = [...walk(h.tree)].find(node => node.type === 'Button' &&
    (label === '저장' ? node.props.id === 'global-save' : text(node) === label))
  assert.ok(node, `Button ${label} exists`)
  assert.equal(Boolean(node.props.disabled), false, `${label} enabled`)
  node.props.onClick()
  h.render()
}

function edit(h, id, value) {
  h.byId(id).props.onChange({ target: { value } })
  h.render()
}

function setupAllFallbackChanges(h) {
  h.click('native-fallback-target-source')
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
}

test('whole-page handler includes the changed conversation spare models with their own targets and applies one token', async () => {
  const h = harness(delegationStatus())
  h.setResponder(operation => operation === 'preview'
    ? { plan_id: 'combined-plan', changes: [
        { profile: 'claire', field: 'native_fallback', before: 'off', after: 'on' }
      ], warnings: [] }
    : { status: 'applied', revision: 13 })
  setupAllFallbackChanges(h)
  h.click('model-target-none')
  h.check('native-fallback-target-other', true)
  assert.match(text(h.byId('draft-reference-summary')), /수정한 예비 모델: 대화 예비 모델 2개 대상/)
  globalButton(h, '저장')
  await h.flush()
  const request = h.calls.find(call => call.operation === 'preview')
  assert.deepEqual(request.body.model_targets, [])
  assert.deepEqual(request.body.fallback_updates.map(u => Object.keys(u).sort()), [['native_fallback', 'profile'], ['native_fallback', 'profile']])
  assert.deepEqual(request.body.fallback_updates.map(u => u.profile), ['claire', 'other'])
  assert.deepEqual(request.body.fallback_confirmations.map(x => [x.profile, x.scope, x.allow_task_rerun]), [
    ['claire', 'native', false], ['other', 'native', false]
  ])
  assert.match(text(h.tree), /대화 예비 모델/)
  assert.equal(h.calls.some(x => x.operation === 'fallback-preview'), false)
  assert.throws(() => h.byId('confirm-preview'))
  assert.deepEqual(h.calls.filter(x => x.operation === 'apply').map(x => x.body), [{ plan_id: 'combined-plan' }])
  assert.equal(h.byId('native-fallback-enabled').props.disabled, false, 'a confirmed save reloads and unlocks by itself')
})

test('whole-page model-only preview preserves untouched fallback policies', async () => {
  const h = harness(delegationStatus())
  edit(h, 'model-main-model', 'changed-main')
  globalButton(h, '저장')
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
})

test('target-only selection copies that fallback but does not widen model targets or other scopes', async () => {
  const h = harness(delegationStatus())
  h.click('native-fallback-target-source')
  h.click('model-target-none')
  h.check('native-fallback-target-other', true)
  globalButton(h, '저장')
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(body.model_targets, [])
  assert.deepEqual(body.fallback_updates, [
    { profile: 'claire', native_fallback: { enabled: false, chain: [] } },
    { profile: 'other', native_fallback: { enabled: false, chain: [] } }
  ])
})

test('changed fallback with empty targets blocks whole preview instead of silently dropping changes', async () => {
  const h = harness(delegationStatus())
  h.click('native-fallback-preset-audited-non-openai')
  h.click('native-fallback-target-none')
  globalButton(h, '저장')
  await h.flush()
  assert.equal(h.calls.length, 0)
  assert.match(text(h.tree), /0개/)
})

test('single save locks fallback edits until its one apply completes', async () => {
  const h = harness(delegationStatus())
  setupAllFallbackChanges(h)
  let resolve
  h.setResponder(operation => operation === 'preview' ? new Promise(r => { resolve = r }) : { status: 'applied' })
  globalButton(h, '저장')
  assert.equal(h.byId('native-fallback-enabled').props.disabled, true)
  resolve({ plan_id: 'obsolete-combined', changes: [{ profile: 'claire', field: 'native_fallback' }] })
  await h.flush()
  assert.throws(() => h.byId('confirm-preview'))
  assert.equal(h.calls.filter(x => x.operation === 'apply').length, 1)
})

test('all consent and review checkboxes are absent; explicit single save remains', async () => {
  const h = harness(delegationStatus())
  setupAllFallbackChanges(h)
  for (const id of ['native-fallback-cost-consent', 'routing-fallback-cost-consent', 'routing-fallback-rerun-consent', 'delegation-fallback-cost-consent']) {
    assert.throws(() => h.byId(id))
  }
  assert.match(text(h.tree), /추가 비용/)
  assert.doesNotMatch(text(h.tree), /기본 위임 모델 사용/)
  h.click('native-fallback-save')
  await h.flush()
  assert.throws(() => h.byId('native-fallback-review'))
  assert.throws(() => h.byId('native-fallback-apply'))
  assert.throws(() => h.byId('confirm-preview'))
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
})

test('combined validation compares the conversation spare models with the draft main model', async () => {
  const h = harness(delegationStatus())
  h.click('native-fallback-target-source')
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  edit(h, 'model-main-provider', 'xiaomi')
  edit(h, 'model-main-model', 'mimo-v2.6-pro')
  globalButton(h, '저장')
  await h.flush()
  assert.equal(h.calls.length, 0)
  assert.match(text(h.tree), /기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
})


test('saved target copy is not repeated on later model-only save while selections are preserved', async () => {
  const data = delegationStatus()
  const h = harness(data)
  h.setResponder(operation => operation === 'preview'
    ? { plan_id: 'copy-plan', changes: [{ profile: 'other', field: 'native_fallback', before: null, after: { enabled: false, chain: [] } }], warnings: [] }
    : { status: 'applied', revision: 13 })
  h.check('native-fallback-target-other', true)
  globalButton(h, '저장')
  await h.flush()
  assert.ok(h.calls.find(c => c.operation === 'preview').body.fallback_updates)
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
  // Someone subsequently changed the former copy target. Do not replay the copy.
  data.revision = 13
  data.profiles.find(x => x.name === 'other').fallbacks.native = nativeState({
    managed: true, enabled: true, chain: [{ provider: 'independent', model: 'other-spare' }], consent: consent('native')
  })
  h.setData(data)
  globalButton(h, '상태 새로고침')
  await h.flush()
  assert.equal(h.byId('native-fallback-target-other').props.checked, true)
  edit(h, 'model-main-model', 'later-model-only')
  globalButton(h, '저장')
  await h.flush()
  assert.equal('fallback_updates' in h.calls.filter(x => x.operation === 'preview').at(-1).body, false)
  // A new explicit target action does create a new one-time copy intent.
  await h.flush()
  h.check('native-fallback-target-other', false)
  globalButton(h, '저장')
  await h.flush()
  assert.ok(h.calls.filter(x => x.operation === 'preview').at(-1).body.fallback_updates)
})


test('unchanged saved routing fallback is checked against changed main model in whole-page handler', async () => {
  const data = delegationStatus()
  const spare = { enabled: true, heavy: route('api', 'saved-heavy'), light: route('api', 'saved-light') }
  const row = data.profiles.find(x => x.name === 'claire')
  row.fallbacks.routing = routingState({ ...spare, consent: consent('routing') })
  row.routing.fallback = spare
  const h = harness(data)
  edit(h, 'model-main-provider', 'api')
  edit(h, 'model-main-model', 'saved-heavy')
  globalButton(h, '저장')
  await h.flush()
  assert.equal(h.calls.length, 0)
  assert.match(text(h.tree), /claire에 보관된 이전 작업 방식의 예비 모델과 겹칩니다/)
})

test('one catalog choice edits provider and model of a spare entry in the same turn; a retained callback stays rejected', async () => {
  const h = harness(delegationStatus())
  h.click('native-fallback-preset-audited-non-openai')
  // The catalog menu calls the field handler twice in one turn: provider, then model.
  const provider = h.byId('native-chain-0-provider').props.onChange, model = h.byId('native-chain-0-model').props.onChange
  provider({ target: { value: 'sample-lab' } }); model({ target: { value: 'sample-flash' } })
  h.render()
  assert.equal(h.byId('native-chain-0-provider').props.value, 'sample-lab')
  assert.equal(h.byId('native-chain-0-model').props.value, 'sample-flash', 'the second field of one choice must not be dropped')
  await Promise.resolve()
  model({ target: { value: 'late-stale-edit' } }); h.render()
  assert.equal(h.byId('native-chain-0-model').props.value, 'sample-flash')
  assert.equal(h.calls.length, 0)
})

test('a fallback save does not reload over an unsaved model edit; the edit and its lock stay until an explicit reload', async () => {
  const h = harness()
  edit(h, 'model-main-model', 'unsaved-main')
  h.click('native-fallback-target-source')
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  await h.click('native-fallback-save')
  await h.flush()
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
  assert.equal(h.calls.filter(call => call.operation === 'status').length, 0, 'no automatic reload')
  assert.equal(h.byId('model-main-model').props.value, 'unsaved-main', 'the unsaved edit is still on the page')
  assert.equal(h.byId('native-fallback-enabled').props.disabled, true)
  globalButton(h, '실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('native-fallback-enabled').props.disabled, false)
})

test('a chosen conversation spare-model target that disappears stays ticked and blocks that save by name', () => {
  const h = harness()
  h.click('native-fallback-target-source')
  h.check('native-fallback-target-other', true)
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  assert.equal(h.byId('native-fallback-save').props.disabled, false)
  const fewer = structuredClone(statusFixture()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  h.setData(fewer); h.render()
  assert.equal(h.byId('native-fallback-target-other').props.checked, true)
  assert.match(text(h.byId('native-fallback-targets-missing')), /더 이상 찾을 수 없어 저장하지 않습니다.*other/)
  assert.equal(h.byId('native-fallback-save').props.disabled, true)
  h.check('native-fallback-target-other', false)
  assert.equal(h.byId('native-fallback-save').props.disabled, false)
})

test('a vanished hand-picked target survives a source switch in both lists until it is unticked', () => {
  const h = harness()
  h.click('model-target-all')
  h.click('native-fallback-target-none'); for (const name of ['default', 'claire', 'other']) h.check(`native-fallback-target-${name}`, true)
  const fewer = structuredClone(statusFixture()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  h.setData(fewer); h.render()
  h.selectProfile('default')
  assert.equal(h.byId('model-target-other').props.checked, true, 'model list keeps it after the switch')
  assert.equal(h.byId('native-fallback-target-other').props.checked, true, 'spare-model list keeps it after the switch')
  assert.match(text(h.byId('native-fallback-targets-missing')), /other/)
  h.check('model-target-other', false); h.check('native-fallback-target-other', false)
  assert.throws(() => h.byId('model-target-other')); assert.throws(() => h.byId('native-fallback-target-other'))
})

test('a page-made spare-model default follows a profile that becomes eligible at the same revision', () => {
  const h = harness()
  const grown = structuredClone(statusFixture())
  grown.profiles.push(profile('added'))
  h.setData(grown); h.render()
  assert.equal(h.byId('native-fallback-target-added').props.checked, true)
})
