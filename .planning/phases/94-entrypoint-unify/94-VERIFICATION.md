---
phase: 94-entrypoint-unify
verified: 2026-06-28T01:02:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "对 technical_plan_generation 工作流（新建实例）跑一次真实飞书需求触发，确认项目群收到「干净结构化 markdown 卡片」（title/summary/执行计划/compat_risks 的 • 项目符号），且正文不含 LLM 原始文本（UNIFY-06 推群端到端）"
    expected: "群里收到结构化卡片，正文来自 plan_markdown（render_merged_plan_markdown），非 raw LLM dump"
    why_human: "notify_feishu_im 推送到真实飞书群 + 卡片视觉渲染属外部服务集成，grep/单测只能验证 plan_markdown 字段渲染与模板字段引用，无法验证真实群消息外观"
  - test: "在配置了真实 AI provider 的环境调用 MCP create_feishu_technical_plan 与 create_coding_plan，确认产出 canonical MergedPlan/PlanVersion 且响应外形兼容（DONE→completed 完整字段；编排在途→partial+session_id，调用方据 session_id 续推）"
    expected: "DONE 时旧响应键全在 + canonical_content；RESEARCHING 在途时 status=partial + session_id，无 5xx"
    why_human: "真实编排需 provider/容器 fan-out，DONE vs PARTIAL 取决于运行期容器就绪情况；单测以 monkeypatch/同步 stub 覆盖契约，真实端到端挂起态需人工验证"
---

# Phase 94: 入口统一 Verification Report

**Phase Goal:** 工作流 / 对话 / MCP 三入口的方案生成全部归一到 `plan_orchestration`，废弃旧 LangChain `ai_plan_generation`（节点库移除、代码 deprecated 不删），done 出口用干净结构化 markdown 推送方案到群。
**Verified:** 2026-06-28T01:02:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth (ROADMAP Success Criteria + Plan must_haves)   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1   | UNIFY-01：`technical_plan_generation` 模板切到 `ai_plan_research`，既有实例不破坏 | ✓ VERIFIED | `technical_plan_generation.json:49` `"type": "ai_plan_research"` + `requirement_text`/`work_item_id` config；无数据迁移（既有 DB 实例不受模板定义改动影响）；`notify_clarify`/`need_clarification` 出边已删（grep count=0） |
| 2   | UNIFY-02：`ai_plan_generation` deprecated + 保留注册 + palette 移除 + 暴露 `ai_plan_research` + 迁移指引 | ✓ VERIFIED | `plan_generation.py:109 @register_node` 保留，`:130 deprecated: ClassVar[bool] = True`，docstring DEPRECATED + `deprecated_node_instantiated` warning；`base.py:570` 基类默认 False；`NodePalette.vue:88` 仅 `ai_plan_research` 裸项（`ai_plan_generation` 已移除）；`docs/workflows/ai-plan-generation-deprecation.md` 存在含 ai_plan_research（7 处） |
| 3   | UNIFY-03/04：MCP 两工具 delegate `plan_orchestration` 产同一 canonical，响应外形兼容 + Mcp* 落库 + token 归因 + 单仓约束 | ✓ VERIFIED | `orchestration_delegate.py:115 delegate_plan_orchestration` + `DelegateResult`；`technical_plan_service.py:367` 调 delegate + `_map_plan_payload`(canonical→旧外形)+`canonical_content`；`views.py:1868` CreateCodingPlanView delegate + `:1871 include_repos=[repository_id]` 单仓 + `:1879 _record_model_usage(run, delegate.model_usage)`（WR-03 token 归因恢复）+ `McpCodingPlanVersion.acreate` 落库 |
| 4   | UNIFY-05：对话方案澄清挂起单一来源，marker 二义隔离 | ✓ VERIFIED | `plan_research_tools.py:42 PLAN_CLARIFICATION_RENDER_MARKER="plan_clarification"`；`_maybe_suspend` CLARIFYING 分支 `:237 marker=PLAN_CLARIFICATION_RENDER_MARKER` + `clarification_id`/`session_id`；值 `!= "ask_clarification"` → chat graph 双条件必不命中（测试 `test_start_plan_research_tool` 守护，前端 `chat.clarification` 27 passed） |
| 5   | UNIFY-06：done 出口干净结构化 plan_markdown 不 dump 原文 + field_not_found 修复 | ✓ VERIFIED | `render.py:28 render_merged_plan_markdown` 仅读 §7 结构化字段（title/summary/execution_plan/compat_risks），`•` 项目符号，coding_instruction 300 截断，无 raw_*；`plan_research.py:144` default 端口 schema 声明 `plan_markdown`，`:529 _map_terminal` DONE 分支调 render 填充；`test_template_validates_with_zero_errors[technical_plan_generation]` 转绿（field_not_found 消除） |

**Score:** 5/5 truths verified（代码 + 测试层）

### Required Artifacts

| Artifact | Expected    | Status | Details |
| -------- | ----------- | ------ | ------- |
| `services/plan_orchestration/render.py` | `render_merged_plan_markdown` 共享 helper | ✓ VERIFIED | 纯函数，barrel 导出（`__init__.py:120`），WIRED：节点 `_map_terminal` + MCP delegate 共用 |
| `workflows/nodes/ai/plan_research.py` | default 端口 schema 声明 plan_markdown + DONE 填充 | ✓ VERIFIED | `:144` schema + `:529` 渲染填充，数据流自 `PlanVersion.content` |
| `workflows/templates/technical_plan_generation.json` | generate_plan=ai_plan_research | ✓ VERIFIED | `:49` 切换 + `:68` `{{nodes.generate_plan.plan_markdown}}` 引用 |
| `workflows/nodes/ai/plan_generation.py` | deprecated ClassVar + 保留注册 | ✓ VERIFIED | `@register_node` + `deprecated=True` + warning |
| `mcp_tools/orchestration_delegate.py` | delegate 核心 + 三态映射 + 异常护栏 + model_usage | ✓ VERIFIED | `delegate_plan_orchestration`，`:202` 外层 try→failed 终态（IN-03），`:53 model_usage`（WR-03） |
| `mcp_tools/technical_plan_service.py` | delegate 路径 + canonical→旧字段映射 + 落库 | ✓ VERIFIED | `_map_execution_plan_to_repository_tasks`（含 steps/test_strategy/risks/rollback/base_branch，WR-01/IN-02）+ `_map_plan_payload`（WR-02） |
| `docs/workflows/ai-plan-generation-deprecation.md` | 迁移指引 | ✓ VERIFIED | 存在，含 ai_plan_research 迁移说明 |
| `web/.../NodePalette.vue` | 移除 ai_plan_generation + 暴露 ai_plan_research | ✓ VERIFIED | `:88` 仅 ai_plan_research 裸项 |

### Key Link Verification

| From | To  | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| technical_plan_generation.json | ai_plan_research.outputs.plan_markdown | `{{nodes.generate_plan.plan_markdown}}` | ✓ WIRED | 模板字段引用 + 节点 schema 声明匹配（field_not_found 消除，校验零 error） |
| plan_research.py `_map_terminal` | render.py | `render_merged_plan_markdown(pv.content)` | ✓ WIRED | `:516` import + `:529` 调用 |
| technical_plan_service.py | orchestration_delegate.py | `delegate_plan_orchestration` | ✓ WIRED | `:19` import + `:367` 调用 |
| views.py CreateCodingPlanView | orchestration_delegate.py | `delegate_plan_orchestration(include_repos=[repository_id])` | ✓ WIRED | `:75` import + `:1868` 调用 + 单仓约束 |
| views.py CreateCodingPlanView | McpCodingPlan(Version) | `acreate` 落库 | ✓ WIRED | `:1903` acreate |
| plan_research_tools.py | delivery.Clarification + PlanSession | 独立 marker + 双条件物理隔离 | ✓ WIRED | marker 值隔离，收答经 91-04 专路由 |
| work_item_execution_service.py `_coding_plan_body` | canonical task 字段 | coding_instruction 回退（WR-01 下游半） | ✓ WIRED | `:211-222` 回退 requirement/steps/test_plan |

### Behavioral Spot-Checks（automated test suite）

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| MCP delegate + 模板 + 节点渲染 + 澄清 marker（后端） | `uv run pytest tests/mcp_tools tests/workflows/test_template_loader.py tests/workflows/test_plan_research_node.py tests/agents/test_start_plan_research_tool.py -q` | 222 passed | ✓ PASS |
| 前端澄清 runtime + 节点库漂移守护 | `pnpm vitest run chat.clarification node-sync` | 27 passed (2 files) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ---------- | ------ | -------- |
| UNIFY-01 | 94-01 | ✓ SATISFIED | 模板切换 + 既有实例不破坏（无迁移） |
| UNIFY-02 | 94-02 | ✓ SATISFIED | deprecated 保留注册 + palette 移除 + 迁移指引 |
| UNIFY-03 | 94-03 | ✓ SATISFIED | create_feishu_technical_plan delegate + 外形/落库兼容 + WR-03 token 归因 |
| UNIFY-04 | 94-04 | ✓ SATISFIED | create_coding_plan delegate + 单仓约束 + 落库 |
| UNIFY-05 | 94-05 | ✓ SATISFIED | 独立 plan_clarification marker 物理隔离 |
| UNIFY-06 | 94-01 | ✓ SATISFIED | done plan_markdown 结构化渲染（结构层；端到端推群见人工验证） |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| （受改文件） | — | TBD/FIXME/XXX 扫描 | — | 无（grep 零命中；`[DEPRECATED — UNIFY-04]` 系有意废弃标注非债务标记，build_coding_plan 按 CONTEXT「deprecated 不删」保留） |

### Code Review 闭环

`94-REVIEW.md`：0 critical，3 warning（WR-01/02/03）+ 5 info。WR-01（方案细节透传 steps/test/risks/rollback + coding_instruction）、WR-02（plan 外形旧键映射 + canonical_content）、WR-03（create_coding_plan token 归因恢复）+ IN-02（base_branch 透传）/ IN-03（delegate 异常→failed 护栏）**均 resolved 并经守护测试覆盖**（代码逐项核对一致）。IN-01（跨仓回退）/ IN-04（范围外 report_* WIP）deferred（用户已确认无关 WIP 不计入）。

### Gaps Summary

无阻断目标的 gap。三入口归一、deprecated 保留注册、澄清单一来源、done 结构化渲染均在代码 + 222/27 测试层验证通过；REVIEW 全部 warning 已修复。

状态判为 **human_needed**（非 passed）：目标含「推送方案到群」与 MCP 三入口产 canonical 的**端到端外部服务行为**——飞书群卡片真实外观、真实 provider/容器下编排 DONE vs PARTIAL 挂起态，均属外部集成，自动化测试以渲染单测 + monkeypatch/同步 stub 契约覆盖，需人工端到端确认（见 frontmatter `human_verification`）。

> 备注（Info，不影响目标达成）：`.planning/REQUIREMENTS.md:81-86` 状态表仍标 UNIFY-01/05/06 为 `Pending`、`:14/18/19` checkbox 未勾，与代码实际完成态不一致——属状态登记滞后（验证以代码为准），建议归档时同步勾选。

---

_Verified: 2026-06-28T01:02:00Z_
_Verifier: Claude (gsd-verifier)_
