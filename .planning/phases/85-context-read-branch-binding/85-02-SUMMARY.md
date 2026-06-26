# 85-02 SUMMARY — 项目上下文读侧 MCP 工具 + RetrievalTrace 两链 + members_only 零泄漏门

**Plan:** 85-02（Phase 85，里程碑 v0.16.0）
**Requirements:** CTX-01（读半：RAG / grep / file-read，任意来源可读）、CTX-02（MCP 链 RetrievalTrace）
**Status:** ✅ 完成（三工具落地 + 安全门 PASS）

## 交付物（新增/改动文件）

| 文件 | 改动 |
|------|------|
| `server/mcp_tools/views.py` | 新增 `_aget_project` / `_assert_project_readable` helper + 三视图 `SearchProjectContextView`(`search_project_context`)、`GrepProjectView`(`grep_project`)、`ReadProjectDocView`(`read_project_doc`) |
| `server/mcp_tools/serializers.py` | 新增 `SearchProjectContextRequestSerializer` / `GrepProjectRequestSerializer` / `ReadProjectDocRequestSerializer` + 3 个 `TOOL_SCHEMA_SNAPSHOT` 条目 |
| `server/mcp_tools/urls.py` | 注册 `tools/search_project_context/` / `tools/grep_project/` / `tools/read_project_doc/` 三路由 |
| `server/initiatives/services/project_search_service.py` | `_keyword_search` 扩 `ProjectDoc.last_synced_snapshot__icontains` 命中分支（`kind="project_doc"`，CTX-01 ProjectDoc 正文 grep 覆盖）；既有 work_item/state_api/artifact/memory 命中逐字不变 |
| `server/tests/mcp_tools/test_project_context_tools.py` | 净新：三工具 + members_only 零泄漏门 + visibility 对称 + 两链覆盖（17 用例） |
| `server/tests/mcp_tools/test_schema_snapshot.py` | 补 3 个工具 schema 快照 |
| `server/tests/knowledge/test_access_scope.py` | 补 members_only 零泄漏 / public_org 对称 / 成员可读 scope 断言（A3 live 校验留痕） |

## 工具能力（CTX-01 读半，任意来源：前端 AI 对话 / MCP / skills）

- `search_project_context`（RAG）：复用 `DeliveryKnowledgeSearchService.search_similar`，写 `RetrievalTrace`（`Kind.CHUNK`，payload `source=mcp_search_project_context` + 条数/scores/top_score + **`duration_ms`**）。
- `grep_project`（关键词 grep）：复用 `ProjectSearchService.search`（含新增 ProjectDoc 正文命中 + 记忆/工件/工作项 + `locator`）。分层耗时（`local_ms`/`knowledge_ms`）由 service 内部既有 trace 满足，view 不重复写。
- `read_project_doc`（file-read）：复用 `DocContentService.get_doc_render`（渲染 markdown + block 分区），写 `RetrievalTrace`（`Kind.FILE`，含 `block_count` + **`duration_ms`**）。doc 不存在/无权同形返回空文档（不泄漏存在性）。

## 是否修复 access_scope.py？——**否**（live 验证后判定无需）

Task 1 安全门 live 校验结论（A3 / Pitfall 2）：

- 召回 payload `project_id` = `entity.space_id`（85-01 normalizer 写入），与 `resolve_allowed_project_ids` 的 membership 维度（`SpaceMembership` → Space id）一致；`_public_org_project_ids` 返回 `initiatives.Project.id`。
- **members_only 对非成员零泄漏已成立**：非成员可读集合不含 members_only 项目的任何维度 id（membership 空 + members_only 不并入 public_org 集），`search_similar(user=非成员, project_ids=[members_only.id])` 经 caller-intersect 收窄即 `[]`（fail-closed，短路于 `allowed_projects` 空）。
- **未发现「按 Space 维度过滤导致 members_only 泄漏」**——该维度错配实际表现为「public_org 内容经 RAG 维度不匹配/成员经 project.id 反而召不到」的**完整性**问题，而非泄漏；且现有 `test_access_scope_includes_public_org_project` 锁定 public_org 返回 Project id 的契约。故**保持 `access_scope.py` 不变**（plan 明确：无泄漏则不改、仅加测试，不引入回归）。

**真正的读侧泄漏面**是 grep/read 两工具底层 service（`ProjectSearchService._keyword_search` / `DocContentService.get_doc_render`）按 `project_id` 直查 DB、**无 visibility 过滤**。因此在 **view 层叠加 `_assert_project_readable`** 作为单一可读口径（与 `pack_project_context` 同：成员任意 visibility 放行 / 非成员+public_org 放行 / 非成员+members_only 拒绝）。该口径按 `initiatives.Project.visibility` 精确判定（非 Space 维度），即便同 Space 含混合可见性项目也不泄漏（grep/read 按 `Project.id` 维度过滤正文）。

> 与 plan 字面建议（`_assert_project_readable` 用 `resolve_allowed_project_ids(user,[project.id])` 非空即可读）的偏差及理由：该建议存在 false-negative（成员经 `project.id` 因 Space 维度错配被拒），故改用 `ProjectMember` + `visibility` 精确判定（AI 对话链 packer 的权威口径），单一 helper 同时服务 grep/read，口径单一且正确。

## 测试结果

- `tests/mcp_tools/test_project_context_tools.py`（17）+ `tests/knowledge/test_access_scope.py`（10）+ `tests/mcp_tools/test_schema_snapshot.py`（1）= **28 passed**。
- 安全门（真实 PASS，非 xfail）：members_only 非成员经三工具一律零结果零正文；`search_similar` 维度零召回；public_org 非成员可读；成员任意 visibility 可读。
- 两链覆盖（CTX-02）：MCP 链（`mcp_search_project_context` trace）+ AI 对话链（`chat_project_context` trace）各落一条，`test_retrieval_trace_two_chains_covered` 断言。
- `tests/mcp_tools/` 全量：**1 failed, 137 passed**。
- ruff：`mcp_tools/` + `project_search_service.py` + 新增测试**全绿**（无新增 lint；access_scope.py 的 I001 为既有、本 plan 未改该文件）。

### 预先存在的失败（非本 plan 引入）

`tests/mcp_tools/test_lookup_project_by_branch.py::test_non_member_failclosed_empty_context` — 该用例建默认 `public_org` 项目却断言非成员 context 为空，与 WS-02「public_org 全员可读」相冲突（`test_chat_project_recall.py::test_bound_project_public_org_non_member_recall` 反向证明 public_org 非成员可召回）。已用 `git stash` 剔除本 plan 全部源改动后复跑确认**该用例在改动前即失败**，属遗留 stale 测试，不在本 plan 范围。

## 观测合规

- 三工具 RetrievalTrace 经 `arecord_retrieval_trace`（内置 `redact_for_ledger`），payload 仅记 id/计数/score/duration_ms，绝不存正文；RequestMetric `labels.call_source` 自动取 `tool_name`（无新增 §4.1 call_source）。
- `_record_agent_decision` + `_record`（ToolCallRecord + RequestMetric）绑触发用户（`_begin` → `begin_interaction_run`）。

## Deferred / 已知限制（非本 plan 范围）

- `recall_similar_chunks` 结构上仅召回 `WORK_ITEM/TECH_PLAN/CODE_CHANGE`，**不召回 `DOCUMENT`**（project_doc/project_memory 实体）。故 `search_project_context` 经真实向量召回目前对项目文档/记忆返回空（grep/file-read 两路不受影响，CTX-01 读半仍可用）。本属既有召回 kind 覆盖问题，扩 `_DEMAND_KINDS` 含 `DOCUMENT` 属独立改动，未在本 plan 触碰（避免 scope creep / 召回回归风险），建议后续 phase 评估。
- 同 Space 混合可见性下，RAG（`search_similar`）维度为 Space，public_org 内容对非成员经 RAG 可能欠召回（fail-closed 安全侧）；grep/read 不受影响（按 `Project.id` 精确）。
