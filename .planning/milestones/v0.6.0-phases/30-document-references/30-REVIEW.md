---
phase: 30-document-references
reviewed: 2026-06-15T16:23:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - server/delivery/models/document.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0004_document_documentversion.py
  - server/delivery/services/document_service.py
  - server/delivery/services/__init__.py
  - server/delivery/api/views.py
  - server/delivery/api/serializers.py
  - server/delivery/urls.py
  - server/knowledge/sources/feishu_document.py
  - server/knowledge/sources/__init__.py
  - server/tests/delivery/test_document_api.py
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: clean
fix_pass:
  fixed:
    - WR-01  # 加 (feishu_tenant, external_ref) 条件 UniqueConstraint（迁移 0005）+ 约束/幂等测试；get_or_create savepoint 天然处理 IntegrityError
  deferred:
    - id: IN-01  # 文档正文重复拉取/快照一致性 — 可接受权衡（plan-checker 已记），P32 一键摄取时优化
    - id: IN-02  # 未来 internal_generated 空键冲突 — 已由 WR-01 条件约束（仅非空 ref）一并消除
    - id: IN-03  # normalizer source 硬编码 "manual" — 低风险，后续接入真实来源时再传
    - id: IN-04  # feishu_document source_id 三元组 vs natural-key token 语义 — P32 接入时对齐
---

# Phase 30: Code Review Report

**Reviewed:** 2026-06-15T16:23:00Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

审查覆盖 Phase 30 全部新增/变更源文件（delivery `Document`/`DocumentVersion` 模型 + 迁移、`DocumentService` 单一写入入口、PRD 快照只读 REST、`feishu_document` normalizer + 注册、配套测试）。

核心契约总体落实正确：
- **INV-6 单一写入**：`Document`/`DocumentVersion` 落库收口于 `DocumentService.upsert_from_feishu`，grep 守护精确锚定有效，normalizer/REST/测试夹具均不旁路 ORM 写。
- **hash 版本规则**：`current_version.content_hash` 相等不翻版本（仅刷 `last_synced_at`），不等才建新版本 + `supersedes` 链 + 推进 `current_version`，与 knowledge 铁律一致。
- **REFERENCES 边方向**：`work_item →(REFERENCES)→ document`，边 `target_entity_id == generate_entity_id("document","feishu_document",token)` 与 document 事件实体 id 同源（`EntityKind.DOCUMENT == "document"`，f-string 派生一致），端到端测试验证通过。
- **INV-3 不 clobber**：work_item 锚事件复用 `feishu_work_item.normalize` 逐字产出，hash 相等短路；`feishu_work_item.py` 未改动。
- **降级 no-rollback**：doc 拉取失败 → 正文空串 + warning，Document/版本/边照常产出，facet 记 `missing`；upsert 异常仅 warning 不阻断 knowledge 投影。
- **REST 只读 + 鉴权**：`IsAuthenticated` 守卫、`select_related("current_version")` 预取、`document_type` 校验、404 语义明确、无写入；无凭证泄漏（序列化器仅暴露 doc 元数据 + 正文，日志不含凭证）。
- **向后兼容**：迁移 0004 仅新增表/索引，依赖 0003，无既有表改动。

发现 1 个 WARNING（去重不变量缺 DB 层强约束）+ 4 个 INFO（重复取材、未来内部文档键冲突隐患、source 硬编码、source_id 契约歧义）。

## Warnings

### WR-01: `(feishu_tenant, external_ref)` 去重缺 DB 层唯一约束，并发可产生重复 Document

**File:** `server/delivery/models/document.py:99-104`、`server/delivery/services/document_service.py:165-175`
**Issue:** CONTEXT/DOMAIN 把 `(feishu_tenant, external_ref)` 定为 external_feishu 文档的「唯一定位/去重键」，但 `Document.Meta` 只对该组合建了**普通 `Index`**，无 `unique_together` / `UniqueConstraint`（仅 `DocumentVersion` 有 `unique_together(document, version)`）。`_upsert_locked` 依赖 `select_for_update().get_or_create(feishu_tenant=tenant, external_ref=doc_token)` 去重——但在 Postgres READ COMMITTED 下，目标行**尚不存在**时 `SELECT ... FOR UPDATE` 无行可锁，两个并发事务会双双走到 INSERT，产生**两条同 token 的 Document**。摄取经 `aschedule_ingestion` → `transaction.on_commit` → `run_in_background` 投递，同一工作项 webhook 抖动 / 并行触发会真实并发，破坏「唯一定位」不变量并使版本链与 PRD 检索（`order_by("-updated_at").afirst()`）结果分叉。现有测试均为顺序流，覆盖不到该窗口。
**Fix:** 加 DB 级条件唯一约束（必须排除内部生成文档的空键，见 IN-02），例如：

```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["feishu_tenant", "external_ref"],
            condition=models.Q(source_kind="external_feishu"),
            name="uniq_document_external_ref",
        ),
    ]
```

并在 `_upsert_locked` 捕获 `IntegrityError` 走「并发已建 → 重读收敛」幂等分支（沿用 `ingestion._persist_sync` 撞约束范式）。

## Info

### IN-01: PRD/技术方案正文被重复拉取，且快照与 Document 正文可能不一致

**File:** `server/knowledge/sources/feishu_document.py:95,138-140`
**Issue:** `normalize` 先调 `feishu_work_item.normalize(request)`（其内部已 `_fetch_doc_body` 拉取 prd/tech 正文内联进 work_item 快照），随后又在 `targets` 循环里对同一 token 再次 `_fetch_doc_body`——每篇文档被拉取两次。除冗余外部调用外，两次取材之间若文档被改动，work_item 知识快照内联正文与操作态 Document 正文会**不一致**（低概率、下次摄取自愈）。CONTEXT Grey Area 3 的「复用取材路径」本意是复用 `_fetch_doc_body` 函数，已满足；此处记重复调用的质量/一致性隐患（性能本身按 v1 约定不计分）。
**Fix:** 评估从 work_item 快照已拉取的正文中复用 doc body（或将取材抽到单次缓存），避免对同一 token 二次 `get_document_content`。

### IN-02: `upsert_from_feishu` 去重键对未来 internal_generated 文档会键冲突

**File:** `server/delivery/services/document_service.py:165-175`
**Issue:** `get_or_create` 仅以 `(feishu_tenant, external_ref)` 定位。当 v0.7+ 落内部生成文档时 `external_ref=""`、`feishu_tenant=""`，所有内部文档都会命中同一 `("","")` 键，导致 `get_or_create` **返回首条而非新建**。本 phase 仅经 `upsert_from_feishu`（external 专用，token 恒非空）写入，尚不触发；但该入口被复用于内部文档前必须换键。
**Fix:** 明确 `upsert_from_feishu` 为 external-only 入口（docstring 已暗示），internal 文档落库走独立入口/键（如按 internal 自身业务 id）；或在 WR-01 的唯一约束上加 `external_ref != ""` 条件并对内部文档单独定位。

### IN-03: normalizer 写 facet 时 `source` 硬编码为 "manual"

**File:** `server/knowledge/sources/feishu_document.py:152`
**Issue:** `upsert_from_feishu(..., source="manual")` 写死，使 `WorkItemSyncState.source` 恒为 `manual`，与实际触发来源（webhook/sync 等 `WorkItemOrigin`）不符；CONTEXT 期望 source 记真实 origin。影响 facet 来源追溯准确性，无功能性破坏。
**Fix:** 由 `IngestionRequest`/调用方透传真实 origin 到 `source`，缺省再回落 `manual`。

### IN-04: feishu_document 的 `source_id` 双重语义（请求级三元组 vs 实体级 token）易致下游误接

**File:** `server/knowledge/sources/feishu_document.py:65-82`、`server/knowledge/models.py:95`
**Issue:** `feishu_document.normalize` 要求 `request.source_id` 为**工作项三元组** `{project_key}:{type}:{id}`（用于定位 work item），而 `generate_entity_id` natural-key 表把 `feishu_document` 的 source_id 标注为**飞书文档 token**（实体级）。二者分别指请求级与实体级 source_id，模块 docstring 有澄清，但表注释与请求约定字面相左；Phase 32 调度者若按表注释传 token 会使 `split(":",2)` 校验失败、静默返回空列表。
**Fix:** 在 `_NORMALIZERS` 注册处或 natural-key 表补一行注释，显式区分「feishu_document 请求 source_id = 工作项三元组锚；document 实体 source_id = doc token」，避免下游误接线。

---

_Reviewed: 2026-06-15T16:23:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
