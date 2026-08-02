from __future__ import annotations

from typing import Any

from app.db.seed_browser import browser_agent_template as _browser_agent
from app.models.domain import AgentTemplate, AgentType

_INFORMATION_SEARCHER_PROMPT = (
    "You are a information searcher specialized in gathering, vetting, and synthesizing "
    "information from the web. Your job is to find high-quality sources and deliver "
    "actionable research reports.\n\n"
    "## Core workflow\n"
    "1. **Understand the request** — clarify scope, time constraints, and required "
    "depth before searching. If anything is ambiguous, ask before proceeding.\n"
    "2. **Search broadly** — use web_search to cast a wide net. Run multiple "
    "searches with different angles and keywords. Prefer authoritative domains "
    "(.edu, .gov, official docs, reputable publications).\n"
    "3. **Read deeply** — use web_fetch on the most promising results. Never "
    "summarize from search snippets alone — always read the source.\n"
    "4. **Cross-verify** — key claims should be confirmed by at least 2 "
    "independent sources. Flag contradictions or outlier claims explicitly.\n"
    "5. **Record** — use write to save your findings as a structured markdown "
    "file. Use edit to refine and update your notes as new information "
    "comes in. Use read to review previously saved materials.\n"
    "6. **Deliver** — Deliver the results as required. If the task requires to save "
    "the information, just do it following the required file struture and format. "
    "If the task requires a feedback report, send your report to the requesting "
    "session via session_send.\n\n"
    "## Rules\n"
    "- Never fabricate URLs or cite a source you haven't fetched.\n"
    "- When web_fetch fails, report it — don't guess what was on the page.\n"
    "- If you find contradictory information, present both sides.\n"
    "- Structure long reports with clear headings for readability."
)

_SEARCH_TOOLS = [
    "web_search",
    "web_fetch",
    "arxiv_search",
    "session_send",
    "write",
    "read",
    "edit",
]

SEED_AGENT_ROWS: list[dict[str, Any]] = [
    {
        "id": "main-agent",
        "name": "Main Agent",
        "description": "一个通用的智能体，配备了多种工具，能够处理各种任务。",
        "agent_type": "tool_use",
        "system_prompt": _INFORMATION_SEARCHER_PROMPT,
        "tool_names": _SEARCH_TOOLS,
        "openai_model": "gpt-5.5",
        "openai_base_url": None,
    },
    {
        "id": "information_searcher",
        "name": "Information Searcher",
        "description": "通过网络搜索、论文检索、网页抓取等工具搜集资料，整理为结构化研究报告。",
        "agent_type": "tool_use",
        "system_prompt": _INFORMATION_SEARCHER_PROMPT,
        "tool_names": _SEARCH_TOOLS,
        "openai_model": "gpt-5.5",
        "openai_base_url": None,
    },
    {
        "id": "agent-claude-code-001",
        "name": "Claude Code Agent",
        "description": "驱动 Claude Code CLI 完成复杂编程与脚本生成任务。",
        "agent_type": "claude_code",
        "system_prompt": "You are a coding assistant powered by Claude Code.",
        "tool_names": [],
        "openai_model": "claude-sonnet",
        "openai_base_url": None,
    },
    _browser_agent().model_dump(
        include={
            "id", "name", "description", "agent_type", "system_prompt",
            "tool_names", "config", "openai_model", "openai_base_url",
        }
    ) | {"agent_type": "tool_use"},
]


def seed_agent_templates() -> list[AgentTemplate]:
    return [
        AgentTemplate(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            agent_type=AgentType(row["agent_type"]),
            system_prompt=row["system_prompt"],
            tool_names=list(row.get("tool_names", [])),
            config=dict(row.get("config", {})),
            openai_model=row.get("openai_model", "gpt-4o"),
            openai_base_url=row.get("openai_base_url"),
        )
        for row in SEED_AGENT_ROWS
    ]
