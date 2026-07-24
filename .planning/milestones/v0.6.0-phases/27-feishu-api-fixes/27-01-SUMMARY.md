---
phase: 27-feishu-api-fixes
plan: 01
subsystem: feishu-parsing
tags: [feishu, parsing, defensive-json, relations, comments, fix-02, fix-03, fix-04]
dependency_graph:
  requires: []
  provides:
    - "services.feishu_parsing — 飞书响应防御解析 + 字段保留/提取 + 关系派生 + 评论解析 共享 helper（Django-free）"
    - "RelationSpec / derive_relations_from_fields — Phase 28 WorkItemService.upsert 步骤 4 消费"
    - "字段 key 常量唯一事实源（feishu.models.KeyFields 反向 import）"
  affects:
    - "server/feishu/models.py（KeyFields 改为反向 import helper 常量）"
    - "Plan 27-02（services/feishu.py）与 27-03（feishu/client.py）将调用本 helper"
tech_stack:
  added: []
  patterns:
    - "纯函数解析模块（无 Django / 无网络 / 无 DB），httpx.Response 本地构造测试"
    - "防御式 .json()：content-type 校验 + try/except，fail-soft(None) / fail-loud(FeishuResponseError) 二分"
    - "日志脱敏：错误信息只放 response.text[:200] 截断片段"
key_files:
  created:
    - server/services/feishu_parsing.py
    - server/tests/services/test_feishu_parsing.py
  modified:
    - server/feishu/models.py
decisions:
  - "字段 key 常量唯一事实源放 Django-free 的 feishu_parsing；feishu.models.KeyFields 反向 import（避免 services→models 层级倒置 + 消除重复，honoring plan-checker WARNING）"
  - "extract_related_ids 兼容 int / 数字字符串 / {id|value} dict 三态，非 list fail-soft 返回 []"
  - "extract_prd_url 优先 alias prd_url，回退 key field_000001；link 值兼容 str 与 {url/value/link/href}"
  - "parse_comments thread_parent_id 取 parent_id 或 thread_parent_id，无则空串"
metrics:
  duration: ~15min
  tasks: 3
  files: 3
  completed: 2026-06-15
---

# Phase 27 Plan 01: 飞书解析共享 helper Summary

为飞书取数/解析建立单一可信的 **Django-free 纯函数 helper** `server/services/feishu_parsing.py`，把本 phase 4 个修复点中可纯函数化的解析逻辑（防御式 JSON 解析、富文本→Markdown、完整 fields[] 保留/提取、关系派生、评论解析）一次性收敛，供 Plan 27-02/27-03 两份 client 共同调用以消除解析漂移；仅产出纯模块 + 单测，不改 client、不动调用方、不落库。

## What Was Built

### Task 1 — 防御式 JSON 解析 + 富文本上移 + 字段保留/提取（commit `a1fe1f02`）
- `FeishuResponseError`、`safe_response_json`（fail-soft → None）、`strict_response_json`（fail-loud → 抛异常）：content-type 校验 + `try/except` 包裹 `.json()`，错误日志/异常只放 `response.text[:200]` 截断片段（T-27-01 / T-27-02）。
- `rich_text_to_markdown` + `_paragraph_to_text`：由 `services/feishu.py` 的 `_parse_rich_text`/`_parse_paragraph` 逐行等价上移为模块级纯函数（paragraph/heading/bullet/ordered/code_block/image + bold/italic/code/link）。
- `build_feishu_fields`（保留完整 5 键元数据，FIX-04）、`flatten_fields`（向后兼容拍平）、`find_field`（按 key/alias）、`extract_select_label`、`extract_related_ids`、`extract_prd_url`、`extract_tech_doc_url`。
- 字段 key 常量（`field_000001`/`field_000009`/`description`/alias `prd_url`）定义在本模块作唯一事实源；`feishu.models.KeyFields` 改为反向 import 这些常量。

### Task 2 — RelationSpec + 关系派生 + 评论解析（commit `4233655b`）
- `RELATION_TYPE_BY_FIELD`、`RELATION_FIELD_TYPE_KEY="work_item_related_multi_select"`、`@dataclass RelationSpec`（relation_type/source_field_key/target_external_id/origin，对齐 DOMAIN §12.3）。
- `derive_relations_from_fields`：仅遍历关联多选字段，对每个 target id 产出一条 spec；`field_000008→belongs_to_project`、`planning_sprint→sprint`、`planning_version/actual_online_version→version`、未命中→`related`；空 `[]`/非关联字段不产出（FIX-02 主路径，纯函数）。
- `parse_comments`：对齐 `comment/list` 形状逐条取 id/content(经 rich_text_to_markdown)/created_at/author(缺省 Unknown)/thread_parent_id；`None`/缺键/形状不符 → `[]`（FIX-03 解析部分）。

### Task 3 — 单测补全（DOMAIN §16 实测 fixture）
- 测试随 Task 1/2 一体写入 `server/tests/services/test_feishu_parsing.py`（26 个用例），覆盖全部导出函数。
- fixture 取 DOMAIN §16 实测值：`field_000001`(alias prd_url, docx 链接)、`field_000002`(select `{label:"示例组A"}`)、`field_000008`([1000000004])、`planning_sprint`([6290075691])、`planning_version`([])；非 JSON 响应用 `httpx.Response(200, text=..., headers=...)` 本地构造，无真实网络（pytest-socket `--disable-socket` 下全绿）。

## Verification Results

- `uv run pytest tests/services/test_feishu_parsing.py -q` → **26 passed**（socket disabled，无真实网络）。
- `uv run ruff format --check services/feishu_parsing.py tests/services/test_feishu_parsing.py` → 2 files already formatted。
- `uv run ruff check ...` → All checks passed。
- `KeyFields` 反向 import 经 `django.setup()` 验证：`PRD_URL=field_000001`、`TECH_DOC_URL=field_000009`、`DESCRIPTION=description`（字符串值不变，~5 处既有调用方零回归）。

## Deviations from Plan

**1. [Rule 3 — 层级/去重，honoring plan-checker WARNING] 字段 key 常量落点 + feishu.models 反向 import**
- **Found during:** Task 1
- **Issue:** 计划 action 文本写"prd/tech key 从 `feishu.models.KeyFields` 引用"，但 plan-checker WARNING 要求 helper 保持 Django-free、严禁 import `feishu.models`（避免 services→Django-models 层级倒置）；同时计划又要求"禁硬编码重复"。
- **Fix:** 把常量定义在 Django-free 的 `feishu_parsing.py` 作唯一事实源，反过来让 `feishu.models.KeyFields` import 这些常量。两全：helper 不依赖 Django + 无重复。
- **Files modified:** server/services/feishu_parsing.py、server/feishu/models.py
- **Commit:** a1fe1f02

## Out-of-Scope Discoveries（不修，已记录）

- `tests/knowledge/test_triggers.py::TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once` 失败（`'[]' 不是有效 UUID`，coding-trigger 关联查询）。在父提交 `dccb2f54`（本 plan 改动前）复跑同样失败 → 确认**预存缺陷、与 27-01 无关**，超出范围。详见 `deferred-items.md`。

## Known Stubs

None — 全部导出符号均有真实实现与单测覆盖，无占位/空值流向。

## Self-Check: PASSED

- FOUND: server/services/feishu_parsing.py
- FOUND: server/tests/services/test_feishu_parsing.py
- FOUND: commit a1fe1f02（Task 1）
- FOUND: commit 4233655b（Task 2）
