---
phase: 36-plansession
plan: 01
subsystem: agents-tools / workflows
tags: [PF-01, PF-02, tool-registry, verify_plan, fail-loud]
requires: []
provides:
  - "统一检索工具名 search_repository_code（prompt + get_enabled_tools）"
  - "build_langchain_tools 未知工具 fail-loud"
  - "verify_plan execution_plan schema 校验（Phase 40 PlanValidator 基础）"
affects:
  - server/workflows/nodes/ai/plan_generation.py
  - server/agents/tools/langchain_adapter.py
  - server/agents/tools/verify_plan.py
  - server/agents/tools/__init__.py
tech-stack:
  added: []
  patterns: ["fail-loud whitelist", "tool-name registry guard test"]
key-files:
  created:
    - server/tests/workflows/test_plan_generation_tools_guard.py
    - server/tests/agents/test_verify_plan.py
  modified:
    - server/workflows/nodes/ai/plan_generation.py
    - server/agents/tools/langchain_adapter.py
    - server/agents/tools/verify_plan.py
    - server/agents/tools/base.py
    - server/agents/tools/__init__.py
    - server/tests/test_langchain_adapter.py
    - server/tests/test_plan_generation_node.py
decisions:
  - "统一到注册名 search_repository_code，不引入工具别名机制"
  - "未知工具 fail-loud raise（含可用工具集），不再静默 continue"
  - "send_plan_card 补登记到 agents.tools 包（fail-loud 暴露的潜在 wiring 缺口）"
metrics:
  duration: "~25m"
  completed: 2026-06-16
---

# Phase 36 Plan 01: 前置修复 PF-01/PF-02 Summary

统一 server 端方案生成检索工具名到注册名 `search_repository_code`，把 `build_langchain_tools` 的静默跳过改为 fail-loud raise，并把 `verify_plan` 校验从不存在的 `tasks` 对齐到 canonical `execution_plan`（逐项 `repository_id` + `coding_instruction`）。

## What Was Built

- **PF-01 工具名统一**：`get_enabled_tools()` 白名单与 `_PLAN_GENERATION_BASE_PROMPT` 内所有 `search_code` → `search_repository_code`（与 `space_tools.py` 注册名一致）。
- **PF-01 fail-loud**：`build_langchain_tools` 遇不在 `_tool_registry` 的工具名 → `raise ValueError`（消息含未知工具名 + `sorted(_tool_registry)`），不再 `continue` 静默退化为「无检索工具」。
- **PF-02 schema 对齐**：`verify_plan` Layer 1 必填字段 `["title","execution_plan"]`；逐项校验 `execution_plan[i]` 为 dict 且含非空 `repository_id`/`coding_instruction`；Layer 2 警告改读 `coding_instruction` 长度。契约 `{valid,errors,warnings,summary}` + `success=True` 不变。
- **守护测试**：工具名一致性守护（`get_enabled_tools` 全在注册表、prompt 无 `search_code`）+ adapter fail-loud + verify_plan 有效/各类无效用例。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2/3 - Missing wiring surfaced by fail-loud] 补登记 send_plan_card**
- **Found during:** Task 1（fail-loud 实装后 `test_plan_generation_node.py` 3 个 happy-path 测试转 failed）
- **Issue:** `agents/tools/__init__.py` 从未 import `agents.tools.send_plan_card`，故 `_tool_registry` 在 app init 后不含 `send_plan_card`。改 fail-loud 前它被静默跳过（与 PF-01 同类根因——方案节点其实从未真正拥有 send_plan_card），改后则在装配期 raise，使节点必 failed。
- **Fix:** 在 `agents/tools/__init__.py` 加 `from agents.tools.send_plan_card import send_plan_card` + `__all__`，使白名单全部工具名在 `import agents.tools` 后均已注册（也使守护测试稳健，不依赖测试间副作用注册）。
- **Files modified:** server/agents/tools/__init__.py
- **Commit:** 3bc843049

**2. [Rule 1 - Test regression] 更新既有 node 测试断言**
- `test_plan_generation_node.py` 断言 `"search_code" in tools` → `"search_repository_code" in tools`（由本改动直接引起）。

**3. [Rule 3 - Convention] base.py docstring 示例工具名**
- `@tool` 装饰器 docstring 内的示例工具名 `search_code` → `search_repository_code`，避免示例诱导误用未注册名 + 满足 `rg search_code agents/` 无残留的验证。

## Verification Evidence

- `pytest tests/test_langchain_adapter.py tests/workflows/test_plan_generation_tools_guard.py tests/agents/test_verify_plan.py tests/test_plan_generation_node.py` → **31 passed**。
- `rg -n "search_code" workflows/ agents/ prompts/ --glob '!**/tests/**'` → **NO RESIDUAL**。
- `ruff format --check`（5 个改动源文件）→ 通过。
- 已核对 `plan_generation.py:486-490` 经 `verify_plan` 结果读取 `entry["input"]["plan"]`（读 input 不读 output），本次 verify_plan 改动不触碰该路径，未回归。

## Success Criteria

- ✅ 成功标准 1（PF-01）：prompt 引用名与注册名一致，未知工具 fail-loud raise。
- ✅ 成功标准 2（PF-02）：verify_plan 对齐 execution_plan，真正命中关键字段。

## Self-Check: PASSED
- FOUND: server/tests/workflows/test_plan_generation_tools_guard.py
- FOUND: server/tests/agents/test_verify_plan.py
- FOUND commit e8c18fedc (test), 3bc843049 (fix)
