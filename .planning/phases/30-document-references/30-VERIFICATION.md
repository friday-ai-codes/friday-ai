---
phase: 30-document-references
verified: 2026-06-15T08:25:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  previous_score: null
human_verification:
  - test: "用真实飞书开放平台凭证（多租户，如 guanghe）经 feishu_document normalizer 摄取真实 PRD/技术方案 docx"
    expected: "Document/DocumentVersion 落正文快照，feishu_tenant 正确派生，REFERENCES 边连真实 work_item；多租户 doc client（开放平台 token，与项目 plugin token 不同域）取材成功"
    why_human: "需真实飞书开放平台凭证 + 多租户域；自动化测试全程 mock get_document_content / doc client，无法验证真实多租户端点正确性（CONTEXT Deferred: human-UAT）"
  - test: "internal_generated 文档（上线说明 / SDD spec）的实际产出 + writeback 回写飞书"
    expected: "内部生成文档经 Document(source_kind=internal_generated, writeback_allowed=True) 路径产出并回写"
    why_human: "本 phase 仅立模型字段位（writeback_allowed / internal_generated），实际产出是 v0.7+ 里程碑，无实现可验证（CONTEXT Deferred）"
---

# Phase 30: Document + REFERENCES 边 Verification Report

**Phase Goal:** 区分 external_feishu/internal_generated 文档落独立 Document/DocumentVersion（delivery）；feishu_document normalizer 摄取飞书 docx + REFERENCES 边关联 WorkItem；给定 prd_url 的 WorkItem 经 Document 检索 PRD 正文快照。DOC-01, DOC-02. INV-3/INV-6.
**Verified:** 2026-06-15T08:25:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Document/DocumentVersion 区分 source_kind(external_feishu\|internal_generated) + document_type(prd\|tech_plan\|...)，PRD/技术方案落独立操作态实体（DOC-01） | ✓ VERIFIED | `models/document.py` 三枚举 + 两模型逐字段对齐 DOMAIN §3/§12.5；`0004` 迁移建出 `delivery_document` / `delivery_document_version`；`test_document_models.py` 7 测试绿 |
| 2 | Document/DocumentVersion 落库只经 DocumentService 单一入口（INV-6），grep 守护 | ✓ VERIFIED | `document_service.py` `upsert_from_feishu` 唯一 writer；`test_document_inv6_guard.py` 旁路写表扫描 + writer 有效性双断言绿 |
| 3 | external_feishu 按 (feishu_tenant, external_ref) 去重；content_hash 相等不翻版本，不等翻版本 + supersedes + 推进 current_version | ✓ VERIFIED | `_upsert_locked` select_for_update().get_or_create + hash 判定；`test_document_service.py` 11 测试覆盖去重/hash/supersedes/facet 绿 |
| 4 | feishu_document normalizer 注册进 get_normalizer，摄取飞书 docx（复用 _extract_doc_token + _fetch_doc_body + doc client，不重写取材） | ✓ VERIFIED | `sources/__init__.py` `_NORMALIZERS["feishu_document"]` 注册；`feishu_document.py` import 复用既有 helper |
| 5 | 产出 knowledge KnowledgeEntity(kind=document) + KnowledgeEdge(REFERENCES) 连 work_item→document（DOC-02） | ✓ VERIFIED | `feishu_document.py` document IngestionEvent(kind=DOCUMENT) + REFERENCES EdgeSpec via dataclasses.replace 挂 wi 锚事件；`knowledge.models` `EntityKind.DOCUMENT` / `EdgeRelation.REFERENCES` 已定义；端到端测试断言入图 |
| 6 | doc 拉取失败降级：缺正文段 + warning，Document/实体仍建（缺段不缺实体），不抛不回滚 | ✓ VERIFIED | `_fetch_doc_body` 空串降级 + 操作态写入 try/except 仅 warning；facet=missing；`test_feishu_document_normalizer.py` 降级测试绿 |
| 7 | 给定带 prd_url 的 WorkItem（三元组）经 Document 实体只读检索 PRD 正文快照（DOC-02 成功标准 3，IsAuthenticated） | ✓ VERIFIED | `WorkItemPrdDocumentView` filter(work_item, document_type).select_related → current_version.content；`DocumentSnapshotSerializer` 全 read_only；路由 `work-items/prd-document/`；`test_document_api.py` 7 测试（命中/401/400/404/只读）绿 |
| 8 | 既有 feishu_work_item normalizer 内联正文保留不动（INV-3），work_item 锚事件复用其产出不 clobber | ✓ VERIFIED | normalizer 复用 `feishu_work_item.normalize` 产出 wi_events[0]；SUMMARY git diff 确认 feishu_work_item.py 未修改；`test_inv3_*` content 一致断言绿 |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/delivery/models/document.py` | Document + DocumentVersion + 三枚举 | ✓ VERIFIED | 逐字段对齐 §12.5；模型层无 create/save 业务方法 |
| `server/delivery/migrations/0004_document_documentversion.py` | 两表 + unique_together + 三索引 | ✓ VERIFIED | makemigrations --check → No changes detected |
| `server/delivery/services/document_service.py` | DocumentService.upsert_from_feishu + derive_feishu_tenant + _content_hash | ✓ VERIFIED | 单一写入收口，去重/版本/facet 完整 |
| `server/knowledge/sources/feishu_document.py` | async normalize → Document + document 实体 + REFERENCES 边 | ✓ VERIFIED | 复用既有取材，双层产出 |
| `server/delivery/api/views.py` (WorkItemPrdDocumentView) | PRD 快照只读端点 | ✓ VERIFIED | IsAuthenticated，纯读不写 |
| `server/delivery/api/serializers.py` (DocumentSnapshotSerializer) | 只读序列化 | ✓ VERIFIED | 全字段 read_only |
| `server/delivery/urls.py` | prd-document/ 路由 | ✓ VERIFIED | 字面段优先于通配 work-items/ |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| feishu_document.py | DocumentService.upsert_from_feishu | 操作态落库经单一入口（INV-6） | ✓ WIRED |
| feishu_document.py | document 实体 (generate_entity_id) | REFERENCES EdgeSpec 出边（work_item→document） | ✓ WIRED |
| feishu_document.py | feishu_work_item.normalize | 复用 wi 锚事件不 clobber | ✓ WIRED |
| WorkItemPrdDocumentView | Document.filter(document_type=prd).current_version.content | 只读查询路径 | ✓ WIRED |
| Document.work_item | delivery.WorkItem | 同 app FK SET_NULL related_name=documents | ✓ WIRED |
| DocumentService | WorkItemSyncState(prd_body/tech_doc) | facet 完整度记录 | ✓ WIRED |

### Behavioral Spot-Checks / Probe Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 30 套件全绿 | `pytest tests/delivery/test_document_*.py tests/knowledge/test_feishu_document_normalizer.py -q` | 35 passed | ✓ PASS |
| 迁移干净 | `python manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DOC-01 | 30-01, 30-02 | 区分外部/内部文档（document_type/source_kind/content_storage），PRD/技术方案落独立 Document | ✓ SATISFIED | 模型 + 迁移 + DocumentService 单一写入 |
| DOC-02 | 30-03, 30-04 | feishu_document normalizer 摄取 docx + REFERENCES 边关联 WorkItem | ✓ SATISFIED | normalizer 注册 + REFERENCES 边 + PRD 快照检索端点 |

### Anti-Patterns Found

无 BLOCKER。源码无 TBD/FIXME/XXX 未引用债务标记。降级路径的 try/except + warning 为既定 §1.4 降配范式，非 stub。

### Human Verification Required

#### 1. 真实多租户飞书 docx 摄取端点正确性

**Test:** 用真实飞书开放平台凭证（多租户，如 guanghe）经 feishu_document normalizer 摄取真实 PRD/技术方案 docx。
**Expected:** Document/DocumentVersion 落正文快照，feishu_tenant 正确派生，REFERENCES 边连真实 work_item；多租户 doc client（开放平台 token，与项目 plugin token 不同域）取材成功。
**Why human:** 需真实开放平台凭证 + 多租户域；自动化测试全程 mock get_document_content / doc client，无法验证真实多租户端点正确性（CONTEXT Deferred: human-UAT）。

#### 2. internal_generated 文档产出 + writeback

**Test:** internal_generated 文档（上线说明 / SDD spec）的实际产出 + writeback 回写飞书。
**Expected:** 内部生成文档经 Document(source_kind=internal_generated, writeback_allowed=True) 路径产出并回写。
**Why human:** 本 phase 仅立模型字段位，实际产出是 v0.7+ 里程碑，无实现可验证（CONTEXT Deferred）。

### Gaps Summary

无 gap。DOC-01 / DOC-02 全部观察态真理在代码中证实：操作态 Document/DocumentVersion 模型与迁移、DocumentService 单一写入入口（INV-6 grep 守护）、feishu_document normalizer 注册并产出 knowledge 投影 + REFERENCES 边、PRD 正文快照只读检索端点、INV-3 不 clobber 既有 feishu_work_item 投影——均验证通过，35 个 phase 测试 + 迁移检查全绿。两项 human_needed（真实多租户端点正确性、internal_generated 产出/writeback）按 CONTEXT 明确 deferred/human-UAT，非本 phase gap。

---

_Verified: 2026-06-15T08:25:00Z_
_Verifier: Claude (gsd-verifier)_
