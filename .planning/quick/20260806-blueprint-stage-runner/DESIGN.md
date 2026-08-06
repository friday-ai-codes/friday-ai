# 技术方案：蓝图编排环节单跑层（Blueprint Stage Runner）

> 日期：2026-08-06 · 范围：`server/services/process_runtime/` + `server/mcp_tools/` + `mcp/` + `skills/`
> 背景：技术方案（blueprint）编排与项目关联仓库互相牵制 —— 项目手动绑定（`ProjectBranch(source=manual)`）
> 会让 route stage 固定路由短路，而路由/调研产物又只能在整条 `technical_blueprint` stage 图里产出，
> 无法单独触发、无法单独测试各环节能力。

## 1. 目标

1. **环节可单跑**：仓库路由、需求规格、仓库调研等环节均可基于「上游产物 JSON」独立触发（MCP / skills），
   不必走完整 `intake → … → ai_review` 编排。
2. **解除双向牵制**：单跑路由可显式 `ignore_pin` 绕过项目手动绑定的固定路由；路由/调研结果**只是提案**，
   是否写回「项目关联仓库」由用户显式调用采纳工具决定。
3. **产物契约即接口**：单跑的输入输出与正式编排的 `stage_state` 契约逐字同形
   （routing 顶层 8 键、`requirement_spec`、§7 PartialPlan），可直接作能力评测的固定用例。

## 2. 非目标

- 不改动 `technical_blueprint` stage 图与十个 `_h_bp_*` handler；正式编排零行为变化。
- 不单跑 repo_plan / merge / ai_review（依赖多仓上下文总线与波次派发，成本高，后续再议）。
- 不新增「确认门 add-repo」的 MCP 面（REST `blueprint-gate` 已覆盖）。

## 3. 现状关键事实（调研结论）

- `BlueprintRouteAdapter` 零 ORM 写（INV-6），事件 emit 全部 best-effort 吞异常 ⇒ 喂一个**内存 stub session**
  即可完整复跑三分量融合路由（能力树 `RepoRouterV2` + 章程 + 历史）。
- 固定路由入口唯一：`route()` 内 `_aresolve_pinned` → `repo_binding_pin.asession_pinned_bindings`，
  只认 `ProjectBranch(source=manual)`。
- 规格环节的可复用纯能力：`blueprint_intake._allm_feature_points`（LLM 拆功能点）、
  `blueprint_intent_classify.aclassify_intents`、`blueprint_ambiguity_score.ascore_ambiguity`（四维歧义打分），
  三者都只拿 session 记日志 id，均可脱离 artifact/线程单跑。
- 调研必须有**真实 `ConvergenceSession`**（`RepoResearchTask`/`PartialPlan` FK 到 session；容器回调按
  `last_output.blueprint_session_id` 反查落库）。但回调侧 barrier 的续驱
  （`adrive_blueprint_session_to_pause_or_terminal`）对 `process_type != technical_blueprint` 一律 no-op、
  恢复扫描（`arecover_stalled_blueprint_sessions`）也只扫 `technical_blueprint` ⇒ 用一个**独立注册的沙箱
  process_type** 建会话，容器结论照常落库，而任何续驱/恢复机制都不会驱动它。
- `ProjectBranchService.bind/unbind` 是项目分支绑定唯一写入口，自带成员 fail-closed 校验与审计。

## 4. 设计

### 4.1 新模块 `server/services/process_runtime/stage_sandbox.py`

- `SANDBOX_PROCESS_TYPE = "blueprint_stage_sandbox"`：模块导入即注册一个单 stage 的
  `ProcessDefinition`（仅为通过 `create_session` 的注册校验；无任何驱动方会 advance 它）。
- `SandboxSession`：内存 stub（`id` / `stage_state` / `decomposition` property / `work_item_id=None` /
  `current_artifact_version_id=None` / `initiated_by_user_id` / `created_by_id`），
  供 route / spec 两个纯读环节零落库单跑。
- 三个 runner：
  - `arun_route_stage(...)`：组 stub session（`stage_state.requirement_spec` + `include_repos` +
    `decomposition.project_id`）→ `BlueprintRouteAdapter().route(session, exclude_repository_ids=…,
    ignore_pin=…)`，返回 routing 契约摘要原样。候选范围：显式 `include_repository_ids` >
    project 所属 space 仓库集 > 全库。
  - `arun_spec_stage(...)`：LLM 拆功能点（或直采调用方给的 `feature_points`）→ intent 分类补齐 →
    四维歧义打分（`aload_spec_gate_config(tier)` + `weighted_total` + `is_ambiguous`）→
    返回 `requirement_spec` + `ambiguity` 报告（与 `ambiguity_report` 同形）。
  - `astart_research_sandbox(...)` / `aget_research_sandbox(...)`：建真实沙箱会话（entrypoint=mcp、
    `created_by` 为触发用户 ⇒ 容器 token 可铸），seed `stage_state.routing.candidates`（112-03 契约形）
    与 `requirement_spec`，直接调 `BlueprintResearchAdapter().dispatch(session)`。deep（direct）仓起容器、
    indirect 仓服务端轻量合成、无在线 runner 自动降级 light（`degraded=true` 可见）。
    结果轮询按 `RepoResearchTask` + 最新 valid `PartialPlan` 读，不依赖会话推进。
    读接口仅限会话创建者（中性 404，不泄露存在性）。

### 4.2 `BlueprintRouteAdapter.route` 增加 `ignore_pin: bool = False`

`True` 时跳过 `_aresolve_pinned` 短路，走完整自动路由。缺省 `False`，正式编排调用点零改动。

### 4.3 新 MCP tools（5 个，`server/mcp_tools/`）

| tool | 语义 | 副作用 |
|---|---|---|
| `route_blueprint_repos` | 三分量完整蓝图路由单跑（区别于既有粗版 `route_repositories`），支持 `ignore_pin` / `exclude_repository_ids` | 无（dry-run） |
| `generate_requirement_spec` | 需求文本 → feature_points + intent + 四维歧义报告与澄清问题 | 无（dry-run） |
| `start_repo_research` | 对指定仓库集发起沙箱调研（容器深调研 / 轻量合成） | 建沙箱会话 + 调研任务 |
| `get_repo_research` | 轮询沙箱调研结果（任务状态 + §7 调研结论） | 无 |
| `apply_repo_association` | **唯一写回路径**：把选定仓库集 bind/unbind 到项目（`ProjectBranch(source=manual)`） | 写项目分支绑定（成员 fail-closed + 审计） |

注册面五件套：`urls.py` + `views.py` + `serializers.py`（含 `TOOL_SCHEMA_SNAPSHOT`）+
`test_schema_snapshot.py` + `mcp/src/tools.ts`（37 → 42，测试计数同步）。

### 4.4 Skills

新增 `skills/skills/friday-blueprint-stages/SKILL.md`：对话工作流「单跑路由 → 单跑调研 →
用户裁决 → apply_repo_association 采纳」，并说明与 `friday-routing`（粗筛）的分工。

## 5. 可观测（按 LOGGING-SPEC）

- MCP 入口自动纳入 `RequestMetric`（`McpToolView._record` 既有旁路）+ `ToolCallRecord` 留痕。
- `stage_sandbox` 三个 runner 各记 `caller` 类 started/completed/failed 事件（`component=process_runtime`，
  带 `initiated_by_user_id` / `duration_ms`；需求正文不进日志，只记标量）。
- 复用的 LLM 调用点 call_source 不变（`BLUEPRINT_DECOMPOSE` / `BLUEPRINT_SPEC_GATE` /
  `BLUEPRINT_REPO_RESEARCH` 等，零新增枚举）。
- `apply_repo_association` 走 `ProjectBranchService` 既有审计（`ACTION_PROJECT_BRANCH_BOUND`）。

## 6. 风险与取舍

- 沙箱会话会留 `ConvergenceSession` 行（status 恒 created）：刻意保留 —— 调研任务/产物需要挂靠，
  且事件留痕可回放；已确认恢复扫描与续驱都按 process_type 过滤，不会误驱。
- route/spec 单跑不落库：能力测试场景不需要留产物，调用留痕由 Interaction Ledger 承担。
- deep 调研的容器成本：上界沿用 `_MAX_ATTEMPTS=2` 与 `_RESEARCH_TIMEOUT=30min` 既有约束；
  单次 `start_repo_research` 限 10 仓。
