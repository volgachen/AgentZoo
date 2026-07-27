# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers the AgentZoo **frontend only** — a React 19 + Vite + TypeScript + Tailwind dashboard that talks to the FastAPI backend. The repo-root `../CLAUDE.md` covers the backend and full-stack architecture; read this file for frontend-isolated work.

## Common commands

Run from `frontend/`:

```bash
npm install
npm run dev        # Vite dev server on :12599, host: true (LAN-reachable)
npm run build      # tsc -b && vite build
npm run lint       # eslint . (flat config)
npm run preview    # serve the built bundle
```

There is no test suite. The build does `tsc -b` first, so type errors fail the build — fix them, don't suppress them.

## Running without the backend

The UI has no mock layer. Every page call reaches the backend at `http://<current-hostname>:12598`. For any non-trivial change, start the backend (see `../backend/` — `uvicorn app.main:app --host 0.0.0.0 --port 12598`) before `npm run dev`, otherwise the Agent Registry and session flows render empty/error states.

If you need to work offline on pure presentation, stub `api` in `src/api/client.ts` locally — don't commit it.

## Architecture

### Backend URL is derived, never hardcoded
`src/api/client.ts` builds `API_HOST` from `window.location.hostname` plus port `12598`. That's what makes the app work on any LAN IP without a rebuild. **Do not** introduce `localhost`, `127.0.0.1`, or an env-baked URL in fetch/WS calls — keep the hostname dynamic. Vite's `server.host: true` in `vite.config.ts` is the dev-time counterpart.

### Single Zustand store owns sessions and sockets
`src/store/sessions.ts` is the only place that opens WebSockets and mutates session state. Components read via selectors (`useStore((s) => …)`) and call actions (`launchSession`, `sendMessage`, `resolveConfirm`, `closeSession`, `refreshSession`). Don't open `new WebSocket(...)` inside a component — route it through the store so the socket lifecycle, event buffer, and session entry stay in one place.

Each `SessionEntry` holds `{ session, events: StreamEvent[], socket, generating, tasks, pendingConfirms }`. Incoming frames are appended to `events`; a `tool_confirm` frame is also pushed onto `pendingConfirms` (the interactive approve/deny queue) and cleared when its `tool_result` or a terminal frame arrives; `onclose` refreshes the session record from REST so the UI sees the final status.

### Wire protocol mirrors the backend
`src/api/types.ts` is the canonical TS mirror of the backend's Pydantic models. When the backend changes a model (new `AgentType`, new `StreamEventType`, added field), update `types.ts` in the same change — the two files are a contract, not independent.

- **WS inbound** (server → client): `{ type: StreamEventType, data: string }` plus a `session_state` frame sent on connect. `StreamEventType` is `"text" | "tool_call" | "tool_confirm" | "tool_result" | "status" | "error" | "done" | "user"`.
- **WS outbound** (client → server): either a user turn `{ content: string }` or a tool decision `{ decision: "approve" | "deny", call_id: string }` answering a `tool_confirm`. The backend drives the agent loop; the client sends one message per turn and waits for a `done` event, approving/denying any `tool_confirm` in between. Note the decision values are the strings `"approve"`/`"deny"`, though the `resolveConfirm(sessionId, callId, approved)` action takes a boolean and maps it.

### Pages own their own presentation
Routes are declared wherever `App.tsx` is wired (top nav: Agent Registry, Sessions, Plugins). Pages live in `src/pages/` — `AgentRegistry.tsx`, `SessionDashboard.tsx`, `LiveConsole.tsx`, `PluginRegistry.tsx`, `PluginConsole.tsx`. `src/components/` holds reusable pieces (`AgentDetailModal`, `WorkingDirPicker`, `TaskListPanel`, `SubAgentListPanel`, `ActiveSessionsMenu`); extract into it only when a piece of UI is reused across pages, not preemptively. `App.tsx` is the shell: a top nav of `NavLink`s (Agent Registry, Sessions, Plugins) plus `ActiveSessionsMenu` and an `<Outlet />`.

### Styling
Tailwind v3 (not v4) via PostCSS + `tailwind.config.js`. The app is dark-themed (`bg-gray-950`, `text-gray-100` on the shell). Prefer Tailwind utility classes; avoid adding CSS modules or a second styling system.

## Conventions

- React 19 + strict TS. Prefer function components and hooks; no class components.
- ESLint flat config (`eslint.config.js`) with `react-hooks` and `react-refresh` plugins — respect the hooks rules, don't disable them locally.
- Router: `react-router-dom` v7. `App.tsx` is the shell with `<Outlet />`; nested routes live under it.
- State: Zustand only. Don't pull in Redux/Jotai/Context-based global state.
- Keep `api/client.ts` the single fetch/WebSocket entry point. Page/store code imports from `api`, not `fetch` directly.