<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/public/logo-dark.svg">
    <img src="web/public/logo.svg" alt="Friday AI" width="420">
  </picture>
</p>

**Friday AI** 是一个开源的开发自动化平台，用来把已经确认的需求推进到可审计的代码变更。它把工作项、代码仓库、工作流编排、代码检索和 AI 编码 Agent 放在同一个自托管系统里。

Friday 适合已经有研发流程的团队：需求需要评审，技术方案需要可见，代码要通过 PR 或 MR 合入，自动化执行过程也要能追踪。

| 能力 | 说明 |
| --- | --- |
| 需求到代码工作流 | 从飞书项目事件或手动运行触发，生成技术方案，等待评审字段，再派发编码任务。 |
| AI 技术方案 | 把工作项转成结构化实现上下文，先评审，再进入编码。 |
| 编码 Agent | 通过已注册 Runner 执行隔离任务，并记录分支、提交、PR/MR 等结果。 |
| 代码智能 | 对仓库做符号抽取、图关系、向量检索和上下文召回，让编码任务拿到更好的代码背景。 |
| 仓库集成 | 统一管理 GitHub / GitLab 仓库、凭据、分支、PR 和 MR。 |
| 自托管部署 | 提供 Docker Compose 完整栈、本地持久化目录、Helm 模板和 Argo CD 示例。 |

## 快速开始

前置要求：

- Docker 和 Docker Compose v2
- Git

生成本地配置和数据目录：

```bash
scripts/setup.sh
```

启动完整服务：

```bash
docker compose up -d
```

Compose 会启动 Web、Server、Runner、PostgreSQL、Redis 和 Qdrant。

| 服务入口 | 地址 |
| --- | --- |
| Web 界面 | <http://localhost:10240> |
| API 文档 | <http://localhost:10240/docs> |
| 后端 API 直连端口 | <http://localhost:10241> |

常用命令：

```bash
docker compose logs -f
docker compose down
docker compose -f docker-compose.yaml -f docker-compose.build.yaml up --build -d
```

## 配置

`scripts/setup.sh` 会创建 `.env`，生成必需密钥，并默认把持久化数据写到 `~/.friday-ai`。需要非交互式部署或自定义数据目录时，可以运行 `scripts/setup.sh --help` 查看参数。

关键环境变量：

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `SECRET_KEY` | 是 | 自动生成 | Django 签名密钥。 |
| `FRIDAY_ENCRYPTION_KEY` | 是 | 自动生成 | 存储凭据的加密密钥。 |
| `RUNNER_REGISTRATION_TOKEN` | 是 | 自动生成 | Server 和 Runner 共享的注册令牌。 |
| `DATABASE_URL` | 否 | `postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday` | Compose 栈使用的数据库地址。 |
| `FRIDAY_DATA_DIR` | 否 | `~/.friday-ai` | PostgreSQL、Redis、Qdrant、Server、Runner 的宿主机数据目录。 |
| `FRIDAY_WEB_PORT` | 否 | `10240` | Web 入口和代理后的 API 文档端口。 |
| `FRIDAY_PORT` | 否 | `10241` | 后端 API 直连端口。 |
| `FRIDAY_IMAGE_PREFIX` | 否 | `ghcr.io/friday-ai-codes/friday-ai` | 容器镜像命名空间。 |
| `FRIDAY_IMAGE_TAG` | 否 | `latest` | 容器镜像标签。 |

不要提交 `.env`、数据库、日志、服务令牌或客户数据导出。

## 本地开发

安装依赖：

```bash
make install
```

启动本地开发环境：

```bash
make dev
```

也可以分别启动服务：

```bash
make dev-server
make dev-web
```

常用检查：

```bash
cd server && uv run pytest
cd web && pnpm lint && pnpm type-check && pnpm test:unit:coverage
cd web && pnpm test:e2e -- --project=chromium
cd runner && go test ./...
cd task && uv run ruff check . && uv run pytest
```

改动部署相关逻辑前，建议验证公开安装路径：

```bash
bash -n scripts/setup.sh
scripts/setup.sh --non-interactive --force --data-dir /tmp/friday-ai-data
docker compose config
```

## 仓库结构

| 路径 | 作用 |
| --- | --- |
| `server/` | Django API、编排服务、仓库索引、集成逻辑和后端测试。 |
| `web/` | Vue 3 前端、共享 UI、Vitest 单元测试和 Playwright e2e 测试。 |
| `runner/` | Go 编写的 Runner 服务，连接 Server 并执行任务。 |
| `task/` | 隔离任务执行容器和任务侧集成测试。 |
| `deploy/` | Docker、Helm 和 Argo CD 部署资产。 |
| `docs/` | VitePress 文档和生成的 API 参考。 |
| `scripts/` | 初始化、验证和发布辅助脚本。 |

## 部署

默认 Compose 部署使用下面的预构建镜像：

```text
ghcr.io/friday-ai-codes/friday-ai
```

可以通过 `FRIDAY_IMAGE_TAG` 固定版本，也可以叠加 `docker-compose.build.yaml` 从当前源码构建镜像。Helm 和 Argo CD 示例在 `deploy/` 目录下。

## 文档

可以先看这些文档：

| 文档 | 内容 |
| --- | --- |
| [快速开始](docs/guide/quick-start.md) | 本地部署、创建第一个项目、测试工作流。 |
| [工作流指南](docs/guide/workflows.md) | 工作流节点、触发器、执行记录和调试。 |
| [管理指南](docs/guide/admin.md) | 用户、权限、OIDC、Runner 和运维配置。 |
| [Friday Codebase Agent](docs/guide/friday-codebase-agent.md) | 代码库 Agent 行为和仓库上下文。 |
| [API 参考](docs/api/index.md) | REST API 文档。 |
| [English README](README.md) | 英文版 README。 |

## 项目状态

Friday AI 还在早期公开发布阶段。API、部署默认值和扩展点可能会在小版本之间调整。

## 贡献

提交 PR 前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 处理，不要直接发公开 issue。

## License

Friday AI 使用 [MIT License](LICENSE) 发布。
