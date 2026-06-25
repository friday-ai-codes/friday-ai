---
phase: 79
title: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联
milestone: v0.15.0
status: complete
completed: 2026-06-26
requirements: [ARTIFACT-01, ARTIFACT-02, ARTIFACT-03, ARTIFACT-04, ARTIFACT-05, KLINK-01, KLINK-02]
---

# Phase 79 SUMMARY — 工件 + RAG + 知识关联

## 落点决策

- 工件模型/服务全部落 **`initiatives` app**（与 `Project` 聚合根同域）；FK 字符串引用
  `"initiatives.Project"` / `"initiatives.ArtifactType"` / `settings.AUTH_USER_MODEL`。
- **复用知识脊柱**：工件正文 = `KnowledgeEntity(kind=document, source_kind="artifact")`；项目/仓库/空间
  作为图谱**参考节点**（新增 `EntityKind` 值），KLINK 边全部经 `KnowledgeEdge`/`graph_store`。
  **不改既有冻结枚举字面值**，仅新增值（触发 check 约束迁移），既有 uuid5 PK 零漂移。

## 新增模型（migrations）

| 模型 | 表 | 说明 |
|---|---|---|
| `initiatives.ArtifactType` | `initiative_artifact_types` | 可配置类型：key/name/carrier/ragable/enabled/builtin + 时间戳 |
| `initiatives.Artifact` | `initiative_artifacts` | 工件实例：project FK + type FK(**PROTECT**) + carrier + title + url + content_ref + version + contributor + 时间戳 |

- `ArtifactCarrier`：feishu_doc / feishu_bitable / external_link / markdown / repo_file；`TEXT_CARRIERS` = 前述去 external_link（可 RAG）。
- 迁移：
  - `initiatives/migrations/0003_artifacttype_artifact.py`（CreateModel ×2）
  - `initiatives/migrations/0004_seed_artifact_types.py`（**data migration seed**，内置 8 类 builtin=True，含 reverse 删除）
  - `knowledge/migrations/0007_remove_knowledgeentity_kentity_kind_valid_and_more.py`（EntityKind +project/repository/space、EntityOrigin +artifact/project → check 约束 `kentity_kind_valid`/`kentity_origin_valid` 重建）

**内置 8 类 seed**：需求文档(feishu_doc,rag) / feature list(feishu_bitable,rag) / 研发 Spec(markdown,rag) / **UI 稿(external_link,非 rag)** / UI 评审(feishu_doc,rag) / 埋点文档(feishu_doc,rag) / 埋点评审(feishu_doc,rag) / 复盘(feishu_doc,rag)。

## 服务 / 入口

- **`ArtifactService`（INV-6 单一写入）** `initiatives/services/artifact_service.py`：
  - 类型：`create_type` / `update_type`（禁用即 `enabled=False`）/ `delete_type`（**builtin 禁删 + 有实例拒删**双保护，DB `PROTECT` + service 预检 `ArtifactTypeError`）。
  - 工件：`create_artifact`（禁用类型不可建 `ArtifactDisabledError`；carrier 缺省取类型默认；ragable 文字载体 → 调度 RAG）/ `update_artifact`（禁用类型既有实例**只读**；内容变更版本递增 + 重摄取）/ `delete_artifact`。
  - 审计经 `AuditService.aemit`（component=initiatives, category=caller, initiated_by_user_id）；async ORM 走 `sync_to_async`。
- **在线查看读取** `initiatives/services/artifact_view.py` `aget_artifact_view`（只读）：飞书 doc → markdown 渲染、飞书 bitable → 记录、external_link → 元数据 + url、md/repo_file → content_ref；飞书正文 `redact_secrets_in_text` 脱敏；拉取失败 fail-soft（返回 error 字段不抛）。
- **项目知识图谱** `initiatives/services/knowledge_graph.py` `ProjectKnowledgeGraphService`：PROJECT/REPOSITORY/SPACE 参考节点唯一写者 + `link_knowledge`(KLINK-01) / `link_project`·`link_repository`·`link_space`(KLINK-02) / `sync_relations_from_operational`（从 Phase 77/78 操作态单向派生，**不双写**）/ `query_graph`（`graph_store.neighbors`/`traverse`，direction=both）。边幂等（neighbors 去重 + IntegrityError 放弃）；审计 `project.knowledge_linked`。

## RAG 摄取（ARTIFACT-04）

- 新 source `knowledge/sources/artifact.py`（镜像 `feishu_document.py`），注册 `"artifact"`：
  ragable 文字载体 → 拉正文（飞书 doc/表格经既有 service，md/repo_file 取 content_ref）→ **`redact_secrets_in_text` 脱敏** → `IngestionEvent(kind=document, origin=artifact)` + **工件→REFERENCES→项目图谱节点**出边（KLINK-01 锚）。
  UI 稿图形外链/非 ragable → 返回空列表（仅元数据，不强行 RAG）。fail-soft（飞书拉取失败 → 空正文，缺段不缺实体）。
  观测 `artifact_rag_normalize_started/completed` + `duration_ms` + 正文长度 + event 数（category=sampling, component=knowledge）；调度侧 `artifact_rag_scheduled`（category=caller）。
- `ArtifactService._maybe_schedule_ingestion` → `aschedule_ingestion(IngestionRequest(source_kind="artifact", ...))`（best-effort 不阻断写入）。

## REST API

- 工件（`/api/projects/<id>/artifacts/`）：GET 列表 / POST 创建 / GET·PATCH·DELETE 详情 / GET `view/` 在线查看。权限：读=Space viewer+ 或项目成员；写=Space admin+。
- 工件类型（`/api/artifact-types/`，**超管 CRUD**）：GET 列表（已认证）/ POST 新增 / PATCH 更新·禁用 / DELETE（builtin/有实例 → 409）。
- 知识关联：POST `/api/projects/<id>/knowledge/`（KLINK-01 关联知识）/ GET `/api/projects/<id>/graph/`（KLINK-02 查询，direction/relations/max_hops）。
- 新增 REST 入口经统一中间件自动纳入 QPS/错误率/时长指标。

## 审计词表

`audit/services/taxonomy.py` +7 action：`artifact_type.created/updated/deleted`、`artifact.created/updated/deleted`、`project.knowledge_linked`（纳入 `ALL_ACTIONS`）。

## 文件改动清单（25 文件）

- 新增源码（9）：`initiatives/models/artifact.py`、`initiatives/services/artifact_service.py`、`initiatives/services/artifact_view.py`、`initiatives/services/knowledge_graph.py`、`initiatives/artifact_type_urls.py`、`knowledge/sources/artifact.py`、`initiatives/migrations/0003_*.py`、`initiatives/migrations/0004_seed_artifact_types.py`、`knowledge/migrations/0007_*.py`。
- 修改源码（9）：`initiatives/models/__init__.py`、`initiatives/services/__init__.py`、`initiatives/serializers.py`、`initiatives/views.py`、`initiatives/urls.py`、`knowledge/models.py`、`knowledge/sources/__init__.py`、`audit/services/taxonomy.py`、`friday/urls.py`。
- 新增/修改测试（8）：`tests/initiatives/test_artifact_inv6_guard.py`、`test_artifact_type_service.py`、`test_artifact_service.py`、`test_artifact_view.py`、`test_project_knowledge_graph.py`、`test_artifact_api.py`、`tests/knowledge/test_artifact_source.py`、`tests/audit/test_audit_taxonomy.py`（扩展）。

## 测试结果

- **新增 39 用例全绿**：
  - INV-6 grep 守护（Artifact/ArtifactType 写表只经 ArtifactService，2）
  - 类型 CRUD/禁用/删除保护/builtin 禁删/有实例拒删 + seed 迁移定义 8 类（7）
  - 工件 CRUD/版本递增/禁用不可建/禁用只读/ragable 调度/图形不调度/删除（7）
  - 在线查看 md/外链/飞书 doc（mock）/拉取失败 fail-soft（4）
  - 项目图谱 link_knowledge(KLINK-01)+查询+幂等+缺实体 raise / link space·project·repo(KLINK-02) / sync_from_operational（6）
  - 工件 RAG 摄取（脱敏 + 边 + entity）/ 图形仅元数据 / 飞书失败 fail-soft（3）
  - API 工件 CRUD+查看+权限 fail-closed / 类型超管 / builtin 删 409 / KLINK link+query（8）
  - 审计词表（2）
- **全量后端**：**6352 passed / 39 failed / 61 skipped / 8 xfailed / 26 deselected**（411s）。
- **零新增回归**：38 failed == Phase-76 baseline（`/tmp/phase76_baseline_failures.txt` `comm` 逐条一致）。
  第 39 个失败 `tests/test_auto_index_trigger.py::test_webhook_dedup_same_sha` = **prompt 明示的"possible 1 flaky cross-suite ordering error"**：单跑通过；不含任何 Phase 79 测试时，仅 `tests/workflows/test_execution_concurrency.py`（baseline 失败的并发用例，泄漏 async context `SynchronousOnlyOperation`）在前即可复现该失败。Phase 79 代码不触 workflows/repositories/webhook 路径，非本期回归。
- `makemigrations --check --dry-run` 干净（`No changes detected`）。

## 偏差 / caveats

- KnowledgeEntity 的 PROJECT/REPOSITORY/SPACE 参考节点由 `ProjectKnowledgeGraphService` 直接 `get_or_create`（知识实体无 INV-6 grep 守护；本 service 是这三类节点唯一写者，已在 docstring 锁定）。边写入仍唯一经 `graph_store`。
- 飞书 bitable 在线查看/摄取按既有骨架返回原始记录（列结构解析留 v2 REL-03）；真实飞书 doc/表格凭证下的端到端在线查看与摄取人工验收为里程碑级 deferred。
- 富前端（工件查看器 / 类型管理页 / 关系图可视化）按 CONTEXT 留 Phase 81（UI-03）；本期只交付后端 + REST（含读取/渲染数据）。
