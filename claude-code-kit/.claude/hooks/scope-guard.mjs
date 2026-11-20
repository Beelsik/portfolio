#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

// PreToolUse guard for Edit / Write / MultiEdit / NotebookEdit.
// Exit code 2 cancels the tool call and feeds stderr back into the session.

const raw = fs.readFileSync(0, 'utf8').trim();
const payload = raw ? JSON.parse(raw) : {};
const root = path.resolve(process.env.CLAUDE_PROJECT_DIR || payload.cwd || process.cwd());

const target =
  payload.tool_input?.file_path ??
  payload.tool_input?.notebook_path ??
  payload.tool_input?.path;

if (!target || typeof target !== 'string') {
  process.exit(0);
}

const absTarget = path.resolve(root, target);
const relRaw = path.relative(root, absTarget);

// On Windows, a path on another drive returns an absolute path from path.relative().
if (relRaw.startsWith('..') || path.isAbsolute(relRaw)) {
  deny(`Refused: "${target}" resolves outside workspace root (${root}).`);
}

const rel = relRaw.split(path.sep).join('/');
const relLower = rel.toLowerCase();

const ALWAYS_PROTECTED = [
  /^\.git(\/|$)/i,
  /(^|\/)\.env($|\.)/i,
  /(^|\/)secrets?(\/|$)/i,
  /\.(pem|key|p12|pfx|keystore)$/i,
  /^\.claude\/settings(\.local)?\.json$/i,
  /^\.claude\/hooks(\/|$)/i,
];

if (ALWAYS_PROTECTED.some((re) => re.test(rel))) {
  deny(`Refused: "${rel}" is on the protected list. Ask the developer to edit it manually.`);
}

const scopePath = path.join(root, '.claude', 'scope.txt');
const scope = loadScope(scopePath);

if (relLower === '.claude/scope.txt') {
  if (scope.length > 0) {
    deny(
      'scope.txt is already locked for the active task.\n' +
      'Stop and list the extra files you need so the developer can approve or add them.'
    );
  }
  process.exit(0);
}

// Empty scope.txt = interactive exploration / no locked task yet.
if (scope.length === 0) {
  process.exit(0);
}

if (scope.some((pattern) => compileGlob(pattern).test(rel))) {
  process.exit(0);
}

deny(
  `Out-of-scope edit blocked: "${rel}"\n` +
  `Allowed patterns in .claude/scope.txt:\n` +
  scope.map((s) => `  - ${s}`).join('\n') +
  '\nAsk before touching files outside the agreed plan.'
);

function loadScope(file) {
  try {
    return fs
      .readFileSync(file, 'utf8')
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#'));
  } catch {
    return [];
  }
}

function compileGlob(pattern) {
  let norm = pattern.replace(/\\/g, '/').replace(/^\.\//, '');
  if (norm.endsWith('/')) norm += '**';

  const expr = norm
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*\/?/g, '\0')
    .replace(/\*/g, '[^/]*')
    .replace(/\?/g, '[^/]')
    .replace(/\0/g, '.*');

  // Case-insensitive on Windows/macOS where FS is usually case-preserving
  const flags = process.platform === 'linux' ? '' : 'i';
  return new RegExp(`^${expr}$`, flags);
}

function deny(msg) {
  process.stderr.write(msg + '\n');
  process.exit(2);
}
