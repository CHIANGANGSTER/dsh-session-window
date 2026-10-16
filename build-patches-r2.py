#!/usr/bin/env python3
"""B-01/B-02: build the R2 patch specification for the DSH Desktop shell.

Writes ``patches/r2/main.js.json`` and ``patches/r2/preload-app.cjs.json``.
Every anchor is taken verbatim from the A-04 extract and must occur exactly once
in the pristine file; ``patch-asar.py`` refuses to write anything otherwise.

Design (see R2-RUNBOOK.md "目标设计"):

* main process: window registry keyed by webContents.id, ``isAppSender``,
  three IPC channels with a pending-target store and bounded expiry, the cookie
  gate widened from "the primary window" to "any registered window", and a
  secondary-window factory reusing ``createWindow``.
* preload: one new ``dshSessionWindow`` object, no ``ipcRenderer`` leak.
* No new electron import names, no new webRequest listener.

Usage:
    python build-patches-r2.py --out patches/r2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ─────────────────────────────────────────────────────────────────────────────
# anchors (verified unique in $R2\extract\lib\main.js)
# ─────────────────────────────────────────────────────────────────────────────
A_SCHEME = 'const SCHEME = "dsh-app";'
A_CREATE_MAIN = "const createMainWindow = () => {"
A_MAIN_ASSIGN = "mainWindow = window;"
A_ENTER_WORKSPACE = "const enterWorkspace = async ({ activate = true } = {}) => {"
A_COOKIE_GATE = (
    "if (hostUrl === void 0 || hostCookie === void 0 || "
    "details.webContentsId !== mainWindow?.webContents.id) {"
)
A_PRELOAD_EXPOSE = (
    'electron.contextBridge.exposeInMainWorld("dshDesktop", '
    "location.protocol === `dsh-app:` && location.hostname === \"app\" && "
    "process.isMainFrame ? createProductApi() : { protocolVersion: 1 });"
)

# ─────────────────────────────────────────────────────────────────────────────
# main.js — block 1: registry, isAppSender, pending store, logging, factory
# Inserted immediately before `const createMainWindow = () => {`.
# Uses only names already in scope: appWindows/appPreload/createWindow/app/join/
# appendFileSync/currentDesktopLocale/browserGuests/shortcuts/applicationUrl.
# ─────────────────────────────────────────────────────────────────────────────
MAIN_BLOCK1 = r"""const appWindows = /* @__PURE__ */ new Set();
const pendingTargets = /* @__PURE__ */ new Map();
const PENDING_SOFT_MS = 6e4;
const PENDING_HARD_MS = 12e4;
let pendingSeq = 0;
const nextRequestId = () => `req_${Date.now().toString(36)}_${(pendingSeq++).toString(36)}`;
const logWindowEvent = (event, fields) => {
	try {
		appendFileSync(join(app.getPath("logs"), "dsh-session-window.log"), `${new Date().toISOString()} ${event} ${JSON.stringify(fields ?? {})}\n`);
	} catch {}
};
const registerAppWindow = (window) => {
	const id = window.webContents.id;
	appWindows.add(id);
	window.on("closed", () => {
		appWindows.delete(id);
		pendingTargets.delete(id);
		logWindowEvent("close", { webContentsId: id });
	});
	logWindowEvent("register", { webContentsId: id });
	return id;
};
const isRegisteredContents = (contents) => contents !== void 0 && contents !== null && appWindows.has(contents.id);
const isAppSender = (event) => {
	const frame = event.senderFrame;
	if (frame === null || frame === void 0) return false;
	if (frame !== event.sender.mainFrame) return false;
	if (!isRegisteredContents(event.sender)) return false;
	try {
		const url = new URL(frame.url);
		return url.protocol === `${SCHEME}:` && url.hostname === "app";
	} catch {
		return false;
	}
};
const attachAppWindowDiagnostics = (window) => {
	window.webContents.on("console-message", (details) => {
		if (details.level !== "error") return;
		logWindowEvent("renderer-error", { webContentsId: window.webContents.id, message: String(details.message).slice(0, 400) });
		rendererConsole.push(`${details.sourceId}:${String(details.lineNumber)} ${details.message}`);
	});
	window.webContents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
		if (isMainFrame && code !== -3 && !quitting && !window.isDestroyed()) reportFatal(/* @__PURE__ */ new Error(`Desktop page failed to load: ${url} (${String(code)}: ${description})`), "renderer");
	});
	window.webContents.on("preload-error", (_event, _path, error) => {
		if (!quitting && !window.isDestroyed()) reportFatal(error, "renderer");
	});
	window.webContents.on("render-process-gone", (_event, details) => {
		navigation = void 0;
		if (!quitting && !window.isDestroyed() && details.reason !== "clean-exit") reportFatal(/* @__PURE__ */ new Error(`Desktop renderer exited: ${details.reason}`), "renderer");
	});
};
const markPendingLoaded = (window) => {
	window.webContents.on("did-finish-load", () => {
		const entry = pendingTargets.get(window.webContents.id);
		if (entry !== void 0) {
			entry.lastLoadAt = Date.now();
			logWindowEvent("pending-load", { webContentsId: window.webContents.id, requestId: entry.requestId });
		}
	});
};
const readPendingTarget = (id) => {
	const entry = pendingTargets.get(id);
	if (entry === void 0) return null;
	const now = Date.now();
	if (!entry.expired) {
		const soft = entry.lastLoadAt !== null && now - entry.lastLoadAt > PENDING_SOFT_MS;
		const hard = now - entry.createdAt > PENDING_HARD_MS;
		if (soft || hard) {
			entry.expired = true;
			logWindowEvent("pending-expired", { webContentsId: id, requestId: entry.requestId, reason: hard ? "hard" : "soft" });
		}
	}
	return {
		requestId: entry.requestId,
		sessionId: entry.sessionId,
		...entry.expired ? { expired: true } : {}
	};
};
const createAppWindow = (sessionId) => {
	const window = createWindow(appPreload, true, true);
	const id = registerAppWindow(window);
	browserGuests.bind(window, (guest, name) => shortcuts.attachGuest(window, guest, name));
	shortcuts.attach(window);
	attachAppWindowDiagnostics(window);
	markPendingLoaded(window);
	window.on("close", (event) => {
		if (quitting || shellInstallerOwnsQuit || sessionEnding) return;
		event.preventDefault();
		if (!window.isDestroyed()) window.destroy();
	});
	const requestId = nextRequestId();
	pendingTargets.set(id, {
		requestId,
		sessionId,
		createdAt: Date.now(),
		lastLoadAt: null,
		expired: false
	});
	logWindowEvent("open", { webContentsId: id, requestId, sessionId });
	window.loadURL(applicationUrl).catch((error) => {
		logWindowEvent("open-failed", { webContentsId: id, requestId, message: String(error) });
		if (!window.isDestroyed()) window.destroy();
	});
	return { window, requestId };
};
"""

# main.js — block 2: the three IPC channels, inserted before enterWorkspace.
MAIN_BLOCK2 = r"""ipcMain.handle("dsh-desktop:open-session-window", async (event, sessionId, displayTitle) => {
	if (!isAppSender(event)) {
		logWindowEvent("reject", { reason: "not-app-sender", channel: "open-session-window" });
		return { ok: false, code: "INVALID_SESSION" };
	}
	if (typeof sessionId !== "string" || sessionId.length === 0 || sessionId.length > 128) {
		logWindowEvent("reject", { reason: "bad-session-id", channel: "open-session-window" });
		return { ok: false, code: "INVALID_SESSION" };
	}
	if (quitting) return { ok: false, code: "OPEN_FAILED" };
	if (appWindows.size >= 8) {
		logWindowEvent("reject", { reason: "window-limit", channel: "open-session-window" });
		return { ok: false, code: "WINDOW_LIMIT" };
	}
	try {
		const { requestId } = createAppWindow(sessionId);
		return { ok: true, requestId };
	} catch (error) {
		logWindowEvent("open-failed", { message: String(error) });
		return { ok: false, code: "OPEN_FAILED" };
	}
});
ipcMain.handle("dsh-desktop:get-pending-target", async (event) => {
	if (!isAppSender(event)) return null;
	const target = readPendingTarget(event.sender.id);
	if (target === null) return null;
	logWindowEvent("pending-read", {
		webContentsId: event.sender.id,
		requestId: target.requestId,
		expired: target.expired === true
	});
	return target;
});
ipcMain.handle("dsh-desktop:ack-pending-target", async (event, requestId, result, code) => {
	if (!isAppSender(event)) return { ok: false, code: "INVALID_SESSION" };
	const id = event.sender.id;
	const entry = pendingTargets.get(id);
	if (entry === void 0 || entry.requestId !== requestId) {
		logWindowEvent("ack-mismatch", { webContentsId: id, requestId: String(requestId) });
		return { ok: false, code: "OPEN_FAILED" };
	}
	pendingTargets.delete(id);
	logWindowEvent("ack", {
		webContentsId: id,
		requestId,
		result: result === "opened" ? "opened" : "failed",
		code: typeof code === "string" ? code : void 0
	});
	return { ok: true };
});
"""

# main.js — block 3: cookie gate widened (replace, not insert).
MAIN_COOKIE_REPLACE = (
    "if (hostUrl === void 0 || hostCookie === void 0 || "
    "!appWindows.has(details.webContentsId)) {"
)

# main.js — block 4: register the primary window too.
MAIN_REGISTER_REPLACE = "mainWindow = window;\n\t\tregisterAppWindow(window);"

# ─────────────────────────────────────────────────────────────────────────────
# preload — one new exposed object.
# ─────────────────────────────────────────────────────────────────────────────
PRELOAD_BLOCK = r"""electron.contextBridge.exposeInMainWorld("dshSessionWindow", location.protocol === `dsh-app:` && location.hostname === "app" && process.isMainFrame ? {
	version: 2,
	openSessionWindow: (sessionId, displayTitle) => electron.ipcRenderer.invoke("dsh-desktop:open-session-window", sessionId, String(displayTitle ?? "")),
	getPendingTarget: () => electron.ipcRenderer.invoke("dsh-desktop:get-pending-target"),
	ackPendingTarget: (requestId, result, code) => electron.ipcRenderer.invoke("dsh-desktop:ack-pending-target", requestId, result, code)
} : { version: 0 });
"""


def window_edits() -> list[dict]:
    """Exact shipped anchors: keep origin/frame checks and route to the owner."""
    pairs = [
        ("locale-bootstrap", 'event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== new URL(applicationUrl).origin', '!isAppSender(event)'),
        ("product-sender", 'mainWindow === void 0 || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents || event.senderFrame === null || event.senderFrame !== mainWindow.webContents.mainFrame', '!isAppSender(event)'),
        ("native-theme", 'if (mainWindow === void 0 || event.sender !== mainWindow.webContents) return;', 'if (!isAppSender(event)) return;'),
        ("locale-change", 'if (window === void 0 || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || typeof next !== "string") return;', 'if (!isAppSender(event) || typeof next !== "string") return;'),
        ("shortcuts-owners", 'function installDesktopShortcuts(getWindow, userData, platform, updateMenu, overlayInput) {', 'function installDesktopShortcuts(getWindow, userData, platform, updateMenu, overlayInput, getWindows) {'),
        ("shortcuts-sender", 'const assertSender = (event) => {\n\t\tconst window = getWindow();', 'const assertSender = (event) => {\n\t\tconst window = getWindows().find((owner) => owner.webContents === event.sender);'),
        ("shortcuts-broadcast", 'const window = getWindow();\n\t\tif (window !== void 0 && !window.isDestroyed() && window.webContents.mainFrame.url.startsWith("dsh-app://app/")) window.webContents.send(DESKTOP_IPC.shortcutsChanged, snapshot);', 'for (const window of getWindows()) {\n\t\t\tif (!window.isDestroyed() && window.webContents.mainFrame.url.startsWith("dsh-app://app/")) window.webContents.send(DESKTOP_IPC.shortcutsChanged, snapshot);\n\t\t}'),
        ("shortcuts-focused", 'installDesktopShortcuts(() => mainWindow,', 'installDesktopShortcuts(() => { const focused = BrowserWindow.getFocusedWindow(); return focused && appWindows.has(focused.webContents.id) ? focused : mainWindow; },'),
        ("shortcuts-registry", '}, (window) => updateOverlays.input(window));', '}, (window) => updateOverlays.input(window), () => BrowserWindow.getAllWindows().filter((window) => appWindows.has(window.webContents.id)));'),
        ("directory-owner", 'installDesktopDirectoryPicker(() => mainWindow);', 'installDesktopDirectoryPicker((contents) => isRegisteredContents(contents) ? BrowserWindow.fromWebContents(contents) : void 0);'),
        ("directory-sender", 'ipcMain.handle(DESKTOP_IPC.directoryPick, async (event) => {\n\t\tconst window = getWindow();', 'ipcMain.handle(DESKTOP_IPC.directoryPick, async (event) => {\n\t\tconst window = getWindow(event.sender);'),
        ("menu-sender", 'if (mainWindow === void 0 || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) throw new Error("desktop menu: rejected sender");', 'if (!isAppSender(event)) throw new Error("desktop menu: rejected sender");'),
        ("menu-owner", 'const window = mainWindow;\n\t\t\tconst editItem =', 'const window = BrowserWindow.fromWebContents(event.sender);\n\t\t\tconst editItem ='),
        ("menu-zoom", 'const zoom = mainWindow.webContents.getZoomFactor();', 'const zoom = window.webContents.getZoomFactor();'),
        ("appearance-owner", 'if (mainWindow === void 0 || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) return;', 'if (!isAppSender(event)) return;\n\t\t\tconst window = BrowserWindow.fromWebContents(event.sender);'),
        ("appearance-target", 'if (validColor(color) && validColor(symbolColor)) mainWindow.setTitleBarOverlay({', 'if (validColor(color) && validColor(symbolColor)) window.setTitleBarOverlay({'),
        ("boot-failure", 'if (event.sender !== mainWindow?.webContents || event.senderFrame !== event.sender.mainFrame) throw new Error("dsh desktop: rejected startup failure from a non-primary frame");', 'if (!isAppSender(event)) throw new Error("dsh desktop: rejected startup failure from an unowned frame");'),
        ("boot-failure-report", 'reportFatal(new Error(message), "web-boot");', 'if (event.sender !== mainWindow?.webContents) {\n\t\t\tlogWindowEvent("boot-failed", { webContentsId: event.sender.id, message: message.slice(0, 400) });\n\t\t\treturn;\n\t\t}\n\t\treportFatal(new Error(message), "web-boot");'),
    ]
    return [{"id": f"main-{name}", "find": before, "replace": after}
            for name, before, after in pairs]


def body(text: str) -> str:
    return text.rstrip("\n") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(HERE / "patches" / "r2"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    main_spec = {
        "asar_path": "/lib/main.js",
        "edits": [
            {"id": "main-insert-registry", "find": "const assertProductSender = (event) => {",
             "insert_before": body(MAIN_BLOCK1)},
            {"id": "main-insert-ipc", "find": A_ENTER_WORKSPACE,
             "insert_before": body(MAIN_BLOCK2)},
            {"id": "main-register-primary", "find": A_MAIN_ASSIGN,
             "replace": MAIN_REGISTER_REPLACE},
            {"id": "main-cookie-gate", "find": A_COOKIE_GATE,
             "replace": MAIN_COOKIE_REPLACE},
        ] + window_edits(),
    }
    preload_spec = {
        "asar_path": "/lib/preload-app.cjs",
        "edits": [
            {"id": "preload-insert-bridge", "find": A_PRELOAD_EXPOSE,
             "insert_after": body(PRELOAD_BLOCK)},
        ],
    }

    for name, spec in (("main.js.json", main_spec), ("preload-app.cjs.json", preload_spec)):
        (out / name).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out / name}")
        for edit in spec["edits"]:
            kind = "insert_before" if "insert_before" in edit else (
                "insert_after" if "insert_after" in edit else "replace")
            print(f"  {edit['id']:<28} {kind:<14} anchor {len(edit['find'])} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

