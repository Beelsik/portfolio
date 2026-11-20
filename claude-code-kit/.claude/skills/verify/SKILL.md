---
name: verify
description: Check a finished change before reporting it - tests, lint, diff size, and what still needs a human check. Use before saying any task is done.
---

# Verify a change

Run and read the output of each:

1. `npm test`
2. `npm run lint`
3. `git diff --stat`. If files outside `.claude/scope.txt` appear, revert them.
4. `git diff`. Look for leftover logs, commented-out code, TODOs you added.

Then write the report in this shape:

- **Changed:** files and one line each
- **Verified:** commands that passed
- **Not verified:** what needs the human, for example behaviour on a real Windows machine
