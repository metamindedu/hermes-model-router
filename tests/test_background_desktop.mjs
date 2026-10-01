import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const loaded = source.replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '').replace(/^export /gm, '').replace('default {', 'const plugin = {')
const jsx = (type, props) => ({ type, props })
const ui = new Function('ROUTES_AREA', 'SIDEBAR_NAV_AREA', 'PALETTE_AREA', 'jsx', 'host', `${loaded}\nreturn { plugin, nativeBackendCall }`)(
  'routes', 'sidebar.nav', 'palette', jsx,
  { state: { profile: { get: () => 'claire' } }, request: () => { throw new Error('unexpected RPC') } }
)

test('only settings contributions remain; no replacement composer or task panel', () => {
  const items = []
  ui.plugin.register({ registerMany: rows => items.push(...rows) })
  assert.deepEqual(items.map(row => row.id), ['page', 'sidebar', 'open'])
  assert.deepEqual(items.map(row => row.area), ['routes', 'sidebar.nav', 'palette'])
  assert.equal(items[0].render().type.name, 'RouterPage')
  assert.doesNotMatch(source, /COMPOSER_AREAS|ComposerProgress|progressScopeAllowed|model-router-progress|focusedSessionId|process\.kill|process\.list|MutationObserver|ResizeObserver|setInterval/)
})

test('discarded progress operation cannot start a CLI request', async () => {
  await assert.rejects(() => ui.nativeBackendCall('/progress'), /지원하지 않는/)
})
