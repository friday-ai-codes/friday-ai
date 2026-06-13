---
phase: 18-engine
plan: 02
subsystem: api
tags: [workflow-engine, routing, scheduler, branch, skipped, target-handle, pytest]

# Dependency graph
requires:
  - phase: 18-engine
    plan: 01
    provides: routing 五纯函数（evaluate_node_readiness/select_successors/compute_skippable/diagnose_deadlock/collect_inputs）+ DAGNode.incoming_edges + engine barrel 导出
provides:
  - "调度主循环（_run_execution）就绪/级联/后继/输入判定接入 routing 纯函数——消除第二套 if-else 路由实现"
  - "node_statuses / node_handles 内存状态映射（18-03/04 消费）"
  - "conftest 引擎集成测试基建：五个可控测试节点 + engine/engine_test_nodes 夹具 + branch/waiting/waiting_terminal 工作流工厂（18-03/04/05 消费）"
  - "条件分支真路由 + 未选中支级联 SKIPPED + skipped 参与完成判定的端到端集成测试"
  - "target_handle 归集经真实调度端到端验证（端口键整包 + 扁平保底并存）"
affects: [18-03, 18-04, 18-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "主循环路由唯一语义源：每轮构造 RoutingState(statuses=node_statuses, handles=node_handles)，先 compute_skippable 级联 skip，再 evaluate_node_readiness 选 ready"
    - "next_handle 单一来源：热路径只从内存 result['handle'] 写 node_handles（仅非 default），封堵 Pitfall 2 双来源不对称"
    - "续跑预填充节点视为 COMPLETED 并从 output_data['_next_handle'] 还原 handle，保留旧'completed/skipped 上游放行下游'语义，避免新 skip_unselected 级联误伤"

key-files:
  created: []
  modified:
    - server/tests/workflows/conftest.py
    - server/workflows/engine/scheduler.py
    - server/tests/workflows/test_engine_routing.py
    - server/tests/workflows/test_engine_inputs.py

key-decisions:
  - "node_statuses 同时在并行路径与调试串行路径写入——否则 debug 模式工作流在新就绪判定下会因状态缺失死锁（Rule 3 阻塞修复）"
  - "续跑/恢复预填充节点 routing 状态记为 COMPLETED（非 SKIPPED），并还原 _next_handle，零回归保留 resume/continue 行为（resume 路由完备化归 18-04）"
  - "waiting_approval/waiting_event 结果写 node_statuses=WAITING，但挂起/轮询/重入分支本任务不动（归 18-03）"

patterns-established:
  - "主循环就绪批：compute_skippable(级联 skip) → evaluate_node_readiness(选 ready) → 并行 gather → 结果回写 node_statuses/node_handles"
  - "引擎集成测试范式：@pytest.mark.asyncio + django_db(transaction=True) + run_sync + 按 node__name 查 NodeExecution 断言"

requirements-completed: [ENG-02, ENG-05]

# Metrics
duration: ~35min
completed: 2026-06-13
---

# Phase 18 Plan 02: 主循环路由接入 + 引擎集成测试基建 Summary

**调度主循环就绪/级联/后继/输入判定全部委托 18-01 routing 纯函数，条件分支真路由（仅选中支执行、未选中支级联 SKIPPED 且参与完成判定），target_handle 归集经端到端集成测试闭环；建立全阶段共享的 conftest 引擎测试基建。**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-13
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `_run_execution` 主循环路由改造：删除手写 `all_deps_completed` ANY/ALL 判定，改为每轮 `compute_skippable` 级联标记可 skip 节点（未选中/前置失败）+ `evaluate_node_readiness` 选 ready；后继与级联语义全部走 routing 纯函数（scheduler 内不再有第二套路由实现）。
- 新增 `node_statuses: dict[str, str]` / `node_handles: dict[str, str]` 状态映射，在并行路径、调试串行路径、续跑预填充、stop_before 跳过四处一致维护（18-03/04 消费）。
- `_collect_inputs` 函数体改为委托 `routing.collect_inputs(dag, str(dag_node.id), node_outputs)`，调用点零改动，删除原扁平合并循环。
- conftest 引擎测试基建：五个可控测试节点（`BranchNode`/`WaitEventNode`/`WaitApprovalNode`/`EchoInputsNode`/`EchoTriggerDataNode`）+ `engine`/`engine_project`/`engine_test_nodes` 具名夹具（非 autouse）+ `branch_workflow`/`waiting_workflow`/`waiting_terminal_workflow` 工作流工厂。
- 集成测试：`TestBranchRoutingIntegration`（真/假支选中 + 对称 + skipped 参与完成判定 + 无匹配 handle 全级联 skip）、`TestTargetHandleIntegration`（端口键整包 + 扁平保底并存 + default 无端口键）。
- 全量 `tests/workflows/` 404 例全绿（397 基线 + 7 新增），零回归。

## Task Commits

每个任务原子提交（顺序执行，正常 git hooks，无 --no-verify）：

1. **Task 1: conftest 引擎集成测试基建** — `405f13be3` (test)
2. **Task 2: 主循环就绪/级联/后继/输入接入 routing 纯函数** — `71bac4a25` (feat)
3. **Task 3: target_handle 端到端集成测试** — `0c8454b1b` (test)

## node_statuses / node_handles 维护点（18-03/04 消费）

`_run_execution`（`server/workflows/engine/scheduler.py`）内：

| 位置 | 写入 |
|------|------|
| 续跑预填充（initial_outputs / skipped_ne_list） | `node_statuses[id]=COMPLETED`，`node_handles[id]=output_data["_next_handle"]`（非 default 时） |
| 级联 skip（compute_skippable 结果） | `node_statuses[id]=SKIPPED` |
| stop_before 下游跳过 | `node_statuses[id]=SKIPPED` |
| 并行结果 completed | `node_statuses[id]=COMPLETED`，`node_handles[id]=result["handle"]`（非 default 时） |
| 并行结果 tolerated | `node_statuses[id]=TOLERATED` |
| 并行结果 failed / exception / 其它 | `node_statuses[id]=FAILED` |
| 并行结果 waiting_approval/event | `node_statuses[id]=WAITING`（挂起/轮询逻辑归 18-03 收口） |
| 调试串行路径 completed/skip/tolerated/failed | 同上各态对应写入 |

每轮循环顶部构造 `RoutingState(statuses=node_statuses, handles=node_handles)`——`statuses` 即 `node_statuses` 本体（同一 dict 引用），故级联 skip 写入后同轮就绪判定即时可见。

## conftest 测试基建清单（18-03/05 消费）

测试节点（`server/tests/workflows/conftest.py`，均 `BaseNode` 子类）：
- `BranchNode`（`test_branch`）：返回 `next_handle=cls._next_handle`（类属性旋钮，默认 "true"），output `{"branch": _next_handle}`
- `WaitEventNode`（`test_wait_event`）：返回 `waiting_event`，类属性 `_exec_count` 计数
- `WaitApprovalNode`（`test_wait_approval`）：返回 `waiting_approval`，类属性 `_exec_count` 计数（18-03 热循环断言用）
- `EchoInputsNode`（`test_echo_inputs`）：output `{"echoed_inputs": dict(context.input_data)}`
- `EchoTriggerDataNode`（`test_echo_trigger`）：output `{"echoed_trigger": dict(context.trigger_data)}`（18-05 消费）

夹具：`engine`（WorkflowEngine 实例）、`engine_project`、`engine_test_nodes`（注册/注销五节点 + 复位旋钮/计数器，**非 autouse**）、`branch_workflow`、`waiting_workflow`、`waiting_terminal_workflow`。

## Pitfall 9 内置模板 condition 用法检查结论

`server/workflows/templates/*.json` 三个内置模板（`code_generation`/`feishu_full_pipeline`/`code_review_pipeline`）中**无 `condition` 节点被当 fan-out 使用**。唯一的分支语义来自 `ai_plan_approval` 的 `approved`/`rejected` 句柄（天然互斥分支，正是新路由要支持的语义），不存在"两分支都期望执行"的存量用法。**结论：无需迁移说明，新就绪/级联语义与现有内置模板完全兼容。**

## 旧语义测试改写清单

**无。** 全量 397 基线用例在新路由语义下全部直接通过，未发现依赖"分支两边都跑"旧语义的失败用例（PATTERNS 预警的 `test_engine.py::test_approval_node_waits` 断言 `waiting_count >= 0` 恒真、`test_cancel_running_execution` 不依赖分支语义，均无需改写）。

## Decisions Made
- **node_statuses 双路径写入**：并行路径与调试串行路径都写 node_statuses，否则 debug 模式工作流在新就绪判定下因前置状态缺失而误判 blocked → 死锁（Rule 3 阻塞修复）。
- **续跑预填充记为 COMPLETED 而非 SKIPPED**：旧主循环 `dep in completed or dep in skipped → 放行下游`，无 skip_unselected 概念。续跑节点 DB 为复用 initial_outputs 机制被标 SKIPPED，但对 routing 记 COMPLETED（已解析且选中）并还原 `_next_handle`，零回归保留 resume/continue 行为；resume 路由完备化归 18-04。
- **waiting 不收口**：waiting_approval/event 写 node_statuses=WAITING，但挂起判定、5s 轮询、重入续跑分支本任务一律不动（禁改项，归 18-03）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 阻塞] 调试串行路径同步写 node_statuses/node_handles**
- **Found during:** Task 2（就绪判定改走 routing 后）
- **Issue:** 计划主述并行路径回写；但 `if execution.is_debug` 串行路径不写 node_statuses 会令 debug 工作流在新就绪判定下死锁
- **Fix:** 在调试串行路径的 completed/skip/tolerated/failed 各分支同步写 node_statuses（completed 另写 node_handles）
- **Files modified:** server/workflows/engine/scheduler.py
- **Commit:** `71bac4a25`

**2. [Rule 3 - 阻塞] 续跑预填充节点 routing 状态记 COMPLETED 并还原 handle**
- **Found during:** Task 2（initial_outputs / skipped_ne_list 预填充段）
- **Issue:** 若按 DB 状态记 SKIPPED，新 skip_unselected 级联会把续跑节点下游误判未选中而级联 skip
- **Fix:** 预填充节点 node_statuses 记 COMPLETED，并从 output_data["_next_handle"] 还原 node_handles
- **Files modified:** server/workflows/engine/scheduler.py
- **Commit:** `71bac4a25`

**Total deviations:** 2 阻塞修复（Rule 3），0 功能偏差、0 架构变更。

## Deferred Issues

- **预存 ruff lint（范围外，未触碰）**：`uv run ruff check workflows/ tests/workflows/` 报 22 处错误，全部位于本计划未修改的文件（`tests/workflows/test_alert_rules.py`、`test_code_node.py`、`test_foreach_node.py`、`test_template_loader.py`）。按 SCOPE BOUNDARY 不予修复。本计划修改的 4 个文件 `ruff format --check` 与 `ruff check` 全绿。

## Issues Encountered
- `uv run` 偶发重排 `server/uv.lock`：本计划零新依赖，每次提交前 `git checkout -- server/uv.lock` 还原，最终 uv.lock 无 diff。

## Threat Surface
- T-18-02（compute_skippable fixpoint 级联 DoS）已缓解：18-01 纯函数为有界迭代（pending 单调缩小），Test 4（`_next_handle="nonexistent_handle"` 无匹配边）证明两支 + Join 全级联 SKIPPED、执行 COMPLETED，无无限循环/无限 running 残留。
- 零新增网络端点/鉴权路径/schema 变更（引擎内部数据流 + 测试）。

## Next Phase Readiness
- 18-03（waiting 挂起/热循环收口）可直接消费 conftest 的 `waiting_workflow`/`waiting_terminal_workflow`/`WaitApprovalNode._exec_count`，并复用 node_statuses=WAITING 标记。
- 18-04（回调续跑）可复用同一套 routing 状态映射与 collect_inputs 委托；resume 路由完备化（handle 还原）在本计划已埋点（预填充段）。
- 18-05（trigger_data）可直接消费 `EchoTriggerDataNode`。

## Self-Check: PASSED

- 4 个修改文件 + SUMMARY.md 均存在于磁盘
- 三个任务提交 `405f13be3` / `71bac4a25` / `0c8454b1b` 均可达
- `tests/workflows/` 404 例全绿（含 7 新增）；4 个改动文件 ruff format + check 通过；`server/uv.lock` 无 diff

---
*Phase: 18-engine*
*Completed: 2026-06-13*
