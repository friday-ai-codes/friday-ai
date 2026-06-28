---
phase: 95-decompose-llm
plan: 02
subsystem: plan_orchestration
tags: [llm, decompose, segments, call_source, fail-soft, json-parsing, observability]

# Dependency graph
requires:
  - phase: 95-decompose-llm (95-01)
    provides: CallSource.PLAN_DECOMPOSE = "plan_decompose" 受控枚举 + LOGGING-SPEC §4.1 登记
  - phase: 90-clarification-capability
    provides: clarification_questions.py 权威样板（单轮 LLM 产结构化 JSON + 健壮解析 + use_call_source + fail-soft）
provides:
  - "server/services/plan_orchestration/decompose_segments.py：入口无关 LLM 拆分 helper"
  - "agenerate_decomposition_segments(*, requirement_text, include_repos, max_segments)：LLM 跨仓拆 segments，失败/无 model/空 → None（best-effort）"
  - "normalize_decomposition_segments：防御 LLM 畸形输出（缺 title 跳过/非法 layer 回退空/字段强转 strip/上限截断）"
  - "_parse_segments_json：健壮 JSON 解析（```json 代码块/裸 JSON/顶层 list）"
affects: [95-decompose-llm, plan_orchestration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "decompose 与 clarification 同构问题：复制 clarification_questions.py 机制（解析/normalize/content_to_text/use_call_source/fail-soft），仅改 prompt/schema/枚举值，不重新发明"
    - "best-effort LLM helper 返回 None 作为「不可用」信号，交由上游触发回退（区别于 clarification 返回 []）"

key-files:
  created:
    - server/services/plan_orchestration/decompose_segments.py
    - server/tests/services/test_decompose_segments.py
  modified: []

key-decisions:
  - "采用 RESEARCH 推荐 union schema：LLM 成功路径产 list[dict]（title/module/layer/repo_hint），fail-soft 回退由上游 95-03 _decompose 做 splitlines（保持现状 list[str]，下游断言零改动）"
  - "helper 失败信号用 None（非 []），语义上区分『LLM 拆分不可用→回退』，与 clarification 的『信息充分→[]』不同"
  - "normalize 空也返回 None：解析后无有效 segment 视为 LLM 拆分失败，触发上游回退"

patterns-established:
  - "镜像 clarification_questions.py 的纯函数 + 异步接线分层：纯函数单测不触网，异步接线 patch 模块级 aresolve/build_chat_model + AsyncMock"
  - "call_source 标注可测：patched ainvoke 内读 get_call_source() 断言调用期 contextvar == 'plan_decompose'"

requirements-completed: [DECOMP-01]

# Metrics
duration: ~10min
completed: 2026-06-28
---

# Phase 95 Plan 02: decompose_segments LLM 拆分 helper Summary

**入口无关的 `decompose_segments.py`：单轮 LLM 把需求跨仓业务线/模块/前后端拆为结构化 `segments`（list[dict]），健壮 JSON 解析 + normalize 防御 + `use_call_source(PLAN_DECOMPOSE)` 标注 + started/completed/failed 生命周期事件，全部失败路径 best-effort 返回 `None` 绝不抛——逐段镜像 clarification_questions.py 样板**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-27T17:38:00Z
- **Completed:** 2026-06-27T17:45:00Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- `agenerate_decomposition_segments`：`aresolve` → `default_model` 守卫 → `build_chat_model(streaming=False)` → `use_call_source(CallSource.PLAN_DECOMPOSE)` → `ainvoke` → `_parse_segments_json` → `normalize`，成功返回 `list[dict]`
- 全失败路径（缺 model / aresolve|build|ainvoke 异常 / 解析空 / 空白 requirement）返回 `None`，`except Exception` best-effort 绝不阻断编排
- `normalize_decomposition_segments` 防御：缺 title 跳过、非法 layer（非 frontend/backend/fullstack/infra）回退空、module/repo_hint 强转 str/strip、`_MAX_SEGMENTS=20` 截断
- `_parse_segments_json` 容错 ```json 代码块 / 裸 JSON / 顶层 list，非法返回 `[]`；`_content_to_text` 兼容 reasoning content_blocks
- 观测：`plan_decompose_started/completed/failed/no_default_model` 结构化事件 + `duration_ms`（category=sampling, component=plan_orchestration）；日志只记 `requirement_len`/计数，不落原文（脱敏）
- 专用单测 20 passed（纯函数解析/normalize/content/prompt 14 不触网 + 异步 happy/缺 model/aresolve 抛/畸形 content/空 requirement/call_source 标注 6）

## Task Commits

Each task was committed atomically:

1. **Task 1: decompose_segments.py 纯函数 + 健壮 JSON 解析 + normalize 防御** - `6782b1825` (feat)
2. **Task 2: agenerate_decomposition_segments 异步 LLM 接线 + 观测 + fail-soft** - `19c62cc60` (feat)

_Note: TDD 任务实现与其单测同源原子提交（impl + test 同 commit）。_

## Files Created/Modified
- `server/services/plan_orchestration/decompose_segments.py` - 入口无关 LLM 拆分 helper（`agenerate_decomposition_segments` / `normalize_decomposition_segments` / `_parse_segments_json` / `_content_to_text` / `_system_prompt` / `_build_prompt`）
- `server/tests/services/test_decompose_segments.py` - 纯函数 + 异步接线单测（14 纯函数不触网 + 6 异步 patch aresolve/build_chat_model）

## Decisions Made
- **union schema（RESEARCH 推荐）：** LLM 成功路径 list[dict]，fail-soft 回退路径（95-03 splitlines list[str]）下游无消费方、异构成本为零，回退路径零行为变更最稳。
- **失败信号 None（非 []）：** decompose 失败要触发上游 splitlines 回退，用 `None` 表达「LLM 拆分不可用」；clarification 用 `[]` 表达「信息充分无需澄清」，语义不同故不照搬返回值。
- **normalize 空 → None：** 解析后无有效 segment 等同拆分失败，统一返回 None 触发回退（记 `plan_decompose_completed` segment_count=0）。

## Deviations from Plan

None - plan executed exactly as written.

（Task 1 移除了计划草拟的 `import time`——纯函数阶段未用，ruff F401 拦截；`time` 在 Task 2 随异步函数重新引入。属同计划内分阶段引入，非偏离。）

## Issues Encountered
- 计划 `<verification>` 的裸 `python -c "import ..."` 在未设 `DJANGO_SETTINGS_MODULE` 时因包 `__init__` 间接引入 engine（依赖 Django settings）而 `ImproperlyConfigured`；用 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 后 import ok。pytest 路径自带 Django 配置，不受影响。

## User Setup Required
None - 纯仓内 helper，复用既有 llm_factory/provider_config/call_source/langchain/structlog，无新依赖、无迁移、无外部服务配置、无供应链面。

## Threat Flags
无新增计划外安全面——helper 仅消费既有 `build_chat_model`（SecretStr 包装 api_key 不手碰）+ `use_call_source` 受控枚举；LLM 输出经 `_parse_segments_json` + `normalize` 双层防御（T-95-03/04/05/06 全部按 threat_model mitigate 落实）。

## Next Phase Readiness
- `agenerate_decomposition_segments` 就绪，95-03 `engine._decompose` 可接线：非空 list[dict] 写入 `decomposition["segments"]`，`None` 触发现状 splitlines 回退（保持 `test_plan_orchestration_engine.py` 既有断言）。
- 无阻塞。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/decompose_segments.py
- FOUND: server/tests/services/test_decompose_segments.py
- FOUND: .planning/phases/95-decompose-llm/95-02-SUMMARY.md
- FOUND commit: 6782b1825 (Task 1)
- FOUND commit: 19c62cc60 (Task 2)

---
*Phase: 95-decompose-llm*
*Completed: 2026-06-28*
