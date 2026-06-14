# Roadmap: Friday AI

## Milestones

- 🚧 **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (active) — 见下方
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 跨里程碑前瞻路线（v0.5–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。

## Phases (v0.5.0)

### Phase 22: 排除配置与统一过滤（fail-closed）

**Goal:** 建立 per-repo/全局排除配置单一源，并在所有读取面 fail-closed 拦截被排除文件。
**Requirements:** EXCL-01, EXCL-02（+ 修 PF-04）
**Success criteria:**

1. 可配置目录/通配/正则排除规则（per-repo + 全局默认）。
2. 被排除文件在索引扫描、MCP get_file/grep、RAG 检索、编码容器 clone 后均不可见。
3. 工具层对命中路径 fail-closed（拒读，不降级泄漏）。

**Plans:** 6 plans（Wave 1: 22-01；Wave 2: 22-02/04/05/06 并行；Wave 3: 22-03）
**Wave 1**

- [x] 22-01-PLAN.md — 排除数据模型 + 单一匹配器 + 内置全局默认 + 设置键 ✅ (064ebdcc0)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 22-02-PLAN.md — 索引扫描面 fail-closed 过滤（full+incremental，修 PF-04）✅ (428c25d0c)
- [ ] 22-04-PLAN.md — 编码容器 clone 后 prune（fail-closed）+ 两派发路径下传规则
- [ ] 22-05-PLAN.md — 排除规则 REST API + 前端 per-repo 编辑入口
- [x] 22-06-PLAN.md — 外部 MCP HTTP 工具（grep/get_file/list/find_related）bare 镜像读取面 fail-closed ✅ (1a0c6f0cd)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 22-03-PLAN.md — 进程内 chat/agent 工具（browse/树）+ RAG 检索 fail-closed + 跨面守护测试（依赖 22-02）

### Phase 23: 清理对账（普通/敏感两模式）

**Goal:** 新增排除后可清理存量派生数据，区分普通排除与敏感清理两模式 + 对账 UI。
**Requirements:** EXCL-04, EXCL-05, EXCL-06（+ 修 PF-03, PF-05）
**Success criteria:**

1. 普通排除清理删净 Qdrant（主+overlay）/ChunkRegistry/codegraph/摘要，无残留。
2. 敏感清理额外覆盖 trace/TaskResult/CodeChangeArchive/prompt snapshot 等操作记录。
3. UI 能对比规则 vs 已索引内容、提示差异、一键清理。

### Phase 24: 敏感文件 AI 识别建议名单

**Goal:** 索引/描述生成阶段识别敏感文件，产出建议名单供用户确认。
**Requirements:** EXCL-03
**Success criteria:**

1. 能识别密钥/env/敏感信息类文件并给出建议名单。
2. 走"建议 + 提醒 + 用户确认"，不静默删除；真密钥高优先级告警。

### Phase 25: Commit 历史索引 + 行号反查

**Goal:** commit 历史可检索 + 行级 → chunk 反查打底。
**Requirements:** IDX-01, IDX-02
**Success criteria:**

1. commit message/author/变更 可被语义检索召回。
2. `ChunkRegistry.line_start/end` 回填；`file:line → chunk_id` API 可用。

### Phase 26: 多仓凭证统一 + MCP 多仓参数

**Goal:** GitLab 凭证统一池 + MCP RAG 多仓检索参数。
**Requirements:** REPO-01, REPO-02
**Success criteria:**

1. 同一 GitLab 实例多仓可复用同一凭证。
2. MCP RAG 工具支持多仓/全仓检索参数。

## Progress

| Phase | Milestone | Requirements | Status | Completed |
|-------|-----------|--------------|--------|-----------|
| 22. 排除配置与统一过滤 | v0.5.0 | EXCL-01..02 | In progress (3/6 plans) | — |
| 23. 清理对账（两模式） | v0.5.0 | EXCL-04..06 | Not started | — |
| 24. 敏感文件 AI 识别 | v0.5.0 | EXCL-03 | Not started | — |
| 25. Commit 历史索引 + 行号反查 | v0.5.0 | IDX-01..02 | Not started | — |
| 26. 多仓凭证统一 + MCP 多仓参数 | v0.5.0 | REPO-01..02 | Not started | — |

**Execution order:** 22 → 23（23 依赖 22 的配置源）；24 依赖 22；25、26 相对独立可并行。

---
*Previous milestones archived in .planning/milestones/*
