# Friday Server

Friday 的 Django 后端：REST + WebSocket API、工作流引擎、代码智能（codegraph / Graph RAG）以及飞书、GitHub / GitLab、AI Provider 集成。

完整文档见[文档站](https://friday-ai-codes.github.io/friday-ai/)，内部实现见 `docs/internals/`。

## 技术栈

- Python 3.14+，Django 5.1+ / DRF（`adrf` 异步视图），`channels` + `daphne` 提供 WebSocket
- 数据库通过 `DATABASE_URL` 配置：默认 SQLite（本地开发），生产推荐 PostgreSQL
- 包管理用 `uv`，配置加载用 `django-environ`（`server/.env` 优先，其次项目根 `.env`）

## 本地开发

```bash
uv sync                              # 安装依赖
uv run python manage.py migrate      # 应用迁移
uv run uvicorn friday.asgi:application --reload   # 启动开发服务（含 WebSocket）
```

也可以在项目根目录用 `make dev` 同时启动 server 和 web。

## 测试与检查

```bash
uv run pytest                # 全量测试
uv run ruff check .          # lint
uv run mypy .                # 类型检查
```

变更后端代码前，建议先跑 `CONTRIBUTING.md` 中列出的重点测试集。

## 目录速览

| 目录 | 职责 |
| --- | --- |
| `friday/` | Django 项目配置、ASGI/WSGI 入口、根路由 |
| `workflows/` | 工作流引擎（DAG 调度）与节点实现 |
| `services/` | 领域服务：索引、Graph RAG、git 平台、Provider 解析 |
| `agents/` | Agent 运行时、工具与事件 |
| `chat/` | Web Chat 会话与流式输出 |
| `codegraph/` / `code_relations/` | 代码图谱与跨仓 API 关系 |
| `feishu/` | 飞书项目 / 文档 / 机器人 / 卡片回调集成 |
| `repositories/` | 仓库接入与索引管理 |
| `runners/` | 与 Go runner 的 WebSocket 调度协议 |
| `mcp_tools/` | MCP 工具的 HTTP 入口 |
| `identity/` / `accounts/` / `access_tokens/` | 认证（JWT / OIDC）、用户与访问令牌 |
| `tests/` | 后端测试 |

## Docker

服务端镜像由仓库根的 `docker-compose.yaml` 统一编排（含 PostgreSQL、Redis、Qdrant），部署方式见[部署文档](https://friday-ai-codes.github.io/friday-ai/deploy/docker-compose)。
