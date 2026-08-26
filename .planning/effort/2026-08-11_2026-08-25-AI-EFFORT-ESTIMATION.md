# 技术方案 Agent 迭代（2026-08-11 ~ 2026-08-25）· AI 开发工作量评估

> 本地留痕版。飞书正式版：<https://guanghe.feishu.cn/docx/XVCJdbsmgojZTMxuXc6cF8K5n9c>（2026-08-25 以用户身份导入创建，门禁 C 以新建文档方式满足）。

## 元数据

| 项 | 内容 |
|---|---|
| 评估对象 | Friday AI「技术方案 Agent」迭代：v0.22.0 收口段 + v0.23.0 仓库路由决策漏斗 + v0.24.0 单仓图查询对齐 + 蓝图/容器提交若干 quick 任务 |
| 开发者 | 刘振泽 / 学习工具 / 前端开发 / 年限档 **>8 年**（年限仅归档，**不影响点数**） |
| 变更范围 | `fa2858f0..HEAD`（2026-08-10 15:14 之后的全部提交，即 8/11 起）+ 当前工作区未提交改动（1 文件 / 1 行） |
| 提交量 | **181 commits**（180 非 merge）：feat 44 / fix 16 / test 31 / docs 81 |
| 有提交的日期 | 6 天：8/11(18)、8/14(62)、8/15(3)、8/18(12)、8/24(51)、8/25(35) |
| 基准来源 | 1/2/3/5 点数尺校准自《学习工具 A 组基准点》+《ai-phone 工作量评估（手写实现视角）》。**1 故事点 = 100 协作点**；故事点只代表复杂度/规模，不代表时间 |

## 头号结论

> **总协作点 = 86.5 故事点 × 100 = 8650 协作点**（全部归属：刘振泽 · AI 单人全栈）

---

## 一、改动客观规模

范围内总计 **544 文件变更 / +52,885 / −3,234**。其中 `.planning/` 为 GSD 流程台账（计划/审计/验证产物），**不计入功能点**（见文末排除说明）。

| 模块 | 文件数 | 新增 | 删除 | 净增 | 新写/复用 |
|---|---|---|---|---|---|
| 后端 `server/`（非测试） | 92 | +14,458 | −988 | **+13,470** | 新写为主（33 个全新模块），含 3 个迁移 |
| 测试（后端 + 前端） | 106 | +12,872 | −494 | **+12,378** | 全部新写，TDD 先红后绿 |
| 前端 `web/` | 20 | +1,384 | −120 | **+1,264** | 改造为主（蓝图查看器既有组件族） |
| 容器执行器 `task/` | 7 | +787 | −280 | **+507** | 新写 MCP 提交工厂 + 重构执行链 |
| 构建 `Dockerfile` | 1 | +3 | −2 | +1 | 接线 |
| **代码合计** | **226** | **+29,504** | **−1,884** | **+27,620** | — |
| 流程台账 `.planning/` | 316 | +23,379 | −1,348 | +22,031 | **不计分** |

新增数据库迁移 3 个：`codegraph/0015_securityfinding_unique_fingerprint`、`prompts/0012_seed_repo_summary_charter`、`repositories/0042_repo_charter_append_only`。

**已逐文件核对，功能点无遗漏**（226 个代码文件全部归入下方 39 个功能点；排除的 `.planning/` 台账与纯路径搬迁文件已注明理由）。

---

## 二、逐功能点打分明细

### A. v0.22.0 收口段（8/11，18 commits）

| # | 功能点 | 功能说明 | 故事点 | 定点理由（该功能点自身复杂度） |
|---|---|---|---|---|
| 1 | Semgrep diff-aware 扫描门禁与 MR 安全段 | `semgrep_sha.py` 新建 + `semgrep_enqueue`/`semgrep_scan`/`semgrep_token`/`security_scan_report` 五模块改造 + `SecurityFinding` 唯一约束迁移 + 3 个挂点（MR service / MCP create_merge_request / coding node）；8 个测试文件 | **3** | 后端 5 模块 + 1 迁移 + 3 挂点，含子进程墙钟超时回收（消除带 token 的孤儿进程）、两端真实 commit sha 解析后才入队、`(repository, fingerprint, mr_key)` 幂等唯一约束——多环节串联且有资源生命周期管理，落大功能档 |
| 2 | code_graph 链路观测契约收口 | 事件名统一补 `code_graph_` 前缀、包内 `category` 收敛 `sampling`、`error=` 全部经 `redact_secrets_in_text` 脱敏；跨 8 个模块 + LOGGING-SPEC 补登 | **1** | 单点改造成熟（加前缀 / 改常量 / 套脱敏函数），复杂度在覆盖面而非机制，等同埋点档 |

### B. v0.23.0 仓库路由决策漏斗（8/14，62 commits，Phase 128–132）

把「全库单段文本相似度选仓」升级为可解释六段决策漏斗（画像 → 团队 → 短名单 → 章程/历史 → 放置单元 → 门禁/反思）。

| # | 功能点 | 功能说明 | 故事点 | 定点理由 |
|---|---|---|---|---|
| 3 | 专项画像抽取 `initiative_profile` | 415 行主模块 + 210 行测试：feature list → `InitiativeProfile`，默认剔除 acceptance/测试正文语料、语料不足返回 `clarify`、LLM 失败 fail-soft 为 `degraded` | **2** | 1 个纯函数模块 + LLM 调用，三条分支（正常/不足/降级）都要可测，方案成熟无状态机 → 中等档 |
| 4 | 团队硬门禁 `team_gate` | 344 行 + 2 个测试文件（365 行）：`team_core` 解析、拒绝 out_of_team primary、空团队 clarify；Blueprint / Association / MCP 三入口接线 | **2** | 判定逻辑本身简单，但要在三个入口同时封住「静默全库 primary」这条旁路，接线面 ×3 → 中等档 |
| 5 | 短名单生成 `shortlist` | 264 行 + 457 行测试：activity / capability / charter 三源候选 + planned 仓强制拉入 | **2** | 三源合并 + 强制拉入规则，多分支但无状态 → 中等档 |
| 6 | 历史先验分桶 `history_prior` | 306 行 + 110 行测试：需求史 / 上线史分桶 API，与 `team_core` 求交后 force-include | **2** | 两类历史源分桶 + 集合运算，机制清晰 → 中等档 |
| 7 | 放置单元聚合 `placement_units` | 397 行 + 237 行测试：`build_placement_units` 按模块依赖 +「复用」边聚合功能点为放置单元 | **2** | 图聚合算法但规模有界，无并发 → 中等档 |
| 8 | 短名单内细落点 `place_units` | 346 行 + 783 行测试：`place_units` 在短名单内定细落点，候选硬限 ⊆ shortlist（V2 `hard_scope`） | **3** | 落点判定 + 硬边界约束 + 与 V2 路由器的硬限协同，测试量最大（552 行 placement 套件），多环节串联 → 大功能档 |
| 9 | 统一五门门禁 `funnel_gates` | 686 行 + 713 行测试：`team → shortlist_coverage → unit_placement → global_consistency → publish` 五门固定顺序，统一 `pass\|clarify\|block` + 12 值 `reason_codes` 闭集 + evidence，聚合取最严重态；发布门 `allow_auto_selected` 需全 unit high + 双证据 | **3** | 五道门 + 稳定 reason_code 闭集契约 + 严重度聚合状态机 + 接线守卫，本身是状态机型大功能 → 大功能档 |
| 10 | 有界反思环 `reflection` | 625 行 + 365 行测试：N=2 上界、子集重算、ledger 脱敏可回放、`role_collapse` 触发检测 | **3** | 有界重入循环（含终止条件保证）+ 可回放留痕，属含状态推进的大功能 → 大功能档 |
| 11 | 漏斗主路径接线 | `blueprint_route.py` +947/−25、`repo_association_service.py` +345/−15、`repo_router_v2.py` 微调；三分量不再唯一决策（INT-01） | **3** | 单文件近千行改造，把两条既有主路径（蓝图选仓 / 项目选仓）改走漏斗且保持不推倒冻结的 `repo_router_v2`，改造面与回归风险最高 → 大功能档 |
| 12 | 高三合成宇宙回归与 D2 bar | `gaosan_eval.py` 175 行 + `gaosan_learning_tools` fixture 256 行 + 277 行回归/契约测试：四基线 hit@primary、out_of_team=0 自动化绿 | **2** | 合成宇宙 fixture + 指标 bar 判定，工程量中等、机制成熟 → 中等档 |

### C. 路由入口收敛（8/15，3 commits）

| # | 功能点 | 功能说明 | 故事点 | 定点理由 |
|---|---|---|---|---|
| 13 | 统一仓库路由入口到 `RepoRouterV2` | 删除旧 `repo_router.py`（−259 行）+ 新增统一面守护测试 61 行 + 既有路由测试重写 | **1** | 纯收敛重构，无新机制；价值在消除双实现漂移，复杂度落单一成熟档 |

### D. 蓝图分仓落点与调研可读化（8/18，12 commits）

| # | 功能点 | 功能说明 | 故事点 | 定点理由 |
|---|---|---|---|---|
| 14 | 仓库章程 append-only 改造 + 摘要种子 | `charter_service.py` +611/−42、`charter_draft_writeback.py` 重写（+103/−112）、`0042_repo_charter_append_only` 迁移、`0012_seed_repo_summary_charter` prompt 种子（148 行）；4 个测试文件改造 | **3** | 存储语义从可覆盖改为 append-only，涉及迁移 + 草稿回写链路重写 + 既有测试契约翻新，数据语义变更风险高 → 大功能档 |
| 15 | 分仓 OpenSpec proposal 生成 | `blueprint_proposal_render.py` 371 行 + 145 行测试：按仓生成 proposal 并作为编码阶段只读上下文注入 | **2** | 单模块渲染 + 一个注入点，结构化输出但无状态机 → 中等档 |
| 16 | 确认门拦截 unsuitable 仓 + 快照幂等刷新 | `blueprint_confirm_gate.py` +330/−18 + `repair_blueprint_confirm_gate` 运维命令 190 行 + 416 行测试 | **3** | 门禁判定 + 幂等快照刷新 + 存量数据修复命令三件套，含幂等与回补语义 → 大功能档 |
| 17 | 功能点 module 贯通修复 + 落点去角色化 | 修复功能点 `module` 未贯通导致落点粒度塌陷；分仓落点从固定角色化改为 agent 直接落点；`blueprint_repo_plan.py` +197、627 行相关测试 | **2** | 一个真实缺陷的根因修复 + 一次设计简化，分支中等 → 中等档 |
| 18 | 仓库调研过程明细按仓分组实时可读 | `blueprintActivity.ts` +363/−16、`BlueprintResearchDrawer.vue` +150、三事件 payload 可读化、zh-CN 文案、119 行前端测试 | **2** | 前端 1 个抽屉组件 + 1 个叙事工具模块 + 后端三事件 payload 对齐，属 UI/文案适配量级 → 中等档 |

### E. v0.24.0 单仓图查询对齐 GitNexus（8/24–8/25，86 commits，Phase 133–140）

| # | 功能点 | 功能说明 | 故事点 | 定点理由 |
|---|---|---|---|---|
| 19 | 评测指标内核（BENCH-04） | `graph_bench_eval.py` 内六指标 scorer + 空结果规则（`NO_GOLD`/`N/A`/`SEED_MISSING`/`NODE_NOT_IN_GRAPH` 各锁定分母）+ `CaseOutcome`/`evaluate_case` 折算 | **3** | 六个指标各自锁定分母与空结果语义（空 gold 记 `NO_GOLD` 而非满分是关键设计），纯函数但机制密集 → 大功能档 |
| 20 | 分桶 / macro 聚合 / 无阈值报告（BENCH-05） | `language × framework × entry_type` 三维分桶 + `INSUFFICIENT_DATA` + macro 按 case 平均 + 受保护桶单列不被 overall 抵消 | **2** | 聚合口径设计有讲究但实现是确定性算术 → 中等档 |
| 21 | run identity + 三方水位 fail-closed | run identity 五元组 + 三方水位（索引 built_at / gold 标注 sha / 源码 checkout sha）不一致即 `INVALID` 短路，绝不产出部分结论 | **2** | fail-closed 短路逻辑清晰，价值高但分支有限 → 中等档 |
| 22 | 冻结 gold 数据集与防反导约束 | `manifest.json` + `dev.json` + `locked_test.json` + `holdout.json` 空壳 + 标注口径 README；edge gold 的 `callee_uid` 必须附独立 `evidence_file_line` 锚点，防止从被测 codegraph 反向导出 | **1** | 数据集 schema + 一条硬校验，工程量小 → 单一成熟档 |
| 23 | 只读基准评测命令 `evaluate_graph_bench` | 900 行 management command + 305 行命令测试 + 运行时分桶下限修复 | **3** | 900 行 CLI 串起「解析水位 → 跑 case → 分桶 → 出报告」全链路，多环节串联 → 大功能档 |
| 24 | TS/JS 可审计调用解析 | `symbol_resolver.py` +503/−32、`wiring.py` +55、`symbol_index.py`/`base.py` 微调；161 行 TS/JS 解析测试 + 分支调用边 dry-run 回填 | **3** | 跨模块 import 解析 + 可审计三态输出 + dry-run 回填，语言语义细节多、边界易漏 → 大功能档 |
| 25 | Python module/class 调用解析 | Python module 与 class 解析增强 + 158 行解析测试 | **2** | 复用 TS/JS 已建的 resolver 框架做语言适配，增量明确 → 中等档 |
| 26 | Process dense+sparse 一等混合索引 | `process_index.py` 353 行 + 158 行测试 + `indexer.py`/`durable/tasks_impl.py` 接线 | **2** | 在既有索引管线上加一路独立投影，模式已成熟 → 中等档 |
| 27 | 统一 `GraphQueryService` | `query_service.py` 549 行：Symbol/Community/Process 三源 RRF 确定性融合（`rrf-v1`，权重 0.6/0.4 + community boost）+ `query_manifest` + `graph-query.v1.json` 契约 133 行 + 404 行测试 | **3** | 三源融合 + 确定性排序版本化 + 对外契约冻结（含 conformance 测试），是本里程碑的核心服务 → 大功能档 |
| 28 | 消歧与有界影响面 | `impact_report`/`process_trace`/`code_graph_tools` 改造 + 采样测试 171 行：显式消歧 + 影响面节点/深度有界 | **2** | 在既有 impact 内核上加消歧与预算边界，增量中等 → 中等档 |
| 29 | 五消费面契约收敛 | MCP 工具面（`views`/`serializers`/`urls`）+ chat 工具 `graph_query.py` 92 行 + `hybrid_search` +49 + `rag_search` +35 + task 侧 `generated_graph_query_manifest` + 104 行工具测试 | **2** | 五个消费面各自接同一契约，单点简单但一致性要求高 → 中等档 |
| 30 | 图查询可观测边界收口 | 唯一 caller 生命周期事件 + 低噪声内部 sampling + 统一异常脱敏 + 跨 retrieval AST 守卫；400 行观测/采样测试 | **2** | 属埋点治理但含 AST 级守卫（机器强制而非约定），高于纯埋点 → 中等档 |
| 31 | threshold policy 与四态 comparator | `graph_bench_compare.py` 824 行 + 511 行测试：严格内容寻址 + 配对校验的只读 policy，四态比较；缺真实 baseline 时拒绝生成伪正式 policy | **3** | 824 行主模块，内容寻址配对 + 四态判定 + fail-closed 拒绝伪 policy，是评测体系的决策层 → 大功能档 |
| 32 | 只读 compare 审计命令 | `compare_graph_bench.py` 192 行 + 201 行命令测试，可回放审计 | **2** | CLI 薄封装 + 可回放要求，工程量中等 → 中等档 |
| 33 | resolver 三态 cell 契约 + benchmark 双身份 hash 证据链 | edge-level 三态测量 + 可机械配对的双身份与 artifact hash 关联；183 行测试 | **2** | 证据链设计（防错配）+ 三态测量，分支中等 → 中等档 |
| 34 | 跨阶段 closure gate 与全组件回归 | Phase 133–140 单一 closure gate（137 行）+ server/task/npm MCP 三组件回归 + 任务仓标识类型校验收窄 + 拒绝 threshold policy 未知扩展字段 | **1** | 门禁本身是一层断言集合，实现简单 → 单一成熟档 |

### F. 8/25 收尾改造

| # | 功能点 | 功能说明 | 故事点 | 定点理由 |
|---|---|---|---|---|
| 35 | 容器 Agent 经 Friday MCP 结构化提交 | `task/core/agent_submit_mcp.py` 549 行新建（三场景共享提交工厂，经 SDK MCP tool 参数提交、input_schema 校验、场景级 CaptureStore 隔离、彻底移除自由文本 JSON 解析与 fallback）+ `executor.py` +166/−202、`runner.py` +41/−74 重构 + 服务端 `callbacks.py` +376/−85 + 4 个测试文件 | **3** | 跨 task/server 两侧改协议：新建唯一结构化提交渠道、删掉旧文本解析路径、服务端回调同步改造，含场景隔离与「空文本成功/未调用失败」单点收口 → 大功能档 |
| 36 | 蓝图阶段导航 + 活动流 + 规格锚点可读化 | 前端 `BlueprintStageStepper.vue` +227、`anchorTargets.ts` 83、`BlueprintThreadCard.vue` +130、`RequirementSpecSection.vue` +77、`useBlueprintLive.ts` +115、zh-CN +88；6 个前端测试文件（558 行） | **3** | 5 个组件/composable 改造 + 锚点定位模块 + 6 组前端测试，交互面与状态同步（实时活动流增量轮询）复杂度接近 UI 适配上档 → 大功能档 |
| 37 | 蓝图仓别名 + 引用溯源 + 确认门恢复 | `blueprint_repo_alias.py` 144、`blueprint_citations.py` 54、`blueprint_resume.py` 25、`blueprint_merge.py` +119、`blueprint_lifecycle_service.py` +83、`blueprint_doc_views.py` 188、`artifact_serializers.py` 32、git platform 三客户端 +63；9 个测试文件 | **3** | 三个新模块 + 融合/生命周期/文档接口改造 + git 客户端扩展，横跨蓝图全链路的补齐 → 大功能档 |
| 38 | chat SDK resume transcript 校验与降级 | `server/chat/sdk_resume.py` 48 行 + `chat_runner` 接线 + 测试：派发前校验 SDK resume transcript，非法则安全降级 | **1** | 单一校验点 + 降级分支，机制简单 → 单一成熟档 |
| 39 | Docker uv 新 tool 目录适配 | `server`/`web`/`task` 三个 Dockerfile 同步构建路径 | **0.5** | 纯构建配置适配，最小增量 |

---

## 三、合计

| 板块 | 功能点数 | 故事点 | 协作点（×100） |
|---|---|---|---|
| A. v0.22.0 收口段（Semgrep 门禁 + 观测收口） | 2 | 4 | 400 |
| B. v0.23.0 仓库路由决策漏斗 | 10 | 24 | 2,400 |
| C. 路由入口收敛 | 1 | 1 | 100 |
| D. 蓝图分仓落点与调研可读化 | 5 | 12 | 1,200 |
| E. v0.24.0 单仓图查询对齐 | 16 | 35 | 3,500 |
| F. 8/25 收尾改造（容器提交协议 / 蓝图前端 / 引用溯源） | 5 | 10.5 | 1,050 |
| **合计** | **39** | **86.5** | **8,650** |

> 总计 86.5 点 ÷ 当前饱和产能基线 1.58 ≈ **54.7 人天**（仅附注展示，不参与计算、不作工期依据）。

**归属**：AI 单人全栈 → 8,650 协作点全部归 刘振泽。学科明细（按各面实际内容占比）：后端 ≈ 5,600 / 测试 ≈ 2,000 / 前端 ≈ 700 / 容器执行器 ≈ 350。

---

## 四、AI 实际耗时

评估窗口 2026-08-11 ~ 2026-08-25 共 15 个自然日，其中**有提交的日期为 6 天**（8/11、8/14、8/15、8/18、8/24、8/25）。按用户口径「有提交的天数都在开发」记为 **≈6 个开发日**。纯信息记录，**不参与点数评估**。

## 五、量级自查

本次 **86.5** 故事点，与 aiphone 全项目 **76** 点作数量级参照：同一量级、略高。旁证——代码净增 27,620 行 / 86.5 点 ≈ **319 行/点**，落在校准标尺区间内（aiphone 1324 行大页 = 5 点 ≈ 265 行/点；1725 行页 = 3 点 ≈ 575 行/点）。范围内含 3 个里程碑段、13 个 phase、39 个功能点，与「一个完整项目」的量级相称，未见注水。仅作 sanity check，不逐项对标。

## 六、基准来源声明

本评估用的 1/2/3/5 点数尺，校准自《学习工具 A 组基准点》与《ai-phone 工作量评估（手写实现视角）》；故事点仅代表复杂度/规模，不代表时间。以上打分**针对本项目自身复杂度**判定，未按组缩放、未人为封顶、未逐项对标 aiphone。**1 故事点 = 100 协作点**。

---

## 附：覆盖自查与排除说明

- **已逐文件核对，无遗漏**：范围内 226 个代码文件（`server/` 92 非测试 + 106 测试 + `web/` 20 + `task/` 7 + 1 Dockerfile）全部归入上表 39 个功能点。
- **排除项及理由**：
  - `.planning/` 316 文件 / +23,379 行——GSD 流程台账（PLAN/SUMMARY/RESEARCH/REVIEW/VERIFICATION/AUDIT），是过程产物而非交付功能，**整体不计分**（按 A 组「技术方案按比例」本可折算，此处从严不计，避免注水）。
  - `.planning/{phases => milestones/v0.22.0-phases}/...` 约 130 个 0 行变更文件——纯路径搬迁，无实质内容。
  - `web/src/auto-imports.d.ts`、`web/src/components.d.ts`——unplugin 自动生成声明文件。
- **年限与点数解耦**：>8 年年限仅作归档元数据，未参与任何一档点数判定。
