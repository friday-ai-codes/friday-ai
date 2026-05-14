# hybrid_graph_capable_golden — Phase Plan fixture
**Purpose:** 锁定 `HybridSearchService.search` 在 `graph_capable` 路径下的
`final_context` 字节级行为（Phase 编排器主体落地后形成的 v2 baseline），
作为 Phase+ 后续修改 `services/retrieval/hybrid_search.py` /
`hop1_reader.py` / `hop2_expander.py` / `find_related.py` 的回归屏障。
与 Phase 落的 `tests/fixtures/layered_search_golden/` 关系：
| 维度 | layered_search_golden (Phase) | hybrid_graph_capable_golden (Phase) |
|------|----------------------------------|----------------------------------------|
| 编排器 | `LayeredSearchService.search` | `HybridSearchService.search` |
| 路径 | 五层 L1..L5 等价委托 | RAG 主线 + `## Graph Context` enrichment |
| 邻居 enrichment | 无 | hop1 payload 直读 + hop2 ORM 扩散 |
| Provider | NullProvider 路径已被 Plan byte-eq 升级（无邻居场景 LocalProvider==NullProvider）；本目录仅锁 LocalProvider/mock GraphCapable Provider 路径 | n/a |
| 数量 | 20 条 | 10 条 |
## 文件格式
每条 fixture 一个 `.txt` 文件，格式：
```
{final_context body —, LF line endings, no trailing newline}
# tokens=N source_layer=hybrid final_chunks=K
```
- **首段**：`HybridSearchService.search.final_context.rstrip("\n")` 原文
- **空行**：视觉分隔
- **末行元数据**：`# tokens=N source_layer=hybrid final_chunks=K`
 - `tokens` = `result.total_tokens`
 - `source_layer` = 固定 `hybrid`（区别于 Phase 的 `L2/L3/L4/EMPTY`）
 - `final_chunks` = `len(hop1_neighbors) + len(hop2_neighbors)`（图谱邻居数；
 本字段 0 表示纯 RAG 路径，与 fixture 04/05/10 对齐）
## fixture 矩阵（10 条）
| NN | slug | 用途 |
|-----|-----------------------------|------|
| 01 | chat_simple_query | 单仓基础 query，hop1 enrichment（一跳邻居 ≥ 2） |
| 02 | agent_symbol_query | symbol_name 起点（Pascal 命名触发 keywords），hop1+hop2 双段 |
| 03 | workflow_multi_repo | 多仓 `repo_ids=[r1,r2]`，两仓 chunk 都进 RAG |
| 04 | empty_repo_graceful | rag_items 空（hop1/hop2 皆空）→ `final_context=""` 不抛错 |
| 05 | null_provider_path | NullProvider 路径 byte-stable（不含 `## Graph Context` 段） |
| 06 | budget_default_8000 | 默认 `max_tokens=8000` → rag 4320 / graph 2880 分配 |
| 07 | budget_override_07 | `GRAPHRAG_BUDGET_RATIO=0.7` → rag 5040 / graph 2160 |
| 08 | hop2_dedup | hop2 target 与 hop1/rag 重合后仅独立邻居入 graph_context |
| 09 | symbol_failure_downgrade | `provider.lookup_symbols` raise → 仍返 RAG + hop1（symbol_failed=True 日志） |
| 10 | no_payload_neighbors | rag_items 无 `payload.related_chunks` 字段 → 仅 RAG section |
## 更新流程（fixture drift 处理）
当 production 代码 `hybrid_search.py` / `hop1_reader.py` / `hop2_expander.py`
变化预期会改 `final_context` 时：
1. 跑生成模式：
 ```bash
 cd server && GENERATE_GOLDEN=1 uv run pytest \
 tests/services/retrieval/test_hybrid_graph_capable_golden.py -v
 ```
 该模式下测试会把 actual 写入 fixture，**所有断言 skip**（不 FAIL）。
2. `git diff server/tests/fixtures/hybrid_graph_capable_golden/` 人工 review
 差异是否符合预期；如非预期立即回滚。
3. 不带 env var 再跑一遍验证 byte-equal：
 ```bash
 cd server && uv run pytest \
 tests/services/retrieval/test_hybrid_graph_capable_golden.py -v
 ```
4. commit fixture 改动与 production 代码一起。
**禁止手动编辑 `.txt` fixture** —— 任何字节差异都应通过 `GENERATE_GOLDEN=1`
重生成走流程，保证 fixture 永远反映 production 行为而不是手工美化。
## 不变量（per Phase CONTEXT.md）
- `final_context` 仅含 ASCII /；LF 换行（无 CRLF）
- `## Graph Context` 段不存在 ⇒ hop1+hop2 邻居均空（避免污染 LLM 上下文）
- 邻居行格式固定：``- `{file_path}:{line}` ({edge_type}, w={weight:.2f}): {reason}``
- `total_tokens` 由 `tiktoken cl100k_base` 计算（确定性）
- mock provider 返回固定数据；同一 fixture 多次跑结果完全一致
