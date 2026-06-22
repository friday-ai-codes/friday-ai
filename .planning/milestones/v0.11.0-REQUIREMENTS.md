# Requirements: Friday AI

**Defined:** 2026-06-17
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码。
**Milestone:** v0.11.0 — 开放与协作

> 对外开放与协作层：把内部工具调用（RAG/grep/仓库分析）作为 **progress/trace 事件**透出给 OpenAI/Anthropic 兼容调用方（复用 v0.7 起沉淀的 §15 事件 taxonomy，**INV-5：透出 progress/trace 非模型私有 CoT、不误用标准 tool_calls**），新增 Anthropic 兼容 `/v1/messages` 端点，把飞书机器人对话改走原生 CardKit 流式卡片，并提供工作流自动建群节点。设计底座：`ROADMAP-vNext.md §v0.11`、`DOMAIN-MODEL.md §10`（事件/trace taxonomy）+ §15（事件 payload 规格）。`PREFLIGHT.md` 无映射 v0.11 的 blocking / should-fix 项。

## v1 Requirements

### Agent API trace 透出（TRACE）

- [x] **TRACE-01**: 把内部工具调用（RAG 检索 / grep / 仓库分析等）经 §15 事件 taxonomy 映射为 OpenAI 兼容流式响应中的 progress / `reasoning_summary` 文本，外部兼容调用方能看到"正在检索 RAG / grep / 分析仓库"等进度（adapter over 事件 taxonomy）
- [x] **TRACE-02**: 内部工具调用**绝不**以标准 `tool_calls` 形式回传给外部客户端（防规范客户端误判为挂起等待回传而卡死），也**不暴露**模型私有 CoT（INV-5）；透出机制以 adapter 实现，缺事件时优雅降级、不破坏既有 `/v1/chat/completions` 行为

### Anthropic 兼容端点（ANTHROPIC）

- [x] **ANTHROPIC-01**: 新增 Anthropic 兼容 `/v1/messages` 端点——请求 / 响应按 Anthropic Messages 形状映射（system / messages / max_tokens 等），复用既有 chat / agent 内核，非流式响应可用
- [x] **ANTHROPIC-02**: `/v1/messages` 流式（SSE）可用，trace / progress 经 thinking block adapter 透出（复用 TRACE-01 的同一事件 taxonomy 映射，INV-5 非原始 CoT）

### 飞书原生流式卡片（CARD）

- [x] **CARD-01**: 飞书机器人对话回复改走原生 CardKit 流式卡片（增量更新，替代现有 PATCH 全量替换），流式体验顺滑、无明显闪烁 / 全量重绘

### 工作流自动建群（GROUP）

- [x] **GROUP-01**: 新增"自动建群"工作流节点——可创建飞书群并拉入指定成员（替代现仅能 `add_bot_to_chat` 加入已有群），群 chat_id 作为节点输出可供下游节点 / 写回 `WorkItem.feishu_chat_id` 使用

## v2 Requirements

### 开放进阶（OPENX）

- **OPENX-01**: 标准双向 `tool_calls` 协议（支持"客户端自带工具"由外部客户端执行并回传）——仅当出现该诉求再做（v0.11 明确不做，见 Out of Scope）
- **OPENX-02**: Anthropic 端点的工具使用 / 多模态 content block 全量对齐（本里程碑仅覆盖文本 messages + trace 透出）
- **OPENX-03**: 飞书卡片交互组件（按钮 / 表单回调）与多卡片会话编排（本里程碑仅做流式文本卡片）

## Out of Scope

| Feature | Reason |
|---------|--------|
| 标准双向 `tool_calls`（客户端自带工具回传执行） | 内部工具是服务端闭环执行，回传标准 tool_calls 会让规范客户端误判挂起等待 → 卡死；统一透出为 progress/trace（INV-5）。客户端自带工具留 v2（OPENX-01，已与用户确认） |
| 暴露模型私有 CoT / 原始 thinking 链 | INV-5：对外只暴露 progress/trace 事件（reasoning_summary / thinking block adapter），非模型私有推理链 |
| 新建独立事件 taxonomy | 复用 v0.7 起沉淀的 §15 事件词表（`PlanSessionEvent` / `event_taxonomy`），对外只是不同 adapter；taxonomy 已在 v0.7 稳定落地 |
| 飞书卡片交互组件 / 多卡片编排 | 本里程碑聚焦流式文本卡片体验，交互组件留 v2（OPENX-03） |
| Anthropic 端点工具 / 多模态 content block 全量对齐 | 本里程碑覆盖文本 messages + 流式 trace 透出；工具 / 多模态对齐留 v2（OPENX-02） |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TRACE-01 | Phase 56 | Complete |
| TRACE-02 | Phase 56 | Complete |
| ANTHROPIC-01 | Phase 57 | Complete |
| ANTHROPIC-02 | Phase 57 | Complete |
| CARD-01 | Phase 58 | Complete |
| GROUP-01 | Phase 59 | Complete |

**Coverage:**

- v1 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓
- Delivered: 6/6 ✓（里程碑审计 PASS，见 milestones/v0.11.0-MILESTONE-AUDIT.md）

---
*Requirements defined: 2026-06-17 for milestone v0.11.0*
