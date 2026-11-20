# claude-code-guardrails

Minimal `.claude/` setup I use on multi-folder TypeScript repos (Electron + React + Node + Supabase) so Claude Code stays inside the agreed files and doesn't close a task while tests are red.

Zero dependencies — hooks use plain Node (`node:fs`, `node:path`, `node:child_process`) and work on Windows, macOS, and Linux.

## Why this exists

Out of the box, asking Claude Code to fix a bug in `app/renderer/` often ends with unsolicited edits in `server/`, reformatted configs, or a confident "all done!" without running Vitest. Prompting alone ("please don't touch other files") gets ignored once context grows. Hooks enforce it at tool-call level:

- **`.claude/hooks/scope-guard.mjs`** (`PreToolUse` on `Edit | Write | MultiEdit | NotebookEdit`):
  - Hard-blocks `.env*` (case-insensitive), keys/certs (`.pem`, `.key`, `.pfx`), `.git/`, and `.claude/hooks/` itself.
  - Rejects paths resolving outside workspace root (including cross-drive paths on Windows).
  - Lets the agent write `.claude/scope.txt` **once** after you approve its plan, then locks `scope.txt` until tests pass. Any edit outside those globs returns exit code `2` and sends the allowed list back via `stderr`.
- **`.claude/hooks/test-gate.mjs`** (`Stop`):
  - Skips if `git status --porcelain` is clean (so read-only questions don't trigger test runs).
  - Runs `CLAUDE_TEST_CMD` (defaults to `npm test --silent`). If tests fail, exits `2` with the last 35 lines of test output so the agent fixes what broke. Caps retries at 3 rounds to avoid infinite token burn, and clears `scope.txt` once tests pass.
- **`.claude/settings.json`**:
  - Explicit `deny` list for `.env` reads, `ssh`/`scp`/`rsync`, `git push`, `git reset --hard`, `supabase db push/reset`.
- **`.claude/skills/` & `.claude/agents/reviewer.md`**:
  - `fix-bug` (reproduce with a failing test first → plan → lock scope → minimal patch), `verify`, and a read-only `reviewer` sub-agent that audits `git diff` against the original prompt.

## Usage

Copy `.claude/` and `CLAUDE.md` into your repo root, then adjust commands and folder notes in `CLAUDE.md`.

If your test runner isn't `npm test --silent`, pass `CLAUDE_TEST_CMD` in `.claude/settings.json` or your shell:

```bash
CLAUDE_TEST_CMD="npx vitest run"
```

## Running hook tests locally

```bash
npm test
```

Uses Node's built-in `node:test` runner (Node 18+) against temporary sandboxes.

## Caveat

`scope-guard.mjs` intercepts Claude's file-editing tools (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`). A raw `Bash` redirection (`echo ... > file`) doesn't go through file-edit hooks — keep write-capable shell commands behind `"ask"` in `.claude/settings.json` and check `git diff --stat` before committing.
