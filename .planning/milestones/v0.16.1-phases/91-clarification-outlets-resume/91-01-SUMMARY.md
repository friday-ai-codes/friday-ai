---
phase: 91-clarification-outlets-resume
plan: 01
subsystem: api
tags: [plan_orchestration, clarification, resume, multi_round, async, sync_to_async, inv6, observability]

# Dependency graph
requires:
  - phase: 90-02
    provides: ClarificationService.create_round / answer_round / ahas_pending（结构化澄清写入 + 幂等作答 + 统一 pending 谓词）
  - phase: 43-02
    provides: adrive_plan_session_to_pause_or_terminal（入口无关续驱 helper）
  - phase: 42-01
    provides: build_orchestration_engine（两入口共用 engine 工厂）
provides:
  - services.plan_orchestration.aanswer_round_and_resume（入口无关「作答 + 续推」共享回流 helper，barrel 导出）
  - ClarifyAdapter 多轮澄清（移除 CR-01 单轮硬限 + _MAX_CLARIFY_ROUNDS=6 上界 + 带已答重判）
  - ClarifyAdapter._collect_prior_answers（已答轮问答喂进重判输入，防同题死循环）
affects: [91-03 飞书澄清回调, 91-04 会话端续推 endpoint, 91-02 工作流发卡]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "入口无关回流 helper：answer_round + build_orchestration_engine + adrive 薄封装，飞书回调/会话 endpoint 同源调用（不造两套），入口私有重调度留各调用方"
    - "多轮澄清三段决策：pending 短路 → round_count 上界兜底 → policy + 带已答重判生成；超界带现有信息继续不无限挂起"
    - "带答案重判防死循环：已答子题答复拼进 agenerate_clarification_questions 的 requirement（最小 diff，不改生成器签名）"

key-files:
  created:
    - server/services/plan_orchestration/answer_resume.py
    - server/tests/services/test_answer_resume.py
  modified:
    - server/services/plan_orchestration/__init__.py
    - server/services/plan_orchestration/clarify_adapter.py
    - server/tests/services/test_engine_clarify.py

key-decisions:
  - "重判输入用「拼进 requirement」最小 diff，不给 agenerate_clarification_questions 加 prior_answers 参数（生成器为未提交 war-room 资产，避免把无关改动卷进本 plan commit）"
  - "_MAX_CLARIFY_ROUNDS=6（CONTEXT D Discretion 须 ≥5），较宽松上界实际极少触顶"
  - "首轮（round_count==0）保留 fail-soft 回退粗单题；多轮重判生成空视为信息足够放行（不再回退单题）"
  - "create_round 返回 Clarification | None，防御性 narrow（None→放行不挂起）以满足 mypy 并守 WR-02 空轮无限挂起精神"
  - "answer_resume 续推 helper 不驱动入口私有重调度（approve_node / chat barrier / marker）——留 91-03/91-04 各调用方"

patterns-established:
  - "Pattern: 入口无关回流 helper（engine 缺省=chat 入口、显式传=工作流入口；clarification_service 可注入复用）"
  - "Pattern: 多轮上界兜底日志仅记计数标量（round_count/session_id），澄清正文不内联日志（T-91-01-04）"

requirements-completed: [CLARIFY-06, CLARIFY-07]

# Metrics
duration: ~25min
completed: 2026-06-27
---

# Phase 91 Plan 01: 共享回流 helper + 多轮澄清放开 Summary

**新增入口无关「作答 + 续推」共享 helper `aanswer_round_and_resume`（薄封装 answer_round + build_orchestration_engine + adrive，供飞书回调/会话 endpoint 同源调用），并放开 ClarifyAdapter 多轮澄清——移除 CR-01 单轮硬限、带已答重判、`_MAX_CLARIFY_ROUNDS=6` 上界兜底防无限挂起。**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-27T07:49:00Z
- **Completed:** 2026-06-27T08:05:00Z
- **Tasks:** 2（均 TDD）
- **Files modified:** 5（2 新建 + 3 改）

## Accomplishments
- `aanswer_round_and_resume(clarification_or_id, answers, *, engine=None, clarification_service=None)`：① `answer_round` 按题幂等写入；② 由 `clar.session_id` 标量解析 `PlanSession`（解析不出 → 返回 None）；③ engine 缺省走 `build_orchestration_engine()`（chat 入口形态）、显式传入直接复用（工作流入口可带 node_execution_id）；④ `adrive` 续驱返回。barrel 导出，飞书回调（91-03）与会话 endpoint（91-04）可同源调用。
- ClarifyAdapter 多轮放开（CLARIFY-07）：**移除 CR-01 `Clarification.objects.filter(...).aexists()` 单轮硬限**，改为「`round_count` 上界兜底 + policy + 带已答重判」。已答信息不足 + 未达上界 → 再生成一轮（`round_no=round_count+1`）；重判信息足够（生成空）→ 放行 researching；达上界（6）→ 带现有信息继续、不再发轮 + best-effort log `clarification_round_cap_reached`。
- `_collect_prior_answers`：读已答子题（`order_by("clarification__round_no","order").values(...)`）组装文本拼进重判 `requirement`，确保答复改变重判输入、不同题死循环（Pitfall 2 / T-91-01-03）。
- INV-6：写入只经 `ClarificationService`（helper/adapter 内无 `Clarification.objects.create/.update/.save`，grep 守护无回归）；async 全程 `*_id` 标量 + `.values` 防裸 lazy-FK。
- best-effort 进出口埋点 `answer_round_and_resume_started/completed`（category=caller、component=plan_orchestration、duration_ms），观测失败吞掉绝不反噬业务。

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1 RED: failing test for aanswer_round_and_resume** - `5f1be5e20` (test)
2. **Task 1 GREEN: answer_resume.py + barrel export** - `b334374c1` (feat)
3. **Task 2 RED: failing multi-round / round_cap tests** - `9604cd62c` (test)
4. **Task 2 GREEN: 多轮放开 + _MAX_CLARIFY_ROUNDS + 带答案重判** - `56cd2291c` (feat)
5. **Deviation fix: helper docstring 避免误触 INV-6 grep** - `75bf0917d` (fix)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `server/services/plan_orchestration/answer_resume.py` - 新建入口无关回流 helper `aanswer_round_and_resume` + `_safe_log`
- `server/services/plan_orchestration/__init__.py` - barrel 加 import + `__all__` 追加 `aanswer_round_and_resume`
- `server/services/plan_orchestration/clarify_adapter.py` - `_MAX_CLARIFY_ROUNDS=6` 常量 + `clarify` 多轮重判改造 + `_collect_prior_answers` helper + docstring 更新
- `server/tests/services/test_answer_resume.py` - 新建 5 用例（同源续驱 / 缺省 build / 显式 engine 复用 / 注入 service / 幂等 / session 缺失）
- `server/tests/services/test_engine_clarify.py` - 新增 3 用例（多轮再发 round_no 递增 / 重判足够放行 / 达上界继续+log）+ `_answered_round` helper

## Decisions Made
- **重判输入「拼进 requirement」最小 diff**：`agenerate_clarification_questions` 是未提交的 war-room 资产（`?? clarification_questions.py`），给它加 `prior_answers` 参数会把无关改动卷进本 plan，故按 plan 二选一取「拼接 requirement」方案，不改生成器签名。
- **首轮 vs 多轮生成空分流**：首轮保留 fail-soft 回退粗单题（90-03 CR-01 用例零回归）；多轮重判生成空视为信息足够放行 researching。
- **create_round None 防御 narrow**：`create_round` 返回 `Clarification | None`（WR-02 空问题守护），questions 非空理论不触发，仍加 `if clar is None: return {"needs_clarification": False}` 满足 mypy 并守无限挂起精神。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] helper docstring 字面误触 INV-6 grep 守护**
- **Found during:** Task 2 验收（运行 `tests/delivery/test_clarification_service.py -k inv6`）
- **Issue:** `answer_resume.py` docstring 含字面串 `Clarification.objects.create/.update/.save`，被 `test_inv6_clarification_single_write_entry` 的 `"Clarification.objects.create" in line` 子串扫描误判为旁路写（该行非 `#` 注释开头，未被跳过）。
- **Fix:** 改述为「无任何 ORM create / update / save 旁路写」，避开字面子串。
- **Files modified:** server/services/plan_orchestration/answer_resume.py
- **Verification:** `uv run pytest tests/delivery/test_clarification_service.py -k inv6` → 2 passed
- **Committed in:** `75bf0917d`

**2. [Rule 3 - Blocking] create_round None 返回触发 mypy union-attr**
- **Found during:** Task 2 GREEN（`uv run mypy clarify_adapter.py`）
- **Issue:** `create_round` 返回 `Clarification | None`，`str(clar.id)` 触发 `union-attr` error。
- **Fix:** create_round 后加 `if clar is None: return {"needs_clarification": False}` 防御性 narrow（兼守 WR-02 空轮无限挂起精神）。
- **Files modified:** server/services/plan_orchestration/clarify_adapter.py
- **Verification:** `uv run mypy services/plan_orchestration/clarify_adapter.py answer_resume.py` → Success: no issues found in 2 source files
- **Committed in:** `56cd2291c`（Task 2 GREEN commit）

---

**Total deviations:** 2 auto-fixed（均 blocking）
**Impact on plan:** 仅为通过 INV-6 grep / mypy 门禁的最小调整，不影响 helper/adapter 语义与覆盖范围。无 scope creep。

## Issues Encountered
- None（除上述两项 deviation）。`agenerate_clarification_questions` 在无 provider 环境返回 []，使「多轮重判足够放行」与既有 `test_real_policy_answered_round_advances_no_second_clarification` 用例在真实 policy 路径下行为一致，零回归。

## Threat Surface Scan
threat_model 五项 mitigate 均落实：T-91-01-01（answer_round 已按 id+answered_at IS NULL 条件更新，helper 不重复造校验）；T-91-01-02（`_MAX_CLARIFY_ROUNDS=6` 上界 + adrive max_steps fail-soft，超界放行）；T-91-01-03（`_collect_prior_answers` 喂已答进重判，答复改变信号防死循环）；T-91-01-04（触顶/续推日志仅记 round_count/session_id 标量，澄清正文只进 LLM prompt 不进日志）；T-91-01-05（写入只经 ClarificationService，INV-6 grep 守护无回归）。无新增网络端点/认证路径/schema 变化，无新威胁面。

## Known Stubs
None - 本 plan 落地后端服务层逻辑（helper + 多轮判定），无 UI 渲染、无 mock 数据。下游 91-02~05 出口面将消费 `aanswer_round_and_resume`（按 ROADMAP 规划，非 stub）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 续推/多轮地基就绪且单一来源：91-03（飞书回调）与 91-04（会话 endpoint）可同源调用 `aanswer_round_and_resume`，入口私有重调度（approve_node / chat barrier）各自实现。
- 多轮澄清放开：答后重判、信息不足再发一轮、足够则继续，`_MAX_CLARIFY_ROUNDS=6` 上界兜底不无限挂起。
- 验收全绿：`test_answer_resume.py`(5) + `test_engine_clarify.py`(14) + INV-6 守护(2) 全 pass；ruff/mypy 干净；`makemigrations --check` 无变化。

---
*Phase: 91-clarification-outlets-resume*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/answer_resume.py
- FOUND: server/tests/services/test_answer_resume.py
- FOUND: .planning/phases/91-clarification-outlets-resume/91-01-SUMMARY.md
- FOUND commit 5f1be5e20 (Task 1 RED)
- FOUND commit b334374c1 (Task 1 GREEN)
- FOUND commit 9604cd62c (Task 2 RED)
- FOUND commit 56cd2291c (Task 2 GREEN)
- FOUND commit 75bf0917d (INV-6 docstring fix)
