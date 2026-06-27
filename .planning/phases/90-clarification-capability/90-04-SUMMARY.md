---
phase: 90-clarification-capability
plan: 04
subsystem: api
tags: [django, async, sync_to_async, clarification, plan_orchestration, inv6, helper, naming-collision]

# Dependency graph
requires:
  - phase: 90-02
    provides: ClarificationService.create_round（结构化澄清轮次容器 + N 子题唯一写入入口）
provides:
  - plan_orchestration.ask_clarification 入口无关 helper（薄封装 create_round，写 delivery.Clarification，携 origin_repo）
  - barrel re-export `from services.plan_orchestration import ask_clarification`
  - 与 chat tool agents/tools/clarification.py:ask_clarification 同名撞车防护（模块路径区分 + 守护测试）
affects: [91 出口面/回流 resume, 94 入口统一（编排任意点主动发问收口同一 helper）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "入口无关编排 helper：薄封装 service 写入收口（create_round），不驱动 advance / 不挂起 / 不写 status（驱动是入口私有，对齐 entrypoint.py / resume.py 精神）"
    - "同名撞车防护：plan_orchestration helper 与 chat tool 经模块路径区分，docstring 显式标注、守护测试断言 __module__，绝不复用/import chat 资产"
    - "函数内 lazy import 规避 import 环（barrel → delivery.services）"

key-files:
  created:
    - server/services/plan_orchestration/ask_clarification.py
    - server/tests/services/test_ask_clarification_helper.py
  modified:
    - server/services/plan_orchestration/__init__.py

key-decisions:
  - "helper 仅薄封装 create_round——不驱动 advance、不挂起 marker、不碰 session.status（status 只经 transition），驱动是入口私有"
  - "命名撞车经模块路径区分（保留 ask_clarification 命名，不改名 ask_plan_clarification），docstring + 守护测试双重防护"
  - "TYPE_CHECKING 下声明返回/参数类型（Clarification / ClarificationService），运行期 lazy import 规避 import 环"

patterns-established:
  - "Pattern: 入口无关 helper 薄封装 service 写入收口，驱动/挂起留给各入口私有"
  - "Pattern: 同名资产经模块路径区分 + 守护测试断言 __module__ 防误调"

requirements-completed: [CLARIFY-03]

# Metrics
duration: 4min
completed: 2026-06-27
---

# Phase 90 Plan 04: 入口无关 ask_clarification helper Summary

**新增 `services.plan_orchestration.ask_clarification` 入口无关 helper：薄封装 `ClarificationService.create_round` 写 `delivery.Clarification` 轮 + 多子题（携 origin_repo、守 INV-6），不驱动 advance / 不挂起；与同名 chat tool 经模块路径区分并加守护测试防撞名。**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-27T06:50:47Z
- **Completed:** 2026-06-27T06:54:10Z
- **Tasks:** 2
- **Files modified:** 3（2 created + 1 modified）

## Accomplishments
- 新建 `ask_clarification(session, questions, *, origin_repo=None, clarification_service=None) -> Clarification`：函数内 lazy import `ClarificationService`，实现仅 `svc.create_round(session, questions, origin_repo=origin_repo)`——**不**驱动 `engine.advance`、**不**挂起 marker、**不**碰 `session.status`（驱动是入口私有，对齐 `entrypoint.py` / `resume.py` 精神）。
- barrel：`plan_orchestration/__init__.py` 加 import + `__all__` 条目，`from services.plan_orchestration import ask_clarification` 可用（`__init__.py` 90-03 未碰，无冲突）。
- 命名撞车防护（Pitfall 1 / T-90-04-02）：模块 docstring 显式标注与 chat tool `agents/tools/clarification.py:ask_clarification`（写 `chat.ConversationIntentTrace` 走 LangGraph interrupt）同名但语义不同，靠模块路径区分，绝不复用/import/改动 chat 资产。
- 守护测试 `tests/services/test_ask_clarification_helper.py`（与既有 `tests/test_ask_clarification_tool.py` chat tool 测试显式区分）：写 delivery 轮 + 多子题 / 携 origin_repo / 调用不改 `session.status` / 注入 service 复用 / `__module__` 区分 chat tool，5 测全绿。

## Task Commits

Each task was committed atomically:

1. **Task 1: 新建 ask_clarification helper + barrel re-export** - `68f0b32e3` (feat)
2. **Task 2: ask_clarification helper 守护测试** - `bd936e4a1` (test)

**Plan metadata:** (本次 docs commit，见末尾)

## Files Created/Modified
- `server/services/plan_orchestration/ask_clarification.py` - 入口无关 ask_clarification helper（薄封装 create_round，写 delivery.Clarification，携 origin_repo；docstring 标注同名撞车防护）
- `server/services/plan_orchestration/__init__.py` - barrel 加 `ask_clarification` import + `__all__` 条目
- `server/tests/services/test_ask_clarification_helper.py` - helper 守护测试（写 delivery + origin_repo + 不驱动/不挂起 + 模块路径区分）

## Decisions Made
- **helper 仅薄封装 create_round**：不驱动 advance、不挂起、不写 status——驱动与挂起映射是各入口私有（对齐 `entrypoint.py` / `resume.py` docstring「驱动是入口私有」）。
- **命名撞车经模块路径区分**：保留 `ask_clarification` 命名（不改名 `ask_plan_clarification`），靠 `services.plan_orchestration` 包路径与 chat tool 区分，docstring + 守护测试（断言 `__module__`）双重防护。
- **TYPE_CHECKING 类型声明 + 运行期 lazy import**：`Clarification` / `ClarificationService` 类型注解放 `TYPE_CHECKING`，运行期在函数内 lazy import，规避 barrel → delivery.services import 环。

## Deviations from Plan

None - plan executed exactly as written.

唯一执行细节：Task 1 plan 的 `<automated>` verify 命令 `uv run python -c "..."` 直接运行时报 `ImproperlyConfigured`（Django settings 未配置，与 helper 代码无关），补 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 后通过（断言 helper 是 async + `__module__` 正确）。非代码偏离。

## Issues Encountered
None - helper 一次通过，5 守护测试全绿，ruff format/check + mypy 干净。INV-6 子模型 grep 守护（90-02）跑通无回归（helper 写入只经 service，无旁路写）。

## Threat Surface Scan
threat_model 四项 mitigate 均已落实：T-90-04-01（helper 仅薄封装 `create_round` 不旁路写表，由 90-02 grep 守护覆盖，本 plan 跑通无新 offender）；T-90-04-02（与 chat tool 同名经模块路径区分，docstring 显式标注 + 守护测试断言 `__module__`，绝不 import/改 chat 资产）；T-90-04-03（helper 不驱动 advance / 不挂起 / 不碰 `session.status`，守护测试断言调用前后 status 不变）；T-90-04-04（helper 只把 `session` 透传给 service，service 内 `sync_to_async`，无裸 lazy-FK）。无新增网络端点/认证路径/信任边界 schema 变化，无新威胁面。

## Known Stubs
None - helper 落地真实写入封装（经 create_round 写 delivery），无 UI 渲染、无 mock 数据。下游编排任意点（架构师融合卡住 / 调研容器卡住，Phase 91/94）将消费本 helper 主动发问。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 编排层主动发问能力就绪：编排任意点可调 `ask_clarification` 产结构化澄清请求（携 origin_repo），与 engine 自动澄清（ClarifyAdapter）共用同一写入收口 `create_round`，不造两套。
- Phase 91 出口面/回流 resume、Phase 94 入口统一可直接复用本 helper。
- CLARIFY-03 完成，Phase 90 四个 plan（90-01 数据脊柱 / 90-02 写入收口 / 90-03 ClarifyAdapter LLM 接线 / 90-04 ask_clarification helper）全部就绪。

---
*Phase: 90-clarification-capability*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/ask_clarification.py
- FOUND: server/tests/services/test_ask_clarification_helper.py
- FOUND: .planning/phases/90-clarification-capability/90-04-SUMMARY.md
- FOUND commit 68f0b32e3 (Task 1)
- FOUND commit bd936e4a1 (Task 2)
