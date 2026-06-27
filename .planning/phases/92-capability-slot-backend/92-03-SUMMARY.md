---
phase: 92-capability-slot-backend
plan: 03
subsystem: workflow-node-slots
tags: [workflow, node, clarification, feishu-card, callback, slot, answer-round, inv6, waiting-event]

# Dependency graph
requires:
  - phase: 92-capability-slot-backend
    provides: NodePort.shape 契约 + KNOWN_PORT_SHAPES（92-01）；build_clarification_card action 参数化（92-02）
  - phase: 91-clarification-outlets-resume
    provides: plan_clarify_callback 回调范式 + build_clarification_card(clarification_id) + ClarificationService.answer_round（INV-6）
provides:
  - "clarification_card 原子节点（node_type=clarification_card，INTEGRATION/blocking）：入 clarification_request、出 clarification_answer + feishu_message"
  - "standalone clarify_card_ 回调：据权威 execution_id/node_id 定位 + node_type 校验 + WAITING_EVENT 幂等门 → answer_round 落库（persisted）/ questions_meta 透传（transient）→ approve_node 本节点"
  - "ClarifyCardCallback 订阅事件键（独立于 91 PlanClarifyCallback）"
  - "node-types.fixture.json node_count=42（含 clarification_card）"
affects: [93-slot-editor, 94-entry-unify]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "澄清卡 = 自洽闭环原子节点：发卡 best-effort + ClarifyCardCallback 订阅 + waiting_event → 独立回调 approve 本 card 节点（绝不绑 PlanSession/ai_plan_research）"
    - "回调据 clarification_id 取整轮 order 子题（persisted 落库）/ 无 clarification_id 据 output_data.questions_meta 透传（transient 不落库）二态收口"

key-files:
  created:
    - server/workflows/nodes/integrations/clarification_card.py
    - server/feishu/callbacks/clarify_card_callback.py
    - server/tests/workflows/test_clarification_card_node.py
    - server/tests/feishu/test_clarify_card_callback.py
  modified:
    - server/feishu/urls.py
    - web/src/types/workflow/__fixtures__/node-types.fixture.json

key-decisions:
  - "approve 本 clarification_card 节点（不绑 PlanSession / 不 approve ai_plan_research）——节点自洽闭环（Open Questions 决议 #1 + Pitfall 4）"
  - "回调据权威 execution_id/node_id 定位 + 校验 node_type==clarification_card + WAITING_EVENT 幂等门（防伪造/跨节点误 approve/重放，T-92-03-SPOOF）"
  - "二态：有 clarification_id → answer_round 落库（INV-6）；无 clarification_id → 据 output_data.questions_meta 透传、跳过落库（transient）"
  - "发卡 best-effort try/except（失败仍 waiting_event 不反噬挂起）；订阅 acreate 不包裹（超时兜底是可靠性机制，guard 已确保 FK 有效）"
  - "fixture 重生成顺带收敛既有 stale 漂移：base 36 实为 stale，注册表真实 42（含 5 个已注册但未重跑 fixture 的 war-room 节点 + clarification_card）"

patterns-established:
  - "Pattern: standalone 澄清卡回调 = ack 即时返回 + 后台（幂等门 + node_type 校验 → 据 clarification_id 取整轮 order 子题/或 questions_meta 透传 → _build_answers → answer_round（仅 persisted，INV-6）→ approve_node 本节点 + 置灰卡）全程 fail-soft 脱敏"

requirements-completed: [SLOT-02]

# Metrics
duration: ~12min
completed: 2026-06-27
---

# Phase 92 Plan 03: clarification_card 节点 + clarify_card 独立回调 Summary

**新增可注册可编排的「澄清卡」原子节点 `clarification_card`（入 `clarification_request`、出 `clarification_answer` + `feishu_message`，INTEGRATION/blocking）——吃澄清请求 → 复用 `build_clarification_card(action="clarify_card_answer")` 发飞书交互卡（best-effort）→ 建 `ClarifyCardCallback` 订阅 → `waiting_event` 挂起；standalone 回调 `clarify_card_` 据服务端权威 `execution_id/node_id` 定位本节点 + 校验 `node_type=="clarification_card"` + `WAITING_EVENT` 幂等门收答，有 `clarification_id` 经 `ClarificationService.answer_round` 落库（INV-6）/ 无则据 `questions_meta` 透传，`approve_node` 续推本 card 节点（绝不绑 `PlanSession`/`ai_plan_research`），收官 SLOT-02。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T10:53:00Z
- **Completed:** 2026-06-27T11:05:00Z
- **Tasks:** 3（Task 1/2 TDD）
- **Files modified:** 6（4 created + 2 modified）

## Accomplishments

- **Task 1 — `ClarificationCardNode`**：`@register_node`、`node_type="clarification_card"`、`category=INTEGRATION`、`execution_mode="server_local"`、`is_blocking=True`；inputs=[`clarification_request`(shape=clarification_request)]、outputs=[`clarification_answer`(shape=clarification_answer), `feishu_message`(shape=feishu_message), `error`]。`execute` 解析 `clarification_request`（clarification_id/questions/chat_id/title/reason）→ 有 clarification_id 按 `order` 取整轮子题（persisted）/ 否则 raw questions（transient）→ 二者皆空或缺 chat_id → `failed`+`next_handle="error"`（D-4）→ `build_clarification_card(action="clarify_card_answer")`（reason/title 经 `redact_secrets_in_text` 脱敏）→ 发卡（**整段 best-effort try/except**，失败标 `card_sent=False` 仍挂起）→ 建 `WorkflowEventSubscription(event_type="ClarifyCardCallback", timeout=60min)` → `waiting_event`（output 携 clarification_id/chat_id/question_count/persisted/card_sent/questions_meta）。
- **Task 2 — `clarify_card_` 独立回调**：`@register_card_callback("clarify_card_")` 同步入口 `handle_clarify_card_action`——`action != "clarify_card_answer"` → None；缺 execution_id/node_id → warning+None（T-92-03-SPOOF；**clarification_id 非必需**，transient 透传模式无轮可写）；`_run_in_thread(_do_clarify_card_async)` + 即时 `_ack_card`。后台 `bind_task_context` re-bind 归因 → ① `_aget_waiting_node` 幂等门（非 waiting no-op）② 校验 `node_type=="clarification_card"`（防跨节点误 approve）③ 有 clarification_id → `_acollect_round_questions`（order）/ 无 → `output_data.questions_meta` ④ `_build_answers`（按 order 枚举 q{i}/qt{i}）⑤ **有 clarification_id 才** `ClarificationService().answer_round`（INV-6）⑥ `approval_data={clarification_answered, clarification_id, answers}` + SUSPENDED→RUNNING + `WorkflowEngine().approve_node(本节点, _FeishuResponder, "clarify_card_answer")` ⑦ 置灰卡 best-effort；全程 fail-soft `redact_secrets_in_text` 脱敏不反噬 5xx。`feishu/urls.py` 加 import 触发注册。
- **Task 3 — fixture 重生成**：`dump_node_fixture` 同步后端注册表 → `node_count` 36→42（新增 `clarification_card` + 顺带收敛 5 个既有 stale 节点）；`node-sync.test.ts` 5 测绿（palette ⊆ fixture 不破）。

## Task Commits

每个任务原子提交（Task 1/2 TDD：test → feat）：

1. **Task 1 RED: ClarificationCardNode 失败测试** - `e5904a172` (test)
2. **Task 1 GREEN: ClarificationCardNode 实现** - `7eae80597` (feat)
3. **Task 2 RED: clarify_card 回调失败测试** - `f7941f71a` (test)
4. **Task 2 GREEN: clarify_card 回调 + urls 注册** - `07a2f196b` (feat)
5. **Task 3: 重生成 node fixture（node_count→42）** - `8e666df47` (chore)

**Plan metadata:** (final docs commit — SUMMARY + STATE + ROADMAP + REQUIREMENTS)

## Files Created/Modified

- `server/workflows/nodes/integrations/clarification_card.py` - `ClarificationCardNode`（发卡 best-effort + ClarifyCardCallback 订阅 + waiting_event；`_acollect_round_questions`/`_resolve_initiator` helper）
- `server/feishu/callbacks/clarify_card_callback.py` - standalone 回调（同步 ack + 后台幂等门 + node_type 校验 + answer_round/透传 + approve_node 本节点 + 置灰卡；`_build_answers`/`_aget_waiting_node`/`_aget_node_type`/`_FeishuResponder` 等）
- `server/feishu/urls.py` - 加 `import feishu.callbacks.clarify_card_callback`（触发 @register_card_callback 注册）
- `web/src/types/workflow/__fixtures__/node-types.fixture.json` - node_count 36→42（含 clarification_card）
- `server/tests/workflows/test_clarification_card_node.py` - 5 用例（注册+shape / persisted 发卡挂起 / raw transient / 发卡失败 best-effort / 缺内容 failed-error）
- `server/tests/feishu/test_clarify_card_callback.py` - 9 用例（前缀唯一 / 同步 ack·缺 id·非目标动作·transient 仍调度 / _build_answers 映射×2 / 后台 answer_round+approve 本节点 / 非 waiting 幂等 / 错节点类型 no-op / fail-soft / transient 跳 answer_round 仍 approve）

## Decisions Made

- **approve 本 card 节点（不绑 PlanSession/ai_plan_research）**：节点自洽闭环（Open Questions 决议 #1 + Pitfall 4），回调据 `node_execution.node.node_type` 校验确为 `clarification_card` 后才 approve，物理隔离 91 的 `plan_clarify_` 链。
- **二态收口**：有 `clarification_id`（persisted）→ `_acollect_round_questions` 取整轮 order 子题 + `answer_round` 落库（INV-6）；无 `clarification_id`（transient）→ 据 `node_execution.output_data["questions_meta"]`（order 序）透传、跳过 `answer_round`（无轮可写），仍 `approve_node` 携 answers。
- **缺内容 fail（D-4）**：questions 空 **或** chat_id 空 → `failed`+`next_handle="error"`（无澄清内容/无群聊无意义）。
- **发卡 best-effort、订阅不包裹**：发卡整段 try/except（失败仍 waiting_event 不反噬挂起，T-92-03-DOS）；`WorkflowEventSubscription.acreate` 不包 try/except（超时兜底是可靠性机制，guard 已确保 FK 有效，mirror 91-02 决策）。
- **复用 `_get_feishu_credentials`**：直接 import `chat_question._get_feishu_credentials`（不复制），测试经 `clarification_card._get_feishu_credentials` patch。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] fixture node_count 36→42（而非 plan 预期的 37）**
- **Found during:** Task 3（重跑 fixture）
- **Issue:** plan 预期 base 36 → +clarification_card = 37，但 `dump_node_fixture` 实际产出 42。核查 diff 发现除 `clarification_card` 外还多 5 个节点（`board_split` / `board_split_review` / `create_project` / `plan_deepen` / `repo_association`）。
- **Root cause:** 这 5 个节点源文件**均已提交**且 `git status` 干净（非 war-room 未提交 WIP）——是 war-room 提交了节点但从未重跑 fixture，导致 committed fixture（36）相对后端注册表 stale 5 个节点。fixture 须镜像注册表事实源，故全量重生成（42）是正确态。
- **Fix:** 提交全量重生成的 fixture（42），收敛既有 stale 漂移 + 新增 clarification_card。
- **Verification:** `node-sync.test.ts` 5 测绿（断言 palette ⊆ fixture，多节点不破红线）；diff 仅含 6 个 `+node_type` 项无其它漂移。
- **Committed in:** `8e666df47`（Task 3 commit）

---

**Total deviations:** 1 auto-fixed（1 blocking）
**Impact on plan:** fixture 必须与后端注册表一致；收敛 stale 漂移属修正既有数据债，无 scope creep（node-sync 守护红线不破）。

## Issues Encountered

- **执行期 git 状态扰动（已恢复，无数据损失）**：基线回归核验时 `git switch --detach <base>` 后的 `git switch main` 未真正返回（end 后仍处 detached HEAD）；随后的 STATE/ROADMAP/REQUIREMENTS 编辑发生在 detached 态。核查 reflog 确认 5 个 92-03 提交完整在 `main`（8e666df47），working-tree 未提交编辑无冲突保留，已 `git switch main` 正确返回。**对涉及文件零影响**（ROADMAP/REQUIREMENTS 在 base 与 main 内容一致）。
- **10 个既有失败经基线回归确认与本 plan 无关**：`test_execution_concurrency`(2 并发计时) + `test_template_loader`(2 `technical_plan_generation` 模板 `field_not_found`) + `test_comment_entry_wiring`(3) + `test_entry_wiring`(1) + `test_inv6_no_bypass_feishu_chat_id_write`(1) + `test_inv6_no_bypass_canonical_plan_write`(1)。在 base 提交（9a32b0437）单独复跑这 10 个测试文件，失败集**完全一致**（10 failed），确认源于 war-room 未提交在制品（initiatives/services、comment-wiring 等），非本 plan 引入。记 deferred-items，不在 92-03 范围内修复。

## Threat Surface Scan

threat_model 六项落实：T-92-03-SPOOF（据权威 execution_id/node_id 定位 + node_type 校验 + WAITING_EVENT 幂等门，clarification_id 仅用于取轮绝不信直传 session_id）、T-92-03-INV6（落库只经 `answer_round`，节点/回调无 `.objects.create/.save` 旁路写 delivery 表）、T-92-03-INFO（reason/title/置灰卡正文 + 异常文本经 `redact_secrets_in_text`，日志仅记 execution_id/node_id/clarification_id 标量）、T-92-03-DOS（发卡 + 回调后台 + 置灰卡均 best-effort fail-soft 不反噬）、T-92-03-ATTR（回调 `bind_task_context(user_id=responder)` re-bind，节点 `initiated_by_user_id` 缺记 system）、T-92-03-SC（本 plan 无任何包安装）。复用既有 `card/callback/` 单一回调入口按前缀路由，无新网络端点/认证路径/schema 变化（`makemigrations --check` 无迁移）。

## Known Stubs

None — 节点 + 回调收答闭环全实现（发卡/取轮/收答/落库/approve/置灰卡）。`clarification_card` 节点在前端 palette **暂不可见/不可拖**（palette 收录是 Phase 93 前端工作）——本 plan 只保后端注册 + fixture 同步，编辑器可见性留 93，非 stub。

## User Setup Required

None - 纯仓内 Python + fixture JSON 重生成，无外部服务配置、无新增依赖、无 DB 迁移。

## Verification Results

- `uv run pytest tests/workflows/test_clarification_card_node.py tests/feishu/test_clarify_card_callback.py -x -q` → 17 passed。
- `uv run pytest tests/workflows tests/feishu tests/delivery -q` → 1166 passed, 10 failed（均既有，base 复跑一致、与本 plan 无关）。
- `uv run ruff format --check`（2 源文件）+ `ruff check` → All checks passed；`uv run mypy`（2 源文件）→ Success: no issues found。
- `uv run python manage.py makemigrations --check` → No changes detected（无 DB 迁移）。
- `cd web && pnpm vitest run node-sync` → 5 passed（node_count=42 含 clarification_card）。

## Next Phase Readiness

- **SLOT-02 收官**：`clarification_card` 节点 + `clarify_card_` 回调闭环就绪，Phase 92（插槽系统后端）3/3 完成。
- **Phase 93（插槽编辑器前端）**：可消费节点端口 shape（clarification_request/clarification_answer/feishu_message）做磁吸；需在 `NodePalette.vue` 收录 `clarification_card` 使其可见可拖（fixture 已含，palette 收录后 node-sync 仍绿）。
- **Phase 94（入口统一）**：澄清单一来源（90/91）+ 插槽节点已就绪，可推进 UNIFY-01~06。

## Self-Check: PASSED

- FOUND: server/workflows/nodes/integrations/clarification_card.py
- FOUND: server/feishu/callbacks/clarify_card_callback.py
- FOUND: server/tests/workflows/test_clarification_card_node.py
- FOUND: server/tests/feishu/test_clarify_card_callback.py
- FOUND: .planning/phases/92-capability-slot-backend/92-03-SUMMARY.md
- FOUND commits: e5904a172 / 7eae80597 / f7941f71a / 07a2f196b / 8e666df47

---
*Phase: 92-capability-slot-backend*
*Completed: 2026-06-27*
