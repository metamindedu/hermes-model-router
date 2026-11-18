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
  fieldset: { margin: 0, padding: 0, border: 0, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.8rem' },
  modelRoute: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.7rem' },
  modelTrigger: { boxSizing: 'border-box', width: '100%', minWidth: 0, height: 'auto', minHeight: '2.85rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem', padding: '0.45rem 0.7rem', textAlign: 'left', whiteSpace: 'normal', fontWeight: 400 },
  modelTriggerCopy: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.1rem', overflowWrap: 'anywhere' },
  modelTriggerModel: { color: 'var(--ui-text-primary)', fontSize: '0.86rem', fontWeight: 580, lineHeight: 1.35 },
  modelTriggerEmpty: { color: 'var(--ui-text-tertiary)', fontSize: '0.86rem', fontWeight: 400, lineHeight: 1.35 },
  modelTriggerProvider: { color: 'var(--ui-text-tertiary)', fontSize: '0.75rem', lineHeight: 1.35 },
  modelMenu: { boxSizing: 'border-box', width: 'min(20rem, calc(100vw - 1.5rem))', padding: 0 },
  manualSummary: { cursor: 'pointer', color: 'var(--ui-text-tertiary)', fontSize: '0.78rem', lineHeight: 1.5 },
  manualBody: { display: 'flex', flexDirection: 'column', gap: '0.55rem', marginTop: '0.6rem' }
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

// What the page showed of one profile, frozen when it was first seen: every value a store save may
// overwrite, in the shape the status row reports it. Sent as `expected`, so the service refuses a save
// over a value that changed elsewhere (model_router/service.py _check_page_expectations).
export function pageExpectation(row) {
  if (!row || typeof row.name !== 'string' || !row.models || !row.routing) return null
  const native = row.fallbacks?.native
  return deepClone({ models: row.models, actual_models: row.actual_models || {},
    routing: { enabled: Boolean(row.routing.enabled), heavy: row.routing.heavy ?? null, light: row.routing.light ?? null, slots: row.routing.slots ?? null,
      skill_enabled: routingSkillEnabled(row) },
    ...(native ? { native_fallback: { enabled: native.enabled ?? null, chain: native.chain ?? [], actual_chain: native.actual_chain ?? [] } } : {}) })
}

// The routing skill's own switch in the profile's skills.disabled: the status reports a
// 'skills.disabled' drift when it differs from the canonical flag, and 'skills.disabled_unavailable'
// when it cannot be read. A routing save may rewrite it, so it is part of what the page froze.
export function routingSkillEnabled(row) {
  const drift = Array.isArray(row?.drift) ? row.drift : []
  return drift.includes('skills.disabled_unavailable') ? null : Boolean(row?.routing?.enabled) !== drift.includes('skills.disabled')
}

// Task routing actually runs for this profile: the canonical flag is on AND its routing skill is not
// disabled in the profile's own config (what the service's routing_config reports as enabled).
export function routingEffectivelyOn(row) {
  return row?.routing?.enabled === true && routingSkillEnabled(row) === true
}

export function copyPageExpectations(profiles) {
  return Object.fromEntries((Array.isArray(profiles) ? profiles : []).map(row => [row?.name, pageExpectation(row)]).filter(([name, value]) => typeof name === 'string' && value))
}

// The frozen expectations one request body needs: every profile and field it may write. Routing
// membership and its skill switch can be repaired on any loaded profile, so a routing-scope body
// covers every profile the page froze.
export function pageExpectationsFor(operation, body, frozen, liveNames = []) {
  const need = new Map()
  const add = (name, field) => { if (!need.has(name)) need.set(name, new Set()); need.get(name).add(field) }
  if (operation === '/preview') {
    const scope = body?.save_scope ?? null
    if (scope === null || scope === 'models') for (const name of body?.model_targets || []) { add(name, 'models'); add(name, 'actual_models') }
    if (scope === null || scope === 'routing') for (const name of liveNames) if (frozen?.[name]) add(name, 'routing')
    for (const update of body?.fallback_updates || []) if (update && Object.prototype.hasOwnProperty.call(update, 'native_fallback')) add(update.profile, 'native_fallback')
  } else if (operation === '/fallback-preview') {
    for (const update of body?.updates || []) if (update && Object.prototype.hasOwnProperty.call(update, 'native_fallback')) add(update.profile, 'native_fallback')
  }
  return [...need].map(([name, fields]) => {
    const value = frozen?.[name]
    if (!value || [...fields].some(field => !value[field])) throw new Error(`${name} 프로필은 이 화면에서 확인한 값이 없어 저장하지 않았습니다. 상태 새로고침 후 다시 저장하세요.`)
    return { profile: name, ...Object.fromEntries([...fields].sort().map(field => [field, deepClone(value[field])])) }
  })
}

// The service reports a compare-and-set refusal as {error: 'ExternalChange', conflict: {profile, field}}.
const EXTERNAL_CHANGE_FIELD_RE = /^[a-z_]+(?:\.[a-z_]+)?$/
export function externalChangeFromError(error) {
  if (error?.backendError !== 'ExternalChange') return null
  const profile = error?.conflict?.profile, field = error?.conflict?.field
  return typeof profile === 'string' && profile && typeof field === 'string' && EXTERNAL_CHANGE_FIELD_RE.test(field)
    ? { profile, field } : null
}
const EXTERNAL_FIELD_LABELS = { models: '저장된 모델', actual_models: '실제 모델 설정', routing: '작업 라우팅', native_fallback: '대화 예비 모델' }
const EXTERNAL_ROLE_LABELS = { main: '대화 모델', delegation: '작업 모델', compression: '압축 모델', title: '제목 모델' }
export function externalChangeLabel(conflict) {
  const [base, role] = String(conflict?.field || '').split('.')
  return `${EXTERNAL_FIELD_LABELS[base] || '설정'}${role ? `(${EXTERNAL_ROLE_LABELS[role] || role})` : ''}`
}
export function externalChangeMessage(conflict) {
  return `다른 곳에서 변경됨 — 다시 불러오세요. ${conflict.profile} 프로필의 ${externalChangeLabel(conflict)} 값이 이 화면을 연 뒤 바뀌어 아무것도 저장하지 않았습니다. 상태 새로고침으로 최신 값을 불러온 뒤 다시 편집하세요.`
}

// Values that changed elsewhere since they were frozen, at the same store revision. Early feedback
// only: the service refuses such a save by itself (see pageExpectation).
export function pageLiveDrift(rows, selected, frozenProfiles, frozenExpectations) {
  const items = []
  const same = (live, loaded) => sameValue(live ?? null, loaded ?? null)
  const list = Array.isArray(rows) ? rows : []
  const current = list.find(row => row.name === selected)
  const frozen = frozenProfiles?.[selected]
  const expect = frozenExpectations?.[selected]
  if (current && frozen) {
    if (!same(current.models, frozen.models) || (expect && !same(current.actual_models || {}, expect.actual_models))) items.push({ profile: selected, part: '대화·작업 모델' })
    if (!same(current.routing?.heavy, frozen.routing?.heavy) || !same(current.routing?.light, frozen.routing?.light)) items.push({ profile: selected, part: '작업 라우팅' })
    if (!same(current.slots?.declarations, frozen.slots)) items.push({ profile: selected, part: '작업 슬롯 모델' })
  }
  for (const row of list) {
    const base = frozenProfiles?.[row.name]
    const frozenSkill = frozenExpectations?.[row.name]?.routing?.skill_enabled
    if ((base && Boolean(row.routing?.enabled) !== Boolean(base.routing?.enabled)) ||
        (frozenSkill !== undefined && routingSkillEnabled(row) !== frozenSkill)) items.push({ profile: row.name, part: '작업 라우팅 사용 여부' })
  }
  if (current && expect?.native_fallback) {
    const native = current.fallbacks?.native
    const live = native ? { enabled: native.enabled ?? null, chain: native.chain ?? [], actual_chain: native.actual_chain ?? [] } : null
    if (!same(live, expect.native_fallback)) items.push({ profile: selected, part: '대화 예비 모델', fallback: true })
  }
  return items
}
export const liveDriftMessage = items => `다른 곳에서 ${items.map(item => `${item.profile} 프로필의 ${item.part}`).join(', ')} 값이 바뀌었습니다. 그 값을 예전 값으로 덮어쓰지 않도록 저장을 막았습니다. 상태 새로고침으로 최신 값을 불러온 뒤 다시 편집하세요. 새로고침하면 저장하지 않은 편집은 사라집니다.`

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
    ...(profile.slots?.declarations ? { slots: profile.slots.declarations } : {}),
    ...(timeouts ? { timeouts } : {})
  })
}

// Slot helpers keep the original role routes and stored routing declarations intact.
export function slotFollowDeclaration(declaration, follow, models) {
  if (!['main', 'delegation', 'custom'].includes(follow)) throw new Error('invalid slot basis')
  if (follow !== 'custom') return { follow, custom: null }
  const route = declaration?.follow === 'custom' ? declaration.custom : models?.[declaration?.follow]
  return { follow, custom: deepClone(route || { provider: '', model: '', reasoning: '' }) }
}

export function slotRoutingForSave(draft, editable) {
  const routing = deepClone(draft.routing)
  delete routing.slots
  if (editable && draft.slots) routing.slots = deepClone(draft.slots)
  return routing
}

// A slot is what the operator assigns a model to; tier only names which of the
// two routed runtime limits applies. Order and ids mirror the backend.
export const TASK_SLOTS = [
  { id: 'design', tier: 'heavy', label: '설계', description: '계획을 세우고 구조를 정하는 작업' },
  { id: 'code-complex', tier: 'light', label: '코드 · 복잡', description: '여러 파일에 걸친 구현과 까다로운 수정' },
  { id: 'code-simple', tier: 'light', label: '코드 · 간단', description: '정해진 패턴의 수정과 테스트·빌드 같은 반복 작업' },
  { id: 'verify-simple', tier: 'light', label: '검증 · 간단', description: '예비 검토와 가벼운 확인' },
  { id: 'verify-complex', tier: 'heavy', label: '검증 · 복잡', description: '최종 의미 검토와 독립 검수' },
  { id: 'computer-use', tier: 'light', label: '컴퓨터 유즈', description: '브라우저나 데스크톱 화면을 직접 조작하는 작업' }
].map(slot => Object.freeze(slot))
export const SLOT_FOLLOW_OPTIONS = [
  { value: 'main', label: '기본 대화 모델과 같게' },
  { value: 'delegation', label: '작업 위임 모델과 같게' },
  { value: 'custom', label: '직접 지정' }
]

// What the loaded profile's installed plugin can do with slots. `available`
// shows the cards; `editable` is false while another installed profile could
// not read a saved slot (the settings file is shared by every profile).
export function slotSupport(status, row) {
  const capabilities = status?.slot_capabilities
  const declarations = row?.slots?.declarations
  const available = capabilities?.schema === 1 && row?.slots?.schema === 1 && row.slots.capable === true &&
    Boolean(declarations) && TASK_SLOTS.every(slot => ['main', 'delegation', 'custom'].includes(declarations[slot.id]?.follow))
  const blocking = available && Array.isArray(capabilities.blocking_profiles) ? capabilities.blocking_profiles.filter(name => typeof name === 'string') : []
  return { available, editable: available && blocking.length === 0, blocking }
}

export function slotResolvedRoute(declaration, models) {
  const route = declaration?.follow === 'custom' ? declaration.custom : models?.[declaration?.follow]
  return route && typeof route === 'object' ? route : null
}

export function slotDraftError(slots) {
  for (const slot of TASK_SLOTS) {
    const declaration = slots?.[slot.id]
    if (!declaration || !['main', 'delegation', 'custom'].includes(declaration.follow)) return `${slot.label}: 모델 기준을 선택하세요.`
    if (declaration.follow !== 'custom') continue
    const route = declaration.custom
    if (!route || !String(route.provider || '').trim() || !String(route.model || '').trim()) return `${slot.label}: 모델을 선택하세요.`
    if (!String(route.reasoning || '').trim()) return `${slot.label}: 추론 강도를 선택하세요.`
  }
  return ''
}

export function toggleName(names, name, checked) {
  const set = new Set(Array.isArray(names) ? names : [])
  if (checked) set.add(name)
  else set.delete(name)
  return [...set]
}

// The retired routed-job fallback (`routing.fallback`) is never sent: the plugin keeps the stored
// value when it is absent, and only fallback_preview could change it.
export function buildPreviewBody(revision, profile, draft, modelTargets, routingProfiles, routingTargets) {
  const { fallback: _retiredFallback, ...routing } = deepClone(draft.routing) || {}
  return {
    expected_revision: revision,
    profile,
    models: deepClone(draft.models),
    model_targets: Array.isArray(modelTargets) ? [...modelTargets] : [],
    routing: { ...routing, enabled: routingProfiles.includes(profile) },
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
  if (!draft || typeof draft.enabled !== 'boolean' || !Array.isArray(draft.chain)) return '대화 예비 모델 설정을 확인할 수 없습니다.'
  if (draft.chain.length > 5) return '대화 예비 모델은 최대 5개까지 지원합니다.'
  if (draft.chain.some(item => !item || typeof item.provider !== 'string' || !item.provider.trim() || typeof item.model !== 'string' || !item.model.trim())) return '각 예비 모델 항목에 공급자와 모델을 입력하세요.'
  const identities = draft.chain.map(item => JSON.stringify([item.provider, item.model]))
  if (new Set(identities).size !== identities.length) return '대화 예비 모델 목록에 중복된 공급자·모델 조합이 있습니다.'
  if (draft.enabled && draft.chain.length === 0) return '대화 예비 모델을 켜려면 모델을 하나 이상 추가하세요.'
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
  if (!draft || typeof draft.enabled !== 'boolean') return '이전 작업 방식의 예비 모델 설정을 확인할 수 없습니다.'
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

// Only the conversation scope is edited on the page. The other two are stored values the page
// keeps reading (status, projected checks) but never writes; their titles say so.
export const PAGE_FALLBACK_SCOPES = freezeDeep(['native'])
export function fallbackScopeTitle(scope) {
  return ({ native: '대화 예비 모델', routing: '이전 작업 방식의 보관된 예비 모델', delegation: '이전 기본 위임 방식의 보관된 예비 모델' })[scope] || '예비 모델'
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
          return `${row.name}의 기본 대화 모델과 대화 예비 모델은 달라야 합니다.`
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
  // Stored routing and delegation fallbacks are never part of a page save, whatever the drafts hold.
  const scopes = PAGE_FALLBACK_SCOPES

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

// Hermes returns at most 48,000 characters of one CLI call's output, so the status of many profiles
// is read in size-bounded pages and joined here. `send(body)` performs one status call. Every page
// must describe the same revision, installation and profile list, otherwise nothing is returned.
// A backend from before paging refuses any status body; it is then asked once the old way.
export const STATUS_PAGE_LIMIT = 64
export const STATUS_CHANGED_MESSAGE = '상태를 읽는 동안 설정이나 프로필 목록이 바뀌었습니다. 상태를 다시 불러오세요.'
export async function readPagedStatus(send) {
  let first
  try { first = await send({ paged: true }) }
  catch (error) {
    if (error?.backendError !== 'ValueError') throw error
    return send({})
  }
  if (!first || !Array.isArray(first.pending_profiles)) return first
  const names = first.profile_names
  const rowNames = data => Array.isArray(data?.profiles) ? data.profiles.map(row => row?.name) : null
  const identity = data => data?.readiness_context?.base_identity ?? null
  const fail = () => { throw new Error(STATUS_CHANGED_MESSAGE) }
  if (!Array.isArray(names) || !rowNames(first) || !sameValue([...rowNames(first), ...first.pending_profiles], names)) fail()
  const rows = [...first.profiles]
  let pending = first.pending_profiles
  for (let page = 0; pending.length; page++) {
    if (page >= STATUS_PAGE_LIMIT) fail()
    const next = await send({ paged: true, profiles: pending })
    if (!next || next.revision !== first.revision || identity(next) !== identity(first) || !sameValue(next.profile_names, names) ||
        !rowNames(next)?.length || !Array.isArray(next.pending_profiles) || !sameValue([...rowNames(next), ...next.pending_profiles], pending)) fail()
    rows.push(...next.profiles)
    pending = next.pending_profiles
  }
  const { pending_profiles: _pending, profile_names: _names, ...status } = first
  return { ...status, profiles: rows }
}

// The backend refuses a request body over 16,384 characters before reading it; say why up front.
// Bodies over one command line are staged in pieces (see stagedBodyChunks); this is the overall cap.
export const PREVIEW_BODY_LIMIT = 400000
export const BODY_TOO_LARGE_MESSAGE = '한 번에 저장하기에는 내용이 너무 큽니다. 적용 대상 프로필을 줄여 여러 번에 나눠 저장하세요.'
export const previewBodyTooLarge = body => Boolean(body) && JSON.stringify(body).length > PREVIEW_BODY_LIMIT

// The model section's store save: one scope when only one part changed, otherwise role models
// and slot models in one plan. Timeouts and the legacy fallback are never part of it.
export function buildModelSectionPreviewBody(snapshot, storeScope) {
  if (storeScope === 'models' || storeScope === 'routing') {
    const prepared = buildScopedPreviewBody(snapshot, storeScope)
    return storeScope === 'routing' && snapshot.routingTargetError ? { body: prepared.body, errors: [...prepared.errors, snapshot.routingTargetError] } : prepared
  }
  const baseline = snapshot?.profileBaselines?.[snapshot.profile]
  if (!baseline?.models || !baseline?.routing || !snapshot.draft) return { body: null, errors: ['불러온 기준 설정을 확인할 수 없습니다. 상태를 새로고침하세요.'] }
  const routing = deepClone(snapshot.draft.routing)
  const body = buildPreviewBody(snapshot.revision, snapshot.profile, { models: deepClone(snapshot.draft.models), routing },
    snapshot.modelTargets, snapshot.routingProfiles, snapshot.routingTargets)
  return { body, errors: snapshot.routingTargetError ? [snapshot.routingTargetError] : [] }
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
  const routingProfiles = saveScope === 'routing' ? snapshot.routingProfiles : baselineMembership
  const modelTargets = saveScope === 'models' ? snapshot.modelTargets : []
  const routingTargets = saveScope === 'routing' ? snapshot.routingTargets : []
  const body = buildPreviewBody(snapshot.revision, snapshot.profile, {
    models: deepClone(models),
    routing: deepClone(routing)
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
    if (error) errors.push(`프로필 ${row.name}에 보관된 이전 작업 방식의 예비 모델과 겹칩니다(이 화면에서는 바꾸지 않는 값입니다): ${error}`)
  }
  return errors
}

export function previewFieldLabel(field) {
  const labels = {
    native_fallback: '대화 예비 모델',
    fallback_providers: '대화 예비 모델 목록',
    fallback_model: '이전 대화 예비 모델 설정',
    'routing.fallback': '이전 작업 방식의 보관된 예비 모델',
    delegation_fallback: '이전 기본 위임 방식의 보관된 예비 모델',
    'delegation.fallback_providers': '이전 기본 위임 방식의 보관된 예비 모델 목록',
    'fallback_consent.native': '대화 예비 모델 승인 기록',
    'fallback_consent.routing': '이전 작업 방식 예비 모델 승인 기록',
    'fallback_consent.delegation': '이전 기본 위임 방식 예비 모델 승인 기록'
  }
  return labels[field] || field || '설정 항목'
}

export function fallbackPreviewMatchesScope(preview, scopeKey, generation, profile, scope) {
  return Boolean(preview && preview.scopeKey === scopeKey && preview.generation === generation &&
    preview.profile === profile && preview.scope === scope)
}

// Reasoning levels the settings backend accepts (service.EFFORTS). The exact
// identifier stays visible beside the plain-language label.
export const REASONING_LEVELS = freezeDeep([
  { value: 'none', label: '추론 끔 (none)' },
  { value: 'minimal', label: '최소 (minimal)' },
  { value: 'low', label: '낮음 (low)' },
  { value: 'medium', label: '보통 (medium)' },
  { value: 'high', label: '높음 (high)' },
  { value: 'xhigh', label: '매우 높음 (xhigh)' },
  { value: 'max', label: '최대 (max)' },
  { value: 'ultra', label: '울트라 (ultra)' }
])

// A stored level outside the list stays selectable so opening the page never
// rewrites or hides it; the save validation still decides whether it is valid.
export function reasoningChoices(value) {
  const current = typeof value === 'string' ? value : ''
  const options = REASONING_LEVELS.map(item => ({ value: item.value, label: item.label }))
  if (current && !options.some(item => item.value === current)) options.push({ value: current, label: `${current} · 목록에 없는 값` })
  return options
}

// The host's own catalog menu (the composer's searchable picker). Older hosts
// do not export it; callers then keep the plain ID inputs.
export function nativeModelMenu(sdk = DesktopSDK) {
  const names = ['ModelCatalogMenu', 'DropdownMenu', 'DropdownMenuContent', 'DropdownMenuTrigger']
  if (!sdk || names.some(name => !sdk[name]) || !sdk.ModelMenuCloseContext?.Provider) return null
  return { ModelCatalogMenu: sdk.ModelCatalogMenu, DropdownMenu: sdk.DropdownMenu, DropdownMenuContent: sdk.DropdownMenuContent,
    DropdownMenuTrigger: sdk.DropdownMenuTrigger, CloseProvider: sdk.ModelMenuCloseContext.Provider }
}

// What a menu selection means here: edit the draft through the existing field
// updater only. Picking a model keeps the saved reasoning level, because each
// role owns that value; only an explicit level pick on a row changes it. Every
// row therefore previews the role's own level, and the host's default level is
// taken only when the role has none yet.
export function modelMenuController({ route, withReasoning = false, onChange }) {
  const value = route && typeof route === 'object' ? route : {}
  const read = key => typeof value[key] === 'string' ? value[key] : ''
  const level = effort => typeof effort === 'string' && REASONING_LEVELS.some(item => item.value === effort)
  const saved = withReasoning && level(value.reasoning) ? value.reasoning : ''
  const pick = (provider, model) => {
    if (typeof provider !== 'string' || typeof model !== 'string' || !provider || !model) return false
    if (provider !== value.provider) onChange('provider', provider)
    if (model !== value.model) onChange('model', model)
    return true
  }
  return {
    allowSpeed: false,
    current: { provider: read('provider'), model: read('model'), effort: withReasoning ? read('reasoning') : '', fast: false },
    presetFor: () => saved ? { effort: saved } : {},
    applyPreset: preset => {
      if (withReasoning && !read('reasoning') && level(preset?.effort)) onChange('reasoning', preset.effort)
    },
    select: (model, provider) => pick(provider, model),
    setOptions: (patch, row) => {
      if (!withReasoning || !level(patch?.effort)) return
      if (pick(row?.provider, row?.model)) onChange('reasoning', patch.effort)
    }
  }
}

// Read-only catalog transport for that menu. Only the configured-provider
// inventory of the loaded profile may pass, pinned to that profile so another
// connection can never answer for it: the active profile uses the connected
// socket, any other loaded profile its exact fresh local route descriptor.
export function createModelCatalogRequest(transport, scope) {
  const sameScope = () => transport?.state?.profile?.get?.() === scope?.activeProfile &&
    (transport?.state?.connectionId?.get?.() || null) === (scope?.connectionId || null)
  return async method => {
    if (method !== 'model.options') throw new Error('이 목록에서는 모델 목록만 읽을 수 있습니다.')
    const profile = scope?.profile
    if (typeof profile !== 'string' || !PREPARATION_PROFILE_RE.test(profile) || typeof scope.activeProfile !== 'string' || !scope.activeProfile) {
      throw new Error('불러온 프로필을 확인할 수 없습니다. ID 직접 입력을 사용하세요.')
    }
    if (!sameScope()) throw new Error('연결된 프로필이 바뀌었습니다. 목록을 닫고 다시 열어 주세요.')
    const params = { profile, explicit_only: true }
    if (profile === scope.activeProfile) return transport.request('model.options', params)
    if (typeof transport.profileRoutes !== 'function' || typeof transport.requestProfile !== 'function') {
      throw new Error(`'${profile}' 프로필의 모델 목록을 불러올 수 없습니다. ID 직접 입력을 사용하세요.`)
    }
    const routes = await transport.profileRoutes()
    if (!sameScope()) throw new Error('연결된 프로필이 바뀌었습니다. 목록을 닫고 다시 열어 주세요.')
    const source = selectPreparationRoute(routes, scope.connectionId || null, scope.activeProfile)
    const target = source ? selectPreparationTargetRoute(routes, source, profile) : null
    if (!target) throw new Error(`'${profile}' 프로필의 모델 목록을 불러올 수 없습니다. ID 직접 입력을 사용하세요.`)
    return transport.requestProfile(target, 'model.options', params)
  }
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

// The trigger shows the exact saved IDs; the menu itself is the host's.
function ModelPickerButton({ id, label, route, onChange, disabled, withReasoning, catalog, menu }) {
  const [open, setOpen] = useState(false)
  const value = route && typeof route === 'object' ? route : {}
  const model = typeof value.model === 'string' ? value.model.trim() : ''
  const provider = typeof value.provider === 'string' ? value.provider.trim() : ''
  const summary = model ? `${provider || '공급자 미지정'} / ${model}` : '선택 안 됨'
  return jsxs(menu.DropdownMenu, {
    open: open && !disabled,
    onOpenChange: next => setOpen(next === true && !disabled),
    children: [
      jsx(menu.DropdownMenuTrigger, { asChild: true, children: jsxs(Button, {
        id, type: 'button', variant: 'outline', disabled, 'aria-label': `${label}: ${summary}`, style: styles.modelTrigger,
        children: [
          jsxs('span', { style: styles.modelTriggerCopy, children: [
            jsx('span', { style: model ? styles.modelTriggerModel : styles.modelTriggerEmpty, children: model || '모델 선택' }),
            jsx('span', { style: styles.modelTriggerProvider, children: provider || (model ? '공급자 ID를 확인하세요' : '목록에서 고르거나 ID를 직접 입력하세요') })
          ] }),
          jsx(Codicon, { name: 'chevron-down', size: '0.8rem', 'aria-hidden': true, style: { flexShrink: 0, opacity: 0.55 } })
        ]
      }) }),
      jsx(menu.DropdownMenuContent, { align: 'start', style: styles.modelMenu, children: jsx(menu.CloseProvider, {
        value: () => setOpen(false),
        children: jsx(menu.ModelCatalogMenu, {
          controller: modelMenuController({ route: value, withReasoning, onChange }),
          profile: catalog.profile,
          ownerConnectionId: catalog.connectionId || undefined,
          request: createModelCatalogRequest(host, catalog)
        })
      }) })
    ]
  })
}

// One model route: the catalog picker first, exact IDs as a fallback. Without
// a loaded profile or on a host lacking the menu, the ID inputs stand alone.
function ModelRouteField({ ids, labels, route, onChange, disabled, catalog = null, withReasoning = false }) {
  const value = route && typeof route === 'object' ? route : {}
  const menu = catalog?.profile ? nativeModelMenu() : null
  const providerField = jsx(Field, { id: ids.provider, label: labels.provider, value: value.provider, onChange: next => onChange('provider', next), disabled })
  const modelField = jsx(Field, { id: ids.model, label: labels.model, value: value.model, onChange: next => onChange('model', next), disabled })
  const reasoningField = withReasoning ? jsx(ChoiceField, { id: ids.reasoning, label: '추론 강도', value: typeof value.reasoning === 'string' ? value.reasoning : '',
    options: reasoningChoices(value.reasoning), placeholder: '강도 선택', disabled, onChange: next => onChange('reasoning', next),
    hint: '모델이 지원하는 강도를 고르세요. 저장할 때 확인합니다.' }) : null
  if (!menu) return jsxs('div', { style: styles.fields, children: [providerField, modelField, reasoningField] })
  return jsxs('div', {
    style: styles.modelRoute,
    children: [
      jsxs('div', { style: styles.field, children: [
        jsx('span', { style: styles.fieldName, children: labels.picker }),
        jsx(ModelPickerButton, { id: ids.picker, label: labels.picker, route: value, onChange, disabled, withReasoning, catalog, menu }),
        withReasoning ? null : jsx('span', { style: styles.hint, children: '이 항목에는 추론 강도를 따로 저장하지 않습니다.' })
      ] }),
      reasoningField,
      jsxs('details', { children: [
        jsx('summary', { style: styles.manualSummary, children: 'ID 직접 입력' }),
        jsxs('div', { style: styles.manualBody, children: [
          jsx('span', { style: styles.hint, children: '목록에 없는 모델은 공급자 ID와 모델 ID를 정확히 입력하세요.' }),
          jsxs('div', { style: styles.fields, children: [providerField, modelField] })
        ] })
      ] })
    ]
  })
}

function RoleRouteFields({ prefix, route, onChange, disabled, catalog }) {
  return jsx(ModelRouteField, {
    ids: { picker: `${prefix}-picker`, provider: `${prefix}-provider`, model: `${prefix}-model`, reasoning: `${prefix}-reasoning` },
    labels: { picker: '모델', provider: '공급자 ID', model: '모델 ID' },
    route, onChange, disabled, catalog, withReasoning: true
  })
}

function ChoiceField({ id, label, value, onChange, options, disabled, placeholder, hint }) {
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
            children: jsx(SelectValue, { placeholder, style: { whiteSpace: 'normal', overflowWrap: 'anywhere', minWidth: 0, textAlign: 'left' } }) }),
          jsx(SelectContent, { children: options.map(option => jsx(SelectItem, { value: option.value, ...(option.disabled === true ? { disabled: true } : {}), children: option.label }, option.value)) })
        ]
      }),
      hint ? jsx('span', { style: styles.hint, children: hint }) : null
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
  const once = async body => {
    const reply = await transport.requestProfile(route, 'cli.exec', {
      argv: ['--profile', route.targetProfile, 'model-router', 'status', '--body', JSON.stringify(body)],
      profile: route.targetProfile, timeout: 180
    }, 210000)
    if (!reply || reply.blocked) throw new Error('preparation_status_unavailable')
    const frames = String(reply.output || '').split(/\r?\n/).filter(line => line.startsWith('MODEL_ROUTER_JSON:'))
    if (frames.length !== 1) throw new Error('preparation_status_unavailable')
    let page
    try { page = JSON.parse(frames[0].slice('MODEL_ROUTER_JSON:'.length)) } catch { throw new Error('preparation_status_unavailable') }
    if (reply.code !== 0 || page?.error) throw Object.assign(new Error('preparation_status_unavailable'), { backendError: page?.error })
    return page
  }
  let data
  try { data = await readPagedStatus(once) } catch { throw new Error('preparation_status_unavailable') }
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
  const once = async payload => {
    const response = await transport.requestProfile(route, 'cli.exec', {
      argv: ['--profile', route.targetProfile, 'model-router', operation, '--body', JSON.stringify(payload)],
      profile: route.targetProfile, timeout: 180
    }, 210000)
    const frames = String(response?.output || '').split(/\r?\n/).filter(line => line.startsWith('MODEL_ROUTER_JSON:'))
    if (!response || response.blocked || frames.length !== 1) throw new Error('initial_setup_reply_unavailable')
    const reply = JSON.parse(frames[0].slice('MODEL_ROUTER_JSON:'.length))
    if (response.code !== 0 || !reply || typeof reply !== 'object' || reply.error) throw Object.assign(new Error('initial_setup_reply_unavailable'), { backendError: reply?.error })
    return reply
  }
  if (operation !== 'status') return once(body)
  let data
  try { data = await readPagedStatus(once) } catch { throw new Error('initial_setup_reply_unavailable') }
  if (!data || !Array.isArray(data.profiles) || !validInitialContext(data.readiness_context)) throw new Error('initial_setup_status_unavailable')
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
    jsx('p', { style: styles.hint, children: '처음에는 다른 프로필 사용을 허용하지 않아 작업 슬롯의 모델 경로만 사용합니다. 전문 프로필 경로는 아래 모델 섹션의 ‘작업 모델’에서 사용 대상을 직접 허용한 뒤 이용할 수 있습니다.' }),
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
// The methods the page offers. Hermes's own 'default' delegation is no longer offered: a profile
// still stored on it is shown read-only (see NATIVE_DELEGATION_LEGACY_LABELS) and never rewritten.
export const NATIVE_DELEGATION_BACKENDS = freezeDeep([
  { value: 'model-router', label: '작업 종류에 맞는 슬롯 모델 사용' },
  { value: 'model-router-auto', label: '에이전트가 모델 / 전문 프로필 중 선택' },
  { value: 'model-router-profiles', label: '전문 프로필에 맡기기' }
])
export const NATIVE_DELEGATION_LEGACY_LABELS = freezeDeep({ default: '기본 위임 모델 사용 (이전 방식)' })
export const nativeBackendSelectable = backend => NATIVE_DELEGATION_BACKENDS.some(item => item.value === backend)

const nativeModelMode = backend => ['model-router', 'model-router-auto'].includes(backend)
const nativeProfileMode = backend => ['model-router-profiles', 'model-router-auto'].includes(backend)
const nativeEmptyPolicy = () => ({ heavy: { mode: 'off', chain: [] }, light: { mode: 'off', chain: [] } })
const nativeDraftPolicy = draft => draft.backend === 'model-router-auto' ? draft.autoPolicy : draft.policy
const nativeSlotPolicyKey = backend => backend === 'model-router-auto' ? 'autoSlotPolicy' : 'slotPolicy'
export const nativeDraftSlotPolicy = draft => draft?.[nativeSlotPolicyKey(draft?.backend)] || null
// Spare models are edited per slot only when the loaded profile's plugin stores them that way.
export const nativeSlotDraftReady = (draft, dto) => dto?.slot_policy_supported === true &&
  [draft?.slotPolicy, draft?.autoSlotPolicy].every(policy => policy && TASK_SLOTS.every(slot => policy[slot.id]))
const nativePolicyEntryError = policy => {
  if (!policy || !['off', 'custom'].includes(policy.mode) || !Array.isArray(policy.chain) ||
    (policy.mode === 'off' && policy.chain.length) || (policy.mode === 'custom' && (!policy.chain.length || policy.chain.length > 5))) return '예비 모델 목록을 확인하세요.'
  const seen = new Set()
  for (const route of policy.chain) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(route.provider || '') || !/^[A-Za-z0-9][A-Za-z0-9._:/-]*(?:\[[A-Za-z0-9._-]{1,32}\])?$/.test(route.model || '')) return '예비 모델의 제공자와 모델 ID를 정확히 입력하세요.'
    const key = `${route.provider.toLowerCase()}\0${route.model.toLowerCase()}`
    if (seen.has(key)) return '같은 예비 경로를 중복해서 넣을 수 없습니다.'
    seen.add(key)
  }
  return ''
}

export function copyNativeDelegationDraft(dto) {
  if (dto?.schema !== 1 || dto.supported !== true || typeof dto.digest !== 'string' ||
    typeof dto.backend !== 'string' || !dto.policy || !dto.profile_routes) return null
  return { backend: dto.backend, expectedDigest: dto.digest, policy: deepClone(dto.policy),
    autoPolicy: deepClone(dto.auto_policy || nativeEmptyPolicy()),
    ...(dto.slot_policy ? { slotPolicy: deepClone(dto.slot_policy) } : {}),
    ...(dto.auto_slot_policy ? { autoSlotPolicy: deepClone(dto.auto_slot_policy) } : {}),
    profile_routes: deepClone(dto.profile_routes), allowProfileAccess: false, descriptionEdits: {} }
}

// `part` limits the check to what an update carries: 'native' sends no allow-list (the stored one,
// which may still name a deleted profile, is left as it is), 'profiles' sends no spare policy.
export function nativeDelegationValidation(draft, profileNames, part = 'all') {
  if (!draft || !NATIVE_DELEGATION_BACKENDS.some(item => item.value === draft.backend)) return '작업을 맡기는 방식을 선택하세요.'
  if (part === 'profiles' || draft.sendPolicy === false) {
    // No spare policy in this update.
  } else if (draft.sendSlotPolicy === true) {
    for (const slot of TASK_SLOTS) {
      const issue = nativePolicyEntryError(nativeDraftSlotPolicy(draft)?.[slot.id])
      if (issue) return `${slot.label}: ${issue}`
    }
  } else {
    for (const role of ['heavy', 'light']) {
      const issue = nativePolicyEntryError(nativeDraftPolicy(draft)?.[role])
      if (issue) return issue
    }
  }
  if (part === 'native') return ''
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

// The part an update leaves out is kept by the writer exactly as stored, including a key that is
// absent: 'native' omits `profile_routes`; 'profiles' omits the spare policy; a 'native' update
// whose spare models are not on screen (`sendPolicy: false`) omits the policy as well.
export function buildNativeDelegationPreviewBody(revision, profile, draft, dto, profileNames, part = 'all') {
  const error = nativeDelegationValidation(draft, profileNames, part)
  if (error) throw new Error(error)
  if (draft.expectedDigest !== dto?.digest) throw new Error('다른 곳에서 작업 분담 설정이 바뀌었습니다. 입력 내용을 확인하고 상태를 다시 불러오세요.')
  if (dto?.editable !== true || dto.supported !== true || typeof dto.digest !== 'string') throw new Error('이 프로필의 작업 분담 설정은 현재 바꿀 수 없습니다.')
  const update = { profile, expected_digest: dto.digest, backend: draft.backend,
    allow_profile_access: part !== 'native' && draft.allowProfileAccess === true }
  if (part !== 'profiles' && draft.sendPolicy !== false) {
    // Exactly one policy shape per update: one entry per task slot, or the two stored roles.
    const bySlot = draft.sendSlotPolicy === true
    const policy = deepClone(bySlot ? nativeDraftSlotPolicy(draft) : nativeDraftPolicy(draft))
    update[bySlot ? 'slot_policy' : 'policy'] = policy
    update.allow_additional_cost = Object.values(policy).some(entry => entry.mode === 'custom')
  }
  if (part !== 'native') update.profile_routes = deepClone(draft.profile_routes)
  return { expected_revision: revision, updates: [update] }
}

export function copyNativeDelegationBaselines(profiles) {
  return Object.fromEntries((Array.isArray(profiles) ? profiles : [])
    .filter(row => typeof row?.name === 'string' && row.native_delegation?.schema === 1)
    .map(row => [row.name, deepClone(row.native_delegation)]))
}

// `origin` is the loaded profile of a model-section copy. Another profile stored on a method the page
// does not offer (Hermes 'default' or an advanced value) keeps it: only loading that profile and
// choosing a method there changes it.
export function nativeDelegationTargetReason(row, backend, slotCopy = false, origin = undefined) {
  if (!row || row.native_delegation?.supported !== true || row.native_delegation.editable !== true) return '이 프로필은 설정을 변경할 수 없습니다.'
  if (origin !== undefined && row.name !== origin && !nativeBackendSelectable(row.native_delegation.backend)) return `이 프로필은 ‘${nativeBackendLabel(row.native_delegation.backend)}’ 방식으로 저장되어 있어 그대로 둡니다. 바꾸려면 이 프로필을 불러와 방식을 고르세요.`
  if (backend === 'model-router-auto' && row.native_delegation.auto_supported !== true) return '설치된 플러그인이 모델 / 프로필 통합 선택을 지원하지 않습니다. 먼저 플러그인을 업데이트하세요.'
  // Effective routing needs BOTH switches on: the canonical flag and the routing skill's own switch
  // (skills.disabled). The service refuses the method for a profile with either one off.
  if (nativeModelMode(backend) && !routingEffectivelyOn(row)) return '이 프로필의 작업 분담이 꺼져 있습니다. 먼저 다시 켜서 저장하세요.'
  if (slotCopy && row.native_delegation.slot_policy_supported !== true) return '이 프로필의 플러그인은 슬롯별 예비 모델을 지원하지 않습니다. 먼저 업데이트하세요.'
  return ''
}

// Whether the operator changed anything one part saves, compared with what was loaded.
// 'native' is the model section's method and spare models, 'profiles' the profile delegation section.
const NATIVE_PART_KEYS = { native: ['backend', 'slotPolicy', 'autoSlotPolicy'], profiles: ['profile_routes'], all: ['backend', 'slotPolicy', 'autoSlotPolicy', 'profile_routes'] }
export function nativeDelegationDraftChanged(draft, dto, part = 'all') {
  const loaded = copyNativeDelegationDraft(dto)
  if (!draft || !loaded || !NATIVE_PART_KEYS[part]) return false
  return NATIVE_PART_KEYS[part].some(key => !sameValue(draft[key] ?? null, loaded[key] ?? null))
}

// Why a profile cannot take the profile delegation section's save: it saves only to profiles whose
// stored method already uses profiles, and it never changes that method.
export function nativeProfileTargetReason(row) {
  const stored = row?.native_delegation?.backend
  const issue = nativeDelegationTargetReason(row, stored)
  if (issue) return issue
  return nativeProfileMode(stored) ? '' : `이 프로필은 전문 프로필에 맡기는 방식이 아닙니다(현재: ${nativeBackendLabel(stored)}). 먼저 ‘모델’ 섹션에서 맡기는 방식을 바꿔 저장하세요.`
}

// One '/delegation-preview' body for one part of the shared draft. `part` decides which fields
// come from the draft; every other field is each target's own stored (baseline) value:
//  'native'   - method and spare models from the draft, each target keeps its stored profile access;
//  'profiles' - allow-list, descriptions and consent from the draft, each target keeps its stored
//               method and spare models (only profiles already on a profile method can take it);
//  'all'      - the earlier one-card save, kept for compatibility.
export function buildNativeDelegationBatchBody(revision, origin, targets, draft, baselines, profiles, part = 'all') {
  const rows = Array.isArray(profiles) ? profiles : []
  const names = rows.map(row => row.name)
  if (!['native', 'profiles', 'all'].includes(part)) throw new Error('저장 범위를 확인할 수 없습니다.')
  if (!Array.isArray(targets) || targets.length < 1 || targets.length > 32 || uniqueProfileNames(targets).length !== targets.length) throw new Error('적용할 프로필을 1개 이상, 최대 32개까지 선택하세요.')
  if (!draft || (part !== 'profiles' && !nativeBackendSelectable(draft.backend))) throw new Error('작업을 맡기는 방식을 선택하세요.')
  const source = rows.find(row => row.name === origin)?.native_delegation
  if (source?.supported !== true || source.editable !== true || !baselines?.[origin] ||
      source.digest !== baselines[origin].digest || draft.expectedDigest !== baselines[origin].digest) throw new Error('불러온 프로필의 설정이 바뀌었습니다. 입력한 내용을 확인하고 상태를 다시 불러오세요.')
  if (part === 'profiles' && !nativeProfileMode(source.backend)) throw new Error('불러온 프로필은 전문 프로필에 맡기는 방식이 아닙니다. 먼저 ‘모델’ 섹션에서 맡기는 방식을 저장하세요.')
  return { expected_revision: revision, updates: targets.map(name => {
    const row = rows.find(item => item.name === name)
    const baseline = baselines[name]
    const backend = part === 'profiles' ? baseline?.backend : draft.backend
    // Spare models are visible only as slot entries in a model mode on a slot-capable loaded
    // profile; in every other case each target keeps its own stored policy in its stored shape.
    const copySlots = part !== 'profiles' && nativeModelMode(draft.backend) && nativeSlotDraftReady(draft, source)
    const issue = part === 'profiles' ? nativeProfileTargetReason(row)
      : nativeDelegationTargetReason(row, draft.backend, copySlots, part === 'native' ? origin : undefined)
    if (issue) throw new Error(`${name}: ${issue}`)
    if (!baseline || baseline.supported !== true || baseline.editable !== true || baseline.digest !== row.native_delegation.digest) throw new Error(`${name}의 설정이 바뀌었습니다. 상태를 다시 불러온 뒤 저장하세요.`)
    // Copy visible fields only. A mode change must never overwrite hidden permissions/policies.
    const storedBySlot = (backend === 'model-router-auto' ? baseline.auto_policy_schema : baseline.policy_schema) === 2
    const routesFromDraft = part === 'profiles' || (part === 'all' && nativeProfileMode(draft.backend))
    const next = { ...deepClone(draft), backend, expectedDigest: baseline.digest,
      // Only the 'native' part with slot cards on screen carries spare models; otherwise the
      // stored policy (or its absence) is left to the writer untouched.
      sendPolicy: part === 'all' || copySlots,
      sendSlotPolicy: copySlots || storedBySlot,
      policy: deepClone(baseline.policy),
      autoPolicy: deepClone(baseline.auto_policy || nativeEmptyPolicy()),
      slotPolicy: deepClone(copySlots && draft.backend === 'model-router' ? draft.slotPolicy : baseline.slot_policy || null),
      autoSlotPolicy: deepClone(copySlots && draft.backend === 'model-router-auto' ? draft.autoSlotPolicy : baseline.auto_slot_policy || null),
      profile_routes: deepClone(routesFromDraft ? draft.profile_routes : baseline.profile_routes),
      allowProfileAccess: routesFromDraft && draft.allowProfileAccess === true }
    if (routesFromDraft && draft.descriptionEdits) {
      next.profile_routes.profiles = next.profile_routes.profiles.map(entry => ({ ...entry, description: draft.descriptionEdits[entry.name] === true
        ? entry.description : baseline.profile_routes.profiles.find(old => old.name === entry.name)?.description ?? '' }))
    }
    if (routesFromDraft) {
      const inheritanceIssue = profileRoleInheritanceIssue(next.profile_routes, baseline.profile_routes, row.native_delegation)
      if (inheritanceIssue) throw new Error(`${name}: ${inheritanceIssue}`)
    }
    // The default profile is edited only on a profile-only source ('model-router-profiles'), and only
    // a profile-only target uses it. Otherwise each target keeps its stored default unless that
    // profile left the allow-list.
    const defaultEdited = part === 'profiles' ? source.backend === 'model-router-profiles' : true
    if (routesFromDraft && (backend === 'model-router-auto' || !defaultEdited)) {
      next.profile_routes.default = next.profile_routes.profiles.some(item => item.name === baseline.profile_routes.default) ? baseline.profile_routes.default : null
    }
    if (routesFromDraft) {
      const beforeNames = new Set(baseline.profile_routes.profiles.map(item => item.name))
      const addsAccess = next.profile_routes.profiles.some(item => !beforeNames.has(item.name)) ||
        (next.profile_routes.default !== null && next.profile_routes.default !== baseline.profile_routes.default)
      if (addsAccess && !next.allowProfileAccess) throw new Error('허용할 프로필의 계정과 기능을 확인한 뒤, 아래 사용 허용에 체크하세요.')
    }
    return buildNativeDelegationPreviewBody(revision, name, next, row.native_delegation, names, part).updates[0]
  }) }
}

export function nativeDelegationSnapshotCurrent(snapshot, status) {
  if (status?.revision !== snapshot.revision) return false
  try {
    buildNativeDelegationBatchBody(snapshot.revision, snapshot.profile, snapshot.nativeTargets,
      snapshot.nativeDraft, snapshot.nativeBaselines, status.profiles, snapshot.nativePart || 'all')
    return true
  } catch { return false }
}

// Which unsaved edits the submitted request bodies saved, field by field. `view` holds the drafted
// value of every edit at the start of the save; `sent` lists each body that was previewed and applied
// ({ operation, part, body }). An edit counts as saved only when the request wrote the drafted value
// to every target it wrote that field to, and to at least one (the default profile, kept per target,
// also counts when the loaded profile received it). Anything else stays unsaved, so the page is not
// reloaded over it.
export function submittedEditCoverage(view, sent) {
  const covered = new Set()
  const every = (list, test) => Array.isArray(list) && list.length > 0 && list.every(test)
  const routeNames = routes => (routes?.profiles || []).map(entry => entry?.name)
  for (const { operation, part, body } of Array.isArray(sent) ? sent : []) {
    if (!body || typeof body !== 'object') continue
    if (operation === '/preview') {
      const scope = body.save_scope ?? null
      if ((scope === null || scope === 'models') && Array.isArray(body.model_targets) && body.model_targets.length) {
        covered.add('copy.models')
        if (sameValue(body.models, view.models)) covered.add('models')
      }
      if ((scope === null || scope === 'routing') && body.routing) {
        const routingTargets = Array.isArray(body.routing_targets) ? body.routing_targets : [body.profile]
        if (routingTargets.length) {
          if (sameValue(body.routing.heavy, view.routing?.heavy) && sameValue(body.routing.light, view.routing?.light)) covered.add('routing.roles')
          if (Object.prototype.hasOwnProperty.call(body.routing, 'slots')) {
            covered.add('copy.slots')
            if (sameValue(body.routing.slots ?? null, view.slots ?? null)) covered.add('routing.slots')
          }
        }
        // Saved only by a request that names it as an explicit re-enable (membership alone is not).
        if ((view.reenable || []).every(name => Array.isArray(body.reenable_profiles) && body.reenable_profiles.includes(name))) covered.add('reenable')
      }
      if (Array.isArray(body.timeout_updates) && body.timeout_updates.length) covered.add('timeouts')
      const fallbackUpdates = (body.fallback_updates || []).filter(update => Object.prototype.hasOwnProperty.call(update, 'native_fallback'))
      if (every(fallbackUpdates, update => sameValue(update.native_fallback, view.nativeFallback))) covered.add('fallback:native')
    } else if (operation === '/fallback-preview') {
      const updates = body.updates
      if (every(updates, update => Object.prototype.hasOwnProperty.call(update, 'native_fallback') && sameValue(update.native_fallback, view.nativeFallback))) covered.add('fallback:native')
    } else if (operation === '/delegation-preview' && view.native) {
      const updates = body.updates
      if (part === 'native') {
        if (every(updates, update => update.backend === view.native.backend)) { covered.add('native.backend'); covered.add('native.copy') }
        if (every(updates, update => update.backend === 'model-router' && sameValue(update.slot_policy, view.native.slotPolicy))) covered.add('native.slotPolicy')
        if (every(updates, update => update.backend === 'model-router-auto' && sameValue(update.slot_policy, view.native.autoSlotPolicy))) covered.add('native.autoSlotPolicy')
      } else if (part === 'profiles') {
        const drafted = view.native.profile_routes || { profiles: [], default: null }
        if (every(updates, update => update.profile_routes)) covered.add('profiles.targets')
        if (every(updates, update => sameValue(routeNames(update.profile_routes), routeNames(drafted)) &&
          drafted.profiles.every(entry => (update.profile !== view.profile && view.native.descriptionEdits?.[entry.name] !== true) ||
            update.profile_routes.profiles.find(item => item.name === entry.name)?.description === entry.description))) covered.add('profiles.list')
        // The default is kept per target unless the source edits it; it is saved when the loaded
        // profile itself received the drafted value, or every target did.
        const takesDefault = update => update.profile_routes && (update.profile_routes.default ?? null) === (drafted.default ?? null)
        if ((Array.isArray(updates) && updates.some(update => update.profile === view.profile && takesDefault(update))) || every(updates, takesDefault)) covered.add('profiles.default')
      }
    }
  }
  return covered
}

export function nativePrimaryModel(row, role) {
  const declaration = row?.routing?.[role]
  const route = declaration?.follow === 'custom' ? declaration.custom : row?.models?.[role === 'heavy' ? 'main' : 'delegation']
  return route && typeof route.model === 'string' && route.model ? route : null
}

const nativeBackendLabel = value => NATIVE_DELEGATION_BACKENDS.find(item => item.value === value)?.label || NATIVE_DELEGATION_LEGACY_LABELS[value] || '별도 고급 설정'
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
  unsupported_sdk: '현재 Hermes에서 역할 제안을 지원하지 않습니다.',
  payer_unavailable: '연결 프로필의 기본 모델 경로를 확인할 수 없어 역할 제안을 보내지 않습니다. 기본 제공자를 사용하거나 엔드포인트·키를 직접 덮어쓴 설정이 없는지 확인하세요.'
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
    typeof value.source?.native_description === 'string' && typeof value.source?.soul_text === 'string' &&
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
      payer.transport === 'user_process' ? jsx('p', { style: styles.hint, children: '직접 설치한 제공자(외부 프로세스)로 실행합니다. 이 프로필의 대화가 쓰는 경로와 같습니다.' }) : null,
      jsx('p', { style: styles.hint, children: `기존 예비 모델: ${(payer.fallback_policy || []).map(row => `${row.provider} / ${row.model}`).join(' → ') || '없음'}` }),
      jsx('p', { style: styles.hint, children: '이 요청에는 해당 프로필의 기존 Hermes 복구 정책이 적용됩니다. 연결 실패나 인증 갱신 등으로 다시 시도하거나 예비 모델을 사용할 수 있으며, 사용량·비용이 발생할 수 있습니다. 금액은 미리 확정할 수 없습니다.' })
    ] }) : null,
    sources ? jsxs('details', { open: true, children: [
      jsx('summary', { children: '모델에 보낼 역할 자료 확인' }),
      jsx('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '13rem', overflowY: 'auto', font: 'inherit', fontSize: '0.8rem', padding: '0.75rem', border: '1px solid var(--ui-stroke-tertiary)', borderRadius: '0.5rem' }, children: JSON.stringify({ '프로필 소개': sources.native_description, '활성 스킬 이름': sources.enabled_skill_names }, null, 2) }),
      sources.soul_text ? jsxs('details', { 'data-model-router-soul': '', children: [
        jsx('summary', { children: `SOUL 문서 전체 (${sources.soul_text.length.toLocaleString('ko-KR')}자) — 펼쳐서 확인` }),
        jsx('pre', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '18rem', overflowY: 'auto', font: 'inherit', fontSize: '0.8rem', padding: '0.75rem', border: '1px solid var(--ui-stroke-tertiary)', borderRadius: '0.5rem' }, children: sources.soul_text })
      ] }) : jsx('p', { style: styles.hint, children: 'SOUL 문서: 보내지 않음' }),
      jsx('p', { style: styles.hint, children: `자료 제외: ${(sources.omitted_sources || []).map(code => ({ external_skills_omitted: '외부 스킬', skills_unavailable: '확인할 수 없는 스킬 목록', soul_sensitive: '자격 증명 형태가 있는 SOUL', soul_too_large: '너무 큰 SOUL', deep_skills_omitted: '깊은 스킬 경로', linked_skills_omitted: '연결된 스킬 폴더' })[code] || '일부 자료').join(', ') || '없음'} · 자료 축약: ${sources.truncated ? '있음' : '없음'} · 출력 요청 상한: ${Number.isSafeInteger(context?.limits?.max_output_tokens) ? context.limits.max_output_tokens : '확인 불가'} 토큰` }),
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

function NativeDelegationCard({ dto, draft, targets, disabled, onChange, catalog = null, slots }) {
  const stale = Boolean(draft && draft.expectedDigest !== dto?.digest)
  const locked = disabled || dto?.editable !== true || !draft || stale
  const selected = Array.isArray(targets) ? targets : []
  const spareReady = nativeSlotDraftReady(draft, dto)
  const updateSparePolicy = (slot, updater) => onChange(current => {
    const key = nativeSlotPolicyKey(current.backend)
    return { ...current, [key]: { ...current[key], [slot]: updater(current[key][slot]) } }
  })
  // A stored method the page no longer offers is shown as the current value only: its item is
  // disabled and a pick of it is ignored. Going back to it is the explicit revert button below.
  const unlisted = [...new Set([dto?.backend, draft?.backend])].filter(value => typeof value === 'string' && !nativeBackendSelectable(value))
  const backendOptions = [...unlisted.map(value => ({ value, label: NATIVE_DELEGATION_LEGACY_LABELS[value] || '현재 별도 고급 설정', disabled: true })), ...NATIVE_DELEGATION_BACKENDS]
  const canRevertBackend = Boolean(draft && typeof dto?.backend === 'string' && !nativeBackendSelectable(dto.backend) && draft.backend !== dto.backend)
  const otherWarnings = Array.isArray(dto?.warnings) ? dto.warnings.filter(code => code !== 'profile_target_missing_remove_from_allowlist') : []
  const slotCard = slot => {
    const declaration = slots.draft[slot.id]
    if (!declaration) return null  // a draft seeded from an incomplete status shows no card rather than failing the page
    const resolved = slotResolvedRoute(declaration, slots.models)
    const coder = slot.id === 'verify-complex' ? slotResolvedRoute(slots.draft['code-complex'], slots.models) : null
    const sameAsCoder = Boolean(coder && resolved && coder.model && coder.provider === resolved.provider && coder.model === resolved.model)
    const primaryLocked = slots.disabled || !slots.support.editable
    const spare = spareReady ? nativeDraftSlotPolicy(draft)[slot.id] : null
    return jsxs('article', { id: `slot-${slot.id}`, style: { ...styles.roleCard, gap: '0.9rem' }, children: [
      jsxs('div', { children: [
        jsxs('div', { style: styles.statusLine, children: [
          jsx('h3', { style: styles.roleTitle, children: slot.label }),
          jsx(Badge, { variant: 'muted', children: slot.tier === 'heavy' ? '긴 작업 제한' : '짧은 작업 제한' })
        ] }),
        jsx('p', { style: { ...styles.hint, marginTop: '0.25rem' }, children: slot.description })
      ] }),
      jsx(ChoiceField, { id: `slot-${slot.id}-follow`, label: '기본 모델', value: declaration.follow, disabled: primaryLocked, options: SLOT_FOLLOW_OPTIONS, onChange: follow => slots.onFollow(slot.id, follow) }),
      declaration.follow === 'custom'
        ? jsx(ModelRouteField, {
          ids: { picker: `slot-${slot.id}-picker`, provider: `slot-${slot.id}-provider`, model: `slot-${slot.id}-model`, reasoning: `slot-${slot.id}-reasoning` },
          labels: { picker: '모델', provider: '공급자 ID', model: '모델 ID' },
          route: declaration.custom, disabled: primaryLocked, catalog, withReasoning: true,
          onChange: (field, value) => slots.onRoute(slot.id, field, value) })
        : jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.25rem', minWidth: 0 }, children: [
          jsx('strong', { id: `slot-${slot.id}-resolved`, style: { overflowWrap: 'anywhere', fontSize: '0.95rem' }, children: resolved?.model || '모델이 설정되지 않았습니다.' }),
          resolved?.model ? jsx('span', { style: styles.hint, children: `연결된 서비스: ${resolved.provider || '—'} · 추론 강도: ${resolved.reasoning || '—'}` }) : null
        ] }),
      sameAsCoder ? jsx('p', { id: 'slot-verify-same-model-note', role: 'note', style: styles.hint, children: '‘코드 · 복잡’과 같은 모델입니다. 같은 모델이 하는 검수는 다른 모델이 하는 검수와 같지 않습니다.' }) : null,
      spare ? jsxs('div', { style: { borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '0.9rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }, children: [
        jsx(ChoiceField, { id: `slot-${slot.id}-fallback-mode`, label: '이 모델을 쓸 수 없을 때', value: spare.mode, disabled: locked,
          options: [{ value: 'off', label: '다른 모델로 전환하지 않음' }, { value: 'custom', label: '예비 모델로 이어가기' }],
          onChange: mode => updateSparePolicy(slot.id, current => ({ mode, chain: mode === 'off' ? [] : current.chain.length ? current.chain : [{ provider: '', model: '' }] })) }),
        ...spare.chain.map((route, index) => jsxs('div', { style: { ...styles.modelRoute, alignItems: 'stretch' }, children: [
          jsx(ModelRouteField, {
            ids: { picker: `slot-${slot.id}-spare-picker-${index}`, provider: `slot-${slot.id}-spare-provider-${index}`, model: `slot-${slot.id}-spare-model-${index}` },
            labels: { picker: `예비 ${index + 1} 모델`, provider: `예비 ${index + 1} 제공자`, model: `예비 ${index + 1} 모델 ID` },
            route, disabled: locked, catalog,
            onChange: (field, value) => updateSparePolicy(slot.id, current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, [field]: value } : item) })) }),
          jsx(Button, { id: `slot-${slot.id}-spare-remove-${index}`, size: 'sm', variant: 'secondary', style: { alignSelf: 'flex-start' }, disabled: locked, onClick: () => updateSparePolicy(slot.id, current => ({ ...current, chain: current.chain.filter((_, at) => at !== index) })), children: '이 예비 모델 삭제' })
        ] }, `${slot.id}-${index}`)),
        spare.mode === 'custom' ? jsx(Button, { id: `slot-${slot.id}-fallback-add`, size: 'sm', variant: 'secondary', style: { alignSelf: 'flex-start' }, disabled: locked || spare.chain.length >= 5,
          onClick: () => updateSparePolicy(slot.id, current => ({ ...current, chain: [...current.chain, { provider: '', model: '' }] })), children: '예비 모델 추가' }) : null
      ] }) : null
    ] }, slot.id)
  }
  return jsxs('div', { id: 'native-delegation-settings', style: { display: 'flex', flexDirection: 'column', gap: '0.9rem', minWidth: 0 }, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '작업 모델' }), jsx(Badge, { variant: 'muted', style: { maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere' }, children: `저장된 방식: ${nativeBackendLabel(dto?.backend)}` })] }),
    jsx('p', { style: styles.hint, children: '간단한 작업은 메인 모델이 직접 처리합니다. 나눠 맡기는 편이 유리한 작업만 아래 방식으로 맡기며, 저장한 내용은 새 대화부터 적용됩니다. 진행 중인 대화나 작업은 중단하지 않습니다.' }),
    stale ? jsx('p', { role: 'alert', style: styles.warning, children: '다른 곳에서 설정이 바뀌었습니다. 입력한 내용은 남겨 두었으니 상태를 다시 불러온 뒤 저장하세요.' }) : null,
    !draft ? jsx('p', { role: 'note', style: styles.warning, children: '이 기능의 설정을 불러오지 못했습니다. Hermes와 플러그인 설치 상태를 확인한 뒤 다시 불러오세요. 기존 값은 바꾸지 않습니다.' }) : jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [
      jsx(ChoiceField, { id: 'native-delegation-backend', label: '작업을 맡기는 방식', value: draft.backend, disabled: locked,
        options: backendOptions,
        onChange: backend => { if (nativeBackendSelectable(backend)) onChange(current => ({ ...current, backend })) } }),
      canRevertBackend ? jsx(Button, { id: 'native-backend-revert', size: 'sm', variant: 'secondary', style: { alignSelf: 'flex-start', whiteSpace: 'normal', height: 'auto', minHeight: '2rem' }, disabled: locked,
        onClick: () => onChange(current => ({ ...current, backend: dto.backend })), children: `저장된 방식(${nativeBackendLabel(dto.backend)})으로 되돌리기` }) : null,
      draft.backend === 'model-router-auto' ? jsx('p', { id: 'native-auto-explanation', role: 'note', style: styles.hint, children: '같은 대화에서 에이전트가 작업마다 아래 작업 슬롯의 모델 또는 허용한 전문 프로필을 고릅니다. 전문 프로필은 그 프로필의 기존 기본 모델·추론 설정을 사용하며 슬롯 모델을 쓰지 않습니다. 필수 검수는 슬롯 모델로 수행합니다. 이 방식의 예비 모델은 모델 전용 방식과 따로 저장됩니다.' }) : null,
      draft.backend === 'default' ? jsx('p', { id: 'native-default-explanation', role: 'note', style: styles.warning, children: '이 프로필은 이전의 ‘기본 위임 모델 사용’ 방식으로 저장되어 있습니다. 이 방식은 더 이상 고를 수 없지만, 저장된 값은 그대로 두며 맡기는 작업도 지금처럼 위의 ‘작업 위임’ 모델을 사용합니다. 작업 종류별 슬롯이나 전문 프로필을 쓰려면 위에서 다른 방식을 고른 뒤 저장하세요. 적용 대상을 넓혀 저장해도 이 방식은 다른 프로필에 복사하지 않습니다.' }) : null,
      !nativeBackendSelectable(draft.backend) && draft.backend !== 'default' ? jsx('p', { id: 'native-unlisted-explanation', role: 'note', style: styles.hint, children: '이 프로필에는 이 화면에서 다루지 않는 방식이 저장되어 있습니다. 저장된 값은 그대로 두며, 적용 대상을 넓혀 저장해도 다른 프로필에 복사하지 않습니다. 바꾸려면 위에서 방식을 고른 뒤 저장하세요.' }) : null,
      nativeModelMode(draft.backend) ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
        jsx('p', { style: styles.hint, children: '에이전트가 작업 종류에 맞는 슬롯을 고르고, 각 슬롯은 아래에서 정한 모델로 실행합니다. 코드뿐 아니라 복잡한 조사·문서 작업도 같은 슬롯으로 맡기며, 단순 글쓰기·번역·요약은 맡기지 않고 메인 모델이 처리합니다. 슬롯마다 다른 모델을 지정할 수 있고, 다른 프로필에는 적용 대상으로 고른 경우에만 복사합니다.' }),
        !slots.support.available ? jsx('p', { id: 'slot-update-note', role: 'note', style: styles.warning, children: '이 프로필에 설치된 플러그인은 작업 슬롯을 지원하지 않습니다. 플러그인을 업데이트하면 슬롯별 모델과 예비 모델을 설정할 수 있습니다. 지금 저장해도 기존 모델과 예비 모델 설정은 그대로 유지합니다.' }) : null,
        slots.support.available && !slots.support.editable ? jsx('p', { id: 'slot-blocked-note', role: 'note', style: styles.warning, children: `다음 프로필의 플러그인을 먼저 업데이트해야 슬롯별 모델을 저장할 수 있습니다: ${slots.support.blocking.join(', ')}. 그때까지 아래 기본 모델은 읽기 전용입니다.` }) : null,
        slots.support.available && !spareReady ? jsx('p', { id: 'slot-spare-update-note', role: 'note', style: styles.hint, children: '슬롯별 예비 모델은 이 프로필의 플러그인을 업데이트한 뒤 설정할 수 있습니다.' }) : null,
        slots.support.available && slots.support.editable && slots.firstSave ? jsx('p', { id: 'slot-first-save-note', role: 'note', style: styles.warning, children: '슬롯 설정을 처음 저장하기 전에: 플러그인을 업데이트한 뒤 다시 시작하지 않은 Hermes 창이나 게이트웨이가 있으면 먼저 다시 시작하세요. 이전 버전으로 실행 중인 곳은 슬롯 설정을 읽지 못해, 다시 시작할 때까지 맡긴 작업을 거절합니다.' }) : null,
        slots.support.available && slots.draft ? jsx('div', { style: styles.roleGrid, children: TASK_SLOTS.map(slotCard) }) : null,
        spareReady && TASK_SLOTS.some(slot => nativeDraftSlotPolicy(draft)[slot.id].mode === 'custom') ? jsx('p', { id: 'slot-spare-cost-note', role: 'note', style: styles.warning, children: `예비 모델을 저장하면 선택한 ${selected.length}개 프로필에서 필요할 때 그 모델로 이어서 실행합니다. 제공자의 요금제에 따라 사용량이나 비용이 늘 수 있습니다.` }) : null
      ] }) : null,

      otherWarnings.length ? jsx('p', { style: styles.warning, children: '이 설정을 변경할 수 있는지 확인이 필요합니다. 설치 상태를 확인한 뒤 다시 불러오세요.' }) : null,
    ] })
  ] })
}

// The profile delegation section: which specialist profiles the agent may hand work to, their
// per-delegation descriptions and the account-use consent. It edits only `profile_routes` and
// consent in the shared draft, and it is editable only while the loaded profile's stored method
// already uses profiles; otherwise it shows the stored allow-list read-only.
function ProfileDelegationCard({ dto, draft, profiles, origin, targets, disabled, onChange, roleScope }) {
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
          liveScope !== value.roleScope?.scopeKey || !entry || !nativeProfileMode(value.dto?.backend) }
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
  const profileSettings = draft?.profile_routes
  const configured = profileSettings?.profiles || []
  const setProfile = (name, checked) => onChange(current => {
    const profiles = checked ? [...current.profile_routes.profiles, { name, description: dto?.profile_routes?.profiles.find(entry => entry.name === name)?.description ?? '' }] : current.profile_routes.profiles.filter(entry => entry.name !== name)
    return { ...current, allowProfileAccess: false, profile_routes: { profiles, default: profiles.some(entry => entry.name === current.profile_routes.default) ? current.profile_routes.default : null } }
  })
  return jsxs('div', { id: 'profile-delegation-settings', style: { display: 'flex', flexDirection: 'column', gap: '0.9rem', minWidth: 0 }, children: [
    stale ? jsx('p', { role: 'alert', style: styles.warning, children: '다른 곳에서 설정이 바뀌었습니다. 입력한 내용은 남겨 두었으니 상태를 다시 불러온 뒤 저장하세요.' }) : null,
    jsx(RoleProposalDialog, { view: rolePreview, onCancel: () => roleController.current.cancel(), onGenerate: () => void roleController.current.generate(), onUse: () => void roleController.current.use() }),
    !draft ? jsx('p', { role: 'note', style: styles.warning, children: '이 기능의 설정을 불러오지 못했습니다. Hermes와 플러그인 설치 상태를 확인한 뒤 다시 불러오세요. 기존 값은 바꾸지 않습니다.' })
    : !nativeProfileMode(dto?.backend) ? jsxs('div', { id: 'profile-delegation-readonly', role: 'note', style: { ...styles.cardSection, display: 'flex', flexDirection: 'column', gap: '0.45rem', overflowWrap: 'anywhere' }, children: [
      jsx('p', { style: { ...styles.hint, margin: 0 }, children: `불러온 프로필(${origin || '선택 안 됨'})은 전문 프로필에 맡기는 방식을 쓰지 않습니다. 현재 방식: ${nativeBackendLabel(dto?.backend)}.` }),
      jsx('p', { style: { ...styles.hint, margin: 0 }, children: '위 ‘모델’ 섹션의 ‘작업을 맡기는 방식’에서 ‘전문 프로필에 맡기기’나 ‘에이전트가 모델 / 전문 프로필 중 선택’을 골라 저장하면, 여기서 맡길 수 있는 프로필을 정할 수 있습니다.' }),
      jsx('p', { style: { ...styles.hint, margin: 0 }, children: `저장된 허용 프로필: ${(dto?.profile_routes?.profiles || []).map(entry => entry.name).join(', ') || '없음'} · 이 값은 바꾸지 않습니다.` })
    ] })
    : jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' }, children: [
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
        dto.backend === 'model-router-profiles' ? jsx(ChoiceField, { id: 'native-profile-default', label: '맡길 프로필을 따로 고르지 않으면', value: profileSettings.default || '__parent__', disabled: locked,
          options: [{ value: '__parent__', label: '현재 대화의 모델 사용' }, ...configured.map(entry => ({ value: entry.name, label: entry.name }))],
          onChange: value => onChange(current => ({ ...current, allowProfileAccess: false, profile_routes: { ...current.profile_routes, default: value === '__parent__' ? null : value } })) }) : jsx('p', { style: styles.hint, children: '통합 방식에서는 맡길 프로필을 작업마다 명시적으로 선택합니다. 기존 프로필 전용 방식의 기본 대상은 유지하며, 그 대상을 허용 목록에서 제거하면 기본 선택도 해제됩니다. 허용 프로필이 없으면 모델 경로만 사용할 수 있습니다.' }),
        jsx(CheckRow, { id: 'native-profile-access-consent', label: `선택한 ${selected.length}개 저장 대상에서 위 프로필의 계정과 기능 사용을 허용합니다`, detail: '허용 대상을 새로 추가하거나 기본 프로필을 바꿀 때 필요합니다. 새로 만드는 프로필은 자동으로 허용되지 않습니다.', checked: draft.allowProfileAccess, disabled: locked,
          onChange: checked => onChange(current => ({ ...current, allowProfileAccess: checked })) })
    ] }),
    Array.isArray(dto?.warnings) && dto.warnings.includes('profile_target_missing_remove_from_allowlist') ? jsx('p', { style: styles.warning, children: '허용 목록에 더 이상 없는 프로필이 있습니다. 목록을 확인하고 제거하세요.' }) : null
  ] })
}

export async function nativeBackendCall(path, options = {}) {
  // The status of many profiles does not fit one CLI reply; it is read in pages.
  if (path === '/status' && !options.body) return readPagedStatus(body => nativeBackendCallOnce(path, { ...options, body }))
  return nativeBackendCallOnce(path, options)
}

async function nativeBackendCallOnce(path, options = {}) {
  const operation = { '/status': 'status', '/preview': 'preview', '/fallback-preview': 'fallback-preview', '/delegation-preview': 'delegation-preview', '/initial-setup-preview': 'initial-setup-preview', '/apply': 'apply' }[path]
  if (!operation) throw new Error('지원하지 않는 플러그인 요청입니다.')
  const profile = options.profile || host.state.profile.get() || 'default'
  const params = (name, body) => ({ argv: ['--profile', profile, 'model-router', name, '--body', JSON.stringify(body)], profile, timeout: 180 })
  let exec = (name, body) => host.request('cli.exec', params(name, body), 210000)
  let body = options.body || {}
  const text = JSON.stringify(body)
  if (text.length > CLI_BODY_INLINE_LIMIT && STAGED_OPERATIONS.has(operation)) {
    // Every piece and the final request go to the one gateway that was live when the transfer
    // started (host.request re-resolves the live socket per call); a switch aborts the transfer.
    const pinned = typeof host.getGateway === 'function' ? host.getGateway() : null
    const connection = host.state?.connectionId?.get?.(), activeProfile = host.state.profile.get()
    if (!pinned || typeof pinned.request !== 'function') throw new Error('현재 연결을 확인할 수 없어 저장 내용을 전달하지 않았습니다. 설정은 변경되지 않았습니다.')
    exec = (name, body) => {
      if (host.getGateway() !== pinned || host.state?.connectionId?.get?.() !== connection || host.state.profile.get() !== activeProfile) {
        return Promise.reject(new Error('저장 도중 연결 또는 프로필이 바뀌어 전달을 멈췄습니다. 설정은 변경되지 않았습니다.'))
      }
      return pinned.request('cli.exec', params(name, body), 210000)
    }
    const id = stageId(), chunks = stagedBodyChunks(text)
    if (chunks.length > STAGED_MAX_CHUNKS) throw new Error('한 번에 저장하기에는 내용이 너무 큽니다. 적용 대상 프로필을 줄여 여러 번에 나눠 저장하세요.')
    for (const [index, chunk] of chunks.entries()) {
      const staged = await exec('stage', { id, index, total: chunks.length, chunk })
      const frame = String(staged?.output || '').split(/\r?\n/).find(value => value.startsWith('MODEL_ROUTER_JSON:'))
      let ok = false
      try { ok = !staged?.blocked && staged.code === 0 && JSON.parse(frame.slice('MODEL_ROUTER_JSON:'.length))?.staged === true } catch {}
      if (!ok) throw new Error('저장 내용을 전달하지 못했습니다. 설정은 변경되지 않았습니다.')
    }
    body = { staged: { id, total: chunks.length, length: text.length } }
  }
  const reply = await exec(operation, body)
  if (reply.blocked) throw new Error(reply.hint || '요청이 차단되었습니다.')
  const line = String(reply.output || '').split(/\r?\n/).find(value => value.startsWith('MODEL_ROUTER_JSON:'))
  if (!line) throw new Error('플러그인 응답을 확인할 수 없습니다. 활성화 상태를 확인하세요.')
  let data
  try { data = JSON.parse(line.slice('MODEL_ROUTER_JSON:'.length)) }
  catch { throw new Error('플러그인 응답이 잘렸거나 손상됐습니다. 상태를 다시 확인하세요.') }
  if (reply.code !== 0 || data.error) throw Object.assign(new Error(data.message || '요청이 완료되지 않았습니다.'), { backendError: data.error, conflict: data.conflict })
  return data
}

// cli.exec passes --body as one Windows command-line argument (32,767 characters with escaping).
// Larger settings bodies go in pieces through the plugin's `stage` operation.
export const CLI_BODY_INLINE_LIMIT = 12000
const STAGED_OPERATIONS = new Set(['preview', 'fallback-preview', 'delegation-preview', 'initial-setup-preview'])
const STAGED_MAX_CHUNKS = 128
export function stagedBodyChunks(text, size = 8000) {
  const chunks = []
  let start = 0
  while (start < text.length) {
    let end = Math.min(text.length, start + size)
    // Never split a surrogate pair: each piece must be well-formed text on its own.
    if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end -= 1
    // Keep each piece's own JSON encoding (quotes and backslashes doubled) under the inline limit.
    while (JSON.stringify(text.slice(start, end)).length > 11000 && end - start > 1) {
      end = start + Math.floor((end - start) / 2)
      if (/[\uD800-\uDBFF]/.test(text[end - 1])) end -= 1
    }
    chunks.push(text.slice(start, end))
    start = end
  }
  return chunks
}
function stageId() {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')
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
  // The profile delegation section's own target list and copy intent (see the model section's pair).
  const [profileDelegationTargets, setProfileDelegationTargets] = useState([])
  const [profileTargetEdited, setProfileTargetEdited] = useState(false)
  // Profile-save targets the fresh pre-apply status no longer listed, while the cached page data still
  // does; they block that save like any other vanished target until unticked or a full reload.
  const [freshMissingProfileTargets, setFreshMissingProfileTargets] = useState([])
  const profileTargetsManualRef = useRef(false)
  const nativeTargetsManualRef = useRef(false)
  const [nativeRecoveryConfirmed, setNativeRecoveryConfirmed] = useState(false)
  const [timeoutBaseline, setTimeoutBaseline] = useState(null)
  const [timeoutTargets, setTimeoutTargets] = useState(null)
  const [timeoutTargetEdited, setTimeoutTargetEdited] = useState(false)
  const [profileBaselines, setProfileBaselines] = useState(null)
  // Per profile, the status values a store save may overwrite, frozen when first seen (`expected`).
  const [expectationBaselines, setExpectationBaselines] = useState(null)
  // A compare-and-set refusal from the service: blocks saving until a reload.
  const [serverConflict, setServerConflict] = useState(null)
  const serverConflictRef = useRef(null)
  const [sectionErrors, setSectionErrors] = useState({ models: '', routing: '', timeouts: '', profiles: '' })
  const [modelTargets, setModelTargets] = useState(null)
  const [routingProfiles, setRoutingProfiles] = useState([])
  // Profiles the operator explicitly ticked to turn task routing back on (sent as reenable_profiles).
  const [reenableChosen, setReenableChosen] = useState([])
  // Hand-picked conversation spare-model targets, kept apart from the pending copy intent
  // (fallbackTargetEdits) that a source switch ends.
  const fallbackTargetsManualRef = useRef(false)
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
  const [autoReloading, setAutoReloading] = useState(false)
  const generationRef = useRef(0)
  const editTurnRef = useRef(null)
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false; generationRef.current += 1 }
  }, [])
  const applyPendingRef = useRef(false)
  const refreshPendingRef = useRef(false)
  // Which parts of the page hold unsaved edits, as of the latest render (read when a save starts).
  const dirtyPartsRef = useRef({})
  const editViewRef = useRef(null)
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
  // Ticked names a same-revision refresh no longer lists. A list the operator chose is never narrowed
  // quietly: it keeps them ticked and its save is blocked by name until they are unticked. A default
  // selection the page made by itself simply follows the live list.
  const liveProfileNames = profiles.map(item => item.name)
  const vanishedFrom = (list, chosen) => chosen && statusQuery.data && Array.isArray(list) ? uniqueProfileNames(list).filter(name => !liveProfileNames.includes(name)) : []
  const vanishedMessage = names => `다음 프로필을 더 이상 찾을 수 없어 저장하지 않습니다. 적용 대상에서 체크를 해제하세요. ${names.join(', ')}`
  const missingTimeoutTargets = vanishedFrom(timeoutTargets, timeoutTargetsManualRef.current)
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
    setProfileDelegationTargets([])
    setProfileTargetEdited(false)
    setFreshMissingProfileTargets([])
    profileTargetsManualRef.current = false
    nativeTargetsManualRef.current = false
    setNativeRecoveryConfirmed(false)
    setDraftRevision(null)
    setTimeoutBaseline(null)
    setTimeoutTargets(null)
    setTimeoutTargetEdited(false)
    timeoutTargetsManualRef.current = false
    setProfileBaselines(null)
    setExpectationBaselines(null)
    setServerConflict(null)
    serverConflictRef.current = null
    setSectionErrors({ models: '', routing: '', timeouts: '', profiles: '' })
    setModelTargets(null)
    setRoutingProfiles([])
    setReenableChosen([])
    fallbackTargetsManualRef.current = false
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
    setProfileDelegationTargets([row.name])
    setProfileTargetEdited(false)
    setFreshMissingProfileTargets([])
    profileTargetsManualRef.current = false
    nativeTargetsManualRef.current = false
    setTimeoutBaseline(copyTimeoutBaseline(row.timeouts))
    setProfileBaselines(copyProfileBaselines(profiles))
    setExpectationBaselines(copyPageExpectations(profiles))
    timeoutTargetsManualRef.current = false
    // Page-made defaults stay symbolic (null = every eligible profile, following the live list)
    // until the operator edits the list by hand.
    setTimeoutTargets(null)
    setTimeoutTargetEdited(false)
    setRoutingBaseline(deepClone({ heavy: row.routing.heavy, light: row.routing.light }))
    setRoutingTargetEdited(false)
    const nativeFallback = copyNativeFallbackDraft(row.fallbacks?.native)
    const routingFallback = copyRoutingFallbackDraft(row.fallbacks?.routing)
    const delegationFallback = copyDelegationFallbackDraft(row.fallbacks?.delegation)
    setFallbackDrafts({ native: nativeFallback, routing: routingFallback, delegation: delegationFallback })
    setFallbackBaselines({ native: nativeFallback ? deepClone(nativeFallback) : null, routing: routingFallback ? deepClone(routingFallback) : null, delegation: delegationFallback ? deepClone(delegationFallback) : null })
    setFallbackTargetEdits({ native: false, routing: false, delegation: false })
    setModelTargets([row.name])
    fallbackTargetsManualRef.current = false
    setFallbackTargets({ native: null, routing: null, delegation: null })
    setRoutingProfiles(profiles.filter(item => item.routing?.enabled === true).map(item => item.name))
    setReenableChosen([])
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
    setSectionErrors({ models: '', routing: '', timeouts: '', profiles: '' })
    setPageError('')
  }
  // A catalog choice edits provider and model in one turn, and the first edit already moves the
  // generation. Later edits of that same turn are accepted; a callback kept past it is not.
  const editFromThisRender = () => {
    const turn = editTurnRef.current
    return renderGeneration === generationRef.current || Boolean(turn && turn.render === renderGeneration && turn.generation === generationRef.current)
  }
  const invalidatePlanForEdit = () => {
    invalidatePlan()
    const mark = { render: renderGeneration, generation: generationRef.current }
    editTurnRef.current = mark
    queueMicrotask(() => { if (editTurnRef.current === mark) editTurnRef.current = null })
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
  const nativeFallbackTargets = selectFallbackTargets(fallbackTargets.native, selectedProfile, profileNames, editableFallbackTargets('native', profiles))
  const routingFallbackTargets = selectFallbackTargets(fallbackTargets.routing, selectedProfile, profileNames, editableFallbackTargets('routing', profiles))
  const delegationFallbackTargets = selectFallbackTargets(fallbackTargets.delegation, selectedProfile, profileNames, editableFallbackTargets('delegation', profiles))
  const missingFallbackTargets = vanishedFrom(fallbackTargets.native, fallbackTargetsManualRef.current)
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
  const routingFallbackError = routingFallbackDraft ? routingFallbackValidation(routingFallbackDraft, routingFallbackRows) : '이 프로필의 이전 작업 방식 예비 모델 상태를 확인할 수 없습니다.'
  const delegationFallbackError = delegationFallbackDraft ? delegationFallbackValidation(delegationFallbackDraft) : '이전 기본 위임 방식의 예비 모델 설정을 확인할 수 없습니다.'
  // One target list for the whole model section: role models, slot models, delegation method and spare models.
  const selectedTargets = reconcileModelTargets(modelTargets, profileNames)
  const missingModelTargets = vanishedFrom(modelTargets, nativeTargetsManualRef.current)
  const slotInfo = slotSupport(statusQuery.data, currentRow)
  // Write intent is the draft against the baseline frozen when the profile was loaded. Live status
  // rows only say whether a value can be written; a live value that moved away from the baseline is a
  // conflict (`liveDrift` below), never an edit.
  const frozenProfile = profileBaselines?.[selectedProfile] || null
  const frozenNativeDto = nativeDelegationBaselines[selectedProfile] || null
  const slotDraftChanged = Boolean(slotInfo.editable && draft?.slots && frozenProfile && !sameValue(draft.slots, frozenProfile.slots ?? null))
  const modelDraftChanged = Boolean(draft && frozenProfile && !sameValue(draft.models, frozenProfile.models))
  const slotDraftIssue = slotInfo.editable && draft?.slots ? slotDraftError(draft.slots) : ''
  // `routingTargetEdited` is the section's copy intent: the operator picked targets by hand.
  // Slot models are copied on fresh intent only while their cards are on screen (a model mode).
  const slotCardsVisible = Boolean(nativeDelegationDraft && nativeModelMode(nativeDelegationDraft.backend))
  const routingCopyPending = !revisionChanged && slotInfo.editable && Boolean(draft?.slots) && (slotDraftChanged || (routingTargetEdited && slotCardsVisible))
  const routingWriteTargets = routingCopyPending ? selectedTargets : []
  const routingTargetError = routingCopyPending ? slotDraftIssue || (!selectedTargets.length ? '‘모델’ 섹션의 적용 대상이 0개입니다. 적용할 프로필을 하나 이상 선택하세요.' : '') : ''
  const modelWriteNeeded = modelDraftChanged || routingTargetEdited
  // Role models go to the target list only while there is an edit or fresh copy intent; a list that
  // merely persisted across a reload or profile change copies nothing.
  const modelWriteTargets = modelWriteNeeded ? selectedTargets : []
  // Bodies are built from this view so every store save carries the same slot declarations.
  const saveDraft = draft ? { ...draft, routing: slotRoutingForSave(draft, slotInfo.editable) } : draft
  const loadedRoutingProfiles = profiles.filter(item => item.routing?.enabled === true).map(item => item.name)
  // Turning routing back on is intent only for a profile that was off when loaded.
  // Effectively off when the page loaded it: the canonical flag is off, or the routing skill is
  // disabled in the profile's own config. Only an explicit tick here turns either back on.
  const frozenRoutingOff = name => profileBaselines?.[name]?.routing?.enabled === false || expectationBaselines?.[name]?.routing?.skill_enabled === false
  const routingOffProfiles = profileNames.filter(frozenRoutingOff)
  const reenableProfiles = routingOffProfiles.filter(name => reenableChosen.includes(name))
  // A ticked re-enable stays an unsaved edit even when its profile drops out of a refreshed status:
  // it is tracked from the ticks and the frozen baseline, not from the live list, and blocks the
  // re-enable save by name until it is unticked.
  // Only offered names can be ticked, so any ticked name the status no longer lists is missing,
  // also after a reload replaced the baseline it was offered from.
  const missingReenable = reenableChosen.filter(name => !profileNames.includes(name))
  const reenableTicks = [...reenableProfiles, ...missingReenable]
  // Values that changed somewhere else since the profile was loaded, at the same store revision (for
  // example a profile without a stored plugin entry whose models are read from its own config).
  // Saving would write the old draft over them, so each save that writes such a part is blocked.
  // Values changed elsewhere since they were frozen (early feedback; the service refuses such a save
  // by itself through `expected`), plus a refusal the service already reported for this page.
  const serverDrift = serverConflict ? [{ profile: serverConflict.profile, part: externalChangeLabel(serverConflict), fallback: serverConflict.field === 'native_fallback' }] : []
  const driftItems = [...pageLiveDrift(profiles, selectedProfile, profileBaselines, expectationBaselines), ...serverDrift]
  const storeDrift = driftItems.filter(item => !item.fallback)
  const fallbackDrift = driftItems.some(item => item.fallback)
  const liveDrift = driftItems
  // Re-checked when a save is dispatched, against the newest status, so a callback kept from an
  // earlier render never sends while the current state is blocked.
  const driftNow = kind => {
    const items = [...pageLiveDrift(statusDataRef.current?.profiles || [], selectedProfile, profileBaselines, expectationBaselines),
      ...(serverConflictRef.current ? [{ fallback: serverConflictRef.current.field === 'native_fallback' }] : [])]
    return items.some(item => kind === 'all' || (kind === 'fallback') === Boolean(item.fallback))
  }
  const storeDriftError = storeDrift.length ? liveDriftMessage(storeDrift) : ''
  const nativeSectionEditable = Boolean(nativeDelegationDraft && currentRow?.native_delegation?.editable === true)
  const nativeSlotCopy = Boolean(nativeSectionEditable && nativeModelMode(nativeDelegationDraft.backend) && nativeSlotDraftReady(nativeDelegationDraft, currentRow.native_delegation))
  const nativeTargetReasons = Object.fromEntries(profiles.map(row => [row.name, nativeSectionEditable ? nativeDelegationTargetReason(row, nativeDelegationDraft.backend, nativeSlotCopy, selectedProfile) : '']))
  // A profile that cannot take the delegation method or spare models still receives the model values.
  const nativeWriteTargets = nativeSectionEditable ? selectedTargets.filter(name => !nativeTargetReasons[name]) : []
  // The model section saves the method and spare models only; profile access is its own section.
  const nativeDraftChanged = nativeSectionEditable && nativeDelegationDraftChanged(nativeDelegationDraft, frozenNativeDto, 'native')
  // A stored method the page no longer offers (Hermes 'default' or an advanced value) is never copied.
  const nativeBackendCopyable = Boolean(nativeDelegationDraft && nativeBackendSelectable(nativeDelegationDraft.backend))
  const nativeWriteNeeded = nativeSectionEditable && nativeBackendCopyable && !revisionChanged && nativeWriteTargets.length > 0 && (nativeDraftChanged || routingTargetEdited)
  let nativeDelegationError = ''
  if (nativeDraftChanged && selectedTargets.includes(selectedProfile) && nativeTargetReasons[selectedProfile]) {
    // The loaded profile's own change must never be dropped silently.
    nativeDelegationError = `${selectedProfile}: ${nativeTargetReasons[selectedProfile]}`
  } else if (nativeWriteNeeded) {
    try { buildNativeDelegationBatchBody(draftRevision, selectedProfile, nativeWriteTargets, nativeDelegationDraft, nativeDelegationBaselines, profiles, 'native') }
    catch (error) { nativeDelegationError = error.message }
  }
  const sectionWriteNeeded = modelWriteNeeded || routingCopyPending || nativeWriteNeeded
  // The profile delegation section: editable only while the loaded profile's stored method uses
  // profiles. It saves to its own targets, each keeping its stored method and spare models.
  const profileSectionEditable = Boolean(nativeSectionEditable && nativeProfileMode(currentRow?.native_delegation?.backend))
  const selectedProfileTargets = reconcileModelTargets(profileDelegationTargets, profileNames)
  // A ticked target that disappeared from a refreshed status is never dropped quietly: it blocks the
  // save by name until it is unticked, and the account-use consent given for the old list is reset.
  const profileTargetList = uniqueProfileNames(Array.isArray(profileDelegationTargets) ? profileDelegationTargets : [])
  const missingProfileTargets = statusQuery.data ? profileTargetList.filter(name => !profileNames.includes(name) || freshMissingProfileTargets.includes(name)) : []
  const missingProfileTargetKey = missingProfileTargets.join('\n')
  useEffect(() => {
    if (!missingProfileTargetKey) return
    setNativeDelegationDraft(current => current?.allowProfileAccess ? { ...current, allowProfileAccess: false } : current)
  }, [missingProfileTargetKey])
  const profileTargetReasons = Object.fromEntries(profiles.map(row => [row.name, freshMissingProfileTargets.includes(row.name)
    ? '저장 직전에 확인한 최신 상태에서 이 프로필을 찾을 수 없습니다. 체크를 해제하세요.' : nativeProfileTargetReason(row)]))
  const profilesDraftChanged = profileSectionEditable && nativeDelegationDraftChanged(nativeDelegationDraft, frozenNativeDto, 'profiles')
  const profilesWriteRequested = profileSectionEditable && (profilesDraftChanged || profileTargetEdited)
  const profilesWriteNeeded = profilesWriteRequested && !revisionChanged && selectedProfileTargets.length > 0
  const profileBlockedTargets = selectedProfileTargets.filter(name => profileTargetReasons[name])
  let profileSaveError = ''
  if (missingProfileTargets.length) {
    profileSaveError = `다음 프로필을 더 이상 찾을 수 없어 전문 프로필 설정을 저장할 수 없습니다. 적용 대상에서 빼 주세요. ${missingProfileTargets.join(', ')}`
  } else if (profilesWriteRequested && !selectedProfileTargets.length) {
    profileSaveError = '‘전문 프로필 위임’의 적용 대상이 0개입니다. 적용할 프로필을 하나 이상 선택하세요.'
  } else if (profilesWriteRequested && profileBlockedTargets.length) {
    // Nothing is skipped quietly here: a target that cannot take the allow-list must be unticked.
    profileSaveError = `다음 프로필에는 전문 프로필 설정을 저장할 수 없습니다. 적용 대상에서 빼 주세요. ${profileBlockedTargets.map(name => `${name}: ${profileTargetReasons[name]}`).join(' ')}`
  } else if (profilesWriteNeeded) {
    try { buildNativeDelegationBatchBody(draftRevision, selectedProfile, selectedProfileTargets, nativeDelegationDraft, nativeDelegationBaselines, profiles, 'profiles') }
    catch (error) { profileSaveError = error.message }
  }
  if (!profileSaveError && profilesWriteNeeded && !nativeStorageAvailable) profileSaveError = '저장 준비를 확인할 수 없습니다. 플러그인을 다시 열어 주세요.'
  // Unsaved edits, compared with the frozen baseline of the loaded profile and independent of whether
  // a section is editable right now. A save clears only the parts whose fields it actually sends.
  // Nothing here reads the live status rows or whether a control is editable right now: an edit made
  // while a section was editable stays unsaved after a refresh makes it read-only.
  const frozenNative = copyNativeDelegationDraft(nativeDelegationBaselines[selectedProfile])
  const differs = (value, loaded) => !sameValue(value ?? null, loaded ?? null)
  const nativeFieldDirty = key => Boolean(nativeDelegationDraft && frozenNative && differs(nativeDelegationDraft[key], frozenNative[key]))
  const draftRoutes = nativeDelegationDraft?.profile_routes || null
  const frozenRoutes = frozenNative?.profile_routes || null
  const frozenReenable = reenableTicks
  dirtyPartsRef.current = {
    // Without a frozen baseline an edit can never be shown as saved.
    models: Boolean(draft && (!frozenProfile || differs(draft.models, frozenProfile.models))),
    'routing.roles': Boolean(draft && frozenProfile && (differs(draft.routing?.heavy, frozenProfile.routing?.heavy) || differs(draft.routing?.light, frozenProfile.routing?.light))),
    'routing.slots': Boolean(draft && frozenProfile && differs(draft.slots, frozenProfile.slots)),
    // A hand-picked model target list is a pending copy of the role models, of the slot models while
    // their cards are on screen, and of the delegation method to profiles stored on a plugin method.
    'copy.models': Boolean(routingTargetEdited),
    'copy.slots': Boolean(routingTargetEdited && slotCardsVisible && draft?.slots),
    'native.copy': Boolean(routingTargetEdited && nativeBackendCopyable && selectedTargets.some(name => nativeBackendSelectable(nativeDelegationBaselines[name]?.backend))),
    'native.backend': nativeFieldDirty('backend'), 'native.slotPolicy': nativeFieldDirty('slotPolicy'), 'native.autoSlotPolicy': nativeFieldDirty('autoSlotPolicy'),
    'profiles.list': Boolean(draftRoutes && frozenRoutes && differs(draftRoutes.profiles, frozenRoutes.profiles)),
    'profiles.default': Boolean(draftRoutes && frozenRoutes && differs(draftRoutes.default, frozenRoutes.default)),
    'profiles.targets': Boolean(profileTargetEdited),
    timeouts: Boolean(timeoutWriteRequested), 'fallback:native': nativeFallbackDraftChanged || Boolean(fallbackTargetEdits.native),
    reenable: frozenReenable.length > 0 }
  // The drafted value of each edit, for checking what a save actually sent.
  editViewRef.current = { profile: selectedProfile, models: draft?.models ?? null,
    routing: draft ? { heavy: draft.routing?.heavy, light: draft.routing?.light } : null, slots: draft?.slots ?? null,
    native: nativeDelegationDraft ? { backend: nativeDelegationDraft.backend, slotPolicy: nativeDelegationDraft.slotPolicy ?? null,
      autoSlotPolicy: nativeDelegationDraft.autoSlotPolicy ?? null, profile_routes: nativeDelegationDraft.profile_routes,
      descriptionEdits: nativeDelegationDraft.descriptionEdits || {} } : null,
    nativeFallback: fallbackValueForScope('native', nativeFallbackDraft), reenable: frozenReenable }
  const noTargetError = (modelDraftChanged || slotDraftChanged || nativeDraftChanged) && !selectedTargets.length ? '‘모델’ 섹션의 적용 대상이 0개입니다. 적용할 프로필을 하나 이상 선택하세요.' : ''
  // A changed delegation method or spare model that no selected profile can take is never dropped silently.
  const noNativeTargetError = nativeDraftChanged && selectedTargets.length && !nativeWriteTargets.length
    ? '바꾼 ‘맡기는 방식·예비 모델’을 받을 수 있는 프로필이 적용 대상에 없습니다. 받을 수 있는 프로필을 선택하거나 그 변경을 되돌리세요.' : ''
  const sectionSaveError = (missingModelTargets.length && (sectionWriteNeeded || routingTargetEdited) ? vanishedMessage(missingModelTargets) : '') ||
    ((modelWriteNeeded || routingCopyPending) ? storeDriftError : '') || nativeDelegationError || (routingCopyPending ? routingTargetError : '') || noTargetError || noNativeTargetError ||
    (nativeWriteNeeded && !nativeStorageAvailable ? '저장 준비를 확인할 수 없습니다. 플러그인을 다시 열어 주세요.' : '')
  const customSlotCount = draft?.slots ? TASK_SLOTS.filter(slot => draft.slots[slot.id]?.follow === 'custom').length : 0
  const spareSlotCount = nativeSlotCopy ? TASK_SLOTS.filter(slot => nativeDraftSlotPolicy(nativeDelegationDraft)[slot.id].mode === 'custom').length : 0
  const sectionSaveSummary = [
    modelWriteNeeded ? '대화 모델' : null,
    routingCopyPending ? `작업 슬롯 모델(직접 지정 ${customSlotCount}개)` : null,
    nativeWriteNeeded ? `맡기는 방식: ${nativeBackendLabel(nativeDelegationDraft.backend)}${nativeSlotCopy ? ` · 예비 모델을 둔 슬롯 ${spareSlotCount}개` : ''}` : null
  ].filter(Boolean).join(' · ') || '바뀐 내용이 없어 저장할 것이 없습니다. 값을 고치면 그 내용을, 적용 대상을 직접 고르면 현재 값을 그 프로필에 저장합니다.'
  const nativeSkippedTargets = nativeDraftChanged || (nativeSectionEditable && nativeBackendCopyable && routingTargetEdited) ? selectedTargets.filter(name => nativeTargetReasons[name]) : []
  const profileRoutesSummary = nativeDelegationDraft?.profile_routes
  const profileSaveSummary = profilesWriteNeeded
    ? `허용할 전문 프로필: ${profileRoutesSummary.profiles.map(entry => entry.name).join(', ') || '없음'}${currentRow?.native_delegation?.backend === 'model-router-profiles' ? ` · 기본: ${profileRoutesSummary.default || '없음'}` : ''}`
    : '바뀐 내용이 없어 저장할 것이 없습니다. 허용 목록이나 설명을 고치면 그 내용을, 적용 대상을 직접 고르면 현재 허용 목록을 그 프로필에 저장합니다.'
  const allTargetsSelected = allModelTargetsSelected(selectedTargets, profileNames)
  const targetSummary = allTargetsSelected ? `전체 ${profileNames.length}개 프로필` : `${selectedTargets.length}/${profileNames.length}개 프로필`
  const timeoutDraftResult = buildTimeoutUpdate(selectedProfile, draft?.timeouts, timeoutBaseline, currentRow?.timeouts)
  const timeoutSettingsSupported = validTimeoutsDto(currentRow?.timeouts)
  const timeoutRoleSupported = splitRoutingSupported(currentRow?.timeouts)
  const timeoutSettingsEditable = timeoutSettingsSupported && timeoutRoleSupported && currentRow?.timeouts?.editable === true && Boolean(draft?.timeouts)
  const disabled = setupPending || profilePreparationLocked() || Boolean(nativeFence) || applyPending || needsReload || revisionChanged || statusQuery.isFetching || !selectedProfile || !draft
  const timeoutSaveValuesValid = Boolean(timeoutPayloadValues(draft?.timeouts, timeoutBaseline))
  const timeoutSaveDisabled = disabled || !timeoutSettingsEditable || !selectedTimeoutTargets.length || missingTimeoutTargets.length > 0 ||
    timeoutSourceRevisionChanged || timeoutTargetsRevisionChanged || !timeoutSaveValuesValid
  const validPreview = previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile)
  const renderGeneration = generationRef.current

  const installFirstSeenBaselines = rows => {
    const fresh = rows.filter(row => typeof row?.name === 'string' && !Object.prototype.hasOwnProperty.call(expectationBaselines || {}, row.name))
    if (!fresh.length || !profileBaselines) return
    setProfileBaselines(current => current ? { ...copyProfileBaselines(fresh), ...current } : current)
    setNativeDelegationBaselines(current => ({ ...copyNativeDelegationBaselines(fresh), ...current }))
    setExpectationBaselines(current => current ? { ...copyPageExpectations(fresh), ...current } : current)
  }
  // Freeze a newly discovered profile when it is first seen, before it can be edited or copied to.
  const unseenProfileKey = profileBaselines && expectationBaselines ? profiles.filter(row => !Object.prototype.hasOwnProperty.call(expectationBaselines, row.name)).map(row => row.name).join('\n') : ''
  useEffect(() => {
    if (unseenProfileKey) installFirstSeenBaselines(profiles)
  }, [unseenProfileKey])

  const selectProfile = name => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    const row = profiles.find(item => item.name === name)
    if (!row) return
    const loadedBaseline = profileBaselines?.[name] || copyProfileBaselines([row])[name]
    if (!loadedBaseline) return
    invalidatePlan()
    // A profile first seen after the page loaded gets its frozen baseline from the status it is
    // selected in, so its edits are compared, saved and guarded like any other.
    installFirstSeenBaselines([row])
    const nextDraft = deepClone(loadedBaseline)
    const timeoutDraft = timeoutDraftFromSettings(loadedBaseline.timeouts)
    if (timeoutDraft) nextDraft.timeouts = timeoutDraft
    else delete nextDraft.timeouts
    setSelectedProfile(name)
    setDraft(nextDraft)
    setNativeDelegationDraft(copyNativeDelegationDraft(nativeDelegationBaselines[name] || row.native_delegation))
    // A ticked profile target that is gone stays listed and blocks that save until it is unticked.
    setProfileDelegationTargets(current => profileTargetsManualRef.current ? uniqueProfileNames(current || []) : [name])
    setProfileTargetEdited(false)
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
    // A hand-picked list survives a source switch as picked, vanished names included; only the
    // pending copy intent ends here.
    setModelTargets(current => nativeTargetsManualRef.current ? uniqueProfileNames(current || []) : [name])
    setRoutingTargets(current => reconcileModelTargets(current, profileNames))
  }

  const applyPreset = presetId => updateDraft(current => applyModelPresetDraft(current, presetId))

  const setSectionTargets = next => {
    if (renderGeneration !== generationRef.current || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    nativeTargetsManualRef.current = true
    setModelTargets(next)
    setRoutingTargetEdited(next.length > 0)
  }
  // Toggle on the list as ticked, so unticking one name never drops a vanished one quietly.
  const toggleModelTarget = (name, checked) => setSectionTargets(toggleName([...selectedTargets, ...missingModelTargets], name, checked))
  const selectAllTargets = () => setSectionTargets(selectAllModelTargets(profileNames))
  const selectNoTargets = () => setSectionTargets(selectNoModelTargets())
  const selectSourceTargets = () => setSectionTargets(selectedProfile ? [selectedProfile] : [])

  const setProfileTargets = next => {
    if (renderGeneration !== generationRef.current || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    profileTargetsManualRef.current = true
    setProfileDelegationTargets(next)
    setProfileTargetEdited(next.length > 0)
    // Access consent was given for a specific target list.
    setNativeDelegationDraft(current => current ? { ...current, allowProfileAccess: false } : current)
  }
  const chooseProfileTargets = (mode, name = null, checked = false) => {
    if (mode === 'all') return setProfileTargets(selectAllModelTargets(profileNames.filter(item => !profileTargetReasons[item])))
    if (mode === 'source') return setProfileTargets(selectedProfile ? [selectedProfile] : [])
    if (mode === 'none') return setProfileTargets(selectNoModelTargets())
    // Toggle on the list as ticked, so unticking one name never drops another missing one silently.
    return setProfileTargets(toggleName(profileTargetList, name, checked))
  }

  const chooseTimeoutTargets = (mode, name = null, checked = false) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const eligible = eligibleTimeoutTargets(profiles)
    let next = [...selectedTimeoutTargets, ...missingTimeoutTargets]
    if (mode === 'all') next = eligible
    else if (mode === 'source') next = eligible.includes(selectedProfile) ? [selectedProfile] : []
    else if (mode === 'none') next = []
    else if (eligible.includes(name) || (missingTimeoutTargets.includes(name) && !checked)) next = toggleName(next, name, checked)
    invalidatePlan()
    timeoutTargetsManualRef.current = true
    setTimeoutTargets([...next])
    setTimeoutTargetEdited(true)
  }

  const toggleRoutingProfile = (name, checked) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlan()
    setReenableChosen(current => toggleName(current, name, checked))
    if (name === selectedProfile && profileBaselines?.[name]?.routing?.enabled === false) {
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
  const changeSlotFollow = (slot, follow) => updateDraft(current => current.slots?.[slot]
    ? { ...current, slots: { ...current.slots, [slot]: slotFollowDeclaration(current.slots[slot], follow, current.models) } } : current)
  const updateSlotRoute = (slot, field, value) => updateDraft(current => current.slots?.[slot]?.follow === 'custom'
    ? { ...current, slots: { ...current.slots, [slot]: { follow: 'custom', custom: { ...(current.slots[slot].custom || {}), [field]: value } } } } : current)

  const updateFallbackDraft = (scope, updater) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || !editFromThisRender()) return
    invalidatePlanForEdit()
    setFallbackDrafts(current => ({
      ...current,
      [scope]: current[scope] ? updater(current[scope]) : current[scope]
    }))
  }

  const updateFallbackTarget = (scope, name, checked) => {
    if (setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || renderGeneration !== generationRef.current) return
    const selected = scope === 'native' ? [...nativeFallbackTargets, ...missingFallbackTargets] : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    invalidatePlan()
    setFallbackTargets(current => ({ ...current, [scope]: toggleName(selected, name, checked) }))
    setFallbackTargetEdits(current => ({ ...current, [scope]: true }))
    if (scope === 'native') fallbackTargetsManualRef.current = true
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
    if (scope === 'native') fallbackTargetsManualRef.current = true
  }

  const canPreviewFallback = scope => {
    if (!fallbackSupported || disabled || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || fallbackPreviewPending || !selectedProfile || !statusQuery.data) return false
    const targets = scope === 'native' ? nativeFallbackTargets : scope === 'routing' ? routingFallbackTargets : delegationFallbackTargets
    const rows = scope === 'native' ? nativeFallbackRows : scope === 'routing' ? routingFallbackRows : delegationFallbackRows
    if (targets.length === 0 || rows.length !== targets.length) return false
    if (scope === 'native' && missingFallbackTargets.length) return false
    if (scope === 'native') {
      if (!nativeFallbackDraft || fallbackDrift || currentRow?.fallbacks?.native?.editable !== true || rows.some(row => row.fallbacks?.native?.editable !== true)) return false
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
    draft: deepClone(saveDraft),
    modelTargets: [...modelWriteTargets],
    // Membership is sent back as loaded; only the re-enable save changes it.
    routingProfiles: [...loadedRoutingProfiles],
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
    noTargetError,
    fallbackDrafts: deepClone(fallbackDrafts),
    fallbackBaselines: deepClone(fallbackBaselines),
    fallbackTargets: deepClone(fallbackTargets),
    fallbackTargetEdits: { ...fallbackTargetEdits },
    profiles: deepClone(profiles),
    // Frozen at load (never re-read after a write): what each store body expects to overwrite.
    pageExpectations: deepClone(expectationBaselines || {}),
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

  // `skipped` names a second step of a save chain that was not started because of this receipt.
  const recordApplyReceipt = (snapshot, receipt, skipped = '') => {
    if (isPartialReceipt(receipt)) {
      setApplyOutcome({ kind: 'partial', result: receipt, ...(skipped ? { message: `다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요. ${skipped}` } : {}) })
    } else if (receipt?.status === 'applied' || receipt?.status === 'no_change') {
      setApplyOutcome({ kind: 'success', result: receipt })
    } else {
      markApplyUnknown(snapshot, `${receipt?.error || '적용 결과를 확인할 수 없습니다. 다시 저장하지 말고 실제 상태를 새로고침하세요.'}${skipped ? ` ${skipped}` : ''}`, receipt)
      return
    }
    needsReloadRef.scopeKey = snapshot.scopeKey
    needsReloadRef.current = true
    setNeedsReload(true)
  }

  const runSave = async ({ operation, scope = null, snapshot, prepare, beforeApply = null, nativeWrite = false, followUp = null }) => {
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
    let cleanSave = false
    // Reloading replaces every draft, so it runs by itself only when the bodies this save actually
    // applied carried every unsaved edit (see submittedEditCoverage).
    const dirtyAtStart = { ...(dirtyPartsRef.current || {}) }
    const viewAtStart = editViewRef.current
    const sent = []
    let nativeFenceRecord = null
    const skippedNote = followUp ? `‘${followUp.secondLabel}’ 저장은 시작하지 않았습니다. 새로고침하면 저장하지 않은 편집은 사라지므로 다시 입력해 저장하세요.` : ''
    // Every store body carries the frozen expectations of the profiles and fields it writes. The
    // follow-up of a combined save uses the same frozen values: its first write (the delegation
    // method) touches none of them, so nothing is advanced.
    const liveNames = (Array.isArray(snapshot.profiles) ? snapshot.profiles : []).map(row => row.name)
    const withExpected = (op, body) => ['/preview', '/fallback-preview'].includes(op) && snapshot.pageExpectations && body
      ? { ...body, expected: pageExpectationsFor(op, body, snapshot.pageExpectations, liveNames) } : body
    const noteConflict = error => {
      const conflict = externalChangeFromError(error)
      if (conflict && isSaveCurrent(snapshot, token)) { serverConflictRef.current = conflict; setServerConflict(conflict) }
      return conflict
    }
    try {
      const rawPrepared = prepare()
      const prepared = { ...rawPrepared, body: rawPrepared.errors?.length ? rawPrepared.body : withExpected(operation, rawPrepared.body) }
      if (prepared.errors?.length) throw new Error(prepared.errors.join(' '))
      if (previewBodyTooLarge(prepared.body)) throw new Error(BODY_TOO_LARGE_MESSAGE)
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
      if (followUp) {
        // Validate the second transaction before the first one writes anything.
        const checkRaw = followUp.prepare()
        if (checkRaw.errors?.length) throw new Error(checkRaw.errors.join(' '))
        const check = { ...checkRaw, body: withExpected(followUp.operation, checkRaw.body) }
        if (previewBodyTooLarge(check.body)) throw new Error(BODY_TOO_LARGE_MESSAGE)
        const checked = await ctx.rest(followUp.operation, { method: 'POST', body: check.body })
        if (!isSaveCurrent(snapshot, token)) return
        if (!checked || typeof checked.plan_id !== 'string' || !Array.isArray(checked.changes)) throw new Error('저장 계획 응답이 올바르지 않습니다. 설정은 변경되지 않았습니다.')
      }
      if (nativeWrite) {
        // Validate the source even when it is not a write target; target CAS alone
        // cannot detect an excluded source changing behind the query cache.
        const freshStatus = await ctx.rest('/status')
        if (!isSaveCurrent(snapshot, token)) return
        // A target that vanished since the page data was cached is named, never dropped quietly.
        const freshNames = new Set((Array.isArray(freshStatus?.profiles) ? freshStatus.profiles : []).map(row => row?.name))
        const vanished = snapshot.nativeTargets.filter(name => !freshNames.has(name))
        if (vanished.length) {
          if (snapshot.nativePart === 'profiles') {
            setFreshMissingProfileTargets(current => uniqueProfileNames([...current, ...vanished]))
            // The account-use consent was given for the old target list.
            setNativeDelegationDraft(current => current ? { ...current, allowProfileAccess: false } : current)
          }
          throw new Error(`다음 프로필을 더 이상 찾을 수 없어 저장하지 않았습니다. 적용 대상에서 빼 주세요. ${vanished.join(', ')}`)
        }
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
      sent.push({ operation, part: snapshot.nativePart || null, body: prepared.body })
      const receipt = await ctx.rest('/apply', { method: 'POST', body: { plan_id: planId }, timeoutMs: 180000 })
      if (nativeFenceRecord) writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey,
        { ...nativeFenceRecord, state: isPartialReceipt(receipt) || ['applied', 'no_change'].includes(receipt?.status) ? 'settled' : 'unknown' }, nativeFenceRecord.id)
      if (!isSaveCurrent(snapshot, token)) {
        markApplyUnknown(snapshot, '저장 도중 연결 또는 프로필이 바뀌어 결과를 확인할 수 없습니다. 다시 저장하지 마세요. 원래 연결·프로필로 돌아가 실제 상태를 새로고침하세요.')
        return
      }
      if (!followUp || isPartialReceipt(receipt) || !['applied', 'no_change'].includes(receipt?.status)) {
        // A partial or unknown first receipt ends the chain; nothing else is attempted.
        recordApplyReceipt(snapshot, receipt, followUp ? skippedNote : '')
        cleanSave = !followUp && !isPartialReceipt(receipt) && ['applied', 'no_change'].includes(receipt?.status)
        return
      }
      // The first apply does not move the store revision, but a plan made before it is not reused.
      let secondStarted = false
      try {
        const nextRaw = followUp.prepare()
        if (nextRaw.errors?.length) throw new Error(nextRaw.errors.join(' '))
        const next = { ...nextRaw, body: withExpected(followUp.operation, nextRaw.body) }
        const plan = await ctx.rest(followUp.operation, { method: 'POST', body: next.body })
        if (!isSaveCurrent(snapshot, token)) throw new Error('저장 도중 연결 또는 프로필이 바뀌었습니다.')
        if (!plan || typeof plan.plan_id !== 'string' || !Array.isArray(plan.changes)) throw new Error('저장 계획 응답이 올바르지 않습니다.')
        secondStarted = true
        sent.push({ operation: followUp.operation, part: null, body: next.body })
        const second = await ctx.rest('/apply', { method: 'POST', body: { plan_id: plan.plan_id }, timeoutMs: 180000 })
        if (!isSaveCurrent(snapshot, token)) throw new Error('저장 도중 연결 또는 프로필이 바뀌었습니다.')
        if (isPartialReceipt(second) || !['applied', 'no_change'].includes(second?.status)) throw new Error(second?.error || '적용 결과를 확인할 수 없습니다.')
        setApplyOutcome({ kind: 'success', result: { [followUp.firstLabel]: receipt, [followUp.secondLabel]: second } })
        cleanSave = true
      } catch (error) {
        const firstDone = receipt.status === 'no_change' ? `‘${followUp.firstLabel}’: 바뀐 내용이 없었습니다.` : `‘${followUp.firstLabel}’: 저장했습니다.`
        // A compare-and-set refusal is checked before the second write: nothing of it was written.
        const conflict = noteConflict(error)
        const reason = `(사유: ${conflict ? externalChangeMessage(conflict) : error?.message || '알 수 없는 오류'})`
        setApplyOutcome({ kind: 'partial', result: { [followUp.firstLabel]: receipt },
          message: secondStarted && !conflict
            ? `${firstDone} ‘${followUp.secondLabel}’: 저장 결과를 확인할 수 없습니다. 다시 저장하지 말고 상태를 새로고침해 실제 반영 여부를 확인하세요. ${reason}`
            : `${firstDone} ‘${followUp.secondLabel}’: 저장하지 않았습니다. 상태를 새로고침한 뒤 저장되지 않은 부분만 다시 편집해 저장하세요. ${reason}` })
      }
      needsReloadRef.scopeKey = snapshot.scopeKey
      needsReloadRef.current = true
      setNeedsReload(true)
    } catch (error) {
      // The service checks the frozen expectations before its first write, so a refusal at apply
      // still means nothing was written.
      const conflict = !nativeFenceRecord ? noteConflict(error) : null
      if (conflict && isSaveCurrent(snapshot, token)) {
        const message = externalChangeMessage(conflict)
        if (operation === '/fallback-preview') setFallbackError({ scope, message })
        else if (scope) setSectionErrors(current => ({ ...current, [scope]: message }))
        else setPageError(message)
      } else if (applyStarted) {
        if (nativeFenceRecord) writeNativeSaveFence(pluginContext.storage, snapshot.scopeKey, { ...nativeFenceRecord, state: 'unknown' }, nativeFenceRecord.id)
        markApplyUnknown(snapshot, `${error?.message || '저장 결과를 확인할 수 없습니다. 다시 저장하지 말고 실제 상태를 새로고침하세요.'}${skippedNote ? ` ${skippedNote}` : ''}`)
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
      const coveredEdits = cleanSave ? submittedEditCoverage(viewAtStart, sent) : new Set()
      const otherEdits = Object.entries(dirtyAtStart).some(([part, dirty]) => dirty && !coveredEdits.has(part))
      // A confirmed save reloads the saved state by itself so editing can continue; partial or
      // unknown results still wait for an explicit refresh.
      if (cleanSave && !otherEdits && generationRef.current === token) {
        setAutoReloading(true)
        void reloadStatus({ keepOutcome: true }).finally(() => setAutoReloading(false))
      }
      else if (cleanSave && otherEdits && generationRef.current === token) setApplyOutcome(current => current?.kind === 'success'
        ? { ...current, message: '저장했습니다. 다른 곳에 저장하지 않은 편집이 있어 자동으로 다시 불러오지 않았습니다. 아래 버튼으로 다시 불러오면 그 편집은 사라집니다.' } : current)
    }
  }

  const saveFallback = scope => {
    // Only the conversation fallback is saved from the page; stored routing/delegation values stay as they are.
    if (!PAGE_FALLBACK_SCOPES.includes(scope) || (scope === 'native' && driftNow('fallback'))) return
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
    if (!editFromThisRender() || setupPendingRef.current || profilePreparationLocked() || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) || applyPendingRef.current || needsReloadRef.current) return
    invalidatePlanForEdit()
    setNativeDelegationDraft(current => current ? updater(current) : current)
  }

  // One button for the model section. The delegation method and spare models live in each
  // profile's config, the role and slot models in the shared plugin store: two transactions,
  // native first because it does not move the store revision.
  const saveModelSection = () => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !draft || !statusQuery.data ||
      setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || refreshPendingRef.current || !profileBaselines) return
    const slotsNeeded = routingCopyPending
    const storeScope = modelWriteNeeded && slotsNeeded ? null : slotsNeeded ? 'routing' : 'models'
    if (!sectionWriteNeeded || sectionSaveError) return
    // Checked again now, against the newest status: this callback may come from an earlier render.
    if ((modelWriteNeeded || slotsNeeded) && driftNow('store')) return
    const snapshot = freezeDeep({ ...captureSaveSnapshot(), nativePart: 'native',
      nativeDraft: nativeDelegationDraft ? deepClone(nativeDelegationDraft) : null,
      nativeTargets: [...nativeWriteTargets], nativeBaselines: deepClone(nativeDelegationBaselines),
      nativeBaseIdentity: statusQuery.data?.readiness_context?.base_identity })
    const store = { operation: '/preview', firstLabel: '맡기는 방식과 예비 모델', secondLabel: '모델 변경',
      prepare: () => buildModelSectionPreviewBody(snapshot, storeScope) }
    if (!nativeWriteNeeded) return runSave({ operation: '/preview', scope: 'models', snapshot, prepare: store.prepare })
    // The method is always sent; spare models only for the method whose slot cards are on screen.
    if (nativeDelegationError || !nativeStorageAvailable || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity) ||
      !nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current)) return
    return runSave({ operation: '/delegation-preview', scope: 'models', snapshot, nativeWrite: true,
      beforeApply: () => nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current),
      prepare: () => ({ body: buildNativeDelegationBatchBody(snapshot.revision, snapshot.profile, snapshot.nativeTargets,
        snapshot.nativeDraft, snapshot.nativeBaselines, snapshot.profiles, 'native'), errors: [] }),
      followUp: modelWriteNeeded || slotsNeeded ? store : null })
  }

  // The profile delegation section's own save: the same '/delegation-preview' path and save fence,
  // with only the allow-list, descriptions and consent taken from the draft.
  const saveProfileSection = () => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !draft || !statusQuery.data ||
      setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || refreshPendingRef.current) return
    if (!profilesWriteNeeded || profileSaveError || !nativeStorageAvailable || readNativeSaveFence(pluginContext.storage, scopeKey, statusDataRef.current?.readiness_context?.base_identity)) return
    const snapshot = freezeDeep({ ...captureSaveSnapshot(), nativePart: 'profiles',
      nativeDraft: deepClone(nativeDelegationDraft), nativeTargets: [...selectedProfileTargets],
      nativeBaselines: deepClone(nativeDelegationBaselines), nativeBaseIdentity: statusQuery.data?.readiness_context?.base_identity })
    if (!nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current)) return
    return runSave({ operation: '/delegation-preview', scope: 'profiles', snapshot, nativeWrite: true,
      beforeApply: () => nativeDelegationSnapshotCurrent(snapshot, statusDataRef.current),
      prepare: () => ({ body: buildNativeDelegationBatchBody(snapshot.revision, snapshot.profile, snapshot.nativeTargets,
        snapshot.nativeDraft, snapshot.nativeBaselines, snapshot.profiles, 'profiles'), errors: [] }) })
  }

  // Turning task routing back on for a profile that had it off: membership only, nothing copied.
  const saveReenable = () => {
    if (renderGeneration !== generationRef.current || revisionChanged || !currentRow || !draft || !statusQuery.data || !reenableProfiles.length || storeDrift.length || missingReenable.length || driftNow('store') ||
      setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current || !profileBaselines) return
    const base = captureSaveSnapshot()
    const routing = deepClone(profileBaselines[selectedProfile]?.routing || draft.routing)
    delete routing.slots
    const snapshot = freezeDeep({ ...base, draft: { ...base.draft, routing }, routingProfiles: uniqueProfileNames([...loadedRoutingProfiles, ...reenableProfiles]), routingTargets: [], routingTargetError: '',
      reenableProfiles: [...reenableProfiles] })
    return runSave({ operation: '/preview', scope: 'models', snapshot, prepare: () => {
      // The explicit re-enable: the service turns the routing skill back on only for these names.
      const prepared = buildScopedPreviewBody(snapshot, 'routing')
      return prepared.body ? { ...prepared, body: { ...prepared.body, reenable_profiles: [...snapshot.reenableProfiles] } } : prepared
    } })
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
    if (renderGeneration !== generationRef.current || revisionChanged || timeoutRevisionChanged || liveDrift.length || pageVanished.length || driftNow('all') || !currentRow || !draft || !statusQuery.data || setupPendingRef.current || profilePreparationLocked() || applyPendingRef.current || needsReloadRef.current) return
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
        return { body: combined.body, errors: [...new Set([...combined.errors, ...projectedErrors, ...(snapshot.routingTargetError ? [snapshot.routingTargetError] : []), ...(snapshot.noTargetError ? [snapshot.noTargetError] : [])])] }
      }
    })
  }


  const reloadStatus = async ({ keepOutcome = false } = {}) => {
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
    setExpectationBaselines(copyPageExpectations(rows))
    setServerConflict(null)
    serverConflictRef.current = null
    setNativeDelegationBaselines(copyNativeDelegationBaselines(rows))
    // A ticked profile target that is gone stays listed and blocks that save until it is unticked.
    setProfileDelegationTargets(current => profileTargetsManualRef.current ? uniqueProfileNames(current || []) : [row?.name].filter(Boolean))
    setProfileTargetEdited(false)
    setFreshMissingProfileTargets([])
    setTimeoutTargets(current => timeoutTargetsManualRef.current ? uniqueProfileNames(current || []) : null)
    setTimeoutTargetEdited(false)
    setSectionErrors({ models: '', routing: '', timeouts: '', profiles: '' })
    setModelTargets(current => nativeTargetsManualRef.current ? uniqueProfileNames(current || []) : [row?.name].filter(Boolean))
    setRoutingProfiles(rows.filter(item => item.routing?.enabled === true).map(item => item.name))
    // Re-enable ticks are hand-picked: a vanished one stays (and blocks) until it is unticked, and
    // one still off keeps its tick. One that is now on needs nothing and is dropped.
    setReenableChosen(current => current.filter(name => {
      const item = rows.find(entry => entry.name === name)
      return !item || item.routing?.enabled === false || routingSkillEnabled(item) === false
    }))
    setRoutingTargets(current => reconcileModelTargets(current, rows.map(item => item.name)))
    setFallbackTargets(current => ({
      native: fallbackTargetsManualRef.current && Array.isArray(current.native) ? uniqueProfileNames(current.native) : null,
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
    if (!keepOutcome) setApplyOutcome(null)
  }

  if (readyScope !== scopeKey || statusQuery.isPending) {
    return jsxs('main', { style: styles.page, 'aria-busy': true, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'status', style: styles.statusLine, children: [jsx(GlyphSpinner, {}), jsx('span', { style: styles.hint, children: '프로필 설정을 불러오고 있습니다.' })] })] })
  }

  // A failed status read shows the error screen, except right after a save: then the page stays
  // (editing is already locked by needsReload) so the save outcome and its retry button remain.
  if (statusQuery.isError && !(statusQuery.data && needsReload)) {
    return jsxs('main', { style: styles.page, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '설정 서비스를 사용할 수 없습니다.' }), jsx('p', { style: styles.hint, children: '이 프로필의 설정 기능에 연결하지 못했습니다. 플러그인이 설치되고 켜져 있는지 확인한 뒤 다시 불러오세요. 기존 설정은 바꾸지 않습니다.' }), jsx('p', { style: styles.hint, children: statusQuery.error?.message || '상태 요청에 실패했습니다.' }), jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => void statusQuery.refetch(), children: '다시 불러오기' })] }), jsx(BackendPreparationGuide, { profile: activeProfile })] })
  }

  // The menu lists the loaded profile's connected services; it never follows
  // the save targets, which are chosen separately below.
  const modelCatalog = selectedProfile && activeProfile ? { profile: selectedProfile, activeProfile, connectionId: connectionId || null } : null
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
      modelCatalog && nativeModelMenu() ? jsx('p', { id: 'model-catalog-note', role: 'note', style: styles.hint, children: `각 역할의 모델을 누르면 불러온 프로필(${selectedProfile})에 연결된 서비스의 모델 목록에서 검색해 고를 수 있습니다. 다른 프로필에도 함께 저장한다면 그 프로필에 같은 서비스가 연결되어 있는지 확인하세요.` }) : null,
      jsx('p', { id: 'fast-inheritance-note', role: 'note', style: styles.hint, children: '메인 세션에서 선택한 Fast 모드는 작업 슬롯으로 맡기는 새 작업이 시작할 때 상속합니다. 지원하지 않는 모델·제공자에는 Fast 옵션을 보내지 않으며, auto/cold의 남은 시간을 연장하지 않습니다. Fast 요청에는 API 추가 요금이나 Codex 크레딧 사용 증가가 있을 수 있습니다. 요청한 모드와 제공자가 실제 처리한 등급은 다를 수 있으며, 업데이트된 실행 기능은 새 세션에서 확인하세요.' }),
      jsx('div', {
        style: styles.roleGrid,
        children: ROLES.map(role => jsxs('article', {
          style: styles.roleCard,
          children: [
            jsxs('div', { children: [jsx('h3', { style: styles.roleTitle, children: role.label }), jsx('p', { style: { ...styles.hint, marginTop: '0.25rem' }, children: role.description })] }),
            jsx(RoleRouteFields, { prefix: `model-${role.id}`, route: draft.models?.[role.id], disabled, catalog: modelCatalog, onChange: (field, value) => updateRole(role.id, field, value) }),
            jsx('p', { style: styles.actual, children: `실제 설정: ${readableValue(currentRow?.actual_models?.[role.id])}` })
          ]
        }, role.id))
      })
    ]
  }) : jsx('p', { role: 'alert', style: styles.warning, children: '선택한 프로필의 모델 또는 라우팅 정보가 없습니다. 프로필을 다시 불러와 상태를 확인하세요.' })

  const sectionSaveBlocked = Boolean(sectionSaveError)
  const modelTargetGroup = jsxs('fieldset', {
    id: 'model-section-targets', style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '적용 대상' }),
      jsx('p', { style: styles.hint, children: '위에서 정한 대화 모델, 맡기는 방식, 작업 슬롯의 모델과 예비 모델을 저장할 프로필입니다. 처음에는 불러온 프로필 하나만 선택됩니다. 값을 고치거나 대상을 직접 고른 뒤 저장하면 선택한 프로필에 같은 설정을 복사합니다. ‘대화 예비 모델’은 그 카드의 적용 대상과 저장 버튼을 따로 씁니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: allTargetsSelected && profileNames.length > 1 ? 'warn' : 'muted', children: targetSummary }), jsx('span', { style: styles.hint, children: `${selectedTargets.length}개 선택` })] }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: 'model-target-source', size: 'sm', variant: 'secondary', disabled, onClick: selectSourceTargets, children: '불러온 프로필만' }),
          jsx(Button, { id: 'model-target-all', size: 'sm', variant: 'secondary', disabled, onClick: selectAllTargets, children: '모두 선택' }),
          jsx(Button, { id: 'model-target-none', size: 'sm', variant: 'secondary', disabled, onClick: selectNoTargets, children: '모두 해제' })
        ] })
      ] }),
      allTargetsSelected && profileNames.length > 1 ? jsx('p', { role: 'note', style: styles.warning, children: `모든 ${profileNames.length}개 프로필이 적용 대상입니다. 저장하면 확인 단계 없이 바로 적용됩니다.` }) : null,
      jsx('div', { style: { ...styles.profileList, alignItems: 'start' }, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `model-target-${row.name}`, label: row.name,
        detail: selectedTargets.includes(row.name) && nativeSkippedTargets.includes(row.name) ? `맡기는 방식과 예비 모델은 적용하지 않습니다. ${nativeTargetReasons[row.name]}` : undefined,
        checked: selectedTargets.includes(row.name), disabled, onChange: checked => toggleModelTarget(row.name, checked) }) }, row.name))
        .concat(missingModelTargets.map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `model-target-${name}`, label: name,
          detail: '이 프로필을 더 이상 찾을 수 없습니다. 체크를 해제하세요.', checked: true, disabled, onChange: checked => toggleModelTarget(name, checked) }) }, `missing:${name}`))) }),
      jsxs('div', { id: 'model-section-summary', role: 'note', style: { ...styles.cardSection, display: 'flex', flexDirection: 'column', gap: '0.45rem', overflowWrap: 'anywhere' }, children: [
        jsx('strong', { children: '저장할 내용' }),
        jsx('p', { style: styles.hint, children: `적용 대상: ${selectedTargets.join(', ') || '선택 안 됨'}` }),
        jsx('p', { style: styles.hint, children: sectionSaveSummary }),
        nativeSkippedTargets.length ? jsx('p', { id: 'model-section-skipped', style: styles.hint, children: `맡기는 방식과 예비 모델을 적용하지 않는 프로필: ${nativeSkippedTargets.join(', ')}. 이 프로필에는 모델 값만 저장합니다.` }) : null
      ] }),
      sectionSaveError ? jsx('p', { role: 'alert', style: styles.warning, children: sectionSaveError }) : null,
      sectionErrors.models ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.models }) : null,
      jsx(Button, { id: 'model-section-save', size: 'sm', variant: 'secondary', style: { whiteSpace: 'normal', height: 'auto', minHeight: '2.1rem' }, disabled: disabled || sectionSaveBlocked || !sectionWriteNeeded, onClick: () => void saveModelSection(), children: applyPending ? '저장 중…' : `선택한 ${selectedTargets.length}개 프로필에 모델 설정 저장` })
    ]
  })

  const reenableGroup = routingOffProfiles.length || missingReenable.length ? jsxs('fieldset', {
    id: 'routing-reenable', style: { ...styles.fieldset, ...styles.cardSection },
    children: [
      jsx('legend', { style: styles.fieldName, children: '작업 분담이 꺼져 있는 프로필' }),
      jsx('p', { style: styles.hint, children: '작업 분담이 꺼져 있는 프로필입니다. 이전에 꺼 두었거나 플러그인이 아직 준비되지 않은 프로필이 여기에 나옵니다. 꺼진 상태에서는 맡기는 방식을 저장할 수 없고, 맡긴 작업도 거절됩니다. 다시 켜려면 프로필을 고르고 아래 버튼으로 먼저 저장하세요. 모델 값은 바뀌지 않습니다. 저장하면 상태를 다시 불러오므로, 아직 저장하지 않은 다른 편집이 있으면 그것부터 저장하세요.' }),
      jsx('div', { style: styles.profileList, children: routingOffProfiles.map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `routing-reenable-${name}`, label: name, checked: reenableProfiles.includes(name), disabled, onChange: checked => toggleRoutingProfile(name, checked) }) }, name))
        .concat(missingReenable.map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `routing-reenable-${name}`, label: name,
          detail: '이 프로필을 더 이상 찾을 수 없습니다. 체크를 해제하세요.', checked: true, disabled, onChange: checked => toggleRoutingProfile(name, checked) }) }, `missing:${name}`))) }),
      missingReenable.length ? jsx('p', { id: 'routing-reenable-missing', role: 'alert', style: styles.warning, children: vanishedMessage(missingReenable) }) : null,
      jsx(Button, { id: 'routing-reenable-save', size: 'sm', variant: 'secondary', style: { alignSelf: 'flex-start', whiteSpace: 'normal', height: 'auto', minHeight: '2.1rem' }, disabled: disabled || !reenableProfiles.length || storeDrift.length > 0 || missingReenable.length > 0, onClick: () => void saveReenable(), children: `선택한 ${reenableProfiles.length}개 프로필의 작업 분담 다시 켜기` })
    ]
  }) : null

  const timeoutSettingsSection = section('작업별 실행 시간 제한', '불러온 프로필에서 일반 작업, 짧은 작업 슬롯, 긴 작업 슬롯의 시간 제한을 각각 분 단위로 편집하고, 아래 시간 제한 적용 대상에 복사합니다. 짧은 작업 제한은 코드·검증(간단)·컴퓨터 유즈 슬롯에, 긴 작업 제한은 설계·검증(복잡) 슬롯에 적용됩니다. 모델·라우팅·폴백 적용 대상과는 독립적입니다.', jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '0.8rem' },
    children: [
      jsx('p', { id: 'timeout-policy-explanation', role: 'note', style: styles.hint, children: '작업을 얼마나 오래 실행할지 분 단위로 정합니다. 0은 전체 실행 시간을 제한하지 않습니다. 제한에 도달하면 중단을 요청하지만, 실제로 멈추기까지 시간이 걸릴 수 있습니다. 응답 대기 같은 Hermes의 다른 제한은 그대로 유지됩니다. 이전에 하나로 설정했던 값은 짧은 작업과 긴 작업에 같은 값으로 표시됩니다.' }),
      jsx('p', { style: styles.hint, children: '작업을 시작할 때의 설정을 사용합니다. 이미 진행 중인 작업의 시간은 바뀌지 않습니다. 응답 대기나 반복 횟수 등 다른 제한은 별도로 적용됩니다.' }),
      !timeoutSettingsSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '이 연결에서는 시간 제한을 변경할 수 없습니다. 기존 값을 그대로 표시합니다. Hermes와 플러그인 버전을 확인하세요.' }) : null,
      timeoutSettingsSupported && !timeoutRoleSupported ? jsx('p', { role: 'alert', style: styles.warning, children: '이 연결에서는 짧은 작업과 긴 작업의 시간 제한을 따로 변경할 수 없습니다. 기존 값을 유지합니다.' }) : null,
      timeoutSettingsSupported && timeoutRoleSupported && currentRow.timeouts.editable !== true ? jsx('p', { role: 'note', style: styles.warning, children: '이 프로필의 시간 제한은 읽기 전용입니다. 기존 값을 보존합니다.' }) : null,
      timeoutRevisionChanged || timeoutSaveRevisionChanged ? jsx('p', { role: 'alert', style: styles.warning, children: '선택한 프로필의 시간 제한 설정이 다른 곳에서 바뀌었습니다. 덮어쓰지 않도록 저장을 멈췄습니다. 최신 상태를 다시 불러오세요.' }) : null,
      timeoutSettingsSupported && currentRow.timeouts.warnings.length ? jsx('div', { role: 'note', style: styles.warning, children: currentRow.timeouts.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: warning }, index)) }) : null,
      timeoutDraftResult.error ? jsx('p', { role: 'alert', style: styles.warning, children: timeoutDraftResult.error }) : null,
      jsx('div', { style: styles.fields, children: [
        jsx(TimeoutField, {
          id: 'delegate-total-minutes',
          label: '일반 위임 작업 제한 (분)',
          value: draft?.timeouts?.delegate_total_minutes,
          onChange: value => updateTimeout('delegate_total_minutes', value),
          disabled: disabled || timeoutRevisionChanged || !timeoutSettingsEditable,
          describedBy: 'timeout-policy-explanation'
        }),
        jsx(TimeoutField, {
          id: 'routed-light-total-minutes',
          label: '짧은 작업 제한 (분)',
          value: draft?.timeouts?.routed_light_total_minutes,
          onChange: value => updateTimeout('routed_light_total_minutes', value),
          disabled: disabled || timeoutRevisionChanged || !timeoutSettingsEditable,
          describedBy: 'timeout-policy-explanation'
        }),
        jsx(TimeoutField, {
          id: 'routed-heavy-total-minutes',
          label: '긴 작업 제한 (분)',
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
        }).concat(missingTimeoutTargets.map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `timeout-target-${name}`, label: name,
          detail: '이 프로필을 더 이상 찾을 수 없습니다. 체크를 해제하세요.', checked: true, disabled,
          onChange: checked => chooseTimeoutTargets('toggle', name, checked) }) }, `missing:${name}`))) }),
        missingTimeoutTargets.length ? jsx('p', { id: 'timeout-targets-missing', role: 'alert', style: styles.warning, children: vanishedMessage(missingTimeoutTargets) }) : null
      ] }),
      sectionErrors.timeouts ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.timeouts }) : null,
      jsx(Button, { id: 'timeouts-save', size: 'sm', variant: 'secondary', disabled: timeoutSaveDisabled, onClick: () => void saveSection('timeouts'), children: applyPending ? '저장 중…' : '시간 제한 저장' })
    ]
  }))

  const fallbackTargetGroup = (scope, selected, allowEditing) => jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: `${fallbackScopeTitle(scope)} 적용 대상` }),
      jsx('p', { style: styles.hint, children: '처음 열면 편집 가능한 모든 프로필이 선택됩니다. 선택한 프로필에 이 카드 설정을 적용합니다. 체크만으로 저장되지는 않으며, 아래 ‘모델’ 적용 대상과는 별개입니다. ‘불러온 프로필만’은 위에서 설정을 불러온 프로필 하나만 남깁니다.' }),
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
      }).concat(scope !== 'native' ? [] : missingFallbackTargets.map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, {
        id: `${scope}-fallback-target-${name}`, label: name, detail: '이 프로필을 더 이상 찾을 수 없습니다. 체크를 해제하세요.', checked: true, disabled,
        onChange: value => updateFallbackTarget(scope, name, value) }) }, `missing:${name}`))) }),
      scope === 'native' && missingFallbackTargets.length
        ? jsx('p', { id: 'native-fallback-targets-missing', role: 'alert', style: styles.warning, children: vanishedMessage(missingFallbackTargets) }) : null
    ]
  })

  const nativeStatus = currentRow?.fallbacks?.native
  const nativeEditable = fallbackSupported && nativeStatus?.editable === true && Boolean(nativeFallbackDraft)
  const nativeChainText = chain => Array.isArray(chain) && chain.length
    ? chain.map(item => `${item?.provider || '—'}/${item?.model || '—'}`).join(' → ')
    : '없음'
  // The main conversation's spare models (native fallback_providers). It sits in the model section
  // under the conversation models but keeps its own targets, save button and '/fallback-preview' path.
  const nativeFallbackPanel = jsxs('article', { id: 'conversation-fallback', style: styles.roleCard, children: [
    jsxs('div', { style: styles.statusLine, children: [jsx('h3', { style: styles.roleTitle, children: '대화 예비 모델' }), jsx(Badge, { variant: nativeStatus?.enabled ? 'warn' : 'muted', children: nativeStatus?.enabled ? '현재 사용' : nativeStatus ? '현재 꺼짐' : '상태 미지원' }), nativeFallbackDraftChanged ? jsx(Badge, { variant: 'muted', children: '초안 변경' }) : null] }),
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
          jsx(ModelRouteField, {
            ids: { picker: `native-chain-${index}-picker`, provider: `native-chain-${index}-provider`, model: `native-chain-${index}-model` },
            labels: { picker: `우선순위 ${index + 1} 모델`, provider: `우선순위 ${index + 1} 공급자 ID`, model: `우선순위 ${index + 1} 모델 ID` },
            route: entry, disabled, catalog: modelCatalog,
            onChange: (field, value) => updateFallbackDraft('native', current => ({ ...current, chain: current.chain.map((item, at) => at === index ? { ...item, [field]: value } : item) })) }),
          jsxs('div', { style: styles.actions, children: [
            jsx(Button, { id: `native-chain-${index}-up`, size: 'sm', variant: 'secondary', disabled: disabled || index === 0, onClick: () => updateFallbackDraft('native', current => { const chain = [...current.chain]; [chain[index - 1], chain[index]] = [chain[index], chain[index - 1]]; return { ...current, chain } }), children: '위로' }),
            jsx(Button, { id: `native-chain-${index}-down`, size: 'sm', variant: 'secondary', disabled: disabled || index === nativeFallbackDraft.chain.length - 1, onClick: () => updateFallbackDraft('native', current => { const chain = [...current.chain]; [chain[index + 1], chain[index]] = [chain[index], chain[index + 1]]; return { ...current, chain } }), children: '아래로' }),
            jsx(Button, { id: `native-chain-${index}-remove`, size: 'sm', variant: 'secondary', disabled, onClick: () => updateFallbackDraft('native', current => ({ ...current, chain: current.chain.filter((_, at) => at !== index) })), children: '삭제' })
          ] })
        ] }, `native-chain-${index}`)),
        jsx(Button, { id: 'native-chain-add', size: 'sm', variant: 'secondary', disabled: disabled || nativeFallbackDraft.chain.length >= 5, onClick: () => updateFallbackDraft('native', current => ({ ...current, chain: [...current.chain, { provider: '', model: '' }] })), children: '모델 추가' }),
        nativeFallbackError ? jsx('p', { role: 'alert', style: styles.warning, children: nativeFallbackError }) : null
      ] }),
      jsx('p', { role: 'note', style: styles.hint, children: '예비 모델을 사용하면 제공자의 요금제에 따라 추가 비용이 발생할 수 있습니다. 아래 저장을 눌러야 적용됩니다.' }),
      fallbackTargetGroup('native', nativeFallbackTargets, nativeEditable),
      fallbackError?.scope === 'native' ? jsx('p', { role: 'alert', style: styles.warning, children: fallbackError.message }) : null,
      jsx(Button, { id: 'native-fallback-save', size: 'sm', variant: 'secondary', disabled: !canPreviewFallback('native'), onClick: () => void saveFallback('native'), children: applyPending ? '저장 중…' : '대화 예비 모델 저장' })
    ] }) : null
  ] })

  const profileSectionDisabled = disabled || !nativeStorageAvailable
  const profileTargetGroup = profileSectionEditable ? jsxs('fieldset', {
    id: 'profile-section-targets', style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '전문 프로필 위임 적용 대상' }),
      jsx('p', { style: styles.hint, children: '위의 허용 목록·설명·사용 허용을 저장할 프로필입니다. 처음에는 불러온 프로필 하나만 선택됩니다. 전문 프로필에 맡기는 방식으로 저장된 프로필만 고를 수 있으며, 각 프로필의 맡기는 방식과 예비 모델은 바꾸지 않습니다. ‘모델’ 섹션의 적용 대상과는 별개입니다.' }),
      jsxs('div', { style: styles.selectionToolbar, children: [
        jsx('span', { style: styles.hint, children: `${selectedProfileTargets.length}개 선택` }),
        jsxs('div', { style: styles.actions, children: [
          jsx(Button, { id: 'profile-target-source', size: 'sm', variant: 'secondary', disabled: profileSectionDisabled, onClick: () => chooseProfileTargets('source'), children: '불러온 프로필만' }),
          jsx(Button, { id: 'profile-target-all', size: 'sm', variant: 'secondary', disabled: profileSectionDisabled, onClick: () => chooseProfileTargets('all'), children: '가능한 프로필 모두' }),
          jsx(Button, { id: 'profile-target-none', size: 'sm', variant: 'secondary', disabled: profileSectionDisabled, onClick: () => chooseProfileTargets('none'), children: '모두 해제' })
        ] })
      ] }),
      jsx('div', { style: { ...styles.profileList, alignItems: 'start' }, children: profiles.map(row => {
        const checked = selectedProfileTargets.includes(row.name)
        return jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `profile-target-${row.name}`, label: row.name,
          detail: profileTargetReasons[row.name] || undefined, checked,
          disabled: profileSectionDisabled || (Boolean(profileTargetReasons[row.name]) && !checked), onChange: value => chooseProfileTargets('toggle', row.name, value) }) }, row.name)
      }).concat(missingProfileTargets.filter(name => !profileNames.includes(name)).map(name => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `profile-target-${name}`, label: name,
        detail: '이 프로필을 더 이상 찾을 수 없습니다. 체크를 해제하세요.', checked: true,
        disabled: profileSectionDisabled, onChange: value => chooseProfileTargets('toggle', name, value) }) }, `missing:${name}`))) }),
      jsxs('div', { id: 'profile-section-summary', role: 'note', style: { ...styles.cardSection, display: 'flex', flexDirection: 'column', gap: '0.45rem', overflowWrap: 'anywhere' }, children: [
        jsx('strong', { children: '저장할 내용' }),
        jsx('p', { style: styles.hint, children: `적용 대상: ${selectedProfileTargets.join(', ') || '선택 안 됨'}` }),
        jsx('p', { style: styles.hint, children: profileSaveSummary })
      ] }),
      profileSaveError ? jsx('p', { role: 'alert', style: styles.warning, children: profileSaveError }) : null,
      sectionErrors.profiles ? jsx('p', { role: 'alert', style: styles.warning, children: sectionErrors.profiles }) : null,
      jsx(Button, { id: 'profile-section-save', size: 'sm', variant: 'secondary', style: { whiteSpace: 'normal', height: 'auto', minHeight: '2.1rem' }, disabled: profileSectionDisabled || Boolean(profileSaveError) || !profilesWriteNeeded, onClick: () => void saveProfileSection(), children: applyPending ? '저장 중…' : `선택한 ${selectedProfileTargets.length}개 프로필에 전문 프로필 설정 저장` })
    ]
  }) : null
  const profileDelegationSection = section('전문 프로필 위임', '에이전트가 작업을 다른 전문 프로필에 맡길 수 있게 허용합니다. 맡길 수 있는 프로필과 위임용 설명을 정하고, 아래 적용 대상에서 고른 프로필에 따로 저장합니다. 모델 설정과는 별도로 저장합니다.', jsxs('div', { id: 'profile-delegation', style: { display: 'flex', flexDirection: 'column', gap: '1rem' }, children: [
    jsx(ProfileDelegationCard, { dto: currentRow?.native_delegation, draft: nativeDelegationDraft, profiles, origin: selectedProfile,
      roleScope: { scopeKey, ownerProfile: activeProfile || 'default', connectionId, baseIdentity: statusQuery.data?.readiness_context?.base_identity, available: statusQuery.data?.role_proposal?.available === true, generation: renderGeneration },
      targets: selectedProfileTargets, disabled: profileSectionDisabled || !profileSectionEditable, onChange: updateNativeDelegationDraft }),
    profileTargetGroup
  ] }))

  const localCombinedSummary = currentRow && draft && statusQuery.data
    ? buildCombinedPreviewBody(statusQuery.data.revision, selectedProfile, draft, modelWriteTargets, loadedRoutingProfiles,
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
    { scope: 'native', label: '대화 예비 모델', changed: nativeFallbackDraftChanged || fallbackTargetEdits.native, count: nativeFallbackTargets.length }
  ].filter(item => item.changed)
  const timeoutSummary = !timeoutSettingsSupported
    ? '시간 제한을 확인할 수 없어 변경하지 않습니다'
    : !timeoutRoleSupported
      ? '역할별 시간 제한 지원 미확인 · 표시만 가능'
      : localCombinedSummary?.body.timeout_updates?.length
        ? `전체 실행 시간 변경: ${localCombinedSummary.body.timeout_updates.length}개 대상 · 일반 ${draft?.timeouts?.delegate_total_minutes}분 / 짧은 작업 ${draft?.timeouts?.routed_light_total_minutes}분 / 긴 작업 ${draft?.timeouts?.routed_heavy_total_minutes}분`
        : timeoutWriteRequested
          ? '시간 제한의 입력값과 대상 프로필 상태를 다시 확인하세요.'
          : `전체 실행 시간 변경 없음 · 시간 제한 대상 ${selectedTimeoutTargets.length}개 선택 · 불러온 ${selectedProfile} 프로필 값 일반 ${draft?.timeouts?.delegate_total_minutes}분 / 짧은 작업 ${draft?.timeouts?.routed_light_total_minutes}분 / 긴 작업 ${draft?.timeouts?.routed_heavy_total_minutes}분`
  const scopeDraftErrors = [
    [nativeFallbackDraftChanged || fallbackTargetEdits.native, nativeFallbackError]
  ].filter(([changed, error]) => changed && error).map(([, error]) => error)
  const summaryValidationErrors = [...new Set([...(localCombinedSummary?.errors || []), ...summaryProjectedErrors, ...scopeDraftErrors, ...(routingTargetError ? [routingTargetError] : []), ...(noTargetError ? [noTargetError] : [])])]
  // The whole-page save writes the model targets, the time-limit targets and the conversation spare
  // models' targets; a vanished ticked name in any list it would write blocks it by name.
  const pageVanished = [...new Set([
    ...((modelWriteNeeded || routingCopyPending) ? missingModelTargets : []),
    ...(timeoutWriteRequested ? missingTimeoutTargets : []),
    ...((nativeFallbackDraftChanged || fallbackTargetEdits.native) ? missingFallbackTargets : [])])]
  const canSaveAll = Boolean(currentRow && draft && statusQuery.data && !disabled && !timeoutRevisionChanged && !liveDrift.length && !pageVanished.length)

  return jsxs('main', {
    style: styles.page,
    children: [
      jsxs('header', { style: styles.header, children: [jsxs('div', { children: [jsx('p', { style: { color: 'var(--ui-accent)', fontSize: '0.72rem', fontWeight: 650, letterSpacing: '0.08em', margin: '0 0 0.45rem' }, children: 'HERMES DESKTOP · 모델 제어' }), jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsx('p', { style: styles.subtitle, children: '대화와 작업에 쓸 모델을 정하고, 원하는 프로필에 함께 적용하세요. 바꿀 대상과 내용을 확인한 뒤 저장하면 됩니다.' })] }), jsx(Button, { size: 'sm', variant: 'secondary', disabled: setupPending || profilePreparationReloadBlocked(scopeKey) || statusQuery.isFetching || applyPending, onClick: () => void reloadStatus(), children: '상태 새로고침' })] }),
      jsx('div', { role: 'note', style: styles.notice, children: '새 규칙은 이후에 시작하는 세션과 허용된 작업에 적용됩니다. 이미 진행 중인 세션의 모델은 자동으로 바뀌지 않습니다.' }),
      jsx(InitialSetupCard, { pluginContext, data: statusQuery.data, scopeKey, settingsBusy: applyPending || setupPending || statusQuery.isFetching, begin: beginProfilePreparation, finish: finishProfilePreparation, onPrepared: profilePreparationChanged }),
      jsx(ProfilePreparationCard, { pluginContext, data: statusQuery.data, scopeKey, settingsBusy: applyPending || setupPending || statusQuery.isFetching, begin: beginProfilePreparation, finish: finishProfilePreparation, onPrepared: profilePreparationChanged }),
      profiles.length === 0 ? jsx('div', { role: 'status', style: styles.notice, children: '관리할 프로필이 없습니다. Hermes에서 프로필을 만든 뒤 상태를 새로고침하세요.' }) : null,
      profiles.length ? section('불러올 프로필', '아래에 불러올 설정을 고릅니다. 실제로 바꿀 프로필은 각 카드의 적용 대상에서 따로 선택하세요.', jsxs('div', { style: styles.fields, children: [jsx(ChoiceField, { id: 'profile-select', label: '프로필', value: selectedProfile || '', disabled: disabled || !profiles.length, onChange: selectProfile, options: profiles.map(row => ({ value: row.name, label: row.name })) }), jsx('div', { style: { ...styles.field, justifyContent: 'flex-end' }, children: jsx('span', { style: styles.hint, children: `지금 사용 중인 프로필: ${activeProfile || '확인 중'}` }) })] }), currentRow ? jsx(StatusView, { profile: currentRow }) : null) : null,
      profiles.length ? section('모델', '대화에 쓸 모델과 그 예비 모델, 나눠 맡기는 작업에 쓸 모델을 한곳에서 정합니다. 대화 예비 모델은 그 카드의 적용 대상과 저장 버튼을 쓰고, 나머지는 맨 아래 적용 대상에서 고른 프로필에만 저장합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1.4rem' }, children: [
        jsxs('div', { id: 'conversation-models', style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [jsx('h3', { style: styles.roleTitle, children: '대화 모델' }), modelFields] }),
        nativeFallbackPanel,
        jsx(NativeDelegationCard, { dto: currentRow?.native_delegation, draft: nativeDelegationDraft, catalog: modelCatalog,
          targets: nativeWriteTargets, disabled: disabled || !nativeStorageAvailable,
          slots: { support: slotInfo, draft: draft?.slots || null, models: draft?.models || null, disabled, onFollow: changeSlotFollow, onRoute: updateSlotRoute,
            firstSave: profiles.every(row => !(row.slots?.stored || []).length && row.native_delegation?.policy_schema !== 2 && row.native_delegation?.auto_policy_schema !== 2) },
          onChange: updateNativeDelegationDraft }),
        reenableGroup,
        modelTargetGroup
      ] })) : null,
      profiles.length ? profileDelegationSection : null,
      profiles.length ? timeoutSettingsSection : null,
      pageVanished.length ? jsx('div', { id: 'page-vanished-alert', role: 'alert', style: styles.warning, children: `전체 저장: ${vanishedMessage(pageVanished)}` }) : null,
      !revisionChanged && liveDrift.length ? jsx('div', { id: 'live-drift-alert', role: 'alert', style: styles.warning, children: liveDriftMessage(liveDrift) }) : null,
      revisionChanged ? jsx('div', { role: 'alert', style: styles.warning, children: '다른 화면에서 설정이 변경되어 저장을 잠갔습니다. 편집값은 아직 보존되어 있습니다. 필요한 값을 확인한 뒤 상태 새로고침으로 최신 설정을 불러와 다시 편집하세요.' }) : null,
      pageError ? jsx('div', { role: 'alert', style: styles.warning, children: pageError }) : null,
      applyOutcome ? jsxs('div', { role: 'status', 'aria-live': 'polite', style: applyOutcome.kind === 'success' ? styles.message : styles.warning, children: [jsx('strong', { children: applyOutcome.kind === 'prepared' ? '플러그인 준비 상태가 달라졌습니다.' : applyOutcome.kind === 'success' ? '적용 요청이 완료되었습니다.' : applyOutcome.kind === 'partial' ? '일부 설정만 적용되었을 수 있습니다.' : '적용 결과를 확인할 수 없습니다.' }), jsx('p', { style: styles.hint, children: applyOutcome.message || (applyOutcome.kind === 'success' ? (autoReloading ? '저장한 상태를 다시 불러오고 있습니다. 끝나면 바로 편집을 이어갈 수 있습니다.' : needsReload ? '저장했습니다. 저장한 상태를 자동으로 다시 불러오지 못했습니다. 아래 버튼으로 다시 불러오세요.' : '저장한 상태를 다시 불러왔습니다. 편집을 이어가세요.') : '다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요.') }), applyOutcome.result ? jsxs('details', { children: [jsx('summary', { style: { cursor: 'pointer', fontSize: '0.8rem' }, children: '세부 결과 보기 · 고급' }), jsx('pre', { style: styles.value, children: readableValue(applyOutcome.result) })] }) : null] }) : null,
      nativeFence ? jsxs('div', { id: 'native-save-recovery', style: styles.warning, children: [
        jsx('p', { children: nativeFence.foreignScope ? '다른 연결에서 시작한 저장 결과를 확인해야 합니다. 저장을 시작한 원래 연결과 프로필로 돌아가 주세요.' : nativeFence.state === 'pending' ? '이전에 시작한 저장이 끝났는지 확인해야 합니다. 같은 설정을 다시 저장하지 마세요.' : nativeFence.state === 'settled' ? '이전에 저장한 결과를 다시 불러온 뒤 편집할 수 있습니다.' : '이전 저장 결과를 확인할 수 없습니다. 같은 설정을 다시 저장하지 말고, 원래 연결에서 저장 작업이 끝났는지 확인하세요.' }),
        (nativeFence.state === 'unknown' || (nativeFence.state === 'pending' && !applyPending)) && !nativeFence.foreignScope ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.6rem' }, children: [
          jsx(CheckRow, { id: 'native-save-recovery-confirm', label: '이전 저장 작업이 끝난 것을 확인했습니다', checked: nativeRecoveryConfirmed, disabled: statusQuery.isFetching, onChange: setNativeRecoveryConfirmed }),
          jsx(Button, { id: 'native-save-recover', size: 'sm', variant: 'secondary', disabled: !nativeRecoveryConfirmed || statusQuery.isFetching || nativeFence.unavailable, onClick: () => void reloadStatus(), children: '확인한 설정 다시 불러오기' })
        ] }) : null
      ] }) : null,
      needsReload || nativeFence ? jsx('div', { style: styles.actions, children: jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching || nativeFence?.state === 'pending', onClick: () => void reloadStatus(), children: statusQuery.isFetching ? '상태 확인 중…' : '실제 상태 확인 후 편집 재개' }) }) : null,
      profiles.length && !needsReload ? section('기본 모델·시간·기타 설정 함께 저장', '위에서 편집한 대화 모델·작업 슬롯 모델·대화 예비 모델·시간 제한을 한 번에 저장합니다. 각 카드에서 고른 적용 대상은 그대로 따릅니다. 맡기는 방식, 슬롯별 예비 모델, 작업 분담 다시 켜기, 전문 프로필 위임은 여기 포함되지 않으며 각 섹션의 버튼으로 저장합니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [
        jsx('div', { id: 'draft-reference-summary', role: 'note', style: styles.section, children: [
          jsx('strong', { children: '현재 초안 요약 · 참고 정보' }),
          jsx('p', { style: styles.hint, children: `대화 모델 적용 ${modelWriteTargets.length}개 (${modelWriteTargets.join(', ') || '바뀐 내용 없음 · 기존 설정 유지'}) · 작업 슬롯 모델 적용 ${routingWriteTargets.length}개 (${routingWriteTargets.join(', ') || '기존 설정 유지'})` }),
          jsx('p', { style: styles.hint, children: modifiedFallbackSummary.length
            ? `수정한 예비 모델: ${modifiedFallbackSummary.map(item => `${item.label} ${item.count}개 대상`).join(' · ')}`
            : '수정한 대화 예비 모델 없음' }),
          jsx('p', { style: styles.hint, children: timeoutSummary }),
          jsx('p', { style: styles.hint, children: '저장 전 변경 내용을 요약한 참고 정보입니다. 실제 반영 결과는 저장 후 상태를 다시 불러와 확인하세요.' }),
          summaryValidationErrors.length ? jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '확인할 항목' }), jsx('ul', { children: summaryValidationErrors.map((error, index) => jsx('li', { children: error }, index)) })] }) : jsx('p', { role: 'status', style: styles.hint, children: '입력한 내용을 확인했습니다. 저장할 때 최신 설정과 다시 비교합니다.' })
        ] }),
        jsx(Button, { id: 'global-save', size: 'sm', variant: 'secondary', disabled: !canSaveAll, onClick: () => void saveAll(), children: applyPending ? '저장 중…' : '저장' })
      ] })) : null
    ]
  })
}

// The execution roster is a passive projection, not a second native runtime.
const EXECUTION_EMPTY_ATOM = { get: () => null, listen: () => () => {} }
const EXECUTION_PROFILE = /^[a-z0-9][a-z0-9_-]{0,63}$/
export function executionId(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 256 && value === value.trim() && !/[\x00-\x1f\x7f]/.test(value)
}
export function executionScopeKey(scope) {
  return scope && executionId(scope.connectionId) && executionId(scope.profile) && executionId(scope.sessionId)
    ? JSON.stringify([scope.connectionId, scope.profile, scope.sessionId]) : null
}
export function selectExecutionRoute(routes, scope) {
  if (!executionScopeKey(scope) || !Array.isArray(routes)) return null
  const matches = routes.filter(row => row && ['local', 'remote'].includes(row.mode) && row.connectionId === scope.connectionId &&
    row.profile === scope.profile && typeof row.targetProfile === 'string' && EXECUTION_PROFILE.test(row.targetProfile))
  return matches.length === 1 ? { ...matches[0] } : null
}
function executionUnknown() { return { kind: 'unknown', role: null, profile: null, evidence: 'unknown' } }
export function executionIdentity(value) {
  if (!value || typeof value !== 'object') return executionUnknown()
  if (value.kind === 'model' && ['heavy', 'light'].includes(value.role) && value.profile == null) {
    const slot = TASK_SLOTS.some(item => item.id === value.slot) ? value.slot : null
    return { kind: 'model', role: value.role, profile: null, slot, evidence: value.evidence === 'runtime_reported' ? 'runtime_reported' : 'unknown' }
  }
  if (value.kind === 'profile' && typeof value.profile === 'string' && EXECUTION_PROFILE.test(value.profile) && value.role == null) {
    return { kind: 'profile', role: null, profile: value.profile, evidence: value.evidence === 'runtime_reported' ? 'runtime_reported' : 'unknown' }
  }
  return executionUnknown()
}
export function executionLabel(identity) {
  const known = executionIdentity(identity)
  const slot = known.kind === 'model' && TASK_SLOTS.find(item => item.id === known.slot)
  return known.kind === 'model' ? `모델 · ${slot ? slot.label : known.role === 'heavy' ? 'Heavy' : 'Light'}` : known.kind === 'profile' ? `프로필 · ${known.profile}` : '실행 종류 미확인'
}
function executionSafeText(value, limit = 256) {
  return typeof value === 'string' && value.length <= limit && value === value.trim() && !/[\x00-\x1f\x7f]/.test(value) ? value : null
}
const NATIVE_TERMINAL = new Set(['completed', 'error', 'failed', 'interrupted', 'cancelled', 'timeout'])
const NATIVE_STATUS = new Set(['requested', 'dispatched', 'queued', 'running', ...NATIVE_TERMINAL, 'unknown'])
const nativeStatus = value => NATIVE_STATUS.has(value) ? value : 'unknown'
const executionCount = value => Number.isSafeInteger(value) && value >= 0 ? value : null
const executionSeconds = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
function executionTool(value) {
  return typeof value === 'string' && /^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$/.test(value) ? value : null
}
const EXECUTION_TOKEN_BUCKETS = ['input', 'cache_read', 'cache_write', 'output']
function executionTokens(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const tokens = {}
  for (const key of EXECUTION_TOKEN_BUCKETS) {
    const count = value[key] ?? 0
    if (!Number.isSafeInteger(count) || count < 0) return null
    tokens[key] = count
  }
  return tokens
}
function executionObservedTokens(row) {
  const tokens = executionTokens(row?.tokens)
  return tokens ? EXECUTION_TOKEN_BUCKETS.reduce((sum, key) => sum + tokens[key], 0) : null
}
// Prompt (uncached + cached) plus output: the same total Hermes reports for a session. The native
// completion total wins: it also counts usage the per-call hook does not see (e.g. MoA advisors).
export function executionTokenTotal(row) {
  return executionCount(row?.token_total) ?? executionObservedTokens(row)
}
export function executionTokenText(count) {
  if (!Number.isSafeInteger(count) || count < 0) return null
  const trim = value => value.toFixed(1).replace(/\.0$/, '')
  if (count < 1000) return `${count}`
  if (count < 9950) return `${trim(count / 1000)}천`
  if (count < 99500) return `${trim(count / 10000)}만`
  if (count < 99995000) return `${Math.round(count / 10000)}만`
  return `${trim(count / 100000000)}억`
}
function executionActivity(input = {}, runtime = null) {
  return {
    child_session_id: executionId(runtime?.child_session_id) ? runtime.child_session_id : executionId(input.child_session_id) ? input.child_session_id : null,
    started_at: executionSeconds(runtime?.started_at) ?? executionSeconds(input.started_at),
    activity_at: executionSeconds(input.activity_at),
    last_tool: executionTool(runtime?.last_tool) || executionTool(input.last_tool),
    tool_count: executionCount(runtime?.tool_count) ?? executionCount(input.tool_count),
    api_call_count: executionCount(input.api_call_count),
    tokens: executionTokens(input.tokens),
    duration_seconds: executionSeconds(input.duration_seconds)
  }
}
function executionNativeCall(input) {
  if (!executionId(input.delegation_id)) return null
  if (Object.prototype.hasOwnProperty.call(input, 'async_unit_id') &&
    (!executionId(input.async_unit_id) || input.async_unit_id !== input.delegation_id)) return null
  const value = Object.prototype.hasOwnProperty.call(input, 'native_call_delegation_id')
    ? input.native_call_delegation_id : input.delegation_id
  // Legacy one-unit rows used the same ID for both. Never infer a split call
  // by stripping suffixes; new backends supply the explicit native call ID.
  return executionId(value) ? value : null
}
function executionModelPair(input, runtime) {
  const api = executionSafeText(input.model)
  if (api) {
    // Distinct model/provider pairs in call order; more than one means Hermes switched to a spare.
    const models = (Array.isArray(input.models) ? input.models.slice(0, 4) : [])
      .map(item => ({ model: executionSafeText(item?.model), provider: executionSafeText(item?.provider) }))
      .filter(item => item.model && !item.model.includes('..') && !/\s/.test(item.model))
    return { model: api, provider: executionSafeText(input.provider), model_source: 'api', models, models_truncated: input.models_truncated === true }
  }
  const route = executionSafeText(input.observed?.model)
  if (route) return { model: route, provider: executionSafeText(input.observed?.provider), model_source: 'route' }
  const roster = executionSafeText(runtime?.model)
  return roster ? { model: roster, provider: null, model_source: 'roster' } : { model: null, provider: null, model_source: null }
}
const EXECUTION_MODEL_SOURCE = { api: 'API 호출 기준', route: '런타임 보고', roster: '시작 시 배정 · 예비 모델 전환 미반영' }
const executionPairText = item => `${item.model}${item.provider ? ` · ${item.provider}` : ''}`
const executionSamePair = (a, b) => a?.model === b?.model && (a?.provider || null) === (b?.provider || null)
// Model/provider transitions observed in the child's own API REQUESTS (attempts, not confirmed
// replies), in order; when bounded, the first and the latest transitions are kept. Usually Hermes' spare-model handling, but a provider can also substitute a model, so
// this is not labelled a spare switch, and the first observed pair is not claimed to be the routed one.
export function executionSpare(row) {
  const models = row?.model_source === 'api' && Array.isArray(row.models) ? row.models : []
  if (models.length < 2 || !row.model) return null
  const current = { model: row.model, provider: row.provider || null }
  return { first: models[0], current, changed: !executionSamePair(models[0], current), observed: models }
}
function executionModelText(row) {
  if (!row.model) return null
  const spare = executionSpare(row)
  if (spare) {
    const steps = spare.observed.map(executionPairText)
    const path = row.models_truncated ? `${steps[0]} → … → ${steps.slice(1).join(' → ')}` : steps.join(' → ')
    return `${executionPairText(spare.current)} (API 호출 기준 · 모델 변경 관찰: ${path})`
  }
  return `${executionPairText(row)} (${EXECUTION_MODEL_SOURCE[row.model_source] || '보고된 모델'})`
}
export function mergeExecutionRows(snapshot, live, targetProfile) {
  if (!snapshot || snapshot.schema !== 1 || snapshot.origin_profile !== targetProfile || !Array.isArray(snapshot.rows)) return []
  const seen = new Set(), rows = [], correlatedLive = new Set()
  const nativeAvailable = Array.isArray(live?.subagents)
  const native = nativeAvailable ? live.subagents.slice(0, 512) : []
  for (const input of snapshot.rows.slice(0, 128)) {
    if (!input || !executionId(input.id) || seen.has(input.id) || input.execution_mode !== 'native' ||
      !Number.isInteger(input.task_index) || input.task_index < 0 || !executionId(input.conversation_id) || !executionId(input.parent_session_id)) continue
    seen.add(input.id)
    const observed = executionIdentity(input.observed), requested = executionIdentity(input.requested)
    const callId = executionNativeCall(input)
    const declaredUnit = Object.prototype.hasOwnProperty.call(input, 'async_unit_id') ? input.async_unit_id : input.delegation_id
    const unitId = executionId(declaredUnit) && declaredUnit === input.delegation_id ? declaredUnit : null
    const matches = executionId(input.subagent_id) ? native.filter(row => row?.subagent_id === input.subagent_id &&
      callId && row.delegation_id === callId) : []
    // The authenticated parent roster plus BOTH native IDs bind the execution.
    // Its stored child session may legitimately rotate during compaction.
    const runtime = matches.length === 1 ? matches[0] : null
    if (runtime) correlatedLive.add(runtime)
    const recorded = nativeStatus(input.status)
    const terminal = NATIVE_TERMINAL.has(recorded)
    const observationGap = !terminal && nativeAvailable && !runtime && executionId(input.subagent_id) &&
      (recorded === 'dispatched' || recorded === 'running' || recorded === 'queued')
    // Terminal hook evidence is sticky; roster disappearance is never success.
    const status = terminal ? recorded : runtime && nativeStatus(runtime.status) !== 'unknown' ? nativeStatus(runtime.status) : observationGap ? 'unknown' : recorded
    rows.push({ id: input.id, execution_mode: 'native', requested, observed, status,
      last_status: observationGap ? recorded : null, observation_gap: Boolean(observationGap),
      subagent_id: executionId(input.subagent_id) ? input.subagent_id : null,
      delegation_id: executionId(input.delegation_id) ? input.delegation_id : null,
      async_unit_id: unitId, native_call_delegation_id: callId,
      conversation_id: input.conversation_id, parent_session_id: input.parent_session_id, task_index: input.task_index,
      // Keep model and provider as one pair from one source: the child's API-call hooks, then the
      // route report, then the native roster's start-time assignment (which never sees a spare switch).
      ...executionModelPair(input, terminal ? null : runtime), backend: executionSafeText(input.observed?.backend, 64),
      ...executionActivity(input, terminal ? null : runtime),
      updated_at: executionSeconds(input.updated_at) })
  }
  // An uncorrelated native child stays unknown. Never match by goal/model/order.
  const liveSeen = new Set()
  for (const item of native.slice(0, 128)) {
    if (!executionId(item?.subagent_id) || correlatedLive.has(item)) continue
    const delegation = executionId(item.delegation_id) ? item.delegation_id : null
    const id = `live:${delegation || 'unbound'}:${item.subagent_id}`
    if (liveSeen.has(id)) continue
    liveSeen.add(id)
    rows.push({ id, execution_mode: 'native', requested: executionUnknown(), observed: executionUnknown(),
      status: nativeStatus(item.status), subagent_id: item.subagent_id, delegation_id: delegation, task_index: null,
      ...executionModelPair({}, item), backend: null, ...executionActivity({}, item) })
  }
  return rows.slice(0, 128)
}
// Public-event projection only. No RPC, subscription, storage or backend dial is
// performed here. Wiring it to the released SDK is a separately verified gate.
const EXECUTION_REPLAY_TYPES = new Set(['subagent.spawn_requested', 'subagent.start', 'subagent.progress', 'subagent.tool', 'subagent.thinking', 'subagent.complete'])
const executionReplayId = value => typeof value === 'string' && !value.includes('..') && /^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$/.test(value)
const executionOutcome = value => value === 'failed' ? 'error' : value
const executionReplayBinding = value => JSON.stringify([value.native_call_delegation_id, value.subagent_id, value.task_index])
export function projectExecutionReplay(reply, scope, cursor = {}, receivedAt = null, parentAliases = []) {
  const key = executionScopeKey(scope)
  const invalid = () => ({ scope_key: key, valid: false, events: [], coverage_gap: true, needs_recovery: true, reason: 'invalid_replay' })
  if (!key || !executionReplayId(scope.sessionId) || !reply || !Array.isArray(reply.events) || reply.events.length > 4096 ||
      !executionReplayId(reply.replay_epoch) || (reply.epoch !== undefined && reply.epoch !== reply.replay_epoch) ||
      executionCount(reply.latest_seq) === null || reply.last_sequence !== reply.latest_seq ||
      reply.count !== reply.events.length || typeof reply.truncated !== 'boolean' || typeof reply.snapshot_required !== 'boolean') return invalid()
  const epoch = reply.replay_epoch, latest = reply.latest_seq
  if ((Object.hasOwn(cursor, 'last_sequence') && executionCount(cursor.last_sequence) === null) ||
      (cursor.replay_epoch != null && !executionReplayId(cursor.replay_epoch)) ||
      (cursor.scope_key != null && cursor.scope_key !== key) ||
      (cursor.replay_epoch === epoch && executionCount(cursor.latest_seq) !== null && latest < cursor.latest_seq)) return invalid()
  const previous = executionCount(cursor.last_sequence) ?? 0
  if (cursor.replay_epoch !== epoch && !reply.snapshot_required) return invalid()
  if (cursor.replay_epoch !== epoch || reply.snapshot_required || reply.truncated) {
    if (reply.events.length) return invalid()
    return { scope_key: key, valid: true, events: [], replay_epoch: epoch, last_sequence: 0, latest_seq: latest,
      coverage_gap: cursor.replay_epoch != null, needs_recovery: true,
      reason: cursor.replay_epoch == null ? 'bootstrap_required' : cursor.replay_epoch !== epoch ? 'epoch_changed' : 'replay_gap' }
  }
  if (previous > latest || reply.events.length !== latest - previous) return invalid()
  // Sort references transiently; neither the raw reply nor any raw frame escapes
  // into the returned cache projection (including uninteresting event types).
  const ordered = reply.events.slice().sort((a, b) => a?.seq - b?.seq)
  const parents = new Set([scope.sessionId, ...(Array.isArray(parentAliases) ? parentAliases.slice(0, 256).filter(executionReplayId) : [])])
  const events = []
  for (let index = 0; index < ordered.length; index++) {
    const frame = ordered[index]
    if (!frame || !parents.has(frame.session_id) || frame.replay_epoch !== epoch || frame.seq !== previous + index + 1) return invalid()
    if (!EXECUTION_REPLAY_TYPES.has(frame.type)) continue
    const value = frame.payload
    if (!value || !executionReplayId(value.delegation_id) || !executionReplayId(value.subagent_id) ||
        !Number.isSafeInteger(value.task_index) || value.task_index < 0) continue
    const terminal = frame.type === 'subagent.complete'
    if (terminal && !NATIVE_TERMINAL.has(value.status)) continue
    events.push({ native_call_delegation_id: value.delegation_id, subagent_id: value.subagent_id, task_index: value.task_index,
      type: frame.type, status: terminal ? value.status : frame.type === 'subagent.spawn_requested' ? 'queued' : 'running',
      reported_child_session_id: executionReplayId(value.child_session_id) ? value.child_session_id : null,
      tool_count: executionCount(value.tool_count), api_call_count: executionCount(value.api_calls),
      // subagent.complete reports the child's session prompt (incl. cache) and output totals.
      token_total: terminal && executionCount(value.input_tokens) !== null && executionCount(value.output_tokens) !== null &&
        Number.isSafeInteger(value.input_tokens + value.output_tokens) ? value.input_tokens + value.output_tokens : null,
      duration_seconds: executionSeconds(value.duration_seconds), last_tool: executionTool(value.tool_name),
      replay_epoch: epoch, sequence: frame.seq, received_at: executionSeconds(receivedAt) })
  }
  return { scope_key: key, valid: true, events, replay_epoch: epoch, last_sequence: latest, latest_seq: latest,
    coverage_gap: false, needs_recovery: false, reason: null }
}
export function createExecutionReplayStore() {
  const scopes = new Map(), retention = new Map()
  let revision = 0
  const obtain = scope => {
    const key = executionScopeKey(scope)
    if (!key) return null
    let entry = scopes.get(key)
    if (!entry) entry = { key, revision: ++revision, replay_epoch: null, last_sequence: 0, latest_seq: 0, coverage_gap: false, needs_recovery: true, reason: 'bootstrap_required', records: new Map() }
    scopes.delete(key); scopes.set(key, entry)
    while (scopes.size > 16) {
      const [oldKey, oldEntry] = scopes.entries().next().value
      for (const binding of oldEntry.records.keys()) retention.delete(JSON.stringify([oldKey, binding]))
      scopes.delete(oldKey)
    }
    return entry
  }
  const cursor = entry => ({ scope_key: entry.key, revision: entry.revision, replay_epoch: entry.replay_epoch, last_sequence: entry.last_sequence, latest_seq: entry.latest_seq })
  return {
    cursor(scope) { const entry = obtain(scope); return entry ? cursor(entry) : null },
    clear() { scopes.clear(); retention.clear(); revision++ },
    recoverFrom(scope, token, sequence) {
      const entry = scopes.get(executionScopeKey(scope))
      if (!entry || !token || JSON.stringify(token) !== JSON.stringify(cursor(entry)) ||
          !entry.needs_recovery || executionCount(sequence) === null || sequence > entry.latest_seq) return false
      entry.last_sequence = sequence; entry.coverage_gap = true; entry.revision = ++revision
      return true
    },
    forget(scope) {
      const key = executionScopeKey(scope), entry = scopes.get(key)
      if (entry) for (const binding of entry.records.keys()) retention.delete(JSON.stringify([key, binding]))
      scopes.delete(key)
    },
    accept(scope, token, reply, receivedAt = null, parentAliases = []) {
      const key = executionScopeKey(scope), entry = scopes.get(key)
      if (!entry || !token || JSON.stringify(token) !== JSON.stringify(cursor(entry))) return { accepted: false, reason: 'stale_replay' }
      const result = projectExecutionReplay(reply, scope, token, receivedAt, parentAliases)
      if (!result.valid) {
        entry.coverage_gap = true; entry.needs_recovery = true; entry.reason = result.reason
        for (const [binding, value] of entry.records) if (!NATIVE_TERMINAL.has(value.status)) {
          entry.records.delete(binding); retention.delete(JSON.stringify([key, binding]))
        }
        entry.revision = ++revision; return { accepted: false, reason: result.reason }
      }
      const epochChanged = entry.replay_epoch !== result.replay_epoch
      entry.replay_epoch = result.replay_epoch; entry.last_sequence = result.last_sequence; entry.latest_seq = result.latest_seq
      entry.coverage_gap ||= result.coverage_gap
      entry.needs_recovery = result.needs_recovery; entry.reason = result.reason
      if (epochChanged || result.needs_recovery) {
        // Keep explicitly observed terminal facts, but old nonterminal frames
        // are not evidence that a child is still running in a fresh stream.
        for (const [binding, value] of entry.records) if (!NATIVE_TERMINAL.has(value.status)) {
          entry.records.delete(binding); retention.delete(JSON.stringify([key, binding]))
        }
      }
      for (const event of result.events) {
        const binding = executionReplayBinding(event), old = entry.records.get(binding)
        const terminal = NATIVE_TERMINAL.has(event.status), settled = NATIVE_TERMINAL.has(old?.status)
        if (settled && !terminal) continue
        const conflict = Boolean(old?.terminal_conflict || settled && terminal && executionOutcome(old.status) !== executionOutcome(event.status))
        const next = { ...event, terminal_conflict: conflict,
          tool_count: event.tool_count ?? old?.tool_count ?? null,
          api_call_count: event.api_call_count ?? old?.api_call_count ?? null,
          token_total: event.token_total ?? old?.token_total ?? null,
          duration_seconds: event.duration_seconds ?? old?.duration_seconds ?? null,
          last_tool: event.last_tool ?? old?.last_tool ?? null }
        entry.records.set(binding, next)
        const retentionKey = JSON.stringify([key, binding])
        retention.delete(retentionKey); retention.set(retentionKey, { key, binding })
        while (retention.size > 512) {
          const [oldKey, oldest] = retention.entries().next().value
          const owner = scopes.get(oldest.key)
          if (owner) { owner.records.delete(oldest.binding); owner.coverage_gap = true }
          retention.delete(oldKey)
        }
      }
      entry.revision = ++revision
      return { accepted: true, needs_recovery: result.needs_recovery, reason: result.reason, cursor: cursor(entry) }
    },
    snapshot(scope) {
      const entry = scopes.get(executionScopeKey(scope))
      return entry ? { scope_key: entry.key, replay_epoch: entry.replay_epoch, last_sequence: entry.last_sequence,
        coverage_gap: entry.coverage_gap, needs_recovery: entry.needs_recovery, reason: entry.reason, records: [...entry.records.values()].map(value => ({ ...value })) } : null
    },
    counts() { return { scopes: scopes.size, records: retention.size } }
  }
}
export function overlayExecutionReplay(rows, projection, scope) {
  if (!Array.isArray(rows)) return []
  if (!projection || projection.scope_key !== executionScopeKey(scope) || !Array.isArray(projection.records)) return rows
  return rows.map(row => {
    if (row.execution_mode !== 'native' || !executionId(row.subagent_id) || !Number.isSafeInteger(row.task_index) || row.task_index < 0) return row
    const call = executionNativeCall(row)
    if (!call) return row
    const matches = projection.records.filter(value => value.native_call_delegation_id === call && value.subagent_id === row.subagent_id && value.task_index === row.task_index)
    if (matches.length !== 1) return row
    const event = matches[0], terminal = NATIVE_TERMINAL.has(event.status), settled = NATIVE_TERMINAL.has(row.status)
    const conflict = event.terminal_conflict || terminal && settled && executionOutcome(event.status) !== executionOutcome(row.status)
    if (conflict) return { ...row, status: 'unknown', observation_gap: true, terminal_conflict: true, status_evidence: 'conflicting_native_terminal' }
    if (settled && !terminal) return row
    if (!terminal && row.observation_gap) return { ...row, event_received_at: event.received_at, last_tool: event.last_tool ?? row.last_tool }
    return { ...row, status: event.status, observation_gap: false, last_status: null,
      status_evidence: 'public_session_event', replay_coverage_gap: projection.coverage_gap === true,
      tool_count: event.tool_count ?? row.tool_count, api_call_count: event.api_call_count ?? row.api_call_count,
      token_total: event.token_total ?? row.token_total ?? null,
      duration_seconds: event.duration_seconds ?? row.duration_seconds, last_tool: event.last_tool ?? row.last_tool,
      event_received_at: event.received_at, reported_child_session_id: event.reported_child_session_id }
  })
}

// Approved ordinary read semantics, existing active canonical socket only.
// No SDK route inventory/resolver/ensure/retain/connect calls are used here.
export function createActiveExecutionObserver(transport, sdk = {}) {
  const store = createExecutionReplayStore(), pending = new Map(), subscriptions = []
  let cacheId = null
  try { cacheId = globalThis.crypto?.randomUUID?.() || null } catch {}
  const queryClient = sdk.queryClient
  const revisionAtom = typeof sdk.atom === 'function' ? sdk.atom(0) : { get: () => 0 }
  const stateKeys = ['focusedSessionOwner', 'focusedSessionId', 'connectionId', 'profile', 'gateway']
  const atoms = stateKeys.map(name => transport?.state?.[name])
  const supported = typeof transport?.getGateway === 'function' && typeof sdk.gatewayActivationEpoch === 'function' &&
    executionReplayId(cacheId) && typeof queryClient?.cancelQueries === 'function' && typeof queryClient?.removeQueries === 'function' &&
    typeof revisionAtom.set === 'function' && atoms.every(atom => typeof atom?.get === 'function' && typeof atom.listen === 'function')
  let disposed = false, cacheHealthy = true, generation = 0, previous = null, gateway = null, removeGatewayState = null
  const retireQueries = all => {
    if (!supported) return
    const predicate = query => {
      const key = query.queryKey
      return Array.isArray(key) && key.length === 5 && key[0] === PLUGIN_ID && key[2] === cacheId &&
        ['execution-active', 'profile-jobs-policy-active'].includes(key[1]) && (all || key[4] !== generation)
    }
    const failed = () => { cacheHealthy = false; generation++; revisionAtom.set(generation) }
    try {
      Promise.resolve(queryClient.cancelQueries({ predicate }, { silent: true })).catch(failed)
      queryClient.removeQueries({ predicate })
    } catch { failed() }
  }
  const readState = () => {
    if (!supported || disposed) return null
    try {
      const scope = executionScopeFromState(transport.state)
      const activeConnection = transport.state.connectionId.get(), activeProfile = transport.state.profile.get()
      const hostState = transport.state.gateway.get(), epoch = sdk.gatewayActivationEpoch(), instance = transport.getGateway()
      return { scope, activeConnection, activeProfile, hostState, epoch, instance,
        signature: JSON.stringify([executionScopeKey(scope), activeConnection, activeProfile, hostState, epoch, instance?.connectionState, instance?.sessionWire]) }
    } catch { return null }
  }
  const invalidate = (reset = false) => {
    generation++
    for (const item of pending.values()) item.abort.abort()
    pending.clear()
    if (reset) store.clear()
    retireQueries(disposed)
    if (typeof revisionAtom.set === 'function') revisionAtom.set(generation)
  }
  const observe = () => {
    const next = readState(), instance = next?.instance || null
    if (next?.signature === previous?.signature && instance === gateway) return
    const transportChanged = gateway !== instance || next?.epoch !== previous?.epoch || next?.hostState !== previous?.hostState ||
      instance?.connectionState !== previous?.connectionState
    previous = next ? { ...next, connectionState: instance?.connectionState } : null
    if (gateway !== instance) {
      if (typeof removeGatewayState === 'function') removeGatewayState()
      gateway = instance; removeGatewayState = null
      if (typeof gateway?.onState === 'function') {
        let registering = true
        removeGatewayState = gateway.onState(() => { if (!registering) invalidate(true) })
        registering = false
      }
    }
    invalidate(transportChanged)
  }
  if (supported) {
    for (const atom of atoms) subscriptions.push(atom.listen(observe))
    observe()
  }
  const capture = scope => {
    observe()
    const current = readState(), key = executionScopeKey(scope), instance = current?.instance
    if (!cacheHealthy || !current || !key || key !== executionScopeKey(current.scope) ||
        current.activeConnection !== scope.connectionId || current.activeProfile !== scope.profile || current.hostState !== 'open' ||
        !Number.isSafeInteger(current.epoch) || current.epoch < 0 || instance?.connectionState !== 'open' ||
        instance?.sessionWire !== 'canonical' || typeof instance.request !== 'function' || typeof instance.onState !== 'function') throw new Error('passive_origin_unavailable')
    // Public registry contract: LOCAL_CONNECTION_ID='local'; local registry
    // targetProfile===profile, independent of legacy remote aliases. Unknown
    // remote/SSH mappings are unsupported, never guessed or discovered here.
    if (scope.connectionId !== 'local' || !EXECUTION_PROFILE.test(scope.profile)) throw new Error('passive_backend_mapping_unavailable')
    return { key, scope: { ...scope }, instance, epoch: current.epoch, generation, backendProfile: scope.profile }
  }
  const current = token => {
    try {
      const next = capture(token.scope)
      return next.key === token.key && next.instance === token.instance && next.epoch === token.epoch && next.generation === token.generation
    } catch { return false }
  }
  const adapter = (token, abort) => {
    // Internal compatibility shape for existing pure normalizers, NOT a newly
    // invented native route or a capability sent to host.requestProfile.
    const descriptor = { connectionId: token.scope.connectionId, mode: 'local', profile: token.scope.profile, targetProfile: token.backendProfile }
    return {
      profileRoutes: async () => { if (!current(token)) throw new Error('execution_scope_changed'); return [{ ...descriptor }] },
      requestProfile: (route, method, params) => {
        if (!current(token) || abort.signal.aborted) throw new Error('execution_scope_changed')
        const allowed = new Set(['plugin.model-router.execution.list', 'subagent.list', 'plugin.model-router.profile_jobs.list', 'plugin.model-router.profile_jobs.describe', 'session.events.since'])
        if (!allowed.has(method) || nativeRouteKey(route) !== nativeRouteKey(descriptor) || !params || params.session_id !== token.scope.sessionId ||
            Object.keys(params).some(name => !['session_id', 'profile', 'replay_epoch', 'last_sequence'].includes(name)) ||
            ('profile' in params && params.profile !== token.backendProfile)) throw new Error('passive_read_refused')
        return token.instance.request(method, { ...params, profile: token.backendProfile }, 10000, abort.signal)
      }
    }
  }
  const replay = async (token, client, abort, parentAliases) => {
    const windows = [512, 64, 8, 1]
    let recovery = 0
    for (let attempt = 0; attempt < 6; attempt++) {
      if (!current(token) || abort.signal.aborted) throw new Error('execution_scope_changed')
      const cursor = store.cursor(token.scope)
      const params = { session_id: token.scope.sessionId, last_sequence: cursor.last_sequence }
      if (cursor.replay_epoch !== null) params.replay_epoch = cursor.replay_epoch
      let raw
      try { raw = await client.requestProfile({ connectionId: token.scope.connectionId, mode: 'local', profile: token.scope.profile, targetProfile: token.backendProfile }, 'session.events.since', params) }
      catch { if (!current(token)) throw new Error('execution_scope_changed'); const known = store.snapshot(token.scope); return { ...known, records: (known?.records || []).filter(value => NATIVE_TERMINAL.has(value.status)), coverage_gap: true, unavailable: true } }
      if (!current(token) || abort.signal.aborted) throw new Error('execution_scope_changed')
      const result = store.accept(token.scope, cursor, raw, Date.now() / 1000, parentAliases)
      raw = null
      if (!result.accepted || !result.needs_recovery) return store.snapshot(token.scope)
      if (result.reason === 'bootstrap_required' || result.reason === 'epoch_changed') continue
      const latest = store.cursor(token.scope)
      if (recovery >= windows.length) return store.snapshot(token.scope)
      store.recoverFrom(token.scope, latest, Math.max(0, latest.latest_seq - windows[recovery++]))
    }
    return store.snapshot(token.scope)
  }
  const run = (operation, scope) => {
    let token
    try { token = capture(scope) } catch { return Promise.reject(new Error('passive_origin_unavailable')) }
    const key = JSON.stringify([operation, token.key, token.generation]), existing = pending.get(key)
    if (existing) return existing.promise
    const item = { abort: new AbortController(), promise: null }
    pending.set(key, item)
    item.promise = (async () => {
      const client = adapter(token, item.abort), valid = () => current(token) && !item.abort.signal.aborted
      if (operation === 'policy') {
        const result = await readProfileJobs(client, token.scope, valid)
        if (!valid()) throw new Error('execution_scope_changed')
        return { ...result, observation_generation: token.generation, observation_lifetime: cacheId, observation_epoch: token.epoch }
      }
      const result = await readExecutionSnapshot(client, token.scope, valid)
      if (!valid()) throw new Error('execution_scope_changed')
      // Only this authorized origin roster supplies parent aliases. Child
      // locators, tap payloads and guessed ID suffixes are never parent proof.
      const parents = [...new Set(result.rows.filter(row => row.execution_mode === 'native')
        .flatMap(row => [row.conversation_id, row.parent_session_id]).filter(executionReplayId))]
      const projection = await replay(token, client, item.abort, parents)
      if (!valid()) throw new Error('execution_scope_changed')
      return { ...result, rows: overlayExecutionReplay(result.rows, projection, token.scope),
        observation_generation: token.generation, observation_lifetime: cacheId, observation_epoch: token.epoch,
        replay_available: !projection?.unavailable && Boolean(projection?.replay_epoch),
        replay_coverage_gap: projection?.coverage_gap === true || projection?.needs_recovery === true }
    })().finally(() => { if (pending.get(key) === item) pending.delete(key) })
    return item.promise
  }
  return {
    revisionAtom, cacheId,
    accepts(scope, data) {
      try {
        const token = capture(scope)
        return data?.scope_key === token.key && data?.observation_lifetime === cacheId &&
          data?.observation_generation === token.generation && data?.observation_epoch === token.epoch
      } catch { return false }
    },
    eligible(scope) { try { capture(scope); return true } catch { return false } },
    generation() { observe(); return generation },
    current(scope, value) { try { return capture(scope).generation === value } catch { return false } },
    read(scope) { return run('snapshot', scope) },
    policy(scope) { return run('policy', scope) },
    dispose() {
      if (disposed) return
      disposed = true; invalidate(true)
      if (typeof removeGatewayState === 'function') removeGatewayState()
      for (const off of subscriptions) if (typeof off === 'function') off()
    }
  }
}

export async function readExecutionSnapshot(transport, scope, isCurrent = () => true) {
  const key = executionScopeKey(scope)
  if (!key || typeof transport?.profileRoutes !== 'function' || typeof transport?.requestProfile !== 'function') throw new Error('execution_unavailable')
  const route = selectExecutionRoute(await transport.profileRoutes(), scope)
  if (!route || !isCurrent()) throw new Error('execution_scope_changed')
  const params = { session_id: scope.sessionId }
  const replies = await Promise.allSettled([
    transport.requestProfile(route, 'plugin.model-router.execution.list', params),
    transport.requestProfile(route, 'subagent.list', params),
    transport.requestProfile(route, 'plugin.model-router.profile_jobs.list', params)
  ])
  if (!isCurrent()) throw new Error('execution_scope_changed')
  const snapshot = replies[0].status === 'fulfilled' ? replies[0].value : null
  const live = replies[1].status === 'fulfilled' ? replies[1].value : null
  const full = replies[2].status === 'fulfilled' ? normalizeProfileJobs(replies[2].value, route.targetProfile, scope.sessionId) : null
  const metadataAvailable = Boolean(snapshot && snapshot.schema === 1 && snapshot.origin_profile === route.targetProfile && Array.isArray(snapshot.rows))
  const nativeAvailable = Boolean(live && Array.isArray(live.subagents))
  const nativeRows = mergeExecutionRows(metadataAvailable ? snapshot : { schema: 1, origin_profile: route.targetProfile, rows: [] }, live, route.targetProfile)
  const fullJobs = full || []
  const combined = [...fullJobs.map(profileJobExecutionRow), ...nativeRows]
  // The server authorizes the requested session and resolves its own aliases.
  return { scope_key: key, rows: combined.slice(0, 128), full_jobs: fullJobs, full_available: full !== null,
    available: Boolean(metadataAvailable || nativeAvailable || full !== null), metadata_available: metadataAvailable,
    native_available: nativeAvailable, limited: combined.length > 128, reason: metadataAvailable ? snapshot.reason_code || null : 'execution_metadata_unavailable' }
}
export function executionScopeFromState(state) {
  // A provided-but-unresolved focused owner is not permission to use the
  // ambient socket's profile. The same profile name can exist on two hosts.
  if (state?.focusedSessionOwner && state?.focusedSessionId) {
    const owner = state.focusedSessionOwner.get()
    return { connectionId: owner?.connectionId, profile: owner?.profile, sessionId: state.focusedSessionId.get() }
  }
  return { connectionId: state?.connectionId?.get?.(), profile: state?.profile?.get?.(), sessionId: state?.activeSessionId?.get?.() }
}
function currentExecutionScope() { return executionScopeFromState(host.state) }
function useExecutionSnapshot(observer) {
  const owner = useValue(host.state?.focusedSessionOwner || EXECUTION_EMPTY_ATOM)
  const focusedId = useValue(host.state?.focusedSessionId || EXECUTION_EMPTY_ATOM)
  const connectionId = useValue(host.state?.connectionId || EXECUTION_EMPTY_ATOM)
  const profile = useValue(host.state?.profile || EXECUTION_EMPTY_ATOM)
  const sessionId = useValue(host.state?.activeSessionId || EXECUTION_EMPTY_ATOM)
  const gateway = useValue(host.state?.gateway || EXECUTION_EMPTY_ATOM)
  const scope = host.state?.focusedSessionOwner && host.state?.focusedSessionId
    ? { connectionId: owner?.connectionId, profile: owner?.profile, sessionId: focusedId } : { connectionId, profile, sessionId }
  const key = executionScopeKey(scope)
  const observationGeneration = useValue(observer?.revisionAtom || EXECUTION_EMPTY_ATOM)
  const eligible = Boolean(key && observer?.eligible(scope))
  const query = useQuery({ queryKey: ['model-router', 'execution-active', observer?.cacheId, key, observationGeneration],
    queryFn: () => observer.read(scope),
    enabled: eligible,
    retry: false, staleTime: 2000, gcTime: 0, refetchInterval: 5000 })
  useEffect(() => {
    if (!eligible || typeof host.onEvent !== 'function') return
    // Events are invalidation hints only: the tap does not attest their owner.
    // Re-read the exact authenticated profile/session, never adopt event rows.
    let lastEventRead = -Infinity
    const invalidate = () => {
      const now = Date.now()
      if (!observer.current(scope, observationGeneration) || now - lastEventRead < 2000) return
      lastEventRead = now
      Promise.resolve(query.refetch()).catch(() => {})
    }
    const disposers = ['plugin.model-router.execution.changed', 'async_delegation', 'subagent.spawn_requested',
      'subagent.start', 'subagent.progress', 'subagent.tool', 'subagent.complete'].map(type => host.onEvent(type, invalidate))
    return () => { for (const dispose of disposers) if (typeof dispose === 'function') dispose() }
  }, [key, gateway, eligible, observationGeneration, query.refetch])
  const data = !eligible && key ? { scope_key: key, available: false, reason: 'passive_origin_unavailable' } :
    observer?.accepts(scope, query.data) ? query.data : null
  return { scope, key, query, data }
}
const executionStyles = {
  panel: { minWidth: 0, minHeight: 0, width: '100%', height: '100%', flex: '1 1 auto', overflowY: 'auto', boxSizing: 'border-box', padding: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', color: 'var(--ui-text-primary)' },
  list: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 22rem), 1fr))', gap: '0.6rem', minWidth: 0 },
  row: { minWidth: 0, border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.6rem', padding: '0.7rem', display: 'flex', flexDirection: 'column', gap: '0.45rem', overflowWrap: 'anywhere' },
  badges: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.4rem', minWidth: 0 },
  badge: { display: 'inline-flex', maxWidth: '100%', minWidth: 0, whiteSpace: 'normal', overflowWrap: 'anywhere', padding: '0.2rem 0.45rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.4rem', fontSize: '0.76rem', lineHeight: 1.4 },
  details: { minWidth: 0, color: 'var(--ui-text-secondary)', fontSize: '0.76rem', lineHeight: 1.55, overflowWrap: 'anywhere' },
  summary: { cursor: 'pointer', color: 'var(--ui-text-secondary)', fontSize: '0.78rem', lineHeight: 1.5 },
  compact: { minWidth: 0, width: '100%', maxHeight: 'min(45vh, 24rem)', overflowY: 'auto', boxSizing: 'border-box', padding: '0.45rem 0', color: 'var(--ui-text-secondary)' }
}
const EXECUTION_STATUS = { requested: '요청', dispatched: '위임 접수', preparing: '실행 준비', creating: '세션 생성 요청', submitting: '작업 제출 요청', queued: '대기', running: '실행 중', approval_wait: '승인 대기', clarify_wait: '답변 대기', stop_requested: '중지 요청', completed: '완료', succeeded: '완료', error: '오류', failed: '실패', interrupted: '중단', cancelled: '취소', timeout: '시간 제한', unknown: '상태 미확인' }
function executionDuration(seconds) {
  const value = executionSeconds(seconds)
  if (value === null || value > Number.MAX_SAFE_INTEGER) return null
  const whole = Math.floor(value), minutes = Math.floor(whole / 60)
  return minutes ? `${minutes}분 ${whole % 60}초` : `${whole}초`
}
function executionActivityLabels(row) {
  const labels = [], tools = executionCount(row.tool_count), calls = executionCount(row.api_call_count)
  if (tools !== null) labels.push(`도구 ${tools}회`)
  else if (row.execution_mode === 'native') labels.push('도구 횟수 미관찰')
  if (calls !== null) labels.push(`모델 호출 ${calls}회`)
  else if (row.execution_mode === 'native') labels.push('모델 호출 횟수 미관찰')
  const tokens = executionTokens(row.tokens), total = executionTokenTotal(row), observed = executionObservedTokens(row)
  const reported = executionCount(row.token_total)
  const parts = tokens && [['입력', tokens.input], ['캐시 읽기', tokens.cache_read], ['캐시 쓰기', tokens.cache_write], ['출력', tokens.output]]
    .filter(([name, count]) => count || name === '입력' || name === '출력').map(([name, count]) => `${name} ${executionTokenText(count)}`).join(' · ')
  if (tokens && (reported === null || reported === observed)) labels.push(`토큰 ${executionTokenText(total)}: ${parts}`)
  else if (tokens) labels.push(`토큰 ${executionTokenText(total)} (완료 보고 기준) · 모델 호출 관찰분 ${executionTokenText(observed)}: ${parts}`)
  else if (total !== null) labels.push(`토큰 ${executionTokenText(total)} (완료 보고 기준)`)
  const tool = executionTool(row.last_tool)
  if (tool) labels.push(`최근 도구: ${tool}`)
  const duration = executionDuration(row.duration_seconds)
  const started = executionSeconds(row.started_at), now = Date.now() / 1000
  if (NATIVE_TERMINAL.has(row.status) && duration !== null) labels.push(`실행 시간: ${duration}`)
  else if (row.status === 'running' && started !== null && started <= now) labels.push(`경과: ${executionDuration(now - started)}`)
  const activity = executionSeconds(row.activity_at)
  if (activity !== null) {
    const date = new Date(activity * 1000)
    if (Number.isFinite(date.getTime())) labels.push(`최근 활동: ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}`)
  }
  const received = executionSeconds(row.event_received_at)
  if (received !== null) {
    const date = new Date(received * 1000)
    if (Number.isFinite(date.getTime())) labels.push(`신호 수신: ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}`)
  }
  return labels
}
export function ExecutionRow({ row, bare = false }) {
  const observed = row.observed?.evidence === 'runtime_reported' && row.observed?.kind !== 'unknown'
  // A route label names the tier only; the requested slot stays the more specific name.
  const identity = observed ? (row.observed.kind === 'model' && row.requested?.kind === 'model' ? { ...row.observed, slot: row.requested.slot } : row.observed) : row.requested
  // The model the child's own API requests reported (runtime report, also when a spare model took over).
  const runtimeModel = row.model ? `${row.model}${row.provider ? ` · ${row.provider}` : ''}` : null
  const activity = executionActivityLabels(row)
  return jsxs('article', { style: bare ? { ...executionStyles.row, border: 0, padding: 0 } : executionStyles.row, 'data-execution-row': row.id, children: [
    jsxs('div', { style: executionStyles.badges, children: [
      jsx('span', { style: executionStyles.badge, children: executionLabel(identity) }),
      jsx('span', { style: executionStyles.badge, children: row.execution_mode === 'gateway' ? '전체 프로필' : '네이티브' }),
      jsx('span', { style: { ...styles.hint, color: row.status === 'running' ? 'var(--ui-accent)' : undefined }, role: 'status', 'data-execution-status': row.status, children: EXECUTION_STATUS[row.status] || '상태 미확인' })
    ] }),
    activity.length ? jsx('div', { style: { ...executionStyles.badges, fontSize: '0.78rem', color: 'var(--ui-text-secondary)' }, 'data-execution-activity': true,
      children: activity.map((label, index) => jsx('span', { children: label }, index)) }) : null,
    row.terminal_conflict ? jsx('p', { style: styles.hint, children: '서로 다른 종료 정보가 확인되어 상태를 확정하지 않습니다.' }) :
      row.observation_gap ? jsx('p', { style: styles.hint, children: '현재 실행 목록에서 확인되지 않습니다. 완료로 판단하지 않으며, 최근 관찰 상태만 유지합니다.' }) : null,
    jsx('p', { style: styles.actual, children: observed ? '실행 정보: 런타임 보고 · 개별 API 응답의 모델 검증과는 다릅니다.' : '역할은 요청 기준입니다. 실행 상태·활동 정보와 실제 역할 확인은 별개입니다.' }),
    runtimeModel ? jsx('p', { style: styles.actual, children: `실행 모델: ${runtimeModel}` }) : null,
    jsxs('details', { style: executionStyles.details, children: [jsx('summary', { style: executionStyles.summary, children: '실행 식별 정보' }),
      jsx('div', { children: `요청: ${executionLabel(row.requested)}` }),
      jsx('div', { children: `실행: ${observed ? executionLabel(identity) + (runtimeModel ? ` · ${runtimeModel}` : '') : executionModelText(row) || '아직 API 호출 보고 없음'}` }),
      row.last_status ? jsx('div', { children: `최근 관찰 상태: ${EXECUTION_STATUS[row.last_status] || '상태 미확인'}` }) : null,
      row.backend ? jsx('div', { children: `방식: ${row.backend}` }) : null,
      row.subagent_id ? jsx('div', { children: `하위 작업: ${row.subagent_id}` }) : null,
      row.delegation_id ? jsx('div', { children: `위임: ${row.delegation_id}` }) : null,
      row.child_session_id ? jsx('div', { children: `하위 작업 세션: ${row.child_session_id}` }) : null,
      row.job?.target_session_id ? jsx('div', { children: `작업 세션: ${row.job.target_session_id}` }) : null,
      row.job?.admission_id ? jsx('div', { children: `접수: ${row.job.admission_id}` }) : null
    ] })
  ] })
}
const EXECUTION_ACTIVE = new Set(['requested', 'dispatched', 'preparing', 'creating', 'submitting', 'queued', 'running', 'approval_wait', 'clarify_wait', 'stop_requested'])
const EXECUTION_FAILED = new Set(['error', 'failed', 'timeout'])
const EXECUTION_DONE = new Set(['completed', 'succeeded'])
const EXECUTION_STOPPED = new Set(['interrupted', 'cancelled'])
function executionStartedAt(row) { return executionSeconds(row.started_at) ?? executionSeconds(row.updated_at) ?? 0 }
// Running work first (newest first), then finished work by most recent change.
export function sortExecutionRows(rows) {
  return (Array.isArray(rows) ? rows : []).map((row, index) => ({ row, index })).sort((a, b) => {
    const activeA = EXECUTION_ACTIVE.has(a.row.status), activeB = EXECUTION_ACTIVE.has(b.row.status)
    if (activeA !== activeB) return activeA ? -1 : 1
    const timeA = activeA ? executionStartedAt(a.row) : executionSeconds(a.row.updated_at) ?? 0
    const timeB = activeB ? executionStartedAt(b.row) : executionSeconds(b.row.updated_at) ?? 0
    return timeB - timeA || b.index - a.index
  }).map(item => item.row)
}
function executionShortLabel(row) {
  const observed = row.observed?.evidence === 'runtime_reported' && row.observed?.kind !== 'unknown'
  const identity = executionIdentity(observed ? (row.observed.kind === 'model' && row.requested?.kind === 'model' ? { ...row.observed, slot: row.requested.slot } : row.observed) : row.requested)
  if (identity.kind === 'profile') return `프로필 · ${identity.profile}`
  if (identity.kind === 'model') return TASK_SLOTS.find(item => item.id === identity.slot)?.label || (identity.role === 'heavy' ? 'Heavy' : 'Light')
  return row.execution_mode === 'gateway' ? '전체 프로필' : '종류 미확인'
}
function executionTime(row) {
  if (EXECUTION_ACTIVE.has(row.status)) {
    const started = executionSeconds(row.started_at), now = Date.now() / 1000
    return started !== null && started <= now ? executionDuration(now - started) : null
  }
  return executionDuration(row.duration_seconds)
}
function executionStatusColor(status) {
  return status === 'running' ? 'var(--ui-accent)' : EXECUTION_FAILED.has(status) ? 'var(--ui-red, var(--ui-text-primary))' : 'var(--ui-text-tertiary)'
}
const stripStyles = {
  root: { minWidth: 0, width: '100%', boxSizing: 'border-box', padding: '0.3rem 0', color: 'var(--ui-text-secondary)', fontSize: '0.78rem', lineHeight: 1.45 },
  summary: { cursor: 'pointer', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.3rem 0.6rem', minWidth: 0, listStyle: 'revert' },
  counts: { color: 'var(--ui-text-primary)', fontWeight: 500, whiteSpace: 'nowrap' },
  chip: { display: 'inline-flex', alignItems: 'center', gap: '0.35rem', minWidth: 0, maxWidth: '100%', padding: '0.05rem 0.45rem', border: '1px solid var(--ui-stroke-secondary)', borderRadius: '999px', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' },
  list: { display: 'flex', flexDirection: 'column', marginTop: '0.35rem', maxHeight: 'min(40vh, 20rem)', overflowY: 'auto', borderTop: '1px solid var(--ui-stroke-tertiary)' },
  item: { minWidth: 0, borderBottom: '1px solid var(--ui-stroke-tertiary)' },
  line: { cursor: 'pointer', display: 'grid', gridTemplateColumns: '4.6rem minmax(0, 1fr) auto', alignItems: 'baseline', columnGap: '0.6rem', padding: '0.3rem 0.15rem', listStyle: 'none' },
  name: { minWidth: 0, display: 'flex', flexWrap: 'wrap', gap: '0 0.5rem', alignItems: 'baseline' },
  model: { color: 'var(--ui-text-tertiary)', overflowWrap: 'anywhere' },
  meta: { color: 'var(--ui-text-tertiary)', whiteSpace: 'nowrap', textAlign: 'end' },
  body: { padding: '0.1rem 0.15rem 0.5rem 5.2rem', color: 'var(--ui-text-tertiary)', overflowWrap: 'anywhere', display: 'flex', flexDirection: 'column', gap: '0.1rem' }
}
function executionChip(row) {
  const time = executionTime(row)
  return jsxs('span', { style: stripStyles.chip, 'data-execution-chip': row.id, children: [
    jsx('span', { 'aria-hidden': true, style: { color: executionStatusColor(row.status) }, children: '●' }),
    [executionShortLabel(row), row.model ? `${row.model}${executionSpare(row) ? ' (모델 변경)' : ''}` : null, EXECUTION_ACTIVE.has(row.status) ? time : `${EXECUTION_STATUS[row.status] || '상태 미확인'}${time ? ` ${time}` : ''}`].filter(Boolean).join(' · ')
  ] }, row.id)
}
export function ExecutionLine({ row, controls = null }) {
  const time = executionTime(row), tools = executionCount(row.tool_count), tokenTotal = executionTokenTotal(row)
  // Time, tool count and token total are on the line itself; the body keeps the token breakdown.
  const activity = executionActivityLabels(row).filter(label => !/횟수 미관찰$|^도구 \d+회$|^경과:|^실행 시간:/.test(label))
  const ids = [row.subagent_id && `하위 작업 ${row.subagent_id}`, row.delegation_id && `위임 ${row.delegation_id}`,
    row.child_session_id && `세션 ${row.child_session_id}`, row.job?.target_session_id && `작업 세션 ${row.job.target_session_id}`].filter(Boolean)
  return jsxs('details', { style: stripStyles.item, 'data-execution-row': row.id, children: [
    jsxs('summary', { style: stripStyles.line, children: [
      jsx('span', { role: 'status', 'data-execution-status': row.status, style: { color: executionStatusColor(row.status), whiteSpace: 'nowrap' }, children: EXECUTION_STATUS[row.status] || '상태 미확인' }),
      jsxs('span', { style: stripStyles.name, children: [
        jsx('span', { style: { color: 'var(--ui-text-primary)' }, children: executionShortLabel(row) }),
        jsx('span', { style: stripStyles.model, children: row.model ? `${row.model}${executionSpare(row) ? ' · 모델 변경 관찰' : ''}` : (EXECUTION_ACTIVE.has(row.status) ? '모델 보고 전' : '모델 보고 없음') })
      ] }),
      jsx('span', { style: stripStyles.meta, children: [time, tools !== null ? `도구 ${tools}회` : null, tokenTotal !== null ? `토큰 ${executionTokenText(tokenTotal)}` : null].filter(Boolean).join(' · ') })
    ] }),
    jsxs('div', { style: stripStyles.body, children: [
      row.observation_gap ? jsx('div', { children: '현재 실행 목록에서 확인되지 않습니다. 완료로 판단하지 않습니다.' }) : null,
      row.terminal_conflict ? jsx('div', { children: '서로 다른 종료 정보가 있어 상태를 확정하지 않습니다.' }) : null,
      jsx('div', { children: `요청: ${executionLabel(row.requested)}${row.execution_mode === 'gateway' ? ' · 전체 프로필 작업' : ''}` }),
      jsx('div', { children: `실행: ${executionModelText(row) || '아직 API 호출 보고 없음'}` }),
      activity.length ? jsx('div', { children: activity.join(' · ') }) : null,
      ids.length ? jsx('div', { children: ids.join(' · ') }) : null,
      controls
    ] })
  ] })
}
// Mounts its content only while open, so a closed section issues no reads.
function LazySection({ label, render }) {
  const [open, setOpen] = useState(false)
  return jsxs('details', { style: { padding: '0.35rem 0.15rem' }, onToggle: event => setOpen(Boolean(event.currentTarget?.open)), children: [
    jsx('summary', { style: { cursor: 'pointer' }, children: label }), open ? render() : null] })
}
export function ExecutionStrip({ rows, unavailable, jobControls = null, jobsPanel = null, defaultOpen = false }) {
  const sorted = sortExecutionRows(rows)
  const active = sorted.filter(row => EXECUTION_ACTIVE.has(row.status))
  const count = set => sorted.filter(row => set.has(row.status)).length
  const completed = count(EXECUTION_DONE), failed = count(EXECUTION_FAILED), stopped = count(EXECUTION_STOPPED)
  // Anything else (observation gap, conflicting terminal evidence, unknown) is never counted as done.
  const unknown = sorted.length - active.length - completed - failed - stopped
  const [open, setOpen] = useState(defaultOpen)
  if (unavailable) return jsx('p', { style: { ...stripStyles.root, color: 'var(--ui-text-tertiary)' }, role: 'status', 'data-model-router-execution': 'compact', children: '서브에이전트 실행 정보를 읽을 수 없습니다.' })
  if (!sorted.length) return null
  const counts = [active.length ? `실행 중 ${active.length}` : null, completed ? `완료 ${completed}` : null, failed ? `오류 ${failed}` : null,
    stopped ? `중단 ${stopped}` : null, unknown ? `미확인 ${unknown}` : null].filter(Boolean)
  const chips = active.length ? active.slice(0, 2) : sorted.slice(0, 1)
  return jsxs('details', { style: stripStyles.root, 'data-model-router-execution': 'compact', open,
    onToggle: event => setOpen(Boolean(event.currentTarget?.open)), children: [
    jsxs('summary', { style: stripStyles.summary, children: [
      jsx('span', { style: stripStyles.counts, children: `서브에이전트 · ${counts.join(' · ')}` }),
      ...chips.map(executionChip),
      active.length > 2 ? jsx('span', { children: `외 ${active.length - 2}개` }) : null
    ] }),
    jsxs('div', { style: stripStyles.list, children: [
      ...sorted.map(row => jsx(ExecutionLine, { row, controls: row.execution_mode === 'gateway' && row.job && jobControls ? jobControls(row) : null }, row.id)),
      // A hidden guide must not keep its policy query alive: mount it only while the strip is open.
      open && jobsPanel ? jsx(LazySection, { label: '전체 프로필 작업 · 허용 범위와 운영자 안내', render: jobsPanel }, 'profile-jobs') : null
    ] })
  ] })
}
// Host-markup compatibility layer, not an SDK API: composer.top renders with no per-composer
// owner, and the strip describes the FOCUSED chat. With several chats split in one window, show
// it only where that chat is shown. Chat surfaces carry data-composer-target: 'main', or 'tile:'
// plus the stored session id; a popped-out composer host carries data-floating-composer-target
// or data-composer-owner (the surface id). Unknown markup fails open (shown).
function chatSurfaces(root) { return Array.from(root?.querySelectorAll?.('[data-chat-surface]') || []) }
// The chat surface an element belongs to, also for a popped-out composer portalled to the document body.
function composerSurfaceOf(element, root) {
  const surface = element?.closest?.('[data-chat-surface]')
  if (surface?.getAttribute?.('data-composer-target')) return surface
  const owner = element?.closest?.('[data-composer-owner]')?.getAttribute?.('data-composer-owner')
  return owner ? chatSurfaces(root).find(item => item.getAttribute?.('data-composer-surface-id') === owner) || null : null
}
function composerTargetOf(element, root) {
  const surface = composerSurfaceOf(element, root)
  const target = surface?.getAttribute?.('data-composer-target')
  if (target) return { target, surface }
  const floating = element?.closest?.('[data-floating-composer-target]')?.getAttribute?.('data-floating-composer-target')
  return floating ? { target: floating, surface: null } : null
}
export function composerShowsFocused(element, focusedStoredId, root = globalThis.document, focusedRuntimeId = null, primaryRuntimeId = null) {
  const found = composerTargetOf(element, root)
  if (!found) return true
  const { target } = found
  if (target.startsWith('tile:')) return Boolean(focusedStoredId) && target === `tile:${focusedStoredId}`
  if (target !== 'main') return true
  // The primary shows only with positive identity: the host's focused runtime id IS the primary's
  // runtime id (host.state.activeSessionId). A missing tile node is not proof (a parked tile can
  // stay focused while unmounted).
  if (!focusedRuntimeId || focusedRuntimeId !== primaryRuntimeId) return false
  if (!focusedStoredId) return true
  // Attribute comparison, not a selector: ids never need escaping.
  const inTile = chatSurfaces(root).some(item => item.getAttribute?.('data-composer-target') === `tile:${focusedStoredId}`)
  if (!inTile) return true
  // The focused chat is open in a tile. The SDK does not say which chat the primary shows, and
  // pointer, focus and keyboard-shortcut paths all move focus differently, so the primary hides:
  // when the same chat is also open in the primary, its strip shows in the tile only. A missing
  // strip is better than another chat's strip.
  return false
}
// Every mounted gate. A chat surface mounting or unmounting (its composer mounts a gate) makes
// the others re-check, with no id change needed: a tile can mount after an async runtime bind.
const composerGates = new Set()
function recheckComposerGates() { for (const recheck of [...composerGates]) recheck() }
export function ComposerFocusGate({ children }) {
  const focusedStored = useValue(host.state?.focusedStoredSessionId || EXECUTION_EMPTY_ATOM)
  const focusedRuntime = useValue(host.state?.focusedSessionId || EXECUTION_EMPTY_ATOM)
  const primaryRuntime = useValue(host.state?.activeSessionId || EXECUTION_EMPTY_ATOM)
  const anchor = useRef(null)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    // Tiles open, close and move by gestures that need not change focus: re-check after pointer,
    // focus and key events too (attribute reads only; React skips unchanged answers).
    let live = true
    const timers = new Set()
    const check = () => { if (live) setVisible(composerShowsFocused(anchor.current, focusedStored, globalThis.document, focusedRuntime, primaryRuntime)) }
    check()
    const doc = globalThis.document
    const later = () => {
      const timer = globalThis.setTimeout(() => { timers.delete(timer); check() }, 0); timers.add(timer)
    }
    composerGates.add(later)
    recheckComposerGates()
    for (const type of ['pointerup', 'focusin', 'keyup']) doc?.addEventListener?.(type, later, true)
    return () => {
      live = false
      composerGates.delete(later)
      for (const timer of timers) globalThis.clearTimeout(timer)
      for (const type of ['pointerup', 'focusin', 'keyup']) doc?.removeEventListener?.(type, later, true)
      recheckComposerGates()
    }
  }, [focusedStored, focusedRuntime, primaryRuntime])
  return jsx('div', { ref: anchor, style: { display: 'contents' }, 'data-model-router-focus-gate': visible ? 'shown' : 'hidden', children: visible ? children() : null })
}
export function ExecutionPanel({ compact = false, ctx, observer } = {}) {
  const { scope, key, query, data } = useExecutionSnapshot(observer)
  const fence = useExecutionFence()
  const [filter, setFilter] = useState('all')
  const rows = (data?.rows || []).filter(row => filter === 'all' || (row.observed?.evidence === 'runtime_reported' ? row.observed : row.requested)?.kind === filter)
  const content = !key ? jsx('p', { style: styles.hint, children: '대화를 선택하면 해당 연결·프로필·대화의 실행 현황을 표시합니다.' }) :
    data?.reason === 'passive_origin_unavailable' ? jsx('p', { style: styles.hint, role: 'status', children: '현재 열린 연결과 포커스 대화가 일치하고 백엔드 프로필을 확인한 경우에만 조회합니다. 연결이 닫혔거나 원격 매핑이 미확인이면 다른 실행 환경을 시작하지 않고 조회를 보류합니다.' }) :
    query.isPending && !data ? jsx('p', { style: styles.hint, children: '실행 정보를 확인하고 있습니다…' }) :
    query.isError || data?.available === false ? jsx('p', { style: styles.hint, role: 'status', children: '이 대화의 실행 정보를 읽을 수 없습니다. 연결과 해당 프로필의 플러그인 준비 상태를 확인하세요. 다른 프로필로 전환해 조회하지 않습니다.' }) :
      rows.length ? jsx('div', { style: executionStyles.list, children: rows.map(row => !compact && row.execution_mode === 'gateway'
        ? jsx(ProfileJobControls, { job: row.job, scope, storage: ctx?.storage, fence, refresh: () => query.refetch() }, `${key}:${row.id}`)
        : jsx(ExecutionRow, { row }, row.id)) }) : jsx('p', { style: styles.hint, children: '확인된 실행 기록이 없습니다. 플러그인 로드 이전 작업은 종류가 확인되지 않을 수 있습니다.' })
  // The composer strip stays out of the way: nothing while there is nothing to show.
  if (compact) return !key || data?.reason === 'passive_origin_unavailable' || (query.isPending && !data) ? null :
    jsx(ExecutionStrip, { rows: data?.rows || [], unavailable: query.isError || data?.available === false,
      // Gateway profile-job controls lived in the removed pane; they now open from the job's own line.
      jobControls: row => jsx(ProfileJobControls, { job: row.job, scope, storage: ctx?.storage, fence, refresh: () => query.refetch() }, `${key}:${row.id}`),
      jobsPanel: () => jsx(ProfileJobsPanel, { ctx, scope, observer, executionData: data, refreshExecutions: () => query.refetch() }, key) })
  return jsxs('section', { style: executionStyles.panel, 'data-model-router-execution': 'panel', 'aria-label': '모델 라우터 실행 현황', children: [
    jsxs('header', { style: styles.sectionHeading, children: [jsx('h2', { style: styles.heading, children: '실행 현황' }),
      jsx(Button, { size: 'sm', variant: 'ghost', disabled: !key || query.isFetching, onClick: () => query.refetch(), children: '새로고침' })] }),
    key ? jsx('p', { style: styles.hint, children: `포커스한 대화 · ${scope.profile} · ${scope.connectionId}` }) : null,
    jsxs('div', { style: executionStyles.badges, children: ['all', 'model', 'profile'].map(value => jsx(Button, { size: 'sm', variant: filter === value ? 'secondary' : 'ghost', onClick: () => setFilter(value), 'aria-pressed': filter === value,
      children: { all: '전체', model: '모델', profile: '프로필' }[value] }, value)) }),
    content,
    data?.limited ? jsx('p', { style: styles.hint, children: '최근 관찰 기록은 최대 128개까지 표시합니다.' }) : null,
    data?.replay_coverage_gap ? jsx('p', { style: styles.hint, role: 'status', children: '일부 이벤트 기록을 복구하지 못했습니다. 확인된 종료 신호만 유지하며, 누락된 결과를 완료로 추정하지 않습니다.' }) : null,
    jsx('p', { style: styles.hint, children: '기존 서브에이전트 카드와 중지·지시 기능은 그대로 유지합니다. 이 패널은 실행 종류와 확인된 식별 정보를 보완합니다.' }),
    key ? jsx(ProfileJobsPanel, { ctx, scope, observer, executionData: data, refreshExecutions: () => query.refetch() }, key) : null
  ] })
}

const PROFILE_JOB_STATES = new Set(['preparing', 'creating', 'submitting', 'queued', 'running', 'approval_wait', 'clarify_wait', 'stop_requested', 'completed', 'failed', 'cancelled', 'unknown'])
const PROFILE_JOB_TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const PROFILE_JOB_FENCES = 'model-router.profile-job-fences.v1'
export function createExecutionFence(read = currentExecutionScope, readGateway = () => host.state?.gateway?.get?.()) {
  let generation = 0, closed = false, last = JSON.stringify([executionScopeKey(read()), readGateway()])
  const observe = () => { const next = JSON.stringify([executionScopeKey(read()), readGateway()]); if (next !== last) { generation++; last = next } }
  return { observe, capture() { observe(); return { key: executionScopeKey(read()), generation } },
    current(token) { observe(); return !closed && Boolean(token?.key) && token.key === executionScopeKey(read()) && token.generation === generation },
    activate() { closed = false; generation++; observe() }, dispose() { closed = true; generation++ } }
}
function useExecutionFence() {
  const ref = useRef(null)
  if (!ref.current) ref.current = createExecutionFence()
  useEffect(() => {
    const fence = ref.current
    fence.activate()
    const atoms = ['focusedSessionOwner', 'focusedSessionId', 'connectionId', 'profile', 'activeSessionId', 'gateway'].map(key => host.state?.[key])
    const disposers = atoms.filter(atom => typeof atom?.listen === 'function').map(atom => atom.listen(fence.observe))
    fence.observe()
    return () => { for (const dispose of disposers) dispose(); fence.dispose() }
  }, [])
  return ref.current
}
function fullPolicyScope(scope) { return executionScopeKey(scope) ? JSON.stringify([scope.connectionId, scope.profile]) : null }
function fenceStore(storage) {
  if (!storage || typeof storage.get !== 'function' || typeof storage.set !== 'function') return null
  try {
    const value = storage.get(PROFILE_JOB_FENCES, { schema: 1, entries: {} })
    return value && value.schema === 1 && value.entries && !Array.isArray(value.entries) && typeof value.entries === 'object' && Object.keys(value.entries).length <= 64 ? deepClone(value) : null
  } catch { return null }
}
export function profileJobFence(storage, key, value) {
  const store = fenceStore(storage)
  let parts
  try { parts = JSON.parse(key) } catch { return { blocked: true, unavailable: true } }
  if (!store || !Array.isArray(parts) || ![2, 3].includes(parts.length) || parts.some(item => !executionId(item)) || JSON.stringify(parts) !== key) return { blocked: true, unavailable: true }
  if (value === undefined) return store.entries[key] || null
  if (value === null) delete store.entries[key]
  else {
    if (Object.keys(store.entries).length >= 64 && !(key in store.entries)) throw new Error('profile_job_fence_capacity')
    store.entries[key] = value
  }
  storage.set(PROFILE_JOB_FENCES, store)
  const readback = fenceStore(storage)
  if (!readback || JSON.stringify(readback.entries[key] || null) !== JSON.stringify(value || null)) throw new Error('profile_job_fence_unavailable')
  return value
}
export function normalizeProfileJobs(reply, targetProfile, parentId) {
  if (!reply || reply.schema !== 1 || reply.origin_profile !== targetProfile || reply.parent_session_id !== parentId || !Array.isArray(reply.jobs)) return null
  const seen = new Set(), jobs = []
  for (const value of reply.jobs.slice(0, 64)) {
    if (!value || !executionId(value.id) || seen.has(value.id) || value.origin_profile !== targetProfile ||
      !executionId(value.parent_session_id) || !EXECUTION_PROFILE.test(value.target_profile || '') || value.execution_mode !== 'gateway' || !PROFILE_JOB_STATES.has(value.status)) continue
    seen.add(value.id)
    const pending = value.pending_request
    const prompt = pending && ['approval', 'clarify'].includes(pending.kind) && executionId(pending.prompt_id) && Number.isSafeInteger(pending.execution_generation) && pending.execution_generation >= 0
      ? { kind: pending.kind, prompt_id: pending.prompt_id, execution_generation: pending.execution_generation,
        text: typeof pending.text === 'string' && pending.text.length <= 8192 ? pending.text : '',
        choices: Array.isArray(pending.choices) ? pending.choices.filter(choice => ['once', 'deny'].includes(choice)) : [] } : null
    jobs.push({ id: value.id, origin_profile: targetProfile, parent_session_id: value.parent_session_id, target_profile: value.target_profile,
      execution_mode: 'gateway', status: value.status, target_session_id: executionId(value.target_session_id) ? value.target_session_id : null,
      admission_id: executionId(value.admission_id) ? value.admission_id : null,
      target_profile_id: executionId(value.target_profile_id) ? value.target_profile_id : null,
      target_instance_id: executionId(value.target_instance_id) ? value.target_instance_id : null,
      target_authority_epoch: Number.isSafeInteger(value.target_authority_epoch) && value.target_authority_epoch >= 0 ? value.target_authority_epoch : null,
      target_cwd: typeof value.target_cwd === 'string' && value.target_cwd.length > 0 && value.target_cwd.length <= 2048 && !/[\x00-\x1f\x7f]/.test(value.target_cwd) ? value.target_cwd : null,
      execution_generation: Number.isSafeInteger(value.execution_generation) && value.execution_generation >= 0 ? value.execution_generation : null,
      completion_delivery: 'explicit_result', result_available: value.result_available === true,
      can_steer: value.can_steer === true, can_approve: false, can_deny: false, can_clarify: false,
      reason_code: /^[a-z0-9_]{1,80}$/.test(value.reason_code || '') ? value.reason_code : null, pending_request: prompt,
      observed: executionIdentity(value.observed), model: executionSafeText(value.model), provider: executionSafeText(value.provider),
      created_at: executionSeconds(value.created_at), updated_at: executionSeconds(value.updated_at) })
  }
  return jobs
}
export function profileJobExecutionRow(job) {
  return { id: `gateway:${job.id}`, execution_mode: 'gateway', requested: { kind: 'profile', profile: job.target_profile, role: null },
    observed: job.observed, status: job.status, task_index: null, model: job.model, provider: job.provider, model_source: job.model ? 'route' : null,
    started_at: job.created_at ?? null, updated_at: job.updated_at ?? null, job }
}
export async function profileJobsRequest(transport, scope, operation, payload = {}, isCurrent = () => true) {
  const allowed = { describe: [], list: [], control: ['job_id', 'operation', 'text'], result: ['job_id'] }
  if (!executionScopeKey(scope) || !Object.hasOwn(allowed, operation) || !payload || typeof payload !== 'object' || Array.isArray(payload) || Object.keys(payload).some(key => !allowed[operation].includes(key))) throw new Error('profile_job_invalid_request')
  if (['control', 'result'].includes(operation) && !executionId(payload.job_id)) throw new Error('profile_job_invalid_job')
  if (operation === 'control' && !['refresh', 'stop', 'steer'].includes(payload.operation)) throw new Error('profile_job_invalid_control')
  if (operation === 'control') {
    const fields = { refresh: [], stop: [], steer: ['text'] }[payload.operation]
    if (Object.keys(payload).some(key => !['job_id', 'operation', ...fields].includes(key)) || fields.some(key => !Object.hasOwn(payload, key))) throw new Error('profile_job_invalid_control')
    if (payload.operation === 'steer' && (typeof payload.text !== 'string' || !payload.text.trim() || payload.text.length > 16000)) throw new Error('profile_job_invalid_control')
  }
  if (!isCurrent()) throw new Error('profile_job_scope_changed')
  const route = selectExecutionRoute(await transport.profileRoutes(), scope)
  if (!route || !isCurrent()) throw new Error('profile_job_scope_changed')
  const frozen = deepClone(payload)
  let reply
  try { reply = await transport.requestProfile(route, `plugin.model-router.profile_jobs.${operation}`, { session_id: scope.sessionId, ...frozen }) }
  catch { const error = new Error('profile_job_outcome_unknown'); error.sent = true; throw error }
  if (!isCurrent()) { const error = new Error('profile_job_scope_changed'); error.sent = true; throw error }
  if (!reply || typeof reply !== 'object' || reply.schema !== 1) { const error = new Error('profile_job_outcome_unknown'); error.sent = true; throw error }
  const origin = reply.origin_profile || reply.job?.origin_profile
  if (origin !== route.targetProfile) { const error = new Error('profile_job_owner_mismatch'); error.sent = true; throw error }
  if (reply.error || ['error', 'refused', 'unknown'].includes(reply.status)) {
    const error = new Error('profile_job_request_refused'); error.noEffect = reply.no_effect === true; error.sent = !error.noEffect; throw error
  }
  if (['control', 'result'].includes(operation) && reply.job?.id !== frozen.job_id) { const error = new Error('profile_job_job_mismatch'); error.sent = true; throw error }
  return reply
}
export async function readProfileJobs(transport, scope, isCurrent = () => true) {
  const reply = await profileJobsRequest(transport, scope, 'describe', {}, isCurrent)
  if (reply.schema !== 1 || !EXECUTION_PROFILE.test(reply.origin_profile || '') || !/^[a-f0-9]{64}$/.test(reply.revision || '') ||
    reply.policy?.schema !== 1 || typeof reply.policy.enabled !== 'boolean' || !Array.isArray(reply.policy.targets) || !Array.isArray(reply.targets)) throw new Error('profile_job_capability_unavailable')
  if (reply.policy.targets.some(name => typeof name !== 'string' || !EXECUTION_PROFILE.test(name)) || new Set(reply.policy.targets).size !== reply.policy.targets.length) throw new Error('profile_job_capability_unavailable')
  if (reply.targets.length > 32 || reply.targets.some(item => !item || typeof item.profile !== 'string' || !EXECUTION_PROFILE.test(item.profile) || typeof item.available !== 'boolean' || (item.available && (typeof item.cwd !== 'string' || !item.cwd || item.cwd.length > 2048))) || new Set(reply.targets.map(item => item.profile)).size !== reply.targets.length) throw new Error('profile_job_capability_unavailable')
  const targets = reply.targets.slice(0, 32).filter(item => item && EXECUTION_PROFILE.test(item.profile || '')).map(item => ({ profile: item.profile,
    cwd: typeof item.cwd === 'string' && item.cwd.length <= 2048 ? item.cwd : null, available: item.available === true }))
  return { schema: 1, scope_key: executionScopeKey(scope), origin_profile: reply.origin_profile, supported: reply.supported === true,
    authority_blocked: reply.reason_code === 'operator_authority_unavailable',
    operator_cli_supported: reply.grant_management?.transport === 'host_cli' && reply.grant_management?.rpc_writable === false,
    policy: { schema: 1, enabled: reply.policy.enabled, targets: [...reply.policy.targets] }, revision: reply.revision, targets, completion_delivery: 'explicit_result' }
}
function nativeRouteKey(route) { return route ? JSON.stringify([route.connectionId, route.mode, route.profile, route.targetProfile]) : null }
function nativeJobKey(job) {
  return JSON.stringify([job.id, job.origin_profile, job.parent_session_id, job.target_profile, job.target_session_id,
    job.target_profile_id, job.target_instance_id, job.target_authority_epoch, job.target_cwd, job.admission_id])
}
export function nativeJobViewSupported(transport, job) {
  return ['profileRoutes', 'requestProfile', 'retainProfile', 'openSession'].every(name => typeof transport?.[name] === 'function') &&
    executionId(job?.id) && executionId(job?.target_session_id) && executionId(job?.target_profile_id) && executionId(job?.target_instance_id) &&
    Number.isSafeInteger(job?.target_authority_epoch) && job.target_authority_epoch >= 0 &&
    typeof job?.target_cwd === 'string' && job.target_cwd.length > 0 && job.target_cwd.length <= 2048 && !/[\x00-\x1f\x7f]/.test(job.target_cwd)
}
export async function openProfileJobNative(transport, scope, selectedJob, isCurrent = () => true) {
  let release
  try {
    if (!executionScopeKey(scope) || !nativeJobViewSupported(transport, selectedJob) || !isCurrent()) throw new Error('unavailable')
    // Copy only allowlisted identity fields; never retain raw target info or prompts.
    const selectedKey = nativeJobKey(selectedJob), jobId = selectedJob.id, targetProfile = selectedJob.target_profile
    const routes = await transport.profileRoutes()
    if (!isCurrent()) throw new Error('scope_changed')
    const source = selectExecutionRoute(routes, scope)
    if (!source) throw new Error('source_unavailable')
    const sourceKey = nativeRouteKey(source)
    const findTarget = rows => {
      if (!Array.isArray(rows) || nativeRouteKey(selectExecutionRoute(rows, scope)) !== sourceKey) throw new Error('source_changed')
      const found = rows.filter(row => row && row.connectionId === source.connectionId && row.mode === source.mode &&
        row.targetProfile === targetProfile && executionId(row.profile))
      if (found.length !== 1) throw new Error('target_ambiguous')
      return { ...found[0] }
    }
    const route = findTarget(routes), routeKey = nativeRouteKey(route)
    const check = async () => {
      if (!isCurrent()) throw new Error('scope_changed')
      const currentRoutes = await transport.profileRoutes()
      if (!isCurrent() || nativeRouteKey(findTarget(currentRoutes)) !== routeKey) throw new Error('route_changed')
      const reply = await profileJobsRequest(transport, scope, 'list', {}, isCurrent)
      if (!Array.isArray(reply.jobs) || reply.jobs.filter(row => row?.id === jobId).length !== 1) throw new Error('job_ambiguous')
      const job = normalizeProfileJobs(reply, source.targetProfile, scope.sessionId)?.find(row => row.id === jobId)
      if (!job || nativeJobKey(job) !== selectedKey || !nativeJobViewSupported(transport, job) || !isCurrent()) throw new Error('job_changed')
      // The source RPC itself awaited I/O: recheck the registry AFTER it too.
      const afterRoutes = await transport.profileRoutes()
      if (!isCurrent() || nativeRouteKey(findTarget(afterRoutes)) !== routeKey) throw new Error('route_changed')
      return job
    }
    let job = await check()
    release = await transport.retainProfile(route, { spawnPriority: 'foreground' })
    if (typeof release !== 'function') throw new Error('lease_unavailable')
    job = await check()
    const runtime = await transport.requestProfile(route, 'runtime.describe', {})
    job = await check()
    if (!runtime || runtime.profile_id !== job.target_profile_id || runtime.instance_id !== job.target_instance_id ||
      !Number.isSafeInteger(runtime.authority_epoch) || runtime.authority_epoch !== job.target_authority_epoch) throw new Error('runtime_changed')
    const info = await transport.requestProfile(route, 'session.info', { session_id: job.target_session_id })
    job = await check()
    // session.info is a flat native DTO without an SID echo. The exact request
    // plus native profile/source/client/CWD checks is the binding; do not invent one.
    if (!info || info.desktop_protocol !== 'hermes-gateway-v1' || info.profile_id !== job.target_profile_id ||
      info.profile_name !== job.target_profile || info.source !== 'tool' || info.cwd !== job.target_cwd ||
      info.client?.name !== 'model-router-profile-job') throw new Error('session_changed')
    await transport.openSession(job.target_session_id, { route, awaitHydration: true, forceResume: true,
      expectHistory: false, keepAllProfilesScope: true })
    // openSession intentionally changes focus. There is no AbortSignal contract
    // after that call starts; never roll back native navigation or replay a task.
    return { opened: true, source_current: isCurrent() }
  } catch { throw new Error('profile_job_native_view_unavailable') }
  finally { if (typeof release === 'function') { try { await release() } catch { throw new Error('profile_job_native_view_unavailable') } } }
}
export function ProfileJobControls({ job, scope, storage, fence, refresh }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [steer, setSteer] = useState(''), [result, setResult] = useState(null)
  const inFlight = useRef(false), fenceKey = JSON.stringify([scope.connectionId, scope.profile, job.id]), blocked = profileJobFence(storage, fenceKey)
  const operate = async (operation, extra = {}) => {
    if (inFlight.current) return
    const token = fence.capture()
    if (token.key !== executionScopeKey(scope) || !fence.current(token)) return
    if (blocked && !['refresh', 'stop', 'result'].includes(operation)) { setMessage('이전 요청의 결과가 미확인입니다. 재전송하지 않습니다.'); return }
    inFlight.current = true; setBusy(true); setMessage('')
    const mutating = operation === 'steer'
    try {
      if (mutating) profileJobFence(storage, fenceKey, { blocked: true, generation: job.execution_generation, prompt_id: job.pending_request?.prompt_id || null, operation })
      const reply = await profileJobsRequest(host, scope, operation === 'result' ? 'result' : 'control',
        operation === 'result' ? { job_id: job.id } : { job_id: job.id, operation, ...extra }, () => fence.current(token))
      if (operation === 'result') {
        if (reply.job?.id !== job.id || (reply.result !== null && (typeof reply.result?.text !== 'string' || reply.result.text.length > 65536))) throw new Error('profile_job_result_unavailable')
        setResult(reply.result?.text ?? null); setMessage(reply.result ? '저장된 결과를 회수했습니다. 부모 대화를 자동으로 재개한 것은 아닙니다.' : '아직 저장된 결과가 없습니다.')
      } else {
        if (mutating) profileJobFence(storage, fenceKey, null)
        setMessage(operation === 'stop' ? '정확한 작업의 중지를 요청했습니다. 종료 여부는 상태로 확인하세요.' : '요청을 보냈습니다. 실제 반영은 작업 상태로 확인하세요.')
      }
      await refresh()
    } catch (error) {
      if (mutating && !error?.sent) { try { profileJobFence(storage, fenceKey, null) } catch {} }
      if (fence.current(token)) setMessage(error?.noEffect ? '요청이 거절되어 해당 작업 변경은 수행되지 않았습니다. 현재 상태와 허용 범위를 확인하세요.' : '요청 결과를 확정할 수 없습니다. 다른 작업이나 새 프롬프트로 재시도하지 않습니다. 상태를 확인하세요.')
    } finally { inFlight.current = false; if (fence.current(token)) setBusy(false) }
  }
  const openNative = async () => {
    if (inFlight.current) return
    const token = fence.capture()
    if (token.key !== executionScopeKey(scope) || !fence.current(token)) return
    inFlight.current = true; setBusy(true); setMessage('')
    try { await openProfileJobNative(host, scope, job, () => fence.current(token)) }
    catch { if (fence.current(token)) setMessage('대상 상태·연결·권한을 확인할 수 없어 화면 열기를 완료하지 못했습니다. 상태를 확인하세요. 작업은 다시 제출하지 않습니다.') }
    finally { inFlight.current = false; if (fence.current(token)) setBusy(false) }
  }
  const pending = job.pending_request
  return jsxs('div', { style: executionStyles.row, children: [
    jsx(ExecutionRow, { row: profileJobExecutionRow(job), bare: true }),
    jsxs('div', { style: styles.actions, children: [
      jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => operate('refresh'), children: '상태 확인' }),
      jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy || !job.admission_id || PROFILE_JOB_TERMINAL.has(job.status), onClick: () => operate('stop'), children: '중지 요청' }),
      jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy || !job.result_available, onClick: () => operate('result'), children: '결과 보기' }),
      jsx(Button, { size: 'sm', variant: 'secondary', disabled: busy || !nativeJobViewSupported(host, job), onClick: openNative, children: 'Hermes에서 대상 대화 열기' })
    ] }),
    job.status === 'running' ? jsxs('div', { style: styles.field, children: [jsx('label', { htmlFor: `job-steer-${job.id}`, children: '실행 중인 작업에 지시' }),
      jsx(Input, { id: `job-steer-${job.id}`, value: steer, disabled: busy || Boolean(blocked) || !job.can_steer, maxLength: 16000, onChange: event => setSteer(event.target.value) }),
      jsx(Button, { size: 'sm', variant: 'secondary', disabled: busy || Boolean(blocked) || !job.can_steer || !steer.trim(), onClick: () => operate('steer', { text: steer }), children: '이 작업에만 지시 보내기' })] }) : null,
    pending ? jsxs('div', { style: styles.field, children: [jsx('p', { style: styles.hint, children: pending.kind === 'approval' ? '사용자 승인을 기다립니다. 대상 대화를 열어 전체 요청을 확인하세요.' : '사용자 답변을 기다립니다. 대상 대화를 열어 질문을 확인하세요.' }),
      jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }, children: pending.text || '요청 내용을 확인할 수 없습니다.' }),
      jsx('p', { style: styles.hint, children: '여기는 읽기 전용 요약입니다. 승인·거절·답변은 기본 Hermes 화면에서만 보냅니다. 해당 계정의 권한과 현재 요청에 대한 검사를 그대로 따릅니다.' })
    ] }) : null,
    blocked ? jsx('p', { style: styles.hint, role: 'status', children: '미확인 요청이 있어 추가 지시·승인을 잠갔습니다. 상태와 결과를 확인하세요. 동일 작업을 새로 실행하지 않습니다.' }) : null,
    message ? jsx('p', { style: styles.hint, role: 'status', children: message }) : null,
    result !== null ? jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap' }, children: result }) : null
  ] })
}
export function ProfileJobsPanel({ ctx, scope, observer, executionData, refreshExecutions }) {
  const key = executionScopeKey(scope)
  const observationGeneration = useValue(observer?.revisionAtom || EXECUTION_EMPTY_ATOM)
  const enabled = Boolean(key && observer?.eligible(scope))
  const query = useQuery({ queryKey: ['model-router', 'profile-jobs-policy-active', observer?.cacheId, key, observationGeneration],
    queryFn: () => observer.policy(scope), enabled, retry: false, staleTime: 5000, gcTime: 0 })
  const data = enabled && observer.accepts(scope, query.data) ? query.data : null
  return jsxs('section', { style: styles.section, 'aria-label': '전체 프로필 작업', children: [
    jsx('h3', { style: styles.heading, children: '전체 프로필 작업 · 별도 선택 기능' }),
    jsx('p', { style: styles.hint, children: '허용한 프로필의 별도 작업 대화에서 실행합니다. 대상의 계정·모델·메모리·도구 정책을 따르며 모든 도구를 강제로 여는 기능은 아닙니다. 네이티브 위임 설정은 그대로입니다.' }),
    jsx('p', { style: styles.hint, children: '승인·답변은 작업 카드의 「Hermes에서 대상 대화 열기」로 이동해 처리하세요. 완료 결과는 「결과 보기」로 회수하며 부모 대화를 자동으로 재개하지 않습니다.' }),
    !enabled ? jsx('p', { style: styles.hint, children: '이미 열린 원래 대화의 연결과 프로필을 확인한 뒤 지원 상태를 조회합니다. 이 패널이 연결을 시작하지는 않습니다.' }) :
    query.isPending ? jsx('p', { style: styles.hint, children: '지원 상태를 확인하고 있습니다…' }) : query.isError || !data ? jsx('p', { style: styles.hint, role: 'status', children: '이 출발 프로필의 설정을 읽을 수 없습니다. 연결과 플러그인 준비 상태를 확인하세요. 다른 실행 방식으로 대신 시작하지 않습니다.' }) :
      jsxs('div', { style: styles.field, children: [
        jsx('p', { style: styles.hint, children: `출발 프로필 ${data.origin_profile} · ${data.policy.enabled ? `${data.policy.targets.length}개 프로필 허용` : '전체 프로필 작업 꺼짐'}` }),
        data.policy.targets.length ? jsx('p', { style: styles.hint, children: `허용 대상: ${data.policy.targets.join(', ')}` }) : null,
        jsx(Button, { size: 'sm', variant: 'ghost', onClick: () => Promise.all([query.refetch(), refreshExecutions()]), children: '현재 허용 범위 새로고침' }),
        data.operator_cli_supported ? jsxs('details', { children: [
          jsx('summary', { style: executionStyles.summary, children: '운영자 설정 안내 · 이 화면은 읽기 전용' }),
          jsx('p', { style: styles.hint, children: `연결 ${scope.connectionId}의 Hermes 호스트에서 운영자 터미널을 열고 출발 프로필 ${data.origin_profile}를 명시하세요. 원격 연결이라면 내 PC가 아니라 해당 서버에서 실행해야 합니다. 아래 예시는 그대로 실행하지 말고 실제 대상 이름과 검토 결과를 넣으세요.` }),
          jsx('p', { style: styles.hint, children: '1. status 명령에 targets JSON을 전달해 대상 계정·도구·메모리·모델 비용과 현재 작업 폴더를 검토합니다. 결과의 operator_revision을 복사하세요.' }),
          jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap' }, children: `hermes --profile ${data.origin_profile} model-router profile-jobs-status --body -` }),
          jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap' }, children: '{"targets":["허용할_프로필명"]}' }),
          jsx('p', { style: styles.hint, children: "JSON은 표준입력으로 전달합니다. PowerShell: 'JSON 원문' | 위_명령 / Git Bash: printf '%s' 'JSON 원문' | 위_명령. 실제 JSON에는 영문 프로필 이름과 revision을 사용하세요." }),
          jsx('p', { style: styles.hint, children: '2. 같은 대상 목록과 방금 검토한 revision을 configure 명령에 전달합니다. 명령을 시작한 뒤 결과가 미확인이면 다시 쓰지 말고 기존 프로세스가 끝난 후 status로 확인하세요.' }),
          jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap' }, children: `hermes --profile ${data.origin_profile} model-router profile-jobs-configure --body -` }),
          jsx('pre', { style: { ...styles.value, whiteSpace: 'pre-wrap' }, children: JSON.stringify({ expected_operator_revision: '1단계에서_검토한_64자리_revision', enabled: true, targets: ['같은_대상_프로필명'], acknowledge_scope: true }, null, 2) }),
          jsx('p', { style: styles.hint, children: '전체 철회는 targets: []를 먼저 status로 검토한 뒤 enabled: false, targets: []로 저장합니다. 허용 철회가 이미 실행 중인 작업을 자동 중지하지는 않으므로 작업 카드를 별도로 확인하세요.' }),
          jsx('p', { style: styles.hint, children: 'CLI는 기존 운영자 OS 권한을 사용합니다. 이 안내나 체크값이 관리자 권한을 만들지는 않습니다. 승인·거절·답변은 이 플러그인에서 중계하지 않습니다.' })
        ] }) : jsx('p', { style: styles.hint, role: 'status', children: '이 버전에서 운영자 CLI 지원을 확인할 수 없습니다. 이 화면에서 권한 저장·승인·답변을 대신 보내지 않습니다.' }),
        jsxs('details', { children: [jsx('summary', { style: executionStyles.summary, children: '실행·연결 범위' }),
          jsx('p', { style: styles.hint, children: '작업 실행은 이미 실행 중인 Gateway만 사용하며 시작·복구하지 않습니다. 대상 대화 열기는 Hermes의 기본 연결 정책을 따라 프로필 백엔드에 연결할 수 있지만 작업을 새로 제출하지 않습니다. 같은 작업 폴더의 전체 프로필 작업은 동시에 하나만 허용합니다.' })] })
      ] })
  ] })
}

export default {
  id: PLUGIN_ID,
  name: '모델 및 라우팅',
  version: '0.12.0',
  defaultEnabled: false,
  register(ctx) {
    preparationStorage = ctx.storage || null
    if (typeof ctx.onDispose === 'function') ctx.onDispose(cancelProfilePreparation)
    const executionObserver = typeof ctx.onDispose === 'function' ? createActiveExecutionObserver(host, DesktopSDK) : null
    if (executionObserver) ctx.onDispose(() => executionObserver.dispose())
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
    // These slots are read-only until the user explicitly operates a worker.
    // Older SDKs keep settings usable without pretending to support a roster.
    if (typeof host.state?.activeSessionId?.get === 'function') {
      ctx.registerMany([
        // No layout pane: the host disables a single-pane plugin as a whole when that pane is closed.
        { id: 'execution-composer', area: DesktopSDK.COMPOSER_AREAS?.top || 'composer.top', order: 40, render: () => jsx(ComposerFocusGate, { children: () => jsx(ExecutionPanel, { compact: true, ctx, observer: executionObserver }) }) }
      ])
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
