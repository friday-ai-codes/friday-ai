---
phase: 31-release-ledger
verified: 2026-06-15T10:08:00Z
status: human_needed
score: 14/14 must-haves verified
overrides_applied: 0
human_verification:
  - test: "用真实开放平台 app_id/app_secret 配置 Project / SystemSetting，对真实飞书 Bitable 表跑 BitableReleaseAdapter.ingest_from_table"
    expected: "tenant_access_token 成功获取（open.feishu.cn internal 端点），list_records 返回真实 items，ReleaseBatch/ReleaseRecord 落库且 raw_row 含真实原始行、bitable_record_key 正确"
    why_human: "需真实开放平台凭证 + 真实 Bitable 数据；pytest-socket 隔离网络，本 phase 仅 respx mock 验证端点形状（CONTEXT 明确延 human-UAT）"
  - test: "对照真实 Bitable 列头/样例行，校验 REL-03 真实业务列 → ReleaseRecord 字段（status/note/work_item_external_id）映射正确性"
    expected: "真实列结构映射后 ReleaseRecord 业务字段与 Bitable 列语义一致"
    why_human: "REL-03 真实列映射 deferred 到 v2（需开放平台凭证 + 列样例）；本 phase 为占位映射骨架，真实语义需人工对照真实表确认"
---

# Phase 31: Release 账本 + Bitable adapter 骨架 Verification Report

**Phase Goal:** 宽容 Release 账本模型（ReleaseBatch/Record/Artifact + raw_row 无损）+ Bitable client/adapter 骨架 + 开放平台 tenant_access_token 解析独立于项目 plugin token + natural key `{app_token}:{table_id}:{record_id}`。REL-01, REL-02。SKELETON — 真实列映射 deferred 到 v2 REL-03。INV-6。
**Verified:** 2026-06-15T10:08:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                              | Status     | Evidence                                                                                                 |
| --- | ------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------- |
| 1   | ReleaseBatch/ReleaseRecord/ReleaseArtifact 三表存在于 DB（migrate 成功）                            | ✓ VERIFIED | migration 0006 创建三表 + index + 条件唯一约束；`makemigrations delivery --check` → No changes detected   |
| 2   | raw_row 原样存取无损（复杂 JSON 写入读回完全相等）                                                  | ✓ VERIFIED | `release.py` 两 row-bearing 模型均 `raw_row=JSONField(default=dict)`；test_release_models / service round-trip 绿 |
| 3   | ReleaseRecord 可用 work_item_external_id 占位（work_item=None）                                     | ✓ VERIFIED | `work_item FK(null, SET_NULL)` + `work_item_external_id BigIntegerField(null)`；`_resolve_work_item` 未命中留占位不抛 |
| 4   | Bitable natural key `{app_token}:{table_id}:{record_id}` 标识就位（字段存在、非空唯一）             | ✓ VERIFIED | `bitable_record_key` 字段 + `build_bitable_record_key` helper + `uniq_release_record_bitable_key` 条件唯一约束 |
| 5   | ReleaseArtifact.artifact_type 限定 mr\|branch\|commit\|diff\|release_note\|doc 枚举                  | ✓ VERIFIED | `ReleaseArtifactType` TextChoices 恰为六值；migration choices 一致                                        |
| 6   | Release 账本落库只经 ReleaseService 单一入口（旁路写表 grep 守护）                                  | ✓ VERIFIED | `test_release_inv6_guard.py::test_inv6_no_bypass_release_write` 绿；adapter 经 `self._service.ingest_batch` 落库 |
| 7   | ingest_batch 用 raw_rows 建 batch + 多记录，raw_row 原样保留                                        | ✓ VERIFIED | `ReleaseService.ingest_batch` → `_create_batch` + 逐行 `upsert_record`；test_release_service 绿            |
| 8   | ReleaseRecord 按 bitable_record_key 幂等 upsert（同 key 收敛同行）                                  | ✓ VERIFIED | `select_for_update().get_or_create(bitable_record_key=key, ...)` + raw_row 覆盖；幂等用例绿                |
| 9   | work_item 经 external_id 反查：命中连 FK，未命中留占位不抛                                          | ✓ VERIFIED | `_resolve_work_item` filter(work_item_id=external_id)，命中连 FK / 未命中 (None, external_id)；两路径用例绿 |
| 10  | BitableClient 用开放平台 tenant_access_token，非项目 plugin token                                   | ✓ VERIFIED | 委托 `FeishuDocClient.get_tenant_access_token`（OPEN_API_BASE=open.feishu.cn）；test 断言 host==open.feishu.cn |
| 11  | BitableClient 凭证来源独立解析，与 plugin token 来源解耦                                            | ✓ VERIFIED | `create_bitable_client_for_project` 取 Project/SystemSetting 开放平台凭证；源码守护 test 断言无 plugin token 入口 |
| 12  | list_records(app_token, table_id) 骨架走开放平台 bitable 端点形状                                   | ✓ VERIFIED | GET `/bitable/v1/apps/{app_token}/tables/{table_id}/records`；respx mock test 验证端点形状 + 返回原始 data |
| 13  | BitableReleaseAdapter 经 ReleaseService 落库，raw_row 不丢，natural key 正确                         | ✓ VERIFIED | `ingest_from_table` → `_map_record`（build_bitable_record_key 预组装）→ `ingest_batch`；test raw_row["record"] 全量 + key 断言绿 |
| 14  | 无开放平台凭证时 adapter 降级不崩（返回 None + warning，不抛）                                       | ✓ VERIFIED | `ingest_from_table` 捕 ValueError/BitableAPIError → warning + return None；降级用例断言 result is None + 无 batch |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact                                                  | Expected                                                   | Status     | Details                                                       |
| -------------------------------------------------------- | --------------------------------------------------------- | ---------- | ------------------------------------------------------------ |
| `server/delivery/models/release.py`                      | 三宽容模型 + 枚举 + natural-key helper                      | ✓ VERIFIED | 167 行，实质实现，无 stub；`__all__` 全导出                    |
| `server/delivery/migrations/0006_*.py`                   | 三表迁移（依赖 0005）                                       | ✓ VERIFIED | dependencies 指向 0005；三表 + 2 index + 条件唯一约束          |
| `server/delivery/services/release_service.py`            | ReleaseService 唯一写入入口                                 | ✓ VERIFIED | 255 行；ingest_batch/upsert_record/add_artifact，sync_to_async + atomic |
| `server/services/feishu_bitable.py`                      | BitableClient + 独立凭证解析                                | ✓ VERIFIED | 223 行；开放平台 token 委托 + list_records/list_tables + 凭证解析 |
| `server/delivery/services/bitable_release_adapter.py`    | BitableReleaseAdapter（经 service 落库）                    | ✓ VERIFIED | 147 行；ingest_from_table + _map_record + 降级                 |
| `server/tests/delivery/test_release_models.py`           | raw_row 无损 + natural key + 占位 + 枚举守护                | ✓ VERIFIED | 测试绿                                                        |
| `server/tests/delivery/test_release_service.py`          | ingest 幂等 + raw_row 无损 + work_item 反查守护             | ✓ VERIFIED | 测试绿                                                        |
| `server/tests/delivery/test_release_inv6_guard.py`       | 旁路写表 grep 守护 + writer 有效性                          | ✓ VERIFIED | 测试绿                                                        |
| `server/tests/services/test_feishu_bitable.py`           | respx token + 端点 + 凭证独立守护                          | ✓ VERIFIED | 测试绿（host 断言 + 源码解耦守护 + 缓存）                      |
| `server/tests/delivery/test_bitable_release_adapter.py`  | adapter raw_row 无损 + natural key + 降级守护              | ✓ VERIFIED | 测试绿                                                        |

### Key Link Verification

| From                              | To                                | Via                                    | Status   | Details                                                  |
| --------------------------------- | --------------------------------- | -------------------------------------- | -------- | -------------------------------------------------------- |
| models/__init__.py                | models/release.py                 | curated re-export                       | ✓ WIRED  | `from delivery.models.release import ...` + `__all__`     |
| services/__init__.py              | release_service / adapter         | curated re-export                       | ✓ WIRED  | ReleaseService + BitableReleaseAdapter re-export          |
| bitable_release_adapter.py        | ReleaseService                    | `self._service.ingest_batch`            | ✓ WIRED  | 不旁路写表；INV-6 grep 守护对 adapter 文件仍 pass         |
| feishu_bitable.py                 | open.feishu.cn tenant_access_token | 委托 FeishuDocClient.get_tenant_access_token | ✓ WIRED | OPEN_API_BASE=open.feishu.cn/open-apis；token internal 端点 |

### Behavioral Spot-Checks

| Behavior                                     | Command                                                                 | Result               | Status |
| -------------------------------------------- | ---------------------------------------------------------------------- | -------------------- | ------ |
| 全部 phase 31 测试                            | `pytest tests/delivery/test_release_*.py tests/services/test_feishu_bitable.py tests/delivery/test_bitable_release_adapter.py -q` | 24 passed in 12.73s  | ✓ PASS |
| migrations 一致                              | `manage.py makemigrations delivery --check --dry-run`                   | No changes detected  | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan      | Description                                                                   | Status      | Evidence                                                        |
| ----------- | ---------------- | ---------------------------------------------------------------------------- | ----------- | -------------------------------------------------------------- |
| REL-01      | 31-01 / 31-02    | Release 账本宽容模型 + raw_row 无损，adapter 演进不丢数据                       | ✓ SATISFIED | 三模型 + raw_row JSONField + ReleaseService 运行时兑现，测试锁定 |
| REL-02      | 31-03            | Bitable client/adapter 骨架 + 开放平台 token 独立解析 + natural key            | ✓ SATISFIED | BitableClient/adapter + create_bitable_client_for_project + natural key，测试锁定 |
| REL-03      | (deferred — v2)  | Bitable 真实列映射 + ReleaseRecord 粒度定型（需开放平台凭证 + 列样例）          | — DEFERRED  | REQUIREMENTS.md 明列为 v2/未来需求，非本 phase 范围（CONTEXT 范围守护） |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | 仅 `TODO(REL-03)` 占位标记，均引用正式后续工作（REL-03 需求 ID） | ℹ️ Info | TODO 关联 REL-03 v2 需求，符合 debt-marker gate 豁免（有正式 follow-up 引用）；非 blocker |

### Human Verification Required

#### 1. 真实开放平台凭证 + 真实 Bitable 端点正确性

**Test:** 用真实开放平台 app_id/app_secret 配置 Project / SystemSetting，对真实飞书 Bitable 表跑 `BitableReleaseAdapter.ingest_from_table`
**Expected:** tenant_access_token 成功获取（open.feishu.cn internal 端点），list_records 返回真实 items，ReleaseBatch/ReleaseRecord 落库且 raw_row 含真实原始行、bitable_record_key 正确
**Why human:** 需真实开放平台凭证 + 真实 Bitable 数据；pytest-socket 隔离网络，本 phase 仅 respx mock 验证端点形状（CONTEXT 明确延 human-UAT）

#### 2. REL-03 真实业务列映射语义正确性（v2 deferred）

**Test:** 对照真实 Bitable 列头/样例行，校验真实业务列 → ReleaseRecord 字段（status/note/work_item_external_id）映射正确性
**Expected:** 真实列结构映射后 ReleaseRecord 业务字段与 Bitable 列语义一致
**Why human:** REL-03 真实列映射 deferred 到 v2（需开放平台凭证 + 列样例）；本 phase 为占位映射骨架，真实语义需人工对照真实表确认

### Gaps Summary

无 gap。本 phase 作为**骨架 + 宽容模型**目标完整达成：14/14 must-have truths 经实际代码 + 24 个测试（全绿）验证；migration 干净；INV-6 收口 + 开放平台 token 与 plugin token 解耦均由测试锁定。

唯一未机器验证的部分（真实开放平台凭证下的端点正确性、REL-03 真实列映射语义）按 CONTEXT 明确范围属 deferred / human-UAT，已列入 Human Verification，**不计为 gap**（intentional skeleton）。因存在 human verification 项，状态判定为 `human_needed`（非 `passed`）。

---

_Verified: 2026-06-15T10:08:00Z_
_Verifier: Claude (gsd-verifier)_
