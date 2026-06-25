---
phase: 79
title: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联
milestone: v0.15.0
status: passed
verified: 2026-06-26
requirements: [ARTIFACT-01, ARTIFACT-02, ARTIFACT-03, ARTIFACT-04, ARTIFACT-05, KLINK-01, KLINK-02]
---

# Phase 79 VERIFICATION

逐条把 ROADMAP「Phase 79 Success Criteria」4 条映射到证据。**status: passed**。

## Criterion 1 — ArtifactType 可配置注册表（内置 8 类 seed）+ 后台增删禁用；禁用不可新建、既有只读

**PASS.**
- 模型 `initiatives/models/artifact.py` `ArtifactType`（key/name/carrier/ragable/enabled/builtin）。
- seed 迁移 `0004_seed_artifact_types.py` 内置 8 类 builtin=True（含 reverse）；`test_seed_migration_defines_eight_builtin_types` 断言 8 类 + UI 稿非 rag/需求文档 rag。
- 增删禁用经 `ArtifactService.create_type/update_type/delete_type` + REST `/api/artifact-types/`（超管）。
- 禁用不可新建：`test_create_on_disabled_type_refused`（`ArtifactDisabledError`）；既有只读：`test_update_on_disabled_type_read_only`。
- 删除保护：builtin 禁删 `test_delete_builtin_type_refused` / API `test_builtin_type_delete_refused`(409)；有实例拒删 `test_delete_type_with_instances_protected`（service 预检 + DB `PROTECT`）。

## Criterion 2 — Artifact 实例挂项目（类型/载体/链接/标题/版本/贡献者）；飞书 doc·表格在线查看、外链跳转、md/内部可编辑

**PASS.**
- 模型 `Artifact`（project/type/carrier/title/url/content_ref/version/contributor）+ `ArtifactService.create/update/delete_artifact`（INV-6，grep 守护 `test_artifact_inv6_guard`）。
- 版本递增：`test_update_bumps_version_on_content_change`。
- 在线查看后端 API `aget_artifact_view` + `GET .../artifacts/<id>/view/`：飞书 doc 渲染 markdown（`test_view_feishu_doc_renders_markdown`，mock）、外链元数据（`test_view_external_link_metadata_only`）、md 内容（`test_view_markdown_returns_content`）、拉取失败 fail-soft（`test_view_feishu_doc_fetch_failure_fail_soft`）。
- md/内部可编辑：`update_artifact` content_ref 可写 + API PATCH（`test_admin_creates_and_lists_and_views_artifact` 链路）。

## Criterion 3 — 工件 RAG 摄取：文字载体全文进 delivery_knowledge；图形外链仅元数据

**PASS.**
- source `knowledge/sources/artifact.py`（注册 `"artifact"`）：ragable 文字载体 → `KnowledgeEntity(kind=document, source_kind="artifact")` 全文入 `delivery_knowledge`（复用 ingestion + chunking + vectors）+ 工件→REFERENCES→项目节点边；脱敏 `redact_secrets_in_text`；fail-soft。
- `test_markdown_artifact_ingested_with_redaction_and_edge`：实体 + 版本 + 脱敏（secret 不在正文）+ REFERENCES 边。
- 图形仅元数据：`test_graphic_artifact_metadata_only_no_ingestion`（external_link/非 rag → normalize 返回 []，无实体）；`test_graphic_artifact_skips_ingestion`（不调度）。
- 飞书失败 fail-soft：`test_feishu_doc_fetch_failure_fail_soft`（缺正文不缺实体）。
- 观测：`artifact_rag_normalize_started/completed` + duration_ms + 计数（category/component 已设）。

## Criterion 4 — 项目↔知识 M2M + 项目↔仓库/空间/知识/项目经 KnowledgeEdge 统一建模、可查询

**PASS.**
- `EntityKind` +project/repository/space、`EntityOrigin` +artifact/project（不改既有冻结字面值，check 约束迁移 `knowledge/0007`）。
- `ProjectKnowledgeGraphService`：KLINK-01 `link_knowledge`（项目↔知识，一知识可属多项目/一项目多知识，幂等）；KLINK-02 `link_project/link_repository/link_space`（均经 `KnowledgeEdge`）；`query_graph`（`graph_store` 多跳查询，direction=both）。
- 不双写：`sync_relations_from_operational` 从 Phase 77/78 操作态单向派生。
- 证据：`test_link_knowledge_creates_edge_and_query`、`test_link_knowledge_idempotent`、`test_link_space_and_project_and_repo`、`test_sync_relations_from_operational`；API `test_link_knowledge_and_query_graph`（POST 关联 + GET 图查询）。

## 回归与迁移证据

- 全量后端：6352 passed / 39 failed / 61 skipped / 8 xfailed / 26 deselected（411s）。
- 零新增回归：38 failed == Phase-76 baseline（`comm` 逐条一致）；第 39 个 `test_auto_index_trigger::test_webhook_dedup_same_sha` 为 prompt 明示的 flaky cross-suite ordering error——单跑通过、无 Phase 79 测试时由 baseline 并发用例 `test_execution_concurrency` 在前即复现，非本期回归。
- 新增 39 用例全绿。
- `makemigrations --check --dry-run` 干净。
- 新迁移：`initiatives/0003_artifacttype_artifact.py`、`initiatives/0004_seed_artifact_types.py`（seed）、`knowledge/0007_remove_knowledgeentity_kentity_kind_valid_and_more.py`。

## human_needed（里程碑级 deferred）

- 真实飞书 doc/表格凭证下的在线查看与 RAG 摄取端到端人工验收（需真实飞书应用 + 文档/多维表格）。
- 飞书 bitable 列结构解析（当前返回原始记录，列解析留 v2 REL-03）。
