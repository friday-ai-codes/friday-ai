---
title: 源码与本地开发
---

# 源码与本地开发

适合二次开发、贡献代码或调试场景。生产部署请优先使用 [Docker Compose](/deploy/docker-compose) 或 [Helm](/deploy/helm)。

## 工具链要求

| 工具 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.14+（`server/.python-version` 锁定） | Server 与 Task |
| uv | 最新 | Python 依赖管理（锁文件 `uv.lock`） |
| Node.js | 见 `web/.nvmrc` | 前端 |
| pnpm | `10.28.0`（`web/package.json` 锁定） | 前端依赖管理 |
| Go | 1.25 | Runner |
| Docker | — | Runner 启动任务容器、可选的本地 PostgreSQL / Qdrant |

## 安装依赖

```bash
git clone https://github.com/friday-ai-codes/friday-ai.git
cd friday-ai

# 生成本地配置（.env）
scripts/setup.sh

# 安装 server (uv sync) + web (pnpm install)
make install
```

## 启动开发环境

一键启动前后端（tmux 分屏，自动写日志到 `.logs/`）：

```bash
make dev
```

或分别启动：

```bash
make dev-server   # uvicorn friday.asgi:application --reload，端口 10241
make dev-web      # pnpm dev，端口 10240
```

后端默认使用 SQLite + 内存 Channel Layer，无需先起 PostgreSQL / Redis。需要完整能力（向量检索、Redis Channel Layer）时，可只用 compose 启动依赖服务：

```bash
docker compose up -d postgres redis qdrant
```

首次启动前初始化数据库：

```bash
cd server
uv run python manage.py migrate
```

管理员账号由首启向导创建；无界面环境可用命令行兜底：

```bash
uv run python manage.py init_superuser
```

## 构建 Runner 与 Task

```bash
# 编译 Go Runner（输出 runner/friday-runner）
make build-runner

# 构建任务容器镜像 friday-task:latest
make build-task
```

本地调试任务执行时，在 `.env` 中设置 `FRIDAY_TASK_IMAGE=friday-task:latest`，Runner 下次启动任务容器即会使用本地镜像（无需重启 Runner）。

Runner 本地运行：

```bash
cd runner
./friday-runner register   # 交互式注册到 server
./friday-runner run        # 启动调度
```

Runner 配置存于配置目录下的 `config.toml`，也可用 `FRIDAY_RUNNER_*` 环境变量覆盖（viper 绑定）。

## 运行测试

```bash
# Server（CI 烟雾测试集见 .github/workflows/ci.yaml）
cd server && uv run pytest

# Web
cd web && pnpm lint && pnpm type-check && pnpm test:unit:coverage
cd web && pnpm test:e2e -- --project=chromium

# Runner
cd runner && go vet ./... && go test ./...

# Task
cd task && uv run ruff check . && uv run pytest
```

## 构建文档站

```bash
pnpm install          # 仓库根目录
pnpm docs:dev         # 本地预览（热更新）
pnpm docs:build       # 构建（会先从 OpenAPI schema 重新生成 API 文档）
```

刷新 REST API 文档数据源：

```bash
cd server && uv run python manage.py spectacular --color --file ../docs/public/schema.json
```

## 下一步

- [贡献指南](/contributing/) —— 提交规范、检查项、PR 流程
- [架构总览](/internals/) —— 理解代码结构再动手
