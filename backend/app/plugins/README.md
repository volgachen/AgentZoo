# AgentZoo 插件系统

插件系统用于给 AgentZoo 增加后台能力、外部集成和 Agent 工具能力。当前第一阶段重点支持 `system_side` 插件：由 AgentZoo 托管、可启动/停止/观察的本地后台插件进程。

## 插件作用域

插件按作用域分为三类：

- `system_side`：系统侧插件。作用于整个 AgentZoo 后台，不绑定某一个 session，例如微信桥接、邮箱监听、定时任务、webhook 监听。
- `session_side`：会话侧插件。只插入某个 session 的运行过程，不影响整个系统，例如 Codex/OpenClaw、某个 session 专用 MCP、prompt/skill 包或临时工具能力。
- `hybrid`：混合插件。既有系统侧后台实例，又能给 session 提供能力。

当前代码优先实现 `system_side`。

`scope` 表示插件影响范围；`entry.type` 表示插件如何被加载或启动；`capabilities` 表示插件需要或提供的能力。

## 插件定义

插件定义不进数据库，而是从本地目录动态扫描：

```text
plugins/
  wechat-bridge/
    plugin.json
    README.md
    src/main.py
```

每个插件目录必须包含 `plugin.json`。示例：

```json
{
  "id": "wechat-bridge",
  "name": "WeChat Bridge",
  "version": "0.1.0",
  "scope": "system_side",
  "provider": "agentzoo",
  "entry": {
    "type": "python",
    "main": "src/main.py"
  },
  "capabilities": ["background", "network", "wechat_login"],
  "subscriptions": ["message.created"],
  "actions": ["session.message.send"],
  "default_config": {
    "command_prefix": "\\cmd",
    "default_session_id": null,
    "bindings": []
  },
  "session": {
    "selectable": false,
    "default_enabled": false
  }
}
```

后端通过 `PluginCatalog` 扫描 `plugins/*/plugin.json`，API 暴露：

```text
GET /api/v1/plugins/catalog
GET /api/v1/plugins/catalog/{plugin_id}
```

## 数据库模型

插件定义来自文件系统。数据库只记录用户创建的实例、每次运行和日志。

```text
plugin_instances
plugin_runs
plugin_logs
```

`plugin_instances` 表示一个长期存在的插件实例，例如“我的微信转发”。它保存：

- `plugin_id`：对应本地 manifest 的 id。
- `display_name`：用户给实例起的名字。
- `config`：实例配置。
- `auto_start`：是否后端启动时自动启动。
- `status`：当前状态。
- `current_run_id`：当前或最近一次运行。

`plugin_runs` 表示一次启动运行。每次启动插件实例都会创建一条 run，保存：

- `plugin_instance_id`
- `plugin_id`
- `status`
- `config_snapshot`
- `started_at`
- `running_at`
- `exited_at`
- `exit_code`
- `error`

`plugin_logs` 表示某次运行产生的日志，挂在 `plugin_run_id` 上。

## 状态

当前插件状态统一使用：

```text
stopped
starting
waiting_input
running
stopping
exited
errored
cancelled
```

第一阶段主要使用：

```text
stopped -> starting -> running -> exited/errored
```

`waiting_input` 是为未来启动交互保留，例如二维码、验证码、确认框等。

## Runtime 插件的运行方式

Runtime 插件被看作 AgentZoo 托管的本地后台进程。它有点像微服务，但不是独立部署服务：

```text
AgentZoo backend
  -> 扫描 plugin.json
  -> 创建 plugin_instance
  -> 创建 plugin_run
  -> 启动插件子进程
  -> 收集 stdout/stderr
  -> 持久化 plugin_logs
  -> 管理状态
```

当前支持的 entry：

```json
{
  "entry": {
    "type": "python",
    "main": "src/main.py"
  }
}
```

启动插件时，Runner 会给子进程传入环境变量：

```text
AGENTZOO_PLUGIN_ID
AGENTZOO_PLUGIN_INSTANCE_ID
AGENTZOO_PLUGIN_RUN_ID
AGENTZOO_PLUGIN_ROOT
AGENTZOO_PLUGIN_CONFIG
```

插件代码可以通过 `AGENTZOO_PLUGIN_CONFIG` 读取实例配置。

## 插件协议

第一阶段使用 stdio JSON Lines 协议。

AgentZoo 通过 stdin 向插件发送事件：

```json
{
  "type": "event",
  "event": {
    "id": "event-id",
    "type": "message.created",
    "source": "agentzoo",
    "data": {
      "session_id": "...",
      "role": "agent",
      "content": "..."
    }
  }
}
```

插件通过 stdout 请求 AgentZoo 执行动作：

```json
{
  "type": "action",
  "action": "session.message.send",
  "data": {
    "session_id": "...",
    "content": "...",
    "source": "wechat:user-id"
  }
}
```

Runner 对 stdout 的处理规则：

- 如果一行是合法 JSON 且 `type == "action"`，交给 `PluginActionDispatcher`。
- 其他 stdout 行作为普通日志保存。
- stderr 永远作为日志保存。

当前已支持的 action：

```text
session.message.send
```

它会把插件消息送进目标 session：

- 如果目标 session 有 live runner，调用 `runner.submit()`。
- 如果没有 live runner，先写入数据库为 user message。

插件来源会标记为：

```text
from_session_id = plugin:{plugin_instance_id}
```

## 事件 Hook

当前已支持的事件：

```text
message.created
```

消息写入数据库后，后端发布 `message.created`。事件总线会查找：

- 正在运行的插件实例。
- 插件 manifest 的 `subscriptions` 是否包含该事件。

匹配后，Runner 通过 stdin 把事件发送给插件进程。

第一阶段事件投递是 best-effort：

- 只投递给当前运行中的插件。
- 不做持久化队列。
- 不做失败重试。
- 不保证插件离线期间补发。

## 回环防护

第一阶段采用最小回环防护：

- 插件产生的消息来源标记为 `plugin:{instance_id}`。
- 微信插件只转发 `role == "agent"` 的 `message.created`。
- 微信插件忽略 `source == plugin:{自己的 instance_id}` 的事件。

这可以避免“微信用户消息进入 session 后又被插件发回微信”的基础回环。

## 微信桥接插件

当前示例插件位于：

```text
plugins/wechat-bridge/
```

它基于 `E:\Projects\AgentZoo\wechat\example.py` 中的用法：

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

重要约定：扫码登录包含在 `WeChatBot()` 初始化过程中，所以微信插件不需要额外向前端请求二维码交互。

微信插件当前流程：

```text
AgentZoo 启动 plugin instance
  -> Runner 启动 plugins/wechat-bridge/src/main.py
  -> WeChatBot() 初始化并处理扫码登录
  -> bot.run() 开始 long-poll
  -> @bot.on_message 收到微信消息
  -> 普通消息输出 session.message.send action
  -> AgentZoo action dispatcher 把消息送进 session
  -> Agent 回复写入数据库
  -> message.created 事件发送给微信插件 stdin
  -> 微信插件调用 bot.send() 发回绑定用户
```

微信插件配置示例：

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

控制命令以 `command_prefix` 开头，例如：

```text
\cmd status
\cmd help
```

未来可以扩展：

```text
\cmd session <session_id>
\cmd bind <session_id>
```

这些需要插件 host 支持持久化更新 instance config。

## 当前 API

插件 catalog：

```text
GET /api/v1/plugins/catalog
GET /api/v1/plugins/catalog/{plugin_id}
```

插件实例：

```text
GET    /api/v1/plugins/instances
POST   /api/v1/plugins/instances
GET    /api/v1/plugins/instances/{instance_id}
PUT    /api/v1/plugins/instances/{instance_id}
DELETE /api/v1/plugins/instances/{instance_id}
```

生命周期：

```text
POST /api/v1/plugins/instances/{instance_id}/start
POST /api/v1/plugins/instances/{instance_id}/stop
POST /api/v1/plugins/instances/{instance_id}/restart
```

运行记录：

```text
GET /api/v1/plugins/instances/{instance_id}/runs
GET /api/v1/plugins/runs/{run_id}
```

日志：

```text
GET /api/v1/plugins/runs/{run_id}/logs
GET /api/v1/plugins/instances/{instance_id}/logs
WS  /api/v1/plugins/instances/{instance_id}/stream
```

## Codex/OpenClaw 插件的兼容方向

Codex/OpenClaw 这类插件通常属于 `session_side`，用于给某个 session 增加工具能力或 skill，而不是作为全局后台服务运行。

长期目标是统一安装目录和 manifest：

```text
plugins/codex-chrome/plugin.json
plugins/openclaw-browser/plugin.json
```

但底层运行方式不同：

- `system_side` 插件由 `plugin_instances/plugin_runs` 管理生命周期。
- `session_side` 插件在创建 session 时选择，注入 prompt、注册 tools 或启动 session-scoped MCP/Node runtime。
- `hybrid` 插件两边都可能使用，既可以有后台实例，也可以被某些 session 选择启用。

第一阶段不实现 session 启动时选择 Codex/OpenClaw 插件。

## 暂缓事项

为了先跑通可用闭环，以下内容暂缓：

- 可靠事件投递、持久化事件队列和重试。
- 插件自动重启策略、退避和最大重启次数。
- 外部服务断线重连。
- 通用启动交互协议。
- 细粒度权限模型。
- secrets 独立存储。
- 插件 action 审计表。
- plugin_logs 保留策略。
- manifest 热加载。
- HTTP 插件 transport。
- session-scoped `session_side` 插件选择。

这些也记录在 `app/plugins/TODO.md`。
