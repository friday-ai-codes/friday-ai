---
phase: 34-reverse-lookup
verified: 2026-06-15T14:50:00Z
status: human_needed
score: 11/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "真实图谱数据下的片段→需求反查端到端验收：在真实仓库 + 真实图谱边（MODIFIES_CHUNK/IMPLEMENTED_BY/HAS_PLAN/REFERENCES 由实际 diff 归档与方案/编码产出）上，调 GET /api/repositories/<id>/reverse-lookup/ 与 MCP reverse_lookup_requirements，确认反查到正确的 work_item/document 与多跳路径。"
    expected: "反查结果与真实图谱关联一致；被排除文件/失效边不泄漏；agent 可经 MCP 消费结构化结果。"
    why_human: "自动化测试用 factory-boy 在测试库构造图谱边覆盖链路语义；真实生产图谱数据的端到端关联正确性需人工对真实需求/代码核对（CONTEXT 已列为 human-UAT）。"
---

# Phase 34: 评论入图 + 片段→需求反查 Verification Report

**Phase Goal:** chunk/模块 → 反查关联需求/文档（find_chunk_at + graph reverse traverse）经 REST + MCP；评论入图（comments into work_item knowledge projection，可检索 + 关联 WorkItem）。RREF-01、RREF-02。复用既有 graph/chunk/retrieval；EntityKind locked；当前视图排除失效边。
**Verified:** 2026-06-15T14:50:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | (repo,file,line) 反查出多跳 work_item/document（chunk←code_change←tech_plan←work_item→document） | ✓ VERIFIED | `reverse_lookup.py:91-134` 逐跳 `chunk_in_edges`→`neighbors(IMPLEMENTED_BY,in)`→`neighbors(HAS_PLAN,in)`→`neighbors(REFERENCES,out)`；`test_reverse_lookup.py` 全链用例绿 |
| 2 | 默认当前视图：过期 MODIFIES_CHUNK 边不进反查结果（Phase 33 as-of） | ✓ VERIFIED | `graph_store.chunk_in_edges` `as_of=None` 过滤 `invalid_at__isnull=True, expired_at__isnull=True`（graph_store.py:301-302）；service 默认调用无 as_of；失效边排除用例绿 |
| 3 | 被排除文件 fail-closed 不泄漏（含 chunk_id 直接入参复判） | ✓ VERIFIED | `find_chunk_at` 路径 + `_resolve_chunk_by_id` 经 `build_matcher_for_repo`+`is_excluded` 复判返空（reverse_lookup.py:190-221）；排除用例绿 |
| 4 | 反查只读，绝不写库 | ✓ VERIFIED | `grep -cE 'add_edge\|invalidate_edge\|save\|upsert\|create'` = 0；纯读 grep 守护测试绿 |
| 5 | REST 端点（IsAuthenticated）返回 {chunks,related_work_items,related_documents,paths} | ✓ VERIFIED | `reverse_lookup_views.py` `IsAuthenticated` + 参数校验；urls.py:276 路由注册；7 REST 用例绿（含 401/403、400） |
| 6 | MCP 工具（已注册，AccessToken/CookieJWT + IsAuthenticated）同形结构化 | ✓ VERIFIED | `mcp_tools/views.py:1267` `tool_name=reverse_lookup_requirements`；serializer+urls+schema snapshot 四面齐；4 MCP 用例绿 |
| 7 | work_item 投影内容含当前评论树文本（评论入图），可被检索召回 | ✓ VERIFIED | `feishu_work_item.py:288-290` `_render_comment_section` 追加 `## 评论` 段；`test_feishu_work_item_comments.py` 内容含 body 用例绿 |
| 8 | 评论文本经既有检索召回并天然关联 WorkItem（不新增 EntityKind） | ✓ VERIFIED | `test_comment_reprojection.py` 端到端 content 含评论子串 + source_id==triple 关联断言绿；`grep '= "comment"' models.py` = 0（EntityKind locked） |
| 9 | 评论事件新增后触发 work_item 快照重投影 | ✓ VERIFIED | `comment_event_service.py:104-128` `created_count>0` 触发 `aschedule_ingestion(source_kind=feishu_work_item, trigger=comment_event_appended)`；触发 + 幂等用例绿 |
| 10 | 评论投影缺料/失败 → 缺段 + warning，不抛不回滚（缺段不缺实体） | ✓ VERIFIED | `feishu_work_item.py:282-296` try/except → `knowledge_normalize_comments_unavailable` warning；无 WorkItem/无评论降级用例绿 |
| 11 | hash-no-version：评论无变化时 content 一致、hash 相等、不翻版本 | ✓ VERIFIED | 确定性渲染严格按 `project_comment_tree` 排序；`test_content_deterministic_across_normalize` 绿 |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/services/reverse_lookup.py` | 反查 service（复用 find_chunk_at + graph_store，纯读） | ✓ VERIFIED | `async def reverse_lookup` 存在、实质实现、被 REST/MCP 双面 import |
| `server/repositories/reverse_lookup_views.py` | ReverseLookupView REST | ✓ VERIFIED | `class ReverseLookupView` + IsAuthenticated；urls.py 路由 wired |
| `server/mcp_tools/views.py` | MCP 工具 reverse_lookup_requirements | ✓ VERIFIED | `class ReverseLookupView(McpToolView)` tool_name 正确；urls.py:40 注册 |
| `server/knowledge/sources/feishu_work_item.py` | work_item 投影并入评论树段 | ✓ VERIFIED | `_resolve_work_item`/`_render_comment_section`/`aproject_comment_tree` wired，`## 评论` 段追加 |
| `server/delivery/services/comment_event_service.py` | append_events 触发重投影 | ✓ VERIFIED | `_schedule_work_item_reprojection` 调 `aschedule_ingestion`，惰性 import + best-effort |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| reverse_lookup.py | services.chunk_lookup.find_chunk_at | fail-closed chunk 定位 | ✓ WIRED |
| reverse_lookup.py | knowledge.graph_store | chunk_in_edges + neighbors 反向多跳 | ✓ WIRED |
| repositories/urls.py | ReverseLookupView | reverse-lookup/ 路由（UUID 通配后） | ✓ WIRED |
| mcp_tools/urls.py | mcp_tools.views.ReverseLookupView | tools/reverse_lookup_requirements/ | ✓ WIRED |
| feishu_work_item.py | delivery.services.aproject_comment_tree | 评论树并入快照 content | ✓ WIRED |
| comment_event_service.py | knowledge.ingestion.aschedule_ingestion | created_count>0 触发重投影 | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 反查/评论入图全部守护用例 | `pytest tests/services/test_reverse_lookup.py tests/repositories/test_reverse_lookup_view.py tests/mcp_tools/test_reverse_lookup_tool.py tests/knowledge/test_feishu_work_item_comments.py tests/knowledge/test_comment_reprojection.py -q` | 28 passed in 10.00s | ✓ PASS |
| 无新 model / migration | `python manage.py makemigrations --check --dry-run` | No changes detected (exit 0) | ✓ PASS |
| 纯读纪律 | `grep -cE 'add_edge\|invalidate_edge\|save\|upsert\|create' services/reverse_lookup.py` | 0 | ✓ PASS |
| EntityKind locked | `grep -cE '= "comment"' knowledge/models.py` | 0 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| RREF-01 | 34-01 | 片段→需求反查 API/MCP（依赖 v0.5 行号回填） | ✓ SATISFIED | service + REST + MCP 全面交付，truths 1-6 verified；REQUIREMENTS.md 标记 Complete |
| RREF-02 | 34-02 | 评论摄取进知识投影，可被检索关联到 WorkItem | ✓ SATISFIED | 评论段并入 work_item 投影 + 重投影触发，truths 7-11 verified；REQUIREMENTS.md 标记 Complete |

### Anti-Patterns Found

无。service 纯读 grep == 0；无 stub/placeholder/未实现标记；降级路径以 warning 显式处理而非吞错。

### Human Verification Required

#### 1. 真实图谱数据下的片段→需求反查端到端验收

**Test:** 在真实仓库 + 真实图谱边上，调 `GET /api/repositories/<id>/reverse-lookup/?path=&line=` 与 MCP `reverse_lookup_requirements`，核对反查到的 work_item/document 与多跳路径是否与真实需求/代码关联一致。
**Expected:** 反查结果正确；被排除文件/失效边不泄漏；agent 可经 MCP 消费结构化结果。
**Why human:** 自动化测试在测试库用 factory-boy 构造图谱边覆盖链路语义；真实生产图谱数据的关联正确性需人工对真实需求/代码核对（CONTEXT 明列 human-UAT 延后项）。

### Gaps Summary

无 gap。两个 plan 的全部 11 条 must-have truths 经代码 + 28 个守护用例 + 静态 grep 守护验证通过；RREF-01/RREF-02 均满足；无新 model/migration，EntityKind 锁定保持，纯读纪律达成。唯一遗留为真实生产图谱数据下的端到端反查人工验收（CONTEXT 已声明为 human-UAT），故状态为 human_needed 而非 passed——自动化层面全绿。

> 备注：`tests/knowledge/test_triggers.py::test_coding_chat_pr_created_branch_delivers_once` 为预存且与本 phase 无关的失败，未纳入本相位计分（按指示忽略）。

---

_Verified: 2026-06-15T14:50:00Z_
_Verifier: Claude (gsd-verifier)_
