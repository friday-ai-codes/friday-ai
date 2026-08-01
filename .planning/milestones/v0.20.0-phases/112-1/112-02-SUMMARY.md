---
phase: 112-1
plan: 02
requirements: [FLOW-01]
provides:
  - "BlueprintLifecycleService 四个线程写入方法：ahas_open_blocking_threads(artifact, kind=None) / open_thread(...) -> BlueprintThread / record_answer(thread, body=..) -> BlueprintThreadMessage / resolve_thread(thread, dismissed=False)——BlueprintThread(+Message) 的唯一 writer，112-05 确认门（repo_confirmation）直接复用同一套 API"
  - "blueprint_ambiguity_score：ascore_ambiguity(goal, feature_points, constraints, prior_context, session_id) -> dict | None（单次 LLM，call_source=blueprint_spec_gate）+ 三个判定纯函数 normalize_ambiguity_scores / weighted_total / is_ambiguous + aload_spec_gate_config() 与 DEFAULT_SPEC_GATE_CONFIG"
  - "blueprint_intent_classify：aclassify_intents(feature_points, session_id) -> dict[fp_id, intent] | None（call_source=blueprint_decompose）+ normalize_intents(data, allowed_ids) + DEFAULT_INTENT='brownfield'"
  - "BlueprintSpecGateAdapter.run(session) 返回契约：{event: 'needs_clarification'|'spec_locked', thread_id: str|None, ambiguity: dict, round: int, stage_state: {'spec_gate': {round, thread_id, pending}}}；stage_state 键常量 STAGE_STATE_KEY='spec_gate'"
  - "ambiguity_report 落位形状：{dimensions, weighted_total, threshold, weights, resolved_thread_ids, capped, scorer_unavailable}；decision_log 条目形状 {thread_id, question, answer, decided_at, decided_by}"
affects:
  - "112-05（stage 注册 + 确认门）：spec_gate handler 按 run() 的 event 值决定 StageOutcome（spec_locked→route / needs_clarification→self-loop）；确认门复用四个线程方法；blueprint_resume 用 ahas_open_blocking_threads 判 pause"
  - "112-03（route）：消费规格锁定后 feature_points[].intent 恒为合法枚举（无需 None 分支）"
  - "115（前端）：三个 spec_gate 事件的 payload 形状在此定型（只含标量与关联键）"
key-files:
  created:
    - server/services/process_runtime/blueprint_ambiguity_score.py
    - server/services/process_runtime/blueprint_intent_classify.py
    - server/services/process_runtime/blueprint_spec_gate.py
    - server/tests/delivery/test_blueprint_thread_service.py
    - server/tests/services/process_runtime/test_blueprint_ambiguity_score.py
    - server/tests/services/process_runtime/test_blueprint_spec_gate.py
  modified:
    - server/delivery/services/blueprint_lifecycle_service.py
completed: 2026-07-30
---

# Phase 112-1 Plan 02: 规格门歧义门（LLM 四维打分 + 澄清线程 + 规格锁定）Summary

**一行结论**：规格门完整回路跑通——`BlueprintLifecycleService` 补齐四个线程写入方法后成为 `BlueprintThread` 的唯一 writer（既有 `transition` 零删改行），四维打分与意图分类各为一次可 mock 的 LLM 单调用且判定全在可单测纯函数里，`BlueprintSpecGateAdapter.run` 以「pending 短路 → 轮数上界 → 已答结论拼装 → 打分 → 超阈值开带候选与证据的阻塞线程 → 放行时 requirement_spec/ambiguity_report/decision_log 一次性落新蓝图版本」六步收口；三条降级路径（LLM 不可得 / 内容校验失败 / 无蓝图版本）全部 fail-closed 判需澄清，唯一放行例外是轮数上界且在 `ambiguity_report.capped` 留痕。

## Accomplishments

- **线程写入唯一 writer（Task 1）**：四个方法全部追加在 `BlueprintLifecycleService` 尾部——`git diff` 无任何删除行，既有 `transition` / `add_reviewer` / `_apply_transition_sync` / `_ALLOWED_TRANSITIONS` 逐字未动，`__all__` 未变。线程行与首条 AI 提问消息在同一 `transaction.atomic` 内落库（非法 kind 抛 `ValueError` 且零行写入，实测 `BlueprintThread.objects.acount() == 0`）；`record_answer` 只把 `open` 推到 `answered`，终态线程再作答只追加消息不回退；`resolve_thread` 以 DB 现值为条件更新，天然幂等（连调两次仍 `resolved`，且首次的结论消息不被重复追加）。`return_stage` 超字段 `max_length=16` 截断而非抛——开不出线程等于规格门静默放行，宁可截断。INV-6 源码扫描守护（`test_blueprint_inv6_guard`）继续全绿，且 `server/services/` 与 `server/delivery/api/` 内 `BlueprintThread.objects.create|acreate` 零命中。

- **四维打分 helper（Task 2）**：`ascore_ambiguity` 逐条镜像 `feature_classify` 的五步骨架（lazy import → `ProviderConfigService.aresolve` → 无 `default_model` 记事件返 `None` → `build_chat_model(streaming=False)` → `use_call_source(CallSource.BLUEPRINT_SPEC_GATE)`），响应经 ```json 围栏 + 裸 JSON 双路解析。**保守方向即 fail-closed**：缺维 / 非数 / 非法一律落 1.0（最歧义），且「理由为空 = 判定失去依据 → 该维降级到保守值 + 占位理由」（镜像 feature_classify 的 modify 无证据回落 unclear）。`weighted_total` 权重缺项取同维默认、全零回退等权（否则总分恒 0 = 门形同虚设）、结果 clamp；`is_ambiguous` 用 `>=`（等于阈值即判需澄清）。`aload_spec_gate_config` 读 `SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG`，`threshold` 经 `float()` + clamp `[0,1]`（实测 `99 → 1.0`）、`weights` 非 dict 回默认、负值取 0，整段异常回默认——绝不抛、绝不 eval（T-112-07）。

- **意图分类 helper（Task 2）**：`normalize_intents` 用 `allowed_ids` 丢弃 LLM 编造的 feature_point id，非法枚举回落 `brownfield`——保守值选「存量改造」是因为它更难被绕过（净新增假设会让路由跳过能力树证据要求）。输出值恒 ∈ `_VALID_INTENT`，`blueprint_schema` 的必填枚举永不违约。

- **规格门 adapter（Task 3）**：`_collect_prior_answers` 一次读出「已 answered/resolved 澄清线程的问答 + 蓝图 `decision_log`」，同时产出重判 prompt 文本、问题指纹集合、`resolved_thread_ids` 与待物化条目——**同一问题不再重复问**是靠指纹剔除实现的（合并提问时的 `N. ` 编号前缀在取指纹前剥掉，多题合并的线程也能逐题去重）。放行路径深拷贝当前版本 content，补齐 intent（已有合法值 > 分类器 > `brownfield`）、写 `ambiguity_report`、按 `thread_id` 去重追加 `decision_log`，再经 `ArtifactService.add_version` 一次性落版本并把仍 `answered` 的线程收尾。`ArtifactContentInvalid` 被捕获→判需澄清（绝不上抛让 engine 落 `failed`）；事件 emit 独立私有方法 + `except Exception` 吞掉。adapter **零 ORM 写**（`.objects.create|acreate|update|aupdate` 零命中），线程经 lifecycle、版本经 ArtifactService。

- **观测面**：三个 112-01 已注册的事件常量全部接上 emit 点（`blueprint.spec_gate.scored` / `.clarification_asked` / `.locked`），payload 只含 `thread_id` / 计数 / 标量分数；两个 LLM helper 的 started/completed/failed 六个事件均带 `category="sampling"` + `component="process_runtime"` + `duration_ms`，adapter 侧生命周期事件带 `category="caller"`；异常文本一律经 `redact_secrets_in_text`；**需求正文与澄清问答正文不进任何日志或事件 payload**（T-112-08）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `ca5c98de` | BlueprintLifecycleService 追加四个线程写入方法（纯追加）+ 11 例线程 service 测试 |
| 2 | `c7c8ed0a` | blueprint_ambiguity_score（四维打分 + 三纯函数 + config loader）+ blueprint_intent_classify + 33 例测试 |
| 3 | `6457ed69` | blueprint_spec_gate adapter 六步回路 + 13 例 stage 测试 + 设置隔离 fixture |

> 本 plan 与 112-03 同分支并行，`git log` 中三个 commit 之间夹有 112-03 的提交（正常，文件面零重叠）。

## Files

- `server/delivery/services/blueprint_lifecycle_service.py`（修改：import 块插入 3 个名字 + 常量 `_MAX_RETURN_STAGE_CHARS` + 类尾追加 4 公开 3 私有方法；**零删除行**）
- `server/services/process_runtime/blueprint_ambiguity_score.py`（新建：四段契约 docstring / 四维常量与默认配置 / 三纯函数 / config loader / LLM 五步骨架 / prompt 两私有函数）
- `server/services/process_runtime/blueprint_intent_classify.py`（新建：同骨架小型版，`_VALID_INTENT` + `normalize_intents` + `aclassify_intents`）
- `server/services/process_runtime/blueprint_spec_gate.py`（新建：`BlueprintSpecGateAdapter`，依赖全 keyword-only 可注入，`_MAX_SPEC_GATE_ROUNDS = 3`）
- `server/tests/delivery/test_blueprint_thread_service.py`（新建，11 例）
- `server/tests/services/process_runtime/test_blueprint_ambiguity_score.py`（新建，33 例）
- `server/tests/services/process_runtime/test_blueprint_spec_gate.py`（新建，13 例）

## Decisions

- **`ambiguity_report` 在两条路径上都产出**：开线程时也回一份（`resolved_thread_ids=[]`），让 handler 无论走哪个分支都拿到同形状结果，避免 112-05 写分支解析。
- **`decided_by` 取回答消息的 author_id**，无 author（AI 代答/系统作答）时落 `"human"`——线程模型无「决策者」字段，只能从消息流推断。
- **`resolved_thread_ids` 口径 = 有实际回答的 answered + resolved 线程**（不含 open / dismissed）：`dismissed` 是「问题被撤销」，不构成规格结论。
- **打分 helper 的 completed 事件内联读一次配置**产出 `weighted_total` / `threshold` / `above_threshold` 分桶指标（PLAN 明列的字段）；loader 自身全兜底，读失败只影响这条日志的数值精度，不影响返回值。
- **测试隔离 fixture 下沉到两个测试文件**而非 conftest：只有这两个文件读写 `blueprint.*` 设置键，放 conftest 会给无关测试加 DB 依赖。

## Deviations from Plan

共 6 处，其中 3 处为按现实修正的事实性偏差，3 处为完成 PLAN 要求所必需的加性扩展。均无功能缩水。

**1. [Rule 3 - 阻塞修复] `ascore_ambiguity` 增加 `prior_context: str = ""` 关键字参数**

- **Found during:** Task 3
- **Issue:** PLAN Task 2 给的签名是 `(goal, feature_points, constraints, session_id)`，但 Task 3 步骤 3 明确要求「已答内容与既有结论……一并拼进打分 prompt 输入（镜像 clarify_adapter L170-175）」——原签名没有承载它的入口。
- **Fix:** 加一个默认空的关键字参数，非空时在 prompt 末尾追加「### 已澄清结论（请勿重复追问……）」分节。默认值为空 ⇒ 不传时行为与 PLAN 原签名逐字一致。
- **Files modified:** `server/services/process_runtime/blueprint_ambiguity_score.py`
- **Commit:** `c7c8ed0a`（测试 `test_score_prior_context_enters_prompt` / `test_prior_answers_feed_back_into_scoring_prompt` 锁死）

**2. [Rule 3 - 阻塞修复] `BlueprintSpecGateAdapter.__init__` 增加第 5 个可注入依赖 `session_service`**

- **Found during:** Task 3
- **Issue:** PLAN 列了 4 个注入依赖（lifecycle / artifacts / scorer / classifier），但同时要求 emit 三个 `ConvergenceSessionEvent` 事件——emit 通道 `ConvergenceSessionService._emit_event` 没有注入位。
- **Fix:** 按 `clarify_adapter` L95-107 同款范式补 `session_service: ConvergenceSessionService | None = None`（`x or DefaultX()`）。属 PLAN 授予的「adapter 内部函数切分自行决定」范围。
- **Files modified:** `server/services/process_runtime/blueprint_spec_gate.py`
- **Commit:** `6457ed69`

**3. [Rule 3 - 契约补全] `run()` 返回 dict 增加第 5 个键 `stage_state`**

- **Found during:** Task 3
- **Issue:** PLAN 同时要求「返回形状恒定 `{event, thread_id, ambiguity, round}`」与「步骤 5 返回 `needs_clarification` + `stage_state` 增量 `{"spec_gate": {...}}`」——四键形状装不下 stage_state 增量。
- **Fix:** `stage_state` 作为**恒定存在**的第 5 键（所有分支都填），形状恒定性不破，handler 侧无需分支判断。
- **Files modified:** `server/services/process_runtime/blueprint_spec_gate.py`
- **Commit:** `6457ed69`

**4. [Rule 1 - 事实修正] 「理由为空」的降级条件从「score 高且 reason 空」放宽为「reason 空」**

- **Found during:** Task 2
- **Issue:** PLAN 写的是「某维 score 高但 reason 为空 → reason 补占位且该维保持保守值」。「score 高」没有可判定的界（0.5？0.8？），且真正危险的方向恰恰相反——**低分且无理由**才是「无依据的放行结论」，正是 `feature_classify`「结论失依据就降级」要防的形态。
- **Fix:** 任何 reason 为空的维一律落保守值 1.0 + 占位理由。PLAN 描述的情形是其子集，降级方向仍严格朝 fail-closed（只会多问，不会少问）。已在模块 docstring 与 `normalize_ambiguity_scores` docstring 写明。
- **Files modified:** `server/services/process_runtime/blueprint_ambiguity_score.py`
- **Commit:** `c7c8ed0a`（`test_normalize_empty_reason_keeps_conservative_score`）

**5. [Rule 1 - 事实修正] intent 兜底测试改为旁路造数据（正常入库路径造不出「无 intent」的蓝图版本）**

- **Found during:** Task 3
- **Issue:** PLAN Task 3 要求测「classifier 返 `None` 且 feature_point 无 intent → 落 `brownfield`」，但 112-01 已把 `intent` 变成 `feature_points.items.required` 的必填枚举——用 `ArtifactService.create` 造缺 intent 的蓝图会被 `ArtifactContentInvalid` 直接拒（实测报错 `'intent' is a required property`），测试根本进不到 adapter。
- **Fix:** 先用合法样例建 artifact，再用 `ArtifactVersion.objects.filter(...).aupdate(content=...)` 旁路抹掉在库版本的 intent（模拟历史/手改数据），然后跑 adapter 断言它把值补回 `brownfield` 且新版本过 `validate_blueprint`。测试意图（兜底确实兜得住、schema 必填枚举不被违约）完全保留，且更贴近这条分支唯一可能的真实触发场景。
- **Files modified:** `server/tests/services/process_runtime/test_blueprint_spec_gate.py`
- **Commit:** `6457ed69`

**6. [Rule 1 - Bug] 跨测试文件的 `SystemSetting` 污染 + sqlite 写锁，补隔离 fixture 并把配置用例改 `transaction=True`**

- **Found during:** Task 3 verify（单文件全绿、合并跑时 `test_low_score_locks_spec_and_passes_schema` 假红）
- **Issue:** 打分测试里 `sync_to_async(_save_setting)` 在独立线程/连接上提交，非事务型 `django_db` 的回滚覆盖不到——残留的 `weights`（`goal` 被 clamp 到 0）漏进规格门测试，把加权总分从 0.05 拉到 0.035。112-01 的 `test_blueprint_settings.py` 只清 60s 缓存、不清 DB 行，同样会污染（相位门跑全量时必炸）。首版隔离 fixture 在非事务事务里发 DELETE，又与另一连接的 INSERT 撞上 sqlite 写锁。
- **Fix:** 两个测试文件各加 autouse fixture，前后清 `key__startswith="blueprint."` 的设置行与其缓存；打分测试的 11 个 DB 用例改 `@pytest.mark.django_db(transaction=True)`（无外层事务持锁，teardown 自带 flush）。合并跑 122 passed（含 112-01 的 17 例设置测试）。
- **Files modified:** `server/tests/services/process_runtime/test_blueprint_ambiguity_score.py`、`server/tests/services/process_runtime/test_blueprint_spec_gate.py`
- **Commit:** `6457ed69`

## 测试与验证

- PLAN verification 主面（5 文件）：**105 passed**
  - `tests/services/process_runtime/test_blueprint_ambiguity_score.py`：33 passed（新建）
  - `tests/services/process_runtime/test_blueprint_spec_gate.py`：13 passed（新建）
  - `tests/delivery/test_blueprint_thread_service.py`：11 passed（新建）
  - `tests/delivery/test_blueprint_lifecycle_service.py`：既有全绿（新方法未破坏 LIFE-01/02/03）
  - `tests/delivery/test_blueprint_inv6_guard.py`：全绿（新 writer 被守护认可）
- 加跑 112-01 的 `tests/test_blueprint_settings.py`：**122 passed**（验证隔离 fixture 消除了跨文件污染）
- 111 底座回归：`test_blueprint_schema` / `test_blueprint_execution` / `test_blueprint_quality` 合计 **66 passed**
- `uv run python manage.py makemigrations --check --dry-run`：`No changes detected`，退出码 0（本 plan 零模型改动）
- **相位门全量测试（`pytest -q` 全套）按 PLAN 约定留给 wave 4 的 112-05**（本 plan 与 112-03 同分支并行，跑全量会被对方半成品染红）
- acceptance 断言逐条实测：
  - `rg -c "^    async def (ahas_open_blocking_threads|open_thread|record_answer|resolve_thread)"` = 4
  - `git diff server/delivery/services/blueprint_lifecycle_service.py | rg "^-" | rg -v "^---"` 输出为空（纯追加）
  - `rg "BlueprintThread.objects.(create|acreate)" server/services/ server/delivery/api/` 零命中
  - `use_call_source(CallSource.BLUEPRINT_SPEC_GATE)` / `BLUEPRINT_SPEC_GATE_CONFIG` / `_VALID_INTENT = ("greenfield", "brownfield", "fix")` 全部命中
  - 打分模块 3 个观测事件 ×4 处、`category="sampling"` ×6、两模块各含 `redact_secrets_in_text`
  - `rg "raise" blueprint_ambiguity_score.py | rg -v "ValueError.*kind"` 计数 0（helper 绝不上抛）
  - spec_gate：`resolved_thread_ids` / `decision_log` / `_MAX_SPEC_GATE_ROUNDS`（3 处）/ 三个事件常量全部命中；`Clarification` 零命中；`.objects.(create|acreate|update|aupdate)` 零命中
- 冻结面自检：本 plan 三个 commit 触及 7 文件 = PLAN `files_modified` 全集；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / system/models / settings_service / event_taxonomy / blueprint_schema` 零命中；并行自检 `blueprint_route.py` 未被本 plan 触碰
- 代码风格：改动文件全部经 `uv run ruff format` + `uv run ruff check --fix`，All checks passed

## Self-Check: PASSED

- 文件存在：7 个 `files_modified` 全部命中（6 新建 + 1 修改）
- commit 存在：`ca5c98de` / `c7c8ed0a` / `6457ed69` 均在 `git log`
- artifacts contains 断言：`async def open_thread` ∈ blueprint_lifecycle_service.py ✓；`BLUEPRINT_SPEC_GATE` ∈ blueprint_ambiguity_score.py ✓；`_VALID_INTENT` ∈ blueprint_intent_classify.py ✓；`resolved_thread_ids` ∈ blueprint_spec_gate.py ✓
- key_links 断言：`BlueprintLifecycleService` / `add_version` ∈ blueprint_spec_gate.py ✓；`BLUEPRINT_SPEC_GATE_CONFIG` ∈ blueprint_ambiguity_score.py ✓

## Next Phase Readiness

- **112-05（stage 注册 + 确认门）**：spec_gate handler 只需读 `run()` 的 `event` 字段映射 StageOutcome（`spec_locked` → route、`needs_clarification` → self-loop 挂起），并把 `stage_state` 增量合并进 session；确认门直接用同四个线程方法开 `repo_confirmation` 线程；`blueprint_resume` 的 pause 判据用 `ahas_open_blocking_threads(artifact)`（不传 kind = 两类线程都算）。
- **112-03（route）**：规格锁定后 `feature_points[].intent` 恒为合法枚举，路由加权无需 `None` 分支。
- **待接线的缺口**：本 plan 只交付 adapter，**stage 未注册**（`builtin_processes.py` 属 112-05）；蓝图状态到 `needs_clarification` 的 `transition` 调用也归 112-05 的 handler（adapter 按 engine 纯度不写 session/artifact 状态）。
- **可调旋钮**：`blueprint.spec_gate.config` 运行时可改阈值与四维权重（默认 0.20 + 0.30/0.25/0.20/0.25）；`_MAX_SPEC_GATE_ROUNDS = 3` 是模块常量，若实战发现三轮不够可外置为设置键。
