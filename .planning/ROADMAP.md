# Roadmap: Friday AI

## Overview

v0.25.0 把 Cursor / Claude Code 中有价值的问答沉淀为 Friday 可召回的仓库知识：先以独立 Capture 账本保证数据永不静默丢失，再冻结 `report_session_knowledge` 契约，异步完成价值评估与中高价值入图，开放仓库/项目召回和原始回放，最后接通两个 IDE 宿主。历史里程碑详情归档在 `.planning/milestones/`。

## Milestones

- ✅ **v0.24.0 单仓图查询对齐 GitNexus** — Phases 133–140（completed 2026-08-24，未打 tag）
- 🚧 **v0.25.0 Cursor / Claude Code 会话知识回写** — Phases 141–145（planning）

## Phases

- [x] **Phase 141: Capture 账本与仓库挂钩** - 原始问答先安全、可归因地落账本，仓库或项目解析失败也不丢 Capture (completed 2026-08-28)
- [x] **Phase 142: MCP 会话回写契约** - 通过新工具 `report_session_knowledge` 提交 Capture，并保持服务端、snapshot、npm 三面对齐 (completed 2026-08-28)
- [ ] **Phase 143: 价值评估与中高入图** - 异步评估 high/medium/low，仅 medium/high 可重试地进入统一知识库
- [ ] **Phase 144: 仓库召回与 Capture 回放** - 按仓库/项目召回会话知识并按 Capture id 安全回放原始问答
- [ ] **Phase 145: Cursor / Claude Code 双宿主采集** - 两个宿主自动配对问题与可见答案精华，干净工作树也能 fail-soft 回写

## Phase Details

### Phase 141: Capture 账本与仓库挂钩

**Goal**: 用户提交的会话问答始终先进入独立、脱敏、可归因的 Capture 账本，并尽可能关联仓库与可选项目
**Depends on**: Phase 140
**Requirements**: STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, OBS-01, OBS-02
**Success Criteria** (what must be TRUE):

  1. 用户提交结构化问答后可获得一条独立 Capture；其中保留问题、可见答案精华、会话与来源元数据，但不会写成 `ProjectMemory` 或 Interaction Ledger 正文。
  2. `repository_id`、`project_id` 任一或同时缺失时 Capture 仍会落库；git URL 无法解析时记录明确 `repo_unresolved` 原因而不静默跳过。
  3. 模型、provider 或 token 计数不可得时以 `unknown` 保存，服务端不会猜测补全。
  4. 每次持久化都经 `CaptureService` 完成脱敏与触发用户归因，并产生带 `duration_ms` 的 caller 生命周期事件；凭证、token、密钥不会进入 Capture、Ledger 或日志。

**Plans:** 4/4 plans complete

Plans:

- [x] 141-01-PLAN.md — Wave 0：Capture/INV-6/观测失败测试骨架（STORE/OBS 契约钉死）
- [x] 141-02-PLAN.md — SessionCapture 模型 + CaptureService 核心 persist + INV-6（STORE-01/02/03/05）
- [x] 141-03-PLAN.md — 仓库/项目挂钩状态机与幂等 first-write-wins（STORE-04/03）
- [x] 141-04-PLAN.md — caller 观测、LOGGING-SPEC 与账本分离回归（OBS-01/02、STORE-01）

### Phase 142: MCP 会话回写契约

**Goal**: Cursor / Claude Code 可通过稳定的新 MCP 工具提交会话知识，任何挂钩失败都不影响 Capture 被接受
**Depends on**: Phase 141
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04
**Success Criteria** (what must be TRUE):

  1. 已认证用户可调用 `report_session_knowledge`，以必填 `question`/`answer` 和可选仓库、分支、会话、项目、模型、客户端字段获得 `accepted=true` 与 `capture_id`。
  2. 无项目、仓库解析失败或默认分支无法唯一定位项目时，调用仍返回 200、`accepted=true` 并产生 Capture；`reason` 如实描述挂钩结果而不表示数据未收。
  3. 服务端 serializer、`TOOL_SCHEMA_SNAPSHOT` 与 npm `mcp/src/tools.ts` 暴露同一工具契约，任一面漂移都会被自动化验收阻止。
  4. 既有 `report_project_knowledge` 仍执行原有项目门闩与 git-diff 记忆路径，不会被扩成 Capture 入口或发生行为回退。

**Plans:** 4/4 plans complete

Plans:

- [x] 142-01-PLAN.md — Wave 0：HTTP 接受语义、三面 schema、client 审计与旧工具隔离 RED 契约
- [x] 142-02-PLAN.md — 服务端 serializer/snapshot/view/url 接线并复用 CaptureService 与 McpToolView lifecycle
- [x] 142-03-PLAN.md — npm 第 52 个工具定义、完整输入 schema 与专用幂等 annotations
- [x] 142-04-PLAN.md — 跨面 phase gate、旧 report_project_knowledge 零回归与 Nyquist 收口

### Phase 143: 价值评估与中高入图

**Goal**: Friday 在 Capture 持久化之后可靠评估知识价值，仅把可复用的中高价值精华加入统一 RAG
**Depends on**: Phase 142
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05, OBS-04
**Success Criteria** (what must be TRUE):

  1. 每条已落库 Capture 会异步得到 `high`、`medium` 或 `low` 价值等级及可检索精华；评估失败时原始 Capture 保留且状态可重试。
  2. 评估调用以独立 `call_source=session_capture_eval` 上报用量，不复用写回质量门或仓库路由 confidence 充当价值等级。
  3. `medium`/`high` Capture 自动经既有摄取入口进入 `delivery_knowledge`，使用 `EntityKind.DOCUMENT` 与 `source_kind=session_capture`；`low` 不向量化但仍可回放。
  4. 服务重启或短暂故障不会丢失待评估/待入图工作：投递 persist-first、可重试，且后台任务保留并重新绑定触发用户。
  5. 评估与入图不会调用项目记忆写入口；`ProjectMemory` 继续保持 draft 门控，Capture 原始内容也不会被当成 RAG 正文。

**Plans**: TBD

### Phase 144: 仓库召回与 Capture 回放

**Goal**: 授权用户能按仓库或项目找回中高价值会话知识，并在需要时只读回放对应原始 Capture
**Depends on**: Phase 143
**Requirements**: RECALL-01, RECALL-02, RECALL-03, RECALL-04, OBS-03
**Success Criteria** (what must be TRUE):

  1. 授权用户可按 `repository_id` 检索已入图的会话知识，并在有项目关联时按 `project_id` 收窄结果。
  2. `pack_project_context` 与交付知识检索会显式纳入 `session_capture`，使已入图知识可被后续 IDE/Agent 上下文召回。
  3. 授权用户可按 Capture id 只读回放原始结构化问答；回放不会扫描 Interaction Ledger payload 作为正文来源。
  4. `main`、`master`、`develop` 等默认分支不会单独把 Capture 误绑到项目，`lookup_project_by_branch` 的默认分支第三源不会返回 `matched=true`。
  5. MCP 与对话召回链 best-effort 写入脱敏 `RetrievalTrace`；观测失败不会改变检索结果。

**Plans**: TBD

### Phase 145: Cursor / Claude Code 双宿主采集

**Goal**: Cursor 与 Claude Code 都能在不阻断编码的前提下自动抽取本轮问题和可见答案精华并回写 Capture
**Depends on**: Phase 144
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04, SKILL-05
**Success Criteria** (what must be TRUE):

  1. Claude Code 通过 `UserPromptSubmit` 缓存问题，并以 `Stop.last_assistant_message` 提取可见答案；Cursor 通过 `beforeSubmitPrompt` 缓存问题、`afterAgentResponse` 配对答案。
  2. 工作区无 git 改动或没有 `diff --stat` 时，零散问答仍会调用 `report_session_knowledge` 并产生 Capture。
  3. 客户端只提交问题与可见答案精华，不上传隐藏思维链；skills、HTTP fallback、`ide_hook_assets` 与 snapshot 守卫对同一行为达成一致。
  4. 安装器可合并 Cursor `hooks.json`（`version: 1`）而不覆盖既有 hook；缺 PAT、接口失败或回写超时时均 fail-soft，不阻断用户继续编码。
  5. Claude Code 专属注入脚本不会被错误复制到 Cursor `stop`，两个宿主的 hook 资产与各自官方事件模型一致。

**Plans**: TBD

## Locked Decisions

- 工具名固定为 `report_session_knowledge`，不扩展 `report_project_knowledge`。
- Capture 以仓库为主挂钩、项目可选；任何解析失败都不得丢 Capture。
- 原始 Capture、提炼知识、Interaction Ledger 三层分离。
- 入图固定使用 `EntityKind.DOCUMENT` + `source_kind=session_capture`，不新增 collection 或 EntityKind。
- 评估固定使用 `call_source=session_capture_eval`；medium/high 自动进入仓级 RAG，low 仅保留回放。
- `ProjectMemory` 保持 draft 门控，不把 Capture 自动写成 active memory。
- 客户端只抽可见精华，未知字段记 `unknown`；不采集全文 transcript 或隐藏思维链。
- 不引入新的 Python/npm 运行时依赖；容器内编码代理写 Capture 保持 Out of Scope。

## Progress

**Execution Order:** 141 → 142 → 143 → 144 → 145

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 141. Capture 账本与仓库挂钩 | v0.25.0 | 4/4 | Complete    | 2026-08-28 |
| 142. MCP 会话回写契约 | v0.25.0 | 4/4 | Complete   | 2026-08-28 |
| 143. 价值评估与中高入图 | v0.25.0 | 0/TBD | Not started | - |
| 144. 仓库召回与 Capture 回放 | v0.25.0 | 0/TBD | Not started | - |
| 145. Cursor / Claude Code 双宿主采集 | v0.25.0 | 0/TBD | Not started | - |

**Coverage:** 27/27 v0.25.0 requirements mapped exactly once；0 unmapped；0 duplicate。

---
*Roadmap created: 2026-08-28*
