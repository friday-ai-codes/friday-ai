---
phase: 18-engine
plan: 03
subsystem: api
tags: [workflow-engine, scheduler, suspend, deadlock, hot-loop, waiting-event, pytest]

# Dependency graph
requires:
  - phase: 18-engine
    plan: 01
    provides: routing 五纯函数（diagnose_deadlock 等）+ RoutingState + engine barrel 导出
  - phase: 18-engine
    plan: 02
    provides: 主循环 node_statuses/node_handles 状态映射 + conftest waiting_*_workflow / WaitApprovalNode._exec_count
provides:
  - "_finalize_run_state 单一收口判定（挂起>死锁>失败>完成 优先级），主循环正常出口/stop_before 出口/无 ready 分支三处共用（18-04 重入路径消费）"
  - "waiting_event/waiting_approval 统一进 waiting 集合且不加回 pending——热循环根除、末端等待判 SUSPENDED"
  - "execution_suspended hook 可达（WS 广播链路打通）"
  - "主循环死锁经 routing.diagnose_deadlock 转 FAILED + 结构化 error_message（Phase 17 约定，末行 json.loads）"
  - "test_engine_waiting.py 挂起语义集成测试 + test_engine_deadlock.py 死锁写入侧集成类"
affects: [18-04, 18-05, 21-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "终局判定单一收口：双循环出口（正常退出 + stop_before 提前退出）+ 无 ready 分支统一调 _finalize_run_state，杜绝 Pitfall 5 双出口语义漂移"
    - "等待即挂起：waiting 节点不加回 pending，主循环挂起后线程立即退出，根除永久 running 僵尸线程（删 5s 轮询）"
    - "挂起优先于死锁的判定优先级：waiting 非空先 SUSPENDED，残留纯死锁在恢复续跑后由 18-04 重入暴露"

key-files:
  created:
    - server/tests/workflows/test_engine_waiting.py
  modified:
    - server/workflows/engine/scheduler.py
    - server/tests/workflows/test_engine_deadlock.py
    - server/tests/workflows/test_engine.py

key-decisions:
  - "调试串行路径也补 waiting_approval/waiting_event 收口分支（进 waiting 集合、不加回 pending），否则 debug 工作流挂起节点会落入 else→failed 误判（Rule 2 缺失功能补齐）"
  - "_finalize_run_state 死锁分支保留 diagnose 返回 None 的兜底文案（极少见状态不一致），仍写中文一句话失败，绝不抛出"
  - "既有 test_approval_node_waits / test_cancel_running_execution 即便在新语义下原样通过，仍按计划改写——删除恒真断言、改 run_sync 锁定 SUSPENDED 真实语义"

patterns-established:
  - "收口判定优先级闭集：waiting(suspend) → pending(deadlock-failed) → failed → completed"
  - "挂起集成测试范式：run_sync + 断言 ExecutionStatus.SUSPENDED + 按 node__name 查 NE 状态 + 耗时 < 3s 反证无轮询延时"

requirements-completed: [ENG-01, ENG-04]

# Metrics
duration: ~30min
completed: 2026-06-13
---

# Phase 18 Plan 03: waiting 挂起收口 + 死锁转 FAILED + 热循环根除 Summary

**主循环完成/挂起/死锁三类终局判定收口为单一 `_finalize_run_state`（双出口共用）：waiting_event/waiting_approval 统一挂起且不加回 pending（消灭热循环 + 永久 running 僵尸），死锁经 routing 诊断转 FAILED 写结构化 error_message，execution_suspended hook 打通；删除 5s 轮询分支与旧死锁分支。全量 tests/workflows/ 412 例零回归。**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-13
- **Tasks:** 3
- **Files modified/created:** 4（1 新建 + 3 修改）

## Accomplishments
- 新增 `_finalize_run_state` 单一收口方法：按 `挂起 > 死锁 > 失败 > 完成` 优先级判定并执行对应 `amark_* + hook`；主循环三处出口（正常退出、stop_before 提前退出、无 ready 分支）统一委托，杜绝双出口语义漂移（Pitfall 5）。
- waiting_event 与 waiting_approval 统一进 `waiting_nodes_mem: set[str]`，**都不加回 pending**：消灭 §1.4 waiting_approval 热循环（审批推进完全依赖 approve_node 回调闭环）；末端 waiting_event 不再被误判 COMPLETED。
- 删除 5s 轮询分支（`all_blocked` DB 遍历 + `asyncio.sleep(5)` + 单键刷新缺陷）——挂起后线程立即退出，根除"永久 running 僵尸线程"DoS 面（T-18-04）。
- 旧死锁分支（只列节点名字）替换为 `routing.diagnose_deadlock` + 结构化 `amark_failed`：error_message = 中文一句话 + `\n` + `json.dumps(diag, ensure_ascii=False)`，末行可独立 `json.loads`（Phase 21 直接消费），仅含拓扑元数据零输出值泄露（T-18-03）。
- 新增 `test_engine_waiting.py`（5 例）+ `test_engine_deadlock.py::TestDeadlockIntegration`（3 例）+ 改写 `test_engine.py` 2 例；全量 `tests/workflows/` 412 例全绿。

## Task Commits

每个任务原子提交（顺序执行，正常 git hooks，无 --no-verify）：

1. **Task 1: 收口函数 + 删轮询 + 热循环修复 + waiting 集成测试** — `b1ed4ce25` (feat)
2. **Task 2: 死锁结构化诊断集成测试（ENG-04 主循环侧）** — `75651db89` (test)
3. **Task 3: 既有审批/取消用例对齐挂起语义** — `04fc29a5f` (test)

## _finalize_run_state 最终签名（18-04 重入路径消费）

```python
async def _finalize_run_state(
    self,
    execution: WorkflowExecution,
    dag: DAG,
    *,
    pending: set[str],
    waiting: set[str],
    failed: set[str],
    completed: set[str],
    node_statuses: dict[str, str],
    node_handles: dict[str, str],
    node_outputs: dict[str, dict],
) -> None:
    ...
```

判定优先级（顺序敏感，禁调换）：
- a. `waiting` 非空 → `amark_suspended()` + `execution_suspended` hook + structlog `workflow_suspended`；
- b. `waiting` 空且 `pending` 非空 → `diagnose_deadlock(dag, RoutingState(node_statuses, node_handles), pending)`；返回 dict 时拼 `f"工作流死锁：{len(pending)} 个节点无法调度\n{json.dumps(diag, ensure_ascii=False)}"` 写 `amark_failed` + `execution_failed` hook；返回 None 兜底仅写中文一句话；
- c. `failed` 非空 → `amark_failed(f"失败节点: {len(failed)}")` + `execution_failed` hook；
- d. 否则 → 收集终端节点（无 outgoing）输出 + `amark_completed` + `execution_completed` hook。

## 删除/替换代码段范围（改造前 scheduler.py 行号）

| 段 | 改造前位置 | 处置 |
|----|-----------|------|
| stop_before 提前退出（amark_completed 不查 waiting） | :648-660 | 替换为 `_finalize_run_state` 调用 |
| 无 ready 分支：waiting DB 遍历 + `all_blocked` + `asyncio.sleep(5)` 轮询 + 单键刷新缺陷 | :662-717 | **整段删除**，替换为单次 `_finalize_run_state` + return |
| 旧死锁分支（只列节点名字的 amark_failed） | :719-737 | 合并进上方收口（routing.diagnose_deadlock 结构化） |
| 并行结果 waiting_approval（加回 pending）/ waiting_event | :904-914 | 统一进 waiting 集合、不加回 pending |
| 主循环正常出口（failed/完成二分支 amark_*） | :924-938 | 替换为 `_finalize_run_state` 调用 |
| 调试串行路径 waiting 分支 | （原缺失） | 新增 waiting_approval/waiting_event → waiting 集合（Rule 2） |

验证锚点：`rg "asyncio.sleep\(5\)" scheduler.py` 零命中；`rg "_finalize_run_state" scheduler.py` 4 处命中（定义 + 三出口调用）。

## A3 timeout 兜底核查结论

**wait 节点超时与主循环线程存活无任何耦合——删除轮询零影响。** 核查 `server/workflows/management/commands/check_timeouts.py`：wait_event/wait_approval 的超时由外部定时命令 `check_timeouts`（推荐 60s 间隔）扫描 `WorkflowEventSubscription.timeout_at` 兜底处理（fail/skip/retry 三种 `timeout_action`），完全独立于工作流执行线程。旧 5s 轮询从不参与超时判定（它只刷新已就绪/已完成节点状态）。故挂起后线程立即退出不会让任何 wait 节点"永远等待"——超时由独立调度器闭环。**无行为退化，CONTEXT 边界内无需扩大修复。**

## 既有测试改写清单

| 用例 | 改写内容 |
|------|---------|
| `test_engine.py::test_approval_node_waits` | 删除 `waiting_count >= 0` 恒真断言；改 `run_sync=True` + 断言 `execution.status == SUSPENDED` 且审批 NE 状态为 `WAITING_APPROVAL` |
| `test_engine.py::test_cancel_running_execution` → `test_cancel_suspended_execution` | 旧语义依赖执行线程存活轮询；改为 `run_sync` 下审批即 SUSPENDED，再 `cancel_execution` 断言 `CANCELLED`（挂起后取消生效） |

注：上述两用例在新语义下即便不改写也恰好通过，但按计划要求删除恒真断言、用 run_sync 锁定真实 SUSPENDED 语义（禁止恒真旁路）。其余 410 例无需改写，新挂起/死锁语义与既有用例完全兼容。

## Decisions Made
- **调试串行路径补 waiting 收口（Rule 2）**：原 debug 串行路径无 waiting_approval/waiting_event 分支，挂起节点会落入 `else → failed` 误判。补充 `elif result.status in (waiting_approval, waiting_event) → waiting 集合 + 不加回 pending`，与并行路径语义对齐。
- **死锁 diagnose 返回 None 的兜底**：`diagnose_deadlock` 三要素未齐（如状态不一致异常态）返回 None 时仍写中文一句话 `amark_failed`，绝不抛出（引擎"结果不外抛"约定）。
- **既有用例照计划改写**：即便原样通过也删除恒真断言并改 run_sync，锁定 ENG-01 真实语义，避免"恒真断言伪绿"。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 缺失关键功能] 调试串行路径补 waiting 节点收口分支**
- **Found during:** Task 1（统一 waiting 集合维护时）
- **Issue:** debug 串行路径结果处理无 waiting_approval/waiting_event 分支，挂起节点被 `else` 误判 failed
- **Fix:** 新增 `elif result.status in (waiting_approval, waiting_event)` → 进 waiting 集合、不加回 pending（pending 已在 :749 discard）
- **Files modified:** server/workflows/engine/scheduler.py
- **Commit:** `b1ed4ce25`

**Total deviations:** 1 缺失功能补齐（Rule 2），0 功能偏差、0 架构变更。

## Issues Encountered
- `uv run` 偶发重排 `server/uv.lock`：本计划零新依赖，每次提交前 `git checkout -- uv.lock` 还原，最终 uv.lock 无 diff。

## Threat Surface
- **T-18-03（死锁诊断信息泄露）已缓解**：error_message 仅由 `diagnose_deadlock` 输出拼装（18-01 已保证签名不接收 node_outputs），Task 2 Test 2 哨兵串 `SECRET_OUTPUT_VALUE` 端到端断言不入 error_message。
- **T-18-04（永久 running 僵尸线程 DoS）已缓解**：删除 5s 轮询后 waiting 即挂起返回，主循环线程不再常驻；Test 2 断言 run_sync 耗时 < 3s 反证无轮询延时。
- 零新增网络端点/鉴权路径/schema 变更（引擎内部状态机 + 测试）。挂起 WS 广播复用既有 `WebSocketBroadcastHook` 形状 `{event, execution_id, status}`，无新增字段。

## Next Phase Readiness
- 18-04（回调续跑）可直接复用 `_finalize_run_state` 做恢复后的终局判定（恢复续跑后残留纯死锁经重入路径暴露并由该方法收口）；waiting 集合语义与 routing 状态映射均已就位。
- waiting 节点超时由 `check_timeouts` 外部命令兜底（与主循环解耦），18-04 重入续跑无需考虑超时线程存活。

## Self-Check: PASSED

- 1 新建 + 3 修改文件 + SUMMARY.md 均存在于磁盘
- 三个任务提交 `b1ed4ce25` / `75651db89` / `04fc29a5f` 均可达
- `tests/workflows/` 412 例全绿（含 8 新增：waiting 5 + deadlock integration 3）；scheduler.py / 三个测试文件 ruff format + check 通过；`asyncio.sleep(5)` 零命中、`_finalize_run_state` 4 处命中、`waiting_count >= 0` 零命中；`server/uv.lock` 无 diff

---
*Phase: 18-engine*
*Completed: 2026-06-13*
