# Backend test scripts

Standalone scripts for verifying backend behavior. Run from `backend/`:

```bash
python scripts/<name>.py
```

Each exits 0 on success, nonzero on failure — so they compose in CI or a shell loop.

## Needs `uvicorn app.main:app` running

| Script | What it checks | External deps |
|---|---|---|
| `test_rest_api.py` | REST round-trip: health, list agents, create/get/delete session, messages | backend only |
| `test_ws_claude_code.py` | Full WS round-trip with Claude Code adapter; two turns to verify `--resume` continuity | backend + `claude` CLI in PATH |
| `test_ws_tool_use.py` | Full WS round-trip with tool-use adapter; asserts `TOOL_CALL` + `TEXT` events | backend + `OPENAI_*` in `.env` |

## No backend needed

| Script | What it checks | External deps |
|---|---|---|
| `test_tools_direct.py` | Each registered tool's `.execute()` returns non-empty output | network (arxiv, duckduckgo) |
| `test_tool_bash.py` | `bash` tool branches: normal, timeout, truncation, background | none |
| `test_adapter_claude_code.py` | `ClaudeCodeAdapter` lifecycle in isolation, two turns | `claude` CLI in PATH |
| `test_adapter_tool_use.py` | `OpenAIToolUseAdapter` lifecycle in isolation, with tool calls | `OPENAI_*` in `.env` |

## Env overrides

- `AGENTZOO_BASE_URL` — override `http://localhost:12598` for the WS/REST scripts.
- `AGENTZOO_AGENT_ID` — override the seed agent used by `test_rest_api.py`.
