# 87-01 SUMMARY — 飞书写 API 地基（BOARD-01）

**Status:** ✅ Done (autonomous, respx-covered, live-write deferred)
**Wave:** 1 | **Requirements:** BOARD-01

## 交付物

### `server/services/feishu.py`（EXTEND）
新增三方法（鉴权复用 `get_plugin_token()` + `X-PLUGIN-TOKEN`/`X-USER-KEY` 骨架，
镜像 `update_work_item_fields`）：

- **`create_work_item(project_key, work_item_type, name, *, description="", template_id=None, extra_fields=None) -> int`**
  POST `work_item/{type}/create`，请求体 `{name, field_value_pairs:[description 富文本], template_id?}`；
  `strict_response_json` fail-loud；`err_code != 0` 抛（异常文本经 `redact_secrets_in_text`）；
  返回新 id（`data.id` 备选 `data.work_item_id`）。
- **`add_work_item_relation(project_key, work_item_type, work_item_id, *, relation_type, target_id, target_type=None) -> bool`**
  POST `work_item/{type}/{id}/relation`，写 `relation_type=1` 关联项目跟踪 / 父子；
  `err_code==0` → True，否则 fail-loud 抛（脱敏）。
- **`detect_relation_capability(project_key, work_item_type) -> dict`**
  GET `work_item/{type}/meta`，`safe_response_json(expect=dict)` fail-soft；
  返回 `{parent_child, project_track, raw}`，保守默认（父子 False / 关联 True），**绝不抛**。
- 辅助纯函数 `_extract_relation_type_keys(meta)`（多候选形状容错解析关系类型 key）。
- structlog 事件：`feishu_work_item_create_started/_completed/_failed`、
  `feishu_work_item_relation_started/_completed/_failed`（caller, component=feishu, +duration_ms）、
  `feishu_relation_capability_probed`（sampling, debug）。日志字段仅 project_key/类型/长度/id，
  **无明文 token**。

### `server/tests/services/test_feishu_create_work_item.py`（NEW）
10 个 respx 用例：建项成功 / 备选 id 字段 / err_code 抛+脱敏断言 / 非 JSON fail-loud / 缺 id 抛；
写关系成功（断言 relation_type=1+target_id）/ err_code 抛；能力探测命中父子 / err_code 降级不抛 /
非 JSON 降级不抛。

### `.planning/phases/87-board-split-card/87-UAT.md`（NEW）
A-CREATE / A-REL / A-DEGRADE 三项 deferred live 验证清单（端点 / 请求体 / 返回字段名 /
关系类型预配 / 父子未配错误码），含真机验证步骤与 `[ASSUMED]→[VERIFIED]` 回填指引。

## 测试结果
- `tests/services/test_feishu_create_work_item.py`：**10 passed**。
- 回归 `test_feishu_service.py` + `test_feishu_project_board.py`：**18 passed**。
- `ruff check`：All checks passed。

## [ASSUMED] deferred（autonomous 不打断）
所有写 API 端点 / 请求体 / 返回字段名标 `[ASSUMED] A-CREATE/A-REL/A-DEGRADE`，
真机写验证（建项 / 写关系 / 关系类型预配 / 父子未配错误码）deferred 记 `87-UAT.md`。
Phase 78 仅验证读；写 API 从未真机跑通，本期以 respx + seam 覆盖契约。

## Blockers
无。autonomous 模式全程未阻断。87-03 可直接调用三方法（建子看板 + 关联项目跟踪 +
父子缺则降级）。
