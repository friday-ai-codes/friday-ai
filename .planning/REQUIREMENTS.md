# Requirements: Friday AI — v0.23.0 仓库路由增强

**Defined:** 2026-08-14  
**Core Value:** 让团队开箱即用、安全地把需求自动变成代码——本里程碑让「需求→改哪个仓」这一步在 feature list 场景下可信、可解释、可门禁。

**Design inputs:** 分阶段决策漏斗（画像→团队→短名单→章程/历史→放置单元→门禁/反思）；既有 `BlueprintRouteAdapter` / `RepoAssociationService` / `RepoRouterV2`；评测语料「高三提分专项」。

## v1 Requirements

### 专项画像（PROF）

- [x] **PROF-01**: 系统能从 feature list（模块总览、全局流转、模块简述）生成可机读专项画像（产品形态、域、brownfield/greenfield/fix、主能力簇、显式非目标、复用声明摘要）
- [x] **PROF-02**: 画像主路径默认排除验收项/测试 case 正文；若仅有操作细节语料则触发澄清而非静默用噪声建画像
- [x] **PROF-03**: 画像结果写入路由 stage 可观测结构（可回放、可绑定 request/run id），失败 fail-soft 并带明确 degrade 原因

### 团队门禁（TEAM）

- [x] **TEAM-01**: 系统能解析需求的 `primary_team` / Space（项目挂载空间优先），产出 `team_core` 仓库集合
- [x] **TEAM-02**: `out_of_team` 仓库默认不可作为 primary；仅 `team_adjacent`（有复用/章程证据）可例外进入
- [x] **TEAM-03**: 无可用团队/空间或 `team_core` 为空（或全无索引）时，路由进入 `clarify`/`block`，不得静默退回全库裸路由

### 短名单与历史先验（LIST）

- [ ] **LIST-01**: 在 `team_core`（∪ 合法 adjacent）内，系统用活跃度 + 能力树粗相关（吃专项画像，非整点验收句）+ 章程 domain 命中生成 shortlist
- [ ] **LIST-02**: 章程规划中域（`evolution`/planned）的仓可在能力树分低时仍进入 shortlist（绕过 Stage0 节点天花板）
- [ ] **LIST-03**: 历史先验拆「需求史」（tech_plan 等）与「上线史」（document 上线记录 / code_change），与 `team_core` 求交后可强制拉入 shortlist
- [ ] **LIST-04**: shortlist 大小与排序可解释（逐仓信号 breakdown）；观测上报候选数/耗时，不回显需求原文

### 章程角色图（ROLE）

- [ ] **ROLE-01**: 对 shortlist 逐仓做章程对齐，产出主/辅/禁角色图（至少覆盖：App 壳、做题/复用宿主、课程配置、学习状态）
- [ ] **ROLE-02**: 触碰章程 `boundaries` 的落点候选被降级或剔除，除非带显式 override 理由
- [ ] **ROLE-03**: 角色图进入后续放置默认约束（例如状态域默认写方 ≠ 任意 UI 页壳主仓）

### 连贯性与放置单元（UNIT）

- [ ] **UNIT-01**: 系统将 feature 点聚合为放置单元（Placement Units），依据模块依赖与正文「复用 X」边，避免 43 点各自独立全库检索
- [ ] **UNIT-02**: 每个放置单元在 shortlist 内产出 `primary_repo` + `supporting_repos[]` + confidence + evidence + open_questions
- [ ] **UNIT-03**: 细排可调用 `RepoRouterV2`，但候选范围硬限制在 shortlist（或 shortlist ∪ 复用宿主），禁止再对全库开放 primary

### 门禁系统（GATE）

- [ ] **GATE-01**: 门禁统一输出 `pass | clarify | block` + `reason_codes[]` + evidence，贯穿路由阶段可观测
- [ ] **GATE-02**: 至少落地：团队门、短名单覆盖门、单元落点门、全局一致性门、发布门（P0 未确认不可下游开工）
- [ ] **GATE-03**: 全局一致性门拦截：出界 primary、同一状态域双写、页面壳散落多 App 仓、违背「复用不改造」类边界

### 反思环（REFL）

- [ ] **REFL-01**: 在证据冲突、角色坍塌、复用矛盾、覆盖空洞等触发条件下启动反思，最多 N 轮（默认 2），超限进入 `needs_human_review`
- [ ] **REFL-02**: 反思产出结构化补丁（矛盾、根因假设、回跳点、repair_actions），只重算受影响短名单/单元，禁止无界全库重跑
- [ ] **REFL-03**: 每轮反思写入 ledger/事件（脱敏），可回放

### 集成与验收（INT）

- [ ] **INT-01**: 蓝图路由 / 项目选仓主路径走决策漏斗（或等价编排），三分量加权可保留为漏斗内信号，不再作为唯一决策
- [ ] **INT-02**: 以「高三提分专项」feature list 为回归锚点：在学习工具 Space 下，四基线仓作为 primary 集合的覆盖达到约定门槛（文档化 hit@primary / 角色覆盖），且 `out_of_team` 仓不得成为 primary
- [ ] **INT-03**: 既有单测与 MCP/编排契约不回归；新增门禁/反思路径有自动化测试（含至少一条角色坍塌→反思修复的合成用例）

## v2 Requirements（本里程碑不排期）

- **PROF-F01**: 多模态/截图原型参与画像
- **TEAM-F01**: 跨 Space 多团队协商 UI 与自动分摊
- **LIST-F01**: 基于点击日志的 LTR 短名单重排
- **GATE-F01**: 可配置门禁策略包（strict/standard/soft）的运营后台
- **REFL-F01**: 多 Agent 对抗式反思（独立 critic 模型）

## Out of Scope

| Feature | Reason |
|---------|--------|
| 推倒重写 `RepoRouterV2` / 能力树索引管线 | 漏斗把 V2 降为细排工具即可；索引大修另立里程碑 |
| 全库 Learning-to-Rank / 点击日志训练 | 冷启动样本不足；与既有 ROUTING-RANKING 结论一致 |
| AI 自动生效改章程 | 章程原则：人工确认生效 |
| 大前端改版 / 全新路由控制台 | 小版本；clarify 面最小增量即可 |
| 把测试 case 当主召回语料 | 实测稀释语义、放大通用交互词 |
| 对每个验收项做一次全库 LLM 路由 | 成本高且与连贯性目标相反 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROF-01 | Phase 128 | Complete |
| PROF-02 | Phase 128 | Complete |
| PROF-03 | Phase 128 | Complete |
| TEAM-01 | Phase 128 | Complete |
| TEAM-02 | Phase 128 | Complete |
| TEAM-03 | Phase 128 | Complete |
| LIST-01 | Phase 129 | Pending |
| LIST-02 | Phase 129 | Pending |
| LIST-03 | Phase 129 | Pending |
| LIST-04 | Phase 129 | Pending |
| ROLE-01 | Phase 129 | Pending |
| ROLE-02 | Phase 129 | Pending |
| ROLE-03 | Phase 129 | Pending |
| UNIT-01 | Phase 130 | Pending |
| UNIT-02 | Phase 130 | Pending |
| UNIT-03 | Phase 130 | Pending |
| INT-01 | Phase 130 | Pending |
| GATE-01 | Phase 131 | Pending |
| GATE-02 | Phase 131 | Pending |
| GATE-03 | Phase 131 | Pending |
| REFL-01 | Phase 131 | Pending |
| REFL-02 | Phase 131 | Pending |
| REFL-03 | Phase 131 | Pending |
| INT-02 | Phase 132 | Pending |
| INT-03 | Phase 132 | Pending |

**Coverage:**

- v1 requirements: 25 total
- Mapped to phases: 25/25 ✓
- Unmapped: 0

| Phase | Requirements | Count |
|-------|--------------|-------|
| 128 | PROF-01~03, TEAM-01~03 | 6 |
| 129 | LIST-01~04, ROLE-01~03 | 7 |
| 130 | UNIT-01~03, INT-01 | 4 |
| 131 | GATE-01~03, REFL-01~03 | 6 |
| 132 | INT-02, INT-03 | 2 |

---
*Requirements defined: 2026-08-14*  
*Last updated: 2026-08-14 — roadmap Phases 128–132 mapped*
