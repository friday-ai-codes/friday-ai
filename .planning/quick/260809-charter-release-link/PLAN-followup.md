---
quick_id: 260809-charter-release-link（续作）
description: 让已挂的上线记录关联与章程真正被"看到"和"用上"
created: 2026-08-09
mode: quick
must_haves:
  truths:
    - 3154 条上线挂仓边在既有关联卡片（正/反向）可见，无需改 Python 过滤条件
    - blueprint 历史落点匹配能把上线记录归因到仓库，且支持一条记录挂多仓
    - AI 对话 / MCP 的仓库路由链能吃到仓库章程
  artifacts:
    - .planning/quick/260809-charter-release-link/normalize_edges.py
    - server/services/process_runtime/blueprint_route_history.py
  key_links:
    - knowledge/artifact_associations.py 正反向均硬过滤 metadata.source == "artifact"
    - knowledge/sources/artifact.py 官方管线：工件实体 repository_id 恒 None，仓库归属只走图边
---

# 续作 — 关联可见 + 关联可用

## 背景（实测结论，勿重新调研）

### 为什么"仓库里看不到"

1. **章程**：`GET /api/repositories/{id}/charter/` 有数据（257 份 `ai_draft`），但前端唯一
   消费方是 blueprint 引用预览弹窗 `CitationCharterPreview.vue`；仓库详情页无入口。
   → **由并行 quick 任务 `260809-3kc` 负责，本续作不碰**。
2. **上线挂仓边**：`artifact_associations.py` 正向（L86-92）与反向（L174）均硬过滤
   `metadata.source == "artifact"`；回填时写的是 `source="release_bitable_import"`，
   3154 条全被挡掉。库里 `source="artifact"` 的 1512 条（官方 `RepoRouterV2` 管线产出）可见。

### 为什么"检索用不上"

| 链路 | 章程 | 上线挂仓边 |
|------|------|-----------|
| blueprint 仓库路由 (`blueprint_charter_match`) | ✅ 读正式字段，不区分 source，`ai_draft` 立即生效 | ❌ |
| 仓库调研 / 拟方案 (`blueprint_research_adapter`) | ✅ prompt 注入 `## 仓库章程` | ❌ |
| blueprint 历史落点 (`blueprint_route_history`) | — | ❌ 双重出局，见下 |
| AI 对话 / MCP | ❌ `server/agents/` `server/mcp_tools/` 零读取 | ❌ |

历史落点双重出局：`HISTORY_ENTITY_KINDS = ["code_change", "tech_plan"]` 且
`include_document_kind=False`（上线记录是 `kind=document`）；即便放开 kind，归因用的是
`entity.repository_id`，而工件实体该列**按设计恒为 None**。

## 决策

- **不回填 `repository_id` 列**：逆 `sources/artifact.py` 设计（恒 None），且 ~460 个
  多仓实体会被压成单值。改为让历史落点**经图边归因**。
- **不改 Python 过滤条件，改归一化数据**：把 3154 条边 `metadata.source` 归一成
  `"artifact"`，另加 `origin="release_bitable_import"` 留痕。零代码回归风险，且未来
  任何消费 `source=="artifact"` 的地方自动生效。

## 任务

- **T1** 边 metadata 归一化脚本 + 修 `backfill.py` 未来写入形状
- **T2** `blueprint_route_history` 纳入 document kind + 经图边归因仓库（支持多仓）
- **T3** 章程接入 AI 对话 / MCP 仓库路由链
- **T4** 脚本 + DB 查询验收
