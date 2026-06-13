---
phase: 18-engine
plan: 05
subsystem: api
tags: [workflow-engine, trigger-data, dispatcher, resume, template-resolver, pytest]

# Dependency graph
requires:
  - phase: 18-engine
    plan: 02
    provides: conftest EchoTriggerDataNode + node_statuses；_collect_inputs 委托 routing
  - phase: 18-engine
    plan: 04
    provides: 回调续跑收敛单点（coding_callback 手工 context 已删，注入点收敛到 _execute_node）
provides:
  - "dispatcher 统一写入 trigger_data.source 键（= context.trigger_type 透传）"
  - "_execute_node 注入 execution.trigger_data → {{trigger.source}}/{{trigger.raw_payload.*}} 真实可解析（ENG-03 唯一读取侧缺口闭环）"
  - "resume_from_node 继承原 trigger_data（source/raw_payload 不丢）+ 附加 resume metadata"
  - "trigger_data 形状定稿：{source, raw_payload, [metadata]}，无 payload 别名键（Phase 21 触发模型消费）"
affects: [21]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "写入侧服务端权威：source 由 dispatcher 按 trigger_type 写入 trigger_data 顶层，raw_payload 内同名字段不覆盖（形状分层防伪造 T-18-08）"
    - "读取侧单点注入：_execute_node 构造 ExecutionContext 时 trigger_data=execution.trigger_data or {}，resolver/get_trigger_data 零改动（不扩大严格化，复用 Phase 17 宽松路径）"
    - "resume 继承用 dict 展开：{**(original.trigger_data or {}), 'metadata': {...}}，metadata 键追加/覆盖"

key-files:
  created:
    - server/tests/workflows/test_engine_trigger_data.py
  modified:
    - server/workflows/triggers/dispatcher.py
    - server/workflows/engine/scheduler.py

key-decisions:
  - "source 直接透传 context.trigger_type（注册名枚举 manual/feishu/webhook；api 走 views 非 dispatcher 路径），与 CONTEXT 锁定的 {source, ...payload} 语义一致"
  - "resolver 零改动：trigger 前缀宽松下钻为 Phase 17 已定稿，本计划只补注入侧；空 trigger_data 下 {{trigger.*}} 维持现状（缺失转空串）"
  - "形状不新增 payload 别名键（Pitfall 8 characterization）——保 retry 读 trigger_data['raw_payload']、normalizer 双键、coding 节点 payload miss 降级行为零回归"

patterns-established:
  - "trigger_data 全链路：dispatcher 写 {source, raw_payload} → _execute_node 注入 → template_resolver trigger 前缀宽松解析"
  - "trigger_data 集成测试范式：dispatch 路径断言写入形状 + start_execution(run_sync) 断言读取解析"

requirements-completed: [ENG-03]

# Metrics
duration: ~25min
completed: 2026-06-13
---

# Phase 18 Plan 05: 触发数据全链路（写入 source + 读取注入 + resume 继承）Summary

**打通 trigger_data 全链路：dispatcher 统一补 `source` 键、`_execute_node` 注入 `execution.trigger_data`（填平真实执行中 `{{trigger.*}}` 永远解析空 dict 的根因）、`resume_from_node` 继承原 trigger_data；template_resolver 零改动，形状无 payload 别名键。ENG-03 闭环，Phase 18 五个 Wave 0 测试缺口清零。**

## 执行方式

> **本计划由 orchestrator inline 执行**（非 gsd-executor 子代理）——派发子代理时遭遇 Cursor 账单错误（unpaid invoice）导致子代理无法启动，按 execute-phase.md 的 sequential inline fallback 由编排层亲自落地。改动小、纯函数路径清晰，inline 执行风险可控。

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-13
- **Tasks:** 2（写入侧 / 读取侧）
- **Files modified:** 2 源 + 1 新测试

## Accomplishments
- **写入侧（dispatcher.py）**：`start_execution(trigger_data=...)` 由 `{"raw_payload": ...}` 改为 `{"source": context.trigger_type, "raw_payload": context.raw_payload}`。source 服务端权威写入，raw_payload 内同名字段不会覆盖顶层 source。
- **写入侧（scheduler.resume_from_node）**：`trigger_data={"metadata": {...}}` 改为 `{**(original_execution.trigger_data or {}), "metadata": {...}}`——继承原 source/raw_payload，附加 resumed_from/failed_node_id。
- **读取侧（scheduler._execute_node）**：ExecutionContext 构造追加 `trigger_data=execution.trigger_data or {}`——这是真实调度中 `{{trigger.*}}` 解析的唯一缺口（此前永远空 dict）。resolver 与 `get_trigger_data` 零改动。
- **测试（test_engine_trigger_data.py，7 例）**：写入侧 3 例（dispatcher source 键 / 无 payload 别名 / resume 继承）+ 读取侧 4 例（注入端到端 / `{{trigger.source}}`+`{{trigger.raw_payload.k}}` 模板解析 / dispatcher 全链路合龙 / 空 trigger_data 宽松语义）。
- 全量 `tests/workflows/` 424 例零回归；五个 Wave 0 测试文件（routing/waiting/trigger_data/deadlock/inputs）合计 56 例全绿。

## Task Commits

1. **写入侧 + 读取侧源改动** — `03e9a46fc` (feat)
2. **trigger_data 全链路集成测试** — `ddca3455d` (test)

> 注：源改动（dispatcher + scheduler 共 3 处）合并为单一 feat 提交（同属 ENG-03 一处语义、互相耦合），测试单独 test 提交。

## VALIDATION Per-Task Map 勾销（18-VALIDATION.md）

| Req | 测试文件 | 状态 |
|-----|----------|------|
| ENG-01 | test_engine_waiting.py | ✅ green（18-03/04） |
| ENG-02 | test_engine_routing.py | ✅ green（18-01/02） |
| ENG-03 | test_engine_trigger_data.py | ✅ green（本计划，7 例） |
| ENG-04 | test_engine_deadlock.py | ✅ green（18-01/03） |
| ENG-05 | test_engine_inputs.py | ✅ green（18-01/02） |

五个 Wave 0 缺口文件全部齐备、合计 56 例全绿。

## trigger_type 枚举透传映射

- 注册的 dispatcher 触发处理器：`manual`（ManualHandler）、`feishu`（FeishuHandler）、`webhook`（WebhookHandler）。source 直接透传该注册名。
- `api`/`resume` 触发不经 dispatcher：API retry 走 `workflows/api/views.py`，resume 走 `resume_from_node`（继承原 source）。CONTEXT 锁定的"manual/api"语义在 dispatcher 侧由 manual 覆盖，api 侧由 views/resume 路径承载，无遗漏。

## Decisions Made
- **source 透传 trigger_type 而非硬编码**：保持与注册名单一事实源一致，未来新增触发器自动带正确 source。
- **resolver 零改动**：trigger 宽松下钻是 Phase 17 定稿边界，本计划严守"只补注入、不扩严格化"。
- **形状不加 payload 别名**：严守 Pitfall 8 characterization，零回归保护 retry/normalizer/coding 降级三处存量消费方。

## Deviations from Plan
- **执行主体偏差**：计划假定 gsd-executor 子代理执行；实际因账单错误由 orchestrator inline 落地（见"执行方式"）。任务内容、提交粒度、验证门禁均按计划执行，无范围变化。
- **源改动合并为单一 feat 提交**：计划 Task 1（写入侧）/Task 2（读取侧）分述，但三处源改动同属 ENG-03 单一语义且互相耦合，合并提交更内聚；测试仍独立提交。
- **无功能/架构偏差。**

## Open Question（留待 Phase 21）
- **OQ-1（payload 别名）**：是否在 trigger_data 顶层补 `payload` 作为 `raw_payload` 别名以简化前端引用——本计划严守现状不加（保兼容）。Phase 21 触发模型若需统一前端引用路径，再行决策。

## Issues Encountered
- `uv run` 偶发重排 `server/uv.lock`：本计划零新依赖，每次提交后 `git checkout -- server/uv.lock` 还原，最终无 diff。
- ruff format 将注入行因长中文注释折成两行（formatter 自主选择），已接受。

## Threat Surface
- T-18-07（trigger_data 注入→模板执行）已缓解：resolver 为纯取值替换（无 eval/exec），本计划不改 resolver、不新增对 trigger_data 的代码执行路径；Test 4 锁定空值宽松语义。
- T-18-08（source 伪造）已缓解：source 由 dispatcher 服务端按 trigger_type 写入顶层，raw_payload 内同名字段不覆盖；Test 1 断言顶层 source 为服务端值。
- 零新增网络端点/鉴权路径/schema 变更。

## Self-Check: PASSED
- 1 新测试 + 2 源文件 + SUMMARY.md 均在磁盘
- 提交 `03e9a46fc` / `ddca3455d` 可达
- `tests/workflows/` 424 例全绿；五 Wave 0 文件 56 例全绿；resolver `git diff` 为空；改动文件 ruff format+check 通过；`server/uv.lock` 无 diff

---
*Phase: 18-engine*
*Completed: 2026-06-13*
