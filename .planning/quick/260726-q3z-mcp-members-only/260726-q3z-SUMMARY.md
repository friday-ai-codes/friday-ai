---
phase: quick-260726-q3z-mcp-members-only
plan: 01
subsystem: knowledge
tags: [vector-recall, access-scope, ingestion, members-only, mcp]
requires: []
provides:
  - "向量召回 project 闸嵌套 OR 逃生支（可见仓库 ⇒ 可召回）"
  - "resolve_allowed_project_ids 含 initiatives.Project 维度（ProjectMember + superuser 全量）"
  - "mcp_coding_plan/mcp_execution_trace 主/锚事件条件携带 space_id"
  - "learning_case 双 None 单仓回填 repository_id + knowledge_normalize_unanchored warning"
affects: [knowledge]
tech-stack:
  added: []
  patterns:
    - "Qdrant 嵌套 Filter(should=[...]) 作为 must 元素实现闸内 OR 逃生支"
key-files:
  created: []
  modified:
    - server/knowledge/vector_recall.py
    - server/knowledge/access_scope.py
    - server/knowledge/sources/mcp_coding_plan.py
    - server/knowledge/sources/mcp_execution_trace.py
    - server/knowledge/sources/learning_case.py
    - server/tests/knowledge/test_vector_recall.py
    - server/tests/knowledge/test_access_scope.py
    - server/tests/knowledge/test_mcp_artifact_sources.py
    - server/tests/knowledge/test_learning_case_source.py
decisions:
  - "逃生支仅在 allowed_repository_ids 非空时构造；第二支 repository_id MatchAny 绝不含空串（防双空串孤儿点泄漏）"
  - "space_id 形参不进 build_plan_event content/hash——锚同源拼法 byte-equal 守护恒绿"
  - "learning_case 仓库回填仅 space_id is None 时进行（space 已有回填会挡「可见项目不可见仓库」用户）"
  - "存量数据零迁移：MCP 三类产物存量点吃检索逃生口；learning_case 双 None 存量按 D-04 接受现状"
metrics:
  duration: ~19min
  completed: 2026-07-26
status: complete
---

# Quick Task 260726-q3z: MCP 产物与 members_only 检索盲区修复 Summary

**一句话：** 向量召回 project 闸加「可见仓库逃生支」+ 权限集合并入 initiatives.Project 维度 + 摄取面回填 space/repo 锚，修复 MCP 三类产物与 members_only 项目文档「只进不出」的 RAG 盲区。

## 三处修复的最终结构

### 1. 检索面（D-01）——`_build_knowledge_must_filter` project 闸

`allowed_project_ids` 与 `allowed_repository_ids` 均非空时，must 中的 project 闸由平铺 `FieldCondition(project_id MatchAny)` 变为嵌套：

```
models.Filter(should=[
    FieldCondition(project_id ∈ allowed_project_ids),          # 分支 A：原条件
    models.Filter(must=[                                        # 分支 B：逃生支
        FieldCondition(project_id == ""),                       # MatchValue 精确空串
        FieldCondition(repository_id ∈ allowed_repository_ids), # MatchAny 不含空串
    ]),
])
```

语义：「实体锚定在可见仓库上 ⇒ 可召回」。`allowed_repository_ids` 为空时保持平铺条件，与修复前逐字段一致（fail-closed 零回归，守护测试锁定）。demand/code 两分路同享此函数，各有独立断言防未来分叉。

### 2. 权限面（D-02）——`resolve_allowed_project_ids` 集合定义

- 普通用户 = SpaceMembership 空间 ∪ **ProjectMember 项目**（`Project.objects.filter(members__user=user)`）∪ public_org 项目
- superuser = 全量 Space ∪ **全量 initiatives.Project**

非成员（无 SpaceMembership 也无 ProjectMember）对 members_only 项目仍零可见；caller intersect 收窄语义不变。`resolve_allowed_repository_ids` 拿本集合后走 `Space.objects.filter(id__in=...)`，新混入的 Project UUID 匹配不到 Space 行自然被忽略——已在 docstring 注明非 bug。

### 3. 摄取面（D-03/D-04）——事件结构

- `build_plan_event` 新增 keyword-only `space_id: str | None = None`，仅进 `IngestionEvent.space_id`，**content 拼法一个字符未动**（byte-equal 守护测试恒绿）。
- `mcp_coding_plan.normalize` 主事件与 `mcp_execution_trace` 锚事件：work_item 可解析（`_resolve_work_item`）且 `technical_plan.space_id` 非空时携带 `space_id=str(tp.space_id)`；不可解析时保持 None 零回归。`code_change` 主事件与 `mcp_repository_analysis` 不动（有非空 repository_id，吃修复 1 逃生口）。
- `learning_case.normalize`：**仅 `space_id is None`** 且 `repositories` 恰 1 名称、Repository 表恰 1 行时回填 `repository_id=str(repo.id)`（查询取 `[:2]` 判唯一）；否则保持 None 并打 warning。

## 新增 warning 事件

`knowledge_normalize_unanchored`（source_kind / source_id / trigger / repositories_count / component=knowledge / category=sampling）——双 None learning_case 无法唯一解析仓库时不再静默。

## 存量数据结论（防画蛇添足）

- **无需任何 rebuild/迁移**：MCP 三类产物存量向量点带非空 `repository_id`，修复 1 的检索逃生口已让它们可召回。
- 既有实体的 `space_id/repository_id` 不会自动更新（`_persist_sync` 更新分支只动 title/event_time/current_version）——**不改 `_persist_sync`**，通用行为变更超出本次范围。
- learning_case 双 None 存量点（`repository_id` 也是空串）吃不到逃生口，按 D-04 接受现状；只保证增量正确 + warning 可见。
- PG 面（related/timeline/detail）按 entity.space_id 判权口径不变；`_vector_project_id` payload 写入口径不变。

## TDD 纪律核对（D-05）

| Task | 证伪（修前红） | 守护（恒绿） |
|------|----------------|--------------|
| 1 | demand/code 两分路嵌套闸断言（修前 `gate is None` 失败） | 平铺退回（repos=[]）、空串不入 MatchAny、既有 route quota/entity_kinds/fail-closed 全套 |
| 2 | ProjectMember 成员含 Project id、superuser 含 members_only Project id（修前 2 失败） | 非成员零可见 + caller 收窄 []、既有 members_only 零泄漏/search_similar 零命中 |
| 3 | plan 主事件/trace 锚 space_id（修前恒 None）、双 None 单仓回填、4 场景 unanchored warning（修前 4 失败） | 锚 content byte-equal、无闭包 space_id=None、space 已有不回填、幂等重摄/触发投递 |

## 验证结果（如实报告）

- 4 个测试文件全量回归：**62 passed, 0 failed, 0 skipped**（`uv run pytest tests/knowledge/test_vector_recall.py tests/knowledge/test_access_scope.py tests/knowledge/test_mcp_artifact_sources.py tests/knowledge/test_learning_case_source.py`）。
- 触碰的 5 个源文件 + 4 个测试文件：`ruff check` / `ruff format --check` 全部通过。
- 存量 lint 噪音（超范围未动，与本任务无关）：`knowledge/ingestion.py` I001、`knowledge/sources/task_result.py` F841、及 18 个从未 format-clean 的 knowledge/ 其他文件（api/、migrations/、toc_* 等）——`ruff format --check knowledge/`（整包）因这些存量文件不绿，触碰文件自身全绿。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 新测试 helper 缺 qdrant models 导入**
- **Found during:** Task 1（RED 阶段守护测试意外失败）
- **Issue:** 测试 helper 用了未导入的 `models` 名字（NameError 而非预期断言）
- **Fix:** 顶层 `from qdrant_client import models as qmodels` 统一使用
- **Files modified:** server/tests/knowledge/test_vector_recall.py
- **Commit:** f1505eb7（并入 Task 1 提交）

**2. [Rule 3 - Blocking] access_scope 既有文件不 format-clean**
- **Found during:** Task 2 提交前 lint
- **Issue:** `access_scope.py` / `test_access_scope.py` 存在既有 I001 与 format 偏差，本次改动使 `ruff format --check`（constraints 指定命令）不过
- **Fix:** 对两文件整体 `ruff format`（纯机械空白变更，无行为改动）
- **Files modified:** server/knowledge/access_scope.py, server/tests/knowledge/test_access_scope.py
- **Commit:** cdb56b1e（并入 Task 2 提交）

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | f1505eb7 | fix(knowledge): 向量召回 project 闸增加可见仓库逃生口 |
| 2 | cdb56b1e | fix(knowledge): 权限集合并入 initiatives.Project 维度修复 members_only 全黑 |
| 3 | 9b3b59bc | fix(knowledge): MCP 方案事件回填 space,learning_case 单仓案例回填仓库锚 |

## Self-Check: PASSED

- 3 个源码提交存在于 git log（f1505eb7 / cdb56b1e / 9b3b59bc）✓
- 9 个 files_modified 全部实际修改并已提交 ✓
- 工作树干净，无未跟踪文件 ✓
