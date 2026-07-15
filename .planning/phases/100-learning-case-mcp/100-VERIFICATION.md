---
phase: 100-learning-case-mcp
verified: 2026-07-15T09:35:00Z
status: passed
score: 5/5 success criteria verified
re_verification: false
deferred:
  - truth: "criterion 5 的 Chat 链 RetrievalTrace 覆盖（Chat 白名单接入 search_learning_cases）"
    addressed_in: "Phase 102"
    evidence: "Phase 102 success criteria 2：「Chat 对话可经白名单新增的 search_learning_cases / read_project_doc / search_project_context 三个工具主动读知识」；100-CONTEXT locked decision：「Chat 链本 phase 只需保证 service 层可复用，白名单接入在 Phase 102」——service 层签名（user 参数、纯函数）已就绪并被 technical_plan_service 复用验证"
human_verification:
  - test: "真实 Qdrant + 真实 embedding 环境跑一次 backfill_learning_cases 后，用真实历史 case 的问题描述调 search_learning_cases / search_delivery_knowledge，确认召回质量与排序合理"
    expected: "目标 case 出现在 top-N，score 为 0-1 向量融合分；两入口结果一致收口"
    why_human: "golden set 验收门使用内嵌 :memory: Qdrant + 确定性假 embedding（bag-of-words hash），真实 embedding 模型的召回质量与真实 server Qdrant 行为（payload index 等）无法在 CI 内验证"
  - test: "在有存量数据的部署上执行 python manage.py backfill_learning_cases，观察 backfill_learning_cases_started/completed 事件与调度计数"
    expected: "四类计数正确、重复执行幂等（content_hash 短路，实体/版本数不变）、不删 delivery_knowledge 其他来源"
    why_human: "命令层幂等已有自动化断言（mock 投递），但真实全链路（后台 runner + 真 Qdrant upsert）需部署环境确认"
---

# Phase 100: 知识收敛基座（learning case 入图 + 检索切换 + MCP 产物入图）验证报告

**Phase Goal:** 统一知识库成立——learning case 与 MCP 链路产物全部进入既有 `KnowledgeEntity` + Qdrant `delivery_knowledge`，经 `DeliveryKnowledgeSearchService` 单一检索面可召回；`search_learning_cases` 底层从 token 打分切换为向量检索且对外契约不变。
**Verified:** 2026-07-15（goal-backward，代码 + 测试实跑，不采信 SUMMARY 叙述）
**Status:** passed（5/5 criteria VERIFIED；2 项轻量 human 项见 frontmatter；Chat 链 trace 按 locked decision 归 Phase 102，deferred）
**Re-verification:** No — initial verification

## 测试实跑证据（本次验证独立执行）

```text
uv run pytest tests/knowledge/ tests/mcp_tools/ -q
===== 3 failed, 559 passed, 1 deselected, 181 warnings in 89.28s =====
```

3 个失败全部为 `tests/knowledge/test_triggers.py::TestWorkflowTriggers::test_workflow_plan_generation_*`，根因经复跑确认为 `ModuleNotFoundError: No module named 'workflows.nodes.ai.plan_generation'`（Chassis v2 重构删除该模块的既有腐化，非本 phase 回归，已登记 `deferred-items.md`）。本 phase 触及的全部测试文件（test_models / test_vector_recall / test_learning_case_source / test_mcp_artifact_sources / test_backfill_learning_cases / test_learning_cases / test_schema_snapshot / test_retrieval_trace）全绿。

## Goal Achievement — Success Criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | learning case（含存量 backfill）双入口召回 + work_item/tech_plan 关联边可见 | ✓ VERIFIED | normalizer `server/knowledge/sources/learning_case.py:50-158`（双事件 + RELATES_TO/REFERENCES 边）；create 钩子 `server/mcp_tools/learning_case_service.py:204-206`（aschedule_ingestion，INV-6 唯一通路）；backfill 命令 `server/knowledge/management/commands/backfill_learning_cases.py`；双入口收口断言 `server/tests/mcp_tools/test_learning_cases.py:527-536`（同 query 经 search_delivery_knowledge entity_kinds=["learning_case"] 召回同一 case）；边可见性断言 `server/tests/knowledge/test_learning_case_source.py:277-287`（RELATES_TO/REFERENCES 活跃边） |
| 2 | search_learning_cases 契约不变 + hint 真实生效 + score 定版 + golden set 验收门 + token 退役 | ✓ VERIFIED | `TOOL_SCHEMA_SNAPSHOT` 键集未动 `server/mcp_tools/serializers.py:689-692`（test_schema_snapshot 通过）；payload 外形函数 `learning_case_payload` 一字未改（18 键全集断言 test_learning_cases.py:521-525，score 为 0-1 浮点）；hint 查询增强 + rerank `learning_case_service.py:287-288,318-325`（`_hint_bonus` +0.05/条只影响排序，payload score = 原始 dto.score）；golden set 三形态（中文/路径/symbol）top-3 + hint 提权断言 test_learning_cases.py:501-618；token 打分零残留（`rg "_TOKEN_RE|_tokens"` 于 learning_case_service.py 零命中，无 fallback 开关） |
| 3 | MCP 三产物可被 search_delivery_knowledge 召回 + plan→execution→work_item 边可达 + 与 chat coding_plan 经 natural key 显式关联不重复入图 | ✓ VERIFIED | 三 normalizer `server/knowledge/sources/mcp_coding_plan.py` / `mcp_repository_analysis.py` / `mcp_execution_trace.py`（kind 复用 tech_plan/document/code_change，_NORMALIZERS 注册 sources/__init__.py:38-41）；6 处写入点投递 `views.py:1790,1928,2032,2144` + `work_item_execution_service.py:277,338`；E2E 边可达断言 `server/tests/knowledge/test_mcp_artifact_sources.py:668-796`（plan—IMPLEMENTED_BY→execution、锚—RELATES_TO→plan、plan—RELATES_TO→chat plan、plan—REFERENCES→analysis、traverse 2 跳可达、既有 HAS_PLAN 边未被打失效 T-100-07、natural key 隔离）；natural key 规则表 4 新行 `server/knowledge/models.py:119-122` |
| 4 | 重复摄取幂等（实体数不变、版本翻转正确）+ Qdrant 不可用 fail-soft 不 500 | ✓ VERIFIED | learning_case 幂等/翻版 `test_learning_case_source.py:246-310`（重摄 current_version==1 短路；改 embedding_text 后 v2 supersedes v1）；MCP 三产物幂等 `test_mcp_artifact_sources.py:798+`（两次 ingest 实体/版本数不变、skipped 短路）；fail-soft `learning_case_service.py:330-338`（整段 try/except → 脱敏 warning + 返回 []）+ HTTP 层断言 test_learning_cases.py:621+（search_similar 抛 RuntimeError → 200 + 空 results） |
| 5 | 新召回路径写 RetrievalTrace 并上报条数/耗时/score（MCP 链 + Chat 链） | ✓ VERIFIED（MCP 链）+ deferred（Chat 链→Phase 102） | MCP 链：`views.py:1723-1741` 每条命中一行 FILE trace（source/case_id/score）经 `McpToolView._record`→`arecord_retrieval_trace`；测试断言 test_learning_cases.py:540-546（trace 行 + payload）+ ToolCallRecord.duration_ms + RequestMetric(route="mcp:search_learning_cases")；结构化事件 `learning_case_search_started/completed`（query_len/hint 计数/result_count/duration_ms，component=mcp_tools，category=caller）`learning_case_service.py:277-299,339-345`。Chat 链按 100-CONTEXT locked decision 本 phase 只需 service 层可复用——`search_learning_cases(user=...)` 纯 service 签名已就绪并被 `technical_plan_service.py:352-366` 复用；白名单接入归 Phase 102 KNOW-05（见 frontmatter deferred） |

**Score:** 5/5 criteria verified

## Required Artifacts（三级核验：存在 / 实质 / 接线）

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/knowledge/models.py` | EntityKind.LEARNING_CASE + natural key 规则表 4 行 | ✓ VERIFIED | L54 枚举 + L119-122 规则表；CHECK 约束经 migration 覆盖 |
| `server/knowledge/migrations/0008_extend_entity_kind_learning_case.py` | RemoveConstraint→AlterField→AddConstraint 三段式 | ✓ VERIFIED | 与 0007 先例结构一致，choices/kind__in 均含 learning_case |
| `server/knowledge/vector_recall.py` | 严格 kind 过滤（吞参修复）+ LEARNING_CASE 入 demand 白名单 | ✓ VERIFIED | L29 `_DEMAND_KINDS` 含 LEARNING_CASE；L215-223 显式 entity_kinds 交集过滤、两分路皆空在 embedding 前短路返回 []，回退写法已删 |
| `server/knowledge/sources/learning_case.py` | 双事件 normalizer（锚 + RELATES_TO/REFERENCES 边、降级） | ✓ VERIFIED | 158 行实质实现；event_time=updated_at（版本翻转正确性修复） |
| `server/knowledge/sources/mcp_coding_plan.py` | tech_plan normalizer + build_plan_event 公开纯构造 + chat plan RELATES_TO 反查 | ✓ VERIFIED | 231 行；锚边强制 RELATES_TO 禁用 HAS_PLAN（T-100-07 docstring 存档） |
| `server/knowledge/sources/mcp_repository_analysis.py` | document 单事件 normalizer | ✓ VERIFIED | payload 摘要纪律（不复制 summary 全文） |
| `server/knowledge/sources/mcp_execution_trace.py` | [plan 锚, code_change] 双事件 + IMPLEMENTED_BY 边 + PR payload | ✓ VERIFIED | last_diff/runner_logs 零接触（T-100-06，哨兵串测试兜底） |
| `server/mcp_tools/learning_case_service.py` | 向量切换 + hint rerank + fail-soft + token 退役 | ✓ VERIFIED | search_similar(entity_kinds=["learning_case"], user=...) + 超采样 + 回捞 + rerank；token 实现零残留 |
| `server/mcp_tools/views.py` + `work_item_execution_service.py` | 6 处写入点投递（含 improve 重摄幂等） | ✓ WIRED | views 1790/1928/2032/2144 + service 277/338，TestTriggers 6 用例逐点断言 |
| `server/knowledge/management/commands/backfill_learning_cases.py` | 四类存量回填 + --only + 幂等不删库 | ✓ VERIFIED | test_backfill_learning_cases.py 5 用例（计数/过滤/幂等/静态守护） |

## Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| KNOW-01 | 100-01/02 | ✓ SATISFIED | EntityKind + migration + normalizer + create 钩子（criterion 1 证据） |
| KNOW-02 | 100-01/04 | ✓ SATISFIED | 向量切换 + 契约不变 + token 退役 + golden set + backfill（criterion 2 证据） |
| KNOW-03 | 100-01/03 | ✓ SATISFIED | 三 normalizer + 写入点 + E2E 边可达 + natural key 关联（criterion 3 证据） |

无 ORPHANED requirements（REQUIREMENTS.md 映射 Phase 100 的仅此三项）。

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| — | 本 phase 触及文件无 TBD/FIXME/XXX/TODO/占位实现 | — | `_NORMALIZERS` 100-01 预注册的 4 个模块已全部落地（非 stub） |

## Human Verification Required

### 1. 真实 Qdrant 召回质量抽查

**Test:** 真实部署环境跑 `backfill_learning_cases` 后，用真实历史 case 的问题描述调 `search_learning_cases` 与 `search_delivery_knowledge`。
**Expected:** 目标 case 在 top-N、score 为 0-1 向量融合分、两入口结果收口一致。
**Why human:** golden set 验收门用内嵌 `:memory:` Qdrant + 确定性假 embedding，真实 embedding 模型召回质量与 server Qdrant 行为不可在 CI 内证。

### 2. 存量回填全链路

**Test:** 有存量数据的部署上执行 `python manage.py backfill_learning_cases`（可先 `--only learning_case`）。
**Expected:** started/completed 事件 + 四类计数正确；重复执行幂等；不影响 delivery_knowledge 其他来源。
**Why human:** 自动化断言 mock 了投递层，真实后台 runner + 真 Qdrant upsert 需部署环境确认。

## Gaps Summary

无 gaps。criterion 5 的 Chat 链 trace 覆盖按 100-CONTEXT locked decision 与 Phase 102 success criteria（KNOW-05 白名单接入）归为 deferred，非本 phase 缺口；service 层可复用性（本 phase 应交付的部分）已验证。已知 3 个测试失败为既有腐化（`workflows.nodes.ai.plan_generation` 模块已删），与本 phase 零关联，已登记 deferred-items.md。

---

_Verified: 2026-07-15T09:35:00Z_
_Verifier: gsd-verifier（goal-backward，代码 + 独立测试实跑）_
