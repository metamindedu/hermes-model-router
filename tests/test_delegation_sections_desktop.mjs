import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// v0.12.0 splits one delegation draft into two saves over the same '/delegation-preview' body shape:
// the model section's method/spare models ('native') and the profile delegation section ('profiles').
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function api() {
  const names = []
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const n of m[1].split(',').map(s => s.trim()).filter(Boolean)) names.push(n)
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  return new Function('DesktopSDK', ...names, code + '\nreturn { NATIVE_DELEGATION_BACKENDS, NATIVE_DELEGATION_LEGACY_LABELS, nativeBackendSelectable, copyNativeDelegationDraft, nativeDelegationDraftChanged, nativeProfileTargetReason, buildNativeDelegationBatchBody, nativeDelegationSnapshotCurrent, PAGE_FALLBACK_SCOPES, submittedEditCoverage }')(
    {}, ...names.map(n => ['jsx', 'jsxs'].includes(n) ? ((type, props) => ({ type, props })) : n))
}
const a = api()
const off = () => ({ heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } })
const slots = () => Object.fromEntries(['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use'].map(id => [id, { mode: 'off', chain: [] }]))
const dto = (name, backend, overrides = {}) => ({ schema: 1, supported: true, editable: true, backend, digest: name[0].repeat(64), auto_supported: true,
  policy: off(), auto_policy: off(), slot_policy: slots(), auto_slot_policy: slots(), policy_schema: 0, auto_policy_schema: 0, slot_policy_supported: true,
  profile_routes: { profiles: [{ name: 'other', description: `stored by ${name}` }], default: null },
  role_intro_inheritance: { schema: 1, supported: true }, warnings: [], ...overrides })
const rows = backends => Object.entries(backends).map(([name, backend]) => ({ name, routing: { enabled: true }, native_delegation: dto(name, backend) }))
const baselines = list => Object.fromEntries(list.map(row => [row.name, structuredClone(row.native_delegation)]))

test('Hermes default delegation is not offered but keeps a readable label', () => {
  assert.deepEqual(a.NATIVE_DELEGATION_BACKENDS.map(item => item.value), ['model-router', 'model-router-auto', 'model-router-profiles'])
  assert.equal(a.nativeBackendSelectable('default'), false)
  assert.match(a.NATIVE_DELEGATION_LEGACY_LABELS.default, /기본 위임 모델 사용/)
  assert.deepEqual(a.PAGE_FALLBACK_SCOPES, ['native'])
})

test('the native part sends the drafted method and each target stored allow-list; it never writes default', () => {
  const list = rows({ claire: 'model-router-profiles', other: 'model-router-auto' })
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  draft.backend = 'model-router'
  draft.profile_routes = { profiles: [{ name: 'claire', description: 'draft only' }], default: 'claire' }
  draft.allowProfileAccess = true
  assert.equal(a.nativeDelegationDraftChanged(draft, list[0].native_delegation, 'native'), true)
  assert.equal(a.nativeDelegationDraftChanged(draft, list[0].native_delegation, 'profiles'), true)
  const body = a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'other'], draft, baselines(list), list, 'native')
  for (const update of body.updates) {
    assert.equal(update.backend, 'model-router')
    // The allow-list is not part of this save: it is omitted, so the writer keeps it (or its absence) as stored.
    assert.equal(Object.hasOwn(update, 'profile_routes'), false)
    assert.equal(update.allow_profile_access, false)
    assert.deepEqual(update.slot_policy, slots(), 'slot cards on screen: the spare models are sent')
  }
  // Without slot cards on screen (a non-model method) the spare policy is omitted too.
  const profilesMethod = a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'other'], { ...draft, backend: 'model-router-profiles' }, baselines(list), list, 'native')
  for (const update of profilesMethod.updates) assert.deepEqual(Object.keys(update).sort(), ['allow_profile_access', 'backend', 'expected_digest', 'profile'])
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire'], { ...draft, backend: 'default' }, baselines(list), list, 'native'), /맡기는 방식을 선택/)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire'], { ...draft, backend: 'default' }, baselines(list), list), /맡기는 방식을 선택/)
})

test('the profiles part sends the drafted allow-list and each target stored method and spare models', () => {
  const list = rows({ claire: 'model-router-profiles', other: 'model-router-auto' })
  list[1].native_delegation.auto_policy.heavy = { mode: 'custom', chain: [{ provider: 'own', model: 'own-spare' }] }
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  draft.backend = 'model-router'
  draft.slotPolicy.design = { mode: 'custom', chain: [{ provider: 'draft', model: 'draft-spare' }] }
  draft.profile_routes = { profiles: [{ name: 'other', description: '' }, { name: 'claire', description: '' }], default: 'claire' }
  assert.equal(a.nativeDelegationDraftChanged({ ...a.copyNativeDelegationDraft(list[0].native_delegation), profile_routes: draft.profile_routes }, list[0].native_delegation, 'native'), false)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'other'], draft, baselines(list), list, 'profiles'), /사용 허용에 체크/)
  draft.allowProfileAccess = true
  const body = a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'other'], draft, baselines(list), list, 'profiles')
  const [claire, other] = body.updates
  assert.equal(claire.backend, 'model-router-profiles')
  assert.equal(other.backend, 'model-router-auto')
  for (const update of body.updates) assert.deepEqual(Object.keys(update).sort(), ['allow_profile_access', 'backend', 'expected_digest', 'profile', 'profile_routes'])
  assert.equal(JSON.stringify(body).includes('draft-spare'), false)
  assert.deepEqual(claire.profile_routes, { profiles: [{ name: 'other', description: 'stored by claire' }, { name: 'claire', description: '' }], default: 'claire' })
  assert.equal(other.profile_routes.default, null, 'the automatic method keeps its stored hidden default')
  assert.ok(body.updates.every(update => update.allow_profile_access === true))
  // A snapshot remembers which part it saves.
  const snapshot = { revision: 3, profile: 'claire', nativeTargets: ['claire', 'other'], nativeDraft: draft, nativeBaselines: baselines(list), nativePart: 'profiles' }
  assert.equal(a.nativeDelegationSnapshotCurrent(snapshot, { revision: 3, profiles: list }), true)
  const legacyMethod = { ...snapshot, nativeDraft: { ...draft, backend: 'default' } }
  assert.equal(a.nativeDelegationSnapshotCurrent(legacyMethod, { revision: 3, profiles: list }), true, 'the profiles part ignores the drafted method')
  assert.equal(a.nativeDelegationSnapshotCurrent({ ...legacyMethod, nativePart: 'native' }, { revision: 3, profiles: list }), false, 'the native part never sends default')
  assert.equal(a.nativeDelegationSnapshotCurrent(snapshot, { revision: 4, profiles: list }), false)
})

test('the profiles part refuses a source or target that is not stored on a profile method', () => {
  const list = rows({ claire: 'model-router-profiles', other: 'model-router', legacy: 'default' })
  assert.equal(a.nativeProfileTargetReason(list[0]), '')
  assert.match(a.nativeProfileTargetReason(list[1]), /전문 프로필에 맡기는 방식이 아닙니다\(현재: 작업 종류에 맞는 슬롯 모델 사용\)/)
  assert.match(a.nativeProfileTargetReason(list[2]), /기본 위임 모델 사용 \(이전 방식\)/)
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'legacy'], draft, baselines(list), list, 'profiles'), /legacy: 이 프로필은 전문 프로필에 맡기는 방식이 아닙니다/)
  const fromSlots = a.copyNativeDelegationDraft(list[1].native_delegation)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'other', ['claire'], fromSlots, baselines(list), list, 'profiles'), /불러온 프로필은 전문 프로필에 맡기는 방식이 아닙니다/)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire'], draft, baselines(list), list, 'everything'), /저장 범위/)
})

test('a model copy refuses another profile stored on default or an unlisted method, by name', () => {
  const list = rows({ claire: 'model-router', legacy: 'default', advanced: 'custom-advanced', plain: 'model-router-profiles' })
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'legacy'], draft, baselines(list), list, 'native'), /legacy: 이 프로필은 ‘기본 위임 모델 사용 \(이전 방식\)’ 방식으로 저장되어 있어 그대로 둡니다/)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['advanced'], draft, baselines(list), list, 'native'), /advanced: .*별도 고급 설정/)
  assert.deepEqual(a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'plain'], draft, baselines(list), list, 'native').updates.map(u => [u.profile, u.backend]),
    [['claire', 'model-router'], ['plain', 'model-router']])
  // The loaded profile itself may leave 'default' when its operator picks a plugin method.
  const fromLegacy = a.copyNativeDelegationDraft(list[1].native_delegation)
  fromLegacy.backend = 'model-router'
  assert.deepEqual(a.buildNativeDelegationBatchBody(3, 'legacy', ['legacy'], fromLegacy, baselines(list), list, 'native').updates.map(u => u.backend), ['model-router'])
})

test('a profile copy from an automatic source keeps each profile-only target stored default unless it left the list', () => {
  const list = rows({ claire: 'model-router-auto', keeper: 'model-router-profiles' })
  list[0].native_delegation.profile_routes = { profiles: [{ name: 'keeper', description: '' }], default: null }
  list[1].native_delegation.profile_routes = { profiles: [{ name: 'keeper', description: 'own' }, { name: 'claire', description: '' }], default: 'claire' }
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  draft.profile_routes = { profiles: [{ name: 'keeper', description: '' }, { name: 'claire', description: '' }], default: null }
  draft.allowProfileAccess = true
  const kept = a.buildNativeDelegationBatchBody(3, 'claire', ['claire', 'keeper'], draft, baselines(list), list, 'profiles').updates
  assert.equal(kept[1].profile_routes.default, 'claire', 'the auto source never edits the default, so the target keeps its own')
  draft.profile_routes = { profiles: [{ name: 'keeper', description: '' }], default: null }
  const removed = a.buildNativeDelegationBatchBody(3, 'claire', ['keeper'], draft, baselines(list), list, 'profiles').updates
  assert.equal(removed[0].profile_routes.default, null, 'a default that left the allow-list is cleared')
  // A profile-only source does edit the default, and a profile-only target takes it.
  const profileSource = rows({ claire: 'model-router-profiles', keeper: 'model-router-profiles' })
  profileSource[1].native_delegation.profile_routes = { profiles: [{ name: 'claire', description: '' }], default: 'claire' }
  const edited = a.copyNativeDelegationDraft(profileSource[0].native_delegation)
  edited.profile_routes = { profiles: [{ name: 'claire', description: '' }], default: null }
  assert.equal(a.buildNativeDelegationBatchBody(3, 'claire', ['keeper'], edited, baselines(profileSource), profileSource, 'profiles').updates[0].profile_routes.default, null)
})

test('the method save does not validate an allow-list it does not send, so a deleted specialist is no dead end', () => {
  const list = rows({ claire: 'model-router' })
  list[0].native_delegation.profile_routes = { profiles: [{ name: 'ghost', description: 'deleted' }], default: 'ghost' }
  const draft = a.copyNativeDelegationDraft(list[0].native_delegation)
  draft.backend = 'model-router-profiles'
  const update = a.buildNativeDelegationBatchBody(3, 'claire', ['claire'], draft, baselines(list), list, 'native').updates[0]
  assert.equal(update.backend, 'model-router-profiles')
  assert.equal(Object.hasOwn(update, 'profile_routes'), false)
  // The profile save still refuses to send a name that no longer exists.
  list[0].native_delegation.backend = 'model-router-profiles'
  const routes = a.copyNativeDelegationDraft(list[0].native_delegation)
  assert.throws(() => a.buildNativeDelegationBatchBody(3, 'claire', ['claire'], routes, baselines(list), list, 'profiles'), /허용할 프로필이 있는지/)
})

test('save coverage is computed field by field from the bodies actually sent to every target', () => {
  const slotsA = { design: { follow: 'main', custom: null } }
  const spare = { design: { mode: 'custom', chain: [{ provider: 's', model: 'm' }] } }
  const view = { profile: 'claire', models: { main: 'm1' }, routing: { heavy: 'h', light: 'l' }, slots: slotsA, reenable: [],
    nativeFallback: { enabled: true, chain: [] },
    native: { backend: 'model-router', slotPolicy: spare, autoSlotPolicy: null, descriptionEdits: {},
      profile_routes: { profiles: [{ name: 'other', description: 'd' }], default: 'other' } } }
  const has = (sent, key) => a.submittedEditCoverage(view, sent).has(key)
  // Store saves: models only in the models scope with targets; slots only when the body carries them.
  const models = { operation: '/preview', body: { save_scope: 'models', profile: 'claire', models: { main: 'm1' }, model_targets: ['claire'], routing: { heavy: 'h', light: 'l', slots: slotsA }, routing_profiles: [] } }
  assert.equal(has([models], 'models'), true)
  assert.equal(has([models], 'routing.slots'), false, 'a models-scope body never writes slots')
  assert.equal(has([{ ...models, body: { ...models.body, model_targets: [] } }], 'models'), false)
  const routing = { operation: '/preview', body: { save_scope: 'routing', profile: 'claire', models: {}, model_targets: [], routing: { heavy: 'h', light: 'l', slots: slotsA }, routing_targets: ['claire'], routing_profiles: [] } }
  assert.equal(has([routing], 'routing.slots'), true)
  assert.equal(has([{ ...routing, body: { ...routing.body, routing: { heavy: 'h', light: 'l' } } }], 'routing.slots'), false)
  // Native method save: the spare models count only when every update carries the drafted ones.
  const native = updates => ({ operation: '/delegation-preview', part: 'native', body: { updates } })
  assert.equal(has([native([{ profile: 'claire', backend: 'model-router' }])], 'native.backend'), true)
  assert.equal(has([native([{ profile: 'claire', backend: 'model-router' }])], 'native.slotPolicy'), false)
  assert.equal(has([native([{ profile: 'claire', backend: 'model-router', slot_policy: spare }, { profile: 'x', backend: 'model-router', slot_policy: spare }])], 'native.slotPolicy'), true)
  assert.equal(has([native([])], 'native.backend'), false, 'nothing sent covers nothing')
  // Profile save: the default counts when the loaded profile or every target received it.
  const routes = (profile, defaultName) => ({ profile, profile_routes: { profiles: [{ name: 'other', description: 'd' }], default: defaultName } })
  const profilesBody = updates => ({ operation: '/delegation-preview', part: 'profiles', body: { updates } })
  assert.equal(has([profilesBody([routes('x', null)])], 'profiles.default'), false)
  assert.equal(has([profilesBody([routes('x', null)])], 'profiles.list'), true)
  assert.equal(has([profilesBody([routes('x', null), routes('claire', 'other')])], 'profiles.default'), true)
  assert.equal(has([profilesBody([routes('x', 'other')])], 'profiles.default'), true)
  assert.equal(has([profilesBody([{ profile: 'claire', profile_routes: { profiles: [{ name: 'other', description: 'old' }], default: 'other' } }])], 'profiles.list'), false,
    'the loaded profile must receive the drafted description')
  // The part decides: a native body never covers the profile edits, and the reverse.
  assert.equal(has([native([routes('claire', 'other')])], 'profiles.list'), false)
  assert.equal(has([profilesBody([{ profile: 'claire', backend: 'model-router', ...routes('claire', 'other') }])], 'native.backend'), false)
  // A re-enable tick is saved only by a request naming it in reenable_profiles, never by membership alone.
  const reView = { ...view, reenable: ['other'] }
  const routed = body => a.submittedEditCoverage(reView, [{ operation: '/preview', body: { save_scope: 'routing', profile: 'claire', routing: {}, routing_targets: [], routing_profiles: ['claire', 'other'], ...body } }]).has('reenable')
  assert.equal(routed({}), false)
  assert.equal(routed({ reenable_profiles: ['other'] }), true)
  // Conversation fallback: every update carries the drafted chain.
  assert.equal(has([{ operation: '/fallback-preview', body: { updates: [{ profile: 'claire', native_fallback: { enabled: true, chain: [] } }] } }], 'fallback:native'), true)
  assert.equal(has([{ operation: '/fallback-preview', body: { updates: [{ profile: 'claire', native_fallback: { enabled: false, chain: [] } }] } }], 'fallback:native'), false)
})
