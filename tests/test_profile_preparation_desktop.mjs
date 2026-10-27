import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const exported = ['validProfileReadiness', 'preparationTargetEligible', 'profileReadinessText', 'profilePreparationCommands', 'selectPreparationRoute', 'selectPreparationTargetRoute', 'readProfilePreparationStatus', 'runProfilePreparation', 'cancelProfilePreparation', 'acknowledgeProfilePreparation', 'profilePreparationLocked', 'profilePreparationReloadBlocked', 'finishProfilePreparationReload']
function load() {
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of match[1].split(',').map(x => x.trim()).filter(Boolean)) imports[name] = name
  const executable = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '').replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function(...Object.keys(imports), `${executable}\nreturn { plugin: pluginDefinition, ${exported.map(name => `${name}: typeof ${name} === 'function' ? ${name} : null`).join(',')} }`)(...Object.values(imports))
}
const id = value => value.repeat(64)
function readiness(state = 'missing', extra = {}) {
  return { schema: 1, state, files: state === 'missing' ? 'missing' : 'complete', python: state === 'ready' ? 'enabled' : 'not_enabled', base_supported: state !== 'missing', split_supported: state !== 'missing', explicit_opt_out: false, managed_selection: false, version: state === 'missing' ? null : '0.4.8', identity: id('1'), reason_codes: state === 'missing' ? ['package_missing'] : [], ...extra }
}
const fixture = () => ({ revision: 1, readiness_context: { schema: 1, base_identity: id('a'), source_profile: 'default', release: { catalog_name: 'model-router', ref: 'b'.repeat(40), version: '0.4.8' } }, profiles: [{ name: 'default', readiness: readiness('ready') }, { name: 'new-profile', readiness: readiness() }, { name: 'second', readiness: readiness('missing', { identity: id('2') }) }] })
const route = { mode: 'local', connectionId: 'local-one', primary: true, profile: 'default', targetProfile: 'default' }
function memoryStorage() {
  const values = new Map()
  return { get(key, fallback = null) { return values.has(key) ? structuredClone(values.get(key)) : fallback }, set(key, value) { values.set(key, structuredClone(value)) } }
}
function harness(options = {}) {
  const api = load(); assert.equal(typeof api.runProfilePreparation, 'function', 'native preparation helper is missing')
  const storage = memoryStorage(); api.plugin.register({ storage, registerSettingsPage() {}, registerMany() {} })
  const snapshot = fixture(), current = structuredClone(snapshot), calls = []
  let live = true
  const transport = { async profileRoutes() { return [route, ...['new-profile', 'second'].map(name => ({ ...route, primary: undefined, profile: name, targetProfile: name }))] }, async requestProfile(actualRoute, method, params, timeout) {
    calls.push({ route: actualRoute, method, params: structuredClone(params), timeout })
    if (method === 'plugins.manage') {
      assert.equal(actualRoute.connectionId, route.connectionId)
      assert.equal(actualRoute.profile, params.profile)
      assert.equal(actualRoute.targetProfile, params.profile)
    } else assert.deepEqual(actualRoute, route)
    if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: options.movedPin ? 'c'.repeat(40) : snapshot.readiness_context.release.ref, version: snapshot.readiness_context.release.version, subdir: '' } }
    if (method === 'cli.exec') {
      assert.deepEqual(params.argv, ['--profile', 'default', 'model-router', 'status', '--body', '{}'])
      if (options.foreignBase) current.readiness_context.base_identity = id('d')
      return { code: 0, blocked: false, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(current) + '\n' }
    }
    assert.equal(method, 'plugins.manage')
    assert.deepEqual(Object.keys(params).sort(), ['action', 'catalog_name', 'enable', 'force', 'profile', 'ref'])
    assert.equal(params.action, 'install'); assert.equal(params.catalog_name, 'model-router'); assert.equal(params.force, false); assert.equal(params.enable, true)
    assert.equal(params.ref, snapshot.readiness_context.release.ref)
    if (options.failure) throw Object.assign(new Error('private scanner output must not surface'), options.failure)
    current.profiles.find(row => row.name === params.profile).readiness = readiness('ready', { identity: id('3') })
    if (options.scopeSwitch) live = false
    return { ok: true, enabled: true, activation: { deferred: { tools: ['coding_route'] } } }
  } }
  const run = (extra = {}) => api.runProfilePreparation({ transport, route, snapshot, selected: ['new-profile'], scopeKey: 'owned-scope', isCurrent: () => live, confirmed: true, storage, ...extra })
  return { api, storage, snapshot, current, calls, run, transport }
}

test('readiness is explicit and malformed/legacy DTO never grants preparation', () => {
  const api = load(); assert.equal(typeof api.validProfileReadiness, 'function')
  assert.equal(api.validProfileReadiness(readiness()), true)
  for (const value of [null, {}, { ...readiness(), schema: 2 }, { ...readiness(), python: 'probably-enabled' }, { ...readiness(), identity: '../path' }, { ...readiness(), identity: [id('1')] }, { ...readiness(), version: 'not-a-version' }]) assert.equal(api.validProfileReadiness(value), false)
  assert.equal(api.preparationTargetEligible({ name: 'safe', readiness: readiness() }), true)
  for (const value of [readiness('disabled'), readiness('unsupported'), readiness('missing', { managed_selection: true }), readiness('missing', { reason_codes: ['profile_changed'] })]) assert.equal(api.preparationTargetEligible({ name: 'safe', readiness: value }), false)
  assert.equal(api.preparationTargetEligible({ name: '../escape', readiness: readiness() }), false)
  assert.equal(api.preparationTargetEligible({ name: ['safe'], readiness: readiness() }), false)
})

test('manual commands are fixed native verbs with validated inventory names only', () => {
  const api = load(); assert.equal(typeof api.profilePreparationCommands, 'function')
  const rows = fixture().profiles.concat([{ name: 'disabled', readiness: readiness('disabled') }, { name: 'bad;command', readiness: readiness() }])
  assert.deepEqual(api.profilePreparationCommands(rows, ['new-profile', 'disabled', 'bad;command', 'not-in-inventory']), ['hermes --profile new-profile plugins install model-router', 'hermes --profile disabled plugins enable model-router'])
})

test('source routing requires an unambiguous local credential-free descriptor', () => {
  const api = load(); assert.equal(typeof api.selectPreparationRoute, 'function')
  assert.deepEqual(api.selectPreparationRoute([route], null, 'default'), route)
  assert.deepEqual(api.selectPreparationRoute([route], 'local-one', 'default'), route)
  assert.equal(api.selectPreparationRoute([{ ...route, mode: 'remote' }], null, 'default'), null)
  assert.equal(api.selectPreparationRoute([route, { ...route, connectionId: 'other-local' }], null, 'default'), null)
  assert.equal(api.selectPreparationRoute([route], 'foreign', 'default'), null)
})

test('explicit native preparation reads back the exact target and never follows arbitrary sources', async () => {
  const h = harness(); const result = await h.run()
  assert.deepEqual(result.outcomes.map(item => item.state), ['observed_ready'])
  assert.equal(result.changed, true); assert.equal(result.unknown, false)
  const writes = h.calls.filter(call => call.method === 'plugins.manage')
  assert.equal(writes.length, 1); assert.equal(writes[0].params.profile, 'new-profile'); assert.equal(writes[0].timeout, 120000)
  assert.equal(h.api.profilePreparationLocked(), true)
  assert.equal(h.api.profilePreparationReloadBlocked('foreign-scope'), true)
  assert.equal(h.api.profilePreparationReloadBlocked('owned-scope'), false)
  assert.equal(h.api.finishProfilePreparationReload({base_identity:id('d')}, 'owned-scope', h.storage), false)
  assert.equal(h.api.finishProfilePreparationReload(h.snapshot.readiness_context, 'owned-scope', h.storage), true)
  assert.equal(h.api.profilePreparationLocked(), false)
})

test('no consent, empty/duplicate/arbitrary target, ready or disabled package causes zero native writes', async () => {
  for (const args of [{ confirmed: false }, { selected: [] }, { selected: ['new-profile', 'new-profile'] }, { selected: ['../escape'] }, { selected: ['default'] }]) {
    const h = harness(); await assert.rejects(h.run(args)); assert.equal(h.calls.length, 0)
  }
  const h = harness(); h.snapshot.profiles[1].readiness = readiness('disabled')
  await assert.rejects(h.run()); assert.equal(h.calls.length, 0)
})

test('catalog pin change and foreign root fail before native mutation', async () => {
  for (const options of [{ movedPin: true }, { foreignBase: true }]) {
    const h = harness(options); const result = await h.run()
    assert.equal(result.manualRequired, true); assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 0)
  }
})

test('double-click is synchronously refused before the first native request completes', async () => {
  const h = harness(); const first = h.run(); await assert.rejects(h.run(), /preparation_busy/); await first
  assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
})

test('scope switch stops queuing after the already-issued native operation without a rollback', async () => {
  const h = harness({ scopeSwitch: true }); const result = await h.run({ selected: ['new-profile', 'second'] })
  assert.deepEqual(result.outcomes.map(item => item.state), ['observed_ready', 'not_started'])
  assert.equal(result.cancelled, true); assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
})

test('unknown write survives remount and is never automatically retried even after manual acknowledgement', async () => {
  const h = harness({ failure: {} }); const result = await h.run()
  assert.equal(result.unknown, true); assert.equal(result.outcomes[0].state, 'unknown'); assert.equal(h.api.profilePreparationLocked(), true)
  await assert.rejects(h.run()); assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
  const remounted = load()
  remounted.plugin.register({ storage: h.storage, registerSettingsPage() {}, registerMany() {} })
  assert.equal(remounted.profilePreparationLocked(), true, 'persisted unknown outcome must survive a new module instance')
  assert.equal(h.api.acknowledgeProfilePreparation(h.storage, id('a'), 'different-scope', true), false)
  assert.equal(h.api.acknowledgeProfilePreparation(h.storage, id('a'), 'owned-scope', true), true)
  await assert.rejects(h.run()); assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
})

test('native refusal is shown as manual review, not force/yes retry or raw scanner output', async () => {
  const h = harness({ failure: { code: 5026 } }); const result = await h.run()
  assert.equal(result.unknown, false); assert.equal(result.outcomes[0].state, 'manual_required')
  assert.equal(JSON.stringify(result).includes('private scanner output'), false)
  assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
})

test('malformed persisted safety state cannot silently unlock preparation or settings writes', () => {
  const api = load()
  api.plugin.register({ storage: { get() { return { schema: 1, blocked: 'invalid' } }, set() {} }, registerSettingsPage() {}, registerMany() {} })
  assert.equal(api.profilePreparationLocked(), true)
})

test('failed safety persistence prevents dispatch', async () => {
  const h = harness(); const broken = { get() { return null }, set() { throw new Error('storage unavailable') } }
  const result = await h.run({ storage: broken })
  assert.equal(result.manualRequired, true); assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 0)
})

test('mutation route must be an exact unambiguous target on the proven local source', () => {
  const api = load(), target = { ...route, primary: undefined, profile: 'new-profile', targetProfile: 'new-profile' }
  assert.equal(typeof api.selectPreparationTargetRoute, 'function')
  assert.deepEqual(api.selectPreparationTargetRoute([route, target], route, 'new-profile'), target)
  for (const routes of [[route], [target, target], [{ ...target, connectionId: 'foreign' }], [{ ...target, mode: 'remote' }], [{ ...target, targetProfile: 'alias-backend' }]]) assert.equal(api.selectPreparationTargetRoute(routes, route, 'new-profile'), null)
})

for (const reason of ['cancel', 'scope']) test(`${reason} during final target status prevents native dispatch`, async () => {
  const h = harness(); let release, current = true, held = false
  const original = h.transport.requestProfile
  h.transport.requestProfile = (r, method, params, timeout) => {
    if (method === 'cli.exec' && !held) {
      held = true
      return new Promise(resolve => { release = () => resolve({ code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(h.current) }) })
    }
    return original(r, method, params, timeout)
  }
  const promise = h.run({ isCurrent: () => current })
  for (let i = 0; i < 20 && !release; i++) await Promise.resolve()
  assert.equal(typeof release, 'function')
  if (reason === 'cancel') h.api.cancelProfilePreparation(); else current = false
  release(); const result = await promise
  assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 0)
  assert.equal(result.outcomes[0].state, 'not_started')
  assert.equal(h.api.profilePreparationLocked(), false)
})

test('cancel during second preflight retains the first mutation fence without starting the second', async () => {
  const h = harness(); let release, reads = 0
  const original = h.transport.requestProfile
  h.transport.requestProfile = (r, method, params, timeout) => {
    if (method === 'cli.exec' && ++reads === 3) return new Promise(resolve => { release = () => resolve({ code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(h.current) }) })
    return original(r, method, params, timeout)
  }
  const promise = h.run({ selected: ['new-profile', 'second'] })
  for (let i = 0; i < 50 && !release; i++) await Promise.resolve()
  assert.equal(typeof release, 'function'); h.api.cancelProfilePreparation(); release()
  const result = await promise
  assert.deepEqual(result.outcomes.map(row => row.state), ['observed_ready', 'not_started'])
  assert.equal(h.calls.filter(call => call.method === 'plugins.manage').length, 1)
  assert.equal(h.storage.get('profile-preparation-safety-v1').pending.settled, true)
})

test('missing target descriptor is manual-only before any mutation', async () => {
  const h = harness(); h.transport.profileRoutes = async () => [route]
  const result = await h.run()
  assert.equal(result.manualRequired, true)
  assert.equal(h.calls.some(call => call.method === 'plugins.manage'), false)
})
