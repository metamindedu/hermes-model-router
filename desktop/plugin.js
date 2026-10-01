import {
  Badge,
  Button,
  Checkbox,
  Codicon,
  COMPOSER_AREAS,
  GlyphSpinner,
  Input,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  host,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const PLUGIN_ID = 'model-router'
const ROUTE_PATH = '/model-router'
const ROLES = [
  { id: 'main', label: '기본 대화', description: '일반 채팅과 기본 응답에 사용합니다.' },
  { id: 'delegation', label: '작업 위임', description: '하위 작업과 가벼운 보조 작업에 사용합니다.' },
  { id: 'compression', label: '대화 압축', description: '긴 대화 요약과 맥락 압축에 사용합니다.' },
  { id: 'title', label: '제목 생성', description: '대화 제목을 자동으로 만들 때 사용합니다.' }
]

const styles = {
  page: {
    boxSizing: 'border-box',
    width: '100%',
    maxWidth: '68rem',
    marginInline: 'auto',
    padding: 'clamp(1rem, 3vw, 2.25rem)',
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
    color: 'var(--ui-text-primary)'
  },
  header: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' },
  title: { margin: 0, fontSize: '1.5rem', lineHeight: 1.2, fontWeight: 650, letterSpacing: '-0.025em' },
  subtitle: { margin: '0.55rem 0 0', color: 'var(--ui-text-secondary)', lineHeight: 1.55, maxWidth: '48rem' },
  section: { display: 'flex', flexDirection: 'column', gap: '0.9rem', border: '1px solid var(--ui-stroke-tertiary)', borderRadius: '0.9rem', padding: '1rem' },
  sectionHeading: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' },
  heading: { margin: 0, fontSize: '1rem', fontWeight: 620 },
  hint: { margin: 0, color: 'var(--ui-text-tertiary)', fontSize: '0.82rem', lineHeight: 1.5 },
  fields: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 15rem), 1fr))', gap: '0.8rem 1rem' },
  field: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.4rem', color: 'var(--ui-text-secondary)', fontSize: '0.82rem' },
  fieldName: { color: 'var(--ui-text-secondary)', fontWeight: 560 },
  roleGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 24rem), 1fr))', gap: '0.8rem' },
  roleCard: { minWidth: 0, boxSizing: 'border-box', padding: '1rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' },
  roleTitle: { margin: 0, fontSize: '0.95rem', fontWeight: 620 },
  choiceGroup: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
  choiceRow: { display: 'flex', gap: '0.65rem', alignItems: 'flex-start', color: 'var(--ui-text-primary)' },
  choiceCopy: { display: 'flex', flexDirection: 'column', gap: '0.15rem', minWidth: 0 },
  profileList: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 13rem), 1fr))', gap: '0.45rem 1rem' },
  profileChoice: { minWidth: 0, display: 'flex', alignItems: 'center', gap: '0.6rem', paddingBlock: '0.3rem' },
  presetGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 19rem), 1fr))', gap: '0.7rem' },
  presetCard: { boxSizing: 'border-box', width: '100%', minWidth: 0, padding: '0.9rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.75rem', background: 'transparent', color: 'var(--ui-text-primary)', font: 'inherit', textAlign: 'left', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '0.55rem' },
  presetSelected: { border: '2px solid var(--ui-accent)', padding: 'calc(0.9rem - 1px)' },
  presetRoleList: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.25rem 0.7rem' },
  presetRole: { color: 'var(--ui-text-secondary)', fontSize: '0.75rem', lineHeight: 1.45, overflowWrap: 'anywhere' },
  selectionToolbar: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem', flexWrap: 'wrap' },
  cardSection: { border: '1px solid var(--ui-stroke-tertiary)', borderRadius: '0.9rem', padding: '1rem' },
  notice: { padding: '0.75rem 0', color: 'var(--ui-text-secondary)', lineHeight: 1.55 },
  warning: { borderInlineStart: '2px solid var(--ui-accent)', paddingInlineStart: '0.8rem', color: 'var(--ui-text-secondary)', lineHeight: 1.55 },
  message: { padding: '0.75rem 0', color: 'var(--ui-text-secondary)', lineHeight: 1.5 },
  changes: { display: 'flex', flexDirection: 'column', gap: '0.6rem' },
  change: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.55rem 0.8rem', padding: '0.75rem 0', borderBottom: '1px solid var(--ui-stroke-tertiary)', alignItems: 'start' },
  changeLabel: { minWidth: 0, gridColumn: '1 / -1', fontWeight: 600, overflowWrap: 'anywhere' },
  changeValue: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.25rem' },
  value: { minWidth: 0, fontFamily: 'var(--font-mono, ui-monospace, monospace)', fontSize: '0.78rem', color: 'var(--ui-text-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' },
  actions: { display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap', paddingTop: '0.4rem' },
  statusLine: { display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' },
  actual: { margin: 0, color: 'var(--ui-text-tertiary)', fontSize: '0.78rem', lineHeight: 1.45, overflowWrap: 'anywhere' },
  fieldset: { margin: 0, padding: 0, border: 0, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.8rem' }
}

const progressStyles = {
  root: { marginBlock: '0.15rem', minWidth: 0 },
  details: { borderBottom: '1px solid var(--ui-stroke-tertiary)', color: 'var(--ui-text-primary)' },
  summary: { display: 'flex', alignItems: 'center', gap: '0.45rem', padding: '0.35rem 0', cursor: 'pointer', listStyle: 'none', fontSize: '0.78rem', fontWeight: 600 },
  list: { display: 'flex', flexDirection: 'column', paddingBottom: '0.25rem' },
  row: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '0.7rem', alignItems: 'center', padding: '0.45rem 0', borderTop: '1px solid var(--ui-stroke-tertiary)', minWidth: 0 },
  copy: { display: 'flex', flexDirection: 'column', gap: '0.12rem', minWidth: 0 },
  heading: { display: 'flex', alignItems: 'baseline', gap: '0.4rem', minWidth: 0, overflow: 'hidden', whiteSpace: 'nowrap' },
  title: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.78rem', fontWeight: 580 },
  meta: { flex: '0 0 auto', color: 'var(--ui-text-tertiary)', fontSize: '0.7rem' },
  activity: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ui-text-secondary)', fontSize: '0.72rem' },
  trailing: { display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--ui-text-tertiary)', fontSize: '0.7rem', fontVariantNumeric: 'tabular-nums' },
  state: { color: 'var(--ui-text-tertiary)', fontSize: '0.68rem' },
  message: { margin: '0.25rem 0 0.45rem', color: 'var(--ui-text-tertiary)', fontSize: '0.72rem' }
}

const COMPOSER_SURFACE_SELECTOR = '[data-slot="composer-surface"]'
const PROGRESS_FINISHED_RETENTION_MS = 8_000

// Pure helpers are kept separate so the routing payload and stale-scope policy
// can be exercised without loading the Desktop renderer SDK in Node tests.
function freezeDeep(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) freezeDeep(child)
    Object.freeze(value)
  }
  return value
}

export const MODEL_PRESETS = freezeDeep([
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'OpenAI 계열 모델 조합',
    models: {
      main: { provider: 'openai-codex', model: 'gpt-6-astra-900k', reasoning: 'medium' },
      delegation: { provider: 'openai-codex', model: 'gpt-6-luna-900k', reasoning: 'max' },
      compression: { provider: 'openai-codex', model: 'gpt-6-luna-900k', reasoning: 'medium' },
      title: { provider: 'openai-codex', model: 'gpt-6-luna', reasoning: 'none' }
    }
  },
  {
    id: 'non-openai',
    name: 'Non-OpenAI',
    description: '비-OpenAI 모델 조합',
    models: {
      main: { provider: 'xiaomi', model: 'mimo-v2.6-pro', reasoning: 'max' },
      delegation: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'max' },
      compression: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'medium' },
      title: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'none' }
    }
  }
])

export function deepClone(value) {
  return JSON.parse(JSON.stringify(value))
}

function sameValue(left, right) {
  if (left === right) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false
  const leftKeys = Object.keys(left).sort()
  const rightKeys = Object.keys(right).sort()
  return leftKeys.length === rightKeys.length &&
    leftKeys.every((key, index) => key === rightKeys[index] && sameValue(left[key], right[key]))
}

export function selectedModelPreset(models) {
  return MODEL_PRESETS.find(preset => sameValue(models, preset.models))?.id || 'custom'
}

export function applyModelPresetDraft(draft, presetId) {
  const preset = MODEL_PRESETS.find(item => item.id === presetId)
  if (!preset || !draft || typeof draft !== 'object' || !draft.routing) return null
  return { ...deepClone(draft), models: deepClone(preset.models) }
}

function uniqueProfileNames(names) {
  return [...new Set(Array.isArray(names) ? names.filter(name => typeof name === 'string' && name.length > 0) : [])]
}

export function selectAllModelTargets(profileNames) {
  return uniqueProfileNames(profileNames)
}

export function selectNoModelTargets() {
  return []
}

export function reconcileModelTargets(selected, profileNames) {
  const available = uniqueProfileNames(profileNames)
  if (!Array.isArray(selected)) return available
  const valid = new Set(available)
  return [...new Set(selected.filter(name => valid.has(name)))]
}

export function allModelTargetsSelected(selected, profileNames) {
  const available = uniqueProfileNames(profileNames)
  return available.length > 0 && available.every(name => Array.isArray(selected) && selected.includes(name))
}

export function invalidatePlanState(generation) {
  return { generation: generation + 1, preview: null, previewPending: false, reviewed: false }
}

export function scopeFingerprint(connectionId, profile, gateway) {
  return JSON.stringify([connectionId || 'local', profile || 'default', gateway || 'idle'])
}

export function copyProfileDraft(profile) {
  if (!profile || typeof profile !== 'object' || !profile.models || !profile.routing) return null
  return deepClone({ models: profile.models, routing: profile.routing })
}

export function toggleName(names, name, checked) {
  const set = new Set(Array.isArray(names) ? names : [])
  if (checked) set.add(name)
  else set.delete(name)
  return [...set]
}

export function buildPreviewBody(revision, profile, draft, modelTargets, routingProfiles) {
  return {
    expected_revision: revision,
    profile,
    models: deepClone(draft.models),
    model_targets: Array.isArray(modelTargets) ? [...modelTargets] : [],
    routing: { ...deepClone(draft.routing), enabled: routingProfiles.includes(profile) },
    routing_profiles: [...routingProfiles]
  }
}

export function previewMatchesScope(preview, scopeKey, generation, profile) {
  return Boolean(
    preview &&
    preview.scopeKey === scopeKey &&
    preview.generation === generation &&
    preview.profile === profile
  )
}

export function isPartialReceipt(receipt) {
  return Boolean(receipt && (receipt.partial === true || receipt.status === 'partial' || receipt.complete === false))
}

export function readableValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value === 'object') {
    const route = ['provider', 'model', 'reasoning'].filter(key => value[key] !== undefined)
    if (route.length) return route.map(key => `${key}: ${value[key] ?? ''}`).join(' · ')
    try { return JSON.stringify(value) } catch { return '확인할 수 없음' }
  }
  return String(value)
}

export const NATIVE_FALLBACK_PRESETS = freezeDeep([
  {
    id: 'audited-non-openai',
    name: '검증된 Non-OpenAI 체인',
    description: '감사된 순서: Xiaomi → DeepSeek',
    chain: [
      { provider: 'xiaomi', model: 'mimo-v2.6-pro' },
      { provider: 'deepseek', model: 'deepseek-flash' }
    ]
  },
  {
    id: 'openai-api',
    name: 'OpenAI API 단일 대체',
    description: '추가 API 사용량 비용이 발생할 수 있습니다.',
    chain: [{ provider: 'openai-api', model: 'gpt-6-astra' }]
  }
])

export const ROUTING_FALLBACK_PRESETS = freezeDeep([
  {
    id: 'openai-api',
    name: 'OpenAI API 쌍',
    description: 'Heavy Astra · Light Luna (API 과금)',
    heavy: { provider: 'openai-api', model: 'gpt-6-astra', reasoning: 'max' },
    light: { provider: 'openai-api', model: 'gpt-5.6-luna', reasoning: 'max' }
  },
  {
    id: 'non-openai',
    name: 'Non-OpenAI BAT 쌍',
    description: 'Heavy Xiaomi · Light DeepSeek (max 추론)',
    heavy: { provider: 'xiaomi', model: 'mimo-v2.6-pro', reasoning: 'max' },
    light: { provider: 'deepseek', model: 'deepseek-flash', reasoning: 'max' }
  }
])

export const SUPPORTED_FALLBACK_CAPABILITIES = freezeDeep({
  native_trigger: 'hermes_runtime',
  native_execution: 'continue_conversation',
  native_reasoning: 'profile_overrides',
  routing_trigger: 'subscription_exhaustion_before_tools',
  routing_execution: 'fresh_task',
  routing_max_retries: 1
})

export function fallbackCapabilitiesSupported(capabilities) {
  return Boolean(capabilities && Object.entries(SUPPORTED_FALLBACK_CAPABILITIES).every(
    ([key, value]) => capabilities[key] === value
  ))
}

export function copyNativeFallbackDraft(native) {
  if (!native || typeof native.enabled !== 'boolean' || !Array.isArray(native.chain)) return null
  return {
    enabled: native.enabled,
    chain: native.chain.map(entry => ({
      provider: typeof entry?.provider === 'string' ? entry.provider : '',
      model: typeof entry?.model === 'string' ? entry.model : ''
    }))
  }
}

export function copyRoutingFallbackDraft(routing) {
  if (!routing || typeof routing.enabled !== 'boolean') return null
  const copyRoute = route => route && typeof route === 'object'
    ? {
        provider: typeof route.provider === 'string' ? route.provider : '',
        model: typeof route.model === 'string' ? route.model : '',
        reasoning: typeof route.reasoning === 'string' ? route.reasoning : ''
      }
    : null
  return { enabled: routing.enabled, heavy: copyRoute(routing.heavy), light: copyRoute(routing.light) }
}

export const DELEGATION_FALLBACK_MODES = freezeDeep([
  { value: 'default', label: '기본 규칙 사용' },
  { value: 'off', label: '사용 안 함' },
  { value: 'custom', label: '위임 전용 목록' }
])

export function validDelegationFallbackState(state) {
  const modes = DELEGATION_FALLBACK_MODES.map(item => item.value)
  const routesAreSimple = routes => Array.isArray(routes) && routes.every(route =>
    route && typeof route.provider === 'string' && typeof route.model === 'string' &&
    Object.keys(route).every(key => key === 'provider' || key === 'model')
  )
  const consentIsKnown = consent => consent === null || Boolean(
    consent && consent.policy_version === 1 &&
    typeof consent.selection_digest === 'string' && consent.selection_digest.length > 0 &&
    ['explicit', 'legacy-approved'].includes(consent.source) &&
    typeof consent.allow_additional_cost === 'boolean' &&
    typeof consent.allow_task_rerun === 'boolean'
  )
  return Boolean(
    state && typeof state === 'object' &&
    typeof state.managed === 'boolean' && typeof state.editable === 'boolean' &&
    modes.includes(state.mode) && Array.isArray(state.chain) && routesAreSimple(state.chain) &&
    (state.actual_mode === null || modes.includes(state.actual_mode)) &&
    routesAreSimple(state.actual_chain) && typeof state.drift === 'boolean' &&
    Array.isArray(state.warnings) && state.warnings.every(warning => typeof warning === 'string') &&
    Object.prototype.hasOwnProperty.call(state, 'consent') && consentIsKnown(state.consent)
  )
}

export function copyDelegationFallbackDraft(delegation) {
  if (!validDelegationFallbackState(delegation)) return null
  const draft = {
    mode: delegation.mode,
    chain: delegation.chain.map(({ provider, model }) => ({ provider, model }))
  }
  return delegationFallbackValidation(draft) ? null : draft
}

export function applyNativeFallbackPresetDraft(draft, presetId) {
  const preset = NATIVE_FALLBACK_PRESETS.find(item => item.id === presetId)
  if (!preset || !draft || typeof draft !== 'object') return null
  return { ...deepClone(draft), chain: deepClone(preset.chain) }
}

export function applyRoutingFallbackPresetDraft(draft, presetId) {
  const preset = ROUTING_FALLBACK_PRESETS.find(item => item.id === presetId)
  if (!preset || !draft || typeof draft !== 'object') return null
  return { ...deepClone(draft), heavy: deepClone(preset.heavy), light: deepClone(preset.light) }
}

export function reconcileFallbackTargets(selected, profileNames) {
  const available = uniqueProfileNames(profileNames)
  if (!Array.isArray(selected)) return null
  const valid = new Set(available)
  return [...new Set(selected.filter(name => valid.has(name)))]
}

export function selectFallbackTargets(selected, sourceProfile, profileNames) {
  if (Array.isArray(selected)) return reconcileFallbackTargets(selected, profileNames)
  return sourceProfile && uniqueProfileNames(profileNames).includes(sourceProfile) ? [sourceProfile] : []
}

export function selectFallbackSourceTarget(sourceProfile, profileNames) {
  return sourceProfile && uniqueProfileNames(profileNames).includes(sourceProfile) ? [sourceProfile] : []
}

export function fallbackConsentReady(consent, scope) {
  return Boolean(
    consent && consent.policy_version === 1 &&
    typeof consent.selection_digest === 'string' && consent.selection_digest.length > 0 &&
    consent.allow_additional_cost === true &&
    (scope !== 'delegation' || consent.allow_task_rerun === false) &&
    (scope !== 'routing' || consent.allow_task_rerun === true)
  )
}

export function fallbackTargetNeedsConsent(scope, row, next) {
  if (!row || !next || (scope !== 'delegation' && next.enabled !== true)) return false
  if (scope === 'native') {
    const current = row.fallbacks?.native
    const sameSelection = current && sameValue(
      { enabled: current.enabled === true, chain: current.chain || [] }, next
    )
    return !sameSelection || current.managed !== true || !fallbackConsentReady(current.consent, 'native')
  }
  if (scope === 'routing') {
    const current = row.fallbacks?.routing
    const sameSelection = current && sameValue(
      { enabled: current.enabled === true, heavy: current.heavy ?? null, light: current.light ?? null }, next
    )
    return !sameSelection || !fallbackConsentReady(current?.consent, 'routing')
  }
  if (scope === 'delegation') {
    if (next.mode === 'off') return false
    const current = row.fallbacks?.delegation
    const sameSelection = current && sameValue(
      { mode: current.mode, chain: current.chain || [] }, next
    )
    return !sameSelection || !fallbackConsentReady(current?.consent, 'delegation')
  }
  return false
}

export function nativeFallbackValidation(draft) {
  if (!draft || typeof draft.enabled !== 'boolean' || !Array.isArray(draft.chain)) return '대화 대체 상태를 확인할 수 없습니다.'
  if (draft.chain.length > 5) return '대화 대체 체인은 최대 5개 모델까지 지원합니다.'
  if (draft.chain.some(item => !item || typeof item.provider !== 'string' || !item.provider.trim() || typeof item.model !== 'string' || !item.model.trim())) return '각 체인 항목에 공급자 ID와 모델 ID를 입력하세요.'
  const identities = draft.chain.map(item => JSON.stringify([item.provider, item.model]))
  if (new Set(identities).size !== identities.length) return '대화 대체 체인에 중복 공급자·모델 조합이 있습니다.'
  if (draft.enabled && draft.chain.length === 0) return '대화를 대체하려면 모델을 하나 이상 추가하세요.'
  return ''
}

export function delegationFallbackValidation(draft) {
  const modes = DELEGATION_FALLBACK_MODES.map(item => item.value)
  if (!draft || !modes.includes(draft.mode) || !Array.isArray(draft.chain)) return '위임 fallback 상태를 확인할 수 없습니다.'
  if (draft.mode !== 'custom') return draft.chain.length === 0 ? '' : '기본 규칙과 사용 안 함 모드에는 위임 전용 체인을 둘 수 없습니다.'
  if (draft.chain.length === 0) return '위임 전용 목록에 모델을 하나 이상 추가하세요.'
  if (draft.chain.length > 5) return '위임 전용 체인은 최대 5개 모델까지 지원합니다.'
  if (draft.chain.some(item => !item || typeof item.provider !== 'string' || !item.provider.trim() || typeof item.model !== 'string' || !item.model.trim())) return '각 위임 전용 항목에 공급자 ID와 모델 ID를 입력하세요.'
  const identities = draft.chain.map(item => JSON.stringify([item.provider, item.model]))
  if (new Set(identities).size !== identities.length) return '위임 전용 목록에 중복 공급자·모델 조합이 있습니다.'
  return ''
}

export function routeIdentity(route) {
  return route && typeof route.provider === 'string' && typeof route.model === 'string'
    ? JSON.stringify([route.provider, route.model])
    : ''
}

export function primaryRouteForFallback(row, role) {
  const configured = row?.routing?.[role]
  if (configured?.follow === 'custom' && configured.custom) return configured.custom
  const modelRole = role === 'heavy' ? 'main' : 'delegation'
  return row?.actual_models?.[modelRole] || row?.models?.[modelRole] || null
}

export function routingFallbackValidation(draft, targetRows = []) {
  if (!draft || typeof draft.enabled !== 'boolean') return '코딩 작업 대체 상태를 확인할 수 없습니다.'
  if (!draft.enabled) return ''
  for (const role of ['heavy', 'light']) {
    const route = draft[role]
    if (!route || ['provider', 'model', 'reasoning'].some(key => typeof route[key] !== 'string' || !route[key].trim())) {
      return `${role === 'heavy' ? 'Heavy' : 'Light'} 대체 모델의 공급자·모델·추론 강도를 입력하세요.`
    }
  }
  if (routeIdentity(draft.heavy) === routeIdentity(draft.light)) return 'Heavy와 Light 대체 모델은 서로 달라야 합니다.'
  for (const row of targetRows) {
    for (const role of ['heavy', 'light']) {
      if (routeIdentity(draft[role]) && routeIdentity(draft[role]) === routeIdentity(primaryRouteForFallback(row, role))) {
        return `${row.name}의 ${role === 'heavy' ? 'Heavy' : 'Light'} 기본 모델과 대체 모델은 달라야 합니다.`
      }
    }
  }
  return ''
}

export function buildFallbackPreviewBody(revision, scope, targetNames, value, profiles, costConfirmed, rerunConfirmed) {
  const byName = new Map((Array.isArray(profiles) ? profiles : []).map(row => [row.name, row]))
  const selected = uniqueProfileNames(targetNames).filter(name => byName.has(name))
  const nativeValue = scope === 'native' ? {
    enabled: value.enabled === true,
    chain: (value.chain || []).map(({ provider, model }) => ({ provider, model }))
  } : null
  const routingValue = scope === 'routing' ? {
    enabled: value.enabled === true,
    heavy: value.heavy ? deepClone(value.heavy) : null,
    light: value.light ? deepClone(value.light) : null
  } : null
  const delegationValue = scope === 'delegation' ? {
    mode: value.mode,
    chain: value.mode === 'custom' ? (value.chain || []).map(({ provider, model }) => ({ provider, model })) : []
  } : null
  const updates = selected.map(profile => scope === 'native'
    ? { profile, native_fallback: deepClone(nativeValue) }
    : scope === 'routing'
      ? { profile, routing_fallback: deepClone(routingValue) }
      : { profile, delegation_fallback: deepClone(delegationValue) })
  const scopeValue = scope === 'native' ? nativeValue : scope === 'routing' ? routingValue : delegationValue
  const confirmations = selected.filter(profile => fallbackTargetNeedsConsent(scope, byName.get(profile), scopeValue))
    .map(profile => ({
      profile,
      scope,
      allow_additional_cost: costConfirmed === true,
      allow_task_rerun: scope === 'routing' && rerunConfirmed === true
    }))
  return { expected_revision: revision, updates, confirmations }
}

export function fallbackPreviewMatchesScope(preview, scopeKey, generation, profile, scope) {
  return Boolean(preview && preview.scopeKey === scopeKey && preview.generation === generation &&
    preview.profile === profile && preview.scope === scope)
}

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0
}

function visibleComposerSurface(element, doc) {
  if (!element || element.isConnected !== true || !doc?.defaultView?.getComputedStyle) return false
  if (typeof element.getClientRects === 'function' && element.getClientRects().length === 0) return false
  let current = element
  while (current && current !== doc) {
    if (current.hidden === true || current.getAttribute?.('aria-hidden') === 'true') return false
    const style = doc.defaultView.getComputedStyle(current)
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false
    if (Number.isFinite(Number.parseFloat(style.opacity)) && Number.parseFloat(style.opacity) <= 0) return false
    current = current.parentElement
  }
  return true
}

export function progressScopeAllowed(snapshot, root, doc) {
  if (!root || root.isConnected !== true || !doc || !snapshot) return false
  const { activeSessionId, focusedSessionId, focusedStoredSessionId, connectionId, profile, focusedSessionOwner } = snapshot
  if (![activeSessionId, focusedSessionId, focusedStoredSessionId, connectionId, profile].every(nonEmptyString)) return false
  if (focusedSessionId !== activeSessionId) return false
  if (!focusedSessionOwner || focusedSessionOwner.connectionId !== connectionId || focusedSessionOwner.profile !== profile) return false
  const rootSurface = typeof root.closest === 'function' ? root.closest(COMPOSER_SURFACE_SELECTOR) : null
  if (!rootSurface || rootSurface.isConnected !== true || !visibleComposerSurface(rootSurface, doc)) return false
  const surfaces = Array.from(doc.querySelectorAll(COMPOSER_SURFACE_SELECTOR) || []).filter(surface => visibleComposerSurface(surface, doc))
  return surfaces.length === 1 && surfaces[0] === rootSurface
}

export function progressResponseMatchesScope(response, scope) {
  if (!response || response.schema !== 1 || response.profile !== scope.profile ||
    response.parent_session_id !== scope.parentSessionId || response.ui_session_id !== scope.uiSessionId ||
    !Array.isArray(response.jobs) || response.jobs.length > 16 || typeof response.has_more !== 'boolean') return false
  return response.jobs.every(job => job && nonEmptyString(job.job_id) && nonEmptyString(job.process_id) &&
    nonEmptyString(job.title) && nonEmptyString(job.role) && nonEmptyString(job.model) &&
    nonEmptyString(job.status) && Number.isFinite(job.started_at) &&
    (job.finished_at === null || Number.isFinite(job.finished_at)) && typeof job.activity === 'string')
}

export function formatElapsed(startedAt, endedAt) {
  if (!Number.isFinite(startedAt) || !Number.isFinite(endedAt)) return '—'
  const totalSeconds = Math.max(0, Math.floor((endedAt - startedAt) / 1000))
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes >= 60) return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${seconds}`
  return `${minutes}:${seconds}`
}

function processEntryId(entry) {
  // The native process.list contract calls this registry id `session_id`; match it exactly.
  if (nonEmptyString(entry?.process_id)) return entry.process_id
  return nonEmptyString(entry?.session_id) ? entry.session_id : ''
}

function terminalProgressState(entry, backendStatus) {
  const nativeStatus = typeof entry?.status === 'string' ? entry.status.toLowerCase() : ''
  const reason = typeof entry?.completion_reason === 'string' ? entry.completion_reason.toLowerCase() : ''
  if (nativeStatus === 'running') return 'running'
  if (nativeStatus === 'killed' || nativeStatus === 'stopped' || ['killed', 'stopped', 'cancelled', 'canceled', 'terminated'].includes(reason)) return 'stopped'
  if (nativeStatus !== 'exited') return null
  if (typeof entry.exit_code === 'number' && entry.exit_code !== 0) return 'failed'
  if (entry.exit_code === 0 && backendStatus === 'completed') return 'completed'
  return 'unverified'
}

export function reconcileProgressJobs(response, processSnapshot, now, previousTerminalTimes = new Map(), scopeKey = '') {
  if (!response || !Array.isArray(processSnapshot?.processes)) return { jobs: [], terminalTimes: new Map() }
  const processRows = new Map(processSnapshot.processes.map(row => [processEntryId(row), row]).filter(([id]) => id))
  const terminalTimes = new Map()
  const jobs = []
  for (const job of response.jobs) {
    const process = processRows.get(job.process_id)
    if (!process) continue
    const state = terminalProgressState(process, job.status)
    if (!state) continue
    if (state === 'running') {
      jobs.push({ ...job, displayState: state, terminalAt: null })
      continue
    }
    const key = `${scopeKey}\u0000${job.job_id}\u0000${job.process_id}`
    const terminalAt = Number.isFinite(job.finished_at)
      ? job.finished_at
      : (previousTerminalTimes.get(key) ?? now)
    terminalTimes.set(key, terminalAt)
    if (now - terminalAt < PROGRESS_FINISHED_RETENTION_MS) {
      jobs.push({ ...job, displayState: state, terminalAt })
    }
  }
  return { jobs, terminalTimes }
}

function Field({ id, label, value, onChange, disabled = false, hint }) {
  return jsxs('label', {
    htmlFor: id,
    style: styles.field,
    children: [
      jsx('span', { style: styles.fieldName, children: label }),
      jsx(Input, {
        id,
        style: { width: '100%', minWidth: 0, boxSizing: 'border-box' },
        value: value ?? '',
        onChange: event => onChange(event.target.value),
        disabled,
        'aria-label': label
      }),
      hint ? jsx('span', { style: styles.hint, children: hint }) : null
    ]
  })
}

function RoleRouteFields({ prefix, route, onChange, disabled }) {
  const value = route && typeof route === 'object' ? route : {}
  const update = field => next => onChange(field, next)
  return jsxs('div', {
    style: styles.fields,
    children: [
      jsx(Field, { id: `${prefix}-provider`, label: '공급자 ID', value: value.provider, onChange: update('provider'), disabled }),
      jsx(Field, { id: `${prefix}-model`, label: '모델 ID', value: value.model, onChange: update('model'), disabled }),
      jsx(Field, { id: `${prefix}-reasoning`, label: '추론 강도', value: value.reasoning, onChange: update('reasoning'), disabled, hint: '현재 값을 보존합니다. 지원되는 값은 미리보기에서 검증됩니다.' })
    ]
  })
}

function ChoiceField({ id, label, value, onChange, options, disabled }) {
  return jsxs('label', {
    htmlFor: id,
    style: styles.field,
    children: [
      jsx('span', { style: styles.fieldName, children: label }),
      jsxs(Select, {
        value,
        onValueChange: onChange,
        disabled,
        children: [
          jsx(SelectTrigger, { id, 'aria-label': label, children: jsx(SelectValue, {}) }),
          jsx(SelectContent, { children: options.map(option => jsx(SelectItem, { value: option.value, children: option.label }, option.value)) })
        ]
      })
    ]
  })
}

function CheckRow({ id, label, detail, checked, onChange, disabled = false }) {
  return jsxs('div', {
    style: styles.choiceRow,
    children: [
      jsx(Checkbox, { id, checked, disabled, onCheckedChange: value => onChange(value === true), 'aria-label': label }),
      jsxs('div', {
        style: styles.choiceCopy,
        children: [
          jsx('label', { htmlFor: id, style: { color: 'var(--ui-text-primary)', cursor: disabled ? 'default' : 'pointer' }, children: label }),
          detail ? jsx('span', { style: styles.hint, children: detail }) : null
        ]
      })
    ]
  })
}

function section(title, description, content, trailing = null) {
  return jsxs('section', {
    style: styles.section,
    children: [
      jsxs('div', {
        style: styles.sectionHeading,
        children: [
          jsxs('div', { children: [jsx('h2', { style: styles.heading, children: title }), description ? jsx('p', { style: { ...styles.hint, marginTop: '0.3rem' }, children: description }) : null] }),
          trailing
        ]
      }),
      content
    ]
  })
}

function StatusView({ profile }) {
  if (!profile) return null
  const actual = profile.actual_models && typeof profile.actual_models === 'object' ? profile.actual_models : {}
  const drift = Array.isArray(profile.drift) ? profile.drift : []
  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
    children: [
      jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: drift.length ? 'warn' : 'muted', children: drift.length ? `차이 ${drift.length}건` : '설정 일치' }), jsx('span', { style: styles.hint, children: `프로필: ${profile.name}` })] }),
      drift.length ? jsx('div', { role: 'status', style: styles.warning, children: jsxs('div', { children: [jsx('strong', { children: '저장 설정과 실제 설정이 다릅니다.' }), jsx('div', { style: { marginTop: '0.25rem' }, children: drift.map((item, index) => jsx('div', { children: readableValue(item) }, index)) })] }) }) : null,
      jsxs('details', { children: [
        jsx('summary', { style: { color: 'var(--ui-text-tertiary)', cursor: 'pointer', fontSize: '0.8rem' }, children: '실제 모델 상태 보기' }),
        jsx('div', { style: { ...styles.fields, marginTop: '0.65rem' }, children: ROLES.map(role => jsxs('div', { style: styles.actual, children: [jsx('strong', { children: role.label }), jsx('div', { children: readableValue(actual[role.id]) })] }, role.id)) })
      ] }),
    ]
  })
}

export async function nativeBackendCall(path, options = {}) {
  const operation = { '/status': 'status', '/preview': 'preview', '/fallback-preview': 'fallback-preview', '/apply': 'apply', '/progress': 'progress' }[path]
  if (!operation) throw new Error('지원하지 않는 플러그인 요청입니다.')
  const profile = options.profile || host.state.profile.get() || 'default'
  const reply = await host.request('cli.exec', {
    argv: ['--profile', profile, 'model-router', operation, '--body', JSON.stringify(options.body || {})],
    profile,
    timeout: 180
  })
  if (reply.blocked) throw new Error(reply.hint || '요청이 차단되었습니다.')
  const line = String(reply.output || '').split(/\r?\n/).find(value => value.startsWith('MODEL_ROUTER_JSON:'))
  if (!line) throw new Error('플러그인 응답을 확인할 수 없습니다. 활성화 상태를 확인하세요.')
  let data
  try { data = JSON.parse(line.slice('MODEL_ROUTER_JSON:'.length)) }
  catch { throw new Error('플러그인 응답이 잘렸거나 손상됐습니다. 상태를 다시 확인하세요.') }
  if (reply.code !== 0 || data.error) throw new Error(data.message || '요청이 완료되지 않았습니다.')
  return data
}

const NULL_HOST_ATOM = { get: () => null, subscribe: () => () => {} }

function useOptionalHostValue(key) {
  const candidate = host.state?.[key]
  return useValue(candidate && typeof candidate.get === 'function' ? candidate : NULL_HOST_ATOM)
}

function readProgressScope() {
  const read = key => {
    const atom = host.state?.[key]
    return atom && typeof atom.get === 'function' ? atom.get() : null
  }
  return {
    activeSessionId: read('activeSessionId'),
    focusedSessionId: read('focusedSessionId'),
    focusedStoredSessionId: read('focusedStoredSessionId'),
    connectionId: read('connectionId'),
    profile: read('profile'),
    focusedSessionOwner: read('focusedSessionOwner')
  }
}

function ComposerProgress() {
  const activeSessionId = useOptionalHostValue('activeSessionId')
  const focusedSessionId = useOptionalHostValue('focusedSessionId')
  const focusedStoredSessionId = useOptionalHostValue('focusedStoredSessionId')
  const connectionId = useOptionalHostValue('connectionId')
  const profile = useOptionalHostValue('profile')
  const focusedSessionOwner = useOptionalHostValue('focusedSessionOwner')
  const rootRef = useRef(null)
  const [surfaceAllowed, setSurfaceAllowed] = useState(false)
  const [clockNow, setClockNow] = useState(() => Date.now())
  const [documentVisible, setDocumentVisible] = useState(() => typeof document !== 'undefined' && document.visibilityState !== 'hidden')
  const [stoppingIds, setStoppingIds] = useState([])
  const [cancelError, setCancelError] = useState('')
  const terminalTimesRef = useRef(new Map())
  const scope = { activeSessionId, focusedSessionId, focusedStoredSessionId, connectionId, profile, focusedSessionOwner }
  const scopeKey = JSON.stringify([connectionId, profile, focusedStoredSessionId, activeSessionId])
  const doc = typeof document === 'undefined' ? null : document
  const currentlyAllowed = progressScopeAllowed(scope, rootRef.current, doc)

  useEffect(() => {
    if (!doc) {
      setSurfaceAllowed(false)
      return undefined
    }
    let disposed = false
    let resizeObserver = null
    let mutationObserver = null
    let attributeObserver = null
    const observed = new Set()
    const observeSurfaces = () => {
      const surfaces = new Set(Array.from(doc.querySelectorAll(COMPOSER_SURFACE_SELECTOR) || []))
      if (resizeObserver) {
        for (const surface of observed) {
          if (!surfaces.has(surface)) {
            resizeObserver.unobserve?.(surface)
            observed.delete(surface)
          }
        }
        for (const surface of surfaces) {
          if (!observed.has(surface)) {
            resizeObserver.observe(surface)
            observed.add(surface)
          }
        }
      }
      if (attributeObserver) {
        attributeObserver.disconnect()
        const targets = new Set()
        for (const surface of surfaces) {
          let current = surface
          while (current) {
            targets.add(current)
            if (current === doc.body || current === doc.documentElement) break
            current = current.parentElement
          }
        }
        for (const target of targets) attributeObserver.observe(target, {
          attributes: true,
          attributeFilter: ['aria-hidden', 'class', 'hidden', 'style']
        })
      }
    }
    const refresh = () => {
      if (disposed) return
      const next = progressScopeAllowed(readProgressScope(), rootRef.current, doc)
      setSurfaceAllowed(current => current === next ? current : next)
      observeSurfaces()
    }
    const hasSurface = node => Boolean(node?.nodeType === 1 && (
      node.matches?.(COMPOSER_SURFACE_SELECTOR) || node.querySelector?.(COMPOSER_SURFACE_SELECTOR)
    ))
    const ResizeObserverType = doc.defaultView?.ResizeObserver
    if (typeof ResizeObserverType === 'function') {
      resizeObserver = new ResizeObserverType(refresh)
    }
    const MutationObserverType = doc.defaultView?.MutationObserver
    if (typeof MutationObserverType === 'function') {
      mutationObserver = new MutationObserverType(records => {
        if (records.some(record => [...(record.addedNodes || []), ...(record.removedNodes || [])].some(hasSurface))) refresh()
      })
      mutationObserver.observe(doc.body || doc.documentElement, { childList: true, subtree: true })
      attributeObserver = new MutationObserverType(refresh)
    }
    refresh()
    return () => {
      disposed = true
      resizeObserver?.disconnect()
      mutationObserver?.disconnect()
      attributeObserver?.disconnect()
    }
  }, [doc, activeSessionId, focusedSessionId, focusedStoredSessionId, connectionId, profile,
    focusedSessionOwner?.connectionId, focusedSessionOwner?.profile])

  useEffect(() => {
    if (!doc) return undefined
    const update = () => setDocumentVisible(doc.visibilityState !== 'hidden')
    update()
    doc.addEventListener?.('visibilitychange', update)
    return () => doc.removeEventListener?.('visibilitychange', update)
  }, [doc])

  const queryEnabled = surfaceAllowed && currentlyAllowed
  const progressQuery = useQuery({
    queryKey: ['model-router-progress', connectionId, profile, focusedStoredSessionId, activeSessionId],
    enabled: Boolean(queryEnabled),
    retry: false,
    refetchInterval: query => query.state.error ? 15_000 : 3_000,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal } = {}) => {
      const captured = { connectionId, profile, parentSessionId: focusedStoredSessionId, uiSessionId: activeSessionId }
      const isCurrent = () => {
        const live = readProgressScope()
        return live.connectionId === captured.connectionId && live.profile === captured.profile &&
          live.focusedStoredSessionId === captured.parentSessionId && live.activeSessionId === captured.uiSessionId &&
          progressScopeAllowed(live, rootRef.current, typeof document === 'undefined' ? null : document)
      }
      if (signal?.aborted || !isCurrent()) throw new Error('stale progress scope')
      const body = { parent_session_id: captured.parentSessionId, ui_session_id: captured.uiSessionId }
      const [response, processSnapshot] = await Promise.all([
        nativeBackendCall('/progress', { body, profile: captured.profile }),
        host.request('process.list', { session_id: captured.uiSessionId })
      ])
      if (signal?.aborted || !isCurrent()) throw new Error('stale progress scope')
      const responseScope = { profile: captured.profile, parentSessionId: captured.parentSessionId, uiSessionId: captured.uiSessionId }
      if (!progressResponseMatchesScope(response, responseScope) || !Array.isArray(processSnapshot?.processes)) {
        throw new Error('invalid progress response')
      }
      const reconciled = reconcileProgressJobs(response, processSnapshot, Date.now(), terminalTimesRef.current, scopeKey)
      terminalTimesRef.current = reconciled.terminalTimes
      return { scopeKey, jobs: reconciled.jobs, hasMore: response.has_more }
    }
  })

  const matchingData = queryEnabled && !progressQuery.isError && progressQuery.data?.scopeKey === scopeKey
    ? progressQuery.data
    : null
  const renderNow = matchingData?.jobs.some(job => job.displayState === 'running') ? clockNow : Date.now()
  const displayJobs = (matchingData?.jobs || []).filter(job =>
    job.displayState === 'running' || (job.terminalAt !== null && renderNow - job.terminalAt < PROGRESS_FINISHED_RETENTION_MS)
  )
  const hasRunning = displayJobs.some(job => job.displayState === 'running')

  useEffect(() => {
    if (!queryEnabled || !hasRunning || !documentVisible) return undefined
    setClockNow(Date.now())
    const timer = setInterval(() => setClockNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [queryEnabled, hasRunning, documentVisible])

  const stopProcess = async processId => {
    if (!nonEmptyString(processId) || !currentlyAllowed || stoppingIds.includes(processId)) return
    const capturedSessionId = activeSessionId
    const capturedScopeKey = scopeKey
    const live = readProgressScope()
    if (JSON.stringify([live.connectionId, live.profile, live.focusedStoredSessionId, live.activeSessionId]) !== capturedScopeKey ||
      live.activeSessionId !== capturedSessionId || !progressScopeAllowed(live, rootRef.current, doc)) return
    setCancelError('')
    setStoppingIds(current => current.includes(processId) ? current : [...current, processId])
    try {
      await host.request('process.kill', { session_id: capturedSessionId, process_id: processId })
      await progressQuery.refetch()
    } catch {
      setCancelError('중지 결과를 확인할 수 없습니다. 현재 상태를 새로 확인하세요.')
    } finally {
      setStoppingIds(current => current.filter(id => id !== processId))
    }
  }

  const root = children => jsx('div', { ref: rootRef, style: progressStyles.root, 'data-model-router-progress': true, children })
  if (!queryEnabled) return root(null)
  if (!displayJobs.length) {
    if (progressQuery.isError) return root(jsx('div', { role: 'status', style: progressStyles.message, children: '서브 에이전트 진행 상황을 확인할 수 없습니다.' }))
    if (progressQuery.isPending || progressQuery.isFetching) return root(jsx('div', { role: 'status', style: progressStyles.message, children: jsx(GlyphSpinner, {}) }))
    return root(null)
  }

  const statusLabel = { running: '실행 중', completed: '완료', failed: '실패', stopped: '중지', unverified: '결과 확인 필요' }
  return root(jsxs('details', {
    style: progressStyles.details,
    children: [
      jsxs('summary', { style: progressStyles.summary, children: [
        jsx(Codicon, { name: 'chevron-right', size: '0.75rem' }),
        `서브 에이전트 작업 ${displayJobs.length}개`,
        progressQuery.isFetching ? jsx(GlyphSpinner, {}) : null
      ] }),
      jsxs('div', { style: progressStyles.list, children: [
        ...displayJobs.map(job => {
          const role = job.role.toLowerCase() === 'heavy' ? 'Heavy' : job.role.toLowerCase() === 'light' ? 'Light' : '작업'
          const endpoint = job.terminalAt ?? clockNow
          return jsxs('div', { style: progressStyles.row, children: [
            jsxs('div', { style: progressStyles.copy, children: [
              jsxs('div', { style: progressStyles.heading, children: [
                jsx('span', { title: job.title, style: progressStyles.title, children: job.title }),
                jsx('span', { style: progressStyles.meta, children: role }),
                jsx('span', { title: job.model, style: { ...progressStyles.meta, maxWidth: '12rem', overflow: 'hidden', textOverflow: 'ellipsis' }, children: job.model }),
                job.displayState !== 'running' ? jsx('span', { style: progressStyles.state, children: statusLabel[job.displayState] }) : null
              ] }),
              jsx('div', { title: job.activity, style: progressStyles.activity, children: job.activity })
            ] }),
            jsxs('div', { style: progressStyles.trailing, children: [
              jsx('time', { children: formatElapsed(job.started_at, endpoint) }),
              job.displayState === 'running' ? jsx(Button, {
                size: 'sm', variant: 'ghost', disabled: stoppingIds.includes(job.process_id),
                'aria-label': '위임 작업 중지',
                onClick: () => void stopProcess(job.process_id),
                children: jsxs('span', { style: { display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }, children: [
                  jsx(Codicon, { name: 'close', size: '0.75rem' }),
                  stoppingIds.includes(job.process_id) ? '중지 중…' : '중지'
                ] })
              }) : null
            ] })
          ] }, job.job_id)
        }),
        matchingData.hasMore ? jsx('p', { style: progressStyles.message, children: '최신 작업 16개를 표시합니다.' }) : null,
        cancelError ? jsx('p', { role: 'status', style: progressStyles.message, children: cancelError }) : null
      ] })
    ]
  }))
}

function RouterPage({ ctx: pluginContext }) {
  // Native CLI RPC uses the same Service as REST and works without restarting
  // an already-running Desktop backend to mount newly installed REST routes.
  const ctx = { rest: nativeBackendCall }
  const activeProfile = useValue(host.state.profile)
  const connectionId = useValue(host.state.connectionId)
  const gateway = useValue(host.state.gateway)
  const scopeKey = scopeFingerprint(connectionId, activeProfile, gateway)
  const [readyScope, setReadyScope] = useState(scopeKey)
  const [selectedProfile, setSelectedProfile] = useState(null)
  const [draft, setDraft] = useState(null)
  const [modelTargets, setModelTargets] = useState(null)
  const [routingProfiles, setRoutingProfiles] = useState([])
  const [fallbackDrafts, setFallbackDrafts] = useState({ native: null, routing: null, delegation: null })
  const [fallbackBaselines, setFallbackBaselines] = useState({ native: null, routing: null, delegation: null })
  const [fallbackTargets, setFallbackTargets] = useState({ native: null, routing: null, delegation: null })
  const [fallbackConsentChecks, setFallbackConsentChecks] = useState({ nativeCost: false, routingCost: false, routingRerun: false, delegationCost: false })
  const [fallbackPreview, setFallbackPreview] = useState(null)
  const [fallbackPreviewPending, setFallbackPreviewPending] = useState(false)
  const [fallbackReviewed, setFallbackReviewed] = useState(false)
  const [fallbackError, setFallbackError] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewPending, setPreviewPending] = useState(false)
  const [applyPending, setApplyPending] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [pageError, setPageError] = useState('')
  const [applyOutcome, setApplyOutcome] = useState(null)
  const [needsReload, setNeedsReload] = useState(false)
  const generationRef = useRef(0)
  const applyPendingRef = useRef(false)
  const needsReloadRef = useRef(false)
  const applyScopeRef = useRef(null)
  const selectedProfileRef = useRef(null)
  selectedProfileRef.current = selectedProfile

  const statusKey = ['model-router', 'status', scopeKey]
  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => ctx.rest('/status'),
    retry: false,
    staleTime: 0
  })
  const profiles = Array.isArray(statusQuery.data?.profiles) ? statusQuery.data.profiles : []

  useEffect(() => {
    if (readyScope === scopeKey) return
    generationRef.current += 1
    setPreview(null)
    setPreviewPending(false)
    setReviewed(false)
    setSelectedProfile(null)
    setDraft(null)
    setModelTargets(null)
    setRoutingProfiles([])
    setFallbackDrafts({ native: null, routing: null, delegation: null })
    setFallbackBaselines({ native: null, routing: null, delegation: null })
    setFallbackTargets({ native: null, routing: null, delegation: null })
    setFallbackConsentChecks({ nativeCost: false, routingCost: false, routingRerun: false, delegationCost: false })
    setFallbackPreview(null)
    setFallbackPreviewPending(false)
    setFallbackReviewed(false)
    setFallbackError('')
    setPageError('')
    if (applyPendingRef.current) {
      applyPendingRef.current = false
      setApplyPending(false)
      needsReloadRef.scopeKey = applyScopeRef.current || readyScope
      setApplyOutcome({ kind: 'unknown', message: '적용 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 적용하지 마세요. 적용을 시작한 원래 프로필·연결로 돌아가 실제 상태를 새로고침하세요.' })
      needsReloadRef.current = true
      setNeedsReload(true)
    } else if (!needsReloadRef.current) {
      setApplyOutcome(null)
    }
    setReadyScope(scopeKey)
  }, [readyScope, scopeKey])

  useEffect(() => {
    if (readyScope !== scopeKey || !statusQuery.data || selectedProfile !== null) return
    const row = profiles.find(item => item.name === statusQuery.data.current_profile) || profiles[0]
    if (!row) return
    setSelectedProfile(row.name)
    setDraft(copyProfileDraft(row))
    const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
    const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
    const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
    setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
    setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setModelTargets(current => reconcileModelTargets(current, profiles.map(item => item.name)))
    setRoutingProfiles(profiles.filter(item => item.routing?.enabled === true).map(item => item.name))
  }, [readyScope, scopeKey, statusQuery.data, selectedProfile, profiles])

  const invalidatePlan = ({ resetFallbackConsent = false } = {}) => {
    const invalidated = invalidatePlanState(generationRef.current)
    generationRef.current = invalidated.generation
    setPreview(invalidated.preview)
    setPreviewPending(invalidated.previewPending)
    setReviewed(invalidated.reviewed)
    setFallbackPreview(null)
    setFallbackPreviewPending(false)
    setFallbackReviewed(false)
    setFallbackError('')
    if (resetFallbackConsent) setFallbackConsentChecks({ nativeCost: false, routingCost: false, routingRerun: false, delegationCost: false })
    setPageError('')
  }
  const updateDraft = updater => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setDraft(current => current ? updater(current) : current)
  }
  const currentRow = profiles.find(item => item.name === selectedProfile) || null
  const profileNames = profiles.map(item => item.name)
  const nativeFallbackTargets = selectFallbackTargets(fallbackTargets.native, selectedProfile, profileNames)
  const routingFallbackTargets = selectFallbackTargets(fallbackTargets.routing, selectedProfile, profileNames)
  const delegationFallbackTargets = selectFallbackTargets(fallbackTargets.delegation, selectedProfile, profileNames)
  const nativeFallbackRows = nativeFallbackTargets.map(name => profiles.find(item => item.name === name)).filter(Boolean)
  const routingFallbackRows = routingFallbackTargets.map(name => profiles.find(item => item.name === name)).filter(Boolean)
  const delegationFallbackRows = delegationFallbackTargets.map(name => profiles.find(item => item.name === name)).filter(Boolean)
  const fallbackCapabilities = statusQuery.data?.fallback_capabilities
  const fallbackSupported = fallbackCapabilitiesSupported(fallbackCapabilities)
  const nativeFallbackDraft = fallbackDrafts.native
  const routingFallbackDraft = fallbackDrafts.routing
  const delegationFallbackDraft = fallbackDrafts.delegation
  const nativeFallbackDraftChanged = Boolean(nativeFallbackDraft && fallbackBaselines.native && !sameValue(nativeFallbackDraft, fallbackBaselines.native))
  const routingFallbackDraftChanged = Boolean(routingFallbackDraft && fallbackBaselines.routing && !sameValue(routingFallbackDraft, fallbackBaselines.routing))
  const delegationFallbackDraftChanged = Boolean(delegationFallbackDraft && fallbackBaselines.delegation && !sameValue(delegationFallbackDraft, fallbackBaselines.delegation))
  const nativeFallbackError = nativeFallbackDraft ? nativeFallbackValidation(nativeFallbackDraft) : '이 프로필의 대화 fallback 상태를 지원하지 않습니다.'
  const routingFallbackError = routingFallbackDraft ? routingFallbackValidation(routingFallbackDraft, routingFallbackRows) : '이 프로필의 코딩 fallback 상태를 지원하지 않습니다.'
  const delegationFallbackError = delegationFallbackDraft ? delegationFallbackValidation(delegationFallbackDraft) : '백엔드가 위임 fallback 상태를 제공하지 않습니다. 상태를 새로고침하세요.'
  const nativeNeedsConsent = nativeFallbackRows.some(row => fallbackTargetNeedsConsent('native', row, nativeFallbackDraft))
  const routingNeedsConsent = routingFallbackRows.some(row => fallbackTargetNeedsConsent('routing', row, routingFallbackDraft))
  const delegationNeedsConsent = delegationFallbackRows.some(row => fallbackTargetNeedsConsent('delegation', row, delegationFallbackDraft))
  const nativeConsentSatisfied = !nativeNeedsConsent || fallbackConsentChecks.nativeCost
  const routingConsentSatisfied = !routingNeedsConsent || (fallbackConsentChecks.routingCost && fallbackConsentChecks.routingRerun)
  const delegationConsentSatisfied = !delegationNeedsConsent || fallbackConsentChecks.delegationCost
  const selectedTargets = reconcileModelTargets(modelTargets, profileNames)
  const allTargetsSelected = allModelTargetsSelected(selectedTargets, profileNames)
  const targetSummary = allTargetsSelected ? `전체 ${profileNames.length}개 프로필` : `${selectedTargets.length}/${profileNames.length}개 프로필`
  const disabled = applyPending || needsReload || statusQuery.isFetching || !selectedProfile || !draft
  const validPreview = previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile)
  const renderGeneration = generationRef.current
  const activeRoutes = draft?.routing || {}
  const routingSummary = `무거운 작업: ${activeRoutes.heavy?.follow === 'custom' ? '별도 모델' : '기본 모델'} · 가벼운 작업: ${activeRoutes.light?.follow === 'custom' ? '별도 모델' : '위임 모델'}`

  const selectProfile = name => {
    if (applyPendingRef.current || needsReloadRef.current) return
    const row = profiles.find(item => item.name === name)
    if (!row) return
    invalidatePlan({ resetFallbackConsent: true })
    setSelectedProfile(name)
    setDraft(copyProfileDraft(row))
    const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
    const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
    const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
    setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
    setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setModelTargets(current => reconcileModelTargets(current, profileNames))
  }

  const applyPreset = presetId => updateDraft(current => applyModelPresetDraft(current, presetId))

  const toggleModelTarget = (name, checked) => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(current => toggleName(current, name, checked))
  }

  const selectAllTargets = () => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(selectAllModelTargets(profileNames))
  }

  const selectNoTargets = () => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(selectNoModelTargets())
  }

  const toggleRoutingProfile = (name, checked) => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setRoutingProfiles(current => toggleName(current, name, checked))
    if (name === selectedProfile) {
      setDraft(current => current ? { ...current, routing: { ...current.routing, enabled: checked } } : current)
    }
  }

  const updateRole = (role, field, value) => updateDraft(current => ({
    ...current,
    models: { ...current.models, [role]: { ...current.models[role], [field]: value } }
  }))
  const updateRoutingRoute = (group, field, value) => updateDraft(current => ({
    ...current,
    routing: {
      ...current.routing,
      [group]: {
        ...current.routing[group],
        custom: { ...(current.routing[group].custom || {}), [field]: value }
      }
    }
  }))
  const changeFollow = (group, value) => updateDraft(current => ({ ...current, routing: { ...current.routing, [group]: { follow: value, custom: value === 'custom' ? { ...(current.routing[group].custom || current.models[group === 'heavy' ? 'main' : 'delegation']) } : null } } }))
  const toggleRoutingEnabled = checked => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setDraft(current => current ? { ...current, routing: { ...current.routing, enabled: checked } } : current)
    if (selectedProfile) setRoutingProfiles(current => toggleName(current, selectedProfile, checked))
  }

  const updateFallbackDraft = (scope, updater) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    invalidatePlan({ resetFallbackConsent: true })
    setFallbackDrafts(current => ({
      ...current,
      [scope]: current[scope] ? updater(current[scope]) : current[scope]
    }))
  }

  const updateFallbackTarget = (scope, name, checked) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const selected = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    invalidatePlan({ resetFallbackConsent: true })
    setFallbackTargets(current => ({ ...current, [scope]: toggleName(selected, name, checked) }))
  }

  const chooseFallbackTargets = (scope, mode) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    let selected = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    if (mode === 'source') selected = selectFallbackSourceTarget(selectedProfile, profileNames)
    if (mode === 'all') {
      const eligible = scope === 'native'
        ? profiles.filter(row => row.fallbacks?.native?.editable === true).map(row => row.name)
        : scope === 'delegation'
          ? profiles.filter(row => validDelegationFallbackState(row.fallbacks?.delegation) && row.fallbacks.delegation.editable === true).map(row => row.name)
          : profileNames
      selected = selectAllModelTargets(eligible)
    }
    if (mode === 'none') selected = selectNoModelTargets()
    invalidatePlan({ resetFallbackConsent: true })
    setFallbackTargets(current => ({ ...current, [scope]: [...selected] }))
  }

  const updateFallbackConsent = (field, checked) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const invalidated = invalidatePlanState(generationRef.current)
    generationRef.current = invalidated.generation
    setPreview(null)
    setPreviewPending(false)
    setReviewed(false)
    setFallbackPreview(null)
    setFallbackPreviewPending(false)
    setFallbackReviewed(false)
    setFallbackError('')
    setPageError('')
    setFallbackConsentChecks(current => ({ ...current, [field]: checked }))
  }

  const canPreviewFallback = scope => {
    if (!fallbackSupported || disabled || applyPendingRef.current || needsReloadRef.current || fallbackPreviewPending || !selectedProfile || !statusQuery.data) return false
    const targets = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    const rows = scope === 'native' ? nativeFallbackRows : scope === 'routing' ? routingFallbackRows : delegationFallbackRows
    if (targets.length === 0 || rows.length !== targets.length) return false
    if (scope === 'native') {
      if (!nativeFallbackDraft || currentRow?.fallbacks?.native?.editable !== true || rows.some(row => row.fallbacks?.native?.editable !== true)) return false
      return !nativeFallbackError && nativeConsentSatisfied
    }
    if (scope === 'routing') {
      if (!routingFallbackDraft || rows.some(row => !row.fallbacks?.routing)) return false
      return !routingFallbackError && routingConsentSatisfied
    }
    if (!delegationFallbackDraft || !validDelegationFallbackState(currentRow?.fallbacks?.delegation) || currentRow.fallbacks.delegation.editable !== true ||
      rows.some(row => !validDelegationFallbackState(row.fallbacks?.delegation) || row.fallbacks.delegation.editable !== true)) return false
    return !delegationFallbackError && delegationConsentSatisfied
  }

  const handleFallbackPreview = async scope => {
    if (renderGeneration !== generationRef.current || applyPendingRef.current || needsReloadRef.current || !canPreviewFallback(scope)) return
    const capturedScope = scopeKey
    const capturedProfile = selectedProfile
    const targetNames = scope === 'native' ? [...nativeFallbackTargets] : scope === 'routing' ? [...routingFallbackTargets] : [...delegationFallbackTargets]
    const value = deepClone(scope === 'native' ? nativeFallbackDraft : scope === 'routing' ? routingFallbackDraft : delegationFallbackDraft)
    const costConfirmed = scope === 'native' ? fallbackConsentChecks.nativeCost : scope === 'routing' ? fallbackConsentChecks.routingCost : fallbackConsentChecks.delegationCost
    const rerunConfirmed = scope === 'routing' && fallbackConsentChecks.routingRerun
    const token = ++generationRef.current
    setPreview(null)
    setReviewed(false)
    setFallbackPreview(null)
    setFallbackReviewed(false)
    setFallbackError('')
    setPageError('')
    setFallbackPreviewPending(true)
    try {
      const body = buildFallbackPreviewBody(
        statusQuery.data.revision, scope, targetNames, value, profiles, costConfirmed, rerunConfirmed
      )
      const result = await ctx.rest('/fallback-preview', { method: 'POST', body })
      if (generationRef.current !== token || selectedProfileRef.current !== capturedProfile ||
        scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) return
      if (!result || typeof result.plan_id !== 'string' || !Array.isArray(result.changes)) {
        throw new Error('대체 설정 미리보기 응답이 올바르지 않습니다. 설정은 변경되지 않았습니다.')
      }
      setFallbackPreview({ ...result, scopeKey: capturedScope, generation: token, profile: capturedProfile, scope })
    } catch (error) {
      if (generationRef.current === token && selectedProfileRef.current === capturedProfile) {
        setFallbackError({ scope, message: error?.message || '대체 설정 미리보기를 만들지 못했습니다.' })
      }
    } finally {
      if (generationRef.current === token) setFallbackPreviewPending(false)
    }
  }

  const handleFallbackApply = async scope => {
    if (!fallbackPreviewMatchesScope(fallbackPreview, scopeKey, generationRef.current, selectedProfile, scope) ||
      !fallbackReviewed || applyPendingRef.current || needsReloadRef.current || disabled || !fallbackPreview?.plan_id) return
    const token = generationRef.current
    const capturedScope = scopeKey
    const capturedProfile = selectedProfile
    const planId = fallbackPreview.plan_id
    applyPendingRef.current = true
    applyScopeRef.current = capturedScope
    setApplyPending(true)
    setPreview(null)
    setReviewed(false)
    setFallbackPreview(null)
    setFallbackReviewed(false)
    setPageError('')
    setFallbackError('')
    try {
      const result = await ctx.rest('/apply', { method: 'POST', body: { plan_id: planId }, timeoutMs: 180000 })
      if (scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope ||
        selectedProfileRef.current !== capturedProfile) {
        generationRef.current += 1
        return
      }
      if (generationRef.current !== token) return
      const partial = isPartialReceipt(result)
      if (result?.ok === false || result?.status === 'failed' || result?.status === 'error') {
        setApplyOutcome({ kind: 'unknown', message: result.error || '백엔드가 적용 실패를 보고했습니다. 다시 적용하지 말고 실제 상태를 새로고침하세요.', result })
      } else {
        setApplyOutcome({ kind: partial ? 'partial' : 'success', result })
      }
      needsReloadRef.scopeKey = capturedScope
      needsReloadRef.current = true
      setNeedsReload(true)
    } catch (error) {
      if (scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope ||
        selectedProfileRef.current !== capturedProfile) {
        generationRef.current += 1
        return
      }
      if (generationRef.current === token) {
        setApplyOutcome({ kind: 'unknown', message: error?.message || '적용 결과를 확인할 수 없습니다.' })
        needsReloadRef.scopeKey = capturedScope
        needsReloadRef.current = true
        setNeedsReload(true)
      }
    } finally {
      if (generationRef.current === token) {
        applyPendingRef.current = false
        setApplyPending(false)
      }
    }
  }

  const handlePreview = async () => {
    if (!currentRow || !draft || !statusQuery.data || disabled || applyPendingRef.current || needsReloadRef.current) return
    const token = ++generationRef.current
    const capturedScope = scopeKey
    const capturedProfile = selectedProfile
    setPreview(null)
    setReviewed(false)
    setPageError('')
    setPreviewPending(true)
    try {
      const body = buildPreviewBody(statusQuery.data.revision, capturedProfile, draft, selectedTargets, routingProfiles)
      const result = await ctx.rest('/preview', { method: 'POST', body })
      if (generationRef.current !== token || scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) return
      if (!result || typeof result.plan_id !== 'string' || !Array.isArray(result.changes)) {
        throw new Error('미리보기 응답이 올바르지 않습니다. 설정은 변경되지 않았습니다.')
      }
      setPreview({ ...result, scopeKey: capturedScope, generation: token, profile: capturedProfile })
    } catch (error) {
      if (generationRef.current === token) setPageError(error?.message || '미리보기를 만들지 못했습니다.')
    } finally {
      if (generationRef.current === token) setPreviewPending(false)
    }
  }

  const handleApply = async () => {
    if (!previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile) || !reviewed || applyPendingRef.current || needsReloadRef.current || disabled || !preview?.plan_id) return
    const token = generationRef.current
    const capturedScope = scopeKey
    applyPendingRef.current = true
    applyScopeRef.current = capturedScope
    setApplyPending(true)
    setPreview(null)
    setReviewed(false)
    setFallbackPreview(null)
    setFallbackReviewed(false)
    setPageError('')
    try {
      const result = await ctx.rest('/apply', { method: 'POST', body: { plan_id: preview.plan_id }, timeoutMs: 180000 })
      if (scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) {
        generationRef.current += 1
        return
      }
      if (generationRef.current !== token) return
      const partial = isPartialReceipt(result)
      if (result?.ok === false || result?.status === 'failed' || result?.status === 'error') {
        setApplyOutcome({ kind: 'unknown', message: result.error || '백엔드가 적용 실패를 보고했습니다. 다시 적용하지 말고 실제 상태를 새로고침하세요.', result })
      } else {
        setApplyOutcome({ kind: partial ? 'partial' : 'success', result })
      }
      needsReloadRef.scopeKey = capturedScope
      needsReloadRef.current = true
      setNeedsReload(true)
    } catch (error) {
      if (scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) {
        generationRef.current += 1
        return
      }
      if (generationRef.current === token) {
        setApplyOutcome({ kind: 'unknown', message: error?.message || '적용 결과를 확인할 수 없습니다.' })
        needsReloadRef.scopeKey = capturedScope
        needsReloadRef.current = true
        setNeedsReload(true)
      }
    } finally {
      if (generationRef.current === token) {
        applyPendingRef.current = false
        setApplyPending(false)
      }
    }
  }

  const reloadStatus = async () => {
    if (applyPendingRef.current) return
    if (needsReloadRef.current && needsReloadRef.scopeKey && scopeKey !== needsReloadRef.scopeKey) {
      setPageError('적용을 시작한 원래 Desktop 프로필·연결로 돌아간 뒤 실제 상태를 새로고침하세요. 이 화면에서는 결과를 추측하거나 다시 적용하지 않습니다.')
      return
    }
    invalidatePlan()
    const capturedScope = scopeKey
    const token = generationRef.current
    setPageError('')
    const response = await statusQuery.refetch()
    if (generationRef.current !== token || scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) return
    if (response.error || !response.data) {
      setPageError(response.error?.message || '상태를 다시 불러오지 못했습니다.')
      return
    }
    const rows = Array.isArray(response.data.profiles) ? response.data.profiles : []
    const row = rows.find(item => item.name === selectedProfile) || rows.find(item => item.name === response.data.current_profile) || rows[0]
    generationRef.current += 1
    setPreview(null)
    setReviewed(false)
    setFallbackPreview(null)
    setFallbackReviewed(false)
    setFallbackConsentChecks({ nativeCost: false, routingCost: false, routingRerun: false, delegationCost: false })
    setModelTargets(current => reconcileModelTargets(current, rows.map(item => item.name)))
    setRoutingProfiles(rows.filter(item => item.routing?.enabled === true).map(item => item.name))
    setFallbackTargets(current => ({
      native: reconcileFallbackTargets(current.native, rows.map(item => item.name)),
      routing: reconcileFallbackTargets(current.routing, rows.map(item => item.name)),
      delegation: reconcileFallbackTargets(current.delegation, rows.map(item => item.name))
    }))
    if (row) {
      setSelectedProfile(row.name)
      setDraft(copyProfileDraft(row))
      const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
      const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
      const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
      setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
      setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    } else {
      setSelectedProfile(null)
      setDraft(null)
      setFallbackDrafts({ native: null, routing: null, delegation: null })
      setFallbackBaselines({ native: null, routing: null, delegation: null })
    }
    setFallbackError('')
    needsReloadRef.current = false
    needsReloadRef.scopeKey = null
    applyScopeRef.current = null
    setNeedsReload(false)
    setApplyOutcome(null)
  }

  if (readyScope !== scopeKey || statusQuery.isPending) {
    return jsxs('main', { style: styles.page, 'aria-busy': true, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'status', style: styles.statusLine, children: [jsx(GlyphSpinner, {}), jsx('span', { style: styles.hint, children: '프로필 설정을 불러오고 있습니다.' })] })] })
  }

  if (statusQuery.isError) {
    return jsxs('main', { style: styles.page, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '설정 서비스를 사용할 수 없습니다.' }), jsx('p', { style: styles.hint, children: '백엔드가 꺼져 있거나 아직 준비되지 않았습니다. 잠시 후 다시 불러오세요. 이 화면에서는 로컬 파일이나 프로필 설정을 직접 변경하지 않습니다.' }), jsx('p', { style: styles.hint, children: statusQuery.error?.message || '상태 요청에 실패했습니다.' }), jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => void statusQuery.refetch(), children: '다시 불러오기' })] })] })
  }

  const currentPreset = draft ? selectedModelPreset(draft.models) : 'custom'
  const modelPresetCards = draft ? jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
    children: [
      jsx('p', { style: styles.hint, children: '프리셋은 네 모델 역할만 편집 가능한 초안에 채웁니다. 라우팅, 대체 모델 허용 여부, 프로필 구성, 모델 적용 대상은 변경하지 않습니다.' }),
      jsx('div', {
        style: styles.presetGrid,
        children: MODEL_PRESETS.map(preset => jsxs('button', {
          id: `preset-${preset.id}`,
          type: 'button',
          'aria-pressed': currentPreset === preset.id,
          disabled,
          onClick: () => applyPreset(preset.id),
          style: currentPreset === preset.id ? { ...styles.presetCard, ...styles.presetSelected } : styles.presetCard,
          children: [
            jsxs('div', { style: styles.statusLine, children: [jsx('strong', { children: preset.name }), jsx(Badge, { variant: currentPreset === preset.id ? 'muted' : 'muted', children: currentPreset === preset.id ? '현재 일치' : '초안에 채우기' })] }),
            jsx('span', { style: styles.hint, children: preset.description }),
            jsx('div', { style: styles.presetRoleList, children: ROLES.map(role => {
              const route = preset.models[role.id]
              return jsx('span', { style: styles.presetRole, children: `${role.label}: ${route.provider}/${route.model} · ${route.reasoning}` }, role.id)
            }) })
          ]
        }, preset.id))
      }),
      jsx('p', { role: 'status', 'aria-live': 'polite', style: styles.hint, children: currentPreset === 'custom' ? '현재 모델 역할은 사용자 지정 조합입니다.' : `현재 네 역할이 ${MODEL_PRESETS.find(item => item.id === currentPreset)?.name} 프리셋과 일치합니다.` })
    ]
  }) : null

  const modelFields = draft ? jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' },
    children: [
      modelPresetCards,
      jsx('div', {
        style: styles.roleGrid,
        children: ROLES.map(role => jsxs('article', {
          style: styles.roleCard,
          children: [
            jsxs('div', { children: [jsx('h3', { style: styles.roleTitle, children: role.label }), jsx('p', { style: { ...styles.hint, marginTop: '0.25rem' }, children: role.description })] }),
            jsx(RoleRouteFields, { prefix: `model-${role.id}`, route: draft.models?.[role.id], disabled, onChange: (field, value) => updateRole(role.id, field, value) }),
            jsx('p', { style: styles.actual, children: `실제 설정: ${readableValue(currentRow?.actual_models?.[role.id])}` })
          ]
        }, role.id))
      })
    ]
  }) : jsx('p', { role: 'alert', style: styles.warning, children: '선택한 프로필의 모델 또는 라우팅 정보가 없습니다. 프로필을 다시 불러와 상태를 확인하세요.' })

  const modelTargetGroup = jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '모델 설정 적용 대상' }),
      jsx('p', { style: styles.hint, children: '아래 프로필에만 기본·위임·압축·제목 모델 초안을 기록합니다. 선택한 프로필 목록은 라우팅 활성 목록과 별개입니다. 아무것도 선택하지 않으면 모델 값은 변경하지 않습니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: allTargetsSelected ? 'warn' : 'muted', children: targetSummary }), jsx('span', { style: styles.hint, children: `${selectedTargets.length}개 선택` })] }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: 'model-target-all', size: 'sm', variant: 'secondary', disabled, onClick: selectAllTargets, children: '모두 선택' }),
          jsx(Button, { id: 'model-target-none', size: 'sm', variant: 'secondary', disabled, onClick: selectNoTargets, children: '모두 해제' })
        ] })
      ] }),
      allTargetsSelected ? jsx('p', { role: 'note', style: styles.warning, children: `모든 ${profileNames.length}개 프로필이 모델 적용 대상입니다. 넓은 범위이므로 미리보기에서 프로필별 변경을 확인한 뒤 적용하세요.` }) : null,
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `model-target-${row.name}`, label: row.name, checked: selectedTargets.includes(row.name), disabled, onChange: checked => toggleModelTarget(row.name, checked) }) }, row.name)) })
    ]
  })

  const routingProfileGroup = jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '라우팅 활성 프로필' }),
      jsx('p', { style: styles.hint, children: '선택한 프로필 목록에만 라우팅 사용 권한을 설정합니다. 새 프로필은 기본적으로 선택되지 않습니다.' }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `routing-profile-${row.name}`, label: row.name, checked: routingProfiles.includes(row.name), disabled, onChange: checked => toggleRoutingProfile(row.name, checked) }) }, row.name)) })
    ]
  })

  const routingFields = draft ? jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '1.4rem' },
    children: [
      jsx(CheckRow, { id: 'routing-enabled', label: '이 프로필에서 라우팅 사용', detail: '선택하면 이 프로필이 라우팅 활성 프로필 목록에도 포함됩니다.', checked: activeRoutes.enabled === true, disabled, onChange: toggleRoutingEnabled }),
      jsxs('div', { style: styles.roleGrid, children: [
        jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '무거운 작업' }), jsx(ChoiceField, { id: 'heavy-follow', label: '대상 기준', value: activeRoutes.heavy?.follow || 'main', disabled, onChange: value => changeFollow('heavy', value), options: [{ value: 'main', label: '기본 대화 모델 따라가기' }, { value: 'custom', label: '별도 모델 지정' }] }), activeRoutes.heavy?.follow === 'custom' ? jsx(RoleRouteFields, { prefix: 'heavy-custom', route: activeRoutes.heavy.custom, disabled, onChange: (field, value) => updateRoutingRoute('heavy', field, value) }) : jsx('p', { style: styles.hint, children: '선택한 프로필의 기본 대화 모델을 사용합니다.' })] }),
        jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '가벼운 작업' }), jsx(ChoiceField, { id: 'light-follow', label: '대상 기준', value: activeRoutes.light?.follow || 'delegation', disabled, onChange: value => changeFollow('light', value), options: [{ value: 'delegation', label: '작업 위임 모델 따라가기' }, { value: 'custom', label: '별도 모델 지정' }] }), activeRoutes.light?.follow === 'custom' ? jsx(RoleRouteFields, { prefix: 'light-custom', route: activeRoutes.light.custom, disabled, onChange: (field, value) => updateRoutingRoute('light', field, value) }) : jsx('p', { style: styles.hint, children: '선택한 프로필의 작업 위임 모델을 사용합니다.' })] })
      ] }),
      jsxs('div', { id: 'legacy-routing-fallback-summary', style: { borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.45rem' }, children: [
        jsx('strong', { children: '코딩 대체 설정 · 읽기 전용' }),
        jsx('p', { style: styles.hint, children: currentRow?.fallbacks?.routing ? `${currentRow.fallbacks.routing.enabled === true ? '사용' : '미사용'} · Heavy ${readableValue(currentRow.fallbacks.routing.heavy)} · Light ${readableValue(currentRow.fallbacks.routing.light)}` : '상태를 확인할 수 없습니다.' }),
        jsx('a', { href: '#fallback-management', style: { color: 'var(--ui-accent)', fontSize: '0.84rem' }, children: '대체 실행 관리 열기' })
      ] })
    ]
  }) : null

  const fallbackTargetGroup = (scope, selected, allowEditing) => jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: `${scope === 'native' ? '대화 전환' : scope === 'routing' ? '코딩 작업' : '위임 제공자 전환'} 적용 대상` }),
      jsx('p', { style: styles.hint, children: '초기 대상은 위 원본 프로필 하나입니다. 이 목록은 모델 일괄 대상 및 라우팅 활성 프로필과 독립적입니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsx('span', { style: styles.hint, children: `${selected.length}/${profileNames.length}개 프로필 선택` }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: `${scope}-fallback-target-source`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'source'), children: '원본 프로필만' }),
          jsx(Button, { id: `${scope}-fallback-target-all`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'all'), children: scope === 'native' || scope === 'delegation' ? '편집 가능 모두' : '모두 선택' }),
          jsx(Button, { id: `${scope}-fallback-target-none`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'none'), children: '모두 해제' })
        ] })
      ] }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => {
        const supported = scope === 'native'
          ? row.fallbacks?.native?.editable === true
          : scope === 'delegation'
            ? validDelegationFallbackState(row.fallbacks?.delegation) && row.fallbacks.delegation.editable === true
            : Boolean(row.fallbacks?.routing)
        const checked = selected.includes(row.name)
        return jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, {
          id: `${scope}-fallback-target-${row.name}`,
          label: row.name,
          detail: supported ? undefined : scope === 'delegation' ? '위임 fallback DTO가 없거나 읽기 전용입니다.' : '현재 fallback 형식은 읽기 전용입니다.',
          checked,
          disabled: disabled || (!supported && !checked),
          onChange: value => updateFallbackTarget(scope, row.name, value)
        }) }, row.name)
      }) })
    ]
  })

  const fallbackPreviewPanel = scope => {
    const current = fallbackPreviewMatchesScope(fallbackPreview, scopeKey, generationRef.current, selectedProfile, scope)
    if (!current) return null
    const changes = Array.isArray(fallbackPreview.changes) ? fallbackPreview.changes : []
    return jsxs('div', { style: styles.section, children: [
      jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: 'muted', children: `${changes.length}개 변경` }), fallbackPreview.expires_at ? jsx('span', { style: styles.hint, children: `만료: ${fallbackPreview.expires_at}` }) : null] }),
      changes.length ? jsxs('div', { role: 'list', style: styles.changes, children: changes.map((change, index) => jsxs('div', { role: 'listitem', style: styles.change, children: [
        jsx('div', { style: styles.changeLabel, children: `${change.profile || '—'} · ${change.field || '대체 설정'}` }),
        jsxs('div', { style: styles.changeValue, children: [jsx('span', { style: styles.hint, children: '변경 전' }), jsx('code', { style: styles.value, children: readableValue(change.before) })] }),
        jsxs('div', { style: styles.changeValue, children: [jsx('span', { style: styles.hint, children: '변경 후' }), jsx('code', { style: styles.value, children: readableValue(change.after) })] })
      ] }, `${change.profile || ''}:${change.field || index}`)) }) : jsx('p', { style: styles.message, children: '변경 사항이 없습니다. 적용할 내용이 없습니다.' }),
      Array.isArray(fallbackPreview.warnings) && fallbackPreview.warnings.length ? jsx('div', { style: styles.warning, children: fallbackPreview.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
      changes.length ? jsxs('div', { style: styles.actions, children: [
        jsx(CheckRow, { id: `${scope}-fallback-review`, label: '이 fallback 범위의 변경 전후를 확인했습니다.', checked: fallbackReviewed, disabled: applyPending || needsReload, onChange: setFallbackReviewed }),
        jsx(Button, { id: `${scope}-fallback-apply`, size: 'sm', disabled: !fallbackReviewed || applyPending || needsReload, onClick: () => void handleFallbackApply(scope), children: applyPending ? '적용 중…' : '이 범위만 확인 후 적용' })
      ] }) : null
    ] })
  }

  const nativeStatus = currentRow?.fallbacks?.native
  const routingFallbackStatus = currentRow?.fallbacks?.routing
  const nativeEditable = fallbackSupported && nativeStatus?.editable === true && Boolean(nativeFallbackDraft)
  const routingEditable = fallbackSupported && Boolean(routingFallbackDraft)
  const nativeChainText = chain => Array.isArray(chain) && chain.length
    ? chain.map(item => `${item?.provider || '—'}/${item?.model || '—'}`).join(' → ')
    : '없음'
  const nativeFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '대화 중 제공자 전환' }), jsx(Badge, { variant: nativeStatus?.enabled ? 'warn' : 'muted', children: nativeStatus?.enabled ? '현재 사용' : nativeStatus ? '현재 꺼짐' : '상태 미지원' }), nativeFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
    jsx('p', { style: styles.hint, children: 'Hermes 런타임이 정하는 전환 조건을 따릅니다. 전환 뒤에는 현재 대화를 이어갑니다. 이 체인에는 공급자·모델만 저장하며 추론 강도는 프로필 재정의와 Hermes 정책을 따릅니다.' }),
    jsx('p', { style: styles.warning, children: '전환 조건과 재시도 동작은 Hermes 정책이 결정합니다. 숫자형 재시도 컨트롤은 제공하지 않습니다. native fallback은 위임·보조 호출에도 영향을 줄 수 있으며 사용량에 따라 추가 비용이 발생할 수 있습니다.' }),
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 설정: ${fallbackBaselines.native?.enabled ? nativeChainText(fallbackBaselines.native.chain) : `꺼짐 · 보관 체인 ${nativeChainText(fallbackBaselines.native?.chain)}`}` }),
      jsx('p', { style: styles.actual, children: `편집 초안: ${nativeFallbackDraft?.enabled ? nativeChainText(nativeFallbackDraft.chain) : `꺼짐 · 보관 체인 ${nativeChainText(nativeFallbackDraft?.chain)}`}` }),
      jsx('p', { style: styles.actual, children: `실제 적용 경로: ${nativeChainText(nativeStatus?.actual_chain)}` })
    ] }),
    nativeStatus?.drift ? jsx('p', { role: 'status', style: styles.warning, children: '저장된 대화 체인과 실제 적용 체인이 다릅니다. 실제 경로를 먼저 확인하세요.' }) : null,
    Array.isArray(nativeStatus?.warnings) && nativeStatus.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: nativeStatus.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '백엔드가 지원하는 fallback 정책 정보를 제공하지 않아 이 설정은 읽기 전용입니다. 호환되는 Model Router 백엔드로 새로고침하세요.' }) : null,
    fallbackSupported && nativeStatus && nativeStatus.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '외부의 고급·불완전 체인 또는 재현할 수 없는 관리 설정입니다. 원본을 보존하기 위해 편집을 잠갔습니다.' }) : null,
    nativeEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(CheckRow, { id: 'native-fallback-enabled', label: '현재 대화에서 대체 체인 사용', detail: '체인 값을 채우는 것만으로는 켜지지 않습니다.', checked: nativeFallbackDraft.enabled, disabled, onChange: checked => updateFallbackDraft('native', current => ({ ...current, enabled: checked })) }),
      nativeStatus?.managed !== true ? jsx('p', { role: 'note', style: styles.warning, children: '현재 체인은 외부 관리 상태입니다. 편집 가능한 단순 체인이지만, 켜서 적용하면 플러그인이 소유하며 새 비용 확인이 필요합니다.' }) : null,
      jsx('div', { style: styles.presetGrid, children: NATIVE_FALLBACK_PRESETS.map(preset => jsx('button', { id: `native-fallback-preset-${preset.id}`, type: 'button', disabled, onClick: () => updateFallbackDraft('native', current => applyNativeFallbackPresetDraft(current, preset.id)), style: styles.presetCard, children: [jsx('strong', { children: preset.name }), jsx('span', { style: styles.hint, children: preset.description }), jsx('span', { style: styles.hint, children: `${preset.chain.map(item => `${item.provider}/${item.model}`).join(' → ')} · 비활성/동의 상태는 그대로 유지` })] }, preset.id)) }),
      jsxs('div', { style: styles.fieldset, children: [
        jsx('strong', { style: styles.fieldName, children: '순서가 있는 대체 체인' }),
        ...nativeFallbackDraft.chain.map((entry, index) => jsxs('div', { style: styles.roleCard, children: [
          jsx('strong', { style: styles.roleTitle, children: `우선순위 ${index + 1}` }),
          jsx('div', { style: styles.fields, children: [
            jsx(Field, { id: `native-chain-${index}-provider`, label: `우선순위 ${index + 1} 공급자 ID`, value: entry.provider, disabled, onChange: value => updateFallbackDraft('native', current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, provider: value } : item) })) }),
            jsx(Field, { id: `native-chain-${index}-model`, label: `우선순위 ${index + 1} 모델 ID`, value: entry.model, disabled, onChange: value => updateFallbackDraft('native', current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, model: value } : item) })) })
          ] }),
          jsxs('div', { style: styles.actions, children: [
            jsx(Button, { id: `native-chain-${index}-up`, size: 'sm', variant: 'secondary', disabled: disabled || index === 0, onClick: () => updateFallbackDraft('native', current => { const chain = [...current.chain]; [chain[index - 1], chain[index]] = [chain[index], chain[index - 1]]; return { ...current, chain } }), children: '위로' }),
            jsx(Button, { id: `native-chain-${index}-down`, size: 'sm', variant: 'secondary', disabled: disabled || index === nativeFallbackDraft.chain.length - 1, onClick: () => updateFallbackDraft('native', current => { const chain = [...current.chain]; [chain[index + 1], chain[index]] = [chain[index], chain[index + 1]]; return { ...current, chain } }), children: '아래로' }),
            jsx(Button, { id: `native-chain-${index}-remove`, size: 'sm', variant: 'secondary', disabled, onClick: () => updateFallbackDraft('native', current => ({ ...current, chain: current.chain.filter((_, at) => at !== index) })), children: '삭제' })
          ] })
        ] }, `${entry.provider}:${entry.model}:${index}`)),
        jsx(Button, { id: 'native-chain-add', size: 'sm', variant: 'secondary', disabled: disabled || nativeFallbackDraft.chain.length >= 5, onClick: () => updateFallbackDraft('native', current => ({ ...current, chain: [...current.chain, { provider: '', model: '' }] })), children: '모델 추가' }),
        nativeFallbackError ? jsx('p', { role: 'alert', style: styles.warning, children: nativeFallbackError }) : null
      ] }),
      nativeNeedsConsent ? jsx(CheckRow, { id: 'native-fallback-cost-consent', label: '선택한 프로필의 대화 대체 모델 사용에 추가 비용이 발생할 수 있음을 확인했습니다.', detail: '새로 켜기·경로 변경·외부 체인 인수에는 새 동의가 필요합니다.', checked: fallbackConsentChecks.nativeCost, disabled, onChange: checked => updateFallbackConsent('nativeCost', checked) }) : nativeFallbackDraft.enabled ? jsx('p', { role: 'status', style: styles.hint, children: '현재 선택과 일치하는 승인된 대체 설정을 유지합니다. 새 승인은 요청하지 않습니다.' }) : null,
      fallbackTargetGroup('native', nativeFallbackTargets, nativeEditable),
      fallbackError?.scope === 'native' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'native-fallback-preview', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('native'), onClick: () => void handleFallbackPreview('native'), children: fallbackPreviewPending ? '미리보기 계산 중…' : '대화 전환만 미리보기' }),
      fallbackPreviewPanel('native')
    ] }) : null
  ] })

  const routingFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '코딩 작업 대체 실행' }), jsx(Badge, { variant: routingFallbackStatus?.enabled ? 'warn' : 'muted', children: routingFallbackStatus?.enabled ? '현재 사용' : routingFallbackStatus ? '현재 꺼짐' : '상태 미지원' }), routingFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
    jsx('p', { style: styles.hint, children: '라우팅된 코딩 작업에만 적용됩니다. 재시도는 도구 호출·부분 출력 전 확인된 구독 한도 초과일 때 같은 역할로 새 작업을 시작하며 최대 1회입니다. 대화 중 provider fallback과 별개로 동작합니다.' }),
    jsx('p', { style: styles.warning, children: '실패 문구만으로는 재시도하지 않습니다. 확인된 한도 초과가 아니거나 이미 도구/부분 출력이 있으면 재시도하지 않습니다. 대체 실행에는 별도 비용이 발생할 수 있습니다.' }),
    routingFallbackStatus?.enabled && currentRow?.routing?.enabled !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필의 코딩 라우팅은 현재 꺼져 있습니다. 여기서 라우팅 활성화나 프로필 멤버십은 변경하지 않습니다.' }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '백엔드가 지원하는 fallback 정책 정보를 제공하지 않아 이 설정은 읽기 전용입니다. 호환되는 Model Router 백엔드로 새로고침하세요.' }) : null,
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 설정: ${routingFallbackStatus?.enabled ? '사용' : '꺼짐'} · Heavy ${readableValue(routingFallbackStatus?.heavy)} · Light ${readableValue(routingFallbackStatus?.light)}` }),
      jsx('p', { style: styles.actual, children: `Heavy 실행 경로: ${readableValue(primaryRouteForFallback(currentRow, 'heavy'))} → ${routingFallbackStatus?.enabled ? readableValue(routingFallbackStatus.heavy) : '대체 꺼짐'}` }),
      jsx('p', { style: styles.actual, children: `Light 실행 경로: ${readableValue(primaryRouteForFallback(currentRow, 'light'))} → ${routingFallbackStatus?.enabled ? readableValue(routingFallbackStatus.light) : '대체 꺼짐'}` })
    ] }),
    routingEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(CheckRow, { id: 'routing-fallback-enabled', label: '새 작업으로 코딩 fallback 허용', detail: '템플릿 선택만으로는 켜지지 않습니다.', checked: routingFallbackDraft.enabled, disabled, onChange: checked => updateFallbackDraft('routing', current => ({ ...current, enabled: checked })) }),
      jsx('div', { style: styles.presetGrid, children: ROUTING_FALLBACK_PRESETS.map(preset => jsx('button', { id: `routing-fallback-preset-${preset.id}`, type: 'button', disabled, onClick: () => updateFallbackDraft('routing', current => applyRoutingFallbackPresetDraft(current, preset.id)), style: styles.presetCard, children: [jsx('strong', { children: preset.name }), jsx('span', { style: styles.hint, children: preset.description }), jsx('span', { style: styles.hint, children: `Heavy ${readableValue(preset.heavy)} · Light ${readableValue(preset.light)} · 비활성/동의 상태는 그대로 유지` })] }, preset.id)) }),
      jsx('div', { style: styles.roleGrid, children: ['heavy', 'light'].map(role => jsxs('article', { style: styles.roleCard, children: [
        jsx('h4', { style: styles.roleTitle, children: role === 'heavy' ? 'Heavy 작업' : 'Light 작업' }),
        jsx(RoleRouteFields, { prefix: `routing-fallback-${role}`, route: routingFallbackDraft[role], disabled, onChange: (field, value) => updateFallbackDraft('routing', current => ({ ...current, [role]: { ...(current[role] || {}), [field]: value } })) }),
        jsx('p', { style: styles.actual, children: `주 경로: ${readableValue(primaryRouteForFallback(currentRow, role))}` }),
        jsx('p', { style: styles.actual, children: `대체 경로: ${readableValue(routingFallbackDraft[role])}` })
      ] }, role)) }),
      routingFallbackError ? jsx('p', { role: 'alert', style: styles.warning, children: routingFallbackError }) : null,
      routingNeedsConsent ? jsxs('div', { style: styles.choiceGroup, children: [
        jsx(CheckRow, { id: 'routing-fallback-cost-consent', label: '선택한 프로필의 코딩 대체 모델 사용에 추가 비용이 발생할 수 있음을 확인했습니다.', checked: fallbackConsentChecks.routingCost, disabled, onChange: checked => updateFallbackConsent('routingCost', checked) }),
        jsx(CheckRow, { id: 'routing-fallback-rerun-consent', label: '대체 시 도구 호출 전 같은 역할의 새 작업이 최대 1회 시작됨을 확인했습니다.', detail: '원래 대화나 이미 생성된 부분 출력을 이어받지 않습니다.', checked: fallbackConsentChecks.routingRerun, disabled, onChange: checked => updateFallbackConsent('routingRerun', checked) })
      ] }) : routingFallbackDraft.enabled ? jsx('p', { role: 'status', style: styles.hint, children: '현재 선택과 일치하는 승인된 코딩 fallback 설정을 유지합니다. 새 승인은 요청하지 않습니다.' }) : null,
      fallbackTargetGroup('routing', routingFallbackTargets, routingEditable),
      fallbackError?.scope === 'routing' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'routing-fallback-preview', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('routing'), onClick: () => void handleFallbackPreview('routing'), children: fallbackPreviewPending ? '미리보기 계산 중…' : '코딩 작업 대체만 미리보기' }),
      fallbackPreviewPanel('routing')
    ] }) : jsx('div', { role: 'note', style: styles.warning, children: routingFallbackStatus ? '현재 코딩 대체 정책은 표시만 가능합니다.' : '이 프로필의 코딩 fallback 상태를 사용할 수 없습니다. 기존 설정은 변경되지 않습니다.' })
  ] })

  const delegationStatus = currentRow?.fallbacks?.delegation
  const delegationStatusValid = validDelegationFallbackState(delegationStatus)
  const delegationEditable = fallbackSupported && delegationStatusValid && delegationStatus.editable === true && Boolean(delegationFallbackDraft)
  const delegationModeLabel = mode => DELEGATION_FALLBACK_MODES.find(item => item.value === mode)?.label || '확인할 수 없음'
  const delegationChainText = chain => Array.isArray(chain) && chain.length
    ? chain.map(item => `${item.provider}/${item.model}`).join(' → ')
    : '없음'
  const delegationFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [
      jsx('h3', { style: styles.roleTitle, children: '위임 작업의 제공자 전환' }),
      jsx(Badge, { variant: delegationStatusValid && delegationStatus.mode !== 'off' ? 'warn' : 'muted', children: delegationStatusValid ? delegationModeLabel(delegationStatus.mode) : '상태 미지원' }),
      delegationFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null
    ] }),
    jsx('p', { style: styles.hint, children: '기본 규칙에서는 제공자·모델을 고정하지 않은 자식만 부모 대화의 폴백을 상속합니다. 고정된 자식도 전환하려면 위임 전용 목록을 지정하세요. 작업별 모델 지정에 따라 달라질 수 있습니다.' }),
    jsx('p', { style: styles.warning, children: '기본 규칙은 무조건 상속을 뜻하지 않습니다. 부모 대화 정책이 나중에 바뀌면 고정되지 않은 위임 자식에도 영향이 갈 수 있습니다. 위임 전용 목록은 자식에 별도 체인을 선언합니다. 이미 진행 중인 위임 작업은 다시 시작되거나 즉시 전환되지 않습니다.' }),
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 정책: ${delegationStatusValid ? delegationModeLabel(fallbackBaselines.delegation?.mode) : '확인할 수 없음'} · 목록 ${delegationChainText(fallbackBaselines.delegation?.chain)}` }),
      jsx('p', { style: styles.actual, children: `실제 선언 정책: ${delegationStatusValid ? delegationModeLabel(delegationStatus.actual_mode) : '확인할 수 없음'} · 선언 체인 ${delegationChainText(delegationStatus?.actual_chain)}` }),
      jsx('p', { style: styles.hint, children: '여기에 표시한 목록은 위임 전용 선언입니다. 실제 상속 여부는 각 위임 작업에서 지정한 모델·제공자에 따라 달라집니다.' })
    ] }),
    delegationStatus?.drift ? jsx('p', { role: 'status', style: styles.warning, children: '저장된 위임 정책과 실제 선언 설정이 다릅니다. 적용 경로를 확인하세요.' }) : null,
    delegationStatusValid && delegationStatus.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: delegationStatus.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '백엔드가 지원하는 fallback 정책 정보를 제공하지 않아 이 설정은 읽기 전용입니다. 상태를 새로고침하세요.' }) : null,
    fallbackSupported && !delegationStatusValid ? jsx('p', { role: 'alert', style: styles.warning, children: '위임 폴백 설정을 확인할 수 없어 편집을 잠갔습니다. 기존 설정은 그대로 보존됩니다. 상태를 새로고침하세요.' }) : null,
    delegationStatusValid && delegationStatus.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '관리자 고정·고급 옵션·설정 읽기 실패 등으로 안전한 편집을 확인할 수 없습니다. 원본을 보존하기 위해 편집을 잠갔습니다.' }) : null,
    delegationEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(ChoiceField, { id: 'delegation-fallback-mode', label: '위임 제공자 전환 정책', value: delegationFallbackDraft.mode, disabled, onChange: mode => updateFallbackDraft('delegation', current => ({ mode, chain: mode === 'custom' ? current.chain : [] })), options: DELEGATION_FALLBACK_MODES }),
      delegationFallbackDraft.mode === 'default' ? jsx('p', { style: styles.hint, children: '기본 규칙에 맡깁니다. 제공자·모델·endpoint가 고정되지 않은 자식만 부모 대화의 체인을 상속하며, 고정된 자식에는 기본적으로 체인이 없습니다.' }) : null,
      delegationFallbackDraft.mode === 'off' ? jsx('p', { style: styles.hint, children: '위임 자식에 적용할 fallback을 명시적으로 끕니다. 저장되는 체인은 비어 있습니다.' }) : null,
      delegationFallbackDraft.mode === 'custom' ? jsxs('div', { style: styles.fieldset, children: [
        jsx('strong', { style: styles.fieldName, children: '순서가 있는 위임 전용 목록' }),
        jsx('p', { style: styles.hint, children: '이 체인은 위임 자식 전용입니다. 대화 모델·라우팅 모델·모델 일괄 대상은 바꾸지 않습니다.' }),
        jsx('button', { id: 'delegation-fallback-template-non-openai', type: 'button', disabled, onClick: () => updateFallbackDraft('delegation', current => ({ ...current, chain: deepClone(NATIVE_FALLBACK_PRESETS[0].chain) })), style: styles.presetCard, children: [jsx('strong', { children: 'Non-OpenAI 체인 초안 채우기' }), jsx('span', { style: styles.hint, children: '추가 비용 확인이나 위임 전용 정책 활성화는 하지 않습니다.' }), jsx('span', { style: styles.hint, children: NATIVE_FALLBACK_PRESETS[0].chain.map(item => `${item.provider}/${item.model}`).join(' → ') })] }),
        ...delegationFallbackDraft.chain.map((entry, index) => jsxs('div', { style: styles.roleCard, children: [
          jsx('strong', { style: styles.roleTitle, children: `우선순위 ${index + 1}` }),
          jsx('div', { style: styles.fields, children: [
            jsx(Field, { id: `delegation-chain-${index}-provider`, label: `위임 우선순위 ${index + 1} 공급자 ID`, value: entry.provider, disabled, onChange: value => updateFallbackDraft('delegation', current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, provider: value } : item) })) }),
            jsx(Field, { id: `delegation-chain-${index}-model`, label: `위임 우선순위 ${index + 1} 모델 ID`, value: entry.model, disabled, onChange: value => updateFallbackDraft('delegation', current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, model: value } : item) })) })
          ] }),
          jsxs('div', { style: styles.actions, children: [
            jsx(Button, { id: `delegation-chain-${index}-up`, size: 'sm', variant: 'secondary', disabled: disabled || index === 0, onClick: () => updateFallbackDraft('delegation', current => { const chain = [...current.chain]; [chain[index - 1], chain[index]] = [chain[index], chain[index - 1]]; return { ...current, chain } }), children: '위로' }),
            jsx(Button, { id: `delegation-chain-${index}-down`, size: 'sm', variant: 'secondary', disabled: disabled || index === delegationFallbackDraft.chain.length - 1, onClick: () => updateFallbackDraft('delegation', current => { const chain = [...current.chain]; [chain[index + 1], chain[index]] = [chain[index], chain[index + 1]]; return { ...current, chain } }), children: '아래로' }),
            jsx(Button, { id: `delegation-chain-${index}-remove`, size: 'sm', variant: 'secondary', disabled, onClick: () => updateFallbackDraft('delegation', current => ({ ...current, chain: current.chain.filter((_, at) => at !== index) })), children: '삭제' })
          ] })
        ] }, `${entry.provider}:${entry.model}:${index}`)),
        jsx(Button, { id: 'delegation-chain-add', size: 'sm', variant: 'secondary', disabled: disabled || delegationFallbackDraft.chain.length >= 5, onClick: () => updateFallbackDraft('delegation', current => ({ ...current, chain: [...current.chain, { provider: '', model: '' }] })), children: '모델 추가' }),
        delegationFallbackError ? jsx('p', { role: 'alert', style: styles.warning, children: delegationFallbackError }) : null
      ] }) : null,
      delegationNeedsConsent ? jsx(CheckRow, { id: 'delegation-fallback-cost-consent', label: '선택한 위임 정책·모델 사용에 추가 비용이 발생할 수 있음을 확인했습니다.', detail: delegationFallbackDraft.mode === 'default' ? '기본 규칙은 고정되지 않은 자식만 조건부 상속합니다. 부모 대화의 이후 폴백 정책 변경도 위임 작업에 반영될 수 있습니다.' : '이 동의는 위임 전용 체인에만 적용되며 코딩 작업 재시도 승인이 아닙니다.', checked: fallbackConsentChecks.delegationCost, disabled, onChange: checked => updateFallbackConsent('delegationCost', checked) }) : delegationFallbackDraft.mode !== 'off' ? jsx('p', { role: 'status', style: styles.hint, children: '현재 선택과 일치하는 위임 정책의 추가 비용 확인을 유지합니다.' }) : null,
      fallbackTargetGroup('delegation', delegationFallbackTargets, delegationEditable),
      fallbackError?.scope === 'delegation' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'delegation-fallback-preview', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('delegation'), onClick: () => void handleFallbackPreview('delegation'), children: fallbackPreviewPending ? '미리보기 계산 중…' : '위임 제공자 전환만 미리보기' }),
      fallbackPreviewPanel('delegation')
    ] }) : null
  ] })

  const fallbackManagement = section('fallback 실행 관리', '대화 지속형 provider 전환, 코딩 작업 재시도, 위임 자식 전환은 별도 정책입니다. 각 카드는 자기 scope만 미리보고 적용합니다.', jsxs('div', { id: 'fallback-management', style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [
    !fallbackSupported ? jsx('div', { role: 'alert', style: styles.warning, children: '지원 정책 정보가 없거나 달라서 모든 fallback 편집이 읽기 전용입니다. 상태를 새로고침해 호환되는 백엔드를 확인하세요.' }) : null,
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.hint, children: `대상 원본 프로필: ${selectedProfile || '선택 안 됨'} · 대화 대상 ${nativeFallbackTargets.length}개 · 코딩 대상 ${routingFallbackTargets.length}개 · 위임 대상 ${delegationFallbackTargets.length}개` }),
      jsx('p', { style: styles.hint, children: '프리셋은 초안만 채웁니다. 자동 활성화나 승인 저장을 하지 않습니다. 모델 역할 프리셋, 모델 적용 대상, 라우팅 활성 프로필과도 분리되어 있습니다.' })
    ] }),
    jsx('div', { style: styles.roleGrid, children: [nativeFallbackPanel, routingFallbackPanel, delegationFallbackPanel] })
  ] }))

  const previewChanges = validPreview ? (Array.isArray(preview.changes) ? preview.changes : []) : []
  const canPreview = Boolean(currentRow && draft && statusQuery.data && !disabled && !previewPending)

  return jsxs('main', {
    style: styles.page,
    children: [
      jsxs('header', { style: styles.header, children: [jsxs('div', { children: [jsx('p', { style: { color: 'var(--ui-accent)', fontSize: '0.72rem', fontWeight: 650, letterSpacing: '0.08em', margin: '0 0 0.45rem' }, children: 'HERMES DESKTOP · 모델 제어' }), jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsx('p', { style: styles.subtitle, children: '프로필별 모델 값을 관리하고 작업 유형에 맞는 라우팅을 구성합니다. 설정은 미리보기와 별도 적용 단계를 거쳐 반영됩니다.' })] }), jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching || applyPending, onClick: () => void reloadStatus(), children: '상태 새로고침' })] }),
      jsx('div', { role: 'note', style: styles.notice, children: '새 규칙은 이후에 시작하는 세션과 허용된 작업에 적용됩니다. 이미 진행 중인 세션의 모델은 자동으로 바뀌지 않습니다.' }),
      profiles.length === 0 ? jsx('div', { role: 'status', style: styles.notice, children: '관리할 프로필이 없습니다. Hermes에서 프로필을 만든 뒤 상태를 새로고침하세요.' }) : null,
      profiles.length ? section('대상 프로필', '편집할 설정 프로필을 고릅니다. 현재 Desktop 연결·프로필 범위가 바뀌면 대기 중인 미리보기는 폐기됩니다.', jsxs('div', { style: styles.fields, children: [jsx(ChoiceField, { id: 'profile-select', label: '프로필', value: selectedProfile || '', disabled: disabled || !profiles.length, onChange: selectProfile, options: profiles.map(row => ({ value: row.name, label: row.name })) }), jsx('div', { style: { ...styles.field, justifyContent: 'flex-end' }, children: jsx('span', { style: styles.hint, children: `현재 Desktop 프로필: ${activeProfile || '확인 중'} · 연결: ${connectionId || 'local'} · 게이트웨이: ${gateway || 'idle'}` }) })] }), currentRow ? jsx(StatusView, { profile: currentRow }) : null) : null,
      profiles.length ? section('모델 대상', '네 역할의 값을 한 번 편집하고, 아래 별도 선택 목록에 체크한 프로필에만 모델 값을 적용합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [modelFields, modelTargetGroup] })) : null,
      profiles.length ? section('작업 라우팅', '무거운 작업과 가벼운 작업은 각각 독립적으로 대상을 정합니다. 라우팅 활성 프로필 선택은 모델 설정 적용 대상과 별개입니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { style: styles.hint, children: routingSummary }),
        jsxs('details', { style: styles.cardSection, children: [
          jsxs('summary', { style: { cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.8rem', flexWrap: 'wrap' }, children: [jsx('strong', { children: '라우팅 세부 설정' }), jsx(Badge, { variant: 'muted', children: `활성 프로필 ${routingProfiles.length}개` })] }),
          jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.9rem' }, children: [routingFields, routingProfileGroup] })
        ] })
      ] })) : null,
      profiles.length ? fallbackManagement : null,
      pageError ? jsx('div', { role: 'alert', style: styles.warning, children: pageError }) : null,
      applyOutcome ? jsxs('div', { role: 'status', 'aria-live': 'polite', style: applyOutcome.kind === 'success' ? styles.message : styles.warning, children: [jsx('strong', { children: applyOutcome.kind === 'success' ? '적용 요청이 완료되었습니다.' : applyOutcome.kind === 'partial' ? '일부 설정만 적용되었을 수 있습니다.' : '적용 결과를 확인할 수 없습니다.' }), jsx('p', { style: styles.hint, children: applyOutcome.message || (applyOutcome.kind === 'success' ? '실제 상태를 새로고침해 확인하세요. 같은 계획을 다시 적용하지 않습니다.' : '다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요.') }), applyOutcome.result ? jsx('p', { style: styles.value, children: readableValue(applyOutcome.result) }) : null] }) : null,
      needsReload ? jsx('div', { style: styles.actions, children: jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching, onClick: () => void reloadStatus(), children: statusQuery.isFetching ? '상태 확인 중…' : '실제 상태 확인 후 편집 재개' }) }) : null,
      profiles.length && !needsReload ? section('미리보기 및 적용', '변경 전후 값을 확인한 다음 별도 확인을 거쳐 적용합니다. 미리보기는 설정을 변경하지 않습니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [
        jsx('p', { style: styles.hint, children: `설정 revision: ${statusQuery.data?.revision ?? '확인할 수 없음'} · 모델 대상 ${targetSummary} · 라우팅 활성 ${routingProfiles.length}개` }),
        jsx(Button, { size: 'sm', variant: 'secondary', disabled: !canPreview, onClick: () => void handlePreview(), children: previewPending ? '미리보기 계산 중…' : '변경 내용 미리보기' }),
        validPreview ? jsxs('div', { style: styles.section, children: [
          jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: 'muted', children: `${previewChanges.length}개 변경` }), preview.expires_at ? jsx('span', { style: styles.hint, children: `만료: ${preview.expires_at}` }) : null] }),
          allTargetsSelected && previewChanges.length ? jsx('div', { role: 'alert', style: styles.warning, children: `광범위한 변경: 모든 ${profileNames.length}개 프로필이 모델 적용 대상입니다. 각 프로필의 변경 전후를 확인하고, 아래 확인란을 선택해야 적용할 수 있습니다.` }) : null,
          previewChanges.length ? jsxs('div', { role: 'list', style: styles.changes, children: previewChanges.map((change, index) => jsxs('div', { role: 'listitem', style: styles.change, children: [
            jsx('div', { style: styles.changeLabel, children: `${change.profile || '—'} · ${change.field || '항목'}` }),
            jsxs('div', { style: styles.changeValue, children: [jsx('span', { style: styles.hint, children: '변경 전' }), jsx('code', { style: styles.value, children: readableValue(change.before) })] }),
            jsxs('div', { style: styles.changeValue, children: [jsx('span', { style: styles.hint, children: '변경 후' }), jsx('code', { style: styles.value, children: readableValue(change.after) })] })
          ] }, `${change.profile || ''}:${change.field || index}`)) }) : jsx('p', { style: styles.message, children: '변경 사항이 없습니다. 적용할 내용이 없습니다.' }),
          Array.isArray(preview.warnings) && preview.warnings.length ? jsx('div', { style: styles.warning, children: preview.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
          previewChanges.length ? jsxs('div', { style: styles.actions, children: [jsx(CheckRow, { id: 'confirm-preview', label: allTargetsSelected ? '모든 프로필 대상 변경 전후를 확인했습니다.' : '변경 전후 내용을 확인했습니다.', checked: reviewed, disabled: applyPending || needsReload, onChange: setReviewed }), jsx(Button, { size: 'sm', disabled: !reviewed || applyPending || !validPreview || needsReload, onClick: () => void handleApply(), children: applyPending ? '적용 중…' : '확인 후 적용' })] }) : null
        ] }) : null
      ] })) : null
    ]
  })
}

export default {
  id: PLUGIN_ID,
  name: '모델 및 라우팅',
  defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      {
        id: 'progress',
        area: COMPOSER_AREAS.top,
        order: -100,
        render: () => jsx(ComposerProgress, {})
      },
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: ROUTE_PATH },
        render: () => jsx(RouterPage, { ctx })
      },
      {
        id: 'sidebar',
        area: SIDEBAR_NAV_AREA,
        data: { path: ROUTE_PATH, label: '모델 및 라우팅', codicon: 'settings-gear' }
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'model-router.open',
          label: '모델 및 라우팅 열기',
          keywords: ['model', 'routing', 'profile', '모델', '라우팅', '프로필'],
          run: () => host.navigate(ROUTE_PATH)
        }
      }
    ])
  }
}
