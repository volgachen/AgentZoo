"""WeChat bridge runtime plugin for AgentZoo.

This plugin follows the local WeChatBot usage shown in
E:/Projects/AgentZoo/wechat/example.py:

    bot = WeChatBot()

    @bot.on_message
    async def handle(msg):
        ...

    bot.run()

Important: QR-code login is handled by WeChatBot() initialization, so this plugin
does not request a separate AgentZoo startup interaction for login.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any

from wechatbot import WeChatBot


@dataclass
class Binding:
    wechat_user_id: str
    session_id: str


@dataclass
class PluginConfig:
    command_prefix: str = r"\cmd"
    default_session_id: str | None = None
    bindings: list[Binding] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "PluginConfig":
        raw = os.getenv("AGENTZOO_PLUGIN_CONFIG", "{}")
        data = json.loads(raw)
        return cls(
            command_prefix=data.get("command_prefix") or r"\cmd",
            default_session_id=data.get("default_session_id"),
            bindings=[
                Binding(
                    wechat_user_id=item["wechat_user_id"],
                    session_id=item["session_id"],
                )
                for item in data.get("bindings", [])
                if item.get("wechat_user_id") and item.get("session_id")
            ],
        )

    def session_for_wechat_user(self, wechat_user_id: str) -> str | None:
        for binding in self.bindings:
            if binding.wechat_user_id == wechat_user_id:
                return binding.session_id
        return self.default_session_id

    def wechat_users_for_session(self, session_id: str) -> list[str]:
        return [
            binding.wechat_user_id
            for binding in self.bindings
            if binding.session_id == session_id
        ]


class AgentZooHost:
    """Placeholder for the future AgentZoo plugin protocol.

    The runner currently records stdout/stderr as logs. The next protocol step is
    for the runner to treat structured stdout frames as actions and stdin frames
    as events. Keeping this behind AgentZooHost makes the WeChat logic stable
    while the host protocol evolves.
    """

    async def send_session_message(self, session_id: str, content: str, *, source: str) -> None:
        action = {
            "type": "action",
            "action": "session.message.send",
            "data": {
                "session_id": session_id,
                "content": content,
                "source": source,
            },
        }
        print(json.dumps(action, ensure_ascii=False), flush=True)


def plain_text_content(content: Any) -> str | None:
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict) and isinstance(parsed.get("content"), str):
            return parsed["content"]
        return content
    if isinstance(content, dict) and isinstance(content.get("content"), str):
        return content["content"]
    return None


class WeChatBridgePlugin:
    def __init__(self, config: PluginConfig) -> None:
        self.config = config
        # WeChatBot() performs QR-code login as part of initialization.
        self.bot = WeChatBot()
        self.host = AgentZooHost()
        self._stop = asyncio.Event()
        self._last_wechat_user_id: str | None = None
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.bot.on_message
        async def handle(msg):
            await self.on_wechat_message(
                wechat_user_id=msg.user_id,
                text=msg.text,
                raw_message=msg,
            )

    async def run(self) -> None:
        print("wechat-bridge starting", flush=True)
        print(f"instance_id={os.getenv('AGENTZOO_PLUGIN_INSTANCE_ID')}", flush=True)
        print(f"run_id={os.getenv('AGENTZOO_PLUGIN_RUN_ID')}", flush=True)
        print(f"config={self.config}", flush=True)
        print("wechat-bridge delegating to WeChatBot.run()", flush=True)
        bot_task = asyncio.create_task(asyncio.to_thread(self.bot.run))
        stdin_task = asyncio.create_task(self._stdin_event_loop())
        done, pending = await asyncio.wait(
            {bot_task, stdin_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                raise exc

    async def on_wechat_message(self, *, wechat_user_id: str, text: str, raw_message: Any) -> None:
        print(f"收到消息，user_id = {wechat_user_id}", flush=True)
        print(f"消息内容 = {text}", flush=True)
        self._last_wechat_user_id = wechat_user_id

        if text.startswith(self.config.command_prefix):
            await self.handle_command(
                wechat_user_id=wechat_user_id,
                text=text,
                raw_message=raw_message,
            )
            return

        session_id = self.config.session_for_wechat_user(wechat_user_id)
        if not session_id:
            await self.bot.send(
                wechat_user_id,
                "No AgentZoo session is bound for this WeChat user.",
            )
            print(
                f"no target session for wechat user={wechat_user_id}; message ignored",
                flush=True,
            )
            return

        await self.host.send_session_message(
            session_id,
            text,
            source=f"wechat:{wechat_user_id}",
        )

    async def handle_command(self, *, wechat_user_id: str, text: str, raw_message: Any) -> None:
        parts = text.strip().split()
        command = parts[1] if len(parts) >= 2 else "help"

        if command == "status":
            session_id = self.config.session_for_wechat_user(wechat_user_id)
            await self.bot.send(
                wechat_user_id,
                f"AgentZoo WeChat bridge is running. Current session: {session_id or 'not bound'}",
            )
            return

        if command == "help":
            await self.bot.send(
                wechat_user_id,
                f"Commands: {self.config.command_prefix} status",
            )
            return

        # Future command examples:
        #   \cmd session <session_id>
        #   \cmd bind <session_id>
        # Those require a persistent config update action from the plugin host.
        await self.bot.send(wechat_user_id, f"Unknown command: {command}")

    async def _stdin_event_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                print(f"ignored non-json stdin frame: {line.rstrip()}", flush=True)
                continue
            if frame.get("type") != "event":
                continue
            event = frame.get("event") or {}
            if event.get("type") == "message.created":
                await self.on_agentzoo_message_created(event)

    async def on_agentzoo_message_created(self, event: dict[str, Any]) -> None:
        """Handle AgentZoo message.created events from stdin."""
        print(f"received AgentZoo event: {event.get('type')} source={event.get('source')}", flush=True)
        source = event.get("source")
        if source == f"plugin:{os.getenv('AGENTZOO_PLUGIN_INSTANCE_ID')}":
            print("ignored self-originated event", flush=True)
            return

        data = event.get("data", {})
        if data.get("role") != "agent":
            print(f"ignored non-agent message role={data.get('role')}", flush=True)
            return

        session_id = data.get("session_id")
        if (
            self.config.default_session_id
            and session_id != self.config.default_session_id
        ):
            print(
                f"ignored agent reply from session={session_id}; "
                f"default_session_id={self.config.default_session_id}",
                flush=True,
            )
            return

        content = data.get("content")
        if not content:
            print("ignored message.created without content", flush=True)
            return
        text = plain_text_content(content)
        if not text:
            print("ignored empty agent text", flush=True)
            return
        if not self._last_wechat_user_id:
            print("no last WeChat user; reply ignored", flush=True)
            return

        print(
            f"forwarding agent reply to last wechat user={self._last_wechat_user_id}",
            flush=True,
        )
        await self.bot.send(self._last_wechat_user_id, text)


async def async_main() -> None:
    config = PluginConfig.from_env()
    plugin = WeChatBridgePlugin(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, plugin._stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    await plugin.run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
