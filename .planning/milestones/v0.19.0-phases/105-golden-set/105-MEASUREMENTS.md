# Phase 105 Measurements — Phase 106 公式定版输入实测（O-1 / O-3）

**Created:** 2026-07-29
**Producer:** 105-02（`measure_repo_index_stats` command + 本文档）
**Consumer:** Phase 106 planning（MaxP 主干口径 + pivoted size normalization 常数 N̄/b）

> **数据环境标注纪律**：本文档每条结论显式注明数据环境——
> `数据环境: 开发库（结构性结论）` 或 `数据环境: 生产实例 friday.yc345.tv（分布实测）`。
> 开发库上只能得出**结构性结论**（命令可运行、统计口径正确、输出形状符合契约），
> 不得作为 N_r 分布结论供 Phase 106 消费。

---

## 1. O-3：Stage 0 dense 余弦可得性（已定论，代码级验证）

**数据环境: 开发库（结构性结论）** —— 本节结论来自代码实读 + 内存 Qdrant 结构性测试，
与数据规模无关，属确定性代码级答案；仅「延迟实测数字」一项待生产回填。

### 结论

1. **RRF 融合分不含 dense 余弦。** `QdrantService.hybrid_search_by_name`
   （`server/services/qdrant_service.py`）用
   `client.query_points(prefetch=[dense, sparse], query=FusionQuery(fusion=Fusion.RRF))`，
   返回的 `score` 是 RRF 融合分（rank-1 量级 ≈ 0.016–0.033），**Qdrant fusion 查询
   不回传 per-prefetch 的原始 dense 余弦**。
2. **取余弦须单独发一次 dense-only 查询。** `repo_index_nodes` collection 距离配置为
   `Distance.COSINE`，dense-only 查询直接返回余弦相似度。**注意**：该 collection 是
   hybrid 模式（命名向量 `dense`/`sparse`），dense-only 查询必须带 `using="dense"`
   （`client.query_points(collection_name="repo_index_nodes", query=vec, using="dense")`）；
   既有 `QdrantService.search_by_name` 查询的是匿名默认向量，**对 hybrid collection
   不可用**（会 400 fallback 返回空），Phase 106 若走余弦路径需新增带 `using` 的封装
   或直接用 client（`measure_repo_index_stats --verify-cosine` 即此写法，可参照）。
3. **无「一次查询同时拿两种分」的官方途径**（qdrant-client >= 1.9 现状）。
   [RESEARCH A1 假设：基于 API 形状与现有代码，官方 changelog 未逐版本核对——
   生产执行 `--verify-cosine` 时顺带复核当时 qdrant-client 版本能力。]

### 给 Phase 106 的推论

- MaxP 主干若用余弦，需在 Stage 0 之外 **+1 次 Qdrant 往返**（同机部署预计 <10ms
  量级）。确切延迟数字待生产实测回填：

| 项 | 值 | 数据环境 |
|----|----|---------|
| dense-only 查询耗时（`--verify-cosine` 的 `duration_ms`） | **待生产实例执行补录** | 生产实例 friday.yc345.tv（deferred 人工步骤） |
| 返回 score 样例（应为 COSINE，自查询 top-1 ≈ 1.0） | **待生产实例执行补录** | 生产实例 friday.yc345.tv（deferred 人工步骤） |

- 若实测延迟可接受（<10ms 量级），MaxP 主干建议用余弦（跨 query 可比）；
  若不可接受，只能用 RRF 分（rank-1 恒为 max、跨 query 不可比，需换归一化策略），
  见 ROUTING-RANKING §9 O-3。

---

## 2. O-1：全仓 N_r 分布（待生产实例执行）

**数据环境: 生产实例 friday.yc345.tv（分布实测）——deferred 人工步骤，尚未执行。**
本地开发库无 259 仓真实索引数据，**本地跑出的全 0 / 小样本结果不得写入本节**
（RESEARCH Pitfall 8：会误导 Phase 106 的 N̄/b 取值）。

### 执行指引（人工步骤）

在有真实索引的部署实例（friday.yc345.tv）上运行：

```bash
cd server && uv run python manage.py measure_repo_index_stats --json --top 20 --verify-cosine
```

把输出 JSON 回填下方占位表（分位数 + top-20），并同时回填 §1 的延迟表。
命令为只读（count/scroll/query），单仓异常自动跳过，可安全在生产执行。

### N_r 分布占位表（待生产实例执行补录）

| 指标 | 值 | 数据环境 |
|------|----|---------|
| 总仓数（is_deleted=False） | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| 有索引仓数（N_r > 0） | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| p50 | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| p90 | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| p99 | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| max | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| mean | 待生产实例执行补录 | 生产实例 friday.yc345.tv |
| median（N̄ 建议口径） | 待生产实例执行补录 | 生产实例 friday.yc345.tv |

### Top-20 倾斜表占位（待生产实例执行补录）

| 仓库 | N_r |
|------|-----|
| 待生产实例执行补录（预期 `study-app` 类 monorepo 居首） | — |

### 命令本身的结构性验证（已完成）

**数据环境: 开发库（结构性结论）** —— `server/tests/codegraph/test_measure_repo_index_stats.py`
用内存 Qdrant（hybrid 命名向量，与生产同形）验证：per-repo exact count 与灌入点数一致、
p50/p90/p99/max/median 键齐全、`--verify-cosine` 自查询 top-1 余弦 ≈ 1.0、
单仓 count 异常不中断全量统计。命令口径与输出形状可信，生产执行只是换数据源。

---

## 3. 给 Phase 106 的输入清单

| 输入 | 取值 / 状态 | 依据 |
|------|------------|------|
| N̄（pivoted size normalization 基准） | 取全仓 N_r **中位数**（比均值抗 monorepo 倾斜）——数值待 §2 生产实测 | ROUTING-RANKING §2.3 |
| b（尺寸归一强度） | 初值 **0.6**，golden set 校准后调整 | ROUTING-RANKING §2.3（形式 HIGH / 常数 MEDIUM） |
| MaxP 主干口径（余弦 vs RRF 分） | **依赖 O-3 延迟实测**：延迟可接受 → 余弦（+1 次 dense-only 查询，`using="dense"`）；否则 RRF 分 + 换归一化策略 | 本文档 §1 |
| N_r 分布是否倾斜（尺寸归一收益判断） | 待 §2 直方图：若 p99/median 倍数不大，§2 尺寸归一化收益有限，b 可下调 | ROUTING-RANKING §9 O-1 |

**未完成前置**：§1 延迟数字与 §2 全部分布数据为 deferred 人工步骤
（105-02-SUMMARY「待人工步骤」清单同步登记）。Phase 106 planning 可先按
「余弦口径 + b=0.6 初值」推进公式形式设计，常数定版等生产回填。
