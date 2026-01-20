# Design: Backend Migration to Django 6.0
## Context
### 背景
Friday 后端当前使用 FastAPI + SQLModel + aiosqlite 构建。随着功能增加和长期维护需求，决定迁移到更成熟的 Django 框架。
### 约束
- **API 兼容性**: 前端 Vue 应用和 Task Runner 不应需要改动
- **数据库**: 继续使用 SQLite，暂不考虑数据迁移
- **异步需求**: 飞书 Webhook、任务调度等需要异步处理能力
- **第三方集成**: 飞书 SDK、GitPython、Docker SDK 需继续兼容
## Goals / Non-Goals
### Goals
- 完成从 FastAPI + SQLModel 到 Django 6.0 + DRF 的完整迁移
- 使用 Uvicorn 作为 ASGI 服务器，保持高性能异步能力
- **保持 REST API 100% 兼容**（路径、方法、请求/响应格式完全一致）
- 利用 Django Admin 提供管理后台
- 使用 Django 原生迁移系统替代 Alembic
- 集成 drf-spectacular 提供 Swagger/OpenAPI 文档
### Non-Goals
- 不迁移现有数据（全新数据库）
- 不更改前端代码（API 保持兼容）
- 不更改 Task Runner 代码（回调 API 保持兼容）
- 不引入 Celery 等额外异步任务队列（保持简单）
---
## API 兼容性分析
### 现有 API 端点清单
经分析，当前系统共有 **6 个功能模块，40+ 个 API 端点**：
| 模块 | 端点数 | 路径前缀 | 说明 |
|---|---|---|---|
| Auth | 5 | `/api/auth/` | 登录、登出、刷新、用户信息、改密 |
| Projects | 14 | `/api/projects/` | 项目 CRUD、仓库关联、飞书配置、Claude 配置 |
| Repositories | 7 | `/api/repositories/` | 仓库 CRUD、凭证管理 |
| Tasks | 12 | `/api/tasks/` | 任务 CRUD、状态转换、执行、日志 |
| Webhooks | 2 | `/api/webhook/` | 飞书/GitHub Webhook |
| Settings | 5 | `/api/settings/` | 系统设置 CRUD |
### 兼容性策略
**结论：API 可以 100% 保持兼容，无需修改前端和 Task Runner**
DRF 可以精确控制：
1. **路径格式**: 使用 `@action` 装饰器和自定义路由
2. **请求格式**: Serializer 完全控制字段名和验证
3. **响应格式**: Serializer 控制输出字段，与 Pydantic 模型一致
4. **HTTP 状态码**: DRF Response 支持自定义状态码
5. **Cookie 处理**: DRF Response 支持 set_cookie
### 需要特别处理的端点
| 端点 | 特殊处理 |
|---|---|
| `POST /api/auth/login` | Cookie 设置 refresh_token |
| `POST /api/auth/refresh` | 从 Cookie 读取 refresh_token |
| `POST /api/webhook/feishu` | 原始 body 解析、Challenge 验证 |
| `POST /api/tasks/{id}/status` | Task Runner 回调，需保持完全兼容 |
| `POST /api/repositories/{id}/credential/access-token` | Form 表单提交 |
---
## Decisions
### Decision 1: 纯 Django REST Framework 方案
**选择**: 使用 Django 6.0 + Django REST Framework，不使用 Django Ninja
**理由**:
- DRF 是最成熟的 Django REST 框架，生态丰富
- Serializer 机制可精确控制请求/响应格式
- ViewSet + Router 提供 RESTful 最佳实践
- 社区支持强，问题排查容易
**核心依赖**:
```toml
[project]
dependencies = [
 "django>=6.0",
 "djangorestframework>=3.15",
 "djangorestframework-simplejwt>=5.3",
 "drf-spectacular>=0.27",
 "django-environ>=0.11",
 "uvicorn[standard]>=0.30",
 "httpx>=0.27",
 "structlog>=24.0",
 "cryptography>=42.0",
 "gitpython>=3.1",
 "docker>=7.0",
]
```
### Decision 2: Uvicorn + Django ASGI
**选择**: 使用 Uvicorn 作为 ASGI 服务器运行 Django
**理由**:
- Uvicorn 是 FastAPI 默认服务器，团队已熟悉
- 高性能异步 I/O，与 FastAPI 性能接近
- Django 6.0 原生支持 ASGI，无需额外适配
**启动命令**:
```bash
# 开发环境
uvicorn friday.asgi:application --reload --host 0.0.0.0 --port 8000
# 生产环境
uvicorn friday.asgi:application --host 0.0.0.0 --port 8000 --workers 4
```
**ASGI 配置** (`friday/asgi.py`):
```python
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'friday.settings')
application = get_asgi_application
```
### Decision 3: drf-spectacular 集成 Swagger
**选择**: 使用 drf-spectacular 自动生成 OpenAPI 3.0 文档
**理由**:
- DRF 生态中最活跃的 OpenAPI 方案
- 自动从 Serializer 生成 Schema
- 支持 Swagger UI 和 ReDoc
- 可自定义扩展
**配置**:
```python
# settings.py
INSTALLED_APPS = [
 ...
 'drf_spectacular',
]
REST_FRAMEWORK = {
 'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
SPECTACULAR_SETTINGS = {
 'TITLE': 'Friday API',
 'DESCRIPTION': 'AI-powered Development Automation System',
 'VERSION': '1.0.0',
 'SERVE_INCLUDE_SCHEMA': False,
}
```
**URL 配置**:
```python
# urls.py
from drf_spectacular.views import (
 SpectacularAPIView,
 SpectacularSwaggerView,
 SpectacularRedocView,
)
urlpatterns = [
 ...
 # OpenAPI Schema
 path('api/schema/', SpectacularAPIView.as_view, name='schema'),
 # Swagger UI
 path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
 # ReDoc
 path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
```
**访问地址**:
- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI JSON: `http://localhost:8000/api/schema/`
### Decision 4: JWT 认证方案
**选择**: djangorestframework-simplejwt + Cookie 存储 Refresh Token
**配置**:
```python
# settings.py
from datetime import timedelta
REST_FRAMEWORK = {
 'DEFAULT_AUTHENTICATION_CLASSES': [
 'rest_framework_simplejwt.authentication.JWTAuthentication',
 ],
}
SIMPLE_JWT = {
 'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
 'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
 'AUTH_HEADER_TYPES': ('Bearer',),
 'USER_ID_FIELD': 'id',
 'USER_ID_CLAIM': 'sub',
}
```
**自定义 Login View** (保持与现有 API 兼容):
```python
class LoginView(APIView):
 permission_classes = [AllowAny]
 def post(self, request):
 serializer = LoginSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 user = serializer.validated_data['user']
 refresh = RefreshToken.for_user(user)
 access_token = str(refresh.access_token)
 response = Response({
 'access_token': access_token,
 'user': UserSerializer(user).data,
 })
 response.set_cookie(
 key='refresh_token',
 value=str(refresh),
 httponly=settings.COOKIE_HTTPONLY,
 samesite=settings.COOKIE_SAMESITE,
 secure=settings.COOKIE_SECURE,
 max_age=7 * 24 * 60 * 60,
 )
 return response
```
### Decision 5: 项目结构设计
**选择**: 按功能模块划分 Django Apps
```
server/
├── manage.py
├── friday/
│ ├── settings.py
│ ├── urls.py
│ ├── asgi.py
│ └── apps/
│ ├── core/ # User, SystemSettings
│ ├── auth/ # 认证端点
│ ├── projects/ # Project, Repository, Credential
│ ├── tasks/ # Task
│ ├── webhooks/ # Webhook 处理
│ └── services/ # 业务服务
```
### Decision 6: 环境变量迁移
| 当前环境变量 | Django 配置 | 说明 |
|---|---|---|
| `FRIDAY_DEBUG` | `DEBUG` | 调试模式 |
| `FRIDAY_PORT` | Uvicorn 启动参数 | 服务端口 |
| `FRIDAY_WEB_PORT` | 保持不变 | Docker Compose |
| `FRIDAY_ENCRYPTION_KEY` | `FRIDAY_ENCRYPTION_KEY` | 加密密钥 |
| `SECRET_KEY` | `SECRET_KEY` | Django 密钥 |
| `JWT_SECRET_KEY` | `SIMPLE_JWT.SIGNING_KEY` | JWT 签名 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `SIMPLE_JWT.ACCESS_TOKEN_LIFETIME` | Token 过期 |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `SIMPLE_JWT.REFRESH_TOKEN_LIFETIME` | Refresh 过期 |
| `COOKIE_SECURE` | `COOKIE_SECURE` | Cookie 安全 |
| `COOKIE_SAMESITE` | `COOKIE_SAMESITE` | SameSite |
| `COOKIE_HTTPONLY` | `COOKIE_HTTPONLY` | HttpOnly |
| `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | 保持不变 |
| `ANTHROPIC_BASE_URL` | `ANTHROPIC_BASE_URL` | 保持不变 |
| `FRIDAY_GITHUB_WEBHOOK_SECRET` | `GITHUB_WEBHOOK_SECRET` | Webhook 密钥 |
---
## 功能模块迁移方案
### 模块 1: Auth（认证）
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/auth/login` | 登录，返回 access_token，Cookie 设置 refresh_token |
| POST | `/api/auth/logout` | 登出，清除 Cookie |
| POST | `/api/auth/refresh` | 刷新 Token |
| GET | `/api/auth/me` | 获取当前用户信息 |
| POST | `/api/auth/change-password` | 修改密码 |
**DRF 实现要点**:
- `LoginView`: 手动生成 JWT，设置 Cookie
- `RefreshView`: 从 Cookie 读取 refresh_token
- `LogoutView`: 删除 Cookie
### 模块 2: Projects（项目管理）
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| GET/POST | `/api/projects/` | 列表/创建 |
| GET/PATCH/DELETE | `/api/projects/{id}` | 详情/更新/删除 |
| POST/DELETE | `/api/projects/{id}/repositories/{repo_id}` | 关联/解除仓库 |
| GET | `/api/projects/{id}/repositories` | 列出关联仓库 |
| GET/PUT/DELETE | `/api/projects/{id}/feishu-config` | 飞书配置 CRUD |
| POST | `/api/projects/{id}/feishu-config/test` | 测试飞书配置 |
| POST | `/api/projects/{id}/refresh-webhook-token` | 刷新 Token |
| PUT | `/api/projects/{id}/webhook-token` | 自定义 Token |
| GET/PUT/DELETE | `/api/projects/{id}/claude-config` | Claude 配置 |
**DRF 实现要点**:
- 使用 `ModelViewSet` + `@action` 装饰器
- 嵌套路由使用自定义 URL patterns
### 模块 3: Repositories（仓库管理）
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| GET/POST | `/api/repositories/` | 列表/创建（含凭证） |
| GET/PATCH/DELETE | `/api/repositories/{id}` | 详情/更新/删除 |
| GET | `/api/repositories/{id}/credential` | 获取凭证 |
| POST | `/api/repositories/{id}/credential/access-token` | 设置 Token (Form) |
| DELETE | `/api/repositories/{id}/credential` | 删除凭证 |
**DRF 实现要点**:
- `POST /credential/access-token` 使用 `FormParser`
### 模块 4: Tasks（任务管理）
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| GET/POST | `/api/tasks/` | 列表（支持过滤）/创建 |
| GET/PATCH/DELETE | `/api/tasks/{id}` | 详情/更新/删除 |
| GET | `/api/tasks/work-item/{work_item_id}` | 按工作项查询 |
| POST | `/api/tasks/{id}/transition/{status}` | 状态转换 |
| POST | `/api/tasks/{id}/execute` | 执行任务 |
| POST | `/api/tasks/{id}/status` | 容器状态回调 ⚠️ |
| POST | `/api/tasks/{id}/stop` | 停止任务 |
| GET | `/api/tasks/{id}/logs` | 获取日志 |
| GET | `/api/tasks/{id}/container-status` | 容器状态 |
**⚠️ 关键**: `POST /api/tasks/{id}/status` 是 Task Runner 的回调端点，必须保持完全兼容。
### 模块 5: Webhooks
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/webhook/feishu` | 飞书 Webhook |
| POST | `/api/webhook/github` | GitHub Webhook |
**DRF 实现要点**:
- 飞书需处理 `url_verification` Challenge
- 使用 `request.body` 获取原始请求体
### 模块 6: Settings（系统设置）
**端点清单**:
| 方法 | 路径 | 功能 |
|---|---|---|
| GET/POST | `/api/settings/` | 列表/创建 |
| GET/PUT/DELETE | `/api/settings/{key}` | 获取/更新/删除 |
---
## Risks / Trade-offs
### Risk 1: API 兼容性遗漏
**风险**: 某些细微的响应格式差异可能影响前端
**缓解**:
- 编写 API 兼容性测试，对比新旧响应
- 使用 Serializer 精确控制字段名和格式
### Risk 2: 异步处理差异
**风险**: Django 的异步支持不如 FastAPI 原生
**缓解**:
- 使用 `sync_to_async` 包装同步代码
- Docker SDK 在线程池中运行
---
## Migration Plan
### Phase: 基础设施
1. 初始化 Django 项目结构
2. 配置 settings.py 和环境变量
3. 配置 Uvicorn ASGI 入口
4. 配置 DRF 和 JWT 认证
5. 集成 drf-spectacular (Swagger)
6. 配置 Django Admin
### Phase: 模型迁移
1. 实现 User 模型（扩展 AbstractUser）
2. 实现 Project, Repository, Credential 模型
3. 实现 Task 模型（含状态枚举）
4. 实现 WebhookLog, WorkItemLog 模型
5. 实现 SystemSettings 模型
6. 生成 Django migrations
7. 配置 Admin 管理界面
### Phase: 服务层迁移
1. 迁移 crypto.py
2. 迁移 feishu.py
3. 迁移 scheduler.py
4. 迁移 claude_config.py
### Phase: API 迁移（按功能模块）
1. Auth 模块
2. Projects 模块
3. Repositories 模块
4. Tasks 模块
5. Webhooks 模块
6. Settings 模块
### Phase: 部署更新
1. 更新 Dockerfile
2. 更新 docker-compose.yml
3. 更新 .env.example
4. 清理旧代码
---
## Open Questions
1. **Django Admin 权限**: 是否需要细粒度的 Admin 权限控制？
2. **API 版本控制**: 是否需要引入 API 版本前缀（如 `/api/v1/`）？
3. **WebSocket 支持**: 未来是否需要 Django Channels 支持实时通知？
