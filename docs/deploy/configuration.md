---
title: 环境变量参考
---

# 环境变量参考

完整模板见仓库根目录 [`.env.example`](https://github.com/friday-ai-codes/friday-ai/blob/main/.env.example)。推荐用 `scripts/setup.sh` 自动生成 `.env`，必填密钥会写入强随机值。

`.env` 解析顺序：先 `server/.env`，再项目根目录 `.env`（`django-environ` 加载）。

::: tip 凭据类配置不在环境变量里
AI Provider Key、Git Token、飞书应用凭据等运行时凭据在 Web 界面配置，经 Fernet 加密后存储在数据库（`ProviderCredential` / `SystemSetting`），不走环境变量。环境变量只承担部署级配置。
:::

## 必填项

| 变量 | 生成方式 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `openssl rand -base64 32` | Django 密钥，用于加密签名 |
| `FRIDAY_ENCRYPTION_KEY` | `openssl rand -base64 32` | 敏感数据加密密钥（Provider Key、Token 等） |
| `RUNNER_REGISTRATION_TOKEN` | `openssl rand -base64 32` | Runner 注册令牌，server 与 runner 共享 |
| `DATABASE_URL` | 见下文 | 数据库连接字符串 |

::: warning 生产环境
为每个密钥生成独立随机值，不要复用示例值，不要跨环境复用。`FRIDAY_ENCRYPTION_KEY` 一旦丢失，数据库中所有加密凭据将无法解密。`.env` 权限建议 `600`。
:::

## 持久化与镜像

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FRIDAY_DATA_DIR` | `~/.friday-ai` | Docker bind mount 根目录（`postgres` / `redis` / `qdrant` / `server` / `runner` 子目录） |
| `FRIDAY_IMAGE_PREFIX` | `ghcr.io/friday-ai-codes/friday-ai` | 预构建镜像命名空间 |
| `FRIDAY_IMAGE_TAG` | `latest` | 镜像标签，生产环境建议固定版本号 |
| `FRIDAY_TASK_IMAGE` | `${FRIDAY_IMAGE_PREFIX}/task:${FRIDAY_IMAGE_TAG}` | 任务容器镜像；本地调试设为 `friday-task:latest` |

## 端口

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FRIDAY_WEB_PORT` | `10240` | Web 前端端口（Nginx 同时代理 API 与 WebSocket） |
| `FRIDAY_PORT` | `10241` | 后端 API 直连端口（调试用） |
| `FRIDAY_RUNNER_CALLBACK_PORT` | `8976` | Runner 回调端口（宿主端口必须与容器端口一致） |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `QDRANT_HTTP_PORT` / `QDRANT_GRPC_PORT` | `6333` / `6334` | Qdrant 端口 |

## Django 核心

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEBUG` | `False` | 调试模式，生产环境必须为 `False` |
| `ALLOWED_HOSTS` | `*` | 生产环境建议限制为实际域名 |
| `FRIDAY_ENV` / `FRIDAY_PRODUCTION` | — | 生产硬化开关：强制 `DEBUG=False`、要求非默认 `SECRET_KEY` 与显式 `ALLOWED_HOSTS` |
| `DJANGO_LOG_LEVEL` | `INFO` | 日志级别 |

## 数据库

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday` | 支持 PostgreSQL / MySQL / SQLite（本地开发：`sqlite:///./data/friday.db`） |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `friday` / `friday` / `friday` | 内置 PostgreSQL 凭据 |

## Redis 与 WebSocket

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `USE_REDIS_CHANNEL_LAYER` | `false` | Compose 部署由编排注入 `REDIS_URL` 并启用；本地开发可用内存 Channel Layer |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis 连接 URL |
| `WEBSOCKET_REQUIRE_TLS` | `false` | WebSocket TLS 要求（生产环境自动启用） |

> Redis 在本项目中是**协调层**（WebSocket Channel Layer 消息总线，以及可选的恢复分布式锁），**不是状态真相源**。工作流、索引、图谱等业务状态的真相源在数据库（Postgres/SQLite）、Qdrant 与文件系统中；即使 Redis 重启丢失数据，业务断点恢复也不受影响。

## 可恢复任务（断点恢复）

长任务（索引、图谱构建等）会登记到 `ResumableTask`（DB 真相源）。进程被 `docker compose up -d` 升级、或 k8s Pod 被重建后，服务启动时由 `RecoveryScheduler` 扫描"租约已过期的运行中任务"并自动续跑（复用 `FileIndex` / `GraphFileIndex` 文件级断点跳过已完成文件）。也可手动触发：`python manage.py recover_tasks`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RESUMABLE_RECOVERY_ON_STARTUP` | `true` | 启动时是否自动恢复未完成任务 |
| `RESUMABLE_LEASE_TTL_SECONDS` | `90` | 任务租约 TTL；启动扫描只领取租约已过期的运行中任务 |
| `RESUMABLE_HEARTBEAT_INTERVAL_SECONDS` | `30` | 运行中任务续租/心跳间隔 |
| `RESUMABLE_USE_REDIS_LOCK` | `false` | 多副本/k8s 推荐开启：用 Redis 对"恢复扫描"做集群级互斥；关闭时由 DB 行级 CAS 保证 exactly-once |

## Qdrant

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant 地址 |
| `QDRANT_API_KEY` | `friday-local`（compose 回落值） | **不要显式设为空字符串**：qdrant 收到空值会开启「空 key 鉴权」，客户端不发空 key，导致健康检查 401 |
| `QDRANT_BUNDLED` | `true` | 是否使用编排内置 Qdrant |

## Runner

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FRIDAY_RUNNER_NAME` | `compose-runner` | Runner 名称 |
| `FRIDAY_RUNNER_EXECUTOR` | `docker` | 执行器类型（`docker` / `k8s`） |
| `DOCKER_GID` | `0` | Docker 组 GID；Linux 上用 `stat -c '%g' /var/run/docker.sock` 获取 |

Runner 自身还支持 `FRIDAY_RUNNER_*` 前缀的全部配置项（viper 绑定，对应 `config.toml`）。

## JWT 认证

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `JWT_SECRET_KEY` | 使用 `SECRET_KEY` | JWT 签名密钥 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access Token 过期时间（分钟） |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh Token 过期时间（天） |
| `COOKIE_SECURE` / `COOKIE_SAMESITE` / `COOKIE_HTTPONLY` | `False` / `Lax` / `True` | Cookie 安全设置 |

## Gunicorn

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GUNICORN_WORKERS` | `1` | Worker 数量（建议 CPU 核数 × 2 + 1） |
| `GUNICORN_TIMEOUT` | `300` | Worker 超时秒数（WebSocket / SSE 长连接需要较长超时） |

## 管理员（命令行兜底）

首次部署的管理员账号默认由 Web「首启初始化向导」创建，系统启动时不再自动建号。以下变量仅在手动执行 `python manage.py init_superuser` 时被读取：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FRIDAY_ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `FRIDAY_ADMIN_PASSWORD` | —（留空随机生成并打印） | 管理员密码 |

重置已有管理员密码：`python manage.py reset_superuser_password`。

## 飞书

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FEISHU_ENCRYPT_KEY` | — | 飞书事件加密密钥 |
| `FEISHU_SIGNATURE_REQUIRED` | `false` | 是否要求飞书签名验证 |

飞书应用凭据（App ID / Secret 等）在 Web 界面按项目配置，详见[飞书集成](/integrations/feishu)。

## 功能开关

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FF_SYNC_WORKFLOW_TO_FEISHU` | `true` | 飞书同步 |
| `FF_ENABLE_WORKFLOW_WEBSOCKET` | `true` | WebSocket 实时更新 |
| `FF_DEFAULT_WORKFLOW_TEMPLATE` | `code_generation` | 默认工作流模板 |
| `FF_ENABLE_SCHEDULER` | `true` | 启用调度器（仓库同步轮询等） |

## 下一步

<LinkCards>
  <LinkCard icon="🐳" title="Docker Compose 部署" desc="一键部署、升级、备份与排障" link="/deploy/docker-compose" />
  <LinkCard icon="☸️" title="Helm / Kubernetes 部署" desc="集群环境的配置项与 Secret 管理" link="/deploy/helm" />
  <LinkCard icon="🔐" title="安全模型" desc="为什么凭据不走环境变量" link="/internals/security" />
</LinkCards>
