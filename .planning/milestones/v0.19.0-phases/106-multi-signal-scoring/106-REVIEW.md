---
phase: 106-multi-signal-scoring
reviewed: 2026-07-30T01:32:00Z
depth: deep
diff_base: d56805eb
files_reviewed: 17
files_reviewed_list:
  - server/codegraph/services/repo_router_scoring.py
  - server/codegraph/services/repo_router_config.py
  - server/codegraph/services/repo_router_metadata.py
  - server/codegraph/services/repo_router_v2.py
  - server/codegraph/services/repo_router_replay.py
  - server/codegraph/services/repo_router_eval.py
  - server/codegraph/management/commands/calibrate_repo_router_metadata.py
  - server/codegraph/management/commands/measure_repo_index_stats.py
  - server/services/qdrant_service.py
  - server/services/process_runtime/builtin_processes.py
  - server/system/models.py
  - server/system/urls.py
  - server/system/views.py
  - web/src/api/settings.ts
  - web/src/components/settings/RepoRouterWeightSettings.vue
  - web/src/components/chat/RoutingDecisionPanel.vue
  - web/src/pages/admin/index.vue
status: findings
fix_status: fixed_with_deferrals
fixed_at: 2026-07-30T02:45:00+08:00
fixed: 16
deferred: 2
fix_regression: "cd server && uv run pytest tests/codegraph tests/system tests/services/test_repo_router_adapter.py -q → 440 passed / 20 skipped；web pnpm vitest RoutingDecisionPanel.test.ts → 12 passed；pnpm type-check 干净"
tests_run: "server/tests/codegraph/{test_repo_router_scoring,test_repo_router_config,test_repo_router_metadata,test_repo_router_replay,test_repo_router_v2_meta,test_repo_router_golden}.py + server/tests/system/test_repo_router_weight_config.py → 187 passed"
findings:
  blocker: 2
  major: 6
  minor: 8
  info: 2
  total: 18
findings_list:
  - id: BL-01
    severity: BLOCKER
    title: "S_top 在同一次查询内混用两套不可比标尺，且方向反了（dense 未覆盖的仓反而拿高分）"
    files:
      - "server/codegraph/services/repo_router_scoring.py:268-283"
      - "server/codegraph/services/repo_router_v2.py:470-506"
    fix: "把 dense 回退改为整条链路级（per-query）决策而非 per-repo：本次查询 dense 覆盖不全时全仓统一走 RRF s_hat 口径；或对未覆盖仓补一次 point-level 余弦查询。"
    status: fixed
    fix_commit: f2b54a08
    fix_note: "resolve_s_top_source 纯函数做 per-query 二选一（全仓有余弦→校准余弦，任一缺失→全仓 RRF）；口径进 ScoredCandidate.s_top_source / 快照 stage0.s_top_source / 观测事件。版本 bump phase106-v2 + baseline 重建同提交。gk-001 翻转在修正标尺后仍成立（详见文末修复记录）。"
  - id: BL-02
    severity: BLOCKER
    title: "快照 repo_meta 只存候选仓导致回放漂移，verify_snapshot_replay 位置比对必然误报（已复现）"
    files:
      - "server/codegraph/services/repo_router_v2.py:254-259"
      - "server/codegraph/services/repo_router_replay.py:190-245"
      - "server/codegraph/services/repo_router_replay.py:270-301"
    fix: "快照存全部分桶仓的 repo_meta（字段本身很小，体积护栏应作用于 node_hits 而非 repo_meta），或回放时只对快照内有 meta 的仓打分。"
    status: fixed
    fix_commit: 7ce74d21
    fix_note: "快照改存全部分桶仓 meta；回放对旧快照裁剪缺 meta 的仓并置 self_contained=False + missing_meta_repo_ids，verify 直接判「快照不自包含」而非报字段差异；位次不一致时附重算完整名次。"
  - id: MJ-01
    severity: MAJOR
    title: "criticality_anchors 外置形同虚设——scorer 硬编默认锚点表，配置改了不生效，快照也不携带"
    files:
      - "server/codegraph/services/repo_router_scoring.py:371-377"
      - "server/codegraph/services/repo_router_scoring.py:553"
    fix: "_criticality_value 接收 anchors 参数（由 aggregate_and_score 从配置注入），并把 criticality_anchors 写进快照 weight_config。"
    status: fixed
    fix_commit: 289a02fa
    fix_note: "aggregate_and_score 新增 criticality_anchors 参数（merge 语义容错）；router 从生效配置注入并写快照，replay 从快照读取。"
  - id: MJ-02
    severity: MAJOR
    title: "t2_disabled_facets 取值空间前后不一致：resolver 比英文 signal 名，校准命令与 UI 给中文 facet 维度名"
    files:
      - "server/codegraph/services/repo_router_metadata.py:351-364"
      - "server/codegraph/management/commands/calibrate_repo_router_metadata.py:88-90"
      - "web/src/components/settings/RepoRouterWeightSettings.vue:365-376"
    fix: "统一为一套枚举（建议 domain/stack）：resolver 同时接受中文维度名映射，校验层做枚举白名单，UI 改成多选而非自由文本。"
    status: fixed
    fix_commit: b6529577
    fix_note: "新增 normalize_t2_disabled_facets（signal 名 + 中文维度名别名表）；校验层白名单化并在落库前归一，resolver 复用同一归一函数，校准命令输出「应写入」列 + t2_disabled_facets_suggested，UI 改多选。"
  - id: MJ-03
    severity: MAJOR
    title: "权重校验没有真正保证「文本主导」：INV-R2 分子漏 activity，且 text=0 / 全 0 权重可通过"
    files:
      - "server/codegraph/services/repo_router_config.py:66-127"
    fix: "把 activity 纳入元数据权重和；补 text 权重必须 > 0 且为最大项、Σw > 0 的硬校验。"
    status: fixed
    fix_commit: 148fac9f
    fix_note: "_META_WEIGHT_KEYS 纳入 activity；新增 Σw>0 / w_text>0 / w_text==max(w) 三条硬校验；前端预校验同口径。附带修正 test_save_takes_effect_without_restart 的用例权重（旧值在新口径下违反 INV-R2）。"
  - id: MJ-04
    severity: MAJOR
    title: "N_r 快照写入 node_count=0 的仓，scorer 把 n_r=0 当有效值 → breadth 反而 +0.29 加成"
    files:
      - "server/codegraph/management/commands/measure_repo_index_stats.py:426-433"
      - "server/codegraph/services/repo_router_scoring.py:306-312"
    fix: "写入端过滤 node_count<=0；同时 scorer 把 n_r<=0 视为缺失（denom_size=1.0）。"
    status: fixed
    fix_commit: 5a6b0593
    fix_note: "两端同时修（防呆）：measure command 只写 node_count>0，scorer 把 n_r<=0（含负值）按缺失处理。"
  - id: MJ-05
    severity: MAJOR
    title: "last_commit 聚合在路由热路径每次全量扫 FileIndex，无覆盖索引"
    files:
      - "server/codegraph/services/repo_router_v2.py:407-438"
      - "server/codegraph/services/repo_router_v2.py:509"
    fix: "与 N_r 同款离线快照，或把 last_commit_at 反范式化到 Repository 上由同步流程维护；至少加 (repository, last_commit_authored_at) 索引 + 短 TTL 缓存。"
    status: fixed
    fix_commit: 639f7ddb
    fix_note: "采纳方案 (c)：新增覆盖索引 idx_repo_last_commit_at（repositories 迁移 0040）+ 60s 进程内缓存（key 含候选仓集合）；离线快照/反范式化留作后续优化。"
  - id: MJ-06
    severity: MAJOR
    title: "T2 冷启动在热路径逐值串行 embedding；批量预热函数 warm_facet_vectors 无任何生产调用方"
    files:
      - "server/codegraph/services/repo_router_metadata.py:481-518"
      - "server/codegraph/services/repo_router_metadata.py:567-624"
    fix: "在 _load_repo_meta 里先收集本次全部待匹配 facet 值调一次 warm_facet_vectors，再逐值走缓存；或给单次路由的 T2 embedding 次数设硬上限。"
    status: fixed
    fix_commit: 639f7ddb
    fix_note: "两条都做：_load_repo_meta 接入批量预热（_collect_t2_facet_values 收齐 domain + 拆分后的 stack 值）；FacetT2Matcher 增加单实例 embed_budget（STAGE0_T2_EMBED_BUDGET=16），超限静默降级 T1-only。"
  - id: MN-01
    severity: MINOR
    title: "_load_latest_commits 捕获 ValidationError 后返回空 dict，一条脏 payload 让全部候选活跃度退化"
    files:
      - "server/codegraph/services/repo_router_v2.py:427-434"
    fix: "先用 uuid.UUID() 逐 rid 过滤出合法值再查询，脏值只影响自身。"
    status: fixed
    fix_commit: 639f7ddb
  - id: MN-02
    severity: MINOR
    title: "dense_search_by_name 日志缺 category/component，异常文本未过 redact_secrets_in_text"
    files:
      - "server/services/qdrant_service.py:1477-1486"
    fix: "补 category=\"sampling\" / component=\"qdrant\"，error 走 redact_secrets_in_text。"
    status: fixed
    fix_commit: a9e15a31
  - id: MN-03
    severity: MINOR
    title: "affine clip 校准区间常数无值域校验（可写 -5 / 100），只校验 lo<hi"
    files:
      - "server/codegraph/services/repo_router_config.py:132-142"
    fix: "给 s_top_c_lo/hi、t2_c_lo/hi 加 [0,1] 范围规则（余弦域），并要求 hi-lo >= 0.05。"
    status: fixed
    fix_commit: a9e15a31
  - id: MN-04
    severity: MINOR
    title: "criticality tie-break 使 sorted_scores 不再单调降序，derive_confidence 的 margin 可为负"
    files:
      - "server/codegraph/services/repo_router_scoring.py:557-570"
      - "server/codegraph/services/repo_router_scoring.py:574-595"
    fix: "derive_confidence 内用 max(0.0, s1-s2) 或显式断言输入降序，并在 docstring 记录 tie-break 后的语义。"
    status: fixed
    fix_commit: a9e15a31
    fix_note: "margin = max(0.0, s1-s2) + docstring 记录「θ_margin(0.08) > crit_band(0.03) 时首位仍为全局最大」的推理与重验条件。"
  - id: MN-05
    severity: MINOR
    title: "RepoRouterWeightSettings.vue（423 行，含预校验与 payload 组装）零单测；网格外历史值使 Select 显示空占位"
    files:
      - "web/src/components/settings/RepoRouterWeightSettings.vue:120-210"
    fix: "补组件单测（INV-R2 预校验拦截 / 400 errors 渲染 / payload 不含 is_default）；非网格值渲染成一次性 legacy 选项并提示。"
    status: deferred
    fix_note: "deferred：组件测试底座成本高于本轮修复预算（该目录尚无 settings 组件测试与 api mock 夹具，需先搭 harness）；网格外历史值的 legacy 选项渲染属 UI 增强。本轮已同步该组件的预校验口径（MJ-03）与 T2 多选改造（MJ-02），并经 pnpm type-check + eslint 验证。建议随 Phase 107 前端改动一并补齐。"
  - id: MN-06
    severity: MINOR
    title: "权重配置写入事件缺 duration_ms；GET 对任意已认证用户开放内部打分配置"
    files:
      - "server/system/views.py:1573-1631"
    fix: "写入日志补 duration_ms（started/completed 成对）；按需把 GET 也收到 superuser 或明确记录该口径为有意放开。"
    status: fixed
    fix_commit: a9e15a31
    fix_note: "补 started/failed/completed 三事件与 duration_ms（校验失败的 400 也留痕）；GET 保持任意已认证用户可读并在 docstring 写明「有意放开」的理由（返回体无凭证、分数分解可解释需要）。"
  - id: MN-07
    severity: MINOR
    title: "golden baseline 已达 Top-1 14/14、MRR@10=1.0，门禁区分度饱和；fixture 的 dense_cos_max/facet_scores 由人工按期望名次填写"
    files:
      - "server/tests/codegraph/fixtures/repo_router_golden/golden_main.json"
      - "server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json"
    fix: "补「新公式应当判错」的负向样本与更多 dense 覆盖组合；把 fixture 数值来源（人工设定 vs 实测）标进 case 注释。"
    status: deferred
    fix_note: "deferred：新增负向样本要新造 case 并重建 baseline，属 golden set 设计工作（与 MN-07 同源的 hold-out 纪律一并评估更稳妥），不在「修评审问题」范围内。本轮 BL-01 已顺带消除「gk-001 翻转部分依赖 dense 回退抬升」这一具体隐患（修正标尺后翻转由公式自然成立，见文末修复记录）。建议在 Phase 107 权重调参前作为独立任务处理。"
  - id: MN-08
    severity: MINOR
    title: "T1 单字符 canonical（\"C\"）在 ASCII 词边界下会命中任意独立 c token，误报风险"
    files:
      - "server/codegraph/services/repo_router_metadata.py:143-155"
      - "server/codegraph/services/repo_router_metadata.py:112"
    fix: "给单字符/两字符 ASCII canonical 设最小长度门槛或要求上下文（如 \"C 语言\"/\"C/C++\"）。"
    status: fixed
    fix_commit: a9e15a31
    fix_note: "长度 < 3 的 ASCII canonical 不再允许裸值命中，只能经别名/上位类目；给 C 补 c语言 / c 语言 / c/c++，给 Go 补 go 语言 / go语言。"
  - id: IN-01
    severity: INFO
    title: "技术栈单值精确命中上限 0.8，与 domain/team 的 1.0 不同尺度（多标签仓仍有小幅优势）"
    files:
      - "server/codegraph/services/repo_router_metadata.py:398-404"
    fix: "属 CONTEXT 锁定取舍；建议在 UI 文案/文档说明 stack 满分口径，避免运维误判权重。"
    status: fixed
    fix_commit: b6529577
    fix_note: "设置页权重区补一段说明：技术栈口径 0.8·max + 0.2·second_max，单值上限 0.8、命中两个技术栈才达 1.0。"
  - id: IN-02
    severity: INFO
    title: "warm_facet_vectors 调用 matcher 私有方法 _cache_get；zip(pending, vectors) 长度不等时静默截断"
    files:
      - "server/codegraph/services/repo_router_metadata.py:591"
      - "server/codegraph/services/repo_router_metadata.py:604"
    fix: "把 _cache_get 提为公开方法；批量返回长度不符时记一条 sampling warning。"
    status: fixed
    fix_commit: 639f7ddb
---

# Phase 106 代码评审报告（多信号打分函数重构）

**评审范围：** `d56805eb..HEAD` 中 `server/` 与 `web/` 的源码改动（32 个文件，+6596/−295；`.planning` 文档不在范围）
**评审深度：** deep（跨文件调用链：scorer ↔ config loader ↔ resolver ↔ router ↔ replay ↔ golden harness ↔ 前端）
**测试基线：** 本 phase 相关 187 条后端测试全绿；下述问题均为测试未覆盖的路径，不是测试失败。
**结论：** `status: findings` —— 2 个 BLOCKER、6 个 MAJOR。公式骨架（MaxP + pivoted breadth、指数衰减、多值 max、缺失重归一化、C_crit tie-break）与 research §2/§3/§4 一致，INV-R1/R3/R4 按构造成立；但 **S_top 的 dense 回退口径**与 **快照自包含性** 两处把新的结构性偏袒和回放不可信重新引了回来，需修复后再进 Phase 107。

## 摘要（先看这里）

做对的部分：加性可拆解结构干净（`breakdown` 两键拆分让 INV-R3 与 breadth 机制断言同时成立，前端零结构改动）；纯函数层零 I/O、时间锚点参数注入、`math.fsum` + 量化 tie-break 的确定性纪律执行到位；降级路径（dense 失败 / N_r 缺失 / embedding 未配置 / 权重非法）全部 best-effort 且不反噬路由；权重端点复用 `SystemSetting` + `settings_service` 缓存失效，`is_superuser` 校验与既有 `ClaudeCodeConfigView` 口径一致。

需要修的部分集中在三类：

1. **标尺一致性**（BL-01）：同一次查询里，dense top-50 覆盖到的仓用「校准余弦」，没覆盖到的仓用「query-local RRF 比值」。后者恒偏高，而没被 dense 覆盖恰恰意味着 dense 相似度低——信号方向是反的。这与 ROUTE-03「消除结构性偏袒」直接冲突。
2. **回放可信度**（BL-02）：快照只存 top-12 候选的 `repo_meta`，回放时非候选仓因缺 meta 分数被大幅抬高并挤进比对窗口，`verify_snapshot_replay` 会稳定误报。已用可运行脚本复现。
3. **「外置」没有真外置 / 校验没有真守住**（MJ-01/02/03）：锚点表改了不生效、`t2_disabled_facets` 按文档填写永不生效、权重校验允许 `text=0` 甚至全 0。

---

## BLOCKER

### BL-01：S_top 在同一次查询内混用两套不可比标尺，且方向反了

**文件：** `server/codegraph/services/repo_router_scoring.py:268-283`、`server/codegraph/services/repo_router_v2.py:470-506`

`_s_top_signal` 的回退是 per-repo 的：

```268:283:server/codegraph/services/repo_router_scoring.py
def _s_top_signal(
    meta: dict[str, Any],
    bucket_s_hats: list[float],
    consts: dict[str, Any],
) -> float:
    """MaxP 主干：dense 余弦 affine clip 校准；缺失回退桶内 max s_hat。"""
    cos = meta.get("dense_cos_max")
    if _is_number(cos):
        c_lo = consts["s_top_c_lo"]
        c_hi = consts["s_top_c_hi"]
        return _clip01((float(cos) - c_lo) / (c_hi - c_lo))
    return max(bucket_s_hats) if bucket_s_hats else 0.0
```

而 `_load_repo_meta` 的 dense 查询 `limit=STAGE0_NODE_K`（50）只覆盖 dense top-50 的点，候选仓可以有几十个（`rids = sorted(buckets)`，`repo_router_v2.py:468`），dense 槽位被少数仓占满时其余仓拿不到 `dense_cos_max`。

两套标尺的量级完全不同：
- 校准余弦：`(cos-0.25)/0.30`，真实余弦 0.30 → **0.167**，0.52 → 0.90；
- RRF query-local 比值：rank-1 恒为 1.0，rank-2 常在 0.9 以上。

实测证据（用本 phase 的公式与默认常数跑）：某仓 `dense_cos_max=0.30` 时 text 分项 0.4583 对应 S_top≈0.167；同一批次里没有 dense 覆盖的仓 s_hat=0.95 → S_top=0.95，text 贡献 0.7125。**S_top 差 5.7 倍，而 w_text·(1-λ)/D ≈ 0.43，折算成最终分差 ≈ 0.35** —— 远超全部元数据信号的贡献上限（0.28/0.95≈0.29）。

更糟的是方向：没进 dense top-50 的仓恰恰是 dense 相似度低的仓（典型是靠 sparse 关键词命中挤进 RRF 的仓），它们因此拿到最高的 S_top。这就是把「大而全的仓因命中多被高估」换成了「dense 弱的仓因未被覆盖被高估」，同一类病理。

golden fixture 自身就编码了这个形态：`gk-001` 只给 `onion-learning`(0.62) 与 `study-app`(0.52) 赋了 `dense_cos_max`，`study-course` / `study-user-status` 省略 → 走回退。实测 `study-course` 的 S_top≈0.79（无任何 dense 证据）并以 0.8232 超过 `study-app` 的 0.7454，`test_gk001_cross_group_repos_in_top5` 的通过部分依赖这个回退抬升，而非「广度偏置被消除」这个被断言的机制。

106-CONTEXT 的原文是「若实现后延迟/成本不可接受，**回退** RRF 分 query-local max 归一」——这是一个**整链路二选一**的取舍，不是 per-repo 混用。当前实现偏离了该裁决。

**修复建议：** 把回退提升为 per-query 决策——`_load_repo_meta` 已经算出 `dense_hit_ratio`，覆盖率低于阈值（或存在任一候选缺失）时对**全部**候选一律不传 `dense_cos_max`，让整条链路统一走 RRF s_hat 口径；覆盖完整时才启用余弦口径。并在 breakdown/trace 里记录本次采用的 `s_top_source`，回放与 golden 才能区分两种口径。若要保留余弦口径，则需为缺失仓补一次按 point id 的余弦读取（`retrieve` + `with_vectors`）。

### BL-02：快照 `repo_meta` 只存候选仓 → 回放分数漂移、verify 稳定误报（已复现）

**文件：** `server/codegraph/services/repo_router_v2.py:254-259`、`server/codegraph/services/repo_router_replay.py:190-245`、`:270-301`

录制侧只保留候选仓的 meta（体积护栏，106-06 计划所要求）：

```254:259:server/codegraph/services/repo_router_v2.py
            snapshot_repo_meta: dict[str, Any] | None = {
                c["repo_id"]: repo_meta[c["repo_id"]]
                for c in stage0_candidates
                if c["repo_id"] in repo_meta
            }
```

但回放侧用**全部** `node_hits` 重算（`replay_route_from_snapshot` 把 `stage0.node_hits` 全量喂给 `aggregate_and_score`），非候选仓拿不到 meta 于是同时获得三重「缺失红利」：`dense_cos_max` 缺失 → S_top 回退高分（见 BL-01）、`n_r` 缺失 → breadth denom=1.0、facet 全缺 → 重归一化只剩 text。而 `verify_snapshot_replay` 是**按位置** `zip(recorded, recomputed)` 比对的，所以被抬高的非候选仓一定会进入比对窗口。

`replay_route_from_snapshot` 的 docstring 声称「非候选仓不参与比对」——这个前提不成立。

可复现脚本（本次评审实际执行，零网络）：录制时 A/B 都有 meta（A cos 0.30、B cos 0.28，n_r 均 600，n_bar=60），快照只留 top-1 候选 A 的 meta：

```
录制时排序: [('A', 0.1437), ('B', 0.1084)]
回放结果:   [{'repo_id': 'B', 'score': 0.8492, ..., 'confidence': 'high'}]
verify:     (False, "[0] repo_id: recorded='A' recomputed='B'")
```

B 的分数从 0.1084 膨胀到 0.8492、confidence 从 low 变 high、Top-1 直接翻转。触发条件是「top-50 node_hits 里的仓数 > STAGE0_REPO_K(12)」——在 259 个仓的生产库里是常态，不是边角情况。这使 ROUTE-09「快照回放零网络同结果」在真实数据下失效，而 replay 正是审计与门禁工具，误报会直接把该工具的信任度打掉。

**修复建议：** 体积护栏应该作用在 `node_hits`（每条含 path 等长字段）上，而不是 `repo_meta`（每仓 5 个短字段，50 个仓也就几 KB）——把全部分桶仓的 meta 存进快照。若坚持只存候选，回放必须与之对称：只对快照 `repo_meta` 里存在的仓打分（其余 hits 丢弃），并在 `ReplayResult` 上标注该裁剪。另外建议给 `verify_snapshot_replay` 加一条前置断言：`set(repo_meta) ⊇ {分桶仓}`，否则直接判「快照不自包含」而不是报字段差异。

---

## MAJOR

### MJ-01：`criticality_anchors` 外置形同虚设

**文件：** `server/codegraph/services/repo_router_scoring.py:371-377`（调用点 `:553`）

```371:377:server/codegraph/services/repo_router_scoring.py
def _criticality_value(meta: dict[str, Any]) -> float | None:
    """关键程度锚点映射：缺失/枚举外 → None。**不进 breakdown**。"""
    raw = meta.get("criticality_value")
    if not isinstance(raw, str):
        return None
    anchors: dict[str, float] = DEFAULT_WEIGHT_CONFIG["criticality_anchors"]
    return anchors.get(raw)
```

函数签名不接受配置，锚点表恒取 `DEFAULT_WEIGHT_CONFIG`。而 `validate_weight_config` 明确校验并落库 `criticality_anchors`（`repo_router_config.py:226-234`）、端点会回显、前端 `buildPayload` 原样带回——运维改了锚点，打分行为**完全不变**。这与 ROUTE-06「全部权重与常数（…CRITICALITY 表等）落 SystemSetting」相违，属于「配置项存在但是死的」，比没有这个配置更危险（运维会以为改生效了）。

顺带的自包含性缺口：快照 `weight_config` 只写 `weights/constants/weight_set_version/alias_dict_hash/embedding_model_id`（`repo_router_v2.py:245-251`），不含锚点表；一旦锚点变成可配置，回放的 tie-break 顺序就不可复现。

**修复：** `aggregate_and_score` 增加 `criticality_anchors` 参数并透传给 `_criticality_value`；router 从 config 注入；快照 `weight_config` 补该键；replay 从快照读取。

### MJ-02：`t2_disabled_facets` 取值空间前后不一致，O-2「放弃 T2」条款实际失效

**文件：** `server/codegraph/services/repo_router_metadata.py:351-364`、`calibrate_repo_router_metadata.py:88-90`、`RepoRouterWeightSettings.vue:365-376`

resolver 用**英文 signal 名**做判定：

```358:364:server/codegraph/services/repo_router_metadata.py
    async def _t2_score(signal: str, value: str) -> float | None:
        """T2 通道前置条件收口：matcher/向量可用且 facet 未被校准禁用。"""
        if t2_matcher is None or not query_embedding:
            return None
        if signal in disabled:
            return None
        return await t2_matcher.match(query_embedding, value)
```

`signal` 只可能是 `domain` / `stack`（`team` 走 `allow_t2=False`）。但：
- 校准命令的报告以**中文 facet 维度名**（`业务线/产品线`、`技术栈`、`服务对象`…）为行键，判定文案直接写「建议加入 `t2_disabled_facets`（区分度不足）」；
- 前端输入框 placeholder 写的是「如：业务域, 团队」；
- `validate_weight_config` 只校验「必须是字符串列表」，没有枚举白名单。

结果：运维按命令输出与 UI 提示填 `业务线/产品线`，`signal in disabled` 永假，被判定区分度不足的 facet 仍然走 T2。research §3.2 步骤 3 的「放弃该 facet 的 T2 通道」这条硬约束在生产里不成立，而这正是防止「信号加了但没用甚至有害」的闸门。另外 `team` 根本不走 T2，UI 却把「团队」当示例。

**修复：** 定义单一枚举（建议就用 `domain`/`stack`），`validate_weight_config` 做白名单校验并拒绝未知值；校准命令输出里同时给出「应写入 `t2_disabled_facets` 的值」列（英文 signal 名）；UI 改为多选。

### MJ-03：权重校验没有真正保证「文本主导」

**文件：** `server/codegraph/services/repo_router_config.py:66-127`

两个缺口：

1. **INV-R2 的分子漏了 activity。** `_META_WEIGHT_KEYS = (domain, stack, team)`（`:70`），而 research §4 的 INV-R2 是「元数据信号权重之和 = 0.45 ≤ 0.5」，0.45 = domain 0.15 + **act 0.12** + stack 0.08 + team 0.05 + crit 0.05。把 activity 排除后校验被显著放宽，默认值恰好两种口径都通过（0.40 ≤ 0.475），所以测试看不出来。
2. **允许 `text=0`，甚至允许全 0。** 实测（`validate_weight_config` 直接调用）：

```
{'text':0,'domain':0,'activity':0,'stack':0,'team':0}          → errors == []
{'text':0,'domain':0.05,'activity':0.55,'stack':0,'team':0}    → errors == []
```

第二组通过后，文本证据完全不进分、活跃度独占 0.55 —— 与「文本证据永远占主导」相反。第一组更严重：全 0 权重让 `_score_with_meta` 的 `denom` 为 0，全部候选 `score=0.0`、`breakdown={}`（实测确认），排序退化为按 `repo_id` 字典序，`derive_confidence` 恒 low → `auto_selected` 恒 false → **正是本里程碑 RELY 组要修的「编排卡死」故障，可被一次合法的权重保存重新触发**。loader 的 fail-safe（非法回退默认）帮不上忙，因为这组值「合法」。

**修复：** 元数据和纳入 activity；补硬校验 `weights[text] > 0`、`weights[text] == max(weights.values())`、`fsum(weights) > 0`；前端预校验同步（`RepoRouterWeightSettings.vue:134-173`）。

### MJ-04：N_r 快照写入 `node_count=0` 的仓，`n_r=0` 反而给 breadth 加成

**文件：** `server/codegraph/management/commands/measure_repo_index_stats.py:426-433`、`server/codegraph/services/repo_router_scoring.py:306-312`

写入端把**所有**仓（含 `node_count=0`）写进 `n_r_by_repo`，只用有索引仓算 `n_bar`：

```426:433:server/codegraph/management/commands/measure_repo_index_stats.py
        n_bar = float(statistics.median(indexed_counts))
        snapshot = {
            "n_r_by_repo": {row["repository_id"]: row["node_count"] for row in per_repo},
            "n_bar": n_bar,
            "generated_at": datetime.now(UTC).isoformat(),
        }
```

scorer 侧 `float(n_r) >= 0.0` 把 0 当有效值：`denom_size = 1 - b + b·0 = 0.4`，即「体量为 0 的仓」得到最强的尺寸归一红利。实测（n_bar=60、单命中、默认常数）：

| n_r | breadth |
|-----|---------|
| 0（快照过期/未索引） | **0.6438** |
| 缺失（不在快照里） | 0.3562 |
| 60（= 中位数） | 0.3562 |
| 620（monorepo） | 0.0725 |

也就是说「不在快照里」是中性的 0.3562，而「在快照里且为 0」拿到 +0.29 的广度加成。真实触发路径：快照生成后新索引的仓（Qdrant 有节点 → 会出现在 node_hits，快照里仍是 0）会获得系统性优势——又是一种结构性偏袒，与 ROUTE-03 目标相反。

**修复：** 写入端 `if row["node_count"] > 0` 过滤；scorer 把 `n_r <= 0` 视为缺失（把 `>= 0.0` 改成 `> 0.0`）；两侧都改（防呆）。另外建议快照带 `generated_at` 陈旧度告警（当前只记录不评估）。

### MJ-05：last_commit 聚合在路由热路径每次全量扫 `FileIndex`

**文件：** `server/codegraph/services/repo_router_v2.py:407-438`、调用点 `:509`

```425:432:server/codegraph/services/repo_router_v2.py
        try:
            rows = list(
                FileIndex.objects.filter(repository_id__in=repository_ids)
                .values("repository_id")
                .annotate(latest=Max("last_commit_authored_at"))
            )
        except (ValidationError, ValueError):
            return {}
```

确实避免了 N+1（单条 GROUP BY），但代价是：每次路由都要读取候选仓（最多 ~50 个）的**全部** `FileIndex` 行来算 Max。`FileIndex.Meta.indexes` 只有 `(repository, file_path)`，`last_commit_authored_at` 上无索引也无覆盖索引，因此是按 repository 前缀的索引扫 + 全行读取。数千文件×数十仓 = 每次路由十万行量级的扫描，落在一条本里程碑正在压延迟的链路上。

对照：`N_r` 正是为了避免「逐次 count」才做成离线快照（`--write-snapshot`），活跃度用了同样重的口径却没有同样的缓解。

**修复：** 三选一——(a) 与 N_r 合并进同一份离线快照；(b) 把 `last_commit_at` 反范式化到 `Repository`（由索引/同步流程写）；(c) 至少加 `(repository, last_commit_authored_at)` 索引并对聚合结果做短 TTL 进程缓存（键含仓集合）。

### MJ-06：T2 冷启动在热路径逐值串行 embedding；批量预热函数无生产调用方

**文件：** `server/codegraph/services/repo_router_metadata.py:481-518`（`match` / `_get_facet_vector`）、`:567-624`（`warm_facet_vectors`）

`_load_repo_meta` 对每个候选仓逐个 `await resolve_facet_scores(...)`，其中每个未命中 T1 的 facet 值都可能触发一次 `FacetT2Matcher.match` → `_get_facet_vector` → `EmbeddingService.generate_embedding(value)`。缓存冷启动（进程重启、Django cache 驱逐、换 embedding 模型导致 key 前缀变化）时，一次路由会串行发出「候选仓数 × (1 domain + N stack 分量)」次 embedding 请求 —— 几十次串行 HTTP，秒级延迟，且全落在 Stage 0。

`warm_facet_vectors`（用 `generate_embeddings_batch` 批量、且 best-effort）正是为此写的，其 docstring 声称「106-04 校准 command / 106-06 router 冷启动调用」，但全仓 grep 只有测试引用它：

```
server/codegraph/services/repo_router_metadata.py:567  (定义)
server/tests/codegraph/test_repo_router_metadata.py:482,498,511  (测试)
```

即生产链路上是死代码，docstring 的调用方声明与事实不符。

**修复：** 在 `_load_repo_meta` 里先扫一遍所有候选仓的 facet 值（split 后去重）调一次 `warm_facet_vectors`，随后逐值只读缓存；并给单次路由的 T2 embedding 次数设硬上限（超限静默降级 T1-only，符合既有「T2 绝不阻塞路由」原则）。

---

## MINOR

### MN-01：`_load_latest_commits` 的脏数据容错粒度过粗
`server/codegraph/services/repo_router_v2.py:427-434`。docstring 说「按该信号不可用处理，不让脏数据杀掉整条 repo_meta 链路」，但实现是 `return {}`：一条非 UUID 的 `repository_id` payload 会让**全部**候选仓的 `last_commit_at` 变成 None，全体退化为枚举回退。建议先 `uuid.UUID(rid)` 逐条过滤合法值再查询，脏值只影响自身。

### MN-02：新增 Qdrant 方法的日志字段不合规范
`server/services/qdrant_service.py:1477-1486`。`dense_search_by_name_failed` 没有 `category` / `component`（`.cursor/rules/observability-logging.mdc` 列为强制自检项），`error=str(e)` 未过 `redact_secrets_in_text`（同 phase 的两个 command 都做了；Qdrant `UnexpectedResponse` 会带上游响应体）。文件内其余日志同样缺字段属既有欠账，但新增代码应按现行规范补齐。

### MN-03：affine clip 校准区间缺值域校验
`server/codegraph/services/repo_router_config.py:132-142`。`_CONSTANT_RULES` 没有 `s_top_c_lo/hi`、`t2_c_lo/hi` 的规则，只有跨键的 `lo < hi`。`s_top_c_lo=-5, s_top_c_hi=0.55` 可通过校验，之后 `(cos+5)/5.55` 让所有仓的 S_top 都压到 0.95 附近（信号方差趋零，正是 research §3.2 警告的「信号加了没用」死法）。建议加 `[0,1]` 范围与最小带宽（如 `hi-lo >= 0.05`）。

### MN-04：tie-break 破坏 `derive_confidence` 的输入单调性
`server/codegraph/services/repo_router_scoring.py:557-570` 与 `:574-595`。`_meta_sort_key` 先按量化带排序、带内按 criticality，因此 `sorted_scores` 不再单调降序，`margin = s1 - s2` 可为负。当前后果无害（只会把 confidence 降为 medium/low，且当 `margin >= θ_margin(0.08) > crit_band(0.03)` 时首位必为全局最大，不会误 auto-select 非最高分仓），但 `derive_confidence` 的 docstring 与参数名 `sorted_scores` 都暗含降序假设。建议 `margin = max(0.0, s1 - s2)` 并把该推理写进 docstring/测试，避免后续调 `crit_band`/`θ_margin` 时踩坑。

### MN-05：权重设置组件零单测；网格外历史值退化为空占位
`web/src/components/settings/RepoRouterWeightSettings.vue:120-210`。423 行新组件带 INV-R2 预校验、区间校验、`is_default` 剥离、400 errors 渲染等分支逻辑，无任何测试（对比：`RoutingDecisionPanel` 的标签改动补了 2 个 case）。另外若 DB 里存着非网格值（旧数据/直写），`Select` 找不到匹配项只显示 placeholder，用户看不出当前值是多少，保存又会被后端拒。建议补组件测试并把非网格值渲染成一次性 legacy 选项 + 提示。

### MN-06：写入事件缺 duration_ms；GET 口径未明确
`server/system/views.py:1573-1631`。`repo_router_weight_config_updated` 的 `category`/`component` 到位，但没有 `duration_ms`（LOGGING-SPEC 要求关键生命周期带耗时）；也没有 started/failed 配对事件（校验失败的 400 无埋点，看不到「谁在反复填错」）。GET 对任意已认证用户开放内部打分权重，虽非凭证但属内部策略，建议要么收到 superuser，要么把「有意放开」写进 docstring。

### MN-07：golden 门禁区分度饱和，fixture 数值人工设定
`server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json`。新 baseline：`recall@5=0.9643`、`mrr@10=1.0`、`top1_correct=14/14`、`false_auto_select_rate=0.0`（105 为 mrr 0.9643 / top1 13）。14 条 case 全部 Top-1 命中意味着门禁只能检出退化、无法验证泛化，而 research §7.2/§7.3 恰恰警告 n=14 上的「完美」多半来自数据构造。`gk-001` 的 `dense_cos_max` 只给了需要区分度的两个仓（`repo_meta` 里 `study-course`/`study-user-status` 省略），facet 匹配分也是内联手写——即 fixture 与期望名次是同一个人同时定的。建议补「新公式应当判错/打平」的负向样本、补 dense 覆盖组合的多样性，并在 case 注释里标明数值来源是人工设定还是实测（沿用 MEASUREMENTS 的数据环境标注纪律）。

### MN-08：T1 单字符 canonical 的误报面
`server/codegraph/services/repo_router_metadata.py:143-155` 与 `:112`。`_contains_token` 对 ASCII token 加 `[a-z0-9]` 词边界，但 `DEFAULT_ALIAS_DICT` 里存在单字符 canonical `"C"`：任何含独立 `c` token 的需求文本（`"c 端"`、`"C 轮"`、路径片段等）都会让「技术栈=C」的仓拿到 T1 满分。同理 `"Go"` 会命中英文动词 `go`。stack 权重只有 0.08，影响有限，但 T1 是「确定性层，误报比漏报代价高」（本文件注释自述）。建议给长度 ≤2 的 ASCII canonical 要求更强上下文（`C 语言` / `C/C++`）或只允许经别名命中。

---

## INFO

### IN-01：stack 满分口径与其他 facet 不同
`server/codegraph/services/repo_router_metadata.py:398-404`。`0.8·max + 0.2·second_max` 使单值精确命中上限为 0.8，而 domain/team 精确命中是 1.0；两个都命中的多标签仓才拿 1.0。这是 CONTEXT 锁定的取舍（research §3.3 的可选折中，保留一点「多重匹配更强」信号），不是缺陷，但会让运维在看 breakdown 时误判「技术栈信号偏弱」。建议在设置页/文档写明该口径。

### IN-02：`warm_facet_vectors` 的实现细节
`server/codegraph/services/repo_router_metadata.py:591`（调用 `matcher._cache_get` 私有方法）、`:604`（`zip(pending, vectors)` 在批量返回条数不足时静默截断，`available` 计数会偏低但无任何记录）。建议把 `_cache_get`/`_cache_set` 提为公开方法，并在长度不符时记一条 sampling warning。

---

## 已核对通过的项（不构成 finding，供后续 phase 参考）

- **公式一致性**：`n_eff` 软计数（`p` 次幂，桶内 `s_hat/s_hat_top`）、pivoted denom `1-b+b·N_r/N̄`、`log1p` 饱和 `n_cap`、`S_text=(1-λ)S_top+λ·breadth` 与 research §2.3 逐步一致；活跃度 `0.5^(max(0,Δd-offset)/H)` + `floor` + 废弃封顶与 §3.5 一致且四行真值表（连续/枚举/皆无/跨来源封顶）全覆盖。
- **多值聚合无 sum/mean**：`_resolve_stack` 只用 `max`/`second_max`，`技术栈` split("/") 后逐值匹配；grep 确认无 sum/mean 路径。
- **缺失重归一化**：`available` 集合上 `D = w_text + Σw_j`，`breakdown[j] = w_j·M_j/D`，`score = fsum(breakdown)` —— INV-R3 按构造成立（`test_all_candidates_satisfy_score_invariants` 用 `==` 严格断言且通过）；INV-R1 由 `Σ ≤ (w_text+Σw)/D = 1` 保证且无截断；INV-R4 成立（关信号只改 D，不改其余项比值）。
- **C_crit 不进加性和**：`breakdown` 无 criticality 键，仅 `ScoredCandidate.criticality` 旁路 + 量化桶 tie-break；量化桶对带边界的近似取舍已在代码注释里显式记录（`repo_router_scoring.py:557-561`）。
- **纯函数纪律**：`repo_router_scoring` 仅 stdlib、无 Django import、时间锚点参数注入（router 里 `scored_at` 是唯一取 `datetime.now` 的位置并进快照）；`math.fsum` + `(-round(score,6), repo_id)` 消除浮点顺序依赖。
- **降级不反噬**：`route()` 对 `aload_weight_config` / `_load_repo_meta` 整体 try/except 回退 legacy 三信号；dense 查询、N_r 快照、embedding 配置、T2 匹配、Django cache 读写、全部观测埋点均 best-effort 且异常吞掉；loader 对非法 DB 行回退 `DEFAULT_WEIGHT_CONFIG` 深拷贝并记 warning。
- **权限与加密**：新端点复用 `SystemSetting`/`SettingKeys`/`settings_service`，`is_superuser` 检查与 `ClaudeCodeConfigView.put` 同款（async 视图里同样直接读 `request.user`，与既有代码一致，非新风险）；`is_encrypted=False` 对非敏感配置合理；`post_save` receiver 保证「保存即生效」。
- **快照脱敏**：`builtin_processes._routing_snapshot_payload` 新增的 `weight_config`/`repo_meta` 两节同样整体过 `redact_for_ledger`；`repo_meta` 只存数值与层级、不存 facet 原文；T2 降级日志把 facet 值截断到 32 字符。
- **前端**：`SIGNAL_LABELS` 键与后端常量字面对齐，未知键回退英文原名有回归测试；`criticality` 不入 breakdown 故 Σ 校验不受影响；`RepoRouterWeightConfig` 类型与后端形状一致，`is_default` 在 PUT 前被剥离（后端拒未知顶层键）；admin 页由既有全局导航守卫做 superuser 拦截。
- **回放双版本**：105 旧快照（缺 `weight_config` 或节残缺/类型错）走 legacy 三信号并标 `LEGACY_SNAPSHOT_NOTE`，`ReplayResult` 继承 `list` 保持向后兼容；`activity_facet` 已进最小字段集，故 legacy 与新路径的枚举回退都可复现（自包含性的缺口只在 BL-02 描述的非候选仓 meta 上）。

---

## 修复记录（2026-07-30）

**结论：** 2 BLOCKER + 6 MAJOR + 6 MINOR + 2 INFO 已修（16 条），2 MINOR 标 deferred（MN-05 组件测试底座、MN-07 golden 负向样本）。逐条状态与 commit 见 frontmatter 各 finding 的 `status` / `fix_commit`。

| commit | 覆盖 finding |
|--------|-------------|
| `f2b54a08` | BL-01（含版本 bump phase106-v2 + baseline 重建） |
| `7ce74d21` | BL-02 |
| `289a02fa` | MJ-01 |
| `b6529577` | MJ-02、IN-01 |
| `148fac9f` | MJ-03 |
| `5a6b0593` | MJ-04 |
| `639f7ddb` | MJ-05、MJ-06、MN-01、IN-02 |
| `a9e15a31` | MN-02、MN-03、MN-04、MN-06、MN-08 |

### gk-001 翻转的最终结论：**仍然成立**，且不再依赖错误抬升

BL-01 修完后 gk-001 的 dense 覆盖不全（4 个候选仓只有 2 个有 `dense_cos_max`），因此整条查询统一走 RRF s_hat 口径。重算结果（`score_case`，n_bar=60、scored_at 2026-07-29）：

| repo | score | breadth 分项 | 变化 |
|------|-------|-------------|------|
| onion-learning | 0.8813 | 0.0697 | 不变（其 S_top 在两种口径下都是 1.0——余弦 0.62 超 c_hi 被 clip，RRF 下又是 rank-1） |
| study-course | 0.8232 | 0.0952 | 不变（原本就走回退） |
| study-user-status | 0.7409 | 0.0803 | 不变（原本就走回退） |
| study-app | 0.7102 | 0.0462 | 0.7453 → 0.7102（原先按校准余弦 0.52→S_top 0.90，现按 RRF 0.8232） |

三条机制断言全部继续成立：
- **翻转**（`test_gk001_mechanism_rank_flipped`）：`onion-learning` 位次 0 < `study-app` 位次 3——修正标尺后 study-app 从第 3 掉到第 4，翻转幅度反而更大。
- **breadth 不偏袒巨仓**（`test_gk001_mechanism_breadth_not_favor_monolith`）：study-app 0.0462 ≤ onion-learning 0.0697，与 dense 口径无关（breadth 只吃 n_eff 与 pivoted denom）。
- **跨组两仓进 Top-5**：`study-course`（第 2）、`study-user-status`（第 3）。

REVIEW 提出的疑虑（「`test_gk001_cross_group_repos_in_top5` 的通过部分依赖回退抬升」）本次得到澄清：受回退抬升影响的确实是 `study-course` 的 S_top，但它在修正后的**统一** RRF 口径下依然是 0.7927（其命中分 0.013 相对 rrf_max 0.0164），排名不靠「缺失红利」而靠真实命中强度；被高估的其实是原实现里 `study-app` 的对照口径。**没有调整任何权重或 fixture 数值**——baseline 唯一 diff 是 gk-001 `ranked_repo_ids` 的 3/4 位互换，汇总指标（Recall@5 0.9642857 / MRR@10 1.0 / Top-1 14/14 / 误自动选中率 0.0）逐字段不变。

### 回归

- `cd server && uv run pytest tests/codegraph tests/system tests/services/test_repo_router_adapter.py -q` → **440 passed / 20 skipped**
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected（新增迁移 `repositories/0040_file_index_last_commit_index`）
- `web`：`pnpm type-check` 干净、`pnpm eslint` 干净、`pnpm vitest run RoutingDecisionPanel.test.ts` → 12 passed
- 新增守护测试：S_top 单一标尺 6 条、快照自包含 3 条、锚点注入 2 条、t2_disabled_facets 归一 4 条、权重硬校验 4 条、n_r<=0 1 条、last_commit 缓存 1 条、脏 rid 隔离 1 条、T2 批量预热 1 条、embed 预算 2 条、margin 夹紧 2 条、短 canonical 1 条、校准区间值域 6 条

---

_Reviewed: 2026-07-30T01:32:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: deep_
_Fixed: 2026-07-30T02:45:00+08:00 by gsd-code-fixer_
