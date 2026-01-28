# Design: 按领域重构 Django Apps
## Context
Friday 项目采用 Django + DRF 后端 + Vue 3 前端架构。随着功能增加，现有的 App 划分已无法清晰反映业务领域，需要按照「一个 App = 一个业务领域」的原则重构。
## Goals / Non-Goals
**Goals:**
- 按业务领域重新划分 Django Apps
- 保持数据库表结构不变（使用 db_table 指定）
- API 路径更语义化
- 前后端同步更新
**Non-Goals:**
- 不修改业务逻辑
- 不添加新功能
- 不进行数据迁移
## Decisions
### Decision 1: App 划分方案
**选择:** 6 个领域 App
```
server/
├── accounts/ # 用户认证
├── settings/ # 系统配置
├── projects/ # 项目管理（轻量）
├── repositories/ # Git 仓库管理
├── feishu/ # 飞书集成（独立领域）
├── tasks/ # AI 任务
└── common/ # 共享工具
```
**理由:**
- 每个 App 职责单一，高内聚低耦合
- 飞书作为独立集成领域，便于未来添加其他集成（GitHub、Jira）
- 符合业界最佳实践（参考 Sentry、Taiga）
### Decision 2: 数据库表名保持不变
**选择:** 使用 `Meta.db_table` 保持原表名
**理由:**
- 避免数据迁移风险
- 渐进式重构，降低出错概率
**示例:**
```python
# repositories/models.py
class Repository(models.Model):
 class Meta:
 db_table = "repositories" # 保持原表名
```
### Decision 3: API 路径设计
**选择:** 按领域组织 API 路径
| 领域 | 路径前缀 | 说明 |
|------|----------|------|
| accounts | `/api/accounts/` | 认证、用户管理 |
| settings | `/api/settings/` | 系统配置 |
| projects | `/api/projects/` | 项目 CRUD |
| repositories | `/api/repositories/` | 仓库 CRUD |
| feishu | `/api/feishu/` | 飞书集成全部功能 |
| tasks | `/api/tasks/` | 任务管理 |
**理由:**
- 语义清晰，符合 RESTful 设计
- 飞书相关功能统一入口，便于权限控制和文档生成
## Directory Structure
### 后端新结构
```
server/
├── accounts/ # 用户认证
│ ├── __init__.py
│ ├── apps.py
│ ├── models.py # User
│ ├── views.py # Login, Logout, Me, ChangePassword
│ ├── serializers.py
│ ├── urls.py
│ └── migrations/
│
├── settings/ # 系统配置
│ ├── __init__.py
│ ├── apps.py
│ ├── models.py # SystemSetting, SettingKeys
│ ├── views.py
│ ├── serializers.py
│ ├── urls.py
│ └── migrations/
│
├── projects/ # 项目管理（轻量化）
│ ├── __init__.py
│ ├── apps.py
│ ├── models.py # Project, ProjectRepository
│ ├── views.py
│ ├── serializers.py
│ ├── urls.py
│ └── migrations/
│
├── repositories/ # Git 仓库
│ ├── __init__.py
│ ├── apps.py
│ ├── models.py # Repository, GitCredential
│ ├── views.py
│ ├── serializers.py
│ ├── urls.py
│ └── migrations/
│
├── feishu/ # 飞书集成
│ ├── __init__.py
│ ├── apps.py
│ ├── models.py # TriggerLog (合并日志)
│ ├── views.py # Webhook 处理, 配置管理, 日志查询
│ ├── serializers.py
│ ├── urls.py
│ ├── client.py # 飞书 API 客户端
│ ├── exceptions.py # FeishuConfigurationError
│ └── migrations/
│
├── tasks/ # AI 任务（保持不变）
│ └── ...
│
├── common/ # 共享模块
│ ├── __init__.py
│ ├── encryption.py # 加密工具
│ ├── exceptions.py # 通用异常
│ └── pagination.py # 分页
│
└── friday/ # 项目配置
 ├── settings.py
 └── urls.py
```
### 前端调整
```
web/src/
├── api/
│ ├── accounts.ts # 原 auth.ts，路径改为 /accounts
│ ├── settings.ts # 路径保持不变
│ ├── projects.ts # 移除飞书相关方法
│ ├── repositories.ts # 保持不变
│ ├── feishu.ts # 新增：飞书配置、日志
│ └── tasks.ts # 保持不变
│
├── types/
│ └── index.ts # 按领域重新分组注释
│
└── stores/
 └── auth.ts # 更新 API 导入
```
## API Mapping
### accounts (原 core/auth)
| 方法 | 当前路径 | 新路径 |
|------|----------|--------|
| POST | `/api/auth/login` | `/api/accounts/login` |
| POST | `/api/auth/logout` | `/api/accounts/logout` |
| POST | `/api/auth/refresh` | `/api/accounts/refresh` |
| GET | `/api/auth/me` | `/api/accounts/me` |
| POST | `/api/auth/change-password` | `/api/accounts/change-password` |
### feishu (原 projects/feishu-config + webhooks)
| 方法 | 当前路径 | 新路径 |
|------|----------|--------|
| GET | `/api/projects/{id}/feishu-config` | `/api/feishu/projects/{id}/config` |
| PUT | `/api/projects/{id}/feishu-config` | `/api/feishu/projects/{id}/config` |
| DELETE | `/api/projects/{id}/feishu-config` | `/api/feishu/projects/{id}/config` |
| POST | `/api/projects/{id}/feishu-config/test` | `/api/feishu/projects/{id}/config/test` |
| POST | `/api/projects/{id}/refresh-webhook-token` | `/api/feishu/projects/{id}/refresh-token` |
| PUT | `/api/projects/{id}/webhook-token` | `/api/feishu/projects/{id}/token` |
| POST | `/api/webhook/feishu` | `/api/feishu/webhook` |
| ~~POST~~ | ~~`/api/webhook/github`~~ | **删除** (不需要) |
| GET | `/api/logs/webhooks` | `/api/feishu/logs` |
| GET | `/api/logs/webhooks/{id}` | `/api/feishu/logs/{id}` |
| GET | `/api/logs/work-items` | `/api/feishu/logs` (合并) |
## Migration Strategy
### Phase: 创建新 App 结构（不删除旧代码）
1. 创建 `accounts/`, `settings/`, `repositories/`, `feishu/`, `common/`
2. 复制 models 到新位置，使用相同的 `db_table`
3. 复制 views, serializers, urls
4. 更新 `INSTALLED_APPS`
### Phase: 更新路由和前端
1. 更新 `friday/urls.py` 使用新的 App 路由
2. 同步更新前端 API 调用路径
3. 测试所有功能
### Phase: 清理旧代码
1. 删除 `core/` 中迁移到其他 App 的代码
2. 删除 `projects/` 中迁移到其他 App 的代码
3. 删除 `webhooks/` App（已合并到 `feishu/`）
4. 删除 `services/` 目录（已合并到各 App）
## Risks / Trade-offs
| 风险 | 缓解措施 |
|------|----------|
| API 路径变更导致前端不兼容 | 前后端同步更新，不提供向后兼容 |
| 迁移过程中外键引用出错 | 使用字符串引用 `"app.Model"`，渐进式更新 |
| 数据库迁移冲突 | 保持 db_table 不变，创建空迁移文件 |
## Open Questions
- 是否需要为 GitHub Webhook 单独创建 `github` App？（当前量少，暂放 repositories）
- 是否需要 API 版本控制？（如 `/api/v1/...`）
