# 88-01 SUMMARY — RepoAssociation/RepoVerifyTask 持久化与观测枚举地基

**Phase:** 88 智能业务关联仓库（v0.16.0）
**Plan:** 88-01（Wave 1，REPO-01/02 持久化基）
**Status:** ✅ 完成
**Date:** 2026-06-27

## 交付内容

### 净新增模型（D-05，INV-6 零业务方法）

- `server/initiatives/models/repo_association.py`（NEW）：
  - `RepoAssociationStatus`：`proposed/confirmed/verifying/verified/rejected`（覆盖 D-01 提案 → D-03 确认 → D-02 深验 → 终态/回退）。
  - `RepoAssociation`：业务级「项目↔仓库关联」真相源。`project` FK(CASCADE) 必填 + 可选 `work_item` FK(SET_NULL, D-06) + `repository` FK(CASCADE) + `status`/`score`/`confidence`/`routed_reason`/`source`/`matched_node_paths`/`initiated_by_user_id` + 时间戳。`db_table="initiative_repo_association"`、`unique_together=(("project","repository"),)`、索引 `["project","status"]`/`["repository"]`。
  - `RepoVerifyTaskStatus`：`pending/running/done/failed/stale`（逐字镜像 `RepoResearchTaskStatus`）。
  - `RepoVerifyTask`：per-repo 容器深验任务（D-02）。`association` FK(CASCADE, related_name=`verify_tasks`) + `repository` FK(CASCADE) + `subagent_session` FK(SET_NULL 回填) + `status`/`attempt`/`error` JSON/`verdict` JSON(schema `{fit,confidence,summary,evidence_files,mismatch_reasons}`)/`initiated_by_user_id` + 时间戳。`db_table="initiative_repo_verify_task"`、索引 `["association","status"]`/`["repository"]`。
  - 模型层**无** create/save/状态变更/校验方法（INV-6，写入收口留 88-02 `RepoAssociationService`）；跨 app FK 全字符串前向引用。
- `server/initiatives/models/__init__.py`（EXTEND）：re-export 四符号 + `__all__`。

### 枚举 / 观测

- `server/subagent/models.py`（EXTEND）：`SubAgentSession.TaskType.REPO_VERIFY = "repo_verify"`（便于 `observability_views` 按 task_type 区分容器深验；容器侧按 task_mode=explore 分流不读 task_type）。
- `server/agents/call_source.py`（EXTEND）：新增 `REPO_VERIFY_CONTAINER = "repo_verify_container"`（逐仓 explore 容器深验 LLM）+ `REPO_ASSOCIATION = "repo_association"`（候选细化/Agent 自处理 LLM）；模块/类 docstring「25 值」→「27 值」。既有 `AUX_REPO_ROUTER` 保留待 88-02 包裹。
- `.planning/observability/LOGGING-SPEC.md` §4.1（EXTEND）：追加 `repo_verify_container` / `repo_association` 两行。

### 迁移

- `server/initiatives/migrations/0010_repo_association.py`（NEW）：纯 `CreateModel`（RepoAssociation + RepoVerifyTask）+ AddIndex + AlterUniqueTogether，无 `RunPython`。依赖 initiatives 0009 + delivery/repositories/subagent 最新迁移（含 subagent 0014）。
- `server/subagent/migrations/0014_alter_subagentsession_task_type.py`（NEW）：`AlterField` task_type choices（无回填）。

### 测试

- `server/tests/initiatives/test_repo_association_models.py`（NEW）：唯一约束 `(project,repository)` IntegrityError、默认 status=proposed、verdict/error 默认空 dict、status 5 态、`TaskType.REPO_VERIFY` 存在、两个新 call_source normalize 命中。
- `server/tests/test_model_usage_call_source.py`（EXTEND）：基线 25 → 27（含 `repo_verify_container`/`repo_association`）。

## 验证结果

- `makemigrations --check --dry-run initiatives subagent`：No changes detected ✅
- `pytest tests/initiatives/test_repo_association_models.py`：7 passed ✅
- `pytest tests/test_model_usage_call_source.py`：25 passed ✅（基线断言 27）
- `ruff check`（改动文件）：All checks passed ✅
- 迁移纯 CreateModel/AlterField 无回填；模型层零业务方法（INV-6 由 88-02 guard 守护）✅

## call_source 基线

- 新增 2 值：`repo_verify_container`、`repo_association`
- 基线：25 → **27**

## 后续（不在本 plan）

- 88-02：`RepoAssociationService`（INV-6 写入收口）+ `RepoRouterV2` 补 `use_call_source(AUX_REPO_ROUTER)` 埋点 + `test_repo_association_inv6_guard.py`。
- 88-03+：`RepoVerifyDispatchService`（复刻 `ResearchDispatchAdapter`）、卡片 HITL 节点/回调。
