---
phase: 19-ssot
plan: 01
subsystem: api
tags: [drf, serializer, django-management-command, node-registry, fixture, pytest]

# Dependency graph
requires:
  - phase: 18-engine
    provides: NodePort target_handle 语义（inputs/outputs 端口集为引擎路由权威）
provides:
  - GET /api/node-types/ 暴露 ui_schema 与 default_config 字段
  - BaseNode._get_default_config 从 config_schema.properties.*.default 派生默认值
  - dump_node_fixture 管理命令（NodeRegistry → 离线精简快照）
  - web/.../__fixtures__/node-types.fixture.json 入库（33 节点，含 fetch_space_info，无幽灵节点）
  - 后端 NodeType 字段级 + 幽灵节点缺席断言
affects: [19-02, 19-03, 19-04, 19-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "后端零回归扩字段：get_schema() 增 key + DRF Serializer 增字段（多余 key 不报错）"
    - "离线 fixture 守护：Django 管理命令从 NodeRegistry dump 精简集入库，免起 HTTP"

key-files:
  created:
    - server/workflows/management/commands/dump_node_fixture.py
    - web/src/types/workflow/__fixtures__/node-types.fixture.json
  modified:
    - server/workflows/nodes/base.py
    - server/workflows/api/serializers.py
    - server/tests/workflows/test_api.py
    - web/package.json

key-decisions:
  - "fixture 由 Django 管理命令（非 tsx 脚本）从 NodeRegistry dump——免起在线后端，契合 CI 离线守护（D-05）"
  - "fixture 精简集仅含 node_type/category/inputs[].name/outputs[].name，按 node_type 排序保证 diff 稳定"

patterns-established:
  - "Pattern 1: get_schema() 派生 default_config（零回归扩字段，config_schema 空时返回 {}）"
  - "Pattern 2: NodeTypeSerializer 增 ui_schema(allow_null)/default_config 暴露后端事实源"
  - "Pattern 3: dump_node_fixture 离线快照 + gen:node-fixture 一键再生成（Pitfall 6）"

requirements-completed: [SSOT-01, SSOT-03]

# Metrics
duration: ~10min
completed: 2026-06-13
---

# Phase 19 Plan 01: 节点定义单一事实源 - 后端补字段 + 离线 fixture Summary

**后端 get_schema() 派生 default_config、NodeTypeSerializer 暴露 ui_schema/default_config（纯增量零回归），并新增 dump_node_fixture 管理命令把 33 个真实节点的精简定义快照入库，作为 CI 漂移守护对账基准。**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-13
- **Tasks:** 3
- **Files modified:** 6（2 新建 + 4 修改）

## Accomplishments
- `BaseNode._get_default_config()` 从 `config_schema.properties.*.default` 收集顶层默认值；`get_schema()` 增 `default_config` key（空 schema 安全返回 `{}`）
- `NodeTypeSerializer` 暴露 `ui_schema`（allow_null）与 `default_config`，闭合 D-01 前端运行时所需的两个缺失字段
- `TestNodeTypeAPI` 新增字段级 + 幽灵节点缺席断言：`fetch_space_info` 在、`fetch_project_info` 不在、`default_config` 键 ⊆ `config_schema.properties`
- 新建 `dump_node_fixture` 管理命令 + 入库 `node-types.fixture.json`（33 节点，确定性排序，可重复生成 diff 稳定）

## Task Commits

Each task was committed atomically:

1. **Task 1: 后端派生 default_config + serializer 暴露 ui_schema/default_config** - `7a62ea38d` (feat)
2. **Task 2: 扩展 TestNodeTypeAPI 字段级断言** - `af853c062` (test)
3. **Task 3: dump_node_fixture 管理命令 + 入库离线 fixture** - `538f51ca2` (feat)

## Files Created/Modified
- `server/workflows/nodes/base.py` - 新增 `_get_default_config` classmethod；`get_schema()` 增 `default_config` key
- `server/workflows/api/serializers.py` - `NodeTypeSerializer` 增 `ui_schema`/`default_config` 字段
- `server/tests/workflows/test_api.py` - 新增 `test_node_types_expose_ui_schema_and_default_config`
- `server/workflows/management/commands/dump_node_fixture.py` - 从 `NodeRegistry.get_all_schemas()` dump 精简集到前端 fixture
- `web/src/types/workflow/__fixtures__/node-types.fixture.json` - 33 节点离线快照（node_type/category/inputs[].name/outputs[].name）
- `web/package.json` - 增 `gen:node-fixture` 脚本指向后端命令

## Decisions Made
- **fixture 生成方式选 Django 管理命令而非 tsx 脚本**：fixture 目的是对账后端事实源，CI 不起后端（RESEARCH §5/A3），直接在 Python 侧 `NodeRegistry.get_all_schemas()` dump 免 HTTP 鉴权与网络依赖；`gen:node-fixture` 仅作便捷转发。
- **fixture 路径以 `Path(__file__).parents[4]` 定位仓库根**：命令在 `server/` 下运行也能正确写入 `web/.../__fixtures__/`，并提供 `--output` 可覆盖。
- **精简集 + node_type 排序**：仅留漂移守护必需字段，排序确定性保证 `git diff` 稳定（acceptance 第三条）。

## Deviations from Plan

None - plan executed exactly as written. 三个任务均按契约实现，verify 全通过。

（说明：插件 `security-compliance` 等 Go 规则不适用于本计划的 Python/TS 改动；`.cursor/rules/` 无与本改动冲突的硬约束。）

## Issues Encountered
- `uv run` 每次会重排 `server/uv.lock`（无新依赖）。按执行约定，每次跑后 `git checkout -- server/uv.lock` 还原；最终 `server/uv.lock` 无任何 diff。

## TDD Gate Compliance
Task 1/Task 2 标注 `tdd="true"`，但项目 `config.json` `tdd_mode: false` 且 orchestrator 未传 MVP_MODE/TDD_MODE，故未强制 RED→GREEN 提交序列门禁。实务上 Task 1 实现 + 既有 NodeType 测试零回归（2 passed），Task 2 追加新断言（3 passed），覆盖等价。

## Verification Results
- `cd server && uv run pytest tests/workflows/test_api.py -k NodeType -x -q` → **3 passed**（含新断言）
- `uv run python manage.py dump_node_fixture` → 写入 33 节点；node 校验 `fetch_space_info` 在、`fetch_project_info` 不在 → **ok**
- 再次运行 dump 后 `git diff` 为空 → fixture 生成确定性 → **稳定**
- `ruff check`（base.py / serializers.py / test_api.py / dump_node_fixture.py）→ **All checks passed**
- `server/uv.lock` 无无关 diff → **clean**

## Next Phase Readiness
- 后端 `/api/node-types/` 已下发 `ui_schema`/`default_config`，19-02+ 前端可改 `useNodeTypesStore` 接口与 registry 适配器消费这两个字段（免 `zod.parse({})` 反推）。
- 离线 `node-types.fixture.json` 已入库，19-05 漂移守护（重写 `node-sync.test.ts`）可直接对账。
- 注意（Pitfall 6）：后续若改后端节点定义，须重跑 `uv run python manage.py dump_node_fixture`（或 `pnpm -C web gen:node-fixture`）刷新 fixture。

## Self-Check: PASSED

- 创建文件存在：`dump_node_fixture.py`、`node-types.fixture.json`、`19-01-SUMMARY.md` 均 FOUND
- 任务提交存在：`7a62ea38d`、`af853c062`、`538f51ca2` 均 FOUND

---
*Phase: 19-ssot*
*Completed: 2026-06-13*
