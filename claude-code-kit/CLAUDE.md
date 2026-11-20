# Project rules

Desktop app (Electron + React), Node server on a VPS, Supabase database.
The app changes users' system settings, so a wrong edit can break someone's PC.

## How every change works
1. Plan first. List the files you will touch and why. Wait for approval.
2. After approval, write those paths (globs allowed) to `.claude/scope.txt`.
   Edits outside that list are blocked by a hook. If you need another file, stop and ask.
3. Make the smallest change that solves the task. No drive-by refactors, renames or formatting.
4. Run the tests. You cannot finish while they fail (Stop hook).
5. Report: what changed, what you verified, what you could not verify.

## Never
- Touch `.env*`, keys, `secrets/`, or production config.
- Connect to the VPS or run migrations against production.
- Delete or weaken a test to make it pass.
- Say something works without having run it.

## Commands
- `npm test`: unit tests (Vitest)
- `npm run test:e2e`: Electron smoke test (Playwright)
- `npm run lint`

## Code map
- `app/main/`: Electron main process. System-level code lives here, so be extra careful. See `app/main/CLAUDE.md`.
- `app/renderer/`: React UI.
- `server/`: Node API on the VPS.
- `supabase/migrations/`: SQL migrations, append-only.
