---
title: 代码智能层（Graph RAG）
---

# 代码智能层（Graph RAG）

代码智能层把符号级代码解析、Graph RAG 和跨仓 API 关联整合为统一能力，是技术方案生成、Web Chat 问答、MCP 工具与编码任务上下文的共同底座。代码主要位于 `server/codegraph/`、`server/code_relations/` 与 `server/services/`（`indexer`、`retrieval`、`graph_builder`、`qdrant_service` 等）。

## 和普通 RAG 有什么不一样

| 类型 | 它擅长什么 | 它容易漏掉什么 |
| --- | --- | --- |
| 普通 RAG | 根据语义相似度找到几段文本，适合回答文档类问题 | 代码里的调用链、导入关系、跨文件影响、前后端接口关系经常不在相似文本里 |
| 普通 Graph | 展示符号、文件、调用、依赖之间的关系，适合导航结构 | 只有图很难理解「这个需求在说什么」，也很难把证据压成模型刚好能用的上下文 |
| Friday Graph RAG | 先用语义和关键词召回相关 chunk，再沿代码图谱做一跳 / 二跳扩散，并补上跨仓 API 关系 | —— 它的目标就是让 Agent 改代码时拿到更接近真实影响面的证据 |

索引过程结合符号解析、Qdrant 混合检索（稠密 + 稀疏向量，`fastembed` 本地嵌入）、图谱扩散、跨仓 API 关联和 token 预算控制。最终进入模型的不是一堆散落片段，而是「需求 + 相关文件 + 符号 + 邻居关系 + 跨仓线索」的组合上下文。

## 多语言 Extractor 矩阵

| 语言 | Backend | 精度 | 说明 |
| --- | --- | --- | --- |
| Python | tree-sitter | 高 | 基础能力 |
| Go | gopls LSP | 高 | 支持跨文件 call resolution |
| TypeScript / TSX | tree-sitter-typescript | 中高 | 支持常见前端调用点解析 |
| Vue 2.7+ / 3 | volar LSP | 高 | 支持 script setup + Options API |
| HTML / CSS | tree-sitter | 中 | 基础符号解析 |

LSP 后端通过 `pygls` 集成外部 language server（`vue-language-server`、`gopls`），配置见 `server/friday/settings.py` 的 `LSP_SERVERS` / `EXTRACTOR_BACKENDS`。

Go gin 路由抽取支持 `r.GET("/path", handler)` 等基本形式与 middleware 参数元数据，结果写入 `codegraph_endpoint` 表。

## 跨仓库 API 关联

前后端分仓时，「改一个接口要动哪些地方」是典型的检索盲区。Friday 通过离线 join 建立前端调用点到后端 handler 的精确连边：

<FlowDiagram :layers="[
  {
    nodes: [
      { title: 'ApiCallSite', badge: '前端仓库', desc: 'Vue / TS 业务调用点（经 ApiWrapper 提取 URL）' },
      { title: 'Endpoint', badge: '后端仓库', desc: 'Go gin 路由 handler（codegraph_endpoint）' },
    ],
    arrow: 'offline join（URL path + method 归一化匹配）',
  },
  {
    nodes: [
      { title: 'CrossRepoApiCall', accent: true, desc: '跨仓 API 连边 → 接入 HybridSearch 扩散' },
    ],
  },
]" />

三步推断：

1. **auto-discover**：在 axios 锚点定位 LowLevelHelper（`get/post/put/delete` 基础封装）；
2. **ApiWrapper 识别**：找调用 LowLevelHelper 的 export function，提取 URL path；
3. **ApiCallSite 追踪**：通过 volar `textDocument/references` 反向找所有业务调用点。

跨仓 `API_CALLS` 类型的 ChunkEdge 已接入混合检索（HybridSearch），可以从前端 chunk 扩散到对应的后端 handler chunk。检索预算分配：50% 同仓语义 / 30% 图谱扩散 / 20% 跨仓 API 扩散。

## 3D Galaxy 可视化

前端导航 → 代码图谱 → **Galaxy 图谱**（路由 `/codegraph/galaxy`）。

- **3D 力导向图**：3d-force-graph（Three.js），发光 + 粒子 + 太空背景；
- **节点类型**：Symbol / File / Repository / ApiWrapper / Endpoint 五类视觉编码；
- **边类型**：CALL / IMPORT / TEST_OF / API_CALLS（粒子流动）/ CO_CHANGED / SEMANTIC / SAME_FILE / IMPLEMENTS；
- **Cmd+K 搜索**：Fuse.js 模糊匹配节点，跳转高亮；
- **节点详情**：点击弹出三段式 Drawer（基础信息 + 局部图 + References 双向列表）；
- **性能**：目标 5000 节点 / 20000 边下 30 FPS，FPS 低于门限时自动切换 ECharts GraphGL 备选渲染器。

## MCP Tools（Agent 使用）

以下工具可在 Agent 对话与 [MCP Server](/integrations/mcp) 中直接调用：

### `find_api_handler(url, method, repository_id)`

给定 URL + HTTP method，找后端 handler：

```python
find_api_handler(
    url="/api/v1/users/123",   # 任意 placeholder 风格，自动归一化
    method="GET",
    repository_id="<后端仓库UUID>",
)
# 返回：[{handler_name: "GetUserHandler", file_path: "handler/user.go", line_number: 42}]
```

### `find_api_callers(handler_name, repository_id)`

给定后端 handler 名，找所有前端业务调用点：

```python
find_api_callers(handler_name="GetUserHandler", repository_id="<后端仓库UUID>")
# 返回：[{caller_file: "src/pages/users/index.vue", line_number: 15, ...}]
```

### `list_endpoints(repository_id, limit=200)`

列出仓库所有 API 端点（按 method + path 排序，`limit` 上限 1000）。

## 索引状态监控

仓库详情页的索引状态卡片展示：

- 代码新鲜度（本地 vs 远端 HEAD SHA）；
- 集合健康（Qdrant 向量点数）；
- GraphRAG 构建状态（`graph_build_status` + 边数）；
- 跨仓 API 匹配数（`cross_repo_match_count` + 构建时间）。

首次部署或升级后需要执行 Django migrations：

```bash
cd server && uv run python manage.py migrate
```

## 相关文档

- [MCP Server](/integrations/mcp) —— 把这套检索能力暴露给本地 IDE 的 AI 助手
- [Friday Codebase Agent](/guide/friday-codebase-agent) —— Skill workflow 与故障恢复
