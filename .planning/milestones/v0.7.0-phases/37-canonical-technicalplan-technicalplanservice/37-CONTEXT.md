# Phase 37: canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §5)

<domain>
## Phase Boundary

立 canonical 方案脊柱与统一写入入口，把存量 3 条 plan 路径渐进收敛（不全量双写、不爆改）：

1. **canonical `TechnicalPlan`/`PlanVersion`**（delivery app，DOMAIN §5.1/§12.7）：方案的唯一事实源；`content` 存 §7 `MergedPlan` schema；版本链 supersedes；可追溯 `WorkItem`（INV-2，chat null 允许）。
2. **`TechnicalPlanService`**（= PlanProjectionService，DOMAIN §5.2/§13.2）：方案解析/创建/关联的唯一入口（INV-6）——`resolve(ref)` / `create_from(origin, payload)` / `link(old_record, canonical)`。
3. **存量 3 路径软链 + 迁移**（DOMAIN §5.3/§5.4）：
   - chat `CodingPlan`（`chat/models.py`，`tech_plan` 文本 + affected_files + 飞书文档 + recommended_repository_ids）
   - mcp `McpWorkItemTechnicalPlan`（`mcp_tools/models.py`，`plan_body` JSON + markdown + repository_tasks + 飞书三元组）
   - workflow（`plan_generation.py` 产出，无独立表 → 经 `external_ref={execution_id}:{node_id}` 软链）
   收敛策略：入口经 service **eager 投影**挂软链（`canonical_plan_id` / `external_ref`）+ 首次读到无 canonical 的旧记录 **read-time lazy migration** 建 canonical 回填链。

**不在本 phase**：架构师融合真实产 MergedPlan（Phase 40，本 phase 只立落库底座 + content schema 校验）；路由/召回/调研（38/39）；PlanValidator 完整校验（40，本 phase verify_plan 已对齐 execution_plan）；编排入口（41/42）。Phase 36 的 `PlanSession.current_plan_version`（UUID 软引用）在本 phase 由 service 写入 PlanVersion.id 后即可被读取（不在 36/37 间建硬 FK）。

</domain>

<decisions>
## Implementation Decisions

### canonical 模型（PLAN-01）
- 落 `server/delivery/models/technical_plan.py`（delivery app，与 WorkItem/PlanSession 同 app，DOMAIN §5 操作态聚合归属）+ curated re-export。
- `TechnicalPlan` 字段（DOMAIN §12.7）：`id UUIDField(pk, uuid4)`、`work_item FK(delivery.WorkItem, null=True, blank=True, SET_NULL)`（INV-2，chat 自然语言 null + 需显式标记 → 加 `origin` 区分；不另设 bool，null work_item + origin=chat 即"自然语言需求"）、`origin CharField(choices: chat|mcp|workflow|orchestration)`、`current_version FK(delivery.PlanVersion, null=True, blank=True, SET_NULL, related_name="+")`、`status CharField(choices: draft|under_review|approved|superseded|archived, default=draft)`、`created_at/updated_at`。
- `PlanVersion` 字段：`id UUIDField(pk, uuid4)`、`plan FK(TechnicalPlan, CASCADE, related_name="versions")`、`version IntegerField`、`supersedes FK(self, null=True, blank=True, SET_NULL)`、`content JSONField(default=dict)`（§7 MergedPlan schema：title/summary/api_contracts/dependency_dag/data_migrations/compat_risks/release_order/rollback_plan/execution_plan）、`content_hash CharField`、`created_at`。
- 约束/索引：`PlanVersion` `unique_together=(plan, version)`；`TechnicalPlan` `index(work_item)`、`index(origin, status)`。
- **循环 FK 处理**：`TechnicalPlan.current_version` ↔ `PlanVersion.plan` 互引用 → 用字符串模型引用（`"delivery.PlanVersion"`）+ 同一 migration 建两表；`current_version` nullable 先建表后由 service 写入（避免 NOT NULL 循环）。
- `content_hash`：复用 v0.6 既有 sha256 helper 语义（hash 相等不翻新版本——对齐 v0.3/v0.6 「hash 相等绝不产生新版本」决策），但**不 import knowledge**（INV-3 边界）；本地 helper 计算 canonical JSON 的 sha256。

### TechnicalPlanService 唯一入口（PLAN-02，INV-6）
- 落 `server/delivery/services/technical_plan_service.py` + service 包 re-export。**所有** 方案创建/版本/关联只经它（INV-6），grep 守护无旁路写 `TechnicalPlan`/`PlanVersion`。
- `create_from(origin, payload, *, work_item=None) -> TechnicalPlan`：新编排（orchestration）eager 建 canonical；校验 payload 的 content 经 §7/`validate_technical_plan`（PF-02 已对齐 execution_plan）；建 TechnicalPlan + 首版 PlanVersion(version=1, content_hash) + 置 current_version。
- `resolve(ref: PlanRef) -> TechnicalPlan`：`PlanRef` 是统一来源标识（dataclass：`origin` + 来源主键，如 `chat:CodingPlan.id` / `mcp:McpWorkItemTechnicalPlan.id` / `workflow:{execution_id}:{node_id}`）。规则（DOMAIN §5.4）：① 旧记录有 `canonical_plan_id`/external_ref 命中 → 读 canonical；② 无但旧记录完整 → **lazy 创建 canonical 再读**（回填链）；③ 找不到旧记录 → raise NotFound。
- `link(old_record, canonical) -> None`：回填软链（`CodingPlan.canonical_plan_id` / `McpWorkItemTechnicalPlan.canonical_plan_id` / workflow 经 `external_ref` 映射表或字段）。
- 版本管理：`add_version(plan, content)`：content_hash 相等 → 复用不翻版本（返回 current）；不等 → 建 PlanVersion(version=current+1, supersedes=current) + 更新 current_version。
- 生命周期（DOMAIN §5.4）：`archive(plan)` 置 status=archived，**不级联删旧表**（旧记录 canonical_plan_id 保留或标 archived）。

### 旧路径软链字段 + 迁移（PLAN-03）
- **chat `CodingPlan`**：加 `canonical_plan_id UUIDField(null=True, blank=True, db_index=True)` 软链字段（不建跨 app 硬 FK，避免 chat→delivery 耦合 + 循环依赖；存 TechnicalPlan.id）。migration 在 chat app。
- **mcp `McpWorkItemTechnicalPlan`**：同样加 `canonical_plan_id UUIDField(null=True, blank=True, db_index=True)`。migration 在 mcp_tools app。
- **workflow**：无独立表 → service 内建 `external_ref` 解析（`workflow:{execution_id}:{node_id}` 字符串）。决策：在 delivery 加轻量 `PlanExternalRef`(external_ref unique, canonical FK) 映射表承载 workflow 软链（chat/mcp 用各自表字段，workflow 用此映射表），统一 `resolve` 走「先查源表字段 / 再查 PlanExternalRef」。
  - **Claude's Discretion**：planner 可选择「workflow 也走 PlanExternalRef」或「三路径统一都走 PlanExternalRef 映射表」——倾向后者更一致（旧表不加字段、零侵入），但 DOMAIN §5.2 明列 chat/mcp 用 `canonical_plan_id` 字段。**最终采纳 DOMAIN 措辞**：chat/mcp 加 `canonical_plan_id` 字段，workflow 用 `PlanExternalRef`。
- **eager 投影时机**（DOMAIN §5.3）：新编排入口（Phase 40/41 接）eager；旧路径**本 phase 不强制改写各入口为 eager**（避免爆改 + 超范围），而是把 lazy migration 做扎实（read-time 首次读建 canonical 回填）。eager 投影提供 service API（`create_from` + `link`），各旧入口在后续顺带接（标 deferred / 在 40/41 接 orchestration 时 chat/mcp 入口可改 eager）。
  - 决策：本 phase 交付 **lazy migration 全链路可用** + service API 就绪 + 至少一条旧路径（建议 chat `CodingPlan`，最活跃）接 eager 投影作示范并守护；mcp/workflow 的 eager 接入可留 deferred（lazy 兜底保证不断层）。

### Claude's Discretion
- `PlanRef` 的精确 dataclass 形态与 `resolve` 的来源分派实现。
- `PlanExternalRef` 是否承载全部三路径 vs 仅 workflow（已倾向 DOMAIN 措辞：chat/mcp 字段 + workflow 映射表）。
- 哪条旧路径接 eager 示范（倾向 chat CodingPlan）。
- content_hash 的 canonical JSON 序列化细节（sort_keys 等）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/delivery/` — delivery app（v0.6+Phase36）：models 包 + curated re-export + UUID pk + service 单一入口范式（WorkItemService/PlanSessionService）+ migrations（最新 0009_plansession）。canonical 模型 + service 落此。
- `server/workflows/schemas/technical_plan.py` — `execution_plan` schema + `validate_technical_plan` + `dict_to_technical_plan`（content 校验复用；PF-02 已对齐）。
- `server/chat/models.py:CodingPlan` — chat 路径旧表（加 canonical_plan_id 软链）。
- `server/mcp_tools/models.py:McpWorkItemTechnicalPlan` — mcp 路径旧表（加 canonical_plan_id 软链）。
- `server/mcp_tools/technical_plan_service.py` — 既有 mcp 侧 plan service（参考其 create 逻辑作 lazy migration payload 取材，不与新 canonical service 混淆职责）。
- Phase 36 `PlanSession.current_plan_version`（UUID 软引用）— service 写 PlanVersion.id 后可被读。

### Established Patterns
- delivery models 包按实体拆 + curated re-export；UUIDField(default=uuid4) pk；落库/状态只经 service（INV-6 + grep 守护）；版本链 supersedes self FK + unique_together(.., version)（对齐 v0.6 DocumentVersion 范式）。
- hash 相等不翻新版本（v0.3/v0.6 决策）；content_hash 复用 sha256 语义但不 import knowledge（INV-3）。
- 跨 app 关联倾向软引用 UUID（v0.5/v0.6 多处用 UUID 软链避免 app 耦合，如 GitInstanceCredential、knowledge 投影引用脊柱）。

### Integration Points
- canonical TechnicalPlan 是 Phase 40 架构师融合 `MergedPlan` 的落库目标（`create_from(origin="orchestration", payload=merged_plan)`）。
- `PlanSession.current_plan_version` 由 service 在融合后写入。
- 旧 3 路径经 resolve/link 渐进收敛；chat/mcp 加软链字段，workflow 经 PlanExternalRef。

</code_context>

<specifics>
## Specific Ideas

- 严格遵循 DOMAIN §5（模型 + service 契约 + 创建时机 + 读优先级与冲突规则）、§12.7（字段级）、§13.2（service 方法签名）、§7（content = MergedPlan schema）。
- 渐进迁移核心：**service 才是策略，"旧表 nullable link" 不是策略**（DOMAIN §5.2）——确保 lazy migration 不断层、冲突以 canonical 为准、归档不级联删旧表。
- INV-2：方案可追溯 WorkItem，chat 自然语言 null + origin=chat 显式标记。
- INV-6：方案落库只经 TechnicalPlanService，grep 守护无旁路。

</specifics>

<deferred>
## Deferred Ideas

- mcp/workflow 旧入口改 eager 投影（本 phase lazy 兜底；eager 在 40/41 接 orchestration 时顺带，或单独 follow-up）。
- 架构师融合真实产 MergedPlan 落 canonical（Phase 40）。
- PlanValidator 完整校验（Phase 40，扩展已对齐的 verify_plan）。
- 旧表读写入口改为操作 canonical（DOMAIN §5.4：迁移期旧表只读历史，chat/mcp 编辑入口改操作 canonical）——逐步收敛，超本 phase 全量改造范围。

</deferred>
