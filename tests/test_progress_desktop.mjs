import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const pluginPath = fileURLToPath(new URL('../desktop/plugin.js', import.meta.url))
const source = await readFile(pluginPath, 'utf8')
const helperStart = source.indexOf('// Pure helpers are kept separate')
const helperEnd = source.indexOf('\nfunction Field(', helperStart)
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'pure helper block should remain identifiable')
const helperSource = source.slice(helperStart, helperEnd).replace(/^export\s+/gm, '')
const helpers = new Function(`
  const COMPOSER_SURFACE_SELECTOR = '[data-slot="composer-surface"]'
  const PROGRESS_FINISHED_RETENTION_MS = 8000
  ${helperSource}
  return { progressScopeAllowed, progressResponseMatchesScope, formatElapsed, reconcileProgressJobs }
`)()

const baseScope = () => ({
  activeSessionId: 'ui-runtime-1',
  focusedSessionId: 'ui-runtime-1',
  focusedStoredSessionId: 'durable-parent-1',
  connectionId: 'local',
  profile: 'claire',
  focusedSessionOwner: { connectionId: 'local', profile: 'claire' }
})

function fakeDocument() {
  const body = { nodeType: 1, style: {}, parentElement: null }
  const documentElement = { nodeType: 1, style: {}, parentElement: null }
  const doc = {
    body,
    documentElement,
    visibilityState: 'visible',
    surfaces: [],
    querySelectorAll(selector) {
      assert.equal(selector, '[data-slot="composer-surface"]')
      return this.surfaces
    },
    addEventListener() {},
    removeEventListener() {}
  }
  body.parentElement = documentElement
  doc.defaultView = {
    getComputedStyle(element) {
      return { display: 'block', visibility: 'visible', opacity: '1', ...(element.style || {}) }
    }
  }
  return doc
}

function fakeSurface(doc, { visible = true, connected = true } = {}) {
  const surface = {
    nodeType: 1,
    isConnected: connected,
    parentElement: doc.body,
    style: { display: visible ? 'block' : 'none', visibility: 'visible', opacity: '1' },
    getClientRects: () => visible ? [{}] : [],
    matches: selector => selector === '[data-slot="composer-surface"]',
    querySelector: () => null
  }
  doc.surfaces.push(surface)
  return surface
}

function fakeRoot(surface, { connected = true } = {}) {
  return { isConnected: connected, closest: selector => selector === '[data-slot="composer-surface"]' ? surface : null }
}

function job(overrides = {}) {
  return {
    job_id: 'job-1', process_id: 'process-1', title: 'Inspect routing scope', role: 'Light',
    model: 'gpt-6-luna', status: 'running', started_at: 1_000, finished_at: null,
    activity: 'Reading the route contract', ...overrides
  }
}

function progress(scope = baseScope(), jobs = [job()], overrides = {}) {
  return {
    schema: 1,
    profile: scope.profile,
    parent_session_id: scope.focusedStoredSessionId,
    ui_session_id: scope.activeSessionId,
    jobs,
    has_more: false,
    ...overrides
  }
}

function processSnapshot(jobs, state = 'running') {
  return { processes: jobs.map(item => ({ session_id: item.process_id, status: state, ...(state === 'exited' ? { exit_code: 0 } : {}) })) }
}

function* walk(node) {
  if (Array.isArray(node)) {
    for (const item of node) yield* walk(item)
    return
  }
  if (!node || typeof node !== 'object') return
  yield node
  yield* walk(node.props?.children)
}

function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(text).join(' ')
  return node?.props ? text(node.props.children) : ''
}

test('scope guard permits only the sole visible composer with matching primary session and owner', () => {
  const doc = fakeDocument()
  const visible = fakeSurface(doc)
  const root = fakeRoot(visible)
  assert.equal(helpers.progressScopeAllowed(baseScope(), root, doc), true)

  const hidden = fakeSurface(doc, { visible: false })
  assert.equal(helpers.progressScopeAllowed(baseScope(), root, doc), true, 'hidden composer surfaces are excluded')
  hidden.isConnected = false
  assert.equal(helpers.progressScopeAllowed(baseScope(), root, doc), true)

  fakeSurface(doc)
  assert.equal(helpers.progressScopeAllowed(baseScope(), root, doc), false, 'two visible composer surfaces suppress plugin polling')
  assert.equal(helpers.progressScopeAllowed(baseScope(), fakeRoot(visible, { connected: false }), doc), false)
})

test('scope guard fails closed for owner mismatch, tile focus, missing IDs, and disconnected surfaces', () => {
  const doc = fakeDocument()
  const surface = fakeSurface(doc)
  const root = fakeRoot(surface)
  assert.equal(helpers.progressScopeAllowed({ ...baseScope(), focusedSessionOwner: { connectionId: 'other', profile: 'claire' } }, root, doc), false)
  assert.equal(helpers.progressScopeAllowed({ ...baseScope(), focusedSessionOwner: { connectionId: 'local', profile: 'default' } }, root, doc), false)
  assert.equal(helpers.progressScopeAllowed({ ...baseScope(), focusedSessionId: 'focused-tile-runtime' }, root, doc), false)
  assert.equal(helpers.progressScopeAllowed({ ...baseScope(), focusedStoredSessionId: null }, root, doc), false)
  surface.isConnected = false
  assert.equal(helpers.progressScopeAllowed(baseScope(), root, doc), false)
})

test('progress response requires the exact profile, durable parent, UI session, schema, and bounded jobs', () => {
  const scope = { profile: 'claire', parentSessionId: 'durable-parent-1', uiSessionId: 'ui-runtime-1' }
  const row = job()
  const response = progress(baseScope(), [row])
  assert.equal(helpers.progressResponseMatchesScope(response, scope), true)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, parent_session_id: 'wrong-parent' }, scope), false)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, ui_session_id: 'wrong-ui' }, scope), false)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, profile: 'other' }, scope), false)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, schema: 2 }, scope), false)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, jobs: Array(17).fill(row) }, scope), false)
  assert.equal(helpers.progressResponseMatchesScope({ ...response, jobs: [{ ...row, finished_at: 'later' }] }, scope), false)
})

test('elapsed formatting is deterministic and terminal rows freeze at their first terminal observation', () => {
  assert.equal(helpers.formatElapsed(0, 61_999), '1:01')
  assert.equal(helpers.formatElapsed(0, 3_723_999), '1:02:03')
  assert.equal(helpers.formatElapsed(5_000, 1_000), '0:00')
  assert.equal(helpers.formatElapsed(Number.NaN, 1_000), '—')

  const scope = baseScope()
  const row = job({ finished_at: null, status: 'running' })
  const first = helpers.reconcileProgressJobs(progress(scope, [row]), processSnapshot([row], 'exited'), 10_000, new Map(), 'scope-a')
  assert.equal(first.jobs[0].displayState, 'unverified', 'exit zero without backend completion evidence stays unverified')
  assert.equal(first.jobs[0].terminalAt, 10_000)
  assert.equal(helpers.formatElapsed(row.started_at, first.jobs[0].terminalAt), '0:09')
  const next = helpers.reconcileProgressJobs(progress(scope, [row]), processSnapshot([row], 'exited'), 12_500, first.terminalTimes, 'scope-a')
  assert.equal(next.jobs[0].terminalAt, 10_000)
  assert.equal(next.jobs[0].displayState, 'unverified')
  const expired = helpers.reconcileProgressJobs(progress(scope, [row]), processSnapshot([row], 'exited'), 18_000, next.terminalTimes, 'scope-a')
  assert.deepEqual(expired.jobs, [])
  const remainsExpired = helpers.reconcileProgressJobs(progress(scope, [row]), processSnapshot([row], 'exited'), 21_000, expired.terminalTimes, 'scope-a')
  assert.deepEqual(remainsExpired.jobs, [], 'a retained native registry row cannot relatch and reappear')
})

test('native process registry alone decides visibility and terminal outcome by exact process ID', () => {
  const scope = baseScope()
  const rows = [
    job({ job_id: 'running', process_id: 'p-running' }),
    job({ job_id: 'done', process_id: 'p-done', status: 'completed', finished_at: null }),
    job({ job_id: 'failed', process_id: 'p-failed' }),
    job({ job_id: 'stopped', process_id: 'p-stopped' }),
    job({ job_id: 'missing', process_id: 'p-missing' }),
    job({ job_id: 'mismatch', process_id: 'p-right' })
  ]
  const response = progress(scope, rows)
  const snapshot = { processes: [
    { session_id: 'p-running', status: 'running' },
    { session_id: 'p-done', status: 'exited', exit_code: 0 },
    { session_id: 'p-failed', status: 'exited', exit_code: 2 },
    { session_id: 'p-stopped', status: 'killed', exit_code: 1 },
    { session_id: 'p-wrong', status: 'running' }
  ] }
  const result = helpers.reconcileProgressJobs(response, snapshot, 20_000, new Map(), 'scope')
  assert.deepEqual(result.jobs.map(item => [item.job_id, item.displayState]), [
    ['running', 'running'], ['done', 'completed'], ['failed', 'failed'], ['stopped', 'stopped']
  ])
  assert.equal(result.jobs.some(item => item.process_id === 'p-missing' || item.process_id === 'p-right'), false)
  assert.equal(JSON.stringify(result.jobs).includes('output_tail'), false)
})

function createHarness({ scope = baseScope(), surfaces = 1, optionalAtoms = true } = {}) {
  const doc = fakeDocument()
  const surface = fakeSurface(doc)
  for (let index = 1; index < surfaces; index++) fakeSurface(doc)
  const root = fakeRoot(surface)
  const values = { ...scope }
  const atoms = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, {
    value,
    get() { return this.value }
  }]))
  if (!optionalAtoms) {
    delete atoms.focusedStoredSessionId
    delete atoms.focusedSessionId
    delete atoms.focusedSessionOwner
    delete atoms.activeSessionId
  }
  const state = { ...atoms }
  let responseBuilder = (body, profileName) => progress({
    ...baseScope(), activeSessionId: body.ui_session_id, focusedStoredSessionId: body.parent_session_id,
    profile: profileName
  })
  let processBuilder = () => ({ processes: [] })
  const calls = []
  const host = {
    state,
    request: async (method, args) => {
      calls.push({ method, args: structuredClone(args) })
      if (method === 'cli.exec') {
        const operationIndex = args.argv.indexOf('model-router')
        const operation = args.argv[operationIndex + 1]
        const body = JSON.parse(args.argv.at(-1))
        const data = responseBuilder(body, args.profile, operation)
        return { blocked: false, code: 0, output: `MODEL_ROUTER_JSON:${JSON.stringify(data)}\n` }
      }
      if (method === 'process.list') return processBuilder(args)
      if (method === 'process.kill') return { status: 'killed' }
      throw new Error(`unexpected request ${method}`)
    }
  }

  let cursor = 0
  const hooks = []
  const effectDeps = []
  const cleanups = []
  let pendingEffects = []
  let dirty = false
  let tree = null
  let queryOptions = null
  const cache = new Map()
  const errors = new Map()
  const fetching = new Set()
  const intervals = []
  const clearedIntervals = []
  let fakeNow = 50_000
  const fakeDate = { now: () => fakeNow }
  const setIntervalFake = (callback, ms) => {
    const handle = { callback, ms }
    intervals.push(handle)
    return handle
  }
  const clearIntervalFake = handle => clearedIntervals.push(handle)

  const useState = initial => {
    const index = cursor++
    if (!(index in hooks)) hooks[index] = typeof initial === 'function' ? initial() : initial
    return [hooks[index], nextValue => {
      const next = typeof nextValue === 'function' ? nextValue(hooks[index]) : nextValue
      if (!Object.is(hooks[index], next)) { hooks[index] = next; dirty = true }
    }]
  }
  const useRef = initial => {
    const index = cursor++
    if (!(index in hooks)) hooks[index] = { current: initial }
    return hooks[index]
  }
  const useEffect = (callback, deps) => {
    const index = cursor++
    const previous = effectDeps[index]
    if (!previous || !deps || deps.some((item, at) => !Object.is(item, previous[at]))) {
      effectDeps[index] = deps
      pendingEffects.push({ index, callback })
    }
  }
  const keyOf = queryKey => JSON.stringify(queryKey)
  const useQuery = options => {
    queryOptions = options
    const key = keyOf(options.queryKey)
    return {
      data: cache.get(key),
      error: errors.get(key),
      isError: errors.has(key),
      isFetching: fetching.has(key),
      isPending: Boolean(options.enabled && !cache.has(key) && !errors.has(key)),
      refetch: async () => runQuery(options)
    }
  }
  const runQuery = async options => {
    const key = keyOf(options.queryKey)
    fetching.add(key)
    render()
    try {
      const data = await options.queryFn({ signal: new AbortController().signal })
      cache.set(key, data)
      errors.delete(key)
      return { data }
    } catch (error) {
      errors.set(key, error)
      return { error }
    } finally {
      fetching.delete(key)
      render()
    }
  }
  const jsx = (type, props = {}) => {
    if (typeof type === 'function') return type(props)
    if (props.ref && props['data-model-router-progress']) props.ref.current = root
    return { type, props }
  }
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
    for (const name of match[1].split(',').map(value => value.trim()).filter(Boolean)) imports[name] = name
  }
  Object.assign(imports, {
    COMPOSER_AREAS: { top: 'composer.top' },
    ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar', PALETTE_AREA: 'palette',
    host, useValue: atom => atom.get(), useState, useRef, useEffect, useQuery, jsx, jsxs: jsx
  })
  const executable = source
    .replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g, '')
    .replace(/export default /g, 'const pluginDefinition = ')
    .replace(/^export\s+/gm, '')
  const getPlugin = new Function('document', 'Date', 'setInterval', 'clearInterval', ...Object.keys(imports), `${executable}\nreturn pluginDefinition`)
  const pluginDefinition = getPlugin(doc, fakeDate, setIntervalFake, clearIntervalFake, ...Object.values(imports))
  const registrations = []
  pluginDefinition.register({ registerMany: entries => registrations.push(...entries) })
  const contribution = registrations.find(entry => entry.id === 'progress')
  assert.ok(contribution, 'composer progress contribution registered')
  assert.equal(contribution.area, 'composer.top')

  const render = () => {
    for (let pass = 0; pass < 20; pass++) {
      cursor = 0
      dirty = false
      pendingEffects = []
      tree = contribution.render()
      const effectsToRun = pendingEffects
      pendingEffects = []
      for (const effect of effectsToRun) {
        cleanups[effect.index]?.()
        cleanups[effect.index] = effect.callback()
      }
      if (!dirty) return tree
    }
    throw new Error('Hook render did not settle')
  }
  render()
  return {
    calls, doc, surface, atoms, intervals, clearedIntervals,
    get tree() { return tree },
    get queryOptions() { return queryOptions },
    render,
    text: () => text(tree),
    nodes: () => [...walk(tree)],
    setScope(next) {
      for (const [key, value] of Object.entries(next)) if (atoms[key]) atoms[key].value = value
      render()
    },
    setResponseBuilder(fn) { responseBuilder = fn },
    setProcessBuilder(fn) { processBuilder = fn },
    async fetch() {
      assert.ok(queryOptions?.enabled, 'query must be enabled for the current scope')
      return runQuery(queryOptions)
    },
    setNow(value) { fakeNow = value },
    async clickKill() {
      const button = this.nodes().find(node => node.type === 'Button' && node.props['aria-label'] === '위임 작업 중지')
      assert.ok(button, 'running row exposes session-scoped stop button')
      button.props.onClick()
      for (let index = 0; index < 12; index++) await Promise.resolve()
      render()
    }
  }
}

test('composer contribution polls exact progress body and same-session native process list; rows require registry matches', async () => {
  const h = createHarness()
  assert.equal(h.queryOptions.enabled, true)
  const rows = [job(), job({ job_id: 'job-2', process_id: 'process-2', title: 'Check UI contract', role: 'Heavy', model: 'gpt-6-astra', activity: 'Checking renderer scope' })]
  h.setResponseBuilder(body => progress(baseScope(), rows, { parent_session_id: body.parent_session_id, ui_session_id: body.ui_session_id }))
  h.setProcessBuilder(() => processSnapshot(rows))
  await h.fetch()
  assert.match(h.text(), /서브 에이전트 작업 2개/)
  assert.match(h.text(), /Inspect routing scope/)
  assert.match(h.text(), /Reading the route contract/)
  assert.match(h.text(), /Check UI contract/)
  assert.match(h.text(), /Checking renderer scope/)
  assert.equal(h.intervals.some(item => item.ms === 1_000), true)

  const progressCall = h.calls.find(call => call.method === 'cli.exec')
  const operationIndex = progressCall.args.argv.indexOf('model-router')
  assert.equal(progressCall.args.argv[operationIndex + 1], 'progress')
  assert.deepEqual(JSON.parse(progressCall.args.argv.at(-1)), {
    parent_session_id: 'durable-parent-1', ui_session_id: 'ui-runtime-1'
  })
  assert.deepEqual(h.calls.find(call => call.method === 'process.list').args, { session_id: 'ui-runtime-1' })
  assert.equal(h.queryOptions.refetchInterval({ state: { error: null } }), 3_000)
  assert.equal(h.queryOptions.retry, false)
})

test('terminal UI time freezes and the finished row clears on the first poll after eight seconds', async () => {
  const h = createHarness()
  const rows = [job()]
  h.setResponseBuilder(body => progress(baseScope(), rows, { parent_session_id: body.parent_session_id, ui_session_id: body.ui_session_id }))
  h.setProcessBuilder(() => processSnapshot(rows))
  await h.fetch()
  assert.equal(h.intervals.some(item => item.ms === 1_000), true)

  h.setProcessBuilder(() => ({ processes: [{ session_id: 'process-1', status: 'exited', exit_code: 0 }] }))
  rows[0] = { ...rows[0], status: 'completed', finished_at: null }
  await h.fetch()
  const elapsedText = () => h.nodes().filter(node => node.type === 'time').map(node => text(node))
  assert.deepEqual(elapsedText(), ['0:49'])
  assert.equal(h.clearedIntervals.some(item => item.ms === 1_000), true)
  h.setNow(54_000)
  h.render()
  assert.deepEqual(elapsedText(), ['0:49'], 'terminal elapsed display is frozen, not tied to wall-clock rerenders')

  h.setNow(58_000)
  await h.fetch()
  assert.doesNotMatch(h.text(), /서브 에이전트 작업/)
})

test('latest sanitized activity refreshes in place without changing row identity or background rail events', async () => {
  const h = createHarness()
  let latest = 'Opening source files'
  const rows = [job({ activity: latest })]
  h.setResponseBuilder(body => progress(baseScope(), rows, { parent_session_id: body.parent_session_id, ui_session_id: body.ui_session_id }))
  h.setProcessBuilder(() => processSnapshot(rows))
  await h.fetch()
  assert.match(h.text(), /Opening source files/)
  latest = 'Running focused assertions'
  rows[0] = { ...rows[0], activity: latest }
  await h.fetch()
  assert.match(h.text(), /Running focused assertions/)
  assert.doesNotMatch(source, /delegate_start|subagent\.started|host\.onEvent\(/)
})

test('split view, focused tile, missing SDK atoms, and owner/source switches suppress polling and stale rows', async () => {
  const multiple = createHarness({ surfaces: 2 })
  assert.equal(multiple.queryOptions.enabled, false)
  assert.equal(multiple.calls.length, 0)

  const tile = createHarness({ scope: { ...baseScope(), focusedSessionId: 'tile-runtime' } })
  assert.equal(tile.queryOptions.enabled, false)
  assert.equal(tile.calls.length, 0)

  const oldSdk = createHarness({ optionalAtoms: false })
  assert.equal(oldSdk.queryOptions.enabled, false)
  assert.equal(oldSdk.calls.length, 0)
  assert.doesNotThrow(() => oldSdk.render())

  const switched = createHarness()
  const oldRow = job()
  switched.setResponseBuilder(body => progress(baseScope(), [oldRow], { parent_session_id: body.parent_session_id, ui_session_id: body.ui_session_id }))
  switched.setProcessBuilder(() => processSnapshot([oldRow]))
  await switched.fetch()
  assert.match(switched.text(), /Inspect routing scope/)
  switched.setScope({ connectionId: 'source-b', profile: 'worker', focusedSessionOwner: { connectionId: 'source-b', profile: 'worker' } })
  assert.equal(switched.queryOptions.enabled, true)
  assert.doesNotMatch(switched.text(), /Inspect routing scope/)
  assert.equal(switched.queryOptions.refetchInterval({ state: { error: new Error('temporary') } }), 15_000)
})

test('late progress response and response ID mismatch never render rows in the current scope', async () => {
  const h = createHarness()
  let finish
  let finishProcesses
  h.setResponseBuilder(() => new Promise(resolve => { finish = resolve }))
  h.setProcessBuilder(() => new Promise(resolve => { finishProcesses = resolve }))
  const pending = h.fetch()
  h.setScope({ connectionId: 'source-new', profile: 'worker', focusedSessionOwner: { connectionId: 'source-new', profile: 'worker' } })
  finish(progress(baseScope(), [job()]))
  finishProcesses(processSnapshot([job()]))
  await pending
  assert.doesNotMatch(h.text(), /Inspect routing scope/)

  const mismatched = createHarness()
  mismatched.setResponseBuilder(body => progress(baseScope(), [job()], { parent_session_id: `${body.parent_session_id}-wrong` }))
  mismatched.setProcessBuilder(() => processSnapshot([job()]))
  await mismatched.fetch()
  assert.doesNotMatch(mismatched.text(), /Inspect routing scope/)
  assert.match(mismatched.text(), /진행 상황을 확인할 수 없습니다/)
})

test('native kill is available only for a known running process and uses the exact scoped process.kill contract', async () => {
  const h = createHarness()
  const rows = [job()]
  h.setResponseBuilder(body => progress(baseScope(), rows, { parent_session_id: body.parent_session_id, ui_session_id: body.ui_session_id }))
  h.setProcessBuilder(() => processSnapshot(rows))
  await h.fetch()
  await h.clickKill()
  const kill = h.calls.find(call => call.method === 'process.kill')
  assert.deepEqual(kill.args, { session_id: 'ui-runtime-1', process_id: 'process-1' })
  assert.equal(h.calls.some(call => call.method === 'process.stop'), false)
})

test('progress CLI uses explicit profile and exact framed operation', async () => {
  const start = source.indexOf('export async function nativeBackendCall')
  const end = source.indexOf('\nconst NULL_HOST_ATOM', start)
  assert.ok(start >= 0 && end > start)
  const functionSource = source.slice(start, end).replace('export ', '')
  let request
  const host = {
    state: { profile: { get: () => 'default' } },
    request: async (method, args) => {
      request = { method, args }
      return { blocked: false, code: 0, output: 'MODEL_ROUTER_JSON:{"schema":1}\n' }
    }
  }
  const call = new Function('host', `${functionSource}; return nativeBackendCall`)(host)
  const body = { parent_session_id: 'durable-parent-1', ui_session_id: 'ui-runtime-1' }
  assert.deepEqual(await call('/progress', { profile: 'default', body }), { schema: 1 })
  assert.equal(request.method, 'cli.exec')
  assert.deepEqual(request.args.argv, ['--profile', 'default', 'model-router', 'progress', '--body', JSON.stringify(body)])
  assert.equal(request.args.profile, 'default')
  await assert.rejects(() => call('/unapproved'))
})
