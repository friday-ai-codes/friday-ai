# Roadmap: Friday AI

## Milestones

- 🚧 **v0.23.0 仓库路由增强（分阶段决策漏斗）** — Phases 128–132 (in progress) — 把「全库单段文本相似度选仓」升级为「画像 → 团队门禁 → 短名单 → 章程/历史 → 放置单元 → 门禁/反思」的可解释决策漏斗；验收锚点「高三提分专项」 — [requirements](./REQUIREMENTS.md) · [research](./research/ROUTING-RANKING.md)
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

### 🚧 v0.23.0 仓库路由增强（分阶段决策漏斗）(Phases 128–132) — IN PROGRESS

**Milestone Goal:** feature list 类需求经可解释决策漏斗稳定命中正确仓集（团队门禁 + 短名单 + 章程角色 + 放置单元 + 门禁/反思），不再漂到语义巧合仓；在 `BlueprintRouteAdapter` / `RepoAssociationService` 上演进，不推倒 `RepoRouterV2`。

- [x] **Phase 128: 专项画像 + 团队门禁地基** — 决策漏斗入口与硬范围（画像机读 + team_core / out_of_team）
- [x] **Phase 129: 短名单 + 历史先验 + 章程角色图** — 候选生成升级（shortlist 可解释 + 主/辅/禁） (completed 2026-08-14)
- [x] **Phase 130: 放置单元 + 主路径接线** — shortlist 内细落点 + 蓝图路由走漏斗 (completed 2026-08-14)
- [ ] **Phase 131: 门禁系统 + 反思环** — pass/clarify/block + 有界回跳修复
- [ ] **Phase 132: 集成验收与高三提分回归** — 回归锚点 + 契约不回归 + 合成反思用例

## Phase Details

### Phase 128: 专项画像 + 团队门禁地基

**Goal**: 系统能从 feature list 产出可机读专项画像，并划定 `team_core` 硬范围——`out_of_team` 默认不可作 primary，无团队时进入 clarify/block 而非全库裸路由
**Depends on**: Nothing（本里程碑首相位；依赖既有 BlueprintRoute / Space / 项目挂载）
**Requirements**: PROF-01, PROF-02, PROF-03, TEAM-01, TEAM-02, TEAM-03
**Success Criteria** (what must be TRUE):

  1. 给定含模块总览/简述的 feature list，系统产出可机读专项画像（产品形态、域、brownfield/greenfield/fix、主能力簇、显式非目标、复用声明摘要）
  2. 画像主路径不把验收项/测试 case 正文当主语料；仅有操作细节语料时进入澄清而非静默建噪声画像
  3. 画像写入路由 stage 可观测结构（可回放、绑定 request/run id）；失败 fail-soft 并带明确 degrade 原因
  4. 系统解析 `primary_team`/Space 产出 `team_core`；`out_of_team` 默认不可作 primary，仅 `team_adjacent`（有复用/章程证据）可例外
  5. 无可用团队/空间或 `team_core` 为空（或全无索引）时，路由进入 `clarify`/`block`，不得静默退回全库裸路由

**Plans:** 3 plans

Plans:

- [x] 128-01-PLAN.md — 专项画像模块（PROF-01~03）：corpus 剔除 + build_profile + fail-soft 观测
- [x] 128-02-PLAN.md — 团队门禁模块（TEAM-01~03）：team_core 解析 + hard gate + 空团队 clarify（D1/D3）
- [x] 128-03-PLAN.md — 漏斗三入口接线：Blueprint / RepoAssociation / MCP，禁止静默全库 primary

### Phase 129: 短名单 + 历史先验 + 章程角色图

**Goal**: 在团队范围内生成可解释 shortlist（活跃度 + 能力树粗相关 + 章程域 + 历史先验强制拉入），并对 shortlist 产出主/辅/禁角色图约束后续落点
**Depends on**: Phase 128
**Requirements**: LIST-01, LIST-02, LIST-03, LIST-04, ROLE-01, ROLE-02, ROLE-03
**Success Criteria** (what must be TRUE):

  1. 在 `team_core`（∪ 合法 adjacent）内，系统用活跃度 + 能力树粗相关（吃专项画像）+ 章程 domain 命中生成 shortlist
  2. 章程规划中域（`evolution`/planned）的仓在能力树分低时仍可进入 shortlist；历史「需求史/上线史」与 `team_core` 求交后可强制拉入
  3. shortlist 大小与排序可解释（逐仓信号 breakdown）；观测上报候选数/耗时，不回显需求原文
  4. 对 shortlist 逐仓产出主/辅/禁角色图（至少覆盖 App 壳、做题/复用宿主、课程配置、学习状态）；触碰 `boundaries` 的落点被降级或剔除（除非显式 override）
  5. 角色图进入后续放置默认约束（例如状态域默认写方 ≠ 任意 UI 页壳主仓）

**Plans:** 4/4 plans complete

Plans:

- [x] 129-01-PLAN.md — shortlist 生成（activity + capability_coarse + charter / planned force-include + breakdown）
- [x] 129-02-PLAN.md — 历史先验分桶（需求史/上线史）∩ team_core force-include
- [x] 129-03-PLAN.md — 固定四角色角色图 + boundaries + placement_defaults
- [x] 129-04-PLAN.md — Blueprint/入口接线 shortlist+role_map（候选 ⊆ shortlist）

### Phase 130: 放置单元 + 主路径接线

**Goal**: feature 点聚合为放置单元后在 shortlist 内细落点（可调用 RepoRouterV2 但不得对全库开放 primary）；蓝图路由/项目选仓主路径走决策漏斗
**Depends on**: Phase 129
**Requirements**: UNIT-01, UNIT-02, UNIT-03, INT-01
**Success Criteria** (what must be TRUE):

  1. 系统将 feature 点聚合为放置单元（Placement Units），依据模块依赖与正文「复用 X」边，避免逐点独立全库检索
  2. 每个放置单元在 shortlist 内产出 `primary_repo` + `supporting_repos[]` + confidence + evidence + open_questions
  3. 细排可调用 `RepoRouterV2`，但候选范围硬限制在 shortlist（或 shortlist ∪ 复用宿主），禁止再对全库开放 primary
  4. 蓝图路由 / 项目选仓主路径走决策漏斗（或等价编排）；三分量加权可作为漏斗内信号，不再作为唯一决策

**Plans**: 3 plans

Plans:

- [x] 130-01-PLAN.md — Placement Units 聚合（模块依赖 + 复用边）
- [x] 130-02-PLAN.md — shortlist∪reuse-host 内细落点（V2 硬限制）
- [x] 130-03-PLAN.md — Blueprint/Association 主路径漏斗接线（INT-01）

### Phase 131: 门禁系统 + 反思环

**Goal**: 统一 `pass | clarify | block` 门禁贯穿各阶段，并在证据冲突等条件下有预算反思回跳修复（不无界全库重跑）
**Depends on**: Phase 130
**Requirements**: GATE-01, GATE-02, GATE-03, REFL-01, REFL-02, REFL-03
**Success Criteria** (what must be TRUE):

  1. 门禁统一输出 `pass | clarify | block` + `reason_codes[]` + evidence，贯穿路由阶段可观测
  2. 至少落地：团队门、短名单覆盖门、单元落点门、全局一致性门、发布门（P0 未确认不可下游开工）
  3. 全局一致性门拦截：出界 primary、同一状态域双写、页面壳散落多 App 仓、违背「复用不改造」类边界
  4. 证据冲突/角色坍塌/复用矛盾/覆盖空洞等触发反思，最多 N 轮（默认 2），超限进入 `needs_human_review`；补丁只重算受影响短名单/单元
  5. 每轮反思写入 ledger/事件（脱敏）可回放

**Plans**: 3 plans

Plans:

- [ ] 131-01-PLAN.md — 统一门禁契约 + 五门（含 D4 发布 / 全局一致性）
- [ ] 131-02-PLAN.md — 有界反思环（N=2、补丁范围、ledger）
- [ ] 131-03-PLAN.md — Blueprint/Association/sandbox 门禁与反思接线

### Phase 132: 集成验收与高三提分回归

**Goal**: 以「高三提分专项」为回归锚点验证漏斗命中四基线仓且 out_of_team 不作 primary；既有契约不回归，门禁/反思有自动化测试
**Depends on**: Phase 131
**Requirements**: INT-02, INT-03
**Success Criteria** (what must be TRUE):

  1. 以「高三提分专项」feature list 为回归锚点：在学习工具 Space 下，四基线仓（`onion-learning`、`onion-practice`、`study-course`、`study-user-status`）作为 primary 集合的覆盖达到约定门槛（文档化 hit@primary / 角色覆盖）
  2. 同用例下 `out_of_team` 仓不得成为 primary
  3. 既有单测与 MCP/编排契约不回归；新增门禁/反思路径有自动化测试（含至少一条角色坍塌→反思修复的合成用例）

**Plans**: TBD

---

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

### v0.23.0 进度表（Phases 128–132）

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 128. 专项画像 + 团队门禁地基 | v0.23.0 | PROF-01~03, TEAM-01~03 | 3/3 | Complete   | 2026-08-14 |
| 129. 短名单 + 历史先验 + 章程角色图 | v0.23.0 | LIST-01~04, ROLE-01~03 | 4/4 | Complete   | 2026-08-14 |
| 130. 放置单元 + 主路径接线 | v0.23.0 | UNIT-01~03, INT-01 | 3/3 | Complete   | 2026-08-14 |
| 131. 门禁系统 + 反思环 | v0.23.0 | GATE-01~03, REFL-01~03 | 0/? | Not started | - |
| 132. 集成验收与高三提分回归 | v0.23.0 | INT-02, INT-03 | 0/? | Not started | - |

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

里程碑 v0.1.0–v0.22.0（Phases 1–127）均已交付并归档。v0.19.0 与 v0.20.0 于 2026-07-29 起双 worktree 并行，2026-08-02 合并（同步点 2）。v0.21.0 于 2026-08-05 轻量归档；v0.22.0 于 2026-08-11 归档（tech_debt，未打 tag）。

**当前在建：** 🚧 **v0.23.0 仓库路由增强（分阶段决策漏斗）** — Phases 128–132。遗留债务见 STATE.md Deferred Items / Pending Todos。

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
