# Roadmap: Friday AI

## Milestones

- ✅ **v0.25.0 Cursor / Claude Code 会话知识回写** — Phases 141–145 (completed 2026-08-31，未打 tag) — 审计 **tech_debt**（27/27 requirements 满足 / 5 phases / 25 plans / 0 critical gaps）；可选真实 IDE smoke 与 hook 双份实现等为非阻断技术债 — [archive](./milestones/v0.25.0-ROADMAP.md) · [requirements](./milestones/v0.25.0-REQUIREMENTS.md) · [audit](./milestones/v0.25.0-MILESTONE-AUDIT.md) · [phases](./milestones/v0.25.0-phases/)
- ✅ **v0.24.0 单仓图查询对齐 GitNexus** — Phases 133–140 (completed 2026-08-24，未打 tag) — 审计 **tech_debt**（39/39 requirements 满足 / 8 phases / 16 plans / 0 critical gaps）；真实 benchmark/Qdrant 数值验证保留为 `human_needed`，不宣称数值优于 v0.22.0
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

<details>
<summary>✅ v0.25.0 Cursor / Claude Code 会话知识回写（Phases 141–145）— SHIPPED 2026-08-31</summary>

- [x] **Phase 141: Capture 账本与仓库挂钩** — 原始问答先安全落账本（4/4，passed）
- [x] **Phase 142: MCP 会话回写契约** — `report_session_knowledge` 三面对齐（4/4，passed）
- [x] **Phase 143: 价值评估与中高入图** — durable eval + medium/high ingest（7/7，passed）
- [x] **Phase 144: 仓库召回与 Capture 回放** — 按仓/项目召回与只读回放（5/5，passed）
- [x] **Phase 145: Cursor / Claude Code 双宿主采集** — hooks 配对 + hooks.json merge（5/5，passed）

</details>

<details>
<summary>✅ v0.24.0 单仓图查询对齐 GitNexus（Phases 133–140）— SHIPPED 2026-08-24</summary>

- [x] **Phase 133–140** — 见 [milestones/v0.24.0-ROADMAP.md](./milestones/v0.24.0-ROADMAP.md)

</details>
