---
phase: 5
plan: "05-01"
wave: 1
status: complete
completed: 2026-06-08
requirements: [COMPAT-01, COMPAT-02, COMPAT-03]
---

# Plan 05-01 Summary — 入口迁移与向后兼容

## 交付
- `server/entrypoint.sh`（改）：删除启动期 `python manage.py init_superuser` 调用，原位补中文注释
  （说明不再自动建号 + 运维如何用 `init_superuser`/`reset_superuser_password` 手动兜底）。migrate /
  `bootstrap_system_settings` / `collectstatic` / `gunicorn` 步骤与 `set -e` 不变。
- `deploy/helm/friday/templates/migration-job.yaml`（改）：pre-install Job 删除 `init_superuser` 调用 + 补注释；
  移除该 Job 上随之失效的 `FRIDAY_ADMIN_USERNAME`/`FRIDAY_ADMIN_PASSWORD` env。`configmap.yaml`/`secret.yaml` 不动
  （server 运行时仍带这些 env，支撑 `kubectl exec ... init_superuser` 兜底）。
- `scripts/verify-runner-e2e.sh`（改）：去自动建号后 `User.objects.first()` 会取空 → 在健康检查后显式
  `docker exec friday-server python manage.py init_superuser`（既修复 e2e 断链，又演示兜底命令可用）。
- `scripts/setup.sh`（改）：管理员密码提示语 + `# 管理员配置` 注释同步为"首启走向导、env 仅供 init_superuser 兜底"；env 照写。
- `.env.example`（改）：`FRIDAY_ADMIN_*` 注释更新为命令兜底用途，明确启动期不再自动建号。
- `docs/guide/quick-start.md`、`docs/guide/admin.md`（改）：把"首次启动自动创建管理员"文案改为"首启走 Web 向导 +
  `init_superuser` 命令兜底"。

## 决策与向后兼容
- entrypoint 采取"完全移除调用"而非新增 env 开关：满足「默认不再调用」且不引入绕过向导的隐式路径（REQUIREMENTS Out of Scope）。
- COMPAT-02：`init_superuser.py` / `reset_superuser_password.py` 零改动，env 驱动用法不变（fail-closed：存在 superuser 即跳过）。
- COMPAT-03：未新增门禁/未改 `SetupStatusView`；已有 superuser 部署 `is_initialized=true` → 向导关闭、不回退；仅全新部署进向导。
- `docker-compose.yaml` 的 `FRIDAY_ADMIN_*` env 保留（启动期 inert，支撑 `docker exec ... init_superuser` 兜底，零回退）。

## 验证
- `bash -n server/entrypoint.sh` / `scripts/*.sh` 语法 OK；`grep -E "^[[:space:]]*python manage.py init_superuser"` 在 entrypoint/migration-job 无可执行调用（仅注释）。
- `uv run python manage.py help` 列出 `init_superuser` 与 `reset_superuser_password`。
- `uv run pytest tests/test_setup_gate.py -q` → 14 passed（Phase 1 门禁未回退）。
- docs/.env.example grep 无遗留"自动创建管理员"误导文案（local dev 段 `createsuperuser` 为有意保留的本地开发手动步骤）。

## Self-Check: PASSED
