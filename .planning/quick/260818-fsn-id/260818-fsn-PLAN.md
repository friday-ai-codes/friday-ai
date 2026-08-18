---
quick_id: 260818-fsn
phase: 260818-fsn-id
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - server/services/process_runtime/blueprint_confirm_gate.py
  - server/services/process_runtime/blueprint_resume.py
  - server/delivery/management/commands/repair_blueprint_confirm_gate.py
  - server/tests/services/process_runtime/test_blueprint_confirm_gate.py
  - server/tests/services/process_runtime/test_blueprint_process_graph.py
  - server/delivery/api/blueprint_doc_views.py
  - server/delivery/urls.py
  - server/delivery/api/artifact_serializers.py
  - server/tests/delivery/test_blueprint_doc_views.py
  - web/src/utils/blueprintActivity.ts
  - web/src/utils/__tests__/blueprintActivity.spec.ts
  - web/src/locales/zh-CN.json
  - web/src/components/blueprint/BlueprintStageStepper.vue
  - web/src/components/blueprint/__tests__/stageStepper.spec.ts
  - web/src/api/blueprints.ts
  - web/src/types/blueprint.ts
  - web/src/composables/useBlueprintLive.ts
  - web/src/composables/__tests__/useBlueprintLive.spec.ts
  - web/src/components/blueprint/BlueprintResearchDrawer.vue
autonomous: true
requirements:
  - GATE-REFRESH-01
  - GATE-REPAIR-01
  - RESEARCH-UI-01
  - RESEARCH-GROUP-01
  - RESEARCH-LIVE-01
  - RESEARCH-OBS-01
user_setup: []
must_haves:
  truths:
    - "已打开的 repo_confirmation 门在调研重试完成后刷新快照（fitness/task_status/现状），不再长期残留 failed 旧态"
    - "并发终态回调下 refresh 幂等且不丢人工门动作（role/responsibility/removed/pending_research/actions）"
    - "过程明细 started 标题为「调研 {repository_name} 仓库」，摘要展示 research_reason；routed_confidence/repository_id/task_id 不进普通字段行（仅 diagnostics raw）"
    - "repo_research 过程明细按仓库分组，在途时可看到可观测进度（工具名/路径/脱敏摘要），不暴露加密思考链"
    - "轻量 progress/tail 端点可轮询；不每 5s 拉全量 research-detail(400 logs)"
    - "部署后可用 repair 命令修复 artifact 7409c0d0-7fde-4bcf-8857-29e437610fc7"
  artifacts:
    - path: "server/services/process_runtime/blueprint_confirm_gate.py"
      provides: "open_gate 幂等 refresh/reopen 语义 + select_for_update 合并快照"
      contains: "arefresh_open_gate_snapshot|refresh"
    - path: "server/delivery/management/commands/repair_blueprint_confirm_gate.py"
      provides: "按 artifact_id 一键刷确认门快照"
    - path: "server/delivery/api/blueprint_doc_views.py"
      provides: "research-progress 轻量 cursor/tail 读面"
    - path: "web/src/utils/blueprintActivity.ts"
      provides: "repo_research 按仓分组 + 普通 UI 隐藏 id/confidence"
    - path: "web/src/composables/useBlueprintLive.ts"
      provides: "仅 researching 时轮询轻量 progress（唯一 refetchInterval 消费点）"
  key_links:
    - from: "blueprint_resume short-circuit"
      to: "BlueprintConfirmGateAdapter.arefresh_open_gate_snapshot"
      via: "blocked+no-pending 返回前仍 refresh"
      pattern: "arefresh_open_gate_snapshot"
    - from: "open_gate existing open thread"
      to: "_abuild_snapshot + merge human fields"
      via: "select_for_update options 写回"
      pattern: "select_for_update|pending_research"
    - from: "useBlueprintLive"
      to: "GET .../blueprint/research-progress/"
      via: "after_log_id cursor + per-repo recent_logs"
      pattern: "research-progress|after_log_id"
    - from: "BlueprintStageStepper repo_research"
      to: "grouped repo cards + research drawer"
      via: "buildStagePanorama / describeEventPayload"
      pattern: "repoGroup|view-research"
---

<objective>
修复 technical_blueprint 在「确认门已开后重调研」时确认快照残留 failed 的缺陷；重做 repo_research 过程明细（标题/摘要/隐藏字段/按仓分组）；并为在途调研提供轻量可观测进度（cursor/tail），同时保留既有结论/过程抽屉。

Purpose: 用户在确认门等待时看到的仓库态与最新调研结论一致；过程明细可读且不拖垮轮询。
Output: 幂等 gate refresh + repair 命令 + progress API + 前端过程明细/直播进度；**禁止 git commit / stage**（父代理或用户另行提交）。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/templates/summary.md

⚠️ **git 纪律（NON-NEGOTIABLE）**
- **禁止** `git commit` / `git add` / stage。只改本计划 `files_modified` 内文件；勿触碰无关在途改动。
- 无 schema migration（cursor 用既有 `SubAgentRuntimeLog.id`）；若必须加字段，仅 additive 且说明兼容策略。

⚠️ **根因（已读代码确认）**
- `BlueprintConfirmGateAdapter.open_gate`：已有 open+blocking `repo_confirmation` 线程时直接短路，**不重算** `_abuild_snapshot`（`test_open_gate_pending_short_circuits` 固化了旧行为）。
- `blueprint_resume._adrive_blueprint_locked`：`waiting_clarification` 且 open+blocking **且** `acollect_pending_research_repos` 为空 → 零 advance。调研终态后 pending 已空，回调续驱短路，**永远不会**再进 `open_gate`。
- 快照含 `task_status`（来自 fitness 聚合）。旧 failed 残留在 `BlueprintThread.options`，门面板/过程态读线程快照 ⇒ 用户看见已失败仓。
</execution_context>

<context>
@.planning/STATE.md
@.cursor/rules/observability-logging.mdc
@server/services/process_runtime/blueprint_confirm_gate.py
@server/services/process_runtime/blueprint_resume.py
@server/services/process_runtime/builtin_processes.py
@server/services/process_runtime/blueprint_research_adapter.py
@server/delivery/api/blueprint_doc_views.py
@server/delivery/services/blueprint_lifecycle_service.py
@server/tests/services/process_runtime/test_blueprint_confirm_gate.py
@server/tests/services/process_runtime/test_blueprint_process_graph.py
@server/tests/delivery/test_blueprint_doc_views.py
@web/src/utils/blueprintActivity.ts
@web/src/components/blueprint/BlueprintStageStepper.vue
@web/src/components/blueprint/BlueprintResearchDrawer.vue
@web/src/composables/useBlueprintLive.ts
@web/src/locales/zh-CN.json
@web/src/api/blueprints.ts

## Locked decisions (cite in actions)

- **D-01** 已开确认门必须支持幂等 **refresh**：用最新 fitness/task_status 更新 `BlueprintThread.options`，保留人工字段。
- **D-02** resume 在 blocked+no-pending 短路前也必须 refresh（否则终态回调到不了 open_gate）。
- **D-03** 并发：线程行 `select_for_update`；无实质变化不写；观测 best-effort。
- **D-04** 过程明细 started 标题：`调研 {repository_name} 仓库`；summary 展示 `research_reason`。
- **D-05** 普通 UI 隐藏 `routed_confidence` / `repository_id` / `task_id`；raw diagnostics 可保留。
- **D-06** 过程明细按仓库分组；保留 `BlueprintResearchDrawer`（结论+全过程）。
- **D-07** 直播进度用轻量 cursor/tail，禁止把全量 `research-detail`（默认 400 logs）塞进 5s 轮询。
- **D-08** 只展示可观测里程碑：tool_call/tool_result 名与路径、脱敏摘要；继续过滤加密 thinking noise；不渲染 chain-of-thought。
- **D-09** 提供 repair 路径修复 artifact `7409c0d0-7fde-4bcf-8857-29e437610fc7`（部署后可跑）。
- **D-10** `refetchInterval` 仍只允许出现在 `useBlueprintLive.ts`（既有源码守卫）。

## Claude's Discretion

- merge 键：`repository_id`。人工保留：`role_suggestion` / `responsibility` / `removed` / `remove_reason` / `pending_research` / `actions`；覆盖：`fitness` / `task_status` / `current_state_summary` / `routing_evidence` / `repository_name`（空名才补）。
- 新仓出现在 fitness 但不在快照：append（`pending_research=False`）；人工 `removed` 仓不因 refresh 复活。
- progress API 路径建议：`GET /delivery/artifacts/<uuid>/blueprint/research-progress/`；query：`after_log_id`（全局 cursor，默认 0）、`limit`（默认 20，clamp ≤50）。
- 每仓返回：`repository_id`/`repository_name`/`task_status`/`run_status`/`latest_observable`/`log_cursor`/`recent_logs[{id,type,content,ts}]`；复用 `_is_noise` + `_log_row` 脱敏。
- 前端 `repo_research` 分组：按 `repository_name`（缺则 id）折叠 started/completed/failed；组内显示 reason + 直播 recent_logs。
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: 确认门幂等 refresh + resume 接线 + 存量 repair</name>
  <files>server/services/process_runtime/blueprint_confirm_gate.py, server/services/process_runtime/blueprint_resume.py, server/delivery/management/commands/repair_blueprint_confirm_gate.py, server/tests/services/process_runtime/test_blueprint_confirm_gate.py, server/tests/services/process_runtime/test_blueprint_process_graph.py</files>
  <behavior>
    - 已有 open `repo_confirmation` 线程时，`open_gate` 调用 refresh：fitness/task_status 更新到 options；人工字段保留；仍返回 `awaiting_confirmation`（D-01）。
    - 无实质变化（归一化后 options 相等）→ 不 UPDATE；重复调用幂等（D-03）。
    - resume：`waiting_clarification` + blocking + 无 pending 短路**之前**调用 refresh；advance 仍为 0（D-02）。
    - 并发：两次 refresh 交错不丢 `actions` / `pending_research`（select_for_update）。
    - repair 命令：`--artifact-id=7409c0d0-7fde-4bcf-8857-29e437610fc7` 刷开着的门；无门/无会话 → 明确 exit 非 0 或跳过消息（D-09）。
  </behavior>
  <action>
  1. 在 `blueprint_confirm_gate.py` 新增 `arefresh_open_gate_snapshot(session) -> dict`（或 adapter 方法）：解析活跃 OPEN/ANSWERED `repo_confirmation` 线程；`_abuild_snapshot`；按 D-01/Discretion merge；`select_for_update` 写回 `options` + `updated_at`；同步可写的 `stage_state["confirmation"]` 形状（与 `acollect_confirmation_state` 一致）经返回值交给调用方可选落盘。导出到模块 `__all__`。
  2. 改 `open_gate`：原「pending 短路」分支改为 **refresh 后** `_result("awaiting_confirmation", ...)`，带刷新后的 `stage_state`。更新/替换 `test_open_gate_pending_short_circuits`：断言仍单线程，但 loader **会被调用**且 `task_status`/fitness 可更新；新增「人工 pending_research/actions 保留」「failed→done 刷新」用例。
  3. 在 `_adrive_blueprint_locked` 短路分支（约 L179–184）调用 refresh（best-effort try/except，失败打 `blueprint_confirm_gate_refresh_failed` 仍返回 session）。新增 process_graph/resume 测试：gate 开着、task 已 done、旧 options `task_status=failed` → resume 后 options 变为最新（advance 仍可 0）。
  4. 新增 management command `repair_blueprint_confirm_gate`：按 artifact 找最新 technical_blueprint 会话 + 开着的门 → `arefresh_open_gate_snapshot`；结构化日志 `blueprint_confirm_gate_repair_*`（category=caller, component=process_runtime, artifact_id, thread_id, duration_ms, initiated_by_user_id=system）。
  5. 观测：`blueprint_confirm_gate_refreshed` / `_noop` / `_failed`：kv 含 session_id/artifact_id/thread_id/repo_count/changed/duration_ms；禁止日志打印 options 全文或凭证。
  </action>
  <verify>
    <automated>cd /Users/zaneliu/Projects/open-source/friday-ai/server && uv run pytest tests/services/process_runtime/test_blueprint_confirm_gate.py tests/services/process_runtime/test_blueprint_process_graph.py -q --tb=short -k "open_gate or refresh or resume_short or pending"</automated>
  </verify>
  <done>
  重调研终态后确认门快照不再卡在 failed；repair 可对目标 artifact 执行；相关单测绿；无 git commit。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: research-progress 轻量 cursor/tail API</name>
  <files>server/delivery/api/blueprint_doc_views.py, server/delivery/urls.py, server/delivery/api/artifact_serializers.py, server/tests/delivery/test_blueprint_doc_views.py</files>
  <behavior>
    - `GET .../blueprint/research-progress/`：200；无会话 → 空结构（与 research-detail 同语义）（D-07）。
    - `after_log_id` + `limit`：只返回 id &gt; cursor 的可观测日志尾部；加密 thinking noise 过滤；正文 `redact_secrets_in_text`（D-08）。
    - 载荷远小于 research-detail：默认每仓 ≤20 条、无全量 400 回溯；含 task/run 状态标量便于 UI（D-07）。
    - 权限/作用域与既有 blueprint 读端点一致；观测 `blueprint_research_progress_read`（duration_ms, repo_count, log_count, category=caller）。
  </behavior>
  <action>
  1. 在 `blueprint_doc_views.py` 实现 progress 装配：按会话 `RepoResearchTask` 分组；对每个 task 用既有 session_id 前缀规则找最新 `bp-research-*` run（本任务聚焦阶段一调研直播；repo_plan 可附 status 但不强制灌日志）；查询 `SubAgentRuntimeLog` where `id__gt=after_log_id` order_by id，滤 `_is_noise`，截断 `limit`。
  2. 注册 url + serializer/OpenAPI 字段；**兼容**：保留既有 `research-detail/` 不变（抽屉全量仍用它）。
  3. 测试：空会话；有日志 cursor 递增；secrets 脱敏；noise 过滤；limit clamp；鉴权回归（复用 doc_views 既有 auth 表驱动风格）。
  </action>
  <verify>
    <automated>cd /Users/zaneliu/Projects/open-source/friday-ai/server && uv run pytest tests/delivery/test_blueprint_doc_views.py -q --tb=short -k "research_progress or research_detail"</automated>
  </verify>
  <done>
  轻量 progress 端点可测且绿；research-detail 零回归；无 git commit。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: 过程明细文案/隐藏字段/按仓分组 + 直播进度接线</name>
  <files>web/src/utils/blueprintActivity.ts, web/src/utils/__tests__/blueprintActivity.spec.ts, web/src/locales/zh-CN.json, web/src/components/blueprint/BlueprintStageStepper.vue, web/src/components/blueprint/__tests__/stageStepper.spec.ts, web/src/api/blueprints.ts, web/src/types/blueprint.ts, web/src/composables/useBlueprintLive.ts, web/src/composables/__tests__/useBlueprintLive.spec.ts, web/src/components/blueprint/BlueprintResearchDrawer.vue</files>
  <behavior>
    - started 展示「调研 {repository_name} 仓库」；summary/字段优先 `research_reason`（D-04）。
    - `describeEventPayload`（或专用过滤）对普通 fields 省略 `routed_confidence`/`repository_id`/`task_id`；raw JSON 仍可折叠查看（D-05）。
    - `repo_research` 详情非串行事件列表，而是按仓库卡片分组（状态+reason+可选直播行）；抽屉入口保留（D-06）。
    - `useBlueprintLive` 在 researching/live 时轮询 `research-progress`（非 research-detail）；drawer 仍按需拉全量 detail，可选对打开的仓用 cursor 增量刷新但不得 5s 全量 400（D-07/D-10）。
  </behavior>
  <action>
  1. 更新 `zh-CN.json`：`repoResearchStarted` → `调研 {repository_name} 仓库`（缺名仍走 Generic）。
  2. `blueprintActivity.ts`：定义 `NORMAL_UI_HIDDEN_PAYLOAD_KEYS`；fields 构建时跳过；新增 `groupRepoResearchEvents(events)`（或 panorama 节点上 `repoGroups`）供 stepper 渲染。
  3. `BlueprintStageStepper.vue`：当 `activeNode.stage === 'repo_research'` 渲染分组 UI；组头可点 `view-research` 并带 `initialRepositoryId`；合并 live progress（来自 `useBlueprintLive` 新返回值）到对应仓卡片。
  4. `useBlueprintLive.ts`：新增 progress query；`refetchInterval` 仅此文件；`isLive` 且蓝图 researching 时启用。
  5. API/types：`getBlueprintResearchProgress`；扩展 drawer 仅在 `open` 时用 detail（保持现状），文档注释标明 progress vs detail 分工。
  6. 单测：activity 隐藏字段 + 分组；stepper 分组 DOM；live composable 不请求 research-detail。
  </action>
  <verify>
    <automated>cd /Users/zaneliu/Projects/open-source/friday-ai/web && pnpm exec vitest run src/utils/__tests__/blueprintActivity.spec.ts src/components/blueprint/__tests__/stageStepper.spec.ts src/composables/__tests__/useBlueprintLive.spec.ts --reporter=dot</automated>
  </verify>
  <done>
  过程明细按仓可读、标题/摘要正确、隐藏字段生效、直播走轻量端点；抽屉保留；无 git commit。
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client→research-progress/detail | 认证用户读工具结果/路径，可能含仓内敏感片段 |
| callback→gate options | 终态回调触发 refresh，写确认门快照 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-fsn-01 | Information Disclosure | research-progress logs | mitigate | 复用 `_log_row`/`redact_secrets_in_text`；过滤加密 thinking；不返回 transcript/CoT |
| T-fsn-02 | Tampering | gate options refresh | mitigate | `select_for_update`；只覆盖 fitness 面，保留人工 actions；权限仍走既有 artifact 读/修命令仅运维 |
| T-fsn-03 | Denial of Service | progress 轮询 | mitigate | limit clamp、每仓短尾、禁止把 400-log detail 接入 live 轮询 |
| T-fsn-SC | Tampering | npm/pip installs | accept | 本任务无新包依赖 |
</threat_model>

<verification>
- 后端：Task 1/2 pytest 命令全绿。
- 前端：Task 3 vitest 全绿。
- 手工/运维：部署后 `uv run python manage.py repair_blueprint_confirm_gate --artifact-id=7409c0d0-7fde-4bcf-8857-29e437610fc7`，确认门 `task_status`/fitness 与最新 PartialPlan 一致。
- 回归：`research-detail` 抽屉仍只在打开时取数；`blueprint-source-guard` 的 refetchInterval 单点约束不破。
</verification>

<success_criteria>
1. 确认门已开 + 重调研完成后，快照不再残留旧 failed（自动化测试覆盖）。
2. 过程明细标题/摘要/隐藏字段/按仓分组符合 D-04–D-06。
3. 在途进度经 research-progress cursor 更新，无 5s 全量 400-log 轮询。
4. 目标 artifact 可通过 repair 命令修复。
5. 观测事件齐全且脱敏；无 git commit。
</success_criteria>

<output>
Create `.planning/quick/260818-fsn-id/260818-fsn-SUMMARY.md` when execution finishes（由 executor 写；本规划步骤不写 SUMMARY）。
</output>
