---
phase: 94-entrypoint-unify
plan: 03
subsystem: mcp_tools
tags: [plan_orchestration, mcp_delegate, technical_plan, merged_plan, entrypoint_unify]

# Dependency graph
requires:
  - phase: 94-entrypoint-unify (94-01)
    provides: "render_merged_plan_markdown 共享渲染 helper（§7 MergedPlan → lark_md）"
  - phase: plan_orchestration（既有）
    provides: "start_orchestration / build_orchestration_engine / adrive / ArchitectMergeAdapter / canonical PlanVersion"
provides:
  - "mcp_tools/orchestration_delegate.delegate_plan_orchestration + DelegateResult（共享 MCP delegate 核心，供 Plan 04 复用）"
  - "build_orchestration_engine(skip_clarification=) no-clarify policy 注入（MCP 单次同步入口直推）"
  - "create_feishu_technical_plan delegate 路径 + canonical→旧响应字段映射 + 落库兼容"
affects: [94-04-mcp-coding-plan-delegate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP 入口 delegate 到统一编排（start_orchestration + build_orchestration_engine(skip_clarification=True) + adrive），绝不在 MCP 层重写拆分/路由/调研/融合"
    - "canonical §7 content → 旧响应字段显式映射白名单（外形兼容，不透传内部键）"
    - "engine clarify policy 注入式开关（skip_clarification）兼顾 MCP 同步友好与工作流/chat 零回归"

key-files:
  created:
    - server/mcp_tools/orchestration_delegate.py
    - server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py
  modified:
    - server/services/plan_orchestration/entrypoint.py
    - server/mcp_tools/technical_plan_service.py
    - server/mcp_tools/views.py
    - server/tests/mcp_tools/test_feishu_technical_plan.py
    - server/tests/mcp_tools/test_learning_cases.py

key-decisions:
  - "build_orchestration_engine 加 skip_clarification 开关注入模块级 _no_clarify policy（恒不澄清），MCP 单次同步入口 best-effort 带现有信息直推；默认 False 保工作流/chat 零回归（其余 adapters 逐字不变）"
  - "delegate 三态映射 mirror plan_research._map_terminal：DONE→completed（取 PlanVersion.content + render markdown）/ RESEARCHING|CLARIFYING 挂起→partial（best-effort 当前 content + session 续推）/ FAILED→failed（content={}）"
  - "canonical execution_plan → 旧 repository_tasks 矩阵显式字段映射白名单（repository_id/repository_name/branch_strategy→planned_branch/coding_instruction/description→change_goal/files→candidate_files/dependencies），缺字段填空不抛（T-94-03-INFO 不透传 content 内部键）"
  - "响应外形兼容：保留全部旧键（technical_plan_id/context_id/project_id/plan/markdown/repository_tasks/evidence/feishu_document/comment/status/retry_state/run_id）+ 新增可选 session_id（partial 续推钥匙，T-94-03-COMPAT）"
  - "actor 解析从 request.user（InteractionRun 无 created_by 字段）——非真实用户 None，召回 stage fail-closed 空召回（T-94-03-ELEV 文档化降级），透传 delegate created_by"
  - "canonical_plan_id（存 delivery.TechnicalPlan.id）不由 delegate.plan_version_id（PlanVersion.id）回填——语义不符，留空避免错误软链"

patterns-established:
  - "MCP 入口统一 delegate 核心：Plan 04（create_coding_plan）复用 delegate_plan_orchestration（include_repos 单仓约束），不造两套"

requirements-completed: [UNIFY-03]

# Metrics
duration: ~25min
completed: 2026-06-27
---

# Phase 94 Plan 03: MCP create_feishu_technical_plan delegate 到统一编排 Summary

**MCP `create_feishu_technical_plan` 改 delegate 到 `plan_orchestration` 产 canonical §7 MergedPlan/PlanVersion，经共享 `delegate_plan_orchestration` 核心（start_orchestration + skip_clarification engine + adrive）三态映射回旧 MCP 响应外形（旧键全保留 + 可选 session_id）并继续落 McpWorkItemTechnicalPlan，MCP 入口注入 no-clarify policy 直推、RESEARCHING 在途返回 PARTIAL + session_id**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-27T15:40:54Z
- **Completed:** 2026-06-27T16:05:51Z
- **Tasks:** 2
- **Files modified:** 7（2 created + 5 modified）

## Accomplishments

- **Task 1** — `build_orchestration_engine(skip_clarification=)` 加开关注入模块级 `_no_clarify` policy（恒判不澄清，MCP 单次同步入口直推，默认 False 工作流/chat 零回归）；新建 `mcp_tools/orchestration_delegate.py`：`delegate_plan_orchestration` + 冻结 `DelegateResult` 共享 delegate 核心——`start_orchestration(entrypoint=workflow)` + `build_orchestration_engine(skip_clarification=True)` + `adrive_plan_session_to_pause_or_terminal` → 三态映射（DONE→completed 取 `PlanVersion.content` + 复用 94-01 `render_merged_plan_markdown`；RESEARCHING/CLARIFYING 挂起→partial best-effort；FAILED→failed），进出口 best-effort 埋点（`mcp_plan_delegate_started/completed`，category=caller、component=mcp_tools、duration_ms、status）。
- **Task 2** — `build_work_item_technical_plan` 重构为 delegate 路径：移除 `_build_repo_task_matrix`/`_resolve_repositories`/`_candidate_files`/`render_technical_plan_markdown` 确定性 seam；canonical `execution_plan[]` → 旧 `repository_tasks` 矩阵显式字段映射白名单（不透传内部键）；`plan`=canonical content / `markdown`=delegate render；响应保留全部旧键 + 新增可选 `session_id`；status 映射（completed/partial/failed）+ writeback 失败再降级；`McpWorkItemTechnicalPlan` 继续落库（`plan_body`=canonical content）；飞书文档/评论 writeback 保留（喂 delegate markdown + 映射矩阵）。`CreateFeishuTechnicalPlanView.post` 解析 actor（request.user，非真实用户 None fail-closed）透传 delegate。
- **MCP 同步达 DONE 契约测试**（WARNING 2）：走真实 delegate 路径（真实 `start_orchestration` + `build_orchestration_engine(skip_clarification=True)` + `adrive`，仅 stub router/recall/research/merge adapter 使 research 同步解析、不触发容器 fan-out），在**空 `node_execution_id`**（MCP 入口形态）下断言 delegate 终态 `status="completed"` + 取到 canonical content + 非空 markdown + 底层 session 达 DONE。

## Task Commits

1. **Task 1: 共享 MCP delegate 核心 + engine skip_clarification 开关** — `97adec023` (feat)
2. **Task 2: create_feishu_technical_plan delegate 接线 + 响应外形/落库守护** — `06ed87966` (feat)

## Files Created/Modified

- `server/mcp_tools/orchestration_delegate.py` (新建) — `delegate_plan_orchestration` + `DelegateResult` 共享 delegate 核心（三态映射 + best-effort 埋点）
- `server/services/plan_orchestration/entrypoint.py` — `build_orchestration_engine(skip_clarification=)` + 模块级 `_no_clarify` policy
- `server/mcp_tools/technical_plan_service.py` — delegate 路径重构 + `_map_execution_plan_to_repository_tasks`/`_map_status`/`_resolve_delivery_work_item`；移除确定性 seam helpers；`actor` 参数
- `server/mcp_tools/views.py` — `CreateFeishuTechnicalPlanView.post` 解析 actor 透传
- `server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py` (新建) — delegate 三态 + 响应 snapshot + 落库 + delegate 调用 + 缺 actor 降级 + 编排挂起 partial + MCP 同步达 DONE 契约
- `server/tests/mcp_tools/test_feishu_technical_plan.py` — 更新为 monkeypatch delegate 适配新 seam（writeback/落库覆盖保留）
- `server/tests/mcp_tools/test_learning_cases.py` — 相似学习案例断言改 evidence（不再内联 canonical plan content）

## Decisions Made

见 frontmatter key-decisions。要点：MCP 入口经 skip_clarification 注入 no-clarify policy 直推（Open Q1 决议 #1）；挂起态语义明确（RESEARCHING/CLARIFYING→PARTIAL + session_id，调用方须容忍并经会话/工作流续推）；响应外形显式字段映射白名单（外形兼容、不透传 canonical 内部键）；actor 取 request.user（InteractionRun 无 created_by），None fail-closed 召回。

## Deviations from Plan

### [Rule 1 - Tests broken by intended behavior change] 更新 delegate seam 切换波及的既有测试

- **Found during:** Task 2（回归 `-k technical_plan` 守护）
- **Issue:** 方案生成从确定性 `_build_repo_task_matrix` 改 delegate 后，3 个既有测试断言旧确定性形态（planned_branch `feat/feishu-*` 前缀、candidate_files 来自 chunk、similar_cases 内联于 `plan`、文档正文含「仓库任务矩阵」）已失效；且这些测试原走真实 service，delegate 化后会触发真实编排（router 无 provider → 优雅 FAILED）。
- **Fix:**
  - `test_feishu_technical_plan.py` 两测改 monkeypatch `delegate_plan_orchestration` 返回 canonical DONE → 断言改新映射外形（planned_branch=branch_strategy、candidate_files 来自 content.files、markdown=render 结果、新增 session_id）；writeback/落库覆盖保留。
  - `test_learning_cases.py::..._auto_includes_similar_learning_case` 改 monkeypatch delegate + 断言相似案例落 `evidence`（learning_case 源），不再内联 canonical `plan`。
  - `tests/knowledge/test_triggers.py::test_mcp_plan_created_delivers` 未改（仅断言 ingestion 三元组，与 delegate 终态无关，delegate 优雅降级后仍通过）。
- **Files modified:** server/tests/mcp_tools/test_feishu_technical_plan.py, server/tests/mcp_tools/test_learning_cases.py
- **Commit:** 06ed87966

### [Plan 文本澄清 - actor 来源] InteractionRun 无 created_by 字段

- PLAN 文本写「从 run 的 created_by_id → User」，但 `InteractionRun` 模型无 `created_by` 字段；改从 `request.user` 解析 actor（与既有 report_project_knowledge 等 MCP 写入视图同源范式），非真实用户 None fail-closed。语义等价、满足 T-94-03-ELEV。

## Issues Encountered

- 异步 ORM 重测（`build_work_item_technical_plan` 直调 / 真实 delegate 契约）在 in-memory sqlite + `sync_to_async`（ArchitectMergeAdapter `_record_merge` / `create_interaction_run`）下偶发 `database table is locked`——对两条 async ORM 重测标 `@pytest.mark.django_db(transaction=True)`、并 monkeypatch 真实后台 ingestion 解决，未影响产物。
- `mcp_tools/views.py` 在 HEAD 即非 ruff-format-clean（预存量，超本 plan 范围）——仅施加最小 actor 编辑、未全量 reformat（避免无关 churn，SCOPE BOUNDARY）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 共享 `delegate_plan_orchestration` 已就位，供 94-04（`create_coding_plan` 单仓 delegate，include_repos=[repository_id]）复用，不造两套。
- 响应外形/落库兼容守护测试（snapshot + 落库 + delegate 调用 + actor 降级 + MCP 同步达 DONE 契约）全绿；`-k technical_plan` 12 passed、广域回归 144 passed。
- 下游：94-04（MCP create_coding_plan delegate，Wave 3，UNIFY-04）为 Phase 94 最后一块。

## Self-Check: PASSED

- `server/mcp_tools/orchestration_delegate.py` — FOUND
- `server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py` — FOUND
- Commit `97adec023` / `06ed87966` — FOUND
- `uv run pytest tests/mcp_tools -k technical_plan` → 12 passed；广域回归（tests/mcp_tools + entry_consistency + TestMcpTriggers）→ 144 passed
- ruff check + mypy（orchestration_delegate / technical_plan_service / entrypoint）干净；`makemigrations --check` 无新迁移

---
*Phase: 94-entrypoint-unify*
*Completed: 2026-06-27*
