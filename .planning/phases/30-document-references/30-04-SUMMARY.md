---
phase: 30-document-references
plan: 04
subsystem: delivery
tags: [django, delivery, rest, adrf, async, document, prd, snapshot, read-only, isauthenticated, inv-6, pytest-django, doc-02]

# Dependency graph
requires:
  - phase: 30-document-references
    plan: 01
    provides: Document/DocumentVersion 模型 + DocumentType 枚举（检索目标）
  - phase: 30-document-references
    plan: 02
    provides: DocumentService.upsert_from_feishu 单一写入入口（INV-6，测试夹具建 Document）
  - phase: 28-workitem-spine
    provides: delivery 最小 REST 范式（adrf APIView + IsAuthenticated + 三元组只读）
provides:
  - WorkItemPrdDocumentView —— 按三元组只读检索 WorkItem 的 PRD 正文快照（经 Document 实体）
  - DocumentSnapshotSerializer —— Document 元数据 + current_version 正文只读序列化
  - work-items/prd-document/ 路由
affects: [32 一键摄取（经 Document 路径摄取后可经此端点检索）, 34 文档反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "delivery 第四个只读端点：复用 WorkItemDetailView/WorkItemCommentTreeView 三元组校验 + afirst 命中已落库 + 404 范式"
    - "select_related('current_version') 预取防 async 隐式同步访问；序列化经 sync_to_async 桥接"
    - "同 work_item 多份同类型文档取 order_by('-updated_at').afirst()（最近更新一条）"
    - "可选 ?document_type= 复用同端点取技术方案等其他类型快照（默认 prd，非法值 400）"

key-files:
  created:
    - server/tests/delivery/test_document_api.py
  modified:
    - server/delivery/api/views.py
    - server/delivery/api/serializers.py
    - server/delivery/urls.py

key-decisions:
  - "serializer 全字段 read_only（落库只经 DocumentService，INV-6）；content/version 取自 current_version（None → \"\"/null，不臆造）"
  - "WorkItem 不存在与无对应 Document 均返回 404，但 detail 文案区分（明确语义，不泄漏存在性歧义）"
  - "支持可选 ?document_type= 复用端点（默认 prd），按 DocumentType.values 校验非法 400（实现 plan 可选项）"
  - "prd-document/ 路由置于通配 work-items/ detail 之前（字面段优先，沿用既有顺序）"

patterns-established:
  - "delivery 只读 REST 经独立操作态 Document 实体检索（相对 work_item 内联快照的独立可检索价值）"

requirements-completed: [DOC-02]

# Metrics
duration: ~12min
completed: 2026-06-15
---

# Phase 30 Plan 04: PRD 正文快照只读 REST Summary

**新增 `WorkItemPrdDocumentView`（adrf `APIView`，`IsAuthenticated`，async get）+ `DocumentSnapshotSerializer` + `work-items/prd-document/` 路由：给定带 `prd_url` 的 WorkItem（三元组），经独立操作态 `Document` 实体（`Document.objects.filter(work_item, document_type=prd).select_related("current_version").order_by("-updated_at").afirst()` → `current_version.content`）只读检索 PRD 正文快照——纯读已落库 Document，不旁路 fetch、不写表，兑现 DOC-02 成功标准 3。三元组校验、afirst 命中、404 语义沿用 28-03 既有 `WorkItemDetailView`/`WorkItemCommentTreeView` 范式；序列化全字段 read_only（INV-6），`content`/`version` 取自 `current_version`（缺 → `""`/null 不臆造）；支持可选 `?document_type=` 复用端点取其他类型快照（默认 prd，非法 400）。7 个检索守护测试全绿，delivery 套件 121 passed 无回归。**

## What Was Built

### Task 1: PRD 正文快照只读 REST 端点 + serializer + 路由

- `server/delivery/api/serializers.py`：新增 **`DocumentSnapshotSerializer`**（`ModelSerializer`，全字段 read_only）——暴露 `id / document_type / source_kind / content_storage / external_ref / canonical_url / feishu_tenant / last_synced_at` + `content`（`SerializerMethodField`，取 `obj.current_version.content`，None → `""`）+ `version`（`SerializerMethodField`，取 `obj.current_version.version`，None → null）。落库只经 `DocumentService`（INV-6）。
- `server/delivery/api/views.py`：新增 **`WorkItemPrdDocumentView(APIView)`**（`permission_classes=[IsAuthenticated]`，async get）：
  - 三元组 query params 校验（缺参 → 400 中文 detail；`work_item_id` 非整数 → 400），沿用既有 view 写法。
  - 可选 `?document_type=`（默认 `DocumentType.PRD`），非法值（不在 `DocumentType.values`）→ 400。
  - 查询路径（只读不旁路 fetch/不写表）：先按三元组 `afirst` 命中已落库 WorkItem；不存在 → 404「WorkItem 不存在」。
  - `Document.objects.filter(work_item, document_type=...).select_related("current_version").order_by("-updated_at").afirst()`（同 work_item 多份取最近更新一条；`select_related` 防 async 隐式同步访问 current_version）。
  - document 为 None → 404「该 WorkItem 暂无对应文档快照」（明确语义，不臆造空文档）。
  - 命中 → `payload = await sync_to_async(lambda: DocumentSnapshotSerializer(document).data)()`，200。
- `server/delivery/urls.py`：注册 `path("work-items/prd-document/", WorkItemPrdDocumentView.as_view(), name="work-item-prd-document")`，置于通配 `work-items/` detail 之前（字面段优先）。

### Task 2: PRD 快照检索守护测试

- `server/tests/delivery/test_document_api.py`（`django_db(transaction=True)`，pytest-socket 零真实网络，端点不回源故无 respx）：7 个测试覆盖
  - **命中**：force_authenticate（JWT Bearer）→ GET prd-document 三元组 → 200 + `content == "PRD 正文快照"` + `document_type=="prd"` + `content_storage=="both"` + `external_ref==DOC_TOKEN` + `feishu_tenant=="guanghe"` + `version==1`（经 Document 实体检索 PRD 正文，DOC-02 成功标准 3 端到端守护）。
  - **未认证**：匿名 GET → 401（IsAuthenticated，T-30-09）。
  - **参数**：缺三元组 → 400；`work_item_id` 非整数 → 400。
  - **未命中**：WorkItem 不存在 → 404；WorkItem 存在但未建 PRD Document → 404（明确语义，不返回空文档）。
  - **只读不写**（T-30-10）：请求前后 Document/DocumentVersion 行数不变。
  - Document 夹具经 `DocumentService().upsert_from_feishu(...)` 建（守 INV-6，不旁路 ORM 写 Document）；WorkItem 经 `acreate`（INV-6 仅约束 Document 写入）。

## Verification Results

- `pytest tests/delivery/test_document_api.py -q` → **7 passed**。
- `pytest tests/delivery/ -q` → **121 passed**（无回归，28/29/30-01/30-02 套件全绿）。
- `ruff format` + `ruff check delivery/api/views.py delivery/api/serializers.py delivery/urls.py tests/delivery/test_document_api.py` → 全部干净。
- 未改 knowledge app（INV-3）；未新增第三方依赖（T-30-SC accept）；Document 夹具经 DocumentService 建（不旁路 ORM 写）。

## Deviations from Plan

**1. [Rule 3 - 工具误操作回滚] `ruff format` 误传 `api/..` 参数全树重格式化已回滚**
- **Found during:** Task 1 ruff 步骤
- **Issue:** `uv run ruff format api/.. ...` 中 `api/..` 解析为 `server/` 全目录，误重格式化 794 个无关文件。
- **Fix:** 列出除本 plan 三文件外的全部受影响文件 `git checkout --` 回滚；随后只对本 plan 四文件跑 `ruff format`。最终 git 仅含本 plan 改动。
- **Files modified:** 无（误改全部回滚，本 plan 目标文件不受影响）。
- **Commit:** 回滚后再提交（558f9dcf / a0c7d16e 仅含本 plan 改动）。

实现层面计划按写法执行，无功能性偏差。

## Threat Surface

- T-30-09（未认证/越权读取）：`permission_classes=[IsAuthenticated]`，匿名 401（`test_unauthenticated_rejected` 守护）→ **mitigated**。
- T-30-10（经读端点旁路写表）：端点纯读（afirst/filter），serializer 全 read_only；只读不写测试守护（请求前后 Document/DocumentVersion 行数不变）；Document 写入 INV-6 grep 守护在 30-02 → **mitigated**。
- T-30-SC（依赖供应链）：无新增 npm/pip 包（adrf APIView + DRF serializer）→ **accept**（不触发包合法性门）。
- 无计划外新增安全相关 surface。

## Self-Check: PASSED

- FOUND: server/delivery/api/views.py (WorkItemPrdDocumentView)
- FOUND: server/delivery/api/serializers.py (DocumentSnapshotSerializer)
- FOUND: server/delivery/urls.py (work-items/prd-document/)
- FOUND: server/tests/delivery/test_document_api.py
- FOUND commit: 558f9dcf (Task 1: endpoint + serializer + route)
- FOUND commit: a0c7d16e (Task 2: guard tests)
