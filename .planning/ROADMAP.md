# Roadmap: Friday AI

## Milestones

- 🚧 **v0.24.0 单仓图查询对齐 GitNexus** — Phases 133–140 (planned) — 在同仓同 commit 的 v0.22 baseline 上，依次提升 TS/JS 与 Python 调用边、建立 Process 一等混合索引、统一 graph-aware query 与 bounded impact，并让五个消费面共享同一契约；最后才锁 threshold policy 与整体回归/观测门禁
- ✅ **v0.23.0 仓库路由增强（分阶段决策漏斗）** — Phases 128–132 (completed 2026-08-14，未打 tag) — 把「全库单段文本相似度选仓」升级为「画像 → 团队门禁 → 短名单 → 章程/历史 → 放置单元 → 门禁/反思」的可解释决策漏斗；验收锚点「高三提分专项」 — 里程碑审计 **tech_debt**（25/25 需求满足 / 5 相位全 verified passed / 0 BLOCKER）见 [audit](./milestones/v0.23.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.23.0-ROADMAP.md) · [requirements](./milestones/v0.23.0-REQUIREMENTS.md) · [phases](./milestones/v0.23.0-phases/) · [decisions](./milestones/v0.23.0-DECISIONS.md) · [research](./research/ROUTING-RANKING.md)
- ✅ **v0.22.0 代码智能图分析升级（对标 GitNexus）** — Phases 121–127 (completed 2026-08-11，未打 tag) — 在现有 codegraph/RAG 底座上叠加内存图分析层：图缓存地基 + impact/trace（穿仓）+ detect_changes 闭环进编码链 + 社区/模块摘要 + 执行流 + rename_preview + Semgrep advisory + LSP 基准 — 里程碑审计 **tech_debt**（27 条需求 26 满足 / 1 部分（IMPACT-03）/ 0 未达；121–126 passed、127 human_needed @ 4/4）见 [audit](./milestones/v0.22.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.22.0-ROADMAP.md) · [requirements](./milestones/v0.22.0-REQUIREMENTS.md) · [phases](./milestones/v0.22.0-phases/) · [research](./research/SUMMARY.md)
- ✅ **v0.21.0 蓝图过程可见与返工闭环（反向关联 + 门到期 + 按阶段 agent 活动流 + 带原始上下文重跑）** — Phases 117–120 (completed 2026-08-05，未打 tag) — 让蓝图的「生成过程」与「返工过程」都对人可见可控：阶段级活动流取代笼统转圈、分仓每仓进度与方案可见、人审可选重跑范围且续跑带原始 agent 上下文、HITL 门不再无限静默悬挂 — 验证 **tech_debt**（15 条需求 14 满足 / 1 部分（LIVE-04 落增量轮询而非推送通道）/ 0 未达；后端 9849 全绿、前端 1 条既存失败）见 [verification](./milestones/v0.21.0-VERIFICATION.md) — [requirements](./milestones/v0.21.0-REQUIREMENTS.md)
- ✅ **v0.20.0 技术方案蓝图（六段结构化蓝图 + 确认门与分仓方案 + 划线澄清收敛 + 全入口收编）** — Phases 111–116 (shipped 2026-08-02) — 技术方案从单轮 JSON 升级为「人类可读、AI 可依此完备编码」的项目级结构化蓝图 — 里程碑审计 tech_debt（34/35 需求满足 / 6 相位全 verified / 0 可在本里程碑内闭合的缺口；GATE-01 与三道入口接缝因硬依赖同步点 2 判 PARTIAL / 转技术债，同步点 2 已由 2026-08-02 的分支合并满足）见 [audit](./milestones/v0.20.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.20.0-ROADMAP.md) · [requirements](./milestones/v0.20.0-REQUIREMENTS.md) · [design](./technical-blueprint/DESIGN.md)
- ✅ **v0.19.0 技术方案可信度（编排不塌陷 + 路由可解释 + 编排产出直连执行流 + 过程可见）** — Phases 105–110（其中 108 已移交 v0.20.0）(completed 2026-08-02，未打 tag) — 让技术方案链路真正跑通并可信：编排不再中途卡死被降级工具顶替、路由基于多维证据分层呈现并可解释、编排产出直连执行流、全过程对用户实时可见 — 5 相位 39/39 plans；里程碑审计 **tech_debt**（19 条需求 17 满足 / 2 部分（ROUTE-03 生产 `nr_snapshot` 未写入、RELY-02 澄清送达需真实飞书）/ 0 未达；ROUTE 缺口已结构性闭合；遗留 27 项人工验收全未执行）见 [audit](./milestones/v0.19.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.19.0-ROADMAP.md) · [requirements](./milestones/v0.19.0-REQUIREMENTS.md) · [research](./research/ROUTING-RANKING.md)
- ✅ **v0.17.0 统一知识库与全链路联动（知识收敛 + 完工沉淀闭环 + 容器内置 MCP/Skills）** — Phases 100–104 (shipped 2026-07-22) — 把多套"知识/经验/沉淀"收敛成统一知识库（单一摄取 + 单一检索），补齐完工沉淀闭环（三链路一致），给编码容器内置 Friday MCP 与 skills — 里程碑审计 tech_debt（19/19 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留 11 项真实 Qdrant·飞书·容器·Cursor 端人工验证 + 若干接受/递延债务）见 [audit](./milestones/v0.17.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.17.0-ROADMAP.md)
- ✅ **v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）** — Phases 96–99 (shipped 2026-07-01) — 把项目外部依赖（`Artifact`：PRD/埋点评审/UI 文档等）接入知识总览/搜索/知识树，并与关键词/业务能力/仓库建关联 — 里程碑审计 tech_debt（12/12 需求满足 / integration_ok；遗留真机/浏览器视觉验收 + 既有范围外测试漂移）见 [audit](./milestones/v0.16.3-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.3-ROADMAP.md)
- ✅ **v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）** — Phases 90–95 (shipped 2026-06-28) — 里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.1-ROADMAP.md)
- ✅ **v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）** — Phases 82–89 (shipped 2026-06-26) — 里程碑审计 tech_debt（37/37 需求满足 / integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [audit](./milestones/v0.16.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.0-ROADMAP.md)
- ✅ **v0.15.0 项目（交付上下文聚合根）** — Phases 76–81 (shipped 2026-06-26) — 里程碑审计 passed（38/38 需求满足 / integration_ok）见 [audit](./milestones/v0.15.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.15.0-ROADMAP.md)
- ✅ **v0.14.0 可观测性与日志治理** — Phases 71–75 (shipped 2026-06-24) — 里程碑审计 passed（34/34 需求满足 / integration_ok）见 [audit](./milestones/v0.14.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.14.0-ROADMAP.md)
- ✅ **v0.13.0 并发治理与索引体验** — Phases 65–70 (shipped 2026-06-23) — 里程碑审计 tech_debt（11/11 需求满足、integration_ok；遗留既有前端测试失败 + URL 拆段拼接 UI + 真机人工验收）见 [audit](./milestones/v0.13.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.13.0-ROADMAP.md)
- ✅ **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (shipped 2026-06-20) — 里程碑审计 tech_debt（16/16 需求满足、integration_ok；遗留真机/真实平台运行期人工验收）见 [audit](./milestones/v0.12.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.12.0-ROADMAP.md)
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.11.0-ROADMAP.md)
- ✅ **v0.10.0 操作审计治理** — Phases 53–55 (shipped 2026-06-17) — [archive](./milestones/v0.10.0-ROADMAP.md)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。
> v0.18.0 是发布轨已占用的版本号，不对应任何 GSD 里程碑，也不占相位号（v0.17.0 止于 Phase 104 → v0.19.0 从 Phase 105 续号）。

## Phases

### 🚧 v0.24.0 单仓图查询对齐 GitNexus（Phases 133–140）

- [ ] **Phase 133: 同仓同 commit 基准与 v0.22 baseline** — 冻结评测身份、gold、分桶和分母，产出不含阈值的原始 baseline
- [ ] **Phase 134: TS/JS resolved 调用边** — 以 import alias、re-export 与 receiver 证据提升 TS/JS 调用边
- [ ] **Phase 135: Python resolved 调用边** — 以 import/member/receiver 绑定提升 Python 调用边并独立验收
- [ ] **Phase 136: Process 一等混合索引** — 从 canonical ProcessTrace 建立可重建、双 lane、同水位的 Process 投影
- [ ] **Phase 137: 统一 GraphQueryService** — 单次自然语言查询确定性融合 Symbol、Community 与 Process 证据
- [ ] **Phase 138: 消歧与 bounded impact** — 仅对已消歧 anchor 返回有界、不可误读为安全的影响面摘要
- [ ] **Phase 139: 五消费面契约收敛** — 服务端、Chat、Django MCP、npm MCP 与编码容器共享 canonical manifest
- [ ] **Phase 140: Threshold policy 与整体收口** — 基于 baseline 后锁定门禁并完成同条件对比、观测与全量回归

## Phase Details

### Phase 133: 同仓同 commit 基准与 v0.22 baseline

**Goal**: 获得可复现、无阈值污染的 v0.22 原始基线，作为后续所有质量声明的唯一比较起点
**Depends on**: Phase 132
**Requirements**: BENCH-01, BENCH-02, BENCH-03, BENCH-04, BENCH-05
**Success Criteria** (what must be TRUE):

  1. 评测者可用固定 repository、branch、commit SHA 运行 benchmark；任一索引、gold 或源码水位不一致时 run 明确标为 `INVALID`，不会产出可比较结论。
  2. 评测数据具有独立的 dev、locked test、holdout 切分，resolved edge gold 来自独立 callsite 标注而不是从被测图反导。
  3. 未修改的 v0.22 能力可在冻结数据集上输出逐 case、逐语言/框架/入口桶的原始 baseline，产物中不存在预填或推断的回归阈值。
  4. 报告同时给出 Symbol/Process recall、resolved edge、impact、trace、冷/热延迟与 token 的固定分母和空结果规则；稀疏桶显示 `INSUFFICIENT_DATA`，受保护桶不会被 overall 掩盖。**Plans**: 4 plans

**Wave 1**

- [ ] 133-01-PLAN.md — 纯函数地基：run identity 五元组 + 三方水位校验（INVALID fail-closed）+ gold schema 校验（BENCH-01, BENCH-02）
- [ ] 133-02-PLAN.md — 冻结 gold 数据集：manifest + dev/locked_test/holdout 三切分 + 防反导 README（BENCH-02）

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 133-03-PLAN.md — 指标 + 分桶 + 无阈值报告：Recall@5/@3、edge P/R、impact、trace 三态、空结果规则、INSUFFICIENT_DATA、macro 聚合（BENCH-03, BENCH-04, BENCH-05）

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 133-04-PLAN.md — 薄 command + 观测：水位闸 INVALID 短路、逐 case 真跑 v0.22 能力（冷/热计时）、无阈值 baseline + run manifest、caller/sampling 埋点（BENCH-01, BENCH-03）

### Phase 134: TS/JS resolved 调用边

**Goal**: TS/JS 调用边由可审计的语言证据解析，错误同名补边不再污染下游 Process、trace 与 impact
**Depends on**: Phase 133
**Requirements**: EDGE-01, EDGE-02, EDGE-03, EDGE-07
**Success Criteria** (what must be TRUE):

  1. 每个 TS/JS 调用点都返回 `resolved`、`ambiguous` 或 `unresolved`，并携带 language、call shape、strategy、候选和证据；全仓同名 fuzzy 不会静默补边。
  2. import alias 与 re-export 链上的直接调用可在 branch 作用域内解析到目标 Symbol，并可追溯每一步解析证据。
  3. receiver 类型或绑定唯一时成员调用可解析；无法唯一确定时保留 `ambiguous`/`unresolved`，不会任选同名 Symbol。
  4. `(repository, branch)` 批量回填支持 dry-run 对比；写入后水位或 resolver 版本变化会使 Community、Process 与检索投影失效，批任务仅输出分桶汇总与采样日志而不在 INFO 循环刷屏。

**Plans**: TBD

### Phase 135: Python resolved 调用边

**Goal**: Python import 与成员调用按独立语言口径可靠解析，不让动态语义被伪装成确定边
**Depends on**: Phase 134
**Requirements**: EDGE-04, EDGE-05
**Success Criteria** (what must be TRUE):

  1. module import、from import alias 与 imported member 调用可解析，并能区分模块成员与局部同名符号。
  2. receiver/class binding 足够明确时成员调用可解析；MRO 或动态目标不能确定时如实降级为 `ambiguous`/`unresolved`。
  3. 评测者可分别查看 language × framework × call shape 的 precision、recall、resolved、ambiguous、unresolved，为 Phase 140 按语言独立锁门提供输入。
  4. Go selector/interface 深化不影响本阶段及里程碑验收，LSP 默认值保持不变。

**Plans**: TBD

### Phase 136: Process 一等混合索引

**Goal**: Process 能脱离 Symbol 名称被直接检索，并始终返回 canonical、同 commit、步骤可核验的执行流证据
**Depends on**: Phase 135
**Requirements**: PROC-01, PROC-02, PROC-03, PROC-04, PROC-05, OBS-04
**Success Criteria** (what must be TRUE):

  1. 每个 Process 都从 canonical `ProcessTrace` 确定性生成包含名称、入口、终点、有序步骤摘要、模块、业务关键词和 `built_at_sha` 的检索文档。
  2. Process 文档进入独立且可重建的 Qdrant 投影，可由 BM25/sparse 与 embedding/dense 两路直接召回，Django 数据仍是事实源。
  3. 查询和对账严格按 repository、branch、generation 与 commit SHA 过滤；重建幂等，旧 generation 不会与新结果静默混排。
  4. 仅出现在 Process 名称、摘要或业务关键词中的 query 仍可直接召回 Process，并明确标注命中 lane。
  5. 返回的 Process 保留完整有序 steps，每步含 Symbol UID、仓库相对路径与 1-based 起止行并可在同 commit blob 核验；重建任务携带并重新 bind `initiated_by_user_id`，无用户时标 `system`。

**Plans**: TBD

### Phase 137: 统一 GraphQueryService

**Goal**: 调用者通过一个版本化入口获得确定性、可解释、同水位的 Symbol、Community 与 Process 查询结果
**Depends on**: Phase 136
**Requirements**: QUERY-01, QUERY-02, QUERY-03, QUERY-04, QUERY-05, QUERY-08, QUERY-09, QUERY-10
**Success Criteria** (what must be TRUE):

  1. 有仓库访问权的调用者可用中文或英文非空自然语言查询；空白 query 在检索或图分析前稳定拒绝，权限与 exclusion 检查 fail-closed。
  2. 一次响应同时返回 Symbol 候选、Community、Process 分组、步骤级 `file:line` 和影响面占位/状态，不要求调用方手工编排底层工具。
  3. Symbol 与 Process lane 确定性融合，同仓同 commit、同配置、同 query 重跑顺序一致；排序账本可离线重算 lane rank、各项贡献、最终分与排序版本。
  4. 同一 Symbol 在多个 Process 中的 step 归属和证据均被保留，matched count 与 returned count 分开报告，不因全局 UID 去重丢失上下文。
  5. 预算不足或 lane 部分失败时响应按 schema-preserving 规则裁剪，并保留水位、warning、总数/返回数、`truncated` 原因、续查提示及各 capability 的 used/degraded/unavailable 状态；混水位证据不会被拼接。

**Plans**: TBD

### Phase 138: 消歧与 bounded impact

**Goal**: 用户只在证据唯一锚定后获得有界影响面，并能看清置信度、覆盖范围和不确定性
**Depends on**: Phase 137
**Requirements**: QUERY-06, QUERY-07, OBS-05
**Success Criteria** (what must be TRUE):

  1. 重名 Symbol 返回路径、行号和 UID 消歧候选；未唯一锚定时标记 `needs_disambiguation`，不会生成确定性 impact 摘要。
  2. 已消歧 anchor 返回复用既有 GraphService 的 bounded impact 摘要、置信度、总数/返回数、截断原因和 drill-down 提示。
  3. 空 impact、不可达、stale 或部分图结果不会被解释为“安全”，而以稳定 warning/degradation 语义呈现。
  4. impact 的图扩展与源码证据复用仓库权限和 exclusion fail-closed；异常文本与 ledger 分别经规定入口脱敏，凭证或被排除内容不会出现在响应、日志或留痕。

**Plans**: TBD

### Phase 139: 五消费面契约收敛

**Goal**: 所有调用面发现并执行同一个版本化 graph query 契约，不再出现 npm 或容器工具漂移
**Depends on**: Phase 138
**Requirements**: CONTRACT-01, CONTRACT-02, CONTRACT-03, CONTRACT-04, CONTRACT-05, OBS-03
**Success Criteria** (what must be TRUE):

  1. 工具名、描述、input/output schema、required、defaults、enums、错误码、响应版本和 capability 元数据均可从单一 versioned manifest/registry 得到。
  2. 服务端 service、Chat Agent 与 Django MCP 仅做鉴权、上下文注入和协议映射，并在 discovery 与真实调用中暴露相同契约。
  3. npm `@friday-ai-codes/mcp` 的 graph query 定义由 canonical manifest 生成，打包 tarball 与服务端完整 schema hash 一致。
  4. 编码容器的 allowed-tools、schema 与真实调用复用同一 manifest；镜像或构建产物缺工具、版本或 schema 不一致时 conformance 测试失败且不得 skip。
  5. 五个消费面调用前均能发现契约版本、单仓/repository 必填语义、索引 commit、水位与 capability 状态；MCP 和 AI 对话调用均 best-effort 写入脱敏 `RetrievalTrace`，观测失败不改变业务响应。

**Plans**: TBD

### Phase 140: Threshold policy 与整体收口

**Goal**: 用 baseline 后审查锁定的门禁证明 v0.24 在相同条件下提升，并以安全、可观测、可回放的整体回归收口
**Depends on**: Phase 139
**Requirements**: BENCH-06, BENCH-07, EDGE-06, OBS-01, OBS-02
**Success Criteria** (what must be TRUE):

  1. threshold policy 仅基于 Phase 133 已完成的 baseline 分布独立锁定并可审查；测试失败不会自动刷新 baseline 或阈值。
  2. v0.24 candidate 与 v0.22 baseline 使用同仓、同 commit、同 query/gold、同 evaluator 比较，并保留可复现命令、配置、排序版本和逐例 diff。
  3. overall 与所有受保护桶均通过锁定门禁，TS/JS、Python、Process、impact、trace、冷/热延迟和 token 的退化不会被其他桶提升抵消。
  4. graph query 生命周期产生含 `duration_ms`、`category=caller`、`component`、触发用户和关联键的 started/completed/failed 事件，不记录 query 正文或凭证；resolver、Process、检索 lane 与 impact 的高频统计使用 `sampling` 且禁止 INFO 刷屏。
  5. 整体回归证明权限/exclusion、脱敏、`initiated_by_user_id`、partial/degradation、契约 hash 与同水位不变式保持；Go 深化、真跨仓 IMPACT-03 和 LSP 默认翻转仍留 Future，不作为通过条件。

**Plans**: TBD

**Execution order:** 133 → 134 → 135 → 136 → 137 → 138 → 139 → 140。Phase 133 只冻结评测协议并采集未修改 v0.22 baseline，不设阈值；Phase 140 才依据 baseline 锁 threshold policy。

**Coverage:** 39/39 v0.24.0 requirements mapped exactly once；0 unmapped；0 duplicate。Future Requirements（Go 深化、真跨仓 IMPACT-03、LSP 默认翻转等）不计入里程碑必达。

<details>
<summary>✅ v0.23.0 仓库路由增强（分阶段决策漏斗）(Phases 128–132) — SHIPPED 2026-08-14（审计 tech_debt，未打 tag）</summary>

- [x] **Phase 128: 专项画像 + 团队门禁地基** — 画像机读 + team_core / out_of_team 硬门（3/3, passed）
- [x] **Phase 129: 短名单 + 历史先验 + 章程角色图** — shortlist 可解释 + 主/辅/禁（4/4, passed）
- [x] **Phase 130: 放置单元 + 主路径接线** — shortlist 内细落点 + 蓝图路由走漏斗（3/3, passed）
- [x] **Phase 131: 门禁系统 + 反思环** — pass/clarify/block + 有界回跳（3/3, passed）
- [x] **Phase 132: 集成验收与高三提分回归** — D2 bar + 契约不回归 + 合成反思（3/3, passed）

完整相位明细见 [milestones/v0.23.0-ROADMAP.md](./milestones/v0.23.0-ROADMAP.md)；相位产物见 [milestones/v0.23.0-phases/](./milestones/v0.23.0-phases/)。

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 128. 专项画像 + 团队门禁地基 | v0.23.0 | 3/3 | ✅ passed | 2026-08-14 |
| 129. 短名单 + 历史先验 + 章程角色图 | v0.23.0 | 4/4 | ✅ passed | 2026-08-14 |
| 130. 放置单元 + 主路径接线 | v0.23.0 | 3/3 | ✅ passed | 2026-08-14 |
| 131. 门禁系统 + 反思环 | v0.23.0 | 3/3 | ✅ passed | 2026-08-14 |
| 132. 集成验收与高三提分回归 | v0.23.0 | 3/3 | ✅ passed | 2026-08-14 |

**Coverage:** 25/25 需求映射；收口 **25 Complete / 0 Partial / 0 Missing**。审计见 [milestones/v0.23.0-MILESTONE-AUDIT.md](./milestones/v0.23.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.22.0 代码智能图分析升级（对标 GitNexus）(Phases 121–127) — SHIPPED 2026-08-11（审计 tech_debt，未打 tag）</summary>

- [x] **Phase 121: 内存图服务基座** — `(repository, branch)` 内存符号图缓存 + 权限/exclusion 读取层收口 (10/10, passed)
- [x] **Phase 122: impact / trace 工具面** — 反向 BFS + 置信度分层 + 跨仓 + MCP/对话双面 (10/10, passed)
- [x] **Phase 123: detect_changes 工具本体** — 水位锚定 diff × Symbol + 批量 impact (6/6, passed)
- [x] **Phase 124: 编码链闭环** — 容器提交前自查 + MR 影响面报告 fail-soft (4/4, passed)
- [x] **Phase 125: 社区检测 + 模块摘要** — Louvain + 指纹跳过 + 三点注入不动冻结面 (4/4, passed)
- [x] **Phase 126: 执行流 + rename_preview + skills** — Process + affected_processes + 只读改名 + skill 分发 (5/5, passed)
- [x] **Phase 127: Semgrep 门禁 + LSP 基准** — diff-aware advisory + volar/gopls 基准 (5/5, human_needed @ 4/4)

完整相位明细见 [milestones/v0.22.0-ROADMAP.md](./milestones/v0.22.0-ROADMAP.md)；相位产物见 [milestones/v0.22.0-phases/](./milestones/v0.22.0-phases/)。

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 121. 内存图服务基座 | v0.22.0 | 10/10 | ✅ passed | 2026-08-09 |
| 122. impact / trace 工具面 | v0.22.0 | 10/10 | ✅ passed | 2026-08-09 |
| 123. detect_changes 工具本体 | v0.22.0 | 6/6 | ✅ passed | 2026-08-10 |
| 124. 编码链闭环 | v0.22.0 | 4/4 | ✅ passed | 2026-08-10 |
| 125. 社区检测 + 模块摘要 | v0.22.0 | 4/4 | ✅ passed | 2026-08-09 |
| 126. 执行流 + rename_preview + skills | v0.22.0 | 5/5 | ✅ passed | 2026-08-10 |
| 127. Semgrep 门禁 + LSP 基准 | v0.22.0 | 5/5 | ⚠️ human_needed（4/4 must-haves） | 2026-08-11 |

**Coverage:** 27/27 需求映射；收口 **26 Complete / 1 Partial（IMPACT-03）/ 0 Missing**。审计见 [milestones/v0.22.0-MILESTONE-AUDIT.md](./milestones/v0.22.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.19.0 技术方案可信度（编排不塌陷 + 路由可解释 + 编排产出直连执行流 + 过程可见）(Phases 105–110，其中 108 已移交 v0.20.0) — COMPLETE 2026-08-02（未打 tag）— 审计 tech_debt</summary>

- [x] Phase 105: 编排解锁与评估标尺 (7/7 plans) — 置信度由分数 margin 确定性推导 + 分数可拆解落 trace + Stage 1 幂等与快照零网络回放 + golden set 回归门禁进默认 suite（RELY-04, ROUTE-07/08/09）— completed 2026-07-30
- [x] Phase 106: 多信号打分函数重构 (8/8 plans) — MaxP + pivoted breadth 消除尺寸偏置 + 域/栈/团队元数据真正入分（缺失重归一化）+ 活跃度指数衰减连续化 + 权重外置不发版可调并绑 `weight_set_version`（ROUTE-03/04/05/06）— completed 2026-07-30
- [x] Phase 107: 分层呈现与链路韧性 (9/9 plans) — `repo_router_ranking` 六个纯函数（分组/迟滞置顶/裁剪/凸组合/降级原因闭集）+ 关联仓从硬过滤改为分组依据 + Stage 1 有界重试与共享预算 + 澄清超时出口真实续驱（ROUTE-01/02, RELY-02/03/05）— completed 2026-07-31
- ~~Phase 108: 方案深度~~ — **已移交 v0.20.0 技术方案蓝图**（DEPTH-01~05 由 `blueprint/v1` 结构化 schema 原生满足；移交于 2026-07-29，两个里程碑双 worktree 并行开发）
- [x] Phase 109: 双脊柱合流 (8/8 plans) — 编排产出经幂等投影直连「选仓→分支→确认编码→导出」四步共用同一 `CodingPlan.id` + schema 层焊死徒手创作路径 + 草稿 fail-closed 与四处一致的「未经代码调研」标注（SPINE-01/02, RELY-01）— completed 2026-07-31
- [x] Phase 110: 过程可观测 (7/7 plans) — `ConvergenceSessionEvent` 单点 fan-out 接 chat SSE + 运行时快照两个隔离分支（编排 / 调研容器日志）+ 六步阶段时间线与按仓日志组挂上编排气泡（OBS-01/02/03）— completed 2026-07-31
- [x] ROUTE 缺口闭环 (2026-08-02，横跨 105/107/110) — 审计发现 ROUTE-01/02/07 与 RELY-03 的用户半边全部建在零挂载点的 `RoutingDecisionPanel` 上；解释职能折进活着的候选面 `RoutingCandidateList.vue` 并删除旧组件，另闭合 `v1_fallback` 降级徽标永不显示的后端洞。报告见 [milestones/v0.19.0-phases/ROUTE-GAP-CLOSURE.md](./milestones/v0.19.0-phases/ROUTE-GAP-CLOSURE.md)

完整阶段详情见 [milestones/v0.19.0-ROADMAP.md](./milestones/v0.19.0-ROADMAP.md)；需求归档见 [milestones/v0.19.0-REQUIREMENTS.md](./milestones/v0.19.0-REQUIREMENTS.md)；里程碑审计 tech_debt（19 条需求 17 满足 / 2 部分 / 0 未达 / 0 BLOCKER；`integration: seams_found` —— `nr_snapshot` 生产方未运行这道接缝仍在；遗留 27 项人工验收全未执行）见 [milestones/v0.19.0-MILESTONE-AUDIT.md](./milestones/v0.19.0-MILESTONE-AUDIT.md) §9。

</details>

<details>
<summary>✅ v0.17.0 统一知识库与全链路联动 (Phases 100–104) — SHIPPED 2026-07-22 — 审计 tech_debt</summary>

- [x] Phase 100: 知识收敛基座 (4/4 plans) — learning case 入图 + 存量回填 + `search_learning_cases` 切向量检索（契约不变）+ MCP 三类产物入图（KNOW-01/02/03）— completed 2026-07-15
- [x] Phase 101: 完工沉淀闭环 (4/4 plans) — 公共飞书回写 service 三链路接入 + 编码完成自动提炼 learning case + 两个平台 Skill 种子 + PR 后可选 review 沉淀（LOOP-01~05）— completed 2026-07-22
- [x] Phase 102: 知识消费面与对外契约 (3/3 plans) — 编排召回扩 kinds + Chat 知识读工具 + ProjectStateApi 可检索 + snapshot/skills 文档对齐（KNOW-04/05/06, UNIFY-04）— completed 2026-07-22
- [x] Phase 103: 编码容器集成 (4/4 plans) — 任务级短 TTL token + 容器知识 MCP + skills 同源注入 + 工作流派发对齐 pack_project_context（AGENT-01~04）— completed 2026-07-22
- [x] Phase 104: 工具面收口 (3/3 plans) — improve/analyze 收敛 delegate_process_runtime + 退役 planning_service 确定性缝 + 清理 plan_orchestration 空壳 + 里程碑四面检索 E2E 验收（UNIFY-01/02/03）— completed 2026-07-22

完整阶段详情见 [milestones/v0.17.0-ROADMAP.md](./milestones/v0.17.0-ROADMAP.md)；里程碑审计 tech_debt（19/19 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留 11 项真实 Qdrant·飞书·容器·Cursor 端人工验证 + 若干接受/递延债务）见 [milestones/v0.17.0-MILESTONE-AUDIT.md](./milestones/v0.17.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）(Phases 96–99) — SHIPPED 2026-07-01 — 审计 tech_debt</summary>

- [x] Phase 96: 外部依赖进检索与总览 (5/5 plans) — 全类型工件登记可发现 + 搜索命中标类型可跳查看 + 知识总览加「交付文档」区块（KDEP-01/02/03）— completed 2026-07-01
- [x] Phase 97: 交付文档知识树视图 (3/3 plans) — `/knowledge` 树页并行「交付文档」树（项目→类型→工件）+ 树内搜索/查看 + 后端树数据 API（KDEP-04/05/06）— completed 2026-07-01
- [x] Phase 98: 工件↔仓库/能力/关键词关联 (3/3 plans) — RepoRouterV2 路由工件正文落 RELATES_TO 边 + 同步 verified RepoAssociation + 关联可查询（KDEP-07/08/09）— completed 2026-07-01
- [x] Phase 99: 关联可视化与交叉入口 (4/4 plans) — 星图纳入 artifact 节点/边 + 知识实体图/详情展示关联 + 作战室↔知识闭环（KDEP-10/11/12）— completed 2026-07-01

完整阶段详情见 [milestones/v0.16.3-ROADMAP.md](./milestones/v0.16.3-ROADMAP.md)；里程碑审计 tech_debt（12/12 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·浏览器视觉端到端验收 + 既有范围外测试漂移）见 [milestones/v0.16.3-MILESTONE-AUDIT.md](./milestones/v0.16.3-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）(Phases 90–95) — SHIPPED 2026-06-28 — 审计 tech_debt</summary>

- [x] Phase 90: 澄清能力层 (4/4 plans) — CLARIFY-01/02/03 — completed 2026-06-27
- [x] Phase 91: 澄清出口面 + 回流 resume (5/5 plans) — CLARIFY-04/05/06/07 — completed 2026-06-27
- [x] Phase 92: 插槽系统（后端） (3/3 plans) — SLOT-01/02 — completed 2026-06-27
- [x] Phase 93: 插槽编辑器（前端） (7/7 plans) — SLOT-03/04 — completed 2026-06-27
- [x] Phase 94: 入口统一 (5/5 plans) — UNIFY-01~06 — completed 2026-06-27
- [x] Phase 95: 拆分完善 (3/3 plans) — DECOMP-01 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.1-ROADMAP.md](./milestones/v0.16.1-ROADMAP.md)；里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [milestones/v0.16.1-MILESTONE-AUDIT.md](./milestones/v0.16.1-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）(Phases 82–89) — SHIPPED 2026-06-26 — 审计 tech_debt</summary>

- [x] Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件 (5/5 plans) — WS-01~04, DOC-01~06 — completed 2026-06-26
- [x] Phase 83: 飞书文档双向同步引擎 (6/6 plans) — SYNC-01~06 — completed 2026-06-26
- [x] Phase 84: 项目工作台前端 2.0 (5/5 plans) — WB-01~05 — completed 2026-06-26
- [x] Phase 85: 项目上下文可读 + 分支绑定 (4/4 plans) — CTX-01/02, BIND-01/02 — completed 2026-06-27
- [x] Phase 86: IDE 上下文闭环（hooks） (5/5 plans) — HOOK-01~04 — completed 2026-06-27
- [x] Phase 87: 看板拆分节点 + 群 + 流式卡片 (4/4 plans) — BOARD-01/02 — completed 2026-06-27
- [x] Phase 88: 智能业务关联仓库 (5/5 plans) — REPO-01/02 — completed 2026-06-27
- [x] Phase 89: 技术方案深化 + 建分支绑项目 (4/4 plans) — PLAN-01~04 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.0-ROADMAP.md](./milestones/v0.16.0-ROADMAP.md)；里程碑审计 tech_debt（37/37 需求、integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [milestones/v0.16.0-MILESTONE-AUDIT.md](./milestones/v0.16.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.15.0 项目（交付上下文聚合根）(Phases 76–81) — SHIPPED 2026-06-26 — 审计 passed</summary>

- [x] Phase 76: 命名腾挪（Project→Space 重构前置） (1/1 plans) — RENAME-01/02 — completed 2026-06-25
- [x] Phase 77: 项目聚合根 + 身份映射 + 成员协作 (1/1 plans) — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25
- [x] Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 (1/1 plans) — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25
- [x] Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 (1/1 plans) — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26
- [x] Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 (1/1 plans) — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26
- [x] Phase 81: Cursor 回流 + 前端项目工作台 (1/1 plans) — CURSOR-01~03, UI-01~03 — completed 2026-06-26

完整阶段详情见 [milestones/v0.15.0-ROADMAP.md](./milestones/v0.15.0-ROADMAP.md)；里程碑审计 passed（38/38 需求、integration_ok）见 [milestones/v0.15.0-MILESTONE-AUDIT.md](./milestones/v0.15.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

### v0.24.0 进度表（Phases 133–140）

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 133. 同仓同 commit 基准与 v0.22 baseline | v0.24.0 | BENCH-01~05 | 0/4 | Planned | - |
| 134. TS/JS resolved 调用边 | v0.24.0 | EDGE-01/02/03/07 | 0/TBD | Not started | - |
| 135. Python resolved 调用边 | v0.24.0 | EDGE-04/05 | 0/TBD | Not started | - |
| 136. Process 一等混合索引 | v0.24.0 | PROC-01~05, OBS-04 | 0/TBD | Not started | - |
| 137. 统一 GraphQueryService | v0.24.0 | QUERY-01~05/08/09/10 | 0/TBD | Not started | - |
| 138. 消歧与 bounded impact | v0.24.0 | QUERY-06/07, OBS-05 | 0/TBD | Not started | - |
| 139. 五消费面契约收敛 | v0.24.0 | CONTRACT-01~05, OBS-03 | 0/TBD | Not started | - |
| 140. Threshold policy 与整体收口 | v0.24.0 | BENCH-06/07, EDGE-06, OBS-01/02 | 0/TBD | Not started | - |

**Coverage (v0.24.0):** 39/39 需求全部映射且每条恰好一次，无孤儿、无重复。阈值严格后置到 Phase 140。

### v0.23.0 进度表（Phases 128–132）

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 128. 专项画像 + 团队门禁地基 | v0.23.0 | PROF-01~03, TEAM-01~03 | 3/3 | Complete   | 2026-08-14 |
| 129. 短名单 + 历史先验 + 章程角色图 | v0.23.0 | LIST-01~04, ROLE-01~03 | 4/4 | Complete   | 2026-08-14 |
| 130. 放置单元 + 主路径接线 | v0.23.0 | UNIT-01~03, INT-01 | 3/3 | Complete   | 2026-08-14 |
| 131. 门禁系统 + 反思环 | v0.23.0 | GATE-01~03, REFL-01~03 | 3/3 | Complete   | 2026-08-14 |
| 132. 集成验收与高三提分回归 | v0.23.0 | INT-02, INT-03 | 3/3 | Complete   | 2026-08-14 |

**Coverage (v0.23.0):** 25/25 需求全部映射，无孤儿、无重复。约束：演进 `BlueprintRouteAdapter` / `RepoAssociationService`；不推倒 `RepoRouterV2`（降为 shortlist 内细排）；新阶段遵守可观测日志规范。

<details>
<summary>✅ v0.22.0 进度表（Phases 121–127，26 Complete / 1 Partial）</summary>

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 121. 内存图服务基座 | v0.22.0 | GRAPH-01~04 | 10/10 | ✅ passed | 2026-08-09 |
| 122. impact / trace 工具面 | v0.22.0 | IMPACT-01~06 | 10/10 | ✅ passed | 2026-08-09 |
| 123. detect_changes 工具本体 | v0.22.0 | DIFF-01/02 | 6/6 | ✅ passed | 2026-08-10 |
| 124. 编码链闭环 | v0.22.0 | DIFF-03/04 | 4/4 | ✅ passed | 2026-08-10 |
| 125. 社区检测 + 模块摘要 | v0.22.0 | MOD-01~04 | 4/4 | ✅ passed | 2026-08-09 |
| 126. 执行流 + rename_preview + skills | v0.22.0 | EXEC-01~03, RENAME-01, SKILL-01 | 5/5 | ✅ passed | 2026-08-10 |
| 127. Semgrep 门禁 + LSP 基准 | v0.22.0 | TAINT-01~03, LSP-01 | 5/5 | ⚠️ human_needed（4/4） | 2026-08-11 |

**Coverage (v0.22.0):** 27/27 需求映射；收口 **26 Complete / 1 Partial（IMPACT-03）/ 0 Missing**。审计 tech_debt 见 [milestones/v0.22.0-MILESTONE-AUDIT.md](./milestones/v0.22.0-MILESTONE-AUDIT.md)；相位产物在 `milestones/v0.22.0-phases/`。**未打 tag**。

</details>

---

里程碑 v0.1.0–v0.23.0（Phases 1–132）均已交付并归档。v0.24.0 从 Phase 133 继续。

**当前在建：** 🚧 **v0.24.0 单仓图查询对齐 GitNexus**（Phases 133–140），Phase 133 ready to plan。遗留债务见 STATE.md Deferred Items / Pending Todos。

<details>
<summary>✅ v0.20.0 进度表（Phases 111–116，34/35 需求已交付 · GATE-01 PARTIAL）</summary>

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 111. 蓝图底座 | v0.20.0 | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | 4/4 | ✅ Complete (passed 24/24) | 2026-07-30 |
| 112. 规格门与双面路由调研 | v0.20.0 | FLOW-01/02/03/04, CHARTER-02/03 | 5/5 | ✅ Complete (16/17 + gap closed) | 2026-07-30 |
| 113. 分仓方案与融合 + Context Bus | v0.20.0 | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | 6/6 | ✅ Complete (passed 54/54) | 2026-07-30 |
| 114. 审查与澄清收敛 | v0.20.0 | FLOW-07, CLAR-02/03/04 | 5/5 | ✅ Complete (passed 83/83) | 2026-07-31 |
| 115. 前端查看器与知识库 | v0.20.0 | VIEW-01/02/03/04, CLAR-01, FLOW-08 | 7/7 | ✅ Complete (passed 107/107) | 2026-08-01 |
| 116. 入口收编与导出 | v0.20.0 | GATE-01, VIEW-05（+ 闭合 VIEW-04、VIEW-02） | 7/7 | ✅ Complete (passed 121/121) | 2026-08-01 |

**Coverage (v0.20.0):** 35/35 需求全部映射，无孤儿、无重复；34 条 Complete、GATE-01 PARTIAL（默认入口切换原硬阻塞同步点 2，该依赖已于 2026-08-02 合并时满足）。里程碑审计 tech_debt 见 [milestones/v0.20.0-MILESTONE-AUDIT.md](./milestones/v0.20.0-MILESTONE-AUDIT.md)；相位产物归档在 `milestones/v0.20.0-phases/`。

</details>

<details>
<summary>✅ v0.19.0 进度表（Phases 105–110，19/19 需求映射 · 17 Complete / 2 Partial）</summary>

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 105. 编排解锁与评估标尺 | v0.19.0 | RELY-04, ROUTE-07/08/09 | 7/7 | ✅ Complete（自动化验证 35/35，人工 UAT 3 项挂账） | 2026-07-30 |
| 106. 多信号打分函数重构 | v0.19.0 | ROUTE-03/04/05/06 | 8/8 | ✅ Complete（自动化验证 34/38，人工 UAT 4 项挂账） | 2026-07-30 |
| 107. 分层呈现与链路韧性 | v0.19.0 | ROUTE-01/02, RELY-02/03/05 | 9/9 | ✅ Complete（自动化验证 87/89，人工 UAT 6 项挂账） | 2026-07-31 |
| 108. 方案深度 | 移交 v0.20.0 | DEPTH-01~05（随迁） | - | Moved (2026-07-29) | - |
| 109. 双脊柱合流 | v0.19.0 | SPINE-01/02, RELY-01 | 8/8 | ✅ Complete（人工 UAT 6 项挂账） | 2026-07-31 |
| 110. 过程可观测 | v0.19.0 | OBS-01/02/03 | 7/7 | ✅ Complete（GAP-1 已闭合；人工 UAT 8 项挂账） | 2026-07-31 |

**Coverage (v0.19.0):** 19/19 需求全部映射，无孤儿、无重复（DEPTH-01~05 已移交 v0.20.0，不再计入本里程碑）。**收口 17 Complete / 2 Partial（ROUTE-03、RELY-02）/ 0 未达**，里程碑判定 `tech_debt`。需求归档见 [milestones/v0.19.0-REQUIREMENTS.md](./milestones/v0.19.0-REQUIREMENTS.md)。

</details>

<details>
<summary>✅ v0.17.0 进度表（Phases 100–104，19/19 需求已交付）</summary>

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 100. 知识收敛基座 | v0.17.0 | KNOW-01/02/03 | 4/4 | ✅ Complete | 2026-07-15 |
| 101. 完工沉淀闭环 | v0.17.0 | LOOP-01~05 | 4/4 | ✅ Complete | 2026-07-22 |
| 102. 知识消费面与对外契约 | v0.17.0 | KNOW-04/05/06, UNIFY-04 | 3/3 | ✅ Complete | 2026-07-22 |
| 103. 编码容器集成 | v0.17.0 | AGENT-01~04 | 4/4 | ✅ Complete | 2026-07-22 |
| 104. 工具面收口 | v0.17.0 | UNIFY-01/02/03 | 3/3 | ✅ Complete | 2026-07-22 |

里程碑审计 tech_debt（19/19 需求满足 / integration_ok；遗留 11 项真实环境人工验证）见 [audit](./milestones/v0.17.0-MILESTONE-AUDIT.md)。

</details>

**v0.22.0 遗留的技术债**（IMPACT-03 真样本 / mcp npm 图工具漂移 / RepoRouterV2Adapter 未挂 module_summary / CreatePRNode 未挂 impact_report / Nyquist 未 validated / 127 SHA 双失败 pending / 三项 human_needed）见 [audit](./milestones/v0.22.0-MILESTONE-AUDIT.md) 与 STATE.md Deferred Items。**v0.20.0** mcp npm 蓝图四工具漂移等见 [audit](./milestones/v0.20.0-MILESTONE-AUDIT.md)；**v0.19.0** 27 项人工验收 + ROUTE-03/RELY-02 PARTIAL 见 [audit](./milestones/v0.19.0-MILESTONE-AUDIT.md) §9.3/§9.5。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
