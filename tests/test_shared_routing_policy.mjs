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

test('settings page explains broad routing scope without turning profile membership into opt-in', () => {
  assert.match(desktop, /코딩과 복잡한 비코딩 판단 작업에 공통 정책을 적용합니다/)
  assert.match(desktop, /근거 충돌/)
  assert.match(desktop, /단순 글쓰기·번역·요약·추출은 Heavy 대상이 아닙니다/)
  assert.match(desktop, /공통 정책은 모든 프로필에서 같지만, 라우팅은 여기서 활성화한 프로필에서만 사용합니다/)
  assert.match(desktop, /새 프로필은 기본적으로 활성화되지 않습니다/)
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
  assert.match(read('plugin.yaml'), /코딩·복잡한 비코딩 판단/)
})
