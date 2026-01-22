# Project Context
## Purpose
Friday 是一个 AI 驱动的敏捷开发自动化系统，旨在无缝集成飞书项目管理和 Claude Code，实现开发任务的自动化执行。
核心目标：
- 自动化监听和响应飞书工作项状态变化
- 利用 AI (Claude Code) 自动生成实现方案和代码
- 提供完整的任务状态流转管理和人工审核机制
- 通过 Docker 容器隔离确保任务执行环境的安全与独立
## Tech Stack
- **Language**: Python 3.14+ (Backend), TypeScript (Frontend)
- **Framework**: Django 6.0 + Django REST Framework (Backend), Vue 3 + Vite (Frontend)
- **Authentication**: djangorestframework-simplejwt (JWT)
- **Database**: SQLite
- **Production Server**: Gunicorn + Uvicorn (ASGI Workers)
- **Containerization**: Docker, Docker Compose
- **Integrations**:
 - Feishu/Lark Open Platform (SDK: lark-oapi)
 - Anthropic API (Claude Code)
 - Git (GitPython)
- **Tools**: UV (Package Management), Pytest (Testing), Ruff (Linting)
## Project Conventions
### Code Style
- 遵循 PEP 8 规范
- 使用 Ruff 进行代码格式化和 Lint 检查
- 类型注解：Python 代码必须包含完整的 Type Hints
- 异步优先：I/O 密集型操作应使用 `async/await`
### Architecture Patterns
- **Monorepo Structure**:
 - `server/`: Backend application (Django, Python)
 - `web/`: Frontend application (Vue 3, TypeScript)
- **Django Apps**:
 - `server/core/`: 核心应用 (认证、健康检查、系统设置)
 - `server/projects/`: 项目和仓库管理
 - `server/tasks/`: 任务生命周期管理
 - `server/webhooks/`: Webhook 处理 (飞书、GitHub)
- **Service Layer**: `server/services/` - 包含业务逻辑（飞书 API 客户端、Docker 调度器、Claude 配置服务）
- **Task Runner**: `server/task/` - 独立的 Docker 容器环境，用于执行具体的 AI 编码任务
- **Webhook Driven**: 主要通过飞书和 GitHub 的 Webhook 触发业务流程
### Database Migration Guidelines
数据库 Schema 变更 **必须** 通过 Django 迁移管理：
1. **修改 Model 后生成迁移**：
 ```bash
 cd server && uv run python manage.py makemigrations
 ```
2. **检查迁移脚本**：`server/<app>/migrations/`
3. **本地测试迁移**：
 ```bash
 uv run python manage.py migrate
 ```
4. **自动迁移机制**：Docker 容器启动时会自动执行 `python manage.py migrate --noinput`
5. **回滚操作**：
 ```bash
 uv run python manage.py migrate <app> <migration_name>
 ```
> **重要**：AI Agent 在完成后端代码变更涉及 Model 修改后，**必须** 生成对应的 Django 迁移脚本
### Testing Strategy
- 使用 `pytest` 进行单元测试和集成测试
- `pytest-asyncio` 用于异步测试
- 目标覆盖率：关键业务逻辑应有较高覆盖率
### Logging Guidelines
日志使用 **structlog** 作为统一的日志库：
1. **获取 logger**：
 ```python
 import structlog
 logger = structlog.get_logger(__name__)
 ```
2. **日志级别**：
 - `DEBUG`: 详细调试信息
 - `INFO`: 常规操作信息（请求处理、状态变更等）
 - `WARNING`: 警告信息（可恢复的异常情况）
 - `ERROR`: 错误信息（需要关注的问题）
3. **结构化日志**：
 ```python
 logger.info("处理事件", event_type=event_type, project_key=project_key)
 ```
4. **日志格式**：
 - 开发模式（`DEBUG=true`）: 彩色控制台输出
 - 生产模式: JSON 格式，便于日志收集
> **重要**：禁止使用标准 `logging` 模块，统一使用 `structlog`
### Git Workflow
- 基于 Pull Request 的工作流
- 分支命名规范建议：`feat/`, `fix/`, `docs/`, `refactor/`
- 提交信息应清晰描述变更内容
## Domain Context
- **Task Lifecycle**: 任务状态流转是核心逻辑 (PENDING → PLANNING → ... → MERGED/FAILED)
- **Feishu Integration**: 系统通过 Webhook 接收飞书事件，并需维护飞书应用凭证
- **Sandboxed Execution**: 每个任务在独立的容器中运行，需管理容器生命周期和资源
## Important Constraints
- 必须保护敏感信息（如 API Keys, 飞书凭证），使用加密存储 (`FRIDAY_ENCRYPTION_KEY`)
- 确保 Docker 环境在部署机器上可用
- 依赖外部 API (Anthropic, Feishu)，需处理网络异常和限流
## External Dependencies
- **Feishu/Lark**: 项目管理和消息通知
- **Anthropic Claude**: AI 代码生成引擎
- **GitHub/Git**: 代码版本控制
