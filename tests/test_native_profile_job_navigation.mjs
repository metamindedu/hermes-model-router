import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as nodeModule from 'node:module'
import path from 'node:path'
import test from 'node:test'

// Exact native public method bodies execute; store/network/navigation/hydration
// dependencies are substituted. This is not a real Desktop/Gateway/provider run.
const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const skip = !core ? 'set HERMES_DESKTOP_SOURCE_ROOT' : !nodeModule.stripTypeScriptTypes ? 'Node >=22.13 required for native TS method extraction' : false
function atom(initial) { let value = initial; return { get: () => value, set: next => { value = next } } }
function nativeHost(serve = async () => ({ nativeFixture: true })) {
  const index = readFileSync(path.join(core, 'apps/desktop/src/sdk/index.ts'), 'utf8')
  const profile = readFileSync(path.join(core, 'apps/desktop/src/sdk/profile-request.ts'), 'utf8')
  const plan = readFileSync(path.join(core, 'apps/desktop/src/sdk/plugin-open-session-plan.ts'), 'utf8')
  function method(name) {
    const start = index.indexOf(`  ${name}: async (`)
    assert.ok(start >= 0, `native SDK method missing: ${name}`)
    const end = index.indexOf('\n  },', start)
    assert.ok(end > start, `native SDK method terminator missing: ${name}`)
    return index.slice(start, end + 4)
  }
  const code = `${profile.replace(/^import .*$/gm, '').replace(/^export /gm, '')}\n${plan.replace(/^export /gm, '')}\nconst sdk = {${method('openSession')},${method('retainProfile')}};`
  const js = nodeModule.stripTypeScriptTypes(code, { mode: 'strip' })
  const calls = [], selected = atom(null), active = atom(null), messages = atom([])
  const io = {
    window: { location: { hash: '', replace() {} }, hermesDesktop: { getProfileRoutes: async () => [] } },
    $profiles: atom([]), $connection: atom({ mode: 'local', connectionId: 'source-connection' }),
    $activeGatewayProfile: atom('origin-alias'), $hydrationSyncProfile: atom(null), $gatewaySwapTarget: atom(null),
    $workspaceMode: atom('normal'), $workspaceOwnerKey: atom(null), $selectedStoredSessionId: selected,
    $activeSessionId: active, $messages: messages, $sessionTiles: atom([]),
    activeGatewayConnectionId: () => 'source-connection',
    normalizeProfileKey: value => { assert.equal(value, value.trim()); return value || 'default' },
    publishWorkspaceScope() { throw Error('unexpected workspace replacement') },
    setSessionOwnerHint: (sid, route) => calls.push({ kind: 'hint', sid, route }),
    openGatewayForAgent: async (connectionId, profile, options) => calls.push({ kind: 'dial', connectionId, profile, options }),
    ensureGatewayProfile() { throw Error('unexpected workspace switch') },
    openGatewayForProfile() { throw Error('unexpected unscoped dial') },
    awaitProfileActivation: async dial => dial(),
    setShowAllProfiles: value => calls.push({ kind: 'all-profiles', value }),
    openSession: (sid, navigate, intent) => { selected.set(sid); navigate(`/session/${sid}`); calls.push({ kind: 'navigate', sid, intent }) },
    sessionTileDelegate: () => null,
    requestSessionResume: (sid, route) => calls.push({ kind: 'resume', sid, route }),
    waitForFocusedSessionHydration: async options => calls.push({ kind: 'hydrate', options }),
    setResumeExhaustedSessionId: sid => calls.push({ kind: 'exhausted', sid }),
    logBotWake() {},
    retainGatewayForAgent: async (connectionId, profile, options) => {
      calls.push({ kind: 'retain', connectionId, profile, options })
      return () => calls.push({ kind: 'release' })
    },
    requestGatewayForAgent: async (...args) => { calls.push({ kind: 'request', args }); return serve(...args) },
    requestGatewayForProfile() { throw Error('unexpected profile-only fallback') },
    DEFAULT_SESSION_HYDRATION_TIMEOUT_MS: 20000
  }
  const run = new Function('io', `const {${Object.keys(io).join(',')}}=io; let openSessionGeneration=0,gatewaySwapTargetOwnerGeneration=null; ${js}; return {...sdk,requestProfile:requestPluginProfile};`)
  return { sdk: run(io), calls, io }
}

for (const mode of ['local', 'remote']) test(`actual native SDK ${mode} route keeps alias, owner hint, hidden zero-history resume and lease`, { skip }, async () => {
  const { sdk, calls, io } = nativeHost()
  const route = { connectionId: 'same-source-connection', mode, profile: 'frontend-worker-alias', targetProfile: 'worker' }
  const release = await sdk.retainProfile(route, { spawnPriority: 'foreground' })
  try {
    await sdk.requestProfile(route, 'runtime.describe', {})
    await sdk.requestProfile(route, 'session.info', { session_id: 'stored-tool-session' })
    await sdk.openSession('stored-tool-session', { route, awaitHydration: true, forceResume: true, expectHistory: false, keepAllProfilesScope: true })
  } finally { release() }
  assert.deepEqual(calls.filter(call => call.kind === 'retain').map(call => [call.connectionId, call.profile]), [['same-source-connection', 'frontend-worker-alias']])
  assert.deepEqual(calls.filter(call => call.kind === 'request').map(call => call.args.slice(0, 3)), [
    ['same-source-connection', 'frontend-worker-alias', 'runtime.describe'], ['same-source-connection', 'frontend-worker-alias', 'session.info']])
  assert.deepEqual(calls.find(call => call.kind === 'hint'), { kind: 'hint', sid: 'stored-tool-session', route })
  assert.deepEqual(calls.find(call => call.kind === 'dial'), { kind: 'dial', connectionId: route.connectionId, profile: route.profile, options: { spawnPriority: 'foreground' } })
  assert.deepEqual(calls.find(call => call.kind === 'resume'), { kind: 'resume', sid: 'stored-tool-session', route })
  assert.equal(calls.find(call => call.kind === 'hydrate').options.expectHistory, false)
  assert.equal(calls.find(call => call.kind === 'hydrate').options.profile, route.profile)
  assert.equal(io.$activeGatewayProfile.get(), 'origin-alias')
  assert.deepEqual(calls.filter(call => call.kind === 'release'), [{ kind: 'release' }])
  assert.equal(calls.filter(call => call.kind === 'navigate').length, 1)
  assert.equal(calls.some(call => /create|submit|approval|clarify|cli.exec/.test(call.args?.[2] || '')), false)
})

function pluginNavigation() {
  const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of match[1].split(',').map(s => s.trim()).filter(Boolean)) imports[name] = name
  imports.DesktopSDK = {}
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const definition = ').replace(/^export\s+/gm, '')
  return new Function(...Object.keys(imports), `${code}; return openProfileJobNative`)(...Object.values(imports))
}
for (const mode of ['local', 'remote']) test(`plugin composes with actual native SDK ${mode} request/retain/open methods`, { skip }, async () => {
  const scope = { connectionId: 'same-source-connection', profile: 'origin-alias', sessionId: 'parent' }
  const source = { ...scope, mode, targetProfile: 'origin' }
  const route = { connectionId: scope.connectionId, mode, profile: 'frontend-worker-alias', targetProfile: 'worker' }
  const job = { id: 'native-job', origin_profile: 'origin', parent_session_id: 'parent', target_profile: 'worker', execution_mode: 'gateway', status: 'approval_wait',
    target_session_id: 'stored-tool-session', target_profile_id: 'native-worker-home', target_instance_id: 'native-instance', target_authority_epoch: 7,
    target_cwd: 'C:/fixture-work', admission_id: 'native-admission', execution_generation: 9 }
  const { sdk, calls, io } = nativeHost(async (connectionId, profile, method, params) => {
    assert.equal(connectionId, scope.connectionId)
    if (method.endsWith('profile_jobs.list')) {
      assert.equal(profile, source.profile); assert.equal(params.session_id, scope.sessionId)
      return { schema: 1, origin_profile: 'origin', parent_session_id: 'parent', jobs: [job] }
    }
    assert.equal(profile, route.profile)
    if (method === 'runtime.describe') return { profile_id: job.target_profile_id, instance_id: job.target_instance_id, authority_epoch: 7 }
    assert.equal(method, 'session.info'); assert.equal(params.session_id, job.target_session_id)
    return { desktop_protocol: 'hermes-gateway-v1', profile_id: job.target_profile_id, profile_name: 'worker', source: 'tool', cwd: job.target_cwd,
      client: { name: 'model-router-profile-job' }, system_prompt: 'PRIVATE_NOT_PROJECTED' }
  })
  sdk.profileRoutes = async () => [source, route]
  const reply = await pluginNavigation()(sdk, scope, job)
  assert.deepEqual(reply, { opened: true, source_current: true })
  assert.equal(calls.filter(call => call.kind === 'release').length, 1)
  assert.equal(calls.filter(call => call.kind === 'navigate').length, 1)
  assert.deepEqual(calls.find(call => call.kind === 'resume').route, route)
  assert.equal(io.$activeGatewayProfile.get(), 'origin-alias')
  assert.equal(calls.some(call => /create|submit|approval|clarify|configure|cli.exec/.test(call.args?.[2] || '')), false)
})
