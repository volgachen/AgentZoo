"""WeChat bridge runtime plugin for Augentia.

This plugin follows the local WeChatBot usage shown in
E:/Projects/Augentia/wechat/example.py:

    bot = WeChatBot()

    @bot.on_message
    async def handle(msg):
        ...

    bot.run()

Important: QR-code login is handled by WeChatBot() initialization, so this plugin
does not request a separate Augentia startup interaction for login.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
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
        raw = os.getenv("AUGENTIA_PLUGIN_CONFIG", "{}")
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


@dataclass
class SessionBotState:
    session_id: str
    status: str = "Not Connected"
    message: str = "Click Connect to login."
    bot: WeChatBot | None = None
    task: asyncio.Task[None] | None = None
    last_wechat_user_id: str | None = None
    qr_url: str | None = None
    error: str | None = None


class AugentiaHost:
    """Placeholder for the future Augentia plugin protocol.

    The runner currently records stdout/stderr as logs. The next protocol step is
    for the runner to treat structured stdout frames as actions and stdin frames
    as events. Keeping this behind AugentiaHost makes the WeChat logic stable
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
        self.host = AugentiaHost()
        self._stop = asyncio.Event()
        self._session_states: dict[str, SessionBotState] = {}

    async def run(self) -> None:
        print("wechat-bridge starting", flush=True)
        print(f"instance_id={os.getenv('AUGENTIA_PLUGIN_INSTANCE_ID')}", flush=True)
        print(f"run_id={os.getenv('AUGENTIA_PLUGIN_RUN_ID')}", flush=True)
        print(f"config={self.config}", flush=True)
        try:
            await self._stdin_event_loop()
        finally:
            for session_id in list(self._session_states):
                await self._disconnect_session(session_id)

    async def on_wechat_message(
        self,
        *,
        session_id: str,
        wechat_user_id: str,
        text: str,
        raw_message: Any,
    ) -> None:
        print(f"收到消息，session_id={session_id} user_id={wechat_user_id}", flush=True)
        print(f"消息内容 = {text}", flush=True)
        state = self._session_state(session_id)
        state.last_wechat_user_id = wechat_user_id

        if text.startswith(self.config.command_prefix):
            await self.handle_command(
                session_id=session_id,
                wechat_user_id=wechat_user_id,
                text=text,
                raw_message=raw_message,
            )
            return

        await self.host.send_session_message(
            session_id,
            text,
            source=f"wechat:{wechat_user_id}",
        )

    async def handle_command(
        self,
        *,
        session_id: str,
        wechat_user_id: str,
        text: str,
        raw_message: Any,
    ) -> None:
        parts = text.strip().split()
        command = parts[1] if len(parts) >= 2 else "help"
        state = self._session_state(session_id)
        bot = state.bot
        if bot is None:
            return

        if command == "status":
            await bot.send(
                wechat_user_id,
                f"Augentia WeChat bridge is connected to session: {session_id}",
            )
            return

        if command == "help":
            await bot.send(
                wechat_user_id,
                f"Commands: {self.config.command_prefix} status",
            )
            return

        await bot.send(wechat_user_id, f"Unknown command: {command}")

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
            frame_type = frame.get("type")
            if frame_type == "event":
                event = frame.get("event") or {}
                if event.get("type") == "message.created":
                    await self.on_augentia_message_created(event)
                continue
            if frame_type == "command":
                await self.on_command(frame)
                continue

    def emit_session_log(self, session_id: str, line: str, *, level: str = "info") -> None:
        frame = {
            "type": "plugin_log",
            "data": {
                "session_id": session_id,
                "level": level,
                "line": line,
            },
        }
        print(json.dumps(frame, ensure_ascii=False), flush=True)

    def _session_state(self, session_id: str) -> SessionBotState:
        state = self._session_states.get(session_id)
        if state is None:
            state = SessionBotState(session_id=session_id)
            self._session_states[session_id] = state
        return state

    def _state_data(self, state: SessionBotState) -> dict[str, Any]:
        data: dict[str, Any] = {
            "session_id": state.session_id,
            "status": state.status,
            "message": state.message,
        }
        if state.qr_url:
            data["qr_url"] = state.qr_url
        if state.error:
            data["error"] = state.error
        return data

    def _cred_path(self, session_id: str) -> str:
        root = Path(os.getenv("AUGENTIA_PLUGIN_ROOT") or ".")
        return str(root / ".state" / "sessions" / session_id / "credentials.json")

    async def _connect_session(self, session_id: str) -> SessionBotState:
        state = self._session_state(session_id)
        if state.status in {"Connected", "Connecting", "Waiting QR Login"}:
            return state

        state.status = "Connecting"
        state.message = "Connecting..."
        state.error = None
        state.qr_url = None
        self.emit_session_log(session_id, "connecting")
        state.task = asyncio.create_task(self._login_and_run_session_bot(state))
        return state

    async def _login_and_run_session_bot(self, state: SessionBotState) -> None:
        session_id = state.session_id

        def on_qr_url(qr_url: str) -> None:
            state.status = "Waiting QR Login"
            state.qr_url = qr_url
            state.message = f"请扫码登录：{qr_url}"
            self.emit_session_log(session_id, f"QR login required: {qr_url}")

        def on_scanned() -> None:
            state.message = "QR scanned. Confirm login in WeChat."
            self.emit_session_log(session_id, "QR scanned")

        def on_expired() -> None:
            state.message = "QR expired. Waiting for a refreshed QR code."
            self.emit_session_log(session_id, "QR expired", level="warning")

        def on_error(exc: Exception) -> None:
            state.status = "Error"
            state.error = str(exc)
            state.message = f"Error: {exc}"
            self.emit_session_log(session_id, f"bot error: {exc}", level="error")

        bot = WeChatBot(
            cred_path=self._cred_path(session_id),
            on_qr_url=on_qr_url,
            on_scanned=on_scanned,
            on_expired=on_expired,
            on_error=on_error,
        )

        @bot.on_message
        async def handle(msg):
            await self.on_wechat_message(
                session_id=session_id,
                wechat_user_id=msg.user_id,
                text=msg.text,
                raw_message=msg,
            )

        try:
            await bot.login()
            state.bot = bot
            state.status = "Connected"
            state.message = "Click to disconnect"
            state.qr_url = None
            state.error = None
            self.emit_session_log(session_id, "session connected")
            await bot.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.status = "Error"
            state.error = str(exc)
            state.message = f"Error: {exc}"
            self.emit_session_log(session_id, f"connect failed: {exc}", level="error")

    async def _disconnect_session(self, session_id: str) -> SessionBotState:
        state = self._session_state(session_id)
        self.emit_session_log(session_id, "disconnecting")
        if state.bot is not None:
            state.bot.stop()
        if state.task is not None:
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
        state.bot = None
        state.task = None
        state.status = "Not Connected"
        state.message = "Click Connect to login."
        state.qr_url = None
        state.error = None
        self.emit_session_log(session_id, "session disconnected")
        return state

    async def on_command(self, frame: dict[str, Any]) -> None:
        command_id = frame.get("id")
        command = frame.get("command")
        data = frame.get("data") or {}
        if not isinstance(command_id, str):
            return
        session_id = data.get("session_id")
        if command in {"session_dialog.status", "session_dialog.input"} and not isinstance(session_id, str):
            response = {
                "type": "response",
                "id": command_id,
                "ok": False,
                "error": "session_id is required",
            }
            print(json.dumps(response, ensure_ascii=False), flush=True)
            return

        if command == "session_dialog.status":
            response = {
                "type": "response",
                "id": command_id,
                "ok": True,
                "data": self._state_data(self._session_state(session_id)),
            }
        elif command == "session_dialog.input":
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                response = {
                    "type": "response",
                    "id": command_id,
                    "ok": False,
                    "error": "text is required",
                }
            else:
                normalized = text.strip().lower()
                self.emit_session_log(session_id, f"operator input: {text.strip()}")
                if normalized in {"connect", "login"}:
                    state = await self._connect_session(session_id)
                elif normalized == "disconnect":
                    state = await self._disconnect_session(session_id)
                else:
                    state = self._session_state(session_id)
                    self.emit_session_log(
                        session_id,
                        f"unknown input: {text.strip()}; use connect or disconnect",
                        level="warning",
                    )
                response = {
                    "type": "response",
                    "id": command_id,
                    "ok": True,
                    "data": self._state_data(state),
                }
        else:
            response = {
                "type": "response",
                "id": command_id,
                "ok": False,
                "error": f"unsupported command: {command}",
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)

    async def on_augentia_message_created(self, event: dict[str, Any]) -> None:
        """Handle Augentia message.created events from stdin."""
        print(f"received Augentia event: {event.get('type')} source={event.get('source')}", flush=True)
        source = event.get("source")
        if source == f"plugin:{os.getenv('AUGENTIA_PLUGIN_INSTANCE_ID')}":
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
        if not isinstance(session_id, str):
            print("ignored message.created without session_id", flush=True)
            return
        state = self._session_state(session_id)
        if state.bot is None or state.status != "Connected":
            print(f"session={session_id} is not connected; reply ignored", flush=True)
            return
        if not state.last_wechat_user_id:
            print(f"session={session_id} has no last WeChat user; reply ignored", flush=True)
            return

        print(
            f"forwarding agent reply session={session_id} to wechat user={state.last_wechat_user_id}",
            flush=True,
        )
        await state.bot.send(state.last_wechat_user_id, text)


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
