# docker-deployment Spec Delta
## ADDED Requirements
### Requirement: Qdrant 向量数据库服务
系统 SHALL 在 Docker Compose 中集成 Qdrant 向量数据库服务，用于存储代码向量索引。
#### Scenario: Qdrant 服务定义
- **WHEN** 查看 docker-compose.yml
- **THEN** 包含 qdrant 服务定义
- **AND** 使用 `qdrant/qdrant:latest` 镜像
- **AND** 暴露 6333 (HTTP) 和 6334 (gRPC) 端口
- **AND** 数据持久化到 `./data/qdrant` 目录
#### Scenario: Qdrant 服务启动
- **WHEN** 执行 `docker compose up`
- **THEN** Qdrant 服务随其他服务一起启动
- **AND** 健康检查通过后服务可用
#### Scenario: 服务依赖
- **WHEN** Friday 后端服务启动
- **THEN** 不强制依赖 Qdrant 服务
- **AND** Qdrant 不可用时，索引功能降级但不影响核心功能
#### Scenario: 环境变量配置
- **WHEN** 配置 Qdrant 服务
- **THEN** 可通过 `QDRANT_API_KEY` 环境变量设置 API 密钥
- **AND** 可通过 `QDRANT_HOST` 环境变量自定义主机地址
