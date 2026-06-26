# 87-02 SUMMARY — feature list 多源输入 + 结构化抽取（BOARD-01 输入侧）

**Status:** Done · **Wave:** 1 · **Requirements:** BOARD-01

## 交付物

| 文件 | 说明 |
|------|------|
| `server/agents/call_source.py` | 新增 `CallSource.BOARD_SPLIT = "board_split"`（枚举 24→25，docstring 计数同步） |
| `server/initiatives/services/feature_list_extractor.py` | NEW `FeatureListExtractor`：`normalize_sources` + `extract_structure`（分块/token 预算/LLM/call_source） |
| `server/initiatives/services/__init__.py` | re-export `FeatureListExtractor` |
| `server/tests/initiatives/test_feature_list_extractor.py` | NEW 6 用例（多源归一化 fail-soft / 82KB 分块降级 / call_source 作用域） |
| `server/tests/test_model_usage_call_source.py` | call_source 完整性基准 24→25（新增 `board_split`） |
| `.planning/observability/LOGGING-SPEC.md` | §4.1 表新增 `board_split` 行 |

## call_source

- 新值：`board_split`（`CallSource.BOARD_SPLIT`）。
- 基准：**24 → 25**（`test_enum_has_all_22_values` 断言 `== 25`）。
- 本 wave 仅本 plan 触碰 call_source。

## 实现要点

### 多源输入归一化（`normalize_sources`）
- 三源：文件上传 md（直接采用）+ 飞书文档链接（经 Phase 83 `create_feishu_doc_client_for_project` + `_extract_document_id` + `get_document_content` 回拉 markdown）+ 粘贴文本。
- 各源独立 try/except **fail-soft**：单源失败仅 `warning` 降级跳过，其余源仍合并；三源全空抛 `ValueError("无可用 feature list 输入源")`。
- 合并文本带 `## [来源:文件]` / `## [来源:飞书文档]` / `## [来源:粘贴]` 分隔标注。

### 结构化抽取（`extract_structure`）
- 按 markdown 标题（`#`/`##`）切块；标题缺失或单块超 token 预算（`_MAX_CHUNK_TOKENS=4000`，~2.5 字符/token 粗估）→ 按行贪心二次细切（`_split_oversize`），**绝不整篇塞 LLM 上下文**。
- 整体超 `_DEGRADE_TOKEN_THRESHOLD=8000` tokens → `degraded=True`。82KB demo（~3.2 万中文字符）实测 `chunk_count>1`、`degraded=True`。
- 每块 `with use_call_source(CallSource.BOARD_SPLIT):` 包裹 `build_chat_model(...).ainvoke(...)`（函数体内 import，保留 FakeChatModel seam）；JSON 解析 → 跨块合并去重 → 拍平 `features_flat`。
- 单块 JSON 解析失败仅跳过（不反噬整体）；LLM 传输/凭证异常 fail-loud 抛由 87-03/87-04，异常文本经 `redact_secrets_in_text`。

### 可观测
- 事件：`feature_list_normalize_completed` / `feature_list_extract_started` / `_completed` / `_failed`（caller，`component=board_split`，带 `duration_ms`/`chunk_count`/`degraded`），per-chunk `feature_list_chunk_extracted`（sampling，debug）。
- LLM 指标经 `arecord_llm_usage`（call_source=board_split）上报请求/token/TTFT/上游错误码（best-effort，绝不反噬）。
- 正文/异常仅记长度，不整篇入日志；脱敏不可绕过。

## 下游契约（供 87-03）

`extract_structure(...)` 返回归一化结构：

```json
{
  "modules": [
    {"name": "模块名", "features": [
      {"name": "功能点名", "description": "功能点原文片段", "acceptance": ["验收项1", "..."]}
    ]}
  ],
  "features_flat": [
    {"module": "模块名", "name": "功能点名", "description": "原文片段", "acceptance": ["..."]}
  ],
  "degraded": false,
  "chunk_count": 1
}
```

87-03 按 `features_flat` 逐 feature 建子看板 work_item（名=`name`、描述=`description`、模块=`module` 作分组）。

## 测试

`cd server && uv run pytest tests/initiatives/test_feature_list_extractor.py tests/test_model_usage_call_source.py -q` → **31 passed**。
- extractor 6/6（含 82KB demo 分块降级冒烟、call_source 作用域断言、飞书源 fail-soft）。
- call_source 基准 25 值。

## Blockers

无。
