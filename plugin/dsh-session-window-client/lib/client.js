/** Open an existing Session in another DSH window; reuse the native row menu. */
window.__ModuleLoader__.load({
  id: 'dsh-session-window-client',
  factory(require) {
    const { createElement, useCallback, useEffect, useState } = require('react')
    const { MenuItemButton, Toast, IconRightUpOutlineRegular } = require('@deepseek-ai/dsh-client-ui-primitives')

    /** Dictionary namespace owned by this plugin. */
    const NS = 'dsh-session-window-client'

    /**
     * A Session id is `session-` followed by a UUID.
     *
     * Read off the session store on disk (`session-07a30b2c-662f-43e3-9384-...json`),
     * NOT the bare v4 UUID that A-08 question 9 assumed - that wrong pattern rejected
     * every real id. The bare form is still accepted so a future build that drops the
     * prefix keeps working.
     */
    const SESSION_ID = /^(?:session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

    /**
     * Row keys are `<kind>:<id>`, e.g. `session:session-07a30b2c-...`. The kind prefix
     * is also what tells a Session row apart from the Project row above it, which
     * carries a row key of its own.
     */
    const ROW_KEY = /^session:(.+)$/

    const PENDING_READ_MS = 5_000
    const LANDING_TOTAL_MS = 30_000
    const ACK_MS = 5_000
    /** Occurrence id of our entry, and the slot that hosts the row menu. */
    const ITEM_ID = 'open-in-new-window'
    const MENU_SLOT = 'sidebar.workspaces.session.menu.item'

    const zh = {
      'menu.openInNewWindow': '在新窗口中打开',
      'notice.openFailed': '无法在新窗口中打开该会话。',
      'notice.windowLimit': '窗口数量已达上限（8 个），请先关闭一些窗口。',
      'notice.timeout': '新窗口打开该会话超时，请重试。',
      'notice.notFound': '该会话不存在或已被删除。'
    }

    const en = {
      'menu.openInNewWindow': 'Open in new window',
      'notice.openFailed': 'Could not open that Session in a new window.',
      'notice.windowLimit': 'The window limit (8) is reached. Close some windows first.',
      'notice.timeout': 'Timed out opening that Session in the new window. Try again.',
      'notice.notFound': 'That Session no longer exists.'
    }

    const MESSAGES = {
      OPEN_FAILED: 'notice.openFailed',
      WINDOW_LIMIT: 'notice.windowLimit',
      TIMEOUT: 'notice.timeout',
      INVALID_SESSION: 'notice.notFound',
      SESSION_NOT_FOUND: 'notice.notFound'
    }

    const bridge = () => globalThis.dshSessionWindow
    const hasBridge = () => globalThis.dshSessionWindow?.version === 2
    const inFlight = () => (globalThis.__dshSessionWindowInFlight ??= new Set())

    // ── notices ──────────────────────────────────────────────────────────────

    let noticeSeq = 0
    const noticeState = { text: null, seq: 0 }
    const noticeListeners = new Set()

    /** Show one notice in the shell overlay. */
    function showNotice(text) {
      noticeState.text = text
      noticeState.seq = ++noticeSeq
      for (const listener of noticeListeners) listener(noticeState.seq)
    }

    /** Overlay host rendering the current notice as a Toast. */
    function SessionWindowNotice() {
      const [, setSeq] = useState(0)
      const [text, setText] = useState(noticeState.text)

      useEffect(() => {
        const listener = (seq) => {
          setSeq(seq)
          setText(noticeState.text)
        }
        noticeListeners.add(listener)
        return () => noticeListeners.delete(listener)
      }, [])

      const done = useCallback(() => setText(null), [])
      if (text === null) return null
      return createElement(Toast, { text, tone: 'danger', anchor: 'top-center', onDone: done })
    }

    // shortcut: native SessionRow markup only; update this selector if the sidebar changes.
    function openNativeMenu(event, sessions) {
      if (!hasBridge() || !(event.target instanceof Element)) return
      const row = event.target.closest('[data-row-key]')
      const match = ROW_KEY.exec(row?.getAttribute('data-row-key') ?? '')
      if (!match || !SESSION_ID.test(match[1]) || !row.className.includes('_sessionRow')) return
      if (!sessionIsKnown(sessions, match[1])) return
      // SessionRow renders the ellipsis anchor before the archive/pin action slot.
      const button = row.querySelector('[class*="_rowActions"] button')
      if (!button || button.disabled) return
      event.preventDefault()
      event.stopImmediatePropagation()
      button.focus()
      button.click()
    }

    // ── the menu entry itself ────────────────────────────────────────────────

    /** "Open in new window", rendered inside the host's own menu list. */
    function OpenInNewWindowItem(props) {
      const { sessionId, displayTitle, useMenuOpenState } = props
      const [, setMenuOpen] = useMenuOpenState()

      const onSelect = useCallback(() => {
        setMenuOpen(false)
        void requestWindow(sessionId, displayTitle)
      }, [sessionId, displayTitle, setMenuOpen])

      if (!hasBridge() || typeof sessionId !== 'string' || !SESSION_ID.test(sessionId)) return null
      return createElement(MenuItemButton, {
        icon: createElement(IconRightUpOutlineRegular),
        onSelect,
        children: props.t('menu.openInNewWindow')
      })
    }

    /** Ask the shell for a second window showing this Session. */
    function requestWindow(sessionId, displayTitle) {
      const entry = bridge()
      if (!entry || entry.version !== 2) return Promise.resolve()
      return Promise.resolve(entry.openSessionWindow(sessionId, displayTitle ?? ''))
        .then((result) => {
          if (result?.ok) return
          showNotice(MESSAGES[result?.code] ?? MESSAGES.OPEN_FAILED)
        })
        .catch(() => showNotice(MESSAGES.OPEN_FAILED))
    }

    // ── landing flow ─────────────────────────────────────────────────────────

    /** A failure carrying one of the shell's machine codes. */
    class LandingError extends Error {
      constructor(code) {
        super(code)
        this.name = 'LandingError'
        this.code = code
      }
    }

    /**
     * Race a promise against a deadline. Only used for the bounded pending read and
     * the bounded acknowledgement - never as a retry.
     */
    function withDeadline(promise, ms, onTimeout) {
      let timer
      const deadline = new Promise((_, reject) => {
        timer = setTimeout(() => reject(onTimeout()), ms)
      })
      return Promise.race([promise, deadline]).finally(() => clearTimeout(timer))
    }

    /** The session service, which owns the Host's session list. */
    function sessionsOf(ctx) {
      try {
        return ctx.get('sessions')
      } catch {
        return undefined
      }
    }

    /** True when the Host's session list already contains this Session. */
    function sessionIsKnown(sessions, sessionId) {
      const snapshot = sessions?.list?.getSnapshot?.()
      if (!snapshot?.byId) return false
      return snapshot.byId[sessionId] !== undefined
    }

    /**
     * Wait until the session list knows the target.
     *
     * Checks the current state first and only then subscribes, so an already-ready
     * window does not wait for an event that will never fire. The subscription is
     * released on every exit path.
     */
    function waitUntilKnown(sessions, sessionId, signal) {
      if (sessionIsKnown(sessions, sessionId)) return Promise.resolve()
      const subscribe = sessions?.list?.subscribe
      if (typeof subscribe !== 'function') return Promise.resolve()
      return new Promise((resolve, reject) => {
        let stop
        const finish = (error) => {
          try {
            stop?.()
          } catch {
            /* subscription already gone */
          }
          signal?.removeEventListener('abort', onAbort)
          if (error) reject(error)
          else resolve()
        }
        const onAbort = () => finish(new LandingError('TIMEOUT'))
        if (signal?.aborted) return finish(new LandingError('TIMEOUT'))
        signal?.addEventListener('abort', onAbort, { once: true })
        stop = subscribe(() => {
          if (sessionIsKnown(sessions, sessionId)) finish()
        })
        if (sessionIsKnown(sessions, sessionId)) finish()
      })
    }

    /** The session id the workspace service currently shows, when it exposes one. */
    function currentSessionId(uiWorkspace) {
      try {
        return uiWorkspace?.selection?.getSnapshot?.()?.sessionId ?? null
      } catch {
        return null
      }
    }

    /**
     * Drive this window to the Session the shell registered for it.
     *
     * Reads the pending target first, so a window without one (including the primary
     * window) stops immediately and never times out. Everything after the read lives
     * under one 30 s budget and the plugin's own lifetime.
     */
    async function runLanding(ctx, life) {
      const entry = bridge()
      if (!entry || entry.version !== 2) return

      let target
      try {
        target = await withDeadline(
          Promise.resolve(entry.getPendingTarget()),
          PENDING_READ_MS,
          () => new LandingError('TIMEOUT')
        )
      } catch {
        // Cannot tell whether this window had a target; the shell's own expiry and
        // its log are the backstop. Stay silent on purpose.
        return
      }
      if (!target || life.aborted) return

      const requestId = target.requestId
      const busy = inFlight()
      if (busy.has(requestId)) return
      busy.add(requestId)
      const release = () => busy.delete(requestId)
      life.addEventListener('abort', release, { once: true })

      try {
        if (target.expired) throw new LandingError('TIMEOUT')

        const deadline = new AbortController()
        const timer = setTimeout(() => deadline.abort(), LANDING_TOTAL_MS)
        const onLifeAbort = () => deadline.abort()
        life.addEventListener('abort', onLifeAbort, { once: true })

        try {
          const uiWorkspace = ctx.get('uiWorkspace')
          const sessions = sessionsOf(ctx)
          await waitUntilKnown(sessions, target.sessionId, deadline.signal)
          if (life.aborted) return
          if (deadline.signal.aborted) throw new LandingError('TIMEOUT')

          await Promise.resolve(uiWorkspace.openSession(target.sessionId))
          if (life.aborted) return
          if (deadline.signal.aborted) throw new LandingError('TIMEOUT')

          const shown = currentSessionId(uiWorkspace)
          // null means this build does not expose a current-session getter; the
          // switch itself not throwing is then the only available evidence.
          if (shown !== null && shown !== target.sessionId) throw new LandingError('OPEN_FAILED')
          if (deadline.signal.aborted) throw new LandingError('TIMEOUT')

          await withDeadline(
            Promise.resolve(entry.ackPendingTarget(requestId, 'opened')),
            ACK_MS,
            () => new LandingError('TIMEOUT')
          )
        } finally {
          clearTimeout(timer)
          life.removeEventListener('abort', onLifeAbort)
        }
      } catch (error) {
        if (life.aborted) return // unloaded or reloaded: stay silent, leave the target
        const code = error instanceof LandingError ? error.code : 'OPEN_FAILED'
        if (code !== 'TIMEOUT') showNotice(code)
        await withDeadline(
          Promise.resolve(entry.ackPendingTarget(requestId, 'failed', code)),
          ACK_MS,
          () => new LandingError('TIMEOUT')
        ).catch(() => {})
      } finally {
        life.removeEventListener('abort', release)
        if (!life.aborted) release()
      }
    }

    // ── plugin entry ─────────────────────────────────────────────────────────

    /** Client services this plugin needs before it can apply. */
    const inject = ['slots', 'locale']

    /**
     * Apply the client half.
     * @param ctx - client root context.
     */
    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'session-window: dictionaries')

      // Our entry, rendered inside whichever menu shows this slot list. order 350
      // places it between Fork (300) and Archive (400).
      //
      // No `inject` factory on the registration: the component needs nothing beyond
      // what the slot provides - `sessionId` and `displayTitle` from renderSlot, `t`
      // bound to this plugin's dictionary via `locale: NS`, and `useMenuOpenState`
      // from the slot's own hook declaration.
      ctx.slots.inject(MENU_SLOT, function* () {
        yield ctx.slots.register(
          { name: MENU_SLOT, id: ITEM_ID, order: 350, locale: NS },
          OpenInNewWindowItem
        )
      })

      ctx.slots.inject('shell.overlay', function* () {
        yield ctx.slots.register(
          { name: 'shell.overlay', id: 'session-window-notice', locale: NS },
          SessionWindowNotice
        )

      })

      ctx.effect(() => {
        const onContextMenu = (event) => openNativeMenu(event, sessionsOf(ctx))
        window.addEventListener('contextmenu', onContextMenu, true)
        return () => window.removeEventListener('contextmenu', onContextMenu, true)
      }, 'session-window: native right click')

      // One landing task per plugin instance, cancelled on unload or hot reload.
      ctx.effect(() => {
        const life = new AbortController()
        runLanding(ctx, life.signal).catch(() => {})
        return () => life.abort()
      }, 'session-window: landing')
    }

    return { inject, apply }
  }
})

