---
phase: 27-feishu-api-fixes
reviewed: 2026-06-15T04:16:00Z
depth: deep
files_reviewed: 4
files_reviewed_list:
  - server/services/feishu_parsing.py
  - server/services/feishu.py
  - server/feishu/client.py
  - server/feishu/models.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: clean
resolution:
  fixed_at: 2026-06-15T04:30:00Z
  warnings_fixed: 2
  info_deferred: 3  # IN-01/02/03 为可追溯性提示，非缺陷，按评审建议本 phase 不改
  commits:
    - daa3a221  # WR-01 fail-soft on valid-JSON non-dict feishu responses
    - 489af710  # WR-02 route remaining bare .json() through defensive parsing
---

# Phase 27: Code Review Report

**Reviewed:** 2026-06-15T04:16:00Z
**Depth:** deep
**Files Reviewed:** 4 source files (+ 3 test files cross-checked)
**Status:** clean（WR-01/WR-02 已修复并补测；IN-01/02/03 按评审建议本 phase 不改，见各条）

## Summary

修复落点（FIX-01/02/03/04）整体扎实且贴合 CONTEXT 锁定决策：解析逻辑收敛到 Django-free 的共享 helper `feishu_parsing.py`，两份 client 委托同一 helper 消除漂移；`feishu_fields` 完整对象数组保留 + 向后兼容拍平 `fields` 双写；`get_work_item` 移除 `work_item_type="story"` 默认值改必填（fail-loud）；relation/comment 端点走 fail-soft。

**安全 / 凭证脱敏：通过。** 日志只放 `response.text[:200]` 截断片段，从不放 `X-PLUGIN-TOKEN`/`X-USER-KEY`/`plugin_secret`；`log_ctx` 仅含 `plugin_id`/`project_key`/`work_item_id`（非机密）。未发现凭证/token 泄漏进日志或异常消息。

**向后兼容：通过（已核验）。** 移除 `get_work_item` 的 `story` 默认值是文档化的破坏性变更，但仓内全部 7 个调用方（`feishu/views.py` ×2、`feishu_workitem.py`、`feishu_work_item.py`、`feishu_im.py`、`wait_feishu.py`、`work_item_tools.py`、`work_item_context_service.py`）均已显式传 `work_item_type`，破坏面已闭合。`feishu_fields` 走新增字段（`default_factory=list`），不影响既有 `fields` 消费方。

主要问题集中在两个**防御式解析仍有缺口**的地方（见 WR-01/WR-02）。

## Warnings

### WR-01: fail-soft 端点对"合法 JSON 但非 dict"响应仍会抛 AttributeError

**Status:** 已修复（commit `daa3a221`）。`safe_response_json` 增加 `expect=dict` 类型守卫，集中收口；`get_comments`（两份 client）与 `get_work_item_relations` 改为 `expect=dict`，`[]`/标量响应 fail-soft 返回 `[]`；补 helper 层 + 两份 client 的 `[]`/标量单测。

**File:** `server/services/feishu.py:250,349` 与 `server/feishu/client.py:295`
**Issue:** `safe_response_json()` 只保证"非 JSON → 返回 None"，但当飞书返回**合法 JSON 且 content-type 为 json、却是 list/标量**（如 `[]`、`"err"`、`123`）时会原样返回该值。随后：

```python
data = safe_response_json(...)
if data is None:
    return []
if data.get("err_code") != 0:   # data 为 list/str/int → AttributeError，冒泡出函数
    return []
```

`get_comments` 与 `get_work_item_relations` 都声称"绝不抛断 / fail-soft 返回 []"（CONTEXT FIX-02/FIX-03 决策），但此路径会抛 `AttributeError`，违反该契约。`parse_comments` 自身有 `isinstance(data, dict)` 防御，但崩在它之前的 `data.get("err_code")` 检查上。现有单测只覆盖了 `text/plain` 与 json-content-type 的 `JSONDecodeError`（`test_safe_response_json_extra_data_returns_none`），未覆盖"合法 JSON 非 dict"形态，故缺口未被测试发现。

**Fix:** 在 `err_code` 判定前加类型守卫（两份 client 一致修改）：

```python
if not isinstance(data, dict):
    logger.warning("feishu_get_comments_parse_failed", reason="non_dict_payload")
    return []
if data.get("err_code") != 0:
    return []
```

或更佳：让 `safe_response_json` 增加可选 `expect=dict` 参数，非期望类型时 fail-soft 返回 None，集中收口。并补一条 `data = [...]`/标量的单测。

### WR-02: 部分 `.json()` 调用未纳入防御式解析，与 CONTEXT 决策不一致

**Status:** 已修复（commit `489af710`）。`add_comment` / `transition_status` / `update_field` / `test_connection` 的裸 `response.json()` 全部改走共享 helper：硬路径（取流转、字段写入）用 `strict_response_json` fail-loud，容错路径用 `safe_response_json(expect=dict)` 软失败；两份 client 一致修改，有效响应行为/返回契约不变。

**File:** `server/services/feishu.py:305,386,416,456` 与 `server/feishu/client.py:251,344,382,412,452`
**Issue:** CONTEXT 错误处理决策明确："**所有 `.json()` 调用都加防御**（避免 PF-10/11 这类非 JSON 响应直接崩）"。但 `add_comment`、`transition_status`、`update_field`（仅 `feishu/client.py`）、`test_connection` 仍使用裸 `response.json()`。这些端点同样面向同一个会返回 `Extra data`/HTML 的飞书网关，遇非 JSON 会直接抛 `JSONDecodeError`（未脱敏、未结构化记日志）。本 phase 范围聚焦 FIX-01~04，但既然决策措辞是"所有"，此为该决策的执行缺口。

**Fix:** 将上述 `response.json()` 替换为 `safe_response_json(...)`（写操作可用 strict 或 safe + 显式 err 判定），与已修复路径保持一致；至少 `add_comment`/`transition_status` 应统一，避免再次出现 PF-11 同类崩溃。

## Info

### IN-01: `derive_relations_from_fields` / `RelationSpec` 已实现但未被任何 client 调用

**File:** `server/services/feishu_parsing.py:435-468`
**Issue:** FIX-02 主路径（从 `work_item_related_multi_select` 字段派生关系）的纯函数已实现且有单测覆盖，但 `get_work_item` 未据此填充 `WorkItemInfo`，目前无生产调用方。符合 CONTEXT"本 phase 只产出派生结构、不落库、Phase 28 消费"的意图，非缺陷；记此条仅为可追溯性——确保 Phase 28 真正接上，否则 FIX-02 主路径在运行时仍是空转（relation 实际仍只走已降级的旧端点）。
**Fix:** 无需本 phase 改动；Phase 28 `WorkItemService.upsert` 接入时验证消费链路。

### IN-02: `feishu/client.py` 的 `get_comments` 注释"FIX-01 无默认"易误导

**File:** `server/feishu/client.py:260`、`server/services/feishu.py:314`
**Issue:** 行内注释 `# work_item_type 必填（FIX-01，无默认）` 暗示本 phase 移除了默认值，但 `get_comments` 的 `work_item_type` **原本就无默认**（仅 `get_work_item` 有 `="story"` 被移除）。注释属事实性轻微误导。
**Fix:** 删除/改为 "work_item_type 历来必填，与 get_work_item 保持一致"。

### IN-03: `feishu/models.py` 文件中段反向 import helper 常量

**File:** `server/feishu/models.py:186-190`
**Issue:** 在 models 文件 `ProcessedEvent` 之后、`KeyFields` 之前插入 `from services.feishu_parsing import ...`（带 `# noqa: E402`）。helper 为 Django-free，不构成循环依赖，唯一事实源收敛方向正确；但模块中段 import 不常见，依赖 `feishu.models` 在 import 期即加载 `services.feishu_parsing`。当前无害，记此条提示团队知悉该耦合方向（models → services helper 常量）。
**Fix:** 无需改动；可考虑把 import 提到文件顶部 import 区（仍保留 noqa 说明），减少"中段 import"的意外感。

---

_Reviewed: 2026-06-15T04:16:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
