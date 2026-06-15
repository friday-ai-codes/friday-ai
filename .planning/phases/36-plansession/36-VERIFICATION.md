---
phase: 36-plansession
title: 前置修复 + 编排引擎骨架 + PlanSession 状态机
verified: 2026-06-16
status: passed
requirements: [PF-01, PF-02, ORCH-01, ORCH-02]
plans_executed: [36-01, 36-02, 36-03]
method: goal-backward
---

# Phase 36 Verification

> 方法：goal-backward —— 从 phase 4 项成功标准倒推，逐项核验代码是否真正交付（非「任务做完」），附可复现证据。

## 结论

**status: passed** —— 4 项成功标准全部 TRUE，证据见下。58 项相关测试全绿，`makemigrations --check` 全项目干净，`search_code` 漂移名零残留，engine 无旁路 status 写。

---

## 成功标准 1（PF-01）：server 端方案生成检索工具真正生效

**判定：✅ TRUE**

- **prompt 引用名与注册名一致**：`_PLAN_GENERATION_BASE_PROMPT` 与 `get_enabled_tools()` 中 `search_code` 全部改为注册名 `search_repository_code`（`space_tools.py:216` `name="search_repository_code"`）。守护测试 `test_plan_generation_tools_guard.py`：`get_enabled_tools` 返回的每个名都在 `_tool_registry`、prompt 无 `search_code`、含 `search_repository_code`。
- **fail-loud**：`build_langchain_tools` 未知工具 `raise ValueError`（含未知名 + `sorted(_tool_registry)`），不再静默 `continue`（`langchain_adapter.py`）。测试 `test_unknown_tool_fails_loud` / `test_unknown_tool_mixed_with_known_raises`。
- **附带修复**：fail-loud 暴露 `send_plan_card` 从未在 app init 登记（同类潜在漂移）→ 已加入 `agents/tools/__init__.py`，使白名单全名可用、节点不再因 fail-loud 误 failed。
- **证据**：`rg -n "search_code" workflows/ agents/ prompts/ --glob '!**/tests/**'` → 无残留；`pytest tests/test_langchain_adapter.py tests/workflows/test_plan_generation_tools_guard.py tests/test_plan_generation_node.py` 全绿。

## 成功标准 2（PF-02）：verify_plan 校验对齐 execution_plan

**判定：✅ TRUE**

- `verify_plan.py` Layer 1 必填 `["title","execution_plan"]`；逐项校验 `execution_plan[i]` 为 dict 且含非空 `repository_id` + `coding_instruction`（对齐 `technical_plan.py` `required:["title","summary","execution_plan"]` + DOMAIN §7 MergedPlan.execution_plan「每任务 repository_id + coding_instruction」）；不再校验不存在的 `tasks`。
- 契约形状 `{valid, errors, warnings, summary}` + `success=True` 不变（`test_contract_shape_stable`）；已核对 `plan_generation.py:486-490` 读 `entry["input"]["plan"]`（读 input 不读 output）未受影响。
- **证据**：`pytest tests/agents/test_verify_plan.py` → 9 passed（有效/缺 title/缺或空 execution_plan/项非对象/缺 repository_id/缺 coding_instruction/warning 不阻断）。

## 成功标准 3（ORCH-02）：PlanSession 状态机可持久化、可从中断恢复、按 §14 推进

**判定：✅ TRUE**

- **模型落库**：`delivery/models/plan_session.py` —— UUID pk + `work_item`(nullable SET_NULL FK) + `entrypoint` + 8-state `status`(默认 decomposing) + `current_plan_version`(UUID 软引用，无 FK) + `decomposition`/`error` JSON；migration `0009_plansession.py` 生成且 `makemigrations --check` 全项目干净，随测试 DB 成功 apply。
- **§14 转移 + 单一入口**：`PlanSessionService.transition` 是 status 唯一变更入口，按 `_ALLOWED`（逐行对齐 §14）白名单校验，非法转移 raise（status 不变、DB 不写）；`fail` 特判任意状态 → failed + 结构化 error。INV-6 grep 守护断言除 service 外无旁路 PlanSession 写 status。
- **持久化 + resume**：status + 中间产物全落 DB 行，`test_create_session_default_and_persist_intermediate` 从 DB 重取验证 status/decomposition 一致（不依赖内存态）。
- **证据**：`pytest tests/delivery/test_plan_session_*.py` → 20 passed（表驱动遍历全部 `_ALLOWED` 合法转移 + 非法 raise + resume + fail）；`pytest tests/delivery/` 全量 229 passed 无回归。

## 成功标准 4（ORCH-01）：可复用入口无关编排 engine 推进流水线

**判定：✅ TRUE**

- **入口无关 + 可注入**：`PlanOrchestrationEngine.__init__` 仅接 `session_service` + 四个可注入 stage 协议（`RouterProtocol/RecallProtocol/ResearchProtocol/MergeProtocol`，`typing.Protocol`），缺省骨架 `Skeleton*`；**不接收任何 workflow/chat IO 对象** → 工作流与 Chat 可共用同一底层。
- **状态驱动推进**：`advance(session)` 按 `session.status` 分派 `_decompose/_route/_recall/_clarify/_research/_merge`；`_decompose` 最小真实拆分（→ routing），其余调注入依赖经 transition 推进；done/failed 终态 no-op。
- **不旁路 status + resume**：engine 经 `PlanSessionService.transition` 驱动转移，**engine.py 无 `.status=` 直接赋值**（rg 守护 + 测试）；advance 按 DB status 续推（resume 测试覆盖任意 status）。骨架 `NotImplementedError` 上抛（不吞 failed），普通异常落 failed。
- **证据**：`pytest tests/services/test_plan_orchestration_engine.py` → 7 passed；`rg -n "\.status\s*=" services/plan_orchestration/engine.py` → 无命中。

---

## 复现命令

```bash
cd server
# 全 phase 测试（58 passed）
uv run pytest tests/test_langchain_adapter.py tests/workflows/test_plan_generation_tools_guard.py \
  tests/agents/test_verify_plan.py tests/test_plan_generation_node.py \
  tests/delivery/test_plan_session_models.py tests/delivery/test_plan_session_service.py \
  tests/delivery/test_plan_session_inv6_guard.py tests/services/test_plan_orchestration_engine.py -q
# 迁移一致性（No changes detected）
uv run python manage.py makemigrations --check --dry-run
# 工具名漂移零残留
rg -n "search_code" workflows/ agents/ prompts/ --glob '!**/tests/**'
# engine 不旁路 status
rg -n "\.status\s*=" services/plan_orchestration/engine.py
```

## Deferred / 后续 phase 接入点（非本 phase 缺陷）

- canonical `PlanVersion` 落库 → Phase 37（`current_plan_version` 本 phase UUID 软引用占位）。
- 真实 router/recall（38）、research fan-out（39）、merge + PlanValidator 扩展（40，在本 phase verify_plan 基础上扩展）、Clarification 回路 + 事件 taxonomy 真实发射 + workflow 入口（41）、Chat 入口（42）。骨架 stage 以 `NotImplementedError` 显式标注接入 phase。

## Gaps

None —— 4 项成功标准全部满足，无阻断缺口。
