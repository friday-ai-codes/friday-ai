# Pitfalls Research

**Domain:** v0.24.0 单仓图查询评测与 MCP 契约对齐（NL→Symbol/Process、resolved edge、impact、trace、`file:line`、延迟/token）
**Researched:** 2026-08-24
**Confidence:** HIGH（指标定义与协议要求有官方资料及本仓实现佐证；阈值必须由本仓 baseline 实测后产生，本文不预设目标值）

> 相位代号仅用于 roadmap 编排：**B0-基准协议与冻结基线**、**B1-调用边质量**、**B2-Process 一等检索**、**B3-统一图查询与证据**、**B4-MCP 契约收敛**、**B5-回归门与运行观测**。关键顺序是先 B0，再改算法；不得先调到“看起来更好”再补 baseline。

## Benchmark Design Contract

### 1. 每次评测必须冻结的运行清单

每个 run 写出机器可读 manifest，至少包含：

- `benchmark_version`、case fixture hash、标注规范版本；
- `repository_id`、仓库 URL/路径、**完整 `commit_sha`**、索引水位 `indexed_commit_sha`；
- extractor/LSP/embedding/reranker/LLM 的实现版本与配置 hash；
- 图构建配置、候选预算、`top_k`、token 上限、截断策略；
- 随机 seed、重复轮次、运行时间、硬件/worker 数、冷/热缓存状态；
- 每个消费面及其构建产物版本：server commit、npm 包版本/tarball hash、task 镜像 digest；
- per-case 原始结果、阶段耗时、输入/输出 token、错误码、截断原因，而不只存聚合分数。

硬前置：`commit_sha == indexed_commit_sha == gold.commit_sha`。任一不等，本次 run 标为 **INVALID**，不得进入 baseline 或趋势。所有 `file:line` 必须从该 commit 的 blob 核验，不读当前工作树。

### 2. Case 与标注规范

一条 case 的最小形状：

```json
{
  "case_id": "stable-id",
  "commit_sha": "full-sha",
  "query": "不泄漏答案的自然语言问题",
  "query_source": "human|issue|trace|synthetic",
  "task": "symbol|process|impact|trace",
  "language": "typescript|javascript|python|go",
  "framework": "vue|django|adrf|cobra|other",
  "entry_type": "api|cli|event|init|workflow|unknown",
  "gold": {},
  "label_status": "double_annotated|adjudicated",
  "split": "dev|locked_test|holdout"
}
```

标注规则：

1. 两名标注者独立标注，分歧由第三人裁决；保留初始标签与裁决理由，不能只留最终答案。
2. Symbol 身份用 `(commit_sha, repo_relative_path, qualified_name, kind, declaration_range)`；Process 身份用 `(entry_symbol_id, terminal/outcome, ordered gold steps 或允许的等价路径集合)`。数据库自增 ID 不可作跨重建 gold。
3. 一个 query 允许多个相关 Symbol/Process；标注 `required` 与 `acceptable`，主 Recall 只按事先锁定的 gold 集计算，不能见到系统输出后追加“也算对”。
4. `file:line` 核验应确认：路径存在、行号在 blob 范围内、声明行确属目标 Symbol；trace 的相邻步骤还要核验对应 callsite/edge。仅“文件存在”不算通过。
5. 正样本之外必须有负样本：仓内不存在的概念、同名歧义、不可达 source→target、被排除文件、错误 commit 的旧符号、合法但无 Process 的入口。负样本不混入 Recall 分母，单独评 no-answer/typed-error。
6. 按 `language`、`framework`、`entry_type` 打标签；多语言文件或跨框架入口需指定主要桶并保留多值标签，避免事后随结果改桶。

### 3. 指标与分母

| 指标 | 单 case 定义 | 聚合与必要配套 |
|------|--------------|----------------|
| NL→Symbol Recall@5 | `|gold_symbol_ids ∩ top5_unique_symbol_ids| / |gold_symbol_ids|`；只纳入 gold 非空正样本 | 先对 case 宏平均；另报 Success@5、MRR/nDCG 作为排序诊断；重复/别名先 canonicalize |
| NL→Process Recall@3 | `|gold_process_ids ∩ top3_unique_process_ids| / |gold_process_ids|`；只纳入 gold 非空正样本 | 先对 case 宏平均；等价 Process 必须在标注时锁定，不能按名称模糊算命中 |
| resolved edge precision | 在**独立抽样并完整标注的 callsite 集**上，`正确预测的 (caller, callsite, callee) / 所有预测为 resolved 的边` | 无预测时 precision 记 `N/A`，不能记 1；按语言和调用构造分桶 |
| resolved edge recall | `正确预测的 gold edge / 全部 gold 可解析 edge` | 分母含系统留作 unresolved 的 gold edge；只抽系统已 resolved 边会让 recall 虚高 |
| impact precision | 对固定 seed、方向、relation 词表、max depth 和结果上限，`预测且在 gold impact 集 / 所有返回 impact 项` | 无返回记 `N/A`，另报 coverage；被截断后的 precision 必须带 `truncated=true`，不可与完整结果混算 |
| trace 成功率 | 正样本中，返回至少一条**端点正确、每个相邻 edge 有效、每步 `file:line` 有效**路径的 case 数 / 可达正样本数 | 同时报路径 edge precision、location validity、超时率；只验证首尾不够 |
| 错误路径正确率 | 负样本中返回预期稳定错误类（`source_not_found`、`target_not_found`、`ambiguous`、`no_path`、`stale_index` 等）的 case 数 / 负样本数 | 另报 false-path rate=`负样本却返回路径 / 负样本数`；禁止把所有失败折成空列表 |
| 延迟 | 从统一入口收到请求到完整响应的墙钟时间；所有 case 均进分母 | 报 p50/p95、冷/热缓存、成功/错误各自分布；timeout 作为超时率，不能从延迟样本删掉 |
| token | 实际送入/返回 LLM 的 input/output token；无 LLM 的阶段记 0 | 报每次调用与每个成功 case 分布；同时记录候选数、序列化字符数、预算与截断原因 |

`file:line validity` 应作为独立指标和 trace/Process 的硬证据条件：`有效位置数 / 所有返回位置数`。如果响应声称 `as_of` 某 commit，却无法在该 commit 验证任一位置，该 case 即失败，而非仅扣一个展示分。

### 4. 分桶与报告规则

- 必报三组边际桶：语言、框架、入口；另报 roadmap 关心的交叉桶，如 `typescript×vue×event`、`python×django×api`。
- overall 采用 per-case macro，仅作摘要；**任何受保护桶回退都不能被 overall 提升抵消**。
- 每桶同时输出 `n`、分子、分母、点估计和置信区间。样本不足时标 `INSUFFICIENT_DATA`，不以 overall 替代，也不判绿。
- TS 与 JS 至少在原始报告分开，是否合并展示只能是额外视图；Python、Go 同理独立。
- 正/负、真实/合成、人标/弱标、冷/热缓存不得混成一个分数。
- 对 retrieval 管线同时保存 `retrieved → reranked → returned` 三层 gold 到达情况，定位是候选召回丢失、排序丢失还是输出截断丢失。

### 5. Baseline 后锁阈值

1. 在 B0 固定 case、commit、索引配置和 harness。
2. 从未修改的 v0.22.0 代码/构建产物运行 baseline；确定性层至少复跑以验证字节稳定，含 LLM/embedding 抖动的层做多轮配对运行。
3. 保存逐 case 与逐桶分布、置信区间、失败清单。baseline 为观测事实，不是目标值。
4. 完成 baseline 后，单独提交 threshold policy。阈值依据产品风险、baseline 方差、样本量和可接受回退预算决定；**本文不臆造数值**。
5. 门禁同时包含：关键 case 不退、受保护桶不退、overall 改善、错误/超时/截断不恶化、位置有效率不退。统计不确定时判“需复验”，不能自动判提升。
6. baseline 或阈值更新必须是显式 review 动作；测试失败时自动重生成 baseline 属禁止行为。

## Critical Pitfalls

### Pitfall 1: “同仓”却不是同 commit，`file:line` 成为伪证据

**What goes wrong:**
query 在 commit A 的索引上运行，gold 或源码核验却来自当前分支 B。符号同名仍能命中，Recall 看似正常，但行号已漂移；Process 步骤甚至会指向另一个函数。最终证明的是“名字大致相似”，不是目标要求的同仓同 commit 可核实证据。

**Why it happens:**
仓库名、branch 和当前工作树比完整 SHA 更方便；索引水位、图缓存水位、git checkout 三者又常由不同组件维护。

**How to avoid:**
manifest 三 SHA 硬相等；评测前 fail-closed 校验，响应必须回 `as_of/commit_sha`；位置核验从 `git show <sha>:<path>` 等不可变 blob 读取。路径、qualified symbol、range 共同标识，禁用裸名和数据库 ID 作为 gold。

**Warning signs:**
- 同一 case 重跑 Recall 不变但行号不断变化；
- 报告只有 branch，没有完整 SHA/index watermark；
- `file:line` 检查读取当前工作树；
- rename 后旧路径仍被判正确。

**Phase to address:** B0 定 manifest 与位置核验器；B3 将 `as_of` 和证据状态焊入统一响应；B5 设 INVALID-run 守门。

---

### Pitfall 2: 指标分母或“算命中”规则未锁，分数可被口径操纵

**What goes wrong:**
无 gold query 被当 Recall=1、无预测被当 precision=1；Symbol 别名重复占满 top5；Process 只要名字相似就算对；edge precision 只抽系统已经解析的边；trace 只核首尾不核中间边。实现不变，改几行 evaluator 就能“提升”。

**Why it happens:**
代码图对象有多重身份与多条可行路径，普通 IR 指标不能直接套用；团队容易先写公式，后补标注语义。

**How to avoid:**
先锁上文指标表和 canonical identity；零分母统一 `N/A` 并显式计 coverage；正负样本分开；Process 等价路径在看预测前标注；edge 以独立 callsite 样本为母集；trace 每条相邻边和每个位置都验证。

**Warning signs:**
- precision 上升同时 resolved 数量骤降；
- top5 含同一符号多个别名/重载投影；
- evaluator 中出现“expected 为空记 1.0”而报告未单列空 gold；
- Process 命中靠名称 substring；
- trace 成功但中间步骤无法在图中复现。

**Phase to address:** B0 锁 evaluator 与双标注规范；B1/B2 分别产 edge/Process gold；B5 冻结 evaluator hash。

---

### Pitfall 3: overall 掩盖语言、框架或入口退化

**What goes wrong:**
Python/Django/API 样本多，overall 提升覆盖 TS/Vue/event 的显著退化；或简单 direct-call 样本淹没 receiver/import alias。结果与“按语言提升 resolved 边、入口可查”的里程碑目标脱节。

**Why it happens:**
micro 聚合天然偏向样本多的桶；三维全交叉又会产生稀疏桶，团队遂退回一个总均值。

**How to avoid:**
按 case macro；固定语言/框架/入口桶及受保护交叉桶；每桶带原始 n/分子/分母/CI；稀疏桶标不足并补样，不借 overall 判绿。报告同时列最差桶、最大回退桶和 case-level diff。

**Warning signs:**
- 报告只有 overall；
- 改 TS resolver 后 Python 样本占比也变化；
- 分桶没有 n；
- 某桶没有数据却显示 0 或绿色；
- TS/JS 被永久合并，无法看 receiver/alias 改动效果。

**Phase to address:** B0 固定 stratification；B1/B2 补齐优先语言与入口样本；B5 实施“overall 不可抵消受保护桶回退”。

---

### Pitfall 4: baseline、开发集和阈值互相污染

**What goes wrong:**
团队反复查看 test 失败并针对单例调 prompt/权重；同一目标 Symbol 的多条改写随机分到 dev/test；直接复制 docstring、函数名或路径生成 query；最后再把当前最好结果保存为“baseline”。这是过拟合，不是提升。

**Why it happens:**
单仓样本有限，人工写 query 时已看代码；golden fixture 又与实现同仓可见，最容易被无意调参。

**How to avoid:**
- B0 先跑冻结 v0.22 baseline，再开放算法开发。
- 按 target family/module/Process family 分组切分，近重复 query 必须同 split；禁止随机按 query 行切。
- `dev` 可见、`locked_test` 仅 CI 汇总、`holdout` 只在相位/里程碑验收打开。
- query 作者与 gold 标注者分离；真实 issue/运行迹象优先。合成 query 必须标 source，并检查是否泄漏 symbol/path/docstring。
- baseline、threshold、case fixture 分文件、分 review；新增 case 不重写历史 baseline，形成新 benchmark_version。

**Warning signs:**
- test query 含精确函数名或路径，而真实用户不会这样问；
- 每次算法提交同时更新 baseline；
- 同一 Process 的多个同义改写跨 dev/test；
- holdout 被日常单测直接打印逐例答案；
- 提升集中在人工刚修改的 case。

**Phase to address:** B0 建 split、去重与访问纪律；B5 才启用 locked/holdout 门禁。

---

### Pitfall 5: resolved edge 的“真值”来自被测图自身

**What goes wrong:**
从现有 `CallEdge` 导出 gold，再评新 resolver；或只人工复核预测出的 resolved 边。前者是自我比较，后者只能估 precision，完全看不到漏掉的 callsite。动态 trace 若被当完整真值，又会把未被测试覆盖但合法的静态边误判为 false positive。

**Why it happens:**
真实程序调用图没有完备 ground truth；动态派发、装饰器、回调和框架注册使纯静态或纯动态证据都不完整。

**How to avoid:**
以源码 callsite 独立分层抽样：按语言、receiver/import alias/member call/直接调用/框架间接调用等构造分桶，标注所有可行 callee。用编译器/LSP、测试动态 trace、人工源码审查作多源证据并保存 provenance。动态 trace 是已执行边的下界，不是完整负例集合；precision/recall 只在明确标注的 callsite universe 内计算。

**Warning signs:**
- edge benchmark 没有 unresolved callsite；
- recall 分母等于当前系统 resolved 边数；
- 新 resolver 关闭大半解析后 precision 大涨、报告仍判绿；
- 未执行到的边一律标 false；
- 标注没有 callsite line/column。

**Phase to address:** B0 定抽样与证据规范；B1 先补 gold 再改 TS/JS、Python resolver；B5 报 resolved coverage 与 P/R 双指标。

---

### Pitfall 6: Process/impact/trace 的 gold 循环定义，负路径缺席

**What goes wrong:**
用当前 CallEdge 生成 Process，再用这些 Process 评价检索；用 BFS 可达集当 impact gold，再评价同一个 BFS；trace 只放已知最短可达对。三项都会接近满分，却无法发现入口漏检、错误 resolved 边、不可达对返回假路径或错误类型漂移。

**Why it happens:**
Process 和 impact 都是派生对象，人工标完整路径成本高；正样本 demo 更直观，错误路径被当异常处理而非产品契约。

**How to avoid:**
- Process gold 从入口语义和真实业务流标注，记录入口、结果/终点、必经步骤及允许的可选分支，不从被测 Process 表反导。
- impact case 固定 seed、方向、边类型、深度与上限；gold 由源码审查、历史改动/测试影响证据和独立图查询交叉裁决，明确它只代表该 scope。
- trace 正样本覆盖多跳、歧义、环；负样本覆盖不可达、缺 source/target、同名歧义、stale、权限/exclusion。错误路径用稳定枚举而非自由文本。
- Process/trace 返回的每一步都做 commit blob `file:line` 核验；截断必须说明在哪一层发生。

**Warning signs:**
- Process Recall@3 的 gold ID 来自同一次索引；
- impact gold 与生产 BFS 共用同一个函数；
- trace benchmark 没有负样本；
- 所有错误都返回 `found=false` 或空列表；
- Process 名称正确但入口/步骤/位置错误仍算命中。

**Phase to address:** B0 建正负 case 骨架；B2 建独立 Process 标注；B3 建 trace/impact 证据验证与稳定错误词表；B5 锁负路径门禁。

---

### Pitfall 7: 延迟/token 被缓存、失败过滤和截断“优化”

**What goes wrong:**
只测热缓存成功请求，timeout 和错误从样本删除；减少候选或提前截断让延迟/token 好看，却把 gold 在 retrieval 或序列化阶段丢掉。平均值进一步掩盖长尾。

**Why it happens:**
性能与质量由同一预算耦合；不同入口又有不同序列化和 agent prompt 开销，单个 service timer 不代表用户等待。

**How to avoid:**
统一入口端到端计时；冷/热分开；所有 case 进入 availability/timeout 分母，成功与错误各报 p50/p95。逐阶段记录候选数、gold 到达、耗时、token、截断前后数量和原因。质量—成本报告必须配对到同一 case/run，不能拿不同样本比较。MCP、Chat、Django、npm、task 各跑同一 conformance/perf case。

**Warning signs:**
- p95 下降但 Recall 同时下降；
- 报告没有 timeout/error 数；
- `truncated` 永远 false 或根本不存在；
- token 只统计输出，不统计输入/工具结果注入；
- npm/task 延迟明显不同却没有分面数据。

**Phase to address:** B0 先定义计时点；B3 输出分层截断元数据；B4 做跨消费面性能冒烟；B5 纳入观测和趋势。

---

### Pitfall 8: MCP 只对齐工具名，schema 与运行时产物仍漂移

**What goes wrong:**
本仓现有 `test_mcp_package_alignment.py` 能抓服务端有而 npm 白名单缺失，但只比较工具名；`TOOL_SCHEMA_SNAPSHOT` 主要锁 request/response 键集合，未完整覆盖类型、required/default、约束、`additionalProperties`、output schema、错误语义、description/annotations。源码对齐也不代表发布的 npm tarball、task 镜像和 Chat 注册表对齐。

**Why it happens:**
工具定义存在 server serializer、Agent schema、Django MCP、npm 静态白名单、容器 allowed tools 多份投影；snapshot 更新容易变成“测试红就重生成”。子模块缺失时 skip 还可能让 CI 假绿。

**How to avoid:**
1. 建 canonical tool manifest：name、description、annotations、input/output JSON Schema、错误枚举、truncation/as_of 字段、contract version。其他消费面由它生成或适配，不手抄。
2. 对 schema 做规范化后语义 hash，不能只比键名或原始 JSON 字节顺序；输入、输出都运行 JSON Schema 校验。
3. conformance matrix 覆盖同一主体/权限下的 tools discovery、合法最小/完整/边界请求、非法请求、成功输出、typed error、截断。工具集可因授权不同而变，但相同 principal/scope 必须一致。
4. CI 测**构建产物**：npm `pack` 后启动 stdio server、task 镜像内 discovery、Django MCP/Chat 运行时注册；必需产物缺失应 fail，不得 skip。
5. breaking change 显式升级 contract version 并提供迁移/兼容窗口；新增可选字段与新增 required 字段分级处理。旧客户端 conformance fixture 常驻。
6. MCP 官方要求工具 server 声明 `tools` capability；工具列表动态变化时声明 `listChanged` 并发送 `notifications/tools/list_changed`，客户端收到后重新 `tools/list`。不能假设会话启动时发现一次就永久有效。

**Warning signs:**
- 工具数相同但某消费面的 required/default/type 不同；
- server 单测绿，发布 npm 调用 404 或参数校验失败；
- CI 因子模块/产物缺失而 skip 对齐测试；
- schema fixture 与实现同提交被无说明重生成；
- 部署新增工具后长会话仍看不到；
- output 无 schema，客户端只能猜自由文本。

**Phase to address:** B4 建单一 manifest、生成链、运行时 conformance 和版本策略；B5 持续跑构建产物矩阵。

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 先改算法，后保存“baseline” | 很快展示高分 | 无法证明相对 v0.22 提升 | never |
| gold 从当前图/Process 表反导 | 标注成本低 | 自我比较、系统性漏报不可见 | 仅用于 harness 冒烟，不得作质量结论 |
| 只有正样本 | 成功率好看 | 假路径、歧义、稳定错误契约无人管 | never |
| overall 单一门禁 | 规则简单 | 小语言/框架/入口退化被掩盖 | 仅作摘要，不得单独判定 |
| 无预测 precision=1 | 避免除零 | 通过“不做事”刷高分 | never；应为 N/A + coverage |
| MCP 仅比较工具名 | 实现便宜 | 类型/默认值/输出/错误语义继续漂移 | 只能作第一层 smoke |
| 只测源码，不测 npm tarball/镜像 | CI 快 | 发布物与源码不同仍假绿 | 本地快速测试可用，发布门禁不可用 |
| 测试失败自动刷新 snapshot | 省 review | 门禁退化为橡皮图章 | never |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Git/index/cache | branch 名相同即认为同快照 | 三方完整 SHA 相等，否则 run INVALID |
| Qdrant/BM25/embedding | 只保存最终 top-k | 保存 retrieval/rerank/return 三层结果和截断 |
| LLM reranker | 单跑一次与确定性 baseline 比 | 配对多轮、固定模型/config，分离确定性层与随机层 |
| GitNexus 对标 | 只复制工具名/Process 展示 | 对齐可验证能力：process-grouped hybrid query、入口类型、步骤与 `file:line`、impact/trace 证据 |
| MCP discovery | 会话启动只拉一次工具列表 | 声明/处理 `listChanged`，变化后重新 `tools/list` |
| MCP output | 只返回 text | 提供 output schema 与 structured content；客户端验证，兼容期可同时给序列化 text |
| npm MCP | 比 `src/tools.ts` 名称集合 | 构建 tarball 后运行 discovery + schema hash + call conformance |
| task 容器 | 只检查镜像构建成功 | 在镜像内用实际 allowed tools/principal 跑 discovery 和最小调用 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 只测热缓存 | 本地极快、首个用户很慢 | 冷/热独立 run，记录 cache state | 首次查询或索引水位变化 |
| 平均延迟 | 少数超时被均值掩盖 | p50/p95 + timeout rate + per-bucket | 图扇出和 Process 数分布长尾时 |
| top_k 前过早截断 | 延迟降、Recall 降 | 每层 gold 到达率与 truncation reason | 大仓或 token budget 紧时 |
| 返回全量 Process/impact | token 与序列化暴涨 | 有界结果、稳定排序、显式截断与 continuation | 高扇出入口/大社区 |
| benchmark 自身重复索引 | 方差主要来自构建 | baseline 固定索引 artifact；另设 cold-build benchmark | 多轮比较时 |
| 各入口重复 LLM 包装 | Chat/npm/task token 不可比 | 同一 core result + 各 adapter 独立 token/latency 记账 | 契约漂移或 prompt 膨胀时 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| fixture 收录私有源码/真实 query 原文 | benchmark 入库泄密 | 只存必要标识与脱敏文本；私有 fixture 分级存放 |
| 负样本包含 excluded 文件却仍返回位置 | 排除规则被图查询绕过 | exclusion case 常驻，任何符号/路径泄露即失败 |
| 日志记录完整工具输入/输出 | 代码、凭证、上游异常泄露 | 结构化计数与 hash；文本过 `redact_secrets_in_text`，ledger 走 `redact_for_ledger` |
| 跨消费面用不同测试身份 | 工具集差异被误判或真实越权被掩盖 | conformance 固定 principal/scope，并另测无权限主体 |
| MCP annotations 当可信授权 | 恶意/漂移 metadata 诱导调用 | 按 MCP 规范视 annotations 为不可信；授权由服务端执行 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 返回 `file:line` 但不带 commit | 用户无法复核，链接可能已漂移 | `repo@sha:path:start-end` + location status |
| 无结果、截断、错误都返回空数组 | 用户误判“仓内没有” | 稳定 error/degradation/truncation 字段 |
| Process 名称命中但步骤不可信 | 产生“完整执行流”错觉 | 展示入口、必经步骤、边置信度、断链/截断 |
| impact 不声明 scope | 用户把有界静态近似当完整影响面 | 输出方向、edge types、depth、commit、coverage |
| 跨入口字段/错误文案不同 | Agent 需为每面写特判 | canonical structured contract + adapter conformance |

## "Looks Done But Isn't" Checklist

- [ ] **Baseline：** 是否确由未修改 v0.22.0 在冻结 commit/cases/config 上运行，而非当前实现回填？
- [ ] **同 commit：** `repo/index/gold` 三 SHA 是否完全相等，`file:line` 是否从 commit blob 验证？
- [ ] **指标：** 每项是否写明分母、零分母行为、canonical identity 和等价路径规则？
- [ ] **分桶：** 是否同时报告语言/框架/入口的 n、分子、分母、CI 与最差桶？
- [ ] **负样本：** trace/no-answer 是否覆盖不可达、歧义、stale、权限、exclusion 和缺失端点？
- [ ] **edge：** recall 分母是否来自独立 callsite 样本，而非当前 resolved 边？
- [ ] **Process：** gold 是否独立于被测 Process 生成器，步骤级位置与边是否核验？
- [ ] **性能：** timeout/error 是否仍在分母，冷/热是否分开，截断是否逐层可观测？
- [ ] **MCP：** 是否比较完整 input/output schema、错误枚举和运行时 discovery，而不只是工具名？
- [ ] **发布物：** npm tarball 与 task 镜像是否真实运行 conformance，缺失时是否 fail 而非 skip？
- [ ] **阈值：** 是否在 baseline 后单独 review 锁定，更新是否有逐 case/逐桶理由？
- [ ] **可复现：** manifest、fixture hash、配置 hash、seed、硬件与原始 per-case 输出是否保存？

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| baseline 已被当前实现污染 | HIGH | 回到 v0.22.0 commit/build，重建同 SHA 索引并重跑；作废旧报告 |
| gold 泄漏/过拟合 | HIGH | 按 target family 重切 split，重写 locked/holdout query，提升 benchmark_version |
| 分母口径错误 | MEDIUM | 修 evaluator、保留旧报告但标 invalid，全部实现重跑，不做分数换算 |
| `file:line` 漂移 | MEDIUM | 引入 blob verifier；无法核验的历史 case 降为 unverified，不计成功 |
| 某语言被 overall 掩盖 | MEDIUM | 冻结该桶回归 case，补样后设独立门；不得只调 overall 权重 |
| MCP schema 已漂移发布 | HIGH | 从 canonical manifest 生成差异矩阵；兼容适配/版本升级；补旧客户端 conformance |
| 性能数据过滤失败样本 | LOW | 从原始 per-case 事件重算；若原始事件缺失则整轮重跑 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| commit/位置伪证据 | B0 + B3 | 三 SHA 不同即 INVALID；每个返回位置过 blob verifier |
| 分母/命中规则漂移 | B0 | evaluator fixture + 手算小样；零分母为 N/A |
| overall 掩盖分桶 | B0 + B5 | 每桶 n/CI；受保护桶回退时 overall 再高也失败 |
| baseline/数据泄漏 | B0 | v0.22 build provenance；group split/近重复审计；locked/holdout 隔离 |
| edge 自我评测 | B0 + B1 | 独立 callsite universe；resolved coverage + precision/recall |
| Process/impact/trace 循环 gold | B2 + B3 | 独立双标、负路径、逐边/逐位置验证 |
| 延迟/token 美化 | B3 + B5 | 冷热 p50/p95、timeout、token、每层 truncation 同报告 |
| MCP 契约漂移 | B4 + B5 | canonical schema hash + npm/task/server/Chat/Django 运行时 conformance |

## Sources

- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)（HIGH）：`tools/list`、`tools/call`、`listChanged`、input/output JSON Schema、structured output、错误与安全要求。
- [GitNexus Processes & Execution Flows](https://abhigyanpatwari-gitnexus.mintlify.app/concepts/processes-and-flows) 与 [Processes Resources](https://abhigyanpatwari-gitnexus.mintlify.app/api/resources/processes)（HIGH）：Process 是入口出发的调用序列；process-grouped search；步骤含 symbol 与文件位置；入口类型包括 api/cli/event/init/unknown；遍历、置信度与截断是能力的一部分。
- [CodeSearchNet Challenge](https://arxiv.org/abs/1909.09436) 与 [官方仓库](https://github.com/github/CodeSearchNet)（HIGH）：代码检索数据去近重复、按仓/文件归组切分，避免相同代码跨 train/test；数据携带 repo/path/function/URL 等可核验证据。
- Helm et al., [Total Recall? How Good Are Static Call Graphs Really?](https://doi.org/10.18420/se2025-28)（HIGH）：真实程序完整调用图 ground truth 通常不可得；固定入口和输入语料的动态 baseline 是近似，覆盖不足会扭曲 precision/recall，不能把动态未观察到当静态 false positive。
- [Sentence Transformers Information Retrieval Evaluator](https://sbert.net/docs/package_reference/multi_vector_encoder/evaluation.html)（HIGH）：Recall@k、Precision@k、MRR、nDCG 等标准 IR 指标；本文在此基础上补代码图 canonical identity、负样本与 commit 证据。
- 本仓事实（HIGH）：`server/codegraph/services/repo_router_eval.py` 已有 per-case macro、固定 seed bootstrap CI、逐例 diff；`repo_route_recall_eval.py` 已证明“只测候选后排序会漏掉召回层失败”；`server/tests/mcp_tools/test_schema_snapshot.py` 当前主要锁键集合；`test_mcp_package_alignment.py` 当前只比工具名且子模块缺失会 skip；`server/tests/agents/test_tool_contracts.py` 已有显式刷新 fixture + review 的好模式。
- Agent Retrieval Bench、SWE-Explore（MEDIUM，2026 新研究）：支持冻结 base commit、line-level ground truth、固定预算、正负 retrieval 和 context efficiency；适合作为设计参照，但 v0.24 不应直接照搬其目标值。

---
*Pitfalls research for: v0.24.0 单仓图查询对齐 GitNexus*
*Researched: 2026-08-24*
