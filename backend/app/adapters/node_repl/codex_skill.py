"""Load a bundled codex plugin's SKILL.md into an agent system prompt.

The plugin ships its own operating instructions; rather than paraphrasing them
(they change between desktop-app versions), we inline the real file and prepend
the host-specific bits SKILL.md can't know: the resolved absolute plugin root and
the Augentia tool ids that stand in for `mcp__node_repl__js`.
"""

import os

from app.adapters.node_repl.registry import codex_plugin_root

_PREAMBLE = """You control the user's real Chrome browser through the Codex \
bundled `chrome` plugin, driven from a persistent Node.js REPL.

Host environment (this replaces what the skill below assumes):
- Plugin root: `{root}`. The skill's `<plugin root>` means exactly this path.
  Import with a file URL: `await import("file:///{root}/scripts/browser-client.mjs")`.
- The skill calls the Node REPL `js` tool `mcp__node_repl__js`. Here it is
  **`node_repl_js`**. `js_reset` is `node_repl_reset`, `js_add_node_module_dir`
  is `node_repl_add_module_dir`. These tools already exist — never "discover"
  them, and never report the browser as unavailable because of a tool name.
- `globalThis.nodeRepl` (including `nodeRepl.write`) is already installed by the
  host. Do not build or overwrite it.
- The plugin's `node_modules` paths are already registered. You do not need
  `node_repl_add_module_dir` for normal browser work.
- State persists across calls and turns in one session, but only on
  `globalThis`. A bare `const tab = ...` is gone by the next call — always
  assign to `globalThis.tab` / `globalThis.browser`.
- Prerequisite you cannot fix from here: the ChatGPT/Codex desktop app must be
  running with its Chrome extension connected. If bootstrap fails with no
  browsers found, say so plainly and ask the user to check the desktop app,
  rather than retrying indefinitely.

Practical notes learned from this host:
- `agent.browsers` is an API object (`list`/`get`/`getDefault`/`getForUrl`), not
  a map. `Object.keys()` on it is always `[]` and means nothing; use
  `await agent.browsers.list()`.
- `tabs.new({url})` ignores `url` — the tab lands on `about:blank`. Navigate
  with an explicit `await tab.goto(url)`.
- An empty `tabs.list()` is normal: you only see tabs your own session created.
  Start with `tabs.new({})`.
- `tab.content` has only `export`/`exportGsuite` — no `text()`. To read page
  text use `tab.playwright`.
- Navigation triggers a host confirmation. It is auto-approved, so treat every
  navigation as really happening in the user's logged-in browser: do not visit
  or act on anything beyond what the user asked for, and never read cookies,
  local storage, passwords, or session stores.

--- BEGIN {name} SKILL.md ---
{skill}
--- END {name} SKILL.md ---
"""


def load_codex_skill_prompt(plugin: str = "chrome", skill: str = "control-chrome") -> str | None:
    root = codex_plugin_root(plugin)
    if not root:
        return None
    path = os.path.join(root, "skills", skill, "SKILL.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        body = f.read()
    # str.replace, not str.format: SKILL.md contains literal JS braces like
    # `tabs.new({url})` that format() would read as fields.
    return (
        _PREAMBLE.replace("{root}", root.rstrip("/"))
        .replace("{name}", skill)
        .replace("{skill}", body)
    )
