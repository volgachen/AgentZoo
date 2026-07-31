# WeChat Bridge

This is an Augentia runtime plugin that follows the `WeChatBot` usage shown in `E:\Projects\Augentia\wechat\example.py`.

```python
from wechatbot import WeChatBot

bot = WeChatBot()

@bot.on_message
async def handle(msg):
    print("收到消息，user_id =", msg.user_id)
    print("消息内容 =", msg.text)
    await bot.send(msg.user_id, "Hello" + msg.text)

bot.run()
```

## Important startup behavior

`WeChatBot()` performs QR-code login during initialization. The plugin therefore does not request a separate Augentia QR-code interaction during startup.

## Intended behavior

- Initialize `WeChatBot()`, which handles scan-login.
- Register `@bot.on_message` to receive WeChat messages.
- Treat messages starting with `command_prefix` as bridge commands.
- Forward normal WeChat messages into an Augentia session via the future `session.message.send` action.
- Subscribe to future `message.created` events and forward matching Agent replies back to WeChat via `bot.send()`.

## Example config

```json
{
  "command_prefix": "\\cmd",
  "default_session_id": "session-id",
  "bindings": [
    {
      "wechat_user_id": "wx-user-1",
      "session_id": "session-id"
    }
  ]
}
```

## Current behavior

The plugin can be started by Augentia as a Python runtime plugin if the `wechatbot` package is available in the backend Python environment. It logs incoming WeChat messages and emits structured JSON action frames for future Augentia host handling.

The backend runner does not yet consume those structured action frames, so message forwarding into sessions still requires the next plugin protocol step.
