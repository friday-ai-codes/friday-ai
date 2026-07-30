# Phase 114: 审查与澄清收敛 - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权）

<domain>
## Phase Boundary

蓝图到达人审前先过独立 AI 对抗审查，findings 化为划线线程并有界收敛；澄清答案回灌产新版本、决策物化进文档；pending 超时语义与人工 block 编辑链路闭环。

**只做审查与澄清收敛 + 人工编辑后端**：不做前端查看器与批注 UI（115）、不做入口收编与飞书导出（116）。人审的**操作端点**属本相位（通过/驳回经 service 收口），其**界面呈现**属 115。

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §5.5（AI 审查七类规则与有界修订）/§6.1（线程模型）/§6.2（线程生命周期与重锚定、pending 超时）/§6.3（人工 block 编辑）/§3.13（decision_log）/§13.2（冻结纪律）。

可消费上游：111 的 `blueprint_schema`（validate/iter_blocks/diff）、`blueprint_anchor`（重锚定）、`blueprint_quality`（覆盖率）、`BlueprintLifecycleService`（11 态守卫）、`BlueprintThread/Message/Reviewer`；112 的确认门锁定快照（`confirmed_at_gate`/`responsibility`）与 `RepoCharter`；113 的 `blueprint_merge` 装配面、九个 stage 的 `technical_blueprint` graph、`BlueprintContextService`、`blueprint_resume` 的 stage→status 映射。

</domain>

<decisions>
## Implementation Decisions

### AI 审查代理与七类规则
- 新建 `server/services/process_runtime/blueprint_review.py` + 追加第 10 个 stage `ai_review`（`builtin_processes.py` 只加注册与新 handler `_h_bp_ai_review`）；审查代理**独立 fresh context**，不与起草/融合共享会话（降相关性偏差）
- **六类机械规则纯函数化**（不交给 LLM，保证可复现与可证伪）：① schema 完整性（`validate_blueprint`）② 引用覆盖（`blueprint_quality`：关键结论必带 citations，无引用的事实性断言 WARNING、关键结论无引用 BLOCKER）③ 角色一致性（每个 direct 仓 ≥1 实现项；indirect 仓 `capabilities_used` 被某实现项或 API 的 data_source 引用；改动 indirect 仓即 BLOCKER）④ API 闭环（`interaction_flows.steps.api_ref` 必指向已声明契约；consumed 的 `data_source.availability=needs_support` 时 `support_repository_id` 必须出现在 repo_associations）⑤ 禁令（不得出现以周为单位排期、不得引入 out_of_scope、不得与 constraints 冲突）⑥ 章程边界（direct 仓实现项违背该仓 `RepoCharter.boundaries` 或落在 `evolution=maintenance_only` 仓，必须有对应 decision_log 支撑，否则 BLOCKER）
- **仅 goal-backward 一类走 LLM**：对每个 feature_point 逆向核对 acceptance_criteria 是否被实现项与 test_strategy 覆盖、`must_haves.truths` 是否有实现项支撑、`key_links` 两端是否都存在；`call_source` 用 111 已注册的 `blueprint_ai_review`
- findings 载体复用 `BlueprintThread(kind=ai_review_finding, severity∈{blocker,warning,info}, blocking)`，锚定到 block（section_path 走 111 `iter_blocks` 的「点分 + [标识]」约定）
- **`open_thread` 加 `severity` 形参（按调研定夺）**：`BlueprintThread.severity` 字段已存在但 `open_thread` 无该形参 → 安全追加 `severity=""` 默认值（零 migration，既有调用方行为不变）
- **finding 留痕禁用 `record_answer`（按调研坐实 112 教训）**：`record_answer` 在同事务把 `open` 推到 `answered`，会让 `ahas_open_blocking_threads` 判为无门、confirm 守卫误放行、续驱 pause 失守。→ 从私有 `_append_thread_message_sync` **提炼公开的 `append_note`** 供 AI findings 留痕，不改变线程 status
- **`blocking == (severity == "blocker")` 强制一致（按调研定夺）**：二者不得各写各的，避免「blocker 不阻塞」或「warning 却阻塞」的错配
- 模型档位与起草**同档**（§12 已定），不强制换模型

### 有界修订与归因打回
- 归因打回：**仓级 BLOCKER 回该仓 `repo_plan`、融合级回 `merge`**，合计 **≤2 轮**（计数存 `stage_state`，复用 113 的有界回退范式）
- **超界出口**：转 `pending_review` 并携未决 BLOCKER 清单（人审可见），**不落 FAILED**（对齐 113 的「绝不静默通过、也不假装失败」）
- 仅 WARNING/INFO：直接进 `pending_review`，findings 作为人审参考（不打回）
- 确认门锁定校验：偏离 112 锁定的仓库集/职责（对照 `confirmed_at_gate`/`responsibility` 快照）即 **BLOCKER**——要变必须重开确认门
- 状态：`ai_reviewing` 期间蓝图状态经 `BlueprintLifecycleService` 转 `ai_reviewing`；打回时转回 `drafting`；通过转 `pending_review`；`blueprint_resume` 的 stage→status 表需追加 `ai_review → ai_reviewing`（受限纯追加，同 113-06 纪律：不改前九 stage 行为）

### 澄清回灌与决策物化
- 答案消费：由对应阶段代理消费 → 产**新 `ArtifactVersion`**（复用 113 幂等口径：同 content_hash 与 current 相同不翻版本）；线程置 `resolved` 并记 `applied_in_version`
- 决策物化：结论写进蓝图 `decision_log` 段（thread_id/question/decision/decided_by/applied_in_version），保证**文档自包含、导出不丢决策**
- 重锚定接线：新版本装配后调 111 的 `blueprint_anchor` 重挂线程（block_id 精确 → quoted_text 模糊 0.85 → `orphaned`）；失锚线程**不删**且可集中查询（供 115 展示「失锚评论」）
- pending 超时：保持 pending + 按可配周期提醒（§12 已定），**不自动作答、不判失败**；提醒对象为 `BlueprintReviewer` 名单 + 发起人

### 人工 block 编辑
- patch 形态：block 级 ops（`replace` / `insert` / `delete`）经 REST → service 收口（INV-6）→ 产新版本，`produced_by_ref="human_edit:{user_id}"`，与 AI 产版本同链路同 diff 视图
- 冲突语义：**人工内容不被 AI 覆盖**——后续 AI 修订以人工版本为基线，冲突必须开线程询问（镜像 `ProjectContextLink` 的「AI 不覆盖人工」原则）
- 校验：编辑后仍须过 `validate_blueprint`（含引用完整性与 `data_source` 形状），不合法直接拒绝并回显原因（不落半合法版本）
- 权限：项目成员皆可编辑（§6.4 已定）；编辑者与人审操作者一并 upsert 进 `BlueprintReviewer` 名单
- 人审操作端点（通过/驳回带划线评论）属本相位，经 `BlueprintLifecycleService`：通过 → `confirmed`；驳回 → `drafting` 且 `revision_round + 1`
- **confirm 守卫收进事务消除 TOCTOU（按调研定夺）**：「无 open+blocking 线程」与「无未解决 BLOCKER」两条判定必须在**同一事务内**完成（不得先查后转），否则存在竞态窗口；因 `blocking == (severity=="blocker")` 已强制一致，该守卫可收敛为单一查询
- **`revision_round` 写入路径（按调研定夺）**：它是蓝图 content 的 `meta` 段字段（非模型字段，全仓无写入方）→ 驳回必须走「改 content → `add_version` → `transition`」三步，**不扩 `_apply_transition_sync`**；本相位是它的首个写入方
- **`merge.merged` 转向变更（按调研定夺）**：`merge` 成功后由原先直转终态改为进入 `ai_review`；接受这一在途会话的行为变更（旧 `technical_plan` process 零感知）

### plan-checker BLOCKER 定夺（2026-07-30，5 条）

- **B1 答案消费必须有生产调用方**：`aapply_thread_answers` 不得是孤儿——在**人审 answer 端点**与 **review 入口**两处显式接线（作答后即消费产新版本），并给 `section_writer` 定**生产实现**（默认 None 不可接受：无人重产段落等于答案不落地）。
- **B2 必须补 finding 处置通道（消死锁）**：超界转 `pending_review` 后未决 BLOCKER 线程会让 confirm 守卫恒拒 → 人审只能驳回、永不能通过。定夺：五端点**新增 finding 处置端点**（`resolve` / `dismiss`，经 lifecycle 收口、记处置人与理由），并补「超界 → 人工处置 finding → confirm 放行」的端到端用例。禁止靠直调 service 充当证据。
- **B3 AI 重装路径必须挂重锚定与人工块保护**：打回后 `repo_rework`/`remerge` 重跑 merge 是主要产版本路径，若不处理会**抹掉人工编辑**且线程不重锚。定夺：**不改 `blueprint_merge.py`**（保持只读受限），改在 **114-03 的 `ai_review` 入口/新版本落库后**统一挂：① 调 `areanchor_threads` 批量重锚定；② **人工块保护**——以版本链中 `produced_by_ref` 带 `human_edit:` 的 block_id 为保护集，重装后逐一比对：内容等价则保留人工版本，实质冲突则**开线程询问**（绝不静默覆盖），对齐「AI 不覆盖人工」原则。
- **B4 提醒需真实周期路径**：GET 快照不是挂载点（无人应答就无请求 → 提醒永不触发）。定夺：挂**既有 apscheduler**（仓库同步轮询已在用，加一个 job，不新起独立定时体系）；判据状态口径明确为 **`needs_clarification`**（对齐 SC-4，不用 `pending_review`）；线程加 `last_reminded_at`（可空 DateTimeField + migration，本相位承载）以支撑「按周期」而非重复轰炸。
- **B5 规则六补 constraints**：`agoal_backward_review` 签名须纳入 `requirement_spec.constraints`（进 digest），使「与 constraints 冲突」真正可判；若确实只能部分覆盖，须在 PLAN 显式登记降级范围与理由，不得默认落空。
- **WARNING 一并修**：114-05 由 artifact 反查会话**必须带 `process_type="technical_blueprint"` 过滤**（112 决策，防跨 process 污染）；114-01 的 `BlueprintThreadMessage.objects.create` 计数验收自相矛盾需订正；114-02 的 `_normalize_locked_repos` 行号与 RESEARCH 不符需按实测更正。

### 观测
- 审查事件 `blueprint_review_started/completed/failed` 带 `duration_ms`/`category=caller`/`component=process_runtime`；findings 计数与分级分布进事件 payload（**正文不进 payload**）
- 打回/超界/人审通过驳回记 `caller` 事件并绑定 `initiated_by_user_id`；机械规则逐条判定记 `sampling`
- AI 打回率与人审修改量喂给 111 的 `blueprint_quality` DB 统计接口（该接口在 111 留了占位，本相位首次有真实数据）

### Claude's Discretion
- 六类机械规则的内部函数切分、goal-backward prompt 措辞、findings 去重与聚合策略、patch ops 的序列化细节、测试组织自行决定，遵循 111/112/113 已建立的 blueprint_* 模块风格。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（111/112/113 交付）
- `blueprint_schema.py`（validate_blueprint / iter_blocks 的 section_path 约定 / diff_blueprint_blocks）
- `blueprint_anchor.py`（重锚定纯函数：block_id → quoted_text 0.85 → orphaned）
- `blueprint_quality.py`（引用覆盖率 + 三项 DB 统计接口占位——本相位首次填数据）
- `BlueprintLifecycleService`（11 态守卫 + CAS + reviewer upsert + best-effort 事件）、`BlueprintThread/Message/Reviewer`
- `blueprint_merge.py`（装配面：确定性投影 + 分节起草 + 对账 + `derive_must_haves`）、`_coverage_gaps()` 归因
- `blueprint_resume.py`（stage→status 映射表，本相位需追加 `ai_review`）
- 112 的确认门锁定快照与 `RepoCharter`（规则 ⑥ 的判据来源）

### Established Patterns
- 113-06 的「受限纯追加」纪律（改 `blueprint_resume` 只动映射表、不改既有 stage 行为、删除行有上界并逐行登记）
- 113 的有界回退 + 超界转终态携未决项范式（`_coverage_gaps` 归因到仓）
- 112 的 HITL 端点范式（多动作、经 lifecycle service 收口、视图层续驱 + 失败隔离）
- 111 的纯函数模块与 jsonschema 风格

### Integration Points
- `ai_review` stage ← `merge` 产出的完整蓝图，→ findings 线程 + 打回或 `pending_review`
- 澄清回灌 ← 线程作答，→ 新 ArtifactVersion + decision_log + 重锚定
- 人工编辑 ← REST patch ops，→ 新版本（同 diff 链路）
- Phase 115 消费本相位：findings/线程/失锚列表/版本 diff/人审操作是查看器的数据面

</code_context>

<specifics>
## Specific Ideas

- 「机械规则纯函数化」是本相位低幻觉的关键：六类规则必须能在无 LLM 的情况下跑出确定性结论，测试用构造样例逐条证伪（缺引用/角色不一致/API 断链/超期排期/越确认门/违章程各一条）
- 有界修订必须能证伪「不会无限循环」：构造持续 BLOCKER 的样例，断言 2 轮后转 `pending_review` 且携未决清单
- 澄清回灌要断言「同一问题不再重复问」（查 decision_log 与 resolved 线程）——这是 112 规格门已立的纪律，本相位延续到审查阶段

</specifics>

<deferred>
## Deferred Ideas

- 审查与起草强制换模型的交叉验证实验（档位可配即可，Future Requirements）
- findings 的严重度自动学习/调参 → Future
- 前端批注呈现与失锚评论列表 UI → Phase 115

</deferred>
