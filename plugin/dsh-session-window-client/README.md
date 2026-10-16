# dsh-session-window-client

Adds **Open in new window** to a Session row's context menu in the DSH desktop
shell, and drives the landing flow inside the window it opens.

## Requirements

The desktop shell must carry the R2 session-window patch
(`dshSessionWindow`, protocol version 2). Without it the plugin activates but
renders nothing: every entry point is guarded by
`globalThis.dshSessionWindow?.version === 2`.

## How it works

1. `sidebar.workspaces.session.menu.item` gains one entry, id
   `open-in-new-window`, order `350`.
2. Selecting it calls `dshSessionWindow.openSessionWindow(sessionId, displayTitle)`.
   The shell creates the window, records a pending target for it, and answers
   `{ ok: true, requestId }` or `{ ok: false, code }`.
3. The new window loads the same application page. On activation this plugin
   reads the pending target with a bounded wait, waits for the Host's session
   list to know the Session, switches with `uiWorkspace.openSession`, confirms,
   and acknowledges.
4. A window with no pending target (including the primary window) stops
   immediately and says nothing.

## Error codes

`OPEN_FAILED`, `WINDOW_LIMIT`, `TIMEOUT`, `INVALID_SESSION`, `SESSION_NOT_FOUND`.
Each shows one user-readable notice; nothing is retried.

A manual session switch cannot be distinguished from a programmatic one
(A-08 question 11), so the plugin does not try: there is no `USER_NAVIGATED`
branch, and the record says so.

## Build

```
node scripts/build.mjs   # syntax check + copy src/client/index.js -> lib/client.js
node scripts/check.mjs   # static assertions from R2-RUNBOOK.md C-04
```

The client half is plain ESM importing only `react` and the DSH primitives, so
there is no transpile step.

