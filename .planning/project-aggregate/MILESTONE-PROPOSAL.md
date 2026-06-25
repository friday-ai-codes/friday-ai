# 里程碑方案：v0.15.0 项目（交付上下文聚合根）

**定稿：** 2026-06-25
**状态：** Proposal（立项草案，供 `plan-phase` 拆解 plan 使用）

> 本文是 v0.15.0 的设计与调研基线。需求清单见 `.planning/REQUIREMENTS.md`，阶段拆分见 `.planning/ROADMAP.md`（Phases 76–81）。

---

## 0. 一句话目标

把"需求 → 代码"全链路的上下文统一收口到一个**在线协作的「项目」聚合根**：每个飞书"项目跟踪"看板对应一个项目，项目聚合需求/工件依赖/工作项/记忆/关联知识/仓库/分支/PR；任何对话、Cursor 编码、Agent 调用都能从该项目加载完整上下文并把沉淀写回。

---

## 1. 第一性原理 / 设计立场

- **项目是聚合根，不是工作流节点。** 它是一份持续存在的领域数据 + 关系图。工作流只是"写它"的众多入口之一（飞书事件、前端、`create_project` 节点、Cursor 上报）。
- **最大化复用既有脊柱，不另起炉灶。** 现有 `KnowledgeEntity/KnowledgeEntityVersion/KnowledgeEdge`（交付知识图谱，bi-temporal、版本链、关系边）几乎就是"项目↔知识/项目间关联"的现成骨架；`delivery.WorkItem`（三元组）就是 story/缺陷；`projects.Project`(→`Space`) 就是组织单元。新增的是"项目聚合根 + 工件 + 记忆 + 身份映射 + MR 实体"这几块**真正空白**的领域层。
- **三层领域结构**（命名见 §2）：

```text
空间 Space（现 projects.Project，组织单元，rename 后腾出 Project 名）
  └─ 项目 Project（新聚合根，对应 1 个飞书「项目跟踪」看板）
       ├─ 状态: 开发中 / 归档 / 终止（可扩展）
       ├─ 成员 ProjectMember（多对多 + 身份: 主R/PM/前端/后端/测试）
       ├─ WorkItem: story / 缺陷（复用 delivery.WorkItem，关系边挂入）
       ├─ Artifact 工件/依赖项（类型后台可增删禁用）
       ├─ Memory（自由文本 + 时间戳/贡献者，可变、共享）
       ├─ MergeRequest 实体（新）+ 仓库/分支（复用）
       └─ 关联: ↔ 其他项目 / ↔ 知识(多对多) / ↔ 空间 / ↔ 仓库
```

- **不做迭代实体**（用户决策）：另一个迭代 = 新建一个项目；"看历史迭代" = 通过"项目↔项目"关联链回看。知识/记忆直接挂项目。
- **观测/脱敏不可绕过**：所有写入 memory / 工件 / webhook 原始留痕前必须经 `redact_credentials`/`redact_secrets_in_text`/`redact_for_ledger`（沿用强制规范）；新增 LLM 调用赋 `call_source`、纳入 QPS/TPS/召回埋点；后台任务带 `initiated_by_user_id`。

---

## 2. 命名决策（已锁定：大重构）

- 后端 `projects.Project` **重命名为 `Space`**，腾出 `Project` 给新聚合根。
- 对外（前端/API/i18n）继续称"空间 Space"——重命名后**名实相符**（现状是 `Project` model 映射前端 Space，历史债）。
- 影响面：model 类名、`related_name`、所有 FK 引用（`WorkItem.project`、`Conversation.project`、`Workflow.project`、`ProjectRepository`、`ProjectMembership`、`Repository` M2M）、`permissions`、agent tools（`space_tools.py`）、workflow 节点（`fetch_space_info`）、serializers/views（部分已叫 `Space*`）。
- **风险控制**：重命名作为**独立前置 Phase（76）**，与新功能解耦；行为零回归、数据零丢失（`db_table` 保持或一次性 migration）；测试基线全绿后再推进 Phase 77。

---

## 3. 现状能力对照（调研结论）

详细调研见本里程碑立项前的三份子代理报告；要点：

| 能力 | 现状 | 支持度 | 关键位置 |
|---|---|---|---|
| 空间/组织单元 + 三角色权限 + 仓库 M2M | 成熟 | 🟢 | `server/projects/`、`server/permissions/` |
| WorkItem 三元组持久化 + 事件流 + 文档 | 成熟 | 🟢 | `server/delivery/` |
| 交付知识图谱（实体/版本/边/bi-temporal） | 成熟，**项目聚合根的现成骨架** | 🟢 | `server/knowledge/` |
| 代码 RAG（仓库+分支 overlay）+ GraphRAG | 成熟 | 🟢 | `server/services/retrieval/`、`server/code_relations/` |
| 交付知识检索 service | 成熟，但**未接入 chat runner** | 🟡 | `knowledge/retrieval.py`、`agents/chat_runner.py` |
| 飞书 webhook 触发 + 专属 token + 工作流 | 成熟 | 🟢 | `server/feishu/` |
| 分支命名 `feat/xxxx-m{work_item_id}-slug` | 单向生成（无反查） | 🟡 | `workflows/nodes/ai/coding.py` |
| MCP 工具链 + 容器 user_token 注入 | 成熟（Cursor 回流地基） | 🟢 | `server/mcp_tools/`、`env_FRIDAY_TASK_USER_TOKEN` |
| 飞书人员 ↔ Friday User 映射 | **不存在** | 🔴 | — |
| 飞书"项目跟踪"看板枚举子项/成员 | **无整板 listing API**，关系靠字段派生 | 🔴 | `services/feishu.py` |
| 工件类型（缺陷/UI稿/评审/埋点/复盘…）建模 | **不存在** | 🔴 | — |
| 通用记忆（会话提炼/共享/可编辑） | **不存在**（仅 McpLearningCase token 匹配） | 🔴 | `mcp_tools/` |
| 跨会话上下文聚合 | **不存在**，对话严格按 conversation_id 隔离 | 🔴 | `server/chat/` |
| MR/PR 独立实体 + 入站状态同步 | **不存在**（仅 url 字符串散落） | 🔴 | `CodingTask.pr_url` 等 |

结论：**"读结构化交付物 + 召回"链路成熟；"身份映射 / 工件 / 记忆 / 跨会话聚合 / MR 实体 / 看板枚举 / Cursor 双向回流"是本里程碑的新增主体。**

---

## 4. 技术前置与风险

| 前置 | 说明 | 落点 |
|---|---|---|
| 飞书"项目跟踪"枚举子项/成员 | 无整板 listing API；需经子项关联字段派生 + 逐项收集，或验证飞书是否提供按项目跟踪查子项接口；拿不到则降级为"半自动"（webhook 逐个并入） | Phase 78（FSPROJ-01）；plan-phase 先验证 API |
| 飞书人员 ↔ Friday User 映射 | 主R/多人/归因/Cursor 上报全依赖；手动绑定 + 飞书事件 JIT；与可观测"谁触发"同源 | Phase 77（IDENT-01） |
| 工件 RAG 物理边界 | 文字载体（飞书doc/表格/md/Spec）可全文 RAG；UI 稿（figma/mastergo）是图形链接，仅存元数据，正文 RAG 需多模态/figma API（留 v2） | Phase 79（ARTIFACT-04） |
| 记忆质量与时效 | 自由文本 + 时间戳/贡献者；人工为主、LLM 提议需人工确认；矛盾消解靠人工覆盖（结构化降权留 v2） | Phase 80（MEM-*） |
| 上下文窗口 | 现阶段必须召回+排序+压缩（不可全量塞）；context packer 按"可降级"设计，"全量加载"是未来态 | Phase 80（RECALL-01） |
| Cursor 回流归因/脱敏/防噪音 | 上报需认证（PAT/user_token）+ 归因（身份映射）+ 脱敏 + 质量门槛 | Phase 81（CURSOR-03） |

---

## 5. 数据模型（建议，plan-phase 细化）

> 复用为主、新增为辅。新增模型一律 UUID 主键、单一写入入口 service（INV-6）、async 走 `sync_to_async`。

**复用/改名：**
- `Space`（= 重命名后的 `projects.Project`）

**新增（建议落 `server/projects/` 或新 app `server/initiatives/`，plan-phase 定）：**
- `Project`（聚合根）：`space` FK、`name`、`description`、`status`（developing/archived/terminated）、`feishu_project_key` + 看板引用、`created_by`、时间戳。单一入口 `ProjectService`。
- `FeishuUserBinding`：`feishu_user_key`/`open_id` ↔ `User`（多对多/带来源 manual|jit），单一解析 `resolve_feishu_user`。
- `ProjectMember`：`project` FK + `user` FK + `role`（owner/pm/frontend/backend/qa，可扩展）+ 唯一约束，主R 唯一/可转移。
- `ArtifactType`：`key`/`name`/`carrier`（feishu_doc/feishu_bitable/external_link/markdown/repo_file）/`ragable` bool/`enabled` bool/`builtin` bool。内置类型 seed 迁移。
- `Artifact`：`project` FK + `type` FK + `title` + `url`/`content_ref` + `version` + `contributor` + 时间戳。
- `ProjectMemory`：`project` FK + `content`(text) + `contributor` FK + `created_at`/`edited_at`（自由文本条目，编辑保留可追溯——新行或 edited_at 二选一，plan-phase 定）。
- `MergeRequest`：`project`/`repository`/`work_item` 关联 + `url` + `source_branch`/`target_branch` + `status`(open/merged/closed) + `review_status` + 平台/外部 id。单一入口 `MergeRequestService` + 入站 webhook 同步。

**关系（复用 `KnowledgeEdge` + 新增项目实体 kind）：**
- 项目 ↔ 知识实体：把 `Project` 纳入交付知识图谱（新增 `KnowledgeEntity.kind` 值或独立关联表，plan-phase 取舍——倾向复用 `KnowledgeEdge` 关联，避免新表）。
- 项目 ↔ 项目 / 项目 ↔ 仓库 / 项目 ↔ 空间：经 `KnowledgeEdge` 或轻量关联表。

---

## 6. 关键流程

### 6.1 创建项目（三入口同源 service）
1. **前端手动**：选 Space + 飞书"项目跟踪"看板 URL + 名称 → `ProjectService.create`。
2. **飞书事件**：项目跟踪拖到指定节点/状态 → webhook → 幂等建同名项目 + 枚举看板人员（身份映射）+ 关联子项 workitem。
3. **工作流 `create_project` 节点**：以看板名建项目 + 拉人带身份 + 关联子项。

去重：以 `(space, feishu_project_key)` 或看板 key 为幂等键。

### 6.2 上下文召回（context packer）
项目 → 聚合需求(WorkItem) + 工件(文字全文) + 记忆 + 关联知识 + 历史 → grep(SQL 精确) + RAG(语义) 召回 → 排序/压缩 → 注入 LLM。Web 会话绑定项目后自动加载；`search_delivery_knowledge` 接入 chat runner 工具白名单。

### 6.3 Cursor 回流闭环
分支名（含 `m{work_item_id}`/项目标识）→ MCP 反查项目 → 召回需求/工件/记忆 → Cursor rules 强制先召回再编码 → 处理完上报沉淀 → Friday 写回项目 memory/知识（认证归因 + 脱敏 + 质量门槛）。

---

## 7. 阶段总览（详见 ROADMAP.md，Phases 76–81）

| Phase | 名称 | 主要需求 |
|---|---|---|
| 76 | 命名腾挪（Project→Space 重构前置） | RENAME-01/02 |
| 77 | 项目聚合根 + 身份映射 + 成员协作 | PROJ-01~05, IDENT-01, MEMBER-01~03 |
| 78 | 飞书触发建项目 + 看板枚举 + 工作项组合 + 创建项目节点 | FSPROJ-01~03, COMPOSE-01/02 |
| 79 | 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 | ARTIFACT-01~05, KLINK-01/02 |
| 80 | 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 | MEM-01~04, RECALL-01~03, MR-01/02 |
| 81 | Cursor 回流（MCP + rules + 上报写回）+ 前端项目工作台 | CURSOR-01~03, UI-01~03 |

执行顺序线性，76 是硬前置（重命名腾挪），77 立聚合根与身份地基，78/79 各自构建组合与工件，80 把记忆/召回/MR 接通会话，81 打通 Cursor 回流与前端工作台。

---

## 8. 显式非目标（本里程碑 Out of Scope）

- **迭代实体**：另一迭代 = 新项目（用户决策）。
- **UI 稿正文 RAG / 多模态设计理解**：UI 稿仅存元数据，figma/多模态读取留 v2。
- **结构化记忆 + 自动矛盾消解 / 旧记忆自动降权**：本期自由文本 + 人工覆盖；结构化升级留 v2。
- **记忆全自动写入（无人工确认）**：本期 LLM 仅产草稿，人工确认入库。
- **每次对话全量加载项目上下文**：本期召回+压缩；全量加载随上下文窗口扩大留未来。
- **Cursor 本地 IDE 插件/hook 主动上报**：本期走 MCP + git + 上报 API；专用插件留 v2。

---

## 9. v2 候选（Future）

- PROJX-01：UI 稿多模态/figma API 接入正文召回。
- PROJX-02：结构化记忆 + 时效降权 + 矛盾消解。
- PROJX-03：记忆全自动提炼（无人工确认）+ 质量评分门槛自适应。
- PROJX-04：Cursor 专用插件/hook 主动行为采集。
- PROJX-05：项目级看板可视/燃尽/进度统计。

---
*立项：2026-06-25 — 里程碑 v0.15.0 项目（交付上下文聚合根），6 Phase（76–81）*
