# Friday AI Compose 完整体实例设计
## 目标
让全新本地环境可以执行：
```bash
scripts/setup.sh
docker compose up -d
```
并启动一个包含 Web、Server、Runner、PostgreSQL、Redis、Qdrant 的 Friday AI 完整体实例。默认使用 GHCR 预构建镜像；源码构建继续通过 `docker-compose.build.yaml` 覆盖。
## 架构
`docker-compose.yaml` 是默认完整体编排入口，不再要求用户显式开启 PostgreSQL profile。`scripts/setup.sh` 是正式初始化入口，负责生成 `.env`、创建宿主机持久化目录、生成密钥和写入默认端口。根目录 `setup.sh` 保留为兼容 wrapper，转发到 `scripts/setup.sh`。
持久化使用宿主机目录，默认根目录为 `~/.friday-ai`，并为每个服务创建独立子目录：
- `postgres` -> `${FRIDAY_DATA_DIR}/postgres`
- `redis` -> `${FRIDAY_DATA_DIR}/redis`
- `qdrant` -> `${FRIDAY_DATA_DIR}/qdrant`
- `server` -> `${FRIDAY_DATA_DIR}/server`
- `runner` -> `${FRIDAY_DATA_DIR}/runner`
## 启动数据流
1. 用户运行 `scripts/setup.sh`。
2. 脚本检查 Docker、Docker Compose、密钥生成工具和 Docker daemon。
3. 脚本生成 `.env`，写入端口、Django 密钥、数据库连接、Runner token、Qdrant URL/API key、管理员配置和 `FRIDAY_DATA_DIR`。
4. 脚本创建每个服务独立的宿主机持久化目录。
5. 用户运行 `docker compose up -d`。
6. Compose 拉取 GHCR 预构建镜像和基础设施镜像。
7. Server 等待数据库，执行迁移，然后运行系统设置 bootstrap，确保数据库中的 `system_settings.qdrant_url` 指向 `http://qdrant:6333`。
8. Server 初始化管理员、收集静态文件并启动 gunicorn。
## 错误处理
`scripts/setup.sh` 在缺少 Docker、Docker Compose V2、Docker daemon 权限或密钥生成工具时失败并提示修复方式。已有 `.env` 时，交互模式询问是否覆盖，非交互模式覆盖。系统设置 bootstrap 不覆盖已有 `qdrant_url`，避免破坏用户在管理后台配置的外部 Qdrant。
## 测试
新增 pytest 覆盖：
- `bootstrap_system_settings` 会从环境写入默认 Qdrant URL。
- 已存在的 Qdrant URL 不会被覆盖。
- Qdrant API key 会加密写入并可解密读取。
- `docker-compose.yaml` 默认包含完整服务集合，PostgreSQL 不依赖 profile。
- Compose 的持久化挂载使用 `${FRIDAY_DATA_DIR}/...` bind mount，而不是 Docker named volumes。
补充命令级验证：
- `bash -n scripts/setup.sh setup.sh`
- `docker compose config`
- 相关 pytest 文件
## 自检
本设计无占位符。范围集中在一键本地完整体部署，不改变业务 API、Provider 配置或前端交互。Compose 默认使用 GHCR 镜像，与用户确认一致。
