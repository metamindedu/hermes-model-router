import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function load(overrides = {}) {
  const params = {}
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(x => x.trim()).filter(Boolean)) params[name] = name
  const state = Object.fromEntries(Object.entries({ connectionId: 'owner', profile: 'claire', activeSessionId: 'parent', gateway: 'open' }).map(([key, value]) => [key, { get: () => value }]))
  const subscriptions = [], effects = [], reads = [], rows = []
  let queryOptions
  const host = { state, profileRoutes: async () => [route()], requestProfile: async () => { throw Error('unexpected request') }, onEvent(type, callback) { const item = { type, callback, disposed: false }; subscriptions.push(item); return () => { item.disposed = true } } }
  const jsx = (type, props = {}, key) => ({ type, props, key })
  const query = { isPending: false, isError: false, isFetching: false, data: { scope_key: '["owner","claire","parent"]', available: true, rows }, refetch: async () => { reads.push('refresh') } }
  Object.assign(params, { DesktopSDK: { COMPOSER_AREAS: { top: 'composer.top' } }, host, jsx, jsxs: jsx,
    useState: value => [value, () => {}], useRef: value => ({ current: value }), useEffect: effect => effects.push(effect),
    useQuery: options => { queryOptions = options; return query }, useValue: atom => atom.get(), ...overrides })
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const api = new Function(...Object.keys(params), code + '\nreturn {executionId,executionScopeKey,executionScopeFromState,selectExecutionRoute,executionIdentity,executionLabel,mergeExecutionRows,readExecutionSnapshot,ExecutionRow,ExecutionPanel,pluginDefinition}')( ...Object.values(params))
  return { ...api, host, query, rows, subscriptions, effects, reads, options: () => queryOptions }
}
const scope = () => ({ connectionId: 'owner', profile: 'claire', sessionId: 'parent' })
const route = () => ({ mode: 'local', connectionId: 'owner', profile: 'claire', targetProfile: 'claire' })
const unknown = () => ({ kind: 'unknown', role: null, profile: null, evidence: 'unknown' })
const row = (id = 'call:0') => ({ id, execution_mode: 'native', conversation_id: 'parent', parent_session_id: 'segment', task_index: 0, subagent_id: 'sa-0-native', delegation_id: 'deleg-native',
  requested: { kind: 'profile', profile: 'wallace', role: null }, observed: unknown(), status: 'dispatched', updated_at: 1 })
const snapshot = () => ({ schema: 1, supported: true, origin_profile: 'claire', conversation_id: 'parent', rows: [row()] })
const text = node => typeof node === 'string' ? node : Array.isArray(node) ? node.map(text).join(' ') : node?.props ? text(node.props.children) : ''
function* walk(node) { if (Array.isArray(node)) { for (const child of node) yield* walk(child) } else if (node && typeof node === 'object') { yield node; yield* walk(node.props?.children) } }

test('execution scope is the literal connection/profile/session tuple, never a bare id', () => {
  const api = load()
  assert.equal(api.executionScopeKey(scope()), '["owner","claire","parent"]')
  for (const bad of [null, {}, { ...scope(), connectionId: '' }, { ...scope(), sessionId: ' parent' }, { ...scope(), profile: 'claire\n' }]) assert.equal(api.executionScopeKey(bad), null)
  assert.notEqual(api.executionScopeKey(scope()), api.executionScopeKey({ ...scope(), connectionId: 'other' }))
})
test('focused owner beats the ambient gateway and unresolved focus never falls back', () => {
  const api = load()
  api.host.state.focusedSessionOwner = { get: () => ({ connectionId: 'remote-other', profile: 'wallace' }) }
  api.host.state.focusedSessionId = { get: () => 'focused-parent' }
  assert.deepEqual(api.executionScopeFromState(api.host.state), { connectionId: 'remote-other', profile: 'wallace', sessionId: 'focused-parent' })
  api.host.state.focusedSessionOwner = { get: () => null }
  assert.equal(api.executionScopeKey(api.executionScopeFromState(api.host.state)), null)
})
test('route selection retains exact SDK descriptor and refuses absent/ambiguous routes', () => {
  const api = load(), exact = route()
  assert.deepEqual(api.selectExecutionRoute([exact], scope()), exact)
  assert.deepEqual(api.selectExecutionRoute([{ ...exact, mode: 'remote' }], scope()), { ...exact, mode: 'remote' })
  assert.equal(api.selectExecutionRoute([exact, exact], scope()), null)
  assert.equal(api.selectExecutionRoute([{ ...exact, connectionId: 'other' }], scope()), null)
  assert.equal(api.selectExecutionRoute([{ ...exact, targetProfile: '../wallace' }], scope()), null)
})
test('model and profile badges do not promote requests into verified runtime identity', () => {
  const api = load()
  assert.equal(api.executionLabel({ kind: 'model', role: 'heavy' }), '모델 · Heavy')
  assert.equal(api.executionLabel({ kind: 'model', role: 'light' }), '모델 · Light')
  assert.equal(api.executionLabel({ kind: 'profile', profile: 'wallace' }), '프로필 · wallace')
  assert.equal(api.executionIdentity({ kind: 'model', role: 'heavy' }).evidence, 'unknown')
  assert.deepEqual(api.executionIdentity({ kind: 'profile', profile: 'wallace', role: 'heavy' }), unknown())
  assert.deepEqual(api.executionIdentity({ kind: 'model', role: 'heavy', evidence: 'response_verified' }), { kind: 'model', role: 'heavy', profile: null, evidence: 'unknown' })
})
test('live native metadata is correlated by BOTH exact subagent and delegation id', () => {
  const api = load(), data = snapshot()
  const rows = api.mergeExecutionRows(data, { subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'deleg-native', status: 'running', model: 'native-model' }] }, 'claire')
  assert.equal(rows.length, 1); assert.equal(rows[0].status, 'running'); assert.equal(rows[0].model, 'native-model')
  assert.equal(rows[0].observed.kind, 'unknown'); assert.equal(rows[0].requested.profile, 'wallace')
  const foreign = api.mergeExecutionRows(data, { subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'other-generation', status: 'running', model: 'other-model' }] }, 'claire')
  assert.equal(foreign.length, 2); assert.equal(foreign[0].model, null); assert.equal(foreign[1].observed.kind, 'unknown')
})
test('missing live record never implies success and unrelated goals/models do not supply identity', () => {
  const api = load()
  const rows = api.mergeExecutionRows(snapshot(), { subagents: [{ subagent_id: 'another', goal: 'same goal', model: 'identical-model', status: 'running' }] }, 'claire')
  assert.equal(rows[0].status, 'dispatched'); assert.equal(rows[1].requested.kind, 'unknown')
})
test('foreign-profile metadata and malformed identifiers are not projected', () => {
  const api = load(), data = snapshot()
  assert.deepEqual(api.mergeExecutionRows(data, null, 'wallace'), [])
  data.rows.push({ ...row('bad'), parent_session_id: '../\nsecret' }, { ...row('bad2'), task_index: -1 }, { ...row('bad3'), execution_mode: 'full' })
  assert.equal(api.mergeExecutionRows(data, null, 'claire').length, 1)
})
test('runtime identity and response verification remain distinct in actual row output', () => {
  const api = load(), requested = row()
  const pending = text(api.ExecutionRow({ row: { ...requested, model: 'reported-model' } }))
  assert.match(pending, /프로필 · wallace/); assert.match(pending, /아직 확인되지/)
  const actual = { ...requested, observed: { kind: 'profile', role: null, profile: 'wallace', evidence: 'runtime_reported' } }
  const output = text(api.ExecutionRow({ row: actual }))
  assert.match(output, /런타임 보고/); assert.match(output, /개별 API 응답/); assert.match(output, /네이티브/)
  assert.doesNotMatch(output, /검증 완료|전체 프로필/)
})
test('read-only roster uses public scoped RPCs and never create/activate/resume/cli/private data', async () => {
  const api = load(), calls = []
  const transport = { profileRoutes: async () => [route()], requestProfile: async (descriptor, method, params) => {
    calls.push({ descriptor, method, params }); return method.includes('execution.list') ? snapshot() : { subagents: [] }
  } }
  const reply = await api.readExecutionSnapshot(transport, scope())
  assert.equal(reply.available, true); assert.equal(reply.rows.length, 1)
  assert.deepEqual(calls.map(item => item.method), ['plugin.model-router.execution.list', 'subagent.list', 'plugin.model-router.profile_jobs.list'])
  for (const item of calls) { assert.deepEqual(item.descriptor, route()); assert.deepEqual(item.params, { session_id: 'parent' }) }
})
test('owner changed during descriptor read prevents all RPC dispatch', async () => {
  const api = load(); let current = true, count = 0
  await assert.rejects(api.readExecutionSnapshot({ profileRoutes: async () => { current = false; return [route()] }, requestProfile: async () => { count++ } }, scope(), () => current), /scope_changed/)
  assert.equal(count, 0)
})
test('owner changed after RPC or snapshot error never supplies another conversation data', async () => {
  const api = load(); let current = true
  const transport = { profileRoutes: async () => [route()], requestProfile: async method => { current = false; return snapshot() } }
  await assert.rejects(api.readExecutionSnapshot(transport, scope(), () => current), /scope_changed/)
  const unavailable = await api.readExecutionSnapshot({ profileRoutes: async () => [route()], requestProfile: async () => { throw Error('private token must not surface') } }, scope())
  assert.equal(unavailable.available, false); assert.equal(JSON.stringify(unavailable).includes('private token'), false)
})
test('a foreign backend snapshot is unavailable rather than silently queried elsewhere', async () => {
  const api = load(), calls = []
  const reply = await api.readExecutionSnapshot({ profileRoutes: async () => [route()], requestProfile: async (r, method) => { calls.push(r); return { ...snapshot(), origin_profile: 'wallace' } } }, scope())
  assert.equal(reply.available, false); assert.deepEqual(reply.rows, []); assert.equal(calls.length, 3)
})
test('registration contributes compact composer and panel only on a supported SDK, without reads/writes', () => {
  const api = load(), contributions = [], settings = []
  api.pluginDefinition.register({ registerMany: rows => contributions.push(...rows), registerSettingsPage: page => settings.push(page) })
  assert.equal(contributions.find(item => item.id === 'execution-composer').area, 'composer.top')
  assert.equal(contributions.find(item => item.id === 'execution-panel').area, 'panes')
  assert.equal(contributions.find(item => item.id === 'execution-panel').data.placement, 'bottom')
  assert.equal(settings.length, 1); assert.deepEqual(api.reads, [])
})
test('compact and panel share a cache key, bounded query polling and lifecycle-owned invalidation', async () => {
  const api = load()
  api.ExecutionPanel({ compact: true }); const key = api.options().queryKey
  api.ExecutionPanel({}); assert.deepEqual(api.options().queryKey, key)
  assert.equal(api.options().retry, false); assert.ok(api.options().refetchInterval >= 3000)
  const dispose = api.effects[0](); assert.ok(api.subscriptions.length > 0)
  api.subscriptions[0].callback({ payload: { rows: [{ profile: 'foreign' }] } }); await Promise.resolve()
  assert.deepEqual(api.reads, ['refresh'])
  api.host.state.activeSessionId = { get: () => 'new-parent' }
  api.subscriptions[0].callback({ payload: { rows: [{ profile: 'foreign' }] } }); await Promise.resolve()
  assert.deepEqual(api.reads, ['refresh']); dispose(); assert.equal(api.subscriptions.every(item => item.disposed), true)
})
test('previous-scope cached data is hidden immediately and empty/new sessions do not query', () => {
  const api = load(); api.query.data = { ...api.query.data, scope_key: '["other","claire","parent"]', rows: [{ ...row(), requested: { kind: 'profile', profile: 'secret-profile' } }] }
  assert.doesNotMatch(text(api.ExecutionPanel({})), /secret-profile/)
  api.host.state.activeSessionId = { get: () => null }; assert.match(text(api.ExecutionPanel({})), /대화를 선택/); assert.equal(api.options().enabled, false)
})
test('long identifiers wrap locally without global styles or HTML execution', () => {
  const api = load(), tree = api.ExecutionRow({ row: { ...row(), model: 'long-name-'.repeat(20) } })
  const article = [...walk(tree)].find(node => node.type === 'article')
  assert.equal(article.props.style.minWidth, 0); assert.equal(article.props.style.overflowWrap, 'anywhere')
  assert.equal([...walk(tree)].some(node => node.props?.dangerouslySetInnerHTML), false)
})
