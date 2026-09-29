import {
  Badge,
  Button,
  Checkbox,
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
    gap: '1.6rem',
    color: 'var(--ui-text-primary)'
  },
  header: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' },
  title: { margin: 0, fontSize: '1.5rem', lineHeight: 1.2, fontWeight: 650, letterSpacing: '-0.025em' },
  subtitle: { margin: '0.55rem 0 0', color: 'var(--ui-text-secondary)', lineHeight: 1.55, maxWidth: '48rem' },
  section: { display: 'flex', flexDirection: 'column', gap: '1rem', borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '1.2rem' },
  sectionHeading: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' },
  heading: { margin: 0, fontSize: '1rem', fontWeight: 620 },
  hint: { margin: 0, color: 'var(--ui-text-tertiary)', fontSize: '0.82rem', lineHeight: 1.5 },
  fields: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 15rem), 1fr))', gap: '0.8rem 1rem' },
  field: { minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.4rem', color: 'var(--ui-text-secondary)', fontSize: '0.82rem' },
  fieldName: { color: 'var(--ui-text-secondary)', fontWeight: 560 },
  roleGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 19rem), 1fr))', columnGap: '1.5rem' },
  roleCard: { minWidth: 0, paddingBlock: '1rem', borderBottom: '1px solid var(--ui-stroke-tertiary)', display: 'flex', flexDirection: 'column', gap: '0.85rem' },
  roleTitle: { margin: 0, fontSize: '0.95rem', fontWeight: 620 },
  choiceGroup: { display: 'flex', flexDirection: 'column', gap: '0.7rem' },
  choiceRow: { display: 'flex', gap: '0.65rem', alignItems: 'flex-start', color: 'var(--ui-text-primary)' },
  choiceCopy: { display: 'flex', flexDirection: 'column', gap: '0.15rem', minWidth: 0 },
  profileList: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 13rem), 1fr))', gap: '0.45rem 1rem' },
  profileChoice: { minWidth: 0, display: 'flex', alignItems: 'center', gap: '0.6rem', paddingBlock: '0.3rem' },
  notice: { padding: '0.8rem 0', color: 'var(--ui-text-secondary)', lineHeight: 1.55 },
  warning: { borderInlineStart: '2px solid var(--ui-accent)', paddingInlineStart: '0.8rem', color: 'var(--ui-text-secondary)', lineHeight: 1.55 },
  message: { padding: '0.75rem 0', color: 'var(--ui-text-secondary)', lineHeight: 1.5 },
  changes: { display: 'flex', flexDirection: 'column', gap: '0.6rem' },
  change: { display: 'grid', gridTemplateColumns: 'minmax(8rem, 0.8fr) minmax(0, 1fr) minmax(0, 1fr)', gap: '0.8rem', paddingBlock: '0.7rem', borderBottom: '1px solid var(--ui-stroke-tertiary)', alignItems: 'start' },
  changeLabel: { minWidth: 0, fontWeight: 600, overflowWrap: 'anywhere' },
  value: { minWidth: 0, fontFamily: 'var(--font-mono, ui-monospace, monospace)', fontSize: '0.78rem', color: 'var(--ui-text-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' },
  actions: { display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap', paddingTop: '0.4rem' },
  statusLine: { display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' },
  actual: { margin: 0, color: 'var(--ui-text-tertiary)', fontSize: '0.78rem', lineHeight: 1.45, overflowWrap: 'anywhere' },
  fieldset: { margin: 0, padding: 0, border: 0, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.8rem' }
}

// Pure helpers are kept separate so the routing payload and stale-scope policy
// can be exercised without loading the Desktop renderer SDK in Node tests.
export function scopeFingerprint(connectionId, profile, gateway) {
  return JSON.stringify([connectionId || 'local', profile || 'default', gateway || 'idle'])
}

export function copyProfileDraft(profile) {
  if (!profile || typeof profile !== 'object' || !profile.models || !profile.routing) return null
  return JSON.parse(JSON.stringify({ models: profile.models, routing: profile.routing }))
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
    models: JSON.parse(JSON.stringify(draft.models)),
    model_targets: [...modelTargets],
    routing: { ...JSON.parse(JSON.stringify(draft.routing)), enabled: routingProfiles.includes(profile) },
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
  const operation = { '/status': 'status', '/preview': 'preview', '/apply': 'apply' }[path]
  if (!operation) throw new Error('지원하지 않는 플러그인 요청입니다.')
  const profile = host.state.profile.get() || 'default'
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
  const [modelTargets, setModelTargets] = useState([])
  const [routingProfiles, setRoutingProfiles] = useState([])
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
    setModelTargets([])
    setRoutingProfiles([])
    setPageError('')
    if (applyPendingRef.current) {
      applyPendingRef.current = false
      setApplyPending(false)
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
    setModelTargets([])
    setRoutingProfiles(profiles.filter(item => item.routing?.enabled === true).map(item => item.name))
  }, [readyScope, scopeKey, statusQuery.data, selectedProfile, profiles])

  const invalidatePlan = () => {
    generationRef.current += 1
    setPreview(null)
    setPreviewPending(false)
    setReviewed(false)
    setPageError('')
  }
  const updateDraft = updater => {
    invalidatePlan()
    setDraft(current => current ? updater(current) : current)
  }
  const currentRow = profiles.find(item => item.name === selectedProfile) || null
  const disabled = applyPending || needsReload || statusQuery.isFetching
  const validPreview = previewMatchesScope(preview, scopeKey, generationRef.current, selectedProfile)
  const activeRoutes = draft?.routing || {}

  const selectProfile = name => {
    const row = profiles.find(item => item.name === name)
    if (!row) return
    invalidatePlan()
    setSelectedProfile(name)
    setDraft(copyProfileDraft(row))
    setModelTargets([])
  }

  const toggleModelTarget = (name, checked) => {
    invalidatePlan()
    setModelTargets(current => toggleName(current, name, checked))
  }

  const toggleRoutingProfile = (name, checked) => {
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
  const updateFallback = (group, field, value) => updateDraft(current => ({
    ...current,
    routing: {
      ...current.routing,
      fallback: {
        ...current.routing.fallback,
        [group]: { ...(current.routing.fallback[group] || {}), [field]: value }
      }
    }
  }))

  const changeFollow = (group, value) => updateDraft(current => ({ ...current, routing: { ...current.routing, [group]: { follow: value, custom: value === 'custom' ? { ...(current.routing[group].custom || current.models[group === 'heavy' ? 'main' : 'delegation']) } : null } } }))
  const toggleRoutingEnabled = checked => {
    invalidatePlan()
    setDraft(current => current ? { ...current, routing: { ...current.routing, enabled: checked } } : current)
    if (selectedProfile) setRoutingProfiles(current => toggleName(current, selectedProfile, checked))
  }

  const handlePreview = async () => {
    if (!currentRow || !draft || !statusQuery.data || disabled) return
    const token = ++generationRef.current
    const capturedScope = scopeKey
    const capturedProfile = selectedProfile
    setPreview(null)
    setReviewed(false)
    setPageError('')
    setPreviewPending(true)
    try {
      const body = buildPreviewBody(statusQuery.data.revision, capturedProfile, draft, modelTargets, routingProfiles)
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
    if (!validPreview || !reviewed || applyPendingRef.current || applyPending || needsReload || !preview?.plan_id) return
    const token = generationRef.current
    const capturedScope = scopeKey
    applyPendingRef.current = true
    setApplyPending(true)
    setPreview(null)
    setReviewed(false)
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
      needsReloadRef.current = true
      setNeedsReload(true)
    } catch (error) {
      if (scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) {
        generationRef.current += 1
        return
      }
      if (generationRef.current === token) {
        setApplyOutcome({ kind: 'unknown', message: error?.message || '적용 결과를 확인할 수 없습니다.' })
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
    const capturedScope = scopeKey
    const token = generationRef.current
    setPageError('')
    const response = await statusQuery.refetch()
    if (generationRef.current !== token || scopeFingerprint(host.state.connectionId.get(), host.state.profile.get(), host.state.gateway.get()) !== capturedScope) return
    if (!response.data) {
      setPageError(response.error?.message || '상태를 다시 불러오지 못했습니다.')
      return
    }
    const rows = Array.isArray(response.data.profiles) ? response.data.profiles : []
    const row = rows.find(item => item.name === selectedProfile) || rows.find(item => item.name === response.data.current_profile) || rows[0]
    generationRef.current += 1
    setPreview(null)
    setReviewed(false)
    setModelTargets([])
    setRoutingProfiles(rows.filter(item => item.routing?.enabled === true).map(item => item.name))
    if (row) {
      setSelectedProfile(row.name)
      setDraft(copyProfileDraft(row))
    } else {
      setSelectedProfile(null)
      setDraft(null)
    }
    needsReloadRef.current = false
    setNeedsReload(false)
    setApplyOutcome(null)
  }

  if (readyScope !== scopeKey || statusQuery.isPending) {
    return jsxs('main', { style: styles.page, 'aria-busy': true, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'status', style: styles.statusLine, children: [jsx(GlyphSpinner, {}), jsx('span', { style: styles.hint, children: '프로필 설정을 불러오고 있습니다.' })] })] })
  }

  if (statusQuery.isError) {
    return jsxs('main', { style: styles.page, children: [jsx('h1', { style: styles.title, children: '모델 및 라우팅' }), jsxs('div', { role: 'alert', style: styles.warning, children: [jsx('strong', { children: '설정 서비스를 사용할 수 없습니다.' }), jsx('p', { style: styles.hint, children: '백엔드가 꺼져 있거나 아직 준비되지 않았습니다. 잠시 후 다시 불러오세요. 이 화면에서는 로컬 파일이나 프로필 설정을 직접 변경하지 않습니다.' }), jsx('p', { style: styles.hint, children: statusQuery.error?.message || '상태 요청에 실패했습니다.' }), jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => void statusQuery.refetch(), children: '다시 불러오기' })] })] })
  }

  const modelFields = draft ? jsx('div', {
    style: styles.roleGrid,
    children: ROLES.map(role => jsxs('article', {
      style: styles.roleCard,
      children: [
        jsxs('div', { children: [jsx('h3', { style: styles.roleTitle, children: role.label }), jsx('p', { style: { ...styles.hint, marginTop: '0.25rem' }, children: role.description })] }),
        jsx(RoleRouteFields, { prefix: `model-${role.id}`, route: draft.models?.[role.id], disabled, onChange: (field, value) => updateRole(role.id, field, value) }),
        jsx('p', { style: styles.actual, children: `실제 설정: ${readableValue(currentRow?.actual_models?.[role.id])}` })
      ]
    }, role.id))
  }) : jsx('p', { role: 'alert', style: styles.warning, children: '선택한 프로필의 모델 또는 라우팅 정보가 없습니다. 프로필을 다시 불러와 상태를 확인하세요.' })

  const modelTargetGroup = jsx('fieldset', {
    style: styles.fieldset,
    children: [
      jsx('legend', { style: styles.fieldName, children: '모델 설정 적용 대상' }),
      jsx('p', { style: styles.hint, children: '아래 프로필에만 기본·위임·압축·제목 모델을 기록합니다. 아무것도 선택하지 않으면 모델 값은 변경하지 않습니다.' }),
      jsx('div', { style: styles.profileList, children: profiles.map(row => jsx('div', { style: styles.profileChoice, children: jsx(CheckRow, { id: `model-target-${row.name}`, label: row.name, checked: modelTargets.includes(row.name), disabled, onChange: checked => toggleModelTarget(row.name, checked) }) }, row.name)) })
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
      jsx('div', { style: { borderTop: '1px solid var(--ui-stroke-tertiary)', paddingTop: '1rem' }, children: jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [jsx(CheckRow, { id: 'fallback-enabled', label: '명시적 대체 모델 사용', detail: '실패 시 추가 비용이 발생할 수 있습니다. 두 작업 경로의 공급자·모델·추론 강도를 각각 지정해야 합니다.', checked: activeRoutes.fallback?.enabled === true, disabled, onChange: checked => updateDraft(current => ({ ...current, routing: { ...current.routing, fallback: { ...current.routing.fallback, enabled: checked } } })) }), activeRoutes.fallback?.enabled ? jsxs('div', { style: styles.warning, children: [jsx('strong', { children: '대체 호출은 별도 모델 비용이 발생할 수 있습니다.' }), jsx('p', { style: { ...styles.hint, marginTop: '0.25rem' }, children: '자동으로 저렴하거나 무료인 모델을 선택하지 않습니다. 아래 두 경로를 직접 확인하세요.' })] }) : null, activeRoutes.fallback?.enabled ? jsxs('div', { style: styles.roleGrid, children: [jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '무거운 작업 대체 모델' }), jsx(RoleRouteFields, { prefix: 'fallback-heavy', route: activeRoutes.fallback.heavy, disabled, onChange: (field, value) => updateFallback('heavy', field, value) })] }), jsxs('article', { style: styles.roleCard, children: [jsx('h3', { style: styles.roleTitle, children: '가벼운 작업 대체 모델' }), jsx(RoleRouteFields, { prefix: 'fallback-light', route: activeRoutes.fallback.light, disabled, onChange: (field, value) => updateFallback('light', field, value) })] })] }) : null] }) })
    ]
  }) : null

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
      profiles.length ? section('작업 라우팅', '무거운 작업과 가벼운 작업은 각각 독립적으로 대상을 정합니다. 팔로우 설정은 현재 선택한 프로필의 모델을 따릅니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '1.4rem' }, children: [routingFields, routingProfileGroup] })) : null,
      pageError ? jsx('div', { role: 'alert', style: styles.warning, children: pageError }) : null,
      applyOutcome ? jsxs('div', { role: 'status', 'aria-live': 'polite', style: applyOutcome.kind === 'success' ? styles.message : styles.warning, children: [jsx('strong', { children: applyOutcome.kind === 'success' ? '적용 요청이 완료되었습니다.' : applyOutcome.kind === 'partial' ? '일부 설정만 적용되었을 수 있습니다.' : '적용 결과를 확인할 수 없습니다.' }), jsx('p', { style: styles.hint, children: applyOutcome.message || (applyOutcome.kind === 'success' ? '실제 상태를 새로고침해 확인하세요. 같은 계획을 다시 적용하지 않습니다.' : '다시 적용하지 마세요. 상태를 새로고침해 실제 반영 여부를 확인하세요.') }), applyOutcome.result ? jsx('p', { style: styles.value, children: readableValue(applyOutcome.result) }) : null] }) : null,
      needsReload ? jsx('div', { style: styles.actions, children: jsx(Button, { size: 'sm', variant: 'secondary', disabled: statusQuery.isFetching, onClick: () => void reloadStatus(), children: statusQuery.isFetching ? '상태 확인 중…' : '실제 상태 확인 후 편집 재개' }) }) : null,
      profiles.length && !needsReload ? section('미리보기 및 적용', '변경 전후 값을 확인한 다음 별도 확인을 거쳐 적용합니다. 미리보기는 설정을 변경하지 않습니다.', jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9rem' }, children: [
        jsx('p', { style: styles.hint, children: `설정 revision: ${statusQuery.data?.revision ?? '확인할 수 없음'} · 모델 적용 대상 ${modelTargets.length}개 · 라우팅 활성 대상 ${routingProfiles.length}개` }),
        jsx(Button, { size: 'sm', variant: 'secondary', disabled: !canPreview, onClick: () => void handlePreview(), children: previewPending ? '미리보기 계산 중…' : '변경 내용 미리보기' }),
        validPreview ? jsxs('div', { style: styles.section, children: [
          jsxs('div', { style: styles.statusLine, children: [jsx(Badge, { variant: 'muted', children: `${previewChanges.length}개 변경` }), preview.expires_at ? jsx('span', { style: styles.hint, children: `만료: ${preview.expires_at}` }) : null] }),
          previewChanges.length ? jsxs('div', { style: styles.changes, children: [jsx('div', { style: { ...styles.change, color: 'var(--ui-text-tertiary)', fontSize: '0.75rem', fontWeight: 600 }, children: [jsx('span', { children: '프로필 · 항목' }), jsx('span', { children: '변경 전' }), jsx('span', { children: '변경 후' })] }), previewChanges.map((change, index) => jsxs('div', { style: styles.change, children: [jsx('span', { style: styles.changeLabel, children: `${change.profile || '—'} · ${change.field || '항목'}` }), jsx('code', { style: styles.value, children: readableValue(change.before) }), jsx('code', { style: styles.value, children: readableValue(change.after) })] }, `${change.profile || ''}:${change.field || index}`))] }) : jsx('p', { style: styles.message, children: '변경 사항이 없습니다. 적용할 내용이 없습니다.' }),
          Array.isArray(preview.warnings) && preview.warnings.length ? jsx('div', { style: styles.warning, children: preview.warnings.map((warning, index) => jsx('p', { style: { margin: index ? '0.35rem 0 0' : 0 }, children: readableValue(warning) }, index)) }) : null,
          previewChanges.length ? jsxs('div', { style: styles.actions, children: [jsx(CheckRow, { id: 'confirm-preview', label: '변경 전후 내용을 확인했습니다.', checked: reviewed, disabled: applyPending || needsReload, onChange: setReviewed }), jsx(Button, { size: 'sm', disabled: !reviewed || applyPending || !validPreview || needsReload, onClick: () => void handleApply(), children: applyPending ? '적용 중…' : '확인 후 적용' })] }) : null
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
