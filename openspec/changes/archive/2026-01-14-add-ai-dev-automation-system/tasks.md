# Implementation Tasks
## 1. 项目基础设施
- [x] 1.1 使用 uv 初始化 Python 项目
- [x] 1.2 配置 FastAPI 应用入口
- [x] 1.3 配置 SQLite + aiosqlite 异步数据库
- [x] 1.4 实现 pydantic-settings 配置管理
- [x] 1.5 编写健康检查接口 /health
## 2. 数据模型实现
- [x] 2.1 Project 模型（项目配置）
- [x] 2.2 GitCredential 模型（Git 凭证，加密存储）
- [x] 2.3 Task 模型（任务状态机）
- [x] 2.4 TaskStatus 枚举（状态定义）
## 3. 项目管理 API
- [x] 3.1 项目 CRUD 接口 (`/api/projects/`)
- [x] 3.2 凭证管理接口（SSH Key / Access Token）
- [x] 3.3 凭证加密服务 (Fernet)
## 4. 任务管理 API
- [x] 4.1 任务 CRUD 接口 (`/api/tasks/`)
- [x] 4.2 任务状态流转接口 (`/api/tasks/{id}/transition/{status}`)
- [x] 4.3 任务执行接口 (`/api/tasks/{id}/execute`)
- [x] 4.4 任务日志/状态查询接口
## 5. 飞书集成
- [x] 5.1 Webhook 接收端点 (`/api/webhook/feishu`)
- [x] 5.2 Challenge 验证响应
- [x] 5.3 事件解析服务
- [x] 5.4 FeishuClient 封装（HTTP 直接调用）
## 6. GitHub 集成
- [x] 6.1 Webhook 接收端点 (`/api/webhook/github`)
- [x] 6.2 PR Merge 事件处理
## 7. 任务容器实现
- [x] 7.1 任务容器 Dockerfile
- [x] 7.2 容器配置模块 (TaskConfig)
- [x] 7.3 Git 操作模块 (GitOperations)
- [x] 7.4 Claude Code 执行器 (ClaudeRunner)
- [x] 7.5 回调客户端 (CallbackClient)
- [x] 7.6 任务执行器主模块 (TaskRunner)
## 8. 任务调度器
- [x] 8.1 Docker 容器管理服务 (TaskScheduler)
- [x] 8.2 容器启动/停止接口
- [x] 8.3 容器日志/状态查询
## 9. 部署与运维
- [x] 9.1 主服务 Dockerfile
- [x] 9.2 docker-compose.yml 编排
- [x] 9.3 .env.example 配置模板
- [x] 9.4 setup.sh 一键部署脚本
- [x] 9.5 .dockerignore 优化
## 10. 测试与文档
- [x] 10.1 pytest 测试配置
- [x] 10.2 API 测试用例
- [x] 10.3 README.md 项目文档