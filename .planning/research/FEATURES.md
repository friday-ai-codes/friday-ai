# Feature Research

**Domain:** 交付知识图谱 / 工程记忆（需求/缺陷 ↔ 技术方案 ↔ 代码 diff 的 GraphRAG 关联）— Friday AI v0.3.0
**Researched:** 2026-06-11
**Confidence:** MEDIUM-HIGH（对标产品行为来自官方文档/工程博客 HIGH；用户期望推断与复杂度评级为 MEDIUM）

> 范围限定：仅研究 v0.3.0 新能力。代码仓库向量索引、GraphRAG 检索、飞书工作项拉取、ai_plan_generation、AICodingNode、chat/CodingPlan、MCP 19 工具、npm skills 均为已有能力（existing），下文只把它们当作依赖项引用，不重复研究。

## 对标产品的工作方式（行为基线）

这类「需求-方案-代码 关联知识库」产品的共同行为模式，按对标对象归纳：

- **Linear Similar Issues / Triage Intelligence**：在"创建/进线"时刻即时召回相似 issue（向量 + LLM 复评），给出"重复 / 相关 / 无关"分级 + 一句话理由，用户可接受/驳回；建议与人工设定的元数据在 UI 上明确区分。核心体验是「在最接近源头的入口拦截」——创建表单、triage 收件箱、客服集成。（HIGH，官方工程博客）
- **Glean（engineering MCP）**：不做独立前端，而是经 MCP 把 permission-aware 检索注入用户已有工具（Cursor/Claude/IDE）；典型 query 是"给定 ticket EN-12345，找相似历史问题 + 关联讨论 + 可能 root cause"；强调跨源（Jira+Slack+GitHub）拼合「why」叙事。（HIGH，官方文档）
- **GitHub Copilot Workspace → Coding Agent**：issue→spec→plan→code 流水线；教训是研究预览形态被砍、能力并入"把 issue 指派给 agent → 出 PR"的异步主流程——即 plan/code 关联以「工作流副产品」形态存活，而非独立产品。对 Friday 的启示：知识图谱应是现有工作流的自动副产品，不是要用户额外维护的系统。（HIGH，GitHub 官方 blog + 多方报道）
- **Zep/Graphiti**：bi-temporal 边（valid_at/invalid_at + created_at/expired_at），新事实矛盾旧事实时"失效不删除"；支持 point-in-time（as-of）查询与"现在什么是真的"查询。这是时间语义的事实标准。（HIGH，官方文档 + arXiv 论文）
- **Traceability 工具（Jama、ContextGit、tracey）**：双向链（forward/backward）、staleness/suspect-link 检测（上游需求变了→下游代码链接标记"可疑"）、覆盖查询（哪些需求没有实现/测试）。关键实践：链接必须自动维护，人工维护的 RTM 必然腐烂。（HIGH/MEDIUM）
- **git 语义检索工具（GitLore、spelungit、diwa）**：commit/diff/PR 三流索引 + 混合检索，回答"为什么有这段代码/当时为什么这么改"；普遍用 git hook 自动增量索引、MCP 暴露给 agent。（MEDIUM，开源 README）

**用户期望的统一画像**：我提一个新需求（任意入口），系统自动告诉我"以前做过类似的吗、当时方案是什么、最后代码怎么改的、那个方案现在还作数吗"——零额外维护成本，答案带出处和时间限定。

## Feature Landscape

### Table Stakes (Users Expect These)

缺了这些，「交付知识图谱」名不副实。

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| 统一实体/边模型（需求/缺陷、方案、diff、MR 四类实体 + 关系边） | 一切检索/关联的地基；traceability 工具的「双向链」共识 | MEDIUM | 结构化业务数据自带稳定 ID（飞书工作项 ID、CodingPlan ID、MR URL），不需要 LLM 抽实体——比 Graphiti 简单得多。Postgres 表 + GraphStore 接口 |
| 工作流自动摄取（方案生成/编码完成即入图） | Copilot Coding Agent 教训：关联必须是工作流副产品，用户不会手动建链 | MEDIUM | 挂在 ai_plan_generation / AICodingNode 完成回调上；依赖既有工作流引擎 hooks |
| 知识向量化入 Qdrant（需求文本/方案/diff） | 相似召回的前提；复用既有 EmbeddingService + hybrid 检索 | MEDIUM | diff 需要切块策略（按文件/hunk）；新建 collection，不污染代码 chunk collection |
| 相似需求召回（给定新需求 → top-K 历史需求 + 关联方案/MR） | Linear Similar Issues 已把这变成行业基线体验 | MEDIUM | 向量召回 + 1-2 跳图扩散拼上下文；Linear 经验：LLM 复评"重复/相关/无关"显著提升精度，可作增强项 |
| 实体关联查看（从任一实体出发查上下游：需求→方案→diff→MR，反向亦可） | traceability 的 forward/backward 双向链是底线 | LOW-MEDIUM | PG 递归 CTE 1-3 跳查询（基准已验证）；API 形态即可，前端可视化另计 |
| 历史迭代轨迹查询（一个需求的方案 v1→v2→v3 与各次编码的时间线） | "当时为什么这么改"是 git 考古类工具的核心 query | MEDIUM | 依赖版本链 + bi-temporal 边；输出按时间排序的叙事结构 |
| 检索命中最新版（旧版本向量下线，默认不召回失效内容） | 召回过期方案 = 主动提供错误信息，比没有更糟；Hindsight 共识"recency-wins with explicit invalidation" | MEDIUM | 重摄取时旧向量打 deprecated payload 或删点 + 边 expired_at；这是版本化的"消费端"底线 |
| 至少一个程序化入口（MCP 工具优先） | Glean/spelungit 模式：agent 时代知识库先服务 agent | LOW-MEDIUM | 复用既有 McpToolView + PAT fail-closed 体系；查询类工具 2-3 个即够起步 |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Bi-temporal 边 + 过时标记（valid/invalid + created/expired 四时间戳） | 通用对标里只有 Zep/Graphiti 做到；在"需求会改、方案会推翻"的交付场景，"这个结论现在还作数吗"是高频问题 | MEDIUM-HIGH | 借鉴 Graphiti 模型但大幅简化：失效信号来自结构化事件（方案被新版本替代、需求状态变更），不需要 LLM 矛盾检测。检索结果显式标注 `superseded by vN` |
| 版本链（同一方案多轮修改形成 supersedes 链，历史可溯） | tracey 的 staleness 检测 + Graphiti 的 invalidation 合体；多轮修改是 Friday 真实工作流（方案评审→改→再改） | MEDIUM | 依赖统一实体模型；版本号 + prev/next 指针即可，不需要 git 式 DAG |
| diff→chunk 关联（diff hunk 链接到既有 ChunkRegistry 代码块） | 独有打通：从"这个需求改了哪些函数"到"这个函数被哪些需求改过"，市面产品（GitLore 除外）都停留在文件级 | HIGH | 依赖既有 codegraph；难点：chunk 会随代码演化漂移，diff 落地时刻的 chunk 快照与当前 chunk 的对齐需明确策略（建议：记 file+symbol+commit_sha，懒解析到当前 chunk） |
| 时间感知混合检索（向量 + 图扩散 + 时间衰减 + 过时硬过滤） | RAG freshness 文献的成熟配方（fused score：α·sim + recency，half-life 14-30 天；失效边硬过滤而非降权） | MEDIUM-HIGH | 依赖 bi-temporal 边 + 向量化；注意文献警告：稳定事实不该被衰减惩罚——只对"状态类"内容（方案、需求状态）施加衰减，过时用硬过滤 |
| 跨入口统一摄取（飞书工作项 / chat 自然语言需求 / MCP / 工作流，同一管道） | Linear 经验：拦截点越靠近源头越有价值；Friday 的多入口（chat 提需求→直接编码）是市面工具覆盖不到的 | MEDIUM | 依赖统一实体模型 + 各入口已有触发点；chat 需求需要从对话里界定"这是一个需求"的判定时机（建议：产出 CodingPlan 或触发编码即摄取，不做对话全量抽取） |
| 多入口暴露（MCP + chat tools + workflow 节点 + npm skills 四形态同一服务层） | Glean 模式（MCP 进 IDE）+ Linear 模式（创建时刻提示）叠加；让 ai_plan_generation 自动引用历史方案是闭环价值点 | MEDIUM | 同一 service 层 4 个薄封装；workflow 节点（"检索相似交付"）使方案生成节点能消费历史 → 这是飞轮 |
| 检索结果带出处与时间限定（每条结果附实体类型、版本、valid 区间、来源链接） | Zep "auditable answer" + Linear "explain why suggested"；信任的前提 | LOW | 在检索返回结构里带 metadata 即可，成本低收益高，建议直接并入 table stakes 实现 |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| 全自动双向同步飞书（图谱变更回写飞书工作项、飞书任何字段变更实时入图） | "单一事实源"直觉，traceability 工具宣传双向 | 回写=写权限+冲突解决+回环风暴（写回触发 webhook 再入图）；飞书字段语义多变，全字段同步噪声远大于信号 | 单向摄取：只在"产出方案/触发编码"等关键事件拉取快照入图；回写仅保留既有的工作流状态通知（已有能力） |
| LLM 自由文本实体/关系抽取（从对话、文档自动抽实体建图） | Graphiti/LightRAG 的标准做法，显得"更智能" | 抽取不稳定、贵、慢；Friday 的实体全部自带稳定 ID（工作项/方案/MR），抽取是负价值；PROJECT.md 已明确排除 | 结构化事件驱动：实体与边由业务事件直接产生，LLM 只用于可选的相似度复评 |
| 在线图算法分析（社区发现、中心度、全图 PageRank 式分析） | GraphRAG 论文（Microsoft）带火的"全局问答" | 批处理索引成本高、与 1-3 跳查询负载完全不同；PG 方案的优势恰恰在浅跳查询，引入全图算法会反推图数据库迁移 | 限定 1-3 跳递归 CTE + 向量召回的局部子图；全局统计走离线报表（如需要，未来里程碑） |
| 通用图谱可视化编辑器（前端画布上增删实体/边） | "知识图谱"一词带来的 UI 想象 | 编辑能力破坏"工作流副产品"不变量（人工边没人维护，必然腐烂——RTM 教训）；画布组件开发成本高 | 只读的实体详情页 + 关联时间线（列表/树形态）；已有 3d-force-graph 依赖可做只读局部子图展示，但排在 API/skill 之后 |
| 对话全量记忆化（把所有 chat 消息当 episode 入图，Zep 式 agent memory） | Zep/Mem0 的产品形态诱惑 | 与本里程碑目标（交付知识）混淆；对话噪声大、隐私敏感（v0.2.0 刚做完会话隔离）、需要 LLM 抽取 | 仅摄取"成为需求"的对话节点（产出 CodingPlan / 触发编码时），其余对话不入图 |
| 旧版本物理删除 | "省存储、防误召回" | 历史轨迹查询是 table stakes，删除即不可逆破坏；审计需求 | Graphiti 式失效不删除：向量打标/下线，边记 expired_at，as-of 查询保留可能性 |
| 强一致实时索引（每个事件同步阻塞写图+写向量） | "检索马上能命中" | 嵌入调用慢且可能失败，阻塞工作流主链路；交付知识的新鲜度容忍度是分钟级 | 异步摄取队列（复用 background_runner 模式），主链路只发事件；失败重试 + 幂等 |

## Feature Dependencies

```
统一实体/边模型 (bi-temporal schema + GraphStore 接口)
    ├──required by──> 工作流自动摄取
    ├──required by──> 跨入口统一摄取（飞书/chat/MCP）
    ├──required by──> 实体关联查看（1-3 跳查询）
    ├──required by──> 版本链
    └──required by──> diff 归档 + diff→chunk 关联

知识向量化 (Qdrant collection + EmbeddingService 复用)
    ├──requires──> 统一实体/边模型（向量点 payload 引用实体 ID）
    └──required by──> 相似需求召回

版本链 ──required by──> 检索命中最新版 ──required by──> 时间感知混合检索（过时硬过滤）
版本链 ──required by──> 历史迭代轨迹查询

相似需求召回 + 实体关联查看 ──required by──> 时间感知混合检索（向量+图扩散融合）

diff→chunk 关联 ──requires──> diff 归档（实体模型内）+ 既有 ChunkRegistry/ChunkEdge (existing)
diff→chunk 关联 ──enhances──> 实体关联查看（代码级反查"这个函数被哪些需求改过"）

时间感知混合检索 ──required by──> 多入口暴露（MCP/chat tools/workflow 节点/skills 是同一检索服务的薄封装）

多入口暴露(workflow 节点) ──enhances──> ai_plan_generation (existing)（方案生成自动引用历史 → 飞轮）
```

### Dependency Notes

- **一切依赖实体模型**：schema 是第一阶段唯一合理起点；GraphStore 接口同期定型（换引擎逃生门是项目既定决策）。
- **版本链 → 最新版检索 → 时间感知检索** 是一条严格的串行链：没有版本链就没有"什么算过时"，没有过时标记就没有时间感知检索的硬过滤项。
- **diff→chunk 关联是唯一 HIGH 复杂度且可降级的项**：降级形态 = diff 归档到文件级（记 file path + commit sha），chunk 级对齐推后。不阻塞其他任何功能。
- **多入口暴露应最后做**：四个入口共享同一 service 层，service 稳定前做入口是返工。
- **冲突**：对话全量记忆化（anti-feature）与会话隔离（v0.2.0 Validated）冲突——摄取 chat 需求时必须带 owner 语义，检索是否跨用户共享需在 REQUIREMENTS 阶段显式决策（建议：交付知识默认全局共享，因为方案/diff 本就是团队资产；但摄取来源里的对话原文不入图，只入提炼后的需求文本）。

## MVP Definition

### Launch With (v1 = v0.3.0 本里程碑)

- [ ] 统一实体/边模型（bi-temporal）+ GraphStore 接口 — 地基，无可替代
- [ ] 工作流自动摄取（方案生成/编码完成事件）+ 飞书/chat 需求入口 — "副产品"不变量，决定数据是否存在
- [ ] 知识向量化 + 相似需求召回（带出处/版本 metadata） — 核心用户价值的最短路径
- [ ] 版本链 + 检索命中最新版 — 没有它，召回过期方案是负价值
- [ ] 实体关联查看 + 历史迭代轨迹（API 级） — traceability 底线
- [ ] 时间感知混合检索（fused score + 过时硬过滤） — 里程碑的差异化承诺
- [ ] diff 归档 + 向量化（文件级起步，chunk 级对齐为同里程碑 stretch） — 全链路闭环必需
- [ ] 多入口暴露：MCP 工具 + workflow 检索节点优先，chat tools 次之，npm skill 收尾 — 价值出口

### Add After Validation (v1.x)

- [ ] LLM 相似度复评（"重复/相关/无关"分级 + 理由）— 触发条件：向量召回精度不满足，参照 Linear 两阶段方案
- [ ] diff→chunk 符号级精确对齐 + 漂移追踪 — 触发条件：文件级关联被实际使用且用户要求更细粒度
- [ ] 前端只读子图/时间线可视化 — 触发条件：API/skill 入口验证了查询模式后，按真实高频查询设计 UI
- [ ] as-of（point-in-time）查询暴露为工具参数 — 数据模型已支持，触发条件：出现审计/复盘场景

### Future Consideration (v2+)

- [ ] 跨需求洞察报表（哪些模块返工最多、方案推翻率）— 离线分析，先积累数据
- [ ] 检索权重自适应（α/half-life 按反馈调参）— 需要使用量与反馈信号
- [ ] 知识图谱与代码图谱（ChunkEdge）双向融合检索 — 涉及既有 collection 不迁移的约束，谨慎评估

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 统一实体/边模型 + GraphStore | HIGH（地基） | MEDIUM | P1 |
| 工作流自动摄取 + 多源入口 | HIGH | MEDIUM | P1 |
| 向量化 + 相似需求召回 | HIGH | MEDIUM | P1 |
| 版本链 + 最新版检索 | HIGH | MEDIUM | P1 |
| 实体关联 + 迭代轨迹查询 | HIGH | LOW-MEDIUM | P1 |
| 时间感知混合检索 | HIGH（差异化） | MEDIUM-HIGH | P1 |
| diff 归档（文件级） | MEDIUM-HIGH | MEDIUM | P1 |
| MCP 工具 + workflow 节点 | HIGH | LOW-MEDIUM | P1 |
| chat tools + npm skill | MEDIUM | LOW | P2 |
| diff→chunk 符号级关联 | MEDIUM | HIGH | P2 |
| LLM 相似度复评 | MEDIUM | MEDIUM | P2 |
| 前端只读可视化 | MEDIUM | MEDIUM-HIGH | P3 |
| as-of 查询暴露 | LOW-MEDIUM | LOW | P3 |

## 用户侧呈现形态对比（问题 4）

| 形态 | 用户期望 | 复杂度 | 建议 |
|------|----------|--------|------|
| MCP 工具 / chat agent tools | Glean 模式：在 agent 对话中"帮我找相似历史需求/这个方案最新版"；答案带出处与时间限定 | LOW-MEDIUM（复用 McpToolView + chat tools 注册机制） | 首选出口。2-4 个查询工具：`search_delivery_knowledge`、`get_entity_timeline`、`get_related_entities` |
| workflow 节点 | 方案生成前自动检索相似交付，注入 prompt 上下文——用户甚至无感知 | LOW-MEDIUM（BaseNode 子类 + 注册即生效） | 价值密度最高的出口（飞轮）：历史交付直接提升新方案质量 |
| npm Friday skill | spelungit/diwa 模式：开发者在自己的 agent 里问"为什么这段代码这么改" | LOW（skill 包装既有 MCP 工具） | 收尾做，纯封装 |
| 前端可视化 | 实体详情页 + 关联时间线为主；图画布是想象中的需求，实际高频是"列表+跳转" | MEDIUM-HIGH（图画布）/ MEDIUM（时间线页） | 本里程碑最多做只读实体详情 + 时间线；图画布不做（anti-feature 区已述） |

## Competitor Feature Analysis

| Feature | Linear | Glean | Zep/Graphiti | Our Approach |
|---------|--------|-------|--------------|--------------|
| 相似召回 | 创建/triage 时刻向量+LLM 两阶段，给分级+理由 | MCP 内跨源检索 | 向量+图+BM25 混合 | 向量+图扩散一阶段起步，LLM 复评留 P2 |
| 时间语义 | 无（只有状态字段） | 无显式模型 | bi-temporal 四时间戳，LLM 矛盾检测失效 | bi-temporal 边，但失效信号来自结构化事件（无 LLM 检测）——更便宜更确定 |
| 实体来源 | 人工创建 issue | 连接器同步全量文档 | LLM 从 episode 抽取 | 业务事件直接产生（稳定 ID），零抽取成本 |
| 代码关联 | commit/PR magic word 链接（文件级） | code search 独立能力 | 无 | diff 归档 + 与自有 ChunkRegistry 打通（潜在最深差异化） |
| 暴露形态 | 自家 UI 内嵌 | MCP 进第三方工具 | SDK/API | 四形态（MCP/chat/workflow/skill）共享一个 service 层 |

## Sources

- Linear: [Using AI to detect similar issues](https://linear.app/now/using-ai-to-detect-similar-issues)、[How we built Triage Intelligence](https://linear.app/now/how-we-built-triage-intelligence)、[Triage Intelligence Docs](https://linear.app/docs/triage-intelligence) — HIGH
- Glean: [MCP for Engineering](https://docs.glean.com/user-guide/mcp/engineering)、[Code Search](https://docs.glean.com/user-guide/assistant/code-search) — HIGH
- Zep/Graphiti: [Bi-Temporal Data Model](https://getzep-graphiti.mintlify.app/concepts/temporal-model)、[Zep arXiv 2501.13956](https://arxiv.org/abs/2501.13956)、graphiti `edge_operations.py` 源码 — HIGH
- GitHub Copilot Workspace 沉浮与 Coding Agent: GitHub Blog（coding agent vs agent mode）、多方报道（sunset 2025-05-30，能力并入 Coding Agent） — HIGH
- Traceability: [Jama Requirements Traceability Guide](https://www.jamasoftware.com/requirements-management-guide/requirements-traceability/what-is-traceability/)（suspect links / 双向链）、[ContextGit](https://github.com/Mohamedsaleh14/ContextGit)、[tracey](https://github.com/bearcove/tracey)（staleness 检测） — MEDIUM-HIGH
- Git 语义检索: [GitLore](https://github.com/ami3g/GitLore)（commit/code/PR 三流索引）、[spelungit](https://github.com/haacked/spelungit)（MCP server）、[diwa](https://github.com/Dorky-Robot/diwa)（hook 驱动增量） — MEDIUM
- 时间衰减检索: [Solving Freshness in RAG (arXiv 2509.19376)](https://arxiv.org/html/2509.19376)（fused score α≈0.7，half-life 14d）、[Memory Retrieval Policies](https://jatinbansal.com/ai-engineering/memory-retrieval-policies/)（staleness 硬过滤 vs 降权）、[Hindsight: Consolidation](https://hindsight.vectorize.io/blog/2026/05/21/agent-memory-consolidation)（recency-wins with explicit invalidation） — MEDIUM-HIGH

---
*Feature research for: 交付知识图谱（Friday AI v0.3.0）*
*Researched: 2026-06-11*
