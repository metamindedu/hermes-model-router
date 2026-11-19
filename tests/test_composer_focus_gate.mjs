// Real React + JSDOM: the composer strip gate uses the public SDK session seam (feature-detected),
// never host markup. Without the SDK hook it falls back to always showing the strip.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')

async function withHarness(t, { sdk, focused }) {
  const require = createRequire(path.join(core, 'apps/desktop/package.json'))
  const { JSDOM } = require('jsdom')
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://fixture.invalid/' })
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const React = require('react'), { createRoot } = require('react-dom/client'), { jsx, jsxs } = require('react/jsx-runtime')
  const atom = value => ({ get: () => value, listen: () => () => {} })
  const state = { focusedStoredSessionId: atom(focused), focusedSessionId: atom('ra'), activeSessionId: atom('ra') }
  const imports = {}
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(v => v.trim()).filter(Boolean)) imports[name] = () => null
  Object.assign(imports, { DesktopSDK: sdk, host: { state }, jsx, jsxs, useValue: a => React.useSyncExternalStore(a.listen, a.get, a.get),
    useState: React.useState, useRef: React.useRef, useEffect: React.useEffect })
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const api = new Function(...Object.keys(imports), code + '\nreturn { ComposerFocusGate };')(...Object.values(imports))
  const root = createRoot(document.getElementById('root'))
  const strip = () => jsx('span', { 'data-strip': '1' })
  const shown = () => [...document.querySelectorAll('[data-strip]')].length
  try {
    await React.act(async () => root.render(jsx(api.ComposerFocusGate, { children: strip })))
    return { shown, React, root }
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