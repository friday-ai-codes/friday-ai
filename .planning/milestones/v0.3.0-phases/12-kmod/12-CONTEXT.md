# Phase 12: 知识模型与图存储地基 - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure phase（自动判定，决策留给执行）

<domain>
## Phase Boundary

交付知识有统一、可审计、带时间语义的存储底座，图访问唯一收口于 GraphStore 接口。

本阶段交付（KMOD-01..04）：
- 四类实体（work_item / tech_plan / code_change / document）统一模型落库，携带 `source_kind` + `source_id` 稳定业务引用、来源（feishu/chat/mcp/workflow）与事件时间
- bi-temporal 四时间戳边（`valid_at`/`invalid_at` + `created_at`/`expired_at`），失效置位不删除
- GraphStore service 接口：1–3 跳递归遍历、有效性过滤、深度上限、防环；边表 raw SQL 仅存在于 GraphStore 实现内
- supersedes 版本链，可按版本号回溯
- `delivery_knowledge` Qdrant collection 显式生命周期管理：维度不匹配拒绝并响亮报错 + 显式重建命令，绝不自动删库重建；payload schema（entity_kind/entity_id/version/is_latest/project_id/event_time + 权限维度字段）第一天定型

不在本阶段：摄取管线（Phase 13）、diff 归档能力（Phase 14，但归档表结构可随本阶段 migrations 建好）、检索（Phase 15）、入口暴露（Phase 16）。

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase（存储模型/服务接口，无用户可见行为）。以 ROADMAP Phase 12 success criteria、REQUIREMENTS KMOD-01..04 及 `.planning/research/PITFALLS.md` 的关键防线为准，沿用代码库既有模式。

ROADMAP/研究已锁定的硬决策（不可偏离）：
- 不引入 Neo4j 等图数据库；PG 递归 CTE 实现 1–3 跳遍历，GraphStore 接口留换引擎逃生门（Out of Scope 表已排除迁移）
- 有效性过滤埋进 GraphStore 接口而非靠约定
- payload 权限字段与 natural key 规则本阶段一次定对（Phase 13+ 依赖）
- 旧版本物理删除被排除——失效置位不删除

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/code_relations/`（ChunkRegistry / ChunkEdge）：既有"图边模型 + 不做 FK 的跨域引用 + admin 最小注册"范式，可作为 knowledge app 实体/边模型参照
- `server/services/embedding.py` `EmbeddingService`：既有向量化服务（Phase 13 复用，本阶段只需 collection schema 对齐）
- `server/services/indexer.py` `_ensure_collection`：既有 Qdrant collection 创建/校验模式（含 `SettingKeys.EMBEDDING_DIMENSION` 读取）——`delivery_knowledge` 生命周期管理可参照但需强化：维度不匹配时拒绝 + 显式重建命令，而非自动重建
- `SystemSetting` / `SettingKeys`：维度等配置的既有读取路径

### Established Patterns
- Django app 即 bounded context：新建 `knowledge` app，自带 `models/`、`services/`（或注册到 `server/services/`）、migrations
- 异步约束：async ORM 经 `sync_to_async`；服务层 stateless、可被 views 与 workflow nodes 调用
- 模型注释/docstring 中文，记录"实现契约"
- 测试：pytest + factory-boy，Qdrant 依赖以 seam/AsyncMock 隔离（见 `tests/test_git_diff_index.py` 模式）

### Integration Points
- `server/friday/settings.py` INSTALLED_APPS 注册新 app
- Django management command 作为 collection 显式重建入口（参照既有命令风格，如 `init_superuser`）
- ChunkRegistry（Phase 14 的 `MODIFIES_CHUNK` 边将引用 chunk_id，不做 FK）

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase。以 success criteria 与 PITFALLS 关键防线为规格。

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped（infrastructure phase）。

</deferred>
