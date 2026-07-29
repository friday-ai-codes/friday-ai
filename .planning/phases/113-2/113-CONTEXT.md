# Phase 113: 分仓方案与融合（阶段 2/3）+ Blueprint Context Bus - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权）

<domain>
## Phase Boundary

确认后的每个仓产出结构化分仓方案（RepoPlan），跨仓动态依赖靠会话级上下文总线协商；主 agent 融合装配出六段齐全、引用完备、跨仓 API 对账闭环的完整蓝图。

**只做阶段 2（分仓方案）+ 阶段 3 的融合装配 + Context Bus**：不做 AI 对抗审查与澄清回灌产版本（114）、不做前端查看器（115）、不做入口收编与导出（116）。

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §5.2（阶段契约表 repo_plan/merge 两行）/§5.3（RepoPlan schema）/§5.6（Blueprint Context Bus 全文）/§3.7-§3.11（现状分析、实现概述、API、影响范围、交互流程字段形状）/§3.12（must_haves 派生）/§13.2（冻结纪律）。

可消费上游：Phase 111 的 `blueprint_schema`（含 intent 必填）/`blueprint_execution`/`blueprint_quality`/`BlueprintLifecycleService`/`BlueprintThread`/`blueprint_anchor`；Phase 112 的确认门锁定产物（`repo_associations` 含 role/responsibility/confirmed_at_gate）/`blueprint_research_adapter` 派发面（含 `force_deep_repository_ids`）/`PartialPlan.content` 的 fitness 段/`blueprint_resume`/`stage_state["routing"]` 契约。

</domain>

<decisions>
## Implementation Decisions

### RepoPlan 分仓方案
- 载体沿用 `PartialPlan.content`，在其中新增 `repo_plan` 段（同一仓的 fitness 调研结论与方案同源可追溯，无需新表）
- 产出方式：direct 仓起容器（复用 112 的 `blueprint_research_adapter` 派发面，新增 plan 模式参数区分调研/拟方案两类 prompt）；indirect 仓由服务端 LLM 合成能力引用清单（轻量，不起容器）
- 澄清与补调研复用既有机制：`BlueprintThread(kind=ai_clarification, blocking)` + dispatch 增量能力；单仓定向补调研走已有 `force_deep_repository_ids` 通路，不新建机制
- RepoPlan 按 DESIGN §5.3 形状做 jsonschema 校验：**新建独立文件 `blueprint_repo_plan_schema.py`**（不碰 112 已冻结的自检面），字段 `repository_id/role/responsibility/fitness/current_state/impl_items/apis_provided/apis_consumed/local_impact/risks/open_question_thread_ids`；不合格触发有界重试（≤2 轮），仍不合格开澄清线程而非静默降级
- **plan 模式扩展点（按调研定夺）**：全部走「新增带默认值的 keyword-only 参数」，缺省行为逐字等价 112——`dispatch(…, mode="research")` / `_build_prompt(…, mode=)`；`last_output.source` 换 `blueprint_repo_plan`（否则被 `_is_blueprint_research` 抢走并因缺 `fitness.verdict` 判失败）；`call_source` 换 111 已注册的 `blueprint_repo_plan`；**`env_FRIDAY_TASK_MODE` 保持 `explore` 不动**（它管 git 写拦截，与调研/拟方案正交）
- **阶段 2 任务态（按调研定夺）**：复用同一 `RepoResearchTask` + `mark_stale` 触发重跑，但 `_h_bp_repo_plan` **自写完成判据**，不复用 `aall_research_tasks_terminal`（阶段语义不同）
- **一仓多条 PartialPlan**：按 seq/更新时间取最新一条作为该仓 canonical 产物（调研段与方案段同源累积，不覆盖历史）

### Blueprint Context Bus（会话级共享上下文）
- 新模型 `delivery.BlueprintContextEntry`：`convergence_session FK / project FK / key / kind(finding|api_surface|contract|decision|dependency_claim|question) / repository_id / content JSON / produced_by / seq(会话内单调) / status(active|superseded)`；**不复用 `ProjectMemory`**（那是项目级长期记忆、打包预算仅 30 条，高频调研写入会污染它）
- key 约定前缀：`repo:{id}.api_surface` / `contract:{name}` / `decision:{thread_id}` / `dependency:{from}->{to}`
- 容器实时读写：扩容器知识 MCP 白名单新增 `read_blueprint_context`（支持 key_prefix / kind / repository_id / since_seq 增量拉取）与 `report_blueprint_context`（内容过 `redact_secrets_in_text`）；写入即对所有并行容器可见（server-authoritative）
- **会话隔离必须 view 层自建（按调研纠偏，重要）**：容器 MCP 鉴权链只到 `token → owner(User)`，**不存在** `token → session → user`；`X-Friday-Session-Id` 仅是关联键、不可信作授权依据。故「只能读写本会话总线」必须在 view 层自建三道校验，缺任一条拒绝（403/404），绝不放行跨会话读写：
  - ① **归属校验**：header session id 对应的 session 的 `AgentSession.user` == token owner。**前置补齐（plan-checker BLOCKER 1 定夺）**：该字段现状可空且蓝图派发时未赋值，故 **RepoPlan 派发面（113-03）必须在派发时写入 `AgentSession.user = dispatch_user`**，02 的校验才有真实数据来源；两者同 wave 实现，02 的测试可直接造带 user 的 session
  - ② **process 校验**：该 session 关联的 `ConvergenceSession.process_type == "technical_blueprint"`（防跨 process 污染，对齐 112 review CRITICAL 的教训）
  - ③ **条目一致**：目标总线条目的 `convergence_session` 与之一致
  - 另叠加项目成员校验（沿用既有 packer 口径：成员 或 public_org）
- 等待原语两档：
  - **短等待**：`await_blueprint_context(key_pattern, timeout)`——**容器侧有界轮询** `read_blueprint_context(since_seq)`（照抄 `task/.../question_loop.py` 的 deadline 骨架），**不做服务端长轮询**：`knowledge_tools.py` 的 `timeout=60.0` 写死在公共 handler 工厂里，改它会波及全部 7 个既有工具。命中即返回；**超时返回正常结果而非 is_error**（否则诱导 agent 重试而非降级），由 agent 自行降级（记录假设 + 开澄清线程），绝不无限挂
  - 短等待**不发心跳**（避免给公共 handler 工厂加 callback 参数，保持既有 7 工具零影响）
  - 容器知识配额：**不改工厂计数逻辑**，派发时把 `FRIDAY_TASK_KNOWLEDGE_QUOTA` 提到 400 以容纳轮询开销
  - **长等待**：容器以 `waiting_context` 结构化结果**退出**（携 partial 产物 id + 等待声明），编排层登记依赖，目标条目就绪后**重新派发**该仓容器（prompt 带 partial 引用续作）——复用 waiting_event + barrier 与 112 的增量派发白名单
- 第一道防线是 wave 预排：repo_plan 阶段按 API provider/consumer 关系预排波次（provider 仓先行），`await` 只兜预排不出来的动态依赖，避免退化成人人互等
- 死锁防护：编排层检测互相等待环（A 等 B、B 等 A）→ 立即判定并抛澄清由用户裁决，不靠超时兜底
- **waiter 生命周期（按调研定夺）**：写入侧在同事务内把被满足的 waiter 置 `superseded`；超时清理挂在 barrier 续驱路径上（不新起定时任务）
- **容器镜像向后兼容**：老镜像无新工具时不得崩——服务端新工具缺失/未知工具名一律返回结构化错误而非 500；容器侧 endpoint/token 空值时整个 MCP server 不挂（沿用既有短路）
- 沉淀：会话结束后有长期价值的条目走 distill 管道产 `ProjectMemory` 草案（人工 confirm 生效，遵守「AI 不覆盖人工」）

### merge 融合装配
- 新建 `blueprint_merge.py`：**绝不修改**冻结的 `architect_merge_adapter.py`；主 agent 分节多次调用而非单次巨 prompt（降幻觉、便于按节归因重试）
- 六段来源分工——**确定性投影优先，LLM 只写需要推理的部分**：
  - `repo_associations` ← 确认门锁定产物直接投影（含 role/responsibility/fitness/confirmed_at_gate/decided_by）
  - `current_state_analysis` ← 各仓 `PartialPlan.content.current_state` 直接投影（citations 一并带上）
  - `implementation_overview`（含 modules 与 items 的 change_type/how/files_touched/depends_on/wave）/`api_contracts`/`interaction_flows`/`impact_analysis` ← LLM 分节起草后装配
  - `must_haves` ← 由 requirement_spec 与实现项确定性派生（复用 111 的派生思路）
- 跨仓 API 对账用**纯函数**（非 LLM 自查）：consumed 契约找不到 provider → 标 needs_support 且要求 support_repository_id 出现在 `repo_associations`（缺失即视为缺协作仓，抛澄清）；provider/consumer 字段不一致（schema/字段名/方向）抛澄清，绝不静默拍板
- **needs_support 落位（plan-checker BLOCKER 4 定夺，关键）**：`api_contracts[]` **无顶层 `availability`**——按 111 schema，它在 `data_source` 下且枚举为 `existing | needs_support`。故对账结果必须写 `data_source.availability` 与 `data_source.support_repository_id`，枚举归一到 `existing|needs_support`（不得引入顶层字段或 `available|unknown` 变体），否则 114/115 按 schema 读不到、SC-4 表面通过实际失效
- 装配后强制门：过 `validate_blueprint`（111）+ 引用覆盖率门（复用 111 的 `blueprint_quality`，阈值走 SystemSetting 可配）；不达标按归因回退——单仓问题回该仓 `repo_plan`、融合问题重融合，合计上界 2 轮
- **超界出口（按调研定夺）**：merge 重试超界转 `STAGE_DONE` 并**携未决项清单**（不落 `STAGE_FAILED`）——蓝图已成形只是未达覆盖率，交由 114 的 AI 审查与人审处置，符合「绝不静默通过、也不假装失败」
- **覆盖率归因（按调研定夺）**：新写 `_coverage_gaps()` 纯函数把未覆盖结论定位到具体仓，作为「单仓回退」的判据来源（否则无法决定回哪个仓）

### 状态、stage 与观测
- 阶段 2/3 蓝图状态 = `drafting`（一律经 `BlueprintLifecycleService`）；有 open+blocking 线程时派生显示 `needs_clarification` 并记 `return_stage`（复用 112 的双轨语义与 `blueprint_resume` 判据）
- **状态映射必须 stage-aware（plan-checker BLOCKER 3 定夺）**：112 的 `blueprint_resume._amap_blueprint_status` 把状态硬编码回 `researching`，若不改，阶段 2/3 的澄清恢复会退回阶段 1。定夺：**允许对 `blueprint_resume.py` 做受限扩展**（它是 112 本里程碑自产文件，不属 §13.2 冻结面）——加 stage→status 映射表（前七 stage → researching，`repo_plan`/`merge` → drafting），且 `repo_plan`/`merge` 两个 handler 开 blocking 线程时必须传 `return_stage`（DRAFTING 对应 stage）；纯追加不改既有前七 stage 行为
- `builtin_processes.py` 的 `technical_blueprint` 追加 `repo_plan → merge` 两 stage（112 已注册前七个），**只加不改**，`_TECHNICAL_PLAN_STAGES` 零触碰
- `call_source` 复用 111 已注册的 `blueprint_repo_plan` / `blueprint_merge`，**不新增枚举值**
- 观测：总线条目读写记 `sampling`，waiter 登记/命中/超时与「谁在等谁」记 `caller` 事件（`component=process_runtime`，容器动作归属 dispatch 用户）并写 `ConvergenceSessionEvent`（blueprint_* 既有类型，供 115 时间线可视化等待关系）

### Claude's Discretion
- 分节 LLM prompt 的具体切分与措辞、对账函数内部结构、总线 key 命名细节、波次预排算法实现、测试组织自行决定，遵循 CONVENTIONS.md 与 111/112 已建立的 blueprint_* 模块风格。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（111/112 交付，直接消费）
- `blueprint_schema.py`（validate_blueprint / iter_blocks / diff / feature_points[].intent）、`blueprint_execution.py`、`blueprint_quality.py`（引用覆盖率门）
- `BlueprintLifecycleService`（状态转移唯一入口）、`BlueprintThread/Message`、`blueprint_anchor`
- `blueprint_research_adapter`（容器派发面，含 `force_deep_repository_ids` 与增量派发白名单）、callbacks 第三链、`blueprint_resume`（pause 判据 + `aresume_blueprint_session`）
- 确认门锁定产物：`repo_associations` 的 role/responsibility/confirmed_at_gate/decided_by + `PartialPlan.content` 的 fitness 段
- 容器 token 链：`mint_task_token` + 3 个 `FRIDAY_TASK_*` env 键（112 已为 PLAN 链接通，本相位复用并扩 MCP 白名单）

### Established Patterns（模仿对象）
- `server/services/process_runtime/architect_merge_adapter.py` — 融合范式（**冻结，只读参考**）
- `task/core/knowledge_tools.py` — 容器知识 MCP 白名单与 handler 形状（扩两个工具照此）
- `task/core/executor.py` 的 `build_knowledge_mcp_server` — MCP 挂载点
- `ask_user` 的容器保活轮询实现 — 短等待原语对齐对象
- 112 的 `blueprint_route`/`blueprint_research_adapter`/确认门 service — 本里程碑自产风格基准

### Integration Points
- `repo_plan` stage ← 确认门锁定的仓库集与职责，→ `PartialPlan.content.repo_plan`
- Context Bus ← 容器 MCP 读写 + 编排层 waiter 登记，→ 并行容器协商与重派
- `merge` stage ← 全部 RepoPlan + 规格 + 确认记录，→ 完整蓝图 `ArtifactVersion`（过 validate_blueprint 与覆盖率门）
- Phase 114 消费本相位：完整蓝图是 AI 对抗审查的输入

</code_context>

<specifics>
## Specific Ideas

- 「A 仓 consumer 等 B 仓 provider 接口契约」是 Context Bus 的验收场景：短等待命中即继续、长等待退出后重派续作、互等环抛澄清，三条路径都要有能证伪的断言
- 引用覆盖率门首次真正生效（111 建的指标 + 112 的调研 citations），阈值可配以免一上线就卡死
- 六段装配的确定性投影部分必须可断言「不经 LLM」——投影结果与上游产物逐字段一致

</specifics>

<deferred>
## Deferred Ideas

- 母子蓝图拆分（schema 支持互引，编排级拆分另议）→ Future Requirements
- 总线条目的跨会话复用（当前仅会话级）→ 观察 distill 效果后再议
- FLOW-02 的「替代建议」结构化字段（Phase 112 残留 PARTIAL）→ 若本相位需机器消费该建议则一并补，否则留 115

</deferred>
