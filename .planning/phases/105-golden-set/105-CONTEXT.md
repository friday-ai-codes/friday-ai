# Phase 105: 编排解锁与评估标尺（确定性置信度 + 分数可拆解 + golden set 门禁） - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐项自动采纳）

<domain>
## Phase Boundary

技术方案编排不再因 Stage 1 失联而永久停摆，且此后每一次排序改动都能被客观判定为改进还是退化——置信度由分数 margin 确定性推导，分数可拆解、可复现、可离线回放，golden set 作为 CI 回归门禁就位。

覆盖需求：RELY-04, ROUTE-07, ROUTE-08, ROUTE-09。

**边界内**：`repo_router_v2` 分数管线重构（去截断/可拆解/稳定排序）、确定性 confidence 推导、快照落 `ConvergenceSessionEvent` 与离线回放、golden set + harness + CI 门禁、Phase 106 公式定版输入实测（N_r 直方图 + dense 余弦可得性）。
**边界外**：完整多信号打分公式（MaxP + pivoted-size breadth + 元数据入分）归 Phase 106；分组呈现与 UI 标注归 Phase 107；Stage 1 rank-swap budget 有界重排归 Phase 107。

</domain>

<decisions>
## Implementation Decisions

### 确定性置信度推导（RELY-04）
- confidence 改为分数 margin 确定性规则（research §1.3a）：`S(1) >= 0.55 且 margin >= 0.08 → high；S(1) >= 0.35 → medium；否则 low`。阈值 θ_abs/θ_rel 外置（SystemSetting 或 settings 常量，golden set 校准后调整）。
- LLM 的 confidence 输出降级为额外输入信号：只允许把边界情形降级（如 high→medium），绝不能把 low 升为 high。Stage 1 完全失联（网关 400 / 连接错误 / 超时三种情形）时系统仍产出 high/medium/low 分级并自动推进。
- `auto_selected` 由确定性 confidence 驱动（`conf == high → auto_selected=True`），不再由 LLM 断言驱动。
- 结果结构新增 `degraded` 标志（Stage 1 未参与时为 True），本 phase 只打数据底座；用户可见的降级标注 UI 归 Phase 107（RELY-03）。

### 分数可拆解与去截断（ROUTE-07）
- 删除 `repo_router_v2.py` 中所有 `min(score, 1.0)` 截断（`_finalize_stage0` 与 Stage 1 候选构造两处）；改用归一化设计保证 `S ∈ [0,1]`：Stage 0 RRF 分做 query-local max 归一（`s_hat = rrf/rrf_max`），合成一律加性。
- 每个候选携带 `breakdown` 字典（信号名 → 贡献值），且 `Σ贡献 == 总分` 恒成立——写成不变量测试（INV-R1/R3：`0 <= S <= 1`、分解和恰等于总分、重归一化后仍成立）。
- 分解同时落两处：`ConvergenceSessionEvent` payload（trace，供回放与逐例 diff）+ 候选 `to_dict()`（供前端展开，Phase 107 消费）。
- 本 phase 打分函数范围：把**现有信号**（文本 max、命中广度、疑似废弃惩罚）重构为可拆解加性形式——废弃惩罚从 `score *= 0.5` 乘性改为对活跃度项封顶（`min(A, 0.10)`）；完整多信号公式（pivoted size normalization、元数据入分、权重表）归 Phase 106，本 phase 不引入新信号。

### 确定性与快照回放（ROUTE-09）
- 稳定 tie-breaking：`sort(key=lambda r: (-round(r.score, 6), r.repository_id))` — 必须先量化（round 6 位）再比较；第二键用不可变 `repository_id`，禁止用 name/path。
- 聚合内部消除浮点顺序依赖：求和前按 `(score desc, node_id asc)` 排序或用 `math.fsum`。
- 快照落 `ConvergenceSessionEvent`（复用既有 append-only 信封，写入只经 `ConvergenceSessionService._emit_event`）：Stage 0 输入与聚合结果、Stage 1 raw prompt/response（必须经 `redact_for_ledger` 脱敏）、每候选分数分解、版本绑定四元组（weight_set_version + prompt_hash + model_id + index_version）。
- LLM 幂等三件套：(1) 输入哈希缓存 `key = sha256(model_id ‖ prompt_template_version ‖ canonical_json(stage0_input) ‖ decode_params)`，TTL 绑定仓库索引版本；(2) LLM 只输出排列（repo_id 有序数组），不输出浮点分数；(3) decode 参数全固定（temperature=0, top_p=1, 固定 seed/max_tokens），候选按 Stage 0 分数降序喂入（固定顺序，位置偏置恒定可复现）。
- 离线 replay 模式：从 `ConvergenceSessionEvent` 快照重建输入、纯函数重算分数与排序，全程零网络调用——与评估 harness 共用同一代码路径。

### golden set 与 CI 门禁（ROUTE-08）
- golden set 形态：版本库内结构化 fixture（YAML 或 JSON，planner 定），每条含需求文本 + 期望仓库集合 + 标签来源（human/weak 分开统计）。必含「高三提分专项」首条真实用例与 ≥2–3 条「正确答案在跨组」的样本（O-4，供 Phase 107 校准 delta）。建立时立刻切出 30% hold-out 封存，记录已开次数。
- 评估 harness：离线纯函数（fixture/快照回放，零网络），全量跑完 < 5s；主指标 Recall@5，次指标 MRR@10，决策指标 Top-1 Accuracy，护栏指标误自动选中率（`count(conf==high AND top1 错) / count(conf==high)`）。不用 nDCG/MAP。
- 门禁规则：`Recall@5 >= baseline`（不允许任何下降）、`Top-1 正确数 >= baseline - 1`（允许 1 例波动）、`误自动选中率 <= 10%`；失败时输出逐例 diff（哪几条变好/变坏、变坏那条的分数分解如何变化）。报告附 bootstrap 95% CI（B=1000）。
- CI 接入：因全量 < 5s，直接作为普通 pytest 测试进默认 suite（随 `.github/workflows/ci.yaml` 既有后端测试 job 自动跑），不单开 job。
- 测试风格：机制级断言优先于结果级断言（锁"尺寸偏置已消除/分解和恒等/排序稳定"这类因果性质，不锁具体名次）。

### Phase 106 公式定版输入实测（success criterion 5）
- 一次性统计脚本（management command 或 harness 附带）：全仓 `repo_index_nodes` 能力树节点数 `N_r` 分布直方图（p50/p90/p99/max，定 `N̄` 与 `b`，O-1）；确认 Stage 0 返回 payload 中 dense 余弦是否可得（决定 MaxP 主干用余弦还是 RRF 分，O-3）。
- 结论落 phase 目录 `105-MEASUREMENTS.md`，作为 Phase 106 planning 的直接输入。

### Claude's Discretion
- fixture 具体格式（YAML vs JSON）、缓存存储介质（DB 表 vs Django cache）、阈值常量外置的具体载体（SystemSetting vs settings.py）由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（started/completed/failed + duration_ms，category=sampling，component=repo_router_v2）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/repo_router_v2.py` — 两阶段路由器本体：`_stage0_node_search`（hybrid RRF，STAGE0_NODE_K=50）→ `_aggregate_by_repo` → `_stage0_candidates`（病理公式 `max_score * (1 + 0.1*min(hits-1,5))` + `DEPRECATED_PENALTY=0.5` 乘性惩罚）→ `_finalize_stage0`/`_stage1_llm_reasoning`（两处 `min(score,1.0)` 截断，line 252/424）。
- `server/delivery/models/convergence_session_event.py` — append-only trace 信封 `{event, session_id, work_item_id?, ts, payload}`，写入单一入口 `ConvergenceSessionService._emit_event`（`server/delivery/services/convergence_session_service.py`）。
- `server/services/process_runtime/repo_router_adapter.py`（82 行）— 编排链消费路由结果的适配层。
- `server/common/logging.py` — `redact_for_ledger` / `redact_secrets_in_text` 脱敏。
- Stage 1 调参已外置 settings（`REPO_ROUTER_STAGE1_TIMEOUT_SECONDS/MAX_CANDIDATES/HITS_PER_REPO`），confidence 阈值可循同一模式。
- 既有 golden 风格测试参考：`server/tests/services/retrieval/test_hybrid_graph_capable_golden.py`。

### Established Patterns
- 结构化日志 structlog kv 事件 + category/component；LLM 调用须赋 `call_source`。
- 测试：pytest + factory-boy + respx，网络隔离（pytest-socket）——离线 harness 天然契合。
- async ORM 走 `sync_to_async`；服务层无状态类方法。

### Integration Points
- `RepoRouterV2.route()` 的调用方：`server/services/process_runtime/repo_router_adapter.py`（编排链）、`server/repositories/route_views.py`、`server/mcp_tools/views.py`（route_repositories）、`server/agents/tools/repo_association_tools.py`。返回结构加字段（breakdown/degraded/confidence 语义变化）需检查各消费方兼容。
- `ConvergenceSessionService._emit_event` — 快照写入唯一入口。
- `.github/workflows/ci.yaml` — 后端测试 job（golden gate 随默认 suite 进入）。

</code_context>

<specifics>
## Specific Ideas

- 全部设计决策以 `.planning/research/ROUTING-RANKING.md`（2026-07-28 调研）为准——该文档给出了公式、常数初值、文献依据与置信度标注；实现时遇到取舍冲突以其 §0 结论速览为准。
- 生产事故锚点：会话 `ccd817d9`（friday.yc345.tv）——Stage 1 降级 → confidence 恒 low → `auto_selected` 恒 false → 编排卡死；`study-app`（62 子应用 monorepo）碾压 `onion-learning` 的误选机制。golden set 首条真实用例即「高三提分专项」。
- 机制级断言示例（research §7.4）：`assert breakdown["study-app"]["breadth"] <= breakdown["onion-learning"]["breadth"]`，不要 `assert result[0].repo == "onion-learning"`。

</specifics>

<deferred>
## Deferred Ideas

- 完整多信号打分公式（MaxP 主干 + pivoted-size-normalized breadth + 元数据入分 + 权重外置 SystemSetting + weight_set_version）→ Phase 106。
- 分组呈现（in_project/global 两组、trust 标注、delta=0.15 迟滞置顶）与降级用户可见 UI → Phase 107。
- Stage 1 有界重排（rank-swap budget K=3、凸组合 α=0.35）→ Phase 107。
- 弱标签扩样脚本（WorkItem→PlanVersion→MR 追溯链挖掘，golden set 20→200+）→ Future（本里程碑不做）。
- Permutation self-consistency（20× 成本）→ 仅留作评估期质量上界参考，不实现。

</deferred>
