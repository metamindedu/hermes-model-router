import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Model selection UX: the host catalog menu drives the existing draft only.
// Synthetic hooks, transport and catalog; no native profile, settings or
// provider request is made by this file.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const service = readFileSync(new URL('../model_router/service.py', import.meta.url), 'utf8')
const MENU_SDK = { ModelCatalogMenu: 'ModelCatalogMenu', ModelMenuCloseContext: { Provider: 'ModelMenuClose' }, DropdownMenu: 'DropdownMenu',
  DropdownMenuContent: 'DropdownMenuContent', DropdownMenuTrigger: 'DropdownMenuTrigger' }
const DIALOG_SDK = { Dialog: 'Dialog', DialogContent: 'DialogContent', DialogHeader: 'DialogHeader', DialogTitle: 'DialogTitle', DialogDescription: 'DialogDescription', DialogFooter: 'DialogFooter' }
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const models = {
  main: route('openai-codex', 'gpt-6-astra-900k', 'medium'),
  delegation: route('openai-codex', 'gpt-6-luna-900k', 'max'),
  compression: route('openai-codex', 'gpt-6-luna-900k', 'medium'),
  title: route('openai-codex', 'gpt-6-luna', 'none')
}
const routing = { enabled: true, heavy: { follow: 'custom', custom: route('operator', 'independent-heavy', 'high') }, light: { follow: 'delegation', custom: null },
  fallback: { enabled: false, heavy: null, light: null } }
const slotIds = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use']
const slotTiers = Object.fromEntries(slotIds.map(id => [id, ['design', 'verify-complex'].includes(id) ? 'heavy' : 'light']))
const offSlots = () => Object.fromEntries(slotIds.map(id => [id, { mode: 'off', chain: [] }]))
const declarations = () => Object.fromEntries(slotIds.map(id => [id, slotTiers[id] === 'heavy'
  ? { follow: 'custom', custom: route('operator', 'independent-heavy', 'high') } : { follow: 'delegation', custom: null }]))
const fixture = () => ({ revision: 7, current_profile: 'claire', recent_apply: null,
  readiness_context: { schema: 1, base_identity: 'd'.repeat(64), source_profile: 'claire', release: null },
  slot_capabilities: { schema: 1, slots: slotIds, tiers: slotTiers, purposes: {}, follows: ['main', 'delegation', 'custom'], blocking_profiles: [] },
  profiles: ['default', 'claire', 'other'].map(name => ({ name, models: structuredClone(models), actual_models: structuredClone(models),
    routing: { ...structuredClone(routing), enabled: name === 'claire' }, drift: [],
    slots: { schema: 1, capable: true, stored: [], declarations: declarations() },
    native_delegation: { schema: 1, supported: true, editable: true, backend: 'model-router', digest: 'a'.repeat(64),
      policy: { heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } }, profile_routes: { profiles: [], default: null },
      slot_policy: offSlots(), auto_slot_policy: offSlots(), policy_schema: 0, auto_policy_schema: 0, slot_policy_supported: true,
      role_intro_inheritance: { schema: 1, supported: true, code_identity: 'e'.repeat(64), activation: 'new_session_or_supported_rebuild' }, warnings: [] },
    role_intro: { schema: 1, state: 'available', default_description: `Role of ${name}`, default_source: 'profile_metadata', description_auto: false, digest: 'f'.repeat(64) } })) })

function* walk(node) {
  if (Array.isArray(node)) { for (const item of node) yield* walk(item); return }
  if (!node || typeof node !== 'object') return
  yield node
  yield* walk(node.props?.children)
}
const text = node => typeof node === 'string' || typeof node === 'number' ? String(node)
  : Array.isArray(node) ? node.map(text).join(' ') : node?.props ? text(node.props.children) : ''
const strip = code => code.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
  .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
  .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
const importNames = () => {
  const names = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
    for (const name of match[1].split(',').map(value => value.trim()).filter(Boolean)) names[name] = name
  }
  return names
}

function helpers(sdk = {}) {
  const imports = { ...importNames(), DesktopSDK: sdk, host: {}, jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
  return new Function(...Object.keys(imports), `${strip(source)}\nreturn { REASONING_LEVELS, reasoningChoices, nativeModelMenu, modelMenuController, createModelCatalogRequest }`)(...Object.values(imports))
}

// RouterPage with in-memory hooks. The picker button is kept as an unrendered
// node and rendered on demand with its own hook slots, so its local open state
// never shares the page's positional hook list.
function harness({ sdk = { ...DIALOG_SDK, ...MENU_SDK }, activeProfile = 'claire' } = {}) {
  let data = fixture(), dirty = false, tree
  const page = { hooks: [], cursor: 0 }, effects = [], calls = [], catalogCalls = [], pickerScopes = new Map()
  let scope = page
  const values = new Map()
  const pluginContext = { storage: { get: (key, fallback = null) => values.has(key) ? structuredClone(values.get(key)) : fallback, set: (key, value) => values.set(key, structuredClone(value)) } }
  const state = Object.fromEntries(Object.entries({ profile: activeProfile, connectionId: 'local', gateway: 'open' })
    .map(([key, value]) => [key, { value, get() { return this.value } }]))
  const host = { state, request: async (method, args) => {
    if (method === 'model.options') { catalogCalls.push({ via: 'request', method, args }); return { providers: [] } }
    const index = args.argv.indexOf('model-router'), operation = args.argv[index + 1], body = JSON.parse(args.argv.at(-1))
    calls.push({ operation, body, profile: args.profile })
    const result = operation === 'status' ? structuredClone(data)
      : operation === 'preview' ? { plan_id: 'test-plan', changes: [{ profile: 'claire', field: 'models.main', before: 'before', after: 'after' }], warnings: [] }
        : { status: 'applied', revision: 8 }
    return { code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(result)}\n` }
  } }
  host.profileRoutes = async () => ['default', 'claire', 'other'].map(profile => ({ mode: 'local', connectionId: 'local', profile, targetProfile: profile }))
  host.requestProfile = async (descriptor, method, args) => { catalogCalls.push({ via: 'requestProfile', descriptor, method, args }); return { providers: [] } }
  const useState = initial => {
    const { hooks } = scope, index = scope.cursor++
    if (!(index in hooks)) hooks[index] = typeof initial === 'function' ? initial() : initial
    return [hooks[index], value => {
      const next = typeof value === 'function' ? value(hooks[index]) : value
      if (!Object.is(hooks[index], next)) { hooks[index] = next; dirty = true }
    }]
  }
  const useRef = initial => { const { hooks } = scope, index = scope.cursor++; return hooks[index] ??= { current: initial } }
  const useEffect = (fn, deps) => {
    const { hooks } = scope, index = scope.cursor++, before = hooks[index]
    if (!before || !deps || deps.some((value, at) => !Object.is(value, before[at]))) { hooks[index] = deps; effects.push(fn) }
  }
  const query = { get data() { return data }, isPending: false, isError: false, isFetching: false, refetch: async () => ({ data }) }
  const jsx = (type, props = {}) => typeof type === 'function' && type.name !== 'ModelPickerButton' ? type(props) : { type, props }
  const imports = { ...importNames(), DesktopSDK: sdk, useState, useRef, useEffect, jsx, jsxs: jsx, host, useValue: atom => atom.get(), useQuery: () => query }
  const moduleApi = new Function(...Object.keys(imports), `${strip(source)}\nreturn { RouterPage, pluginDefinition }`)(...Object.values(imports))
  moduleApi.pluginDefinition.register({ ...pluginContext, registerSettingsPage() {}, registerMany() {} })
  const render = () => {
    for (let attempt = 0; attempt < 20; attempt++) {
      dirty = false; scope = page; page.cursor = 0; tree = moduleApi.RouterPage({ ctx: pluginContext })
      for (const effect of effects.splice(0)) effect()
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  const nodes = () => [...walk(tree)]
  const byId = id => { const node = nodes().find(item => item.props?.id === id); assert.ok(node, `Control not found: ${id}`); return node }
  const pickerIds = () => nodes().filter(node => node.type?.name === 'ModelPickerButton').map(node => node.props.id)
  // Render one picker with isolated positional hooks owned by its id.
  const picker = (id, overrides = {}) => {
    const found = nodes().find(item => item.type?.name === 'ModelPickerButton' && item.props.id === id)
    assert.ok(found, `Picker not found: ${id}`)
    const node = { type: found.type, props: { ...found.props, ...overrides } }
    const own = pickerScopes.get(id) || { hooks: [], cursor: 0 }
    pickerScopes.set(id, own)
    own.cursor = 0; scope = own
    let view
    try { view = node.type(node.props) } finally { scope = page }
    const inner = [...walk(view)]
    return { node, view, dropdown: view, trigger: inner.find(item => item.type === 'Button'),
      menu: inner.find(item => item.type === 'ModelCatalogMenu'), close: inner.find(item => item.type === 'ModelMenuClose') }
  }
  render()
  return { calls, catalogCalls, state, render, byId, nodes, picker, pickerIds,
    flush: async () => { for (let at = 0; at < 20; at++) await Promise.resolve(); render() },
    click: id => { const node = byId(id); assert.ok(!node.props.disabled); node.props.onClick(); render() },
    selectValue: id => nodes().find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.value,
    select: (id, value) => { nodes().find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === id)).props.onValueChange(value); render() },
    selectProfile: name => { nodes().find(node => node.type === 'Select' && [...walk(node)].some(child => child.props?.id === 'profile-select')).props.onValueChange(name); render() } }
}

test('reasoning choices are exactly the backend efforts and keep an unlisted stored value visible', () => {
  const api = helpers()
  const efforts = /^EFFORTS = \{([^}]*)\}/m.exec(service)
  assert.ok(efforts, 'backend EFFORTS set should remain identifiable')
  const backend = [...efforts[1].matchAll(/"([a-z]+)"/g)].map(match => match[1]).sort()
  assert.deepEqual(api.REASONING_LEVELS.map(item => item.value).sort(), backend)
  for (const item of api.REASONING_LEVELS) assert.ok(item.label.includes(`(${item.value})`), 'exact identifier stays visible')
  assert.deepEqual(api.reasoningChoices('high').map(item => item.value), api.REASONING_LEVELS.map(item => item.value))
  assert.equal(api.reasoningChoices('').length, api.REASONING_LEVELS.length)
  assert.equal(api.reasoningChoices(undefined).length, api.REASONING_LEVELS.length)
  const legacy = api.reasoningChoices('legacy-level')
  assert.equal(legacy.at(-1).value, 'legacy-level')
  assert.match(legacy.at(-1).label, /목록에 없는 값/)
  assert.ok(Object.isFrozen(api.REASONING_LEVELS) && Object.isFrozen(api.REASONING_LEVELS[0]))
})

test('the catalog menu is used only when the host exports every required piece', () => {
  const api = helpers()
  assert.equal(api.nativeModelMenu({}), null)
  assert.equal(api.nativeModelMenu(null), null)
  for (const missing of Object.keys(MENU_SDK)) {
    const partial = { ...MENU_SDK }; delete partial[missing]
    assert.equal(api.nativeModelMenu(partial), null, `${missing} is required`)
  }
  assert.equal(api.nativeModelMenu({ ...MENU_SDK, ModelMenuCloseContext: {} }), null)
  const menu = api.nativeModelMenu(MENU_SDK)
  assert.deepEqual(menu, { ModelCatalogMenu: 'ModelCatalogMenu', DropdownMenu: 'DropdownMenu', DropdownMenuContent: 'DropdownMenuContent', DropdownMenuTrigger: 'DropdownMenuTrigger', CloseProvider: 'ModelMenuClose' })
})

test('choosing a model edits provider and model only and never rewrites the saved reasoning level', () => {
  const api = helpers(), edits = []
  const controller = api.modelMenuController({ route: route('openai-codex', 'gpt-6-astra-900k', 'medium'), withReasoning: true, onChange: (field, value) => edits.push([field, value]) })
  assert.equal(controller.allowSpeed, false)
  assert.deepEqual(controller.current, { provider: 'openai-codex', model: 'gpt-6-astra-900k', effort: 'medium', fast: false })
  assert.deepEqual(controller.presetFor('deepseek', 'deepseek-flash'), { effort: 'medium' }, 'every row previews the level this role keeps')
  assert.equal(controller.select('deepseek-flash', 'deepseek'), true)
  // The menu then offers its own remembered/default effort for the new row.
  controller.applyPreset({ effort: 'high', fast: true, serviceTier: 'priority' }, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash']])
  edits.length = 0
  assert.equal(controller.select('gpt-6-luna', 'openai-codex'), true)
  assert.deepEqual(edits, [['model', 'gpt-6-luna']], 'an unchanged provider is not rewritten')
  edits.length = 0
  for (const [model, provider] of [['', 'deepseek'], ['deepseek-flash', ''], [null, 'deepseek'], ['deepseek-flash', undefined]]) assert.equal(controller.select(model, provider), false)
  assert.deepEqual(edits, [], 'an incomplete row aborts without a partial edit')
})

test('an explicit level pick on a row changes reasoning; fast, unknown levels and chain entries do not', () => {
  const api = helpers(), edits = []
  const onChange = (field, value) => edits.push([field, value])
  const withLevel = api.modelMenuController({ route: route('openai-codex', 'gpt-6-astra-900k', 'medium'), withReasoning: true, onChange })
  withLevel.setOptions({ effort: 'high' }, { isActive: true, provider: 'openai-codex', model: 'gpt-6-astra-900k' })
  assert.deepEqual(edits, [['reasoning', 'high']])
  edits.length = 0
  withLevel.setOptions({ effort: 'none' }, { isActive: false, provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash'], ['reasoning', 'none']])
  edits.length = 0
  for (const patch of [{ fast: true }, { serviceTier: 'priority' }, { effort: '' }, { effort: 'turbo' }, { effort: 3 }, null]) withLevel.setOptions(patch, { provider: 'deepseek', model: 'deepseek-flash' })
  withLevel.setOptions({ effort: 'high' }, { provider: '', model: 'deepseek-flash' })
  assert.deepEqual(edits, [])
  const chain = api.modelMenuController({ route: { provider: 'xiaomi', model: 'mimo-v2.6-pro' }, onChange })
  assert.equal(chain.current.effort, '')
  chain.setOptions({ effort: 'high' }, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [], 'a spare-model entry stores no reasoning level')
  assert.equal(chain.select('deepseek-flash', 'deepseek'), true)
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash']])
  chain.applyPreset({ effort: 'high' }, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(chain.presetFor('deepseek', 'deepseek-flash'), {})
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash']])
})

test('a role without a level takes the host default once; an unlisted stored level is never replaced by a model pick', () => {
  const api = helpers(), edits = []
  const onChange = (field, value) => edits.push([field, value])
  const empty = api.modelMenuController({ route: null, withReasoning: true, onChange })
  assert.deepEqual(empty.current, { provider: '', model: '', effort: '', fast: false })
  assert.deepEqual(empty.presetFor('deepseek', 'deepseek-flash'), {})
  assert.equal(empty.select('deepseek-flash', 'deepseek'), true)
  empty.applyPreset({ effort: 'medium' }, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash'], ['reasoning', 'medium']])
  edits.length = 0
  for (const preset of [{}, { effort: undefined }, { effort: '' }, { effort: 'turbo' }, null]) empty.applyPreset(preset, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [], 'a model without a usable default leaves the level for the user to choose')
  const legacy = api.modelMenuController({ route: route('operator', 'old-model', 'legacy-level'), withReasoning: true, onChange })
  assert.equal(legacy.current.effort, 'legacy-level')
  assert.deepEqual(legacy.presetFor('deepseek', 'deepseek-flash'), {})
  legacy.select('deepseek-flash', 'deepseek')
  legacy.applyPreset({ effort: 'medium' }, { provider: 'deepseek', model: 'deepseek-flash' })
  assert.deepEqual(edits, [['provider', 'deepseek'], ['model', 'deepseek-flash']])
})

function transport({ profile = 'claire', connectionId = 'local', routes } = {}) {
  const log = []
  const state = { profile: { value: profile, get() { return this.value } }, connectionId: { value: connectionId, get() { return this.value } } }
  const list = routes || ['default', 'claire', 'other'].map(name => ({ mode: 'local', connectionId: 'local', profile: name, targetProfile: name }))
  return { log, state, request: async (method, params) => { log.push(['request', method, params]); return { providers: [{ slug: 'active' }] } },
    profileRoutes: async () => { log.push(['routes']); return structuredClone(list) },
    requestProfile: async (descriptor, method, params, ...rest) => { log.push(['requestProfile', descriptor, method, params, rest.length]); return { providers: [{ slug: 'routed' }] } } }
}

test('catalog transport reads only the loaded active profile inventory and discards caller parameters', async () => {
  const api = helpers(), wire = transport()
  const request = api.createModelCatalogRequest(wire, { profile: 'claire', activeProfile: 'claire', connectionId: 'local' })
  const reply = await request('model.options', { refresh: true, include_unconfigured: true, explicit_only: false, session_id: 'other-session', profile: 'default' })
  assert.deepEqual(reply, { providers: [{ slug: 'active' }] })
  assert.deepEqual(wire.log, [['request', 'model.options', { profile: 'claire', explicit_only: true }]])
  for (const method of ['config.set', 'session.mutate', 'model.save_key', 'cli.exec', '']) await assert.rejects(request(method, {}), /모델 목록만/)
  assert.equal(wire.log.length, 1, 'no other method reaches the transport')
})

test('another loaded profile is read only through its exact fresh local route descriptor', async () => {
  const api = helpers(), wire = transport()
  const request = api.createModelCatalogRequest(wire, { profile: 'other', activeProfile: 'claire', connectionId: 'local' })
  assert.deepEqual(await request('model.options', { refresh: true }), { providers: [{ slug: 'routed' }] })
  assert.deepEqual(wire.log, [['routes'], ['requestProfile', { mode: 'local', connectionId: 'local', profile: 'other', targetProfile: 'other' }, 'model.options', { profile: 'other', explicit_only: true }, 0]])
  const cases = {
    absent: [{ mode: 'local', connectionId: 'local', profile: 'claire', targetProfile: 'claire' }],
    alias: [{ mode: 'local', connectionId: 'local', profile: 'claire', targetProfile: 'claire' }, { mode: 'local', connectionId: 'local', profile: 'other-alias', targetProfile: 'other' }],
    ambiguous: [{ mode: 'local', connectionId: 'local', profile: 'claire', targetProfile: 'claire' }, ...[1, 2].map(() => ({ mode: 'local', connectionId: 'local', profile: 'other', targetProfile: 'other' }))],
    remote: [{ mode: 'local', connectionId: 'local', profile: 'claire', targetProfile: 'claire' }, { mode: 'remote', connectionId: 'local', profile: 'other', targetProfile: 'other' }],
    foreign: [{ mode: 'local', connectionId: 'local', profile: 'claire', targetProfile: 'claire' }, { mode: 'local', connectionId: 'elsewhere', profile: 'other', targetProfile: 'other' }],
    sourceless: [{ mode: 'local', connectionId: 'local', profile: 'other', targetProfile: 'other' }]
  }
  for (const [name, routes] of Object.entries(cases)) {
    const refused = transport({ routes })
    await assert.rejects(api.createModelCatalogRequest(refused, { profile: 'other', activeProfile: 'claire', connectionId: 'local' })('model.options'), /ID 직접 입력/, name)
    assert.deepEqual(refused.log, [['routes']], `${name}: nothing is requested`)
  }
  const legacy = transport(); delete legacy.requestProfile
  await assert.rejects(api.createModelCatalogRequest(legacy, { profile: 'other', activeProfile: 'claire', connectionId: 'local' })('model.options'), /ID 직접 입력/)
  assert.deepEqual(legacy.log, [])
})

test('a changed connection or profile and an unusable scope refuse before any catalog read', async () => {
  const api = helpers()
  for (const change of [wire => { wire.state.profile.value = 'default' }, wire => { wire.state.connectionId.value = 'elsewhere' }]) {
    const wire = transport(); change(wire)
    await assert.rejects(api.createModelCatalogRequest(wire, { profile: 'claire', activeProfile: 'claire', connectionId: 'local' })('model.options'), /바뀌었습니다/)
    await assert.rejects(api.createModelCatalogRequest(wire, { profile: 'other', activeProfile: 'claire', connectionId: 'local' })('model.options'), /바뀌었습니다/)
    assert.deepEqual(wire.log, [])
  }
  const late = transport(), routes = late.profileRoutes
  late.profileRoutes = async () => { const value = await routes(); late.state.profile.value = 'default'; return value }
  await assert.rejects(api.createModelCatalogRequest(late, { profile: 'other', activeProfile: 'claire', connectionId: 'local' })('model.options'), /바뀌었습니다/)
  assert.deepEqual(late.log, [['routes']], 'a switch during route lookup cancels the routed read')
  for (const scope of [null, {}, { profile: 'claire' }, { profile: '../claire', activeProfile: 'claire', connectionId: 'local' }, { profile: 'Claire', activeProfile: 'claire', connectionId: 'local' }, { profile: 7, activeProfile: 'claire', connectionId: 'local' }]) {
    const wire = transport()
    await assert.rejects(api.createModelCatalogRequest(wire, scope)('model.options'), /불러온 프로필을 확인할 수 없습니다/)
    assert.deepEqual(wire.log, [])
  }
})

test('every model route shows the catalog picker with exact IDs kept under manual entry', () => {
  const h = harness()
  assert.deepEqual(h.pickerIds().sort(), ['model-compression-picker', 'model-main-picker', 'model-title-picker', 'slot-design-picker', 'slot-verify-complex-picker'])
  assert.match(text(h.byId('model-catalog-note')), /불러온 프로필\(claire\)/)
  const main = h.picker('model-main-picker')
  assert.equal(main.trigger.props.disabled, false)
  assert.equal(main.trigger.props['aria-label'], '모델: openai-codex / gpt-6-astra-900k')
  assert.match(text(main.trigger), /gpt-6-astra-900k/)
  assert.match(text(main.trigger), /openai-codex/)
  assert.equal(main.dropdown.props.open, false)
  assert.deepEqual({ profile: main.menu.props.profile, owner: main.menu.props.ownerConnectionId }, { profile: 'claire', owner: 'local' })
  assert.equal(main.menu.props.controller.current.effort, 'medium')
  // Exact identifiers stay editable, inside a native disclosure.
  const manual = h.nodes().filter(node => node.type === 'details' && [...walk(node)].some(child => child.props?.id === 'model-main-model'))
  assert.equal(manual.length, 1)
  assert.match(text(manual[0].props.children[0]), /ID 직접 입력/)
  assert.equal(h.byId('model-main-provider').props.value, 'openai-codex')
  assert.equal(h.byId('model-main-model').props.value, 'gpt-6-astra-900k')
  assert.equal(h.selectValue('model-main-reasoning'), 'medium')
})

test('a catalog choice fills the draft only and is saved through the existing preview payload', async () => {
  const h = harness()
  assert.equal(h.picker('model-main-picker').menu.props.controller.select('deepseek-flash', 'deepseek'), true)
  h.render()
  assert.equal(h.byId('model-main-provider').props.value, 'deepseek')
  assert.equal(h.byId('model-main-model').props.value, 'deepseek-flash')
  assert.equal(h.selectValue('model-main-reasoning'), 'medium', 'the saved level survives a model change')
  assert.match(text(h.picker('model-main-picker').trigger), /deepseek-flash/)
  assert.equal(h.byId('model-compression-model').props.value, models.compression.model, 'other roles are untouched')
  assert.throws(() => h.byId('model-delegation-model'), 'the delegation model is not edited on this page')
  h.picker('slot-design-picker').menu.props.controller.setOptions({ effort: 'max' }, { isActive: true, provider: 'operator', model: 'independent-heavy' })
  h.render()
  assert.equal(h.selectValue('slot-design-reasoning'), 'max')
  h.select('model-title-reasoning', 'low')
  assert.equal(h.selectValue('model-title-reasoning'), 'low')
  assert.equal(h.calls.length, 0, 'selection alone saves nothing')
  assert.equal(h.catalogCalls.length, 0, 'no catalog read happens before a menu asks for one')
  h.click('model-section-save'); await h.flush()
  const payload = h.calls.find(call => call.operation === 'preview').body
  assert.deepEqual(payload.models.main, route('deepseek', 'deepseek-flash', 'medium'))
  assert.deepEqual(payload.models.title, route('openai-codex', 'gpt-6-luna', 'low'))
  assert.equal(Object.hasOwn(payload.models, 'delegation'), false, 'the delegation model is never sent')
  assert.deepEqual(payload.routing.slots.design.custom, route('operator', 'independent-heavy', 'max'), 'the slot level chosen in the menu is saved with it')
  assert.deepEqual(payload.routing.slots['verify-complex'], declarations()['verify-complex'])
  assert.deepEqual(payload.routing.heavy, routing.heavy, 'the tier pair is sent back as loaded')
})

test('the menu opens only while enabled and closes through the host close context', () => {
  const h = harness()
  const locked = h.picker('model-compression-picker', { disabled: true })
  assert.equal(locked.trigger.props.disabled, true)
  locked.dropdown.props.onOpenChange(true)
  assert.equal(h.picker('model-compression-picker', { disabled: true }).dropdown.props.open, false)
  assert.equal(h.picker('model-compression-picker').dropdown.props.open, false, 'a refused open leaves nothing pending')
  let view = h.picker('model-main-picker')
  view.dropdown.props.onOpenChange(true)
  view = h.picker('model-main-picker')
  assert.equal(view.dropdown.props.open, true)
  assert.equal(h.picker('model-title-picker').dropdown.props.open, false, 'each picker owns its own menu')
  view.close.props.value()
  assert.equal(h.picker('model-main-picker').dropdown.props.open, false)
})

test('the catalog follows the loaded profile and reaches a non-active profile by its exact route', async () => {
  const h = harness()
  await h.picker('model-main-picker').menu.props.request('model.options', { refresh: true })
  assert.deepEqual(h.catalogCalls, [{ via: 'request', method: 'model.options', args: { profile: 'claire', explicit_only: true } }])
  h.selectProfile('other')
  const other = h.picker('model-main-picker').menu
  assert.equal(other.props.profile, 'other')
  assert.match(text(h.byId('model-catalog-note')), /불러온 프로필\(other\)/)
  await other.props.request('model.options')
  assert.deepEqual(h.catalogCalls.at(-1), { via: 'requestProfile', descriptor: { mode: 'local', connectionId: 'local', profile: 'other', targetProfile: 'other' }, method: 'model.options', args: { profile: 'other', explicit_only: true } })
  await assert.rejects(other.props.request('config.set', { key: 'model', value: 'x' }), /모델 목록만/)
  assert.equal(h.catalogCalls.length, 2)
  assert.equal(h.calls.filter(call => call.operation !== 'status').length, 0, 'reading a catalog never previews or applies settings')
})

test('a host without the catalog menu keeps the plain ID inputs and a level select', () => {
  const h = harness({ sdk: { ...DIALOG_SDK } })
  assert.deepEqual(h.pickerIds(), [])
  assert.equal(h.nodes().some(node => node.props?.id === 'model-catalog-note'), false)
  assert.equal(h.nodes().some(node => node.type === 'details' && [...walk(node)].some(child => child.props?.id === 'model-main-model')), false)
  assert.equal(h.byId('model-main-provider').props.value, 'openai-codex')
  h.byId('model-main-model').props.onChange({ target: { value: 'typed-model' } }); h.render()
  assert.equal(h.byId('model-main-model').props.value, 'typed-model')
  assert.equal(h.selectValue('model-main-reasoning'), 'medium')
  assert.equal(h.catalogCalls.length, 0)
})

test('spare-model entries use the same picker without a reasoning level and keep stable row keys', () => {
  assert.doesNotMatch(source, /`\$\{entry\.provider\}:\$\{entry\.model\}:\$\{index\}`/, 'typing an ID must not remount its own row')
  assert.ok(source.includes('picker: index => `${prefix}-chain-${index}-picker`') && source.includes("chainIds('native')"), 'native-chain picker missing')
  assert.equal(source.includes('delegation-chain-'), false, 'the default-delegation spare list is gone')
  assert.ok(source.includes('picker: index => `slot-${slot.id}-spare-picker-${index}`'))
  assert.match(source, /이 항목에는 추론 강도를 따로 저장하지 않습니다/)
})

test('a catalog choice for a slot spare model fills provider and model together, and a later retained callback stays rejected', async () => {
  const h = harness()
  h.select('slot-design-fallback-mode', 'custom')
  const stale = h.picker('slot-design-spare-picker-0').menu.props.controller
  assert.equal(stale.select('sample-flash', 'sample-lab'), true)
  h.render()
  assert.equal(h.byId('slot-design-spare-provider-0').props.value, 'sample-lab')
  assert.equal(h.byId('slot-design-spare-model-0').props.value, 'sample-flash', 'the second field of one choice must not be dropped')
  assert.match(text(h.picker('slot-design-spare-picker-0').trigger), /sample-flash/)
  // The same controller, kept from the render before the edit, is a retained callback now.
  await Promise.resolve()
  stale.select('other-model', 'other-service'); h.render()
  assert.equal(h.byId('slot-design-spare-model-0').props.value, 'sample-flash')
  assert.equal(h.byId('slot-design-spare-provider-0').props.value, 'sample-lab')
  assert.equal(h.calls.length, 0)
})
