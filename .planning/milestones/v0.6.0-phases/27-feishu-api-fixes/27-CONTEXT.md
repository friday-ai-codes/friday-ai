# Phase 27: 飞书接口前置修复 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

修对 4 个飞书工作项/评论接口缺陷（PF-09/10/11/12），为后续 `WorkItemService.upsert`（Phase 28）提供可靠的真实数据回源。本 phase **只修 API/解析层**，不建 `delivery` app、不建 canonical `WorkItem` 模型、不做 upsert 编排（那是 Phase 28）。范围严格限定在飞书客户端取数与字段解析的正确性 + 可测性。

覆盖需求：FIX-01（真实 work_item_type 取数）、FIX-02（关系字段派生）、FIX-03（评论端点修复）、FIX-04（完整 fields[] 元数据）。
</domain>

<decisions>
## Implementation Decisions

### 客户端收敛与改动面（Grey Area 1）
- 存在两份近重复实现 `server/feishu/client.py` 与 `server/services/feishu.py`（均含 `FeishuClient`/`WorkItemInfo`/`_parse_rich_text`）。本 phase **不强行删除其一**（dedup 风险高、~50 个调用方），而是把"取数 + 字段解析"的修复逻辑落在**共享 helper 模块**（如 `server/services/feishu_parsing.py` 或在 services 层确立 canonical），两个 client 都调用同一 helper，消除解析漂移。
- canonical 取数/解析以 `server/services/feishu.py` 为主（services 层，DOMAIN §13 服务契约归属此处，且 Phase 28 `WorkItemService` 与 `server/knowledge/sources/feishu_work_item.py` normalizer 从这里消费）。
- 所有公开方法保持**向后兼容签名**：新增返回数据走新增属性/可选参数，绝不破坏现有 ~50 调用方（workflow 节点、agent tools、chat、mcp_tools 等）。
- 改动落点最小化：优先在解析层修复，不重构调用方。

### work_item_type 取数（FIX-01 / PF-09，Grey Area 2）
- 移除 `get_work_item` / `get_comments` 的 `work_item_type="story"` **默认值**：改为**必填参数**（无默认），调用方必须显式传真实 type；缺失时 fail-loud（抛明确异常或类型校验报错），绝不静默落 `story` 取错/取空。
- type 真实来源：由调用方从 identity（三元组）/webhook payload/URL 解析得到的真实 `work_item_type_key`（story/issue/...）。
- 容器型工作项真实 `type_key` 未知（URL 段 `project` ≠ API type）→ **本 phase 不支持容器型**，按 REQUIREMENTS Out of Scope 处理；提供 `work_item/all-types` 探查 helper 以便日后反推，但不在本 phase 落地容器型映射。
- `get_comments` 与 `get_work_item` 的 type 处理保持一致（同样必填）。

### 完整 fields[] 元数据（FIX-04 / PF-12，Grey Area 3）
- `WorkItemInfo` **新增** `feishu_fields: list[dict]` 属性，保留完整 `fields[]` 对象数组（每项含 `field_key`/`field_name`/`field_value`/`field_type_key`/`field_alias`），对齐 DOMAIN §12.1 `WorkItem.feishu_fields` 与 §16 字段对象形状。
- **保留**既有 `fields: dict[str, Any]`（拍平 `{field_key: field_value}`）作向后兼容，现有调用方不受影响；新逻辑读 `feishu_fields`。
- 提供按 alias/type 提取的 helper：`prd_url`（alias `prd_url` / `field_bcff9b`）、`tech_doc_url`、select 类取 `{label, value}` 的 label、关联类取 `[id...]`（DOMAIN §16 实测映射）。
- select 字段 value 形状 `{label, value}`、关联字段为 `[id...]`、`work_item_status` 含 `state_key`/`history[]`/`current_nodes`/`state_times` 一并可解析（为 Phase 28 派生 `status_display_name` 铺路，但本 phase 仅暴露解析能力，不落库）。

### 关系派生（FIX-02 / PF-10，Grey Area 4）
- 关系**主路径改为从关联字段派生**：新增纯函数 `derive_relations_from_fields(feishu_fields) -> list[RelationSpec]`，从 `work_item_related_multi_select` 类字段派生：
  - `field_caadeb`（所属项目）→ `belongs_to_project`
  - `planning_sprint`（所属迭代）→ `sprint`
  - `planning_version` / `actual_online_version`（版本）→ `version`
  - 其余关联字段 → `related`
  - 每条带 `relation_type` / `source_field_key` / `target_external_id`(目标飞书 id) / `origin="feishu_field"`（对齐 DOMAIN §12.3）。
- 失效的独立 relation 端点 `get_work_item_relations` **降级为可选**：容错 JSON 解析错误（`Extra data` 等非 JSON 响应）→ 返回 `[]` 并 warning，绝不抛断；保留方法签名，标注 `origin="feishu_relation_api"`，主路径不依赖它。
- 本 phase 产出的是"派生 RelationSpec 结构"，**不落库** `WorkItemRelation`（落库是 Phase 28）。

### 评论端点修复（FIX-03 / PF-11，Grey Area 5）
- `get_comments` 实测 JSON 解析错（端点路径/响应形状疑似变化）。修复策略：
  - **防御式解析**：`response.json()` 用 try/except 包裹 + content-type 校验，遇非 JSON（HTML/空/流式）不抛崩，记结构化 warning 并返回 `[]`（fail-soft，对齐项目"取数失败降级"既有范式）。
  - 解析按飞书工作项评论列表文档形状对齐（`comment/list`，分页 `page_size`，正确 header `X-PLUGIN-TOKEN`/`X-USER-KEY`），逐条取 `id`/`content`/`created_at`/`author`/线程父 id（为 Phase 29 评论事件流铺垫，但本 phase 仅返回扁平列表 + 必要字段）。
  - 真实端点正确性（路径/鉴权是否变更）**需带真实飞书凭证人工验收** → 记入 deferred / human-UAT；本 phase 以"修对解析 + 不崩 + 单测覆盖响应形状"为可自动验证的成功标准。

### 错误处理与一致性
- 统一飞书响应错误判定：注意 token 接口用 `data["error"]["code"]`，工作项接口用 `data["err_code"]` —— 不强行统一两套语义，但**所有 `.json()` 调用都加防御**（避免 PF-10/11 这类非 JSON 响应直接崩）。
- 失败语义二分：取数硬失败（明确 err_code≠0 且关键调用）→ 抛带上下文异常；列表/可选 facet（评论、relation 端点）→ fail-soft 返回空 + warning。

### 测试策略（Claude's Discretion 范围内）
- 用 `respx`（既有栈，httpx mocking）+ `pytest-asyncio` 写单测，**不发真实网络**（`pytest-socket` 隔离）。
- 覆盖：① 不传 type 时 fail-loud / 传 issue type 正确取数；② `feishu_fields` 完整对象保留（断言能取到 alias `prd_url` 与 select label）；③ `derive_relations_from_fields` 从 `field_caadeb=[7010938167]` 正确派生 `belongs_to_project`；④ `get_comments` 遇非 JSON 响应 fail-soft 返回 `[]` 不崩 + 正常响应正确解析；⑤ relation 端点 JSON 解析错降级返回 `[]`。
- 用 DOMAIN §16 实测样例值（story 7010225564 / issue 5580252273 字段）作 fixture，保证贴合真实形状。

### Claude's Discretion
- 共享 helper 模块的确切文件名/拆分粒度、`RelationSpec` 的具体 dataclass 形状、helper 函数命名、是否给 `WorkItemInfo` 加 `parse_*` 类方法 —— 由实现按既有约定（snake_case、services 层、中文 docstring）决定。
- 是否顺带把 `feishu/client.py` 标注 deprecation 注释 —— 可做但非必须，不破坏行为。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/feishu.py` — services 层 `FeishuClient`，含 `get_work_item`/`get_work_item_relations`/`get_comments`/`_parse_rich_text`/`_parse_paragraph`。canonical 落点。
- `server/feishu/client.py` — 近重复实现（无 `get_work_item_relations`），同样需同步修复或共享 helper。
- `WorkItemInfo` dataclass（两处各一份）— 待扩展 `feishu_fields` 完整数组。
- `common.encryption.decrypt_value` — 凭证解密（工厂函数已用）。
- `_parse_rich_text` / `_parse_paragraph` — 富文本→Markdown，评论/描述复用。

### Established Patterns
- async httpx 客户端 + `X-PLUGIN-TOKEN`/`X-USER-KEY` header；`get_plugin_token` 带缓存。
- 失败降级既有范式（`get_comments`/`get_work_item_relations` err_code≠0 返回 `[]`）。
- 测试：`respx` mock httpx、`pytest-asyncio`、`pytest-socket` 网络隔离（见 `server/tests/`）。
- 中文 docstring、`ruff format`（line 100）、snake_case。

### Integration Points
- 下游消费方：`server/knowledge/sources/feishu_work_item.py`（normalizer）、`server/workflows/nodes/integrations/feishu_workitem.py`、`server/mcp_tools/work_item_context_service.py`、`server/agents/tools/work_item_tools.py`、`server/workflows/triggers/handlers/feishu.py` 等 ~50 处 —— 改动必须向后兼容。
- Phase 28 `WorkItemService.upsert` 将从修好的取数/派生 helper 消费（DOMAIN §13.1 步骤 2/4）。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §16 实测字段映射是字段派生/测试 fixture 的权威来源：`prd_url=field_bcff9b(alias prd_url)`、`所属项目=field_caadeb(work_item_related_multi_select)`、`planning_sprint`、`planning_version`/`actual_online_version`、select value 形状 `{label,value}`。
- PF-09 实测：type=`project` 查容器型返回 `WorkItem Not Found(30005)` → 容器型不在本 phase。
- PF-10 实测：`get_work_item_relations` 返回 `Extra data: line 1 column 5`（非 JSON）→ 必须防御式解析。
- 真实样例工作项：story `7010225564`、issue `5580252273`（project_key `622c10eb5daaee81db915189`，simple_name `study_platform`）。
</specifics>

<deferred>
## Deferred Ideas

- 容器型工作项真实 `type_key` 映射（需查"工作项类型"接口或字段反推）—— REQUIREMENTS Out of Scope。
- `get_comments` 真实端点路径/鉴权正确性带真实飞书凭证的人工验收 —— human-UAT（本 phase 只保证解析不崩 + 形状正确 + 单测覆盖）。
- 两份 `FeishuClient` 物理 dedup / 删除其一 —— 风险高，留观察，非本 phase 范围。
- `WorkItemRelation` / `WorkItem` 落库与 `WorkItemService.upsert` —— Phase 28。
- 评论事件流 append-only 摄取 —— Phase 29。
</deferred>

---

*Phase: 27-feishu-api-fixes*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
