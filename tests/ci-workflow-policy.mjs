import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../.github/workflows/desktop-tests.yml', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
function validate(text) {
  assert.match(text, /on:\n  push:\n    branches: \['\*\*'\]\n  pull_request:/)
  assert.match(text, /cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}/)
  assert.match(text, /group: desktop-tests-\$\{\{ github\.ref \}\}/)
  assert.match(text, /permissions:\n  contents: read/)
  const jobs = text.slice(text.indexOf('\njobs:\n'))
  assert.deepEqual([...jobs.matchAll(/^  ([\w-]+):/gm)].map(match => match[1]), ['desktop'])
  assert.match(jobs, /os: \[windows-latest, ubuntu-latest\]/)
  assert.match(jobs, /fail-fast: false/)
  assert.match(jobs, /node-version: '24'/)
  assert.match(jobs, /persist-credentials: false/)
  assert.match(jobs, /actions\/checkout@11d5960a326750d5838078e36cf38b85af677262/)
  assert.match(jobs, /actions\/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020/)
  assert.match(jobs, /node --check desktop\/plugin\.js\n          node --test --test-reporter=tap tests\/\*\.mjs/)
  assert.doesNotMatch(jobs, /continue-on-error|secrets\.|publish|npm publish|wrangler|workflow_dispatch/)
}

test('all branch pushes and optional PRs retain both OS test suites without tag push duplication', () => validate(source))
test('CRLF checkout preserves the same workflow contract', () => validate(source.replace(/\n/g, '\r\n').replace(/\r\n/g, '\n')))
test('tag admission, main cancellation and lost OS coverage are rejected', () => {
  for (const broken of [
    source.replace("branches: ['**']", "tags: ['**']"),
    source.replace("${{ github.event_name == 'pull_request' }}", 'true'),
    source.replace('[windows-latest, ubuntu-latest]', '[ubuntu-latest]'),
    source.replace('contents: read', 'contents: write'),
  ]) assert.throws(() => validate(broken))
})
