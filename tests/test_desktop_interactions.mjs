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
const slotIds = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use']
const slotTiers = Object.fromEntries(slotIds.map(id => [id, ['design', 'verify-complex'].includes(id) ? 'heavy' : 'light']))
const offSlots = () => Object.fromEntries(slotIds.map(id => [id, { mode: 'off', chain: [] }]))
// A never-saved slot is shown as what its tier resolves through: Heavy is custom here, Light follows delegation.
const declarations = () => Object.fromEntries(slotIds.map(id => [id, slotTiers[id] === 'heavy'
  ? { follow: 'custom', custom: route('operator', 'independent-heavy', 'high') } : { follow: 'delegation', custom: null }]))
const fixture = () => ({ revision: 7, current_profile: 'claire', recent_apply: null,
  readiness_context: { schema: 1, base_identity: 'd'.repeat(64), source_profile: 'claire', release: null },
  slot_capabilities: { schema: 1, slots: slotIds, tiers: slotTiers, purposes: {}, follows: ['main', 'delegation', 'custom'], blocking_profiles: [] },
  profiles: ['default', 'claire', 'other'].map(name => ({ name, models: structuredClone(models),
    actual_models: structuredClone(models), routing: { ...structuredClone(routing), enabled: name === 'claire' }, drift: [],
    slots: { schema: 1, capable: true, stored: [], declarations: declarations() },
    native_delegation: { schema: 1, supported: true, editable: true, backend: 'default', digest: 'a'.repeat(64),
      policy: { heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } },
      slot_policy: offSlots(), auto_slot_policy: offSlots(), policy_schema: 0, auto_policy_schema: 0, slot_policy_supported: true,
      profile_routes: { profiles: [], default: null }, role_intro_inheritance: { schema: 1, supported: true, code_identity: 'e'.repeat(64), activation: 'new_session_or_supported_rebuild' }, warnings: [] },
    role_intro: { schema: 1, state: 'available', default_description: `Role of ${name}`, default_source: 'profile_metadata', description_auto: false, digest: 'f'.repeat(64) } })) })
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
  const pluginContext = { storage: options.storage || setupStorage() }
  let data = options.data ? structuredClone(options.data) : fixture(), cursor = 0, dirty = false, tree
  const hooks = [], effects = [], calls = [], cleanups = new Map()
  const state = Object.fromEntries(Object.entries({ profile: 'claire', connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  let statusResponder = () => structuredClone(data)
  let responder = operation => operation === 'preview'
    ? { plan_id: 'test-plan', changes: [{ profile: 'claire', field: 'models.main', before: 'before', after: 'after' }], warnings: [] }
    : { status: 'applied', revision: 8 }
  const host = { state, request: async (method, args) => {
    const index = args.argv.indexOf('model-router'), operation = args.argv[index + 1]
    const body = JSON.parse(args.argv.at(-1))
    calls.push({ method, operation, body, profile: args.profile })
    const result = await (operation === 'status' ? statusResponder(body) : responder(operation, body))
    return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(result)}\n` }
  } }
  const gatewayInstance = { request: (method, args) => host.request(method, args) }
  host.getGateway = () => gatewayInstance
  host.profileRoutes = async () => ['default', 'claire', 'other'].map(profile => ({ mode: 'local', connectionId: 'local', profile, targetProfile: profile, primary: profile === 'claire' }))
  host.requestProfile = async (descriptor, method, args) => {
    assert.equal(args.profile, descriptor.profile)
    assert.equal(args.argv[1], descriptor.targetProfile)
    return host.request(method, args)
  }
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
  Object.assign(imports, { DesktopSDK: { Dialog: 'Dialog', DialogContent: 'DialogContent', DialogHeader: 'DialogHeader', DialogTitle: 'DialogTitle', DialogDescription: 'DialogDescription', DialogFooter: 'DialogFooter' }, useState, useRef, useEffect, jsx, jsxs: jsx, host,
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
  const flush = async () => { for (let at = 0; at < 40; at++) await Promise.resolve(); render() }
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
    setResponder(fn) { responder = fn }, setStatusResponder(fn) { statusResponder = fn }, setRefetcher(fn) { refetcher = fn }, setQueryError(value) { query.isError = value }, setData(next) { data = next }, data: () => data,
    check(id, value) { byId(id).props.onCheckedChange(value); render() },
    input(id, value) { byId(id).props.onChange({ target: { value } }); render() },
    selectValue(id) { return find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.value },
    select(id, value) { find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.onValueChange(value); render() } }
}

const setupReadiness = (state = 'missing') => ({ schema: 1, state, files: state === 'missing' ? 'missing' : 'complete', python: state === 'ready' ? 'enabled' : 'not_enabled', base_supported: state === 'ready', split_supported: state === 'ready', explicit_opt_out: false, managed_selection: false, version: state === 'ready' ? '0.4.8' : null, identity: (state === 'ready' ? '2' : '1').repeat(64), reason_codes: state === 'missing' ? ['package_missing'] : [] })
const setupFixture = () => ({ ...fixture(), readiness_context: { schema: 1, base_identity: 'a'.repeat(64), source_profile: 'claire', release: { catalog_name: 'model-router', version: '0.4.8', ref: 'b'.repeat(40) } }, profiles: fixture().profiles.map(row => ({ ...row, readiness: setupReadiness('ready') })).concat([{ ...structuredClone(fixture().profiles[2]), name: 'future', readiness: setupReadiness() }]) })
function setupStorage() {
  const values = new Map()
  return { get(key, fallback = null) { return values.has(key) ? structuredClone(values.get(key)) : fallback }, set(key, value) { values.set(key, structuredClone(value)) } }
}

test('readiness-only refresh preserves dirty model drafts and a manual target selection', async () => {
  const h = harness()
  h.input('model-main-model', 'keep-my-unsaved-model')
  h.click('model-target-none'); h.check('model-target-other', true)
  h.setStatusResponder(() => setupFixture())
  h.click('prepare-refresh'); await h.flush()
  assert.equal(h.byId('model-main-model').props.value, 'keep-my-unsaved-model')
  assert.deepEqual(h.selected('model-target-'), ['other'])
  assert.deepEqual(h.selected('prepare-profile-'), [])
  assert.ok(h.byId('prepare-profile-future'))
  assert.deepEqual(h.calls.map(call => call.operation), ['status'])
  assert.equal(h.data().profiles.some(row => row.name === 'future'), false, 'readiness refresh must not rebase model settings')
})

test('readiness refresh synchronously locks a retained settings-save callback until its read finishes', async () => {
  const h = harness(); h.input('model-main-model', 'retain-draft')
  const staleSave = h.byId('global-save').props.onClick
  let resolveStatus
  h.setStatusResponder(() => new Promise(resolve => { resolveStatus = resolve }))
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
  h.click('model-target-none'); h.check('model-target-other', true)
  const route = { mode: 'local', primary: true, connectionId: 'local', profile: 'claire', targetProfile: 'claire' }
  const writes = [], nativeCalls = []
  h.host.profileRoutes = async () => { nativeCalls.push('profileRoutes'); return [route, { ...route, primary: undefined, profile: 'future', targetProfile: 'future' }] }
  h.host.requestProfile = async (actualRoute, method, params) => {
    nativeCalls.push(method)
    if (method === 'plugins.manage') {
      assert.equal(actualRoute.profile, params.profile)
      assert.equal(actualRoute.targetProfile, params.profile)
    } else assert.deepEqual(actualRoute, route)
    if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: 'b'.repeat(40), version: '0.4.8', subdir: '' } }
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
  assert.deepEqual(h.selected('model-target-'), ['other'])
  assert.equal(h.calls.some(call => ['preview', 'apply'].includes(call.operation)), false)
  assert.equal(h.byId('model-section-save').props.disabled, true)
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
    if(method==='plugins.catalog.lookup') return {status:'found',entry:{name:'model-router',repo:'https://github.com/metamindedu/hermes-model-router',sha:'b'.repeat(40),version:'0.4.8',subdir:''}}
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
  assert.equal(remounted.byId('model-main-model').props.disabled,true,'a new page must not clear the mutation fence')
  remounted.setRefetcher(async()=>({data:nativeView}))
  remounted.clickLabel('상태 새로고침');await remounted.flush()
  assert.equal(storage.get('profile-preparation-safety-v1').pending,null)
  assert.equal(remounted.byId('model-main-model').props.disabled,false)
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
      if (method === 'plugins.catalog.lookup') return { status: 'found', entry: { name: 'model-router', repo: 'https://github.com/metamindedu/hermes-model-router', sha: 'b'.repeat(40), version: '0.4.8', subdir: '' } }
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

test('preset click fills exact BAT models in draft only and does not alter custom routes', async () => {
  const h = harness()
  h.click('preset-non-openai')
  assert.equal(h.byId('model-main-model').props.value, 'mimo-v2.6-pro')
  assert.equal(h.byId('model-main-provider').props.value, 'xiaomi')
  assert.equal(h.selectValue('model-main-reasoning'), 'max')
  assert.equal(h.byId('model-title-model').props.value, 'deepseek-flash')
  assert.equal(h.selectValue('model-title-reasoning'), 'none')
  assert.equal(h.calls.length, 0)
  h.click('global-save'); await h.flush()
  const payload = h.calls.find(c => c.operation === 'preview').body
  const { fallback: _retired, ...routingWithoutFallback } = routing
  assert.deepEqual(payload.routing, { ...routingWithoutFallback, slots: declarations() })
  assert.deepEqual(payload.routing_profiles, ['claire'])
  assert.deepEqual(payload.model_targets, ['claire'])
  assert.deepEqual(payload.routing_targets, [])
  assert.equal(payload.models.delegation.reasoning, 'max')
  assert.equal(payload.models.compression.reasoning, 'medium')
  h.click('preset-openai')
  for (const [role, fields] of Object.entries(models)) for (const [field, value] of Object.entries(fields))
    assert.equal(field === 'reasoning' ? h.selectValue(`model-${role}-reasoning`) : h.byId(`model-${role}-${field}`).props.value, value)
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
})

test('none and explicit subset survive source changes and refresh; a removed hand-picked profile stays until unticked', async () => {
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
  assert.deepEqual(h.selected('model-target-'), ['claire'], 'never dropped by a reload either')
  h.check('model-target-claire', false)
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
  // A confirmed save reloads the saved state by itself; editing continues without a manual refresh.
  assert.equal(h.byId('preset-non-openai').props.disabled, false)
  assert.throws(() => h.button('실제 상태 확인 후 편집 재개'))
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

test('fresh connection/profile scope starts with its loaded profile only, without leaking previous choices', () => {
  const h = harness()
  h.click('model-target-all')
  h.state.connectionId.value = 'another-connection'
  h.state.profile.value = 'default'
  h.setData({ ...fixture(), current_profile: 'default' })
  h.render()
  assert.deepEqual(h.selected('model-target-'), ['default'])
})

// Every profile already stored on a profile method, each with its own digest: the profile section is editable.
function profileFixture(backend = 'model-router-profiles') {
  const data = fixture()
  data.profiles.forEach((row, index) => {
    row.routing.enabled = true
    row.native_delegation.digest = ['a', 'b', 'c'][index].repeat(64)
    row.native_delegation.backend = backend
    row.native_delegation.auto_supported = true
    row.native_delegation.auto_policy = { heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } }
  })
  return data
}

const autoFixture = () => {
  const data = fixture()
  for (const row of data.profiles) {
    if (row.name !== 'claire') row.native_delegation.backend = 'model-router-profiles'
    row.routing.enabled = true
    row.native_delegation.auto_supported = true
    row.native_delegation.auto_policy = { heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } }
  }
  return data
}

test('automatic mode is chosen and saved in the model section; profile access waits for its own section', async () => {
  const data = autoFixture()
  data.profiles[1].native_delegation.policy.heavy = { mode: 'custom', chain: [{ provider: 'old', model: 'old-spare' }] }
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router-auto')
  assert.deepEqual(h.calls, [])
  assert.match(text(h.byId('native-auto-explanation')), /기본 모델·추론 설정/)
  assert.match(text(h.byId('native-auto-explanation')), /필수 검수는 슬롯 모델/)
  assert.equal(h.selectValue('slot-design-fallback-mode'), 'off')
  // The loaded profile is not stored on a profile method yet: its profile section is read-only.
  assert.match(text(h.byId('profile-delegation-readonly')), /전문 프로필에 맡기는 방식을 쓰지 않습니다/)
  assert.throws(() => h.byId('native-profile-other'))
  assert.throws(() => h.byId('profile-section-save'))
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'new')
  h.input('slot-design-spare-model-0', 'auto-spare')
  h.setResponder(operation => operation === 'delegation-preview' ? { plan_id: 'auto-plan', changes: [] } : { status: 'applied' })
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  const update = h.calls[0].body.updates[0]
  assert.equal(update.backend, 'model-router-auto')
  assert.deepEqual(update.slot_policy.design.chain, [{ provider: 'new', model: 'auto-spare' }])
  assert.equal(update.allow_additional_cost, true)
  assert.equal(update.allow_profile_access, false)
  assert.equal(Object.hasOwn(update, 'profile_routes'), false, 'the stored allow-list is not sent: the writer keeps it as stored')
})

test('automatic bulk save preserves each hidden ordinary-profile default', async () => {
  const data = autoFixture()
  for (const [i, row] of data.profiles.entries()) {
    row.native_delegation.profile_routes = { profiles: [{ name: 'default', description: 'General' }, { name: 'other', description: 'Specialist' }], default: i === 1 ? 'other' : 'default' }
  }
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router-auto')
  h.click('model-target-all')
  h.setResponder(operation => operation === 'delegation-preview' ? { plan_id: 'auto-plan', changes: [] } : { status: 'applied' })
  h.click('model-section-save'); await h.flush()
  assert.equal(h.calls[0].body.updates.length, 3)
  for (const update of h.calls[0].body.updates) {
    assert.equal(Object.hasOwn(update, 'profile_routes'), false, 'each stored allow-list and hidden default is left to the writer')
    assert.equal(update.allow_profile_access, false)
  }
})

test('old backend capability cannot save automatic mode', () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router-auto')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-targets')), /claire: .*통합 선택을 지원하지 않습니다/)
  assert.deepEqual(h.calls, [])
})

test('automatic and model-only spare drafts stay independent when switching modes', () => {
  const h = harness({ data: autoFixture() })
  h.select('native-delegation-backend', 'model-router-auto')
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'auto-provider')
  h.input('slot-design-spare-model-0', 'auto-model')
  h.select('native-delegation-backend', 'model-router')
  assert.equal(h.selectValue('slot-design-fallback-mode'), 'off')
  h.select('native-delegation-backend', 'model-router-auto')
  assert.equal(h.byId('slot-design-spare-model-0').props.value, 'auto-model')
  assert.deepEqual(h.calls, [])
})

test('backend selection is draft-only; one save writes the method first and the model edit second', async () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router')
  assert.deepEqual(h.calls, [])
  h.input('model-main-model', 'edited-main-model')
  h.setResponder(nativeReply)
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), CHAIN)
  const body = h.calls[0].body
  assert.deepEqual(Object.keys(body).sort(), ['expected_revision', 'updates'])
  assert.equal(body.updates.length, 1)
  assert.equal(body.updates[0].profile, 'claire')
  assert.equal(body.updates[0].backend, 'model-router')
  assert.equal(Object.hasOwn(body.updates[0], 'policy'), false)
  assert.deepEqual(body.updates[0].slot_policy, offSlots())
  assert.equal(JSON.stringify(body).includes('edited-main-model'), false)
  // The store plan validated before the native apply is not the one applied afterwards.
  assert.deepEqual(h.calls[1].body, h.calls[4].body)
  assert.equal(h.calls[4].body.save_scope, 'models')
  assert.equal(h.calls[4].body.models.main.model, 'edited-main-model')
  assert.deepEqual(h.calls[4].body.model_targets, ['claire'])
  assert.equal(h.calls[4].body.expected_revision, 7)
  assert.deepEqual(h.calls[3].body, { plan_id: 'native-batch-plan' })
  assert.deepEqual(h.calls[5].body, { plan_id: 'store-plan' })
})

test('profile execution grants start empty and do not follow model-copy targets', async () => {
  const h = harness({ data: profileFixture() })
  assert.deepEqual(h.selected('native-profile-'), [])
  assert.deepEqual(h.selected('profile-target-'), ['claire'])
  h.check('native-profile-other', true)
  h.click('native-profile-role-custom-other')
  h.input('native-profile-description-other', 'Read-only evidence collection')
  h.select('native-profile-default', 'other')
  h.check('native-profile-access-consent', true)
  h.click('model-target-all')
  assert.deepEqual(h.selected('profile-target-'), ['claire'], 'the model list never widens the profile list')
  assert.equal(h.byId('native-profile-access-consent').props.checked, true, 'model targets do not touch the profile consent')
  assert.match(text(h.byId('profile-section-summary')), /허용할 전문 프로필: other · 기본: other/)
  h.setResponder(operation => operation === 'delegation-preview'
    ? { plan_id: 'native-plan', changes: [{ profile: 'claire', field: 'delegation.backends.model-router-profiles' }], warnings: [] }
    : { status: 'applied', revision: 7 })
  h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.equal(h.calls[0].body.updates.length, 1)
  const update = h.calls[0].body.updates[0]
  assert.deepEqual(update.profile_routes, { profiles: [{ name: 'other', description: 'Read-only evidence collection' }], default: 'other' })
  assert.equal(update.allow_profile_access, true)
  assert.equal(update.profile, 'claire')
  assert.equal(update.backend, 'model-router-profiles')
})

test('the whole-page save never carries the delegation method; the model section save does', async () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router-profiles')
  h.click('global-save'); await h.flush()
  assert.equal(h.calls[0].operation, 'preview')
  assert.equal(JSON.stringify(h.calls[0].body).includes('model-router-profiles'), false)
  assert.equal(Object.hasOwn(h.calls[0].body, 'updates'), false)
  const g = harness()
  g.select('native-delegation-backend', 'model-router-profiles')
  g.setResponder(nativeReply); g.click('model-section-save'); await g.flush()
  assert.deepEqual(g.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.equal(g.calls[0].body.updates[0].backend, 'model-router-profiles')
})

test('native save never retries an ambiguous write and shares the global save lock', async () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router')
  let resolvePlan
  h.setResponder(operation => {
    if (operation === 'apply') throw new Error('write outcome unknown')
    return new Promise(resolve => { resolvePlan = resolve })
  })
  const staleSave = h.byId('model-section-save').props.onClick
  h.click('model-section-save'); staleSave(); h.render()
  assert.equal(h.calls.length, 1)
  assert.equal(h.byId('global-save').props.disabled, true)
  resolvePlan({ plan_id: 'native-plan', changes: [], warnings: [] }); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.equal(h.byId('model-section-save').props.disabled, true)
})

test('changing origin profile while native preview is pending never applies a stale plan', async () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router')
  let resolvePlan
  h.setResponder(() => new Promise(resolve => { resolvePlan = resolve }))
  h.click('model-section-save')
  h.state.connectionId.value = 'different-origin'; h.render()
  resolvePlan({ plan_id: 'stale-native-plan', changes: [], warnings: [] }); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview'])
})

test('native draft never adopts a newer query digest with an unchanged canonical revision', () => {
  const h = harness()
  h.select('native-delegation-backend', 'model-router')
  const retained = h.byId('model-section-save').props.onClick
  const newer = structuredClone(h.data())
  newer.profiles.find(row => row.name === 'claire').native_delegation.digest = 'b'.repeat(64)
  h.setData(newer); h.render()
  assert.equal(h.byId('model-section-save').props.disabled, true)
  retained(); h.render()
  assert.deepEqual(h.calls, [], 'a retained handler must not dispatch against a changed native baseline')
})

// The loaded profile (claire) is stored on Hermes' 'default' method; the other two on a plugin
// method, so a model-section copy may change them (a copy never rewrites another 'default').
const nativeBatchFixture = () => {
  const data = fixture()
  data.profiles.forEach((row, index) => {
    row.routing.enabled = true
    row.native_delegation.digest = ['a', 'b', 'c'][index].repeat(64)
    if (row.name !== 'claire') row.native_delegation.backend = 'model-router-profiles'
  })
  return data
}
const nativeReply = operation => operation === 'delegation-preview' ? { plan_id: 'native-batch-plan', changes: [], warnings: [] }
  : operation === 'preview' ? { plan_id: 'store-plan', changes: [], warnings: [] } : { status: 'applied', revision: 7 }
// A hand-picked target list is copy intent for the whole section: the delegation method first, then the models.
const CHAIN = ['delegation-preview', 'preview', 'status', 'apply', 'preview', 'apply']

test('each slot shows its own editable model next to its spare switching, following the unsaved draft', () => {
  const h = harness({ data: nativeBatchFixture() })
  assert.throws(() => h.byId('slot-design-follow'), 'the default method has no slot cards')
  assert.match(text(h.byId('native-default-explanation')), /작업 위임/)
  h.select('native-delegation-backend', 'model-router')
  assert.equal(h.selectValue('slot-design-follow'), 'custom')
  assert.equal(h.byId('slot-design-model').props.value, 'independent-heavy')
  assert.equal(h.selectValue('slot-code-complex-follow'), 'delegation')
  assert.equal(text(h.byId('slot-code-complex-resolved')), models.delegation.model)
  for (const id of slotIds) assert.equal(h.selectValue(`slot-${id}-fallback-mode`), 'off')
  const copy = text(h.byId('native-delegation-settings'))
  assert.match(copy, /다른 모델로 전환하지 않음/)
  assert.match(copy, /간단한 작업은 메인 모델이 직접 처리/)
  assert.doesNotMatch(copy, /Heavy|Light|delegate_task|purpose|백엔드|도구 재구성|revision|CAS|SOUL|자식 대화/)
  h.input('model-delegation-model', 'unsaved-delegation-model')
  assert.equal(text(h.byId('slot-code-complex-resolved')), 'unsaved-delegation-model')
  assert.deepEqual(h.calls, [])
})

test('one target list starts with the loaded profile and widens only by an explicit choice', () => {
  const h = harness({ data: nativeBatchFixture() })
  assert.deepEqual(h.selected('model-target-'), ['claire'])
  assert.throws(() => h.byId('routing-target-all')); assert.throws(() => h.byId('native-target-all'))
  h.click('model-target-all')
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  h.click('model-target-source')
  assert.deepEqual(h.selected('model-target-'), ['claire'])
  assert.deepEqual(h.calls, [])
})

test('native bulk save carries every target own frozen digest and no unrelated model/time payload', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router')
  h.click('model-target-all')
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'spare-service')
  h.input('slot-design-spare-model-0', 'spare/model')
  h.input('model-main-model', 'bulk-main')
  assert.match(text(h.byId('model-section-summary')), /default.*claire.*other/)
  assert.match(text(h.byId('model-section-summary')), /예비 모델을 둔 슬롯 1개/)
  assert.match(text(h.byId('native-delegation-settings')), /추가 비용|비용이 늘/)
  h.setResponder(nativeReply)
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), CHAIN)
  const updates = h.calls[0].body.updates
  assert.deepEqual(updates.map(row => row.profile), ['default', 'claire', 'other'])
  assert.deepEqual(updates.map(row => row.expected_digest), ['a', 'b', 'c'].map(c => c.repeat(64)))
  for (const update of updates) {
    assert.deepEqual(update.slot_policy.design, { mode: 'custom', chain: [{ provider: 'spare-service', model: 'spare/model' }] })
    assert.equal(update.allow_additional_cost, true)
    assert.equal(update.allow_profile_access, false)
  }
  assert.equal(JSON.stringify(h.calls[0].body).includes('bulk-main'), false)
  assert.equal(Object.hasOwn(h.calls[0].body, 'timeout_updates'), false)
  // Role models and the untouched slot declarations follow in one store plan for the same targets.
  const store = h.calls[4].body
  assert.equal(Object.hasOwn(store, 'save_scope'), false)
  assert.equal(store.models.main.model, 'bulk-main')
  assert.deepEqual(store.model_targets, ['default', 'claire', 'other'])
  assert.deepEqual(store.routing_targets, ['default', 'claire', 'other'])
  assert.deepEqual(store.routing.slots, declarations())
  assert.deepEqual(store.routing.heavy, routing.heavy); assert.deepEqual(store.routing.light, routing.light)
  assert.deepEqual(store.routing_profiles, ['default', 'claire', 'other'])
  assert.equal(Object.hasOwn(store, 'timeout_updates'), false)
})

test('native empty/subset selection survives source changes and explicit status refresh without widening', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.click('model-target-none')
  h.selectProfile('default')
  assert.deepEqual(h.selected('model-target-'), [])
  h.check('model-target-other', true)
  h.selectProfile('claire')
  assert.deepEqual(h.selected('model-target-'), ['other'])
  h.clickLabel('상태 새로고침'); await h.flush()
  assert.deepEqual(h.selected('model-target-'), ['other'])
  const newData = structuredClone(h.data())
  newData.profiles.push({ ...structuredClone(newData.profiles[0]), name: 'new-profile' })
  h.setData(newData); h.render()
  assert.deepEqual(h.selected('model-target-'), ['other'])
})

test('native source without manual targets follows the explicitly loaded profile only', () => {
  const h = harness({ data: nativeBatchFixture() })
  h.selectProfile('default')
  assert.deepEqual(h.selected('model-target-'), ['default'])
  h.selectProfile('other')
  assert.deepEqual(h.selected('model-target-'), ['other'])
})

test('native role save preserves each target hidden profile access rather than copying source allowlist', async () => {
  const data = nativeBatchFixture()
  data.profiles[2].native_delegation.profile_routes = { profiles: [{ name: 'default', description: 'retain account access' }], default: 'default' }
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  const other = h.calls[0].body.updates.find(row => row.profile === 'other')
  assert.equal(Object.hasOwn(other, 'profile_routes'), false)
  assert.equal(other.allow_profile_access, false)
})

test('profile roles inherit native intro without making an input or copying it on custom toggle', () => {
  const h = harness({ data: profileFixture() })
  h.check('native-profile-other', true)
  assert.match(text(h.byId('native-profile-role-other')), /Role of other/)
  assert.throws(() => h.byId('native-profile-description-other'))
  h.click('native-profile-role-custom-other')
  assert.equal(h.byId('native-profile-description-other').props.value, '')
  assert.deepEqual(h.calls, [])
  h.input('native-profile-description-other', 'Only for this delegation')
  h.click('native-profile-role-reset-other')
  assert.throws(() => h.byId('native-profile-description-other'))
  assert.match(text(h.byId('native-profile-role-other')), /Role of other/)
  assert.deepEqual(h.calls, [])
})

test('untouched descriptions retain each save origin and explicit edit propagates only its row', async () => {
  const data = profileFixture()
  for (const [index, row] of data.profiles.entries()) row.native_delegation.profile_routes = { profiles: [{ name: 'other', description: `Own description ${index}` }], default: null }
  const h = harness({ data }); h.click('profile-target-all')
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.equal(h.calls[0].body.updates.length, 3)
  for (const update of h.calls[0].body.updates) assert.equal(update.profile_routes.profiles[0].description, data.profiles.find(row => row.name === update.profile).native_delegation.profile_routes.profiles[0].description)
  const g = harness({ data }); g.click('profile-target-all')
  g.input('native-profile-description-other', 'Explicit new override'); g.setResponder(nativeReply); g.click('profile-section-save'); await g.flush()
  for (const update of g.calls[0].body.updates) assert.equal(update.profile_routes.profiles[0].description, 'Explicit new override')
})

test('legacy origin refuses new inheritance but permits old blank, removal or explicit override', async () => {
  const data = profileFixture(); delete data.profiles[1].native_delegation.role_intro_inheritance
  const h = harness({ data }); h.check('native-profile-other', true); h.check('native-profile-access-consent', true)
  assert.equal(h.byId('profile-section-save').props.disabled, true)
  h.click('native-profile-role-custom-other'); h.input('native-profile-description-other', 'Manual role'); assert.equal(h.byId('profile-section-save').props.disabled, false)
  const existing = profileFixture(); delete existing.profiles[1].native_delegation.role_intro_inheritance
  existing.profiles[1].native_delegation.profile_routes = { profiles: [{ name: 'other', description: '' }], default: null }
  const g = harness({ data: existing }); g.click('profile-target-source'); assert.equal(g.byId('profile-section-save').props.disabled, false)
  g.check('native-profile-other', false); assert.equal(g.byId('profile-section-save').props.disabled, false)
})

function roleContext() { return { schema: 1, owner: { profile: 'claire', base_identity: 'd'.repeat(64) }, target_profile: 'other',
  capability: { available: true, reason_code: null }, source: { digest: 'e'.repeat(64), native_description: 'Reviewed role', soul_text: '', enabled_skill_names: [], omitted_sources: [], truncated: false },
  payer: { profile: 'claire', basis: 'owner_saved_main', provider: 'fixture', model: 'owner-saved-model', fallback_policy: [], native_recovery: 'host_managed', route_digest: 'f'.repeat(64), estimate_usd: null }, limits: { input_bytes: 8192, max_output_tokens: 512, request_timeout_seconds: 30 } } }
function roleAIReply(operation) {
  const context = roleContext()
  if (operation === 'role-proposal-context') return context
  if (operation === 'role-proposal') return { schema: 1, status: 'proposed', owner: context.owner, target_profile: 'other', source_digest: context.source.digest, route_digest: context.payer.route_digest, proposal: { description: 'AI role draft only' }, model_attribution: { provider_verified: false }, usage: {}, stale: false }
  return nativeReply(operation)
}
test('real page AI controls preview first, generate once and accept into draft without saving', async () => {
  const data = profileFixture(); data.role_proposal = { schema: 1, available: true, transport: 'native_cli' }
  const h = harness({ data }); h.check('native-profile-other', true); h.setResponder(roleAIReply)
  h.click('native-profile-role-ai-other'); await h.flush()
  assert.deepEqual(h.calls.map(row => row.operation), ['role-proposal-context'])
  h.clickLabel('제안 만들기'); await h.flush()
  assert.deepEqual(h.calls.map(row => row.operation), ['role-proposal-context', 'role-proposal'])
  h.clickLabel('위임용 설명으로 사용'); await h.flush()
  assert.equal(h.byId('native-profile-description-other').props.value, 'AI role draft only')
  assert.equal(h.byId('native-profile-access-consent').props.checked, false)
  assert.deepEqual(h.calls.map(row => row.operation), ['role-proposal-context', 'role-proposal', 'role-proposal-context'])
  assert.ok(h.calls.every(row => row.profile === 'claire'))
})
test('AI result cannot overwrite later manual description or a different loaded template', async () => {
  const data = profileFixture(); data.role_proposal = { schema: 1, available: true, transport: 'native_cli' }
  const h = harness({ data }); h.check('native-profile-other', true); h.setResponder(roleAIReply)
  h.click('native-profile-role-ai-other'); await h.flush(); h.click('native-profile-role-custom-other'); h.input('native-profile-description-other', 'Keep manual draft'); await h.flush()
  assert.throws(() => h.button('제안 만들기')); assert.equal(h.byId('native-profile-description-other').props.value, 'Keep manual draft')
  assert.equal(h.calls.filter(row => row.operation === 'role-proposal').length, 0)
})

test('profile section bulk save preserves each target stored method and spare policy', async () => {
  const data = profileFixture()
  data.profiles[2].native_delegation.policy.light = { mode: 'custom', chain: [{ provider: 'existing-service', model: 'existing-spare' }] }
  data.profiles[0].native_delegation.backend = 'model-router-auto'
  data.profiles[0].native_delegation.auto_policy.heavy = { mode: 'custom', chain: [{ provider: 'own', model: 'own-auto-spare' }] }
  const h = harness({ data })
  h.click('profile-target-all')
  h.check('native-profile-other', true)
  h.select('native-profile-default', 'other')
  assert.equal(h.byId('profile-section-save').props.disabled, true, 'a new grant needs the consent')
  h.check('native-profile-access-consent', true)
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  const byName = Object.fromEntries(h.calls[0].body.updates.map(row => [row.profile, row]))
  assert.deepEqual(Object.keys(byName), ['default', 'claire', 'other'])
  assert.equal(byName.default.backend, 'model-router-auto')
  assert.equal(byName.claire.backend, 'model-router-profiles')
  assert.equal(byName.other.backend, 'model-router-profiles')
  for (const update of Object.values(byName)) {
    for (const key of ['policy', 'slot_policy', 'allow_additional_cost']) assert.equal(Object.hasOwn(update, key), false, `${update.profile} ${key}: the stored spare policy is left to the writer`)
    assert.deepEqual(update.profile_routes.profiles.map(entry => entry.name), ['other'])
    assert.equal(update.allow_profile_access, true)
    assert.equal(update.expected_digest, data.profiles.find(row => row.name === update.profile).native_delegation.digest)
  }
  // The automatic method keeps its stored hidden default; the profile method takes the draft's.
  assert.equal(byName.default.profile_routes.default, null)
  assert.equal(byName.claire.profile_routes.default, 'other')
  assert.equal(byName.other.profile_routes.default, 'other')
})

test('expanding profile save targets resets account-access confirmation; model targets do not', () => {
  const h = harness({ data: profileFixture() })
  h.check('native-profile-other', true); h.check('native-profile-access-consent', true)
  h.click('model-target-all')
  assert.equal(h.byId('native-profile-access-consent').props.checked, true)
  h.click('profile-target-all')
  assert.equal(h.byId('native-profile-access-consent').props.checked, false)
  assert.equal(h.byId('profile-section-save').props.disabled, true)
})

test('native non-source stale digest blocks save and retained callbacks without silently rebasing', () => {
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  const save = h.byId('model-section-save').props.onClick
  const next = structuredClone(h.data())
  next.profiles[0].native_delegation.digest = 'd'.repeat(64)
  h.setData(next); h.render()
  assert.equal(h.byId('model-section-save').props.disabled, true)
  save(); h.render()
  assert.deepEqual(h.calls, [])
  h.check('model-target-default', false)
  assert.equal(h.byId('model-section-save').props.disabled, false)
})

test('native target changes during preview prevent apply even when global revision is unchanged', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  let release
  h.setResponder(() => new Promise(resolve => { release = resolve }))
  h.click('model-section-save')
  const next = structuredClone(h.data()); next.profiles[2].native_delegation.digest = 'd'.repeat(64)
  h.setData(next); h.render()
  release({ plan_id: 'stale-target-plan', changes: [], warnings: [] }); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview'])
})

test('a selected target that disappears stays ticked and blocks by name; one that cannot take the method is skipped in the open', async () => {
  const gone = harness({ data: nativeBatchFixture() })
  gone.select('native-delegation-backend', 'model-router'); gone.click('model-target-all')
  const fewer = structuredClone(gone.data()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  gone.setData(fewer); gone.render()
  assert.deepEqual(gone.selected('model-target-'), ['claire', 'default', 'other'], 'never dropped quietly')
  assert.match(text(gone.byId('model-section-targets')), /더 이상 찾을 수 없어 저장하지 않습니다\. 적용 대상에서 체크를 해제하세요\. other/)
  assert.equal(gone.byId('model-section-save').props.disabled, true)
  gone.check('model-target-other', false)
  assert.deepEqual(gone.selected('model-target-'), ['claire', 'default'])
  assert.equal(gone.byId('model-section-save').props.disabled, false)
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  const next = structuredClone(h.data()); next.profiles[2].native_delegation.editable = false
  h.setData(next); h.render()
  assert.match(text(h.byId('model-section-skipped')), /other/)
  assert.match(text(h.byId('model-section-targets')), /맡기는 방식과 예비 모델은 적용하지 않습니다\. 이 프로필은 설정을 변경할 수 없습니다/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls[0].body.updates.map(row => row.profile), ['default', 'claire'])
  assert.deepEqual(h.calls[4].body.model_targets, ['default', 'claire', 'other'])
})

test('native all-selected never enables a profile saved with role routing disabled', async () => {
  const data = nativeBatchFixture(); data.profiles[2].routing.enabled = false
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  assert.match(text(h.byId('model-section-targets')), /적용하지 않습니다\. 이 프로필의 작업 분담이 꺼져 있습니다/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls[0].body.updates.map(row => row.profile), ['default', 'claire'])
  assert.equal(JSON.stringify(h.calls[0].body).includes('routing_profiles'), false)
  assert.deepEqual(h.calls[4].body.routing_profiles, ['default', 'claire'], 'saving models never turns routing back on')
})

test('native preview resolving after page unmount cannot start an apply', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  let release
  h.setResponder(() => new Promise(resolve => { release = resolve }))
  h.click('model-section-save'); h.unmount()
  release({ plan_id: 'unmounted-plan', changes: [], warnings: [] }); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview'])
})

test('native ambiguous apply remains locked after page remount until explicit reconciliation', async () => {
  const storage = setupStorage(), data = nativeBatchFixture()
  const h = harness({ storage, data })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  h.setResponder(operation => { if (operation === 'apply') throw new Error('unknown write'); return nativeReply(operation) })
  h.click('model-section-save'); await h.flush(); h.unmount()
  const next = harness({ storage, data })
  assert.equal(next.byId('model-main-model').props.disabled, true)
  assert.deepEqual(next.calls, [])
  next.clickLabel('실제 상태 확인 후 편집 재개'); await next.flush()
  assert.equal(next.byId('model-main-model').props.disabled, true)
  next.check('native-save-recovery-confirm', true)
  next.click('native-save-recover'); await next.flush()
  assert.equal(next.byId('model-main-model').props.disabled, false)
})

test('native pending write from a disposed page is manual-only, not a permanent unrecoverable lock', async () => {
  const storage = setupStorage(), data = nativeBatchFixture()
  const owner = harness({ storage, data })
  owner.select('native-delegation-backend', 'model-router')
  owner.setResponder(operation => operation === 'apply' ? new Promise(() => {}) : nativeReply(operation))
  owner.click('model-section-save'); await owner.flush(); owner.unmount()
  const next = harness({ storage, data })
  assert.equal(next.byId('model-main-model').props.disabled, true)
  assert.equal(next.byId('native-save-recovery-confirm').props.checked, false)
  assert.deepEqual(next.calls, [])
  next.check('native-save-recovery-confirm', true)
  next.click('native-save-recover'); await next.flush()
  assert.equal(next.byId('model-main-model').props.disabled, false)
  assert.deepEqual(next.calls, [], 'reconciliation reads status only; it never retries the old write')
})

test('native unresolved write cannot be cleared from a different connection to the same root', async () => {
  const storage = setupStorage(), data = nativeBatchFixture()
  const owner = harness({ storage, data })
  owner.select('native-delegation-backend', 'model-router')
  owner.setResponder(operation => { if (operation === 'apply') throw new Error('unknown write'); return nativeReply(operation) })
  owner.click('model-section-save'); await owner.flush(); owner.unmount()
  const next = harness({ storage, data })
  next.state.connectionId.value = 'different-view-of-same-root'; next.render()
  assert.equal(next.byId('model-main-model').props.disabled, true)
  assert.throws(() => next.byId('native-save-recovery-confirm'))
  next.clickLabel('실제 상태 확인 후 편집 재개'); await next.flush()
  assert.equal(next.byId('model-main-model').props.disabled, true)
  assert.deepEqual(next.calls, [])
})

test('native unresolved record does not lock an unrelated verified root', async () => {
  const storage = setupStorage(), data = nativeBatchFixture()
  const owner = harness({ storage, data })
  owner.select('native-delegation-backend', 'model-router')
  owner.setResponder(operation => { if (operation === 'apply') throw new Error('unknown write'); return nativeReply(operation) })
  owner.click('model-section-save'); await owner.flush(); owner.unmount()
  const foreign = nativeBatchFixture(); foreign.readiness_context.base_identity = 'e'.repeat(64)
  const next = harness({ storage, data: foreign })
  next.state.connectionId.value = 'other-root-connection'; next.render()
  assert.equal(next.byId('model-main-model').props.disabled, false)
  assert.deepEqual(next.calls, [])
})

function initialSetupFixture() {
  const data = nativeBatchFixture()
  data.readiness_context.release = { catalog_name: 'model-router', version: '0.6.0', ref: 'b'.repeat(40) }
  data.profiles.forEach((row, index) => {
    row.readiness = { ...setupReadiness('ready'), version: '0.6.0' }
    row.initial_setup = { schema: 1, default_backend: 'model-router-auto', action: 'select_backend', eligible: true, backend_unset: true,
      digest: String(index + 1).repeat(64), intent_digest: 'a'.repeat(64), reason_codes: ['backend_unset'] }
  })
  return data
}

test('initial card defaults eligible profiles only and never writes while viewed or selected', () => {
  const data = initialSetupFixture()
  data.profiles[2].initial_setup.action = 'preserved'; data.profiles[2].initial_setup.eligible = false
  const h = harness({ data })
  assert.deepEqual(h.selected('initial-profile-'), ['claire', 'default'])
  assert.equal(h.byId('initial-profile-other').props.disabled, true)
  h.click('initial-setup-none'); assert.deepEqual(h.selected('initial-profile-'), [])
  assert.equal(h.byId('initial-setup-run').props.disabled, true)
  h.click('initial-setup-all'); assert.deepEqual(h.selected('initial-profile-'), ['claire', 'default'])
  assert.deepEqual(h.calls, [])
})

test('retained initial setup callback cannot revive an emptied selection', async () => {
  const h = harness({ data: initialSetupFixture() }), retained = h.byId('initial-setup-run').props.onClick
  let routes = 0
  h.host.profileRoutes = async () => { routes += 1; return [] }
  h.click('initial-setup-none'); retained(); await h.flush()
  assert.equal(routes, 0); assert.deepEqual(h.calls, [])
})

test('initial card preserves manual empty/subset and offers new profiles without selecting them', async () => {
  const h = harness({ data: initialSetupFixture() })
  h.click('initial-setup-none'); h.selectProfile('default')
  assert.deepEqual(h.selected('initial-profile-'), [])
  h.check('initial-profile-other', true)
  const fresh = structuredClone(h.data()); fresh.profiles.push({ ...structuredClone(fresh.profiles[0]), name: 'future-setup' })
  h.setStatusResponder(() => fresh)
  h.input('model-main-model', 'keep-unrelated-initial-draft')
  h.click('initial-setup-refresh'); await h.flush()
  assert.deepEqual(h.selected('initial-profile-'), ['other'])
  assert.equal(h.byId('initial-profile-future-setup').props.checked, false)
  assert.equal(h.byId('model-main-model').props.value, 'keep-unrelated-initial-draft')
})

test('actual initial page handler preserves dirty drafts and uses only explicit setup writes', async () => {
  const h = harness({ data: initialSetupFixture() }), backend = structuredClone(h.data()), requests = [], plans = new Map()
  h.click('initial-setup-none'); h.check('initial-profile-other', true)
  h.input('model-main-model', 'keep-unsaved-setup-model')
  const retainedSave = h.byId('global-save').props.onClick
  h.host.profileRoutes = async () => ['default','claire','other'].map(profile => ({ mode: 'local', connectionId: 'local', profile, targetProfile: profile }))
  h.host.requestProfile = async (route, method, args) => {
    assert.equal(route.profile, 'claire'); assert.equal(args.profile, 'claire'); assert.equal(method, 'cli.exec')
    const operation = args.argv[args.argv.indexOf('model-router') + 1], body = JSON.parse(args.argv.at(-1))
    requests.push({ operation, body })
    let result
    if (operation === 'status') result = structuredClone(backend)
    else if (operation === 'initial-setup-preview') {
      const profile = body.updates[0].profile, plan_id = 'b'.repeat(32)
      plans.set(plan_id, profile); result = { plan_id, default_backend: 'model-router-auto', changes: [{ profile, field: 'delegation.backend', before: null, after: 'model-router-auto' }] }
    } else if (operation === 'apply') {
      const profile = plans.get(body.plan_id), row = backend.profiles.find(row => row.name === profile)
      row.initial_setup.action = 'complete'; row.initial_setup.eligible = false; row.native_delegation.backend = 'model-router-auto'
      result = { status: 'applied', plan_id: body.plan_id, applied: [{ profile, key: 'delegation.backend' }], remaining: [] }
    } else throw new Error(operation)
    return { code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(result) }
  }
  h.click('initial-setup-run')
  for (let i=0; i<5; i++) await h.flush()
  assert.deepEqual(requests.filter(row => row.operation !== 'status').map(row => row.operation), ['initial-setup-preview', 'apply'])
  assert.deepEqual(requests.find(row => row.operation === 'initial-setup-preview').body.updates.map(row => row.profile), ['other'])
  assert.equal(h.byId('model-main-model').props.value, 'keep-unsaved-setup-model')
  assert.throws(() => h.byId('global-save'), 'normal save is replaced by explicit rebase after setup')
  retainedSave(); h.render()
  assert.deepEqual(h.calls, [])
})

test('native malformed saved mutation record is not interpreted as permission to retry', () => {
  const storage = setupStorage()
  storage.set('native-settings-save-fences-v1', { '["local","claire","open"]': { state: 'unknown' } })
  const h = harness({ storage, data: nativeBatchFixture() })
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.deepEqual(h.calls, [])
})

for (const changed of ['excluded-source', 'selected-target', 'root']) {
  test(`native preview rechecks uncached server ${changed} state before apply`, async () => {
    const h = harness({ data: nativeBatchFixture() })
    h.select('native-delegation-backend', 'model-router')
    h.click('model-target-none'); h.check('model-target-other', true)
    const fresh = structuredClone(h.data())
    if (changed === 'root') fresh.readiness_context.base_identity = 'e'.repeat(64)
    else fresh.profiles.find(row => row.name === (changed === 'excluded-source' ? 'claire' : 'other')).native_delegation.digest = 'f'.repeat(64)
    h.setResponder(nativeReply); h.setStatusResponder(() => fresh)
    h.click('model-section-save'); await h.flush()
    assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'preview', 'status'])
    assert.deepEqual(h.calls[0].body.updates.map(row => row.profile), ['other'])
    assert.notDeepEqual(h.data(), fresh, 'fresh validation must not silently rebase query/drafts')
  })
}

test('native fresh status failure cannot dispatch apply', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.select('native-delegation-backend', 'model-router')
  h.setResponder(nativeReply); h.setStatusResponder(() => { throw new Error('status unavailable') })
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status'])
})

for (const change of ['unmount', 'leave-and-return']) {
  test(`native fresh status resolving after ${change} cannot dispatch apply`, async () => {
    const h = harness({ data: nativeBatchFixture() })
    h.select('native-delegation-backend', 'model-router')
    let release
    h.setResponder(nativeReply); h.setStatusResponder(() => new Promise(resolve => { release = resolve }))
    h.click('model-section-save'); await h.flush()
    assert.equal(typeof release, 'function')
    if (change === 'unmount') h.unmount()
    else { h.state.connectionId.value = 'elsewhere'; h.render(); h.state.connectionId.value = 'local'; h.render() }
    release(structuredClone(h.data())); await h.flush()
    assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status'])
  })
}

// ---- Task slots: per-slot models, per-slot spare models, one save -------------
const slotFixture = () => {
  const data = nativeBatchFixture()
  for (const row of data.profiles) row.native_delegation.backend = 'model-router'
  return data
}

test('slot basis switching edits the draft only: custom is pre-filled from the followed model and cleared when leaving', () => {
  const h = harness({ data: slotFixture() })
  assert.equal(h.selectValue('slot-code-complex-follow'), 'delegation')
  h.select('slot-code-complex-follow', 'custom')
  assert.equal(h.byId('slot-code-complex-model').props.value, models.delegation.model)
  assert.equal(h.byId('slot-code-complex-provider').props.value, models.delegation.provider)
  assert.equal(h.selectValue('slot-code-complex-reasoning'), models.delegation.reasoning)
  h.input('slot-code-complex-model', 'strong-coder')
  h.select('slot-code-complex-follow', 'main')
  assert.throws(() => h.byId('slot-code-complex-model'))
  assert.equal(text(h.byId('slot-code-complex-resolved')), models.main.model)
  h.select('slot-code-complex-follow', 'custom')
  assert.equal(h.byId('slot-code-complex-model').props.value, models.main.model, 'a discarded custom route is not resurrected')
  assert.deepEqual(h.calls, [])
})

test('a slot-only change is one routing-scoped store save carrying all six slots and the untouched tier pair', async () => {
  const h = harness({ data: slotFixture() })
  h.select('slot-computer-use-follow', 'custom')
  h.input('slot-computer-use-provider', 'screen-service'); h.input('slot-computer-use-model', 'screen-model')
  assert.match(text(h.byId('model-section-summary')), /작업 슬롯 모델\(직접 지정 3개\)/)
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  const body = h.calls[0].body
  assert.equal(body.save_scope, 'routing')
  assert.deepEqual(Object.keys(body.routing.slots), slotIds)
  assert.deepEqual(body.routing.slots['computer-use'], { follow: 'custom', custom: route('screen-service', 'screen-model', models.delegation.reasoning) })
  assert.deepEqual(body.routing.slots.design, declarations().design)
  assert.deepEqual(body.routing.heavy, routing.heavy); assert.deepEqual(body.routing.light, routing.light)
  assert.deepEqual(body.routing_targets, ['claire'])
  assert.deepEqual(body.model_targets, [])
  assert.deepEqual(body.routing_profiles, ['default', 'claire', 'other'])
})

test('an incomplete custom slot or an empty target list blocks the save before any request', () => {
  const h = harness({ data: slotFixture() })
  h.select('slot-verify-simple-follow', 'custom'); h.input('slot-verify-simple-model', '')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-targets')), /검증 · 간단: 모델을 선택하세요/)
  h.input('slot-verify-simple-model', 'quick-check')
  assert.equal(h.byId('model-section-save').props.disabled, false)
  h.click('model-target-none')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-targets')), /적용 대상이 0개입니다/)
  assert.deepEqual(h.calls, [])
})

test('slot models are read-only and left out of every store body while another installed profile cannot read them', async () => {
  const data = slotFixture(); data.slot_capabilities.blocking_profiles = ['other']
  const h = harness({ data })
  assert.match(text(h.byId('slot-blocked-note')), /other/)
  assert.equal(h.byId('slot-design-model').props.disabled, true)
  assert.equal(h.byId('slot-design-fallback-mode') && h.selectValue('slot-design-fallback-mode'), 'off')
  h.input('model-main-model', 'still-editable'); h.click('model-target-all')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  const store = h.calls.filter(call => call.operation === 'preview').at(-1).body
  assert.equal(store.save_scope, 'models')
  assert.equal(Object.hasOwn(store.routing, 'slots'), false)
  const g = harness({ data }); g.input('model-main-model', 'whole-page'); g.click('global-save'); await g.flush()
  assert.equal(Object.hasOwn(g.calls[0].body.routing, 'slots'), false)
})

test('a profile whose plugin predates slots shows no slot cards and keeps its stored two-role spare policy', async () => {
  const data = slotFixture(); delete data.slot_capabilities
  for (const row of data.profiles) {
    delete row.slots
    for (const key of ['slot_policy', 'auto_slot_policy', 'policy_schema', 'auto_policy_schema', 'slot_policy_supported']) delete row.native_delegation[key]
  }
  data.profiles[1].native_delegation.policy.heavy = { mode: 'custom', chain: [{ provider: 'kept', model: 'kept-spare' }] }
  const h = harness({ data })
  assert.match(text(h.byId('slot-update-note')), /업데이트/)
  assert.throws(() => h.byId('slot-design-follow'))
  h.select('native-delegation-backend', 'model-router-auto'); h.select('native-delegation-backend', 'model-router-profiles')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  const update = h.calls[0].body.updates[0]
  assert.equal(update.backend, 'model-router-profiles')
  for (const key of ['slot_policy', 'policy', 'allow_additional_cost', 'profile_routes']) assert.equal(Object.hasOwn(update, key), false, `${key} is left to the writer`)
})

test('copying slot spare models refuses nothing silently: an older target is skipped by name and keeps its own policy', async () => {
  const data = slotFixture(); data.profiles[2].native_delegation.slot_policy_supported = false
  const h = harness({ data })
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
  h.click('model-target-all')
  assert.match(text(h.byId('model-section-skipped')), /other/)
  assert.match(text(h.byId('model-section-targets')), /슬롯별 예비 모델을 지원하지 않습니다/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  const updates = h.calls[0].body.updates
  assert.deepEqual(updates.map(row => row.profile), ['default', 'claire'])
  for (const update of updates) {
    assert.deepEqual(update.slot_policy.design, { mode: 'custom', chain: [{ provider: 'spare-service', model: 'spare/model' }] })
    assert.deepEqual(update.slot_policy['code-complex'], { mode: 'off', chain: [] })
    assert.equal(Object.hasOwn(update, 'policy'), false)
    assert.equal(update.allow_additional_cost, true)
  }
})

test('a non-model method leaves every target spare policy in its stored shape', async () => {
  const data = slotFixture()
  data.profiles[0].native_delegation.policy_schema = 2
  data.profiles[0].native_delegation.slot_policy.design = { mode: 'custom', chain: [{ provider: 'own', model: 'own-slot-spare' }] }
  data.profiles[2].native_delegation.policy_schema = 1
  data.profiles[2].native_delegation.policy.light = { mode: 'custom', chain: [{ provider: 'own', model: 'own-role-spare' }] }
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router-profiles'); h.click('model-target-all')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  // No spare models on screen for a non-model method: every target's stored policy (two-role, per
  // slot or absent) is left to the writer.
  assert.deepEqual(h.calls[0].body.updates.map(row => row.profile), ['default', 'claire', 'other'])
  for (const update of h.calls[0].body.updates) {
    assert.equal(update.backend, 'model-router-profiles')
    for (const key of ['policy', 'slot_policy', 'allow_additional_cost']) assert.equal(Object.hasOwn(update, key), false)
  }
})

test('either preview failing stops the chain before anything is written', async () => {
  for (const failing of ['delegation-preview', 'preview']) {
    const h = harness({ data: slotFixture() })
    h.select('slot-design-fallback-mode', 'custom')
    h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
    h.input('model-main-model', 'edited-main')
    h.setResponder(operation => { if (operation === failing) throw new Error('validation refused'); return nativeReply(operation) })
    h.click('model-section-save'); await h.flush()
    assert.equal(h.calls.some(call => call.operation === 'apply'), false)
    assert.deepEqual(h.calls.map(call => call.operation), failing === 'preview' ? ['delegation-preview', 'preview'] : ['delegation-preview'])
    assert.match(text(h.byId('model-section-targets')), /저장되지 않았습니다\. validation refused/)
    assert.equal(h.byId('model-main-model').props.value, 'edited-main', 'the draft survives a refused save')
    assert.equal(h.byId('model-section-save').props.disabled, false)
  }
})

test('a store failure after the native apply is reported as partial, names both halves and is never retried', async () => {
  for (const stage of ['second-preview', 'second-apply']) {
    const h = harness({ data: slotFixture() })
    h.select('slot-design-fallback-mode', 'custom')
    h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
    h.input('model-main-model', 'edited-main')
    let previews = 0, applies = 0
    h.setResponder(operation => {
      if (operation === 'preview' && ++previews === 2 && stage === 'second-preview') throw new Error('store changed meanwhile')
      if (operation === 'apply' && ++applies === 2) throw new Error('transport lost')
      return nativeReply(operation)
    })
    h.click('model-section-save'); await h.flush()
    assert.deepEqual(h.calls.map(call => call.operation), stage === 'second-preview' ? CHAIN.slice(0, 5) : CHAIN)
    const outcome = text(h.render())
    assert.match(outcome, /일부 설정만 적용되었을 수 있습니다/)
    assert.match(outcome, /‘맡기는 방식과 예비 모델’: 저장했습니다\./)
    assert.match(outcome, stage === 'second-preview' ? /‘모델 변경’: 저장하지 않았습니다\..*\(사유: store changed meanwhile\)/ : /‘모델 변경’: 저장 결과를 확인할 수 없습니다\..*\(사유: transport lost\)/)
    assert.doesNotMatch(outcome, /은\(는\)/)
    assert.equal(h.byId('model-main-model').props.disabled, true, 'editing stays locked until the real state is reloaded')
    const before = h.calls.length
    h.byId('model-section-save').props.onClick?.(); await h.flush()
    assert.equal(h.calls.length, before)
  }
})

test('a partial native receipt ends the chain: the store save is not attempted', async () => {
  const h = harness({ data: slotFixture() })
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
  h.input('model-main-model', 'edited-main')
  h.setResponder(operation => operation === 'apply' ? { status: 'partial', applied: [], remaining: [{ profile: 'claire', key: 'delegation.backend' }] } : nativeReply(operation))
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'preview', 'status', 'apply'])
  assert.match(text(h.render()), /일부 설정만 적용되었을 수 있습니다/)
  assert.match(text(h.render()), /‘모델 변경’ 저장은 시작하지 않았습니다/)
  // The same is said when the native apply itself is lost.
  const g = harness({ data: slotFixture() })
  g.select('slot-design-fallback-mode', 'custom')
  g.input('slot-design-spare-provider-0', 'spare-service'); g.input('slot-design-spare-model-0', 'spare/model')
  g.input('model-main-model', 'edited-main')
  g.setResponder(operation => { if (operation === 'apply') throw new Error('transport lost'); return nativeReply(operation) })
  g.click('model-section-save'); await g.flush()
  assert.deepEqual(g.calls.map(call => call.operation), ['delegation-preview', 'preview', 'status', 'apply'])
  assert.match(text(g.render()), /적용 결과를 확인할 수 없습니다/)
  assert.match(text(g.render()), /transport lost ‘모델 변경’ 저장은 시작하지 않았습니다/)
})

test('profiles with task routing off get a separate re-enable save that changes membership only', async () => {
  const quiet = harness({ data: slotFixture() })
  assert.throws(() => quiet.byId('routing-reenable'), 'no notice while every profile has routing on')
  assert.throws(() => quiet.byId('routing-enabled')); assert.throws(() => quiet.byId('routing-profile-claire'))
  const data = fixture(); data.profiles[1].native_delegation.backend = 'model-router'
  const h = harness({ data })
  assert.deepEqual([...walk(h.byId('routing-reenable'))].filter(node => node.type === 'Checkbox').map(node => node.props.id), ['routing-reenable-default', 'routing-reenable-other'])
  assert.equal(h.byId('routing-reenable-save').props.disabled, true)
  h.check('routing-reenable-other', true)
  h.select('slot-code-simple-follow', 'main'); h.input('model-main-model', 'unsaved-main')
  h.click('routing-reenable-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  const body = h.calls[0].body
  assert.equal(body.save_scope, 'routing')
  assert.deepEqual(body.routing_profiles, ['claire', 'other'])
  assert.deepEqual(body.routing_targets, [])
  assert.equal(Object.hasOwn(body.routing, 'slots'), false)
  assert.deepEqual(body.routing.heavy, routing.heavy); assert.deepEqual(body.routing.light, routing.light)
  assert.equal(body.routing.enabled, true)
  assert.deepEqual(body.model_targets, [])
  assert.equal(JSON.stringify(body).includes('unsaved-main'), false)
  const g = harness({ data })
  g.check('routing-reenable-other', true); g.input('model-main-model', 'model-only')
  g.click('model-section-save'); await g.flush()
  assert.deepEqual(g.calls[0].body.routing_profiles, ['claire'], 'the model save never changes membership')
  assert.equal(g.byId('routing-reenable-other').props.checked, true, 'a pending re-enable choice survives a model save (no automatic reload over it)')
  assert.equal(g.calls.filter(call => call.operation === 'status').length, 0)
})

test('a review slot on the same model as complex code says so without blocking the save', () => {
  const h = harness({ data: slotFixture() })
  assert.throws(() => h.byId('slot-verify-same-model-note'))
  h.select('slot-code-complex-follow', 'custom')
  h.input('slot-code-complex-provider', 'operator'); h.input('slot-code-complex-model', 'independent-heavy')
  assert.match(text(h.byId('slot-verify-same-model-note')), /같은 모델/)
  assert.equal(h.byId('model-section-save').props.disabled, false)
})

// ---- Copy intent and stale-state locks for the one target list -----------------
test('a hand-picked target list persists, but its copy intent ends with a profile change or a reload', async () => {
  const h = harness({ data: slotFixture() })
  h.click('model-target-none'); h.check('model-target-other', true)
  h.selectProfile('default')
  assert.deepEqual(h.selected('model-target-'), ['other'])
  h.input('model-main-model', 'new-main')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.find(c => c.operation === 'preview').body.routing_targets, [], 'slot models are not copied without an edit or a fresh choice')
  h.click('model-target-all')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'preview').at(-1).body.routing_targets, ['default', 'claire', 'other'])
  // The whole-page save does not carry the delegation method the hand-picked list would also copy,
  // so it does not reload over that pending copy by itself.
  assert.match(text(h.render()), /자동으로 다시 불러오지 않았습니다/)
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  h.input('model-main-model', 'next-main')
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.filter(c => c.operation === 'preview').at(-1).body.routing_targets, [])
})

test('reverting a slot edit cancels its implicit copy: the save is role models only', async () => {
  const h = harness({ data: slotFixture() })
  h.input('slot-design-model', 'temporary-edit'); h.input('slot-design-model', 'independent-heavy')
  h.input('model-main-model', 'model-only')
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  assert.equal(h.calls[0].body.save_scope, 'models')
  assert.deepEqual(h.calls[0].body.routing_targets, [])
})

test('a background revision change locks the save, keeps the draft and never promotes old copy intent', async () => {
  const h = harness({ data: slotFixture() })
  h.input('slot-design-model', 'unsaved-old-edit'); h.click('model-target-all')
  const staleSave = h.byId('model-section-save').props.onClick
  const newer = structuredClone(h.data()); newer.revision++
  h.setData(newer); h.render()
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.equal(h.byId('slot-design-model').props.value, 'unsaved-old-edit')
  staleSave(); await h.flush()
  assert.equal(h.calls.length, 0)
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  h.clickLabel('상태 새로고침'); await h.flush()
  // The wide list is still ticked, but with no edit and no fresh choice there is nothing to save.
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-summary')), /바뀐 내용이 없어 저장할 것이 없습니다/)
  h.byId('model-section-save').props.onClick?.(); await h.flush()
  assert.equal(h.calls.length, 0)
  h.click('global-save'); await h.flush()
  const body = h.calls.find(call => call.operation === 'preview').body
  assert.equal(body.expected_revision, 8)
  assert.deepEqual(body.model_targets, [], 'a list that merely persisted copies no role models')
  assert.deepEqual(body.routing_targets, [])
})

test('a status refresh during pending validation changes neither the captured targets nor the revision, and applies once', async () => {
  const h = harness({ data: slotFixture() })
  let release
  h.setResponder(operation => operation === 'preview' ? new Promise(resolve => { release = resolve }) : { status: 'applied', revision: 8 })
  h.input('slot-design-model', 'captured-route'); h.click('model-target-all')
  h.click('global-save'); await h.flush()
  const captured = structuredClone(h.calls[0].body)
  h.setData({ ...structuredClone(h.data()), revision: 8 }); h.render()
  release({ plan_id: 'captured-plan', changes: [] }); await h.flush()
  assert.deepEqual(h.calls[0].body, captured)
  assert.equal(captured.expected_revision, 7)
  assert.deepEqual(captured.routing_targets, ['default', 'claire', 'other'])
  assert.equal(captured.routing.slots.design.custom.model, 'captured-route')
  assert.equal(h.calls.filter(c => c.operation === 'apply').length, 1)
})

test('a source-only target list never widens when another profile is loaded', async () => {
  const h = harness({ data: slotFixture() })
  h.click('model-target-source')
  h.selectProfile('other')
  assert.deepEqual(h.selected('model-target-'), ['claire'])
  h.input('slot-design-model', 'other-route-copy')
  h.click('model-section-save'); await h.flush()
  const body = h.calls.find(c => c.operation === 'preview').body
  assert.equal(body.profile, 'other')
  assert.deepEqual(body.routing_targets, ['claire'])
})

// ---- Review corrections: nothing-to-save, hidden values, whole-page coherence ----
test('with nothing changed the model save is disabled; a persisted wide list copies nothing after a profile change', async () => {
  const fresh = harness({ data: slotFixture() })
  assert.equal(fresh.byId('model-section-save').props.disabled, true)
  fresh.byId('model-section-save').props.onClick?.(); await fresh.flush()
  assert.deepEqual(fresh.calls, [])
  const h = harness({ data: slotFixture() })
  h.click('model-target-all')
  assert.equal(h.byId('model-section-save').props.disabled, false, 'a fresh choice is copy intent')
  h.selectProfile('other')
  assert.deepEqual(h.selected('model-target-'), ['claire', 'default', 'other'])
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.byId('model-section-save').props.onClick?.(); await h.flush()
  assert.deepEqual(h.calls, [], 'the other profile models are never copied under a no-change summary')
  // Picking the list again is a new, visible decision.
  h.click('model-target-source')
  assert.match(text(h.byId('model-section-summary')), /적용 대상: other/)
  assert.equal(h.byId('model-section-save').props.disabled, false)
})
test('a changed delegation method or spare model that no selected profile can take is an error, not a quiet no-op', async () => {
  const data = slotFixture()
  const names = data.profiles.map(row => row.name)
  const loaded = data.current_profile, away = names.find(name => name !== loaded)
  data.profiles.find(row => row.name === away).routing.enabled = false
  const h = harness({ data })
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
  h.click('model-target-none'); h.check(`model-target-${away}`, true)
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-targets')), /받을 수 있는 프로필이 적용 대상에 없습니다/)
  h.byId('model-section-save').props.onClick?.(); await h.flush()
  assert.deepEqual(h.calls, [], 'nothing is sent while the change has nowhere to go')
  h.check(`model-target-${loaded}`, true)
  assert.doesNotMatch(text(h.byId('model-section-targets')), /받을 수 있는 프로필이 적용 대상에 없습니다/)
  assert.equal(h.byId('model-section-save').props.disabled, false)
})

test('the whole-page save follows the same rules: no silent model copy, no membership change, zero targets is an error', async () => {
  const data = fixture(); data.profiles[1].native_delegation.backend = 'model-router'
  const h = harness({ data })
  h.check('routing-reenable-other', true)
  assert.doesNotMatch(text(h.byId('draft-reference-summary')), /다시 켜기/)
  h.click('global-save'); await h.flush()
  const untouched = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(untouched.model_targets, [])
  assert.deepEqual(untouched.routing_profiles, ['claire'], 'a ticked re-enable box is saved only by its own button')
  const g = harness({ data })
  g.input('model-main-model', 'edited-main'); g.click('model-target-none')
  assert.match(text(g.render()), /‘모델’ 섹션의 적용 대상이 0개입니다/)
  g.click('global-save'); await g.flush()
  assert.deepEqual(g.calls, [], 'an edited model with nowhere to go is refused, not reported as saved')
  assert.match(text(g.render()), /저장되지 않았습니다\. .*‘모델’ 섹션의 적용 대상이 0개입니다/)
  assert.doesNotMatch(text(g.render()), /적용 요청이 완료되었습니다/)
  g.check('model-target-claire', true)
  assert.match(text(g.byId('draft-reference-summary')), /대화 모델 적용 1개 \(claire\)/)
  g.click('global-save'); await g.flush()
  assert.deepEqual(g.calls.find(call => call.operation === 'preview').body.model_targets, ['claire'])
})

test('slot models are not copied by a hand-picked list while their cards are hidden; the profile summary names the allow-list', async () => {
  const data = slotFixture()
  for (const row of data.profiles) row.native_delegation.backend = 'model-router-profiles'
  data.profiles[1].native_delegation.profile_routes = { profiles: [{ name: 'default', description: '' }], default: 'default' }
  const h = harness({ data })
  assert.throws(() => h.byId('slot-design-follow'))
  h.click('model-target-none'); h.check('model-target-claire', true)
  const summary = text(h.byId('model-section-summary'))
  assert.doesNotMatch(summary, /작업 슬롯 모델/)
  assert.match(summary, /맡기는 방식: 전문 프로필에 맡기기/)
  assert.doesNotMatch(summary, /허용할 전문 프로필/, 'the allow-list belongs to its own section')
  h.click('profile-target-source')
  assert.match(text(h.byId('profile-section-summary')), /허용할 전문 프로필: default · 기본: default/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.equal(Object.hasOwn(h.calls[0].body.updates[0], 'profile_routes'), false)
  assert.equal(h.calls[0].body.updates[0].allow_profile_access, false)
  const store = h.calls.filter(call => call.operation === 'preview').at(-1).body
  assert.equal(store.save_scope, 'models')
  assert.deepEqual(store.routing_targets, [])
})

test('a status that gains slot fields under a mounted page renders without slot cards instead of failing', () => {
  const old = slotFixture(); delete old.slot_capabilities
  for (const row of old.profiles) delete row.slots
  const h = harness({ data: old })
  assert.throws(() => h.byId('slot-design-follow'))
  h.setData(slotFixture())
  assert.doesNotThrow(() => h.render())
  assert.throws(() => h.byId('slot-design-follow'), 'cards wait for a draft seeded by a reload')
})

test('a profile without slot support in a model mode keeps every target stored policy shape', async () => {
  const data = slotFixture(); delete data.slot_capabilities
  delete data.profiles[1].slots; data.profiles[1].native_delegation.slot_policy_supported = false
  data.profiles[0].native_delegation.policy_schema = 2
  data.profiles[0].native_delegation.slot_policy.design = { mode: 'custom', chain: [{ provider: 'own', model: 'own-slot-spare' }] }
  const h = harness({ data })
  assert.match(text(h.byId('slot-update-note')), /업데이트/)
  h.click('model-target-all')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  // The loaded profile cannot show per-slot spare models, so no target's stored policy is sent.
  for (const update of h.calls[0].body.updates) {
    for (const key of ['policy', 'slot_policy', 'allow_additional_cost']) assert.equal(Object.hasOwn(update, key), false)
  }
  const store = h.calls.filter(call => call.operation === 'preview').at(-1).body
  assert.equal(Object.hasOwn(store.routing, 'slots'), false)
})

test('a target that stops being editable between the click and the fresh status check blocks the whole save', async () => {
  const h = harness({ data: slotFixture() })
  h.select('slot-design-fallback-mode', 'custom')
  h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
  h.click('model-target-all')
  const changed = structuredClone(h.data()); changed.profiles[2].native_delegation.editable = false
  h.setStatusResponder(() => changed)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.equal(h.calls.some(call => call.operation === 'apply'), false)
  assert.match(text(h.byId('model-section-targets')), /저장되지 않았습니다\. 원본 또는 선택한 프로필의 설정이 바뀌었습니다/)
})

test('a body longer than one command line is staged in pieces and sent by reference', async () => {
  const h = harness({ data: slotFixture() })
  h.setResponder(operation => operation === 'stage' ? { staged: true } : operation === 'apply' ? { status: 'applied' } : { plan_id: 'big-plan', changes: [] })
  h.input('model-main-model', 'm'.repeat(17000) + '😀"\\')
  h.click('model-section-save'); await h.flush()
  const stages = h.calls.filter(c => c.operation === 'stage'), preview = h.calls.find(c => c.operation === 'preview')
  assert.ok(stages.length >= 2)
  assert.ok(stages.every(c => JSON.stringify(c.body).length <= 12000), 'each piece fits one command line')
  assert.deepEqual(stages.map(c => c.body.index), stages.map((_, index) => index))
  assert.ok(stages.every(c => c.body.id === stages[0].body.id && c.body.total === stages.length && /^[0-9a-f]{32}$/.test(c.body.id)))
  const text = stages.map(c => c.body.chunk).join('')
  assert.deepEqual(preview.body, { staged: { id: stages[0].body.id, total: stages.length, length: text.length } })
  assert.equal(JSON.parse(text).models.main.model, 'm'.repeat(17000) + '😀"\\')
  assert.deepEqual(h.calls.filter(c => c.operation === 'apply').map(c => c.body), [{ plan_id: 'big-plan' }])
})

test('a gateway switch during a staged transfer stops before any later piece or the request is sent', async () => {
  const h = harness({ data: slotFixture() })
  let pieces = 0
  h.setResponder(operation => {
    if (operation === 'stage') { pieces += 1; if (pieces === 1) h.host.getGateway = () => ({ request: async () => { throw new Error('sent to the new gateway') } }); return { staged: true } }
    return operation === 'apply' ? { status: 'applied' } : { plan_id: 'p', changes: [] }
  })
  h.input('model-main-model', 'm'.repeat(30000))
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(c => c.operation), ['stage'])
  assert.match(text(h.byId('model-section-targets')), /연결 또는 프로필이 바뀌어 전달을 멈췄습니다/)
})

test('a request too large even for staging is refused up front with the reason, before anything is sent', async () => {
  const h = harness({ data: slotFixture() })
  h.input('model-main-model', 'm'.repeat(410000))
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls, [])
  assert.match(text(h.byId('model-section-targets')), /저장되지 않았습니다\. 한 번에 저장하기에는 내용이 너무 큽니다\. 적용 대상 프로필을 줄여/)
})

test('the restart reminder shows only before any slot setting was ever saved', () => {
  const h = harness({ data: slotFixture() })
  assert.match(text(h.byId('slot-first-save-note')), /다시 시작하지 않은 Hermes 창이나 게이트웨이/)
  const stored = slotFixture(); stored.profiles[0].slots.stored = ['design']
  assert.throws(() => harness({ data: stored }).byId('slot-first-save-note'))
  const spare = slotFixture(); spare.profiles[2].native_delegation.policy_schema = 2
  assert.throws(() => harness({ data: spare }).byId('slot-first-save-note'))
})

test('a failed status read: error screen for an ordinary refresh; after a save the outcome stays locked until a retry succeeds', async () => {
  // Ordinary failed refresh with cached data: the error screen, nothing editable or saveable.
  const plain = harness()
  plain.setQueryError(true); plain.render()
  assert.throws(() => plain.byId('model-main-model'))
  assert.throws(() => plain.byId('global-save'))
  assert.match(text(plain.render()), /설정 서비스를 사용할 수 없습니다/)
  // After a confirmed save whose automatic reload fails.
  const h = harness()
  h.input('model-main-model', 'saved-main')
  h.setRefetcher(async () => { h.setQueryError(true); return { data: h.data(), error: new Error('refresh failed') } })
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.map(c => c.operation), ['preview', 'apply'])
  assert.match(text(h.render()), /자동으로 다시 불러오지 못했습니다/)
  assert.equal(h.byId('model-main-model').props.disabled, true)
  h.setRefetcher(async () => { h.setQueryError(false); return { data: h.data() } })
  h.clickLabel('실제 상태 확인 후 편집 재개'); await h.flush()
  assert.equal(h.byId('model-main-model').props.disabled, false)
})

// ---- v0.12.0: the method and the profile delegation are two sections over one draft ----
const backendOptions = h => {
  const select = [...walk(h.render())].find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'native-delegation-backend'))
  return [...walk(select)].filter(node => node.type === 'SelectItem').map(node => [node.props.value, text(node), node.props.disabled === true])
}

test('the Hermes default method is no longer offered; a profile stored on it stays as it is and is never copied', async () => {
  const h = harness({ data: nativeBatchFixture() })
  assert.equal(h.selectValue('native-delegation-backend'), 'default')
  assert.deepEqual(backendOptions(h).map(([value, , disabled]) => [value, disabled]), [['default', true], ['model-router', false], ['model-router-auto', false], ['model-router-profiles', false]])
  assert.match(backendOptions(h)[0][1], /이전 방식/)
  assert.throws(() => h.byId('native-backend-revert'))
  assert.match(text(h.byId('native-default-explanation')), /더 이상 고를 수 없지만, 저장된 값은 그대로/)
  // Widening the targets copies the role models, never the stored 'default' method.
  h.input('model-main-model', 'copied-main'); h.click('model-target-all')
  assert.doesNotMatch(text(h.byId('model-section-summary')), /맡기는 방식/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  assert.deepEqual(h.calls[0].body.model_targets, ['default', 'claire', 'other'])
  assert.equal(JSON.stringify(h.calls).includes('"backend"'), false)
  // Choosing a plugin method is an explicit change. 'default' stays listed but disabled, a pick of it
  // is ignored, and going back is the explicit revert button.
  const g = harness({ data: nativeBatchFixture() })
  g.select('native-delegation-backend', 'model-router')
  assert.deepEqual(backendOptions(g)[0], ['default', backendOptions(g)[0][1], true])
  assert.throws(() => g.byId('native-default-explanation'))
  g.select('native-delegation-backend', 'default')
  assert.equal(g.selectValue('native-delegation-backend'), 'model-router', 'a pick of default is ignored')
  g.click('native-backend-revert')
  assert.equal(g.selectValue('native-delegation-backend'), 'default')
  assert.equal(g.byId('model-section-save').props.disabled, true, 'back on the stored value there is nothing to save')
  assert.deepEqual(g.calls, [])
})

test('a model copy never rewrites another profile stored on default or an unlisted method', async () => {
  const data = nativeBatchFixture()
  data.profiles[1].native_delegation.backend = 'model-router'
  data.profiles[0].native_delegation.backend = 'default'
  data.profiles[2].native_delegation.backend = 'advanced-custom'
  const h = harness({ data })
  // The method is left untouched; the hand-picked list is the copy intent.
  h.input('model-main-model', 'copied-main'); h.click('model-target-all')
  assert.match(text(h.byId('model-section-skipped')), /default, other/)
  assert.match(text(h.byId('model-section-targets')), /‘기본 위임 모델 사용 \(이전 방식\)’ 방식으로 저장되어 있어 그대로 둡니다/)
  assert.match(text(h.byId('model-section-targets')), /‘별도 고급 설정’ 방식으로 저장되어 있어 그대로 둡니다/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), CHAIN)
  assert.deepEqual(h.calls[0].body.updates.map(update => [update.profile, update.backend]), [['claire', 'model-router']])
  assert.deepEqual(h.calls[4].body.model_targets, ['default', 'claire', 'other'], 'the models are still copied')
})

test('the profile section is read-only unless the loaded profile is stored on a profile method', () => {
  const data = slotFixture()
  data.profiles[2].native_delegation.backend = 'model-router-profiles'
  data.profiles[1].native_delegation.profile_routes = { profiles: [{ name: 'other', description: 'kept' }], default: null }
  const h = harness({ data })
  const note = text(h.byId('profile-delegation-readonly'))
  assert.match(note, /claire/); assert.match(note, /작업 종류에 맞는 슬롯 모델 사용/); assert.match(note, /저장된 허용 프로필: other/)
  for (const id of ['native-profile-other', 'native-profile-access-consent', 'profile-section-save', 'profile-section-targets']) assert.throws(() => h.byId(id), id)
  // Choosing a profile method in the model section is not enough: it must be saved first.
  h.select('native-delegation-backend', 'model-router-profiles')
  assert.ok(h.byId('profile-delegation-readonly'))
  h.selectProfile('other')
  assert.throws(() => h.byId('profile-delegation-readonly'))
  assert.equal(h.selectValue('native-profile-default'), '__parent__')
  assert.deepEqual(h.selected('profile-target-'), ['other'])
  assert.deepEqual(h.calls, [])
})

test('the two delegation saves split one draft: each sends its own part and every target keeps its stored other part', async () => {
  const data = profileFixture('model-router-auto')
  data.profiles.forEach((row, index) => { row.native_delegation.profile_routes = { profiles: [{ name: 'other', description: `Own ${index}` }], default: null } })
  const editBoth = h => {
    h.select('slot-design-fallback-mode', 'custom'); h.input('slot-design-spare-provider-0', 'spare-service'); h.input('slot-design-spare-model-0', 'spare/model')
    h.check('native-profile-default', true); h.check('native-profile-access-consent', true)
    h.click('model-target-all'); h.click('profile-target-all'); h.check('native-profile-access-consent', true)
  }
  const h = harness({ data }); editBoth(h)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.slice(0, 1).map(call => call.operation), ['delegation-preview'])
  for (const update of h.calls[0].body.updates) {
    const stored = data.profiles.find(row => row.name === update.profile).native_delegation
    assert.equal(update.backend, 'model-router-auto')
    assert.deepEqual(update.slot_policy.design, { mode: 'custom', chain: [{ provider: 'spare-service', model: 'spare/model' }] })
    assert.equal(Object.hasOwn(update, 'profile_routes'), false, 'the model save leaves each stored allow-list to the writer')
    assert.equal(update.allow_profile_access, false)
  }
  assert.match(text(h.render()), /자동으로 다시 불러오지 않았습니다/, 'the unsaved profile edit is not reloaded away')
  assert.equal(h.byId('native-profile-default').props.checked, true)

  const g = harness({ data }); editBoth(g)
  g.setResponder(nativeReply); g.click('profile-section-save'); await g.flush()
  assert.deepEqual(g.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.equal(JSON.stringify(g.calls[0].body).includes('spare/model'), false, 'the profile save never carries the spare-model edit')
  for (const update of g.calls[0].body.updates) {
    const stored = data.profiles.find(row => row.name === update.profile).native_delegation
    assert.equal(update.backend, stored.backend)
    for (const key of ['policy', 'slot_policy', 'allow_additional_cost']) assert.equal(Object.hasOwn(update, key), false)
    assert.deepEqual(update.profile_routes.profiles.map(entry => entry.name), ['other', 'default'])
    assert.equal(update.allow_profile_access, true)
  }
  assert.match(text(g.render()), /자동으로 다시 불러오지 않았습니다/, 'the unsaved method edit is not reloaded away')
  assert.equal(g.byId('slot-design-spare-model-0').props.value, 'spare/model')
})

test('a confirmed profile-only save reloads by itself; the model section dirty state is untouched by it', async () => {
  const h = harness({ data: profileFixture() })
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.check('native-profile-other', true); h.check('native-profile-access-consent', true)
  assert.equal(h.byId('model-section-save').props.disabled, true, 'a profile edit is not a model-section change')
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.doesNotMatch(text(h.render()), /자동으로 다시 불러오지 않았습니다/)
  assert.equal(h.byId('native-profile-other').props.disabled, false, 'reloaded and editable again')
  assert.deepEqual(h.selected('native-profile-'), [], 'the draft was replaced by the reloaded state')
})

test('a profile target that cannot take the allow-list is disabled, skipped by select-all, and blocks the save by name if it changes', () => {
  const data = profileFixture(); data.profiles[2].native_delegation.backend = 'model-router'
  const h = harness({ data })
  assert.equal(h.byId('profile-target-other').props.disabled, true)
  assert.match(text(h.byId('profile-section-targets')), /전문 프로필에 맡기는 방식이 아닙니다\(현재: 작업 종류에 맞는 슬롯 모델 사용\)/)
  h.click('profile-target-all')
  assert.deepEqual(h.selected('profile-target-'), ['claire', 'default'])
  assert.equal(h.byId('profile-section-save').props.disabled, false)
  const next = structuredClone(h.data()); next.profiles[0].native_delegation.backend = 'model-router'
  h.setData(next); h.render()
  assert.equal(h.byId('profile-section-save').props.disabled, true)
  assert.match(text(h.byId('profile-section-targets')), /다음 프로필에는 전문 프로필 설정을 저장할 수 없습니다\. 적용 대상에서 빼 주세요\. default:/)
  h.byId('profile-section-save').props.onClick(); h.render()
  assert.deepEqual(h.calls, [])
})

test('a save that does not send an edited field never counts it as saved (no reload over it)', async () => {
  // (a) An automatic-mode spare edit, then the draft switched to the model-only method: the save sends the
  // model-only spare models, not the automatic ones.
  const a = harness({ data: autoFixture() })
  a.select('native-delegation-backend', 'model-router-auto')
  a.select('slot-design-fallback-mode', 'custom'); a.input('slot-design-spare-provider-0', 'auto-service'); a.input('slot-design-spare-model-0', 'auto-model')
  a.select('native-delegation-backend', 'model-router')
  a.setResponder(nativeReply); a.click('model-section-save'); await a.flush()
  assert.equal(JSON.stringify(a.calls[0].body).includes('auto-model'), false)
  assert.match(text(a.render()), /자동으로 다시 불러오지 않았습니다/)
  // (c) A profile edit stays unsaved even after a refreshed status makes the loaded profile read-only.
  const c = harness({ data: profileFixture() })
  c.check('native-profile-other', true)
  const readOnly = structuredClone(c.data()); readOnly.profiles.find(row => row.name === 'claire').native_delegation.editable = false
  c.setData(readOnly); c.render()
  c.input('model-main-model', 'unrelated-main')
  c.setResponder(nativeReply); c.click('model-section-save'); await c.flush()
  assert.deepEqual(c.calls.map(call => call.operation), ['preview', 'apply'])
  assert.match(text(c.render()), /자동으로 다시 불러오지 않았습니다/, 'the unsaved allow-list edit is still counted')
})

test('a model-only profile that still lists a deleted specialist can switch to a profile method, then remove it', async () => {
  const data = nativeBatchFixture()
  const claire = data.profiles.find(row => row.name === 'claire').native_delegation
  claire.backend = 'model-router'
  claire.profile_routes = { profiles: [{ name: 'ghost', description: 'deleted' }], default: 'ghost' }
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router-profiles')
  assert.equal(h.byId('model-section-save').props.disabled, false, 'the untouched stored allow-list does not block the method save')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  const update = h.calls[0].body.updates[0]
  assert.equal(update.backend, 'model-router-profiles')
  assert.equal(Object.hasOwn(update, 'profile_routes'), false)
  // Once stored on the profile method, the profile section offers removing the missing name.
  claire.backend = 'model-router-profiles'; claire.warnings = ['profile_target_missing_remove_from_allowlist']
  const g = harness({ data })
  assert.match(text(g.byId('profile-delegation-settings')), /더 이상 없는 프로필: ghost/)
  assert.equal(g.byId('profile-section-save').props.disabled, true)
  g.clickLabel('허용 목록에서 제거')
  g.setResponder(nativeReply); g.click('profile-section-save'); await g.flush()
  assert.deepEqual(g.calls[0].body.updates[0].profile_routes, { profiles: [], default: null })
})

test('a profile copy from an automatic source keeps a profile-only target default', async () => {
  const data = profileFixture('model-router-auto')
  data.profiles[0].native_delegation.backend = 'model-router-profiles'
  data.profiles[0].native_delegation.profile_routes = { profiles: [{ name: 'other', description: 'own' }], default: 'other' }
  data.profiles[1].native_delegation.profile_routes = { profiles: [{ name: 'other', description: '' }], default: null }
  const h = harness({ data })
  assert.throws(() => h.selectValue('native-profile-default'), 'an automatic source has no default control')
  h.check('native-profile-claire', true)
  h.click('profile-target-all'); h.check('native-profile-access-consent', true)
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  const byName = Object.fromEntries(h.calls[0].body.updates.map(update => [update.profile, update]))
  assert.equal(byName.default.profile_routes.default, 'other', 'the hidden default is not cleared')
  assert.deepEqual(byName.default.profile_routes.profiles.map(entry => entry.name), ['other', 'claire'])
  assert.equal(byName.default.profile_routes.profiles[0].description, 'own', 'an untouched description stays the target own')
})

test('a default profile sent to no target is not counted as saved; sent to the loaded profile it is', async () => {
  const setup = () => {
    const data = profileFixture()
    const [defaultRow, claire] = data.profiles
    claire.native_delegation.profile_routes = { profiles: [{ name: 'other', description: '' }], default: null }
    defaultRow.native_delegation.backend = 'model-router-auto'
    defaultRow.native_delegation.profile_routes = { profiles: [{ name: 'other', description: '' }], default: null }
    return data
  }
  const h = harness({ data: setup() })
  h.select('native-profile-default', 'other')
  h.click('profile-target-none'); h.check('profile-target-default', true); h.check('native-profile-access-consent', true)
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.deepEqual(h.calls[0].body.updates.map(update => [update.profile, update.profile_routes.default]), [['default', null]], 'the automatic target keeps its own default')
  assert.match(text(h.render()), /자동으로 다시 불러오지 않았습니다/)
  assert.equal(h.selectValue('native-profile-default'), 'other', 'the unsaved default edit is kept')
  // Saved to the loaded profile itself, the same edit is covered and the page reloads.
  const g = harness({ data: setup() })
  g.select('native-profile-default', 'other')
  g.click('profile-target-all'); g.check('native-profile-access-consent', true)
  g.setResponder(nativeReply); g.click('profile-section-save'); await g.flush()
  assert.deepEqual(g.calls[0].body.updates.map(update => [update.profile, update.profile_routes.default]), [['default', null], ['claire', 'other'], ['other', 'other']])
  assert.doesNotMatch(text(g.render()), /자동으로 다시 불러오지 않았습니다/)
})

test('a slot edit stays unsaved when a refresh makes slots read-only and a model-only save follows', async () => {
  const h = harness({ data: slotFixture() })
  h.input('slot-design-model', 'edited-design')
  const blocked = structuredClone(h.data()); blocked.slot_capabilities.blocking_profiles = ['other']
  h.setData(blocked); h.render()
  assert.equal(h.byId('slot-design-model').props.disabled, true)
  h.input('model-main-model', 'unrelated-main')
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  assert.equal(h.calls[0].body.save_scope, 'models')
  assert.equal(Object.hasOwn(h.calls[0].body.routing ?? {}, 'slots'), false)
  assert.match(text(h.render()), /자동으로 다시 불러오지 않았습니다/)
  assert.equal(h.byId('slot-design-model').props.value, 'edited-design', 'the slot edit was not reloaded away')
})

test('a profile-save target that disappears blocks the save by name and resets the consent', async () => {
  const h = harness({ data: profileFixture() })
  h.check('native-profile-other', true)
  h.click('profile-target-all'); h.check('native-profile-access-consent', true)
  const shrunk = structuredClone(h.data()); shrunk.profiles = shrunk.profiles.filter(row => row.name !== 'default')
  h.setData(shrunk); h.render()
  assert.match(text(h.byId('profile-section-targets')), /더 이상 찾을 수 없어 전문 프로필 설정을 저장할 수 없습니다\. 적용 대상에서 빼 주세요\. default/)
  assert.equal(h.byId('profile-section-save').props.disabled, true)
  assert.equal(h.byId('native-profile-access-consent').props.checked, false, 'consent given for the old list is reset')
  assert.equal(h.byId('profile-target-default').props.checked, true, 'the missing name stays visible until unticked')
  h.check('profile-target-default', false)
  assert.throws(() => h.byId('profile-target-default'))
  h.check('native-profile-access-consent', true)
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls[0].body.updates.map(update => update.profile), ['claire', 'other'])
})

test('a value changed elsewhere at the same revision is a conflict, never an edit to write back', async () => {
  const h = harness({ data: nativeBatchFixture() })
  assert.equal(h.byId('model-section-save').props.disabled, true)
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'claire').models.main.model = 'externally-selected'
  h.setData(refreshed); h.render()
  assert.match(text(h.byId('live-drift-alert')), /다른 곳에서 claire 프로필의 대화·작업 모델 값이 바뀌었습니다.*상태 새로고침/)
  assert.equal(h.byId('model-section-save').props.disabled, true, 'no edit: nothing to write')
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.deepEqual(h.calls, [], 'the old model is never sent back')
  // With a real edit the conflict blocks the model save by name, too.
  h.input('model-delegation-model', 'my-edit')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('model-section-targets')), /대화·작업 모델 값이 바뀌었습니다/)
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.deepEqual(h.calls, [])
})

test('other live drifts block the saves that would write them: spare models, routing on/off', async () => {
  const data = nativeBatchFixture()
  for (const row of data.profiles) row.fallbacks = { native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null } }
  const h = harness({ data })
  const fallback = structuredClone(h.data())
  const claire = fallback.profiles.find(row => row.name === 'claire')
  claire.fallbacks.native.enabled = true; claire.fallbacks.native.chain = [{ provider: 'elsewhere', model: 'external-spare' }]
  h.setData(fallback); h.render()
  assert.match(text(h.byId('live-drift-alert')), /대화 예비 모델/)
  assert.equal(h.byId('global-save').props.disabled, true)
  const g = harness({ data: nativeBatchFixture() })
  const toggled = structuredClone(g.data())
  toggled.profiles.find(row => row.name === 'other').routing.enabled = false
  g.setData(toggled); g.render()
  assert.match(text(g.byId('live-drift-alert')), /작업 라우팅 사용 여부/)
  assert.throws(() => g.byId('routing-reenable'), 'a profile switched off elsewhere is not offered for re-enabling from stale data')
  g.input('model-main-model', 'edited')
  assert.equal(g.byId('global-save').props.disabled, true)
  assert.equal(g.byId('model-section-save').props.disabled, true)
  assert.deepEqual(g.calls, [])
})

test('a profile-save target that vanishes only in the fresh pre-apply status is named, unconsented and blocked', async () => {
  const h = harness({ data: profileFixture() })
  h.check('native-profile-other', true)
  h.click('profile-target-all'); h.check('native-profile-access-consent', true)
  h.setStatusResponder(() => { const fresh = structuredClone(h.data()); fresh.profiles = fresh.profiles.filter(row => row.name !== 'default'); return fresh })
  h.setResponder(nativeReply); h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'status'], 'never applied')
  const section = text(h.byId('profile-section-targets'))
  assert.match(section, /더 이상 찾을 수 없어 저장하지 않았습니다\. 적용 대상에서 빼 주세요\. default/)
  assert.match(section, /더 이상 찾을 수 없어 전문 프로필 설정을 저장할 수 없습니다\. 적용 대상에서 빼 주세요\. default/)
  assert.equal(h.byId('native-profile-access-consent').props.checked, false)
  assert.equal(h.byId('profile-section-save').props.disabled, true)
  assert.match(section, /최신 상태에서 이 프로필을 찾을 수 없습니다/)
  assert.equal(h.byId('profile-target-default').props.checked, true)
  h.check('profile-target-default', false)
  h.check('native-profile-access-consent', true)
  assert.equal(h.byId('profile-section-save').props.disabled, false)
  h.setStatusResponder(() => h.data())
  h.click('profile-section-save'); await h.flush()
  assert.deepEqual(h.calls.slice(2).map(call => call.operation), ['delegation-preview', 'status', 'apply'])
  assert.deepEqual(h.calls[2].body.updates.map(update => update.profile), ['claire', 'other'])
})

const conflictReply = code => (operation, body) => operation === 'preview' || operation === 'fallback-preview'
  ? { error: 'ExternalChange', conflict: { profile: code.split(':')[0], field: code.split(':')[1] }, message: '작업이 완료되지 않았습니다. 상태를 확인한 후 다시 미리보기 하세요.' } : nativeReply(operation, body)

test('every store body carries the values frozen at load; the service refusal becomes a blocking conflict', async () => {
  const data = nativeBatchFixture()
  const h = harness({ data })
  const frozenMain = structuredClone(data.profiles.find(row => row.name === 'other').actual_models)
  h.input('model-delegation-model', 'my-delegation-edit'); h.click('model-target-all')
  // `other` changed its own config after the page loaded; the page only checks the loaded profile.
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'other').actual_models.main.model = 'changed-elsewhere'
  h.setData(refreshed); h.render()
  h.setResponder(conflictReply('other:actual_models.main'))
  h.click('global-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview'], 'refused before any apply')
  const expected = Object.fromEntries(h.calls[0].body.expected.map(item => [item.profile, item]))
  assert.deepEqual(expected.other.actual_models, frozenMain, 'the frozen value, not the refreshed one')
  assert.deepEqual(Object.keys(expected).sort(), ['claire', 'default', 'other'])
  for (const item of Object.values(expected)) assert.deepEqual(Object.keys(item).sort(), ['actual_models', 'models', 'profile', 'routing'])
  const page = text(h.render())
  assert.match(page, /다른 곳에서 변경됨 — 다시 불러오세요\. other 프로필의 실제 모델 설정\(대화 모델\) 값이/)
  assert.equal(h.byId('global-save').props.disabled, true, 'blocked until a reload')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.match(text(h.byId('live-drift-alert')), /other 프로필의 실제 모델 설정\(대화 모델\)/)
})

test('a loaded profile whose actual model changed elsewhere blocks a delegation-model edit early', () => {
  const h = harness({ data: nativeBatchFixture() })
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'claire').actual_models.main.model = 'changed-elsewhere'
  h.setData(refreshed); h.render()
  h.input('model-delegation-model', 'my-delegation-edit')
  assert.equal(h.byId('model-section-save').props.disabled, true)
  assert.equal(h.byId('global-save').props.disabled, true)
  assert.match(text(h.byId('live-drift-alert')), /claire 프로필의 대화·작업 모델/)
})

test('the follow-up store write of a combined save carries the frozen expectations, and a refusal stops it', async () => {
  const data = nativeBatchFixture()
  const frozen = structuredClone(data.profiles.find(row => row.name === 'claire').actual_models)
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router')
  h.input('model-delegation-model', 'my-delegation-edit')
  // The fresh status read before the first write reports a new main model for claire.
  h.setStatusResponder(() => { const fresh = structuredClone(h.data()); fresh.profiles.find(row => row.name === 'claire').actual_models.main.model = 'changed-elsewhere'; return fresh })
  let previews = 0
  h.setResponder((operation, body) => operation === 'preview' && ++previews === 2
    ? { error: 'ExternalChange', conflict: { profile: 'claire', field: 'actual_models.main' }, message: 'x' } : nativeReply(operation, body))
  h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['delegation-preview', 'preview', 'status', 'apply', 'preview'], 'no second apply')
  const [first, second] = h.calls.filter(call => call.operation === 'preview').map(call => call.body)
  assert.deepEqual(second.expected, first.expected, 'not re-read after the first write')
  assert.deepEqual(second.expected.find(item => item.profile === 'claire').actual_models, frozen)
  assert.match(text(h.render()), /맡기는 방식과 예비 모델’: 저장했습니다\. ‘모델 변경’: 저장하지 않았습니다\..*다른 곳에서 변경됨 — 다시 불러오세요\. claire 프로필의 실제 모델 설정\(대화 모델\)/)
})

test('a model-save callback kept from an earlier render does not dispatch once drift disables saving', async () => {
  const h = harness({ data: nativeBatchFixture() })
  h.input('model-main-model', 'my-edit')
  const retained = h.byId('model-section-save').props.onClick
  const retainedAll = h.byId('global-save').props.onClick
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'claire').actual_models.delegation.model = 'changed-elsewhere'
  h.setData(refreshed); h.render()
  assert.equal(h.byId('model-section-save').props.disabled, true)
  h.setResponder(nativeReply)
  retained(); retainedAll(); await h.flush()
  assert.deepEqual(h.calls, [])
})

test('a profile discovered after load is frozen when first seen, so its edit is saved, guarded and never dropped', async () => {
  const h = harness({ data: nativeBatchFixture() })
  const grown = structuredClone(h.data())
  const fourth = structuredClone(grown.profiles.find(row => row.name === 'other')); fourth.name = 'fourth'
  fourth.native_delegation.digest = 'd'.repeat(64)
  grown.profiles.push(fourth)
  h.setData(grown); h.render(); h.render()
  h.selectProfile('fourth')
  h.input('model-main-model', 'fourth-edit')
  assert.equal(h.byId('model-section-save').props.disabled, false)
  h.setResponder(nativeReply); h.click('global-save'); await h.flush()
  const body = h.calls[0].body
  assert.deepEqual(body.model_targets, ['fourth'])
  assert.equal(body.models.main.model, 'fourth-edit')
  assert.deepEqual(body.expected.find(item => item.profile === 'fourth').actual_models, fourth.actual_models)
})

test('switching the loaded profile keeps a vanished ticked profile target listed and blocked by name', () => {
  const h = harness({ data: profileFixture() })
  h.click('profile-target-all')
  const shrunk = structuredClone(h.data()); shrunk.profiles = shrunk.profiles.filter(row => row.name !== 'default')
  h.setData(shrunk); h.render()
  h.selectProfile('other')
  h.check('native-profile-claire', true)
  assert.equal(h.byId('profile-target-default').props.checked, true)
  assert.match(text(h.byId('profile-section-targets')), /더 이상 찾을 수 없어 전문 프로필 설정을 저장할 수 없습니다\. 적용 대상에서 빼 주세요\. default/)
  assert.equal(h.byId('profile-section-save').props.disabled, true)
})

test('a routing on/off change elsewhere names the profile that changed', () => {
  const h = harness({ data: nativeBatchFixture() })
  const toggled = structuredClone(h.data())
  toggled.profiles.find(row => row.name === 'other').routing.enabled = false
  h.setData(toggled); h.render()
  const alert = text(h.byId('live-drift-alert'))
  assert.match(alert, /other 프로필의 작업 라우팅 사용 여부/)
  assert.doesNotMatch(alert, /claire 프로필의 작업 라우팅 사용 여부/)
})

test('a ticked re-enable stays an unsaved edit and blocks by name when its profile drops out of a refresh', async () => {
  const data = nativeBatchFixture(); data.profiles.find(row => row.name === 'other').routing.enabled = false
  const h = harness({ data })
  h.check('routing-reenable-other', true)
  h.input('model-main-model', 'main-edit')
  const fewer = structuredClone(h.data()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  h.setData(fewer); h.render()
  assert.equal(h.byId('routing-reenable-other').props.checked, true, 'still listed and ticked')
  assert.match(text(h.byId('routing-reenable-missing')), /더 이상 찾을 수 없어 저장하지 않습니다.*other/)
  assert.equal(h.byId('routing-reenable-save').props.disabled, true)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls.map(call => call.operation), ['preview', 'apply'])
  assert.equal(h.calls[0].body.routing_profiles.includes('other'), false)
  assert.match(text(h.render()), /자동으로 다시 불러오지 않았습니다/, 'the re-enable tick is not reloaded away')
  assert.equal(h.byId('routing-reenable-other').props.checked, true)
  // Before any save, unticking it is the explicit way to drop the vanished name.
  const g = harness({ data })
  g.check('routing-reenable-other', true)
  g.setData(fewer); g.render()
  g.check('routing-reenable-other', false)
  assert.throws(() => g.byId('routing-reenable-other'))
})

test('a routing skill switched off in a profile config is drift for that profile', () => {
  const h = harness({ data: nativeBatchFixture() })
  const refreshed = structuredClone(h.data())
  refreshed.profiles.find(row => row.name === 'other').drift = ['skills.disabled']
  h.setData(refreshed); h.render()
  assert.match(text(h.byId('live-drift-alert')), /other 프로필의 작업 라우팅 사용 여부/)
  assert.equal(h.byId('global-save').props.disabled, true)
})

test('more than 64 profiles still save: expected covers every profile without a fixed cap', async () => {
  const data = nativeBatchFixture()
  const template = data.profiles.find(row => row.name === 'other')
  for (let index = 1; index <= 67; index++) {
    const row = structuredClone(template); row.name = `p${index}`
    row.native_delegation.digest = index.toString(16).padStart(64, 'e')
    data.profiles.push(row)
  }
  const h = harness({ data })
  h.input('model-main-model', 'main-edit')
  assert.equal(h.byId('global-save').props.disabled, false)
  h.setResponder((operation, body) => operation === 'stage' ? { staged: true } : nativeReply(operation, body))
  h.click('global-save'); await h.flush()
  const stages = h.calls.filter(call => call.operation === 'stage')
  assert.deepEqual(h.calls.filter(call => call.operation !== 'stage').map(call => call.operation), ['preview', 'apply'], 'sent (staged by size) and applied')
  const body = JSON.parse(stages.sort((a, b) => a.body.index - b.body.index).map(call => call.body.chunk).join(''))
  const expected = body.expected
  assert.equal(expected.length, 70)
  assert.ok(expected.every(item => item.routing && typeof item.routing.skill_enabled === 'boolean'))
})

test('a profile whose routing skill is off stays off through an unrelated save, and only an explicit tick re-enables it', async () => {
  const data = nativeBatchFixture()
  data.profiles.find(row => row.name === 'other').drift = ['skills.disabled']  // canonical on, skill off
  const h = harness({ data })
  assert.equal(h.byId('routing-reenable-other').props.checked, false, 'offered for an explicit re-enable')
  h.input('model-main-model', 'main-edit')
  h.setResponder(nativeReply); h.click('global-save'); await h.flush()
  const body = h.calls[0].body
  assert.equal(Object.hasOwn(body, 'reenable_profiles'), false, 'an unrelated save never asks to re-enable')
  assert.equal(body.expected.find(item => item.profile === 'other').routing.skill_enabled, false)
  const g = harness({ data })
  g.check('routing-reenable-other', true)
  g.setResponder(nativeReply); g.click('routing-reenable-save'); await g.flush()
  const reenable = g.calls[0].body
  assert.deepEqual(reenable.reenable_profiles, ['other'])
  assert.ok(reenable.routing_profiles.includes('other'))
})

test('a profile whose routing skill is off takes the model copy but not the native method', async () => {
  const data = nativeBatchFixture()
  data.profiles.find(row => row.name === 'other').drift = ['skills.disabled']  // canonical on, skill off
  const h = harness({ data })
  h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
  assert.match(text(h.byId('model-section-targets')), /이 프로필의 작업 분담이 꺼져 있습니다/)
  h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
  assert.deepEqual(h.calls[0].body.updates.map(row => row.profile), ['default', 'claire'], 'never sent to the native method batch')
  const store = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(store.model_targets, ['default', 'claire', 'other'], 'its model-only copy is kept')
  assert.equal(Object.hasOwn(store, 'reenable_profiles'), false)
})

test('an explicit reload keeps a vanished re-enable tick listed and blocking until it is unticked', async () => {
  const data = nativeBatchFixture(); data.profiles.find(row => row.name === 'other').routing.enabled = false
  const h = harness({ data })
  h.check('routing-reenable-other', true)
  const fewer = structuredClone(h.data()); fewer.profiles = fewer.profiles.filter(row => row.name !== 'other')
  h.setData(fewer)
  h.clickLabel('상태 새로고침'); await h.flush()
  assert.equal(h.byId('routing-reenable-other').props.checked, true, 'still listed and ticked after the reload')
  assert.match(text(h.byId('routing-reenable-missing')), /other/)
  assert.equal(h.byId('routing-reenable-save').props.disabled, true)
  h.check('routing-reenable-other', false)
  assert.throws(() => h.byId('routing-reenable-other'))
  // A tick on a profile that is still off survives the reload; one turned on elsewhere is dropped.
  const g = harness({ data })
  g.check('routing-reenable-other', true)
  g.clickLabel('상태 새로고침'); await g.flush()
  assert.equal(g.byId('routing-reenable-other').props.checked, true)
  const on = structuredClone(g.data()); on.profiles.find(row => row.name === 'other').routing.enabled = true
  g.setData(on); g.clickLabel('상태 새로고침'); await g.flush()
  assert.throws(() => g.byId('routing-reenable-other'))
})

for (const [canonical, skill] of [[true, true], [true, false], [false, true], [false, false]]) {
  test(`native method eligibility needs both switches on (canonical ${canonical ? 'on' : 'off'}, skill ${skill ? 'on' : 'off'}); the model copy always goes`, async () => {
    const data = nativeBatchFixture()
    const other = data.profiles.find(row => row.name === 'other')
    other.routing.enabled = canonical
    // The status reports a skills.disabled drift when the skill's switch differs from the canonical flag.
    other.drift = canonical === skill ? [] : ['skills.disabled']
    const h = harness({ data })
    h.select('native-delegation-backend', 'model-router'); h.click('model-target-all')
    h.setResponder(nativeReply); h.click('model-section-save'); await h.flush()
    const batch = h.calls.find(call => call.operation === 'delegation-preview').body.updates.map(row => row.profile)
    assert.equal(batch.includes('other'), canonical && skill)
    const store = h.calls.find(call => call.operation === 'preview').body
    assert.ok(store.model_targets.includes('other'), 'the model copy is never lost')
    assert.equal(store.routing_profiles.includes('other'), canonical, 'membership stays as stored')
  })
}
