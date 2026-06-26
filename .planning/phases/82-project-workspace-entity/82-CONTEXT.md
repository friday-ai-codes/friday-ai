# Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 五份文件落地 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

立起"项目工作区"实体层：扩展 `Project`（visibility/feishu_folder_token）、新增 5 文件容器（`ProjectDoc`）与同步映射表（`ProjectDocBlockMap`）+ 结构化 API 清单（`ProjectStateApi`）、每项目建飞书专属文件夹并把 MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT 5 文件创建于其下、文件互链 + 看板描述可打开、前端侧边栏「项目」tab、权限翻转为默认全员可读（public_org）/ 写仅成员。

交付需求：WS-01~04, DOC-01~06。
</domain>

<decisions>
## Implementation Decisions

### 飞书文件夹 + 5 文件创建时机
- **异步后台创建**：建项目时不阻塞，文件夹（`create_folder`，父=Space `feishu_doc_folder_token`）+ 5 文件（`create_document(folder_token=…)`）经后台任务创建；失败标 broken + 可一键重建。
- 后台任务必须带 `initiated_by_user_id`（创建者归因），worker 入口 re-bind 用户上下文。
- `create_folder` 5QPS/不可并发约束 → per-task 串行；DB 存 `Project.feishu_folder_token` + 每文件 `ProjectDoc.feishu_document_id`/`feishu_doc_token`，不乱放。

### 侧边栏「项目」tab 范围
- **默认展示"当前所选空间"下的项目**（不是全局跨空间）。
- **用户所选空间用 localStorage 本地记忆**：用户选了某空间后，下次进入沿用该空间（前端本地记住即可，无需后端持久化偏好）。
- tab 位置：「首页」之下、「空间」之上。
- 列表内仍支持按状态/成员筛选；进入为项目工作台。

### 权限翻转 + visibility 迁移
- 新增 `Project.visibility`(public_org / members_only，默认 **public_org**)。
- **当前无历史项目** → 新建项目直接落 `public_org`，**不写任何数据迁移翻转逻辑**（migration 仅 AddField + default，不回填）。
- 权限语义：非成员可读、可对任意 public_org 项目发起会话；写（记忆/STATE/成员/文件）仅项目成员 fail-closed；召回 scope 随 visibility；脱敏闸不可绕过。

### 数据模型（plan-phase 细化）
- 扩展 `Project`：`visibility`、`feishu_folder_token`。
- 新增 `ProjectDoc`（doc_type=memory/state/milestones/research/preflight + feishu token + last_synced_revision + last_synced_snapshot + 时间戳）；MEMORY 条目仍落 `ProjectMemory`，`ProjectDoc(memory)` 只持飞书映射与渲染。
- 新增 `ProjectDocBlockMap`（doc FK + feishu_block_id + db_ref + section(system/human) + content_hash）。
- 新增 `ProjectStateApi`（project FK + method + path + params JSON + status + 贡献来源）。
- 所有写入收口 service（INV-6，grep 守护）；async ORM 走 `sync_to_async`。

### 文件互链 + 看板可打开（DOC-06）
- 5 文件头部导航区互链（链到其余 4 文件 + 看板 + Friday 项目页）。
- 看板（项目跟踪）描述经 `update_work_item_fields` 追加「📁 项目工作区」段（文件夹/5 文件/Friday 项目页链接）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/initiatives/models/project.py`：`Project` 聚合根（UUID PK、space FK、status 状态机、feishu_project_key 幂等键、related_projects/work_items M2M）— 本期扩 visibility/feishu_folder_token。
- `server/initiatives/models/member.py`：`ProjectMember`（OWNER/PM/FRONTEND/BACKEND/QA 角色、单 owner partial constraint）— 权限判定依据。
- `server/initiatives/models/memory.py`：`ProjectMemory`(+Revision append-only +Draft pending/confirmed/rejected) — MEMORY 文件复用，不重造。
- `server/initiatives/services/project_service.py`、`memory_service.py`：写入收口 service（INV-6）。
- `server/services/feishu_doc.py`：block API / create_document / folder_token —— 文件夹+文件创建复用。
- `server/services/feishu.py::update_work_item_fields`：看板描述追加。
- `web/src/pages/spaces/[id]/*.vue`、`web/src/components/layout/AppSidebar.vue`：侧边栏 tab + 工作台子页布局参照。

### Established Patterns
- 模型层零业务方法、写入收口单一 service + `test_*_inv6_guard` grep 守护。
- UUIDField PK + partial UniqueConstraint 幂等键。
- 后台任务带 `initiated_by_user_id`、worker 入口 re-bind、best-effort fail-soft。

### Integration Points
- `server/projects/`(Space) `feishu_doc_folder_token` 作父文件夹。
- `web/src/api/` 新增 projects 工作区端点；`AppSidebar.vue` 注册 tab。

</code_context>

<specifics>
## Specific Ideas

- 侧边栏空间选择用 localStorage 记忆（用户明确要求"本地记忆即可"）。
- 无历史项目，省去 visibility 迁移脚本（用户明确"现在全部没有历史的项目，可以直接 public_org"）。

</specifics>

<deferred>
## Deferred Ideas

- 项目级看板燃尽/进度统计（PROJX-05，v2）。
- Space 单层文件夹 1500 上限的分桶嵌套：先实现单层，超限兜底留 plan-phase 评估。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — 设计基线（§5 文件夹结构、§6 数据模型、§4.4 五文件形态）
- `.planning/REQUIREMENTS.md` — WS-01~04, DOC-01~06
- `.planning/ROADMAP.md` — Phase 82 Success Criteria
- `.cursor/rules/observability-logging.mdc` — 观测/脱敏/归因强制项

</canonical_refs>
