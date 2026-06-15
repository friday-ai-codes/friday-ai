---
phase: 35-screenshot-recall
plan: 01
subsystem: backend
tags: [vision, multimodal, rag, recall, delivery-knowledge, graceful-degrade]
requires:
  - services.provider_config.ProviderConfigService.aresolve_or_error
  - services.model_modalities.infer_model_modalities
  - agents.llm_factory.build_chat_model
  - knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar
provides:
  - services.screenshot_recall.extract_semantics
  - services.screenshot_recall.recall_from_screenshot
  - chat.multimodal.validate_image_bytes
  - "REST: POST /delivery/screenshot-recall/"
affects:
  - server/chat/multimodal.py
  - server/delivery/api/views.py
tech-stack:
  added: []
  patterns:
    - "可选 LLM graceful 降级（镜像 Phase 24 sensitive_detect，error_type-only 日志）"
    - "复用既有交付知识检索 chokepoint（不新建检索 / 不建图片向量库）"
    - "瞬态 bytes → base64 inline 多模态调用（不持久化原图）"
key-files:
  created:
    - server/services/screenshot_recall.py
    - server/tests/services/test_screenshot_recall.py
    - server/tests/delivery/test_screenshot_recall_api.py
  modified:
    - server/chat/multimodal.py
    - server/delivery/api/views.py
    - server/delivery/api/serializers.py
    - server/delivery/urls.py
decisions:
  - "validate_image_bytes 从 store_image_bytes 抽出（非持久化双校验），store_image_bytes 改为先校验再落盘——零行为回归"
  - "新增 SCREENSHOT_RECALL_MIME_TYPES={png,jpeg,webp}，截图路径后端权威集与 35-UI-SPEC 前端 accept 对齐（排除 GIF，PLAN-CHECKER WARNING #2）"
  - "work_item_id 取 entity.source_id 优先回退 entity.entity_id；link ← provenance.feishu_url（PLAN-CHECKER WARNING #1，不假设序列化 dict 顶层 source_id）"
  - "vision 能力双判：PROVIDER_REGISTRY.supports_vision + infer_model_modalities 含 image，任一不支持即降级"
  - "提取降级（degraded=true）与召回异常（degraded=false + results=[]）严格区分"
metrics:
  duration: ~9m
  completed: 2026-06-15T15:40Z
  tasks: 3
  files: 7
---

# Phase 35 Plan 01: 截图识别需求后端服务 + REST Summary

截图经多模态 vision LLM 提取「文字/UI/业务意图」语义，拼文本 query 复用既有交付知识检索召回 work_item 需求；全程瞬态 base64 inline（不持久化原图、不建图片向量库），无 vision 模型/调用失败时 graceful 降级；配套 `POST /delivery/screenshot-recall/`（IsAuthenticated + multipart + 后端权威双校验）。

## What Was Built

- **`chat.multimodal.validate_image_bytes`**：从 `store_image_bytes` 抽出的非持久化双校验 helper（空/超 10MB/MIME/sniff/声明不一致），返回 `(mime_type, size)`，保留既有 `ImageValidationError` code；`store_image_bytes` 重构为先校验再落盘（零回归，5 个既有 chat 图片测试仍绿）。新增 `SCREENSHOT_RECALL_MIME_TYPES`（png/jpeg/webp）供截图路径收紧。
- **`services.screenshot_recall.extract_semantics`**：解析 vision-capable provider（`aresolve_or_error` + `infer_model_modalities`/`PROVIDER_REGISTRY.supports_vision` 双判）→ 构造多模态 HumanMessage（ANTHROPIC base64 source / 其余 image_url data-url，从内存 bytes 直接 base64）→ `build_chat_model(streaming=False).ainvoke` → 容错 JSON 解析为 `ExtractedSemantics{text,ui_elements,business_intent}`。任意降级条件/异常 → 返回 `None`（不抛，日志仅记 `error_type`）。
- **`services.screenshot_recall.recall_from_screenshot`**：extract → 拼文本 query → 复用 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["work_item"])` → 映射 35-UI-SPEC `RecalledRequirement`。返回 `ScreenshotRecallResult` dict（degraded 三态）。
- **`ScreenshotRecallView`**（`delivery/api/views.py`）+ 路由 `screenshot-recall/` + 文档 serializers：multipart `screenshot` 上传，IsAuthenticated，后端权威校验，透传服务 result（degraded 亦 200）。

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| RED | 守护测试（失败先行） | 5a7ecdd1 | tests/services/test_screenshot_recall.py |
| 1+2 | multimodal 重构 + screenshot_recall 服务（vision 提语义 + 既有 RAG 召回） | c57f94e3 | chat/multimodal.py, services/screenshot_recall.py |
| 3 | ScreenshotRecallView REST + 路由 + serializers + API 测试 | ad156499 | delivery/api/views.py, delivery/urls.py, delivery/api/serializers.py, tests/delivery/test_screenshot_recall_api.py |

## Deviations from Plan

**1. [合并提交] Task 1 与 Task 2 共用同一新建服务模块 `screenshot_recall.py`，以单个 `feat` 提交交付。**
- 原因：两函数（`extract_semantics`/`recall_from_screenshot`）构成一个内聚新模块，`recall_from_screenshot` 直接依赖 `extract_semantics`；把单个新文件的一个函数硬拆成两次提交无实际价值。RED 测试（覆盖两者）已先行单独提交。
- 影响：无功能影响；TDD RED→GREEN 顺序保留（test 提交在 feat 之前）。

其余按计划执行。`tests/knowledge/test_triggers.py` 的无关失败按指示忽略。

## Verification

- `tests/services/test_screenshot_recall.py` + `tests/delivery/test_screenshot_recall_api.py`：16 passed。
- `tests/chat -k image`（store_image_bytes 重构零回归）：5 passed。
- `ruff check`（仅改动文件）：All checks passed。
- grep 守护 `qdrant|EmbeddingService|store_image_bytes|write_bytes` on `services/screenshot_recall.py`：无命中（不建图片向量库 / 不持久化原图）。

## TDD Gate Compliance

- RED：`test(35-01)` @ 5a7ecdd1（模块缺失 → collection error，确认失败）。
- GREEN：`feat(35-01)` @ c57f94e3。
- 无 REFACTOR 提交（实现一次到位）。

## Self-Check: PASSED
- FOUND: server/services/screenshot_recall.py
- FOUND: server/tests/services/test_screenshot_recall.py
- FOUND: server/tests/delivery/test_screenshot_recall_api.py
- FOUND commits: 5a7ecdd1, c57f94e3, ad156499
