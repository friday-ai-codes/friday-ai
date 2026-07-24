---
phase: 27-feishu-api-fixes
plan: 02
subsystem: feishu-client
tags: [feishu, fix-01, fix-02, fix-03, fix-04, defensive-json, work-item, comments, relations, backward-compat]
dependency_graph:
  requires:
    - "services.feishu_parsing（Plan 27-01 共享 helper：strict/safe_response_json、build_feishu_fields、flatten_fields、rich_text_to_markdown、parse_comments）"
  provides:
    - "canonical FeishuClient 四项修复（FIX-01/02/03/04）：work_item_type 必填 fail-loud、WorkItemInfo.feishu_fields 完整元数据、get_comments / relations 端点 fail-soft"
    - "Phase 28 WorkItemService.upsert（DOMAIN §13.1 步骤 2/4）与 knowledge/sources/feishu_work_item.py normalizer 的可靠回源"
  affects:
    - "services/feishu.py 公开方法签名：get_work_item / get_comments 的 work_item_type 变必填（仅去默认，不重排参数）"
    - "WorkItemInfo 新增 feishu_fields 属性（带默认值，向后兼容既有构造）"
tech_stack:
  added: []
  patterns:
    - "client 取数链路消费 27-01 共享 helper，消除两份 client 的解析漂移"
    - "失败语义二分：硬取数路径（get_work_item / get_plugin_token）strict_response_json fail-loud；可选 facet（comments / relations 端点）safe_response_json fail-soft 返回 []"
    - "respx + pytest-asyncio mock httpx，pytest-socket 网络隔离，先 mock token 端点再 mock 业务端点"
key_files:
  created:
    - server/tests/services/test_feishu_service.py
  modified:
    - server/services/feishu.py
decisions:
  - "get_work_item / get_comments 移除 work_item_type=\"story\" 默认改必填（fail-loud TypeError），不重排参数位置；实测全部 services.feishu 调用方（feishu_work_item normalizer / mcp work_item_context / agent work_item_tools / feishu_im）均已显式传 type，零回归"
  - "WorkItemInfo.feishu_fields: list[dict] = field(default_factory=list) 带默认，既有构造不破坏（向后兼容）；fields 拍平 dict 保留与 feishu_fields 完整对象双写"
  - "get_work_item_relations 降级为可选：safe_response_json 非 JSON → [] + warning 绝不抛；关系项标注 origin=feishu_relation_api，主路径不依赖此端点（走 27-01 derive_relations_from_fields）"
  - "_parse_rich_text 改为薄封装委托 rich_text_to_markdown，删除重复的 _parse_paragraph（行为等价，消除漂移）"
metrics:
  duration: ~12min
  tasks: 3
  files: 2
  completed: 2026-06-15
---

# Phase 27 Plan 02: canonical FeishuClient 四项修复 Summary

把 Plan 27-01 的 Django-free 共享 helper 接入 canonical `server/services/feishu.py`，一次性落地 4 个修复：FIX-01（`work_item_type` 移除 `="story"` 默认改必填、fail-loud）、FIX-04（`WorkItemInfo.feishu_fields` 保留完整字段对象数组、旧 `fields` 拍平 dict 向后兼容）、FIX-03（`get_comments` 防御解析 fail-soft + 正常逐条解析）、FIX-02（`get_work_item_relations` 端点降级为可选 fail-soft）。公开签名严格向后兼容（仅去默认 + 仅新增带默认属性），不动任何 ~50 调用方。

## What Was Built

### Task 1 — FIX-01 必填 type + FIX-04 feishu_fields + 硬路径防御解析（test `965c39fa` → feat `f2325d61`）
- `WorkItemInfo` 新增 `feishu_fields: list[dict] = field(default_factory=list)`（保留完整字段元数据；既有构造因默认值不破坏）。
- `get_work_item` 签名 `work_item_type: str = "story"` → `work_item_type: str`（必填、保持关键字位置不变，不传即 `TypeError` fail-loud，PF-09 不再静默落 story）。
- `get_work_item` / `get_plugin_token` 的 `.json()` 换 `strict_response_json`：非 JSON → 抛 `FeishuResponseError`（带脱敏 body 截断片段，禁含凭证）。
- 字段解析双写：`feishu_fields = build_feishu_fields(raw_fields)` + `fields_dict = flatten_fields(raw_fields)`；description 经 `rich_text_to_markdown`；status 仍取 `work_item_status.state_key`。
- `_parse_rich_text` 改薄封装 `return rich_text_to_markdown(rich_text)`，删除重复 `_parse_paragraph`（行为等价）。

### Task 2 — FIX-03 get_comments + FIX-02 relations 端点降级 fail-soft（test `8ae16dad` → feat `b2bcc433`）
- `get_comments` 移除 type 默认（必填）；`.json()` 换 `safe_response_json`，`data is None`（非 JSON）→ `[]` + warning；解析改 `parse_comments(data)` 逐条取 id/content/created_at/author/thread_parent_id。
- `get_work_item_relations` `.json()` 换 `safe_response_json`，非 JSON（PF-10 实测 `Extra data: line 1 column 5`）→ `[]` + warning，绝不抛；err_code≠0 仍降级 `[]`；关系项新增 `origin="feishu_relation_api"` 标注（主路径不依赖此端点）。

### Task 3 — canonical client respx 单测 + 回归 + 格式（test `244d31f3`）
- 新建 `server/tests/services/test_feishu_service.py`（9 用例），`@respx.mock` + `pytest.mark.asyncio`，直接传凭证构造 client 绕过 DB 工厂，先 mock token 端点再 mock 业务端点；fixture 取 DOMAIN §16 形状（issue 1000000006，含 `field_000001`(prd_url link)/`field_000002`(select)/`field_000008`(关联)/description 富文本）。
- FIX-01/02/03/04 各有断言覆盖；ruff format 通过。

## Verification Results

- `uv run pytest tests/services/test_feishu_service.py -q` → **9 passed**（pytest-socket 隔离，全部经 respx mock，无真实网络）。
- 联合 `tests/services/test_feishu_parsing.py` + `tests/mcp_tools/test_feishu_work_item_context.py` → **39 passed**（下游 mcp 签名回归未破坏）。
- `tests/knowledge/test_triggers.py` → **43 passed, 1 failed**：唯一失败 `TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once`（coding-trigger UUID）为**预存缺陷、与本 plan 无关**（27-01 SUMMARY 已记录，父提交即失败），不在范围。
- `uv run ruff format --check services/feishu.py tests/services/test_feishu_service.py` → 2 files already formatted；`ruff check` → All checks passed。

## Deviations from Plan

None - 计划按原文执行（仅去 work_item_type 默认 + 仅加带默认 feishu_fields 属性，向后兼容；接入 27-01 helper，不重实现解析）。

## Backward Compatibility Verification

实测全部 `services.feishu.FeishuClient` 调用方在签名变更后零回归：
- `knowledge/sources/feishu_work_item.py:149`、`mcp_tools/work_item_context_service.py:196,219`、`agents/tools/work_item_tools.py:84`、`services/feishu_im.py:802` 均已显式传 `work_item_type`。
- `mcp_tools/work_item_execution_service.py` / `technical_plan_service.py` 仅用 `add_comment`（未改签名）。
- 走 `feishu.client`（非本 plan）的调用方（`feishu/views.py`、`workflows/.../feishu_workitem.py`、`wait_feishu.py`、`mr_service.py`）不受影响。
- `WorkItemInfo` 新增字段带 `default_factory`，既有 `WorkItemInfo(...)` 构造无需改动。

## Known Stubs

None — 四项修复均有真实实现与 respx 断言覆盖，无占位/空值流向。

## Threat Surface Scan

无计划 `<threat_model>` 之外的新增安全面。T-27-04（comments/relations fail-soft）、T-27-05（get_work_item strict 校验 fail-loud）、T-27-06（body 截断脱敏、凭证不入日志/异常）均经 27-01 helper 落地并由本 plan 接线 + 断言（异常消息不含 token/secret）覆盖。

## Self-Check: PASSED

- FOUND: server/services/feishu.py
- FOUND: server/tests/services/test_feishu_service.py
- FOUND: commit 965c39fa（Task 1 RED）
- FOUND: commit f2325d61（Task 1 GREEN）
- FOUND: commit 8ae16dad（Task 2 RED）
- FOUND: commit b2bcc433（Task 2 GREEN）
- FOUND: commit 244d31f3（Task 3 finalize）
