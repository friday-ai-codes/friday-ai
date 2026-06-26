---
phase: 85-context-read-branch-binding
plan: 04
type: summary
requirements: [BIND-02, CTX-01]
status: done
---

# 85-04 Summary — lookup_project_by_branch 多绑定 + fail-soft 候选（含两处旗标修复）

## 范围

- **主任务 BIND-02**：扩展 MCP `lookup_project_by_branch`，在 work_item_id 反查之外叠加
  `ProjectBranch` 显式多绑定反查，两源合并去重；可选 `repository_id` 收窄跨仓同名分支；
  单命中召回 + 写 `RetrievalTrace`，多/无命中 fail-soft 返回候选（绝不抛、绝不阻断编码）。
- **修复 A（WS-02 对齐）**：原 `test_non_member_failclosed_empty_context`（CURSOR-01 v0.15.0）
  用默认 visibility 项目断言非成员 fail-closed，但 Phase 82 WS-02 后默认 `public_org`（非成员可读）。
  拆为两测：members_only + 非成员 → fail-closed 空 context；public_org + 非成员 → 可读非空。
  不弱化 members_only 真·fail-closed。
- **修复 B（CTX-01 RAG 完整性）**：`recall_similar_chunks` 仅召回 WORK_ITEM/TECH_PLAN/CODE_CHANGE，
  导致项目 DOCUMENT 实体（85-01 物化的 5 文件/记忆/工件）向量 RAG 返回空。新增
  `include_document_kind` 开关，仅项目上下文读路径（`search_project_context` + `pack_project_context`）
  把 DOCUMENT 纳入无仓库 demand 分路；权限仍由 `allowed_project_ids`/visibility 收口，无泄漏，
  不回归全局代码检索召回口径。

## 改动文件

| 文件 | 改动 |
|------|------|
| `server/mcp_tools/serializers.py` | `LookupProjectByBranchRequestSerializer` 新增可选 `repository_id`；`TOOL_SCHEMA_SNAPSHOT` 加 `repository_id`（请求/响应） |
| `server/mcp_tools/views.py` | `LookupProjectByBranchView` 新增 `_lookup_by_branch_binding`（按 branch_name[+repository_id] 查显式绑定）+ 两源合并去重 + `binding_source` 标记 + `repository_id` 回显；`SearchProjectContextView` 召回传 `include_document_kind=True`（CTX-01 调用位） |
| `server/knowledge/vector_recall.py` | `recall_similar_chunks` 新增 `include_document_kind`，True 时 demand 分路纳入 `DOCUMENT` |
| `server/knowledge/retrieval.py` | `DeliveryKnowledgeSearchService.search_similar` 透传 `include_document_kind` |
| `server/services/project_context_packer.py` | AI 对话链 `_layer_rag` 召回传 `include_document_kind=True`（CTX-01 第二条链） |
| `server/tests/mcp_tools/test_lookup_project_by_branch.py` | WS-02 stale 测试拆分对齐 + BIND-02 多绑定/合并去重/跨仓 fail-soft/repository_id 收窄/无命中守护测试 |
| `server/tests/mcp_tools/test_project_context_tools.py` | 新增 CTX-01 `search_project_context` 纳入 DOCUMENT 召回断言 |
| `server/tests/knowledge/test_vector_recall.py` | 新增 include_document_kind demand 分路含/不含 DOCUMENT 守护测试 |
| `server/tests/mcp_tools/test_schema_snapshot.py` | 快照同步 `repository_id` |

## 契约保持

- 既有输出键（`branch_name`/`work_item_id`/`matched`/`project`/`candidates`/`context`/`included_layers`/`run_id`）不变，新增 `repository_id`（回显）；Phase 86 消费契约不破坏。
- 召回经 `pack_project_context` 内置 fail-closed（非成员零召回），DOCUMENT 召回不绕过 visibility/access 闸。
- RetrievalTrace 复用 `mcp_lookup_project_by_branch` source，payload 增 `binding_source`（work_item/branch_binding/both）。

## 验证

- `uv run pytest tests/mcp_tools tests/initiatives tests/knowledge -q` → **689 passed, 1 deselected**。
- 含修复后的 stale 测试 + 新 BIND-02 + CTX-01 召回测试全绿。
- 仅修改文件 ruff 无新增 lint（既有 F401/I001 为历史遗留，未触及）。

## 遗留 / 说明

- `recall_similar_chunks` 的 DOCUMENT 召回仅作用于显式开启的项目上下文读路径；端到端向量命中依赖 Qdrant，单测以「filter 含 DOCUMENT + 透传 include_document_kind」+「search_project_context 返回物化文档命中」两层断言守护，不依赖真实向量库。
