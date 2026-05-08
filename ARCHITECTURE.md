# 🤖 Agent Gateway & Multi-Agent Orchestration System 开发白皮书

## 一、 项目愿景与目标

构建一个高扩展性的 **Agent Gateway (智能体网关)**，实现对多种底层架构智能体（如基础 Tool-use Agent、CLI驱动的 Claude Code 等）的统一入口管理、会话持久化和流式状态监控。

**核心验证项目**：基于该网关搭建一套 **自动化 AI 研究与直播推流系统**。系统通过调度不同的 Agent 协同工作，完成从 Arxiv 检索、讲稿生成（Human-in-the-loop 审核）到自动推流的完整工作流。

---

## 二、 系统总体架构图 (Layered Architecture)

系统采用“网关-适配器”解耦模式，分为四大核心层级：

| 层级 | 模块名称 | 技术栈选型 | 核心职责 |
|---|---|---|---|
| **前端呈现层** | Management Dashboard | Vue 3 / React 18, Tailwind CSS | 提供可视化控制台，包括智能体注册、活跃会话监控、实时日志流（WebSocket）。 |
| **网关接入层** | API & WebSocket Gateway | FastAPI (Python), Uvicorn | 暴露 RESTful 接口与长连接，处理跨域 (CORS)，管理全局并发请求。 |
| **核心逻辑层** | Session & Route Manager | 异步 Python, 依赖注入 (DI) | 负责状态机流转，依靠仓储模式 (Repository) 读写数据，调度底层 Adapter。 |
| **代理适配层** | Agent Adapters | `asyncio.subprocess`, SDKs | 屏蔽底层差异。将标准指令转化为 API 请求或 CLI 标准输入，并捕获输出返回给网关。 |

---

## 三、 数据库服务设计 (基于仓储模式的依赖倒置)

为保证前期研发的高效性与后期生产环境的健壮性，数据库层采用 **接口与实现分离** 的设计。

### 1. 核心领域模型 (Domain Models)

*   **AgentTemplate (智能体模板)**: 定义 Agent 的类型、Prompt 和包含的工具。
*   **Session (会话状态)**: 管理多轮对话，记录状态枚举 (`INITIALIZING`, `RUNNING`, `WAITING_USER`, `COMPLETED`, `ERROR`)。
*   **Message (交互日志)**: 记录系统、用户、工具与 Agent 之间的每一次信息流转。

### 2. 数据库接口定义 (`IAgentDatabase`)

所有的业务逻辑均仅依赖以下抽象接口：

```python
from abc import ABC, abstractmethod

class IAgentDatabase(ABC):
    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentTemplate: pass
    
    @abstractmethod
    async def create_session(self, agent_id: str) -> Session: pass
    
    @abstractmethod
    async def update_session_status(self, session_id: str, status: str) -> Session: pass
    
    @abstractmethod
    async def add_message(self, session_id: str, role: str, content: str) -> Message: pass
```

### 3. 分阶段实现策略

*   **阶段一 (当前/研发期)**：注入 `MockMemoryDatabase`。数据存储在 Python 字典中，极速启动，无需配置外部环境，方便跑通前后端通信与 Agent 适配逻辑。
*   **阶段二 (生产期)**：注入 `PostgreSQLDatabase`。基于 `SQLAlchemy` (asyncpg) 重新实现接口方法，业务层代码 **零修改** 即可实现持久化存储。

---

## 四、 后端网关服务规范 (Backend Specification)

后端主要充当“调度中心”与“数据总线”。

### 1. 核心 API 路由设计

| 路由端点 | HTTP 方法 | 功能描述 |
|---|---|---|
| `/api/v1/agents` | GET | 获取大厅中可用的 Agent 模板列表。 |
| `/api/v1/sessions` | POST | 启动新会话，拉起底层的 Agent 适配器。 |
| `/api/v1/sessions/{id}` | GET | 获取指定会话的当前状态机状态。 |
| `/api/v1/sessions/{id}/stream`| WebSocket | **核心**：实时推送 Agent 的思考过程、工具调用日志及终端输出 (stdout) 给前端。 |

### 2. Agent 适配器模式 (Adapter Pattern)

针对不同类型的 Agent，必须实现 `BaseAgentAdapter` 接口。

*   **基础 Tool-use Agent**: 通过标准 LLM SDK 循环调用，解析 `tool_calls`。
*   **Claude Code Adapter (重点难点)**:
    *   使用 `asyncio.create_subprocess_shell` 启动进程。
    *   使用异步队列 (asyncio.Queue) 或非阻塞 I/O 实时读取 `stdout/stderr`，将其解析为文本流通过 WebSocket 发送。
    *   接收网关指令，写入 `stdin` 以推进对话。

---

## 五、 前端控制台规范 (Frontend Specification)

前端提供“驾驶舱”级别的管理体验。

### 1. 页面模块规划

*   **🤖 智能体大厅 (Agent Registry)**: 卡片式展示系统支持的 Agent。提供快捷表单配置初始 Prompt，一键触发 `Launch`。
*   **⚡ 会话看板 (Session Dashboard)**: 动态数据表格。利用轮询或全局 WebSocket 同步所有在线 Session 的运行状态（如“检索中”、“等待人工确认”）。
*   **📺 实时控制台 (Live Console)**: 
    *   左侧区域：类似 `xterm.js` 的终端界面或气泡聊天框，实时打印执行日志。
    *   右侧区域：人工干预面板 (Human-in-the-loop)。当状态为 `WAITING_USER` 时，可在此修改生成的讲稿并点击 `Approve` 放行。

### 2. 关键技术点

*   必须配置 Axios/Fetch 的 `baseURL` 并在 FastAPI 端开启 `CORSMiddleware`，防止跨域拦截。
*   WebSocket 断线重连机制 (Reconnect logic)，确保长耗时任务不断联。

---

## 六、 验证项目工作流：自动化研究与直播推流

本流程将贯穿上述所有模块，验证系统的多 Agent 编排能力：

1.  **触发 (Trigger)**: 用户在 Dashboard 启动 `Research_Agent` 会话，输入检索主题（如“具身智能”）。
2.  **检索与生成 (Processing)**: 网关调度基础 Tool Agent，调用 Arxiv/Web 搜索工具，将数据写入 Database，汇总后交由 `Claude Code` 生成直播脚本。
3.  **人工审核 (Human-in-the-loop)**: 网关将 Session 状态置为 `WAITING_USER`。用户在前端 Live Console 预览并修改脚本。
4.  **自动推流 (Broadcasting)**: 用户点击确认，网关拉起 `Broadcaster_Agent`，接管最终脚本，调用 TTS 及 FFMPEG/OBS 接口完成流媒体推送。

---

## 七、 实施里程碑 (Roadmap)

*   **📍 Milestone 1: 骨架搭建 (Mock DB + 基础 API)**
    *   完成 FastAPI 基础路由与依赖注入的 Mock 数据库。
    *   跑通一个基础的 HTTP 和 WebSocket 接口。
*   **📍 Milestone 2: 攻坚 Claude Code 适配器**
    *   实现通过 `asyncio.subprocess` 后台安全运行 Claude Code，并将 CLI 输出成功转为 WebSocket 流推送给客户端。
*   **📍 Milestone 3: 前端 Dashboard 连通**
    *   基于 Vue/React 搭建控制台，实现状态展示和日志渲染。
*   **📍 Milestone 4: 工作流组装与生产化迁移**
    *   串联 Research -> Script -> Broadcast 工作流。
    *   将 Mock 数据库替换为 PostgreSQL。
