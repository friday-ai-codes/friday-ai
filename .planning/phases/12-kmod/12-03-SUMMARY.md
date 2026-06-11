---
phase: 12-kmod
plan: "03"
status: complete
requirements_addressed: [KMOD-01]
subsystem: knowledge
tags: [qdrant, collection-lifecycle, payload-schema, management-command, fail-loud]
dependency_graph:
  requires:
    - "Plan 12-01（knowledge app + tests/knowledge/ 基建，含 mock_qdrant_client seam）"
  provides:
    - "DELIVERY_KNOWLEDGE_COLLECTION / KNOWLEDGE_PAYLOAD_INDEXED_FIELDS / KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS 单一事实源常量"
    - "ensure_delivery_knowledge_collection：缺失创建 / 匹配通过 / 不匹配响亮拒绝（绝不删库）"
    - "KnowledgeError 基类 + KnowledgeCollectionMismatchError"
    - "rebuild_delivery_knowledge 显式重建命令（--yes 确认流程）"
    - "SettingKeys.KNOWLEDGE_COLLECTION_META（collection 元信息 JSON）"
  affects:
    - "Phase 13 摄取（import payload schema 常量写入 point；调用 ensure）"
    - "Phase 15 检索（import 同一份 schema 常量做强制过滤，含权限维度）"
key-files:
  created:
    - server/knowledge/exceptions.py
    - server/knowledge/collection.py
    - server/knowledge/management/__init__.py
    - server/knowledge/management/commands/__init__.py
    - server/knowledge/management/commands/rebuild_delivery_knowledge.py
    - server/tests/knowledge/test_collection.py
  modified:
    - server/system/models.py
decisions:
  - "payload schema 8 索引字段第一天定型（entity_kind/entity_id/version/is_latest/project_id/repository_id/source_kind/event_time），回归测试锁键集合，增删必须显式过审"
  - "ensure 语义与 indexer 刻意相反：mismatch → raise KnowledgeCollectionMismatchError（绝不 delete/recreate）；异常一律重抛（无 return False 静默语义）"
  - "重建唯一入口 manage.py rebuild_delivery_knowledge --yes；无 --yes 仅打印 WARNING 横幅零副作用"
  - "collection 元信息（model/dimension/schema_version=1）存 SystemSetting knowledge_collection_meta；匹配通过时缺失补写（升级路径）"
metrics:
  duration: ~8min
  tasks: 3
  files: 7
  tests: 9 (+40 既有不回归)
completed: 2026-06-11
---

# Phase 12 Plan 03: delivery_knowledge collection 生命周期 Summary

delivery_knowledge Qdrant collection 的显式生命周期管理落地（ROADMAP SC#5）：payload schema（含 project_id/repository_id 权限维度）以单一事实源常量第一天定型并有回归测试锁定；ensure 函数在维度/hybrid 结构不匹配时 raise `KnowledgeCollectionMismatchError` 响亮拒绝且零删库路径（与既有 indexer 自动重建语义刻意相反）；重建唯一入口为 `manage.py rebuild_delivery_knowledge --yes`。

## What Was Built

- **`server/knowledge/exceptions.py`**：`KnowledgeError` 基类（message + details dict + `__str__` 拼 details，agents/core 同型）+ `KnowledgeCollectionMismatchError`（docstring 写明"抛出即拒绝，不得捕获后自动重建"契约）。
- **`server/knowledge/collection.py`（约 220 行）**：
  - `DELIVERY_KNOWLEDGE_COLLECTION = "delivery_knowledge"`、`KNOWLEDGE_SCHEMA_VERSION = 1`；
  - `KNOWLEDGE_PAYLOAD_INDEXED_FIELDS`：8 字段 → `PayloadSchemaType` 映射（KEYWORD×5 / INTEGER / BOOL / DATETIME）；`KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS`：6 个非索引必带字段元组（Phase 13 写入契约）；
  - 模块 docstring 锁定三条边界：schema 为 Phase 13/15 单一事实源、`is_latest` 只服务召回面（P10）、权限维度字段第一天定型不许回填（P6）；
  - `ensure_delivery_knowledge_collection()`（async）：EMBEDDING_DIMENSION 经 SystemSetting 读取（default 1024，indexer 同款）；client 唯一路径 `QdrantService.get_client()`，同步调用全部 `sync_to_async` 包装；缺失 → hybrid（dense+sparse）创建 + 8 个 payload index 循环 + 元信息 `aupdate_or_create` 落库 + `knowledge_collection_created` 事件；存在 → `get_collection` 严格比对（dict ⇒ hybrid、`.get("dense").size` 取维度），不匹配 → `knowledge_collection_config_mismatch` error 事件 + raise（message 含现有/期望维度与 `rebuild_delivery_knowledge --yes` 指引）；匹配 → 元信息缺失补写；任何 Qdrant 异常向上冒泡。
- **`server/system/models.py`**：`SettingKeys.KNOWLEDGE_COLLECTION_META = "knowledge_collection_meta"`（value 为 JSON：model/dimension/schema_version）。
- **`rebuild_delivery_knowledge` 命令**：无 `--yes` → init_superuser 同款 `"=" * 60` WARNING 横幅打印将发生什么后直接 return（退出码 0，零副作用）；带 `--yes` → `asyncio.run(_rebuild())`：`delete_collection_by_name` → `ensure_delivery_knowledge_collection()` → SUCCESS 输出新维度；structlog `rebuild_delivery_knowledge_started/finished` 始末事件；异常不吞；docstring 留 Phase 13"从 PG 全量重嵌入"TODO 锚点。
- **`server/tests/knowledge/test_collection.py`（9 用例，Qdrant 全 mock）**：缺失创建（create 一次 + payload index 调用数 == 8 + 元信息 JSON 含 dimension）/ 匹配通过 / 维度 768 vs 1024 不匹配 raise 且 `delete_collection.assert_not_called()`（P8 核心断言，message 断言 768/1024/--yes）/ 非 hybrid 结构 raise 不删库 / `UnexpectedResponse` 冒泡 / EMBEDDING_DIMENSION=768 按设置值创建 / 命令无 `--yes` 零副作用（横幅文案断言）/ 命令带 `--yes` 删一次 + 建一次 / schema 8 字段键集合契约锁。

## Deviations from Plan

None - plan executed exactly as written.

（注：`system/models.py` 存在既有 `ProviderCredential` 段的 ruff format 漂移，与本计划改动无关，按 scope boundary 未处理。）

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `ba9189b5` | feat(12-03): payload schema 定型与 delivery_knowledge ensure 函数 |
| 2 | `2798a1ca` | feat(12-03): rebuild_delivery_knowledge 显式重建命令 |
| 3 | `dcf7a462` | test(12-03): collection 生命周期、维度校验与重建命令全套测试 |

## Known Stubs

- `KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS` 仅为 docstring 契约常量（Phase 13 摄取写入时消费），本阶段无写入路径——计划内有意预留，不阻塞本计划目标。
- rebuild 命令的"从 PG 全量重嵌入"步骤：Phase 13 接入摄取后扩展（docstring TODO 锚点已留），当前 collection 无数据，重建 = 删 + 建。

## Threat Flags

None — 本计划交付面与 PLAN.md `<threat_model>` 一致：T-12-04（mismatch raise 不删库 + structlog error 留痕 + 删除仅经 `--yes` + `assert_not_called()` 固化）、T-12-02（project_id/repository_id 进 payload index 第一天定型 + 回归测试锁键集合）、T-12-06（异常一律重抛 + UnexpectedResponse 冒泡用例）均已落地，无新增安全面。

## Self-Check: PASSED

- 全部 7 个交付文件存在（collection.py / exceptions.py / 命令 + 两个 `__init__.py` / test_collection.py / system/models.py 修改）
- `uv run pytest tests/knowledge/ -x` → 49 passed（9 新增 + 40 既有零回归，perf deselected）
- `uv run python manage.py check` → System check identified no issues (0 silenced)
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected
- grep 验收全过：collection.py 中 `delete_collection`=0、`return False`=0、`QdrantService.get_client`=1、`QdrantClient(`=0、`rebuild_delivery_knowledge --yes`=4；命令文件 `store_true`=1、`ensure_delivery_knowledge_collection`=3、`Phase 13`=1；测试 `assert_not_called`=8
- 3 个任务 commit（ba9189b5 / 2798a1ca / dcf7a462）均在 git log
