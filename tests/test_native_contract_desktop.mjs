import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import test from 'node:test'

// Cross-language contract for '/delegation-preview'. This test builds the exact request bodies the
// page sends for the main save shapes with the real builders in desktop/plugin.js and keeps them in
// tests/fixtures/native_delegation_contract.json. tests/test_native_contract.py feeds every body
// through the real native_service preview/apply against a temporary config. The fixture must match
// what the builders produce now; regenerate it with UPDATE_CONTRACT_FIXTURES=1.
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function api() {
  const names = []
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const n of m[1].split(',').map(s => s.trim()).filter(Boolean)) names.push(n)
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function('DesktopSDK', ...names, code + '\nreturn { copyNativeDelegationDraft, copyNativeDelegationBaselines, buildNativeDelegationBatchBody, TASK_SLOTS, pageExpectation, pageExpectationsFor }')(
    {}, ...names.map(n => ['jsx', 'jsxs'].includes(n) ? ((type, props) => ({ type, props })) : n))
}
const a = api()
const FIXTURE = new URL('./fixtures/native_delegation_contract.json', import.meta.url)
// The profiles of the Python fixture in tests/test_native_service.py.
const NAMES = ['default', 'p1', 'p2']
const offRoles = () => ({ heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } })
const offSlots = () => Object.fromEntries(a.TASK_SLOTS.map(slot => [slot.id, { mode: 'off', chain: [] }]))

// The status DTO the real service reports for a seed; the Python side checks it field by field, so a
// change in what the service reports also makes this contract fail.
function dtoFor(name, seed) {
  const routes = seed.routes ? structuredClone(seed.routes) : { profiles: [], default: null }
  return { schema: 1, supported: true, editable: true, backend: seed.backend, digest: `digest:${name}`,
    role_intro_inheritance: { schema: 1, supported: true }, auto_supported: true,
    policy: offRoles(), auto_policy: offRoles(), slot_policy: offSlots(), auto_slot_policy: offSlots(),
    policy_schema: seed.slot ? 2 : 0, auto_policy_schema: seed.autoSlot ? 2 : 0, slot_policy_supported: true,
    profile_routes: routes,
    warnings: routes.profiles.some(entry => !NAMES.includes(entry.name)) ? ['profile_target_missing_remove_from_allowlist'] : [] }
}

function contractCase(name, description, seeds, origin, targets, part, edit) {
  // Task routing is on for every profile, as in the Python fixture (routing_config enabled).
  const rows = NAMES.map(profile => ({ name: profile, routing: { enabled: true }, native_delegation: dtoFor(profile, seeds[profile]) }))
  const draft = a.copyNativeDelegationDraft(rows.find(row => row.name === origin).native_delegation)
  edit(draft)
  const body = a.buildNativeDelegationBatchBody(0, origin, targets, draft, a.copyNativeDelegationBaselines(rows), rows, part)
  return { name, description, part, origin, seeds, dtos: Object.fromEntries(rows.map(row => [row.name, row.native_delegation])), body }
}

const spare = model => ({ mode: 'custom', chain: [{ provider: 'spare-service', model }] })
export function contractCases() {
  return [
    contractCase('backend-only-method-change', 'Model save choosing the profile method: no slot cards on screen, so only the method is sent.',
      { default: { backend: 'model-router' }, p1: { backend: 'model-router' }, p2: { backend: 'model-router-auto' } },
      'default', ['default', 'p1'], 'native', draft => { draft.backend = 'model-router-profiles' }),
    contractCase('model-save-with-slot-cards', 'Model-only source with an edited slot spare model, copied to a profile-only target that has no stored policy.',
      { default: { backend: 'model-router', slot: 'off' }, p1: { backend: 'model-router-profiles' }, p2: { backend: 'model-router' } },
      'default', ['default', 'p1', 'p2'], 'native', draft => { draft.slotPolicy.design = spare('design-spare') }),
    contractCase('model-save-auto-source', 'Automatic source with an edited automatic slot spare model; the stored allow-list is not sent.',
      { default: { backend: 'model-router-auto', autoSlot: 'off', routes: { profiles: [{ name: 'p1', description: 'specialist' }], default: null } },
        p1: { backend: 'model-router-profiles' }, p2: { backend: 'model-router-auto' } },
      'default', ['default', 'p2'], 'native', draft => { draft.autoSlotPolicy['verify-simple'] = spare('verify-spare') }),
    contractCase('model-save-without-slot-cards', 'Profile-only source copying its method; no spare models and no allow-list are sent.',
      { default: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p1', description: 'kept' }], default: 'p1' } },
        p1: { backend: 'model-router' }, p2: { backend: 'model-router-profiles' } },
      'default', ['default', 'p1', 'p2'], 'native', () => {}),
    contractCase('profile-save-profile-source', 'Profile-only source adding a specialist and a default; the automatic target keeps its own default.',
      { default: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p1', description: 'old' }], default: null } },
        p1: { backend: 'model-router-profiles' }, p2: { backend: 'model-router-auto', routes: { profiles: [{ name: 'p1', description: 'own' }], default: null } } },
      'default', ['default', 'p1', 'p2'], 'profiles', draft => {
        draft.profile_routes = { profiles: [...draft.profile_routes.profiles, { name: 'p2', description: 'reviewer' }], default: 'p2' }
        draft.descriptionEdits = { p2: true }
        draft.allowProfileAccess = true
      }),
    contractCase('profile-save-auto-source', 'Automatic source adding a specialist; a profile-only target keeps its stored default.',
      { default: { backend: 'model-router-auto', routes: { profiles: [{ name: 'p1', description: 'a' }], default: null } },
        p1: { backend: 'model-router-profiles', routes: { profiles: [{ name: 'p2', description: 'own' }], default: 'p2' } }, p2: { backend: 'model-router-profiles' } },
      'default', ['default', 'p1'], 'profiles', draft => {
        draft.profile_routes = { profiles: [...draft.profile_routes.profiles, { name: 'p2', description: 'b' }], default: null }
        draft.descriptionEdits = { p2: true }
        draft.allowProfileAccess = true
      }),
    contractCase('deleted-specialist-method-change', 'Model-only source whose stored allow-list still names a deleted profile switches to the profile method.',
      { default: { backend: 'model-router', routes: { profiles: [{ name: 'ghost', description: 'deleted' }], default: 'ghost' } },
        p1: { backend: 'model-router' }, p2: { backend: 'model-router' } },
      'default', ['default'], 'native', draft => { draft.backend = 'model-router-profiles' })
  ]
}

const render = () => `${JSON.stringify({ schema: 1, generated_by: 'tests/test_native_contract_desktop.mjs', cases: contractCases() }, null, 2)}\n`

test('the delegation contract fixture matches the bodies the page builds now', () => {
  const expected = render()
  if (process.env.UPDATE_CONTRACT_FIXTURES === '1') {
    mkdirSync(new URL('./fixtures/', import.meta.url), { recursive: true })
    writeFileSync(FIXTURE, expected)
  }
  assert.equal(existsSync(FIXTURE), true, 'missing fixture: run with UPDATE_CONTRACT_FIXTURES=1')
  const stored = readFileSync(FIXTURE, 'utf8').replace(/\r\n/g, '\n')
  assert.equal(stored, expected, 'stale fixture: the page builders changed; rerun with UPDATE_CONTRACT_FIXTURES=1 and run tests/test_native_contract.py')
})

test('the contract covers every main body shape', () => {
  const shapes = contractCases().flatMap(item => item.body.updates.map(update => [item.part, Object.keys(update).sort().join(',')]))
  const keys = new Set(shapes.map(([part, fields]) => `${part}:${fields}`))
  assert.ok(keys.has('native:allow_profile_access,backend,expected_digest,profile'), 'backend-only')
  assert.ok(keys.has('native:allow_additional_cost,allow_profile_access,backend,expected_digest,profile,slot_policy'), 'method with slot spare models')
  assert.ok(keys.has('profiles:allow_profile_access,backend,expected_digest,profile,profile_routes'), 'profile save')
  for (const [, fields] of shapes) assert.equal(fields.includes('profile_routes') && fields.includes('slot_policy'), false, 'no update carries both parts')
})

// The `expected` values of '/preview' and '/fallback-preview' (compare-and-set). The page copies them
// from a status row with pageExpectation(); tests/test_page_expectations.py checks that the same
// mapping of the service's own status rows equals what the service compares against.
const EXPECTATION_FIXTURE = new URL('./fixtures/page_expectation_contract.json', import.meta.url)
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const sampleRow = () => ({
  name: 'p1',
  models: { main: route('openai-codex', 'stored-main', 'high'), delegation: route('deepseek', 'stored-light', 'low'),
    compression: route('openai-codex', 'stored-main', 'high'), title: route('openai-codex', 'stored-main', 'high') },
  actual_models: { main: route('openai-codex', 'actual-main', 'high'), delegation: route('deepseek', 'stored-light', 'low'),
    compression: route('openai-codex', 'actual-main', 'high'), title: route('openai-codex', 'actual-main', 'high') },
  routing: { enabled: true, heavy: { follow: 'main', custom: null }, light: { follow: 'custom', custom: route('deepseek', 'routed', 'low') },
    fallback: { enabled: false, heavy: null, light: null }, slots: { design: { follow: 'main', custom: null } } },
  fallbacks: { native: { managed: true, editable: true, enabled: true, chain: [{ provider: 'xiaomi', model: 'spare' }],
    actual_chain: [{ provider: 'xiaomi', model: 'spare' }], drift: false, warnings: [], consent: null } },
  // The compression and title-generation spare models (auxiliary.<task>.fallback_chain), since v0.13.0.
  auxiliary_fallbacks: {
    compression: { schema: 1, key: 'auxiliary.compression.fallback_chain', editable: true, present: true, chain: [{ provider: 'deepseek', model: 'flash' }],
      actual_chain: [{ provider: 'deepseek', model: 'flash' }], drift: false, managed_overlay: false, warnings: [] },
    title: { schema: 1, key: 'auxiliary.title_generation.fallback_chain', editable: true, present: false, chain: [], actual_chain: [], drift: false, managed_overlay: false, warnings: [] } },
  // The routing skill is switched off in the profile's own config while the canonical flag is on.
  drift: ['skills.disabled']
})
const renderExpectations = () => {
  const row = sampleRow()
  const frozen = { p1: a.pageExpectation(row) }
  const body = { save_scope: null, model_targets: ['p1'], fallback_updates: [{ profile: 'p1', native_fallback: { enabled: false, chain: [] }, auxiliary_fallback: { title: [] } }] }
  return `${JSON.stringify({ schema: 1, generated_by: 'tests/test_native_contract_desktop.mjs', row, expectation: frozen.p1,
    preview_expected: a.pageExpectationsFor('/preview', body, frozen, ['p1']) }, null, 2)}\n`
}

test('the page expectation fixture matches what the page sends now', () => {
  const expected = renderExpectations()
  if (process.env.UPDATE_CONTRACT_FIXTURES === '1') writeFileSync(EXPECTATION_FIXTURE, expected)
  assert.equal(existsSync(EXPECTATION_FIXTURE), true, 'missing fixture: run with UPDATE_CONTRACT_FIXTURES=1')
  assert.equal(readFileSync(EXPECTATION_FIXTURE, 'utf8').replace(/\r\n/g, '\n'), expected, 'stale fixture: rerun with UPDATE_CONTRACT_FIXTURES=1 and run tests/test_page_expectations.py')
})
