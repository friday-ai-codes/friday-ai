---
phase: 104-tool-surface-closure
verified: 2026-07-22T08:20:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:

  - test: "在真实 Cursor 客户端经 MCP 调用 improve_coding_plan（含一次触发 research/clarify 在途的场景）"
    expected: "同步场景在 HTTP 请求内返回 completed/failed；research/clarify 在途立即返回 partial + session_id，Cursor 不挂起不超时"
    why_human: "partial 短路机制已代码级验证（delegate 三态映射 + 契约进 schema），但真实 Cursor 客户端的超时/挂起行为属实时外部集成，无法用测试/grep 验证"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 104: 工具面收口（improve/analyze 收敛 + 确定性缝退役 + 端到端验收） Verification Report

**Phase Goal:** MCP 工具面收口到统一编排——`improve_coding_plan` / `analyze_repository` 收敛到 `delegate_process_runtime`，`planning_service.py` 确定性缝退役、`plan_orchestration/` 空壳删除、全仓残留引用清零，并完成"四处检索同一 learning case"的里程碑端到端验收。
**Verified:** 2026-07-22T08:20:00Z
**Status:** human_needed（自动化检查全过，仅剩真实 Cursor 客户端行为一项人工验证）
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（ROADMAP Success Criteria）

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | improve_coding_plan 走统一编排（feedback 编排重跑产新 version、trace 可见 session、契约进 schema、partial 短路不挂起） | ✓ VERIFIED | `views.py:2076` ImproveCodingPlanView 调 `delegate_process_runtime`（requirement_text 三段 feedback 块 L2045-2060）；`McpCodingPlanVersion.acreate(version=current_version+1)` L2105；响应含 `session_id`/`status` L2141-2142；契约写进 `serializers.py:234-242`（同步 await 至 pause/terminal、partial+session_id 短路）；partial 短路实现在 `orchestration_delegate.py:203-213`（非 DONE/FAILED → partial best-effort）；snapshot improve/create 均含 session_id/status（serializers.py:671/675，create 漂移一并修复）；`test_improve_coding_plan_appends_new_version` 走 fake delegate 通过 |
| 2 | analyze_repository 收敛 + 产物被编排实际消费；planning_service.py 删除、helper 随迁、测试不失覆盖 | ✓ VERIFIED | `repository_analysis_service.py`（203 行）承接 `build_repository_analysis`；`views.py:77` 改引用随迁模块；消费链三层实打实：views（create L1888-1904 / improve L2065-2081 读 `McpRepositoryAnalysis.summary` 注入）→ `delegate_process_runtime(extra_evidence=...)`（orchestration_delegate.py:126,177）→ `start_orchestration` 写 `decomposition.extra_evidence`（entrypoint.py:58-59）→ merge prompt 拼装 + trace 事件计数（architect_merge_adapter.py:96-100,160-164）；`planning_service.py` 已删除；`tests/services/test_process_runtime_extra_evidence.py` 5 passed；`test_planning_tools.py` analyze 用例断言原样通过（覆盖不丢） |
| 3 | rg planning_service 全仓零残留；plan_orchestration/ 目录删除 + 文档清理；patch target 全部可 import | ✓ VERIFIED | 亲自复跑：`rg planning_service`（排除 .planning/.claude/.git）exit=1 零命中；`rg plan_orchestration` 同样零命中（docs 残留已清）；`server/services/plan_orchestration/` 目录不存在；`tests/mcp_tools/test_patch_target_guard.py` 4 passed（importlib 逐段解析，含 `mcp_tools.views.delegate_process_runtime` / `services.process_runtime.start_orchestration` 显式断言） |
| 4 | 里程碑 E2E：同一 learning case 四面可检索（Chat / 编排召回 / MCP view / 容器链），MCP 与 Chat top-1 一致 | ✓ VERIFIED | `tests/test_milestone_e2e_learning_case.py`（367 行 > min 150）3 passed：面 3 MCP view POST `/api/mcp/tools/search_learning_cases/` top-1=强相关条；面 1 Chat 工具 `agents.tools.knowledge_read_tools.search_learning_cases` 命中同条；统一排序断言 `mcp_top1 == chat_top1`（L292）；面 2 `DeliveryKnowledgeRecallAdapter().recall` 命中 kind=learning_case 且 entity_id 精确匹配 `generate_entity_id` uuid5 派生（L326）；面 4 容器链组合覆盖：`reverse("mcp-tool-search-learning-cases")` 同 URL 胶合断言（L354）+ `task/core/knowledge_tools.py:167` 同名工具 + `task/tests/test_knowledge_tools.py` handler 契约 + `tests/mcp_tools/test_container_knowledge_chain.py` 服务端链路 |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/mcp_tools/views.py` | ImproveCodingPlanView 收敛 delegate；import 不再含 improve_coding_plan | ✓ VERIFIED | import 仅 `delegate_process_runtime, map_canonical_to_coding_plan, build_repository_analysis`；含 `mcp_coding_plan_improved` ingestion 触发 |
| `server/mcp_tools/orchestration_delegate.py` | map_canonical_to_coding_plan 随迁落位 | ✓ VERIFIED | `def map_canonical_to_coding_plan` L250 |
| `server/mcp_tools/serializers.py` | 契约描述 + snapshot 含 session_id/status | ✓ VERIFIED | docstring L211-242；snapshot L671/675 |
| `server/mcp_tools/repository_analysis_service.py` | 证据采集器随迁（min 120 行） | ✓ VERIFIED | 203 行，`def build_repository_analysis` + PlanningResult + normalize_context_chunks |
| `server/services/process_runtime/entrypoint.py` | extra_evidence 注入 stage_state | ✓ VERIFIED | L42/58-59，truthy 才写键 |
| `server/tests/mcp_tools/test_patch_target_guard.py` | importlib patch target 防线 | ✓ VERIFIED | 4 passed |
| `server/tests/test_milestone_e2e_learning_case.py` | 四面 E2E（min 150 行，contains DeliveryKnowledgeRecallAdapter） | ✓ VERIFIED | 367 行，3 passed |
| `server/mcp_tools/planning_service.py` | 已删除 | ✓ VERIFIED | 文件不存在 |
| `server/services/plan_orchestration/` | 空目录已删除 | ✓ VERIFIED | 目录不存在 |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| views.py ImproveCodingPlanView | orchestration_delegate.py | delegate_process_runtime + map_canonical | ✓ WIRED | L2076/L2089 调用，结果写 version 并回写 current_version |
| test_planning_tools.py | mcp_tools.views.delegate_process_runtime | monkeypatch fake delegate | ✓ WIRED | `_make_fake_delegate` L183 + patch，improve/create 不打真实编排 |
| views.py AnalyzeRepositoryView | repository_analysis_service.py | import 随迁模块 | ✓ WIRED | `from .repository_analysis_service import build_repository_analysis` L77 |
| orchestration_delegate.py | entrypoint.py | extra_evidence 透传 start_orchestration | ✓ WIRED | L177 `extra_evidence=extra_evidence` |
| architect_merge_adapter.py（LLMMergedPlanSynthesizer） | decomposition.extra_evidence | _build_prompt 拼装 + EVENT_PLAN_MERGE_STARTED 计数 | ✓ WIRED | L96-100 prompt 段、L160-164 trace 计数 |
| test_milestone_e2e | agents/tools/knowledge_read_tools.py | Chat 工具面直调 | ✓ WIRED | L261 import + async_to_sync 调用 |
| test_milestone_e2e | /api/mcp/tools/search_learning_cases/ | MCP view HTTP + reverse 同 URL 胶合 | ✓ WIRED | L52 常量 + L354 reverse 断言 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| ImproveCodingPlanView 响应 | plan_payload / session_id / status | delegate_process_runtime 编排 canonical content → map_canonical 映射 | Yes（fake delegate 测试捕获 kwargs 断言 extra_evidence 实际到达） | ✓ FLOWING |
| merge prompt | decomposition.extra_evidence | views 读 McpRepositoryAnalysis.summary → delegate → stage_state | Yes（test_build_prompt_includes_extra_evidence_section 断言证据进 prompt） | ✓ FLOWING |
| E2E 四面检索 | learning case hits | create → ingestion → 内存 Qdrant 真实向量入库 → DeliveryKnowledgeSearchService | Yes（双种子区分度设计，弱相关条不得抢 top-1） | ✓ FLOWING |

### Behavioral Spot-Checks（测试套件执行）

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 里程碑四面 E2E | `uv run pytest tests/test_milestone_e2e_learning_case.py -v` | 3 passed | ✓ PASS |
| MCP 工具面全量回归 | `uv run pytest tests/mcp_tools/` | 191 passed, 0 failed | ✓ PASS |
| extra_evidence 三层接线 | `uv run pytest tests/services/test_process_runtime_extra_evidence.py` | 5 passed | ✓ PASS |
| stale patch target 守卫 | `uv run pytest tests/mcp_tools/test_patch_target_guard.py` | 4 passed | ✓ PASS |
| planning_service 残留 | `rg planning_service`（排除 .planning/.claude/.git） | 零命中（exit=1） | ✓ PASS |
| plan_orchestration 残留 | `rg plan_orchestration`（同排除） | 零命中（exit=1） | ✓ PASS |

注：deferred-items.md 记载的 `test_work_item_execution.py` 5 例 Phase 103 rot 已在 104-02 修复（本次 191 passed 含该文件）。已知烂尾（tests/knowledge/test_triggers.py ×3、test_sub_step_coding_node.py::test_plan_generation_node_still_works）不在本次运行范围。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| UNIFY-01 | 104-01, 104-03 | improve_coding_plan 走统一编排，trace 可见 session | ✓ SATISFIED | Truth 1 全部证据 |
| UNIFY-02 | 104-02, 104-03 | analyze 收敛 + 证据消费 + planning_service.py 删除 + helper 随迁 | ✓ SATISFIED | Truth 2 全部证据 |
| UNIFY-03 | 104-02, 104-03 | plan_orchestration 空壳删除 + 全仓残留清零 | ✓ SATISFIED | Truth 3 全部证据 |

无 ORPHANED 需求（REQUIREMENTS.md 映射 Phase 104 的仅 UNIFY-01/02/03，全部被 plans 认领）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | 本次改动 10 个关键文件扫描 TBD/FIXME/XXX/placeholder/not yet implemented 零命中 | — | 无 |

### Human Verification Required

### 1. 真实 Cursor 客户端 improve_coding_plan 不挂起验证

**Test:** 在真实 Cursor 客户端经 MCP 调用 `improve_coding_plan`（含一次触发 research/clarify 在途的场景）。
**Expected:** 同步场景 HTTP 请求内返回 completed/failed；research/clarify 在途立即返回 `partial` + `session_id`，Cursor 不挂起不超时；可凭 session_id 经 `get_coding_execution` 跟进。
**Why human:** partial 短路机制已代码级验证（delegate 三态映射、契约进 schema、fake delegate 测试），但真实 Cursor 客户端的超时/挂起行为属实时外部集成，无法程序化验证。与既往里程碑"真机·真实 provider 验收"遗留同类。

### Gaps Summary

无 gap。4/4 success criteria 在代码库层面全部验证成立：improve 收敛统一编排（契约定版、partial 短路、snapshot 双修）、analyze 随迁且 extra_evidence 三层消费链路 trace 可见、planning_service/plan_orchestration 全仓零残留 + patch target 守卫落防、四面检索 E2E 含统一排序断言全绿。唯一待办为真实 Cursor 客户端的实时行为人工确认（机制已验证，属例行真机验收项）。

---

_Verified: 2026-07-22T08:20:00Z_
_Verifier: Claude (gsd-verifier)_
