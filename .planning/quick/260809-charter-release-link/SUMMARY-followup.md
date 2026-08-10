---
quick_id: 260809-charter-release-link（续作）
status: complete
date: 2026-08-09
---

# Summary（续作）— 关联可见 + 关联可用

## 问题

上一轮把 3154 条上线挂仓边和 257 份章程写进了库，但**看不到也用不上**：

- `artifact_associations.py` 正反向都硬过滤 `metadata.source == "artifact"`，
  而回填写的是自造的 `"release_bitable_import"` → 3154 条边全被挡掉。
- `blueprint_route_history` 用 `entity.repository_id` 归因，而工件实体该列
  **按设计恒为 None**（`knowledge/sources/artifact.py`，一个工件可挂多仓）；
  且 `HISTORY_ENTITY_KINDS` 不含 `document` + `include_document_kind=False`。
- AI 对话（`analyze_repository_relevance`）与 MCP（`route_repositories`）
  两条链**零章程读取**。

## Done

### T1 边 metadata 归一（数据，零代码回归风险）

`normalize_edges.py`：3154 条边 `metadata.source` → `"artifact"`，
原来源移到 `origin="release_bitable_import"` 留痕。`source=artifact` 边
1512 → **4666**。`backfill.py` 同步改掉未来写入形状。

**为什么不改 Python 过滤条件**：`source` 语义是「关联种类」，官方
`RepoRouterV2` 管线产出的也是 `"artifact"`；归一后未来任何消费
`source=="artifact"` 的地方自动生效，且不动代码。

### T2 历史落点经图边归因（`blueprint_route_history.py`）

- `HISTORY_ENTITY_KINDS` 加 `document`，`include_document_kind=True`
- 新增 `_resolve_repos_via_edges`：批量两跳（边 → 仓库节点 → `source_id`），
  **支持一条上线挂多仓**，每个候选仓都拿到同一条证据
- 归因失败 best-effort 返回 `{}`，不阻断路由；日志加 `edge_attributed_count`

**为什么不回填 `repository_id` 列**：逆 `sources/artifact.py` 设计，且抽样
200 条里有 **26 条（13%）挂多仓**，单个 FK 会直接丢掉。

### T3 章程接入对话 / MCP（`services/charter_route_signal.py`，新增）

与会话解耦的章程分量入口，复用 blueprint 的纯函数打分与候选补入：

- **加性调整而非凸组合**：凸组合会把没有章程的仓整体 ×(1-weight)，等于把
  「没写章程」当负分。加性下无章程逐字节零扰动（有单测守）。
- 权重 `settings.REPO_ROUTE_CHARTER_WEIGHT`（默认 0.25），设 0 即完全关停
- 接入 `agents/tools/repository_relevance.py`：改分 + 补证据 + 章程补入候选；
  触及禁区强制取消自动选中；`breakdown` 取差值维持「各项之和 == score」；
  `score_ranked` 同步调整（前端实际排序键）
- 接入 `mcp_tools/views.py::RouteRepositoriesView`
- ⛔ `RepoRouterV2` 零改动（§13.2 冻结面），章程不进它的 prompt

## 验收（`verify.py`）

| 项 | 值 |
|----|-----|
| 已挂仓的上线实体 | 2560 / 3997 |
| 残留未归一的边 | 0 |
| 反查抽样 | study-app 1142 / onion-learning 391 / problem-app 221 |
| 图边归因成功率 | 200 / 200（其中 26 条挂多仓） |
| 章程覆盖 | 257 / 257 有摘要的仓（全 `ai_draft`） |

测试（逐文件隔离跑，全绿）：

| 文件 | 结果 |
|------|------|
| `tests/services/test_charter_route_signal.py`（新增） | 6 passed |
| `tests/agents/test_repository_relevance_tool.py` + `tests/mcp_tools/test_route_repositories.py` | 38 passed |
| `tests/services/process_runtime/test_blueprint_route_stage.py` | 6 passed |
| `tests/services/process_runtime/test_blueprint_stage_rerun.py` | 24 passed |
| `tests/agents/tools/test_knowledge_read_tools.py` | 10 passed |

⚠ **未拿到全量套件绿**：`pytest tests/services/ tests/knowledge/ tests/agents/`
一次性跑（46 分钟）报 101 failed / 856 errors，但同一批文件**单独跑全过**，且
报错文件里包含与本次改动完全无关的（如 `test_knowledge_read_tools.py`）。
成因是共享远程 PG 上并发跑测试造成的 `test_friday` 建库/连接争用（当时另一个
agent 在跑 charter UI 的测试），非本次改动。全量绿需要独占测试库再验一次。

## 复检轮（260809 上午，"都试试"）

真实数据端到端把每个消费点跑了一遍，发现并修复 4 个问题：

1. **归一化断了章程起草的上线记录输入**（我自己引入）：`charter_service.
   _load_recent_releases` 仍按旧值 `metadata__source="release_bitable_import"`
   过滤 → 恒空。改为按 `source="artifact"` 边 + **工件类型** `release_record`
   筛选（按类型而非按导入来源，官方管线以后挂的上线记录也能吃到）。
   修后 study-app 能取到 967 条。
2. **2 字符 ASCII 片段假阳性**：`_matches` 的片段子串判定放行 `ai`/`h5` 这类
   缩写，「AI 自习室精准学对接」把「AI Agent 自治」「AI 代码审查」全判成满分
   命中。纯 ASCII 片段收紧到 ≥3 字符（CJK 2 字词如「培优」保持可命中）。
3. **note 不参与领域命中**：AI 起草的 domain 常是概括词（"AI 助学"），具体能力
   （"AI 自习室"）写在 note 里——此前 study-app 的真命中其实是靠 `ai` 假阳性通道
   碰巧对的。改为 domain 或 note 命中皆可。
4. **note 通用 2 字词假阳性**：note 参与后「错题本导出」经 note 里的「导出」
   命中「发货单操作管理」。note 是长自由文本，其片段判定收紧到 ≥3 字符
   （`_MIN_NOTE_SEGMENT_LEN`）。

以上 3 处匹配语义改动都落在 `blueprint_charter_match.py`（blueprint 路由同样
受益），新增 3 条回归测试；该文件 41 项测试全绿。

端到端验证通过的链路：

- 正向关联（上线工件 → activity-page）与反查（study-app 1142 条）
- 上线记录向量召回（「考前突击完成页 pad 适配」score 0.871 命中原记录）
- 历史落点：10 条召回 7 条经图边归因，study-app 5 命中 / problem-app 1 命中
- 真实对话链 `_analyze_relevance_core`：v2 路由（真 LLM）→ 章程分量 →
  「错题本」类 query 能补入 `backend/wrong-problem` 等仓 → trace 落库，
  breakdown 之和 == score 恒等式保持
- `charter_service` 测试 42+1 全过（1 项为并发库争用抖动，隔离跑通过）

## 刻意未做 / 已知问题

- **仓库详情页 UI**：由并行 quick 任务 `260809-3kc` 负责，本续作不碰其文件。
- **反查接口无分页**：`GET /api/knowledge/repositories/{id}/artifacts/` 一次返回
  全部（study-app 1142 条 / 3.4s），归一化后放大了 ~6 倍。需要加 `limit` + `total`
  才适合前端卡片直接渲染。
- **`document` 进历史召回会分流 demand 分路预算**（原本只有 code_change/tech_plan），
  路由质量需要实际观察 `edge_attributed_count` 与命中分布。
- 仍未挂仓的 1437 条上线记录：服务名在 Friday 已索引的 270 个仓里没有对应仓库。
- 章程全是 `ai_draft`，未经人工确认门；证据行已显式标注「未经人工确认」。
- **复合 query 部分匹配不敏感**：「错题本导出」匹配不上 domain「错题本基础」
  （3-gram 重合 1 < 2 的保守门槛，假阳性代价 > 假阴性的既有取舍）。要提升只能
  上分词或语义向量，超出零依赖 matcher 的边界。
- **章程起草粒度**：「高三提分专项」在 257 份章程里无任何 owned_domains 声明
  （mimo 概括成了「学习工具」这类大领域）。机制上补入依赖章程写得够细，
  需要人工确认门迭代内容，代码侧无解。
- note 参与命中后仍有轻微噪声（「数据导出」补入 export 类 query），但补入候选
  恒 low + 不自动选中 + 证据行可解释，可接受。
