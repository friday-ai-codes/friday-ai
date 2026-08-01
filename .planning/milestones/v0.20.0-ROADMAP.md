# Roadmap: Friday AI

## Milestones

- ✅ **v0.20.0 技术方案蓝图（六段结构化蓝图 + 确认门与分仓方案 + 划线澄清收敛 + 全入口收编）** — Phases 111–116 (completed 2026-08-01，待与 v0.19.0 合并后归档) — 技术方案从单轮 JSON 升级为「人类可读、AI 可依此完备编码」的项目级结构化蓝图 — 里程碑审计 tech_debt（34/35 需求满足 / 6 相位全 verified / 7 道跨相位接缝全 WIRED / 0 gaps；GATE-01 因硬依赖同步点 2 判 PARTIAL）见 [audit](./v0.20.0-MILESTONE-AUDIT.md) — [requirements](./REQUIREMENTS.md) · [design](./technical-blueprint/DESIGN.md)
- 🟡 **v0.19.0 技术方案可信度（编排不塌陷 + 路由可解释 + 方案够深 + 过程可见）** — Phases 105–110 (planning) — 让技术方案链路真正跑通并可信：编排不再中途卡死被降级工具顶替、路由基于多维证据分层呈现并可解释、方案结构覆盖数据流编排与模块↔仓映射、全过程对用户实时可见 — [requirements](./REQUIREMENTS.md) · [research](./research/ROUTING-RANKING.md)
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

### ✅ v0.20.0 技术方案蓝图 (Phases 111–116) — COMPLETE（六相位全部完成并 verified，里程碑审计 tech_debt，待归档；与 v0.19.0 双 worktree 并行）

**Milestone Goal:** 技术方案从单轮 JSON 升级为「人类可读、AI 可依此完备编码」的项目级结构化蓝图——六段固定骨架每条结论带引用证据，三大编排阶段贯穿仓库确认门与分仓方案，仓库章程补齐净新增落点知识，飞书式划线澄清多轮收敛，全生命周期状态可管理，知识库可查、可引用、可导出。

> **设计输入:** [.planning/technical-blueprint/DESIGN.md](./technical-blueprint/DESIGN.md)（13 节，§12 八项决策已定夺）。**并行纪律（§13.2，强制）:** 不改 `repo_router_v2.py`；冻结既有 `technical_plan` process 六文件（流水线全走 `blueprint_*` 新文件，`builtin_processes.py` 仅加注册项）；`ConvergenceSessionEvent` 既有契约只消费不修改（仅新增 `blueprint_*` 事件类型）；前端只新建组件，TechPlanCard/时间线触点升级留到同步点 2 后。DEPTH-01~05 自 v0.19.0 Phase 108 迁入（映射见 REQUIREMENTS.md）。

- [x] **Phase 111: 蓝图底座** - blueprint/v1 schema 强制校验 + 11 态生命周期状态机 + 划线线程/评审人模型 + RepoCharter 章程模型与 AI 起草管道 + execution_plan 确定性派生 + golden set 质量基线（SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02）— completed 2026-07-30（4/4 plans，verification passed 24/24）
- [x] **Phase 112: 规格门与双面路由调研（阶段 1）** - spec_gate 歧义门与意图分类 + blueprint_route 双面路由（章程/历史落点/能力树融合）+ 逐仓容器 fitness 调研 + reroute 有界循环 + repo_confirmation 硬确认门与章程回灌（FLOW-01/02/03/04, CHARTER-02/03）— completed 2026-07-30（5/5 plans，verification 16/17 + gap closure）
- [x] **Phase 113: 分仓方案与融合（阶段 2/3）+ Context Bus** - repo_plan 逐仓方案 + 会话级共享上下文总线（实时读写/等待恢复/环检测）+ merge 融合装配（六段 + 引用强制 + 跨仓 API 对账）（FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03）— completed 2026-07-30（6/6 plans，verification passed 54/54）
- [x] **Phase 114: 审查与澄清收敛** - AI 对抗审查七类规则与归因打回 + 澄清答案回灌产新版本 + 决策记录物化 + pending 语义 + 人工 block 编辑（FLOW-07, CLAR-02/03/04） (completed 2026-07-31)
- [x] **Phase 115: 前端查看器与知识库** - BlueprintViewer 六段结构化渲染与批注层 + 二级引用预览 + 知识库技术方案 tab + 项目关联 + 人审终审 UI（VIEW-01/02/03/04, CLAR-01, FLOW-08） (completed 2026-07-31)
- [x] **Phase 116: 入口收编与导出** - MCP 异步澄清协议 + 全入口统一走蓝图编排 + 飞书导出升级 + 知识图谱物化 + 引用预览源码正文（GATE-01, VIEW-05，并闭合 115 顺延的 VIEW-04 / VIEW-02）— completed 2026-08-01（7/7 plans）。⚠️ **触点升级与默认入口切换未做**：硬依赖同步点 2（v0.19.0 Phase 109/110 合并），顺延为里程碑收尾之后的独立工作项 ⇒ GATE-01 保持 PARTIAL

**执行顺序（依赖链）:** 111 → 112 → 113 → 114 → 115 → 116，线性。111 是数据与质量地基（schema/状态机/线程/章程/golden set 全是后续相位的消费对象）；112 先锁规格与仓库集（确认门锁定是 113 分仓方案的输入）；113 产出完整蓝图（114 才有东西可审）；114 收敛审查与澄清闭环（115 才有完整状态与线程可展示）；115 查看器就位后 116 才能做全入口收编（人审终审是收编的前置能力）。**与 v0.19.0 的同步点:** 同步点 1 = 0.19 Phase 107 合并主干（rebase 对齐澄清送达/提醒设施，影响 112/114 的送达通道，未合并前用现有澄清通道兜底）；同步点 2 = 0.19 Phase 109/110 合并（execution 投影与事件时间线契约就位，116 的触点升级与入口切换在其后执行）。

**UI 触面:** Phase 115（查看器/批注层/知识库 tab——`/gsd-ui-phase` 应介入）、Phase 116（TechPlanCard/工作流节点触点接入）。

#### Phase Details (v0.20.0)

### Phase 111: 蓝图底座（schema + 生命周期 + 线程/章程模型 + 质量基线）

**Goal**: 蓝图的一切结构与状态有了权威地基——blueprint/v1 schema 由 jsonschema 强制、11 态生命周期有守卫可追溯、划线线程与评审人模型就位、仓库章程模型与 AI 起草管道可用、execution_plan 可确定性派生、golden set 质量基线建立。
**Depends on**: Nothing（与 v0.19.0 零文件交集，立即可动工；§13.2 边界纪律全程生效）
**Requirements**: SCHEMA-01, SCHEMA-06, SCHEMA-07, LIFE-01, LIFE-02, LIFE-03, CHARTER-01, GATE-02
**Success Criteria** (what must be TRUE):

  1. 构造缺段/缺必填字段的蓝图 JSON 写入被 jsonschema 校验拒绝；六段齐全的样例通过校验落 `ArtifactVersion`（content.schema_version=blueprint/v1），同一蓝图两个版本可产出 block 级 diff（新增/删除/修改块可辨识）。
  2. 蓝图 11 态转移由 `BlueprintLifecycleService` 单点收口：存在 open+blocking 线程时 confirm 被拒绝；失败/废弃是显式终态且失败可重试；每次转移落 `ConvergenceSessionEvent`（新增 `blueprint_*` 类型，不改既有类型）。
  3. 任一项目成员执行确认动作后自动进入该蓝图的方案评审人名单，名单可查、可手动增补，署名与时间留痕。
  4. `RepoCharter` 可由 AI 从 ai_summary/近期 MR 历史/既有 RepoAssociation 裁决蒸馏出草案，人工 confirm 后生效（source=human_confirmed）；对人工确认过的章程 AI 只能提修订草案、不能直接覆盖。
  5. 蓝图 golden set 离线可跑：含高三提分专项首条 golden case，输出引用覆盖率/目标仓命中率/审查打回率等指标，同输入重复运行结果一致。

**Plans**: 4 plans（wave 1: 01/02/03 并行；wave 2: 04）

Plans:

- [x] 111-01-PLAN.md — blueprint/v1 六段 jsonschema + block diff + execution_plan 确定性派生 + builtin_types 校验接线（SCHEMA-01/06/07）
- [x] 111-02-PLAN.md — Artifact.blueprint_status 11 态 + BlueprintThread/Message/Reviewer 模型 + LifecycleService 守卫/CAS/事件 + 重锚定纯函数（LIFE-01/02/03）
- [x] 111-03-PLAN.md — RepoCharter 模型 + AI 起草管道 + charter REST 三端点 + call_source 8 值与 LOGGING-SPEC 登记（CHARTER-01）
- [x] 111-04-PLAN.md — blueprint_quality 指标 + 高三提分专项 golden case + evaluate_blueprint_golden command + 全链路集成冒烟（GATE-02）

### Phase 112: 规格门与双面路由调研（阶段 1：调研与确认门）

**Goal**: 需求进来先锁规格再定仓——歧义超阈值必澄清、feature_point 带意图分类；路由融合章程/历史落点/能力树三路证据且分数可解释；逐仓容器调研产出 fitness 判定与职责建议；不合适仓有界重路由；出口硬确认门锁定仓库集与职责并回灌章程。
**Depends on**: Phase 111（schema/线程/章程模型是本相位的读写对象）。软依赖同步点 1（v0.19.0 Phase 107 澄清送达设施；未合并前用现有澄清通道兜底，合并后 rebase 对齐）
**Requirements**: FLOW-01, FLOW-02, FLOW-03, FLOW-04, CHARTER-02, CHARTER-03
**Success Criteria** (what must be TRUE):

  1. 需求歧义超阈值时编排停在「需要澄清」并抛出带候选选项与证据的问题，作答后规格锁定且同一问题不再重复问；每个 feature_point 带 greenfield/brownfield/fix 意图标注。
  2. `blueprint_route` 输出候选带 `charter_match` 分量且分数可拆解；greenfield 功能点上章程 owned(planned) 的仓能进入候选（复现高三提分专项 case：onion-learning 不再因能力树无节点被淘汰）；brownfield 上命中章程禁区的候选被降权，LLM 保留它必须给显式理由。
  3. 每个候选仓由独立 claude code 容器调研（PLAN 链接通任务 token 与容器知识 MCP），回传 fitness 判定 + role 建议 + 职责描述 + 带 citations 的现状 findings；unsuitable 触发重路由 ≤2 轮，仍不收敛升确认门由用户裁决。
  4. 确认门展示仓库清单/role/职责/fitness/现状摘要/证据；用户移除仓、手动加仓（触发新仓调研）、改判 role、修改职责均驱动对应重调研；确认后仓库集与职责锁定，后续阶段擅自变更会被 AI 审查判 BLOCKER。
  5. 确认门动作产生章程修订草案（确认/改判 → owned_domains、移除 → boundaries），人工 confirm 后生效；rejected 路由候选可一键沉淀为章程禁区候选。

**Plans**: 5 plans（wave 1: 01；wave 2: 02/03 并行；wave 3: 04；wave 4: 05）

Plans:

- [x] 112-01-PLAN.md — feature_points[].intent 必填枚举 + 2 份字面数据同步与 6 个消费测试回归 + SettingKeys 歧义阈值/路由权重两键与 async float/json getter + 112 阶段事件常量（FLOW-01, CHARTER-02 前置）
- [x] 112-02-PLAN.md — spec_gate 歧义门：LLM 四维打分（call_source=blueprint_spec_gate）+ 意图分类 + BlueprintThread(ai_clarification, blocking) 澄清回路 + 规格锁定与 decision_log 物化 + 不重复提问（FLOW-01）
- [x] 112-03-PLAN.md — blueprint_route 双面路由：RepoRouterV2 原样输出为 router_base + charter_match（owned/planned、boundaries 判负、evolution 降权、章程候选补入）+ history_match（delivery knowledge）+ intent 加权 + breakdown 三分量恒等式（CHARTER-02, FLOW-04）
- [x] 112-04-PLAN.md — blueprint_research_adapter 逐仓容器调研：fan-out + mint_task_token 与 3 个 env 键接通 + 章程随 prompt 注入 + fitness 落 PartialPlan.content + callbacks 第三条 PLAN 链 + reroute ≤2 轮与超限升确认门（FLOW-02, FLOW-04）
- [x] 112-05-PLAN.md — repo_confirmation 硬确认门：五动作 REST 经 BlueprintLifecycleService 收口 + 仓库集/职责锁定与 decision_log + 章程回灌 ai_draft 与 rejected 一键沉淀 + technical_blueprint 七 stage 注册 + blueprint_resume 蓝图专用续驱（FLOW-03, CHARTER-03）

### Phase 113: 分仓方案与融合（阶段 2/3）+ Blueprint Context Bus

**Goal**: 确认后的每个仓产出结构化分仓方案，跨仓动态依赖靠会话级上下文总线协商；主 agent 融合装配出六段齐全、引用完备、跨仓 API 对账闭环的完整蓝图。
**Depends on**: Phase 112（确认门锁定的仓库集与职责是分仓方案的输入）
**Requirements**: FLOW-05, FLOW-06, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05, BUS-01, BUS-02, BUS-03
**Success Criteria** (what must be TRUE):

  1. 每个 direct 仓产出 RepoPlan（实现项含 change_type/伪代码/涉及文件/测试策略、提供与消费 API、局部影响、风险），indirect 仓产出能力引用清单；拟定中可抛澄清线程、可发起单仓定向补调研。
  2. 蓝图容器凭任务 token 实时读写会话上下文总线（全程无分支）；「A 仓等 B 仓接口契约」场景跑通：短等待 await 轮询拿到即继续，长等待以 waiting_context 携带 partial 产物退出、条目就绪后自动重派续作；互相等待环被检测并抛澄清给用户裁决。
  3. merge 产出的蓝图通过 schema 校验且六段齐全：实现项逐项标 change_type 并映射功能↔模块↔仓库；交互流程覆盖「页面→接口→参数→数据→流向→行为路径」完整叙事；API 段含数据来源与可用性说明。
  4. 现状 finding/选仓理由/影响判断的引用覆盖率达到基线（golden set 可量测）；consumed API 无 provider 时被标 needs_support 且支持仓出现在仓库关联；跨仓矛盾在融合中抛澄清而非静默拍板。
  5. 会话结束后有价值的总线条目可经 distill 管道生成项目记忆草案（人工 confirm 生效）。

**Plans**: 6 plans（wave 1: 01；wave 2: 02/03 并行；wave 3: 04；wave 4: 05；wave 5: 06）

Plans:

- [x] 113-01-PLAN.md — BlueprintContextEntry 模型 + 0032 migration（三复合索引 + seq 唯一约束）+ BlueprintContextService（锁父行 seq 分配 / JSON 递归脱敏自建 / waiter 登记含环检测 / satisfy 同事务置 superseded）+ 三个 blueprint.context.* 事件（BUS-01/02 数据面）
- [x] 113-02-PLAN.md — 容器 MCP 两侧接通：服务端 read_/report_blueprint_context 两 view + **view 层自建三道会话校验**（鉴权链只到 token→owner）+ 全路径非 5xx + task 侧白名单 7→9（公共 handler 工厂零改动）（BUS-01）
- [x] 113-03-PLAN.md — RepoPlan 分仓方案：新建 blueprint_repo_plan_schema.py（§5.3 十一字段）+ 派发面 mode="plan" 四扩展点（缺省等价 112）+ BlueprintRepoPlanAdapter（确认门仓集 / direct 派发 / indirect 合成 / 有界重试 / 自写完成判据）+ callbacks 第四链（FLOW-05, SCHEMA-03）
- [x] 113-04-PLAN.md — 等待原语：await_blueprint_context 容器侧有界轮询（超时返正常结果非 is_error）+ waiting_context 退出与自动重派续作 + 波次预排纯函数（provider 先行）+ 互等环抛澄清；三条路径各有可证伪断言（BUS-02）
- [x] 113-05-PLAN.md — 融合装配：blueprint_reconcile 跨仓 API 对账纯函数 + blueprint_merge（确定性投影含 rationale.citations / 引用池先建后填 / 四段分节 LLM / must_haves 确定性派生 / 幂等落 ArtifactVersion）（FLOW-06, SCHEMA-02/03/04/05）
- [x] 113-06-PLAN.md — 融合门与 stage 收口：引用覆盖率门（阈值走 SettingKeys.BLUEPRINT_MERGE_CONFIG）+ coverage_gaps 归因 + 有界回退 ≤2 轮 + 超界转 STAGE_DONE 带未决项 + technical_blueprint 追加 repo_plan→merge 两 stage（只加不改）+ distill 沉淀草案（FLOW-06, SCHEMA-02, BUS-03）

### Phase 114: 审查与澄清收敛（AI 对抗审查 + 线程闭环 + 人工编辑）

**Goal**: 蓝图到达人审前先过独立 AI 对抗审查，findings 化为划线线程有界收敛；澄清答案回灌产新版本、决策物化；pending 语义与人工编辑链路闭环。
**Depends on**: Phase 113（有完整蓝图可审）
**Requirements**: FLOW-07, CLAR-02, CLAR-03, CLAR-04
**Success Criteria** (what must be TRUE):

  1. 独立审查代理（fresh context）按七类规则产出分级 findings 并锚定到 block，直接生成划线线程；仓级 BLOCKER 只打回对应仓的 repo_plan、融合级回 merge，合计 ≤2 轮后带未决项升人审；确认门锁定的仓库集/职责被擅自变更、direct 仓实现项违背章程禁区且无决策记录支撑，均判 BLOCKER。
  2. 澄清作答后由对应阶段代理消费答案产出新版本，线程置 resolved 并记录 applied_in_version，结论物化进蓝图决策记录段；旧版本批注在新版本上按 block_id + quoted_text 重锚定，失锚线程集中可见。
  3. 人工直接编辑 block 生成新版本（produced_by=human_edit，归属可审计）；后续 AI 修订以人工版本为基线不覆盖人工内容，冲突时开线程询问。
  4. blocking 澄清无人应答时会话停在「需要澄清」显式状态并按配置周期提醒（飞书卡片重推/站内通知），随时作答恢复；不自动作答、不判失败。

**Plans**: 5 plans（wave 1: 01；wave 2: 02；wave 3: 03；wave 4: 04；wave 5: 05）

Plans:

- [x] 114-01-PLAN.md — 线程底座：open_thread 追加 severity 形参（零 migration，既有调用逐字等价）+ blocking == (severity=="blocker") 不变式强制 + 从 _append_thread_message_sync 提炼公开 append_note（留痕不改状态，record_answer 禁用于 finding）+ confirm 守卫两条判据收敛进 _apply_transition_sync 同一事务的单次 Q 查询消除 TOCTOU（FLOW-07）
- [x] 114-02-PLAN.md — 新建 blueprint_review.py：六类机械规则纯函数（前置完整性短路 / schema / 引用覆盖条目级 / 角色一致性 / API 闭环 / 禁令 / 章程边界 + 确认门锁定校验）在无 LLM 下产确定性结论，每类一条构造样例证伪；goal-backward 一类走 LLM（call_source=blueprint_ai_review，签名纳入 requirement_spec.constraints 并进 digest 使「与 constraints 冲突」可判，不可得 fail-closed 记 warning meta finding）（FLOW-07）
- [x] 114-04-PLAN.md — 澄清回灌与人工编辑（**wave 3，已提前到 114-03 之前**）：areanchor_threads 批量重锚定（diff 预筛 + section_path 刷新 + 失锚 orphaned 不删 + 一次 bulk_update）+ block 级 patch ops 经 service 收口产 human_edit 版本（不合法拒绝且不落版本）+ 回灌三步链与 decision_log 物化保 answer 键、decided_at 用作答消息时间戳保幂等 + section_writer 生产实现 ablock_section_writer（默认注入，答案真的落地）+ AI 不覆盖人工（回灌冲突开线程）+ 人工块保护入口 acollect_human_block_ids / arestore_human_blocks 供 114-03 接线（CLAR-02, CLAR-03）
- [x] 114-03-PLAN.md — ai_review stage 接入（**wave 4**）：入口先接线三件（aapply_thread_answers 消费答案产新版本 / arestore_human_blocks 保护人工块冲突开线程 / areanchor_threads 重锚）再跑判定；BlueprintReviewAdapter（findings 批量建线程用 severity 形参与 append_note 留痕、(rule_id, block_id) 去重、有界回退归因仓级回 repo_plan/融合级回 merge ≤2 轮计数存 stage_state["ai_review"]、超界转 pending_review 携未决清单绝不 FAILED）+ builtin_processes 只加第 10 个 stage 与 _h_bp_ai_review 且 merge.merged 改指 ai_review + blueprint_resume 映射表追加一行（删除行 0）；blueprint_merge.py 零改动（FLOW-07）
- [x] 114-05-PLAN.md — 人审端点与收口（**wave 5**）：新建 blueprint_review_views.py 七端点（GET 快照 / approve 经事务内守卫无 TOCTOU / reject 三步链写 meta.revision_round 首个写入方 / edit-blocks / threads answer 是 record_answer 唯一正当用法且同请求内接回灌 / threads resolve + dismiss 为 finding 处置通道解超界死锁）+ reviewer upsert + 澄清超时提醒挂既有 apscheduler 一个 job（判据 needs_clarification + BlueprintThread.last_reminded_at 保周期不重复轰炸，全相位唯一一条 migration）+ blueprint_quality 三项 DB 统计实装（human_edit_volume 用 produced_by_ref__startswith 而非不存在的 created_by_user_id）+ 全量相位门（FLOW-07, CLAR-03, CLAR-04）

### Phase 115: 前端查看器与知识库（结构化阅读 + 批注 + 管理面）

**Goal**: 蓝图对人可读、可审、可管理——结构化查看器（六段导航/批注层/版本 diff/阶段时间线）、二级引用预览、知识库技术方案 tab、项目关联展示、人审终审操作全部可用。
**Depends on**: Phase 114（有完整状态机与线程数据可展示）
**Requirements**: VIEW-01, VIEW-02, VIEW-03, VIEW-04, CLAR-01, FLOW-08
**Success Criteria** (what must be TRUE):

  1. 打开蓝图看到六段结构化渲染（交互流程 mermaid/伪代码块/API 契约卡/影响矩阵/仓库关联卡）+ 11 态状态徽标 + 阶段时间线；生成中各段展示实时进展（复用 ConvergenceSessionEvent，不新建推送通道）。
  2. AI 划线提问以飞书式下划线高亮呈现，点击展开线程侧栏可多轮回复；用户可对任意选区发起评论；版本切换 + block 级 diff 视图可用。
  3. 引用 chip 点击在查看器上再弹一层预览（知识实体 / **代码位置：文件路径 + 行号区间 + 引用快照** / 其他蓝图 / 章程条目）；仓库关联卡可直接跳转仓库页。
  4. 知识库「技术方案」tab 支持状态/项目/仓库筛选与搜索、深链直达查看器；项目内生成的蓝图自动挂项目并在项目物料面板可见；蓝图引用的知识/仓库/其它蓝图可查（**反向「被谁引用」随 Phase 116 知识图谱物化交付**）。
  5. 人审终审在查看器内完成：通过（评审人署名、状态到已确认）或驳回（带划线评论回产出中、修订轮次 +1）。

**Plans**: 7 plans（wave 1: 01；wave 2: 02；wave 3: 03/04 并行；wave 4: 05；wave 5: 06；wave 6: 07）

Plans:

- [x] 115-01-PLAN.md — 后端五个只读/轻写端点：蓝图正文（含 quality 三态，闭 MN-05）/ 阶段事件（21 个 BLUEPRINT_EVENTS，无会话回 200 空结构）/ 线程详情 GET（补 options + last_reminded_at + messages）与选区评论 POST（经新 service 收口，INV-6）/ 蓝图列表（ProjectMember 可见集合 + 方案 A 先聚合再切片 + 响应键 current_status 避开 INV-6 守卫 + 五键分页）；五端点照挂 _aassert_project_scope（import 复用，blueprint_review_views.py 零改动）（VIEW-01/03/04, CLAR-01）
- [x] 115-02-PLAN.md — 前端数据层与纯函数地基：happy-dom 能力锁探针 settle A2 + types/api×2/config 12 态/annotationTokens/StatusBadge + utils 两件（blockText 四分支同源 P-13、iterBlocks 13 处 collect、canonical 指纹、区间切分、两段式 offset）+ stores + 三个 composable（唯一轮询消费点 useBlueprintLive：snapshot 走函数式 refetchInterval 读自身 data，doc/events 走 isLive 并**必须配 watch(isLive) 的 refetch 踢动**——函数体读外部 ref 不是被追踪的响应式依赖，缺了它章节进度会静默冻结；配 useBlueprintLive.spec.ts 的 1→2 时序用例）+ 三处纯追加点一次做完（i18n 全量子树 / safelist 12 图标 / api barrel）+ 前端源码扫描守卫 spec（VIEW-01/02/03/04, CLAR-01, FLOW-08）
- [x] 115-03-PLAN.md — 块渲染与批注可视层 + 引用二级预览：BlueprintBlock（五类块分发 + <mark> 字符区间 + 越界/table/mermaid 整块降级 + orphaned 正文不渲染 + citation chip，批注与引用的唯一实现点）/ BlueprintBlockList（段级三分支 + 选区侦测唯一落点，同块与跨块分流）/ CitationPreviewDialog + 五个子件（任何失败一律快照兜底且不关弹窗；chunk-at 判据用 usable）；⭐ **代码预览为降级形态（文件路径 + 行号区间 + 引用快照，无源码正文因而无行高亮），源码正文读面顺延 116** —— chunk_lookup 只 select chunk_id/file_path/line_start/line_end/chunk_index，chunk_at_views 返 {path,line,chunks} 不带正文，唯一带 content 的读面是需要 query 的向量搜索，无法按 path+行号区间取，故 SC-3 已同步收窄（VIEW-01/02, CLAR-01）
- [x] 115-04-PLAN.md — 线程侧栏与写路径 + 人审终审 + 版本 diff：四组分组（一律走 sidebarGroups，失锚不二次过滤）+ ⭐ kind 硬分流做在渲染层（finding 卡里根本没有 Composer 节点）+ readonly 是不存在于 DOM 而 finding 处置不受其约束 + 终审 disabled+Tooltip 与二次确认 + ⭐ approve 409 的 unresolved_blocker_thread_ids 逐条可点跳转 + 质量面板三态绝不显示 0 + 版本切换与 block 级 diff（canonical 分类 + diffWords + .diff-* 复制进 scoped）（CLAR-01, FLOW-08, VIEW-01）
- [x] 115-05-PLAN.md — 十段正文组件（九个 section + 四张卡）：段组件零批注实现一律透传 blockCtx；must_haves 与 decision_log/deferred_ideas 两个特例段不接批注层且组件内写明原因；availability 只从 data_source 读不回落顶层；仓库关联卡直跳仓库页（SC-3）与 unsuitable 替代建议原样展示；⭐ associations 段范围收窄为「本蓝图引用了 + 关联项目」，**反向「被谁引用」顺延 116 知识图谱物化**（knowledge/artifact_associations.py 查的是 initiatives.Artifact 投影的 KnowledgeEntity，拿 delivery.Artifact.id 必然落空，SC-4 已同步收窄）（VIEW-01/02/04）
- [x] 115-06-PLAN.md — 查看器路由页装配 + 知识库 tab + 项目物料卡：⭐ 十段 <section id> 无条件渲染且 sections 恒 10 项、badge 传 '' 不传 0（P-4/P-18，否则左栏高亮全程失效而看起来只是迟钝）+ AnchorNavLayout 页面直接使用与三栏装配 + 六 query 双向同步与一次性消费 + 404 单一中性文案 + gate 非 200 不进错误分档 + 六个动作端点接线（零乐观更新、409 blocked 开解药面板、reflow 五档不当失败）+ 两处纯追加点（tab 宿主 / 物料面板）+ 全相位前端门（VIEW-01/02/03/04, CLAR-01, FLOW-08）
- [x] 115-07-PLAN.md — 确认门面板（⭐ 相对 ROADMAP SC 的范围增量，本相位最后一个可独立顺延 plan，顺延目标 116 且不得丢弃）：消费 112 的 blueprint-gate/ 快照与七动作，渲染条件只有「200 与否」一条（该链八端点里七个无项目范围闸 ⇒ 状态码不携带权限信息，三种 404 行为必须一致）+ 一次 POST + 双 invalidate + pending 行禁用 + confirm 409 的 pending_clarification 一键跳未决线程 + ⭐ 可顺延性实跑验证（回退后前端四道门仍全绿）+ 相位级收口自检（VIEW-01；同时闭 FLOW-03 的界面可达性）

**UI hint**: yes

### Phase 116: 入口收编与导出（全入口统一 + MCP 协议 + 飞书导出 + 图谱物化）

**Goal**: 全入口统一走蓝图编排、MCP 支持异步澄清、飞书导出升级、引用物化进知识图谱——蓝图成为技术方案的唯一产出形态。
**Depends on**: Phase 115（人审终审是入口收编的前置能力）。**硬依赖同步点 2**（v0.19.0 Phase 109/110 合并：execution 投影与事件时间线契约就位后，才做 TechPlanCard/工作流节点触点升级与默认入口切换）
**Requirements**: GATE-01, VIEW-05（并闭合 115 顺延的 VIEW-04、VIEW-02）
**Success Criteria** (what must be TRUE):

  1. workflow `ai_plan_research` 节点、chat `start_plan_research`、MCP `create_feishu_technical_plan`、feature list 链路**全部具备走 `technical_blueprint` process 的可执行路径**（蓝图 intake 与功能点拆分接线完成、所有续驱点按 `process_type` 选 adapter），并由 per-entry 运行时开关控制；开关默认仍为 `technical_plan`。**本相位已交付旧链残余流量的可观测性**（`technical_plan_entry_used` 按 `entry_key` 分桶 + process 注册表退役注记），**默认切换与旧 process 退役收口顺延同步点 2 后的收尾 plan**（其时为改一个设置默认值 + 三处触点升级 + workflow 节点终态映射改 HITL 挂起）。
  2. MCP 入口不再 skip_clarification：立即返回会话与 pending 状态，澄清经新工具可作答、结果可续取；澄清同时推飞书卡片，交互密度按 assumptions 档位可配。
  3. 导出飞书文档包含六段全量 + 决策记录附录；未确认版本在界面与导出物上均带「未经确认」显式标注（对齐 RELY-01 语义）。
  4. 蓝图 citations 物化为知识图谱 REFERENCES 边、项目关联物化为 RELATES_TO 边；知识库反查「本蓝图被哪些方案/知识引用」可用。

**Plans**: 7 plans（wave 1: 01；wave 2: 02；wave 3: 03/04；wave 4: 05；wave 5: 06；wave 6: 07）

Plans:

- [x] 116-01-PLAN.md — 分派地基与既有写面补闸：build_engine_for_session 按 process_type 同时换 engine **与 driver**（旧 driver 的 ahas_pending 短路对蓝图恒 False，只换 engine 仍会被推到 advance_step_limit）+ 两个同名 dep（research/merge）的类型身份自检挡住 ArchitectMergeAdapter 往蓝图落 v0 content + resume.py 对称守卫 + per-entry 开关 blueprint_entry_switch（⭐ 实参必须是 ast.Constant，MCP 的 entrypoint 实测是 "workflow"）+ 两个 SettingKeys + 旧链退役观察按独立 entry_key 分桶 + blueprint-gate/ 八端点补范围闸（更严变体：两个失败分支同一中性 404）与 confirm 两处 409 补 blocked_reason（GATE-01）
- [x] 116-02-PLAN.md — 蓝图 intake（SC-1 主体，全仓此前零实现）：blueprint_intake.py 的 11 键最小骨架（⭐ 显式带 schema_version，缺它会让校验器/renderer/入图门控三条链同时静默降级）+ requirement_spec.goal 承载需求原文 + aresolve_project_id 四链唯一收口（⭐ MCP 的 context.space 是 Space FK，必须过 _aresolve_project）+ 推不出即拒绝发起且 DB 零副作用 + start_blueprint_orchestration 纯追加 + _h_bp_intake/_h_bp_decompose 落实（⭐ StageOutcome 必须显式带 current_artifact_version，否则卡死 spec_gate）+ feature_segments 直采零 LLM（GATE-01）
- [x] 116-03-PLAN.md — 四入口的蓝图可执行路径：六个续驱点全改 build_engine_for_session（含 CONTEXT 未点名但实测为真的 answer_resume:102-103 与 plan_clarify_callback:242，漏改即作答后无人续驱且零异常）+ 四入口按字面量查开关与 project_id 推导 + ⭐ chat 三条断链（等澄清的健康会话不再被报成「方案编排失败」/ 两个蓝图 barrier 补 CHAT 回灌，否则对话永远停在「容器运行中」）+ ast 扫描把「漏改一处」变成机器可逮（GATE-01）
- [x] 116-04-PLAN.md — SC-4 图谱物化与反查：⭐ 第一个 task 是打通 relations 三层（_DEFAULT_RELATIONS 不含 REFERENCES 且中间两层不透传 ⇒ 边全对、端点 200、页面空白）+ knowledge/sources/blueprint.py normalizer（目标实体存在性预过滤 + 丢弃计数 sampling / 同目标 citation 聚合成一条边 / RELATES_TO 恰好 1 条 / ⛔ 去掉会变成谎言的 first_seen_version_no）+ 门控挂 create 与 add_version 两处（v1 骨架走 create，只挂后者会让新建蓝图查不到）+ knowledge_entity_id 换算键 + 前端补两块且 getArtifactAssociations 的零调用断言原样保留（VIEW-04）
- [x] 116-05-PLAN.md — SC-3 渲染器与飞书导出：render_blueprint_markdown(content, *, blueprint_status) 三条不变量（必填 keyword-only + 闭合白名单让任何取值都关不掉标注 + ⛔ 零布尔开关，唯一可机器验的形式是 inspect.signature 断言）+ builtin_types 判别分支与 ArtifactTimelineSerializer 蓝图特判（⭐ 两个面都带标注，顺带修掉 current_version_markdown 的结构性空壳）+ 两个导出端点（availability 三判据 / 上游失败 400·502 中性 detail / ⭐ 留痕落 Interaction Ledger，导出前后 ArtifactVersion 计数不变且不进 BLUEPRINT_EVENTS）+ 前端常驻不可关闭横幅与按 availability 隐藏的导出按钮（VIEW-05）
- [x] 116-06-PLAN.md — SC-2 MCP 异步澄清协议：blueprint_answer_action 抽取（MCP ⛔ 不直写线程 ⛔ 不自调 REST ⇒ 只剩共享 service 一条路；三道闸顺序有源码断言，finding 作答 400 且线程一字未变）+ 两个新工具（寻址键 artifact_id、⛔ 无第三个 list 工具、markdown 走 116-05 renderer）+ create_feishu_technical_plan 追加三键与 status=partial 且同步进 snapshot + ⭐ assumptions 三档（max_rounds 是真实新增且以 DEFAULT_SPEC_GATE_CONFIG 为唯一来源，三处调用点都要带档位否则 ambiguity_report 与 sampling 日志撒谎；assume_more ≠ skip_clarification 有正反并列）+ blueprint_notify 一个文件收敛澄清送达（GATE-01）
- [x] 116-07-PLAN.md — 代码预览源码正文读面（⭐ 本相位最后一个可独立顺延的 plan，顺延须同步改写 REQUIREMENTS VIEW-02 的顺延目标；**顺延时由 116-06 的相位出口检查兜底**）：先把 GetRepositoryFileView 的排除判定/镜像读取/分支解析/chunk 回退下沉成 services/repo_file_read.py（⛔ 复制一份违反 fail-closed 单一实现纪律，需回归 TOOL_SCHEMA_SNAPSHOT）+ 新增 file-lines 端点取 chunk_at 的中性口径（被排除/不存在/无镜像三者响应体逐字相同的 200 空，⛔ 不取 MCP 的 404 file_excluded）+ 区间超上界截断而非报错 + 前端引用预览升级为带正文与行高亮 + ⭐ 可独立顺延性实跑验证（VIEW-02）

**UI hint**: yes

### 🟡 v0.19.0 技术方案可信度 (Phases 105–110) — PLANNING

**Milestone Goal:** 让技术方案链路真正跑通并可信——编排不再中途卡死被降级工具顶替，路由基于多维证据分层呈现并可解释，方案结构覆盖数据流编排 / 模块↔仓映射 / 新增改造对照 / 主动澄清，全过程对用户实时可见。

- [ ] **Phase 105: 编排解锁与评估标尺** - 置信度由分数 margin 确定性推导 + 分数可拆解落 trace + 幂等与快照回放 + golden set 回归门禁（RELY-04, ROUTE-07/08/09）
- [ ] **Phase 106: 多信号打分函数重构** - 消除尺寸偏置 + 元数据信号真正入分 + 活跃度连续化 + 权重外置不发版可调（ROUTE-03/04/05/06）
- [ ] **Phase 107: 分层呈现与链路韧性** - 本项目/全局两组呈现与跨组标注 + 降级可见 + 澄清必达有出口 + Stage 1 重试与延迟上界（ROUTE-01/02, RELY-02/03/05）
- [ ] **Phase 108: 方案深度** - 业务流程编排叙事 + 模块↔仓库映射 + 新增/改造对照 + 删除分周计划 + 主动澄清（DEPTH-01~05）
- [ ] **Phase 109: 双脊柱合流** - 编排产出直连"选仓→分支→确认编码"执行流 + 移除徒手创作路径 + 草稿显式标注（SPINE-01/02, RELY-01）
- [ ] **Phase 110: 过程可观测** - 编排事件桥接 chat SSE + 调研容器日志可见 + 前端阶段时间线（OBS-01/02/03）

**执行顺序（依赖链）:** 105 → 106 → 107 → 108 → 109 → 110，线性。105 是全里程碑枢纽——RELY-04 是解开死锁的最短路径（Stage 1 不可靠时置信度恒 low → `auto_selected` 恒 false → 编排卡死 → 降级工具顶替），同时解除 RELY-02/RELY-03 的压力，也是 ROUTE 组能被正确评估的前提；ROUTE-08 的 golden set 是回归门禁而非优化目标（research §7.2：10–50 条只能检出大幅退化），不先建则后面每一步排序改动都是盲改。106 的 ROUTE-03 是路由误选的直接机制（现行 `max_score×(1+0.1×min(hits-1,5))` 结构性偏袒大单体），research 给了可直接落地的替代公式与数值验算，风险低收益高故紧随其后。107 的分组呈现要求两组分数可比（同一打分函数、无 group-conditional 项），必须等 106 定版。108 DEPTH 的价值依赖 RELY 组先成立——编排若仍卡死，方案提示词改得再好也一次都用不上。109 内部 SPINE-01 严格先于 SPINE-02（必须先有编排产出直连执行流的替代路径，才能安全砍掉唯一的编码入口）。110 OBS 相对独立放最后，但须复用 107 已落的事件源，不重复建设。

**实测前置分布（research §9 的 6 个开放项，不得留到实现中途才发现）:** O-1 全仓能力树节点数 `N_r` 分布 + O-3 Stage 0 是否可取 dense 余弦 + O-4 golden set 跨组样本 → **Phase 105**；O-2 embedding 余弦校准 + O-5 `last_commit_at` 覆盖率 → **Phase 106**；O-6 Stage 1 延迟压降 → **Phase 107**。

**UI 触面:** Phase 107（分组结果与 trust 标注呈现）、Phase 109（TechPlanCard 与选仓/分支执行流）、Phase 110（阶段时间线 + 流式进展）。

#### Phase Details (v0.19.0)

### Phase 105: 编排解锁与评估标尺（确定性置信度 + 分数可拆解 + golden set 门禁）

**Goal**: 技术方案编排不再因 Stage 1 失联而永久停摆，且此后每一次排序改动都能被客观判定为改进还是退化——置信度由分数 margin 确定性推导，分数可拆解、可复现、可离线回放，golden set 作为 CI 回归门禁就位。
**Depends on**: Nothing（本里程碑首个 phase。仓库去重与 Space 归属治理已于立项前完成；Stage 1 超时外置已单独修复 `1c9ebdff`）
**Requirements**: RELY-04, ROUTE-07, ROUTE-08, ROUTE-09
**Success Criteria** (what must be TRUE):

  1. Stage 1 完全不可用时（网关 400 / 连接错误 / 超时三种情形），用户发起的方案编排仍能拿到 high / medium / low 分级并自动推进到下一阶段，不再恒 low、不再无差别触发强制确认；LLM 的 confidence 只能把边界情况降级，不能把 low 升为 high。
  2. 用户在路由结果里展开任一候选仓，能看到每个信号的贡献值且各项之和恰等于总分；不存在把多个高分候选压平到同一分的截断（现行 `min(score, 1.0)` 销毁排序信息的行为消失）。
  3. 同一需求 + 同一索引状态重复路由两次，得到完全相同的候选顺序与分数（Stage 1 可用与不可用两种情形都成立）；从 `ConvergenceSessionEvent` 快照可离线回放出同一结果且全程零网络调用。
  4. golden set 建成并接入 CI 门禁：含「高三提分专项」首条真实用例与至少 2–3 条「正确答案在跨组」的样本，全量跑完 < 5s；Recall@5 低于基线、Top-1 正确数低于基线−1 或误自动选中率 > 10% 时门禁失败，并输出逐例 diff（哪几条变好、哪几条变坏、变坏那条的分数分解如何变化）。
  5. Phase 106 的公式定版输入已实测落文档：全仓能力树节点数 `N_r` 分布直方图（p50/p90/p99/max，用于定 `N̄` 与 `b`，O-1）+ Stage 0 返回结构中 dense 余弦是否可得（决定 MaxP 主干用余弦还是 RRF 分，O-3）。

**Plans**: 7 plans

Plans:

- [ ] 105-01-PLAN.md — 纯函数打分核心（加性分解/margin 置信度/只降不升）+ 阈值外置 + 不变量测试（wave 1）
- [ ] 105-02-PLAN.md — O-1/O-3 实测 command（measure_repo_index_stats）+ 105-MEASUREMENTS.md（wave 1）
- [ ] 105-03-PLAN.md — RepoRouterV2 接线：去截断/breakdown/degraded/确定性 auto_selected + 三种失联测试 + clarify policy 回归（wave 2）
- [ ] 105-04-PLAN.md — golden set fixture + 离线评估 harness + CI 门禁进默认 suite（wave 2）
- [ ] 105-05-PLAN.md — Stage 1 幂等三件套：输入哈希缓存 + 排列输出 + decode 固定 + call_source（wave 3）
- [ ] 105-06-PLAN.md — 前端最小展开：breakdown 透传 + RoutingDecisionPanel 分数分解 + confidence Tooltip（wave 3）
- [ ] 105-07-PLAN.md — 快照落 ConvergenceSessionEvent + 离线 replay 零网络同结果（wave 4）

**UI hint**: yes

### Phase 106: 多信号打分函数重构（尺寸偏置 + 元数据入分 + 活跃度连续 + 权重外置）

**Goal**: 路由排序由一个可拆解、无结构性偏袒、不发版可调的多信号打分函数决定——大而全的单体不再因命中节点多而被系统性高估，业务域 / 技术栈 / 团队 / 关键程度 / 活跃度从"算了给 LLM 看"变成真正参与打分。
**Depends on**: Phase 105（无回归门禁与分数分解则公式改动是盲改；`N_r` 分布与余弦口径是公式定版的直接输入）
**Requirements**: ROUTE-03, ROUTE-04, ROUTE-05, ROUTE-06
**Success Criteria** (what must be TRUE):

  1. 「高三提分专项」用例中前端候选 `onion-learning` 排在 `study-app` 之前、后端 `study-course` 与 `study-user-status` 进入 Top-5；断言锁定的是机制（`study-app` 的广度加成不高于 `onion-learning`）而非某组权重下的偶然名次；golden set 门禁通过（Recall@5 不低于基线、误自动选中率 ≤ 10%）。
  2. 需求文本提到业务域 / 技术栈 / 团队时，对应元数据匹配对最终分数产生可见且可拆解的贡献；仓库该项元数据缺失时该信号被剔除并重归一化，元数据填得不全的仓不因此被系统性压低（"未知"不等于"确认不匹配"）。
  3. 半年 / 一年 / 两年未提交的仓库，其活跃度得分呈连续递减而非只有「疑似废弃」一档生效；废弃惩罚完全落在活跃度项内并可单独展示，不再以乘性系数污染总分。
  4. 运维在系统设置里调整任一权重或常数并保存后，下一次路由立即按新值打分且无需发版；每条路由结果记录其所用的权重版本，跨版本结果不被混作同一口径比较。
  5. 实测前置完成并写入配置说明：embedding 在中文短需求 × facet 值上的余弦校准区间（区分度不足 0.10 的 facet 放弃该通道，O-2）+ `last_commit_at` 的全仓覆盖率与新鲜度（覆盖不足的仓退回枚举映射，O-5）。

**Plans**: TBD

### Phase 107: 分层呈现与链路韧性（分组/跨组标注 + 降级可见 + 澄清必达 + Stage 1 有界）

**Goal**: 用户看到的路由结果分组可信、降级有明确标注，编排在澄清环节与上游抖动下不再无声卡死。
**Depends on**: Phase 106（两组分数可比的前提是同一套打分函数、无任何 group-conditional 偏移）；Phase 105（RELY-04 解除"置信度恒 low"后，强制确认才不再无差别触发，澄清回路的真实缺陷才暴露得出来）
**Requirements**: ROUTE-01, ROUTE-02, RELY-02, RELY-03, RELY-05
**Success Criteria** (what must be TRUE):

  1. 路由结果分「本项目关联仓」与「全局候选」两组呈现、各组内按同一套分数排序，用户能一眼看出哪些是本平台内的；跨组候选带「未关联当前平台，可能涉及跨组协作」标注，用户据此判断是否要拉其他团队。
  2. 全局组首位显著优于本项目组首位（超过迟滞阈值）时该组被置顶并显式提示「更匹配的仓不在本项目关联范围内」；分数上不存在任何"本项目 +boost"的暗补偿（组别只进呈现与 trust 字段，绝不进分数）。
  3. 路由走降级路径（Stage 1 不可用 / `v2_stage0_only`）时，用户能看到「本次未经 LLM 推理，置信度仅供参考」的明确提示，而不是拿到一份看不出问题的结果。
  4. 编排进入澄清后，澄清一定送达用户且可作答；无人应答时有明确超时出口（继续推进或如实失败并说明原因），会话不会再永久停在 `waiting_clarification`。
  5. Stage 1 单次调用有重试与延迟上界，超出即降级继续，用户不会无限等待；O-6 的延迟压降结论（实测 34–71s 能否压到可接受）已落文档，若压不下来则缓存与快照回放作为主要收益来源已体现在设计中。

**Plans**: TBD
**UI hint**: yes

### Phase 108: 方案深度（业务编排叙事 + 模块↔仓映射 + 新增/改造对照 + 主动澄清）

**Goal**: 编排产出的技术方案覆盖数据产出与流转、业务流程编排叙事、功能↔模块↔仓库映射、新增/改造逐项对照，并在需求含糊时主动抛出带选项的澄清，而不是带着模糊假设直接出方案。
**Depends on**: Phase 107（编排能稳定跑完并拿到可信路由结果，方案提示词与 schema 的改动才会被真实用到；编排仍卡死时改提示词一次都用不上）
**Requirements**: DEPTH-01, DEPTH-02, DEPTH-03, DEPTH-04, DEPTH-05
**Success Criteria** (what must be TRUE):

  1. 用户拿到的方案能读到完整的业务流程叙事与数据流向：在哪个页面、经哪个接口、传什么参数、拿到什么数据、数据流向哪里、用户有哪几条行为路径。
  2. 方案给出功能 ↔ 模块 ↔ 仓库的映射关系，用户据此能判断每个仓具体要改什么。
  3. 方案逐项标注「新增」还是「改造」；改造项写明与既有功能如何配合、影响哪些已交付能力。
  4. 方案中不再出现以周为单位的分阶段实施计划（自由文本产出的分周计划消失，非模板产物不再泄漏到正文）。
  5. 需求存在影响方案质量的不确定点时（含 research 阶段已产出却无人消费的 `unclear_features`），系统在第二轮主动抛出澄清并给出候选选项，用户作答后方案据此收敛。

**Plans**: TBD

### Phase 109: 双脊柱合流（编排产出直连执行流 + 移除徒手创作路径）

**Goal**: 编排产出的技术方案可直接进入"选目标仓 → 配置分支 → 确认编码 → 飞书导出"的执行流，系统不再存在由对话模型徒手编写方案正文的产出路径，用户拿到的方案一定来自完整编排链路。
**Depends on**: Phase 108（先有够深的编排方案，替代徒手创作才不降质）。**Phase 内部顺序硬约束**：SPINE-01 必须先于 SPINE-02——必须先有编排产出直连执行流的替代路径，才能安全砍掉当前 SPA 唯一的编码入口。
**Requirements**: SPINE-01, SPINE-02, RELY-01
**Success Criteria** (what must be TRUE):

  1. 用户在编排产出方案后可直接进入选目标仓 → 配置分支 → 确认编码 → 飞书导出，全程无需重新走一遍方案生成。
  2. 系统不再存在「由对话模型徒手编写方案正文」的产出路径；`create_coding_plan` 的执行半边（选仓 / 分支 / 确认编码 / 导出）保持可用，SPA 与 MCP 两条编码链路零回归（MCP 执行链依赖其创建 chat `CodingPlan` 做桥接的行为不被破坏）。
  3. 用户拿到的技术方案一定来自完整编排链路；编排未完成时若仍提供草稿，草稿在界面与导出物上均显式标注「未经代码调研」，不会被误当作正式方案送去编码。
  4. 编排产出投影成执行侧对象的过程幂等：同一方案版本重复投影不产生重复的编码计划。

**Plans**: TBD
**UI hint**: yes

### Phase 110: 过程可观测（阶段流式 + 容器日志 + 阶段时间线）

**Goal**: 方案生成全过程对用户实时可见——阶段进展与阶段性内容边跑边出、调研容器日志可查、失败停在哪一步一目了然。
**Depends on**: Phase 109（编排链路已成为唯一方案来源，可观测面才覆盖真实产出路径）。与 Phase 107 有重叠面（都要把编排内部状态暴露给用户），必须复用同一事件源，不重复建设。
**Requirements**: OBS-01, OBS-02, OBS-03
**Success Criteria** (what must be TRUE):

  1. 用户发起方案生成后能实时看到阶段进展与阶段性内容（拆分 / 路由 / 召回 / 澄清 / 并行调研 / 融合），而不是长时间静默后一次性吐出结果。
  2. 方案调研阶段的容器执行日志对用户可见，体验与深度分析一致（不再被来源过滤挡在运行时快照之外）。
  3. 前端展示方案生成的阶段时间线；编排失败时用户能直接看出停在哪一步、原因是什么。
  4. 实时进展与 Phase 107 的降级提示复用同一事件源（`ConvergenceSessionEvent`），未新建平行推送通道，同一状态不存在两处各自实现。

**Plans**: TBD
**UI hint**: yes

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

**✅ 本分支当前立项：v0.20.0 技术方案蓝图（Phases 111–116，6 阶段 / 35 需求 SCHEMA·LIFE·CHARTER·FLOW·CLAR·BUS·VIEW·GATE）**——设计输入 [technical-blueprint/DESIGN.md](./technical-blueprint/DESIGN.md)，与 v0.19.0（`milestone/v0.19.0-plan-trust` worktree，v0.19.0 侧进度以该分支为准）并行开发。**六个相位全部完成且 verified（34/34 plans）**；里程碑审计判 `tech_debt`（34/35 需求满足，GATE-01 因硬依赖同步点 2 判 PARTIAL），详见 [v0.20.0-MILESTONE-AUDIT.md](./v0.20.0-MILESTONE-AUDIT.md)。**待与 v0.19.0 合并后 `$gsd-complete-milestone`**。

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 111. 蓝图底座 | v0.20.0 | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | 4/4 | ✅ Complete (passed 24/24) | 2026-07-30 |
| 112. 规格门与双面路由调研 | v0.20.0 | FLOW-01/02/03/04, CHARTER-02/03 | 5/5 | ✅ Complete (16/17 + gap closed) | 2026-07-30 |
| 113. 分仓方案与融合 + Context Bus | v0.20.0 | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | 6/6 | ✅ Complete (passed 54/54) | 2026-07-30 |
| 114. 审查与澄清收敛 | v0.20.0 | FLOW-07, CLAR-02/03/04 | 5/5 | ✅ Complete (passed 83/83) | 2026-07-31 |
| 115. 前端查看器与知识库 | v0.20.0 | VIEW-01/02/03/04, CLAR-01, FLOW-08 | 7/7 | ✅ Complete (passed 107/107) | 2026-08-01 |
| 116. 入口收编与导出 | v0.20.0 | GATE-01, VIEW-05（+ 闭合 VIEW-04、VIEW-02） | 7/7 | ✅ Complete (passed 121/121) | 2026-08-01 |

**Coverage (v0.20.0):** 35/35 需求全部映射，无孤儿、无重复（DEPTH-01~05 自 v0.19.0 Phase 108 迁入，映射见 REQUIREMENTS.md）。

里程碑 v0.1.0–v0.17.0（Phases 1–104）均已交付。**🟡 当前立项：v0.19.0 技术方案可信度（Phases 105–110，6 阶段 / 24 需求 RELY·ROUTE·DEPTH·SPINE·OBS）**——源于一次生产实例的实证排查：用户拿到的技术方案根本不是技术方案流水线产出的，两个 `ConvergenceSession` 都停在 `clarify/waiting_clarification`，agent 等不到就绕道 `create_coding_plan` 徒手编了一份。根因链已实测定位（haiku 档误配 → 网关 400 → Stage 1 静默降级 → 置信度恒 low → `auto_selected` 恒 false → 强制确认无差别触发 → 编排卡死 → 降级工具顶替）。规划与调研已就绪（REQUIREMENTS 24 条 + [research/ROUTING-RANKING.md](./research/ROUTING-RANKING.md)），**待 `$gsd-plan-phase 105`**。

| Phase | Milestone | Requirements | Plans Complete | Status | Completed |
|-------|-----------|--------------|----------------|--------|-----------|
| 105. 编排解锁与评估标尺 | v0.19.0 | RELY-04, ROUTE-07/08/09 | 0/TBD | Not started | - |
| 106. 多信号打分函数重构 | v0.19.0 | ROUTE-03/04/05/06 | 0/TBD | Not started | - |
| 107. 分层呈现与链路韧性 | v0.19.0 | ROUTE-01/02, RELY-02/03/05 | 0/TBD | Not started | - |
| 108. 方案深度 | v0.19.0 | DEPTH-01~05 | 0/TBD | Not started | - |
| 109. 双脊柱合流 | v0.19.0 | SPINE-01/02, RELY-01 | 0/TBD | Not started | - |
| 110. 过程可观测 | v0.19.0 | OBS-01/02/03 | 0/TBD | Not started | - |

**Coverage (v0.19.0):** 24/24 需求全部映射，无孤儿、无重复。

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

v0.17.0 遗留的真实 Qdrant·飞书·容器·Cursor 端人工验证（11 项）见 [audit](./milestones/v0.17.0-MILESTONE-AUDIT.md)；v0.16.3 遗留真机·真实 provider·浏览器视觉验收见 [audit](./milestones/v0.16.3-MILESTONE-AUDIT.md)；v0.16.1 遗留人工验收（10 项）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) §4。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
