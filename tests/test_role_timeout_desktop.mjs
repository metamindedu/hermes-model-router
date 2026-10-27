import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const route = (provider, model, reasoning = 'high') => ({ provider, model, reasoning })
const legacyTimeouts = (revision, delegate, routed, overrides = {}) => ({
  schema: 1, revision, delegate_total_seconds: delegate, routed_total_seconds: routed,
  editable: true, split_routing_supported: true, warnings: [], ...overrides
})
const splitTimeouts = (revision, delegate, light, heavy, overrides = {}) => ({
  schema: 2, revision, delegate_total_seconds: delegate,
  routed_light_total_seconds: light, routed_heavy_total_seconds: heavy,
  editable: true, split_routing_supported: true, warnings: [], ...overrides
})
const profile = (name, timeouts) => ({
  name,
  models: {
    main: route('fixture', `${name}-main`), delegation: route('fixture', `${name}-delegate`),
    compression: route('fixture', `${name}-compression`), title: route('fixture', `${name}-title`, 'none')
  },
  actual_models: { main: route('fixture', `${name}-main`), delegation: route('fixture', `${name}-delegate`) },
  routing: {
    enabled: name === 'claire', heavy: { follow: 'main', custom: null },
    light: { follow: 'delegation', custom: null }, fallback: { enabled: false, heavy: null, light: null }
  },
  fallbacks: {
    native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null },
    routing: { editable: true, enabled: false, heavy: null, light: null, consent: null },
    delegation: { managed: true, editable: true, mode: 'default', chain: [], actual_mode: 'default', actual_chain: [], drift: false, warnings: [], consent: null }
  },
  drift: [], timeouts
})
const fixture = (overrides = {}) => ({
  revision: 12, current_profile: 'claire',
  fallback_capabilities: {
    native_trigger: 'hermes_runtime', native_execution: 'continue_conversation', native_reasoning: 'profile_overrides',
    routing_trigger: 'subscription_exhaustion_before_tools', routing_execution: 'fresh_task', routing_max_retries: 1
  },
  profiles: [
    profile('default', legacyTimeouts(3, 0, 1800)),
    profile('claire', splitTimeouts(8, 120, 900, 7200)),
    profile('other', legacyTimeouts(11, 12, 7200))
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
function harness(initial = fixture()) {
  let data = initial, cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = []
  const state = Object.fromEntries(Object.entries({ profile: 'claire', connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  const host = { state, request: async (_method, args) => {
    const at = args.argv.indexOf('model-router')
    const operation = args.argv[at + 1]
    const body = JSON.parse(args.argv.at(-1))
    calls.push({ operation, body })
    const result = operation === 'preview'
      ? { plan_id: 'role-timeout-plan', changes: [], warnings: [] }
      : { status: 'applied', revision: 13 }
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
      hooks[index] = deps; effects.push(fn)
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
  const byId = id => {
    const node = [...walk(tree)].find(item => item.props?.id === id)
    assert.ok(node, `Control not found: ${id}`)
    return node
  }
  const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); render() }
  const input = (id, value) => {
    const node = byId(id); assert.equal(node.props.disabled, false, `${id} enabled`)
    node.props.onChange({ target: { value } }); render()
  }
  const click = id => {
    const node = byId(id); assert.equal(node.props.disabled, false, `${id} enabled`)
    const result = node.props.onClick?.(); render(); return result
  }
  const check = (id, checked) => {
    const node = byId(id); assert.equal(node.props.disabled, false, `${id} enabled`)
    node.props.onCheckedChange(checked); render()
  }
  render()
  return { calls, byId, input, click, check, render, flush, tree: () => tree,
    data: () => data, setData(value) { data = value } }
}

function preview(h) { return h.calls.find(call => call.operation === 'preview') }

test('individual timeout section handler sends all three unchanged schema-2 values with the selected target revision', async () => {
  const h = harness()
  assert.deepEqual([
    h.byId('delegate-total-minutes').props.value,
    h.byId('routed-light-total-minutes').props.value,
    h.byId('routed-heavy-total-minutes').props.value
  ], [2, 15, 120])
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  await h.click('timeouts-save')
  await h.flush()
  const body = preview(h).body
  assert.equal(body.save_scope, 'timeouts')
  assert.deepEqual(body.timeout_updates, [{ profile: 'other', expected_revision: 11,
    delegate_total_seconds: 120, routed_light_total_seconds: 900, routed_heavy_total_seconds: 7200 }])
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
})

test('a selected role-timeout target that loses capability remains selected but the actual save handler fails closed', async () => {
  const h = harness()
  h.click('timeout-target-none')
  h.check('timeout-target-other', true)
  const next = structuredClone(h.data())
  next.profiles.find(row => row.name === 'other').timeouts.split_routing_supported = false
  h.setData(next)
  h.render()
  assert.equal(h.byId('timeout-target-other').props.checked, true)
  assert.equal(h.byId('timeouts-save').props.disabled, true)
  assert.match(text(h.tree()), /역할별 시간 제한 지원/)
  h.byId('timeouts-save').props.onClick()
  await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'preview'), false)
})

test('schema-1 legacy capability omission does not enable editing or bulk selection from numeric defaults', () => {
  const data = fixture()
  const sourceRow = data.profiles.find(row => row.name === 'claire')
  sourceRow.timeouts = legacyTimeouts(8, 0, 3600)
  delete sourceRow.timeouts.split_routing_supported
  const h = harness(data)
  assert.deepEqual([
    h.byId('delegate-total-minutes').props.value,
    h.byId('routed-light-total-minutes').props.value,
    h.byId('routed-heavy-total-minutes').props.value
  ], [0, 60, 60])
  for (const id of ['delegate-total-minutes', 'routed-light-total-minutes', 'routed-heavy-total-minutes']) {
    assert.equal(h.byId(id).props.disabled, true)
  }
  assert.equal(h.byId('timeout-target-claire').props.checked, false)
  assert.equal(h.byId('timeout-target-claire').props.disabled, true)
  assert.match(text(h.tree()), /Light와 Heavy의 시간 제한을 따로 변경할 수 없습니다/)
})

test('routing defaults are explained while explicit opt-out controls stay inside closed advanced settings', () => {
  const h = harness()
  const advanced = h.byId('routing-activation-advanced')
  assert.equal(advanced.type, 'details')
  assert.notEqual(advanced.props.open, true)
  const ids = [...walk(advanced)].map(node => node.props?.id)
  assert.ok(ids.includes('routing-enabled'))
  assert.ok(ids.includes('routing-profile-default'))
  assert.match(text(h.tree()), /작업 분담이 기본으로 켜집니다/)
  assert.match(text(h.tree()), /같은 모델/)
  assert.equal(h.byId('routing-enabled').props.checked, true)
  assert.equal(h.byId('routing-profile-default').props.checked, false)
  assert.equal(h.calls.length, 0)
})
