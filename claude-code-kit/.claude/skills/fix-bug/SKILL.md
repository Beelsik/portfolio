---
name: fix-bug
description: Fix a reported bug with a locked scope, a failing test first, and a reviewed diff. Use whenever the human reports a bug or a regression.
---

# Fix a bug

1. **Reproduce.** Find the code path. Write a test that fails because of the bug. If you cannot reproduce it, stop and ask for steps.
2. **Plan.** Name the cause in one sentence and list the files you will change (usually 1-3). Wait for approval.
3. **Lock scope.** Write the approved paths to `.claude/scope.txt`, one per line.
4. **Fix.** Smallest change that makes the new test pass. Nothing else.
5. **Verify.** Run `npm test` and `npm run lint`. Use the `verify` skill.
6. **Review.** Ask the `reviewer` agent to compare the diff with the original request.
7. **Report.** Cause, fix, test added, and anything not verified (for example: "not tested on Windows 10").
