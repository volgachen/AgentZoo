"""Seed template for the Chrome-controlling agent.

Defined here rather than inline in `_SEED_AGENTS` because its system prompt is
built at import time from the installed codex plugin's SKILL.md, and both
`db/mysql.py` and `db/mock.py` need the identical value.
"""

from app.adapters.node_repl.codex_skill import load_codex_skill_prompt
from app.models.domain import AgentTemplate, AgentType

_FALLBACK_PROMPT = (
    "You control a Chrome browser through the Codex bundled `chrome` plugin via "
    "the node_repl_js tool. The plugin could not be located on this machine at "
    "startup, so browser control is unavailable: tell the user the "
    "ChatGPT/Codex desktop app does not appear to be installed, and do not "
    "attempt to bootstrap."
)


def browser_agent_template() -> AgentTemplate:
    return AgentTemplate(
        id="agent-browser-chrome-001",
        name="Chrome Browser Agent",
        description="通过 Codex 自带的 chrome 插件驱动用户本机真实运行的 Chrome：导航、点击、输入、截图、读取页面内容。需要 ChatGPT/Codex 桌面端处于运行状态。",
        agent_type=AgentType.TOOL_USE,
        system_prompt=load_codex_skill_prompt("chrome", "control-chrome") or _FALLBACK_PROMPT,
        tool_names=[
            "node_repl_js",
            "node_repl_reset",
            "node_repl_add_module_dir",
            "read",
            "write",
        ],
        # node_repl_js stays gated (its class default): it is arbitrary code
        # execution AND the plugin's own confirmation layer is auto-accepted on
        # the host side, so TOOL_CONFIRM is the only human checkpoint on actions
        # taken in the user's logged-in browser.
        config={},
    )
