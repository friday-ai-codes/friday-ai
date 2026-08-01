---
phase: 109-spine-convergence
plan: 02
subsystem: database
tags: [django, migration, unique-constraint, drf-serializer, provenance, sqlite, mysql]

# Dependency graph
requires:
  - phase: 109-01
    provides: SPA 四步同一 plan_id 端到端护栏 + MCP 桥接三对象直接断言（本 plan 动 schema 前的零回归基线）
provides:
  - CodingPlanProvenance 枚举（orchestrated / draft）与 CodingPlan.provenance 列（default draft，db_index）
  - CodingPlan.source_artifact_version_id 列（UUID 软引用，null/blank，db_index）—— 编排方案投影的幂等键
  - 无条件唯一约束 uniq_codingplan_source_artifact_version + 读 connection.introspection.get_constraints 的存在性断言（防 AddConstraint 被后端静默跳过）
  - additive 迁移 chat.0033（AddField x2 + AddConstraint x1，无 data migration）
  - MCP 裸 ORM 桥接在新增两列下零回归的直接断言（default draft / 来源列 NULL / 多 NULL 行不撞约束）
  - provenance 等五字段经 CodingPlanSerializer 与 ConversationRuntimeCodingPlanSerializer 双面透出，provenance read-only
affects: [109-03, 109-04, 109-05, SPINE-01, RELY-01]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "唯一约束必须无条件：带 condition= 会在 supports_partial_indexes=False 的后端（MySQL/MariaDB）被 _unique_supported() 静默跳过"
    - "约束存在性断言：用 connection.introspection.get_constraints 按列集合（而非按名字）断言，把「约束被静默跳过」变成可检出缺陷"
    - "新增列必须带 default / null=True，否则打断 mcp_tools 的裸 ORM 桥接"

key-files:
  created:
    - server/chat/migrations/0033_codingplan_provenance_and_source.py
  modified:
    - server/chat/models.py
    - server/chat/serializers.py
    - server/chat/conversation_service.py
    - server/tests/test_coding_plan_model.py
    - server/tests/mcp_tools/test_bridge_session.py
    - server/tests/test_coding_plan_api.py

key-decisions:
  - "唯一约束采用无条件形态（不带 condition=Q(isnull=False)）：三后端唯一索引都视 NULL 互不相等，草稿行天然共存；带 condition 反而会在 MySQL 上被静默跳过"
  - "provenance 的 default 取 draft 而非 orchestrated：存量 coding_plans 行全是徒手产物，标 orchestrated 等于把历史数据谎报为可信；因此不写任何 data migration"
  - "约束存在性按列集合断言、约束名断言降级为条件分支（后端可能改写名字），避免测试对后端命名细节过拟合"
  - "runtime 序列化器的新字段沿用同文件既有 feishu_doc_* 的 required=False + default 写法而非 read_only=True：该序列化器只做出参组装，且 DRF 不允许同一字段既 read_only 又带 default"
  - "Spoofing 断言落两条：CodingPlanSerializer 字段 read_only is True（直接口径）+ 带 provenance 的 PATCH 打详情端点后 DB 值仍为 draft（端到端口径）"

patterns-established:
  - "约束纪律三件套：无条件唯一约束 + 约束名与 service 层幂等分支字面一致 + get_constraints 存在性断言"
  - "对照断言成对出现：一条证明约束在挡真值（重复非空 → IntegrityError），一条证明约束不挡 NULL（多草稿行共存）"

requirements-completed: [SPINE-01, SPINE-02, RELY-01]

coverage:
  - id: D1
    description: "CodingPlanProvenance 枚举 + provenance / source_artifact_version_id 两列落地，default draft，additive 迁移 0033 无 data migration"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_plan_model.py#test_source_artifact_version_constraint_allows_nulls_but_blocks_duplicates"
        status: pass
      - kind: automated_ui
        ref: "cd server && uv run python manage.py makemigrations --check --dry-run (exit 0, No changes detected)"
        status: pass
    human_judgment: false
  - id: D2
    description: "无条件唯一约束 uniq_codingplan_source_artifact_version 在当前 DB 后端确实存在（防 AddConstraint 静默跳过），且挡真值重复不挡 NULL"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_plan_model.py#test_source_artifact_version_unique_constraint_exists_on_backend"
        status: pass
      - kind: unit
        ref: "server/tests/test_coding_plan_model.py#test_source_artifact_version_constraint_allows_nulls_but_blocks_duplicates"
        status: pass
    human_judgment: false
  - id: D3
    description: "MCP 裸 ORM 桥接在新增两列后零回归：provenance 走 DB default draft、source_artifact_version_id 为 NULL、连续两次桥接不撞唯一约束"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/mcp_tools/test_bridge_session.py#test_create_bridge_session_defaults_new_provenance_columns"
        status: pass
      - kind: unit
        ref: "server/tests/mcp_tools/test_bridge_session.py#test_create_bridge_session_twice_not_blocked_by_unique_constraint"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/mcp_tools/ (全绿)"
        status: pass
    human_judgment: false
  - id: D4
    description: "五个新字段经 CodingPlanSerializer 与 ConversationRuntimeCodingPlanSerializer 双面透出，runtime payload 同步补键"
    requirement: "RELY-01"
    verification:
      - kind: integration
        ref: "server/tests/test_coding_plan_api.py#TestCodingPlanDetailAPI::test_detail_exposes_provenance_and_source_columns"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/test_conversation_runtime.py (18 passed，runtime 契约零回归)"
        status: pass
    human_judgment: false
  - id: D5
    description: "provenance 客户端不可伪造为 orchestrated（T-109-02-01 Spoofing 缓解）"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_plan_api.py#TestCodingPlanProvenanceNotClientWritable::test_provenance_is_read_only_on_both_serializers"
        status: pass
      - kind: integration
        ref: "server/tests/test_coding_plan_api.py#TestCodingPlanProvenanceNotClientWritable::test_write_request_cannot_flip_provenance"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 02: CodingPlan 来源标志 + 投影幂等约束 Summary

**chat `CodingPlan` 获得 `provenance`（默认 draft）与 `source_artifact_version_id` 两列、一条无条件唯一约束（含 `get_constraints` 存在性断言）与 additive 迁移 `0033`，五个新字段经 runtime + plan 两个序列化面 read-only 透出**

## Performance

- **Duration:** ~18 min
- **Tasks:** 3
- **Files created:** 1
- **Files modified:** 6

## Accomplishments

- 落下 RELY-01 的数据层唯一载体：`CodingPlanProvenance`（`orchestrated` / `draft`）+ `CodingPlan.provenance`，`default=DRAFT`。界面与飞书导出都只读 `CodingPlan`，所以这一列就是「未经代码调研」告示的共同瓶颈点，无需在两条链上各标一次。
- 落下 SPINE-01 的并发安全幂等键：`source_artifact_version_id` + **无条件**唯一约束 `uniq_codingplan_source_artifact_version`。这是本 plan 最关键的一条纪律 —— 若照初稿加 `condition=Q(isnull=False)`，`_unique_supported()` 会在 `supports_partial_indexes = False` 的 MySQL/MariaDB 上让 `AddConstraint` 被**静默跳过**，109-03 的 `except IntegrityError` 分支永不触发。
- 把「约束被静默跳过」变成可检出缺陷：新增一条读 `connection.introspection.get_constraints` 的用例，按**列集合**断言表上存在 `unique=True` 且 `columns == ["source_artifact_version_id"]` 的项。没有它，「约束存在」与「约束不存在」的测试表现完全一致（多 NULL 共存在无约束时同样通过，幂等用例是顺序调用）。
- 迁移保持纯 additive：`AddField` x2 + `AddConstraint` x1，零 `RunPython`。`default="draft"` 恰好正确描述存量行，不需要（也明确禁止）把存量刷成 `orchestrated` 的 data migration。
- MCP 零回归有直接锁：`_create_bridge_session` 的裸 `objects.create()` 未传新字段，两条新断言钉住「走 DB default draft」与「来源列 NULL」，另一条用例连续桥接两次证明无条件约束不误伤多 NULL 行。
- 前端契约双面补齐：`CodingPlanSerializer` 与 `ConversationRuntimeCodingPlanSerializer` 各增字段，`coding_plan_payload` 同步补五个键 —— 前端可直接从 runtime 拿到 `provenance` 与方案正文渲染告示，无需二次拉详情端点。

## Task Commits

1. **Task 1: CodingPlan 来源标志 + 投影来源列 + 无条件唯一约束（additive 迁移）** — `4041264a` (feat)
2. **Task 2: MCP 桥接零回归 —— 裸 ORM 建对象在新列下仍成功** — `20668d1f` (test)
3. **Task 3: 新字段经 runtime 与 plan 两个序列化面透出** — `e49440e0` (feat)

## Files Created/Modified

- `server/chat/migrations/0033_codingplan_provenance_and_source.py` — additive 迁移（`AddField` x2 + `AddConstraint` x1，依赖 `0032`）
- `server/chat/models.py` — `CodingPlanProvenance` 枚举、两列、`CodingPlan.Meta.constraints`（该 Meta 此前 0 个约束）+ 无条件形态的理由注释
- `server/chat/serializers.py` — `CodingPlanSerializer` +3 字段（全 `read_only=True`）、`ConversationRuntimeCodingPlanSerializer` +5 字段
- `server/chat/conversation_service.py` — `coding_plan_payload` 补 `provenance` / `tech_plan` / `affected_files` / `recommended_repository_ids` / `source_artifact_version_id`
- `server/tests/test_coding_plan_model.py` — 约束存在性断言 + 「多 NULL 共存 / 真值重复抛 `IntegrityError`」对照断言（+2 用例）
- `server/tests/mcp_tools/test_bridge_session.py` — 新列默认值断言 + 连续两次桥接断言（+2 用例）
- `server/tests/test_coding_plan_api.py` — 详情端点新字段透出 + read-only / 写请求防伪造断言（+3 用例）

## Decisions Made

- **约束采用无条件形态**：`server/chat/models.py` 的既有先例 `unique_active_plan_repo` 带 `condition=Q(status__in=...)`，但那条约束在 MySQL 上同样是静默失效的既有技术债 —— 只照抄它的**纪律**（约束名与 service 层幂等分支字面一致 + `IntegrityError` 降级），不照抄 `condition` 用法。约束不纳入 `conversation`：同一 `ArtifactVersion` 在两个 conversation 各投一份正是要防的重复。
- **`source_artifact_version_id` 的 `help_text` 显式区分 `canonical_plan_id`**：那一列在迁移 `0022` 加、`0031` 删（Chassis v2 解耦 chat↔delivery）。新列只记投影来源留痕、不构成双向耦合，注释在位以免未来审计把它当成重复的历史包袱再删一次。
- **约束名断言降级为条件分支**：部分后端会改写约束/索引名，主断言按列集合；若后端保留原名则一并断言该条目形状。避免测试对后端命名细节过拟合。
- **runtime 序列化器新字段用 `required=False` + `default` 而非 `read_only=True`**：沿用同一序列化器内既有 `feishu_doc_token` / `feishu_doc_url` 的写法（该序列化器只做 runtime 出参组装，无写路径），且 DRF 不允许同一字段既 `read_only` 又带 `default`。read-only 语义写在类 docstring 里。
- **Spoofing 断言落两条口径**：`CodingPlanSerializer().fields["provenance"].read_only is True`（直接口径，plan 指定）+ 带 `provenance: orchestrated` 的 PATCH 打详情端点后 DB 值仍为 `draft`（端到端口径，证明该端点确无写入口）。

## Deviations from Plan

None — plan 执行与原文一致。三个 task 均一次通过，无需 debug 循环，无 Rule 1–4 触发。

（一处**非偏离**的写法说明已记入 Decisions：runtime 序列化器新字段的 kwargs 按 plan 原文给定的 `required=False` + `default` 落地，而非 `read_only=True` —— plan 正文同时写了「全部 read-only 语义」与具体 kwargs，两者在 DRF 中不能字面兼容，按 plan 给定的 kwargs 落地并把 read-only 语义写进 docstring。）

## Issues Encountered

- `uv run ruff format --check` 在 `chat/models.py` 与 `tests/test_coding_plan_model.py` 上报 would-reformat。核对 `git show HEAD:` 基线后确认这是**改动前既有**的格式漂移（本仓 CI 只跑 `ruff check`，未强制 `ruff format`），因此不做全文件重排；只把本 plan 新增代码块调整到 `ruff format` 稳定形态（`ruff format --diff` 对新增行零输出）。
- 测试日志里的 `background_task_failed` / qdrant `SocketBlockedError` 是既有噪声：`aget_or_create_for_conversation` 会调度知识库摄取，而 `--disable-socket` 下摄取触网被挡。属背景任务 best-effort 失败，不影响用例结果（9/9 绿）。

## Verification Results

| 命令 | 结果 |
|---|---|
| `uv run python manage.py makemigrations --check --dry-run` | exit 0（No changes detected，无模型漂移） |
| `uv run pytest tests/test_coding_plan_model.py -q` | 9 passed |
| `uv run pytest tests/mcp_tools/test_bridge_session.py tests/mcp_tools/test_execution_tools.py -x -q` | 6 passed |
| `uv run pytest tests/test_coding_plan_api.py tests/test_conversation_facade.py -x -q` | 22 passed |
| `uv run pytest tests/test_conversation_runtime.py -q` | 18 passed（runtime 契约零回归） |
| `uv run pytest tests/test_coding_plan_model.py tests/test_coding_plan_api.py tests/mcp_tools/ tests/test_spa_coding_chain_e2e.py -q` | **235 passed**（含 wave 1 护栏零回归） |
| `uv run pytest tests/test_coding_plans_sessions_api.py tests/test_coding_plan_export_api.py tests/test_coding_plan_exporter.py tests/test_conversations.py tests/test_conversation_facade.py -q` | 60 passed（序列化器消费方零回归） |
| `uv run ruff check`（6 个改动文件） | All checks passed |
| `rg -n 'condition=' server/chat/models.py` | 仅命中 `CodingSession` 的既有约束（:577）与新增的纪律注释（:313）；新约束无 `condition=` |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-02-01（Spoofing） | `CodingPlanSerializer` 的 `provenance` / `source_artifact_version_id` 声明 `read_only=True`；runtime 序列化器无写路径。两条断言：字段 `read_only is True` + PATCH 后 DB 值仍 `draft` |
| T-109-02-02（Repudiation） | `default=CodingPlanProvenance.DRAFT`，迁移零 `RunPython` —— 存量徒手产物不被谎报为 `orchestrated` |
| T-109-02-03（DoS，MCP 桥接崩链） | 新列带 `default` / `null=True`；`test_create_bridge_session_defaults_new_provenance_columns` 直调 `_create_bridge_session` 断言不抛且字段形状正确 |
| T-109-02-04（Tampering，约束静默失效） | 约束**无** `condition=`；`test_source_artifact_version_unique_constraint_exists_on_backend` 读 `get_constraints` 断言约束在当前后端确实存在；对照用例证明它挡真值重复而不挡 NULL |
| T-109-02-SC（供应链） | 零新增依赖，未执行任何包管理器安装命令 |

## Observability

本 plan 只加数据层字段与出参字段，未新增 API 入口 / LLM 调用 / 召回 / 队列任务 / webhook，无新增埋点义务。`coding_plan_payload` 组装处的既有 `runtime.coding_plan_attached`（`category: sampling`）debug 事件未改动；`CodingPlan` 模型层既有 `coding_plan_get_or_created` / `coding_plan_updated` 事件未改动。新增两列不含凭证或敏感信息（`provenance` 是闭集枚举，`source_artifact_version_id` 是内部 UUID），无脱敏义务。写 `orchestrated` 的投影 service 及其埋点属 109-03 交付物。

## Known Stubs

无占位实现。以下是**按 plan 设计**分派到后续 plan 的下游接线，不是本 plan 的 stub：

- 唯一约束目前只被测试触发 —— 真正写 `orchestrated` + `source_artifact_version_id` 的投影 service 与 `get_or_create` / `except IntegrityError` 幂等分支属 **109-03**。
- 前端 `web/src/types/chat.ts` 的对应扩字段与 `TechPlanCard` 告示条属 **109-04**（plan 正文明令本 task 不提前改前端）。
- `CodingExecutionSpec` 携带「未经调研」标志、送编码 fail-closed 防护属后续 plan。

## User Setup Required

None —— 无外部服务配置需求。迁移 `0033` 为 additive，部署时随 `migrate` 自动生效（`AddConstraint` 无条件形态，三后端一致落地）。

## Next Phase Readiness

- 109-03 可直接用 `get_or_create(source_artifact_version_id=...)` + `except IntegrityError` 实现投影幂等：DB 约束已在位且其存在性有断言保护，不必再做应用层查重。
- 109-04 的前端扩字段可直接消费 runtime 的 `coding_plan.provenance` / `tech_plan`，后端两侧已透出；TS 类型漏一侧不报错，仍需手工对齐（plan 已识别）。
- ⚠️ 提醒后续 plan：给 `CodingPlan` 加列必须带 `default` 或 `null=True`，否则 `tests/mcp_tools/test_bridge_session.py` 会立刻变红（这是设计意图）。
- ⚠️ 遗留技术债（超出本 plan scope，未修）：`CodingSession` 的 `unique_active_plan_repo` 带 `condition=`，在 MySQL/MariaDB 上同样被静默跳过。本 plan 只在注释中标注该事实，未改动该约束。

## Self-Check: PASSED

迁移文件 `server/chat/migrations/0033_codingplan_provenance_and_source.py` 存在于磁盘；3 个 task commit（`4041264a` / `20668d1f` / `e49440e0`）均可在 git 历史中检得；`git diff --diff-filter=D` 三次提交均无文件删除。

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
