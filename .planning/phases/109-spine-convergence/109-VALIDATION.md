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
| T-01-1 SPA 四步同一 `plan_id` 端到端护栏 | 109-01 | 1 | SPINE-01 | T-109-01-01/02 | 非 owner 打 fan-out 与导出端点统一 404；护栏本体不得被 mock | integration | `cd server && uv run pytest tests/test_spa_coding_chain_e2e.py -x` | ❌ W0 | ⬜ pending |
| T-01-2 MCP 桥接三对象直接断言 | 109-01 | 1 | SPINE-02 | T-109-01-02 | 保护对象是模型字段形状而非工具行为 | integration | `cd server && uv run pytest tests/mcp_tools/test_bridge_session.py tests/mcp_tools/test_execution_tools.py tests/mcp_tools/test_create_coding_plan_delegate.py -x` | ❌ W0 | ⬜ pending |
| T-01-3 两个 chat `@tool` 签名 fixture baseline | 109-01 | 1 | SPINE-02 | T-109-01-03 | 契约变更必须留下一次可 review 的显式提交 | unit | `cd server && uv run pytest tests/agents/test_tool_contracts.py -x` | 🟡 加 fixture | ⬜ pending |
| T-02-1 `provenance` + `source_artifact_version_id` + **无条件**唯一约束 + 迁移 | 109-02 | 2 | RELY-01, SPINE-01 | T-109-02-02/04 | default `draft` 不谎报存量；约束**不带 `condition`**（partial index 在 MySQL 上被 `_unique_supported()` 静默跳过）；`get_constraints` 断言约束确实存在 | unit | `cd server && uv run python manage.py makemigrations --check --dry-run && uv run pytest tests/test_coding_plan_model.py -x` | ✅ 存在 | ⬜ pending |
| T-02-2 MCP 裸 ORM 建对象零回归 | 109-02 | 2 | SPINE-02 | T-109-02-03 | 新列带 default / nullable，桥接不崩 | integration | `cd server && uv run pytest tests/mcp_tools/test_bridge_session.py tests/mcp_tools/test_execution_tools.py -x` | ❌ W0（109-01 建） | ⬜ pending |
| T-02-3 新字段双序列化面透出（`provenance` read-only） | 109-02 | 2 | RELY-01 | T-109-02-01 | 客户端不可伪造 `orchestrated` | unit | `cd server && uv run pytest tests/test_coding_plan_api.py tests/test_conversation_facade.py -x` | ✅ 存在 | ⬜ pending |
| T-03-1 §7 → CodingPlan 纯映射（`create→add` 显式断言） | 109-03 | 3 | SPINE-01 | T-109-03-04 | 半可信 LLM content fail-safe 不抛 | unit | `cd server && uv run pytest tests/test_plan_projection_service.py -k mapping -x` | ❌ W0 | ⬜ pending |
| T-03-2 `PlanProjectionService` 幂等/并发/多版本/追溯 + 观测 | 109-03 | 3 | SPINE-01 | T-109-03-05/06/07 | DB 约束 + `aget_or_create` + `IntegrityError` 三件套；异常文本脱敏 | integration | `cd server && uv run pytest tests/test_plan_projection_service.py -x` | ❌ W0 | ⬜ pending |
| T-03-3 惰性投影端点（owner gate + 稳定机器码） | 109-03 | 3 | SPINE-01 | T-109-03-01/02/03 | 不存在与无权限统一 404；请求体不含 `conversation_id`（防 IDOR） | integration | `cd server && uv run pytest tests/test_plan_projection_api.py tests/test_spa_coding_chain_e2e.py -x` | ❌ W0 | ⬜ pending |
| T-04-1 前端类型契约 + 投影 API 客户端 + store action | 109-04 | 4 | SPINE-01 | T-109-04-03 | 前端只传 `artifact_version_id`，不得拼 `CodingPlan` | unit（前端） | `cd web && pnpm vitest run src/stores/__tests__/chat.runtime.spec.ts src/api/__tests__/` | ✅ 存在 | ⬜ pending |
| T-04-2 `OrchestratedPlanCard.vue` +「进入编码」+ 就地交棒 | 109-04 | 4 | SPINE-01 | T-109-04-01/02/04 | 零 `v-html`；不回显后端 `message`；重复点击幂等 | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/OrchestratedPlanCard.spec.ts` | ❌ W0 | ⬜ pending |
| T-04-3 `UNGROUPABLE_TOOLS` 登记 + 渲染分支 + 三处工具展示登记 | 109-04 | 4 | SPINE-01 | T-109-04-01/02 | 静默失守点（漏登记 ⇒ 卡片不渲染）显式断言 | unit（前端） | `cd web && pnpm vitest run src/composables/__tests__/useToolDisplay.spec.ts src/components/chat/__tests__/` | 🟡 加用例 | ⬜ pending |
| T-05-1 两个门一起收窄 + 落库走投影 service + **归属判定下移进 service** + 拒绝留痕 | 109-05 | 5 | SPINE-02 | T-109-05-01/02/03/04/06/07 | schema 层收窄（非 prompt）；无来源 fail-closed 并留痕；`aproject`/`arebind` 必填 `actor_user_id`，工具与端点共享同一道门；不碰 `mcp_tools/`。**预期红窗**：签名 fixture 与 8 个旧签名用例由 T-05-2 收口，不得回退 schema | integration | `cd server && uv run pytest tests/mcp_tools/ tests/test_plan_projection_service.py tests/test_plan_projection_api.py -x` | ✅ 存在 | ⬜ pending |
| T-05-2 正向不变量 + 键集合枚举 + fixture 契约升级 + 工具单测重写 + **跨会话拒绝用例** | 109-05 | 5 | SPINE-02 | T-109-05-01/04/07 | 「结构上不可能」被测试锁住，防未来回退；`arebind` 不跨会话读他人方案正文 | unit | `cd server && uv run pytest tests/agents/test_coding_tools_schema_guard.py tests/agents/test_tool_contracts.py tests/test_coding_tools.py tests/test_plan_projection_service.py tests/test_plan_projection_api.py -x` | ❌ W0（guard 新建） | ⬜ pending |
| T-05-3 11 处影响面同步（两份白名单一致性 + prompt/文案 + 断言升级） | 109-05 | 5 | SPINE-02 | T-109-05-05 | 凡挂 `create_coding_plan` 必挂编排工具（防死路） | unit | `cd server && uv run pytest tests/test_conversation_service_fragment_extraction.py tests/test_conversation_service_prompt_fragments.py tests/test_project_context_line.py tests/test_chat_tools.py -x` | ✅ 存在 | ⬜ pending |
| T-06-1 `techPlan` 三级优先 + `plan_id` 守卫 + 空正文占位 | 109-06 | 5 | SPINE-02 | T-109-06-01/02 | 多方案会话不串态；新增面零 `v-html` | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` | 🟡 加用例 | ⬜ pending |
| T-06-2 tool input 降级为历史兜底 + 三级优先用例 | 109-06 | 5 | SPINE-02 | T-109-06-01 | 历史消息不变空、渲染零报错 | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/` | 🟡 加用例 | ⬜ pending |
| T-07-1 fan-out 草稿 gate（fail-closed + 稳定 `code` + 留痕）+ **三个被打红测试文件的穷举处置** | 109-07 | 6 | RELY-01 | T-109-07-01/02/03/05 | 直接打端点也拒绝且 DB 零写入；gate 在权限门之后；`acknowledge_unresearched` 任何一层都无 `True` 默认值；SPA 四步护栏仍覆盖 draft 形态 | integration | `cd server && uv run pytest tests/test_coding_plans_sessions_api.py tests/test_spa_coding_chain_e2e.py tests/knowledge/test_triggers.py tests/test_coding_session_service.py -x` | 🟡 加用例 | ⬜ pending |
| T-07-2 `CodingExecutionSpec.unresearched` 随 dispatch 下发 | 109-07 | 6 | RELY-01 | T-109-07-06 | 允许清单判定，历史数据走保守分支 | unit | `cd server && uv run pytest tests/test_coding_session_service.py tests/test_coding_session_graph.py tests/test_coding_session_graph_e2e.py -x` | 🟡 加用例 | ⬜ pending |
| T-07-3 飞书导出「未经代码调研」告示 | 109-07 | 6 | RELY-01 | T-109-07-04/06 | 读 `provenance` 不匹配文案；不回显原始取值 | unit | `cd server && uv run pytest tests/test_coding_plan_exporter.py tests/test_coding_plan_export_api.py -x` | 🟡 加用例 | ⬜ pending |
| T-08-1 `isUnresearched` 允许清单 + 草稿横幅 + 常驻徽标 | 109-08 | 7 | RELY-01 | T-109-08-02/03/04 | 未知取值保守标注且不上屏；零 `v-html` | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` | 🟡 加用例 | ⬜ pending |
| T-08-2 确认弹层 + ack 三路径透传 + `code` 分支兜底 | 109-08 | 7 | RELY-01 | T-109-08-01/05/06 | `acknowledge_unresearched: true` 只能由用户勾选产生；按 `code` 不按 `detail` | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` | 🟡 加用例 | ⬜ pending |
| T-08-3 界面标注与确认路径用例扩充 | 109-08 | 7 | RELY-01 | T-109-08-01/02/03/06 | 四种保守分支 + 折叠可见 + 串态防护 + 重试同弹层 | unit（前端） | `cd web && pnpm vitest run src/components/chat/__tests__/` | 🟡 加用例 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*File Exists: ✅ 存在 · 🟡 存在但需加/改用例 · ❌ W0 需新建*

**采样连续性检查**：23 个 task 全部带 `<automated>` 命令，无连续 3 个 task 缺自动化验证；无 watch-mode 参数（`pnpm vitest run` / `pytest -x` 均为一次性）。

---

## Wave 0 Requirements

- [ ] **SPA 四步同一 `plan_id` 不变量的端到端用例** → **plan 109-01 Task 1（wave 1）**。研究确认全仓缺失，且**必须早于任何 schema 改动** —— 这是 SPINE-01→SPINE-02 顺序硬约束的具体落法。计划层的落法：109-01 处于 wave 1，109-02（首个模型/迁移改动）处于 wave 2，109-05（schema 收窄）处于 wave 5。
- [ ] **工具 schema 漂移守护** → 分两步落地，理由是正向不变量在收窄前必然失败：
  - [ ] **漂移可见（wave 1）**：plan 109-01 Task 3 给 `create_coding_plan` / `update_coding_plan` 各建一份 `inspect.signature` fixture baseline（记录收窄前现状），接入既有 `tests/agents/test_tool_contracts.py` 的字节 diff 机制 ⇒ 此后任何入参增删都会显式变红。
  - [ ] **正向不变量（wave 5）**：plan 109-05 Task 2 新建 `tests/agents/test_coding_tools_schema_guard.py`，断言 `"tech_plan" not in parameters["properties"]` / `"affected_files" not in ...` / `"artifact_version_id" in required`，并追加两组 `properties` **键集合枚举式相等**断言（让「悄悄加一个新的正文别名入参」也变红，而非只防住这两个具体名字）。

*MCP 侧护栏已完整（6 组 delegate 守护 + 执行链 e2e），无需新建；但 109-01 Task 2 仍新建 `tests/mcp_tools/test_bridge_session.py` 补上「`_create_bridge_session` 建成三对象且字段形状不变」的直接断言 —— 既有 `test_execution_tools.py` 只间接覆盖 `CodingSession`，未显式断言 chat `CodingPlan`（109-RESEARCH §11.2 的 🟡 缺口）。*

---

## Explicit Scope Boundaries

逐条记录本 phase 刻意不做/收窄的范围，供 VERIFICATION 引用，避免误判为缺陷：

1. **D-3（投影只做 chat 入口）**：无 conversation 的编排入口（workflow / MCP）不做投影——`ConvergenceSession` 无 space FK，反查有歧义。SC-1 的用户故事在 chat 入口下完整成立；其余入口记 deferred。
2. **D-4（chat 呈现只做最小可操作面）**：不渲染方案正文、无进度 UI、无阶段流式/时间线——严格留给 Phase 110。
3. **DEPTH 冻结**：`process_runtime` 的 prompt/schema 不做 DEPTH 向改动（v0.20.0 并行）。方案结构深度由 v0.20.0 蓝图提供。
4. **两套 CodingPlan 不合表**：`chat.CodingPlan` 与 `mcp_tools.McpCodingPlan` 合为 canonical 属 Future（REQUIREMENTS 已列）。
5. **MCP 桥接的保护对象是「模型字段形状」而非工具行为**：MCP 执行链从不调用 chat `@tool`，其桥接是 `_create_bridge_session` 的裸 ORM——新增字段**必须带 default**，否则裸 `objects.create()` 崩。
6. **`create_coding_plan` 不整体删除**：只砍创作半边，执行半边（选仓/分支/确认编码/导出）保持可用。
7. **`CodingPlan → MergeRequest` 不建 FK**：`MergeRequest` 从未与 chat 编码域建外键（109-RESEARCH §7）。本 phase 只补 `ArtifactVersion → CodingPlan` 这一段断链，`CodingPlan → MR` 沿用既有 `pr_url` + `(repository, source_branch)` 弱对齐。SC-4 的追溯验收口径 = 「`source_artifact_version_id → ArtifactVersion → Artifact → WorkItem` 两跳可达」，不含端到端 FK join。
8. **导出第三出口不覆盖**：`ArchitectMergeAdapter._maybe_bind_plan_to_project` → `ProjectDocService.append_research_note` 的项目 RESEARCH 文档镜像只走编排产物（恒 `orchestrated`），不可能是草稿，RELY-01 的双侧标注无需覆盖它。
9. **存量方案将集体出现草稿标注**：迁移 `default="draft"` ⇒ 历史会话里所有徒手创作的 `CodingPlan` 卡片都会出现「未经调研」横幅与徽标。这是 **RELY-01 的预期行为**（存量确实全是徒手产物，保守标注正确），**不是回归**。
10. **`render_merged_plan_markdown` 的 lark_md 方言接受现状**：投影出的 `tech_plan` 用 `•` 而非 `- `，在 markdown-it（GFM）下显示为纯文本项目符号。本 phase 不 fork 第二个渲染器；若 UAT 判观感不可接受，处置方式是给该函数加 `flavor` 参数。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 「进入编码」入口与投影后交棒的观感 | SPINE-01 | 视觉与交互判断 | 编排产出方案后点「进入编码」，确认就地内嵌执行流卡片、无空窗 |
| 草稿标注双侧一致性（界面 + 飞书导出物） | RELY-01 | 飞书导出需真实环境 | 导出一份草稿方案，确认导出物含「未经代码调研」告示且与界面主句逐字一致 |
| 执行流四步真机连通（含飞书导出） | SPINE-01 | 需真实 Git 平台与飞书 | 走完选仓→配分支→确认编码→导出全链 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies（23/23）
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（SPA 四步护栏 + MCP 桥接锁 + 签名 fixture 在 wave 1；正向不变量在 wave 5，理由见 §Wave 0 Requirements）
- [x] No watch-mode flags（`pnpm vitest run` / `pytest -x`）
- [x] Feedback latency < 60s（per-task 命令均为定向跑：后端 `pytest` 定向文件 / 前端 `vitest run` 定向路径）。**全仓类型检查 `pnpm vue-tsc --noEmit -p tsconfig.json` 不计入 per-task 反馈延迟** —— 它通常远超 60s，因此在 109-04 / 109-06 / 109-08 三个前端 plan 中只作为 **plan 级 `<verification>`**（每个 wave 收口时跑一次），不作为任何 task 的 `<automated>`。这条口径与 §Sampling Rate 的「After every task commit: 受改模块定向跑」一致。
- [ ] `nyquist_compliant: true` set in frontmatter（待 wave 1 落地后置真）

**Approval:** pending
