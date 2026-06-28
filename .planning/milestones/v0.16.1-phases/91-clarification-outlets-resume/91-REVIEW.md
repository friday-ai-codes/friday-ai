---
phase: 91-clarification-outlets-resume
reviewed: 2026-06-27T09:20:00Z
depth: deep
files_reviewed: 15
files_reviewed_list:
  - server/services/plan_orchestration/answer_resume.py
  - server/services/plan_orchestration/clarify_adapter.py
  - server/services/plan_orchestration/__init__.py
  - server/feishu/cards/chat_question_card.py
  - server/feishu/callbacks/plan_clarify_callback.py
  - server/workflows/nodes/ai/plan_research.py
  - server/workflows/nodes/integrations/plan_deepen.py
  - server/agents/tools/plan_research_tools.py
  - server/chat/views.py
  - server/chat/serializers.py
  - server/chat/conversation_service.py
  - web/src/components/chat/ClarificationCard.vue
  - web/src/types/clarification.ts
  - web/src/api/chat.ts
  - web/src/stores/chat.ts
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: resolved
resolved_at: 2026-06-27T10:00:00Z
resolution:
  CR-01: resolved   # owner-skip + space_id 守卫，commit 07d870185
  WR-01: resolved   # 发卡侧整轮取子题，commit 934a4ea90
  WR-02: resolved   # 轮缺失返回 None，commit 345176b93
  WR-03: resolved   # 归属校验收窄到 pending 轮，commit 4d743bd2d
  IN-01: deferred    # 多轮计数含 legacy 行，仅影响展示用 round_no，按 INFO 暂缓
  IN-02: deferred    # runtime 题面脱敏一致性，owner-gated API 风险低，按 INFO 暂缓
---

# Phase 91: Code Review Report

**Reviewed:** 2026-06-27T09:20:00Z
**Depth:** deep
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Phase 91 把 plan 编排澄清回路的两个出口面（飞书群卡回调 + 会话 REST endpoint）接到同一份共享回流 helper（`aanswer_round_and_resume`），并放开多轮澄清 + 带答案重判 + 轮数上界。整体设计落地很扎实：CLARIFY-06 同源 helper 确实被两入口共用、未造两套；飞书回调据卡片权威 `clarification_id` 取轮、绝不信回调 `session_id`，防伪造到位；INV-6 写入全部经 `ClarificationService`，无旁路写；async 全程用 `*_id` 标量解析 FK；脱敏与 best-effort 观测齐备；前端单题卡回归路径物理隔离、i18n 为真实 zh-CN。回调已在 `feishu/urls.py` 正确注册，新路由已挂载，所用 import 均存在。

但**会话端 endpoint 的权限门存在一处真实缺陷**：二级 `has_project_access` 兜底门缺少「仅对非 owner 生效」的守卫，与本仓既有所有会话视图（`views.py` 多处 `and conversation.created_by_id != user.id` 二级门范式）背离，会对**已通过 owner gate 的合法 owner**强加项目成员校验——空间为空（个人/通用会话）时直接 500（`has_project_access` 对 `None` 空间访问 `.pk`），owner 非 `member` 角色时误 404。这是当前唯一 BLOCKER。其余为 q{i}↔order 映射的潜在漂移、helper TOCTOU 边界、归属校验作用域偏宽三项 WARNING。

## Critical Issues

### CR-01: 会话端二级项目门误施加于 owner —— 空间为空会 500、非成员 owner 误 404

> **✅ RESOLVED**（commit `07d870185`）：二级 `has_project_access` 门补 `space_id is not None`
> + `created_by_id != user.id` 双守卫，对齐既有范式（views.py:882-889 / 1099-1106 / 1208-1215），
> 合法 owner 直接放行、空 space 不再访问 `None.pk`。新增「owner+空 space 放行」「owner+非成员放行」
> 回归测试（`tests/test_plan_clarification_answer_endpoint.py`）。

**File:** `server/chat/views.py:3037-3049`
**Issue:**
`PlanClarificationAnswerView.post` 的 owner gate（3024-3034）已对「非 owner」统一 404；走到 3037 时用户**必为 owner**（且 `IsAuthenticated` 保证已认证）。但紧随的二级门无条件对所有非 superuser 调 `has_project_access`：

```python
# 3037
if not getattr(user, "is_superuser", False):
    allowed = await sync_to_async(PermissionService.has_project_access)(
        user, conversation.space, "member",
    )
    if not allowed:
        return _not_found
```

本仓既有所有会话视图（如 `views.py:886-890 / 1103-1107 / 1212-1216`）的二级 `has_project_access` 兜底都带 `and conversation.created_by_id != user.id` 守卫——即「owner 已被 owner gate 授权，不再叠加项目门，二级门仅兜底 null-owner/共享行」。此处漏了该守卫，后果：

1. **空间为空时 500**：个人/通用会话（含 bound_project 但 `space` 为空的作战室会话）`conversation.space is None`。`has_project_access(user, None, "member")` → 成员查 `get_user_role` 返回 None → 进入 `logger.debug(..., project_id=str(project.pk))`（`permissions/services.py:60-61`）→ `None.pk` `AttributeError` 上抛（view 此段无 try/except）→ 合法 owner 答 plan 澄清直接 500。chat 出口面正是面向个人会话的主路径，可触发。
2. **非成员 owner 误 404**：owner 在该空间仅 `viewer` 或非成员时 `has_project_access(..., "member")` 返回 False → 对已确认的 owner 返回 404，拒绝其作答。

**Fix:**
对齐既有范式，给二级门加 owner-skip 守卫（owner 已授权即跳过项目门）：

```python
# project 级 has_project_access 仅作 null-owner/共享行兜底；owner 已授权不叠加
if (
    not getattr(user, "is_superuser", False)
    and conversation.created_by_id != user.id
):
    from permissions.services import PermissionService

    allowed = await sync_to_async(PermissionService.has_project_access)(
        user, conversation.space, "member",
    )
    if not allowed:
        logger.warning(
            "plan_clarification_answer_denied_cross_project",
            user_id=str(getattr(user, "id", "")),
            conversation_id=str(conversation_id),
        )
        return _not_found
```

（注：因上方 owner gate 已 404 全部非 owner，此守卫等效于让二级门对当前路径短路；如未来放开共享会话作答，再单独按 `space is not None` 设计项目门并防 `None.pk`。）

## Warnings

### WR-01: 发卡侧与回调侧 q{i}↔order 过滤口径不一致（WARNING #3 不变量未真正逐字成立）

> **✅ RESOLVED**（commit `934a4ea90`）：发卡侧 `plan_research._acollect_round_questions` 去掉
> `answered_at__isnull=True` 过滤，整轮按 `order` 取全部子题，与回调侧逐字一致。新增「同一轮部分已答」
> 守护测试（`test_acollect_round_questions_includes_answered_subquestions`）固化不变量。

**File:** `server/workflows/nodes/ai/plan_research.py:444-449` ↔ `server/feishu/callbacks/plan_clarify_callback.py:168-172`
**Issue:**
回调侧 `_acollect_round_questions` 注释声称与发卡侧「枚举顺序逐字一致」，并刻意**取整轮全部子题**（不按 `answered_at` 过滤）以防索引漂移：

```python
# plan_clarify_callback.py:168
ClarificationQuestion.objects.filter(clarification_id=clarification_id).order_by("order")
```

但发卡侧 `plan_research.AIPlanResearchNode._acollect_round_questions` 恰恰**按 `answered_at__isnull=True` 过滤**后再 enumerate 赋 `q{i}`：

```python
# plan_research.py:444
ClarificationQuestion.objects.filter(
    clarification_id=clarification_id, answered_at__isnull=True
).order_by("order")
```

两侧过滤口径不同。当前流程下每轮容器是 `create_round` 新建、发卡时全部子题未答（unanswered == all），故索引恰好对齐、不会出错。但这违背了所声明的「逐字一致」不变量：一旦未来出现「同一轮部分已答后再次发卡」（多轮内重发 / 容器复用），发卡侧 `q{i}` 会跳过已答子题、回调侧 `q{i}` 仍含已答子题 → 索引↔question_id 错位，答案写到**错误的题**。属潜在正确性隐患（当前未触发）。

**Fix:** 两侧统一口径。建议发卡侧也取整轮全部子题（与回调侧一致、最稳）：

```python
# plan_research.py：去掉 answered_at__isnull=True，整轮按 order 取
ClarificationQuestion.objects.filter(clarification_id=clarification_id).order_by("order")
```

或反之让回调侧也只取未答子题——但必须两侧同改，且在测试中加「部分已答轮重发」守护。

### WR-02: `aanswer_round_and_resume` 在轮缺失（TOCTOU）时 `clar.session_id` AttributeError，而非文档承诺的返回 None

> **✅ RESOLVED**（commit `345176b93`）：helper 对 `answer_round` 返回值 `getattr(clar, "session_id", None)`，
> 非模型实例（裸 id）即 best-effort 记 `resolved_session=False` 日志并返回 `None`，与 docstring 语义一致。

**File:** `server/services/plan_orchestration/answer_resume.py:76-79`
**Issue:**
helper 文档称「解析不出 session → 返回 None」，但缺失轮的退化路径会先抛异常。`ClarificationService.answer_round`（`clarification_service.py:251-252`）在轮不存在时返回**裸 id**（`clar if clar is not None else round_or_id`，而 `round_or_id` 是调用方传入的 `clarification_id` 字符串/UUID）：

```python
# answer_resume.py:76
clar = await clarification_service.answer_round(clarification_or_id, answers)
# clar 此时可能是裸 id（轮被并发删除/过期）
session = await PlanSession.objects.filter(id=clar.session_id).afirst()  # 裸 id 无 .session_id → AttributeError
```

两入口（chat view `_answer_and_resume`、飞书 `_do_clarify_answer_async`）都有 try/except 兜底，故仅 fail-soft 记日志、续推静默失败，不反噬主响应——但与 helper 文档语义不符，且把本应「干净返回 None」的边界变成异常路径。低概率（已过 pending 校验后才进入），仍属健壮性缺陷。

**Fix:** helper 内对 `answer_round` 返回值做模型判定，非模型实例即按「解析不出」返回 None：

```python
clar = await clarification_service.answer_round(clarification_or_id, answers)
session_id = getattr(clar, "session_id", None)
if session_id is None:
    _safe_log("answer_round_and_resume_completed", ..., resolved_session=False, ...)
    return None
session = await PlanSession.objects.filter(id=session_id).afirst()
```

### WR-03: 会话端 question_id 归属校验作用域为 session（非 pending 轮），越界判定偏宽

> **✅ RESOLVED**（commit `4d743bd2d`）：归属校验 `acount` 作用域由 `clarification__session_id=session.id`
> 收窄到 `clarification_id=pending_round.id`，历史已答轮的 question_id 越界返回 400，不再误导性 `answered:True`。
> 新增历史已答轮 question_id 回归测试（`test_400_question_id_from_prior_answered_round`）。

**File:** `server/chat/views.py:3083-3098`
**Issue:**
归属校验注释称「每个提交的 question_id 必属该 pending 轮」，但实际 `acount` 以 **session 维度**比对：

```python
owned_count = await ClarificationQuestion.objects.filter(
    clarification__session_id=session.id, id__in=submitted_ids
).acount()
```

故同一 session **历史已答轮**的 question_id 也能通过校验。这些 id 进 `answer_round` 后因 `answered_at__isnull=True` 过滤被 no-op，pending 轮子题仍未答 → 容器不推进、session 仍 CLARIFYING，但 endpoint 仍返回 `{"answered": True}`（误导性成功，轮被「卡住」）。属防伪造/健壮性边界偏宽（生产中前端只提交 pending 轮 id，故未触发），与本 phase「question_id 归属校验」重点直接相关。

**Fix:** 把作用域收窄到 pending 轮容器：

```python
owned_count = await ClarificationQuestion.objects.filter(
    clarification_id=pending_round.id, id__in=submitted_ids
).acount()
```

（`pending_round` 已在 3067-3073 取到，直接复用其 id 即可。）

## Info

### IN-01: 多轮计数含 legacy 单题/回退粗题行，`round_no` 可能不准/重复

> **⏸ DEFERRED**：仅影响多轮卡片头部「第 N 轮」展示，不影响落库正确性与短路逻辑，按 INFO 暂缓。

**File:** `server/services/plan_orchestration/clarify_adapter.py:114,151-153`
**Issue:**
`round_count = Clarification.objects.filter(session_id=session.id).acount()` 统计该 session 全部 Clarification 行（含 `create_clarification` 建的 fallback 粗单题行，其 `round_no` 默认 None），用于 `_MAX_CLARIFY_ROUNDS` 上界与 `create_round(round_no=round_count + 1)`。混入无 `round_no` 的 legacy/回退行会让展示用 `round_no` 偏移或重复。仅影响多轮卡片头部「第 N 轮」展示，不影响落库正确性与短路逻辑。
**Fix:** 计数与 round_no 派生改为仅统计结构化轮（如 `round_no__isnull=False` 或有子题的容器），或显式 `Max(round_no)+1`。

### IN-02: runtime `pending_plan_clarification` 序列化未对题面脱敏（与发卡侧不一致）

> **⏸ DEFERRED**：该响应为 owner-gated API（非日志/ledger），风险低，仅跨出口面一致性建议，按 INFO 暂缓。

**File:** `server/chat/conversation_service.py:2358-2371`
**Issue:**
飞书发卡（`plan_research.py:453`）与置灰卡（`plan_clarify_callback.py:318`）均对题面/答复走 `redact_secrets_in_text`，但会话 runtime 序列化 `question`/`selected`/`freeform_text` 直出未脱敏。该响应是 owner-gated API（非日志/ledger，观测脱敏规则主要约束后者），风险低，仅为跨出口面一致性建议。
**Fix:** 如需统一，对 `question`（必要时含已回填 `freeform_text`）套 `redact_secrets_in_text` 后再放入 `pending_plan_clarification`。

---

_Reviewed: 2026-06-27T09:20:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
