---
phase: 30-document-references
plan: 03
subsystem: knowledge
tags: [django, knowledge, normalizer, feishu, document, references, edge, ingestion, projection, degradation, inv-3, inv-6, pytest-django, async]

# Dependency graph
requires:
  - phase: 30-document-references
    plan: 01
    provides: Document/DocumentVersion 模型 + 三枚举（操作态落库目标）
  - phase: 30-document-references
    plan: 02
    provides: DocumentService.upsert_from_feishu 单一写入入口（INV-6）+ derive_feishu_tenant
  - phase: 28-workitem-spine
    provides: WorkItem 脊柱（work_item FK 关联）
provides:
  - feishu_document normalizer —— 飞书 docx（PRD/技术方案）→ 操作态 Document + knowledge document 实体 + work_item→REFERENCES→document 边
  - get_normalizer 注册表登记 feishu_document
affects: [32 一键摄取（经 Document 路径摄取 PRD/技术方案）, 34 文档反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "work_item 锚事件复用 feishu_work_item.normalize 产出（content 逐字一致 hash 相等不 clobber 既有快照，INV-3）"
    - "REFERENCES 出边 via dataclasses.replace 挂到 frozen IngestionEvent（work_item→document 方向，对齐 mcp_plan HAS_PLAN 双事件出边范式）"
    - "doc token 取自 work_item 锚事件 payload 内 prd_url/tech_doc_url 字面值（不重复 get_work_item）"
    - "操作态写入（DocumentService，INV-6）与 knowledge 投影（ingest_events）双层并存；操作态写入异常仅 warning 不阻断投影（降级不回滚）"
    - "doc 取材复用 _extract_doc_token + _fetch_doc_body + create_feishu_doc_client_for_project + get_document_content（不重写取材路径）"

key-files:
  created:
    - server/knowledge/sources/feishu_document.py
    - server/tests/knowledge/test_feishu_document_normalizer.py
  modified:
    - server/knowledge/sources/__init__.py

key-decisions:
  - "normalizer 输入签名取工作项三元组（CONTEXT Grey Area 3 Claude's Discretion），与 feishu_work_item 同锚"
  - "work_item 锚事件复用 feishu_work_item.normalize 产出，不重写取材；feishu_work_item.py 不修改（INV-3）"
  - "doc token 从 wi 锚事件 payload 的 prd_url/tech_doc_url 提取（避免重复 get_work_item）；doc 正文仍经 _fetch_doc_body 拉取（与 feishu_work_item 内联正文同 docx 二次拉取，accepted tradeoff per plan note）"
  - "document 实体 title 取正文首个 markdown 标题，缺正文降级 work_item 名+文档类型 label"
  - "REFERENCES 边非 exclusive（一个 work_item 可同时引用 PRD 与技术方案两文档）"
  - "操作态 WorkItem 缺则 None 占位（缺脊柱不缺文档实体）；id 非法不抛"

patterns-established:
  - "knowledge 第六个 normalizer：复用既有锚事件 + 既有取材 helper，产出双层（操作态 Document + knowledge 投影）+ 跨实体 REFERENCES 边"

requirements-completed: [DOC-02]

# Metrics
duration: ~20min
completed: 2026-06-15
---

# Phase 30 Plan 03: feishu_document normalizer + REFERENCES 边 Summary

**新增 `server/knowledge/sources/feishu_document.py` normalizer 并注册进 `get_normalizer` 注册表：从工作项三元组 + work_item 锚事件 payload 的 `prd_url`/`tech_doc_url` 提取飞书 doc token（复用 `_extract_doc_token`），经既有 `create_feishu_doc_client_for_project` + `get_document_content` 拉正文（复用 `_fetch_doc_body`，不重写取材），产出 ① 操作态 `Document`/`DocumentVersion`（经 30-02 `DocumentService` 单一入口 INV-6 + `work_item` FK）；② knowledge 投影 `KnowledgeEntity(kind=document)` + `KnowledgeEdge(relation=REFERENCES)` 连 work_item 实体 → document 实体（方向 work_item→document，对齐 mcp_plan HAS_PLAN 出边范式）。work_item 锚事件复用 `feishu_work_item.normalize` 产出（content 逐字一致 hash 相等不 clobber 既有快照），`feishu_work_item.py` 未修改（INV-3）。doc 拉取失败降级缺正文段 + warning，缺段不缺实体不抛不回滚。8 个 normalizer 守护测试全绿，knowledge + delivery 套件 392 passed（仅既有无关 test_triggers.py 1 failed，按指示忽略）。**

## What Was Built

### Task 1: feishu_document normalizer（操作态 Document + knowledge document 实体 + REFERENCES 边）+ 注册

- `server/knowledge/sources/feishu_document.py`：
  - **`async normalize(request)`**：source_kind 字面值 `feishu_document`，source_id = 工作项三元组 `{project_key}:{work_item_type}:{work_item_id}`（与 feishu_work_item 同锚）。
  - 流程（复用既有取材，缺料降级不抛）：① 解析三元组（非法/缺段 → `knowledge_normalize_source_missing` warning + `return []`）；取 Project（缺 → warning + `[]`）；② **work_item 锚事件复用 `feishu_work_item.normalize(request)`**（wi_events 空 → warning + `[]`），取 `wi_events[0]` 作锚——content 与既有 feishu_work_item 投影逐字一致，hash 相等不翻版本（INV-3 不 clobber）；③ doc token 取自 wi 锚事件 payload 内 `prd_url`/`tech_doc_url` 字面值，经 `_extract_doc_token` 提取（避免重复 `get_work_item`）；两者皆空 → 原样返回 wi 锚事件（缺段不缺实体）；④ `create_feishu_doc_client_for_project` try/except 降级 None；⑤ 对每个 (document_type, token, canonical_url)：`_fetch_doc_body` 拉正文（失败返回空串 + warning），**操作态落库** `DocumentService().upsert_from_feishu(...)`（整段 try/except，异常仅 warning 不阻断投影），构造 **knowledge document IngestionEvent**（kind=DOCUMENT/origin=FEISHU/source_kind=feishu_document/source_id=token），累加 **REFERENCES 出边 EdgeSpec**（target=`generate_entity_id("document","feishu_document",token)`）；⑥ `dataclasses.replace(wi_event, edges=(*wi_event.edges, *reference_edges))` 挂边，`return [wi_event_with_edges, *document_events]`。
  - 复用纪律：`_extract_doc_token` / `_fetch_doc_body` 从 feishu_work_item import 复用；doc client + get_document_content 经既有 service 取材；feishu_work_item.py **未修改**（INV-3）。
- `server/knowledge/sources/__init__.py`：`_NORMALIZERS` 注册 `"feishu_document": "knowledge.sources.feishu_document"`（沿用惰性 import 风格）。

### Task 2: normalizer 端到端守护测试（Document + REFERENCES 边 + 降级 + hash + INV-3）

- `server/tests/knowledge/test_feishu_document_normalizer.py`（`django_db(transaction=True)`，monkeypatch feishu client（get_work_item/relations）+ doc client（get_document_content），复用 conftest embedding/qdrant mock + 本地 mock_ensure/mock_upsert，pytest-socket 零真实网络）：8 个测试覆盖
  - normalize 产出形状：wi 锚（携 REFERENCES 出边，target id 经 generate_entity_id）+ document 事件；
  - prd_url + tech_doc_url 同存 → 两 document 事件 + 两 REFERENCES 出边；
  - 端到端 `await ingest_events`：`KnowledgeEntity(kind=document, source_kind=feishu_document, source_id=token)` + `KnowledgeEdge(REFERENCES, source=work_item 实体, target=document 实体)`，边方向 work_item→document；
  - 操作态 Document(work_item, prd, both, external_ref=token, feishu_tenant=guanghe) + DocumentVersion(content) + facet PRD_BODY=complete；
  - 降级：get_document_content 抛异常 → 正文空、normalize 不抛、document 事件 + REFERENCES 边仍在、Document 仍建（content 空）、facet=missing；
  - hash 相等二次 normalize → DocumentVersion 计数不变；
  - INV-3：wi 锚事件 content/title 与单独跑 feishu_work_item.normalize 一致；
  - 无文档 token → 仅返回 wi 锚事件（无 document、edges=()、Document 零建）。

## Verification Results

- `pytest tests/knowledge/test_feishu_document_normalizer.py -q` → **8 passed**。
- `pytest tests/knowledge/ tests/delivery/ -q` → **392 passed, 1 deselected, 1 failed**（唯一 failed = 既有无关 `tests/knowledge/test_triggers.py::test_coding_chat_pr_created_branch_delivers_once`，按执行指示忽略；feishu_document/ingestion/delivery 全绿无回归）。
- `ruff format` + `ruff check knowledge/sources/feishu_document.py knowledge/sources/__init__.py tests/knowledge/test_feishu_document_normalizer.py` → 全部干净。
- INV-3：`git diff --stat HEAD -- server/knowledge/sources/feishu_work_item.py` → **空**（feishu_work_item.py 未被修改）。
- 取材复用：feishu_document 未重写 doc 拉取（复用 `_extract_doc_token` / `_fetch_doc_body` / `create_feishu_doc_client_for_project` / `get_document_content`）；未新增第三方依赖（T-30-SC accept）。

## Deviations from Plan

None - 计划按写法执行。

**关于双拉取（plan-checker advisory，accepted）：** 复用 `feishu_work_item.normalize`（内部已拉一次 docx 正文做内联快照）+ 本 normalizer 经 `_fetch_doc_body` 再拉一次供 Document 落库，同一 docx 被拉取两次。按 plan NOTE 这是 accepted tradeoff（复用既有取材 vs 单次拉取去重）；未做 dedupe 以避免重写 feishu_work_item 取材逻辑（INV-3 不动既有 normalizer）。

## Threat Surface

- T-30-06（doc 拉取失败掀翻摄取）：`_fetch_doc_body` 失败返回空串 + warning；操作态写入 try/except 不阻断投影；缺段不缺实体不抛不回滚（`test_doc_fetch_failure_degrades_without_raise` 守护）→ **mitigated**。
- T-30-07（clobber 既有 feishu_work_item 快照）：work_item 锚事件复用 `feishu_work_item.normalize` 产出（content 一致 hash 相等不翻版本），feishu_work_item.py 未修改（`test_inv3_work_item_anchor_content_matches_feishu_work_item` + git diff 守护）→ **mitigated**。
- T-30-08（doc 拉取失败日志泄漏凭证）：沿用 feishu_work_item warning 仅记 doc_token/error 类型，凭证经既有 service 层（DB 加密，零 env）→ **mitigated**。
- T-30-SC（依赖供应链）：无新增包（复用既有 feishu doc client + ingestion 管线）→ **accept**（不触发包合法性门）。
- 无计划外新增安全相关 surface。

## Self-Check: PASSED

- FOUND: server/knowledge/sources/feishu_document.py
- FOUND: server/knowledge/sources/__init__.py
- FOUND: server/tests/knowledge/test_feishu_document_normalizer.py
- FOUND commit: e3ab2275 (Task 1: normalizer + register)
- FOUND commit: 077865db (Task 2: guard tests)
