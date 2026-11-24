// Real React + JSDOM: the composer strip gate uses the public SDK session seam (feature-detected),
// never host markup. Without the SDK hook it falls back to always showing the strip.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')

async function withHarness(t, { sdk, focused, focusedRuntime = 'ra', primaryRuntime = 'ra' }) {
  const require = createRequire(path.join(core, 'apps/desktop/package.json'))
  const { JSDOM } = require('jsdom')
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://fixture.invalid/' })
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const React = require('react'), { createRoot } = require('react-dom/client'), { jsx, jsxs } = require('react/jsx-runtime')
  const atom = value => ({ get: () => value, listen: () => () => {} })
  const state = { focusedStoredSessionId: atom(focused), focusedSessionId: atom(focusedRuntime), activeSessionId: atom(primaryRuntime) }
  const imports = {}
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(v => v.trim()).filter(Boolean)) imports[name] = () => null
  Object.assign(imports, { DesktopSDK: sdk, host: { state }, jsx, jsxs, useValue: a => React.useSyncExternalStore(a.listen, a.get, a.get),
    useState: React.useState, useRef: React.useRef, useEffect: React.useEffect })
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const api = new Function(...Object.keys(imports), code + '\nreturn { ComposerFocusGate };')(...Object.values(imports))
  const root = createRoot(document.getElementById('root'))
  const strip = mode => jsx('span', { 'data-strip': String(mode) })
  const shown = () => [...document.querySelectorAll('[data-strip]')].length
  const modes = () => [...document.querySelectorAll('[data-strip]')].map(node => node.getAttribute('data-strip'))
  try {
    await React.act(async () => root.render(jsx(api.ComposerFocusGate, { children: strip })))
    return { shown, modes, React, root }
  } catch (e) {
    await React.act(async () => root.unmount()); dom.window.close(); throw e
  }
}

test('without the SDK hook the gate falls back to always showing the strip', { skip: !core }, async t => {
  const { shown, React, root } = await withHarness(t, { sdk: {}, focused: 'A' })
  try { assert.equal(shown(), 1, 'no useComposerSession → always show (pre-gate behaviour)') }
  finally { await React.act(async () => root.unmount()) }
})

test('with the SDK hook the strip shows only for the focused composer session', { skip: !core }, async t => {
  const match = await withHarness(t, { sdk: { useComposerSession: () => ({ storedSessionId: 'A' }) }, focused: 'A' })
  try { assert.equal(match.shown(), 1, 'composer session matches focus → shown') }
  finally { await match.React.act(async () => match.root.unmount()) }
  const other = await withHarness(t, { sdk: { useComposerSession: () => ({ storedSessionId: 'A' }) }, focused: 'B' })
  try { assert.equal(other.shown(), 0, 'composer session differs from focus → hidden') }
  finally { await other.React.act(async () => other.root.unmount()) }
  const unknown = await withHarness(t, { sdk: { useComposerSession: () => null }, focused: 'A' })
  try { assert.equal(unknown.shown(), 0, 'unknown composer session → hidden (fail toward hiding)') }
  finally { await unknown.React.act(async () => unknown.root.unmount()) }
})

test('the SDK hook accepts a bare stored session id string as well as an object', { skip: !core }, async t => {
  const { shown, React, root } = await withHarness(t, { sdk: { useComposerSession: () => 'A' }, focused: 'A' })
  try { assert.equal(shown(), 1) }
  finally { await React.act(async () => root.unmount()) }
})

test('the primary composer reads its own session while a split tile holds focus', { skip: !core }, async t => {
  // Split: primary pane = P (runtime rp), focused tile = B (runtime rb).
  const primary = await withHarness(t, { sdk: { useComposerSession: () => ({ sessionId: 'rp', storedSessionId: 'P' }) },
    focused: 'B', focusedRuntime: 'rb', primaryRuntime: 'rp' })
  try { assert.deepEqual(primary.modes(), ['primary'], 'primary composer shows its own chat, not the focused tile') }
  finally { await primary.React.act(async () => primary.root.unmount()) }
  const tile = await withHarness(t, { sdk: { useComposerSession: () => ({ sessionId: 'rb', storedSessionId: 'B' }) },
    focused: 'B', focusedRuntime: 'rb', primaryRuntime: 'rp' })
  try { assert.deepEqual(tile.modes(), ['focused'], 'the focused tile keeps the focused scope') }
  finally { await tile.React.act(async () => tile.root.unmount()) }
  const otherTile = await withHarness(t, { sdk: { useComposerSession: () => ({ sessionId: 'rc', storedSessionId: 'C' }) },
    focused: 'B', focusedRuntime: 'rb', primaryRuntime: 'rp' })
  try { assert.equal(otherTile.shown(), 0, 'an unfocused tile has no owner proof → hidden') }
  finally { await otherTile.React.act(async () => otherTile.root.unmount()) }
})

test('the primary rule never applies while the primary itself is focused or the focused runtime is unknown', { skip: !core }, async t => {
  for (const [focusedRuntime, label] of [['rp', 'primary focused but stored ids differ'], [null, 'focused tile runtime not bound yet']]) {
    const h = await withHarness(t, { sdk: { useComposerSession: () => ({ sessionId: 'rp', storedSessionId: 'P' }) },
      focused: 'B', focusedRuntime, primaryRuntime: 'rp' })
    try { assert.equal(h.shown(), 0, label) }
    finally { await h.React.act(async () => h.root.unmount()) }
  }
  const bare = await withHarness(t, { sdk: { useComposerSession: () => 'rp' }, focused: 'B', focusedRuntime: 'rb', primaryRuntime: 'rp' })
  try { assert.equal(bare.shown(), 0, 'a bare string is a stored id, never a runtime id') }
  finally { await bare.React.act(async () => bare.root.unmount()) }
  const draft = await withHarness(t, { sdk: { useComposerSession: () => ({ sessionId: null, storedSessionId: null }) }, focused: 'B', focusedRuntime: 'rb', primaryRuntime: 'rp' })
  try { assert.equal(draft.shown(), 0, 'a draft composer has no session → hidden') }
  finally { await draft.React.act(async () => draft.root.unmount()) }
})

test('without the SDK hook the strip keeps the focused scope', { skip: !core }, async t => {
  const { modes, React, root } = await withHarness(t, { sdk: {}, focused: 'A' })
  try { assert.deepEqual(modes(), ['focused']) }
  finally { await React.act(async () => root.unmount()) }
})
