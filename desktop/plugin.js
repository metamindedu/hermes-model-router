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
  roleCard: { minWidth: 0, boxSizing: 'border-box', padding: '1rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', overflowWrap: 'anywhere' },
  roleTitle: { margin: 0, fontSize: '0.95rem', fontWeight: 620 },
  choiceGroup: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
  choiceRow: { display: 'flex', gap: '0.65rem', alignItems: 'flex-start', color: 'var(--ui-text-primary)' },
  choiceCopy: { display: 'flex', flexDirection: 'column', gap: '0.15rem', minWidth: 0, overflowWrap: 'anywhere' },
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
  return ({ native: '일반 대화 폴백', routing: '작업·검증 라우팅 폴백', delegation: '기본 위임 방식의 예비 모델' })[scope] || '폴백'
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
    delegation_fallback: '기본 위임 방식의 예비 모델',
    'delegation.fallback_providers': '기본 위임 방식의 예비 모델 목록',
    'fallback_consent.native': '일반 대화 폴백 승인 기록',
    'fallback_consent.routing': '작업·검증 라우팅 폴백 승인 기록',
    'fallback_consent.delegation': '기본 위임 방식의 예비 모델 승인 기록'
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
      jsx(Field, { id: `${prefix}-reasoning`, label: '추론 강도', value: value.reasoning, onChange: update('reasoning'), disabled, hint: '모델이 지원하는 강도를 입력하세요. 저장할 때 확인합니다.' })
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
          jsx(SelectTrigger, { id, 'aria-label': label,
            style: { width: '100%', minWidth: 0, height: 'auto', minHeight: '2.15rem', whiteSpace: 'normal', textAlign: 'left' },
            children: jsx(SelectValue, { style: { whiteSpace: 'normal', overflowWrap: 'anywhere', minWidth: 0, textAlign: 'left' } }) }),
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

// Profile preparation is explicit native admission, never a status side effect.
const PREPARATION_STORAGE_KEY = 'profile-preparation-safety-v1'
const PREPARATION_PROFILE_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/
const PREPARATION_SHA_RE = /^[a-fA-F0-9]{40}$/
const PREPARATION_ID_RE = /^[a-f0-9]{64}$/
const PREPARATION_VERSION_RE = /^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/
const PREPARATION_REPOS = new Set(['https://github.com/metamindedu/hermes-model-router', 'https://github.com/metamindedu/hermes-model-router.git'])
let preparationStorage = null
let runningPreparation = null
let preparationGeneration = 0

export function validProfileReadiness(value) {
  return Boolean(value && value.schema === 1 &&
    ['missing', 'disabled', 'ready', 'unsupported'].includes(value.state) &&
    ['missing', 'complete', 'partial', 'unsafe'].includes(value.files) &&
    ['enabled', 'disabled', 'not_enabled', 'unknown'].includes(value.python) &&
    typeof value.base_supported === 'boolean' && typeof value.split_supported === 'boolean' &&
    typeof value.explicit_opt_out === 'boolean' && typeof value.managed_selection === 'boolean' &&
    Array.isArray(value.reason_codes) && value.reason_codes.every(code => typeof code === 'string' && /^[a-z_]+$/.test(code)) &&
    (value.version === null || (typeof value.version === 'string' && value.version.length <= 64 && PREPARATION_VERSION_RE.test(value.version))) &&
    (value.identity === null || (typeof value.identity === 'string' && PREPARATION_ID_RE.test(value.identity))))
}

export function preparationTargetEligible(row) {
  const r = row?.readiness
  return Boolean(typeof row?.name === 'string' && PREPARATION_PROFILE_RE.test(row.name) && validProfileReadiness(r) &&
    r.state === 'missing' && r.files === 'missing' && !r.managed_selection && r.identity &&
    !r.reason_codes.some(code => /unsafe|invalid|unavailable|changed|dynamic|managed|noncanonical|partial/.test(code)))
}

export function profileReadinessText(row) {
  const r = row?.readiness
  if (!validProfileReadiness(r)) return '준비 상태 확인 미지원 — 기본 플러그인 관리에서 확인'
  const labels = { missing: 'Python 플러그인 미설치', disabled: '설치됨 · Python 비활성', ready: '코드 설치 · Python 활성화 설정 완료', unsupported: '지원 상태 확인 필요 · 수동 검토' }
  let label = labels[r.state]
  if (r.version) label += ` (${r.version})`
  if (r.managed_selection) label += ' · 관리자 정책'
  if (r.explicit_opt_out) label += ' · 라우팅 OFF 유지'
  return label
}

export function profilePreparationCommands(rows, selected) {
  const names = [...new Set(Array.isArray(selected) ? selected : [])]
  return names.map(name => {
    const row = rows.find(item => item.name === name)
    if (!row || typeof name !== 'string' || !PREPARATION_PROFILE_RE.test(name) || !validProfileReadiness(row.readiness)) return null
    if (row.readiness.state === 'missing') return `hermes --profile ${name} plugins install model-router`
    if (row.readiness.state === 'disabled') return `hermes --profile ${name} plugins enable model-router`
    return null
  }).filter(Boolean)
}

function readPreparationSafety(storage = preparationStorage) {
  if (!storage || typeof storage.get !== 'function' || typeof storage.set !== 'function') return null
  try {
    const value = storage.get(PREPARATION_STORAGE_KEY, null)
    if (value === null) return { schema: 1, pending: null, blocked: [] }
    if (!value || value.schema !== 1 || !Array.isArray(value.blocked) || value.blocked.length > 256) return null
    if (value.blocked.some(item => !item || !PREPARATION_ID_RE.test(item.base) || !PREPARATION_PROFILE_RE.test(item.name))) return null
    if (value.pending !== null && (!value.pending || !PREPARATION_ID_RE.test(value.pending.base) || !Array.isArray(value.pending.started) || value.pending.started.length > 32 || value.pending.started.some(name => !PREPARATION_PROFILE_RE.test(name)))) return null
    if (value.pending && ((value.pending.phase !== undefined && !['install', 'enable', 'backend'].includes(value.pending.phase)) ||
        (value.pending.target !== undefined && !PREPARATION_PROFILE_RE.test(value.pending.target)) ||
        (value.pending.plan_id !== undefined && !/^[a-f0-9]{32}$/.test(value.pending.plan_id)))) return null
    return value
  } catch { return null }
}

export function profilePreparationLocked() {
  const safety = readPreparationSafety()
  return Boolean(runningPreparation || safety?.pending || (preparationStorage && !safety))
}

export function profilePreparationReloadBlocked(scopeKey) {
  const safety = readPreparationSafety()
  return Boolean(runningPreparation || (preparationStorage && !safety) ||
    (safety?.pending && (safety.pending.settled !== true || safety.pending.scopeKey !== scopeKey)))
}

export function finishProfilePreparationReload(context, scopeKey, storage = preparationStorage) {
  const safety = readPreparationSafety(storage)
  if (!safety) return !storage
  if (!safety.pending) return true
  if (runningPreparation || safety.pending.settled !== true ||
    safety.pending.scopeKey !== scopeKey || safety.pending.base !== context?.base_identity) return false
  safety.pending = null
  writePreparationSafety(safety, storage)
  return true
}

function writePreparationSafety(value, storage) {
  storage.set(PREPARATION_STORAGE_KEY, value)
  const readback = readPreparationSafety(storage)
  if (!readback || JSON.stringify(readback) !== JSON.stringify(value)) throw new Error('preparation_storage_unavailable')
}

function validPreparationContext(context) {
  return Boolean(context && context.schema === 1 && typeof context.base_identity === 'string' && PREPARATION_ID_RE.test(context.base_identity) &&
    typeof context.source_profile === 'string' && PREPARATION_PROFILE_RE.test(context.source_profile) && context.release &&
    context.release.catalog_name === 'model-router' && typeof context.release.ref === 'string' && PREPARATION_SHA_RE.test(context.release.ref) &&
    typeof context.release.version === 'string' && context.release.version.length <= 64 && PREPARATION_VERSION_RE.test(context.release.version))
}

function samePreparationRelease(a, b) {
  return validPreparationContext(a) && validPreparationContext(b) && a.base_identity === b.base_identity &&
    a.source_profile === b.source_profile && a.release.ref === b.release.ref && a.release.version === b.release.version
}

export function selectPreparationRoute(routes, connectionId, activeProfile) {
  if (!Array.isArray(routes)) return null
  const candidates = routes.filter(route => route && route.mode === 'local' &&
    typeof route.connectionId === 'string' && route.connectionId.trim() &&
    typeof route.targetProfile === 'string' && PREPARATION_PROFILE_RE.test(route.targetProfile) && route.profile === route.targetProfile &&
    (connectionId ? route.connectionId === connectionId && route.profile === activeProfile : route.primary === true))
  return candidates.length === 1 ? { ...candidates[0] } : null
}

// The SDK may overwrite params.profile with the descriptor's profile. Never
// retarget a source descriptor or manufacture one: use the exact fresh native
// target descriptor from the same authoritative local source. Aliases or
// absent/ambiguous routes remain manual-only.
export function selectPreparationTargetRoute(routes, sourceRoute, name) {
  if (!PREPARATION_PROFILE_RE.test(name || '') || typeof name !== 'string' || !sourceRoute || sourceRoute.mode !== 'local') return null
  const source = selectPreparationRoute(routes, sourceRoute.connectionId, sourceRoute.profile)
  if (!source || source.targetProfile !== sourceRoute.targetProfile) return null
  const candidates = routes.filter(route => route && route.mode === 'local' && route.connectionId === source.connectionId &&
    route.profile === name && route.targetProfile === name)
  return candidates.length === 1 ? { ...candidates[0] } : null
}

export async function readProfilePreparationStatus(transport, route) {
  const reply = await transport.requestProfile(route, 'cli.exec', {
    argv: ['--profile', route.targetProfile, 'model-router', 'status', '--body', '{}'],
    profile: route.targetProfile, timeout: 180
  }, 210000)
  if (!reply || reply.blocked || reply.code !== 0) throw new Error('preparation_status_unavailable')
  const frames = String(reply.output || '').split(/\r?\n/).filter(line => line.startsWith('MODEL_ROUTER_JSON:'))
  if (frames.length !== 1) throw new Error('preparation_status_unavailable')
  let data
  try { data = JSON.parse(frames[0].slice('MODEL_ROUTER_JSON:'.length)) } catch { throw new Error('preparation_status_unavailable') }
  if (!data || !Array.isArray(data.profiles) || !validPreparationContext(data.readiness_context)) throw new Error('preparation_status_unavailable')
  return data
}

// A failed/expired native write is not retried. Its target remains manual-only
// even after the user explicitly releases the original scope's safety latch.
export async function runProfilePreparation({ transport, route, snapshot, selected, scopeKey, isCurrent, confirmed, storage, onProgress = () => {} }) {
  if (runningPreparation) throw new Error('preparation_busy')
  if (!confirmed || !validPreparationContext(snapshot?.readiness_context) || !Array.isArray(snapshot.profiles)) throw new Error('preparation_not_confirmed')
  const targets = [...new Set(Array.isArray(selected) ? selected : [])]
  if (!targets.length || targets.length > 32 || targets.length !== selected.length) throw new Error('preparation_invalid_targets')
  const context = snapshot.readiness_context
  const safety = readPreparationSafety(storage)
  if (!safety || safety.pending || !route || route.mode !== 'local' || route.profile !== route.targetProfile ||
    route.targetProfile !== context.source_profile || typeof transport.profileRoutes !== 'function') throw new Error('preparation_manual_required')
  for (const name of targets) {
    const row = snapshot.profiles.find(item => item.name === name)
    if (!preparationTargetEligible(row) || safety.blocked.some(item => item.base === context.base_identity && item.name === name)) throw new Error('preparation_invalid_targets')
  }
  const outcomes = targets.map(name => ({ name, state: 'not_started' }))
  const operation = { scopeKey, cancelled: false }
  const generation = preparationGeneration
  runningPreparation = operation
  const stillCurrent = () => !operation.cancelled && generation === preparationGeneration && isCurrent()
  let uncertain = false, changed = false, dispatched = false
  try {
    if (!stillCurrent()) throw new Error('preparation_scope_changed')
    const lookup = await transport.requestProfile(route, 'plugins.catalog.lookup', { name: 'model-router', profile: route.targetProfile }, 30000)
    if (!lookup || lookup.status !== 'found' || lookup.entry?.name !== 'model-router' ||
      !PREPARATION_REPOS.has(lookup.entry.repo) || lookup.entry.sha !== context.release.ref || lookup.entry.version !== context.release.version || (lookup.entry.subdir || '') !== '') throw new Error('preparation_catalog_changed')
    for (const outcome of outcomes) {
      if (!stillCurrent()) break
      const observed = await readProfilePreparationStatus(transport, route)
      if (!stillCurrent()) break
      if (!samePreparationRelease(context, observed.readiness_context)) throw new Error('preparation_scope_changed')
      const before = snapshot.profiles.find(item => item.name === outcome.name)
      const fresh = observed.profiles.find(item => item.name === outcome.name)
      if (!preparationTargetEligible(fresh) || fresh.readiness.identity !== before.readiness.identity) {
        outcome.state = 'changed_before_start'; onProgress([...outcomes]); break
      }
      const routes = await transport.profileRoutes()
      if (!stillCurrent()) break
      const targetRoute = selectPreparationTargetRoute(routes, route, outcome.name)
      if (!targetRoute) throw new Error('preparation_target_route_unavailable')
      // No await between the last ownership/cancel check, fence and dispatch.
      // Keep the latch across remount/reload before dispatch, never after it.
      safety.pending = { base: context.base_identity, scopeKey, started: [...(safety.pending?.started || []), outcome.name] }
      writePreparationSafety(safety, storage)
      outcome.state = 'running'; dispatched = true
      let receipt = null, errorCode = null
      try {
        const request = transport.requestProfile(targetRoute, 'plugins.manage', {
          action: 'install', catalog_name: 'model-router', ref: context.release.ref,
          profile: outcome.name, force: false, enable: true
        }, 120000)
        onProgress([...outcomes])
        receipt = await request
      } catch (error) { errorCode = typeof error?.code === 'number' ? error.code : null }
      let after = null
      try { after = await readProfilePreparationStatus(transport, route) } catch { /* unknown; do not retry */ }
      const row = after?.profiles?.find(item => item.name === outcome.name)
      const owned = samePreparationRelease(context, after?.readiness_context)
      if (receipt?.ok === true && owned && validProfileReadiness(row?.readiness) && row.readiness.state === 'ready') {
        outcome.state = 'observed_ready'; changed = true
        outcome.newSessionRequired = true
      } else if (owned && preparationTargetEligible(row) && row.readiness.identity === before.readiness.identity && [-32601, 4000, 5026].includes(errorCode)) {
        outcome.state = 'manual_required'
      } else if (receipt?.ok === true && owned && validProfileReadiness(row?.readiness) && row.readiness.state === 'disabled') {
        outcome.state = 'installed_disabled'; changed = true
      } else {
        outcome.state = 'unknown'; uncertain = true
        if (!safety.blocked.some(item => item.base === context.base_identity && item.name === outcome.name)) safety.blocked.push({ base: context.base_identity, name: outcome.name })
      }
      onProgress([...outcomes])
      if (uncertain || outcome.state !== 'observed_ready' || !stillCurrent()) break
    }
    if (!uncertain) {
      if (changed && safety.pending) safety.pending.settled = true
      else safety.pending = null
      writePreparationSafety(safety, storage)
    }
    else writePreparationSafety(safety, storage)
    return { outcomes, changed, unknown: uncertain, cancelled: !stillCurrent() }
  } catch {
    if (dispatched && safety.pending) {
      uncertain = true
      for (const name of safety.pending.started) if (!safety.blocked.some(item => item.base === context.base_identity && item.name === name)) safety.blocked.push({ base: context.base_identity, name })
      try { writePreparationSafety(safety, storage) } catch { /* retain current in-memory latch */ }
    }
    return { outcomes, changed, unknown: uncertain, manualRequired: true }
  } finally {
    if (!uncertain) runningPreparation = null
  }
}

export function cancelProfilePreparation() {
  preparationGeneration += 1
  if (runningPreparation) runningPreparation.cancelled = true
}

export function acknowledgeProfilePreparation(storage, base, scopeKey, confirmed) {
  const safety = readPreparationSafety(storage)
  if (!confirmed || !safety?.pending || safety.pending.base !== base || safety.pending.scopeKey !== scopeKey) return false
  // This acknowledges manual reconciliation, not native completion. Any target
  // with an uncertain write stays excluded from automatic preparation.
  for (const name of safety.pending.started) if (!safety.blocked.some(item => item.base === base && item.name === name)) safety.blocked.push({ base, name })
  safety.pending.settled = true
  writePreparationSafety(safety, storage)
  runningPreparation = null
  return true
}

function BackendPreparationGuide({ profile }) {
  const name = PREPARATION_PROFILE_RE.test(profile || '') ? profile : null
  const commands = name ? `# 이미 설치되어 있는 경우\nhermes --profile ${name} plugins enable model-router\n\n# 미설치인 경우\nhermes --profile ${name} plugins install model-router` : null
  return jsxs('section', { id: 'backend-preparation-guide', style: styles.section, children: [
    jsx('h2', { style: styles.heading, children: 'Python 실행 플러그인 준비' }),
    jsx('p', { style: styles.hint, children: `현재 Desktop 프로필: ${name || '확인 필요'}. 화면 플러그인과 Python 실행 플러그인의 활성화는 별개입니다. 기본 플러그인 관리에서 해당 프로필의 model-router 설치·활성화를 먼저 확인하세요.` }),
    commands ? jsx('pre', { style: styles.value, children: commands }) : null,
    jsx('p', { style: styles.hint, children: '설치가 필요하면 위 명령을 직접 실행하거나 기본 플러그인 관리를 이용하세요. 기존 모델과 시간 제한은 유지됩니다. 설치 후 상태를 다시 불러오고 새 대화에서 사용하세요.' }),
    jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => host.navigate('/capabilities?tab=plugins&plugin=model-router'), children: '기본 플러그인 관리 열기' })
  ] })
}

const INITIAL_SETUP_BACKEND = 'model-router-auto'

function validInitialContext(context) {
  return Boolean(context && context.schema === 1 && PREPARATION_ID_RE.test(context.base_identity || '') &&
    typeof context.source_profile === 'string' && PREPARATION_PROFILE_RE.test(context.source_profile))
}

export function validInitialSetup(value) {
  return Boolean(value && value.schema === 1 && ['install', 'enable', 'select_backend', 'complete', 'preserved', 'manual'].includes(value.action) &&
    value.default_backend === INITIAL_SETUP_BACKEND &&
    typeof value.eligible === 'boolean' && typeof value.backend_unset === 'boolean' &&
    typeof value.digest === 'string' && (value.digest === '' || PREPARATION_ID_RE.test(value.digest)) &&
    typeof value.intent_digest === 'string' && (value.intent_digest === '' || PREPARATION_ID_RE.test(value.intent_digest)) &&
    Array.isArray(value.reason_codes) && value.reason_codes.every(code => typeof code === 'string' && /^[a-z_]+$/.test(code)))
}

export function initialSetupEligible(row, safety, base) {
  const value = row?.initial_setup
  return Boolean(typeof row?.name === 'string' && PREPARATION_PROFILE_RE.test(row.name) && validInitialSetup(value) && value.eligible === true &&
    ['install', 'enable', 'select_backend'].includes(value.action) && PREPARATION_ID_RE.test(value.digest) && PREPARATION_ID_RE.test(value.intent_digest) &&
    validProfileReadiness(row.readiness) && PREPARATION_ID_RE.test(row.readiness.identity || '') && row.readiness.explicit_opt_out === false && row.readiness.managed_selection === false &&
    safety && !safety.blocked.some(item => item.base === base && item.name === row.name))
}

async function initialSetupRequest(transport, route, operation, body = {}) {
  if (!['status', 'initial-setup-preview', 'apply'].includes(operation)) throw new Error('initial_setup_invalid_operation')
  const response = await transport.requestProfile(route, 'cli.exec', {
    argv: ['--profile', route.targetProfile, 'model-router', operation, '--body', JSON.stringify(body)],
    profile: route.targetProfile, timeout: 180
  }, 210000)
  const frames = String(response?.output || '').split(/\r?\n/).filter(line => line.startsWith('MODEL_ROUTER_JSON:'))
  if (!response || response.blocked || response.code !== 0 || frames.length !== 1) throw new Error('initial_setup_reply_unavailable')
  const data = JSON.parse(frames[0].slice('MODEL_ROUTER_JSON:'.length))
  if (!data || typeof data !== 'object' || data.error) throw new Error('initial_setup_reply_unavailable')
  if (operation === 'status' && (!Array.isArray(data.profiles) || !validInitialContext(data.readiness_context))) throw new Error('initial_setup_status_unavailable')
  return data
}

export async function runInitialSetup({ transport, snapshot, selected, scopeKey, connectionId, activeProfile, storage, isCurrent, onProgress = () => {} }) {
  const context = snapshot?.readiness_context
  const safety = readPreparationSafety(storage)
  const targets = Array.isArray(selected) ? [...selected] : []
  if (profilePreparationLocked() || !safety || safety.pending || !validInitialContext(context) ||
      readNativeSaveFence(storage, scopeKey, context?.base_identity) || !targets.length || targets.length > 32 || new Set(targets).size !== targets.length ||
      !Array.isArray(snapshot?.profiles) || typeof transport?.profileRoutes !== 'function' || typeof transport?.requestProfile !== 'function' ||
      targets.some(name => !initialSetupEligible(snapshot.profiles.find(row => row.name === name), safety, context.base_identity))) throw new Error('initial_setup_not_available')
  const generation = preparationGeneration, operation = { scopeKey, cancelled: false }
  runningPreparation = operation
  const current = () => !operation.cancelled && generation === preparationGeneration && isCurrent()
  const outcomes = targets.map(name => ({ name, state: 'not_started' }))
  let changed = false, unknown = false, issued = false, observed = snapshot
  const sameOwner = data => validInitialContext(data?.readiness_context) && data.readiness_context.base_identity === context.base_identity && data.readiness_context.source_profile === context.source_profile
  const mark = (name, phase, planId = null) => {
    safety.pending = { base: context.base_identity, scopeKey, started: [...new Set([...(safety.pending?.started || []), name])], phase, target: name, ...(planId ? { plan_id: planId } : {}) }
    writePreparationSafety(safety, storage)
  }
  try {
    if (!current()) throw new Error('initial_setup_cancelled')
    const routes = await transport.profileRoutes()
    if (!current()) throw new Error('initial_setup_cancelled')
    const source = selectPreparationRoute(routes, connectionId, activeProfile)
    if (!source || source.targetProfile !== context.source_profile) throw new Error('initial_setup_source_unavailable')
    observed = await initialSetupRequest(transport, source, 'status')
    if (!current() || !sameOwner(observed)) throw new Error('initial_setup_scope_changed')
    for (const name of targets) {
      const before = snapshot.profiles.find(row => row.name === name), fresh = observed.profiles.find(row => row.name === name)
      if (!initialSetupEligible(fresh, safety, context.base_identity) || fresh.initial_setup.digest !== before.initial_setup.digest) throw new Error('initial_setup_targets_changed')
    }
    if (targets.some(name => snapshot.profiles.find(row => row.name === name).initial_setup.action === 'install')) {
      if (!validPreparationContext(context)) throw new Error('initial_setup_catalog_unavailable')
      const lookup = await transport.requestProfile(source, 'plugins.catalog.lookup', { name: 'model-router', profile: source.targetProfile }, 30000)
      if (!current() || !lookup || lookup.status !== 'found' || lookup.entry?.name !== 'model-router' ||
          !PREPARATION_REPOS.has(lookup.entry.repo) || lookup.entry.sha !== context.release.ref || lookup.entry.version !== context.release.version || (lookup.entry.subdir || '') !== '') throw new Error('initial_setup_catalog_changed')
    }
    for (const outcome of outcomes) {
      if (!current()) break
      observed = await initialSetupRequest(transport, source, 'status')
      if (!current()) break
      if (!sameOwner(observed)) throw new Error('initial_setup_scope_changed')
      const original = snapshot.profiles.find(row => row.name === outcome.name)
      let row = observed.profiles.find(item => item.name === outcome.name)
      if (!initialSetupEligible(row, safety, context.base_identity) || row.initial_setup.digest !== original.initial_setup.digest || row.initial_setup.intent_digest !== original.initial_setup.intent_digest) throw new Error('initial_setup_target_changed')
      if (['install', 'enable'].includes(row.initial_setup.action)) {
        const freshRoutes = await transport.profileRoutes()
        if (!current()) break
        const target = selectPreparationTargetRoute(freshRoutes, source, outcome.name)
        if (!target) throw new Error('initial_setup_target_route_unavailable')
        const action = row.initial_setup.action
        const beforeDispatch = await initialSetupRequest(transport, source, 'status')
        if (!current()) break
        const dispatchRow = beforeDispatch.profiles.find(item => item.name === outcome.name)
        if (!sameOwner(beforeDispatch) || !initialSetupEligible(dispatchRow, safety, context.base_identity) ||
            dispatchRow.initial_setup.digest !== row.initial_setup.digest || dispatchRow.initial_setup.intent_digest !== original.initial_setup.intent_digest) throw new Error('initial_setup_target_changed')
        observed = beforeDispatch; row = dispatchRow
        if (action === 'install' && (!samePreparationRelease(context, observed.readiness_context) || !validPreparationContext(context))) throw new Error('initial_setup_release_changed')
        if (!current()) break
        mark(outcome.name, action)
        issued = true; outcome.state = action === 'install' ? 'installing' : 'enabling'
        const request = transport.requestProfile(target, 'plugins.manage', action === 'install'
          ? { action: 'install', catalog_name: 'model-router', ref: context.release.ref, profile: outcome.name, force: false, enable: true }
          : { action: 'toggle', name: 'model-router', enable: true, profile: outcome.name }, 120000)
        onProgress([...outcomes])
        const receipt = await request
        observed = await initialSetupRequest(transport, source, 'status')
        row = observed.profiles.find(item => item.name === outcome.name)
        if (receipt?.ok !== true || !sameOwner(observed) || !validInitialSetup(row?.initial_setup) ||
            !validProfileReadiness(row.readiness) || row.readiness.state !== 'ready' || row.readiness.version !== original.readiness.version && action === 'enable' ||
            action === 'install' && row.readiness.version !== context.release.version || row.initial_setup.intent_digest !== original.initial_setup.intent_digest ||
            !['select_backend', 'complete'].includes(row.initial_setup.action)) throw new Error('initial_setup_native_readback_unavailable')
        changed = true; outcome.state = 'prepared'
        if (!current()) break
      }
      if (row.initial_setup.action === 'select_backend') {
        if (!current()) break
        const digest = row.initial_setup.digest
        const plan = await initialSetupRequest(transport, source, 'initial-setup-preview', {
          expected_revision: observed.revision, expected_root_identity: context.base_identity,
          updates: [{ profile: outcome.name, expected_digest: digest }]
        })
        if (!current()) break
        if (typeof plan.plan_id !== 'string' || !/^[a-f0-9]{32}$/.test(plan.plan_id) || !Array.isArray(plan.changes) || plan.changes.length !== 1 ||
            plan.default_backend !== INITIAL_SETUP_BACKEND || plan.changes[0].profile !== outcome.name || plan.changes[0].field !== 'delegation.backend' || plan.changes[0].after !== INITIAL_SETUP_BACKEND) throw new Error('initial_setup_plan_invalid')
        const fresh = await initialSetupRequest(transport, source, 'status')
        if (!current()) break
        const freshRow = fresh.profiles.find(item => item.name === outcome.name)
        if (!sameOwner(fresh) || fresh.revision !== observed.revision || freshRow?.initial_setup?.digest !== digest ||
            freshRow.initial_setup.intent_digest !== original.initial_setup.intent_digest || !initialSetupEligible(freshRow, safety, context.base_identity) ||
            readNativeSaveFence(storage, scopeKey, context.base_identity)) throw new Error('initial_setup_changed_before_apply')
        mark(outcome.name, 'backend', plan.plan_id)
        issued = true; outcome.state = 'selecting_backend'
        const request = initialSetupRequest(transport, source, 'apply', { plan_id: plan.plan_id })
        onProgress([...outcomes])
        const receipt = await request
        observed = await initialSetupRequest(transport, source, 'status')
        const after = observed.profiles.find(item => item.name === outcome.name)
        if (receipt.status !== 'applied' || receipt.plan_id !== plan.plan_id || !Array.isArray(receipt.applied) || receipt.applied.length !== 1 ||
            receipt.applied[0].profile !== outcome.name || receipt.applied[0].key !== 'delegation.backend' || !Array.isArray(receipt.remaining) || receipt.remaining.length ||
            !sameOwner(observed) || !validInitialSetup(after?.initial_setup) || after.initial_setup.action !== 'complete' || after.native_delegation?.backend !== INITIAL_SETUP_BACKEND || after.readiness?.state !== 'ready') throw new Error('initial_setup_apply_unknown')
        changed = true
      }
      outcome.state = 'complete'; onProgress([...outcomes])
      if (!current()) break
    }
    if (safety.pending) safety.pending.settled = true
    writePreparationSafety(safety, storage)
    return { outcomes, changed, unknown: false, cancelled: !current(), observation: observed }
  } catch {
    unknown = issued
    if (unknown) {
      for (const name of safety.pending?.started || []) if (!safety.blocked.some(item => item.base === context.base_identity && item.name === name)) safety.blocked.push({ base: context.base_identity, name })
      const last = outcomes.find(item => ['installing', 'enabling', 'selecting_backend', 'prepared'].includes(item.state))
      if (last) last.state = 'unknown'
    }
    try { writePreparationSafety(safety, storage) } catch { /* never dispatch again after storage failure */ }
    return { outcomes, changed, unknown, manualRequired: true, observation: observed }
  } finally { if (!unknown) runningPreparation = null }
}

function InitialSetupCard({ pluginContext, data, scopeKey, settingsBusy, begin, finish, onPrepared }) {
  const [observation, setObservation] = useState(data)
  const [targets, setTargets] = useState([])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const initialized = useRef(false), mounted = useRef(true), currentScope = useRef(scopeKey), attempt = useRef(0), viewGeneration = useRef(0), busyRef = useRef(false)
  currentScope.current = scopeKey
  const renderGeneration = viewGeneration.current
  const sourceScopeNow = () => scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get())
  useEffect(() => {
    mounted.current = true; viewGeneration.current += 1; busyRef.current = false; initialized.current = false; setTargets([]); setResult(null)
    return () => { mounted.current = false; viewGeneration.current += 1; attempt.current += 1; cancelProfilePreparation() }
  }, [scopeKey])
  useEffect(() => {
    viewGeneration.current += 1
    setObservation(data)
    const safety = readPreparationSafety(pluginContext?.storage), base = data?.readiness_context?.base_identity
    if (!validInitialContext(data?.readiness_context) || !(data?.profiles || []).some(row => validInitialSetup(row.initial_setup))) return
    const eligible = (data?.profiles || []).filter(row => initialSetupEligible(row, safety, base)).map(row => row.name)
    if (!initialized.current) { initialized.current = true; setTargets(eligible) }
    else setTargets(current => current.filter(name => eligible.includes(name)))
  }, [data, scopeKey])
  const rows = observation?.profiles || [], context = observation?.readiness_context
  const safety = readPreparationSafety(pluginContext?.storage)
  const eligible = rows.filter(row => initialSetupEligible(row, safety, context?.base_identity)).map(row => row.name)
  const supported = validInitialContext(context) && rows.some(row => validInitialSetup(row.initial_setup))
  const locked = busy || settingsBusy || profilePreparationLocked() || Boolean(readNativeSaveFence(pluginContext?.storage, scopeKey, context?.base_identity))
  const refresh = async () => {
    if (locked || busyRef.current || renderGeneration !== viewGeneration.current || sourceScopeNow() !== scopeKey || !begin(true)) return
    busyRef.current = true; viewGeneration.current += 1
    const captured = scopeKey, token = ++attempt.current, generation = preparationGeneration; setBusy(true)
    try {
      const fresh = await nativeBackendCall('/status')
      if (mounted.current && currentScope.current === captured && sourceScopeNow() === captured && attempt.current === token && generation === preparationGeneration && fresh?.readiness_context?.base_identity === context?.base_identity) {
        setObservation(fresh)
        const next = (fresh.profiles || []).filter(row => initialSetupEligible(row, readPreparationSafety(pluginContext.storage), fresh.readiness_context?.base_identity)).map(row => row.name)
        setTargets(current => current.filter(name => next.includes(name)))
      }
    } catch { if (mounted.current) setResult({ manualRequired: true }) }
    finally { if (mounted.current && attempt.current === token && currentScope.current === captured) { busyRef.current = false; setBusy(false); finish() } }
  }
  const prepare = async () => {
    if (locked || busyRef.current || renderGeneration !== viewGeneration.current || sourceScopeNow() !== scopeKey || !targets.length || targets.length > 32 || !begin()) return
    busyRef.current = true; viewGeneration.current += 1
    const captured = scopeKey, generation = preparationGeneration, token = ++attempt.current
    const current = () => mounted.current && attempt.current === token && currentScope.current === captured && sourceScopeNow() === captured && generation === preparationGeneration
    setBusy(true); setResult(null)
    try {
      const reply = await runInitialSetup({ transport: host, snapshot: observation, selected: [...targets], scopeKey: captured,
        connectionId: host.state.connectionId.get(), activeProfile: host.state.profile.get(), storage: pluginContext.storage,
        isCurrent: current, onProgress: outcomes => { if (mounted.current && currentScope.current === captured) setResult({ outcomes }) } })
      if (mounted.current && (reply.changed || reply.unknown)) onPrepared(captured, reply.unknown)
      if (mounted.current && currentScope.current === captured) { setResult(reply); if (reply.observation) setObservation(reply.observation) }
    } catch { if (mounted.current && currentScope.current === captured) setResult({ manualRequired: true }) }
    finally { if (mounted.current && attempt.current === token && currentScope.current === captured) { busyRef.current = false; setBusy(false); finish() } }
  }
  const chooseTargets = (mode, name, value) => {
    if (locked || busyRef.current || renderGeneration !== viewGeneration.current || sourceScopeNow() !== scopeKey) return
    viewGeneration.current += 1
    setTargets(current => mode === 'all' ? [...eligible] : mode === 'none' ? [] : toggleName(current, name, value))
  }
  const labels = { install: '설치하고 사용 준비', enable: '설치된 플러그인 사용 준비', select_backend: '모델 / 전문 프로필 통합 방식 선택', complete: '이미 준비됨', preserved: '기존 선택 유지', manual: '직접 확인 필요', not_started: '대기', installing: '설치 중', enabling: '활성화 중', prepared: '설치 확인', selecting_backend: '작업 방식 저장 중', unknown: '결과 확인 필요 · 자동 재시도 안 함' }
  return jsxs('details', { id: 'initial-setup', open: eligible.length > 0, style: styles.section, children: [
    jsx('summary', { style: { cursor: 'pointer' }, children: jsxs('span', { style: styles.statusLine, children: [jsx('strong', { style: styles.heading, children: '처음 사용하는 프로필 준비' }), jsx(Badge, { variant: 'muted', children: `준비됨 ${rows.filter(row => row.initial_setup?.action === 'complete').length}/${rows.length}` })] }) }),
    jsx('p', { style: styles.hint, children: '아래에서 고른 프로필에 필요한 플러그인을 준비하고, 아직 작업 방식을 고르지 않았다면 ‘에이전트가 모델 / 전문 프로필 중 선택’을 기본 적용합니다. 버튼을 누르기 전에는 아무것도 바뀌지 않습니다.' }),
    jsx('p', { style: styles.hint, children: '처음에는 다른 프로필 사용을 허용하지 않아 Heavy / Light 모델 경로만 사용합니다. 전문 프로필 경로는 아래 작업 분담 카드에서 사용 대상을 직접 허용한 뒤 이용할 수 있습니다.' }),
    jsx('p', { style: styles.hint, children: '모델·로그인 정보·예비 모델·시간 제한·다른 프로필 계정 사용 권한은 바꾸지 않습니다. 이전에 꺼 두거나 다른 작업 방식을 고른 프로필도 그대로 둡니다. 새로 만든 프로필은 나중에 이 목록에서 준비할 수 있습니다.' }),
    jsxs('div', { style: styles.selectionToolbar, children: [jsx('strong', { children: `${targets.length}개 선택` }), jsxs('div', { style: styles.actions, children: [
      jsx(Button, { id: 'initial-setup-all', size: 'sm', variant: 'secondary', disabled: locked || !supported, onClick: () => chooseTargets('all'), children: '준비 가능한 프로필 전체 선택' }),
      jsx(Button, { id: 'initial-setup-none', size: 'sm', variant: 'secondary', disabled: locked, onClick: () => chooseTargets('none'), children: '모두 해제' })] })] }),
    jsx('div', { style: styles.profileList, children: rows.map(row => jsx(CheckRow, { id: `initial-profile-${row.name}`, label: row.name,
      detail: labels[row.initial_setup?.action] || '지원 여부 확인 필요', checked: targets.includes(row.name), disabled: locked || !eligible.includes(row.name),
      onChange: value => chooseTargets('toggle', row.name, value) }, row.name)) }),
    jsx('p', { id: 'initial-setup-summary', style: { ...styles.hint, overflowWrap: 'anywhere' }, children: `준비할 프로필: ${targets.join(', ') || '선택 안 됨'}` }),
    !supported ? jsx('p', { style: styles.warning, children: '이 연결에서 초기 설정을 지원하는지 확인하지 못했습니다. 플러그인을 업데이트하거나 기본 플러그인 관리에서 확인하세요.' }) : null,
    targets.length > 32 ? jsx('p', { role: 'alert', style: styles.warning, children: '한 번에 최대 32개 프로필을 준비할 수 있습니다. 적용 대상을 나눠 선택하세요.' }) : null,
    jsx(Button, { id: 'initial-setup-run', size: 'sm', disabled: locked || !supported || !targets.length || targets.length > 32,
      style: { height: 'auto', whiteSpace: 'normal', minHeight: '2.15rem' }, onClick: () => void prepare(), children: busy ? '선택한 프로필을 준비하는 중…' : `선택한 ${targets.length}개 프로필에서 사용` }),
    jsx('p', { style: styles.hint, children: '설치 화면에 나오는 출처·필요한 구성 요소·권한 안내는 그대로 적용됩니다. 도구 사용 범위를 따로 제한한 프로필이나 다른 버전·수정본은 기본 플러그인 관리에서 먼저 확인하세요. 작업 중 프로필을 삭제하거나 이름을 바꾸지 마세요. 저장한 작업 방식은 새 대화부터 적용됩니다.' }),
    jsxs('div', { style: styles.actions, children: [jsx(Button, { id: 'initial-setup-refresh', size: 'sm', variant: 'secondary', disabled: locked, onClick: () => void refresh(), children: '준비 상태 다시 확인' }),
      busy ? jsx(Button, { id: 'initial-setup-cancel', size: 'sm', variant: 'secondary', onClick: cancelProfilePreparation, children: '다음 작업부터 중단' }) : null] }),
    result?.outcomes ? jsx('ul', { 'aria-live': 'polite', children: result.outcomes.map(row => jsx('li', { children: `${row.name}: ${labels[row.state] || '확인 필요'}` }, row.name)) }) : null,
    result?.manualRequired || result?.unknown ? jsx('p', { role: 'alert', style: styles.warning, children: '준비를 완료하지 못했습니다. 같은 작업을 반복하지 말고 기본 플러그인 관리에서 결과를 확인하세요. 설치 버전이 카탈로그와 다르면 자동 설치를 보류합니다.' }) : null,
    result?.changed ? jsx('p', { role: 'status', style: styles.warning, children: '변경된 준비 상태를 확인했습니다. 다른 카드의 미저장 내용은 유지했습니다. 편집을 계속하려면 원래 연결에서 전체 상태를 다시 불러오세요.' }) : null
  ] })
}

function ProfilePreparationCard({ pluginContext, data, scopeKey, settingsBusy, begin, finish, onPrepared }) {
  const [observation, setObservation] = useState(data)
  const [targets, setTargets] = useState([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [manualConfirmed, setManualConfirmed] = useState(false)
  const currentScope = useRef(scopeKey)
  const mounted = useRef(true)
  currentScope.current = scopeKey
  useEffect(() => {
    setObservation(data); setTargets(current => current.filter(name => (data?.profiles || []).some(row => row.name === name)))
  }, [data])
  useEffect(() => {
    mounted.current = true
    setTargets([]); setConsent(false); setResult(null); setManualConfirmed(false); cancelProfilePreparation()
    return () => { mounted.current = false; cancelProfilePreparation() }
  }, [scopeKey])
  const rows = Array.isArray(observation?.profiles) ? observation.profiles : []
  const context = observation?.readiness_context
  const supported = validPreparationContext(context)
  const sourceScopeNow = () => scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get())
  const safety = readPreparationSafety(pluginContext?.storage)
  const selectedRows = rows.filter(row => targets.includes(row.name))
  const commands = profilePreparationCommands(rows, targets)
  const refresh = async () => {
    if (busy || settingsBusy || !begin(true)) return
    const captured = scopeKey
    setBusy(true)
    try {
      const response = await nativeBackendCall('/status')
      if (!mounted.current || currentScope.current !== captured || sourceScopeNow() !== captured) return
      setObservation(response)
      setTargets(current => current.filter(name => (response.profiles || []).some(row => row.name === name)))
    } catch { if (mounted.current && currentScope.current === captured) setResult({ manualRequired: true }) }
    finally { setBusy(false); finish() }
  }
  const prepare = async () => {
    if (busy || settingsBusy || !consent || !targets.length || !begin()) return
    const captured = scopeKey
    const generation = preparationGeneration
    const isAttemptCurrent = () => generation === preparationGeneration && mounted.current && currentScope.current === captured && sourceScopeNow() === captured
    setBusy(true); setResult(null)
    try {
      if (typeof host.profileRoutes !== 'function' || typeof host.requestProfile !== 'function') throw new Error('preparation_routing_unavailable')
      const routes = await host.profileRoutes()
      if (!isAttemptCurrent()) throw new Error('preparation_scope_changed')
      const route = selectPreparationRoute(routes, host.state.connectionId.get(), host.state.profile.get())
      if (!route) throw new Error('preparation_scope_changed')
      const owned = await readProfilePreparationStatus(host, route)
      if (!isAttemptCurrent()) throw new Error('preparation_scope_changed')
      if (!samePreparationRelease(context, owned.readiness_context)) throw new Error('preparation_scope_changed')
      const reply = await runProfilePreparation({ transport: host, route, snapshot: observation, selected: targets,
        scopeKey: captured, confirmed: consent, storage: pluginContext.storage,
        isCurrent: isAttemptCurrent,
        onProgress: outcomes => { if (mounted.current && currentScope.current === captured) setResult({ outcomes }) } })
      if (mounted.current && (reply.changed || reply.unknown)) onPrepared(captured, reply.unknown)
      if (mounted.current && currentScope.current === captured) { setResult(reply); setConsent(false) }
    } catch { if (mounted.current && currentScope.current === captured) setResult({ manualRequired: true }) }
    finally { setBusy(false); finish() }
  }
  const options = rows.map(row => {
    const r = row.readiness
    const blocked = safety?.blocked.some(item => item.base === context?.base_identity && item.name === row.name)
    const canSelect = validProfileReadiness(r) && ['missing', 'disabled'].includes(r.state) && !r.managed_selection && !blocked
    return jsxs('label', { style: { display: 'flex', gap: '0.5rem', alignItems: 'flex-start', padding: '0.5rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.4rem' }, children: [
      jsx(Checkbox, { id: `prepare-profile-${row.name}`, checked: targets.includes(row.name), disabled: busy || settingsBusy || !canSelect,
        onCheckedChange: checked => { setTargets(current => checked === true ? [...new Set([...current, row.name])] : current.filter(name => name !== row.name)); setConsent(false) } }),
      jsxs('span', { style: { minWidth: 0, overflowWrap: 'anywhere' }, children: [jsx('strong', { children: row.name }), jsx('small', { style: { display: 'block', color: 'var(--ui-text-tertiary)' }, children: blocked ? '이전 결과 불명 — 수동 준비만 가능' : profileReadinessText(row) })] })
    ] }, row.name)
  })
  const automatic = supported && safety && !safety.pending && selectedRows.length > 0 && selectedRows.every(preparationTargetEligible) && targets.length <= 32
  const labels = { not_started: '미시작', running: '네이티브 설치 중', observed_ready: '설치·활성화 설정 확인', changed_before_start: '상태 변경 감지 · 중단', manual_required: '네이티브 수동 검토 필요', installed_disabled: '설치됨 · 활성화 확인 필요', unknown: '결과 불명 · 자동 재시도 금지' }
  return jsxs('details', { id: 'profile-preparation', style: styles.section, children: [
    jsx('summary', { style: { cursor: 'pointer' }, children: jsxs('span', { style: { display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.5rem', maxWidth: '100%' }, children: [jsx('strong', { style: styles.heading, children: '프로필별 플러그인 준비' }), jsx(Badge, { variant: 'muted', children: `설치·활성화 설정 확인 ${rows.filter(row => validProfileReadiness(row.readiness) && row.readiness.state === 'ready').length}/${rows.length}` })] }) }),
    jsx('p', { style: styles.hint, children: '이 설정 화면은 함께 쓰지만, 기능을 사용할 프로필마다 플러그인이 설치되어 있어야 합니다. 새 프로필은 목록에서 직접 선택해 준비하세요. 상태를 확인하는 것만으로 설치되지는 않습니다.' }),
    jsx('p', { style: styles.hint, children: '준비됨은 설치와 사용 설정을 확인했다는 뜻입니다. 새로 설치했다면 새 대화에서 사용할 수 있습니다.' }),
    jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: '0.5rem' }, children: options }),
    !supported ? jsx('p', { role: 'note', style: styles.warning, children: '설치 상태를 안전하게 확인하지 못했습니다. 기존 설정은 바꾸지 않습니다. 기본 플러그인 관리에서 설치 상태를 확인하세요.' }) : null,
    targets.length ? jsx('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', userSelect: 'text' }, children: commands.join('\n') || '선택한 기존 패키지는 기본 플러그인 관리에서 검토하세요.' }) : null,
    jsx('p', { style: styles.hint, children: '한 번에 최대 32개 프로필에 새로 설치할 수 있습니다. 이미 설치되어 있거나 다른 버전이 있는 프로필은 덮어쓰지 않습니다. 원격 연결이나 구형 Hermes에서는 기본 플러그인 관리를 이용해 주세요.' }),
    jsx('p', { style: styles.hint, children: '선택한 프로필에 플러그인과 필요한 구성 요소를 설치합니다. 모델·예비 모델·시간 제한은 복사하지 않습니다. 새 설치에서는 작업 분담이 기본으로 켜지며, 이전에 꺼 둔 설정은 유지합니다. 설치 중에는 프로필 이름을 바꾸거나 삭제하지 마세요.' }),
    jsxs('label', { style: { display: 'flex', gap: '0.5rem', alignItems: 'center' }, children: [jsx(Checkbox, { id: 'prepare-consent', checked: consent, disabled: busy || settingsBusy || !automatic, onCheckedChange: value => setConsent(value === true) }), jsx('span', { children: '선택한 프로필에 플러그인과 필요한 구성 요소를 설치하고 사용하도록 설정합니다.' })] }),
    jsxs('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.6rem' }, children: [
      jsx(Button, { id: 'prepare-refresh', size: 'sm', variant: 'secondary', disabled: busy || settingsBusy, onClick: () => void refresh(), children: '준비 상태만 새로고침' }),
      jsx(Button, { id: 'prepare-run', size: 'sm', disabled: busy || settingsBusy || !automatic || !consent || profilePreparationLocked(), onClick: () => void prepare(), children: busy ? '설치 준비 중…' : '선택한 미설치 프로필 준비' }),
      busy ? jsx(Button, { id: 'prepare-cancel', size: 'sm', variant: 'secondary', onClick: cancelProfilePreparation, children: '다음 프로필부터 중단' }) : null,
      jsx(Button, { id: 'prepare-native-help', size: 'sm', variant: 'secondary', disabled: busy, onClick: () => host.navigate('/capabilities?tab=plugins&plugin=model-router'), children: '기본 플러그인 관리 열기' })
    ] }),
    jsx('p', { style: styles.hint, children: '설치 화면에 표시되는 출처와 권한 요청을 확인하세요. 진행 결과가 불분명하면 다시 설치하지 말고 기본 플러그인 관리에서 먼저 확인하세요.' }),
    result?.outcomes ? jsx('ul', { 'aria-live': 'polite', children: result.outcomes.map(item => jsx('li', { children: `${item.name}: ${labels[item.state] || '확인 필요'}` }, item.name)) }) : null,
    result?.changed ? jsx('p', { role: 'status', style: styles.warning, children: '준비 상태가 바뀌었습니다. 미저장 설정 초안은 유지했습니다. 저장 전에 전체 상태를 명시적으로 다시 불러오고 새로 준비한 적용 대상을 확인하세요. 전체 새로고침은 미저장 편집을 버립니다.' }) : null,
    result?.manualRequired ? jsx('p', { role: 'alert', style: styles.warning, children: '자동 설치를 진행할 수 없어 중단했습니다. 기본 플러그인 관리에서 확인하세요. 기존 설치를 강제로 덮어쓰지는 않습니다.' }) : null,
    safety?.pending ? jsxs('div', { role: 'alert', style: styles.warning, children: [
      jsx('p', { children: safety.pending.settled === true ? '준비 후 설정 기준을 갱신해야 합니다. 원래 연결에서 상단의 전체 상태 새로고침을 실행하세요. 미저장 편집을 버리므로 필요한 초안을 먼저 확인하세요.' : '이전 준비 작업의 종료 또는 결과가 확인되지 않았습니다. 원래 연결에서 네이티브 작업을 먼저 확인하세요. 중단은 이미 실행 중인 설치를 취소하지 않습니다.' }),
      jsxs('label', { style: { display: 'flex', gap: '0.5rem' }, children: [jsx(Checkbox, { id: 'prepare-manual-ack', checked: manualConfirmed, disabled: busy || safety.pending.settled === true, onCheckedChange: value => setManualConfirmed(value === true) }), jsx('span', { children: '기본 플러그인 관리에서 원래 작업과 대상을 수동 확인했습니다.' })] }),
      jsx(Button, { id: 'prepare-release-latch', size: 'sm', variant: 'secondary', style: { whiteSpace: 'normal', height: 'auto', minHeight: '2rem', maxWidth: '100%', textAlign: 'left' }, disabled: busy || safety.pending.settled === true || !manualConfirmed || safety.pending.scopeKey !== scopeKey || safety.pending.base !== context?.base_identity,
        onClick: () => { if (acknowledgeProfilePreparation(pluginContext.storage, context.base_identity, scopeKey, manualConfirmed)) { setResult({ manualRequired: true }); setManualConfirmed(false); finish() } }, children: '수동 확인 기록 · 결과 불명 대상은 자동 준비에서 제외' })
    ] }) : null
  ] })
}
export const NATIVE_DELEGATION_BACKENDS = freezeDeep([
  { value: 'default', label: '기본 위임 모델 사용' },
  { value: 'model-router', label: '작업에 맞춰 Heavy / Light 선택' },
  { value: 'model-router-auto', label: '에이전트가 모델 / 전문 프로필 중 선택' },
  { value: 'model-router-profiles', label: '전문 프로필에 맡기기' }
])

const nativeModelMode = backend => ['model-router', 'model-router-auto'].includes(backend)
const nativeProfileMode = backend => ['model-router-profiles', 'model-router-auto'].includes(backend)
const nativeEmptyPolicy = () => ({ heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } })
const nativeDraftPolicy = draft => draft.backend === 'model-router-auto' ? draft.autoPolicy : draft.policy

export function copyNativeDelegationDraft(dto) {
  if (dto?.schema !== 1 || dto.supported !== true || typeof dto.digest !== 'string' ||
    typeof dto.backend !== 'string' || !dto.policy || !dto.profile_routes) return null
  return { backend: dto.backend, expectedDigest: dto.digest, policy: deepClone(dto.policy),
    autoPolicy: deepClone(dto.auto_policy || nativeEmptyPolicy()), profile_routes: deepClone(dto.profile_routes), allowProfileAccess: false, descriptionEdits: {} }
}

export function nativeDelegationValidation(draft, profileNames) {
  if (!draft || !NATIVE_DELEGATION_BACKENDS.some(item => item.value === draft.backend)) return '작업을 맡기는 방식을 선택하세요.'
  for (const role of ['heavy', 'light']) {
    const policy = nativeDraftPolicy(draft)?.[role]
    if (!policy || !['off', 'custom'].includes(policy.mode) || !Array.isArray(policy.chain) ||
      (policy.mode === 'off' && policy.chain.length) || (policy.mode === 'custom' && (!policy.chain.length || policy.chain.length > 5))) return '예비 모델 목록을 확인하세요.'
    const seen = new Set()
    for (const route of policy.chain) {
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(route.provider || '') || !/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/.test(route.model || '')) return '예비 모델의 제공자와 모델 ID를 정확히 입력하세요.'
      const key = `${route.provider.toLowerCase()}\0${route.model.toLowerCase()}`
      if (seen.has(key)) return '같은 예비 경로를 중복해서 넣을 수 없습니다.'
      seen.add(key)
    }
  }
  const settings = draft.profile_routes
  if (!settings || !Array.isArray(settings.profiles) || settings.profiles.length > 32) return '프로필 허용 목록을 확인하세요.'
  const seen = new Set()
  for (const entry of settings.profiles) {
    if (!profileNames.includes(entry?.name) || seen.has(entry.name) || typeof entry.description !== 'string' || Array.from(entry.description).length > 512 || /[\u0000-\u001f\u007f]/.test(entry.description)) return '허용할 프로필이 있는지, 중복해서 골랐는지 확인하세요.'
    seen.add(entry.name)
  }
  if (settings.default !== null && !seen.has(settings.default)) return '기본 프로필은 허용 목록 안에서 선택하세요.'
  return ''
}

export function buildNativeDelegationPreviewBody(revision, profile, draft, dto, profileNames) {
  const error = nativeDelegationValidation(draft, profileNames)
  if (error) throw new Error(error)
  if (draft.expectedDigest !== dto?.digest) throw new Error('다른 곳에서 작업 분담 설정이 바뀌었습니다. 입력 내용을 확인하고 상태를 다시 불러오세요.')
  if (dto?.editable !== true || dto.supported !== true || typeof dto.digest !== 'string') throw new Error('이 프로필의 작업 분담 설정은 현재 바꿀 수 없습니다.')
  return { expected_revision: revision, updates: [{ profile, expected_digest: dto.digest,
    backend: draft.backend, policy: deepClone(nativeDraftPolicy(draft)), profile_routes: deepClone(draft.profile_routes),
    allow_additional_cost: ['heavy', 'light'].some(role => nativeDraftPolicy(draft)[role].mode === 'custom'),
    allow_profile_access: draft.allowProfileAccess === true }] }
}

export function copyNativeDelegationBaselines(profiles) {
  return Object.fromEntries((Array.isArray(profiles) ? profiles : [])
    .filter(row => typeof row?.name === 'string' && row.native_delegation?.schema === 1)
    .map(row => [row.name, deepClone(row.native_delegation)]))
}

export function nativeDelegationTargetReason(row, backend) {
  if (!row || row.native_delegation?.supported !== true || row.native_delegation.editable !== true) return '이 프로필은 설정을 변경할 수 없습니다.'
  if (backend === 'model-router-auto' && row.native_delegation.auto_supported !== true) return '설치된 플러그인이 모델 / 프로필 통합 선택을 지원하지 않습니다. 먼저 플러그인을 업데이트하세요.'
  if (nativeModelMode(backend) && row.routing?.enabled !== true) return '이 프로필의 작업 분담이 꺼져 있습니다. 아래 작업 분담 설정에서 먼저 켜세요.'
  return ''
}

export function buildNativeDelegationBatchBody(revision, origin, targets, draft, baselines, profiles) {
  const rows = Array.isArray(profiles) ? profiles : []
  const names = rows.map(row => row.name)
  if (!Array.isArray(targets) || targets.length < 1 || targets.length > 32 || uniqueProfileNames(targets).length !== targets.length) throw new Error('적용할 프로필을 1개 이상, 최대 32개까지 선택하세요.')
  if (!draft || !NATIVE_DELEGATION_BACKENDS.some(item => item.value === draft.backend)) throw new Error('작업을 맡기는 방식을 선택하세요.')
  const source = rows.find(row => row.name === origin)?.native_delegation
  if (source?.supported !== true || source.editable !== true || !baselines?.[origin] ||
      source.digest !== baselines[origin].digest || draft.expectedDigest !== baselines[origin].digest) throw new Error('불러온 프로필의 설정이 바뀌었습니다. 입력한 내용을 확인하고 상태를 다시 불러오세요.')
  return { expected_revision: revision, updates: targets.map(name => {
    const row = rows.find(item => item.name === name)
    const baseline = baselines[name]
    const issue = nativeDelegationTargetReason(row, draft.backend)
    if (issue) throw new Error(`${name}: ${issue}`)
    if (!baseline || baseline.supported !== true || baseline.editable !== true || baseline.digest !== row.native_delegation.digest) throw new Error(`${name}의 설정이 바뀌었습니다. 상태를 다시 불러온 뒤 저장하세요.`)
    // Copy visible fields only. A mode change must never overwrite hidden permissions/policies.
    const next = { ...deepClone(draft), expectedDigest: baseline.digest,
      policy: deepClone(draft.backend === 'model-router' ? draft.policy : baseline.policy),
      autoPolicy: deepClone(draft.backend === 'model-router-auto' ? draft.autoPolicy : baseline.auto_policy || nativeEmptyPolicy()),
      profile_routes: deepClone(nativeProfileMode(draft.backend) ? draft.profile_routes : baseline.profile_routes),
      allowProfileAccess: nativeProfileMode(draft.backend) && draft.allowProfileAccess === true }
    if (nativeProfileMode(draft.backend) && draft.descriptionEdits) {
      next.profile_routes.profiles = next.profile_routes.profiles.map(entry => ({ ...entry, description: draft.descriptionEdits[entry.name] === true
        ? entry.description : baseline.profile_routes.profiles.find(old => old.name === entry.name)?.description ?? '' }))
    }
    if (nativeProfileMode(draft.backend)) {
      const inheritanceIssue = profileRoleInheritanceIssue(next.profile_routes, baseline.profile_routes, row.native_delegation)
      if (inheritanceIssue) throw new Error(`${name}: ${inheritanceIssue}`)
    }
    if (draft.backend === 'model-router-auto') {
      // The default is hidden here: only explicit per-task profile choices are supported.
      next.profile_routes.default = next.profile_routes.profiles.some(item => item.name === baseline.profile_routes.default) ? baseline.profile_routes.default : null
    }
    const beforeNames = new Set(baseline.profile_routes.profiles.map(item => item.name))
    const addsAccess = next.profile_routes.profiles.some(item => !beforeNames.has(item.name)) ||
      (next.profile_routes.default !== null && next.profile_routes.default !== baseline.profile_routes.default)
    if (addsAccess && !next.allowProfileAccess) throw new Error('허용할 프로필의 계정과 기능을 확인한 뒤, 아래 사용 허용에 체크하세요.')
    return buildNativeDelegationPreviewBody(revision, name, next, row.native_delegation, names).updates[0]
  }) }
}

export function nativeDelegationSnapshotCurrent(snapshot, status) {
  if (status?.revision !== snapshot.revision) return false
  try {
    buildNativeDelegationBatchBody(snapshot.revision, snapshot.profile, snapshot.nativeTargets,
      snapshot.nativeDraft, snapshot.nativeBaselines, status.profiles)
    return true
  } catch { return false }
}

export function nativePrimaryModel(row, role) {
  const declaration = row?.routing?.[role]
  const route = declaration?.follow === 'custom' ? declaration.custom : row?.models?.[role === 'heavy' ? 'main' : 'delegation']
  return route && typeof route.model === 'string' && route.model ? route : null
}

const nativeBackendLabel = value => NATIVE_DELEGATION_BACKENDS.find(item => item.value === value)?.label || '별도 고급 설정'
const nativeSpareLabel = policy => policy?.mode === 'custom' ? `예비 모델 ${policy.chain.length}개 사용` : '다른 모델로 전환하지 않음'
const NATIVE_SAVE_FENCE_KEY = 'native-settings-save-fences-v1'

export function readNativeSaveFence(storage, scopeKey, baseIdentity = null) {
  try {
    const all = storage?.get?.(NATIVE_SAVE_FENCE_KEY, {}) || {}
    if (typeof all !== 'object' || Array.isArray(all)) throw new Error('invalid save record')
    const valid = value => value && typeof value.scopeKey === 'string' && typeof value.id === 'string' &&
      PREPARATION_ID_RE.test(value.baseIdentity || '') && Array.isArray(value.targets) &&
      value.targets.every(name => typeof name === 'string' && PREPARATION_PROFILE_RE.test(name)) && ['pending', 'settled', 'unknown'].includes(value.state)
    const value = all[scopeKey]
    if (value !== undefined) {
      if (!valid(value) || value.scopeKey !== scopeKey) throw new Error('invalid save record')
      return value
    }
    if (PREPARATION_ID_RE.test(baseIdentity || '')) {
      const foreign = Object.values(all).find(item => item?.baseIdentity === baseIdentity)
      if (foreign) {
        if (!valid(foreign)) throw new Error('invalid save record')
        return { ...foreign, foreignScope: true }
      }
    }
    return null
  } catch { return { scopeKey, id: 'unavailable', state: 'unknown', unavailable: true } }
}

function writeNativeSaveFence(storage, scopeKey, value, expectedId = null) {
  if (!storage || typeof storage.get !== 'function' || typeof storage.set !== 'function') return false
  try {
    const all = storage.get(NATIVE_SAVE_FENCE_KEY, {}) || {}
    if (expectedId !== null && all[scopeKey]?.id !== expectedId) return false
    if (value === null) delete all[scopeKey]
    else all[scopeKey] = deepClone(value)
    storage.set(NATIVE_SAVE_FENCE_KEY, all)
    const observed = readNativeSaveFence(storage, scopeKey)
    return value === null ? observed === null : sameValue(observed, value)
  } catch { return false }
}

export function profileRoleView(row, entry) {
  if (typeof entry?.description === 'string' && entry.description !== '') return { source: 'override', description: entry.description, auto: false }
  const intro = row?.role_intro
  if (intro?.schema === 1 && intro.state === 'available' && typeof intro.default_description === 'string' && intro.default_description) {
    return { source: 'profile_metadata', description: intro.default_description, auto: intro.description_auto === true }
  }
  return { source: 'unknown', description: '', auto: false }
}

export function editProfileRoleDescription(draft, name, description) {
  if (!draft?.profile_routes?.profiles.some(row => row.name === name) || typeof description !== 'string') return draft
  return { ...draft, descriptionEdits: { ...(draft.descriptionEdits || {}), [name]: true },
    profile_routes: { ...draft.profile_routes, profiles: draft.profile_routes.profiles.map(row => row.name === name ? { ...row, description } : row) } }
}

function profileRoleInheritanceIssue(next, before, dto) {
  const requestsInheritance = next.profiles.some(row => row.description === '' &&
    (!before.profiles.some(old => old.name === row.name) || before.profiles.find(old => old.name === row.name).description !== ''))
  return requestsInheritance && dto?.role_intro_inheritance?.supported !== true
    ? '이 저장 대상은 기본 소개 자동 사용을 지원하지 않습니다. 플러그인을 업데이트하거나 직접 작성한 위임용 설명을 사용하세요.' : ''
}

const ROLE_PROPOSAL_MESSAGES = {
  source_changed: '역할 자료가 바뀌었습니다. 내용을 다시 확인한 뒤 새로 요청하세요.',
  payer_changed: '연결 프로필의 모델 설정이 바뀌었습니다. 사용량 정보를 다시 확인하세요.',
  stale_result: '자료나 편집 상태가 바뀌어 이 제안을 사용할 수 없습니다.',
  no_evidence: '역할을 제안할 근거가 부족합니다. 프로필 기본 소개를 먼저 작성하거나 직접 설명하세요.',
  unsafe_target: '이 프로필의 역할 자료를 안전하게 읽을 수 없습니다.',
  owner_mismatch: '연결 또는 프로필이 바뀌었습니다. 현재 연결에서 다시 확인하세요.',
  provider_failed: '모델이 제안을 완료하지 못했습니다. 자동으로 다시 요청하지 않습니다.',
  invalid_output: '안전한 한 줄 역할 설명을 얻지 못했습니다. 자동으로 다시 요청하지 않습니다.',
  unsupported_transport: '이 연결에서는 역할 제안을 사용할 수 없습니다.',
  unsupported_sdk: '현재 Hermes에서 역할 제안을 지원하지 않습니다.'
}
const roleProposalMessage = code => ROLE_PROPOSAL_MESSAGES[code] || '역할 제안을 확인할 수 없습니다. 기존 소개와 입력한 설명은 유지했습니다.'

export function createRoleProposalController({ transport, readState, onUpdate, onUse }) {
  let serial = 0, disposed = false, pending = false, current = null
  const stateSignature = target => JSON.stringify(readState(target))
  const valid = item => !disposed && current === item && item.serial === serial && item.signature === stateSignature(item.target)
  const emit = view => { if (!disposed) onUpdate(view) }
  const cancel = () => { serial += 1; current = null; pending = false; emit(null) }
  const fail = (item, code) => { if (valid(item)) emit({ phase: 'error', target: item.target, context: item.context || null, message: roleProposalMessage(code) }) }
  const call = async (item, operation, body) => {
    if (!valid(item)) throw new Error('stale_result')
    const reply = await transport.requestProfile(item.route, 'cli.exec', {
      argv: ['--profile', item.route.targetProfile, 'model-router', operation, '--body', JSON.stringify(body)],
      profile: item.route.targetProfile, timeout: 180
    }, 210000)
    if (!valid(item)) throw new Error('stale_result')
    const frames = String(reply?.output || '').split(/\r?\n/).filter(line => line.startsWith('MODEL_ROUTER_JSON:'))
    if (!reply || reply.blocked || frames.length !== 1) throw new Error('unsupported_transport')
    let value
    try { value = JSON.parse(frames[0].slice('MODEL_ROUTER_JSON:'.length)) } catch { throw new Error('invalid_output') }
    if (value?.status === 'error' || value?.error) throw new Error(Object.hasOwn(ROLE_PROPOSAL_MESSAGES, value.code) ? value.code : 'invalid_output')
    if (reply.code !== 0) throw new Error('unsupported_transport')
    return value
  }
  const contextBody = item => ({ schema: 1, owner_profile: item.ownerProfile, base_identity: item.baseIdentity, target_profile: item.target })
  const validContext = (value, item) => value?.schema === 1 && value.owner?.profile === item.ownerProfile &&
    value.owner?.base_identity === item.baseIdentity && value.target_profile === item.target &&
    typeof value.capability?.available === 'boolean' && PREPARATION_ID_RE.test(value.source?.digest || '') &&
    value.payer?.profile === item.ownerProfile && PREPARATION_ID_RE.test(value.payer?.route_digest || '') &&
    typeof value.source?.native_description === 'string' && typeof value.source?.soul_role_excerpt === 'string' &&
    Array.isArray(value.source?.enabled_skill_names) && value.source.enabled_skill_names.every(name => typeof name === 'string')
  return {
    cancel,
    dispose() { cancel(); disposed = true },
    invalidate() { if (current && !valid(current)) cancel() },
    async open(target) {
      if (disposed || pending) return
      cancel()
      const observed = readState(target)
      const item = { serial, target, ownerProfile: observed?.ownerProfile, baseIdentity: observed?.baseIdentity, signature: stateSignature(target) }
      current = item; pending = true; emit({ phase: 'loading', target })
      try {
        if (observed?.blocked || !PREPARATION_PROFILE_RE.test(target || '') || !PREPARATION_PROFILE_RE.test(item.ownerProfile || '') || !PREPARATION_ID_RE.test(item.baseIdentity || '')) throw new Error('unsupported_transport')
        const routes = await transport.profileRoutes()
        if (!valid(item)) return
        item.route = selectPreparationRoute(routes, observed.connectionId, item.ownerProfile)
        if (!item.route || item.route.profile !== item.ownerProfile) throw new Error('unsupported_transport')
        const value = await call(item, 'role-proposal-context', contextBody(item))
        if (!validContext(value, item)) throw new Error('invalid_output')
        item.context = value; emit({ phase: 'review', target, context: value })
      } catch (error) { fail(item, error.message) }
      finally { if (current === item) pending = false }
    },
    async generate() {
      const item = current
      if (pending || !item || !valid(item) || item.context?.capability?.available !== true || item.generated) return
      pending = true; item.generated = true; emit({ phase: 'generating', target: item.target, context: item.context })
      try {
        const value = await call(item, 'role-proposal', { ...contextBody(item), source_digest: item.context.source.digest,
          route_digest: item.context.payer.route_digest, consent: { send_reviewed_sources: true, use_owner_native_policy: true } })
        const text = value?.proposal?.description
        if (value?.schema !== 1 || value.status !== 'proposed' || value.stale !== false ||
          value.owner?.profile !== item.ownerProfile || value.owner?.base_identity !== item.baseIdentity || value.target_profile !== item.target ||
          value.source_digest !== item.context.source.digest || value.route_digest !== item.context.payer.route_digest ||
          typeof text !== 'string' || !text.trim() || Array.from(text).length > 512 || /[\u0000-\u001f\u007f-\u009f]/.test(text)) throw new Error('invalid_output')
        item.result = value; emit({ phase: 'proposed', target: item.target, context: item.context, proposal: text })
      } catch (error) { fail(item, error.message) }
      finally { if (current === item) pending = false }
    },
    async use() {
      const item = current
      if (pending || !item || !valid(item) || !item.result) return
      pending = true; emit({ phase: 'checking', target: item.target, context: item.context, proposal: item.result.proposal.description })
      try {
        const fresh = await call(item, 'role-proposal-context', contextBody(item))
        if (!validContext(fresh, item) || fresh.capability.available !== true || fresh.source.digest !== item.context.source.digest || fresh.payer.route_digest !== item.context.payer.route_digest) throw new Error('stale_result')
        if (!valid(item)) return
        const target = item.target, text = item.result.proposal.description
        cancel(); onUse(target, text)
      } catch (error) { fail(item, error.message) }
      finally { if (current === item) pending = false }
    }
  }
}

function RoleProposalDialog({ view, onCancel, onGenerate, onUse }) {
  if (!view) return null
  const context = view.context, busy = ['loading', 'generating', 'checking'].includes(view.phase)
  const payer = context?.payer, sources = context?.source
  const content = [
    jsx(DesktopSDK.DialogHeader, { children: jsx(DesktopSDK.DialogTitle, { children: 'AI 역할 제안' }) }),
    jsx(DesktopSDK.DialogDescription, { children: `자료 대상: ${view.target} · 제안은 위임용 설명 초안에만 적용합니다. 프로필 기본 소개와 SOUL은 바꾸지 않습니다.` }),
    busy ? jsx('p', { role: 'status', style: styles.hint, children: view.phase === 'loading' ? '전송할 역할 자료와 사용량 정보를 확인하고 있습니다.' : view.phase === 'checking' ? '역할 자료와 편집 상태가 그대로인지 확인하고 있습니다.' : '제안을 만들고 있습니다. 취소해도 이미 시작한 요청에는 사용량이 발생할 수 있습니다.' }) : null,
    payer ? jsxs('div', { style: styles.cardSection, children: [
      jsx('strong', { children: `사용량을 사용하는 연결 프로필: ${payer.profile}` }),
      jsx('p', { style: styles.hint, children: `저장된 기본 모델: ${payer.provider} / ${payer.model}` }),
      jsx('p', { style: styles.hint, children: `기존 예비 모델: ${(payer.fallback_policy || []).map(row => `${row.provider} / ${row.model}`).join(' → ') || '없음'}` }),
      jsx('p', { style: styles.hint, children: '이 요청에는 해당 프로필의 기존 Hermes 복구 정책이 적용됩니다. 연결 실패나 인증 갱신 등으로 다시 시도하거나 예비 모델을 사용할 수 있으며, 사용량·비용이 발생할 수 있습니다. 금액은 미리 확정할 수 없습니다.' })
    ] }) : null,
    sources ? jsxs('details', { open: true, children: [
      jsx('summary', { children: '모델에 보낼 역할 자료 확인' }),
      jsx('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '13rem', overflowY: 'auto', font: 'inherit', fontSize: '0.8rem', padding: '0.75rem', border: '1px solid var(--ui-stroke-tertiary)', borderRadius: '0.5rem' }, children: JSON.stringify({ '프로필 소개': sources.native_description, 'SOUL 역할 부분': sources.soul_role_excerpt, '활성 스킬 이름': sources.enabled_skill_names }, null, 2) }),
      jsx('p', { style: styles.hint, children: '대화·기억·인증 파일·스킬 본문은 읽지 않습니다. 위 전송 자료에 민감한 내용이 보이면 취소하세요. 제안은 확인 후 사용하세요.' })
    ] }) : null,
    context?.capability?.available === false ? jsx('p', { role: 'note', style: styles.warning, children: roleProposalMessage(context.capability.reason_code) }) : null,
    view.message ? jsx('p', { role: 'alert', style: styles.warning, children: view.message }) : null,
    typeof view.proposal === 'string' ? jsxs('div', { style: styles.cardSection, children: [jsx('strong', { children: '제안 · 확인 후 사용하세요' }), jsx('p', { style: { margin: '0.5rem 0 0', overflowWrap: 'anywhere' }, children: view.proposal })] }) : null,
    jsxs(DesktopSDK.DialogFooter, { style: { flexWrap: 'wrap', gap: '0.5rem' }, children: [
      jsx(Button, { variant: 'secondary', onClick: onCancel, children: '취소' }),
      view.phase === 'review' ? jsx(Button, { disabled: context?.capability?.available !== true, onClick: onGenerate, children: '제안 만들기' }) : null,
      view.phase === 'proposed' ? jsx(Button, { onClick: onUse, children: '위임용 설명으로 사용' }) : null
    ] })
  ]
  return jsx(DesktopSDK.Dialog, { open: true, onOpenChange: open => { if (!open) onCancel() }, children: jsx(DesktopSDK.DialogContent, { style: { maxWidth: 'min(44rem, calc(100vw - 2rem))', maxHeight: '85vh', overflowY: 'auto', overflowWrap: 'anywhere' }, children: content }) })
}

function NativeDelegationCard({ dto, draft, profiles, origin, sourceRow, targets, disabled, onChange, onTargets, onSave, error, roleScope }) {
  const [roleEditors, setRoleEditors] = useState({})
  const [rolePreview, setRolePreview] = useState(null)
  const roleInputs = useRef(null)
  const roleMounted = useRef(true)
  const roleController = useRef(null)
  roleInputs.current = { dto, draft, profiles, origin, targets, disabled, roleScope, onChange }
  if (!roleController.current) roleController.current = createRoleProposalController({
    transport: { profileRoutes: () => host.profileRoutes(), requestProfile: (...args) => host.requestProfile(...args) },
    readState: target => {
      const value = roleInputs.current
      const liveProfile = host.state?.profile?.get?.() || value.roleScope?.ownerProfile
      const liveConnection = host.state?.connectionId?.get?.() || null
      const liveScope = host.state?.gateway?.get ? scopeFingerprint(liveConnection, liveProfile, host.state.gateway.get()) : value.roleScope?.scopeKey
      const entry = value.draft?.profile_routes?.profiles.find(row => row.name === target)
      return { ownerProfile: value.roleScope?.ownerProfile, connectionId: value.roleScope?.connectionId,
        scopeKey: liveScope, expectedScope: value.roleScope?.scopeKey, baseIdentity: value.roleScope?.baseIdentity,
        template: value.origin, generation: value.roleScope?.generation, draft: JSON.stringify(value.draft), targets: value.targets,
        metadataDigest: value.profiles.find(row => row.name === target)?.role_intro?.digest,
        blocked: !roleMounted.current || value.disabled || value.roleScope?.available !== true || liveProfile !== value.roleScope?.ownerProfile ||
          liveScope !== value.roleScope?.scopeKey || !entry || !nativeProfileMode(value.draft?.backend) }
    },
    onUpdate: view => { if (roleMounted.current) setRolePreview(view) },
    onUse: (name, description) => {
      if (!roleMounted.current) return
      roleInputs.current.onChange(current => editProfileRoleDescription(current, name, description))
      setRoleEditors(current => ({ ...current, [name]: true }))
    }
  })
  useEffect(() => {
    roleMounted.current = true
    const disposers = [host.state?.profile, host.state?.connectionId, host.state?.gateway]
      .filter(atom => typeof atom?.listen === 'function').map(atom => atom.listen(() => roleController.current.cancel()))
    return () => { roleMounted.current = false; for (const dispose of disposers) dispose(); roleController.current.cancel() }
  }, [])
  useEffect(() => { roleController.current.invalidate() })

  const stale = Boolean(draft && draft.expectedDigest !== dto?.digest)
  const locked = disabled || dto?.editable !== true || !draft || stale
  const selected = Array.isArray(targets) ? targets : []
  const updatePolicy = (role, updater) => onChange(current => {
    const key = current.backend === 'model-router-auto' ? 'autoPolicy' : 'policy'
    return { ...current, [key]: { ...current[key], [role]: updater(current[key][role]) } }
  })
  const profileSettings = draft?.profile_routes
  const configured = profileSettings?.profiles || []
  const setProfile = (name, checked) => onChange(current => {
    const profiles = checked ? [...current.profile_routes.profiles, { name, description: dto?.profile_routes?.profiles.find(entry => entry.name === name)?.description ?? '' }] : current.profile_routes.profiles.filter(entry => entry.name !== name)
    return { ...current, allowProfileAccess: false, profile_routes: { profiles, default: profiles.some(entry => entry.name === current.profile_routes.default) ? current.profile_routes.default : null } }
  })
  const fallbackRole = role => {
    const policy = nativeDraftPolicy(draft)[role]
    const primary = nativePrimaryModel(sourceRow, role)
    return jsxs('article', { style: { ...styles.roleCard, gap: '0.9rem' }, children: [
      jsxs('div', { style: styles.statusLine, children: [
        jsx('h3', { style: styles.roleTitle, children: role === 'heavy' ? 'Heavy · 계획과 중요한 검토' : 'Light · 구현과 반복 작업' }),
        jsx(Badge, { variant: 'muted', children: primary ? '기본 모델 설정됨' : '기본 모델 확인 필요' })
      ] }),
      jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.25rem', minWidth: 0 }, children: [
        jsx('span', { style: styles.fieldName, children: `기본 모델 · ${origin || '불러온 프로필'}` }),
        jsx('strong', { id: `native-${role}-primary-model`, style: { overflowWrap: 'anywhere', fontSize: '0.95rem' }, children: primary?.model || '설정을 불러오지 못했습니다.' }),
        primary ? jsx('span', { style: styles.hint, children: `연결된 서비스: ${primary.provider}` }) : null
      ] }),
      jsxs('div', { style: { borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '0.9rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }, children: [
        jsx(ChoiceField, { id: `native-${role}-fallback-mode`, label: '기본 모델을 쓸 수 없을 때', value: policy.mode, disabled: locked,
          options: [{ value: 'off', label: '다른 모델로 전환하지 않음' }, { value: 'custom', label: '예비 모델로 이어가기' }],
          onChange: mode => updatePolicy(role, current => ({ mode, chain: mode === 'off' ? [] : current.chain.length ? current.chain : [{ provider: '', model: '' }] })) }),
        jsx('p', { id: `native-${role}-fallback-explanation`, style: styles.hint, children: policy.mode === 'off'
          ? '기본 모델은 그대로 사용합니다. 사용할 수 없을 때 다른 모델로 바꾸지 않는다는 뜻입니다.'
          : '필요할 때 아래 순서대로 다른 모델을 시도합니다. 진행한 내용은 이어받으며, 사용량이나 비용이 늘 수 있습니다.' }),
        ...policy.chain.map((route, index) => jsxs('div', { style: { ...styles.fields, minWidth: 0 }, children: [
          jsx(Field, { id: `native-${role}-provider-${index}`, label: `예비 ${index + 1} 제공자`, value: route.provider, disabled: locked,
            onChange: value => updatePolicy(role, current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, provider: value } : item) })) }),
          jsx(Field, { id: `native-${role}-model-${index}`, label: `예비 ${index + 1} 모델 ID`, value: route.model, disabled: locked,
            onChange: value => updatePolicy(role, current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, model: value } : item) })) }),
          jsx(Button, { size: 'sm', variant: 'secondary', disabled: locked, onClick: () => updatePolicy(role, current => ({ ...current, chain: current.chain.filter((_, at) => at !== index) })), children: '이 예비 모델 삭제' })
        ] }, `${role}-${index}`)),
        policy.mode === 'custom' ? jsx(Button, { id: `native-${role}-fallback-add`, size: 'sm', variant: 'secondary', disabled: locked || policy.chain.length >= 5,
          onClick: () => updatePolicy(role, current => ({ ...current, chain: [...current.chain, { provider: '', model: '' }] })), children: '예비 모델 추가' }) : null
      ] })
    ] }, role)
  }
  return jsxs('section', { id: 'native-delegation-settings', style: styles.section, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h2', { style: styles.heading, children: '작업 분담과 예비 모델' }), jsx(Badge, { variant: 'muted', style: { maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere' }, children: `저장된 방식: ${nativeBackendLabel(dto?.backend)}` })] }),
    jsx('p', { style: styles.hint, children: '작업을 나눠 맡길 때 사용할 방식을 고릅니다. 기본 모델과, 그 모델을 사용할 수 없을 때의 예비 모델은 별도로 설정합니다.' }),
    jsx('p', { style: styles.hint, children: '저장한 방식은 새 대화부터 적용됩니다. 지금 진행 중인 대화나 작업을 중단하지 않습니다.' }),
    stale ? jsx('p', { role: 'alert', style: styles.warning, children: '다른 곳에서 설정이 바뀌었습니다. 입력한 내용은 남겨 두었으니 상태를 다시 불러온 뒤 저장하세요.' }) : null,
    jsx(RoleProposalDialog, { view: rolePreview, onCancel: () => roleController.current.cancel(), onGenerate: () => void roleController.current.generate(), onUse: () => void roleController.current.use() }),
    !draft ? jsx('p', { role: 'note', style: styles.warning, children: '이 기능의 설정을 불러오지 못했습니다. Hermes와 플러그인 설치 상태를 확인한 뒤 다시 불러오세요. 기존 값은 바꾸지 않습니다.' }) : jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [
      jsx(ChoiceField, { id: 'native-delegation-backend', label: '작업을 맡기는 방식', value: draft.backend, disabled: locked,
        options: NATIVE_DELEGATION_BACKENDS.some(item => item.value === draft.backend) ? NATIVE_DELEGATION_BACKENDS : [{ value: draft.backend, label: '현재 별도 고급 설정' }, ...NATIVE_DELEGATION_BACKENDS],
        onChange: backend => onChange(current => ({ ...current, backend, allowProfileAccess: false })) }),
      draft.backend === 'model-router-auto' ? jsx('p', { id: 'native-auto-explanation', role: 'note', style: styles.hint, children: '같은 대화에서 에이전트가 작업마다 Heavy / Light 모델 경로 또는 아래에서 허용한 전문 프로필을 고릅니다. 전문 프로필은 그 프로필의 기존 기본 모델·추론 설정을 사용하며, Heavy / Light를 다시 고르지 않습니다. 필수 Heavy 검수는 모델 경로로 수행합니다. 예비 모델 설정도 기존 모델 전용 방식과 별도로 저장됩니다.' }) : null,
      nativeModelMode(draft.backend) ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { style: styles.hint, children: '계획과 중요한 검토는 Heavy, 구현과 반복 작업은 Light 모델에 맡깁니다. 아래는 불러온 프로필에 저장된 기본 모델이며, 다른 프로필의 기본 모델은 각자의 설정을 따릅니다.' }),
        jsx('div', { style: styles.roleGrid, children: ['heavy', 'light'].map(fallbackRole) }),
        ['heavy', 'light'].some(role => nativeDraftPolicy(draft)[role].mode === 'custom') ? jsx('p', { role: 'note', style: styles.warning, children: `예비 모델을 설정하고 저장하면 선택한 ${selected.length}개 프로필에서 필요할 때 사용할 수 있습니다. 제공자의 요금제에 따라 사용량이나 비용이 늘 수 있습니다.` }) : null
      ] }) : null,
      nativeProfileMode(draft.backend) ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { role: 'note', style: styles.warning, children: '선택한 전문 프로필의 모델과 연결된 계정으로 새 작업을 맡깁니다. 해당 계정의 사용량이나 요금이 발생할 수 있습니다. 기존 대화에 이어 쓰는 기능은 아닙니다. 신뢰할 수 있는 프로필만 허용하세요.' }),
        ...profiles.map(row => {
          const entry = configured.find(item => item.name === row.name)
          const role = profileRoleView(row, entry)
          const custom = entry && (entry.description !== '' || roleEditors[row.name] === true)
          const inherited = selected.length > 0 && selected.every(name => profiles.find(item => item.name === name)?.native_delegation?.role_intro_inheritance?.supported === true)
          return jsxs('div', { style: { ...styles.cardSection, minWidth: 0 }, children: [
            jsx(CheckRow, { id: `native-profile-${row.name}`, label: row.name, detail: '이 프로필의 연결 계정과 기능 사용 허용', checked: Boolean(entry), disabled: locked, onChange: checked => setProfile(row.name, checked) }),
            jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.5rem', minWidth: 0, overflowWrap: 'anywhere' }, children: [
              jsx(Badge, { variant: 'muted', children: role.source === 'override' ? '이 위임의 설명' : role.source === 'profile_metadata' ? entry && inherited ? '프로필 기본 소개 자동 사용 · 새 대화부터' : '프로필 기본 소개 · 참고용' : '기본 소개 없음' }),
              jsx('p', { id: `native-profile-role-${row.name}`, style: styles.hint, children: role.description || '역할을 추측하지 않습니다. 필요한 경우 직접 설명하거나 AI 제안을 검토하세요.' }),
              role.auto ? jsx('p', { style: styles.hint, children: '프로필에 저장된 자동 작성 소개입니다. 내용이 맞는지 확인하세요.' }) : null,
              entry ? jsxs('div', { style: styles.actions, children: [
                !custom ? jsx(Button, { id: `native-profile-role-custom-${row.name}`, size: 'sm', variant: 'secondary', disabled: locked, onClick: () => setRoleEditors(current => ({ ...current, [row.name]: true })), children: '이 위임에서만 다르게 설명' }) : null,
                custom ? jsx(Button, { id: `native-profile-role-reset-${row.name}`, size: 'sm', variant: 'secondary', disabled: locked, onClick: () => { onChange(current => editProfileRoleDescription(current, row.name, '')); setRoleEditors(current => ({ ...current, [row.name]: false })) }, children: '기본 소개로 되돌리기' }) : null,
                jsx(Button, { id: `native-profile-role-ai-${row.name}`, size: 'sm', variant: 'secondary', disabled: locked || roleScope?.available !== true || Boolean(rolePreview), onClick: () => void roleController.current.open(row.name), children: 'AI로 역할 제안' })
              ] }) : null,
              custom ? jsx(Field, { id: `native-profile-description-${row.name}`, label: '이 위임에서 사용할 설명 · 선택 사항', value: entry.description, disabled: locked, onChange: description => onChange(current => editProfileRoleDescription(current, row.name, description)) }) : null,
              entry && !inherited && entry.description === '' ? jsx('p', { role: 'note', style: styles.hint, children: '선택한 저장 대상 중 기본 소개 자동 사용을 지원하지 않는 설치본이 있습니다. 원래 빈 값은 유지하지만, 새로 자동 사용하려면 업데이트가 필요합니다.' }) : null,
              entry && roleScope?.available !== true ? jsx('p', { style: styles.hint, children: '이 연결에서는 AI 제안을 사용할 수 없습니다. 기존 소개나 직접 작성한 설명은 사용할 수 있습니다.' }) : null
            ] })
          ] }, row.name)
        }),
        ...configured.filter(entry => !profiles.some(row => row.name === entry.name)).map(entry => jsxs('div', { style: styles.warning, children: [jsx('span', { children: `더 이상 없는 프로필: ${entry.name}` }), jsx(Button, { size: 'sm', variant: 'secondary', disabled: locked, onClick: () => setProfile(entry.name, false), children: '허용 목록에서 제거' })] }, entry.name)),
        draft.backend === 'model-router-profiles' ? jsx(ChoiceField, { id: 'native-profile-default', label: '맡길 프로필을 따로 고르지 않으면', value: profileSettings.default || '__parent__', disabled: locked,
          options: [{ value: '__parent__', label: '현재 대화의 모델 사용' }, ...configured.map(entry => ({ value: entry.name, label: entry.name }))],
          onChange: value => onChange(current => ({ ...current, allowProfileAccess: false, profile_routes: { ...current.profile_routes, default: value === '__parent__' ? null : value } })) }) : jsx('p', { style: styles.hint, children: '통합 방식에서는 맡길 프로필을 작업마다 명시적으로 선택합니다. 기존 프로필 전용 방식의 기본 대상은 유지하며, 그 대상을 허용 목록에서 제거하면 기본 선택도 해제됩니다. 허용 프로필이 없으면 모델 경로만 사용할 수 있습니다.' }),
        jsx(CheckRow, { id: 'native-profile-access-consent', label: `선택한 ${selected.length}개 저장 대상에서 위 프로필의 계정과 기능 사용을 허용합니다`, detail: '허용 대상을 새로 추가하거나 기본 프로필을 바꿀 때 필요합니다. 새로 만드는 프로필은 자동으로 허용되지 않습니다.', checked: draft.allowProfileAccess, disabled: locked,
          onChange: checked => onChange(current => ({ ...current, allowProfileAccess: checked })) })
      ] }) : null,
      jsxs('fieldset', { style: { ...styles.fieldset, borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '1rem' }, children: [
        jsx('legend', { style: styles.fieldName, children: '이 설정을 적용할 프로필' }),
        jsx('p', { style: styles.hint, children: '처음에는 불러온 프로필 하나만 선택됩니다. 여러 프로필을 골라도 저장하기 전에는 바뀌지 않습니다. 다른 카드에서 고른 대상과는 별개입니다.' }),
        jsxs('div', { style: styles.selectionToolbar, children: [
          jsx('strong', { children: `${selected.length}개 선택` }),
          jsxs('div', { style: styles.actions, children: [
            jsx(Button, { id: 'native-target-source', size: 'sm', variant: 'secondary', disabled: locked, onClick: () => onTargets('source'), children: '불러온 프로필만' }),
            jsx(Button, { id: 'native-target-all', size: 'sm', variant: 'secondary', disabled: locked, onClick: () => onTargets('all'), children: '전체 선택' }),
            jsx(Button, { id: 'native-target-none', size: 'sm', variant: 'secondary', disabled: locked, onClick: () => onTargets('none'), children: '모두 해제' })
          ] })
        ] }),
        jsx('div', { style: styles.profileList, children: profiles.map(row => {
          const reason = nativeDelegationTargetReason(row, draft.backend)
          const checked = selected.includes(row.name)
          return jsx(CheckRow, { id: `native-target-${row.name}`, label: row.name, detail: reason || undefined, checked,
            disabled: locked || (Boolean(reason) && !checked), onChange: value => onTargets('toggle', row.name, value) }, row.name)
        }) })
      ] }),
      jsxs('div', { id: 'native-save-summary', role: 'note', style: { ...styles.cardSection, display: 'flex', flexDirection: 'column', gap: '0.45rem', overflowWrap: 'anywhere' }, children: [
        jsx('strong', { children: '저장할 내용' }),
        jsx('p', { style: styles.hint, children: `적용 대상: ${selected.join(', ') || '선택 안 됨'}` }),
        jsx('p', { style: styles.hint, children: `작업 분담: ${nativeBackendLabel(draft.backend)}` }),
        nativeModelMode(draft.backend) ? jsx('p', { style: styles.hint, children: `Heavy: ${nativeSpareLabel(nativeDraftPolicy(draft).heavy)} · Light: ${nativeSpareLabel(nativeDraftPolicy(draft).light)}` }) : null,
        nativeProfileMode(draft.backend) ? jsx('p', { style: styles.hint, children: `허용할 전문 프로필: ${configured.map(row => row.name).join(', ') || '없음'} · ${draft.backend === 'model-router-auto' ? '작업마다 명시 선택 · 대상 프로필의 기본 모델·추론 설정 사용' : `기본: ${profileSettings.default || '현재 대화 모델'}. 예비 모델은 각 저장 대상의 기존 설정을 유지합니다.`}` }) : jsx('p', { style: styles.hint, children: '전문 프로필의 계정 사용 허용 목록은 각 프로필의 기존 설정을 유지합니다.' }),
        jsx('p', { style: styles.hint, children: '기본 모델·시간 제한·다른 카드의 설정은 바꾸지 않습니다.' })
      ] }),
      Array.isArray(dto?.warnings) && dto.warnings.length ? jsx('p', { style: styles.warning, children: dto.warnings.includes('profile_target_missing_remove_from_allowlist') ? '허용 목록에 더 이상 없는 프로필이 있습니다. 목록을 확인하고 제거하세요.' : '이 설정을 변경할 수 있는지 확인이 필요합니다. 설치 상태를 확인한 뒤 다시 불러오세요.' }) : null,
      error ? jsx('p', { role: 'alert', style: styles.warning, children: error }) : null,
      jsx(Button, { id: 'native-delegation-save', size: 'sm', variant: 'secondary', style: { whiteSpace: 'normal', height: 'auto', minHeight: '2.1rem' }, disabled: locked || Boolean(error) || selected.length === 0, onClick: onSave, children: `선택한 ${selected.length}개 프로필에 이 설정 저장` }),
      jsx('p', { style: styles.hint, children: '이 카드는 따로 저장합니다. 아래 함께 저장 버튼에는 포함되지 않습니다.' })
    ] })
  ] })
}

export async function nativeBackendCall(path, options = {}) {
  const operation = { '/status': 'status', '/preview': 'preview', '/fallback-preview': 'fallback-preview', '/delegation-preview': 'delegation-preview', '/initial-setup-preview': 'initial-setup-preview', '/apply': 'apply' }[path]
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
  const [nativeDelegationDraft, setNativeDelegationDraft] = useState(null)
  const [nativeDelegationBaselines, setNativeDelegationBaselines] = useState({})
  const [nativeDelegationTargets, setNativeDelegationTargets] = useState([])
  const nativeTargetsManualRef = useRef(false)
  const [nativeRecoveryConfirmed, setNativeRecoveryConfirmed] = useState(false)
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
  const [setupPending, setSetupPending] = useState(false)
  const setupPendingRef = useRef(false)
  const [reviewed, setReviewed] = useState(false)
  const [pageError, setPageError] = useState('')
  const [applyOutcome, setApplyOutcome] = useState(null)
  const [needsReload, setNeedsReload] = useState(false)
  const generationRef = useRef(0)
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false; generationRef.current += 1 }
  }, [])
  const applyPendingRef = useRef(false)
  const refreshPendingRef = useRef(false)
  const needsReloadRef = useRef(false)
  const applyScopeRef = useRef(null)
  const applyPhaseRef = useRef(null)
  const selectedProfileRef = useRef(null)
  const timeoutTargetsManualRef = useRef(false)
  selectedProfileRef.current = selectedProfile
  const beginProfilePreparation = (readOnly = false) => {
    if (setupPendingRef.current || applyPendingRef.current || refreshPendingRef.current ||
      (!readOnly && (needsReloadRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity)))) return false
    setupPendingRef.current = true
    setSetupPending(true)
    return true
  }
  const finishProfilePreparation = () => { setupPendingRef.current = false; setSetupPending(false) }
  const profilePreparationChanged = (capturedScope, unknown) => {
    needsReloadRef.current = true
    needsReloadRef.scopeKey = capturedScope
    setNeedsReload(true)
    setApplyOutcome({ kind: unknown ? 'unknown' : 'prepared', message: '플러그인 준비로 실행 상태가 바뀌었거나 결과 확인이 필요합니다. 미저장 초안은 유지했습니다. 원래 연결에서 전체 상태를 명시적으로 새로고침한 뒤 적용 대상을 확인하세요. 전체 새로고침은 미저장 편집을 버립니다.' })
    setPreview(null)
    setFallbackPreview(null)
  }

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
    setNativeDelegationDraft(null)
    setNativeDelegationBaselines({})
    setNativeDelegationTargets([])
    nativeTargetsManualRef.current = false
    setNativeRecoveryConfirmed(false)
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
    setNativeDelegationDraft(copyNativeDelegationDraft(row.native_delegation))
    setNativeDelegationBaselines(copyNativeDelegationBaselines(profiles))
    setNativeDelegationTargets([row.name])
    nativeTargetsManualRef.current = false
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
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setDraft(current => current ? updater(current) : current)
  }
  const currentRow = profiles.find(item => item.name === selectedProfile) || null
  const profileNames = profiles.map(item => item.name)
  const nativeFence = readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity)
  const nativeStorageAvailable = typeof pluginContext.storage?.get === 'function' && typeof pluginContext.storage?.set === 'function'
  let nativeDelegationError = ''
  if (nativeDelegationDraft && selectedProfile) {
    try { buildNativeDelegationBatchBody(draftRevision, selectedProfile, nativeDelegationTargets, nativeDelegationDraft, nativeDelegationBaselines, profiles) }
    catch (error) { nativeDelegationError = error.message }
  }
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
  const delegationFallbackError = delegationFallbackDraft ? delegationFallbackValidation(delegationFallbackDraft) : '기본 위임 방식의 예비 모델 설정을 확인할 수 없습니다. 상태를 새로고침하세요.'
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
  const disabled = setupPending || profilePreparationLocked() || Boolean(nativeFence) || applyPending || needsReload || revisionChanged || statusQuery.isFetching || !selectedProfile || !draft
  const timeoutSaveValuesValid = Boolean(timeoutPayloadValues(draft?.timeouts, timeoutBaseline))
  const timeoutSaveDisabled = disabled || !timeoutSettingsEditable || !selectedTimeoutTargets.length ||
    timeoutSourceRevisionChanged || timeoutTargetsRevisionChanged || !timeoutSaveValuesValid
  const validPreview = previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile)
  const renderGeneration = generationRef.current
  const activeRoutes = draft?.routing || {}
  const routingSummary = `무거운 작업: ${activeRoutes.heavy?.follow === 'custom' ? '별도 모델' : '기본 모델'} · 가벼운 작업: ${activeRoutes.light?.follow === 'custom' ? '별도 모델' : '위임 모델'}`

  const selectProfile = name => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
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
    setNativeDelegationDraft(copyNativeDelegationDraft(nativeDelegationBaselines[name]))
    if (!nativeTargetsManualRef.current) setNativeDelegationTargets([name])
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
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(current => toggleName(current, name, checked))
  }

  const selectAllTargets = () => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(selectAllModelTargets(profileNames))
  }

  const selectNoTargets = () => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setModelTargets(selectNoModelTargets())
  }

  const chooseTimeoutTargets = (mode, name = null, checked = false) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
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
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    invalidatePlan()
    const next = mode === 'all' ? [...profileNames] : mode === 'none' ? []
      : mode === 'source' ? [selectedProfile] : toggleName(selectedRoutingTargets, name, checked)
    setRoutingTargets(next)
    setRoutingTargetEdited(next.length > 0)
  }

  const toggleRoutingProfile = (name, checked) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
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
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setDraft(current => current ? { ...current, routing: { ...current.routing, enabled: checked } } : current)
    if (selectedProfile) setRoutingProfiles(current => toggleName(current, selectedProfile, checked))
  }

  const updateFallbackDraft = (scope, updater) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    invalidatePlan()
    setFallbackDrafts(current => ({
      ...current,
      [scope]: current[scope] ? updater(current[scope]) : current[scope]
    }))
  }

  const updateFallbackTarget = (scope, name, checked) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const selected = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    invalidatePlan()
    setFallbackTargets(current => ({ ...current, [scope]: toggleName(selected, name, checked) }))
    setFallbackTargetEdits(current => ({ ...current, [scope]: true }))
  }

  const chooseFallbackTargets = (scope, mode) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
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
    if (!fallbackSupported || disabled || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || fallbackPreviewPending || !selectedProfile || !statusQuery.data) return false
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

  const isSaveCurrent = (snapshot, token) => mountedRef.current && generationRef.current === token &&
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

  const runSave = async ({ operation, scope = null, snapshot, prepare, beforeApply = null, nativeWrite = false }) => {
    if (!snapshot || setupPendingRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) || applyPendingRef.current || needsReloadRef.current) return
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
    let nativeFenceRecord = null
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
      if (beforeApply && !beforeApply()) throw new Error('선택한 프로필의 설정이 저장 준비 중에 바뀌었습니다. 상태를 다시 불러온 뒤 저장하세요.')
      if (nativeWrite) {
        // Validate the source even when it is not a write target; target CAS alone
        // cannot detect an excluded source changing behind the query cache.
        const freshStatus = await ctx.rest('/status')
        if (!isSaveCurrent(snapshot, token)) return
        if (freshStatus?.readiness_context?.base_identity !== snapshot.nativeBaseIdentity ||
            !nativeDelegationSnapshotCurrent(snapshot, freshStatus) || (beforeApply && !beforeApply())) {
          throw new Error('원본 또는 선택한 프로필의 설정이 바뀌었습니다. 상태를 다시 불러온 뒤 저장하세요.')
        }
        if (!PREPARATION_ID_RE.test(snapshot.nativeBaseIdentity || '')) throw new Error('현재 연결을 확인할 수 없습니다. 상태를 다시 불러오세요.')
        if (readNativeSaveFence(pluginContext.storage, snapshot.scopeKey, snapshot.nativeBaseIdentity)) throw new Error('이전 저장 결과를 먼저 확인하세요.')
        nativeFenceRecord = { id: planId, scopeKey: snapshot.scopeKey,
          baseIdentity: snapshot.nativeBaseIdentity, targets: [...snapshot.nativeTargets], state: 'pending' }
        if (!writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey, nativeFenceRecord)) throw new Error('저장 진행 상태를 기록할 수 없습니다. 설정은 적용하지 않았습니다.')
      }
      applyStarted = true
      applyPhaseRef.current = 'apply'
      const receipt = await ctx.rest('/apply', { method: 'POST', body: { plan_id: planId }, timeoutMs: 180000 })
      if (nativeFenceRecord) writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey,
        { ...nativeFenceRecord, state: isPartialReceipt(receipt) || ['applied', 'no_change'].includes(receipt?.status) ? 'settled' : 'unknown' }, nativeFenceRecord.id)
      if (!isSaveCurrent(snapshot, token)) {
        markApplyUnknown(snapshot, '저장 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 저장하지 마세요. 원래 연결·프로필로 돌아가 실제 상태를 새로고침하세요.')
        return
      }
      recordApplyReceipt(snapshot, receipt)
    } catch (error) {
      if (applyStarted) {
        if (nativeFenceRecord) writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey, { ...nativeFenceRecord, state: 'unknown' }, nativeFenceRecord.id)
        markApplyUnknown(snapshot, error?.message || '저장 결과를 확인할 수 없습니다. 다시 저장하지 말고 실제 상태를 새로고침하세요.')
      } else if (isSaveCurrent(snapshot, token)) {
        const message = `저장되지 않았습니다. ${error?.message || '설정 검증에 실패했습니다.'}`
        if (operation === '/fallback-preview') setFallbackError({ scope, message })
        else if (scope) setSectionErrors(current => ({ ...current, [scope]: message }))
        else setPageError(message)
      }
    } finally {
      if (nativeFenceRecord && !applyStarted) writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey, null, nativeFenceRecord.id)
      if (applyStarted && !isSaveCurrent(snapshot, token)) {
        markApplyUnknown(snapshot, '저장 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 저장하지 마세요. 원래 연결·프로필로 돌아가 실제 상태를 새로고침하세요.')
      }
      releaseSaveLock(token)
    }
  }

  const saveFallback = scope => {
    if (renderGeneration !== generationRef.current || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || !canPreviewFallback(scope)) return
    const snapshot = captureSaveSnapshot()
    const targetNames = scope === 'native' ? [...nativeFallbackTargets] : scope === 'routing' ? [...routingFallbackTargets] : [...delegationFallbackTargets]
    const value = deepClone(scope === 'native' ? nativeFallbackDraft : scope === 'routing' ? routingFallbackDraft : delegationFallbackDraft)
    return runSave({
      operation: '/fallback-preview', scope, snapshot,
      prepare: () => ({ body: buildFallbackPreviewBody(snapshot.revision, scope, targetNames, value, snapshot.profiles), errors: [] })
    })
  }

  const updateNativeDelegationDraft = updater => {
    if (renderGeneration !== generationRef.current || setupPendingRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setNativeDelegationDraft(current => current ? updater(current) : current)
  }

  const chooseNativeDelegationTargets = (mode, name = null, checked = false) => {
    if (renderGeneration !== generationRef.current || setupPendingRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) || applyPendingRef.current || needsReloadRef.current) return
    const next = mode === 'all' ? profiles.filter(row => !nativeDelegationTargetReason(row, nativeDelegationDraft?.backend)).map(row => row.name)
      : mode === 'source' ? [selectedProfile] : mode === 'none' ? [] : toggleName(nativeDelegationTargets, name, checked)
    invalidatePlan()
    nativeTargetsManualRef.current = true
    setNativeDelegationTargets(next)
    setNativeDelegationDraft(current => current ? { ...current, allowProfileAccess: false } : current)
  }

  const saveNativeDelegation = () => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !nativeDelegationDraft ||
      setupPendingRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) || applyPendingRef.current || needsReloadRef.current || refreshPendingRef.current || !nativeStorageAvailable) return
    const snapshot = freezeDeep({ ...captureSaveSnapshot(), nativeDraft: deepClone(nativeDelegationDraft),
      nativeTargets: [...nativeDelegationTargets], nativeBaselines: deepClone(nativeDelegationBaselines),
      nativeBaseIdentity: statusQuery.data?.readiness_context?.base_identity })
    if (!nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current)) return
    return runSave({ operation: '/delegation-preview', scope: 'native_delegation', snapshot, nativeWrite: true,
      beforeApply: () => nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current),
      prepare: () => ({ body: buildNativeDelegationBatchBody(snapshot.revision, snapshot.profile, snapshot.nativeTargets,
        snapshot.nativeDraft, snapshot.nativeBaselines, snapshot.profiles), errors: [] }) })
  }

  const saveSection = saveScope => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !draft || !statusQuery.data ||
      setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || !profileBaselines) return
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
    if (renderGeneration !== generationRef.current || revisionChanged || timeoutRevisionChanged || !currentRow || !draft || !statusQuery.data || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
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
    if (setupPendingRef.current || profilePreparationReloadBlocked(scopeKey) || applyPendingRef.current || refreshPendingRef.current) return
    const fenceBefore = readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity)
    if (fenceBefore?.foreignScope) { setPageError('이전 저장을 시작한 연결과 프로필로 돌아가 결과를 먼저 확인하세요.'); return }
    if (fenceBefore?.state === 'pending' && !nativeRecoveryConfirmed) { setPageError('이전 저장이 아직 진행 중일 수 있습니다. 작업이 끝났는지 먼저 확인하세요.'); return }
    if (fenceBefore?.state === 'unknown' && !nativeRecoveryConfirmed) { setPageError('이전 저장 작업이 끝났는지 먼저 확인하세요. 같은 설정을 다시 저장하지 마세요.'); return }
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
    if (!finishProfilePreparationReload(response.data.readiness_context, capturedScope)) {
      setPageError('준비를 시작한 원래 연결과 실제 상태를 확인하지 못했습니다. 설정 기준은 갱신하지 않습니다.')
      return
    }
    if (fenceBefore && (fenceBefore.unavailable || response.data.readiness_context?.base_identity !== fenceBefore.baseIdentity ||
        readNativeSaveFence(pluginContext.storage, capturedScope)?.id !== fenceBefore.id ||
        !writeNativeSaveFence(pluginContext.storage, capturedScope, null, fenceBefore.id))) {
      setPageError('저장을 시작한 연결의 실제 상태를 확인하지 못했습니다. 원래 연결에서 다시 확인하세요.'); return
    }
    setNativeRecoveryConfirmed(false)
    const rows = Array.isArray(response.data.profiles) ? response.data.profiles : []
    const row = rows.find(item => item.name === selectedProfile) || rows.find(item => item.name === response.data.current_profile) || rows[0]
    generationRef.current += 1
    setPreview(null)
    setReviewed(false)
    setFallbackPreview(null)
    setProfileBaselines(copyProfileBaselines(rows))
    setNativeDelegationBaselines(copyNativeDelegationBaselines(rows))
    setNativeDelegationTargets(current => nativeTargetsManualRef.current ? current.filter(name => rows.some(row => row.name === name)) : [row?.name].filter(Boolean))
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
    setNativeDelegationDraft(copyNativeDelegationDraft(row.native_delegation))
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
    setNativeDelegationDraft(null)
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
    return jsxs('main', { style: styles.page, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '설정 서비스를 사용할 수 없습니다.' }), jsx('p', { style: styles.hint, children: '이 프로필의 설정 기능에 연결하지 못했습니다. 플러그인이 설치되고 켜져 있는지 확인한 뒤 다시 불러오세요. 기존 설정은 바꾸지 않습니다.' }), jsx('p', { style: styles.hint, children: statusQuery.error?.message || '상태 요청에 실패했습니다.' }), jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => void statusQuery.refetch(), children: '다시 불러오기' })] }), jsx(BackendPreparationGuide, { profile: activeProfile })] })
  }

  const currentPreset = draft ? selectedModelPreset(draft.models) : 'custom'
  const modelPresetCards = draft ? jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
    children: [
      jsx('p', { style: styles.hint, children: '추천 구성을 고르면 아래 네 가지 모델 입력값만 바뀝니다. 저장을 눌러야 적용되며, 예비 모델이나 시간 제한은 바꾸지 않습니다.' }),
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

  const timeoutSettingsSection = section('작업별 실행 시간 제한', '불러온 프로필에서 일반 작업·Light·Heavy의 시간 제한을 각각 분 단위로 편집하고, 아래 시간 제한 적용 대상에 복사합니다. 모델·라우팅·폴백 적용 대상과는 독립적입니다.', jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' },
    children: [
      jsx('p', { id: 'timeout-policy-explanation', role: 'note', style: styles.hint, children: '작업을 얼마나 오래 실행할지 분 단위로 정합니다. 0은 전체 실행 시간을 제한하지 않습니다. 제한에 도달하면 중단을 요청하지만, 실제로 멈추기까지 시간이 걸릴 수 있습니다. 응답 대기 같은 Hermes의 다른 제한은 그대로 유지됩니다. 이전에 하나로 설정했던 값은 Light와 Heavy에 같은 값으로 표시됩니다.' }),
      jsx('p', { style: styles.hint, children: '작업을 시작할 때의 설정을 사용합니다. 이미 진행 중인 작업의 시간은 바뀌지 않습니다. 응답 대기나 반복 횟수 등 다른 제한은 별도로 적용됩니다.' }),
      !timeoutSettingsSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '이 연결에서는 시간 제한을 변경할 수 없습니다. 기존 값을 그대로 표시합니다. Hermes와 플러그인 버전을 확인하세요.' }) : null,
      timeoutSettingsSupported && !timeoutRoleSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '이 연결에서는 Light와 Heavy의 시간 제한을 따로 변경할 수 없습니다. 기존 값을 유지합니다.' }) : null,
      timeoutSettingsSupported && timeoutRoleSupported && currentRow.timeouts.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필의 시간 제한은 읽기 전용입니다. 기존 값을 보존합니다.' }) : null,
      timeoutRevisionChanged || timeoutSaveRevisionChanged ? jsx('p', { role: 'alert', style: styles.warning, children: '선택한 프로필의 시간 제한 설정이 다른 곳에서 바뀌었습니다. 덮어쓰지 않도록 저장을 멈췄습니다. 최신 상태를 다시 불러오세요.' }) : null,
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
      jsx('legend', { style: styles.fieldName, children: '작업 분담을 사용할 프로필' }),
      jsx('p', { style: styles.hint, children: '새로 설치한 프로필은 작업 분담이 기본으로 켜집니다. 이전에 꺼 둔 프로필은 그대로 유지합니다. 아래 체크는 기능 사용 여부이며, 모델을 복사할 대상 선택과는 별개입니다.' }),
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
        jsx('strong', { children: '이전 버전 작업의 예비 모델 · 참고' }),
        jsx('p', { style: styles.hint, children: currentRow?.fallbacks?.routing ? `${currentRow.fallbacks.routing.enabled === true ? '사용' : '미사용'} · Heavy ${readableValue(currentRow.fallbacks.routing.heavy)} · Light ${readableValue(currentRow.fallbacks.routing.light)}` : '상태를 확인할 수 없습니다.' }),
        jsx('a', { href: '#native-delegation-settings', style: { color: 'var(--ui-accent)', fontSize: '0.84rem' }, children: '현재 작업의 예비 모델 설정으로 이동' })
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
    jsx('p', { id: 'native-fallback-recovery-note', role: 'note', style: styles.hint, children: '사용 제한이 풀리면 다음 응답에서 기본 모델을 다시 시도할 수 있습니다. 복귀 준비 알림은 정상 응답을 확인했다는 뜻은 아닙니다. 아래 목록은 예비 모델 설정이며, 지금 대화 중인 모델을 표시하는 것은 아닙니다.' }),
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
      jsx('p', { role: 'note', style: styles.hint, children: '예비 모델을 사용하면 제공자의 요금제에 따라 추가 비용이 발생할 수 있습니다. 아래 저장을 눌러야 적용됩니다.' }),
      fallbackTargetGroup('native', nativeFallbackTargets, nativeEditable),
      fallbackError?.scope === 'native' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'native-fallback-save', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('native'), onClick: () => void saveFallback('native'), children: applyPending ? '저장 중…' : '저장' })
    ] }) : null
  ] })

  const routingFallbackPanel = jsxs('article', { style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '작업·검증 라우팅 폴백' }), jsx(Badge, { variant: routingFallbackStatus?.enabled ? 'warn' : 'muted', children: routingFallbackStatus?.enabled ? '현재 사용' : routingFallbackStatus ? '현재 꺼짐' : '상태 미지원' }), routingFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
    jsx('p', { style: styles.hint, children: '이전 버전 작업의 호환 설정입니다. 현재 Heavy/Light 예비 모델은 위의 ‘작업 분담과 예비 모델’에서 설정하세요. 이 항목은 이전 방식에서 사용량 소진으로 작업을 시작하지 못했을 때만 새 작업을 한 번 시도하는 별도 설정입니다.' }),
    jsx('p', { id: 'routing-fallback-recovery-note', role: 'note', style: styles.hint, children: '폴백으로 시작한 시도는 작업 도중 기본 모델로 다시 전환하지 않습니다. 다음 새 작업은 설정된 기본 경로부터 시작합니다. 진행 중 작업의 경로나 결과가 불명확하다고 자동으로 다시 실행하지 않습니다.' }),
    jsx('p', { style: styles.warning, children: '실패 문구만으로는 재시도하지 않습니다. 확인된 한도 초과가 아니거나 이미 도구/부분 출력이 있으면 재시도하지 않습니다. 대체 실행에는 별도 비용이 발생할 수 있습니다.' }),
    routingFallbackStatus?.enabled && currentRow?.routing?.enabled !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필은 작업 분담이 꺼져 있습니다. 여기서 예비 모델을 저장해도 작업 분담 자체가 켜지지는 않습니다.' }) : null,
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
      jsx('h3', { style: styles.roleTitle, children: '기본 위임 방식의 예비 모델' }),
      jsx(Badge, { variant: delegationStatusValid && delegationStatus.mode !== 'off' ? 'warn' : 'muted', children: delegationStatusValid ? delegationModeLabel(delegationStatus.mode) : '상태 미지원' }),
      delegationFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null
    ] }),
    jsx('p', { style: styles.hint, children: '작업을 맡기는 방식에서 ‘기본 위임 모델 사용’을 골랐을 때의 예비 모델입니다. Heavy/Light 방식의 예비 모델은 위의 ‘작업 분담과 예비 모델’에서 설정합니다.' }),
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
      delegationFallbackDraft.mode === 'off' ? jsx('p', { style: styles.hint, children: '기본 위임 모델은 그대로 사용하고, 다른 모델로 전환하지 않습니다. 일반 대화에 설정한 예비 모델도 사용하지 않습니다.' }) : null,
      delegationFallbackDraft.mode === 'custom' ? jsxs('div', { style: styles.fieldset, children: [
        jsx('strong', { style: styles.fieldName, children: '순서가 있는 위임 전용 목록' }),
        jsx('p', { style: styles.hint, children: '기본 위임 방식의 예비 모델을 위에서 아래 순서로 시도합니다. 일반 대화와 Heavy/Light의 예비 모델은 바꾸지 않습니다.' }),
        jsx('button', { id: 'delegation-fallback-template-non-openai', type: 'button', disabled, onClick: () => updateFallbackDraft('delegation', current => ({ ...current, chain: deepClone(NATIVE_FALLBACK_PRESETS[0].chain) })), style: styles.presetCard, children: [jsx('strong', { children: 'Non-OpenAI 예비 목록 채우기' }), jsx('span', { style: styles.hint, children: '예비 모델 입력값만 채웁니다. 저장을 눌러야 적용됩니다.' }), jsx('span', { style: styles.hint, children: NATIVE_FALLBACK_PRESETS[0].chain.map(item => `${item.provider}/${item.model}`).join(' → ') })] }),
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
    jsx('div', { style: styles.roleGrid, children: nativeFallbackPanel }),
    jsxs('details', { style: styles.cardSection, children: [
      jsx('summary', { style: { cursor: 'pointer' }, children: '다른 작업 방식의 예비 모델 · 고급' }),
      jsx('p', { style: { ...styles.hint, marginBlock: '0.7rem' }, children: '기본 위임 방식이나 이전 버전의 호환 설정입니다. 현재 Heavy/Light 예비 모델은 위의 ‘작업 분담과 예비 모델’에서 설정하세요.' }),
      jsx('div', { style: styles.roleGrid, children: [delegationFallbackPanel, routingFallbackPanel] })
    ] })
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
    ? '시간 제한을 확인할 수 없어 변경하지 않습니다'
    : !timeoutRoleSupported
      ? '역할별 시간 제한 지원 미확인 · 표시만 가능'
      : localCombinedSummary?.body.timeout_updates?.length
        ? `전체 실행 시간 변경: ${localCombinedSummary.body.timeout_updates.length}개 대상 · 일반 ${draft?.timeouts?.delegate_total_minutes}분 / Light ${draft?.timeouts?.routed_light_total_minutes}분 / Heavy ${draft?.timeouts?.routed_heavy_total_minutes}분`
        : timeoutWriteRequested
          ? '시간 제한의 입력값과 대상 프로필 상태를 다시 확인하세요.'
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
      jsxs('header', { style: styles.header, children: [jsxs('div', { children: [jsx('p', { style: { color: 'var(--ui-accent)', fontSize: '0.72rem', fontWeight: 650, letterSpacing: '0.08em', margin: '0 0 0.45rem' }, children: 'HERMES DESKTOP · 모델 제어' }), jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsx('p', { style: styles.subtitle, children: '대화와 작업에 쓸 모델을 정하고, 원하는 프로필에 함께 적용하세요. 바꿀 대상과 내용을 확인한 뒤 저장하면 됩니다.' })] }), jsx(Button, { size: 'sm', variant: 'secondary', disabled: setupPending || profilePreparationReloadBlocked(scopeKey) || statusQuery.isFetching || applyPending, onClick: () => void reloadStatus(), children: '상태 새로고침' })] }),
      jsx('div', { role: 'note', style: styles.notice, children: '새 규칙은 이후에 시작하는 세션과 허용된 작업에 적용됩니다. 이미 진행 중인 세션의 모델은 자동으로 바뀌지 않습니다.' }),
      jsx(InitialSetupCard, { pluginContext, data: statusQuery.data, scopeKey, settingsBusy: applyPending || setupPending || statusQuery.isFetching, begin: beginProfilePreparation, finish: finishProfilePreparation, onPrepared: profilePreparationChanged }),
      jsx(ProfilePreparationCard, { pluginContext, data: statusQuery.data, scopeKey, settingsBusy: applyPending || setupPending || statusQuery.isFetching, begin: beginProfilePreparation, finish: finishProfilePreparation, onPrepared: profilePreparationChanged }),
      profiles.length === 0 ? jsx('div', { role: 'status', style: styles.notice, children: '관리할 프로필이 없습니다. Hermes에서 프로필을 만든 뒤 상태를 새로고침하세요.' }) : null,
      profiles.length ? section('불러올 프로필', '아래에 불러올 설정을 고릅니다. 실제로 바꿀 프로필은 각 카드의 적용 대상에서 따로 선택하세요.', jsxs('div', { style: styles.fields, children: [jsx(ChoiceField, { id: 'profile-select', label: '프로필', value: selectedProfile || '', disabled: disabled || !profiles.length, onChange: selectProfile, options: profiles.map(row => ({ value: row.name, label: row.name })) }), jsx('div', { style: { ...styles.field, justifyContent: 'flex-end' }, children: jsx('span', { style: styles.hint, children: `지금 사용 중인 프로필: ${activeProfile || '확인 중'}` }) })] }), currentRow ? jsx(StatusView, { profile: currentRow }) : null) : null,
      profiles.length ? section('모델 대상', '대화·작업·요약·제목에 쓸 모델을 정합니다. 선택한 프로필에만 이 모델 값을 저장합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [modelFields, modelTargetGroup] })) : null,
      profiles.length ? jsx(NativeDelegationCard, { dto: currentRow?.native_delegation, draft: nativeDelegationDraft, profiles, origin: selectedProfile, sourceRow: currentRow,
        roleScope: { scopeKey, ownerProfile: activeProfile || 'default', connectionId, baseIdentity: statusQuery.data?.readiness_context?.base_identity, available: statusQuery.data?.role_proposal?.available === true, generation: renderGeneration },
        targets: nativeDelegationTargets, disabled: disabled || !nativeStorageAvailable,
        error: sectionErrors.native_delegation || nativeDelegationError || (!nativeStorageAvailable ? '저장 준비를 확인할 수 없습니다. 플러그인을 다시 열어 주세요.' : ''),
        onChange: updateNativeDelegationDraft, onTargets: chooseNativeDelegationTargets, onSave: () => void saveNativeDelegation() }) : null,
      profiles.length ? timeoutSettingsSection : null,
      profiles.length ? section('Heavy / Light 기본 모델', '간단한 작업은 메인 모델이 직접 처리합니다. 나눠 맡기는 편이 유리한 작업은 Light에, 계획이나 중요한 검토는 Heavy에 맡깁니다. 단순 글쓰기·번역·요약 때문에 무조건 Heavy를 쓰지는 않습니다. 여기서는 각 역할의 기본 모델을 정합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { style: styles.hint, children: routingSummary }),
        jsx('p', { id: 'routing-default-note', role: 'note', style: styles.hint, children: 'Heavy와 Light에 같은 모델을 지정해도 작업은 각각 따로 진행됩니다. 같은 모델의 별도 검토가 서로 다른 모델을 쓰는 검토를 뜻하지는 않습니다. 저장하기 전에는 현재 설정이 바뀌지 않습니다.' }),
        jsxs('details', { style: styles.cardSection, children: [
          jsxs('summary', { style: { cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.8rem', flexWrap: 'wrap' }, children: [jsx('strong', { children: '역할별 기본 모델 바꾸기' }), jsx(Badge, { variant: 'muted', children: `사용 프로필 ${routingProfiles.length}개` })] }),
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
      applyOutcome ? jsxs('div', { role: 'status', 'aria-live': 'polite', style: applyOutcome.kind === 'success' ? styles.message : styles.warning, children: [jsx('strong', { children: applyOutcome.kind === 'prepared' ? '플러그인 준비 상태가 달라졌습니다.' : applyOutcome.kind === 'success' ? '적용 요청이 완료되었습니다.' : applyOutcome.kind === 'partial' ? '일부 설정만 적용되었을 수 있습니다.' : '적용 결과를 확인할 수 없습니다.' }), jsx('p', { style: styles.hint, children: applyOutcome.message || (applyOutcome.kind === 'success' ? '실제 상태를 새로고침해 확인하세요. 저장한 내용을 다시 확인한 뒤 편집을 계속하세요.' : '다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요.') }), applyOutcome.result ? jsxs('details', { children: [jsx('summary', { style: { cursor: 'pointer', fontSize: '0.8rem' }, children: '세부 결과 보기 · 고급' }), jsx('pre', { style: styles.value, children: readableValue(applyOutcome.result) })] }) : null] }) : null,
      nativeFence ? jsxs('div', { id: 'native-save-recovery', style: styles.warning, children: [
        jsx('p', { children: nativeFence.foreignScope ? '다른 연결에서 시작한 저장 결과를 확인해야 합니다. 저장을 시작한 원래 연결과 프로필로 돌아가 주세요.' : nativeFence.state === 'pending' ? '이전에 시작한 저장이 끝났는지 확인해야 합니다. 같은 설정을 다시 저장하지 마세요.' : nativeFence.state === 'settled' ? '이전에 저장한 결과를 다시 불러온 뒤 편집할 수 있습니다.' : '이전 저장 결과를 확인할 수 없습니다. 같은 설정을 다시 저장하지 말고, 원래 연결에서 저장 작업이 끝났는지 확인하세요.' }),
        (nativeFence.state === 'unknown' || (nativeFence.state === 'pending' && !applyPending)) && !nativeFence.foreignScope ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.6rem' }, children: [
          jsx(CheckRow, { id: 'native-save-recovery-confirm', label: '이전 저장 작업이 끝난 것을 확인했습니다', checked: nativeRecoveryConfirmed, disabled: statusQuery.isFetching, onChange: setNativeRecoveryConfirmed }),
          jsx(Button, { id: 'native-save-recover', size: 'sm', variant: 'secondary', disabled: !nativeRecoveryConfirmed || statusQuery.isFetching || nativeFence.unavailable, onClick: () => void reloadStatus(), children: '확인한 설정 다시 불러오기' })
        ] }) : null
      ] }) : null,
      needsReload || nativeFence ? jsx('div', { style: styles.actions, children: jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching || nativeFence?.state === 'pending', onClick: () => void reloadStatus(), children: statusQuery.isFetching ? '상태 확인 중…' : '실제 상태 확인 후 편집 재개' }) }) : null,
      profiles.length && !needsReload ? section('기본 모델·시간·기타 설정 함께 저장', '위에서 편집한 모델·작업 분담·예비 모델을 함께 저장합니다. 각 카드에서 고른 적용 대상은 그대로 따릅니다. ‘작업 분담과 예비 모델’ 카드는 별도 저장입니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [
        jsx('div', { id: 'draft-reference-summary', role: 'note', style: styles.section, children: [
          jsx('strong', { children: '현재 초안 요약 · 참고 정보' }),
          jsx('p', { style: styles.hint, children: `모델 적용 대상 ${targetSummary} · 라우팅 활성 ${routingProfiles.length}개 · Heavy/Light 설정 적용 ${routingWriteTargets.length}개 (${routingWriteTargets.join(', ') || '기존 설정 유지'})` }),
          jsx('p', { style: styles.hint, children: modifiedFallbackSummary.length
            ? `수정한 폴백: ${modifiedFallbackSummary.map(item => `${item.label} ${item.count}개 대상`).join(' · ')}`
            : '수정한 폴백 없음' }),
          jsx('p', { style: styles.hint, children: timeoutSummary }),
          jsx('p', { style: styles.hint, children: '저장 전 변경 내용을 요약한 참고 정보입니다. 실제 반영 결과는 저장 후 상태를 다시 불러와 확인하세요.' }),
          summaryValidationErrors.length ? jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '확인할 항목' }), jsx('ul', { children: summaryValidationErrors.map((error, index) => jsx('li', { children: error }, index)) })] }) : jsx('p', { role: 'status', style: styles.hint, children: '입력한 내용을 확인했습니다. 저장할 때 최신 설정과 다시 비교합니다.' })
        ] }),
        jsx(Button, { id: 'global-save', size: 'sm', variant: 'secondary', disabled: !canSaveAll, onClick: () => void saveAll(), children: applyPending ? '저장 중…' : '저장' })
      ] })) : null
    ]
  })
}

export default {
  id: PLUGIN_ID,
  name: '모델 및 라우팅',
  version: '0.8.0',
  defaultEnabled: false,
  register(ctx) {
    preparationStorage = ctx.storage || null
    if (typeof ctx.onDispose === 'function') ctx.onDispose(cancelProfilePreparation)
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
