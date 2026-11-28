import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Per-slot runtime limits (v0.18.0, timeouts schema 3): the ordinary delegation limit plus one limit
// per task slot. A slot without its own limit runs with `default_slot_seconds` (2 hours); a blank
// slot field on the page means exactly that, and a partial save clears it with `null`.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helpers = new Function(`${source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')}\nreturn {
  copyProfileDraft, copyTimeoutBaseline, validTimeoutsDto, parseTimeoutMinutes, changedTimeoutFields,
  timeoutDraftChanged, timeoutRevisionMatches, buildTimeoutUpdate, buildTimeoutUpdates, timeoutDurationText,
  eligibleTimeoutTargets, timeoutUpdateFields, timeoutFieldLabels, TASK_SLOTS
}`)()

const SLOT_IDS = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use', 'advise']
const route = (provider, model, reasoning = 'high') => ({ provider, model, reasoning })
const timeoutDto = (overrides = {}) => ({
  schema: 3,
  revision: 8,
  delegate_total_seconds: 0,
  slot_seconds: { design: 5400 },
  default_slot_seconds: 7200,
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
  routing: { enabled: name === 'claire', slots: {} },
  fallbacks: {
    native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null },
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
    native_reasoning: 'profile_overrides'
  },
  profiles: [
    profile('default', timeoutDto({ revision: 3, slot_seconds: {} })),
    profile('claire', timeoutDto({ revision: 8 })),
    profile('other', timeoutDto({ revision: 11, delegate_total_seconds: 12, slot_seconds: { 'code-simple': 600 } }))
  ],
  ...overrides
})
const partialFixture = () => statusFixture({ partial_save_schema: 1 })

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
    calls, state, render, byId, find, click, clickLabel, input, check, selectProfile, flush,
    get tree() { return tree },
    data: () => data,
    setData(value) { data = value },
    setResponder(fn) { responder = fn }
  }
}

const globalSave = h => h.click('global-save')
const preview = h => h.calls.find(call => call.operation === 'preview')
const everyTarget = values => [
  { profile: 'default', expected_revision: 3, ...values },
  { profile: 'claire', expected_revision: 8, ...values },
  { profile: 'other', expected_revision: 11, ...values }
]

test('timeout DTOs are schema 3 only and fail closed on anything else', () => {
  const supported = profile('claire')
  assert.equal(helpers.validTimeoutsDto(supported.timeouts), true)
  assert.deepEqual(helpers.copyProfileDraft(supported).timeouts, {
    schema: 3, revision: 8, editable: true, default_slot_seconds: 7200,
    delegate_total_minutes: 0, slot_minutes: { design: 90 }
  })
  assert.deepEqual(helpers.copyTimeoutBaseline(supported.timeouts), {
    schema: 3, revision: 8, editable: true, delegate_total_seconds: 0, slot_seconds: { design: 5400 }, default_slot_seconds: 7200
  })
  assert.equal('timeouts' in helpers.copyProfileDraft(profile('old', null)), false)
  // A custom slot's limit is a valid stored value, defined here or not.
  assert.equal(helpers.validTimeoutsDto(timeoutDto({ slot_seconds: { 'custom:3d': 60, advise: 0 } })), true)
  const invalid = [
    // what the service reports for an unreadable file, and the earlier schemas
    timeoutDto({ schema: null, revision: null, delegate_total_seconds: null, slot_seconds: null, editable: false, warnings: ['timeouts_invalid'] }),
    timeoutDto({ schema: 2 }), timeoutDto({ revision: 1.5 }), timeoutDto({ delegate_total_seconds: -1 }),
    timeoutDto({ delegate_total_seconds: Infinity }), timeoutDto({ slot_seconds: null }), timeoutDto({ slot_seconds: [] }),
    timeoutDto({ slot_seconds: { design: -1 } }), timeoutDto({ slot_seconds: { design: true } }), timeoutDto({ slot_seconds: { design: NaN } }),
    timeoutDto({ slot_seconds: { 'not-a-slot': 60 } }), timeoutDto({ slot_seconds: { 'custom:X': 60 } }), timeoutDto({ default_slot_seconds: undefined }),
    timeoutDto({ editable: 'true' }), timeoutDto({ warnings: 'not-an-array' }), timeoutDto({ warnings: [7] })
  ]
  for (const dto of invalid) {
    assert.equal(helpers.validTimeoutsDto(dto), false, JSON.stringify(dto))
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
  assert.deepEqual([7200, 5400, 1800, 90, 0].map(helpers.timeoutDurationText), ['2시간', '1시간 30분', '30분', '1.5분', '제한 없음'])
})

test('the page shows one minute field per task slot; a slot without its own limit is blank with the 2-hour default as its hint', () => {
  const h = harness()
  const delegate = h.byId('delegate-total-minutes')
  assert.equal(delegate.props['aria-label'], '일반 위임 작업 제한 (분)')
  assert.equal(delegate.props.value, 0)
  const labels = { design: '설계', 'code-complex': '코드 · 복잡', 'code-simple': '코드 · 간단', 'verify-simple': '검증 · 간단', 'verify-complex': '검증 · 복잡', 'computer-use': '컴퓨터 유즈' }
  for (const [id, label] of Object.entries(labels)) {
    const field = h.byId(`slot-timeout-${id}`)
    assert.equal(field.props['aria-label'], `${label} (분)`)
    assert.equal(field.props.type, 'number')
    assert.equal(field.props.min, 0)
    assert.equal(field.props.step, 'any')
    assert.equal(field.props.disabled, false)
    assert.equal(field.props.placeholder, '2시간 (기본값)')
    assert.equal(field.props.value, id === 'design' ? 90 : '', id)
  }
  // The advisor's limit is fixed by its tool: shown, never an input.
  const advise = h.byId('slot-timeout-advise')
  assert.equal(advise.type, 'div')
  assert.equal(advise.props.onChange, undefined)
  assert.match(text(advise), /5분 고정/)
  const copy = text(h.tree)
  for (const phrase of [
    '작업별 실행 시간 제한', '작업 슬롯별 제한', '비우면 2시간 (기본값) · 0은 제한 없음', '기본값(2시간)이 적용되고',
    '다른 제한은 그대로 유지', '중단을 요청하지만', '실제로 멈추기까지 시간이 걸릴', '작업을 시작할 때의 설정',
    '응답 대기나 반복 횟수', '모델·라우팅·폴백 적용 대상과는 독립적', '조언 슬롯은 호출마다 5분으로 고정'
  ]) assert.ok(copy.includes(phrase), `missing UI explanation: ${phrase}`)
  assert.doesNotMatch(copy, /Heavy|Light|짧은 작업 제한|긴 작업 제한|짧은 작업 슬롯|긴 작업 슬롯/)
  // The minute fields are the ordinary limit and one per editable slot, nothing else.
  assert.deepEqual([...walk(h.tree)].filter(node => node.type === 'Input').map(node => node.props.id).filter(id => /minutes$|^slot-timeout-/.test(id || '')),
    ['delegate-total-minutes', ...SLOT_IDS.filter(id => id !== 'advise').map(id => `slot-timeout-${id}`)])
})

test('the default shown follows default_slot_seconds from the status', () => {
  const data = statusFixture()
  for (const row of data.profiles) row.timeouts.default_slot_seconds = 5400
  const h = harness(data)
  assert.equal(h.byId('slot-timeout-code-complex').props.placeholder, '1시간 30분 (기본값)')
})

test('an unsupported timeout DTO stays blank, disabled, and absent from the whole-page save', async () => {
  const data = statusFixture()
  delete data.profiles.find(row => row.name === 'claire').timeouts
  const h = harness(data)
  assert.equal(h.byId('delegate-total-minutes').props.value, '')
  assert.equal(h.byId('slot-timeout-design').props.value, '')
  assert.equal(h.byId('delegate-total-minutes').props.disabled, true)
  assert.equal(h.byId('slot-timeout-design').props.disabled, true)
  assert.match(text(h.tree), /시간 제한을 확인할 수 없어 변경하지 않습니다/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  assert.equal('timeout_updates' in preview(h).body, false)
})

test('full form: the whole-page save sends the ordinary limit and every slot that has its own limit', async () => {
  for (const [id, value, expected] of [
    ['delegate-total-minutes', '75.5', { delegate_total_seconds: 4530, slot_seconds: { design: 5400 } }],
    ['slot-timeout-code-complex', '30', { delegate_total_seconds: 0, slot_seconds: { design: 5400, 'code-complex': 1800 } }],
    ['slot-timeout-verify-complex', '0', { delegate_total_seconds: 0, slot_seconds: { design: 5400, 'verify-complex': 0 } }],
    // a cleared field: the slot has no own limit any more, so it is left out (it runs with 2 hours)
    ['slot-timeout-design', '', { delegate_total_seconds: 0, slot_seconds: {} }],
    ['slot-timeout-design', '  ', { delegate_total_seconds: 0, slot_seconds: {} }]
  ]) {
    const h = harness()
    h.input(id, value)
    globalSave(h)
    await h.flush()
    const body = preview(h).body
    assert.equal('partial_save_schema' in body, false)
    assert.deepEqual(body.timeout_updates, everyTarget(expected), `${id}=${JSON.stringify(value)}`)
    assert.deepEqual(body.model_targets, [], 'an unchanged model draft copies nothing; timeout targets are their own list')
    assert.equal('fallback_updates' in body, false)
  }
})

test('partial form: only the changed field goes to each target, and a cleared slot is null (back to the default)', async () => {
  for (const [id, value, expected] of [
    ['slot-timeout-design', '', { slot_seconds: { design: null } }],
    ['slot-timeout-code-simple', '45', { slot_seconds: { 'code-simple': 2700 } }],
    ['slot-timeout-design', '0', { slot_seconds: { design: 0 } }],
    ['delegate-total-minutes', '5', { delegate_total_seconds: 300 }]
  ]) {
    const h = harness(partialFixture())
    h.input(id, value)
    globalSave(h)
    await h.flush()
    const body = preview(h).body
    assert.equal(body.partial_save_schema, 1)
    assert.deepEqual(body.timeout_updates, everyTarget(expected), `${id}=${JSON.stringify(value)}`)
  }
  // Two edits in one save: both fields, still nothing else.
  const h = harness(partialFixture())
  h.input('slot-timeout-design', '')
  h.input('slot-timeout-computer-use', '15')
  assert.match(text(h.byId('timeout-section-summary')), /바뀐 값만\(설계·컴퓨터 유즈\)/)
  globalSave(h)
  await h.flush()
  assert.deepEqual(preview(h).body.timeout_updates, everyTarget({ slot_seconds: { design: null, 'computer-use': 900 } }))
})

test('partial form: the time-limit section save uses the same patch, and copy-all names every slot', async () => {
  const h = harness(partialFixture())
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  assert.equal(h.byId('timeouts-save').props.disabled, true, 'nothing changed and no copy-all')
  h.input('slot-timeout-design', '')
  await h.click('timeouts-save')
  await h.flush()
  const body = preview(h).body
  assert.equal(body.save_scope, 'timeouts')
  assert.deepEqual(body.timeout_updates, [{ profile: 'other', expected_revision: 11, slot_seconds: { design: null } }])
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])

  // Copy-all: the loaded profile's whole time limits replace the target's, also its own slot limits.
  const copy = harness(partialFixture())
  copy.click('timeout-target-none')
  copy.check('timeout-target-other', true)
  copy.check('timeout-copy-all', true)
  assert.match(text(copy.byId('timeout-section-summary')), /일반 위임과 모든 작업 슬롯의 제한 전체/)
  await copy.click('timeouts-save')
  await copy.flush()
  assert.deepEqual(preview(copy).body.timeout_updates, [{ profile: 'other', expected_revision: 11, delegate_total_seconds: 0,
    slot_seconds: Object.fromEntries(SLOT_IDS.map(id => [id, id === 'design' ? 5400 : null])) }])
})

test('full form: the section save copies the whole time limits to the chosen target', async () => {
  const h = harness()
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  h.check('timeout-copy-all', true)
  await h.click('timeouts-save')
  await h.flush()
  assert.deepEqual(preview(h).body.timeout_updates, [{ profile: 'other', expected_revision: 11, delegate_total_seconds: 0, slot_seconds: { design: 5400 } }])
})

test('unchanged limits are omitted; edits copy the loaded source values with target-local revisions', async () => {
  const unchanged = harness()
  unchanged.input('model-main-model', 'model-only-change')
  globalSave(unchanged)
  await unchanged.flush()
  assert.equal('timeout_updates' in preview(unchanged).body, false)

  const h = harness()
  h.input('delegate-total-minutes', '99')
  h.selectProfile('other')
  assert.equal(h.byId('delegate-total-minutes').props.value, 12 / 60)
  assert.equal(h.byId('slot-timeout-code-simple').props.value, 10)
  assert.equal(h.byId('slot-timeout-design').props.value, '')
  h.input('delegate-total-minutes', '22')
  globalSave(h)
  await h.flush()
  assert.deepEqual(preview(h).body.timeout_updates, everyTarget({ delegate_total_seconds: 1320, slot_seconds: { 'code-simple': 600 } }))
})

test('read-only supported DTO displays actual values but cannot edit or add timeout_updates', async () => {
  const data = statusFixture()
  data.profiles.find(row => row.name === 'claire').timeouts.editable = false
  const h = harness(data)
  assert.equal(h.byId('delegate-total-minutes').props.value, 0)
  assert.equal(h.byId('slot-timeout-design').props.value, 90)
  assert.equal(h.byId('delegate-total-minutes').props.disabled, true)
  assert.equal(h.byId('slot-timeout-design').props.disabled, true)
  assert.match(text(h.tree), /시간 제한은 읽기 전용/)
  h.input('model-main-model', 'model-only-change')
  globalSave(h)
  await h.flush()
  assert.equal('timeout_updates' in preview(h).body, false)
})

test('invalid edited values are reported locally and never sent to preview', async () => {
  for (const [id, value] of [['delegate-total-minutes', '-1'], ['delegate-total-minutes', ''], ['slot-timeout-design', '-5'], ['slot-timeout-code-simple', 'abc']]) {
    const h = harness()
    h.input(id, value)
    assert.match(text(h.tree), /0 이상의 분 단위 숫자/, id)
    assert.equal(h.byId('global-save').props.disabled, false, 'the save reports why it cannot be written')
    globalSave(h)
    await h.flush()
    assert.equal(h.calls.length, 0, `${id}=${value}`)
  }
})

test('timeout revision replacement blocks overwrite until explicit refresh establishes a new baseline', async () => {
  const h = harness()
  h.input('slot-timeout-design', '100')
  const next = structuredClone(h.data())
  const row = next.profiles.find(item => item.name === 'claire')
  row.timeouts.revision = 9
  row.timeouts.delegate_total_seconds = 5
  row.timeouts.slot_seconds = { 'code-complex': 1200 }
  h.setData(next)
  h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.match(text(h.tree), /시간 제한 설정이 다른 곳에서 바뀌었습니다/)
  assert.equal(h.calls.length, 0)

  h.clickLabel('상태 새로고침')
  await h.flush()
  assert.equal(h.byId('delegate-total-minutes').props.value, 5 / 60)
  assert.equal(h.byId('slot-timeout-design').props.value, '')
  assert.equal(h.byId('slot-timeout-code-complex').props.value, 20)
  h.input('delegate-total-minutes', '6')
  globalSave(h)
  await h.flush()
  assert.deepEqual(preview(h).body.timeout_updates, [
    { profile: 'default', expected_revision: 3, delegate_total_seconds: 360, slot_seconds: { 'code-complex': 1200 } },
    { profile: 'claire', expected_revision: 9, delegate_total_seconds: 360, slot_seconds: { 'code-complex': 1200 } },
    { profile: 'other', expected_revision: 11, delegate_total_seconds: 360, slot_seconds: { 'code-complex': 1200 } }
  ])
})

test('immutable timeout save snapshot does not drift and incoming revision change cancels before apply', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('slot-timeout-code-simple', '9000')
  globalSave(h)
  const captured = structuredClone(h.calls[0].body)
  assert.deepEqual(captured.timeout_updates, everyTarget({ delegate_total_seconds: 0, slot_seconds: { design: 5400, 'code-simple': 540000 } }))
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').timeouts.revision = 9
  h.setData(newer)
  h.render()
  assert.deepEqual(h.calls[0].body, captured)
  resolvePreview({ plan_id: 'stale-timeout-plan', changes: [] })
  await h.flush()
  assert.deepEqual(h.calls[0].body, captured)
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.match(text(h.tree), /시간 제한 설정이 다른 곳에서 바뀌었습니다/)
})

test('connection change during timeout validation cancels the old scope without carrying its draft forward', async () => {
  const h = harness()
  let resolvePreview
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { resolvePreview = resolve })
    : { status: 'applied', revision: 13 })
  h.input('slot-timeout-verify-simple', '7654')
  globalSave(h)
  assert.deepEqual(h.calls[0].body.timeout_updates, everyTarget({ delegate_total_seconds: 0, slot_seconds: { design: 5400, 'verify-simple': 459240 } }))
  h.state.connectionId.value = 'different-connection'
  h.render()
  resolvePreview({ plan_id: 'old-connection-plan', changes: [] })
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.equal(h.byId('slot-timeout-verify-simple').props.value, '')
})

test('the model section save of conversation spare models does not copy or save runtime limits', async () => {
  const h = harness()
  h.input('slot-timeout-design', '9999')
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').timeouts.revision = 9
  h.setData(newer)
  h.render()
  assert.equal(h.byId('slot-timeout-design').props.disabled, true)
  h.find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'native-fallback-mode')).props.onValueChange('custom'); h.render()
  h.input('native-chain-0-provider', 'xiaomi')
  h.input('native-chain-0-model', 'mimo-v2.6-pro')
  h.click('model-section-save')
  await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['fallback-preview', 'apply'])
  const body = h.calls[0].body
  assert.equal('timeout_updates' in body, false)
  assert.deepEqual(body.updates.map(update => update.profile), ['claire'])
})

test('fractional and large stored seconds are sent back exactly while another field is edited', async () => {
  for (const stored of [1e100, Number.MAX_SAFE_INTEGER, 123.456]) {
    const data = statusFixture()
    const sourceRow = data.profiles.find(row => row.name === 'claire')
    sourceRow.timeouts.delegate_total_seconds = 123.456
    sourceRow.timeouts.slot_seconds = { design: stored }
    const h = harness(data)
    assert.equal(h.byId('delegate-total-minutes').props.value, 123.456 / 60)
    h.input('slot-timeout-code-complex', '15')
    globalSave(h)
    await h.flush()
    const update = preview(h).body.timeout_updates.find(item => item.profile === 'claire')
    assert.equal(update.delegate_total_seconds, 123.456)
    assert.deepEqual(update.slot_seconds, { design: stored, 'code-complex': 900 })
  }
})

test('custom slots get their own field; a stored limit of a slot that is no longer defined is not copied', async () => {
  const data = statusFixture()
  data.slot_capabilities = { schema: 1, slots: SLOT_IDS, purposes: {}, follows: ['main', 'custom'], blocking_profiles: [], custom_slots_supported: true,
    custom_slot_limit: 4, custom_slots: [{ id: 'custom:3d', label: '3D 작업', description: 'Blender Python 코드와 렌더 결과 검수' }] }
  data.profiles.find(row => row.name === 'claire').timeouts.slot_seconds = { design: 5400, 'custom:gone': 60 }
  const h = harness(data)
  const field = h.byId('slot-timeout-custom:3d')
  assert.equal(field.props['aria-label'], '3D 작업 · 사용자지정 (분)')
  assert.equal(field.props.value, '')
  assert.equal(field.props.placeholder, '2시간 (기본값)')
  assert.throws(() => h.byId('slot-timeout-custom:gone'))
  h.input('slot-timeout-custom:3d', '30')
  globalSave(h)
  await h.flush()
  assert.deepEqual(preview(h).body.timeout_updates, everyTarget({ delegate_total_seconds: 0, slot_seconds: { design: 5400, 'custom:3d': 1800 } }))
})

test('helpers: full and partial updates, a cleared slot as null, and every refusal', () => {
  const dto = timeoutDto()
  const draft = helpers.copyProfileDraft(profile('claire', dto)).timeouts
  const baseline = helpers.copyTimeoutBaseline(dto)
  assert.equal(helpers.timeoutDraftChanged(draft, baseline), false)
  assert.deepEqual(helpers.changedTimeoutFields(draft, baseline), [])
  // A blank field for a slot that has no own limit is not a change.
  assert.equal(helpers.timeoutDraftChanged({ ...draft, slot_minutes: { ...draft.slot_minutes, 'code-simple': '' } }, baseline), false)
  const changed = { ...draft, delegate_total_minutes: '0.5', slot_minutes: { design: '1e100', 'code-simple': '' } }
  assert.deepEqual(helpers.changedTimeoutFields(changed, baseline), ['delegate_total_seconds', 'slot:design'])
  assert.equal(helpers.timeoutFieldLabels(helpers.changedTimeoutFields(changed, baseline)), '일반 위임·설계')
  assert.deepEqual(helpers.buildTimeoutUpdate('claire', changed, baseline, dto), {
    changed: true,
    update: { profile: 'claire', expected_revision: 8, delegate_total_seconds: 30, slot_seconds: { design: 6e101 } },
    error: ''
  })
  const cleared = { ...draft, slot_minutes: { design: '' } }
  const fields = helpers.changedTimeoutFields(cleared, baseline)
  assert.deepEqual(fields, ['slot:design'])
  assert.deepEqual(helpers.buildTimeoutUpdate('claire', cleared, baseline, dto, fields, true).update,
    { profile: 'claire', expected_revision: 8, slot_seconds: { design: null } })
  assert.deepEqual(helpers.buildTimeoutUpdate('claire', cleared, baseline, dto).update,
    { profile: 'claire', expected_revision: 8, delegate_total_seconds: 0, slot_seconds: {} }, 'full form: the slot is left out')
  assert.deepEqual(helpers.timeoutUpdateFields({ profile: 'claire', expected_revision: 8, slot_seconds: { design: null } }), ['slot:design'])
  assert.equal(helpers.timeoutRevisionMatches(baseline, timeoutDto({ revision: 9 })), false)
  assert.match(helpers.buildTimeoutUpdate('claire', changed, baseline, timeoutDto({ revision: 9 })).error, /revision/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, slot_minutes: { design: '1e308' } }, baseline, dto).error, /초 단위로 변환/)
  assert.match(helpers.buildTimeoutUpdate('claire', { ...changed, delegate_total_minutes: true }, baseline, dto).error, /분 단위/)
  const readOnly = timeoutDto({ editable: false })
  const locked = helpers.buildTimeoutUpdate('claire', { ...helpers.copyProfileDraft(profile('claire', readOnly)).timeouts, delegate_total_minutes: '1' }, helpers.copyTimeoutBaseline(readOnly), readOnly)
  assert.equal(locked.update, null)
  assert.match(locked.error, /읽기 전용/)
  const rows = statusFixture().profiles
  rows[2].timeouts.editable = false
  rows[0].timeouts = timeoutDto({ schema: 2 })
  assert.deepEqual(helpers.eligibleTimeoutTargets(rows), ['claire'])
  const many = helpers.buildTimeoutUpdates('claire', cleared, ['claire', 'other'],
    { claire: baseline, other: helpers.copyTimeoutBaseline(timeoutDto({ revision: 11 })) }, { claire: dto, other: timeoutDto({ revision: 11 }) }, fields, true)
  assert.deepEqual(many, { updates: [{ profile: 'claire', expected_revision: 8, slot_seconds: { design: null } }, { profile: 'other', expected_revision: 11, slot_seconds: { design: null } }], errors: [] })
  const stale = helpers.buildTimeoutUpdates('claire', cleared, ['claire', 'other'],
    { claire: baseline, other: helpers.copyTimeoutBaseline(timeoutDto({ revision: 11 })) }, { claire: dto, other: timeoutDto({ revision: 12 }) }, fields, true)
  assert.deepEqual(stale.updates, [])
  assert.match(stale.errors.join(' '), /other 프로필의 시간 제한 revision/)
})

test('task routing can no longer be turned off here; profiles saved with it off are only offered a way back on', () => {
  const h = harness()
  for (const gone of ['routing-activation-advanced', 'routing-enabled', 'routing-profile-default']) assert.throws(() => h.byId(gone))
  const notice = h.byId('routing-reenable')
  assert.deepEqual([...walk(notice)].map(node => node.props?.id).filter(id => /^routing-reenable-(?!save)/.test(id || '')), ['routing-reenable-default', 'routing-reenable-other'])
  assert.equal(h.byId('routing-reenable-default').props.checked, false)
  assert.equal(h.byId('routing-reenable-save').props.disabled, true)
  assert.match(text(notice), /이전에 꺼 두었거나 플러그인이 아직 준비되지 않은 프로필/)
  assert.match(text(notice), /저장하지 않은 다른 편집이 있으면 그것부터 저장/)
  assert.match(text(h.tree), /작업 분담이 기본으로 켜지며/)
  assert.equal(h.calls.length, 0)
})
