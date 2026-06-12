# Phase 13: 统一摄取与版本化 - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure/pipeline phase（自动判定，决策留给执行）

<domain>
## Phase Boundary

知识摄取成为业务流程的自动副产品——幂等、异步、版本化，检索面始终只见最新版；以 chat 与 MCP 两个形态最稳定的触发点验证管线。

本阶段交付（INGEST-03/05/06/07/08）：
- 统一摄取 service（单一入口，触发点只接线、不各写触发逻辑）
- chat 触发点：对话产出 CodingPlan 或触发编码时，提炼后的需求文本与方案自动入图入向量（对话原文不入图）
- MCP 触发点：`create_feishu_technical_plan` / `execute_work_item_repo_tasks` 等产出方案/执行编码时自动摄取
- 版本翻转：修改后重摄取为新版本——新版本向量入库、旧版本向量下线（`is_latest` 翻转兜底 + 物理删除）、旧边写 `expired_at`，检索默认只命中最新版
- 异步幂等：`transaction.on_commit` + background runner；幂等键约束 + reconcile 对账命令
- 向量化：确定性 chunk + 既有 EmbeddingService 写入 `delivery_knowledge`（hybrid dense+sparse），payload 完整携带 entity_kind/entity_id/version/is_latest/project_id/event_time

不在本阶段：workflow/编码回调/飞书触发点与 diff 归档（Phase 14）、检索（Phase 15）、入口暴露（Phase 16）。

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pipeline/infrastructure phase，无直接用户界面。以 ROADMAP Phase 13 success criteria、REQUIREMENTS INGEST-03/05/06/07/08、Phase 12 已定型的契约为准。

已锁定的硬约束（不可偏离）：
- Phase 12 契约是上游事实源：实体经 `generate_entity_id`（uuid5 natural key）落 `knowledge` app 三模型；payload schema 8 字段以 `knowledge/collection.py` 常量为唯一事实源；图写入只走 GraphStore 接口（不得绕过）；边失效用 GraphStore 置位原语（不可覆盖已置位时间戳）
- 摄取一律 `transaction.on_commit` + `services/background_runner.run_in_background` 异步执行，不阻塞请求/工作流主链路
- 幂等：同一事件重复投递不产生重复实体/版本（幂等键约束兜底 + reconcile 对账命令可验证）
- `is_latest` 翻转是版本下线第一道防线，物理删除向量只是优化（PITFALLS 防线）
- 对话原文不入图——只摄取提炼后的需求文本与方案
- 触发点只做接线（调用统一摄取 service），不在各触发点内重复实现摄取逻辑

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/`（Phase 12 产物）：三模型 + `generate_entity_id` + GraphStore（含 `invalidate_entity_version` 级联失效原语）+ `collection.py`（payload schema 常量、`ensure_delivery_knowledge_collection`、`get_expected_dimension`）
- `server/services/background_runner.py` `run_in_background`：既有后台执行器（code_relations 的 reconcile 已用此模式）
- `server/code_relations/signals.py`：`transaction.on_commit` + 去重调度的成熟范式（含 rollback 边界注释），可直接参照
- `server/services/embedding.py` `EmbeddingService`、`server/services/sparse_encoder.py`：hybrid dense+sparse 向量化既有路径
- `server/services/qdrant_service.py`：Qdrant 写入/删点既有封装
- chat 侧：`server/chat/models.py` `CodingPlan`（L174）、`server/chat/conversation_service.py`
- MCP 侧：`server/mcp_tools/views.py`（`create_feishu_technical_plan` L837、`execute_work_item_repo_tasks` L970）、`server/mcp_tools/work_item_execution_service.py`

### Established Patterns
- 信号/服务调用后 `transaction.on_commit` 注册回调，回滚不触发；批量去重后单次投递
- 测试：Qdrant/embedding 以 seam（AsyncMock/monkeypatch）隔离，`--disable-socket` 强制
- Django management command 作对账/重建入口（参照 `rebuild_delivery_knowledge`）

### Integration Points
- chat：CodingPlan 产生/更新处、触发编码处（conversation_service / coding_session_service）
- MCP：两个工具 view/service 的成功路径尾部
- `server/knowledge/` 内新增 ingestion service 模块（领域 service 放 app 内，沿 Phase 12 结构惯例）

</code_context>

<specifics>
## Specific Ideas

No specific requirements — 以 success criteria 与 PITFALLS 防线为规格。reconcile 对账命令需可验证幂等性（重复投递 → 单实体单版本）。

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped（infrastructure phase）。

</deferred>
