# Change: 添加超级管理员用户管理功能
## Why
当前系统首次启动时没有默认管理员用户，无法登录系统进行配置。需要提供自动创建初始管理员、命令行重置密码、以及强制首次登录修改密码的完整管理员账号管理机制。
## What Changes
- 在服务启动/迁移后自动检查并创建默认管理员用户（如未配置）
- 新增 `reset_superuser_password` Django 管理命令，支持重置管理员密码并打印新密码
- User 模型添加 `must_change_password` 字段，标记是否需要强制修改密码
- 登录流程检测 `must_change_password` 状态，返回特殊响应要求前端跳转修改密码
- 新增管理员账号设置页面（前端），支持修改用户名和密码
- 新增管理员账号管理 API 端点
## Impact
- Affected specs: `accounts` (新增)
- Affected code:
 - `server/accounts/models.py` - 添加 `must_change_password` 字段
 - `server/accounts/management/commands/` - 新增管理命令
 - `server/accounts/views.py` - 修改登录逻辑，新增管理员设置 API
 - `server/accounts/serializers.py` - 新增序列化器
 - `server/friday/settings.py` - 添加默认管理员配置项
 - `web/src/views/` - 新增管理员设置页面
 - `web/src/api/` - 新增 API 调用
