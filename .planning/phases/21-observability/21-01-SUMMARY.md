---
phase: 21-observability
plan: 01
subsystem: testing
tags: [pytest, pytest-asyncio, django-test, feishu, workflow-triggers, websocket, tdd-red]

# Dependency graph
requires:
  - phase: 18-engine
    provides: NodeExecution.error_message/error_code 字段、execution 终态语义
provides:
  - "TRIG-01 后端 RED 测试：async_sync_workflow_triggers 单数同步 / 复数兜底 / filter_config 映射 / 端到端匹配 / OQ#1 负向字段排除"
  - "TRIG-02 后端 RED 测试：Workflow.TriggerType choices 不含 schedule"
  - "TRIG-03 后端 RED 测试：飞书 _dispatch_to_workflows 失败/无匹配 TriggerLog 持久化"
  - "OBS-01 后端 RED 测试：WebSocketBroadcastHook 失败态广播 error_message/error_code"
affects: [21-03 同步与枚举修复, 21-04 dispatch 失败持久化与 WS 广播]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED 锚点：先行失败测试断言修复后契约，由后续实现计划转绿（Nyquist 验证锚点）"
    - "async DB 测试：@pytest.mark.asyncio + @pytest.mark.django_db(transaction=True) + acreate（照抄 test_hooks.py 范式）"
    - "WebSocketBroadcastHook 单测：patch channels.layers.get_channel_layer + SimpleNamespace 构造 execution/node_execution（不触 DB）"

key-files:
  created:
    - server/tests/workflows/test_trigger_sync.py
    - server/tests/workflows/test_trigger_type_choices.py
  modified:
    - server/tests/test_trigger_dispatcher.py
    - server/tests/workflows/test_hooks.py

key-decisions:
  - "created_by 可空 → 测试自建 Project/Workflow，省去 user 夹具，降低跨夹具耦合"
  - "legacy event_types 兜底用例当前 GREEN（现状读复数即生效）——作为修复后回归保护保留，非 RED"
  - "FeishuWebhookView._dispatch_to_workflows 不引用 self，直接 view 实例 + patch feishu.views.TriggerDispatcher 注入失败行为"

patterns-established:
  - "RED 失败必须是断言失败（非 collection/import error）：本计划全部 RED 失败均为 assert 级"

requirements-completed: []  # 本计划仅建立 RED 测试锚点；TRIG-01/02/03、OBS-01 待 21-03/04 实现转绿后标记

# Metrics
duration: 16min
completed: 2026-06-13
---

# Phase 21 Plan 01: 后端测试脚手架（TDD RED）Summary

**为 TRIG-01/02/03 + OBS-01（后端）建立 13 个先行失败测试锚点：feishu 触发同步、schedule 枚举移除、dispatch 失败持久化、WS 失败广播——锁死修复后契约，待 21-03/04 转绿。**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-06-13T15:09:00Z
- **Completed:** 2026-06-13T15:13:30Z
- **Tasks:** 3
- **Files modified:** 4（2 新建 + 2 扩展）

## Accomplishments
- TRIG-01：新建 `test_trigger_sync.py`，5 用例覆盖单数同步、复数兜底、filter_config 映射、端到端 matches_event、OQ#1 负向字段排除。
- TRIG-02：新建 `test_trigger_type_choices.py`，断言 choices 移除 schedule、保留 manual/webhook/event。
- TRIG-03：扩展 `test_trigger_dispatcher.py`，新增 `TestFeishuDispatchFailurePersistence`，断言异常→error、无匹配→ignored 持久化（error_message ≤2000）。
- OBS-01：扩展 `test_hooks.py`，3 用例断言失败/超时广播含 error 字段、成功态不含（向后兼容）。
- 4 文件 `--collect-only` 共 36 用例全部收集成功，无 import/collection error。

## Task Commits

Each task was committed atomically:

1. **Task 1: 新建 test_trigger_sync.py（TRIG-01）** - `e92a7088b` (test)
2. **Task 2: 新建 test_trigger_type_choices.py + 扩展 test_trigger_dispatcher.py（TRIG-02/TRIG-03）** - `8625075b8` (test)
3. **Task 3: 扩展 test_hooks.py（OBS-01）** - `2b41be61b` (test)

**Plan metadata:** (本提交) `docs(21-01): complete backend test scaffold plan`

## Files Created/Modified
- `server/tests/workflows/test_trigger_sync.py` - 新建。TRIG-01 同步/兜底/filter_config/端到端/OQ#1 RED 测试。
- `server/tests/workflows/test_trigger_type_choices.py` - 新建。TRIG-02 choices 断言。
- `server/tests/test_trigger_dispatcher.py` - 扩展。TRIG-03 飞书路径失败/无匹配持久化断言。
- `server/tests/workflows/test_hooks.py` - 扩展。OBS-01 WS 失败广播 error 字段断言。

## RED 用例清单与转绿计划

| 用例 | 文件 | 当前状态 | 转绿计划 |
|------|------|----------|----------|
| `test_singular_event_type_creates_trigger` | test_trigger_sync.py | RED（读复数→trigger_count=0） | 21-03 |
| `test_filter_config_maps_project_and_work_item` | test_trigger_sync.py | RED（无 trigger 生成） | 21-03 |
| `test_e2e_match` | test_trigger_sync.py | RED（无 trigger 生成） | 21-03 |
| `test_exclude_and_project_ids_not_in_filter_config` | test_trigger_sync.py | RED（无 trigger 生成） | 21-03 |
| `test_legacy_event_types_array_fallback` | test_trigger_sync.py | **GREEN**（现状读复数即生效，回归保护） | — |
| `test_trigger_type_choices_exclude_schedule` | test_trigger_type_choices.py | RED（choices 仍含 schedule） | 21-03 |
| `test_trigger_type_choices_keep_others` | test_trigger_type_choices.py | **GREEN**（回归保护） | — |
| `test_dispatch_exception_sets_triggerlog_error` | test_trigger_dispatcher.py | RED（异常仅 structlog，status 恒 ACCEPTED） | 21-04 |
| `test_dispatch_no_match_sets_triggerlog_ignored` | test_trigger_dispatcher.py | RED（无匹配不更新 status） | 21-04 |
| `test_broadcast_failed_node_includes_error_fields` | test_hooks.py | RED（message 不含 error_*） | 21-03/04 |
| `test_broadcast_timeout_node_includes_error_fields` | test_hooks.py | RED（message 不含 error_*） | 21-03/04 |
| `test_broadcast_success_node_omits_error_fields` | test_hooks.py | **GREEN**（向后兼容回归保护） | — |

**RED 计数：** 8 RED（断言级失败）+ 3 GREEN 回归保护 + 既有未受影响用例。所有 RED 均为 `assert` 级失败，非 collection/import error（符合 Wave 0 预期）。

## Decisions Made
- 测试自建 `Project`/`Workflow`（created_by 可空），避免依赖 `user` 夹具，降低与 transaction=True 异步事务的耦合风险。
- `legacy event_types` 兜底用例在现状下即 GREEN（当前代码读复数），保留为修复后回归保护，不强求 RED。
- TRIG-03 直接实例化 `FeishuWebhookView` 调 `_dispatch_to_workflows`（该方法不引用 self），并 `patch("feishu.views.TriggerDispatcher")` 注入失败/空返回行为。

## Deviations from Plan

None - plan executed exactly as written.

（注：计划锚点 verify 命令 `<automated>` 在 RED 阶段预期失败，已按 objective 显式说明正常提交失败测试；未实现源码使其转绿，源码实现为 21-03/04 职责。）

## Issues Encountered
- 首次运行 pytest 时因 shell 重复 `cd server` 导致工作目录漂移、报 file not found；改用绝对 working_directory 重跑解决，与测试本身无关。
- `uv run` 会改写 `server/uv.lock`；每次提交前 `git checkout -- server/uv.lock` 还原（无新增依赖）。

## Known Stubs
None - 本计划仅产出测试文件，无 UI/数据桩。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 21-03（同步修复 + schedule 枚举移除 + WS 广播）：可直接以 `test_trigger_sync.py` / `test_trigger_type_choices.py` / `test_hooks.py` 失败态用例为转绿验收锚点。
- 21-04（dispatch 失败持久化）：以 `TestFeishuDispatchFailurePersistence` 为转绿验收锚点。
- 阻塞/风险：无。RED 测试已锁死契约形态（filter_config 键名、error_message 截断 ≤2000、message error 可选键）。

## Self-Check: PASSED

- 4 测试文件 + SUMMARY.md 均存在（FOUND）。
- 3 个任务提交 `e92a7088b` / `8625075b8` / `2b41be61b` 均在 git 历史中。

---
*Phase: 21-observability*
*Completed: 2026-06-13*
