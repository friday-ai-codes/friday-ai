# Phase 76 Summary: 命名腾挪（Project→Space 重构前置）

**Completed:** 2026-06-25
**Requirements:** RENAME-01, RENAME-02
**Result:** ✅ 数据零丢失 + 行为/测试零回归

## What changed

把后端领域模型 `projects.Project` 重命名为 `Space`，全栈 `project→space` 内部引用一致更新，腾出 `Project` 名给 Phase 77。

### 模型 / 字段重命名
- `projects.models.Project` → **`Space`**（`db_table="projects"` 保留）
- `projects.models.ProjectRepository` → **`SpaceRepository`**（`db_table="project_repositories"` 保留），FK `project`→`space`
- `permissions.models.ProjectMembership` → **`SpaceMembership`**（`db_table="project_memberships"` 保留），FK `project`→`space`，User related_name `project_memberships`→`space_memberships`
- `permissions.models.ProjectRole` → **`SpaceRole`**（TextChoices）
- 跨 app FK 字段 `project`→`space`（`RenameField`）：`workflows.Workflow` / `workflows.WorkflowExecution` / `workflows.AlertRule` / `chat.Conversation` / `delivery.WorkItem` / `delivery.IngestRun` / `mcp_tools.McpWorkItemContext` / `mcp_tools.McpWorkItemTechnicalPlan` / `prompts.Prompt` / `feishu.TriggerLog` / `feishu.FeishuBotThread` / `knowledge.KnowledgeEntity` / `agents.AgentSession` / `runners.RegistrationToken`
- M2M 字段/related_name：`Space.repositories` related_name `projects`→`spaces`；`Runner.projects`→`spaces`；`Space.default_provider_credential_id` related_name `default_for_projects`→`default_for_spaces`

### 内部 DTO（同步重命名以消除 project/space 混用）
- `feishu.bot.project_resolver.ProjectResolution.project` → `space`
- `feishu.bot.service.ProjectContextDecision.project` → `space`
- `workflows.triggers.context.TriggerContext.project` → `space`
- `knowledge` 摄取 DTO（`IngestionEvent` / `EntityMetadata` 等）字段 `project_id` → `space_id`

### 对外契约保持不变（SC-3）
- REST 序列化字段：`workflows`/`AlertRule`/`WorkItem` serializer 仍对外暴露 `project` 字段（经 `source="space"` 显式映射），chat `space_id` 字段保持；前端 `web/` 零改动。
- 审计 `target_type="project"/"project_membership"/"project_repository"`、`scope="project"` choices、Qdrant payload key `"project_id"`、reverse-lookup 结果 key `"project_id"`、飞书 `feishu_project_key`/`project_key`、API query `?space_id=` 等全部保持。
- 内部 helper 名保留：`PermissionService.has_project_access`/`get_user_projects`、`IsProjectAdmin`/`IsProjectMember`/`ProjectRolePermission`、`ProjectScopedQuerysetMixin`、`render_prompt(project_id=)` 等函数参数名。

## Migrations created (11 — 全部元数据级 rename，零数据搬迁)

| App | Migration |
|-----|-----------|
| projects | `0010_rename_project_to_space` |
| permissions | `0002_rename_projectmembership_to_spacemembership` |
| workflows | `0031_rename_project_to_space` |
| chat | `0026_rename_project_to_space` |
| delivery | `0025_rename_project_to_space` |
| mcp_tools | `0009_rename_project_to_space` |
| prompts | `0010_rename_project_to_space` |
| feishu | `0005_rename_project_to_space` |
| knowledge | `0006_rename_project_to_space` |
| agents | `0004_rename_project_to_space` |
| runners | `0007_rename_project_to_space` |

**操作类型统计（无 DeleteModel/CreateModel/RemoveField/AddField）：** 3×RenameModel、17×RenameField、14×AlterField（related_name/verbose 同步）、10×RemoveIndex+10×AddIndex（命名索引重命名）、2×RemoveConstraint+2×AddConstraint（唯一约束重命名）、1×AlterModelOptions。

> SQLite 命门：每个含命名索引/约束的 rename 迁移内部按 `RemoveIndex/RemoveConstraint → RenameField → AddIndex/AddConstraint` 排序，规避表重建时重建引用旧字段的索引。`projects/0010` 显式依赖全部「创建指向 `projects.Project` 的 FK」的迁移，确保 `RenameModel` 在跨 app FK 进入状态后执行（避免拓扑悬空引用）。

## Test results

- **Baseline（改动前）:** 6266 passed, **38 failed**, 61 skipped, 8 xfailed（~6:40）。
- **改动后（最终）:** **6266 passed, 38 failed**, 61 skipped, 8 xfailed（~6:35）。
- **回归对比:** 新增失败 = **0**；38 个失败与 baseline **逐条一致**（`comm` 差集为空）。
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（干净）。
- 全新 sqlite 库 `migrate` 全部 289 迁移 OK；`manage.py check` 0 issues。
- `grep` 全 server 确认无残留 `Project`/`ProjectRepository`/`ProjectMembership`/`ProjectRole` 旧模型类引用（除迁移历史文件）。

### 既有失败（pre-existing，与本期无关，存 `/tmp/phase76_baseline_failures.txt`）
38 条，集中于：repo summary 状态派生 / `_active_summary_tasks` import、prompts signals、hybrid retrieval 结构化日志、execution concurrency、comment/entry wiring、sensitive suggestions、branch indexer、data foundation、agent_framework hybrid search。均为环境/既有问题，改动前后同样失败。

## Files touched

~355 处改动：非测试非迁移源码 **141** 个、测试文件 **187** 个、新增迁移 **11** 个，加规划 artifacts。

> 注：CONTEXT/ROADMAP 写的 "~520 后端测试" 为陈旧估计；真实后端套件 6266 passed。
