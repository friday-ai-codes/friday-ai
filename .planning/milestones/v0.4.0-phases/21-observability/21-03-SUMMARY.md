---
phase: 21-observability
plan: 03
subsystem: workflow-triggers
tags: [feishu, workflow-triggers, filter-config, trigger-log, webhook, dispatch, tdd-green]

# Dependency graph
requires:
  - phase: 21-observability
    plan: 01
    provides: "TRIG-01 / TRIG-03 后端 RED 测试锚点（test_trigger_sync.py / test_trigger_dispatcher.py 飞书失败持久化）"
provides:
  - "TRIG-01：async_sync_workflow_triggers 单数 event_type 优先 + 复数兜底 + filter_config 正向映射"
  - "TRIG-03：飞书 _dispatch_to_workflows 失败/无匹配落 TriggerLog（error/ignored + 截断 error_message）"
  - "TRIG-03：webhook dispatch 异常返回结构化错误响应、无匹配带 reason 区分"
affects: [21-04 dispatch 失败持久化与 WS 广播]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "node.config → filter_config 仅写正向 include 字段（OQ#1：负向/Space UUID 留 v2，避免 _matches_filter 静默误匹配）"
    - "dispatch 失败态持久化：asave(update_fields=[...]) + str(e)[:2000] 截断（ASVS V7 仅人类可读摘要）"
    - "webhook 区分原因响应：异常 500 {status:error} / 无匹配 200 {reason:no_matching_trigger}"

key-files:
  created:
    - .planning/phases/21-observability/deferred-items.md
  modified:
    - server/workflows/api/views.py
    - server/feishu/views.py

key-decisions:
  - "单数 event_type 优先、历史复数 event_types 兜底并存（Pitfall 1：不删复数读取避免存量丢 trigger）"
  - "exclude_*/project_ids 不写入正向 filter_config（OQ#1 裁定，留 v2）"
  - "webhook path 触发不强塞 TriggerLog（难解析唯一 WebhookConfig，Pitfall 4）→ 改结构化响应"

requirements-completed: [TRIG-01, TRIG-03]

# Metrics
duration: 6min
completed: 2026-06-13
---

# Phase 21 Plan 03: TRIG-01 触发同步修复 + TRIG-03 dispatch 失败可查 Summary

**修复触发链路根因：`async_sync_workflow_triggers` 改读单数 `event_type`（复数兜底）并把可正向表达的 filter 字段写入 `filter_config`，消除"读复数→恒空→trigger 被 deactivate→飞书事件无法匹配"；dispatch 失败不再静默吞掉——飞书路径落 `TriggerLog`（error/ignored + 截断 error_message），webhook 路径返回区分原因的结构化响应。**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-13T15:27:44Z
- **Completed:** 2026-06-13T15:33:17Z
- **Tasks:** 3
- **Files modified:** 2（+1 新建 deferred-items.md）

## Accomplishments
- TRIG-01：`async_sync_workflow_triggers` 读取改为 `event_type` 单数优先 + 历史复数 `event_types` 兜底；`filter_status`（数组，含 `filter_status_custom` 追加）→ `cur_work_item_status.state_key`；`filter_project_key`/`filter_work_item_type` → `project_key`/`work_item_type_key`；`project_ids`/`exclude_*` 不写入正向 filter_config（OQ#1）。`test_trigger_sync.py` 5 用例全绿（含端到端 matches_event）。
- TRIG-03 飞书：`_dispatch_to_workflows` 新增 `else` 无匹配分支（IGNORED + `event_type` 原因）与 `except` 异常分支（ERROR + `str(e)[:2000]`），均 `asave(update_fields=["status","error_message"])`；成功语义不变。`TestFeishuDispatchFailurePersistence` 2 用例全绿。
- TRIG-03 webhook：`WebhookTriggerView.post` 用 `try/except` 包住 `dispatcher.dispatch`，异常返回 HTTP 500 `{status:error, message:str(e)[:2000]}` + `webhook_dispatch_failed` 日志；无匹配 200 增 `reason:no_matching_trigger`。既有 webhook 测试零回退。

## Task Commits

Each task was committed atomically:

1. **Task 1: TRIG-01 单数读取 + filter_config 映射** - `eec091a86` (fix)
2. **Task 2: TRIG-03 飞书 dispatch 失败/无匹配落 TriggerLog** - `a8014eaa7` (fix)
3. **Task 3: TRIG-03 webhook 区分原因的结构化响应** - `e0cdde9c1` (fix)

## Files Created/Modified
- `server/workflows/api/views.py` - `async_sync_workflow_triggers` 单数读取 + filter_config 正向映射（TRIG-01）；`WebhookTriggerView.post` 异常/无匹配结构化响应（TRIG-03）。
- `server/feishu/views.py` - `_dispatch_to_workflows` 失败/无匹配落 TriggerLog 失败态 + 截断 error_message（TRIG-03）。
- `.planning/phases/21-observability/deferred-items.md` - 登记 4 项越界（out-of-scope）既有失败测试。

## 目标 RED 用例转绿情况

| 用例 | 文件 | 结果 |
|------|------|------|
| `test_singular_event_type_creates_trigger` | test_trigger_sync.py | GREEN |
| `test_legacy_event_types_array_fallback` | test_trigger_sync.py | GREEN（回归保护） |
| `test_filter_config_maps_project_and_work_item` | test_trigger_sync.py | GREEN |
| `test_e2e_match` | test_trigger_sync.py | GREEN |
| `test_exclude_and_project_ids_not_in_filter_config` | test_trigger_sync.py | GREEN |
| `test_dispatch_exception_sets_triggerlog_error` | test_trigger_dispatcher.py | GREEN |
| `test_dispatch_no_match_sets_triggerlog_ignored` | test_trigger_dispatcher.py | GREEN |

`test_trigger_sync.py` 全量 5 passed；`test_trigger_dispatcher.py -k "error or ignored or fail"` 4 passed。

## Deviations from Plan

None — plan executed exactly as written（Task 1/2/3 按 `<action>` 实现，无 Rule 1-4 触发）。

## Deferred Issues（越界，非本计划回归）

全量回归 `tests/workflows/ + tests/test_trigger*.py` 余 4 个失败，均在 21-03 之前即失败（已于临时 worktree 检出 HEAD~3 复现确认），且不属于本计划 requirements（TRIG-01/TRIG-03）或 files_modified；登记于 `deferred-items.md`，未修复：

| 失败用例 | 归属 | 处置计划 |
|----------|------|----------|
| `test_dispatch_success_returns_executions` | 18-05 ENG-03（`trigger_data` 新增 `source` 键，断言未同步） | 18-05 收尾 |
| `test_broadcast_failed_node_includes_error_fields` | OBS-01（WS 失败广播 RED） | 21-04 |
| `test_broadcast_timeout_node_includes_error_fields` | OBS-01（WS 失败广播 RED） | 21-04 |
| `test_trigger_type_choices_exclude_schedule` | TRIG-02（schedule 枚举移除 RED，本计划不含 TRIG-02 任务） | TRIG-02 实现计划 |

零回归：上述 4 项均非本计划引入；本计划目标集 9 用例全绿。

## Threat Surface

- T-21-03-01（Information Disclosure）：error_message 仅 `str(e)[:2000]` 截断摘要，未拼接 payload/凭证/node 输出值。已 mitigate。
- T-21-03-02（Tampering）：exclude_*/project_ids 不写入正向 filter_config。已 mitigate。
- T-21-03-03（DoS）：error_message 写入前 `[:2000]` 截断。已 mitigate。
- 未引入计划 `<threat_model>` 之外的新增安全面（零新依赖、内部重构）。

## Known Stubs
None — 均为既有代码内部修复，无 UI/数据桩。

## Self-Check: PASSED

- `server/workflows/api/views.py` / `server/feishu/views.py` / `deferred-items.md` 均存在（FOUND）。
- 提交 `eec091a86` / `a8014eaa7` / `e0cdde9c1` 均在 git 历史中。
- `ruff check` 两文件 All checks passed。

---
*Phase: 21-observability*
*Completed: 2026-06-13*
