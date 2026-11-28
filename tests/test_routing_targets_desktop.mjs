import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const start = source.indexOf('// Pure helpers are kept separate')
const end = source.indexOf('\nfunction Field(', start)
const { buildPreviewBody, buildCombinedPreviewBody } = new Function(source.slice(start, end).replace(/^export\s+/gm, '') + '\nreturn {buildPreviewBody, buildCombinedPreviewBody}')()
const route = model => ({ provider: 'fixture', model, reasoning: 'high' })
// v0.18.0 routing: {enabled, slots}, the slots holding only stored declarations.
const row = name => ({ name, models: { main: route(name + '-main'), delegation: route(name + '-delegate') },
  actual_models: { main: route(name + '-drift'), delegation: route(name + '-drift-delegate') },
  routing: { enabled: true, slots: { design: { follow: 'custom', custom: route(name + '-designer') } } },
  fallbacks: { native: { managed: true, editable: true, enabled: false, chain: [], actual_chain: [], drift: false, warnings: [], consent: null } } })
const draftFor = r => ({ models: structuredClone(r.models), routing: { ...structuredClone(r.routing), slots: { ...structuredClone(r.routing.slots), 'code-simple': { follow: 'custom', custom: route('other-coder') } } } })

test('preview encodes exact routing targets including empty, while absent retains old contract', () => {
  const r = row('source'), draft = draftFor(r)
  assert.equal('routing_targets' in buildPreviewBody(1, r.name, draft, [], []), false)
  for (const targets of [[], ['other']]) {
    const body = buildPreviewBody(1, r.name, draft, [], [], targets)
    assert.deepEqual(body.routing_targets, targets)
    body.routing_targets.push('mutation')
    assert.equal(targets.includes('mutation'), false)
  }
})

test('the routing a preview sends is {enabled, slots}: the full slot map, or only the named slots of a partial save', () => {
  const r = row('source'), draft = draftFor(r)
  const full = buildPreviewBody(1, 'source', draft, [], ['source'], ['other'])
  assert.deepEqual(full.routing, { enabled: true, slots: draft.routing.slots })
  assert.deepEqual(buildPreviewBody(1, 'source', draft, [], [], ['other']).routing.enabled, false, 'membership decides enabled')
  const partial = buildPreviewBody(1, 'source', { ...draft, routing: { enabled: true, slots: { 'code-simple': draft.routing.slots['code-simple'] } } }, [], ['source'], ['other'], null, true)
  assert.equal(partial.partial_save_schema, 1)
  assert.deepEqual(partial.routing, { enabled: true, slots: { 'code-simple': { follow: 'custom', custom: route('other-coder') } } })
  assert.deepEqual(buildPreviewBody(1, 'source', { ...draft, routing: { enabled: true, slots: {} } }, [], ['source'], [], null, true).routing, { enabled: true },
    'a partial save that writes no slot leaves the key out')
  const noSlots = buildPreviewBody(1, 'source', { ...draft, routing: { enabled: true } }, [], ['source'], [])
  assert.deepEqual(noSlots.routing, { enabled: true, slots: {} }, 'the full form always names the slot map')
})

test('a combined body carries the routing targets and no spare-model update without a spare-model edit', () => {
  const rows = [row('source'), row('other')], draft = draftFor(rows[0])
  for (const routingTargets of [['other'], []]) {
    const result = buildCombinedPreviewBody(1, 'source', draft, [], ['source', 'other'],
      { native: null }, { native: null }, {}, rows, true, {}, routingTargets)
    assert.deepEqual(result.errors, [])
    assert.deepEqual(result.body.routing_targets, routingTargets)
    assert.deepEqual(Object.keys(result.body.routing).sort(), ['enabled', 'slots'])
    assert.equal('fallback_updates' in result.body, false)
    assert.equal('fallback_confirmations' in result.body, false)
  }
})
