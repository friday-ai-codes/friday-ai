# Phase 59: 工作流自动建群节点 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳)

<domain>
## Phase Boundary

本 phase 新增"自动建群"工作流节点：创建飞书群 + 拉入指定成员（替代现仅能 `add_bot_to_chat` 加入已有群），新建群的 `chat_id` 作为节点输出供下游节点引用，并可选写回 `WorkItem.feishu_chat_id`（DOMAIN §1.2 writeback 字段），写回失败 fail-soft 不阻断工作流。

**现状坐标（实证）：**
- `server/workflows/nodes/integrations/feishu_chat.py`：已有 `FetchGroupChatNode`（取已有群 chat_id）/ `JoinGroupChatNode`（`ensure_bot_in_chat` 加入已有群）——**均无建群能力**。
- `server/services/feishu_im.py` `FeishuIMClient`：有 `get_chat_members` / `is_bot_in_chat` / `add_bot_to_chat` / `ensure_bot_in_chat`——**无 `create_chat`（建群）方法**。
- `server/delivery/models/work_item.py`：`feishu_chat_id = CharField(max_length=128, blank=True, default="")` 已存在（writeback 字段）。
- `server/delivery/services/work_item_service.py`：sync mirror 刷新**刻意不写** `feishu_chat_id`（writeback 不在 `_MIRROR_FIELDS`/update_fields 内，line 246-248 注释）——即当前**无任何 feishu_chat_id 写入入口**，本 phase 须新增（INV-6 单一写入入口）。

**交付物边界：**
- `FeishuIMClient` / `FeishuIMService` 新增 `create_chat`（建群）方法：`POST /im/v1/chats` 创建群（name/owner 等）+ 拉入成员（`id_list`，open_id/user_id），返回 chat_id。独立新增，不改既有 `add_bot_to_chat` / `ensure_bot_in_chat`。
- 新增 `CreateGroupChatNode` 工作流节点（`@register_node`，`NodeCategory.INTEGRATION`，`execution_mode="server_local"`，自动注册）：配置群名/owner/成员 id_list（支持模板变量）+ 可选 writeback（work_item 标识）；输出 `chat_id`（+ 群元信息）供下游 `JoinGroupChatNode` / 发卡节点等引用。
- 可选 writeback：把新建群 chat_id 写回 `WorkItem.feishu_chat_id`——经**单一写入入口**（INV-6，新增 `WorkItemService` writeback 方法或等价 service 收口，不旁路写表），失败 fail-soft（warning + 不阻断节点/工作流，节点仍返回 chat_id）。
- 守护测试：create_chat httpx 形状（端点/payload/成员拉入/code!=0 报错）、节点 happy path（建群→输出 chat_id）、writeback happy/fail-soft、缺参/建群失败的 error handle、零回归（既有 feishu_chat 节点 + work_item_service 不破）。

**不在本 phase（Out of Scope）：**
- 飞书卡片交互组件/多卡片编排（v2 OPENX-03）。
- 群成员的复杂权限/角色管理、解散群/转让群主等群管理全集（仅建群 + 拉人）。
- 自动建群的触发编排策略（本 phase 只提供节点，编排由用户在工作流中连线）。
</domain>

<decisions>
## Implementation Decisions

### 建群 API 封装
- `FeishuIMClient.create_chat` 手写 httpx（复用 `get_tenant_access_token` + httpx + tenacity rate-limit 范式，对齐 `add_bot_to_chat`）；`POST /im/v1/chats`（research 须确认精确 body：name / description / owner_id / user_id_list / bot_id_list / chat_mode 等 + `user_id_type` query 参数）；`code!=0 → raise FeishuIMError`；返回 chat_id（+ 可用群元信息）。
- 成员拉入策略：建群时 body 直接带成员 `id_list`（飞书 create chat 支持建群即拉人）；若飞书 API 限制，则建群后追加 `add_chat_members` 调用（research 定夺单步 vs 两步）。bot 自身按需纳入（owner/成员）。
- `FeishuIMService.create_chat` 委托方法，节点经 service 调用（对齐 `FetchGroupChatNode`/`JoinGroupChatNode` 用 `FeishuIMService.create(project)` 的范式）。

### 工作流节点
- `CreateGroupChatNode` 镜像既有 feishu_chat 节点结构：`config_schema`（群名 name、可选 description、owner_id、成员 member_ids（逗号分隔或列表，支持 `render_template`）、可选 writeback 的 project_key/work_item_id/work_item_type）；`inputs` default OBJECT；`outputs` default（成功，含 chat_id）+ error（失败）。
- 输出 `chat_id` 作为节点 output 的一等字段（+ source/群名等），供下游节点 `context` 引用（与 `FetchGroupChatNode` 输出 chat_id 对称，下游 `JoinGroupChatNode` 可直接消费）。
- 缺必填（群名/成员）或建群 API 失败 → `NodeResult(status="failed", next_handle="error")`（节点级失败语义，对齐既有 feishu_chat 节点）。

### writeback（chat_id → WorkItem.feishu_chat_id）
- 可选：仅当节点配置了 work_item 标识（project_key + work_item_id [+ type]）才 writeback。
- 经**单一写入入口**（INV-6）：新增 `WorkItemService`（或 delivery service）的 writeback 方法（如 `awriteback_feishu_chat_id`），收口对 `feishu_chat_id` 的写入（`feishu_project_key + work_item_type + work_item_id` 定位 WorkItem，`save(update_fields=["feishu_chat_id"])`），绝不旁路写表、绝不混入 sync mirror 的 `_MIRROR_FIELDS`。
- fail-soft：writeback 失败（WorkItem 不存在/DB 异常）→ try/except + 结构化 warning，**不阻断**节点——节点仍返回成功 + chat_id（建群成功是主产物，writeback 是 best-effort 附加）。建群本身失败才走 error。

### 测试边界
- create_chat httpx 形状单测（mock httpx：端点 `/im/v1/chats`、body name/成员 id_list、user_id_type query、code!=0 抛 FeishuIMError、成功取 chat_id）。
- 节点集成测：mock FeishuIMService.create_chat → 断言建群成功输出 chat_id（next_handle=default）；缺群名/成员 → failed；create_chat 抛错 → failed+error handle。
- writeback 测：配 work_item 标识 + mock writeback service → 断言写入 feishu_chat_id；writeback 抛错 → 节点仍 completed + chat_id（fail-soft，warning），断言不冒泡。
- INV-6 守护：feishu_chat_id 写入仅经 writeback service 单一入口（grep 守护，对齐既有 INV-6 守护范式）。
- 零回归：既有 `test_feishu_*`（feishu_chat 节点 / feishu_im 群方法）+ delivery work_item_service 测试全绿。

### the agent's Discretion
- create_chat 成员单步 vs 两步（建群即拉人 vs 建群后 add_members）依 research 对飞书 API 的结论定。
- member_ids 配置格式（逗号分隔字符串 vs JSON 列表）、user_id_type（open_id/user_id/union_id）默认值由 research/实现定夺。
- writeback service 方法放置（扩 `WorkItemService` vs 新轻量 writeback service）由 plan 按 INV-6 与代码现状定。
- 节点是否复用 `FetchGroupChatNode` 的 work_item 参数命名（project_key/work_item_id/work_item_type）保持一致——倾向一致以降低用户认知成本。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/nodes/integrations/feishu_chat.py` `FetchGroupChatNode` / `JoinGroupChatNode`：节点结构/config_schema/inputs/outputs/`FeishuIMService.create(project)` 调用/`render_template`/error handle 的完整范式——`CreateGroupChatNode` 直接镜像。
- `server/services/feishu_im.py` `FeishuIMClient.add_bot_to_chat`（`POST /im/v1/chats/{id}/members` + tenant token + tenacity rate-limit + `code!=0` 报错范式）——`create_chat` 复用基建；`FeishuIMService` 委托范式。
- `server/workflows/nodes/registry.py` `@register_node`：放 `BaseNode` 子类于 `workflows/nodes/integrations/` 即自动注册（无需手动登记）。
- `server/delivery/services/work_item_service.py` `WorkItemService`：WorkItem 定位（`feishu_project_key + work_item_type + work_item_id`）+ 单一写入入口范式（INV-6）——writeback 方法新增的落点参考。
- `server/delivery/models/work_item.py` `feishu_chat_id` 字段（已存在，无需 migration）。

### Established Patterns
- 节点：`@register_node` + `node_type`/`display_name`/`config_schema`/`inputs`/`outputs` + `async def execute(context) -> NodeResult`，失败返回 `NodeResult(status="failed", next_handle="error")`（不抛过引擎，见 nodes/base.py 契约）。
- IM client：httpx.AsyncClient + tenant_access_token Bearer + `data.get("code")==0` 判定 + RateLimitError/tenacity 重试 + 结构化 structlog。
- INV-6 单一写入入口 + grep 守护（参考 v0.6/v0.9/v0.10 既有 INV-6 守护测试范式）。
- 测试在 `server/tests/services/test_feishu_im.py`（IM 群方法，mock httpx）、`server/tests/test_feishu_bot_*` / workflow 节点测试。
- 测试命令：`cd server && uv run pytest tests/ -q -k "feishu or work_item"`（plan-phase 核对实际选择器）。

### Integration Points
- 飞书建群 API（`/im/v1/chats`）：外部协议——research 须用 WebSearch 查飞书官方 create chat 文档（2026）确认 body 字段（name/owner_id/user_id_list/bot_id_list/chat_mode/user_id_type）、建群即拉人 vs 两步、id 类型、bot 自动入群规则、权限要求。
- `WorkItemService` writeback：新增方法须与 sync mirror（`_refresh_mirror` 刻意排除 feishu_chat_id，line 246-248）解耦——writeback 是独立写入路径，绝不进 `_MIRROR_FIELDS`。
- `ExecutionContext`（workflows/nodes/base.py）：`node_config` / `render_template` / `input_data` / `workflow_execution.workflow.project`——节点取 project 建 FeishuIMService、取配置/上游数据的入口。

</code_context>

<specifics>
## Specific Ideas

- `CreateGroupChatNode` 与既有 `FetchGroupChatNode`/`JoinGroupChatNode` 构成"建群→（取群）→加群→发卡"完整工作流链路，chat_id 一等输出贯通下游。
- writeback 走 INV-6 单一入口 + fail-soft，既满足 DOMAIN §1.2 writeback 语义，又不让飞书侧失败阻断工作流主流程。
- create_chat 复用 add_bot_to_chat 的 token/httpx/tenacity 基建，最小新增面、与既有飞书 client 风格一致。
</specifics>

<deferred>
## Deferred Ideas

- 群管理全集（解散/转让群主/移除成员/改群信息）——本 phase 仅建群 + 拉人。
- 自动建群的触发/编排策略与去重（同一 work_item 重复建群防护）——若需要可后续加，本 phase 提供节点能力。
- 真实飞书租户建群端到端验收（需真实应用 + 真实用户 open_id）——deferred（对齐既有飞书 E2E deferred 惯例）。
- 飞书卡片交互组件/多卡片编排——v2 OPENX-03。
</deferred>
