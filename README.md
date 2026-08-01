# 新时代 AI 工作台

在这个时代，每个人都有很多事情要处理：完成本职工作、追踪前沿热点，还要记得回复越来越多的通讯消息。

但我们不可能都像大老板一样，有秘书或助理帮自己处理琐事。所以，如果有 AI 助理，是不是可以让生活和工作更轻松一些？

这个项目希望提供一个可以长期运行在你自己电脑上的 AI 工作台。你可以把事情交给 AI 助理，让它帮你记录、提醒、调研，或者在授权后操作浏览器完成一些重复性任务。

## 特性

- **日程安排助理**：将需要做的事情转发给 AI 助理，AI 助理可以帮你记录在日历上，并在合适的时间提醒你处理。
- **网页每日签到**：对于需要每日签到、打卡，或其他重复性操作的网页，可以让 AI 助理在浏览器中协助处理。
- **消息自动调研**：当群友、同事或老板聊到你不了解的内容时，可以让 AI 助理帮你搜索和整理资料，节省查找信息的时间。

## 使用方法

首先，你需要给 AI 助理准备一台电脑。AI 助理会在这台电脑上运行后端服务、前端控制台，并在需要时操作浏览器。

### 1. 准备数据库服务

AI 助理需要数据库来保存会话记录和状态信息。本地开发或试用时，推荐使用项目内置的 SQLite 持久化后端。SQLite 通过 Python 标准库工作，不需要安装和启动 MySQL、MariaDB 等额外数据库服务，数据会保存到本地文件。

在 `backend/.env` 中使用：

```dotenv
DB_TYPE="sqlite"
SQLITE_PATH="backend/.local/augentia.db"
```

如果你已经有可用的 MySQL 服务，也可以继续在 `backend/.env` 中配置 MySQL 连接信息：

```dotenv
DB_TYPE="mysql"
MYSQL_HOST="127.0.0.1"
MYSQL_PORT="3306"
MYSQL_USER="root"
MYSQL_PASSWORD=""
MYSQL_DATABASE="augentia"
```

项目也保留了一个可选的本机 MySQL/MariaDB 管理脚本：`python scripts/local_mysql.py start`。不过它仍然要求电脑上已经安装 MySQL 或 MariaDB 服务端程序，所以普通本地试用优先使用 SQLite 即可。临时测试还可以把 `DB_TYPE` 改成 `mock`，但这种内存数据库不会持久保存数据。

### 2. 安装浏览器插件

如果你希望 AI 助理操作浏览器，需要先在浏览器中安装 [控制插件](https://chromewebstore.google.com/detail/chatgpt/hehggadaopoacecdllhhajmbjkdcmajg) 。

### 3. 启动后端服务

启动前，请先在 `backend/.env` 中配置 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `OPENAI_MODEL` 等必要信息。

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 12598
# API available at http://<your-ip>:12598
# Docs available at http://<your-ip>:12598/docs
```

### 4. 启动前端服务

```bash
cd frontend
npm install
npm run dev
# Dashboard available at http://<your-ip>:12599
```

### 5. 连接微信

敬请期待。

## 致谢

此项目的许多设计理念借鉴了 Codex、Claude Code 等业内知名产品，同时也感谢 [wechatbot](https://github.com/corespeed-io/wechatbot) 等项目提供的能力支持。
