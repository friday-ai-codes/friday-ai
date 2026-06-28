---
phase: 90-clarification-capability
reviewed: 2026-06-27T07:05:34Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/delivery/models/clarification.py
  - server/delivery/models/__init__.py
  - server/delivery/services/clarification_service.py
  - server/delivery/migrations/0026_clarification_questions.py
  - server/services/plan_orchestration/clarify_adapter.py
  - server/services/plan_orchestration/ask_clarification.py
  - server/services/plan_orchestration/resume.py
  - server/services/plan_orchestration/__init__.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
resolved_followup: "WR-01 容器状态推进 answered + WR-02 空轮守护已修复并补守护测试（16 passed）；WR-03 + 3 INFO 记账到 Phase 91"
status: issues_found
---

# Phase 90: Code Review Report

**Reviewed:** 2026-06-27T07:05:34Z
**Depth:** deep（含跨文件调用链 / pending 谓词一致性追踪）
**Files Reviewed:** 8（外加 cross-reference 读取 `clarification_questions.py`、`plan_research.py`、`plan_research_tools.py`、`plan_deepen.py` 与测试 `test_clarification_service.py` 等）
**Status:** issues_found（0 BLOCKER / 3 WARNING / 3 INFO）

## Summary

本次审查覆盖 Phase 90（澄清能力层）全量提交（`2c6f530bb~1..50cd881ee`，含 90-01/02/03/04）。重点核对项**全部通过**，无 BLOCKER：

- **INV-6（写入收口）通过**：`Clarification.objects.create` / `ClarificationQuestion.objects.create|bulk_create` 仅出现在 `clarification_service.py`；其余 4 处对 `Clarification.objects.filter(...)` 的引用（`clarify_adapter`、`plan_research`、`plan_research_tools`、`plan_deepen`）均为**读**（`.aexists`/`.values`/`.afirst`），非旁路写。grep 守护测试（含子模型）覆盖到位。
- **采纳信号 `recommendation_adopted` 三态正确且不可篡改**：`single`/`multi`/`None` 在 server 端 `_answer_question` 内一次性定格，`answers` 仅读 `question_id/selected/freeform_text`，**不接受**调用方传入 adopted，采纳率统计可信。
- **fail-soft 通过**：LLM `[]`/异常已在 `agenerate_clarification_questions` 内吞为 `[]`，`ClarifyAdapter.clarify` 对 `if questions:` 分流回退 legacy 单题，未新增抛点；resume 不阻断。
- **命名撞车隔离通过**：统一 `ask_clarification` 仅薄封装 `create_round`，靠模块路径区分，**未 import / 未复用** `agents/tools/clarification.py:ask_clarification`。
- **观测与 async ORM 通过**：生命周期事件带 `category`/`component`/`duration_ms`；`call_source=plan_clarification` 埋点未被破坏；所有写经 `sync_to_async`，无裸 lazy-FK（policy 仅读已加载 JSONField）；日志未泄漏凭证/答案明文。

发现 3 个 WARNING（健壮性 / 一致性 / 生命周期完整性）与 3 个 INFO，详见下文。

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `container_status` 生命周期只入不转——永远停留 "pending"

**File:** `server/delivery/services/clarification_service.py:191`（写入）、`server/delivery/models/clarification.py:43-45`（字段语义）
**Issue:** `_create_round_sync` 把容器 `container_status` 设为 `"pending"`，但 `answer_round` / `_answer_question` 全程**只更新子题** `answered_at`/`recommendation_adopted`，从不把容器 `container_status` 推进到 `"answered"`/`"skipped"`。模型注释声明该字段含 `pending/answered/skipped` 三态，实际只会出现 `pending`（或 `None`，legacy 行）。测试 `test_create_round_builds_container_and_questions` 也只断言初始 `"pending"`，无任何用例验证它会变。Phase 91 出口面/采纳率若按 `container_status` 判断"轮是否已答"将得到永远 pending 的错误结论。
**Fix:** 二选一——(a) 在 `answer_round` 中当本轮全部子题 `answered_at` 非空时，于同一 `sync_to_async` 块内条件更新容器 `container_status="answered"`；或 (b) 若 Phase 90 决定"轮状态"统一由 `ahas_pending`（按子题）派生、不用 `container_status`，则删除该字段写入与模型字段，避免留下永不前进的误导性状态。建议 (a)：

```python
# _answer_round_sync 末尾（仍在 sync 块内）
if answered and not ClarificationQuestion.objects.filter(
    clarification_id=round_id, answered_at__isnull=True
).exists():
    Clarification.objects.filter(id=round_id, container_status="pending").update(
        container_status="answered"
    )
```

### WR-02: 空问题轮 → 永久不可作答的 pending（`create_round` / `ask_clarification` 无空列表守护）

**File:** `server/services/plan_orchestration/ask_clarification.py:39-66`、`server/delivery/services/clarification_service.py:185-207, 302-313`
**Issue:** `create_round(session, [])` 会建一个**无子题**的容器（`container_status="pending"`、`answered_at=None`、`children=[]`）。此时 `ahas_pending` 走 legacy 分支 `questions__isnull=True AND answered_at__isnull=True` → 命中 → 永远 `True`；而 `answer_round([])` 不会作答任何子题，**无法解除挂起**（只能靠语义错配的 legacy `answer_clarification` 改容器 `answered_at` 兜底）。`ClarifyAdapter` 内有 `if questions:` 守护，但**入口无关的 `ask_clarification` helper 直接透传 `questions`、零校验**，作为 Phase 91+ 公开能力，任一调用方误传 `[]` 即让 session 永久卡在 clarifying。无对应回归测试。
**Fix:** 在 `create_round`（或 `ask_clarification`）入口对空列表 fail-fast，避免落不可作答轮：

```python
async def create_round(self, session, questions, *, ...):
    if not questions:
        raise ValueError("create_round requires at least one question")
    ...
```
并补一条"空 questions 被拒"的守护用例。

### WR-03: pending 谓词在生产入口未完全收口——结构化轮经旧入口判定/渲染会漂移

**File:** `server/workflows/nodes/ai/plan_research.py:312-319`、`server/agents/tools/plan_research_tools.py:210-217`、`server/workflows/nodes/integrations/plan_deepen.py:214-221`
**Issue:** CONTEXT 与 service docstring 强调"pending 判定收口到 `ahas_pending` 统一谓词，避免逻辑漂移"。本 phase 只把 **resume.py / e2e helper** 收口；但三个**生产入口**的 `_maybe_suspend` / `_apending_clarification_question` 仍直接用 legacy `Clarification.objects.filter(session_id=..., answered_at__isnull=True)`。结构化轮容器 `answered_at` **永远为 None**、`question=""`，于是这些旧读法对结构化轮：(1) 取到的 `question` 为空串、`options` 取不到 → 挂起 marker / 卡片文案是空澄清；(2) 判 pending 完全依赖容器 `answered_at`，与子题真实作答状态脱钩。

注：功能上当前由收口后的 `adrive_plan_session_to_pause_or_terminal`（先 `ahas_pending` 短路）门控，`_maybe_suspend` 仅在确有 pending 时被触达，故**不构成无限挂起/错误 FAILED**；空 marker 内容属"出口面渲染"（Phase 91 范畴，CONTEXT 已 deferred）。但 legacy 读法滞留是明确的逻辑漂移隐患，未来若有入口绕过 resume helper 直接调 `_maybe_suspend` 即会误判。
**Fix:** Phase 91 出口面落地时，把这三处 pending 读法与 marker 内容一并收口到 `ClarificationService`（新增"取本轮未答子题列表"读谓词，承载 `question/options/recommended`），不再裸读容器 `answered_at`/`question`。本 phase 可不动代码，但应在 91 计划中显式记账。

## Info

### IN-01: `round_no` 文档承诺"按已有轮数派生"，实现实际只存透传值

**File:** `server/delivery/models/clarification.py:41-42`、`server/delivery/services/clarification_service.py:143-207`
**Issue:** 模型注释称 `round_no`"由 service 写入时按 session 已有轮数派生"，但 `create_round` 仅原样落 `round_no`（`ClarifyAdapter` 调用不传 → 恒为 `None`）。当前单轮 HITL 无碍，Phase 91 多轮 resume 会踩到"轮序号缺失"。
**Fix:** 要么在 `create_round` 内 `round_no = round_no if round_no is not None else <count existing rounds>` 真正派生，要么修正注释为"由调用方传入"。

### IN-02: INV-6 grep 守护覆盖不全（漏 `Clarification` 实例 `.save()` / `.filter().update()` 旁路）

**File:** `server/tests/delivery/test_clarification_service.py:151-198`
**Issue:** 守护仅断言 `Clarification.objects.create` 与 `ClarificationQuestion.objects.(create|bulk_create)` / `ClarificationQuestion(...).save`。`Clarification(...).save()`、`Clarification.objects.filter(...).update(answered_at=...)` 等写法可绕过断言。当前无旁路，但守护存在盲区。
**Fix:** 扩展正则覆盖 `Clarification(...).save`、`Clarification.objects.filter(...).update(`（白名单 service 文件），与子模型守护对齐。

### IN-03: `qtype = str(q.get("type", "single"))` 对 `type=None` 退化为字符串 "None"

**File:** `server/delivery/services/clarification_service.py:198`
**Issue:** 若归一后的问题 `type` 显式为 `None`，`str(None)` → `"None"`（非 `"single"`）。`_answer_question` 中 `q.qtype == "multi"` 仍走 else（按 single 处理），行为正确但落库脏值。
**Fix:** `qtype=str(q.get("type") or "single")`，把 falsy/None 归到默认 single。

---

_Reviewed: 2026-06-27T07:05:34Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
