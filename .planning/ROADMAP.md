# Roadmap: Friday AI

## Milestones

- 🚧 **v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）** — Phases 82–89 (planning 2026-06-26)
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

## Phases

### 🚧 v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）(Phases 82–89 — PLANNING)

**Milestone Goal:** 把"项目"升级为团队真正用的**在线协作工作区**——每个项目一个飞书文件夹 + 5 个固定工作区文件（MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT），人在飞书写、Agent/Cursor 在系统写，**双向实时同步且不互相冲掉**；项目上下文可被任意来源读取/召回/回写；并把"feature list → 拆看板 → 关联仓库 → 技术方案 → 建分支"做成人机协同卡片流水线。构建于 v0.15.0 领域地基之上，复用不重造。

> 完整设计与调研基线见 `.planning/project-workspace/MILESTONE-PROPOSAL.md`；需求 37 条见 `.planning/REQUIREMENTS.md`。4 个锁定决策：DB canonical + 飞书双向镜像；默认全员可读+visibility 开关、写仅成员；MEMORY 条目式不做整篇 diff；STATE/MILESTONES 活计算+结构化+补充段。

**Wave 1 — 工作区实体 + 双向同步地基（最小可交付）：**

- [x] **Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件落地** - 扩 `Project`(visibility/feishu_folder_token) + 新 `ProjectDoc`/`ProjectDocBlockMap` + 每项目飞书文件夹 + 5 文件创建于其下 + 互链/看板描述链接 + 侧边栏「项目」tab + 权限翻转（public_org 默认/写仅成员）— WS-01~04, DOC-01~06
- [ ] **Phase 83: 飞书文档双向同步引擎** - `drive.file.edit_v1` subscribe + 事件路由 + block 级增量推送 + block_id 结构化匹配（代替整篇 diff）+ last-synced 快照/映射表 + 三方合并 + 编辑感知延迟写 + redis read-through + TTL 兜底 + 边界/失败模式全集 — SYNC-01~06
- [ ] **Phase 84: 项目工作台前端 2.0** - 大盘（概览/人员带身份/状态栏）+ feature list 进度灯 + 5 文件查看编辑（md 实时渲染）+ 记忆编辑/LLM 提议确认 + 外部依赖关联展示 + 列表筛选/全局+RAG 搜索 — WB-01~05

**Wave 2 — 上下文闭环（IDE hooks）：**

- [ ] **Phase 85: 项目上下文可读 + 分支绑定** - 项目上下文物化为可 RAG+grep+file-read（MCP/skills/前端任意来源）+ 沉淀进知识图谱可索引/关联扩充 + `ProjectBranch` 多绑定模型 + 分支名反查项目扩展 — CTX-01/02, BIND-01/02
- [ ] **Phase 86: IDE 上下文闭环（hooks）** - 读路径 MCP 注入工具 + always-on rule（三家通）+ Claude Code UserPromptSubmit 注入；写路径 stop hook → report 写回 draft（质量门槛/归因/脱敏）+ STATE 结构化回写 + claude code runner 派发带上下文 + session 持久化（SessionStore→Redis）— HOOK-01~04

**Wave 3 — feature list 交付流水线：**

- [ ] **Phase 87: 看板拆分节点 + 群 + 流式卡片** - feature list → 子看板（work_item/create + 父子关联，名=feature 名/描述=feature 原文）工作流节点 + AI 会话可调 + 拉群+bot 入群 + 拆分结果流式卡片（开始创建/输入框）+ 多轮重拆 — BOARD-01/02
- [ ] **Phase 88: 智能业务关联仓库** - 知识库（活跃度/功能梳理）+ RAG 多轮 + Agent 自处理 + 卡片引导式多轮澄清/确认 + 用户确认后逐仓自校验 + 最终卡片确认 — REPO-01/02
- [ ] **Phase 89: 技术方案深化 + 建分支绑项目** - per-repo+overall 方案（负责事项/预改动/影响模块/e2e·单测/风险/feature 冲突）+ 修订回路「调研问题发现」卡片 + 容器 5min 挂起/resume（session 持久化）+ 按方案建分支推送并绑项目 — PLAN-01~04

> **执行/拆分建议**：Wave 1（82–84）是最小可交付地基，必须先做且全绿；Wave 2（85–86）、Wave 3（87–89）依赖 Wave 1，可在本里程碑内顺序推进，也可按需拆成 v0.17/v0.18 独立发布。

## Phase Details

### Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 五份文件落地（Project Workspace Entity）

**Goal**: 立起"项目工作区"实体层——扩展 `Project`、新增 5 文件容器与同步映射表、每项目建飞书文件夹并把 5 文件创建于其下、文件互链 + 看板描述可打开、侧边栏「项目」tab、权限翻转为默认全员可读/写仅成员
**Depends on**: v0.15.0（`initiatives` app / `ProjectService` / `ProjectMemory` / `feishu_doc.py`）
**Requirements**: WS-01~04, DOC-01~06
**Success Criteria** (what must be TRUE):

  1. `Project` 扩 `visibility`(public_org/members_only 默认 public_org) + `feishu_folder_token`；权限翻转——非成员可读可发起会话、写（记忆/STATE/成员/文件）仅成员 fail-closed，召回 scope 随 visibility；脱敏不可绕过
  2. 新增 `ProjectDoc`(5 type) + `ProjectDocBlockMap`（block_id↔DB ref + section）+ `ProjectStateApi`（结构化 API 清单）模型，写入收口 service（INV-6）
  3. 每项目经 `create_folder` 建飞书专属文件夹（父=Space folder），MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT 5 文件用 `create_document(folder_token=…)` 创建于其下；DB 存 folder/doc token，不乱放
  4. 5 文件头部导航区互链 + 看板（项目跟踪）描述追加「项目工作区」段（文件夹/5 文件/Friday 项目页链接），可从看板打开
  5. 前端侧边栏新增「项目」tab（首页↓空间↑）；STATE/MILESTONES 以活计算派生 + 补充段、MEMORY 复用条目式渲染

**Plans**: 5 plans

Plans:
- [x] 82-01-PLAN.md — 扩 Project(visibility/feishu_folder_token) + 新 ProjectDoc/ProjectDocBlockMap/ProjectStateApi 模型 + 迁移 0006（纯 AddField+CreateModel 无回填）
- [x] 82-02-PLAN.md — FeishuDocClient.create_folder + ProjectDocService 单一写入(INV-6) + 后台串行建文件夹/5 文件/互链/看板描述追加(DOC-06) + broken 兜底 + guard/feishu respx 测试
- [x] 82-03-PLAN.md — 权限翻转读半：pack_project_context + access_scope 按 visibility 分流（public_org 读放行 / members_only fail-closed）+ 对称守护测试
- [x] 82-04-PLAN.md — 前端侧边栏「项目」tab(首页↓空间↑) + /projects 默认按所选空间 + localStorage 记忆 + vitest
- [x] 82-05-PLAN.md — REST：visibility PATCH + rehome_space 改归(WS-03) + ProjectDoc 列表/一键重建 + ProjectStateApi 列表/增删(DOC-02)

**Waves**: W1 = 82-01 ∥ 82-04；W2 = 82-02 ∥ 82-03（均依赖 82-01）；W3 = 82-05（依赖 82-02）

**UI hint**: yes

### Phase 83: 飞书文档双向同步引擎（Feishu Doc Bi-Sync Engine）

**Goal**: 实现 5 文件的飞书↔Friday 双向近实时同步，且用户在飞书编辑绝不被系统写入冲掉；覆盖全部边界/失败模式
**Depends on**: Phase 82（5 文件 + 飞书文件夹 + 映射表就绪）
**Requirements**: SYNC-01~06
**Success Criteria** (what must be TRUE):

  1. 飞书→Friday：按文件 `subscribe` + 现有事件链路路由 `drive.file.edit_v1` → 回拉正文；进行中项目 TTL 轮询兜底防漏事件
  2. Friday→飞书：DB 写触发 block 级增量推送，**永不整篇覆盖**；per-doc 串行队列 + 限流退避
  3. block_id 结构化匹配（新增/编辑/删除）+ last-synced 快照 + 映射表代替整篇 diff；MEMORY 飞书编辑按 block_id 落 revision
  4. 冲突处理：区段所有权分区（系统区/人工区互不写）+ Agent append + 三方合并 + capture-never-clobber + 编辑感知延迟写——验证"用户编辑中系统写入不冲掉用户内容"
  5. 边界全覆盖：漏事件、同块冲突、编辑系统区、文档被删/移、归档停同步转只读快照、redis 不可用降级、非成员编辑归因——全部 fail-soft 不反噬

**Plans**: 6 plans（5 waves）

Plans:
- [ ] 83-01-PLAN.md — 地基：migration 0007（ProjectDoc subscribed/last_feishu_edit_at OQ-4 + ProjectDocBlockRevision capture 落点 OQ-2）+ doc_sync_diff.py 纯函数（block_id 结构化 diff + 三方合并，无 IO）+ conftest — SYNC-03/04
- [ ] 83-05-PLAN.md — read-through 缓存模块 doc_sync_cache.py（命中/失效 delete/redis 故障降级直读 DB）+ settings IGNORE_EXCEPTIONS + TTL — SYNC-05
- [ ] 83-02-PLAN.md — 飞书→Friday：drive.file.edit_v1 路由+normalizer+归因 + durable pull plumbing(QUEUE_DOC_SYNC) + subscribe_file + DocSyncService.pull + INV-6 guard + live-Feishu UAT 检查点（autonomous:false）— SYNC-01
- [ ] 83-03-PLAN.md — Friday→飞书：update_block/delete_blocks + DocSyncService.push（系统区 block 级增量，永不整篇 replace）+ per-doc 串行/debounce/退避 + 系统区写后钩子 — SYNC-02
- [ ] 83-04-PLAN.md — 冲突：三方合并 + capture-never-clobber（ProjectDocBlockRevision/ProjectMemoryRevision + 飞书评论）+ OQ-1 MEMORY 非成员 fail-soft 归因 + 编辑感知延迟写(OQ-3) + 乐观并发 rebase — SYNC-03/04
- [ ] 83-06-PLAN.md — 边界全集：TTL 兜底轮询 poll_project_docs_revisions + not-found→broken+一键重建 + 归档停同步退订转只读快照 + 非成员归因 + 限流退避，全 fail-soft — SYNC-06（强化 SYNC-01）

**Waves**: W1 = 83-01 ∥ 83-05（无依赖）；W2 = 83-02（依赖 01/05）；W3 = 83-03（依赖 02）；W4 = 83-04（依赖 02/03）；W5 = 83-06（依赖 02/03/04）

> 注：83-02 含 live-Feishu UAT 真机验证（A1/A3/A5），autonomous:false；真机 E2E（update/delete block A4 等）deferred 记 83-UAT.md，autonomous 链路以 respx/[ASSUMED] seam 覆盖。

### Phase 84: 项目工作台前端（Project Workbench UI）

**Goal**: 把项目做成可视、好用的在线工作区前端——大盘/人员/进度灯/5 文件实时编辑/外部依赖/全局+RAG 搜索
**Depends on**: Phase 82（实体）、Phase 83（同步，文件可实时看）
**Requirements**: WB-01~05
**Success Criteria** (what must be TRUE):

  1. 项目大盘——概览 + 人员带身份（PM/开发负责人/开发者/测试）+ 状态栏；借鉴工作区体验，加载稳定/空错兜底
  2. feature list 展示 + 进度灯（待开发/进行中/测试中/已完成，结合看板 WorkItem 状态）
  3. 5 文件在线查看 + 编辑（md 实时渲染，编辑经同步引擎回灌）+ 记忆编辑 + LLM 提议确认 UI
  4. 外部依赖/关联展示（原型/Spec/缺陷/UI 稿/评审/复盘 + 分支/知识/仓库/项目/PR）
  5. 项目列表按 空间/状态/成员 筛选 + 全局 + RAG 模糊搜索（搜到上下文→属哪个仓库/项目）+ 创建入口；全量 zh-CN、vue-tsc 绿、不破前端基线

**Plans**: 5 plans（3 waves）

Plans:
- [x] 82-01-PLAN.md — 数据层：扩 Project(visibility/feishu_folder_token) + 新 ProjectDoc/ProjectDocBlockMap/ProjectStateApi + 迁移 0006（纯 AddField+CreateModel，无回填）
- [x] 82-02-PLAN.md — 飞书供给：FeishuDocClient.create_folder + ProjectDocService(INV-6) + 后台串行建文件夹+5 文件（归因/broken）
- [x] 82-03-PLAN.md — 权限翻转 + 初始化 REST（visibility/space 改归/ProjectDoc 列表·重建/StateApi CRUD）+ DOC-06 互链与看板段
- [x] 82-04-PLAN.md — 前端 WS-01：侧边栏「项目」tab（首页↓空间↑）+ 列表按所选空间 localStorage 记忆 + API 接口补字段
- [x] 82-05-PLAN.md — WS-03 会话项目绑定改归/解绑（Conversation.bound_project）

**UI hint**: yes

### Phase 85: 项目上下文可读 + 分支绑定（Context Read + Branch Binding）

**Goal**: 让项目全部上下文可被任意来源 RAG/grep/file-read，并建立分支↔项目多绑定
**Depends on**: Phase 82/83（5 文件内容齐备）
**Requirements**: CTX-01/02, BIND-01/02
**Success Criteria** (what must be TRUE):

  1. 项目上下文物化为可 RAG + 可 grep + 可 file-read，前端 AI 对话 / MCP / skills 任意来源均可读取项目全部信息
  2. 项目（5 文件/记忆/工件）沉淀进交付知识图谱可索引 + 关联扩充；全局+RAG 搜索能定位上下文所属仓库/项目；新增召回写 `RetrievalTrace`
  3. `ProjectBranch` 多绑定模型（一项目多分支，前端可绑）+ 分支↔看板结合
  4. 分支名反查项目（扩展 `lookup_project_by_branch` 支持显式多绑定），多/无命中 fail-soft

**Plans**: TBD（plan-phase 拆分）

### Phase 86: IDE 上下文闭环（Context Loop）

**Goal**: 打通 Cursor/Claude Code/Codex 在某分支开发时自动拉项目上下文、会话结束回写沉淀的双向闭环
**Depends on**: Phase 85（分支绑定 + 上下文可读）
**Requirements**: HOOK-01~04
**Success Criteria** (what must be TRUE):

  1. 读路径：MCP 注入工具 + always-on rule（Cursor/Claude Code/Codex 三家通用，规则强制先反查项目+召回再编码）；Claude Code `UserPromptSubmit` 自动注入做增强（Cursor `beforeSubmitPrompt` 不能注入，故走 MCP+rule）
  2. 写路径：`stop` hook 组织上下文+用户改动 → `report_project_knowledge` 写回；MEMORY/RESEARCH 落 draft 人工确认，经质量门槛 + 归因（resolve_feishu_user）+ 脱敏
  3. STATE 结构化回写——会话结束把新增/改动 API 以结构化清单写入，跨会话/跨角色可读，带审计可回滚
  4. claude code runner 派发带项目上下文 + session 持久化（`SessionStore`→Redis）支持跨容器 resume；hook 无 PAT/未绑项目时静默跳过不阻断编码

**Plans**: TBD（plan-phase 拆分）

### Phase 87: 看板拆分节点 + 群 + 流式卡片（Board Split + Card）

**Goal**: 基于 feature list 自动拆子看板并经群聊卡片人机协同确认
**Depends on**: v0.15.0（飞书看板/建群/CardKit）+ Wave 1（项目）
**Requirements**: BOARD-01/02
**Success Criteria** (what must be TRUE):

  1. 看板拆分节点——Agent 基于 feature list 拆子看板（`work_item/create`，名=feature 名/描述=feature 原文，`relation_type=1` 关联项目跟踪）；工作流节点自动注册 + AI 会话可调；父子关系类型缺失时降级（建看板不挂父子 + 提示配置中心）
  2. 拉群 + 飞书 bot 入群 + 拆分结果流式卡片（「开始创建」/ 输入框+发送）
  3. 用户点「开始创建」直接建看板；用户输入信息则多轮重拆后重新发群

**Plans**: TBD（plan-phase 拆分）

### Phase 88: 智能业务关联仓库（Repo Association）

**Goal**: 基于 feature list + 拆分看板，多轮交互式拟定并校验业务↔仓库关联
**Depends on**: Phase 87（看板拆分结果）
**Requirements**: REPO-01/02
**Success Criteria** (what must be TRUE):

  1. 智能仓库关联——结合知识库（活跃度/功能梳理）+ RAG 多轮 + Agent 自处理，发卡片引导式多轮澄清/确认涉及仓库（含用户自校验）
  2. 用户确认仓库后逐仓自校验（基于确认仓库再验证业务适配性，发现不符可回退重确认）+ 最终卡片确认

**Plans**: TBD（plan-phase 拆分）

### Phase 89: 技术方案深化 + 建分支绑项目（Tech Plan + Branch）

**Goal**: 产出 per-repo + overall 技术方案，支持修订回路与容器挂起，方案确认后建分支并绑项目
**Depends on**: Phase 88（仓库关联确认）+ v0.7/v0.8（PlanOrchestration/多仓编码）
**Requirements**: PLAN-01~04
**Success Criteria** (what must be TRUE):

  1. per-repo + overall 技术方案——每仓负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature list 不清处/与现功能冲突；含跨仓上下文；发卡片多轮校验澄清
  2. 方案修订回路——执行中发现要改/增/删仓库 → 「调研问题发现」卡片 → 更新方案/创建补充修订 + 同步改仓库关联
  3. 容器 5 分钟无回复挂起/暂存，用户卡片回复后 resume（session 持久化）继续到终态
  4. 方案确认后按方案（含分支名）对每仓建分支并推送 + 绑定 仓库↔分支↔项目，回接 IDE 闭环

**Plans**: TBD（plan-phase 拆分）

<details>
<summary>✅ v0.15.0 项目（交付上下文聚合根）(Phases 76–81) — SHIPPED 2026-06-26 — 审计 passed</summary>

- [x] Phase 76: 命名腾挪（Project→Space 重构前置） (1/1 plans) — RENAME-01/02 — completed 2026-06-25
- [x] Phase 77: 项目聚合根 + 身份映射 + 成员协作 (1/1 plans) — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25
- [x] Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 (1/1 plans) — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25
- [x] Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 (1/1 plans) — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26
- [x] Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 (1/1 plans) — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26
- [x] Phase 81: Cursor 回流 + 前端项目工作台 (1/1 plans) — CURSOR-01~03, UI-01~03 — completed 2026-06-26

完整阶段详情见 [milestones/v0.15.0-ROADMAP.md](./milestones/v0.15.0-ROADMAP.md)；里程碑审计 passed（38/38 需求、integration_ok）见 [milestones/v0.15.0-MILESTONE-AUDIT.md](./milestones/v0.15.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.15.0（Phases 1–81）均已交付。当前进行中：**🚧 v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）（Phases 82–89，8 阶段 / 37 需求，planning 2026-06-26）**。

| Phase | Requirements | Wave | Status |
|-------|--------------|------|--------|
| 82. 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件 | WS-01~04, DOC-01~06 | 1 | ✅ Complete |
| 83. 飞书文档双向同步引擎 | SYNC-01~06 | 1 | ☐ Pending |
| 84. 项目工作台前端 2.0 | WB-01~05 | 1 | ☐ Pending |
| 85. 项目上下文可读 + 分支绑定 | CTX-01/02, BIND-01/02 | 2 | ☐ Pending |
| 86. IDE 上下文闭环（hooks） | HOOK-01~04 | 2 | ☐ Pending |
| 87. 看板拆分节点 + 群 + 流式卡片 | BOARD-01/02 | 3 | ☐ Pending |
| 88. 智能业务关联仓库 | REPO-01/02 | 3 | ☐ Pending |
| 89. 技术方案深化 + 建分支绑项目 | PLAN-01~04 | 3 | ☐ Pending |

**Execution order:** 82 → 83 → 84（Wave 1 地基，必须先全绿）→ 85 → 86（Wave 2 闭环）→ 87 → 88 → 89（Wave 3 流水线，线性）。Wave 1 是最小可交付；Wave 2/3 依赖 Wave 1，可在本里程碑内顺序推进或按需拆 v0.17/v0.18。

**UI 触面（标 UI hint）:** Phase 82（侧边栏 tab/文件落地）、Phase 84（项目工作台集中前端，`/gsd-ui-phase` 应介入）。83/85/86/87/88/89 以后端 + 节点 + 同步/卡片为主。

**关键约束 / 设计底座（plan-phase 必读）:** DB canonical + 飞书文档双向镜像（永不整篇覆盖、block 级 + 分区 + append + 编辑感知延迟写）；block_id 结构化匹配代替整篇 diff；默认全员可读+visibility 开关、写仅成员；STATE/MILESTONES 活计算+结构化+补充段；最大化复用 v0.15.0 地基（`initiatives`/`ProjectService`/`ProjectMemory`/context packer/MCP/`feishu_doc.py`）；新增 LLM 赋 `call_source`、新增召回写 `RetrievalTrace`、脱敏不可绕过、后台任务带 `initiated_by_user_id`、写入收口 INV-6。完整方案见 `.planning/project-workspace/MILESTONE-PROPOSAL.md`。

| Phase | Requirements | Status |
|-------|--------------|--------|
| 76. 命名腾挪（Project→Space 重构前置） | RENAME-01/02 | ✅ Complete |
| 77. 项目聚合根 + 身份映射 + 成员协作 | PROJ-01~05, IDENT-01, MEMBER-01~03 | ✅ Complete |
| 78. 飞书触发建项目 + 看板枚举 + 工作项组合 | FSPROJ-01~03, COMPOSE-01/02 | ✅ Complete |
| 79. 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 | ARTIFACT-01~05, KLINK-01/02 | ✅ Complete |
| 80. 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 | MEM-01~04, RECALL-01~03, MR-01/02 | ✅ Complete |
| 81. Cursor 回流 + 前端项目工作台 | CURSOR-01~03, UI-01~03 | ✅ Complete |

**Execution order:** 76 → 77 → 78 → 79 → 80 → 81（线性）。依赖链：76（命名腾挪）是硬前置，必须全绿再推进；77（聚合根 + 身份 + 成员）立地基；78（飞书触发 + 组合）与 79（工件 + 知识关联）分别构建组合与依赖；80（记忆 + MR + 召回）把上下文接通会话；81（Cursor 回流 + 前端工作台）打通双向闭环与可视。

**UI 触面（标 UI hint）:** Phase 77（项目创建/成员）、Phase 79（工件查看/类型管理）、Phase 80（记忆编辑/召回）、Phase 81（项目工作台集中前端）。`/gsd-ui-phase` 应介入 81，可选介入 77/79/80。76/78 以后端为主。

**关键约束 / 设计底座（plan-phase 必读）:** 命名已锁定大重构（Project→Space，76 独立前置）；不做迭代实体（另一迭代=新项目）；记忆为自由文本 + 时间戳/贡献者、人工为主 + LLM 提议确认；工件文字载体可全文 RAG、UI 稿仅元数据；飞书无整板枚举 API（经子项字段派生）；身份映射是主R/协作/归因/Cursor 上报的前置；复用 `KnowledgeEntity/Edge` 做项目↔知识/项目间关联、复用 `delivery.WorkItem` 做 story/缺陷、复用 `delivery_knowledge` 召回；脱敏不可绕过 + 后台任务带 `initiated_by_user_id` + 新增 LLM/召回埋点。完整方案见 `.planning/project-aggregate/MILESTONE-PROPOSAL.md`。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
