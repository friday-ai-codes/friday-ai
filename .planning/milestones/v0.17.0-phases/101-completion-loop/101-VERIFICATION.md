---
phase: 101-completion-loop
verified: 2026-07-22T05:20:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:

  - test: "真实飞书回写：跑一次带 write_back=True 且绑定工作项的 ai_coding 工作流（或 MCP execute_work_item），确认飞书工作项出现『Friday 已更新执行结果：{title}』评论且表格格式正确"
    expected: "工作项评论区出现结构化结果评论；MCP 链路文档同时 append『## 执行结果』表格"
    why_human: "需要真实飞书租户凭证与外部 API，测试全部 mock 飞书客户端"

  - test: "真实 LLM 提炼质量：编码任务成功完成后检查自动产生的 learning case 内容（problem/root_cause/solution 是否为可复用经验而非任务日志），并观察 learning_case_rejected 事件占比"
    expected: "case 内容有信息量、可检索复用；REJECT 率不失控（质量门有效但不误杀）"
    why_human: "LLM 产物质量无法程序化断言；测试仅 mock _acall_llm 返回固定 JSON"

  - test: "统一检索可见性：自动提炼的 case 经 Phase 100 入图通路后，在知识检索（search_learning_cases / 编排召回）中可命中"
    expected: "以 case 关键词检索能召回该条 learning case"
    why_human: "需真实 Qdrant + embedding 环境端到端跑通；测试只断言 aschedule_ingestion 被正确调用"

  - test: "PR review 沉淀（可选）：打开 learning_case.pr_review_enabled 后建一次 PR，确认产生 outcome=review 的 learning case 且 ModelUsageRecord 出现 call_source=pr_review_capture 记录"
    expected: "一条 review case 入库（幂等键 {sid}:pr_review）；用量可按 source 聚合"
    why_human: "依赖真实 LLM 与 git 平台 diff"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 101: 完工沉淀闭环（公共回写 + 自动提炼 + Skill 种子）Verification Report

**Phase Goal:** 任一链路（工作流 / Chat / MCP）编码完成后业务侧一致可见、经验自动沉淀——飞书回写抽为公共 service 三链路统一接入，编码成功完成自动提炼 learning case 入统一知识库，平台内置编码前调研与完工沉淀两个多步 Skill，PR 后可选轻量 review 沉淀。
**Verified:** 2026-07-22T05:20:00Z（UTC）
**Status:** human_needed（自动化验证全过，存外部依赖项待人工确认）
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（= ROADMAP 5 条 Success Criteria）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | workflow `ai_coding` MR 后飞书评论回写（与 MCP 同格式）+ chat 建 PR 后能反查三元组即回写 + MCP 薄包装零回归（write_back 开关/retry_state） | ✓ VERIFIED | 公共 service `server/delivery/services/coding_completion.py`（360 行，模板逐字迁移 L162-200）；workflow 锚点 `workflows/nodes/ai/coding.py` L1303→`_run_completion_loop` L1361-1480 调 `awrite_back`；chat 锚点 `orchestration/coding_graph.py` L561-679（PR 成功分支 L791 `write_back=True`、skip-PR L734 `False`）；MCP 薄包装 `mcp_tools/work_item_execution_service.py` L479-536（PARTIAL 翻转 + `failed_stage="execution_writeback"` L520-527 逐字保留）。测试：`tests/delivery/test_coding_completion.py` + `tests/mcp_tools/test_work_item_execution.py`（含 write_back True/False 两态既有断言零改动）全绿 |
| 2 | 存量工作流零行为变化（fallback 守门用例 + 升级说明）+ `writeback_skipped`/`writeback_failed` 事件不重试轰炸 | ✓ VERIFIED | 三态守门 `coding.py` L1422-1437（键缺失+无 triple → debug 静默零噪音）；守门用例 `tests/workflows/test_coding_writeback.py` 6 用例（含 `test_legacy_config_without_key_and_no_triple_is_zero_change`、`test_explicit_true_without_triple_logs_writeback_skipped`）全绿；事件 `coding_completion.py` L273-281/L313-324 带 category/component/initiated_by_user_id，单次调用整体 try/except 兜底（L338-359）无任何重试循环；升级说明 `docs/guide/workflows.md` L162-165 warning 块 |
| 3 | 编码成功自动产至多一条 learning case（幂等 source_session_id）+ 失败/取消不产 case + REJECT 路径计数 + kill switch 秒关 | ✓ VERIFIED | 管线 `mcp_tools/learning_case_extraction.py` L203-251：kill switch（`LEARNING_CASE_AUTO_EXTRACT` default=True，L204）→ 状态门（`_SUCCESS_STATUSES={"completed"}` L53/L210）→ 幂等查重（L215，先于 LLM 不烧 token）→ REJECT（`learning_case_rejected` warning 事件 L359-368 不入库）；幂等键 migration `mcp_tools/migrations/0011`（`source_session_id` unique + run FK 放松）；三链路调度接线（workflow L1470-1480 / chat L648 / MCP L597-613 均 `run_in_background`）；`tests/mcp_tools/test_learning_case_extraction.py` 五路全绿（开关关零 LLM 调用/状态门/幂等重入单条/REJECT 事件断言/成功路径含脱敏与入图断言） |
| 4 | `pre_coding_research`/`post_coding_capture` 两个 Skill 在 `/api/tools/execute/` 可调 + 步级 trace 完整 + PR review 沉淀默认关 | ✓ VERIFIED | 种子 migration `tools/migrations/0005_seed_platform_skills.py`（L148/L169 两个 SKILL + 7 个 builtin 步骤）；步级 trace `tools/sources/skill.py`（`skill_step_started/completed/failed` 三态事件 L55-90 + run 非 None 逐步 `arecord_tool_call` L94-99）；`tools/views.py` L61 传 run；`tests/tools/test_platform_skills.py` 5 用例全绿（含 PAT 端到端 `/api/tools/execute/` 调 pre_coding_research → 4 条步级记录）；`pr_review_capture.py` 开关默认关（L85 `default=False`），双锚点调度前置开关检查（coding.py L1502 / coding_graph.py L670），`tests/mcp_tools/test_pr_review_capture.py` 5 用例全绿（含开关关零成本断言） |
| 5 | 新 call_source 登记 LOGGING-SPEC §4.1 + ModelUsageRecord 可按 source 聚合 + 事件带 initiated_by_user_id | ✓ VERIFIED | `agents/call_source.py` L100/L103 `LEARNING_CASE_EXTRACTION`/`PR_REVIEW_CAPTURE`（枚举 35 值，导入实测确认）+ L97 补登 `feature_list_parse`；`LOGGING-SPEC.md` §4.1 L100-102 三行登记；两个 LLM 调用点均 `use_call_source` + `arecord_llm_usage` 成功/异常双路（extraction L461/L527、review L258/L329）；枚举守卫 `tests/test_model_usage_call_source.py` 全绿；回写/沉淀事件全部带 `initiated_by_user_id`（无则 "system"，coding_completion.py L244、learning_case_extraction.py L342/L367）；commit 顺序 32ef4eec（登记）先于 51c7152c（提炼代码），"先登记再写代码"成立 |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/delivery/services/coding_completion.py` | 公共回写 service + 三元组反查器 | ✓ VERIFIED | 360 行；`RepoResult`/`WorkItemTriple`/`awrite_back`/两个 resolver；与 MCP 模型零耦合 |
| `server/mcp_tools/learning_case_extraction.py` | 提炼管线 + `aextract_for_session` + `apersist_extracted_case` | ✓ VERIFIED | 541 行；导入实测 OK |
| `server/mcp_tools/pr_review_capture.py` | LOOP-05 review 沉淀 | ✓ VERIFIED | `REVIEW_SYSTEM_PROMPT` 只 import（L233）；复用 `apersist_extracted_case` |
| `server/mcp_tools/migrations/0011_learningcase_auto_extract.py` | run FK 放松 + source_session_id unique | ✓ VERIFIED | `makemigrations --check` 无缺失 |
| `server/tools/migrations/0005_seed_platform_skills.py` | 2 SKILL + 7 builtin 种子 | ✓ VERIFIED | get_or_create 幂等 + reverse |
| `server/tools/handlers/skill_steps.py` | 7 个步骤 handler | ✓ VERIFIED | 全部委托既有 service，权限主体 fail-closed |
| `server/tools/sources/skill.py` | 步级 trace | ✓ VERIFIED | 三态事件 + 逐步 ToolCallRecord |
| `web/src/types/workflow/schemas.ts` | 前端 write_back 同步 | ✓ VERIFIED | L296 `write_back: z.boolean().default(true)` |
| `docs/guide/workflows.md` | 升级说明 | ✓ VERIFIED | L162-165 配置行 + warning 块 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `coding.py _finalize_and_notify` | `CompletionWritebackService.awrite_back` | L1303 → `_run_completion_loop` L1457 | ✓ WIRED | 三态守门后调用，space_id/initiated_by_user_id 透传 |
| `coding_graph.py create_pr_or_skip_node` | `awrite_back` + `aextract_for_session` | L791/L734 → `_run_completion_loop` L619/L648 | ✓ WIRED | PR 成功回写、skip-PR 只提炼 |
| MCP `_write_results_back` | `CompletionWritebackService` | L501 薄委托 | ✓ WIRED | retry_state 语义留在 MCP 层 |
| MCP `execute_work_item_repo_tasks` | `aextract_for_session` | L597-613 `run_in_background` | ✓ WIRED | 仅 COMPLETED 且有 session |
| `pr_review_capture.py` | `apersist_extracted_case` | L37 import / L145 调用 | ✓ WIRED | 走 LOOP-03 质量门/幂等/入库路径 |
| `skill.py` | `arecord_tool_call` | L96-99 | ✓ WIRED | `{skill}#{i}:{step}` 命名 |
| `views.py /api/tools/execute/` | `execute_tool(run=run)` | L61 | ✓ WIRED | 端到端测试驱动验证 |
| 提炼入库 | Phase 100 入图 | `aschedule_ingestion("learning_case", ...)` L329 | ✓ WIRED | 测试断言调用参数含 initiated_by_user_id |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 全部新模块可导入 + 枚举 35 值 | `python -c "import ..."` | imports OK, 35 | ✓ PASS |
| 无缺失 migration | `manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |
| Phase 101 目标测试 | `pytest`（9 个测试文件） | **76 passed** | ✓ PASS |
| 回归宿主（coding graph/node/wave/e2e/events/sub_step） | `pytest`（6 个文件） | 73 passed, 1 xfailed, 1 failed（已知腐坏 `test_plan_generation_node_still_works`，引用不存在模块，deferred-items 在案，与本 phase 无关） | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|------------|--------|----------|
| LOOP-01 公共回写 service + MCP 薄包装 | 101-01 | ✓ SATISFIED | Truth 1 |
| LOOP-02 workflow/chat 锚点 + 存量 fallback | 101-03 | ✓ SATISFIED | Truth 1/2 |
| LOOP-03 自动提炼（幂等/质量门/开关） | 101-02/03 | ✓ SATISFIED | Truth 3 |
| LOOP-04 平台 Skill 种子 + 步级 trace | 101-04 | ✓ SATISFIED | Truth 4 |
| LOOP-05 PR review 可选沉淀（默认关） | 101-04 | ✓ SATISFIED | Truth 4 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `mcp_tools/learning_case_extraction.py` | 57 | `"TODO"` 字面量 | ℹ️ Info | 非债务标记——是质量门的去模板断言前缀常量（`_TEMPLATE_PREFIXES`），属功能实现 |

无 TBD/FIXME/XXX 债务标记；无空实现/占位 stub。

**已知设计态 seam（非 gap）：** chat 链反查键 `ArtifactVersion.content.chat_coding_plan_id` 当前无生产写入方，生产 chat 回写恒走"反查不到自然跳过"——这是 101-03 plan 锁定的零行为变化设计（禁止重新引入 chat→delivery eager 投影），成功标准 1 的措辞本身是条件式（"若能反查到……同样回写"），正向路径由测试构造 content 埋键驱动验证（`test_coding_graph_completion.py` PR成功+triple 用例）。点亮条件已写入 resolver docstring。

### Human Verification Required

#### 1. 真实飞书回写

**Test:** 跑一次带 write_back=True 且绑定工作项的 ai_coding 工作流（或 MCP execute_work_item），查看飞书工作项评论区。
**Expected:** 出现「Friday 已更新执行结果：{title}」评论 + 仓库状态列表；MCP 链路文档同时 append「## 执行结果」表格。
**Why human:** 需真实飞书租户与外部 API；测试全部 mock 飞书客户端。

#### 2. 真实 LLM 提炼质量

**Test:** 编码任务成功完成后检查自动 learning case 内容与 `learning_case_rejected` 事件占比。
**Expected:** case 为可复用经验而非任务日志；REJECT 率不失控。
**Why human:** LLM 产物质量无法程序化断言。

#### 3. 统一检索可见性（端到端）

**Test:** 自动提炼 case 入图后用关键词检索（search_learning_cases / 编排召回）。
**Expected:** 能召回该条 case。
**Why human:** 需真实 Qdrant + embedding 环境；测试只断言 `aschedule_ingestion` 被正确调用。

#### 4. PR review 沉淀开关联动

**Test:** 打开 `learning_case.pr_review_enabled` 后建 PR。
**Expected:** 产生 outcome=review 的 case（幂等键 `{sid}:pr_review`）；`ModelUsageRecord` 出现 `call_source=pr_review_capture`。
**Why human:** 依赖真实 LLM 与 git 平台 diff。

### Gaps Summary

无阻断性 gap。5/5 成功标准在代码与测试层面全部验证通过：公共回写 service 实质实现且三链路接线完整、存量 fallback 三态守门有专项用例、提炼管线全套质量门/幂等/开关落地、Skill 种子与步级 trace 端到端可调、观测登记先行且事件归因完整。回归宿主 73 passed，唯一失败为 phase 前已存在的腐坏用例（deferred-items 在案）。待人工确认项均为外部服务/LLM 质量类，无法程序化验证。

---

_Verified: 2026-07-22T05:20:00Z_
_Verifier: Claude (gsd-verifier)_
