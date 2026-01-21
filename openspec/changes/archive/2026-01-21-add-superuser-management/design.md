# Design: 超级管理员用户管理
## Context
Friday 作为私有化部署的系统，需要在首次启动时提供可用的管理员账号。同时需要提供便捷的密码重置机制和安全的强制修改密码流程。
**约束条件：**
- 单租户系统，仅需一个超级管理员
- 需要支持 Docker 容器环境
- 密码重置后应强制用户修改密码
## Goals / Non-Goals
**Goals:**
- 首次启动自动创建管理员账号
- 提供命令行密码重置工具
- 强制首次登录/密码重置后修改密码
- 提供 Web 界面修改账号信息
- 架构设计预留多用户、分权限、分组扩展能力
**Non-Goals (当前阶段):**
- 多用户管理界面（当前仅支持单管理员操作）
- 邮件重置密码
- 第三方认证集成
- 用户组/角色管理界面
**Future-Ready (架构预留):**
- 多用户账号管理
- 基于 Django Group 的角色管理
- 细粒度权限控制
## Decisions
### 1. 默认管理员创建机制
**Decision:** 在 `migrate` 后通过管理命令 `init_superuser` 检查并创建。
**配置方式：**
```bash
# 环境变量（可选）
FRIDAY_ADMIN_USERNAME=admin # 默认: admin
FRIDAY_ADMIN_PASSWORD= # 如未设置则自动生成
```
**逻辑：**
1. 检查是否存在超级管理员用户
2. 如不存在，使用配置或默认值创建
3. 如密码自动生成，打印到日志并设置 `must_change_password=True`
**Alternatives considered:**
- Data migration: 不够灵活，难以支持环境变量配置
- AppConfig.ready: 可能在非 web 场景重复执行
### 2. 密码重置命令
**Decision:** 创建 `reset_superuser_password` 管理命令。
```bash
# 使用方式
python manage.py reset_superuser_password [--username admin] [--password new_pass]
# 如未指定密码则自动生成并打印
```
**行为：**
- 重置指定用户（默认 admin）的密码
- 自动设置 `must_change_password=True`
- 打印新密码到控制台
### 3. 强制修改密码机制
**Decision:** 使用 `must_change_password` 字段 + 前端路由守卫。
**登录响应：**
```json
{
 "access_token": "...",
 "user": {...},
 "must_change_password": true // 新增字段
}
```
**流程：**
1. 登录成功后检查 `must_change_password`
2. 如为 true，前端跳转到强制修改密码页面
3. 路由守卫阻止访问其他页面
4. 修改密码成功后清除标记，正常进入系统
### 4. 管理员设置 API
**Decision:** 新增独立的管理员设置端点。
```
GET/PUT /api/admin/profile - 获取/更新管理员信息
POST /api/admin/password - 修改管理员密码
```
**权限：** 仅限超级管理员访问
## Risks / Trade-offs
| Risk | Mitigation |
|------|------------|
| 自动生成密码可能被日志收集 | 建议生产环境通过环境变量配置初始密码 |
| must_change_password 可被绕过（直接调 API） | 后端关键 API 也需检查此标记 |
| 单一管理员账号风险 | 当前阶段可接受，后续可扩展多用户 |
## Migration Plan. 添加 `must_change_password` 字段（默认 False，不影响现有用户）
2. 部署后运行 `init_superuser` 创建初始管理员
3. 现有用户不受影响，仅新创建或重置密码的用户需要强制修改
**Rollback:**
- 字段添加是向后兼容的，可安全回滚
## Open Questions
- 是否需要密码复杂度要求？当前使用 Django 默认验证器
- 是否需要密码过期机制？当前暂不实现
