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
  for (const copy of [desktop, readme]) {
    assert.match(copy, /작고 범위가 명확한 수정은 메인 모델이 직접 처리/)
    assert.match(copy, /독립적인 실작업 두 개 이상/)
    assert.match(copy, /필수 Heavy·독립 검수/)
  }
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
  assert.match(canonical, /Each job records requested and actual model\/provider evidence/)
  assert.match(compatibility, /skill_view\(name="model-router:adaptive-coding-orchestration"\)/)
  assert.match(compatibility, /not routine writing\/extraction/)
})

test('settings page explains broad routing scope, default-on installation, and preserved explicit opt-outs', () => {
  assert.match(desktop, /코딩과 복잡한 비코딩 판단 작업에 공통 정책을 적용합니다/)
  assert.match(desktop, /근거 충돌/)
  assert.match(desktop, /단순 글쓰기·번역·요약·추출은 Heavy 대상이 아닙니다/)
  assert.match(desktop, /플러그인이 설치되고 별도 사용 여부를 저장하지 않은 프로필은 기본 활성화/)
  assert.match(desktop, /기존에 저장한 OFF와 명시적인 스킬 비활성화는 보존/)
  assert.match(desktop, /작업·검증 라우팅 폴백/)
  assert.doesNotMatch(desktop, /코딩·검증 라우팅/)
  assert.match(readme, /동봉 정책은 프로필마다 동일합니다/)
  assert.match(readme, /공통 정책 문구의 배포는 라우팅 사용 동의가 아닙니다/)
  assert.match(readme, /단순 글쓰기·번역·요약·정보 추출/)
})

test('tool identifier, purpose enum, profile gate and runtime contract remain unchanged', () => {
  assert.match(registration, /"name": "coding_route"/)
  assert.match(registration, /"enum": \["implementation", "mechanical", "preliminary-review", "plan", "semantic-final", "independent-review"\]/)
  assert.match(registration, /implementation\/mechanical\/preliminary-review use Light; plan\/semantic-final\/independent-review use Heavy/)
  assert.match(registration, /Disabled profiles are denied/)
  assert.match(registration, /This tool never changes model settings/)
  assert.match(registration, /coding and complex non-coding judgment/)
  assert.match(registration, /Profile-enabled coding and complex non-coding orchestration/)
  assert.doesNotMatch(registration, /Profile-enabled coding orchestration|코딩 라우팅이 꺼져/)
  assert.match(read('plugin.yaml'), /Profile model settings, default-on Heavy\/Light task routing/)
})
