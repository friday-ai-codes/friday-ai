# Feature Research

**Domain:** v0.24.0 单仓 graph-aware query（对齐 GitNexus 的 Process 分组混合检索）
**Researched:** 2026-08-24
**Confidence:** HIGH（核心结论来自 GitNexus 官方仓库 `11a60e6` 的源码、README 与官方 Skill）

> 范围限定：本文只研究统一查询入口、Process 一等检索、可解释排序、`file:line` 证据、截断/降级、工具发现、多消费面契约与单仓 benchmark。Friday 已有 `GraphService`、impact、trace、Community、Process 不重复研究。跨仓 impact、PDG/CFG、rename apply、以 Leiden 替换现有社区算法均不进入 v0.24.0。

## 结论先行

1. GitNexus 的 `query` 不是平铺文件搜索：它并行执行 BM25 与 semantic 检索，以 RRF 合并 Symbol，再沿 `STEP_IN_PROCESS` 归入 Process；结果分为 `processes`、`process_symbols`、`definitions`。
2. GitNexus 当前主线的 Process **不是直接检索对象**。检索先命中 Symbol，再把 Symbol 映射到 Process。因此，把 Process 名称、入口、终点、步骤摘要、模块和业务关键词直接纳入 BM25/embedding，是 Friday 可验证的差异化，而不是照抄。
3. GitNexus 的 Process 排名为「命中 Symbol 的 RRF 分数求和 + 最大 Community cohesion 的固定小幅加成」，只返回最终 `priority`，没有返回各项贡献。Friday 要做到“可解释排序”，必须把检索 lane、原始 rank、RRF 贡献、图增强贡献和稳定 tie-break 暴露为结构化 breakdown。
4. GitNexus 对运行降级处理较成熟：FTS 不可用时继续 semantic-only 并返回 warning；向量索引失败时尝试 exact scan；图 enrichment 真失败时返回 `partial: true`。但 embeddings 未生成、exact scan 因规模上限退出等路径仍可能静默退为 BM25-only。Friday 应把每条 lane 的实际状态统一返回。
5. GitNexus 有三层结果约束：`limit`、`max_symbols`、MCP `maxTokens`。最后一层只是 UTF-8 安全的字符串截断，可能把结构化 JSON 截断成以 `…` 结尾的文本；Friday 不应复制这种不透明截断，应优先做 schema-preserving 语义裁剪并返回总数、返回数和裁剪原因。
6. 工具发现不是只列工具名：GitNexus 动态 `ListTools` 会在多仓时把 `repo` 改成机器可读的必填参数，repo context resource 同时给出索引新鲜度、可用工具与下一步资源。Friday 的五个消费面应从同一 canonical manifest 生成 schema，并能发现能力、版本、仓库/commit 水位和降级状态。

## 观察事实：GitNexus 的用户可见行为

以下均为对 GitNexus 当前主线源码的观察，不是 Friday 的既定设计。

### 查询、分组与排序

| 观察事实 | 用户可见结果 | 证据 |
|---------|--------------|------|
| `query` 接受自然语言 `search_query`，默认最多 5 个 Process、每个 Process 最多 10 个 Symbol，源码内容默认关闭 | 一次调用先看到少量流程与定位信息，不默认灌入源码 | `tools.ts`、`local-backend.ts` |
| BM25 与 semantic 并行执行；候选上限为 `limit × max_symbols`；两路用 RRF 合并 | 同时兼顾精确关键词和语义近似；命中两路的候选得到更高融合分 | `local-backend.ts` |
| 每个命中 Symbol 经 `STEP_IN_PROCESS` 找到所有所属 Process | 结果按执行流分组，而不是按文件平铺 | `local-backend.ts` |
| Process 的 `totalScore` 是成员命中 Symbol 的 RRF 分数之和；`cohesionBoost` 取成员 Community cohesion 最大值；最终 `priority = totalScore + cohesionBoost × 0.1` | 多个相关步骤同时命中的流程更靠前；内聚度只作小幅增强 | `local-backend.ts` |
| 同分时按稳定 ID 排序，Community 多归属时也按 Community ID 稳定选第一项 | 相同索引和输入下，边界截断结果可复现 | `local-backend.ts` |
| `task_context`、`goal` 出现在公开 schema，但当前单仓 `query()` 排序实现没有消费这两个字段 | 调用者以为它们“帮助排序”，但单仓结果实际不受其影响 | `tools.ts` 与 `local-backend.ts` 对照 |
| `processes[].symbol_count` 在 per-process 截断和全局去重之前计算；`process_symbols` 最后按 Symbol ID 全局去重 | 一个 Symbol 同属多个 Process 时，扁平列表只保留首次出现的 `process_id`；计数与实际返回条数可能不同 | `local-backend.ts` |

### `file:line`、Process 与后续动作

| 观察事实 | 用户可见结果 | 证据 |
|---------|--------------|------|
| `query.process_symbols` 返回 `filePath`、1-based `startLine/endLine`、`process_id`、`step_index` 和可选 `module` | Agent 可从自然语言结果直接跳到代码区间，并知道它在流程第几步 | `local-backend.ts`、`resources.ts` |
| `definitions` 保存未归入任何 Process 的文件/符号，最多 20 项 | 没有 Process 归属的类型或文件不会完全丢失 | `local-backend.ts` |
| `process/{name}` resource 返回按 step 排序的完整 trace，但当前只显示 `name (filePath)`，未显示行号 | `query` 有行区间，完整 Process resource 反而缺少 `file:line`，证据契约不完全一致 | `resources.ts` |
| `query` 本身不返回 blast radius；MCP 响应提示调用者下一步用 `context`，再按需用 `impact` | GitNexus 的统一程度是“发现流程”，不是 Friday 目标的 NL→…→impact 一次完成 | `server.ts`、官方 `gitnexus-exploring` Skill |
| repo context resource 返回 stats、staleness、可用 tools/resources；官方 Skill 要求先绑定 repo、检查 freshness，再 query | 索引水位是回答可信度的一部分，而不是隐藏运维细节 | `resources.ts`、官方 Skill |

### 截断与降级

| 场景 | GitNexus 行为 | 对 Friday 的启示 |
|------|---------------|------------------|
| Process 数量过多 | `limit` 截断 Process | 需要返回匹配总数/返回数，不能只给 top-N |
| 单 Process 符号过多 | `max_symbols` 截断该 Process；`include_content=false` 控制体积 | 保留结构证据优先于源码正文 |
| 独立 definitions 过多 | 固定截到 20 | 固定隐式 cap 不利于调用者判断遗漏；应显式元数据化 |
| MCP 响应超预算 | `maxTokens` 按每 token 估算 4 UTF-8 bytes，对完整文本做安全前缀截断并以 `…` 结尾 | 这是 transport guardrail，不是语义分页；Friday 应避免截断 JSON 中段 |
| FTS 完全不可用 | semantic-only 继续；返回包含 repo/branch/indexedAt 的 warning | 降级可见且带修复上下文是 table stake |
| FTS 部分表失败 | 保留其他结果；warning；`partial: true` | 部分成功必须区别于完整成功 |
| 未生成 embeddings | semantic lane 返回空，通常继续 BM25-only | Friday 应显式返回 lane=`unavailable/not_indexed`，不能让用户误判为完整 hybrid |
| VECTOR 查询失败 | 尝试 exact scan；仅首次向服务端日志写 fallback | 可自动降级，但用户结果应标实际执行模式 |
| exact scan 超出内部规模上限 | semantic lane 返回空 | 不应静默等同于“没有语义命中” |
| Process/Community 表不存在 | 当作正常配置，不标 `partial` | Friday v0.24.0 已承诺这两类对象；缺失时应明确 capability unavailable，而非看似完整空结果 |
| Process/Community/content enrichment 真失败 | 继续返回已有数据；warning；`partial: true` | best-effort 不反噬主查询，同时不隐藏证据缺口 |
| CJK 分词配置不一致或 query 超出分词保护上限 | 返回具体 warning 和修复建议 | 中文 NL query 的分词模式与索引模式必须进入 benchmark 与 capability 回显 |

### 工具发现与契约

| 观察事实 | 价值 | Friday 对应要求 |
|---------|------|----------------|
| `GITNEXUS_TOOLS` 是 MCP tools schema 的集中定义 | 工具名、描述、参数边界不散落 | 建 canonical graph-query manifest |
| `ListTools` 根据只读策略、仓库 allowlist 动态过滤；多仓且无默认仓时，把 `repo` 注入 required | Agent 在调用前即可发现权限与必填作用域 | Friday 单仓 query 仍要显式绑定 `repository_id`，五面同一 required 语义 |
| `gitnexus://repos` 与 repo context resource 提供仓库发现、索引 stats/staleness、available tools/resources | 先发现能力，再执行重查询 | Friday 工具发现需包含 schema version、index commit、能力 lane |
| 工具响应附 next-step hint；官方 Skill 固化 `list_repos → context → query → context → process` | 小模型不必猜工具编排 | Friday 的统一入口应减少必需的二次编排；高级 drill-down 仍提供明确 next actions |
| 旧 `query` 参数仍兼容，但公开 schema 只广告 `search_query`，以绕过特定客户端会丢 `query` 参数的问题 | 公开契约和兼容别名可分离 | canonical manifest 可保留 alias，但 contract test 必须覆盖每个消费面真实序列化 |

## Feature Landscape

### Table Stakes（用户默认应当具备）

| Feature | Why Expected | Complexity | 可转为原子验收的 Notes |
|---------|--------------|------------|--------------------------|
| **TS-01 单一 graph-aware query** | 用户不应手工串 Symbol、Community、Process、impact 多个底层工具 | HIGH | 给定 repository + NL query，一次响应同时含候选 Symbol、Community、Process、步骤证据和有界 impact 摘要；空 query 明确拒绝 |
| **TS-02 Process 分组结果契约** | GitNexus 已把执行流分组做成核心用户行为 | MEDIUM | 每个 Process 内嵌自己的命中 Symbol/steps，不使用会丢多归属的全局扁平去重；返回 `matched_symbol_count` 与 `returned_symbol_count` |
| **TS-03 Process 一等 BM25/embedding 召回** | 仅 Symbol→Process 映射会漏掉业务词只存在于流程摘要的查询 | HIGH | Process 检索文档至少覆盖名称、入口、终点、步骤摘要、模块、业务关键词；测试“Symbol 名无 query 词、Process 摘要有 query 词”仍能召回 |
| **TS-04 双 lane 混合检索与确定性融合** | 关键词与自然语言互补；相同输入应可复现 | HIGH | Symbol lane 与 Process lane 均记录 BM25/semantic 排名；同仓同 commit 同配置重复运行排序一致；tie-break 使用稳定 ID |
| **TS-05 可解释排序 breakdown** | 仅给一个 `priority` 无法判断为什么命中，也无法做 benchmark 归因 | MEDIUM | 每个结果返回命中 lane、各检索 rank/贡献、图增强贡献、最终分与排序版本；所有贡献可重算最终分；不在研究阶段臆造权重 |
| **TS-06 步骤级 `file:line` 证据** | Agent 必须能核验并跳转，不可只有流程叙事 | MEDIUM | 每个返回步骤包含仓库相对路径、1-based start/end line、Symbol UID、index commit；行号落在文件范围内且源码锚点可反查 |
| **TS-07 候选消歧与锚点选择** | 重名 Symbol 不能静默选第一个后继续算 impact | MEDIUM | 重名时返回候选及路径/行号；impact 只基于已明确 UID 的 anchor；无法唯一化时标 `needs_disambiguation`，不伪造影响面 |
| **TS-08 有界 impact 摘要** | v0.24.0 目标要求一次回答影响面，但不能把完整传递闭包灌入 | MEDIUM | 对明确 anchor 返回既有 impact 能力的摘要、直接影响样本和截断信息；完整明细通过 next action/drill-down 获取 |
| **TS-09 schema-preserving 截断** | LLM 工具响应必须在预算内且仍可解析 | MEDIUM | 按“源码正文→次要 Symbol→低排 Process”顺序裁剪；始终返回合法 schema、总数/返回数、`truncated=true`、原因和继续查询提示 |
| **TS-10 lane 级降级可见** | BM25-only、semantic-only、无 Process enrichment 不能看起来像完整 hybrid | MEDIUM | 返回 `retrieval_status`，分别标 BM25、embedding、graph enrichment、impact 的 used/degraded/unavailable 及脱敏原因；部分成功置 `partial=true` |
| **TS-11 索引水位与证据一致性** | `file:line`、Process、impact 必须来自同仓同 commit，否则组合答案不可核验 | MEDIUM | 响应顶层返回 repository、branch/index key、commit SHA；发现组件水位不一致时降级或拒绝拼接，并明确 warning |
| **TS-12 canonical 工具契约与发现** | 服务端、Chat、Django MCP、npm MCP、容器任一漂移都会造成“服务端有、Agent 找不到” | HIGH | 五个消费面从同一 manifest 生成/适配；工具名、description、required、defaults、enums、response version 一致；schema hash snapshot 全面相等 |
| **TS-13 权限、排除与可观测约束** | 新统一入口不能绕过既有安全边界 | MEDIUM | 所有 lane 复用 repository 权限与 exclusion fail-closed；日志/`RetrievalTrace` best-effort，携带触发用户和关联键，不记录凭证或未脱敏上游文本 |
| **TS-14 单仓同 commit benchmark** | “更好”必须可重复证明，不能凭样例感受 | HIGH | 冻结 repo+commit+query set，先记录 v0.22 baseline；按语言/框架/入口类型分桶，产 Symbol/Process recall、`file:line` 有效率、resolved edge、impact/trace、延迟/token 原始结果；回归阈值仅在 baseline 后锁定 |

### Differentiators（相对 GitNexus 的竞争优势）

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **DF-01 Process 直接检索 + Symbol 间接映射双路合流** | GitNexus 当前只先搜 Symbol 再映射 Process；Friday 可召回“业务概念存在于流程摘要、却不在符号名”的流程 | HIGH | Process 是独立检索文档，不只是 enrichment 标签；与 Symbol→Process 证据在统一排序中合流 |
| **DF-02 一次返回 NL→证据→影响面** | GitNexus 要 query→context→impact 多调用；Friday 面向编码/方案 Agent 可一次获得可行动摘要 | HIGH | 保持 bounded summary；不要在统一入口塞完整 impact 闭包 |
| **DF-03 完整排序账本** | GitNexus 只暴露三位小数 `priority`；Friday 可让用户和 benchmark 精确解释每次排序变化 | MEDIUM | breakdown、排序版本、稳定 tie-break、lane 状态全部结构化；可离线回放 |
| **DF-04 五消费面同契约** | GitNexus MCP 定义集中，但 Friday 的产品价值要求 Chat、Django MCP、npm MCP、容器与服务端真正同源 | HIGH | contract manifest + 生成物/adapter + schema hash + E2E discovery；这是 v0.22 npm 漂移的结构性修复 |
| **DF-05 证据一致性硬约束** | 把 Process、行号、impact 锚定同一 index commit，避免“每块都真、拼起来是假” | MEDIUM | 每个 evidence item 可继承顶层水位；混水位不得静默合并 |
| **DF-06 结构化、可续查的预算降级** | GitNexus `maxTokens` 可能截断结构化文本；Friday 可在低 token 预算下仍返回可解析且可 drill-down 的答案 | MEDIUM | 用语义裁剪替代字符串截断；测试多个预算档只验证单调裁剪与 schema 完整，不预设业务阈值 |

### Anti-Features（明确不做或不复制）

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **AF-01 跨仓 impact / group query** | 看起来是统一查询的自然延伸 | 本里程碑验收是单仓 benchmark；跨仓真实样本与生产者仍有已知欠债，会稀释单仓质量闭环 | 响应明确 `scope=single_repository`；跨仓后续独立里程碑 |
| **AF-02 自研或扩展 PDG/CFG** | 希望 query 解释控制/数据依赖 | 编译器级范围，与 Process 混合召回没有必要依赖；会造成范围爆炸 | 只消费现有 Symbol/调用边/Process/impact |
| **AF-03 rename apply** | Agent 拿到 Symbol 后可顺手改名 | 引入写仓副作用，与只读统一查询无关 | 保留既有只读能力；编码 Agent 自己编辑 |
| **AF-04 把 Louvain 换成 Leiden** | GitNexus 文档称 Community 使用 Leiden | Friday 已有固定 seed 的 Louvain 决策；替换算法会把检索改进与社区重建混为一谈 | 复用现有 Community；只改其检索/解释消费 |
| **AF-05 仅搜 Symbol 再映射 Process** | 最接近 GitNexus 当前实现，改动较小 | Process 仍非一等对象，无法满足“业务词命中流程摘要”的目标 | Symbol 与 Process 两条 retrieval lane |
| **AF-06 用 LLM 直接给最终排序分** | 自然语言 query 看似适合智能重排 | 不可稳定回放、难解释、难做同 commit benchmark | 确定性混合排序；如后续加 LLM，只能有界重排且不得覆盖事实分 |
| **AF-07 全局扁平 `process_symbols` + Symbol ID 去重** | 输出紧凑、看似省 token | 多 Process 归属会丢失，Process 计数与返回项不一致 | Symbol 嵌套在 Process 内；共享 Symbol 可重复引用 UID，正文去重另做 |
| **AF-08 仅返回最终 `priority`** | payload 更小 | 用户无法解释 Community/Process 为什么排前，也无法定位 benchmark 回归 | 返回可加和 breakdown 和排序版本 |
| **AF-09 字符串中段 `maxTokens` 截断** | 实现简单、能硬控上下文 | 可能破坏 JSON/schema，调用者不知道漏了哪一层 | schema-preserving 语义裁剪 + truncation metadata |
| **AF-10 静默退为 BM25-only 或空 Process** | availability-first | 用户会把能力缺失误判为“没有相关流程” | availability-first 继续，但 lane 状态、warning、partial 必须可见 |
| **AF-11 在 baseline 前拍脑袋设门槛/权重** | 便于先写 CI | 违反同仓同 commit 实测原则，可能把旧缺陷固化或制造不可达门槛 | 先采 baseline 与分桶分布，再在需求评审中锁阈值与版本 |
| **AF-12 为五个入口手写五份 schema** | 每个入口能快速上线 | 必然重演 npm MCP 漂移，且默认值/枚举最容易悄悄分叉 | canonical manifest 派生适配层与 snapshot |

## Feature Dependencies

```text
[同仓同 commit 数据集与 v0.22 baseline]
    └──requires──> [TS-14 benchmark 与后续门槛]

[Process 检索文档构建]
    └──requires──> [TS-03 Process 一等 BM25/embedding]
                       └──requires──> [TS-04 双 lane 融合]
                                          └──requires──> [TS-05 排序 breakdown]

[稳定 Symbol UID + Community/Process 归属 + index commit]
    └──requires──> [TS-02 Process 分组]
    └──requires──> [TS-06 file:line 证据]
    └──requires──> [TS-07 消歧]
                       └──requires──> [TS-08 impact 摘要]

[TS-02~TS-11 canonical response schema]
    └──requires──> [TS-01 单一入口]
                       └──requires──> [TS-12 五消费面契约与发现]

[TS-09 语义截断] ──cross-cuts──> [TS-01/02/06/08/12]
[TS-10 降级可见] ──cross-cuts──> [BM25/embedding/graph/impact]
[TS-11 水位一致性] ──cross-cuts──> [所有证据与 benchmark]
[TS-13 权限/排除/观测] ──cross-cuts──> [所有入口]
```

### Dependency Notes

- **先建 Process 检索文档，再做融合排序。** 没有可独立索引的 Process 表示，就仍然只是 GitNexus 式 Symbol→Process enrichment。
- **先定 canonical response，再铺五个入口。** 否则各入口会围绕半成品 schema 独立演化，最后只能做人工对齐。
- **消歧先于 impact。** 任何基于名称猜中的 impact 都会把低置信候选包装成确定事实。
- **水位一致性先于 benchmark。** benchmark 若混用不同 commit 的 Symbol、Process 或行号，指标本身不可解释。
- **benchmark 先采 baseline，后锁回归门。** 研究只定义指标维度和数据冻结协议，不定义阈值。
- **TS/JS 与 Python resolved edge 提升是召回质量依赖，但应按语言独立测。** Go 按项目既定依赖顺序后置，不应阻塞统一契约和 benchmark harness。

## MVP Definition（v0.24.0）

### Launch With

- [ ] **MVP-01** canonical graph query request/response schema：单仓作用域、版本、水位、Process 嵌套结果、evidence、breakdown、truncation、degradation。
- [ ] **MVP-02** Process 检索文档与 BM25/embedding 双 lane：支持业务词直接命中 Process。
- [ ] **MVP-03** Symbol + Process 确定性混合排序：可重算 breakdown、稳定 tie-break、重名消歧。
- [ ] **MVP-04** 步骤级 `file:line` + bounded impact 摘要：所有结论可核验，同一 commit。
- [ ] **MVP-05** schema-preserving 预算与 lane 级降级：部分成功不装成完整成功。
- [ ] **MVP-06** 服务端、Chat、Django MCP、npm MCP、编码容器五面发现同一工具契约。
- [ ] **MVP-07** 单仓 benchmark：冻结同仓同 commit，先记录 v0.22 baseline，再锁门槛。
- [ ] **MVP-08** 权限/exclusion/脱敏/触发用户/`RetrievalTrace` 与结构化日志覆盖。

### Add After Validation

- [ ] **VAL-01** query drill-down cursor/分页：只有 benchmark 证明 top-N 语义裁剪不足时再增加。
- [ ] **VAL-02** 可选 `task_context`/`goal` 真正入排序：只有建立独立增益对照后启用；不能只在 schema 声称有效。
- [ ] **VAL-03** 更丰富的 Process 摘要生成：先验证确定性字段索引，确有召回缺口再引入额外 LLM 生成成本。

### Future Consideration

- [ ] 跨仓 graph-aware query / impact。
- [ ] PDG/CFG 或语句级数据流检索。
- [ ] rename apply。
- [ ] 社区算法替换。
- [ ] 学习排序或 LLM 重排。

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| canonical request/response + 水位 | HIGH | MEDIUM | P1 |
| Process 一等混合召回 | HIGH | HIGH | P1 |
| Process 分组 + `file:line` | HIGH | MEDIUM | P1 |
| 可解释确定性排序 | HIGH | MEDIUM | P1 |
| bounded impact 摘要 | HIGH | MEDIUM | P1 |
| 截断/降级结构化 | HIGH | MEDIUM | P1 |
| 五消费面契约与发现 | HIGH | HIGH | P1 |
| 单仓 benchmark | HIGH | HIGH | P1 |
| `task_context`/`goal` 排序增强 | MEDIUM | MEDIUM | P2 |
| Process LLM 摘要扩充 | MEDIUM | MEDIUM | P2 |
| 跨仓 query | OUT OF SCOPE | HIGH | P3 |

## Competitor Feature Analysis

| Feature | GitNexus 当前主线 | Friday v0.24.0 建议 |
|---------|-------------------|----------------------|
| 检索入口 | NL query，BM25 + semantic 并行，RRF | 保留混合检索，增加 Symbol lane + Process lane |
| Process 命中 | 先命中 Symbol，再沿 `STEP_IN_PROCESS` 分组 | Process 自身可被 BM25/embedding 直接命中，同时接受 Symbol 间接证据 |
| Process 排名 | Symbol RRF 分数求和 + 最大 cohesion 小幅加成 | 确定性融合，但返回完整 breakdown；具体权重在 baseline 后锁定 |
| 结果结构 | `processes` + 扁平 `process_symbols` + `definitions` | Process 内嵌命中与步骤；保留 standalone Symbol 区，避免多归属丢失 |
| 行号 | query Symbol 为 1-based start/end；Process resource 仅 file | 所有 Process steps 一致返回 1-based `file:line` 和 index commit |
| impact | 需 query→context→impact 后续调用 | 统一入口返回有界摘要，完整 impact 仍可 drill-down |
| 截断 | limit、max_symbols、definitions cap、可选字符串 maxTokens | 语义裁剪、合法 schema、总数/返回数/原因/next action |
| 降级 | FTS warning、enrichment partial；部分 semantic 降级仅日志可见 | 每条 lane 结构化状态，任何不完整结果 `partial` 可见 |
| 工具发现 | 集中 tools 定义；动态 required repo；context resource + Skill | canonical manifest 派生五消费面，schema hash 与真实调用 E2E |
| 评测 | 源码有单元回归与 timing，但不是 Friday 目标的同仓 v0.22 对照 | 冻结单仓 commit 与分桶 query set，先 baseline 后门槛 |

## 可直接转成需求的验收清单

1. **QUERY-01:** 给定已索引 repository 和非空中文/英文 NL query，统一入口返回版本化 schema；空白 query 不触发检索。
2. **QUERY-02:** 响应顶层 repository、branch/index key、commit 与每条 evidence 一致；混水位不能静默拼接。
3. **PROC-01:** Process 文档包含名称、入口、终点、步骤摘要、模块、业务关键词，并进入 BM25 与 embedding 两路。
4. **PROC-02:** 构造 query 词只存在于 Process 文档、不存在于 Symbol 名的 fixture，Process 仍进入候选。
5. **GROUP-01:** 同一 Symbol 属于两个 Process 时，两个 Process 均保留该 UID 的归属/step 证据；计数与返回数各自明确。
6. **RANK-01:** 每个候选的 breakdown 可确定性重算最终分，排序版本存在，稳定 ID 决定同分顺序。
7. **RANK-02:** 同仓、同 commit、同配置、同 query 重复运行，候选顺序与 breakdown 相同。
8. **EVID-01:** 每个 Process 返回的每一步都有 repo-relative file、1-based line range、Symbol UID；随机抽样可读取对应源码范围。
9. **DISAMB-01:** 重名 anchor 返回候选而不静默选取；未消歧时 impact 标不可用/待选择。
10. **IMPACT-01:** 已消歧 anchor 返回 bounded summary、总数/返回数和 drill-down 提示，不复制完整闭包。
11. **BUDGET-01:** 在不同响应预算下输出始终满足 schema；预算收紧只减少可选正文/低排项，不移除水位、warning、truncation 元数据。
12. **DEGRADE-01:** 分别模拟 FTS、embedding、Process enrichment、impact 失败；主查询 best-effort 返回，lane 状态与 `partial` 如实变化。
13. **CONTRACT-01:** 五消费面对同一 manifest 的工具名、required/default/enum、response schema version 和 schema hash 一致。
14. **DISCOVER-01:** 每个消费面在执行前都能发现工具能力、契约版本、仓库作用域和索引水位； npm/容器真实调用不依赖只存在于服务端的隐藏参数。
15. **BENCH-01:** benchmark 固定 repo+commit+query set，按语言/框架/入口类型分桶；v0.22 baseline 与 v0.24 candidate 使用同一输入运行。
16. **BENCH-02:** 报告输出 Symbol/Process recall、`file:line` 有效率、resolved edge、impact/trace、延迟、token 的逐例原始结果与汇总；阈值字段在 baseline 采集前不得伪造。
17. **OBS-01:** query 生命周期有 started/completed/failed 结构化事件、`duration_ms`、`category`、`component` 和触发用户；各检索 lane 写 best-effort trace，任何观测失败不改变业务响应。

## Sources

**一手源码与文档（HIGH confidence，均核对于 GitNexus `11a60e6de30ac3905066c2012f47878b995e69ed`，2026-08-24）：**

- GitNexus `query` 主实现：BM25/semantic 并行、RRF、Process 分组、cohesion boost、稳定 tie-break、`file:line`、warning/partial
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/mcp/local/local-backend.ts
- MCP tool canonical definitions：`query` schema、`limit`、`max_symbols`、`include_content`、`maxTokens`、工具发现参数
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/mcp/tools.ts
- MCP server：动态工具发现、仓库作用域 required 注入、next-step hints、response budget 应用
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/mcp/server.ts
- MCP output budget：4 UTF-8 bytes/token 估算与 `…` 前缀截断
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/mcp/output-budget.ts
- MCP resources：repo context/staleness/tool discovery、Process 列表与 step trace、行号口径
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/mcp/resources.ts
- Hybrid search 核心：RRF 与 FTS→semantic-only fallback
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus/src/core/search/hybrid-search.ts
- 官方探索 Skill：repo 绑定、freshness、query→context→process 的用户工作流
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/gitnexus-claude-plugin/skills/gitnexus-exploring/SKILL.md
- 官方 README：Process-grouped query 示例、MCP response budget、当前工具面
  https://github.com/abhigyanpatwari/GitNexus/blob/11a60e6de30ac3905066c2012f47878b995e69ed/README.md

**Friday 范围与既有决策（HIGH confidence）：**

- `.planning/PROJECT.md`：v0.24.0 Goal、Active features、v0.22.0 已交付基线与显式边界。

## Confidence 与待验证项

| Area | Confidence | Notes |
|------|------------|-------|
| GitNexus query 分组与排序 | HIGH | 直接阅读当前主线实现；文档中“按 step count 归一化”的旧说法与当前源码不一致，本文以源码为准 |
| 行号与 Process resource | HIGH | `local-backend.ts` 和 `resources.ts` 可直接对照 |
| 截断与降级 | HIGH | 直接读取 query、semantic fallback、output-budget 实现 |
| 工具发现 | HIGH | 直接读取 MCP `ListTools`、resources 和官方 Skill |
| Friday 排序权重/回归阈值 | 未定 | 必须由同仓同 commit baseline 决定；本文刻意不臆造 |
| Process 直接检索的实际增益 | MEDIUM | 机制上补足 GitNexus 的间接映射缺口，但增益需 BENCH-01/02 实测 |

---
*Feature research for: Friday AI v0.24.0 单仓 graph-aware query*
*Researched: 2026-08-24*
