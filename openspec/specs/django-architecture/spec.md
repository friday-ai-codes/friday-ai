# django-architecture Specification
## Purpose
TBD - created by archiving change refactor-django-apps. Update Purpose after archive.
## Requirements
### Requirement: Django App 领域划分
系统 SHALL 按照业务领域划分 Django Apps，每个 App 负责单一领域，保持高内聚低耦合。
#### Scenario: App 结构
- **WHEN** 查看项目的 Django App 结构
- **THEN** 存在以下 6 个核心 App：
 - `accounts` - 用户认证和管理
 - `settings` - 系统配置管理
 - `projects` - 项目管理
 - `repositories` - Git 仓库管理
 - `feishu` - 飞书集成
 - `tasks` - AI 任务管理
- **AND** 存在 `common` 共享模块
#### Scenario: App 职责边界
- **WHEN** 需要添加用户认证相关功能
- **THEN** 修改 `accounts` App
- **AND** 不影响其他 App
- **WHEN** 需要添加飞书集成相关功能
- **THEN** 修改 `feishu` App
- **AND** 不影响 `projects` 或 `repositories` App
### Requirement: accounts App 结构
accounts App SHALL 负责用户认证和用户管理。
#### Scenario: 模型定义
- **WHEN** 查看 accounts App 模型
- **THEN** 包含 User 模型（继承 AbstractUser）
- **AND** User 模型使用 `db_table = "users"`
#### Scenario: API 端点
- **WHEN** 用户进行认证操作
- **THEN** 使用 `/api/accounts/` 前缀的 API
- **AND** 包括 login, logout, refresh, me, change-password 端点
### Requirement: settings App 结构
settings App SHALL 负责系统级配置管理。
#### Scenario: 模型定义
- **WHEN** 查看 settings App 模型
- **THEN** 包含 SystemSetting 模型
- **AND** 包含 SettingKeys 常量类
- **AND** SystemSetting 使用 `db_table = "system_settings"`
#### Scenario: API 端点
- **WHEN** 管理系统配置
- **THEN** 使用 `/api/settings/` 前缀的 API
### Requirement: repositories App 结构
repositories App SHALL 负责 Git 仓库和凭证管理。
#### Scenario: 模型定义
- **WHEN** 查看 repositories App 模型
- **THEN** 包含 Repository 模型
- **AND** 包含 GitCredential 模型
- **AND** 包含 GitPlatform, AuthType 枚举
- **AND** Repository 使用 `db_table = "repositories"`
- **AND** GitCredential 使用 `db_table = "git_credentials"`
#### Scenario: API 端点
- **WHEN** 管理 Git 仓库
- **THEN** 使用 `/api/repositories/` 前缀的 API
- **AND** GitHub Webhook 使用 `/api/repositories/webhook/github`
### Requirement: feishu App 结构
feishu App SHALL 负责所有飞书集成功能，包括配置管理、Webhook 处理、日志记录。
#### Scenario: 模型定义
- **WHEN** 查看 feishu App 模型
- **THEN** 包含 TriggerLog 模型（合并原 WebhookLog 和 WorkItemLog）
#### Scenario: 飞书配置 API
- **WHEN** 管理项目的飞书配置
- **THEN** 使用 `/api/feishu/projects/{id}/config` 端点
- **AND** 包括 GET, PUT, DELETE 方法
- **AND** 测试配置使用 POST `/api/feishu/projects/{id}/config/test`
#### Scenario: Webhook Token API
- **WHEN** 管理项目的 Webhook Token
- **THEN** 刷新 Token 使用 POST `/api/feishu/projects/{id}/refresh-token`
- **AND** 更新 Token 使用 PUT `/api/feishu/projects/{id}/token`
#### Scenario: Webhook 接收
- **WHEN** 飞书项目发送 Webhook 请求
- **THEN** 使用 POST `/api/feishu/webhook` 端点接收
#### Scenario: 日志查询
- **WHEN** 查询飞书相关日志
- **THEN** 使用 `/api/feishu/logs` 端点
- **AND** 支持分页和过滤
#### Scenario: 飞书 API 客户端
- **WHEN** 系统需要调用飞书 API
- **THEN** 使用 `feishu.client` 模块中的客户端类
- **AND** 客户端根据项目配置动态创建
### Requirement: projects App 精简
projects App SHALL 仅负责项目的核心管理，不包含飞书配置和仓库管理。
#### Scenario: 模型定义
- **WHEN** 查看 projects App 模型
- **THEN** 包含 Project 模型
- **AND** 包含 ProjectRepository 关联模型
- **AND** 不包含 Repository 或 GitCredential 模型
- **AND** Project 保留 feishu_* 字段（配置数据存储）
#### Scenario: API 端点
- **WHEN** 管理项目
- **THEN** 使用 `/api/projects/` 前缀的 API
- **AND** 不包含飞书配置相关端点
### Requirement: common 模块
common 模块 SHALL 提供跨 App 共享的工具函数和类。
#### Scenario: 模块内容
- **WHEN** 查看 common 模块
- **THEN** 包含 `encryption.py` 加密工具
- **AND** 包含 `routers.py` 自定义路由器
- **AND** 包含 `exceptions.py` 通用异常
- **AND** 包含 `pagination.py` 分页工具
#### Scenario: 无数据库模型
- **WHEN** 查看 common 模块
- **THEN** 不包含 Django 模型
- **AND** 不在 INSTALLED_APPS 中注册
### Requirement: 数据库兼容性
系统 SHALL 保持数据库表结构不变，确保无需数据迁移。
#### Scenario: 表名保持不变
- **WHEN** 执行数据库迁移
- **THEN** 所有表名保持不变
- **AND** 使用 `Meta.db_table` 显式指定表名
#### Scenario: 外键关系保持
- **WHEN** 查看模型外键
- **THEN** 使用字符串引用（如 `"projects.Project"`）
- **AND** 外键关系正确指向新位置的模型
