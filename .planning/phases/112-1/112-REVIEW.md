---
phase: 112-1
status: findings
reviewed: 2026-07-30
depth: deep
diff_base: 94479721
findings:
  critical: 2
  major: 7
  minor: 7
  total: 16
frozen_surface: clean
---

# Phase 112-1 代码审查报告（规格门与双面路由调研）

**审查范围：** `git diff 94479721..HEAD -- server/`（Phase 111 末尾 commit `94479721` 至
`89d5afb0`），22 个源文件 + 22 个测试文件，+14275/-41。只审 server/ 源码与测试，
`.planning/` 文档不审。

**审查方式：** 逐文件通读 11 个新模块 + 7 个改动文件的完整 diff；跨文件追踪四条链
（REST → lifecycle → adapter → engine / 容器回调 → barrier → 续驱 / route → charter →
research / gate action → charter 回灌）；对 112-VERIFICATION.md 已判 VERIFIED 的 16 条
truth **不复算能力有无**，只查它没覆盖的 bug / 安全 / 并发 / 语义空洞维度。

**结论：** 2 CRITICAL / 7 MAJOR / 7 MINOR。冻结面复核**通过**（10 个声明冻结文件
`git diff` 为空）。两条 CRITICAL 都不是「功能没做」，而是「做了但在真实并发/降级路径上
会做错事」：一条会把无关的 `technical_plan` 会话打成 FAILED，一条让规格门的 fail-closed
在 LLM 持续不可用时开门放行且不留旁路痕迹。

---

## Critical Issues

### CR-01：确认门动作端点按「最近一条」取会话，不校验 `process_type`，可把无关 `technical_plan` 会话驱成 FAILED

**File:** `server/delivery/api/blueprint_gate_views.py:68-76`（`_aload_session`），
受影响调用点 `:227 / :257 / :279 / :300 / :321 / :435`

**Issue:**
`_aload_session` 只按 `current_artifact_version__artifact_id` 过滤，取 `-created_at`
第一条，**不带 `process_type` 条件**：

```python
ConvergenceSession.objects.filter(current_artifact_version__artifact_id=artifact_id)
    .order_by("-created_at").afirst()
```

而蓝图链**刻意复用**了 `technical_plan` 这个 `artifact_type`（`builtin_processes.py`
第三次 `register_process_type` 的注释：「artifact_type 复用 Phase 111 的 technical_plan」），
所以同一个 artifact 上完全可能同时挂着 `technical_plan` 与 `technical_blueprint` 两条会话。
一旦最近一条是 `technical_plan`，六个动作端点拿到的 `session` 就是错的，随后
`blueprint_resume.aresume_after_gate_action(session)` 会用
`build_blueprint_engine()`（deps 只有 `spec_gate/route/research/confirm_gate`）去
`engine.advance` 它。`ProcessEngine.advance` 按 `session.process_type` 取 stage graph，
于是跑的是 `technical_plan` 的 handler：

- `_h_route`（`builtin_processes.py:109`）直接 `engine.deps.router.route(session)`
- `_h_recall:122` / `_h_clarify:164` / `_h_merge:181` 同形

`SimpleNamespace` 上没有 `router` → `AttributeError`。engine 对 handler 内不可恢复异常的
处理是「经 transition 落 `fail`」，即**把这条无关的技术方案会话直接标成 FAILED**。
`aresume_after_gate_action` 的 try/except 根本看不到这个异常（engine 已自行吞成 fail
转移），REST 仍返回 2xx，用户与日志都察觉不到。

同一处缺陷的次级后果：`alock`（`blueprint_confirm_gate.py:534`）会把错误的
`produced_by_session_id` 写进新蓝图版本；`_afilter_dispatchable_repos`
（`blueprint_confirm_gate.py:216`）按错误 session_id 查 task，`pending_research` 判据恒空
→ `research_required` 边永远走不到（SC-4 在这种数据形态下静默断链）。

**Fix:**

```python
async def _aload_session(artifact_id: Any) -> Any:
    from delivery.models import ConvergenceSession

    return await (
        ConvergenceSession.objects.filter(
            current_artifact_version__artifact_id=artifact_id,
            process_type="technical_blueprint",   # 唯一正确的会话来源
        )
        .order_by("-created_at")
        .afirst()
    )
```

并在 `blueprint_resume.adrive_blueprint_session_to_pause_or_terminal` 入口加一道守卫
（防其它调用方再犯）：

```python
if str(getattr(session, "process_type", "")) != "technical_blueprint":
    logger.warning("blueprint_resume_wrong_process_type", ...)
    return session      # no-op，绝不用蓝图 engine 驱别的 process
```

补一条断言：同 artifact 上先建一条 `technical_plan` 会话再建蓝图会话，调 `remove-repo`
后断言 `technical_plan` 会话 `status` 未变（现实现会红成 `failed`）。

---

### CR-02：规格门 fail-closed 有放行洞——LLM 持续不可用时第二轮直接放行，且 `capped=False` 不留旁路痕

**File:** `server/services/process_runtime/blueprint_spec_gate.py:202-243`
（配合 `:76-81` `_FALLBACK_QUESTION`、`:536-538` 指纹入集）

**Issue:**
`blueprint_spec_gate.py` 模块 docstring 写明不变量：「规格门是全链路唯一 fail-closed 点，
**唯一的放行例外是显式轮数上界，且必须在 `ambiguity_report.capped` 留痕（T-112-06）**」。
现实现存在第二条放行路径，且不留 capped 痕：

1. 第 1 轮 scorer 不可得 → `scorer_unavailable=True`，`scores["questions"]` 被替换成
   **常量** `_FALLBACK_QUESTION`（固定文案）→ 开阻塞线程挂起（正确）。
2. 用户作答 → 线程 `answered`，`_collect_prior_answers` 把该线程的问题正文逐行取指纹
   放进 `prior["fingerprints"]`（`:536-538`）。
3. 第 2 轮（`round_no=1 < 3`）scorer 仍不可得 → 又是同一条 `_FALLBACK_QUESTION`，
   `weighted_total` 恒 1.0、`above=True`；但 `:203-207` 的指纹过滤把它整条剔除
   → `questions == []` → 不进 `_open_clarification`，**直落 `:231` 的
   `_lock_spec(..., capped=False)` 放行**。

也就是说：LLM 持续不可用 + 用户答过一次通用问题，规格门就在
`weighted_total=1.0 ≥ threshold=0.20` 的情况下放行，`ambiguity_report.capped=False`。
下游（114 的 AI 审查、115 呈现面）无法从 `capped` 区分「按轮数上界放行」与
「因为问不出新问题而放行」。同一逻辑也适用于 LLM 可用但复述同一问题的情形：
`above=True` 却按「无新问题」等价成「无歧义」放行。

**Fix:** 「超阈值 + 无新问题」不是「不歧义」，必须与「按上界放行」同等留痕，且在
scorer 不可得时不得靠指纹过滤把唯一的兜底问题吃掉：

```python
if above:
    questions = [...]                       # 现有指纹过滤
    if questions:
        return await self._open_clarification(...)
    if scorer_unavailable:
        # 打分不可得时兜底问题恒为常量，指纹必然命中 → 不做过滤，保持挂起
        return await self._open_clarification(
            ..., questions=[dict(_FALLBACK_QUESTION)], ...
        )
    # 仍超阈值但确实问不出新问题 → 放行必须留痕
    released_without_questions = True
```

并把 `released_without_questions`（或复用 `capped=True`）落进
`_ambiguity_report`，让 `spec_locked` 事件与 `ambiguity_report` 都能回答
「这次放行走的是哪条例外」。补一条断言：scorer 恒 `None` + 已答一条兜底线程 →
第 2 轮 `event == "needs_clarification"`（现实现会红成 `spec_locked`）。

---

## Warnings（MAJOR）

### MJ-01：`add_repo` 的 `repository_id` 不做范围校验，任意登录用户可把全库任意仓挂进任意蓝图并触发容器与章程写入

**File:** `server/delivery/services/blueprint_lifecycle_service.py:889-897`、
`:1129-1136`（`_lookup_gate_repository`）

**Issue:** `_lookup_gate_repository` 只做 `Repository.objects.filter(id=...).first()`，
**不校验该仓是否属于本蓝图的范围**。同一相位的路由侧却是收窄的：
`blueprint_route._resolve_repository_ids`（`blueprint_route.py:844-873`）明确按
`work_item.space.repositories` 限定候选范围。两处口径不一致，`add_repo` 成了绕过范围的口子。

后果链（全部已端到端接通，因此不是理论问题）：
`add_repo(任意 repository_id)` → 快照 `pending_research=True` + `RepoResearchTask` PENDING
→ 续驱 `_h_bp_repo_research` → `_dispatch_deep_task` 用 `aresolve_git_token(repo)`
拿该仓 git 凭证起容器 clone 并读代码（`blueprint_research_adapter.py:502-512`）
→ `confirm` 时 `_asubmit_charter_drafts` → `asubmit_charter_draft` 往**该仓**章程写
`owned_domains` 草案（`source=ai_draft` 分支是正式字段就地更新，不是 draft_content）。

八个端点全部只有 `IsAuthenticated`（与 delivery 既有 view 同级，属既有约定，不单独计为
缺陷），但「URL 里的 artifact 与 body 里的 repository_id 完全解耦」是本相位新引入的范围
缺口。

**Fix:** 在 `_apply_gate_snapshot_sync` 的 `add_repo` 分支加范围白名单（与路由同源）：

```python
if action == "add_repo":
    repo = _lookup_gate_repository(repository_id)
    if repo is None or not _in_blueprint_scope(session, repository_id):
        return _gate_outcome(GATE_ERROR_REPOSITORY_NOT_FOUND)
```

`_in_blueprint_scope` 复用 `work_item.space.repositories` 的 id 集合（无 work_item 时退化
为「必须已在 `stage_state["routing"].candidates` 内」），越界统一回 404 中性消息。

---

### MJ-02：派发次数上界是死代码——`attempt` 在蓝图链里永不自增，容器可被无上限重开

**File:** `server/services/process_runtime/blueprint_research_adapter.py:60-63`、
`:177-183`

**Issue:** adapter 声明「自实现重试上界」并在派发前判
`int(getattr(task, "attempt", 0)) >= _MAX_ATTEMPTS`（=2）。但蓝图链里**没有任何一处给
`attempt` 加过 1**：

- `research_service.create_tasks_for_session` → `attempt: 0`（`research_service.py:66`）
- `mark_running` / `mark_failed` / `record_partial` / `mark_stale` 的 `update_fields`
  都不含 `attempt`
- 唯一 `attempt=F("attempt")+1` 在 `retry_task`（`research_service.py:162`），而本相位
  **明确禁止复用它**（它硬编码断言 stage 名为 `"research"`）

所以 `attempt` 恒为 0，`:177` 的分支恒为假，`"max_attempts_exhausted"` 是不可达代码。
真实后果不只是死代码：`upgrade-research` / `reclassify_role(indirect→direct)` /
`edit_responsibility({"rerun": true})` 每调一次都会 `mark_stale` → `dispatch` 起一个新的
30 分钟调研容器，**没有任何次数上界**。`MAX_REROUTE_ROUNDS=2` 只约束自动重路由，
约束不到人工动作路径。这与 T-112-19「无界重路由本身也是烧容器额度的 DoS 面」的立意冲突。

**Fix:** 让上界真的可触发——在把 task 置回可派发态的那一步自增 `attempt`（新增一个
`ResearchService` 公开方法，或在 adapter 侧经 `stage_state` 记逐仓派发计数）：

```python
# research_service.py（新增公开方法，不改 retry_task 语义）
@sync_to_async
def _bump_attempt_sync(self, task_id) -> int:
    return RepoResearchTask.objects.filter(id=task_id).update(
        attempt=F("attempt") + 1, updated_at=timezone.now()
    )
```

在 `_dispatch_deep_task` 成功派发后调用它，并补一条断言：同一仓连续三次
`upgrade-research` 后 `dispatcher.await_count == 2`（现实现是 3）。

---

### MJ-03：`confirm` 与 `add_repo` 并发时用户动作静默丢失，并留下永不派发的孤儿 task

**File:** `server/services/process_runtime/blueprint_confirm_gate.py:500-552`
（`alock`），对照 `blueprint_lifecycle_service.py:874-950`

**Issue:** 动作侧 `_apply_gate_snapshot_sync` 用 `select_for_update` 保护「读-改-写单条
线程行」，但 `alock` 走的是完全另一条路径：`:500` `_aload_active_gate_thread`（无锁）→
`:511` `iter_snapshot_repos(thread.options)` → `:531` `add_version` → `:548`
`resolve_thread`。两者之间没有任何互斥或版本校验。

`confirm` 与 `add_repo` 交错时（用户双击、或前端并发、或两人同时操作）：

1. `confirm` 读到快照 v1（不含新仓）
2. `add_repo` 提交：快照变 v2（含新仓 + `pending_research=True`），`RepoResearchTask` 落
   PENDING，REST 回 200
3. `confirm` 用 v1 落 `repo_associations`（新仓不在里面），并 `resolve_thread` 关门

此后 `_acollect_thread_marked_repos`（`blueprint_confirm_gate.py:184-193`）只查
`OPEN/ANSWERED` 线程，已 `RESOLVED` 的线程里的 `pending_research` 标记再也读不到 →
`acollect_pending_research_repos` 恒空 → `research_required` 边不会被触发 → 那个 PENDING
task 成为孤儿（既不派发也不终态），而用户拿到的是 `add_repo` 的 200。
用户的加仓动作**静默丢失**，且蓝图锁定结果与用户最后一次操作不一致。

**Fix:** 让锁定与动作走同一把锁 + 加一道锁前重查：

```python
# alock：把线程行读进同一事务并加锁（与 _apply_gate_snapshot_sync 同源）
row = await self._aload_and_lock_gate_thread(artifact.id)   # select_for_update
...
# 锁定前重查待调研仓，非空则拒绝锁定，让用户先等新仓调研完
pending = await acollect_pending_research_repos(session)
if pending:
    return self._result("awaiting_confirmation", str(thread.id), None, 0)
```

视图侧把这种情况映射成 409（「有仓正在调研，暂不能确认」）。补一条断言：
`add_repo` 成功后紧接 `confirm`，断言 `confirm` 回 409 或锁定集合包含新仓——两者任一，
但绝不能是「200 且新仓消失」。

---

### MJ-04：self-loop 转移让 CAS 失效，`stage_state` 存在并发覆盖（与 `blueprint_resume` 的并发声明不符）

**File:** `server/services/process_runtime/blueprint_resume.py:24-30`（并发声明）、
`server/services/process_runtime/blueprint_research_adapter.py:833-907`
（`aadvance_reroute` 整字典回写）

**Issue:** `blueprint_resume` docstring 声明「同一会话并发续驱由
`_apply_transition_sync` 的 CAS 去重（`filter(id, current_stage=from_stage).update()`；
`updated != 1` → `ConcurrentTransitionError`），败者那步 advance 是 no-op」。
这个声明对 self-loop 不成立：

`engine.advance`（`engine.py:104-105`）先算
`merged_state = {**(session.stage_state or {}), **outcome.stage_state_update}`，
再 CAS `filter(id=..., current_stage=from_stage).update(stage_state=merged_state, ...)`。
而蓝图三个 pausable stage 的挂起边全是 **self-loop**（`spec_gate→spec_gate`、
`repo_research→repo_research`、`repo_confirmation→repo_confirmation`），此时
`new_stage == from_stage`，CAS 条件对**两个**并发写者都成立 → 两者都 `updated == 1`
→ 后写者的 `stage_state` 整份覆盖先写者。

具体损失面：两个确认门动作端点并发续驱时，`_h_bp_repo_confirmation` 各自写
`{"confirmation": state}`；`aadvance_reroute` 更严重——它按 `{**state, ...}` 整字典浅
合并回写（`:885-906`），一旦与另一路续驱交错，`routing.candidates` 的追加、
`reroute.excluded` 的累积、`escalation` 都可能被回退到读取时的旧值，
即 GAP-1 闭环刚建立的「排除集永久累积」性质在并发下会破。

**Fix:** stage_state 的写入需要自己的乐观锁，不能借 `current_stage` 的 CAS：

- 最小：给 `ConvergenceSession` 的 stage_state 写入加 `updated_at` 条件
  （`filter(id=..., current_stage=from_stage, updated_at=<读到的值>)`），
  `updated != 1` 时重读重算一次（`aadvance_reroute` 已有 `_areload_session`，重试成本低）；
- 或：把 `reroute` / `confirmation` 两个键改成「只读增量键」，用
  `JSONField` 的原子路径更新（PostgreSQL `jsonb_set`）而不是整字典替换。

补一条断言：两个并发 `aresume_after_gate_action` 之后，`stage_state` 同时保留两次动作的
`confirmation` 与 `reroute.excluded`（现实现会丢一份）。

---

### MJ-05：禁区保留理由被路由器的能力树 `reasoning` 顶替，「LLM 必须给显式理由」只在形式上成立

**File:** `server/services/process_runtime/blueprint_route.py:215-223`
（`resolve_boundary_override`）、`:739-748`（`_apply_boundary_overrides`）

**Issue:** CONTEXT 锁定决策：「命中禁区仍保留候选时 **LLM 必须给显式理由**」。
现实现的优先级是「① 路由器原样 `reasoning` → ② sanity-check LLM → ③ 打
`unjustified_boundary_hit`」。而 `RepoRouterV2` 的 `reasoning` 是**能力树命中说明**
（docstring 自己写的例子：`"命中能力节点: ..."`），与「为什么明令不承接却还留着」
毫无关系，且对路由器召回的候选**恒非空**。

于是：
- `pending`（`:739-747`，只挑 `reasoning` 空白的候选）在正常路径上恒为空 →
  `_aexplain_boundary_overrides` 几乎永不被调用，那套 sanity-check LLM 是死路径；
- `unjustified_boundary_hit` 几乎永远为 `False`，`unjustified_boundary_hit_count` 恒 0；
- 验收断言 `boundary_override_reason` 与 `unjustified_boundary_hit`「恰有其一」
  （112-VERIFICATION Truth #2）在**形式上**为真，语义上却是「用一段无关文本冒充理由」。

**Fix:** 禁区保留理由只认针对禁区的判断，不认通用路由说明：

```python
def resolve_boundary_override(*, violated_boundaries, llm_reason="",
                              router_reasoning="") -> tuple[str, bool]:
    if not violated_boundaries:
        return "", False
    reason = str(llm_reason or "").strip()      # ① sanity-check LLM 优先
    if reason:
        return reason[:_MAX_REASON_CHARS], False
    return "", True                            # ② 拿不到就如实打标记
```

`_apply_boundary_overrides` 的 `pending` 改为**全部**禁区命中候选（不再按 reasoning
是否为空筛），`router_reasoning` 仅作展示字段留在 evidence 里。补一条断言：
路由器返回非空 reasoning 的禁区候选，在 sanity-check LLM 不可用时
`unjustified_boundary_hit is True`（现实现为 False）。

---

### MJ-06：CJK 单个 3-gram 交集即判禁区命中（-1.0），假阳性可直接抹平满分 owned

**File:** `server/services/process_runtime/blueprint_charter_match.py:112-141`
（`_matches`），配合 `:45-51` `boundary_hit = -1.0`

**Issue:** `_matches` 的第四条判定是
`if target_tokens & _tokens(term): return True`——**一个** 3-gram 重合即判命中，
没有数量或覆盖率阈值。而中文长句里的通用 3-gram（`服务端`、`数据库`、`相关功`、
`权益鉴`、`的配置` 等）在「章程禁区整句」与「需求正文整句」之间偶然重合的概率并不低，
`_MIN_SEGMENT_LEN = 2` 又让 2 字片段参与子串判定（第二条判定），进一步放大。

命中后果是重的，不是「略降权」：
- `boundary_hit = -1.0`，注释自陈「单条禁区命中即可把满分 owned 命中压回 0」；
- 同时把该候选送进 `_apply_boundary_overrides`，产 `boundary_override_reason` /
  `unjustified_boundary_hit`，污染确认门快照的 `violated_boundaries` 与
  115 呈现面的「命中章程禁区」；
- 每条命中都 `negative += -1.0` 累加（`:221`），多条假阳性叠加后 `score` 恒到
  下界 `-1.0`。

112-03-SUMMARY 把 3-gram 记为「加固」（补了中文整句下禁区降权的可用性），方向没错，
但缺了假阳性侧的护栏——这正是 VERIFICATION 未覆盖的一面（它只验了「能命中」，
没验「不该命中时不命中」）。

**Fix:** 给 token 交集判定加强度阈值，并把命中方式写进证据供人复核：

```python
_MIN_NGRAM_OVERLAP = 2      # 单个通用 3-gram 不足以判命中

overlap = target_tokens & _tokens(term)
if len(overlap) >= _MIN_NGRAM_OVERLAP:
    return True
```

（或用覆盖率：`len(overlap) / max(1, len(target_tokens)) >= 0.3`。）
并让 `CharterMatchResult` 多带一个 `match_kind`（`substring` / `ngram`），
写进 breakdown evidence。补两条断言：① 禁区「不承接课程权益鉴权」vs 需求
「展示课程内容与权益鉴权状态」仍判命中（保回归）；② 禁区「不承接支付相关功能」vs
需求「新增导出相关功能」**不**判命中（现实现会红）。

---

### MJ-07：章程回灌把整段职责当 `owned_domains.domain` 写入，与 `_matches` 的子串语义叠加成自我强化的假阳性

**File:** `server/services/process_runtime/blueprint_confirm_gate.py:884-905`
（`_build_charter_draft`）

**Issue:** `_build_charter_draft` 在非 removed 分支产出
`{"owned_domains": [{"domain": responsibility[:200], "status": ...}]}`——把**一整段职责
描述**（上限 200 字）当作 `domain` 字段值。`domain` 在 `score_charter_match` 里是被
`_matches(domain, terms)` 拿去做子串 / 3-gram 匹配的**领域名**。

叠加效应：
- `asubmit_charter_draft` 对 `source=ai_draft` 的章程是**正式字段就地更新**
  （`charter_draft_writeback.py:190-194`，不是只写 `draft_content`），所以这条 200 字
  「domain」立刻对后续路由生效，不需要人工 confirm；
- 200 字的 domain 与任意需求正文之间几乎必然有 3-gram 交集（见 MJ-06）→ 该仓
  `owned_implemented = 1.0` 近乎恒命中 → 一次确认门操作就把这个仓变成「什么需求都归我」；
- `_merge_list` 按 `domain` 去重，每次确认门职责措辞略有不同就追加一条新「domain」，
  章程会持续膨胀。

**Fix:** `domain` 必须是短领域名，不能是职责正文：

```python
_MAX_DOMAIN_CHARS = 40

return {
    "owned_domains": [
        {
            "domain": _extract_domain_name(entry) [:_MAX_DOMAIN_CHARS],  # 仓名/领域名，非职责正文
            "status": "implemented" if role == "direct" else "planned",
            "note": responsibility[:500],        # 职责正文落 note，不参与匹配
            "citations": [],
        }
    ]
}
```

`_extract_domain_name` 取快照里已有的 `routing_evidence.matched_domains` 首项，
取不到则**不产 owned_domains 草案**（返回 `{}`）——宁可不回灌，也不写一条会污染路由的
领域。并在 `charter_draft_writeback` 侧对 `owned_domains[].domain` 加长度上界兜底。
补一条断言：确认一个 200 字职责后重跑路由，该仓对**无关**需求的 `charter_match` 仍为 0。

---

## Info（MINOR）

### MN-01：`rejected-to-boundary` 的项目范围完全由请求体决定，URL 里的 artifact 只做存在性检查

**File:** `server/delivery/api/blueprint_gate_views.py:346-398`、`:485-502`

**Issue:** `project_id = body["project_id"] or 蓝图 meta.project_id`——body 优先。
`artifact_id` 只用于 `_aload_artifact` 存在性检查，不约束写入范围；
`repository_id` 同样直接透传进 `_aload_rejected_reasons` 的 filter。任意登录用户可用
任意合法 artifact_id + 任意 project_id 批量往别的项目的仓写 `boundaries` 草案
（上限 200 条候选）。与 MJ-01 同源，但影响面只到章程草案，故计 MINOR。

**Fix:** `project_id` 只从蓝图 `meta.project_id` 推导；body 若传了就必须与之相等，
否则 403；`repository_id` 必须落在该 project 的仓集合内。

### MN-02：阻塞线程判据读失败一律 fail-open（返回 False，放行 advance）

**File:** `server/services/process_runtime/blueprint_resume.py:199-202`

**Issue:** `_ahas_open_blocking_blueprint_threads` 的 `except` 返回 `False`，注释
「判据读失败按『无阻塞线程』放行（宁可多推一步）」。这与规格门/确认门的 fail-closed
方向相反：DB 抖动时会把「有未决澄清线程」误判成无门而放行一步 advance。虽然
`_h_bp_spec_gate` / `open_gate` 内还有各自的 pending 门二次兜底（同一次故障下它们也会
抛，最终由 engine 落 fail），但方向性错误值得纠正。

**Fix:** 判据读失败按 `True`（保持挂起）处理——挂起可由下一次触发恢复，误放行不可逆。

### MN-03：`aupgrade_to_deep` 对在途 task 返回 `True`，端点回 200 但实际 no-op

**File:** `server/services/process_runtime/blueprint_research_adapter.py:742-760`

**Issue:** `mark_stale` 按 WR-01 只动已终态 task，对 `RUNNING` task 返回 0；随后
`dispatch` 的 `_DISPATCHABLE_STATUSES` 白名单也跳过它。此时 `aupgrade_to_deep`
仍无条件 `return True` → 端点回 200 / `upgraded=True`，用户以为已重开深调研，
实际什么都没发生（`result.get("dispatched")` 为 0 也没被用来判定）。

**Fix:** 区分三种语义：已派发（200）/ 在途无需重开（200 + 显式
`already_running=True`）/ 不可用（503）。

### MN-04：容器失败的上游 error 文本未截断即落 `ConvergenceSessionEvent.payload`

**File:** `server/subagent/api/callbacks.py`（`_handle_blueprint_research_failure`，
`error_msg = redact_secrets_in_text(str(p.get("error", ...)))` 直接进 payload）

**Issue:** `event_taxonomy.py` 对该事件的注释是「payload:
repository_id/attempt/error_kind（异常文本已脱敏**截断**）」，adapter 侧
`_emit_failed`（`blueprint_research_adapter.py:1047-1056`）也只落 `reason` 枚举值。
回调侧却把任意长度的容器 error 原文（仅脱敏）落进 payload，口径不一致，
且 `redact_secrets_in_text` 只覆盖已知凭证形态，长文本入库放大了残留泄漏面。

**Fix:** `error_msg[:500]`，并把 `error_kind`（枚举）与 `error_detail`（截断文本）分开。

### MN-05：事件 emit 通道四处不一，三处直调私有 `_emit_event`、一处裸建 ORM 行

**File:** `blueprint_route.py:838`、`blueprint_confirm_gate.py:752`、
`blueprint_research_adapter.py:1061`（均 `ConvergenceSessionService()._emit_event`）、
`blueprint_lifecycle_service.py:987`（`ConvergenceSessionEvent.objects.acreate` 裸建）

**Issue:** 同一相位内四种写法写同一张表。私有方法被跨模块调用（下划线前缀契约被打破），
裸建那处还自己拼 `work_item=getattr(session, "work_item_id", None)`——依赖
`work_item` 恰好是软 UUID 字段（现状确实是 `UUIDField`），一旦该字段将来改成真 FK，
这处会静默 warning 后丢事件。后续给蓝图事件统一加字段（如 `initiated_by_user_id`）要改四处。

**Fix:** 在 `ConvergenceSessionService` 上开一个公开 `aemit_event(event, session, payload)`
（内部转调现有实现），四处统一走它。

### MN-06：`aget_float_setting` 无生产调用方（死代码）

**File:** `server/system/settings_service.py:124-136`

**Issue:** 全仓只有 `tests/test_blueprint_settings.py` 引用它；
`aload_spec_gate_config` 走的是 `aget_json_setting`。docstring 自陈用途是
「blueprint.spec_gate.config 的 threshold 兜底路径」，该路径并不存在。

**Fix:** 删除，或让 `aload_spec_gate_config` 在 JSON 键缺失时真的用它读一个独立的
`blueprint.spec_gate.threshold` 标量键。

### MN-07：`builtin_processes.py` 模块中段 import 重型 adapter，且导出的常量无消费方

**File:** `server/services/process_runtime/builtin_processes.py`
（`from ... blueprint_research_adapter import MAX_REROUTE_ROUNDS as _MAX_REROUTE_ROUNDS`
+ `MAX_BLUEPRINT_REROUTE_ROUNDS = _MAX_REROUTE_ROUNDS`）

**Issue:** 为「不复制一个数字」把 `blueprint_research_adapter`（连带
`delivery.services` / `delivery.models`）拉进 process 注册的 import 期，
这是循环 import 的潜在触发点；且 `MAX_BLUEPRINT_REROUTE_ROUNDS` 全仓无任何消费方
（含测试），属只导出不使用。`# noqa: E402` 是为守「纯追加」纪律而付的代价。

**Fix:** 常量下沉到轻量模块（如 `process_runtime/constants.py` 或 `registry`），
`builtin_processes` 与 `blueprint_research_adapter` 都从那里读；删掉无消费方的
`MAX_BLUEPRINT_REROUTE_ROUNDS`。

---

## 纪律复核：冻结面（`git diff 94479721..HEAD`）

**结论：通过。** 以下 10 个文件 diff 为空：

| 文件 | diff |
|------|------|
| `codegraph/services/repo_router_v2.py` | 空 |
| `services/process_runtime/resume.py` | 空 |
| `services/process_runtime/research_adapter.py` | 空 |
| `services/process_runtime/decompose_segments.py` | 空 |
| `services/process_runtime/architect_merge_adapter.py` | 空 |
| `services/process_runtime/merged_plan.py` | 空 |
| `services/process_runtime/clarify_adapter.py` | 空 |
| `services/process_runtime/render.py` | 空 |
| `repositories/services/charter_service.py` | 空 |
| `agents/call_source.py` | 空（4 个蓝图 `call_source` 值均为 Phase 111 既有枚举） |

- `builtin_processes.py` 的 `_TECHNICAL_PLAN_STAGES` / `_ECHO_STAGES` / 既有两次
  `register_process_type`：**零改动**（diff 里只作为上下文行出现）；新增部分是 7 个
  `_h_bp_*` handler + 1 张 stage 表 + 第三次注册。
- `ConvergenceSessionEvent` 模型未改动；新增的 11 个事件常量全在
  `BLUEPRINT_EVENTS` 内，未污染 `ALL_EVENTS`。
- `settings_service.py` 删除行 0（既有 8 个 getter 逐字未动），只追加两个 async getter。
- **摩擦项（不计缺陷，与 VERIFICATION Anti-Pattern #3 同一处）**：
  `system/models.py`（11 行）与 `artifact_serializers.py`（6 行）的删除行经逐行核对全部为
  `ruff format` 换行重排（`LOG_RETENTION_SIZE` / `ALERT_*` 常量、`JSONField(...)` 参数
  换行），键名/键值/行为零变更；`callbacks.py` +301/-0 已按同一问题手工守住纯追加。
  建议后续 plan 统一「只对新增段跑 format」。

## 观测与 INV-6 复核（本次未发现缺陷）

- `category` / `component` 齐备；LLM 调用点三处均用已注册枚举
  （`BLUEPRINT_SPEC_GATE` / `BLUEPRINT_DECOMPOSE` / `BLUEPRINT_REROUTE`），
  容器链 `_derive_container_call_source` 补了 `BLUEPRINT_REPO_RESEARCH`。
  唯一口径瑕疵：禁区解释复用 `BLUEPRINT_REROUTE` 且用
  `reason_kind="boundary_override"` 区分——已在代码注释里说明理由（不新增枚举值属
  冻结面约束），可接受。
- 明文 token 只进 `dispatch metadata`；日志只记 `has_user_token` 布尔
  （`blueprint_research_adapter.py:449`）；`rg friday_pat_` 在新增源文件零命中；
  dispatch 失败主动 `arevoke_task_tokens`。TTL = 30min + 10min 余量，
  与编码链一致。**未发现 token 泄漏面。**
- `BlueprintThread` / `BlueprintThreadMessage` 的写入全部经
  `BlueprintLifecycleService`；`RepoResearchTask` / `PartialPlan` 全部经
  `ResearchService`；adapter 与视图零 ORM 写（读路径直查）。**INV-6 收口成立。**
- prompt 注入面：章程正文与需求正文都取自服务端权威状态并逐节截断，
  LLM 输出侧全部按 `repository_id` / `feature_point id` 白名单过滤 + 枚举校验 + 截断，
  未发现「LLM 输出直接落库/直接决定放行」的路径（`_parse_blueprint_fitness` 缺
  `verdict` 即判失败是正确的方向）。

---

_Reviewed: 2026-07-30_
_Reviewer: gsd-code-reviewer（deep，跨文件调用链追踪 + 冻结面 git diff 复核）_
