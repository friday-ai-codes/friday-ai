---
status: passed
phase: 76
verified: 2026-06-25
---

# Phase 76 Verification: 命名腾挪（Project→Space 重构前置）

**Verdict:** ✅ **passed** — 全部 4 条 Success Criteria 成立，后端测试零回归，迁移元数据级零数据丢失。

## Success Criteria → Evidence

### SC-1 — `projects.Project` 重命名为 `Space`，数据零丢失，既有"空间"功能行为零回归 ✅
- `projects.models.Project` → `Space`、`ProjectRepository` → `SpaceRepository`，`db_table="projects"` / `"project_repositories"` **显式保留**。
- 迁移 `projects/0010` + `permissions/0002` + 9 个跨 app 迁移共 **3×RenameModel / 17×RenameField / 14×AlterField / 10×Add+10×RemoveIndex / 2×Add+2×RemoveConstraint / 1×AlterModelOptions**，**零** `DeleteModel`/`CreateModel`/`RemoveField`/`AddField` —— DB 层为元数据级（表名保留→无表搬迁；列重命名为 `ALTER ... RENAME COLUMN`）→ **既有数据零丢失、可逆**。
- 全新 sqlite 库从零 `migrate` 全部 289 迁移 OK（无 DROP/CREATE 数据表）。
- 飞书凭证 / Provider 默认（`default_provider_credential_id` related_name→`default_for_spaces`）/ 仓库 M2M（`spaces`）/ 三角色成员权限（`SpaceMembership`/`SpaceRole`，`has_project_access` 逻辑不变）相关测试全绿。

### SC-2 — 全栈 `project→space` 内部引用一致更新 ✅
- serializers / views / permissions（`PermissionService`/`api_permissions`/`mixins`）/ `agents/tools/space_tools` / workflow `fetch_space_info` / 各 FK（`WorkItem.space`/`Conversation.space`/`Workflow.space`/`SpaceRepository`/`SpaceMembership`/`Repository` M2M `spaces`/`Runner.spaces`）全部对齐。
- `grep` 全 server（除迁移历史）**无残留** `Project`/`ProjectRepository`/`ProjectMembership`/`ProjectRole` 旧模型类引用，亦无 `.project`/`filter(project=)`/`project__`/`select_related("project")` 等旧字段用法（保留项除外）。

### SC-3 — 对外（前端 / API / i18n）继续称"空间 Space"，无用户可见行为变化 ✅
- REST 序列化对外字段保持：workflow/AlertRule/WorkItem serializer 仍暴露 `project`（`source="space"` 显式映射），chat `space_id` 字段不变；**`web/` 零改动**。
- 审计 `target_type`/`scope="project"` choices/Qdrant payload key/reverse-lookup 结果 key/`feishu_project_key`/API query `?space_id=` 等对外契约逐一保留。
- 前端 130 测试基线不受影响（未改 `web/`）。

### SC-4 — 后端测试基线全绿；`makemigrations --check` 干净 ✅
- 后端：**6266 passed / 38 failed**（与 baseline 逐条一致，新增失败 **0**）/ 61 skipped / 8 xfailed。
- `manage.py makemigrations --check --dry-run` → **No changes detected**。
- 38 个 failed 为**既有失败（pre-existing）**，与本次重命名无关（证据：改动前同样失败，清单 `/tmp/phase76_baseline_failures.txt`；领域为 repo summary / hybrid 日志 / prompts signals / concurrency / comment wiring 等）。
  > 说明：ROADMAP 写的 "~520 后端测试" 为陈旧估计，真实套件为 6266 passed。

## Notes / Risk controls applied
- SQLite 表重建顺序命门：rename 迁移内 `RemoveIndex/RemoveConstraint → RenameField → AddIndex/AddConstraint`。
- 跨 app lazy-ref 命门：`projects/0010` 依赖全部 FK 创建迁移，保证 `RenameModel` 在引用进入状态后执行。
- 内部 DTO（`ProjectResolution`/`ProjectContextDecision`/`TriggerContext`/knowledge `IngestionEvent`/`EntityMetadata`）字段一并对齐，消除 project/space 混用。
- 函数参数名 `project`/`project_id`（`aresolve_*`/`render_prompt`/`ingest_from_table` 等）与对外字段刻意保留，避免破坏调用方与前端。

## Human follow-up
- 无阻断项。真机/真实 Postgres 升级验证（rename 迁移在 Postgres 上同为元数据级）建议纳入发布前 checklist；本期已在 SQLite 全量 migrate + 测试套件验证。
