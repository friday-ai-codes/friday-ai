# Phase 132: 集成验收与高三提分回归 - Context

**Gathered:** 2026-08-14  
**Status:** Ready for planning  
**Mode:** Locked from v0.23.0-DECISIONS **D2** + orchestrator brief（INT-02 / INT-03）；灰区由 Claude's Discretion

<domain>
## Phase Boundary

本相位是 v0.23.0 漏斗里程碑的**集成验收收口**，在 Phase 128–131 全部 verified 之后交付：

1. **INT-02 回归锚点**：以「高三提分专项」feature list 为锚，在学习工具（Learning-tools）Space 语义下，按 **placement-unit 级**评测，使四基线仓各自至少一次作为某放置单元的 `primary`，且 `out_of_team` primary 计数为 **0**。评测路径必须是 **漏斗（含 charter/history）**，禁止裸跑 `RepoRouterV2`。
2. **INT-03 契约不回归**：既有单测与 MCP/编排契约不回归；门禁/反思路径有自动化测试，且至少一条 **角色坍塌 → 反思修复** 的合成用例（可在 131 钩子上扩到接线级）。

**不实现**：GATE-F01 策略后台、REFL-F01 多 Agent 对抗反思、路由大前端、章程自动生效、LTR 重排、43 功能点 top1 评测范式。**禁止重写** `RepoRouterV2`。

</domain>

<decisions>
## Implementation Decisions

### Locked product（v0.23.0-DECISIONS D2 + Defaults）
- **D-01（← D2 / INT-02）:** 验收粒度 = **placement-unit / module-level**，**不是** 43 feature-point top1。
- **D-02（← D2）:** 四基线仓必须各自至少一次作为某 placement unit 的 **primary**：
  - `frontend/onion-learning`
  - `frontend/onion-practice`（alias `onion-practice`）
  - `backend/study-course`（alias `study-course`）
  - `backend/study-user-status`
  Alias 与规范名在评分时等价归一（basename / 去前缀匹配均可，须单测锁定）。
- **D-03（← D2）:** 同用例下 `out_of_team` primary 计数必须为 **0**（硬失败）。
- **D-04（← D2）:** Eval path = Learning-tools Space + **决策漏斗**（team → shortlist ± history → role_map → placement → gates/reflection），**charter/history 启用**；**禁止**以裸 `RepoRouterV2.route` 作为验收主路径。
- **D-05（← Defaults）:** 不推倒 `RepoRouterV2`；无大前端；演进面停留在 Adapter / Association / process_runtime 漏斗与**评测 harness**。

### 语料与可重复性
- **D-06:** 优先 **确定性合成 fixtures**（模拟 Learning-tools Space 的 `team_core` / membership、四基线 + 若干 `out_of_team` 诱饵仓、压缩版高三 modules/features、role/charter/history 信号）。活 Space 不可用时，合成路径必须足以在 CI 断言 D-01~D-03。
- **D-07:** `.planning/quick/260809-repo-route-eval/` 与 `.planning/quick/260811-gaosan-route-5rounds/` 作为 **语料/对照参考**（分布、失败模式、仓名 alias），**不得**把旧「裸 V2 5 轮结果」当作漏斗通过标准；可选 `@pytest.mark.live_space` 脚本复用其项目/Space id 做手工/夜间评测，默认 CI skip。
- **D-08:** 文档化 hit@primary / 角色覆盖门槛：代码侧导出常量 + 短文（本相位 RESEARCH/PLAN 或 `gaosan_eval` 模块 docstring）写明「每基线 ≥1 unit primary」与「out_of_team_primary_count == 0」即为约定门槛（无额外百分比阈值，除非后续用户改 D2）。

### 评测 harness（INT-02）
- **D-09:** 新模块（建议）`server/services/process_runtime/gaosan_eval.py`（或 `eval/gaosan_placement_bar.py`）：纯函数
  - 输入：`placements[]`（unit_id + primary_repo）、`membership` / `out_of_team` 集合、可选 role_map
  - 输出：`baseline_primary_hits`、`missing_baselines`、`out_of_team_primary_count`、`passed: bool`、规范化 primary 集合
  - **禁止**读需求全文进日志；观测若有，仅 counts + passed（sampling）。
- **D-10:** 漏斗回归测：在合成 Learning-tools 宇宙内驱动（stub V2 / stub embedding 允许）跑到 placements + gates，再喂给 D-09 断言；若产品路径缺洞导致四基线无法各至少一次 primary，**修漏斗/role/placement 信号或 fixture 对齐**，不得降低 D2 门槛、不得改评测为 feature-point top1。

### 契约与反思（INT-03）
- **D-11:** 维护一份可一键跑的 **契约回归包**（pytest 文件列表或 `pytest` 路径聚合）：至少覆盖 Phase 128–131 漏斗守卫（`test_funnel_*`、`test_funnel_gates*`、`test_reflection`、`test_initiative_profile` / team / shortlist / role / placement 相关）+ 选定 MCP/编排契约（如 `tests/mcp_tools/test_mcp_read_flow.py` 或既有 skill/workflow 契约中与选仓相关的子集——以「不回归」为准，不扩新 MCP 工具）。
- **D-12:** 至少一条 **角色坍塌 → 反思修复** 合成用例：在 131 `test_role_collapse_repair_path_for_int03_hook` 之上，增加 **接线级**（`BlueprintRouteAdapter` 或等价 funnel 出口）用例：注入 forbidden/坍塌 primary → 触发 reflection → 修复后不再含 `role_collapse` / 对应 gate 可再评估；证明非仅纯函数 hook。
- **D-13:** V2 freeze 守卫：本相位业务 commits **不得**修改 `server/codegraph/services/repo_router_v2.py`（评测 stub/monkeypatch 除外）。

### Claude's Discretion
- 合成 fixture 模块数（建议 4–9 个放置单元对齐四角色，不必还原全部 45 feature 点）
- live_space 标记命名与是否放在 `scripts/` vs `tests/.../live/`
- 契约包是独立 `test_v023_contract_suite.py` 聚合 import，还是 Makefile/`pytest` ini marker `v023_funnel`
- role 覆盖断言深度（D2 硬要求是四基线 primary；角色图四角色覆盖可作为附加 soft assert，失败时 warn 或一并硬断言——默认：**硬断言四角色各有 primary 指派或等价 placement 覆盖**，与 ROADMAP「角色覆盖」对齐）

</decisions>

<specifics>
## Specific Ideas

- 旧 quick 评测证明裸 V2 在高三语料上 **study-course 易丢、onion-learning 易被 LLM 剔、out_of_team 易漂**——本相位验收的是漏斗纠正后的 placement-unit 结果，不是复现 V2 分数。
- Phase 131 已留 INT-03 纯函数钩子；132 要把「不回归 + 接线级坍塌修复」收进默认 pytest。
- 四基线 ↔ 四角色直觉映射（fixture 应对齐，非硬编码产品逻辑）：
  - `onion-learning` ≈ `app_shell`
  - `onion-practice` ≈ `practice_reuse_host`
  - `study-course` ≈ `course_config`
  - `study-user-status` ≈ `learning_state`
- 语料正文参考：`.planning/feature-list-demo.md`（高三提分专项 Feature List）。

</specifics>

<canonical_refs>
## Canonical References

### Product / requirements
- `.planning/milestones/v0.23.0-DECISIONS.md` — **D2** 验收门槛
- `.planning/REQUIREMENTS.md` — INT-02, INT-03
- `.planning/ROADMAP.md` — Phase 132 success criteria
- `.planning/PROJECT.md` — 验收锚点四基线仓

### Prior phases（集成面）
- `.planning/phases/128-initiative-profile-team-gate/128-VERIFICATION.md`
- `.planning/phases/129-shortlist-history-role-map/129-VERIFICATION.md`
- `.planning/phases/130-placement-units-wiring/130-VERIFICATION.md`
- `.planning/phases/131-gate-system-reflection/131-VERIFICATION.md`
- `.planning/phases/131-gate-system-reflection/131-CONTEXT.md`（反思/门禁契约）

### Quick eval corpus（参考，非通过标准）
- `.planning/quick/260809-repo-route-eval/SUMMARY.md`
- `.planning/quick/260811-gaosan-route-5rounds/`（`route-5rounds-results.json`、脚本）
- `.planning/feature-list-demo.md`

### Observability
- `.planning/observability/LOGGING-SPEC.md`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `funnel_gates.py` / `reflection.py` / `place_units.py` / `placement_units.py` / `role_map.py` / `shortlist.py` / `team_gate.py`
- `BlueprintRouteAdapter._aapply_placement_funnel` + gates/reflection 接线
- `RepoAssociationService` feature-list 漏斗路径
- `test_reflection.py::test_role_collapse_repair_path_for_int03_hook`
- `test_funnel_gates_wiring.py` Adapter 守卫模式

### Established Patterns
- 合成 fixture + stub V2；断言 hard_scope / membership / reason_codes
- structlog sampling；禁止需求全文
- TDD：先 RED 写 bar/断言，再补 harness 与漏斗对齐
- V2 freeze：commits 文件列表守卫

### Integration Points
- placements 出口 → `gaosan_eval.score_*` → pytest
- 可选 live：Learning-tools Space id（见 260809 SUMMARY）仅标记跳过路径
- INT-03 契约包聚合 128–131 测试入口

</code_context>

<deferred>
## Deferred Ideas

- GATE-F01 / REFL-F01 / 大前端 / 章程自动生效 / LTR
- 把 43 点 top1 或裸 V2 5 轮复跑作为 CI 门禁
- 运营可配置 hit@k 百分比仪表盘

</deferred>

---

*Phase: 132-integration-gaosan-regression*
