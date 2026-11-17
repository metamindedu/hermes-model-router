// Real React + JSDOM: the split-chat gate re-checks when another chat surface mounts, with no id change.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core = process.env.HERMES_DESKTOP_SOURCE_ROOT
const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')

test('primary strip hides when a tile holding the same chat mounts later, without any id change', { skip: !core }, async () => {
  const require = createRequire(path.join(core, 'apps/desktop/package.json'))
  const { JSDOM } = require('jsdom')
  const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://fixture.invalid/' })
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const React = require('react'), { createRoot } = require('react-dom/client'), { jsx, jsxs } = require('react/jsx-runtime')
  const atom = value => ({ get: () => value, listen: () => () => {} })
  const state = { focusedStoredSessionId: atom('A'), focusedSessionId: atom('ra'), activeSessionId: atom('ra') }
  const imports = {}
  for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of m[1].split(',').map(v => v.trim()).filter(Boolean)) imports[name] = () => null
  Object.assign(imports, { DesktopSDK: {}, host: { state }, jsx, jsxs, useValue: a => React.useSyncExternalStore(a.listen, a.get, a.get),
    useState: React.useState, useRef: React.useRef, useEffect: React.useEffect })
  const code = source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m, '')
    .replace(/export default /g, 'const pluginDefinition = ').replace(/^export\s+/gm, '')
  const api = new Function(...Object.keys(imports), code + '\nreturn { ComposerFocusGate };')(...Object.values(imports))
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
  const strip = label => () => jsx('span', { 'data-strip': label })
  const surface = (target, label) => jsx('div', { 'data-chat-surface': '', 'data-composer-target': target, children: jsx(api.ComposerFocusGate, { children: strip(label) }) }, target)
  const root = createRoot(document.getElementById('root'))
  const shown = () => [...document.querySelectorAll('[data-strip]')].map(el => el.getAttribute('data-strip')).sort()
  try {
    await React.act(async () => root.render(jsxs(React.Fragment, { children: [surface('main', 'primary')] })))
    await React.act(async () => { await sleep(10) })
    assert.deepEqual(shown(), ['primary'])
    await React.act(async () => root.render(jsxs(React.Fragment, { children: [surface('main', 'primary'), surface('tile:A', 'tile')] })))
    await React.act(async () => { await sleep(10) })
    assert.deepEqual(shown(), ['tile'], 'the later-mounted tile takes the strip; the primary hides with no id change')
    await React.act(async () => root.render(jsxs(React.Fragment, { children: [surface('main', 'primary')] })))
    await React.act(async () => { await sleep(10) })
    assert.deepEqual(shown(), ['primary'], 'the primary shows again when the tile unmounts')
  } finally {
    await React.act(async () => root.unmount())
    dom.window.close()
  }
})
