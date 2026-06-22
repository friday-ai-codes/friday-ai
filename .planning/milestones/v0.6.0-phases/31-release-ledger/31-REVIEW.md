---
phase: 31-release-ledger
reviewed: 2026-06-15T10:06:00Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - server/delivery/models/release.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0006_releasebatch_releaserecord_releaseartifact.py
  - server/delivery/services/release_service.py
  - server/delivery/services/__init__.py
  - server/delivery/services/bitable_release_adapter.py
  - server/services/feishu_bitable.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: clean
warnings_resolved: 3
info_deferred: 3
---

# Phase 31: Code Review Report

**Reviewed:** 2026-06-15T10:06:00Z
**Depth:** deep
**Files Reviewed:** 7
**Status:** clean（3 个 WARNING 已修复，3 个 INFO 延后，详见「修复结论」）

## 修复结论（2026-06-15）

3 个 WARNING 均已修复并补回归测试（`tests/delivery/` + `tests/services/test_feishu_bitable.py` 全绿，157 passed）：

- **WR-01**：`BitableReleaseAdapter.ingest_from_table` 降级捕获扩到
  `(BitableAPIError, FeishuDocAPIError, httpx.HTTPError, ValueError)`——token 取失败 /
  网络抖动 / 非 JSON 响应统一降级 warning + 返回 None，不崩；只兜外部失败异常面，编程
  错误仍冒泡。
- **WR-02**：`ReleaseService._resolve_batch`（原 `_create_batch`）改为按 `external_ref`
  稳定自然键 `get_or_create` 幂等收敛；adapter 以 `{app_token}:{table_id}` 作 `external_ref`；
  新增条件唯一约束 `uniq_release_batch_external_ref`（migration 0007，镜像 ReleaseRecord
  范式）。重复摄取同一张表复用同批，不再累积空批次。
- **WR-03**：`_resolve_work_item` 对非整型 `work_item_external_id` 容错（`int()` 失败仅丢
  work_item 占位 + warning，**绝不丢整行**），raw_row 仍无损落库（REL-01）。

3 个 INFO 延后（骨架阶段风险低，留 REL-03 真实列映射时一并处理，符合本 phase 范围守护）：

- **IN-01**（`source` 死参数）：纯整洁性，无行为风险，留 REL-03 收口手动录入入口时一并清理。
- **IN-02**（`list_tables` 错误码分类不一致 / `.json()` 前不校验 HTTP status）：与 WR-01 同源，
  WR-01 已在 adapter 侧统一降级兜住运行时风险；client 内 `_get_json` 统一收口留 REL-03。
- **IN-03**（`add_artifact` 不校验 `artifact_type`）：骨架阶段无外部入口调用，留 REL-03 接入
  真实证据写入时补 service 入口枚举校验。

## Summary

Reviewed the Release 账本宽容模型 + Bitable client/adapter 骨架。核心契约都成立，质量良好：

- **raw_row 无损**：`ReleaseBatch`/`ReleaseRecord` 用 `JSONField` 原样存取；adapter 把完整 Bitable record 嵌在 `raw_row["record"]`，演进不丢数据（REL-01）。✓
- **DB 级自然键唯一**：`uniq_release_record_bitable_key` 偏特唯一约束（`condition=~Q(bitable_record_key="")`）已落 migration 0006，**与 Document `0005` 偏特唯一范式一致** —— 并发幂等 upsert 的去重在 DB 层强制，不靠应用层。✓（直接回答 review 焦点：是的，DB-enforced，镜像 Document/CommentEvent）
- **凭证解耦**：`create_bitable_client_for_project` 只读项目级 `feishu_app_id`/`feishu_app_secret_encrypted` + SystemSetting 兜底，`BitableClient` 内部组合 `FeishuDocClient` 走 `open.feishu.cn` internal 端点，**完全不触碰 `services/feishu.py` plugin token**（REL-02）。源码守护测试 + 我手工核对均确认。✓
- **INV-6**：adapter 经 `ReleaseService.ingest_batch` 收口，grep 守护覆盖三模型。✓
- **骨架范围**：业务列映射均标 `TODO(REL-03)`，未越界做真实列解析。✓

发现 3 个 WARNING（均关健壮性/语义，非崩溃性安全问题）+ 3 个 INFO。无 BLOCKER。

## Warnings

### WR-01: Adapter 降级只兜 `BitableAPIError`，token/网络/非 JSON 异常逃逸导致崩溃

**File:** `server/delivery/services/bitable_release_adapter.py:96-101`, `server/services/feishu_bitable.py:80-86,115-137`
**Issue:** `ingest_from_table` 的降级只捕获 `ValueError`（无凭证）与 `BitableAPIError`（`list_records` 失败）。但 `list_records` 内部先调 `get_tenant_access_token()`，该方法委托 `FeishuDocClient`，token 取失败时抛 **`FeishuDocAPIError`**（独立异常树，**非** `BitableAPIError` 子类）；此外 `client.get(...)` 网络异常（`httpx.ConnectError`/`TimeoutException`）与非 JSON HTTP 响应触发的 `response.json()` → `JSONDecodeError` 也都不是 `BitableAPIError`。这些异常会穿透 `except BitableAPIError`，**直接冒泡崩溃调用方**，违反本 phase 明确的「无凭证/API 失败 → warning + 返回 None，骨架不崩」契约（CONTEXT §范围守护、adapter docstring）。「配了但 app_id/secret 无效」「开放平台短暂网络抖动」在生产可达。
**Fix:** 扩大降级捕获范围，使「API/凭证类失败」统一降级为 `None`：

```python
from services.feishu_bitable import BitableAPIError
from services.feishu_doc import FeishuDocAPIError
import httpx

try:
    data = await client.list_records(app_token, table_id)
except (BitableAPIError, FeishuDocAPIError, httpx.HTTPError, ValueError) as exc:
    log.warning("bitable_list_records_failed", error=str(exc))
    return None
```

（或在 `BitableClient.get_tenant_access_token` 内把 `FeishuDocAPIError` 转译为 `BitableAPIError`，并在 `list_records`/`list_tables` 内 `try/except httpx.HTTPError` 后统一抛 `BitableAPIError`，让 adapter 单一异常面收口。）

### WR-02: 重复摄取同一 Bitable 表会每次新建空 `ReleaseBatch`，记录仍挂旧 batch（batch 级非幂等）

**File:** `server/delivery/services/release_service.py:76-98,174-201`
**Issue:** `ingest_batch` **每次无条件 `_create_batch`**，再按 `bitable_record_key` upsert 记录。记录级幂等正确（`get_or_create` 命中不新增），但 `get_or_create` 的 `defaults={"batch": batch, ...}` 只在**新建**时生效——已存在记录在 `if not created:` 分支里刷新 `raw_row`/`work_item`/`status`/`note`，**唯独不更新 `batch`**。后果：对同一张表二次 `ingest_from_table` 会创建一个**空的（或近空）`ReleaseBatch`**，而老记录永远指向首次 batch。长期重复摄取会累积空批次，且「记录属于哪次上线窗口」的语义失真。本 phase「幂等 upsert」是显式焦点，记录级 OK 但 batch 级有缺口。
**Fix:** 明确 batch 与 record 的幂等语义。最简：仅当本批至少落库 1 条新记录时才保留 batch，否则回收空 batch；或在 `not created` 分支把 `record.batch = batch` 一并刷新（并加入 `update_fields`）以反映「最近一次出现的批次」。需结合 DOMAIN §4 批次语义决策，建议在 REL-03 真实列映射前明确。

### WR-03: `work_item_external_id` 非整型时整行被丢弃，违反 raw_row 无损意图

**File:** `server/delivery/services/release_service.py:205-224`
**Issue:** `_resolve_work_item` 读 `raw_row.get("work_item_external_id")`，非 `None` 即 `WorkItem.objects.filter(work_item_id=external_id)`。若 Bitable 列回传非整型（如字符串/dict），`BigIntegerField` 查询会抛 `ValueError`，经 `ingest_batch` best-effort try/except **整行被跳过**——该行的 `raw_row` 连同原始 record 一并丢失，与 REL-01「演进不丢数据」意图相悖（占位字段的类型问题不应导致丢行）。
**Fix:** 占位反查对非整型容错——取值后 `try: external_id = int(external_id)` 失败则 `return None, None`（仍以 `raw_row` 无损落库 + `work_item=None` 占位），不让可选占位字段的脏值吃掉整行：

```python
external_id = raw_row.get("work_item_external_id")
if external_id is None:
    return None, None
try:
    external_id = int(external_id)
except (TypeError, ValueError):
    logger.info("release_record_workitem_external_id_invalid", value=str(external_id))
    return None, None
```

## Info

### IN-01: `upsert_record`/`_upsert_record` 的 `source` 参数未使用

**File:** `server/delivery/services/release_service.py:100-115,146-162`
**Issue:** `source` 形参从 `ingest_batch` 一路透传到 `_upsert_record`，但 `ReleaseRecord` 无 `source` 字段（source 在 batch 上），参数体内从未消费——死参数，易误导调用方以为记录级可分来源。
**Fix:** 移除 `upsert_record`/`_upsert_record` 的 `source` 形参（或加注释说明保留意图）。

### IN-02: `list_tables` 不分类频控错误，且两个端点 `.json()` 前不校验 HTTP 状态

**File:** `server/services/feishu_bitable.py:139-157`
**Issue:** `list_records` 对 `_RATE_LIMIT_CODES`/"rate limit" 分类抛 `RateLimitError`，但 `list_tables` 仅抛通用 `BitableAPIError`，分类不一致。两方法均直接 `response.json()` 不先看 HTTP status（依赖 httpx 默认 5s 超时），非 200 非 JSON 响应会抛 `JSONDecodeError`（与 WR-01 同源逃逸）。骨架阶段可接受。
**Fix:** `list_tables` 复用 `list_records` 的错误码分类；或在 REL-03 抽出统一 `_get_json(...)` 收口 status 校验 + 错误码分类。

### IN-03: `add_artifact` 不校验 `artifact_type` 取值

**File:** `server/delivery/services/release_service.py:117-131,238-254`
**Issue:** `artifact_type` 直接落库，Django `choices` 仅做表单校验、**不在 DB 强制**，故非法类型可写入 `delivery_release_artifact`。骨架阶段无外部入口调用，风险低。
**Fix:** service 入口对 `artifact_type` 做 `ReleaseArtifactType` 成员校验，非法值早抛，避免脏枚举入库。

---

_Reviewed: 2026-06-15T10:06:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
