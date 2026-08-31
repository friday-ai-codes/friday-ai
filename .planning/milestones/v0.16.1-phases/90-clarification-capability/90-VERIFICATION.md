---
phase: 90-clarification-capability
verified: 2026-06-27T07:15:00Z
status: human_needed
score: 3/3 must-haves verified
overrides_applied: 0
deferred:

  - truth: "三个生产入口（plan_research.py / plan_research_tools.py / plan_deepen.py）的 pending 读法与 marker 渲染收口到 ahas_pending"
    addressed_in: "Phase 91（澄清出口面 + 回流 resume）"
    evidence: "90-REVIEW.md WR-03 明确「出口面渲染属 Phase 91 范畴，CONTEXT 已 deferred；本 phase 可不动代码，应在 91 计划显式记账」；Phase 90 scope 为 resume + e2e helper 两处收口（90-03-PLAN）"
human_verification:

  - test: "配置 default_model（真实 provider）后触发编排澄清，人工核对 LLM 产出的多问题/每题选项/推荐项是否合理、关键词是否加重"
    expected: "结构化多题质量可用：问题聚焦、选项覆盖、推荐项合理，call_source=plan_clarification 上报请求/token/TTFT"
    why_human: "需真实 LLM provider 集成 + 人工判断生成质量（VALIDATION.md Manual-Only 预先声明；自动化测试用 mock 生成器只验接线不验质量）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 90: 澄清能力层 Verification Report

**Phase Goal:** 把「澄清」做成 plan_orchestration 的一等能力——结构化数据模型（多问题单/多选+选项+推荐项+多答案 + 持久化推荐采纳信号 + 绑定技术方案）+ LLM 多问题生成接线 + 入口无关统一 ask_clarification 能力。
**Verified:** 2026-06-27T07:15:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 结构化澄清数据模型支持多问题（单/多选+选项+推荐项）+ 多答案 + 单一写入入口 INV-6 | ✓ VERIFIED | `ClarificationQuestion` 子表（`clarification.py:67-119`）含 order/question/qtype/options/recommended/selected/freeform_text/answered_at/`recommendation_adopted`；`Clarification` 容器加 round_no/container_status/origin_repo/plan_version_id（全 nullable）；写入只经 `ClarificationService.create_round/answer_round`（INV-6 grep 守护 2 用例通过，全仓除 service 外无旁路写） |
| 2 | LLM 基于需求+路由候选+召回上下文产多问题，`call_source=plan_clarification` 接线 | ✓ VERIFIED（接线层）；质量待人工 | `clarify_adapter.py:123-134` 首轮 needs==True 后调 `agenerate_clarification_questions(requirement, routing, recall_hits)` → `create_round` 落库；空/异常 fail-soft 回退 `create_clarification` 单题（`:135-146`）；生成器 `clarification_questions.py:159` `use_call_source(CallSource.PLAN_CLARIFICATION)`。产出**质量**需真实 provider 人工核对（见 Human Verification） |
| 3 | 编排任意点经统一 `ask_clarification` 能力产结构化澄清请求，入口无关、可携 origin_repo | ✓ VERIFIED | `services/plan_orchestration/ask_clarification.py:39-67` 薄封装 `create_round`，携 origin_repo、不驱动 advance/不挂起/不碰 status；barrel re-export（`__init__.py:20,116`）；与 chat tool 同名经模块路径区分（守护测试 `test_..._is_plan_orchestration_not_chat_tool`） |

**Score:** 3/3 truths verified（接线与结构层全 VERIFIED；CLARIFY-02 的 LLM 产出质量需人工核对）

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | 三个生产入口（`plan_research.py`/`plan_research_tools.py`/`plan_deepen.py`）pending 读法 + marker 渲染收口 ahas_pending | Phase 91 | 90-REVIEW.md WR-03：出口面渲染属 Phase 91 范畴（CONTEXT deferred）；Phase 90 scope 仅 resume + e2e helper 两处收口。功能当前由收口后的 `adrive_plan_session_to_pause_or_terminal` 先 ahas_pending 短路门控，不构成无限挂起/错误 FAILED |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/delivery/models/clarification.py` | 容器新字段 + ClarificationQuestion 子表 | ✓ VERIFIED | 容器 4 nullable 字段；子表全字段齐备，FK CASCADE related_name=questions，db_table+复合索引；模型层零业务方法 |
| `server/delivery/migrations/0026_clarification_questions.py` | 容器 AddField×4 + 子表 CreateModel，依赖 0025 | ✓ VERIFIED | 内容与模型一致；`makemigrations delivery --check` → "No changes detected"（exit 0） |
| `server/delivery/models/__init__.py` | ClarificationQuestion barrel re-export | ✓ VERIFIED | import + `__all__`（行 9,113） |
| `server/delivery/services/clarification_service.py` | create_round/answer_round/ahas_pending | ✓ VERIFIED | 三方法落地；`recommendation_adopted` server 端 single/multi/None 三态定格；幂等条件更新；WR-01 容器推进 + WR-02 空轮守护 |
| `server/services/plan_orchestration/clarify_adapter.py` | LLM 多题接线 + fail-soft + ahas_pending | ✓ VERIFIED | 三段判定收口；fail-soft 记 `clarification_fallback_coarse_question` |
| `server/services/plan_orchestration/resume.py` | CLARIFYING 短路改调 ahas_pending | ✓ VERIFIED | `:64-68` lazy import + `ahas_pending` |
| `server/services/plan_orchestration/ask_clarification.py` | 入口无关 helper | ✓ VERIFIED | 薄封装 create_round；不驱动/不挂起 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `__init__.py`(delivery) | `ClarificationQuestion` | from import | ✓ WIRED | re-export + __all__ |
| `clarify_adapter.py` | `agenerate_clarification_questions` | 首轮 needs==True 调用 | ✓ WIRED | 模块顶 import + await 调用 |
| `clarify_adapter.py` | `create_round` / `ahas_pending` | 落库 + pending 收口 | ✓ WIRED | `:101,132,144` |
| `resume.py` | `ClarificationService.ahas_pending` | CLARIFYING 短路 | ✓ WIRED | lazy import + await |
| `plan_orchestration/__init__.py` | `ask_clarification` | barrel re-export | ✓ WIRED | `:20,116` |
| `ask_clarification.py` | `ClarificationService.create_round` | 薄封装 | ✓ WIRED | `:64-67` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 澄清能力测试全绿 | `pytest tests/delivery/test_clarification_service.py tests/services/test_engine_clarify.py tests/services/test_plan_research_e2e.py tests/services/test_ask_clarification_helper.py -q` | 35 passed in 23s | ✓ PASS |
| 迁移与模型一致 | `manage.py makemigrations delivery --check --dry-run` | No changes detected (exit 0) | ✓ PASS |
| INV-6 无旁路写 | grep `Clarification(Question)?.objects.(create|bulk_create)` | 仅 `clarification_service.py`（+测试） | ✓ PASS |

> 注：实际测试文件路径为 `tests/services/test_engine_clarify.py` / `tests/services/test_plan_research_e2e.py`（user query 写作 `tests/services/plan_orchestration/...`，仓内实际无该子目录）。已用实际路径验证。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CLARIFY-01 | 90-01, 90-02 | 结构化澄清数据模型 + 单一写入入口 INV-6 | ✓ SATISFIED | 模型 + service + INV-6 grep 守护 |
| CLARIFY-02 | 90-03 | LLM 结构化多问题生成（call_source=plan_clarification） | ✓ SATISFIED（接线）/ ⚠️ 质量待人工 | adapter 接线 + 生成器 call_source；产出质量需真实 provider 人工核对 |
| CLARIFY-03 | 90-04 | 统一入口无关 ask_clarification（携 origin_repo） | ✓ SATISFIED | helper + barrel + 同名防撞守护 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 无 TBD/FIXME/XXX；无 stub/空实现；无旁路写 | ℹ️ Info | 修改文件扫描干净，观测埋点 best-effort 包裹 |

### Human Verification Required

#### 1. 真实 LLM 多问题生成质量（CLARIFY-02）

**Test:** 配置 `default_model`（真实 provider）后触发一次编排澄清（首轮 needs==True 路径）。
**Expected:** LLM 产出的多问题结构化合理——问题聚焦、每题选项覆盖、推荐项合理、关键词加重；`call_source=plan_clarification` 上报请求/token/TTFT/上游错误码。
**Why human:** 需真实 LLM provider 集成 + 人工判断生成质量。自动化测试用 mock 生成器只验「接线 + fail-soft + 落库」，不验产出质量（VALIDATION.md 已预先声明为 Manual-Only）。

### Gaps Summary

无 BLOCKER、无 gaps。Phase 90 三条 ROADMAP 成功标准在代码中全部可观测达成：结构化数据模型（容器+子表+采纳信号+绑定）、LLM 多题接线（含 fail-soft + call_source）、入口无关 `ask_clarification` helper（INV-6、origin_repo、防撞名）均落地并经 35 个测试守护；INV-6 写入收口与 ahas_pending 统一谓词一致；code-review 的 WR-01（容器推进 answered）与 WR-02（空轮守护）已修复并补守护测试。

唯一未自动闭环项为 CLARIFY-02 的**真实 LLM 产出质量**——属外部 provider 集成 + 主观判断，VALIDATION.md 预先列为 Manual-Only，故状态判定为 `human_needed`（非 gaps）。code-review 的 WR-03 + 3 个 INFO 为 Phase 91 出口面记账的 deferred 项，不阻断本 phase 目标达成。

---

_Verified: 2026-06-27T07:15:00Z_
_Verifier: Claude (gsd-verifier)_
