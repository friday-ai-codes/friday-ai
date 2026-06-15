# Phase 35: 截图识别需求 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

用户上传截图，经多模态 LLM 提取文字/UI/业务语义 → 文本 query → 召回对应需求（复用现有 work_item/知识库 RAG，**非图片向量库**）。

覆盖需求：VIS-01（截图 → 多模态 LLM 提语义 → 文本 query → 召回需求，非图片向量库）。
依赖：相对独立（多模态 LLM 路线；召回复用既有 RAG 与 WorkItem 脊柱）。最后做。
不变量：INV-3（复用既有 knowledge 检索投影，不新建图片向量库）。
**Frontend phase（UI hint: yes）**：含截图上传 + 召回结果 UI。
明确排除：图片向量库（视觉相似/标注向量库）→ backlog（Out of Scope）。
</domain>

<decisions>
## Implementation Decisions

### 多模态 LLM 语义提取（Grey Area 1，VIS-01 标准 1）
- 后端 service（如 `server/services/screenshot_recall.py` 的 `extract_semantics(image)` + `recall_from_screenshot(image)`）：
  - 经既有 provider 解析（`services.provider_config` + `services.model_modalities`/`model_capabilities` 选**vision/多模态能力**模型；`agents.llm_factory` 构造 client）调多模态 LLM，传截图（image bytes/base64 → image_url/inline image content）。
  - 提取**文字/UI 元素/业务语义**为结构化或纯文本（OCR 文字 + UI 控件 + 业务意图描述），作为后续 query 的来源。
  - 无 vision 模型/解析失败：graceful 降级（`ProviderMissingError`/无 vision 能力 → 明确错误返回，不崩；对齐既有 `aresolve_or_error` 范式）。
- 凭证/模型经既有 `ProviderCredential`/`SystemSetting`/provider 解析（零 env、不绕过加密，遵 PROJECT 约束）。

### 文本 query → 召回需求（Grey Area 2，VIS-01 标准 2）
- 把提取的语义转为**文本 query**，喂给**既有 RAG/检索面**（`services/retrieval/rag_search` / hybrid_search / 既有 work_item·知识库召回）→ 召回对应需求（work_item）/相关知识。
- **复用既有检索 chokepoint**（含 Phase 22 fail-closed 排除、多仓参数等既有能力），不新建检索；召回结果按既有相关性返回，标注来源 work_item。
- 召回面可选复用 Phase 34 反查 / 既有 search_rag —— 取能召回 work_item/需求者。

### 非图片向量库（Grey Area 3，VIS-01 标准 3）
- **全程不建图片向量库**：截图只经多模态 LLM 转文本，再走文本 RAG；不存图片 embedding、不做视觉相似检索（视觉相似/标注向量库列 backlog，Out of Scope）。
- 截图本身：处理后**不持久化原图**（或仅瞬态/按需，避免引入图片存储面），仅用其提取的文本 query。

### 截图上传 + 召回 UI（Grey Area 4，frontend）
- 最小 UI（Vue 3 + TS + Tailwind + reka-ui/shadcn-vue，沿用 web/ 约定）：截图上传（拖拽/选择/粘贴）→ 提交 → 展示提取语义（可选）+ 召回的需求列表（work_item 标题/链接/相关度）。
- 经既有 API client + TanStack Query；i18n 默认中文（vue-i18n）；UI 设计契约由 gsd-ui-phase 产出 UI-SPEC。
- 上传大小/类型校验（图片格式、尺寸上限），前端 + 后端双校验。

### 范围守护（Grey Area 5）
- 本 phase 是**多模态 LLM → 文本 → 既有 RAG**编排 + 上传 UI；不新建检索/向量库/work_item 机制。
- 真实多模态模型可用性 + 召回质量依赖真实 vision 模型与真实数据 → human-UAT（本 phase 以"vision 调用接线 + 文本 query 喂既有 RAG + 召回结构化返回 + 降级不崩 + 单测 mock vision"为可自动验证标准）。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first；ORM `sync_to_async`；vision 调用 httpx async（复用既有 provider client）。
- 后端测试：pytest-django + factory-boy + respx（mock 多模态 LLM 响应 + 既有 RAG）+ pytest-socket。守护：① 截图 → mock vision → 提取文本语义；② 文本 query 喂既有 RAG → 召回 work_item；③ 无 vision 模型/缺供应商 graceful 降级不崩；④ 不建图片向量库（不写 embedding 面，可测无图片向量存储调用）；⑤ 上传校验（非图片/超大拒绝）。
- 前端测试：vitest + @vue/test-utils + happy-dom；上传 + 结果渲染 + i18n 文案守护。

### Claude's Discretion
- service 文件/命名、提取语义的结构（纯文本 vs 结构化 JSON）、召回走 rag_search 还是 Phase 34 反查、vision 模型选取策略（首个 vision-capable default vs 显式配置）、REST 端点形态（同步返回 vs 异步）、UI 落点路径、是否瞬态保留原图 —— 由实现按既有约定决定。
- 截图传给 LLM 的编码（base64 inline vs 临时 URL）—— 取既有 provider client 支持且不持久化原图者。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/provider_config.py`（provider 解析）、`server/services/model_modalities.py` + `model_capabilities.py`（vision/多模态能力检测）、`server/agents/llm_factory.py`（LLM client 构造）—— vision 模型解析 + 调用。
- `services` 既有 `aresolve_or_error` / ProviderMissingError 降级范式（参考 Phase 24 sensitive_detect 的可选 LLM 二分类降级）。
- `server/services/retrieval/`（rag_search / hybrid_search — 既有 RAG 检索面，含 Phase 22 fail-closed 排除、多仓参数）—— 文本 query 召回 work_item/知识。
- Phase 34 反查 service / 既有 work_item 检索 —— 召回 work_item 可选复用。
- `ProviderCredential`/`SystemSetting`/`SettingKeys`（加密凭证，零 env）—— 模型凭证。
- 前端既有上传 / 面板 / api client / TanStack Query / vue-i18n 范式。

### Established Patterns
- 可选 LLM 调用 graceful 降级（缺供应商/解析失败 return 错误不冒泡，Phase 24 范式）。
- 检索经既有 chokepoint（search_rag），fail-closed 排除贯穿。
- 凭证经 service 层加密解析，零 env，不绕过。
- async DRF + sync_to_async；前端 Vue3 <script setup> + TanStack Query + vue-i18n（zh-CN）；ruff line 100；中文 docstring；vitest 前端。

### Integration Points
- `server/services/`（screenshot_recall service）；`server/*/api/` + urls（上传 + 召回 REST，IsAuthenticated）。
- `web/src/`（截图上传 + 召回结果 UI + api 模块 + i18n）。
- 复用 provider_config / model_modalities / llm_factory / retrieval RAG。
</code_context>

<specifics>
## Specific Ideas

- 路线：截图 → 多模态 LLM（vision）→ 文字/UI/业务语义 → 文本 query → 既有 RAG 召回需求。绝不建图片向量库（VIS-01 标准 3 + Out of Scope）。
- 复用既有检索面（含 fail-closed 排除），召回 work_item/需求。
- 缺 vision 模型/供应商 graceful 降级不崩（Phase 24 范式）。
- 真实 vision 模型召回质量 → human-UAT。
</specifics>

<deferred>
## Deferred Ideas

- 图片向量库（视觉相似检索 / 标注向量库）—— backlog，Out of Scope（场景不匹配、太重）。
- 原图持久化 / 截图历史库 —— 非本 phase（仅瞬态用文本 query）。
- 真实多模态模型召回质量人工验收 —— human-UAT（需真实 vision 模型 + 真实需求数据）。
</deferred>

---

*Phase: 35-screenshot-recall*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
