# Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，elegant defaults；后端为主，无 UI）

<domain>
## Phase Boundary

把"飞书项目跟踪看板"自动转成 `Project` 聚合根：封装飞书看板枚举（子项 story/缺陷 + 人员带角色）、飞书事件幂等建项目并拉人（经身份映射带身份）、提供 `create_project` 工作流节点，并把 `WorkItem` 经关系边组合进项目。

**In scope（FSPROJ-01~03, COMPOSE-01/02）:**
- 飞书"项目跟踪"看板枚举封装（子项 + 人员带角色，无整板 API 时经子项关联字段派生，fail-soft 降级）
- 飞书事件触发幂等建项目 + 拉人带身份
- 工作流 `create_project` 节点（自动注册）
- 项目↔WorkItem 组合（story/缺陷复用 `delivery.WorkItem`，关系边挂入，手动并入/移除）

**Out of scope:**
- 工件 / 知识图谱关联 → Phase 79
- 记忆 / MR / 召回 → Phase 80
- 前端工作台（项目详情看工作项 UI）→ Phase 81
</domain>

<decisions>
## Implementation Decisions

### 飞书看板枚举（FSPROJ-01，核心风险）
- **复用既有飞书服务**：`server/services/feishu.py`/`feishu_bitable.py`/`feishu_im.py` + `server/feishu/client.py`，**不**新引 SDK。封装新 service（如 `server/services/feishu_project_board.py` 或 `feishu/services/board.py`，plan-phase 定）`enumerate_board(feishu_project_key) -> {work_items:[...], people:[{user_key, role}]}`。
- **无整板 listing API**：经"项目跟踪"子项关联字段派生逐项收集（复用 Phase 27 `get_work_item`/relations API + `WorkItemRelation` 范式）。plan-phase **先盘点 `server/services/feishu*.py` 现有端点能力**确认可达性。
- **fail-soft 降级**：拿不到子项/成员时不抛、返回部分结果 + warning，降级为"半自动"（webhook 逐个并入）。硬路径 fail-loud、软路径 fail-soft（沿用 Phase 27 `strict_response_json`/`safe_response_json` 范式）。
- 角色来源：飞书人员在看板中的角色字段 → 经 `ProjectRole` 映射（owner/pm/frontend/backend/qa），无法判定时给保守默认（如 backend 或不带角色，plan-phase 定）。

### 飞书事件触发建项目（FSPROJ-02）
- 复用既有飞书 webhook/事件链路（`server/feishu/views.py`/`websocket_client.py`/trigger dispatcher）。"项目跟踪拖到指定节点/状态"事件 → 经身份映射（Phase 77 `resolve_feishu_user`，JIT 自动绑定）建项目 + 拉人带身份。
- **幂等**：以 `(space, feishu_project_key)` 为键经 `ProjectService.create`（Phase 77 已实现 get_or_create 幂等），重复事件不重复建（重复仅补齐成员/关联，不新建）。
- 后台/事件路径**显式携带 `initiated_by_user_id`**（经身份映射解析触发飞书人对应 Friday 用户；未映射标 `system`），并在 worker 入口 re-bind（观测规范）。webhook 原始 payload 脱敏后留痕。

### 工作流 create_project 节点（FSPROJ-03）
- 新增 `CreateProjectNode`（`@register_node` 自动注册 `create_project`，全局唯一不撞名；`NodeCategory.INTEGRATION`，`execution_mode="server_local"`），镜像既有 INTEGRATION 节点（如 `feishu_chat.CreateGroupChatNode`/`fetch_space_info`）结构 + 全中文 config_schema。
- execute：render 看板引用/名称 → 调枚举 service → `ProjectService.create`（幂等）→ 经身份映射拉人带角色 → 关联子项 WorkItem；inputs=[default]、outputs=[default(成功), error(失败)]；缺看板引用 → failed+error handle。节点不直接写表，经 `ProjectService` 单一入口（INV-6）。

### 工作项组合（COMPOSE-01/02）
- **项目↔WorkItem 轻量关系边**：`initiatives` app 新增 through `ProjectWorkItemLink`（`project` FK + `work_item` FK→delivery.WorkItem + `provenance`(board_derived/manual) + 时间戳，`unique_together(project, work_item)`），`Project.work_items` M2M。经 `ProjectService`（INV-6）做 attach/detach。
- **story 与缺陷统一复用 `delivery.WorkItem`**（按 `work_item_type` 区分 story/缺陷），缺陷**不重复建模为工件**（COMPOSE-02）；同一 link 表挂入，board_derived 自动并入 + 手动并入/移除（COMPOSE-01）。
- KnowledgeEdge 富建模留 Phase 79；本期轻量关系表（与 Phase 77 项目↔项目关系一致取舍）。

### 观测与异步（强制规范）
- 飞书事件/节点为后台触发：带 `initiated_by_user_id`、category=caller（事件触发的一次调用）、component（如 feishu/initiatives）；枚举/建项目关键生命周期 started/completed/failed + duration_ms。
- 飞书上游响应体/异常文本经 `redact_secrets_in_text`；webhook 原始 payload `redact_for_ledger` 后落库。
- async ORM 走 `sync_to_async`；节点失败返回 `NodeResult(status="failed")` 不抛过引擎。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/feishu.py` / `feishu_bitable.py` / `feishu_im.py` / `server/feishu/client.py`：飞书 API 客户端 + Phase 27 共享解析 helper（`strict_response_json`/`safe_response_json`/`get_work_item`/relations）。
- `server/feishu/views.py` / `websocket_client.py` / trigger dispatcher：飞书事件/webhook 链路。
- `server/initiatives/`（Phase 77）：`Project`/`ProjectMember`/`ProjectService`/`resolve_feishu_user`（feishu app）。
- `server/delivery/`：`WorkItem`（三元组、work_item_type）、`WorkItemRelation` 派生范式。
- `server/workflows/nodes/integrations/`（如 `feishu_chat.py` CreateGroupChatNode）、`workflows/nodes/data/fetch_space_info.py`：节点范式 + `@register_node`。

### Established Patterns
- 飞书硬/软路径双解析（fail-loud / fail-soft 返回 []）；节点 `@register_node` 自动注册 + 中文 config_schema + default/error 双出口。
- 单一写入 service（INV-6）；后台任务携带 `initiated_by_user_id` + worker 入口 re-bind。

### Integration Points
- `ProjectService.create`（幂等 (space, feishu_project_key)）+ `resolve_feishu_user`（JIT 绑定）= Phase 77 复用基石。
- 项目↔WorkItem link 在 `initiatives`；WorkItem 在 `delivery`（字符串 FK 引用）。
</code_context>

<specifics>
## Specific Ideas

- plan-phase **务必先验证飞书"项目跟踪"枚举子项/成员 API 真实能力**（盘点既有端点），据此定枚举实现与降级面；测试用 respx mock 飞书响应，不依赖真实凭证。
- 重复飞书事件只补齐成员/关联不新建（幂等语义）；半自动降级路径要可被后续 webhook 逐项并入。
- 角色映射表（飞书角色字段 → ProjectRole）集中定义，无法判定给保守默认。
</specifics>

<deferred>
## Deferred Ideas

- 项目↔知识/仓库 KnowledgeEdge 统一建模 → Phase 79（KLINK）。
- 项目详情前端看工作项/成员 → Phase 81（UI-02）。
- 真实飞书凭证下的端到端枚举/事件触发人工验收 → 里程碑级（需真实飞书应用）。
</deferred>
