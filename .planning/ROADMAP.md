# Roadmap: Friday AI

## Milestones

- 🚧 **v0.26.0 MCP 全链路开放与稳定性** — Phases 146–152 (planned) — 让外部 Agent 仅通过公开 MCP 稳定完成技术蓝图全链，并具备契约对齐、幂等恢复、安全诊断与真实发布证据
- ✅ **v0.25.0 Cursor / Claude Code 会话知识回写** — Phases 141–145 (completed 2026-08-31，未打 tag) — 审计 **tech_debt**（27/27 requirements 满足 / 5 phases / 25 plans / 0 critical gaps）；可选真实 IDE smoke 与 hook 双份实现等为非阻断技术债 — [archive](./milestones/v0.25.0-ROADMAP.md) · [requirements](./milestones/v0.25.0-REQUIREMENTS.md) · [audit](./milestones/v0.25.0-MILESTONE-AUDIT.md) · [phases](./milestones/v0.25.0-phases/)
- ✅ **v0.24.0 单仓图查询对齐 GitNexus** — Phases 133–140 (completed 2026-08-24，未打 tag) — 审计 **tech_debt**（39/39 requirements 满足 / 8 phases / 16 plans / 0 critical gaps）；真实 benchmark/Qdrant 数值验证保留为 `human_needed`，不宣称数值优于 v0.22.0
- ✅ **v0.23.0 仓库路由增强（分阶段决策漏斗）** — Phases 128–132 (completed 2026-08-14，未打 tag) — 把「全库单段文本相似度选仓」升级为「画像 → 团队门禁 → 短名单 → 章程/历史 → 放置单元 → 门禁/反思」的可解释决策漏斗；验收锚点「示例功能专项」 — 里程碑审计 **tech_debt**（25/25 需求满足 / 5 相位全 verified passed / 0 BLOCKER）见 [audit](./milestones/v0.23.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.23.0-ROADMAP.md) · [requirements](./milestones/v0.23.0-REQUIREMENTS.md) · [phases](./milestones/v0.23.0-phases/) · [decisions](./milestones/v0.23.0-DECISIONS.md) · [research](./research/ROUTING-RANKING.md)
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

### 🚧 v0.26.0 MCP 全链路开放与稳定性（Phases 146–152）

**Milestone Goal:** 让外部 Agent 仅通过公开 MCP 即可稳定完成技术蓝图全链，并能在长任务、HITL、回调丢失和跨版本发布场景下安全诊断与恢复。

- [ ] **Phase 146: 契约注册表与生成目录** — 消除服务端、HTTP、snapshot 与 npm stdio 的工具契约漂移
- [ ] **Phase 147: 共享服务与安全边界** — 让 REST 与 MCP 共用 canonical 查询、命令、授权和错误语义
- [ ] **Phase 148: Operation 与幂等控制面** — 提供秒级 accepted、作用域幂等和无副作用轮询
- [ ] **Phase 149: 全链状态、产物与诊断** — 让 Agent 只靠 MCP 判断阶段、等待原因、失败域和下一动作
- [ ] **Phase 150: 仓库确认与规格 HITL** — 公开完整仓库 gate 修改、CAS 确认和硬门禁
- [ ] **Phase 151: 分仓、融合、评审与交接控制** — 开放定向重试、finding 处置、终审返工与 confirmed handoff
- [ ] **Phase 152: 恢复、真实 Canary 与发布门禁** — 用真实 stdio/Qdrant/runner/飞书链验证恢复和发布完整性

## Phase Details

### Phase 146: 契约注册表与生成目录
**Goal**: 外部 Agent 在服务端、HTTP 与 npm stdio 任一公开面看到并调用完全一致、可验证且向后兼容的 MCP 工具契约。
**Depends on**: Phase 145（v0.25.0 已完成）
**Requirements**: PUB-01, PUB-02, PUB-03, PUB-04, PUB-05, PUB-06
**Success Criteria** (what must be TRUE):
  1. Agent 从 npm stdio `tools/list` 可发现并调用服务端全部 55 个现有工具，工具名、URL、输入/输出 schema 与 annotations 一致。
  2. 每个成功响应都有可按 `outputSchema` 校验的 `structuredContent`，失败可按稳定机器码处理而不解析中文文本。
  3. 契约生成 `--check` 在干净树无差异，且 CI 在 `mcp/` 缺失、删工具/字段、新增 required 或收窄 enum 时明确失败。
  4. Doctor 能准确报告 npm/client 与 server 的版本、manifest hash 和具体差异，且 `SERVER_VERSION` 与 `package.json` 一致。
**Plans**: 6 plans

Plans:
- [ ] 146-01-PLAN.md — 建立 canonical registry、完整 schema/manifest 与独立 compatibility baseline
- [ ] 146-02-PLAN.md — 生成 canonical JSON/snapshot/TS catalog，并提供严格只读 `--check`
- [ ] 146-03-PLAN.md — 切换 registry URL 与 npm 55-tool catalog，同时保留 handoff 工作
- [ ] 146-04-PLAN.md — 统一 outputSchema、structuredContent 与稳定机器错误
- [ ] 146-05-PLAN.md — 发布 manifest identity 并对齐 package version 与 doctor
- [ ] 146-06-PLAN.md — 接入 CI/publish 硬门与版本钉扎文档

### Phase 147: 共享服务与安全边界
**Goal**: REST 与 MCP 通过同一 canonical 应用服务安全读写蓝图，调用者无法伪造范围或从错误差异探测资源。
**Depends on**: Phase 146
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, SEC-05
**Success Criteria** (what must be TRUE):
  1. 同一蓝图动作经 REST 或 MCP 执行会得到相同 canonical 状态与机器错误，adapter 不形成第二套状态机。
  2. 项目范围只从 artifact/session/thread 关系推导；非成员与不存在资源返回同形 404，请求体自报归属不能越权。
  3. 新 MCP 入口具备可关联 actor 的 caller 生命周期、时长与 correlation IDs，后台续驱保留触发用户且观测故障不影响业务。
  4. 状态、错误、finding、澄清、产物摘要和 Ledger 均脱敏；工具 annotations 准确区分只读查询与高影响 mutation，且不泄露凭证、job ID 或堆栈。
**Plans**: TBD

### Phase 148: Operation 与幂等控制面
**Goal**: Agent 能安全发起长时蓝图任务，在断连、超时或重试后找回同一任务而不复制任何副作用。
**Depends on**: Phase 147
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04, OPS-05
**Success Criteria** (what must be TRUE):
  1. `start_technical_blueprint` 在秒级返回 operation/session/artifact 坐标、状态、轮询间隔和下一动作，不同步等待调研或融合。
  2. 相同 actor、project、tool、idempotency key 与负载的并发请求复用同一任务；同 key 异负载稳定返回 409。
  3. 请求超时或断开后，Agent 可用 operation 或原幂等键找回任务，且 session、artifact、容器与外部副作用均不重复。
  4. Operation 查询只投影 canonical 状态且轮询无副作用；mutation 响应能分别表达 `action_committed` 与 `drive_pending`。
**Plans**: TBD

### Phase 149: 全链状态、产物与诊断
**Goal**: Agent 无需访问内部数据库或日志，即可通过纯读 MCP 准确判断蓝图全链状态、证据完整性和合法下一动作。
**Depends on**: Phase 148
**Requirements**: STAT-01, STAT-02, STAT-03, STAT-04, STAT-05, STAT-06, STAT-07, GATE-01
**Success Criteria** (what must be TRUE):
  1. 总状态查询稳定返回 stage、进度、等待原因、不可变版本坐标、retry 信息和服务端权威 `next_actions`。
  2. Agent 可分别查看逐仓 research/repo-plan、每轮 merge、review findings、规格澄清和 orphaned threads，且看不到 CoT 或内部堆栈。
  3. 增量事件可用 `since_seq/max_seq/has_more` 无遗漏翻页，事件只含 allowlisted ID、计数、阶段与脱敏摘要。
  4. Runner callback 丢失、durable resume 异常或 lease 恢复时，诊断明确给出 `waiting_on/recovery_state/retryable` 与合法恢复动作。
  5. 关键读取失败返回结构化 retryable error；合法空结果明确携带 `completeness/empty_reason`，不会以 `200 + []` 伪装成功。
**Plans**: TBD

### Phase 150: 仓库确认与规格 HITL
**Goal**: Agent 能通过 MCP 完成规格澄清和仓库确认，同时任何陈旧或未确认决策都无法越过硬门进入执行。
**Depends on**: Phase 149
**Requirements**: GATE-02, GATE-03, GATE-04, GATE-05
**Success Criteria** (what must be TRUE):
  1. Agent 可读取含仓库、角色、职责、fitness、pending research、移除态、gate token 和 ready-to-lock 的完整 gate 快照。
  2. Agent 可逐仓 add、remove、reclassify、编辑职责和升级调研，并在每次动作后获得新 gate token 与下一动作。
  3. 使用陈旧 gate version/hash 确认会返回 409 且不锁定；使用最新坐标确认后，既有 resume 链异步进入 repo-plan。
  4. 未经过仓库确认或最终确认的蓝图，经任何 MCP、REST 或工作流路径尝试编码、推分支或创建 MR 时均为零副作用。
**Plans**: TBD

### Phase 151: 分仓、融合、评审与交接控制
**Goal**: Agent 能以最小失败域重试分仓与融合、完整处置评审并基于精确版本坐标完成终审或返工交接。
**Depends on**: Phase 150
**Requirements**: RPLAN-01, RPLAN-02, RPLAN-03, MERGE-01, MERGE-02, REVIEW-01, REVIEW-02, REVIEW-03, REVIEW-04, REVIEW-05, HAND-01, HAND-02
**Success Criteria** (what must be TRUE):
  1. Agent 可读取指定仓的 canonical repo plan 和 immutable merge 产物，并核验 attempt、版本/hash、引用、validation、coverage、gap 与未决 thread。
  2. 对单仓 failed/stale/degraded/empty 任务的 CAS 重试只增加目标仓 attempt；merge 重试使用精确旧坐标，陈旧请求 409 且不创建版本，历史产物均保留。
  3. Finding 只能通过 reason 必填的 resolve/dismiss 处置；终态重放 noop 且不覆盖首次留痕，澄清 answer 对 finding 稳定返回 `not_answerable`。
  4. Agent 可从 npm stdio 执行最终 approve 或按 `review/merge/repos/full` 退回；陈旧四坐标或未决 blocker 阻止 approve，返工只影响归一后的目标范围。
  5. Confirmed handoff 对 technical plan、artifact、version、content hash、confirmed 状态和非空 repository tasks 全部 fail-closed；成功时受限文件的 hash、任务数和 canonical 内容可复核且可清理。
**Plans**: TBD

### Phase 152: 恢复、真实 Canary 与发布门禁
**Goal**: 完整 MCP-only 蓝图链在真实依赖和故障注入下可恢复，并且只有携带可复核 live 证据的包才能发布。
**Depends on**: Phase 151
**Requirements**: SEC-06, LIVE-01, LIVE-02, LIVE-03, LIVE-04, LIVE-05, LIVE-06
**Success Criteria** (what must be TRUE):
  1. 多客户端按 `poll_after_ms`、限流与退避轮询时不会 busy-loop 冲击数据库或 worker，并能按权威动作恢复可重试任务。
  2. Canary 经待发布或已发布 npm stdio 的真实 `tools/call`，使用真实已索引 Qdrant 仓和 runner/container callback 完成路由、调研、分仓、融合与 review。
  3. 故意丢失一次 structured callback 后，reconciliation 能收敛且不重复任务、版本或外部副作用。
  4. Canary 完成一次真实或受控真实凭证的飞书 HITL，并验证最终 handoff 四坐标、文件 hash 与 repository task count 一致。
  5. 发布报告分列 synthetic 与 live 状态；`live_unrun` 阻止完整链声明，publish gate 同时验证 catalog、compatibility、版本/doctor、secret scan 和 npm 安装版本钉扎。
**Plans**: TBD

## v0.26.0 Cross-Cutting Exit Gates

以下门禁适用于 Phase 146–152 的每个相位；任一未满足均不得判定该相位完成：

- **Security**: canonical scope 推导、PAT owner 权限与同形 404 fail-closed；高影响 mutation 在 service 内重验状态和 CAS。
- **Observability**: caller `started/completed/failed`、`duration_ms`、`component`、actor/correlation IDs 齐全；高频内部步骤用 sampling；后台显式传播 `initiated_by_user_id`；观测 best-effort。
- **Redaction**: 日志、错误、上游异常、finding/clarification、handoff 摘要与 Ledger 按既有入口脱敏；日志只留 ID、计数、长度和 hash。
- **Compatibility**: 旧 URL、工具名与 required keys 不破坏；新增字段保持 additive；server 先兼容部署，npm 后发布。
- **Evidence**: 每项能力同时具备 service、HTTP adapter、stdio contract 测试；live 与 synthetic 证据分开，关键成功响应不得用空主载荷代替。

## v0.26.0 Progress

**Execution Order:** 146 → 147 → 148 → 149 → 150 → 151 → 152

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 146. 契约注册表与生成目录 | 0/6 | Planned | - |
| 147. 共享服务与安全边界 | 0/TBD | Not started | - |
| 148. Operation 与幂等控制面 | 0/TBD | Not started | - |
| 149. 全链状态、产物与诊断 | 0/TBD | Not started | - |
| 150. 仓库确认与规格 HITL | 0/TBD | Not started | - |
| 151. 分仓、融合、评审与交接控制 | 0/TBD | Not started | - |
| 152. 恢复、真实 Canary 与发布门禁 | 0/TBD | Not started | - |

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
