---
phase: 79
title: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联
milestone: v0.15.0
status: planned
requirements: [ARTIFACT-01, ARTIFACT-02, ARTIFACT-03, ARTIFACT-04, ARTIFACT-05, KLINK-01, KLINK-02]
---

# Phase 79 PLAN — 工件 + RAG + 知识关联

## 目标回顾（4 条 Success Criteria）

1. `ArtifactType` 可配置注册表（内置 8 类 seed），后台增删禁用；禁用类型不可新建实例、既有只读。
2. `Artifact` 实例挂项目（类型/载体/链接/标题/版本/贡献者）；飞书 doc/表格在线查看渲染、外链跳转、md/内部可编辑。
3. 工件 RAG 摄取——文字载体全文进 `delivery_knowledge`；UI 稿图形外链仅元数据。
4. 项目↔知识 M2M + 项目↔仓库/空间/知识/项目经 `KnowledgeEdge` 统一建模、可查询。

## 锁定设计决策（落实 CONTEXT）

- 模型落 `initiatives` app；FK 字符串引用 `"initiatives.Project"` / `settings.AUTH_USER_MODEL` / `"initiatives.ArtifactType"`。
- **ArtifactService 单一写入入口（INV-6）**：`ArtifactType` + `Artifact` 全部 create/update/delete 收口，grep 守护。模型层无业务方法。
- 类型删除双重保护：`Artifact.type` FK `on_delete=PROTECT`（DB 兜底）+ service 预检（有实例拒删 / builtin 禁删只可禁用）。
- 知识脊柱复用：`EntityKind` 增 `project`/`repository`/`space`（图谱节点）；`EntityOrigin` 增 `artifact`（工件知识）/`project`（投影参考节点）。**不改既有冻结字面值**；新增值仅触发 check 约束迁移。
- 工件知识实体 kind = `DOCUMENT`，source_kind = `"artifact"`，source_id = `str(artifact.id)`（`generate_entity_id` 派生，与 feishu_document 不撞）。
- 工件 RAG 摄取镜像 `sources/feishu_document.py`：飞书正文经 `redact_secrets_in_text` 脱敏后入图；fail-soft（缺正文不缺工件）；started/completed/failed + duration_ms + 计数观测。
- 项目作为图谱节点 + KLINK 边经 `ProjectKnowledgeGraphService`（PROJECT/REPOSITORY/SPACE 参考节点唯一写者）+ `graph_store`（边唯一写者）。**不与 Phase 77/78 操作态表双写**——边由 service 单向派生/补建。查询用 `direction="both"`，方向不敏感。

## Waves

### Wave 1 — 模型 + seed 迁移（ARTIFACT-01/02 地基）
- `initiatives/models/artifact.py`：`ArtifactCarrier` + `ArtifactType` + `Artifact`。
- `initiatives/models/__init__.py` 导出。
- 迁移 `0003_artifacttype_artifact`（CreateModel ×2）。
- 迁移 `0004_seed_artifact_types`（data migration，8 builtin，reverse 删 builtin）。
- commit `feat(79): ArtifactType/Artifact 模型 + 内置 8 类 seed 迁移`

### Wave 2 — ArtifactService（INV-6 + 禁用/删除保护，ARTIFACT-01/05）
- `initiatives/services/artifact_service.py`：类型 CRUD（禁用即 enabled=False；删除 builtin/instance 双保护）+ 工件 CRUD（禁用类型不可建/只读、版本递增、调度 RAG）。审计 component=initiatives。
- `audit/services/taxonomy.py`：+ artifact_type.*/artifact.* + project.knowledge_linked。
- `initiatives/services/__init__.py` 导出。
- commit `feat(79): ArtifactService 单一写入 + 类型禁用/删除保护 + 审计`

### Wave 3 — 在线查看读 API + REST CRUD（ARTIFACT-02/03）
- `initiatives/services/artifact_view.py`：`aget_artifact_view`（飞书 doc/bitable 经既有 service 读取渲染 / 外链元数据 / md·repo_file content_ref）。
- `initiatives/serializers.py`：Artifact* / ArtifactType* serializers。
- `initiatives/views.py`：Artifact CRUD + view + 类型管理（超管）+ KLINK 视图。
- `initiatives/urls.py` + `initiatives/artifact_type_urls.py` + `friday/urls.py` 接线。
- commit `feat(79): 工件在线查看读 API + 工件/类型 REST CRUD`

### Wave 4 — 工件 RAG 摄取（ARTIFACT-04）
- `knowledge/models.py`：EntityKind/EntityOrigin 增值 + generate_entity_id natural key 文档。
- 迁移 `knowledge/0007_*`（check 约束更新）。
- `knowledge/sources/artifact.py`：normalizer（脱敏 + fail-soft + 观测 + 工件→REFERENCES→项目节点边）。
- `knowledge/sources/__init__.py` 注册 `"artifact"`。
- ArtifactService 调 `aschedule_ingestion`（ragable 文字载体）。
- commit `feat(79): 工件 RAG 摄取 source + 脱敏 + fail-soft + 观测`

### Wave 5 — 知识图谱节点 + KLINK 边 + 查询 API（KLINK-01/02）
- `initiatives/services/knowledge_graph.py`：`ProjectKnowledgeGraphService`（参考节点 + link_knowledge/link_project/link_repository/link_space + query_graph）。
- ArtifactService 创建工件后 `link` 工件知识（经 normalizer 边）；KLINK link/query 视图接线。
- commit `feat(79): 项目图谱节点 + KLINK 边 + 查询 API`

### Wave 6 — 测试
- `tests/initiatives/test_artifact_inv6_guard.py`、`test_artifact_type_service.py`、`test_artifact_service.py`、`test_artifact_view.py`、`test_artifact_api.py`、`test_project_knowledge_graph.py`
- `tests/knowledge/test_artifact_source.py`
- `tests/audit/test_audit_taxonomy.py`（扩展）
- commit `test(79): 工件类型/实例/RAG/KLINK 守护测试`

## 验证
- `makemigrations --check --dry-run` 干净（含 knowledge check 约束 + initiatives 模型 + seed）。
- `uv run pytest -q`：baseline 38 failed 不变（零新增回归），新增用例全绿。
