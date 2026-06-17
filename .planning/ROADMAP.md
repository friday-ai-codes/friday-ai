# Roadmap: Friday AI

## Milestones

- 🚧 **v0.11.0 开放与协作** — Phases 56–59 (planning)
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

> 跨里程碑前瞻路线（v0.5–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。v0.11 为本前瞻路线的收官里程碑。

## Phases

### 🚧 v0.11.0 开放与协作 (Planning)

**Milestone Goal:** 对外开放与协作层——把内部工具调用（RAG/grep/仓库分析）作为 progress/trace 事件透出给 OpenAI/Anthropic 兼容调用方（复用 v0.7 起沉淀的 §15 事件 taxonomy，INV-5 非模型私有 CoT、不误用标准 tool_calls），新增 Anthropic 兼容 `/v1/messages` 端点，把飞书机器人对话改走原生 CardKit 流式卡片，并提供工作流自动建群节点。设计底座：`ROADMAP-vNext.md §v0.11`、`DOMAIN-MODEL.md §10`（事件/trace taxonomy）+ §15（事件 payload 规格）。`PREFLIGHT.md` 无映射 v0.11 的 blocking/should-fix 项。

- [x] **Phase 56: compat 内部工具调用 → progress/trace 事件透出** (2/2 plans, complete 2026-06-17) - OpenAI 兼容流式响应把内部工具调用经 §15 taxonomy 映射为 progress/`reasoning_summary`，不暴露 CoT、不误用 tool_calls（INV-5），缺事件优雅降级零回归 — TRACE-01, TRACE-02
- [ ] **Phase 57: Anthropic 兼容端点 `/v1/messages`** (1/2 plans) - 新增 Anthropic Messages 形状映射端点（复用既有 chat/agent 内核），非流式 + 流式（SSE）可用，trace 经 thinking block adapter 复用 Phase 56 taxonomy 映射 — ANTHROPIC-01, ANTHROPIC-02
- [ ] **Phase 58: 飞书原生流式卡片（CardKit）** (TBD plans) - 飞书机器人对话回复改走原生 CardKit 流式增量卡片（替代 PATCH 全量替换），体验顺滑无全量重绘 — CARD-01
- [ ] **Phase 59: 工作流自动建群节点** (TBD plans) - 新增"自动建群"工作流节点：创建飞书群 + 拉入成员（替代仅 `add_bot_to_chat`），群 chat_id 作节点输出供下游/写回 `WorkItem.feishu_chat_id` — GROUP-01

## Phase Details

### Phase 56: compat 内部工具调用 → progress/trace 事件透出

**Goal**: OpenAI 兼容调用方能看到内部工具调用的进度，且绝不破坏规范客户端（不误用 tool_calls / 不泄漏 CoT）
**Depends on**: Nothing（复用 v0.7 §15 事件 taxonomy `PlanSessionEvent`/`event_taxonomy` + 既有 `server/compat/` `/v1/chat/completions` 流式 + `reasoning_content`）
**Requirements**: TRACE-01, TRACE-02
**Success Criteria** (what must be TRUE):

  1. 外部 OpenAI 兼容调用方在流式响应中能看到"正在检索 RAG / grep / 分析仓库"等 progress（映射为 `reasoning_summary` / progress 文本），来源是 §15 事件 taxonomy
  2. 内部工具调用**绝不**以标准 `tool_calls` 字段回传（规范客户端不会误判挂起等待回传而卡死）
  3. **不暴露**模型私有 CoT——仅透出 progress/trace 语义（INV-5）
  4. 无事件可透出时优雅降级，既有 `/v1/chat/completions` 行为零回归

**UI hint**: no

### Phase 57: Anthropic 兼容端点 `/v1/messages`

**Goal**: 提供 Anthropic Messages 兼容端点，文本对话 + 流式 trace 透出可用
**Depends on**: Phase 56（复用 taxonomy → progress 透出 adapter，thinking block 复用同一映射）
**Requirements**: ANTHROPIC-01, ANTHROPIC-02
**Success Criteria** (what must be TRUE):

  1. `POST /v1/messages` 按 Anthropic Messages 形状映射（system / messages / max_tokens 等）请求与非流式响应，复用既有 chat/agent 内核
  2. `/v1/messages` 流式（SSE）可用（message_start / content_block_delta / message_stop 事件序列）
  3. trace / progress 经 thinking block adapter 透出，复用 Phase 56 的同一 §15 事件 taxonomy 映射（INV-5 非原始 CoT）
  4. 既有 OpenAI compat 端点零回归

**UI hint**: no

### Phase 58: 飞书原生流式卡片（CardKit）

**Goal**: 飞书机器人对话回复走原生流式卡片，体验顺滑
**Depends on**: Nothing（依赖既有飞书机器人双向对话 + 现 PATCH 流式卡片实现，本 phase 替换为原生 CardKit）
**Requirements**: CARD-01
**Success Criteria** (what must be TRUE):

  1. 飞书机器人对话回复经原生 CardKit 流式接口增量更新（替代 PATCH 全量替换）
  2. 流式过程无明显闪烁 / 全量重绘，体验顺滑
  3. 流式失败 / 不支持时优雅降级到既有路径，对话回复不丢失

**UI hint**: no（飞书侧卡片，非 Web 前端）

### Phase 59: 工作流自动建群节点

**Goal**: 工作流可自动创建飞书群并拉人，群可被下游消费
**Depends on**: Nothing（依赖既有飞书 client + 工作流节点自动注册机制；可选写回 `WorkItem.feishu_chat_id`）
**Requirements**: GROUP-01
**Success Criteria** (what must be TRUE):

  1. 新增"自动建群"工作流节点可创建飞书群并拉入指定成员（替代仅能 `add_bot_to_chat` 加入已有群）
  2. 新建群的 `chat_id` 作为节点输出可供下游节点引用
  3. 可选把群 `chat_id` 写回 `WorkItem.feishu_chat_id`（writeback 字段，DOMAIN §1.2），失败 fail-soft 不阻断工作流

**UI hint**: no（工作流节点，复用既有节点配置 UI）

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

- [x] Phase 53: `AuditEvent` 模型 + emit 地基 (2/2 plans) — AUDIT-01, AUDIT-02 — completed 2026-06-17
- [x] Phase 54: 敏感操作全量覆盖 emit (2/2 plans) — AUDITCOV-01, AUDITCOV-02 — completed 2026-06-17
- [x] Phase 55: 审计查询 API + 前端视图 + 导出 (3/3 plans) — AUDITUI-01, AUDITUI-02 — completed 2026-06-17

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。里程碑审计 passed 见 [milestones/v0.10.0-MILESTONE-AUDIT.md](./milestones/v0.10.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。里程碑审计 passed（11/11 需求、integration_ok、INV-6/INV-2 成立）见 [milestones/v0.9.0-MILESTONE-AUDIT.md](./milestones/v0.9.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。里程碑审计 passed（9/9 需求、integration_ok、Nyquist 5/5）见 [milestones/v0.8.0-MILESTONE-AUDIT.md](./milestones/v0.8.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。里程碑审计 passed（19/19 需求、INV-2/5/6 成立）见 [milestones/v0.7.0-MILESTONE-AUDIT.md](./milestones/v0.7.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.10.0（Phases 1–55）均已交付归档。**当前里程碑 v0.11.0 开放与协作（Phases 56–59）规划完成，待执行**——`/gsd-plan-phase 56` 起步，或 autonomous 跑完整个里程碑。v0.11 为 `ROADMAP-vNext.md` 前瞻路线的收官里程碑。

---
*Previous milestones archived in .planning/milestones/*
