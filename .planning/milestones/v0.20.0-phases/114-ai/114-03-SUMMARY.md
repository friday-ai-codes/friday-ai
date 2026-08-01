---
phase: 114-ai
plan: 03
requirements: [FLOW-07]
provides:
  - "`BlueprintReviewAdapter(*, artifact_service=None, lifecycle_service=None, session_service=None, node_execution_id='')`；`async def review(self, session) -> dict` —— **恒定八键** `{review_status, artifact_version_id, round, back_target, back_repository_id, report, stage_state, thread_ids}`，`review_status ∈ {passed, retry, exhausted, needs_clarification}`。**绝不上抛**"
  - "⭐ **入口三件接线**（顺序固定，全在读审查基线之前）：`arestore_human_blocks`（B3 人工块保护）→ `aapply_thread_answers`（B1 答案消费）→ `areanchor_threads`（批量重锚，判据 = 版本推进）。任一返 `conflict` ⇒ 直接 `needs_clarification` 停等，不跑判定"
  - "`ai_review` 是蓝图链**第 10 个 stage**：`transitions = {review_passed: STAGE_DONE, review_exhausted: STAGE_DONE, repo_rework: repo_plan, remerge: merge, needs_clarification: ai_review}`，`pausable=True`，`wait_status=waiting_clarification`，**不含 failed 出边**"
  - "`_h_bp_ai_review(session, engine) -> StageOutcome` 的 status→event 白名单：`passed→review_passed` / `exhausted→review_exhausted` / `retry→repo_rework|remerge`（按 `back_target`）/ 其余→`needs_clarification`（**先 ensure 阻塞线程**）"
  - "`_abp_mark_ai_reviewing(session)` —— 幂等 + best-effort；合法边只有 `DRAFTING → AI_REVIEWING`，故非 `drafting` 时先委托 `_abp_mark_drafting` 补跳（`\"\"` 时它再补 `researching`）"
  - "`stage_state[\"ai_review\"]` 桶键集：`{round, status, thread_ids, unresolved, anchored_version_id, blocker_count, warning_count, info_count, thread_count, last_attribution?}`；`unresolved` 元素**恰好六键** `{rule_id, severity, section_path, block_id, repository_id, thread_id}`（**零正文**）"
  - "`_decide_back_target(blockers) -> {back_target, back_repository_id, blocker_count}` —— 全部 BLOCKER 同仓 → `BACK_TARGET_REPO_PLAN='repo_plan'` + 仓 id；跨仓 / 无归属 → `BACK_TARGET_REMERGE=''`（融合级）"
  - "模块常量：`MAX_REVIEW_ROUNDS = 2`、`_MAX_UNRESOLVED = 30`、`RETURN_STAGE_AI_REVIEWING = 'ai_reviewing'`、`REVIEW_PASSED/RETRY/EXHAUSTED/NEEDS_CLARIFICATION`"
  - "`SettingKeys.BLUEPRINT_REVIEW_CONFIG = 'blueprint.review.config'`，value JSON `{\"max_review_rounds\": int}`，整段回落 `MAX_REVIEW_ROUNDS`（**零 migration**）"
  - "三个事件常量（纯追加进 `__all__` 与 `BLUEPRINT_EVENTS`，后者 18 → 21）：`EVENT_BLUEPRINT_REVIEW_STARTED/COMPLETED/FAILED` = `blueprint.review.started/completed/failed`"
  - "`blueprint_resume._STAGE_BLUEPRINT_STATUS` 追加 `\"ai_review\": \"ai_reviewing\"`（删除行 **0**）"
affects:
  - "⭐ 114-05（人审端点）：本 stage 的产出即人审输入 —— finding 线程（`kind=ai_review_finding`、`severity`、`anchor`、`created_on_version`、`return_stage='ai_reviewing'`）与 `stage_state['ai_review']['unresolved']` 六键快照。**超界死锁的唯一出口**是 finding 处置端点（`resolve_thread(dismissed=False/True)`）—— 见下方「114-05 接线契约」"
  - "115（查看器）：三个 `blueprint.review.*` 事件进时间线；finding 线程按 `severity` 分级呈现；失锚线程仍走 `anchor_status='orphaned'` 集中查询"
  - "⭐ 全相位：`aapply_thread_answers` 与 `arestore_human_blocks` 从此有生产调用方（B1/B3 不再是孤儿）"
key-files:
  created:
    - server/tests/services/process_runtime/test_blueprint_review_stage.py
  modified:
    - server/services/process_runtime/blueprint_review.py
    - server/services/process_runtime/builtin_processes.py
    - server/services/process_runtime/entrypoint.py
    - server/services/process_runtime/blueprint_resume.py
    - server/delivery/services/event_taxonomy.py
    - server/system/models.py
    - server/tests/services/process_runtime/test_blueprint_process_graph.py
    - server/tests/services/process_runtime/test_blueprint_merge_gate.py
    - server/tests/services/process_runtime/test_blueprint_status_stage_map.py
    - server/tests/delivery/test_blueprint_event_taxonomy_112.py
completed: 2026-07-31
---

# Phase 114 Plan 03: ai_review stage 接线（判定内核 → 线程 / 状态 / 出边）Summary

**一行结论**：`ai_review` 成为蓝图链第 10 个 stage —— `blueprint_review.py` 文件尾**纯追加** 975 行 adapter 节（入口三件接线 → 六类 + goal-backward → findings 批量落分级线程 → 有界回退归因 → 超界携未决清单进人审），`builtin_processes.py` 只加两个函数与一项注册、蓝图链 `merge.merged` 改指 `ai_review` 一行（删除行 **2**，全落在该 stage 段内，旧 `technical_plan` 链零感知），`blueprint_resume.py` 删除行 **0**；新建 34 例 stage 端到端测试把两条最贵的失效模式锁死并经**三处变异实测证伪**（重锚判据写错 / 审查桶写进融合桶 / 轮次不递增，各自使对应用例转红）。⭐ **`blueprint_merge.py` 全程零改动**（`git diff --stat` 空），B3 的人工块保护挂在本 stage 入口而非融合里。`tests/delivery/` **655 passed**（与基线逐字一致）+ `tests/services/process_runtime/` **608 passed**（573 + 35），合计 **1263 = 1228 基线 + 35，零回归**；`makemigrations --check` 退出码 **0**，ruff check + format 全通过。

## Accomplishments

- **两条无限循环防线都被可证伪地锁死**（本 plan 最贵的两个失效模式）：
  - ⭐ **轮次桶不复用融合桶**（T-114-14）。`stage_state` 增量只写 `{"ai_review": bucket}`，靠 engine 的顶层浅合并落盘。融合侧的 `_build_stage_state` 每轮**整桶覆盖**它自己那个键，轮次塞进去会被抹掉 ⇒ 计数归零 ⇒ 无限打回。测试预置带 `sentinel` 的融合桶，跑一轮后断言它**逐字不变**；**变异验证**：把回写键改成融合桶后该用例立刻转红。
  - ⭐ **超界出口是「待人审」不是「流程失败」**（T-114-15）。`ai_review` 的 `transitions` 五条出边**不含 failed**（全图扫描断言 `test_blueprint_chain_has_no_failed_edge_but_old_chain_still_does` 自动覆盖新 stage）；adapter 源码 `rg "STAGE_FAILED|\"failed\""` **零命中**。端到端用例连跑三轮持续 BLOCKER：前两轮打回（蓝图 `drafting`、`round` 递增、**版本数不增**），第三次走 `review_exhausted` ⇒ 蓝图 `pending_review`、`unresolved` 非空且元素**恰好六键**、会话 `status == DONE` 且 **不是 FAILED**。**变异验证**：把轮次递增去掉后该用例转红。
- **⭐ 入口三件接线成立，`blueprint_merge.py` 一行未改**（B1/B3 定夺）：
  - **人工块保护（0-b）**在最前。理由写进 docstring：打回后 `repo_rework`/`remerge` 重跑融合并 `add_version` 是本相位**主要的产版本路径**，而融合模块是只读受限面 —— 保护只能挂在审查入口。停等判据读 `status == "conflict"`，**不读 `preserved`**（后者是 `conflicted` 的子集，差集 = 当前态整块缺失、无落位可写回的块，拿它当判据会漏掉「块被重装删掉」那一档）。
  - **答案消费（0-a）**紧随其后，`section_writer` 不传 ⇒ 走 114-04 的生产实现。测试用 spy 包住真实 `aapply_thread_answers` 断言 `await_count == 1` —— 少了这条，「版本 +1」也可能是别的路径产生的，B1 接线并未被真正证明。
  - **批量重锚（0-c）**的判据是「**版本推进**」（比对 artifact 最新版本 id 与 `anchored_version_id`），**不是**「本轮是否产版本」。12b 用例专门构造「仅融合重装产新版本、无已作答线程、无人工块」的主路径 —— 0-a/0-b 都不产版本，错误实现下重锚永不触发。**变异验证**：把重锚整体短路后 12a/12b 同时转红、12c 仍绿。
- **findings 变成可分级、可锚定、可去重的线程**。三条通道各司其职：本轮仍在 → `append_note("第 N 轮仍存在…")`；新出现 → `open_thread`（`blocking` 由 `severity` **派生**而非各写各的，错配会被 114-01 的不变式 raise）；本轮消失 → `resolve_thread`。单条失败 best-effort 吞掉，绝不让一条 finding 落库失败把整轮审查打成异常。
- ⛔ **留痕通道纪律**：`rg "record_answer" blueprint_review.py` **零命中**（含 docstring —— 本模块用「会把 `open` 推到 `answered` 的作答通道」指代它，不写出 token）。行为侧同步断言：留痕后线程仍 `open`、`ahas_open_blocking_threads` 仍为真（门还在）。
- **去重索引不靠新增字段**。`BlueprintThread` 无 `rule_id` 列，anchor 也不该被塞业务标记，故 `question` 统一格式化为 `[{rule_id}] {detail}`，索引从**首条消息**的 `[rule_id]` 前缀反查 + `anchor.block_id or anchor.section_path` 定位，与 `finding_dedupe_key` 同构。两次查询（线程 + 消息 `values()`）搞定，无 N+1。
- **`quoted_text` 必须非空**。实测 `blueprint_anchor.reanchor`：block_id 消失且 `quoted_text` 为空时**直接判失锚**。故开线程时用 `iter_blocks` 定位该块、取 `_block_text(block)[:500]` 填入 —— 留空会让块被删后批注全部错位（CLAR-02）。
- **CAS 冲突绝不外泄**（T-114-21）。`_atransition` 先判幂等（已是目标态直接返回，合法边表无自环），并发冲突 `arefresh_from_db` 重试一次，仍失败或非法边一律记 warning 返 `False`，调用方把出口降级成 `needs_clarification`。整个 `review()` 外层再包一层 `try/except` → `needs_clarification` + `blueprint.review.failed` 事件，**上抛就会让 engine 落终态失败**。
- **观测合规**：新增 12 条结构化事件全部带 `category` + `component`；`blueprint_review_completed` 带 `duration_ms`（含入口接线耗时，`started` 在 0-b 之前取、全程不重置）。payload / 日志只放计数、分级分布与关联键 —— **finding 正文、蓝图正文、澄清文本一律不进**（T-114-20）；异常文本走 `redact_secrets_in_text` 并截断。零新增 `CallSource`（goal-backward 复用 114-02 已注册的 `blueprint_ai_review`）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `36f4600e` | `SettingKeys.BLUEPRINT_REVIEW_CONFIG` + 三个 `blueprint.review.*` 事件常量 + `BlueprintReviewAdapter` 全节（975 行纯追加） |
| 2 | `13ac3d13` | `_abp_mark_ai_reviewing` + `_h_bp_ai_review` + `ai_review` StageDef + `merge.merged → ai_review` + entrypoint deps + resume 映射一行 |
| 3 | `8101dcdf` | `test_blueprint_review_stage.py`「守十三件事」34 例 + 三处接续点断言同步 |

## Files

- `server/services/process_runtime/blueprint_review.py`（**+975 / −0**，文件尾纯追加 adapter 节）
- `server/services/process_runtime/builtin_processes.py`（+123 / −2）
- `server/services/process_runtime/entrypoint.py`（+5 / −2）
- `server/services/process_runtime/blueprint_resume.py`（**+2 / −0**）
- `server/delivery/services/event_taxonomy.py`（**+12 / −0**）
- `server/system/models.py`（**+5 / −0**）
- `server/tests/services/process_runtime/test_blueprint_review_stage.py`（新建，810 行 / 27 个 `def test_` → **34 例**）
- 四个既有测试文件的接续点断言同步（见下方登记表）

合计 **+2008 / −26**（`git diff --stat c005d5b6..HEAD`）。

## 114-05 接线契约（人审端点按此逐字消费）

### 七个审查侧消费点

| # | 消费面 | 取值 |
| - | ------ | ---- |
| 1 | **finding 清单** | `BlueprintThread.objects.filter(artifact=…, kind=ThreadKind.AI_REVIEW_FINDING)`，按 `severity ∈ {blocker, warning, info}` 分级 |
| 2 | **finding 正文** | 线程首条消息 body，格式 `[{rule_id}] {detail}`（`rule_id` 全表见 114-02-SUMMARY） |
| 3 | **复检留痕** | 同线程后续 `author_type == "ai"` 消息，body 前缀「第 N 轮仍存在：」 |
| 4 | **锚点** | `thread.anchor = {section_path, block_id, quoted_text}`；失锚线程 `anchor_status == "orphaned"` |
| 5 | **未决快照** | `session.stage_state["ai_review"]["unresolved"]`，元素**恰好六键**、条数 ≤30、**零正文** |
| 6 | **轮次与归因** | 同桶的 `round` / `status` / `last_attribution = {back_target, back_repository_id, blocker_count}` |
| 7 | **只读计数** | `BlueprintLifecycleService.aunresolved_blocker_count(artifact)`（114-01，**仅供呈现**，绝不用于 confirm 守卫判定） |

### ⭐ 超界死锁的出口（114-05 必须实现的那件事）

轮次用尽时蓝图落 `pending_review`，但**未决 BLOCKER finding 线程仍在 `{open, answered}`** ⇒ 114-01 的 confirm 守卫判据②仍命中 ⇒ `pending_review → confirmed` 被拒。这是**有意的**：带未决 BLOCKER 的蓝图不该被确认。

解锁只有一条路 —— 114-05 的 finding 处置端点让线程**离开 `{open, answered}`**：

| 动作 | 调用 | 语义 |
| ---- | ---- | ---- |
| 采纳并修复 | `resolve_thread(thread, resolution=…)` → `resolved` | 问题已解决 |
| 判为误报 | `resolve_thread(thread, dismissed=True)` → `dismissed` | 人工裁定不成立 |

两者都会让守卫判据②（`status__in=[open, answered]`）不再命中，confirm 随之放行。⛔ **绝不能**用作答通道「顺手」把 finding 推到 `answered` —— 那既解不开门（判据②仍含 `answered`），又污染线程状态。

### stage 出边与状态映射（114-05 的续驱侧要按此判断）

| adapter `review_status` | handler event | stage 目标 | 蓝图状态 |
| ----------------------- | ------------- | ---------- | -------- |
| `passed` | `review_passed` | `STAGE_DONE` | `pending_review` |
| `exhausted` | `review_exhausted` | `STAGE_DONE` | `pending_review`（携未决清单） |
| `retry` + `back_target == "repo_plan"` | `repo_rework` | `repo_plan` | `drafting` |
| `retry` + 其余 | `remerge` | `merge` | `drafting` |
| `needs_clarification` / 未知值 | `needs_clarification` | `ai_review`（self-loop） | 不变（先 ensure 阻塞线程） |

## 受限面删除行逐行登记

| 文件 | 删除行 | 上界 | 逐行归属 |
| ---- | ------ | ---- | -------- |
| `blueprint_review.py` | **0** | 0 | 文件尾纯追加，114-02 的判定内核一字未动 |
| `event_taxonomy.py` | **0** | 0 | `__all__` / 常量定义 / `BLUEPRINT_EVENTS` 三处纯追加 |
| `system/models.py` | **0** | 0 | `SettingKeys` 尾部纯追加一键 + 四段注释 |
| `blueprint_resume.py` | **0** | 0 | 映射表追加一行 + 一行注释（`rg "^-[^-]"` 空输出） |
| `builtin_processes.py` | **2** | ≤3 | ① `# 114 接续点：追加 ai_review stage 时把该值改为 "ai_review" 即可` → 改写为「**已接续**（114-03）」；② `"merged": STAGE_DONE,` → `"merged": "ai_review",`。**两行都在 `_TECHNICAL_BLUEPRINT_STAGES["merge"]` 段内**，`_TECHNICAL_PLAN_STAGES` 一字未动 |
| `entrypoint.py` | **2** | ≤2 | ① docstring「九个 `_h_bp_*`」→「十个」；② deps 名单行追加 ``review``。第 4 行「后两个是 113-06 追加的阶段 2/3。」**逐字保留**，新说明另起一行追加 |

**实测计数**：`^async def _h_bp_` = **10**（9 → 10）；`^register_process_type\(` = **3**（未新增注册项）；`artifact_type="technical_plan"` = **2**（与改动前相同，**未新增 artifact_type**）；`_abp_ensure_blocking_clarification(` = **6**（+1，新 handler 的 self-loop 前置防线）。

## 既有回归断言更新前后对照

| 文件 | 位置 | 更新前 | 更新后 |
| ---- | ---- | ------ | ------ |
| `test_blueprint_process_graph.py` | `BLUEPRINT_STAGE_KEYS` | 112 七个 ∪ 113 两个 | 追加 `BLUEPRINT_STAGE_KEYS_114 = ("ai_review",)` 并并入 |
| 同上 | `test_merge_merged_is_the_114_handoff_point` | `merged == STAGE_DONE` | `merged == "ai_review"` + **旧链正向对照** `_TECHNICAL_PLAN_STAGES["merge"].transitions["merged"] == STAGE_DONE` + `ai_review.review_exhausted == STAGE_DONE` |
| 同上 | pausable 集合 | 五项 | 追加 `"ai_review"` |
| 同上 | `test_handler_count_and_registration_count` | `== 9`（7+2） | `== 10`（7+2+1），register 计数**保持 3** |
| 同上 | `test_handlers_pass_through_without_deps` | 九条参数化 | 追加 `(bp._h_bp_ai_review, "needs_clarification")` |
| `test_blueprint_merge_gate.py` | 四跳可达 | `merged == STAGE_DONE` | 改名为 `..._five_hops`，`merged == "ai_review"` + `ai_review.review_passed == STAGE_DONE`（保持 `STAGE_DONE` import 有消费方） |
| `test_blueprint_status_stage_map.py` | `test_stage_status_table_matches_enum` | 表 == `STAGES_113` | 表 == `STAGES_113 ∪ STAGES_114`，新增 `ai_review == AI_REVIEWING` 断言；**七条 112 参数化等价性断言逐字未动** |
| `test_blueprint_event_taxonomy_112.py` | `test_blueprint_events_shape` | `len(BLUEPRINT_EVENTS) == 18` | `== 21`，新增 `_NEW_114_EVENTS` 三项（见 Deviations #2） |

## Decisions

- **融合级 `back_target` 用空串而非融合桶名字面量**。PLAN 同时要求 `_decide_back_target` 返回 `("merge", "")` 与 `rg '"merge"'` 零命中 —— 两者不可能同时满足。选空串的理由不只是绕开验收：handler 的映射本就是「`"repo_plan"` → `repo_rework`，其余 → `remerge`」（与 `_h_bp_merge` 逐字同款，且 `("retry", "", "remerge")` 早已是融合侧的参数化用例），空串完全等价；而保住「本模块不出现融合桶字面量」这条性质，就让 T-114-14 的防线从「靠人判读意图」升级成 **rg 可硬验收**。常量 `BACK_TARGET_REPO_PLAN` / `BACK_TARGET_REMERGE` 已导出，下游不必写字面量。
- **入口顺序按 114-04 契约取「保护 → 消费」而非 PLAN action 的「消费 → 保护」**（见 Deviations #1）。
- **`quoted_text` 取块正文前 500 字符而非留空**。留空看似最保守（正文零外泄），实则让 `reanchor` 的模糊分支彻底失效 —— 块被重装删掉时线程直接失锚。anchor 存的是 DB 字段不是日志，T-114-20 约束的是「正文进 `stage_state` / payload / 日志」，anchor 不在其列。
- **去重索引从首条消息前缀反查 `rule_id`，不往 anchor 里塞业务标记**。anchor 会被 `areanchor_threads` 整体重写（`dict(anchor, block_id=…)`），塞进去的键虽然会被保留，但语义上 anchor 是「挂在哪」不是「为什么挂」；混进去会让 115 的锚点渲染读到不认识的键。
- **`_atransition` 先判幂等再转移**。合法边表**无自环**（`DRAFTING → DRAFTING` 非法），而 `_abp_mark_ai_reviewing` 是 best-effort —— 它失败时蓝图可能仍停在 `drafting`，此时打回路径的 `→ DRAFTING` 会因非法边被拒、把 `retry` 降级成 `needs_clarification`。加幂等短路后这条路径恒定成立。
- **`review()` 拆成外层 `review` + 内层 `_areview`**。外层只负责「起始事件 + 兜底 `try/except` + 失败事件」，内层是九步主链。合成一个函数会让主链被一层巨大的 `try` 缩进包住，且 `round_no` / `started` 要在 `except` 里重新解析。

## Deviations from Plan

共 3 处：1 处按上游已验证契约纠正 PLAN 的步骤顺序，2 处为 PLAN 验收字面与既有代码/意图冲突的判读。无功能性偏离。

**1. [Rule 1 - PLAN 与上游契约冲突，按上游为准] 入口顺序取 `arestore_human_blocks` → `aapply_thread_answers`，与 PLAN action 的 0-a/0-b 编号相反**

- **Found during:** Task 1
- **Issue:** PLAN `<action>` 把「答案消费」编为 0-a、「人工块保护」编为 0-b；而 114-04-SUMMARY 的「114-03 接线契约」节明写顺序为 `arestore_human_blocks` → `aapply_thread_answers` → 判定内核，且该顺序是 114-04 交付时**已验证**的契约。
- **Fix:** 按上游契约执行（先保护、后消费）。语义上也更正确：先把重装抹掉的人工块恢复到位，答案回灌才是在「正确的当前内容」之上改写；反过来则可能把答案写进一份马上要被人工块覆盖回去的正文。PLAN 的**可执行验收断言**（`aapply_thread_answers` 与 `arestore_human_blocks` 的位置都必须早于 `order_by("-version_no")`）在两种顺序下都成立，实跑 `entry wiring order OK`。
- **Files modified:** `server/services/process_runtime/blueprint_review.py`
- **Commit:** `36f4600e`

**2. [Rule 3 - PLAN 未登记的接续点断言] 两处「计数/集合随追加更新」的既有断言必须同步，PLAN 只列了三条**

- **Found during:** Task 1 / Task 2 收官验证
- **Issue:** PLAN `<execution_context>` 列了三条随接续点变化的既有断言。实跑发现另有两条同类：`test_blueprint_event_taxonomy_112.py::test_blueprint_events_shape`（`len(BLUEPRINT_EVENTS) == 18` 硬编码，纯追加三常量后必红）与 `test_blueprint_status_stage_map.py::test_stage_status_table_matches_enum`（`set(表) == set(STAGES_113)`，映射表追加一行后必红）。两者都是「集合形状快照」，PLAN 反而明确要求后者「自动覆盖新行」——说明是遗漏登记而非禁止改动。
- **Fix:** 按同款体例更新：前者追加 `_NEW_114_EVENTS` 三项、计数 18 → 21；后者追加 `STAGES_114 = ("ai_review",)` 并新增 `ai_review == AI_REVIEWING` 的等值断言。两文件的**其余断言逐字未动**（`test_blueprint_status_stage_map` 的七条 112 参数化等价性断言继续绿）。
- **Files modified:** `server/tests/delivery/test_blueprint_event_taxonomy_112.py`、`server/tests/services/process_runtime/test_blueprint_status_stage_map.py`
- **Commit:** `36f4600e` / `8101dcdf`

**3. [Rule 3 - PLAN 验收字面与 114-02 冻结面冲突] `rg '"merge"' blueprint_review.py` 的唯一命中在 114-02 的既有注释行，按「新增段零命中」判读**

- **Found during:** Task 1 acceptance
- **Issue:** PLAN 同时要求「114-02 的纯函数节一字不动」与 `rg -n '"merge"' blueprint_review.py` **零命中**。实测唯一命中是 `:76` —— 114-02 写在 `STAGE_STATE_KEY` 上方的警示注释「⚠️ 绝不复用 "merge" 桶：那会把审查结论写进融合状态…」。按字面执行验收就必须删掉那句警示，而它恰恰是本 plan 这条纪律的书面依据。
- **Fix:** 按验收意图（「adapter 绝不写融合桶」）判读为**本 plan 新增段零命中**，并实测坐实：`:76` 之后（adapter 节起始行 1406 之后）**零命中**。为让这条判读不依赖人工目测，实现侧特意避开了融合桶字面量（见 Decisions 第一条），并另配两条运行时断言：`test_review_bucket_never_overwrites_the_merge_bucket`（sentinel 逐字不变）与 `test_stage_state_key_is_not_the_merge_bucket`。同款矛盾 114-02 / 114-04 已各遇一次并按相同方式判读。
- **Files modified:** 无（判读差异，非代码改动）
- **Commit:** —

## 测试与验证

### 测试计数（与 114-04 收官基线逐条比对）

| 套件 | 114-04 收官基线 | 本 plan 后 | 增量 |
| ---- | --------------- | ---------- | ---- |
| `tests/delivery/` | 655 passed | **655 passed** | 0（线程底座与事件面零回归） |
| `tests/services/process_runtime/` | 573 passed | **608 passed** | +35 |
| **合计** | **1228** | **1263 passed** | **+35** |

+35 = 新测试文件 **34 例** + `test_handlers_pass_through_without_deps` 新增的 1 条参数化条目。**零 failed / 零 error / 零回归**。

### ⭐ 变异验证（证伪能力实测，非声明）

| # | 变异 | 结果 |
| - | ---- | ---- |
| A | `_areanchor_if_advanced` 开头直接 `return anchored`（等价于「以本轮是否产版本为判据」的错误实现） | `test_reanchor_runs_after_answer_reflow_produces_a_version` + `test_reanchor_runs_on_the_merge_rework_path_without_any_reflow_version` **2 failed / 32 passed** |
| B | `_bucket` 的回写键改成融合桶（T-114-14 的错误实现） | `test_review_bucket_never_overwrites_the_merge_bucket` 转红 |
| C | 打回出口的 `round_no + 1` 改回 `round_no`（有界回退退化成无限循环） | `test_persistent_blocker_exhausts_into_pending_review_and_never_fails` **1 failed / 1 passed**（`-k exhaust`） |

三次变异均已还原，`git diff --stat -- blueprint_review.py` **输出为空**后才提交 Task 3。

### 门禁

- `uv run pytest tests/ -q` → **8450 passed, 1 failed, 63 skipped, 26 deselected, 1 xfailed**。唯一失败项 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 与本 plan **无关**：断言 `skills/skills/*/SKILL.md` ≥4，而本 worktree 的 `skills/` 是空目录（主检出里有内容），纯 worktree 环境现象；本 plan 的改动文件清单不含 `skills/` 下任何路径。
- `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**（**零 migration**；全相位唯一的 `BlueprintThread.last_reminded_at` 仍由 114-05 承载）。
- `uv run ruff check services/process_runtime/ delivery/services/ system/models.py tests/services/process_runtime/ tests/delivery/` → **All checks passed!**
- `uv run ruff format --check`（**只对** `blueprint_review.py` 与新测试文件；`builtin_processes.py` / `entrypoint.py` / `blueprint_resume.py` / `event_taxonomy.py` / `system/models.py` 按受限面纪律**不跑 format**）→ **2 files already formatted**。

### 冻结面 / 受限面自检

- ⭐ **`git diff c005d5b6..HEAD -- server/services/process_runtime/blueprint_merge.py` 输出为空**（B3 定夺的头号验收：人工块保护挂在审查入口，融合模块一行不改）。
- **22 个冻结 / 受限只读文件 `git diff` 全为 0 行**：`blueprint_merge` / `blueprint_reflow` / `blueprint_lifecycle_service` / `blueprint_schema` / `blueprint_quality` / `blueprint_anchor` / `blueprint_reconcile` / `blueprint_confirm_gate` / `blueprint_spec_gate` / `blueprint_repo_plan` / `blueprint_charter_match` / `blueprint_block_edit` / `codegraph/services/repo_router_v2` / 六个冻结 legacy technical_plan process 文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `clarify_adapter` / `render` / `resume`）/ `delivery/services/merged_plan` / `repositories/services/charter_service` / `system/settings_service` / `agents/call_source`。
- **改动文件恰为 11 个**（PLAN 声明九个 + Deviations #2 登记的两个测试文件）。

### 契约与纪律断言（实跑）

- `events OK` —— 三常量字面值 `blueprint.review.started/completed/failed` 且全部 ∈ `BLUEPRINT_EVENTS`。
- `entry wiring order OK` —— 两个入口接线的源码位置都早于审查基线的 `order_by("-version_no")`。
- `stage graph OK` —— `merge.merged == "ai_review"`、`ai_review` 五条出边逐字匹配、`STAGE_FAILED ∉ transitions.values()`、旧链 `merge.merged == STAGE_DONE`。
- `deps OK ['confirm_gate', 'merge', 'repo_plan', 'research', 'review', 'route', 'spec_gate']` —— 三方一致性（docstring / `SimpleNamespace` / handler `getattr`）。
- `resume map OK` —— `_STAGE_BLUEPRINT_STATUS` 恰为三键且 `ai_review == BlueprintStatus.AI_REVIEWING`。
- **rg 硬验收（adapter 源码）**：`record_answer` **0**、`STAGE_FAILED|"failed"` **0**、`BlueprintThread.objects.(create|acreate)` **0**、`ConvergenceSessionEvent.objects.acreate(|._emit_event(` **0**；`append_note` 4、`resolve_thread` 2、`blocking=(` 1、`ConcurrentBlueprintTransitionError` 3、`aapply_thread_answers` 2、`arestore_human_blocks` 1、`areanchor_threads` 1。
- **在途会话检查**（行为变更前置）：本 worktree 的开发库尚未 migrate（`no such table: delivery_convergence_session`）⇒ **零在途 `current_stage="merge"` 会话**，`merge.merged` 改指 `ai_review` 无存量影响。部署侧升级前仍建议复跑该查询。

## Known Stubs

无。本 plan 未引入任何硬编码空值、占位文案或未接数据源的组件；所有降级路径（章程读失败 / goal-backward 不可得 / 重锚失败 / 事件 emit 失败）都有显式的可观测落点与对应用例。

## Deferred Issues

**`blueprint_lifecycle_service.py:358` 的 `blueprint_transition_event_persist_failed` 仍缺 `category` / `component`** —— 114-04 已登记的历史遗留项（由 111-02 commit `251697a7` 引入）。本 plan 对该文件的配额是**零改动**（受限只读面，`git diff` 必须为空），修它会直接违反硬约束。仍留给 114-05（会正当修改 lifecycle 相关面）顺带补齐。影响有界：该事件是 best-effort 的事件持久化失败 warning，不进指标聚合口径。

## Self-Check: PASSED

- **文件存在**：11 个改动文件全部在磁盘上；`test_blueprint_review_stage.py` 810 行 / 27 个 `def test_`（参数化展开 34 例）✓
- **commit 存在**：`36f4600e` / `13ac3d13` / `8101dcdf` 均在 `git log`（`milestone/v0.20.0-blueprint`）✓
- **artifacts `contains` 断言**：`class BlueprintReviewAdapter` ∈ `blueprint_review.py` ✓；`async def _h_bp_ai_review` ∈ `builtin_processes.py` ✓；`"ai_review": "ai_reviewing"` ∈ `blueprint_resume.py` ✓；`blueprint.review.started` ∈ `event_taxonomy.py` ✓；`review_exhausted` ∈ 新测试文件 ✓
- **key_links 断言**：`open_thread` / `append_note` / `resolve_thread` / `transition` ∈ adapter（全部经 lifecycle）✓；`getattr(getattr(engine, "deps", None), "review", None)` ∈ handler ✓；`review=BlueprintReviewAdapter(...)` ∈ entrypoint ✓
- **must_haves truths 逐条**：恒定键返回 ✓ / B1 入口有生产调用方且有 spy 断言 ✓ / B3 人工块保护接线且 `blueprint_merge.py` 零改动 ✓ / 重锚以版本推进为判据且覆盖重装主路径 ✓ / `severity` 与 `blocking` 同源 ✓ / 去重走留痕不重开线程 ✓ / `record_answer` 零命中 ✓ / 有界回退 ≤2 轮且计数在自己的桶 ✓ / 超界落 `pending_review` 非 FAILED（含可证伪用例）✓ / 两桶互不覆盖 ✓ / 仅 WARNING 不打回 ✓ / 未决清单六键无正文 ✓ / 状态全经 lifecycle ✓ / CAS 异常不外泄 ✓ / `merge.merged` 接续且旧链正向对照 ✓ / resume 映射删除行 0 ✓ / deps 三方一致 ✓ / 事件纯追加 ✓
- **受限面**：删除行 `blueprint_review`=0 / `event_taxonomy`=0 / `system/models`=0 / `blueprint_resume`=0 / `builtin_processes`=2(≤3) / `entrypoint`=2(≤2) ✓
- **门禁**：1263 passed / 0 failed（两套件）✓；全量 8450 passed / 1 failed（与本 plan 无关的 worktree 环境项）✓；`makemigrations --check` 退出码 0 ✓；ruff check + format 通过 ✓

## Next Phase Readiness

- **114-05 可直接消费**上方「114-05 接线契约」的七个消费点与出边映射表。最关键的一条：**超界死锁的唯一出口是 finding 处置端点**（`resolve_thread(dismissed=False/True)`），⛔ 绝不能用作答通道把 finding 推到 `answered`（既解不开门也污染状态）。
- **114-05 的两条既有纪律仍然有效**：确认端点直接调 `transition(artifact, "confirmed", …)`，守卫已在 `_apply_transition_sync` 事务内自足，**禁止**在视图层先查未决 BLOCKER 再 transition（114-01 的源码扫描用例会红）；`aapply_thread_answers` 在 answer 端点里接在 `record_answer` **之后**、同请求内。
- **给后续 writer 的纪律**：① 任何新增的 stage_state 写入都必须只写自己的桶，**绝不整桶读改写别人的键**；② 任何新增的产版本路径必须跟一次 `areanchor_threads`，且判据取「版本推进」而非「本轮是否产版本」；③ 新增出口分支一律走 `_result` 的恒定八键，handler 侧只据 `review_status` 走白名单出边；④ 新增机械规则请加进 114-02 的 `run_mechanical_rules` **固定顺序尾部**（顺序即确定性契约，插中间会让「第 N 轮仍存在」的比对失真）；⑤ 新开 finding 线程的 `question` **必须**保持 `[{rule_id}] {detail}` 前缀 —— 去重索引靠它反查 rule_id，改格式会让第 2 轮重开线程、人审侧噪声爆炸。
