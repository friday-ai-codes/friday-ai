# Implementation Tasks
## Phase: 创建新 App 结构
### 1.1 创建 accounts App
- 1.1.1 创建 `accounts/` 目录结构（apps.py, __init__.py）
- 1.1.2 迁移 User 模型到 `accounts/models.py`
- 1.1.3 迁移认证视图到 `accounts/views.py`
- 1.1.4 迁移认证序列化器到 `accounts/serializers.py`
- 1.1.5 创建 `accounts/urls.py`
- 1.1.6 创建空迁移文件（保持 db_table 兼容）
### 1.2 创建 settings App
- 1.2.1 创建 `settings/` 目录结构
- 1.2.2 迁移 SystemSetting, SettingKeys 到 `settings/models.py`
- 1.2.3 迁移设置视图到 `settings/views.py`
- 1.2.4 迁移设置序列化器到 `settings/serializers.py`
- 1.2.5 创建 `settings/urls.py`
- 1.2.6 创建空迁移文件
### 1.3 创建 repositories App
- 1.3.1 创建 `repositories/` 目录结构
- 1.3.2 迁移 Repository, GitCredential, GitPlatform, AuthType 到 `repositories/models.py`
- 1.3.3 迁移仓库视图到 `repositories/views.py`
- 1.3.4 迁移仓库序列化器到 `repositories/serializers.py`
- 1.3.5 创建 `repositories/urls.py`
- 1.3.6 创建空迁移文件
### 1.4 创建 feishu App
- 1.4.1 创建 `feishu/` 目录结构
- 1.4.2 创建 TriggerLog 模型（合并 WebhookLog + WorkItemLog）
- 1.4.3 迁移飞书 Webhook 视图到 `feishu/views.py`
- 1.4.4 迁移飞书配置视图（从 projects）到 `feishu/views.py`
- 1.4.5 创建日志查询视图
- 1.4.6 迁移 `services/feishu/` 到 `feishu/client.py`
- 1.4.7 创建 `feishu/urls.py`
- 1.4.8 创建 `feishu/serializers.py`
- 1.4.9 创建迁移文件
### 1.5 创建 common 模块
- 1.5.1 创建 `common/` 目录
- 1.5.2 迁移 `utils/encryption.py` 到 `common/encryption.py`
- 1.5.3 迁移 `utils/routers.py` 到 `common/routers.py`
- 1.5.4 创建 `common/exceptions.py`
- 1.5.5 创建 `common/pagination.py`
### 1.6 精简 projects App
- 1.6.1 从 `projects/models.py` 移除 Repository, GitCredential
- 1.6.2 从 `projects/views.py` 移除飞书配置相关视图
- 1.6.3 更新 `projects/serializers.py`
- 1.6.4 更新 `projects/urls.py`
## Phase: 更新配置和路由
### 2.1 更新 Django 配置
- 2.1.1 更新 `friday/settings.py` INSTALLED_APPS
- 2.1.2 更新 AUTH_USER_MODEL 指向 `accounts.User`
### 2.2 更新主路由
- 2.2.1 更新 `friday/urls.py` 使用新的 App 路由
- 2.2.2 验证所有 API 端点可访问
### 2.3 更新模型引用
- 2.3.1 更新 tasks/models.py 中的外键引用
- 2.3.2 更新 feishu/models.py 中的外键引用
- 2.3.3 更新所有 import 语句
## Phase: 更新前端
### 3.1 更新 API 服务
- 3.1.1 重命名 `api/auth.ts` 为 `api/accounts.ts`，更新路径
- 3.1.2 创建 `api/feishu.ts`，从 projects.ts 迁移飞书相关方法
- 3.1.3 更新 `api/projects.ts`，移除飞书相关方法
- 3.1.4 更新 `api/index.ts` 导出
### 3.2 更新类型定义
- 3.2.1 重新组织 `types/index.ts` 按领域分组注释
### 3.3 更新 Stores
- 3.3.1 更新 `stores/auth.ts` 使用新的 API 路径
- 3.3.2 更新 `stores/projects.ts` 移除飞书相关方法
### 3.4 更新页面组件
- 3.4.1 更新 `pages/login.vue` 使用新的 API
- 3.4.2 更新 `pages/projects/` 相关组件
- 3.4.3 更新 `pages/logs/` 相关组件
## Phase: 清理和测试
### 4.1 运行数据库迁移
- 4.1.1 执行 `python manage.py makemigrations`
- 4.1.2 执行 `python manage.py migrate`
- 4.1.3 验证数据库结构正确
### 4.2 运行测试
- 4.2.1 运行后端单元测试
- 4.2.2 运行前端测试
- 4.2.3 手动测试关键流程
### 4.3 清理旧代码
- 4.3.1 删除 `core/` 中已迁移的代码（保留 urls_health.py）
- 4.3.2 删除 `webhooks/` App
- 4.3.3 删除 `services/` 目录
- 4.3.4 删除 `utils/` 中已迁移的代码
### 4.4 更新文档
- 4.4.1 更新 API 文档
- 4.4.2 更新 README
