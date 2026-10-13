import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const loaded = source.replace(/^import[\s\S]*?from ['"][^'"]+['"];?\s*$/gm, '').replace(/^export /gm, '').replace('default {', 'const plugin = {')
const jsx = (type, props) => ({ type, props })
function fixture(sdk = {}) {
  const navigation = []
  let rpcCalls = 0
  const ui = new Function('ROUTES_AREA', 'SIDEBAR_NAV_AREA', 'PALETTE_AREA', 'jsx', 'host', 'DesktopSDK', `${loaded}\nreturn { plugin, nativeBackendCall }`)(
    'routes', 'sidebar.nav', 'palette', jsx,
    { state: { profile: { get: () => 'claire' } }, navigate: path => navigation.push(path), request: () => { rpcCalls++; throw new Error('unexpected RPC') } }, sdk
  )
  return { ...ui, navigation, rpcCalls: () => rpcCalls }
}

test('native settings replaces main sidebar, preserving RouterPage/context and performing no writes', () => {
  const ui = fixture({ pluginSettingsHref: id => `/settings?tab=plugins&plugin=${id}` })
  const items = []; const pages = []
  const ctx = { registerSettingsPage: page => pages.push(page), registerMany: rows => items.push(...rows) }
  ui.plugin.register(ctx)
  assert.equal(pages.length, 1)
  assert.equal(pages[0].id, 'settings')
  assert.equal(pages[0].title, '모델 및 라우팅')
  assert.equal(pages[0].icon, 'settings-gear')
  const render = pages[0].render()
  assert.equal(render.type.name, 'RouterPage')
  assert.equal(render.props.ctx, ctx)
  assert.deepEqual(items.map(row => row.id), ['page', 'open'])
  assert.deepEqual(items.map(row => row.area), ['routes', 'palette'])
  assert.equal(items[0].data.path, '/model-router')
  assert.equal(items[0].render().type, render.type)
  assert.equal(items[0].render().props.ctx, ctx)
  assert.equal(ui.rpcCalls(), 0)
  assert.doesNotMatch(source, /SIDEBAR_NAV_AREA|COMPOSER_AREAS|ComposerProgress|progressScopeAllowed|model-router-progress|focusedSessionId|process\.kill|process\.list|MutationObserver|ResizeObserver|setInterval/)
})

test('palette opens native plugin settings instead of legacy workspace route', () => {
  const ui = fixture({ pluginSettingsHref: id => `/settings?tab=plugins&plugin=${id}` })
  const items = []
  ui.plugin.register({ registerSettingsPage: () => {}, registerMany: rows => items.push(...rows) })
  items.find(row => row.id === 'open').data.run()
  assert.deepEqual(ui.navigation, ['/settings?tab=plugins&plugin=model-router'])
  assert.equal(ui.rpcCalls(), 0)
})

test('older SDK uses settings.plugins without restoring main sidebar', () => {
  const ui = fixture({ SETTINGS_PLUGINS_AREA: 'settings.plugins' })
  const items = []
  const ctx = { register: row => items.push(row), registerMany: rows => items.push(...rows) }
  ui.plugin.register(ctx)
  assert.deepEqual(items.map(row => row.area), ['settings.plugins', 'routes', 'palette'])
  assert.equal(items[0].title, '모델 및 라우팅')
  assert.equal(items[0].render().props.ctx, ctx)
  items.find(row => row.id === 'open').data.run()
  assert.deepEqual(ui.navigation, ['/settings?tab=plugins&plugin=model-router'])
  assert.equal(ui.rpcCalls(), 0)
})

test('minimal old context preserves compatibility route and palette with no new sidebar or writes', () => {
  const ui = fixture()
  const items = []
  ui.plugin.register({ registerMany: rows => items.push(...rows) })
  assert.deepEqual(items.map(row => row.area), ['routes', 'palette'])
  items[1].data.run()
  assert.deepEqual(ui.navigation, ['/settings?tab=plugins&plugin=model-router'])
  assert.equal(ui.rpcCalls(), 0)
})

test('discarded progress operation cannot start a CLI request', async () => {
  const ui = fixture()
  await assert.rejects(() => ui.nativeBackendCall('/progress'), /지원하지 않는/)
  assert.equal(ui.rpcCalls(), 0)
})
