---
phase: 27-feishu-api-fixes
plan: 03
subsystem: feishu-client
tags: [feishu, fix-01, fix-03, fix-04, defensive-json, work-item, comments, backward-compat, dedup-drift]
dependency_graph:
  requires:
    - "services.feishu_parsing（Plan 27-01 共享 helper：strict/safe_response_json、build_feishu_fields、flatten_fields、rich_text_to_markdown、parse_comments）"
    - "Plan 27-02 canonical services/feishu.py 等价写法（作一致性参照）"
  provides:
    - "near-dup feishu.client FeishuClient 三项修复（FIX-01/03/04）：work_item_type 必填 fail-loud、WorkItemInfo.feishu_fields 完整元数据、get_comments fail-soft"
    - "webhook/workflow 路径（feishu/views.py、feishu_workitem.py、wait_feishu.py、mr_service.py）与 normalizer/mcp 路径（services.feishu）解析行为完全一致，消除两份 client 漂移"
  affects:
    - "feishu.client 公开方法签名：get_work_item / get_comments 的 work_item_type 变必填（仅去默认，不重排参数）"
    - "feishu.client.WorkItemInfo 新增 feishu_fields 属性（带默认值，向后兼容既有构造）"
tech_stack:
  added: []
  patterns:
    - "近重复 client 取数链路消费 27-01 共享 helper，与 canonical client 同源、断言同输入同输出"
    - "失败语义二分：硬取数路径（get_work_item / get_plugin_token）strict_response_json fail-loud；可选 facet（comments 端点）safe_response_json fail-soft 返回 []"
    - "respx + pytest-asyncio mock httpx，pytest-socket 网络隔离，先 mock token 端点再 mock 业务端点"
key_files:
  created:
    - server/tests/test_feishu_api_client.py
  modified:
    - server/feishu/client.py
decisions:
  - "feishu.client 本无独立 relation 端点（无 get_work_item_relations）→ 本 plan 只落 FIX-01/03/04 三项，不涉 FIX-02（与 plan 范围一致）"
  - "get_work_item / get_comments 移除 work_item_type=\"story\" 默认改必填（fail-loud TypeError），不重排参数位置；实测全部 feishu.client 调用方（feishu/views.py L747/L1002、feishu_workitem.py、wait_feishu.py、feishu_im.py、mr_service.py 等）均已显式传 type（含 views L1002 显式传 payload.get(...,\"story\") 字符串），零回归"
  - "WorkItemInfo.feishu_fields: list[dict] = field(default_factory=list) 带默认，既有构造不破坏（向后兼容）；fields 拍平 dict 与 feishu_fields 完整对象双写"
  - "_parse_rich_text 改薄封装委托 rich_text_to_markdown，删除重复 _parse_paragraph（行为等价，消除漂移）"
  - "Task 2 的 respx 测试文件随 TDD RED 一体写入（test_feishu_api_client.py），断言与 Plan 27-02 services client 测试同输入同输出，佐证两份 client 无漂移"
metrics:
  duration: ~10min
  tasks: 2
  files: 2
  completed: 2026-06-15
---

# Phase 27 Plan 03: near-dup FeishuClient 同步修复 Summary

把 Plan 27-01 的 Django-free 共享 helper 接入**近重复** client `server/feishu/client.py`，与 Plan 27-02 对 canonical `services/feishu.py` 的修复**保持完全一致的解析行为**（同源 helper 消除漂移）。本 client 无独立 relation 端点，故落地 FIX-01（`work_item_type` 必填 fail-loud）、FIX-04（`WorkItemInfo.feishu_fields` 完整字段对象数组、旧 `fields` 拍平 dict 向后兼容）、FIX-03（`get_comments` 防御解析 fail-soft + 逐条解析）三项。公开签名严格向后兼容（仅去默认 + 仅新增带默认属性），不动任何调用方。

## What Was Built

### Task 1 — feishu/client.py 接入 helper（test `fa4415a2` → feat `8a281b6f`，TDD）
- **import 共享 helper**：`from services.feishu_parsing import (build_feishu_fields, flatten_fields, parse_comments, rich_text_to_markdown, safe_response_json, strict_response_json)`；文件顶部加注释指明 canonical 取数/解析在 `services/feishu.py` + `services/feishu_parsing.py`，本文件为兼容副本。
- **FIX-01**：`get_work_item` / `get_comments` 签名 `work_item_type: str = "story"` → `work_item_type: str`（必填、保持关键字位置不变，不传即 `TypeError` fail-loud，PF-09 不再静默落 story）。
- **FIX-04**：`WorkItemInfo` 新增 `feishu_fields: list[dict] = field(default_factory=list)`（既有构造因默认值不破坏）；字段解析双写 `feishu_fields = build_feishu_fields(raw_fields)` + `fields_dict = flatten_fields(raw_fields)`；description 经 `rich_text_to_markdown`；status 仍取 `work_item_status.state_key`；保留 err_code≠0 / 空 items 抛异常语义。
- **硬路径防御解析**：`get_work_item` / `get_plugin_token` 的 `.json()` 换 `strict_response_json`，非 JSON → 抛 `FeishuResponseError`（带脱敏 body 截断片段，禁含凭证）。
- **FIX-03**：`get_comments` 的 `.json()` 换 `safe_response_json`，`data is None`（非 JSON）→ `[]` + warning；解析改 `parse_comments(data)` 逐条取 id/content/created_at/author/thread_parent_id。
- **去重消漂移**：`_parse_rich_text` 改薄封装 `return rich_text_to_markdown(rich_text)`，删除重复 `_parse_paragraph`（行为等价）。
- `add_comment` / `update_field` / `transition_status` / `test_connection` / `FeishuAPIError` 本 plan 不改行为（按计划避免越界）。

### Task 2 — feishu.client respx 单测 + 一致性回归（随 TDD RED 一体写入 `fa4415a2`）
- 新建 `server/tests/test_feishu_api_client.py`（7 用例），`@respx.mock` + `pytest.mark.asyncio`，直接传凭证构造 client 绕过 DB 工厂，先 mock token 端点再 mock 业务端点。
- fixture 取 DOMAIN §16 形状（issue 1000000006，含 `field_000001`(alias prd_url, link)、`field_000002`(select `{label,value}`)、`field_000008`(关联多选)、description 富文本）。
- 断言与 Plan 27-02 的 `test_feishu_service.py` 对应用例**同输入同输出**（feishu_fields/fields/status/description、评论 id/content/author/thread_parent_id），佐证两份 client 无漂移。
- FIX-01（不传 type → TypeError × 2）、FIX-03（非 JSON → [] / 正常逐条解析）、FIX-04（feishu_fields 完整 + fields 拍平 + 富文本）、硬路径（非 JSON 抛 FeishuResponseError、消息不含凭证）各有断言覆盖。

## Verification Results

- `uv run pytest tests/test_feishu_api_client.py -q` → **7 passed**（pytest-socket 隔离，全部经 respx mock，无真实网络）。
- 联合回归 `tests/test_feishu_api_client.py + tests/services/test_feishu_service.py + tests/services/test_feishu_parsing.py + tests/test_feishu.py + tests/workflows/test_nodes.py` → **89 passed**（两份 client 测试同绿 + webhook/workflow 路径既有测试/mock 未破坏，签名变更零回归）。
- `uv run ruff format --check feishu/client.py tests/test_feishu_api_client.py` → 均 already formatted；`uv run ruff check feishu/client.py tests/test_feishu_api_client.py` → All checks passed。

## Backward Compatibility Verification

实测全部 `feishu.client.FeishuClient` 调用方在签名变更后零回归（均已显式传 `work_item_type`）：
- `feishu/views.py:747`（显式 `work_item_type=work_item_type`）、`feishu/views.py:1002`（显式 `payload.get("work_item_type_key", "story")` 字符串，仍是显式实参，不触发 TypeError）。
- `workflows/nodes/integrations/feishu_workitem.py:183`、`workflows/nodes/control/wait_feishu.py:186`、`services/feishu_im.py:802` 均显式传 type。
- `workflows/services/mr_service.py`、`projects/views.py`、`workflows/triggers/handlers/feishu.py` 引用 `feishu.client` 但不调用 `get_work_item`/`get_comments`（不受签名变更影响）。
- `WorkItemInfo` 新增字段带 `default_factory`，既有 `WorkItemInfo(...)` 构造无需改动。

## Deviations from Plan

**1. [Rule 3 — 满足 plan Task 2 verify 门禁] feishu/client.py 顺带 ruff format 收敛两处预存多行表达式**
- **Found during:** Task 1（GREEN 提交前 `ruff format --check` 报 1 file would be reformatted）
- **Issue:** `update_field` 的 `raise FeishuAPIError(...)` 与 `create_feishu_client_for_project` 的 `raise ValueError(...) from e` 为**预存**多行格式（非本 plan 编辑区），但 plan Task 2 verify 显式要求 `ruff format --check feishu/client.py` 通过。
- **Fix:** 对整文件跑 `ruff format`（纯格式：两处多行表达式折叠为单行，无逻辑改动），满足门禁。
- **Files modified:** server/feishu/client.py
- **Commit:** 8a281b6f（随 GREEN 一并提交）

> 注：Task 2 的 respx 测试文件按 TDD 流程在 RED 阶段（`fa4415a2`）一体写入并提交，GREEN（`8a281b6f`）落地 client 实现后转绿；Task 2 无独立新增代码提交。

## Known Stubs

None — 三项修复均有真实实现与 respx 断言覆盖，无占位/空值流向。

## Threat Surface Scan

无计划 `<threat_model>` 之外的新增安全面。T-27-07（get_comments 经 safe_response_json fail-soft 返回 []，webhook 摄取不崩断）、T-27-08（get_work_item strict_response_json + err_code/空 items 校验 fail-loud 不静默落错 type 数据）、T-27-09（两份 client 强制共享同一 helper，单测断言同输入同输出消除路径间漂移）均经 27-01 helper 落地并由本 plan 接线 + 断言覆盖；异常消息脱敏（不含 plugin_token/plugin_secret）经测试验证。

## Self-Check: PASSED

- FOUND: server/feishu/client.py
- FOUND: server/tests/test_feishu_api_client.py
- FOUND: commit fa4415a2（Task 1 RED）
- FOUND: commit 8a281b6f（Task 1 GREEN）
