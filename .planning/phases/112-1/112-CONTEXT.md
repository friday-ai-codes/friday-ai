# Phase 112: 规格门与双面路由调研（阶段 1：调研与确认门） - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权）

<domain>
## Phase Boundary

需求进来先锁规格再定仓——歧义超阈值必澄清、feature_point 带意图分类；路由融合章程/历史落点/能力树三路证据且分数可解释；逐仓容器调研产出 fitness 判定与职责建议；不合适仓有界重路由；出口硬确认门锁定仓库集与职责并回灌章程。

**只做阶段 0（规格门）+ 阶段 1（调研与确认门）**：不做 repo_plan 分仓方案与 merge 融合（113）、不做 Context Bus（113）、不做 AI 对抗审查（114）、不做前端查看器（115，本相位只提供 REST 与事件数据面）、不做入口切换（116）。

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §5.1（阶段图）/§5.2（阶段契约表）/§5.4（歧义门）/§5.7（RepoCharter 与双面路由）/§3.5-§3.7（requirement_spec、repo_associations、current_state_analysis 字段）/§6（线程模型）/§13.2（冻结纪律）。

可消费的 Phase 111 底座：`blueprint_schema.py`（validate_blueprint/iter_blocks/diff）、`blueprint_execution.py`、`blueprint_quality.py`、`BlueprintLifecycleService`（11 态守卫/CAS/事件）、`BlueprintThread/Message/Reviewer` 模型、`blueprint_anchor.py`、`RepoCharter` + `charter_service` + charter REST、`call_source` 8 值。

</domain>

<decisions>
## Implementation Decisions

### 规格门（spec_gate）与意图分类
- 歧义四维打分（goal/boundary/constraint/acceptance）由 LLM 单调用产出分数 + 理由，`call_source=blueprint_spec_gate`；加权总分与阈值比较决定是否放行
- 阈值与四维权重外置到 `SystemSetting`（运行时可调，默认总分阈值 0.20），镜像 v0.19.0 权重外置做法；打分记录进 `ambiguity_report`（schema 已有字段）
- 澄清载体复用 Phase 111 的 `BlueprintThread(kind=ai_clarification, blocking=true)`，options 携带候选选项 + 证据引用；**不**新建澄清表、**不**复用 `delivery.Clarification`
- 作答后规格锁定：`requirement_spec` 写入蓝图版本，已解决线程 id 进 `ambiguity_report.resolved_thread_ids`，结论物化进 `decision_log`；同一问题不再重复问（提问前查 decision_log 与 resolved 线程）
- `intent` 落位 = `blueprint_schema` 的 `feature_points[]` 补必填枚举字段 `intent: greenfield | brownfield | fix`（schema 演进，含向后兼容：既有测试样例工厂同步补字段）

### 双面路由（blueprint_route）
- 新建 `server/services/process_runtime/blueprint_route.py`：内嵌调用 `RepoRouterV2` 取原样输出，**绝不修改** `codegraph/services/repo_router_v2.py`（§13.2）
- `charter_match` 为 adapter 层加性分量：`owned_domains`（含 `status=planned`）匹配加分、`boundaries` 命中判负、`evolution=maintenance_only/deprecated` 降权；按 feature_point `intent` 加权——greenfield 重章程与历史落点，brownfield/fix 重能力树，章程作 sanity check（命中禁区仍保留候选时 LLM 必须给显式理由）
- `history_match` 分量来自既有 delivery knowledge 检索（kinds=`code_change`/`tech_plan`）：召回「同类需求近期实际合进哪个仓」
- breakdown 在 adapter 层组装（含 charter_match/history_match + RepoRouterV2 原始各信号，各项之和等于总分），写 `ConvergenceSessionEvent`（`blueprint_*` 事件类型）供 115 前端展开；`repo_associations.routing_evidence` 字段形状不变
- 章程条目被引用时产出 `citation.source_type=repo_charter`（schema 引用池支持）

### 逐仓容器调研与 reroute
- 新建 `server/services/process_runtime/blueprint_research_adapter.py`：复制 `research_adapter.py` 的 dispatch 范式但为独立文件（冻结面不动）；容器 = `SubAgentSession(TaskType.PLAN)`，按仓 fan-out 并行
- 容器上下文接通：派发时 `mint_task_token` + 注入 `FRIDAY_TASK_KNOWLEDGE_ENDPOINT`（复制编码链 Phase 103 做法，PLAN 链现状缺失，本相位补齐）；章程内容随 prompt 注入，**不**扩容器 MCP 白名单（留给 113 Context Bus）
- direct 候选深调研；indirect 候选默认轻量（能力树 + RAG + 知识图谱证据，服务端合成），提供人工升级为深调研的入口（REST 动作）
- fitness 产物形状：`RepoResearchTask.report` JSON 增 `fitness{verdict: suitable|partial|unsuitable, reasons, citations}` + `role_suggestion(direct|indirect)` + `responsibility` + `findings[]`（带 citations），可直接投影进蓝图 `repo_associations` 与 `current_state_analysis`
- reroute 上界 ≤2 轮（计数存 `ConvergenceSession.stage_state`）：unsuitable 仓排除后由主 agent 补候选重调研；仍不收敛 → 带全部现状升确认门由用户裁决（绝不静默失败）

### 确认门与章程回灌
- 确认门载体 = `BlueprintThread(kind=repo_confirmation, blocking=true)`，options 存结构化仓库清单快照（每仓 role 建议/职责/fitness 结论/现状摘要/证据引用）
- 五种用户动作走 REST：`confirm` / `remove_repo` / `add_repo` / `reclassify_role` / `edit_responsibility`，全部经 `BlueprintLifecycleService` 收口（INV-6）；add_repo 触发新仓调研、remove/reclassify/edit 驱动对应重调研或直接更新快照
- 锁定语义：确认后仓库集与职责写入蓝图 `repo_associations`（`confirmed_at_gate=true`、`decided_by=human`、`responsibility` 落字段）并记 `decision_log`；后续阶段变更须重开确认门（114 的 AI 审查按此判 BLOCKER）
- 章程回灌：确认/改判 role 后的职责聚合 → `owned_domains` 草案；移除仓动作 → `boundaries` 草案；一律经 Phase 111 的 `charter_service` 产 `source=ai_draft`（人工 confirm 才生效，绝不自动改）；另提供「`RepoAssociation.status=rejected` 一键沉淀为章程禁区候选」API
- 确认动作执行者自动进 `BlueprintReviewer` 名单（复用 111 的 upsert 逻辑）

### stage graph 与状态映射
- `builtin_processes.py` 新增 `technical_blueprint` process 注册项（**仅加字典项**，不动既有 `technical_plan` stage graph）
- 本相位落 stage 骨架：`intake → decompose → spec_gate(pausable) → route → repo_research(pausable) → reroute → repo_confirmation(pausable)`；`repo_plan / merge` 由 Phase 113 接续注册
- 状态映射：阶段 0/1 全程蓝图状态 = `researching`；有 open+blocking 线程时派生显示 `needs_clarification`（记 `return_stage`），一律经 `BlueprintLifecycleService`
- 澄清送达：同步点 1（v0.19.0 Phase 107）未合并前用现有澄清通道（飞书卡片 + chat 路由）兜底，合并后 rebase 对齐；超时保持 pending + 提醒（不自动作答、不判失败）

### Claude's Discretion
- 各 adapter 内部函数切分、prompt 具体措辞、breakdown 字段命名细节、REST 序列化器组织、测试组织结构自行决定，遵循 CONVENTIONS.md 与 Phase 111 已建立的 blueprint_* 模块风格。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（Phase 111 交付，直接消费）
- `server/services/process_runtime/blueprint_schema.py` — validate_blueprint / iter_blocks / diff_blueprint_blocks（本相位需为 feature_points 补 intent 字段）
- `server/delivery/services/blueprint_lifecycle_service.py` — 11 态转移守卫 + CAS + reviewer upsert + best-effort 事件（所有状态变更与确认动作经此）
- `server/delivery/models/` — BlueprintThread / BlueprintThreadMessage / BlueprintReviewer（确认门与澄清线程载体）
- `server/repositories/` — RepoCharter 模型 + `charter_service`（章程读取与回灌草案）+ charter REST 三端点
- `server/agents/call_source.py` — blueprint_spec_gate / blueprint_repo_research / blueprint_reroute 等 8 值已注册
- `server/tests/helpers/blueprint_samples.py` — make_blueprint 工厂（补 intent 字段后继续复用）

### Established Patterns（本相位模仿对象）
- `server/services/process_runtime/research_adapter.py` — 容器 fan-out dispatch 范式（**只读参考，禁改**）
- `server/services/process_runtime/decompose_segments.py` — LLM 单调用 JSON 输出范式（**只读参考，禁改**）
- `server/services/process_runtime/builtin_processes.py` — stage graph 注册（只加注册项）
- `server/workflows/nodes/ai/coding.py` + `server/access_tokens/services.py` — mint_task_token + FRIDAY_TASK_KNOWLEDGE_ENDPOINT 注入范式（PLAN 链接通照此）
- `server/codegraph/services/repo_router_v2.py` — 路由输出契约（**只读调用，禁改**）

### Integration Points
- `blueprint_route` ← RepoRouterV2 输出 + RepoCharter + delivery knowledge 召回，→ 候选清单与 breakdown 事件
- `blueprint_research_adapter` ← 候选清单，→ SubAgentSession(PLAN) 容器 + RepoResearchTask.report（fitness/role/responsibility/findings）
- 确认门 REST ← 用户动作，→ BlueprintLifecycleService → 蓝图 repo_associations 锁定 + charter_service 草案
- Phase 113 消费本相位：确认门锁定的仓库集与职责是 repo_plan 的输入

</code_context>

<specifics>
## Specific Ideas

- 高三提分专项 case 是本相位的验收靶子：greenfield 功能点上 `onion-learning` 必须能凭章程 owned(planned) 进入候选（而非因能力树无培优节点被淘汰）；`study-plan`/`study-practice` 命中章程禁区须被降权
- 断言写机制级（章程分量对候选排序产生可拆解影响）而非结果级名次，与 v0.19.0 golden set 方法论一致
- 111 的 `evaluate_blueprint_golden` command 与 `blueprint_quality` 指标（目标仓命中率）在本相位首次有真实数据可评

</specifics>

<deferred>
## Deferred Ideas

- 容器 MCP 白名单扩 charter/context 工具 → Phase 113（Context Bus 一并做）
- charter_match 权重自动调参 → Future Requirements
- 确认门的前端 UI 呈现 → Phase 115（本相位只交付 REST 与事件数据面）

</deferred>
