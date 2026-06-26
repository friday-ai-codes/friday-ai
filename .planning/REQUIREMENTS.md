# Requirements: Friday AI

**Defined:** 2026-06-26
**Core Value:** 把"项目"做成团队真正用的**在线协作工作区**——人在飞书写、Agent/Cursor 在系统写，双向实时同步不互相冲掉；项目上下文可被任意来源读取/召回/回写；并把"feature list → 拆看板 → 关联仓库 → 技术方案 → 建分支"做成人机协同的交付流水线。里程碑 v0.16.0 在 **8 个 Phase（82–89）** 内交付。

> 完整设计与调研基线见 `.planning/project-workspace/MILESTONE-PROPOSAL.md`；阶段拆分见 `.planning/ROADMAP.md`（Phases 82–89）。本里程碑构建在 v0.15.0（项目聚合根）之上，复用其全部领域地基。

## v1 Requirements

Milestone v0.16.0 项目工作区。每条映射到一个 Phase（见 Traceability）。

### 项目工作区与权限（WS）

- [ ] **WS-01**: 前端左侧菜单新增「项目」入口（位于「首页」之下、「空间」之上）；项目作为工作区一等入口，点进为项目工作台
- [ ] **WS-02**: 权限翻转——默认全员可读、可对任意项目发起会话（`visibility=public_org`），新增项目级 `visibility` 开关（public_org / members_only）；**写（记忆/STATE/成员/文件）仅项目成员**；脱敏闸不可绕过
- [ ] **WS-03**: 项目可与空间解绑 / 改归到其他空间；AI 对话的项目绑定可解绑 / 改归（`Conversation.bound_project`）
- [ ] **WS-04**: 每个项目在飞书建专属文件夹（`create_folder`，父=Space `feishu_doc_folder_token`），5 个工作区文件统一创建在该文件夹下；DB 存 `feishu_folder_token` + 各文件 doc token，文件不乱放

### 五个工作区文件（DOC）

- [ ] **DOC-01**: MEMORY——复用条目式 `ProjectMemory`（每条带时间戳/贡献者 + revision + draft），渲染为「文件」视图；积累项目知识/记忆
- [ ] **DOC-02**: STATE——活计算派生区（API/前端看板/e2e/UAT 状态）+ **结构化「已完成 API 清单」**（method/path/params/status）+ 自由文本备注段
- [ ] **DOC-03**: MILESTONES——以子看板（`delivery.WorkItem`）实时派生（状态/风险/反馈/验收）+ 人写补充段；子看板即项目里程碑
- [ ] **DOC-04**: RESEARCH——项目调研长文（业务方依赖、技术选型/决策、灰区讨论），共享进上下文
- [ ] **DOC-05**: PREFLIGHT——项目前置风险/前置修复清单（仿 `PREFLIGHT.md` 形态，agent 可产「待确认」建议 draft），辅助 LLM 规避问题
- [ ] **DOC-06**: 5 文件互链（文档头部导航区链到其余 4 文件 + 看板 + Friday 项目页）；看板描述追加「项目工作区」段，可从看板打开文件夹 / 5 文件 / Friday 项目页

### 飞书文档双向同步（SYNC）

- [ ] **SYNC-01**: 飞书→Friday——按文件 `subscribe` + 现有事件链路路由 `drive.file.edit_v1`（不含正文）→ 回拉正文；进行中项目 TTL 轮询兜底防漏事件
- [ ] **SYNC-02**: Friday→飞书——DB 写触发 block 级增量推送（`docx blocks` API），**永不整篇覆盖**
- [ ] **SYNC-03**: block_id 结构化匹配（新增/编辑/删除）+ last-synced 快照 + (block_id↔DB 条目/段) 映射表，**代替整篇文本 diff**
- [ ] **SYNC-04**: 冲突处理——区段所有权分区（系统区/人工区互不写）+ Agent append + 三方合并（base/theirs/ours）+ capture-never-clobber + 编辑感知延迟写（anti-抖动）；保证用户在飞书编辑不被冲掉
- [ ] **SYNC-05**: 及时性 + 缓存——redis read-through，写时/收事件失效，TTL 兜底，redis 不可用降级直读 DB
- [ ] **SYNC-06**: 边界/失败模式全覆盖——漏事件、同块冲突、编辑系统区、文档被删/移、归档停同步转只读快照、限流退避、非成员编辑归因；全部 fail-soft 不反噬主流程

### 项目工作台前端（WB）

- [ ] **WB-01**: 项目大盘——概览 + 人员（带身份：PM/开发负责人/开发者/测试）+ 状态栏；借鉴「工作区」体验
- [ ] **WB-02**: feature list 展示 + 进度灯（待开发/进行中/测试中/已完成，结合看板 WorkItem 状态点亮）
- [ ] **WB-03**: 5 文件在线查看 + 编辑（md 实时渲染）+ 记忆编辑 + LLM 提议确认 UI
- [ ] **WB-04**: 外部依赖/关联展示——原型/Spec/缺陷/UI 稿/评审/复盘（复用 `Artifact`）+ 关联分支/知识/仓库/项目/PR
- [ ] **WB-05**: 项目列表——按 空间/状态/成员 筛选过滤 + 全局 + RAG 模糊搜索 + 创建入口（手动创建项目、绑定看板）

### 上下文可读与分支绑定（CTX / BIND）

- [ ] **CTX-01**: 项目上下文物化为可 RAG + 可 grep + 可 file-read，任意来源（前端 AI 对话 / MCP / skills）均可读取项目全部信息
- [ ] **CTX-02**: 项目（含 5 文件/记忆/工件）沉淀进交付知识图谱可索引 + 关联扩充；全局+RAG 搜索能搜到某上下文属于哪个仓库/项目
- [ ] **BIND-01**: 分支↔项目多绑定模型（`ProjectBranch`，一项目多分支、前端可绑）+ 分支↔看板结合
- [ ] **BIND-02**: 分支名反查项目（扩展 `lookup_project_by_branch` 支持多分支显式绑定），多/无命中 fail-soft 返回候选

### IDE 上下文闭环（HOOK）

- [ ] **HOOK-01**: 读路径——MCP 注入工具 + always-on Cursor/Claude Code rule（强制先反查项目+召回再编码，三家通用）；Claude Code `UserPromptSubmit` 自动注入做增强
- [ ] **HOOK-02**: 写路径——`stop` hook 组织上下文+用户改动 → `report_project_knowledge` 写回；MEMORY/RESEARCH 落 draft 人工确认，全部经质量门槛 + 归因 + 脱敏
- [ ] **HOOK-03**: STATE 结构化回写——会话结束把新增/改动 API 以结构化清单（method/path/params/status）写入，跨会话/跨角色（前后端）可读，带审计可回滚
- [ ] **HOOK-04**: claude code runner 派发带项目上下文 + session 持久化（`SessionStore`→Redis）支持跨容器 resume

### 看板拆分（BOARD）

- [ ] **BOARD-01**: 看板拆分节点——基于 feature list 用 Agent 拆出子看板（`work_item/create`，名=feature 名、描述=feature 原文、`relation_type=1` 关联项目跟踪）；工作流节点 + AI 会话可调用
- [ ] **BOARD-02**: 拆分流程——拉群 + 飞书 bot 入群 + 拆分结果流式卡片（「开始创建」/ 输入框+发送）；用户输入则多轮重拆后重新发群

### 智能业务关联仓库（REPO）

- [ ] **REPO-01**: 智能仓库关联——基于 feature list+拆分看板，结合知识库（活跃度/功能梳理）+ RAG 多轮 + Agent 自处理，发卡片引导式多轮澄清/确认涉及仓库
- [ ] **REPO-02**: 用户确认仓库后逐仓自校验（基于确认仓库再验证业务适配性）+ 最终卡片确认

### 技术方案深化（PLAN）

- [ ] **PLAN-01**: per-repo + overall 技术方案——每仓负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature list 不清处/与现功能冲突；含跨仓上下文
- [ ] **PLAN-02**: 方案修订回路——执行中发现要改/增/删仓库 → 「调研问题发现」卡片 → 更新方案/创建补充修订 + 同步改仓库关联（多轮，优雅处理）
- [ ] **PLAN-03**: 容器资源优化——单仓任务遇阻等待用户时，5 分钟无回复挂起/暂存容器；用户卡片回复后 resume（session 持久化）继续
- [ ] **PLAN-04**: 方案确认后按方案（含分支名）对每个仓库建分支并推送 + 绑定项目（仓库↔分支↔项目），回接 IDE 闭环

## Future Requirements

后续里程碑（v2，本期不做）：

- **PROJX-01**: UI 稿多模态 / figma API 接入正文召回
- **PROJX-02**: 结构化记忆 + 时效降权 + 矛盾消解
- **PROJX-03**: 记忆全自动提炼（无人工确认）
- **PROJX-04**: Cursor / Claude Code 专用插件 / hook 主动行为采集
- **PROJX-05**: 项目级看板可视 / 燃尽 / 进度统计
- **PROJX-06**: 产品在系统内对话调研 → 直接产出 feature list 并关联项目

## Out of Scope

| Feature | Reason |
|---------|--------|
| 飞书文档跨系统亚秒级 OT 实时协同 | 飞书文档只能经 API 读写，无法接入其 OT 引擎；本期按"秒级最终一致 + block 级不冲突"交付 |
| 产品在系统内产出 feature list | 用户明示本期先用外部产出的 feature list；系统内调研产出留 v2（PROJX-06） |
| UI 稿正文 RAG / 多模态 | UI 稿仅存元数据，多模态留 v2（PROJX-01） |
| 记忆全自动写入（无人确认） | LLM/hook 仅产 draft，人工确认入库，防共享记忆污染 |
| Codex 原生 hook 注入上下文 | Codex hook 能力弱，按"仅 MCP+rules"对待 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WS-01 | Phase 82 | ☐ Pending |
| WS-02 | Phase 82 | ☐ Pending |
| WS-03 | Phase 82 | ☐ Pending |
| WS-04 | Phase 82 | ☐ Pending |
| DOC-01 | Phase 82 | ☐ Pending |
| DOC-02 | Phase 82 | ☐ Pending |
| DOC-03 | Phase 82 | ☐ Pending |
| DOC-04 | Phase 82 | ☐ Pending |
| DOC-05 | Phase 82 | ☐ Pending |
| DOC-06 | Phase 82 | ☐ Pending |
| SYNC-01 | Phase 83 | ☐ Pending |
| SYNC-02 | Phase 83 | ☐ Pending |
| SYNC-03 | Phase 83 | ☐ Pending |
| SYNC-04 | Phase 83 | ☐ Pending |
| SYNC-05 | Phase 83 | ☐ Pending |
| SYNC-06 | Phase 83 | ☐ Pending |
| WB-01 | Phase 84 | ☐ Pending |
| WB-02 | Phase 84 | ☐ Pending |
| WB-03 | Phase 84 | ☐ Pending |
| WB-04 | Phase 84 | ☐ Pending |
| WB-05 | Phase 84 | ☐ Pending |
| CTX-01 | Phase 85 | ☐ Pending |
| CTX-02 | Phase 85 | ☐ Pending |
| BIND-01 | Phase 85 | ☐ Pending |
| BIND-02 | Phase 85 | ☐ Pending |
| HOOK-01 | Phase 86 | ☐ Pending |
| HOOK-02 | Phase 86 | ☐ Pending |
| HOOK-03 | Phase 86 | ☐ Pending |
| HOOK-04 | Phase 86 | ☐ Pending |
| BOARD-01 | Phase 87 | ☐ Pending |
| BOARD-02 | Phase 87 | ☐ Pending |
| REPO-01 | Phase 88 | ☐ Pending |
| REPO-02 | Phase 88 | ☐ Pending |
| PLAN-01 | Phase 89 | ☐ Pending |
| PLAN-02 | Phase 89 | ☐ Pending |
| PLAN-03 | Phase 89 | ☐ Pending |
| PLAN-04 | Phase 89 | ☐ Pending |

**Coverage:**

- v1 requirements: 37 total
- Mapped to phases: 37
- Completed: 0
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-26 — milestone v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）（8 Phase 82–89）*
