# 86-01 SUMMARY — IDE hook 写路径 active 直写（HOOK-02）

**Plan:** 86-01（Phase 86 IDE 上下文闭环，milestone v0.16.0）
**Status:** ✅ Done — 全部测试通过
**Deviation:** 用户授权 accepted deviation（2026-06-26）—— stop hook active 直写生效（不落 draft）。

## 落地内容

实现 HOOK-02 写路径的**用户授权范围变更**：stop hook 经 MCP `report_project_knowledge`
以 **active 模式**调用时，MEMORY/RESEARCH **直接写入生效（active）不经 draft 人工确认**。
覆盖 REQUIREMENTS HOOK-02「落 draft 人工确认」与 Out-of-Scope「记忆全自动写入本期不做」。

### 四道兜底（绝不绕过）

1. **质量门槛**：复用 `evaluate_writeback_quality`（低质/空/重复拒收，distill 后内容再过一遍）。
2. **脱敏不可绕过**：复用 `append` / `redact_secrets_in_text`，入库内容天然脱敏。
3. **成员校验静默跳过**：非成员 / 未认证 / 未绑项目 → `applied=False` / `accepted=false` 200，
   绝不抛、绝不阻断编码（区别于 draft 路径的 403 fail-closed）。
4. **审计可回滚**：每次写入 emit AuditEvent（MEMORY=`project.memory_created` + 初始 revision；
   RESEARCH=`project.research_note_appended`），撤销经 `supersede` / 人工编辑。

归因：`request.user` → `initiated_by_user_id`；未提供取 contributor.id，仍无 → `system`。
全程 fail-soft：active 路径任何异常 → `accepted=false` 200，绝不 5xx。draft 默认路径
（CURSOR-03）逐字不回退。

## Files modified

| 文件 | 改动 |
|------|------|
| `server/initiatives/services/memory_service.py` | 新增 `record_hook_writeback`（active 直写 + 非成员静默跳过 + 复用 append 脱敏/审计/物化）|
| `server/initiatives/services/project_doc_service.py` | 新增 `append_research_note`（RESEARCH `last_synced_snapshot` append-only + 审计 + 成员判定 helper）|
| `server/initiatives/services/memory_distill.py` | 新增 `distill_hook_writeback`（call_source=ide_hook_distill，best-effort）；`_acall_llm`/`_record_usage` 泛化 prompt/call_source |
| `server/mcp_tools/views.py` | `ReportProjectKnowledgeView.post` 增 active 写回分支（`_handle_active_writeback` + `_maybe_distill`，fail-soft 包裹）|
| `server/mcp_tools/serializers.py` | `ReportProjectKnowledgeRequestSerializer` 新增可选 `writeback_mode`/`target`/`distill` |
| `server/agents/call_source.py` | 新增 `CallSource.IDE_HOOK_DISTILL`（枚举 23→24）|
| `server/audit/services/taxonomy.py` | 新增 `ACTION_PROJECT_RESEARCH_NOTE_APPENDED`（`project.research_note_appended`）|
| `.planning/observability/LOGGING-SPEC.md` | §4.1 新增 `ide_hook_distill` 行 |
| `server/tests/test_model_usage_call_source.py` | call_source 基线 23→24（含 `ide_hook_distill`）|
| `server/tests/initiatives/test_memory_hook_writeback.py` | 新增 Task 1 服务层守护测试 |
| `server/tests/mcp_tools/test_report_project_knowledge.py` | 扩充 active 模式守护测试 |

## call_source

✅ 新增 `ide_hook_distill`（LOGGING-SPEC §4.1 + `CallSource` 枚举），基线测试 23→24（已 bump）。

## Tests

`uv run pytest tests/initiatives/test_memory_hook_writeback.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_memory_distill.py tests/test_model_usage_call_source.py tests/initiatives/test_memory_inv6_guard.py tests/initiatives/test_project_doc_inv6_guard.py tests/audit/test_audit_taxonomy.py -q`
→ **58 passed**。`ruff check` 无新增 lint。

INV-6 守护通过：MEMORY 写经 `MemoryService.append`、RESEARCH/ProjectDoc 写经
`ProjectDocService`，无旁路写表。

## Deviation note for VERIFICATION

- **accepted deviation（2026-06-26）**：active 直写覆盖 HOOK-02「落 draft」+ Out-of-Scope。
  已在 `MemoryService.record_hook_writeback` / `ProjectDocService.append_research_note` /
  `ReportProjectKnowledgeView` docstring 标注。
- 四道兜底齐备（质量门槛 / 脱敏 / 成员静默跳过 / 审计可回滚），均有守护测试。
- 注意：「未认证 active→200」为代码侧纵深防御（`is_authenticated` guard）；实际未带 PAT
  请求在 `McpToolView`（IsAuthenticated）层即 401，故未对该分支单测（框架契约决定）。

## 范围边界

- 仅服务端写回逻辑（HOOK-02）。stop hook 客户端脚本资产留 86-05。
- distill LLM 为可选直透（`distill=True` 时启用），默认关闭。
