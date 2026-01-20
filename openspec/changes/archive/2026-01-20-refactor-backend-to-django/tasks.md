# Implementation Tasks
## 1. 项目初始化
- [x] 1.1 创建 Django 6.0 项目结构
- [x] 1.2 配置 pyproject.toml 依赖（Django, DRF, simplejwt, django-environ, uvicorn, adrf 等）
- [x] 1.3 配置 settings.py（数据库、认证、中间件、环境变量）
- [x] 1.4 配置 ASGI 入口（Uvicorn + Django）
- [x] 1.5 配置 django-environ 环境变量管理（完整迁移现有配置）
- [x] 1.6 配置 structlog 与 Django logging 集成
## 2. Django Apps 结构
- [x] 2.1 创建 `core` app（通用模型和工具）
- [x] 2.2 创建 `projects` app（项目和仓库管理）
- [x] 2.3 创建 `tasks` app（任务管理）
- [x] 2.4 创建 `webhooks` app（Webhook 处理）
- [x] 2.5 创建 `authentication` app（认证模块 - 集成到 core app）
## 3. 模型迁移
- [x] 3.1 实现 User 模型（扩展 Django AbstractUser）
- [x] 3.2 实现 Project 模型（含 claude_config JSON 字段）
- [x] 3.3 实现 Repository 模型（ForeignKey to Project）
- [x] 3.4 实现 Credential 模型（加密字段）
- [x] 3.5 实现 Task 模型（状态枚举、关联关系）
- [x] 3.6 实现 WebhookLog 模型
- [x] 3.7 实现 SystemSettings 模型
- [x] 3.8 生成 Django migrations
- [x] 3.9 配置 Django Admin 管理界面 - **不需要**：本系统是管理服务本身
## 4. 服务层迁移
- [x] 4.1 迁移 crypto.py（Fernet 加密服务）
- [x] 4.2 迁移 feishu.py（飞书 API 客户端）
- [x] 4.3 迁移 scheduler.py（Docker 任务调度器）
- [x] 4.4 迁移 claude_config.py（Claude 配置服务）
## 5. 认证模块
- [x] 5.1 配置 djangorestframework-simplejwt
- [x] 5.2 实现登录视图（TokenObtainPairView）
- [x] 5.3 实现 Token 刷新视图
- [x] 5.4 实现用户信息视图
- [x] 5.5 实现密码修改视图
- [x] 5.6 配置 URL 路由 `/api/auth/`
## 6. 项目管理 API
- [x] 6.1 实现 ProjectSerializer
- [x] 6.2 实现 RepositorySerializer
- [x] 6.3 实现 CredentialSerializer（隐藏敏感字段）
- [x] 6.4 实现 ProjectViewSet（CRUD）
- [x] 6.5 实现 RepositoryViewSet（嵌套路由）
- [x] 6.6 实现凭证管理视图
- [x] 6.7 配置 URL 路由 `/api/projects/`
## 7. 任务管理 API
- [x] 7.1 实现 TaskSerializer
- [x] 7.2 实现 TaskViewSet（CRUD）
- [x] 7.3 实现任务状态转换视图（transition）
- [x] 7.4 实现任务执行视图（execute）- 完整容器调度
- [x] 7.5 实现任务日志查询视图
- [x] 7.6 配置 URL 路由 `/api/tasks/`
## 8. Webhook 模块
- [x] 8.1 实现飞书 Webhook 视图（URL 路由和基本接收）
- [x] 8.2 实现飞书 Challenge 验证
- [x] 8.3 实现 GitHub Webhook 视图（URL 路由和基本接收）
- [x] 8.4 实现 WebhookLogSerializer
- [x] 8.5 实现 Webhook 日志查询视图
- [x] 8.6 配置 URL 路由 `/api/webhook/`
- [x] 8.7 实现飞书 Webhook 事件处理逻辑（WorkitemCreate/Status/Comment/Update）
- [x] 8.8 实现 GitHub PR 合并后任务状态更新
## 9. 系统设置 API
- [x] 9.1 实现 SystemSettingsSerializer
- [x] 9.2 实现 ClaudeConfigSerializer
- [x] 9.3 实现系统设置视图
- [x] 9.4 配置 URL 路由 `/api/settings/`
## 10. 部署配置
- [x] 10.1 更新 Dockerfile（使用 Gunicorn + Uvicorn workers）
- [x] 10.2 更新 docker-compose.yml
- [x] 10.3 更新 .env.example
- [x] 10.4 配置静态文件收集（collectstatic）- **不需要**：本系统是 API 服务，无静态文件
- [x] 10.5 更新 setup.sh 部署脚本 - **不需要**：基于 Dockerfile 部署
## 11. 测试
- [x] 11.1 配置 pytest-django
- [x] 11.2 编写模型单元测试 - 已实现 `server/tests/test_crypto.py`
- [x] 11.3 编写 API 集成测试 - 已实现 `server/tests/test_projects.py`, `test_tasks.py`, `test_settings.py`, `test_repositories.py`
- [x] 11.4 编写认证流程测试 - 已实现 `server/tests/test_auth.py`
- [x] 11.5 编写 Webhook 处理测试 - 已实现 `server/tests/test_webhooks.py`
- [x] 11.6 前后端集成验证 - 已完成
## 12. 文档和清理
- [x] 12.1 更新 README.md - 已更新为 Django 技术栈说明
- [x] 12.2 更新 openspec/project.md 技术栈描述 - 已更新
- [x] 12.3 编写 Django 开发指南 - 已包含在 README.md 中
- [x] 12.4 删除旧的 FastAPI 代码（server/src/friday）- **保留**：用户确认不删除
- [x] 12.5 删除 Alembic 配置和迁移文件 - **保留**：用户确认不删除
---
## 迁移进度摘要
**总体完成度: 100%**
### ✅ 已完成
- 项目结构和配置
- 所有 Django Apps 创建
- 数据模型迁移
- 认证模块（JWT）
- 基础 CRUD API（Projects, Repositories, Tasks, Settings）
- Webhook 路由和日志记录
- 容器调度服务 (scheduler.py) - 任务执行的核心
- 飞书 API 客户端 (feishu.py) - 飞书集成核心
- Claude 配置服务 (claude_config.py)
- Webhook 业务逻辑处理 - 创建任务、状态同步
- GitHub PR 合并处理
- 完整测试覆盖
- 文档更新
