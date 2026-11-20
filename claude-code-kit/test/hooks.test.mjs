import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KIT_ROOT = path.resolve(__dirname, '..');
const SCOPE_GUARD = path.join(KIT_ROOT, '.claude', 'hooks', 'scope-guard.mjs');
const TEST_GATE = path.join(KIT_ROOT, '.claude', 'hooks', 'test-gate.mjs');

function makeSandbox(scopeLines = []) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-guard-test-'));
  fs.mkdirSync(path.join(dir, '.claude', 'hooks'), { recursive: true });
  fs.writeFileSync(
    path.join(dir, '.claude', 'scope.txt'),
    scopeLines.join('\n') + (scopeLines.length ? '\n' : '')
  );
  return dir;
}

function runGuard(cwd, filePath) {
  const payload = JSON.stringify({
    cwd,
    tool_name: 'Edit',
    tool_input: { file_path: filePath },
  });
  return spawnSync(process.execPath, [SCOPE_GUARD], {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: cwd },
  });
}

function initGitDirty(dir) {
  spawnSync('git', ['init', '-q'], { cwd: dir });
  fs.writeFileSync(path.join(dir, 'index.js'), 'export const ok = 1;\n');
}

test('allows regular file edit when scope.txt is empty', () => {
  const dir = makeSandbox();
  const res = runGuard(dir, 'app/renderer/App.tsx');
  assert.equal(res.status, 0);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('blocks .env variants regardless of casing', () => {
  const dir = makeSandbox(['**']);
  for (const target of ['.env', '.env.production', 'server/.ENV.local']) {
    const res = runGuard(dir, target);
    assert.equal(res.status, 2, `Expected ${target} to be blocked`);
    assert.match(res.stderr, /protected/i);
  }
  fs.rmSync(dir, { recursive: true, force: true });
});

test('blocks edits to hook files and .git internals', () => {
  const dir = makeSandbox(['**']);
  assert.equal(runGuard(dir, '.claude/hooks/scope-guard.mjs').status, 2);
  assert.equal(runGuard(dir, '.git/hooks/pre-commit').status, 2);
  assert.equal(runGuard(dir, 'certs/prod.pem').status, 2);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('blocks path traversal outside project root', () => {
  const dir = makeSandbox(['**']);
  const res = runGuard(dir, '../outside-secret.txt');
  assert.equal(res.status, 2);
  assert.match(res.stderr, /outside workspace/i);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('allows writing scope.txt once, then locks it', () => {
  const emptyDir = makeSandbox([]);
  assert.equal(runGuard(emptyDir, '.claude/scope.txt').status, 0);
  fs.rmSync(emptyDir, { recursive: true, force: true });

  const lockedDir = makeSandbox(['app/renderer/**']);
  const res = runGuard(lockedDir, '.claude/scope.txt');
  assert.equal(res.status, 2);
  assert.match(res.stderr, /locked/i);
  fs.rmSync(lockedDir, { recursive: true, force: true });
});

test('enforces glob patterns and directory prefixes when scope is active', () => {
  const dir = makeSandbox(['app/renderer/**/*.tsx', 'server/routes/']);
  assert.equal(runGuard(dir, 'app/renderer/components/Modal.tsx').status, 0);
  assert.equal(runGuard(dir, 'server/routes/bookings.ts').status, 0);

  const blocked = runGuard(dir, 'app/main/registry.ts');
  assert.equal(blocked.status, 2);
  assert.match(blocked.stderr, /Out-of-scope/i);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('test-gate blocks failing tests up to 3 times, then releases', () => {
  const dir = makeSandbox(['index.js']);
  initGitDirty(dir);
  const sessionId = `test-fail-${Date.now()}`;
  const payload = JSON.stringify({ cwd: dir, session_id: sessionId });

  for (let i = 1; i <= 3; i++) {
    const res = spawnSync(process.execPath, [TEST_GATE], {
      input: payload,
      encoding: 'utf8',
      env: {
        ...process.env,
        CLAUDE_PROJECT_DIR: dir,
        CLAUDE_TEST_CMD: `${process.execPath} -e "console.error('FAIL: spec'); process.exit(1)"`,
      },
    });
    assert.equal(res.status, 2, `Attempt ${i} should exit 2`);
    assert.match(res.stderr, new RegExp(`attempt ${i}/3`));
  }

  // 4th attempt releases loop so the agent can stop and report
  const fourth = spawnSync(process.execPath, [TEST_GATE], {
    input: payload,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: dir,
      CLAUDE_TEST_CMD: `${process.execPath} -e "process.exit(1)"`,
    },
  });
  assert.equal(fourth.status, 0);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('test-gate clears scope.txt once tests pass', () => {
  const dir = makeSandbox(['index.js']);
  initGitDirty(dir);
  const payload = JSON.stringify({ cwd: dir, session_id: `test-pass-${Date.now()}` });

  const res = spawnSync(process.execPath, [TEST_GATE], {
    input: payload,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: dir,
      CLAUDE_TEST_CMD: `${process.execPath} -e "process.exit(0)"`,
    },
  });
  assert.equal(res.status, 0);

  const remaining = fs
    .readFileSync(path.join(dir, '.claude', 'scope.txt'), 'utf8')
    .split(/\r?\n/)
    .filter((l) => l.trim() && !l.trim().startsWith('#'));
  assert.equal(remaining.length, 0);
  fs.rmSync(dir, { recursive: true, force: true });
});
