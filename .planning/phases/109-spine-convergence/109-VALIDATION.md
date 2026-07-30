---
phase: 109
slug: spine-convergence
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-30
---

# Phase 109 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/） |
| **Config file** | server/pyproject.toml |
| **Quick run command** | `cd server && uv run pytest tests/chat tests/mcp_tools -q` |
| **Full suite command** | `cd server && uv run pytest -q`；前端 `cd web && pnpm vitest run` |
| **Estimated runtime** | 快跑 ~60s；全量 ~11min |

---

## Sampling Rate

- **After every task commit:** 受改模块定向跑（chat / mcp_tools / agents / delivery）
- **After every plan wave:** SPA 与 MCP 两条编码链路端到端 + 受影响模块全量
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| （由 planner 填充） | — | — | SPINE-01/02, RELY-01 | — | 草稿送编码需显式确认；投影不绕权限 | unit/integration | `uv run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **SPA 四步同一 `plan_id` 不变量的端到端用例**（研究确认全仓缺失，且**必须早于任何 schema 改动** —— 这是 SPINE-01→SPINE-02 顺序硬约束的具体落法）
- [ ] 工具 schema 漂移守护（正向不变量：创作入参不存在于 schema）

*MCP 侧护栏已完整（6 组 delegate 守护 + 执行链 e2e），无需新建。*

---

## Explicit Scope Boundaries

逐条记录本 phase 刻意不做/收窄的范围，供 VERIFICATION 引用，避免误判为缺陷：

1. **D-3（投影只做 chat 入口）**：无 conversation 的编排入口（workflow / MCP）不做投影——`ConvergenceSession` 无 space FK，反查有歧义。SC-1 的用户故事在 chat 入口下完整成立；其余入口记 deferred。
2. **D-4（chat 呈现只做最小可操作面）**：不渲染方案正文、无进度 UI、无阶段流式/时间线——严格留给 Phase 110。
3. **DEPTH 冻结**：`process_runtime` 的 prompt/schema 不做 DEPTH 向改动（v0.20.0 并行）。方案结构深度由 v0.20.0 蓝图提供。
4. **两套 CodingPlan 不合表**：`chat.CodingPlan` 与 `mcp_tools.McpCodingPlan` 合为 canonical 属 Future（REQUIREMENTS 已列）。
5. **MCP 桥接的保护对象是「模型字段形状」而非工具行为**：MCP 执行链从不调用 chat `@tool`，其桥接是 `_create_bridge_session` 的裸 ORM——新增字段**必须带 default**，否则裸 `objects.create()` 崩。
6. **`create_coding_plan` 不整体删除**：只砍创作半边，执行半边（选仓/分支/确认编码/导出）保持可用。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 「进入编码」入口与投影后交棒的观感 | SPINE-01 | 视觉与交互判断 | 编排产出方案后点「进入编码」，确认就地内嵌执行流卡片、无空窗 |
| 草稿标注双侧一致性（界面 + 飞书导出物） | RELY-01 | 飞书导出需真实环境 | 导出一份草稿方案，确认导出物含「未经代码调研」告示且与界面主句逐字一致 |
| 执行流四步真机连通（含飞书导出） | SPINE-01 | 需真实 Git 平台与飞书 | 走完选仓→配分支→确认编码→导出全链 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
