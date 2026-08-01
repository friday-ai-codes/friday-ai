# Phase 111: 蓝图底座（schema + 生命周期 + 线程/章程模型 + 质量基线） - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权）

<domain>
## Phase Boundary

蓝图的一切结构与状态有了权威地基——blueprint/v1 schema 由 jsonschema 强制、11 态生命周期有守卫可追溯、划线线程与评审人模型就位、仓库章程模型与 AI 起草管道可用、execution_plan 可确定性派生、golden set 质量基线建立。**只做数据与服务底座，不做编排流水线（112/113）、不做 AI 审查（114）、不做前端（115）、不做入口切换（116）。**

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §3（schema）/ §4（状态机）/ §5.7（RepoCharter）/ §6（线程模型）/ §12（八项决策）/ §13.2（并行边界纪律）。

</domain>

<decisions>
## Implementation Decisions

### Schema 模块与校验落位
- blueprint/v1 schema 模块放 `server/services/process_runtime/blueprint_schema.py` 新文件——与 `merged_plan.py` 平级但绝不修改它（§13.2 冻结纪律）
- schema 定义用 Python dict + `jsonschema` 校验，镜像 `server/workflows/schemas/technical_plan.py` 既有惯例（不引入 pydantic）
- 校验粒度：顶层必填（六段 + meta + requirement_spec + must_haves）+ 六段各自结构校验 + 引用完整性检查（block.citations 的 id 必须存在于文档级引用池；implementation_overview.items 的 feature_point_id 必须可解析到 requirement_spec）
- execution_plan 派生器：`server/services/process_runtime/blueprint_execution.py` 纯函数（blueprint dict → execution_plan list，按 repo 聚合 + depends_on/wave 拓扑），输出必须通过既有 `validate_technical_plan`（jsonschema），保证下游 coding dispatcher 零改动

### 生命周期与评审人模型
- `blueprint_status` 落在 `delivery.Artifact` 新增 TextChoices 字段（11 态：researching/drafting/ai_reviewing/needs_clarification/pending_review/confirmed/implementing/implemented/archived/failed/superseded）；空值 = 旧 v0 数据，不参与状态机
- 转移守卫收口于 `server/delivery/services/blueprint_lifecycle_service.py`（镜像 `convergence_session_service` 的 INV-6 单一写入范式）；非法转移抛异常；`needs_clarification` 记录 `return_status`
- `pending_review → confirmed` 守卫：无 open+blocking 线程（查 BlueprintThread）
- 评审人 `delivery.BlueprintReviewer`：artifact FK + user FK（unique together）+ first_action + created_at；确认类动作自动 upsert
- 状态事件复用 `ConvergenceSessionEvent`，只新增 `blueprint_*` 事件类型常量，绝不改既有类型/字段（§13.2）；写事件 best-effort（观测不反噬业务）

### 线程与章程模型
- `delivery.BlueprintThread` + `delivery.BlueprintThreadMessage` 两表；字段按 DESIGN §6.1（anchor JSONField 可空=全局线程、kind: ai_clarification/ai_review_finding/human_comment/repo_confirmation、severity、blocking、options、status: open/answered/resolved/dismissed、return_stage、initiated_by_user_id）
- 重锚定算法 `server/delivery/services/blueprint_anchor.py` 纯函数：block_id 精确匹配优先 → quoted_text difflib 模糊匹配（相似度阈值 0.85）→ 置 orphaned；失锚不删线程
- `RepoCharter` 落 `repositories` app：`OneToOneField(Repository)` 一仓一份 + version + source(ai_draft/human_confirmed) + confirmed_by + 结构化 JSONField（positioning/owned_domains/boundaries/placement_preferences/audience/form/evolution，形状按 DESIGN §5.7）
- 章程起草管道 `repositories/services/charter_service.py`：从 ai_summary/facets + 近期 MR/code_change 历史 + verified/rejected RepoAssociation 蒸馏 LLM 草案（source=ai_draft）；confirm API 置 human_confirmed；人工确认后 AI 只能提修订草案（新 draft 版本），绝不覆盖
- 章程 REST：repositories 既有 API 惯例下新增 charter 读取 / 草案生成 / confirm 端点

### Golden set 与观测
- golden set 存 `server/tests/fixtures/blueprint_golden/*.json` + management command `evaluate_blueprint_golden` 离线运行；独立于 v0.19.0 的路由 golden set（不共文件、不产生冲突面）
- 首条 golden case：高三提分专项（期望 direct 仓集合 + 关键 feature_points），断言机制级
- 指标计算 `server/services/process_runtime/blueprint_quality.py` 纯函数：引用覆盖率（带 citations 的关键结论占比）、目标仓命中率（direct 集合对比期望）；AI 打回率/人审修改量/澄清轮次从 DB 统计（本相位留函数接口，数据由后续相位填充）
- `agents/call_source.py` 枚举新增 8 值：blueprint_decompose / blueprint_spec_gate / blueprint_repo_research / blueprint_reroute / blueprint_repo_plan / blueprint_merge / blueprint_ai_review / **blueprint_charter_draft**（章程起草 LLM 调用，RESEARCH Open Question 定夺）；同步登记 `.planning/observability/LOGGING-SPEC.md` §4.1
- structlog 事件：blueprint_stage_started/completed/failed（duration_ms + category=caller + component=process_runtime）；LifecycleService 状态转移记 caller 事件绑定 initiated_by_user_id

### Claude's Discretion
- migration 拆分方式、索引设计、TextChoices 常量命名、测试组织结构、docstring 措辞等实现细节自行决定，遵循 CONVENTIONS.md 与既有 delivery/repositories app 风格。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/schemas/technical_plan.py` — 既有 execution_plan jsonschema 与 `validate_technical_plan`（派生器输出校验直接复用）
- `server/services/process_runtime/merged_plan.py` — §7 校验范式参考（只读，禁改）
- `server/delivery/models/artifact.py` — Artifact/ArtifactVersion（加字段的宿主）；`artifact_service.py` 写入唯一入口
- `server/delivery/services/convergence_session_service.py` — INV-6 状态转移单点收口范式（LifecycleService 镜像它）
- `server/delivery/models/convergence_session.py` — ConvergenceSessionEvent（新增 blueprint_* 事件类型）
- `server/initiatives/models/repo_association.py` — RepoAssociation（章程蒸馏的输入之一）
- `server/repositories/` — Repository 模型与 ai_summary/facets（RepoCharter 宿主 app）
- `server/agents/call_source.py` — call_source 枚举（新增 7 值）

### Established Patterns
- Django app 模型分包 `models/`、service 层收口写入（INV-6）、TextChoices 闭集、UUID 主键、JSONField 结构化负载
- ruff format 100 列、中文 docstring 引用「实现契约/phase」、structlog kv 事件（snake_case started/completed/failed）
- 测试：pytest + factory-boy，`server/tests/<app>/` 组织；management command 测试走 call_command

### Integration Points
- `delivery.Artifact.blueprint_status` ← BlueprintLifecycleService ← 后续相位（112–116）全部经由它转移状态
- ConvergenceSessionEvent ← 状态/阶段事件（前端时间线在 115 消费）
- RepoCharter ← 112 的 blueprint_route/确认门回灌；charter_service 草案管道本相位先建
- blueprint_schema/blueprint_execution ← 113 merge 装配与派生调用

</code_context>

<specifics>
## Specific Ideas

- 六段 schema 字段形状严格按 DESIGN.md §3.3–§3.14（Block/Citation 基元、repo_associations 含 role/fitness/responsibility/confirmed_at_gate、must_haves truths/artifacts/key_links、decision_log、deferred_ideas）
- 11 态枚举值用英文 snake_case 存库，中文标签走 TextChoices label（i18n 默认中文）
- `schema_version: "blueprint/v1"` 为判别字段；旧 MergedPlan 隐式 v0，校验器遇 v0 直接 pass-through（不迁移）

</specifics>

<deferred>
## Deferred Ideas

- 段级细粒度编辑权限（初版全员可编辑 + 版本链审计，REQUIREMENTS Future）
- golden set 弱标签扩样（需采纳行为日志积累）
- 章程 charter_match 权重自动调参（Future）

</deferred>
