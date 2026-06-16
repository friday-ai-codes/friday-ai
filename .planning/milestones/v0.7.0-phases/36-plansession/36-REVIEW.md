---
phase: 36-plansession
reviewed: 2026-06-16T07:45:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - server/agents/tools/langchain_adapter.py
  - server/agents/tools/verify_plan.py
  - server/agents/tools/__init__.py
  - server/workflows/nodes/ai/plan_generation.py
  - server/delivery/models/plan_session.py
  - server/delivery/services/plan_session_service.py
  - server/delivery/migrations/0009_plansession.py
  - server/services/plan_orchestration/engine.py
  - server/services/plan_orchestration/protocols.py
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: findings_resolved
resolved_at: 2026-06-16T08:00:00Z
resolution:
  fixed: [CR-01, WR-01, IN-01, IN-02]
  skipped: [WR-02]
  skipped_reason: WR-02 属工具注册架构性重构（集中化 import），超出本 phase 范围，留待后续 phase 处理。
---

# Phase 36: Code Review Report

**Reviewed:** 2026-06-16T07:45:00Z
**Depth:** standard
**Files Reviewed:** 9 (source only; tests excluded from finding scope per review policy)
**Status:** findings_resolved（CR-01 / WR-01 / IN-01 / IN-02 已修复并补回归测试；WR-02 超范围跳过）

> **修复记录（2026-06-16）：** 4 项 actionable findings（CR-01/WR-01/IN-01/IN-02）已逐条原子提交修复并补回归测试。受影响测试套件全绿：`tests/delivery` + `tests/agents/test_verify_plan.py`（246 passed）、`plan_orchestration/engine` 选择集（108 passed），delivery 套件无回归。WR-02（工具注册集中化）为架构性重构、超本 phase 范围，未处理。

## Summary

Phase 36 交付了 PF-01/PF-02 前置修复 + PlanSession 状态机 + 编排 engine 骨架。整体实现质量高、与 36-CONTEXT 决策与 DOMAIN §6/§14 高度一致：`_ALLOWED` 转移表逐行对齐 §14（8 态 + fail 特判完整）、engine 经 `transition` 驱动不旁路 `status`、async/ORM 全部经 `sync_to_async`/`afirst()` 桥接无同步 ORM 误用、`build_langchain_tools` fail-loud 改动安全（见下分析）。

**PF-01 fail-loud 回归分析（指令 #3）：无破坏现有 caller 的回归。** 仅 `base_agent.py:661`（workflow）与 `chat_runner.py:580`（chat）两处调用 `build_langchain_tools`。两条链路喂入的工具名均已注册：workflow 的 `get_enabled_tools` 6 个 base 工具全在 `agents/tools/__init__.py`（含本 phase 补登记的 `send_plan_card`）；chat 的 `_BASE/_INDEXED/_DEEP_ANALYSIS_TOOL_NAMES` 全名经 `chat_runner` 顶部 `import agents.tools.chat_tools/coding_tools/...`（副作用注册）保障。workflow 路径的 `ValueError` 被 `base_agent.py:816 except ValueError` 捕获为 `NodeResult(status=failed)`，不会击穿引擎。`send_plan_card` 补登记完整。

但发现 1 个 critical 健壮性缺陷（verify_plan 对非 list `execution_plan` 抛异常，违反其自身声明的 fail-safe 契约 T-36-01-01），以及状态机并发/工具注册完整性两处 warning。

## Critical Issues

### CR-01: verify_plan 对非 list 真值 `execution_plan` 抛异常（违反 fail-safe 契约） — ✅ RESOLVED

> **已修复**（commit `fix(36): CR-01 ...`）：Layer 1 对真值非 list 的 `execution_plan` 显式记 `{field: "execution_plan", message: "execution_plan 必须是数组"}` 并归一为 `[]`，Layer 2 不再崩溃；补 str/dict/int/None 回归用例（断言 `success=True` 且 `valid=False`，不抛异常）。`test_verify_plan.py` 13 passed。

**File:** `server/agents/tools/verify_plan.py:50` + `:76`
**Severity:** critical / blocker

**Issue:** 工具 docstring 与 36-01-PLAN threat model T-36-01-01 明确承诺「半可信输入：非法结构落 errors 不抛异常（工具恒 success=True）」。但当 LLM 产出的 `plan["execution_plan"]` 是**真值但非 list**（如字符串、dict、int）时，Layer 1 的逐项校验被 `if isinstance(execution_plan, list)`（:50）跳过且不记任何 error，随后 Layer 2 在 `if not errors:` 为真时执行 `for i, item in enumerate(execution_plan): item.get(...)`（:76-77）——对字符串/dict 抛 `AttributeError`，对 int 抛 `TypeError`，工具直接崩溃而非返回 `{valid: False, errors:[...]}`。

已复现：
```
{'title':'valid title','execution_plan':'a string'} -> AttributeError 'str' object has no attribute 'get'
{'title':'valid title','execution_plan':{'a':1}}    -> AttributeError 'str' object has no attribute 'get'
{'title':'valid title','execution_plan':5}          -> TypeError 'int' object is not iterable
```
该输入完全在 LLM 半可信产出范围内（execution_plan 写成对象而非数组是常见 LLM 错误），且现有测试 `test_verify_plan.py` 未覆盖此类型——`test_empty_execution_plan` 只测 `[]`，无非 list 真值用例。这恰是 verify_plan 作为 Phase 40 PlanValidator 地基应当 fail-safe 兜住的场景，却反而成为崩溃点。

**Fix:** Layer 1 在跳过非 list 时显式记 error，使 Layer 2 因 `errors` 非空而短路；并加固 Layer 2 遍历：

```python
    execution_plan = plan.get("execution_plan", [])
    if not isinstance(execution_plan, list):
        # execution_plan 存在但不是数组：记错误而非静默跳过（避免 Layer 2 崩溃）
        if "execution_plan" in plan and plan["execution_plan"]:
            errors.append(
                {"field": "execution_plan", "message": "execution_plan 必须是数组"}
            )
        execution_plan = []
    else:
        for i, item in enumerate(execution_plan):
            ...  # 现有逐项校验不变
```
同时建议在 `test_verify_plan.py` 增 `execution_plan` 为 str/dict/int 的回归用例，断言 `result.success is True` 且 `valid is False`（不抛异常）。

## Warnings

### WR-01: PlanSessionService.transition / engine.advance 无并发保护，存在 TOCTOU 双推进 — ✅ RESOLVED

> **已修复**（commit `fix(36): WR-01 ...`）：`_apply_transition_sync` 改为以 `status == from_status` 为前置条件的原子更新 `PlanSession.objects.filter(id=, status=from_status).update(...)`，断言影响行数 ==1，否则抛 `ConcurrentTransitionError`，绝不盲写覆盖（并发/陈旧 advance 不能同时成功推进同一转移，保 resume 安全）。`update()` 不触发 `auto_now`，显式写 `updated_at=timezone.now()`。补陈旧转移被拒回归测试。INV-6 guard 仍绿（`.update` 落在唯一 writer 模块）。

**File:** `server/delivery/services/plan_session_service.py:107`、`:118-129`；`server/services/plan_orchestration/engine.py:67`、`:82`
**Severity:** high / warning

**Issue:** `transition` 以传入 `session` 对象的**内存态 `session.status`** 做合法性判定（:107 `_ALLOWED.get(session.status, {})`），`_apply_transition_sync` 的 `save(update_fields=["status", ...])`（:129）无 `status` 前置条件、无 `select_for_update` 行锁、无乐观版本号。engine `advance`（:67）同样直接信任传入 `session.status` 分派，不在入口 reload。

后果：当 workflow 与 chat「共用同一底层」（本 phase 核心目标）或两个 worker 同时 resume 同一 `PlanSession` 行时——两者各自加载到相同 `status`（如 `routing`），各自 `advance` → 各自 `router.route()` + `transition("routed")`，第二次 transition 基于陈旧内存态再次推进并盲写 DB 行，导致**副作用重复执行**（真实实现里即重复 fan-out/重复路由）与状态被覆盖。这直接削弱 T-36-02-03/“可从任意 status resume”所声称的可恢复性保证。

骨架阶段可接受暂缓，但应在 38/41 接真实副作用前落地。**Fix（建议）：** `_apply_transition_sync` 内用 `PlanSession.objects.filter(id=session.id, status=from_status).update(...)` 做条件更新并断言影响行数==1，或在 transition 入口 `select_for_update()` 重读 status 后再校验；至少在本文件 docstring 标注“调用方须保证单飞/串行 advance”并加 TODO。

### WR-02: 工具注册依赖 import 副作用且 `__init__.py` 不完整，`enabled_tools` 配置链路存在 fail-loud 隐患 — ⏭️ SKIPPED（超范围）

> **跳过**：注册集中化（在 `agents/tools/__init__.py` 统一 import 所有 `@tool` 模块）属架构性重构，牵涉 import 顺序与进程入口耦合，超出本 phase（前置修复 + 状态机骨架）范围。当前两条 caller（workflow/chat）均安全（见 Summary 回归分析），非现网回归。留待后续 phase 处理。

**File:** `server/agents/tools/__init__.py:12-48`；`server/workflows/nodes/ai/plan_generation.py:305-309`
**Severity:** medium / warning

**Issue:** `_tool_registry` 的填充完全靠模块 import 副作用。`agents/tools/__init__.py` **未** import `chat_tools` / `coding_tools` / `deep_analysis_registry`（这些工具名 `get_space_overview`/`browse_file_content`/`list_space_structure`/`deep_analysis`/`create_coding_plan`/`update_coding_plan` 仅在 `chat_runner` 顶部被显式 import 注册）。当前两条 caller 均安全（见 Summary），但 `get_enabled_tools` 允许用户经 `enabled_tools` 节点配置追加任意工具名（:306-309）——若在一个从未 import `chat_runner` 的 workflow 进程中配置了 chat-only 工具名，PF-01 fail-loud 会把原先「静默降级」变为 `NodeResult(status=failed)` 硬失败。这是 import 顺序脆弱性 + 注册不集中导致的潜在行为变化（非当前回归，但属 PF-01 改动放大面）。

**Fix（建议）：** 将注册集中——把所有 `@tool` 模块在 `agents/tools/__init__.py` 统一 import（如 `chat_tools`/`coding_tools`/`deep_analysis_registry`），使 `_tool_registry` 与进程入口无关、可预测；或在 `build_langchain_tools` 的 `ValueError` 文案中提示「该工具可能未被本进程 import 注册」以便诊断。

## Info

### IN-01: transition("fail") 无来源状态守护，可覆盖既有 error / 从 done 回落 failed — ✅ RESOLVED

> **已修复**（commit `fix(36): IN-01 ...`）：`_fail` 加终态守护——已 `done`/`failed` 的会话再 `fail` 为幂等 no-op，不无声回落 `done→failed`、不二次覆盖首个诊断 `error`（保留首因）。补两条终态守护测试。

**File:** `server/delivery/services/plan_session_service.py:104-105`、`:131-143`
**Severity:** low / info

**Issue:** `fail` 走特判（:104）不查 `_ALLOWED`，对任意状态（含 `done`、已 `failed`）均置 `failed` 并以新 `error` 覆盖 `session.error`（:142）。§14「任意 → failed」语义上允许，但缺幂等/终态守护意味着对一个已 `done` 的会话误调 `fail` 会无声回落，或二次 fail 覆盖首次的诊断 error。建议对 `done`/`failed` 终态的 fail 加 no-op 或保留首个 error（append 而非 overwrite）。

### IN-02: create_session 未校验 entrypoint 合法值 — ✅ RESOLVED

> **已修复**（commit `fix(36): IN-02 ...`）：`create_session` 对非 `workflow`/`chat` 的 `entrypoint` 显式 `raise ValueError`（Django `choices` 仅 `full_clean()` 校验、`create()` 不触发），与状态机「非法即 raise」风格一致。补回归测试。

**File:** `server/delivery/services/plan_session_service.py:67-91`
**Severity:** low / info

**Issue:** `create_session(entrypoint: str, ...)` 直接 `PlanSession.objects.create(entrypoint=entrypoint, ...)`，而 Django `choices` 仅在 `full_clean()` 时校验、`create()` 不触发。传入非 `workflow`/`chat` 的字符串会被静默落库。作为单一写入入口建议显式校验 `entrypoint in PlanSessionEntrypoint.values` 否则 raise，与状态机「非法即 raise」风格一致。

---

_Reviewed: 2026-06-16T07:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
