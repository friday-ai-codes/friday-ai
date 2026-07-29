# Phase 105: 编排解锁与评估标尺（确定性置信度 + 分数可拆解 + golden set 门禁） - Research

**Researched:** 2026-07-29
**Domain:** 检索排序管线重构 + 离线评估 harness + 事件快照回放（纯代码库内工程，无新外部依赖）
**Confidence:** HIGH（代码现状全部实读验证；设计公式以 ROUTING-RANKING.md 调研为准）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**确定性置信度推导（RELY-04）**
- confidence 改为分数 margin 确定性规则（research §1.3a）：`S(1) >= 0.55 且 margin >= 0.08 → high；S(1) >= 0.35 → medium；否则 low`。阈值 θ_abs/θ_rel 外置（SystemSetting 或 settings 常量，golden set 校准后调整）。
- LLM 的 confidence 输出降级为额外输入信号：只允许把边界情形降级（如 high→medium），绝不能把 low 升为 high。Stage 1 完全失联（网关 400 / 连接错误 / 超时三种情形）时系统仍产出 high/medium/low 分级并自动推进。
- `auto_selected` 由确定性 confidence 驱动（`conf == high → auto_selected=True`），不再由 LLM 断言驱动。
- 结果结构新增 `degraded` 标志（Stage 1 未参与时为 True），本 phase 只打数据底座；用户可见的降级标注 UI 归 Phase 107（RELY-03）。

**分数可拆解与去截断（ROUTE-07）**
- 删除 `repo_router_v2.py` 中所有 `min(score, 1.0)` 截断（`_finalize_stage0` 与 Stage 1 候选构造两处）；改用归一化设计保证 `S ∈ [0,1]`：Stage 0 RRF 分做 query-local max 归一（`s_hat = rrf/rrf_max`），合成一律加性。
- 每个候选携带 `breakdown` 字典（信号名 → 贡献值），且 `Σ贡献 == 总分` 恒成立——写成不变量测试（INV-R1/R3：`0 <= S <= 1`、分解和恰等于总分、重归一化后仍成立）。
- 分解同时落两处：`ConvergenceSessionEvent` payload（trace，供回放与逐例 diff）+ 候选 `to_dict()`。本 phase 含**最小前端展开**：用户在路由结果里展开任一候选可见各信号贡献值且和恰等于总分（success criterion 2）；完整分组呈现/跨组标注/降级标注 UI 归 Phase 107。
- 本 phase 打分函数范围：把**现有信号**（文本 max、命中广度、疑似废弃惩罚）重构为可拆解加性形式——废弃惩罚从 `score *= 0.5` 乘性改为对活跃度项封顶（`min(A, 0.10)`）；完整多信号公式（pivoted size normalization、元数据入分、权重表）归 Phase 106，本 phase 不引入新信号。

**确定性与快照回放（ROUTE-09）**
- 稳定 tie-breaking：`sort(key=lambda r: (-round(r.score, 6), r.repository_id))` — 必须先量化（round 6 位）再比较；第二键用不可变 `repository_id`，禁止用 name/path。
- 聚合内部消除浮点顺序依赖：求和前按 `(score desc, node_id asc)` 排序或用 `math.fsum`。
- 快照落 `ConvergenceSessionEvent`（复用既有 append-only 信封，写入只经 `ConvergenceSessionService._emit_event`）：Stage 0 输入与聚合结果、Stage 1 raw prompt/response（必须经 `redact_for_ledger` 脱敏）、每候选分数分解、版本绑定四元组（weight_set_version + prompt_hash + model_id + index_version）。
- LLM 幂等三件套：(1) 输入哈希缓存 `key = sha256(model_id ‖ prompt_template_version ‖ canonical_json(stage0_input) ‖ decode_params)`，TTL 绑定仓库索引版本；(2) LLM 只输出排列（repo_id 有序数组），不输出浮点分数；(3) decode 参数全固定（temperature=0, top_p=1, 固定 seed/max_tokens），候选按 Stage 0 分数降序喂入（固定顺序，位置偏置恒定可复现）。
- 离线 replay 模式：从 `ConvergenceSessionEvent` 快照重建输入、纯函数重算分数与排序，全程零网络调用——与评估 harness 共用同一代码路径。

**golden set 与 CI 门禁（ROUTE-08）**
- golden set 形态：版本库内结构化 fixture（YAML 或 JSON，planner 定），每条含需求文本 + 期望仓库集合 + 标签来源（human/weak 分开统计）。必含「高三提分专项」首条真实用例与 ≥2–3 条「正确答案在跨组」的样本（O-4，供 Phase 107 校准 delta）。建立时立刻切出 30% hold-out 封存，记录已开次数。
- 评估 harness：离线纯函数（fixture/快照回放，零网络），全量跑完 < 5s；主指标 Recall@5，次指标 MRR@10，决策指标 Top-1 Accuracy，护栏指标误自动选中率（`count(conf==high AND top1 错) / count(conf==high)`）。不用 nDCG/MAP。
- 门禁规则：`Recall@5 >= baseline`（不允许任何下降）、`Top-1 正确数 >= baseline - 1`（允许 1 例波动）、`误自动选中率 <= 10%`；失败时输出逐例 diff（哪几条变好/变坏、变坏那条的分数分解如何变化）。报告附 bootstrap 95% CI（B=1000）。
- CI 接入：因全量 < 5s，直接作为普通 pytest 测试进默认 suite（随 `.github/workflows/ci.yaml` 既有后端测试 job 自动跑），不单开 job。
- 测试风格：机制级断言优先于结果级断言（锁"尺寸偏置已消除/分解和恒等/排序稳定"这类因果性质，不锁具体名次）。

**Phase 106 公式定版输入实测（success criterion 5）**
- 一次性统计脚本（management command 或 harness 附带）：全仓 `repo_index_nodes` 能力树节点数 `N_r` 分布直方图（p50/p90/p99/max，定 `N̄` 与 `b`，O-1）；确认 Stage 0 返回 payload 中 dense 余弦是否可得（决定 MaxP 主干用余弦还是 RRF 分，O-3）。
- 结论落 phase 目录 `105-MEASUREMENTS.md`，作为 Phase 106 planning 的直接输入。

### Claude's Discretion
- fixture 具体格式（YAML vs JSON）、缓存存储介质（DB 表 vs Django cache）、阈值常量外置的具体载体（SystemSetting vs settings.py）由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（started/completed/failed + duration_ms，category=sampling，component=repo_router_v2）。

### Deferred Ideas (OUT OF SCOPE)
- 完整多信号打分公式（MaxP 主干 + pivoted-size-normalized breadth + 元数据入分 + 权重外置 SystemSetting + weight_set_version）→ Phase 106。
- 分组呈现（in_project/global 两组、trust 标注、delta=0.15 迟滞置顶）与降级用户可见 UI → Phase 107。
- Stage 1 有界重排（rank-swap budget K=3、凸组合 α=0.35）→ Phase 107。
- 弱标签扩样脚本（WorkItem→PlanVersion→MR 追溯链挖掘，golden set 20→200+）→ Future（本里程碑不做）。
- Permutation self-consistency（20× 成本）→ 仅留作评估期质量上界参考，不实现。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RELY-04 | Stage 1 完全失联时，系统仍能给出可用的置信度分级并自动推进——置信度由分数 margin 确定性推导，LLM 判断降为输入而非决策者 | §2 现状解剖定位了死锁的三个代码点（`_finalize_stage0` 恒 low / `auto_selected` 只由 LLM 首位 high 驱动 / `clarify_adapter` 默认 policy「无 high/medium → 需澄清」）；§3 给出 Stage 1 三种失联情形在现有代码中的落点与测试模拟方式 |
| ROUTE-07 | 每个候选的分数可展开到各信号的贡献值 | §2 定位两处 `min(score,1.0)`（line 252/424）与病理聚合公式（line 217-218）；§4 消费方矩阵证明加字段是 additive-safe；§8 前端落点（`RoutingDecisionPanel.vue` + `RepositoryRelevanceCandidate` pydantic 模型） |
| ROUTE-08 | golden set 回归门禁 | §7 测试基建（pytest 默认 `--disable-socket`、golden 测试既有 idiom、CI server-ci job 默认 suite 即门禁）；§5 harness 与 replay 共用纯函数路径的结构建议 |
| ROUTE-09 | 同需求+同索引状态重复路由结果完全相同；快照可离线回放 | §2 定位现有排序无 tie-breaker；§6 `ConvergenceSessionEvent` 写入契约 + event taxonomy 守护测试的扩展要求；§9 缓存与版本绑定的现有基建（Django cache / `built_at` payload 字段） |
</phase_requirements>

## Summary

本 phase 是纯代码库内的工程重构 + 测试基建建设，**不需要任何新外部依赖**。三个核心事实决定了 plan 的形状：

1. **死锁机制已完整定位**。`RepoRouterV2.route()` 在 Stage 1 任意失败时走 `_finalize_stage0`，该函数把每个候选硬编码为 `confidence="low"`（repo_router_v2.py:253），且 `auto_selected` 只在「LLM 候选首位 confidence==high」时为 True（line 154）。下游 `clarify_adapter.py` 的默认 policy 是「routing 候选无任一 high/medium → 需澄清」——三者串联即生产事故链。修复点集中在 `repo_router_v2.py` 单文件 + 阈值常量外置，下游 policy 代码无需改动（它读的是 confidence 字段，语义修复后自动解锁）。

2. **返回结构加字段是 additive-safe，但消费方比 CONTEXT 列出的多**。`RepoRouterV2.route()` 共有 8 个直接调用方（编排 adapter、REST 路由视图、MCP route_repositories、chat 相关性路由、repo 关联服务、知识源 artifact、skill steps、space tools），全部按具名字段读取（`c.score / c.confidence / c.reasoning`），新增 `breakdown`/`degraded` 不破坏任何一方；但 `confidence` 语义变化会改变 `clarify_adapter`（澄清触发）、`feature_confirm_questions`（确认题）、`research_adapter`（深入调研筛选）的行为——这正是本 phase 的目的，plan 里要为这三处写行为级回归测试。

3. **O-3 的答案在代码里已经可读**：`QdrantService.hybrid_search_by_name` 用 Qdrant `FusionQuery(fusion=RRF)` 查询，返回的 `score` 是 RRF 融合分，**dense 余弦不在返回结构中**（Qdrant fusion 查询不回传 per-prefetch 原始分）。要拿余弦需要单独发一次 dense-only 查询（`search_by_name` 已存在，返回 COSINE 距离分）。105-MEASUREMENTS.md 应记录这一结论 + 单独 dense 查询的延迟代价，供 Phase 106 决定 MaxP 主干口径。

**Primary recommendation:** 按「纯函数打分核心（可从 dict 输入重算）→ 路由器接线 → 快照落盘 → harness/golden set → 前端最小展开」分层实施；打分核心与 harness 共用同一模块，从第一天起就零网络可测。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 分数聚合/归一/分解（纯函数） | Backend 服务层（`server/codegraph/services/`） | — | 必须是无 I/O 纯函数才能被 harness 离线复用 |
| 确定性 confidence 推导 | Backend 服务层（同上） | — | margin 规则是打分核心的一部分 |
| 阈值/常量外置 | Backend 配置层（`settings.py` env 变量） | SystemSetting（Phase 106 权重表再上） | Stage 1 调参已有 `REPO_ROUTER_STAGE1_*` env 先例（settings.py:328-333） |
| 快照写入 | Backend 编排层（`_h_route` / `ConvergenceSessionService._emit_event`） | — | 事件写入单一入口约束（INV-6）；只有编排链有 session 上下文 |
| LLM 输入哈希缓存 | Backend 服务层（Django cache） | — | CACHES 已配 Redis/LocMem 双轨（settings.py:199-231） |
| golden set + harness | 测试层（`server/tests/` + fixture 目录） | — | pytest 默认 suite 即 CI 门禁 |
| N_r 直方图/余弦可得性实测 | management command（`server/codegraph/management/commands/`） | — | 既有 `measure_*` 命令先例；需在有真实索引的实例上跑 |
| 最小展开 UI | Frontend（`web/src/components/chat/RoutingDecisionPanel.vue`） | Backend serializer（breakdown 透传） | 现有唯一的路由候选展示组件 |

## Standard Stack

### Core（全部为既有依赖，零新增）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest + pytest-asyncio + pytest-django | pytest>=9.0.2（server/pyproject.toml 锁定） | harness/golden 门禁载体 | `addopts` 默认 `--disable-socket`，离线 harness 天然被强制 |
| Django cache framework | django>=5.1 内置 | LLM 输入哈希缓存 | CACHES 已配置（Redis 优先 / LocMem 回退），conftest 每测试自动 clear |
| structlog | 既有 | 观测埋点 | `category=sampling, component=repo_router_v2` 已在用（repo_router_v2.py:142-143） |
| `math.fsum` / `round` | stdlib | 浮点顺序无关求和 + 量化 tie-break | CONTEXT 锁定 |
| `hashlib.sha256` + `json.dumps(sort_keys=True)` | stdlib | canonical 输入哈希 | 无需第三方 canonical-json 库（输入是自产 dict，控制得住） |
| `random.Random(seed)` | stdlib | bootstrap 95% CI（B=1000） | 20-50 样本 × 1000 次重采样纯 Python 毫秒级，不需要 numpy |

**注意：不要为 bootstrap CI 引入 numpy/scipy**——server 依赖树里没有直接依赖它们，样本量 ≤50 用 stdlib 就足够，引入大依赖违反本 phase「零新增」的最小面。

### 版本/格式选型（Claude's Discretion 项的建议）

| 决策点 | 建议 | 理由 |
|--------|------|------|
| fixture 格式 | **JSON**（非 YAML） | `pyyaml` 不是 server 直接依赖（pyproject.toml 无 yaml 项）；JSON 用 stdlib，且 golden 逐例 diff 输出天然 JSON 化 |
| 缓存介质 | **Django cache**（非 DB 表） | settings 已配 django_redis + LocMem 回退；`doc_sync_cache.py` 有 read-through 先例；DB 表要 migration，杀鸡用牛刀 |
| 阈值载体 | **settings.py + env 覆盖**（`REPO_ROUTER_CONF_THRESHOLD_ABS/REL` 等） | 与既有 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 同模式（settings.py:322-333 + `_stage1_conf()` 调用时读取）；SystemSetting 留给 Phase 106 的权重表（那才需要不发版可调 + weight_set_version） |

## Package Legitimacy Audit

本 phase **不安装任何新外部包**。所有实现使用既有依赖（pytest/Django/structlog/stdlib）。无需 slopcheck 验证。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## 现状解剖：`repo_router_v2.py` 分数管线（§2）

### 执行流（520 行单文件，全部实读）

```
route(query, top_k=3, repository_ids, use_llm=True)
├── _stage0_node_search(query, repository_ids)
│     sparse encode → dense embed → QdrantService.hybrid_search_by_name(
│         COLLECTION_NAME="repo_index_nodes", top_k=STAGE0_NODE_K=50)
│     返回 [{"id", "score"(RRF 融合分), "payload"}]；无命中 → _fallback_v1
├── _aggregate_by_repo(node_hits)
│     按 payload.repository_id 分桶；桶内 sort(key=score, reverse=True)
│     ⚠️ 无 tie-breaker（等分节点顺序依赖 Qdrant 返回序）
├── _stage0_candidates(repo_buckets, top_k=STAGE0_REPO_K=12)
│     score = max_score * (1 + 0.1 * min(hits-1, 5))     # 病理公式 line 217-218
│     facets["活跃度"]=="疑似废弃" → score *= DEPRECATED_PENALTY(0.5)  # 乘性惩罚 line 221-222
│     scored.sort(key=lambda x: x["score"], reverse=True)  # ⚠️ 无 tie-breaker line 233
├── use_llm=False → _finalize_stage0 → router_version="v2_stage0_only", auto_selected=False
├── _stage1_llm_reasoning(...)  失败（任意异常）→ 降级 _finalize_stage0
│     ProviderMissingError → None（warning: reason="provider_missing"）
│     无模型名 → None（reason="no_model_configured"）
│     asyncio.wait_for 超时 / 网关 400 / 连接错误 → 异常冒泡到 route() 被 except 捕获
│     LLM 输出不可解析 → None（reason="unparsable_llm_output"）
└── auto_selected = llm_candidates[0].confidence == "high"    # line 154，仅 LLM 路径可为 True
```

### 必改代码点清单（行号为当前 HEAD）

| 位置 | 现状 | 改动 |
|------|------|------|
| `_finalize_stage0` line 252 | `score=min(c["score"], 1.0)` | 删截断；score 来自归一化管线 |
| `_finalize_stage0` line 253 | `confidence="low"` 硬编码 | 改为确定性 margin 推导 |
| `_stage1_llm_reasoning` line 424 | `score=min(float(base["score"]), 1.0)` | 删截断 |
| `_stage0_candidates` line 217-218 | `max_score * (1 + 0.1*min(hits-1,5))` 乘性 | 重构为加性可拆解（本 phase 只重构现有 3 信号：文本 max、命中广度、废弃惩罚→活跃度封顶） |
| `_stage0_candidates` line 221-222 | `score *= 0.5` 废弃惩罚 | 改为对活跃度项封顶 `min(A, 0.10)` |
| `_stage0_candidates` line 233 / `_aggregate_by_repo` line 204 | `sort(reverse=True)` 无 tie-break | `key=lambda r: (-round(score, 6), repository_id)`；聚合求和用 `math.fsum` 或先按 `(score desc, node_id asc)` 排序 |
| `route()` line 154 | `auto_selected` 由 LLM 首位 high 驱动 | 由确定性 confidence 驱动，所有路径（含降级）一致 |
| `RepoRouteCandidateV2` / `to_dict()` line 74-84 | 无 breakdown | 加 `breakdown: dict[str, float]`（进 to_dict） |
| `RepoRouteResultV2` line 87-94 | 无 degraded | 加 `degraded: bool`（Stage 1 未参与 = True；`v2_stage0_only`/`v1_fallback` 均 True） |
| `_stage1_llm_reasoning` line 380 | `model.ainvoke([system, human])` 无 decode 参数固定 | temperature=0/top_p=1 固定（见 Open Questions Q2：`build_chat_model` 未暴露 temperature 形参） |
| `_stage1_llm_reasoning` line 412-414 | LLM 输出 confidence 字段直接采信 | LLM 改为输出排列 + 可选降级建议；confidence 只能降不能升 |

### Stage 1 失联的三种情形与现有代码路径

| 情形 | 触发点 | 现有行为 | 测试模拟方式 |
|------|--------|---------|-------------|
| 网关 400 | `model.ainvoke` 抛 provider SDK 异常 | route() except 捕获 → 降级 | monkeypatch `build_chat_model` 返回 raise 的 fake（conftest 已有 `fake_chat_model_factory` seam）或 respx 拦 httpx |
| 连接错误 | 同上（httpx ConnectError） | 同上 | 同上；pytest-socket 默认禁网即天然连接错误 |
| 超时 | `asyncio.wait_for(..., timeout)` 抛 `TimeoutError` | 同上 | fake model ainvoke 里 `await asyncio.sleep` 超阈值，或直接 raise TimeoutError |

另有两条「静默 None」路径（provider_missing / no_model_configured / unparsable_llm_output）——同样走 `_finalize_stage0`，确定性 confidence 必须同等覆盖。

### RRF 分数量级（归一化设计的输入事实）

Qdrant `Fusion.RRF` 融合 dense+sparse 两个 prefetch list。单 list rank-1 贡献 ≈ `1/(60+1)` ≈ 0.0164，两 list 都 rank-1 的点上限 ≈ 0.0328。`repo_router_v2.py` 模块 docstring 亦自述 RRF 原始分在 ~0.016 量级。query-local max 归一（`s_hat = rrf/rrf_max`）后 rank-1 恒为 1.0——**这意味着本 phase 的「文本 max」信号在 query 内无绝对强度区分**（ROUTING-RANKING §2.3 已指出），本 phase 接受此局限（跨 query 可比的 MaxP 主干归 Phase 106，取决于 O-3 实测）。

## 消费方矩阵：返回结构变更的兼容面（§4）

`RepoRouterV2.route()` 直接调用方（8 处，全部实读确认字段消费方式）：

| 调用方 | 消费字段 | confidence 语义变化的影响 | breakdown/degraded 新增的影响 |
|--------|---------|--------------------------|------------------------------|
| `server/services/process_runtime/repo_router_adapter.py`（编排链） | 映射为 `{repo_id, confidence, repository_name}` + `router_version/auto_selected` → 落 `session.routing` | **核心受益方**：下游 `clarify_adapter`（无 high/medium → 澄清）、`feature_confirm_questions._repo_confirm_question`、`classify_adapter`、`research_adapter`（按 confidence 筛「需深入」仓）、`recall_adapter` 全部读 `session.routing.candidates[].confidence` | adapter 的精简 dict 需要透传 degraded（供 Phase 107 UI）；breakdown 是否进 session.routing 由 planner 定（trace 里必有） |
| `server/repositories/route_views.py`（POST /api/repositories/route/） | score/confidence/match_reason/sub_project/... 逐字段 | 无破坏 | 加字段即向前端可见 |
| `server/mcp_tools/views.py:434`（route_repositories MCP 工具） | 同上 + auto_selected + RetrievalTrace(kind=ROUTING) 落库 | 无破坏 | trace item 建议带 breakdown |
| `server/agents/tools/repository_relevance.py:216`（chat 会话路由） | confidence→level、score `max(0,min(1,·))` 夹紧、reasoning→evidence；写 `RepositoryRoutingTrace`（前端 RoutingDecisionPanel 数据源） | `selected = high or (medium and score>=threshold)` 行为随 confidence 修复而变化——需回归测试 | **前端最小展开的必经之路**：`RepositoryRelevanceCandidate`（pydantic，`score: Field(ge=0, le=1)`）加可选 `breakdown` 字段 → trace JSON → 前端 |
| `server/initiatives/services/repo_association_service.py`（含 `context_link_service.py`） | `_candidate_dict`：score(round 4)/confidence/reason/matched_node_paths；`use_call_source(AUX_REPO_ROUTER)` 作用域内调 route | RepoAssociation 落库存 confidence 字符串，无破坏 | 加字段 additive-safe |
| `server/knowledge/sources/artifact.py` | route 结果做 artifact 归仓 | 无破坏 | — |
| `server/tools/handlers/skill_steps.py:81` | auto_selected + candidates | auto_selected 语义变化（确定性驱动）方向是「更可用」 | — |
| `server/agents/tools/space_tools.py`、`server/repositories/tree_views.py` | 只读易用字段 | 无破坏 | — |

**关键结论**：新增字段全部 additive-safe（无一处做 dict 键全等断言的生产代码）；既有测试里有 stub `RepoRouteResultV2`/`RepoRouteCandidateV2` 的（`test_repo_router_adapter.py` 等 6 个文件），dataclass 加带默认值的字段不破坏这些构造。

## 快照与事件基建：`ConvergenceSessionEvent` 写入契约（§6）

- **模型**（`server/delivery/models/convergence_session_event.py`）：`{id(UUID), session(FK, CASCADE), event(CharField 64), work_item(UUID 软引用), payload(JSONField), ts, created_at}`；append-only，`ordering=["created_at"]`，索引 `(session, ts)` + `(event)`。
- **写入单一入口**：`ConvergenceSessionService._emit_event(event_name, session, payload)` —— best-effort（异常吞掉只 warning），绝不阻断编排。
- **现有 emit 点**：`_h_route`（`server/services/process_runtime/builtin_processes.py:107-117`）在路由 stage 完成后 emit `EVENT_REPO_ROUTING = "repo.routing"`，当前 payload 只有 `{candidates: [{repo_id, confidence}]}`。**这就是快照的落点**：把 payload 扩充为完整快照（Stage 0 输入与聚合结果、Stage 1 raw prompt/response 经 `redact_for_ledger`、每候选 breakdown、版本四元组），不需要新事件名。
- **event taxonomy 守护测试**（`server/tests/services/test_event_taxonomy_alignment.py`）：断言所有 emit 点引用 `EVENT_*` 常量、常量 ∈ `ALL_EVENTS`、每个事件有 producer。**若 planner 决定新增独立快照事件名**（如 `repo.routing.snapshot`），必须同步改 `event_taxonomy.py`（常量 + ALL_EVENTS + `_EVENT_PRODUCERS` 映射三处）；**复用 `repo.routing` 扩 payload 则零改动**——推荐后者。
- **脱敏**：`redact_for_ledger` 在 `server/interactions/redaction.py:48`（不是 common/logging.py——CONTEXT 里的路径说法不准确，注意 import 路径）。对 nested dict/list/str 全覆盖。Stage 1 raw prompt/response 入 payload 前必经它。
- **会话上下文可及性**：只有编排链（`_h_route` → adapter）有 session。其余 7 个调用方（chat/MCP/REST）无 ConvergenceSession——**快照仅覆盖编排链**；golden set harness 用版本库内 fixture 输入（不依赖快照），replay 模式才消费快照。两者共用同一「纯函数重算」代码路径即可满足 success criterion 3。

## Stage 0 返回结构与 O-1/O-3 实测途径（§5）

### O-3：dense 余弦可得性 —— 代码级答案已明确

`QdrantService.hybrid_search_by_name`（qdrant_service.py:1354-1404）用 `client.query_points(prefetch=[dense, sparse], query=FusionQuery(fusion=RRF))`，返回 `[{"id", "score", "payload"}]`——`score` 是 RRF 融合分，**Qdrant fusion 查询不返回 per-prefetch 的原始 dense 余弦**。要取余弦有两条路（写进 105-MEASUREMENTS.md 供 Phase 106 决策）：

1. 追加一次 dense-only 查询：`QdrantService.search_by_name`（已存在，collection 距离配置 `Distance.COSINE`，返回原始余弦分）——多一次 Qdrant 往返（同机部署 <10ms 量级，量测确认）。
2. Qdrant `query_points` 对每个 prefetch 结果不单独回传分数，无「一次查询同时拿两种分」的官方途径（qdrant-client >=1.9 现状）。

### O-1：N_r 直方图统计途径

- 节点写入方：`RepoIndexTreeBuilder.build`（`server/codegraph/services/repo_index_tree.py:78-189`），payload 含 `repository_id / repo_name / node_id / node_type / node_path / sub_project / depth / facets(JSON str) / built_at(ISO)`。
- `QdrantService` **没有 count/scroll 封装**——统计脚本直接用 `QdrantService.get_client().count(collection_name="repo_index_nodes", count_filter=models.Filter(must=[FieldCondition(key="repository_id", match=MatchValue(value=rid))]), exact=True)` 按仓计数；仓列表从 `Repository.objects.filter(is_deleted=False)` 取。
- 落点：management command（先例：`server/codegraph/management/commands/measure_extractor_precision.py` 等 `measure_*` 系列）。**必须在有真实索引的部署实例（friday.yc345.tv）上执行**，本地开发库无 259 仓数据——plan 里要有一个 human/checkpoint 步骤把实测结果转写进 `105-MEASUREMENTS.md`。
- p50/p90/p99/max 用 stdlib `statistics.quantiles` 即可。

### index_version 的现实口径

payload 里现成的版本信号是 `built_at`（每次 `RepoIndexTreeBuilder.build` 重建时刷新）。快照的「index_version」与 LLM 缓存 TTL 绑定可用「参与候选的各仓 built_at 拼接哈希」或 Repository 行上的索引时间戳字段——planner 按最小改动选口径；不存在现成的全局 index version 单调计数器。

## 缓存 / 阈值外置 / 观测的既有基建（§9）

- **Django cache**：`settings.py:199-231` —— `CACHE_REDIS_URL` 有值走 `django_redis.cache.RedisCache`（`KEY_PREFIX="friday"`, `TIMEOUT=300`, `IGNORE_EXCEPTIONS=True`），否则 LocMemCache。conftest `_clear_throttle_cache` autouse 每测试前后 `cache.clear()`——LLM 输入哈希缓存的测试隔离免费获得。read-through 先例：`server/initiatives/services/doc_sync_cache.py`。
- **阈值外置**：既有模式是 settings 常量 + env 覆盖 + 调用时读取（`_stage1_conf()`，repo_router_v2.py:48-58 + settings.py:322-333）。confidence 阈值 θ_abs/θ_rel 循同一模式加 `REPO_ROUTER_CONF_*` 即可；SystemSetting 侧的 typed helper（`system/settings_service.py` 的 `aget_setting/aget_int_setting` 等）也可用，但 settings+env 更贴近既有 Stage 1 调参惯例。
- **观测**：`CallSource.AUX_REPO_ROUTER = "aux_repo_router"` 已在枚举（`server/agents/call_source.py:58`），LOGGING-SPEC §4.1 已登记（`aux_repo_router` ↔ `repo_router_v2`）。作用域声明用 `use_call_source(CallSource.AUX_REPO_ROUTER)` 上下文管理器（先例：`feature_classify.py:258`）。**现状缺口**：`repo_association_service` 调 route 时已包 call_source 作用域，但编排 adapter 与其它调用方没包——本 phase 改动 Stage 1 调用点时应在 router 内部（`_stage1_llm_reasoning`）统一包一层，消灭调用方遗漏。既有事件名 `repo_router_v2_stage1_completed/failed/skipped`（含 duration_ms/category/component）保持，新增打分与快照事件按同风格补 `repo_router_v2_scored`、`repo_router_v2_snapshot_emitted`（best-effort）。

## 前端最小展开 UI 的落点（§8）

- **唯一现存的路由候选展示组件**：`web/src/components/chat/RoutingDecisionPanel.vue`（chat 消息里的「路由决策」卡片，可折叠、按 score 排序、Badge 显示 `score% + 高/中/低`、Tooltip 显示 evidence）。数据链：`repository_relevance.py` → `RepositoryRoutingTrace.candidates`（JSON） → `useRoutingStore` → panel。
- 编排链（ConvergenceSession）的事件**前端目前完全不消费**（web/src 无 `repo.routing`/convergence 匹配）——所以本 phase 的「用户展开候选仓见 breakdown」只能落在 RoutingDecisionPanel 这条链上。
- 改动面：
  1. 后端 `RepositoryRelevanceCandidate`（`server/agents/tools/schemas/repository_relevance.py:29`，pydantic）加 `breakdown: dict[str, float] = Field(default_factory=dict)`（注意 `score` 有 `le=1.0` 约束——归一化设计天然满足）；`repository_relevance.py` v2 路径把 `c.breakdown` 透传。
  2. 前端 `web/src/types/routing.ts` `RoutingCandidate` 加 `breakdown?: Record<string, number>`；`RoutingDecisionPanel.vue` 每行加展开区显示各信号贡献 + 合计。既有组件测试：`web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts`（vitest + @vue/test-utils），照样式补用例。
- 「和恰等于总分」在前端做展示即可（合计行），恒等性由后端不变量测试保证；前端浮点显示用 `toFixed` 注意舍入后合计观感（建议显示后端 round 过的贡献值并直接显示后端总分，不前端求和）。

## Architecture Patterns

### 推荐模块结构

```
server/codegraph/services/
├── repo_router_v2.py          # 保留：编排接线（Stage 0 检索 I/O、Stage 1 LLM I/O、降级链）
├── repo_router_scoring.py     # 新增：纯函数打分核心（零 I/O、零 ORM、零网络）
│     ├── aggregate_and_score(node_hits: list[dict], θ) -> list[ScoredCandidate]
│     │     # 归一化 → 加性合成 → breakdown → 稳定排序，math.fsum
│     ├── derive_confidence(scores: list[float], θ_abs, θ_rel) -> Confidence
│     ├── apply_llm_adjustment(conf, llm_conf) -> Confidence   # 只降不升
│     └── 常量/阈值从参数注入（settings 读取留在调用方）
server/codegraph/management/commands/
└── measure_repo_index_stats.py  # O-1/O-3 一次性实测（N_r 直方图 + 余弦可得性验证）
server/tests/codegraph/
├── test_repo_router_scoring.py        # 不变量 INV-R1/R3 + margin 规则 + tie-break
├── test_repo_router_v2_degraded.py    # Stage 1 三种失联 → 分级仍产出 + degraded=True
├── test_repo_router_golden.py         # golden set 门禁（进默认 suite 即 CI 门禁）
└── fixtures/repo_router_golden/       # JSON fixture（golden set 本体 + hold-out 标记）
```

**核心原则：打分与 confidence 推导必须是「dict in → dataclass out」的纯函数**，`route()`、replay 模式、golden harness 三者调同一函数。这是 success criterion 3（快照回放零网络同结果）的结构保证。

### Pattern 1: Golden 门禁测试 idiom（沿用既有 golden 测试风格）

既有参照：`server/tests/services/retrieval/test_hybrid_graph_capable_golden.py` + `tests/codegraph/test_layered_search_golden.py` —— fixture 文件入库、`GENERATE_GOLDEN=1` 环境变量重生成、字节级/结构级断言、mock 边界固定在模块 seam。golden 路由门禁沿用该 idiom，但断言对象是指标（Recall@5/Top-1/误自动选中率）+ 机制级性质，不是 byte-equal。

### Pattern 2: Stage 1 失败注入

conftest 已有 `fake_chat_model_factory`（注入 `agents.llm_factory.build_chat_model` seam）与 `mock_aresolve_ok/missing`。Stage 1 失联测试直接 monkeypatch `codegraph.services.repo_router_v2` 内 import 的 `build_chat_model`（注意它是函数内 lazy import——patch 目标为 `agents.llm_factory.build_chat_model`）。

### Pattern 3: 快照 payload 结构（建议形状）

```python
# repo.routing 事件 payload 扩充（经 redact_for_ledger 后写入）
{
  "candidates": [{"repo_id", "confidence", "score", "breakdown": {...}}, ...],
  "router_version": "v2" | "v2_stage0_only" | "v1_fallback",
  "degraded": bool,
  "auto_selected": bool,
  "stage0": {"query": ..., "node_hits": [...精简: node_id/repository_id/score/node_path...]},
  "stage1": {"prompt": <redacted>, "response": <redacted>, "model_id": ..., "skipped_reason": ...},
  "versions": {"weight_set_version": "phase105-v1", "prompt_hash": sha256(...),
               "model_id": ..., "index_version": <participating repos built_at hash>},
}
```

### Anti-Patterns to Avoid

- **在 `_emit_event` 之外写 ConvergenceSessionEvent**：违反 INV-6（写入单一入口），且守护测试会拦裸字符串事件名。
- **golden 断言锁具体名次**：用机制级断言（`breakdown["study-app"]["breadth"] <= breakdown["onion-learning"]["breadth"]`），CONTEXT 明确要求。
- **把 confidence 推导散落在调用方**：`repository_relevance.py` 已有一份「confidence→selected」的映射逻辑，不要再增第二份 margin 实现——推导只在 scoring 模块一处。
- **快照存全量 node payload**：50 个 hit 每个带 summary/keywords 会让 payload 膨胀；存重算所需最小字段集（score/node_id/repository_id/facets 活跃度/node_path）。
- **测试里真连 Qdrant**：默认 `--disable-socket`；需要真检索行为时用 `QdrantClient(":memory:")` + monkeypatch `QdrantService.get_client`（先例 `test_milestone_e2e_learning_case.py:104-105`）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| trace 事件持久化 | 新表/新写入口 | 既有 `ConvergenceSessionEvent` + `_emit_event` | append-only 信封 + 守护测试已就位 |
| 脱敏 | 自写正则 | `interactions.redaction.redact_for_ledger` | 双保险（字段名 + 值模式 + friday_pat 兜底），contract 锁定 |
| 缓存 | 自建 DB 缓存表 | Django cache（Redis/LocMem 已配） | IGNORE_EXCEPTIONS=True 已符合「观测不反噬业务」 |
| LLM 失败注入 | 自写 fake provider | conftest `fake_chat_model_factory` seam | 全仓统一 seam，checkpoint 静态扫描保护 |
| 内存向量库 | mock 每个 Qdrant 方法 | `QdrantClient(":memory:")` | qdrant-client 官方本地模式，行为等价 |
| 分位数 | numpy | `statistics.quantiles` | 零新依赖 |

**Key insight:** 本 phase 的全部基础设施（事件信封、脱敏、缓存、LLM seam、golden idiom、网络隔离）在代码库里都已存在且有守护测试——plan 的价值在正确复用，不在新建。

## Common Pitfalls

### Pitfall 1: 改 confidence 语义但漏测下游 policy 行为
**What goes wrong:** `clarify_adapter._default_needs_clarification`（routing 无 high/medium → 需澄清）、`feature_confirm_questions._repo_confirm_question`、`research_adapter`（按 confidence 筛深入调研仓）的行为都随 confidence 分布改变。只测 router 单元不足以证明「编排自动推进」。
**How to avoid:** 为「Stage 1 失联 + margin 达标 → clarify policy 判定无需澄清」写一条贯穿 adapter 层的集成测试（mock RepoRouterV2.route 之下、真实 policy 之上）。
**Warning signs:** golden 全绿但 e2e 编排仍卡 clarify。

### Pitfall 2: 破坏既有测试的 stub 构造
**What goes wrong:** 6 个测试文件直接构造 `RepoRouteCandidateV2/ResultV2`。给 dataclass 加**无默认值**字段会全部炸掉。
**How to avoid:** 新字段一律带默认值（`breakdown: dict = field(default_factory=dict)`、`degraded: bool = False`）。

### Pitfall 3: 快照 payload 忘记脱敏或过度存储
**What goes wrong:** Stage 1 prompt 含仓库 summary（可能含敏感串）；raw response 直接入库违反脱敏红线。payload 无界膨胀拖慢 session 查询。
**How to avoid:** 写入前统一过 `redact_for_ledger`；node_hits 存最小字段集；为 payload 大小加一条上限测试（如序列化后 < 64KB）。

### Pitfall 4: golden set < 5s 被 DB/Django 启动吃掉
**What goes wrong:** 若 harness 每例走 ORM/session，50 例 × setup 开销轻松超 5s。
**How to avoid:** harness 主路径不触 DB（纯函数 + JSON fixture 输入）；pytest 用 module-scope fixture 一次性加载 golden set。`<5s` 断言本身写进测试（`time.monotonic` 包裹全量评估，宽松阈值防 CI 抖动误报，比如断 <10s、目标 <5s 记 log）。
**Warning signs:** 本地 2s、CI 8s。

### Pitfall 5: tie-break 未先量化
**What goes wrong:** 直接 `sort(key=-score)`，两个数学等值但浮点表示差 1e-17 的分数在不同求和顺序下顺序翻转。
**How to avoid:** CONTEXT 锁定 `(-round(score, 6), repository_id)`；聚合求和用 `math.fsum`。写一条「打乱 node_hits 输入顺序 100 次结果 byte-equal」的性质测试。

### Pitfall 6: hold-out 封存形同虚设
**What goes wrong:** hold-out 样本和主 set 放同一文件，跑 harness 顺手全跑，封存失效。
**How to avoid:** hold-out 单独文件 + 默认 skip（如 `@pytest.mark.holdout` 且 addopts 排除，或 fixture 带 `holdout: true` 字段被 harness 默认过滤）；文件头记录「已开次数」字段，人工递增。

### Pitfall 7: LLM 缓存污染确定性测试
**What goes wrong:** 输入哈希缓存跨用例残留导致「重复路由同结果」测试假绿（其实是缓存命中不是确定性）。
**How to avoid:** conftest 已每测试 `cache.clear()`；确定性测试要分别断言「缓存命中路径」与「禁缓存路径（直接调纯函数）」两种同结果。

### Pitfall 8: N_r 实测被当成可本地完成的任务
**What goes wrong:** 本地 Qdrant 没有 259 仓真实索引，命令跑出来全是 0，写进 MEASUREMENTS 误导 Phase 106。
**How to avoid:** plan 中把「在生产实例执行 + 转写结果」列为 checkpoint:human-verify 类步骤。

## Code Examples

### 确定性 confidence（纯函数，harness 共用）

```python
# 来源：CONTEXT 锁定规则 + ROUTING-RANKING §1.3a
def derive_confidence(sorted_scores: list[float], *, theta_abs: float = 0.55,
                      theta_margin: float = 0.08, theta_med: float = 0.35) -> Confidence:
    if not sorted_scores:
        return "low"
    s1 = sorted_scores[0]
    margin = s1 - (sorted_scores[1] if len(sorted_scores) > 1 else 0.0)
    if s1 >= theta_abs and margin >= theta_margin:
        return "high"
    if s1 >= theta_med:
        return "medium"
    return "low"

def apply_llm_adjustment(deterministic: Confidence, llm: Confidence | None) -> Confidence:
    order = {"low": 0, "medium": 1, "high": 2}
    if llm is None:
        return deterministic
    return llm if order[llm] < order[deterministic] else deterministic  # 只降不升
```

### 不变量测试（INV-R1/R3）

```python
# 来源：ROUTING-RANKING §4 INV 表 + CONTEXT 机制级断言要求
def test_breakdown_sums_to_total(scored_candidates):
    for c in scored_candidates:
        assert 0.0 <= c.score <= 1.0                                   # INV-R1
        assert abs(math.fsum(c.breakdown.values()) - c.score) < 1e-9   # INV-R3

def test_order_invariant_to_input_shuffle(node_hits):
    base = aggregate_and_score(node_hits)
    for seed in range(100):
        shuffled = random.Random(seed).sample(node_hits, len(node_hits))
        assert aggregate_and_score(shuffled) == base
```

### N_r 统计（management command 核心）

```python
# 来源：qdrant-client count API（qdrant_service.get_client() 直用）
from qdrant_client import models
client = QdrantService.get_client()
counts = {}
for repo in Repository.objects.filter(is_deleted=False):
    counts[str(repo.id)] = client.count(
        collection_name="repo_index_nodes",
        count_filter=models.Filter(must=[models.FieldCondition(
            key="repository_id", match=models.MatchValue(value=str(repo.id)))]),
        exact=True,
    ).count
# statistics.quantiles(list(counts.values()), n=100) → p50/p90/p99
```

### 输入哈希缓存 key（CONTEXT 锁定构成）

```python
key_material = "\x1f".join([
    model_id, PROMPT_TEMPLATE_VERSION,
    json.dumps(stage0_input, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
    json.dumps(decode_params, sort_keys=True),
])
cache_key = f"repo_router_v2:stage1:{hashlib.sha256(key_material.encode()).hexdigest()}"
django_cache.set(cache_key, permutation, timeout=STAGE1_CACHE_TTL)  # TTL 绑定索引版本见 §5
```

## Runtime State Inventory

> 本 phase 属打分管线重构（非 rename），但涉及一处存量数据语义变化，逐项核对：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `RepositoryRoutingTrace.candidates`（历史行无 breakdown）、`RepoAssociation.confidence`（历史行为旧语义 LLM confidence） | 无需迁移——breakdown 为可选字段，前端对缺失回退不展开；confidence 历史行照旧展示 |
| Live service config | 无（阈值走 settings/env，新增默认值） | none — 已核对 settings.py |
| OS-registered state | 无 | none |
| Secrets/env vars | 新增 env（`REPO_ROUTER_CONF_*`）带默认值，缺失不破坏 | 补 `.env.example` 文档 |
| Build artifacts | 无 | none |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LLM 断言 confidence + `auto_selected` | 确定性 margin 推导，LLM 只降不升 | 本 phase | 编排解锁；Stage 1 变成 best-effort 增强 |
| `max_score×(1+0.1×min(hits-1,5))` 乘性 + `min(score,1.0)` 截断 | query-local 归一 + 加性合成 + breakdown | 本 phase | 排序信息不再销毁；Phase 106 公式重构有承接面 |
| 排序改动靠人肉判断 | golden set 回归门禁进默认 pytest suite | 本 phase | 每次排序改动可客观判定 |

**Deprecated/outdated:** `DEPRECATED_PENALTY = 0.5` 乘性常量随重构删除（惩罚改为活跃度项封顶）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Qdrant fusion 查询无法同时回传 per-prefetch 原始分（需单独 dense 查询取余弦）[ASSUMED — 基于 qdrant-client 1.9+ API 形状与现有代码，未逐版本核对官方 changelog] | §5 | 若新版本支持，Phase 106 可省一次查询；measurement command 执行时顺带验证即可，风险极低 |
| A2 | 本地 `QdrantClient(":memory:")` 的 RRF fusion 行为与 server 版一致 [ASSUMED — 既有 e2e 测试依赖此等价性] | §7 | golden fixture 若源自内存模式生成，个别分数可能与生产有微小出入——golden set 输入本就是固化 fixture（非现场检索），不受影响 |
| A3 | 「高三提分专项」真实用例的需求文本与期望仓集合可从生产会话 `ccd817d9` 追溯获得 [ASSUMED — 会话 id 来自 CONTEXT，未在本库验证其数据可导出] | golden set | 若取不到原文，需人工重写等价用例——需 user/checkpoint 提供 |
| A4 | Stage 1 decode 参数固定需扩展 `build_chat_model`（现签名无 temperature/top_p/seed 形参）[VERIFIED: llm_factory.py:64-75 实读，确认无这些形参；「需扩展」是推断，或可用 langchain `model.bind()`] | §2 | 若各 provider 类不统一支持 bind，则在 build_chat_model 加可选形参（改动面小） |

## Open Questions

1. **Stage 1 decode 参数如何注入（temperature=0/top_p=1/seed）？**
   - What we know: `build_chat_model` 不暴露这些参数；langchain BaseChatModel 通常支持构造 kwargs 或 `.bind()`。
   - What's unclear: 各 provider 分支（anthropic/openai/gemini/ollama）对 seed 的支持不一。
   - Recommendation: planner 安排「扩展 `build_chat_model` 加可选 `temperature/top_p/seed` 透传」小任务；seed 不被支持的 provider 记 debug log 静默忽略（幂等主要靠缓存+排列输出，decode 固定是第三道防线）。
   - **RESOLVED:** 采纳 recommendation——`105-05-PLAN.md` Task 1「build_chat_model 扩展 decode 参数透传」实现可选 `temperature/top_p/seed` 形参（默认 None 零回归面，不支持的 provider 记 `llm_decode_param_ignored` debug log 静默忽略）；Task 2 在 Stage 1 以 `temperature=0.0, top_p=1.0, seed=42` 调用。未走 `.bind()` 路线（provider 支持不统一）。
2. **快照写入点放 `_h_route`（adapter 外）还是 router 内部回调？**
   - What we know: 事件写入必须经 `_emit_event`（只有编排链有 session）；router 本体被 8 方复用。
   - Recommendation: router 返回结构携带完整 trace 材料（breakdown/stage0 摘要/stage1 redacted 材料），`_h_route` 组装 payload 并 emit——router 保持无 session 依赖。
   - **RESOLVED:** 采纳 recommendation——快照材料随 `RepoRouteResultV2.snapshot` 携带（`105-03-PLAN.md` Task 1 组装 stage0 材料 + versions；`105-05-PLAN.md` Task 2 补 stage1 redacted 材料），写入点在 `_h_route`：组装完整 payload 后经 `_emit_event(EVENT_REPO_ROUTING)` 落库（`105-07-PLAN.md` Task 1）。router 保持无 session 依赖。
3. **golden set 首批规模与跨组样本从哪来？**
   - What we know: CONTEXT 要求首条真实用例 + ≥2–3 条跨组样本；弱标签扩样明确 deferred。
   - Recommendation: 首批 10–20 条人工构造（真实事故用例 + 典型仓群），plan 里排一个「样本征集/确认」checkpoint。
   - **RESOLVED:** 采纳 recommendation 的规模与构造策略——`105-04-PLAN.md` Task 2 人工构造 20 条（golden_main.json 14 条 + golden_holdout.json 6 条封存），首条为真实事故用例 `gk-001-gaosan-tifen`（按 ROUTING-RANKING §2.4 数值示意构造），含 ≥2 条 cross_group=true 样本。偏差说明：不排 checkpoint 任务（autonomous 模式），改为在 105-04 SUMMARY 中标注「真实生产样本（会话 ccd817d9 原文）待人工补充替换合成版本」。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest + pytest-socket + respx | harness/门禁 | ✓ | pyproject.toml 锁定（pytest>=9.0.2） | — |
| Django cache（Redis 或 LocMem） | LLM 输入哈希缓存 | ✓ | settings 双轨已配 | LocMem（单进程语义足够，缓存是优化非正确性依赖） |
| Qdrant（真实实例 + 259 仓索引） | 仅 O-1/O-3 实测 command | ✗（本地无生产数据） | — | 在生产实例执行 command（checkpoint 步骤）；开发/CI 全程不需要 |
| vitest + @vue/test-utils | 前端展开 UI 测试 | ✓ | web/package.json | — |

**Missing dependencies with no fallback:** 无（生产实例访问属操作步骤而非依赖缺失）。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >= 9.0.2 + pytest-asyncio（asyncio_mode=auto）+ pytest-django；前端 vitest ^4 |
| Config file | `server/pyproject.toml [tool.pytest.ini_options]`（addopts 默认 `--disable-socket --allow-unix-socket`）；`web/package.json` |
| Quick run command | `cd server && uv run pytest tests/codegraph/test_repo_router_scoring.py -x` |
| Full suite command | `cd server && uv run pytest`（= CI server-ci job 的原样命令） |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RELY-04 | Stage 1 网关 400/连接错误/超时 三情形下仍产出 high/medium/low 且 degraded=True；LLM confidence 只降不升 | unit | `uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x` | ❌ Wave 0 |
| RELY-04 | 失联 + margin 达标 → clarify policy 判定无需澄清（编排推进） | integration | `uv run pytest tests/services/test_clarify_adapter*.py -k routing -x`（补用例） | ⚠️ 文件存在，补用例 |
| ROUTE-07 | INV-R1/R3：`0<=S<=1`、`Σbreakdown==score`、截断消失 | unit（性质） | `uv run pytest tests/codegraph/test_repo_router_scoring.py -x` | ❌ Wave 0 |
| ROUTE-07 | 前端展开显示各信号贡献 + 合计 | unit（组件） | `cd web && pnpm exec vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ⚠️ 文件存在，补用例 |
| ROUTE-08 | golden 门禁：Recall@5>=baseline / Top-1>=baseline-1 / 误自动选中率<=10% + 逐例 diff + <5s | unit（golden） | `uv run pytest tests/codegraph/test_repo_router_golden.py -x` | ❌ Wave 0 |
| ROUTE-09 | 同输入重复两次 byte-equal（Stage 1 可用/不可用）；输入乱序 100 次同结果；快照 replay 零网络同结果 | unit（性质 + replay） | `uv run pytest tests/codegraph/test_repo_router_scoring.py tests/codegraph/test_repo_router_replay.py -x` | ❌ Wave 0 |
| SC-5 | O-1/O-3 实测落 105-MEASUREMENTS.md | manual-only（生产实例执行 command + 转写） | `uv run python manage.py measure_repo_index_stats`（在部署实例） | ❌ Wave 0（command 本体）+ human 步骤 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/codegraph/ -x`（scoring/degraded/golden/replay 子集，秒级）
- **Per wave merge:** `uv run pytest`（全量默认 suite）+ `cd web && pnpm exec vue-tsc --noEmit && pnpm exec vitest run`（涉前端 wave）
- **Phase gate:** server 全量 + web 全量 green；golden 门禁属默认 suite 自动含入

### Wave 0 Gaps
- [ ] `tests/codegraph/test_repo_router_scoring.py` — INV-R1/R3、margin 规则、tie-break、乱序性质（REQ ROUTE-07/09）
- [ ] `tests/codegraph/test_repo_router_v2_degraded.py` — 三种失联 + degraded + 只降不升（REQ RELY-04）
- [ ] `tests/codegraph/test_repo_router_golden.py` + `tests/codegraph/fixtures/repo_router_golden/*.json` — 门禁 + 逐例 diff + bootstrap CI（REQ ROUTE-08）
- [ ] `tests/codegraph/test_repo_router_replay.py` — 快照重建 → 纯函数重算 → 同结果（REQ ROUTE-09）
- [ ] 框架安装：无需（全部既有）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 不改任何入口鉴权 |
| V3 Session Management | no | — |
| V4 Access Control | no | 事件读取沿用既有 session 归属查询 |
| V5 Input Validation | yes（有限） | golden fixture 是库内静态文件；REST 入口已有 serializer 限长（route_views.py `max_length=1000/top_k<=10`），不动 |
| V6 Cryptography | no | sha256 仅作缓存 key，非安全用途 |

### Known Threat Patterns for 本 phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Stage 1 prompt/response 含敏感串入库 | Information Disclosure | 写 payload 前必经 `interactions.redaction.redact_for_ledger`（contract 锁定）；测试断言快照中无 `sk-` 等模式 |
| 快照 payload 无界膨胀（DoS-ish） | Denial of Service | node_hits 存最小字段集 + payload 大小上限测试 |
| LLM 编造 repo_id 进入排列 | Tampering | 既有防线保留（`by_id.get(rid) is None → 丢弃`，repo_router_v2.py:409-411）；排列输出模式下同样白名单校验 |

## Sources

### Primary (HIGH confidence — 全部为本仓库实读)
- `server/codegraph/services/repo_router_v2.py`（全文 520 行）— 病理公式/截断/降级链/auto_selected 逻辑
- `server/services/qdrant_service.py:1354-1437` — hybrid_search_by_name 返回结构（O-3 依据）
- `server/delivery/services/convergence_session_service.py` + `server/delivery/models/convergence_session_event.py` + `server/delivery/services/event_taxonomy.py` + `server/tests/services/test_event_taxonomy_alignment.py` — 快照信封契约与守护
- `server/services/process_runtime/`（builtin_processes/repo_router_adapter/clarify_adapter/feature_confirm_questions/classify_adapter/research_adapter/recall_adapter）— confidence 消费面
- `server/agents/tools/repository_relevance.py` + `schemas/repository_relevance.py` + `web/src/components/chat/RoutingDecisionPanel.vue` + `web/src/types/routing.ts` — 前端落点数据链
- `server/pyproject.toml`、`server/tests/conftest.py`、`.github/workflows/ci.yaml`、`server/tests/services/retrieval/test_hybrid_graph_capable_golden.py`、`server/tests/test_milestone_e2e_learning_case.py` — 测试/CI 基建
- `server/friday/settings.py`（CACHES / REPO_ROUTER_STAGE1_*）、`server/system/models.py + settings_service.py`、`server/interactions/redaction.py`、`server/agents/call_source.py`、`server/agents/llm_factory.py` — 配置/脱敏/观测基建
- `.planning/research/ROUTING-RANKING.md`（2026-07-28）— 公式/常数/文献依据（设计权威，CONTEXT 指定）

### Secondary (MEDIUM confidence)
- qdrant-client Fusion/count API 形状 — 基于既有代码用法推断 + 库内多处一致使用；O-3 结论以 measurement command 现场再验证一次

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- 现状解剖与消费方矩阵: HIGH — 全部文件实读、行号核对
- 快照/事件契约: HIGH — 模型 + 服务 + 守护测试三方交叉验证
- O-3 结论（余弦不可得需单独查询）: MEDIUM-HIGH — 代码级确认 fusion 返回结构，官方 API 逐版本能力未穷举（A1）
- golden set 内容来源（真实用例可追溯性）: MEDIUM — 依赖生产数据可达性（A3）
- 阈值/公式数值: 按 ROUTING-RANKING 标注（形式 HIGH、常数 MEDIUM，golden set 校准）

**Research date:** 2026-07-29
**Valid until:** 2026-08-28（库内事实随 HEAD 变动；ROUTING-RANKING 设计结论长期有效）
