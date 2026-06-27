---
phase: 95-decompose-llm
reviewed: 2026-06-27T18:04:22Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - server/agents/call_source.py
  - server/services/plan_orchestration/decompose_segments.py
  - server/services/plan_orchestration/engine.py
  - server/tests/services/test_decompose_segments.py
  - server/tests/services/test_plan_orchestration_engine.py
  - server/tests/test_model_usage_call_source.py
  - .planning/observability/LOGGING-SPEC.md
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
  resolved_at: 2026-06-28T02:08:00Z
---

# Phase 95: Code Review Report

**Reviewed:** 2026-06-27T18:04:22Z
**Depth:** deep
**Files Reviewed:** 7
**Status:** issues_found

## Summary

审查 Phase 95（DECOMP-01）的 LLM 跨仓拆分接线。核心实现质量高：`decompose_segments.py`
逐段镜像权威样板 `clarification_questions.py`（CLARIFY-02），fail-soft 契约完整且
经测试充分覆盖；`engine._decompose` 的 LLM→splitlines 回退路径正确，恒走
`transition("decomposed")`，DECOMP-01 关键不变式（绝不落 FAILED / 保留 routing 契约键 /
不直 mutate status）均成立。

**未发现 BLOCKER**——无逻辑错误、无注入、无密钥硬编码、无认证绕过。

关键路径逐项核验：
- **fail-soft**：缺 default_model / aresolve 抛 / build / ainvoke 抛 / 解析异常 / 空 →
  helper 恒返回 `None`（`except Exception` 兜底），`_decompose` 据此 splitlines 回退，
  `if result:` 正确区分 `None`/空 list 与非空 list。✔
- **健壮 JSON 解析**：代码块/裸 JSON/顶层 list/非 dict 项剔除/非法 → `[]`，不抛。✔
- **normalize 防御**：缺 title 跳过、非法/缺 layer 回退空、字段强转 str/strip、截断
  `_MAX_SEGMENTS`。✔（截断顺序有一处可改进，见 IN-01）
- **routing 契约保留**：两路径均落 `{requirement_text, include_repos, segments}`，
  既有 engine 断言零改（union schema：segments 可为 `list[str]` 或 `list[dict]`）。✔
- **观测**：`use_call_source(PLAN_DECOMPOSE)` 包裹 ainvoke；started/completed/failed +
  `duration_ms`（completed/failed 均带），`category=sampling` / `component=plan_orchestration`；
  仅记 `requirement_len`/`include_repos_count`/`segment_count`，不落需求原文。✔
- **枚举完整性**：`CallSource` 32 值，docstring 计数 30→32 一致，`test_model_usage_call_source`
  以照抄基准守护（`len(...) == 32` + 含 `plan_decompose`）。✔
- **async**：纯 await 链，无阻塞 ORM；`_work_item_title` 走 async ORM `afirst()`。✔

唯一 WARNING 为上游异常文本脱敏的纵深防御缺口（已被自动 processor 部分缓解）；其余为
可选健壮性/级别纪律改进。

## Warnings

### WR-01: `plan_decompose_failed` 的 `error=str(exc)` 未经 `redact_secrets_in_text` 手动脱敏

**状态：RESOLVED（2026-06-28）** —— `decompose_segments.py` 顶部 `from common.logging import
redact_secrets_in_text`，`except` 分支改为 `error=redact_secrets_in_text(str(exc))`；新增测试
`test_agenerate_redacts_secret_in_failed_log` 以 `capture_logs` 断言含 `sk-ant-*` 凭证的上游异常
在 `plan_decompose_failed.error` 中被替换为 `***REDACTED***`。ruff/mypy/pytest 全绿。
（样板 `clarification_questions.py` 的同类回填未在本次范围内，留作后续统一约定。）

**File:** `server/services/plan_orchestration/decompose_segments.py:202-209`
**Issue:**
`except` 分支直接把 `error=str(exc)` 写入日志。`exc` 来自 `model.ainvoke`（langchain →
Provider HTTP），上游错误体可能回显 prompt 内容（含 `requirement_text` 业务原文），与本
phase「脱敏只记长度/计数、不落需求原文」目标相悖。观测强制规范亦要求「上游响应体/异常
文本手动走 `redact_secrets_in_text`」。

**缓解现状（降级而非排除）：** 全局 structlog `redact_credentials` processor 会对所有字符串
字段值跑 `SENSITIVE_VALUE_PATTERN.sub`，故 `sk-*/Bearer/AIza/PEM` 等**凭证格式**会被自动
脱敏；残余风险是上游错误回显的**需求原文**（非凭证模式）不被该 pattern 命中。注：此写法与
已合入的权威样板 `clarification_questions.py:170-176` 完全一致，属既有约定缺口而非本 phase 引入。

**Fix:**
```python
from common.logging import redact_secrets_in_text  # 顶部或就近 import

except Exception as exc:  # noqa: BLE001 — best-effort，绝不阻断编排
    logger.warning(
        "plan_decompose_failed",
        category="sampling",
        component="plan_orchestration",
        error=redact_secrets_in_text(str(exc)),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return None
```
（如团队认为应统一约定，宜同时回填 `clarification_questions.py`，避免样板继续传播。）

## Info

> **状态：DEFERRED（2026-06-28）** —— 以下 3 条 INFO 均为可选健壮性/级别纪律/文档措辞改进，
> 非缺陷，本次不处理，留作后续。

### IN-01: `normalize_decomposition_segments` 先截断后过滤，畸形前导项会压低有效产出

**File:** `server/services/plan_orchestration/decompose_segments.py:84-89`
**Issue:**
`for item in raw[:max_segments]` 先按 `max_segments` 切片，再在循环内跳过缺 title 项。当
前 `max_segments`(20) 个原始项中混入若干无 title 项时，最终有效 segments 会 < 20，即使
索引 20 之后仍有合法项。语义上是「限处理量防失控」，非错误行为，但与「最多保留 N 个**有效**
拆分项」的直觉略有偏差。
**Fix（如需「填满到 max 个有效项」语义）：** 先过滤再截断 ——
```python
result: list[dict[str, Any]] = []
for item in raw:               # 不先切片
    ...                        # 现有 title/layer/module/repo_hint 归一
    result.append({...})
    if len(result) >= max_segments:
        break
return result
```
若刻意要「限制处理总量」则现状可接受，建议在 docstring 注明取舍。

### IN-02: `plan_decompose_started` 与 `plan_decompose_completed` 均以 INFO 记录（category=sampling）

**File:** `server/services/plan_orchestration/decompose_segments.py:155-161, 186-200`
**Issue:**
单次 decompose 会产 started + completed 两条 INFO（外加可能的 fallback 一条）。事件标
`category="sampling"`，而观测规范对 sampling 类倾向「debug 或采样」。本调用为每会话一次的
低频编排阶段，INFO 量级可接受，且 started 事件比权威样板（仅记 completed）更完整；仅作级别
纪律提示，非缺陷。若后续 decompose 调用频次上升，可将 started 降 debug 或纳入采样。

### IN-03: `_decompose` 的「绝不落 FAILED」依赖 helper 自包异常，DB 层异常仍会落 FAILED

**File:** `server/services/plan_orchestration/engine.py:106-151`
**Issue:**
docstring 称 `_decompose` 恒走 `transition("decomposed")` 绝不落 FAILED。这对 **LLM 路径**
成立（helper 全程 `except Exception` 兜底）。但 `_work_item_title` 的 async ORM 查询
(`engine.py:307-312`) 或 `transition` 本身若抛（DB/基础设施故障），仍会被 `advance` 的通用
`except` 捕获并 `transition("fail")`。这属合理的基础设施失败语义，但与 docstring 的绝对措辞
略有出入。
**Fix:** 文档措辞收敛为「LLM 拆分任何失败路径绝不落 FAILED；基础设施(DB)异常按编排通用
失败语义处理」，避免读者误解为 `_decompose` 完全不可能 FAILED。无需改代码。

---

_Reviewed: 2026-06-27T18:04:22Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
