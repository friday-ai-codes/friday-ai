# 里程碑方案：v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）

**定稿：** 2026-06-26
**状态：** Proposal（立项草案，供 `plan-phase` 拆解 plan 使用）

> 本文是 v0.16.0 的设计与调研基线。需求清单见 `.planning/REQUIREMENTS.md`，阶段拆分见 `.planning/ROADMAP.md`（Phases 82–89）。本里程碑在 v0.15.0「项目（交付上下文聚合根）」之上，把"项目"升级为**真正的在线协作工作区**，并打通飞书文档双向实时同步、IDE 上下文双向闭环、以及 feature list → 交付的流水线。

---

## 0. 一句话目标

把"项目"做成团队真正用的**在线协作工作区**：每个项目有一个飞书文件夹 + 5 个固定工作区文件（MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT），**人在飞书里写、Agent/Cursor 在系统里写，双向实时同步且不互相冲掉**；项目上下文可被任意来源（前端 AI 对话 / MCP / skills / IDE hooks）读取与召回、可沉淀回写；并把"产品交 feature list → 拆看板 → 关联仓库 → 技术方案 → 建分支"做成一条带人机协同卡片的交付流水线。

---

## 1. 与 v0.15.0 的关系（复用 / 增强 / 净新）

v0.15.0 已落地领域地基，本期**严禁重复造**，只增强 + 补净新：

- **直接复用**：`initiatives` app（`Project` 状态机 developing/archived/terminated、`ProjectService`、`ProjectMember` 角色、`Artifact`/`ArtifactType`、`ProjectMemory`+revision+draft、`MergeRequest`、`ProjectWorkItemLink`、`ProjectRelation`）、`resolve_feishu_user`、context packer（grep+RAG+token 预算+fail-closed+RetrievalTrace）、`Conversation.bound_project`、`lookup_project_by_branch`/`report_project_knowledge` MCP、cursor_rules API、KnowledgeEdge KLINK、`feishu_doc.py`（block API/create_document/folder_token）、`feishu.py::update_work_item_fields`、git-webhook。
- **增强/改设**：权限从"成员 fail-closed"翻成"默认全员可读可问 + visibility 开关、写仍成员"；MEMORY 由纯 DB 升级为"DB 条目式 + 飞书文档双向镜像"；`/projects` 前端从最小创建升级为完整工作台 + 侧边栏 tab；分支反查升级为显式多绑定；技术方案（v0.7/v0.8）增强为 feature-list 输入 + 卡片 HITL + 修订回路 + 容器挂起。
- **净新增**：5 文件工作区模型 + **飞书文档双向实时同步引擎**（本期最大硬骨头）、每项目飞书文件夹、IDE hooks 闭环、看板拆分节点、智能仓库关联交互回路。

---

## 2. 第一性原理 / 设计立场

1. **项目=工作区，飞书文档=人类编辑面，Friday DB=系统真相源。** 三者通过同步引擎保持一致，但 canonical 永远是 DB（保证 RAG/grep/权限/审计/版本/原子写都成立）。
2. **永不整篇覆盖。** 跨系统冲突的根因是"整篇 replace"；本期所有系统侧写入都是 **block 级 + 分区 + append**，配合"编辑感知延迟写"，从机制上消灭"用户编辑被冲掉"。
3. **活计算优先于手写大文件。** STATE/MILESTONES 的可计算部分做成实时派生视图，只把人写的判断留成可编辑段——规避 `POLISH-PLAN.md` 自列的"巨型文件没人维护"反模式。
4. **观测/脱敏不可绕过。** 新增 LLM 赋 `call_source`、新增召回写 `RetrievalTrace`、飞书正文/hook 上传/webhook 原始 payload 一律脱敏、后台/外部触发带 `initiated_by_user_id`、写入收口单一 service（INV-6）。
5. **fail-soft 不反噬主流程。** 同步/hook/飞书事件任何一环失败都不得阻断用户在飞书编辑、不得阻断用户在 IDE 编码。

---

## 3. 四个已锁定决策（用户确认）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 5 文件真相源 | **DB canonical + 飞书文档双向镜像 + redis 纯读缓存**；取消"归档才进 DB"（DB 恒为源，归档=停止刷新缓存/停同步转只读快照） |
| 2 | 权限 | **默认全员可读可问（public_org）+ 项目级 `visibility` 开关 + 写仅成员**；脱敏闸不松；非成员可读可问但不可贡献记忆 |
| 3 | MEMORY 模型 | **保留条目式 `ProjectMemory`**（满足"每条带时间戳/贡献者"）+ 渲染为文件视图；飞书编辑按 block_id 匹配落 revision，**不做整篇 diff** |
| 4 | STATE/MILESTONES | **活计算派生 + 结构化字段 + 自由文本补充段**；同时镜像到飞书文档允许人编辑补充段 |

---

## 4. 飞书文档双向同步引擎（本期核心，详设）

### 4.1 同步链路（双向 + 及时 + 兜底）
- **飞书→Friday**：现有飞书事件链路按 `event_type` 路由 `drive.file.edit_v1`（秒级 webhook，**不含正文**）→ 回拉 `get_document_content` blocks。漏事件兜底：进行中项目 TTL 轮询比对 revision。
- **Friday→飞书**：DB 写 → 异步任务做 **block 级**增量更新（`/docx/v1/documents/{id}/blocks/...`），**永不整篇 replace**。
- **缓存**：redis read-through，写时/收事件时失效，TTL 兜底；redis 不可用降级直读 DB（best-effort）。
- **诚实边界**：秒级**最终一致**，非亚秒 OT；飞书 API 限流（create_folder 5QPS/不可并发、文档块写有频控）→ 退避 + per-doc 串行队列。

### 4.2 防"编辑被冲掉/抖动"四机制（叠加生效）
1. **永不整篇覆盖，只写 block 级**——系统写 A 块、用户敲 B 块，飞书自身 OT 合并不同块的并发写。
2. **区段所有权分区**——每文件切"系统维护区 / 人工编辑区"，系统只写系统区、人只写人工区，物理不相交。
3. **Agent 写一律 append**——hook/agent 只追加新 block，绝不就地改既有 block。
4. **编辑感知延迟写**——推送前探测"文档近 N 秒是否有人编辑"（drive 事件/last-edit 时间），活跃则系统写入入队、静默窗口再落；带乐观并发（last-synced revision 校验，变了先 rebase 再写）。

### 4.3 "用户编辑过了怎么生成 diff"——block_id 结构化匹配（非整篇文本 diff）
每个文件维护 **last-synced 快照 + (飞书 block_id ↔ DB 条目/段 id) 映射表**。收到事件回拉 blocks 后逐块比对：

```
新 block_id（映射表无）        → 用户新增一条 → DB 建条目/段
已知 block_id、内容变了        → 用户编辑该条 → DB 落新 revision（留史）
映射表有、飞书已无             → 用户删除     → DB 标 superseded（不真删）
→ 更新 last-synced 快照 + 映射表
```

- 飞书 docx block_id 稳定（改文字 id 不变），所以**不靠脆弱全文 diff，靠结构化逐块匹配**；飞书自己的 diff 归飞书，我们只认"哪条结构变了"。
- 真·同块冲突（罕见）→ 三方合并（base=last-synced / theirs=飞书 / ours=DB）：不相交自动并；相交执行 **capture-never-clobber**（落败方存 revision + 标记 + 飞书发评论提示），绝不静默丢。
- 块被拆分/合并导致 block_id 漂移的边角：回退"就近匹配 + capture"，不丢内容。

### 4.4 五文件最终形态

| 文件 | canonical | 系统区（系统写/人只读） | 人工区（人写/系统不碰） | Agent 写法 | 飞书镜像 |
|---|---|---|---|---|---|
| MEMORY | DB 条目式（复用 v0.15.0） | — | 条目流 | append 条目(draft) | 双向（按 block_id 落 revision） |
| STATE | DB（派生+结构化+备注） | 派生区 + API 清单 | 备注段 | append API 条目 | 双向（人编辑仅备注段） |
| MILESTONES | DB 派生自 WorkItem | 子看板派生区 | 风险/验收补充段 | 系统派生 | 双向（人编辑仅补充段） |
| RESEARCH | DB 长文 | "AI 建议(待确认)"区 | 正文（决策/选型/灰区） | append draft block | 双向 |
| PREFLIGHT | DB 风险条目（仿 PREFLIGHT.md） | "AI 发现风险(待确认)"区 | 风险条目正文 | append draft block | 双向 |

---

## 5. 文件夹与互链结构

- 每项目用 `drive/v1/files/create_folder`（父 = Space `feishu_doc_folder_token`）建专属文件夹，token 存 `Project.feishu_folder_token`；5 文件用 `create_document(folder_token=该文件夹)` 建于其下——**不乱放**。
- DB 侧每文件存 `feishu_document_id` + `feishu_doc_token`，Friday↔飞书双向定位。
- 每文档头部"导航区"block：链到其余 4 文件 + 看板 + Friday 项目页。
- 看板可打开：`update_work_item_fields` 往"项目跟踪"看板**描述**追加"📁 项目工作区"段（文件夹 + 5 文件 + Friday 项目页链接）。
- 边角：Space 单层文件夹上限 1500，超限按 Space 分桶嵌套；文档被用户手删/移出文件夹 → 回拉报 not-found → 标 broken + 通知 + 可一键重建。

---

## 6. 数据模型建议（plan-phase 细化）

- **复用**：`Project`、`ProjectMember`、`ProjectMemory(+Revision+Draft)`、`Artifact/ArtifactType`、`MergeRequest`、`ProjectWorkItemLink`、`ProjectRelation`。
- **扩展 `Project`**：`visibility`(public_org/members_only)、`feishu_folder_token`。
- **新增 `ProjectDoc`**（5 文件的统一容器，type=memory/state/milestones/research/preflight）：`project` FK + `doc_type` + `feishu_document_id`/`feishu_doc_token` + `last_synced_revision` + `last_synced_snapshot`(或快照表) + 时间戳；MEMORY 的条目仍落 `ProjectMemory`，`ProjectDoc(memory)` 只持有飞书映射与渲染。
- **新增 `ProjectDocBlockMap`**：`doc` FK + `feishu_block_id` + `db_ref`(条目/段 id) + `section`(system/human) + `content_hash` —— 同步引擎的映射表。
- **新增 `ProjectBranch`**：`project` FK + `repository` FK + `branch_name` + `source`(manual/plan/coding) + 时间戳，唯一(project,repository,branch_name)。
- **新增 `ProjectStateApi`**（STATE 的结构化 API 清单）：`project` FK + `method`+`path`+`params`(JSON)+`status` + 贡献来源。
- 关系/知识沿用 `KnowledgeEdge`；新增 LLM/召回点按规范埋点。

---

## 7. IDE 上下文闭环（hooks 三家差异 + 正确架构）

**调研结论（已查证）**：
- **Cursor**（1.7+）：有 `hooks.json`（`beforeSubmitPrompt`/`stop`/`afterFileEdit`/`beforeMCPExecution`…），自动映射 Claude Code hook 名。**关键限制：`beforeSubmitPrompt` 只能放行/拦截，不能注入上下文。**
- **Claude Code**：`UserPromptSubmit` **能注入**上下文（stdout）；hooks 成熟。
- **Codex**：hooks 最弱，按"仅 MCP+rules"对待。

**正确架构**：
- **读路径（注入上下文）**：主走 **MCP 工具 `lookup_project_by_branch`（扩多分支）+ 一条 always-on Cursor/CC rule**（强制"先反查项目+召回再编码"）——三家全通；Claude Code 额外用 `UserPromptSubmit` 自动注入做增强。**不把注入押在 Cursor hook 上。**
- **写路径（会话结束回写）**：`stop` hook（三家都有）→ 组织上下文+用户改动 → 调 `report_project_knowledge` → 落 **draft + 质量门槛 + 归因(resolve_feishu_user)+脱敏**；STATE 走**结构化 API 清单**直写（带审计可回滚），MEMORY/RESEARCH 走 draft 人工确认。
- **容器侧**：claude code runner 派发带项目上下文；**session 持久化用 SessionStore→Redis**（session JSONL 本地、跨容器不共享，必须镜像）支持冷启动 resume。

---

## 8. feature list 交付流水线（增强 v0.7/v0.8）

输入从"原始需求"升级为 **feature list**（见 `feature-list-demo.md`：82KB 富文档，需结构化抽取 模块→功能点→验收项，分块 + token 预算）。流水线：

1. **看板拆分节点**（净新）：feature list → 子看板（`work_item/create`，名=feature 名、描述=feature 原文，`relation_type=1` 关联项目跟踪）；工作流节点 + AI 会话可调。
2. **拉群 + bot 入群 + 流式卡片**（复用 v0.11 CardKit + v0.5x 建群）：拆分结果发群，"开始创建 / 输入框+发送"；用户输入 → 多轮重拆。
3. **智能仓库关联**（增强 RepoRouterV2 + 卡片 HITL）：知识库(活跃度/功能梳理)+RAG 多轮+Agent 自处理 → 卡片澄清/确认 → 用户确认仓库后**逐仓自校验** → 最终卡片确认。
4. **技术方案深化**（增强 v0.7 PlanOrchestration）：per-repo（负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature list 不清/与现功能冲突）+ overall 整体方案；**修订回路**——发现要改/增/删仓库 → "调研问题发现"卡片 → 更新方案/补充修订 + 改仓库关联（多轮）；**容器 5min 无回复挂起**（finish turn→停容器→回复后 SessionStore resume，复用 v0.8 callback resume + v0.12 durable）。
5. **建分支绑项目**（复用 v0.8 git/branch + 新 `ProjectBranch`）：方案确认 → 按方案建分支并推送 → 绑定 仓库↔分支↔项目，回接 IDE 闭环。

---

## 9. 边界状态 / 失败模式（必须在 plan/execute 覆盖）

| 场景 | 处理 |
|---|---|
| 飞书事件漏发 | 进行中项目 TTL 轮询比对 revision 兜底 |
| 同块两边都改 | 三方合并 + capture-never-clobber（落败存 revision + 评论提示） |
| 用户编辑了"系统区" | 不阻止，捕获为修订 + 飞书评论提示"此段系统维护，请写到 XX 区" |
| 文档被用户手删/移出文件夹 | 回拉 not-found → 标 broken + 通知 + 一键重建 |
| 项目归档/终止 | 停双向同步 + 停 subscribe，文档转**只读快照入 DB**（不再刷新缓存） |
| 非成员在飞书编辑文档 | 飞书侧有权限即可编辑；我们 fail-soft 接受 + 归因(operator→resolve_feishu_user，未映射 system) |
| 飞书限流 | 退避重试 + per-doc 串行队列 + create_folder 不并发 |
| redis 不可用 | 降级直读 DB，缓存 best-effort |
| 分支名反查不到/多命中 | fail-soft 返回空或候选列表，不抛、不阻断编码 |
| hook 无 PAT/分支未绑项目 | 静默跳过，绝不阻断用户编码 |
| feature list 过大(82KB) | 结构化抽取 + 分块 + token 预算降级 |
| 看板父子关系类型未配 | 拆分前检测 relation 定义，缺则降级"建看板不挂父子 + 提示去配置中心" |
| 容器 resume 找不到 session | SessionStore 未命中 → 用应用态(方案+用户回复)重灌新 session（官方推荐兜底） |

---

## 10. 外部依赖调研结论（全部已查证可行）

| 依赖 | 结论 | 约束 |
|---|---|---|
| 飞书文档变更事件 | ✅ `drive.file.edit_v1` | 按文件 `subscribe`（app 即 owner 可订）、单回调地址多路复用、事件不含正文需回拉、应用须发布 |
| 飞书新建文件夹 | ✅ `drive/v1/files/create_folder` | 5QPS/不可并发、单层 1500 上限、`drive:drive`/`space:folder:create` |
| 飞书块级写 | ✅ `docx/v1/documents/{id}/blocks/...`（稳定 block_id） | 频控；用 children/descendant 增量写 |
| 看板拆分（建工作项+父子） | ✅ `work_item/create` + `relation_type=1` + 子任务 API | plugin_token+user_key 鉴权；父子关系类型可能需配置中心预配 |
| Cursor hooks | ✅ 有，但 `beforeSubmitPrompt` 不能注入上下文 | 注入走 MCP+rules；CC `UserPromptSubmit` 可注入 |
| 容器 resume | ✅ `--resume`/SDK resume | session 本地态 → 必须 SessionStore(Redis) 或重灌状态、cwd 须一致 |

---

## 11. 阶段总览（8 Phase / 3 Wave，详见 ROADMAP Phases 82–89）

**Wave 1 — 工作区实体 + 双向同步地基（最小可交付）**
- Phase 82：项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件落地（DB canonical）+ 侧边栏 tab
- Phase 83：飞书文档双向同步引擎（subscribe + block_id 结构化匹配 + 三方合并 + 编辑感知延迟写 + 边界全集）
- Phase 84：项目工作台前端 2.0（大盘/人员/feature 进度灯/5 文件查看编辑/外部依赖/全局+RAG 搜索）

**Wave 2 — 上下文闭环（IDE hooks）**
- Phase 85：项目上下文可 RAG+grep+file-read（物化）+ 分支↔项目多绑定
- Phase 86：IDE 上下文闭环（MCP 注入 + rules + CC/Cursor/Codex hooks 读写 + session 持久化 + runner 派发带上下文）

**Wave 3 — feature list 交付流水线**
- Phase 87：看板拆分节点 + 拉群 + 流式卡片（多轮拆分）
- Phase 88：智能业务关联仓库（多轮交互 + 逐仓自校验 + 卡片确认）
- Phase 89：技术方案深化（per-repo+overall + 修订回路卡片 + 5min 挂起/resume + 按方案建分支绑项目）

> **执行/拆分建议**：Wave 1（82–84）是本里程碑的最小可交付地基，必须先做；Wave 2（85–86）、Wave 3（87–89）依赖 Wave 1，可在本里程碑内顺序推进，也可按需拆成 v0.17/v0.18 独立发布。

---

## 12. 观测与安全强制项

- 新增 LLM（看板拆分、仓库关联、方案、hook 提炼）→ 赋 `call_source`（LOGGING-SPEC §4.1 登记新值）+ 上报请求/token/TTFT/上游错误码。
- 新增召回（项目搜索、MCP 反查注入、hook 注入）→ 写 `RetrievalTrace` + 条数/分层耗时/score，MCP 与 AI 对话两条链都覆盖。
- 飞书文档正文 / hook 上传 / webhook 原始 payload → `redact_secrets_in_text` / `redact_for_ledger` 不可绕过。
- 飞书事件 / hook / 容器任务 → 带 `initiated_by_user_id`（归因），worker 入口 re-bind，系统行为标 `system`。
- 所有写入收口单一 service（INV-6）+ grep 守护；async ORM 走 `sync_to_async`；i18n 默认中文。

---

## 13. 非目标（本里程碑 Out of Scope / v2）

- 产品在系统内对话产出 feature list（用户明示本期不做）。
- UI 稿多模态/figma 正文召回（PROJX-01）、结构化记忆/自动降权（PROJX-02）、记忆全自动写入无需确认（PROJX-03）、Cursor 专用插件主动采集（PROJX-04）、项目看板燃尽/进度统计（PROJX-05）。
- 飞书文档跨系统亚秒级 OT（不可达，按秒级最终一致交付）。

---

## 14. 主要风险

- **同步引擎复杂度**（Phase 83）是全期最大风险——block_id 漂移、限流、漏事件、归档态切换都要测全；建议先把 MEMORY（append、最简）跑通再推 STATE/RESEARCH。
- **看板拆分写 API** 走 plugin 鉴权 + 父子关系预配，plan-phase 须先 live 验证（Phase 78 已验证读、写未验证）。
- **hooks 三家差异**易踩"Cursor 注入落空"坑——读路径务必 MCP+rules 兜底。
- **容器挂起/resume** 的 session 持久化是 Wave 3 硬前置，先做 SessionStore。
- 范围大（37 需求/8 Phase），建议严格 wave 顺序 + 每 wave 可独立验收。

---
*立项：2026-06-26 — 里程碑 v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线），8 Phase（82–89）/ 37 需求*
