# Change: 按领域重构 Django Apps
## Why
当前的 Django App 划分存在以下问题：
1. **`core` 职责混杂** - 同时包含用户认证 (User) 和系统配置 (SystemSetting)，两个不相关的领域
2. **`projects` 过于臃肿** - 包含项目管理、Git 仓库、Git 凭证、飞书配置等多个职责
3. **`webhooks` 职责不清** - 只有日志模型，飞书集成逻辑散落在 services/ 和 webhooks/
4. **缺少清晰的领域边界** - 难以独立演进各个功能模块
## What Changes
### 后端重构
将现有 4 个 App 重构为 6 个领域清晰的 App：
| 当前 App | 新 App | 包含内容 |
|----------|--------|----------|
| `core` (User) | `accounts` | User, 认证视图 |
| `core` (SystemSetting) | `settings` | SystemSetting |
| `projects` (Project) | `projects` | Project（轻量化） |
| `projects` (Repository, GitCredential) | `repositories` | Repository, GitCredential |
| `webhooks` + `services/feishu` | `feishu` | FeishuConfig, TriggerLog, Webhook 处理, API 客户端 |
| `tasks` | `tasks` | Task（保持不变） |
### API 路径调整
| 当前路径 | 新路径 | 说明 |
|----------|--------|------|
| `/api/auth/*` | `/api/accounts/*` | 认证相关 |
| `/api/projects/{id}/feishu-config` | `/api/feishu/projects/{id}/config` | 飞书配置 |
| `/api/webhook/feishu` | `/api/feishu/webhook` | 飞书 Webhook |
| `/api/logs/webhooks` | `/api/feishu/logs` | 飞书日志 |
| `/api/logs/work-items` | `/api/feishu/logs` | 合并到飞书日志 |
| `/api/settings/*` | `/api/settings/*` | 保持不变 |
| `/api/webhook/github` | **删除** | 不需要此功能 |
### 前端调整
- 更新 `api/*.ts` 中的 API 路径
- 重新组织 `types/index.ts` 按领域分组
- 更新 stores 中的 API 调用
## Impact
- Affected specs: 新增 `django-architecture` 规格
- Affected code:
 - **后端**: 所有 Django App 结构、models、views、urls、serializers
 - **前端**: `api/*.ts`, `types/index.ts`, `stores/*.ts`
 - **配置**: `friday/settings.py` (INSTALLED_APPS)
- **BREAKING**: API 路径变更，需要前后端同步更新
