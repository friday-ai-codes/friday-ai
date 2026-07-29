# Roadmap: Friday AI

## Milestones

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
**Wave 1**

- [x] 105-01-PLAN.md — 纯函数打分核心（加性分解/margin 置信度/只降不升）+ 阈值外置 + 不变量测试（wave 1）
- [x] 105-02-PLAN.md — O-1/O-3 实测 command（measure_repo_index_stats）+ 105-MEASUREMENTS.md（wave 1）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 105-03-PLAN.md — RepoRouterV2 接线：去截断/breakdown/degraded/确定性 auto_selected + 三种失联行为测试 + clarify policy 回归（wave 2）
- [x] 105-04-PLAN.md — golden set fixture + 离线评估 harness + CI 门禁进默认 suite（wave 2）

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 105-05-PLAN.md — Stage 1 幂等三件套：输入哈希缓存 + 排列输出 + decode 固定 + call_source（wave 3）
- [x] 105-06-PLAN.md — 前端最小展开：breakdown 透传 + RoutingDecisionPanel 分数分解 + confidence Tooltip（wave 3）

**Wave 4** *(blocked on Wave 3 completion)*

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
