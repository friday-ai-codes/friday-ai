---
gsd_state_version: 1.0
milestone: v0.20.0
milestone_name: 技术方案蓝图
status: executing
last_updated: "2026-07-31T05:00:00.000Z"
last_activity: 2026-07-31 -- Phase 114 plan 03 complete (ai_review stage 接线)
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 20
  completed_plans: 19
  percent: 56
---

# Project State

## Project Reference

See: .planning/PROJECT.md；本里程碑权威设计输入：**[.planning/technical-blueprint/DESIGN.md](./technical-blueprint/DESIGN.md)**（13 节，§12 八项决策已定夺，plan-phase 必读）。

**Core value（v0.20.0，在建）:** 技术方案成为「人类可读、AI 可依此完备编码」的项目级结构化蓝图——六段骨架每条结论带引用证据，三大编排阶段贯穿仓库确认门与分仓方案，仓库章程补齐净新增落点知识，飞书式划线澄清多轮收敛，全生命周期可管理，知识库可查可引可导出。
**Current focus:** Phase 114 — 审查与澄清收敛（AI 对抗审查 + 线程闭环 + 人工编辑）

## Current Position

Phase: 114 (审查与澄清收敛（AI 对抗审查 + 线程闭环 + 人工编辑）) — ✅ COMPLETE
Plan: 5 of 5 complete（114-01 线程底座 / 114-02 判定内核 / 114-04 回灌与人工编辑 / 114-03 ai_review stage 接线 / 114-05 人审七端点与度量面收口）
Status: Phase 114 已收口，下一个 **Phase 115 前端查看器与知识库**（消费契约见 `114-05-SUMMARY.md` 的七端点契约表与「Next Phase Readiness」节）
Last activity: 2026-07-31 -- 114-05 交付人审七端点 + finding 处置通道（**超界死锁打通**，经真实 REST 端点端到端证伪）+ 澄清提醒周期路径（既有 apscheduler 一个 job）+ blueprint_quality 三项 DB 统计实装；65 例新测试 + 三处变异验证，全量 8507 passed / 1 failed（仅 worktree 环境项 `test_skills_snapshot_guard`，零新增失败），全相位恰好一条 migration（`delivery/0033`）且 `makemigrations --check` 退出码 0

## Milestone Overview (v0.20.0 — Phases 111–116 — 🟡 PLANNING)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 111 | 蓝图底座（schema + 状态机 + 线程/章程模型 + golden set） | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | ✅ Complete (4/4, passed 24/24) |
| 112 | 规格门与双面路由调研（阶段 1 + 确认门 + 章程回灌） | FLOW-01/02/03/04, CHARTER-02/03 | ✅ Complete (5/5, 16/17 + gap closed) |
| 113 | 分仓方案与融合（阶段 2/3）+ Context Bus | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | ✅ Complete (6/6, passed 54/54) |
| 114 | 审查与澄清收敛（AI 审查 + 线程闭环 + 人工编辑） | FLOW-07, CLAR-02/03/04 | ✅ Complete (5/5，四条 REQ + 五条 BLOCKER 定夺均有绿色用例背书) |
| 115 | 前端查看器与知识库（查看器/批注/tab/终审 UI） | VIEW-01/02/03/04, CLAR-01, FLOW-08 | Not started |
| 116 | 入口收编与导出（MCP 协议 + 全入口 + 飞书导出 + 图谱物化） | GATE-01, VIEW-05 | Not started |

完整需求见 [REQUIREMENTS.md](./REQUIREMENTS.md)（35 条 + Traceability，35/35 映射；DEPTH-01~05 自 v0.19.0 Phase 108 迁入）；阶段详情见 [ROADMAP.md](./ROADMAP.md)。

**Execution order（依赖链，线性）:** 111 → 112 → 113 → 114 → 115 → 116。111 是数据与质量地基；112 锁规格与仓库集（确认门输出是 113 的输入）；113 产出完整蓝图；114 审查与澄清闭环；115 查看器；116 全入口收编（人审终审为前置）。

## 并行开发（与 v0.19.0 双 worktree，§13 纪律强制）

- **对方线:** `milestone/v0.19.0-plan-trust` worktree（Phases 105–107 + 109 + 110；108 已移交本里程碑，对方分支已确认收录该决策，commit `1fd3e60c`）。
- **同步点 1**（0.19 Phase 107 合并主干）：rebase 对齐澄清送达/提醒设施——影响 112/114 送达通道，未合并前用现有澄清通道兜底。
- **同步点 2**（0.19 Phase 109/110 合并）：execution 投影与事件时间线契约就位——116 的触点升级与默认入口切换在其后执行。
- **边界纪律（每个 plan 都必须遵守，违反=计划不通过）:**
  1. **不改 `codegraph/services/repo_router_v2.py`**——章程/历史落点证据在 `blueprint_route` adapter 层融合。
  2. **冻结既有 `technical_plan` process 六文件**（`decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py` 只读）；蓝图流水线全走 `blueprint_*` 新文件，`builtin_processes.py` 仅新增注册项。
  3. **`ConvergenceSessionEvent` 既有事件类型/字段只消费不修改**，本里程碑仅新增 `blueprint_*` 事件类型。
  4. **前端只新建组件**（BlueprintViewer/blueprints tab/批注层/预览弹层）；TechPlanCard/RoutingDecisionPanel/执行时间线归 0.19，触点升级留到同步点 2 后（116）。
  5. **migration 纪律**：`delivery`/`mcp_tools`/`repositories` 新增 migration 在每次同步点 rebase 时重新生成序号。
  6. **rebase 节奏**：0.19 每个 phase 合并主干后，本分支 rebase 一次，不长期漂移；`.planning/STATE.md` 冲突以本分支为准（ours）。

## 关键约束 / 设计底座（plan-phase 必读）

- **产物 canonical**：蓝图落 `delivery.Artifact(artifact_type=technical_plan)` + `ArtifactVersion.content`（`schema_version="blueprint/v1"`，旧 MergedPlan 为隐式 v0 只读渲染）；markdown 与 execution_plan 都是确定性派生物，禁止双轨创作。
- **上下文纪律**：`stage_state` 只存 id/计数/小摘要（单字段 <2KB）；子代理传 id 清单自取正文；并行容器动态共享走 Context Bus（DESIGN §5.6），不靠 prompt 传递。
- **HITL 语义**：确认门是硬门（`kind=repo_confirmation` 阻塞线程）；澄清超时保持显式 pending + 提醒，不自动作答不判失败；「需要澄清」是叠加态，记 `return_stage`。
- **章程原则**（DESIGN §5.7）：`RepoCharter` 人工确认生效，AI 只可提修订草案；意图分流是权重融合不是硬开关；`charter_match` 进 score breakdown；确认门动作回灌为草案。
- **权限**：项目成员皆可确认/评论/编辑；确认者自动进 `BlueprintReviewer` 名单；不做段级权限。
- **观测规范强制**：新 LLM 调用赋 `call_source`（`blueprint_decompose/spec_gate/repo_research/reroute/repo_plan/merge/ai_review`，LOGGING-SPEC §4.1 先登记）；stage 事件 `blueprint_stage_started/completed/failed` 带 `duration_ms`/`category`/`component`；容器动作绑定 `initiated_by_user_id`；脱敏不可绕过。
- **既有纪律沿用**：INV-6 单一写入入口（新增 `BlueprintLifecycleService` 等 service 收口）；async ORM 走 `sync_to_async`；i18n 默认中文；观测代码 best-effort 绝不反噬业务。
- **Out of Scope 锁定**：改 `repo_router_v2.py`；改旧 technical_plan process 六文件；改 `ConvergenceSessionEvent` 既有契约；TechPlanCard 等 0.19 归属组件（同步点 2 前）；Prompt Center 化；母子蓝图编排拆分；段级权限；审查换模型（档位可配即可）。

## Accumulated Context

### Decisions

- [Milestone v0.20.0, 2026-07-29]: 八项设计决策已定夺（DESIGN.md §12）——①蓝图项目级一项目一份活跃蓝图；②indirect 仓默认轻量调研可人工升级；③项目成员皆可确认、确认者自动进评审人名单；④澄清超时保持显式 pending 不自动作答；⑤AI 审查默认与起草同模型档位；⑥golden set 起步即建（含目标仓命中率，首条 case 高三提分专项）；⑦Context Bus 会话级共享上下文（token→会话→项目绑定 + 两档等待恢复 + 环检测）；⑧RepoCharter 仓库章程补意图面知识、双面路由按意图分流加权。
- [Milestone v0.20.0, 2026-07-29]: Phase 108（DEPTH-01~05）自 v0.19.0 迁入本里程碑，由 blueprint/v1 schema 原生满足；v0.19.0 分支已同步收录（commit `1fd3e60c`），其 109 改以现行 §7 execution_plan 对接执行流。
- [Milestone v0.20.0, 2026-07-29]: 与 v0.19.0 并行开发的四条边界纪律与两个同步点定版（DESIGN.md §13.2/§13.3），本文件「并行开发」节为执行时唯一对照清单。
- [Phase 111, 2026-07-30]: 111-01: `validate_blueprint` 对 `schema_version != "blueprint/v1"`（含缺失/未来版本）一律 pass-through，v0/v1 判别唯一收敛在 `delivery/artifacts/builtin_types.py` 的判别分支——未来 blueprint/v2 只改该判别点。
- [Phase 111, 2026-07-30]: 111-01: `iter_blocks` 的 section_path 约定 = 点分 + `[标识]`（items→id、repo_associations/current_state_analysis→repository_id、affected_features→feature、steps→seq，缺失回退位置下标）；114 重锚定与 115 渲染均按此约定消费，已有测试锁形状。
- [Phase 111, 2026-07-30]: 111-02: lifecycle 事件写入对 `ConvergenceSessionEvent.session`（非空 FK）做 session 可选处理——无编排会话时只打 structlog（best-effort）；`blueprint_*` 事件常量放独立 frozenset 不进 `ALL_EVENTS`（避免 taxonomy 覆盖性反查失败）。
- [Phase 111, 2026-07-30]: 111-03: charter 的「AI 不覆盖人工」不变量守卫落在 `charter_service` 层（human_confirmed 后 AI 只能产新 draft）；REST confirm 端点经 service 收口，不直写模型。
- [Phase 112, 2026-07-30]: 112-03: breakdown 三分量口径 = `router_base`（RepoRouterV2 整个 score 作单一不可拆分量，因该文件冻结且现状无 breakdown 字段）+ `charter_match` + `history_match`，三项之和等于总分；v0.19.0 Phase 105 落地分数分解后只需展开 router_base，adapter 契约不变。
- [Phase 112, 2026-07-30]: 112-03: 中文命中判定必须用 CJK 3-gram 交集——原按分隔符切词对「无分隔符整句禁区规则」必然漏判，会让章程禁区降权在生产静默失效。
- [Phase 112, 2026-07-30]: 112-04: fitness/role_suggestion/responsibility/findings 落 `PartialPlan.content`（`RepoResearchTask` 无 report 字段，仅作任务态载体）；dispatch 需 `force_deep_repository_ids` 参数，否则「人工升级深调研」会被重新分回轻量桶静默失效。
- [Phase 112, 2026-07-30]: 112-05: 确认门动作的续驱触发点在**视图层**（六个改状态端点，confirm 在 alock 之后——塞进 service 会在锁定前空转）；续驱失败只记 caller 事件、REST 仍 2xx、标记留库待下次触发；幂等复用既有 CAS 与 dispatch 白名单，不新造锁。
- [Phase 112, 2026-07-30]: 112-05: 确认门留痕不可用 `record_answer`（会把门推到 answered 并被重开第二道门）；fitness citations 必须过引用池白名单（否则 confirm 永远锁不上）；`alock` 不可读 session 钉住的版本（会覆盖规格门成果）。
- [Phase 113, 2026-07-30]: 113-01: 总线 `seq` 会话内单调**锁父 ConvergenceSession 行**分配（不锁子表——`select_for_update` 对空结果集无可靠 gap lock，MySQL/PG 行为不一），`UniqueConstraint(session, seq)` 只作兜底；seq 计算须提取为 `_next_seq` 打桩接缝，否则确定性冲突用例无从证伪。并发证据不得用 `asyncio.gather`（thread_sensitive 串行 + SQLite select_for_update no-op ⇒ 平凡通过）。
- [Phase 113, 2026-07-30]: 113-01: 总线 `content` 是 JSON dict，必须走自建 `_redact_json` **递归叶子脱敏**；禁止 `redact_secrets_in_text(json.dumps(...))` 再 loads。waiter 落 `kind="dependency_claim"` 行而非 stage_state（并行容器高频写会 lost-update）。
- [Phase 113, 2026-07-30]: 113-02: 容器 MCP 鉴权只到 `token → owner`，会话隔离必须 view 层自建三道（`sub.main_session.user_id == request.user.id` 空值 fail-closed / `process_type == technical_blueprint` / 条目 session 一致）；三道均经变异验证可触发 403。公共 handler 工厂（`timeout=60.0`/`quota_counter`/无 callback）禁改——配额改由派发时提到 400。
- [Phase 113, 2026-07-30]: 113-03: plan 模式全走带默认值 keyword-only 参数（缺省逐字等价 112）；`last_output.source` 必须换 `blueprint_repo_plan`（否则被阶段 1 判据抢走并因缺 `fitness.verdict` 判失败）；`env_FRIDAY_TASK_MODE` 保持 `explore`（它管 git 写拦截，与调研/拟方案正交）；重试须「先 mark_failed 再 mark_stale」并豁免跨阶段 `_MAX_ATTEMPTS`。
- [Phase 113, 2026-07-30]: 113-05: needs_support **只写 `data_source.availability`（`existing|needs_support`）与 `data_source.support_repository_id`**，顶层零残留——111 schema 无顶层 availability，写错位置会让 114/115 读不到而断言仍全绿（假通过）。确定性投影段（repo_associations/current_state_analysis）必须可断言「零起草贡献仍逐字段一致」。
- [Phase 112 review 修复, 2026-07-30]: **跨 process 污染防线**：确认门 `_aload_session` 必须强制过滤 `process_type="technical_blueprint"`（取不到即 404），且 `adrive_blueprint_session_to_pause_or_terminal` 入口加守卫 no-op——原实现按「最近一条」取会话会把并存的 `technical_plan` 会话用蓝图 engine 驱成 FAILED 而 REST 仍回 2xx（反向断言已证实）。后续任何按 artifact 取会话的代码都必须带 process_type 过滤。
- [Phase 112 review 修复, 2026-07-30]: **规格门 fail-closed 补洞**：打分不可得或 `total=1.0` 时一律复述原问题重新挂起（兜底问题不参与指纹去重）；「问不出新问题」才放行且必须记 `capped=True` + `release_reason` 区分两条例外路径。
- [Phase 112, 2026-07-30]: GAP-1 闭环：`reroute.excluded` 必须被候选筛选真实消费（路由候选 + 确认门 pending 两条来源同时剔除，仅人工升级豁免），reroute 轮复用 `blueprint_route(exclude_repository_ids=...)` 补候选、补不到才升门；排除集累积。
- [Phase 114, 2026-07-31]: 114-04: **任何产新版本的路径都必须跟一次 `areanchor_threads`**，否则旧批注错位；基线一律 `order_by("-version_no").afirst()`，绝不读 `session.current_artifact_version`（会把上游成果覆盖回旧内容）。线程行写入唯一通道是 lifecycle service 内的 `bulk_update`（INV-6），adapter / view / 纯函数层只读。
- [Phase 114, 2026-07-31]: 114-04: **写进 content 的时间戳必须来自可重放的既有数据**（`decision_log.decided_at` 取线程作答消息的 `created_at`）——用 `timezone.now()` 会让 `content_hash` 每次变、每次翻新版本，破坏「同 hash 不翻版本」并把版本历史刷成噪声。同理 `anchor` 不进 `decision_log`（随重锚定漂移）。
- [Phase 114, 2026-07-31]: 114-04: **「AI 不覆盖人工」需要两个入口**——回灌侧 `detect_human_conflicts`（交集非空即不落版本、开阻塞线程）挡不住 `repo_rework`/`remerge` 的**重装**路径，后者由 `arestore_human_blocks` 逐块 canonical JSON 比对兜住（人工块写回 + 开线程）。「哪些块是人写的」唯一判据是 `produced_by_ref__startswith="human_edit:"`（`ArtifactVersion` 无 `created_by_user_id`）。
- [Phase 114, 2026-07-31]: 114-04: `decision_log` 物化**必须保 `answer` 键**（`blueprint_spec_gate._collect_prior_answers:587` 读它），否则「同一问题不再重复问」在审查阶段静默断链；`applied_in_version` 取**基线版本 id**（产出版本 id 写入前不可知），产出版本经 `produced_by_ref == f"ai_review_reflow:{thread_id}"` 反查。
- [Phase 114, 2026-07-31]: 114-04: `section_writer` 缺省即生产实现 `ablock_section_writer`（**不是 no-op**）——否则答案只进 `decision_log` 而正文永不更新，等于答案不落地；LLM 不可得只让该块原样保留，`decision_log` 与线程收尾照常 ⇒ 答案永不丢失。
- [Phase 114, 2026-07-31]: 114-03: **审查轮次绝不进融合桶**——`stage_state` 增量只写自己的 `"ai_review"` 键，靠 engine 顶层浅合并落盘；融合侧 `_build_stage_state` 每轮整桶覆盖它自己那个键，轮次塞进去会被抹掉 ⇒ 计数归零 ⇒ 无限打回循环（T-114-14）。任何新增 stage 的 stage_state 写入都必须只写自己的桶。
- [Phase 114, 2026-07-31]: 114-03: **审查超界是「待人审」不是「流程失败」**——`ai_review` 的 transitions 五条出边不含 failed，超界走 `review_exhausted → STAGE_DONE` + 蓝图 `pending_review` + `unresolved` 六键快照。死锁出口由 114-05 的 finding 处置端点提供（`resolve_thread(dismissed=False/True)` 让线程离开 `{open, answered}`，confirm 守卫随之放行）；⛔ 绝不能用作答通道把 finding 推到 `answered`（既解不开门也污染状态）。
- [Phase 114, 2026-07-31]: 114-03: **批量重锚的判据是「版本推进」而非「本轮是否产版本」**——B3 点名的主路径是 `repo_rework`/`remerge` 重跑融合产的版本，此时 `arestore_human_blocks` / `aapply_thread_answers` 都不产版本；以「本轮是否产版本」为判据会让重锚永不触发、批注全部错位（CLAR-02）。判据实现为比对 artifact 最新版本 id 与 `stage_state["ai_review"]["anchored_version_id"]`。
- [Phase 114, 2026-07-31]: 114-03: finding 线程的 `question` **必须**保持 `[{rule_id}] {detail}` 前缀——`BlueprintThread` 无 rule_id 列，去重索引靠首条消息的该前缀反查；改格式会让第 2 轮重开线程、人审侧噪声爆炸。`anchor.quoted_text` 必须非空（`reanchor` 在 block_id 消失且 quoted_text 为空时直接判失锚）。
- [Phase 114, 2026-07-31]: 114-05: **超界死锁的唯一正向出口是 finding 处置端点**（`blueprint-review/threads/<uuid>/resolve/` 与 `/dismiss/` → `resolve_thread(dismissed=False/True)`）——线程落终态后离开 confirm 守卫判据②，approve 放行；⛔ 绝不用作答通道处置（只推到 `answered`，仍在判据里，解不开锁还污染状态）。变异实测：换成作答通道后死锁用例转红。
- [Phase 114, 2026-07-31]: 114-05: **approve 端点零事务外二次查询**——守卫判据已在 `_apply_transition_sync` 事务内单次 `Q`，视图再查即 TOCTOU；`aunresolved_blocker_count` 只用于 GET 快照与 **409 响应体的呈现**（告诉人审「去处置这几条」，那是解药入口）。114-01 的 `test_no_out_of_transaction_blocker_check_before_confirm` 扫 `delivery/api/` 全目录，新增端点文件必须避开该形状。
- [Phase 114, 2026-07-31]: 114-05: **任何读 `Artifact.blueprint_status` 的返回键/字典键都不能用字段名本身**——`test_inv6_no_bypass_blueprint_status_field_write` 把「字段名 + 等号」形态的赋值/kwarg/字典键一律判为旁路写（该正则是为了逮住 `**{…}` 展开绕过 CAS）。纯读场景改用 `current_status` 之类的键名，**绝不为迁就命名去豁免守卫**。
- [Phase 114, 2026-07-31]: 114-05: **新增周期任务一律挂既有 apscheduler**（不新起 cron / systemd timer / 第二个 `BackgroundScheduler`），且「tick 间隔」与「业务周期」分层——tick 以启动值为准，业务周期读配置可热改。GET 只读端点是**伪挂载点**（没人来看就没有请求，任务永不触发）。提醒判据状态是 `needs_clarification` 而非 `pending_review`（后者是「等人审决策」，不是「无人应答」）。
- [Phase 114, 2026-07-31]: 114-05: **新增 DB 统计无数据必须返 `None` 而不是 0**，并把「无数据 / 零值 / 有值」三态写成并列用例——那是逮住「口径写错导致指标恒零而测试全绿」的唯一手段（`human_edit_volume` 的 `created_by_user_id` 偏差就是这么被逮住的：`ArtifactVersion` 无该字段，正解是 `produced_by_ref__startswith="human_edit:"`）。
- [Phase 111, 2026-07-30]: 111-04: golden set 与 v0.19.0 路由 golden set 完全分离（`server/tests/fixtures/blueprint_golden/` + `evaluate_blueprint_golden` command），首条 case 为高三提分专项；引用覆盖率/目标仓命中率为纯函数，另三项 DB 统计留接口占位待 112–114 填充数据。

### Pending Todos

- [Phase 111 review 跳过项] **MN-06**：需新增 migration 才能修（详见 `.planning/phases/111-schema/111-REVIEW.md` Fix Log）——留到 112/113 有 migration 批次时一并做，避免为单条 MINOR 单独起 migration
- [Phase 111 review 跳过项] **MN-12**：属权限口径决策（非实现缺陷），与 115 前端权限呈现一并定夺
- [Phase 112 review 跳过项] **MN-06**：删除/启用皆属零行为收益的 churn（理由见 `.planning/phases/112-1/112-REVIEW.md` Fix Log）；MJ-06 的 `match_kind` 证据字段一并保留
- [Phase 113 review 跳过项] **MN-09 重试计数无服务端权威来源**：两条建议修法均不可取——改 `session_id` 前缀撞冻结面 `research_adapter.py`；改走 `last_output` 是安全倒退（runner 可篡改 → 无界重试）。现状影响有界（卡住时人可见可续），**正解是给服务端加权威计数列**，另起小相位处理（见 `.planning/phases/113-2/113-REVIEW.md` Fix Log）
- ~~[Phase 114-04 延后项] `blueprint_lifecycle_service.py:358` 的 `blueprint_transition_event_persist_failed` 缺 `category`/`component`~~ —— **114-05 已修**（commit `6f91f778`，补 `category="caller"` + `component="blueprint_lifecycle"`，并把异常文本改走 `redact_secrets_in_text`）。⚠️ 留一个可再议点：该事件与同函数内的转移事件家族（`component="process_runtime"`）不同组，若 115 观测面希望转移家族共用一个 component，改这一处即可（零行为影响）
- [Phase 114-05 有意边界] **提醒只到「记事件 + 写周期锚点」为止，渠道投递未实现**：这是 PLAN 的有意边界（飞书卡片重推/站内通知归 115/116 通知面）。当前运维能从 `blueprint_clarification_reminded` 事件看到「谁该被提醒、几个人、哪条线程」，但**用户收不到实际通知** ⇒ 115/116 接上通知面之前，CLAR-04 的用户可感知价值只兑现一半。收件人名单可经 `BlueprintReviewer` ∪ 蓝图会话发起人复算（⚠️ 反查会话必须带 `process_type="technical_blueprint"` 过滤）
- [Phase 114-03 环境项] **`tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 在本 worktree 恒红**：断言 `skills/skills/*/SKILL.md` ≥4，而 worktree 的 `skills/` 是空目录（主检出里有内容）。纯 worktree 环境现象，与蓝图相位无关；里程碑收尾在主检出复跑即可
- [Phase 112 残留 PARTIAL] **FLOW-02 的「替代建议」无结构化字段**：fitness 的 `reasons` 承载了理由，但 unsuitable 时的「建议改去哪个仓」未落成结构化字段（当前混在自由文本里）。113 若需机器消费该建议再补 schema 字段，否则留到 115 前端呈现时定夺

### Blockers/Concerns

- 同步点 1/2 依赖 v0.19.0 的 107 / 109+110 合并主干节奏；116 的入口切换在同步点 2 前不可执行（可先做 MCP 协议与导出的后端部分）。
- `.planning/` 三文件（ROADMAP/REQUIREMENTS/STATE）与 0.19 分支在里程碑收尾合并时预期机械冲突：v0.19.0 段以对方为准、v0.20.0 段以本分支为准、STATE 以存活里程碑为准。

### 共享面改动备注（Phase 113-06，同步点需关注）

- **`process_runtime/engine.py`**（非 §13.2 冻结面，但与旧 `technical_plan` process 共享）：修掉「每次不产版本的转移都无条件把 `session.current_artifact_version` 透传成 NULL」的缺陷——原行为会让阶段 2/3 永远找不到基线版本，且因全链 best-effort 吞异常而完全静默。该修复对两条链都是严格改进，但**属共享代码**：与 v0.19.0 合并时需确认无冲突，并在 rebase 后复跑旧链回归。
- 另修：无阻塞线程的 `needs_clarification` self-loop 会被续驱推到 `max_steps` 落 FAILED（已加出口）。

### 安全边界备注（Phase 113-02）

- `ConvergenceSession` **无 project FK**：容器 MCP 总线读写的「项目成员」闸只能 best-effort 反查，**会话未绑项目时不叠加成员校验**。此时硬防线是第①道（session 的 `AgentSession.user` == task token owner，空值 fail-closed）+ 第②道（`process_type == technical_blueprint`）+ 第③道（条目 session 一致），三道均经变异验证可触发 403。若后续要求「未绑项目会话也必须过成员闸」，需先给 ConvergenceSession 补项目关联——留待 114/116 评估。

## Session Continuity

Last session: 2026-07-31 — Phase 114 全量交付（114-01 线程底座 → 114-02 判定内核 → 114-04 回灌与人工编辑 → 114-03 ai_review stage → 114-05 人审端点与度量面收口）
Next step: **Phase 115（前端查看器与知识库）** —— 可直接消费 `114-05-SUMMARY.md` 的七端点契约表（URL / `name` / 入参 / 状态码映射 / GET 快照响应键 / answer 的 `reflow` 键 / approve 409 的未决清单形状）与「Next Phase Readiness」节；版本溯源用 `produced_by_ref` 四前缀（`human_edit:` / `ai_review_reflow:` / `human_block_restore:` / `blueprint_review_reject:`）。⚠️ **115/116 必须接上通知面**：澄清提醒当前只落事件与周期锚点，用户收不到实际通知（见 Pending Todos）。
Resume file: 无（干净接力点：Phase 111–114 全部 commit 已入库）
