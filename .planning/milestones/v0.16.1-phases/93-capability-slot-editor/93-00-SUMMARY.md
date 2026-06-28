---
phase: 93-capability-slot-editor
plan: 00
subsystem: api
tags: [drf, serializer, node-types, port-shape, slot, workflow]

# Dependency graph
requires:
  - phase: 92-capability-slot-backend
    provides: "NodePort.shape 字段 + get_schema() 每端口写入 shape 键（92-01/92-02/92-03）"
provides:
  - "NodePortSerializer.shape 字段声明——GET /api/node-types/ 端到端向前端暴露端口 shape（DRF 不再静默剥离）"
  - "GET /api/node-types/ 集成断言：shape 经序列化器透传非空（ai_plan_research.clarify / clarification_card.clarification_request）+ 通用端口空 shape 零回归"
affects: [93-01, 93-02, 93-05, 93-06, capability-slot-editor, resolvePortShape, 磁吸, 契约校验, 端口着色]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "只读接口补字段：序列化器声明缺失字段以停止 DRF 静默剥离 get_schema() 输出"
    - "端到端集成断言证伪：先 RED（补字段前断言失败）后 GREEN，证明真修 BLOCKER 而非自造数据掩盖"

key-files:
  created: []
  modified:
    - server/workflows/api/serializers.py
    - server/tests/workflows/test_node_schema.py

key-decisions:
  - "NodePortSerializer.shape = CharField(required=False, allow_blank=True, default='')——与 NodePort.shape: str = '' 同口径（空串=通配），既有节点零回归"
  - "集成断言走真实 reverse('node-type-list') + APIClient，不绕过序列化器（既有 get_schema 级断言无法捕获 DRF 剥离）"
  - "可观测性豁免：只读接口补字段、无新调用入口/LLM/召回，NodeTypeViewSet 已纳入既有请求统计 → 无需新增 structlog 事件/指标埋点"

patterns-established:
  - "序列化器补字段须配端到端集成断言（命中真实路由），单测级 get_schema 断言绕过序列化器会掩盖剥离缺口"

requirements-completed: [SLOT-03]

# Metrics
duration: ~12min
completed: 2026-06-27
---

# Phase 93 Plan 00: NodePortSerializer shape 暴露 Summary

**NodePortSerializer 补 shape 字段，闭合 /api/node-types/ 未向前端暴露端口 shape 的地基 BLOCKER（DRF 此前静默剥离 get_schema() 写入的 shape），并以端到端集成断言锁死 shape 不再被剥离。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T12:14:00Z
- **Completed:** 2026-06-27T12:20:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- `NodePortSerializer` 新增 `shape = serializers.CharField(required=False, allow_blank=True, default="")`，DRF 不再静默剥离 `NodePort.get_schema()` 写入的 shape，前端 `resolvePortShape` 可从权威 SSOT `/api/node-types/` 读到真实 shape。
- 新增 `TestNodeTypesApiExposesShape` 集成断言类（走真实 `reverse("node-type-list")` + APIClient）：端到端验证 `ai_plan_research.clarify` / `clarification_card.clarification_request` 端口回传 `shape=="clarification_request"`，通用 `ai_plan_research.default` 端口回传 `shape==""`（零回归通配）。
- RED→GREEN 证伪：补字段前 3 条新断言全部失败（DRF 剥离 shape），补字段后 7 项全绿，证明真修 BLOCKER 而非自造数据掩盖。

## Task Commits

Each task was committed atomically:

1. **Task 1: NodePortSerializer 补 shape 字段 + GET /api/node-types/ 集成断言** - `9c91e5cd5` (fix)

**Plan metadata:** (final docs commit — see below)

## Files Created/Modified
- `server/workflows/api/serializers.py` - `NodePortSerializer` 追加 `shape` 字段声明（CharField, allow_blank, default=""），停止 DRF 剥离
- `server/tests/workflows/test_node_schema.py` - 新增 `TestNodeTypesApiExposesShape`（@pytest.mark.django_db）+ `_find_port` helper，端到端断言 shape 透传与零回归

## Decisions Made
- `shape` 字段口径与 `NodePort.shape: str = ""` 完全一致（空串=通配），保既有节点零回归。
- 集成断言走真实路由 + APIClient，不绕过序列化器——既有 `test_node_schema.py` 的 `get_schema()` 级断言断言原始 dict、绕过序列化器，正是它掩盖了 DRF 剥离缺口。
- **可观测性判定（遵 AGENTS.md / observability-logging）**：本改动为既有只读接口补字段，无新调用入口、无新 LLM 调用、无新召回；`NodeTypeViewSet` 已存在且已纳入既有请求入口统计 → 无需新增 structlog 事件/指标埋点。威胁登记 T-93-00-INFO（shape 为非敏感能力语义标识，与 name/label/description 同级公开，端点已 IsAuthenticated）accept。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 集成断言中 `clarify` 端口归属修正为 outputs（plan 散文误写 inputs）**
- **Found during:** Task 1
- **Issue:** PLAN.md 散文与 must_haves 多处称 "ai_plan_research 的 clarify **input** 端口"，但 `server/workflows/nodes/ai/plan_research.py` 中 `clarify`（shape=clarification_request）实为 **output** 端口（inputs 仅 default/resume）。若照字面在 inputs 中查找 clarify，断言会因找不到端口而失败。
- **Fix:** 集成断言在 `node["outputs"]` 中查找 `name=="clarify"`，并在断言注释中标注其为 output 端口；`clarification_card.clarification_request`（input）与 `ai_plan_research.default`（output）按真实归属断言。
- **Files modified:** server/tests/workflows/test_node_schema.py
- **Verification:** RED 阶段 3 断言均按正确归属失败（证明 shape 被剥离而非端口找错），GREEN 阶段全绿。
- **Committed in:** 9c91e5cd5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 修正后断言反映真实端口拓扑，未改变 plan 验证意图（仍证明 DRF 不再剥离 shape）。无 scope creep。

## Issues Encountered
None - 计划核心改动（序列化器补字段 + 集成断言）按设计落地。

## Deferred Issues
- `uv run mypy server/workflows/api/serializers.py` 报 3 个 `arg-type` 错误，全部位于 `workflows/validation/graph_validator.py:443/469/500`（mypy 跟随 import 报出），与本 plan 改动文件无关、为 base 既有问题（war-room 未提交在制品范畴），未在范围内修复。本 plan 改动文件 `serializers.py` 自身 mypy 干净、ruff 干净。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 地基缺口闭合：`/api/node-types/` 端到端向前端暴露端口 shape，下游 93-01（契约兼容判定）→ 93-02 → 93-05/06（着色/磁吸）的前端 shape 消费不再恒为 no-op。
- Wave 1 就位，可推进 Phase 93 后续 plan（前端 @vue-flow 形状磁吸编辑器 + NodePalette 收录 clarification_card）。

## Self-Check: PASSED

- FOUND: server/workflows/api/serializers.py
- FOUND: server/tests/workflows/test_node_schema.py
- FOUND: .planning/phases/93-capability-slot-editor/93-00-SUMMARY.md
- FOUND: commit 9c91e5cd5 (fix(93-00): NodePortSerializer 暴露 shape 字段 + /api/node-types/ 集成断言)

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
