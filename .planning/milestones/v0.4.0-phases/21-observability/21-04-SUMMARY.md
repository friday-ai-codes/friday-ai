---
phase: 21-observability
plan: 04
subsystem: workflows
tags: [django-migration, text-choices, websocket-hook, observability, trigger-cleanup, tdd-green]

# Dependency graph
requires:
  - phase: 21-observability
    provides: 21-01 RED 测试锚点（test_trigger_type_choices.py / test_hooks.py WS 广播）
  - phase: 18-engine
    provides: NodeExecution.error_message/error_code 字段
provides:
  - "TRIG-02：Workflow.TriggerType.choices 不含 schedule + 0027 AlterField 安全收窄"
  - "OBS-01 后端：WebSocketBroadcastHook 失败/超时态广播 error_message/error_code 可选键"
affects: [前端 WS 失败展示消费方, 涉及 trigger_type 枚举的序列化/校验]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TextChoices 收窄走 AlterField migration（无 DB 约束，存量行不报错）+ 可选 RunPython 数据归一"
    - "WS Hook 仅失败态追加可选键（向后兼容），沿用 node_debug_paused 条件键写法"

key-files:
  created:
    - server/workflows/migrations/0027_remove_schedule_trigger_type.py
  modified:
    - server/workflows/models/workflow.py
    - server/workflows/hooks/builtin.py

key-decisions:
  - "0027 同时含可选 RunPython（schedule→manual update），更干净且可逆为 noop，禁止删行/CHECK 约束"
  - "error_message 透传时截断 2000 字符（防超大 payload），error_code 透传原值，不二次拼接敏感数据"

requirements-completed: [TRIG-02, OBS-01]

# Metrics
duration: ~14min
completed: 2026-06-13
---

# Phase 21 Plan 04: TRIG-02 枚举清理 + OBS-01 WS 失败广播 Summary

**移除僵尸触发类型 schedule（枚举 + 0027 AlterField 安全收窄），并让 WebSocketBroadcastHook 在节点失败/超时时广播 error_message/error_code，将 21-01 的 RED 测试转绿。**

## Performance

- **Duration:** ~14 min
- **Tasks:** 3
- **Files modified:** 3（1 新建 migration + 2 源码修改）

## Accomplishments
- TRIG-02（Task 1）：`Workflow.TriggerType` 删除 `SCHEDULE`，保留 manual/webhook/event，补充「外部 cron→webhook」口径注释。
- TRIG-02（Task 2）：新建 `0027_remove_schedule_trigger_type.py`——AlterField 收窄 choices + 可选 RunPython 将存量 schedule 行归一为 manual；依赖 0026，无 RunSQL/AddConstraint/CheckConstraint。
- OBS-01（Task 3）：`WebSocketBroadcastHook` 在 `node_execution.status in ("failed", "timeout")` 时追加 `error_message`（截断 2000）/`error_code`，成功态不写入键；AlertRuleHook 不受影响。

## Task Commits

每个任务独立原子提交：

1. **Task 1: TriggerType 移除 SCHEDULE（TRIG-02）** - `ce2fac994` (feat)
2. **Task 2: 新增 0027 migration 收窄 trigger_type choices（TRIG-02）** - `489a1614d` (feat)
3. **Task 3: WS 广播失败态追加 error_message/error_code（OBS-01）** - `edab90614` (feat)

**Plan metadata:** (本提交) `docs(21-04): complete trigger cleanup + WS error broadcast plan`

## Files Created/Modified
- `server/workflows/models/workflow.py` - `TriggerType` 移除 SCHEDULE 枚举值并加注释。
- `server/workflows/migrations/0027_remove_schedule_trigger_type.py` - 新建。AlterField 收窄 choices + 可选 schedule→manual RunPython。
- `server/workflows/hooks/builtin.py` - `WebSocketBroadcastHook` 失败/超时态追加可选 error 键。

## RED → GREEN 验收

| 用例 | 文件 | 结果 |
|------|------|------|
| `test_trigger_type_choices_exclude_schedule` | test_trigger_type_choices.py | GREEN |
| `test_trigger_type_choices_keep_others` | test_trigger_type_choices.py | GREEN（回归保护） |
| `test_broadcast_failed_node_includes_error_fields` | test_hooks.py | GREEN |
| `test_broadcast_timeout_node_includes_error_fields` | test_hooks.py | GREEN |
| `test_broadcast_success_node_omits_error_fields` | test_hooks.py | GREEN（向后兼容） |

- `makemigrations --check --dry-run workflows`：`No changes detected`（模型/迁移一致）。
- `migrate workflows --plan`：列出 0027（AlterField + RunPython），无报错。
- `tests/workflows/`：**476 passed**，零回归。
- `test_alert_rules.py`：11 passed，AlertRuleHook 不回退。

## Decisions Made
- 0027 在 AlterField 之外追加可选 `RunPython(forwards, noop)`，将存量 `trigger_type="schedule"` 归一为 `manual`，更干净且可逆；严格仅 update，禁止删行/CHECK 约束（Pitfall 3，TextChoices 无 DB 约束）。
- `error_message` 透传时 `[:2000]` 截断防止超大 payload（呼应 T-21-04-03 / additional_context），`error_code` 原值透传；不二次拼接敏感数据（值由 Phase 17/18 已产出摘要+末行 JSON）。

## Deviations from Plan

None - plan executed exactly as written.

（说明：PLAN Task 3 action 写"直接透传"，本实现在透传基础上对 error_message 追加 `[:2000]` 长度上限，与 additional_context「str[:2000] 截断不泄露值」一致；不改变测试断言值，非语义偏离。）

## Deferred Issues
- `server/workflows/hooks/builtin.py` 存在 5 处 **既有** ruff I001（import block 未排序，位于 L254/270/307/367/408 的内层函数 import，与本计划改点无关）。属 SCOPE BOUNDARY 之外的 pre-existing lint，未在本计划修复；本计划改点（L67-77 附近）未引入新告警。

## Threat Surface Scan
- T-21-04-01（WS error_message 信息泄露）：已 mitigate——仅失败态写入、execution_{id} group 隔离、直接透传后端已产出摘要并 2000 截断，不二次拼接 payload/凭证。
- T-21-04-02（migration 误删存量）：已 mitigate——仅 AlterField + update，无删行/CHECK 约束。
- 未发现 PLAN `<threat_model>` 之外的新增安全面。

## Known Stubs
None.

## User Setup Required
None.

## Self-Check: PASSED

- `server/workflows/models/workflow.py`、`server/workflows/migrations/0027_remove_schedule_trigger_type.py`、`server/workflows/hooks/builtin.py`、本 SUMMARY.md 均存在（FOUND）。
- 3 个任务提交 `ce2fac994` / `489a1614d` / `edab90614` 均在 git 历史中（FOUND）。

---
*Phase: 21-observability*
*Completed: 2026-06-13*
