# Phase 31: Release 账本 + Bitable adapter 骨架 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

落地 Release 账本**宽容模型**（`ReleaseBatch`/`ReleaseRecord`/`ReleaseArtifact` + 保留 `raw_row`），并搭飞书 Bitable client/adapter **骨架**；开放平台 `tenant_access_token` 解析**独立于**项目 plugin token。真实多维表格列映射待开放平台凭证后填（v2 REL-03，本 phase 不做）。

覆盖需求：REL-01（宽容模型 + raw_row，adapter 演进不丢数据）、REL-02（Bitable client/adapter 骨架 + 开放平台 token 独立解析 + natural key `{app_token}:{table_id}:{record_id}`）。
依赖：Phase 28（`ReleaseRecord` 关联 `WorkItem`）。
不变量：INV-3（操作态在 delivery）、INV-6 精神（账本落库经服务入口）。
本 phase 是**骨架 + 宽容模型**——明确不要求真实列结构全量映射（那是 v2 REL-03 待开放平台凭证）。
</domain>

<decisions>
## Implementation Decisions

### Release 账本模型（Grey Area 1，DOMAIN §4/§12.6 宽容模型）
- 落 **delivery app**（`server/delivery/models/release.py`），re-export 于 `models/__init__.py`。
- `ReleaseBatch`：`id(UUID)`、`name(CharField)`、`released_at(DateTimeField null)`、`source(choices: bitable|manual)`、`external_ref(CharField blank)`、`raw_row(JSONField default=dict)`（保留 Bitable 原始行）、`created_at`/`updated_at`。
- `ReleaseRecord`：`id(UUID)`、`batch FK(CASCADE)`、`work_item FK(delivery.WorkItem, null, SET_NULL)`、`work_item_external_id(BigIntegerField null)`（反查中占位，目标未落库）、`status(CharField blank)`、`note(TextField blank)`、`raw_row(JSONField default=dict)`、`created_at`/`updated_at`。
- `ReleaseArtifact`：`id(UUID)`、`release_record FK(CASCADE)`、`artifact_type(choices: mr|branch|commit|diff|release_note|doc)`、`ref(CharField)`（MR URL / sha / doc token）、`payload(JSONField default=dict)`、`created_at`。
- **宽容核心**：`raw_row` 保留 Bitable 原始行，adapter 演进/列映射变化**不丢数据**（REL-01）；模型字段是宽容子集，真实列结构映射 v2 REL-03 再填。
- Bitable 记录 natural key：`{app_token}:{table_id}:{record_id}`（标识唯一定位 Bitable 行），存于 `external_ref` 或独立字段——本 phase 仅要求 natural key **标识就位**，不要求列结构全量映射。

### Bitable client/adapter 骨架（Grey Area 2，REL-02）
- 新增 `server/services/feishu_bitable.py`（client）：复用既有 `FeishuDocClient` 的**开放平台 tenant_access_token 模式**（`open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`，app_id/app_secret，2h 缓存自动刷新）——**独立于项目 plugin token**（`project.feishu.cn`）。提供 `BitableClient(app_id, app_secret)` + `get_tenant_access_token()` + 列出表/读记录的**骨架方法**（`list_records(app_token, table_id)` 等），骨架可调通 token 获取与端点形状，真实列解析留 adapter。
- adapter（`BitableReleaseAdapter` 或类似）：把 Bitable 原始行 → `ReleaseBatch`/`ReleaseRecord` 宽容模型，**保留 raw_row**；列→字段映射本 phase 只建**最小骨架/占位映射**（natural key + raw_row 必填，业务列映射 TODO 标 REL-03）。
- 凭证来源：开放平台 app_id/app_secret 经既有凭证体系解析（复用 `create_feishu_doc_client_for_project` 同款来源——Project / SystemSetting 加密凭证），**明确与项目 plugin token 来源解耦**（REL-02 核心）。本 phase 不要求真实凭证可用（无凭证时骨架不崩、降级）。

### 账本写入入口（Grey Area 3，INV-6 精神）
- Release 账本落库经 delivery 服务入口（如 `ReleaseService.ingest_batch(raw_rows, source)` / `upsert_record`），收口写入；可加 INV-6 grep 守护（沿用 Phase 28/29/30 范式）。
- `ReleaseRecord.work_item` 关联：经 work_item_external_id 反查已落库 WorkItem，命中则连 FK，未命中留 `work_item_external_id` 占位（对齐 WorkItemRelation 占位范式）。

### 范围守护（Grey Area 4）
- **本 phase 是骨架**：不接入真实 Bitable 数据全量入库（缺开放平台凭证 + 列样例）；不做真实列映射（REL-03 v2）。
- 成功标准聚焦：① 宽容模型落地 + raw_row 保留（adapter 演进不丢数据，可测：raw_row 原样存取）；② Bitable client/adapter 骨架就位 + 开放平台 token 解析独立（可测：client 用 tenant_access_token 模式、凭证来源与 plugin token 解耦）；③ natural key `{app_token}:{table_id}:{record_id}` 标识就位。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first；ORM `sync_to_async`；client 用 httpx async（复用 FeishuDocClient 范式）。
- 测试：pytest-django + factory-boy + respx（mock tenant_access_token + bitable list_records）+ pytest-socket。守护：① 宽容模型 raw_row 原样保留/取回（REL-01）；② adapter 从 raw_row 建 batch/record 不丢原始数据；③ natural key 标识正确；④ Bitable client 走开放平台 token（respx 验证 token 端点 + 凭证来源独立于 plugin token）；⑤ work_item 反查命中连 FK / 未命中占位；⑥ INV-6 账本旁路写表守护。

### Claude's Discretion
- natural key 存 external_ref 还是独立 3 字段、ReleaseService 命名/拆分、adapter 占位映射的具体形状、骨架 client 暴露哪些方法、凭证来源细节（Project 字段 vs SystemSetting）—— 由实现按既有约定与 FeishuDocClient 范式决定。
- 无开放平台凭证时骨架的降级行为（raise vs 返回空 + warning）—— 取与既有飞书 client 一致的降级范式。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/feishu_doc.py FeishuDocClient`：开放平台 `tenant_access_token` 模式（`open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`，app_id/app_secret，2h 缓存）—— BitableClient 直接复用该 token 范式。
- `create_feishu_doc_client_for_project`（feishu_doc_tools）—— 开放平台凭证来源解析范式，BitableClient 凭证来源对齐（独立于 project plugin token）。
- Phase 28 `server/delivery/`（models/ 包 + service 单一写入 + migration + INV-6 grep 守护 + WorkItem FK + 占位 external_id 范式）—— Release 模型/服务复用。
- `services/feishu.py`（项目 plugin token，`project.feishu.cn`）—— 对比基线：REL-02 要求开放平台 token 来源与此**解耦**。

### Established Patterns
- delivery app models/ + service 单一写入 + migration（Phase 28/29/30 模板）。
- httpx async client + token 缓存（FeishuDocClient）；缺凭证降级 + warning。
- 占位 external_id（target 未落库）范式（WorkItemRelation / Document.work_item）。
- ruff line 100；中文 docstring；structlog；pytest-django + factory-boy + respx + pytest-socket。

### Integration Points
- `server/delivery/models/`（新增 release）+ migration；`server/delivery/services/`（ReleaseService）。
- `server/services/feishu_bitable.py`（新 client + adapter 骨架）。
- 下游：v2 REL-03 真实列映射（待开放平台 app_id/secret + 列头/样例行）；Phase 32 一键摄取可经 ReleaseRecord 关联。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §4 / §12.6 是 Release 账本建模权威；宽容模型核心 = 保留 raw_row，adapter 演进不丢数据。
- DOMAIN §1.5 实测：Bitable/文档在 `<tenant>.feishu.cn` 走开放平台 token，与 work item 的项目 plugin token（`project.feishu.cn`）不同域不同凭证体系——REL-02 解耦的实测依据。
- natural key `{app_token}:{table_id}:{record_id}` 标识 Bitable 行。
- 被阻塞输入：开放平台 `tenant_access_token` 真实凭证未到位 → 本 phase 仅 adapter 骨架 + 宽容模型（真实列映射 = v2 REL-03）。
</specifics>

<deferred>
## Deferred Ideas

- Bitable 真实多维表格列结构全量映射 + ReleaseRecord 粒度定型（REL-03，需开放平台 app_id/secret + 列头/样例行）—— v2。
- Bitable 真实数据全量入库 —— 缺开放平台 tenant_access_token + 列样例。
- 一键摄取经 ReleaseRecord 关联 —— Phase 32 / 后续。
- Bitable 真实凭证/端点正确性人工验收 —— human-UAT（需真实开放平台凭证）。
</deferred>

---

*Phase: 31-release-ledger*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
