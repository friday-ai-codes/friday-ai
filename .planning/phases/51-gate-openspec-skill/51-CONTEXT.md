# Phase 51: 编码前置 gate + openspec skill 编码策略 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区由设计文档 + 实地读码自动决策，未向用户提问)

<domain>
## Phase Boundary

SDD 仓库编码前强制关联 spec 已 `approved`（gate 拦截未批），且编码容器注入 openspec 指引使编码遵循 openspec 流程。

**In scope:**
- 消费 `RepoCodingTask.follow_openspec`（v0.8 预留字段）：建任务时按仓库 SDD 标记置位（GATE-01 前置）
- 编码派发前 gate：`follow_openspec=True` 的仓校验关联 `SddSpec.status==approved`，未批准拦截 + 如实标注阻断原因，不静默放行（GATE-01）
- 已 approved 的 SDD 仓正常放行派发；非 SDD 仓零回归（GATE-01）
- 编码容器注入 openspec 指引：dispatch 传 `follow_openspec` flag + task `system_prompt` 按仓库类型注入 openspec 段 + 复用 `setting_sources=["project"]` 原生加载仓库内 `.claude/skills`（GATE-02）

**Out of scope（本 phase）:**
- spec↔实现 PR 关联 + 交付验收视图（Phase 52）
- spec 内容深度 lint / drift 检测（v2）
</domain>

<decisions>
## Implementation Decisions（smart discuss 自动决策）

### D-51-1 建任务时按仓库 SDD 标记置 `follow_openspec`
`RepoCodingTaskService.create_tasks_for_plan`（v0.8 已建）逐仓建 `RepoCodingTask` 时，查 `Repository.facets.get("methodology")=="SDD"` → 置 `follow_openspec=True`（defaults 写入 + 已存在漂移回填，幂等）。这是 v0.8 预留字段（默认 False）的**首次消费**。非 SDD 仓保持 False。

### D-51-2 编码派发前 gate（GATE-01，fail-closed）
`AICodingNode._dispatch_wave`（v0.8 已建，dispatch 前）对每个待派发 task：
- `follow_openspec=False` → 直接放行（非 SDD 零回归）
- `follow_openspec=True` → 校验关联 spec 已批准：`SddSpec.objects.filter(plan_version_id=task.plan_version_id, repository_id=task.repository_id, status=SddSpecStatus.APPROVED).aexists()`
  - 已批准 → 放行 dispatch（正常 mark_running）
  - 未批准（无 spec / spec 非 approved）→ **gate 拦截**：不 dispatch、经 `RepoCodingTaskService` 新增 `mark_gate_blocked(task, reason)` 置 failed 终态 + `error={reason:"spec_not_approved", spec_status:<当前状态或 missing>}`，如实标注阻断原因（不静默放行）。
- gate 拦截复用 wave 失败语义：被拦截仓视同 failed → `aadvance_coding_waves` 传递闭包阻断其下游（liveness 不死锁，下游标 `upstream_failed`），整 wave 收尾后操作者可见阻断原因。

### D-51-3 gate 阻断单一写入入口（INV-6）
`RepoCodingTaskService` 新增 `mark_gate_blocked(task, reason, spec_status)`：条件 `.filter(status in {pending}).update(status=failed, error={...})`（仅 pending→failed，幂等防重复/防翻在途态），对齐既有 `mark_failed`/`mark_blocked` 范式。状态写入只经 service。

### D-51-4 openspec 指引注入（GATE-02）
- **server dispatch 侧**：`AICodingNode` 编码 dispatch metadata 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC="true"`（仅 `follow_openspec=True` 仓；对齐 v0.8 PF-06 env 注入范式，逐键加一个布尔 env，不改既有键）。
- **task 容器侧**：task config 读 `FRIDAY_TASK_FOLLOW_OPENSPEC` env（pydantic-settings，默认 False）；`_get_system_prompt()` 当 `follow_openspec` 为真时**追加 openspec 指引段**（指示 agent：本仓为 SDD/openspec 仓，编码须遵循 `openspec/` 下已批准的 spec/change proposal，优先查阅仓库内 openspec skill 与 spec 文档，按 spec delta 实现）。
- **原生 skill 加载**：`setting_sources=["project"]`（task executor 已有）自动加载仓库内 `.claude/skills`——SDD 仓自带 openspec skill 即被 claude code 原生使用，Friday 侧仅加 system_prompt 注入点（核查结论：极小改动）。

### D-51-5 零回归 + fail-soft 边界
- gate 校验异常（如 SddSpec 查询失败）→ 保守 fail-closed（视为未批准拦截，记 warning），不放行未校验的 SDD 仓编码；但**绝不**因 gate 逻辑异常崩溃整 wave 调度（异常隔离到单仓，标 failed reason=gate_error）。
- 非 SDD 仓（follow_openspec=False）完全不经 gate/注入路径 → 与 v0.8 编码完全一致（守护测试断言）。
- task 侧 `FRIDAY_TASK_FOLLOW_OPENSPEC` 缺省/为 false → system_prompt 与现状逐字一致（零回归）。

### D-51-6 INV-6 / async 约束
- gate 阻断写入只经 `RepoCodingTaskService`；async ORM 用 `*_id` 标量 / `aexists` / `afirst`，禁裸 lazy-FK。
</decisions>

<code_context>
## Existing Code Insights

- **`RepoCodingTaskService.create_tasks_for_plan`**（`server/delivery/services/repo_coding_task_service.py:37`）：逐仓 get_or_create RepoCodingTask（status=pending）+ wave 回填 + depends_on.set；本 phase 在 defaults 加 follow_openspec（按 repo facets）。已有 `mark_running/mark_done/mark_failed/mark_blocked` 条件更新范式（`.filter(status=...).update(...)` + 影响行数）。
- **`AICodingNode._dispatch_wave`**（`server/workflows/nodes/ai/coding.py:520`）：dispatch 成功仓经 `service.mark_running`；本 phase 在 dispatch 前插 gate。dispatch metadata 注入在 ~1402-1484（`DispatchTask` + env_FRIDAY_TASK_*，PF-06 逐键对齐 chat 基线）——加 `env_FRIDAY_TASK_FOLLOW_OPENSPEC`。
- **`aadvance_coding_waves`**（`server/services/plan_orchestration/wave_progression.py`）：失败/阻断传递闭包阻断下游（liveness 命门）——gate 拦截仓标 failed 后天然走此阻断。
- **`SddSpec` / `SddSpecStatus.APPROVED`**（Phase 49/50，`server/delivery/models/sdd_spec.py`）：plan_version FK + repository FK + status；gate 查询 `(plan_version_id, repository_id, status=approved)`。
- **task `_get_system_prompt`**（`task/core/executor.py:806`）：当前**硬编码**返回固定 prompt；本 phase 加 follow_openspec 条件追加 openspec 段。`setting_sources=["project"]`（executor.py:584）已原生加载仓库内 `.claude/skills`。
- **task config**：`task/` 用 pydantic-settings 读 `FRIDAY_TASK_*` env（`task/core/config.py` 或同等）——加 `follow_openspec: bool=False` 字段。
- **Repository.facets**（Phase 48）：`facets["methodology"]=="SDD"` 判 SDD 仓。
</code_context>

<specifics>
## Specific Ideas

- server：`RepoCodingTaskService.create_tasks_for_plan` 加 follow_openspec 置位 + 新增 `mark_gate_blocked`；`AICodingNode._dispatch_wave` 加 gate 校验 + dispatch metadata 加 `env_FRIDAY_TASK_FOLLOW_OPENSPEC`。
- task：config 加 `follow_openspec` 字段（读 `FRIDAY_TASK_FOLLOW_OPENSPEC`）；`_get_system_prompt` 条件追加 openspec 指引段（独立 helper 便于测试）。
- 守护测试：
  - 后端：create_tasks_for_plan 对 SDD 仓置 follow_openspec=True / 非 SDD False；gate 未批准（无 spec / draft / in_review）→ mark_gate_blocked failed reason=spec_not_approved 不 dispatch + 下游阻断；已 approved → 正常 dispatch mark_running；非 SDD 仓零回归（不经 gate）；gate 异常 fail-closed 隔离不崩 wave；env 注入仅 SDD 仓；INV-6 grep（mark_gate_blocked 经 service）。
  - task：follow_openspec=true → system_prompt 含 openspec 指引段；false/缺省 → 逐字等于现状（零回归）。
- 后端 ruff + pytest + makemigrations --check（应无新 migration——follow_openspec 字段 v0.8 已存在）；task ruff + pytest。本 phase 无前端（无 UI hint）。

> ⚠ 真实 runner + Docker 容器端到端（gate 拦截真实编码 / openspec skill 真实加载 + 真模型遵循）属真实环境验收 → human_needed deferred（对齐既有容器 E2E deferred）。
</specifics>

<deferred>
## Deferred Ideas

- spec↔实现 PR 关联 + 交付验收视图（Phase 52）；gate 放行后编码产 PR 由 Phase 52 回填关联。
- spec drift 检测（实现偏离 approved spec 告警）（v2 SDDX-02）。
- openspec spec 内容/格式深度 lint（v2 SDDX-01）。
- 真实容器 E2E（gate + openspec skill 真实加载 + 真模型遵循）→ 真实环境人工验收。
</deferred>
