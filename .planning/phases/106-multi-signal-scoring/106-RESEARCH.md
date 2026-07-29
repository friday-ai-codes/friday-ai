# Phase 106: 多信号打分函数重构 - Research

**Researched:** 2026-07-29
**Domain:** 检索排序 / 多信号线性融合 / Django 后端 + Vue 前端集成
**Confidence:** HIGH（代码层事实全部实读验证；公式与常数沿用 ROUTING-RANKING 已锁定结论）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**聚合公式与尺寸偏置（ROUTE-03）**
- 聚合结构：MaxP 主干 + pivoted-size-normalized 对数饱和 breadth，**加性**合成（research §2.3 三步：n_eff 软计数 p=2 → pivoted denom `1-b+b·N_r/N̄` b=0.6 → `log1p` 饱和 n_cap=6；`S_text=(1-λ)·S_top+λ·breadth` λ=0.25）。
- `N̄` 用全仓能力树节点数**中位数**（抗 monorepo 倾斜）；`N_r` 离线取自 repo_index_nodes 计数（105-02 的 measure command 已有计数逻辑可复用）。
- MaxP 主干口径（O-3）：优先用单独 dense 查询取余弦（`using="dense"`，105-MEASUREMENTS 已验证可行）+ affine clip 校准；若实现后延迟/成本不可接受，回退 RRF 分 query-local max 归一，取舍记录进 SUMMARY 与代码注释。
- 机制级断言：golden set 用例锁机制（`breakdown["study-app"]["breadth"] <= breakdown["onion-learning"]["breadth"]`、跨组样本进 Top-5）而非偶然名次；gk-001（Top-1=onion-learning）翻转后 `GENERATE_GOLDEN=1` 重建 baseline 并核对 Recall@5 不降、误自动选中率 ≤10%。
- 所有常数（p/b/n_cap/λ/N̄ 快照值）外置，见权重外置节。

**元数据入分（ROUTE-04）**
- 三层匹配：T1 确定性别名词典（facet 值 + 人工同义词表；1.0 精确/别名、0.6 上位类目）→ T2 校准 embedding 余弦（`clip((cos-c_lo)/(c_hi-c_lo),0,1)`，初值 c_lo=0.25/c_hi=0.55，**必须按 O-2 流程实测校准**：200 组负样本 p95→c_lo、30 组正样本 p50→c_hi；`c_hi-c_lo<0.10` 的 facet 放弃 T2 只留 T1）→ T3 LLM 判定**绝不进分数**（只作 Stage 1 解释材料）。
- 多值 facet 取 **max**（技术栈可用 `0.8·max+0.2·second_max`），绝不 sum/mean（尺寸偏置同构重演）。
- 缺失信号：**权重重归一化**（`S=Σ w_j·M_j / Σ w_j`，仅对 present 信号），不补 0；全部元数据缺失时退化为纯文本分数。trace/breakdown 记录每个 facet 分数来源层（T1/T2/缺失）。
- `关键程度` 是静态先验：固定锚点 {核心 1.0/重要 0.7/一般 0.4/边缘 0.15}，权重上限 0.05，且仅作同分带内 tie-break（|S_a-S_b|<0.03 时生效）。`团队归属` 是条件信号：需求文本未提团队时标**不可用**走重归一化，不给 0.5。
- facet 值 embedding 全量缓存（闭集几百条）；换 embedding 模型必须重校准并把模型 id 写进 weight_set_version。

**活跃度连续化（ROUTE-05）**
- 指数衰减：`A_recency = 0.5^(max(0,(now-last_commit_at).days-offset)/H)`，H=180d、offset=14d、floor=0.05（`A_act=max(A_recency, 0.05)`）。
- `疑似废弃` 惩罚改为对 A_act 封顶：`A_act = min(A_act, 0.10)`——完全落在活跃度项内、可在 breakdown 单独展示（105-03 已把乘性 DEPRECATED_PENALTY 移除，此处接管语义）。
- 无 `last_commit_at` 时回退枚举映射 {活跃开发:0.9, 维护中:0.6, 低频:0.3, 疑似废弃:0.1}。
- O-5 实测：全仓 `last_commit_at` 覆盖率与新鲜度统计（可扩展 105-02 的 measure command），结论落 106-MEASUREMENTS.md（沿用数据环境标注纪律）；覆盖不足的仓自动走枚举回退。

**权重外置（ROUTE-06）**
- 全部权重与常数（6 信号权重 + p/b/n_cap/λ/H/offset/floor/c_lo/c_hi/θ_abs/θ_rel/CRITICALITY 表等）落 `SystemSetting`（复用既有 `SettingKeys`/service 层与加密约定，绝不绕过），附 `weight_set_version` 字符串。
- 权重初值（research §4）：S_text 0.55 / M_domain 0.15 / A_act 0.12 / M_stack 0.08 / M_team 0.05 / C_crit 0.05，Σ=1.00。不变量写成测试：INV-R1 `0≤S≤1` 无截断；INV-R2 元数据权重和 ≤0.5（文本主导，可证明推论落测试）；INV-R3 Σ贡献==总分（重归一化后仍成立）；INV-R4 关任一信号不改其余相对比例。
- 生效语义：保存后下一次路由立即按新值打分（调用时读取 + 短 TTL 进程内缓存均可，planner 定），无需发版/重启。每条路由结果/快照记录 weight_set_version（105 版本四元组已有该位，从占位换成真实版本）。
- 运维界面：优先复用既有系统设置管理面（若已有通用 SystemSetting 编辑器则零新 UI；否则最小表单/JSON 编辑 + 校验 Σw=1 与网格取值），researcher 确认落点。权重取值约束在**离散网格** {0,0.05,0.08,0.10,0.12,0.15,0.20,0.30,0.40,0.55}（防过拟合四道闸之一），后端校验。
- Stage 1 之上的凸组合 `S_ranked=0.65·S_final+0.35·S_llm` 归 Phase 107（有界重排），本 phase 打分函数只产 S_final。

### Claude's Discretion
- 别名词典的初始条目规模与存放形态（fixture/SystemSetting/代码常量）、facet embedding 缓存介质、SystemSetting 键名切分粒度由 planner/executor 按代码库惯例定。
- O-2 校准若开发库缺少真实 facet 数据，允许用结构性样本先定管线并把生产校准记 deferred（同 O-1 纪律）。
- 观测埋点按 LOGGING-SPEC 补齐；新增设置读写走既有权限面。

### Deferred Ideas (OUT OF SCOPE)
- 分组呈现（in_project/global、trust 标注、delta=0.15 迟滞）与 Stage 1 凸组合 α=0.35 → Phase 107。
- 权重自动调参（coordinate ascent 建议器）/在线学习 → Future（本里程碑不做）。
- 活跃度 v2 增强（`0.7·A_recency + 0.3·commit 频次饱和`）→ Future（research §3.5 标注本次不做）。
- O-1/O-2 生产环境校准数字回填 → 挂账人工步骤（同 105 UAT 纪律）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-03 | 大而全的单体仓库不再因命中节点多而被系统性高估——同等相关度下小而精的正确仓库能胜出 | §1 打分核心扩展面（breadth 公式替换点在 `aggregate_and_score` 第 3 步）；§4 dense 余弦查询路径；§3 N_r/N̄ 数据获取方案；§8 gk-001 翻转与 fixture 扩展 |
| ROUTE-04 | 业务域、团队归属、技术栈、关键程度等元数据参与排序打分 | §2 facets 键名/闭集/覆盖率实况；§6 embedding 校准管线；§9 别名词典现状（需从零建）；§7 快照携带元数据信号 |
| ROUTE-05 | 仓库维护活跃度以连续量参与打分 | §3 `last_commit_at` 数据源（`Max(FileIndex.last_commit_authored_at)`）与免 N+1 取法；O-5 实测方案 |
| ROUTE-06 | 运维可在不发版的前提下调整各信号权重 | §5 SystemSetting/settings_service/信号失效机制/REST API/前端设置页落点全链路 |
</phase_requirements>

## Summary

本 phase 是纯代码/配置改造，不装任何新外部包（Package Legitimacy Audit 为空）。所有公式与常数已由 ROUTING-RANKING.md + CONTEXT 锁定，研究重点是「现有代码的扩展面与数据可得性」。十个关键调查点全部有代码级答案，其中三个发现会实质影响计划编排：

1. **`last_commit_at` 不在 `Repository` 上**——它要从 `Max(FileIndex.last_commit_authored_at)` 按仓聚合得出（`FacetService._compute_activity` 已是这个口径）。路由时对 ≤12 个候选仓做**一次** `values("repository_id").annotate(latest=Max(...))` 聚合查询即可，无 N+1；但这意味着纯函数签名必须扩展出「repo 级元数据注入」参数，且该值必须进快照供离线回放。
2. **T2 embedding 余弦在离线回放/golden harness 里不可重算**（要打 embedding API）。因此架构上必须把「信号解析」（I/O：dense 查询、embedding、DB 聚合）与「打分」（纯函数）分成两层：router 层解析出 per-repo 的 `repo_meta`（N_r、last_commit_at、各 facet 匹配分+来源层、dense 余弦），纯函数只消费数值。快照记录 repo_meta 原值（与 Stage 1 排列记录同一模式），golden fixture 扩展同形字段。
3. **`关键程度` 的事实闭集与 CONTEXT 锚点表不一致**——`FacetService._compute_criticality` 只产 {核心, 重要, 边缘}，没有「一般」档；且「tie-break only（|ΔS|<0.03 才生效）」与「加性权重 0.05、Σw=1.00」两种语义在实现上互斥，需要 planner 定夺（本文 §Open Questions 给出推荐）。

**Primary recommendation:** 按「resolver（I/O，router 层）→ scorer（纯函数）」两层扩展 `repo_router_scoring.aggregate_and_score`；权重+常数落单个 JSON SystemSetting 键 `repo_router.weight_config`（点分命名惯例），经专用 API view 做 Σw=1 + 离散网格校验；读取走 `settings_service.get_json_setting`（60s 缓存 + signal 写时失效 = 保存即生效）+ `sync_to_async` 包装。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MaxP+breadth 聚合、元数据合成、活跃度衰减、重归一化 | 纯函数层 `repo_router_scoring.py` | — | router/replay/golden 三方共用，零 I/O 才能离线回放（105 结构保证，必须延续） |
| dense 余弦查询、last_commit 聚合、facet T1/T2 解析（repo_meta 组装） | Router 层 `repo_router_v2.py` + 新 resolver 模块 | `QdrantService` / `EmbeddingService` | 全部 I/O 收在 Stage 0 内；解析结果以数据形式进快照 |
| facet 值 embedding 缓存与 O-2 校准 | 服务层（新 resolver/校准 command） | Django cache | 闭集几百条，一次算全量缓存 |
| N_r/N̄ 快照、O-5 覆盖率统计 | management command（扩展 `measure_repo_index_stats`） | SystemSetting（N̄/N_r 快照存放） | 离线一次性实测，路由时只读快照 |
| 权重/常数存取 + 校验 | `system` app（SettingKeys + 专用 view） | `settings_service` | 复用加密/权限/缓存失效既有设施（项目 Convention 约束） |
| 权重编辑 UI | `web/src/pages/admin/index.vue` 新设置 section | `web/src/api/settings.ts` | 已有通用 per-key 设置 API + section 组件模式（RerankSettings.vue 同款） |
| 快照携带权重与 repo_meta、旧快照回退 | `repo_router_v2._build_snapshot` + `repo_router_replay.py` | `builtin_processes._h_route` | versions 四元组已有 weight_set_version 位 |
| golden 门禁扩展 | `server/tests/codegraph/`（fixture + eval + gate） | — | GENERATE_GOLDEN=1 只重建 baseline，主 fixture 手工维护需扩字段 |
| breakdown 新信号中文标签 | `web/src/components/chat/RoutingDecisionPanel.vue` | — | `SIGNAL_LABELS` 组件内硬编码 map（非 vue-i18n），未知 key 回退英文原名 |

## Standard Stack

本 phase **零新增依赖**：全部使用既有栈（Django 5.1 / adrf / qdrant-client ≥1.9 / structlog / pytest 9 / Vue 3）。禁止引入 numpy/scipy（105 已锁定：eval/bootstrap 用 stdlib，`repo_router_eval.py` 模块契约明文禁止）。

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 单 JSON SystemSetting 键存权重 | 每常数一个键（`repo_router.weight_text` 等 ~20 个键） | 多键便于单项改动，但 Σw=1 跨键校验无处落、原子性差；单 JSON 键 + 专用 view 校验更稳（`CLAUDE_CODE_CONFIG` 先例） |
| dense 余弦（MaxP 主干） | RRF 分 query-local max | CONTEXT 已锁：余弦优先，延迟不可接受才回退；回退时 rank-1 恒为 1.0、跨 query 不可比 |
| Django cache 缓存 facet 向量 | 新 DB 表 / Qdrant collection | 闭集几百条、重算成本低（一次批量 embedding），cache 丢失可重建；建表是过度设计 |

## Package Legitimacy Audit

本 phase 不安装任何外部包。**Packages removed due to slopcheck [SLOP] verdict:** none。**Packages flagged as suspicious [SUS]:** none。

## 关键调查发现（planner 需要的事实）

### §1 打分核心现状与扩展面 [VERIFIED: 代码实读 `server/codegraph/services/repo_router_scoring.py`]

现有契约（250 行，零 Django/零 I/O，仅 stdlib）：

- 入口 `aggregate_and_score(node_hits, *, weights=None) -> list[ScoredCandidate]`。流程：按 `payload.repository_id` 分桶 → 桶内 `(-round(score,6), node_id)` 稳定排序 → query-local max 归一 `s_hat` → 三信号 `{text: max(s_hat), breadth: min(len(hits)-1,5)/5, activity: 枚举映射|None}` → 缺失重归一化 `breakdown[j] = w_j·M_j / Σ_available w` → `score = math.fsum(breakdown.values())`（Σbreakdown==score 按构造成立）→ 候选 `(-round(score,6), repo_id)` 排序。
- breakdown key 常量：`SIGNAL_TEXT="text"` / `SIGNAL_BREADTH="breadth"` / `SIGNAL_ACTIVITY="activity"`——**前端映射表与之对齐，禁止改名**（105-01 patterns-established）。新信号沿用此模式加常量：建议 `SIGNAL_DOMAIN="domain"` / `SIGNAL_STACK="stack"` / `SIGNAL_TEAM="team"` / `SIGNAL_CRITICALITY="criticality"`。
- `PHASE105_WEIGHTS = {text:0.70, breadth:0.20, activity:0.10}`、`WEIGHT_SET_VERSION = "phase105-v1"`、`ACTIVITY_ENUM_MAP`、`DEPRECATED_ACTIVITY_CAP=0.10` 均为模块常量。
- `derive_confidence` / `apply_llm_adjustment` 本 phase 不动（θ 阈值已 settings 外置，105-01）。

**扩展面（三处签名变化，影响四个调用方）：**

1. `aggregate_and_score` 需新增参数：per-repo 元数据注入（建议 `repo_meta: dict[str, RepoMeta] | None`，含 `n_r` / `last_commit_at`（ISO str 或 None）/ `dense_cos_max`（float 或 None）/ 各 facet 匹配分与来源层）与常数（建议 `constants: dict | None`，含 p/b/n_cap/λ/N̄/H/offset/floor/c_lo/c_hi/CRITICALITY 表）。全部带默认值，缺省时行为可控（`repo_meta=None` → 新信号全部不可用 → 重归一化后退化为 text+breadth+activity，旧调用零破坏）。
2. `now` 必须参数注入（活跃度衰减用），禁止函数内 `datetime.now()`——否则回放/golden 不确定。快照/fixture 记录 `scored_at`。
3. 四个调用方同步：`repo_router_v2._stage0_candidates`（传入真实 repo_meta + settings 权重）、`repo_router_replay.replay_route_from_snapshot`（从快照读 repo_meta + 权重）、`repo_router_eval.evaluate_cases`（从 fixture case 读）、`test_repo_router_scoring.py`（30 条性质测试扩展）。

**breadth 在 breakdown 的表示**：CONTEXT 机制断言引用 `breakdown[repo]["breadth"]`，且 λ 合成 `S_text=(1-λ)S_top+λ·breadth` 是加性的——推荐 breakdown 保持扁平并拆成两个 key：`text` 贡献 = `w_text·(1-λ)·S_top/denom`、`breadth` 贡献 = `w_text·λ·breadth/denom`。这样 INV-R3（Σ==score）与机制断言同时成立，前端零结构改动。（机制断言里的 `breakdown["study-app"]` 是 harness 侧「repo_id → breakdown dict」的索引写法，非嵌套 breakdown。）

### §2 facets 数据实况 [VERIFIED: 代码实读 `facet_service.py` / `summary_service.py` / `repo_index_tree.py` / `models.py`]

**数据流**：`Repository.facets`（JSONField）→ `RepoIndexTreeBuilder.build` 时 `json.dumps` 整体冗余进**每个**节点的 `payload.facets` → 打分核心 `_parse_facets` 取桶首 hit 的 facets。即路由时 facets 已在 hit payload 里，无需额外查询；但新鲜度绑定树重建时间（`refresh_facts` 走全量重建，由 `services/indexer.py` 与 `subagent/api/callbacks.py` 在索引完成后触发）。

**facet 键名与闭集（实际字段名，全中文 key）：**

| 键 | 类别 | 取值 | 来源 |
|----|------|------|------|
| `活跃度` | 事实分面 | {活跃开发, 维护中, 低频, 疑似废弃}（14d/90d/365d 分档） | `FacetService._compute_activity` |
| `关键程度` | 事实分面 | **{核心, 重要, 边缘}——无「一般」档**（入度 ≥10/≥1/0） | `FacetService._compute_criticality` |
| `团队归属` | 事实分面 | 开放集：git URL namespace 链（如 `"group/sub"`） | `FacetService._compute_team` |
| `技术栈` | 事实分面 | **单字符串斜杠拼接 Top-3**（如 `"Python/Vue/Go"`，语言名闭集 `_EXT_LANGUAGE_MAP` 20 值） | `FacetService._compute_tech_stack` |
| `业务线/产品线` | 语义分面 | `FacetVocabulary` 受控词表（dimension unique，values JSON 列表）；LLM 选不出填 **"未分类"** | `summary_service.SEMANTIC_FACET_DIMENSIONS` |
| `服务对象` / `技术形态` | 语义分面 | 同上（词表驱动） | 同上 |
| `_pinned` | 元键 | 维度名列表（人工 pin，刷新跳过），下划线前缀键在 Stage 1 prompt 已被过滤 | `facet_service.py` |

**要点**：
- `M_domain` 的 facet 键是 **`业务线/产品线`**（复合键名含斜杠）；值 `"未分类"` 应视为信号不可用（等同缺失），不是一个可匹配值。
- `技术栈` 是**多值但存成单字符串**——resolver 必须 `split("/")` 再做 `0.8·max+0.2·second_max`。
- facet 值闭集枚举来源：语义分面查 `FacetVocabulary.objects.filter(is_active=True)`；事实分面在代码常量（`ACTIVITY_ENUM_MAP` 已有；criticality/tech 需照抄 `facet_service.py`）。`团队归属` 是开放集，只能走 T1 精确/别名匹配，无 T2 意义有限（团队名 embedding 区分度存疑，O-2 会给结论）。
- **覆盖率查询**：`Repository.objects.filter(is_deleted=False).values_list("facets", flat=True)` 后按键统计非空/非"未分类"占比——建议并入 O-5 统计 command 一起输出（开发库数字只作结构性验证，生产实测 deferred，沿用 105 数据环境标注纪律）。

### §3 `last_commit_at` 数据源与免 N+1 取法 [VERIFIED: 代码实读 `repositories/models.py:568-608`, `facet_service.py:87-105`]

- `Repository` **没有** last_commit 字段。`FileIndex`（文件级索引记录，unique(repository, file_path)）有 `last_commit_sha` / `last_commit_authored_at`，由 indexer 写入时 `git log -1 --format=%H|%ct -- <file>` 逐文件填入。
- 仓库级口径 = `FileIndex.objects.filter(repository_id=rid).aggregate(Max("last_commit_authored_at"))`——`FacetService._compute_activity` 已用此口径产四档枚举，连续化只是保留原始 timestamp 不分档。
- **路由时高效取法（免 N+1）**：Stage 0 候选 ≤ `STAGE0_REPO_K=12`，一次聚合查询：

```python
# router 层（sync_to_async 包装）
from django.db.models import Max
rows = FileIndex.objects.filter(repository_id__in=candidate_ids).values(
    "repository_id"
).annotate(latest=Max("last_commit_authored_at"))
latest_by_repo = {str(r["repository_id"]): r["latest"] for r in rows}
```

- 新鲜度绑定「最近一次索引」时间——仓库索引停更则该值停更，但停更本身就意味着低活跃，语义自洽（可在 SUMMARY 注明）。无 FileIndex 行的仓（未索引/新导入）→ 枚举回退（CONTEXT 已锁）。
- O-5 统计（覆盖率 + 新鲜度分位数）建议扩展 `measure_repo_index_stats` 加 `--activity` 选项（该 command 已有 per-repo 循环与 JSON/markdown 双输出骨架，结构性测试 `test_measure_repo_index_stats.py` 在内存 Qdrant 上验证）。开发库跑出的数字不得写入 106-MEASUREMENTS.md 的生产结论区。

### §4 dense 余弦查询路径与延迟 [VERIFIED: 代码实读 `qdrant_service.py:1317-1425`, `measure_repo_index_stats.py:247-307`; 延迟数字 ASSUMED 待生产回填]

- O-3 已定论（105-MEASUREMENTS §1）：`hybrid_search_by_name` 的 `FusionQuery(Fusion.RRF)` 返回融合分，**不回传 per-prefetch dense 余弦**；qdrant-client ≥1.9 无「一次查询同时拿两种分」的官方途径 [ASSUMED: API 形状推断，官方 changelog 未逐版本核对]。
- **`QdrantService.search_by_name` 对 hybrid collection 不可用**（查匿名默认向量 → 400 → 返回空）。必须新增带 `using="dense"` 的封装，写法照抄 `measure_repo_index_stats._verify_cosine` 探针：

```python
# 建议新增 QdrantService.dense_search_by_name（与 search_by_name 同形，仅加 using）
results = client.query_points(
    collection_name=collection_name,
    query=query_dense,            # 复用 _stage0_node_search 已算好的向量，零额外 embedding
    using="dense",
    query_filter=query_filter,    # 与 hybrid 同 filter（repository_ids 限定）
    limit=top_k,                  # 与 STAGE0_NODE_K=50 一致
    with_payload=True,            # 需要 repository_id 做归仓
)
```

- **批量方案**：一次 dense-only top-50 查询拿到 `{node_id: cosine}`，router 按 `payload.repository_id` 归仓取 max 得每仓 `dense_cos_max`；RRF 命中但不在 dense top-50 的仓 → `dense_cos_max` 不可用 → 该仓 `S_top` 回退 RRF s_hat（或对该仓单独标记，planner 定；推荐回退 + trace 标注 `s_top_source`）。共 **+1 次 Qdrant 往返**，同机部署预期 <10ms 量级 [ASSUMED: 105-MEASUREMENTS 推断，确切数字待生产 `--verify-cosine` 回填]。
- affine clip 校准：`S_top = clip((cos - c_lo)/(c_hi - c_lo), 0, 1)`，c_lo/c_hi 与 facet 校准同属 O-2 输出、同存 weight_config。
- 回退口径（延迟不可接受时）：RRF query-local max（现状 `s_hat`），取舍记录进 SUMMARY 与代码注释（CONTEXT 锁定）。

### §5 SystemSetting 全链路 [VERIFIED: 代码实读 `system/models.py`, `settings_service.py`, `signals.py`, `views.py`, `urls.py`, `web/src/api/settings.ts`, `web/src/pages/admin/index.vue`]

- **模型**：`SystemSetting(key PK, value Text, is_encrypted, description, updated_at)`。键名惯例：新键用点分命名（`log.level` / `metric.retention_days` / `code_index.exclusion.global_defaults` 先例）→ 建议 `repo_router.weight_config`（单 JSON 键，含 6 权重 + 全部常数 + `weight_set_version` + `embedding_model_id` + `calibrated_at`）。权重非敏感数据，`is_encrypted=False`，不涉加密约定。
- **读取**：`system.settings_service.get_json_setting(key, default)`（sync，60s Django cache；**async 版 `aget_*` 无缓存直查 DB 且没有 aget_json**）。`system/signals.py` 在 `SystemSetting` post_save/post_delete 时 `_invalidate_setting_cache(key)`——**保存即失效缓存，下一次路由立即生效**，满足 CONTEXT 生效语义，无需自建 TTL。router 是 async：用 `sync_to_async(get_json_setting, thread_sensitive=False)` 包装（`_stage0_node_search` 同款模式）。解析+校验+回退默认值建议收敛为一个 loader 函数（值非法/缺失 → 代码默认 + warning 日志），纯函数本身不读配置（105 契约延续）。
- **REST API**：`/api/settings/`（list/create）与 `/api/settings/<key>/`（get/put/delete），`permission_classes=[IsSuperUser]`——**通用 PUT 无 per-key 校验**。Σw=1 + 离散网格 {0,0.05,0.08,0.10,0.12,0.15,0.20,0.30,0.40,0.55} 校验必须落专用端点：照抄 `ClaudeCodeConfigView`（`system/views.py:866-948`，GET/PUT 单 JSON 键 + 结构校验）新建 `RepoRouterWeightConfigView`，挂 `system/urls.py`（注意通配路由 `<str:key>/` 在最后，新路径需排其前）。
- **前端落点**：无通用 SystemSetting 编辑器 UI；既有模式是 `web/src/pages/admin/index.vue` 设置 tab + section 组件（`web/src/components/settings/RerankSettings.vue` 是最贴近的样例：per-key `getSetting/putSetting`）。最小方案：新 section 组件（表单或 JSON 编辑 + 前端预校验 Σw=1/网格，后端为准）+ `web/src/api/settings.ts` 加 API 函数。`SettingKey` enum（前端）与 `SettingKeys`（后端）需同步加常量。
- **权限**：设置页在 `pages/admin/`（superuser 面板），后端 `IsSuperUser`——「哪些角色可改」= 仅 superuser，符合"新增设置读写走既有权限面"。

### §6 embedding 校准管线（O-2） [VERIFIED: 代码实读 `services/embedding.py`, `agents/call_source.py`]

- `EmbeddingService.generate_embedding(text) -> list[float] | None`（async；每次调用从 SystemSetting 读 api_url/api_key/model；失败返回 None 不抛）。批量版 `generate_embeddings_batch(texts, batch_size=32)` 可用于全量 facet 值向量预热。`CallSource.EMBEDDING` 枚举已存在（LOGGING-SPEC 22+ 值表内）。
- **模型 id 获取**：`EmbeddingService.get_config()["model"]`（默认 "BAAI/bge-m3"）——写进 weight_config 的 `embedding_model_id`，换模型必须重校准（CONTEXT 锁定）。
- **facet 值向量缓存**：无现成向量缓存设施。推荐 Django cache（`django.core.cache`，与 Stage 1 输入哈希缓存同设施）：key = `repo_router:facet_vec:{model_id}:{sha256(facet_value)}`，TTL 长（如 7d）；进程内再加模块级 dict 兜底。cache miss → 调 embedding → 回写。闭集几百条，冷启动一次批量预热即可；**T2 不可用时（embedding 失败/未配置）该 facet 静默降级 T1-only**，绝不阻塞路由（观测 warning 一次）。
- **O-2 校准脚本形态**：推荐**独立** management command（如 `calibrate_repo_router_metadata`）而非塞进 `measure_repo_index_stats`——后者是 O-1/O-3 的 Qdrant 统计，职责不同；校准要采样需求文本×facet 值算余弦分布（200 负样本 p95→c_lo、30 正样本 p50→c_hi、`c_hi-c_lo<0.10` 判废弃 T2）。正样本需人工确认对，开发库缺真实数据时按 CONTEXT 纪律：结构性样本定管线 + 生产校准 deferred。输出落 106-MEASUREMENTS.md（数据环境标注）。command 观测按 `measure_repo_index_stats` 的 `_LOG_KV` 模式（`initiated_by_user_id="system"`, category="caller", component="codegraph"）。

### §7 快照/回放兼容 [VERIFIED: 代码实读 `repo_router_v2._build_snapshot`, `repo_router_replay.py`, 105-07-SUMMARY]

- 现状：`snapshot = {stage0: {query, node_hits[最小字段集: node_id/repository_id/score/node_path/activity_facet]}, stage1, candidates[to_dict], versions: {weight_set_version, index_version, prompt_hash?, model_id?}}`。`_h_route`（`builtin_processes.py`）组装 payload 整体过 `redact_for_ledger` 落 `ConvergenceSessionEvent`（复用 `repo.routing` 事件名）。**64KB 体积护栏测试存在**（50 hits 满配 <64KB）——新增字段后须复核。
- **Phase 106 快照必须新增**：(a) `versions.weight_set_version` 换真实版本 + 快照携带**生效权重与常数的完整值**（建议 `versions.weights` 或独立 `weight_config` 节）；(b) per-repo `repo_meta`（n_r、last_commit_at、dense_cos_max、各 facet 匹配分+来源层 T1/T2/缺失）——**T2 余弦与 DB 聚合离线不可重算，必须以数据形式记录**（与 Stage 1 排列记录同一设计模式：LLM/外部 I/O 的产物记录为数据，回放消费数据）。
- **replay 改造**：`replay_route_from_snapshot` 增加从 payload 读权重/常数/repo_meta；**105 旧快照回退策略实现位置就在这里**——检测 `versions.weight_set_version == "phase105-v1"`（或缺 weights 节）→ 用 `PHASE105_WEIGHTS` + 旧三信号路径重算，diff 输出标注「旧版本快照，按当时版本比对」（research §6.2-9：版本不同即不可比，不做跨版本换算）。`verify_snapshot_replay` 比对键（repo_id/score/breakdown/confidence）不变，breakdown 键集合比对天然覆盖新信号。
- `_rebuild_hits` 需扩展还原完整 facets（现在只还原 `活跃度`）——或改为 repo_meta 直接携带 facet 匹配分后 hits 无需 facets（推荐后者，快照更小）。

### §8 golden set 门禁与 fixture 扩展 [VERIFIED: 代码实读 `test_repo_router_golden.py`, `repo_router_eval.py`, `golden_main.json`, `golden_baseline.json`]

- fixture 现状：`golden_main.json` 14 条（+`golden_holdout.json` 封存 6 条，门禁绝不加载），case 形状 `{id, _notice, query, label_source, cross_group, expected_repos, node_hits}`；hit payload 只有 `node_id/repository_id/repo_name/node_path/facets`，且 facets 大多只有 `活跃度`。baseline：Recall@5=0.9643、Top-1=13/14、误自动选中率=0.0、`weight_set_version="phase105-v1"`。
- **主 fixture 是手工维护的合成数据**（gk-001 `_notice` 注明「场景合成重写」「预期由 Phase 106 pivoted normalization 翻转」）；`GENERATE_GOLDEN=1` 只重建 **baseline**（指标 JSON），不生成 node_hits。`tests/codegraph/_generate_golden_fixtures.py` 是 layered_search 的生成器，与 repo_router golden 无关。
- **fixture 必须扩展的字段（离线评估新公式的关键）**：
  1. hit 级：`payload.facets` 补全五维（业务线/产品线、技术栈、团队归属、关键程度、活跃度）——gk-001 的 study-app/onion-learning 需按 `_notice` 设定合理值；
  2. case 级：新增 `repo_meta`（或同名结构）：`{repo_id: {n_r, last_commit_at, dense_cos_max?}}`——gk-001 按示意值 N_r(study-app)≈620、N_r(onion-learning)≈30、N̄≈60（research §2.4）；
  3. case 级：`scored_at`（固定时间戳，活跃度衰减确定性）与（若权重非默认）`weight_overrides`。
  4. T2 匹配分：harness 离线走 **T1-only**（别名词典本身随 fixture/常量可 import，确定性）；或 fixture 直接内联 per-facet 匹配分。推荐 T1-only + 可选内联 override——机制断言不依赖 T2。
- **门禁翻转流程**：`WEIGHT_SET_VERSION` 升为 `"phase106-v1"` → 版本守护断言强制 `GENERATE_GOLDEN=1 uv run pytest tests/codegraph/test_repo_router_golden.py -q` 重建 baseline → `git diff` 人工 review 逐例 diff → 核对 Recall@5 ≥ 0.9643、Top-1 ≥ 13（gk-001 翻转应使 Top-1=14/14）、误自动选中率 ≤10%。
- **机制级断言写在** `test_repo_router_golden.py`（现有 `test_gk001_expected_repos_recalled_into_candidates` 处扩展/新增）：`breakdown` 断言 `breadth(study-app) <= breadth(onion-learning)`、`rank(onion-learning) < rank(study-app)`、跨组样本进 Top-5。`evaluate_cases` 签名需接受 weights/constants/repo_meta 透传。
- 时间预算：全量评估硬断言 <10s（`--disable-socket` 下零网络）——新信号是纯算术，无风险。

### §9 别名词典：无既有基建，从零最小形态 [VERIFIED: 全库 rg "别名|同义词|synonym|alias" 无相关命中]

学习案例/知识库均无同义词/别名设施。最小形态建议（Claude's Discretion 范围，供 planner 选）：

- 结构：`{facet_dim: {canonical_value: {"aliases": [...], "parent": str|None}}}`——alias 命中 1.0、parent（上位类目）命中 0.6。
- 存放：**代码常量模块起步**（如 `repo_router_metadata.py` 内 `DEFAULT_ALIAS_DICT`，纯函数可 import、golden harness 确定性）+ SystemSetting 键 `repo_router.alias_dict` 覆盖（运维可补条目，loader 合并，快照记录生效词典 hash 保回放确定性）。纯 fixture 存放不利于生产维护；纯 SystemSetting 让 golden harness 依赖 DB——双轨合并两全。
- 初始条目：从 `FacetVocabulary.values`（语义分面闭集）+ 事实分面枚举生成骨架，人工补同义词（生产词表内容 deferred，同 O-2 纪律）。
- T1 匹配算法：需求文本子串/分词包含匹配（中文短语直接 `in` 即可起步；不引分词库——零依赖约束）。

### §10 前端 breakdown 标签 [VERIFIED: 代码实读 `web/src/components/chat/RoutingDecisionPanel.vue:81-89`]

- `SIGNAL_LABELS` 是**组件内硬编码 map**（非 vue-i18n）：`{text: '文本相关', breadth: '命中广度', activity: '活跃度'}`；未知 key 回退英文原名——新信号零改动可展示，但需补中文：`domain: '业务域匹配'`、`stack: '技术栈匹配'`、`team: '团队归属'`、`criticality: '关键程度'`（若进 breakdown）。有配套测试 `RoutingDecisionPanel.test.ts` 需同步。
- 前端有 Σbreakdown≈score 容差校验（console.warn），重归一化后仍成立，无需改。
- 「facet 分数来源层 T1/T2/缺失」若要进前端展示需扩 trace 结构——CONTEXT 只要求 trace/breakdown 记录来源层（后端快照/trace 层面即满足），前端展示非必须，建议 Phase 106 只落数据、UI 增强留给 Phase 107 分组呈现一起做。

## Architecture Patterns

### 推荐分层（resolver → scorer）

```
Stage 0 (repo_router_v2, async I/O)
  ├─ hybrid RRF top-50（现状）
  ├─ dense-only top-50（新，+1 Qdrant 往返，复用 query_dense）
  ├─ FileIndex last_commit 聚合（新，1 次 DB 查询，≤12 仓）
  ├─ N_r/N̄ 快照读取（新，SystemSetting 或缓存，离线 command 产出）
  ├─ 元数据 T1/T2 解析（新 resolver：别名词典纯匹配 + facet 向量缓存余弦）
  └─ 权重/常数 loader（settings_service + 校验回退）
        ↓  组装 repo_meta: dict[repo_id, RepoMeta] + weights + constants + now
aggregate_and_score(node_hits, repo_meta=…, weights=…, constants=…, now=…)   ← 纯函数
        ↓  ScoredCandidate(breakdown 7 键) → 排序 → confidence（不变）
snapshot（记录 repo_meta 原值 + 权重常数全值 + weight_set_version）
        ↓
replay / golden harness：从快照/fixture 读同形数据 → 调同一纯函数 → 零网络同结果
```

### Pattern 1: 「外部 I/O 产物记录为数据」（快照回放契约）
**What:** T2 余弦、dense 余弦、DB 聚合值不可离线重算——router 解析后以数值形式进快照，replay 直接消费。
**When:** 所有新信号。与 105-07 的 Stage 1 排列记录同构（`repo_router_replay.py` docstring 明文原则）。

### Pattern 2: 「配置 loader 单点 + 参数注入」
**What:** 权重/常数由 router 层一个 loader 读取（get_json_setting + 校验 + 默认回退），纯函数只收参数。θ 阈值（105-01 `_conf_thresholds`）已是同款模式。
**When:** 权重外置。纯函数模块保持"不读任何配置"的模块契约。

### Pattern 3: 专用 JSON 配置端点（`ClaudeCodeConfigView` 先例）
**What:** GET/PUT 单 JSON SystemSetting 键 + 服务端结构校验（Σw=1、离散网格、常数范围）+ IsSuperUser。
**When:** 权重编辑 API。通用 `/api/settings/<key>/` PUT 无校验，不可直接用于权重。

### Anti-Patterns to Avoid
- **在纯函数里读 settings / datetime.now() / 调 embedding**——破坏回放确定性（105 结构保证，回归即事故）。
- **多值 facet sum/mean**——尺寸偏置同构重演（CONTEXT 锁定 max）。
- **缺失补 0**——重归一化是锁定语义；`团队归属` 需求未提团队时必须标不可用，不给 0.5。
- **改既有 breakdown key 名**（text/breadth/activity）——前端映射与快照兼容双重破坏。
- **在通用 settings PUT 上放行未校验权重**——网格与 Σw=1 校验必须后端强制。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 设置缓存与写时失效 | 自建 TTL/进程内缓存 | `settings_service.get_json_setting` + `signals._invalidate_setting_cache` | 已有 60s 缓存 + post_save 失效，保存即生效 |
| dense 查询封装 | 直接在 router 里裸用 client | `QdrantService` 新增 `dense_search_by_name`（照抄 `_verify_cosine` 写法） | 与 `search_by_name`/`hybrid_search_by_name` 同层对称，异常处理/日志一致 |
| facet 向量存储 | 新 DB 表 / 新 Qdrant collection | Django cache + 批量 embedding 预热 | 闭集几百条可重建，建表过度设计 |
| bootstrap CI / 指标 | numpy/scipy | `repo_router_eval.py` 既有 stdlib 实现 | 105 明文禁止引入 numpy/scipy |
| 权重编辑 UI 骨架 | 全新页面/路由 | `admin/index.vue` tab + section 组件（RerankSettings 同款） | 既有设置面模式，零新路由 |

## Common Pitfalls

### Pitfall 1: `关键程度` 闭集不一致
**What goes wrong:** CONTEXT 锚点表有「一般 0.4」，但 `FacetService` 只产 {核心, 重要, 边缘}——若映射表漏「一般」，人工 pin 的「一般」值会掉进"枚举外→信号不可用"分支。
**How to avoid:** CRITICALITY 表四档全保留（外置常数），枚举外值→不可用；SUMMARY 注明事实分面自动值只有三档。

### Pitfall 2: `业务线/产品线` 的 "未分类" 值
**What goes wrong:** 把 "未分类" 当可匹配 facet 值送进 T2 embedding，产生噪声匹配分。
**How to avoid:** resolver 把 `"未分类"`、空串视为信号缺失（重归一化），写测试锁定。

### Pitfall 3: `技术栈` 单字符串多值
**What goes wrong:** 对 `"Python/Vue/Go"` 整串做匹配——精确匹配永不命中、embedding 匹配语义混浊。
**How to avoid:** `split("/")` 成值列表再 `0.8·max+0.2·second_max`。

### Pitfall 4: 活跃度双源冲突
**What goes wrong:** `last_commit_at` 连续值与 facets `活跃度` 枚举同时可用时重复计分或语义打架（如 facets 是旧的"疑似废弃"但最近有 commit）。
**How to avoid:** 优先级明确：有 `last_commit_at` → 连续衰减；`疑似废弃` 封顶 `min(A_act, 0.10)` **无论哪个来源**（CONTEXT：封顶语义接管）；无 timestamp → 枚举回退。真值表写成测试。

### Pitfall 5: 快照体积膨胀突破 64KB 护栏
**What goes wrong:** repo_meta + 权重常数全值 + 补全 facets 让 50-hits 满配快照超 64KB，`test_snapshot_payload_under_64kb_with_50_hits` 红。
**How to avoid:** repo_meta 只记候选仓（≤12）不记全部 hits 仓；facet 匹配分记数值+层级不记原文；实现后跑该测试确认。

### Pitfall 6: dense top-50 与 RRF top-50 集合不重合
**What goes wrong:** 假设每个 RRF 候选仓都能拿到 dense 余弦——实际 dense top-50 可能不含某仓任何节点，`dense_cos_max` 缺失时若默认 0 会把该仓 S_top 打死。
**How to avoid:** 缺失 → 回退该仓 RRF s_hat（并 trace 标注来源），或提高 dense limit；写缺失路径测试。

### Pitfall 7: 权重生效语义与 async 读取
**What goes wrong:** 用 `aget_setting`（无缓存）逐键读 20 个常数 → 每次路由 20 次 DB 查询；或自建长 TTL 缓存 → 保存后不生效。
**How to avoid:** 单 JSON 键 + `sync_to_async(get_json_setting)` 一次读取（60s 缓存 + 信号失效）。

### Pitfall 8: 忘记 bump `WEIGHT_SET_VERSION` 或忘记重建 baseline
**What goes wrong:** 公式变了但版本没变——门禁按旧 baseline 比较出假红/假绿；版本变了没重建——版本守护断言直接红。
**How to avoid:** 版本守护断言已存在（`test_golden_gate_vs_baseline` 首个 assert），流程写进 plan 验证步骤。

### Pitfall 9: 开发库实测数字污染 MEASUREMENTS
**What goes wrong:** 本地空库跑 O-5/O-2 得全 0/无意义分布写进结论，误导常数定版。
**How to avoid:** 沿用 105 数据环境标注纪律——每条结论标 `数据环境: 开发库（结构性结论）` 或 `生产实例（分布实测，deferred）`。

## Code Examples

### 重归一化 + 新信号合成（纯函数核心改造示意）

```python
# Source: 现有 repo_router_scoring.py 模式扩展 + ROUTING-RANKING §2.3/§3.4
# 信号解析（M_j ∈ [0,1] 或 None=不可用），全部来自参数注入
signals: dict[str, float | None] = {
    SIGNAL_TEXT: (1 - lam_share_placeholder, ...),  # 实现拆两键，见 §1
    SIGNAL_BREADTH: breadth,          # log1p(n_eff/denom)/log1p(n_cap), denom=1-b+b*N_r/N_bar
    SIGNAL_ACTIVITY: a_act,           # 0.5**(max(0, Δd-offset)/H), floor/封顶
    SIGNAL_DOMAIN: m_domain,          # T1/T2 匹配分（resolver 注入）
    SIGNAL_STACK: m_stack,            # 0.8*max + 0.2*second_max
    SIGNAL_TEAM: m_team,              # 需求未提团队 → None
}
available = {s: v for s, v in signals.items() if v is not None}
denom = math.fsum(w.get(s, 0.0) for s in available)
breakdown = {s: w.get(s, 0.0) * v / denom for s, v in available.items()}
score = math.fsum(breakdown.values())   # INV-R3 按构造成立
```

### 候选仓 last_commit 一次聚合（router 层）

```python
# Source: facet_service._compute_activity 口径 + Django ORM values/annotate
def _load_latest_commits(candidate_ids: list[str]) -> dict[str, str | None]:
    from django.db.models import Max
    from repositories.models import FileIndex
    rows = FileIndex.objects.filter(repository_id__in=candidate_ids).values(
        "repository_id"
    ).annotate(latest=Max("last_commit_authored_at"))
    return {str(r["repository_id"]): (r["latest"].isoformat() if r["latest"] else None) for r in rows}
# router: await sync_to_async(_load_latest_commits, thread_sensitive=False)(ids)
```

### 权重 loader（router 层，保存即生效）

```python
# Source: settings_service.get_json_setting + _conf_thresholds 参数注入模式
from asgiref.sync import sync_to_async
from system.settings_service import get_json_setting

WEIGHT_GRID = {0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.55}

async def aload_weight_config() -> dict:
    raw = await sync_to_async(get_json_setting, thread_sensitive=False)(
        "repo_router.weight_config", {}
    )
    return _validate_or_default(raw)  # 非法值 → 代码默认 + warning（观测 best-effort）
```

## Runtime State Inventory

非 rename/refactor/migration phase——唯一的"存量数据兼容"是 **105 旧快照回放**（§7 已覆盖：`weight_set_version=="phase105-v1"` → 旧权重路径回放，实现位置 `repo_router_replay.py`）。golden baseline JSON 属 git 内文件，`GENERATE_GOLDEN=1` 重建即迁移。无其他运行时状态受影响（Qdrant collection 结构不变、DB schema 不变或仅加 SystemSetting 行）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | dense-only 查询同机延迟 <10ms 量级（qdrant-client ≥1.9 无一次查询双分数途径） | §4 | 延迟不可接受 → 触发 CONTEXT 已锁的 RRF 回退路径，非阻塞 |
| A2 | 生产库 facets 五维覆盖率足以让元数据信号起作用 | §2 | 覆盖率低 → 重归一化自动退化为文本主导（设计已兜底），O-5/覆盖率统计给实数 |
| A3 | 团队归属开放集值可被 T1 别名匹配有效覆盖（T2 对团队名区分度存疑） | §9 | M_team 常年不可用 → 重归一化兜底；O-2 校准会显式判废弃 T2 |
| A4 | 中文短语 `in` 包含匹配足以支撑 T1 起步（不引分词库） | §9 | 召回不足 → 补别名条目即可，不需要换算法 |

## Open Questions

1. **`C_crit` 的实现语义：加性贡献 vs 排序 tie-break**
   - What we know: CONTEXT 同时锁定「权重表含 C_crit 0.05、Σ=1.00、INV-R2/R3」与「仅作同分带内 tie-break（|S_a-S_b|<0.03 时生效）」。两者机械上互斥：加性贡献最大差 ≈0.05 > 0.03，能翻转带外名次；纯 tie-break 则 C_crit 不进 Σbreakdown。
   - What's unclear: research §3.6 原文是「权重上限 0.05，**且建议只作为**同分带内排序依据」——偏向 tie-break。
   - Recommendation: 实现为**排序 tie-break**：加性和不含 C_crit（其余权重经重归一化天然吸收），排序键 `(-round(score,6), -crit_anchor, repo_id)` 仅在量化后同分带（round 到 |Δ|<0.03 语义可用「score 量化到 0.03 粒度桶」或显式带内比较）生效；C_crit 值仍进 trace/breakdown 旁路字段（informational，不计 Σ）。权重表中 0.05 保留在 weight_config 里作为未来切换开关。planner 若选加性方案，需放弃「仅同分带生效」字面语义并在 SUMMARY 记录取舍。
2. **N_r/N̄ 快照的存放与刷新**
   - What we know: N_r 离线取自 Qdrant 计数（measure command 已有逻辑）；N̄ 为中位数；路由时不应逐次 count（12 仓 × exact count 也可接受但慢）。
   - Recommendation: measure command 增加 `--write-snapshot` 把 `{repo_id: n_r}` + median 写 SystemSetting（如 `repo_router.nr_snapshot`）；router loader 带缓存读取；快照缺失时 breadth 退化（b=0 等价路径）并 warning。索引重建后运维重跑 command（或索引完成钩子自动刷新，planner 定）。
3. **生产实测数字（O-1/O-3/O-5/O-2）全部 deferred**
   - What we know: 105-MEASUREMENTS 占位表未回填；本 phase 可按「余弦口径 + b=0.6 初值」推进公式形式，常数定版等生产回填。
   - Recommendation: 106-MEASUREMENTS.md 沿用占位表 + 执行指引模式；把「生产执行 + 回填」列为 UAT 挂账人工步骤。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Qdrant（dev） | dense 查询/N_r 统计的结构性测试 | ✓（测试用内存 Qdrant，`test_measure_repo_index_stats` 先例） | qdrant-client ≥1.9 | 单测全部走内存/mock，无真实实例依赖 |
| Embedding API（dev） | O-2 校准真实余弦 | ✗（开发库通常未配） | — | CONTEXT 已允许：结构性样本定管线，生产校准 deferred |
| 生产实例 friday.yc345.tv | O-1/O-3/O-5/O-2 分布实测 | ✗（人工步骤） | — | 占位表 + deferred 纪律（105 同款） |
| uv / pytest / pnpm | 测试与前端构建 | ✓ | pytest ≥9.0.2, asyncio_mode=auto | — |

**Missing dependencies with no fallback:** 无（全部有降级/deferred 路径）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ≥9.0.2 + pytest-asyncio（`asyncio_mode="auto"`）+ pytest-django + pytest-socket（默认 `--disable-socket`） |
| Config file | `server/pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/codegraph/test_repo_router_scoring.py -q` |
| Full suite command | `cd server && uv run pytest tests/codegraph -q`（收口再跑 `tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py`，105-07 先例 684 passed） |
| Frontend | `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUTE-03 | MaxP+breadth 聚合消除尺寸偏置；gk-001 Top-1 翻转；机制断言 breadth 反向倾斜 | unit + golden gate | `uv run pytest tests/codegraph/test_repo_router_scoring.py tests/codegraph/test_repo_router_golden.py -q` | ✅ 既有文件扩展（fixture 需补字段——Wave 0） |
| ROUTE-04 | 元数据 T1/T2 入分、多值 max、缺失重归一化、来源层记录、"未分类"视为缺失 | unit | `uv run pytest tests/codegraph/test_repo_router_scoring.py -q`（新增 metadata 测试类；resolver 单测新文件） | ❌ resolver 测试文件 Wave 0 |
| ROUTE-05 | 指数衰减 + offset/floor/废弃封顶 + 枚举回退真值表；last_commit 聚合免 N+1 | unit | `uv run pytest tests/codegraph/test_repo_router_scoring.py -q`；聚合查询 `pytest tests/codegraph/test_repo_router_v2_degraded.py -q`（或新文件） | ✅/❌ 部分 Wave 0 |
| ROUTE-06 | 权重 SystemSetting 读写 + Σw=1/网格校验 + 保存即生效 + weight_set_version 进快照 | unit + integration | `uv run pytest tests/system/ tests/codegraph/test_repo_router_replay.py -q` | ❌ 权重 view/loader 测试 Wave 0 |
| INV-R1..R4 | 四不变量性质测试（新 6 信号下重验） | unit | `uv run pytest tests/codegraph/test_repo_router_scoring.py -q` | ✅ 扩展既有 TestInvariants |
| 回放兼容 | 新快照携带权重回放同结果；105 旧快照回退默认值不抛 | unit | `uv run pytest tests/codegraph/test_repo_router_replay.py -q` | ✅ 扩展（旧快照 case 新增） |
| 前端标签 | 新信号中文标签 + 未知 key 回退 | unit (vitest) | `pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 扩展 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/codegraph/test_repo_router_scoring.py -q`（<2s）
- **Per wave merge:** `cd server && uv run pytest tests/codegraph -q`
- **Phase gate:** `tests/codegraph + tests/delivery + tests/services/test_repo_router_adapter.py` 全绿 + golden 门禁（GENERATE_GOLDEN 重建后）Recall@5 ≥ baseline、Top-1=14/14 预期、误自动选中率 ≤10%，然后 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `golden_main.json`（+holdout）fixture 字段扩展：facets 五维补全 + `repo_meta`（n_r/last_commit_at/dense_cos_max）+ `scored_at`——covers ROUTE-03/04/05 的离线可评估性（**关键前置**：无此扩展新公式无法离线验证）
- [ ] `server/tests/codegraph/test_repo_router_metadata.py`（或并入 scoring 测试）——T1/T2 resolver、别名词典、"未分类"/多值/条件信号
- [ ] `server/tests/system/test_repo_router_weight_config.py`——权重 view 校验（Σw=1、网格、非法回退）
- [ ] `measure_repo_index_stats` 扩展（O-5 activity 统计 + N_r 快照写入）的结构性测试扩展（既有 `test_measure_repo_index_stats.py` 模式）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（复用既有 JWT/权限面） | — |
| V4 Access Control | yes | 权重/校准端点 `IsSuperUser`（既有 `permissions.api_permissions`）；绝不放宽到普通用户 |
| V5 Input Validation | yes | 权重 PUT 服务端强校验（Σw=1、离散网格白名单、常数范围、JSON 结构）——DRF serializer/显式校验，拒绝任意 JSON 直写 |
| V6 Cryptography | no（权重非敏感，不加密；embedding key 走既有 `is_encrypted` + `decrypt_value`，本 phase 不新增凭证） | — |

### Known Threat Patterns for 本 phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 恶意/错误权重写入使路由全错或除零 | Tampering / DoS | 服务端网格+Σ校验；loader 侧二次校验非法回退默认（defensive denom guard 已有先例） |
| 快照泄漏需求文本/凭证 | Information Disclosure | 快照整体过 `redact_for_ledger`（105-07 既有，新增字段自动覆盖）；校准 command 异常文本 `redact_secrets_in_text` |
| facet 值/别名词典注入超长文本打爆 embedding | DoS | resolver 侧值长度上限 + 闭集来源（FacetVocabulary/枚举） |
| 日志泄凭证 | Information Disclosure | structlog `redact_credentials` 自动 processor（既有）；新事件 kv 不放原始需求文本全文（截断） |

### 观测埋点自检（LOGGING-SPEC 强制，planner 落 task）
- 新事件：权重加载失败（warning, sampling）、dense 余弦查询耗时（debug, sampling, `duration_ms`）、元数据 resolver 降级（T2→T1, warning 采样）、校准 command started/completed/failed（caller, `initiated_by_user_id="system"`）。
- 全部 `category` + `component`（`repo_router_v2` / `codegraph`）；facet embedding 调用在 `use_call_source(CallSource.EMBEDDING)` 作用域（若 EmbeddingService 未内置则 resolver 包裹）。
- 高频路径（每次路由）禁 INFO——沿用 `repo_router_v2_scored` debug 模式；观测 helper try/except 吞异常。

## Sources

### Primary (HIGH confidence)
- 代码实读（本 worktree）：`server/codegraph/services/repo_router_scoring.py` / `repo_router_v2.py` / `repo_router_replay.py` / `repo_router_eval.py` / `repo_index_tree.py`、`server/repositories/facet_service.py` / `summary_service.py` / `models.py`、`server/system/models.py` / `settings_service.py` / `signals.py` / `views.py` / `urls.py`、`server/services/qdrant_service.py` / `embedding.py`、`server/codegraph/management/commands/measure_repo_index_stats.py`、`server/tests/codegraph/test_repo_router_golden.py` + fixtures、`web/src/components/chat/RoutingDecisionPanel.vue`、`web/src/api/settings.ts`、`web/src/pages/admin/index.vue`
- `.planning/research/ROUTING-RANKING.md`（公式/常数/评估权威来源，其自身引用 SIGIR/ECIR/NAACL 文献链）
- `.planning/phases/105-golden-set/105-MEASUREMENTS.md`（O-3 定论）与 105-01/03/07-SUMMARY

### Secondary (MEDIUM confidence)
- qdrant-client fusion 查询不回传 per-prefetch 分数：105-02 代码级验证 + 内存 Qdrant 结构性测试（`test_measure_repo_index_stats.py`）

### Tertiary (LOW confidence / deferred)
- dense 查询生产延迟、N_r 分布、facets 覆盖率、c_lo/c_hi——全部待生产实测回填（占位纪律）

## Metadata

**Confidence breakdown:**
- 打分核心/快照/golden 扩展面: HIGH — 全部代码实读，105 三个 SUMMARY 交叉印证
- facets/last_commit 数据源: HIGH — 生成方与消费方代码闭环确认；生产覆盖率数字 LOW（deferred）
- SystemSetting/前端落点: HIGH — 模型/service/signal/view/前端组件逐层验证
- dense 余弦路径: HIGH（可行性，O-3 定论）/ MEDIUM（延迟量级，待实测）
- C_crit tie-break 语义: MEDIUM — CONTEXT 内部张力，已列 Open Question 供 planner 裁决

**Research date:** 2026-07-29
**Valid until:** 2026-08-28（内部代码事实，随 105 收口后稳定；生产实测数字另行回填）
