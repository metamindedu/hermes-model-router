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
  const query = { isPending: false, isError: false, isFetching: false, data: { scope_key: '["owner","claire","parent"]', observation_generation: 1, observation_lifetime: 'leaf-fixture', observation_epoch: 1, available: true, rows }, refetch: async () => { reads.push('refresh') } }
  Object.assign(params, { DesktopSDK: { COMPOSER_AREAS: { top: 'composer.top' } }, host, jsx, jsxs: jsx,
    useState: value => [value, () => {}], useRef: value => ({ current: value }), useEffect: effect => effects.push(effect),
    useQuery: options => { queryOptions = options; return query }, useValue: atom => atom.get(), ...overrides })
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const api = new Function(...Object.keys(params), code + '\nreturn {executionTokenText,executionTokenTotal,executionId,executionScopeKey,executionScopeFromState,selectExecutionRoute,executionIdentity,executionLabel,mergeExecutionRows,projectExecutionReplay,createExecutionReplayStore,createActiveExecutionObserver,overlayExecutionReplay,readExecutionSnapshot,ExecutionRow,ExecutionPanel,ExecutionStrip,ExecutionLine,sortExecutionRows,profileJobExecutionRow,normalizeProfileJobs,executionSpare,composerStripVisible,pluginDefinition}')( ...Object.values(params))
  // Leaf rendering/invalidation fixture. Actual observer transport/fences are
  // exercised separately in test_active_execution_observer.mjs.
  const observer = { cacheId: 'leaf-fixture', revisionAtom: { get: () => 1 }, eligible: selected => Boolean(api.executionScopeKey(selected)),
    accepts: (selected,data) => data?.scope_key === api.executionScopeKey(selected) && data?.observation_generation === 1 && data?.observation_lifetime === 'leaf-fixture' && data?.observation_epoch === 1,
    current: selected => api.executionScopeKey(selected) === api.executionScopeKey(api.executionScopeFromState(host.state)) }
  return { ...api, ExecutionPanel: props => api.ExecutionPanel({ ...props, observer }), host, query, rows, subscriptions, effects, reads, options: () => queryOptions }
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
test('composer strip orders running work first and summarises counts with slot and model', () => {
  const api = load(), now = Date.now() / 1000
  const model = (id, status, extra = {}) => ({ ...row(id), requested: { kind: 'model', role: 'light', slot: 'code-simple', profile: null }, status, ...extra })
  const rows = [model('old-done', 'completed', { updated_at: now - 300, duration_seconds: 42, model: 'gpt-6.1-terra', model_source: 'api' }),
    model('failed', 'error', { updated_at: now - 100 }),
    model('run-old', 'running', { started_at: now - 90, model: 'gpt-6.1-sol' }),
    model('new-done', 'completed', { updated_at: now - 10, model: 'gpt-6-astra' }),
    model('run-new', 'running', { started_at: now - 5 })]
  assert.deepEqual(api.sortExecutionRows(rows).map(item => item.id), ['run-new', 'run-old', 'new-done', 'failed', 'old-done'])
  const strip = api.ExecutionStrip({ rows })
  const summary = text(strip.props.children[0])
  assert.match(summary, /서브에이전트 · 실행 중 2 · 완료 2 · 오류 1/)
  assert.match(summary, /코드 · 간단 · gpt-6\.1-sol · 1분 3\d초/)
  assert.doesNotMatch(summary, /Heavy|Light|미확인|포커스 대화/)
  const lines = strip.props.children[1].props.children.filter(Boolean)
  assert.deepEqual(lines.map(item => item.props.row.id), ['run-new', 'run-old', 'new-done', 'failed', 'old-done'])
  const line = text(api.ExecutionLine({ row: rows[0] }))
  assert.match(line, /완료 코드 · 간단 gpt-6\.1-terra 42초/); assert.match(line, /API 호출 기준/); assert.match(line, /하위 작업 sa-0-native/)
  assert.match(text(api.ExecutionLine({ row: rows[4] })), /모델 보고 전/)
  // Only finished work: the latest one is the chip.
  assert.match(text(api.ExecutionStrip({ rows: [rows[0], rows[3]] }).props.children[0]), /완료 2 .*코드 · 간단 · gpt-6-astra · 완료/)
  assert.equal(api.ExecutionStrip({ rows: [] }), null)
  // Gaps, conflicts and stops are never counted as completed.
  const mixed = [rows[0], model('gap', 'unknown', { observation_gap: true }), model('stop', 'cancelled'), model('int', 'interrupted'), model('t', 'timeout')]
  assert.match(text(api.ExecutionStrip({ rows: mixed }).props.children[0]), /서브에이전트 · 완료 1 · 오류 1 · 중단 2 · 미확인 1/)
  const job = { id: 'j', target_profile: 'wallace', status: 'completed', created_at: now - 50, updated_at: now - 1 }
  const gatewayRow = api.profileJobExecutionRow(job)
  assert.deepEqual([gatewayRow.started_at, gatewayRow.updated_at], [now - 50, now - 1])
  assert.equal(api.sortExecutionRows([rows[3], gatewayRow])[0].id, 'gateway:j', 'a newer finished gateway job sorts first')
  assert.match(text(api.ExecutionStrip({ rows: [], unavailable: true })), /읽을 수 없습니다/)
})
test('model and profile badges do not promote requests into verified runtime identity', () => {
  const api = load()
  assert.equal(api.executionLabel({ kind: 'model', role: 'heavy' }), '모델 · Heavy')
  assert.equal(api.executionLabel({ kind: 'model', role: 'light' }), '모델 · Light')
  assert.equal(api.executionLabel(api.executionIdentity({ kind: 'model', role: 'light', slot: 'code-simple' })), '모델 · 코드 · 간단')
  assert.equal(api.executionIdentity({ kind: 'model', role: 'light', slot: '../x' }).slot, null)
  assert.equal(api.executionLabel({ kind: 'profile', profile: 'wallace' }), '프로필 · wallace')
  assert.equal(api.executionIdentity({ kind: 'model', role: 'heavy' }).evidence, 'unknown')
  assert.deepEqual(api.executionIdentity({ kind: 'profile', profile: 'wallace', role: 'heavy' }), unknown())
  assert.deepEqual(api.executionIdentity({ kind: 'model', role: 'heavy', evidence: 'response_verified' }), { kind: 'model', role: 'heavy', profile: null, slot: null, evidence: 'unknown' })
})
test('split units correlate live call IDs without duplicate cards or suffix inference', () => {
  const api = load(), data = snapshot()
  data.rows = [
    {...row('split:0'), delegation_id:'opaque-unit-z', async_unit_id:'opaque-unit-z', native_call_delegation_id:'call-wide'},
    {...row('split:1'), subagent_id:'sa-1-native', task_index:1, delegation_id:'opaque-unit-a', async_unit_id:'opaque-unit-a', native_call_delegation_id:'call-wide',
      requested:{kind:'model',role:'heavy',profile:null}}
  ]
  const live = {subagents:[
    {subagent_id:'sa-0-native',delegation_id:'call-wide',status:'running'},
    {subagent_id:'sa-1-native',delegation_id:'call-wide',status:'running'}
  ]}
  const cards = api.mergeExecutionRows(data, live, 'claire')
  assert.equal(cards.length,2)
  assert.deepEqual(cards.map(c=>c.status),['running','running'])
  assert.deepEqual(cards.map(c=>c.async_unit_id),['opaque-unit-z','opaque-unit-a'])
  assert.equal(cards[0].requested.profile,'wallace'); assert.equal(cards[1].requested.role,'heavy')
  assert.ok(cards.every(c=>c.native_call_delegation_id==='call-wide' && c.observed.kind==='unknown'))
  data.rows[0].status='completed'
  assert.equal(api.mergeExecutionRows(data,live,'claire').length,2,'late live row must not duplicate a settled child')
})
test('invalid explicit call/unit metadata cannot borrow legacy unit-as-call matching', () => {
  const api=load(), live={subagents:[{subagent_id:'sa-0-native',delegation_id:'deleg-native',status:'running'}]}
  for(const extra of [{native_call_delegation_id:null},{native_call_delegation_id:'other-call'},
      {native_call_delegation_id:'deleg-native',async_unit_id:'different-unit'}]){
    const data=snapshot(); Object.assign(data.rows[0],extra)
    const cards=api.mergeExecutionRows(data,live,'claire')
    assert.equal(cards[0].status,'unknown'); assert.equal(cards[0].model,null)
  }
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
  assert.equal(rows[0].status, 'unknown'); assert.equal(rows[0].last_status, 'dispatched'); assert.equal(rows[1].requested.kind, 'unknown')
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
  assert.match(pending, /프로필 · wallace/); assert.match(pending, /역할은 요청 기준/)
  const actual = { ...requested, observed: { kind: 'profile', role: null, profile: 'wallace', evidence: 'runtime_reported' } }
  const output = text(api.ExecutionRow({ row: actual }))
  assert.match(output, /런타임 보고/); assert.match(output, /개별 API 응답/); assert.match(output, /네이티브/)
  assert.doesNotMatch(output, /검증 완료|전체 프로필/)
  const modelRow = { ...requested, requested: { kind: 'model', role: 'light', slot: 'code-simple', profile: null }, model: 'gpt-6.1-terra', provider: 'openai-codex', model_source: 'api' }
  const reported = text(api.ExecutionRow({ row: modelRow }))
  assert.match(reported, /모델 · 코드 · 간단/); assert.match(reported, /실행: gpt-6\.1-terra · openai-codex \(API 호출 기준\)/)
  assert.doesNotMatch(reported, /실행: 미확인/)
  assert.match(text(api.ExecutionRow({ row: { ...modelRow, model: null, provider: null } })), /아직 API 호출 보고 없음/)
})
test('model and provider stay one pair from one source; the roster model is never labelled as an API report', () => {
  const api = load(), live = status => ({ subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'deleg-native', status, model: 'primary-model' }] })
  const data = snapshot(); data.rows[0] = { ...data.rows[0], status: 'running', model: 'spare-model', provider: 'spare-provider' }
  const [hooked] = api.mergeExecutionRows(data, live('running'), 'claire')
  assert.deepEqual([hooked.model, hooked.provider, hooked.model_source], ['spare-model', 'spare-provider', 'api'])
  const queued = snapshot(); queued.rows[0] = { ...queued.rows[0], status: 'queued' }
  const [rosterOnly] = api.mergeExecutionRows(queued, live('queued'), 'claire')
  assert.deepEqual([rosterOnly.model, rosterOnly.provider, rosterOnly.model_source], ['primary-model', null, 'roster'])
  const output = text(api.ExecutionLine({ row: rosterOnly }))
  assert.match(output, /primary-model \(시작 시 배정/); assert.doesNotMatch(output, /API 호출 기준/)
  const routed = snapshot(); routed.rows[0] = { ...routed.rows[0], observed: { kind: 'model', role: 'light', model: 'route-model', provider: 'route-provider', evidence: 'runtime_reported' } }
  assert.deepEqual(api.mergeExecutionRows(routed, live('running'), 'claire').map(item => [item.model, item.provider, item.model_source])[0], ['route-model', 'route-provider', 'route'])
})
test('a completed profile delegation shows its stored route report instead of 모델 보고 없음', () => {
  // The origin's API hooks never see a profile-routed child's calls and the live roster is gone
  // after completion; the backend fills observed from the stored delegation route report.
  const api = load(), data = snapshot()
  data.rows[0] = { ...data.rows[0], status: 'completed', duration_seconds: 144,
    observed: { kind: 'profile', role: null, profile: 'wallace', backend: 'model-router-auto',
      model: 'qwen/qwen4-max:free', provider: 'nous', evidence: 'runtime_reported' } }
  const [merged] = api.mergeExecutionRows(data, { subagents: [] }, 'claire')
  assert.deepEqual([merged.model, merged.provider, merged.model_source], ['qwen/qwen4-max:free', 'nous', 'route'])
  assert.equal(merged.status, 'completed')
  const line = text(api.ExecutionLine({ row: merged }))
  assert.match(line, /완료 프로필 · wallace qwen\/qwen4-max:free 2분 24초/)
  assert.match(line, /실행: qwen\/qwen4-max:free · nous \(런타임 보고\)/)
  assert.doesNotMatch(line, /모델 보고 없음|아직 API 호출 보고 없음/)
  assert.match(text(api.ExecutionStrip({ rows: [merged] }).props.children[0]), /프로필 · wallace · qwen\/qwen4-max:free · 완료 2분 24초/)
  const panel = text(api.ExecutionRow({ row: merged }))
  assert.match(panel, /실행 모델: qwen\/qwen4-max:free · nous/); assert.match(panel, /런타임 보고/)
  // Replay counters coexist with the stored route report (the screenshot's 11 calls / token total).
  const withCounters = { ...merged, api_call_count: 11, token_total: 324449, tool_count: 17 }
  const counted = text(api.ExecutionLine({ row: withCounters }))
  assert.match(counted, /모델 호출 11회/); assert.match(counted, /토큰 32만 \(완료 보고 기준\)/)
  assert.match(counted, /qwen\/qwen4-max:free · nous \(런타임 보고\)/)
  // Without the stored report the honest placeholder stays (running or unsupported origins).
  const bare = api.mergeExecutionRows(snapshot(), { subagents: [] }, 'claire')[0]
  assert.match(text(api.ExecutionLine({ row: { ...bare, status: 'completed' } })), /모델 보고 없음/)
})
test('a whole-call refused request is settled as 오류, never counted as 실행 중', () => {
  // The roster settles a top-level delegate_task refusal to status 'error'; the strip must
  // count it as a failed row, not leave a phantom active request running forever.
  const api = load(), data = snapshot()
  data.rows[0] = { ...data.rows[0], status: 'error' }
  const [merged] = api.mergeExecutionRows(data, { subagents: [] }, 'claire')
  assert.equal(merged.status, 'error')
  const summary = text(api.ExecutionStrip({ rows: [merged] }).props.children[0])
  assert.match(summary, /서브에이전트 · 오류 1/)
  assert.doesNotMatch(summary, /실행 중/)
  assert.match(text(api.ExecutionLine({ row: merged })), /오류/)
  // A still-requested row IS active (the pre-refusal state), proving the count tracks status.
  const pending = snapshot(); pending.rows[0] = { ...pending.rows[0], status: 'requested' }
  const [requested] = api.mergeExecutionRows(pending, { subagents: [] }, 'claire')
  assert.equal(requested.status, 'requested')
  assert.match(text(api.ExecutionStrip({ rows: [requested] }).props.children[0]), /실행 중 1/)
})
test('a spare-model switch names the model that ran and the routed model it replaced', () => {
  const api = load()
  const data = snapshot(); data.rows[0] = { ...data.rows[0], requested: { kind: 'model', role: 'light', slot: 'code-simple', profile: null }, status: 'running',
    model: 'gemini-4-hydrogen', provider: 'gemini', models: [{ model: 'gpt-6.1-terra', provider: 'openai-codex' }, { model: 'gemini-4-hydrogen', provider: 'gemini' }, { model: '../bad', provider: 'x' }] }
  const [row] = api.mergeExecutionRows(data, { subagents: [] }, 'claire')
  assert.equal(row.models.length, 2, 'unsafe pairs are dropped')
  assert.equal(api.executionSpare(row).changed, true)
  const line = text(api.ExecutionLine({ row }))
  assert.match(line, /gemini-4-hydrogen · 모델 변경 관찰/)
  assert.match(line, /gemini-4-hydrogen · gemini \(API 호출 기준 · 모델 변경 관찰: gpt-6\.1-terra · openai-codex → gemini-4-hydrogen · gemini\)/)
  // The first observed pair is not claimed to be the routed model.
  assert.doesNotMatch(line, /기본 gpt|에서 전환/)
  assert.match(text(api.ExecutionStrip({ rows: [row] }).props.children[0]), /gemini-4-hydrogen \(모델 변경\)/)
  const back = { ...row, model: 'gpt-6.1-terra', provider: 'openai-codex' }
  assert.equal(api.executionSpare(back).changed, false)
  assert.match(text(api.ExecutionLine({ row: back })), /변경 관찰: gpt-6\.1-terra · openai-codex → gemini-4-hydrogen · gemini/)
  const aba = { ...back, models: [...row.models.slice(0, 2), { model: 'gpt-6.1-terra', provider: 'openai-codex' }] }
  assert.match(text(api.ExecutionLine({ row: aba })), /gpt-6\.1-terra · openai-codex → gemini-4-hydrogen · gemini → gpt-6\.1-terra · openai-codex\)/)
  const cut = { ...aba, models_truncated: true }
  assert.match(text(api.ExecutionLine({ row: cut })), /gpt-6\.1-terra · openai-codex → … → gemini-4-hydrogen/)
  // One pair only: no spare claim; route/roster sources never claim a spare.
  assert.equal(api.executionSpare({ ...row, models: [row.models[0]] }), null)
  assert.equal(api.executionSpare({ ...row, model_source: 'roster' }), null)
})
test('the composer strip gates on the public SDK session identity, not host markup', () => {
  const api = load()
  // Positive identity match only; an unknown composer session or focus hides the strip.
  assert.equal(api.composerStripVisible('A', 'A'), true)
  assert.equal(api.composerStripVisible('A', 'B'), false)
  assert.equal(api.composerStripVisible(null, 'A'), false)
  assert.equal(api.composerStripVisible('A', null), false)
  assert.equal(api.composerStripVisible('', 'A'), false)
  assert.equal(api.composerStripVisible('A', ''), false)
  // Ids are compared by value, never parsed as markup or put into a selector.
  assert.equal(api.composerStripVisible('x"]\n', 'x"]\n'), true)
  assert.equal(api.composerStripVisible('tile:A', 'A'), false, 'a raw tile target is not a stored session id')
})

test('full-profile job controls and the profile-job guide stay reachable from the composer strip', () => {
  const api = load(), job = { id: 'job-1', target_profile: 'wallace', status: 'running' }
  const rows = [{ id: 'gateway:job-1', execution_mode: 'gateway', requested: { kind: 'profile', profile: 'wallace', role: null }, observed: unknown(), status: 'running', job }, row()]
  const panel = []
  const closed = api.ExecutionStrip({ rows, jobsPanel: () => { panel.push(1); return null } })
  assert.ok(!closed.props.children[1].props.children.some(item => /전체 프로필 작업/.test(item?.props?.label || '')), 'a closed strip does not mount the guide')
  const strip = api.ExecutionStrip({ rows, defaultOpen: true, jobControls: item => ({ type: 'Controls', props: { job: item.job } }), jobsPanel: () => { panel.push(1); return null } })
  const items = strip.props.children[1].props.children
  const gateway = items.find(item => item.props?.row?.id === 'gateway:job-1'), native = items.find(item => item.props?.row?.id === 'call:0')
  assert.equal(gateway.props.controls.props.job, job); assert.equal(native.props.controls, null)
  assert.ok(text(api.ExecutionLine({ row: rows[0], controls: { type: 'Controls', props: { children: 'JOB-CONTROLS' } } })).includes('JOB-CONTROLS'))
  assert.ok(items.some(item => /전체 프로필 작업/.test(item.props?.label || '')))
  assert.equal(panel.length, 0, 'the guide is not mounted (and issues no reads) until opened')
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
test('registration contributes the compact composer and no layout pane, without reads/writes', () => {
  const api = load(), contributions = [], settings = []
  api.pluginDefinition.register({ registerMany: rows => contributions.push(...rows), registerSettingsPage: page => settings.push(page) })
  assert.equal(contributions.find(item => item.id === 'execution-composer').area, 'composer.top')
  // Closing a plugin's only pane disables the whole plugin in the host.
  assert.deepEqual(contributions.filter(item => item.area === 'panes'), [])
  assert.equal(settings.length, 1); assert.deepEqual(api.reads, [])
})
test('compact and panel share a cache key, bounded query polling and lifecycle-owned invalidation', async () => {
  const api = load()
  api.ExecutionPanel({ compact: true }); const key = api.options().queryKey
  api.ExecutionPanel({}); assert.deepEqual(api.options().queryKey, key)
  assert.equal(api.options().retry, false); assert.ok(api.options().refetchInterval >= 3000); assert.equal(api.options().gcTime,0)
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

test('terminal hook snapshot survives live roster removal and stale running frames', () => {
  const api = load()
  for (const status of ['completed', 'failed', 'error', 'interrupted', 'cancelled', 'timeout']) {
    const data = snapshot(); Object.assign(data.rows[0], { status, model: 'settled-model', duration_seconds: 65 })
    assert.equal(api.mergeExecutionRows(data, { subagents: [] }, 'claire')[0].status, status)
    const late = { subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'deleg-native', status: 'running', model: 'stale-model' }] }
    const projected = api.mergeExecutionRows(data, late, 'claire')[0]
    assert.equal(projected.status, status); assert.equal(projected.model, 'settled-model')
    assert.equal(projected.observation_gap, false)
  }
})
test('native snapshot fields reach the card without admitting goal, arguments or thinking', () => {
  const api = load(), data = snapshot()
  const runtime = { subagent_id: 'sa-0-native', delegation_id: 'deleg-native', child_session_id: 'child-stored', status: 'running',
    model: 'vendor/model', tool_count: 7, last_tool: 'read_file', started_at: Date.now() / 1000 - 70,
    goal: 'PRIVATE_GOAL', args: 'PRIVATE_ARGUMENTS', thinking: 'PRIVATE_THINKING' }
  Object.assign(data.rows[0], { api_call_count: 3, activity_at: Date.now() / 1000, provider: 'provider' })
  const projected = api.mergeExecutionRows(data, { subagents: [runtime] }, 'claire')[0]
  assert.equal(projected.tool_count, 7); assert.equal(projected.last_tool, 'read_file')
  assert.equal(projected.child_session_id, 'child-stored'); assert.equal(projected.api_call_count, 3)
  const rendered = text(api.ExecutionRow({ row: projected }))
  assert.match(rendered, /실행 중/); assert.match(rendered, /도구 7회/); assert.match(rendered, /모델 호출 3회/)
  assert.match(rendered, /최근 도구: read_file/); assert.match(rendered, /경과: 1분/); assert.match(rendered, /최근 활동:/)
  assert.doesNotMatch(JSON.stringify(projected) + rendered, /PRIVATE_/)
  assert.equal(projected.observed.kind, 'unknown', 'model metadata is not proof of a profile or Heavy role')
})
test('invalid activity fields and tool argument strings are omitted rather than rendered', () => {
  const api = load(), data = snapshot()
  Object.assign(data.rows[0], { status: 'completed', tool_count: -1, api_call_count: true, last_tool: 'terminal(password=PRIVATE)',
    started_at: Infinity, activity_at: Infinity, duration_seconds: NaN })
  const projected = api.mergeExecutionRows(data, { subagents: [] }, 'claire')[0]
  assert.equal(projected.tool_count, null); assert.equal(projected.api_call_count, null); assert.equal(projected.last_tool, null)
  assert.equal(projected.started_at, null); assert.equal(projected.activity_at, null); assert.equal(projected.duration_seconds, null)
  assert.doesNotMatch(text(api.ExecutionRow({ row: projected })), /PRIVATE|Infinity|NaN|모델 호출 \d+회|도구 -/)
  assert.match(text(api.ExecutionRow({ row: projected })), /도구 횟수 미관찰/)
  assert.match(text(api.ExecutionRow({ row: projected })), /모델 호출 횟수 미관찰/)
})
test('absence displays an observation gap, never an eternal dispatched or fabricated success', () => {
  const api = load(), projected = api.mergeExecutionRows(snapshot(), { subagents: [] }, 'claire')[0]
  assert.equal(projected.status, 'unknown'); assert.equal(projected.observation_gap, true)
  const rendered = text(api.ExecutionRow({ row: projected }))
  assert.match(rendered, /상태 미확인/); assert.match(rendered, /완료로 판단하지/); assert.match(rendered, /최근 관찰 상태: 위임 접수/)
  assert.equal(api.mergeExecutionRows(snapshot(), null, 'claire')[0].status, 'dispatched', 'failed live read is not an empty successful roster')
})
test('queued snapshot without live evidence is a gap, not an eternal waiting claim', () => {
  const api = load(), data = snapshot(); data.rows[0].status = 'queued'
  const absent = api.mergeExecutionRows(data, { subagents: [] }, 'claire')[0]
  assert.equal(absent.status, 'unknown'); assert.equal(absent.last_status, 'queued'); assert.equal(absent.observation_gap, true)
  const present = {subagents:[{subagent_id:'sa-0-native',delegation_id:'deleg-native',status:'queued'}]}
  assert.equal(api.mergeExecutionRows(data, present, 'claire')[0].status, 'queued')
})
test('compacted child session is accepted only within the exact native execution IDs', () => {
  const api = load(), data = snapshot(); data.rows[0].child_session_id = 'original-child'
  const live = { subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'deleg-native', child_session_id: 'compacted-child', status: 'running', last_tool: 'read_file', model: 'live-model' }] }
  const projected = api.mergeExecutionRows(data, live, 'claire')[0]
  assert.equal(projected.status, 'running'); assert.equal(projected.model, 'live-model'); assert.equal(projected.last_tool, 'read_file')
  assert.equal(projected.child_session_id, 'compacted-child')
  live.subagents[0].delegation_id = 'other-execution'
  assert.equal(api.mergeExecutionRows(data, live, 'claire')[0].status, 'unknown')
})
test('current dotted native events invalidate reads, but event payloads never supply row state', async () => {
  const api = load(); api.ExecutionPanel({ compact: true }); const dispose = api.effects[0]()
  const types = api.subscriptions.map(item => item.type)
  for (const type of ['subagent.spawn_requested', 'subagent.start', 'subagent.progress', 'subagent.tool', 'subagent.complete']) assert.ok(types.includes(type))
  api.subscriptions.find(item => item.type === 'subagent.complete').callback({ payload: { status: 'completed', secret: 'PRIVATE' } })
  await Promise.resolve(); assert.deepEqual(api.reads, ['refresh']); assert.deepEqual(api.rows, [])
  api.subscriptions.find(item => item.type === 'subagent.progress').callback({ payload: {} })
  assert.deepEqual(api.reads, ['refresh'], 'progress storms are coalesced; bounded polling recovers a skipped invalidation')
  dispose(); assert.equal(api.subscriptions.every(item => item.disposed), true)
})

// These test pure public-frame projection, not SDK routing or installed UI.
const replayFrame = (sequence, payload = {}, type = 'subagent.complete', epoch = 'epoch-1') => ({
  session_id: 'parent', replay_epoch: epoch, seq: sequence, type,
  payload: { delegation_id: 'deleg-native', subagent_id: 'sa-0-native', task_index: 0, status: 'completed', ...payload }
})
const replayReply = (events, latest = events.length, epoch = 'epoch-1', recovery = false) => ({
  events, latest_seq: latest, last_sequence: latest, replay_epoch: epoch, epoch,
  snapshot_required: recovery, truncated: recovery, count: events.length
})
function bootReplay(api, store, selected = scope()) {
  const token = store.cursor(selected)
  assert.equal(store.accept(selected, token, replayReply([], 0, 'epoch-1', true)).accepted, true)
  return store.cursor(selected)
}
test('public replay strips prose/requests/files/raw payload before any returned cache state', () => {
  const api = load(), store = api.createExecutionReplayStore(), token = bootReplay(api, store)
  const frame = replayFrame(1, { goal:'PRIVATE_CANARY', text:'PRIVATE_CANARY', summary:'PRIVATE_CANARY',
    output_tail:[{text:'PRIVATE_CANARY'}], files_read:['PRIVATE_CANARY'], tool_preview:'PRIVATE_CANARY',
    child_session_id:'reported-original', api_calls:2, tool_count:4, duration_seconds:1.5, tool_name:'read_file' })
  const reply = {...replayReply([frame]), open_requests:[{prompt:'PRIVATE_CANARY'}]}
  assert.equal(store.accept(scope(),token,reply,123).accepted,true)
  const projected=store.snapshot(scope()), value=projected.records[0]
  assert.doesNotMatch(JSON.stringify(projected), /PRIVATE_CANARY|payload|open_requests|files_read/)
  assert.equal(value.api_call_count,2); assert.equal(value.tool_count,4); assert.equal(value.received_at,123)
  assert.equal(value.reported_child_session_id,'reported-original')
  assert.equal(value.last_tool,'read_file'); assert.equal(projected.coverage_gap,false)
  assert.equal(projected.needs_recovery,false)
})
test('public replay validates the whole epoch/sequence/count/parent envelope atomically', () => {
  const api=load(), cursor={replay_epoch:'epoch-1',last_sequence:0}
  const valid=replayReply([replayFrame(1),replayFrame(2)])
  const bad=[{...valid,count:1}, {...valid,last_sequence:3}, {...valid,latest_seq:NaN},
    {...valid,events:[replayFrame(1),replayFrame(1)]},
    {...valid,events:[replayFrame(1),{...replayFrame(2),session_id:'foreign-parent'}]},
    {...valid,events:[replayFrame(1),replayFrame(2,{},'subagent.complete','epoch-other')]},
    {...valid,events:[replayFrame(1),replayFrame(3)]}, {...valid,epoch:'epoch-other'},
    {...valid,snapshot_required:true}, {...valid,events:new Array(4097)}]
  for(const reply of bad) {
    const result=api.projectExecutionReplay(reply,scope(),cursor)
    assert.equal(result.valid,false); assert.deepEqual(result.events,[])
  }
  const sorted=api.projectExecutionReplay({...valid,events:valid.events.toReversed()},scope(),cursor)
  assert.equal(sorted.valid,true); assert.deepEqual(sorted.events.map(value=>value.sequence),[1,2])
})
test('uninteresting native frames advance cursor without acquiring their content', () => {
  const api=load(), cursor={replay_epoch:'epoch-1',last_sequence:0}
  const frame=replayFrame(1,{text:'PRIVATE_CANARY'},'message.complete')
  const result=api.projectExecutionReplay(replayReply([frame]),scope(),cursor)
  assert.equal(result.last_sequence,1); assert.deepEqual(result.events,[])
  assert.doesNotMatch(JSON.stringify(result),/PRIVATE_CANARY/)
})
test('explicit per-child terminal precedes sibling join and survives stale running/list removal', () => {
  const api=load(), store=api.createExecutionReplayStore(), token=bootReplay(api,store)
  const complete=replayFrame(1,{status:'failed',tool_count:3,api_calls:2,child_session_id:'reported-original'})
  store.accept(scope(),token,replayReply([complete]),100)
  const data=snapshot(); data.rows.push({...row('call:1'),task_index:1,subagent_id:'sa-1-native'})
  const live={subagents:[{subagent_id:'sa-0-native',delegation_id:'deleg-native',status:'running',child_session_id:'rotated-physical'},
    {subagent_id:'sa-1-native',delegation_id:'deleg-native',status:'running'}]}
  const rows=api.overlayExecutionReplay(api.mergeExecutionRows(data,live,'claire'),store.snapshot(scope()),scope())
  assert.deepEqual(rows.map(value=>value.status),['failed','running'])
  assert.equal(rows[0].child_session_id,'rotated-physical','event locator is not proven current physical ID')
  assert.equal(rows[0].observed.kind,'unknown'); assert.equal(rows[0].requested.profile,'wallace')
  const next=replayFrame(2,{},'subagent.start')
  store.accept(scope(),store.cursor(scope()),replayReply([next],2),101)
  const settled=api.overlayExecutionReplay(api.mergeExecutionRows(snapshot(),{subagents:[]},'claire'),store.snapshot(scope()),scope())[0]
  assert.equal(settled.status,'failed'); assert.equal(settled.tool_count,3); assert.equal(settled.observation_gap,false)
})
test('pre-post terminal stays pending until exact dispatch row; split units do not infer a suffix', () => {
  const api=load(),store=api.createExecutionReplayStore(),token=bootReplay(api,store)
  store.accept(scope(),token,replayReply([replayFrame(1,{delegation_id:'actual-call'})]))
  assert.deepEqual(api.overlayExecutionReplay([],store.snapshot(scope()),scope()),[])
  const data=snapshot(); Object.assign(data.rows[0],{delegation_id:'opaque-unit',async_unit_id:'opaque-unit',native_call_delegation_id:'actual-call'})
  const rows=api.mergeExecutionRows(data,{subagents:[]},'claire')
  assert.equal(api.overlayExecutionReplay(rows,store.snapshot(scope()),scope())[0].status,'completed')
  for(const change of [{task_index:1},{subagent_id:'sa-other'},{native_call_delegation_id:'other-call'},
    {native_call_delegation_id:'actual-call',async_unit_id:'not-the-unit'}]) {
    assert.equal(api.overlayExecutionReplay([{...rows[0],...change}],store.snapshot(scope()),scope())[0].status,'unknown')
  }
})
test('missing/invalid terminal metadata never becomes successful completion or invented counts', () => {
  const api=load(),cursor={replay_epoch:'epoch-1',last_sequence:0}
  for(const change of [{status:undefined},{status:'running'},{subagent_id:undefined},{task_index:-1},{delegation_id:'../bad'}]) {
    const result=api.projectExecutionReplay(replayReply([replayFrame(1,change)]),scope(),cursor)
    assert.equal(result.valid,true); assert.deepEqual(result.events,[])
  }
  const projected=api.projectExecutionReplay(replayReply([replayFrame(1,{tool_count:-1,api_calls:true,duration_seconds:Infinity,tool_name:'PRIVATE KEY'})]),scope(),cursor).events[0]
  assert.equal(projected.tool_count,null); assert.equal(projected.api_call_count,null)
  assert.equal(projected.duration_seconds,null); assert.equal(projected.last_tool,null)
  for(const status of ['completed','failed','error','timeout','interrupted','cancelled']) {
    assert.equal(api.projectExecutionReplay(replayReply([replayFrame(1,{status})]),scope(),cursor).events[0].status,status)
  }
})
test('conflicting explicit terminal is unknown; failed/error aliases are not a conflict', () => {
  const api=load(),store=api.createExecutionReplayStore(); bootReplay(api,store)
  store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(1,{status:'failed'})]))
  store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(2,{status:'error'})],2))
  assert.equal(store.snapshot(scope()).records[0].terminal_conflict,false)
  store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(3,{status:'completed'})],3))
  const rows=api.mergeExecutionRows(snapshot(),{subagents:[]},'claire')
  const result=api.overlayExecutionReplay(rows,store.snapshot(scope()),scope())[0]
  assert.equal(result.status,'unknown'); assert.equal(result.terminal_conflict,true)
  const other=api.createExecutionReplayStore(); bootReplay(api,other)
  other.accept(scope(),other.cursor(scope()),replayReply([replayFrame(1)]))
  rows[0].status='timeout'
  assert.equal(api.overlayExecutionReplay(rows,other.snapshot(scope()),scope())[0].terminal_conflict,true)
})
test('epoch/gap drops stale running facts, preserves terminal facts and never claims recovery', () => {
  const api=load(),store=api.createExecutionReplayStore(); bootReplay(api,store)
  store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(1),replayFrame(2,{subagent_id:'sa-1-native',task_index:1},'subagent.start')]))
  assert.equal(store.snapshot(scope()).records.length,2)
  const old=store.cursor(scope())
  const result=store.accept(scope(),old,replayReply([],1,'epoch-2',true))
  assert.equal(result.needs_recovery,true)
  const value=store.snapshot(scope())
  assert.equal(value.coverage_gap,true); assert.equal(value.records.length,1); assert.equal(value.records[0].status,'completed')
  assert.equal(store.accept(scope(),old,replayReply([replayFrame(3)],3)).accepted,false)
  store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(1,{},'subagent.complete','epoch-2')],1,'epoch-2'))
  assert.equal(store.snapshot(scope()).coverage_gap,true,'a good tail cannot erase prior missing coverage')
})
test('scope/revision fences reject foreign source/profile/session, stale replies and forgotten A-B-A', () => {
  const api=load(),store=api.createExecutionReplayStore(); bootReplay(api,store)
  const old=store.cursor(scope())
  store.accept(scope(),old,replayReply([replayFrame(1)]))
  assert.equal(store.accept(scope(),old,replayReply([replayFrame(1)])).accepted,false)
  const rows=api.mergeExecutionRows(snapshot(),{subagents:[]},'claire')
  for(const selected of [{...scope(),connectionId:'foreign'}, {...scope(),profile:'foreign'}, {...scope(),sessionId:'foreign'}]) {
    assert.equal(api.overlayExecutionReplay(rows,store.snapshot(scope()),selected),rows)
    assert.equal(store.snapshot(selected),null)
  }
  const beforeForget=store.cursor(scope()); store.forget(scope()); bootReplay(api,store)
  assert.equal(store.accept(scope(),beforeForget,replayReply([replayFrame(2)],2)).accepted,false)
})
test('invalid replay cursors and regressing authenticated watermarks fail closed', () => {
  const api=load(), reply=replayReply([])
  for (const cursor of [{replay_epoch:'epoch-1',last_sequence:-1}, {replay_epoch:'epoch-1',last_sequence:true},
    {replay_epoch:'epoch-1',last_sequence:0,latest_seq:5}, {replay_epoch:'epoch-1',last_sequence:0,scope_key:'foreign'},
    {replay_epoch:'../bad',last_sequence:0}]) assert.equal(api.projectExecutionReplay(reply,scope(),cursor).valid,false)
  assert.equal(api.projectExecutionReplay(reply,scope(),{}).valid,false,'missing epoch requires the native bootstrap verdict')
  const store=api.createExecutionReplayStore(); bootReplay(api,store)
  store.accept(scope(),store.cursor(scope()),replayReply([],5,'epoch-2',true))
  assert.equal(store.accept(scope(),store.cursor(scope()),replayReply([replayFrame(1,{},'subagent.complete','epoch-2')],1,'epoch-2')).accepted,false)
  assert.equal(store.snapshot(scope()).coverage_gap,true)
})

test('replay retention is globally bounded and never persists or creates routes', () => {
  const api=load(),store=api.createExecutionReplayStore(); bootReplay(api,store)
  const frames=Array.from({length:513},(_,i)=>replayFrame(i+1,{subagent_id:`sa-${i}`,task_index:i}))
  store.accept(scope(),store.cursor(scope()),replayReply(frames))
  assert.deepEqual(store.counts(),{scopes:1,records:512}); assert.equal(store.snapshot(scope()).coverage_gap,true)
  for(let i=0;i<20;i++) store.cursor({...scope(),sessionId:`parent-${i}`})
  assert.equal(store.counts().scopes,16); assert.equal(store.counts().records,0)
  assert.deepEqual(api.subscriptions,[]); assert.deepEqual(api.reads,[])
  const unsupported = api.createActiveExecutionObserver(api.host, {})
  assert.equal(unsupported.eligible(scope()),false)
  assert.deepEqual(api.reads,[]); unsupported.dispose()
})

test('each execution shows its token total on the line and the breakdown in the body', () => {
  const api = load()
  assert.deepEqual([0, 999, 1234, 9949, 9999, 12345, 99499, 99950, 553000, 99994999, 99999999, 123456789].map(api.executionTokenText),
    ['0', '999', '1.2천', '9.9천', '1만', '1.2만', '9.9만', '10만', '55만', '9999만', '1억', '1.2억'])
  const data = snapshot(); data.rows[0] = { ...data.rows[0], status: 'completed', tool_count: 16,
    tokens: { input: 121159, cache_read: 427648, cache_write: 0, output: 2693 } }
  const [row] = api.mergeExecutionRows(data, { subagents: [] }, 'claire')
  assert.equal(api.executionTokenTotal(row), 551500)
  const line = text(api.ExecutionLine({ row }))
  assert.match(line, /도구 16회 · 토큰 55만/)
  assert.match(line, /토큰 55만: 입력 12만 · 캐시 읽기 43만 · 출력 2.7천/)
  assert.doesNotMatch(line, /캐시 쓰기/, 'zero cache buckets are omitted')
  const bad = snapshot(); bad.rows[0] = { ...bad.rows[0], tokens: { input: -1, output: 2 } }
  const [badRow] = api.mergeExecutionRows(bad, { subagents: [] }, 'claire')
  assert.equal(api.executionTokenTotal(badRow), null)
  assert.doesNotMatch(text(api.ExecutionLine({ row: badRow })), /토큰/)
  // MoA advisors: the hook sees the aggregator only, the native completion total counts all.
  const store = api.createExecutionReplayStore(), token = bootReplay(api, store)
  store.accept(scope(), token, replayReply([replayFrame(1, { status: 'completed', tool_count: 2, api_calls: 1, input_tokens: 700, output_tokens: 200 })]), 100)
  const moa = snapshot(); moa.rows[0] = { ...moa.rows[0], tokens: { input: 60, output: 40 } }
  const live = { subagents: [{ subagent_id: 'sa-0-native', delegation_id: 'deleg-native', status: 'running' }] }
  const [moaRow] = api.overlayExecutionReplay(api.mergeExecutionRows(moa, live, 'claire'), store.snapshot(scope()), scope())
  assert.equal(api.executionTokenTotal(moaRow), 900)
  const moaLine = text(api.ExecutionLine({ row: moaRow }))
  assert.match(moaLine, /도구 2회 · 토큰 900/)
  assert.match(moaLine, /토큰 900 \(완료 보고 기준\) · 모델 호출 관찰분 100: 입력 60 · 출력 40/)
  const same = { ...moaRow, token_total: 100 }
  assert.match(text(api.ExecutionLine({ row: same })), /토큰 100: 입력 60 · 출력 40/)
})
