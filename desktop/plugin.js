import {
  Badge,
  Button,
  Checkbox,
  Codicon,
  GlyphSpinner,
  Input,
  PALETTE_AREA,
  ROUTES_AREA,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  host,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'
import * as DesktopSDK from '@hermes/plugin-sdk'
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

const TIMEOUT_MINUTE_KEYS = ['delegate_total_minutes', 'routed_light_total_minutes', 'routed_heavy_total_minutes']

function validSeconds(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function validTimeoutSettingsShape(timeouts) {
  if (!timeouts || typeof timeouts !== 'object' || Array.isArray(timeouts) ||
    !Number.isInteger(timeouts.revision) || timeouts.revision < 0 || typeof timeouts.editable !== 'boolean') return false
  if (timeouts.schema === 1) {
    return validSeconds(timeouts.delegate_total_seconds) && validSeconds(timeouts.routed_total_seconds) &&
      !Object.hasOwn(timeouts, 'routed_light_total_seconds') && !Object.hasOwn(timeouts, 'routed_heavy_total_seconds')
  }
  if (timeouts.schema === 2) {
    return validSeconds(timeouts.delegate_total_seconds) && validSeconds(timeouts.routed_light_total_seconds) &&
      validSeconds(timeouts.routed_heavy_total_seconds) && !Object.hasOwn(timeouts, 'routed_total_seconds')
  }
  return false
}

export function validTimeoutsDto(timeouts) {
  return Boolean(validTimeoutSettingsShape(timeouts) && Array.isArray(timeouts.warnings) &&
    timeouts.warnings.every(warning => typeof warning === 'string'))
}

export function splitRoutingSupported(timeouts) {
  return Boolean(validTimeoutsDto(timeouts) && timeouts.split_routing_supported === true)
}

export function projectTimeoutSeconds(timeouts) {
  if (!validTimeoutSettingsShape(timeouts)) return null
  if (timeouts.schema === 1) return {
    delegate_total_seconds: timeouts.delegate_total_seconds,
    routed_light_total_seconds: timeouts.routed_total_seconds,
    routed_heavy_total_seconds: timeouts.routed_total_seconds
  }
  return {
    delegate_total_seconds: timeouts.delegate_total_seconds,
    routed_light_total_seconds: timeouts.routed_light_total_seconds,
    routed_heavy_total_seconds: timeouts.routed_heavy_total_seconds
  }
}

function copyTimeoutSettingsShape(timeouts) {
  if (!validTimeoutSettingsShape(timeouts)) return null
  return {
    schema: timeouts.schema,
    revision: timeouts.revision,
    delegate_total_seconds: timeouts.delegate_total_seconds,
    ...(timeouts.schema === 1
      ? { routed_total_seconds: timeouts.routed_total_seconds }
      : { routed_light_total_seconds: timeouts.routed_light_total_seconds, routed_heavy_total_seconds: timeouts.routed_heavy_total_seconds }),
    editable: timeouts.editable,
    split_routing_supported: timeouts.split_routing_supported === true
  }
}

function copyTimeoutSettings(timeouts) {
  if (!validTimeoutsDto(timeouts)) return null
  return { ...copyTimeoutSettingsShape(timeouts), warnings: [...timeouts.warnings] }
}

export function copyTimeoutBaseline(timeouts) {
  const settings = copyTimeoutSettings(timeouts)
  const projected = projectTimeoutSeconds(settings)
  return settings && projected ? {
    schema: settings.schema,
    revision: settings.revision,
    editable: settings.editable,
    split_routing_supported: settings.split_routing_supported,
    delegate_total_seconds: settings.delegate_total_seconds,
    ...(settings.schema === 1 ? { routed_total_seconds: settings.routed_total_seconds } : {}),
    routed_light_total_seconds: projected.routed_light_total_seconds,
    routed_heavy_total_seconds: projected.routed_heavy_total_seconds
  } : null
}

function copyTimeoutBaselineShape(timeouts) {
  return copyTimeoutBaseline(timeouts)
}

function timeoutDraftFromSettings(timeouts) {
  if (!validTimeoutsDto(timeouts)) return null
  const projected = projectTimeoutSeconds(timeouts)
  if (!projected) return null
  return {
    schema: timeouts.schema,
    revision: timeouts.revision,
    editable: timeouts.editable,
    split_routing_supported: timeouts.split_routing_supported === true,
    delegate_total_minutes: projected.delegate_total_seconds / 60,
    routed_light_total_minutes: projected.routed_light_total_seconds / 60,
    routed_heavy_total_minutes: projected.routed_heavy_total_seconds / 60
  }
}

export function eligibleTimeoutTargets(profiles) {
  return (Array.isArray(profiles) ? profiles : [])
    .filter(row => typeof row?.name === 'string' && row.name.length > 0 &&
      splitRoutingSupported(row.timeouts) && row.timeouts.editable === true)
    .map(row => row.name)
}

export function reconcileTimeoutTargets(selected, profiles) {
  if (!Array.isArray(selected)) return eligibleTimeoutTargets(profiles)
  // Eligibility only initializes the selection. A previously selected target
  // becoming readonly/unsupported must block a save, not silently narrow it.
  const allowed = new Set((Array.isArray(profiles) ? profiles : []).map(row => row?.name))
  return uniqueProfileNames(selected).filter(name => allowed.has(name))
}

function copyProfileBaselines(profiles) {
  return Object.fromEntries((Array.isArray(profiles) ? profiles : [])
    .map(row => {
      const draft = copyProfileDraft(row)
      if (!draft) return [row?.name, null]
      const timeouts = copyTimeoutSettings(row.timeouts)
      return [row.name, { ...draft, ...(timeouts ? { timeouts } : {}) }]
    })
    .filter(([name, baseline]) => typeof name === 'string' && name.length > 0 && baseline))
}

function timeoutBaselinesFromProfiles(profileBaselines) {
  return Object.fromEntries(Object.entries(profileBaselines || {})
    .map(([name, baseline]) => [name, copyTimeoutSettingsShape(baseline?.timeouts)])
    .filter(([, baseline]) => baseline))
}

function currentTimeoutsFromProfiles(profiles) {
  return Object.fromEntries((Array.isArray(profiles) ? profiles : [])
    .map(row => [row?.name, copyTimeoutSettings(row?.timeouts)])
    .filter(([name]) => typeof name === 'string' && name.length > 0))
}

export function parseTimeoutMinutes(value) {
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? value : null
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = Number(value.trim())
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

function timeoutBaselineSeconds(baseline, minuteKey) {
  if (minuteKey === 'delegate_total_minutes') return baseline?.delegate_total_seconds
  if (baseline?.schema === 1) return baseline.routed_total_seconds
  return minuteKey === 'routed_light_total_minutes'
    ? baseline?.routed_light_total_seconds
    : baseline?.routed_heavy_total_seconds
}

function timeoutBaselineMinute(baseline, minuteKey) {
  const seconds = timeoutBaselineSeconds(baseline, minuteKey)
  return validSeconds(seconds) ? seconds / 60 : null
}

export function timeoutDraftChanged(timeouts, baseline) {
  if (!timeouts || !baseline) return false
  return TIMEOUT_MINUTE_KEYS.some(key => {
    const value = parseTimeoutMinutes(timeouts[key])
    const original = timeoutBaselineMinute(baseline, key)
    return value === null || original === null || value !== original
  })
}

export function timeoutRevisionMatches(baseline, currentTimeouts) {
  return Boolean(baseline && validTimeoutSettingsShape(currentTimeouts) &&
    currentTimeouts.revision === baseline.revision)
}

function timeoutPayloadValues(timeouts, baseline) {
  if (!timeouts || !baseline) return null
  const values = {}
  for (const key of TIMEOUT_MINUTE_KEYS) {
    const minutes = parseTimeoutMinutes(timeouts[key])
    const secondsKey = key === 'delegate_total_minutes'
      ? 'delegate_total_seconds'
      : key === 'routed_light_total_minutes' ? 'routed_light_total_seconds' : 'routed_heavy_total_seconds'
    if (minutes === null) return null
    const sourceSeconds = timeoutBaselineSeconds(baseline, key)
    const baselineMinutes = validSeconds(sourceSeconds) ? sourceSeconds / 60 : null
    const seconds = minutes === baselineMinutes ? sourceSeconds : minutes * 60
    if (!validSeconds(seconds)) return null
    values[secondsKey] = seconds
  }
  return values
}

function timeoutUpdateError() {
  return '각 시간 제한을 0 이상의 유한한 분 단위 숫자로 입력하세요. 입력값을 초 단위로 변환할 수 없는 경우 저장할 수 없습니다.'
}

export function buildTimeoutUpdate(profile, timeouts, baseline, currentTimeouts) {
  const changed = timeoutDraftChanged(timeouts, baseline)
  if (!changed) return { changed: false, update: null, error: '' }
  if (!baseline || !timeouts || typeof profile !== 'string' || !profile) {
    return { changed: true, update: null, error: '시간 제한 편집 상태를 확인할 수 없습니다. 상태를 새로고침하세요.' }
  }
  if (timeouts.editable !== true || timeouts.split_routing_supported !== true || baseline.editable !== true || baseline.split_routing_supported !== true) {
    return { changed: true, update: null, error: '역할별 시간 제한 지원이 확인되지 않아 현재 시간 제한은 읽기 전용입니다.' }
  }
  if (timeouts.revision !== baseline.revision || !timeoutRevisionMatches(baseline, currentTimeouts) ||
    currentTimeouts.editable !== true || currentTimeouts.split_routing_supported !== true) {
    return { changed: true, update: null, error: '시간 제한 revision 또는 역할별 지원 상태가 바뀌었거나 편집할 수 없습니다. 상태를 새로고침한 뒤 다시 편집하세요.' }
  }
  const values = timeoutPayloadValues(timeouts, baseline)
  if (!values) return { changed: true, update: null, error: timeoutUpdateError() }
  return {
    changed: true,
    update: { profile, expected_revision: baseline.revision, ...values },
    error: ''
  }
}

export function buildTimeoutUpdates(sourceProfile, timeouts, targetNames, baselinesByProfile, currentByProfile) {
  const targets = uniqueProfileNames(targetNames)
  if (!sourceProfile || !timeouts || typeof timeouts !== 'object') {
    return { updates: [], errors: ['시간 제한 편집 상태를 확인할 수 없습니다. 상태를 새로고침하세요.'] }
  }
  if (!targets.length) {
    return { updates: [], errors: ['시간 제한 적용 대상이 0개입니다. 편집 가능한 프로필을 하나 이상 선택하세요.'] }
  }
  const sourceBaseline = baselinesByProfile?.[sourceProfile]
  const sourceCurrent = currentByProfile?.[sourceProfile]
  if (!sourceBaseline || !validTimeoutsDto(sourceCurrent) || sourceBaseline.editable !== true ||
    sourceBaseline.split_routing_supported !== true || sourceCurrent.editable !== true ||
    sourceCurrent.split_routing_supported !== true || !timeoutRevisionMatches(sourceBaseline, sourceCurrent)) {
    return { updates: [], errors: [`시간 제한 원본 프로필 ${sourceProfile}의 역할별 지원 또는 불러온 revision을 확인할 수 없습니다. 상태를 새로고침하세요.`] }
  }
  const values = timeoutPayloadValues(timeouts, sourceBaseline)
  if (!values) return { updates: [], errors: [timeoutUpdateError()] }
  const updates = []
  const errors = []
  for (const profile of targets) {
    const baseline = baselinesByProfile?.[profile]
    const current = currentByProfile?.[profile]
    if (!baseline || !validTimeoutsDto(current) || !validTimeoutSettingsShape(baseline) ||
      baseline.editable !== true || baseline.split_routing_supported !== true || current.editable !== true ||
      current.split_routing_supported !== true || !timeoutRevisionMatches(baseline, current)) {
      errors.push(`${profile} 프로필의 역할별 시간 제한 지원, revision 또는 편집 권한을 확인할 수 없습니다. 상태를 새로고침하세요.`)
      continue
    }
    updates.push({ profile, expected_revision: baseline.revision, ...values })
  }
  return { updates: errors.length ? [] : updates, errors }
}

export function copyProfileDraft(profile) {
  if (!profile || typeof profile !== 'object' || !profile.models || !profile.routing) return null
  const timeouts = timeoutDraftFromSettings(profile.timeouts)
  return deepClone({
    models: profile.models,
    routing: profile.routing,
    ...(timeouts ? { timeouts } : {})
  })
}

export function toggleName(names, name, checked) {
  const set = new Set(Array.isArray(names) ? names : [])
  if (checked) set.add(name)
  else set.delete(name)
  return [...set]
}

export function buildPreviewBody(revision, profile, draft, modelTargets, routingProfiles, routingTargets) {
  return {
    expected_revision: revision,
    profile,
    models: deepClone(draft.models),
    model_targets: Array.isArray(modelTargets) ? [...modelTargets] : [],
    routing: { ...deepClone(draft.routing), enabled: routingProfiles.includes(profile) },
    routing_profiles: [...routingProfiles],
    ...(routingTargets === undefined ? {} : { routing_targets: [...routingTargets] })
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
    name: '비-OpenAI 제공자 조합',
    description: '대체 순서: Xiaomi 다음 DeepSeek',
    chain: [
      { provider: 'xiaomi', model: 'mimo-v2.6-pro' },
      { provider: 'deepseek', model: 'deepseek-flash' }
    ]
  },
  {
    id: 'openai-api',
    name: 'OpenAI API 모델',
    description: 'API 사용량에 따라 추가 비용이 발생할 수 있습니다.',
    chain: [{ provider: 'openai-api', model: 'gpt-6-astra' }]
  }
])

export const ROUTING_FALLBACK_PRESETS = freezeDeep([
  {
    id: 'openai-api',
    name: 'OpenAI API 모델 조합',
    description: 'Heavy와 Light는 다른 모델을 사용합니다. API 사용량에 따라 추가 비용이 발생할 수 있습니다.',
    heavy: { provider: 'openai-api', model: 'gpt-6-astra', reasoning: 'max' },
    light: { provider: 'openai-api', model: 'gpt-5.6-luna', reasoning: 'max' }
  },
  {
    id: 'non-openai',
    name: '비-OpenAI 모델 조합',
    description: 'Heavy는 Xiaomi, Light는 DeepSeek를 사용합니다.',
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

export function selectFallbackTargets(selected, sourceProfile, profileNames, initialTargets = profileNames) {
  if (Array.isArray(selected)) return reconcileFallbackTargets(selected, profileNames)
  return reconcileFallbackTargets(initialTargets, profileNames) || []
}

export function editableFallbackTargets(scope, profiles) {
  return (Array.isArray(profiles) ? profiles : []).filter(row => fallbackScopeEditable(scope, row)).map(row => row.name)
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
  if (!draft || typeof draft.enabled !== 'boolean' || !Array.isArray(draft.chain)) return '일반 대화 폴백 설정을 확인할 수 없습니다.'
  if (draft.chain.length > 5) return '일반 대화 폴백 목록은 최대 5개까지 지원합니다.'
  if (draft.chain.some(item => !item || typeof item.provider !== 'string' || !item.provider.trim() || typeof item.model !== 'string' || !item.model.trim())) return '각 폴백 항목에 공급자와 모델을 입력하세요.'
  const identities = draft.chain.map(item => JSON.stringify([item.provider, item.model]))
  if (new Set(identities).size !== identities.length) return '일반 대화 폴백 목록에 중복된 공급자·모델 조합이 있습니다.'
  if (draft.enabled && draft.chain.length === 0) return '일반 대화 폴백을 켜려면 모델을 하나 이상 추가하세요.'
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

export function primaryRouteForFallback(row, role, projection = null) {
  const isRoutingDraft = projection && (Array.isArray(projection.routing_targets)
    ? projection.routing_targets.includes(row?.name)
    : row?.name === projection.profile)
  const configured = (isRoutingDraft ? projection.routing : row?.routing)?.[role]
  if (configured?.follow === 'custom' && configured.custom) return configured.custom
  const modelRole = role === 'heavy' ? 'main' : 'delegation'
  if (projection?.model_targets?.includes(row?.name)) return projection.models?.[modelRole] || null
  return row?.models?.[modelRole] || row?.actual_models?.[modelRole] || null
}

export function routingFallbackValidation(draft, targetRows = [], projection = null) {
  if (!draft || typeof draft.enabled !== 'boolean') return '작업·검증 라우팅 폴백 설정을 확인할 수 없습니다.'
  if (!draft.enabled) return ''
  for (const role of ['heavy', 'light']) {
    const route = draft[role]
    if (!route || ['provider', 'model', 'reasoning'].some(key => typeof route[key] !== 'string' || !route[key].trim())) {
      return `${role === 'heavy' ? 'Heavy' : 'Light'} 대체 경로의 공급자·모델·추론 강도를 입력하세요.`
    }
  }
  if (routeIdentity(draft.heavy) === routeIdentity(draft.light)) return 'Heavy와 Light 대체 모델은 서로 달라야 합니다.'
  for (const row of targetRows) {
    for (const role of ['heavy', 'light']) {
        if (routeIdentity(draft[role]) && routeIdentity(draft[role]) === routeIdentity(primaryRouteForFallback(row, role, projection))) {
        return `${row.name} 프로필의 ${role === 'heavy' ? 'Heavy' : 'Light'} 기본 경로와 대체 경로는 달라야 합니다.`
      }
    }
  }
  return ''
}

export function fallbackScopeTitle(scope) {
  return ({ native: '일반 대화 폴백', routing: '작업·검증 라우팅 폴백', delegation: '네이티브 서브 에이전트 폴백' })[scope] || '폴백'
}

function fallbackValueForScope(scope, value) {
  if (!value) return null
  if (scope === 'native') return {
    enabled: value.enabled === true,
    chain: (value.chain || []).map(({ provider, model }) => ({ provider, model }))
  }
  if (scope === 'routing') return {
    enabled: value.enabled === true,
    heavy: value.heavy ? deepClone(value.heavy) : null,
    light: value.light ? deepClone(value.light) : null
  }
  return {
    mode: value.mode,
    chain: value.mode === 'custom' ? (value.chain || []).map(({ provider, model }) => ({ provider, model })) : []
  }
}

function fallbackScopeEditable(scope, row) {
  if (scope === 'native') return row?.fallbacks?.native?.editable === true
  if (scope === 'delegation') return validDelegationFallbackState(row?.fallbacks?.delegation) && row.fallbacks.delegation.editable === true
  const state = row?.fallbacks?.routing
  return Boolean(state && state.editable !== false && state.readonly !== true)
}

function fallbackScopeValidation(scope, value, rows, projection) {
  if (scope === 'native') {
    const invalid = nativeFallbackValidation(value)
    if (invalid) return invalid
    if (value.enabled) {
      for (const row of rows) {
        const primary = projection?.model_targets?.includes(row.name)
          ? projection.models?.main
          : row.actual_models?.main || row.models?.main
        if (primary && value.chain.some(item => routeIdentity(item) === routeIdentity(primary))) {
          return `${row.name}의 기본 대화 모델과 대화 폴백 모델은 달라야 합니다.`
        }
      }
    }
    return ''
  }
  if (scope === 'routing') return routingFallbackValidation(value, rows, projection)
  return delegationFallbackValidation(value)
}

export function buildFallbackPreviewBody(revision, scope, targetNames, value, profiles) {
  const byName = new Map((Array.isArray(profiles) ? profiles : []).map(row => [row.name, row]))
  const selected = uniqueProfileNames(targetNames).filter(name => byName.has(name))
  const scopeValue = fallbackValueForScope(scope, value)
  const key = scope === 'native' ? 'native_fallback' : scope === 'routing' ? 'routing_fallback' : 'delegation_fallback'
  const updates = selected.map(profile => ({ profile, [key]: deepClone(scopeValue) }))
  const confirmations = selected.filter(profile => fallbackTargetNeedsConsent(scope, byName.get(profile), scopeValue))
    .map(profile => ({
      profile,
      scope,
      allow_additional_cost: true,
      allow_task_rerun: scope === 'routing'
    }))
  return { expected_revision: revision, updates, confirmations }
}

export function buildCombinedPreviewBody(revision, profile, draft, modelTargets, routingProfiles, fallbackDrafts, fallbackBaselines, fallbackTargets, profiles, fallbackSupported = true, fallbackTargetEdits = {}, routingTargets, timeoutSettings = null) {
  const body = buildPreviewBody(revision, profile, draft, modelTargets, routingProfiles, routingTargets)
  const rows = Array.isArray(profiles) ? profiles : []
  const byName = new Map(rows.map(row => [row.name, row]))
  const projection = { profile, models: deepClone(draft.models), routing: deepClone(body.routing), model_targets: [...body.model_targets], routing_targets: body.routing_targets }
  const errors = []
  const updatesByProfile = new Map()
  const confirmations = []
  const scopes = ['native', 'routing', 'delegation']

  for (const scope of scopes) {
    const value = fallbackValueForScope(scope, fallbackDrafts?.[scope])
    const baseline = fallbackValueForScope(scope, fallbackBaselines?.[scope])
    const targetsWereEdited = fallbackTargetEdits[scope] === true
    const changed = Boolean(value && !sameValue(value, baseline))
    if (!changed && !targetsWereEdited) continue
    const title = fallbackScopeTitle(scope)
    if (!fallbackSupported) {
      errors.push(`${title}는 현재 백엔드에서 편집할 수 없습니다. 기존 설정을 보존했습니다.`)
      continue
    }
    if (!value) {
      errors.push(`${title}의 편집 가능한 설정을 확인할 수 없습니다. 상태를 새로고침하세요.`)
      continue
    }
    const targets = selectFallbackTargets(fallbackTargets?.[scope], profile, rows.map(row => row.name), editableFallbackTargets(scope, rows))
    if (!targets.length) {
      errors.push(`${title} 변경 대상이 0개입니다. 적용할 프로필을 하나 이상 선택하세요.`)
      continue
    }
    const targetRows = targets.map(name => byName.get(name)).filter(Boolean)
    if (targetRows.length !== targets.length) {
      errors.push(`${title} 대상 프로필 목록이 최신 상태가 아닙니다. 상태를 새로고침하세요.`)
      continue
    }
    const readOnly = targetRows.filter(row => !fallbackScopeEditable(scope, row)).map(row => row.name)
    if (readOnly.length) {
      errors.push(`${title}은(는) ${readOnly.join(', ')} 프로필에서 읽기 전용이므로 변경할 수 없습니다.`)
      continue
    }
    const validation = fallbackScopeValidation(scope, value, targetRows, projection)
    if (validation) {
      errors.push(`${title}: ${validation}`)
      continue
    }
    const key = scope === 'native' ? 'native_fallback' : scope === 'routing' ? 'routing_fallback' : 'delegation_fallback'
    for (const name of targets) {
      const update = updatesByProfile.get(name) || { profile: name }
      update[key] = deepClone(value)
      updatesByProfile.set(name, update)
      if (fallbackTargetNeedsConsent(scope, byName.get(name), value)) {
        confirmations.push({ profile: name, scope, allow_additional_cost: true, allow_task_rerun: scope === 'routing' })
      }
    }
  }

  if (updatesByProfile.size) {
    body.fallback_updates = [...updatesByProfile.values()]
    body.fallback_confirmations = confirmations
  }
  if (timeoutSettings) {
    const requested = timeoutSettings.copyIntent === true || timeoutDraftChanged(timeoutSettings.draft, timeoutSettings.baseline)
    if (requested && timeoutSettings.baselinesByProfile && timeoutSettings.currentByProfile) {
      const timeoutResult = buildTimeoutUpdates(
        timeoutSettings.profile,
        timeoutSettings.draft,
        timeoutSettings.targets,
        timeoutSettings.baselinesByProfile,
        timeoutSettings.currentByProfile
      )
      if (timeoutResult.updates.length) body.timeout_updates = timeoutResult.updates
      errors.push(...timeoutResult.errors)
    } else if (!timeoutSettings.baselinesByProfile || !timeoutSettings.currentByProfile) {
      const timeoutResult = buildTimeoutUpdate(
        timeoutSettings.profile,
        timeoutSettings.draft,
        timeoutSettings.baseline,
        timeoutSettings.current
      )
      if (timeoutResult.update) body.timeout_updates = [timeoutResult.update]
      if (timeoutResult.error) errors.push(timeoutResult.error)
    }
  }
  return { body, errors }
}

export function buildScopedPreviewBody(snapshot, saveScope) {
  if (!snapshot || !['models', 'routing', 'timeouts'].includes(saveScope)) {
    return { body: null, errors: ['저장 범위를 확인할 수 없습니다.'] }
  }
  const baseline = snapshot.profileBaselines?.[snapshot.profile]
  if (!baseline?.models || !baseline?.routing || !snapshot.draft) {
    return { body: null, errors: ['불러온 기준 설정을 확인할 수 없습니다. 상태를 새로고침하세요.'] }
  }
  const baselineMembership = Object.entries(snapshot.profileBaselines || {})
    .filter(([, row]) => row?.routing?.enabled === true)
    .map(([name]) => name)
  const models = saveScope === 'models' ? snapshot.draft.models : baseline.models
  const routing = saveScope === 'routing' ? snapshot.draft.routing : baseline.routing
  const routingWithSavedFallback = deepClone(routing)
  if (Object.prototype.hasOwnProperty.call(baseline.routing, 'fallback') && baseline.routing.fallback !== undefined) {
    routingWithSavedFallback.fallback = deepClone(baseline.routing.fallback)
  } else {
    delete routingWithSavedFallback.fallback
  }
  const routingProfiles = saveScope === 'routing' ? snapshot.routingProfiles : baselineMembership
  const modelTargets = saveScope === 'models' ? snapshot.modelTargets : []
  const routingTargets = saveScope === 'routing' ? snapshot.routingTargets : []
  const body = buildPreviewBody(snapshot.revision, snapshot.profile, {
    models: deepClone(models),
    routing: routingWithSavedFallback
  }, modelTargets, routingProfiles, routingTargets)
  body.save_scope = saveScope
  if (saveScope !== 'timeouts') return { body, errors: [] }
  const timeoutResult = buildTimeoutUpdates(
    snapshot.profile,
    snapshot.draft.timeouts,
    snapshot.timeoutTargets,
    snapshot.timeoutBaselinesByProfile,
    snapshot.currentTimeoutsByProfile
  )
  if (timeoutResult.updates.length) body.timeout_updates = timeoutResult.updates
  return { body, errors: timeoutResult.errors }
}

export function projectedRoutingFallbackErrors(profiles, projection, updatedFallbackProfiles = []) {
  const updated = new Set(updatedFallbackProfiles)
  const errors = []
  for (const row of Array.isArray(profiles) ? profiles : []) {
    const value = copyRoutingFallbackDraft(row?.fallbacks?.routing)
    if (!value?.enabled || updated.has(row.name)) continue
    const primaryChanged = ['heavy', 'light'].some(role =>
      routeIdentity(primaryRouteForFallback(row, role)) !== routeIdentity(primaryRouteForFallback(row, role, projection))
    )
    if (!primaryChanged) continue
    const error = routingFallbackValidation(value, [row], projection)
    if (error) errors.push(`프로필 ${row.name}의 저장된 작업·검증 라우팅 폴백: ${error}`)
  }
  return errors
}

export function previewFieldLabel(field) {
  const labels = {
    native_fallback: '일반 대화 폴백',
    fallback_providers: '일반 대화 폴백 목록',
    fallback_model: '이전 대화 폴백 설정',
    'routing.fallback': '작업·검증 라우팅 폴백',
    delegation_fallback: '네이티브 서브 에이전트 폴백',
    'delegation.fallback_providers': '네이티브 서브 에이전트 폴백 목록',
    'fallback_consent.native': '일반 대화 폴백 승인 기록',
    'fallback_consent.routing': '작업·검증 라우팅 폴백 승인 기록',
    'fallback_consent.delegation': '네이티브 서브 에이전트 폴백 승인 기록'
  }
  return labels[field] || field || '설정 항목'
}

export function fallbackPreviewMatchesScope(preview, scopeKey, generation, profile, scope) {
  return Boolean(preview && preview.scopeKey === scopeKey && preview.generation === generation &&
    preview.profile === profile && preview.scope === scope)
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

function TimeoutField({ id, label, value, onChange, disabled, describedBy }) {
  return jsxs('label', {
    htmlFor: id,
    style: styles.field,
    children: [
      jsx('span', { style: styles.fieldName, children: label }),
      jsx(Input, {
        id,
        type: 'number',
        min: 0,
        step: 'any',
        inputMode: 'decimal',
        style: { width: '100%', minWidth: 0, boxSizing: 'border-box' },
        value: value ?? '',
        onChange: event => onChange(event.target.value),
        disabled,
        'aria-label': label,
        'aria-describedby': describedBy
      }),
      jsx('span', { style: styles.hint, children: '분 (minutes)' })
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
  const operation = { '/status': 'status', '/preview': 'preview', '/fallback-preview': 'fallback-preview', '/apply': 'apply' }[path]
  if (!operation) throw new Error('지원하지 않는 플러그인 요청입니다.')
  const profile = options.profile || host.state.profile.get() || 'default'
  const reply = await host.request('cli.exec', {
    argv: ['--profile', profile, 'model-router', operation, '--body', JSON.stringify(options.body || {})],
    profile,
    timeout: 180
  }, 210000)
  if (reply.blocked) throw new Error(reply.hint || '요청이 차단되었습니다.')
  const line = String(reply.output || '').split(/\r?\n/).find(value => value.startsWith('MODEL_ROUTER_JSON:'))
  if (!line) throw new Error('플러그인 응답을 확인할 수 없습니다. 활성화 상태를 확인하세요.')
  let data
  try { data = JSON.parse(line.slice('MODEL_ROUTER_JSON:'.length)) }
  catch { throw new Error('플러그인 응답이 잘렸거나 손상됐습니다. 상태를 다시 확인하세요.') }
  if (reply.code !== 0 || data.error) throw new Error(data.message || '요청이 완료되지 않았습니다.')
  return data
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
  const [draftRevision, setDraftRevision] = useState(null)
  const [timeoutBaseline, setTimeoutBaseline] = useState(null)
  const [timeoutTargets, setTimeoutTargets] = useState(null)
  const [timeoutTargetEdited, setTimeoutTargetEdited] = useState(false)
  const [profileBaselines, setProfileBaselines] = useState(null)
  const [sectionErrors, setSectionErrors] = useState({ models: '', routing: '', timeouts: '' })
  const [modelTargets, setModelTargets] = useState(null)
  const [routingProfiles, setRoutingProfiles] = useState([])
  const [routingTargets, setRoutingTargets] = useState(null)
  const [routingBaseline, setRoutingBaseline] = useState(null)
  const [routingTargetEdited, setRoutingTargetEdited] = useState(false)
  const [fallbackDrafts, setFallbackDrafts] = useState({ native: null, routing: null, delegation: null })
  const [fallbackBaselines, setFallbackBaselines] = useState({ native: null, routing: null, delegation: null })
  const [fallbackTargets, setFallbackTargets] = useState({ native: null, routing: null, delegation: null })
  const [fallbackTargetEdits, setFallbackTargetEdits] = useState({ native: false, routing: false, delegation: false })
  const [fallbackPreview, setFallbackPreview] = useState(null)
  const [fallbackPreviewPending, setFallbackPreviewPending] = useState(false)
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
  const refreshPendingRef = useRef(false)
  const needsReloadRef = useRef(false)
  const applyScopeRef = useRef(null)
  const applyPhaseRef = useRef(null)
  const selectedProfileRef = useRef(null)
  const timeoutTargetsManualRef = useRef(false)
  selectedProfileRef.current = selectedProfile

  const statusKey = ['model-router', 'status', scopeKey]
  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => ctx.rest('/status'),
    retry: false,
    staleTime: 0
  })
  const profiles = Array.isArray(statusQuery.data?.profiles) ? statusQuery.data.profiles : []
  const statusDataRef = useRef(statusQuery.data)
  statusDataRef.current = statusQuery.data
  const revisionChanged = draftRevision !== null && statusQuery.data?.revision !== draftRevision
  const loadedTimeoutRow = profiles.find(item => item.name === selectedProfile) || null
  const timeoutChanged = timeoutDraftChanged(draft?.timeouts, timeoutBaseline)
  const timeoutWriteRequested = timeoutChanged || timeoutTargetEdited
  const timeoutBaselineMap = timeoutBaselinesFromProfiles(profileBaselines)
  const selectedTimeoutTargets = reconcileTimeoutTargets(timeoutTargets, profiles)
  const timeoutSourceRevisionChanged = Boolean(timeoutBaseline && (
    !validTimeoutsDto(loadedTimeoutRow?.timeouts) ||
    timeoutBaselineMap[selectedProfile]?.editable !== loadedTimeoutRow?.timeouts?.editable ||
    timeoutBaselineMap[selectedProfile]?.split_routing_supported !== (loadedTimeoutRow?.timeouts?.split_routing_supported === true) ||
    !timeoutRevisionMatches(timeoutBaselineMap[selectedProfile], loadedTimeoutRow?.timeouts)
  ))
  const timeoutTargetsRevisionChanged = selectedTimeoutTargets.some(name => {
    const row = profiles.find(item => item.name === name)
    const baseline = timeoutBaselineMap[name]
    return !validTimeoutsDto(row?.timeouts) || baseline?.editable !== row?.timeouts?.editable ||
      baseline?.split_routing_supported !== (row?.timeouts?.split_routing_supported === true) ||
      row?.timeouts?.editable !== true || row?.timeouts?.split_routing_supported !== true ||
      !timeoutRevisionMatches(baseline, row?.timeouts)
  })
  const timeoutRevisionChanged = timeoutWriteRequested && (timeoutSourceRevisionChanged || timeoutTargetsRevisionChanged)
  const timeoutSaveRevisionChanged = timeoutSourceRevisionChanged || timeoutTargetsRevisionChanged
  useEffect(() => {
    if ((!revisionChanged && !timeoutRevisionChanged) || applyPendingRef.current || refreshPendingRef.current) return
    // Never pair old draft/copy intent with a newer query revision. Preserve
    // the draft for inspection but require an explicit fresh baseline.
    if (revisionChanged) {
      generationRef.current += 1
      setRoutingTargetEdited(false)
    }
    setPreview(null)
    setFallbackPreview(null)
  }, [revisionChanged, timeoutRevisionChanged, draftRevision, timeoutBaseline?.revision, statusQuery.data?.revision, applyPending])

  useEffect(() => {
    if (readyScope === scopeKey) return
    generationRef.current += 1
    setPreview(null)
    setPreviewPending(false)
    setReviewed(false)
    setSelectedProfile(null)
    setDraft(null)
    setDraftRevision(null)
    setTimeoutBaseline(null)
    setTimeoutTargets(null)
    setTimeoutTargetEdited(false)
    timeoutTargetsManualRef.current = false
    setProfileBaselines(null)
    setSectionErrors({ models: '', routing: '', timeouts: '' })
    setModelTargets(null)
    setRoutingProfiles([])
    setRoutingTargets(null)
    setRoutingBaseline(null)
    setRoutingTargetEdited(false)
    setFallbackDrafts({ native: null, routing: null, delegation: null })
    setFallbackBaselines({ native: null, routing: null, delegation: null })
    setFallbackTargets({ native: null, routing: null, delegation: null })
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
    setFallbackPreview(null)
    setFallbackPreviewPending(false)
    setFallbackError('')
    setPageError('')
    if (applyPendingRef.current) {
      const wasApplying = applyPhaseRef.current === 'apply'
      const originalScope = applyScopeRef.current || readyScope
      applyPendingRef.current = false
      applyPhaseRef.current = null
      setApplyPending(false)
      if (wasApplying) {
        needsReloadRef.scopeKey = originalScope
        setApplyOutcome({ kind: 'unknown', message: '적용 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 적용하지 마세요. 적용을 시작한 원래 프로필·연결로 돌아가 실제 상태를 새로고침하세요.' })
        needsReloadRef.current = true
        setNeedsReload(true)
      } else if (!needsReloadRef.current) {
        setApplyOutcome(null)
      }
    } else if (!needsReloadRef.current) {
      setApplyOutcome(null)
    }
    setReadyScope(scopeKey)
  }, [readyScope, scopeKey])

  useEffect(() => {
    if (readyScope !== scopeKey || !statusQuery.data || selectedProfile !== null) return
    const row = profiles.find(item => item.name === statusQuery.data.current_profile) || profiles[0]
    if (!row) return
    const nextDraft = copyProfileDraft(row)
    setSelectedProfile(row.name)
    setDraftRevision(statusQuery.data.revision)
    setDraft(nextDraft)
    setTimeoutBaseline(copyTimeoutBaseline(row.timeouts))
    setProfileBaselines(copyProfileBaselines(profiles))
    timeoutTargetsManualRef.current = false
    setTimeoutTargets(current => reconcileTimeoutTargets(current, profiles))
    setTimeoutTargetEdited(false)
    setRoutingBaseline(deepClone({ heavy: row.routing.heavy, light: row.routing.light }))
    setRoutingTargetEdited(false)
    const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
    const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
    const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
    setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
    setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
    setModelTargets(current => reconcileModelTargets(current, profiles.map(item => item.name)))
    setFallbackTargets(current => Object.fromEntries(['native', 'routing', 'delegation'].map(scope => [scope, selectFallbackTargets(current[scope], row.name, profiles.map(item => item.name), editableFallbackTargets(scope, profiles))])))
    setRoutingProfiles(profiles.filter(item => item.routing?.enabled === true).map(item => item.name))
    setRoutingTargets(current => reconcileModelTargets(current, profiles.map(item => item.name)))
  }, [readyScope, scopeKey, statusQuery.data, selectedProfile, profiles])

  const invalidatePlan = () => {
    const invalidated = invalidatePlanState(generationRef.current)
    generationRef.current = invalidated.generation
    setPreview(invalidated.preview)
    setPreviewPending(invalidated.previewPending)
    setReviewed(invalidated.reviewed)
    setFallbackPreview(null)
    setFallbackPreviewPending(false)
    setFallbackError('')
    setSectionErrors({ models: '', routing: '', timeouts: '' })
    setPageError('')
  }
  const updateDraft = updater => {
    if (applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setDraft(current => current ? updater(current) : current)
  }
  const currentRow = profiles.find(item => item.name === selectedProfile) || null
  const profileNames = profiles.map(item => item.name)
  const nativeFallbackTargets = selectFallbackTargets(fallbackTargets.native, selectedProfile, profileNames, editableFallbackTargets('native', profiles))
  const routingFallbackTargets = selectFallbackTargets(fallbackTargets.routing, selectedProfile, profileNames, editableFallbackTargets('routing', profiles))
  const delegationFallbackTargets = selectFallbackTargets(fallbackTargets.delegation, selectedProfile, profileNames, editableFallbackTargets('delegation', profiles))
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
  const routingFallbackError = routingFallbackDraft ? routingFallbackValidation(routingFallbackDraft, routingFallbackRows) : '이 프로필의 작업 라우팅 폴백 상태를 지원하지 않습니다.'
  const delegationFallbackError = delegationFallbackDraft ? delegationFallbackValidation(delegationFallbackDraft) : '네이티브 서브 에이전트 폴백 설정을 확인할 수 없습니다. 상태를 새로고침하세요.'
  const selectedRoutingTargets = reconcileModelTargets(routingTargets, profileNames)
  const routingDraftChanged = Boolean(draft && routingBaseline && !sameValue({ heavy: draft.routing.heavy, light: draft.routing.light }, routingBaseline))
  const routingCopyPending = !revisionChanged && (routingDraftChanged || routingTargetEdited)
  const routingWriteTargets = routingCopyPending ? selectedRoutingTargets : []
  const routingTargetError = routingCopyPending && !selectedRoutingTargets.length ? 'Heavy/Light 설정 적용 대상이 0개입니다. 적용할 프로필을 하나 이상 선택하세요.' : ''
  const selectedTargets = reconcileModelTargets(modelTargets, profileNames)
  const allTargetsSelected = allModelTargetsSelected(selectedTargets, profileNames)
  const targetSummary = allTargetsSelected ? `전체 ${profileNames.length}개 프로필` : `${selectedTargets.length}/${profileNames.length}개 프로필`
  const timeoutDraftResult = buildTimeoutUpdate(selectedProfile, draft?.timeouts, timeoutBaseline, currentRow?.timeouts)
  const timeoutSettingsSupported = validTimeoutsDto(currentRow?.timeouts)
  const timeoutRoleSupported = splitRoutingSupported(currentRow?.timeouts)
  const timeoutSettingsEditable = timeoutSettingsSupported && timeoutRoleSupported && currentRow?.timeouts?.editable === true && Boolean(draft?.timeouts)
  const disabled = applyPending || needsReload || revisionChanged || statusQuery.isFetching || !selectedProfile || !draft
  const timeoutSaveValuesValid = Boolean(timeoutPayloadValues(draft?.timeouts, timeoutBaseline))
  const timeoutSaveDisabled = disabled || !timeoutSettingsEditable || !selectedTimeoutTargets.length ||
    timeoutSourceRevisionChanged || timeoutTargetsRevisionChanged || !timeoutSaveValuesValid
  const validPreview = previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile)
  const renderGeneration = generationRef.current
  const activeRoutes = draft?.routing || {}
  const routingSummary = `무거운 작업: ${activeRoutes.heavy?.follow === 'custom' ? '별도 모델' : '기본 모델'} · 가벼운 작업: ${activeRoutes.light?.follow === 'custom' ? '별도 모델' : '위임 모델'}`

  const selectProfile = name => {
    if (applyPendingRef.current || needsReloadRef.current) return
    const row = profiles.find(item => item.name === name)
    if (!row) return
    const loadedBaseline = profileBaselines?.[name] || copyProfileDraft(row)
    if (!loadedBaseline) return
    invalidatePlan()
    const nextDraft = deepClone(loadedBaseline)
    const timeoutDraft = timeoutDraftFromSettings(loadedBaseline.timeouts)
    if (timeoutDraft) nextDraft.timeouts = timeoutDraft
    else delete nextDraft.timeouts
    setSelectedProfile(name)
    setDraft(nextDraft)
    setTimeoutBaseline(copyTimeoutBaselineShape(loadedBaseline.timeouts))
    setTimeoutTargetEdited(false)
    setRoutingBaseline(deepClone({ heavy: loadedBaseline.routing.heavy, light: loadedBaseline.routing.light }))
    setRoutingTargetEdited(false)
    const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
    const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
    const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
    setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
    setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
    setModelTargets(current => reconcileModelTargets(current, profileNames))
    setRoutingTargets(current => reconcileModelTargets(current, profileNames))
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

  const chooseTimeoutTargets = (mode, name = null, checked = false) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const eligible = eligibleTimeoutTargets(profiles)
    let next = selectedTimeoutTargets
    if (mode === 'all') next = eligible
    else if (mode === 'source') next = eligible.includes(selectedProfile) ? [selectedProfile] : []
    else if (mode === 'none') next = []
    else if (eligible.includes(name)) next = toggleName(selectedTimeoutTargets, name, checked)
    invalidatePlan()
    timeoutTargetsManualRef.current = true
    setTimeoutTargets([...next])
    setTimeoutTargetEdited(true)
  }

  const chooseRoutingTargets = (mode, name = null, checked = false) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    invalidatePlan()
    const next = mode === 'all' ? [...profileNames] : mode === 'none' ? []
      : mode === 'source' ? [selectedProfile] : toggleName(selectedRoutingTargets, name, checked)
    setRoutingTargets(next)
    setRoutingTargetEdited(next.length > 0)
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
  const updateTimeout = (key, value) => updateDraft(current => ({
    ...current,
    timeouts: { ...current.timeouts, [key]: value }
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
    invalidatePlan()
    setFallbackDrafts(current => ({
      ...current,
      [scope]: current[scope] ? updater(current[scope]) : current[scope]
    }))
  }

  const updateFallbackTarget = (scope, name, checked) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const selected = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    invalidatePlan()
    setFallbackTargets(current => ({ ...current, [scope]: toggleName(selected, name, checked) }))
    setFallbackTargetEdits(current => ({ ...current, [scope]: true }))
  }

  const chooseFallbackTargets = (scope, mode) => {
    if (applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    let selected = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    if (mode === 'source') selected = selectFallbackSourceTarget(selectedProfile, profileNames)
    if (mode === 'all') {
      const eligible = editableFallbackTargets(scope, profiles)
      selected = selectAllModelTargets(eligible)
    }
    if (mode === 'none') selected = selectNoModelTargets()
    invalidatePlan()
    setFallbackTargets(current => ({ ...current, [scope]: [...selected] }))
    setFallbackTargetEdits(current => ({ ...current, [scope]: true }))
  }

  const canPreviewFallback = scope => {
    if (!fallbackSupported || disabled || applyPendingRef.current || needsReloadRef.current || fallbackPreviewPending || !selectedProfile || !statusQuery.data) return false
    const targets = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    const rows = scope === 'native' ? nativeFallbackRows : scope === 'routing' ? routingFallbackRows : delegationFallbackRows
    if (targets.length === 0 || rows.length !== targets.length) return false
    if (scope === 'native') {
      if (!nativeFallbackDraft || currentRow?.fallbacks?.native?.editable !== true || rows.some(row => row.fallbacks?.native?.editable !== true)) return false
      return !nativeFallbackError
    }
    if (scope === 'routing') {
      if (!routingFallbackDraft || rows.some(row => !row.fallbacks?.routing || row.fallbacks.routing.editable === false || row.fallbacks.routing.readonly === true)) return false
      return !routingFallbackError
    }
    if (!delegationFallbackDraft || !validDelegationFallbackState(currentRow?.fallbacks?.delegation) || currentRow.fallbacks.delegation.editable !== true ||
      rows.some(row => !validDelegationFallbackState(row.fallbacks?.delegation) || row.fallbacks.delegation.editable !== true)) return false
    return !delegationFallbackError
  }

  const captureSaveSnapshot = () => freezeDeep({
    scopeKey,
    profile: selectedProfile,
    revision: draftRevision,
    draft: deepClone(draft),
    modelTargets: [...selectedTargets],
    routingProfiles: [...routingProfiles],
    routingTargets: [...routingWriteTargets],
    timeoutTargets: [...selectedTimeoutTargets],
    timeoutTargetEdited,
    timeoutBaselinesByProfile: timeoutBaselinesFromProfiles(profileBaselines),
    currentTimeoutsByProfile: currentTimeoutsFromProfiles(profiles),
    profileBaselines: deepClone(profileBaselines || {}),
    timeoutsBaseline: timeoutBaseline ? deepClone(timeoutBaseline) : null,
    timeoutsCurrent: copyTimeoutSettings(currentRow?.timeouts),
    timeoutWriteIntent: timeoutWriteRequested,
    routingTargetError,
    fallbackDrafts: deepClone(fallbackDrafts),
    fallbackBaselines: deepClone(fallbackBaselines),
    fallbackTargets: deepClone(fallbackTargets),
    fallbackTargetEdits: { ...fallbackTargetEdits },
    profiles: deepClone(profiles),
    fallbackSupported
  })

  const isSaveCurrent = (snapshot, token) => generationRef.current === token &&
    selectedProfileRef.current === snapshot.profile &&
    scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) === snapshot.scopeKey

  const timeoutSnapshotStillCurrent = (snapshot, updates) => {
    const names = uniqueProfileNames([snapshot.profile, ...(Array.isArray(updates) ? updates.map(update => update.profile) : [])])
    const currentRows = Array.isArray(statusDataRef.current?.profiles) ? statusDataRef.current.profiles : []
    return names.every(name => {
      const baseline = snapshot.timeoutBaselinesByProfile?.[name]
      const current = currentRows.find(row => row.name === name)?.timeouts
      if (!baseline || !validTimeoutsDto(current) || current.editable !== baseline.editable ||
        current.split_routing_supported !== baseline.split_routing_supported || current.split_routing_supported !== true ||
        (name !== snapshot.profile && current.editable !== true)) return false
      return timeoutRevisionMatches(baseline, current)
    })
  }

  const releaseSaveLock = token => {
    if (generationRef.current !== token || !applyPendingRef.current) return
    applyPendingRef.current = false
    applyPhaseRef.current = null
    setApplyPending(false)
  }

  const markApplyUnknown = (snapshot, message, result = null) => {
    setApplyOutcome({ kind: 'unknown', message, result })
    needsReloadRef.scopeKey = snapshot.scopeKey
    needsReloadRef.current = true
    setNeedsReload(true)
  }

  const recordApplyReceipt = (snapshot, receipt) => {
    if (isPartialReceipt(receipt)) {
      setApplyOutcome({ kind: 'partial', result: receipt })
    } else if (receipt?.status === 'applied' || receipt?.status === 'no_change') {
      setApplyOutcome({ kind: 'success', result: receipt })
    } else {
      markApplyUnknown(snapshot, receipt?.error || '적용 결과를 확인할 수 없습니다. 다시 저장하지 말고 실제 상태를 새로고침하세요.', receipt)
      return
    }
    needsReloadRef.scopeKey = snapshot.scopeKey
    needsReloadRef.current = true
    setNeedsReload(true)
  }

  const runSave = async ({ operation, scope = null, snapshot, prepare }) => {
    if (!snapshot || applyPendingRef.current || needsReloadRef.current) return
    const token = ++generationRef.current
    applyPendingRef.current = true
    applyScopeRef.current = snapshot.scopeKey
    applyPhaseRef.current = 'preview'
    setApplyPending(true)
    setPreview(null)
    setFallbackPreview(null)
    setPageError('')
    setFallbackError('')
    if (scope && operation !== '/fallback-preview') {
      setSectionErrors(current => ({ ...current, [scope]: '' }))
    }
    let applyStarted = false
    try {
      const prepared = prepare()
      if (prepared.errors?.length) throw new Error(prepared.errors.join(' '))
      const timeoutUpdates = Array.isArray(prepared.body?.timeout_updates) ? prepared.body.timeout_updates : []
      const result = await ctx.rest(operation, { method: 'POST', body: prepared.body })
      if (!isSaveCurrent(snapshot, token)) return
      if (timeoutUpdates.length && !timeoutSnapshotStillCurrent(snapshot, timeoutUpdates)) {
        const message = '저장 검증 중 대상 프로필의 시간 제한 revision이 바뀌었습니다. 적용하지 않았습니다. 상태를 새로고침한 뒤 다시 편집하세요.'
        if (scope && operation !== '/fallback-preview') setSectionErrors(current => ({ ...current, [scope]: message }))
        else setPageError(message)
        return
      }
      if (!result || typeof result.plan_id !== 'string' || !Array.isArray(result.changes)) {
        throw new Error('저장 계획 응답이 올바르지 않습니다. 설정은 변경되지 않았습니다.')
      }
      const planId = result.plan_id
      if (!isSaveCurrent(snapshot, token)) return
      applyStarted = true
      applyPhaseRef.current = 'apply'
      const receipt = await ctx.rest('/apply', { method: 'POST', body: { plan_id: planId }, timeoutMs: 180000 })
      if (!isSaveCurrent(snapshot, token)) {
        markApplyUnknown(snapshot, '저장 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 저장하지 마세요. 원래 연결·프로필로 돌아가 실제 상태를 새로고침하세요.')
        return
      }
      recordApplyReceipt(snapshot, receipt)
    } catch (error) {
      if (applyStarted) {
        markApplyUnknown(snapshot, error?.message || '저장 결과를 확인할 수 없습니다. 다시 저장하지 말고 실제 상태를 새로고침하세요.')
      } else if (isSaveCurrent(snapshot, token)) {
        const message = `저장되지 않았습니다. ${error?.message || '설정 검증에 실패했습니다.'}`
        if (operation === '/fallback-preview') setFallbackError({ scope, message })
        else if (scope) setSectionErrors(current => ({ ...current, [scope]: message }))
        else setPageError(message)
      }
    } finally {
      if (applyStarted && !isSaveCurrent(snapshot, token)) {
        markApplyUnknown(snapshot, '저장 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 저장하지 마세요. 원래 연결·프로필로 돌아가 실제 상태를 새로고침하세요.')
      }
      releaseSaveLock(token)
    }
  }

  const saveFallback = scope => {
    if (renderGeneration !== generationRef.current || applyPendingRef.current || needsReloadRef.current || !canPreviewFallback(scope)) return
    const snapshot = captureSaveSnapshot()
    const targetNames = scope === 'native' ? [...nativeFallbackTargets] : scope === 'routing' ? [...routingFallbackTargets] : [...delegationFallbackTargets]
    const value = deepClone(scope === 'native' ? nativeFallbackDraft : scope === 'routing' ? routingFallbackDraft : delegationFallbackDraft)
    return runSave({
      operation: '/fallback-preview', scope, snapshot,
      prepare: () => ({ body: buildFallbackPreviewBody(snapshot.revision, scope, targetNames, value, snapshot.profiles), errors: [] })
    })
  }

  const saveSection = saveScope => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !draft || !statusQuery.data ||
      applyPendingRef.current || needsReloadRef.current || !profileBaselines) return
    if (saveScope === 'timeouts' && timeoutSaveDisabled) return
    if (!['models', 'routing', 'timeouts'].includes(saveScope)) return
    const snapshot = captureSaveSnapshot()
    return runSave({
      operation: '/preview', scope: saveScope, snapshot,
      prepare: () => {
        const prepared = buildScopedPreviewBody(snapshot, saveScope)
        if (saveScope === 'routing' && snapshot.routingTargetError) {
          prepared.errors.push(snapshot.routingTargetError)
        }
        return prepared
      }
    })
  }

  const saveAll = () => {
    if (renderGeneration !== generationRef.current || revisionChanged || timeoutRevisionChanged || !currentRow || !draft || !statusQuery.data || applyPendingRef.current || needsReloadRef.current) return
    const snapshot = captureSaveSnapshot()
    return runSave({
      operation: '/preview', snapshot,
      prepare: () => {
        const combined = buildCombinedPreviewBody(
          snapshot.revision,
          snapshot.profile,
          snapshot.draft,
          snapshot.modelTargets,
          snapshot.routingProfiles,
          snapshot.fallbackDrafts,
          snapshot.fallbackBaselines,
          snapshot.fallbackTargets,
          snapshot.profiles,
          snapshot.fallbackSupported,
          snapshot.fallbackTargetEdits,
          snapshot.routingTargets,
          {
            profile: snapshot.profile,
            draft: snapshot.draft?.timeouts,
            baseline: snapshot.timeoutsBaseline,
            current: snapshot.timeoutsCurrent,
            targets: snapshot.timeoutTargets,
            baselinesByProfile: snapshot.timeoutBaselinesByProfile,
            currentByProfile: snapshot.currentTimeoutsByProfile,
            copyIntent: snapshot.timeoutTargetEdited
          }
        )
        const routingUpdates = (combined.body.fallback_updates || [])
          .filter(update => Object.prototype.hasOwnProperty.call(update, 'routing_fallback'))
          .map(update => update.profile)
        const projectedErrors = projectedRoutingFallbackErrors(snapshot.profiles, {
          profile: snapshot.profile,
          models: snapshot.draft.models,
          routing: combined.body.routing,
          model_targets: combined.body.model_targets,
          routing_targets: combined.body.routing_targets
        }, routingUpdates)
        return { body: combined.body, errors: [...combined.errors, ...projectedErrors, ...(snapshot.routingTargetError ? [snapshot.routingTargetError] : [])] }
      }
    })
  }


  const reloadStatus = async () => {
    if (applyPendingRef.current || refreshPendingRef.current) return
    if (needsReloadRef.current && needsReloadRef.scopeKey && scopeKey !== needsReloadRef.scopeKey) {
      setPageError('적용을 시작한 원래 Desktop 프로필·연결로 돌아간 뒤 실제 상태를 새로고침하세요. 이 화면에서는 결과를 추측하거나 다시 적용하지 않습니다.')
      return
    }
    invalidatePlan()
    const capturedScope = scopeKey
    const token = generationRef.current
    setPageError('')
    refreshPendingRef.current = true
    let response
    try { response = await statusQuery.refetch() } finally { refreshPendingRef.current = false }
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
    setProfileBaselines(copyProfileBaselines(rows))
    setTimeoutTargets(current => timeoutTargetsManualRef.current
      ? reconcileTimeoutTargets(current, rows)
      : eligibleTimeoutTargets(rows))
    setTimeoutTargetEdited(false)
    setSectionErrors({ models: '', routing: '', timeouts: '' })
    setModelTargets(current => reconcileModelTargets(current, rows.map(item => item.name)))
    setRoutingProfiles(rows.filter(item => item.routing?.enabled === true).map(item => item.name))
    setRoutingTargets(current => reconcileModelTargets(current, rows.map(item => item.name)))
    setFallbackTargets(current => ({
      native: reconcileFallbackTargets(current.native, rows.map(item => item.name)),
      routing: reconcileFallbackTargets(current.routing, rows.map(item => item.name)),
      delegation: reconcileFallbackTargets(current.delegation, rows.map(item => item.name))
    }))
    setDraftRevision(response.data.revision)
    if (row) {
      const nextDraft = copyProfileDraft(row)
      setSelectedProfile(row.name)
      setDraft(nextDraft)
      setTimeoutBaseline(copyTimeoutBaseline(row.timeouts))
      setRoutingBaseline(deepClone({ heavy: row.routing.heavy, light: row.routing.light }))
      setRoutingTargetEdited(false)
      const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
      const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
      const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
      setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
      setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
    } else {
      setSelectedProfile(null)
      setDraft(null)
      setTimeoutBaseline(null)
      setRoutingBaseline(null)
      setRoutingTargetEdited(false)
      setFallbackDrafts({ native: null, routing: null, delegation: null })
      setFallbackBaselines({ native: null, routing: null, delegation: null })
    }
    setFallbackError('')
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
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
      jsx('p', { id: 'fast-inheritance-note', role: 'note', style: styles.hint, children: '메인 세션에서 선택한 Fast 모드는 기본 위임과 Heavy/Light 라우팅의 새 작업이 시작할 때 상속합니다. 지원하지 않는 모델·제공자에는 Fast 옵션을 보내지 않으며, auto/cold의 남은 시간을 연장하지 않습니다. Fast 요청에는 API 추가 요금이나 Codex 크레딧 사용 증가가 있을 수 있습니다. 요청한 모드와 제공자가 실제 처리한 등급은 다를 수 있으며, 업데이트된 실행 기능은 새 세션에서 확인하세요.' }),
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
      allTargetsSelected ? jsx('p', { role: 'note', style: styles.warning, children: `모든 ${profileNames.length}개 프로필이 모델 적용 대상입니다. 아래 초안 요약에서 적용 범위를 확인하세요.` }) : null,
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `model-target-${row.name}`, label: row.name, checked: selectedTargets.includes(row.name), disabled, onChange: checked => toggleModelTarget(row.name, checked) }) }, row.name)) }),
      sectionErrors.models ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.models }) : null,
      jsx(Button, { id: 'models-save', size: 'sm', variant: 'secondary', disabled, onClick: () => void saveSection('models'), children: applyPending ? '저장 중…' : '모델 설정 저장' })
    ]
  })

  const timeoutSettingsSection = section('전체 실행 시간 제한 (TOTAL)', '불러온 프로필에서 일반 작업·Light·Heavy의 시간 제한을 각각 분 단위로 편집하고, 아래 시간 제한 적용 대상에 복사합니다. 모델·라우팅·폴백 적용 대상과는 독립적입니다.', jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' },
    children: [
      jsx('p', { id: 'timeout-policy-explanation', role: 'note', style: styles.hint, children: '세 값은 분 단위이며 각각 독립적입니다. 0은 해당 역할에 플러그인 전체 시간 상한을 두지 않습니다. 일반 서브 에이전트 전체 시간은 delegation.child_timeout_seconds의 비활동 시간 제한을 바꾸지 않습니다. 일반 서브 에이전트 시간이 끝나면 Hermes에 협조적 중단을 요청하지만 프로세스 종료를 보장하지 않습니다. 라우팅 Light와 Heavy는 각자의 제한을 사용하고, 시간 초과 시 실행 프로세스를 정리합니다. 기존 통합 시간 설정은 Light와 Heavy에 같은 값으로 표시됩니다.' }),
      jsx('p', { style: styles.hint, children: '새 작업은 시작할 때 현재 정책을 스냅샷으로 사용합니다. 이미 실행 중인 작업에는 소급 적용되지 않습니다. 요청·도구별 제한과 반복 횟수 제한은 별도로 유지됩니다.' }),
      !timeoutSettingsSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '시간 제한 DTO를 지원하지 않는 백엔드입니다 (UNSUPPORTED). 값을 추정하거나 기본값을 채우지 않고 읽기 전용으로 표시합니다.' }) : null,
      timeoutSettingsSupported && !timeoutRoleSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '역할별 시간 제한 지원을 확인할 수 없는 백엔드입니다. 일반·Light·Heavy 값을 표시만 하며 편집하거나 일괄 적용할 수 없습니다. 백엔드 지원 여부를 추정하지 않습니다.' }) : null,
      timeoutSettingsSupported && timeoutRoleSupported && currentRow.timeouts.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필의 시간 제한은 읽기 전용입니다. 기존 값을 보존합니다.' }) : null,
      timeoutRevisionChanged || timeoutSaveRevisionChanged ? jsx('p', { role: 'alert', style: styles.warning, children: '불러온 뒤 시간 제한 대상 프로필의 revision 또는 역할별 지원 상태가 바뀌었습니다. 덮어쓰기를 막았습니다. 상태 새로고침으로 최신 값을 다시 불러오세요.' }) : null,
      timeoutSettingsSupported && currentRow.timeouts.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: currentRow.timeouts.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: warning }, index)) }) : null,
      timeoutDraftResult.error ? jsx('p', { role: 'alert', style: styles.warning, children: timeoutDraftResult.error }) : null,
      jsx('div', { style: styles.fields, children: [
        jsx(TimeoutField, {
          id: 'delegate-total-minutes',
          label: '일반 서브 에이전트 전체 실행 시간 (분)',
          value: draft?.timeouts?.delegate_total_minutes,
          onChange: value => updateTimeout('delegate_total_minutes', value),
          disabled: disabled || timeoutRevisionChanged || !timeoutSettingsEditable,
          describedBy: 'timeout-policy-explanation'
        }),
        jsx(TimeoutField, {
          id: 'routed-light-total-minutes',
          label: '라우팅 Light 전체 실행 시간 (분)',
          value: draft?.timeouts?.routed_light_total_minutes,
          onChange: value => updateTimeout('routed_light_total_minutes', value),
          disabled: disabled || timeoutRevisionChanged || !timeoutSettingsEditable,
          describedBy: 'timeout-policy-explanation'
        }),
        jsx(TimeoutField, {
          id: 'routed-heavy-total-minutes',
          label: '라우팅 Heavy 전체 실행 시간 (분)',
          value: draft?.timeouts?.routed_heavy_total_minutes,
          onChange: value => updateTimeout('routed_heavy_total_minutes', value),
          disabled: disabled || timeoutRevisionChanged || !timeoutSettingsEditable,
          describedBy: 'timeout-policy-explanation'
        })
      ] }),
      jsx('fieldset', { id: 'timeout-targets', style: styles.fieldset, children: [
        jsx('legend', { style: styles.fieldName, children: '시간 제한 적용 대상' }),
        jsx('p', { style: styles.hint, children: '처음 열면 역할별 지원이 확인되고 편집 가능한 모든 프로필을 선택합니다. 수동 부분 선택이나 모두 해제는 프로필 전환과 새로고침 후에도 유지됩니다. 대상 선택만으로 저장되지는 않으며, 전체 저장에선 변경한 값 또는 직접 지정한 복사 의도만 적용합니다.' }),
        jsxs('div', { style: styles.selectionToolbar, children: [
          jsx('span', { style: styles.hint, children: `${selectedTimeoutTargets.length}/${eligibleTimeoutTargets(profiles).length}개 편집 가능 프로필 선택${timeoutTargetEdited ? ' · 전체 저장에 복사 의도 포함' : ''}` }),
          jsxs('div', { style: styles.actions, children: [
            jsx(Button, { id: 'timeout-target-source', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseTimeoutTargets('source'), children: '불러온 프로필만' }),
            jsx(Button, { id: 'timeout-target-all', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseTimeoutTargets('all'), children: '전체 선택' }),
            jsx(Button, { id: 'timeout-target-none', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseTimeoutTargets('none'), children: '모두 해제' })
          ] })
        ] }),
        jsx('div', { style: styles.profileList, children: profiles.map(row => {
          const dtoValid = validTimeoutsDto(row.timeouts)
          const roleSupported = splitRoutingSupported(row.timeouts)
          const eligible = roleSupported && row.timeouts.editable === true
          const detail = !dtoValid
            ? '시간 제한 정보를 확인할 수 없습니다. 기존 값을 보존합니다.'
            : !roleSupported
              ? '역할별 시간 제한 지원을 확인할 수 없어 선택할 수 없습니다.'
              : row.timeouts.editable !== true ? '시간 제한은 읽기 전용입니다. 기존 값을 보존합니다.' : undefined
          return jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, {
            id: `timeout-target-${row.name}`,
            label: row.name,
            detail,
            checked: selectedTimeoutTargets.includes(row.name),
            disabled: disabled || !eligible,
            onChange: checked => chooseTimeoutTargets('toggle', row.name, checked)
          }) }, row.name)
        }) })
      ] }),
      sectionErrors.timeouts ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.timeouts }) : null,
      jsx(Button, { id: 'timeouts-save', size: 'sm', variant: 'secondary', disabled: timeoutSaveDisabled, onClick: () => void saveSection('timeouts'), children: applyPending ? '저장 중…' : '시간 제한 저장' })
    ]
  }))

  const routingTargetGroup = jsx('fieldset', {
    id: 'routing-targets', style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: 'Heavy/Light 설정 적용 대상' }),
      jsx('p', { style: styles.hint, children: '처음에는 모든 프로필이 선택됩니다. 이 목록은 Heavy/Light 설정 복사 대상이며 라우팅 활성 프로필을 바꾸지 않습니다. 값을 수정하거나 대상을 직접 선택한 뒤 저장하면 선택한 프로필에 설정을 복사합니다. 따라가기는 각 대상의 모델을 사용하며, 폴백은 복사하지 않습니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsx('span', { style: styles.hint, children: `${selectedRoutingTargets.length}/${profileNames.length}개 선택 · 이번 저장 적용 ${routingWriteTargets.length}개` }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: 'routing-target-source', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseRoutingTargets('source'), children: '불러온 프로필만' }),
          jsx(Button, { id: 'routing-target-all', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseRoutingTargets('all'), children: '전체 선택' }),
          jsx(Button, { id: 'routing-target-none', size: 'sm', variant: 'secondary', disabled, onClick: () => chooseRoutingTargets('none'), children: '모두 해제' })
        ] })
      ] }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `routing-target-${row.name}`, label: row.name, checked: selectedRoutingTargets.includes(row.name), disabled, onChange: checked => chooseRoutingTargets('toggle', row.name, checked) }) }, row.name)) })
    ]
  })

  const routingProfileGroup = jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '라우팅 활성 프로필' }),
      jsx('p', { style: styles.hint, children: '플러그인이 설치되고 별도 사용 여부를 저장하지 않은 프로필은 기본 활성화됩니다. 기존에 저장한 OFF와 명시적인 스킬 비활성화는 보존합니다. 진단·비교가 필요할 때만 여기서 끄세요. Heavy/Light 모델 복사 대상과 활성 멤버십은 별개입니다.' }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `routing-profile-${row.name}`, label: row.name, checked: routingProfiles.includes(row.name), disabled, onChange: checked => toggleRoutingProfile(row.name, checked) }) }, row.name)) })
    ]
  })

  const routingFields = draft ? jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '1.4rem' },
    children: [

      jsxs('div', { style: styles.roleGrid, children: [
        jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '무거운 작업' }), jsx(ChoiceField, { id: 'heavy-follow', label: '대상 기준', value: activeRoutes.heavy?.follow || 'main', disabled, onChange: value => changeFollow('heavy', value), options: [{ value: 'main', label: '기본 대화 모델 따라가기' }, { value: 'custom', label: '별도 모델 지정' }] }), activeRoutes.heavy?.follow === 'custom' ? jsx(RoleRouteFields, { prefix: 'heavy-custom', route: activeRoutes.heavy.custom, disabled, onChange: (field, value) => updateRoutingRoute('heavy', field, value) }) : jsx('p', { style: styles.hint, children: '선택한 프로필의 기본 대화 모델을 사용합니다.' })] }),
        jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '가벼운 작업' }), jsx(ChoiceField, { id: 'light-follow', label: '대상 기준', value: activeRoutes.light?.follow || 'delegation', disabled, onChange: value => changeFollow('light', value), options: [{ value: 'delegation', label: '작업 위임 모델 따라가기' }, { value: 'custom', label: '별도 모델 지정' }] }), activeRoutes.light?.follow === 'custom' ? jsx(RoleRouteFields, { prefix: 'light-custom', route: activeRoutes.light.custom, disabled, onChange: (field, value) => updateRoutingRoute('light', field, value) }) : jsx('p', { style: styles.hint, children: '선택한 프로필의 작업 위임 모델을 사용합니다.' })] })
      ] }),
      jsxs('div', { id: 'legacy-routing-fallback-summary', style: { borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.45rem' }, children: [
        jsx('strong', { children: '작업 라우팅 대체 설정 · 읽기 전용' }),
        jsx('p', { style: styles.hint, children: currentRow?.fallbacks?.routing ? `${currentRow.fallbacks.routing.enabled === true ? '사용' : '미사용'} · Heavy ${readableValue(currentRow.fallbacks.routing.heavy)} · Light ${readableValue(currentRow.fallbacks.routing.light)}` : '상태를 확인할 수 없습니다.' }),
        jsx('a', { href: '#fallback-management', style: { color: 'var(--ui-accent)', fontSize: '0.84rem' }, children: '대체 실행 관리 열기' })
      ] })
    ]
  }) : null

  const fallbackTargetGroup = (scope, selected, allowEditing) => jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: `${fallbackScopeTitle(scope)} 적용 대상` }),
      jsx('p', { style: styles.hint, children: '처음 열면 편집 가능한 모든 프로필이 선택됩니다. 선택한 프로필에 이 카드 설정을 적용합니다. 체크만으로 저장되지는 않으며, 모델 적용 대상과는 별개입니다. ‘불러온 프로필만’은 위에서 설정을 불러온 프로필 하나만 남깁니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsx('span', { style: styles.hint, children: `${selected.length}/${profileNames.length}개 프로필 선택` }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: `${scope}-fallback-target-source`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'source'), children: '불러온 프로필만' }),
          jsx(Button, { id: `${scope}-fallback-target-all`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'all'), children: '전체 선택' }),
          jsx(Button, { id: `${scope}-fallback-target-none`, size: 'sm', variant: 'secondary', disabled, onClick: () => chooseFallbackTargets(scope, 'none'), children: '모두 해제' })
        ] })
      ] }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => {
        const supported = scope === 'native'
          ? row.fallbacks?.native?.editable === true
          : scope === 'delegation'
            ? validDelegationFallbackState(row.fallbacks?.delegation) && row.fallbacks.delegation.editable === true
            : Boolean(row.fallbacks?.routing && row.fallbacks.routing.editable !== false && row.fallbacks.routing.readonly !== true)
        const checked = selected.includes(row.name)
        return jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, {
          id: `${scope}-fallback-target-${row.name}`,
          label: row.name,
          detail: supported ? undefined : '설정을 확인할 수 없거나 읽기 전용입니다. 기존 값을 보존합니다.',
          checked,
          disabled: disabled || (!supported && !checked),
          onChange: value => updateFallbackTarget(scope, row.name, value)
        }) }, row.name)
      }) })
    ]
  })

  const nativeStatus = currentRow?.fallbacks?.native
  const routingFallbackStatus = currentRow?.fallbacks?.routing
  const nativeEditable = fallbackSupported && nativeStatus?.editable === true && Boolean(nativeFallbackDraft)
  const routingEditable = fallbackSupported && Boolean(routingFallbackDraft) && routingFallbackStatus?.editable !== false && routingFallbackStatus?.readonly !== true
  const nativeChainText = chain => Array.isArray(chain) && chain.length
    ? chain.map(item => `${item?.provider || '—'}/${item?.model || '—'}`).join(' → ')
    : '없음'
  const nativeFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '일반 대화 폴백' }), jsx(Badge, { variant: nativeStatus?.enabled ? 'warn' : 'muted', children: nativeStatus?.enabled ? '현재 사용' : nativeStatus ? '현재 꺼짐' : '상태 미지원' }), nativeFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
    jsx('p', { style: styles.hint, children: '메인 세션에서 나와 대화하는 모델의 예비입니다. 주 모델을 사용할 수 없을 때, Hermes의 전환 조건에 따라 현재 대화 문맥으로 다른 모델을 사용합니다. 이 설정을 저장한다고 진행 중인 응답이 즉시 바뀌지는 않습니다.' }),
    jsx('p', { id: 'native-fallback-recovery-note', role: 'note', style: styles.hint, children: '메인 모델 복귀는 Hermes가 다음 턴에 사용 제한과 쿨다운을 확인하여 결정합니다. 런타임 복원 안내는 메인 모델로 다시 요청할 준비가 되었다는 뜻이며, 정상 응답을 확인했다는 뜻은 아닙니다. 아래 예비 경로는 설정에서 확인한 목록이며 현재 대화가 사용 중인 모델 표시는 아닙니다.' }),
    jsx('p', { style: styles.warning, children: '대체 모델을 켜거나 경로를 바꾸면 사용량에 따라 추가 비용이 발생할 수 있습니다. 선택한 범위를 저장할 때만 설정에 반영됩니다.' }),
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 설정: ${fallbackBaselines.native?.enabled ? nativeChainText(fallbackBaselines.native.chain) : `꺼짐 · 보관 체인 ${nativeChainText(fallbackBaselines.native?.chain)}`}` }),
      jsx('p', { style: styles.actual, children: `편집 초안: ${nativeFallbackDraft?.enabled ? nativeChainText(nativeFallbackDraft.chain) : `꺼짐 · 보관 체인 ${nativeChainText(nativeFallbackDraft?.chain)}`}` }),
      jsx('p', { style: styles.actual, children: `실제 적용 경로: ${nativeChainText(nativeStatus?.actual_chain)}` })
    ] }),
    nativeStatus?.drift ? jsx('p', { role: 'status', style: styles.warning, children: '저장된 대화 체인과 실제 적용 체인이 다릅니다. 실제 경로를 먼저 확인하세요.' }) : null,
    Array.isArray(nativeStatus?.warnings) && nativeStatus.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: nativeStatus.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '폴백 설정을 안전하게 변경할 수 있는지 확인되지 않아 읽기 전용으로 표시합니다. 플러그인 업데이트 후 상태를 새로고침하세요.' }) : null,
    fallbackSupported && nativeStatus && nativeStatus.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '별도의 고급 옵션이나 관리자 고정 설정이 있어 이 화면에서 안전하게 변경할 수 없습니다. 기존 설정을 보호하기 위해 읽기 전용으로 표시합니다.' }) : null,
    nativeEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(CheckRow, { id: 'native-fallback-enabled', label: '메인 대화에서 대체 체인 사용', detail: '모델 목록을 채우는 것만으로는 켜지지 않습니다.', checked: nativeFallbackDraft.enabled, disabled, onChange: checked => updateFallbackDraft('native', current => ({ ...current, enabled: checked })) }),
      nativeStatus?.managed !== true ? jsx('p', { role: 'note', style: styles.warning, children: '현재 체인은 다른 설정에서 관리됩니다. 화면을 열거나 값을 편집하는 것만으로 소유권은 바뀌지 않습니다. 이 범위에 명시적으로 적용하면 플러그인 관리 설정으로 전환됩니다.' }) : null,
      jsx('div', { style: styles.presetGrid, children: NATIVE_FALLBACK_PRESETS.map(preset => jsx('button', { id: `native-fallback-preset-${preset.id}`, type: 'button', disabled, onClick: () => updateFallbackDraft('native', current => applyNativeFallbackPresetDraft(current, preset.id)), style: styles.presetCard, children: [jsx('strong', { children: preset.name }), jsx('span', { style: styles.hint, children: preset.description }), jsx('span', { style: styles.hint, children: `${preset.chain.map(item => `${item.provider}/${item.model}`).join(' → ')} · 선택한 값은 초안에만 반영되며 사용 여부는 별도로 선택합니다.` })] }, preset.id)) }),
      jsxs('div', { style: styles.fieldset, children: [
        jsx('strong', { style: styles.fieldName, children: '예비 모델 목록 · 위에서 아래 순서로 시도' }),
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
      jsx('p', { role: 'note', style: styles.hint, children: '대체 모델 제공자의 요금 정책에 따라 추가 비용이 발생할 수 있습니다. 켜기나 모델 변경은 초안에만 반영되며, 미리보기 후 직접 적용해야 저장됩니다.' }),
      fallbackTargetGroup('native', nativeFallbackTargets, nativeEditable),
      fallbackError?.scope === 'native' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'native-fallback-save', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('native'), onClick: () => void saveFallback('native'), children: applyPending ? '저장 중…' : '저장' })
    ] }) : null
  ] })

  const routingFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '작업·검증 라우팅 폴백' }), jsx(Badge, { variant: routingFallbackStatus?.enabled ? 'warn' : 'muted', children: routingFallbackStatus?.enabled ? '현재 사용' : routingFallbackStatus ? '현재 꺼짐' : '상태 미지원' }), routingFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
    jsx('p', { style: styles.hint, children: '이 플러그인이 Heavy/Light로 배정한 작업의 예비 모델입니다. 구독 사용량 소진 때문에 작업을 시작하지 못한 경우, 같은 등급의 예비 모델로 새 작업을 최대 한 번 시도합니다. 일반 대화나 네이티브 위임 폴백과는 별개입니다.' }),
    jsx('p', { id: 'routing-fallback-recovery-note', role: 'note', style: styles.hint, children: '폴백으로 시작한 시도는 작업 도중 기본 모델로 다시 전환하지 않습니다. 다음 새 작업은 설정된 기본 경로부터 시작합니다. 진행 중 작업의 경로나 결과가 불명확하다고 자동으로 다시 실행하지 않습니다.' }),
    jsx('p', { style: styles.warning, children: '실패 문구만으로는 재시도하지 않습니다. 확인된 한도 초과가 아니거나 이미 도구/부분 출력이 있으면 재시도하지 않습니다. 대체 실행에는 별도 비용이 발생할 수 있습니다.' }),
    routingFallbackStatus?.enabled && currentRow?.routing?.enabled !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필의 작업 라우팅은 현재 꺼져 있습니다. 여기서 라우팅 활성화나 프로필 멤버십은 변경하지 않습니다.' }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '폴백 설정을 안전하게 변경할 수 있는지 확인되지 않아 읽기 전용으로 표시합니다. 플러그인 업데이트 후 상태를 새로고침하세요.' }) : null,
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 설정: ${routingFallbackStatus?.enabled ? '사용' : '꺼짐'} · Heavy ${readableValue(routingFallbackStatus?.heavy)} · Light ${readableValue(routingFallbackStatus?.light)}` }),
      jsx('p', { style: styles.actual, children: `Heavy 실행 경로: ${readableValue(primaryRouteForFallback(currentRow, 'heavy'))} → ${routingFallbackStatus?.enabled ? readableValue(routingFallbackStatus.heavy) : '대체 꺼짐'}` }),
      jsx('p', { style: styles.actual, children: `Light 실행 경로: ${readableValue(primaryRouteForFallback(currentRow, 'light'))} → ${routingFallbackStatus?.enabled ? readableValue(routingFallbackStatus.light) : '대체 꺼짐'}` })
    ] }),
    routingEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(CheckRow, { id: 'routing-fallback-enabled', label: '작업·검증 라우팅의 예비 모델 사용', detail: '템플릿 선택만으로는 켜지지 않습니다.', checked: routingFallbackDraft.enabled, disabled, onChange: checked => updateFallbackDraft('routing', current => ({ ...current, enabled: checked })) }),
      jsx('div', { style: styles.presetGrid, children: ROUTING_FALLBACK_PRESETS.map(preset => jsx('button', { id: `routing-fallback-preset-${preset.id}`, type: 'button', disabled, onClick: () => updateFallbackDraft('routing', current => applyRoutingFallbackPresetDraft(current, preset.id)), style: styles.presetCard, children: [jsx('strong', { children: preset.name }), jsx('span', { style: styles.hint, children: preset.description }), jsx('span', { style: styles.hint, children: `Heavy ${readableValue(preset.heavy)} · Light ${readableValue(preset.light)} · 사용 여부는 그대로 유지` })] }, preset.id)) }),
      jsx('div', { style: styles.roleGrid, children: ['heavy', 'light'].map(role => jsxs('article', { style: styles.roleCard, children: [
        jsx('h4', { style: styles.roleTitle, children: role === 'heavy' ? 'Heavy 작업' : 'Light 작업' }),
        jsx(RoleRouteFields, { prefix: `routing-fallback-${role}`, route: routingFallbackDraft[role], disabled, onChange: (field, value) => updateFallbackDraft('routing', current => ({ ...current, [role]: { ...(current[role] || {}), [field]: value } })) }),
        jsx('p', { style: styles.actual, children: `주 경로: ${readableValue(primaryRouteForFallback(currentRow, role))}` }),
        jsx('p', { style: styles.actual, children: `대체 경로: ${readableValue(routingFallbackDraft[role])}` })
      ] }, role)) }),
      routingFallbackError ? jsx('p', { role: 'alert', style: styles.warning, children: routingFallbackError }) : null,
      jsx('p', { role: 'note', style: styles.hint, children: '예비 모델 사용에는 추가 비용이 발생할 수 있습니다. 조건을 만족할 때 같은 Heavy/Light 등급의 새 작업을 최대 한 번 시도하며, 이전 작업의 부분 답변을 이어받지 않습니다.' }),
      fallbackTargetGroup('routing', routingFallbackTargets, routingEditable),
      fallbackError?.scope === 'routing' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'routing-fallback-save', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('routing'), onClick: () => void saveFallback('routing'), children: applyPending ? '저장 중…' : '저장' })
    ] }) : jsx('div', { role: 'note', style: styles.warning, children: routingFallbackStatus ? '현재 작업 라우팅 대체 정책은 표시만 가능합니다.' : '이 프로필의 작업 라우팅 폴백 상태를 사용할 수 없습니다. 기존 설정은 변경되지 않습니다.' })
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
      jsx('h3', { style: styles.roleTitle, children: '네이티브 서브 에이전트 폴백' }),
      jsx(Badge, { variant: delegationStatusValid && delegationStatus.mode !== 'off' ? 'warn' : 'muted', children: delegationStatusValid ? delegationModeLabel(delegationStatus.mode) : '상태 미지원' }),
      delegationFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null
    ] }),
    jsx('p', { style: styles.hint, children: 'Hermes의 네이티브 위임 기능(delegate_task)으로 일을 맡긴 서브 에이전트의 예비 모델입니다. 이 플러그인의 Heavy/Light 작업·검증 라우팅과는 다른 설정입니다.' }),
    jsx('p', { style: styles.warning, children: '기본 규칙에서는 모델·제공자를 따로 지정하지 않은 서브 에이전트만 메인 대화의 예비 목록을 물려받습니다. 특정 모델을 지정한 서브 에이전트도 전환하려면 위임 전용 목록을 선택하세요. 이미 진행 중인 위임 작업을 다시 시작하거나 즉시 바꾸지는 않습니다.' }),
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.actual, children: `저장 정책: ${delegationStatusValid ? delegationModeLabel(fallbackBaselines.delegation?.mode) : '확인할 수 없음'} · 목록 ${delegationChainText(fallbackBaselines.delegation?.chain)}` }),
      jsx('p', { style: styles.actual, children: `실제 선언 정책: ${delegationStatusValid ? delegationModeLabel(delegationStatus.actual_mode) : '확인할 수 없음'} · 선언 체인 ${delegationChainText(delegationStatus?.actual_chain)}` }),
      jsx('p', { style: styles.hint, children: '여기에 표시한 목록은 위임 전용 선언입니다. 실제 상속 여부는 각 위임 작업에서 지정한 모델·제공자에 따라 달라집니다.' })
    ] }),
    delegationStatus?.drift ? jsx('p', { role: 'status', style: styles.warning, children: '저장된 위임 정책과 실제 선언 설정이 다릅니다. 적용 경로를 확인하세요.' }) : null,
    delegationStatusValid && delegationStatus.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: delegationStatus.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
    !fallbackSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '폴백 설정 정보를 확인할 수 없어 읽기 전용으로 표시합니다. 상태를 새로고침하세요.' }) : null,
    fallbackSupported && !delegationStatusValid ? jsx('p', { role: 'alert', style: styles.warning, children: '위임 폴백 설정을 확인할 수 없어 편집을 잠갔습니다. 기존 설정은 그대로 보존됩니다. 상태를 새로고침하세요.' }) : null,
    delegationStatusValid && delegationStatus.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '관리자 고정·고급 옵션·설정 읽기 실패 등으로 안전한 편집을 확인할 수 없습니다. 원본을 보존하기 위해 편집을 잠갔습니다.' }) : null,
    delegationEditable ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.85rem' }, children: [
      jsx(ChoiceField, { id: 'delegation-fallback-mode', label: '네이티브 서브 에이전트의 예비 모델 사용 방식', value: delegationFallbackDraft.mode, disabled, onChange: mode => updateFallbackDraft('delegation', current => ({ mode, chain: mode === 'custom' ? current.chain : [] })), options: DELEGATION_FALLBACK_MODES }),
      delegationFallbackDraft.mode === 'default' ? jsx('p', { style: styles.hint, children: '모델·제공자·접속 주소를 따로 지정하지 않은 서브 에이전트만 메인 대화의 예비 목록을 물려받습니다. 따로 지정한 서브 에이전트는 예비 모델 없이 실행됩니다.' }) : null,
      delegationFallbackDraft.mode === 'off' ? jsx('p', { style: styles.hint, children: '네이티브 서브 에이전트의 예비 모델을 사용하지 않습니다. 메인 대화의 예비 목록도 물려받지 않습니다.' }) : null,
      delegationFallbackDraft.mode === 'custom' ? jsxs('div', { style: styles.fieldset, children: [
        jsx('strong', { style: styles.fieldName, children: '순서가 있는 위임 전용 목록' }),
        jsx('p', { style: styles.hint, children: '네이티브 서브 에이전트용 예비 모델을 위에서 아래 순서로 시도합니다. 메인 대화나 Heavy/Light 라우팅의 예비 모델은 바꾸지 않습니다.' }),
        jsx('button', { id: 'delegation-fallback-template-non-openai', type: 'button', disabled, onClick: () => updateFallbackDraft('delegation', current => ({ ...current, chain: deepClone(NATIVE_FALLBACK_PRESETS[0].chain) })), style: styles.presetCard, children: [jsx('strong', { children: 'Non-OpenAI 예비 목록 채우기' }), jsx('span', { style: styles.hint, children: '예비 목록만 채웁니다. 미리보기 후 적용해야 저장됩니다.' }), jsx('span', { style: styles.hint, children: NATIVE_FALLBACK_PRESETS[0].chain.map(item => `${item.provider}/${item.model}`).join(' → ') })] }),
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
      jsx('p', { role: 'note', style: styles.hint, children: '서브 에이전트의 예비 모델 사용에도 추가 비용이 발생할 수 있습니다. 기본 규칙을 사용하면 메인 대화의 이후 폴백 변경이 모델을 따로 지정하지 않은 서브 에이전트에도 반영될 수 있습니다.' }),
      fallbackTargetGroup('delegation', delegationFallbackTargets, delegationEditable),
      fallbackError?.scope === 'delegation' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'delegation-fallback-save', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('delegation'), onClick: () => void saveFallback('delegation'), children: applyPending ? '저장 중…' : '저장' })
    ] }) : null
  ] })

  const fallbackManagement = section('예비 모델(폴백) 설정', '주 모델을 사용할 수 없을 때 대신 쓸 모델입니다. 메인 대화, Heavy/Light 작업·검증, 네이티브 서브 에이전트를 따로 설정합니다. 수정한 폴백은 아래 전체 미리보기·저장에도 포함됩니다.', jsxs('div', { id: 'fallback-management', style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [
    !fallbackSupported ? jsx('div', { role: 'alert', style: styles.warning, children: '폴백 편집 기능을 확인할 수 없어 기존 설정을 읽기 전용으로 표시합니다. 플러그인 업데이트 후 상태를 새로고침하세요.' }) : null,
    jsxs('div', { style: styles.fields, children: [
      jsx('p', { style: styles.hint, children: `대상 원본 프로필: ${selectedProfile || '선택 안 됨'} · 대화 대상 ${nativeFallbackTargets.length}개 · 작업·검증 대상 ${routingFallbackTargets.length}개 · 위임 대상 ${delegationFallbackTargets.length}개` }),
      jsx('p', { style: styles.hint, children: '프리셋은 초안만 채웁니다. 자동 활성화나 승인 저장을 하지 않습니다. 모델 역할 프리셋, 모델 적용 대상, 라우팅 활성 프로필과도 분리되어 있습니다.' })
    ] }),
    jsx('div', { style: styles.roleGrid, children: [nativeFallbackPanel, routingFallbackPanel, delegationFallbackPanel] })
  ] }))

  const localCombinedSummary = currentRow && draft && statusQuery.data
    ? buildCombinedPreviewBody(statusQuery.data.revision, selectedProfile, draft, selectedTargets, routingProfiles,
      fallbackDrafts, fallbackBaselines, fallbackTargets, profiles, fallbackSupported, fallbackTargetEdits, routingWriteTargets,
      {
        profile: selectedProfile,
        draft: draft.timeouts,
        baseline: timeoutBaseline,
        current: currentRow.timeouts,
        targets: selectedTimeoutTargets,
        baselinesByProfile: timeoutBaselineMap,
        currentByProfile: currentTimeoutsFromProfiles(profiles),
        copyIntent: timeoutTargetEdited
      })
    : null
  const summaryRoutingUpdates = (localCombinedSummary?.body.fallback_updates || [])
    .filter(update => Object.prototype.hasOwnProperty.call(update, 'routing_fallback'))
    .map(update => update.profile)
  const summaryProjectedErrors = localCombinedSummary && draft ? projectedRoutingFallbackErrors(profiles, {
    profile: selectedProfile,
    models: draft.models,
    routing: localCombinedSummary.body.routing,
    model_targets: localCombinedSummary.body.model_targets,
    routing_targets: localCombinedSummary.body.routing_targets
  }, summaryRoutingUpdates) : []
  const modifiedFallbackSummary = [
    { scope: 'native', label: '일반 대화', changed: nativeFallbackDraftChanged || fallbackTargetEdits.native, count: nativeFallbackTargets.length },
    { scope: 'routing', label: '작업·검증', changed: routingFallbackDraftChanged || fallbackTargetEdits.routing, count: routingFallbackTargets.length },
    { scope: 'delegation', label: '네이티브 위임', changed: delegationFallbackDraftChanged || fallbackTargetEdits.delegation, count: delegationFallbackTargets.length }
  ].filter(item => item.changed)
  const timeoutSummary = !timeoutSettingsSupported
    ? '전체 실행 시간: UNSUPPORTED · 읽기 전용'
    : !timeoutRoleSupported
      ? '역할별 시간 제한 지원 미확인 · 표시만 가능'
      : localCombinedSummary?.body.timeout_updates?.length
        ? `전체 실행 시간 변경: ${localCombinedSummary.body.timeout_updates.length}개 대상 · 일반 ${draft?.timeouts?.delegate_total_minutes}분 / Light ${draft?.timeouts?.routed_light_total_minutes}분 / Heavy ${draft?.timeouts?.routed_heavy_total_minutes}분`
        : timeoutWriteRequested
          ? '전체 실행 시간: 입력 또는 대상 revision을 확인하세요.'
          : `전체 실행 시간 변경 없음 · 시간 제한 대상 ${selectedTimeoutTargets.length}개 선택 · 불러온 ${selectedProfile} 프로필 값 일반 ${draft?.timeouts?.delegate_total_minutes}분 / Light ${draft?.timeouts?.routed_light_total_minutes}분 / Heavy ${draft?.timeouts?.routed_heavy_total_minutes}분`
  const scopeDraftErrors = [
    [nativeFallbackDraftChanged || fallbackTargetEdits.native, nativeFallbackError],
    [routingFallbackDraftChanged || fallbackTargetEdits.routing, routingFallbackError],
    [delegationFallbackDraftChanged || fallbackTargetEdits.delegation, delegationFallbackError]
  ].filter(([changed, error]) => changed && error).map(([, error]) => error)
  const summaryValidationErrors = [...new Set([...(localCombinedSummary?.errors || []), ...summaryProjectedErrors, ...scopeDraftErrors, ...(routingTargetError ? [routingTargetError] : [])])]
  const canSaveAll = Boolean(currentRow && draft && statusQuery.data && !disabled && !timeoutRevisionChanged)

  return jsxs('main', {
    style: styles.page,
    children: [
      jsxs('header', { style: styles.header, children: [jsxs('div', { children: [jsx('p', { style: { color: 'var(--ui-accent)', fontSize: '0.72rem', fontWeight: 650, letterSpacing: '0.08em', margin: '0 0 0.45rem' }, children: 'HERMES DESKTOP · 모델 제어' }), jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsx('p', { style: styles.subtitle, children: '프로필별 모델 값을 관리하고 작업 유형에 맞는 라우팅을 구성합니다. 저장을 누르면 서버 검증 후 한 번에 적용됩니다.' })] }), jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching || applyPending, onClick: () => void reloadStatus(), children: '상태 새로고침' })] }),
      jsx('div', { role: 'note', style: styles.notice, children: '새 규칙은 이후에 시작하는 세션과 허용된 작업에 적용됩니다. 이미 진행 중인 세션의 모델은 자동으로 바뀌지 않습니다.' }),
      profiles.length === 0 ? jsx('div', { role: 'status', style: styles.notice, children: '관리할 프로필이 없습니다. Hermes에서 프로필을 만든 뒤 상태를 새로고침하세요.' }) : null,
      profiles.length ? section('대상 프로필', '편집할 설정 프로필을 고릅니다. 저장 검증 중 범위가 바뀌면 적용 전 요청은 안전하게 취소됩니다.', jsxs('div', { style: styles.fields, children: [jsx(ChoiceField, { id: 'profile-select', label: '프로필', value: selectedProfile || '', disabled: disabled || !profiles.length, onChange: selectProfile, options: profiles.map(row => ({ value: row.name, label: row.name })) }), jsx('div', { style: { ...styles.field, justifyContent: 'flex-end' }, children: jsx('span', { style: styles.hint, children: `현재 Desktop 프로필: ${activeProfile || '확인 중'} · 연결: ${connectionId || 'local'} · 게이트웨이: ${gateway || 'idle'}` }) })] }), currentRow ? jsx(StatusView, { profile: currentRow }) : null) : null,
      profiles.length ? section('모델 대상', '네 역할의 값을 한 번 편집하고, 아래 별도 선택 목록에 체크한 프로필에만 모델 값을 적용합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [modelFields, modelTargetGroup] })) : null,
      profiles.length ? timeoutSettingsSection : null,
      profiles.length ? section('작업 라우팅', '작고 범위가 명확한 수정은 메인 모델이 직접 처리합니다. 일반 구현 위임은 독립적인 실작업 두 개 이상으로 나눌 가치가 있고 시작·문맥 전달·조정 비용보다 병렬 처리 이득이 클 때만 사용합니다. 작은 작업을 억지로 나누거나 테스트·빌드를 두 번째 실작업으로 세지 않습니다. 사용자의 명시적 위임 요청과 필수 Heavy·독립 검수는 예외이며 기존 안전 게이트를 유지합니다. 코딩과 복잡한 비코딩 판단 작업에 공통 정책을 적용합니다. 근거 충돌, 여러 근거를 종합하는 판단, 오류 영향이 큰 학습 자료·문항 검토, 반복된 개념적 실패가 예입니다. 단순 글쓰기·번역·요약·추출은 Heavy 대상이 아닙니다. Heavy/Light 모델 적용 대상과 라우팅 활성 프로필은 따로 선택하며, 정책을 공통 배포해도 기존 프로필 활성 멤버십은 바뀌지 않습니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { style: styles.hint, children: routingSummary }),
        jsx('p', { id: 'routing-default-note', role: 'note', style: styles.hint, children: '새로 설치한 프로필의 작업 라우팅은 기본 활성화됩니다. Heavy/Light에 동일 모델을 사용할 수 있으며, 작업마다 별도 컨텍스트로 실행합니다. 같은 모델의 별도 검수는 서로 다른 모델을 통한 검수를 뜻하지 않습니다. 모델·폴백·시간값은 임의로 변경하지 않습니다.' }),
        jsxs('details', { style: styles.cardSection, children: [
          jsxs('summary', { style: { cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.8rem', flexWrap: 'wrap' }, children: [jsx('strong', { children: '라우팅 세부 설정' }), jsx(Badge, { variant: 'muted', children: `활성 프로필 ${routingProfiles.length}개` })] }),
          jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.9rem' }, children: [routingFields, routingTargetGroup,
            jsxs('details', { id: 'routing-activation-advanced', style: styles.cardSection, children: [
              jsx('summary', { style: { cursor: 'pointer' }, children: '고급: 라우팅 일시 중지 및 프로필 사용 여부' }),
              jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.9rem' }, children: [
                jsx(CheckRow, { id: 'routing-enabled', label: '이 프로필에서 라우팅 사용', detail: '기본값은 ON입니다. 진단·비교용으로 중지할 수 있으며, 저장하기 전에는 실행 상태가 바뀌지 않습니다.', checked: activeRoutes.enabled === true, disabled, onChange: toggleRoutingEnabled }),
                routingProfileGroup
              ] })
            ] })
          ] })
        ] }),
        routingTargetError ? jsx('p', { role: 'alert', style: styles.warning, children: routingTargetError }) : null,
        sectionErrors.routing ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.routing }) : null,
        jsx(Button, { id: 'routing-save', size: 'sm', variant: 'secondary', disabled: disabled || Boolean(routingTargetError), onClick: () => void saveSection('routing'), children: applyPending ? '저장 중…' : '라우팅 설정 저장 (활성화 + Heavy/Light)' })
      ] })) : null,
      profiles.length ? fallbackManagement : null,
      revisionChanged ? jsx('div', { role: 'alert', style: styles.warning, children: '다른 화면에서 설정이 변경되어 저장을 잠갔습니다. 편집값은 아직 보존되어 있습니다. 필요한 값을 확인한 뒤 상태 새로고침으로 최신 설정을 불러와 다시 편집하세요.' }) : null,
      pageError ? jsx('div', { role: 'alert', style: styles.warning, children: pageError }) : null,
      applyOutcome ? jsxs('div', { role: 'status', 'aria-live': 'polite', style: applyOutcome.kind === 'success' ? styles.message : styles.warning, children: [jsx('strong', { children: applyOutcome.kind === 'success' ? '적용 요청이 완료되었습니다.' : applyOutcome.kind === 'partial' ? '일부 설정만 적용되었을 수 있습니다.' : '적용 결과를 확인할 수 없습니다.' }), jsx('p', { style: styles.hint, children: applyOutcome.message || (applyOutcome.kind === 'success' ? '실제 상태를 새로고침해 확인하세요. 같은 계획을 다시 적용하지 않습니다.' : '다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요.') }), applyOutcome.result ? jsx('p', { style: styles.value, children: readableValue(applyOutcome.result) }) : null] }) : null,
      needsReload ? jsx('div', { style: styles.actions, children: jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching, onClick: () => void reloadStatus(), children: statusQuery.isFetching ? '상태 확인 중…' : '실제 상태 확인 후 편집 재개' }) }) : null,
      profiles.length && !needsReload ? section('전체 설정 저장', '모델·라우팅과 수정한 폴백을 한 번에 저장합니다. 저장하면 서버가 현재 revision을 검증한 뒤 같은 계획을 적용합니다. 각 폴백은 해당 카드에서 고른 대상에만 적용됩니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [
        jsx('div', { id: 'draft-reference-summary', role: 'note', style: styles.section, children: [
          jsx('strong', { children: '현재 초안 요약 · 참고 정보' }),
          jsx('p', { style: styles.hint, children: `설정 revision ${statusQuery.data?.revision ?? '확인할 수 없음'} · 모델 대상 ${targetSummary} · 라우팅 활성 ${routingProfiles.length}개 · Heavy/Light 설정 적용 ${routingWriteTargets.length}개 (${routingWriteTargets.join(', ') || '기존 설정 유지'})` }),
          jsx('p', { style: styles.hint, children: modifiedFallbackSummary.length
            ? `수정한 폴백: ${modifiedFallbackSummary.map(item => `${item.label} ${item.count}개 대상`).join(' · ')}`
            : '수정한 폴백 없음' }),
          jsx('p', { style: styles.hint, children: timeoutSummary }),
          jsx('p', { style: styles.hint, children: '이 요약은 현재 초안에서 로컬로 계산한 참고 정보이며, 서버 검증 결과나 실제 저장 결과 또는 확정된 변경 내역을 보증하지 않습니다.' }),
          summaryValidationErrors.length ? jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '확인할 항목' }), jsx('ul', { children: summaryValidationErrors.map((error, index) => jsx('li', { children: error }, index)) })] }) : jsx('p', { role: 'status', style: styles.hint, children: '현재 입력에서 감지된 오류가 없습니다. 서버 검증은 저장 과정에서 수행됩니다.' })
        ] }),
        jsx(Button, { id: 'global-save', size: 'sm', variant: 'secondary', disabled: !canSaveAll, onClick: () => void saveAll(), children: applyPending ? '저장 중…' : '저장' })
      ] })) : null
    ]
  })
}

export default {
  id: PLUGIN_ID,
  name: '모델 및 라우팅',
  version: '0.4.5',
  defaultEnabled: false,
  register(ctx) {
    const page = {
      id: 'settings',
      title: '모델 및 라우팅',
      icon: 'settings-gear',
      render: () => jsx(RouterPage, { ctx })
    }
    if (typeof ctx.registerSettingsPage === 'function') {
      ctx.registerSettingsPage(page)
    } else if (typeof ctx.register === 'function') {
      // Public low-level settings contribution for older SDKs; never a sidebar fallback.
      ctx.register({
        id: page.id,
        area: DesktopSDK.SETTINGS_PLUGINS_AREA || 'settings.plugins',
        title: page.title,
        render: page.render,
        data: { icon: page.icon }
      })
    }
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: ROUTE_PATH },
        // Compatibility for existing bookmarks only; there is no main-sidebar entry.
        render: page.render
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'model-router.open',
          label: '모델 및 라우팅 열기',
          keywords: ['model', 'routing', 'profile', '모델', '라우팅', '프로필'],
          run: () => host.navigate(typeof DesktopSDK.pluginSettingsHref === 'function'
            ? DesktopSDK.pluginSettingsHref(PLUGIN_ID)
            : '/settings?tab=plugins&plugin=model-router')
        }
      }
    ])
  }
}
