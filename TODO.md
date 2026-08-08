# TODO

## subagent 工具

### `.env` 继承会带入父代理的身份变量（MY_SESSION_ID / PARENT_SESSION_ID）

**现状**：`subagent` 工具创建子 session 时，会读取父代理 `working_dir/.env` 的全部内容原样作为 `body.env` 传给创建接口（`backend/app/adapters/tools/subagent.py::_read_env`），用于让子代理继承父的运行时配置（`OPENAI_*`、`GATEWAY_URL` 等）。

**隐患**：父代理的 `.env` 里**一定**含有 `MY_SESSION_ID=<父id>`，可能还有 `PARENT_SESSION_ID=<爷爷id>`（创建父 session 时网关写入的）。路由（`backend/app/routers/sessions.py:108-114`）是**字符串拼接**而非按 key 去重：先写 `body.env`，再追加 `PARENT_SESSION_ID` / `MY_SESSION_ID`。结果子代理的 `.env` 里这两个 key 各出现两行：

```
MY_SESSION_ID=<父id>        ← 继承自父 .env（错误，污染）
...
MY_SESSION_ID=<子id>        ← 网关追加（正确）
```

最终取到哪个值**取决于消费方的解析语义**：
- `set -a; source .env` 或 python-dotenv（默认）→ 后者覆盖前者 → 取到子 id ✅
- "首次出现者胜" 的解析器 → 取到父 id ❌ → 子代理误判自己身份、回报给错误对象

即使覆盖正确，`.env` 留重复行也不雅、易在 debug 时误导。

**建议修法**：在 `_read_env`（或新增过滤步骤）里逐行读父 `.env`，**跳过 `MY_SESSION_ID` / `PARENT_SESSION_ID` 开头的行**再传给 `body.env`。这样身份变量只由网关注入一次，值必正确，无重复行，也不再依赖消费方"后者覆盖前者"的假设。

---

### 子代理 worktree 回收（git worktree remove）尚未实现

**现状**：`isolation="worktree"` 会用 `git worktree add -b subagent/<id>` 建立隔离工作区与分支，但**没有回收逻辑**——worktree 目录与分支会一直留在磁盘上。

**待办**：在 session 终止生命周期（适配器 / 路由层，子代理 DONE/ERROR 时）挂钩，执行 `git worktree remove`，**保留分支**（交付策略为父代理自行 `git merge subagent/<id>`）。涉及适配器/路由生命周期，不在工具层。

---

## bash 工具

### CWD 接力只作用于 bash 自身，未跨工具共享

**现状**：`bash` 工具已实现 CWD 接力（`backend/app/adapters/tools/bash.py`）——每条前台命令在解析到 Bash 执行器时被包装成 `<命令>` → `__az_rc=$?` → `pwd -P > 侧文件` → `exit $__az_rc`，命令跑完读回侧文件、校验是真实目录后更新实例状态 `self._cwd`，下一条 bash 命令的 `cwd=` 即用此值。这样 `cd subdir` 能延续到下一次 bash 调用。退出码先存后还原（`[exit code: N]` 头不受影响），`pwd -P` 写侧文件而非 stdout（返回输出不变）。Windows + Git Bash 下会把侧文件路径从 `E:\...` 转为 `E:/...` 注入 shell，并把 `pwd -P` 返回的 `E:/...` 或 `/e/...` 规范化为 Windows drive-slash 路径。

**局限**：
1. **不跨工具**：`self._cwd` 挂在 bash 工具实例上，只影响后续 bash 调用。`read`/`write`/`edit` 是各自独立的工具实例，仍用静态 `working_dir` 解析相对路径——bash 里的 `cd` 不改变它们的基准目录。Claude Code 那边 cwd 是**全局**的（`setCwd` 影响所有工具）。
2. **依赖 Bash 执行器**：包装器用 sh 语法（`$?`、`pwd -P`）。如果 `AGENT_BASH_PATH` 和 `PATH` 都找不到 Bash，工具会回退到原默认 shell，并跳过 CWD 接力以避免 cmd.exe 解析错误。
3. **不跨重启**：状态在工具实例内存里，后端重启即丢，回退到 session 的静态 `working_dir`（与 Claude Code"重启即丢"边界一致）。

**建议修法（若需跨工具）**：引入一个**会话级共享 cwd store**（按 `session_id` 键控，可挂在 `SessionRunner` 或一个轻量单例上），bash 接力后写入、`read`/`write`/`edit` 的 `resolve_path` 改为优先读该 store 再回退 `working_dir`。注意并发：同一 session 的工具调用本就被 runner 串行化，store 无需加锁。

**仍未解决（与 Claude Code 同）**：`source venv/bin/activate`、命令内 `export FOO=bar` 等"shell 进程内部未导出的状态"依然不跨命令延续——这是无状态 spawn 架构的固有边界。Claude Code 的对应缓解是启动期 ShellSnapshot（dump `.bashrc` 的 alias/function/PATH）+ `/env` 显式注入；我们目前两者都未实现，可作为后续增强项。

### Claude Code BashTool 可借鉴但尚未实现的增强项

- **Shell 可执行性验证**：解析 `AGENT_BASH_PATH` 或 `PATH` 中的 `bash` 后，用短超时执行 `bash --version` 验证它确实可启动，避免缓存损坏或不可执行的 shell 路径。
- **CWD 异常恢复**：如果当前 `cwd` 被命令删除，下一次执行前应恢复到 session 初始 `working_dir` 或返回明确错误，而不是让 spawn 抛出底层异常。
- **实时输出进度**：前台长命令可以把输出持续写入任务文件，并通过事件流给前端推送最近输出、总行数和总字节数，而不是只在命令结束后返回。
- **后台任务管理**：`run_in_background` 可升级为有任务 ID、可查询输出、可终止、完成通知的长期任务，而不只是返回日志文件路径。
- **自动后台化**：长时间阻塞的前台命令可以在阈值后自动转后台，保持主会话可继续响应。该功能依赖完整后台任务管理。
- **命令级安全解析**：借鉴 Claude Code 的 AST 解析和权限规则，将审批粒度从“是否允许 bash 工具”提升到“是否允许这条具体命令”，区分只读、搜索、文件修改、删除、网络访问等风险。
- **Sandbox / 只读约束**：高风险命令可在 sandbox 中试跑或限制文件系统写入范围，降低误操作风险。
- **Shell 环境快照**：会话启动时缓存 shell profile、alias、function 和 PATH 等初始化结果，后续命令复用，减少每次新 shell 的初始化成本并增强一致性。

---

## 2026-08 代码审查遗留项

以下问题来自本轮项目审查。SQLite `plugin_logs.session_id` 缺失和会话路由职责膨胀已处理，不再列入待办。

### P0：任务依赖更新缺少事务

**现状**：任务依赖同时写入 `blocks` 和 `blocked_by` 两个 JSON 数组。MySQL、SQLite 和 Mock 分别复制了双向维护规则；持久化实现采用多次独立读写，MySQL 使用 autocommit，SQLite 的 `_execute` 每次立即 commit。

**风险**：中途异常或并发更新可能只写成功一侧，形成不一致依赖和悬空引用。

**建议**：短期为创建、更新和删除依赖建立事务边界及一致性测试；中期改为独立 `task_dependencies` 关系表，用唯一约束维护边。

### P1：SQLite 同步 I/O 阻塞事件循环

**现状**：`SqliteDatabase` 暴露异步方法，但内部直接调用同步 `sqlite3`，并在每条 `_execute` 后 commit。插件日志逐行写入时尤为频繁。

**建议**：使用异步 SQLite 驱动或统一放入线程，明确单写者/连接锁，并为插件日志增加批量落库。

### P1：会话工作区准备仍是阻塞操作且缺少完整生命周期

**现状**：工作区逻辑已从路由移至 `app/core/workspace.py`，但目录复制和 `subprocess.run` Git 操作仍同步执行。Worktree 删除与失败回滚尚未实现。

**建议**：改为线程或异步子进程并设置超时；将 workspace 建模为有创建、失败回滚、删除回收的资源，删除 session 时回收 worktree 目录但按既定交付策略保留分支。

### P1：会话状态存在多个事实来源

**现状**：后端 Runner 写数据库状态，前端同时根据 `tool_confirm`、`tool_result`、`done`、`error` 推断状态，并通过轮询再次覆盖。

**建议**：后端状态机作为唯一事实来源；每次状态变更广播带序号的 `session_state`，前端不再自行推断 SessionStatus。

### P1：WebSocket 历史回填与实时事件存在竞态

**现状**：前端先连接 WebSocket，再读取 REST 历史，最终直接拼接；同一消息可能同时出现在历史和实时事件中。

**建议**：引入事件序号或消息游标，支持从游标订阅；至少先按 `message_id` 去重，并增加重连回归测试。

### P1：工具确认关联仍有旧协议兼容分支

**现状**：后端 `tool_result` 已携带 `call_id`，前端仍可能按工具名称删除待确认卡片。

**建议**：全链路仅使用 `call_id` 关联 call/confirm/result；旧历史兼容集中到独立 decoder，不混入实时 reducer。

### P1：插件进程退出时待处理命令不会立即失败

**现状**：插件命令 Future 只在响应或超时时结束；插件崩溃或被停止时，没有统一拒绝 `_pending_commands`。

**建议**：进程退出和 stop 时以明确异常结束全部待处理命令，并为订阅队列设置容量与背压策略。

### P2：数据库实现重复且迁移机制补丁化

**现状**：MySQL、SQLite、Mock 各自复制 CRUD 和任务领域规则；MySQL 与 SQLite 分别维护临时字段探测迁移。

**建议**：建立覆盖所有 `IAgentDatabase` 实现的契约测试；领域规则上移到 service；引入有版本号、可按顺序执行的正式迁移。

### P2：前端 Session store 和 LiveConsole 职责膨胀

**现状**：`store/sessions.ts` 同时处理连接、历史兼容、通知、状态推断、确认和任务刷新；`LiveConsole.tsx` 同时负责协议投影、工具事件合并和页面布局。

**建议**：拆出 connection manager、event reducer、history decoder、task hook 和 timeline 组件，优先为纯事件转换函数增加单元测试。

### P2：前后端协议类型手工复制并已漂移

**现状**：REST 和 WebSocket 类型由前后端手工维护，部分后端事件和 Session 字段未出现在前端类型中；事件 `data` 经常是 JSON 字符串内再嵌 JSON。

**建议**：从 OpenAPI 生成 REST 类型；WebSocket 使用结构化可判别联合、协议版本和事件序号。

### P2：工具和 Adapter 抽象类型不准确

**现状**：`BaseTool.execute(**kwargs)` 与各工具显式参数的 override 不兼容；异步生成器接口声明也使 Pyright 报错。

**建议**：工具参数使用 Pydantic 模型或泛型参数模型统一生成校验与 Schema；修正异步迭代协议，使 Pyright 成为可执行门禁。

### P2：配置默认值、依赖和工程门禁不统一

**现状**：数据库默认值在 `Settings`、`init_db` 和 README 中不一致；后端依赖未锁版本；没有已跟踪 CI 或标准测试框架。审查时前端 build 和 Python compile 通过，但 ESLint 与 Pyright 均未通过。

**建议**：统一通过 Settings 读取配置；锁定依赖；引入 pytest 和 CI，执行后端测试、Pyright、前端 build/lint。修复当前 ESLint effect、依赖数组和 Fast Refresh 问题。

### P2：本地优先部署边界需要明确

**现状**：CORS 全开放，无认证；文件浏览和附加 Prompt 可读取主机路径；插件继承完整后端环境变量；前端固定使用 HTTP/WS 端口。

**建议**：明确仅可信本机或允许局域网。如果允许局域网，增加认证、来源限制和文件访问根；插件环境改为 allowlist；前端支持运行时 API 配置及 HTTPS/WSS。
