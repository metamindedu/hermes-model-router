import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helperSource = source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')
const helpers = new Function(`${helperSource}\nreturn {
  MODEL_PRESETS, ROUTING_FALLBACK_PRESETS, SUPPORTED_FALLBACK_CAPABILITIES,
  deepClone, sameValue, applyModelPresetDraft, copyProfileDraft,
  fallbackCapabilitiesSupported, copyNativeFallbackDraft, copyRoutingFallbackDraft,
  applyRoutingFallbackPresetDraft, moveChainEntry, nativeFallbackModeDraft, nativeFallbackTargetReason,
  buildModelSectionFallbackBody, foldedRouteIdentity, FALLBACK_PROVIDER_RE, FALLBACK_MODEL_RE,
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
// The conversation spare models (native fallback) sit under the main conversation model, in the task
// slots' pattern, and are saved by the model section's save to the model section's targets.
const SPARES = [{ provider: 'xiaomi', model: 'mimo-v2.6-pro' }, { provider: 'deepseek', model: 'deepseek-flash' }]
const selectNode = (h, id) => [...walk(h.tree)].find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id))
function choose(h, id, value) {
  const node = selectNode(h, id)
  assert.ok(node, `${id} exists`)
  assert.equal(Boolean(node.props.disabled), false, `${id} should be enabled`)
  node.props.onValueChange(value)
  h.render()
}
function draftSpares(h, chain = SPARES) {
  choose(h, 'native-fallback-mode', 'custom')
  chain.forEach((entry, index) => {
    if (index > 0) h.click('native-chain-add')
    edit(h, `native-chain-${index}-provider`, entry.provider)
    edit(h, `native-chain-${index}-model`, entry.model)
  })
}
const lastPreview = h => h.calls.filter(call => call.operation === 'preview').at(-1)
const lastFallback = h => h.calls.filter(call => call.operation === 'fallback-preview').at(-1)
const routingExpectation = { enabled: true, heavy: { follow: 'main', custom: null }, light: { follow: 'delegation', custom: null }, slots: null, skill_enabled: true }
const offExpectation = { enabled: false, chain: [], actual_chain: [] }
const timeoutDto = revision => ({ schema: 1, revision, delegate_total_seconds: 0, routed_total_seconds: 3600, editable: true, split_routing_supported: true, warnings: [] })

test('the Fast inheritance note stays readonly; the long spare-model status copy is gone', () => {
  const h = harness()
  const fast = h.byId('fast-inheritance-note')
  assert.match(text(fast), /작업 슬롯으로 맡기는 새 작업/)
  assert.doesNotMatch(text(fast), /기본 위임/)
  assert.match(text(fast), /시작할 때/)
  assert.match(text(fast), /지원하지 않는/)
  assert.match(text(fast), /추가 요금|크레딧/)
  assert.throws(() => h.byId('routing-fallback-recovery-note'), 'the retired routed-job spare models are no longer on the page')
  assert.throws(() => h.byId('native-fallback-recovery-note'))
  const page = text(h.tree)
  for (const removed of ['저장 설정:', '편집 초안:', '실제 적용 경로', '메인 대화에서 대체 체인 사용']) assert.equal(page.includes(removed), false, removed)
  assert.equal(fast.props.onClick, undefined)
  assert.equal(h.calls.length, 0)
})

test('model presets remain exact; the conversation spare-model presets are removed, routing presets only fill drafts', () => {
  assert.deepEqual(helpers.MODEL_PRESETS.map(item => item.id), ['openai', 'non-openai'])
  assert.doesNotMatch(source, /NATIVE_FALLBACK_PRESETS|applyNativeFallbackPresetDraft|native-fallback-preset-/)
  const routeOff = { enabled: false, heavy: null, light: null }
  const routeDraft = helpers.applyRoutingFallbackPresetDraft(routeOff, 'non-openai')
  assert.equal(routeDraft.enabled, false)
  assert.deepEqual(routeDraft.heavy, route('xiaomi', 'mimo-v2.6-pro'))
  assert.deepEqual(routeDraft.light, route('deepseek', 'deepseek-flash'))
  assert.deepEqual(helpers.applyRoutingFallbackPresetDraft(routeOff, 'openai-api'), {
    enabled: false,
    heavy: route('openai-api', 'gpt-6-astra'),
    light: route('openai-api', 'gpt-5.6-luna')
  })
  const h = harness()
  assert.equal([...walk(h.tree)].some(node => String(node.props?.id || '').startsWith('native-fallback-preset-')), false)
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

test('the editor sits directly under the main model picker: picker, then 이 모델을 쓸 수 없을 때, then the chain', () => {
  const h = harness()
  draftSpares(h)
  const ids = [...walk(h.tree)].map(node => node.props?.id).filter(Boolean)
  const at = id => { const index = ids.indexOf(id); assert.ok(index >= 0, id); return index }
  // Without a model catalog the pickers are the ID fields.
  assert.ok(at('conversation-models') < at('model-main-provider'))
  assert.ok(at('model-main-reasoning') < at('conversation-fallback'), 'under the main conversation model')
  assert.ok(at('conversation-fallback') < at('native-fallback-mode'))
  assert.ok(at('native-fallback-mode') < at('native-chain-0-provider') && at('native-chain-0-model') < at('native-chain-1-provider'))
  assert.ok(at('native-chain-1-model') < at('native-chain-add'))
  assert.ok(at('native-chain-add') < at('model-delegation-provider'), 'inside the main model card, before the other roles')
  assert.ok(at('model-delegation-provider') < at('model-section-targets'))
  assert.ok(at('model-section-targets') < at('profile-delegation'), 'profile delegation is its own section after the model section')
  assert.ok(at('profile-delegation') < at('timeout-targets'))
  const mode = selectNode(h, 'native-fallback-mode')
  assert.equal(mode.props.value, 'custom')
  assert.deepEqual([...walk(mode)].filter(node => node.type === 'SelectItem').map(node => [node.props.value, text(node)]),
    [['off', '다른 모델로 전환하지 않음'], ['custom', '예비 모델로 이어가기']])
  assert.match(text(h.byId('conversation-fallback')), /이 모델을 쓸 수 없을 때/)
  assert.match(text(h.byId('native-fallback-cost-note')), /비용이 늘 수 있습니다/)
  assert.equal(text(h.byId('native-chain-0-remove')), '이 예비 모델 삭제')
  assert.equal(text(h.byId('native-chain-add')), '예비 모델 추가')
})

test('the separate spare-model card, its target list, save button and presets are gone', () => {
  const h = harness()
  const ids = [...walk(h.tree)].map(node => node.props?.id).filter(Boolean)
  for (const id of ['native-fallback-save', 'native-fallback-enabled', 'native-fallback-targets-missing', 'native-fallback-target-source', 'native-fallback-target-all', 'native-fallback-target-none'])
    assert.equal(ids.includes(id), false, id)
  assert.equal(ids.some(id => id.startsWith('native-fallback-target-') || id.startsWith('native-fallback-preset-')), false)
  assert.doesNotMatch(source, /id: 'native-fallback-save'|native-fallback-target-|fallbackTargetGroup|nativeFallbackPanel|const saveFallback/)
  assert.doesNotMatch(source, /id: 'fallback-management'|id: 'routing-fallback-|id: 'delegation-fallback-|delegation-chain-/)
  assert.doesNotMatch(source, /id: 'fallback-enabled'/)
  assert.doesNotMatch(source, /updateFallback\s*=/)
  assert.match(source, /id: 'native-delegation-settings'/)
  assert.match(source, /selectedProfileRef\.current === snapshot\.profile/)
  assert.match(source, /applyPendingRef\.current = true/)
  assert.match(source, /needsReloadRef\.current = true/)
  assert.doesNotMatch(source, /window\.hermesDesktop|child_process|node:fs|localStorage|\bfetch\s*\(/)
  assert.doesNotMatch(text(h.tree), /그 카드의 적용 대상과 저장 버튼/)
})

test('choosing 예비 모델로 이어가기 turns it on with one row; switching off keeps the stored chain', async () => {
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').fallbacks.native = nativeState({ enabled: true, chain: structuredClone(SPARES), actual_chain: structuredClone(SPARES), consent: consent('native') })
  const h = harness(data)
  assert.equal(selectNode(h, 'native-fallback-mode').props.value, 'custom')
  assert.equal(h.byId('native-chain-1-model').props.value, 'deepseek-flash')
  assert.equal(h.byId('model-section-save').props.disabled, true, 'nothing changed yet')
  choose(h, 'native-fallback-mode', 'off')
  assert.throws(() => h.byId('native-chain-0-picker'), 'no rows while switched off')
  assert.throws(() => h.byId('native-chain-add'))
  assert.match(text(h.byId('native-fallback-kept')), /지우지 않고 보관합니다/)
  assert.throws(() => h.byId('native-fallback-cost-note'))
  choose(h, 'native-fallback-mode', 'custom')
  assert.equal(h.byId('native-chain-1-model').props.value, 'deepseek-flash', 'the kept chain comes back')
  assert.equal(h.byId('model-section-save').props.disabled, true, 'back to the stored value: nothing to save')
  choose(h, 'native-fallback-mode', 'off')
  await h.click('model-section-save'); await h.flush()
  const body = lastFallback(h).body
  assert.deepEqual(body.updates, [{ profile: 'claire', native_fallback: { enabled: false, chain: SPARES } }])
  assert.deepEqual(body.confirmations, [], 'switching off needs no cost consent')
  // A row added and left blank is not kept when switching off.
  assert.deepEqual(helpers.nativeFallbackModeDraft({ enabled: false, chain: [] }, 'custom'), { enabled: true, chain: [{ provider: '', model: '' }] })
  assert.deepEqual(helpers.nativeFallbackModeDraft({ enabled: true, chain: [{ provider: '', model: '' }] }, 'off'), { enabled: false, chain: [] })
  assert.deepEqual(helpers.nativeFallbackModeDraft({ enabled: true, chain: SPARES }, 'off'), { enabled: false, chain: SPARES })
})

test('spare-model validation stays: at most five, no duplicates, never the main model, on needs a model', () => {
  const h = harness()
  choose(h, 'native-fallback-mode', 'custom')
  assert.match(text(h.byId('native-fallback-error')), /공급자와 모델을 입력하세요/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  edit(h, 'native-chain-0-provider', 'primary'); edit(h, 'native-chain-0-model', 'claire-main')
  assert.match(text(h.byId('native-fallback-error')), /대화 모델과 같은 모델은 예비 모델로 둘 수 없습니다/)
  assert.match(text(h.byId('model-section-targets')), /claire의 기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  edit(h, 'native-chain-0-model', 'other-model')
  for (let index = 1; index < 5; index++) {
    h.click('native-chain-add')
    edit(h, `native-chain-${index}-provider`, 'p'); edit(h, `native-chain-${index}-model`, `m${index}`)
  }
  assert.equal(h.byId('native-chain-add').props.disabled, true, 'at most five')
  edit(h, 'native-chain-4-model', 'm3')
  assert.match(text(h.byId('native-fallback-error')), /중복/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  edit(h, 'native-chain-4-model', 'm4')
  assert.equal(h.byId('model-section-save').props.disabled, false)
  assert.equal(helpers.nativeFallbackValidation({ enabled: true, chain: [] }).length > 0, true)
})

test('priority buttons reorder the conversation spare models and the save sends the new order', async () => {
  const h = harness()
  draftSpares(h)
  assert.equal(h.byId('native-chain-0-up').props.disabled, true)
  assert.equal(h.byId('native-chain-1-down').props.disabled, true)
  assert.equal(text(h.byId('native-chain-1-up')), '위로')
  assert.equal(text(h.byId('native-chain-0-down')), '아래로')
  h.click('native-chain-1-up')
  assert.equal(h.byId('native-chain-0-model').props.value, 'deepseek-flash')
  assert.equal(h.byId('native-chain-1-model').props.value, 'mimo-v2.6-pro')
  h.click('native-chain-0-down')
  h.click('native-chain-0-down')
  assert.equal(h.byId('native-chain-0-model').props.value, 'deepseek-flash', 'the last one stays last')
  assert.equal(h.calls.length, 0)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(lastFallback(h).body.updates[0].native_fallback.chain, [SPARES[1], SPARES[0]])
  assert.deepEqual(helpers.moveChainEntry(['a', 'b', 'c'], 2, -1), ['a', 'c', 'b'])
  assert.deepEqual(helpers.moveChainEntry(['a', 'b', 'c'], 0, -1), ['a', 'b', 'c'])
  assert.deepEqual(helpers.moveChainEntry(['a', 'b', 'c'], 2, 1), ['a', 'b', 'c'])
  assert.deepEqual(helpers.moveChainEntry(['a', 'b'], 0, 2), ['a', 'b'])
})

test('a spare-model-only edit sends only the narrow /fallback-preview body with its frozen expectation', async () => {
  // Task routing is off for `other`: an unscoped store plan would rewrite its skills.disabled
  // (tests/test_model_section_fallback.py). The spare-model save must never start that pass.
  const data = statusFixture()
  data.profiles.find(row => row.name === 'other').routing.enabled = false
  const h = harness(data)
  draftSpares(h)
  assert.match(text(h.byId('model-section-summary')), /대화 예비 모델: 2개 사용/)
  assert.throws(() => h.byId('native-fallback-cost-consent'), 'the save itself is the consent; no checkbox')
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['fallback-preview', 'apply'], 'no store plan, no routing pass')
  assert.deepEqual(h.calls[0].body, {
    expected_revision: 12,
    updates: [{ profile: 'claire', native_fallback: { enabled: true, chain: SPARES } }],
    confirmations: [{ profile: 'claire', scope: 'native', allow_additional_cost: true, allow_task_rerun: false }],
    expected: [{ profile: 'claire', native_fallback: offExpectation }]
  })
  assert.deepEqual(h.calls[1].body, { plan_id: 'fallback-plan' })
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, false, 'every edit was submitted: the page reloads and unlocks by itself')
  assert.throws(() => h.byId('confirm-preview'))
})

test('models and spare models go together to the model targets; a target that cannot take the spare models is skipped by name', async () => {
  const data = statusFixture()
  data.profiles.find(row => row.name === 'other').fallbacks.native.editable = false
  delete data.profiles.find(row => row.name === 'default').fallbacks.native
  const h = harness(data)
  edit(h, 'model-main-model', 'copied-main')
  draftSpares(h)
  h.click('model-target-all')
  const summary = text(h.byId('model-section-summary'))
  assert.match(summary, /대화 예비 모델을 적용하지 않는 프로필: default, other/)
  const targets = text(h.byId('model-section-targets'))
  assert.match(targets, /대화 예비 모델은 적용하지 않습니다\. 이 프로필의 대화 예비 모델은 읽기 전용입니다/)
  assert.match(targets, /대화 예비 모델은 적용하지 않습니다\. 이 프로필의 대화 예비 모델 설정을 확인할 수 없습니다/)
  assert.equal(h.byId('model-section-save').props.disabled, false, 'skipped targets never fail the save')
  await h.click('model-section-save'); await h.flush()
  // The main model changes on a spare-model target, so the spare models are planned only after the
  // models applied, at the revision that apply reported.
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply', 'fallback-preview', 'apply'])
  const body = lastPreview(h).body
  assert.equal(body.save_scope, 'models', 'the models go through the scoped plan')
  assert.deepEqual(body.model_targets, ['default', 'claire', 'other'], 'every target still receives the models')
  assert.equal(body.models.main.model, 'copied-main')
  assert.equal('fallback_updates' in body, false)
  assert.deepEqual(body.expected.map(item => [item.profile, Object.keys(item).sort()]), [
    ['default', ['actual_models', 'models', 'profile']], ['claire', ['actual_models', 'models', 'profile']], ['other', ['actual_models', 'models', 'profile']]])
  const spare = lastFallback(h).body
  assert.equal(spare.expected_revision, 13, 'the revision the models apply reported')
  assert.deepEqual(spare.updates.map(update => update.profile), ['claire'])
  assert.deepEqual(spare.expected, [{ profile: 'claire', native_fallback: offExpectation }])
  assert.deepEqual(helpers.nativeFallbackTargetReason(data.profiles[1]), '')
  assert.match(helpers.nativeFallbackTargetReason(data.profiles[1], false), /확인되지 않았습니다/)
})

test('a bystander without a resolved main model is never part of a spare-model save', async () => {
  // The unscoped plan would have to project `other` and fail ('profile other has no resolved main
  // model', tests/test_model_section_fallback.py); the narrow path never reads it.
  const data = statusFixture()
  const other = data.profiles.find(row => row.name === 'other')
  other.models.main = route('', '', '')
  other.actual_models = {}
  other.routing.enabled = false
  const h = harness(data)
  draftSpares(h)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['fallback-preview', 'apply'])
  assert.equal(JSON.stringify(h.calls).includes('"other"'), false, 'nothing names the bystander')
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, false, 'saved and reloaded')
})

test('a hand-picked target list copies the current spare models; unchanged loaded targets copy nothing', async () => {
  const h = harness()
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.check('model-target-other', true)
  assert.match(text(h.byId('model-section-summary')), /대화 예비 모델: 사용 안 함/)
  await h.click('model-section-save'); await h.flush()
  // Copying the models changes other's main model, which the spare models are checked against: they
  // are planned only after the models applied.
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply', 'fallback-preview', 'apply'])
  const body = lastPreview(h).body
  assert.equal(body.save_scope, 'models')
  assert.deepEqual(body.model_targets, ['claire', 'other'])
  assert.deepEqual(lastFallback(h).body.updates, [
    { profile: 'claire', native_fallback: { enabled: false, chain: [] } },
    { profile: 'other', native_fallback: { enabled: false, chain: [] } }
  ])
  assert.deepEqual(lastFallback(h).body.confirmations, [])
  // When no spare-model target's main model changes, the spare models are validated before the first write.
  const v = harness()
  edit(v, 'model-compression-model', 'new-compression')
  draftSpares(v)
  await v.click('model-section-save'); await v.flush()
  assert.deepEqual(v.calls.map(call => call.operation), ['preview', 'fallback-preview', 'apply', 'fallback-preview', 'apply'])
  assert.deepEqual(v.calls.filter(call => call.operation === 'fallback-preview').map(call => call.body.expected_revision), [12, 13])
  // A model-only edit with the default target list never touches the spare models.
  const g = harness()
  edit(g, 'model-main-model', 'model-only')
  await g.click('model-section-save'); await g.flush()
  assert.equal(lastPreview(g).body.save_scope, 'models')
  assert.equal('fallback_updates' in lastPreview(g).body, false)
})

test('the whole-page save carries the spare models once, to the model targets', async () => {
  const h = harness(delegationStatus())
  h.setResponder(operation => operation === 'preview'
    ? { plan_id: 'combined-plan', changes: [{ profile: 'claire', field: 'native_fallback', before: 'off', after: 'on' }], warnings: [] }
    : { status: 'applied', revision: 13 })
  draftSpares(h)
  h.check('model-target-other', true)
  assert.match(text(h.byId('draft-reference-summary')), /대화 예비 모델 적용 2개 \(claire, other\)/)
  globalButton(h, '저장')
  await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  const request = h.calls[0].body
  assert.deepEqual(request.model_targets, ['claire', 'other'])
  assert.deepEqual(request.fallback_updates.map(u => u.profile), ['claire', 'other'], 'each target once')
  assert.deepEqual(request.fallback_updates.map(u => Object.keys(u).sort()), [['native_fallback', 'profile'], ['native_fallback', 'profile']])
  assert.deepEqual(request.fallback_confirmations.map(x => [x.profile, x.scope, x.allow_task_rerun]), [['claire', 'native', false], ['other', 'native', false]])
  assert.equal(request.expected.filter(item => 'native_fallback' in item).length, 2)
  assert.equal(h.calls.some(x => x.operation === 'fallback-preview'), false)
  assert.deepEqual(h.calls.filter(x => x.operation === 'apply').map(x => x.body), [{ plan_id: 'combined-plan' }])
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, false, 'a confirmed save reloads and unlocks by itself')
})

test('the stored routed-job and default-delegation values are never written with the spare models', async () => {
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
  draftSpares(h)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(lastFallback(h).body.updates.map(update => Object.keys(update).sort()), [['native_fallback', 'profile']])
  assert.deepEqual(lastFallback(h).body.confirmations.map(row => row.scope), ['native'])
  draftSpares(h, [SPARES[1]])
  globalButton(h, '저장'); await h.flush()
  const whole = lastPreview(h).body
  assert.deepEqual(whole.fallback_updates.map(update => Object.keys(update).sort()), [['native_fallback', 'profile']])
  assert.deepEqual(whole.fallback_confirmations.map(row => row.scope), ['native'])
  assert.equal(JSON.stringify(h.calls).includes('routing_fallback') || JSON.stringify(h.calls).includes('delegation_fallback'), false)
})

test('a spare-model save cannot apply after the source changes; unsupported or read-only spare models stay read only', async () => {
  const h = harness()
  draftSpares(h)
  let resolvePreview
  h.setResponder(operation => operation === 'fallback-preview' ? new Promise(resolve => { resolvePreview = resolve }) : { status: 'applied' })
  const pending = h.click('model-section-save')
  h.state.connectionId.value = 'other-source'; h.render()
  resolvePreview({ plan_id: 'stale-plan', changes: [{ profile: 'claire', field: 'fallbacks.native' }] })
  await pending
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  const unsupported = harness(statusFixture({ fallback_capabilities: { ...helpers.SUPPORTED_FALLBACK_CAPABILITIES, native_execution: 'unknown' } }))
  assert.match(text(unsupported.byId('native-fallback-unsupported')), /읽기 전용/)
  assert.equal(selectNode(unsupported, 'native-fallback-mode').props.disabled, true)
  assert.throws(() => unsupported.byId('routing-fallback-enabled'))
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').fallbacks.native = nativeState({ editable: false, enabled: true, chain: [SPARES[0]], actual_chain: [SPARES[0]] })
  const readonly = harness(data)
  assert.match(text(readonly.byId('native-fallback-readonly')), /읽기 전용/)
  assert.equal(selectNode(readonly, 'native-fallback-mode').props.disabled, true)
  assert.equal(readonly.byId('native-chain-0-model').props.disabled, true)
  assert.equal(readonly.byId('native-chain-0-up').props.disabled, true)
  readonly.click('model-target-all')
  assert.match(text(readonly.byId('model-section-fallback-skipped')), /default, claire, other/)
  readonly.click('model-section-save')
  await readonly.flush()
  assert.equal('fallback_updates' in lastPreview(readonly).body, false, 'a read-only source copies only the models')
  assert.equal(readonly.calls.some(call => call.operation === 'fallback-preview'), false)
})

test('without confirmed fallback capabilities a hand-picked copy sends only the models and names every target as skipped', async () => {
  const data = statusFixture()
  delete data.fallback_capabilities
  const h = harness(data)
  assert.throws(() => h.byId('model-section-fallback-skipped'), 'nothing is copied yet')
  h.click('model-target-all')
  assert.match(text(h.byId('model-section-fallback-skipped')), /대화 예비 모델을 적용하지 않는 프로필: default, claire, other/)
  assert.match(text(h.byId('model-section-write-other')), /other: 대화 모델 저장 · 대화 예비 모델은 그대로 둠\(이 연결에서는 대화 예비 모델을 안전하게 바꿀 수 있는지 확인되지 않았습니다\.\)/)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  assert.equal(lastPreview(h).body.save_scope, 'models')
  assert.deepEqual(lastPreview(h).body.model_targets, ['default', 'claire', 'other'])
})

test('managed elsewhere, drift and warnings: one short note each, only when they apply', () => {
  const plain = harness()
  for (const id of ['native-fallback-managed', 'native-fallback-drift', 'native-fallback-warnings']) assert.throws(() => plain.byId(id), id)
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').fallbacks.native = nativeState({ managed: false, enabled: true, chain: [SPARES[0]], actual_chain: [SPARES[1]], drift: true, warnings: ['custom_providers_present'] })
  const h = harness(data)
  assert.match(text(h.byId('native-fallback-managed')), /다른 설정에서 관리됩니다/)
  assert.match(text(h.byId('native-fallback-drift')), /실제로 쓰는 예비 모델이 다릅니다.*deepseek\/deepseek-flash/)
  assert.match(text(h.byId('native-fallback-warnings')), /custom_providers_present/)
})

test('a spare-model edit blocks the model save while the loaded profile cannot take it or changed elsewhere', () => {
  const h = harness()
  draftSpares(h)
  assert.equal(h.byId('model-section-save').props.disabled, false)
  const readonly = structuredClone(statusFixture())
  readonly.profiles.find(row => row.name === 'claire').fallbacks.native.editable = false
  h.setData(readonly); h.render()
  assert.match(text(h.byId('model-section-targets')), /claire: 이 프로필의 대화 예비 모델은 읽기 전용입니다\. 이 화면을 연 뒤 바뀌어, 바꾼 대화 예비 모델은 어느 프로필에도 저장할 수 없습니다/)
  assert.equal(h.byId('model-section-save').props.disabled, true, 'the loaded profile own edit is never dropped silently')
  const g = harness()
  draftSpares(g)
  const changed = structuredClone(statusFixture())
  changed.profiles.find(row => row.name === 'claire').fallbacks.native = nativeState({ enabled: true, chain: [{ provider: 'elsewhere', model: 'external-spare' }], actual_chain: [{ provider: 'elsewhere', model: 'external-spare' }] })
  g.setData(changed); g.render()
  assert.match(text(g.byId('model-section-targets')), /claire 프로필의 대화 예비 모델 값이 바뀌었습니다/)
  assert.equal(g.byId('model-section-save').props.disabled, true)
  assert.equal(g.byId('global-save').props.disabled, true)
  assert.equal(g.calls.length, 0)
})

test('a spare-model-only save never sends the routing of other profiles, so a routing switch changed elsewhere does not block it', async () => {
  const h = harness()
  draftSpares(h)
  const toggled = structuredClone(statusFixture())
  toggled.profiles.find(row => row.name === 'other').routing.enabled = false
  h.setData(toggled); h.render()
  assert.match(text(h.byId('live-drift-alert')), /other 프로필의 작업 라우팅 사용 여부/)
  assert.equal(h.byId('global-save').props.disabled, true, 'the unscoped whole-page save would send it')
  assert.equal(h.byId('model-section-save').props.disabled, false)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['fallback-preview', 'apply'])
  assert.deepEqual(h.calls[0].body.expected, [{ profile: 'claire', native_fallback: offExpectation }])
  // With a model edit the models plan is blocked by the same drift, as before.
  const g = harness()
  edit(g, 'model-main-model', 'edited')
  g.setData(structuredClone(toggled)); g.render()
  assert.equal(g.byId('model-section-save').props.disabled, true)
})

test('a spare that differs from the new main model only in case is blocked before any request', async () => {
  // Repro: main primary/new-main, spare primary/NEW-MAIN. The service compares both IDs case-folded
  // (service.py), so the spare step would be refused only after the models had been saved.
  const h = harness()
  edit(h, 'model-main-model', 'new-main')
  draftSpares(h, [{ provider: 'primary', model: 'NEW-MAIN' }])
  assert.match(text(h.byId('native-fallback-error')), /대화 모델과 같은 모델은 예비 모델로 둘 수 없습니다/)
  assert.match(text(h.byId('model-section-targets')), /claire의 기본 대화 모델과 대화 예비 모델은 달라야 합니다\(대소문자만 다른 경우 포함\)/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.byId('model-section-save').props.onClick(); await h.flush()
  assert.deepEqual(h.calls, [], 'no /preview, no /apply')
  // The provider is case-folded too. A hand-picked target receives the copied main model, so it is
  // checked against that projected model, not its stored one.
  const g = harness()
  draftSpares(g, [{ provider: 'PRIMARY', model: 'Other-Main' }])
  g.check('model-target-other', true)
  assert.equal(g.byId('model-section-save').props.disabled, false, 'other will have claire-main, not other-main')
  assert.match(text(g.byId('model-section-write-other')), /other: 대화 모델, 대화 예비 모델\(1개 사용\) 저장/)
  edit(g, 'model-main-model', 'other-main')
  assert.match(text(g.byId('model-section-targets')), /claire의 기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
  assert.equal(g.byId('model-section-save').props.disabled, true)
  // The step-3 body builder runs the same check, so a retained callback cannot get past it either:
  // it is called before the first apply of the save.
  const snapshot = { revision: 12, profile: 'claire', profiles: statusFixture().profiles, modelTargets: ['claire'],
    draft: { models: { ...statusFixture().profiles[1].models, main: route('primary', 'new-main', 'high') } },
    fallbackWrite: { targets: ['claire'], value: { enabled: true, chain: [{ provider: 'primary', model: 'NEW-MAIN' }] } } }
  const built = helpers.buildModelSectionFallbackBody(snapshot, 13)
  assert.equal(built.body, null)
  assert.match(built.errors.join(' '), /claire의 기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
  assert.ok(helpers.buildModelSectionFallbackBody({ ...snapshot, fallbackWrite: { ...snapshot.fallbackWrite, value: { enabled: true, chain: [{ provider: 'primary', model: 'other-spare' }] } } }, 13).body)
  // Every target that receives the spare models: one that is not a model target keeps its stored main.
  const both = { ...snapshot, fallbackWrite: { targets: ['claire', 'other'], value: { enabled: true, chain: [{ provider: 'Primary', model: 'OTHER-main' }] } } }
  assert.match(helpers.buildModelSectionFallbackBody(both, 13).errors.join(' '), /other의 기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
})

test('a spare is compared with the stored main model only, never the actual one, like the service', async () => {
  // Stored main primary/claire-main, actual main primary/runtime-main. The service compares with the
  // stored entry (tests/test_model_section_fallback.py), so a spare equal to the actual one is valid.
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').actual_models.main = route('primary', 'runtime-main', 'high')
  const h = harness(data)
  draftSpares(h, [{ provider: 'PRIMARY', model: 'RUNTIME-MAIN' }])
  assert.throws(() => h.byId('native-fallback-error'))
  assert.equal(h.byId('model-section-save').props.disabled, false)
  await h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['fallback-preview', 'apply'])
  assert.deepEqual(h.calls[0].body.updates, [{ profile: 'claire', native_fallback: { enabled: true, chain: [{ provider: 'PRIMARY', model: 'RUNTIME-MAIN' }] } }])
  // The stored main model, in any case, is still refused before any request.
  const g = harness(structuredClone(data))
  draftSpares(g, [{ provider: 'Primary', model: 'Claire-Main' }])
  assert.match(text(g.byId('model-section-targets')), /claire의 기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
  assert.equal(g.byId('model-section-save').props.disabled, true)
  assert.deepEqual(g.calls, [])
})

test('a save callback kept from before a refresh made the source spare models read-only sends nothing', async () => {
  for (const change of ['read-only', 'capabilities']) {
    const h = harness()
    draftSpares(h)
    const retained = h.byId('model-section-save').props.onClick
    const retainedAll = h.byId('global-save').props.onClick
    const refreshed = structuredClone(statusFixture())
    if (change === 'read-only') refreshed.profiles.find(row => row.name === 'claire').fallbacks.native.editable = false
    else delete refreshed.fallback_capabilities
    // The newest status reaches the page, but the retained callbacks come from the render before it.
    h.setData(refreshed); h.render()
    assert.equal(h.byId('model-section-save').props.disabled, true, change)
    retained(); retainedAll(); await h.flush()
    assert.deepEqual(h.calls, [], change)
  }
})

test('the page refuses up front every spare-model token and duplicate the service refuses', () => {
  const cases = JSON.parse(readFileSync(new URL('./fixtures/fallback_token_cases.json', import.meta.url), 'utf8'))
  const valid = (provider, model) => helpers.nativeFallbackValidation({ enabled: true, chain: [{ provider, model }] }) === ''
  for (const [provider, ok] of cases.providers) assert.equal(valid(provider, 'gpt-6-astra'), ok, `provider ${JSON.stringify(provider)}`)
  for (const [model, ok] of cases.models) assert.equal(valid('xiaomi', model), ok, `model ${JSON.stringify(model)}`)
  assert.match(helpers.nativeFallbackValidation({ enabled: true, chain: [{ provider: 'Xiaomi', model: 'Spare' }, { provider: 'xiaomi', model: 'spare' }] }), /중복/)
  assert.equal(helpers.foldedRouteIdentity({ provider: 'A', model: 'B[1M]' }), helpers.foldedRouteIdentity({ provider: 'a', model: 'b[1m]' }))
  const h = harness()
  draftSpares(h, [{ provider: 'xiaomi', model: 'spare ' }])
  assert.match(text(h.byId('native-fallback-error')), /앞뒤 공백이나 쓸 수 없는 문자/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
})

test('a refresh that makes the loaded profile spare models non-editable blocks their write even when it is not a target', async () => {
  const h = harness()
  draftSpares(h)
  h.click('model-target-none')
  h.check('model-target-other', true)
  assert.equal(h.byId('model-section-save').props.disabled, false, 'other can take the drafted spare models')
  const readonly = structuredClone(statusFixture())
  readonly.profiles.find(row => row.name === 'claire').fallbacks.native.editable = false
  h.setData(readonly); h.render()
  assert.match(text(h.byId('model-section-targets')), /claire: 이 프로필의 대화 예비 모델은 읽기 전용입니다\. 이 화면을 연 뒤 바뀌어, 바꾼 대화 예비 모델은 어느 프로필에도 저장할 수 없습니다\. 상태를 새로고침해/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.byId('model-section-save').props.onClick(); await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'fallback-preview'), false)
  assert.deepEqual(h.calls, [])
  // The same when the capabilities stop being confirmed.
  const g = harness()
  draftSpares(g)
  const unconfirmed = structuredClone(statusFixture())
  delete unconfirmed.fallback_capabilities
  g.setData(unconfirmed); g.render()
  assert.match(text(g.byId('model-section-targets')), /claire: 이 연결에서는 대화 예비 모델을 안전하게 바꿀 수 있는지 확인되지 않았습니다\. 이 화면을 연 뒤 바뀌어/)
  assert.equal(g.byId('model-section-save').props.disabled, true)
})

test('a changed spare model with no target, or a vanished ticked target, blocks the save by name', () => {
  const h = harness()
  draftSpares(h)
  h.click('model-target-none')
  assert.match(text(h.byId('model-section-targets')), /적용 대상이 0개입니다/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.check('model-target-claire', true)
  h.check('model-target-other', true)
  assert.equal(h.byId('model-section-save').props.disabled, false)
  const fewer = structuredClone(statusFixture()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  h.setData(fewer); h.render()
  assert.equal(h.byId('model-target-other').props.checked, true)
  assert.match(text(h.byId('model-section-targets')), /더 이상 찾을 수 없어 저장하지 않습니다.*other/)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('page-vanished-alert')), /other/)
  h.check('model-target-other', false)
  assert.equal(h.byId('model-section-save').props.disabled, false)
})

test('a save that leaves another edit unsaved never reloads over it, in either direction', async () => {
  const data = statusFixture()
  data.profiles.forEach((row, index) => { row.timeouts = timeoutDto(index + 3) })
  const h = harness(data)
  draftSpares(h)
  edit(h, 'delegate-total-minutes', '7')
  await h.click('model-section-save'); await h.flush()
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 1)
  assert.match(text(h.tree), /다른 곳에 저장하지 않은 편집이 있어 자동으로 다시 불러오지 않았습니다/)
  assert.equal(h.byId('delegate-total-minutes').props.value, '7', 'the unsaved time limit is still on the page')
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, true, 'locked until an explicit reload')
  globalButton(h, '실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, false)
  // The reverse: a time-limit save leaves the spare-model edit unsaved and does not reload over it.
  const g = harness(structuredClone(data))
  draftSpares(g)
  edit(g, 'delegate-total-minutes', '7')
  await g.click('timeouts-save'); await g.flush()
  assert.equal('fallback_updates' in lastPreview(g).body, false)
  assert.equal(selectNode(g, 'native-fallback-mode').props.value, 'custom', 'the spare-model draft is kept')
  assert.equal(g.byId('native-chain-1-model').props.value, 'deepseek-flash')
})

test('one save locks the spare-model editor until its one apply completes', async () => {
  const h = harness(delegationStatus())
  draftSpares(h)
  let resolve
  h.setResponder(operation => operation === 'preview' ? new Promise(r => { resolve = r }) : { status: 'applied' })
  globalButton(h, '저장')
  assert.equal(selectNode(h, 'native-fallback-mode').props.disabled, true)
  assert.equal(h.byId('native-chain-0-up').props.disabled, true)
  resolve({ plan_id: 'obsolete-combined', changes: [{ profile: 'claire', field: 'native_fallback' }] })
  await h.flush()
  assert.throws(() => h.byId('confirm-preview'))
  assert.equal(h.calls.filter(x => x.operation === 'apply').length, 1)
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

test('whole-page model-only preview preserves untouched fallback policies', async () => {
  const h = harness(delegationStatus())
  edit(h, 'model-main-model', 'changed-main')
  globalButton(h, '저장')
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.equal('fallback_updates' in body, false)
  assert.equal('fallback_confirmations' in body, false)
})

test('combined validation compares the conversation spare models with the draft main model', async () => {
  const h = harness(delegationStatus())
  draftSpares(h)
  edit(h, 'model-main-provider', 'xiaomi')
  edit(h, 'model-main-model', 'mimo-v2.6-pro')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  globalButton(h, '저장')
  await h.flush()
  assert.equal(h.calls.length, 0)
  assert.match(text(h.tree), /기본 대화 모델과 대화 예비 모델은 달라야 합니다/)
})

test('a saved spare-model copy is not repeated on a later model-only save', async () => {
  const data = delegationStatus()
  const h = harness(data)
  h.setResponder(operation => ['preview', 'fallback-preview'].includes(operation)
    ? { plan_id: 'copy-plan', changes: [{ profile: 'other', field: 'native_fallback', before: null, after: { enabled: false, chain: [] } }], warnings: [] }
    : { status: 'applied', revision: 13 })
  h.check('model-target-other', true)
  await h.click('model-section-save')
  await h.flush()
  assert.deepEqual(lastFallback(h).body.updates.map(update => update.profile), ['claire', 'other'])
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 2, 'the models, then the spare models')
  // Someone subsequently changed the former copy target. Do not replay the copy.
  data.revision = 13
  data.profiles.find(x => x.name === 'other').fallbacks.native = nativeState({
    managed: true, enabled: true, chain: [{ provider: 'independent', model: 'other-spare' }], consent: consent('native')
  })
  h.setData(data)
  globalButton(h, '상태 새로고침')
  await h.flush()
  assert.equal(h.byId('model-target-other').props.checked, true, 'the hand-picked list stays')
  edit(h, 'model-main-model', 'later-model-only')
  const before = h.calls.filter(c => c.operation === 'fallback-preview').length
  await h.click('model-section-save')
  await h.flush()
  assert.equal(lastPreview(h).body.save_scope, 'models')
  assert.equal(h.calls.filter(c => c.operation === 'fallback-preview').length, before, 'no spare-model copy is replayed')
  // A new explicit target action does create a new one-time copy intent.
  h.check('model-target-other', false)
  await h.click('model-section-save')
  await h.flush()
  assert.deepEqual(lastFallback(h).body.updates.map(update => update.profile), ['claire'])
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
  choose(h, 'native-fallback-mode', 'custom')
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
