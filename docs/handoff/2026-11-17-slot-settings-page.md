# Handoff: settings page for task slots (stage 2)

Read `AGENTS.md` and the `2026-11-17: Task slots replace the Heavy/Light pair` section of `PLAN.md` first. This file is the implementation baseline; a material deviation goes back to the parent instead of being decided locally.

## Deliverable

`desktop/plugin.js` shows one `모델` section in which the operator sets, per task slot, the primary model and the spare models, and saves with one button. The Python backend for this already exists and is frozen (contract below).

## Ownership

You own: `desktop/plugin.js`, `tests/*.mjs`, `scripts/fixtures/fixture-model-picker-entry.jsx`.
Do not touch: any `*.py`, `PLAN.md`, `README.md`, `docs/wiki/*`, `skills/`, `compat/`, `plugin.yaml`, `scripts/*.py`, `scripts/render_model_picker_fixture.mjs`. Another worker edits Python and docs in this tree at the same time.

No commit, push, install, plugin replacement, `hermes` CLI call that writes, live profile/config write, or restart. Tests use synthetic hosts and invented data only. Keep each file's existing line endings (`desktop/plugin.js` and the `.mjs` tests are CRLF).

## Backend contract (frozen)

Status (`/status`):

- `status.slot_capabilities = { schema: 1, slots: [...six ids in display order], tiers: {slot: 'heavy'|'light'}, purposes: {purpose: slot}, follows: ['main','delegation','custom'], blocking_profiles: [profile names] }`. Absent on an older backend.
- `row.slots = { schema: 1, capable: bool, stored: [slot ids], declarations: { <slot>: { follow: 'main'|'delegation'|'custom', custom: {provider, model, reasoning} | null } } }`. `declarations` always has all six slots (a never-saved slot is shown as what it currently resolves through).
- `row.native_delegation` adds `slot_policy` and `auto_slot_policy` (`{ <slot>: { mode: 'off'|'custom', chain: [{provider, model}] } }`, all six slots), `policy_schema` and `auto_policy_schema` (`0` nothing stored, `1` two roles, `2` per slot), `slot_policy_supported: bool`. The old `policy` / `auto_policy` (heavy/light) stay.
- `row.routing` may carry `slots` (stored declarations only); `heavy` / `light` / `enabled` / `fallback` are unchanged.

Slot ids, in order: `design`, `code-complex`, `code-simple`, `verify-simple`, `verify-complex`, `computer-use`. Tiers: `design` and `verify-complex` are `heavy`, the rest `light`. Tier now only decides which of the two routed runtime limits applies.

Store save (`/preview`, then `/apply`): `body.routing.slots` is an optional mapping of the same declaration shape. Key omitted: stored slots are left alone. `{}`: stored slots are cleared. `follow: 'custom'` requires a full route; any other follow requires `custom: null`. `routing.heavy` / `routing.light` / `routing.enabled` / `routing.fallback` must still be sent (send them back as loaded). `routing_targets` copies the slot declarations to the selected profiles exactly as Heavy/Light were copied. While `blocking_profiles` is non-empty a body with non-empty `slots` is refused with `task slots need every installed profile on this plugin version first`.

Native save (`/delegation-preview`, then `/apply`): each update carries exactly one of `policy` (two roles) or `slot_policy` (all six slots, no consent fields). `slot_policy` is refused when that profile's `slot_policy_supported` is not true. `policy` is refused when the stored block for the backend being saved has schema `2`. `allow_additional_cost` must be true when any entry is `custom`.

## Page design

Replace the three sections `모델 대상`, `작업 분담과 예비 모델` and `Heavy / Light 기본 모델` with one section titled `모델`, in this order:

1. `대화 모델`: the four existing role cards with their existing ids and fields.
2. `작업 모델`:
   - The delegation-method Select, id `native-delegation-backend`, same options and labels.
   - Keep one sentence containing `간단한 작업은 메인 모델이 직접 처리` (small work stays with Main; delegation is for work worth splitting).
   - Model modes (`model-router`, `model-router-auto`): six slot cards. Each card has
     - title and one-line description (table below) and a muted badge naming the runtime-limit group (`긴 작업 제한` for heavy tier, `짧은 작업 제한` for light tier);
     - basis Select id `slot-<slot>-follow`: `기본 대화 모델과 같게` (`main`), `작업 위임 모델과 같게` (`delegation`), `직접 지정` (`custom`). For `main` / `delegation` show the model it currently resolves to as read-only text (id `slot-<slot>-resolved`). For `custom` render the existing `ModelRouteField` with ids `slot-<slot>-picker`, `-provider`, `-model`, `-reasoning` and `withReasoning: true`. Switching to `custom` pre-fills from the model it was following; switching away sets `custom: null`;
     - spare models: Select id `slot-<slot>-fallback-mode` (`다른 모델로 전환하지 않음` / `예비 모델로 이어가기`), chain entries through `ModelRouteField` without reasoning (ids `slot-<slot>-spare-picker-<i>`, `-spare-provider-<i>`, `-spare-model-<i>`), add button id `slot-<slot>-fallback-add` (max five), a delete button per entry. Position-based React keys only.
   - Profile modes (`model-router-profiles`, `model-router-auto`): the existing allowed-profile list, role-description controls, default-profile Select and the access-consent CheckRow, behaviour unchanged.
   - `default` mode: no slot cards; one note that delegated work uses the `작업 위임` model above.
3. One `적용 대상` fieldset (id `model-section-targets`): buttons `model-target-source` / `model-target-all` / `model-target-none` and a CheckRow per profile `model-target-<name>`. Default selection is the loaded profile only. A profile that cannot take the native part shows the existing `nativeDelegationTargetReason` text as its detail.
4. A short `저장할 내용` summary (targets, method, how many slots use a model of their own, how many have spare models), a cost notice when any slot has spare models, any error, and one button id `model-section-save`.

Slot copy:

| slot | title | description |
|---|---|---|
| `design` | 설계 | 계획을 세우고 구조를 정하는 작업 |
| `code-complex` | 코드 · 복잡 | 여러 파일에 걸친 구현과 까다로운 수정 |
| `code-simple` | 코드 · 간단 | 정해진 패턴의 수정과 테스트·빌드 같은 반복 작업 |
| `verify-simple` | 검증 · 간단 | 예비 검토와 가벼운 확인 |
| `verify-complex` | 검증 · 복잡 | 최종 의미 검토와 독립 검수 |
| `computer-use` | 컴퓨터 유즈 | 브라우저나 데스크톱 화면을 직접 조작하는 작업 |

When `verify-complex` resolves to the same provider and model as `code-complex`, show a note under the `verify-complex` card that a review on the same model is not a review by a different model. It is advice, never a save blocker.

Removed from the page: the routing on/off CheckRow (`routing-enabled`), the per-profile routing membership list, the Heavy/Light `대상 기준` editors, the separate routing target list and `routing-save`, the native card's own target list, summary and `native-delegation-save`, `models-save`. `routing_profiles` is sent back as loaded. Only when some loaded profile has `routing.enabled === false` show a notice in `작업 모델` listing those profiles with one CheckRow each (`routing-reenable-<name>`) and its own button `routing-reenable-save` (`선택한 프로필의 작업 분담 다시 켜기`). Re-enabling is a separate, small store transaction and is never part of `model-section-save`: it runs the existing scoped save (`/preview` with `save_scope: 'routing'`, then `/apply`) with `routing` as loaded except `enabled` matching the new membership for the loaded profile, `routing_profiles` = the loaded membership plus the checked profiles, `routing_targets: []` and no `slots` key, so nothing but membership changes. The button is disabled while nothing is checked. `model-section-save` always sends `routing_profiles` as loaded; a profile that is still off keeps showing the existing `nativeDelegationTargetReason` text and blocks a model-mode native save for that target exactly as today (the operator re-enables first, reloads, then saves the rest). The words Heavy and Light no longer appear in this section. In the runtime-limit section relabel the two routed limits as `설계 · 검증(복잡) 슬롯` and `코드 · 검증(간단) · 컴퓨터 유즈 슬롯`; ids and behaviour unchanged. The legacy fallback section and the combined-save section stay; change the combined section's sentence about the separate card to say that the delegation method and slot spare models are saved by the `모델` section's button.

Capability states:

- `slot_capabilities` missing, or the loaded profile's `row.slots.capable !== true` or its `native_delegation.slot_policy_supported !== true` (call this "the loaded profile has no slot support"): no slot cards; a note that this profile's plugin must be updated before slot models can be set. The method Select and profile routes keep working. Nothing slot-shaped was edited, so in this state every target's native update, in every mode, sends that target's own stored policy shape untouched (the "other modes" rule below) and the "target not supported" error does not apply.
- `blocking_profiles` non-empty: slot primary-model controls are read-only with a note naming the profiles that must be updated first; `routing.slots` is omitted from the store body. Spare models stay editable.

## Drafts and bodies

- Store draft: `draft.slots` = deep copy of `row.slots.declarations` (keep `draft.routing` as loaded). The store body's `routing` is the loaded routing plus `slots: draft.slots` (all six) when slot editing is available, otherwise without the key. Never change `routing.heavy` / `routing.light`.
- The combined-save section builds its body from the same draft, so it must carry the same `routing.slots` (or omit the key under the same conditions) and use the section's target list for `model_targets` and `routing_targets`.
- Native draft: add `slotPolicy` and `autoSlotPolicy` from the DTO; the active one is chosen by backend exactly as `nativeDraftPolicy` does today. Keep `policy` / `autoPolicy` as loaded and never edit them.
- Native update per target, extending `buildNativeDelegationBatchBody`:
  - the loaded profile has no slot support (see Capability states): the "other modes" rule for every target, regardless of mode. This takes precedence over the next two rules;
  - model mode, target `slot_policy_supported`: `slot_policy` = the draft's active slot policy;
  - model mode, loaded profile has slot support but the target does not: throw `<name>: 이 프로필의 플러그인은 슬롯별 예비 모델을 지원하지 않습니다. 먼저 업데이트하세요.`;
  - other modes: keep the stored shape untouched: `slot_policy: baseline.slot_policy` when the baseline's schema for the key being written is `2`, otherwise `policy: baseline.policy` (the key written is the auto one only for `model-router-auto`, as today);
  - `allow_additional_cost` = some entry of the policy being sent is `custom`.
- Validation mirrors the existing spare-chain rules per slot (provider/model patterns, 1 to 5 entries in `custom`, none in `off`, no duplicate route within a slot).

## One button, two transactions

The store save and the native save stay the two existing transactions. `model-section-save` runs them in this fixed order inside one save lock:

1. Decide what is needed. Native step: the native draft differs from the loaded profile's baseline, or the target list was edited by hand. Store step: models or slots differ from the baseline, or the target list was edited by hand. Re-enable boxes never affect this chain. If neither, run the store step alone (it reports no change).
2. Native preview (`/delegation-preview`) when needed. Failure: nothing saved, show the error, stop.
3. Store preview (`/preview`, no `save_scope`, timeouts and legacy fallback untouched, `model_targets` and `routing_targets` both the section's target list) when needed, for validation. Failure: nothing saved, show the error, stop.
4. Native apply with the existing fence and fresh-status check. A partial or unknown receipt is handled exactly as today and ends the chain.
5. Store preview again (the native apply does not move the store revision, but a plan made before it must not be reused) and store apply.
6. Record one outcome. If step 4 applied and step 5 failed or is unknown, report it as partial in plain words: the delegation method and spare models were saved, the model changes were not, and the status must be reloaded. Never retry automatically and never start step 5 after a partial or unknown native receipt.

Reuse `runSave`'s guards (generation token, scope checks, `isSaveCurrent`, fence, reload requirement). Add the chain as a small extension rather than a second copy of that function.

## Acceptance

- `node --check desktop/plugin.js` and `node --test tests/*.mjs` pass. Tests that covered removed controls are rewritten for the new controls, not deleted, when the behaviour still exists (target selection, stale-revision locks, native fence, role proposals, model picker, timeouts, legacy fallback, combined save).
- New Node tests cover: slot draft seeding; basis switching (pre-fill and `custom: null`); the store body carrying all six slots and unchanged `heavy` / `light`; omission of `slots` while blocked; per-target native body shape for every mode and support combination above; chain order for the four cases (store only, native only, both, neither); stop-before-apply on either preview failure; partial outcome wording; no second apply after a partial native receipt; default target is the loaded profile only; re-enable notice only when a profile is off, its separate save body (membership only, `routing_targets: []`, no `slots`), and `model-section-save` never changing `routing_profiles`; the no-slot-support state sending each target's stored policy shape in a model mode.
- `scripts/fixtures/fixture-model-picker-entry.jsx` returns the new status fields with invented data (three profiles, one slot `custom`, one slot with a spare model, one profile with routing off) so the page renders in the isolated renderer. Do not run a browser; the parent does the visual pass.
- Report: files changed, test totals from the real run, anything not done, and every place you deviated from this file.

## Non-goals

Operator-added slots, any backend change, per-slot runtime limits, removing the legacy fallback or combined-save sections, release or install work, README/wiki text.

## Implementation record (parent, 2026-11-17)

Decided by the parent while implementing; where this section and the text above disagree, this section is what the source does.

- **Store step scope.** `model-section-save` sends `save_scope: 'models'` when only role models are written, `save_scope: 'routing'` when only slot declarations are, and no `save_scope` only when both are. The narrower scope keeps an untouched part out of the plan. Timeouts and the legacy fallback are never included.
- **Nothing to save.** When no draft differs and there is no fresh copy intent, `model-section-save` is disabled and its handler returns; the store step is not run "to report no change". Reason: that request still carried `model_targets`, so a list that merely persisted would have received the loaded profile's role models under a no-change summary.
- **Role models follow the same intent rule as the rest.** `model_targets` is the target list only when the role-model draft changed or the list was picked by hand since the last load; otherwise `[]`. The whole-page save (`global-save`) uses the same rule and the same list.
- **Slot models are copied on fresh intent only while their cards are shown** (a model mode). In `default` and profile modes a hand-picked list copies role models and the delegation method, not hidden slot declarations; an actual slot edit is still saved.
- **Membership.** Only `routing-reenable-save` changes `routing_profiles`. `global-save` sends loaded membership even with a re-enable box ticked.
- **Zero targets with an edit** is an error on both save buttons, not a successful no-op.
- **Chain stop.** When the native apply ends partial, unknown or thrown, the outcome also says the model step was not started and that a reload discards unsaved edits. Outcome text names each half in quotes with its result; a `no_change` first receipt is reported as no change, not as saved.
- **Profile modes** list the allow-list and default profile under `저장할 내용`, because a hand-picked save writes them to every target.
- **Request size.** A body over 16,384 characters is refused by the page before sending, with the instruction to split targets (the backend's own limit; the per-slot spare policy makes it reachable with many targets).
- **First slot save.** While no profile has stored slots or a per-slot spare block, the slot section shows a reminder to restart every Hermes process running the previous plugin version first (`slot-first-save-note`).
- **Targets that cannot take the native step are skipped in the open, not refused.** With one target list, refusing the whole save would also keep role and slot models from a profile that can take them. A selected profile with routing off, a non-editable delegation block, or (in a model mode) no `slot_policy_supported` is left out of the native updates, named under `저장할 내용` (`model-section-skipped`) and on its own row, and still gets the store step. The loaded profile itself must be able to take the native step; otherwise the save is blocked with its reason.
- **Copy intent.** A hand-picked target list makes both steps run for the current values; that intent ends with a reload or a profile change, while the selection itself persists. Without it, a step runs only when its own draft differs from the loaded baseline.
- **Cost.** Spare models show a cost notice (`slot-spare-cost-note`); `allow_additional_cost` is derived from the policy sent. There is no cost checkbox.
- **Same-turn edits.** `updateNativeDelegationDraft` and `updateFallbackDraft` accept further edits in the turn that moved the generation (a catalog choice writes provider, then model) and reject callbacks kept past that turn.
- **Runtime-limit wording.** The three limit fields are labelled `일반 위임 작업 제한`, `짧은 작업 제한`, `긴 작업 제한`; the section text says which slots each covers.
- **Fixture.** `fixture-model-picker-entry.jsx` answers `delegation-preview` and `apply` with invented receipts so the chain can be watched; it writes nothing.

## Independent review (2026-11-17) and what was done with it

Two fresh read-only reviews, both GO-WITH-FIXES. Corrected in source with tests: the no-change save copying role models (desktop MAJOR), chain-stop wording, render guard for a status that gains slot fields, zero-target whole-page save, summary omissions, Korean text, the apply-time capability gate (`service.apply`), initial-setup validation of slot routes, bundled policy wording about `config.slots`, the 16,384-character body limit, and the install-order rule for processes still running pre-slot code (page reminder, `after-install.md`, `docs/wiki/task-slots.md`, `PLAN.md`).

Left as is, known:

- Frozen-backend side effects of any routing-scoped or unscoped store save, unchanged by this work: the loaded profile's `routing.heavy` / `routing.light` are copied to routing targets along with the slots, `routing_profiles` is an absolute list, `skills.disabled` drift is repaired on profiles in that list, and store entries are created for every discovered profile. So "membership only" for `routing-reenable-save` describes the request body.
- A process running pre-slot code is not detected by the capability gate, which reads packages on disk. It fails closed until restarted.
- Dead state in `desktop/plugin.js` after the merge (`nativeDelegationTargets`, `routingTargets`, `routingBaseline`, the `models` / `routing` branches of `saveSection`, `sectionErrors.routing`).
- Two React "unique key" development warnings from older sections that pass child arrays to `jsx` (runtime-limit fields, fallback target group, combined-save summary).
- `README.md` and the `coding_route` tool description still describe Heavy/Light; `PLAN.md` does not list `routing_config().purpose_slots`.
- `model_router/slots.py`, `tests/test_slots.py`, `tests/test_slots_desktop.mjs`, `tests/test_model_picker_desktop.mjs` and the fixture files are part of the v0.11.0 commit.

## Corrections after the review of the commit

- **Status is read in pages.** Hermes returns at most 48,000 characters of one CLI call's output. The slot fields grew the status of eleven real profiles to 50,866 characters, so the page could not load. `status` accepts `{"paged": true}` and an optional `profiles` list, returns rows up to `STATUS_PAGE_BUDGET` (30,000 characters) and names the rest in `pending_profiles`; the page joins the pages only when revision, installation identity and profile list agree. A call without a body returns the complete status as before. A backend from before paging refuses the body and is then asked once the old way.
- The apply-time check stops only a plan that adds or changes some profile's slots; clearing one profile while another keeps its slots is no longer refused.
- A changed delegation method or spare model that no selected profile can take is shown as an error instead of an empty summary, and the save handler refuses to run while the section shows an error.
- Plan replies are bounded too. On an eleven-profile fake home a second slot save to every profile previewed at 54,217 characters and a delegation preview with long allow-list descriptions at 58,761 for four targets. The CLI handler prints a plan larger than 40,000 characters with each change's profile and field only (`changes_compacted`); the page only checks that `changes` is a list, and the stored plan is unchanged.
- Tests were added for the unchanged-slot apply path, the slot routes checked by initial setup, paging on both sides and the status CLI body.
