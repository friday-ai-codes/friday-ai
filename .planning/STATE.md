---
gsd_state_version: 1.0
milestone: v0.20.0
milestone_name: 技术方案蓝图
status: v0.20.0 milestone complete
last_updated: "2026-08-02T00:55:00.000Z"
last_activity: 2026-08-02
last_activity_description: v0.20.0 milestone completed and archived
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 34
  completed_plans: 34
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md（updated 2026-08-02，v0.20.0 归档后）。v0.20.0 的权威设计输入 `technical-blueprint/DESIGN.md` 与全部相位产物已归档到 `.planning/milestones/v0.20.0-phases/`。

**Core value:** 让团队"开箱即用、安全地"把需求自动变成代码。**v0.20.0 交付的那一层**：技术方案成为「人类可读、AI 可依此完备编码」的项目级结构化蓝图——六段骨架每条结论带引用证据，三大编排阶段贯穿仓库确认门与分仓方案，飞书式划线澄清多轮收敛，全生命周期可管理、可查可引可导出。
**Current focus:** ⛔ **下一里程碑尚未立项**。它取决于 `milestone/v0.19.0-plan-trust` 的合并（同步点 2）——在此之前 v0.20.0 的收尾工作项（默认入口切换等四件事）结构上无法开始。

## Current Position

Phase: Milestone v0.20.0 complete
Plan: —
Status: Awaiting next milestone（阻塞于 v0.19.0 分支合并）
Last activity: 2026-08-02 — Milestone v0.20.0 completed and archived

> 相位执行期的逐 plan 状态存档（116-07 / 116-06 / 116-05 / 116-04 / 116-03 的收口记录、各 plan 的「开工前必读」清单）随本次归档移出本文件 —— 权威副本在 `.planning/milestones/v0.20.0-phases/<phase>/<plan>-SUMMARY.md`，历史版本在 git。**仍然有效的跨里程碑信息全部保留在下方**：并行开发口径、关键约束/设计底座、Accumulated Context 的 Decisions 与 Pending Todos、Blockers/Concerns。

## Milestone Overview (v0.20.0 — Phases 111–116 — ✅ SHIPPED 2026-08-02；六相位全部完成并 verified，CLAR-03 closure 已闭，里程碑审计 `tech_debt`)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 111 | 蓝图底座（schema + 状态机 + 线程/章程模型 + golden set） | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | ✅ Complete (4/4, passed 24/24) |
| 112 | 规格门与双面路由调研（阶段 1 + 确认门 + 章程回灌） | FLOW-01/02/03/04, CHARTER-02/03 | ✅ Complete (5/5, 16/17 + gap closed) |
| 113 | 分仓方案与融合（阶段 2/3）+ Context Bus | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | ✅ Complete (6/6, passed 54/54) |
| 114 | 审查与澄清收敛（AI 审查 + 线程闭环 + 人工编辑） | FLOW-07, CLAR-02/03/04 | ✅ Complete (5/5，四条 REQ + 五条 BLOCKER 定夺均有绿色用例背书) · ✅ Reviewed & Fixed (10 fixed / 1 skipped) |
| 115 | 前端查看器与知识库（查看器/批注/tab/终审 UI） | VIEW-01/02/03/04, CLAR-01, FLOW-08 | ✅ Complete (7/7) |
| 116 | 入口收编与导出（MCP 协议 + 全入口 + 飞书导出 + 图谱物化） | GATE-01, VIEW-05（+ 顺延闭合 VIEW-04、VIEW-02） | ✅ Complete (7/7, passed 121/121) · ✅ Reviewed & Fixed (9 fixed / 0 skipped) |

完整需求见 [milestones/v0.20.0-REQUIREMENTS.md](./milestones/v0.20.0-REQUIREMENTS.md)（35 条 + Traceability，35/35 映射、34 条 Complete；DEPTH-01~05 自 v0.19.0 Phase 108 迁入）；阶段详情见 [milestones/v0.20.0-ROADMAP.md](./milestones/v0.20.0-ROADMAP.md)；里程碑审计见 [milestones/v0.20.0-MILESTONE-AUDIT.md](./milestones/v0.20.0-MILESTONE-AUDIT.md)。

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
  ⭐ **「项目成员」自 114 review 起是真的有闸**（MJ-03）：蓝图七端点按蓝图自身 `meta.project_id` 反查 `initiatives.ProjectMember`，fail-closed + 中性 404 + superuser 直通；范围只从蓝图推导，绝不接受请求体 `project_id`。**新增任何蓝图读写端点都要照挂 `_aassert_project_scope`。**

- **可编辑状态白名单**（114 review MJ-04）：改写蓝图正文的路径（`edit-blocks` / `answer` 回灌）一律过 `blueprint_lifecycle_service.is_blueprint_editable`；已 `confirmed` 及其后的状态**不可无声改写**，要改先驳回（`confirmed → drafting` 合法边）再重走人审——这是「AI 不得覆盖人工」的对称面。
- **观测规范强制**：新 LLM 调用赋 `call_source`（`blueprint_decompose/spec_gate/repo_research/reroute/repo_plan/merge/ai_review`，LOGGING-SPEC §4.1 先登记）；stage 事件 `blueprint_stage_started/completed/failed` 带 `duration_ms`/`category`/`component`；容器动作绑定 `initiated_by_user_id`；脱敏不可绕过。
- **既有纪律沿用**：INV-6 单一写入入口（新增 `BlueprintLifecycleService` 等 service 收口）；async ORM 走 `sync_to_async`；i18n 默认中文；观测代码 best-effort 绝不反噬业务。
- **Out of Scope 锁定**：改 `repo_router_v2.py`；改旧 technical_plan process 六文件；改 `ConvergenceSessionEvent` 既有契约；TechPlanCard 等 0.19 归属组件（同步点 2 前）；Prompt Center 化；母子蓝图编排拆分；段级权限；审查换模型（档位可配即可）。

## Deferred Items

Items acknowledged and deferred at milestone close on 2026-08-02（`gsd-tools query audit-open` 全量 4 项，均判为不阻塞归档）:

| Category | Item | Status |
|----------|------|--------|
| verification_gap | Phase 112 · `112-VERIFICATION.md` | gaps_found（该 gap 已在相位内 closure，见 ROADMAP 记账「16/17 + gap closed」；VERIFICATION 文件的 frontmatter 未回写，归档随相位产物移入 `milestones/v0.20.0-phases/112-1/`） |
| quick_task | `260610-oug-url-https` | unknown（v0.20.0 范围外的既有 quick task） |
| quick_task | `260611-ghb-workflow-card-uniform` | unknown（v0.20.0 范围外的既有 quick task） |
| quick_task | `260624-w11-abort-stuck-index-job-962-and-add-2mb-pr` | unknown（v0.20.0 范围外的既有 quick task） |

⚠️ 里程碑级技术债（同步点 2 的四件事 / G1·G3·G4 三道入口接缝 / mcp npm 包漂移 / Nyquist validation 缺失 / 平台级脱敏与权限口径）**不在本表**，权威清单是下方 Pending Todos 与 [milestones/v0.20.0-MILESTONE-AUDIT.md](./milestones/v0.20.0-MILESTONE-AUDIT.md)。

## Operator Next Steps

- ⛔ **不要现在开下一个里程碑。** 先合并 `milestone/v0.19.0-plan-trust`（`.planning/` 三文件的机械冲突口径见下方 Blockers）。
- 合并达成同步点 2 之后，第一件事是 Pending Todos 第 2 条的**四件事同批改动**（翻四个 per-entry 开关默认值 + 三个入口出口映射重做 + 三处触点升级 + 旧 `technical_plan` process 退役）。⚠️ 灰度顺序按「第一次澄清就会撞 G1/G4」估，⛔ 不要按「先翻开关再看终态」的直觉走。
- 之后再 `$gsd-new-milestone` 立项下一里程碑（届时在 `REQUIREMENTS.md` 之上追加新段）。

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
- [Phase 114 review 修复, 2026-07-31]: **⛔ 回灌链绝不消费 `ai_review_finding`（CR-01，115/116 新增作答/回灌入口必须遵守）**：`blueprint_reflow.REFLOW_KINDS` 只含 `ai_clarification`，且**显式传入的 `threads` 也按 kind 过滤**（fail-closed，不依赖调用方自觉）。根因是回灌链落版本成功后会对被消费线程**无条件 `resolve_thread`** ⇒ 让 finding 进来即等于「在 BLOCKER 上回一句任意文本」就解开 confirm 门，绕开 `reason` 必填 / `[已修复]`-`[误报忽略]` 语义 / 「处置人：{uid}」留痕。finding 处置**只**走 `aresolve_finding` / `adismiss_finding`；answer 端点对 finding 一律 400。
- [Phase 114 review 修复, 2026-07-31]: **stage graph 的出边只能推向终态，没有任何一条边能把 `done` 拉回运行**（MJ-01）。人审驳回因此必须显式复位会话：新增 `ConvergenceSessionService.areopen_stage`（只从 `done` 复位、`failed` 不动以留首因、stage 必须在 stage graph 内、CAS 以 `status==done` 为前置、不碰 `stage_state`/`current_artifact_version`/`error`），`areject_blueprint` 在「版本已落 + 轮次已加 + 状态已 drafting」之后复位到 `merge`（与 `ai_review` 既有 `remerge` 出边同目标，不新造返工语义）。**115/116 若新增「把终态会话拉回运行」的需求，一律复用它，不要各自 update session.status。**
- [Phase 114 review 修复, 2026-07-31]: **动作端点回传的状态必须在续驱之后重读**（MJ-01 第二点）：service 侧取值发生在续驱之前，而 `_amap_blueprint_status` 会据「仍有 open+blocking 线程」把状态推成 `needs_clarification` ⇒ 直接回传 service 快照会让前端拿到的状态「刷新一下就变」。`blueprint_review_views._acurrent_status` 是该口径的落点。
- [Phase 114 review 修复, 2026-07-31]: **「没有 anchor」≠「失锚」（MJ-02，115 直接消费 `orphaned_threads`）**：批量重锚前置 `_has_anchor_locator`（`block_id` 或 `quoted_text` 非空），无定位即 `skipped` 且 `anchor_status` 保持原值。`blueprint_anchor.reanchor` 把空 anchor 判 orphaned 是**单条**语义下的正确行为，批量层照搬会把自动推进线程 / 规格门确认门线程 / 无划线的驳回评论 / 无 block_id 的 finding 线程在**每一条产版本路径**上持久标成失锚 ⇒ CLAR-02 的失锚清单被噪声淹没。**115 呈现失锚清单时可以信任「里面都是真失锚」。**
- [Phase 114 review 修复, 2026-07-31]: **蓝图七端点已收项目范围闸（MJ-03）——115 前端与 116 入口新增蓝图写端点必须照挂**：`blueprint_review_views._aassert_project_scope` = 按蓝图自身 `meta.project_id` 反查 + 校验 `ProjectMember`，**fail-closed**（读不到/非 UUID → 400）、越权回**中性 404**（不泄露存在性）、superuser 直通；范围**只从蓝图推导，绝不接受请求体里的 `project_id`**。⚠️ 同时订正一条既有认知：本仓**有**项目成员概念（`initiatives.ProjectMember` / `permissions.IsProjectMember` / `chat.conversation_service._is_project_member`），关键约束节「项目成员皆可确认/评论/编辑」现在是真的有闸，不再是「全员皆可」。
- [Phase 114 review 修复, 2026-07-31]: **人不该在确认之后无声覆盖已确认内容（MJ-04）**——与「AI 不得覆盖人工」对称。`blueprint_lifecycle_service.EDITABLE_BLUEPRINT_STATUSES` / `is_blueprint_editable` 是**唯一**判据（含 `""` 以兼容 v0 数据），`edit-blocks` 与 `answer` 双侧收口；越界要改必须先驳回（`confirmed → drafting` 是合法边）再重走人审。理由：`edit-blocks` 原先全程不读 `blueprint_status` ⇒ 已 `confirmed`/`implementing` 的蓝图可继续落 `human_edit:` 版本而状态不变，下游拿到的 `current_version` 已不是当初被确认的那一版（确认锚定的内容被事后掉包且无痕），且 `human_edit:` 前缀是 B3 人工块保护的判据源，保护集会凭空扩大。**115/116 新增任何改写蓝图正文的路径都必须过这道闸。**
- [Phase 114 review 修复, 2026-07-31]: **同一 rule 的不同形态必须由 `rule_id` 区分，不能靠 `section_path`**（MN-03）：`finding_dedupe_key` 优先取 `block_id`，改 `section_path` 根本不改变键；而 `rule_id` 是 `_aload_finding_threads` 唯一能从线程首条消息 `[rule_id]` 前缀反查回来的段，也因此是唯一能让**第二轮**的键仍分得开的载体（给 `_finding` 加 `variant` 键无效——反查不回来）。`gate_lock_violation` 已拆成 `_MISSING`（保留原值）/`_ROLE`/`_RESPONSIBILITY` 三值。
- [Phase 114 review 修复, 2026-07-31]: **终审态不由续驱驱动**（MN-06）：`blueprint_resume._HUMAN_OWNED_STATUSES`（`pending_review`/`confirmed`/`implementing`/`implemented`/`archived`/`superseded`）在状态映射前短路——这些状态的推进只归人审动作端点与下游 implementing 链。原先 `pending_review` + 未决 BLOCKER 会让映射器每次续驱都白抛一次非法边并刷一条 `blueprint_status_map_skipped`，真故障淹没在噪声里。
- [Phase 114 review 修复, 2026-07-31]: **周期任务的「已完成」计数与事件必须在写回成功之后才落**（MN-04）；**扫描窗口必须显式排序**（MN-01）——`BlueprintThread.Meta` 无 `ordering`，无 `ORDER BY` 的 `LIMIT` 会让已提醒的线程永久占名额、后来的静默饿死。两条对 115/116 新增的任何「扫描 + 写锚点」周期任务同样适用。
- [Phase 115-01]: 蓝图列表响应键定为 current_status（避开 INV-6 字段级守卫；ORM 过滤走 _STATUS_FIELD 常量），UI-SPEC §3.3 同步订正
- [Phase 115-01]: 列表分页体定为 {total, items, page, page_size, has_next} 五键（方案 A 的 Python 侧过滤用不上 DRF 分页 helper），订正 UI-SPEC §3.3 的「DRF 分页体」
- [Phase 115-01]: 范围闸与中性 404 文案常量一律 import 复用 blueprint_review_views 私有符号（既有文件零改动），使「非成员 404 与不存在 404 逐字相同」结构性成立
- [Phase 115-02, 2026-08-01]: **A2 假设 settle：happy-dom 20.10.2 四项能力全部支持**（`createTreeWalker` / `createRange` / `Range.getBoundingClientRect` / `getSelection`，加三项行为探针共七项全 `true`，由 `utils/__tests__/domCapabilities.test.ts` 的 `toMatchInlineSnapshot` 永久锁住）⇒ 批注层 offset 计算走**自动化单测**而非 UAT；**唯一仍归 UAT 的是选区 popover 的落点坐标**（happy-dom 无布局引擎，`getBoundingClientRect` 恒返 0 矩形）。
- [Phase 115-02, 2026-08-01]: **UI-SPEC §8.3 轮询写法订正为「两形态 + `watch` 踢动」**：自带状态字段的 snapshot 查询读**自身** `query.state.data`；**无状态字段**的 doc/events 查询读外部 `isLive` 并**必须配 `watch(isLive, on => on && refetch())`**。理由：函数式 `refetchInterval` 只在本查询自己的 state 更新时重算，函数体里读外部 ref **不是被追踪的响应式依赖**（`cloneDeepUnref` 不下探函数体）⇒ 无 `watch` 时 doc/events 永不装定时器，症状是**首屏有内容、无报错、快照徽标还在跳，而章节进度冻结在打开那一刻**（P-9 静默假通过）。**已做变异验证：注释掉 `watch` 后用例转红（`expected 1 to be 2`），恢复即绿。** 同时删掉 §8.3 的 `useDocumentVisibility()` 一条（TanStack Query 内建 `refetchIntervalInBackground: false`）。
- [Phase 115-02, 2026-08-01]: **`refetchInterval` 全相位只允许出现在 `web/src/composables/useBlueprintLive.ts`**（源码扫描守卫锁死）——同步点 2 换 v0.19.0 推送契约时**只改这一个文件**。
- [Phase 115-02, 2026-08-01]: **UI-SPEC §10.1 chunk-at 判据订正**：可用判据是 `!ok || chunks.length === 0`（**200-空 chunks 也不可用**，后端对「无命中」与「被排除文件」刻意不可区分），⛔ 不是「非 2xx」；判据**封装进返回类型** `{chunks, usable}`，调用点不各自判。其错误体键是 `error` 不是 `detail` ⇒ `ApiError.detail` 会回落成无意义的 `'请求失败'`，⛔ 任何调用点不得回显。
- [Phase 115-02, 2026-08-01]: **UI-SPEC §3.6/§10.1 代码正文来源订正**：`chunk-at` 的 `chunks[]` **没有代码正文**，全仓也无「按 path + 行区间取源码」的读面 ⇒ `CitationCodePreview` 本相位降级为「文件路径 + 行号区间 + citation `quote` 快照」，⛔ 不引 CodeMirror、⛔ 不新增后端端点（该读面归 Phase 116）。
- [Phase 115-02, 2026-08-01]: **UI-SPEC §7.4 选区 popover 订正**：用 **`import { PopoverAnchor } from 'reka-ui'`**（已核实 `reka-ui@2.9.10` 的 `dist/index.d.ts` 与 `dist/index.js` 都导出它，**无需降级到 `PopoverTrigger` 方案**）+ 零尺寸虚拟锚点 div；⛔ 不从 `~/components/ui/popover` 导入（该 barrel 只导出 `Popover`/`PopoverContent`/`PopoverTrigger` 三个，给它加导出 = 又一处既有文件修改）。⚠️ 同时订正一条计划认知：**`@floating-ui/dom` 与 `@floating-ui/vue` 在基线就已是 `web/package.json` 的直接依赖**（非本 plan 引入），当前 `web/src/` 对其零引用；纪律照旧 ⛔ 不写 `useFloating`、⛔ 不手搓定位。
- [Phase 115-02, 2026-08-01]: **`blockText` 按「字段优先级」而非 `block.type` 分派（P-13）**：后端 `_block_text` 完全不看 type，而 schema 对 `text` 无类型约束 ⇒「`type: pseudocode` 且 `text` 非空」完全合法；按 type 分派得到的 offset **仍在合法范围内** ⇒ 不触发降级、不报错、`<mark>` 照渲，**只是圈错了字**。已上双证（fixture 用例 + 源码扫描断言函数体内 `.type` 零命中）。
- [Phase 115-02, 2026-08-01]: **服务端态一律不进 Pinia**：`doc`/`threads`/`snapshot`/`events`/`timeline`/`gate`/`list` 全走 TanStack Query（key 约定 `['blueprint', <面>, artifactId, …]`，失效走前缀匹配 `invalidateQueries({queryKey:['blueprint']})`）；`useBlueprintViewerStore` 只放 `sidebarCollapsed`/`showClosedAnnotations`/`kindFilters` 三项**用户偏好**并 `useLocalStorage` 持久化。
- [Phase 115-02, 2026-08-01]: **404 前端只有一个 i18n 键** `knowledge.blueprints.error.notFoundOrForbidden = "无权访问或该蓝图不存在"`，⛔ 不建 `notFound`/`forbidden` 第二个键（后端对「不存在」与「非成员」刻意返回逐字相同的 404，翻成两种文案即被差分枚举破防）；源码守卫同时扫竞品中文字面量。⭐ **115 review MN-02 补充**：确实需要给某一档 404 加恢复路径时，**只加动作不加话** —— 判据必须纯结构化（如「`?version=` 非空 + 正文 404 + 人审快照 200」三条 AND，⛔ 不读 `detail` 文本），文案一字不改，存在性防线因此不受影响。
- [Phase 115 review, 2026-08-01]: **前缀失效是蓝图面唯一被接受的失效口径**（MJ-01）。任何组件想收窄成若干个精确 key 之前请先数：确认门动作同时改 `gate` / `snapshot` / `doc` / `threads` / `events` **五个**查询，而 `doc` 的 key 尾段是 `versionId ?? 'current'` —— **精确匹配天然写不全**。⛔ 失效面的用例不许断言 `invalidateQueries` 的调用次数或入参（那证明不了覆盖面，正是原缺陷躲过 22 条既有用例的原因），判据一律是**缓存条目的 `isInvalidated`**。
- [Phase 115 review, 2026-08-01]: **凡后端已下发权威计数，前端一律以它为准**（MJ-03）。人审快照的 `unresolved_blocker_count` 由 confirm 闸的**同一个方法**产出 ⇒ 与「点确认会不会吃 409」天然同口径；前端派生只作快照未就绪时的占位，且判据必须与后端逐字对齐（`kind=ai_review_finding` + `severity=blocker` + `status ∈ {open, answered}`，⛔ **不看 `blocking`、不看 `anchor_status`**，且要在 `anchored` 过滤**之前**从全量 `threads` 上算）。唯一实现是 `blueprintAnnotations.isUnresolvedBlocker`，`annotationCounts` 与页面 `sectionTones` 共用它。⚠️ 取权威值用 `??` 不是 `||`：`0` 是合法且常见的权威值。
- [Phase ?]: 116-02：aresolve_project_id 是四条入口推导链的唯一收口，MCP 分支必过 _aresolve_project 换算 Space→Project（⛔ 绝不透传 space_id，否则该蓝图全部端点恒不可用且无补救入口）
- [Phase ?]: 116-02：骨架的 schema_version 取自懒 import 的 BLUEPRINT_SCHEMA_VERSION，⛔ 不复制字面量（漏写/写错会让校验器、渲染器、入图门控三条链同时静默降级到 v0）
- [Phase ?]: 116-02：feature_point id 取确定性位序 fp_{n}，⛔ 不用随机 uuid —— 随机 id 会让每次重跑都翻一个新版本，把版本历史刷成噪声
- [Phase ?]: 116-03：四入口的蓝图分支一律「早退到独立 helper」而不是 if/else 包住既有调用 —— 旧链代码路径因此一行未动（比行为断言更强的「开关关闭时逐字一致」）
- [Phase ?]: 116-03：driver 必须与 engine 一起分派，即使调用方自带 engine（answer_resume 的 engine 用调用方的、driver 恒用分派出的；沿用旧 driver 会把健康蓝图会话推成 advance_step_limit FAILED 且零异常）
- [Phase ?]: 116-03：chat 蓝图挂起判据与 blueprint_resume 的 pause 短路同源（open+blocking BlueprintThread、⛔ 不传 kind、显式 order_by），⛔ 不用对蓝图恒 False 的 ClarificationService.ahas_pending

### Pending Todos

> ⭐⭐⭐ **本表在 115-UI-REVIEW 的修复轮（2026-08-01，v0.20.0 里程碑审计前的最后一次改动）
> 又新增五条。** 该轮结论 **13 fixed / 4 skipped**（2 HIGH + 6 MEDIUM 全修，11 LOW 修 7 跳 4；
> 逐条 commit 与修前红/修后绿证据见 `.planning/milestones/v0.20.0-phases/115-ui/115-UI-REVIEW.md` 的 Fix Log）。
> ⛔ **本表原有的顺延项没有一条被该轮关掉** —— 该轮全部改动都在 `web/src/`，`server/` 零改动。
> 新增的五条是四条跳过项（UI-REVIEW **L-2** / **L-5** / **L-9** / **L-11**）加一条顺带发现
> （`ui/badge` 的 `warning` variant 绕开 `--color-warning`），⭐ **其中 L-2 与 L-5 是 UI-SPEC 自身
> 的修订项**（§11.1 的 `Separator`+`border-l` 双竖线冗余、§11.2 的指标单位），下次订正契约时一并处理。
>
> ---
>
> ⭐⭐ **本表已在 116-REVIEW 的修复轮（v0.20.0 里程碑审计前的最后一次改动）再复核一遍。**
> 该轮结论 **9 fixed / 0 skipped**（3 MAJOR + 6 MINOR 全修，逐条 commit 与证据见
> `.planning/milestones/v0.20.0-phases/116-entry/116-REVIEW.md` 的 Fix Log）。**⛔ 本表原有的顺延项没有一条被该轮
> 关掉** —— 九条 findings 与它们不相交。该轮**新增一条**顺延项（下方第 6 条：chat 回灌的挂载点
> 靠人工维持、无结构性保证）。⭐ **进里程碑审计时真正待办的是下面六条**：
> ① **同步点 2 的默认切换与三处触点升级**（含 `plan_research._map_terminal` 改 HITL 挂起，四件事同批，第 2 条）；
> ② **`redact_secrets_in_text` 不覆盖数据库连接串**（平台级，与「全仓 `error=str(exc)` 未脱敏」合并成独立清理相位，第 4 条 + 第 25 条）；
> ③ **115-MN-03 的四语义契约整体改版**（400 分支的存在性预言机，第 3 条）；
> ④ ~~**apscheduler 周期提醒接上 `blueprint_notify`**~~ —— **归档前收尾已闭**（commit `162eecd5`）；**残留**：澄清卡片的交互回调仍等同步点 1（第 19 条）；
> ⑤ **FLOW-02 的「替代建议」补结构化字段**（等机器消费方出现，第 22 条）；
> ⑥ **chat 回灌的挂载点无结构性保证**（本轮新增，第 6 条）。
> ⚠️ 另有一条**平台级观察**记在 116-07-SUMMARY §15：`RepositoryPermission` 是「任意登录用户可读任意存在的仓库」而非仓库级 ACL —— 与本表 Phase 111 的 MN-12「权限口径」一并定夺。
>
> ---
>
> ⭐⭐⭐ **本表已在里程碑审计之后的「归档前收尾」再复核一遍（2026-08-01）。** 该轮关掉的是**记账项 + 上面第 ④ 条**：
> ROADMAP 六处记账（`96127524`）、14 份 SUMMARY 的 `requirements:` frontmatter（`c2fc4036`）、
> apscheduler 周期提醒接送达收口（`162eecd5`）、GATE-01 复选框与 PARTIAL 对齐（`5fc8e9e6`）；
> 另把 `test_skills_snapshot_guard` 那条常驻环境红**就地跑绿**（初始化 `skills/` + `mcp/` 子模块，3 passed）。
> ⛔ **①②③⑤⑥ 五条顺延项没有一条被关掉**，且该轮**新增一条**：mcp npm 包缺四个本里程碑新增工具
> （子模块 checkout 后 `test_mcp_package_alignment` 首次实跑才暴露，见下方条目）。
> ⚠️ 里程碑审计经二轮核查后判 **`gaps_found`**（CLAR-03 的产品面不可达 + 三道边界接缝 G1/G3/G4），
> 归档前**必做**的 CLAR-03 closure phase 本轮**未动**，详见 [`v0.20.0-MILESTONE-AUDIT.md`](./v0.20.0-MILESTONE-AUDIT.md) §11 与 §12。
>
> ---
>
> ⭐⭐⭐⭐ **CLAR-03 closure（2026-08-02）已闭，审计 status 随之 `gaps_found` → `tech_debt`。**
> 走的是审计 §11 的**路径 (a) 补面**而非 (b) 收窄措辞：需求首句承诺的是一个具体用户能力、后端完全就绪、
> 无语义障碍 ⇒ 兑现能力比事后重定义需求更诚实。交付 = 反转 115 那条自相矛盾的源码守卫 + 补 api 层函数
> + 查看器 block 编辑面（选区浮层入口 → 编辑弹窗 → `edit-blocks` 端点），**后端零改动**。
> ⛔ **G1/G3/G4 未闭**，它们转入本表上方第 2 条的技术债 —— 判据是**可闭合性**而非严重性：三者默认开关下
> 潜伏、硬阻塞在同步点 2，审计本身也判它们不阻塞归档。三条 commit 与证据见
> [`v0.20.0-MILESTONE-AUDIT.md`](./v0.20.0-MILESTONE-AUDIT.md) §13。
>
> ---
>
> ⭐ **本表已在 116-07（Phase 116 最后一个 plan / v0.20.0 功能面收尾）复核过一遍**：本 plan 解决的条目已划掉，其余保留项均已改写成「里程碑收尾之后的独立工作项」措辞，⛔ 不再有任何一条指向某个已完成的 plan 去接。真正顺延的分别是：① **同步点 2 的默认切换与三处触点升级**（含 `plan_research._map_terminal` 改 HITL 挂起，四件事同批，见下第 2 条）、② **`redact_secrets_in_text` 不覆盖数据库连接串**（平台级，第 4 条）、③ **MN-03 的四语义契约整体改版**（400 分支的存在性预言机，第 3 条）、④ **澄清飞书卡片的交互回调 + apscheduler 周期提醒接线**（等同步点 1）、⑤ **FLOW-02 的「替代建议」补结构化字段**（本次收口新发现的过期指向：原措辞指望 113/115 顺手做，两者都已完成且都没做）。⚠️ 另有一条**平台级观察**记在 116-07-SUMMARY §15：`RepositoryPermission` 是「任意登录用户可读任意存在的仓库」而非仓库级 ACL（`permissions.py` 自承待扩展）—— 非 116-07 引入（每个仓库读面都是这口径、`chunk-at` 甚至更弱），与本表 Phase 111 的 MN-12「权限口径」一并定夺。

- ~~⭐ [Phase 115-03 顺延 · **VIEW-02 的最后一块**] 代码位置引用预览缺源码正文与行高亮~~ —— **116-07 已闭**（commit `2242d4fe` / `9babf666` / `96658922`）：新增 `GET /api/repositories/<id>/file-lines/`，实现下沉进 `services/repo_file_read.aread_repository_file` 这**唯一一份**（与 MCP `get_repository_file` 共享，含 requested + resolved 双复判的 fail-closed 排除判定）；SPA 面把「被排除 / 不存在 / 无镜像」映射成**逐字相同的 200 空**（无存在性预言机），MCP 面的 **404 `file_excluded`** 逐字未改。`CitationCodePreview` 据此渲染正文 + 行号列 + **citation 区间行高亮**，取不到正文回落 quote 快照、⛔ 不关弹窗、⛔ 不回显错误体，⛔ 零新增依赖。`REQUIREMENTS.md` 的 VIEW-02 已转 **Complete**。
- ⭐ [Phase 116 收口 · **同步点 2 之后的独立工作项**，⛔ 不属于任何已完成 plan] **蓝图默认切换尚未发生，且必须与三件事同批做**：① 四个 per-entry 开关键仍全为 `technical_plan`（翻默认 = 让编码代理拿着**未经人审**的蓝图去建分支写代码，正面违反 RELY-01）；② **三个入口的出口映射整体重做**（⚠️ **里程碑审计第二轮把这一条从「`_map_terminal` 一行」扩到了实测规模**，见 `v0.20.0-MILESTONE-AUDIT.md` §2.3 / §4.1 的 G1/G3/G4）；③ 三处触点升级与旧 `technical_plan` process 收口退役。⇒ **四件事是同一批改动**，⛔ 任何一件单独做都会造成回退。阻塞在 v0.19.0 的同步点 2 合并节奏。
  - ⭐ **第 ② 件事的实际范围（⛔ 不是一行）** —— 四个入口里只有 **chat 做对了**（`plan_research_tools._map_terminal_blueprint:474-531` 按 `blueprint_status` 分桶、`pending_review` 计成功），其余三个各要改一处，且改的**不是同一个东西**：
    - **workflow（G1，最重）**：`plan_research._maybe_suspend`（`:468-471`）用旧链模型 `ClarificationService().ahas_pending` 判待答，而蓝图链**从不写 `Clarification` 行**（写的是 `BlueprintThread`）⇒ 停在 `waiting_clarification` 的蓝图会话 `pending=None` → 不发卡 → 不建订阅 → `suspend=None` → 落 `_map_terminal` 非 DONE 分支 → `status=failed`。⇒ 要改的是**挂起判据**，`_map_terminal`（`:626`）那行 `DONE→completed` 只是同一处的第二半。
    - **feature_list（G4）**：`initiatives/services/feature_solution_service.py:485-512` 同为旧链模型，待答问题取自 `ClarificationQuestion` ⇒ 蓝图会话永久 `researching` + 空问题列表 + 该面无解阻手段。⇒ 要改的是**问题来源**。
    - **MCP（G3）**：`orchestration_delegate.py:267-276` 的 `DONE→completed` 无蓝图分支、`_load_canonical` 用 v0 渲染器；`technical_plan_service.py:440` 读 `content["execution_plan"]`，blueprint/v1 无该顶层键 ⇒ `repository_tasks` 恒 `[]`（**响应结构合法而语义为空**的静默降级）。⇒ 要改的是**主载荷映射**。
  - ⚠️ **顺序上有个比已知风险更早的坑**：真翻 `workflow` 或 `feature_list` 开关后，**第一次澄清就会撞上 G1/G4**（规格门每一次提问、确认硬门每一次停等都会触发），**早于**「未经人审的蓝图被送进 `ai_coding`」这个已登记的风险 —— 后者要等一条会话跑到终态才显形。⇒ 排期与灰度顺序按此估，⛔ 不要按「先翻开关再看终态」的直觉走。
- ⭐ [归档前收尾新发现 · **跨仓改动，⛔ 不在本里程碑范围内**] **mcp npm 包与服务端工具面漂移四个工具**：`tests/mcp_tools/test_mcp_package_alignment.py` 实测「服务端有、包缺失：`answer_blueprint_clarification` / `get_technical_blueprint` / `read_blueprint_context` / `report_blueprint_context`」。⭐ **这条守卫在 `mcp/` 子模块未 checkout 时 `pytest.skip`** ⇒ **全里程碑从未实跑过**，是归档前收尾初始化子模块时才第一次跑起来并当场转红的（与 `test_skills_snapshot_guard` 那条「守卫在本 worktree 空跑」完全同构 —— 空跑掩盖的不止一条）。四个工具**全部是本里程碑新增**（113-02 两个总线工具 + 116-06 两个澄清工具），而 `mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 是**静态白名单、未知工具直接拒绝** ⇒ **经 npm 包接入的 agent 调不到它们**：服务端端点齐备，客户端不可达。⚠️ 这削弱 GATE-01「MCP 异步澄清协议全量交付」的口径（REST / 服务端侧为真，npm 客户端侧不可达）。⇒ 修法是给 `mcp` 子模块补四个条目**并发版**，那是**另一个仓库**的改动 + 一次发布 ⛔ 不在 v0.20.0 范围内，且本 worktree 明确不动子模块指针。**在它修好之前，后端全量套件的唯一红是这一条**（判据：`git diff` 对 `server/mcp_tools` / `mcp` / `server/tests/mcp_tools` 为空 ⇒ 与本里程碑任何改动无关）
- ⭐ [Phase 115 review 跳过项 · **MN-03**] **范围闸的 400 分支对「`meta.project_id` 不合法」的那批 artifact 仍构成存在性预言机**（`blueprint_review_views._aassert_project_scope:277-278`；114 引入，115 把暴露面从 7 个端点扩到 11 个，⭐ **116 一次改到位扩到 15 个** —— 116-05 的两个飞书导出端点 +2、116-06 的两个 MCP 工具 +2，两者都是**import 复用同源实现**而不是复制第四份，理由是 MJ-03 的单一实现纪律；⛔ **暴露面变大是已知代价，四语义契约的整体改版仍是独立工作项**）。**判为设计决策而非缺陷、本轮不修**，四条理由：① **400 本身就是那四条语义之一**（`115-01-PLAN.md:126` 逐字列它为 fail-closed 标志物），并进 404 = 删掉四条里的一条；② 这是 **114 的面且 115 明文 🔒 零改动**（PLAN 四处要求 `git diff` 为空，两个新 View 刻意 import 复用而非复制）；③ 该闸跑在**成员判定之前** ⇒ 对**真成员**同样触发，400 在前端就近回显「meta.project_id 缺失或非法」（管理员据此知道去修哪份数据），改 404 则整页替换成中性文案且无恢复出口 —— **正是 115-MN-02 刚修掉的死路形状**；④ 暴露面只限 `meta.project_id` 非 UUID 的那一小批，形状正常的蓝图其「非成员 404」与「不存在 404」用**同一个常量对象**，预言机已关闭。⇒ **正确形态是连同四条语义契约一起改版**（含前端 400 档的去向与两族参数化 `test_*_fail_closed_*` 的重写），⛔ 不是单点改一行状态码。⚠️ **Phase 116 已全部完成且未动它** ⇒ 该改版明确是**里程碑收尾之后的独立工作项**，与本表 Phase 111 的 MN-12「权限口径」一并定夺。⭐ **暴露面计数在 116 收口后维持 15 个端点**：116-07 新增的 `file-lines` 走的是 `repositories` 的仓库读面权限口径（`[IsAuthenticated, RepositoryPermission]` + `aget_object_or_404`），**不经** `_aassert_project_scope` ⇒ ⛔ 不再 +1
- ⭐ [Phase 116 review 修复轮顺带发现 · **未修** · 本轮新增] **chat 阻塞 waiter 的回灌靠「逐个挂载」维持，没有结构性保证**：`_afeedback_chat_blueprint_barrier` 现在有**三个**挂载点 —— 两个容器回调 barrier（`_trigger_blueprint_research_barrier` / `_trigger_blueprint_repo_plan_barrier`）加上 116-MN-04 新挂的作答链共同出口（`blueprint_resume.aresume_after_gate_action` 收尾）。helper 自带 chat 守门 + 终态守门 + barrier 去重 ⇒ **多挂幂等安全**，本轮也补了「非 chat 入口走同一条链仍不回灌」的守门对照。但「**哪些路径通向终态**」这件事仍是人工清单：以后新增第四条通向终态的路径而忘了挂，症状又是「对话里的占位永久停住、且不抛异常」（115-MJ-02 与 116-MN-04 已经是同一形状的第二次复发）。⇒ **彻底的形态是让终态转移本身发出一个事件、回灌去订阅它**，那要动 `ConvergenceSessionEvent`（§13.2 冻结面，且与 0.19 的时间线契约耦合）⇒ **里程碑收尾之后的独立工作项**，与本表第 21 条「`areopen_stage` 未发事件」**同批定夺**（两条都要新增事件常量，同步点 2 之后一起做才不会来回改契约）
- ⭐ [Phase 115 **UI 审计**修复轮跳过项 · **未修** · UI-SPEC 修订项] **§11.1 同时要求 `Separator` 与 `border-l`，实现忠实照做 ⇒ 顶栏终审区左侧出现两条相距 8px 的平行竖线**（UI-REVIEW **L-2**）：§11.1 逐字写着「用 `Separator`（`~/components/ui/separator`）+ `ml-auto` 隔开，**容器 `pl-4 border-l border-border`**」，`BlueprintReviewActions.vue:77-78` 两者都渲染了。⇒ **这是契约自身的冗余而不是实现缺陷**，删任一条都是单方面偏离一条写死的条款 ⇒ 正确形态是**先在 §11.1 上二选一**（建议留 `border-l`，与 `pl-4` 同属一个容器）再让实现跟上，与 UI-SPEC 的下一次订正同批走。改动本身只有两行（删 `<Separator>` + 删 import），⛔ 不是「难所以不做」
- ⭐ [Phase 115 **UI 审计**修复轮跳过项 · **登记为刻意简化** · UI-SPEC 修订项] **质量面板的三项指标渲染裸数字，§11.2 写的是 `{v} 次人工编辑` / `{v} 轮`**（UI-REVIEW **L-5**）：评审给了两条并列改法，修复轮取后者「在 §11.2 上登记这处刻意简化」。理由：① metric-card 形态「标签在上、大数在下」，标签本身就是「人工编辑量」「澄清轮次」，把单位塞进数值位会变成「人工编辑量 / **12 次人工编辑**」的互相复述；② 数值位是 §14 的 Display 档（24px），「12 次人工编辑」在 `sm:grid-cols-2` 的窄格里必然换行，四格高度参差；③ 评审自己判为 LOW 并写明「metric-card 形态本身是常见范式」。⇒ **下次修订 UI-SPEC 时把 §11.2 那两格的期望值改成「标签携带单位、值为裸数字」**，⛔ 不是在 `plain()` 里补单位
- ⭐ [Phase 115 **UI 审计**修复轮跳过项 · **未修**] **7 个死 i18n 键**（UI-REVIEW **L-9**：`tabPanel.repoRoleDirect` / `tabPanel.repoRoleIndirect` / `viewer.highlightJump` / `repo.fitnessReasons` / `api.direction` / `flow.steps` / `review.disabledReadonly`）：零用户可见影响、零运行时代价，属纯清洁度项。⭐ **其中两条不是垃圾而是缺口标记**：`review.disabledReadonly`（只读态下终审按钮的禁用原因）与 `viewer.highlightJump`（命中高亮后的跳转提示）命名的都是契约描述过、实现尚未接上的 affordance —— 删掉它们等于把「这里还缺一句话」这条信息一起删掉，而**接上**它们属于新增交互、超出一条 LOW 的边界。另：`review.disabledReadonly` / `repo.fitnessReasons` 目前活在两个 spec 的 i18n fixture 里，删主文件会留下悬空 fixture。⚠️ **评审这条的证据有一处不准**：`flow.steps` 在 `InteractionFlowsSection.vue:174,201` 与 `blueprintBlocks.ts:221` 有命中 —— 那是**数据字段**访问不是 i18n 键，结论侥幸仍成立，但说明该清单是文本匹配得来的，逐条删除前需再核一遍。⇒ 与「接上那两个 affordance」一并定夺。（`mustHaves.empty` 不在此列，已由 UI-REVIEW M-5 接上消费方）
- ⭐ [Phase 115 **UI 审计**修复轮跳过项 · **未修** · 架构取舍] **`useCitationPreview` 的 `openCitation` / `loading` / `data` / `fallback` / `close` 在页面侧零消费**（UI-REVIEW **L-11**）：`[id].vue` 只解构 `open` / `citation` / `openWithSnapshot`，五个 `Citation*Preview` 子件各自取数、各自渲染 `CitationFallback.vue`。评审给的两条改法**都不是小改动**：**A「删掉未消费的分支」**会连带让 `snapshotOf` 与 `CitationFallback` 接口失去意义、composable 塌缩成 4 行包装，而它的 docstring 里那段「⭐ 兜底不留白（强制）：任何非 2xx 一律走快照兜底，⛔ 不关弹窗、⛔ 不渲染空白弹窗、⛔ 不回显后端错误体」是 **§10.1 的契约原文** —— 删掉等于删掉契约的一处落地实现；**B「把子件取数收编进来」**要把四个子件（各自不同的端点与兜底判据，`CitationCodePreview` 还是 116-07 刚做的双数据源）的取数搬进页面层，跨五个文件且会翻掉 `citationPreview.spec.ts` 里 20 余条按子件组织的用例。⇒ **正确时机是 §13.8 下一次修订**，那时一并定夺「citation 装配职责归 composable 还是归子件」，⛔ 不是单点删几个 `return` 键
- ⭐ [Phase 115 **UI 审计**修复轮顺带发现 · **未修** · 全站级] **`ui/badge` 的 `warning` variant 自己绕开了 `--color-warning` 令牌**：`components/ui/badge/index.ts:19` 写的是 `bg-amber-500/10 text-amber-700`，而 `--color-warning: hsl(38 92% 50%)` 在 `main.css:90` 此前**全仓零消费方**（UI-REVIEW L-1 修完后才有两处：蓝图历史版本条与「未经确认」横幅）。两个色值实算几乎逐位相同 ⇒ 当下无视觉后果，但「令牌定义了却没人用、各处各写调色板色」是全站级问题。⚠️ `ui/badge` 是**既有共享原语**，不在 v0.20 前端 CREATE-ONLY 边界内 ⇒ 只登记不改，与全站设计令牌收口一并定夺
- ⭐ [Phase 115 review 顺带发现 · **未修** · 平台级] **`redact_secrets_in_text` 不覆盖数据库连接串**：它只替换 `sk-ant-*` / `sk-*` / `AIza*` / `Bearer *` / PEM 私钥（`common/logging.py:362` 的 `SENSITIVE_VALUE_PATTERN`）。写 115-MJ-04 用例时**实测**异常文本里的 `postgres://user:s3cr3t@10.0.0.1:5432/friday` **原样进了日志**。不是 115 引入、也不限蓝图链 —— 全仓 `redact_secrets_in_text(str(exc))` 的调用点都吃这一口径。改 `SENSITIVE_VALUE_PATTERN` 要连带回归全部消费方 ⇒ 与本表既有的「全仓二十余处 `error=str(exc)` 未脱敏」清理项**合并成一个独立清理相位**。⚠️ **116 全相位未动它**（116-07 新增的 `services/repo_file_read.py` 与 `repositories/repo_file_views.py` 同样只是照既有口径调用它）⇒ 该缺口在 v0.20.0 收尾时**依然存在**，是里程碑之后的独立清理项
- ⭐ [Phase 115 review 定夺 · **116 接线必读**] **「best-effort」只覆盖观测，不覆盖业务**（115-MJ-04 的根因与修法）：`.cursor/rules/observability-logging.mdc` 的「失败吞掉、绝不打断主流程」约束的是**埋点代码**。把业务主体（queryset / 可见性过滤 / 行装配）一并包进 `except Exception` 返 200 空结构，会让「读失败」与「真的没数据」在 HTTP 层完全同形，前端只能把两者渲染成同一个空态。现行形态见 `blueprint_list_views.py`：`_aggregate` 失败**如实 503 + 中性 detail**（⛔ 不回显异常原文），`_log_list` 另包一层 `try/except: pass`。⚠️ **503 响应体逐字不含 `items` / `total`** —— 若把空结构也塞进去，前端 `items.length === 0` 分支又会把它读成空态（有用例钉死）。116 新增任何列表/聚合端点请照此分层
- ⭐ [Phase 115 review 定夺 · **116 接线必读**] **会话 stage 名与阶段时间线节点名不是同一套**（115-MJ-02 修复中发现，评审建议修法里未提及、直接照抄会静默失效）：后端 stage graph 是 `intake / decompose / spec_gate / route / repo_research / reroute / repo_confirmation / repo_plan / merge / ai_review`（`builtin_processes.py:850-960`），前端 `BLUEPRINT_STAGES` 是 `spec_gate / route / repo_research / **confirmation** / repo_plan / merge / ai_review / **pending_review**`。换算走 `blueprintBlocks.SESSION_STAGE_ALIASES`（`repo_confirmation → confirmation`、`reroute → route`）+ `PRE_TIMELINE_SESSION_STAGES`（`intake` / `decompose` ⇒ `-1`）。漏了别名表的症状是 `indexOf` 返 `-1`、位序推断**整条静默不生效**（确认门阶段的 `route` 继续转圈）。⛔ 不要「统一命名」：两侧各有既有消费方。另一条实证：`current_stage` **不会**取 `__done__` —— `transition` 在 `target == STAGE_DONE` 时保留 `from_stage`（`convergence_session_service.py:172-173`），所以 confirmed 蓝图的 `current_stage` 是 `ai_review`
- ~~⭐ [Phase 115-07 提出 · **既有后端缺口**] **`blueprint-gate/` 八个端点里有七个没有项目范围闸**~~ —— **116-01 已闭**（commit `dd8c0f74`）：新增 `_aassert_gate_scope`（**全文件唯一一份授权判据**），五个改快照动作经 `_aapply_action` 一处挂闸、`snapshot` / `rejected-to-boundary` / `upgrade-research` 三个直挂 ⇒ 八端点全覆盖。⭐ 用**更严变体**：「读不到 `meta.project_id`」与「非项目成员」回**同一个中性 404 常量对象**（`_GATE_NOT_OPEN_DETAIL`）⇒ **零新增存在性暴露面**，由 `assert a.json() == b.json()` 背书；⛔ 刻意**不 import** review 链那个带 400 分支的整体闸（见下面 MN-03 那条）。三条破坏性写（`confirm` / `remove-repo` / `add-repo`）另有「非成员调用后 DB 一字未动」的用例。原文存档如下 ——
- [原文存档] **`blueprint-gate/` 八个端点里有七个没有项目范围闸**：实读 `server/delivery/api/blueprint_gate_views.py`，范围闸 helper `_ablueprint_project_id`（`:511`）**只在 `BlueprintRejectedToBoundaryView`（`:385`）里被调用过一次**，其余七个 View 只有 `IsAuthenticated`。⇒ 该链的 404 混合了「门未开启」（绝大多数蓝图绝大多数时间的正常态）/「artifact 不存在」/「无蓝图编排会话」三种语义，**状态码不携带任何权限信息**。115-07 的前端已按 P-10 处理（渲染条件只有「200 与否」一条，⛔ 不进错误分档、不据它推断权限，三种 404 行为一致有并列用例），但**后端的闸本身仍缺**。本相位边界是「只加读面」不修它 ⇒ 顺延为独立工作项（与 Phase 111 的 MN-12「权限口径」一并定夺）
- ~~⭐ [Phase 115-07 提出 · 后端小缺口] **`confirm/` 的 409 未下发 `blocked_reason`**~~ —— **116-01 已闭**（commit `dd8c0f74`）：两处 409 的 body 各补一个 `blocked_reason` 键（未决澄清档为字面量 `"pending_clarification"`，`alock` 拒锁档原样透传 `lock["reason"]`），**前端零改动**即让 115-07 已实现且已有用例的「一键跳未决线程」在生产生效（`gatePanel.spec.ts:577` / `:591` 复跑 22 passed）。原文存档如下 ——
- [原文存档] **`confirm/` 的 409 未下发 `blocked_reason`**：`blueprint_gate_views.py:240`（未决阻塞澄清）与 `:249`（`alock` 拒绝落锁）两处 409 的**响应体里只有 `detail`**，`blocked_reason` 只活在 service 返回值里被视图消费掉了。前端已按机器可读键实现两档分流（`pending_clarification` ⇒ 一键跳侧栏未决组；其余 ⇒ 回显 `detail` + 刷新重试），⛔ **坚持不按中文 `detail` 分支**（那等于把后端文案当协议）。⇒ 后端在这两处 409 的 body 里补一个 `blocked_reason` 键即可让「一键跳未决线程」这档在生产生效；在此之前该档功能降级但语义正确
- ~~[Phase 115-07 重申 · SC-4 范围收窄] **关联段的「引用了本蓝图 / 关联知识」顺延 Phase 116 的知识图谱物化**（115-05 已首次登记，115-07 相位收口时重申）：当前关联段只呈现本蓝图**引出**的引用与关联项目，反向「被谁引用」需要图谱物化后才有数据源~~ —— **116-04 已闭**（commit `dd9bb454` / `dc606e3e` / `dd14e876`）：数据源已就位（`knowledge/sources/blueprint.py` 把 citations 物化成 `REFERENCES` 边），查询链的三层断点（view / service / 前端都不透传 `relations`，而 `_DEFAULT_RELATIONS` 不含 `REFERENCES`）已纯追加打通，关联段补上「被哪些方案 / 知识引用」（`direction:'in'`）与「关联知识」（`direction:'out'`）两块
- [Phase 111 review 跳过项] **MN-06**：需新增 migration 才能修（详见 `.planning/milestones/v0.20.0-phases/111-schema/111-REVIEW.md` Fix Log）——留到 112/113 有 migration 批次时一并做，避免为单条 MINOR 单独起 migration
- ~~[Phase 111 review 跳过项] **MN-12**：属权限口径决策（非实现缺陷），与 115 前端权限呈现一并定夺~~ —— **116-01 结案**。定夺内容：115 已定「**前端不自建权限判断、一律以后端状态码为准；项目成员即全权**」（`blueprint-gate/` 的 404 是正常态，⛔ 不据它推断权限）；116-01 给 gate 链补齐范围闸后，蓝图**全部读写面 20 + 8 = 28 个端点的授权口径统一**为「superuser 直通 / 蓝图 `meta.project_id` 的项目成员放行 / 其余中性 404」。⚠️ **115-MN-03 的存在性预言机整体改版仍是独立工作项**：116-01 用的是**更严变体**（gate 链八端点的两个失败分支回同一中性 404），`_aassert_project_scope` 的 400 分支**一行未动、暴露面未扩大**；那条四语义契约的整体改版（含前端 400 档去向与两族参数化用例重写）仍待独立处理
- [Phase 112 review 跳过项] **MN-06**：删除/启用皆属零行为收益的 churn（理由见 `.planning/milestones/v0.20.0-phases/112-1/112-REVIEW.md` Fix Log）；MJ-06 的 `match_kind` 证据字段一并保留
- [Phase 113 review 跳过项] **MN-09 重试计数无服务端权威来源**：两条建议修法均不可取——改 `session_id` 前缀撞冻结面 `research_adapter.py`；改走 `last_output` 是安全倒退（runner 可篡改 → 无界重试）。现状影响有界（卡住时人可见可续），**正解是给服务端加权威计数列**，另起小相位处理（见 `.planning/milestones/v0.20.0-phases/113-2/113-REVIEW.md` Fix Log）
- ~~[Phase 114-04 延后项] `blueprint_lifecycle_service.py:358` 的 `blueprint_transition_event_persist_failed` 缺 `category`/`component`~~ —— **114-05 已修**（commit `6f91f778`，补 `category="caller"` + `component="blueprint_lifecycle"`，并把异常文本改走 `redact_secrets_in_text`）。⚠️ 留一个可再议点：该事件与同函数内的转移事件家族（`component="process_runtime"`）不同组，若 115 观测面希望转移家族共用一个 component，改这一处即可（零行为影响）
- ~~[Phase 114-05 有意边界] **提醒只到「记事件 + 写周期锚点」为止，渠道投递未实现**~~ —— **116-06 已闭（首次送达）**（commit `0bae932b`）：新增 `services/process_runtime/blueprint_notify.anotify_blueprint_clarification` —— 蓝图澄清飞书卡片送达的**唯一收口**，收件人口径与本条描述**逐字一致**（`BlueprintReviewer` ∪ 蓝图会话发起人，反查带 `process_type="technical_blueprint"` 过滤），题面过 `redact_secrets_in_text`、整段 best-effort、⛔ 不依赖 `ExecutionContext`；**唯一接线点**是 `blueprint_spec_gate._open_clarification`（开完 blocking 线程之后），由一条扫全仓的用例背书「⛔ 不在四个入口各接一次」。⭐ **模块 docstring 写明「同步点 1 之后换 107 的送达设施时只改这一个文件」**。~~⚠️ **残留半条**：114-05 那条 apscheduler **周期提醒**仍只写锚点、未调该收口~~ —— **归档前收尾已闭**（commit `162eecd5`）：`aremind_clarification_threads` 现在在**锚点写回成功之后**按 artifact 分组调该收口推卡片。⭐ 三条落地要点：① **顺序不可换**（锚点是「同周期不重复轰炸」的唯一依据，先发卡再写锚点会让一次 IM 抖动导致每个 tick 重发）；② **一份蓝图一张卡**（同时到期 N 条线程只推一张，N 张本身就是轰炸）；③ 题面优先取 `BlueprintThread.options`（规格门 `_open_clarification` 把整份 `questions` 原样存了进去）、否则回落首条消息正文。整段 best-effort ⇒ 发卡失败不改恒定四键计数、不回滚锚点。新增 4 条用例，前 3 条经实跑变异（回退接线调用）转红后恢复。⚠️ **实际不止「一行调用」**（原估算偏小）。⛔ 送达收口的接线点白名单随之从 1 处扩到 2 处（`test_blueprint_notify` 的守卫已同步改为「首次送达 + 周期重推」两条逐字路径，各自仍只允许一个 import + 一处调用）。⚠️ 另：卡片当前是**通知形态**（`action="blueprint_clarify_answer"` 未注册 handler，`CardCallbackView` 无匹配即优雅返回、⛔ 不抢占既有路由也不 5xx），作答走 REST 人审端点 / MCP `answer_blueprint_clarification` / 蓝图查看器三条已实装通道；⭐ **接交互回调等同步点 1**（换 107 的送达设施是同一批改动），届时**仍只改 `blueprint_notify.py` 那一个文件**。原文存档如下 ——
  > [Phase 114-05 有意边界] 提醒只到「记事件 + 写周期锚点」为止，渠道投递未实现：这是 PLAN 的有意边界（飞书卡片重推/站内通知归 115/116 通知面）。当前运维能从 `blueprint_clarification_reminded` 事件看到「谁该被提醒、几个人、哪条线程」，但**用户收不到实际通知** ⇒ 115/116 接上通知面之前，CLAR-04 的用户可感知价值只兑现一半。

- ~~[Phase 114-03 环境项] **`tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 在本 worktree 恒红**~~ —— **归档前收尾已闭**：在本 worktree **初始化 `skills/` 与 `mcp/` 两个子模块**后就地复跑，**3 passed**。`SKILL_FILES` 非空 ⇒ `test_skill_tool_references_subset_of_snapshot` **不再空跑**，本里程碑新增的两个 MCP 工具与 `answer` 动词前缀均已过该守卫的文档面（审计 §6.3 观察 3 的「文档面从未实跑过」由此消解）。⇒ 后端全量的那条常驻环境红**已消失**。
- ⛔ ⭐ [**归档前收尾新发现** · **未修** · 跨仓] **mcp npm 包与服务端工具面漂移四个工具，经 npm 包接入的 agent 调不到它们**：`tests/mcp_tools/test_mcp_package_alignment.py` 在 `mcp/` 子模块未 checkout 时 `pytest.skip` ⇒ **全里程碑从未实跑过**；上面那次子模块初始化让它首次跑起来，立刻报红 —— `服务端有、包缺失：['answer_blueprint_clarification', 'get_technical_blueprint', 'read_blueprint_context', 'report_blueprint_context']`，**四个全是本里程碑新增**（113-02 的两个上下文总线工具 + 116-06 的两个澄清工具）。`mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 是**静态白名单、未知工具直接拒绝** ⇒ 服务端端点齐备但客户端不可达。⚠️ **这削弱 GATE-01「MCP 异步澄清协议全量交付」的口径**（那一半在服务端为真、在 npm 客户端为假）。修法是给 `mcp` 子模块补四个条目并发版 ⇒ **跨仓改动、独立工作项**（本 worktree 明确不动子模块指针）。⭐ 与「skills 守卫在此空跑」完全同构：**守卫空跑掩盖的不止一条**，合并/CI 侧应确保这两条守卫都在有子模块的环境里跑
- ⭐ [Phase 112 残留 · **里程碑收尾之后的独立工作项**，⛔ 不属于任何已完成 plan] **FLOW-02 的「替代建议」无结构化字段**：fitness 的 `reasons` 承载了理由，但 unsuitable 时的「建议改去哪个仓」未落成结构化字段（当前混在自由文本里）。⚠️ **原措辞「113 若需…否则留到 115 前端呈现时定夺」已过期** —— 113 与 115 都已完成且都未补该字段（115 的确认门 UI 直接渲染自由文本，可读但不可机器消费）。⇒ FLOW-02 的**需求文本本身不要求结构化**（只要求「+ 替代建议」），故 Traceability 判 Complete；补 schema 字段是**机器消费方出现时**才做的增强，与「不合适仓自动回主 agent 重路由」的既有能力无关
- ~~[Phase 114 review 跳过项] **MN-05：`blueprint_quality` 三项 DB 统计零消费方**~~ —— **115-04 已闭**（commit `4ce29602`）：`BlueprintQualityPanel.vue` 是这三项统计的**唯一消费面**，`null` 渲染「暂无数据」**绝不显示 0**，三态并列用例已由变异（把空值合并成零）证明「`null` 用例转红而 `0` 用例仍绿」。评审原建议的「接进 `evaluate_blueprint_golden`」不可行的判断维持不变（golden case 无 `artifact_id`）。✅ **剩余接线项已由 115-06 完成**（commit `ee1e8dce`）：页面按 `current_state_analysis` / `repo_associations` / `impact_analysis` 三处是否至少一处非空派生 `hasKeyConclusions` 并传入，「空文档满分」的口径陷阱旁注（`quality.noKeyConclusions`）现已可见。原始记录如下 ——
- [Phase 114 review 跳过项 · 原文存档] **MN-05：`blueprint_quality` 三项 DB 统计（`ai_rejection_rate` / `human_edit_volume` / `clarification_rounds`）零消费方** —— ⚠️ **115/116 必读**：SUMMARY 的「度量面闭环」只兑现到「口径已实装、可被调用」，**全仓无任何消费点**（既不进离线评估也不进 API / 大盘）。评审建议的「接进 `evaluate_blueprint_golden`」经核实**不可行**：golden case 是静态 JSON fixture（顶层只有 `name/description/blueprint/expected`，**无 `artifact_id`**，DB 里也不存在对应 artifact），而三项统计全部按 `artifact_id` 查 delivery models，且该 command 明写「全程无 DB 写、天然过 `--disable-socket`」——硬接只会得到三个恒 `None` 的键，比不接更糟。**正确消费面是 115/116 的运行时大盘 / 人审面板**（有真实 artifact_id 在手）。已在 `blueprint_quality.py` 的 DB 统计节源码处同步登记。详见 `.planning/milestones/v0.20.0-phases/114-ai/114-REVIEW.md` Fix Log
- [Phase 114 review 顺延项] **全仓仍有二十余处 `error=str(exc)` 未脱敏**（`crawl_service` / `work_item_service` / `coding_completion` / `comment_event_service` / `release_service` 等，均早于本纪律）。114 已把**蓝图链九个模块**收口并加了 AST 守卫 `tests/delivery/test_blueprint_log_redaction_guard.py`（新增蓝图模块请加进它的 `_SCANNED_MODULES`）。全仓收口另起独立清理，并可考虑把该守卫的扫描面逐步扩到全仓
- ~~[Phase 115-02 范围收窄 · P-5] ⭐ **SC-4 的 `associations` 段本相位只做「本蓝图引用了」+「关联项目」**，**「引用了本蓝图 / 关联知识」顺延 Phase 116 的知识图谱物化**。理由：`knowledgeApi.getRelated` / `getArtifactAssociations` 查的是 `initiatives.Artifact` 投影的 KnowledgeEntity（`server/knowledge/artifact_associations.py:75`），而蓝图存在 `delivery.Artifact` ⇒ 拿蓝图 id 去调**必然 404/空**。`web/src/api/blueprints.ts` 与本相位任何文件对这两个符号**零调用**（已加验收断言）。116 做图谱物化时一并补这两块呈现。~~ —— **116-04 已闭**（含「蓝图 citations 未物化成 `KnowledgeEdge`」这层）：citations 已按九种 `source_type` 换算成 `REFERENCES` 边（同目标聚合成一条、目标不存在的先过滤并按 `source_type` 计数）。⭐ 结论要点：**`getArtifactAssociations` 对 `delivery.Artifact` 必然落空这条判断依然成立** —— 116 改走 `getRelated` + REFERENCES 边这条**另一条链**，⛔ 不是把它修好了；那条 `toHaveBeenCalledTimes(0)` 断言原样保留。
- [Phase 115-02 环境项] **pnpm 10.34.2 会漂移 `web/pnpm-workspace.yaml`**：在本 worktree 跑**任何** `pnpm` 命令（含 `pnpm exec vitest`）都会自动向 `catalogs` 回填缺失条目（`three` / `mermaid` / `wordcloud` / `3d-force-graph` / `medium-zoom` / `@types/*`）。⭐ **115-03 起每个前端 plan 跑完门之后请 `git status` 检查并 `git checkout -- web/pnpm-workspace.yaml` 还原**，否则会被边界核算误判为「新增依赖」。⚠️ **116-REVIEW 修复轮再次复现**（回填了 `@types/three` / `@types/wordcloud` / `3d-force-graph` 三条，已还原、未提交）⇒ 该现象**在里程碑收尾时依然存在**，审计核算依赖变更时请以 `git diff` 而非工作区状态为准。
- [Phase 115-02 验收脚本缺陷（非实现缺陷）] **计划里 404 竞品键的验收正则 `/notFound$|notExist|forbidden/i` 会误伤获批键本身**——带 `/i` 且 `forbidden` 是子串匹配 ⇒ 把唯一获批的 `notFoundOrForbidden` 判为竞品，脚本恒抛错。修正判据：**先排除获批键再扫竞品**。已用修正版复跑通过（实现无缺陷）。后续 plan 若复用该脚本请一并改正。
- ~~[Phase 115-03 回报项] 仓库章程四分区的小标题缺 i18n 键（4 个）~~ —— **115-06 已闭**（commit `38f6eb35`）：`repo.charterPositioning` / `charterOwnedDomains` / `charterBoundaries` / `charterPlacement` 已补，`CitationCharterPreview` 的 `sections` 计算加回 `label` 并渲染一行 `<p>`，`data-charter-section` 身份属性原样保留。
- [Phase 115-03 环境事实] **happy-dom 20.10.2 的 `createTreeWalker(SHOW_TEXT)` 会把注释节点一并返回**（Vue 的 `<!--v-if-->` 等，`length` 为 0）。**对生产逻辑无影响**（`offsetInFlatText` 累加 0，offset 结果正确；真实浏览器的 `SHOW_TEXT` 本就不含注释），但**测试里不能用「取第一个文本节点」**——会拿到长度 0 的节点、`range.setEnd` 直接 `IndexSizeError`。115-04/05 写选区相关用例时请按内容找文本节点（范式见 `__tests__/BlueprintBlock.spec.ts` 的 `textNodeWith`）。⛔ 不要为此改 `collectTextNodes`（生产行为正确）。
- [Phase 115-03 视觉待定] **越界降级「整块左色条」的色相目前落在下边框而非左边**：`annotationClass()` 产出的是 `border-bottom` + `bg-*` 字面量类，而运行期拼出来的任意值类名 Tailwind 不会生成规则 ⇒ 无法把它改写成 `border-left`。当前实现是「中性 2px 左描边 + 色相底纹与下边框」，降级身份由 `data-testid="blueprint-block-degraded"` 与计数角标承载。若 UAT 判定需要真正的左侧色条，正解是给 `annotationTokens.ts` 增一个 `annotationBarClass()` 字面量表，⛔ 不在组件里补颜色。
- ~~[Phase 115-04 回报项] 写路径与决策面缺 5 个 i18n 键~~ —— **115-06 已闭**（commit `38f6eb35`）：`review.disabledReason`（带 `{status}` 插值）/ `review.rejectKeepAnchor` / `quality.noKeyConclusions` / `thread.draftCancel` / `diff.mustHavesExcluded` 已补并全部换回；⭐ **草稿卡补上了可见的「取消」按钮**（`Esc` 放弃草稿仍保留），115-04 的「草稿卡缺可见取消」UAT 项随之关闭。⚠️ `reviewActions.spec.ts` 的手写最小 i18n 键树同步补了两个键 —— 那类 spec 不 import `zh-CN.json`，缺键会让断言读到键名。
- [Phase 115-04 契约扩展 · 115-06 接线注意] **线程侧栏与线程卡各多两个 prop**：越界降级判据需要**块正文**才能算（`isValidAnchor(anchor, blockText.length)`），线程层拿不到 ⇒ 由持有正文的页面算好，经 `degradedThreadIds`（侧栏）/ `degraded`（卡）传入；草稿卡走 `draft` prop + `create-comment` / `cancel-comment` 两个 emit。`BlueprintCommentDraft` 是 115-03 `SelectionPayload` 的**结构子集**，115-06 可直接把 `SelectionPayload` 传进来。
- ~~[Phase 115-04 视觉待定 · UAT] 草稿卡没有可见的「取消」按钮~~ —— **115-06 已闭**：`thread.draftCancel` 已补，草稿卡恢复可见「取消」按钮（`data-testid="blueprint-thread-draft-cancel"`），焦点在草稿卡内按 `Esc` 放弃的路径同时保留。
- ~~[Phase 115-05 回报项] 段渲染面缺 21 个 i18n 键（33 个键）~~ —— **115-06 已闭**（commit `38f6eb35`）：33 个键全补并逐处换回，**优先换回 ③ 档**（`intent` / finding `kind` / `change_type` / `actor` / `cross_team` / `reversible=false` / `availability` 未标注 —— 这一档此前在界面上直接印英文枚举值）；**三处跨子树借用已全部换回本子树**（关联能力 → `repo.capabilitiesUsed`、引用文档 → `associations.citedByThis`、关联项目 → `associations.relatedProject`）。四档枚举一律保留「未知值回落 schema 原样 token」的分支，`data-*` 身份属性全部原样保留（既有用例按它们定位，零改动）。⚠️ `sections.spec.ts` 的手写 i18n 键树同步补键，并改正了一处硬编码旧降级文案的断言。
- ~~[Phase 115-05 范围收窄落地 · 承接 115-02 P-5] ⭐ **SC-4 的收窄已在 UI 侧兑现并有用例背书**：`BlueprintAssociationsSection.vue` 只做「本蓝图引用了」（`content.citations` 按 `source_type` 分组统计 + 可点 chip，零端点）+「关联项目」（`RouterLink` 到 `/projects/{projectId}`）；两个必然 404 的反查端点**源码零命中**且有 `toHaveBeenCalledTimes(0)` 的用例。**反向「被谁引用 / 关联知识」顺延 Phase 116 的知识图谱物化**，届时在该组件里补两块即可（现有两块无需重构）。⛔ 执行期不得再把 SC-4 理解成「双向可查」——ROADMAP 的 SC-4 原文与 REQUIREMENTS 的 VIEW-04（PARTIAL）已在 plan 阶段对账完毕。~~ —— **116-04 已闭**，且当年的预判被证实：**现有两块确实无需重构**，只是纯追加了两块与一个 `knowledgeEntityId` prop。`sections.spec.ts` 的 `9a` 拆成三条（`getRelated` 转真实入参断言含 `relations:['REFERENCES']` / `maxHops:1`；`getArtifactAssociations` 的 `toHaveBeenCalledTimes(0)` **原样保留**；新增「`knowledgeEntityId` 为空 ⇒ 零请求」）。VIEW-04 由 PARTIAL 转 Complete。
- [Phase 115-05 契约扩展 · 115-06 接线注意] **十段容器必须由页面无条件渲染**（P-4）：段内空态已由组件层处理（规则表见 `115-05-SUMMARY.md` §7，其中 `must_haves` 三块同空时**刻意不出空态卡**），页面**不要**再套一层 `v-if` 判空——那正是让 `AnchorNavLayout` 的 mount-only observer 观察不到、左栏高亮静默失效的写法（已有用例覆盖「九段空数据仍渲染内容区」这半边）。另需接住两个跨段跳转锚点：`fp-<feature_point_id>`（需求规格段功能点卡）与 `api-<contract_id>`（API 契约卡根元素），`goto-anchor` 载荷**已是完整 DOM id**，页面只做 88px 偏移 + 2s ring 高亮，⛔ 不要再拼一次前缀。
- [Phase 115-05 定夺] **`decision_log` 的 `open-thread` 语义 = 「跳转到该决策对应的线程」**（⛔ 不是「在该段发起批注」）：条目带 `thread_id` 才渲染入口按钮（`data-testid="blueprint-decision-goto-thread"`），不带则不渲染。115-06 接住后应完成「开侧栏 → 设 `activeThreadId` → 正文滚动」，与 `BlueprintBlockedDialog` 的 `goto-thread` 同一套处理。
- [Phase 115-06 订正登记 · P-4 的两处外延] ⭐ **UI-SPEC §6.9 与 §9.2 各订正一处**：① `must_haves` / `decision_log` 无内容时**段容器与导航项仍渲染**，只是段内不出内容；② **diff 视图下十段容器仍在**（段内内容收起、diff 面板渲染在段序列之前），⛔ 不「替换正文区」。两处同源：那个锚点布局件只在 `onMounted` 按 `sections` 逐个 `getElementById`，任何条件渲染都会让 observer 挂不上，且**退出 diff 后不会恢复**（页面无重挂载）。⭐ 后续任何人想给这十段加 `v-if` 之前，请先跑 `blueprintViewer.spec` 用例 1。
- [Phase 115-06 环境项 · ⭐ 后续前端 plan 必读] **`pnpm build` 会重写 `web/src/components.d.ts` 并顺带裁掉一批与本次无关的既有条目**（本次是 29 条懒加载件）。直接提交等于在生成物里夹带删除，会给别人的分支制造无意义冲突。做法：`git checkout` 还原后**按字典序手工插入自己的那几行**（本次 +4/−0）。`src/typed-router.d.ts` 无此问题（+15/−0，纯追加）。⚠️ **116-REVIEW 修复轮再次复现**（本次是 **纯删除 29 条、零新增**，因为该轮没有新建任何组件 ⇒ 直接 `git checkout` 还原即可，无需手工追加）。
- [Phase 115-06 缺件登记] **仓内没有 `ui/alert` 组件**（只有语义完全不同的 `alert-dialog`）。查看器的历史版本与只读提示改用带语义描边的 `div` + `role="status"`（`data-testid` 分别是 `blueprint-history-notice` / `blueprint-readonly-notice`）。⛔ 115-06 未新建 `ui/alert` —— 那是通用设计系统件，形态要与 DESIGN 对齐，超出单个 plan 的边界。若 116 有第三处需要，再按 DESIGN 统一补。
- [Phase 115-06 验收脚本缺陷（非实现缺陷）] **「组件目录内那个锚点布局件名零命中」这条自 115-05 落地起就已不可能满足**：`MustHavesSection` / `CurrentStateSection` / `RequirementSpecSection` 三个 docstring 在解释「为什么段容器要由页面无条件渲染」时各写了一次它的名字。该条的真实意图是「⛔ 任何组件都不得**包**它」，形状正确的判据是 `rg "<AnchorNavLayout" web/src/components/blueprint/` **零命中**（已实测）。唯一的非注释引用是 `BlueprintSectionNav` 的 `import type { NavSection }` —— 那是类型依赖而非组合。
- [Phase 115-05 定夺 · 闭 Phase 112 残留] **`fitness.verdict === 'unsuitable'` 时的「替代建议」按 `fitness.reasons` 自由文本原样展示**，⛔ 不补 schema 字段、⛔ 不做结构化解析（UI-SPEC §0.2 判定 6）。前端只是呈现方，为了呈现去改一份已锁定的后端 schema 不划算；真要结构化应在产出侧（114 链路）做。这同时定夺了本表原先登记的「Phase 112 残留 PARTIAL / FLOW-02：替代建议无结构化字段」。
- [Phase 114 review 可再议] **`ConvergenceSessionService.areopen_stage` 未发 `ConvergenceSessionEvent`**：新事件类型属纯追加、本可做，但 §13.2 把既有事件类型/字段定为 consume-only，且复位已由 `convergence_session_reopened` 结构化日志 + `blueprint_review_rejected` 双重可归因。若 115 的事件时间线希望「人审驳回导致的会话复位」在时间线上可见，需新增一个 `blueprint.review.session_reopened` 事件常量（同步点 2 后与 0.19 的时间线契约一并定）

### Blockers/Concerns

- 同步点 1/2 依赖 v0.19.0 的 107 / 109+110 合并主干节奏；116 的入口切换在同步点 2 前不可执行（可先做 MCP 协议与导出的后端部分）。
- `.planning/` 三文件（ROADMAP/REQUIREMENTS/STATE）与 0.19 分支在里程碑收尾合并时预期机械冲突：v0.19.0 段以对方为准、v0.20.0 段以本分支为准、STATE 以存活里程碑为准。

### 共享面改动备注（Phase 113-06，同步点需关注）

- **`process_runtime/engine.py`**（非 §13.2 冻结面，但与旧 `technical_plan` process 共享）：修掉「每次不产版本的转移都无条件把 `session.current_artifact_version` 透传成 NULL」的缺陷——原行为会让阶段 2/3 永远找不到基线版本，且因全链 best-effort 吞异常而完全静默。该修复对两条链都是严格改进，但**属共享代码**：与 v0.19.0 合并时需确认无冲突，并在 rebase 后复跑旧链回归。
- 另修：无阻塞线程的 `needs_clarification` self-loop 会被续驱推到 `max_steps` 落 FAILED（已加出口）。

### 安全边界备注（Phase 113-02）

- `ConvergenceSession` **无 project FK**：容器 MCP 总线读写的「项目成员」闸只能 best-effort 反查，**会话未绑项目时不叠加成员校验**。此时硬防线是第①道（session 的 `AgentSession.user` == task token owner，空值 fail-closed）+ 第②道（`process_type == technical_blueprint`）+ 第③道（条目 session 一致），三道均经变异验证可触发 403。若后续要求「未绑项目会话也必须过成员闸」，需先给 ConvergenceSession 补项目关联——留待 114/116 评估。

## Session Continuity

Last session: 2026-08-02T00:55:00.000Z
Next step: ✅ **v0.20.0 已归档**（`$gsd-complete-milestone`）—— ROADMAP 折叠、REQUIREMENTS/ROADMAP/AUDIT 与六个相位目录已进 `.planning/milestones/`，MILESTONES.md 与 PROJECT.md 已回写。**下一步不是开新里程碑**，是合并 `milestone/v0.19.0-plan-trust`（见 Operator Next Steps）。

⚠️ **归档时的两条口径记录**（供后续对账）：① **未打 git tag** —— 本仓 tag 是发布轨（最新 `v0.18.0`），与 GSD 里程碑号不同轨，且 v0.15.0/v0.16.x/v0.17.0 三个里程碑同样无 tag；在未合并的并行分支上打发布号 tag 会制造假发布点。② **`REQUIREMENTS.md` 未整份删除**，只切走 v0.20.0 段 —— v0.19.0 仍是在建里程碑且该文件是其 24 条需求的唯一定义处。
⚠️ **审计核算改动面时的两个已知环境噪声**：`pnpm build` 重写 `web/src/components.d.ts`、`pnpm` 回填 `web/pnpm-workspace.yaml` 的 catalog ⇒ **请以 `git diff` 为准，⛔ 不要按工作区状态判「新增依赖」**。
⚠️ **后端全量的唯一红是 `test_mcp_package_alignment`**（mcp npm 包缺四个本里程碑新增工具）—— 跨仓、真实缺口、不在 v0.20.0 范围内，见 Pending Todos。

Resume file: None

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 115 P01 | 90m | 3 tasks | 7 files |
| Phase 115 P02 | ~180m | 3 tasks | 23 files（+4372/−1），新增 150 例前端用例 |
| Phase 115 P03 | ~60m | 3 tasks | 11 files 新建 + 1 生成物，新增 43 例前端用例 |
| Phase 115 P04 | ~90m | 3 tasks | 14 files 新建 + 1 生成物（+2970），新增 58 例前端用例，六条变异验证 |
| Phase 115 P05 | ~90m | 3 tasks | 16 files 新建 + 1 生成物，新增 37 例前端用例，四条变异验证 |
| Phase 115 P06 | ~150m | 3 tasks | 11 files 新建 + 8 files 改（i18n 交接 + 两处纯追加），新增 16 例前端用例，一条变异验证 |
| Phase 116-entry P02 | ~2h | 3 tasks | 5 files |
| Phase 116-entry P03 | ~3h | 3 tasks | 16 files |
| Phase 116-entry P04 | ~2.5h | 3 tasks | 17 files（3 新建 + 14 改），新增 30 例后端用例 + 2 例前端用例，一条变异验证 |
