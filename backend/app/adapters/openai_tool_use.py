import json
import logging
import os
from typing import AsyncGenerator
from openai import AsyncOpenAI
from app.adapters.base import BaseAgentAdapter, StreamEvent, StreamEventType
import app.adapters.tools  # noqa: F401 — triggers tool registration
from app.adapters.tools.registry import load_tools
from app.adapters.tools.base import BaseTool

logger = logging.getLogger("agentzoo.adapter.tool_use")


class OpenAIToolUseAdapter(BaseAgentAdapter):
    def __init__(
        self,
        tool_names: list[str],
        model: str = "gpt-4o",
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._tool_names = tool_names
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
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
        if system_prompt:
            self._messages = [{"role": "system", "content": system_prompt}]
        self._alive = True
        logger.info(
            "started model=%s base_url=%s tools=%s",
            self._model, base_url, [t.name for t in self._tools],
        )

    async def send(self, message: str) -> None:
        self._pending = message

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

        logger.info("turn complete iters=%d", loop_iter)
        yield StreamEvent(type=StreamEventType.DONE, data="")

    async def stop(self) -> None:
        self._alive = False
        self._client = None

    @property
    def is_alive(self) -> bool:
        return self._alive
