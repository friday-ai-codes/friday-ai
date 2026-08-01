# Phase 107 Measurements — Stage 1 延迟实测（O-6）与三个数值参数的取值依据

**Created:** 2026-07-30
**Producer:** 107-02（`measure_stage1_latency` 命令 + 本文档）
**Consumer:** SC-5（O-6 结论落文档）、A5（per-call 超时是否下调的后续判定）、107-UAT（生产回填挂账）

> **数据环境标注纪律**（沿用 105/106-MEASUREMENTS）：本文档每条结论显式注明数据环境——
> `数据环境: 开发库/CI（结构性结论）` 或 `数据环境: 生产实例 friday.yc345.tv（分布实测）`。
> 开发库上只能得出**结构性结论**（命令可运行、分位口径正确、输出形状符合契约），
> **不得**把本地跑出的 `n=0` 或小样本数字当作延迟分布结论。
> 本文档中未实测处一律写 `deferred` 并给出复测命令，**不出现任何编造的分位数字**。

---

## 1. 数据环境标注

| 环境 | 数据库 | 时间窗 | 样本量 n | 采样率 | 是否含缓存命中 | 状态 |
|------|--------|--------|---------|--------|---------------|------|
| 本地开发 | SQLite（`DATA_DIR/friday.db`） | `--days 7` | `n=0（无生产数据）` | 不适用 | 否（无调用） | 结构性验证已完成 |
| CI | SQLite（pytest 测试库） | 用例构造 | `n=0（无生产数据）`，用例内为人造样本 | 不适用 | 否（无真实调用） | 结构性验证已完成 |
| 生产实例 friday.yc345.tv | PostgreSQL 17 | `--days 7`（建议再取 `--days 30` 对照） | **deferred** | **deferred**（须记录当时 `SettingKeys.LOG_*` 采样配置） | **否**——只含未命中缓存的调用 | **deferred**：待运维执行 |

**复测命令**（任意环境同一条，口径不变）：

```bash
cd server && uv run python manage.py measure_stage1_latency --days 7 --json
```

- Postgres 下走 `percentile_cont`（`WITHIN GROUP (ORDER BY ...)`，精确分位，LOGGING-SPEC §4.3
  纪律：不自研直方图/聚合器），口径与运维大盘一致。
- 非 Postgres（本地 SQLite）自动回退 Python 侧线性插值分位（与 `repo_router_eval._quantile`
  同口径，stdlib）——**dev 降级，结果不得回填本文档**。
- 输出只含聚合量（`event` / `window_days` / `window_start` / `db_vendor` / `n` /
  `p50_ms` / `p90_ms` / `p99_ms`），不回显任何 payload 原文（T-107-02）。
- 零样本时退出码 0 并给排查提示（采样配置 / 组件日志级别 / 缓存命中率过高三种常见成因）；
  查询本身失败则以非零退出码结束（排障工具，失败必须可见）。

**回填时必须同时记录**：执行时刻的采样配置与 `repo_router_v2` 组件日志级别、时间窗、
样本量 n。缺这三项的分位数字无法解读（见 §2 口径说明）。

---

## 2. O-6：Stage 1 延迟分布

**数据环境: 生产实例 friday.yc345.tv（分布实测）——deferred，尚未执行。**

### 口径（读数字前必须知道的三条）

1. **数据源是 `SystemLogEntry.payload.duration_ms`**，事件 `repo_router_v2_stage1_completed`
   （`repo_router_v2._stage1_llm_reasoning` 打点）。**不是** `ModelUsageRecord`——Stage 1
   直调 `build_chat_model(...).ainvoke(...)`，不经 `interactions.ledger.record_model_usage`
   这个写入 chokepoint，故该表里查不到 `aux_repo_router` 的行（107-RESEARCH §9 VERIFIED）。
   `ModelUsageRecord` 埋点补齐在 **107-05**；补齐后本节可增加一条 ledger 口径对照
   （两条口径应当同量级，若显著背离说明有一侧漏记）。
2. **测的是「缓存未命中时的上游真实延迟」，不是用户感知延迟。** Stage 1 输入哈希缓存
   命中的路径既不发 LLM 调用、也不打该事件（打点在 `if not cache_hit:` 块内），
   所以本节分位是上游延迟的**上偏估计**；用户侧平均等待时间随缓存命中率下降。
3. **事件是采样类（`category="sampling"`）且级别为 `logger.info`**：落库量受运行时采样
   配置（`SettingKeys.LOG_*`）影响，可能不是全量；若 `repo_router_v2` 组件日志级别被调到
   WARNING 则一行都没有。分位数字必须与当时的采样率一并记录才可解读。

### 分位占位表（待生产实例执行补录）

| 指标 | 值 | 数据环境 |
|------|----|---------|
| 样本量 n | deferred | 生产实例 friday.yc345.tv（deferred） |
| p50_ms | deferred | 生产实例 friday.yc345.tv（deferred） |
| p90_ms | deferred | 生产实例 friday.yc345.tv（deferred） |
| p99_ms | deferred | 生产实例 friday.yc345.tv（deferred） |
| 采样率 | deferred | 生产实例 friday.yc345.tv（deferred） |

### 已知参考区间（**非本次实测**）

既有生产观测记录的 Stage 1 调用耗时区间为 **34–71s**（来源：107-RESEARCH §5 对现有
`REPO_ROUTER_STAGE1_TIMEOUT_SECONDS=90` 与观测耗时的讨论，属**既有生产观测**而非本
phase 的分位实测）。它只用于说明「per-call 90s 已接近可接受上界量级」这一量纲判断，
**不得**当作 p50/p90/p99 使用。

### 命令本身的结构性验证（已完成）

**数据环境: 开发库/CI（结构性结论）** —— `server/tests/codegraph/test_measure_stage1_latency.py`
（7 用例全绿）验证：

- 5 条人造样本 1000/2000/3000/4000/5000ms → `n=5` 且 p50 落在 [2900, 3100]（线性插值分位）。
- 时间窗过滤（早于 `--days` 的行不计入）与事件名过滤（非目标事件不计入）成立。
- `payload` 缺 `duration_ms`、值为 `None`、值为非数值字符串、`payload` 为空 → 该行跳过，
  不抛异常且不计入 n。
- 零样本 → 不抛、输出含 `n=0` 与排查提示（`ZeroDivisionError` 路径被覆盖）。
- `--json` 为单个可解析对象，键含 `n` / `p50_ms` / `p90_ms` / `p99_ms` / `window_days` /
  `event` / `db_vendor`。
- payload 内即使带凭证形态串，stdout 也不含 `sk-` / `Bearer ` / `AIza` 片段（T-107-02）。
- 本地空库零样本手动跑通：`measure_stage1_latency --days 7 --json` 退出码 0、输出可
  `json.loads`（在已 migrate 的 SQLite 上验证；未 migrate 的库缺表时按设计以非零退出码报错）。

命令口径与输出形状可信，生产执行只是换数据源。

---

## 3. 设计取舍：压不下来时的主要收益来源

**如实记录（SC-5 后半句）**：若生产分位回填后确认 Stage 1 上游延迟压不到可接受范围
（当前量纲判断：p90 仍在数十秒级），本 phase 的收益**主要不来自上游延迟本身的下降**，
而来自以下三条把「不确定的慢」变成「有界的慢」的机制：

1. **Stage 1 输入哈希缓存**（105 已落地）——命中即零上游调用，重复/相似路由请求
   的用户感知延迟降到检索量级。这是唯一能真正把平均延迟压下去的手段。
2. **快照回放**（105 已落地）——离线零网络复现整次路由决策，排障与回归不再需要
   真实上游调用，把「验证一次改动」的成本从分钟级降到毫秒级。
3. **总预算硬上界**（本 phase 107-01 新增 `REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS`）——
   首调 + 1 次重试共享 deadline，超出即降级继续（`degraded=True` 且对用户可见，
   RELY-03），用户不再无限等待；慢从「不可预期」变成「有上界且被告知」。

换句话说：O-6 的价值是**判定要不要继续投资上游延迟优化**，而不是本 phase 的交付依赖。
更深的压降手段（cross-encoder 替代 LLM 重排等）按 CONTEXT `<deferred>` 视 O-6 结论另议。

---

## 4. 三个数值参数的取值依据与已知局限

### 4.1 `REPO_ROUTER_GROUP_DELTA = 0.15`（block ranking 迟滞阈值）

**数据环境: 开发库（golden fixture 离线实测，零网络）**

依据：golden set 两条 `cross_group` 样本在 `phase106-v2` 权重下的
`S_global(1) - S_in_project(1)` 离线实测（107-RESEARCH §10，纯函数 `score_case`）：

| case | S_in_project(1) | S_global(1) | 差值 | delta=0.15 是否触发置顶 | 余量 |
|------|----------------|-------------|------|----------------------|------|
| `gk-008-cross-group-auth` | `edu-content-hub` 0.7565 | `auth-service` 0.9336 | **0.1771** | 触发 | +0.0271 |
| `gk-009-cross-group-payment` | `finance-dashboard` 0.6238 | `payment-gateway` 0.8852 | **0.2614** | 触发 | +0.1114 |

**局限（可用上界受 gk-008 约束）**：delta 一旦 **> 0.1771**，gk-008 就会退回
「本项目组置顶而正确仓被压在下面」——即重演本里程碑要修的那类故障。可用余量仅
**+0.0271**，非常薄：组织内跨组协作频率变化、或打分权重再调，都需要重新校准 delta。
下界侧则**绝不能取 0**：0 会让 0.001 级分数波动反复翻转置顶，破坏幂等与体验
（CONTEXT 锁定）。

上界语义已由 107-01 Task 3 的 golden 机制断言锁定（断言写成 `差值 >= 默认 delta` 而非
`== 0.1771`，避免权重微调造成假红，ROUTING-RANKING §7.4 纪律）。

### 4.2 `REPO_ROUTER_STAGE1_ALPHA = 0.35`（凸组合权重，D-7）

**数据环境: 无（未经数据校准）——这是本参数最重要的已知局限。**

依据：`.planning/research/ROUTING-RANKING.md` §1.3c 给出的**锁定初值**，CONTEXT 裁决
D-7 采纳。凸组合形式为 `S_ranked = (1-α)·S_final + α·S_llm`，其中
`S_llm = 1 - (rank_llm-1)/(N-1)`；Stage 1 降级时 α=0（退化为纯 Stage 0 排序）。

**局限（结构性，不是「暂时没做」）**：α **未经离线校准**，因为离线 harness
（`score_case` / `evaluate_cases`）**结构上不跑 Stage 1**——harness 只走 Stage 0 打分链，
α 在其中恒为 0，故 golden set 无法用于扫 α。可行的校准路径只剩两条：生产 A/B 或
人工抽检；两者都不在本 phase 范围内。

**红线**：**不得**为了校准 α 把凸组合塞进离线 harness。harness 的 `phase106-v2` baseline
是 Phase 106 定版打分口径的回归基准，把 Stage 1 / 凸组合塞进去会改变 baseline 的语义、
污染 106-07 的回放比对与 golden fixture 形状（同时也违反 D-3：`S_ranked` 绝不覆盖
`RepoRouteCandidateV2.score`）。

### 4.3 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = 90.0`（per-call，未下调）+ `REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = 120.0`（新增总预算）

**数据环境: 生产实例（O-6 数字 deferred）——故本 phase 不动 per-call。**

依据（与 107-01 assumptions A5 一致）：A5 要求「必须先做 O-6 实测再定 per-call」。
O-6 的生产分位在本 phase 为 `deferred`，因此：

- **per-call 保持 90.0 不下调**。理由：在没有分位数字的前提下下调，会把原本
  70–89s 能成功返回的调用变成用户可见降级（`degraded=True`），拿走本来拿得到的
  重排收益——用一个可见的回归换一个未经测量的收益，不划算。
- **新增总预算 120.0**，作为「首调 + 1 次重试共享的 deadline」。相对今日行为
  **零回归**：今日单调上界就是 90s，总预算 120 只是给「首调快速失败（网关 5xx /
  连接错误，秒级返回）」留出重试余量；慢调用吃满 90s 后剩余预算不足，重试不会
  发生，行为与今日一致。

**待办（不在本 phase 生效）**：回填 O-6 分位后，研究给出的下调建议区间为
**per-call 40–45s**（依据是既有观测的 34–71s 区间——该区间下沿之上、上沿之下切长尾）。
是否下调、下调到多少，须以回填后的 p90/p99 与「降级率上升幅度」共同判定，
记入 107-UAT 后续项。

---

## 5. 待回填清单（UAT 交接）

以下均为「管线已就绪、只差在生产实例跑命令回填数字」的人工步骤（同 105/106 UAT 纪律，
数据环境标注不可省略）：

| # | 项 | 执行方式 | 回填位置 |
|---|----|---------|---------|
| 1 | **O-6** Stage 1 延迟分位 p50/p90/p99 与样本量 n | `cd server && uv run python manage.py measure_stage1_latency --days 7 --json`（生产 Postgres 走 `percentile_cont`；建议同时取 `--days 30` 对照） | 本文档 §2 分位占位表 + §1 生产行 |
| 2 | **采样率与组件日志级别快照** | 记录执行时刻的 `SettingKeys.LOG_*` 采样配置与 `repo_router_v2` 组件日志级别 | 本文档 §1 生产行「采样率」列 |
| 3 | **per-call 超时下调判定（A5 收口）** | 以 §2 回填的 p90/p99 对照建议区间 40–45s，评估下调后的预期降级率 | 本文档 §4.3「待办」段 + `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 取值 |
| 4 | **ledger 口径对照**（107-05 埋点补齐后） | 用 `ModelUsageRecord`（`call_source=aux_repo_router`）的既有分位聚合与 §2 数字对照，量级应一致 | 本文档 §2 口径第 1 条 |

**未完成前置的运行态**：O-6 回填前，Stage 1 按 per-call 90.0 / 总预算 120.0 运行，
α 按锁定初值 0.35 运行，delta 按 0.15 运行——三者均已外置（settings + env），
回填后调整无需改代码。
