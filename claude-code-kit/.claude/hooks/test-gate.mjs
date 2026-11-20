#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

// Stop hook: runs test suite if the working tree has changes.
// Blocks completion (exit 2) up to MAX_ATTEMPTS times so the agent fixes regressions
// instead of declaring victory on broken tests.

const MAX_ATTEMPTS = 3;
const raw = fs.readFileSync(0, 'utf8').trim();
const payload = raw ? JSON.parse(raw) : {};
const root = path.resolve(process.env.CLAUDE_PROJECT_DIR || payload.cwd || process.cwd());

const sessionKey = String(payload.session_id || 'local').replace(/[^a-zA-Z0-9_-]/g, '_');
const stateFile = path.join(os.tmpdir(), `cc-test-gate-${sessionKey}.count`);

const status = spawnSync('git', ['status', '--porcelain'], {
  cwd: root,
  encoding: 'utf8',
});

// Clean tree (read-only Q&A session) -> let it finish right away.
if (status.status === 0 && !status.stdout.trim()) {
  cleanup();
  process.exit(0);
}

const testCmd = process.env.CLAUDE_TEST_CMD || 'npm test --silent';
const result = spawnSync(testCmd, {
  cwd: root,
  shell: true,
  encoding: 'utf8',
  timeout: 240_000,
});

if (result.status === 0) {
  const scopeFile = path.join(root, '.claude', 'scope.txt');
  if (fs.existsSync(scopeFile)) {
    fs.writeFileSync(
      scopeFile,
      '# Scope cleared after passing tests. Fill once the next plan is approved.\n'
    );
  }
  cleanup();
  process.exit(0);
}

const attempt = readCount(stateFile) + 1;
if (attempt > MAX_ATTEMPTS) {
  cleanup();
  // Stop looping after 3 failed rounds; CLAUDE.md requires reporting the failure explicitly.
  process.exit(0);
}

fs.writeFileSync(stateFile, String(attempt), 'utf8');

const combined = `${result.stdout || ''}\n${result.stderr || ''}`.trim();
const tail = combined.split(/\r?\n/).slice(-35).join('\n');

process.stderr.write(
  `[test-gate] "${testCmd}" failed (attempt ${attempt}/${MAX_ATTEMPTS}).\n` +
  `Fix the failing tests before finishing — do not skip or delete assertions.\n\n` +
  `${tail}\n`
);
process.exit(2);

function readCount(file) {
  try {
    return Number.parseInt(fs.readFileSync(file, 'utf8'), 10) || 0;
  } catch {
    return 0;
  }
}

function cleanup() {
  try {
    fs.rmSync(stateFile, { force: true });
  } catch {}
}
