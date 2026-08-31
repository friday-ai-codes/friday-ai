# Phase 21 — Deferred / Out-of-Scope Items
- status: acknowledged


执行 21-03（TRIG-01 + TRIG-03）期间发现的、**不属于本计划契约**（files_modified 仅
`server/workflows/api/views.py` + `server/feishu/views.py`；requirements 仅 TRIG-01/TRIG-03）
的既有失败测试。均为先行 RED 或前序阶段引入，**未由 21-03 修复**，登记待对应计划处理。

| 失败用例 | 文件 | 归属 | 性质 | 处置计划 | status |
|----------|------|------|------|----------| --- |
| `test_dispatch_success_returns_executions` | tests/test_trigger_dispatcher.py | 18-05 ENG-03 | 前序阶段 `dispatcher.py` 在 `trigger_data` 新增 `source` 键（commit 03e9a46fc），该断言未同步更新。HEAD~3（21-03 前）已失败，非本计划回归。 | 18-05 收尾 / 测试断言对齐 | resolved |
| `test_broadcast_failed_node_includes_error_fields` | tests/workflows/test_hooks.py | OBS-01 | 21-01 建立的 RED 锚点（WS 失败广播 error 字段），21-03 计划不含 OBS-01 任务。 | 21-04（WS 广播） | resolved |
| `test_broadcast_timeout_node_includes_error_fields` | tests/workflows/test_hooks.py | OBS-01 | 同上。 | 21-04（WS 广播） | resolved |
| `test_trigger_type_choices_exclude_schedule` | tests/workflows/test_trigger_type_choices.py | TRIG-02 | 21-01 RED（choices 仍含 schedule），21-03 计划 requirements 仅 TRIG-01/TRIG-03，不含 TRIG-02 枚举移除。 | TRIG-02 实现计划 | resolved |

> 备注：本计划目标集（`test_trigger_sync.py` TRIG-01 5 用例 + `test_trigger_dispatcher.py`
> 飞书失败持久化 `TestFeishuDispatchFailurePersistence` 4 用例）已全部转绿；上述 4 项均
> 在 21-03 之前即为失败/RED，零回归。
