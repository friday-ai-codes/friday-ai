---
phase: 94-entrypoint-unify
plan: 04
subsystem: mcp_tools
tags: [plan_orchestration, mcp_delegate, coding_plan, merged_plan, entrypoint_unify, single_repo]

# Dependency graph
requires:
  - phase: 94-entrypoint-unify (94-03)
    provides: "mcp_tools/orchestration_delegate.delegate_plan_orchestration + DelegateResult（共享 MCP delegate 核心）"
  - phase: plan_orchestration（既有）
    provides: "start_orchestration(include_repos=) 单仓约束 + canonical §7 MergedPlan/PlanVersion"
provides:
  - "create_coding_plan delegate 路径（include_repos=[repository_id] 单仓约束 + canonical execution_plan 该仓 task → 旧单仓响应字段映射）"
  - "planning_service.map_canonical_to_coding_plan（canonical §7 → affected_files/steps/test_plan/title 显式白名单）"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP create_coding_plan 入口归一到统一编排（复用 94-03 delegate_plan_orchestration，include_repos=[repository_id] 约束单仓），绝不在 MCP 层重写拆分/路由/调研/融合"
    - "canonical §7 execution_plan 该仓 task → 旧单仓 coding plan 字段显式映射白名单（外形兼容，不透传内部键，他仓 task 不进单仓响应）"

key-files:
  created:
    - server/tests/mcp_tools/test_create_coding_plan_delegate.py
  modified:
    - server/mcp_tools/views.py
    - server/mcp_tools/planning_service.py
    - server/tests/mcp_tools/test_planning_tools.py

key-decisions:
  - "CreateCodingPlanView.post 方案生成从确定性 build_coding_plan seam 改 delegate_plan_orchestration(include_repos=[repository_id])——单仓约束让编排只跑该仓（Open Q2 决议）；复用 94-03 共享核心不造两套"
  - "新增 planning_service.map_canonical_to_coding_plan：从 canonical execution_plan 筛该 repository_id 的 task（取首个匹配；无匹配回退首项；空则最小结构）→ 显式映射 affected_files(files[].path)/steps(coding_instruction 拆解最小步骤)/test_plan(canonical 无 per-task 测试字段→空 list)/risks(content.risks 回退 compat_risks)/title(content.title 或 repo.name)；缺字段填空不抛（T-94-04-INFO 白名单不透传内部键）"
  - "build_coding_plan 函数保留（不删，标注 [DEPRECATED — UNIFY-04] 被 delegate 取代），对齐「seam 被取代但函数保留」State of the Art"
  - "McpCodingPlan/McpCodingPlanVersion 继续落库（A5 字段全保留）；plan_body 优先 canonical content，挂起/失败态 content={} 时回退映射后单仓 payload；output 旧键全保留 + 新增可选 session_id（partial 续推钥匙）+ status（delegate 终态映射）"
  - "actor 从 request.user 解析（mirror 94-03 与 CreateFeishuTechnicalPlanView 同源范式；InteractionRun 无 created_by 字段），非真实用户 None fail-closed 召回（T-94-04-ELEV 文档化降级）透传 delegate"
  - "MCP 层移除 _record_model_usage 调用（delegate 无 model_usage；编排 adapters 内部承担 LLM 埋点，call_source 链路完整，无需 view 层重复）"

patterns-established:
  - "MCP create_feishu_technical_plan（94-03）/ create_coding_plan（94-04）均经共享 delegate_plan_orchestration 收口到 canonical，三入口（feishu technical_plan / coding_plan / 工作流·对话）口径统一，消除分叉"

requirements-completed: [UNIFY-04]

# Metrics
duration: ~30min
completed: 2026-06-27
---

# Phase 94 Plan 04: MCP create_coding_plan delegate 到统一编排（单仓约束 + canonical 映射）Summary

**MCP `create_coding_plan` 产物口径收口到 `plan_orchestration`——复用 Plan 03 共享 `delegate_plan_orchestration` 核心，delegate 时 `include_repos=[repository_id]` 约束编排只跑单仓（Open Q2），从 canonical §7 `execution_plan` 中该仓 task 经新增 `map_canonical_to_coding_plan` 显式映射回旧单仓响应字段（affected_files/steps/test_plan/title），不再走独立确定性 `build_coding_plan` seam；McpCodingPlan/McpCodingPlanVersion 继续落库，output 旧键全保留 + 可选 session_id/status，至此 Phase 94 三入口口径统一收官**

## Performance

- **Duration:** ~30 min
- **Tasks:** 1
- **Files modified:** 4（1 created + 3 modified）

## Accomplishments

- **Task 1** — `CreateCodingPlanView.post` 方案生成从确定性 `build_coding_plan` 改 `delegate_plan_orchestration(requirement_text=..., work_item=None, include_repos=[repository_id], created_by=actor)`——`include_repos=[repository_id]` 约束编排只跑单仓（Open Q2 决议）。新增 `planning_service.map_canonical_to_coding_plan`：从 canonical §7 `execution_plan` 筛该 `repository_id` 的 task（取首个匹配；无匹配回退首项；空则最小结构）→ 显式映射回旧单仓字段（`affected_files`←files[].path、`steps`←coding_instruction 拆解最小步骤结构、`test_plan`←canonical 无 per-task 测试字段故 best-effort 空 list、`risks`←content.risks 回退 compat_risks、`title`←content.title 或 repo.name），缺字段填空不抛（T-94-04-INFO 白名单不透传内部键，他仓 task 不进单仓响应）。`McpCodingPlan`/`McpCodingPlanVersion` 继续落库（plan_body 优先 canonical content，content={} 时回退映射 payload；字段全保留兼容 A5）。`output_data` 保留全部旧键（plan_id/version_id/version/repository_id/branch/plan/evidence/run_id）+ 新增可选 `session_id`（partial 续推）+ `status`（delegate 终态映射）。actor 从 `request.user` 解析（is_authenticated + id 守卫，None fail-closed）透传 delegate。`build_coding_plan` 保留并标注 `[DEPRECATED — UNIFY-04]`。新建 `test_create_coding_plan_delegate.py`（6 守护）+ 更新 `test_planning_tools.py` 适配 delegate seam。

## Task Commits

1. **Task 1: create_coding_plan delegate 接线 + canonical 单仓映射 + 落库/响应守护** — `13ce88a5d` (feat)

## Files Created/Modified

- `server/mcp_tools/views.py` — `CreateCodingPlanView.post` 改 delegate 路径（include_repos=[repository_id] + actor 解析 + canonical 映射 + 落库保留 + output session_id/status）；移除 `_record_model_usage` 调用与 `build_coding_plan` 导入；新增 `delegate_plan_orchestration`/`map_canonical_to_coding_plan` 导入
- `server/mcp_tools/planning_service.py` — 新增 `map_canonical_to_coding_plan`（canonical §7 → 旧单仓字段显式白名单）；`build_coding_plan` 标注 `[DEPRECATED — UNIFY-04]`（保留）
- `server/tests/mcp_tools/test_create_coding_plan_delegate.py` (新建) — 6 守护：① delegate 被调 + include_repos=[repository_id] 单仓 + actor 透传 ② canonical 该仓 task → affected_files/steps/test_plan/title 映射 ③ 响应键 snapshot（旧键全在 + session_id + status）④ McpCodingPlan/McpCodingPlanVersion 落库 ⑤ partial 挂起态 output 携 session_id 不崩 ⑥ 空 content 映射安全降级（map 单元）
- `server/tests/mcp_tools/test_planning_tools.py` — `test_create_coding_plan_stores_version_and_evidence` 改 monkeypatch delegate 适配新 seam（断言映射后单仓字段 + 落库 + 工具调用/召回 trace；移除 ModelUsageRecord 断言）

## Decisions Made

见 frontmatter key-decisions。要点：单仓约束经 `include_repos=[repository_id]`（Open Q2 决议）；canonical execution_plan 该仓 task 显式字段映射白名单（外形兼容、不透传内部键、他仓 task 不进单仓响应，T-94-04-INFO）；响应外形兼容（旧键全保留 + 可选 session_id/status）+ 落库兼容（plan_body 优先 canonical content，挂起/失败回退映射 payload）；actor 取 request.user（None fail-closed，T-94-04-ELEV）；MCP 层不再记 model_usage（编排 adapters 承担）。

## Deviations from Plan

### [Rule 1 - Tests broken by intended behavior change] 更新 delegate seam 切换波及的既有测试

- **Found during:** Task 1（回归 `-k coding_plan` 守护）
- **Issue:** 方案生成从确定性 `build_coding_plan` 改 delegate 后，`test_planning_tools.py::test_create_coding_plan_stores_version_and_evidence` 断言旧确定性形态（src/main.py 来自 chunk/file_paths、`body["plan"]["test_plan"]` 非空、`ModelUsageRecord` 由 MCP 层记录）已失效；且该测试原走真实路径，delegate 化后会触发真实编排（router 无 provider → 优雅 FAILED → content={}）。
- **Fix:** 改 monkeypatch `mcp_tools.views.delegate_plan_orchestration` 返回 canonical DONE（含 src/main.py task files）→ 断言映射后单仓字段（affected_files 含 src/main.py、steps 非空、status=completed、session_id）+ McpCodingPlan(Version) 落库 + ToolCallRecord/RetrievalTrace；移除 `ModelUsageRecord` 断言（MCP 层不再记 model_usage，编排 adapters 承担）。`test_improve_coding_plan_appends_new_version`（仅用 create 取 plan_id、improve 路径未改）零回归无需改。
- **Files modified:** server/tests/mcp_tools/test_planning_tools.py
- **Commit:** 13ce88a5d

### [Plan 文本澄清 - actor 来源] InteractionRun 无 created_by 字段

- PLAN 文本写「从 run 的 created_by_id → User」，但 `InteractionRun` 模型无 `created_by` 字段；改从 `request.user` 解析 actor（与 94-03 `CreateFeishuTechnicalPlanView` / `report_project_knowledge` 等 MCP 写入视图同源范式），非真实用户 None fail-closed。语义等价、满足 T-94-04-ELEV。

## Issues Encountered

- `mcp_tools/planning_service.py` 与 `mcp_tools/views.py` 在 HEAD 即非 ruff-format-clean（预存量，超本 plan 范围）——仅对本 plan 新增/改动代码施加最小格式（`map_canonical_to_coding_plan` 的 title 表达式按 ruff 折行），未全量 reformat 既有非 clean 行（避免无关 churn，SCOPE BOUNDARY）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 94（入口统一）收官：UNIFY-01~06 全落地，三入口（feishu technical_plan / coding_plan / 工作流·对话）口径统一到同一 canonical MergedPlan，分叉消除。
- 守护测试：`test_create_coding_plan_delegate` 6 passed + `tests/mcp_tools` 全量 147 passed；ruff（受改代码）/mypy（views/planning_service）干净、`makemigrations --check` 无新迁移、schema snapshot 守护通过（MCP contract 不漂移）。
- 下游：Phase 95（DECOMP-01 拆分完善）相对独立，可收尾推进。

## Threat Flags

无新增安全相关 surface（纯内部重构：复用既有 delegate 核心 + 单仓约束经既有 `_get_indexed_repo` 校验 + 映射白名单；无新网络端点/认证路径/schema 改动）。

## Self-Check: PASSED

- `server/tests/mcp_tools/test_create_coding_plan_delegate.py` — FOUND
- `server/mcp_tools/planning_service.py::map_canonical_to_coding_plan` — FOUND
- Commit `13ce88a5d` — FOUND（`git log` 可查）
- `uv run pytest tests/mcp_tools/test_create_coding_plan_delegate.py` → 6 passed；`-k coding_plan` → 10 passed；`tests/mcp_tools` 全量 → 147 passed
- ruff check（受改代码）+ mypy（views/planning_service）干净；`makemigrations --check` 无新迁移；schema snapshot 1 passed

---
*Phase: 94-entrypoint-unify*
*Completed: 2026-06-27*
