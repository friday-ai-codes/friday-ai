---
status: complete
phase: 01-setup-gate
source: [01-VERIFICATION.md]
started: 2026-06-08T15:52:00+08:00
updated: 2026-06-08T23:27:00+08:00
---

## Current Test

[testing complete]

## Tests

### 1. 全新部署 E2E 浏览器重定向测试

expected: 启动无 superuser 的后端实例，浏览器访问任意非 `/setup` 页面 → 自动跳转到 `/setup` 并显示「首次设置」向导界面；完成设置（创建管理员）后跳转到 `/login`；此后再次访问 `/setup` 被重定向到 `/login`（向导不再出现）。
why_human: 路由守卫逻辑已通过单元断言验证，但完整 E2E 流程（前端 fetch 后端 + 路由跳转渲染）需真实浏览器环境；01-VALIDATION.md 已登记此 Manual-Only 条目。
result: pass
evidence: 真实浏览器流程跑通 — 通过 `/setup` 向导创建了 superuser（data/friday.db `users` 表存在 `admin`, is_superuser=1），后续 `GET /api/auth/me/` 持续返回 200（已登录）；修复前因 `DATABASE_URL` 指向未迁移的空库报 `no such table: users`，已对 friday.db 执行 `manage.py migrate` 解决。

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
