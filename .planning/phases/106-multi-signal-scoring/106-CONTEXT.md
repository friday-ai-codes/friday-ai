# Phase 106: 多信号打分函数重构（尺寸偏置 + 元数据入分 + 活跃度连续 + 权重外置） - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐项自动采纳）

<domain>
## Phase Boundary

路由排序由一个可拆解、无结构性偏袒、不发版可调的多信号打分函数决定——大而全的单体不再因命中节点多而被系统性高估，业务域/技术栈/团队/关键程度/活跃度从"算了给 LLM 看"变成真正参与打分。

覆盖需求：ROUTE-03, ROUTE-04, ROUTE-05, ROUTE-06。

**边界内**：`repo_router_scoring` 纯函数核心扩展（MaxP + breadth 聚合、元数据信号、活跃度连续、缺失重归一化）、权重/常数外置 SystemSetting + weight_set_version、O-2/O-5 实测、golden set 机制级断言与 gk-001 翻转。
**边界外**：分组呈现与 delta 迟滞置顶（Phase 107）；Stage 1 有界重排凸组合（Phase 107）；权重自动调参/在线学习（Future）。

**依赖输入（Phase 105 已产出）**：分数分解/不变量测试底座（`server/codegraph/services/repo_router_scoring.py`）、golden set 门禁（14+6 条，baseline Recall@5=0.9643、gk-001 为预期失败样本待翻转）、105-MEASUREMENTS.md（O-3 定论：fusion 不回传 dense 余弦，需 `client.query_points(using="dense")` 单独查询；O-1 生产分布 deferred，开发库结构性结论可用）。

</domain>

<decisions>
## Implementation Decisions

### 聚合公式与尺寸偏置（ROUTE-03）
- 聚合结构：MaxP 主干 + pivoted-size-normalized 对数饱和 breadth，**加性**合成（research §2.3 三步：n_eff 软计数 p=2 → pivoted denom `1-b+b·N_r/N̄` b=0.6 → `log1p` 饱和 n_cap=6；`S_text=(1-λ)·S_top+λ·breadth` λ=0.25）。
- `N̄` 用全仓能力树节点数**中位数**（抗 monorepo 倾斜）；`N_r` 离线取自 repo_index_nodes 计数（105-02 的 measure command 已有计数逻辑可复用）。N_r/N̄ 快照经 measure command 新增 `--write-snapshot` 写入 SystemSetting，router 走缓存读取（裁决自 106-RESEARCH Open Question 2）。
- MaxP 主干口径（O-3）：优先用单独 dense 查询取余弦（`using="dense"`，105-MEASUREMENTS 已验证可行）+ affine clip 校准；若实现后延迟/成本不可接受，回退 RRF 分 query-local max 归一，取舍记录进 SUMMARY 与代码注释。
- 机制级断言：golden set 用例锁机制（`breakdown["study-app"]["breadth"] <= breakdown["onion-learning"]["breadth"]`、跨组样本进 Top-5）而非偶然名次；gk-001（Top-1=onion-learning）翻转后 `GENERATE_GOLDEN=1` 重建 baseline 并核对 Recall@5 不降、误自动选中率 ≤10%。
- 所有常数（p/b/n_cap/λ/N̄ 快照值）外置，见权重外置节。

### 元数据入分（ROUTE-04）
- 三层匹配：T1 确定性别名词典（facet 值 + 人工同义词表；1.0 精确/别名、0.6 上位类目）→ T2 校准 embedding 余弦（`clip((cos-c_lo)/(c_hi-c_lo),0,1)`，初值 c_lo=0.25/c_hi=0.55，**必须按 O-2 流程实测校准**：200 组负样本 p95→c_lo、30 组正样本 p50→c_hi；`c_hi-c_lo<0.10` 的 facet 放弃 T2 只留 T1）→ T3 LLM 判定**绝不进分数**（只作 Stage 1 解释材料）。
- 多值 facet 取 **max**（技术栈可用 `0.8·max+0.2·second_max`），绝不 sum/mean（尺寸偏置同构重演）。
- 缺失信号：**权重重归一化**（`S=Σ w_j·M_j / Σ w_j`，仅对 present 信号），不补 0；全部元数据缺失时退化为纯文本分数。trace/breakdown 记录每个 facet 分数来源层（T1/T2/缺失）。
- `关键程度` 是静态先验：**不进加性和**，仅作同分带内 tie-break（|S_a-S_b|<0.03 时按锚点 {核心 1.0/重要 0.7/一般 0.4/边缘 0.15} 决序；值走 trace/breakdown 旁路字段展示，不计入 Σ贡献==总分 的恒等式）——裁决自 research §3.6 与 106-RESEARCH Open Question 1。加性权重表因此为 5 信号（text 0.55/domain 0.15/act 0.12/stack 0.08/team 0.05，相对权重经重归一化生效，绝对和无须为 1）。`团队归属` 是条件信号：需求文本未提团队时标**不可用**走重归一化，不给 0.5。
- facet 值 embedding 全量缓存（闭集几百条）；换 embedding 模型必须重校准并把模型 id 写进 weight_set_version。

### 活跃度连续化（ROUTE-05）
- 指数衰减：`A_recency = 0.5^(max(0,(now-last_commit_at).days-offset)/H)`，H=180d、offset=14d、floor=0.05（`A_act=max(A_recency, 0.05)`）。
- `疑似废弃` 惩罚改为对 A_act 封顶：`A_act = min(A_act, 0.10)`——完全落在活跃度项内、可在 breakdown 单独展示（105-03 已把乘性 DEPRECATED_PENALTY 移除，此处接管语义）。
- 无 `last_commit_at` 时回退枚举映射 {活跃开发:0.9, 维护中:0.6, 低频:0.3, 疑似废弃:0.1}。
- O-5 实测：全仓 `last_commit_at` 覆盖率与新鲜度统计（可扩展 105-02 的 measure command），结论落 106-MEASUREMENTS.md（沿用数据环境标注纪律）；覆盖不足的仓自动走枚举回退。

### 权重外置（ROUTE-06）
- 全部权重与常数（6 信号权重 + p/b/n_cap/λ/H/offset/floor/c_lo/c_hi/θ_abs/θ_rel/CRITICALITY 表等）落 `SystemSetting`（复用既有 `SettingKeys`/service 层与加密约定，绝不绕过），附 `weight_set_version` 字符串。
- 权重初值（research §4）：S_text 0.55 / M_domain 0.15 / A_act 0.12 / M_stack 0.08 / M_team 0.05 / C_crit 0.05，Σ=1.00。不变量写成测试：INV-R1 `0≤S≤1` 无截断；INV-R2 元数据权重和 ≤0.5（文本主导，可证明推论落测试）；INV-R3 Σ贡献==总分（重归一化后仍成立）；INV-R4 关任一信号不改其余相对比例。
- 生效语义：保存后下一次路由立即按新值打分（调用时读取 + 短 TTL 进程内缓存均可，planner 定），无需发版/重启。每条路由结果/快照记录 weight_set_version（105 版本四元组已有该位，从占位换成真实版本）。
- 运维界面：优先复用既有系统设置管理面（若已有通用 SystemSetting 编辑器则零新 UI；否则最小表单/JSON 编辑 + 校验 Σw=1 与网格取值），researcher 确认落点。权重取值约束在**离散网格** {0,0.05,0.08,0.10,0.12,0.15,0.20,0.30,0.40,0.55}（防过拟合四道闸之一），后端校验。
- Stage 1 之上的凸组合 `S_ranked=0.65·S_final+0.35·S_llm` 归 Phase 107（有界重排），本 phase 打分函数只产 S_final。

### Claude's Discretion
- 别名词典的初始条目规模与存放形态（fixture/SystemSetting/代码常量）、facet embedding 缓存介质、SystemSetting 键名切分粒度由 planner/executor 按代码库惯例定。
- O-2 校准若开发库缺少真实 facet 数据，允许用结构性样本先定管线并把生产校准记 deferred（同 O-1 纪律）。
- 观测埋点按 LOGGING-SPEC 补齐；新增设置读写走既有权限面。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/repo_router_scoring.py`（105-01）— 纯函数打分核心：加性分解、缺失重归一化已有雏形、fsum/量化 tie-break、margin confidence。本 phase 主要改造点。
- `server/codegraph/services/repo_router_v2.py`（105-03/05 后）— 已接线 breakdown/degraded/快照材料/缓存；`_stage0_candidates` 调用打分核心。
- `server/codegraph/management/commands/measure_repo_index_stats.py`（105-02）— N_r 计数与 dense 余弦探针，可扩展 O-5/O-2 统计。
- golden set 门禁（105-04）：`server/tests/.../golden` fixture + harness + baseline（gk-001 待翻转）。
- `SystemSetting` / `SettingKeys` / service 层（项目约束：新增设置必须复用，不绕加密与权限）。
- 前端 `RoutingDecisionPanel.vue` 分数分解展开（105-06）— 新信号进 breakdown 自动获得展示（信号中文标签映射需补新键）。

### Established Patterns
- 阈值/参数外置先例：`REPO_ROUTER_STAGE1_*`（settings+env）与 SystemSetting 双轨——本 phase 权重走 SystemSetting（运维可改），纯技术参数可留 settings。
- 观测：structlog kv + category/component；embedding 调用有 `embedding` call_source。

### Integration Points
- `repo_router_scoring.py` 的函数签名扩展 → `repo_router_v2.py` 调用点、`repo_router_replay.py`（回放必须同步消费权重快照，保证旧快照可回放——快照里记 weight_set_version 与常数值）、golden harness。
- facets 数据源：repo_index_nodes payload 的 facets 字段（105 已解析）；`last_commit_at` 来源需 researcher 确认（Repository 模型/同步状态）。
- 系统设置 UI：web/src 既有设置页面模式。

</code_context>

<specifics>
## Specific Ideas

- 一切公式/常数/不变量以 `.planning/research/ROUTING-RANKING.md` §2/§3/§4/§7 为准；冲突以 §0 结论速览裁决。
- 回放兼容：Phase 105 的快照没有权重信息（phase105-v1 常数寄生在代码里）——106 起快照必须携带 weight_set_version + 关键常数，replay 优先用快照内值；对 105 旧快照回退当前默认值并标注（不追求跨版本比较，版本不同即不可比，见 research §6.2-9）。
- gk-001 翻转是本 phase 的验收锚点：`_notice` 里已注明「由 Phase 106 翻转」。

</specifics>

<deferred>
## Deferred Ideas

- 分组呈现（in_project/global、trust 标注、delta=0.15 迟滞）与 Stage 1 凸组合 α=0.35 → Phase 107。
- 权重自动调参（coordinate ascent 建议器）/在线学习 → Future（本里程碑不做）。
- 活跃度 v2 增强（`0.7·A_recency + 0.3·commit 频次饱和`）→ Future（research §3.5 标注本次不做）。
- O-1/O-2 生产环境校准数字回填 → 挂账人工步骤（同 105 UAT 纪律）。

</deferred>
