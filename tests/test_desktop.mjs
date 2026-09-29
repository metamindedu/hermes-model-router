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
const helpers = new Function(`${helperSource}\nreturn { scopeFingerprint, copyProfileDraft, toggleName, buildPreviewBody, previewMatchesScope, isPartialReceipt, readableValue }`)()

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

test('preview and apply are separate, scope-guarded requests with no retry affordance after ambiguity', () => {
  assert.match(source, /ctx\.rest\('\/status'\)/)
  assert.match(source, /ctx\.rest\('\/preview', \{ method: 'POST', body \}\)/)
  assert.match(source, /ctx\.rest\('\/apply', \{ method: 'POST', body: \{ plan_id: preview\.plan_id \}, timeoutMs: 180000 \}\)/)
  assert.match(source, /미리보기는 설정을 변경하지 않습니다/)
  assert.match(source, /확인 후 적용/)
  assert.match(source, /다시 적용하지 마세요/)
  assert.match(source, /setPreview\(null\)/)
  assert.match(source, /generationRef\.current !== token/)
  assert.match(source, /isPartialReceipt\(result\)/)
  assert.match(source, /실제 상태 확인 후 편집 재개/)
})

test('presentation uses Hermes theme tokens and does not access local files or shell', () => {
  assert.match(source, /var\(--ui-/)
  assert.doesNotMatch(source, /window\.hermesDesktop|child_process|node:fs|localStorage|\bfetch\s*\(/)
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|\brgb\s*\(/)
  assert.doesNotMatch(source, /<\/?[A-Za-z][^>]*>/, 'disk plugin must use jsx() calls instead of uncompiled JSX')
})
