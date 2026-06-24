---
title: Docker Compose 部署
---

# Docker Compose 部署

推荐的部署方式。使用 GHCR 上的预构建镜像，无需本地编译。

## 前置要求

- Docker Engine + Docker Compose v2
- Git
- **内核参数 `vm.max_map_count`（Linux 宿主机必做）**：Qdrant 用 mmap 存储向量/索引，索引仓库较多时 mmap 数量会撞内核默认上限（65530），导致 Qdrant 崩溃重启循环。该参数无法由 compose 设置，需在宿主机执行一次：

```bash
sudo bash deploy/scripts/set-vm-max-map-count.sh
# 等价于：
#   sudo sysctl -w vm.max_map_count=1048576
#   echo 'vm.max_map_count=1048576' | sudo tee /etc/sysctl.d/99-qdrant.conf
```

## 一键部署

```bash
git clone https://github.com/friday-ai-codes/friday-ai.git
cd friday-ai

# 初始化配置：自动生成密钥、写入 .env、创建数据目录
scripts/setup.sh

# 启动完整栈
docker compose up -d
```

`scripts/setup.sh` 会：

- 生成 `SECRET_KEY`、`FRIDAY_ENCRYPTION_KEY`、`RUNNER_REGISTRATION_TOKEN`、`QDRANT_API_KEY` 等强随机密钥并写入 `.env`；
- 默认在 `~/.friday-ai` 下创建 `postgres`、`redis`、`qdrant`、`server`、`runner` 五个持久化目录；
- 写入预构建镜像的命名空间（`FRIDAY_IMAGE_PREFIX`）和标签（`FRIDAY_IMAGE_TAG`）。

非交互模式（CI / 自动化脚本）：

```bash
scripts/setup.sh --non-interactive --force --data-dir /opt/friday-data
```

## 服务编排

| 服务 | 容器名 | 端口 | 说明 |
| --- | --- | --- | --- |
| web | `friday-web` | `10240` | 前端界面 + Nginx 反向代理（同时代理 API 与 WebSocket） |
| server | `friday-server` | `10241` | Django 后端（Gunicorn + Daphne），`10241` 仅作调试直连 |
| runner | `friday-runner` | `8976` | Go 调度器；回调端口必须发布到宿主机供任务容器回调 |
| postgres | `friday-postgres` | — | PostgreSQL 17（仅内部网络） |
| redis | `friday-redis` | `6379` | Channel Layer 与缓存 |
| qdrant | `friday-qdrant` | `6333/6334` | 向量数据库（代码语义检索） |

启动后访问：

| 入口 | 地址 |
| --- | --- |
| Friday Web | <http://localhost:10240> |
| API 文档（Swagger） | <http://localhost:10240/docs> |

::: tip 首次访问
全新部署首次打开 Web 会进入「首启初始化向导」，按提示设置管理员账号即可。该向导是 fail-closed 的：系统中已存在管理员时接口直接拒绝，不能被用于重置或接管现有实例。
:::

## 关键编排细节

这些细节在排障时经常用到：

- **Runner 挂载 Docker socket**：Runner 通过 `/var/run/docker.sock` 在宿主 daemon 上启动任务容器（与 Runner 是「兄弟容器」关系）。Linux 上需要设置 `DOCKER_GID`（`stat -c '%g' /var/run/docker.sock` 获取），macOS Docker Desktop / OrbStack 用默认值即可。
- **回调链路**：任务容器通过 `host.docker.internal` 回调 Runner 的 CallbackServer（默认 `8976`），server 也通过同样机制向任务容器回传交互答案，因此 compose 里为 server 显式配置了 `host-gateway` 映射。

<FlowDiagram :layers="[
  {
    nodes: [
      { title: '任务容器', badge: 'task', desc: 'Runner 启动的「兄弟容器」，跑 Claude Code' },
    ],
    arrow: 'host.docker.internal:8976 上报进度 / 提问',
  },
  {
    nodes: [
      { title: 'Runner CallbackServer', badge: ':8976', accent: true, desc: '回调端口必须发布到宿主机' },
    ],
    arrow: 'WebSocket + HTTP · 转发回 server（含交互答案回传）',
    bidirectional: true,
  },
  {
    nodes: [
      { title: 'Server', badge: 'Django', desc: 'compose 已配置 host-gateway 映射' },
    ],
  },
]" />
- **Qdrant API Key**：`QDRANT_API_KEY` 不能显式设为空字符串。qdrant 只要收到空值就会开启「空 key 鉴权」，而客户端不发空 key，健康检查会 401。留空请保持注释，compose 会回落到两端一致的默认值。
- **Task 镜像**：Runner 启动任务容器时默认拉取 `ghcr.io/friday-ai-codes/friday-ai/task:latest`，本地调试可 `make build-task` 后设置 `FRIDAY_TASK_IMAGE=friday-task:latest`。

## 升级

```bash
git pull
docker compose pull
docker compose up -d
```

数据库迁移由 server 容器启动时自动执行。升级前建议备份数据目录（见下文）。

固定版本部署：在 `.env` 中把 `FRIDAY_IMAGE_TAG` 设为具体版本号（如 `v0.0.1`），避免 `latest` 漂移。

## 备份与恢复

所有持久化数据都在 `FRIDAY_DATA_DIR`（默认 `~/.friday-ai`）下：

```bash
# 备份（建议先停服保证一致性）
docker compose stop
tar czf friday-backup-$(date +%Y%m%d).tar.gz -C ~ .friday-ai
docker compose start

# 仅备份数据库（不停服）
docker exec friday-postgres pg_dump -U friday friday > friday-db-$(date +%Y%m%d).sql
```

::: warning 别忘了 .env
`FRIDAY_ENCRYPTION_KEY` 丢失后数据库里所有加密凭据（Provider Key、Git Token 等）将无法解密。备份数据目录的同时必须备份 `.env`。
:::

## 生产环境清单

- [ ] 用 `scripts/setup.sh` 生成独立随机密钥，不复用任何示例值，`.env` 权限设为 `600`
- [ ] `DEBUG=False`，`ALLOWED_HOSTS` 限制为实际域名
- [ ] 用反向代理（Caddy / Nginx / Traefik）终结 TLS，转发到 `127.0.0.1:10240`，并代理 WebSocket（`Upgrade` 头）
- [ ] `FRIDAY_IMAGE_TAG` 固定为具体版本号
- [ ] 配置数据目录的定期备份
- [ ] 飞书集成走 HTTPS 域名（事件回调地址 `https://your-domain/api/feishu/webhook/`）

反向代理示例（Caddy）：

```text
friday.example.com {
    reverse_proxy 127.0.0.1:10240
}
```

## 源码构建部署

不想用预构建镜像时，可以从源码构建：

```bash
docker compose -f docker-compose.yaml -f docker-compose.build.yaml up --build -d
```

## 常见问题

### Runner 无法启动任务容器

检查 Docker socket 权限：Linux 上确认 `.env` 中 `DOCKER_GID` 与宿主机 `stat -c '%g' /var/run/docker.sock` 输出一致后重启 runner。

### 任务容器回调失败（All connection attempts failed）

确认 `8976` 端口已发布到宿主机且未被占用；自定义端口时设置 `FRIDAY_RUNNER_CALLBACK_PORT`（宿主端口必须与容器端口一致）。

### Qdrant 健康检查 401

检查 `.env` 中 `QDRANT_API_KEY` 是否被显式设为空字符串，删除该行或填入非空值后重启。

## 下一步

- [快速开始](/guide/quick-start) —— 配置 Provider、索引仓库、跑第一条工作流
- [环境变量参考](/deploy/configuration) —— 全部配置项说明
