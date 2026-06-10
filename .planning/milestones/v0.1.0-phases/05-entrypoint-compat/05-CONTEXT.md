# Phase 5: 入口迁移与向后兼容 - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

> Phase 5: Infrastructure phase — skipping discuss, writing minimal context.
> 本 phase 为纯基础设施/迁移（关键字「迁移」；成功标准均为技术性：entrypoint 不再调用命令、
> 命令保留可用、已有部署不回退、仅全新部署进向导），无新增用户可见行为，故跳过灰区问答，
> 所有实现选择归 Claude's Discretion。

<domain>
## Phase Boundary

把"启动期自动建管理员"从容器/集群入口脚本中迁移出来，改由 Phase 1–4 已交付的首启向导承担，
同时保证向后兼容、运维兜底命令保留。具体交付（全部为减法 + 文档/脚本同步，**不回退任何前序向导逻辑**）：

1. **entrypoint 去自动建号（COMPAT-01）**：`server/entrypoint.sh` 默认不再调用 `init_superuser`；
   k8s 等价入口 `deploy/helm/friday/templates/migration-job.yaml` 同步去除该调用。
2. **运维兜底命令保留（COMPAT-02）**：`init_superuser` / `reset_superuser_password` 两个管理命令
   原样保留、env 驱动用法（`FRIDAY_ADMIN_USERNAME` / `FRIDAY_ADMIN_PASSWORD`）不变，仍可手动建/重置。
3. **向后兼容（COMPAT-03）**：已有 superuser 的部署升级后不进向导、不回退；仅全新部署（无 superuser）进向导。
   该保证由 **Phase 1 门禁天然提供**（`SetupStatusView`：`is_initialized = User.objects.filter(is_superuser=True).exists()`），
   本 phase 不新增门禁逻辑，仅确认并验证。

边界**之外**（沿用 REQUIREMENTS Out of Scope）：不引入会绕过向导的隐式 env 自动建号路径
（不新增 `FRIDAY_AUTO_CREATE_SUPERUSER` 之类开关）；不改命令本身的实现；不重写门禁；不动认证/会话逻辑。

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion（纯基础设施，以下为已采用的迁移默认决策）

- **entrypoint 采取"完全移除调用"而非"env 开关默认关闭"**：`server/entrypoint.sh` 直接删除
  `init_superuser` 调用并补中文注释（说明为何不再自动建号、运维如何手动建号）。理由：REQUIREMENTS
  Out of Scope 明确拒绝"`FRIDAY_ADMIN_*` 自动建号并跳过向导"的隐式 env 路径；完全移除使「默认不再调用」
  天然成立，且不引入新的绕过向导开关。
- **k8s migration-job 同步移除 `init_superuser`**：保持与容器 entrypoint 行为一致；该 Job 上随之失效的
  `FRIDAY_ADMIN_*` env 一并移除。但 `configmap.yaml`（`FRIDAY_ADMIN_USERNAME`）/ `secret.yaml`
  （`FRIDAY_ADMIN_PASSWORD`）保留，使 server 运行时仍带这些 env，运维可 `kubectl exec ... init_superuser` 兜底。
- **`docker-compose.yaml` 的 `FRIDAY_ADMIN_*` env 保留**：entrypoint 去调用后它们在启动期不再触发建号
  （inert），但保留以支撑 `docker exec friday-server python manage.py init_superuser` 运维兜底；保留＝最保守、零回退。
- **命令文件零改动**：`init_superuser.py` / `reset_superuser_password.py` 不动（已 fail-closed：存在 superuser 即跳过）。
- **脚本同步**：`scripts/verify-runner-e2e.sh` 原依赖启动期自动建号（健康检查后 `User.objects.first()`），
  必须在健康检查后显式执行一次 `docker exec friday-server python manage.py init_superuser`，否则 e2e 断链；
  这同时正好演示运维兜底命令可用。`scripts/setup.sh` 的"管理员密码（留空则首次启动自动生成）"提示语更新为
  与新流程一致（向导创建 / 命令兜底），仍照常写入 env（供命令使用）。
- **文档同步**：`docs/guide/quick-start.md`、`docs/guide/admin.md`、`.env.example` 中"首次启动自动创建管理员"
  的描述改为"首启走 Web 向导创建；`init_superuser` 仅作命令行兜底（支持 `FRIDAY_ADMIN_*`）"。
- **不新增自动化测试**：纯 shell/yaml/docs 改动；验证以 grep 断言 + 命令保留性 + Phase 1 门禁回归为准。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/accounts/management/commands/init_superuser.py`：fail-closed（`User.objects.filter(is_superuser=True).exists()` 即跳过），
  env 驱动 `FRIDAY_ADMIN_USERNAME`/`FRIDAY_ADMIN_PASSWORD`，未配密码则随机生成 + `must_change_password`。保留不动。
- `server/accounts/management/commands/reset_superuser_password.py`：按用户名重置 superuser 密码。保留不动。
- `server/accounts/views.py::SetupStatusView`：`is_initialized = exists(is_superuser=True)` —— 向后兼容的天然门禁来源。

### Established Patterns
- entrypoint 风格：`#!/bin/bash` + `set -e`，分步 echo 中文提示（迁移 → bootstrap → collectstatic → gunicorn）。
- helm migration-job：pre-install hook，`sh -c` 串行 `migrate` + `init_superuser`，env 直配（不走 envFrom）。

### Integration Points（本 phase 触及文件）
- 核心：`server/entrypoint.sh`、`deploy/helm/friday/templates/migration-job.yaml`
- 脚本：`scripts/verify-runner-e2e.sh`、`scripts/setup.sh`
- 文档/示例：`docs/guide/quick-start.md`、`docs/guide/admin.md`、`.env.example`
- 保留确认（不改）：`server/accounts/management/commands/{init_superuser,reset_superuser_password}.py`、
  `docker-compose.yaml`、`deploy/helm/friday/templates/{configmap,secret}.yaml`

</code_context>

<specifics>
## Specific Ideas

- entrypoint 改动必须留清晰中文注释：为何不再自动建号（改由首启向导承担）+ 运维如何手动建号
  （`python manage.py init_superuser`，可配 `FRIDAY_ADMIN_*`）。
- shell 保持 POSIX/bash 兼容，不破坏现有 `set -e` 与步骤顺序（仅删除建号步骤）。
- COMPAT-03 不写新代码，靠 Phase 1 门禁；验证须显式确认"已有 superuser → is_initialized=true → 向导关闭"。

</specifics>

<deferred>
## Deferred Ideas

- 向导内联动基础设施密钥脚本 / 部署健康总览等——已在 REQUIREMENTS v2 (SETUPX) 跟踪，不在本期。

</deferred>
