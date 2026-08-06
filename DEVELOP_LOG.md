# 2026-08-05

- **Bash 使用 Git Bash 并修正 Windows CWD 接力**：`bash` 工具按 `AGENT_BASH_PATH`、系统 `PATH` 中的 `bash`、原默认 shell 顺序选择执行器。使用 Git Bash 时，CWD relay 的临时文件路径会在 Windows 原生格式与 `E:/...` drive-slash 格式之间转换，`pwd -P` 的结果也会规范化为 Windows drive-slash 路径，避免把 `/e/...` 形式直接传给 Python 的 `cwd`。
- **Claude Code BashTool 借鉴项记录**：已在 `TODO.md` 的 bash 工具章节记录可后续考虑的 shell 可执行性验证、跨工具共享 CWD、环境快照、实时输出、后台任务管理、自动后台化、命令级安全解析和 sandbox 等方向。

# 2026-08-04

- **工具权限系统第一版落地**：新增 `tool_permissions` 规则机制，支持 `read` / `write` / `edit` 基于路径的 `allow` / `deny` / `ask` 决策，并支持 `tool` / `tools` 两种工具选择写法。路径会按 session working directory 规范化，避免 `../` 绕过目录规则。
- **权限配置改为 session 级文件**：Tool Permissions 不再写入 agent template，而是保存到 `$AUGENTIA_HOME/sessions/{session_id}/config.json`，默认位置为 `~/.augentia/sessions/{session_id}/config.json`。创建或恢复 session runner 时会确保配置文件存在；前端保存后会立即 reload 当前 live adapter，使权限变更对当前会话即时生效。
- **Live Console 右侧栏重组**：右侧栏改为页签结构，`Overview` 中上下展示 Tasks 和 Sub-agents，另有 `Tool Permissions` 页签用于编辑当前 session 的权限配置。
- **Tool Permissions 规则测试器**：新增 `POST /api/v1/sessions/{session_id}/tool-permissions/test`，前端可以在 Tool Permissions 页签里选择 `read` / `write` / `edit` 并输入路径，查看当前规则的决策结果、命中规则和规范化后的绝对路径。
- **Bash 权限支持**：`tool_permissions` 现在支持 `bash` 简单命令规则，例如 `commands: ["rg *", "git status", "git diff *"]`，复合 shell 命令默认 ask。同时新增显式危险开关 `shell: "any"`，可对任意 bash 命令直接 allow，包括管道、重定向和复合命令。
- **System Prompt 页签**：Live Console 右侧新增 `System Prompt` 页签。后端提供 `GET /api/v1/sessions/{session_id}/system-prompt`，优先从 live adapter 内存里的 system message 读取当前会话真实 system prompt；没有 live adapter 时 fallback 到 agent prompt 与 session additional prompt 的重新拼接结果。

# 2026-08-03

- **插件系统完善**：新增 runtime plugin 的逐会话管理入口。插件可以在 manifest 中声明 `has_session_dialog`，当对应插件实例处于 running 状态时，会出现在每个会话行的 More 下拉列表中。点击后打开统一的 Plugin Session Console。逐会话插件窗口现在采用统一布局：顶部展示插件返回的当前会话状态，中间展示当前 session 对应的插件日志，底部展示插件返回的 `message` 指引文本和 Connect/Disconnect 操作按钮。同时新增 UI -> backend -> plugin process 的 command 通道。前端通过 `POST /api/v1/plugins/instances/{instance_id}/commands` 发送，后端通过 stdin 将 command 转发给插件进程，并等待插件 stdout 返回同 id 的 response。
- **微信插件可用**：`wechat-bridge` 现在按 session 维护独立的 bot/state 映射。每个会话默认是 Not Connected，点击 Connect 后在后台启动登录流程；如果已有 credentials 会直接进入 Connected，如果需要扫码则返回可点击的二维码登录地址。连接成功后，微信消息会转发到对应 Augentia session，Agent 回复也会按 session 路由回最近的微信联系人。
- **对话历史浏览体验优化**：现在可以利用键盘上下键翻阅对话历史，避免那种突然出现一长段消息还得手动拖到消息开头的尴尬体验。
- **浏览器外系统通知**：在获取权限后，允许 Augentia 将回复完成和工具确认的通知以系统消息的形式推送。