---
phase: 12-kmod
plan: "01"
status: complete
requirements_addressed: [KMOD-01, KMOD-02, KMOD-03]
subsystem: knowledge
tags: [django, models, migrations, bi-temporal, version-chain, test-infra]
dependency_graph:
  requires: []
  provides:
    - "knowledge Django app（INSTALLED_APPS 注册）"
    - "KnowledgeEntity / KnowledgeEntityVersion / KnowledgeEdge 三模型 + 全部 DB 约束/索引"
    - "EntityKind / EntityOrigin / EdgeRelation 枚举字面值（A3/A4 定案锁死）"
    - "generate_entity_id uuid5 唯一入口 + KNOWLEDGE_NAMESPACE"
    - "tests/knowledge/ 测试基建（entity/version/edge 工厂 + mock_qdrant_client seam）"
  affects:
    - "Plan 12-02（GraphStore 消费三模型与 conftest fixtures）"
    - "Plan 12-03（collection payload schema 与 conftest mock_qdrant_client）"
    - "Phase 13 摄取（natural key / generate_entity_id / 单 latest 契约）"
key-files:
  created:
    - server/knowledge/__init__.py
    - server/knowledge/apps.py
    - server/knowledge/models.py
    - server/knowledge/admin.py
    - server/knowledge/migrations/__init__.py
    - server/knowledge/migrations/0001_initial.py
    - server/tests/knowledge/__init__.py
    - server/tests/knowledge/conftest.py
    - server/tests/knowledge/test_models.py
  modified:
    - server/friday/settings.py
decisions:
  - "EntityKind 字面值锁定：work_item / tech_plan / code_change / document（进 uuid5 PK 派生，改名即数据迁移）"
  - "EdgeRelation 锁定六值，MODIFIES_CHUNK 为 Phase 14 占位"
  - "generate_entity_id 拼接格式 f\"{kind}:{source_kind}:{source_id}\" + 独立 KNOWLEDGE_NAMESPACE（不复用 code_relations NAMESPACE_REPO）"
  - "CodeChangeArchive 不预建（RESEARCH Open Question 1 定案，Phase 14 自带 migration）"
metrics:
  duration: ~10min
  tasks: 3
  files: 10
  tests: 22
completed: 2026-06-11
---

# Phase 12 Plan 01: 知识模型与测试基建 Summary

新建 `knowledge` Django app，三张地基表（实体 uuid5 稳定 PK / supersedes 版本链 / bi-temporal 四时间戳边）的全部不变量在 DB 层以 10 个约束 + 6 个索引兜底，并随 Wave 0 测试基建（4 个 conftest fixture + 22 条约束测试全绿）一次交付。

## What Was Built

- **`server/knowledge/models.py`（334 行）**：
  - `KnowledgeEntity`：uuid5 同源稳定 PK（`generate_entity_id` 唯一入口）、`(kind, source_kind, source_id)` natural key 唯一约束、kind/origin 枚举 DB CheckConstraint 双保险、project/repository FK（SET_NULL 防删项目抹历史）；docstring 锁定 natural key 规则表与双层引用原则。
  - `KnowledgeEntityVersion`：supersedes 自引用 FK（`on_delete=PROTECT`）、`(entity, version)` 唯一、`uniq_kversion_one_latest` 条件唯一（单 latest）、`kversion_valid_range` 时间次序；docstring 写明三条实现契约（非线性历史 / 并发撞约束是期望行为 / 版本链回溯只走 PG 不依赖 Qdrant）。
  - `KnowledgeEdge`：bi-temporal 四时间戳（valid_at/invalid_at + created_at/expired_at）、`uniq_kedge_active` 活跃边条件唯一、`kedge_target_xor` 实体边 XOR chunk 边、relation 枚举兜底、fanout/reverse/active 三索引。
- **`0001_initial.py`**：三表 + 全部约束/索引一次落库；`makemigrations --check --dry-run` 干净。
- **`settings.py`**：INSTALLED_APPS 注册 `"knowledge"`（紧邻 `"code_relations"`）。
- **`admin.py`**：三模型最小 ModelAdmin（list_display/list_filter/readonly_fields）。
- **`tests/knowledge/conftest.py`**：`entity_factory` / `version_factory` / `edge_factory` 闭包工厂 + `mock_qdrant_client`（QdrantService.get_client monkeypatch seam，非 autouse）；全部 aware datetime。
- **`tests/knowledge/test_models.py`**：22 条用例覆盖 KMOD-01/02/03 全部 DB 不变量（含 EXPLAIN QUERY PLAN 断言 `idx_kedge_fanout`），`-k version` 收集 6 条。

## Deviations from Plan

None - plan executed exactly as written.

（注：`pytest tests/knowledge/ --collect-only` 在 Task 2 时点退出码为 5——"no tests collected"，因测试文件属 Task 3 交付；conftest 导入无误，Task 3 落地后全套退出码 0。）

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `d42b94ad` | feat(12-01): 新建 knowledge app —— 三张地基表与全部 DB 约束 |
| 2 | `8b62a89c` | test(12-01): knowledge 测试基建（Wave 0）与 admin 最小注册 |
| 3 | `5f44edb1` | test(12-01): KMOD-01/02/03 约束、枚举兜底与版本链回溯全套测试 |

## Known Stubs

- `EdgeRelation.MODIFIES_CHUNK` 与 `KnowledgeEdge.target_chunk_id`：Phase 14 占位（docstring 已注明），本计划仅落枚举与字段 + XOR 约束测试，不交付写入路径——属计划内有意预留，不阻塞本计划目标。

## Threat Flags

None — 本计划交付面与 PLAN.md `<threat_model>` 一致（T-12-02/T-12-04/T-12-05 的 mitigate 均已落地：project/repository FK 第一天进模型、PROTECT + 置位语义有 ProtectedError 测试、枚举 TextChoices + CheckConstraint 双保险有直接 create 非法值测试），无新增安全面。

## Self-Check: PASSED

- 全部 10 个交付文件存在（models.py 334 行 ≥ 150）
- `uv run pytest tests/knowledge/ -x` → 22 passed
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected
- 四个关键约束（uniq_kentity_natural_key / uniq_kversion_one_latest / uniq_kedge_active / kedge_target_xor）在 models.py 命中 4 处
- 3 个任务 commit（d42b94ad / 8b62a89c / 5f44edb1）均在 git log
