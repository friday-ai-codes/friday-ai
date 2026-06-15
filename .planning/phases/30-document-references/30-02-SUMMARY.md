---
phase: 30-document-references
plan: 02
subsystem: services
tags: [django, delivery, document, document-version, service, inv-6, dedup, content-hash, version-chain, sync-state, facet, pytest-django, async, sync-to-async]

# Dependency graph
requires:
  - phase: 30-document-references
    plan: 01
    provides: Document/DocumentVersion 模型 + 三枚举 + 0004 migration（落库目标表）
  - phase: 28-workitem-spine
    provides: WorkItem 脊柱 + WorkItemSyncState(prd_body/tech_doc facet) + service async 范式
provides:
  - DocumentService.upsert_from_feishu —— Document/DocumentVersion 单一写入入口（INV-6）
  - derive_feishu_tenant —— doc URL host 派生租户 slug 纯函数
  - _content_hash —— sha256 内容指纹（复用 knowledge 算法，单一来源）
  - Document/DocumentVersion 旁路写表 INV-6 grep 守护测试
affects: [30-03 feishu_document normalizer（调用 DocumentService 落操作态）, 30-04 PRD 快照检索, 32 一键摄取]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Document 写入收口复用 28-02 WorkItemService 范式：async-first + sync_to_async 桥接 ORM + transaction.atomic + select_for_update"
    - "去重定位键 (feishu_tenant, external_ref=doc_token)：select_for_update().get_or_create 单锁收敛同一 Document"
    - "内容版本范式复用 knowledge 'hash 相等不翻版本' 铁律：content_hash 相等仅刷 last_synced_at，不等建新版本 + supersedes 链 + 推进 current_version"
    - "facet 完整度复用 28-02 _record_sync_state：update_or_create(work_item, facet) 幂等；content 非空 complete / 缺正文 missing"
    - "Document INV-6 grep 守护独立文件（不改 Phase 28 test_inv6_guard.py），精确锚定无误伤"

key-files:
  created:
    - server/delivery/services/document_service.py
    - server/tests/delivery/test_document_service.py
    - server/tests/delivery/test_document_inv6_guard.py
  modified:
    - server/delivery/services/__init__.py

key-decisions:
  - "feishu_tenant 由 doc URL host 派生（<tenant>.feishu.cn → tenant）；非飞书域 / 无意义首段（feishu.cn/www）→ ''（CONTEXT Claude's Discretion：取 doc URL host 为稳定租户来源）"
  - "_content_hash 复用 knowledge ingestion 同 sha256 算法但不 import knowledge（INV-3：守单向，knowledge 投影是 30-03 职责）"
  - "document_type 首建后不漂移：doc_token 不变即同一文档，已存在仅刷 mirror 类字段（canonical_url、work_item 若先前 None 则补连）"
  - "facet 仅对 prd→prd_body / tech_plan→tech_doc 记录；其余类型不记 facet；work_item=None 跳过 facet 且不抛"
  - "缺正文降级（content=''）仍 upsert Document/Version（缺段不缺实体），facet 记 missing——对齐 §1.4 降级范式，不回滚"

patterns-established:
  - "delivery 第三个操作态写入收口（继 WorkItemService / CommentEventService）：Document/DocumentVersion 唯一 writer，INV-6 grep 守护 + writer 有效性双断言"

requirements-completed: [DOC-01]

# Metrics
duration: ~25min
completed: 2026-06-15
---

# Phase 30 Plan 02: DocumentService 单一写入入口 Summary

**新增 `DocumentService.upsert_from_feishu` 作为 Document/DocumentVersion 落库的唯一写入收口（INV-6）：external_feishu 文档按 `(feishu_tenant, external_ref=doc_token)` 去重定位，`content_hash` 相等不翻版本、不等建新 `DocumentVersion` + supersedes 链并推进 `current_version`，落 `content_storage=both`、`feishu_tenant` 由 doc URL host 派生；摄取成功按 `document_type` 映射记 `WorkItemSyncState(prd_body|tech_doc)` facet 完整度（缺正文 missing）。配 Document/DocumentVersion 旁路写表 INV-6 grep 守护（精确锚定无误伤）。11 个 service 测试 + 2 个守护测试全绿，delivery 套件 114 passed 无回归。**

## What Was Built

### Task 1 [TDD]: DocumentService.upsert_from_feishu 单一写入入口

- `server/delivery/services/document_service.py`：
  - **`_content_hash(text)`**：`hashlib.sha256(text.encode("utf-8")).hexdigest()`——与 knowledge ingestion 同算法（单一来源），不 import knowledge（INV-3）。
  - **`derive_feishu_tenant(canonical_url)`**：`urlparse().hostname` 取首段子域作租户 slug（`guanghe.feishu.cn` → "guanghe"、`acme.larksuite.com` → "acme"）；非飞书/lark 域、无 host、无意义首段（`feishu.cn`/`www`）→ ""。
  - **`DocumentService.upsert_from_feishu(*, work_item, document_type, doc_token, content, canonical_url, feishu_tenant="", source="manual")`**：
    - 去重定位键 `(feishu_tenant or derive_feishu_tenant(canonical_url), external_ref=doc_token)`。
    - 经 `sync_to_async` 的 `_upsert_locked`：`transaction.atomic()` + `Document.objects.select_for_update().get_or_create(...)`，首建落 `source_kind=external_feishu` + `content_storage=both` + canonical_url + work_item；已存在刷 mirror（canonical_url 变更、work_item 先前 None 则补连，document_type 不漂移）。
    - 版本判定：current_version 存在且 `content_hash` 相等 → 仅刷 last_synced_at（**不翻版本**）；否则建 `DocumentVersion(version=cur.version+1 if cur else 1, supersedes=cur, content, content_hash)` 并推进 `Document.current_version`（显式 update_fields 白名单）。
    - facet：`prd→PRD_BODY`、`tech_plan→TECH_DOC`，content 非空 `complete` / 空 `missing`，经 `_record_sync_state`（`WorkItemSyncState.update_or_create(work_item, facet)`，复用 28-02 范式）；work_item=None 跳过。
  - `server/delivery/services/__init__.py`：re-export `DocumentService` / `derive_feishu_tenant`，更新 `__all__`。
- `server/tests/delivery/test_document_service.py`：11 个测试（2 个纯函数 `derive_feishu_tenant` + 9 个 service）覆盖首摄建实体/版本/facet、`(tenant, token)` 去重收敛、hash 相等不翻版本、hash 不等翻版本+supersedes+current_version 推进、缺正文 facet=missing、tech_plan→tech_doc、work_item=None 跳过 facet 不抛、显式 tenant 覆盖派生、work_item 后补连。

### Task 2: Document/DocumentVersion INV-6 旁路写表 grep 守护

- `server/tests/delivery/test_document_inv6_guard.py`：纯本地源码扫描（无 DB/网络），沿用 `test_inv6_guard.py` 精确锚定范式，独立文件（不改 Phase 28 文件，避免所有权冲突）：
  - 唯一 writer 常量 `_ALLOWED_DOCUMENT_WRITER = "delivery/services/document_service.py"`。
  - Document 三正则（`Document.objects.<write>` / `\bDocument\s*\(` / `Document(...).save(`）+ DocumentVersion 同款三正则。
  - `test_inv6_no_bypass_document_write`：遍历 server/ .py（排除 writer/tests/migrations/models），跳过 `class Document*` 定义行，命中即记 violation 断言为空。
  - `test_inv6_document_writer_module_actually_writes`：断言 writer 确含 `get_or_create` + DocumentVersion 写表（守护有效性）。

## Verification Results

- `pytest tests/delivery/test_document_service.py -x -q` → **11 passed**。
- `pytest tests/delivery/test_document_inv6_guard.py -q` → **2 passed**。
- `pytest tests/delivery/ -q` → **114 passed**（含既有 test_inv6_guard.py / 28 / 29 套件，无回归）。
- `ruff format --check` + `ruff check delivery/ tests/delivery/` → 全部干净。
- service 测试全程无真实网络（pytest-socket；DocumentService 不回源，content 由调用方传入）。
- delivery 未 import knowledge 投影模型（INV-3，test_inv3_delivery_does_not_write_knowledge_models 覆盖）；无新增第三方依赖（T-30-SC accept）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DocumentService docstring 触发 INV-3 守护误报**
- **Found during:** Task 2 后全套回归
- **Issue:** 既有 `test_inv3_delivery_does_not_write_knowledge_models` 扫描 `delivery/` 源码**文本**（`"knowledge.models" in text or \bKnowledgeEntity\b`），document_service.py docstring 字面提及投影模型名（`不 import knowledge.models / 不写 KnowledgeEntity`）触发误报，1 failed。
- **Fix:** 把 docstring 改述为中文描述（"不 import / 不写 knowledge 投影模型"），去掉字面 token；语义不变，守护恢复绿。
- **Files modified:** server/delivery/services/document_service.py
- **Commit:** a0b54f1d

**2. [Rule 3 - Blocking] 守护测试 docstring 正则转义 SyntaxWarning**
- **Found during:** Task 2
- **Issue:** test_document_inv6_guard.py 模块 docstring 含 `\b`/`\s` 正则示例，触发 `SyntaxWarning: invalid escape sequence`。
- **Fix:** 模块 docstring 改为 raw 字符串（`r"""`）。
- **Files modified:** server/tests/delivery/test_document_inv6_guard.py
- **Commit:** fd649ace（含在 Task 2 提交内）

## Threat Surface

- T-30-03（旁路写 Document 表）：DocumentService 单一写入收口 + test_document_inv6_guard.py grep 守护（精确锚定无误伤）→ **mitigated**。
- T-30-04（重复摄取放大版本表）：`(feishu_tenant, external_ref)` 去重 + `content_hash` 相等不翻版本，service 测试 `test_dedup_*` / `test_hash_equal_*` 守护 → **mitigated**。
- T-30-05（SyncState.error/日志凭证泄漏）：DocumentService 不回源、content 由调用方传入，facet 记录不拼接外部错误串（error=""）；文档正文属业务内容不入 error 面 → **mitigated（surface 未开放）**。
- T-30-SC（依赖供应链）：纯 Django service + stdlib hashlib/urllib，无新增包 → **accept**（不触发包合法性门）。
- 无计划外新增安全相关 surface。

## Self-Check: PASSED

- FOUND: server/delivery/services/document_service.py
- FOUND: server/delivery/services/__init__.py
- FOUND: server/tests/delivery/test_document_service.py
- FOUND: server/tests/delivery/test_document_inv6_guard.py
- FOUND commit: 128eb41d (Task 1 RED: failing service tests)
- FOUND commit: 43bafa42 (Task 1 GREEN: DocumentService impl)
- FOUND commit: fd649ace (Task 2: INV-6 guard test)
- FOUND commit: a0b54f1d (fix: INV-3 docstring)
