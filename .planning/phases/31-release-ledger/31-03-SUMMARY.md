---
phase: 31-release-ledger
plan: 03
subsystem: delivery
tags: [release-ledger, bitable, open-platform-token, adapter, natural-key, raw_row, REL-02]
requires:
  - "31-01 Release 宽容模型（build_bitable_record_key + bitable_record_key + raw_row）"
  - "31-02 ReleaseService（ingest_batch 落库收口，消费预组装 bitable_record_key）"
  - "services/feishu_doc.py FeishuDocClient（开放平台 tenant_access_token 模式）"
provides:
  - "BitableClient — 复用 FeishuDocClient 开放平台 token + list_records/list_tables 骨架端点"
  - "create_bitable_client_for_project — 独立开放平台凭证解析（与项目 plugin token 解耦）"
  - "BitableReleaseAdapter — Bitable 行 → ReleaseService 落库（保留 raw_row + 预组装 natural key + 降级）"
affects:
  - "v2 REL-03（真实 Bitable 列结构映射 / 全量入库 — 待开放平台凭证 + 列样例）"
  - "Phase 32 一键摄取（可经 ReleaseRecord 关联）"
tech-stack:
  added: []
  patterns:
    - "组合复用既有 FeishuDocClient 委托 get_tenant_access_token（DRY，非复制 token 实现）"
    - "凭证来源 Project 级优先 + SystemSetting 回退 + 无凭证 raise ValueError（镜像 doc client）"
    - "adapter 经 service 单一写入入口落库（不旁路写 Release 表，守 INV-6）"
    - "无凭证/API 失败 try/except 降级返回 None + warning（骨架不崩）"
    - "natural key 唯一拼接点收口在 adapter（build_bitable_record_key），service 只消费成品 key"
key-files:
  created:
    - server/services/feishu_bitable.py
    - server/delivery/services/bitable_release_adapter.py
    - server/tests/services/test_feishu_bitable.py
    - server/tests/delivery/test_bitable_release_adapter.py
  modified:
    - server/delivery/services/__init__.py
decisions:
  - "BitableClient 内部组合 FeishuDocClient 实例并委托 get_tenant_access_token —— 真正复用开放平台 token（DRY），保证 token 端点为开放平台 internal 端点"
  - "凭证解析自带 _aget_system_open_platform_credentials（不复用 agents.tools 的 doc 版本），保持 services 层独立、解耦 plugin token"
  - "adapter raw_row 形状 = {bitable_record_key, record(原始全量), status/note/work_item_external_id(占位)}；原始 record 全量落 raw_row['record'] 保 REL-01 无损"
  - "natural key 拼接唯一收口在 adapter._map_record（经 build_bitable_record_key），ReleaseService 只消费成品 key（避免 31-02 已定的拼接漂移）"
metrics:
  duration: ~6m
  completed: 2026-06-15
  tasks: 3
  files: 5
---

# Phase 31 Plan 03: BitableClient + Adapter 骨架 Summary

飞书 Bitable client/adapter **骨架**（REL-02）落地：`BitableClient` 复用既有
`FeishuDocClient` 的开放平台 `tenant_access_token` 模式（`open.feishu.cn` internal
端点，2h 缓存），凭证来源经独立解析器 `create_bitable_client_for_project`、**与项目
plugin token 来源完全解耦**；`BitableReleaseAdapter` 把 Bitable 原始行经
`ReleaseService.ingest_batch` 落库（保留 raw_row + 经 `build_bitable_record_key`
预组装 natural key），无凭证 / API 失败降级返回 None 不崩。6 个守护测试全绿。

## What Was Built

- **`server/services/feishu_bitable.py`**（Task 1）：
  - `BitableClient(app_id, app_secret)`：`OPEN_API_BASE = FeishuDocClient.OPEN_API_BASE`
    （`https://open.feishu.cn/open-apis`）；内部组合一个 `FeishuDocClient` 实例，
    `get_tenant_access_token` 委托其实现（真正复用开放平台 token，DRY；token 端点保证
    为开放平台 `/auth/v3/tenant_access_token/internal`）。
  - 骨架方法 `list_records(app_token, table_id, *, page_token, page_size)`：取 token →
    GET `{OPEN_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records`（DOMAIN
    §4 端点形状）+ Bearer + 分页 params → `code!=0` 分类抛错（RateLimit/通用），成功返回
    原始 `data`（含 items/has_more/page_token，**不解析列**）；可选 `list_tables` 骨架同形。
  - 异常 `BitableAPIError` + `RateLimitError` 子类（沿用 feishu_doc.py 风格）。
  - `create_bitable_client_for_project(project)`：项目级开放平台凭证优先
    （`feishu_app_id` + `decrypt_value(feishu_app_secret_encrypted)`）、回退 SystemSetting
    （`FEISHU_APP_ID`/`FEISHU_APP_SECRET`，加密则 decrypt）、无凭证 raise `ValueError`；
    自带 async 凭证解析 helper，**不**取 `services/feishu.py` plugin token。
  - 真实列解析处标 `TODO(REL-03)`。
- **`server/delivery/services/bitable_release_adapter.py`**（Task 2）：
  - `BitableReleaseAdapter(*, client=None, service=None)`：依赖可注入（测试友好），缺省
    内部构造 `ReleaseService`。
  - `ingest_from_table(*, project, app_token, table_id, source=ReleaseSource.BITABLE)`：
    无注入 client → `create_bitable_client_for_project`（捕 `ValueError` → warning +
    返回 None 降级）→ `list_records`（捕 `BitableAPIError` → 降级 None）→ 每条经
    `_map_record` 占位映射 → `ReleaseService.ingest_batch` 落库返回 `ReleaseBatch`。
  - `_map_record`：raw_row = `{bitable_record_key(经 build_bitable_record_key 预组装),
    record(原始全量保留), status/note/work_item_external_id(从 fields 顶层占位取值)}`；
    natural key 唯一拼接点收口在此，业务列映射标 `TODO(REL-03)`。
- **`server/delivery/services/__init__.py`**（Task 2 修改）：re-export `BitableReleaseAdapter` + `__all__`。
- **`server/tests/services/test_feishu_bitable.py`**（Task 3）：4 用例，respx mock httpx 无真实网络。
- **`server/tests/delivery/test_bitable_release_adapter.py`**（Task 3）：2 用例，`django_db(transaction=True)` + 注入式 fake client。

## Verification Results

- `pytest tests/services/test_feishu_bitable.py tests/delivery/test_bitable_release_adapter.py`：
  **6 passed**（client 4：token 端点 host=open.feishu.cn + list_records 端点形状 + token
  缓存 call_count==1 + 凭证来源解耦源码守护；adapter 2：raw_row 无损 + natural key 经
  service 落库、无凭证降级返回 None 不抛 DB 无新增）。
- `python -c "from delivery.services import BitableReleaseAdapter"`（django.setup）：`ok`。
- `python -c "from services.feishu_bitable import BitableClient, create_bitable_client_for_project; assert OPEN_API_BASE.startswith('https://open.feishu.cn')"`：`ok`。
- 31-02 `test_release_inv6_guard.py`：**2 passed**（adapter 不旁路写 Release 三模型，守护对新增 adapter 文件仍 pass）。
- `ruff check`（仅本 plan 变更文件：feishu_bitable.py / bitable_release_adapter.py / __init__.py / 两测试）：All checks passed。
- 全程无真实网络（respx / fake client；pytest-socket 无 SocketBlockedError）。

## Deviations from Plan

None - plan executed exactly as written.

> 说明：plan Task 1 提示「可直接组合一个 FeishuDocClient 实例并委托其
> get_tenant_access_token，或抽取共享 token helper——任一由实现按 DRY 决定」。本实现
> 选择**组合 FeishuDocClient 委托 token**（plan 明示选项之一，非偏离）。

## Known Stubs

占位映射（非完成态，已标 `TODO(REL-03)`，属本 phase 设计内骨架，非缺口）：

- `BitableClient.list_records` 只返回原始 `data` 不解析多维表格列结构（真实列解析待开放
  平台凭证 + 列样例，REL-03 v2）。
- `adapter._map_record` 业务列 → 字段只占位（从 record `fields` 顶层同名键取
  status/note/work_item_external_id，取不到留空/None）；真实业务列映射 REL-03。
- `ingest_from_table` 只取 `list_records` 首页（真实分页遍历留 REL-03）。

以上为 CONTEXT 明确的「骨架 + 宽容模型」范围（真实列映射 = v2 REL-03，待开放平台
凭证），非阻断本 plan 目标的 stub；raw_row 全量保留确保 adapter 演进不丢数据。

## Threat Flags

无新增计划外安全面。开放平台凭证经 `decrypt_value` 解密后仅入 client 内存 + 单次
httpx 请求 header/body，不入 structlog（T-31-06 沿用 feishu_doc.py 不记 token 范式）；
token 端点为 open.feishu.cn 且不取 plugin token，源码守护测试覆盖（T-31-07）；无凭证 /
API 失败降级不崩（T-31-08）；adapter 经 ReleaseService 落库、INV-6 grep 守护覆盖（T-31-09）。

## Self-Check: PASSED

- FOUND: server/services/feishu_bitable.py
- FOUND: server/delivery/services/bitable_release_adapter.py
- FOUND: server/tests/services/test_feishu_bitable.py
- FOUND: server/tests/delivery/test_bitable_release_adapter.py
- FOUND: server/delivery/services/__init__.py（BitableReleaseAdapter re-export）
- FOUND commit c31eebd1 (Task 1), 69187842 (Task 2), ad31b929 (Task 3)
