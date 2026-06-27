---
phase: 92-capability-slot-backend
plan: 02
subsystem: workflow-node-slots
tags: [workflow, node-port, shape, slot, clarification, feishu-card, plan-orchestration]

# Dependency graph
requires:
  - phase: 92-capability-slot-backend
    provides: NodePort.shape 能力契约字段 + KNOWN_PORT_SHAPES + _validate_port_shapes 契约兼容校验
  - phase: 91-clarification-outlets-resume
    provides: build_clarification_card(clarification_id) + plan_clarify_answer 路由 + _send_clarify_card
provides:
  - ai_plan_research clarify 输出端口（shape=clarification_request，凹槽）
  - ai_plan_research resume 输入端口（shape=clarification_answer，凸点）
  - build_clarification_card action 关键字参数（默认 plan_clarify_answer，可传 clarify_card_answer）
affects: [92-03, 93-slot-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "插槽端口 = 仅 NodePort 声明（带 shape），execute 运行时不经新 handle 路由（声明≠分支）"
    - "回调 action 前缀参数化（默认值=现状）保向后兼容，前缀经 startswith 物理隔离"

key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/plan_research.py
    - server/feishu/cards/chat_question_card.py
    - server/tests/workflows/test_plan_research_node.py
    - server/tests/feishu/test_chat_question_card.py

key-decisions:
  - "clarify/resume 为 additive 端口声明：execute/_map_terminal/_maybe_suspend 一字未改，NodeResult.next_handle 仍只走 default/error（Pitfall 5 / A4）"
  - "default/error 生产端口逐字保留且 shape 恒空（保「空契约=通配」零回归，不拦截既有 plan→coding 边）"
  - "build_clarification_card action 默认值=plan_clarify_answer（91 现状），不改 91 既有调用点 → 路由零回归"

patterns-established:
  - "节点暴露插槽端口 = 加 NodePort(shape=...) 声明，不动运行时驱动逻辑"

requirements-completed: [SLOT-02]

# Metrics
duration: 8min
completed: 2026-06-27
---

# Phase 92 Plan 02: ai_plan_research 澄清插槽端口 + 卡片 action 参数化 Summary

**ai_plan_research 暴露 clarify(out, shape=clarification_request) / resume(in, shape=clarification_answer) 插槽端口（仅声明、execute 运行时零改动）+ build_clarification_card 回调 action 前缀参数化（默认 plan_clarify_answer，向后兼容），为 92-03 standalone 澄清卡节点路由独立回调铺平。**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-27T10:39:55Z
- **Completed:** 2026-06-27T10:47:00Z
- **Tasks:** 2（均 TDD）
- **Files modified:** 4（0 created + 4 modified）

## Accomplishments

- `AIPlanResearchNode.inputs` 追加 `resume`（凸点，`shape="clarification_answer"`，`required=False`）；`outputs` 追加 `clarify`（凹槽，`shape="clarification_request"`）——供 Phase 93 编辑器形状磁吸 + `WorkflowGraphValidator._validate_port_shapes`（92-01）契约识别消费。
- 既有 `default`（含 schema）/`error` 生产端口逐字保留、`shape` 恒空（通配）——validator 双端任一空契约即短路放行，既有 `plan→coding` 边零回归。
- `get_schema()` 经 92-01 既有逐端口 dump `shape` 键，自动把 `clarify`/`resume` 的 shape 经 `/api/node-types/` 单向只读流出给前端。
- `build_clarification_card` 新增关键字参数 `action: str = "plan_clarify_answer"`，form_submit `value.action` 由硬编码改为该参数；其余 value 字段（execution_id/node_id/clarification_id/question_count/`q{i}`/`qt{i}`）逐字不变。
- docstring 补 `action` 说明：`plan_clarify_answer`（91 工作流澄清，绑 PlanSession）/ `clarify_card_answer`（92 standalone 卡）经 CardCallbackView `startswith` 物理隔离、互不抢占。

## Task Commits

每个任务原子提交（TDD：test → feat）：

1. **Task 1 RED: clarify/resume 端口存在性 + get_schema shape 失败测试** - `28009d173` (test)
2. **Task 1 GREEN: ai_plan_research clarify/resume 插槽端口声明** - `4192db2e7` (feat)
3. **Task 2 RED: build_clarification_card action 参数化失败测试** - `bb4d8c22d` (test)
4. **Task 2 GREEN: build_clarification_card action 关键字参数** - `487a51d89` (feat)

## Files Created/Modified

- `server/workflows/nodes/ai/plan_research.py` - inputs 加 resume(shape=clarification_answer)、outputs 加 clarify(shape=clarification_request)；default/error 端口与 execute/_maybe_suspend/_map_terminal 一字未改
- `server/feishu/cards/chat_question_card.py` - build_clarification_card 加 action 关键字参数（默认 plan_clarify_answer）+ form_submit value.action 取参数 + docstring 说明
- `server/tests/workflows/test_plan_research_node.py` - 新增端口存在性（behavior 1/2）+ get_schema shape（behavior 3）2 用例，更新 test_schema_and_registration 断言反映新端口集（behavior 4 零回归）
- `server/tests/feishu/test_chat_question_card.py` - 新增 TestBuildClarificationCardAction 3 用例（默认值/自定义值/并列锚字段）

## Decisions Made

- **clarify/resume 是声明，不是运行时分支（Pitfall 5 / A4）**：91 发卡逻辑已在 `_maybe_suspend`/`_send_clarify_card`，不依赖 clarify handle 路由；`NodeResult.next_handle` 仍只走 default/error。新端口仅供前端磁吸 + validator 识别契约，`execute`/`_map_terminal`/`_maybe_suspend` 一字未改。
- **不给现有 default/error 端口补契约（Open Questions 决议 #3）**：保 `shape=""` 通配，避免拦截既有生产边（validator 双端任一空即放行）。
- **build_clarification_card action 默认值=91 现状**：不改 91 既有调用点（`plan_research.py._send_clarify_card` 不传 action → 默认 plan_clarify_answer），91 工作流澄清路由零回归；92-03 standalone 卡节点显式传 `clarify_card_answer` 切换前缀。

## Deviations from Plan

None - plan executed exactly as written.

唯一附带动作：Task 1 GREEN 需同步更新既有 `test_schema_and_registration` 中对端口集的精确断言（`inputs == {default, resume}`、`outputs == {default, clarify, error}`）——这是新增端口的必然反映，非行为回归（behavior 4 的 execute/_maybe_suspend 行为测试逐字不变、全绿）。

## Issues Encountered

- **`tests/workflows tests/feishu` 全量 4 个失败经核实为既有失败、与本 plan 无关**：`test_execution_concurrency`（2，并发计时）+ `test_template_loader`（2，`technical_plan_generation` 模板 `generate_plan` 节点缺 `plan_markdown` 字段 `field_not_found`）。已将本 plan 2 个源文件回退至 base（`28c8d282a`）复跑确认 4 个失败**完全一致**（源于 war-room 未提交在制品，非 `incompatible_port_shape`，与本 plan shape 端口无关）。本 plan 相关用例 `test_plan_research_node.py`(15) + `test_chat_question_card.py`(13) 全绿。

## User Setup Required

None - 纯仓内 Python 改动，无外部服务配置、无新增依赖、无 DB 迁移。

## Next Phase Readiness

- SLOT-02 端口暴露半 + 卡片复用准备完成：92-03 可新建 `clarification_card` 节点（消费 `build_clarification_card(action="clarify_card_answer")`）+ 注册 `clarify_card_` 独立回调（answer_round 落库 + approve 本节点）。
- ⚠️ 92-03 新增节点后需重跑 `pnpm -C web gen:node-fixture`（92-01/92-02 仅加端口字段不 dump fixture，`_to_fixture_node` 不含 shape）。
- `ai_plan_research` 的 `clarify`/`resume` 端口经 `_validate_port_shapes`（92-01）约束：新建连边若双端 shape 非空且不等将报 `incompatible_port_shape`。

## Verification Results

- `uv run pytest tests/workflows/test_plan_research_node.py tests/feishu/test_chat_question_card.py -x -q` → 28 passed。
- `uv run pytest tests/workflows tests/feishu -q` → 703 passed, 4 failed（均既有，base 复跑一致）。
- `uv run ruff format --check`（2 文件）→ already formatted；`ruff check` → All checks passed。
- `uv run mypy workflows/nodes/ai/plan_research.py` → Success: no issues found。
- `uv run python manage.py makemigrations --check` → No changes detected（无 DB 迁移）。

## Self-Check: PASSED

- 全部 modified 文件存在（plan_research.py / chat_question_card.py / test_plan_research_node.py / test_chat_question_card.py / 92-02-SUMMARY.md）。
- 全部任务提交存在（28009d173 / 4192db2e7 / bb4d8c22d / 487a51d89）。

---
*Phase: 92-capability-slot-backend*
*Completed: 2026-06-27*
