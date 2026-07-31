# Augentia 插件系统

插件系统用于给 Augentia 增加后台能力、外部集成和 Agent 工具能力。当前第一阶段重点支持 `system_side` 插件：由 Augentia 托管、可启动/停止/观察的本地后台插件进程。

## 插件作用域

插件按作用域分为三类：

- `system_side`：系统侧插件。作用于整个 Augentia 后台，不绑定某一个 session，例如微信桥接、邮箱监听、定时任务、webhook 监听。
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
  "provider": "augentia",
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

Runtime 插件被看作 Augentia 托管的本地后台进程。它有点像微服务，但不是独立部署服务：

```text
Augentia backend
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
AUGENTIA_PLUGIN_ID
AUGENTIA_PLUGIN_INSTANCE_ID
AUGENTIA_PLUGIN_RUN_ID
AUGENTIA_PLUGIN_ROOT
AUGENTIA_PLUGIN_CONFIG
```

插件代码可以通过 `AUGENTIA_PLUGIN_CONFIG` 读取实例配置。

## 插件协议

第一阶段使用 stdio JSON Lines 协议。

Augentia 通过 stdin 向插件发送事件：

```json
{
  "type": "event",
  "event": {
    "id": "event-id",
    "type": "message.created",
    "source": "augentia",
    "data": {
      "session_id": "...",
      "role": "agent",
      "content": "..."
    }
  }
}
```

插件通过 stdout 请求 Augentia 执行动作：

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

它基于 `E:\Projects\Augentia\wechat\example.py` 中的用法：

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
Augentia 启动 plugin instance
  -> Runner 启动 plugins/wechat-bridge/src/main.py
  -> WeChatBot() 初始化并处理扫码登录
  -> bot.run() 开始 long-poll
  -> @bot.on_message 收到微信消息
  -> 普通消息输出 session.message.send action
  -> Augentia action dispatcher 把消息送进 session
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

## 前端改造建议

前端需要基于 `scope` 区分插件入口位置：

- `system_side`：进入后台插件管理页面，支持创建实例、启动/停止、查看状态和日志。
- `session_side`：进入创建 session 页面，作为本次 session 的可选能力。第一阶段后端还未实现，可以先只在 UI 设计里预留。
- `hybrid`：同时出现在后台插件管理和创建 session 页面。

第一阶段建议先实现 `system_side` 插件管理。

### 页面结构

建议新增一个插件管理入口，例如：

```text
/plugins
```

页面可以分成三个区域：

```text
Installed Plugins     # 来自 /plugins/catalog
Plugin Instances      # 来自 /plugins/instances
Instance Detail       # 状态、runs、logs、配置
```

`Installed Plugins` 展示本地已安装插件定义：

- `name`
- `id`
- `version`
- `scope`
- `provider`
- `description`
- `capabilities`
- `subscriptions`
- `actions`

对于 `scope == "system_side"` 或 `scope == "hybrid"` 的插件，显示“创建实例”按钮。

`Plugin Instances` 展示已经创建的实例：

- `display_name`
- `plugin_id`
- `status`
- `auto_start`
- `current_run_id`
- `created_at`
- `updated_at`

每个实例需要操作按钮：

```text
Start
Stop
Restart
Edit Config
Delete
View Logs
View Runs
```

按钮状态建议按实例状态控制：

```text
stopped/exited/errored/cancelled -> 可以 Start / Edit / Delete
starting/waiting_input/running/stopping -> 禁止 Edit / Delete
running -> 可以 Stop / Restart
```

### API 调用流程

页面加载时：

```text
GET /api/v1/plugins/catalog
GET /api/v1/plugins/instances
```

创建实例时：

```text
POST /api/v1/plugins/instances
```

请求体：

```json
{
  "plugin_id": "wechat-bridge",
  "display_name": "我的微信转发",
  "config": {
    "command_prefix": "\\cmd",
    "default_session_id": "session-id",
    "bindings": []
  },
  "auto_start": false
}
```

启动实例：

```text
POST /api/v1/plugins/instances/{instance_id}/start
```

停止实例：

```text
POST /api/v1/plugins/instances/{instance_id}/stop
```

重启实例：

```text
POST /api/v1/plugins/instances/{instance_id}/restart
```

更新实例配置：

```text
PUT /api/v1/plugins/instances/{instance_id}
```

查看运行历史：

```text
GET /api/v1/plugins/instances/{instance_id}/runs
```

查看日志：

```text
GET /api/v1/plugins/instances/{instance_id}/logs
GET /api/v1/plugins/runs/{run_id}/logs
```

实时日志和状态流：

```text
WS /api/v1/plugins/instances/{instance_id}/stream
```

WebSocket 当前会发送：

```json
{"type":"plugin_instance_state","data":{...}}
{"type":"log","data":{"ts":"...","stream":"stdout","line":"..."}}
{"type":"status","data":{"status":"running","run_id":"..."}}
```

### 状态展示

前端应统一识别这些状态：

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

建议视觉语义：

- `running`：正常运行。
- `starting` / `stopping`：进行中。
- `waiting_input`：等待用户操作，第一阶段暂时不会触发。
- `exited`：已正常退出。
- `errored`：错误，需要展示 `plugin_runs.error` 或日志中的 stderr。
- `cancelled`：用户取消。

### 日志界面

日志界面建议支持：

- 按 `stream` 区分 `stdout/stderr/system/event`。
- 默认打开当前实例的实时日志流。
- 可以切换查看历史 run 日志。
- stderr 和 system error 使用更醒目的样式。
- 日志列表需要虚拟滚动或至少限制最大渲染行数。

第一阶段不需要做日志搜索、下载、清理和保留策略。

### 微信插件配置 UI

`wechat-bridge` 的配置可以先做成表单：

```text
Display Name
Auto Start
Command Prefix
Default Session
Bindings
```

`Default Session` 应该从现有 session 列表中选择，保存为 `default_session_id`。

`Bindings` 是多行配置：

```text
wechat_user_id    session_id
```

其中 `session_id` 也应该从 session 列表选择。`wechat_user_id` 第一阶段可以让用户手动输入，因为当前插件会在日志里打印：

```text
收到消息，user_id = ...
```

用户可以先启动插件、给微信发一条消息、从日志里复制 `user_id`，再回到配置里添加绑定。

更好的后续体验是：前端从插件日志或未来的 structured event 中识别最近出现的微信用户，提供“一键绑定到 session”。

### 创建实例后的推荐操作流

微信插件第一版操作流：

```text
1. 打开 Plugins 页面。
2. 在 Installed Plugins 找到 WeChat Bridge。
3. 创建实例，填写 default_session_id 或 bindings。
4. 点击 Start。
5. WeChatBot() 初始化并处理扫码登录。
6. 在日志中确认 Logged in 和 Long-poll started。
7. 从微信发消息。
8. 插件输出 session.message.send action。
9. 目标 session 的 Agent 回复后，插件收到 message.created 并 bot.send 回微信。
```

如果没有 live session runner，插件消息会先写入数据库，但不会触发 Agent 继续回复。前端需要提示：

```text
目标 session 必须是 live/running 状态，插件消息才能触发 Agent 回复。
```

### session_side 插件的前端预留

未来创建 session 页面可以增加插件选择区：

```text
Session Plugins
[ ] Codex Chrome
[ ] OpenClaw Browser
[ ] GitHub MCP
```

筛选条件：

```text
scope == "session_side" or scope == "hybrid"
session.selectable == true
```

第一阶段后端还没有 `session_plugins` 表，也没有 session 启动时加载插件的逻辑，所以前端可以先不实现，或者只在设计中预留区域。

### 错误处理

前端需要重点处理：

- `404`：插件定义或实例不存在，刷新 catalog/instances。
- `409`：实例正在运行，不能编辑或重复启动。
- 启动后很快 `errored`：自动打开日志，展示 stderr tail 或 run error。
- WebSocket 断开：回退到轮询 `GET /instances/{id}/logs`。

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
