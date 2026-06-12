import json
import logging
import os
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.adapters.base import BaseAgentAdapter, StreamEvent, StreamEventType
from app.models.domain import Message, MessageRole
import app.adapters.tools  # noqa: F401 — triggers tool registration
from app.adapters.tools.registry import load_tools
from app.adapters.tools.base import BaseTool

logger = logging.getLogger("agentzoo.adapter.tool_use")

# Tool results can be large (e.g. a fetched web page). The full result still
# goes to the LLM context (_messages); only the persisted/broadcast copy in the
# TOOL_RESULT event is truncated.
_TOOL_RESULT_MAX = 8000


class OpenAIToolUseAdapter(BaseAgentAdapter):
    def __init__(
        self,
        tool_names: list[str],
        model: str = "gpt-4o",
        base_url: str | None = None,
        api_key: str | None = None,
        session_id: str | None = None,
        working_dir: str | None = None,
    ) -> None:
        super().__init__(session_id)
        self._tool_names = tool_names
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        # Pass-through to filesystem tools so bash/read/write/edit run in the
        # session's working_dir instead of the backend process's cwd. The
        # ClaudeCode adapter handles this naturally by spawning the CLI with
        # cwd=working_dir; tool-use has to thread it into each tool itself.
        self._working_dir = working_dir
        self._tools: list[BaseTool] = []
        self._messages: list[dict] = []
        self._pending: str | None = None
        self._alive = False
        self._client: AsyncOpenAI | None = None

    async def start(self, system_prompt: str) -> None:
        base_url = self._base_url or os.getenv("OPENAI_BASE_URL")
        api_key = self._api_key or os.getenv("OPENAI_API_KEY")
        self._model = self._model if self._model != "gpt-4o" else os.getenv("OPENAI_MODEL", self._model)
        kwargs: dict = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        self._client = AsyncOpenAI(**kwargs)
        self._tools = load_tools(self._tool_names)
        for t in self._tools:
            t.session_id = self.session_id
            t.working_dir = self._working_dir
        if system_prompt:
            self._messages = [{"role": "system", "content": system_prompt}]
        self._alive = True
        logger.info(
            "started model=%s base_url=%s tools=%s",
            self._model, base_url, [t.name for t in self._tools],
        )

    async def send(self, message: str) -> None:
        self._pending = message

    async def restore_history(self, messages: list[Message]) -> None:
        """Rebuild conversation context after a backend restart, using OpenAI's
        native tool roles.

        Persisted rows use our own vocabulary (user/agent/tool_call/tool) and we
        never stored OpenAI's tool_call_id. The runner always writes each
        TOOL_CALL immediately followed by its TOOL result, in order, so we
        re-pair them by adjacency and synthesize a stable id — producing a valid
        assistant(tool_calls) -> tool(tool_call_id) sequence the API accepts.
        Two fidelity limits: tool results were truncated to _TOOL_RESULT_MAX when
        persisted, and a turn interrupted before its result was stored gets a
        placeholder response so the tool_call still has a match. The system
        prompt seeded in start() is preserved (SYSTEM rows aren't persisted).
        """
        restored: list[dict] = []
        i = 0
        n = len(messages)
        call_seq = 0
        while i < n:
            m = messages[i]
            if m.role == MessageRole.USER:
                restored.append({"role": "user", "content": m.content})
                i += 1
            elif m.role == MessageRole.AGENT:
                restored.append({"role": "assistant", "content": m.content})
                i += 1
            elif m.role == MessageRole.TOOL_CALL:
                name, arguments = self._parse_persisted_tool_call(m.content)
                call_id = f"restored_call_{call_seq}"
                call_seq += 1
                restored.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }],
                })
                # The matching result is the next row, unless the turn was
                # interrupted before it was persisted — then synthesize one so
                # the tool_call isn't left dangling (the API requires a response).
                result = "[result not recorded]"
                if i + 1 < n and messages[i + 1].role == MessageRole.TOOL:
                    result = self._parse_persisted_tool_result(messages[i + 1].content)
                    i += 1
                restored.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                })
                i += 1
            elif m.role == MessageRole.TOOL:
                # Orphan result with no preceding call — can't attach a tool role
                # without a matching id, so keep it as plain assistant context.
                restored.append({
                    "role": "assistant",
                    "content": f"[previous tool result] {m.content}",
                })
                i += 1
            else:
                i += 1
        self._messages.extend(restored)
        logger.info(
            "restored %d history rows -> %d context messages (total=%d)",
            n, len(restored), len(self._messages),
        )

    @staticmethod
    def _parse_persisted_tool_call(content: str) -> tuple[str, str]:
        # TOOL_CALL rows store json.dumps({"name", "args"}); OpenAI wants the
        # arguments back as a JSON string.
        try:
            obj = json.loads(content)
            return obj.get("name", "unknown"), json.dumps(obj.get("args", {}))
        except (json.JSONDecodeError, TypeError, AttributeError):
            return "unknown", "{}"

    @staticmethod
    def _parse_persisted_tool_result(content: str) -> str:
        # TOOL rows store json.dumps({"name", "result"}); fall back to the raw
        # string if it isn't the expected shape.
        try:
            obj = json.loads(content)
            return obj.get("result", content) if isinstance(obj, dict) else content
        except json.JSONDecodeError:
            return content

    async def stream(self) -> AsyncGenerator[StreamEvent, None]:
        if self._pending is None or self._client is None:
            return

        self._messages.append({"role": "user", "content": self._pending})
        logger.debug("user turn: %r", self._pending)
        self._pending = None

        tool_schemas = [t.to_openai_schema() for t in self._tools]
        tool_map = {t.name: t for t in self._tools}
        loop_iter = 0

        while True:
            loop_iter += 1
            call_kwargs: dict = {
                "model": self._model,
                "messages": self._messages,
            }
            if tool_schemas:
                call_kwargs["tools"] = tool_schemas

            logger.info("chat.completions iter=%d msg_count=%d", loop_iter, len(self._messages))
            try:
                response = await self._client.chat.completions.create(**call_kwargs)
            except Exception as e:
                logger.exception("chat.completions failed")
                yield StreamEvent(type=StreamEventType.ERROR, data=f"LLM call failed: {e}")
                return

            # A correctly-spec'd Chat Completions endpoint returns a ChatCompletion
            # object. Some OpenAI-compatible gateways (e.g. Codex/Responses-style
            # backends whose base_url is .../codex/v1) don't implement
            # /chat/completions and hand back a raw string body instead, which the
            # SDK passes through unparsed — `response` is then a str and indexing
            # .choices raises AttributeError. Fail loudly with a useful message.
            if not hasattr(response, "choices"):
                logger.error(
                    "endpoint did not return a ChatCompletion (got %s): %r",
                    type(response).__name__, response,
                )
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    data=(
                        "LLM endpoint did not return a Chat Completions response. "
                        "Check that OPENAI_BASE_URL points at an OpenAI-compatible "
                        "/chat/completions endpoint (not a Codex/Responses backend)."
                    ),
                )
                return

            choice = response.choices[0]
            msg = choice.message
            self._messages.append(msg.model_dump(exclude_unset=False))
            logger.debug(
                "assistant reply: content_len=%s tool_calls=%d finish=%s",
                len(msg.content) if msg.content else 0,
                len(msg.tool_calls or []),
                choice.finish_reason,
            )

            if msg.content:
                yield StreamEvent(type=StreamEventType.TEXT, data=msg.content)

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                logger.info("tool call: %s args=%s", fn_name, fn_args)

                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL,
                    data=json.dumps({"name": fn_name, "args": fn_args}),
                )

                tool = tool_map.get(fn_name)
                if tool is None:
                    result = f"Error: tool '{fn_name}' not found"
                    logger.warning("tool %s not in map (available=%s)", fn_name, list(tool_map))
                else:
                    try:
                        result = await tool.execute(**fn_args)
                        logger.debug("tool %s result len=%d", fn_name, len(result))
                    except Exception as e:
                        logger.exception("tool %s raised", fn_name)
                        result = f"Error executing {fn_name}: {e}"

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

                result_view = (
                    result[:_TOOL_RESULT_MAX] + "\n...[truncated]"
                    if len(result) > _TOOL_RESULT_MAX
                    else result
                )
                yield StreamEvent(
                    type=StreamEventType.TOOL_RESULT,
                    data=json.dumps({"name": fn_name, "result": result_view}),
                )

        logger.info("turn complete iters=%d", loop_iter)
        yield StreamEvent(type=StreamEventType.DONE, data="")

    async def stop(self) -> None:
        self._alive = False
        self._client = None

    @property
    def is_alive(self) -> bool:
        return self._alive
