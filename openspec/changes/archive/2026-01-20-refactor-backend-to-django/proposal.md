# Change: Migrate Backend from FastAPI + SQLModel to Django 6.0
## Why
当前后端使用 FastAPI + SQLModel 构建，虽然性能优秀，但随着项目复杂度增加，存在以下挑战：
1. **ORM 成熟度**: SQLModel 相对较新，生态系统和工具链不如 Django ORM 完善
2. **Admin 后台缺失**: 缺乏开箱即用的管理界面，运维和调试成本高
3. **认证系统**: 需要手动实现完整的用户认证、权限管理系统
4. **迁移工具**: Alembic 需要额外配置，而 Django 的迁移系统更加成熟和自动化
5. **长期维护**: Django 作为成熟框架，社区支持更强，长期维护成本更低
Django 6.0 带来了显著的性能提升和现代化特性，是进行此迁移的最佳时机。
## What Changes
### **BREAKING** - 完整后端框架迁移
- **框架迁移**: FastAPI → Django 6.0 + Django REST Framework
- **ORM 迁移**: SQLModel → Django ORM
- **ASGI 服务器**: 继续使用 Uvicorn（与 FastAPI 一致）
- **数据库**: 继续使用 SQLite（无需数据迁移）
- **异步支持**: 利用 Django 6.0 原生 async 视图 + Uvicorn ASGI
- **认证系统**: 迁移到 Django 内置认证 + JWT (djangorestframework-simplejwt)
- **环境变量**: 完整迁移所有配置项到 django-environ
### 模块迁移对照
| 当前 (FastAPI) | 迁移后 (Django) |
|---|---|
| `routes/*.py` | `views/*.py` + `urls.py` |
| `models/*.py` (SQLModel) | `models.py` (Django ORM) |
| `dependencies/auth.py` | `authentication.py` + Django Auth |
| `services/*.py` | `services/*.py` (保持) |
| `alembic/` | `migrations/` (Django 原生) |
| `config.py` (Pydantic Settings) | `settings.py` + django-environ |
| `database.py` | Django 内置数据库配置 |
### 新增能力
- Django Admin 管理后台
- 更完善的权限控制系统
- 内置的 CSRF 保护
- 更成熟的测试框架
## Impact
- **Affected specs**:
 - `ai-dev-automation` - API 端点路径和响应格式保持兼容
 - `feishu-integration` - Webhook 处理逻辑迁移
 - `frontend-architecture` - API 调用保持兼容（无需前端改动）
- **Affected code**:
 - `server/src/friday/` - 完全重构
 - `server/pyproject.toml` - 依赖变更
 - `server/Dockerfile` - 更新启动命令
 - `docker-compose.yml` - 服务配置调整
- **Breaking changes**:
 - API 响应格式可能有细微差异（需确保前端兼容）
 - 认证 Token 格式变更（需重新登录）
