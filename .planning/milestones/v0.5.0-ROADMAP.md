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

**Plans:** 7/6 plans complete
**Wave 1**

- [x] 22-01-PLAN.md — 排除数据模型 + 单一匹配器 + 内置全局默认 + 设置键 ✅ (064ebdcc0)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 22-02-PLAN.md — 索引扫描面 fail-closed 过滤（full+incremental，修 PF-04）✅ (428c25d0c)
- [x] 22-04-PLAN.md — 编码容器 clone 后 prune（fail-closed）+ 两派发路径下传规则 ✅ (1c925c804)
- [x] 22-05-PLAN.md — 排除规则 REST API + 前端 per-repo 编辑入口 ✅ (b8c2adc38)
- [x] 22-06-PLAN.md — 外部 MCP HTTP 工具（grep/get_file/list/find_related）bare 镜像读取面 fail-closed ✅ (1a0c6f0cd)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 22-03-PLAN.md — 进程内 chat/agent 工具（browse/树）+ RAG 检索 fail-closed + 跨面守护测试（依赖 22-02）✅ (481ba91d6)

**Gap closure** *(22-VERIFICATION 唯一阻断项，EXCL-02)*

- [x] 22-GAP — `CodeSearchView._search`（REST `POST /api/repositories/<id>/search/` 旁路直读面）fail-closed：挂接 build_matcher_for_repo + is_excluded，被排除文件不返回 content/path + 守护测试 ✅ (56d230553)

### Phase 23: 清理对账（普通/敏感两模式）

**Goal:** 新增排除后可清理存量派生数据，区分普通排除与敏感清理两模式 + 对账 UI。
**Requirements:** EXCL-04, EXCL-05, EXCL-06（+ 修 PF-03, PF-05）
**Plans:** 4/4 plans complete
**Success criteria:**

1. 普通排除清理删净 Qdrant（主+overlay）/ChunkRegistry/codegraph/摘要，无残留。
2. 敏感清理额外覆盖 trace/TaskResult/CodeChangeArchive/prompt snapshot 等操作记录。
3. UI 能对比规则 vs 已索引内容、提示差异、一键清理。

Plans:
**Wave 1**

- [x] 23-01-PLAN.md — 统一 purge_file 删除入口（PF-03 + PF-05 + overlay），删后四面无残留（Wave 1）✅ (6b481a8cf/d6ccf931b/972b720d5)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 23-02-PLAN.md — 普通清理服务 + 对账计算 + reconcile/cleanup API（Wave 2）✅ (8f91c8cb7/63f492be9/b20f7bedf)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 23-03-PLAN.md — 敏感清理操作记录数据面（CodeChangeArchive/TaskResult/ActionLog 等，Wave 3）✅ (beca0283c/869f534ac)
- [x] 23-04-PLAN.md — 对账/清理前端面板（差异提示 + 普通/敏感双入口强确认 + 派发后状态回显未清面/caveat，Wave 3）✅ (51cd36867/baa35af01)

### Phase 24: 敏感文件 AI 识别建议名单

**Goal:** 索引/描述生成阶段识别敏感文件，产出建议名单供用户确认。
**Requirements:** EXCL-03
**Plans:** 4/4 plans complete
**Success criteria:**

1. 能识别密钥/env/敏感信息类文件并给出建议名单。
2. 走"建议 + 提醒 + 用户确认"，不静默删除；真密钥高优先级告警。

Plans:
**Wave 1**

- [x] 24-01-PLAN.md — SensitiveFileSuggestion 模型 + 迁移 + 确定性检测器（启发式+内容扫描+upsert） ✅ 2026-06-15

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 24-02-PLAN.md — run_full_index 后台触发 + 可选 LLM 二分类（graceful 退化） ✅ 2026-06-15
- [x] 24-03-PLAN.md — REST API：list / accept（建 ai_suggested 规则）/ dismiss，绝不静默删 ✅ 2026-06-15

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 24-04-PLAN.md — 前端建议面板（real_secret 高优先级告警 + 接受/忽略 + 页面挂载） ✅ 2026-06-15

### Phase 25: Commit 历史索引 + 行号反查

**Goal:** commit 历史可检索 + 行级 → chunk 反查打底。
**Requirements:** IDX-01, IDX-02
**Plans:** 4/4 plans complete
**Success criteria:**

1. commit message/author/变更 可被语义检索召回。
2. `ChunkRegistry.line_start/end` 回填；`file:line → chunk_id` API 可用。

Plans:
**Wave 1**

- [x] 25-01-PLAN.md — IDX-02：索引时回填 ChunkRegistry.line_start/line_end（无需 migration，字段已存在）✅ (cd14492cb)
- [x] 25-02-PLAN.md — IDX-02：find_chunk_at service + GET /api/repositories/<id>/chunk-at/（fail-closed 排除）✅ (f6477be3b)
- [x] 25-03-PLAN.md — IDX-01：commit 历史摄取服务 + 增量边界字段 migration（kind=commit 入主 collection）✅ (6aa4d3dc1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 25-04-PLAN.md — IDX-01：commit 索引挂接全量/增量流程 + search_rag 召回端到端守护 ✅ (daa1b198b)

### Phase 26: 多仓凭证统一 + MCP 多仓参数

**Goal:** GitLab 凭证统一池 + MCP RAG 多仓检索参数。
**Requirements:** REPO-01, REPO-02
**Success criteria:**

1. 同一 GitLab 实例多仓可复用同一凭证。
2. MCP RAG 工具支持多仓/全仓检索参数。

**Plans:** 6/5 plans complete
Plans:
**Wave 1**

- [x] 26-01-PLAN.md — REPO-01: GitInstanceCredential 模型 + 迁移 0036 + 凭证解析器（per-repo 优先 → 实例池 host fallback）+ 单测
- [x] 26-05-PLAN.md — REPO-02: search_rag_chunks 多仓/全仓参数 + 合并检索 + 来源标注 + 跨仓 fail-closed 守护测试

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 26-02-PLAN.md — REPO-01: 解析器接入克隆/索引/bare 镜像/图谱克隆取 token 路径 + 守护测试
- [x] 26-03-PLAN.md — REPO-01: 解析器接入 git 平台客户端（MR/PR）/ 编码 dispatch / diff archive 取 token 路径 + 守护测试 ✅ (b592debac)
- [x] 26-04-PLAN.md — REPO-01: 实例凭证 REST CRUD（token write-only 加密、IsSuperUser）+ 前端管理页（不回显）+ 守护测试 ✅ (d18394869)
- [x] 26-06-GAP — REPO-01: 闭合 26-VERIFICATION 缺口——残留 6 文件 ≥8 处内联取 token（pr.py/coding_graph.py/code_review.py/summary_service.py/chat_tools.py/views.py TestConn）统一经解析器 + gap 守护测试 ✅ (b76a9f1d6, 39d351ad7)

## Progress

| Phase | Milestone | Requirements | Status | Completed |
|-------|-----------|--------------|--------|-----------|
| 22. 排除配置与统一过滤 | v0.5.0 | 7/6 | Complete    | 2026-06-14 |
| 23. 清理对账（两模式） | v0.5.0 | 4/4 | Complete    | 2026-06-14 |
| 24. 敏感文件 AI 识别 | v0.5.0 | 4/4 | Complete    | 2026-06-14 |
| 25. Commit 历史索引 + 行号反查 | v0.5.0 | 4/4 | Complete    | 2026-06-14 |
| 26. 多仓凭证统一 + MCP 多仓参数 | v0.5.0 | 6/5 | Complete    | 2026-06-15 |

**Execution order:** 22 → 23（23 依赖 22 的配置源）；24 依赖 22；25、26 相对独立可并行。

---
*Previous milestones archived in .planning/milestones/*
