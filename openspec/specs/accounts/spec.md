# accounts Specification
## Purpose
TBD - created by archiving change add-superuser-management. Update Purpose after archive.
## Requirements
### Requirement: 初始管理员自动创建
系统 SHALL 在首次启动时自动创建默认超级管理员用户（如尚不存在）。
管理员用户名可通过环境变量 `FRIDAY_ADMIN_USERNAME` 配置，默认为 `admin`。
初始密码可通过环境变量 `FRIDAY_ADMIN_PASSWORD` 配置，如未配置则自动生成随机密码并打印到控制台日志。
自动生成密码时，系统 SHALL 设置 `must_change_password` 标记为 `true`。
#### Scenario: 首次启动无管理员用户
- **WHEN** 系统启动且数据库中不存在超级管理员用户
- **AND** 环境变量 `FRIDAY_ADMIN_PASSWORD` 已配置
- **THEN** 系统创建用户名为配置值（或默认 `admin`）的超级管理员
- **AND** 使用配置的密码
- **AND** 设置 `must_change_password=false`
#### Scenario: 首次启动自动生成密码
- **WHEN** 系统启动且数据库中不存在超级管理员用户
- **AND** 环境变量 `FRIDAY_ADMIN_PASSWORD` 未配置
- **THEN** 系统创建超级管理员并生成随机密码
- **AND** 将密码打印到控制台日志
- **AND** 设置 `must_change_password=true`
#### Scenario: 已存在管理员用户
- **WHEN** 系统启动且已存在超级管理员用户
- **THEN** 系统不创建新用户
- **AND** 不修改现有用户
---
### Requirement: 管理员密码重置命令
系统 SHALL 提供 `reset_superuser_password` 管理命令，允许管理员通过命令行重置超级管理员密码。
命令支持可选参数 `--username` 指定用户（默认 `admin`）和 `--password` 指定新密码。
如未指定密码，系统 SHALL 自动生成随机密码并打印到控制台。
密码重置后，系统 SHALL 设置目标用户的 `must_change_password` 标记为 `true`。
#### Scenario: 指定新密码重置
- **WHEN** 管理员执行 `python manage.py reset_superuser_password --password newpass123`
- **THEN** 系统重置 admin 用户密码为 `newpass123`
- **AND** 设置 `must_change_password=true`
- **AND** 打印成功消息
#### Scenario: 自动生成密码重置
- **WHEN** 管理员执行 `python manage.py reset_superuser_password`
- **THEN** 系统生成随机密码并重置 admin 用户密码
- **AND** 将新密码打印到控制台
- **AND** 设置 `must_change_password=true`
#### Scenario: 指定用户名重置
- **WHEN** 管理员执行 `python manage.py reset_superuser_password --username superadmin`
- **THEN** 系统重置用户名为 `superadmin` 的用户密码
- **AND** 如用户不存在则报错退出
---
### Requirement: 强制修改密码机制
系统 SHALL 在用户登录时检查 `must_change_password` 标记，如为 `true` 则要求用户在进行其他操作前先修改密码。
登录响应 SHALL 包含 `must_change_password` 字段指示是否需要强制修改密码。
用户成功修改密码后，系统 SHALL 自动清除 `must_change_password` 标记。
#### Scenario: 登录时需要强制修改密码
- **WHEN** 用户登录成功
- **AND** 用户的 `must_change_password` 为 `true`
- **THEN** 登录响应包含 `must_change_password: true`
- **AND** 前端跳转到强制修改密码页面
#### Scenario: 正常登录无需修改密码
- **WHEN** 用户登录成功
- **AND** 用户的 `must_change_password` 为 `false`
- **THEN** 登录响应包含 `must_change_password: false`
- **AND** 前端正常进入系统
#### Scenario: 强制修改密码成功
- **WHEN** 处于强制修改密码状态的用户提交新密码
- **AND** 新密码符合密码策略
- **THEN** 系统更新用户密码
- **AND** 设置 `must_change_password=false`
- **AND** 用户可正常访问系统
#### Scenario: 强制修改密码状态下访问限制
- **WHEN** 用户的 `must_change_password` 为 `true`
- **AND** 用户尝试访问非修改密码的页面
- **THEN** 前端重定向到强制修改密码页面
---
### Requirement: 管理员账号设置界面
系统 SHALL 提供管理员账号设置页面，允许管理员修改自己的用户名、显示名和密码。
设置入口 SHALL 位于系统设置菜单中。
仅超级管理员用户可访问此功能。
#### Scenario: 修改管理员用户名
- **WHEN** 管理员在账号设置页面修改用户名
- **AND** 新用户名不与现有用户冲突
- **THEN** 系统更新管理员用户名
- **AND** 显示成功提示
#### Scenario: 修改管理员显示名
- **WHEN** 管理员在账号设置页面修改显示名
- **THEN** 系统更新管理员显示名
- **AND** 显示成功提示
#### Scenario: 管理员修改密码
- **WHEN** 管理员在账号设置页面修改密码
- **AND** 提供正确的旧密码
- **AND** 新密码符合密码策略
- **THEN** 系统更新管理员密码
- **AND** 显示成功提示
#### Scenario: 非管理员访问账号设置
- **WHEN** 非超级管理员用户尝试访问账号设置 API
- **THEN** 系统返回 403 Forbidden 错误
---
### Requirement: 管理员账号 API
系统 SHALL 提供管理员账号管理的 REST API 端点。
- `GET /api/admin/profile` - 获取当前管理员信息
- `PUT /api/admin/profile` - 更新管理员用户名和显示名
- `POST /api/admin/password` - 修改管理员密码
所有端点 SHALL 要求超级管理员权限。
#### Scenario: 获取管理员信息
- **WHEN** 管理员调用 `GET /api/admin/profile`
- **THEN** 返回管理员的 `username`、`display_name`、`created_at` 等信息
#### Scenario: 更新管理员信息
- **WHEN** 管理员调用 `PUT /api/admin/profile` 并提供新的 `username` 和 `display_name`
- **AND** 新用户名不冲突
- **THEN** 系统更新管理员信息
- **AND** 返回更新后的信息
#### Scenario: 修改管理员密码 API
- **WHEN** 管理员调用 `POST /api/admin/password` 并提供 `old_password` 和 `new_password`
- **AND** 旧密码正确
- **AND** 新密码符合策略
- **THEN** 系统更新密码
- **AND** 返回成功响应
