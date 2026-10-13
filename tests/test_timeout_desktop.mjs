import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helpers = new Function(`${source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')}\nreturn {
  copyProfileDraft, copyTimeoutBaseline, validTimeoutsDto, parseTimeoutMinutes,
  timeoutDraftChanged, timeoutRevisionMatches, buildTimeoutUpdate, buildTimeoutUpdates,
  projectTimeoutSeconds, splitRoutingSupported, eligibleTimeoutTargets, buildCombinedPreviewBody
}`)()

const route = (provider, model, reasoning = 'high') => ({ provider, model, reasoning })
const timeoutDto = (overrides = {}) => ({
  schema: 1,
  revision: 8,
  delegate_total_seconds: 0,
  routed_total_seconds: 3600,
  editable: true,
  split_routing_supported: true,
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

test('timeout DTOs fail closed and legacy projection preserves the original split-capability signal', () => {
  const supported = profile('claire')
  assert.equal(helpers.validTimeoutsDto(supported.timeouts), true)
  assert.deepEqual(helpers.copyProfileDraft(supported).timeouts, {
    schema: 1, revision: 8, editable: true, split_routing_supported: true,
    delegate_total_minutes: 0, routed_light_total_minutes: 60, routed_heavy_total_minutes: 60
  })
  assert.deepEqual(helpers.projectTimeoutSeconds(supported.timeouts), {
    delegate_total_seconds: 0, routed_light_total_seconds: 3600, routed_heavy_total_seconds: 3600
  })
  assert.equal('timeouts' in helpers.copyProfileDraft(profile('old', null)), false)
  const v2 = { schema: 2, revision: 8, delegate_total_seconds: 30, routed_light_total_seconds: 900,
    routed_heavy_total_seconds: 7200, editable: true, split_routing_supported: true, warnings: [] }
  assert.deepEqual(helpers.projectTimeoutSeconds(v2), {
    delegate_total_seconds: 30, routed_light_total_seconds: 900, routed_heavy_total_seconds: 7200
  })
  assert.equal(helpers.validTimeoutsDto({ ...v2, routed_total_seconds: 3600 }), false)
  const invalid = [
    timeoutDto({ schema: 2 }), timeoutDto({ revision: 1.5 }), timeoutDto({ delegate_total_seconds: -1 }),
    timeoutDto({ delegate_total_seconds: Infinity }), timeoutDto({ routed_total_seconds: NaN }),
    timeoutDto({ routed_total_seconds: true }), timeoutDto({ editable: 'true' }),
    timeoutDto({ warnings: 'not-an-array' }), timeoutDto({ warnings: [7] })
  ]
  for (const dto of invalid) {
    assert.equal(helpers.validTimeoutsDto(dto), false)
    assert.equal('timeouts' in helpers.copyProfileDraft(profile('invalid', dto)), false)
  }
})

test('minute input validation rejects blank, boolean, negative and non-finite values while allowing fractions and large finite values', () => {
  for (const value of [-1, true, false, '', '  ', 'Infinity', '-0.1', NaN, Infinity, -Infinity]) {
    assert.equal(helpers.parseTimeoutMinutes(value), null, `reject ${String(value)}`)
  }
  assert.equal(helpers.parseTimeoutMinutes(0), 0)
  assert.equal(helpers.parseTimeoutMinutes('0.5'), 0.5)
  assert.equal(helpers.parseTimeoutMinutes('12.5'), 12.5)
  assert.equal(helpers.parseTimeoutMinutes('1e100'), 1e100)
})

test('actual page renders three accessible minute fields and independently inherited legacy role values', () => {
  const h = harness()
  const delegate = h.byId('delegate-total-minutes')
  const light = h.byId('routed-light-total-minutes')
  const heavy = h.byId('routed-heavy-total-minutes')
  assert.equal(delegate.props['aria-label'], '일반 서브 에이전트 전체 실행 시간 (분)')
  assert.equal(light.props['aria-label'], '라우팅 Light 전체 실행 시간 (분)')
  assert.equal(heavy.props['aria-label'], '라우팅 Heavy 전체 실행 시간 (분)')
  for (const field of [delegate, light, heavy]) {
    assert.equal(field.props.type, 'number')
    assert.equal(field.props.min, 0)
    assert.equal(field.props.step, 'any')
    assert.equal(field.props.disabled, false)
  }
  assert.deepEqual([delegate.props.value, light.props.value, heavy.props.value], [0, 60, 60])
  const copy = text(h.tree)
  for (const phrase of [
    '전체 실행 시간 제한 (TOTAL)', '분 (minutes)', 'delegation.child_timeout_seconds',
    '협조적 중단을 요청', '실행 프로세스를 정리', '새 작업은 시작할 때 현재 정책을 스냅샷',
    '요청·도구별 제한과 반복 횟수 제한', '모델·라우팅·폴백 적용 대상과는 독립적', 'Light', 'Heavy'
  ]) assert.ok(copy.includes(phrase), `missing UI explanation: ${phrase}`)
})

test('unsupported old-backend timeout DTO stays blank, disabled, and absent from whole-page save', async () => {
  const data = statusFixture()
  delete data.profiles.find(row => row.name === 'claire').timeouts
  const h = harness(data)
  assert.equal(h.byId('delegate-total-minutes').props.value, '')
  assert.equal(h.byId('routed-light-total-minutes').props.value, '')
  assert.equal(h.byId('delegate-total-minutes').props.disabled, true)
  assert.equal(h.byId('routed-light-total-minutes').props.disabled, true)
  assert.match(text(h.tree), /UNSUPPORTED/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.equal('timeout_updates' in body, false)
})

test('whole-page save emits changed minute fields as seconds and sends all three timeout values with loaded revisions', async () => {
  for (const [id, value, expected] of [
    ['delegate-total-minutes', '75.5', { delegate_total_seconds: 4530, routed_light_total_seconds: 3600, routed_heavy_total_seconds: 3600 }],
    ['routed-light-total-minutes', '90', { delegate_total_seconds: 0, routed_light_total_seconds: 5400, routed_heavy_total_seconds: 3600 }]
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

test('unchanged limits are omitted; edits copy selected source values in seconds with target-local revisions', async () => {
  const unchanged = harness()
  unchanged.input('model-main-model', 'model-only-change')
  globalSave(unchanged)
  await unchanged.flush()
  assert.equal('timeout_updates' in unchanged.calls.find(call => call.operation === 'preview').body, false)

  const h = harness()
  h.input('delegate-total-minutes', '99')
  h.selectProfile('other')
  assert.equal(h.byId('delegate-total-minutes').props.value, 12 / 60)
  assert.equal(h.byId('routed-light-total-minutes').props.value, 7200 / 60)
  h.input('delegate-total-minutes', '22')
  globalSave(h)
  await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 1320, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 1320, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 1320, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 }
  ])
})

test('read-only supported DTO displays actual values but cannot edit or add timeout_updates', async () => {
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').timeouts.editable = false
  const h = harness(data)
  assert.equal(h.byId('delegate-total-minutes').props.value, 0)
  assert.equal(h.byId('routed-light-total-minutes').props.value, 60)
  assert.equal(h.byId('routed-heavy-total-minutes').props.value, 60)
  assert.equal(h.byId('delegate-total-minutes').props.disabled, true)
  assert.match(text(h.tree), /시간 제한은 읽기 전용/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  assert.equal('timeout_updates' in h.calls.find(call => call.operation === 'preview').body, false)
})

test('invalid edited values are reported locally and never sent to preview', async () => {
  const h = harness()
  h.input('delegate-total-minutes', '-1')
  assert.match(text(h.tree), /0 이상의 유한한 분 단위 숫자|초 단위로 변환할 수 없는/)
  globalSave(h)
  await h.flush()
  assert.equal(h.calls.length, 0)
})

test('timeout revision replacement blocks overwrite until explicit refresh establishes a new baseline', async () => {
  const h = harness()
  h.input('delegate-total-minutes', '90')
  const next = structuredClone(h.data())
  const row = next.profiles.find(item => item.name === 'claire')
  row.timeouts.revision = 9
  row.timeouts.delegate_total_seconds = 5
  row.timeouts.routed_total_seconds = 7200
  h.setData(next)
  h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.match(text(h.tree), /revision.*바뀌었습니다/)
  assert.equal(h.calls.length, 0)

  h.clickLabel('상태 새로고침')
  await h.flush()
  assert.equal(h.byId('delegate-total-minutes').props.value, 5 / 60)
  assert.equal(h.byId('routed-light-total-minutes').props.value, 120)
  h.input('delegate-total-minutes', '6')
  globalSave(h)
  await h.flush()
  assert.deepEqual(h.calls.find(call => call.operation === 'preview').body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 360, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 },
    { profile: 'claire', expected_revision: 9, delegate_total_seconds: 360, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 360, routed_light_total_seconds: 7200, routed_heavy_total_seconds: 7200 }
  ])
})

test('immutable timeout save snapshot does not drift and incoming revision change cancels before apply', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('routed-light-total-minutes', '9000')
  globalSave(h)
  const captured = structuredClone(h.calls[0].body)
  assert.deepEqual(captured.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 0, routed_light_total_seconds: 540000, routed_heavy_total_seconds: 3600 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, routed_light_total_seconds: 540000, routed_heavy_total_seconds: 3600 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 0, routed_light_total_seconds: 540000, routed_heavy_total_seconds: 3600 }
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
  assert.match(text(h.tree), /revision.*바뀌었습니다/)
})

test('connection change during timeout validation cancels the old scope without carrying its draft forward', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('routed-light-total-minutes', '7654')
  globalSave(h)
  assert.deepEqual(h.calls[0].body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 0, routed_light_total_seconds: 459240, routed_heavy_total_seconds: 3600 },
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, routed_light_total_seconds: 459240, routed_heavy_total_seconds: 3600 },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 0, routed_light_total_seconds: 459240, routed_heavy_total_seconds: 3600 }
  ])
  h.state.connectionId.value = 'different-connection'
  h.render()
  resolvePreview({ plan_id: 'old-connection-plan', changes: [] })
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.equal(h.byId('routed-light-total-minutes').props.value, 60)
})

test('independent fallback save does not copy or save total-runtime limits', async () => {
  const h = harness()
  h.input('routed-light-total-minutes', '9999')
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').timeouts.revision = 9
  h.setData(newer)
  h.render()
  assert.equal(h.byId('routed-light-total-minutes').props.disabled, true)
  h.click('native-fallback-preset-audited-non-openai')
  h.check('native-fallback-enabled', true)
  h.click('native-fallback-save')
  await h.flush()
  const body = h.calls.find(call => call.operation === 'fallback-preview').body
  assert.equal('timeout_updates' in body, false)
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
})

test('actual legacy handler preserves original fractional and large raw seconds while another role is edited', async () => {
  for (const routedSeconds of [1e100, Number.MAX_SAFE_INTEGER]) {
    const data = statusFixture()
    const sourceRow = data.profiles.find(row => row.name === 'claire')
    sourceRow.timeouts.delegate_total_seconds = 123.456
    sourceRow.timeouts.routed_total_seconds = routedSeconds
    const h = harness(data)
    assert.equal(h.byId('delegate-total-minutes').props.value, 123.456 / 60)
    h.input('routed-light-total-minutes', '15')
    globalSave(h)
    await h.flush()
    const update = h.calls.find(call => call.operation === 'preview').body.timeout_updates
      .find(item => item.profile === 'claire')
    assert.equal(update.delegate_total_seconds, 123.456)
    assert.equal(update.routed_light_total_seconds, 900)
    assert.equal(update.routed_heavy_total_seconds, routedSeconds)
  }
})

test('timeout helper builds three-second-field updates and rejects invalid, stale, overflow, or unsupported drafts', () => {
  const dto = timeoutDto()
  const draft = helpers.copyProfileDraft(profile('claire', dto)).timeouts
  const baseline = helpers.copyTimeoutBaseline(dto)
  const changed = { ...draft, delegate_total_minutes: '0.5', routed_light_total_minutes: '1e100' }
  const built = helpers.buildTimeoutUpdate('claire', changed, baseline, dto)
  assert.deepEqual(built, {
    changed: true,
    update: { profile: 'claire', expected_revision: 8, delegate_total_seconds: 30,
      routed_light_total_seconds: 6e101, routed_heavy_total_seconds: 3600 },
    error: ''
  })
  assert.equal(helpers.timeoutDraftChanged(draft, baseline), false)
  assert.equal(helpers.timeoutRevisionMatches(baseline, timeoutDto({ revision: 9 })), false)
  assert.match(helpers.buildTimeoutUpdate('claire', changed, baseline, timeoutDto({ revision: 9 })).error, /revision/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, routed_light_total_minutes: '1e308' }, baseline, dto).error, /초 단위로 변환/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, delegate_total_minutes: true }, baseline, dto).error, /분 단위/)
  const missingCapability = { ...dto }
  delete missingCapability.split_routing_supported
  assert.equal(helpers.splitRoutingSupported(missingCapability), false)
  assert.equal(helpers.buildTimeoutUpdate('claire', { ...draft, delegate_total_minutes: '1' },
    helpers.copyTimeoutBaseline(missingCapability), missingCapability).update, null)
})
