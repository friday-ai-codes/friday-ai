# Phase 5: 入口迁移与向后兼容 - Research

**Researched:** 2026-06-08
**Scope:** 基础设施迁移；研究聚焦"现状盘点 + 移除自动建号后的回退/断链风险"。

## 现状盘点（自动建号的全部触发点 + 依赖）

| 位置 | 现状 | 处置 |
|------|------|------|
| `server/entrypoint.sh:30-31` | `echo "初始化管理员..." && python manage.py init_superuser` | **移除**，补中文注释（COMPAT-01） |
| `deploy/helm/friday/templates/migration-job.yaml:46-47` | pre-install Job `sh -c` 内 `python manage.py init_superuser` | **移除**该行，保留 migrate（COMPAT-01 k8s 等价） |
| `deploy/helm/friday/templates/migration-job.yaml:61-64` | Job 上 `FRIDAY_ADMIN_USERNAME/PASSWORD` env | 命令移除后失效 → **移除** |
| `server/accounts/management/commands/init_superuser.py` | fail-closed + env 驱动 + 随机密码兜底 | **保留不动**（COMPAT-02） |
| `server/accounts/management/commands/reset_superuser_password.py` | 按用户名重置 | **保留不动**（COMPAT-02） |
| `server/accounts/views.py::SetupStatusView` | `is_initialized = exists(is_superuser=True)` | **不改**，COMPAT-03 的天然保证来源 |
| `docker-compose.yaml:39-40` | server `FRIDAY_ADMIN_*` env | **保留**（启动期 inert，支撑 `docker exec ... init_superuser` 兜底） |
| `deploy/helm/.../configmap.yaml:12` + `secret.yaml:14` | server 运行时 `FRIDAY_ADMIN_*` | **保留**（支撑 `kubectl exec ... init_superuser` 兜底） |
| `scripts/verify-runner-e2e.sh:78-83,94-104` | 设 `FRIDAY_ADMIN_*` env 启动，健康检查后 `User.objects.first()` 取用户 | **断链风险**：去自动建号后 `User.objects.first()` 返回 None → 必须在健康检查后显式 `init_superuser` |
| `scripts/setup.sh:230,343-347` | 提示"密码留空则首次启动自动生成" + 写 env | 提示语**更新**为新流程；env 照写（供命令用） |
| `docs/guide/quick-start.md:78` | "配置 FRIDAY_ADMIN_* 则首次启动自动创建，否则 createsuperuser" | 文案**更新**为向导 + `init_superuser` 兜底 |
| `docs/guide/admin.md:194-195` | env 表注"首次启动时自动创建" | 描述**更新**为"仅手动 `init_superuser` 时生效" |
| `.env.example:101-103` | 注释 `FRIDAY_ADMIN_*` | 注释**更新**为运维兜底用途 |

## 关键风险与对策

1. **e2e 脚本断链（高）**：`scripts/verify-runner-e2e.sh` 依赖启动期自动建号产生第一个 User。
   对策：在"Server 健康检查通过"后、创建 Registration Token 前，插入
   `docker exec friday-server python manage.py init_superuser`（env 已传 admin/admin123）。
   既修复断链，又顺带验证运维兜底命令在去 entrypoint 调用后仍可手动建号。
2. **向后兼容回退（中）**：已有部署升级后若误进向导即为回退。
   对策：不新增门禁、不改 `SetupStatusView`；已有部署已存在 superuser → `is_initialized=true` → 向导 403/关闭（Phase 1 行为）。`init_superuser` 本就 fail-closed（存在 superuser 即跳过），即便保留也幂等。
3. **隐式 env 绕过向导（中）**：不得引入 `FRIDAY_AUTO_CREATE_SUPERUSER` 等默认开启的自动建号开关
   （REQUIREMENTS Out of Scope）。对策：entrypoint 直接移除调用，不加开关。
4. **shell 兼容（低）**：`server/entrypoint.sh` 用 `#!/bin/bash`，`migration-job` 用 `sh -c`；
   仅做删除 + 注释，不引入新语法，保持兼容。

## 验证策略（无自动化测试，grep + 行为确认）

- `grep -n init_superuser server/entrypoint.sh` → 无匹配（仅注释中可出现命令名作说明）。
- `ls server/accounts/management/commands/{init_superuser,reset_superuser_password}.py` → 存在；`python manage.py help` 列出二者。
- `grep init_superuser deploy/helm/friday/templates/migration-job.yaml` → 无（除注释）。
- Phase 1 回归：`cd server && uv run pytest tests/test_setup_gate.py -q` 全绿（确认门禁未回退）。
- 文档/示例 grep 确认无遗留"自动创建管理员"误导文案。
