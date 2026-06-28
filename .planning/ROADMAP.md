# Roadmap: Friday AI

## Milestones

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

## Phases

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

里程碑 v0.1.0–v0.16.1（Phases 1–95）均已交付。**✅ v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）（Phases 90–95，6 阶段 / 27 plans / 18 v1 需求 UNIFY/CLARIFY/SLOT/DECOMP）已 shipped（2026-06-28，里程碑审计 tech_debt — 18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER，遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）**，完整阶段详情见 [milestones/v0.16.1-ROADMAP.md](./milestones/v0.16.1-ROADMAP.md)、审计见 [milestones/v0.16.1-MILESTONE-AUDIT.md](./milestones/v0.16.1-MILESTONE-AUDIT.md)。

**下一步：`$gsd-new-milestone` 启动下一里程碑（含 requirements 重新定义）。** v0.16.1 遗留的真机/真实 provider/画布视觉端到端人工验收（10 项）见 audit §4 与各 phase VERIFICATION「Deferred」段。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
