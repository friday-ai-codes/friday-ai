---
phase: 112-1
plan: 05
subsystem: process_runtime / delivery API —— 阶段 1 出口确认门与编排面接通
requirements: [FLOW-03, CHARTER-03]
provides:
  - "确认门快照契约（`BlueprintThread(kind=repo_confirmation, blocking=True).options` 为**唯一权威载体**）：逐仓 `{repository_id, repository_name, role_suggestion, responsibility, confidence, fitness{verdict,reasons,citations}, current_state_summary, routing_evidence{total,router_base,charter_match,history_match,router_version,confidence,matched_domains,violated_boundaries,history_match_unavailable}, task_status, pending_research, removed, actions[]}`"
  - "`stage_state[\"confirmation\"]` 落盘形状 `{thread_id, thread_status, repos: [<上述条目>]}`（112-04 的增量 dispatch 唯一读取面；由 `_h_bp_repo_confirmation` 每次经 transition 刷新）"
  - "8 个 REST 端点（`/api/delivery/artifacts/<uuid:artifact_id>/blueprint-gate/...`）：`GET ''`（只读快照）+ `confirm/` / `remove-repo/` / `add-repo/` / `reclassify-role/` / `edit-responsibility/` / `rejected-to-boundary/` / `upgrade-research/`，全部 `IsAuthenticated`、视图零 ORM 写"
  - "`BlueprintLifecycleService.apply_gate_action(artifact, *, thread, action, payload, acting_user, initiated_by_user_id, session=None) -> {requires_research, repository_id, thread_id, ready_to_lock, blocked_reason}`（形状恒定五键）"
  - "`BlueprintLifecycleService.aupgrade_repo_research(artifact, *, repository_id, acting_user, initiated_by_user_id, session=None) -> {upgraded, repository_id}`"
  - "`BlueprintLifecycleService.aload_gate_thread(artifact) -> BlueprintThread | None`（open/answered 确认门线程定位，视图与 adapter 共用）"
  - "五动作 → 重调研确定规则表 + `pending_research` 标记语义：`add_repo` 恒重调研（`create_tasks_for_session` 落 PENDING）；`remove_repo` 恒否；`reclassify_role` 仅 `indirect→direct`（`mark_stale`）；`edit_responsibility` 仅 `payload[\"rerun\"] is True`（`mark_stale`）；`confirm` 走锁定路径。**标记无需清位**——判据是「标记 ∧ task ∈ {pending, stale}」的合取"
  - "`blueprint_confirm_gate.acollect_pending_research_repos(session) -> list[str]`：待调研判据**唯一实现**，标记来源 = `stage_state[\"confirmation\"]` ∪ **活跃确认门线程 options** 的并集（动作端点只写线程行，stage_state 要等下一次 transition）"
  - "`blueprint_confirm_gate.acollect_confirmation_state(session) -> dict | None`：从活跃线程重建 stage_state 落盘值（handler 在 research_required 分支刷新用）"
  - "`blueprint_confirm_gate.build_locked_associations(*, snapshot, decisions=None, citation_pool=None) -> list[dict]` 纯函数：`decided_by=\"human\"` / `confirmed_at_gate=True` / `responsibility` 落 block_list；removed 仓不进；`fitness.citations` 按引用池白名单过滤"
  - "`BlueprintConfirmGateAdapter.open_gate(session) -> {event ∈ awaiting_confirmation|confirmed, thread_id, stage_state, repo_count}` 与 `alock(session, *, acting_user=None, decisions=None) -> 同形`"
  - "`charter_draft_writeback.asubmit_charter_draft(repository_id, draft, *, initiated_by_user_id=\"system\", merge=True) -> RepoCharter | None`：复用 `charter_service.normalize_charter_draft` 归一 + 与 `adraft_charter` 等价的三分支落库；`merge=True` 按 `domain`/`rule`/`(kind,target)` 去重追加"
  - "`technical_blueprint` stage graph（七 stage）：`intake→decompose→spec_gate(pausable/waiting_clarification)→route→repo_research(pausable/waiting_event)→reroute→repo_confirmation(pausable/waiting_clarification)`；`reroute.exhausted → repo_confirmation`（不落 failed）；`repo_confirmation.research_required → repo_research` 回边；`repo_confirmation.confirmed → __done__`"
  - "**113 接续点**：把 `repo_confirmation.transitions[\"confirmed\"]` 改为 `\"repo_plan\"` 并追加两个 StageDef 即可（transitions 是数据，无需改 engine）"
  - "`blueprint_resume.adrive_blueprint_session_to_pause_or_terminal(engine, session, *, max_steps=20)`：pause 判据合取式 = `waiting_clarification` ∧ 有 open+blocking `BlueprintThread` ∧ `acollect_pending_research_repos(session)` **为空** → 短路；有待调研仓则**放行 advance**"
  - "`blueprint_resume.aresume_after_gate_action(session, *, initiated_by_user_id, engine=None)`：六个动作端点的续驱入口（confirm 在 alock 之后）；整段 try/except 全兜，失败只记 `blueprint_gate_resume_failed` 并返回传入 session，动作 REST 仍 2xx；并发靠 `_apply_transition_sync` 的 CAS、容器不重开靠 `_DISPATCHABLE_STATUSES` + `get_or_create`、死循环靠 `max_steps`——**零新造锁/字段/status**"
  - "`blueprint_resume.aresume_blueprint_session(session, *, engine=None)`：112-04 调研 fan-out barrier 的接线契约（函数名即契约，已自动接通）"
  - "`entrypoint.build_blueprint_engine(*, session_service=None, node_execution_id=\"\")`：deps 属性名单 = `{spec_gate, route, research, confirm_gate}`（与七个 `_h_bp_*` handler 的 getattr 取名逐字一致，有等价性断言）"
affects:
  - "113（repo_plan）：确认门锁定的 `repo_associations`（`confirmed_at_gate`/`decided_by=human`/`responsibility`）与 `decision_log` 是分仓方案的输入面；接续只需改一个 transitions 值 + 追加 StageDef"
  - "114（AI 审查）：`confirmed_at_gate=true` 的仓库集若在后续阶段被改动，须重开确认门 —— 审查据此判 BLOCKER"
  - "115（前端）：8 个端点即确认门数据面；`blueprint.confirmation.opened|action|locked` 三事件 payload 在此定型（只含计数与关联键）"
  - "116（入口收编）：`build_blueprint_engine` + `start_orchestration` 形态的蓝图会话创建是入口切换的接线点"
tech-stack:
  added: []
  patterns:
    - "确认门快照的**唯一权威载体是线程行**，stage_state 是它的投影（每次 transition 刷新）——动作端点只写线程即可让判据立刻成立，不需要在 REST 路径上写 session"
    - "判据单一实现 + 双消费方（handler 决定出边 / resume 决定放行），两处漂移即链路断裂"
    - "「留痕消息」与「作答」分离：确认门动作只追加消息（`_arecord_gate_note`），**绝不把线程推到 answered**——否则 `ahas_open_blocking_threads`（只认 open）会判为无门并重开第二条"
    - "错误码枚举 + 视图侧状态码映射（service 抛 `ValueError(<code>)`，视图按 `GATE_NOT_FOUND_ERRORS` 分层 404/400），避免为分层新造异常类"
    - "受限文件纯追加纪律：新常量/新 `__all__` 项用 `__all__ += [...]` 追加语句，不改既有 `__all__` 行；跨模块常量复用用中段 import + `# noqa: E402`"
key-files:
  created:
    - server/services/process_runtime/blueprint_confirm_gate.py
    - server/services/process_runtime/blueprint_resume.py
    - server/repositories/services/charter_draft_writeback.py
    - server/delivery/api/blueprint_gate_views.py
    - server/tests/services/process_runtime/test_blueprint_confirm_gate.py
    - server/tests/services/process_runtime/test_blueprint_process_graph.py
    - server/tests/delivery/test_blueprint_gate_api.py
    - server/tests/repositories/test_charter_draft_writeback.py
  modified:
    - server/delivery/services/blueprint_lifecycle_service.py
    - server/services/process_runtime/builtin_processes.py
    - server/services/process_runtime/entrypoint.py
    - server/delivery/api/artifact_serializers.py
    - server/delivery/urls.py
    - server/tests/repositories/test_charter_service.py
    - server/tests/subagent/test_blueprint_research_callback.py
    - server/tests/test_model_usage_call_source.py
decisions:
  - "确认门快照的权威载体定为线程 `options`，`stage_state[\"confirmation\"]` 只作投影：动作端点若要写 session 就得绕过 `transition`（旁路 CAS、埋 lost-update），而判据必须在动作返回前立刻成立"
  - "确认门动作用「只追加消息」而非 `record_answer`：后者把线程推到 `answered`，会让 pending 门失守并重开第二条确认门线程"
  - "`build_locked_associations` 增 `citation_pool` 白名单过滤：调研产出的 citations 是裸文件路径，直接落进蓝图会让后置检查 (a) 判整份非法 → 确认门永远锁不上"
  - "`alock` 的锁定基线取 artifact **最新**版本而非 session 钉住的那一版：规格门放行时已 `add_version` 推进 current_version，读 session 那一版会把规格门成果覆盖回去"
  - "handler 不再额外 emit 事件：四个蓝图 adapter 各自已 emit `blueprint.*`，engine 的 `transition` 也记一条，handler 再 emit 会把计数打成两倍"
  - "`aupgrade_repo_research` 的容器派发发生在 service 调用内（112-04 的 `aupgrade_to_deep` 自带带 `force_deep_repository_ids` 的 dispatch），因此该端点续驱后 stage 停在 `repo_confirmation` 而非 `repo_research` —— 断言落在「容器确实为且只为该仓起了」"
completed: 2026-07-30
---

# Phase 112-1 Plan 05: 确认门 + 七 stage 注册 + 续驱接通 Summary

**一行结论**：阶段 1 的出口硬门与整条流水线的编排面同时闭合——确认门以 `BlueprintThread(repo_confirmation, blocking)` 的 `options` 承载权威仓库清单快照，七个动作经 REST 收口 `BlueprintLifecycleService`（视图零 ORM 写、错误码分层 404/400/409/503），`confirm` 经 `alock` 把仓库集与职责写进 `repo_associations`（`confirmed_at_gate`/`decided_by=human`/`responsibility`）并记幂等 `decision_log`；`technical_blueprint` 七 stage 注册完成（`exhausted` 升确认门不落 failed、`repo_confirmation → repo_research` 有 `research_required` 回边），六个改状态端点在动作持久化后统一触发 `blueprint_resume.aresume_after_gate_action` 续驱，**SC-4 的证伪线是经 REST `add-repo` 真实入口的端到端断言**（session 落 `repo_research`、只为新仓起 1 个容器、A/B 两仓 task 与 `PartialPlan` 行数逐一不变），而非手工 `engine.advance`；`charter_service.py` 与七个冻结文件逐字未改。

## Accomplishments

- **确认门载体与快照（Task 1，FLOW-03）**：`open_gate` 六步（无版本 fail-closed → pending 门短路 → 已锁定判 `confirmed` → 组装快照 → 开阻塞线程 → emit）。快照来源是「112-03 路由候选 ∪ 112-04 `acollect_fitness` ∪ `escalation` 现状」的并集，正文类字段按「小摘要」纪律截断（职责 2000 / 现状 1000 / 列表 10 项）。pending 门实测：已有 open 门时再 `open_gate` → 线程数不增且 `fitness_loader.await_count == 0`。

- **锁定语义与 fail-closed（Task 1）**：`alock` 深拷贝 artifact **最新**版本 content → `build_locked_associations` 纯函数映射 → `decision_log` 按 `(thread_id, action, repository_id)` 去重追加 → `add_version`。`ArtifactContentInvalid` 被捕获后返回 `awaiting_confirmation`（实测版本数不增、异常不上抛）；章程草案**逐仓独立 try/except**（writer 抛异常时锁定仍成功且 `repo_associations` 已写入）。确认者经 111 的 `add_reviewer` upsert 进 `BlueprintReviewer`（`first_action="repo_confirmation"`）。锁定后的蓝图实测过 `validate_blueprint` 返回 `(True, None)`。

- **五动作单点收口与重调研规则表（Task 1，SC-4 前半）**：`apply_gate_action` 的 action 白名单在 service 层 `raise ValueError(<code>)`，返回形状恒定五键。规则表在**唯一 mutator** `_apply_gate_snapshot_sync` 内实现（`select_for_update` + `transaction.atomic` 整段读改写单条线程行）——`reclassify_role` 需要「改判前的角色」才能判定，必须同事务先读后写。`requires_research=True` 的动作**同时**做两件写入：快照打 `pending_research=True` + 经 `ResearchService` 公开方法把 task 落到可派发态（`add_repo` → `create_tasks_for_session` 落 PENDING；改判/rerun → `mark_stale` 落 STALE）。四条规则各有参数化断言（含 `direct→indirect` 与同角色改判**不**触发、`edit_responsibility` 默认**不**触发）。

- **待调研判据的单一实现（Task 1 ①b）**：`acollect_pending_research_repos` 被 `_h_bp_repo_confirmation`（决定 `research_required` 出边）与 `blueprint_resume`（决定是否放行一步 advance）**同一份**复用。判据是合取「标记 ∧ task ∈ {pending, stale}」，故标记**无需清位**：task 一旦被 dispatch 推到 `running` 判据自然为假（有专项断言）。标记来源取 `stage_state` ∪ **活跃线程 options** 的并集——只读 `stage_state` 会让紧随动作的那次续驱判据为空（有 `test_pending_probe_reads_live_thread_snapshot` 专门锁死这条）。

- **八个端点与状态码分层（Task 2）**：一动作一 View、`IsAuthenticated` 逐个声明、重依赖方法体内 lazy import、serializer `.data` 一律 `sync_to_async`。分层：未认证 401/403；artifact/门/仓不存在 404；非法 role / 缺 `repository_id` / 无法确定项目范围 400；未决阻塞澄清线程或内容校验未过 409；依赖不可用 503。`rejected-to-boundary` 的范围解析优先 body 的 `project_id`、缺省取蓝图 `meta.project_id`，两者都不是合法 UUID 时必须显式给 `repository_id`（**绝不跨项目全表沉淀**）。

- **章程回灌只产 ai_draft（Task 2，CHARTER-03）**：新文件 `charter_draft_writeback` 归一逐字复用 `charter_service.normalize_charter_draft`（畸形输入的归一结果与直接调用该函数**逐字相等**的对照断言），三分支落库与 `adraft_charter` 行为等价（无 charter → 建行 v1；`ai_draft` → 就地更新且 version 不变；`human_confirmed` → **只写 `draft_content`**，正式四字段逐字段与写入前完全相等）。`merge=True` 按 key 去重追加（同 domain/同 rule 重复提交不堆积）。`git diff --stat repositories/services/charter_service.py` 输出为空。

- **续驱有生产调用方（Task 2 ⓐ + Task 3 ②）**：`rg -c "aresume_after_gate_action" blueprint_gate_views.py` **等于 6**（六个改状态端点各一处；只读快照与 rejected 沉淀不接，源码注释写明理由）。失败隔离在 helper 内：真链路测试把**内层 driver** 换成抛异常的替身（桩掉外层入口会连它的 try/except 一起替掉，那测的是「视图有没有自己包 try」而非契约），断言五个动作端点仍 2xx 且动作结果已持久化。

- **七 stage 注册（Task 3）**：`builtin_processes.py` 纯追加 7 个 `_h_bp_*` handler + `_TECHNICAL_BLUEPRINT_STAGES` + 第三次 `register_process_type`（docstring 计数一行除外，`git diff | rg "^-"` 为空）。`_h_bp_route` 是 `stage_state["routing"]` 的唯一写入方，adapter 缺依赖时 `stage_state_update is None`（绝不写半截键）。`_h_bp_repo_confirmation` 的判定顺序固定为「先 `research_required` 再 `awaiting_confirmation`」，且在 `research_required` 分支用 `acollect_confirmation_state` 把最新快照刷进 `stage_state`（不刷则 112-04 的 dispatch 派不到新仓）。`MAX_BLUEPRINT_REROUTE_ROUNDS` 复用 112-04 常量（有等值断言）。

- **蓝图专用续驱（Task 3 ②）**：`resume.py` 逐字未改（`git diff --stat` 为空）。pause 判据的合取第二项有**独立放行断言**（只看线程就短路时该断言即红）。蓝图状态映射经 `BlueprintLifecycleService.transition`（阶段 0/1 全程 `researching`，有 open+blocking 线程时派生 `needs_clarification` 并带 `return_status=researching`），非法边/并发冲突一律吞掉——映射是展示面，绝不反噬续驱。`aresume_blueprint_session` 一并交付，112-04 的 fan-out barrier 已自动接通（其 Known Stubs 关闭）。

- **SC-4 端到端证伪线（Task 3 ④，本 plan 最关键的一条）**：7 例经**真实 REST 入口**、**不桩续驱**（只替身 dispatcher + 凭证解析 + 在线 runner）：
  - `add-repo` → `current_stage == "repo_research"`、C 仓 task ∈ {pending, running}、dispatcher **恰 await 1 次**且入参 repo_url 含 C 仓名、A/B 两仓 task 仍 `done` 且 `PartialPlan` 行数不变；
  - `reclassify-role`(indirect→direct) → 同样落 `repo_research`、该仓 task stale/running、dispatcher await 1；
  - `reclassify-role`(direct→indirect) / `remove-repo` → **仍停在 `repo_confirmation`** 且 dispatcher `await_count == 0`；
  - `upgrade-research` → 容器确实为且只为该仓起（dispatcher await 1 且 repo_url 匹配），其它仓结论保留；
  - `confirm` → 续驱把 session 推到 `status == done`（证明 confirm 也接了续驱而非停在挂起态）；
  - 续驱失败（真链路版） → `add-repo` 仍 200 且 `pending_research` 标记与 C 仓 task 已持久化、stage 不前进。

- **观测面**：三个 112-01 事件常量（`blueprint.confirmation.opened|action|locked`）全部接上 emit 点，payload 只含计数与 id。新增结构化事件 `blueprint_confirmation_opened|locked` / `blueprint_gate_action_applied` / `blueprint_gate_resume_completed|failed` / `charter_draft_submitted` 均带 `category="caller"` + `component` + `duration_ms` + `initiated_by_user_id`（无触发用户记 `system`）；判据/映射类事件走 `category="sampling"`。异常文本一律经 `redact_secrets_in_text`；职责正文/需求原文/禁区规则正文不进事件 payload。观测与章程回灌全部 best-effort。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `3bb86008` | 确认门 adapter（快照/锁定/decision_log/判据单一实现）+ lifecycle 纯追加五动作与升级方法 + 26 例测试 |
| 2 | `c78da852` | charter 定向草案写入（新文件）+ 8 个端点 + 序列化器 + 9 条路由 + 续驱接线（6 处）+ blueprint_resume + build_blueprint_engine + 49 例测试 |
| 3 | `9c79cbbf` | 七 stage 注册 + 7 个 handler + 32 例 stage graph 测试 + 7 例真实入口 SC-4 证伪线 |
| — | `5de5ef39` | 相位门两处断言口径修正（barrier 接通后的事件序列 + call_source 基准） |

## 测试与验证

- 新增 **114 例**全绿：
  - `tests/services/process_runtime/test_blueprint_confirm_gate.py`：**26 passed**
  - `tests/services/process_runtime/test_blueprint_process_graph.py`：**32 passed**
  - `tests/delivery/test_blueprint_gate_api.py`：**47 passed**（含 7 例真实入口 SC-4 端到端）
  - `tests/repositories/test_charter_draft_writeback.py`：**9 passed**
- PLAN verification 逐条实测：
  - `pytest tests/services/ tests/delivery/ tests/repositories/ tests/subagent/ -q` → **2108 passed, 1 skipped**
  - `pytest -q` 全套（相位门）→ **8013 passed, 63 skipped, 1 xfailed, 1 failed**；唯一红是 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` —— **纯环境问题**：`skills/` 是 git submodule（mode 160000），本 worktree 未初始化且其 pin 的 commit `755aae20` 在 remote 上不存在（`git submodule update --init skills` 实测 `upload-pack: not our ref`）。与本 plan 零关系（本 plan 改动文件清单不含 `skills/` 或该测试），已登记为 deferred。
  - `python manage.py evaluate_blueprint_golden` → 退出码 **0**（`total=1, failed=0`）
  - `python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**
- 冻结面自检（`git diff --name-only HEAD~4 HEAD` 精确匹配）：`repo_router_v2.py` / `process_runtime/{decompose_segments,research_adapter,architect_merge_adapter,merged_plan,clarify_adapter,render,resume,blueprint_schema,blueprint_route,blueprint_spec_gate,blueprint_research_adapter}.py` / `system/models.py` / `system/settings_service.py` / `event_taxonomy.py` / **`repositories/services/charter_service.py`** 全部**零命中**。
- 受限面自检（纯追加）：`git diff <file> | rg "^-" | rg -v "^---"` 对 `blueprint_lifecycle_service.py` / `entrypoint.py` 输出为空；对 `builtin_processes.py` 只有 docstring 计数一行（PLAN 明确允许）。
- acceptance rg 逐条实测：`confirmed_at_gate` ✓ / `"decided_by": "human"` ✓ / `async def apply_gate_action` ✓ / 五动作词频 37 ≥ 5 / adapter `.objects.(create|acreate|update|aupdate)` **0** / `add_reviewer` ✓ / `^async def acollect_pending_research_repos` ✓ / `blueprint-gate` in urls 17 ≥ 8 / `blueprint-gate-upgrade-research` ✓ / `IsAuthenticated` 10 ≥ 8 / `aupgrade_to_deep` in service ✓ / `aupgrade_repo_research` in views ✓ / `asubmit_charter_draft` ✓ / `normalize_charter_draft` ×6 ✓ / `RepoCharter.objects.(update|aupdate)` **0** / 视图 ORM 写正则 **0** / `sync_to_async` in views ✓ / **`aresume_after_gate_action` in views == 6** / `"research_required": "repo_research"` ✓ / `"routing"` ✓ / `^async def _h_bp_` **== 7** / `^register_process_type\(` **== 3** / `ahas_open_blocking_threads` in resume ✓ / `ClarificationService|delivery.Clarification` in resume **0** / `acollect_pending_research_repos` 在 resume 与 builtin **两文件均命中** / `^async def aresume_after_gate_action` ✓ / `^def build_blueprint_engine` ✓ / `threading.Lock|select_for_update|advisory_lock` in resume **0** / `git diff --stat resume.py` 为空。
- `manage.py shell` 注册项断言输出 `ok`（七 stage、`initial_stage == "intake"`、`exhausted → repo_confirmation`、`research_required → repo_research`）。
- 代码风格：改动文件全部经 `uv run ruff format` + `ruff check --fix`（只对自己改的文件跑），All checks passed。

## Deviations from Plan

共 10 处：4 处按现实修正的事实性偏差、4 处为完成 PLAN 要求所必需的加性扩展、2 处验收口径修正。无功能缩水。

**1. [Rule 1 - Bug] 确认门动作用「只追加消息」代替 `record_answer`（否则确认门会被开出第二条线程）**

- **Found during:** Task 1
- **Issue:** PLAN 要求动作侧 `record_answer` 追加人工消息留痕。但 111/112-02 的 `record_answer` 会把 `open` 线程推到 `answered`，而 `ahas_open_blocking_threads`（**只认 `open`**，属 112-02 冻结行为）随后判为「无门」→ `open_gate` 的 pending 门失守、再开第二条 `repo_confirmation` 线程；`blueprint_resume` 的 pause 判据同时失守。
- **Fix:** 新增私有 `_arecord_gate_note`（只 `BlueprintThreadMessage.objects.create`，**状态一字不动**），确认门线程保持 `open` 直到 `confirm` 的 `alock` 收尾。docstring 写明这条差别的理由。
- **Files modified:** `server/delivery/services/blueprint_lifecycle_service.py`
- **Commit:** `3bb86008`（`test_confirm_ready_to_lock_when_no_blocking_clarification` 断言动作后线程仍 `OPEN`）

**2. [Rule 1 - Bug] `build_locked_associations` 增 `citation_pool` 关键字：不过滤 citations 会让确认门永远锁不上**

- **Found during:** Task 1
- **Issue:** PLAN 的纯函数签名是 `(*, snapshot, decisions)`。但调研产出的 `fitness.citations` 是**裸文件路径/符号名**，而 `blueprint_schema` 后置检查 (a) 要求任何块内 `citations` id 必须存在于文档级引用池——直接落进去会让整份蓝图 `ArtifactContentInvalid`，`alock` 走 fail-closed 分支，`confirm` 在生产上永远失败。
- **Fix:** 加 `citation_pool: set[str] | None = None`（默认 `None` = 全留，与 PLAN 原签名行为一致）；`alock` 传入当前版本 `content["citations"]` 的键集做白名单过滤。
- **Files modified:** `server/services/process_runtime/blueprint_confirm_gate.py`
- **Commit:** `3bb86008`（`test_build_locked_associations_marks_human_decision_and_drops_removed` 锁死）

**3. [Rule 1 - Bug] `alock` 的锁定基线改取 artifact 最新版本（而非 session 钉住的那一版）**

- **Found during:** Task 2（写 confirm API 测试时）
- **Issue:** PLAN 写「深拷贝当前 `ArtifactVersion.content`」，实现为读 `session.current_artifact_version_id`。但规格门放行时 `add_version` 已推进 `artifact.current_version`，而 `session.current_artifact_version` 只在 handler 显式给 `StageOutcome.current_artifact_version` 时才更新——读 session 那一版会把规格门的 `requirement_spec` / `ambiguity_report` / `decision_log` 成果**覆盖回旧内容**。
- **Fix:** 用 session 那一版只解析 artifact 身份，content 基线取 `ArtifactVersion.objects.filter(artifact_id=...).order_by("-version_no").afirst()`（取不到才回落）。
- **Files modified:** `server/services/process_runtime/blueprint_confirm_gate.py`
- **Commit:** `c78da852`

**4. [Rule 1 - 事实修正] 待调研判据的标记来源是「`stage_state` ∪ 活跃线程 options」的并集，不是只读 `stage_state`**

- **Found during:** Task 1 ①b
- **Issue:** PLAN 写判据「读 `session.stage_state.get("confirmation")` 里 `pending_research is True` 的仓」。但动作端点（按 INV-6）只写线程行，`stage_state` 要等下一次 `transition` 才刷新——**紧随动作的那次续驱**读到的 `stage_state` 里根本没有新仓，判据为空 → pause 短路 → `research_required` 边永远走不到，SC-4 断链。
- **Fix:** 标记来源取并集（`stage_state["confirmation"]` ∪ open/answered 确认门线程 `options`），仍是**唯一实现**、两个消费方共用。同时 `_h_bp_repo_confirmation` 在 `research_required` 分支用 `acollect_confirmation_state` 把最新快照刷进 `stage_state`，保证 112-04 的 dispatch 读得到（它只认 `stage_state["confirmation"]`）。
- **Files modified:** `server/services/process_runtime/blueprint_confirm_gate.py`、`server/services/process_runtime/builtin_processes.py`
- **Commit:** `3bb86008` / `9c79cbbf`（`test_pending_probe_reads_live_thread_snapshot` 专门锁死）

**5. [Rule 3 - 契约补全] `apply_gate_action` / `aupgrade_repo_research` 增 `session=None` 关键字**

- **Found during:** Task 1 ②
- **Issue:** PLAN 给的签名只有 `(artifact, *, thread, action, payload, acting_user, initiated_by_user_id)`，但同一处要求经 `ResearchService.create_tasks_for_session(session, ...)` / `mark_stale` 落 task 可派发态、并 emit `ConvergenceSessionEvent`（`session` 是非空 FK）——原签名没有承载会话的入口。
- **Fix:** 加 `session: Any = None`（视图从 artifact 反查后传入）。为空时只保留快照标记 + 记一条 warning（标记在库里，下次续驱仍可闭环），**绝不因此抛错让动作失败**。
- **Files modified:** `server/delivery/services/blueprint_lifecycle_service.py`
- **Commit:** `3bb86008`

**6. [Rule 3 - 契约补全] `confirm` 的「未决澄清线程」用第 5 个恒定键 `blocked_reason` 表达，不新造异常类**

- **Found during:** Task 1 ②
- **Issue:** PLAN 要求返回形状恒定四键，同时要求视图对「存在未决阻塞澄清线程」回 **409**——四键装不下这个语义，而新造异常类会迫使修改 `blueprint_lifecycle_service.py` 的既有 `__all__` 行（破坏「纯追加」硬约束）。
- **Fix:** 返回值加**恒定存在**的第 5 键 `blocked_reason: str`（未阻塞为 `""`），形状恒定性不破、调用方无需判分支；视图据它回 409。
- **Files modified:** `server/delivery/services/blueprint_lifecycle_service.py`、`server/delivery/api/blueprint_gate_views.py`
- **Commit:** `3bb86008` / `c78da852`

**7. [Rule 3 - 契约补全] `open_gate` 增「已锁定 → `confirmed`」分支**

- **Found during:** Task 3 ①
- **Issue:** PLAN 的 `open_gate` 只描述了 pending 门与开门两条路径，但 `_h_bp_repo_confirmation` 需要「已确认 → `confirmed`」才能走到 `STAGE_DONE`——否则 `confirm` 后续驱会在 self-loop 上空转，`confirmed` 边永远走不到。
- **Fix:** `open_gate` 在 pending 门之后加一步：存在 `resolved` 的 `repo_confirmation` 线程（= `alock` 已收尾）→ 返回 `{"event": "confirmed"}`。
- **Files modified:** `server/services/process_runtime/blueprint_confirm_gate.py`
- **Commit:** `3bb86008`（`test_e2e_confirm_through_rest_drives_session_to_terminal` 端到端锁死）

**8. [Rule 3 - 阻塞修复] `charter_service` 的 INV-6 源码扫描守护改为 writer **白名单**（新增第二个合法 writer）**

- **Found during:** Task 2 verify
- **Issue:** `tests/repositories/test_charter_service.py::test_inv6_no_bypass_writes` 硬编码「唯一 writer = `charter_service.py`」，而 PLAN（W2）明令确认门章程回灌的写入函数**必须**放在新文件 `charter_draft_writeback.py`——两者直接冲突，新文件的 `RepoCharter.objects.create` 必然被判违规。
- **Fix:** 守护改为 `_ALLOWED_WRITERS` 枚举白名单（两个模块），并在注释写明第二个 writer 的存在理由与等价性由哪个测试锁死。**守护强度不变**——合法 writer 仍是显式枚举，新增写点必须登记。**没有**把守护放宽成正则或整目录豁免。
- **Files modified:** `server/tests/repositories/test_charter_service.py`
- **Commit:** `c78da852`

**9. [Rule 1 - 验收口径] 两处不可能成立/写错方向的验收断言**

- **Found during:** Task 2 / Task 3 verify
- **Issue 与 Fix：**
  - **`rg -n "STAGE_FAILED" builtin_processes.py | rg -c "exhausted"` 等于 0**：命中的那一行是**冻结的** `_TECHNICAL_PLAN_STAGES` 里 `merge.exhausted: STAGE_FAILED`（`:249`，先于本 plan 存在且不可改）。本 plan 的蓝图 stage 块内该组合零命中；真正的保证由 `test_reroute_exhausted_escalates_to_confirmation_not_failed` 的 `STAGE_FAILED not in stages["reroute"].transitions.values()` 断言承担。
  - **Task 2 的「续驱失败隔离」测法**：PLAN 写「把 `aresume_after_gate_action` 的 `AsyncMock` 设 `side_effect=RuntimeError`」。但失败隔离的契约恰恰是「helper 自己兜、视图不重复包」——替掉外层入口会连它的 `try/except` 一起替掉，那测的是「视图有没有自己包 try」，且必然让视图 500。改为桩掉**内层** `adrive_blueprint_session_to_pause_or_terminal`，保留真实包裹（Task 3 ④ 的真链路版同法）。
- **Files modified:** `server/tests/delivery/test_blueprint_gate_api.py`、`server/tests/services/process_runtime/test_blueprint_process_graph.py`
- **Commit:** `c78da852` / `9c79cbbf`

**10. [Rule 3 - 阻塞修复] 相位门两处既有断言口径（barrier 接通的连带影响 + Phase 111 遗留基准）**

- **Found during:** 相位门全量 `pytest -q`
- **Issue 与 Fix：**
  - `tests/subagent/test_blueprint_research_callback.py::test_failure_callback_marks_container_failed_and_emits` 断言失败回调 emit 的事件「恰好只有一条」。112-04 的 barrier 当时是 no-op 桩（其 Known Stubs 明写「112-05 只需提供该函数名即自动接通」），本 plan 提供 `aresume_blueprint_session` 后 barrier 真的会驱动 engine，后续 `transition` 各自 emit 一条。断言收紧为「失败事件必须是**第一条**」——守护强度不降（仍锁定失败事件必发且优先），且如实反映接通后的实态。
  - `tests/test_model_usage_call_source.py::TestCallSourceEnum::test_enum_has_all_22_values` 的期望集停在 35 值，而 `CallSource` 早在 **Phase 111-03**（commit `4505c7e6`）就补了蓝图链 8 值、另有 `feature_change_classify`。该断言自 111-03 起即红，与本 plan 改动无关（本 plan 未触碰 `agents/call_source.py`）；因本 plan 承接相位门全量测试，按 Rule 3 补齐期望集到 44 值并在 docstring 记录来源。
- **Files modified:** `server/tests/subagent/test_blueprint_research_callback.py`、`server/tests/test_model_usage_call_source.py`
- **Commit:** `5de5ef39`

## Deferred Issues

- **`tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`（相位门唯一残留红）**：`skills/` 是 git submodule（gitlink `755aae20`），本 worktree 未初始化，且该 commit 在 remote 上不存在（`git submodule update --init skills` 实测报 `upload-pack: not our ref`）。属**环境/子模块 pin 漂移**，不是代码问题，且完全在本 plan 的改动面之外（scope boundary：不顺手修）。修复路径：在主仓补齐 submodule pin 或在 worktree 初始化 submodule。
- **确认门重开后的快照刷新**：`open_gate` 的 pending 门在有 open 线程时不重算快照，因此容器回调带回的**新** fitness 不会自动回填进已开的门（用户需通过动作端点或重开门才看到）。这是 pending 门语义的必然结果，不影响本 plan 的任何交付物（锁定读的是线程快照 + 用户裁决），115 的呈现面可按 id 自取 `PartialPlan` 明细。

## Known Stubs

无。`_h_bp_intake` / `_h_bp_decompose` 是**有意的零副作用直通**（阶段 0 的需求装配由入口/规格门承担，功能点拆分留 116 入口切换），不是未接线的数据面占位——两者不取 deps、不写 stage_state，且 handler pass-through 测试逐条覆盖。112-04 遗留的 barrier 接线占位（`aresume_blueprint_session`）已由本 plan **关闭**。

## Threat Flags

无新增安全面。PLAN threat register 九条逐条落实：

- **T-112-22（越权）**：八端点 `IsAuthenticated`；`confirm` 绑 `request.user` 落 `decided_by=human` + `BlueprintReviewer` 留痕（有 API 断言）。
- **T-112-23（篡改 action/role/responsibility）**：action 白名单 + role 枚举在 service 层 `raise ValueError`；responsibility 截断 2000 / reason 截断 500；`body` 非 dict 按缺省处理；`artifact_id` 由 Django UUID converter 校验；`add_repo` 的仓存在性经 `Repository.objects.filter` 校验（非法 uuid 一律按「不存在」→ 404）。
- **T-112-24（AI 覆盖人工章程）**：`asubmit_charter_draft` 三分支等价性 + `human_confirmed` 只写 `draft_content` 双向断言（API 层与 service 层各一组）；`RepoCharter.objects.(update|aupdate)` 反向 rg 零命中；`charter_service.py` diff 为空。
- **T-112-25（决策不可追溯）**：`decision_log` 逐动作记 `{thread_id, action, repository_id, before, after, decided_at, decided_by}` 且按三元组幂等；事件 payload 带 action + repository_id；`initiated_by_user_id` 贯穿动作、续驱与草案写入。
- **T-112-26 / T-112-29（DoS：反复重开 / advance 死循环 / 并发重复起容器 / 续驱拖垮动作）**：pending 门短路不重开线程；`max_steps=20` 兜底（有 `advance_step_limit` 断言）；pausable self-loop 靠 status 短路；并发续驱靠 `_apply_transition_sync` 的 CAS 去重（`ConcurrentTransitionError` 被 engine 吞掉不落 fail）；容器不重开靠 `_DISPATCHABLE_STATUSES` + `get_or_create`（E2E 断言 dispatcher 恰 1 次、已完成仓零重跑）；续驱 `try/except` 全兜、失败只记 `blueprint_gate_resume_failed` 且 REST 仍 2xx；**零新造锁**（反向 rg 零命中）。
- **T-112-27（新 process 影响旧链）**：`_TECHNICAL_PLAN_STAGES` 逐字冻结快照测试 + `git diff` 纯追加断言；七个新 handler 全部 `getattr` 软取依赖，`engine.deps` 整体 `None` 也安全穿过（参数化覆盖 7×2）。
- **T-112-28（快照/事件泄漏正文）**：快照按「小摘要」纪律截断；事件 payload 只记计数与 id；异常经 `redact_secrets_in_text`；`rejected` 沉淀的范围解析拒绝跨项目全表查询（无范围即 400）。
- **T-112-SC**：零新增外部依赖，零模型改动（`makemigrations --check` 退出码 0）。

## Self-Check: PASSED

- 文件存在：8 个新建 + 8 个修改，全部命中（`git diff --name-only HEAD~4 HEAD` 16 个文件 = 上述清单）
- commit 存在：`3bb86008` / `c78da852` / `9c79cbbf` / `5de5ef39` 均在 `git log`
- artifacts `contains` 断言：`acollect_pending_research_repos` ∈ blueprint_confirm_gate.py ✓；`IsAuthenticated` ×10 ∈ blueprint_gate_views.py ✓；`_TECHNICAL_BLUEPRINT_STAGES` ∈ builtin_processes.py ✓；`aresume_after_gate_action` ∈ blueprint_resume.py ✓；`asubmit_charter_draft` ∈ charter_draft_writeback.py ✓
- key_links 断言：views → `BlueprintLifecycleService` ✓（视图零 ORM 写正则零命中）；confirm_gate → `asubmit_charter_draft` ✓；builtin_processes → `register_process_type` ×3 ✓；blueprint_resume → `ahas_open_blocking_threads` ✓；views → `aresume_after_gate_action` **×6** ✓
- 冻结面 / 受限面 / 并行面三项自检输出均为空 ✓
- **STATE.md / ROADMAP.md 未由本 plan 更新**：本 worktree 无 `gsd-tools` 可执行（`command -v gsd-tools` 为空），且 wave 1–3 的并行 plan 同样未更新——相位级 bookkeeping 留给 orchestrator 统一收口，避免四条并行线互相覆盖。

## Next Phase Readiness

- **113（repo_plan + merge + Context Bus）**：
  - stage graph 接续只需两步：把 `repo_confirmation.transitions["confirmed"]` 从 `STAGE_DONE` 改为 `"repo_plan"`，并在 `_TECHNICAL_BLUEPRINT_STAGES` 追加 `repo_plan` / `merge` 两个 StageDef（transitions 是数据，engine 与 `build_blueprint_engine` 都不用改，只需给 deps 加对应 adapter 属性——名单一致性有断言守护）。
  - 输入面：锁定后的 `repo_associations`（`role` / `responsibility` block_list / `fitness` / `routing_evidence` / `confirmed_at_gate` / `decided_by`）+ `decision_log`；逐仓明细按 `repository_id` 自取 `PartialPlan.content`（`findings` / `fitness.reasons` 全量在那里）。
  - 「锁定后变更须重开确认门」是 114 判 BLOCKER 的依据：判据 = 蓝图 `repo_associations` 的仓集与最新 `resolved` 确认门线程快照不一致。
- **115（前端）**：8 个端点即数据面，`GET blueprint-gate/` 一次返回门状态 + 逐仓快照 + `pending_research_repository_ids`；三个 confirmation 事件 payload 已定型。
- **116（入口收编）**：蓝图会话创建需补一个 `start_blueprint_orchestration`（形态照 `start_orchestration`，`process_type="technical_blueprint"`、`initial_stage="intake"`）——本 plan 只交付 engine 工厂与 stage graph，会话建立入口留给 116。
- **可调旋钮**：`_MAX_RESPONSIBILITY_CHARS = 2000` / `_MAX_SUMMARY_CHARS = 1000` / `_MAX_LIST_ITEMS = 10`（快照截断）、`max_steps = 20`（续驱上界）、`MAX_BLUEPRINT_REROUTE_ROUNDS`（复用 112-04）均为模块常量；若实战需运行时可调，按 112-02 的 `SettingKeys` 范式外置（模块常量留作缺省兜底）。
