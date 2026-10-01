import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const pluginPath = fileURLToPath(new URL('../desktop/plugin.js', import.meta.url))
const source = await readFile(pluginPath, 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helperSource = source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')
const helpers = new Function(`${helperSource}\nreturn { MODEL_PRESETS, deepClone, selectedModelPreset, applyModelPresetDraft, selectAllModelTargets, selectNoModelTargets, reconcileModelTargets, allModelTargetsSelected, invalidatePlanState, scopeFingerprint, copyProfileDraft, toggleName, buildPreviewBody, previewMatchesScope, isPartialReceipt, readableValue }`)()

const sampleProfile = {
  name: 'claire',
  models: {
    main: { provider: 'anthropic', model: 'claude-sonnet', reasoning: 'medium' },
    delegation: { provider: 'openai', model: 'gpt-mini', reasoning: 'low' },
    compression: { provider: 'openai', model: 'gpt-mini', reasoning: 'low' },
    title: { provider: 'openai', model: 'gpt-mini', reasoning: 'low' }
  },
  routing: {
    enabled: true,
    heavy: { follow: 'custom', custom: { provider: 'openai', model: 'gpt-pro', reasoning: 'high' } },
    light: { follow: 'delegation', custom: null },
    fallback: {
      enabled: true,
      heavy: { provider: 'anthropic', model: 'claude-opus', reasoning: 'high' },
      light: { provider: 'openai', model: 'gpt-mini', reasoning: 'low' }
    }
  }
}

const expectedPresetModels = {
  openai: {
    main: { provider: 'openai-codex', model: 'gpt-6-astra-900k', reasoning: 'medium' },
    delegation: { provider: 'openai-codex', model: 'gpt-6-luna-900k', reasoning: 'max' },
    compression: { provider: 'openai-codex', model: 'gpt-6-luna-900k', reasoning: 'medium' },
    title: { provider: 'openai-codex', model: 'gpt-6-luna', reasoning: 'none' }
  },
  'non-openai': {
    main: { provider: 'xiaomi', model: 'mimo-v2.6-pro', reasoning: 'max' },
    delegation: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'max' },
    compression: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'medium' },
    title: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'none' }
  }
}

test('editable model presets exactly match the requested four model-role templates', () => {
  assert.deepEqual(Object.fromEntries(helpers.MODEL_PRESETS.map(preset => [preset.id, preset.models])), expectedPresetModels)
  assert.deepEqual(helpers.MODEL_PRESETS.map(preset => preset.id), ['openai', 'non-openai'])
  assert.ok(Object.isFrozen(helpers.MODEL_PRESETS))
  for (const preset of helpers.MODEL_PRESETS) {
    assert.ok(Object.isFrozen(preset.models))
    for (const role of ['main', 'delegation', 'compression', 'title']) assert.ok(Object.isFrozen(preset.models[role]))
    assert.equal(helpers.selectedModelPreset(helpers.deepClone(preset.models)), preset.id)
  }
  const edited = helpers.deepClone(expectedPresetModels.openai)
  edited.title.reasoning = 'low'
  assert.equal(helpers.selectedModelPreset(edited), 'custom')
  edited.title.reasoning = 'none'
  edited.main.extra = true
  assert.equal(helpers.selectedModelPreset(edited), 'custom')
})

test('applying a preset replaces only cloned model roles and never mutates shared templates', () => {
  const draft = helpers.copyProfileDraft(sampleProfile)
  const originalModels = helpers.deepClone(draft.models)
  const originalRouting = helpers.deepClone(draft.routing)
  const next = helpers.applyModelPresetDraft(draft, 'non-openai')
  assert.deepEqual(next.models, expectedPresetModels['non-openai'])
  assert.deepEqual(next.routing, originalRouting)
  assert.notStrictEqual(next.models, draft.models)
  assert.notStrictEqual(next.routing, draft.routing)
  assert.deepEqual(draft.models, originalModels)
  next.models.main.model = 'edited-after-apply'
  next.routing.fallback.heavy.model = 'edited-route'
  assert.deepEqual(helpers.MODEL_PRESETS[1].models, expectedPresetModels['non-openai'])
  assert.equal(draft.routing.fallback.heavy.model, 'claude-opus')
  assert.equal(helpers.applyModelPresetDraft(draft, 'unknown'), null)
})

test('model targets default to all only when uninitialized and preserve intentional empty selection', () => {
  const profileNames = ['default', 'claire', 'research', 'claire']
  assert.deepEqual(helpers.reconcileModelTargets(null, profileNames), ['default', 'claire', 'research'])
  assert.deepEqual(helpers.selectAllModelTargets(profileNames), ['default', 'claire', 'research'])
  assert.deepEqual(helpers.selectNoModelTargets(), [])
  assert.deepEqual(helpers.reconcileModelTargets([], profileNames), [])
  assert.deepEqual(helpers.reconcileModelTargets(['research', 'removed', 'default', 'research'], ['default', 'research', 'new']), ['research', 'default'])
  assert.equal(helpers.allModelTargetsSelected(['research', 'default', 'claire'], profileNames), true)
  assert.equal(helpers.allModelTargetsSelected([], profileNames), false)
})

test('bulk model targets remain separate from routing scope in both all and none preview payloads', () => {
  const draft = helpers.copyProfileDraft(sampleProfile)
  const available = ['default', 'claire', 'research']
  const routingProfiles = ['default']
  const allPayload = helpers.buildPreviewBody(8, 'claire', draft, helpers.selectAllModelTargets(available), routingProfiles)
  const nonePayload = helpers.buildPreviewBody(8, 'claire', draft, helpers.selectNoModelTargets(), routingProfiles)
  assert.deepEqual(allPayload.model_targets, available)
  assert.deepEqual(nonePayload.model_targets, [])
  assert.deepEqual(allPayload.routing_profiles, routingProfiles)
  assert.deepEqual(nonePayload.routing_profiles, routingProfiles)
  assert.deepEqual(allPayload.routing, { ...sampleProfile.routing, enabled: false })
  assert.deepEqual(nonePayload.routing, { ...sampleProfile.routing, enabled: false })
})

test('bulk target actions invalidate pending previews and their prior confirmation generation', () => {
  const preview = { scopeKey: 'scope-a', generation: 12, profile: 'claire' }
  assert.equal(helpers.previewMatchesScope(preview, 'scope-a', 12, 'claire'), true)
  const invalidated = helpers.invalidatePlanState(12)
  assert.deepEqual(invalidated, { generation: 13, preview: null, previewPending: false, reviewed: false })
  assert.equal(helpers.previewMatchesScope(preview, 'scope-a', invalidated.generation, 'claire'), false)
  for (const action of ['selectAllTargets', 'selectNoTargets']) {
    const match = source.match(new RegExp(`const ${action} = \\(\\) => \\{([\\s\\S]*?)\\n  \\}`))
    assert.ok(match, `${action} handler missing`)
    assert.match(match[1], /invalidatePlan\(\)/)
    assert.match(match[1], /setModelTargets\(/)
    assert.doesNotMatch(match[1], /setRoutingProfiles/)
  }
})

test('profile draft cloning preserves every model and route field without aliasing source state', () => {
  const draft = helpers.copyProfileDraft(sampleProfile)
  assert.deepEqual(draft, { models: sampleProfile.models, routing: sampleProfile.routing })
  assert.notStrictEqual(draft.models, sampleProfile.models)
  assert.notStrictEqual(draft.routing.fallback.heavy, sampleProfile.routing.fallback.heavy)
  draft.routing.fallback.heavy.model = 'changed'
  assert.equal(sampleProfile.routing.fallback.heavy.model, 'claude-opus')
  assert.equal(helpers.copyProfileDraft({ models: {}, routing: null }), null)
})

test('preview payload carries full draft and keeps model targets separate from routing profiles', () => {
  const draft = helpers.copyProfileDraft(sampleProfile)
  const modelTargets = ['claire', 'research']
  const routingProfiles = ['default', 'claire']
  const payload = helpers.buildPreviewBody(17, 'claire', draft, modelTargets, routingProfiles)
  assert.deepEqual(payload, {
    expected_revision: 17,
    profile: 'claire',
    models: sampleProfile.models,
    model_targets: ['claire', 'research'],
    routing: sampleProfile.routing,
    routing_profiles: ['default', 'claire']
  })
  payload.models.main.model = 'mutated'
  payload.routing.heavy.custom.provider = 'mutated'
  payload.model_targets.push('later')
  assert.equal(draft.models.main.model, 'claude-sonnet')
  assert.equal(draft.routing.heavy.custom.provider, 'openai')
  assert.deepEqual(modelTargets, ['claire', 'research'])
})

test('scope identity changes across connection, profile, and gateway changes', () => {
  const base = helpers.scopeFingerprint('local', 'default', 'open')
  assert.notEqual(helpers.scopeFingerprint('remote', 'default', 'open'), base)
  assert.notEqual(helpers.scopeFingerprint('local', 'claire', 'open'), base)
  assert.notEqual(helpers.scopeFingerprint('local', 'default', 'connecting'), base)
})

test('checkbox selection remains a unique independent profile list', () => {
  assert.deepEqual(helpers.toggleName(['default', 'claire', 'claire'], 'claire', false), ['default'])
  assert.deepEqual(helpers.toggleName(['default'], 'claire', true), ['default', 'claire'])
  assert.deepEqual(helpers.toggleName([], 'default', true), ['default'])
})

test('pending preview is valid only for its captured scope, generation, and profile', () => {
  const preview = { scopeKey: 'scope-a', generation: 8, profile: 'claire' }
  assert.equal(helpers.previewMatchesScope(preview, 'scope-a', 8, 'claire'), true)
  assert.equal(helpers.previewMatchesScope(preview, 'scope-b', 8, 'claire'), false)
  assert.equal(helpers.previewMatchesScope(preview, 'scope-a', 9, 'claire'), false)
  assert.equal(helpers.previewMatchesScope(preview, 'scope-a', 8, 'default'), false)
  assert.equal(helpers.previewMatchesScope(null, 'scope-a', 8, 'claire'), false)
})

test('partial apply receipts are distinguishable and safe model values are readable', () => {
  assert.equal(helpers.isPartialReceipt({ partial: true }), true)
  assert.equal(helpers.isPartialReceipt({ status: 'partial' }), true)
  assert.equal(helpers.isPartialReceipt({ complete: false }), true)
  assert.equal(helpers.isPartialReceipt({ status: 'ok', complete: true }), false)
  assert.equal(helpers.readableValue({ provider: 'openai', model: 'gpt-mini', reasoning: 'low' }), 'provider: openai · model: gpt-mini · reasoning: low')
  assert.equal(helpers.readableValue(null), '—')
})

test('disk plugin uses only supported SDK imports and registers the Korean native page', () => {
  const imports = [...source.matchAll(/\bfrom\s+['"]([^'"]+)['"]/g)].map(match => match[1])
  assert.ok(imports.length > 0)
  assert.ok(imports.every(specifier => ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'].includes(specifier)), imports.join(', '))
  assert.match(source, /id:\s*PLUGIN_ID/)
  assert.match(source, /const PLUGIN_ID = 'model-router'/)
  assert.match(source, /defaultEnabled:\s*false/)
  assert.match(source, /data:\s*\{ path: ROUTE_PATH \}/)
  assert.match(source, /label: '모델 및 라우팅'/)
  assert.match(source, /label: '모델 및 라우팅 열기'/)
  assert.match(source, /ROUTE_PATH = '\/model-router'/)
  assert.match(source, /scopeFingerprint\(connectionId, activeProfile, gateway\)/)
})

test('form exposes four model roles, distinct application scopes, and accessible field names', () => {
  for (const role of ['main', 'delegation', 'compression', 'title']) assert.ok(source.includes(`id: '${role}'`) || source.includes(`id: '${role}',`), `${role} role missing`)
  assert.match(source, /모델 설정 적용 대상/)
  assert.match(source, /라우팅 활성 프로필/)
  assert.match(source, /model_targets:/)
  assert.match(source, /routing_profiles:/)
  assert.match(source, /공급자 ID/)
  assert.match(source, /모델 ID/)
  assert.match(source, /추론 강도/)
  assert.match(source, /aria-label/)
  assert.match(source, /새 규칙은 이후에 시작하는 세션/)
  assert.match(source, /실제 설정:/)
  assert.match(source, /차이 \$\{drift.length\}건/)
})

test('single save internally validates and applies with scope guards and no confirmation gate', () => {
  assert.match(source, /ctx\.rest\('\/status'\)/)
  assert.match(source, /ctx\.rest\(operation, \{ method: 'POST', body: prepared\.body \}\)/)
  assert.match(source, /ctx\.rest\('\/apply', \{ method: 'POST', body: \{ plan_id: planId \}, timeoutMs: 180000 \}\)/)
  assert.match(source, /const planId = result\.plan_id/)
  assert.doesNotMatch(source, /id: 'confirm-preview'/)
  assert.match(source, /id: 'global-save'/)
  assert.match(source, /다시 적용하지 마세요/)
  assert.match(source, /isSaveCurrent\(snapshot, token\)/)
  assert.match(source, /isPartialReceipt\(receipt\)/)
  assert.match(source, /실제 상태 확인 후 편집 재개/)
})

test('presentation uses Hermes theme tokens and does not access local files or shell', () => {
  assert.match(source, /var\(--ui-/)
  assert.doesNotMatch(source, /window\.hermesDesktop|child_process|node:fs|localStorage|\bfetch\s*\(/)
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|\brgb\s*\(/)
  assert.doesNotMatch(source, /<\/?[A-Za-z][^>]*>/, 'disk plugin must use jsx() calls instead of uncompiled JSX')
})
