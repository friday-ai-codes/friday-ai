# Phase 111: 蓝图底座（schema + 生命周期 + 线程/章程模型 + 质量基线）- Research

**Researched:** 2026-07-29
**Domain:** Django 数据模型 / jsonschema 校验 / 服务层状态机（纯后端，零前端、零编排流水线）
**Confidence:** HIGH（全部结论来自本 worktree 代码实读，带行号引用；无外部依赖新增）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Schema 模块与校验落位
- blueprint/v1 schema 模块放 `server/services/process_runtime/blueprint_schema.py` 新文件——与 `merged_plan.py` 平级但绝不修改它（§13.2 冻结纪律）
- schema 定义用 Python dict + `jsonschema` 校验，镜像 `server/workflows/schemas/technical_plan.py` 既有惯例（不引入 pydantic）
- 校验粒度：顶层必填（六段 + meta + requirement_spec + must_haves）+ 六段各自结构校验 + 引用完整性检查（block.citations 的 id 必须存在于文档级引用池；implementation_overview.items 的 feature_point_id 必须可解析到 requirement_spec）
- execution_plan 派生器：`server/services/process_runtime/blueprint_execution.py` 纯函数（blueprint dict → execution_plan list，按 repo 聚合 + depends_on/wave 拓扑），输出必须通过既有 `validate_technical_plan`（jsonschema），保证下游 coding dispatcher 零改动

#### 生命周期与评审人模型
- `blueprint_status` 落在 `delivery.Artifact` 新增 TextChoices 字段（11 态：researching/drafting/ai_reviewing/needs_clarification/pending_review/confirmed/implementing/implemented/archived/failed/superseded）；空值 = 旧 v0 数据，不参与状态机
- 转移守卫收口于 `server/delivery/services/blueprint_lifecycle_service.py`（镜像 `convergence_session_service` 的 INV-6 单一写入范式）；非法转移抛异常；`needs_clarification` 记录 `return_status`
- `pending_review → confirmed` 守卫：无 open+blocking 线程（查 BlueprintThread）
- 评审人 `delivery.BlueprintReviewer`：artifact FK + user FK（unique together）+ first_action + created_at；确认类动作自动 upsert
- 状态事件复用 `ConvergenceSessionEvent`，只新增 `blueprint_*` 事件类型常量，绝不改既有类型/字段（§13.2）；写事件 best-effort（观测不反噬业务）

#### 线程与章程模型
- `delivery.BlueprintThread` + `delivery.BlueprintThreadMessage` 两表；字段按 DESIGN §6.1（anchor JSONField 可空=全局线程、kind: ai_clarification/ai_review_finding/human_comment/repo_confirmation、severity、blocking、options、status: open/answered/resolved/dismissed、return_stage、initiated_by_user_id）
- 重锚定算法 `server/delivery/services/blueprint_anchor.py` 纯函数：block_id 精确匹配优先 → quoted_text difflib 模糊匹配（相似度阈值 0.85）→ 置 orphaned；失锚不删线程
- `RepoCharter` 落 `repositories` app：`OneToOneField(Repository)` 一仓一份 + version + source(ai_draft/human_confirmed) + confirmed_by + 结构化 JSONField（positioning/owned_domains/boundaries/placement_preferences/audience/form/evolution，形状按 DESIGN §5.7）
- 章程起草管道 `repositories/services/charter_service.py`：从 ai_summary/facets + 近期 MR/code_change 历史 + verified/rejected RepoAssociation 蒸馏 LLM 草案（source=ai_draft）；confirm API 置 human_confirmed；人工确认后 AI 只能提修订草案（新 draft 版本），绝不覆盖
- 章程 REST：repositories 既有 API 惯例下新增 charter 读取 / 草案生成 / confirm 端点

#### Golden set 与观测
- golden set 存 `server/tests/fixtures/blueprint_golden/*.json` + management command `evaluate_blueprint_golden` 离线运行；独立于 v0.19.0 的路由 golden set（不共文件、不产生冲突面）
- 首条 golden case：高三提分专项（期望 direct 仓集合 + 关键 feature_points），断言机制级
- 指标计算 `server/services/process_runtime/blueprint_quality.py` 纯函数：引用覆盖率（带 citations 的关键结论占比）、目标仓命中率（direct 集合对比期望）；AI 打回率/人审修改量/澄清轮次从 DB 统计（本相位留函数接口，数据由后续相位填充）
- `agents/call_source.py` 枚举新增 7 值：blueprint_decompose / blueprint_spec_gate / blueprint_repo_research / blueprint_reroute / blueprint_repo_plan / blueprint_merge / blueprint_ai_review；同步登记 `.planning/observability/LOGGING-SPEC.md` §4.1
- structlog 事件：blueprint_stage_started/completed/failed（duration_ms + category=caller + component=process_runtime）；LifecycleService 状态转移记 caller 事件绑定 initiated_by_user_id

### Claude's Discretion
- migration 拆分方式、索引设计、TextChoices 常量命名、测试组织结构、docstring 措辞等实现细节自行决定，遵循 CONVENTIONS.md 与既有 delivery/repositories app 风格。

### Deferred Ideas (OUT OF SCOPE)
- 段级细粒度编辑权限（初版全员可编辑 + 版本链审计，REQUIREMENTS Future）
- golden set 弱标签扩样（需采纳行为日志积累）
- 章程 charter_match 权重自动调参（Future）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHEMA-01 | 六段固定骨架 + 需求规格 + 验收锚点由 schema 强制，缺段/必填缺失无法过校验入库 | §落点地图 1（blueprint_schema.py）+ §现状事实 2.6（artifact registry 校验接线：`validate_content` 是 `ArtifactService.create/add_version` 的强制入口） |
| SCHEMA-06 | execution_plan 确定性派生且与现行 schema 一致，编码分发零改动 | §落点地图 2（blueprint_execution.py）+ §现状事实 2.5（`validate_technical_plan` 必填字段清单：id/name/repository_id/repository_name/branch_strategy） |
| SCHEMA-07 | 项目级一份活跃蓝图，多版本演进；版本间 block 级 diff | §落点地图 1（diff 纯函数落 blueprint_schema.py）+ §现状事实 2.1/2.2（ArtifactVersion 版本链与 content_hash 去重）+ §Pitfalls P10（Artifact 无 project FK 的事实） |
| LIFE-01 | 11 态生命周期，转移有守卫且可追溯 | §落点地图 5/6（blueprint_status 字段 + BlueprintLifecycleService）+ §现状事实 2.3（ConvergenceSessionService 的 CAS 单点收口范式逐行参考） |
| LIFE-02 | 阻塞澄清未清不可确认；确认动作自动入评审人名单 | §落点地图 4/6（BlueprintThread + BlueprintReviewer + confirm 守卫查询） |
| LIFE-03 | 失败/废弃显式终态，失败可重试 | §落点地图 6（状态机转移表含 failed→researching 重试边，见 DESIGN §4.2） |
| CHARTER-01 | 一仓一份版本化章程，AI 起草人工确认，人工内容不被 AI 覆盖 | §落点地图 8/9/10（RepoCharter model + charter_service + REST）+ §现状事实 2.7/2.8（蒸馏输入的三个数据源现状） |
| GATE-02 | golden set 与质量指标基线建立，退化可回归检出 | §落点地图 3/11/12（blueprint_quality.py + evaluate_blueprint_golden command + fixtures）+ §测试策略（call_command 测试范式） |
</phase_requirements>

## Summary

Phase 111 是纯后端数据与服务底座：三个 `services/process_runtime/` 新纯函数模块（schema 校验 / execution_plan 派生 / 质量指标）、delivery app 三个新模型加一个 Artifact 新字段与两个新 service、repositories app 一个新模型加一个 service 加三个 REST 端点、一个 management command 加 golden fixtures、call_source 枚举扩 7 值。与 v0.19.0 零文件交集（§13.2 冻结清单全程有效），所有既有文件改动收敛在 5 处小改（`delivery/artifacts/builtin_types.py` 校验器分支、`delivery/models/__init__.py` 与 `delivery/services/event_taxonomy.py` 追加、`repositories/models.py` 与 `repositories/urls.py` 追加、`agents/call_source.py` 追加）。

代码库已有全部所需范式的权威样板：jsonschema 校验镜像 `workflows/schemas/technical_plan.py`；状态机单点收口镜像 `convergence_session_service.py`（CAS 原子更新 + 非法转移抛 ValueError + fail 特判 + best-effort 事件）；LLM 起草管道镜像 `decompose_segments.py`（`ProviderConfigService.aresolve` → `build_chat_model` → `use_call_source` → best-effort 降级）；REST 镜像 `delivery/api/artifact_views.py`（adrf async APIView + `sync_to_async` 包 serializer）；command 测试镜像 `test_rebuild_repo_summaries.py`（`call_command` + StringIO）。

三个最关键的接线事实：(1) `ArtifactService.create/add_version` 会先过 `validate_content("technical_plan", content)`，而现注册校验器是严格 §7 schema（顶层必填 title/summary/execution_plan）——blueprint/v1 content 顶层没有 title/summary，**不改 `delivery/artifacts/builtin_types.py` 的校验器分支，蓝图 content 根本落不了库**；(2) `ConvergenceSessionEvent.session` 是非空 FK，蓝图生命周期事件必须挂在某个 ConvergenceSession 上，111 阶段无编排会话时事件写入需可跳过；(3) `event_taxonomy.ALL_EVENTS` 有覆盖性反查守护测试，新增 blueprint_* 常量不能直接塞进 ALL_EVENTS。

**Primary recommendation:** 严格按 CONTEXT 锁定的文件落点实施，全部新逻辑走新文件；既有文件只做「追加注册/追加分支」5 处小改；每个新聚合根按 app 惯例配 INV-6 grep 守护测试。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| blueprint/v1 schema 定义与校验 | 纯函数层（`services/process_runtime/`） | delivery artifact registry（接线） | 校验无 IO；registry 是 ArtifactService 的强制校验入口 |
| execution_plan 派生 | 纯函数层（`services/process_runtime/`） | — | 确定性、无 LLM、无 ORM |
| block 级 diff | 纯函数层（`services/process_runtime/`） | — | 两个 content dict 的比较，无 IO |
| 11 态生命周期 + 评审人 | 服务层（`delivery/services/`） | 数据层（delivery migration） | 状态写入必须单点收口（INV-6），带 DB CAS |
| 划线线程模型 | 数据层（delivery models + migration） | 服务层（confirm 守卫查询） | 111 只建模型与守卫查询；线程业务流转归 114 |
| 重锚定算法 | 纯函数层（`delivery/services/blueprint_anchor.py`） | — | 纯函数，输入旧 anchor + 新 blocks |
| RepoCharter 模型与起草 | 数据层 + 服务层（repositories app） | LLM（best-effort 单轮调用） | 章程是仓库域资产；LLM 只产草案 |
| charter REST | API 层（repositories views/urls） | — | 沿用 adrf async APIView + IsAuthenticated |
| golden set 评估 | management command（delivery app） | 纯函数层（blueprint_quality） | 离线运行，输出指标；不接 CI 之外的运行时 |
| 观测埋点 | 横切（structlog + call_source） | — | 常量登记 + 调用点标注 |

## 落点地图（新建/修改文件清单）

> 路径全部相对 worktree 根。「新建」= 全新文件；「修改」= 既有文件追加，改动面已注明。

### A. 纯函数层（services/process_runtime/，全新建）

| # | 文件 | 实现内容 |
|---|------|---------|
| 1 | `server/services/process_runtime/blueprint_schema.py`（新建） | ① `BLUEPRINT_SCHEMA_VERSION = "blueprint/v1"` 判别常量；② Python dict 形式的 blueprint/v1 jsonschema（顶层必填：meta/requirement_spec/六段/must_haves + citations 池；六段各自结构按 DESIGN §3.3–§3.14；Block/Citation 基元子 schema 复用）；③ `validate_blueprint(content) -> (bool, str|None)` 入口——先 jsonschema 结构校验，再 Python 后置引用完整性检查（block.citations 的 id ∈ 文档级 citations 池；implementation_overview.items[].feature_point_id ∈ requirement_spec.feature_points[].id）；jsonschema 表达不了跨节点引用，必须后置函数做；④ 判别逻辑：`content.get("schema_version") != "blueprint/v1"` 时视为 v0 直接 `(True, None)` pass-through（旧 MergedPlan 零迁移）；⑤ block 级 diff 纯函数（SC1 要求「新增/删除/修改块可辨识」）：按 block_id 对齐两个版本的 block 序列，产出 added/removed/modified 三组——落本文件（block 基元的属地）或平级 `blueprint_diff.py`，Claude's discretion |
| 2 | `server/services/process_runtime/blueprint_execution.py`（新建） | `derive_execution_plan(blueprint: dict) -> list[dict]` 纯函数：从 `implementation_overview.items` 按 `repository_id` 聚合 + `depends_on`/`wave` 拓扑排序；`coding_instruction` 由 item.how（Block[] 文本拼装，含 pseudocode）+ 相关规格/现状引用拼装；每个 task 必须补齐 `validate_technical_plan` 的必填字段：`id`/`name`/`repository_id`/`repository_name`（从 repo_associations 快照取名）/`branch_strategy`（蓝图无此概念，派生时给默认值如 `"feature"`，enum 只认 feature/hotfix/release）；`files` 从 items[].files_touched 映射（action 枚举 create/modify/delete，注意蓝图侧 change_type 有 4 值 indirect_refine 不在 files action 枚举内——files_touched.action 本来就是 3 值，直接透传）；输出整体（含 title/summary 顶层字段）必须过 `validate_technical_plan`，函数内断言或返回校验结果 |
| 3 | `server/services/process_runtime/blueprint_quality.py`（新建） | 纯函数指标：① `citation_coverage(blueprint) -> float`——关键结论（current_state_analysis.findings / repo_associations.rationale / impact_analysis.affected_features）中带非空 citations 的占比；② `target_repo_hit_rate(blueprint, expected_direct_repo_names) -> float`——direct 仓集合对比期望集合；③ AI 打回率/人审修改量/澄清轮次的 DB 统计**函数接口占位**（签名 + docstring + 返回 None/空实现或查询骨架，数据由 112–114 填充）。全部无 ORM 依赖的放前面，DB 统计接口单独隔离（可放同文件但注明依赖 delivery models 的懒 import） |

### B. delivery app（模型 + migration + service + 事件常量）

| # | 文件 | 实现内容 |
|---|------|---------|
| 4 | `server/delivery/models/blueprint_thread.py`（新建，文件名 discretion） | `BlueprintThread`：UUID pk + `artifact` FK(delivery.Artifact, CASCADE) + `created_on_version` FK(ArtifactVersion, SET_NULL/PROTECT discretion) + `anchor` JSONField(null=可空=全局线程；形状 {section_path, block_id, start_offset, end_offset, quoted_text}) + `anchor_status` TextChoices(anchored/orphaned) + `kind` TextChoices(ai_clarification/ai_review_finding/human_comment/repo_confirmation) + `severity` TextChoices(blocker/warning/info, blank) + `blocking` Bool + `options` JSONField(list) + `status` TextChoices(open/answered/resolved/dismissed) + `return_stage` CharField(researching/drafting/ai_reviewing, blank) + `initiated_by_user_id` CharField(64, default "system") + created_at/updated_at；索引至少 (artifact, status) 支撑 confirm 守卫查询。`BlueprintThreadMessage`：thread FK CASCADE + `author_type`(ai/human) + `author` FK(AUTH_USER_MODEL, SET_NULL null) + `body` TextField + created_at。镜像 `repo_association.py` 的模型层纪律：不写任何业务 create/save 方法 |
| 5 | `server/delivery/models/blueprint_reviewer.py`（新建，可与 #4 合文件，discretion） | `BlueprintReviewer`：UUID pk + `artifact` FK(CASCADE) + `user` FK(settings.AUTH_USER_MODEL, CASCADE) + `first_action` CharField（如 repo_confirmation/final_approve/final_reject/manual_add）+ created_at；`unique_together = (("artifact", "user"),)`。AUTH_USER_MODEL = "accounts.User"（settings.py L477）；FK 范式参照 `ConvergenceSession.created_by`（convergence_session.py L104-110） |
| 6 | `server/delivery/models/artifact.py`（修改，最小追加） | ① 新增 `BlueprintStatus(models.TextChoices)` 11 值（英文 snake_case 存库 + 中文 label）：researching/drafting/ai_reviewing/needs_clarification/pending_review/confirmed/implementing/implemented/archived/failed/superseded；② `Artifact` 追加 `blueprint_status = CharField(max_length=24, choices=..., blank=True, default="")`——空串 = 旧 v0 数据不参与状态机（max_length 须 ≥19 容纳 needs_clarification）；③ 视需要加 `models.Index(fields=["artifact_type", "blueprint_status"])`（discretion）。不动既有字段与枚举 |
| 7 | `server/delivery/migrations/0031_*.py`（新建，一个或多个） | 当前最新 = `0030_humantask.py`。内容：Artifact 加字段 + BlueprintThread/BlueprintThreadMessage/BlueprintReviewer 三表。拆分方式 discretion（单 migration 亦可）；依赖 `("delivery", "0030_humantask")`，user FK 自动带 accounts 依赖 |
| 8 | `server/delivery/services/blueprint_lifecycle_service.py`（新建） | 蓝图状态**唯一写入入口**（镜像 `convergence_session_service.py` 全套范式，逐条对应）：① 模块内 `_ALLOWED_TRANSITIONS: dict[str, set[str]]` 写死 DESIGN §4.2 全部合法边（含 failed→researching 重试、researching/drafting/pending_review/confirmed→superseded、needs_clarification→return_status 三向恢复）；② `transition(artifact, to_status, *, initiated_by_user_id, session=None, return_status=None)`——非法转移 `raise ValueError`（参照 convergence_session_service.py L157-162 的报错风格）；DB 写用 CAS：`Artifact.objects.filter(id=..., blueprint_status=from).update(...)`，命中 ≠1 抛 `ConcurrentTransitionError` 同款异常（参照 L219-227 / L45-51）；ORM 经 `sync_to_async`；③ `pending_review → confirmed` 守卫：`BlueprintThread.objects.filter(artifact=..., status="open", blocking=True).aexists()` 为 True 则拒绝；④ 进入 `needs_clarification` 时把 `return_status` 记下（落点 discretion：Artifact 加一列，或 thread.return_stage 已承载——CONTEXT 说「needs_clarification 记录 return_status」，最小实现是 lifecycle service 参数 + thread.return_stage，是否在 Artifact 加列由 planner 定）；⑤ 确认类动作自动 upsert `BlueprintReviewer`（`aupdate_or_create(artifact=, user=, defaults=...)`，first_action 只在首插时写）；⑥ 每次转移写 `ConvergenceSessionEvent`（blueprint_* 事件类型）**best-effort**：session 参数非 None 时才写行（session FK 非空约束，见 Pitfall P3），异常吞掉只 warning（参照 L316-324）；同时打 structlog caller 事件（event 名如 `blueprint_status_transitioned`，带 from/to/artifact_id/initiated_by_user_id/duration_ms，category=caller, component=process_runtime） |
| 9 | `server/delivery/services/blueprint_anchor.py`（新建） | `reanchor(anchor: dict, new_blocks: list[dict]) -> tuple[dict, str]` 纯函数（或批量版）：① block_id 精确匹配新版本 blocks → anchored；② 未命中时以 `difflib.SequenceMatcher(None, anchor["quoted_text"], block_text).ratio()` 找最佳块，阈值 ≥0.85 → 重挂新 block_id；③ 都失败 → `("orphaned")`，不删线程。stdlib difflib，无新依赖。111 只交付算法与单测；批量应用到线程行的调用方在 114 |
| 10 | `server/delivery/services/event_taxonomy.py`（修改，只追加） | 新增 `EVENT_BLUEPRINT_*` Final 常量（如 `blueprint.status.transitioned` 或 `blueprint.stage.started/completed/failed`——命名风格对齐既有 `technical_plan.merge.started` 的点分层级，前缀 `blueprint.`）。**不得加入 `ALL_EVENTS`**（它有覆盖性反查守护，见 Pitfall P4）；建议新建独立 `BLUEPRINT_EVENTS: Final[frozenset]` 常量集 + `__all__` 追加。既有常量/成员一律不动（§13.2 纪律 3） |
| 11 | `server/delivery/artifacts/builtin_types.py`（修改，校验器分支） | `_validate_technical_plan(content)` 改为判别分支：`content.get("schema_version") == "blueprint/v1"` → 调 `services.process_runtime.blueprint_schema.validate_blueprint`（函数内懒 import，保持既有惯例 L15/L21）；否则维持现状 `validate_technical_plan(content)`（v0 行为零变化）。**这是蓝图 content 能落 ArtifactVersion 的唯一接线点**（validate_content 是 ArtifactService.create/add_version 的强制入口，见现状事实 2.6）。renderer 分支本相位不做（markdown 渲染归 115/116） |

### C. repositories app（RepoCharter + service + REST）

| # | 文件 | 实现内容 |
|---|------|---------|
| 12 | `server/repositories/models.py`（修改，尾部追加） | repositories 的模型是**单文件模块**（非 models/ 包），新模型直接追加到文件尾部（与 `SensitiveFileSuggestion` L1005 之后并列）。`CharterSource(models.TextChoices)`：AI_DRAFT="ai_draft" / HUMAN_CONFIRMED="human_confirmed"。`RepoCharter`：UUID pk + `repository` OneToOneField(Repository, CASCADE, related_name="charter") + `version` PositiveIntegerField(default=1) + `source` CharField(choices=CharterSource) + `confirmed_by` FK(settings.AUTH_USER_MODEL, SET_NULL, null) + 结构化 JSONField 群（positioning CharField/TextField + owned_domains/boundaries/placement_preferences JSONField(list) + audience/form CharField + evolution CharField(active/maintenance_only/deprecated TextChoices)）+ `draft_content` JSONField（承载「人工确认后 AI 只能提修订草案」——见下）+ created_at/updated_at。**「AI 不覆盖人工」的存储语义**（CONTEXT 锁定行为、存储形状 discretion）：最小方案 = 单行模型 + `draft_content` JSONField 存 pending 修订草案（confirm 时草案内容提升为正式字段、version+1、source=human_confirmed；source 已是 human_confirmed 时 AI 起草只写 draft_content 绝不动正式字段）。多行版本表也可，但一仓一份 OneToOne + 草案列已满足 CHARTER-01 验收（版本化 = version 计数 + 草案/正式分离） |
| 13 | `server/repositories/migrations/0040_repo_charter.py`（新建） | 当前最新 = `0039_repository_git_instance_credential.py`；依赖 0039 + accounts（user FK 自动） |
| 14 | `server/repositories/services/charter_service.py`（新建） | 起草管道 + confirm 收口（RepoCharter 的**唯一写入入口**，配 INV-6 守护）：① `adraft_charter(repository_id, *, initiated_by_user_id)`——蒸馏输入三源：`Repository.ai_summary`（JSON 字符串，取 overview/能力树摘要，见现状事实 2.7）+ `Repository.facets`（语义分面「业务线/产品线、服务对象、技术形态」+ 事实分面「活跃度/关键程度/团队归属/技术栈」）+ 近期 MR 历史（`initiatives.MergeRequest.objects.filter(repository_id=...).order_by("-created_at")[:N]` 的 title/status）+ `initiatives.RepoAssociation`（verified 的 routed_reason 作 owned 证据、rejected 的作 boundaries 候选）——LLM 单轮产结构化草案（JSON 输出 + 归一化防御，全程镜像 `decompose_segments.py` 范式：`ProviderConfigService.aresolve()` → extra.default_model → `build_chat_model(resolved, model, streaming=False)` → `use_call_source(...)` → best-effort except 降级 None，见现状事实 2.9）；产出写 charter（无 charter 建 source=ai_draft；source=human_confirmed 时**只写 draft_content**）；② `aconfirm_charter(repository_id, user, *, edits=None)`——置 source=human_confirmed、confirmed_by、version+1、清 draft_content；③ structlog：charter_draft_started/completed/failed + charter_confirmed（caller，component 建议 repositories 或 charter_service，duration_ms + initiated_by_user_id）。call_source 注意：CONTEXT 锁定的 7 个新枚举值里**没有** charter 起草专用值——用 7 值之外的既有值不合适，这是一个 CONTEXT 缺口，见 Open Questions Q1 |
| 15 | `server/repositories/charter_views.py`（新建）+ `server/repositories/urls.py`（修改，追加 path） | 三端点（adrf async APIView + `IsAuthenticated`，镜像 `delivery/api/artifact_views.py` 范式：async get/post + `sync_to_async` 包 serializer `.data`）：`GET /api/repositories/<uuid:repository_id>/charter/`（读取，无则 404 或返回空骨架，discretion）；`POST .../charter/draft/`（触发 AI 起草，返回草案）；`POST .../charter/confirm/`（人工确认，body 可带编辑后的字段）。urls.py 落点：追加到 router include 之后的 `<uuid:repository_id>/xxx/` 资源子路由区（参照 urls.py L149-320 的既有排布；charter 是字面段子路由，与 uuid 通配不冲突）。serializer 放 `serializers.py` 追加或 view 内联 discretion |

### D. 观测与质量基线

| # | 文件 | 实现内容 |
|---|------|---------|
| 16 | `server/agents/call_source.py`（修改，只追加枚举成员） | `CallSource` 追加 7 值：`BLUEPRINT_DECOMPOSE = "blueprint_decompose"` / `BLUEPRINT_SPEC_GATE = "blueprint_spec_gate"` / `BLUEPRINT_REPO_RESEARCH = "blueprint_repo_research"` / `BLUEPRINT_REROUTE = "blueprint_reroute"` / `BLUEPRINT_REPO_PLAN = "blueprint_repo_plan"` / `BLUEPRINT_MERGE = "blueprint_merge"` / `BLUEPRINT_AI_REVIEW = "blueprint_ai_review"`，每值带注释（沿用既有成员的「phase 来源 + 用途」注释风格 L66-107）；类 docstring 的「36 值」计数同步改 43。无枚举计数守护测试（已验证 `tests/test_model_usage_call_source.py` 无 len 断言），normalize 自动兼容新值 |
| 17 | `.planning/observability/LOGGING-SPEC.md`（修改） | §4.1 call_source 表追加同 7 行（表在 L62-66 起始区域）；§5/§10 视需要登记 blueprint_* structlog 事件名 |
| 18 | `server/delivery/management/commands/evaluate_blueprint_golden.py`（新建，含 `management/__init__.py` + `management/commands/__init__.py`） | delivery app 当前**无** management/ 目录（全仓 43 个 command 分布在其他 app，见测试策略）。command 职责：遍历 `server/tests/fixtures/blueprint_golden/*.json`，每个 case 含蓝图样例 + 期望（expected_direct_repos / 关键 feature_points / 引用覆盖率下限）；对每 case 跑 `validate_blueprint` + `derive_execution_plan` + `blueprint_quality` 指标，输出逐例结果与汇总；断言机制级（如「引用覆盖率 ≥ 基线」「direct 集合命中 ≥ 期望」），失败以非零码退出（CommandError）；同输入重复运行结果一致（全程纯函数，无 LLM、无网络——离线可跑）。放 delivery（蓝图 artifact 属地）而非 repositories，discretion 可改 |
| 19 | `server/tests/fixtures/blueprint_golden/first_case_gaokao_boost.json`（新建，命名 discretion） | 首条 golden case：高三提分专项——完整 blueprint/v1 样例 content（六段齐全、citations 完备、repo_associations 含期望 direct 仓集合如 onion-learning/study-course 等）+ expected 块（direct 仓集合 + 关键 feature_points + 指标下限）。fixtures 目录已有 `layered_search_golden/`、`hybrid_graph_capable_golden/` 先例（.txt），本目录用 .json（CONTEXT 锁定）；与 v0.19.0 路由 golden set（在另一 worktree，本 worktree 无该目录）零交集 |

### E. 测试（新建，组织见 §测试策略）

- `server/tests/services/test_blueprint_schema.py`（缺段拒绝 / 六段齐全通过 / v0 pass-through / 引用完整性 / block diff）
- `server/tests/services/test_blueprint_execution.py`（聚合 + 拓扑 + 输出过 validate_technical_plan + 确定性）
- `server/tests/services/test_blueprint_quality.py`（覆盖率/命中率边界）
- `server/tests/delivery/test_blueprint_models.py`（模型形状 + unique 约束）
- `server/tests/delivery/test_blueprint_lifecycle_service.py`（11 态合法/非法转移矩阵 + confirm 阻塞守卫 + reviewer upsert + CAS 并发拒绝 + failed 重试）
- `server/tests/delivery/test_blueprint_inv6_guard.py`（BlueprintThread/BlueprintThreadMessage/BlueprintReviewer + Artifact.blueprint_status 字段赋值的旁路守护，镜像 test_artifact_inv6_guard.py 范式）
- `server/tests/delivery/test_blueprint_anchor.py`（精确/模糊/失锚三分支 + 0.85 阈值边界）
- `server/tests/repositories/test_charter_model.py` / `test_charter_service.py`（AI 草案 → confirm → 再起草只进 draft_content 的「不覆盖」不变量）/ `test_charter_api.py`
- `server/tests/delivery/test_evaluate_blueprint_golden.py`（call_command 范式）
- `server/tests/repositories/test_charter_inv6_guard.py`（RepoCharter 单一 writer 守护，discretion 并入 charter 测试文件）

## 现状事实（带行号引用）

### 2.1 Artifact / ArtifactVersion（宿主模型）

`server/delivery/models/artifact.py`：
- `ArtifactStatus` L26-33：draft/under_review/approved/superseded/archived（与新 BlueprintStatus 是**两个正交字段**，见 DESIGN §4.3 映射表）。
- `Artifact` L45-95：UUID pk；`artifact_type` CharField(40) L53；`work_item` FK 可空 SET_NULL L55-61；`status` CharField(16) L65-69；`current_version` FK→ArtifactVersion（SET_NULL，related_name="+"）L72-78；`created_by_user_id` CharField(64) L80；db_table `delivery_artifact` L86；索引 `[artifact_type, status]` / `[work_item]` L89-92。**没有 project FK**——蓝图的项目归属只在 `content.meta.project_id`（DESIGN §3.4），见 Pitfall P10。
- `ArtifactVersion` L98-145：`artifact` FK CASCADE related_name="versions" L104-108；`version_no` L109；`supersedes` self-FK L110-116；`content` JSONField L117；`content_hash` sha256 hex L119；`produced_by_session_id`（字符串软引用）L122；`produced_by_ref` L124；`approval_status` L126-130；`unique_together (artifact, version_no)` L138；索引 `[artifact, -version_no]` / `[content_hash]` L139-142。版本链 + hash 去重已就绪，**SCHEMA-07 的多版本演进零建模成本**，111 只需补 block 级 diff 纯函数。

### 2.2 ArtifactService（写入唯一入口）

`server/delivery/services/artifact_service.py`：
- `create` L53-84：**先** `validate_content(artifact_type, content)` L65-67，不过则抛 `ArtifactContentInvalid`；然后 `_create_sync` L86-115（`@sync_to_async` + `transaction.atomic`，建 Artifact + v1 + 置 current_version）。
- `add_version` L117-134：同样先 `validate_content` L126-130；`_add_version_sync` L136-162 内 hash 相等复用 current 不翻版本 L148-149，否则 `supersedes=current` 建新版并推进。
- `_content_hash` L43-47：`sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")))`。
- INV-6 守护：`server/tests/delivery/test_artifact_inv6_guard.py` 的 `_ALLOWED_WRITER = "delivery/services/artifact_service.py"` L42；扫描 pattern L57-65 锚定 `Artifact.objects.(create|bulk_create|get_or_create|update_or_create)` 与 `Artifact(` 实例化——**`Artifact.objects.filter(...).update(...)` 不在 pattern 内**，BlueprintLifecycleService 用 CAS `.filter().update()` 改 `blueprint_status` 不会误触该守护（但要新建自己的守护测试声明第二 writer 的字段边界，见 Pitfall P2）。

### 2.3 ConvergenceSessionService（INV-6 状态机范式，逐行参考）

`server/delivery/services/convergence_session_service.py`：
- `ConcurrentTransitionError` L45-51：CAS 命中 ≠1 的专用异常。
- `transition` L126-189：非法转移 `raise ValueError`（含合法 event 清单的报错文案）L157-162；status 派生规则 L164-176。
- `_apply_transition_sync` L191-237：CAS 核心 `ConvergenceSession.objects.filter(id=..., current_stage=from_stage).update(**values)`，`updated != 1` 抛异常 L219-227，然后同步内存态 L228-237。
- `_fail` L239-273：终态幂等 no-op（保留首因）L247-258 + CAS 失败后 `_refresh_status_sync` 放弃 L260-271。
- `_emit_event` L304-324：先 structlog（category=sampling）再 `_persist_event`，**try/except 吞掉持久化失败只 warning**（best-effort 范本）L316-324；`_persist_event` L326-335 是 ConvergenceSessionEvent 的唯一写入点（模型 docstring L9-10 声明该约定，**无 grep 守护测试**——已验证 tests 下无 ConvergenceSessionEvent 的 INV-6 扫描）。

### 2.4 ConvergenceSessionEvent 与事件 taxonomy

- `server/delivery/models/convergence_session_event.py` L21-56：`session` FK **非空** CASCADE related_name="events" L29-33；`event` CharField(64) 开放集 L35；`work_item` UUID 软引用 L37；`payload` JSONField L39；`ts` L41；append-only ordering L49；索引 `[session, ts]` / `[event]` L50-53。
- `server/delivery/services/event_taxonomy.py`：`EVENT_*` Final 常量 L47-73（命名风格 `technical_plan.merge.started` 点分层级）；`ALL_EVENTS` frozenset L76-92（守护测试基准）；`RESERVED_EVENTS` L95-101（「已定义但非本 phase 产出」的先例——blueprint 常量照此思路独立成集）；`build_envelope` L104-118。
- 守护测试 `server/tests/services/test_event_taxonomy_alignment.py`：L104-118 断言扫描文件（engine.py/research_adapter.py/architect_merge_adapter.py/callbacks.py，见 L22-25）的 emit 引用 ⊆ ALL_EVENTS；L121-141 **覆盖性反查**——ALL_EVENTS 每个事件必须登记 producer 且被 emit。→ blueprint 常量**不能进 ALL_EVENTS**（111 的 emit 点 blueprint_lifecycle_service.py 不在扫描清单，放进去必挂反查）。

### 2.5 execution_plan 既有 schema（派生器的输出契约）

`server/workflows/schemas/technical_plan.py`：
- `TECHNICAL_PLAN_JSON_SCHEMA` L63-204：顶层 required `["title", "summary", "execution_plan"]` L68；execution_plan 每项 required `["id", "name", "repository_id", "repository_name", "branch_strategy"]` L101-107；`branch_strategy` enum `["feature", "hotfix", "release"]` L129-133；`files[].action` enum `["create", "modify", "delete"]` L149-153；`dependencies` list[str] L161-165。
- `validate_technical_plan` L207-222：返回 `(bool, str|None)`——派生器输出的验收函数，直接复用。
- ⚠️ `dict_to_technical_plan` L225-279 是**陈旧代码**：L272 传参 `spaces=data.get("projects", [])` 但 dataclass 字段名是 `projects`（调用即 TypeError）；全仓无调用点（仅 `workflows/schemas/__init__.py` 再导出）。派生器**只用 `validate_technical_plan`，勿碰 `dict_to_technical_plan`**。

### 2.6 artifact type registry（蓝图校验的接线点）

- `server/delivery/artifacts/registry.py`：`register_artifact_type` L31-40；`validate_content` L55-62（未注册类型直接拒绝）。
- `server/delivery/artifacts/builtin_types.py` L14-30：`technical_plan` 的 validator = `validate_technical_plan`（懒 import 范式 L15），renderer = `render_merged_plan_markdown` L21。注册靠 `delivery/artifacts/__init__.py` L7-8 的 import 副作用（import 任何 `delivery.artifacts.*` 子模块都会先执行包 init，注册必然生效）。
- **关键推论**：blueprint/v1 content 顶层没有 title/summary（在 meta 里，DESIGN §3.3/§3.4），现行严格 §7 校验器必拒——蓝图落库的前置是改 `builtin_types._validate_technical_plan` 为 schema_version 分支（落点地图 #11）。DESIGN §3.1 明确不新增 artifact_type，排除「注册新类型」路线。

### 2.7 Repository 模型（章程蒸馏的输入面）

`server/repositories/models.py`（**单文件模块**，共 25 个类，最后一个 `SensitiveFileSuggestion` L1005）：
- `ai_summary` TextField L323（**JSON 字符串**：`overview_text` property L354-370 解析其 `overview` 字段，非 JSON 时取原文）；`ai_summary_status` L324-328；`ai_summary_tree` JSONField L336（PageIndex 化能力树，节点含 node_id/node_type/title/summary/keywords/paths）；`is_monorepo` L337；`facets` JSONField L340（`{dimension: value}` + `_pinned` 列表）；`tree_stale_state` L343；db_table `"repositories"` L346。
- facets 维度：语义分面 `SEMANTIC_FACET_DIMENSIONS = ("业务线/产品线", "服务对象", "技术形态")`（summary_service.py L37）；事实分面 `活跃度/关键程度/团队归属/技术栈`（facet_service.py L26-29）。DESIGN §5.7 的 `audience`/`form` 分别对齐「服务对象」「技术形态」。
- 最新 migration：`0039_repository_git_instance_credential.py` → RepoCharter 是 **0040**。
- `repositories/services/` 子包已存在（`__init__.py` 只有 docstring，列了 index_cleanup 一个模块）——charter_service.py 落这里，`__init__` docstring 顺手补一行。

### 2.8 RepoAssociation 与 MergeRequest（蒸馏的另两路输入）

- `server/initiatives/models/repo_association.py`：`RepoAssociationStatus` L30-37（proposed/confirmed/verifying/verified/rejected）；`RepoAssociation` L40-92——`project` FK L46-50、`repository` FK L60-64、`score` L71、`confidence` L72、`routed_reason` TextField L73、`matched_node_paths` JSONField L75、`unique_together (project, repository)` L85。蒸馏取材：`status=verified` 行的 routed_reason（owned 证据）、`status=rejected` 行（boundaries 候选）。
- `server/initiatives/models/merge_request.py`：`MergeRequest` L37-114——`repository` FK 可空 L49-56、`title` L72、`status`（open/merged/closed）L79-84、created_at ordering L99。近期 MR 历史 = `MergeRequest.objects.filter(repository_id=...).order_by("-created_at")[:N]`。
- 备选证据源：`knowledge.models.EntityKind.CODE_CHANGE = "code_change"`（knowledge/models.py L43）+ `KnowledgeEntity.repository` FK L168——若要拉 code_change 历史可用，但 MR 实体已够 111 的草案管道，勿过度取材（discretion）。

### 2.9 LLM 调用惯例（charter 起草管道的样板）

`server/services/process_runtime/decompose_segments.py` L134-212 是完整权威样板：
- `ProviderConfigService.aresolve()` L165 → `resolved.extra.default_model` L166（无 model 降级 return None L167-174）；
- `build_chat_model(resolved, model_name, streaming=False)` L176（签名见 `agents/llm_factory.py` L64-75）；
- `with use_call_source(CallSource.X):` 包住 `await model.ainvoke(messages)` L181-182；
- LLM 文本 → JSON 健壮解析（```json 代码块 + 裸 JSON 双路）L55-71 + 归一化防御函数 L74-105；
- structlog started/completed/failed 三事件带 duration_ms L157-163/L186-202/L204-212；失败 `redact_secrets_in_text(str(exc))` L209 后 warning，**best-effort return None 绝不抛**。

### 2.10 REST 惯例

- 挂载：`/api/repositories/` → `repositories.urls`（friday/urls.py L34）；`/api/delivery/` → `delivery.urls`（L82）。
- `repositories/urls.py`：adrf `DefaultRouter` 注册 RepositoryViewSet L59-60；**字面段路由必须在 router include 之前**（L63-64 注释），`<uuid:repository_id>/xxx/` 资源子路由在 router include 之后 L149-322。charter 三端点属后者。
- view 范式：`delivery/api/artifact_views.py`——adrf `APIView` + `permission_classes = [IsAuthenticated]` L65 + `async def get` L67 + **`.data` 一律 `sync_to_async` 包裹**（docstring L12-13 明文纪律，用法 L95-97）+ 非法 UUID 前置 400 L68-81 + 不存在 404 中性消息 L116-119。repositories/views.py 同栈（adrf imports L11-12，IsAuthenticated L19，超管另有 `permissions.api_permissions.IsSuperUser` L25）。

### 2.11 call_source 现状

`server/agents/call_source.py`：`CallSource(str, Enum)` L37-107 现 **36 值**（类 docstring L38 声明计数）；`normalize` L109-123 非法值回退 unknown；`use_call_source` contextmanager L142-149。新值 = 直接追加成员 + 注释，**无枚举计数守护测试**（`tests/test_model_usage_call_source.py` 已查无 len 断言）。

### 2.12 migration / app / 配置杂项

- delivery 最新 migration `0030_humantask.py`（31 个文件）；delivery app 无 management/ 目录；`delivery/models/__init__.py` 是 curated re-export（新模型需追加 import + `__all__`）。
- `AUTH_USER_MODEL = "accounts.User"`（friday/settings.py L477）；INSTALLED_APPS L89-133 已含 delivery/repositories/initiatives/agents，**无需注册新 app**。
- `jsonschema>=4.23.0` 已是直接依赖（server/pyproject.toml L51）；`difflib` stdlib；**无 ulid 库**——DESIGN 的 `blk_01JC5X…` ULID 是风格示例，schema 校验对 block_id 只做非空字符串（或宽 pattern）校验即可，golden fixtures 手写 id，不引新依赖。
- pytest：`asyncio_mode = "auto"`、`--disable-socket`、默认排除 `perf/integration/slow/postgres_queue` markers（pyproject L112-126）；factory-boy 在 dev 依赖 L105 但主流测试直接 `Model.objects.create`。

## Architecture Patterns

### Pattern 1: INV-6 单一 writer service + grep 守护
**What:** 每个聚合根一个 service 收口全部写入；纯源码正则扫描测试断言无旁路。
**参照:** `convergence_session_service.py`（CAS 状态机）、`test_artifact_inv6_guard.py`（守护测试结构：_ALLOWED_WRITER + patterns + 豁免清单 + 「守护的守护」）。
**111 应用:** BlueprintLifecycleService（blueprint_status + BlueprintThread/Message/Reviewer 的 writer）、CharterService（RepoCharter 的 writer），各配守护测试。

### Pattern 2: 注册式 artifact 校验（新类型/新形状零改 service）
**What:** `register_artifact_type(type, validator, renderer)`，ArtifactService 统一走 `validate_content`。
**111 应用:** 不注册新类型，只给 `technical_plan` 的 validator 加 schema_version 分支（DESIGN §3.1 锁定沿用 technical_plan）。

### Pattern 3: 纯函数模块 + 懒 import
**What:** process_runtime 的校验/派生模块只依赖 stdlib + jsonschema，跨层引用（如 workflows.schemas）顶层 import，重依赖（LLM/ORM）函数内懒 import。
**参照:** `merged_plan.py`（顶层仅 import validate_technical_plan，docstring 声明 INV-3 边界）、`builtin_types.py`（函数内懒 import）。

### Pattern 4: TextChoices 闭集 + 英文值中文 label
**参照:** `ArtifactStatus` L26-33、`RepoAssociationStatus` L30-37。111 的 BlueprintStatus/CharterSource/thread 各枚举照此。

### Anti-Patterns to Avoid
- **旁路写表**：任何新模型不在模型层写业务 create/save（`repo_association.py` L17-18 的纪律声明是范本）。
- **raw async 直查 ORM**：async 上下文一律 `sync_to_async` 或 Django async API（afirst/aexists/asave/aupdate_or_create）。
- **在既有枚举上扩值**：ArtifactStatus/ConvergenceSessionStatus 一个值都不加（§13.2）；蓝图 11 态是**新字段新枚举**。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON 结构校验 | 手写字段遍历校验 | `jsonschema` 4.23（已有依赖）+ Draft 2020-12 | technical_plan.py 先例；错误信息现成 |
| execution_plan 输出验收 | 自写第二份 execution schema | `validate_technical_plan`（workflows/schemas/technical_plan.py L207） | CONTEXT 锁定；保证 dispatcher 零改动 |
| 文本相似度（重锚定） | 自研编辑距离 | stdlib `difflib.SequenceMatcher.ratio()` | 阈值 0.85 是 CONTEXT 锁定值；零依赖 |
| content 去重 | 自写版本比较 | `ArtifactService.add_version` 的 content_hash 机制（L136-162） | 已就绪，hash 相等不翻版本 |
| LLM JSON 输出解析 | 从零写解析 | 镜像 `decompose_segments._parse_segments_json` L55-71 + 归一化函数 | 处理 ```json 代码块/裸 JSON/reasoning content_blocks 三态 |
| 状态机并发安全 | select_for_update / 乐观锁自研 | CAS `filter(id=..., <state>=from).update(...)` 命中计数判定 | convergence_session_service L219-227 先例（WR-01） |

## Common Pitfalls

### P1: async ORM 桥接遗漏
**What goes wrong:** service/view 的 async 路径直接碰 ORM → `SynchronousOnlyOperation`。
**How to avoid:** 写路径统一 `@sync_to_async` + `transaction.atomic`（artifact_service L86-115 范式）；读路径用 async API（`afirst`/`aexists`/`aupdate_or_create`，facet_service L48/L65 先例）；REST serializer `.data` 必须 `sync_to_async` 包（artifact_views L95-97）。confirm 守卫的线程查询用 `aexists()`。

### P2: INV-6 边界——谁能写 Artifact.blueprint_status
**What goes wrong:** 既有守护只锚定 `Artifact.objects.create/...` 与 `Artifact(` 实例化（test_artifact_inv6_guard.py L57-65），`.filter().update()` 不触发——lifecycle service 的 CAS 写不会挂既有守护，但「ArtifactService 是 Artifact 唯一 writer」的文档语义被打破。
**How to avoid:** 计划里显式声明：ArtifactService 仍是 Artifact **行创建/版本/status** 的唯一 writer；BlueprintLifecycleService 是 **blueprint_status 字段**的唯一 writer（模型 docstring L13 与新守护测试同步声明字段级分工，镜像 `test_inv6_guard.py` 里 feishu_chat_id 的「字段级守护」先例 L159-180）。
**Warning signs:** 任何第三处出现 `blueprint_status=` 赋值。

### P3: ConvergenceSessionEvent.session 非空 FK
**What goes wrong:** 111 的状态转移多发生在无编排会话的场景（测试/golden 运行/后续人工操作），直接写事件行会因 session 非空约束失败。
**How to avoid:** lifecycle service 的事件写入签名带 `session: ConvergenceSession | None = None`——有 session 才落 ConvergenceSessionEvent 行（payload 带 artifact_id/from/to/initiated_by_user_id），无 session 只打 structlog；整体 try/except 吞异常（best-effort，CONTEXT 锁定「观测不反噬业务」）。**绝不给 event 模型加可空 artifact 字段**（改既有表 = 违反 §13.2 纪律 3）。

### P4: event_taxonomy 守护测试的覆盖性反查
**What goes wrong:** 把 `blueprint.*` 常量加进 `ALL_EVENTS` → `test_all_events_each_emitted_by_producer`（test_event_taxonomy_alignment.py L121-141）要求登记 producer 且 emit 点可扫描到，而 111 的 emit 点（blueprint_lifecycle_service.py）不在其扫描文件清单（L22-25）→ 必挂。
**How to avoid:** 新常量放独立 `BLUEPRINT_EVENTS` frozenset（镜像 `RESERVED_EVENTS` L95-101 的「已定义但不计入 ALL_EVENTS」先例）；既有 ALL_EVENTS 成员一个不动。

### P5: TextChoices 值冲突与 max_length
**What goes wrong:** BlueprintStatus 与 ArtifactStatus 共存同表——两个字段两套枚举，值有重叠（superseded/archived）但列不同不冲突；真正的坑是 `needs_clarification` 长 19 字符，CharField(16)（照抄 status 字段长度）会截断。
**How to avoid:** `blueprint_status = CharField(max_length=24, ...)`；blank=True + default=""（空串 = v0 旧数据不参与状态机，CONTEXT 锁定）。同理 thread.kind 的 `ai_review_finding`（17 字符）、`repo_confirmation`（17 字符）也要 max_length ≥20。

### P6: jsonschema 校验性能
**What goes wrong:** 每次 `jsonschema.validate(data, SCHEMA)` 都重新编译 schema；蓝图 schema 大（六段全结构），golden 评估与 add_version 高频调用时浪费明显。
**How to avoid:** 模块级预编译 `_VALIDATOR = jsonschema.Draft202012Validator(BLUEPRINT_SCHEMA)` 一次构建，调用 `_VALIDATOR.iter_errors(data)`/`.validate(data)` 复用（technical_plan.py 用的是便捷函数 L219，蓝图 schema 体量大得多，建议升级为预编译；这不违反「镜像既有惯例」——惯例指 dict + jsonschema 而非 pydantic）。引用完整性（citations id 解析 / feature_point_id 解析）jsonschema 表达不了，必须后置 Python 检查，合并进 `validate_blueprint` 返回统一 `(bool, str|None)`。

### P7: §13.2 冻结清单（planner 不得规划改动以下文件）
1. `server/codegraph/services/repo_router_v2.py` — 路由核心归 v0.19.0 独占。
2. 既有 `technical_plan` process 六文件**只读冻结**：`server/services/process_runtime/decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py`。
3. `ConvergenceSessionEvent` 既有事件类型与 payload 字段：只新增 `blueprint_*` 类型常量，不改模型字段、不改既有常量。
4. 前端只新建不改旧（111 无前端触面，自然满足）。
5. `builtin_processes.py` 本相位也不需要动（111 不注册新 process；那是 112/113 的事，且届时仅加注册项）。
6. migration 纪律：0.20 侧新增 migration 在同步点 rebase 时可能需重新生成序号——migration 文件命名带语义 slug（如 `0031_blueprint_models.py`）便于重排。

### P8: 陈旧代码 `dict_to_technical_plan`
`workflows/schemas/technical_plan.py` L272 的 `spaces=` 传参与 dataclass 字段 `projects` 不符（调用即 TypeError），全仓无调用点。派生器只依赖 `validate_technical_plan`；**不要顺手修它**（超范围，且属 workflows 域）。

### P9: 派生器的字段补齐义务
blueprint items 没有 `branch_strategy`/`repository_name`/顶层 `title/summary`——派生函数必须自行补齐（branch_strategy 默认 `"feature"`；repository_name 从 `repo_associations` 快照查；title/summary 从 meta 取）。漏一个，`validate_technical_plan` 立刻拒绝（required 清单见现状事实 2.5）。

### P10: Artifact 无 project FK
「一个项目一份活跃蓝图」（SCHEMA-07）的项目归属只存 `content.meta.project_id`，DB 无法直接索引查询。111 的验收不要求按项目检索（那是 115/116）；唯一性守卫属 lifecycle/创建入口职责，而创建入口在 112+。**111 不要为此加字段/约束**（避免过度设计与 rebase 冲突面）；若 planner 认为需要占位，最多在 lifecycle service docstring 记录该约束由后续相位在创建路径守卫。

### P11: charter「AI 不覆盖人工」的不变量测试
**What goes wrong:** 起草管道在 source=human_confirmed 时误写正式字段。
**How to avoid:** service 层单点判断 + 专测不变量：`human_confirmed` 状态下调用 `adraft_charter` 后，正式字段逐一相等、只有 `draft_content` 变化。镜像 `ProjectMemory`「AI 不覆盖人工」原则（DESIGN §5.7）。

## 测试策略

- **组织**：`server/tests/<app>/test_*.py`（delivery 53 个 / repositories 46 个先例）；process_runtime 纯函数测试放 `server/tests/services/`（`test_decompose_segments.py` 先例）。无 `__init__.py` 需求（pytest rootdir 配置 pyproject L112-117）。
- **fixture 惯例**：直接 `Model.objects.create(...)` 建数据（`test_rebuild_repo_summaries._make_repo` L15-22 范式）；factory-boy 可用但非强制。delivery 测试共享 seam 在 `tests/delivery/conftest.py`（mock_embedding/mock_qdrant_client 等，111 用不到向量 seam）。
- **async 测试**：`asyncio_mode = "auto"`——async def 测试直接写，`@pytest.mark.django_db` 配合（`test_artifact_service.py` 先例：`@pytest.mark.django_db` + `@pytest.mark.asyncio` 双标；auto 模式下后者可省）。
- **management command 测试**：`call_command("evaluate_blueprint_golden", stdout=StringIO())` + 断言输出文本 + `pytest.raises(CommandError)` 断言失败路径（`test_rebuild_repo_summaries.py` L25-59 逐行范式）。
- **LLM mock**：charter_service 测试 patch `build_chat_model` 或注入 fake response（`tests/helpers/fake_chat_model.py` 已有 FakeChatModel 可复用；`test_decompose_segments.py` 演示 patch 点）。全局 `--disable-socket` 兜底。
- **INV-6 守护**：镜像 `test_artifact_inv6_guard.py` 结构（_ALLOWED_WRITER 常量 + 正则 patterns + `_is_scanned` 剪枝 + 「writer 确实在写」的守护有效性断言）。
- **网络隔离**：golden 评估 command 全程纯函数无网络，天然过 `--disable-socket`。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ≥9.0.2 + pytest-asyncio（auto）+ pytest-django ≥4.8 |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]`（L112-126） |
| Quick run command | `cd server && uv run pytest tests/delivery/test_blueprint_lifecycle_service.py -x -q`（单文件 <30s） |
| Full suite command | `cd server && uv run pytest`（默认排除 perf/integration/slow/postgres_queue） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHEMA-01 | 缺段/缺必填被拒；六段齐全通过并落 ArtifactVersion | unit + integration | `uv run pytest tests/services/test_blueprint_schema.py tests/delivery/test_blueprint_artifact_wiring.py -x` | ❌ Wave 0 |
| SCHEMA-06 | 派生输出过 validate_technical_plan；同输入同输出 | unit | `uv run pytest tests/services/test_blueprint_execution.py -x` | ❌ Wave 0 |
| SCHEMA-07 | 两版本 block 级 diff 可辨识新增/删除/修改 | unit | `uv run pytest tests/services/test_blueprint_schema.py -k diff -x` | ❌ Wave 0 |
| LIFE-01 | 11 态合法/非法转移矩阵 + CAS 并发拒绝 | unit (django_db) | `uv run pytest tests/delivery/test_blueprint_lifecycle_service.py -x` | ❌ Wave 0 |
| LIFE-02 | open+blocking 线程阻塞 confirm；确认动作 upsert reviewer | unit (django_db) | 同上 `-k "confirm or reviewer"` | ❌ Wave 0 |
| LIFE-03 | failed/superseded 终态；failed→researching 重试 | unit (django_db) | 同上 `-k "failed or superseded"` | ❌ Wave 0 |
| CHARTER-01 | 草案蒸馏（mock LLM）→ confirm 生效 → 不覆盖不变量 | unit (django_db) + api | `uv run pytest tests/repositories/test_charter_service.py tests/repositories/test_charter_api.py -x` | ❌ Wave 0 |
| GATE-02 | golden command 离线可跑、指标输出、重复运行一致 | command test | `uv run pytest tests/delivery/test_evaluate_blueprint_golden.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 对应新测试文件单跑（`-x -q`）。
- **Per wave merge:** `uv run pytest tests/delivery/ tests/repositories/ tests/services/ -q`。
- **Phase gate:** 全量 `uv run pytest` 绿 + `python manage.py makemigrations --check --dry-run` 无缺失 migration。

### Wave 0 Gaps
- [ ] 上表全部测试文件（本相位全新建）
- [ ] `server/tests/fixtures/blueprint_golden/` 目录与首条 case fixture
- 框架无缺口：pytest/pytest-asyncio/factory-boy/jsonschema 全部已装。

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（复用既有 JWT/中间件） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | charter 三端点 `IsAuthenticated`（repositories 既有 view 同级；不引入更细权限——CONTEXT/§6.4 低门槛决策）；写操作绑定 `request.user` 落 confirmed_by/initiated_by_user_id |
| V5 Input Validation | yes | jsonschema 校验即入库门（ArtifactContentInvalid 拒绝）；REST body serializer/显式字段白名单；UUID path 参数 Django converter 天然校验 |
| V6 Cryptography | no（无新凭证/密钥面） | — |

### Known Threat Patterns for Django/DRF
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM 异常文本泄漏上游响应/凭证 | Information Disclosure | `redact_secrets_in_text` 包异常文本（decompose_segments L209 先例；观测规范强制） |
| call_source 维度基数污染 | Tampering | `CallSource.normalize` 已有回退（L109-123），新值进受控枚举即可 |
| 状态机 TOCTOU 并发双写 | Tampering | CAS filter+update 命中计数（convergence_session_service WR-01 先例） |
| golden fixtures 注入执行 | Tampering | fixtures 只作数据读入纯函数，无 eval/无模板渲染 |

## Environment Availability

本相位无新增外部依赖：`jsonschema>=4.23.0`（pyproject L51，已装）、`difflib`（stdlib）、pytest 栈（已装）。数据库用测试默认 SQLite 即可（新表无 Postgres 专属特性）。LLM 调用点（charter 起草）运行时依赖 ProviderConfig，测试全程 mock——无环境阻塞项。

## Package Legitimacy Audit

**无新增第三方包**——全部实现基于既有依赖（jsonschema/django/structlog/langchain 栈）与 stdlib。无需 slopcheck。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | golden command 落 delivery app（而非 repositories/独立 app）[ASSUMED，CONTEXT 未指定宿主 app，仅锁定命令名与 fixtures 路径] | 落点地图 #18 | 极低——Django command 可挂任意 installed app，换宿主是文件移动 |
| A2 | block 级 diff 纯函数落 `blueprint_schema.py`（CONTEXT 未指定文件）[ASSUMED] | 落点地图 #1 | 极低——planner 可改独立 `blueprint_diff.py`，均在锁定的 process_runtime 平级区 |
| A3 | RepoCharter 用「单行 + draft_content 草案列」实现版本化与 AI 不覆盖（CONTEXT 锁行为未锁存储形状）[ASSUMED] | 落点地图 #12 | 低——若 planner 选多行版本表，migration 与 service 形状变化，但 REST/验收面不变 |
| A4 | `needs_clarification` 的 `return_status` 由 lifecycle service 参数 + BlueprintThread.return_stage 承载，不在 Artifact 加列 [ASSUMED] | 落点地图 #8 | 低——若需持久化在 Artifact 上，migration 里多一列即可 |

## Open Questions

1. **charter 起草的 call_source 取值**
   - What we know：CONTEXT 锁定 7 个新枚举值（blueprint_decompose/spec_gate/repo_research/reroute/repo_plan/merge/ai_review），全部对应 112–114 的编排阶段；charter 起草 LLM 调用发生在 111 但 7 值中无对应项。
   - What's unclear：用哪个 call_source 标注 charter 草案调用。
   - Recommendation：新增第 8 个值 `charter_draft`（同步 LOGGING-SPEC §4.1）——比复用语义不符的既有值（如 repo_association）干净；这是对 CONTEXT 的最小合理扩充，planner 在 plan 里显式声明即可。若坚持不扩值，退而用 `REPO_ASSOCIATION`（同为仓库关联域的 LLM 调用）并注释说明。

2. **blueprint_* ConvergenceSessionEvent 事件名的确切拼写**
   - What we know：CONTEXT 只说「新增 blueprint_* 事件类型常量」；既有 taxonomy 命名是点分层级（`technical_plan.merge.started`）。
   - Recommendation：`blueprint.status.transitioned`（payload: from/to/artifact_id）为 111 唯一实际 emit 的事件；`blueprint.stage.started/completed/failed` 常量可同批定义供 112+ 使用（放 BLUEPRINT_EVENTS 集合，不进 ALL_EVENTS）。命名归 planner 定夺，落定后 112–116 消费同一常量。

3. **golden case 的「高三提分专项」期望 direct 仓集合具体取值**
   - What we know：DESIGN §5.7 实证提到 onion-learning / study-course / onion-practice / study-app / study-plan / study-practice 等仓名；期望 4 仓稳定集合的准确清单在路由试验记录里。
   - Recommendation：fixture 的 expected_direct_repos 以 DESIGN §5.7 表格提及的目标仓为准（onion-learning、study-course 必在）；断言机制级（命中率阈值）而非逐仓全等，避免对试验记录的过度耦合。

## Sources

### Primary (HIGH confidence — 本 worktree 代码实读，行号为证)
- `server/delivery/models/artifact.py` / `convergence_session.py` / `convergence_session_event.py` / `models/__init__.py`
- `server/delivery/services/artifact_service.py` / `convergence_session_service.py` / `event_taxonomy.py`
- `server/delivery/artifacts/registry.py` / `builtin_types.py` / `__init__.py`
- `server/workflows/schemas/technical_plan.py`；`server/services/process_runtime/merged_plan.py` / `decompose_segments.py`（只读参考）
- `server/repositories/models.py` / `urls.py` / `views.py` / `summary_service.py` / `facet_service.py` / `services/__init__.py` / migrations 目录
- `server/initiatives/models/repo_association.py` / `merge_request.py`；`server/knowledge/models.py`
- `server/agents/call_source.py` / `llm_factory.py`；`server/friday/settings.py` / `urls.py`；`server/pyproject.toml`
- `server/tests/delivery/test_artifact_inv6_guard.py` / `conftest.py`；`server/tests/services/test_event_taxonomy_alignment.py`；`server/tests/repositories/test_rebuild_repo_summaries.py`
- `.planning/technical-blueprint/DESIGN.md`（§3/§4/§5.7/§6/§12/§13.2）；`.planning/phases/111-schema/111-CONTEXT.md`；`.planning/ROADMAP.md`；`.planning/REQUIREMENTS.md`；`.planning/observability/LOGGING-SPEC.md`；`.planning/config.json`

### Secondary / Tertiary
- 无（本相位零外部技术调研需求：jsonschema/difflib 均为既有依赖 + stdlib，用法以库内既有调用点为准）

## Metadata

**Confidence breakdown:**
- 落点地图: HIGH — 全部落点由 CONTEXT 锁定或有直接同构先例；仅 A1–A4 四处形状级假设。
- 现状事实: HIGH — 逐文件实读 + 行号引用；关键接线（registry 校验 / event 非空 FK / taxonomy 守护）均验证到测试层。
- Pitfalls: HIGH — P2/P3/P4 直接来自守护测试与模型约束实读，非推测。

**Research date:** 2026-07-29
**Valid until:** 本 worktree 内长期有效；每次同步点 rebase（0.19 phase 合并主干）后需复核 delivery/repositories 的 migration 序号与 `event_taxonomy.py` 是否有 0.19 侧新增（§13.2 纪律 5/6）。
