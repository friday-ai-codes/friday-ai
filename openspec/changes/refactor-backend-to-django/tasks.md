# Implementation Tasks
## 1. 项目初始化
- 1.1 创建 Django 6.0 项目结构
- 1.2 配置 pyproject.toml 依赖（Django, DRF, simplejwt, django-environ, uvicorn, adrf 等）
- 1.3 配置 settings.py（数据库、认证、中间件、环境变量）
- 1.4 配置 ASGI 入口（Uvicorn + Django）
- 1.5 配置 django-environ 环境变量管理（完整迁移现有配置）
- 1.6 配置 structlog 与 Django logging 集成
## 2. Django Apps 结构
- 2.1 创建 `core` app（通用模型和工具）
- 2.2 创建 `projects` app（项目和仓库管理）
- 2.3 创建 `tasks` app（任务管理）
- 2.4 创建 `webhooks` app（Webhook 处理）
- 2.5 创建 `authentication` app（认证模块）
## 3. 模型迁移
- 3.1 实现 User 模型（扩展 Django AbstractUser）
- 3.2 实现 Project 模型（含 claude_config JSON 字段）
- 3.3 实现 Repository 模型（ForeignKey to Project）
- 3.4 实现 Credential 模型（加密字段）
- 3.5 实现 Task 模型（状态枚举、关联关系）
- 3.6 实现 WebhookLog 模型
- 3.7 实现 SystemSettings 模型
- 3.8 生成 Django migrations
- 3.9 配置 Django Admin 管理界面
## 4. 服务层迁移
- 4.1 迁移 crypto.py（Fernet 加密服务）
- 4.2 迁移 feishu.py（飞书 API 客户端）
- 4.3 迁移 scheduler.py（Docker 任务调度器）
- 4.4 迁移 claude_config.py（Claude 配置服务）
## 5. 认证模块
- 5.1 配置 djangorestframework-simplejwt
- 5.2 实现登录视图（TokenObtainPairView）
- 5.3 实现 Token 刷新视图
- 5.4 实现用户信息视图
- 5.5 实现密码修改视图
- 5.6 配置 URL 路由 `/api/auth/`
## 6. 项目管理 API
- 6.1 实现 ProjectSerializer
- 6.2 实现 RepositorySerializer
- 6.3 实现 CredentialSerializer（隐藏敏感字段）
- 6.4 实现 ProjectViewSet（CRUD）
- 6.5 实现 RepositoryViewSet（嵌套路由）
- 6.6 实现凭证管理视图
- 6.7 配置 URL 路由 `/api/projects/`
## 7. 任务管理 API
- 7.1 实现 TaskSerializer
- 7.2 实现 TaskViewSet（CRUD）
- 7.3 实现任务状态转换视图（transition）
- 7.4 实现任务执行视图（execute）- async
- 7.5 实现任务日志查询视图
- 7.6 配置 URL 路由 `/api/tasks/`
## 8. Webhook 模块
- 8.1 实现飞书 Webhook 视图
- 8.2 实现飞书 Challenge 验证
- 8.3 实现 GitHub Webhook 视图
- 8.4 实现 WebhookLogSerializer
- 8.5 实现 Webhook 日志查询视图
- 8.6 配置 URL 路由 `/api/webhook/`
## 9. 系统设置 API
- 9.1 实现 SystemSettingsSerializer
- 9.2 实现 ClaudeConfigSerializer
- 9.3 实现系统设置视图
- 9.4 配置 URL 路由 `/api/settings/`
## 10. 部署配置
- 10.1 更新 Dockerfile（使用 Gunicorn + Uvicorn workers）
- 10.2 更新 docker-compose.yml
- 10.3 更新 .env.example
- 10.4 配置静态文件收集（collectstatic）
- 10.5 更新 setup.sh 部署脚本
## 11. 测试
- 11.1 配置 pytest-django
- 11.2 编写模型单元测试
- 11.3 编写 API 集成测试
- 11.4 编写认证流程测试
- 11.5 编写 Webhook 处理测试
- 11.6 前后端集成验证
## 12. 文档和清理
- 12.1 更新 README.md
- 12.2 更新 openspec/project.md 技术栈描述
- 12.3 编写 Django 开发指南
- 12.4 删除旧的 FastAPI 代码
- 12.5 删除 Alembic 配置和迁移文件
