# Phase 76 Plan: 命名腾挪（Project→Space 重构前置）

**Created:** 2026-06-25
**Requirements:** RENAME-01, RENAME-02
**Hard constraints:** 数据零丢失（zero data loss）+ 行为/测试零回归（zero behavior/test regression）

## Baseline (pre-change)

`cd server && uv run pytest -q` → **6266 passed, 38 failed, 61 skipped, 8 xfailed**（耗时 ~7min）。

38 个失败为**既有失败（pre-existing）**，与本次重命名无关（repo summary 派生、prompts signals、hybrid retrieval 结构化日志、execution concurrency、comment/entry wiring、agent framework hybrid search 等）。完整清单存 `/tmp/phase76_baseline_failures.txt`，用于回归对比：**判定标准 = baseline 通过的用例不得在改动后失败**。

> 注：CONTEXT/ROADMAP 写的 "~520 后端测试" 为陈旧估计；真实后端套件 ~6300。

## Rename scope (LOCKED — from 76-CONTEXT.md + user directive)

### RENAME（释放 `Project` 命名空间）
| 旧 | 新 | 位置 | 迁移 |
|----|----|------|------|
| model `Project` | `Space` | `projects/models.py` | `RenameModel`（db_table=`projects` 保留） |
| model `ProjectRepository` | `SpaceRepository` | `projects/models.py` | `RenameModel`（db_table=`project_repositories` 保留） |
| model `ProjectMembership` | `SpaceMembership` | `permissions/models.py` | `RenameModel`（db_table=`project_memberships` 保留） |
| enum `ProjectRole` | `SpaceRole` | `permissions/models.py` | 无（TextChoices 不入库结构） |
| FK field `project` → `space` | 见下 14 处跨 app FK | `RenameField` |
| M2M related_name `projects` | `spaces` | `Space.repositories` | `AlterField`（无 SQL） |
| FK related_name `default_for_projects` | `default_for_spaces` | `Space.default_provider_credential_id` | `AlterField` |
| FK related_name `project_memberships` | `space_memberships` | `SpaceMembership.user` | `AlterField` |

跨 app `project` FK（全部指向 `projects.Project`，逐一 `RenameField` → `space`，related_name 不含 "project" 的保留）：
`workflows.Workflow`、`workflows.WorkflowExecution`、`workflows.AlertRule`、`chat.Conversation`、`delivery.WorkItem`、`delivery.IngestRun`、`mcp_tools.McpWorkItemContext`、`mcp_tools.McpWorkItemTechnicalPlan`、`prompts.Prompt`、`feishu.*`（2 处）、`knowledge.KnowledgeEntity`、`agents.AgentSession`、`runners.*`。

### KEEP（对外不变 / 内部辅助 / DB 不动 —— 命门）
- `feishu_project_key` / `feishu_project_simple_name` / feishu `project_key` 参数 —— 飞书侧概念，**不改**（Phase 77 复用）。
- 审计 `target_type="project"/"project_membership"/"project_repository"`、审计 payload dict key `{"project_id": ...}`、`scope="project"` choices、`ACTION_PROJECT_*` taxonomy —— 对外/留痕契约，**不改**。
- 权限类名 `IsProjectMember`/`IsProjectAdmin`/`ProjectRolePermission`、`PermissionService.has_project_access`/`get_user_projects`/`get_user_role`/`_get_project`、`ProjectScopedQuerysetMixin` —— 内部 helper 名，不占 `Project` 模型命名空间，不改（仅其内部对 model/field 的引用对齐）。
- `db_table`（`projects`/`project_repositories`/`project_memberships`）与所有数据列 —— `RenameModel` 因 db_table 显式保留为元数据级；`RenameField` 列重命名为元数据级 `ALTER ... RENAME COLUMN`，零数据搬迁、可逆。
- REST API 路径 / 前端 / i18n —— 已称 "space"，不动 `web/`（除非内部 import 真断）。

## Execution waves（每 wave 原子提交，`refactor(76): ...`）

- **Wave 1 — Models + migrations（数据核心）**
  1. 编辑 `projects/models.py`、`permissions/models.py` 及 14 个跨 app 模型文件：重命名 model 类、FK 字段 `project→space`、相关 related_name、字符串引用 `"projects.Project"→"projects.Space"`、`__all__`/`constraints`/`indexes`/`unique_together` 字段名。
  2. `yes | uv run python manage.py makemigrations`（自动确认 rename 探测）。
  3. 人工核验生成的迁移**仅含 `RenameModel`/`RenameField`/`AlterField`**，无 `DeleteModel`/`CreateModel`/`RemoveField`/`AddField`（否则手写）。
  4. `manage.py migrate`（sqlite 测试库）+ `manage.py check`。

- **Wave 2 — Code references**
  5. 脚本化重命名**大写类名**（`ProjectRepository`/`ProjectMembership`→`Space*`、`ProjectRole`(?!Permission)→`SpaceRole`、`\bProject\b`→`Space`），范围 `server/**/*.py`，**排除 `*/migrations/*`**，保护清单见上。
  6. `manage.py check` + import 冒烟；修任何 ImportError。

- **Wave 2b — 小写 FK 字段用法（test-driven）**
  7. 跑全量 pytest；`FieldError`（`filter(project=)`）与 `AttributeError`（`obj.project`/`obj.project_id`）逐一精确定位修复为 `space`/`space_id`，**不动**审计 dict key / feishu key。迭代至无新增失败。

- **Wave 3 — 验收**
  8. `uv run python manage.py makemigrations --check --dry-run` 干净。
  9. 全量 pytest 与 baseline diff：新增失败=0。
  10. `grep` 全 server 确认无残留 `projects.models.Project` 旧类名引用（除迁移历史）。
  11. 写 76-SUMMARY.md / 76-VERIFICATION.md，最终提交含 artifacts。

## Risk controls
- 迁移 rename-only：杜绝 drop/create → 数据零丢失（SC-1/SC-4）。
- 测试套件作为 FK 字段重命名的强校验网（FieldError/AttributeError 高噪可见）。
- 大写类名脚本带 word-boundary + 负向 lookahead 保护，排除 migrations。
- 对外契约（API/审计/飞书/i18n/前端）显式 KEEP 清单 → 零用户可见变化（SC-3）。
