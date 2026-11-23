import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import test from 'node:test'

// Cross-language contract for the partial section saves (v0.15.0, `partial_save_schema: 1`). This
// test builds the exact partial request bodies the page sends with the real builders in
// desktop/plugin.js and keeps them in tests/fixtures/partial_save_contract.json.
// tests/test_partial_save_contract.py feeds every body through the real service preview/apply against
// a temporary home. The fixture must match what the builders produce now; regenerate it with
// UPDATE_CONTRACT_FIXTURES=1.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function api() {
  const names = []
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const n of m[1].split(',').map(s => s.trim()).filter(Boolean)) names.push(n)
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function('DesktopSDK', ...names, code + `
return { copyNativeDelegationDraft, copyNativeDelegationBaselines, planNativeDelegationBatch, buildNativeDelegationBatchBody, TASK_SLOTS,
  pageExpectation, pageExpectationsFor, buildModelSectionPreviewBody, buildScopedPreviewBody, slotRoutingForSave, editedSlotIds,
  partialSlotSkips, mergePartialSlots, profileRoutesPatch, mergeProfileRoutes, changedTimeoutFields, copyProfileDraft, submittedEditCoverage, modelSectionWriteSet, PARTIAL_SAVE_SCHEMA }`)(
    {}, ...names.map(n => ['jsx', 'jsxs'].includes(n) ? ((type, props) => ({ type, props })) : n))
}
const a = api()
const FIXTURE = new URL('./fixtures/partial_save_contract.json', import.meta.url)
const NAMES = ['default', 'p1', 'p2']
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const offRoles = () => ({ heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } })
const offSlots = () => Object.fromEntries(a.TASK_SLOTS.map(slot => [slot.id, { mode: 'off', chain: [] }]))
const spare = model => ({ mode: 'custom', chain: [{ provider: 'spare-service', model }] })

// ---- '/delegation-preview' (the Python fixture of tests/test_native_service.py) ----
// A seed: backend, optional routes, and the stored policy block: `slot` ('off' or {slot: model}) a
// per-slot block, `twoRole` an all-off two-role block.
function dtoFor(name, seed) {
  const routes = seed.routes ? structuredClone(seed.routes) : { profiles: [], default: null }
  const slotPolicy = offSlots()
  if (seed.slot && seed.slot !== 'off') for (const [id, model] of Object.entries(seed.slot)) slotPolicy[id] = spare(model)
  return { schema: 1, supported: true, editable: true, backend: seed.backend, digest: `digest:${name}`,
    role_intro_inheritance: { schema: 1, supported: true }, auto_supported: true,
    policy: offRoles(), auto_policy: offRoles(), slot_policy: slotPolicy, auto_slot_policy: offSlots(),
    policy_schema: seed.twoRole ? 1 : seed.slot ? 2 : 0, auto_policy_schema: 0, slot_policy_supported: true,
    profile_routes: routes, warnings: [] }
}

function nativeCase(name, description, seeds, origin, targets, part, edit, copyAll = false) {
  const rows = NAMES.map(profile => ({ name: profile, routing: { enabled: true }, native_delegation: dtoFor(profile, seeds[profile]) }))
  const draft = a.copyNativeDelegationDraft(rows.find(row => row.name === origin).native_delegation)
  edit(draft)
  const plan = a.planNativeDelegationBatch(0, origin, targets, draft, a.copyNativeDelegationBaselines(rows), rows, part, { partial: true, copyAll })
  return { kind: 'native', name, description, part, origin, targets, seeds, dtos: Object.fromEntries(rows.map(row => [row.name, row.native_delegation])),
    // `skipped`: targets that receive no update at all; `partly_skipped`: targets named for one part
    // (for example a default they cannot take) that still receive the rest.
    body: plan.body, skipped: Object.keys(plan.skipped).filter(target => !plan.body.updates.some(update => update.profile === target)),
    partly_skipped: Object.keys(plan.skipped).filter(target => plan.body.updates.some(update => update.profile === target)) }
}

// ---- '/preview' (the Python store fixture of tests/test_slots.py: default, p1, p2) ----
// Rows as the page sees them: the stored slot declarations of each profile, routing on, skill on.
// `models` is a placeholder the Python side replaces with the real status models (a routing- or
// timeout-scope save sends the loaded baseline models, which the service does not write).
const PLACEHOLDER_MODELS = { main: route('placeholder', 'main', 'high'), compression: route('placeholder', 'main', 'high'), title: route('placeholder', 'main', 'high') }
function storeRow(name, stored, timeouts = null) {
  const declarations = Object.fromEntries(a.TASK_SLOTS.map(slot => [slot.id, stored?.[slot.id] || { follow: slot.tier === 'heavy' ? 'main' : 'delegation', custom: null }]))
  return { name, models: structuredClone(PLACEHOLDER_MODELS), actual_models: structuredClone(PLACEHOLDER_MODELS),
    routing: { enabled: true, heavy: { follow: 'main', custom: null }, light: { follow: 'delegation', custom: null },
      fallback: { enabled: false, heavy: null, light: null }, ...(stored ? { slots: structuredClone(stored) } : {}) },
    slots: { schema: 1, capable: true, declarations, stored: Object.keys(stored || {}) }, drift: [], ...(timeouts ? { timeouts } : {}) }
}
function snapshotFor(rows, origin, extra) {
  const baselines = Object.fromEntries(rows.map(row => [row.name, a.copyProfileDraft(row)]))
  return { revision: 0, profile: origin, profiles: rows, profileBaselines: baselines, draft: a.copyProfileDraft(rows.find(row => row.name === origin)),
    routingProfiles: rows.filter(row => row.routing.enabled).map(row => row.name), modelTargets: [], partialSave: true, ...extra }
}
const withExpected = (body, rows) => ({ ...body, expected: a.pageExpectationsFor('/preview', body, Object.fromEntries(rows.map(row => [row.name, a.pageExpectation(row)])), rows.map(row => row.name)) })

function slotCase(name, description, seeds, origin, targets, edit, copyAll = false) {
  const rows = NAMES.map(profile => storeRow(profile, seeds[profile]))
  const snapshot = snapshotFor(rows, origin, { routingTargets: targets })
  const frozen = structuredClone(snapshot.draft.slots)
  edit(snapshot.draft.slots)
  const edited = a.editedSlotIds(snapshot.draft.slots, frozen)
  snapshot.draft.routing = a.slotRoutingForSave(snapshot.draft, true, copyAll ? null : edited)
  const { body, errors } = a.buildScopedPreviewBody(snapshot, 'routing')
  assert.deepEqual(errors, [])
  const submitted = Object.keys(body.routing.slots || {})
  return { kind: 'store', name, description, origin, seeds, edited,
    skips: Object.fromEntries(targets.map(target => [target, a.partialSlotSkips(rows.find(row => row.name === target), submitted, origin)])),
    merged: Object.fromEntries(targets.map(target => [target, a.mergePartialSlots(seeds[target] || null, body.routing.slots, target !== origin)])),
    body: withExpected(body, rows) }
}

// The untouched default profile reports the earlier single routed limit.
const untouched = () => ({ schema: 1, revision: 0, delegate_total_seconds: 0, routed_total_seconds: 3600, editable: true, split_routing_supported: true, warnings: [] })
const split = (revision, delegate, light, heavy) => ({ schema: 2, revision, delegate_total_seconds: delegate, routed_light_total_seconds: light,
  routed_heavy_total_seconds: heavy, editable: true, split_routing_supported: true, warnings: [] })
function timeoutCase(name, description, seeds, origin, targets, edit, copyAll = false) {
  const rows = NAMES.map(profile => storeRow(profile, null, seeds[profile]))
  const snapshot = snapshotFor(rows, origin, { routingTargets: [], timeoutTargets: targets, timeoutCopyAll: copyAll,
    timeoutsBaseline: structuredClone(seeds[origin]),
    timeoutBaselinesByProfile: Object.fromEntries(Object.entries(seeds).map(([key, value]) => [key, (({ warnings: _w, ...rest }) => rest)(value)])),
    currentTimeoutsByProfile: structuredClone(seeds) })
  edit(snapshot.draft.timeouts)
  const { body, errors } = a.buildScopedPreviewBody(snapshot, 'timeouts')
  assert.deepEqual(errors, [])
  return { kind: 'store', name, description, origin, seeds, body: withExpected(body, rows) }
}

export function contractCases() {
  return [
    nativeCase('native-slot-spare-patch', 'Only the edited slot spare model goes to each target; a target with nothing stored starts from all off; a two-role target is skipped.',
      { default: { backend: 'model-router', slot: 'off' }, p1: { backend: 'model-router', slot: { 'code-complex': 'p1-own-spare' } }, p2: { backend: 'model-router', twoRole: true } },
      'default', ['default', 'p1', 'p2'], 'native', draft => { draft.slotPolicy.design = spare('design-spare') }),
    nativeCase('native-slot-spare-off-patch', 'Switching one stored custom slot off sends that slot only, without cost confirmation.',
      { default: { backend: 'model-router', slot: { design: 'old-spare', 'verify-complex': 'kept-spare' } }, p1: { backend: 'model-router' }, p2: { backend: 'model-router' } },
      'default', ['default'], 'native', draft => { draft.slotPolicy.design = { mode: 'off', chain: [] } }),
    nativeCase('native-method-only', 'A method edit sends the method only; every target keeps its stored spare models.',
      { default: { backend: 'model-router', slot: 'off' }, p1: { backend: 'model-router', slot: { design: 'p1-spare' } }, p2: { backend: 'model-router-auto' } },
      'default', ['default', 'p1', 'p2'], 'native', draft => { draft.backend = 'model-router-profiles' }),
    nativeCase('native-copy-all', 'With copy-all the earlier full body is sent (marker included).',
      { default: { backend: 'model-router', slot: { design: 'copied-spare' } }, p1: { backend: 'model-router', slot: { 'code-simple': 'p1-spare' } }, p2: { backend: 'model-router' } },
      'default', ['default', 'p1'], 'native', () => {}, true),
    nativeCase('profiles-routes-patch', 'An added specialist and a new default go to each target as a patch; a target already listing it keeps its own description.',
      { default: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p1', description: 'source description' }], default: null } },
        p1: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p2', description: 'p1 own description' }], default: null } },
        p2: { backend: 'model-router-auto', routes: { profiles: [{ name: 'p1', description: 'p2 own' }], default: null } } },
      'default', ['default', 'p1', 'p2'], 'profiles', draft => {
        draft.profile_routes = { profiles: [...draft.profile_routes.profiles, { name: 'p2', description: 'reviewer' }], default: 'p2' }
        draft.descriptionEdits = { p2: true }
        draft.allowProfileAccess = true
      }),
    nativeCase('profiles-routes-remove-and-describe', 'A removal and a description edit need no new authority.',
      { default: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p1', description: 'a' }, { name: 'p2', description: 'b' }], default: 'p2' } },
        p1: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p2', description: 'p1 keeps' }], default: 'p2' } }, p2: { backend: 'model-router' } },
      'default', ['default', 'p1'], 'profiles', draft => {
        draft.profile_routes = { profiles: [{ name: 'p2', description: 'edited b' }], default: 'p2' }
        draft.descriptionEdits = { p2: true }
      }),
    slotCase('slot-merge', 'One edited slot merges over each target; unsent slots keep their declaration, absent ones stay absent.',
      { p1: { 'verify-simple': { follow: 'custom', custom: route('operator', 'p1-checker', 'low') } },
        p2: { 'computer-use': { follow: 'custom', custom: route('operator', 'p2-screen', 'medium') }, 'code-simple': { follow: 'delegation', custom: null } } },
      'p1', ['p1', 'p2'], slots => { slots.design = { follow: 'custom', custom: route('operator', 'designer', 'high') } }),
    slotCase('slot-legacy-collision', 'A submitted slot that another target stores as following the delegation model is kept there.',
      { p1: { 'code-simple': { follow: 'custom', custom: route('operator', 'p1-coder', 'low') } }, p2: { 'code-simple': { follow: 'delegation', custom: null } } },
      'p1', ['p1', 'p2'], slots => { slots['code-simple'] = { follow: 'main', custom: null } }),
    slotCase('slot-copy-all', 'Copy-all sends every slot (the earlier slot map), merged per target.',
      { p1: { design: { follow: 'custom', custom: route('operator', 'copied-designer', 'high') }, 'code-complex': { follow: 'main', custom: null },
        'code-simple': { follow: 'main', custom: null }, 'verify-simple': { follow: 'custom', custom: route('operator', 'copied-checker', 'low') },
        'verify-complex': { follow: 'main', custom: null }, 'computer-use': { follow: 'main', custom: null } },
        p2: { 'verify-complex': { follow: 'custom', custom: route('operator', 'p2-reviewer', 'xhigh') }, 'code-simple': { follow: 'delegation', custom: null } } },
      'p1', ['p1', 'p2'], () => {}, true),
    timeoutCase('timeout-one-field', 'Only the changed time limit goes to each target; the others keep their own values.',
      { default: untouched(), p1: split(1, 60, 1800, 7200), p2: split(1, 30, 4000, 5000) },
      'p1', ['p1', 'p2'], timeouts => { timeouts.delegate_total_minutes = 5 }),
    timeoutCase('timeout-copy-all', 'Copy-all sends all three values.',
      { default: untouched(), p1: split(1, 60, 1800, 7200), p2: split(1, 30, 4000, 5000) },
      'p1', ['p2'], () => {}, true)
  ]
}

const render = () => `${JSON.stringify({ schema: 1, generated_by: 'tests/test_partial_save_contract_desktop.mjs', cases: contractCases() }, null, 2)}\n`

test('the partial save contract fixture matches the bodies the page builds now', () => {
  const expected = render()
  if (process.env.UPDATE_CONTRACT_FIXTURES === '1') {
    mkdirSync(new URL('./fixtures/', import.meta.url), { recursive: true })
    writeFileSync(FIXTURE, expected)
  }
  assert.equal(existsSync(FIXTURE), true, 'missing fixture: run with UPDATE_CONTRACT_FIXTURES=1')
  const stored = readFileSync(FIXTURE, 'utf8').replace(/\r\n/g, '\n')
  assert.equal(stored, expected, 'stale fixture: the page builders changed; rerun with UPDATE_CONTRACT_FIXTURES=1 and run tests/test_partial_save_contract.py')
})

test('every partial body carries the literal marker and only the changed parts', () => {
  const cases = Object.fromEntries(contractCases().map(item => [item.name, item]))
  for (const item of Object.values(cases)) assert.equal(item.body.partial_save_schema, 1, item.name)
  const patch = cases['native-slot-spare-patch']
  assert.deepEqual(patch.skipped, ['p2'])
  assert.deepEqual(patch.body.updates.map(update => [update.profile, Object.keys(update).sort()]), [
    ['default', ['allow_additional_cost', 'allow_profile_access', 'expected_digest', 'profile', 'slot_policy_patch']],
    ['p1', ['allow_additional_cost', 'allow_profile_access', 'expected_digest', 'profile', 'slot_policy_patch']]])
  for (const update of patch.body.updates) assert.deepEqual(Object.keys(update.slot_policy_patch), ['design'])
  assert.deepEqual(cases['native-slot-spare-off-patch'].body.updates[0].allow_additional_cost, false)
  assert.deepEqual(cases['native-method-only'].body.updates.map(update => Object.keys(update).sort()),
    Array(3).fill(['allow_profile_access', 'backend', 'expected_digest', 'profile']))
  assert.ok(cases['native-copy-all'].body.updates.every(update => update.slot_policy && update.backend))
  const routes = cases['profiles-routes-patch'].body.updates
  assert.ok(routes.every(update => !('profile_routes' in update) && update.profile_routes_patch.add?.[0]?.name === 'p2' && !('descriptions' in update.profile_routes_patch)))
  // The automatic target keeps its own (hidden) default.
  assert.deepEqual(routes.map(update => 'default' in update.profile_routes_patch), [true, true, false])
  const merge = cases['slot-merge'].body
  assert.deepEqual(Object.keys(merge.routing).sort(), ['enabled', 'slots'], 'no Heavy/Light')
  assert.deepEqual(Object.keys(merge.routing.slots), ['design'])
  assert.deepEqual(merge.expected.map(item => [item.profile, Object.keys(item.routing.slots)]), [['default', ['design']], ['p1', ['design']], ['p2', ['design']]])
  assert.deepEqual(cases['slot-legacy-collision'].skips, { p1: [], p2: ['code-simple'] })
  assert.equal(Object.keys(cases['slot-copy-all'].body.routing.slots).length, 6)
  assert.deepEqual(cases['slot-copy-all'].skips, { p1: [], p2: ['code-simple'] })
  assert.deepEqual(cases['timeout-one-field'].body.timeout_updates.map(update => Object.keys(update).sort()),
    Array(2).fill(['delegate_total_seconds', 'expected_revision', 'profile']))
  assert.deepEqual(Object.keys(cases['timeout-copy-all'].body.timeout_updates[0]).sort(),
    ['delegate_total_seconds', 'expected_revision', 'profile', 'routed_heavy_total_seconds', 'routed_light_total_seconds'])
})

test('without the capability the same builders keep the earlier full bodies', () => {
  const rows = NAMES.map(profile => ({ name: profile, routing: { enabled: true }, native_delegation: dtoFor(profile, { backend: 'model-router', slot: 'off' }) }))
  const draft = a.copyNativeDelegationDraft(rows[0].native_delegation)
  draft.slotPolicy.design = spare('design-spare')
  const legacy = a.buildNativeDelegationBatchBody(0, 'default', ['default', 'p1'], draft, a.copyNativeDelegationBaselines(rows), rows, 'native')
  assert.equal('partial_save_schema' in legacy, false)
  assert.ok(legacy.updates.every(update => update.backend === 'model-router' && Object.keys(update.slot_policy).length === 6))
  const store = NAMES.map(profile => storeRow(profile, null))
  const snapshot = { ...snapshotFor(store, 'p1', { routingTargets: ['p1'] }), partialSave: false }
  snapshot.draft.slots.design = { follow: 'custom', custom: route('operator', 'designer', 'high') }
  snapshot.draft.routing = a.slotRoutingForSave(snapshot.draft, true)
  const { body } = a.buildScopedPreviewBody(snapshot, 'routing')
  assert.equal('partial_save_schema' in body, false)
  assert.deepEqual(Object.keys(body.routing).sort(), ['enabled', 'heavy', 'light', 'slots'])
  assert.equal(Object.keys(body.routing.slots).length, 6)
})

test('an edit counts as saved only when the partial body carried it as drafted', () => {
  const designed = { follow: 'custom', custom: route('operator', 'designer', 'high') }
  const view = { profile: 'p1', slots: { design: designed, 'code-simple': { follow: 'main', custom: null } }, editedSlots: ['design'],
    timeoutFields: ['delegate_total_seconds'],
    native: { backend: 'model-router', slotPolicy: { design: spare('d') }, autoSlotPolicy: null, editedSpares: ['design'], profile_routes: { profiles: [], default: null }, frozenRoutes: { profiles: [], default: null }, descriptionEdits: {} } }
  const store = slots => ({ operation: '/preview', body: { partial_save_schema: 1, save_scope: 'routing', profile: 'p1', routing: { enabled: true, slots }, routing_targets: ['p1'] } })
  const covered = a.submittedEditCoverage(view, [store({ design: designed })])
  assert.ok(covered.has('routing.slots'))
  assert.equal(covered.has('copy.slots'), false, 'one slot is not a copy of every slot')
  assert.equal(a.submittedEditCoverage(view, [store({ 'code-simple': view.slots['code-simple'] })]).has('routing.slots'), false)
  assert.equal(a.submittedEditCoverage(view, [store({ design: { follow: 'main', custom: null } })]).has('routing.slots'), false)
  const timeouts = fields => ({ operation: '/preview', body: { partial_save_schema: 1, save_scope: 'timeouts', timeout_updates: [{ profile: 'p1', expected_revision: 1, ...fields }] } })
  assert.ok(a.submittedEditCoverage(view, [timeouts({ delegate_total_seconds: 60 })]).has('timeouts'))
  assert.equal(a.submittedEditCoverage(view, [timeouts({ routed_light_total_seconds: 60 })]).has('timeouts'), false)
  const native = patch => ({ operation: '/delegation-preview', part: 'native', body: { partial_save_schema: 1, updates: [{ profile: 'p1', slot_policy_patch: patch }] } })
  assert.ok(a.submittedEditCoverage(view, [native({ design: spare('d') })]).has('native.slotPolicy'))
  assert.equal(a.submittedEditCoverage(view, [native({ design: spare('other') })]).has('native.slotPolicy'), false)
  // The write summary is read from the same bodies.
  const set = a.modelSectionWriteSet({ store: store({ design: designed }).body, native: native({ design: spare('d') }).body, profiles: [] })
  assert.deepEqual(set.get('p1').slots, ['design'])
  assert.deepEqual(set.get('p1').slotSpares, ['design'])
})
