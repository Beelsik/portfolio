# app/main: Electron main process

This code runs with the user's permissions and changes Windows settings
(power plans, services, registry keys). Rules for this folder:

- Every system change goes through `tweaks/` and must have a matching `revert()`.
- Before writing a registry key, read and store the old value.
- Use the `safeExec()` wrapper, never `child_process.exec` directly.
- Any new tweak needs a unit test for `apply()` and `revert()` with the system layer mocked.
- Do not test on the real system from Claude Code. The human tests on the Windows PC.
