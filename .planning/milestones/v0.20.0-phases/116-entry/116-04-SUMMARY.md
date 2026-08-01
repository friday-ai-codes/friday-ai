---
phase: 116-entry
plan: 04
subsystem: knowledge-graph + delivery-artifacts + blueprint-ui
requirements: [VIEW-04]
tags: [knowledge-graph, reverse-lookup, normalizer, edge-materialization, observability, view-04]
requires: ["116-02"]
provides:
  - "GET /api/knowledge/related/<id>/ 的 ?relations=A,B 白名单入参（非法 400，不传时行为逐字不变）"
  - "DeliveryKnowledgeSearchService.get_related(relations=...) 透传形参"
  - "web api/knowledge.ts getRelated 的 relations?: string[] 可选项"
  - "knowledge.sources.blueprint.normalize（蓝图 → tech_plan 实体 + REFERENCES/RELATES_TO 两类边）"
  - "knowledge.sources.blueprint.blueprint_entity_id（蓝图 natural key 的对外派生入口，INV-3 下 delivery 侧唯一合法换算通路）"
  - "_NORMALIZERS['blueprint'] 注册项"
  - "ArtifactService.create / add_version 两处 blueprint/v1 门控投递（add_version 侧判断是否真的翻版本）"
  - "GET .../blueprint/ 响应第 8 键 knowledge_entity_id"
  - "BlueprintAssociationsSection 的「被哪些方案/知识引用」与「关联知识」两块"
affects: [116-05, 116-06]
tech-stack:
  added: []
  patterns:
    [ensure-reference-node, batch-existence-prefilter, edge-metadata-aggregation, additive-query-param, lazy-import-schema-constant, falsifiable-mutation-test]
key-files:
  created:
    - server/knowledge/sources/blueprint.py
    - server/tests/knowledge/test_related_relations_param.py
    - server/tests/knowledge/test_blueprint_normalizer.py
  modified:
    - server/knowledge/api/views.py
    - server/knowledge/retrieval.py
    - server/knowledge/models.py
    - server/knowledge/sources/__init__.py
    - server/delivery/services/artifact_service.py
    - server/delivery/api/blueprint_doc_views.py
    - server/tests/delivery/test_blueprint_log_redaction_guard.py
    - server/tests/delivery/conftest.py
    - web/src/api/knowledge.ts
    - web/src/components/blueprint/BlueprintAssociationsSection.vue
    - web/src/components/blueprint/__tests__/sections.spec.ts
    - web/src/locales/zh-CN.json
    - web/src/types/blueprint.ts
    - web/src/pages/knowledge/blueprints/[id].vue
decisions:
  - "⭐ 蓝图 natural key 的对外派生入口落在 `knowledge/sources/blueprint.blueprint_entity_id` 而不是让 view 直接 import `generate_entity_id` —— `tests/delivery/test_inv6_guard.py::test_inv3_delivery_does_not_write_knowledge_models` 禁止 delivery app 出现 `knowledge.models` 字样（实跑转红后改的），而 natural key 又只能有一份定义"
  - "项目 `RELATES_TO` 边的目标经 `ProjectKnowledgeGraphService().ensure_project_node` 取得且**不进**存在性预过滤；存在性过滤只作用于 citation 派生的目标"
  - "仓库类 citation（repo_file / rag_chunk / repo_charter）的 repo id 先取 `locator.repository_id|repo_id`、再退到 `source_id`（`repo_charter` 的引用条目把 repo id 放在 source_id，见 `blueprint_route.py:791`）；都还原不出即丢弃"
  - "payload ⛔ 不快照 `blueprint_status` —— `test_blueprint_inv6_guard` 把该字段的任何字典键/赋值都判为旁路写（实跑转红后改的），且图谱侧复制一份状态必然过期"
  - "`tests/delivery/conftest.py` 新增 autouse 的 `_no_blueprint_background_ingest`（只拦 `source_kind == \"blueprint\"`）—— 门控上线后 delivery 包的既有用例经 SQLite 撞 `database table is locked`（生产 PostgreSQL 无此形态）"
metrics:
  duration: "~2.5h"
  completed: 2026-08-01
---

# Phase 116 Plan 04: relations 三层打通 + 蓝图入图 + 反查 Summary

**One-liner:** 让「蓝图被谁引用」从**结构上不可能**变成真的能查 —— 先把 `?relations=` 的三层断链接上（不接这条，后面所有边的工作都只能被一个恒空的查询验收），再落一个把四种「静默假通过」形态逐条钉死的 normalizer（目标不存在的边被**计数**而不是被吞、同目标多条 citation 聚合成一条、`RELATES_TO` 恰好 1 条、⛔ 无 `first_seen_version_no`），最后把换算键与前端两块补上；反查的验收是**端到端走真实端点**，项目边的验收用**夹具不预建节点 + 变异实跑**证伪。

## PHASE_BASE

`815257c50a495558940dd3763afd06be07de4d02`

本 plan 内所有冻结面 / 删除行 / 边界核算一律 `git diff 815257c5 -- <file>`（逐 Task 原子提交之后裸 `git diff` 恒空，断言会静默恒真）。

## 提交

| # | commit | 内容 |
|---|--------|------|
| 1 | `dd9bb454` | Task 1：`relations` 三层透传（view + service + 前端）+ 7 条用例（含端到端反查与反向对照） |
| 2 | `dc606e3e` | Task 2：normalizer + `_NORMALIZERS` 注册 + `models.py` natural key 行 + `create`/`add_version` 两处门控 + 脱敏守卫清单 + 23 条用例 |
| 3 | `dd14e876` | Task 3：`knowledge_entity_id` 第 8 键 + 前端两块 + `sections.spec.ts` 拆三条 + i18n |

---

## ⭐ 1. 反查的完整调用链契约

```
GET /api/delivery/artifacts/<artifact_id>/blueprint/
  → 响应第 8 键 knowledge_entity_id            （= generate_entity_id("tech_plan","blueprint",artifact_id)）
GET /api/knowledge/related/<knowledge_entity_id>/?direction=in&relations=REFERENCES&max_hops=1
  → 返回「引用了本蓝图」的实体列表
```

**为什么 `max_hops=1` 必须显式传**：view（`knowledge/api/views.py`）与前端（`api/knowledge.ts`）的默认都是 **2**。「被谁引用」要的是**直接引用者**，不传会把二跳实体也列进来 —— 用户会据一个并不存在的引用关系做决策（T-116-35）。后端 `test_max_hops_one_returns_only_direct_referrer` / `test_max_hops_two_returns_transitive_referrer` 两条并列用例把这个差异钉死。

**为什么 `relations=REFERENCES` 必须显式传**：`_DEFAULT_RELATIONS = [HAS_PLAN, IMPLEMENTED_BY, RELATES_TO]` **不含 `REFERENCES`**，不传等于查一个恒空的集合。

## ⭐ 2. `?relations=` 的契约

| 情形 | 行为 |
|---|---|
| 不传 / 传空串 | `relations=None` ⇒ 下游 `rels = relations or list(_DEFAULT_RELATIONS)` ⇒ **行为逐字不变** |
| 合法子集（如 `REFERENCES` / `REFERENCES,RELATES_TO`） | 只遍历这些关系 |
| 含任一非法值（`BOGUS` / `REFERENCES,BOGUS`） | **400**，`detail = "relations must be a subset of: DUPLICATE_OF, HAS_PLAN, ..."`（与既有 `direction` 校验同形） |

`EdgeRelation` 在 view 内**懒 import**（`_parse_relations_param` 函数体内），为的是让 `knowledge/api/views.py` 的删除行保持 **0**（改既有 import 行会算一次删除）；该文件本就有 `from django.db.models import Q` 的同款函数内 import 先例。

⭐ **`_DEFAULT_RELATIONS` 逐字未动**：`git diff $PHASE_BASE -- server/knowledge/related.py` 为空。护栏是 `test_reverse_lookup_without_relations_is_empty` —— 任何人图省事把 `REFERENCES` 加进默认集，它立刻转红。

## ⭐ 3. normalizer 的产出契约

| 项 | 值 |
|---|---|
| 实体 natural key | `generate_entity_id("tech_plan", "blueprint", str(artifact_id))`（⛔ 零新 `EntityKind`，`source_kind` 区分子类是 Phase 100 惯例） |
| `kind` / `origin` / `source_kind` | `EntityKind.TECH_PLAN` / `EntityOrigin.ARTIFACT` / `"blueprint"` |
| `space_id` 来源链 | `content.meta.project_id`（**Project id**）→ `initiatives.Project.space_id`（**Space id**）→ `IngestionEvent.space_id` |
| `content` | `# {meta.title}` + 按 `iter_blocks` 走查的逐段 block 文本（`## {顶层段名}` 分隔），经 `redact_secrets_in_text` 脱敏，截断 60000 字 |
| `payload` | `{artifact_id, version_no, project_id, status, citation_count, reference_edge_count}` —— 只放标量与计数，⛔ 不塞整份 content |
| `event_time` | 当前版本 `created_at`（`_aware` 补时区） |
| 边 ① | `citations` → `REFERENCES`，`exclusive=False`（append-only：新版本删掉某条引用**不**失效旧边，bi-temporal 下「v2 曾引用过它」仍是事实） |
| 边 ② | `meta.project_id` → 项目图谱节点 `RELATES_TO`，`exclusive=True` |

**块取文本口径同源**：正文提炼直接 import `delivery.services.blueprint_anchor._block_text`（`text` → `code.source` → `rows` 的**字段优先级**，**完全不看 block 的类型字段**）—— ⛔ 不复制一份实现，否则与 114 的锚点坐标系分叉。

**降级（缺料一律 warning + 返回空列表，⛔ 不产半截事件）**：artifact / 当前版本缺失 → `knowledge_normalize_source_missing`；`schema_version != blueprint/v1` → `blueprint_knowledge_normalize_schema_mismatch`；project / `space_id` 反查不到 → `knowledge_normalize_blueprint_space_unresolved`。

⭐ **space 反查不到为什么是「整体不入图」**：`fetch_related_entities` 有**两处** `space_id is None` 短路（`related.py:40-41` 判起点实体、`:79-80` 判每个对端实体）⇒ space 为空的实体既查不出邻居、也不会出现在别人的邻居里，是一个**双向不可见**的孤儿节点。「入了图却永远查不出来」比不入图难排查得多。

## ⭐ 4. 九种 `source_type` → 目标实体换算表

| `source_type` | 目标实体 id | 还原来源 |
|---|---|---|
| `knowledge_entity` | `source_id` 本身 | 需能解析成 UUID，否则丢弃 |
| `work_item` | `generate_entity_id("work_item","feishu_work_item", "{project_key}:{type_key}:{item_id}")` | `source_id` 已是三元组则直取；否则从 `locator.project_key` / `work_item_type_key` / `work_item_id` 拼；**还原不出即丢弃** |
| `feishu_doc` | `generate_entity_id("document","feishu_document", token)` | `source_id`，退到 `locator.token` |
| `blueprint` | `generate_entity_id("tech_plan","blueprint", artifact_id)`（同款 natural key） | `source_id` |
| `artifact_version` | 先查 `ArtifactVersion → artifact_id`，再换算成蓝图实体 id | `source_id`；查不到即丢弃 |
| `repo_file` | `repository_node_id(repo_id)` | `locator.repository_id\|repo_id` → 退到 `source_id`（`repo_file` 的 `source_id` 是文件路径 ⇒ 通常丢弃） |
| `rag_chunk` | 同上 | 同上 |
| `repo_charter` | 同上 | 同上（该来源的 repo id 就在 `source_id`，`blueprint_route.py:791`） |
| `url` | — | ⛔ **不成边**（图里没有对应节点，建边只会撞 FK 被吞成 warning） |

⭐ 仓库类三种统一复用 `initiatives.services.knowledge_graph.repository_node_id`（`:57-58`，就是 `generate_entity_id(EntityKind.REPOSITORY,"repository",…)` 的既有唯一派生入口）—— ⛔ 本模块**零内联副本**，`rg "generate_entity_id(\"repository\"" ` 零命中。

## ⭐ 5. 四条结构约束 → 用例名对照

| 约束 | 机制（为什么不做会静默假通过） | 用例 |
|---|---|---|
| ① 目标不存在的 spec **先过滤**（一次批量 `filter(id__in=…)`）+ 丢弃计数 | `KnowledgeEdge.target_entity` 是真 FK ⇒ `IntegrityError` → 被 `apply_edge_specs:435-443` 吞成 warning，边**静默消失**；且该分支与「撞 `uniq_kedge_active`（并发已建，良性）」共用同一个 except，日志分不出来 | `test_missing_target_drops_edge_and_counts_by_source_type` |
| ② 同目标多条 citation **聚合成一条** `EdgeSpec` | `uniq_kedge_active` 是 `(source, target, relation)` 唯一 ⇒ 朴素写法从第二条起稳定撞约束被吞成 warning | `test_two_citations_same_target_produce_one_edge`（**经完整 `ingest_events`**，断活跃边恰好 1 条且 `citation_ids` 两项） |
| ③ `RELATES_TO` 出边**恰好 1 条** | `exclusive` 的作用域是 `(source, relation)` **不含目标类型** ⇒ 多条会互相 `invalidate_edge`，走的是**正常路径**（不是异常、不是 warning）—— 完全静默 | `test_relates_to_edge_is_exactly_one` |
| ④ ⛔ 无 `first_seen_version_no` | 重摄取时 `update_edge_metadata` **整体覆盖**，normalizer 拿不到既有边 metadata ⇒ 该字段每次被刷成当前版本号，字段名与语义直接对不上 | `test_reference_edge_metadata_has_no_first_seen_version_no` |

四条**逐条写进模块 docstring**（含机制与行号），验收脚本断言 docstring 内含 `uniq_kedge_active` / `IntegrityError` / `exclusive` / `first_seen_version_no` 四个 token。

## ⭐ 6. B2 登记：项目节点走 `ensure`，且**不进**存在性过滤

`project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)`，返回值直接作 `EdgeSpec.target_entity_id` —— 与 `knowledge/sources/project_doc.py:110` / `project_memory.py:90` / `artifact.py:396` **三处同形**。`initiatives/services/knowledge_graph.py:1-7` 的 docstring 明写该 service 是 PROJECT/REPOSITORY/SPACE 参考节点的**唯一写者**，`ensure_project_node:70-86` 是幂等 `get_or_create`。

⛔ **为什么项目边不进存在性预过滤**：`ensure` 已保证节点存在；把它塞进过滤器会在「项目节点尚未被别的路径建过」的**生产场景**里把边静默吃掉（只剩一条 `sampling` 事件），而任何测试夹具都会顺手把节点建出来 ⇒「`RELATES_TO` 恰好 1 条」**永久恒绿**。存在性过滤**只作用于 citation 派生的目标**（那些目标来自别的摄取批次，确实可能不存在）。

**可证伪用例**：`test_project_node_absent_is_created_by_ensure` —— 夹具**不预建**项目节点（先断言 `filter(id=project_node_id(...)).aexists() is False`），跑完整摄取后断言 (a) 节点被建出来、(b) `RELATES_TO` 活跃边恰好 1 条、(c) 该目标不在 `dropped_by_source_type` 里。

⭐ **变异实跑记录**（把项目边改写成「查一下、查不到就丢弃」）：

```
红：tests/knowledge/test_blueprint_normalizer.py:233: in test_project_node_absent_is_created_by_ensure
    E   assert False is True
    （连带 test_relates_to_edge_is_exactly_one 也转红：E assert 0 == 1 / where 0 = len([])）
绿：还原后 23 passed
```

## ⭐ 7. 两处门控与「是否真的翻了版本」

共享私有 helper `delivery/services/artifact_service._amaybe_schedule_blueprint_ingestion(artifact_id, content, *, trigger)`：

- 判别逐字 `isinstance(content, dict) and content.get("schema_version") == BLUEPRINT_SCHEMA_VERSION`，常量**懒 import** 自 schema 模块（MN-10，⛔ 不复制 `"blueprint/v1"` 字面量）；
- ⛔ **不包 try**：`aschedule_ingestion` 内部已吞异常（`ingestion.py:118`），重复兜底会掩盖「normalizer 注册漏行」这类应当响亮的错误。

| 落点 | 判据 | 理由 |
|---|---|---|
| `create` | 判别通过即投递 | **P-10**：intake 建的 v1 骨架走 `create` **不经 `add_version`** ⇒ 只挂 `add_version` 的话「新建蓝图 → 立刻查图谱 → 空」会被当 bug 反复排查。`create` 的调用面只有旧链 merge 与 echo，加判别对它们零影响 |
| `add_version` | 先记 `artifact.current_version_id`，与返回 version 的 `id` **不同**才投递 | `_add_version_sync` 在 `content_hash` 相等时 `return current`（版本没翻），不比对就投递等于每次无变化的重复写入都白跑一次 normalizer + 一次后台任务 |

用例：`test_create_schedules_ingestion_for_blueprint_v1`（v1 骨架经 `create` 也入图）／`test_create_does_not_schedule_for_v0_content`（**反向对照**：v0 content 零调用 —— 证明判据没写反）／`test_add_version_without_content_change_schedules_once`（同一 content 连写两次只投一次）。

## ⭐ 8. 丢弃计数事件的字段清单（运维据它查「哪些引用没成边」）

事件名 `blueprint_knowledge_edges_resolved`，`category="sampling"` / `component="knowledge"`：

| 字段 | 含义 |
|---|---|
| `artifact_id` | 蓝图 artifact id |
| `kept_count` | 最终产出的 `REFERENCES` EdgeSpec 条数（已聚合、已过存在性过滤） |
| `dropped_count` | 被丢弃的 citation 条数合计 |
| `dropped_by_source_type` | `{source_type: 条数}` —— 区分「`url` 本就不成边」「三元组还原不出」「目标实体不在库」 |
| `trigger` | 触发来源 |

另有 `blueprint_knowledge_normalize_started` / `_completed`（后者带 `duration_ms` / `content_length` / `edge_count` / `entity_id`）。日志只记 id 与计数，⛔ 零正文。`knowledge/sources/blueprint.py` 已加入 `tests/delivery/test_blueprint_log_redaction_guard._SCANNED_MODULES`（与模块创建**同一个 commit**，该守卫 `read_text()` 不兜 `FileNotFoundError`）。

## 9. 前端两块

| 项 | 块 A「被哪些方案 / 知识引用」 | 块 B「关联知识」 |
|---|---|---|
| queryKey | `['blueprint','related-in',artifactId,knowledgeEntityId]` | `['blueprint','related-out',artifactId,knowledgeEntityId]` |
| 入参 | `getRelated(knowledgeEntityId, { direction:'in', relations:['REFERENCES'], maxHops:1 })` | 同款，`direction:'out'` |
| `enabled` | `Boolean(knowledgeEntityId)` —— 为空时**两块都不发请求** | 同左 |
| 空态 | 本块内一行灰字（`referencedByEmpty` / `relatedKnowledgeEmpty`），⛔ 不弹 toast、⛔ 不进错误分档 | 同左 |
| 与既有块的关系 | 「本蓝图引用了」是**引用池原样**（含 `url` 这类不成边的条目）；块 B 是**已物化成边**、可点进去继续查的邻居 —— 互补而非重复 | |

⛔ 零轮询字面量（源码守卫 `blueprint-source-guard.spec.ts` 逐字扫描；docstring 里也不能出现该字面量 —— 实跑转红后已改写措辞）。

**`sections.spec.ts` 拆条前后对照**：

| 前 | 后 |
|---|---|
| `9a.` 一条用例同时断言 `getRelated` 与 `getArtifactAssociations` **都为 0** | `9a-1` `getRelated` **被真实调用两次**，`mock.calls` 逐字含 `['entity-1', {direction:'in', relations:['REFERENCES'], maxHops:1}]` 与 `direction:'out'` 那条 |
| | `9a-2` `getArtifactAssociations` **仍 `toHaveBeenCalledTimes(0)`** |
| | `9a-3` `knowledgeEntityId` 为空 ⇒ `getRelated` 零调用（证明 `enabled` 不是摆设） |

⭐ **为什么 `getArtifactAssociations` 仍必须为 0**：它查的是 `generate_entity_id(EntityKind.DOCUMENT, "artifact", …)` 即 `initiatives.Artifact` 的投影（`knowledge/artifact_associations.py:75`），而蓝图活在 `delivery.Artifact` ⇒ 拿蓝图 id 去调**依然必然落空**。116 不是把它修好了，而是**改走另一条链**（`getRelated` + 物化的 REFERENCES 边）。这条防线原样保留。

## ⭐ 10. 额外文件登记（超出 `files_modified` 的 3 个）

| 文件 | 理由 | 删除行 |
|---|---|---|
| `web/src/types/blueprint.ts` | `BlueprintDocumentResponse` 必须有 `knowledge_entity_id: string`，否则页面读该键 `pnpm type-check` 不过。纯追加一个字段 + 注释 | **0** |
| `web/src/pages/knowledge/blueprints/[id].vue` | `knowledgeEntityId` 由页面透传（它已持有 doc 响应）；组件自己拿不到该键。纯追加一行 `:knowledge-entity-id="docQuery.data.value?.knowledge_entity_id ?? null"` | **0** |
| `server/tests/delivery/conftest.py` | 门控上线后 delivery 包的既有用例（经 `ArtifactService` 写蓝图版本）会让后台线程在 **SQLite** 上并发写、撞 `database table is locked`（**7 条既有用例转红**，生产 PostgreSQL 无此形态）。新增 autouse fixture `_no_blueprint_background_ingest`，⭐ **只拦 `source_kind == "blueprint"`**，其它 source_kind 原样放行；门控本身「该投递 / 不该投递」的断言在 `tests/knowledge/test_blueprint_normalizer.py`，不靠该 fixture 承载 | **0** |

## 11. 受限面删除行逐行核算

| 文件 | 计划上界 | 实测 | 说明 |
|---|---|---|---|
| `server/knowledge/api/views.py` | 0 | **0** | ✅ |
| `server/knowledge/retrieval.py` | 1 | **1** | ✅ 单参数行改多行 |
| `server/knowledge/models.py` | 0 | **0** | ✅ 只追加 natural key 表格行 |
| `server/knowledge/sources/__init__.py` | 0 | **0** | ✅ |
| `server/delivery/services/artifact_service.py` | 0 | **0** | ⚠️ 首次实现时误跑 `ruff format` 造成 18 处**既有代码**重排，已 `git checkout $PHASE_BASE --` 还原后重新逐处追加 |
| `server/delivery/api/blueprint_doc_views.py` | 0 | **0** | ✅ 既有 7 键一字未动 |
| `server/tests/delivery/test_blueprint_log_redaction_guard.py` | 0 | **0** | ✅ |
| `web/src/api/knowledge.ts` | 0 | **1** | ⚠️ 见 Deviations D-1 |
| `web/src/components/blueprint/BlueprintAssociationsSection.vue` | 8 | **16** | ⚠️ 见 Deviations D-2 |
| `web/src/components/blueprint/__tests__/sections.spec.ts` | 4 | **6** | ⚠️ 见 Deviations D-3 |
| `web/src/locales/zh-CN.json` | 0 | **1** | ⚠️ 见 Deviations D-4 |

**冻结面核算（全部为空）**：`git diff $PHASE_BASE --stat --` 对 `server/knowledge/related.py`（`_DEFAULT_RELATIONS`）、`server/knowledge/ingestion.py`（`apply_edge_specs`）、`server/codegraph/services/repo_router_v2.py`、`web/src/components/chat/TechPlanCard.vue`、`web/src/components/chat/RoutingDecisionPanel.vue`、`web/src/components/execution/NodeDataTab.vue`、`web/src/components/delivery/ArtifactTimeline.vue`、`web/src/pages/knowledge/entities/` —— **输出全空**。

**环境项核算**：`pnpm build` 重写了 `web/src/components.d.ts`（裁掉 29 条无关条目），已 `git checkout --` 还原；本 plan 未新增组件文件，该文件保持零变更。`web/pnpm-workspace.yaml` 本轮**未发生漂移**（`git status --porcelain` 对两个文件均为空）。

## 12. 门与基线比对

| 门 | 基线 | 本 plan | 结论 |
|---|---|---|---|
| `cd server && uv run pytest tests/ -q` | 8741 passed / 1 failed（`test_skills_snapshot_guard::test_skill_files_discovered`，worktree 环境产物） | **8772 passed / 1 failed**（同一条，且仍是唯一一条） | ✅ 无新增失败。+31 = 新用例 30（7 + 23）+ 脱敏守卫参数化多出的 1 例（`_SCANNED_MODULES` 追加一行） |
| `makemigrations --check --dry-run` | exit 0 | **exit 0**（`No changes detected`） | ✅ 零 migration |
| `cd web && pnpm exec vitest run` | 1674 passed / 1 skipped | **1676 passed / 1 skipped** | ✅ 无新增失败（9a 拆三条 ⇒ +2） |
| `pnpm type-check` | exit 0 | **exit 0** | ✅ |
| `pnpm build` | 通过 | **通过**（`✓ built in 7.44s`） | ✅ |
| `pnpm exec eslint <触及的 6 个前端文件>` | 全仓 111 problems | 触及文件 **零输出** | ✅ 零新增 |
| `ruff check` / `ruff format --check`（新建与触及文件） | — | 通过 | ✅ |

⚠️ `knowledge/api/views.py` 在 **PHASE_BASE 就已经** `ruff format --check` 不通过（已用 `git show $PHASE_BASE:` 取原文复验），属既有状态，本 plan 未扩大也未修复（该文件的 format 不在本 plan 的验收项内，且格式化它会产生大量与本 plan 无关的删除行）。

## ⭐ 13. VIEW-04 转 Complete 的证据清单

| 方向 | 兑现用例 |
|---|---|
| **正向可查**（本蓝图引用了什么） | `test_source_type_*` 九条（四种直连 + 三种落仓库节点 + `url` 不成边 + 还原不出即丢弃）；前端块 B「关联知识」`direction:'out'` |
| **反向「被谁引用」** | ⭐ `test_reverse_lookup_returns_referrer_end_to_end`（造 `blueprint -REFERENCES-> entity` 边，从**被引方**走**真实端点** `?direction=in&relations=REFERENCES&max_hops=1` 查回**引用方**）；`test_reverse_lookup_without_relations_is_empty`（反向对照，同时是 `_DEFAULT_RELATIONS` 的护栏）；前端块 A + `sections.spec.ts` 9a-1 的入参逐字断言 |
| **边真的被物化** | `test_two_citations_same_target_produce_one_edge` / `test_project_node_absent_is_created_by_ensure` 两条**经完整 `ingest_events`** 后查 `KnowledgeEdge` 活跃边 |
| **换算键可用** | `GET .../blueprint/` 第 8 键 + `types/blueprint.ts` 的类型契约 + 页面透传 |

## ⭐ 14. REQUIREMENTS 维护项（本 plan 执行完成后已可翻）

**已执行**（本 plan 三个实现 commit 全部落地并过门之后才翻，C4）：`REQUIREMENTS.md` 的 **VIEW-04** 两处已由 `PARTIAL` 翻成 `Complete` —— 条目行（`:67`，勾选框同时打勾）与覆盖率表行（`:136`）。

**GATE-01 维持 `PARTIAL` 不动**（复核结论）：该条的内容是「全入口统一走蓝图编排 + MCP 异步澄清协议」，与 SC-4 不同源；其 PARTIAL 的两个真实阻塞项是 ① 默认开关顺延同步点 2 后的收尾 plan、② MCP 调用方接线归 116-06 —— 本 plan 都没动。⇒ 按实际交付复核的结论是**不翻**。

## ⭐ 15. STATE 维护项（划掉的三条 SC-4 收窄 todo）

按 STATE 实读原文划掉，原行号与原文如下：

- **L178**（Phase 115-07 重申 · SC-4 范围收窄）：「关联段的「引用了本蓝图 / 关联知识」顺延 Phase 116 的知识图谱物化…反向「被谁引用」需要图谱物化后才有数据源」 ⇒ **116-04 已闭**：REFERENCES 边已物化，两块已补。
- **L190**（Phase 115-02 范围收窄 · P-5）：「⭐ **SC-4 的 `associations` 段本相位只做「本蓝图引用了」+「关联项目」**…116 做图谱物化时一并补这两块呈现」 ⇒ **116-04 已闭**（含「蓝图 citations 未物化成 `KnowledgeEdge`」这层）。
- **L200**（Phase 115-05 范围收窄落地 · 承接 115-02 P-5）：「…两个必然 404 的反查端点**源码零命中**且有 `toHaveBeenCalledTimes(0)` 的用例…届时在该组件里补两块即可（现有两块无需重构）」 ⇒ **116-04 已闭**，且预判被证实：**现有两块确实无需重构**。⭐ 结论要点：**`getArtifactAssociations` 对 `delivery.Artifact` 必然落空这条判断依然成立** —— 本 plan 改走 `getRelated` + REFERENCES 边，**⛔ 不是把它修好了**，那条 `toHaveBeenCalledTimes(0)` 断言原样保留。

## Deviations from Plan

### D-1 [Rule 3] `web/src/api/knowledge.ts` 删除行 1（计划上界 0）

计划 Task 1 ③ 的 action 直接给出了改写后的签名行 `options?: { asOf…, relations?: string[] }` —— 在同一行的行内类型上加字段，**物理上不可能**做到 0 删除行（该行必须被替换）。两条要求在计划内互相矛盾。取「action 的逐字代码 + 语义纯追加」为准：删除行 1 是一次**签名行重排**，无任何既有键/行为被移除，不传 `relations` 时不拼该 query 键。

### D-2 [Rule 3] `BlueprintAssociationsSection.vue` 删除行 16（计划上界 8）

计划要求「docstring 收窄段**改写**」+ 补两块 + 改 `isEmpty`。收窄段本身就有 14 行（含「为什么收窄」的整条证据链与「收窄已完成对账」整段），改写它必然产生 >8 行删除。实际构成：收窄段 14 行 + `isEmpty` 1 行 + props 结束 1 行。**零既有渲染块被删**（原「本蓝图引用了」「关联项目」两块逐字保留，只把注释编号从 ①② 改成 ①④）。

### D-3 [Rule 3] `sections.spec.ts` 删除行 6（计划上界 4）

计划要求「一条用例拆两条」，实际拆成**三条**（计划 action ③ 自己也要求补第三条「`knowledgeEntityId` 为空 ⇒ 零请求」）。删除行构成：原 9a 用例头与两条断言（拆分不可避免）+ `mountWith` 的 `global:` 行（要装 `VueQueryPlugin`，否则 `useQuery` 在测试里拿不到 queryClient）+ `getRelated` mock 行（要 resolve 出数组，否则 TanStack Query 把 `undefined` 当非法返回值）+ i18n 键树的 `associations` 行（补四个新键）。⭐ **`getArtifactAssociations` 的 `toHaveBeenCalledTimes(0)` 断言原样保留**，这是本条的硬要求。

### D-4 [Rule 3] `web/src/locales/zh-CN.json` 删除行 1（计划上界 0）

JSON 语法：在既有子树末尾追加键，必须给原最后一行 `"relatedProject": "关联项目"` 补一个逗号。纯语法性重排，无键被删。

### D-5 [Rule 2] `knowledge_entity_id` 改经 `blueprint_entity_id` 而不是直接 import `generate_entity_id`

计划 Task 3 ① 写的是「懒 import `from knowledge.models import generate_entity_id`」。实跑 `tests/delivery/test_inv6_guard.py::test_inv3_delivery_does_not_write_knowledge_models` **转红**：该守卫扫描 `delivery/**/*.py` 里任何 `knowledge.models` 字样或 `\bKnowledgeEntity\b`（INV-3：delivery 是操作态事实源，不双写、不引 knowledge 模型层）。⇒ 把 natural key 的派生函数在 normalizer 模块公开为 `knowledge.sources.blueprint.blueprint_entity_id`（内部仍走 `generate_entity_id` 唯一入口），view 改 import 它。**natural key 仍只有一份定义**，且与 `initiatives.services.knowledge_graph.project_node_id` 是同款分工。

### D-6 [Rule 2] payload 去掉 `blueprint_status` 键

原实现在 `payload` 里快照了 `blueprint_status`。实跑 `tests/delivery/test_blueprint_inv6_guard.py::test_inv6_no_bypass_blueprint_status_field_write` **转红**：该守卫把任何模块里的 `"blueprint_status":` 字典键都判为旁路写（INV-6 把该字段收在 `BlueprintLifecycleService` 的 CAS update 一处）。⇒ 去掉该键（图谱侧复制一份状态本来也必然过期），保留 `status`。

### D-7 [Rule 3] `first_seen_version_no` 在模块 docstring 里保留 1 处命中

计划两条验收互斥：一条要求模块 docstring 内含 `first_seen_version_no`（四条结构约束的 token 断言），另一条要求全文件 `rg` **零命中**。取「零命中」的**意图**（⛔ 不作为边 metadata 的键）：全文件仅 **1 处**命中，位于模块 docstring 的约束 ④ 标题行，代码与 metadata 里零使用。同理，为满足「`graph_store` / `uuid5` 零命中」，已把 docstring 里两处**说明性提及**改写为「边写入层」「id 派生规则」。

### D-8 [Rule 3] 新增 `tests/delivery/conftest.py` 的 autouse 摄取 seam

见上文「额外文件登记」。触发原因是门控上线后 7 条既有 delivery 用例撞 SQLite `database table is locked`（`test_blueprint_doc_views` 4 条 / `test_blueprint_list_views` 1 条 / `test_blueprint_review_views` 2 条）。

### 无 Rule 4（架构决策）触发，无 checkpoint。

## Known Stubs

无。两块前端均接真实端点，空态是真实的「查到 0 条」而不是占位。

## Self-Check: PASSED

三个新建文件（`knowledge/sources/blueprint.py` / 两个测试文件）与本 SUMMARY 均存在于磁盘；三个 commit（`dd9bb454` / `dc606e3e` / `dd14e876`）均可在 `git log` 中定位。

## Threat Flags

无新增未登记的安全面：本 plan 未新增网络端点（`?relations=` 是既有端点的可选入参，走同一套 `IsAuthenticated` + `space_id` 可见性判定），未改 schema，未新增依赖。
