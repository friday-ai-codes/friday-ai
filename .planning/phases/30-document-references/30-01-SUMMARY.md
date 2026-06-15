---
phase: 30-document-references
plan: 01
subsystem: database
tags: [django, delivery, document, version-chain, models, migration, uuid, unique-together, pytest-django]

# Dependency graph
requires:
  - phase: 28-workitem-spine
    provides: canonical WorkItem 模型（Document.work_item FK 关联脊柱 + REFERENCES 操作态对应）
provides:
  - Document 操作态实体（区分 external_feishu/internal_generated + document_type 五值 + content_storage 三值）
  - DocumentVersion 版本链（supersedes self FK + unique_together(document, version)）
  - DocumentType/DocumentSourceKind/ContentStorage 三枚举
  - delivery 0004 migration（已 migrate，建出 delivery_document / delivery_document_version 两表）
affects: [30-02 DocumentService 落库, 30-03 feishu_document normalizer, 30-04 PRD 快照检索, 32 一键摄取, 34 文档反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Document 操作态实体落 delivery app（与 WorkItem 脊柱同 app，DOMAIN §0）"
    - "版本链 = supersedes self FK(SET_NULL) + unique_together(document, version)，沿用 knowledge 版本化范式"
    - "current_version 前向字符串 FK + related_name='+'，SET_NULL 避免删版本抹 Document"
    - "本 plan 仅建表与枚举，无 create/save 业务逻辑（落库归 30-02 service，守 INV-6）"

key-files:
  created:
    - server/delivery/models/document.py
    - server/delivery/migrations/0004_document_documentversion.py
    - server/tests/delivery/test_document_models.py
  modified:
    - server/delivery/models/__init__.py

key-decisions:
  - "Document/DocumentVersion 逐字段对齐 DOMAIN §3/§12.5（字面值锁定，不增不改）；三枚举值与中文标签对齐 §3"
  - "DocumentVersion.supersedes 用 self FK + SET_NULL（与 §12.5 supersedes FK(self,null) 对齐），unique_together(document, version) 在 DB 层强制版本唯一（T-30-01）"
  - "Document.current_version on_delete=SET_NULL + related_name='+'（避免与 versions 反查名冲突）；work_item on_delete=SET_NULL + related_name='documents'"
  - "canonical_url 沿用 WorkItem.prd_url 的 max_length=1000（自托管/多租户深链可超默认 200）"
  - "迁移文件重命名为 0004_document_documentversion.py（去除 Django 自动追加的长后缀），makemigrations --check 仍干净"

patterns-established:
  - "delivery 操作态文档实体不 import knowledge.models（守 INV-3：knowledge 是投影，Document 操作态在 delivery）"

requirements-completed: [DOC-01]

# Metrics
duration: ~10min
completed: 2026-06-15
---

# Phase 30 Plan 01: Document + DocumentVersion 模型 Summary

**新增 `Document` / `DocumentVersion` 两个操作态实体落 delivery app，逐字段对齐 DOMAIN §3/§12.5：区分外部飞书文档与内部生成文档（document_type/source_kind/content_storage 三枚举），版本链经 supersedes self FK + unique_together(document, version)，work_item FK 关联脊柱；0004 迁移已 migrate 建出两表，7 个模型单测全绿，delivery 套件 101 个无回归。**

## What Was Built

### Task 1: Document/DocumentVersion 模型 + 枚举 + 包 re-export

- `server/delivery/models/document.py`：
  - **三枚举**：`DocumentType`（prd|tech_plan|release_note|sdd_spec|other）、`DocumentSourceKind`（external_feishu|internal_generated）、`ContentStorage`（snapshot|reference|both），值与中文标签对齐 DOMAIN §3。
  - **`Document`**（db_table=`delivery_document`）：document_type/source_kind/external_ref/canonical_url(1000)/content_storage(default=both)/current_version FK(SET_NULL, related_name='+')/last_synced_at/writeback_allowed/work_item FK(SET_NULL, related_name='documents')/feishu_tenant/created_at/updated_at。两索引：`(work_item, document_type)`（30-04 PRD 检索）、`(feishu_tenant, external_ref)`（30-02 去重定位）。
  - **`DocumentVersion`**（db_table=`delivery_document_version`）：document FK(CASCADE, related_name='versions')/version(PositiveInt)/supersedes self FK(SET_NULL, related_name='superseded_by')/content/content_hash(64)/created_at。`unique_together(document, version)` + 索引 `(document, -version)`。
  - 模型层无 create/save/upsert 业务方法（落库归 30-02，守 INV-6）。
- `server/delivery/models/__init__.py`：追加 curated re-export（Document/DocumentVersion/DocumentType/DocumentSourceKind/ContentStorage）。

### Task 2 [BLOCKING]: 0004 迁移 + 模型层单测

- `server/delivery/migrations/0004_document_documentversion.py`：dependencies 指向 `0003_workitemcommentevent_uniq_comment_event_anchor`，建两表 + unique_together + 三索引。`makemigrations --check --dry-run` → No changes detected；`migrate delivery` 应用 OK；DB 实际建出 `delivery_document` / `delivery_document_version`。
- `server/tests/delivery/test_document_models.py`：7 个测试覆盖字段读回、current_version 指向、unique_together(document, version) 抛 IntegrityError、supersedes 自引用版本链、work_item FK 反查 + None 占位、current_version on_delete=SET_NULL（删版本后 Document 保留、置 None）。

## Verification Results

- `makemigrations delivery --check --dry-run` → **No changes detected**（迁移就绪、干净）。
- `migrate delivery` → 应用 0004 OK，两表建出（introspection 确认 `True True`）。
- `pytest tests/delivery/test_document_models.py -x -q` → **7 passed**。
- `pytest tests/delivery/ -q` → **101 passed**（无回归）。
- `ruff format --check` + `ruff check delivery/ tests/delivery/test_document_models.py` → 全部干净。
- delivery 未 import knowledge.models（INV-3，既有 test_inv6_guard.py 覆盖）；无新增第三方依赖（T-30-SC accept）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 迁移文件重命名**
- **Found during:** Task 2
- **Issue:** Django `makemigrations` 自动生成的迁移名为 `0004_document_documentversion_document_current_version_and_more.py`，与 plan 指定的 `0004_document_documentversion.py` 不一致。
- **Fix:** `git mv` 重命名为 plan 指定名；重命名后 `makemigrations --check` 仍 No changes detected、`migrate` 正常应用。
- **Files modified:** server/delivery/migrations/0004_document_documentversion.py
- **Commit:** f9160e7e

**2. [Rule 3 - Blocking] 生成迁移 import 块 ruff I001**
- **Found during:** Task 2
- **Issue:** 自动生成迁移的 import 顺序触发 ruff I001（`import uuid` 位置）。
- **Fix:** `ruff check --fix` + `ruff format` 规范化（plan action 已预期此收尾步骤）。
- **Commit:** f9160e7e

## Threat Surface

- T-30-01（DocumentVersion 重复版本号）：`unique_together(document, version)` DB 层强制，模型单测 `test_document_version_unique_together` 守护 → **mitigated**。
- T-30-02（旁路写 Document 表）：本 plan 仅建表无写入路径，INV-6 写入收口归 30-02 → accept（按计划）。
- T-30-SC（依赖供应链）：无新增包 → accept（不触发包合法性门）。
- 无计划外新增安全相关 surface（建表，写入路径未开放）。

## Self-Check: PASSED

- FOUND: server/delivery/models/document.py
- FOUND: server/delivery/models/__init__.py
- FOUND: server/delivery/migrations/0004_document_documentversion.py
- FOUND: server/tests/delivery/test_document_models.py
- FOUND commit: 75c89178 (Task 1: models + enums)
- FOUND commit: f9160e7e (Task 2: migration + tests)
