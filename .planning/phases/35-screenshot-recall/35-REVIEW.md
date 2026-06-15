---
phase: 35-screenshot-recall
reviewed: 2026-06-15T23:59:00Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - server/services/screenshot_recall.py
  - server/chat/multimodal.py
  - server/delivery/api/views.py
  - server/delivery/urls.py
  - server/delivery/api/serializers.py
  - web/src/api/screenshotRecall.ts
  - web/src/components/knowledge/ScreenshotRecallPanel.vue
  - web/src/pages/knowledge/screenshot.vue
  - web/src/components/layout/AppSidebar.vue
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: clean
resolved_at: 2026-06-16T00:12:00Z
resolution: 3 WARNING 已修复（WR-01/02/03，含 UI-REVIEW UX-1/2/3）；INFO 项 advisory 暂缓
---

# Phase 35: Code Review Report

**Reviewed:** 2026-06-15T23:59:00Z
**Depth:** deep
**Files Reviewed:** 9
**Status:** clean（3 WARNING 已修复；INFO 为 advisory，暂缓）

## Resolution（2026-06-16）

3 个 WARNING + UI-REVIEW 的 3 个体验瑕疵已全部修复并各自原子提交（`fix(35):`），后端
service/API 测试（`--disable-socket`）与前端 `ScreenshotRecallPanel` vitest + `vue-tsc` 全绿：

- **WR-01**（降级原因混淆）：`extract_semantics` 返回 `(semantics, degrade_reason)`，区分
  `no_vision_model` / `extraction_failed`；API 透出 `degraded_code`，前端按码切文案、仅配置类
  降级展示「前往系统设置」。
- **WR-02**（空 query 退化检索）：三段语义全空时短路，不发起空串向量召回，按
  `extraction_failed` 降级返回。
- **WR-03**（score 越界）：`relevance` 在 API 边界经 `_clamp01` 钳制到 `[0,1]`（单调，不改排序）。
- **UX-1**：空态改 `v-else-if="!isError"`，与 error 互斥。
- **UX-2**：降级「前往系统设置」由 `<a href>` 改 `<RouterLink to="/admin">`（SPA 导航）。
- **UX-3**：召回区回显派生检索词；移除死 key `results.source`。

INFO 项（advisory，暂缓、不阻断）：
- **IN-01**：`validate_image_bytes` 报错文案写死「GIF」，与截图端点排除 GIF 的允许集不一致——
  属共享多模态校验文案，跨端点收敛需单独评估，本期暂缓。
- **IN-02**：Django 默认上传处理器对 2.5–10MB 文件瞬态落临时盘（框架层、自动清理，非应用持久化）——
  与「应用层不持久化原图」不变量不冲突，暂缓（如需严格全程不触盘可后续显式限定 upload_handlers）。

## Summary

截图识别需求（VIS-01）的后端编排与上传 UI 整体实现稳健，**核心不变量全部达成**：

- **不建图片向量库 / 不持久化原图**：`screenshot_recall.py` 仅在内存 `bytes → base64 inline` 送 LLM，无 `store_image_bytes` / `write_bytes` / `qdrant` / `EmbeddingService` 写入面；视图层亦不落库（有源码 grep 守护测试）。✓
- **复用既有召回**：召回唯一走 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["work_item"])`，未新建检索面，访问域经 `request.user` fail-closed。✓
- **零 env 凭证**：模型解析经 `ProviderConfigService.aresolve_or_error`，无任何 `os.environ` 读取。✓
- **graceful 降级**：无 provider / 无 default_model / 非 vision 模型 / 调用异常一律返回 `None → degraded=true`，不抛；两处 `except` 均只记 `error_type`，不记 `str(exc)`（防回显图片/密钥）。✓
- **vision 双判**：`_model_supports_vision` 同时校验 `PROVIDER_REGISTRY.supports_vision` 与 `infer_model_modalities` 含 `image`。✓
- **后端权威校验**：`validate_image_bytes(allowed=SCREENSHOT_RECALL_MIME_TYPES)` 限 png/jpeg/webp + ≤10MB + sniff + 声明一致性，与前端 `ACCEPTED_TYPES` / `accept` 列表一致；非图片/超大不进 LLM。✓
- **REST 鉴权**：`ScreenshotRecallView` `IsAuthenticated`（有未认证 401/403 测试）。✓
- **前端上传安全**：`URL.revokeObjectURL` 在替换/移除/卸载三处释放；三入口统一 `handleFile` 校验；`degraded` 经 `onSuccess` 与 `error`（`onError`）态明确区分。✓

未发现 BLOCKER。下列为 3 个 WARNING + 2 个 INFO，均为健壮性/一致性与边界，不阻断发布。

## Warnings

### WR-01: 召回阶段故障被静默呈现为「无结果」，掩盖基础设施错误

**File:** `server/services/screenshot_recall.py:242-247`
**Issue:** 当 `search_similar` 抛异常（如 Qdrant / RAG 后端不可用）时，`results = []` 且 `degraded=False`，前端因此进入 `no-results`（“未召回到相关需求”）分支。真实的检索故障与「截图确实无匹配需求」对用户完全不可区分——一次瞬时后端故障会被误读为「该截图没有相关需求」，且没有可重试的错误提示。docstring 标注此为有意设计（“语义在、召回空、走 no-results 而非 error”），但语义提取成功 ≠ 召回成功，二者应可区分。
**Fix:** 在召回 `except` 分支增加一个区分位（不污染 `degraded` 语义），让前端能渲染可重试错误：
```python
except Exception as exc:  # noqa: BLE001
    logger.warning("screenshot_recall.search_failed", error_type=type(exc).__name__)
    return {
        "degraded": False,
        "search_error": True,  # 新增：前端据此显示可重试错误而非 no-results
        "semantics": {...},
        "query": query,
        "results": [],
    }
```
（同步在 serializer + `ScreenshotRecallResult` TS 接口 + 面板状态机补一态。）

### WR-02: 空语义产生空 query，仍发起向量检索，可能召回退化/无关结果

**File:** `server/services/screenshot_recall.py:219-241`
**Issue:** 若 vision 模型返回 `{}` 或三段全空（`_parse_semantics_json` 仍返回非 `None` 的 `ExtractedSemantics("","","")`），`_build_query` 得到空串 `""`，随后仍以空 query 调 `search_similar("")`。空串 embedding 的最近邻是退化/任意结果，可能把无语义信号的「需求」当作召回项呈现给用户（或在 embedding 后端对空串报错时白白触发一次检索）。当前无空 query 短路。
**Fix:** query 为空时直接短路返回空召回，避免退化检索：
```python
query = _build_query(semantics)
if not query:
    return {"degraded": False, "semantics": {...}, "query": query, "results": []}
```

### WR-03: 错误响应体 `{code, error}` 与全仓 `{detail}` 约定不一致，前端无法回显后端校验文案

**File:** `server/delivery/api/views.py:328-344`
**Issue:** `ScreenshotRecallView` 的 400 返回 `{"code":..., "error":...}`，而同文件其余视图（`WorkItemDetailView` / `IngestRunDetailView` 等）一律返回 `{"detail":...}`，且共享前端 `client.ts:236-247` 仅解析 `parsed.detail`。结果：后端权威校验文案（如「图片过大，请上传 10MB 以内的图片。」「图片声明格式与文件内容不一致」）不会被 `useErrorHandler` 展示，用户只看到通用「请求失败 / 识别失败」。这与 35-UI-SPEC「后端拒绝时回显后端 message」契约不符；尤其 `mime_mismatch` 这类前端无法预检的分支，用户拿不到可操作原因。
**Fix:** 与全仓约定对齐，改用 `detail`（或补 `detail` 同时保留 `code` 供分支）：
```python
return Response({"detail": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST)
```

## Info

### IN-01: 校验失败文案提及 GIF，但截图端点刻意排除 GIF

**File:** `server/chat/multimodal.py:115,117`
**Issue:** `validate_image_bytes` 的硬编码报错文案为「请使用 PNG、JPEG、GIF 或 WebP。」/「图片格式不支持…」。当截图端点（`allowed=SCREENSHOT_RECALL_MIME_TYPES`，不含 GIF）拒绝一张 GIF 时，回显文案仍声称 GIF 可用，与端点实际允许集矛盾，对用户具误导性。
**Fix:** 报错文案改为依据传入 `allowed` 动态生成允许的扩展名集合（或截图端点用更窄文案），避免写死「GIF」。

### IN-02: Django 默认上传处理器可能把 >2.5MB 截图瞬态写入磁盘临时文件

**File:** `server/delivery/api/views.py:333`
**Issue:** 服务/视图代码确实「绝不落盘」，但 `validate_image_bytes`/服务读取前，Django 的默认 `TemporaryFileUploadHandler` 会把超过 `FILE_UPLOAD_MAX_MEMORY_SIZE`（默认 2.5MB）的 multipart 文件写入临时文件——介于 2.5–10MB 的截图原图字节因此会瞬态落盘（请求结束后框架自动清理）。这属框架层、非应用持久化（无 storage_ref、无 DB 记录、自动清理），与 INV「不建图片向量库 / 不持久化原图」实质不冲突，但 `screenshot_recall.py` docstring「绝不落盘」的强表述仅对应用代码成立。
**Fix:** 如需严格保证全程不触盘，可在该端点显式限定 `request.upload_handlers = [MemoryFileUploadHandler(...)]`（需在读取 FILES 前设置），或调高内存阈值；否则建议把 docstring/不变量措辞收敛为「应用层不持久化原图」以免过度承诺。

---

_Reviewed: 2026-06-15T23:59:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
