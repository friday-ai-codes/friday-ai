---
phase: 92-capability-slot-backend
reviewed: 2026-06-27T11:20:00Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - server/workflows/nodes/base.py
  - server/workflows/nodes/shapes.py
  - server/workflows/validation/graph_validator.py
  - server/workflows/nodes/ai/plan_research.py
  - server/feishu/cards/chat_question_card.py
  - server/workflows/nodes/integrations/clarification_card.py
  - server/feishu/callbacks/clarify_card_callback.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
resolution:
  WR-01: resolved
  IN-01: deferred
  IN-02: deferred
  IN-03: deferred
---

# Phase 92: Code Review Report

**Reviewed:** 2026-06-27T11:20:00Z
**Depth:** deep（含跨文件调用链：validator→registry、callback→scheduler.approve_node、node→collect_inputs/amark_waiting_event）
**Files Reviewed:** 7
**Status:** issues_found（0 BLOCKER / 1 WARNING / 3 INFO）

## Summary

Phase 92（capability-slot-backend，92-01~92-03）的实现质量高，核心契约稳健：

- **SLOT-01 零回归（重点）**：`NodePort.shape` 字段带默认空串放在 dataclass 末尾（不破坏既有位置参数构造），与 `port_type` 正交；`get_schema` 输出新增 `shape` 字段。`_validate_port_shapes` 严格遵守「向后兼容命门」——任一端 shape 空/`default` 端口（shape 恒空）→ 通配放行，仅双端非空且不等才报 `incompatible_port_shape`，且 handle 非法/节点未知/边缺失均跳过不重复报。由于本 phase 唯一带非空 shape 的端口（`ai_plan_research.clarify/resume`、`clarification_card.*`）全是新端口，既有工作流/模板的边无法命中该规则，零回归在结构上成立，并由测试佐证。
- **SLOT-02**：`ai_plan_research` clarify/resume 仅声明端口、`execute`/`_map_terminal`/`_maybe_suspend` 路由未改（仍只走 default/error），续推钥匙仍是 `output_data.session_id`，default/error 零回归。`clarification_card` 回调防伪造到位：服务端权威 `execution_id/node_id` 定位 + `node_type=="clarification_card"` 校验 + `WAITING_EVENT` 幂等门三重防线；落库只经 `ClarificationService.answer_round`（INV-6）；`clarify_card_` 前缀与 91 `plan_clarify_` 经 `CardCallbackView` `startswith` 物理隔离。
- **运行时验证**：`amark_waiting_event` 将 `waiting_event` 输出落到 `output_data`，故 transient 路径回调可读 `questions_meta`；`collect_inputs` 按 `target_handle` 归集，`clarification_request` 命名端口可正确落到 `get_input("clarification_request")`。
- **fixture**：`uv run python manage.py dump_node_fixture` 重新生成与提交版本**逐字节相同**（`node_count=42`，含 `clarification_card`、`ai_plan_research` 新增 resume/clarify 端口、无 war-room stale 节点），node-sync 不破。
- **测试**：92 相关 79 个测试全绿（graph_validator / plan_research / clarification_card_node / chat_question_card / clarify_card_callback）。

唯一需修项为发卡侧澄清问题正文未脱敏（与 91 镜像不一致）；其余为可读性/健壮性提示。

## Warnings

### WR-01: clarification_card 发卡问题正文未脱敏（与 91 镜像 + 脱敏硬规则不一致）

**Status:** ✅ RESOLVED（2026-06-27）—— `build_clarification_card` 前对 `card_questions` 问题正文应用 `redact_secrets_in_text`（与镜像 `ai_plan_research._acollect_round_questions` 发卡脱敏一致），保持 best-effort 不反噬挂起；新增 `test_card_question_text_is_redacted` 断言脱敏生效；ruff/mypy + 6 个相关单测全绿。
**File:** `server/workflows/nodes/integrations/clarification_card.py:176-184`
**Issue:** 节点对 `title` / `reason` 调用了 `redact_secrets_in_text`（L200-201），且回调置灰卡 `_send_answered_card_best_effort` 对问题与答案均脱敏；但**发卡时 `card_questions` 的问题正文 `str(q.get("question", ""))` 未脱敏**。对照镜像 `ai_plan_research._acollect_round_questions`（plan_research.py:481）对问题正文显式 `redact_secrets_in_text` 脱敏。问题正文来源于编排引擎/LLM 上游产物，按观测与安全规范（「脱敏不可绕过……上游响应体」）及 phase 重点「脱敏飞书 payload/答案」应统一脱敏。实际泄露面有限（日志只记 chat_id/message_id 不记卡体；受众即本群），但与既有安全范式存在可见偏差，应对齐。
**Fix:**
```python
card_questions = [
    {
        "question": redact_secrets_in_text(str(q.get("question", ""))),
        "type": q.get("type") or q.get("qtype") or "single",
        "options": q.get("options") or [],
        "recommended": q.get("recommended") or [],
    }
    for q in questions
]
```

## Info

> **DEFERRED（2026-06-27）**：以下 3 条 INFO 不在本次修复范围。IN-01 属 Phase 93 接线设计注意点（语义端口不驱动路由）；IN-02 question_count 死参沿袭镜像，无功能影响；IN-03 transient dict 守卫为健壮性提示，引擎已兜底降级。

### IN-01: 声明的 clarification_answer/feishu_message 输出端口不驱动运行时路由（approve_node 硬编码 "approved"）

**File:** `server/workflows/nodes/integrations/clarification_card.py:102-116`
**Issue:** 回调经 `WorkflowEngine.approve_node` 续推，`approve_node`（scheduler.py:1376-1380）将 `_next_handle` 硬编码为 `"approved"`。而本节点声明的输出端口是 `clarification_answer`/`feishu_message`/`error`，无 `approved`/`default` 端口。结合 `routing._edge_selected`（routing.py:66-81）：当下游边 `source_handle="clarification_answer"` 时，`next_handle="approved"` 不匹配，且 `"approved"` 不在该节点 outgoing 桶中 → 仅 `source_handle=="default"` 的边被回退选中 → **经 `clarification_answer` 端口直连的下游会被判 skip_unselected 而跳过**。答案数据本身仍经 `collect_inputs` 扁平合并下发（不丢数据）。此行为与既有 `GroupChatQuestionNode`（声明 answered/timeout/error、同样经 `approve_node` 续推）逐字一致，且 SLOT-02 设计明确这些 shape 端口为 Phase 93 形状磁吸的「声明」用途，故非本 phase 回归。提示：Phase 93 把该节点实际接入工作流时，下游需经 default 句柄连线（或为该家族节点统一引入 `approved`/语义端口路由），否则语义端口连线会被跳过。
**Fix:** 无需在本 phase 修改；记录给 Phase 93 接线设计：要么文档化「下游走 default 句柄」，要么让 `approve_node` 续推的节点把 `_next_handle` 映射到语义输出端口（如 `clarification_answer`）。

### IN-02: 回调 question_count 参数全程未使用（镜像 plan_clarify 的死参）

**File:** `server/feishu/callbacks/clarify_card_callback.py:77,105,211`
**Issue:** `question_count` 从回调 data 解析（L77）并透传进 `_do_clarify_card_async`（L105/形参 L211），但函数体内 answers 长度完全由 `_acollect_round_questions` / `questions_meta` 决定，`question_count` 从不参与逻辑。与镜像 `plan_clarify_callback` 同样存在该未用参数，属沿袭。无功能影响。
**Fix:** 可删除该参数的解析与透传，或保留以与镜像一致；如保留建议加注释说明仅为审计回显占位。

### IN-03: transient questions 列表项未做 dict 类型守卫

**File:** `server/workflows/nodes/integrations/clarification_card.py:158-159,176-184`
**Issue:** transient 分支 `questions = list(raw) if isinstance(raw, list) else []` 仅校验外层是 list，未校验每个元素为 dict。若上游传入含非 dict 元素（如 str）的 `questions`，`card_questions`/`questions_meta` 推导式中的 `q.get(...)` 会抛 `AttributeError`，由引擎兜底降级为节点 failed（不致命，但非该节点 D-4「缺内容→failed+error」的预期优雅路径）。persisted 分支来自 DB 无此风险。
**Fix:**
```python
raw = req.get("questions")
questions = [q for q in raw if isinstance(q, dict)] if isinstance(raw, list) else []
```

---

_Reviewed: 2026-06-27T11:20:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
