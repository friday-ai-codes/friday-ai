# 多信号仓库路由与检索排序 — 设计调研

**服务于：** Friday AI v0.19.0 里程碑 ROUTE 需求组
**任务定义：** 给定一段自然语言需求，从 ~259 个代码仓库中定位「应该改哪个」
**调研日期：** 2026-07-28
**整体置信度：** MEDIUM-HIGH（方法论与公式形式 HIGH，具体常数取值 MEDIUM，需 golden set 校准）
**冷启动约束：** 全文假设无点击日志、golden set 规模 10–50 条。所有"需要训练数据"的方案一律标注不可用。

---

## 0. 结论速览（给 roadmapper 的可执行摘要）

| 决策点 | 结论 | 置信度 |
|--------|------|--------|
| 融合方式 | **线性加权和**（signal fusion 层）+ **级联重排**（LLM 有界重排），**不做 LTR** | HIGH |
| RRF 用在哪 | 只用在 Stage 0 的 dense+sparse 合并（现状保持，k=60），**不要**用 RRF 融合元数据信号 | HIGH |
| 多命中聚合 | **MaxP 为主干 + pivoted-size-normalized 对数饱和 breadth 加成**（加性、上限 λ=0.25） | HIGH（形式）/ MEDIUM（常数） |
| 尺寸偏置修正 | BM25 的 `b` 思想：`n_eff / (1 - b + b·N_r/N̄)`，b 初值 **0.6** | HIGH |
| 元数据匹配 | 三层：确定性别名词典 → 校准后的 embedding 余弦 → **不用 LLM 进分数** | HIGH |
| 多值 facet 聚合 | **取 max，绝不取 sum**（否则尺寸偏置在元数据侧重演） | HIGH |
| 活跃度 | 指数衰减 `0.5^(Δd/H)`，半衰期 **H=180d**，offset 14d，floor 0.05 | MEDIUM |
| 缺失信号处理 | **权重重归一化**，不是补 0（补 0 = 把"未知"当"不匹配"罚） | HIGH |
| confidence 判定 | 改为**确定性的分数 margin 规则**，LLM confidence 降为输入而非决策者 | HIGH |
| 分组呈现 | **一套分数、组内全序、组间不全序**；组别只影响呈现与 trust 标注，绝不进分数 | HIGH |
| 主评估指标 | **Recall@5**（主）+ MRR@10（次）+ 误自动选中率（护栏）；nDCG 不用 | HIGH |
| golden set 定位 | **回归门禁**，不是优化目标。n=10–50 只能检出大幅退化 | HIGH |
| LLM 幂等 | temperature=0 **不充分**；靠"输出排列而非分数 + 输入哈希缓存 + 快照回放" | HIGH |

---

## 1. 融合方式选型

### 1.1 三条路线的适用条件与代价

| 方案 | 需要的数据量 | 适用条件 | 代价 | 本项目判定 |
|------|-------------|---------|------|-----------|
| 线性加权和 | 0（人工设权）～50 条（微调） | 信号数 ≤ 10、每个信号语义清晰、需要可解释 | 无法表达信号交互（如"技术栈匹配只在业务域也匹配时才有意义"）；权重靠人拍 | ✅ **采用** |
| Learning-to-Rank（LambdaMART / RankNet / ListNet） | 数百～数千条带标注 query | 有稳定标注流或点击日志 | 10–50 条 × 6 特征必然过拟合；模型不可解释，违反"分数必须可拆解"原则 | ❌ **否决** |
| Coordinate Ascent（线性 LTR） | 50～200 条 | 小样本下最稳的 LTR 变体 | 仍需 k-fold CV；n=20 时 fold 间方差大 | ⚠️ **只作"权重建议器"**，不做自动上线 |
| 级联重排（retrieve → rerank） | 0（zero-shot LLM/cross-encoder） | 第一阶段召回率足够高 | 重排器无监督时可能比第一阶段更差；LLM 引入非幂等与延迟 | ✅ **保留但必须有界** |

**为什么否决 LTR：** LambdaMART 类模型在 LETOR/MSLR 上的标准训练规模是 10k+ query。20 条 query × 每条 ~12 个候选 = 240 个样本、6+ 特征，参数量与样本量同数量级。TREC News 的实践报告（Middlebury TREC-30）显示，即使有 120 条训练 query，Random Forest 仍明显过拟合，而 Coordinate Ascent 这种**线性、直接优化 IR 指标**的模型反而最好——这是小样本下的一般规律，而我们的样本量比那个还小一个数量级。

来源：
- Metzler & Croft, *Linear feature-based models for information retrieval*, Information Retrieval 10(3), 2007（Coordinate Ascent 原始论文）
- RankLib 文档明确记 Coordinate Ascent 是唯一在无 validation set 时也工作良好的算法：https://sourceforge.net/p/lemur/wiki/RankLib%20How%20to%20use/
- Middlebury TREC-30 报告（小样本下 CA > RF）：https://trec.nist.gov/pubs/trec30/papers/middlebury-N.pdf

### 1.2 为什么不用 RRF 融合信号层（这是个容易踩的坑）

RRF 的优势在于**尺度不变**：它只看 rank 不看 score，因此天然解决"BM25 分数和余弦相似度不可比"的问题，且无需调参（Cormack et al., SIGIR 2009，k=60 是 pilot 阶段定的经验常数，社区实测 k∈[20,100] nDCG@10 差异 < 0.5 点）。

**但 RRF 在信号融合层是错的**，理由：

1. **元数据信号产生退化排名。** `关键程度` 只有 4 档，全部"核心"仓库并列第一。RRF 对并列没有定义良好的处理，实现上通常按输入顺序打破——直接引入不可复现的顺序依赖。
2. **RRF 丢弃幅度，而我们恰恰需要幅度。** 业务需求是"文本证据必须压过元数据"，这是一个 4:1 的幅度关系。RRF 里每个 list 的权重是相等的（除非加 weighted-RRF，但那又回到了调权重，还多丢了幅度信息）。
3. **RRF 假设各 list 是独立的相关性证据。** 我们的信号高度相关（业务域匹配和文本命中显然相关），共识投票的语义不成立。

**结论：分层用不同融合器。** Stage 0 内部（dense vs sparse，两个独立的、尺度不可比的排序器）继续用 RRF k=60；信号融合层用归一化后的线性加权和。这不是折中，是各用其所长。

来源：Cormack, Clarke & Buettcher, *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*, SIGIR 2009 — https://cormack.uwaterloo.ca/cormacksigir09-rrf

### 1.3 级联重排的边界化（针对本次生产事故的直接修正）

现状失败链：Stage 1 LLM 降级 → confidence 恒 low → `auto_selected` 恒 false → 编排卡死。根因是**把一个不可靠组件放在了决策关键路径上，且没有 fallback 语义**。

三条修正，按重要性排序：

**(a) confidence 改为确定性推导，不由 LLM 断言。**

```python
margin = S(1) - S(2)                       # 归一化分数差
if S(1) >= 0.55 and margin >= 0.08:  conf = "high"
elif S(1) >= 0.35:                   conf = "medium"
else:                                conf = "low"
```
LLM 的 confidence 输出降级为**一个额外信号**（可用于在边界情况把 high 降为 medium，但不能把 low 升为 high）。这样 Stage 1 完全失联时，系统仍能产出 high confidence 并自动推进。
置信度：HIGH（这是纯工程解耦，不依赖任何检索理论）。阈值 0.55/0.08 是初值，需 golden set 校准。

**(b) LLM 只允许在有界窗口内重排（rank-swap budget）。**

```
约束：|rank_llm(r) - rank_stage0(r)| <= K,  K = 3
且 LLM 不得引入 Stage 0 Top-12 之外的仓库
```
代价：LLM 无法修正 Stage 0 的严重错误（若正确仓在 Stage 0 排第 8，LLM 最多提到第 5）。收益：LLM 幻觉/降级造成的损害有硬上界，且可写成单元测试。冷启动下（无法验证 LLM 重排质量优于 Stage 0）这个取舍是对的。
置信度：MEDIUM-HIGH（工程惯例，无直接文献；但与 vertical selection 中"不可比证据不硬拼"的原则一致）。

**(c) 最终分数是两阶段的凸组合，不是替换。**

```
S_final(r) = (1 - α)·S_stage0(r) + α·S_llm(r),   α = 0.35
S_llm(r)   = 1 - (rank_llm(r) - 1) / (N - 1)     # LLM 排名映射回 [0,1]
Stage 1 降级时：α = 0，且 degraded=True 必须对用户可见
```
置信度：MEDIUM（α=0.35 是拍的；建议 golden set 上扫 α ∈ {0, 0.2, 0.35, 0.5}）。

---

## 2. 多命中聚合：如何消除尺寸偏置

### 2.1 现行公式的病理

```python
score = max_score * (1 + 0.1 * min(hits - 1, 5))    # 现状
```

三个独立缺陷：

1. **加成是乘性的且上限 1.5×。** 一个含 62 子应用的 monorepo 拿满 1.5×，一个小而精的仓拿 1.0×。后者要赢必须 max_score 高出 50%——而 RRF 分数的动态范围本来就窄（rank 1 到 rank 10 只差 15%），**结构上不可能**。这就是 `study-app` 碾压 `onion-learning` 的确切机制。
2. **hits 是原始计数，不含任何尺寸归一。** 大仓命中多是几乎确定的先验事实，不是相关性证据。
3. **`score = min(c["score"], 1.0)` 的截断**（见 `repo_router_v2.py:252`）会让多个高分仓并列在 1.0，销毁排序信息且让 tie-breaking 随机化。

### 2.2 检索领域的四种标准手段及代价

| 手段 | 公式 | 解决什么 | 代价 |
|------|------|---------|------|
| **MaxP** | `S = max_i s_i` | 完全免疫命中数偏置 | 丢失"多处相关"的证据；单个 outlier 节点能决定全局 |
| **SumP** | `S = Σ s_i` | 捕获广度 | 尺寸偏置最严重 |
| **AvgP** | `S = Σ s_i / m` | 归一化尺寸 | 惩罚过头：一个大仓有 1 个完美命中 + 9 个弱命中，均值反而低于只有 1 个中等命中的小仓 |
| **LogSumExp** | `S = τ·ln Σ exp(s_i/τ)` | τ→0 退化为 max，τ→∞ 退化为 sum，连续可调 | 不可拆解（无法回答"这 0.03 分从哪来"），违反本项目"分数必须可拆解"原则 |
| **Pivoted length norm** | `÷ (1-b + b·len/avg_len)` | 用一个参数 b 在"不归一"和"完全归一"之间连续插值 | 需要知道 avg_len；b 需调 |
| **对数饱和** | `ln(1+x)` / `x/(x+pivot)` | 让边际命中递减收益 | 无法区分"10 个命中"和"20 个命中"（这通常是好事） |

**文献结论：MaxP 一般最优，MaxP 与 SumP 差距小。** Dai & Callan（SIGIR 2019）在 Robust04/ClueWeb09 上比较 FirstP/MaxP/SumP，MaxP 除一个设置外都最优；Zhang et al.（ECIR 2021）复现并推广到新数据集，结论一致。这直接支持"max 做主干，广度做小加成"的结构，而不是相反。

**分布式 IR 的教训更贴切。** 我们的任务本质是 **resource selection / shard selection**——"给定 query，选哪个 collection 去搜"，这是 federated search 的核心问题，与"选哪个仓"同构。CORI 算法在集合尺寸分布倾斜时表现很差；Si & Callan（SIGIR 2003）提出的 ReDDE 之所以更好，**核心就是显式引入集合尺寸 `|C_i|` 做缩放**。Web 场景的后续工作（Resource Selection for Federated Search on the Web, 2016）直接给出结论：*"考虑集合估计尺寸的资源选择方法，明显优于不考虑尺寸的方法"*，且*"集合尺寸对性能有巨大影响"*。我们现在正在犯的就是 CORI 的错。

来源：
- Dai & Callan, *Deeper Text Understanding for IR with Contextual Neural Language Modeling*, SIGIR 2019
- Zhang et al., *Comparing Score Aggregation Approaches for Document Retrieval with Pretrained Transformers*, ECIR 2021 — https://cs.uwaterloo.ca/~jimmylin/publications/ZhangXinyu_etal_ECIR2021.pdf
- Si & Callan, *Relevant Document Distribution Estimation Method for Resource Selection*, SIGIR 2003 — https://www.cs.cmu.edu/~callan/Papers/sigir03-lsi.pdf
- Si & Callan, *Distributed Information Retrieval With Skewed Database Size Distributions*, 2003 — https://www.cs.cmu.edu/~callan/Papers/dgo03-lsi.pdf
- *Resource Selection for Federated Search on the Web*, arXiv:1609.04556 — https://ar5iv.labs.arxiv.org/html/1609.04556
- Robertson & Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*（b 参数的 verbosity/scope 两假设推导）— https://www.khoury.northeastern.edu/home/vip/teach/IRcourse/IR_surveys/robertson_foundations.pdf
- Singhal, Buckley & Mitra, *Pivoted Document Length Normalization*, SIGIR 1996

### 2.3 建议的聚合公式（完整可实现）

**前置：分数归一化。** Stage 0 的 RRF 原始分在 ~0.016 量级，必须先归一。用 **query-local max 归一**（不用 min-max，因为 min-max 对 outlier 敏感）：

```python
s_hat[i] = rrf_score[i] / rrf_score_max_of_this_query      # ∈ (0, 1], rank1 恒为 1.0
```
注意：这样 `s_hat[0] == 1.0` 恒成立，所以 MaxP 项本身不再有区分度。因此 **MaxP 主干要用「跨 query 可比的绝对强度」**，建议用 dense 余弦（Stage 0 已有）而非 RRF 分：

```python
S_top(r) = calibrate(max_i cosine_i)     # 见 §3.2 的 affine clip 校准
```

**聚合三步：**

```python
# Step 1 — 有效命中数（软计数，弱命中不算满分）
#   p=2：分数为 top hit 一半的节点只贡献 0.25 个命中
n_eff = sum((s_hat[i] / s_hat[0]) ** p for i in range(m))       # p = 2, n_eff ∈ [1, m]

# Step 2 — pivoted size normalization（BM25 的 b 思想）
#   N_r  = 该仓在 repo_index_nodes 中的能力树节点总数（离线可得，非本次查询命中数）
#   N_bar = 全部仓库 N_r 的均值（或中位数，更抗倾斜；建议用中位数）
denom  = 1.0 - b + b * (N_r / N_bar)                             # b = 0.6
n_norm = n_eff / denom

# Step 3 — 对数饱和 + 归一到 [0,1]
breadth = min(math.log1p(n_norm) / math.log1p(n_cap), 1.0)       # n_cap = 6

# 文本证据合成（加性，不是乘性）
S_text = (1 - lam) * S_top + lam * breadth                       # lam = 0.25
```

**参数初值与含义：**

| 参数 | 初值 | 含义 | 调整方向 |
|------|------|------|---------|
| `p` | 2 | 软计数陡度。p=1 → 线性计数；p→∞ → 只算 top hit | 若发现"一个强命中的小仓被多个中等命中的大仓压过"，调高到 3 |
| `b` | 0.6 | 尺寸归一强度。0=不归一（现状），1=完全按密度 | monorepo 仍占优 → 调到 0.8；小仓噪声被过度放大 → 降到 0.4 |
| `N_bar` | 全仓节点数**中位数** | 用中位数不用均值 — 62 子应用的 monorepo 会把均值拉爆 | — |
| `n_cap` | 6 | breadth 饱和点。6 个有效命中 ≈ 满分 | — |
| `lam` | 0.25 | breadth 在文本证据中的占比上限 | 广度信号被证明无效（ablation 不降）→ 归 0 |

**为什么加性不乘性：** 乘性加成的效果依赖 `S_top` 的大小（S_top=0.9 时 1.5× 加成 = +0.45 绝对分，S_top=0.3 时只 = +0.15），这让"广度贡献了多少分"依赖于另一个信号——不可拆解。加性形式下 breadth 的贡献恒为 `lam·breadth`，可以直接在 UI 上写"广度 +0.11"。

### 2.4 用真实 case 验证公式（`study-app` vs `onion-learning`）

设（示意值，落地时用真实节点数）：`study-app` 有 62 子应用 → N_r ≈ 620 节点，命中 6 个；`onion-learning` → N_r ≈ 30 节点，命中 1 个；全仓节点数中位数 N̄ ≈ 60。

| | 现行公式 | 新公式（b=0.6, n_cap=6, λ=0.25） |
|---|---|---|
| `study-app` 加成 | `1 + 0.1×5 = 1.50×` | denom = 0.4 + 0.6×(620/60) = 6.6；n_eff ≈ 6 → n_norm = 0.91；breadth = ln(1.91)/ln(7) = **0.33** |
| `onion-learning` 加成 | `1 + 0 = 1.00×` | denom = 0.4 + 0.6×(30/60) = 0.7；n_eff = 1 → n_norm = 1.43；breadth = ln(2.43)/ln(7) = **0.46** |
| 净效果 | onion-learning 需 max_score 高出 **50%** 才能赢 | breadth 项**反向倾斜 0.13**，乘 λ=0.25 → 折算 **+0.03** 给 onion-learning |

即：偏置从 "+50% 给大仓" 翻转为 "+0.03 给小仓"。翻转的幅度小且有界，这是刻意的——不能矫枉过正把大仓一律打死（`study-app` 有时确实是对的）。

置信度：MEDIUM（数值示意；N_r 的真实分布未实测，落地第一步应先打印全仓 N_r 直方图确认 N̄ 与 b 的合理性）。

---

## 3. 元数据信号的量化与融入

### 3.1 三层匹配策略

| 层级 | 方法 | 输出 | 何时用 | 代价 |
|------|------|------|--------|------|
| **T1 别名词典**（推荐主力） | facet 值 + 人工同义词表，对需求文本做确定性匹配 | 1.0 精确/别名命中；0.6 上位类目命中；未命中→进 T2 | 首选 | 需维护每 facet 几十条别名；新业务线出现时会漏 |
| **T2 校准 embedding 余弦** | `cos(embed(需求), embed(facet值+别名串))` 经 affine clip | [0,1] | T1 该组全部未命中时 | 需要一次性校准；facet 值向量可全量缓存（闭集，几百条） |
| **T3 LLM 判定** | — | — | **不进分数** | 破坏幂等 + 成本 + 不可拆解。只在 Stage 1 prompt 里作为解释材料 |

trace 中必须记录每个 facet 分数来自哪一层（T1/T2/缺失），这是可解释性的最低要求。

### 3.2 embedding 余弦必须校准（最容易被忽略的一步）

原始余弦**不能**直接当 0–1 分。中文短文本在多语 sentence embedding 上，完全无关的两句话余弦通常落在 0.20–0.40，强相关落在 0.50–0.70。若直接用余弦，所有 facet 都拿 0.3 左右——信号方差趋零，权重再大也不起作用（这正是"信号加了但没用"的典型死法）。

```python
M = clip((cos - c_lo) / (c_hi - c_lo), 0.0, 1.0)
# 初值：c_lo = 0.25, c_hi = 0.55
```

**校准流程（必做，一次性，约 30 分钟）：**
1. 随机抽 200 组「随机需求 × 随机 facet 值」（负样本），算余弦，取 **p95** 作为 `c_lo`。
2. 抽 30 组人工确认匹配的「需求 × facet 值」（正样本），取 **p50** 作为 `c_hi`。
3. 若 `c_hi - c_lo < 0.10`，说明该 embedding 模型无法区分这个 facet → **放弃该 facet 的 T2 通道**，只保留 T1。

置信度：HIGH（方法）；c_lo/c_hi 具体值 LOW，**必须实测**，换 embedding 模型必须重校准并把模型 id 写进权重版本号。

### 3.3 多值 facet：取 max，绝不取 sum

若一个仓的 `技术栈` 有 8 个值（Vue/TS/Go/Python/…），而另一个只有 2 个：

```python
M_stack = max(match(v) for v in facet_values)      # ✅
M_stack = sum(match(v) for v in facet_values)      # ❌ 标签越多分越高
M_stack = mean(match(v) for v in facet_values)     # ❌ 一个精确命中被 7 个无关标签稀释
```

这是 §2 尺寸偏置在元数据侧的完全同构重演，很容易漏掉。可选折中：`0.8·max + 0.2·second_max`，保留"多重匹配更强"的一点信号，但上限受控。

### 3.4 缺失信号：权重重归一化，不是补 0

大量仓库的 facets 是不完整的。若缺失补 0，等于把"未知"当成"确认不匹配"来惩罚——系统性地偏袒元数据填得全的仓，与相关性无关。

```python
available = [j for j in signals if j.is_present]
S = sum(w[j] * M[j] for j in available) / sum(w[j] for j in available)
```
性质：S 仍在 [0,1]；全部元数据缺失时退化为纯文本分数（正确的降级语义）；且是幂等的纯函数。
置信度：HIGH。

### 3.5 活跃度：从 4 档枚举改连续时间衰减

**推荐函数：指数衰减（对应 Elasticsearch `exp` decay，`scale`=半衰期，`decay`=0.5）**

```python
delta_days = max(0.0, (now - last_commit_at).days - offset_days)   # offset = 14
A_recency  = 0.5 ** (delta_days / H)                               # H = 180
A_act      = max(A_recency, A_floor)                               # A_floor = 0.05
```

**为什么 exp 而不是 gauss：** ES 的两条曲线在 2×scale 处差异巨大——gauss 掉到 0.0625，exp 还有 0.25。我们要长尾：一个一年没提交但确实正确的仓，必须仍然可召回（本里程碑「召回优先于精排」原则）。gauss 的钟形顶部（近期不区分）在这里也不需要——`offset=14d` 已经提供了平顶。

**半衰期 H 的取值经验：**

| H | 效果 | 适用 |
|---|------|------|
| 90d | 季度性维护的仓掉到 0.5 以下 | 快迭代的产品仓群 |
| **180d** | 半年无提交 → 0.5；一年 → 0.25；两年 → 0.06 | ✅ 推荐初值 |
| 365d | 两年内几乎不区分 | 大量长期稳定的基础设施仓 |

**`疑似废弃` 的处理改法。** 现行是 `score *= 0.5` 的乘性惩罚——它把加性可拆解模型污染成混合模型。改为**对 A_act 施加上限**：

```python
if facets.get("活跃度") == "疑似废弃":
    A_act = min(A_act, 0.10)
```
这样惩罚仍然生效，但完全落在 A_act 这一项内，`w_act × A_act` 的贡献依然可以在 UI 上单独展示。若有明确的 archived 标志（而非启发式判断），才做硬过滤。

**v2 可选增强（本次不做）：** `A = 0.7·A_recency + 0.3·(c90 / (c90 + 20))`，c90 = 近 90 天 commit 数，饱和 pivot=20。理由：只看最后一次提交无法区分"活跃开发"和"上周改了个 typo"。

来源：Elasticsearch function_score decay functions 官方文档 — https://www.elastic.co/guide/en/elasticsearch/reference/8.19/query-dsl-function-score-query.html（gauss/exp/linear 的精确公式与 scale/offset/decay 语义）
置信度：HIGH（函数形式与参数语义）/ MEDIUM（H=180d 是判断，需 golden set 验证）

### 3.6 `关键程度` 是先验，不是匹配信号 — 必须小权重

`关键程度`（核心/重要/一般/边缘）**与 query 无关**。它是一个静态先验，和 PageRank 在网页排序中的地位一样：有用，但如果权重给大了，会让"核心仓"在所有查询上都排前面，这正是我们要避免的另一种结构性偏袒（把 monolith 偏置换成了 critical 偏置）。

```python
CRITICALITY = {"核心": 1.0, "重要": 0.7, "一般": 0.4, "边缘": 0.15}
```
权重上限建议 **0.05**，且建议只作为**同分带内的排序依据**（当 |S_a - S_b| < 0.03 时才让它起作用）。同理适用于 `技术形态`、`服务对象` 这类静态属性。

`团队归属` 是条件信号：需求文本里没有提到任何团队时，该项应标为 **不可用**（走 §3.4 的重归一化），而不是给所有仓 0.5。

---

## 4. 各信号归一化与权重初值表

**约束：** 所有 `M_j ∈ [0,1]`；`Σw_j = 1.00`；`S_final ∈ [0,1]`。缺失项走 §3.4 重归一化。

| 信号 | 符号 | 归一化方法 | 权重初值 | 缺失时 | 来源层 | 置信度 |
|------|------|-----------|---------|--------|--------|--------|
| 文本证据（MaxP + breadth） | `S_text` | `(1-λ)·calibrate(cos_max) + λ·breadth`，见 §2.3 | **0.55** | 不可能缺失（候选来自它） | Stage 0 | HIGH |
| 业务域 / 产品线匹配 | `M_domain` | T1 别名 → T2 校准余弦；多值取 max | **0.15** | 重归一化 | facets | MEDIUM |
| 活跃度（连续） | `A_act` | `0.5^(Δd/180)`，offset 14d，floor 0.05，废弃封顶 0.10 | **0.12** | 无 commit 时间 → 用枚举映射 {活跃开发:0.9, 维护中:0.6, 低频:0.3, 疑似废弃:0.1} | git + facets | MEDIUM |
| 技术栈 / 架构适配 | `M_stack` | 同 domain；`0.8·max + 0.2·second` | **0.08** | 重归一化 | facets | MEDIUM |
| 团队归属 | `M_team` | T1 别名；需求未提团队 → **标为不可用** | **0.05** | 重归一化（常见） | facets | MEDIUM |
| 关键程度（静态先验） | `C_crit` | 固定锚点 {1.0, 0.7, 0.4, 0.15} | **0.05** | 重归一化 | facets | MEDIUM |
| **合计** | | | **1.00** | | | |

**不变量（应写成测试）：**
- INV-R1：`0 ≤ S_final ≤ 1`，且不存在 §2.1 那种 `min(score, 1.0)` 截断。
- INV-R2：元数据信号权重之和 = 0.45 ≤ 0.5 — 文本证据永远占主导。可证明推论：一个 `S_text` 落后领先者 0.45 以上的仓，任何元数据组合都无法把它排到第一。
- INV-R3：所有信号的贡献 `w_j·M_j` 可单独输出，且 `Σ = S_final`（重归一化后仍成立）。
- INV-R4：关掉任一信号（w=0）不改变其余信号的相对贡献比例。

**LLM 重排在此之上：** `S_ranked = 0.65·S_final + 0.35·S_llm`（§1.3c），Stage 1 降级时 α=0。

**外置存储：** 全部权重与常数（`p, b, n_cap, λ, H, offset, c_lo, c_hi, α, K, θ_abs, θ_rel, CRITICALITY 表`）落 `SystemSetting`，附一个 **weight_set_version** 字符串。任何评估结果必须绑定这个 version + prompt hash 才有意义。

---

## 5. 分层 / 分组召回的呈现与打分

### 5.1 两组分数是否可比？

**可比，当且仅当：用完全相同的打分函数、相同的特征集，且没有任何 group-conditional 项。**

具体要求：
- ❌ 不要给「本项目关联仓」加 `+0.1` 的 in-domain boost。加了之后两组分数立刻不可比，"跨组结果分数更低"就变成了自我实现的预言，用户无法判断到底是相关性低还是被罚了。
- ✅ 组别信息只出现在**独立字段**里：`group ∈ {in_project, global}`、`trust ∈ {trusted, needs_confirmation}`、`cross_group_note`。
- ✅ 若确实需要表达"域内优先"的产品偏好，把它做成**呈现层的默认排序 + 默认勾选**，而不是分数偏移。呈现层的偏好是可关闭、可解释的；分数偏移是不可见的。

### 5.2 组间：不做全序，做 block ranking

aggregated search / vertical selection 领域的核心教训正是这个：不同 vertical 的证据类型不同、同一特征在不同 vertical 上的预测力也不同，因此**强行拼成一个全序会引入不可解释的偏差**；工业做法是把 vertical 当成一个 block，先决定「选哪些 block」，再决定「block 放在什么位置」，而不是把所有条目倒进一个排序器。

来源：
- Arguello et al., *Sources of Evidence for Vertical Selection*, SIGIR 2009 — https://841.io/doc/vertical-selection.pdf
- Arguello & Diaz, *Learning to Aggregate Vertical Results into Web Search Results*, CIKM 2011 — https://ils.unc.edu/~jarguell/ArguelloCIKM11Extended.pdf

**落地建议：**

```
呈现结构：
  【本项目关联仓】     组内按 S_ranked 降序，展示 Top-3，trust=trusted
  【全局候选】         组内按 S_ranked 降序，展示 Top-3，trust=needs_confirmation
                       每条带 badge：「未关联当前平台，可能涉跨组协作」

置顶决策（block ordering，带迟滞）：
  if S_global(1) - S_in_project(1) >= delta:      # delta = 0.15
      把全局组置顶，并显式提示「更匹配的仓不在本项目关联范围内」
  else:
      本项目组置顶
```

`delta = 0.15` 是**迟滞阈值**（hysteresis），不是 0。用 0 会让两组分数在 0.001 级别波动时反复翻转置顶，用户体验和幂等都受损。0.15 大约相当于「一整个元数据信号的满分贡献」，语义上是"要跨组胜出，必须有实质性优势"。

**这套方案的代价（必须说清）：**
1. 一套分数意味着**不能对域内单独校准**。域内样本更多，理论上可以拟合得更准；我们放弃了这个收益，换取可比性与可解释性。冷启动下这个交换是划算的（域内样本也远不够拟合）。
2. `delta` 是又一个手调参数，且它的最优值取决于「跨组协作」在这个组织里的真实频率——golden set 里必须包含至少 2–3 条「正确答案在跨组」的样本，否则 delta 无从校准。
3. 两组各展示 Top-3 会让用户面对 6 个候选（认知负担上升）。若 in-project 组首位 confidence=high 且 delta 未触发，建议默认折叠全局组。

---

## 6. 可复现与幂等保证清单

### 6.1 首要事实：temperature=0 不保证同输入同输出

这是必须让实现者知道的一个反直觉事实。生产推理服务的非确定性主因**不是**采样随机性，而是**缺少 batch invariance**：服务端动态 batching，batch size 随并发负载变化；matmul / attention / RMSNorm 的归约顺序依赖 batch size；浮点加法不满足结合律 → logits 出现末位差异 → 在近似平局的 token 上分歧 → 输出发散。batch size 由别人的请求决定，完全不在你的控制内。

来源：Thinking Machines Lab, *Defeating Nondeterminism in LLM Inference* — https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/；vLLM `VLLM_BATCH_INVARIANT=1` 文档 — https://docs.vllm.ai/en/stable/features/batch_invariance/（代价：吞吐下降 50–60%，且我们用的是第三方网关，根本无法开启）

**推论：既然无法在模型层保证幂等，就必须在系统层保证。**

### 6.2 幂等保证清单（按优先级）

| # | 措施 | 具体做法 | 保证强度 | 代价 |
|---|------|---------|---------|------|
| 1 | **输入哈希缓存 + 回放** | `key = sha256(model_id ‖ prompt_template_version ‖ canonical_json(stage0_input) ‖ decode_params)`；命中直接返回。TTL 绑定仓库索引版本（重索引 → key 变） | **工程级确定** | 缓存存储；索引变更后首次调用仍要打 LLM |
| 2 | **LLM 只输出排列，不输出分数** | 让模型返回 `["repo_a","repo_c","repo_b"]`，禁止返回浮点分。离散低熵输出对 logits 微扰远比浮点数鲁棒 | 高 | 丢失 LLM 的置信度细粒度（但 §1.3a 已把 confidence 改为确定性推导，本就不需要） |
| 3 | **快照回放** | Stage 0 输入、Stage 1 raw prompt/response、分数分解（每项 `w_j·M_j`）全部脱敏后落 `ConvergenceSessionEvent`；提供 replay 模式从事件重建结果、不打网络 | 完全 | 存储；脱敏必须走 `redact_for_ledger` |
| 4 | **稳定 tie-breaking** | `sort(key=lambda r: (-round(r.score, 6), r.repository_id))` | 完全 | — |
| 5 | **聚合内部消除浮点顺序依赖** | `n_eff` 求和前先按 `(score desc, node_id asc)` 排序；或用 `math.fsum` | 完全 | 可忽略 |
| 6 | **decode 参数全固定** | `temperature=0, top_p=1, seed=固定, max_tokens=固定`；不用流式聚合（流式分块边界可能影响解析） | 部分（见 6.1） | — |
| 7 | **模型别名前置解析** | `mimo-v2.5-pro[1m]` 这类别名在调用前解析成具体 model id 并记入 trace | 完全 | — |
| 8 | **LLM 输入顺序固定** | 候选按 Stage 0 分数降序喂入（确定性顺序）。position bias 因此恒定 → 有偏但可复现 | 完全（对幂等） | 引入固定的位置偏置（见 6.3） |
| 9 | **版本绑定** | 每条结果记 `weight_set_version + prompt_hash + model_id + index_version`；四者任一变化 → 结果不可跨版本比较 | — | — |

**第 4 条的两个细节容易做错：**
- **必须先量化再比较。** 直接 `sort(key=-score)` 时，两个数学上相等但浮点表示差 1e-17 的分数会在不同 CPU / 不同求和顺序下给出不同顺序。`round(score, 6)` 把差异吸收掉（分数已归一到 [0,1]，1e-6 无语义）。
- **第二键必须全序且稳定。** 用 `repository_id`（不可变整数），**不要**用 `name`（可改名）或 `path`（可迁移）。

### 6.3 位置偏置：一个必须承认的取舍

LLM listwise 重排存在强位置偏置（Found in the Middle, NAACL 2024）。两条路：

| 方案 | 幂等 | 准确性 | 成本 |
|------|------|--------|------|
| **固定输入顺序（推荐）** | ✅ 完全 | 有恒定偏置（偏袒排在前面的，即 Stage 0 已经看好的） | 1× |
| Permutation self-consistency（m=20 次 shuffle + Kendall-tau 中心排列） | 需固定 shuffle 种子才幂等 | 论文报告 GPT-3.5 提升 7–18%，Mistral 34–52% | **20×** LLM 调用 |

**冷启动建议：固定顺序 + §1.3b 的 rank-swap budget K=3。** 理由：(a) 20× 成本在一个已经因 Stage 1 耗时 34–71s 而卡顿的链路上不可接受；(b) 固定顺序的偏置方向是"信任 Stage 0"，而 Stage 0 恰好是我们本次重点加固的确定性部分——这个偏置与我们的设计意图同向。perm-SC 留作**评估期的质量上界参考**（离线跑一次，看看它比固定顺序好多少，据此决定要不要投入）。

论文还有一个直接可用的发现：**提高 temperature 对 listwise ranking 的多样性采样无效甚至有害**（ρ = -0.078，某任务上显著变差）。这从另一个角度支撑 temperature=0。

来源：Tang et al., *Found in the Middle: Permutation Self-Consistency Improves Listwise Ranking in Large Language Models*, NAACL 2024 — https://aclanthology.org/2024.naacl-long.129/

---

## 7. 评估方案

### 7.1 指标选择：Recall@5 主，MRR@10 次，nDCG 不用

| 指标 | 用不用 | 理由 |
|------|-------|------|
| **Recall@5** | ✅ **主指标** | 每条需求只有 1–3 个正确仓，二元相关性。Recall@k 直接回答"正确仓有没有进候选"——这正是本次事故的失败点（`study-user-status` 曾被 Space 硬过滤完全挡在门外），也与「召回优先于精排」原则对齐 |
| **MRR@10** | ✅ 次指标 | 首位质量。单正确答案时 MRR 就是 1/rank，解释直观 |
| **Top-1 Accuracy** | ✅ 决策指标 | 因为 high confidence → `auto_selected` → 直接进编码，Top-1 错误的代价远高于 Top-5 错误 |
| **误自动选中率** | ✅ **护栏指标** | `count(conf==high AND top1 错误) / count(conf==high)`。这是唯一直接量化"编排被错误自动推进"的指标，**必须设硬上限（建议 ≤ 10%）** |
| nDCG@k | ❌ 不用 | 需要分级相关性标注。只有二元标注时 nDCG 退化为 DCG 的一个单调变换，不提供 Recall/MRR 之外的信息，却增加解释成本和实现面。若将来引入「主仓/协作仓」两级标注，再考虑 nDCG@5（gain: 主仓=3，协作仓=1） |
| MAP | ❌ 不用 | 每 query 相关文档数太少（1–3），MAP 与 MRR 高度相关 |

### 7.2 直面统计能力：10–50 条能做什么、不能做什么

**能做：** 检出大幅退化（Recall@5 掉 20 个百分点以上）、逐例回归对比、机制层断言。
**不能做：** 声称 2–5 个百分点的改进是真实的。

依据（IR 评估的经典结论）：
- Voorhees & Buckley（SIGIR 2002）实测 topic set ≤ 25 时的错误率，结论是错误率比预期大得多。
- Voorhees（SIGIR 2009, *Topic Set Size Redux*）：*"50-topic sets are clearly too small to have confidence in a conclusion when using a measure as unstable as P(10)"*。
- Sakai, *Topic set size design*（Information Retrieval Journal, 2016）：所需 topic 数取决于指标方差，同一组统计要求下不同指标可差数倍；50 topics 的传统做法缺乏原则性依据。
- 另有实证给出：对特定系统对，达到 95% 置信所需样本量范围是 **10 到 722**。

来源：
- https://doi.org/10.1145/564376.564432（Voorhees & Buckley 2002）
- https://link.springer.com/article/10.1007/s10791-015-9273-z（Sakai, Topic set size design）
- https://doi.org/10.3906/elk-1203-20（样本量 10–722 的实证范围）

**工程结论：把 golden set 定位为回归门禁（regression gate），不是优化目标。**

```
门禁规则（CI 里跑）：
  Recall@5      >= baseline            （不允许任何下降）
  Top-1 正确数  >= baseline - 1        （允许 1 例波动）
  误自动选中率  <= 10%
  且必须输出【逐例 diff】：哪几条变好、哪几条变坏、变坏的那条分数分解如何变化
```

**报告 bootstrap 置信区间。** 对 query 做有放回重采样 B=1000 次，报告 Recall@5 的 95% CI。n=20 时 CI 宽度通常在 ±0.15~0.20 —— **把这个宽度直接打印在报告里**，是防止团队对 0.02 的均值波动过度解读的最有效手段。

### 7.3 防过拟合的四道闸

1. **限制自由度。** 权重不超过 6 个，且**只允许在离散网格上取值**：`{0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.55}`。不做连续优化。理由：连续优化在 n=20 上等价于记忆样本。
2. **冻结 hold-out。** golden set 建立时立刻切出 30% 封存，只在里程碑验收开一次。开过之后它就不再是 hold-out（必须记录已开次数）。
3. **fold 稳定性剪枝（最重要的一条规则）。** 5-fold CV 下，若某权重的最优取值在不同 fold 间跳变（如 fold1 最优 0.20、fold3 最优 0.0），**说明该信号无效，直接把权重归 0 并删除该信号**。冷启动下宁可少信号——每多一个无效信号就多一个过拟合入口。
4. **记录调参次数。** 在 n=20 上试 20 组权重，"最优"那组的提升几乎肯定是多重比较噪声。把累计试验次数写进权重版本的元数据里，作为可信度折扣的依据。

### 7.4 机制级断言 > 结果级断言

用首条真实 case（「高三提分专项」）写测试时，**不要只断言最终名次**：

```python
# ❌ 脆弱：任何权重微调都可能让它红/绿，且红了不知道为什么
assert result[0].repo == "onion-learning"

# ✅ 稳健：锁定的是机制，不是结果
assert breakdown["study-app"]["breadth"] <= breakdown["onion-learning"]["breadth"]
assert rank("onion-learning") < rank("study-app")
assert "study-course" in top_k(5) and "study-user-status" in top_k(5)
```
机制级断言抗过拟合，因为它锁定的是"尺寸偏置已被消除"这个因果性质，而不是某组权重下的偶然名次。

### 7.5 权重调参的工程流程

```
1. 冻结 Stage 0 检索（embedding / RRF / Top-50 不动）——变量隔离，只调融合层
2. 建离线 harness：从 ConvergenceSessionEvent 快照回放输入，纯函数算分，零网络
   目标：全量 golden set 跑完 < 5s（这决定了调参能不能进入交互式循环）
3. 坐标上升：一次只动一个权重，在 §7.3-1 的网格上扫
   目标函数：Recall@5，平局用 MRR@10 打破
   扫完全部权重为一轮，跑 2 轮（第 3 轮通常已无变化）
4. 每轮记录 5-fold CV 的 fold 间方差；触发 §7.3-3 剪枝规则的信号立即归零
5. 对每个信号做 ablation（w=0）；关掉后指标不降的信号 → 删除
6. 最终权重写 SystemSetting，元数据附：golden_set_hash / 指标值 / bootstrap CI /
   调参试验次数 / weight_set_version
```

### 7.6 扩样通道（把 golden set 从 20 推到 200+）

项目已有 `WorkItem → TechnicalPlan → PlanVersion → MergeRequest` 的完整追溯链，这是一个**零人工成本的弱标签源**：

```
需求文本（WorkItem.description）  →  最终真实合入的 MR 所属仓库集合
```

历史上每一个成功合入的 MR 都在告诉你"这个需求应该改哪个仓"。建议单独起一个离线脚本挖掘这些对，做人工抽检后并入 golden set。噪声来源：一个需求可能改了多个仓、也可能改错了仓后又改回来——所以只取「有 spec/plan 关联且 MR 已 merged」的样本，并标为 weak label（与人工 golden 分开统计）。

置信度：MEDIUM（数据链路存在是事实；能挖出多少条取决于历史数据量，未实测）。

---

## 8. 落地顺序建议（给 roadmapper）

按「改动风险 × 收益」排序，每一步独立可验证：

| 序 | 改动 | 收益 | 风险 | 依赖 |
|---|------|------|------|------|
| 1 | 建离线评估 harness + golden set（含首条真实 case）+ 快照回放 | 后续所有改动才有标尺 | 低 | 无 |
| 2 | 去掉 `min(score, 1.0)` 截断 + 稳定 tie-breaking + 分数分解落 trace | 修复排序信息销毁；可解释性地基 | 低 | 无 |
| 3 | 聚合公式换成 MaxP + pivoted-size-normalized 对数 breadth | **直接修复 monolith 误选**（本里程碑核心目标） | 中 | 需先统计全仓 N_r 分布定 N̄ |
| 4 | confidence 改为确定性 margin 规则 | **直接修复编排卡死** | 低 | 依赖 3 的分数标定 |
| 5 | 活跃度改连续衰减 + 废弃惩罚改为 A_act 封顶 | 消除混合乘/加模型 | 低 | 需 `last_commit_at` 可得 |
| 6 | 元数据信号入分（domain / stack / team / criticality）+ 重归一化 | 补齐"算了不用"的信号 | 中 | 需别名词典 + embedding 校准 |
| 7 | 分层召回与分组呈现（一套分数 + trust 标注 + delta 迟滞） | 修复 Space 硬过滤漏召回 | 中 | 依赖 2–6 的分数可比性 |
| 8 | Stage 1 有界重排（rank-swap budget + 凸组合 + 降级可见） | 限制 LLM 损害面 | 中 | 依赖 4 |
| 9 | 权重外置 SystemSetting + weight_set_version | 调参不发版 | 低 | 依赖 6 |
| 10 | 弱标签扩样脚本 | 让 golden set 长到有统计意义 | 低 | 依赖 1 |

**关键路径提醒：** 第 1 步不做，后面 9 步全是盲改。第 3 步和第 4 步各自独立修复了本次生产事故的一环（误选 / 卡死），建议优先。

---

## 9. 开放问题与需实测项

| # | 问题 | 影响 | 如何解决 |
|---|------|------|---------|
| O-1 | 全仓 `N_r`（能力树节点数）的真实分布未知 | 直接决定 `b` 和 `N̄` 的合理取值；若分布不倾斜则 §2 的整个尺寸归一化收益有限 | 落地第一步打印 N_r 直方图（p50/p90/p99/max） |
| O-2 | embedding 模型在中文短需求 × facet 值上的余弦分布未测 | 决定 `c_lo/c_hi`，也决定 T2 通道到底可不可用 | §3.2 的两步校准，30 分钟 |
| O-3 | Stage 0 的 dense 余弦是否已在 payload 中可得（现只见 RRF 分） | 若不可得，MaxP 主干只能用 RRF 分，则需换归一化策略（RRF 分 rank1 恒为 max，跨 query 不可比） | 读一次 `_stage0_node_search` 返回结构 |
| O-4 | golden set 中「正确答案在跨组」的样本是否存在 | 无此类样本则 §5 的 `delta` 完全无法校准 | 建集时刻意补 2–3 条 |
| O-5 | `last_commit_at` 对全部 259 仓是否可得、是否新鲜 | 决定活跃度连续化能覆盖多少仓，覆盖不足则退回枚举 | 查一次仓库同步状态 |
| O-6 | Stage 1 的 34–71s 延迟能否压到可接受 | 若压不下来，§6.2 的缓存收益会变成主要价值来源；也可能需要考虑用 cross-encoder 替代 LLM 重排 | 本里程碑 RELY 组已在处理 |

---

## 10. 置信度总表

| 章节 | 置信度 | 依据 |
|------|--------|------|
| §1 融合方式选型（线性 + 级联，否决 LTR） | **HIGH** | Metzler & Croft、RankLib 文档、TREC 小样本实证一致 |
| §1.2 不用 RRF 融合信号层 | **HIGH** | Cormack 原论文对 RRF 适用前提的表述 + 退化排名的逻辑推导 |
| §2 聚合公式形式（MaxP + 尺寸归一 + 对数饱和） | **HIGH** | Dai & Callan、Zhang ECIR'21、Si & Callan ReDDE、BM25 b 参数四条独立证据链 |
| §2.3 具体常数（p=2, b=0.6, n_cap=6, λ=0.25） | **MEDIUM** | 形式有据、数值是判断，需 golden set 校准 |
| §2.4 真实 case 的数值验证 | **LOW-MEDIUM** | N_r 为示意值，未实测（见 O-1） |
| §3.1–3.4 元数据量化（三层 / max 聚合 / 重归一化） | **HIGH** | 逻辑推导 + 与 §2 尺寸偏置同构 |
| §3.2 校准常数 c_lo/c_hi | **LOW** | 模型相关，**必须实测**（见 O-2） |
| §3.5 时间衰减函数形式与 offset/floor 语义 | **HIGH** | Elasticsearch 官方文档 |
| §3.5 半衰期 H=180d | **MEDIUM** | 无 repo routing 领域基准，是判断 |
| §4 权重初值表 | **MEDIUM** | 满足 INV-R2 等结构约束，但具体数值待调 |
| §5 分组呈现（一套分数 + block ranking） | **HIGH** | Arguello vertical selection 系列的直接教训 |
| §5 delta=0.15 迟滞阈值 | **LOW-MEDIUM** | 需 O-4 的样本才能校准 |
| §6 幂等清单 | **HIGH** | Thinking Machines batch invariance + vLLM 文档 + 工程惯例 |
| §6.3 位置偏置取舍 | **HIGH** | Found in the Middle (NAACL 2024) 含 temperature 无效的实证 |
| §7 评估指标选择 | **HIGH** | 二元相关性 + 单正确答案的场景下 Recall/MRR 优于 nDCG 是标准结论 |
| §7.2 小样本统计能力的界限 | **HIGH** | Voorhees & Buckley 2002、Voorhees 2009、Sakai 2016 三篇一致 |
| §7.3 防过拟合四道闸 | **MEDIUM-HIGH** | 标准 ML 实践，未针对本场景实证 |

---

## 参考来源汇总

**多命中聚合与长度归一化**
- Dai & Callan, *Deeper Text Understanding for IR with Contextual Neural Language Modeling*, SIGIR 2019（FirstP/MaxP/SumP）
- Zhang, Yates, Lin et al., *Comparing Score Aggregation Approaches for Document Retrieval with Pretrained Transformers*, ECIR 2021 — https://cs.uwaterloo.ca/~jimmylin/publications/ZhangXinyu_etal_ECIR2021.pdf
- Singhal, Buckley & Mitra, *Pivoted Document Length Normalization*, SIGIR 1996 — https://doi.org/10.1145/3130348.3130365
- Robertson & Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*（B = (1-b) + b·dl/avdl 的 verbosity/scope 推导）— https://www.khoury.northeastern.edu/home/vip/teach/IRcourse/IR_surveys/robertson_foundations.pdf

**资源选择 / 分片选择（与"选哪个仓"同构）**
- Si & Callan, *Relevant Document Distribution Estimation Method for Resource Selection*, SIGIR 2003 — https://www.cs.cmu.edu/~callan/Papers/sigir03-lsi.pdf
- Si & Callan, *Distributed IR With Skewed Database Size Distributions*, 2003 — https://www.cs.cmu.edu/~callan/Papers/dgo03-lsi.pdf
- *Resource Selection for Federated Search on the Web*, arXiv:1609.04556 — https://ar5iv.labs.arxiv.org/html/1609.04556
- Aly, Hiemstra & Demeester, *Taily: Shard Selection Using the Tail of Score Distributions*, SIGIR 2013

**融合与重排**
- Cormack, Clarke & Buettcher, *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*, SIGIR 2009 — https://cormack.uwaterloo.ca/cormacksigir09-rrf
- Metzler & Croft, *Linear feature-based models for information retrieval*, Information Retrieval 10(3), 2007（Coordinate Ascent）
- RankLib 使用文档 — https://sourceforge.net/p/lemur/wiki/RankLib%20How%20to%20use/
- Tang et al., *Found in the Middle: Permutation Self-Consistency Improves Listwise Ranking in LLMs*, NAACL 2024 — https://aclanthology.org/2024.naacl-long.129/

**软件工程域的同类任务**
- Ye, Bunescu & Liu, *Learning to Rank Relevant Files for Bug Reports Using Domain Knowledge*, FSE 2014
- Ye, Bunescu & Liu, *Mapping Bug Reports to Relevant Files: A Ranking Model, a Fine-Grained Benchmark, and Feature Evaluation*, TSE 42(4), 2016 — https://doi.org/10.1109/TSE.2015.2479232

**聚合搜索 / 分组呈现**
- Arguello, Diaz, Callan & Crespo, *Sources of Evidence for Vertical Selection*, SIGIR 2009 — https://841.io/doc/vertical-selection.pdf
- Arguello & Diaz, *Learning to Aggregate Vertical Results into Web Search Results*, CIKM 2011 — https://ils.unc.edu/~jarguell/ArguelloCIKM11Extended.pdf

**评分函数工程实现（公式与参数语义的权威参考）**
- Elasticsearch function_score query（decay functions gauss/exp/linear、field_value_factor 的 log1p/saturation modifier）— https://www.elastic.co/guide/en/elasticsearch/reference/8.19/query-dsl-function-score-query.html

**LLM 幂等**
- Thinking Machines Lab, *Defeating Nondeterminism in LLM Inference* — https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- vLLM Batch Invariance 文档 — https://docs.vllm.ai/en/stable/features/batch_invariance/

**小样本评估的统计能力**
- Voorhees & Buckley, *The Effect of Topic Set Size on Retrieval Experiment Error*, SIGIR 2002 — https://doi.org/10.1145/564376.564432
- Voorhees, *Topic Set Size Redux*, SIGIR 2009
- Sakai, *Topic Set Size Design*, Information Retrieval Journal, 2016 — https://link.springer.com/article/10.1007/s10791-015-9273-z
- *Design of IR experiments: the sufficient topic set size...*（样本量 10–722 的实证范围）— https://doi.org/10.3906/elk-1203-20
