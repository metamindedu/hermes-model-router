import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function api() {
  const imports = {}
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(x => x.trim()).filter(Boolean)) imports[name] = name
  imports.DesktopSDK = {}
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function(...Object.keys(imports), code + '\nreturn {createExecutionFence,profileJobFence,normalizeProfileJobs,profileJobExecutionRow,profileJobsRequest,readProfileJobs,readExecutionSnapshot,nativeJobViewSupported,openProfileJobNative}')( ...Object.values(imports))
}
const scope = () => ({ connectionId: 'local-source', profile: 'claire', sessionId: 'parent' })
const route = () => ({ mode: 'local', connectionId: 'local-source', profile: 'claire', targetProfile: 'claire' })
const job = () => ({ id: 'job-fixture', origin_profile: 'claire', parent_session_id: 'parent', target_profile: 'wallace', execution_mode: 'gateway', status: 'running',
  target_session_id: 'target-session', admission_id: 'admission-fixture', execution_generation: 4, result_available: false, completion_delivery: 'explicit_result', pending_request: null })
const listing = () => ({ schema: 1, origin_profile: 'claire', parent_session_id: 'parent', completion_delivery: 'explicit_result', jobs: [job()] })
const describe = () => ({ schema: 1, origin_profile: 'claire', revision: 'a'.repeat(64), supported: true, policy: { schema: 1, enabled: false, targets: [] },
  targets: [{ profile: 'wallace', cwd: 'C:/fixture-work', available: true }], completion_delivery: 'explicit_result' })
function storage() { let value; return { get(_key, fallback) { return value === undefined ? fallback : structuredClone(value) }, set(_key, next) { value = structuredClone(next) }, peek() { return value } } }
function transport(reply = describe()) { const calls = []; return { calls, profileRoutes: async () => [route()], requestProfile: async (descriptor, method, params) => { calls.push({ descriptor, method, params }); return structuredClone(reply) } } }

test('epoch fence ignores equivalent owner objects but rejects ABA and gateway reconnection', () => {
  const a = api(); let current = scope(), gateway = 'open'
  const fence = a.createExecutionFence(() => current, () => gateway)
  const first = fence.capture(); current = { ...current }; fence.observe(); assert.equal(fence.current(first), true)
  current = { ...current, sessionId: 'other' }; fence.observe(); current = scope(); fence.observe(); assert.equal(fence.current(first), false)
  const second = fence.capture(); gateway = 'closed'; fence.observe(); gateway = 'open'; fence.observe(); assert.equal(fence.current(second), false)
  const last = fence.capture(); fence.dispose(); assert.equal(fence.current(last), false); fence.activate(); assert.equal(fence.current(last), false)
})
test('unknown write fences persist by exact source/job and corruption is fail-closed', () => {
  const a = api(), store = storage(), sourceKey = '["local-source","claire"]'
  assert.equal(a.profileJobFence(store, sourceKey), null)
  a.profileJobFence(store, sourceKey, { blocked: true, before_revision: 'a'.repeat(64) })
  assert.equal(api().profileJobFence(store, sourceKey).blocked, true)
  assert.equal(a.profileJobFence(store, '["other-source","claire"]'), null)
  a.profileJobFence(store, sourceKey, null); assert.equal(a.profileJobFence(store, sourceKey), null)
  assert.equal(a.profileJobFence(null, sourceKey).unavailable, true)
  assert.equal(a.profileJobFence({ get: () => ({ schema: 1, entries: [] }), set() {} }, sourceKey).blocked, true)
  assert.equal(a.profileJobFence(store, '__proto__').blocked, true)
})
test('long literal scope ids are supported without normalization or prototype keys', () => {
  const a = api(), store = storage(), key = JSON.stringify(['source-'.repeat(30), 'specialist', 'job-'.repeat(50)])
  a.profileJobFence(store, key, { blocked: true }); assert.equal(a.profileJobFence(store, key).blocked, true)
  assert.equal(a.profileJobFence(store, ' ["source","profile"] ').blocked, true)
})
test('full jobs project only bounded visible metadata and keep pending outcome unknown', () => {
  const a = api(), data = listing()
  data.jobs[0] = { ...job(), status: 'unknown', prompt: 'PRIVATE_PROMPT', messages: ['PRIVATE_MESSAGES'], result: { text: 'PRIVATE_RESULT' } }
  const jobs = a.normalizeProfileJobs(data, 'claire', 'parent')
  assert.equal(jobs.length, 1); assert.equal(jobs[0].status, 'unknown'); assert.equal(jobs[0].completion_delivery, 'explicit_result')
  assert.doesNotMatch(JSON.stringify(jobs), /PRIVATE/)
  const row = a.profileJobExecutionRow(jobs[0]); assert.equal(row.execution_mode, 'gateway'); assert.equal(row.requested.profile, 'wallace'); assert.equal(row.observed.evidence, 'unknown')
})
test('foreign origin/parent, malformed rows and duplicate jobs cannot inflate the roster', () => {
  const a = api(), data = listing()
  assert.equal(a.normalizeProfileJobs(data, 'wallace', 'parent'), null)
  assert.equal(a.normalizeProfileJobs(data, 'claire', 'another-parent'), null)
  data.jobs.push(job(), { ...job(), id: 'bad\njob' }, { ...job(), id: 'invalid-kind', execution_mode: 'native' }, { ...job(), id: 'foreign', origin_profile: 'other' })
  assert.equal(a.normalizeProfileJobs(data, 'claire', 'parent').length, 1)
})
test('approval projection retains only one-time choices and exact prompt/generation', () => {
  const a = api(), data = listing()
  data.jobs[0].pending_request = { kind: 'approval', prompt_id: 'request-fixture', execution_generation: 4, text: 'Fixture approval', choices: ['once', 'always', 'session', 'deny'] }
  const [j] = a.normalizeProfileJobs(data, 'claire', 'parent')
  assert.deepEqual(j.pending_request.choices, ['once', 'deny'])
  data.jobs[0].pending_request.execution_generation = '4'; assert.equal(a.normalizeProfileJobs(data, 'claire', 'parent')[0].pending_request, null)
})
test('even an acknowledged configuration cannot enter generic plugin RPC', async () => {
  const a = api(), host = transport()
  await assert.rejects(a.profileJobsRequest(host, scope(), 'configure', { expected_revision: 'a'.repeat(64), enabled: true, targets: ['wallace'], acknowledge_scope: true }), /invalid_request/)
  assert.equal(host.calls.length, 0)
})
test('arbitrary RPCs, supplied parents, paths, credentials and grant-less saves fail before dispatch', async () => {
  const a = api(), host = transport()
  for (const [operation, payload] of [['session.create', {}], ['configure', { expected_revision: 'a'.repeat(64), enabled: true, targets: ['wallace'], acknowledge_scope: false }],
    ['describe', { session_id: 'other' }], ['describe', { home: '/private' }], ['control', { job_id: 'j', operation: 'prompt.submit' }],
    ['configure', { expected_revision: 'a'.repeat(64), enabled: true, targets: ['../other'], acknowledge_scope: true }],
    ['configure', { expected_revision: 'a'.repeat(64), enabled: true, targets: ['wallace', 'wallace'], acknowledge_scope: true }]]) {
    await assert.rejects(a.profileJobsRequest(host, scope(), operation, payload), /invalid/)
  }
  assert.equal(host.calls.length, 0)
})
test('control requests have strict per-operation fields and never accept permanent approval', async () => {
  const a = api(), host = transport({ schema: 1, origin_profile: 'claire', job: { ...job(), id: 'j' } })
  for (const payload of [{ job_id: 'j', operation: 'stop', text: 'a prompt' }, { job_id: 'j', operation: 'steer', text: ' ' },
    { job_id: 'j', operation: 'approve', prompt_id: 'p', choice: 'always' }, { job_id: 'j', operation: 'clarify', prompt_id: 'p', answer: 5 },
    { job_id: 'j', operation: 'steer', text: 'instruction', execution_generation: 44 }]) await assert.rejects(a.profileJobsRequest(host, scope(), 'control', payload), /invalid/)
  assert.equal(host.calls.length, 0)
  for (const choice of ['once', 'deny']) await assert.rejects(a.profileJobsRequest(host, scope(), 'control', { job_id: 'j', operation: 'approve', prompt_id: 'p', choice }), /invalid/)
  await assert.rejects(a.profileJobsRequest(host, scope(), 'control', { job_id: 'j', operation: 'clarify', prompt_id: 'p', answer: 'yes' }), /invalid/)
  assert.equal(host.calls.length, 0)
})
test('scope change before or after descriptor resolution blocks all writes', async () => {
  const a = api(), host = transport(); let current = false
  await assert.rejects(a.profileJobsRequest(host, scope(), 'describe', {}, () => current), /scope_changed/)
  current = true; host.profileRoutes = async () => { current = false; return [route()] }
  await assert.rejects(a.profileJobsRequest(host, scope(), 'describe', {}, () => current), /scope_changed/)
  assert.equal(host.calls.length, 0)
})
test('post-dispatch errors and owner mismatch are unknown and never expose raw diagnostics', async () => {
  const a = api(), host = transport()
  host.requestProfile = async () => { throw Error('RAW_CREDENTIAL_OR_DIAGNOSTIC') }
  const error = await a.profileJobsRequest(host, scope(), 'describe').catch(e => e)
  assert.equal(error.sent, true); assert.doesNotMatch(error.message, /RAW_CREDENTIAL/)
  host.requestProfile = async () => ({ ...describe(), origin_profile: 'wallace' })
  await assert.rejects(a.profileJobsRequest(host, scope(), 'describe'), /owner_mismatch/)
})
test('policy reads do not grant access or contact targets and preserve a saved OFF', async () => {
  const a = api(), host = transport()
  const data = await a.readProfileJobs(host, scope())
  assert.equal(data.policy.enabled, false); assert.deepEqual(data.policy.targets, [])
  assert.deepEqual(host.calls.map(item => item.method), ['plugin.model-router.profile_jobs.describe'])
  assert.equal(data.completion_delivery, 'explicit_result')
})
test('authenticated known refusal clears uncertainty only for the exact responding owner', async () => {
  const a = api(), refused = { schema: 1, origin_profile: 'claire', status: 'refused', no_effect: true, error: 'invalid_or_denied' }
  const known = await a.profileJobsRequest(transport(refused), scope(), 'describe').catch(e => e)
  assert.equal(known.sent, false); assert.equal(known.noEffect, true)
  const foreign = await a.profileJobsRequest(transport({ ...refused, origin_profile: 'wallace' }), scope(), 'describe').catch(e => e)
  assert.equal(foreign.sent, true); assert.notEqual(foreign.noEffect, true)
  const unknown = await a.profileJobsRequest(transport({ ...refused, status: 'unknown', no_effect: false }), scope(), 'describe').catch(e => e)
  assert.equal(unknown.sent, true)
})
test('a different job ACK cannot clear an exact job control fence', async () => {
  const a = api(), host = transport({ schema: 1, origin_profile: 'claire', job: job() })
  const error = await a.profileJobsRequest(host, scope(), 'control', { job_id: 'another-job', operation: 'stop' }).catch(e => e)
  assert.equal(error.sent, true); assert.match(error.message, /job_mismatch/)
})
test('missing host authority is a read-only capability, never an implied grant', async () => {
  const a = api(), host = transport({ ...describe(), supported: false, reason_code: 'operator_authority_unavailable' })
  const data = await a.readProfileJobs(host, scope())
  assert.equal(data.supported, false); assert.equal(data.authority_blocked, true)
  assert.deepEqual(host.calls.map(item => item.method), ['plugin.model-router.profile_jobs.describe'])
  const panel = source.slice(source.indexOf('export function ProfileJobsPanel'), source.indexOf('export default'))
  assert.doesNotMatch(panel, /profileJobsRequest\([^\n]*'configure'/)
  assert.match(panel, /이 화면은 읽기 전용/)
  assert.match(panel, /operator_cli_supported/)
})
test('malformed policy/inventory is unavailable instead of silently repaired', async () => {
  const a = api()
  const samples = [{ ...describe(), policy: { schema: 1, enabled: 'true', targets: [] } }, { ...describe(), revision: 'bad' },
    { ...describe(), targets: [{ profile: 'wallace', cwd: null, available: true }] }, { ...describe(), targets: [describe().targets[0], describe().targets[0]] }]
  for (const sample of samples) await assert.rejects(a.readProfileJobs(transport(sample), scope()), /unavailable/)
})
test('common snapshot merges full and native without inventing native handles or hidden text', async () => {
  const a = api(), host = transport()
  host.requestProfile = async (_route, method) => method.endsWith('profile_jobs.list') ? listing() : method === 'subagent.list' ? { subagents: [] } : { schema: 1, origin_profile: 'claire', supported: true, rows: [] }
  const data = await a.readExecutionSnapshot(host, scope())
  assert.equal(data.rows.length, 1); assert.equal(data.rows[0].execution_mode, 'gateway'); assert.equal(data.full_jobs[0].id, 'job-fixture')
  assert.equal(data.rows[0].subagent_id, undefined); assert.equal(data.rows[0].delegation_id, undefined)
})

function nativeFixture(onStep = () => {}) {
  const selected = { ...job(), target_profile_id: 'native-worker', target_instance_id: 'native-instance', target_authority_epoch: 7, target_cwd: 'C:/fixture-work' }
  const destination = { ...route(), profile: 'writer-alias', targetProfile: 'wallace' }
  const state = { current: true, calls: [], jobs: [selected], routes: [route(), destination,
    { ...destination, connectionId: 'different-connection' }],
    runtime: { profile_id: 'native-worker', instance_id: 'native-instance', authority_epoch: 7 },
    info: { desktop_protocol: 'hermes-gateway-v1', profile_id: 'native-worker', profile_name: 'wallace', source: 'tool', cwd: 'C:/fixture-work',
      client: { name: 'model-router-profile-job' }, system_prompt: 'PRIVATE_INVENTORY_NOT_PROJECTED' } }
  const step = (kind, value = {}) => { state.calls.push({ kind, ...value }); onStep(kind, state) }
  const transport = {
    async profileRoutes() { step('routes'); return structuredClone(state.routes) },
    async retainProfile(descriptor, options) { step('retain', { descriptor, options }); return () => step('release') },
    async requestProfile(descriptor, method, params) {
      if (method.endsWith('profile_jobs.list')) { step('list', { descriptor, method, params }); return { ...listing(), jobs: structuredClone(state.jobs) } }
      if (method === 'runtime.describe') { step('runtime', { descriptor, method, params }); return structuredClone(state.runtime) }
      if (method === 'session.info') { step('info', { descriptor, method, params }); return structuredClone(state.info) }
      throw new Error('unexpected method')
    },
    async openSession(sessionId, options) { step('open', { sessionId, options }) }
  }
  return { state, transport, selected, destination }
}

test('native handoff uses exact backend identity and frontend alias with flat SID-less info', async () => {
  const a = api(), f = nativeFixture()
  const result = await a.openProfileJobNative(f.transport, scope(), f.selected, () => f.state.current)
  assert.deepEqual(result, { opened: true, source_current: true })
  const opened = f.state.calls.filter(call => call.kind === 'open')
  assert.equal(opened.length, 1); assert.equal(opened[0].sessionId, f.selected.target_session_id)
  assert.deepEqual(opened[0].options, { route: f.destination, awaitHydration: true, forceResume: true, expectHistory: false, keepAllProfilesScope: true })
  assert.equal(f.state.calls.filter(call => call.kind === 'release').length, 1)
  assert.deepEqual(f.state.calls.find(call => call.kind === 'info').params, { session_id: f.selected.target_session_id })
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE/)
  assert.equal(f.state.calls.some(call => /create|submit|approval|clarify|configure|cli.exec/.test(call.method || '')), false)
})

test('native navigation has no fallback across identity/route/session/SDK ambiguity', async t => {
  const cases = {
    epoch: f => { f.state.runtime.authority_epoch++ },
    instance: f => { f.state.runtime.instance_id = 'other' },
    runtimeProfile: f => { f.state.runtime.profile_id = 'other' },
    infoProfile: f => { f.state.info.profile_id = 'other' },
    profileName: f => { f.state.info.profile_name = 'other' },
    cwd: f => { f.state.info.cwd = 'C:/other-work' },
    source: f => { f.state.info.source = 'gui' },
    client: f => { f.state.info.client.name = 'another-client' },
    protocol: f => { f.state.info.desktop_protocol = 'legacy' },
    duplicateRoute: f => { f.state.routes.push({ ...f.destination, profile: 'second-alias' }) },
    foreignConnectionOnly: f => { f.state.routes = f.state.routes.filter(row => row.profile !== f.destination.profile || row.connectionId !== scope().connectionId) },
    missingJob: f => { f.state.jobs = [] },
    duplicateJob: f => { f.state.jobs.push({ ...f.selected }) },
    retargetedJob: f => { f.state.jobs = [{ ...f.selected, target_session_id: 'unrelated-session' }] },
    oldSDK: f => { delete f.transport.retainProfile },
    malformedLease: f => { f.transport.retainProfile = async () => null },
    failedLease: f => { f.transport.retainProfile = async () => { throw Error('PRIVATE_LEASE_DIAGNOSTIC') } }
  }
  for (const [name, change] of Object.entries(cases)) await t.test(name, async () => {
    const a = api(), f = nativeFixture(); change(f)
    const error = await a.openProfileJobNative(f.transport, scope(), f.selected, () => f.state.current).catch(error => error)
    assert.equal(error.message, 'profile_job_native_view_unavailable')
    assert.equal(f.state.calls.filter(call => call.kind === 'open').length, 0)
    assert.equal(f.state.calls.filter(call => call.kind === 'release').length, f.state.calls.some(call => call.kind === 'retain') ? 1 : 0)
  })
})

test('every pre-navigation await boundary fences scope drift and releases acquired lease', async t => {
  const reference = nativeFixture()
  await api().openProfileJobNative(reference.transport, scope(), reference.selected)
  const count = reference.state.calls.findIndex(call => call.kind === 'open')
  for (let boundary = 1; boundary <= count; boundary++) await t.test(`boundary-${boundary}`, async () => {
    let seen = 0
    const f = nativeFixture((kind, state) => { if (++seen === boundary) state.current = false })
    await assert.rejects(api().openProfileJobNative(f.transport, scope(), f.selected, () => f.state.current), /native_view_unavailable/)
    assert.equal(f.state.calls.some(call => call.kind === 'open'), false)
    assert.equal(f.state.calls.filter(call => call.kind === 'release').length, f.state.calls.some(call => call.kind === 'retain') ? 1 : 0)
  })
})

test('native open failure and release errors never expose raw diagnostics or replay work', async () => {
  for (const phase of ['open', 'release']) {
    const f = nativeFixture()
    if (phase === 'open') f.transport.openSession = async () => { f.state.calls.push({ kind: 'open' }); throw Error('PRIVATE_NATIVE_ERROR') }
    else f.transport.retainProfile = async () => () => { f.state.calls.push({ kind: 'release' }); throw Error('PRIVATE_NATIVE_ERROR') }
    await assert.rejects(api().openProfileJobNative(f.transport, scope(), f.selected), error => error.message === 'profile_job_native_view_unavailable')
    assert.equal(f.state.calls.filter(call => call.kind === 'open').length, 1)
    assert.equal(f.state.calls.filter(call => call.kind === 'release').length, 1)
  }
})

test('native handoff cannot undo focus changes after pinned open has started', async () => {
  const f = nativeFixture((kind, state) => { if (kind === 'open') state.current = false })
  const result = await api().openProfileJobNative(f.transport, scope(), f.selected, () => f.state.current)
  assert.deepEqual(result, { opened: true, source_current: false })
  assert.equal(f.state.calls.filter(call => call.kind === 'open').length, 1)
  assert.equal(f.state.calls.filter(call => call.kind === 'release').length, 1)
})

