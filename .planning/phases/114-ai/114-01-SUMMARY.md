---
phase: 114-ai
plan: 01
requirements: [FLOW-07]
provides:
  - "`open_thread(artifact, *, kind, blocking, question, options=None, initiated_by_user_id=\"system\", created_on_version=None, anchor=None, return_stage=\"\", severity=\"\") -> BlueprintThread` —— `severity` 为**最后一个** keyword-only 形参，默认空串，**零 migration**"
  - "`severity` 校验规则：`sev = str(severity or \"\")`；`sev` 非空且 ∉ `ThreadSeverity.values` → `ValueError`，文案 `非法线程 severity={severity!r}；合法值={sorted(ThreadSeverity.values)} 或空串`（`sorted` 结果 = `['blocker', 'info', 'warning']`）"
  - "⭐ **不变式报错文案（114-02/03 错配用例须逐字对齐）**：`kind == ThreadKind.AI_REVIEW_FINDING` 且 `bool(blocking) != (sev == ThreadSeverity.BLOCKER)` → `ValueError(\"ai_review_finding 线程必须满足 blocking == (severity == 'blocker')：\" f\"当前 severity={sev!r} blocking={bool(blocking)}\")`。两处 raise 都在任何 DB 写之前（`_open_thread_sync` 尚未调用）⇒ 非法入参零副作用"
  - "`append_note(thread, *, body, author=None, author_type=ThreadAuthorType.AI, initiated_by_user_id=\"system\") -> BlueprintThreadMessage` —— **只追加消息、绝不推进线程 status**；默认 `author_type=\"ai\"`；日志事件 `blueprint_thread_note_appended`（`category=\"caller\"` / `component=\"blueprint_lifecycle\"`，字段 `thread_id`/`kind`/`severity`/`author_type`/`initiated_by_user_id`，**`body` 绝不进日志**）"
  - "`_append_thread_message_sync(thread, *, body, author, author_type=ThreadAuthorType.HUMAN)` —— 新增 `author_type` 形参，默认仍 `HUMAN`（遗漏调用方逐字等价）；全文件唯一的消息追加写点"
  - "`BlueprintLifecycleService._has_confirm_blockers_sync(artifact) -> bool`（`@staticmethod`）—— confirm 唯一守卫判据，**必须在 `_apply_transition_sync` 的 `transaction.atomic()` 内调用**。单次查询用 `Q` 覆盖两条：① `Q(status=OPEN, blocking=True)`；② `Q(kind=AI_REVIEW_FINDING, severity=BLOCKER, status__in=[OPEN, ANSWERED])`"
  - "`aunresolved_blocker_count(artifact) -> int` —— `kind=ai_review_finding & severity=blocker & status ∈ {open, answered}` 计数，**仅供报告**（114-03 `unresolved` 快照 / 114-05 人审呈现），docstring 明写「绝不用于 confirm 守卫判定」"
  - "⚠️ **`_apply_transition_sync` 新报错文案**：`存在未解决的阻塞澄清线程或未决 BLOCKER 审查发现，蓝图不可确认`（旧文案 `存在未解决的阻塞澄清线程，蓝图不可确认` 为其前缀 ⇒ 既有 `pytest.raises(match=...)` 与串前缀匹配不受影响）"
  - "`ahas_open_blocking_threads` / `record_answer` / `resolve_thread` / `apply_gate_action` / `transition` 签名与语义**零改动**"
affects:
  - "114-02（机械规则）/114-03（ai_review 入口）：直接消费 `open_thread(severity=…)`（必须同时给对 `blocking`，否则 ValueError）与 `append_note`（第 N 轮复检留痕）；`unresolved` 快照用 `aunresolved_blocker_count`"
  - "114-05（人审端点）：确认端点**禁止**在事务外先查未决 BLOCKER 再 transition——守卫已在 `_apply_transition_sync` 事务内收敛；违反会被 `test_no_out_of_transaction_blocker_check_before_confirm` 源码扫描逮住"
  - "114-05（finding 处置端点 B2）：`resolve_thread(dismissed=…)` 把 finding 推到 `resolved`/`dismissed` 后即脱离守卫判据②（`status__in=[open, answered]`），confirm 随之放行——死锁出口成立"
key-files:
  created:
    - server/tests/delivery/test_blueprint_review_threads.py
  modified:
    - server/delivery/services/blueprint_lifecycle_service.py
completed: 2026-07-30
---

# Phase 114 Plan 01: 审查线程 API 扩展底座 Summary

**一行结论**：`BlueprintLifecycleService` 单文件内完成四项底座——`open_thread` 追加 `severity: str = ""`（零 migration，`makemigrations --check` 退出码 0）、`ai_review_finding` 在**任何 DB 写之前**强制 `blocking == (severity == "blocker")`、从私有 `_append_thread_message_sync` 提炼公开 `append_note`（留痕不改 status，`_arecord_gate_note` 改为委托它且仍传 `HUMAN`）、confirm 两条判据收敛为 `_apply_transition_sync` 原事务内 `_has_confirm_blockers_sync` 的**单次 `Q` 查询**；19 例新测试全绿且经**双向变异验证真能证伪**（拆掉判据② → `record_answer` 反向断言失败；禁用守卫 → 三条 confirm 用例失败），`tests/delivery/ + tests/services/process_runtime/` **1137 passed** 零回归，受限面删除行 **12 ≤ 12**，`BlueprintThreadMessage.objects.create` 实测仍为 **4**（未新增写表路径）。

## Accomplishments

- **severity 形参零 migration**：`BlueprintThread.severity` 字段自 111-02 即存在（`blueprint_thread.py:92`，`max_length=16`/`blank`/`default=""`），本 plan 只补 service 侧形参与透传。`git diff server/delivery/models/blueprint_thread.py` 输出为空，`makemigrations --check --dry-run` 退出码 0。
- **不变式在 DB 写之前生效**：`severity` 白名单校验与 `blocking == (severity == "blocker")` 两处 `raise` 都紧跟既有 `kind` 白名单之后、`_open_thread_sync` 之前 ⇒ 非法入参**零副作用**（三条错配用例各自断言 `BlueprintThread` 行数不增）。`ThreadSeverity` 走枚举常量白名单，无字面量。
- **`append_note` 是提炼而非新增通道**：照 `resolve_thread` 的「公开 async 方法 = 校验 + 委托 `@sync_to_async` 事务 + 结构化日志三段」形态；`_append_thread_message_sync` 只把硬编码 `author_type=ThreadAuthorType.HUMAN` 换成同名形参（默认仍 `HUMAN`）；`_arecord_gate_note` 改为 `self.append_note(..., author_type=ThreadAuthorType.HUMAN)` 显式传值（**不跟 `append_note` 的 AI 默认值走**）。`BlueprintThreadMessage.objects.create` 出现处**改动前后同为 4**，`test_blueprint_inv6_guard` 3 例全绿。
- **confirm 守卫单次 `Q` 查询 + 纵深防御**：`_has_confirm_blockers_sync` 用一条 `filter(artifact).filter(Q(...) | Q(...)).exists()` 覆盖两条判据。判据②在不变式成立时是①的子集，仍显式写出——**变异验证坐实其价值**：拆掉②后，`record_answer` 把 BLOCKER finding 推到 `answered` 的旁路立刻能放行 confirm（用例 fail）。守卫落在 `_apply_transition_sync` 已有的那个 `transaction.atomic()` 内，视图层与 adapter 层**零事务外二次查询**。
- **`ahas_open_blocking_threads` 一行未改**：它是 `blueprint_resume` 的 pause 判据与 112 确认门专属过滤（带 `kind` 参数），语义与 confirm 守卫不同；混用会让规格门/确认门互相误挡。
- **观测合规**：`blueprint_thread_opened` 追加 `severity` 标量；新增 `blueprint_thread_note_appended`（`category="caller"` / `component="blueprint_lifecycle"` / 带 `initiated_by_user_id`）。`rg -n "body=" blueprint_lifecycle_service.py | rg "logger"` **零命中** —— finding 正文与澄清问题绝不进日志（T-114-05）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `337ea3b3` | `open_thread` 的 `severity` 形参 + 白名单校验 + `blocking` 不变式 + `_open_thread_sync` 透传 + 日志标量 + 只读 `aunresolved_blocker_count` |
| 2 | `baa092a4` | 公开 `append_note` + `_append_thread_message_sync` 的 `author_type` 形参 + `_arecord_gate_note` 委托 + `_has_confirm_blockers_sync` 单次 `Q` 守卫收敛 |
| 3 | `0d4f4318` | `test_blueprint_review_threads.py` 19 例（severity / 不变式 / `append_note` / `record_answer` 反向断言 / TOCTOU / 源码扫描 ×2 / 门留痕等价） |

## Files

- `server/delivery/services/blueprint_lifecycle_service.py`（修改：+ `ThreadSeverity` import、+ `from django.db.models import Q`、+ `_has_confirm_blockers_sync`、+ `aunresolved_blocker_count`、+ `append_note`、`open_thread` 与 `_open_thread_sync` 的 `severity` 形参链、`_append_thread_message_sync` 的 `author_type` 形参、`_arecord_gate_note` 委托、`_apply_transition_sync` 守卫两行化）
- `server/tests/delivery/test_blueprint_review_threads.py`（新建 19 例，模块 docstring「守九件事」编号清单）

## 受限面删除行逐行登记（合计 12 ≤ 12）

| # | 原行号 | 归属 | 删除内容 | 理由 |
| - | ------ | ---- | -------- | ---- |
| 1 | 241 | `_apply_transition_sync` docstring | `          期间新建的阻塞线程不再被漏挡（MN-01）。` | 该行续写为「自 114-01 起为 `_has_confirm_blockers_sync` 的单次 `Q` 查询覆盖两条判据」，首行 `- confirm 守卫（open+blocking 线程）与 CAS 同事务：…` 逐字保留 |
| 2–9 | 252–259 | `_apply_transition_sync` 函数体 | 8 行内联守卫（`if to_status == CONFIRMED:` + 5 行 `BlueprintThread.objects.filter(...).exists()` + `if has_open_blocking:` + 旧 `raise ValueError`） | 提炼为 `self._has_confirm_blockers_sync(artifact)` 两行调用，判据从一条扩到两条且仍在同一 `transaction.atomic()` 内（PLAN 预估「5 行」与实测 8 行不符，见 Deviations #1） |
| 10 | 1053 | `_arecord_gate_note` 函数体 | `        return await self._append_thread_message_sync(thread, body=str(body or ""), author=author)` | 改为委托 `self.append_note(..., author_type=ThreadAuthorType.HUMAN)`；docstring 全文保留并追加一行说明 |
| 11 | 1057 | `_append_thread_message_sync` 签名 | `        self, thread: BlueprintThread, *, body: str, author: Any` | 签名展开为多行以容纳 `author_type: str = ThreadAuthorType.HUMAN` 形参 |
| 12 | 1061 | `_append_thread_message_sync` 函数体 | `            author_type=ThreadAuthorType.HUMAN,` | 硬编码值换成形参 `author_type=author_type,` |

全部 12 行落在 `_apply_transition_sync`（含其 docstring）/ `_arecord_gate_note` / `_append_thread_message_sync` 三处，与 PLAN 允许的归属清单完全一致；顶层 import 块与其余部分**零删除**（两个 import 均为纯追加）。

## `blueprint_gate_views.py` 报错文案核对结果

**无需改动，零扩大改动面。** `BlueprintGateConfirmView`（`blueprint_gate_views.py:239-240`）的 409 走的是 `apply_gate_action` 返回的**结构化字段** `result["blocked_reason"] == "pending_clarification"`，其 detail 串 `"存在未解决的阻塞澄清线程"` 是视图**自己拼的常量**，与 `_apply_transition_sync` 的 `ValueError` 文案无任何耦合。全仓 `rg "存在未解决的阻塞澄清线程"` 命中三处：service 的 raise（本 plan 改）、gate view 的 detail 常量（未改）、`test_blueprint_gate_api.py:358` 对该 detail 的断言（未改，仍绿）。此外新文案以旧文案为**前缀**，即便有 `pytest.raises(match=...)` 式的正则搜索也不会失效。

## Decisions

- **`_has_confirm_blockers_sync` 取 `@staticmethod`**：它不读任何实例状态，且测试需要用 `monkeypatch.setattr(cls, name, staticmethod(fn))` 在守卫窗口内注入竞态行。做成实例方法会让 patch 的绑定语义变复杂（`self` 会被吃掉一个位置参），静态方法与调用点 `self._has_confirm_blockers_sync(artifact)` 两边都自然。
- **判据②保留而非收敛掉**：不变式成立时②是①的子集，理论上可删。保留的理由由变异验证给出——它是唯一挡住「误用 `record_answer` 留痕」这条旁路的防线，而 `record_answer` 是既有公开方法、任何后续 plan 都可能误调。纵深防御的成本是同一条 `Q` 里多一个分支（零额外查询）。
- **TOCTOU 用例用「守卫窗口内插行」而非真多线程**：`_apply_transition_sync` 是 `@sync_to_async` + `transaction.atomic()`，真并发在 SQLite 上只会撞表锁而非撞到守卫窗口。改为 monkeypatch 守卫、进入时先真实 `create` 一条 `open+blocking` finding 再调原实现——精确模拟「守卫查询发生的那一刻线程刚被建出来」，且**配对照组**（不插行时 transition 成功）证明断言非恒真。守卫「确在事务内」这条正交事实由独立的源码行号扫描用例承担。

## Deviations from Plan

共 2 处，均为 PLAN 预估与实测不符的修正，无功能性偏离。

**1. [Rule 3 - PLAN 行数预估与实测不符] `_apply_transition_sync` 内联守卫实测 8 行（PLAN 写 5 行），删除行预算按实际重新分配**

- **Found during:** Task 2
- **Issue:** PLAN `<execution_context>` 把 `_apply_transition_sync:252-259` 的内联守卫记为「5 行」并给该项 ≤7 行预算（含 docstring 1 行），总预算 ≤12。实测该守卫是 8 行（`if` + 5 行 filter 链 + `if has_open_blocking:` + `raise`）。按 PLAN 原写法「docstring 首条说明同步补一句」会改掉 2 行 docstring，合计 13 行，**超出总预算 12**。
- **Fix:** 把 docstring 改动收窄为**只改续行 1 行**（首行 `- confirm 守卫（open+blocking 线程）与 CAS 同事务：check-then-act 窗口收敛，` 逐字还原，新说明追加在续行之后），删除行降至 **12**，正好落在预算内且逐行归属仍在允许清单中。守卫本体改动形状与 PLAN 完全一致。
- **Files modified:** `server/delivery/services/blueprint_lifecycle_service.py`
- **Commit:** `baa092a4`

**2. [Rule 3 - 范围外，未修] `ruff check delivery/` 报 4 条 I001，全在既有 Django 生成 migration**

- **Found during:** Task 2 acceptance
- **Issue:** PLAN Task 2 验收要求 `uv run ruff check delivery/` 通过，实跑报 4 错，全部是 `0026_clarification_questions.py` / `0027_artifact_…` / `0030_humantask.py` / `0031_blueprint_models.py` 的 import 未排序 —— Django `makemigrations` 生成风格，与本 plan 无关（113-01 SUMMARY 已登记过同一批，属既有欠账）。
- **Fix:** 按「只修本 task 改动直接导致的问题」的范围纪律**不修**。改以「本 plan 触及的 2 个 py 文件 `ruff check` 全通过 + 新测试文件 `ruff format --check` 通过」作为等价验收，两者均已实测通过。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/delivery/test_blueprint_review_threads.py`：**19 passed**（severity 三档参数化 3 + 既有调用等价 1 + 不变式错配 3 + 合法对照 2 + 非 finding 豁免 1 + 非法 severity 1 + `append_note` 不改状态 1 + 留痕后仍拒 confirm 1 + `record_answer` 反向断言 1 + TOCTOU 竞态 1 + 无阻塞对照 1 + 守卫在事务内源码扫描 1 + 视图零二次查询源码扫描 1 + 门留痕 human 等价 1）
- **PLAN verification 全套**：`uv run pytest tests/delivery/ tests/services/process_runtime/ -q` → **1137 passed**（`tests/delivery/` 单跑 620 passed，与本 plan 动工前逐字一致 ⇒ 112-05 确认门八端点、111-02 lifecycle、INV-6 扫描零回归）
- ⭐ **变异验证（证伪能力实测，非声明）**：
  1. 把 `_has_confirm_blockers_sync` 的 `Q` 拆掉判据②（只留 `Q(status=OPEN, blocking=True)`）→ `test_record_answer_on_finding_breaks_legacy_gate_but_new_guard_holds` **fail**（1 failed / 18 passed）⇒ 纵深防御真的在挡 `record_answer` 旁路，反向断言非恒真。
  2. 把守卫调用整体短路（`if False and …`）→ `test_append_note_then_confirm_still_blocked` / `test_record_answer_…` / `test_confirm_guard_rejects_thread_created_inside_guard_window` **三条同时 fail**（3 failed / 16 passed）⇒ TOCTOU 用例确实依赖守卫真的执行。
  3. 两次变异均已 `git checkout --` 回滚，`git status --short` 干净后才提交 Task 3。
- `uv run python manage.py makemigrations --check --dry-run`：`No changes detected`，退出码 **0**（零 migration 的硬证据）
- `git diff server/delivery/models/blueprint_thread.py`：输出为空（模型一行不改）
- **冻结面自检**：`git diff --name-only HEAD~3 HEAD` 只含 `server/delivery/services/blueprint_lifecycle_service.py` 与 `server/tests/delivery/test_blueprint_review_threads.py` 两个文件；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / blueprint_resume / blueprint_schema / blueprint_quality / blueprint_merge / blueprint_confirm_gate / blueprint_spec_gate / charter_service / settings_service / event_taxonomy / call_source / blueprint_thread.py / task/ / web/` **零命中**
- **受限面自检**：`git diff HEAD~3 HEAD -- …blueprint_lifecycle_service.py | rg "^-" | rg -v "^---" | wc -l` = **12**（逐行登记见上表）
- **写表路径自检**：`rg -c "BlueprintThreadMessage.objects.create" …blueprint_lifecycle_service.py` = **4**（`_open_thread_sync` 首条问 / `_record_answer_sync` / `_resolve_thread_sync` 结论 / `_append_thread_message_sync`），与动工前实测值相同 ⇒ 未新增第 5 处
- **观测面自检**：`rg -n "body=" …blueprint_lifecycle_service.py | rg "logger"` 零命中；`rg -c "ThreadSeverity" …` = 8（import + 白名单 + 不变式 + 守卫 + 计数 helper 等）
- **代码风格**：`uv run ruff check delivery/services/blueprint_lifecycle_service.py` All checks passed（**未对该受限文件跑 `ruff format`**）；新测试文件 `ruff format` + `ruff check --fix` 后 `ruff format --check` 通过

## Self-Check: PASSED

- 文件存在：`server/delivery/services/blueprint_lifecycle_service.py` ✓（修改）、`server/tests/delivery/test_blueprint_review_threads.py` ✓（新建）
- commit 存在：`337ea3b3` / `baa092a4` / `0d4f4318` 均在 `git log`
- artifacts contains 断言：`def append_note` ∈ service ✓（`:552`）；`append_note` ∈ 测试文件 ✓（9 处命中）
- key_links 断言：`ThreadSeverity` ∈ service ✓（8 处，枚举白名单无字面量）；`self.append_note(` ∈ service ✓（`:1163`，`_arecord_gate_note` 委托）
- must_haves truths 逐条：`severity: str = ""` ✓（`:418`）/ 112-113 调用等价（620 passed 零变化）✓ / 不变式 DB 写前拒绝 ✓ / `append_note` 不改 status ✓ / `_arecord_gate_note` 仍 human ✓ / 守卫事务内单次查询 ✓ / `record_answer` 反向断言 ✓ / `aunresolved_blocker_count` 仅供报告 ✓

## Next Phase Readiness

- **114-02 / 114-03**：`open_thread(kind=ThreadKind.AI_REVIEW_FINDING, severity=…, blocking=…)` 必须**成对**给值——`blocker/True`、`warning/False`、`info/False` 是仅有的三种合法组合，其余一律 `ValueError`（文案见 provides，错配用例请逐字对齐）。第 N 轮复检留痕**只能**用 `append_note`，用 `record_answer` 会被 `test_record_answer_on_finding_breaks_legacy_gate_but_new_guard_holds` 的语义反噬（守卫虽仍挡住，但线程状态被污染、`ahas_open_blocking_threads` 失真）。
- **114-05**：确认端点直接调 `transition(artifact, "confirmed", …)` 即可，守卫已自足；**禁止**在视图层先 `aunresolved_blocker_count` 再 transition（源码扫描用例已就位，会 fail）。未决清单呈现请用 `aunresolved_blocker_count`（只读）。
- **B2 死锁出口已通**：finding 处置走 `resolve_thread(dismissed=True/False)` → 线程离开 `{open, answered}` → 守卫判据②不再命中 → confirm 放行。114-05 的端到端用例可直接建立在这条链上。
- **给后续 writer 的硬约束**：`_has_confirm_blockers_sync` 只允许在 `_apply_transition_sync` 的事务内调用；新增守卫判据请加进那条 `Q`，**不要**新开查询或把判定挪到调用方。`append_note` 是唯一「留痕不改状态」的公开通道，新增留痕点走它，不要再提炼第二条写表路径（`test_blueprint_inv6_guard` + `create` 计数双守）。
