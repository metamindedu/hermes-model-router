import React from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '@/components/ui/tooltip'
import './fixture-model-picker-shim.jsx'
import { RouterPage } from '../../desktop/plugin.js'

window.fixtureErrors = []
window.fixtureConsole = []
for (const level of ['error', 'warn']) {
  const original = console[level]
  console[level] = (...args) => { if (window.fixtureConsole.length < 64) window.fixtureConsole.push({ level, message: args.map(String).join(' ').slice(0, 1000) }); original.apply(console, args) }
}
window.addEventListener('error', event => window.fixtureErrors.push(String(event.message)))
window.addEventListener('unhandledrejection', event => window.fixtureErrors.push(String(event.reason)))

// Invented profiles, services and model names. Nothing here is read from a
// real profile, account or provider.
const LONG = 'research-profile-with-a-long-name-for-layout'
const route = (provider, model, reasoning) => ({ provider, model, reasoning })
const models = {
  main: route('fixture-cloud', 'fixture-large-2-preview-with-a-very-long-identifier-900k', 'medium'),
  delegation: route('fixture-cloud', 'fixture-small-2', 'max'),
  compression: route('sample-lab', 'sample-mini', 'medium'),
  title: route('', '', '')
}
const slotIds = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use', 'advise']
// Invented operator-added slots (one with a long label/description for layout).
const customSlots = [
  { id: 'custom:3d-graphics', label: '3D·그래픽', description: 'Blender Python·Three.js/WebGL·셰이더 코드와 렌더 결과 검수' },
  { id: 'custom:ko-writing-long-identifier', label: '한국어 글쓰기·윤문 전문 슬롯 이름', description: '자연스러운 한국어 원고 작성과 윤문, 번역투 제거, 지정한 문체 적용까지 맡기는 아주 긴 설명 문장으로 줄바꿈을 확인합니다' }
]
const declarations = Object.fromEntries([...slotIds, ...customSlots.map(item => item.id)].map(id => [id, id === 'design' || id === 'custom:3d-graphics'
  ? { follow: 'custom', custom: route('sample-lab', 'sample-pro-reasoner', 'high') }
  : { follow: 'main', custom: null }]))
const slotPolicy = Object.fromEntries(slotIds.map(id => [id, id === 'code-complex'
  ? { mode: 'custom', chain: [{ provider: 'sample-lab', model: 'sample-flash' }] }
  : { mode: 'off', chain: [] }]))
const profile = name => ({ name, models: structuredClone(models), actual_models: structuredClone(models),
  slots: { schema: 1, capable: true, stored: ['design'], declarations: structuredClone(declarations) },
  routing: { enabled: name !== 'writer', slots: { design: structuredClone(declarations.design) } },
  drift: [],
  native_delegation: { schema: 1, supported: true, editable: true, backend: 'model-router', digest: 'a'.repeat(64),
    slot_policy_supported: true, policy_schema: 2, auto_policy_schema: 0, slot_policy: structuredClone(slotPolicy), auto_slot_policy: Object.fromEntries(slotIds.map(id => [id, { mode: 'off', chain: [] }])),
    auto_supported: true,
    profile_routes: { profiles: [], default: null }, role_intro_inheritance: { schema: 1, supported: true, code_identity: 'e'.repeat(64), activation: 'new_session_or_supported_rebuild' }, warnings: [] },
  role_intro: { schema: 1, state: 'available', default_description: 'Invented role text', default_source: 'profile_metadata', description_auto: false, digest: 'f'.repeat(64) } })
const status = { revision: 7, current_profile: 'default', recent_apply: null,
  slot_capabilities: { schema: 1, slots: slotIds, purposes: { plan: 'design', implementation: 'code-complex', mechanical: 'code-simple', 'preliminary-review': 'verify-simple', 'semantic-final': 'verify-complex', 'independent-review': 'verify-complex', 'computer-use': 'computer-use', advise: 'advise' }, follows: ['main', 'custom'], blocking_profiles: [],
    custom_slots_supported: true, custom_slot_limit: 4, custom_slots: structuredClone(customSlots) },
  readiness_context: { schema: 1, base_identity: 'd'.repeat(64), source_profile: 'default', release: null },
  profiles: ['default', 'writer', LONG].map(profile) }
const caps = names => Object.fromEntries(names.map(name => [name, { fast: false, reasoning: !name.includes('mini') }]))
const catalog = owner => ({ provider: 'fixture-cloud', model: 'fixture-small-2', providers: [
  { slug: 'fixture-cloud', name: 'Fixture Cloud', authenticated: true, is_current: true,
    models: ['fixture-large-2-preview-with-a-very-long-identifier-900k', 'fixture-large-2', 'fixture-small-2', 'fixture-small-2-fast', owner + '-only-model'],
    capabilities: caps(['fixture-large-2-preview-with-a-very-long-identifier-900k', 'fixture-large-2', 'fixture-small-2', 'fixture-small-2-fast', owner + '-only-model']) },
  { slug: 'sample-lab', name: 'Sample Lab', authenticated: true, models: ['sample-pro-reasoner', 'sample-flash', 'sample-mini'], capabilities: caps(['sample-pro-reasoner', 'sample-flash', 'sample-mini']) }
] })
const data = { actions: [], catalogReads: [], fail: false }
window.fixture = data
const reply = value => ({ code: 0, output: 'MODEL_ROUTER_JSON:' + JSON.stringify(value) + '\n' })
window.fixtureRequest = async (method, params) => {
  if (method === 'model.options') {
    data.catalogReads.push({ via: 'request', params })
    if (data.fail) throw new Error('가짜 실패: 모델 목록을 불러오지 못했습니다.')
    return catalog(params.profile)
  }
  if (method !== 'cli.exec') throw new Error('forbidden synthetic method: ' + method)
  const index = params.argv.indexOf('model-router'), operation = params.argv[index + 1]
  data.actions.push({ operation, body: JSON.parse(params.argv.at(-1)) })
  if (operation === 'status') return reply(structuredClone(status))
  if (operation === 'preview' || operation === 'delegation-preview') return reply({ plan_id: 'fixture-plan-' + data.actions.length, changes: [], warnings: [] })
  if (operation === 'custom-slots-preview') return reply({ plan_id: 'fixture-plan-' + data.actions.length, warnings: [],
    changes: [{ profile: '*', field: 'custom_slots' }, { profile: 'writer', field: 'routing.slots', before: { 'custom:3d-graphics': { follow: 'main', custom: null } }, after: null }] })
  // Nothing is written anywhere: the receipt is invented so the save chain can be watched end to end.
  if (operation === 'apply') return reply({ status: 'applied', revision: status.revision })
  throw new Error('forbidden synthetic operation: ' + operation)
}
window.fixtureRoutes = () => status.profiles.map(row => ({ mode: 'local', connectionId: 'local', profile: row.name, targetProfile: row.name, ...(row.name === 'default' ? { primary: true } : {}) }))
window.fixtureRequestProfile = async (descriptor, method, params) => {
  if (method !== 'model.options') throw new Error('forbidden synthetic routed method: ' + method)
  data.catalogReads.push({ via: 'requestProfile', descriptor, params })
  if (data.fail) throw new Error('가짜 실패: 모델 목록을 불러오지 못했습니다.')
  return catalog(descriptor.targetProfile)
}
const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
const values = new Map(), storage = { get: (key, fallback = null) => values.has(key) ? structuredClone(values.get(key)) : fallback, set: (key, value) => values.set(key, structuredClone(value)) }
function App() {
  return <QueryClientProvider client={client}><TooltipProvider><div style={{ height: '100vh', overflowY: 'auto', overscrollBehavior: 'contain' }}>
    <p style={{ fontSize: 12, margin: 0, padding: '8px 12px' }}>격리 검수 · 실제 Native 컴포넌트 · 프로필·서비스·모델 목록은 모두 가짜 · 저장/모델 호출 없음</p>
    <RouterPage ctx={{ storage }} />
  </div></TooltipProvider></QueryClientProvider>
}
createRoot(document.getElementById('root')).render(<App />)
