import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const start = source.indexOf('// Pure helpers are kept separate')
const end = source.indexOf('\nfunction Field(', start)
const { buildPreviewBody, primaryRouteForFallback, projectedRoutingFallbackErrors, buildCombinedPreviewBody } = new Function(source.slice(start, end).replace(/^export\s+/gm, '') + '\nreturn {buildPreviewBody, primaryRouteForFallback, projectedRoutingFallbackErrors, buildCombinedPreviewBody}')()
const route = model => ({ provider: 'fixture', model, reasoning: 'high' })
const row = name => ({ name, models: { main: route(name + '-main'), delegation: route(name + '-light') },
  actual_models: { main: route(name + '-drift'), delegation: route(name + '-drift-light') },
  routing: { enabled: true, heavy: { follow: 'main', custom: null }, light: { follow: 'delegation', custom: null }, fallback: { enabled: false, heavy: null, light: null } },
  fallbacks: { routing: { enabled: true, heavy: route(name + '-spare'), light: route(name + '-spare-light') } } })
const draftFor = r => ({ models: structuredClone(r.models), routing: { ...structuredClone(r.routing), heavy: { follow: 'custom', custom: route('other-spare') } } })

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

test('non-source primary collision is checked only when explicitly targeted', () => {
  const rows = [row('source'), row('other')], draft = draftFor(rows[0])
  const projection = buildPreviewBody(1, 'source', draft, [], ['source', 'other'], ['other'])
  assert.equal(primaryRouteForFallback(rows[1], 'heavy', projection).model, 'other-spare')
  assert.equal(primaryRouteForFallback(rows[0], 'heavy', projection).model, 'source-main')
  assert.match(projectedRoutingFallbackErrors(rows, projection).join(' '), /other/)
  assert.deepEqual(projectedRoutingFallbackErrors(rows, { ...projection, routing_targets: [] }), [])
})

test('follow projection uses each target canonical model, not source or external drift', () => {
  const r = row('other'), sourceRow = row('source')
  const body = buildPreviewBody(1, 'source', sourceRow, [], [], ['other'])
  assert.equal(primaryRouteForFallback(r, 'heavy', body).model, 'other-main')
  assert.equal(primaryRouteForFallback(r, 'heavy').model, 'other-main')
  body.model_targets = ['other']
  assert.equal(primaryRouteForFallback(r, 'heavy', body).model, 'source-main')
})

test('combined fallback validation receives non-source routing copy projection', () => {
  const rows = [row('source'), row('other')], draft = draftFor(rows[0])
  const fallback = { enabled: true, heavy: route('other-spare'), light: route('new-spare-light') }
  const before = { ...fallback, enabled: false }
  const result = buildCombinedPreviewBody(1, 'source', draft, [], ['source', 'other'],
    { routing: fallback }, { routing: before }, { routing: ['other'] }, rows, true, {}, ['other'])
  assert.match(result.errors.join(' '), /other/)
  const notCopied = buildCombinedPreviewBody(1, 'source', draft, [], ['source', 'other'],
    { routing: fallback }, { routing: before }, { routing: ['other'] }, rows, true, {}, [])
  assert.deepEqual(notCopied.errors, [])
})
