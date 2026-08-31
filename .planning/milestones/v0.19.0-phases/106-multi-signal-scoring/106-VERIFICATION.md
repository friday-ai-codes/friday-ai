---
phase: 106-multi-signal-scoring
verified: 2026-07-30T03:05:00+08:00
status: human_needed
score: 34/38 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  note: "首次验证（此前只有 106-REVIEW.md 的评审+修复记录，无 VERIFICATION.md）"
human_verification:

  - test: "以 superuser 登录管理页 → 打开「仓库路由权重」设置区：确认能读到当前生效配置（默认态有标注）；把 domain 权重调到 0.55（破坏文本主导）与填一个网格外值（如 0.13），确认前端即时内联提示；改回合法值保存，刷新页面确认回读一致；再故意直接构造一次被后端拒绝的保存，确认 400 的 errors 列表逐条展示"
    expected: "读取/修改/保存闭环可用；INV-R2 与网格外取值在前端即时提示；保存成功后回读与后端 GET 一致；400 时逐条错误可见"
    why_human: "RepoRouterWeightSettings.vue（484 行，含预校验/payload 组装/错误渲染分支）零组件测试——MN-05 已按 deferred 挂账（该目录尚无 settings 组件测试与 api mock 夹具）。grep 只能证明代码与接线存在，证明不了交互与渲染。附带需人眼确认 MN-05 记的已知缺陷：DB 里若存着网格外历史值，Select 只显示 placeholder"

  - test: "在生产实例 friday.yc345.tv 执行 `cd server && uv run python manage.py measure_repo_index_stats --activity --write-snapshot`，确认 SystemSetting `repo_router.nr_snapshot` 写入全表 N_r + N̄ 中位数 + generated_at，并把 last_commit_at 覆盖率/新鲜度 p50/p90 与 facets 五维覆盖率回填 106-MEASUREMENTS.md §1 两张占位表"
    expected: "快照写入成功、下一次路由 breadth 走 pivoted 归一（不再 denom_size=1.0 降级）；占位表补齐并带「生产实例」数据环境标注"
    why_human: "需要真实仓库数据的部署实例；本地开发库无真实仓，跑出的全 0 结果按数据环境标注纪律禁止回填。命令口径与写读闭环已在开发库结构性验证通过"

  - test: "在生产实例按 106-MEASUREMENTS.md §2 指引人工确认约 30 组正样本后执行 `calibrate_repo_router_metadata --positives-file ...`，把各 facet 的 c_lo/c_hi 与「c_hi-c_lo < 0.10 → 弃 T2」判定回填 §2 占位表，并经权重端点写入 constants.t2_c_lo/t2_c_hi 与 t2_disabled_facets"
    expected: "O-2 校准数字落表、常数经端点生效（保存即生效，无需发版）；区分度不足的 facet 进 t2_disabled_facets 后 T2 通道确实被禁用"
    why_human: "需真实需求文本 + 已配置 EmbeddingService，且第一步「人工确认正样本」本身是人工判断。管线（采样→分布→建议→判定）已在 --structural 零网络模式下结构性验证通过"

  - test: "生产实例跑若干次真实路由后，查 `repo_router_meta_resolved` 事件的 `dense_hit_ratio` 与 `s_top_source` 分布，确认校准余弦口径（dense_cosine）在生产是否真的会被启用"
    expected: "能给出「生产上 S_top 实际走哪套标尺」的结论，据此判断 s_top_c_lo/s_top_c_hi 两个常数是否值得校准"
    why_human: "BL-01 修复后 S_top 改为 per-query 二选一——只要任一分桶仓拿不到 dense_cos_max 就全仓回退 RRF。dense 查询 limit=STAGE0_NODE_K(50) 且已按候选仓过滤，但生产分桶仓数常在数十量级，覆盖是否满足只能实测。这不是缺陷（CONTEXT O-3 明确允许整链路回退，且口径已进快照与观测），但影响余弦校准常数的优先级"
deferred:

  - truth: "SC-5 的生产实测数字（O-2 余弦校准区间 / O-5 last_commit_at 覆盖率与新鲜度）尚未回填"
    addressed_in: "本里程碑 UAT 人工步骤（106-MEASUREMENTS.md §3 挂账清单第 2/3 项）"
    evidence: "106-CONTEXT.md《Claude's Discretion》锁定：「O-2 校准若开发库缺少真实 facet 数据，允许用结构性样本先定管线并把生产校准记 deferred（同 O-1 纪律）」；deferred 节亦载明「O-1/O-2 生产环境校准数字回填 → 挂账人工步骤」"

  - truth: "MN-05（权重设置组件单测底座 + 网格外历史值的 legacy 选项渲染）"
    addressed_in: "Phase 107 前端改动"
    evidence: "106-REVIEW.md MN-05 fix_note：「建议随 Phase 107 前端改动一并补齐」"

  - truth: "MN-07（golden 负向样本 + dense 覆盖组合多样性 + fixture 数值来源标注）"
    addressed_in: "Phase 107 权重调参前的独立任务"
    evidence: "106-REVIEW.md MN-07 fix_note：「建议在 Phase 107 权重调参前作为独立任务处理」"
warnings:

  - id: W-1
    title: "106-MEASUREMENTS.md §1 的结构性结论与 MJ-04 修复后的代码相矛盾"
    detail: "文档写「0 计数仓保留在 n_r_by_repo 全表中」，但 measure_repo_index_stats.py:429-435 与 test_measure_repo_index_stats.py:297,314-318 已改为只写 node_count > 0 的仓（MJ-04 修复，防「体量 0」仓凭空拿 +0.29 广度加成）。运维照文档理解会误判快照内容"
    files: [".planning/phases/106-multi-signal-scoring/106-MEASUREMENTS.md:73"]

  - id: W-2
    title: "ROADMAP.md 里程碑跟踪表 Phase 106 行仍写 `0/TBD | Not started`"
    detail: "同文件 L105-121 的 8 个 plan 已全部 [x]，跟踪表（L338）未同步；REQUIREMENTS.md Traceability 的 ROUTE-03~06 状态列亦仍为 Pending（该列全项目统一未维护，含已完成的 Phase 105，属既有台账惯例而非本相位遗漏）"
    files: [".planning/ROADMAP.md:338", ".planning/REQUIREMENTS.md:85-88"]
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 106：多信号打分函数重构 —— 验证报告

**相位目标：** 路由排序由一个可拆解、无结构性偏袒、不发版可调的多信号打分函数决定——大而全的单体不再因命中节点多而被系统性高估，业务域/技术栈/团队/关键程度/活跃度从"算了给 LLM 看"变成真正参与打分。
**验证时间：** 2026-07-30T03:05:00+08:00
**验证分支：** `milestone/v0.19.0-plan-trust`（worktree `.claude/worktrees/v0.19-plan-trust`，HEAD `391e7224`）
**结论：** `human_needed` —— **34/38 项 must-have 已核实，0 项失败**；剩余 4 项是「只能人工/生产验证」的项（前端交互 + 三项生产实测/观测），按 honest-verifier 纪律 abstain 而不静默 pass。

**验证方式声明：** 不采信 SUMMARY.md 的自述。全部结论来自（a）实读源码；（b）实跑测试；（c）**独立编写探针脚本重算打分**，其中 gk-001 翻转归因做了 6 组反事实对照 + fixture 与 Phase 105 的逐字段 diff。

---

## 1. ROADMAP Success Criteria 核对

| # | Success Criterion | 状态 | 证据 |
|---|-------------------|------|------|
| SC-1 | gk-001 翻转 + 机制断言 + golden 门禁（Recall@5 不降、误自动选中率 ≤10%） | ✓ VERIFIED | 实跑 `pytest tests/codegraph/test_repo_router_golden.py -q` → **9 passed**（含 `test_gk001_mechanism_rank_flipped` / `..._breadth_not_favor_monolith` / `..._cross_group_repos_in_top5`）。baseline：`recall@5=0.9642857`（与 105 基线 `0.9642857` 相等，未降）、`top1_correct=14/14`（105 为 13）、`mrr@10=1.0`（105 为 0.9642857）、`false_auto_select_rate=0.0 ≤ 0.10`、`weight_set_version=phase106-v2`。翻转归因见 §2 |
| SC-2 | 元数据匹配可见可拆解贡献；缺失剔除并重归一化（"未知"≠"不匹配"）；多值取 max 无 sum/mean | ✓ VERIFIED | 独立探针：全命中 → `{text,breadth,domain,stack,team}` 五键且 `Σbreakdown == score`（严格 `==`，非 `isclose`）；`domain` 缺失 → **该键不出现**、其余重归一化；缺失（0.8698）> 确认不匹配 `score=0.0`（0.7126），"未知"确实不等于"不匹配"。多值：`_resolve_stack` 只用 `max`/`second_max`（`0.8·max+0.2·second`），全模块 grep 无 sum/mean 路径。端到端由 `test_full_meta_breakdown_criticality_and_snapshot` 覆盖（需求未提团队 → `team` 键不出现） |
| SC-3 | 活跃度连续递减；废弃惩罚落在活跃度项内、不再乘性污染总分 | ✓ VERIFIED | 独立探针（`H=180d/offset=14d/floor=0.05`）activity 贡献：0d `0.179104` → 30d `0.168402` → 180d `0.094513` → 365d `0.046355` → 730d `0.011368` → 2000d `0.008955`(floor)，严格递减。废弃对照：`text`/`breadth` 两项**逐字节不变**（0.615672 / 0.073102），只有 `activity` 从 0.179104 压到 0.017910（`min(A, deprecated_cap=0.10)`），且 `Σbreakdown == score` 仍成立 |
| SC-4 | 改权重/常数后下一次路由即生效无需发版；每条结果记 weight_set_version；跨版本不混作同一口径 | ✓ VERIFIED | `test_save_takes_effect_without_restart`：写 SystemSetting → 第二次 `route()` 的 `snapshot.weight_config.weight_set_version == "test-v2"` 且 `snapshot.versions.weight_set_version == "test-v2"`、`domain` 贡献随权重上调变大（无重启）。生效链路 = `get_json_setting` 60s 缓存 + `post_save` receiver 失效。跨版本隔离三处：golden 门禁 `baseline.weight_set_version == WEIGHT_SET_VERSION` 硬守护；replay 旧快照标 `legacy_snapshot=True` + `weight_set_version="phase105-v1"` + diff 首行 `LEGACY_SNAPSHOT_NOTE`；`repo_router_v2.py:944` 把版本写进路由结果留痕 |
| SC-5 | O-2 校准区间 + O-5 覆盖率/新鲜度实测写入配置说明 | ⚠️ 部分（生产数字按锁定决策 deferred） | 106-MEASUREMENTS.md 齐备：O-2/O-5 占位表 + 逐条数据环境标注 + 执行指引 + §3 三项 deferred 挂账清单 + 「回填前按 DEFAULT 初值运行」说明。两条管线的**结构性**验证已完成（`test_measure_repo_index_stats.py` / `test_calibrate_repo_router_metadata.py` 全绿，含 `--structural` 零网络端到端与「无正样本时 c_hi 输出 deferred 不猜分布」）。**生产数字未回填** —— 106-CONTEXT《Claude's Discretion》明示允许，故合规；已列入人工步骤而非计为失败。另见 W-1 文档漂移 |

---

## 2. SC-1 专项：gk-001 翻转是否由公式驱动（独立复核 BL-01 修复后的结论）

用户要求独立复核「翻转由公式而非 fixture 数值/权重调参驱动」。做了两层取证。

### 2.1 fixture 未被调数（与 Phase 105 逐字段 diff）

对 `d56805eb..HEAD` 的 `golden_main.json` 做结构化 diff（14 条 case 全量）：

| 检查项 | 结果 |
|--------|------|
| case id 集合 | 完全相同（14 → 14） |
| `query` 文本 | 0 处变更 |
| `expected_repos` | 0 处变更 |
| `node_hits` 的 score 序列 | **0 处变更** |
| `node_hits` 的 repository_id 序列 | 0 处变更 |
| 新增顶层键 | 仅 `repo_meta` / `constants` / `scored_at` |
| case 级 `weights` 覆盖 | **无任何 case 自带 weights** |
| case 级 `constants` 覆盖 | 仅 `n_bar`（一个值） |

即：判定输入（query / 期望答案 / 检索命中与分数）一个字节没动，也没有把权重塞进 fixture 逐例调参。

### 2.2 翻转对公式各分量的依赖（6 组反事实重算）

用 `aggregate_and_score` 直接重算 gk-001（`n_bar=60`, `scored_at=2026-07-29`）：

| 变体 | s_top 口径 | Top-1 | onion-learning | study-app | 翻转成立？ |
|------|-----------|-------|----------------|-----------|-----------|
| A 原样 fixture | `rrf_s_hat` | onion-learning | 0.8813 | 0.7102（第 4） | ✓ |
| B 剥掉**全部** facet_scores | `rrf_s_hat` | onion-learning | 0.8884 | 0.7480（第 3） | ✓ |
| C 再剥掉 `dense_cos_max` | `rrf_s_hat` | onion-learning | 0.8884 | 0.7480 | ✓（与 B 逐字段相同） |
| D 给全部仓补齐 `dense_cos_max`（强制 dense 口径） | `dense_cosine` | onion-learning | 0.8813 | 0.7454 | ✓ |
| E 去掉全部 `n_r`（关闭 pivoted 归一） | `rrf_s_hat` | onion-learning | 0.8661 | 0.8083 | ✓（但 breadth 反转，见下） |
| F Phase 105 legacy 公式（`repo_meta=None`） | — | **study-app** | 0.7900 | **0.8662** | ✗（复现原事故） |

关键读数：

1. **B/C 逐字段相同** —— gk-001 现在整条查询走 RRF 口径（4 个候选仓只有 2 个有余弦），fixture 里那两个 `dense_cos_max` 对结果**完全无影响**。REVIEW BL-01 提出的「翻转部分依赖 dense 回退抬升」这一隐患确认已消除，且是因为标尺被统一、不是因为改了数。
2. **B/C 证明翻转不依赖元数据信号** —— 把 domain/stack 匹配分全部抹掉，onion-learning 仍以 0.8884 : 0.7480 领先。翻转的根因是公式结构：105 的 `breadth = min(hits-1,5)/5` 独占权重 0.20（study-app 拿满 +0.20、onion-learning 拿 0），106 把广度压进 `w_text·λ` 一项（上限 0.1375）并做 pivoted 归一。
3. **E 是机制断言的反证** —— 关掉 pivoted 归一后 `breadth(study-app)=0.1444 > breadth(onion-learning)=0.0544`，`test_gk001_mechanism_breadth_not_favor_monolith` 会失败。这正说明该断言锁的是 pivoted normalization 这个机制本身，而不是偶然名次。
4. **F 复现原事故** —— legacy 路径下 study-app 0.8662 > onion-learning 0.7900，与 105 baseline 的 Top-1 一致，说明「翻转」是同一输入下换公式的结果。

**结论：SC-1 的翻转由公式驱动，独立复核通过。** 残留的诚实说明：`repo_meta` 里的 `n_r`(620/30/45/25)、`n_bar`(60)、facet 匹配分仍是人工按 ROUTING-RANKING §2.4 设定的（MN-07 已 deferred 挂账），但由变体 B/C/E 可知翻转不建立在这些数值的具体取值上。

---

## 3. PLAN must_haves 全量核对（8 份，33 条 truth）

### 106-01 纯函数打分核心（5/5 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | 命中多但 N_r 大的仓 breadth 贡献不高于命中少但 N_r 小的仓 | ✓ | `_breadth_signal`（`repo_router_scoring.py:326-360`）三步与 §2.3 一致；探针 A：study-app(6 命中/N_r=620) breadth 0.0462 ≤ onion-learning(1 命中/N_r=30) 0.0697；变体 E 反证机制归因 |
| 2 | facet 有值 → 键出现且 Σ==score；缺失 → 键不出现并重归一化，不被系统性压低 | ✓ | 见 SC-2 探针（缺失 0.8698 > 不匹配 0.7126） |
| 3 | 30/180/365/730 天活跃度严格递减；废弃封顶落在 activity 一项内 | ✓ | 见 SC-3 探针 |
| 4 | `repo_meta=None` 时与 Phase 105 逐字段一致（legacy 零破坏） | ✓ | `_score_legacy` 与 105 同构；探针 F 复算出的四仓分数与 105 公式手算一致；`test_legacy_snapshot_replays_without_error_and_flags` 断言旧快照回放 `score/breakdown/confidence` 逐字段等值；golden 全绿 |
| 5 | 关键程度不进加性和，仅同分带 tie-break，值走旁路字段 | ✓ | 探针：`criticality=1.0` 而 `breakdown keys = ['breadth','text']`、`Σ==score`；`_meta_sort_key` 量化桶 tie-break（`:643-647`）；`test_all_candidates_satisfy_score_invariants` 对 golden 全候选用 `==` 严格断言 |

### 106-02 权重外置端点与 loader（4/4 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | superuser PUT 后下一次 `load_weight_config` 返回新值（保存即生效） | ✓ | `test_put_valid_config_persists_and_takes_effect` + `test_save_takes_effect_without_restart`（穿到 `route()`） |
| 2 | 非法配置被 400 拒绝 + 逐条错误；直写 DB 的非法值被 loader 二次校验拦截并回退默认 + warning | ✓ | `test_put_off_grid_weight_rejected` / `test_put_inv_r2_violation_rejected` / `test_put_c_lo_ge_c_hi_rejected`；`test_degraded_invalid_weight_config_row`（直写网格外值 → 路由仍成功且版本回落 `WEIGHT_SET_VERSION`）；`load_weight_config` 的 warning 走 best-effort try/except |
| 3 | GET 无行返回默认 + `is_default=true`，有行返回存储值 | ✓ | `test_get_unconfigured_returns_default_with_flag` / `test_get_configured_returns_stored_values` |
| 4 | 非 superuser PUT 被 403 | ✓ | `test_put_non_superuser_forbidden`；`views.py:1600` `request.user.is_superuser` 检查 |

MJ-03 修复独立复核：`_META_WEIGHT_KEYS` 已含 `activity`（`repo_router_config.py:76`），并补齐 `Σw > 0` / `w_text > 0` / `w_text == max(w)` 三条硬校验（`:130-149`）——REVIEW 复现的两组「合法但致命」权重（全 0、`text=0 + activity=0.55`）现在均被拒。前端 `RepoRouterWeightSettings.vue:162-183` 预校验同口径。

### 106-03 元数据 resolver（4/4 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | 精确/别名命中 1.0、上位类目 0.6，零网络零 DB 可离线 import | ✓ | `_T1_MATCH_SCORE=1.0` / `_T1_PARENT_SCORE=0.6`（`:132-133`），`match_t1` 纯函数；模块顶层无 Django import（Django 依赖全部局部 import，`:478-480` 注释即契约） |
| 2 | `技术栈` 单串多值 split("/") 后 `0.8·max + 0.2·second_max`，不因标签多得分更高 | ✓ | `_resolve_stack`（`:442-466`）只 `sorted(...)[0]/[1]`，无 sum/mean |
| 3 | `未分类`/空/缺失 → None；需求未提团队 → team 返回 None 而非 0.5 | ✓ | `_normalize_facet_value`（`:365-374`）；`team` 走 `allow_t2=False` 且未命中即 `_unavailable()`；端到端 `test_full_meta_breakdown_criticality_and_snapshot` 断言 `"team" not in breakdown` |
| 4 | T2 不可用（未配置/失败/被禁用）静默降级 T1-only，不阻塞路由；每个分数带来源层标注 | ✓ | `_t2_score`（`:420-426`）三重前置收口；`test_degraded_embedding_unconfigured_t1_only` 断言 `"t2" not in layers` 且额外 embedding 次数为 0 |

MJ-02 修复独立复核：`normalize_t2_disabled_facets` 归一（signal 名 + 中文维度名别名表）在 **resolver（`:418`）与校验层（`repo_router_config.py:297`）共用同一函数**，校验层白名单化并在落库前归一 —— 「按文档填中文名永不生效」的静默失效已闭合。

### 106-04 实测 command 与 MEASUREMENTS（3/4 ✓，1 → human）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | 运维在**生产实例**执行 `--write-snapshot` 后 SystemSetting 持有全表 N_r + N̄ 中位数 + generated_at | ? UNCERTAIN → human | 写读闭环、`n_bar` 中位数口径、空库拒写在开发库全部验证（`test_measure_repo_index_stats.py`）；**生产执行是人工步骤，未执行** |
| 2 | `--activity` 输出覆盖率/新鲜度分位数 + facets 五维覆盖率（O-5 执行工具就位），覆盖不足自动走枚举回退 | ✓ | 命令实现 + 覆盖率口径测试；枚举回退在 `_activity_signal_v2` 真值表第 2 行（探针已验） |
| 3 | `calibrate_repo_router_metadata` 按 O-2 产出余弦分布与逐 facet 判定；embedding 未配置时结构性样本仍可跑通 | ✓ | `test_calibrate_repo_router_metadata.py` 全绿：`--structural` 零网络端到端、无正样本时 c_hi 输出「需人工正样本，deferred」不猜分布、`c_hi-c_lo<0.10 → 建议加入 t2_disabled_facets`、正样本文件严格结构校验、EmbeddingService 全失败即退不重试 |
| 4 | 106-MEASUREMENTS.md 沿用数据环境标注纪律；生产回填列 deferred | ✓（附 W-1） | 每条结论带 `数据环境:` 标注；§3 三项挂账。**但 §1 有一句结构性结论已与 MJ-04 修复后的代码矛盾 → W-1** |

### 106-05 前端权重设置区与标签（1/3 ✓，2 → human）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | superuser 在管理页能读/改/存权重与常数；网格外与文本主导破坏前端即时提示 | ? UNCERTAIN → human | 三级接线齐备：`admin/index.vue:10,121` 挂载 → 组件 `:119,262` 调 `getRepoRouterWeightConfig`/`putRepoRouterWeightConfig` → `settings.ts:131,142` 打专用端点 `/settings/repo-router/weight-config/`（不走无校验的通用 updateSetting）；预校验逻辑与后端同口径（已逐条读过 `:158-211`）。**但组件零单测（MN-05 deferred），交互与渲染 grep 不可验** |
| 2 | 新信号 domain/stack/team 显示中文标签；未知 key 回退英文原名 | ✓ | `RoutingDecisionPanel.vue:88-90` 三键中文标签，与后端 `SIGNAL_DOMAIN/STACK/TEAM` 字面对齐；实跑 `pnpm vitest RoutingDecisionPanel.test.ts` → **12 passed**（含未知 key 回退） |
| 3 | 保存后回读与后端 GET 一致；400 的 errors 逐条展示 | ? UNCERTAIN → human | `buildPayload()` 已剥离 `is_default`（后端拒未知顶层键）、`serverErrors` 渲染分支存在；`pnpm type-check` 干净。**无测试覆盖该行为** |

### 106-06 六信号生产接线（5/5 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | 一次路由 = hybrid + 恰一次 dense-only 查询（零额外 embedding）+ 恰一次 FileIndex 聚合，无 N+1；dense 失败/未覆盖不使路由失败 | ✓ | `test_one_route_query_budget_no_nplus1`、`test_degraded_dense_failure_falls_back_rrf`；`_load_repo_meta` 复用 `query_dense`；`_load_latest_commits` 单条 GROUP BY + 60s 缓存（`test_last_commit_aggregation_cached_across_routes`） |
| 2 | 提到域/栈/团队时 breakdown 出现对应键且 Σ==score；缺失则不出现并重归一化（SC-2 端到端） | ✓ | `test_full_meta_breakdown_criticality_and_snapshot` |
| 3 | 保存新配置后下一次 `route()` 按新值；快照 `versions.weight_set_version` + `weight_config` 节记录全量权重/常数/alias_dict_hash | ✓ | `test_save_takes_effect_without_restart`；快照组装 `repo_router_v2.py:264-271`（含 `criticality_anchors`，MJ-01 修复后真进快照） |
| 4 | 快照带 per-候选 repo_meta（n_r/last_commit_at/dense_cos_max/facet_scores/criticality_value）与 scored_at，回放零网络可消费 | ✓ | 断言 `set(repo_meta) == {big, small, bare}`（**全部分桶仓**，BL-02 修复后从「只存候选」改为全量，`:277`）、`scored_at` 为 tz-aware ISO；`scored_at` 是全链路唯一 `datetime.now` 取点（`:244`） |
| 5 | 权重非法 / nr_snapshot 缺失 / embedding 未配置 / dense 异常四种降级下路由全可用 | ✓ | 四条独立用例逐一断言（`test_degraded_*` × 4）+ `test_meta_overall_failure_falls_back_legacy` 整体回退 legacy |

### 106-07 双版本回放（4/4 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | 新快照零网络重算，顺序/分数/breakdown（含新三键）/confidence 逐字段等值；权重与元数据取自快照而非当时 SystemSetting | ✓ | `test_new_snapshot_replay_matches_recorded`、`test_replay_weights_come_from_snapshot_not_environment`、`test_replay_activity_anchor_is_snapshot_scored_at`、`test_verify_detects_tampered_domain_breakdown` |
| 2 | 105 旧快照回放不抛：回退 PHASE105_WEIGHTS + legacy 路径同结果，diff 标注旧版本、不做跨版本换算 | ✓ | `test_legacy_snapshot_replays_without_error_and_flags`（breakdown ⊆ 三信号、`legacy_snapshot=True`、`weight_set_version="phase105-v1"`）、`test_legacy_verify_diff_carries_version_note`（diff 首行 = `LEGACY_SNAPSHOT_NOTE`，新格式 diff 不带该标注）、`test_malformed_weight_config_falls_back_legacy` |
| 3 | 50 hits + 12 候选满配 repo_meta + weight_config 全值 < 64KB | ✓ | `test_new_snapshot_payload_under_64kb_with_full_meta` |
| 4 | replay 模块保持零 I/O import 纯度 | ✓ | `test_replay_module_import_purity` |

BL-02 修复独立复核：`test_snapshot_carries_meta_for_all_bucket_repos`（候选 1 个但 meta 覆盖 3 个分桶仓、`self_contained=True`、verify 通过）+ `test_partial_meta_snapshot_is_reported_as_not_self_contained`（旧口径快照直接判「快照不自包含」并列出 `missing_meta_repo_ids`，不再输出误导性字段差异）+ `test_missing_meta_repo_gets_breadth_bonus_without_trimming`（缺失红利量级证据）。审计工具的误报面已闭合。

### 106-08 golden 门禁与 gk-001（4/4 ✓）

| # | Truth | 状态 | 证据 |
|---|-------|------|------|
| 1 | gk-001 Top-1 == onion-learning；断言锁机制（breadth 对比 + 相对名次 + 跨组两仓进 Top-5） | ✓ | 三条机制断言全绿；§2 反事实复核 |
| 2 | 新 baseline：`phase106-v2` + Recall@5 ≥ 0.9643 + Top-1 14/14 + 误自动选中率 ≤10% | ✓ | baseline 实读：0.9642857 / 14 / 0.0；版本双守护（`test_golden_gate_vs_baseline` 首个 assert + `test_baseline_carries_version_and_ci_fields` 字面绑定 `"phase106-v2"`） |
| 3 | 默认 pytest suite 全绿、全量评估 < 10s 零网络（T2 不参与离线评估） | ✓ | 9 passed in **0.11s**；`test_full_eval_within_time_budget`；fixture 内联 facet 匹配分，`--disable-socket` 全局隔离 |
| 4 | hold-out 6 条仅同形字段扩展，`opened_count` 保持 0，门禁文件零引用 | ✓ | 实读：`opened_count=0`、`opened_log=[]`、6 条 case；逐 case diff 确认 `query`/`expected_repos`/`node_hits` score 与 rid **全部未变**，仅新增 `repo_meta`/`constants`/`scored_at` 与 facets 四维；`rg holdout test_repo_router_golden.py` → 无引用 |

---

## 4. 需求覆盖（ROUTE-03/04/05/06 逐条追溯）

| 需求 | 声明该需求的 PLAN | 描述 | 状态 | 证据 |
|------|------------------|------|------|------|
| ROUTE-03 | 106-01, 106-04, 106-06, 106-08 | 大而全单体不再因命中多被系统性高估 | ✓ SATISFIED | pivoted-size-normalized 对数饱和 breadth 落地并经反事实复核；gk-001 翻转；`test_size_bias_breadth_inverse_tilt_in_production_chain` 在生产链路上守护；MJ-04（`n_r<=0` 视为缺失）与 BL-01（S_top 单一标尺）消除了两种新引入的偏袒 |
| ROUTE-04 | 106-01, 106-03, 106-05, 106-06 | 元数据参与排序打分而非只给 LLM 看 | ✓ SATISFIED | domain/stack/team 三键进 breakdown 且 Σ==score；缺失剔除重归一化；多值 max；关键程度按 CONTEXT 裁决走 tie-break 旁路；前端中文标签 |
| ROUTE-05 | 106-01, 106-04, 106-06 | 活跃度以连续量参与打分 | ✓ SATISFIED | 指数衰减四行真值表全覆盖；废弃改为 activity 项封顶（乘性污染已移除）；无 `last_commit_at` 走枚举回退；`(repository, last_commit_authored_at)` 覆盖索引 + 60s 缓存收敛热路径成本 |
| ROUTE-06 | 106-02, 106-05, 106-06, 106-07 | 运维不发版调权重 | ✓ SATISFIED | 专用端点 + loader 单点校验 + `post_save` 缓存失效 + 前端设置区（交互待人工点）；`weight_set_version` 进结果/快照/baseline，跨版本三处隔离 |

无孤儿需求：REQUIREMENTS.md L111 映射到 Phase 106 的 4 条 ID 与 PLAN frontmatter 声明的 4 条完全一致。

---

## 5. 数据流追踪（Level 4）

| 产物 | 数据变量 | 数据源 | 是否真数据流通 | 状态 |
|------|---------|--------|---------------|------|
| `repo_router_scoring.aggregate_and_score` | `repo_meta` | router `_load_repo_meta` 组装（Qdrant dense + FileIndex 聚合 + facet resolver + N_r 快照） | ✓ 全部四路真取数，四种降级各有独立用例 | ✓ FLOWING |
| `RoutingDecisionPanel` breakdown 展示 | `breakdown` | 后端 `ScoredCandidate.breakdown` → 快照/API | ✓ 键名字面对齐，12 vitest 覆盖 | ✓ FLOWING |
| `RepoRouterWeightSettings` 表单 | `config` | `getRepoRouterWeightConfig()` → 专用端点 → `load_weight_config()` → SystemSetting | ✓ 链路完整（读到写到生效经后端测试串通） | ✓ FLOWING（渲染层待人工确认） |
| `constants.n_bar` | `meta_stats.n_bar` | `aload_nr_snapshot()` → SystemSetting `repo_router.nr_snapshot` ← measure command `--write-snapshot` | ⚠️ 链路通、**生产快照尚未写入** → 当前生产会走 `denom_size=1.0` 降级 | ⚠️ 待生产执行（human #2） |
| `constants.t2_c_lo/t2_c_hi` | resolver `FacetT2Matcher` | weight_config ← O-2 校准 command | ⚠️ 链路通、按初值 0.25/0.55 运行 | ⚠️ 待生产校准（human #3） |
| `s_top_source` | `resolve_s_top_source(rids, repo_meta)` | dense 查询覆盖率 | ✓ router 与 scorer 调同一纯函数、喂同一输入，口径恒等并进快照/观测 | ✓ FLOWING（生产实际取值待观测，human #4） |

---

## 6. 行为抽查与探针执行

| 检查 | 命令 | 结果 | 状态 |
|------|------|------|------|
| golden 门禁 + 机制断言 | `cd server && uv run pytest tests/codegraph/test_repo_router_golden.py -q` | 9 passed in 0.11s | ✓ PASS |
| 相位全量后端回归 | `cd server && uv run pytest tests/codegraph tests/system tests/services/test_repo_router_adapter.py -q` | **440 passed / 20 skipped** in 38.18s | ✓ PASS |
| 迁移完整性 | `cd server && uv run python manage.py makemigrations --check --dry-run` | `No changes detected` | ✓ PASS |
| 新迁移合规 | 实读 `repositories/0040_file_index_last_commit_index.py` | 依赖 `0039`（链正确）、仅一个 `AddIndex(['repository','last_commit_authored_at'], name='idx_repo_last_commit_at')`、无数据迁移/无破坏性操作、与 `FileIndex.Meta.indexes` 同步 | ✓ PASS |
| 前端类型 | `cd web && pnpm type-check` | 干净退出，无输出 | ✓ PASS |
| 前端单测 | `cd web && pnpm vitest run RoutingDecisionPanel.test.ts` | 12 passed | ✓ PASS |
| gk-001 归因反事实探针 | 自编脚本（6 变体重算，见 §2.2） | 翻转在 A/B/C/D/E 全部成立；F 复现原事故 | ✓ PASS |
| SC-2/SC-3 机制探针 | 自编脚本（重归一化 / 递减 / 废弃封顶 / criticality 旁路） | 全部符合，`Σbreakdown == score` 严格相等 | ✓ PASS |
| fixture 调数取证 | 与 `d56805eb` 结构化 diff（main + holdout） | 判定输入 0 变更、无 case 级 weights | ✓ PASS |

**探针说明：** 无项目约定的 `scripts/*/tests/probe-*.sh`（`find` 无匹配），PLAN/SUMMARY 也未声明 probe 脚本，故本相位以 pytest 门禁 + 自编探针替代，未采信任何 SUMMARY 中的 PASS 标记。

---

## 7. 反模式扫描

对 `d56805eb..HEAD` 的 34 个 `server/` + `web/` 改动文件扫描：

| 类别 | 结果 | 严重度 |
|------|------|--------|
| 债务标记 `TBD` / `FIXME` / `XXX` | **0 处** | — |
| `TODO` / `HACK` / `PLACEHOLDER` | **0 处** | — |
| 观测规范（`category`/`component`） | 新增/改动的 `repo_router_*`、两个 management command（经 `**_LOG_KV` 注入 `category=caller`/`component=codegraph`/`initiated_by_user_id=system`）、新端点（started/failed/completed 三事件 + `duration_ms` + `category=caller`）全部合规。`system/views.py` 中缺 `category` 的 8 处均为 HEAD 既存代码，非本相位新增 | ℹ️ INFO |
| 脱敏 | `dense_search_by_name` 异常走 `redact_secrets_in_text`；两个 command 同款；快照 `weight_config`/`repo_meta` 整体过 `redact_for_ledger` 且 `repo_meta` 不存 facet 原文 | ✓ |
| 观测反噬 | 全部埋点包 try/except pass；`route()` 对 config/meta 组装整体 try/except 回退 legacy | ✓ |
| 文档漂移 | 106-MEASUREMENTS.md §1 一句结论与 MJ-04 后的代码矛盾 | ⚠️ W-1 |
| 台账漂移 | ROADMAP 跟踪表 Phase 106 行仍 `Not started` | ⚠️ W-2 |

---

## 8. 评审修复记录复核

106-REVIEW.md 声明 16 修 / 2 deferred。抽查独立复核（不采信 fix_note）：

| Finding | 声明 | 独立复核 |
|---------|------|---------|
| BL-01 S_top 混用标尺 | fixed `f2b54a08` | ✓ `resolve_s_top_source` 为 per-query 纯函数（`scoring.py:282-302`），router（`v2.py:636`）与 scorer（`:585`）调同一函数、喂同一输入；口径进 `ScoredCandidate.s_top_source` / 快照 `stage0.s_top_source` / 观测事件。§2.2 变体 B/C 逐字段相同，证明 gk-001 已不受 dense 回退影响 |
| BL-02 快照 repo_meta 只存候选 | fixed `7ce74d21` | ✓ `:277` 改 `dict(repo_meta)` 全量；三条自包含性用例 + 缺失红利量级用例 |
| MJ-01 锚点外置形同虚设 | fixed `289a02fa` | ✓ `_criticality_value(meta, anchors)` 收参（`:431-441`）、`aggregate_and_score` 新增 `criticality_anchors`、router 注入并进快照、replay 从快照读 |
| MJ-02 t2_disabled_facets 取值空间不一致 | fixed `b6529577` | ✓ `normalize_t2_disabled_facets` 被 resolver 与校验层**共用**；未知值 400 拒绝；UI 改多选 |
| MJ-03 文本主导未真正守住 | fixed `148fac9f` | ✓ `activity` 纳入分子 + 三条硬校验；前端同口径 |
| MJ-04 `n_r=0` 反获加成 | fixed `5a6b0593` | ✓ 两端同修：command 只写 `node_count > 0`、scorer `float(n_r) > 0.0`（`:352`）。**但 MEASUREMENTS 未同步 → W-1** |
| MJ-05 last_commit 热路径全扫 | fixed `639f7ddb` | ✓ 迁移 0040 覆盖索引 + 60s 缓存（键含候选仓集合）+ 缓存用例 |
| MJ-06 T2 冷启动串行 | fixed `639f7ddb` | ✓ `_load_repo_meta:603-604` 真调 `warm_facet_vectors`（死代码已激活）+ `STAGE0_T2_EMBED_BUDGET` 硬上限 + 用例 |
| MN-01~04, MN-06, MN-08, IN-01, IN-02 | fixed | ✓ 逐处抽查通过（`margin = max(0.0, s1-s2)` 与 docstring 重验条件、`_CONSTANT_RULES` 余弦域 [0,1] + 最小带宽 0.05、脏 rid 逐条过滤、短 ASCII canonical 门槛、stack 口径 UI 说明） |
| MN-05, MN-07 | deferred | ⚠️ 确认仍未修，且直接构成本报告的 human #1 与 SC-1 的诚实说明；deferral 理由与去向（Phase 107）已在 REVIEW 记录 |

---

## 9. 结论

**没有发现 BLOCKER，没有 must-have 失败。** 相位目标的三条硬承诺——「结构性偏袒被消除」「元数据真正入分」「不发版可调」——在代码里成立，且经独立重算与反事实对照排除了「靠 fixture/权重调参装出来」的可能。评审的 2 BLOCKER + 6 MAJOR 修复我逐条复核确认落地，其中 BL-01 的修复反而让 gk-001 的翻转幅度更大、归因更干净。

判 `human_needed` 而非 `passed`，是因为下列 4 项按 honest-verifier 纪律必须 abstain、不允许静默算通过：

1. **前端权重设置区的交互与渲染**（106-05 truth 1/3）—— 组件 484 行零单测（MN-05 deferred），接线与预校验逻辑可读、行为不可验。
2. **生产 N_r/N̄ 快照写入**（106-04 truth 1）—— 未执行；这项没做之前，生产的 breadth 会一直走 `denom_size=1.0` 降级，ROUTE-03 的 pivoted 归一在生产上尚未真正启用。这是 4 项里对目标影响最大的一项。
3. **O-2 余弦校准数字回填**（SC-5）—— 管线就绪、按初值运行，锁定决策允许 deferred。
4. **生产 dense 覆盖率 → S_top 实际口径**（观测项）—— BL-01 修复把回退提为 per-query 后，生产是否还会走校准余弦口径需实测才知道；这不是缺陷，但决定 `s_top_c_lo/c_hi` 是否值得校准。

另有两条 WARNING（W-1 文档与代码矛盾、W-2 台账未同步），均为一行级修订，不阻塞进入 Phase 107。

---

_Verified: 2026-07-30T03:05:00+08:00_
_Verifier: gsd-verifier（goal-backward，adversarial stance）_
