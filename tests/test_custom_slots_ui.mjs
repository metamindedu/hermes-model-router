// Real React + jsdom: the real CustomSlotsSection and ExecutionRow from desktop/plugin.js (host controls
// inert). Needs HERMES_DESKTOP_SOURCE_ROOT (a Desktop source checkout for jsdom and React); skipped without.
import test from 'node:test'

if (process.env.HERMES_DESKTOP_SOURCE_ROOT) await import('./fixtures/custom_slots_ui_cases.mjs')
else test('custom slot section UI (needs HERMES_DESKTOP_SOURCE_ROOT)', { skip: 'HERMES_DESKTOP_SOURCE_ROOT is not set' }, () => {})
