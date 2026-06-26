# Phase 89 — PLAN-01 Summary（技术方案深化主链路 + 观测地基）

**Status:** ✅ Done
**Plan:** `.planning/phases/89-tech-plan-branch/89-01-PLAN.md`
**Date:** 2026-06-27

## 交付内容

消费 Phase 88 确认仓（`get_verified_associations`）→ 经 **v0.7 同一编排引擎**
（`build_orchestration_engine` + `adrive_plan_session_to_pause_or_terminal`，**未造第二个 engine**）
深化 per-repo 七要素 + overall 整体方案 + 跨仓上下文 → 落 canonical `TechnicalPlan`/`PlanVersion`
（复用不新建）→ 终态镜像进项目 RESEARCH（经 `ProjectDocService.append_research_note` → 触发
Phase 83 双向同步飞书，never-clobber）。卡片多轮校验澄清复用既有 `ClarifyAdapter` HITL +
`waiting_event` 节点续驱。本 plan 集中注册 Phase 89 全部新 `call_source`。

## Files

### Added
- `server/initiatives/services/plan_deepen_service.py` — `PlanDeepenService`（INV-6 编排收口：
  消费 88 verified → 引擎深化 → 七要素 canonical → RESEARCH 镜像；结构化事件
  `plan_deepen_started/_completed/_failed/_mirror_failed`，category=caller，component=plan_deepen，
  duration_ms，归因 initiated_by_user_id，镜像前 `redact_secrets_in_text` 脱敏，best-effort 不反噬）。
- `server/workflows/nodes/integrations/plan_deepen.py` — `PlanDeepenNode`（node_type=`plan_deepen`，
  is_blocking，消费 88 + 引擎续驱 + clarifying/researching → `waiting_event` + `WorkflowEventSubscription`
  超时兜底，DONE → completed 携 plan_version 锚，FAILED/异常 → error 分支，registry 自动发现）。
- `server/feishu/cards/plan_deepen_card.py` — `build_plan_deepen_card`（progress/clarify/done 三态，
  CardKit schema 2.0，action_value 仅携 execution_id/node_id/round/action，不携方案/澄清正文）。
- `server/tests/initiatives/test_plan_deepen_service.py` — 消费 88 + include_repos 透传 + 引擎工厂复用 +
  DONE 镜像 / 非 DONE 不镜像 / 无 verified 仍跑 + call_source normalize + 七要素渲染（6 用例）。
- `server/tests/workflows/test_plan_deepen_node.py` — 注册 + 无需求 error + clarifying waiting_event +
  订阅创建 + initiated_by 透传 + DONE completed + FAILED/异常 error（6 用例）。

### Modified
- `server/agents/call_source.py` — 新增 `PLAN_DEEPEN`/`PLAN_REVISION`/`BRANCH_NAMING` 三枚举；
  docstring「27 值」→「30 值」。
- `.planning/observability/LOGGING-SPEC.md` — §4.1 追加 `plan_deepen`/`plan_revision`/`branch_naming` 三行。
- `server/services/plan_orchestration/research_adapter.py` — per-repo explore 深化 prompt 扩为产七要素
  （负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature 不清处/与现功能冲突），
  注入对应仓 routed_reason/matched_node_paths 上下文；容器 dispatch 包 `use_call_source(PLAN_DEEPEN)`。
  零回归既有签名/续驱契约。
- `server/services/plan_orchestration/architect_merge_adapter.py` — merge prompt 扩 `overall_plan` +
  `cross_repo_context` 段（additionalProperties 允许，不破 schema 校验）；融合 LLM 调用包
  `use_call_source(PLAN_DEEPEN)`。零回归既有 MergedPlan 字段。
- `server/tests/test_model_usage_call_source.py` — 基准 27→30（含三新枚举）。

## call_source

- 新增（集中注册，下游 wave 仅消费不再改 `call_source.py`）：
  `plan_deepen`（per-repo/overall 七要素深化）、`plan_revision`（89-02 修订回路）、`branch_naming`（89-04 分支名）。
- **新基准 = 30**（27 → 30）。

## Tests

- `tests/initiatives/test_plan_deepen_service.py` ✅ + `tests/workflows/test_plan_deepen_node.py` ✅ +
  `tests/test_model_usage_call_source.py`（基准 30）✅ + `tests/initiatives/test_repo_association_output.py` ✅
  → **39 passed**。
- v0.7 零回归：`tests/services -k "plan_orchestration or merge or research_adapter"` → **91 passed**。
- ruff check 全绿（含新文件）。

## LOCKED 符合

- ✅ 复用 v0.7 `TechnicalPlan`/`PlanVersion` + 同一 engine（无第二工厂，grep `build_orchestration_engine`）。
- ✅ per-repo 七要素 + overall + 跨仓上下文。
- ✅ 终态镜像进 RESEARCH（Phase 83，经 `append_research_note`，never-clobber）。
- ✅ 消费 Phase 88 `get_verified_associations`。
- ✅ call_source 集中注册（27→30）+ LOGGING-SPEC §4.1。
- ✅ INV-6（写经 engine/TechnicalPlanService/append_research_note，无旁路写）；脱敏；归因。
- ✅ 零 v0.7 regression。

## Handoff（89-02/03/04）

- **call_source 已就绪，勿再改 `call_source.py`**：`plan_revision`（89-02 修订回路「调研问题发现」
  检测 LLM）、`branch_naming`（89-04 分支名生成 LLM）已注册，直接 `use_call_source(...)` 消费。
- **89-02 修订回路**：复用 `PlanVersion.supersedes` + `TechnicalPlanService` 加补充修订；改仓库关联走
  Phase 88 `RepoAssociationService`；卡片 FSM 镜像 87/88 `@register_card_callback`。可复用本 plan 的
  `PlanDeepenService`/节点续驱范式（`node_execution_id` 续驱）。
- **89-03 容器挂起/resume**：复用 86 `SessionStore` + `build_resume_dispatch_env` + v0.8 callback resume +
  v0.12 durable；`CodingSession` 加 `SUSPENDED` + `parked_at`（plan-phase 已注记承载模型 A1 待 live 确认）。
- **89-04 建分支绑项目**：复用 `CreateBranchNode` server-local git + `ProjectBranchService.bind(source=PLAN)`；
  分支名固定格式 `{type}/{yymmdd}.m-{work_item_id}.{项目名}[-{版本号}]`，AI 仅定 type/版本号开关，
  server 权威拼装 + 正则兜底 + 卡片确认。
- **节点输出 handle**：`PlanDeepenNode` 暴露 `default`（DONE）/`clarifying`（等待）/`error`。终态 output
  携 `session_id` + `plan_version_id`，供下游分支/修订回路定位 canonical 方案。
- **未覆盖（deferred → 89-UAT）**：真机 runner+Docker explore 深化 / 真实飞书卡片多轮 / RESEARCH 飞书下行
  端到端（autonomous 链路以 seam/mock 覆盖，对齐 87/88）。
