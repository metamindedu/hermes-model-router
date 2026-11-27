import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const strip = code => code.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
  .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
  .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
const api = new Function('DesktopSDK', `${strip(source)}\nreturn { TASK_SLOTS, taskSlots, setCustomTaskSlots, customSlotDefinitions, customSlotDraftError, customSlotChangeLines,
  slotSupport, slotDraftError, editedSlotIds, mergePartialSlots, slotsCopyable, executionIdentity, executionLabel, executionShortLabel, CUSTOM_SLOT_LIMIT }`)({})
const threeD = { id: 'custom:3d-graphics', label: '3D·그래픽', description: 'Blender Python·Three.js 코드와 렌더 결과 검수', tier: 'heavy' }
const writing = { id: 'custom:ko-writing', label: '한국어 글쓰기', description: '자연스러운 한국어 원고 작성과 윤문', tier: 'light' }
const status = list => ({ slot_capabilities: { schema: 1, custom_slots_supported: true, custom_slots: list, blocking_profiles: [] } })

test('custom slots from the status follow the built-ins; a malformed list adds none', () => {
  const { TASK_SLOTS, taskSlots, setCustomTaskSlots, customSlotDefinitions } = api
  setCustomTaskSlots(status([threeD, writing]))
  assert.deepEqual(taskSlots().map(slot => slot.id), [...TASK_SLOTS.map(slot => slot.id), threeD.id, writing.id])
  assert.equal(taskSlots().at(-1).custom, true)
  assert.equal(TASK_SLOTS.length, 7)
  for (const bad of [
    [{ ...threeD, id: 'custom-3d' }], [{ ...threeD, tier: 'x' }], [{ ...threeD, label: 'x'.repeat(25) }],
    [{ ...threeD, description: 'a\nb' }], [threeD, threeD], Array(5).fill(threeD), 'nope'
  ]) assert.deepEqual(customSlotDefinitions(status(bad)), [], JSON.stringify(bad).slice(0, 60))
  setCustomTaskSlots(status(undefined))
  assert.deepEqual(taskSlots().map(slot => slot.id), TASK_SLOTS.map(slot => slot.id))
})

test('slot helpers cover custom slots; their declarations save after the built-ins', () => {
  const { setCustomTaskSlots, slotSupport, slotDraftError, editedSlotIds, mergePartialSlots, slotsCopyable } = api
  setCustomTaskSlots(status([threeD]))
  const ids = ['design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use', 'advise', threeD.id]
  const declarations = Object.fromEntries(ids.map(id => [id, { follow: 'main', custom: null }]))
  const row = { slots: { schema: 1, capable: true, declarations } }
  assert.equal(slotSupport(status([threeD]), row).available, true)
  const { [threeD.id]: _, ...builtinOnly } = declarations
  assert.equal(slotSupport(status([threeD]), { slots: { ...row.slots, declarations: builtinOnly } }).available, false)
  assert.equal(slotDraftError({ ...declarations, [threeD.id]: { follow: 'custom', custom: { provider: '', model: '', reasoning: '' } } }), '3D·그래픽: 모델을 선택하세요.')
  const draft = { ...declarations, [threeD.id]: { follow: 'custom', custom: { provider: 'p', model: 'blender', reasoning: 'high' } } }
  assert.deepEqual(editedSlotIds(draft, declarations), [threeD.id])
  const merged = mergePartialSlots({ [threeD.id]: draft[threeD.id], design: declarations.design }, { 'custom:zz': draft[threeD.id], advise: declarations.advise }, false)
  assert.deepEqual(Object.keys(merged), ['design', 'advise', threeD.id, 'custom:zz'])
  assert.equal(slotsCopyable({ [threeD.id]: { follow: 'delegation', custom: null } }), false)
  setCustomTaskSlots(status([]))
})

test('the definition form refuses what the service refuses', () => {
  const { customSlotDraftError, CUSTOM_SLOT_LIMIT } = api
  assert.equal(CUSTOM_SLOT_LIMIT, 4)
  assert.equal(customSlotDraftError([threeD, writing]), '')
  assert.equal(customSlotDraftError([]), '')
  const cases = [
    [[{ ...threeD, id: 'custom:' }], /ID/], [[{ ...threeD, id: 'custom:A1' }], /ID/], [[threeD, { ...writing, id: threeD.id }], /같은 ID/],
    [[threeD, { ...writing, label: threeD.label }], /같은 이름/], [[{ ...threeD, label: ' x' }], /이름/], [[{ ...threeD, label: '' }], /이름/],
    [[{ ...threeD, description: '' }], /설명/], [[{ ...threeD, description: 'x'.repeat(121) }], /설명/], [[{ ...threeD, description: 'a\u202eb' }], /설명/],
    [[{ ...threeD, tier: '' }], /시간 제한/], [[{ ...threeD, label: 'a\u0085b' }], /이름/], [[{ ...threeD, description: 'a\u200bb' }], /설명/],
    [[{ ...threeD, description: 'tag\u{E0041}' }], /설명/], [[{ ...threeD, label: 'del\u007f' }], /이름/],
    [[{ ...threeD, description: 'a\u2028b' }], /설명/], [[{ ...threeD, label: 'a\u2029b' }], /이름/], [[{ ...threeD, label: 'a\ud800b' }], /이름/],
    [[{ ...threeD, label: '\u{1F469}\u200d\u{1F4BB} 코딩' }], /이름/], [Array.from({ length: 5 }, (_, n) => ({ ...threeD, id: `custom:s-${n}`, label: `L${n}` })), /4개/]
  ]
  for (const [list, pattern] of cases) assert.match(customSlotDraftError(list), pattern)
})

test('the save summary names added, changed and removed slots and the cleared slot models', () => {
  const { customSlotChangeLines } = api
  const lines = customSlotChangeLines([threeD, writing], [{ ...threeD, label: '3D 작업' }, { id: 'custom:video', label: '영상 편집', description: 'FFmpeg 조립', tier: 'heavy' }],
    [{ profile: '*', field: 'custom_slots' }, { profile: 'p1', field: 'routing.slots', before: { [writing.id]: { follow: 'main', custom: null } }, after: null }])
  assert.deepEqual(lines, ['변경: 3D·그래픽 → 3D 작업 (custom:3d-graphics)', '추가: 영상 편집 (custom:video)', '삭제: 한국어 글쓰기 (custom:ko-writing)',
    'p1: 삭제하는 슬롯의 모델 설정도 지웁니다 (custom:ko-writing)'])
})

test('the status line names a custom slot by the label the roster reports', () => {
  const { executionIdentity, executionLabel } = api
  const requested = { kind: 'model', role: 'heavy', profile: null, slot: threeD.id, slot_label: threeD.label }
  assert.equal(executionLabel(requested), '모델 · 3D·그래픽')
  assert.equal(executionIdentity(requested).slot, threeD.id)
  // A bad label or id is not shown; the tier stands in.
  assert.equal(executionLabel({ ...requested, slot_label: 'x'.repeat(25) }), '모델 · Heavy')
  assert.equal(executionLabel({ ...requested, slot: 'custom-3d' }), '모델 · Heavy')
  assert.equal(executionLabel({ ...requested, slot_label: 'a\nb' }), '모델 · Heavy')
})

test('the section saves through its own preview and keeps spare models off custom cards', () => {
  assert.match(source, /'\/custom-slots-preview': 'custom-slots-preview'/)
  assert.match(source, /rest\('\/custom-slots-preview', \{ body: \{ expected_revision: status\.revision, custom_slots: plain\(draft\) \} \}\)/)
  assert.match(source, /const spare = spareReady && !slot\.custom \? nativeDraftSlotPolicy\(draft\)\[slot\.id\] : null/)
  assert.match(source, /children: taskSlots\(\)\.map\(slotCard\)/)
  // Spare-model policies stay built-in only: the service refuses any other key set.
  assert.match(source, /spareReady && TASK_SLOTS\.some\(slot => nativeDraftSlotPolicy\(draft\)\[slot\.id\]\.mode === 'custom'\)/)
})

test('lengths count code points like the service', () => {
  const { customSlotDraftError, customSlotDefinitions } = api
  const emoji = '🎬'.repeat(24)
  assert.equal(customSlotDraftError([{ ...threeD, label: emoji }]), '')
  assert.deepEqual(customSlotDefinitions(status([{ ...threeD, label: emoji }])).map(item => item.label), [emoji])
  assert.match(customSlotDraftError([{ ...threeD, label: emoji + '🎬' }]), /이름/)
  const longDescription = '🎬'.repeat(120)
  assert.equal(customSlotDraftError([{ ...threeD, description: longDescription }]), '')
  assert.equal(customSlotDefinitions(status([{ ...threeD, description: longDescription }])).length, 1)
  assert.match(customSlotDraftError([{ ...threeD, description: longDescription + '🎬' }]), /설명/)
  assert.equal(customSlotDefinitions(status([{ ...threeD, description: longDescription + '🎬' }])).length, 0)
  assert.equal(api.executionLabel({ kind: 'model', role: 'heavy', profile: null, slot: threeD.id, slot_label: emoji }), `모델 · ${emoji}`)
  assert.equal(customSlotDefinitions(status([{ ...threeD, label: 'a\u2028b' }])).length, 0)
})

test('review fixes: recovery save, unreadable lock, stale draft reset, run panel label', () => {
  assert.match(source, /disabled: disabled \|\| busy \|\| Boolean\(error\) \|\| \(blocking\.length > 0 && plain\(draft\)\.length > 0\)/)
  assert.match(source, /id: 'custom-slots-unreadable'/)
  assert.match(source, /const storedKey = JSON\.stringify\(\[status\?\.revision \?\? null, stored\]\)/)
  assert.match(source, /\{ \.\.\.row\.observed, slot: row\.requested\.slot, slot_label: row\.requested\.slot_label \} : row\.observed\) : row\.requested\r?\n  \/\/ The model the child's own API/)
})

test('the short status label names an observed custom slot child by its label', () => {
  const requested = { kind: 'model', role: 'heavy', profile: null, slot: threeD.id, slot_label: threeD.label, evidence: 'unknown' }
  const observed = { kind: 'model', role: 'heavy', profile: null, slot: null, evidence: 'runtime_reported' }
  assert.equal(api.executionShortLabel({ requested, observed }), threeD.label)
  assert.equal(api.executionShortLabel({ requested }), threeD.label)
  assert.equal(api.executionShortLabel({ requested: { ...requested, slot: 'design', slot_label: undefined }, observed }), '설계')
})
