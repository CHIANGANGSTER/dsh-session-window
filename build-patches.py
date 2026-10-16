#!/usr/bin/env python3
"""Build the patch specs consumed by ``patch-asar.py``.

Five anchored edits across two files:

``lib/main.js``
  1. ``__dshWindows``  — window registry + the second-window factory.
  2. ``open-session-window`` / ``show-session-menu`` IPC handlers.
  3. WebSocket cookie injection no longer restricted to the primary window.
  4. The Electron import line, to pull in ``WebContents``.

``lib/preload-app.cjs``
  5. ``dshSessionWindow`` — context menu bridge plus the "open session" event.

Anchors are exact substrings of the shipped bundle (v0.2.0-rc.2). The patcher
fails loudly if any anchor does not match exactly once, so a future app version
cannot silently produce a broken shell.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH_DIR = HERE / "patches"
PATCH_DIR.mkdir(parents=True, exist_ok=True)


def body(text: str) -> str:
    """Author with indentation, ship it minified."""
    return " ".join(line.strip() for line in text.strip().splitlines())


# ═════════════════════════════════════════════════════════════════════════════
# lib/main.js
# ═════════════════════════════════════════════════════════════════════════════
IMPORT_FIND = (
    'import { BrowserWindow, Menu, Notification, Tray, WebContentsView, app, clipboard, '
    'dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, session, shell, '
    'systemPreferences } from "electron";'
)
IMPORT_REPLACE = (
    'import { BrowserWindow, Menu, Notification, Tray, WebContents, WebContentsView, app, '
    'clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, '
    'session, shell, systemPreferences } from "electron";'
)

REGISTRY_FIND = "const createMainWindow = () => {"
REGISTRY_REPLACE = "const createMainWindow = () => {" + body("""
const __dshWindows = {
	windows: new Set(),
	spawned: 0,
	/** @returns the application window owning these contents, if it is one of ours. */
	find: (contents) => contents === void 0 || contents === null || contents.isDestroyed() === true ? void 0 : [...__dshWindows.windows].find((w) => w.isDestroyed() === false && w.webContents === contents),
	/**
	* Open one more application window, focused on a Session when one is named.
	* Reuses an existing window past the cap so a runaway caller cannot spawn
	* unbounded windows.
	* @param input.sessionId - Session to reveal in the new window.
	* @param input.activate - focus the window once it has loaded.
	* @returns the window, or undefined when the shell cannot open one.
	*/
	open: async ({ sessionId, activate = true } = {}) => {
		if (quitting || mainWindow === void 0 || mainWindow.isDestroyed()) return void 0;
		if (__dshWindows.windows.size >= 8) {
			const reuse = [...__dshWindows.windows].find((w) => w.isDestroyed() === false);
			if (reuse === void 0) return void 0;
			if (typeof sessionId === "string" && sessionId.length > 0) reuse.webContents.send("dsh-desktop:open-session", sessionId);
			reuse.show();
			reuse.focus();
			return reuse;
		}
		const step = __dshWindows.spawned++ % 6;
		const base = mainWindow.getBounds();
		const window = createWindow(appPreload, false, true);
		window.setBounds({
			x: base.x + 40 * step,
			y: base.y + 40 * step,
			width: base.width,
			height: base.height
		});
		__dshWindows.windows.add(window);
		window.on("closed", () => {
			__dshWindows.windows.delete(window);
		});
		window.on("close", (event) => {
			if (quitting || shellInstallerOwnsQuit || sessionEnding) return;
			if (window !== mainWindow) return;
			event.preventDefault();
			if (updateDialog.isOpen) {
				updateDialog.focus();
				return;
			}
			const hide = () => {
				if (!quitting && !shellInstallerOwnsQuit && !sessionEnding && !window.isDestroyed()) hideMainWindow(window);
			};
			if (backgroundNotice === void 0) hide();
			else backgroundNotice.close(hide);
		});
		if (typeof sessionId === "string" && sessionId.length > 0) window.setTitle(sessionId);
		try {
			await window.loadURL(applicationUrl);
		} catch (error) {
			__dshWindows.windows.delete(window);
			if (window.isDestroyed() === false) window.destroy();
			throw error;
		}
		if (window.isDestroyed()) return void 0;
		if (typeof sessionId === "string" && sessionId.length > 0) window.webContents.send("dsh-desktop:open-session", sessionId);
		if (activate) {
			window.show();
			window.focus();
		}
		return window;
	}
};
""")

IPC_FIND = "const enterWorkspace = async ({ activate = true } = {}) => {"
IPC_REPLACE = "const enterWorkspace = async ({ activate = true } = {}) => {" + body("""
ipcMain.handle("dsh-desktop:open-session-window", async (event, sessionId, displayTitle) => {
	const owner = __dshWindows.find(event.sender);
	if (owner === void 0) throw new Error("dsh desktop: rejected window request from an unowned renderer");
	if (typeof sessionId !== "string" || sessionId.length === 0 || sessionId.length > 200) throw new Error("dsh desktop: invalid session id");
	const window = await __dshWindows.open({ sessionId });
	if (window === void 0) throw new Error("dsh desktop: window limit reached");
	return { windowId: window.id };
});
ipcMain.handle("dsh-desktop:show-session-menu", async (event, sessionId, displayTitle, x, y) => {
	const owner = __dshWindows.find(event.sender);
	if (owner === void 0) return null;
	if (typeof sessionId !== "string" || sessionId.length === 0 || sessionId.length > 200) return null;
	let label = "Open in new window";
	try {
		label = currentDesktopLocale().messages.openInNewWindow ?? label;
	} catch {}
	const suffix = typeof displayTitle === "string" && displayTitle.trim().length > 0 ? ": " + displayTitle.trim().slice(0, 60) : "";
	return await new Promise((resolve) => {
		let chosen = null;
		Menu.buildFromTemplate([{
			id: "open-in-new-window",
			label: label + suffix,
			click: () => {
				chosen = "open-in-new-window";
			}
		}]).popup({
			window: owner,
			x: Number.isFinite(x) ? Math.round(x) : void 0,
			y: Number.isFinite(y) ? Math.round(y) : void 0,
			callback: () => resolve(chosen)
		});
	});
});
""")

WS_FIND = (
    "if (hostUrl === void 0 || hostCookie === void 0 || "
    "details.webContentsId !== mainWindow?.webContents.id) {"
)
WS_REPLACE = (
    "if (hostUrl === void 0 || hostCookie === void 0 || "
    "__dshWindows.find(WebContents.fromId(details.webContentsId)) === void 0) {"
)

# ═════════════════════════════════════════════════════════════════════════════
# lib/preload-app.cjs
# ═════════════════════════════════════════════════════════════════════════════
PRELOAD_FIND = 'electron.contextBridge.exposeInMainWorld("dshDesktop", location.protocol === `dsh-app:` && location.hostname === "app" && process.isMainFrame ? createProductApi() : { protocolVersion: 1 });'
PRELOAD_REPLACE = PRELOAD_FIND + body("""
electron.contextBridge.exposeInMainWorld(`dshSessionWindow`, {
	/**
	* Show the Desktop-owned session menu at a point and, when the user picks it,
	* open the Session in a second application window.
	* @param sessionId - Session the row represents.
	* @param displayTitle - optional row title, shown in the menu line.
	* @param x - viewport x of the originating click.
	* @param y - viewport y of the originating click.
	* @returns the chosen action id, or null when nothing was chosen.
	*/
	contextMenu: (sessionId, displayTitle, x, y) => {
		if (location.protocol !== `dsh-app:` || location.hostname !== `app` || process.isMainFrame !== true) return Promise.resolve(null);
		if (typeof sessionId !== `string` || sessionId.length === 0 || sessionId.length > 200) return Promise.resolve(null);
		return electron.ipcRenderer.invoke(
			`dsh-desktop:show-session-menu`,
			sessionId,
			String(displayTitle ?? ``),
			Number(x),
			Number(y)
		).then((action) => {
			if (action !== `open-in-new-window`) return action;
			return electron.ipcRenderer.invoke(
				`dsh-desktop:open-session-window`,
				sessionId,
				String(displayTitle ?? ``)
			).then(() => `open-in-new-window`, () => null);
		}, () => null);
	},
	/**
	* Subscribe to "reveal this Session here", sent once a window opened by the
	* shell has finished loading.
	* @param listener - receives the Session id.
	* @returns an unsubscribe function.
	*/
	onOpenSession(listener) {
		if (location.protocol !== `dsh-app:` || location.hostname !== `app` || process.isMainFrame !== true) return () => {};
		const handle = (_event, sessionId) => {
			if (typeof sessionId === `string` && sessionId.length > 0) listener(sessionId);
		};
		electron.ipcRenderer.on(`dsh-desktop:open-session`, handle);
		return () => {
			electron.ipcRenderer.off(`dsh-desktop:open-session`, handle);
		};
	}
});
""")

SPECS = {
    "main.js": {
        "asar_path": "/lib/main.js",
        "edits": [
            {"id": "import-webcontents", "find": IMPORT_FIND, "replace": IMPORT_REPLACE},
            {"id": "window-registry-and-factory", "find": REGISTRY_FIND, "replace": REGISTRY_REPLACE},
            {"id": "session-window-ipc", "find": IPC_FIND, "replace": IPC_REPLACE},
            {"id": "ws-cookie-any-app-window", "find": WS_FIND, "replace": WS_REPLACE},
        ],
    },
    "preload-app.cjs": {
        "asar_path": "/lib/preload-app.cjs",
        "edits": [
            {"id": "session-window-bridge", "find": PRELOAD_FIND, "replace": PRELOAD_REPLACE},
        ],
    },
}


def main() -> None:
    total = 0
    for entry, spec in SPECS.items():
        out = PATCH_DIR / f"{entry}.json"
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"=== {entry} -> {out.name}")
        for edit in spec["edits"]:
            delta = len(edit["replace"]) - len(edit["find"])
            total += delta
            print(f"    {edit['id']:<32} +{delta} bytes")
    print(f"\nspecs written; total inserted {total} bytes")


if __name__ == "__main__":
    main()

