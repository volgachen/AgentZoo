# Plugin TODO

The first implementation is intentionally scoped to a usable local loop: start a runtime plugin, dispatch plugin actions, and deliver basic platform events.

Deferred items:

- Reliable event delivery with persisted event queues and retry tracking.
- Plugin auto-restart policies, exponential backoff, and max restart limits.
- Full disconnect/reconnect handling for external services such as WeChat.
- Interactive startup protocol for plugins that cannot handle login internally.
- Fine-grained plugin permissions and action allowlists per instance.
- Secrets storage separate from normal plugin config.
- Session-scoped tool-provider plugins such as Codex/OpenClaw selection at session startup.
- Persistent plugin action audit table.
- Log retention policies for `plugin_logs`.
- Hot reload of `plugins/*/plugin.json` without backend restart.
- HTTP plugin transport. The default transport remains stdio JSON lines.
