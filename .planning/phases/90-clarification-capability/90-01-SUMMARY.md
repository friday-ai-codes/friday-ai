---
phase: 90-clarification-capability
plan: 01
subsystem: database
tags: [django, orm, migration, clarification, plan_orchestration, jsonfield]

# Dependency graph
requires:
  - phase: pre-existing delivery app
    provides: Clarification 单题模型（0016）+ migration head 0025_rename_project_to_space
provides:
  - Clarification 轮次容器新字段（round_no/container_status/origin_repo/plan_version_id，全 nullable）
  - ClarificationQuestion 子表（多问题 + 单/多选 + 选项 + 推荐项 + 按题答案 + recommendation_adopted 采纳信号）
  - 迁移 0026_clarification_questions（依赖 0025，向后兼容）
  - barrel re-export delivery.models.ClarificationQuestion
affects: [90-02 service 写入收口, 90-03 adapter LLM 接线, 90-04 统一 helper, Phase 91 出口面/多轮 resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "父子模型 + 最小迁移：沿用 Clarification 作轮次容器（加 nullable 字段）+ 新建子表，旧行不破坏"
    - "字段命名规避：container_status（非 status）避免状态机误判；qtype（非 type）避开 Python 内建"
    - "采纳信号建模：recommendation_adopted nullable 持久化，作答时定格（本 plan 仅建字段，写入归 service）"

key-files:
  created:
    - server/delivery/migrations/0026_clarification_questions.py
  modified:
    - server/delivery/models/clarification.py
    - server/delivery/models/__init__.py

key-decisions:
  - "沿用 Clarification 作轮次容器（非新建 ClarificationRound）—— 最小迁移成本（CONTEXT Claude's Discretion 倾向）"
  - "新字段一律 null=True, blank=True；保留既有 question/answer/answered_at/affected_partials 不删（向后兼容）"
  - "迁移交 makemigrations 自动生成后人工核对 + 重命名为 0026_clarification_questions.py（未手写迁移逻辑、无数据回填）"
  - "模型层零业务方法（守 INV-6，写入逻辑归 90-02 ClarificationService）"

patterns-established:
  - "Pattern: ClarificationQuestion 子表 FK CASCADE + related_name=questions + db_table=delivery_clarification_question + 复合索引 [clarification, order]"
  - "Pattern: 采纳率可按题 SQL 聚合（recommendation_adopted__isnull=False 为分母）"

requirements-completed: [CLARIFY-01]

# Metrics
duration: 5min
completed: 2026-06-27
---

# Phase 90 Plan 01: 结构化澄清数据脊柱 Summary

**把 Clarification 扩展为轮次容器（4 个 nullable 字段）并新建 ClarificationQuestion 子表，承载多问题/单多选/选项/推荐项/按题答案 + 持久化 recommendation_adopted 采纳信号，全部向后兼容（迁移 0026 依赖 0025）。**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-27T06:15:00Z
- **Completed:** 2026-06-27T06:18:30Z
- **Tasks:** 2
- **Files modified:** 3（1 created, 2 modified）

## Accomplishments
- `Clarification` 新增 4 个 nullable 容器字段：`round_no`（多轮序号）/`container_status`（pending/answered/skipped）/`origin_repo`（CLARIFY-03 携带）/`plan_version_id`（采纳率分析冗余绑定，canonical 仍是 session.current_plan_version）。
- 新建 `ClarificationQuestion` 子表：`order`/`question`/`qtype`/`options`/`recommended`/`origin_repo`/`selected`/`freeform_text`/`answered_at`/`recommendation_adopted`/`created_at`，FK CASCADE `related_name="questions"`，`db_table="delivery_clarification_question"`，复合索引 `[clarification, order]`。
- 迁移 `0026_clarification_questions` 自动生成、依赖 `0025_rename_project_to_space`、`makemigrations --check` 干净、可正向 `migrate`（SQLite dev DB 验证通过）。
- barrel re-export `ClarificationQuestion`（`__init__.py` import + `__all__`），既有 `question`/`answer`/`answered_at`/`affected_partials` 字段保留未删。

## Task Commits

Each task was committed atomically:

1. **Task 1: 扩展 Clarification 容器 + 新建 ClarificationQuestion 子表 + barrel re-export** - `2c6f530bb` (feat)
2. **Task 2: 生成迁移 0026（容器 AddField + 子表 CreateModel，依赖 0025）** - `2f6b75dab` (feat)

_Note: 模型层零业务方法（写入逻辑归 90-02），无 TDD 拆分。_

## Files Created/Modified
- `server/delivery/models/clarification.py` - 容器新增 4 nullable 字段 + 新建 ClarificationQuestion 子表（含中文 docstring，零业务方法）
- `server/delivery/models/__init__.py` - re-export ClarificationQuestion + `__all__` 条目
- `server/delivery/migrations/0026_clarification_questions.py` - 容器 4 AddField（全 nullable）+ ClarificationQuestion CreateModel，依赖 0025

## Decisions Made
- **沿用 Clarification 作轮次容器**（非新建 ClarificationRound）：最小迁移成本，无需迁现有 FK/测试（CONTEXT Claude's Discretion 授权）。
- **新字段全 nullable + 保留既有列**：旧行 migrate 后仍可读，不强制回填历史（T-90-01-01 缓解）。
- **字段命名规避**：`container_status`（非 `status`）避免与 `PlanSession.status` 混淆 + 迁移误判状态机字段；`qtype`（非 `type`）避开 Python 内建（T-90-01-03 缓解）。
- **迁移自动生成后重命名**：`makemigrations delivery` 生成 `0026_clarification_container_status_and_more.py` → 重命名为计划指定的 `0026_clarification_questions.py`（语义更清晰），未手写迁移逻辑、无数据回填。

## Deviations from Plan

None - plan executed exactly as written. 唯一微调：Django 自动生成的迁移文件名 `0026_clarification_container_status_and_more.py` 重命名为计划指定的 `0026_clarification_questions.py`（计划 Task 2 action 已明确要求此重命名，非偏离）。

## Issues Encountered
- Task 1 自动化校验用裸 `python -c` 导入 Django 模型报 `ImproperlyConfigured`（settings 未配置）——改用 `manage.py shell -c` 执行同等断言，校验通过（环境差异，非代码问题）。

## Threat Surface Scan
本 plan 仅新增 Django 模型字段 + 子表 + nullable 迁移，无新网络端点/认证路径/文件访问/信任边界 schema 变化。threat_model 三项 mitigate（T-90-01-01/02/03）均已落实：新字段全 nullable 不破坏旧行；模型层零业务方法（写入收口待 90-02 service + INV-6 grep 守护扩展）；命名规避 status/type 冲突。无新增威胁面。

## Known Stubs
None - 本 plan 是数据模型层（建表/字段），无 UI 渲染、无 mock 数据。`recommendation_adopted` 等字段的写入/计算逻辑按计划归属 90-02 ClarificationService，非 stub。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 数据脊柱就绪：90-02 可在此模型上扩展 `ClarificationService.create_round`/`answer_round`/`ahas_pending`（写入收口 + 采纳信号计算 + 向后兼容 pending 谓词）。
- INV-6 grep 守护需在 90-02 扩展覆盖 `ClarificationQuestion.objects.create`/`.save`（本 plan 未引入任何子表写入点，无 INV-6 缺口）。
- 部署/CI 升级时 `migrate` 自动建子表 `delivery_clarification_question` 并对旧 `delivery_clarification` 表加 nullable 列。

---
*Phase: 90-clarification-capability*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/delivery/models/clarification.py
- FOUND: server/delivery/migrations/0026_clarification_questions.py
- FOUND: .planning/phases/90-clarification-capability/90-01-SUMMARY.md
- FOUND commit 2c6f530bb (Task 1)
- FOUND commit 2f6b75dab (Task 2)
