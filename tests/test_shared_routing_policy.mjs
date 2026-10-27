import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = new URL('../', import.meta.url)
const read = relative => readFileSync(fileURLToPath(new URL(relative, root)), 'utf8')
const canonical = read('skills/adaptive-coding-orchestration/SKILL.md')
const compatibility = read('compat/adaptive-coding-orchestration/SKILL.md')
const desktop = read('desktop/plugin.js')
const registration = read('__init__.py')
const readme = read('README.md')

test('small bounded changes stay Main-owned before route discovery or configuration', () => {
  for (const policy of [canonical, compatibility]) {
    assert.match(policy, /Main implements small, bounded changes directly/)
    assert.match(policy, /at least two substantive, independent workstreams/)
    assert.match(policy, /Do not split a small task artificially/)
    assert.match(policy, /startup, context transfer and coordination/)
    assert.match(policy, /required Heavy or independent review/)
  }
  assert.ok(canonical.indexOf('## Direct-Main default') < canonical.indexOf('## First check'))
  assert.match(canonical, /do not discover or query coding_route just to perform local work/)
  assert.match(canonical, /Tests, lint, build and optional review of the same small edit do not count/)
  assert.match(canonical, /Apply the same threshold to native delegate_task/)
  assert.match(canonical, /A required single Heavy review is an exception/)
  assert.match(canonical, /Small review-driven corrections stay with Main/)
  assert.match(canonical, /User-facing visual\/motion design remains Main-owned/)
  assert.doesNotMatch(canonical, /Medium: Main or Light implements|Light normally fixes findings/)
})

test('discovery and settings copy expose the direct-Main default without changing the router API', () => {
  assert.match(registration, /Main handles small bounded changes directly/)
  assert.match(registration, /at least two substantive independent workstreams/)
  assert.match(registration, /required Heavy\/independent review remains mandatory/)
  assert.match(desktop, /간단한 작업은 메인 모델이 직접 처리/)
  assert.match(desktop, /계획이나 중요한 검토는 Heavy/)
  // Detailed execution policy remains in the canonical skill/docs, not consumer UI.
  assert.match(readme, /작고 범위가 명확한 수정은 메인 모델이 직접 처리/)
  assert.match(readme, /독립적인 실작업 두 개 이상/)
  assert.match(readme, /필수 Heavy·독립 검수/)
})

test('canonical and compatibility skill keep the name and share complex non-coding scope', () => {
  assert.match(canonical, /^name: adaptive-coding-orchestration$/m)
  assert.match(compatibility, /^name: adaptive-coding-orchestration$/m)
  assert.match(canonical, /coding_route\(action="config"\)/)
  assert.match(canonical, /substantial ambiguity, interdependent evidence, consequential content errors, or repeated conceptual failure/)
  assert.match(canonical, /Do not route ordinary writing, translation, summaries, simple extraction or one-step lookups to Heavy/)
  assert.match(canonical, /Divide large content work by nonoverlapping subject\/item ranges with saved checkpoints and a concrete time\/retry budget/)
  assert.match(canonical, /Pilot the output before scaling/)
  assert.match(canonical, /Keep external writes serialized under existing approvals/)
  assert.match(canonical, /After two failed attempts at the same operation/)
  assert.match(canonical, /requested route, native runtime-reported/)
  assert.match(compatibility, /skill_view\(name="model-router:adaptive-coding-orchestration"\)/)
  assert.match(compatibility, /not routine writing\/extraction/)
})

test('settings page explains broad routing scope, default-on installation, and preserved explicit opt-outs', () => {
  assert.match(desktop, /계획이나 중요한 검토는 Heavy/)
  assert.match(desktop, /단순 글쓰기·번역·요약 때문에 무조건 Heavy를 쓰지는 않습니다/)
  assert.match(desktop, /새로 설치한 프로필은 작업 분담이 기본으로 켜집니다/)
  assert.match(desktop, /이전에 꺼 둔 프로필은 그대로 유지/)
  assert.match(desktop, /작업·검증 라우팅 폴백/)
  assert.doesNotMatch(desktop, /코딩·검증 라우팅/)
  assert.match(readme, /동봉 정책은 프로필마다 동일합니다/)
  assert.match(readme, /공통 정책 문구의 배포는 라우팅 사용 동의가 아닙니다/)
  assert.match(readme, /단순 글쓰기·번역·요약·정보 추출/)
})

test('native routing replaces launch fields while legacy read-only access remains', () => {
  assert.match(registration, /"name": "coding_route"/)
  assert.match(registration, /register_native_delegation\(ctx, home\)/)
  assert.match(registration, /"enum": \["config", "status", "join"\]/)
  assert.doesNotMatch(registration, /"enum": \["config", "start"/)
  assert.match(registration, /start_retired/)
  assert.match(registration, /Profile-enabled coding and complex non-coding orchestration/)
  assert.match(canonical, /Native routes \(Hermes >=0.22.5\)/)
  assert.match(canonical, /`model-router-profiles`/)
  assert.match(canonical, /legacy fresh-task-rerun consent never authorizes/)
  assert.match(read('plugin.yaml'), /requires_hermes: ">=0.22.5"/)
  assert.doesNotMatch(desktop, /시간 초과 시 실행 프로세스를 정리합니다/)
  assert.match(desktop, /중단을 요청하지만, 실제로 멈추기까지 시간이 걸릴/)
  assert.doesNotMatch(canonical, /Routed jobs retain their existing process-tree cancellation/ )
})
