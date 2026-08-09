# Feature Research

**Domain:** 代码智能图分析（graph-based code intelligence for AI coding agents），对标 GitNexus
**Researched:** 2026-08-09
**Confidence:** HIGH（GitNexus 全部工具契约来自官方 Mintlify docs 一手引用；Semgrep 来自官方 docs；Sourcegraph / Aider 来自官方文档与源码）

> 范围限定：只研究 v0.22.0 净新增功能（impact / trace / detect_changes / 社区检测+模块摘要 / 执行流 / rename_preview / Semgrep taint 门禁）。已有能力（hybrid 检索、grep、find_related、RepoRouter、CrossRepoApiCall、Galaxy 可视化、索引管线）不重复研究。

## 一手调研：GitNexus 工具契约（问题 1）

以下输入输出格式全部摘自 GitNexus 官方文档（https://abhigyanpatwari-gitnexus.mintlify.app），是设计 Friday 同类 MCP 工具时的直接参照。

### `impact`（blast radius 分析）

**输入参数：**

| 参数 | 说明 |
|------|------|
| `target` | 函数/类/方法/文件名（如 `"validateUser"`、`"src/auth/validator.ts"`） |
| `direction` | `"upstream"`（谁依赖我，最常用）/ `"downstream"`（我依赖谁） |
| `maxDepth` | 最大遍历深度，推荐 1–5 |
| `relationTypes` | 边类型过滤：`CALLS` / `IMPORTS` / `EXTENDS` / `IMPLEMENTS`，省略则用 usage-based 推断 |
| `includeTests` | 是否含测试文件（想知道哪些测试会挂时设 true） |
| `minConfidence` | 边置信度阈值 0–1（降低可多召回、代价是误报） |
| `repo` | 多仓索引时必填 |

**输出结构（关键设计点）：**

- `risk`：整体风险 `LOW` / `MEDIUM` / `HIGH` / `CRITICAL`，有明确判定标准（如 MEDIUM = 5–15 个受影响符号、2–5 条受影响流程、多模块）
- `summary`：`directCallers` / `affectedProcesses` / `affectedModules` / `totalAffected` 四个计数
- `byDepth`：**按深度分组 + 语义标签**——`d1` = "WILL BREAK"（直接调用者，必须更新）、`d2` = "LIKELY AFFECTED"（间接依赖，可能要改）、`d3` = "MAY NEED TESTING"（传递影响，需测试）。每个符号带 `name` / `type` / `filePath` / `line` / `edgeType` / `confidence`
- `affected_processes`：受影响执行流列表，标注 target 出现在流程第几步（`step` / `totalSteps`）
- `affected_modules`：受影响功能模块，分 `direct`（d=1 命中）与 `indirect`（d≥2 命中）

**关键洞察**：深度分组 + 每条边独立 `confidence` + 语义化风险标签，是让 LLM agent 直接可消费的核心设计——agent 不需要自己解释图遍历结果，工具已经把"该做什么"编码进了分组语义（d1 必改、d2 复查、d3 补测试）。

### `detect_changes`（diff → 受影响符号 → 受影响流程）

**输入参数：**

| 参数 | 说明 |
|------|------|
| `scope` | `"unstaged"`（默认）/ `"staged"`（提交前检查）/ `"all"` / `"compare"`（PR 影响分析，需 `base_ref`） |
| `base_ref` | 比较基线：`"main"` / `"HEAD~3"` / commit hash |
| `repo` | 多仓时必填 |

**输出结构：**

- `changed_symbols[]`：`uid` / `name` / `type` / `filePath` / `changeType`（modified/added/deleted）/ `linesChanged`
- `affected_processes[]`：`name` / `affectedSteps[]`（流程中哪几步被改到）/ `totalSteps` / `module`
- `risk` + `summary`（filesChanged / symbolsChanged / processesAffected / modulesAffected）

**官方定位**：pre-commit 工作流的一环（文档给出 git pre-commit hook 与 GitHub Actions PR 检查两个集成示例，HIGH/CRITICAL 时警告或阻断）；有显式的**索引新鲜度限制声明**——索引过期会漏掉新符号，工具提示先重建索引。

### `context`（符号 360 度视图）

- **输入**：`name` / `uid`（零歧义查找，优先）/ `file_path`（重名消歧）/ `include_content`（默认关，开了才带源码）/ `repo`；三者至少给一个
- **输出**：`symbol` 元数据（含所属 `module` 社区）+ `incoming`（分类：calls / imports / extends / implements）+ `outgoing`（同分类）+ `processes[]`（参与的执行流及步骤位置）
- **消歧协议**：重名时返回 `disambiguation[]` 候选列表（uid + filePath + line），让 agent 二选一——不猜、不静默取第一个

### `query`（概念 → 执行流分组检索）

- **输入**：`query` 自然语言 + `task_context`（"我在做什么"）+ `goal`（"我想找什么"）两个排序增强参数 + `limit`（默认 5，1–20）+ `max_symbols`（默认 10，每流程符号上限）+ `include_content`（默认关）
- **输出**：`processes[]`（按 RRF 相关度排序的执行流）+ `process_symbols[]`（参与符号，带 uid/process 归属/step_index）+ `definitions[]`（匹配但不属于任何流程的独立类型）
- **截断策略**：limit × max_symbols 双维度截断 + `include_content` 默认关闭控 token——这是所有工具的统一纪律

### `rename`（多文件协同改名，问题 5）

- **输入**：`symbol_name` 或 `symbol_uid` + `new_name` + `file_path`（消歧）+ **`dry_run` 默认 `true`** + `repo`
- **输出**：`changes[]` 按文件分组，每条 edit 带 `line` / `old_text` / `new_text` / **`confidence`（二值：`"graph"` = 图边高置信、`"text_search"` = regex 兜底低置信）** / `context`（周边代码片段供人审）；`summary`（totalEdits / filesAffected / graphEdits / textSearchEdits）；`applied` 标志
- **官方工作流**：preview → 人审 text_search 项 → `dry_run:false` 应用 → `detect_changes()` 验证范围 → 独立 commit
- **显式限制声明**：抓不到动态属性访问（`obj["validateUser"]()`）、外部配置里的字符串、未索引文件

**对问题 5 的回答**：GitNexus 的 rename 是"preview 默认 + 可选 apply"。**只读 preview 是它设计的重心**——confidence 二分、context 片段、强制先审后改的 checklist 全部服务于 preview 环节；apply 只是最后一步落盘。Friday 场景（服务端工具、消费者是编码代理而非本地 CLI 用户）只做只读 preview 完全成立：apply 半边由编码代理拿着清单自己执行编辑，服务端直接改写用户仓库反而引入危险的写路径。**table stakes 是 preview 的质量**：图引用 + 文本兜底双源、逐条 confidence 标注、周边 context、按文件分组、动态引用限制的显式声明。

### Clusters / Processes 资源与模块摘要（问题 3）

**Clusters（Leiden 社区检测）：**

- 资源 `gitnexus://repo/{name}/clusters` 返回 **top 20** 模块：`name`（启发式标签，基于目录模式自动生成）+ `symbols` 计数 + `cohesion`（内聚度百分比，80%+ = 边界清晰的好模块，<40% = 社区过宽）
- 详情资源 `cluster/{name}` 返回成员符号列表（同样 top 20 截断）
- 注意：GitNexus 的模块名是**启发式生成**（`heuristicLabel`），没有 LLM 摘要——这正是 Friday 计划的「LLM 生成模块摘要」可以超越的点

**Processes（执行流）：**

- 入口点检测是**多因子打分**：call ratio（调多被调少 +40~60）、exported（+30）、命名模式（`handle|on|process|execute` +40，`main|run` +50）、路径模式（controller/handler +20）、框架装饰器乘子（`@Controller`/`@app.route` ×1.5–3）；**测试文件排除**
- 追踪算法：从入口 BFS 正向，`maxTraceDepth: 10`、`maxBranching: 4`（防工具函数爆炸）、`minSteps: 3`（滤掉 A→B 两步平凡流）、`maxProcesses` 按仓库规模动态 `max(20, min(300, symbolCount/10))`、**边置信度 ≥0.5 才参与追踪**（滤掉 fuzzy 匹配导致的跳线）
- 去重两层：子集去重（短 trace 是长 trace 子串则删）+ 端点去重（同 entry→terminal 只留最长）
- Process 分 `intra_community` / `cross_community` 两类，**跨社区流程被标注为架构上最重要的**
- 每个符号有 `STEP_IN_PROCESS` 边带 step 序号，`context` 工具直接透出「此符号在 LoginFlow 第 2/7 步」

**AI agent 怎么消费效果最好（GitNexus 的答案）：**

1. **skills 随索引自动落仓**：`gitnexus analyze` 把 4 个 skill（exploring / debugging / impact-analysis / refactoring）写进 `.claude/skills/gitnexus/`，生成 `AGENTS.md` 引用，Claude Code 还注册 PreToolUse hooks（用图上下文增强 grep/glob）
2. **skill = 工作流 + checklist**：每个 skill 定义任务触发条件、工具选择顺序、必查清单（如 exploring：先读 context 资源 → query → context 工具 → process 资源 → 读源码）
3. **「always start with context」**：约 150 token 的轻量资源先行（符号计数、staleness 检查、可用工具），agent 先花小钱确认索引可用再花大钱查询
4. **「smart tools, not raw queries」哲学**：工具返回**预结构化情报**（process 分组、分类引用、深度分组 blast radius），不返回原始图数据——"agent 一次调用拿全上下文（而不是 5–10 次）、小模型也能用好（工具做了重活）"
5. `cypher` 原始查询工具保留为 escape hatch，但 skills 全部引导走 smart tools

### `detect_impact` MCP prompt（问题 4 的编排范式）

GitNexus 除工具外还提供 prompt：`detect_impact(scope, base_ref)` 引导 agent 走四步工作流——① `detect_changes` 找改动符号与受影响流程 → ② 对关键符号跑 `context` 看全引用 → ③ 对高危项跑 `impact` 看 blast radius → ④ 产出结构化 markdown 风险报告（Changes / Affected Processes / Risk Level / Recommendations 四段，含测试建议、review 建议、部署建议）。**prompt 提供工作流逻辑，tool 提供数据**——这个报告结构就是 Friday「detect_changes 接入 MR 描述」的模板参照。

**对问题 4 的回答（受影响流程 vs 受影响符号清单）**：GitNexus 的答案是**两者都给、各司其职**——

- **受影响符号清单**（changed_symbols + impact byDepth）是 coding agent 的**行动指南**：d1 逐条列出"必须更新的 caller"，带 file:line 可直接跳转编辑。没有它 agent 无法行动。
- **受影响流程**（affected_processes）是**风险叙事层**：「LoginFlow 第 2 步被改」比「validateUser 有 23 个 caller」对人类 reviewer 和 MR 描述更有说服力；官方 best practice 明说"Breaking LoginFlow is more critical than a utility function"。
- 对 Friday：**符号清单是 MVP 必需**（编码代理提交前自查靠它行动），**流程叙事是 MR 描述的增值层**（依赖执行流功能先落地）。两者不是二选一，是分层交付。

### 置信度体系（Friday impact 置信度分级的参照）

GitNexus 每条边带 `confidence` + `reason`：

| 分数 | 场景 | reason |
|------|------|--------|
| 1.0 | 同文件引用 | `same-file` |
| 0.85 | import 已解析的跨文件调用 | `import-resolved` |
| ~0.5–0.7 | import 解析失败的模糊名匹配 | `fuzzy-global` |
| ~0.3 | 常见名（`render`/`init`）的极低置信匹配 | `fuzzy-global-low-confidence` |

流程追踪硬性过滤 `MIN_TRACE_CONFIDENCE = 0.5`；impact 让调用方用 `minConfidence` 自选权衡。Friday 的三级来源（解析边 / 裸名边 / 跨仓 `match_confidence`）可直接映射到这套数值 + reason 字符串的呈现方式。

## 竞品交互范式（问题 2）

### Sourcegraph（code navigation）

- **双层精度模型**：search-based（tree-sitter/ctags 启发式，开箱即用、有误报漏报）与 precise（SCIP 编译器级索引，跨仓精确）并存，UI 里 find references 结果**同时展示两类并标注来源**——与 Friday「解析边 vs 裸名边」的置信度分层是同一设计哲学：不隐藏低置信结果，而是标注让用户/agent 自行取舍
- 跨仓导航靠 SCIP 全局唯一 symbol ID + 版本感知解析；find implementations 支持接口→跨仓所有实现
- 定位是「人看的导航」而非「agent 消费的分析」：无深度分组、无风险分级——GitNexus 式的 blast radius 语义化是 agent 时代的增量

### Aider repo map（模块摘要消费的另一个范本）

- tree-sitter 抽定义/引用 → 文件为节点、引用为边建图 → **NetworkX Personalized PageRank** 排序 → 在 **token 预算内**（默认 1k，`--map-tokens` 可调）挑最重要的符号签名塞进每轮 prompt
- 个性化偏置：聊天中已加入的文件出边 ×50、用户提到的标识符 ×10、长而具体的标识符 ×10、引用频次开方衰减
- **对 Friday 模块摘要的启示**：agent 消费图产物的成功范式是「**排序 + 预算截断**，不是全量灌入」。模块摘要喂 RepoRouter / 技术方案生成时应同样按相关度排序、限 token 预算，而非把所有社区摘要拼接
- 反面教训：Aider 的 map 每轮重算（有缓存），Friday 的内存图服务 + 水位失效设计已经规避了这一成本

### CodeQL

- 以编译器级数据流/污点分析为核心，查询语言（QL）表达能力最强，但索引构建重（需编译）、增量差、面向安全审计而非 agent 实时交互。Friday 的定位（tree-sitter 图 + Semgrep 外购 taint）刻意避开了这条重路线——与 PROJECT.md「买不是造」决策一致，本调研确认该取舍与业界一致（GitNexus 同样不做数据流分析）

### Cody（Sourcegraph 的 agent context）

- context 引擎混合 keyword + embedding 检索，近年方向是把 precise code graph 作为 context 源之一。公开资料中无 GitNexus 式的 impact/blast-radius 工具面——确认「图分析工具化给 agent」仍是差异化空间而非红海

## Semgrep taint 门禁在 MR 流程的呈现（问题 6）

来自 Semgrep 官方 docs 的关键实践：

**扫描模式（决定噪声水平的第一因素）：**

- **diff-aware scanning**：MR 场景只报「基线之后新引入」的 finding。基线取 merge-base（`SEMGREP_BASELINE_COMMIT=$(git merge-base main feature-branch)`），非 GitHub/GitLab CI 环境用 `SEMGREP_BASELINE_REF`
- **推荐组合**：主干分支定期 full scan（维护全量 finding 台账）+ MR 分支 diff-aware scan（只看增量）——否则同一 finding 在每个分支重复出现
- **shortest-path-only**：同一 source→sink 组合只报最短路径一条，加速 triage（多路径同 taint 视为重复）

**finding 分级与生命周期：**

- 规则自带 severity（ERROR/WARNING/INFO 三级），平台侧 finding 状态机：Open → Reviewing / Fixing / **Ignored**（须给原因：False positive / Acceptable risk / No time to fix）/ Fixed
- **triage 跨分支生效**：某 finding 在任一分支被 ignore，其他分支/ref 同步 ignore——不用每个 MR 重复处理同一误报
- 误报处理三通道：平台 UI 批量 triage、代码内 `nosemgrep` 注释、**MR 评论回复 `/fp`**（把开发者留在 MR 上下文里完成 triage）
- dataflow traces（source→sink 传播路径逐步展示）随 finding 给出，`--dataflow-traces` CLI 可见

**taint 能力边界（影响 Friday 门禁的承诺口径）：**

- CE 版 taint 是**函数内**（intraprocedural）；跨函数（`--pro-intrafile`）与跨文件（`--pro` + rule 标 `interfile: true`）是 **Semgrep Pro 付费能力**，且跨文件仅支持部分语言、内存要求高（8GB/核、默认 5GB 上限超限自动回退单文件分析、3 小时超时回退）
- 引擎无路径敏感、无指针/别名分析、数组元素不追踪——官方明示的假阴性来源
- **对 Friday 的直接含义**：开源集成只能承诺函数内 taint + 规则库扫 diff，跨函数/跨文件 taint 不可承诺（除非用户自带 Pro license）；门禁文案必须如实声明这个边界，否则「安全门禁」的名号会产生虚假安全感

**门禁呈现的成熟范式（供 MR 集成参照）：**

1. finding 以 MR 评论/描述区块呈现，带 severity、规则 ID、dataflow trace、修复建议
2. 默认**报告不阻断**（或仅 ERROR 级阻断），阻断必须配 override 通道（`/fp`、ignore + 原因）——无 escape hatch 的硬门禁会被团队整体绕过或关闭
3. baseline 语义让存量债务不淹没增量信号

## Feature Landscape

### Table Stakes（对标 GitNexus 的必备项）

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| impact 深度分组 + 语义标签 | GitNexus byDepth d1/d2/d3 = WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING 已是 agent 消费的事实标准 | MEDIUM | 反向 BFS 按深度分桶；标签语义直接写进工具描述与输出 |
| 每条边独立 confidence + `minConfidence` 参数 | GitNexus 1.0/0.85/0.5/0.3 四档 + reason 字符串；调用方自选精度/召回权衡 | LOW | Friday 三级来源（解析边 1.0 / 裸名边 ~0.5 / 跨仓 match_confidence 原值）映射即可，务必带 reason |
| 风险分级 LOW/MEDIUM/HIGH/CRITICAL + 明确判定标准 | GitNexus impact 与 detect_changes 都给 risk + criteria 表；agent 靠它决定下一步动作强度 | LOW | 判定标准（符号数/流程数/模块数阈值）写死可解释，不要 LLM 判 |
| 结果截断 + summary 计数 | 所有 GitNexus 工具 limit/max_symbols 双维截断、include_content 默认关、资源 top-20 | LOW | token 纪律是 agent 工具的生命线；summary 计数让 agent 知道被截断了多少 |
| detect_changes 的 scope 参数（staged/all/compare+base_ref） | GitNexus 四种 scope 覆盖 pre-commit / PR 两大场景；compare+base_ref 是 MR 影响分析的标准形态 | MEDIUM | Friday 场景以 compare（MR diff）为主；git diff 行区间 × Symbol 行区间定位已在里程碑规划 |
| 受影响符号清单（changeType + 行数 + file:line） | coding agent 的行动指南；无清单无法行动（问题 4 结论） | MEDIUM | uid/name/type/filePath/changeType/linesChanged 六字段是 GitNexus 的最小集 |
| trace 路径带 file:line 逐步渲染 | GitNexus process 资源逐 step 给 symbol+file:line+community；Sourcegraph 导航同样以位置为锚 | LOW | 两符号最短路 + 每跳 file:line + 边类型/置信度 |
| 重名消歧协议（uid 优先 + disambiguation 候选列表） | GitNexus context/rename 遇重名返回候选让 agent 明确二选，绝不静默取第一个 | LOW | Friday Symbol 已有主键，透出稳定 uid 即可 |
| 索引新鲜度（staleness）声明 | GitNexus context 资源带 staleness 检查，detect_changes 文档显式声明索引过期的失效模式 | LOW | Friday 已有 `last_indexed_commit_sha` 水位，工具输出带「索引落后 N commits」提示 |
| rename 只读 preview：图边 + 文本兜底双源、逐条 confidence 二分、context 片段 | GitNexus rename 的价值重心在 preview 质量（问题 5 结论）；动态引用限制须显式声明 | MEDIUM | Friday 只做只读半边是合理裁剪；graph/text_search 二值标签 + 按文件分组照搬 |
| taint 门禁 diff-aware（只报 MR 新增 finding） | Semgrep 官方推荐范式；全量 finding 灌 MR 是噪声灾难 | MEDIUM | baseline 取 merge-base；主干 full scan 台账可后置 |
| finding 分级 + 误报通道 | severity 三级 + ignore 须给原因 + triage 跨分支生效是 Semgrep 成熟实践 | MEDIUM | 最小集：severity 透出 + `nosemgrep` 注释生效 + 门禁默认报告不阻断 |

### Differentiators（Friday 的竞争优势位）

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| 跨仓 impact（穿 `CrossRepoApiCall` 边界） | GitNexus 每仓独立图、impact 不穿仓；Friday 多仓图 + 跨仓 API 边可以回答「改这个后端接口影响哪些前端仓」——里程碑已标「反超 GitNexus」 | HIGH | 跨仓边带 `match_confidence`，在 byDepth 输出里标注 `cross_repo: true` + 独立置信档 |
| LLM 模块摘要（超越 heuristicLabel） | GitNexus 社区标签是目录启发式字符串；Friday 用 LLM 生成语义摘要，喂 RepoRouter charter_match 与技术方案生成——摘要成为路由/规划的检索信号而不只是展示 | MEDIUM | Aider 教训：消费端按相关度排序 + token 预算截断，不全量灌入。LLM 调用须赋 `call_source` |
| detect_changes → MR 描述自动生成闭环 | GitNexus 的 detect_impact prompt 只产给人看的报告；Friday 把同一报告结构（Changes/Affected Processes/Risk/Recommendations）直接写进编码任务的 MR 描述与提交前自查 | MEDIUM | 报告模板照 detect_impact prompt 四段结构；接入 `RepoCodingTask` 提交链路 |
| 服务端多用户图服务（权限 + exclusion fail-closed） | GitNexus 是本地单用户 CLI；Friday 图工具天然继承 PAT 鉴权、排除文件六面不可见、RetrievalTrace 留痕 | MEDIUM | 复用既有 MCP 工具模式即零额外设计；这是自托管团队场景的护城河 |
| taint 门禁进 MR 编排流 | GitNexus 完全没有安全分析面；Semgrep 自身是通用 CI 工具——Friday 把 diff-aware taint 扫描编排进「需求→PR」流水线，finding 进 MR 描述/评论 | MEDIUM | 买不是造（已定决策）；开源版只承诺函数内 taint，文案如实声明边界 |
| 执行流以 `Endpoint` 为一等入口 | GitNexus 入口点靠启发式打分猜；Friday 已有 Endpoint 模型（路由装饰器解析），入口是确定性的——执行流质量天花板更高 | MEDIUM | 保留 GitNexus 的 BFS 参数纪律（maxDepth 10 / maxBranching 4 / minSteps 3 / 置信度 ≥0.5） |
| skills 随平台分发（repo-specific 工作流） | GitNexus 用 `.claude/skills/` 落仓 + AGENTS.md 引用证明了「工具 + 工作流 skill」比裸工具留存率高；Friday 已有 `@friday-ai-codes/skills` 同源分发管线 | LOW | 新增 impact-analysis / refactoring 两个 skill 模板即可，复用 v0.17.0 同源机制 |

### Anti-Features（明确不做/不这样做）

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| rename 自动 apply（服务端改写用户仓库） | "既然能算出清单为什么不直接改" | 服务端写用户仓库是危险的新写路径；GitNexus 的 apply 是本地 CLI 场景，且官方 checklist 也强制先 preview 人审 | 只读 preview 清单 + 编码代理自己执行编辑（里程碑已定） |
| 自研 PDG/CFG/污点分析 | "CodeQL 能做我们也做" | 编译器级数据流是另一个量级的工程；GitNexus 同样不做；CodeQL 索引重、增量差 | Semgrep taint mode 外购（已定决策，本调研确认与业界一致） |
| 原始图数据 dump / 裸 Cypher 面向 agent | "灵活性最大" | GitNexus skills 明确引导「smart tools, not raw queries」——预结构化输出让 agent 一次拿全、小模型可用；裸图数据浪费 token 且小模型驾驭不了 | 预结构化工具输出；原始查询最多作为 superuser 调试 escape hatch |
| 无截断的完整 impact 结果 | "怕漏" | 大仓 d3 传递闭包可达数千符号，token 爆炸且 agent 消化不了 | 深度分组 + 每层 top-N + summary 总计数 + minConfidence 过滤 |
| taint 硬门禁默认阻断、无 override | "安全要严" | Semgrep 实践证明无 escape hatch 的硬门禁会被整体绕过；存量债务淹没增量信号 | diff-aware 只报新增 + 默认报告不阻断（或仅 ERROR 阻断）+ ignore/nosemgrep 通道 |
| 用受影响流程替代受影响符号清单 | "流程叙事更高级" | 流程是叙事层不是行动层；agent 没有符号清单无法定位要改的 caller（问题 4 结论） | 符号清单为主 + 流程叙事为 MR 描述增值层，两者分层交付 |
| 每请求实时全图重算 | "保证最新" | Aider 每轮重算是本地小图；服务端多仓大图重算延迟不可接受 | 内存图缓存 + `last_indexed_commit_sha` 水位失效 + LRU（地基已规划） |
| 承诺跨函数/跨文件 taint（开源版） | "门禁要全" | 跨函数/跨文件 taint 是 Semgrep Pro 付费能力且资源要求高（8GB/核）；虚假承诺产生虚假安全感 | 如实声明函数内边界；Pro license 用户可配置升级 |

## Feature Dependencies

```
内存图服务（地基：networkx 缓存 + 水位失效 + LRU）
    └──required by──> impact 影响面分析
    └──required by──> trace 调用路径
    └──required by──> rename_preview（图引用半边）
    └──required by──> 社区检测
    └──required by──> 执行流追踪

impact ──required by──> detect_changes（diff→符号→批量 impact）
社区检测 ──required by──> LLM 模块摘要 ──enhances──> RepoRouter / 技术方案生成
社区检测 ──enhances──> 执行流（intra/cross_community 分类；GitNexus 中社区先于流程检测）
执行流（Process 模型） ──enhances──> detect_changes（affected_processes 叙事层）
执行流 ──enhances──> impact（affected_processes 字段）
detect_changes ──required by──> MR 描述自动生成 / 编码任务提交前自查

Semgrep taint 门禁 ──independent──（只依赖 MR diff 通道，不依赖内存图）
rename_preview ──enhances──> 编码代理改名工作流（grep 兜底半边复用既有 grep 面）
```

### Dependency Notes

- **一切图工具依赖内存图服务**：GitNexus 用 KuzuDB 常驻 + 连接池懒加载 5 分钟逐出；Friday 的 networkx 缓存 + 水位 + LRU 是同构方案，必须第一个落地。
- **社区检测先于执行流**：GitNexus 索引管线第 6 阶段在社区之后才做流程检测，因为 Process 需要 `intra/cross_community` 分类与 community 归属标注——Friday 相位排序应保持同序。
- **detect_changes 分两层交付**：符号清单半边只依赖 impact（MVP）；affected_processes 叙事半边依赖执行流（可后置增强，不阻塞 MR 描述首版）。
- **Semgrep 门禁与图功能零耦合**：可并行开发，任何相位插入均可。
- **模块摘要是消费端驱动的**：摘要本身 MEDIUM 复杂度，但价值取决于 RepoRouter/方案生成的消费接线；喂养侧遵循 Aider 范式（排序 + 预算截断）。

## MVP Definition

### Launch With (v1)

- [ ] 内存图服务 — 一切图工具的地基，无它全部空谈
- [ ] impact（深度分组 + 置信度 + 风险分级 + 截断 + 跨仓边） — 里程碑核心承诺，agent「改前自查」的主工具
- [ ] trace 调用路径 — impact 的姊妹工具，实现共享图遍历基建，边际成本低
- [ ] detect_changes 符号清单半边 + MR 描述接入 — 「提交前自查」闭环是 Friday 区别于 GitNexus 的落点
- [ ] 重名消歧 + staleness 提示 + 截断纪律 — 所有工具的横切 table stakes，首版就要有

### Add After Validation (v1.x)

- [ ] 社区检测 + LLM 模块摘要 — 触发条件：impact/trace 上线后，RepoRouter charter_match 消费接线就绪
- [ ] 执行流（Endpoint 入口 + Process 模型） — 触发条件：社区检测落库后；随后回填 detect_changes/impact 的 affected_processes 字段
- [ ] rename_preview — 独立性强，编码代理改名需求出现即可插入
- [ ] Semgrep taint 门禁（diff-aware + severity + nosemgrep） — 独立轨道，MR diff 通道就绪即可；首版报告不阻断
- [ ] impact-analysis / refactoring skills 进 `@friday-ai-codes/skills` — 工具面稳定后固化工作流

### Future Consideration (v2+)

- [ ] detect_impact 式 MCP prompt（编排 detect_changes→context→impact 的工作流 prompt） — 等工具面全部稳定
- [ ] taint 门禁台账化（主干 full scan + finding 状态机 + 跨分支 triage） — Semgrep 平台级能力，自建成本高，等门禁用量验证
- [ ] 模块摘要进 Galaxy 可视化 / 前端社区着色 — 展示层增值，不影响 agent 链路

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 内存图服务 | HIGH（地基） | MEDIUM | P1 |
| impact（含跨仓） | HIGH | HIGH | P1 |
| trace | MEDIUM | LOW（复用 impact 基建） | P1 |
| detect_changes 符号清单 + MR 描述 | HIGH | MEDIUM | P1 |
| 社区检测 + LLM 模块摘要 | MEDIUM | MEDIUM | P2 |
| 执行流（Endpoint 入口 + Process） | MEDIUM | HIGH | P2 |
| rename_preview | MEDIUM | MEDIUM | P2 |
| Semgrep taint 门禁 | MEDIUM | MEDIUM | P2 |
| skills 固化工作流 | MEDIUM | LOW | P2 |
| detect_impact 式编排 prompt | LOW | LOW | P3 |
| taint finding 台账/状态机 | LOW | HIGH | P3 |

## Competitor Feature Analysis

| Feature | GitNexus | Sourcegraph / CodeQL / Aider / Semgrep | Our Approach |
|---------|----------|----------------------------------------|--------------|
| impact/blast radius | byDepth d1/d2/d3 语义标签 + risk 四级 + minConfidence + affected_processes/modules | Sourcegraph：find references 跨仓精确但无深度分组/风险语义（面向人） | 照搬 GitNexus 输出契约 + 跨仓边（反超）+ 置信度三源映射 |
| detect_changes | scope 四态 + base_ref + 符号清单 + 流程叙事 + pre-commit/CI 集成示例 | Semgrep：diff-aware baseline（merge-base）是同构思想 | scope 以 compare（MR diff）为主，报告结构照 detect_impact prompt 四段进 MR 描述 |
| 模块/社区 | Leiden + heuristicLabel + cohesion% + top-20 资源 | Aider：PageRank 排序 + token 预算截断喂 LLM | Leiden/Louvain 社区落库 + LLM 语义摘要（超越启发式标签），消费端按 Aider 范式排序限额 |
| 执行流 | 入口启发式打分 + BFS（depth10/branch4/minSteps3/conf≥0.5）+ 双层去重 + intra/cross 分类 | 无对标（CodeQL 数据流是另一范畴） | Endpoint 确定性入口（优于启发式猜测）+ 保留 GitNexus BFS 参数纪律 |
| rename | preview 默认 + graph/text_search 二分 confidence + context 片段 + 可 apply | Sourcegraph：无批量 rename；IDE LSP rename 单机精确但无跨文件 confidence 分层 | 只读 preview（不做 apply），双源 + confidence 二分照搬 |
| 安全门禁 | 无 | Semgrep：diff-aware + severity + triage 状态机 + /fp + nosemgrep + shortest-path | 集成 Semgrep（买不是造）；开源版如实声明函数内 taint 边界 |
| agent 消费面 | 7 tools + 6 resources + 2 prompts + 4 skills 落仓 + hooks | Cody：context 检索为主，无图分析工具面 | MCP 工具复用既有模式 + skills 同源分发；「smart tools 预结构化」哲学全盘采纳 |

## Sources

**一手（HIGH confidence）：**

- GitNexus 官方文档（Mintlify，2026-08-09 抓取）：`api/tools/{impact,detect-changes,context,query,rename}.md`、`api/resources/clusters.md`、`api/prompts/detect-impact.md`、`concepts/{knowledge-graph,processes-and-flows}.md`、`skills/overview.md` — https://abhigyanpatwari-gitnexus.mintlify.app
- GitNexus GitHub README — https://github.com/abhigyanpatwari/GitNexus
- Semgrep 官方 docs：taint-mode overview、semgrep-pro-engine-intro、findings-ci、ci-environment-variables、finding_all_taints（shortest-path） — https://docs.semgrep.dev
- Aider 官方：repomap.html、2023/10/22/repomap.html、`aider/repomap.py` 源码 — https://aider.chat

**二手验证（MEDIUM confidence）：**

- Sourcegraph docs：precise-code-navigation、code-navigation、cross-repository blog、SCIP repo — https://sourcegraph.com/docs
- Aider PageRank 解析（anishgandhi.com）、DeepWiki repomap 分析 — 与官方源码交叉验证一致

---
*Feature research for: 代码智能图分析升级（对标 GitNexus，Friday AI v0.22.0）*
*Researched: 2026-08-09*
