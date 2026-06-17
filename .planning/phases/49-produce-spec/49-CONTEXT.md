# Phase 49: 方案产 openspec spec + Document(sdd_spec) - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区由设计文档 + 实地读码自动决策，未向用户提问)

<domain>
## Phase Boundary

SDD 仓库的方案编排（`PlanSession` 融合阶段，接 v0.7 扩展点）额外产出 openspec 格式 spec draft，落 `Document(sdd_spec)` 并经单一入口写入，关联来源 `WorkItem` 与 `PlanVersion`。

**In scope:**
- 融合成功后对涉及的 SDD 仓库产 openspec spec draft（SPEC-01）
- spec draft 落 `Document(document_type=sdd_spec, source_kind=internal_generated)` 经 `DocumentService` 单一入口（INV-6）
- 引入 `SddSpec` 脊柱实体（spec 操作态），关联 `WorkItem` + `PlanVersion` + `Repository`（SPEC-02）
- 非 SDD 仓库不产 spec（零回归）

**Out of scope（本 phase）:**
- spec 状态机流转 + 评审记录 + 前端展示（Phase 50；本 phase 仅落 `status=draft` 初值与全枚举定义）
- 编码前置 gate（Phase 51）、spec↔PR 关联/验收（Phase 52）
- openspec 内容深度 lint/校验（v2 SDDX-01）
</domain>

<decisions>
## Implementation Decisions（smart discuss 自动决策）

### D-49-1 引入 `SddSpec` 脊柱实体（delivery app）—— 50/51/52 的挂载点
新建 `server/delivery/models/sdd_spec.py`：
- `document` FK → `Document`（持有 spec 正文/版本，CASCADE 或 SET_NULL）
- `repository` FK → `repositories.Repository`（哪个 SDD 仓）
- `work_item` FK(null) → `WorkItem`（SPEC-02 追溯，可空对齐 chat 自然语言）
- `plan_version` FK(null) → `delivery.PlanVersion`（SPEC-02 来源方案，SET_NULL）
- `status` CharField，`SddSpecStatus` 全枚举**现在定义**：`draft / in_review / approved / implemented / archived`（默认 `draft`；流转逻辑归 Phase 50）——刻意区别于 `TechnicalPlan.status`（`under_review`/`superseded`），spec 语义确需 `in_review`/`implemented`
- `change_kind` choices `proposal / delta`（openspec change proposal vs spec delta），默认 `proposal`
- `created_at/updated_at`
- **幂等键**：`unique_together(plan_version, repository)`——同一方案版本对同一仓只产一份 spec，重跑幂等不重复
- 模型层零业务方法（守 INV-6），写入只经 `SddSpecService`

### D-49-2 `DocumentService.create_internal_spec(...)` —— 内部生成文档的单一写入入口
扩 `DocumentService` 新增 async `create_internal_spec(*, work_item, repository_label, content, title="")`：
- 落 `Document(document_type=sdd_spec, source_kind=internal_generated, content_storage=snapshot)` + `DocumentVersion`（content + content_hash）
- internal 文档 `external_ref=""`（豁免飞书去重唯一约束，已有 condition `~Q(external_ref="")`）；不派生 feishu_tenant
- 复用既有 hash 不翻版本铁律（同 spec 内容重产不翻版本）
- **守 INV-6**：Document/DocumentVersion 仍只经 DocumentService 写（grep 守护沿用 test_document_inv6_guard 范式）

### D-49-3 `SddSpecService` —— SddSpec 单一写入入口（INV-6）
新建 `server/delivery/services/sdd_spec_service.py`，本 phase 实现：
- `create_draft(*, plan_version_id, repository, work_item, content, change_kind="proposal")`：经 `DocumentService.create_internal_spec` 落 Document(sdd_spec) → `get_or_create(plan_version_id, repository)` 建/取 `SddSpec(status=draft)` 连 document/work_item。幂等（已存在不重复建）。
- （状态流转 / 评审写入方法归 Phase 50，本 phase 不实现。）

### D-49-4 spec 内容生成：可注入 `SddSpecSynthesizer`（镜像 MergedPlanSynthesizer）
新建协议 + 默认 LLM 合成器（`spec_generation.py` 内或并列）：
- `SddSpecSynthesizer.synthesize(*, requirement, merged_plan, repository) -> str`（openspec 格式 markdown）
- 默认 `LLMSddSpecSynthesizer`：`ProviderConfigService.aresolve` + `build_chat_model`，system prompt 教 openspec change-proposal 结构（`## Why` / `## What Changes` / `## Spec Deltas`：ADDED/MODIFIED/REMOVED Requirements + Scenarios）；输入=需求 + MergedPlan + 仓库名。**真实 LLM 路径仅构造 + 单测 mock，真容器/真模型 E2E deferred**（对齐 LLMMergedPlanSynthesizer 范式）。合成失败抛异常由 hook 捕获降级。

### D-49-5 挂接点：融合通过后 best-effort 产 spec（fail-soft，绝不阻断编排）
新建 `server/services/plan_orchestration/spec_generation.py` 暴露 async `agenerate_specs_for_plan(plan_version_id, *, synthesizer=None, spec_service=None)`：
- 解析 `PlanVersion.content`（MergedPlan）的 `execution_plan[].repository_id` 取涉及仓
- 过滤 `Repository.facets.get("methodology")=="SDD"` 的仓（非 SDD 跳过 → 零回归；无 SDD 仓 → no-op）
- 逐 SDD 仓：synthesize → `SddSpecService.create_draft`；逐仓 try/except 隔离
- emit `EVENT_SPEC_DRAFTED`（best-effort）
- **从 `ArchitectMergeAdapter._handle_pass` 在 `EVENT_PLAN_MERGE_COMPLETED` 之后调用，整段 try/except 吞为 warning `sdd_spec_generation_failed`，绝不阻断融合/编排返回**（对齐 adapter 内既有 best-effort emit 范式）。经 adapter 构造注入可选 `spec_generation_hook`（默认真实实现），便于单测 stub。

### D-49-6 事件 taxonomy 新增 `spec.drafted`
`event_taxonomy.py` 加 `EVENT_SPEC_DRAFTED = "spec.drafted"`，payload `{spec_id, repository_id, plan_version_id}`，经既有 `PlanSessionEvent` append-only 信封（§15，为 v0.11 对外 adapter 备料）。

### D-49-7 零回归 + INV-6 守护
- 非 SDD 仓 / 无 SDD 仓 / spec 生成异常 → 编排路径与 v0.8 完全一致（守护测试断言 merge 返回 passed 不受影响）。
- INV-6 grep 守护：SddSpec 只经 SddSpecService 写、Document(sdd_spec) 只经 DocumentService 写。
</decisions>

<code_context>
## Existing Code Insights

- **融合落点**：`server/services/plan_orchestration/architect_merge_adapter.py` `_handle_pass`——融合通过后 `TechnicalPlanService.create_from("orchestration")` 落 canonical `PlanVersion`、置 `session.current_plan_version`、emit `EVENT_PLAN_MERGE_COMPLETED`。在此之后挂 spec 生成 hook（best-effort）。adapter 已有 `_emit` best-effort 范式与可注入依赖（synthesizer/services）模式可镜像。
- **Document 模型**：`server/delivery/models/document.py`——`DocumentType.SDD_SPEC`/`DocumentSourceKind.INTERNAL_GENERATED` 枚举已存在；`work_item` FK 已有；`external_ref` 唯一约束 condition `~Q(external_ref="")` 豁免内部文档；`content_storage` 默认 both（内部 spec 用 snapshot）；版本链 supersedes + hash 不翻版本。
- **DocumentService**：`server/delivery/services/document_service.py`——当前仅 `upsert_from_feishu`（external）；需新增 `create_internal_spec`（internal）。`_content_hash` 复用、`@sync_to_async` + `transaction.atomic` + `select_for_update` 范式可镜像。
- **PlanVersion / TechnicalPlan**：`server/delivery/models/`（delivery app，与 SddSpec 同 app，直接 FK 引用）。`PlanVersion.content` 存 MergedPlan（§7：`execution_plan[].repository_id/repository_name`）。
- **Repository.facets**：Phase 48 已落 `facets["methodology"]="SDD"`；`Repository` 在 `repositories.models`。
- **可注入 LLM 合成器范式**：`LLMMergedPlanSynthesizer`（同 adapter 文件）——`ProviderConfigService.aresolve` + `build_chat_model` + 健壮 JSON/文本解析；spec 合成器镜像（输出 markdown 而非 JSON）。
- **事件 taxonomy**：`server/delivery/services/event_taxonomy.py` + `PlanSessionEvent` append-only（§15）。
- **INV-6 grep 守护范式**：`server/tests/delivery/test_document_inv6_guard.py` / `test_research_inv6_guard.py`。
</code_context>

<specifics>
## Specific Ideas

- 新文件：`server/delivery/models/sdd_spec.py`（`SddSpec` + `SddSpecStatus` + `SddSpecChangeKind`）、`server/delivery/services/sdd_spec_service.py`、`server/services/plan_orchestration/spec_generation.py`（含 `SddSpecSynthesizer` 协议 + `LLMSddSpecSynthesizer` + `agenerate_specs_for_plan`）。
- migration：delivery 新增 `SddSpec` 表（含 `unique_together(plan_version, repository)`），`makemigrations` 自动生成；模型 curated re-export 进 `delivery/models/__init__.py` + `delivery/services/__init__.py`。
- `DocumentService.create_internal_spec` 新方法；adapter `_handle_pass` 末尾 best-effort 调 `agenerate_specs_for_plan`。
- 守护测试：
  - SDD 仓融合通过 → 产 SddSpec(draft) + Document(sdd_spec, internal_generated) + DocumentVersion，关联 work_item/plan_version/repository；emit spec.drafted。
  - 非 SDD 仓 / 无 SDD 仓 → 不产 spec，merge 返回 passed 零回归。
  - spec 合成异常 → fail-soft，merge 仍 passed（warning，不冒泡）。
  - 幂等：同 plan_version+repo 重产不重复建 SddSpec、同内容不翻 DocumentVersion。
  - INV-6 grep 守护：SddSpec 仅经 SddSpecService、Document 仅经 DocumentService。
- 后端 ruff + pytest；本 phase 无前端（无 UI hint）。
</specifics>

<deferred>
## Deferred Ideas

- spec 状态机流转 + 评审记录 + 前端展示 → Phase 50。
- 编码前置 gate（消费 SddSpec.status==approved）→ Phase 51。
- spec↔实现 PR 关联 + 交付验收视图 → Phase 52。
- openspec 内容/格式深度 lint 校验 → v2 SDDX-01。
- spec draft 回写飞书（writeback_allowed）→ 暂不做。
</deferred>
