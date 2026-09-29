import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Exercise real RouterPage handlers with in-memory hooks and transport only.
// No DOM/native profile/settings writes are performed by this harness.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const models = {
  main: route('openai-codex', 'gpt-6-astra-900k', 'medium'),
  delegation: route('openai-codex', 'gpt-6-luna-900k', 'max'),
  compression: route('openai-codex', 'gpt-6-luna-900k', 'medium'),
  title: route('openai-codex', 'gpt-6-luna', 'none')
}
const routing = {
  enabled: true,
  heavy: { follow: 'custom', custom: route('operator', 'independent-heavy', 'high') },
  light: { follow: 'delegation', custom: null },
  fallback: { enabled: false, heavy: null, light: null }
}
const fixture = () => ({ revision: 7, current_profile: 'claire', recent_apply: null,
  profiles: ['default', 'claire', 'other'].map(name => ({ name, models: structuredClone(models),
    actual_models: structuredClone(models), routing: { ...structuredClone(routing), enabled: name === 'claire' }, drift: [] })) })
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
function harness() {
  let data = fixture(), cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = []
  const state = Object.fromEntries(Object.entries({ profile: 'claire', connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  let responder = operation => operation === 'preview'
    ? { plan_id: 'test-plan', changes: [{ profile: 'claire', field: 'models.main', before: 'before', after: 'after' }], warnings: [] }
    : { status: 'applied', revision: 8 }
  const host = { state, request: async (method, args) => {
    const index = args.argv.indexOf('model-router'), operation = args.argv[index + 1]
    const body = JSON.parse(args.argv.at(-1))
    calls.push({ method, operation, body, profile: args.profile })
    const result = await responder(operation, body)
    return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(result)}\n` }
  } }
  const useState = initial => {
    const index = cursor++
    if (!(index in hooks)) hooks[index] = typeof initial === 'function' ? initial() : initial
    return [hooks[index], value => {
      const next = typeof value === 'function' ? value(hooks[index]) : value
      if (!Object.is(hooks[index], next)) { hooks[index] = next; dirty = true }
    }]
  }
  const useRef = initial => { const index = cursor++; return hooks[index] ??= { current: initial } }
  const useEffect = (fn, deps) => {
    const index = cursor++, before = hooks[index]
    if (!before || !deps || deps.some((value, at) => !Object.is(value, before[at]))) {
      hooks[index] = deps; effects.push(fn)
    }
  }
  let refetcher = async () => ({ data })
  const query = { get data() { return data }, isPending: false, isError: false, isFetching: false,
    refetch: async () => {
      query.isFetching = true
      try { return await refetcher() } finally { query.isFetching = false }
    } }
  const jsx = (type, props = {}) => typeof type === 'function' ? type(props) : { type, props }
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
    for (const name of match[1].split(',').map(s => s.trim()).filter(Boolean)) imports[name] = name
  }
  Object.assign(imports, { useState, useRef, useEffect, jsx, jsxs: jsx, host,
    useValue: atom => atom.get(), useQuery: () => query })
  const executable = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const RouterPage = new Function(...Object.keys(imports), `${executable}\nreturn RouterPage`)(...Object.values(imports))
  const render = () => {
    for (let attempt = 0; attempt < 20; attempt++) {
      dirty = false; cursor = 0; tree = RouterPage({ ctx: {} })
      for (const effect of effects.splice(0)) effect()
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  const find = predicate => { const node = [...walk(tree)].find(predicate); assert.ok(node, 'Control not found'); return node }
  const byId = id => find(node => node.props?.id === id)
  const flush = async () => { for (let at = 0; at < 8; at++) await Promise.resolve(); render() }
  const click = id => { const node = byId(id); assert.ok(!node.props.disabled); node.props.onClick(); render() }
  const button = label => find(node => node.type === 'Button' && text(node).includes(label))
  const clickLabel = label => { const node = button(label); assert.ok(!node.props.disabled); node.props.onClick(); render() }
  const selected = prefix => [...walk(tree)].filter(node => node.type === 'Checkbox' && node.props.id?.startsWith(prefix) && node.props.checked === true)
    .map(node => node.props.id.slice(prefix.length)).sort()
  const selectProfile = name => {
    find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'profile-select')).props.onValueChange(name); render()
  }
  render()
  return { calls, state, render, byId, button, click, clickLabel, selected, selectProfile, flush,
    setResponder(fn) { responder = fn }, setRefetcher(fn) { refetcher = fn }, setData(next) { data = next }, data: () => data,
    check(id, value) { byId(id).props.onCheckedChange(value); render() },
    input(id, value) { byId(id).props.onChange({ target: { value } }); render() } }
}

test('initial page selects every model target but preserves routing opt-in membership', () => {
  const h = harness()
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  assert.deepEqual(h.selected('routing-profile-'), ['claire'])
  assert.equal(h.calls.length, 0)
})

test('preset click fills exact BAT models in draft only and does not alter custom routes', async () => {
  const h = harness()
  h.click('preset-non-openai')
  assert.equal(h.byId('model-main-model').props.value, 'mimo-v2.6-pro')
  assert.equal(h.byId('model-main-provider').props.value, 'xiaomi')
  assert.equal(h.byId('model-main-reasoning').props.value, 'max')
  assert.equal(h.byId('model-title-model').props.value, 'deepseek-flash')
  assert.equal(h.byId('model-title-reasoning').props.value, 'none')
  assert.equal(h.calls.length, 0)
  h.clickLabel('변경 내용 미리보기'); await h.flush()
  const payload = h.calls.at(-1).body
  assert.deepEqual(payload.routing, routing)
  assert.deepEqual(payload.routing_profiles, ['claire'])
  assert.deepEqual([...payload.model_targets].sort(), ['claire', 'default', 'other'])
  assert.equal(payload.models.delegation.reasoning, 'max')
  assert.equal(payload.models.compression.reasoning, 'medium')
  h.click('preset-openai')
  for (const [role, fields] of Object.entries(models)) for (const [field, value] of Object.entries(fields))
    assert.equal(h.byId(`model-${role}-${field}`).props.value, value)
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 0)
})

test('none and explicit subset survive source changes and refresh; removed profiles are filtered', async () => {
  const h = harness()
  h.click('model-target-none')
  h.selectProfile('other')
  h.clickLabel('상태 새로고침'); await h.flush()
  assert.deepEqual(h.selected('model-target-'), [])
  h.check('model-target-claire', true)
  h.selectProfile('default')
  h.clickLabel('상태 새로고침'); await h.flush()
  assert.deepEqual(h.selected('model-target-'), ['claire'])
  h.setData({ ...h.data(), profiles: h.data().profiles.filter(p => p.name !== 'claire') })
  h.clickLabel('상태 새로고침'); await h.flush()
  assert.deepEqual(h.selected('model-target-'), [])
})

test('bulk target and preset changes discard an already reviewed preview', async () => {
  for (const control of ['model-target-all', 'model-target-none', 'preset-non-openai']) {
    const h = harness()
    h.clickLabel('변경 내용 미리보기'); await h.flush()
    h.check('confirm-preview', true)
    h.click(control)
    assert.throws(() => h.byId('confirm-preview'), /Control not found/)
    assert.equal(h.calls.filter(c => c.operation === 'apply').length, 0)
    assert.deepEqual(h.selected('routing-profile-'), ['claire'])
  }
})

test('an in-flight preview cannot revive after a preset edit', async () => {
  const h = harness(); let resolve
  h.setResponder(() => new Promise(done => { resolve = done }))
  h.clickLabel('변경 내용 미리보기')
  h.click('preset-non-openai')
  resolve({ plan_id: 'stale', changes: [{ profile: 'claire', field: 'models' }], warnings: [] })
  await h.flush()
  assert.throws(() => h.byId('confirm-preview'), /Control not found/)
  assert.equal(h.byId('model-main-model').props.value, 'mimo-v2.6-pro')
})

test('confirmation remains mandatory before any apply request', async () => {
  const h = harness()
  h.click('preset-non-openai')
  h.clickLabel('변경 내용 미리보기'); await h.flush()
  assert.equal(h.button('확인 후 적용').props.disabled, true)
  h.check('confirm-preview', true)
  h.clickLabel('확인 후 적용'); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'apply').map(c => c.body), [{ plan_id: 'test-plan' }])
})

test('refresh invalidates a pending preview immediately and never leaves preview loading stuck', async () => {
  const h = harness(); let finishPreview, finishRefresh
  h.setResponder(() => new Promise(resolve => { finishPreview = resolve }))
  h.setRefetcher(() => new Promise(resolve => { finishRefresh = resolve }))
  h.clickLabel('변경 내용 미리보기')
  h.clickLabel('상태 새로고침')
  finishRefresh({ data: h.data() }); await h.flush()
  finishPreview({ plan_id: 'obsolete', changes: [{ profile: 'claire', field: 'models' }], warnings: [] }); await h.flush()
  assert.throws(() => h.byId('confirm-preview'), /Control not found/)
  assert.equal(h.button('변경 내용 미리보기').props.disabled, false)
})

test('refresh immediately retires a confirmed plan and a stale apply handler cannot send it', async () => {
  const h = harness(); let finishRefresh
  h.clickLabel('변경 내용 미리보기'); await h.flush()
  h.check('confirm-preview', true)
  const staleApply = h.button('확인 후 적용').props.onClick
  h.setRefetcher(() => new Promise(resolve => { finishRefresh = resolve }))
  h.clickLabel('상태 새로고침')
  staleApply(); await h.flush()
  assert.equal(h.calls.filter(call => call.operation === 'apply').length, 0)
  assert.throws(() => h.byId('confirm-preview'), /Control not found/)
  finishRefresh({ data: h.data() }); await h.flush()
})

test('refresh failure with cached data does not unlock an ambiguous apply', async () => {
  const h = harness()
  h.setResponder(operation => {
    if (operation === 'apply') throw new Error('unknown transport outcome')
    return { plan_id: 'test-plan', changes: [{ profile: 'claire', field: 'models' }], warnings: [] }
  })
  h.clickLabel('변경 내용 미리보기'); await h.flush()
  h.check('confirm-preview', true)
  h.clickLabel('확인 후 적용'); await h.flush()
  h.setRefetcher(async () => ({ data: h.data(), error: new Error('refresh failed') }))
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
})

test('fresh connection/profile scope starts all-selected without leaking previous routing choices', () => {
  const h = harness()
  h.click('model-target-none')
  h.state.connectionId.value = 'another-connection'
  h.state.profile.value = 'default'
  h.setData({ ...fixture(), current_profile: 'default' })
  h.render()
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  assert.deepEqual(h.selected('routing-profile-'), ['claire'])
})
