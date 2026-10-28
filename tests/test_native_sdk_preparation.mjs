import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

// Opt-in host-source contract test. Only OS/gateway I/O is substituted; the
// installed SDK's actual descriptor dispatch AND gateway profile rewriting
// functions execute unchanged after TypeScript transpilation.
const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const pluginSource = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function plugin() {
  const imports = {}
  for (const m of pluginSource.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(x => x.trim()).filter(Boolean)) imports[name] = name
  const code = pluginSource.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function(...Object.keys(imports), code + '\nreturn {runProfilePreparation,selectPreparationTargetRoute,runInitialSetup}')( ...Object.values(imports))
}
function actualFunction(source, name) {
  const start = source.indexOf(`export async function ${name}<`)
  assert.ok(start >= 0, `native function missing: ${name}`)
  const end = source.indexOf('\n}\n', start)
  assert.ok(end > start)
  return source.slice(start, end + 3).replace(/^export /gm, '')
}
function nativeTransport(topology, serve) {
  const require = createRequire(path.join(core, 'apps/desktop/package.json'))
  const { transformSync } = require('esbuild')
  const profile = readFileSync(path.join(core, 'apps/desktop/src/sdk/profile-request.ts'), 'utf8')
  const gateway = readFileSync(path.join(core, 'apps/desktop/src/store/gateway.ts'), 'utf8')
  const code = [actualFunction(profile, 'requestPluginProfile'), actualFunction(gateway, 'requestGatewayForProfile'), actualFunction(gateway, 'requestGatewayForAgent')].join('\n')
  const io = {
    window: { hermesDesktop: { getConnectionFor() {} } },
    registryBackendScopeKey: (connection, profile) => `${connection}::${profile}`,
    normKey: value => value,
    isPrimaryRegistryRoute: (_connection, profile) => topology === 'primary' && profile === 'future',
    ridesPrimaryBackend: async (_connection, profile) => profile === 'source' || topology === 'shared',
    requestOnPrimaryGateway: (method, params) => serve(method, params, params.profile),
    gatewayForProfile: async profile => ({ key: profile, scopeProfile: true, release() {}, gateway: { request: (method, params) => serve(method, params, profile) } }),
    g: { secondaries: new Map(), dialFailures: new Map(), activeKey: null },
    traceAgentRoute() {}, rearmSecondary() {}, async openSecondaryForRequest() {},
    createSecondary: (profile, connectionId) => ({ scope: `${connectionId}::${profile}`, retained: true, activeRequests: 0, gateway: { request: (method, params) => serve(method, params, profile) } }),
    drainPendingConnectionRedial: () => false,
    relayRetained: () => false, foregroundPinned: () => false, disposeSecondary() {}
  }
  const js = transformSync(code, { loader: 'ts', format: 'cjs', target: 'es2022' }).code
  return new Function('io', `const {${Object.keys(io).join(',')}}=io;\n${js}\nreturn requestPluginProfile`)(io)
}
const id = value => value.repeat(64)
function readiness(ready = false) {
  return { schema: 1, state: ready ? 'ready' : 'missing', files: ready ? 'complete' : 'missing', python: ready ? 'enabled' : 'not_enabled', base_supported: ready, split_supported: ready, explicit_opt_out: false, managed_selection: false, version: ready ? '0.4.8' : null, identity: id(ready ? '2' : '1'), reason_codes: ready ? [] : ['package_missing'] }
}
for (const topology of ['primary', 'shared', 'isolated']) test(`actual native SDK ${topology} transport binds the selected target, not the source`, { skip: !core && 'set HERMES_DESKTOP_SOURCE_ROOT to the pinned compatible Hermes checkout' }, async () => {
  const api = plugin(), source = { mode: 'local', connectionId: 'local-source', profile: 'source', targetProfile: 'source' }
  const target = { ...source, profile: 'future', targetProfile: 'future' }, routes = [source, target]
  const snapshot = { readiness_context: { schema: 1, base_identity: id('a'), source_profile: 'source', release: { catalog_name: 'model-router', ref: 'b'.repeat(40), version: '0.4.8' } }, profiles: [{ name: 'source', readiness: readiness(true) }, { name: 'future', readiness: readiness() }] }
  const current = structuredClone(snapshot), writes = []
  const requestProfile = nativeTransport(topology, async (method, params, backendProfile) => {
    if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: 'b'.repeat(40), version: '0.4.8' } }
    if (method === 'cli.exec') return { code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(current) }
    assert.equal(method, 'plugins.manage')
    writes.push({ params, backendProfile })
    assert.equal(params.profile, 'future', 'assert FINAL SDK payload, not plugin pre-transport payload')
    assert.equal(backendProfile, 'future', 'shared scope/dedicated backend must bind the selected target')
    current.profiles[1].readiness = readiness(true)
    return { ok: true, enabled: true }
  })
  const values = new Map(), storage = { get: (k, fallback = null) => values.has(k) ? structuredClone(values.get(k)) : fallback, set: (k, value) => values.set(k, structuredClone(value)) }
  const reply = await api.runProfilePreparation({ transport: { requestProfile, profileRoutes: async () => routes }, route: source, snapshot, selected: ['future'], scopeKey: 'owned', isCurrent: () => true, confirmed: true, storage })
  assert.deepEqual(reply.outcomes.map(row => row.state), ['observed_ready'])
  assert.equal(writes.length, 1)
  assert.equal(current.profiles[0].readiness.identity, snapshot.profiles[0].readiness.identity)
  assert.equal(api.selectPreparationTargetRoute([{ ...target, targetProfile: 'different-backend' }, source], source, 'future'), null)
})

for (const topology of ['primary', 'shared', 'isolated']) test(`actual SDK ${topology} initial enable and backend selection retain distinct owners`, { skip: !core && 'set HERMES_DESKTOP_SOURCE_ROOT' }, async () => {
  const api = plugin(), source = { mode: 'local', connectionId: 'local-source', profile: 'source', targetProfile: 'source' }
  const target = { ...source, profile: 'future', targetProfile: 'future' }
  const complete = { schema: 1, default_backend: 'model-router-auto', action: 'complete', eligible: false, backend_unset: false, digest: id('a'), intent_digest: id('b'), reason_codes: [] }
  const snapshot = { revision: 0, readiness_context: { schema: 1, base_identity: id('a'), source_profile: 'source', release: null }, profiles: [
    { name: 'source', readiness: { ...readiness(true), version: '0.6.0' }, initial_setup: complete, native_delegation: { backend: 'model-router' } },
    { name: 'future', readiness: { ...readiness(true), state: 'disabled', python: 'not_enabled', version: '0.6.0' }, initial_setup: { ...complete, action: 'enable', eligible: true, backend_unset: true, digest: id('c') }, native_delegation: { backend: 'default' } }
  ] }
  const current = structuredClone(snapshot), writes = []
  const requestProfile = nativeTransport(topology, async (method, params, backendProfile) => {
    if (method === 'plugins.manage') {
      assert.equal(params.action, 'toggle'); assert.equal(params.profile, 'future'); assert.equal(backendProfile, 'future')
      writes.push('enable-future'); current.profiles[1].readiness = { ...readiness(true), version: '0.6.0' }
      current.profiles[1].initial_setup.action = 'select_backend'; current.profiles[1].initial_setup.digest = id('d')
      return { ok: true }
    }
    assert.equal(method, 'cli.exec'); assert.equal(params.profile, 'source'); assert.equal(backendProfile, 'source')
    const operation = params.argv[params.argv.indexOf('model-router')+1], body = JSON.parse(params.argv.at(-1))
    let reply
    if (operation === 'status') reply = structuredClone(current)
    else if (operation === 'initial-setup-preview') {
      assert.equal(body.updates[0].profile, 'future')
      reply = { plan_id: 'a'.repeat(32), default_backend: 'model-router-auto', changes: [{ profile: 'future', field: 'delegation.backend', after: 'model-router-auto' }] }
    } else {
      assert.equal(operation, 'apply'); writes.push('backend-future')
      current.profiles[1].initial_setup = { ...complete }; current.profiles[1].native_delegation.backend = 'model-router-auto'
      reply = { status: 'applied', plan_id: body.plan_id, applied: [{ profile: 'future', key: 'delegation.backend' }], remaining: [] }
    }
    return { code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(reply) }
  })
  const values = new Map(), storage = { get: (key, fallback=null) => values.has(key) ? structuredClone(values.get(key)) : fallback, set: (key,value) => values.set(key,structuredClone(value)) }
  const result = await api.runInitialSetup({ transport: { requestProfile, profileRoutes: async () => [source,target] }, snapshot, selected: ['future'],
    scopeKey: 'owned', connectionId: 'local-source', activeProfile: 'source', storage, isCurrent: () => true })
  assert.deepEqual(writes, ['enable-future','backend-future']); assert.equal(result.outcomes[0].state, 'complete')
})
