---
phase: 35-screenshot-recall
verified: 2026-06-15T23:57:00Z
status: human_needed
score: 11/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "配置真实 vision-capable provider/模型，上传真实界面截图，确认提取语义与召回 work_item 质量"
    expected: "提取出合理的文字/UI/业务意图三段语义，召回相关 work_item 需求（相关度排序合理）"
    why_human: "需真实多模态模型 + 真实需求数据；recall 质量无法 mock 验证（CONTEXT Grey Area 5 / deferred human-UAT）"
  - test: "在浏览器打开 /knowledge/screenshot，分别用点击/拖拽/粘贴上传截图，观察 6 态视觉呈现"
    expected: "三入口均触发预览+提交；empty/loading/error/degraded(amber)/success/no-results 各态视觉正确、可读、响应式正常"
    why_human: "视觉外观、拖拽/粘贴交互、真实渲染观感无法以 grep/单测确认（视觉 UI 确认 deferred human-UAT）"
---

# Phase 35: 截图识别需求 Verification Report

**Phase Goal:** 截图 → 多模态 LLM 提语义 → 文本 query → 召回需求（复用既有 RAG/work_item，非图片向量库）+ 上传 UI。VIS-01。Graceful degradation；NO image vector DB；NO persisted original image。
**Verified:** 2026-06-15T23:57:00Z
**Status:** human_needed
**Re-verification:** 是 — 复核 + 重跑测试（前序报告无 gaps，本次重新确认代码与测试证据）

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 上传截图经多模态 LLM 提取文字/UI/业务语义 | ✓ VERIFIED | `extract_semantics` 构造多模态 HumanMessage（text+image block）→ `build_chat_model().ainvoke` → JSON 解析三段（screenshot_recall.py:118-173） |
| 2 | 提取语义转文本 query 喂既有交付知识检索召回 work_item | ✓ VERIFIED | `recall_from_screenshot` 拼 query → `DeliveryKnowledgeSearchService().search_similar(entity_kinds=[EntityKind.WORK_ITEM.value])`（:229-241）；测试断言 entity_kinds==["work_item"] |
| 3 | 无 vision / ProviderMissingError / 提取失败 graceful 降级（degraded=true，不抛） | ✓ VERIFIED | 多重降级分支均 return None → degraded dict；全程 try/except 仅记 error_type（:134-173, 219-227） |
| 4 | 全程不建图片向量库、不持久化原图（瞬态 bytes → base64 inline） | ✓ VERIFIED | grep 守护 `qdrant\|EmbeddingService\|store_image_bytes\|write_bytes\|DATA_DIR\|.save(` 无命中；`_build_image_block` 内存 bytes 直接 base64（:76-91） |
| 5 | REST 端点 IsAuthenticated + multipart + 类型/大小后端权威校验（拒绝 400） | ✓ VERIFIED | `ScreenshotRecallView`：permission_classes=[IsAuthenticated]、MultiPartParser、`validate_image_bytes(allowed=SCREENSHOT_RECALL_MIME_TYPES)` → 400（views.py:298-349）；测试覆盖 401/非图片/超大/缺文件 |
| 6 | 三种上传入口（点击/拖拽/粘贴）命中同一校验+预览路径 | ✓ VERIFIED | 点击/drop/paste 三入口均调 `handleFile`（Panel.vue:66,93,102,113） |
| 7 | 前端校验拒绝非图片与 >10MB（不发请求、焦点回 dropzone） | ✓ VERIFIED | `handleFile` MIME/size 校验内联红字 + 不发请求 + focusDropzone（:66-83）；spec 断言非图片/>10MB 未调 recall |
| 8 | 提交后 6 态可视：empty/loading/error/degraded/success/no-results | ✓ VERIFIED | Panel 结果区 6 态分支（data-testid 齐全 :260-417）；spec 覆盖各态 |
| 9 | 降级态区分于错误态（amber 卡片 + 前往系统设置链接，不弹 error toast） | ✓ VERIFIED | `result.degraded` 渲染 amber 卡片 + settingsLink（:284-304）；degraded 走 onSuccess 不弹 error toast；spec 断言 |
| 10 | 召回列表渲染 work_item title/来源/相关度/外链；语义卡可展开收起 | ✓ VERIFIED | `recall-item-{idx}` 列表 + 可折叠语义卡（:306-398）；spec 渲染 recall-item-0 含 title |
| 11 | 全部文案走 screenshotRecall.* i18n（默认中文），侧边栏可进入 /knowledge/screenshot | ✓ VERIFIED | zh-CN.json `screenshotRecall` 块（:271）；AppSidebar mainNavItems `/knowledge/screenshot`（:87）；screenshot.vue 引用 Panel |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/screenshot_recall.py` | extract_semantics + recall_from_screenshot 编排 | ✓ VERIFIED | 259 行，两函数 + 降级三态 |
| `server/chat/multimodal.py` | validate_image_bytes 非持久化双校验 + SCREENSHOT_RECALL_MIME_TYPES | ✓ VERIFIED | helper :89；窄集 :33；ImageValidationError :54 |
| `server/delivery/api/views.py` | ScreenshotRecallView（multipart + IsAuthenticated） | ✓ VERIFIED | :286-349 |
| `server/delivery/urls.py` | screenshot-recall/ 路由 | ✓ VERIFIED | :39-43 |
| `web/src/components/knowledge/ScreenshotRecallPanel.vue` | 6 态面板 + 三入口 | ✓ VERIFIED | 419 行 |
| `web/src/api/screenshotRecall.ts` | screenshotRecallApi.recall | ✓ VERIFIED | FormData → POST /delivery/screenshot-recall/ |
| `web/src/pages/knowledge/screenshot.vue` | 路由页 | ✓ VERIFIED | 引用 ScreenshotRecallPanel |
| `web/src/locales/zh-CN.json` | screenshotRecall i18n 块 | ✓ VERIFIED | 顶层块 :271 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| screenshot_recall.py | ProviderConfigService.aresolve_or_error | vision 解析 + 降级 | ✓ WIRED |
| screenshot_recall.py | DeliveryKnowledgeSearchService.search_similar | entity_kinds=[work_item] | ✓ WIRED |
| views.py ScreenshotRecallView | recall_from_screenshot | REST 调用服务 | ✓ WIRED |
| Panel.vue | screenshotRecall.ts | useMutation 调 recall | ✓ WIRED |
| screenshotRecall.ts | POST /delivery/screenshot-recall/ | post(FormData) | ✓ WIRED |
| AppSidebar.vue | /knowledge/screenshot | mainNavItems | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端服务+API 测试 | `uv run pytest tests/services/test_screenshot_recall.py tests/delivery/test_screenshot_recall_api.py -q` | 16 passed | ✓ PASS |
| 无新 migration | `manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |
| 前端面板守护 | `pnpm exec vitest run ScreenshotRecallPanel.spec.ts` | 7 passed | ✓ PASS |
| 不建图片向量库/不落盘 | grep `qdrant\|EmbeddingService\|store_image_bytes\|write_bytes\|DATA_DIR\|.save(` on screenshot_recall.py | 无命中 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| VIS-01 | 35-01, 35-02 | 截图 → 多模态 LLM 提语义 → 文本 query → 召回需求（非图片向量库） | ✓ SATISFIED | 后端编排 + REST + 前端面板全链路验证；REQUIREMENTS.md:61/118 标记 Complete |

### Anti-Patterns Found

无。新文件无 TBD/FIXME/XXX；grep 守护确认无图片向量库 / 原图落盘调用。

### Human Verification Required

1. **真实 vision 模型召回质量** — 配置真实多模态模型上传真实截图，确认语义提取 + work_item 召回质量。
   - Expected: 合理三段语义 + 相关 work_item 召回（排序合理）
   - Why human: 需真实 vision 模型 + 真实需求数据，recall 质量无法 mock（CONTEXT Grey Area 5）。
2. **视觉 UI 确认** — 浏览器打开 /knowledge/screenshot，点击/拖拽/粘贴三入口 + 6 态视觉呈现。
   - Expected: 三入口工作；6 态视觉正确、可读、响应式
   - Why human: 视觉外观与交互无法以 grep/单测确认。

### Gaps Summary

无阻断性 gap。所有 11 条可自动验证的 must-have 已通过代码 + 重跑测试证据确认（vision 提语义、文本 query 召回 work_item、graceful 降级、不建图片向量库、不持久化原图、REST 认证+双校验、前端三入口+6 态+i18n）。无新 migration（无新模型）。仅剩两项 CONTEXT 明确界定的 deferred human-UAT（真实模型召回质量 + 视觉 UI），故状态为 human_needed 而非 passed。已知 `tests/knowledge/test_triggers.py` 无关失败按指示不计入本阶段。

---

_Verified: 2026-06-15T23:57:00Z_
_Verifier: Claude (gsd-verifier)_
