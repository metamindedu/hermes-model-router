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
function harness(options = {}) {
  const pluginContext = { storage: options.storage || null }
  let data = fixture(), cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = [], cleanups = new Map()
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
      hooks[index] = deps; effects.push(() => {
        cleanups.get(index)?.()
        const cleanup = fn()
        if (typeof cleanup === 'function') cleanups.set(index, cleanup)
        else cleanups.delete(index)
      })
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
    .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const moduleApi = new Function(...Object.keys(imports), `${executable}\nreturn { RouterPage, pluginDefinition }`)(...Object.values(imports))
  const RouterPage = moduleApi.RouterPage
  moduleApi.pluginDefinition.register({ ...pluginContext, registerSettingsPage() {}, registerMany() {} })
  const render = () => {
    for (let attempt = 0; attempt < 20; attempt++) {
      dirty = false; cursor = 0; tree = RouterPage({ ctx: pluginContext })
      for (const effect of effects.splice(0)) effect()
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  const find = predicate => { const node = [...walk(tree)].find(predicate); assert.ok(node, 'Control not found'); return node }
  const byId = id => find(node => node.props?.id === id)
  const flush = async () => { for (let at = 0; at < 20; at++) await Promise.resolve(); render() }
  const click = id => { const node = byId(id); assert.ok(!node.props.disabled); node.props.onClick(); render() }
  const button = label => find(node => node.type === 'Button' && text(node).includes(label))
  const clickLabel = label => { const node = button(label); assert.ok(!node.props.disabled); node.props.onClick(); render() }
  const selected = prefix => [...walk(tree)].filter(node => node.type === 'Checkbox' && node.props.id?.startsWith(prefix) && node.props.checked === true)
    .map(node => node.props.id.slice(prefix.length)).sort()
  const selectProfile = name => {
    find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'profile-select')).props.onValueChange(name); render()
  }
  render()
  return { calls, state, host, render, byId, button, click, clickLabel, selected, selectProfile, flush,
    unmount() { for (const cleanup of cleanups.values()) cleanup(); cleanups.clear() },
    setResponder(fn) { responder = fn }, setRefetcher(fn) { refetcher = fn }, setData(next) { data = next }, data: () => data,
    check(id, value) { byId(id).props.onCheckedChange(value); render() },
    input(id, value) { byId(id).props.onChange({ target: { value } }); render() } }
}

const setupReadiness = (state = 'missing') => ({ schema: 1, state, files: state === 'missing' ? 'missing' : 'complete', python: state === 'ready' ? 'enabled' : 'not_enabled', base_supported: state === 'ready', split_supported: state === 'ready', explicit_opt_out: false, managed_selection: false, version: state === 'ready' ? '0.4.8' : null, identity: (state === 'ready' ? '2' : '1').repeat(64), reason_codes: state === 'missing' ? ['package_missing'] : [] })
const setupFixture = () => ({ ...fixture(), readiness_context: { schema: 1, base_identity: 'a'.repeat(64), source_profile: 'claire', release: { catalog_name: 'model-router', version: '0.4.8', ref: 'b'.repeat(40) } }, profiles: fixture().profiles.map(row => ({ ...row, readiness: setupReadiness('ready') })).concat([{ ...structuredClone(fixture().profiles[2]), name: 'future', readiness: setupReadiness() }]) })
function setupStorage() {
  const values = new Map()
  return { get(key, fallback = null) { return values.has(key) ? structuredClone(values.get(key)) : fallback }, set(key, value) { values.set(key, structuredClone(value)) } }
}

test('readiness-only refresh preserves dirty model/route drafts and manual or empty copy selections', async () => {
  const h = harness()
  h.input('model-main-model', 'keep-my-unsaved-model')
  h.input('heavy-custom-model', 'keep-my-unsaved-heavy')
  h.click('model-target-none'); h.check('model-target-other', true)
  h.click('routing-target-none')
  h.setResponder(operation => { assert.equal(operation, 'status'); return setupFixture() })
  h.click('prepare-refresh'); await h.flush()
  assert.equal(h.byId('model-main-model').props.value, 'keep-my-unsaved-model')
  assert.equal(h.byId('heavy-custom-model').props.value, 'keep-my-unsaved-heavy')
  assert.deepEqual(h.selected('model-target-'), ['other'])
  assert.deepEqual(h.selected('routing-target-'), [])
  assert.deepEqual(h.selected('prepare-profile-'), [])
  assert.ok(h.byId('prepare-profile-future'))
  assert.deepEqual(h.calls.map(call => call.operation), ['status'])
  assert.equal(h.data().profiles.some(row => row.name === 'future'), false, 'readiness refresh must not rebase model settings')
})

test('readiness refresh synchronously locks a retained settings-save callback until its read finishes', async () => {
  const h = harness(); h.input('model-main-model', 'retain-draft')
  const staleSave = h.byId('global-save').props.onClick
  let resolveStatus
  h.setResponder(() => new Promise(resolve => { resolveStatus = resolve }))
  h.click('prepare-refresh'); staleSave(); h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.deepEqual(h.calls.map(call => call.operation), ['status'])
  resolveStatus(setupFixture()); await h.flush()
  assert.equal(h.byId('model-main-model').props.value, 'retain-draft')
  assert.equal(h.byId('global-save').props.disabled, false)
})

test('real preparation controls make one explicit native install and preserve dirty settings until explicit reload', async () => {
  const h = harness({ storage: setupStorage() }), snapshot = setupFixture(), nativeView = structuredClone(snapshot)
  h.setData(snapshot); h.render()
  h.input('model-main-model', 'unsaved-model-before-setup')
  h.click('model-target-none'); h.check('model-target-other', true); h.click('routing-target-none')
  const route = { mode: 'local', primary: true, connectionId: 'local', profile: 'claire', targetProfile: 'claire' }
  const writes = [], nativeCalls = []
  h.host.profileRoutes = async () => { nativeCalls.push('profileRoutes'); return [route, { ...route, primary: undefined, profile: 'future', targetProfile: 'future' }] }
  h.host.requestProfile = async (actualRoute, method, params) => {
    nativeCalls.push(method)
    if (method === 'plugins.manage') {
      assert.equal(actualRoute.profile, params.profile)
      assert.equal(actualRoute.targetProfile, params.profile)
    } else assert.deepEqual(actualRoute, route)
    if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: 'b'.repeat(40), subdir: '' } }
    if (method === 'cli.exec') return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(nativeView)}\n` }
    assert.equal(method, 'plugins.manage'); writes.push(params)
    nativeView.profiles.find(row => row.name === 'future').readiness = setupReadiness('ready')
    return { ok: true, enabled: true }
  }
  assert.deepEqual(h.selected('prepare-profile-'), [])
  h.check('prepare-profile-future', true)
  assert.equal(h.byId('prepare-run').props.disabled, true)
  h.check('prepare-consent', true); h.click('prepare-run'); await h.flush(); await h.flush()
  assert.equal(writes.length, 1, `native calls: ${nativeCalls.join(', ')}; preparation view: ${text(h.byId('profile-preparation'))}`); assert.equal(writes[0].profile, 'future'); assert.equal(writes[0].force, false)
  assert.equal(h.byId('model-main-model').props.value, 'unsaved-model-before-setup')
  assert.deepEqual(h.selected('model-target-'), ['other']); assert.deepEqual(h.selected('routing-target-'), [])
  assert.equal(h.calls.some(call => ['preview', 'apply'].includes(call.operation)), false)
  assert.equal(h.byId('models-save').props.disabled, true)
})

test('unmount during route lookup cancels before any native preparation RPC', async () => {
  const h = harness({ storage: setupStorage() }); h.setData(setupFixture()); h.render()
  let releaseRoutes; const calls = []
  h.host.profileRoutes = () => new Promise(resolve => { releaseRoutes = resolve })
  h.host.requestProfile = async (_route, method) => { calls.push(method); throw new Error('must not dispatch') }
  h.check('prepare-profile-future', true); h.check('prepare-consent', true); h.click('prepare-run')
  h.unmount(); releaseRoutes([{mode:'local',primary:true,connectionId:'local',profile:'claire',targetProfile:'claire'}])
  for (let at=0;at<40;at++) await Promise.resolve()
  assert.deepEqual(calls, [])
})

test('unmount stops the queue and a remounted page stays locked until owner-scoped full reload', async () => {
  const storage = setupStorage(), h = harness({storage}), snapshot=setupFixture()
  snapshot.profiles.push({...structuredClone(snapshot.profiles.at(-1)),name:'second-future'})
  const nativeView=structuredClone(snapshot), route={mode:'local',primary:true,connectionId:'local',profile:'claire',targetProfile:'claire'}, writes=[]
  let finishInstall
  h.setData(snapshot);h.render();h.host.profileRoutes=async()=>[route,...['future','second-future'].map(name=>({...route,primary:undefined,profile:name,targetProfile:name}))]
  h.host.requestProfile=async(_route,method,params)=>{
    if(method==='plugins.catalog.lookup') return {status:'found',entry:{name:'model-router',repo:'https://github.com/metamindedu/hermes-model-router',sha:'b'.repeat(40),subdir:''}}
    if(method==='cli.exec') return {code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify(nativeView)}
    assert.equal(method,'plugins.manage');writes.push(params)
    return new Promise(resolve=>{finishInstall=()=>{nativeView.profiles.find(row=>row.name===params.profile).readiness=setupReadiness('ready');resolve({ok:true})}})
  }
  h.check('prepare-profile-future',true);h.check('prepare-profile-second-future',true);h.check('prepare-consent',true);h.click('prepare-run');await h.flush()
  assert.equal(writes.length,1)
  h.unmount();finishInstall();for(let at=0;at<50;at++) await Promise.resolve()
  assert.equal(writes.length,1,'unmount must never queue the second target')
  assert.equal(storage.get('profile-preparation-safety-v1').pending.settled,true)
  const remounted=harness({storage});remounted.setData(nativeView);remounted.render()
  assert.equal(remounted.byId('models-save').props.disabled,true,'a new page must not clear the mutation fence')
  remounted.setRefetcher(async()=>({data:nativeView}))
  remounted.clickLabel('상태 새로고침');await remounted.flush()
  assert.equal(storage.get('profile-preparation-safety-v1').pending,null)
  assert.equal(remounted.byId('models-save').props.disabled,false)
})

for (const phase of ['routes', 'initial-status', 'final-status']) {
  for (const stop of ['cancel', 'unmount', 'leave-and-return']) test(`${stop} during ${phase} prevents later preparation writes`, async () => {
    const h = harness({ storage: setupStorage() }), snapshot = setupFixture()
    h.setData(snapshot); h.render()
    const source = { mode: 'local', primary: true, connectionId: 'local', profile: 'claire', targetProfile: 'claire' }
    const routes = [source, { ...source, primary: undefined, profile: 'future', targetProfile: 'future' }]
    let release, reads = 0, routeReads = 0; const writes = []
    h.host.profileRoutes = () => {
      routeReads++
      if (phase === 'routes' && routeReads === 1) return new Promise(resolve => { release = () => resolve(routes) })
      return Promise.resolve(routes)
    }
    h.host.requestProfile = async (_route, method, params) => {
      if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: 'b'.repeat(40), subdir: '' } }
      if (method === 'cli.exec') {
        reads++
        if ((phase === 'initial-status' && reads === 1) || (phase === 'final-status' && reads === 2)) return new Promise(resolve => { release = () => resolve({ code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(snapshot) }) })
        return { code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(snapshot) }
      }
      writes.push(params); return { ok: true }
    }
    h.check('prepare-profile-future', true); h.check('prepare-consent', true); h.click('prepare-run'); await h.flush()
    assert.equal(typeof release, 'function')
    if (stop === 'cancel') h.click('prepare-cancel')
    else if (stop === 'unmount') h.unmount()
    else {
      h.host.state.profile.value = 'other'; h.render()
      h.host.state.profile.value = 'claire'; h.render()
    }
    release(); for (let i = 0; i < 50; i++) await Promise.resolve()
    assert.deepEqual(writes, [])
    assert.equal(h.calls.some(call => ['preview', 'apply'].includes(call.operation)), false)
  })
}

test('editing Heavy with all profiles checked saves the exact bulk routing targets', async () => {
  const h = harness()
  h.check('routing-profile-default', true)
  h.check('routing-profile-other', true)
  h.input('heavy-custom-model', 'new-bulk-heavy')
  h.click('global-save'); await h.flush()
  const payload = h.calls.find(c => c.operation === 'preview').body
  assert.deepEqual([...payload.routing_targets].sort(), ['claire', 'default', 'other'])
  assert.equal(payload.routing.heavy.custom.model, 'new-bulk-heavy')
})

test('model-only save and enable-only save do not copy primary routing', async () => {
  const h = harness()
  h.check('routing-profile-other', true)
  h.input('model-main-model', 'new-main-only')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_targets, [])
})

test('routing copy targets are independent, explicit, and source is not implicit', async () => {
  const h = harness()
  h.click('routing-target-none')
  h.check('routing-target-other', true)
  assert.deepEqual(h.selected('routing-profile-'), ['claire'])
  h.click('model-target-none')
  h.click('global-save'); await h.flush()
  const payload = h.calls.find(c => c.operation === 'preview').body
  assert.deepEqual(payload.routing_targets, ['other'])
  assert.deepEqual(payload.model_targets, [])
  assert.deepEqual(payload.routing_profiles, ['claire'])
})

test('empty routing target blocks an edited route instead of falling back to source', async () => {
  const h = harness()
  h.click('routing-target-none')
  h.input('heavy-custom-model', 'must-not-save-to-source')
  h.click('global-save'); await h.flush()
  assert.equal(h.calls.length, 0)
  assert.equal(h.byId('global-save').props.disabled, false)
})

test('routing target selection persists but copy intent clears on source change and refresh', async () => {
  const h = harness()
  h.click('routing-target-none')
  h.check('routing-target-other', true)
  h.selectProfile('default')
  assert.deepEqual(h.selected('routing-target-'), ['other'])
  h.input('model-main-model', 'new-main')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_targets, [])
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  h.click('routing-target-all')
  h.click('global-save'); await h.flush()
  assert.deepEqual([...h.calls.filter(c => c.operation === 'preview').at(-1).body.routing_targets].sort(), ['claire', 'default', 'other'])
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  h.input('model-main-model', 'next-main')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'preview').at(-1).body.routing_targets, [])
})

test('reverting a primary edit cancels implicit copy and an empty unedited scope allows model-only save', async () => {
  const h = harness()
  h.input('heavy-custom-model', 'temporary-edit')
  h.input('heavy-custom-model', 'independent-heavy')
  h.click('routing-target-none')
  h.input('model-main-model', 'model-only')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_targets, [])
})

test('routing source-only target never widens when changing the loaded profile', async () => {
  const h = harness()
  h.click('routing-target-source')
  assert.deepEqual(h.selected('routing-target-'), ['claire'])
  h.selectProfile('other')
  assert.deepEqual(h.selected('routing-target-'), ['claire'])
  h.input('heavy-custom-model', 'other-route-copy')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_targets, ['claire'])
})

test('background status refresh cannot promote old routing copy intent to a newer revision', async () => {
  const h = harness()
  h.click('routing-target-all')
  const staleSave = h.byId('global-save').props.onClick
  const newer = structuredClone(h.data())
  newer.revision++
  newer.profiles.find(r => r.name === 'other').routing.heavy.custom.model = 'external-new-route'
  h.setData(newer); h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  staleSave(); await h.flush()
  assert.equal(h.calls.length, 0)
  assert.deepEqual(h.selected('routing-target-'), ['claire', 'default', 'other'])
  h.clickLabel('상태 새로고침'); await h.flush()
  h.click('global-save'); await h.flush()
  const payload = h.calls.find(c => c.operation === 'preview').body
  assert.equal(payload.expected_revision, 8)
  assert.deepEqual(payload.routing_targets, [])
})

test('background revision change blocks edited routing without discarding draft or rebasing it', async () => {
  const h = harness()
  h.input('heavy-custom-model', 'unsaved-old-edit')
  h.setData({ ...structuredClone(h.data()), revision: 9 }); h.render()
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.equal(h.byId('heavy-custom-model').props.value, 'unsaved-old-edit')
  assert.equal(h.calls.length, 0)
})

test('status refresh during pending validation does not change captured targets/revision or duplicate apply', async () => {
  const h = harness()
  let release
  h.setResponder(operation => operation === 'preview'
    ? new Promise(resolve => { release = resolve }) : { status: 'applied', revision: 8 })
  h.input('heavy-custom-model', 'captured-route')
  h.click('global-save'); await h.flush()
  const captured = structuredClone(h.calls[0].body)
  h.setData({ ...structuredClone(h.data()), revision: 8 }); h.render()
  release({ plan_id: 'captured-plan', changes: [] }); await h.flush()
  assert.deepEqual(h.calls[0].body, captured)
  assert.equal(captured.expected_revision, 7)
  assert.deepEqual([...captured.routing_targets].sort(), ['claire', 'default', 'other'])
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
})

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
  h.click('global-save'); await h.flush()
  const payload = h.calls.find(c => c.operation === 'preview').body
  assert.deepEqual(payload.routing, routing)
  assert.deepEqual(payload.routing_profiles, ['claire'])
  assert.deepEqual([...payload.model_targets].sort(), ['claire', 'default', 'other'])
  assert.equal(payload.models.delegation.reasoning, 'max')
  assert.equal(payload.models.compression.reasoning, 'medium')
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  h.click('preset-openai')
  for (const [role, fields] of Object.entries(models)) for (const [field, value] of Object.entries(fields))
    assert.equal(h.byId(`model-${role}-${field}`).props.value, value)
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
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

test('single save validates then applies once without a preview or confirmation control', async () => {
  const h = harness()
  h.click('preset-non-openai')
  assert.equal(h.calls.length, 0)
  assert.throws(() => h.byId('confirm-preview'))
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.map(c => c.operation), ['preview', 'apply'])
  assert.deepEqual(h.calls[1].body, { plan_id: 'test-plan' })
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, false)
})

test('save locks editing and duplicate clicks even while validation is pending', async () => {
  const h = harness(); let finish
  h.setResponder(op => op === 'preview' ? new Promise(r => { finish = r }) : { status: 'applied' })
  const click = h.byId('global-save').props.onClick
  click(); h.render(); click(); h.render()
  assert.equal(h.calls.length, 1)
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
  assert.equal(h.byId('model-main-model').props.disabled, true)
  assert.equal(h.button('상태 새로고침').props.disabled, true)
  finish({ plan_id: 'only-once', changes: [] }); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'apply').map(c => c.body), [{ plan_id: 'only-once' }])
})

test('validation rejection unlocks safely and never applies', async () => {
  const h = harness()
  h.setResponder(() => { throw new Error('validation timeout') })
  h.click('global-save'); await h.flush()
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 0)
  assert.equal(h.byId('preset-non-openai').props.disabled, false)
  assert.equal(h.byId('global-save').props.disabled, false)
})

test('scope change during validation cancels before writes and old failure cannot lock a new save', async () => {
  const h = harness(); let oldReject
  h.setResponder(() => new Promise((r, reject) => { oldReject = reject }))
  h.click('global-save')
  h.state.connectionId.value = 'new-connection'; h.render()
  let newResolve
  h.setResponder(op => op === 'preview' ? { plan_id: 'new-plan', changes: [] } : new Promise(r => { newResolve = r }))
  h.click('global-save'); await h.flush()
  oldReject(new Error('old validation timed out')); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
  newResolve({ status: 'applied' }); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'apply').map(c => c.body), [{ plan_id: 'new-plan' }])
  assert.ok(!JSON.stringify(h.data()).includes('old validation'))
})

test('late validation success after scope change cannot apply its token', async () => {
  const h = harness(); let finish
  h.setResponder(() => new Promise(r => { finish = r }))
  h.click('global-save')
  h.state.connectionId.value = 'other-source'; h.render()
  finish({ plan_id: 'obsolete', changes: [] }); await h.flush()
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 0)
  assert.equal(h.byId('global-save').props.disabled, false)
})

test('a stale save callback is invalidated by refresh before making any request', async () => {
  const h = harness()
  const stale = h.byId('global-save').props.onClick
  h.clickLabel('상태 새로고침'); await h.flush()
  stale(); await h.flush()
  assert.equal(h.calls.length, 0)
})

test('scope change during apply locks until original scope is reloaded', async () => {
  const h = harness(); let finish
  h.setResponder(op => op === 'preview' ? { plan_id: 'pending-apply', changes: [] } : new Promise(r => { finish = r }))
  h.click('global-save'); await h.flush()
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
  h.state.connectionId.value = 'other-connection'; h.render()
  finish({ status: 'applied' }); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, true)
  h.state.connectionId.value = 'local'; h.render()
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('preset-non-openai').props.disabled, false)
})

test('refresh failure with cached data does not unlock an ambiguous apply', async () => {
  const h = harness()
  h.setResponder(operation => {
    if (operation === 'apply') throw new Error('unknown transport outcome')
    return { plan_id: 'test-plan', changes: [{ profile: 'claire', field: 'models' }], warnings: [] }
  })
  h.click('global-save'); await h.flush()
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
