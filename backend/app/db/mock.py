from datetime import datetime, timezone
from typing import Dict, List
from app.db.interface import IAgentDatabase, _UNSET
from app.models.domain import (
    AgentTemplate, AgentType, Session, SessionStatus,
    Message, MessageRole,
    Plugin, PluginStatus,
    Task, TaskStatus,
)


_SEED_AGENTS = [
    AgentTemplate(
        id="agent-research-001",
        name="Research Agent",
        description="通过网络搜索、论文检索、网页抓取等工具搜集资料，整理为结构化研究报告。",
        agent_type=AgentType.TOOL_USE,
        system_prompt=(
            "You are a research agent specialized in gathering, vetting, and synthesizing "
            "information from the web. Your job is to find high-quality sources and deliver "
            "actionable research reports.\n\n"
            "## Core workflow\n"
            "1. **Understand the request** — clarify scope, time constraints, and required "
            "depth before searching. If anything is ambiguous, ask before proceeding.\n"
            "2. **Search broadly** — use web_search to cast a wide net. Run multiple "
            "searches with different angles and keywords. Prefer authoritative domains "
            "(.edu, .gov, official docs, reputable publications). For academic topics, "
            "use arxiv_search.\n"
            "3. **Read deeply** — use web_fetch on the most promising results. Never "
            "summarize from search snippets alone — always read the source.\n"
            "4. **Cross-verify** — key claims should be confirmed by at least 2 "
            "independent sources. Flag contradictions or outlier claims explicitly.\n"
            "5. **Record** — use write to save your findings as a structured markdown "
            "file. Use edit to refine and update your notes as new information "
            "comes in. Use read to review previously saved materials.\n"
            "6. **Deliver** — when the research is complete, send your report to the "
            "requesting session via session_send. Include key findings, evidence, "
            "sources, and confidence levels.\n\n"
            "## Output format for reports\n"
            "Every finding should include:\n"
            "- **Key finding** (1-2 sentences)\n"
            "- **Evidence** (what the source says, with quotes under 125 chars)\n"
            "- **Source** (URL + brief credibility note)\n"
            "- **Confidence** (High / Medium / Low — based on source quality and "
            "cross-verification)\n\n"
            "## Rules\n"
            "- Never fabricate URLs or cite a source you haven't fetched.\n"
            "- When web_fetch fails, report it — don't guess what was on the page.\n"
            "- If you find contradictory information, present both sides.\n"
            "- Structure long reports with clear headings for readability."
        ),
        tool_names=[
            "web_search", "web_fetch", "arxiv_search",
            "session_send", "write", "read", "edit",
        ],
    ),
    AgentTemplate(
        id="agent-claude-code-001",
        name="Claude Code Agent",
        description="驱动 Claude Code CLI 完成复杂编程与脚本生成任务。",
        agent_type=AgentType.CLAUDE_CODE,
        system_prompt="You are a coding assistant powered by Claude Code.",
    ),
]


class MockMemoryDatabase(IAgentDatabase):
    def __init__(self) -> None:
        self._agents: Dict[str, AgentTemplate] = {a.id: a for a in _SEED_AGENTS}
        self._sessions: Dict[str, Session] = {}
        self._messages: Dict[str, List[Message]] = {}
        self._plugins: Dict[str, Plugin] = {}
        # tasks keyed by task_list_id -> task_id -> Task
        self._tasks: Dict[str, Dict[str, Task]] = {}
        # monotonic per-list id counter; survives deletes (ids never reused)
        self._task_counters: Dict[str, int] = {}

    async def list_agents(self) -> List[AgentTemplate]:
        return list(self._agents.values())

    async def get_agent(self, agent_id: str) -> AgentTemplate:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent '{agent_id}' not found")
        return agent

    async def create_agent(self, template: AgentTemplate) -> AgentTemplate:
        self._agents[template.id] = template
        return template

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        tool_names: list[str] | None = None,
        openai_model: str | None = None,
        openai_base_url: str | None = None,
    ) -> AgentTemplate:
        agent = await self.get_agent(agent_id)
        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if system_prompt is not None:
            agent.system_prompt = system_prompt
        if tool_names is not None:
            agent.tool_names = tool_names
        if openai_model is not None:
            agent.openai_model = openai_model
        if openai_base_url is not None:
            agent.openai_base_url = openai_base_url
        return agent

    async def delete_agent(self, agent_id: str) -> None:
        await self.get_agent(agent_id)
        del self._agents[agent_id]

    async def create_session(
        self,
        agent_id: str,
        working_dir: str | None = None,
        *,
        parent_session_id: str | None = None,
    ) -> Session:
        await self.get_agent(agent_id)  # validate agent exists
        session = Session(
            agent_id=agent_id,
            working_dir=working_dir,
            parent_session_id=parent_session_id,
        )
        self._sessions[session.id] = session
        self._messages[session.id] = []
        return session

    async def get_session(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found")
        return session

    async def list_sessions(self) -> List[Session]:
        return list(self._sessions.values())

    async def update_session_status(self, session_id: str, status: SessionStatus) -> Session:
        session = await self.get_session(session_id)
        session.status = status
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        from_session_id: str | None = None,
    ) -> Message:
        await self.get_session(session_id)  # validate session exists
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            from_session_id=from_session_id,
        )
        self._messages[session_id].append(message)
        return message

    async def get_messages(self, session_id: str) -> List[Message]:
        await self.get_session(session_id)
        return list(self._messages[session_id])

    # ------- Plugins -------

    async def list_plugins(self) -> List[Plugin]:
        return list(self._plugins.values())

    async def get_plugin(self, plugin_id: str) -> Plugin:
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise KeyError(f"Plugin '{plugin_id}' not found")
        return plugin

    async def create_plugin(self, name: str, code: str) -> Plugin:
        plugin = Plugin(name=name, code=code)
        self._plugins[plugin.id] = plugin
        return plugin

    async def update_plugin(
        self,
        plugin_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
    ) -> Plugin:
        plugin = await self.get_plugin(plugin_id)
        if name is not None:
            plugin.name = name
        if code is not None:
            plugin.code = code
        plugin.updated_at = datetime.now(timezone.utc)
        return plugin

    async def delete_plugin(self, plugin_id: str) -> None:
        await self.get_plugin(plugin_id)
        del self._plugins[plugin_id]

    async def set_plugin_status(
        self,
        plugin_id: str,
        status: PluginStatus,
        *,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> Plugin:
        plugin = await self.get_plugin(plugin_id)
        now = datetime.now(timezone.utc)
        plugin.status = status
        if status == PluginStatus.RUNNING:
            plugin.last_started_at = now
            plugin.last_exited_at = None
            plugin.last_exit_code = None
            plugin.last_error = None
        else:
            plugin.last_exited_at = now
            if exit_code is not None:
                plugin.last_exit_code = exit_code
            if error is not None:
                plugin.last_error = error
        plugin.updated_at = now
        return plugin

    # ------- Tasks -------

    async def create_task(
        self,
        task_list_id: str,
        subject: str,
        description: str,
        *,
        active_form: str | None = None,
        metadata: dict | None = None,
    ) -> Task:
        next_id = self._task_counters.get(task_list_id, 0) + 1
        self._task_counters[task_list_id] = next_id
        task = Task(
            id=str(next_id),
            task_list_id=task_list_id,
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata,
        )
        self._tasks.setdefault(task_list_id, {})[task.id] = task
        return task

    async def get_task(self, task_list_id: str, task_id: str) -> Task | None:
        return self._tasks.get(task_list_id, {}).get(task_id)

    async def list_tasks(self, task_list_id: str) -> List[Task]:
        tasks = self._tasks.get(task_list_id, {})
        return sorted(tasks.values(), key=lambda t: int(t.id))

    async def update_task(
        self,
        task_list_id: str,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        status: TaskStatus | None = None,
        owner: str | None = _UNSET,
        metadata: dict | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> Task | None:
        task = self._tasks.get(task_list_id, {}).get(task_id)
        if task is None:
            return None

        if subject is not None:
            task.subject = subject
        if description is not None:
            task.description = description
        if active_form is not None:
            task.active_form = active_form
        if status is not None:
            task.status = status
        if owner is not _UNSET:
            task.owner = owner
        if metadata is not None:
            merged = dict(task.metadata or {})
            for k, v in metadata.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            task.metadata = merged or None

        # Reciprocal dependency wiring: A blocks B  <=>  B blockedBy A.
        for other_id in add_blocks or []:
            other = self._tasks.get(task_list_id, {}).get(other_id)
            if other is None:
                continue
            if other_id not in task.blocks:
                task.blocks.append(other_id)
            if task_id not in other.blocked_by:
                other.blocked_by.append(task_id)
        for other_id in add_blocked_by or []:
            other = self._tasks.get(task_list_id, {}).get(other_id)
            if other is None:
                continue
            if other_id not in task.blocked_by:
                task.blocked_by.append(other_id)
            if task_id not in other.blocks:
                other.blocks.append(task_id)

        task.updated_at = datetime.now(timezone.utc)
        return task

    async def delete_task(self, task_list_id: str, task_id: str) -> bool:
        tasks = self._tasks.get(task_list_id, {})
        if task_id not in tasks:
            return False
        del tasks[task_id]
        # Cascade: strip dangling references from every other task.
        for other in tasks.values():
            if task_id in other.blocks:
                other.blocks.remove(task_id)
            if task_id in other.blocked_by:
                other.blocked_by.remove(task_id)
        return True
