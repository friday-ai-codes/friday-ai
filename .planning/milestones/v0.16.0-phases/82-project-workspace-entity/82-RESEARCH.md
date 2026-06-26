# Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 五份文件落地 - Research

**Researched:** 2026-06-26
**Domain:** Django 领域建模（initiatives app 扩展）+ 飞书 Drive/Docx API + adrf 异步 REST + 后台任务归因 + Vue 3 侧边栏/localStorage
**Confidence:** HIGH（全部基于已读真实源码；唯一 MEDIUM 项为飞书 `create_folder` 端点形态——库内尚无实现，需 plan-phase live 验证）

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（逐字摘自 82-CONTEXT.md `<decisions>`）

**飞书文件夹 + 5 文件创建时机**
- **异步后台创建**：建项目时不阻塞，文件夹（`create_folder`，父=Space `feishu_doc_folder_token`）+ 5 文件（`create_document(folder_token=…)`）经后台任务创建；失败标 broken + 可一键重建。
- 后台任务必须带 `initiated_by_user_id`（创建者归因），worker 入口 re-bind 用户上下文。
- `create_folder` 5QPS/不可并发约束 → per-task 串行；DB 存 `Project.feishu_folder_token` + 每文件 `ProjectDoc.feishu_document_id`/`feishu_doc_token`，不乱放。

**侧边栏「项目」tab 范围**
- **默认展示"当前所选空间"下的项目**（不是全局跨空间）。
- **用户所选空间用 localStorage 本地记忆**（前端本地记住即可，无需后端持久化偏好）。
- tab 位置：「首页」之下、「空间」之上。
- 列表内仍支持按状态/成员筛选；进入为项目工作台。

**权限翻转 + visibility 迁移**
- 新增 `Project.visibility`(public_org / members_only，默认 **public_org**)。
- **当前无历史项目** → 新建项目直接落 `public_org`，**不写任何数据迁移翻转逻辑**（migration 仅 AddField + default，不回填）。
- 权限语义：非成员可读、可对任意 public_org 项目发起会话；写（记忆/STATE/成员/文件）仅项目成员 fail-closed；召回 scope 随 visibility；脱敏闸不可绕过。

**数据模型（plan-phase 细化）**
- 扩展 `Project`：`visibility`、`feishu_folder_token`。
- 新增 `ProjectDoc`（doc_type=memory/state/milestones/research/preflight + feishu token + last_synced_revision + last_synced_snapshot + 时间戳）；MEMORY 条目仍落 `ProjectMemory`，`ProjectDoc(memory)` 只持飞书映射与渲染。
- 新增 `ProjectDocBlockMap`（doc FK + feishu_block_id + db_ref + section(system/human) + content_hash）。
- 新增 `ProjectStateApi`（project FK + method + path + params JSON + status + 贡献来源）。
- 所有写入收口 service（INV-6，grep 守护）；async ORM 走 `sync_to_async`。

**文件互链 + 看板可打开（DOC-06）**
- 5 文件头部导航区互链（链到其余 4 文件 + 看板 + Friday 项目页）。
- 看板（项目跟踪）描述经 `update_work_item_fields` 追加「📁 项目工作区」段（文件夹/5 文件/Friday 项目页链接）。

### Claude's Discretion
- `ProjectDoc.last_synced_snapshot` 落 TextField/JSONField 还是独立快照表（CONTEXT 写"或快照表"）— 推荐内联 JSON/Text 字段（最小可用，同步引擎 Phase 83 用），不另起表。
- broken/rebuild 的状态字段命名与放置（建议 `ProjectDoc.sync_status` 枚举 + `Project.workspace_status` 或复用每文件状态聚合）。
- 后台任务用 `background_runner.run_in_background` 还是 `resumable`/durable —— 见 §架构/Don't Hand-Roll，推荐 `run_in_background`（已支持 `initiated_by_user_id` re-bind）。
- 5 文件初始正文模板内容（zh-CN）。

### Deferred Ideas (OUT OF SCOPE)
- 项目级看板燃尽/进度统计（PROJX-05，v2）。
- Space 单层文件夹 1500 上限的分桶嵌套：先实现单层，超限兜底留 plan-phase 评估。
- 飞书↔Friday **双向同步引擎**（subscribe / block_id 结构化匹配 / 三方合并 / 编辑感知延迟写）= **Phase 83**，本期只建实体 + 映射表骨架 + 单向首建落地，不做同步循环。
- 项目工作台 2.0 前端（大盘/进度灯/5 文件在线编辑）= Phase 84。本期前端仅：侧边栏 tab + 默认按所选空间列项目 + localStorage 记忆。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WS-01 | 左侧菜单新增「项目」入口（首页↓、空间↑），点进为工作台 | `web/src/components/layout/AppSidebar.vue` `mainNavItems` 插入；`/projects` 路由与 `web/src/pages/projects/index.vue` 已存在（Phase 81 落地），本期改为默认按所选空间过滤 + localStorage |
| WS-02 | 权限翻转：默认 public_org，非成员可读可发起会话；写仅成员；脱敏不可绕过 | `Project.visibility` 新字段；`initiatives/permissions.py` + `services/project_context_packer.py`（fail-closed 改 visibility 感知）+ `knowledge/access_scope.py`；写仍走 `MemoryService._assert_member` 等成员闸 |
| WS-03 | 项目↔空间解绑/改归；`Conversation.bound_project` 解绑/改归 | `Project.space` 当前是 `CASCADE` 非空 FK；`ProjectService.update` 白名单不含 space/visibility——需扩展（见 Pitfalls）。`Conversation.bound_project` 已是软/可空引用（v0.15.0） |
| WS-04 | 每项目飞书专属文件夹（create_folder，父=Space folder），5 文件建其下，DB 存 folder/doc token | `FeishuDocClient.create_document(folder_token=…)` 已有；**`create_folder` 缺失需新增**；`Space.feishu_doc_folder_token` 作父；后台任务经 `run_in_background` |
| DOC-01 | MEMORY 复用条目式 `ProjectMemory`，渲染为文件视图 | `ProjectMemory(+Revision+Draft)` + `MemoryService` 全部复用；`ProjectDoc(memory)` 只持飞书映射 |
| DOC-02 | STATE：活计算派生 + 结构化「已完成 API 清单」(method/path/params/status) + 自由文本备注段 | 新增 `ProjectStateApi` 模型 + 写入 service；活计算派生在 Phase 83/84 渲染 |
| DOC-03 | MILESTONES：以 `delivery.WorkItem` 实时派生 + 人写补充段 | 复用 `ProjectWorkItemLink` → `delivery.WorkItem`；本期建 `ProjectDoc(milestones)` 容器 |
| DOC-04 | RESEARCH：项目调研长文 | `ProjectDoc(research)` 容器 + 飞书文档；正文长文留 Phase 84 编辑面 |
| DOC-05 | PREFLIGHT：前置风险/修复清单（agent 可产 draft） | `ProjectDoc(preflight)` 容器；draft 机制可复用记忆 Draft 范式（本期建容器，draft 产出留后续） |
| DOC-06 | 5 文件互链 + 看板描述追加「项目工作区」段可打开 | 文档头部导航 block + `FeishuClient.update_work_item_fields(project_key, work_item_id, work_item_type, fields)` 追加描述 |
</phase_requirements>

---

## Summary

Phase 82 是 v0.16.0 的实体地基，**严格复用 `server/initiatives/` 这套已成熟的"模型零业务方法 + 单一 service 写入收口（INV-6）+ grep 守护 + async ORM(`sync_to_async`) + AuditService 归因 + best-effort WS 推送"范式**。改动落点高度集中：（1）`Project` 加两个字段（`visibility`、`feishu_folder_token`）+ 配套 broken/rebuild 状态；（2）三个新模型（`ProjectDoc`/`ProjectDocBlockMap`/`ProjectStateApi`）+ 一个新 service + 一个新 INV-6 guard 测试；（3）`FeishuDocClient` **新增 `create_folder`**（库内目前只有 `create_document`）+ 一条后台 coroutine 串行建文件夹与 5 文件；（4）权限翻转：读/召回从"成员 fail-closed"放宽为"public_org 全员可读可问、members_only 仍成员闸"，**写一律保持成员闸**；（5）前端侧边栏插一个 tab + 按 localStorage 记忆的所选空间过滤项目。

**两个最大风险（必须 plan 显式覆盖）**：① 飞书 `create_folder` 端点库内无实现、需镜像 `create_document` 新增并 live 验证（5QPS/不可并发/单层 1500 上限）；② "召回 scope 随 visibility"会触碰 **3 处现存 fail-closed 召回闸**（`project_context_packer.pack_project_context`、`knowledge/access_scope.resolve_allowed_project_ids`、`chat/config._maybe_pack_project_context`）——放宽稍有不慎即泄漏 members_only 项目内容，必须分 visibility 精确处理并补对称守护测试。

**Primary recommendation:** 逐字镜像 `initiatives/services/project_service.py` + `test_project_inv6_guard.py` 建 `ProjectDocService` + 新 guard；`Project` 字段走 `0006_*` 纯 AddField 迁移（无回填）；飞书文件夹/5 文件创建在 `ProjectDocService` 内经 `services.background_runner.run_in_background(coro_factory, name=..., initiated_by_user_id=...)` 串行落地、失败置 `sync_status=broken` 供一键重建；权限翻转只放宽"读/召回"且按 `visibility` 分流，写闸（`MemoryService._assert_member` 等）一字不动。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `Project` 字段扩展（visibility/folder_token/状态） | DB / Models (`initiatives/models/project.py`) | Migration | 模型层只声明字段，零业务方法（既有约定） |
| 3 个新工作区模型 | DB / Models | Migration `0006` | 同上，结构声明归模型层 |
| 写入收口（建文档容器/block map/api 清单/folder token） | Service (`initiatives/services/project_doc_service.py` 新建) | — | INV-6：唯一写入入口 + 审计 + 归因 |
| 飞书文件夹 + 5 文件创建（外呼） | Service（后台 coroutine） | `services/feishu_doc.py`（API client）/ `services/background_runner.py`（调度） | 外呼 best-effort，归因经后台 runner re-bind |
| 看板描述追加「工作区」段 | Service | `services/feishu.py::update_work_item_fields` | 飞书 OpenAPI 写工作项字段 |
| 权限翻转（读/召回放宽 + 写闸不动） | API/permissions (`initiatives/permissions.py`) + 召回 service (`project_context_packer`/`access_scope`) | — | 权限是 API/服务层职责，按 visibility 分流 |
| REST 入口（ProjectDoc 列表/重建/STATE API 清单 CRUD） | API (`initiatives/views.py` adrf APIView) | serializers/urls | 入口自动纳入 RequestMetric（中间件） |
| 侧边栏 tab + 所选空间记忆 | Browser / Client (`AppSidebar.vue` + pinia/localStorage) | `web/src/api/projects.ts` | 纯前端导航 + 本地偏好，无后端持久化 |

---

## Standard Stack

**本期不新增任何外部依赖。** 全部用既有栈（Django 6.x / adrf / structlog / asgiref / httpx / tenacity / Vue 3 / @vueuse `useLocalStorage` / @tanstack/vue-query）。

| 既有能力 | 位置 | 用途 |
|---------|------|------|
| 模型零业务方法 + UUID PK + partial UniqueConstraint | `initiatives/models/project.py`、`member.py` | 新模型逐字镜像 |
| 单一写入 service（INV-6） | `initiatives/services/project_service.py` | 新 `ProjectDocService` 模板 |
| INV-6 grep 守护 | `tests/initiatives/test_project_inv6_guard.py`、`test_artifact_inv6_guard.py`（多模型版） | 新 guard 模板 |
| `AuditService.aemit` 归因 + 脱敏入口 | `audit/services/audit_service.py` + `taxonomy` | 写操作审计（需登记新 action 常量） |
| `redact_secrets_in_text` / `redact_for_ledger` | `server/common/logging.py` | 文档正文/快照入库脱敏 |
| 后台任务 + 归因 re-bind | `services/background_runner.py::run_in_background(coro_factory, name=, initiated_by_user_id=)` | 异步建文件夹/5 文件 |
| 飞书文档 API client | `services/feishu_doc.py::FeishuDocClient`（`create_document`/`get_document_content`/`append_markdown`/`_write_blocks`） | 建 5 文件；**需补 `create_folder`** |
| 飞书 client 工厂 | `agents/tools/feishu_doc_tools.py::create_feishu_doc_client_for_project(space)`（项目级→系统级回退） | 取 FeishuDocClient（注意入参是 **Space** 实例） |
| 飞书工作项字段写 | `services/feishu.py::FeishuClient.update_work_item_fields(project_key, work_item_id, work_item_type, fields)` | 看板描述追加段（DOC-06） |
| 召回打包 + fail-closed | `services/project_context_packer.py::pack_project_context(project, user, ...)` | 权限翻转需改 visibility 感知 |
| 知识检索 scope | `knowledge/access_scope.py::resolve_allowed_project_ids(user, project_ids)` | 权限翻转需考虑 public_org |
| 前端本地偏好 | `@vueuse/core` `useLocalStorage`（AppSidebar 已用 `'sidebar-collapsed'`） | 所选空间记忆 |

**Version verification:** N/A —— 无新增包；不需 `npm view`/`pip index`。

## Package Legitimacy Audit

> 本期不安装任何外部包 —— **SKIPPED（no external packages）**。所有能力来自仓库现有依赖与现有内部模块。

---

## Architecture Patterns

### System Architecture Diagram（Phase 82 数据流）

```text
[前端] /projects 页（按 localStorage 所选空间过滤）
   │  GET /api/projects/?space_id=<选中空间>          (已有 list 入口)
   ▼
[REST adrf APIView] ProjectListCreateView.post  ──创建项目──► ProjectService.create()
   │                                                      │ (建 Project + owner 成员 + 审计)
   │                                                      ▼
   │                                            visibility 默认 public_org（模型 default）
   │
   └─创建成功后触发──► ProjectDocService.provision_workspace(project, initiated_by_user_id)
                          │
                          ▼ run_in_background(coro_factory, name="project-workspace:{id}",
                          │                    initiated_by_user_id=<creator>)   ← worker 入口 re-bind
                          ▼ (独立 worker loop，串行，best-effort)
        ┌───────────────────────────────────────────────────────────────┐
        │ 1) FeishuDocClient.create_folder(name, parent=Space.folder)     │ 5QPS/不可并发 → 串行
        │    └► Project.feishu_folder_token = token  (经 ProjectService/   │
        │        ProjectDocService 写，INV-6)                              │
        │ 2) for doc_type in [memory,state,milestones,research,preflight]:│
        │      create_document(title, folder_token, content_模板)         │ per-doc 串行 + 退避
        │      └► ProjectDoc(doc_type, feishu_document_id, feishu_doc_token)│ (ProjectDocService 写)
        │ 3) 互链：回写每文档头部导航 block（链到其余4+看板+Friday页）       │
        │ 4) update_work_item_fields(...) 追加看板描述「📁 项目工作区」段   │
        │ 任一步失败 → ProjectDoc.sync_status=broken（不抛，留一键重建入口） │
        └───────────────────────────────────────────────────────────────┘

[读路径 / 召回] AI 对话(bound_project) / MCP / REST
   ▼
pack_project_context(project, user)   ← 改：visibility==public_org → 放行非成员读
   │                                      visibility==members_only → 维持 fail-closed
   └► writes（记忆/STATE/成员/文件）始终 _assert_member fail-closed（不变）
```

### Recommended File Layout（新增/改动）

```text
server/initiatives/
├── models/
│   ├── project.py            # 改：+visibility +feishu_folder_token (+workspace 状态)
│   ├── project_doc.py        # 新：ProjectDoc / ProjectDocBlockMap / DocType / SyncStatus / DocSection
│   ├── project_state_api.py  # 新：ProjectStateApi / ApiStatus / ApiSource
│   └── __init__.py           # 改：导出新模型/枚举
├── services/
│   ├── project_service.py    # 改：update 白名单加 visibility/feishu_folder_token；或单设 set_folder_token()
│   ├── project_doc_service.py# 新：ProjectDoc/BlockMap/StateApi 唯一写入入口 + provision_workspace 后台
│   └── __init__.py           # 改：导出 ProjectDocService
├── migrations/
│   └── 0006_*.py             # 新：AddField(Project.*) + CreateModel(3 新模型)，无回填
├── views.py / serializers.py / urls.py   # 改：ProjectDoc 列表/重建、StateApi CRUD、visibility 字段
server/services/feishu_doc.py # 改：FeishuDocClient.create_folder()（镜像 create_document）
server/services/project_context_packer.py  # 改：visibility 感知放宽
server/knowledge/access_scope.py           # 改：public_org 项目纳入可读集合（按需）
server/tests/initiatives/test_project_doc_inv6_guard.py   # 新：3 新模型 grep 守护
web/src/components/layout/AppSidebar.vue   # 改：mainNavItems 插「项目」(首页↓空间↑)
web/src/pages/projects/index.vue           # 改：默认 space_id=localStorage 记忆
web/src/api/projects.ts                    # 改：Project 接口加 visibility；ProjectDoc 端点
```

### Pattern 1: 模型零业务方法 + UUID PK + partial UniqueConstraint
**What:** 新模型逐字镜像 `Project`/`ProjectMember`：`UUIDField(primary_key, default=uuid.uuid4, editable=False)`、FK `on_delete=CASCADE related_name=...`、`TextChoices` 闭集枚举、`Meta.db_table`/`verbose_name`/`indexes`/`constraints`、**无 create/save 业务方法**。
**幂等键示例**（每项目每 doc_type 唯一）：
```python
# Source: 镜像 initiatives/models/member.py uniq_project_single_owner
class Meta:
    db_table = "initiative_project_docs"
    constraints = [
        models.UniqueConstraint(
            fields=["project", "doc_type"], name="uniq_project_doc_type"
        ),
    ]
```

### Pattern 2: 单一写入 service（INV-6） + async + sync_to_async + 审计
**What:** 复刻 `ProjectService` 结构——`async def` 公共方法 + `@sync_to_async def _xxx_locked`（内含 `transaction.atomic()` + `select_for_update()`）+ `AuditService.aemit(..., metadata={"component":"initiatives","category":"caller","initiated_by_user_id": str(actor_id) if actor_id else "system"}, source="api")` + best-effort `apush_project_event`。
```python
# Source: initiatives/services/project_service.py:128-168 (_create_locked 范式)
@sync_to_async
def _upsert_doc_locked(self, *, project_id, doc_type, **fields):
    with transaction.atomic():
        return ProjectDoc.objects.get_or_create(
            project_id=project_id, doc_type=doc_type, defaults=fields
        )
```

### Pattern 3: 后台任务带归因 + worker 入口 re-bind（飞书外呼）
**What:** 文件夹/5 文件创建经 `run_in_background`，**传 factory 不传 coroutine**，带 `initiated_by_user_id`；runner 在干净 context 内经 `bind_task_context(user_id=, source="background")` 重绑发起用户。
```python
# Source: services/background_runner.py:111-153
from services.background_runner import run_in_background

def provision_dispatch(project_id, user_id):
    run_in_background(
        lambda: _provision_workspace_coro(project_id),   # factory
        name=f"project-workspace:{project_id}",
        initiated_by_user_id=str(user_id) if user_id else None,
    )
```
**注意**：`background_runner` 是**进程内、重启即丢**（Phase 61 起降级为 SQLite dev fallback / 轻任务）。本任务幂等 + 失败置 `broken` 状态 + 一键重建端点足以兜底（无需 durable），但 plan 须确保 **broken/进行中状态持久化在 DB**（不能只存内存），重启后用户仍可重建。

### Pattern 4: 飞书 client 串行外呼 + 限流退避
**What:** `FeishuDocClient` 已用 `tenacity @retry(retry_if_exception_type(RateLimitError))`；`create_folder` 须同样处理 `99991400`/rate-limit。`create_folder` **5QPS 且不可并发** → per-task 内 5 文件 + 1 文件夹**全部串行 await**（绝不 `asyncio.gather` 并发）。

### Anti-Patterns to Avoid
- **旁路写新模型**：任何 `ProjectDoc.objects.create(...)` / `ProjectDoc(...)` 出现在 service 外 → INV-6 guard 红。所有写入（含后台 coroutine、views）必须经 `ProjectDocService`。
- **整篇覆盖飞书文档**：本期建文件首建可写全量；但**互链回写**绝不能整篇 replace（用 block 级 children API，为 Phase 83 同步引擎留接口）。
- **权限翻转一刀切放行**：不能把召回 fail-closed 直接删掉——必须 `visibility==public_org` 才放行非成员，`members_only` 维持。
- **后台 coroutine 直接 ORM 写不归因**：必须经 service + 后台 re-bind，否则审计 `initiated_by_user_id` 丢失。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 后台脱离请求生命周期跑 coroutine | 裸 `asyncio.create_task` | `services/background_runner.run_in_background` | request loop 关闭后 `sync_to_async` 会 `CurrentThreadExecutor already quit`（该模块 docstring 即此坑） |
| 后台任务归因 | 手动 contextvar 传 user | `run_in_background(initiated_by_user_id=...)` | 已在 worker 干净 context 内 `bind_task_context` re-bind |
| 飞书 token 缓存/刷新 | 自写 token 逻辑 | `FeishuDocClient.get_tenant_access_token()`（2h 缓存） | 已实现，`feishu_bitable` 也复用它 |
| markdown ↔ 飞书 block 转换 | 自写转换 | `feishu_doc.markdown_to_blocks` / `blocks_to_markdown` | 已支持表格/标题/代码/列表/内联样式 |
| 写入审计 + 脱敏 | 自写日志 | `AuditService.aemit`（内置 `redact_for_ledger`） | 凭证脱敏不可绕过 |
| 项目可见性/成员集合 | 自写 membership 查询 | `permissions/services.py::PermissionService`、`initiatives/permissions.py`、`access_scope.py` | 已有 Space 三角色 + 项目成员判定 + fail-closed |
| 前端本地偏好持久化 | 自写 localStorage 读写 | `@vueuse/core useLocalStorage` | AppSidebar 已用此范式 |

**Key insight:** 这一期几乎所有"难点"都有现成件。真正需要新写的只有：3 个模型 + 1 个 service + 1 个 `create_folder` 方法 + 权限 visibility 分流 + 前端 tab。其余都是装配。

## Common Pitfalls

### Pitfall 1: `create_folder` 在 `feishu_doc.py` 不存在
**What goes wrong:** CONTEXT/REQUIREMENTS 假定 `create_folder` 可用，但 `FeishuDocClient` 当前只有 `create_document(title, folder_token, content)`、`get_document_content`、`append_markdown`、`_write_blocks` —— **无任何文件夹创建方法**（已 grep 全仓确认，仅文档/计划里提到，代码里无）。
**How to avoid:** plan 必须含"新增 `FeishuDocClient.create_folder(name, folder_token) -> token`"任务，镜像 `create_document` 的 token/headers/retry/错误码处理。端点：`POST {OPEN_API_BASE}/drive/v1/files/create_folder`，body `{"name": ..., "folder_token": <父>}`，返回 `data.token`。权限 scope `drive:drive` / `space:folder:create`。**[CITED: open.feishu.cn drive v1 create_folder]** —— 字段名/返回结构需 live 验证（标 MEDIUM）。
**Warning signs:** 5QPS/不可并发限制 → 多项目并发建会撞限流；务必 per-task 串行 + 退避。

### Pitfall 2: 权限翻转触碰 3 处 fail-closed 召回闸（泄漏风险）
**What goes wrong:** "召回 scope 随 visibility"要放宽读，但现有 3 处都是硬 fail-closed：
1. `services/project_context_packer.py::pack_project_context` → `if not await _is_member(...): return PackedContext()`（RECALL-03）。
2. `chat/config.py::_maybe_pack_project_context` → 包一层 best-effort 调上面。
3. `knowledge/access_scope.py::resolve_allowed_project_ids` → 只返回 `PermissionService.get_user_projects`（membership）项目。
直接删 fail-closed 会让 members_only 也泄漏。
**How to avoid:** 改为 visibility 感知——`is_member OR project.visibility == public_org` 才放行读/召回；`members_only` 维持 fail-closed。`access_scope` 需把 public_org 项目并入 allowed 集合（注意 caller intersect 语义不能被放宽破坏）。**写路径（`MemoryService._assert_member`、成员/工件/StateApi 写）一字不动，始终成员闸。** 必须补对称守护测试：public_org 非成员可读、members_only 非成员零召回、任意 visibility 非成员写被拒。

### Pitfall 3: `ProjectService.update` 字段白名单不含新字段 / space 改归
**What goes wrong:** `ProjectService.update` `allowed = {"name","description","feishu_board_url","feishu_board_id"}`——`visibility`、`feishu_folder_token`、`space`（WS-03 改归）都不在内，PATCH 会被静默丢弃。
**How to avoid:** 扩展白名单（`visibility`），`feishu_folder_token` 建议走专用 `set_folder_token`（后台任务写，不暴露给用户 PATCH）；`space` 改归（WS-03）需专门方法（含 owner 唯一约束/审计），不要简单塞进 update 白名单。`Project.space` 当前 `on_delete=CASCADE` 非空——改归只换 FK 值即可，无需改 null 约束。

### Pitfall 4: 新模型 INV-6 guard 必须新建（现有 guard 不覆盖且不误伤）
**What goes wrong:** `test_project_inv6_guard.py` 的 `_MODELS=("Project","ProjectMember",...)`。正则 `\bProject\.objects` 与 `\bProject\s*\(` **不会**误伤 `ProjectDoc`（"Project" 后是 "Doc" 非 `.`/空白/`(`）——好处是无误报，坏处是 3 个新模型**完全没被守护**。
**How to avoid:** 新建 `test_project_doc_inv6_guard.py`，镜像 `test_artifact_inv6_guard.py`（多模型版，已处理 `Artifact`/`ArtifactType` 前缀误伤），`_MODELS=("ProjectDoc","ProjectDocBlockMap","ProjectStateApi")`，`_ALLOWED_WRITER="initiatives/services/project_doc_service.py"`，并加 `writer_actually_writes` 有效性断言。注意 `ProjectDoc` 与 `ProjectDocBlockMap` 前缀重叠——`ProjectDoc(` 会误伤 `ProjectDocBlockMap(`，需像 artifact guard 那样加跳过逻辑。

### Pitfall 5: 飞书 client 工厂入参是 Space 不是 Project
**What goes wrong:** `create_feishu_doc_client_for_project(project: Space)` 名字叫 project 但读 `project.feishu_app_id`（Space 字段）+ 回退系统设置。`feishu_doc_folder_token` 也在 **Space**（`projects.Space`，`server/projects/models.py:50`）。
**How to avoid:** 后台任务取 `project.space`（`Project.space` FK），用 `project.space` 构 client、`project.space.feishu_doc_folder_token` 作父文件夹。空 folder_token / 无飞书凭证 → fail-soft 置 broken（不抛）。

### Pitfall 6: 看板描述追加须读后再写，勿覆盖
**What goes wrong:** `update_work_item_fields(project_key, work_item_id, work_item_type, fields)` 写 `update_fields`——若直接写 description 会覆盖飞书原描述。
**How to avoid:** 先 `get_work_item` 读现描述，追加「📁 项目工作区」段后整体回写（幂等：检测段已存在则不重复追加）。`work_item_id` 是 int、`work_item_type` 必填（Phase 27 起 fail-loud）。需确认 description 的 field_key（plan-phase live 验证）。

### Pitfall 7: 异步 ORM lazy FK 访问
**What goes wrong:** async 上下文裸访问 `project.space.feishu_doc_folder_token` 触发同步 DB 查询报错。
**How to avoid:** `select_related("space")` 预取，或在 `sync_to_async` 块内访问（既有 view 全用 `Project.objects.select_related("space")`）。

## Runtime State Inventory

> 本期**非 rename/migration 重构**，但因"权限翻转 + 新建项目即建飞书文件夹"涉及外部副作用与既有数据，做一轮轻量盘点：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data（历史项目） | **无历史项目**（CONTEXT/用户明确"现在全部没有历史的项目"）→ visibility 迁移仅 AddField+default，**不回填** | migration `0006` 仅 AddField |
| Live service config（飞书） | Space `feishu_doc_folder_token`（父文件夹，可能为空）；每项目运行期产出新飞书文件夹 + 5 文件 token（DB 落 `Project.feishu_folder_token`/`ProjectDoc.feishu_*`） | DB 持久化 token；broken 状态可重建 |
| OS-registered state | 无 | None |
| Secrets/env vars | 飞书 app_id/app_secret（Space 加密字段 / SystemSetting）——既有，本期只读复用，不新增 | None |
| Build artifacts | 无 | None |

**结论**：唯一"既有数据"风险是 Space 未配 `feishu_doc_folder_token` → 文件夹创建无父级 → fail-soft 置 broken + 前端提示去配置（不阻断建项目）。

## Code Examples

### 新模型枚举 + 字段（镜像既有）
```python
# Source: 镜像 initiatives/models/memory.py + member.py
class DocType(models.TextChoices):
    MEMORY = "memory", "记忆"
    STATE = "state", "状态"
    MILESTONES = "milestones", "里程碑"
    RESEARCH = "research", "调研"
    PREFLIGHT = "preflight", "前置检查"

class DocSyncStatus(models.TextChoices):
    PENDING = "pending", "待创建"
    READY = "ready", "已就绪"
    BROKEN = "broken", "失效待重建"

class DocSection(models.TextChoices):
    SYSTEM = "system", "系统区"
    HUMAN = "human", "人工区"
```

### Project 字段扩展（纯 AddField）
```python
# Source: 镜像 projects/migrations/0006_add_feishu_doc_folder_token.py + initiatives field 风格
class ProjectVisibility(models.TextChoices):
    PUBLIC_ORG = "public_org", "全员可读"
    MEMBERS_ONLY = "members_only", "仅成员"

# Project 新增字段：
visibility = models.CharField(max_length=20, choices=ProjectVisibility.choices,
                              default=ProjectVisibility.PUBLIC_ORG, verbose_name="可见性")
feishu_folder_token = models.CharField(max_length=200, blank=True, default="",
                                       verbose_name="飞书工作区文件夹 token")
```

### 权限翻转：召回 visibility 感知（pack_project_context 改造点）
```python
# Source: services/project_context_packer.py:101-110 现状（需改）
# 改前：if not await _is_member(project_id, user): return PackedContext()
# 改后（伪码）：
allowed = await _is_member(project_id, user)
if not allowed and getattr(project, "visibility", "") == ProjectVisibility.PUBLIC_ORG:
    allowed = True          # public_org 非成员可读召回
if not allowed:
    return PackedContext()  # members_only 维持 fail-closed
```

### 飞书 create_folder（镜像 create_document，需新增 — MEDIUM 待 live 验证）
```python
# Source: 镜像 services/feishu_doc.py::create_document（端点/返回结构需 live 验证）
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=60),
       retry=retry_if_exception_type(RateLimitError), reraise=True)
async def create_folder(self, name: str, folder_token: str) -> str:
    token = await self.get_tenant_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{self.OPEN_API_BASE}/drive/v1/files/create_folder",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"name": name, "folder_token": folder_token},
        )
        data = resp.json()
        if data.get("code") != 0:
            if data.get("code") == 99991400: raise RateLimitError(...)
            raise FeishuDocAPIError(...)
        return data["data"]["token"]
```

### 前端侧边栏插 tab + localStorage 记忆
```typescript
// Source: AppSidebar.vue mainNavItems（首页 index0、空间 index1 之间插入）
const mainNavItems: NavItem[] = [
  { to: '/', label: '首页', icon: 'lucide--home', exact: true },
  { to: '/projects', label: '项目', icon: 'lucide--folder-kanban' },  // 新增
  { to: '/spaces', label: '空间', icon: 'lucide--folder-git-2' },
  // ...
]
// projects/index.vue：所选空间记忆（@vueuse useLocalStorage，已有 'sidebar-collapsed' 范式）
const spaceFilter = useLocalStorage('projects-selected-space', '__all__')
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 项目读/召回 = 成员 fail-closed（v0.15.0 RECALL-03） | public_org 全员可读可问 + visibility 开关 + 写仍成员 | 本期（WS-02） | 召回闸需 visibility 分流，不可一刀切 |
| 后台长任务 = `background_runner` 兼 index/graph | 生产 index/graph 走 durable（Phase 61+）；`background_runner` 降级 SQLite dev/轻任务 | Phase 61 | 本期轻外呼任务用 `background_runner` 合适；重持久需求才考虑 durable |
| 飞书文档 = 只 `create_document` | 需补 `create_folder`（每项目专属文件夹） | 本期（WS-04） | 新增 API 方法 + live 验证 |

**Deprecated/outdated:** 无（本期全新增 + 字段扩展）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 飞书 `create_folder` 端点 `POST /drive/v1/files/create_folder`、body `{name, folder_token}`、返回 `data.token` | Pitfall 1 / Code Examples | 字段名/路径错 → 文件夹创建失败；plan 须 live 验证（参考飞书开放平台 Drive v1 文档） |
| A2 | 看板 description 经 `update_work_item_fields` 的某 field_key 写入、可读后追加 | Pitfall 6 | field_key 错 → 追加失败；live 验证工作项字段元数据 |
| A3 | `background_runner`（进程内、重启丢）对"建文件夹+5 文件 + broken 重建"足够，无需 durable | Pattern 3 / Don't Hand-Roll | 若要求重启后自动续跑则需 durable；但 broken 状态持久化 + 一键重建已覆盖（用户决策即"失败标 broken + 可重建"） |
| A4 | 无历史项目 → 不写 visibility 回填迁移 | Runtime State Inventory | 若实际存在历史项目则需回填（用户已明确无历史项目） |
| A5 | `ProjectDoc(memory)` 仅持飞书映射，记忆条目仍落 `ProjectMemory`（不重造） | phase_requirements DOC-01 | 用户/CONTEXT 已锁定，风险低 |

## Open Questions

1. **飞书 `create_folder` 单层 1500 上限兜底**
   - What we know：CONTEXT 把"分桶嵌套"deferred，本期单层。
   - What's unclear：达到上限时行为（报错码？）。
   - Recommendation：本期按单层实现，超限 → fail-soft 置 broken + warning，分桶留后续（CONTEXT 已 defer）。

2. **STATE/MILESTONES "活计算派生" 本期做到哪一步**
   - What we know：DOC-02/03 要派生 + 结构化 + 补充段；Phase 84 才做工作台前端渲染。
   - What's unclear：本期是否要落派生渲染，还是只建 `ProjectStateApi` 表 + `ProjectDoc` 容器。
   - Recommendation：本期建模型 + 写入 service + 首建飞书文件占位；活计算渲染落 Phase 83（同步）/84（前端）。plan 应明确边界。

3. **`ProjectStateApi` 写入来源**（HOOK-03 STATE 结构化回写是 Phase 86）
   - Recommendation：本期建模型 + service 写入入口 + 最小 REST（列表/手动增删），Cursor/hook 回写留 Phase 86。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| 飞书开放平台 app 凭证（Drive/Docx scope） | create_folder/create_document/看板写 | 运行期（Space/SystemSetting 配） | — | 未配 → 置 broken + 前端提示，不阻断建项目 |
| `services/background_runner` | 异步建文件夹/5 文件 | ✓（仓内模块） | — | — |
| 既有 `FeishuDocClient`/`FeishuClient` | 文档/工作项写 | ✓ | — | — |

**Missing dependencies with no fallback:** 无（飞书外呼失败均 fail-soft 置 broken）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-django + pytest-asyncio（`server/pyproject.toml`），respx（httpx mock），pytest-socket（网络隔离） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| Quick run command | `cd server && uv run pytest tests/initiatives/ -x` |
| Full suite command | `cd server && uv run pytest tests/initiatives/ tests/services/test_project_context_packer.py tests/test_chat_project_recall.py` |
| 前端 | `cd web && pnpm vitest run`（项目列表 `pages/projects/__tests__/projects-list.spec.ts` 已存在）+ `pnpm vue-tsc --noEmit` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WS-02 | public_org 非成员可召回；members_only 非成员零召回 | unit/async | `pytest tests/services/test_project_context_packer.py -x` | ✅（扩充已有 fail-closed 测试） |
| WS-02 | 非成员写记忆/StateApi 被拒（403/PermissionError） | unit/async | `pytest tests/initiatives/test_memory_inv6_guard.py tests/initiatives/ -k member` | ✅（既有成员闸测试） |
| WS-04 | 后台建文件夹+5 文件落 token；飞书失败置 broken | unit/async (respx) | `pytest tests/initiatives/test_project_doc_service.py -x` | ❌ Wave 0 |
| DOC-01~05 | 3 新模型唯一约束 + 写入收口 | unit | `pytest tests/initiatives/test_project_doc_service.py` | ❌ Wave 0 |
| INV-6 | 3 新模型无旁路写 | static grep | `pytest tests/initiatives/test_project_doc_inv6_guard.py` | ❌ Wave 0 |
| migration | `makemigrations --check` 干净 | smoke | `cd server && uv run python manage.py makemigrations --check --dry-run` | n/a |
| WS-01 | 侧边栏含「项目」tab（首页↓空间↑）；列表按所选空间 | unit (vitest) | `cd web && pnpm vitest run` | ✅（扩充 projects-list.spec.ts） |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/initiatives/ -x`
- **Per wave merge:** 上面 Full suite command + `makemigrations --check` + 前端 vitest/vue-tsc
- **Phase gate:** 全绿 + INV-6 guard（含新建）+ `makemigrations --check` 干净

### Wave 0 Gaps
- [ ] `tests/initiatives/test_project_doc_service.py` — ProjectDocService 写入 + provision + broken 路径（WS-04/DOC）
- [ ] `tests/initiatives/test_project_doc_inv6_guard.py` — 镜像 artifact 多模型 guard（覆盖 ProjectDoc/BlockMap/StateApi）
- [ ] 扩充 `tests/services/test_project_context_packer.py` — public_org vs members_only 对称用例
- [ ] 扩充 `tests/test_feishu_doc_errors.py` 或新增 — `create_folder` respx 形状 + 限流退避
- [ ] 扩充 `web/.../projects-list.spec.ts` — 所选空间 localStorage + 侧边栏 tab

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | yes | 读放宽按 `visibility`；写一律成员闸（`_assert_member`/Space admin）；fail-closed 默认 |
| V5 Input Validation | yes | DRF serializer 校验（visibility 闭集、method/path/status 枚举） |
| V7 Logging（脱敏） | yes | 飞书正文/快照入库 `redact_secrets_in_text`；审计 `redact_for_ledger`；日志 `redact_credentials` 自动 processor |
| V6 Cryptography | no（本期不碰凭证加密） | 复用既有 Fernet（Space app_secret），不新增 |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 权限翻转误放行 members_only 召回（信息泄漏） | Information Disclosure | visibility 分流 + 对称守护测试（public_org 放行 / members_only fail-closed） |
| 非成员写记忆/STATE/成员/文件 | Elevation of Privilege | 写路径成员闸不动（`MemoryService._assert_member` 等），新 StateApi/Doc 写同样成员/admin 校验 |
| 飞书正文/文档 token 泄漏进日志 | Information Disclosure | 入库脱敏 + 日志只记 doc_id/计数，不记正文/token 明文 |
| 后台任务归因丢失 | Repudiation | `run_in_background(initiated_by_user_id=...)` + worker re-bind；未知标 `system` |
| 旁路写新模型绕过审计 | Tampering | INV-6 grep guard（新建覆盖 3 模型） |

## 观测与日志强制项（本期必须）
- 新增 REST 入口（ProjectDoc 列表/重建、StateApi CRUD、visibility PATCH）→ 自动纳入 RequestMetric（统一中间件，无需手写）；写操作 `AuditService.aemit`（category=caller, component=initiatives, initiated_by_user_id）。
- 后台 provision 任务 → `structlog` `project_workspace_provision_started/completed/failed` + `duration_ms` + `initiated_by_user_id`；飞书外呼失败 `*_failed` warning（best-effort 不反噬）。
- 召回放宽 → 召回路径已写 `RetrievalTrace`（packer 内）；放宽后非成员命中也应能归因（仍写 trace，标 visibility）。
- 飞书上游响应体/异常文本 → `redact_secrets_in_text`；文档正文入库（如快照）→ 脱敏。
- 本期**无新增 LLM 调用**（不涉及 `call_source`）；无高频循环（无 INFO 刷屏风险）。

## Project Constraints (from .cursor/rules/)
- `.cursor/rules/observability-logging.mdc`（强制）：`structlog.get_logger(__name__)`、snake_case 事件名 + kv、`category`(caller/sampling) + `component`、绑定触发用户、脱敏不可绕过、best-effort 不反噬、关键生命周期带 `duration_ms`。新增 REST 入口纳入 QPS/错误率/时长；新增召回写 `RetrievalTrace`。
- INV-6（项目既有不变量）：领域模型零业务方法，写入收口单一 service + grep 守护。
- async ORM 一律 `sync_to_async`；i18n 默认中文（前端文案接 vue-i18n）。
- 凭证用 Fernet 加密、fail-closed 安全默认（沿用 v0.15.0 约定）。

## Sources

### Primary (HIGH confidence — 本仓真实源码已读)
- `server/initiatives/models/{project,member,memory}.py`、`models/__init__.py` — 模型范式 + 现有字段
- `server/initiatives/services/{project_service,memory_service,project_board_sync}.py`、`services/__init__.py` — INV-6 service 范式 + 后台外呼范式
- `server/tests/initiatives/test_{project,artifact}_inv6_guard.py` — guard 范式（单/多模型）
- `server/initiatives/{views,urls,serializers}.py` — REST/adrf 范式 + 现有 list 筛选
- `server/initiatives/permissions.py` + `server/services/project_context_packer.py` + `server/knowledge/access_scope.py` + `server/chat/config.py` — 权限/召回 fail-closed 现状（翻转落点）
- `server/services/feishu_doc.py` — FeishuDocClient（`create_document` 有、`create_folder` **无**）
- `server/services/feishu.py::update_work_item_fields` — 看板字段写签名
- `server/agents/tools/feishu_doc_tools.py::create_feishu_doc_client_for_project` — client 工厂（入参 Space）
- `server/projects/models.py::Space.feishu_doc_folder_token` — 父文件夹字段位置
- `server/services/background_runner.py` — `run_in_background(coro_factory, name=, initiated_by_user_id=)` + re-bind
- `server/initiatives/migrations/0005_*.py` — 最新迁移（新迁移 = `0006`，dependency `('initiatives','0005_mergerequest_mergerequestevent_projectmemory_and_more')`）
- `web/src/components/layout/AppSidebar.vue`、`web/src/pages/projects/index.vue`、`web/src/api/projects.ts` — 侧边栏/列表/API 现状

### Secondary (MEDIUM confidence — 需 live 验证)
- 飞书开放平台 Drive v1 `create_folder` 端点形态（A1）、工作项 description field_key（A2）

## Metadata

**Confidence breakdown:**
- 实体建模 + INV-6 service + guard：HIGH — 直接镜像 4 个已交付的同构实现
- 权限翻转落点：HIGH — 3 处 fail-closed 闸均已定位读取
- 后台任务归因：HIGH — `run_in_background` 已支持
- 飞书 `create_folder`：MEDIUM — 库内无实现，端点字段需 live 验证
- 前端 tab/localStorage：HIGH — 范式已在用

**关键数字（plan 直接用）：**
- 新迁移名：`0006_*`，dependency `('initiatives','0005_mergerequest_mergerequestevent_projectmemory_and_more')`
- 新 service：`initiatives/services/project_doc_service.py`；新 guard：`tests/initiatives/test_project_doc_inv6_guard.py`，`_MODELS=("ProjectDoc","ProjectDocBlockMap","ProjectStateApi")`
- 侧边栏插入位：`AppSidebar.vue` `mainNavItems` index 0(首页) 与 1(空间) 之间

**Research date:** 2026-06-26
**Valid until:** 2026-07-26（稳定领域代码；飞书 `create_folder` 端点 7 天内 live 验证为宜）

## RESEARCH COMPLETE
