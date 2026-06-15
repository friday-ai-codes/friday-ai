---
phase: 32-one-click-ingest
reviewed: 2026-06-15T19:55:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - server/delivery/models/ingest_run.py
  - server/delivery/migrations/0008_ingestrun.py
  - server/delivery/services/ingest_parsing.py
  - server/delivery/services/ingest_orchestrator.py
  - server/delivery/api/views.py
  - server/delivery/api/serializers.py
  - server/delivery/urls.py
  - server/knowledge/diff_archive.py
  - web/src/api/ingest.ts
  - web/src/api/index.ts
  - web/src/components/knowledge/IngestPanel.vue
  - web/src/pages/knowledge/ingest.vue
  - web/src/components/layout/AppSidebar.vue
  - web/src/locales/zh-CN.json
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: clean
resolution:
  fixed:
    - WR-01: 文档步零产出改记 skipped（含 reason），ingest() 回传产出数 + 守护测试
    - IN-01: 状态端点保留 IsAuthenticated 并补归属/范围说明注释（无 owner 字段，不过度设计）
    - IN-02: 前端加客户端轮询上限（2 分钟）+ timeout 态（复用错误渲染 + ingest.run.timeout）
    - "UI-WARNING-1: 新增 ingest.run.failed 文案，failed 态不再复用 partial"
    - "UI-WARNING-2: 派发→首轮状态空窗加 running 占位骨架"
  deferred:
    - "WR-02: 合成 commit_sha + 粗粒度 MR-diff 幂等致更新后 diff 静默陈旧 → 归入 Phase 33 (HDIFF：commit-anchored freeze + bi-temporal invalidation)；属「拉取 MR 元数据 / 新鲜度模型」范畴，超本 phase「纯编排既有能力」边界，留待 33 统一处理。"
  advisory:
    - IN-03: 前后端 URL 校验大小写不一致（后端 startswith 大小写敏感）— 体验瑕疵，非阻断
    - IN-04: Tailwind 4 建议 break-words → wrap-break-word（linter advisory）
    - "UI INFO: 外链 text-primary 越白名单 / 装饰图标 aria-hidden / font-medium 第 3 档字重 — 咨询性"
---

# Phase 32: Code Review Report — 一键摄取编排

**Reviewed:** 2026-06-15T19:55:00Z
**Depth:** deep
**Files Reviewed:** 14
**Status:** clean（WR-01 + 3 项 UI/IN 已修复并测试通过；WR-02 deferred → Phase 33 HDIFF；IN-03/IN-04 + 余 UI INFO 为咨询性 advisory）

## Summary

编排逻辑、步级隔离、SSRF 边界、脱敏、鉴权、INV-3/INV-6、后台派发、前端派发→轮询均符合 phase 契约，无 BLOCKER。

重点核验通过：
- **SSRF**：`aresolve_repo_and_mr` 强制命中已落库 `Repository` 才放行；真实 diff 拉取经 `repository` 自身凭证 client（`get_git_platform_client`），从不以用户 URL 为抓取目标；`board_url`/`mr_url` 仅解析标识符。
- **INV-3**（含未提交修订）：orchestrator 已移除 `knowledge.models` 直接引用，改用 `aarchive_exists` 读 helper + 字面值 `kind="code_change"`/`origin="workflow"`；已核对字面值与 `EntityKind.CODE_CHANGE`/`EntityOrigin.WORKFLOW` 完全相等，不会破坏 `generate_entity_id` 派生与检索。
- **INV-6 / 无旁路写**：WorkItem 经 `WorkItemService.upsert`、Document 经 normalizer→`DocumentService`，delivery 层不直写 WorkItem/Document/knowledge 模型。
- **脱敏**：步级/编排级 error 一律过 `_safe_error`（`_redact_secrets` + 截断）；diff 原文绝不进 `steps`/payload（payload 仅 archive_id/统计）。
- **鉴权**：`IngestDispatchView` / `IngestRunDetailView` 均 `IsAuthenticated`。
- **后台派发**：`run_in_background(factory, name=...)` factory 形态正确；run 行在派发前已 await create 落库，orchestrator `aget` 可命中。
- **前端**：`refetchInterval` 在 completed/failed 停轮，partial-success 与 load-error（不清空既有结果）渲染正确，i18n 键齐全，守护测试以真实 `zh-CN.json` 断言。

剩余为状态如实性 / 新鲜度 / 健壮性的 2 个 Warning + 4 个 Info，均非阻断。

## Warnings

### WR-01: 文档步在 normalizer 零产出时仍报 `ok`（状态不如实）

**File:** `server/delivery/services/ingest_orchestrator.py:152-161`
**Issue:** 步 2 仅以「`ingest()` 未抛异常」判定 `status="ok"`。但 `knowledge/ingestion.py:ingest` 在 normalizer 返回 `[]` 时（如 `feishu_document.normalize` 因 Project 不存在 / work_item 锚事件为空而返回 `[]`，见 `feishu_document.py:84-103`）只 `logger.warning` 后**静默 return**，不抛异常。结果：实际零实体入库，前端却显示「PRD/技术方案文档 · 成功」。这与 phase「结构化结果如实展示、不靠静态文案」的目标相悖（false-positive ok）。
**Fix:** 让 `ingest()` 回传是否实际产出事件，或编排侧在 step 2 之前/之后探测产物（如 Document/实体存在性）再据实记 `ok`/`skipped`：

```python
from knowledge.ingestion import IngestionRequest, ingest
events_ingested = await ingest(IngestionRequest(...))  # 改为返回 int/bool
status = "ok" if events_ingested else "skipped"
await _write_step(run, "document",
    StepResult(status=status, identifier=source_id,
               error="" if events_ingested else "未找到可摄取的文档/项目"))
```

### WR-02: 合成稳定 `commit_sha` + 粗粒度幂等导致 MR 更新后 diff 静默陈旧

**File:** `server/delivery/services/ingest_orchestrator.py:222,237-254`
**Issue:** `commit_sha = f"mr-{mr_iid}"` 对同一 MR 恒定。`archive_code_change` 幂等键为 `(source_kind, source_id, commit_sha)`（`diff_archive.py:554-556`），故 MR 有新提交后再次摄取会命中幂等短路返回 `None`，**不会刷新 diff**；随后 `aarchive_exists(source_kind, source_id)`（只按 source_kind+source_id，不含 commit_sha）为 True → 报 `ok`。即「MR 已变更但 RAG 内仍是旧 diff」却显示成功。同一粗粒度还会让「本次因凭证缺失失败、但存在旧归档」误判为 `ok`。
**Fix:** 若需反映 MR 最新状态，应取真实 head commit/MR 更新时间纳入 `commit_sha`（属「拉取 MR 元数据」，可能超本 phase「纯编排」边界——若刻意 out-of-scope，请在 step `ok` 文案/`error` 中标注「已存在归档，未必为最新」，并改用含 `commit_sha` 的判定区分本次产物：

```python
# 至少：明确「幂等命中既有归档」与「本次新归档」的语义，避免 ok 掩盖陈旧
if await aarchive_exists(_MR_SOURCE_KIND, source_id):
    StepResult(status="ok", identifier=source_id, link=mr_url,
               error="已存在归档（若 MR 有更新需手动重建）")
```

## Info

### IN-01: 状态端点无归属校验，任意已登录用户可读任意 run

**File:** `server/delivery/api/views.py:266-273`
**Issue:** `IngestRunDetailView.get` 仅按 `run_id` 取行，无 owner/项目维度过滤；任意已登录用户可凭 UUID 读取任意 run 的 board/MR 标识与脱敏 error。
**Fix:** 内部团队工具 + UUIDv4 不可猜，威胁面有限；如需收紧可加 `created_by` 字段并按 `request.user` 过滤。当前可接受，记录备查。

### IN-02: 后台任务在设终态前夭折则 run 永驻 `running`，前端无限轮询

**File:** `server/delivery/services/ingest_orchestrator.py:91`；`web/src/components/knowledge/IngestPanel.vue:76`
**Issue:** `IngestRun.objects.aget` 在 `try` 之外；该行或 worker loop 异常退出时，run 不会被置 `completed/failed`，前端 `refetchInterval`（running→2s）将无限轮询，无超时/心跳兜底。
**Fix:** 将 `aget` 纳入兜底，或前端对 `running` 设最长轮询时长/起始时间阈值后停轮并提示。

### IN-03: 前后端 URL 校验大小写不一致，`HTTPS://` 通过前端却被后端 400

**File:** `server/delivery/api/serializers.py:147`；`web/src/components/knowledge/IngestPanel.vue:29`
**Issue:** 后端 `value.startswith(("http://","https://"))` 大小写敏感；前端用 `/^https?:\/\//i`（不敏感）。用户输入 `HTTPS://...` 前端放行、后端 422/400，体验割裂（解析层 `urlparse` 本身大小写无关）。
**Fix:** 后端改 `value.lower().startswith(("http://","https://"))` 与前端对齐。

### IN-04: Tailwind 4 类名写法（lint warning）

**File:** `web/src/components/knowledge/IngestPanel.vue:261`
**Issue:** `break-words` 在 Tailwind 4 建议写作 `wrap-break-word`（linter warning）。
**Fix:** 替换为 `wrap-break-word`。

---

_Reviewed: 2026-06-15T19:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
