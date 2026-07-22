---
phase: 100-learning-case-mcp
reviewed: 2026-07-22T04:25:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - server/knowledge/migrations/0008_extend_entity_kind_learning_case.py
  - server/knowledge/models.py
  - server/knowledge/sources/__init__.py
  - server/knowledge/vector_recall.py
  - server/knowledge/sources/learning_case.py
  - server/knowledge/sources/mcp_coding_plan.py
  - server/knowledge/sources/mcp_repository_analysis.py
  - server/knowledge/sources/mcp_execution_trace.py
  - server/knowledge/management/commands/backfill_learning_cases.py
  - server/mcp_tools/learning_case_service.py
  - server/mcp_tools/serializers.py
  - server/mcp_tools/views.py
  - server/mcp_tools/work_item_execution_service.py
  - server/mcp_tools/technical_plan_service.py
  - server/tests/knowledge/test_models.py
  - server/tests/knowledge/test_vector_recall.py
  - server/tests/knowledge/test_learning_case_source.py
  - server/tests/knowledge/test_mcp_artifact_sources.py
  - server/tests/knowledge/test_backfill_learning_cases.py
  - server/tests/mcp_tools/test_learning_cases.py
findings:
  blocker: 0
  high: 2
  medium: 1
  low: 2
  total: 5
status: findings
---

# Phase 100: Code Review Report

**Reviewed:** 2026-07-22T04:25:00Z
**Depth:** standard
**Files Reviewed:** 20（12 个 Phase 100 提交的并集，`work_item_execution_service.py` 仅审 d56cc9dc 提交 diff——该文件正被 Phase 101 并发修改，工作区现状不在本次范围内）
**Status:** findings

## Summary

审查范围为 Phase 100 十二个提交（59c8d5e5…a383d198）触及的全部源文件。整体质量较高：`vector_recall.py` 吞参修复正确（显式 `entity_kinds` 严格交集过滤、双分路皆空在 embedding 之前短路、`entity_kinds=None` 零回归）；`TOOL_SCHEMA_SNAPSHOT` 键集无回归（serializer 仅增 `help_text`，快照测试只断言键集）；work_item 锚 content 拼法与 `mcp_plan.py` 逐字节一致（不翻版 ping-pong）；`HAS_PLAN` exclusive 陷阱有明确决策存档并有回归测试（T-100-07）；`search_learning_cases` fail-soft、hint 增强/提权、RetrievalTrace 均按 CONTEXT 定案落地；migration 照抄 0007 先例无误。

两个 HIGH 问题都属于「幂等/时序边角被吞异常掩盖」类：一是 `build_plan_event` 用 `plan.created_at` 做 `event_time`，令 improve 后的重摄翻版必撞 `kversion_valid_range` CHECK 并被吞成 `knowledge_ingest_concurrent_conflict`，改进后的方案内容永远进不了知识库；二是 `backfill_learning_cases` 作为一次性 CLI 把摄取投递到 daemon 线程后立即退出进程，绝大部分摄取根本不会执行，P1「切换当天检索全空」防线名存实亡。两者现有测试均未覆盖（幂等测试只测同内容重摄；backfill 测试全程 mock `aschedule_ingestion`）。

## High

### HI-01: `build_plan_event` 用 `plan.created_at` 做 `event_time`，improve 翻版必撞 CHECK 约束且被静默吞掉

**File:** `server/knowledge/sources/mcp_coding_plan.py:94`
**Issue:** `KnowledgeEntityVersion` 有 `kversion_valid_range` CHECK（`models.py:275-278`：`invalid_at` 必须严格大于 `valid_at`）。版本翻转时（`ingestion.py:567-568/598`）旧版 `invalid_at` 与新版 `valid_at` 都取 `event.event_time`。`build_plan_event` 固定 `event_time=plan.created_at`（`auto_now_add`，永不推进），因此：

1. 首摄 v1：`valid_at = plan.created_at`；
2. `ImproveCodingPlanView` 建新 `McpCodingPlanVersion` 后重摄（`views.py:2027-2033`，注释声称「content 变更走版本翻转……天然幂等」）：content 变更 → 走翻版路径 → `latest.invalid_at = plan.created_at == latest.valid_at` → 违反 `invalid_at > valid_at` → `IntegrityError` → 被 `_persist_sync` 外层 except 捕获记为 `knowledge_ingest_concurrent_conflict`（warning）并返回 skipped。

结果：**improve 后的方案内容永远无法进入知识库**（实体停留在 v1 内容），且日志伪装成并发冲突，排障方向完全错误。同一缺陷也波及 `mcp_execution_trace.py:142` 的 plan 锚事件（plan 在 improve 后由 trace 摄取带入新 content，同样翻版失败）。`learning_case.py:111-113` 的注释恰好记载了这个坑（「created_at 不随内容变更推进会使重摄翻版被拒」），learning_case 自己用了 `updated_at`，mcp_coding_plan 却没有。100-03 的幂等测试（`test_mcp_artifact_sources.py::TestIdempotentReingest`）只测同内容重摄（hash 短路），未覆盖内容变更翻版，故未暴露。
**Fix:**

```python
# server/knowledge/sources/mcp_coding_plan.py build_plan_event
        event_time=plan.updated_at,  # McpCodingPlan 有 auto_now updated_at；
        # improve 路径 plan.asave(update_fields=[..., "updated_at"]) 会推进它，
        # 翻版时 invalid_at > 旧 valid_at 成立（learning_case.py 同款纪律）
```

同文件 L220 的 work_item 锚事件 `event_time=plan.created_at` 建议一并改为 `plan.updated_at`（锚 content 随 context.name/description 变更时同理）。补一个「improve 后重摄版本 1→2 翻转」的回归测试（`test_learning_case_source.py::test_reingest_idempotent_then_version_flip` 同款）。另注意 `mcp_execution_trace.py:104` 的 code_change 事件用 `completed_at or created_at`——若同一 trace 在 `completed_at` 不变的前提下内容再变（如 error 补写后经 backfill 重摄）会撞同一约束，属低概率边角，可在修复时顺带确认。

### HI-02: `backfill_learning_cases` 投递到 daemon 线程后进程立即退出，摄取大概率不执行

**File:** `server/knowledge/management/commands/backfill_learning_cases.py:118-123`
**Issue:** `aschedule_ingestion` 的执行路径是 `transaction.on_commit`（autocommit 下立即触发）→ `run_in_background` → **daemon 线程**上的常驻 event loop（`services/background_runner.py:94-98`，`daemon=True`）。该模式在常驻服务进程里成立，但 `backfill_learning_cases` 是一次性 CLI 命令：`handle()` 调度完 N 条后立刻返回、进程退出，daemon 线程被直接杀死，**排队与执行中的摄取任务全部丢失**（调度循环本身很快，几乎没有任务来得及完成 embed→持久化→upsert 全链）。命令输出「已调度 N 条」并打 `backfill_learning_cases_completed` 事件，给出「回填已完成」的错误信号；而本命令恰是「检索切换三件套」的 P1 防线（避免切换当天检索全空），实际防线为空。范本 `rebuild_project_context` 有同样结构，但它主要由服务进程内定时任务驱动，进程常驻掩盖了问题；照抄到手动 CLI 场景后执行前提不再成立。测试（`test_backfill_learning_cases.py`）全程 mock `aschedule_ingestion`，只断言投递集合，无法暴露。
**Fix:** 命令内绕过后台投递、同步逐条执行摄取并统计失败数：

```python
from knowledge.ingestion import IngestionRequest, ingest

async def _backfill(only=None, *, on_progress=None) -> dict[str, int]:
    ...
    async for row in querysets[source_kind].aiterator():
        try:
            await ingest(
                IngestionRequest(source_kind=source_kind, source_id=str(row.id), trigger=_TRIGGER)
            )
        except Exception:
            logger.exception("backfill_ingest_failed", source_kind=source_kind, source_id=str(row.id))
            failed[source_kind] += 1
        ...
```

（备选：保留 `aschedule_ingestion` 但在 `handle()` 末尾调 `background_runner.wait_for_pending(timeout=...)`——其 docstring 允许 shutdown 场景；不过同步 `ingest` 更可控且能如实上报失败条数。）修复后把「已调度」措辞改为「已摄取 / 失败」。

## Medium

### ME-01: `trace.error` 原文未脱敏写入知识库 content（可检索留痕的凭证泄漏面）

**File:** `server/knowledge/sources/mcp_execution_trace.py:75-76`
**Issue:** `_build_content` 把 `trace.error[:500]` 原文拼进 `code_change` 实体 content，随后进入 PG `KnowledgeEntityVersion.content` 与 Qdrant 向量点，可被 `search_delivery_knowledge` / 编排召回长期检索到。执行 trace 的 error 来自 runner/git 执行失败文本，git 报错常包含带凭证的 remote URL（如 `https://oauth2:<token>@gitlab.../repo.git`）或上游响应片段。工作区强制规范要求「凭证/上游响应/异常文本已脱敏」且「入库留痕」不可绕过；本模块对 `last_diff`/`runner_logs` 做了零接触纪律（T-100-06），但对 error 文本漏了脱敏。`learning_case_service.py:333` 在日志侧用了 `redact_secrets_in_text`，先例现成。
**Fix:**

```python
from common.logging import redact_secrets_in_text

    if trace.error:
        lines += ["## 错误", "", redact_secrets_in_text(trace.error)[:500], ""]
```

注意：脱敏会改变 content 字节，已入图的存量实体会在下次重摄时翻一次版本（预期行为，一次性）。

## Low

### LO-01: MCP 三个 normalizer 的 warning 事件缺 `component`/`category` 字段

**File:** `server/knowledge/sources/mcp_coding_plan.py:167-182`、`server/knowledge/sources/mcp_repository_analysis.py:66-71`、`server/knowledge/sources/mcp_execution_trace.py:91-96, 135-140`
**Issue:** 同 phase 的 `learning_case.py:60-67` 按可观测性规范给 `knowledge_normalize_source_missing` 等事件带了 `component="knowledge", category="sampling"`，但 100-03 的三个 normalizer 的同名/同类 warning 均未带，同一事件在不同 source 下归类口径不一致，影响按 component/category 聚合排障。
**Fix:** 为上述 4 处 warning 补 `component="knowledge", category="sampling"` 两个 kv（与 `learning_case.py` 对齐）。

### LO-02: MCP 写入点投递摄取未携带 `initiated_by_user_id`，后台摄取日志归因降级为 system

**File:** `server/mcp_tools/views.py:1786-1791, 1924-1929, 2027-2033, 2139-2147`；`server/mcp_tools/work_item_execution_service.py:274-279, 335-342`（d56cc9dc diff）
**Issue:** 可观测性规范要求后台任务显式携带 `initiated_by_user_id` 并在 worker 入口重新 bind；`aschedule_ingestion` 已支持该参数（`ingestion.py:118-119`）。这 6 处 MCP 写入点均有已认证的触发用户（`request.user` / run 归属），却全部不传，后台摄取日志只能记 system。`learning_case_service.py:202-203` 对该取舍有文档化说明（MCP 链归因经 InteractionRun/ToolCallRecord 留痕），views.py 各写入点沿用同一模式但无注释；属于有既有归因兜底的文档化偏离，故降为 LOW。
**Fix:** 传 `initiated_by_user_id=str(request.user.id)`（views 层）/ 透传编排发起者（service 层）；或至少在各写入点补一行与 `learning_case_service.py` 同款的取舍注释，避免后续新增写入点误以为可无条件省略。

## 已核对无问题项（择要）

- **vector_recall 吞参修复**：显式 `entity_kinds` 严格交集过滤、交集为空的分路不发 Qdrant 查询、双空在 embedding 前短路返回 `[]`、`entity_kinds=None` 保持既有口径；4 个证伪型回归测试覆盖。
- **契约**：`TOOL_SCHEMA_SNAPSHOT` 的 `search_learning_cases` request/response 键集不变（serializer 仅增 `help_text`，快照测试按键集断言）；`learning_case_payload` 外形不变，`score` 为 0-1 向量融合分且有契约测试守门。
- **锚同源拼法**：`learning_case.py` / `mcp_coding_plan.py` 的 work_item 锚 content 与 `mcp_plan.py` 逐字节一致（`f"{name}\n\n{description or ''}"`），不产生锚翻版 ping-pong；`mcp_execution_trace` plan 锚复用 `build_plan_event` 满足同源纪律。
- **HAS_PLAN exclusive 陷阱**：锚出边强制 `RELATES_TO`，决策存档于模块 docstring，且有 T-100-07 回归断言既有 HAS_PLAN 边不被打失效。
- **fail-soft**：`search_learning_cases` 捕获检索/回捞异常返回空 results（异常文本经 `redact_secrets_in_text` 脱敏后入日志），`CancelledError` 不受 `except Exception` 影响。
- **空引用防线**：`trace.commit_sha` 为 `CharField(default="")` 非空，`[:8]` 切片安全；`McpWorkItemRepoTask.technical_plan` 非空 FK，`_resolve_work_item` 无 None 解引用；`McpLearningCase.context/technical_plan` 可空路径均有 `is not None` 判定。
- **migration 0008**：照抄 0007 先例（RemoveConstraint → AlterField → AddConstraint），choices 全集正确。
- **T-100-06 纪律**：`last_diff` / `runner_logs` 未进 content/payload（除 ME-01 的 error 文本外）。

---

## Fix Resolution（2026-07-22）

全部 5 项 findings 已处置（4 项完全修复 + 1 项因并发约束部分修复）。测试：`tests/knowledge/ tests/mcp_tools/` 全量 570 passed / 3 failed（失败均为 `test_triggers.py::TestWorkflowTriggers` 存量 rotten failures，与本次修复无关）。

### HI-01 — FIXED（commit `300e5a17`）

- `build_plan_event`（共享构造级别）与同文件 work_item 锚事件 `event_time` 由 `plan.created_at` 改为 `plan.updated_at`（auto_now，improve 路径 `asave(update_fields=[..., "updated_at"])` 推进）；锚 content 拼法未动，`mcp_execution_trace` 锚复用同一构造，字节一致性回归测试（`test_execution_trace_dual_events_anchor_content_byte_equal`）保持通过。
- 顺带修复 review 点名的同类边角：`mcp_execution_trace.py` code_change 事件 `event_time` 由 `completed_at or created_at` 改为 `trace.updated_at`（error 补写后 backfill 重摄同样需要 event_time 推进）；`make_aware` 兜底随之移除（auto_now 恒为 aware）。
- 新增回归测试 `TestIdempotentReingest::test_plan_reingest_after_improve_flips_version`：improve 后重摄版本 1→2 翻转、v2 supersedes v1、无 `knowledge_ingest_concurrent_conflict` 伪装。

### HI-02 — FIXED（commit `072847b7`）

- `backfill_learning_cases` 绕过 `aschedule_ingestion` 后台投递，命令内同步逐条 `await ingest(...)`；单条失败 warning（异常文本经 `redact_secrets_in_text` 脱敏）+ 按类 failed 计数不中断；输出措辞由「已调度」改为「已摄取 N 条、失败 M 条」，completed 事件上报 `ingested/failed` 双计数。
- 测试重写：mock 对象由 `aschedule_ingestion` 换成 `ingest`（断言 handle() 返回前逐条 await 完成）；新增端到端用例（mock 向量栈真跑摄取，命令返回时 `KnowledgeEntity` 已落库）与失败计数用例（毒丸条目不中断其余摄取）。

### ME-01 — FIXED（commit `d479b590`）

- `_build_content` 中 `trace.error` 先经 `redact_secrets_in_text` 脱敏再截断 500 字符入 content；新增守护测试断言 Bearer token 不出现在事件任何字段、`***REDACTED***` 在场。存量实体下次重摄翻一次版本属预期（一次性）。

### LO-01 — FIXED（commit `f814ccea`）

- 三个 MCP normalizer 的 5 处 warning 事件（`knowledge_normalize_source_missing` ×3、`knowledge_normalize_plan_version_missing`、`knowledge_normalize_anchor_plan_missing`）补齐 `component="knowledge", category="sampling"`，与 `learning_case.py` 归类口径一致。

### LO-02 — PARTIALLY FIXED（commit `e8df0951`）

- `views.py` 4 处写入点（AnalyzeRepository / CreateCodingPlan / ImproveCodingPlan / ExecuteCodingPlan）投递均携带 `initiated_by_user_id=str(request.user.id)`，并补注释说明「无触发用户的调用点缺省 system」兜底语义。
- **跳过**：`work_item_execution_service.py` 2 处（L274-279 / L335-342）——该文件正被 Phase 101-03 并发修改（本次执行的硬约束：不得触碰），待 Phase 101 合流后按同款模式补传（编排发起者透传）。

---

_Reviewed: 2026-07-22T04:25:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Fixed: 2026-07-22 — Claude (gsd-code-fixer), commits 300e5a17 / 072847b7 / d479b590 / f814ccea / e8df0951_
