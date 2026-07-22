---
phase: 102-knowledge-consumption
verified: 2026-07-22T05:40:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "真实 Qdrant 环境端到端：IDE 调 report_project_state 上报 API 清单后，用 search_project_context 检索该 API 路径关键词"
    expected: "命中 STATE 文档 chunk，结果正文含「METHOD path — status」API 清单行"
    why_human: "CI 无 Qdrant，自动化测试的诚实边界是「物化内容包含 API 清单行」这一确定性环节（102-02-SUMMARY 明示）；向量入库→检索命中需真实向量库验证"
---

# Phase 102: 知识消费面与对外契约 Verification Report

**Phase Goal:** 统一知识库的消费面补齐——方案编排召回覆盖项目沉淀与历史经验，Chat 对话能主动读知识，IDE 上报的 API 清单可语义检索，对外工具契约（schema snapshot + `@friday-ai-codes/skills` 文档）与新行为完整对齐。
**Verified:** 2026-07-22T05:40:00Z（UTC）
**Status:** human_needed（自动化检查 4/4 全过；余 1 项需真实 Qdrant 环境人工验证）
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（ROADMAP 4 条 Success Criteria）

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 编排 recalling 召回 `document`+`learning_case`（可配置默认开、每 kind 限额守 token 预算），RetrievalTrace + 条数/耗时/score 埋点可见 | ✓ VERIFIED | `settings.py` L243-258 `PROCESS_RECALL_ENTITY_KINDS`（默认 5 kinds 含 document/learning_case，env 可覆盖）+ `PROCESS_RECALL_KIND_LIMITS`；`recall_adapter.py` L83-87 运行时读取、L112 `include_document_kind` 动态传参、L185-203 `_truncate_per_kind` 限额截断、L131-183 `_record_trace`（RetrievalTrace payload 含 kinds/result_count/per_kind_counts/scores/top_score/duration_ms + `process_recall_completed` 事件，整段 best-effort）；`entrypoint.py` L91 注入编排；`test_recall_adapter.py` 10 passed |
| 2 | Chat 经白名单三个薄封装工具主动读知识，权限 fail-closed | ✓ VERIFIED | `agents/tools/knowledge_read_tools.py`（330 行实体实现）：`search_learning_cases` 走 `_resolve_conversation_user` fail-closed（L127-129 user 为 None 直接拒绝）、`search_project_context`/`read_project_doc` 走 `_resolve_project_scope`+`_deny`（L202-204/L275-277）；全部转调真实 service（`learning_case_service.search_learning_cases`/`search_similar(include_document_kind=True, project_ids 收口)`/`DocContentService.get_doc_render`）+ Chat 链 RetrievalTrace（conversation_id、source=chat、best-effort）；`chat_runner.py` L41 import 注册、L120 挂 `_INDEXED_TOOL_NAMES`、L135-136 挂 `_PROJECT_READ_TOOL_NAMES`；`test_knowledge_read_tools.py` 全绿 + `test_chat_project_recall.py` 8 passed 无回归 |
| 3 | `report_project_state` 上报后 `search_project_context` 能命中 API 清单（STATE 物化路径入向量库） | ✓ VERIFIED（代码链）/ 端到端命中留人工 | `project_doc_service.py` L432-443 `upsert_state_api` 成功后查 STATE doc 并调 `_schedule_materialization`（断链修复）；`knowledge/sources/project_doc.py` L94-105 normalizer 对 STATE 文档直查 `ProjectStateApi` 表追加 live「METHOD path — status」行（上限 500、拼接后全文 `redact_secrets_in_text`）；`test_state_api_materialize_hook.py` + `test_project_doc_source.py` 全绿（断言到「摄取内容含 API 清单」确定性环节）；向量库命中环节 CI 无 Qdrant，转人工验证 |
| 4 | `TOOL_SCHEMA_SNAPSHOT` 覆盖全部注册工具 + 注册==snapshot 守卫绿 + skills 文档对齐 + skills-tools⊆snapshot grep 守卫绿 | ✓ VERIFIED | `serializers.py` L731-734 `report_project_state` 条目（request 4 字段/response 5 键，与 view 输出核实）；`test_schema_snapshot.py::test_registered_tools_match_snapshot` 双向差集断言（urls 路由名==snapshot 键集）；`test_skills_snapshot_guard.py` 反引号+动词前缀 token 抽取 ⊆ snapshot∪字段名允许集 + `test_skill_files_discovered` 防空跑假绿；`friday-memory/SKILL.md` L41 已改统一向量检索语义（hints 为增强/提权非收窄，「收窄范围」零残留）；`friday-code/SKILL.md` L21/L47 收录 `reverse_lookup_requirements` 反查路由；4 个守卫/快照测试全绿 |

**Score:** 4/4 truths verified（SC3 代码链全通，端到端向量命中为诚实边界内的人工项）

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/friday/settings.py` | PROCESS_RECALL 双配置项 | ✓ VERIFIED | L243-258，env.list/env.json 可覆盖 |
| `server/services/process_runtime/recall_adapter.py` | 可配置 kinds + 限额 + 埋点 | ✓ VERIFIED | 225 行实体实现，entrypoint.py L91 接线（WIRED） |
| `server/agents/tools/knowledge_read_tools.py` | 三个薄封装工具 | ✓ VERIFIED | 330 行，chat_runner import 注册 + 白名单挂载（WIRED） |
| `server/initiatives/services/project_doc_service.py` | upsert_state_api 物化钩子 | ✓ VERIFIED | L432-443（WIRED 到既有 `_schedule_materialization`） |
| `server/knowledge/sources/project_doc.py` | STATE normalizer live API 行 | ✓ VERIFIED | L94-105 直查表 + 脱敏（WIRED 到摄取管线） |
| `server/mcp_tools/serializers.py` | snapshot 30 键含 report_project_state | ✓ VERIFIED | L731-734 |
| `server/tests/mcp_tools/test_skills_snapshot_guard.py` | grep 守卫（新文件） | ✓ VERIFIED | 2 用例含防空跑断言 |
| `skills/skills/friday-memory/SKILL.md`、`friday-code/SKILL.md` | 文档对齐 | ✓ VERIFIED | 子模块提交 e804acf + 主仓指针 104fe3a1 |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| 编排 recalling stage | recall_adapter | `entrypoint.py` L91 `recall=DeliveryKnowledgeRecallAdapter()` | ✓ WIRED |
| recall_adapter | settings | recall() 内 `getattr(settings, ...)` 运行时读取 | ✓ WIRED |
| chat_runner 白名单 | 三工具 | L41 import 侧效应注册 + L120/L135-136 白名单常量 | ✓ WIRED |
| 三工具 | 既有 service | learning_case_service / search_similar / DocContentService 真实转调 | ✓ WIRED |
| upsert_state_api | STATE 物化 | `_schedule_materialization(doc_id)` L441 | ✓ WIRED |
| STATE normalizer | ProjectStateApi 表 | L98 直查 + L105 拼入摄取正文 | ✓ WIRED |
| snapshot | urls 注册 | 守卫测试双向差集断言 | ✓ WIRED |
| skills 文档 | snapshot | grep 守卫测试 | ✓ WIRED |

### Behavioral Spot-Checks（测试执行）

| Suite | Result | Status |
| --- | --- | --- |
| `tests/services/test_recall_adapter.py` + `tests/agents/tools/test_knowledge_read_tools.py` + `tests/initiatives/test_state_api_materialize_hook.py` + `tests/knowledge/test_project_doc_source.py` + `tests/mcp_tools/test_schema_snapshot.py` + `tests/mcp_tools/test_skills_snapshot_guard.py` | **31 passed** | ✓ PASS |
| `tests/test_chat_project_recall.py`（chat 白名单回归） | **8 passed** | ✓ PASS |

已知烂尾失败（`tests/knowledge/test_triggers.py` 3 项、`test_sub_step_coding_node.py::test_plan_generation_node_still_works`）不在本次执行范围内，未影响判定。并行 code-fixer 修改的 Phase 101 文件（skill_steps.py / tools/views.py 等）不属本 phase 范围，未纳入判定。

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| KNOW-04 编排召回扩容 | 102-01 | ✓ SATISFIED | SC1 证据链 |
| KNOW-05 Chat 知识读工具 | 102-02 | ✓ SATISFIED | SC2 证据链 |
| KNOW-06 ProjectStateApi 可检索 | 102-02 | ✓ SATISFIED（代码链） | SC3 证据链 |
| UNIFY-04 契约与文档对齐 | 102-03 | ✓ SATISFIED | SC4 证据链 |

### Anti-Patterns Found

无。8 个改动文件扫描 TBD/FIXME/XXX/placeholder/not-implemented：零命中。三份 SUMMARY 声称的提交（d4a0881d/f4561acd/676012fb/cdb7a253/19ff6302/0ce3c3de/b7cfc8cf/73c4dac6/65d5922e/104fe3a1 + skills@e804acf）全部存在。

### Human Verification Required

### 1. ProjectStateApi 端到端检索命中（真实 Qdrant）

**Test:** 起真实 Qdrant 环境，经 MCP `report_project_state` 上报若干 API（method/path/status），等待 STATE 文档物化摄取完成后，调 `search_project_context`（MCP 或 Chat 工具）以 API 路径关键词检索。
**Expected:** 命中 STATE 文档，结果正文含「METHOD path — status」清单行。
**Why human:** CI 无 Qdrant，自动化验收链止于「物化摄取内容包含 API 清单行」这一确定性环节（102-02-SUMMARY 声明的诚实边界）；向量入库与检索命中依赖真实向量库。

### Gaps Summary

无 gaps。4 条 Success Criteria 的代码证据全部落地且守卫/回归测试全绿；唯一余项是需要真实向量库的端到端命中人工验证（上表）。

---

_Verified: 2026-07-22T05:40:00Z_
_Verifier: Claude (gsd-verifier)_
