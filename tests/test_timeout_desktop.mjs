import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helpers = new Function(`${source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')}\nreturn {
  copyProfileDraft, copyTimeoutBaseline, validTimeoutsDto, parseTimeoutSeconds,
  timeoutDraftChanged, timeoutRevisionMatches, buildTimeoutUpdate, buildCombinedPreviewBody
}`)()

const route = (provider, model, reasoning = 'high') => ({ provider, model, reasoning })
const timeoutDto = (overrides = {}) => ({
  schema: 1,
  revision: 8,
  delegate_total_seconds: 0,
  routed_total_seconds: 3600,
  editable: true,
  warnings: ['fixture warning'],
  ...overrides
})
const profile = (name, timeouts = timeoutDto()) => ({
  name,
  models: {
    main: route('provider', `${name}-main`),
    delegation: route('provider', `${name}-delegate`),
    compression: route('provider', `${name}-compression`),
    title: route('provider', `${name}-title`, 'none')
  },
  actual_models: {
    main: route('provider', `${name}-main`),
    delegation: route('provider', `${name}-delegate`)
  },
  routing: {
    enabled: name === 'claire',
    heavy: { follow: 'main', custom: null },
    light: { follow: 'delegation', custom: null },
    fallback: { enabled: false, heavy: null, light: null }
  },
  fallbacks: {
    native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null },
    routing: { enabled: false, heavy: null, light: null, consent: null },
    delegation: { managed: false, editable: true, mode: 'default', chain: [], actual_mode: 'default', actual_chain: [], drift: false, warnings: [], consent: null }
  },
  drift: [],
  ...(timeouts === undefined ? {} : { timeouts })
})
const statusFixture = (overrides = {}) => ({
  revision: 12,
  current_profile: 'claire',
  fallback_capabilities: {
    native_trigger: 'hermes_runtime',
    native_execution: 'continue_conversation',
    native_reasoning: 'profile_overrides',
    routing_trigger: 'subscription_exhaustion_before_tools',
    routing_execution: 'fresh_task',
    routing_max_retries: 1
  },
  profiles: [
    profile('default', timeoutDto({ revision: 3, delegate_total_seconds: 0, routed_total_seconds: 1800 })),
    profile('claire', timeoutDto({ revision: 8 })),
    profile('other', timeoutDto({ revision: 11, delegate_total_seconds: 12, routed_total_seconds: 7200 }))
  ],
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
  let responder = operation => operation === 'preview' || operation === 'fallback-preview'
    ? { plan_id: 'timeout-plan', changes: [], warnings: [] }
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
  const flush = async () => { for (let index = 0; index < 30; index++) await Promise.resolve(); render() }
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
  const selectProfile = name => {
    const select = find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'profile-select'))
    select.props.onValueChange(name)
    render()
  }
  render()
  return {
    calls, state, render, byId, click, clickLabel, input, check, selectProfile, flush,
    get tree() { return tree },
    data: () => data,
    setData(value) { data = value },
    setResponder(fn) { responder = fn }
  }
}

function globalSave(h) { return h.click('global-save') }

test('DTO validation fails closed and copies only supported timeout settings, not warnings', () => {
  const supported = profile('claire')
  assert.equal(helpers.validTimeoutsDto(supported.timeouts), true)
  assert.deepEqual(helpers.copyProfileDraft(supported).timeouts, {
    schema: 1, revision: 8, delegate_total_seconds: 0, routed_total_seconds: 3600, editable: true
  })
  assert.equal('warnings' in helpers.copyProfileDraft(supported).timeouts, false)
  assert.equal('timeouts' in helpers.copyProfileDraft(profile('old', null)), false)
  const invalid = [
    timeoutDto({ schema: 2 }),
    timeoutDto({ revision: 1.5 }),
    timeoutDto({ delegate_total_seconds: -1 }),
    timeoutDto({ delegate_total_seconds: Infinity }),
    timeoutDto({ routed_total_seconds: NaN }),
    timeoutDto({ routed_total_seconds: true }),
    timeoutDto({ editable: 'true' }),
    timeoutDto({ warnings: 'not-an-array' }),
    timeoutDto({ warnings: [7] })
  ]
  for (const dto of invalid) {
    assert.equal(helpers.validTimeoutsDto(dto), false)
    assert.equal('timeouts' in helpers.copyProfileDraft(profile('invalid', dto)), false)
  }
})

test('time fields reject negative, boolean, blank and non-finite input without an arbitrary upper cap', () => {
  for (const value of [-1, true, false, '', '  ', 'Infinity', '-0.1', NaN, Infinity, -Infinity]) {
    assert.equal(helpers.parseTimeoutSeconds(value), null, `reject ${String(value)}`)
  }
  assert.equal(helpers.parseTimeoutSeconds(0), 0)
  assert.equal(helpers.parseTimeoutSeconds('12.5'), 12.5)
  assert.equal(helpers.parseTimeoutSeconds('1e100'), 1e100)
})

test('actual page renders two accessible numeric TOTAL fields with the contract explanations', () => {
  const h = harness()
  const delegate = h.byId('delegate-total-seconds')
  const routed = h.byId('routed-total-seconds')
  assert.equal(delegate.props['aria-label'], '일반 서브 에이전트 전체 실행 시간')
  assert.equal(routed.props['aria-label'], '라우팅 서브 에이전트 전체 실행 시간')
  assert.equal(delegate.props.type, 'number')
  assert.equal(routed.props.type, 'number')
  assert.equal(delegate.props.min, 0)
  assert.equal(routed.props.min, 0)
  assert.equal(delegate.props.step, 'any')
  assert.equal(routed.props.step, 'any')
  assert.equal(delegate.props.value, 0)
  assert.equal(routed.props.value, 3600)
  assert.equal(delegate.props.disabled, false)
  assert.equal(routed.props.disabled, false)
  const copy = text(h.tree)
  for (const phrase of [
    '전체 실행 시간 제한 (TOTAL)', '초 (seconds)', 'delegation.child_timeout_seconds',
    '협조적 중단을 요청', '실행 프로세스를 정리', '새 작업은 시작할 때 현재 정책을 스냅샷',
    '요청·도구별 제한과 반복 횟수 제한', '모델·라우팅·폴백 적용 대상과는 독립적'
  ]) assert.ok(copy.includes(phrase), `missing UI explanation: ${phrase}`)
})

test('unsupported old-backend timeout DTO stays blank, disabled, and absent from whole-page save', async () => {
  const data = statusFixture()
  delete data.profiles.find(row => row.name === 'claire').timeouts
  const h = harness(data)
  assert.equal(h.byId('delegate-total-seconds').props.value, '')
  assert.equal(h.byId('routed-total-seconds').props.value, '')
  assert.equal(h.byId('delegate-total-seconds').props.disabled, true)
  assert.equal(h.byId('routed-total-seconds').props.disabled, true)
  assert.match(text(h.tree), /UNSUPPORTED/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.equal('timeout_updates' in body, false)
})

test('whole-page save sends only the loaded profile timeout update, numeric seconds, and loaded timeout revision', async () => {
  for (const [id, value, expected] of [
    ['delegate-total-seconds', '75.5', { delegate_total_seconds: 75.5, routed_total_seconds: 3600 }],
    ['routed-total-seconds', '5400', { delegate_total_seconds: 0, routed_total_seconds: 5400 }]
  ]) {
    const h = harness()
    h.input(id, value)
    globalSave(h)
    await h.flush()
    const body = h.calls.find(call => call.operation === 'preview').body
    assert.deepEqual(body.timeout_updates, [
      { profile: 'default', expected_revision: 3, ...expected },
      { profile: 'claire', expected_revision: 8, ...expected },
      { profile: 'other', expected_revision: 11, ...expected }
    ])
    assert.deepEqual(body.model_targets, ['default', 'claire', 'other'])
    assert.deepEqual(body.timeout_updates.map(update => update.profile), ['default', 'claire', 'other'])
    assert.equal('fallback_updates' in body, false)
  }
})

test('unchanged limits are omitted; edits use selected source values across selected timeout targets', async () => {
  const unchanged = harness()
  unchanged.input('model-main-model', 'model-only-change')
  globalSave(unchanged)
  await unchanged.flush()
  assert.equal('timeout_updates' in unchanged.calls.find(call => call.operation === 'preview').body, false)

  const h = harness()
  h.input('delegate-total-seconds', '99')
  h.selectProfile('other')
  assert.equal(h.byId('delegate-total-seconds').props.value, 12)
  assert.equal(h.byId('routed-total-seconds').props.value, 7200)
  h.input('delegate-total-seconds', '22')
  globalSave(h)
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 22, routed_total_seconds: 7200 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 22, routed_total_seconds: 7200 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 22, routed_total_seconds: 7200 }
  ])
})

test('read-only supported DTO displays actual values but cannot edit or add timeout_updates', async () => {
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').timeouts.editable = false
  const h = harness(data)
  assert.equal(h.byId('delegate-total-seconds').props.value, 0)
  assert.equal(h.byId('routed-total-seconds').props.value, 3600)
  assert.equal(h.byId('delegate-total-seconds').props.disabled, true)
  assert.match(text(h.tree), /시간 제한은 읽기 전용/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  assert.equal('timeout_updates' in h.calls.find(call => call.operation === 'preview').body, false)
})

test('invalid edited values are reported locally and never sent to preview', async () => {
  const h = harness()
  h.input('delegate-total-seconds', '-1')
  assert.match(text(h.tree), /0 이상의 유한한 초 단위 숫자/)
  globalSave(h)
  await h.flush()
  assert.equal(h.calls.length, 0)
})

test('timeout revision replacement blocks overwrite until explicit refresh establishes a new baseline', async () => {
  const h = harness()
  h.input('delegate-total-seconds', '90')
  const next = structuredClone(h.data())
  const row = next.profiles.find(item => item.name === 'claire')
  row.timeouts.revision = 9
  row.timeouts.delegate_total_seconds = 5
  row.timeouts.routed_total_seconds = 7200
  h.setData(next)
  h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.match(text(h.tree), /revision이 바뀌었습니다/)
  assert.equal(h.calls.length, 0)

  h.clickLabel('상태 새로고침')
  await h.flush()
  assert.equal(h.byId('delegate-total-seconds').props.value, 5)
  assert.equal(h.byId('routed-total-seconds').props.value, 7200)
  h.input('delegate-total-seconds', '6')
  globalSave(h)
  await h.flush()
  assert.deepEqual(h.calls.find(call => call.operation === 'preview').body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 6, routed_total_seconds: 7200 },
    { profile: 'claire', expected_revision: 9, delegate_total_seconds: 6, routed_total_seconds: 7200 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 6, routed_total_seconds: 7200 }
  ])
})

test('immutable timeout save snapshot does not drift and incoming revision change cancels before apply', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('routed-total-seconds', '9000')
  globalSave(h)
  const captured = structuredClone(h.calls[0].body)
  assert.deepEqual(captured.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 0, routed_total_seconds: 9000 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, routed_total_seconds: 9000 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 0, routed_total_seconds: 9000 }
  ])
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').timeouts.revision = 9
  h.setData(newer)
  h.render()
  assert.deepEqual(h.calls[0].body, captured)
  resolvePreview({ plan_id: 'stale-timeout-plan', changes: [] })
  await h.flush()
  assert.deepEqual(h.calls[0].body, captured)
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.match(text(h.tree), /revision이 바뀌었습니다/)
})

test('connection change during timeout validation cancels the old scope without carrying its draft forward', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('routed-total-seconds', '7654')
  globalSave(h)
  assert.deepEqual(h.calls[0].body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 0, routed_total_seconds: 7654 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, routed_total_seconds: 7654 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 0, routed_total_seconds: 7654 }
  ])
  h.state.connectionId.value = 'different-connection'
  h.render()
  resolvePreview({ plan_id: 'old-connection-plan', changes: [] })
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.equal(h.byId('routed-total-seconds').props.value, 3600)
})

test('independent fallback save does not copy or save total-runtime limits', async () => {
  const h = harness()
  h.input('routed-total-seconds', '9999')
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').timeouts.revision = 9
  h.setData(newer)
  h.render()
  assert.equal(h.byId('routed-total-seconds').props.disabled, true)
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  h.click('native-fallback-save')
  await h.flush()
  const body = h.calls.find(call => call.operation === 'fallback-preview').body
  assert.equal('timeout_updates' in body, false)
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
})

test('timeout helper emits one profile-local update and rejects malformed, stale, or invalid values', () => {
  const dto = timeoutDto()
  const draft = helpers.copyProfileDraft(profile('claire', dto)).timeouts
  const baseline = helpers.copyTimeoutBaseline(dto)
  const changed = { ...draft, delegate_total_seconds: '0', routed_total_seconds: '1e100' }
  const built = helpers.buildTimeoutUpdate('claire', changed, baseline, dto)
  assert.deepEqual(built, {
    changed: true,
    update: { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, routed_total_seconds: 1e100 },
    error: ''
  })
  assert.equal(helpers.timeoutDraftChanged(draft, baseline), false)
  assert.equal(helpers.timeoutRevisionMatches(baseline, timeoutDto({ revision: 9 })), false)
  assert.match(helpers.buildTimeoutUpdate('claire', changed, baseline, timeoutDto({ revision: 9 })).error, /revision/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, routed_total_seconds: Infinity }, baseline, dto).error, /유한한/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, delegate_total_seconds: true }, baseline, dto).error, /유한한/)
})
