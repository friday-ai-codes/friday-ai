# Phase 76: 命名腾挪（Project→Space 重构前置） - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure/refactor phase (auto-generated, decisions at agent discretion within locked constraints)

<domain>
## Phase Boundary

把后端 `projects` app 中的领域模型类 `Project` 重命名为 `Space`（前端/对外早已称"空间 Space"，本期消化历史命名债），腾出 `Project` 这个名字给 Phase 77 新建的「项目聚合根」。全栈内部 `project→space` 引用一致更新，**数据零丢失、行为与测试基线零回归**。

**In scope:**
- 后端模型类 `projects.models.Project` → `Space`；through 模型 `ProjectRepository` → `SpaceRepository`（db_table 保持，避免数据搬迁）
- 成员模型（当前 `members_*.py` 中的 membership）相应 `project` 字段/related_name → `space`
- 全栈内部符号：serializers / views / permissions / `agents/tools/space_tools.py` / workflow `fetch_space_info` / 各 FK（`WorkItem.project` / `Conversation.project` / `Workflow.project` / `Repository` M2M `related_name`）一致更新为 `space`
- 单一 `RenameModel` / `RenameField` 迁移（db_table 与列名保持 → DB 层无数据搬迁）

**Out of scope（留 Phase 77+）:**
- 新建任何「项目聚合根」实体或新功能
- 对外 API 路径 / 前端路由 / i18n 文案变化（继续称"空间 Space"，零用户可见变化）
- 修改业务逻辑、新增字段
</domain>

<decisions>
## Implementation Decisions

### 重命名策略（数据零丢失命门）
- **保持 `db_table = "projects"` 与所有列名不变** —— 迁移走 `migrations.RenameModel("Project", "Space")` + `RenameField`（through/membership 的 `project`→`space`），因 db_table/列名显式保持，DB 层为元数据级无数据搬迁，既有数据零丢失。
- **保持 Django app label 为 `projects`** —— 不重命名 app（app label 重命名牵连 `content_types`/`migrations` 依赖图，风险与本期目标不成比例）。只重命名 app 内的**模型类**与**字段引用**。
- through 模型 `ProjectRepository` → `SpaceRepository`、`db_table = "project_repositories"` 保持。
- 成员 through/模型中的 `project` FK 字段 → `space`（`RenameField`），related_name 同步（如 `ProjectMembership` → `SpaceMembership`，related_name `members`/`memberships` 保持语义）。

### 引用一致性（零回归命门）
- 跨 app 的 FK 字段名（`WorkItem.project` / `Conversation.project` / `Workflow.project`）→ `space`，并出 `RenameField` 迁移；`related_name`（如 `Repository.projects` M2M）→ `spaces`，调用方一致更新。
- 字符串引用 `"projects.Project"` → `"projects.Space"`（app label 不变，只换模型名）。
- 服务/工具/工作流节点中已用 "space" 语义的（`space_tools.py`/`fetch_space_info.py`/`space_resolver.py`/`test_conversation_space_switch.py`）核对对齐到新模型类，消除 `Project`/`space` 混用。

### 对外不变（兼容命门）
- 前端、REST API 路径、i18n 文案继续称"空间 Space"，无用户可见行为变化（SC-3）。
- 若现有对外路由/序列化字段已是 `project` 命名且前端在用，**对外契约保持原样**，仅内部 Python 符号重命名（不破坏前端）。冲突处优先"对外零变化"。

### 验收（必须全绿）
- 后端 ~520 + 前端 ~130 测试基线全绿；`python manage.py makemigrations --check --dry-run` 干净（无未生成迁移）。
- `grep` 全 server 确认无残留对 `projects.models.Project` 旧类名的 import/引用（除迁移历史文件）。

### 观测/约束（强制规范）
- 纯重命名不新增 LLM/召回/请求入口，无新增埋点需求；不得引入行为变化即不触发观测义务。
- 迁移可逆（reverse migration 能回退），release checklist 保留 `check_v81_legacy_residue` 等既有命令不动。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/projects/`：`models.py`（`Project`/`ProjectRepository`/`RepositoryPermission`）、`serializers.py`、`views.py`、`members_serializers.py`、`members_views.py`、`urls.py`、`migrations/`（至 0009）。
- 已部分采用 "space" 语义的下游：`server/agents/tools/space_tools.py`、`server/workflows/nodes/data/fetch_space_info.py`、`server/delivery/services/space_resolver.py`、`web/src/pages/spaces/`。

### Established Patterns
- Django app = bounded context，模型在 `<app>/models/`；FK 用字符串引用 `"app.Model"`；migration 自动生成。
- 约 140 个 server 文件 import 或引用 `projects`（含 ~80 测试文件）—— 引用面广但多为 import 路径与字段名。

### Integration Points
- 跨 app FK：`delivery.WorkItem.project`、`chat.Conversation.project`、`workflows.Workflow.project`、`repositories.Repository` M2M。
- Provider 凭证：`Project.default_provider_credential_id` → `system.ProviderCredential`（related_name `default_for_projects` → `default_for_spaces`）。
- 飞书：`feishu_project_key` 字段名属对外/飞书语义，**保留不改**（避免破坏飞书集成与 Phase 77 复用）。
</code_context>

<specifics>
## Specific Ideas

- `feishu_project_key` 是飞书侧概念字段，**不**在本期重命名（Phase 77 新聚合根也会复用该飞书 key 语义）。
- 优先用 Django `RenameModel`/`RenameField` 迁移而非删表重建，确保零数据搬迁。
- 重命名应作为独立可回退 PR（STATE.md Operator Next Steps 已建议）。
</specifics>

<deferred>
## Deferred Ideas

- 新建「项目聚合根」`Project` 实体与一切新功能 → Phase 77+。
- app label 由 `projects` 改为 `spaces`（如未来想彻底统一）→ 非本期目标，风险不成比例。
</deferred>
