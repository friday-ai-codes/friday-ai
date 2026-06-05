# 代码智能层功能指南
> **发布日期：** 2026-05-16
> **适用：** 开发者 / 系统集成
---
## 概览
代码智能层将符号级代码解析、GraphRAG 和跨仓 API 关联整合为统一能力，包含：
1. **多语言 extractor 矩阵** — Go / TS/TSX / Vue 2.7+/3 精确解析
2. **跨仓库前后端 API 关联** — 前端 axios call site → 后端 handler 精确连边
3. **3D Galaxy 可视化** — 银河感力导向图（30 FPS，5000+ 节点）
4. **3 个新 MCP tool** — agent 可直接查 API handler / 调用方 / 端点列表
---
## 1. 多语言 Extractor 矩阵
### 支持语言
| 语言 | Backend | 精度 | 说明 |
|------|---------|------|------|
| Python | tree-sitter | 高 | 既有 |
| Go | gopls LSP | 高 | 支持跨文件 call resolution |
| TypeScript / TSX | tree-sitter-typescript | 中高 | 支持常见前端调用点解析 |
| Vue 2.7+ / 3 | volar LSP | 高 | 支持 script setup + Options API |
| HTML / CSS | tree-sitter | 中 | 支持基础符号解析 |
### Go Endpoint 识别（gin）
Go gin 路由抽取支持：
- `r.GET("/path", handler)` / `r.POST(...)` 等基本形式
- `ogin.G*` middleware 参数元数据
- 查询：`codegraph_endpoint` 表
---
## 2. 跨仓库 API 关联
### 数据流
```
前端仓库（Vue/TS） 后端仓库（Go gin）
───────────────── ─────────────────
ApiCallSite Endpoint
 ↓ (via ApiWrapper) ↑
 └──────── CrossRepoApiCall ──────────┘
 (offline join)
```
### 三步推断
1. **auto-discover**：在 axios 锚点定位 LowLevelHelper（`get/post/put/delete` 基础封装）
2. **ApiWrapper 识别**：找调用 LowLevelHelper 的 export function，提取 URL path
3. **ApiCallSite 追踪**：通过 volar `textDocument/references` 反向找所有业务调用点
### HybridSearch API 扩散
跨仓 `API_CALLS` 类型 ChunkEdge 已接入 HybridSearch，支持：
- 从前端 chunk 扩散到对应的后端 handler chunk
- Budget 分配：50% 同仓语义 / 30% 图谱扩散 / 20% 跨仓 API 扩散
---
## 3. 3D Galaxy 可视化
### 访问路径
**前端导航** → 代码图谱 → **Galaxy 图谱**，或直接访问 `/codegraph/galaxy`
### 功能
- **3D 力导向图**：3d-force-graph（Three.js），银河感（发光 + 粒子 + 太空背景）
- **节点类型**：Symbol / File / Repository / ApiWrapper / Endpoint（5 类视觉编码）
- **边类型**：CALL / IMPORT / TEST_OF / API_CALLS（粒子流动）/ CO_CHANGED / SEMANTIC / SAME_FILE / IMPLEMENTS
- **Cmd+K 搜索**：Fuse.js 模糊匹配节点，跳转高亮
- **NodeDetailDrawer**：点击节点弹出三段式 Drawer（基础信息 + 局部图 + References 双向列表）
### 性能
- 目标：5000 节点 / 20000 边下 30 FPS
- FPS 低于门限时自动切换 ECharts GraphGL 备选渲染器
---
## 4. MCP Tools（Agent 使用）
以下 MCP tools 可在 Agent 对话中直接调用：
### `find_api_handler(url, method, repository_id)`
给定 URL + HTTP method，找后端 handler。
```python
# 示例：找处理 GET /api/v1/users/:id 的 Go handler
find_api_handler(
 url="/api/v1/users/123", # 任意 placeholder 风格，自动归一化
 method="GET",
 repository_id="<后端仓库UUID>",
)
# 返回：[{handler_name: "GetUserHandler", file_path: "handler/user.go", line_number: 42}]
```
### `find_api_callers(handler_name, repository_id)`
给定后端 handler 名，找所有前端业务调用点（business call site）。
```python
find_api_callers(
 handler_name="GetUserHandler",
 repository_id="<后端仓库UUID>",
)
# 返回：[{caller_file: "src/pages/users/index.vue", line_number: 15, ...}]
```
### `list_endpoints(repository_id, limit=200)`
列出仓库所有 API 端点（按 method + path 排序）。
```python
list_endpoints(
 repository_id="<后端仓库UUID>",
 limit=200, # max 1000
)
# 返回：{endpoints: [{http_method: "GET", url_path: "/api/v1/users", ...}], total: 285}
```
---
## 5. 数据库 Migrations 汇总
首次部署或升级后需要执行 Django migrations：
执行命令：
```bash
cd server && uv run python manage.py migrate
```
---
## 6. 索引状态监控
仓库详情页 **索引状态卡片**（RepoHashFreshnessCard）已扩展显示：
- 代码新鲜度（本地 vs 远端 HEAD SHA）
- 集合健康（Qdrant 向量点数）
- GraphRAG 构建状态（graph_build_status + 边数）
- **跨仓 API 匹配数**（cross_repo_match_count + 构建时间）
---
*文档更新日期：2026-05-16*
