# Project Context
## Purpose
Friday 是一个 AI 驱动的敏捷开发自动化系统，旨在无缝集成飞书项目管理和 Claude Code，实现开发任务的自动化执行。
核心目标：
- 自动化监听和响应飞书工作项状态变化
- 利用 AI (Claude Code) 自动生成实现方案和代码
- 提供完整的任务状态流转管理和人工审核机制
- 通过 Docker 容器隔离确保任务执行环境的安全与独立
## Tech Stack
- **Language**: Python 3.11+ (Backend), TypeScript (Frontend)
- **Framework**: FastAPI (Backend), Vue 3 + Vite (Frontend), SQLModel (ORM)
- **Database**: SQLite (aiosqlite)
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
 - `server/`: Backend application (FastAPI, Python)
 - `web/`: Frontend application (Vue 3, TypeScript)
- **API Layer**: `server/src/friday/routes/` - 处理 HTTP 请求和路由
- **Service Layer**: `server/src/friday/services/` - 包含业务逻辑（如飞书集成、调度器、加密服务）
- **Data Layer**: `server/src/friday/models/` & `server/src/friday/database.py` - 定义数据模型和数据库交互
- **Task Runner**: `server/task/` - 独立的 Docker 容器环境，用于执行具体的 AI 编码任务
- **Webhook Driven**: 主要通过飞书和 GitHub 的 Webhook 触发业务流程
### Testing Strategy
- 使用 `pytest` 进行单元测试和集成测试
- `pytest-asyncio` 用于异步测试
- 目标覆盖率：关键业务逻辑应有较高覆盖率
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
