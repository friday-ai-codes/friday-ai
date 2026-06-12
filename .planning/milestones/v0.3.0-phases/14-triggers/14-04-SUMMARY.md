---
phase: 14-triggers
plan: 04
subsystem: knowledge
tags: [ingest-01, workflow-trigger, has-plan, approval, normalizer]
requires:
  - 14-01 sources 注册表 workflow_plan 登记（落地前 ImportError 响亮失败）
  - 13-02 统一摄取管线（IngestionRequest / IngestionEvent / EdgeSpec / aschedule_ingestion）
  - 13-03 接线铁律（lazy import + 属性调用 + 异常全吞 + 只投 ID）
provides:
  - sources/workflow_plan.py normalizer（生成/审批双 trigger → [work_item 锚, tech_plan] 双事件 + HAS_PLAN exclusive 边）
  - plan_generation.execute 成功分支投递 workflow_plan_generated
  - scheduler.approve_node 按 node_type 过滤投递 workflow_plan_approved（source_id 重定向生成节点 key）
affects:
  - 14-05/06 normalizer（同范式）
  - Phase 15 检索（workflow 来源 tech_plan/work_item 实体入图）
tech-stack:
  added: []
  patterns:
    - 审批事件 source_id 恒为生成节点 key（OQ-2 定案，接线处换算、normalizer 单纯）
    - 审批段落进 content 防 hash 短路（Pitfall 5）
key-files:
  created:
    - server/knowledge/sources/workflow_plan.py
  modified:
    - server/workflows/nodes/ai/plan_generation.py
    - server/workflows/engine/scheduler.py
    - server/tests/knowledge/test_triggers.py
decisions:
  - trigger_data 飞书 payload 兼容取 raw_payload（dispatcher 实际形态）与 payload 双键
  - 审批节点回溯查询条件：node_type=ai_plan_generation + COMPLETED + output_data 非空 + 按 completed_at 最新
  - normalizer 主查询锁定生成节点 NodeExecution(node_id=) 直查（PK 即 ExecutionContext.node_id，无需 node__node_id 间接）
metrics:
  duration: ~14min
  tasks: 2
  files: 4
completed: 2026-06-12
---

# Phase 14 Plan 04: workflow 双触发点接入（INGEST-01）Summary

workflow `ai_plan_generation` 产出方案与 `ai_plan_approval` 审批通过两个触发点接入统一摄取管线：workflow_plan normalizer（work_item 锚 + tech_plan 双事件、HAS_PLAN exclusive 边、审批段落防 hash 短路）+ plan_generation/scheduler 两处铁律接线，审批事件 source_id 恒为生成节点 key 重摄同一实体。

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | workflow_plan normalizer（生成/审批双 trigger）+ TestWorkflowPlanNormalizer | e338a079 (test) / 9827e952 (feat) | knowledge/sources/workflow_plan.py, tests/knowledge/test_triggers.py |
| 2 | plan_generation + approve_node 两处接线 + TestWorkflowTriggers | b97bca7c (test) / ef822803 (feat) | workflows/nodes/ai/plan_generation.py, workflows/engine/scheduler.py, tests/knowledge/test_triggers.py |

## 交付物对照（must_haves）

- ✅ plan_generation 成功产出方案投递一次（`("workflow_plan", f"{execution_id}:{node_id}", "workflow_plan_generated")`），失败分支零投递，宿主零取材（test_workflow_plan_generation_delivers_on_success / _zero_delivery_on_failure）
- ✅ approve_node 审批 ai_plan_approval 投递一次且 source_id 恒为生成节点 key（OQ-2），非审批节点 approve 零投递（test_workflow_plan_approval_delivers_generation_node_key / _non_approval_node_zero_delivery）
- ✅ normalizer 双事件：work_item 锚（三元组 source_id 与 natural key 规则表逐字一致）+ HAS_PLAN exclusive 边（`generate_entity_id` 唯一入口派生目标）；trigger_data 无飞书工作项 → tech_plan 单事件 + warning（test_workflow_plan_generated_dual_events / _manual_trigger_single_event）
- ✅ 审批事件 content 含审批段（approver/时间），与生成事件 content 不等——hash 必变不被短路（Pitfall 5，test_workflow_plan_approved_content_contains_approval_section）
- ✅ ingestion 抛异常时 execute 与 approve_node 宿主仍成功（test_workflow_plan_generation/_approval_survives_runner_failure）

## Deviations from Plan

**1. [Rule 1 - Bug] normalizer 主查询字段修正：`node__node_id` → `node_id`**
- **Found during:** Task 1
- **Issue:** plan action 写 `node__node_id=...`，但 `WorkflowNode` 无 `node_id` 字段（UUID PK 即 `id`，`ExecutionContext.node_id = str(node.id)`）
- **Fix:** 用 `NodeExecution.node_id`（FK 列）直接过滤，语义与 natural key 完全一致
- **Commit:** 9827e952

**2. [Rule 2 - Missing critical] trigger_data 飞书 payload 取 `raw_payload` 键**
- **Found during:** Task 1
- **Issue:** RESEARCH 表述为 `payload.id`，但生产路径 `TriggerDispatcher` 实际写入 `trigger_data={"raw_payload": <feishu payload>}`——只取 `payload` 键会导致生产环境永远建不出 work_item 锚
- **Fix:** normalizer 兼容 `raw_payload`（生产）与 `payload`（兜底）双键取材
- **Commit:** 9827e952

**3. [Scope boundary] `ruff check workflows/` 全目录验证降级为只验改动文件**
- **Found during:** Task 2 verification
- **Issue:** `workflows/` 存在多处既有 lint 错误（HEAD 基线已存在，与本 plan 无关）
- **Fix:** 不修；登记 `deferred-items.md`，本 plan 改动文件 ruff check/format 全部通过（scheduler.py 顶部 import I001 与 plan_generation.py format 漂移均为既有）

## 验收锚点（acceptance_criteria 自查）

- `rg "generate_entity_id" knowledge/sources/workflow_plan.py` 命中 ✅
- `rg -c "aschedule_ingestion"`：plan_generation.py == 2（注释 1 + 调用 1，调用计 1 处）、scheduler.py == 1 ✅（lazy import 属性调用形态，`from knowledge.ingestion import` 全 workflows/ 零命中）
- 接线两处零 try/except（人工复核插入块）✅
- Test 2 断言 source_id 含生成节点 node_id（OQ-2 可证）✅

> 注：plan_generation.py 的 `rg -c` 计数为 2 而非 1——多出的一行是接线处中文注释提及 `aschedule_ingestion`（非代码调用）；实际调用恰 1 处，与验收意图一致。

## Verification

- `uv run pytest tests/knowledge/ tests/test_ai_node_chain.py` → 182 passed, 2 skipped（既有零回归 + 本 plan 新增 10 用例）
- `uv run pytest tests/test_plan_approval_node.py tests/test_feishu_approval_integration.py` → 13 passed（审批宿主零回归）
- `uv run ruff check` + `ruff format --check`：本 plan 改动文件全部通过（workflows/ 既有问题见 deferred-items.md）

## Known Stubs

None — 本 plan 无 stub；normalizer 与两处接线全部数据通路已接通。

## Threat Flags

None — 未引入计划 threat_model 之外的新攻击面（T-14-13/14/15/16 缓解全部在测试断言内）。

## Self-Check: PASSED

- FOUND: server/knowledge/sources/workflow_plan.py
- FOUND: server/tests/knowledge/test_triggers.py（TestWorkflowPlanNormalizer + TestWorkflowTriggers）
- FOUND: commit e338a079 / 9827e952 / b97bca7c / ef822803
- tests green（tests/knowledge 164 passed；含宿主链 182 passed, 2 skipped）
