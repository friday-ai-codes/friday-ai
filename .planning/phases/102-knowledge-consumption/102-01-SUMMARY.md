---
phase: 102-knowledge-consumption
plan: 01
subsystem: process-runtime-recall
tags: [recall, knowledge, retrieval-trace, observability, know-04]
requires:
  - "Phase 100：EntityKind.LEARNING_CASE 存在、vector_recall._DEMAND_KINDS 已含 LEARNING_CASE、include_document_kind flag 可用"
provides:
  - "编排召回 kinds 可配置（PROCESS_RECALL_ENTITY_KINDS，env 可覆盖，默认 5 kinds 含 document/learning_case）"
  - "每 kind 限额截断守 token 预算（PROCESS_RECALL_KIND_LIMITS，单查后按 kind 截断）"
  - "召回埋点：RetrievalTrace（source=process_recall）+ process_recall_completed 结构化事件（best-effort）"
affects:
  - "方案编排 recalling 阶段：召回面扩为 5 kinds，recall_context 可含 document/learning_case 命中"
tech-stack:
  added: []
  patterns:
    - "settings 运行时读取（recall() 调用时 getattr，非 import 快照）→ override_settings 可测、改 env 即生效"
    - "单查后按 kind 截断（非分 kind 多查）：单次 search_similar 全成本，score 同源 RRF 排序可比"
    - "观测 best-effort：埋点整段独立 try/except 吞异常，绝不反噬召回主流程"
key-files:
  created: []
  modified:
    - server/friday/settings.py
    - server/services/process_runtime/recall_adapter.py
    - server/tests/services/test_recall_adapter.py
decisions:
  - "Claude's Discretion 落定：单查后按 kind 截断——5 kinds 分查是 5 倍 embedding+Qdrant 成本且跨查 score 不可比；top_k 超采样 sum(limits)*2 给截断留余量"
  - "self.top_k 语义调整为总量上限兜底 max(top_k, sum(limits))，不破坏 entrypoint.py 无参构造"
  - "trace payload 不含召回正文/title 全文/query 原文（T-102-02 信息泄露 mitigate），session_id 可回查 decomposition"
  - "测试统一 autouse fixture mock interactions.ledger.arecord_retrieval_trace（延迟 import 在调用时解析，patch 源模块即生效）"
metrics:
  duration: "~5 分钟"
  completed: "2026-07-22"
---

# Phase 102 Plan 01: 编排召回扩容（KNOW-04）Summary

编排召回 kinds 从硬编码 3 类扩为 settings 可配置 5 类（+ document/learning_case 默认开、include_document_kind 动态传参），单查后按 kind 限额截断守 token 预算，并补齐 RetrievalTrace + process_recall_completed 埋点（best-effort 吞异常）。

## Tasks

| Task | 内容 | Commit |
| --- | --- | --- |
| 1 | settings 双配置项 + adapter 可配置 kinds 与每 kind 限额截断 | d4a0881d |
| 2 | 召回埋点：RetrievalTrace + 结构化事件（best-effort） | f4561acd |
| 3 | 测试更新：新默认集合 / 可配置 / 限额 / trace best-effort | 676012fb |

## 验证结果

- `uv run pytest tests/services/test_recall_adapter.py -v`：**10 passed**（≥10 达标）——新默认 5-kind 集合、settings 可配置、include_document_kind 动态传参、每 kind 限额截断 + score 降序、trace 写入断言、trace 失败不破坏召回；既有 4 个行为用例（fail-closed / 异常空召回 / repository_ids / actor 解析）逐字保留全绿。
- `uv run ruff check services/process_runtime/ friday/settings.py` + `ruff format --check recall_adapter.py`：干净。
- `rg -n "include_document_kind" recall_adapter.py`：命中（L112 动态传参 + docstring 说明）。
- 按 plan 修订注记执行：Task 1/2 阶段不以旧 3-kind 断言红作为失败依据（当时仅该两处红、行为用例全绿），完整 pytest verify 在 Task 3 测试改写完成后执行并全绿。

## Deviations from Plan

None - plan executed exactly as written.

（执行顺序说明：`plan_recall_search_failed` warning 补 category/component kv 按计划归属 Task 2 提交，Task 1 提交不含该改动，保持任务原子性。）

## Known Stubs

无——kinds/limits/埋点全部接真实链路，无占位数据。

## Threat Flags

无新增安全面。威胁登记项处置均落地：T-102-01（fail-closed 用例逐字保留）、T-102-02（payload 无正文/query）、T-102-03（限额 + sum(limits)*2 上限）、T-102-04（accept，vector_recall 白名单交集已挡）。

## Self-Check: PASSED

- server/friday/settings.py 含 PROCESS_RECALL_KIND_LIMITS：存在
- server/services/process_runtime/recall_adapter.py 含 PROCESS_RECALL_ENTITY_KINDS / include_document_kind / arecord_retrieval_trace：存在
- 提交 d4a0881d / f4561acd / 676012fb：均存在
- 10/10 目标测试通过
