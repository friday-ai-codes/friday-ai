---
phase: 05-entrypoint-compat
reviewed: 2026-06-08T17:34:40+08:00
status: clean
findings:
  high: 0
  medium: 0
  low: 0
scope: [server/entrypoint.sh, deploy/helm/friday/templates/migration-job.yaml, scripts/verify-runner-e2e.sh, scripts/setup.sh, .env.example, docs/guide/quick-start.md, docs/guide/admin.md]
---

# Phase 05 Code Review — 入口迁移与向后兼容

**Status:** clean（无 high/medium/low 问题）

## 审查范围
纯基础设施/迁移改动：1 个 shell entrypoint、1 个 helm 模板、2 个脚本、1 个 env 示例、2 篇文档。无应用逻辑/Python 代码改动；命令文件未触碰。

## 检查项与结论

| 检查 | 结论 |
|------|------|
| 正确性：是否真正移除自动建号 | ✓ entrypoint 与 helm migration-job 均无可执行 `init_superuser` 调用（仅注释）；migrate/bootstrap/collectstatic/gunicorn 顺序与 `set -e` 不变 |
| 向后兼容：是否回退前序向导/门禁 | ✓ 未改 `SetupStatusView`/门禁；`test_setup_gate.py` 14 passed；已有 superuser → 向导关闭 |
| 运维兜底：命令是否仍可用 | ✓ 命令文件零改动；`manage.py help` 列出二者；entrypoint/helm/docs 均给出兜底命令示例 |
| 断链风险：e2e 是否仍可跑通 | ✓ 健康检查后显式 `init_superuser`，修复 `User.objects.first()` 取空 |
| Shell 兼容/语法 | ✓ `bash -n` 通过；仅删除 + 注释，无新语法 |
| YAML 结构 | ✓ migration-job env 列表删除后缩进/结构完整，无悬挂键 |
| 孤儿配置 | ✓ helm `values.yaml` 的 admin* 仍经 configmap/secret 供 server 运行时（兜底），非孤儿；compose `FRIDAY_ADMIN_*` 有意保留 |
| 安全：是否引入绕过向导的隐式建号 | ✓ 未新增任何自动建号 env 开关（符合 REQUIREMENTS Out of Scope） |
| 文档准确性 | ✓ 无遗留"首次启动自动创建管理员"误导文案；local dev 段 `createsuperuser` 为有意保留 |

## 结论
无需修复。改动小而内聚，注释清晰（中文），向后兼容由 Phase 1 门禁天然保证并经回归确认。
