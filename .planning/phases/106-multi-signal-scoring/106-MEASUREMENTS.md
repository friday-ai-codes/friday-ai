# Phase 106 Measurements — 多信号打分常数定版输入实测（O-2 / O-5）

**Created:** 2026-07-29
**Producer:** 106-04（`measure_repo_index_stats --activity/--write-snapshot` + `calibrate_repo_router_metadata` + 本文档）
**Consumer:** 打分常数定版（`t2_c_lo`/`t2_c_hi`/`t2_disabled_facets`）、ROUTE-05 覆盖率证据、106-06 router breadth 供数（N_r 快照）

> **数据环境标注纪律**（沿用 105-MEASUREMENTS）：本文档每条结论显式注明数据环境——
> `数据环境: 开发库（结构性结论）` 或 `数据环境: 生产实例 friday.yc345.tv（分布实测）`。
> 开发库上只能得出**结构性结论**（命令可运行、统计口径正确、输出形状符合契约），
> 不得作为覆盖率 / 余弦分布结论供打分常数定版消费（RESEARCH Pitfall 8）。

---

## 1. O-5：全仓 last_commit_at 覆盖率/新鲜度 + facets 五维覆盖率（待生产实例执行）

**数据环境: 生产实例 friday.yc345.tv（分布实测）——deferred 人工步骤，尚未执行。**
本地开发库无真实仓数据，本地跑出的全 0 / 小样本结果不得写入本节占位表。

### 执行指引（人工步骤）

在有真实数据的部署实例（friday.yc345.tv）上运行：

```bash
cd server && uv run python manage.py measure_repo_index_stats --activity --write-snapshot
```

（默认输出 markdown 表便于直接回填；机器可读加 `--json`。`--activity` 只读统计；
`--write-snapshot` 会把 N_r 全表 + N̄ 中位数写入 SystemSetting
`repo_router.nr_snapshot`——这是 106-06 router pivoted breadth 的数据源，
**索引重建后运维需重跑一次**刷新快照。空库拒绝写入，不会覆盖有效快照。）

### last_commit_at 覆盖率/新鲜度占位表（待生产实例执行补录）

| 指标 | 值 | 数据环境 |
|------|----|---------|
| 总仓数（is_deleted=False） | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| last_commit_at 有值仓数 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 覆盖率 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 新鲜度 p50（距 now 天数） | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 新鲜度 p90（距 now 天数） | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |

**消费方式（ROUTE-05）**：覆盖率决定连续活跃度（指数衰减）能覆盖多少仓——
无 `last_commit_at` 的仓打分侧自动走枚举回退 {活跃开发:0.9, 维护中:0.6, 低频:0.3, 疑似废弃:0.1}，
无需人工干预；覆盖率过低（<50%）时枚举回退是主路径，H/offset 常数调优收益有限。

### facets 五维覆盖率占位表（待生产实例执行补录）

| facet | 覆盖率 | 数据环境 |
|-------|--------|---------|
| 业务线/产品线（非空且非「未分类」） | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 技术栈 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 团队归属 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 关键程度 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |
| 活跃度 | 待生产实例执行补录 | 生产实例 friday.yc345.tv（deferred） |

**消费方式（ROUTE-04）**：覆盖率低的 facet 大概率整体走缺失重归一化——
若某 facet 生产覆盖率 <30%，其权重调优优先级应下调（信号常年缺席）。

### 命令本身的结构性验证（已完成）

**数据环境: 开发库（结构性结论）** —— `server/tests/codegraph/test_measure_repo_index_stats.py`
用内存 Qdrant（hybrid 命名向量，与生产同形）+ SQLite 测试库验证：

- `--activity` 覆盖率口径正确：每仓取 `FileIndex` 按仓 `Max(last_commit_authored_at)`
  一次聚合；无 FileIndex 行的仓与行存在但 `last_commit_authored_at` 全 NULL 的仓
  均计入未覆盖；新鲜度 p50/p90 为距 now 天数的线性插值分位数
  （与 `repo_router_eval._quantile` 同口径，stdlib 禁 numpy）。
- facets 五维覆盖率键集合恰为 {业务线/产品线, 技术栈, 团队归属, 关键程度, 活跃度}；
  `业务线/产品线` 的「未分类」计未覆盖，其余维度非空即覆盖。
- `--write-snapshot` 写读闭环：写入后 `load_nr_snapshot()`（106-02 loader）读回
  `n_r_by_repo`/`n_bar` 与写入一致；`n_bar` = 有索引仓（node_count > 0）节点数的
  `statistics.median`（中位数抗 monorepo 倾斜，ROUTING-RANKING §2.3 N̄ 行）；
  0 计数仓保留在 `n_r_by_repo` 全表中。
- 空库（无任何已索引仓）`--write-snapshot` 拒绝写入（防空快照覆盖有效值，T-106-09）。

命令口径与输出形状可信，生产执行只是换数据源。

---

## 2. O-2：需求文本 × facet 值余弦分布校准（由 106-04 Task 2 补）

（占位——本节由 `calibrate_repo_router_metadata` command 落地后补齐。）
