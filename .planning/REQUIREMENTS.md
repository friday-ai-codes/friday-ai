# Requirements — v0.22.0 代码智能图分析升级（对标 GitNexus）

**Milestone:** v0.22.0
**Defined:** 2026-08-09
**Source:** 与 GitNexus（本地代码知识图谱 + MCP 工具引擎）的能力对比调研：Friday 赢在服务端多仓/权限/观测/交付流水线耦合，输在静态图分析深度（impact / trace / 执行流 / 聚类 / PDG 全缺）。本里程碑在现有 codegraph/RAG 底座上补齐图分析能力。领域调研见 `.planning/research/`（STACK / FEATURES / ARCHITECTURE / PITFALLS / SUMMARY，commit `8cdd47ce`）。
**前置:** v0.21.0（Phases 117–120）已验证归档；`CallEdge` 已有外键化 `caller_symbol`/`callee_symbol`；networkx 3.6.1 已在依赖树；`GalaxyGraphCache` 提供签名失效范式先例。

> 需求以「用户/agent 能做到什么」表述，不描述实现。已定裁决：图引擎用 networkx（rustworkx 缺社区检测暂不引入）；社区检测用内置 `louvain_communities(seed=固定)`（leidenalg GPL-3.0 否决，Leiden 列触发条件升级项）；污点分析外购 Semgrep CE（1.172.0+，独立 CLI）不自研 PDG。

---

## v0.22.0 Requirements

### GRAPH — 内存图服务（地基）

- [x] **GRAPH-01**: Agent/工具查询任一已索引仓库时，系统提供该 `(repository, branch)` 的内存符号图（`Symbol`/`CallEdge`/`ChunkEdge`/`CrossRepoApiCall` 装配），首次构建后命中缓存，不重复建图
- [x] **GRAPH-02**: 索引水位（`last_indexed_commit_sha`）或边构建代数变化后缓存自动失效重建；取图时校验水位，不返回「水位已更新但边未建完」的半新图
- [x] **GRAPH-03**: 缓存带字节预算 LRU 逐出 + single-flight 防并发构建风暴；超预算大仓有降级路径（不缓存/按需子图），进程不 OOM
- [x] **GRAPH-04**: 图读取层统一收口权限校验与 exclusion 过滤（fail-closed），排除文件在所有图分析工具输出中不可见

### IMPACT — 影响面与调用路径

- [x] **IMPACT-01**: 用户/agent 对任一符号执行 impact 查询，获得反向依赖的深度分组结果（d1/d2/d3 = WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING 语义标签）
- [x] **IMPACT-02**: impact 每条边带 confidence 分档（解析边 / 裸名边 / 跨仓 `match_confidence` 原值）+ reason 说明，调用方可用 `min_confidence` 参数自选精度/召回
- [x] **IMPACT-03**: impact 可穿仓库边界（沿 `CrossRepoApiCall` 边），跨仓结果标注 `cross_repo: true` 与独立置信档——改后端 `Endpoint` 能列出受影响的前端调用点
- [x] **IMPACT-04**: impact 输出带确定性风险分级（LOW/MEDIUM/HIGH/CRITICAL，阈值判定可解释、不走 LLM）与截断 summary 计数（agent 知道被截断了多少）
- [x] **IMPACT-05**: trace 工具：任意两符号间有向最短路，逐跳渲染 file:line + 边类型/置信度；符号重名时返回消歧候选列表，绝不静默取第一个
- [x] **IMPACT-06**: impact/trace 经 MCP 工具 + agents 对话工具双面暴露，输出带索引 staleness 提示（「索引落后 N commits」）

### DIFF — detect_changes 与编码链闭环

- [x] **DIFF-01**: 用户/agent 对分支 diff（base 锚定 `last_indexed_commit_sha`，保证与 Symbol 行号同源）执行 detect_changes，获得受影响符号清单（changeType / 行数 / file:line）与批量 impact 结果
- [x] **DIFF-02**: detect_changes 支持 compare + base_ref 场景（MR diff）；文件重命名被识别、不产生误报
- [x] **DIFF-03**: 编码任务容器在提交前可经既有 MCP PAT 白名单调用 detect_changes 自查（受影响清单进提交决策）
- [x] **DIFF-04**: MR 描述自动附影响面报告（Changes / Affected / Risk / Recommendations 四段结构），fail-soft 不阻断建 MR 主流程

### MOD — 社区检测与模块摘要

- [x] **MOD-01**: 每仓图上运行社区检测（networkx `louvain_communities` 固定 seed），社区归属以独立模型 + 软引用落库（⛔ 不加在 `Symbol` 上——增量索引 per-file 删建会丢），增量索引后自动刷新
- [x] **MOD-02**: 社区成员指纹稳定化——指纹（Jaccard 阈值）判定未变的社区跳过摘要重生成；「无代码变更连续重建两次，LLM 调用数为 0」是验收用例
- [x] **MOD-03**: 每个社区生成 LLM 模块摘要（关键文件 / 入口 / 职责叙述，LLM 调用赋 `call_source`）
- [x] **MOD-04**: 模块摘要注入 RepoRouter adapter 层（evidence 侧）与技术方案生成 prompt（⛔ `repo_router_v2.py` 是冻结面不许动）；消费端按相关度排序 + token 预算截断，不全量灌入

### EXEC — 执行流追踪

- [x] **EXEC-01**: 以 `Endpoint` 为确定性入口正向追踪执行流，遵守 BFS 纪律（maxDepth 10 / maxBranching 4 / minSteps 3 / 只走置信度 ≥0.5 的边 + 去重），结果存 Process 模型
- [x] **EXEC-02**: 执行流带社区归属分类（intra/cross_community），可经 MCP 工具查询
- [x] **EXEC-03**: detect_changes / impact 输出回填 `affected_processes` 叙事层（受影响执行流名称清单，进 MR 描述增值段）

### RENAME — 改名预览

- [x] **RENAME-01**: rename_preview 只读工具：图解析引用 + grep 文本兜底双源合并，逐条带 graph/text_search 置信标签、context 片段，按文件分组输出；显式声明动态引用/字符串模板的覆盖限制；**只出清单不改写**，apply 由编码代理自行执行

### TAINT — Semgrep 安全门禁

- [ ] **TAINT-01**: MR 流程可触发 Semgrep diff-aware 扫描（`--baseline-commit` 取 merge-base），只报本次 MR 新增 finding；Semgrep 以独立 CLI/venv 形态集成，不进 server Python 依赖树
- [ ] **TAINT-02**: finding 带 severity 分级进 MR 描述/评论；门禁默认报告不阻断（advisory 起步）；`nosemgrep` 误报通道生效
- [ ] **TAINT-03**: 门禁文案如实声明 CE 版函数内 taint 边界（不虚假承诺跨函数/跨文件）；Pro 能力经 `SEMGREP_APP_TOKEN` opt-in

### LSP — 解析精度

- [ ] **LSP-01**: server 镜像补齐 Node/Go 运行时前提，volar/gopls 带可用性探测 + fail-soft 降级 + 孤儿进程清扫；产出开启前后的抽取质量/耗时基准报告，**默认值翻转由基准数据决定**（本里程碑不盲翻）

### SKILL — 工作流固化

- [ ] **SKILL-01**: impact-analysis / refactoring 两个工作流 skill 进 `@friday-ai-codes/skills` 同源分发（复用 v0.17.0 机制），编码容器与外部 agent 可用

---

## Future Requirements（本里程碑不做，登记备查）

- **detect_impact 式 MCP 编排 prompt**（detect_changes→context→impact 工作流）— 等工具面稳定（v2+）
- **taint 门禁台账化**（主干 full scan + finding 状态机 + 跨分支 triage）— 等门禁用量验证（v2+）
- **模块摘要进 Galaxy 可视化 / 社区着色** — 展示层增值，不影响 agent 链路
- **Leiden 社区检测升级** — 触发条件：指纹跳过后摘要重生成率仍超阈值，或部署方接受 GPL 时 opt-in
- **rustworkx 图引擎升级** — 触发条件：单仓 >50 万边 / impact p95 >2s / 缓存 >2GB（STACK.md 已记录 adapter seam 策略）
- **context 符号 360 度视图工具**（GitNexus `context` 对标）— impact/trace 稳定后自然演化

## Out of Scope（显式排除）

| 项 | 原因 |
|---|---|
| 开箱体验/安装向导对标 | 用户明确排除 |
| 自研 PDG/CFG/污点分析 | 编译器级工程量；Semgrep 外购已定（业界一致） |
| 新语言 extractor（Java/Kotlin/Rust 等） | 每语言成本大且独立，单独立项 |
| rename 自动 apply（服务端改写用户仓库） | 危险的新写路径；preview + 编码代理执行已覆盖 |
| 裸 Cypher/原始图 dump 面向 agent | GitNexus skills 自己都引导「smart tools, not raw queries」 |
| taint 硬门禁默认阻断、无 override | Semgrep 实践证明会被整体绕过 |
| 承诺跨函数/跨文件 taint（CE 版） | Pro 付费能力；虚假承诺产生虚假安全感 |
| 每请求实时全图重算 | 服务端多仓大图延迟不可接受，缓存方案已定 |

## Traceability

<!-- roadmap 创建于 2026-08-09（Phases 121–127），27/27 需求全部映射，无孤儿、无重复 -->

| Requirement | Phase | Status |
|-------------|-------|--------|
| GRAPH-01 | Phase 121 | Complete |
| GRAPH-02 | Phase 121 | Complete |
| GRAPH-03 | Phase 121 | Complete |
| GRAPH-04 | Phase 121 | Complete |
| IMPACT-01 | Phase 122 | Complete |
| IMPACT-02 | Phase 122 | Complete |
| IMPACT-03 | Phase 122 | Complete |
| IMPACT-04 | Phase 122 | Complete |
| IMPACT-05 | Phase 122 | Complete |
| IMPACT-06 | Phase 122 | Complete |
| DIFF-01 | Phase 123 | Complete |
| DIFF-02 | Phase 123 | Complete |
| DIFF-03 | Phase 124 | Complete |
| DIFF-04 | Phase 124 | Complete |
| MOD-01 | Phase 125 | Complete |
| MOD-02 | Phase 125 | Complete |
| MOD-03 | Phase 125 | Complete |
| MOD-04 | Phase 125 | Complete |
| EXEC-01 | Phase 126 | Complete |
| EXEC-02 | Phase 126 | Complete |
| EXEC-03 | Phase 126 | Complete |
| RENAME-01 | Phase 126 | Complete |
| SKILL-01 | Phase 126 | Pending |
| TAINT-01 | Phase 127 | Pending |
| TAINT-02 | Phase 127 | Pending |
| TAINT-03 | Phase 127 | Pending |
| LSP-01 | Phase 127 | Pending |

**Coverage:** 27/27 mapped（GRAPH 4 / IMPACT 6 / DIFF 4 / MOD 4 / EXEC 3 / RENAME 1 / TAINT 3 / LSP 1 / SKILL 1）— 无孤儿、无重复。

> 注：立项时页脚记「24 条需求」为计数笔误，实际清单为 **27 条 REQ-ID / 9 分类**（上表逐条可数）。

*Last updated: 2026-08-09 — Phase 121 完成，GRAPH-01~04 交付（内存图服务基座）*
