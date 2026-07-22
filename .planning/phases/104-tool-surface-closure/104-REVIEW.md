---
phase: 104-tool-surface-closure
reviewed: 2026-07-22T08:35:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - docs/workflows/ai-plan-generation-deprecation.md
  - server/mcp_tools/orchestration_delegate.py
  - server/mcp_tools/planning_service.py
  - server/mcp_tools/repository_analysis_service.py
  - server/mcp_tools/serializers.py
  - server/mcp_tools/views.py
  - server/services/process_runtime/architect_merge_adapter.py
  - server/services/process_runtime/entrypoint.py
  - server/tests/knowledge/test_mcp_artifact_sources.py
  - server/tests/mcp_tools/test_create_coding_plan_delegate.py
  - server/tests/mcp_tools/test_patch_target_guard.py
  - server/tests/mcp_tools/test_planning_tools.py
  - server/tests/mcp_tools/test_schema_snapshot.py
  - server/tests/mcp_tools/test_work_item_execution.py
  - server/tests/services/test_process_runtime_extra_evidence.py
  - server/tests/test_milestone_e2e_learning_case.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 104: Code Review Report

**Reviewed:** 2026-07-22T08:35:00Z
**Depth:** standard
**Files Reviewed:** 16（9 个 commit 的源码并集：ceb42613 / 3a3969d7 / 334930cf / 1b5beade / cd29f1ee / 2528409c / 9175d1e6 / a35d74e7 / 562f697c，排除 `.planning/`）
**Status:** issues_found

## Summary

对 Phase 104 工具面收口（improve/analyze 收敛统一编排、`planning_service.py` 退役、extra_evidence 接线、里程碑 E2E 验收）做标准深度审查。整体质量良好，重点核验结论：

- **删缝完整性**：全仓 `rg planning_service` / `rg plan_orchestration` 零命中；`services/plan_orchestration/` 目录已删；views 无悬空 import。随迁符号（`map_canonical_to_coding_plan`、`build_repository_analysis`、`normalize_context_chunks`、`_module_groups`/`_entry_points`/`_test_paths`/`_usage`/`PlanningResult`）经逐符号 diff 验证与删除前**字节级一致**。
- **contract/snapshot 一致性**：create/improve 视图实际响应键集与 `TOOL_SCHEMA_SNAPSHOT` 及 `test_schema_snapshot.py` 三方一致（含新增 `session_id`/`status`）。
- **feedback 块组装**：三段结构（原需求 / 最新版本摘要 / feedback）内容全部来自库内业务字段与用户输入，不含凭证类内容；日志与 merge trace 事件只带 `extra_evidence_count` 计数、不带证据正文，符合脱敏纪律。
- **版本映射边界**：空 canonical content（partial/failed）经 `content or plan_payload` 回退到 `map_canonical_to_coding_plan` 的最小结构，非 dict 内容有 isinstance 防御。但 **failed 态仍推进 `current_version` 指针**（见 WR-01）；并发改版竞态为既有语义随迁（见 WR-02）。
- **测试质量**：patch-target 守卫测试真实解析 dotted-path（含空集防御，非 vacuous）；E2E 用 md5 派生的确定性 bag-of-words embedding + 内存 Qdrant，无网络，强/弱双种子保证 top-1 断言有区分度。触及的 26 个测试本地全部通过；`uv run ruff check` 全绿。
- **观测规范**：`delegate_process_runtime` 进出口事件带 `category="caller"` / `component="mcp_tools"` / `duration_ms`，观测代码全部 best-effort 包裹。

无 Critical / BLOCKER。3 个 Warning（1 个新引入行为、2 个既有语义随迁但值得修）、4 个 Info。

## Warnings

### WR-01: improve 在 delegate `failed` 态仍产新版本并推进 `current_version`，可静默回退可执行方案

**File:** `server/mcp_tools/views.py:2100-2117`
**Issue:** `ImproveCodingPlanView` 对 `delegate.status` 不分支：`failed`（含 IN-03 护栏把编排异常映射成的 failed）时 `content == {}`，`plan_body` 回退为 `map_canonical_to_coding_plan({})` 的最小结构（`steps=[]`、`affected_files=[]`），仍 `acreate(version=next_version)` 并把 `plan.current_version` 推到该退化版本。而 `execute_coding_plan` 不带 `version_id` 时默认取最新版本（`views.py:2309-2314` `order_by("-version").afirst()`）——一次瞬时编排失败会让后续默认执行的"当前方案"从上一个好版本静默回退成空方案。`partial` 落新版本是测试固化的契约（`test_improve_coding_plan_partial_short_circuits_with_session`），但 CONTEXT 锁定决策只覆盖 DONE/partial 语义，未要求 failed 也推进版本指针。
**Fix:**
```python
# failed 态：返回 status="failed" + session_id 供排障，但不产退化版本、不动 current_version
if delegate.status == "failed":
    # 不 acreate 新 version，响应 version/version_id 回填 latest，或返回明确错误体
    ...
else:
    next_version = int(plan.current_version) + 1
    version = await McpCodingPlanVersion.objects.acreate(...)
    plan.current_version = next_version
    await plan.asave(update_fields=["current_version", "updated_at"])
```
（若响应外形必须恒含 version 键，可保留落版本行为但仅在 `status != "failed"` 时推进 `current_version` 指针，并在 schema 描述里写明。）

### WR-02: `current_version + 1` 读-改-写竞态：并发 improve 同 plan 触发 IntegrityError → 500（既有语义随迁）

**File:** `server/mcp_tools/views.py:2102-2117`
**Issue:** `next_version = int(plan.current_version) + 1` 后 `acreate(version=next_version)`，无锁无重试。两个并发 improve 读到同一 `current_version`，第二个 `acreate` 撞 `(plan, version)` 唯一约束抛 `IntegrityError` → 未捕获 → 500，且此时统一编排已完整跑完（时长/token 成本已花，结果丢弃）。收敛前旧代码同型（CONTEXT 锁定"递增语义不变"指版本号语义，非竞态处理），但收敛后单次请求成本从毫秒级确定性函数变成分钟级编排，撞车代价被放大。
**Fix:** 捕获 `IntegrityError` 后基于 `Max("version")` 重算重试一次落库（编排结果不必重跑）；或版本分配走 `sync_to_async` 包裹的 `select_for_update` 事务。至少把 IntegrityError 映射为 409 结构化错误而非 500。

### WR-03: improve 把未截断的 `context_chunks` 原文折入 requirement_text，stage_state 与 prompt 无体积上限

**File:** `server/mcp_tools/views.py:2055-2061`
**Issue:** `context_chunks` serializer 只限条数（`max_length=20`），单个 DictField 值体积不限。improve 将每个 chunk 整体 `json.dumps` 折入 requirement_text 第四段，随后写入 `ConvergenceSession.stage_state.decomposition.requirement_text` 并进入拆分/融合各阶段 prompt。旧确定性 seam 对 chunk 有 `content_preview[:500]` 截断（见随迁的 `normalize_context_chunks`），新链路无任何截断——PAT 调用方送 20 个大 chunk 可造出多 MB 的会话行与 LLM prompt（成本放大 + 可能超上下文窗口导致编排失败）。系统边界输入应设上限。
**Fix:**
```python
chunk_lines = "\n".join(
    json.dumps(chunk, ensure_ascii=False, default=str)[:2000] for chunk in context_chunks
)
```
（或复用 `normalize_context_chunks` 的 preview 截断语义后再折入。）

## Info

### IN-01: create_coding_plan 静默丢弃 `context_chunks`，与新增 docstring 的"同型"表述不一致

**File:** `server/mcp_tools/serializers.py:208-215`, `server/mcp_tools/views.py:1836-1991`
**Issue:** `CreateCodingPlanView` 校验后从不引用 `context_chunks`（收敛先例遗留），而 104-01 新增的 create docstring 说"与 improve 完全同型、详见 improve 契约"——improve 契约明确 chunks 折入 feedback 块被消费。同型表述会让调用方误以为 create 的 chunks 也进编排。
**Fix:** 在 create docstring 补一句"``context_chunks`` 当前 accepted-but-ignored（收敛后编排自带召回）"，或与 improve 对齐折入 requirement_text。

### IN-02: patch-target 守卫正则不覆盖 `mocker.patch(` / `unittest.mock.patch(` 拼写

**File:** `server/tests/mcp_tools/test_patch_target_guard.py:33-35`
**Issue:** `_TARGET_PATTERN` 只匹配 `monkeypatch.setattr` / `mock.patch` / 裸 `patch`。守卫清单内文件当前未用 `mocker.patch` 等拼写（经核不漏），但未来改写测试换拼写时守卫会静默缩水；空集防御是文件级总量断言，单文件正则失配不会显形。
**Fix:** 正则加 `mocker\.patch|unittest\.mock\.patch` 分支，或把空集防御下沉到 per-file（每个守卫文件至少提取到 1 个 target 或显式豁免）。

### IN-03: 容器链同 URL 契约测试的 URL 模板为字面复制而非从 task 源码派生

**File:** `server/tests/test_milestone_e2e_learning_case.py:362-367`
**Issue:** `container_url_template = "/api/mcp/tools/{tool_name}/"` 是 `task/core/knowledge_tools.py:267` 拼接式的手抄副本（server 测试无法 import task 包，docstring 已写明组合覆盖逻辑，task 半边由 `task/tests/test_knowledge_tools.py` 兜住）。若 task 侧改模板，本测试不会失败——契约漂移要靠 task 侧测试显形。可接受，仅记录。
**Fix:** 可选：读 `task/core/knowledge_tools.py` 源文件正则提取 f-string 模板做断言（仓库单体，路径可达），彻底消除两半边手抄。

### IN-04: `serializers.py` / `views.py` 存在全文件级 ruff format 漂移（既有状态）

**File:** `server/mcp_tools/serializers.py`, `server/mcp_tools/views.py`
**Issue:** `uv run ruff format --check` 报两文件需重排（合计 500+ 行 diff），漂移遍布全文件（含 Phase 104 之前的 TOOL_SCHEMA_SNAPSHOT 长行风格），非本 phase 引入；本 phase 新增行沿用了局部既有长行风格。lint（E501 ignored）全绿。
**Fix:** 单独提交一次 `ruff format` 全量整理（与功能变更分离），或在 CI 加 format --check 门禁前先清欠账。

---

_Reviewed: 2026-07-22T08:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
