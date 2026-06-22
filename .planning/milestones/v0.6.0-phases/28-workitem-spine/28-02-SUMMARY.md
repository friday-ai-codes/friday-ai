---
phase: 28-workitem-spine
plan: 02
subsystem: services
tags: [django, delivery, work-item, upsert, async, sync_to_async, idempotency, respx, tdd]

# Dependency graph
requires:
  - phase: 28-workitem-spine
    plan: 01
    provides: canonical WorkItem / WorkItemSyncState / WorkItemRelation / WorkItemStatusEvent 四模型 + 0001 migration
  - phase: 27-feishu-prefix-fixes
    provides: get_work_item（真实 type / 完整 feishu_fields）+ feishu_parsing 派生 helper（复用）
provides:
  - WorkItemService.upsert 单一写入入口（INV-6，DOMAIN §13.1 全步骤）
  - WorkItemIdentity（飞书三元组 frozen dataclass）
  - delivery.services.derivation 纯函数（derive_status_fields / derive_status_events）
  - delivery.signals.work_item_synced（best-effort 事件位）
affects: [28-03 webhook/manual 接线 + INV-6 grep 守护, 29 评论事件流, 30 Document/REFERENCES, 31 Release 账本, 32 一键摄取, 34 反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "async service：ORM 经 sync_to_async 桥接，select_for_update 放 transaction.atomic 同步块内"
    - "mirror-only 刷新：显式 update_fields 白名单，friday_enhanced/writeback 永不在内（结构性保护）"
    - "per-facet 独立 sync_to_async 调用 = 独立事务，天然实现部分 facet 失败不回滚整体"
    - "async DB 测试用 @pytest.mark.django_db(transaction=True) 隔离跨线程连接写入"
    - "复用 Phase 27 feishu_parsing 派生（derive_relations_from_fields/extract_prd_url/extract_tech_doc_url），不重写"

key-files:
  created:
    - server/delivery/services/derivation.py
    - server/delivery/services/work_item_service.py
    - server/delivery/signals.py
    - server/tests/delivery/test_work_item_service.py
  modified:
    - server/delivery/services/__init__.py

key-decisions:
  - "回源失败 / project 未配置 → basic_fields facet 记 missing+error，WorkItem 行（已 get_or_create）保留，不整体回滚（WIT-03，对齐 knowledge normalizer 降级范式）"
  - "关系目标解析按 (feishu_project_key, work_item_id=target_external_id) 匹配（不限 work_item_type），因容器型 type 未知；未命中走 target_external_id 占位、目标后续 upsert 反向回填"
  - "状态变更先 append WorkItemStatusEvent(pre/cur) 后改 mirror（含首次 ''→state）；无变更不重复 append（WIT-05）"
  - "prd_body/tech_doc/comments facet 本 phase 不摄取 → 记 missing，不假装 complete"
  - "async DB 测试改用 transaction=True：sync_to_async/async ORM 写入走独立连接，不被主连接事务回滚，标准 django_db 会跨测试泄漏 Project 唯一键"

requirements-completed: [WIT-01, WIT-02, WIT-03, WIT-04, WIT-05]

# Metrics
duration: ~25min
completed: 2026-06-15
---

# Phase 28 Plan 02: WorkItemService.upsert 单一写入入口 Summary

**实现 WorkItem 唯一写入入口 `WorkItemService.upsert`（INV-6，DOMAIN §13.1 全步骤）：三元组幂等收敛、mirror-only 刷新结构性保护 friday_enhanced、per-facet WorkItemSyncState 且回源失败不整体回滚、关系派生 + target_external_id 占位/回填、状态变更 append-only StatusEvent；复用 Phase 27 feishu_parsing 派生，18 个 service 守护测试全绿（respx mock 回源，零真实网络）。**

## Performance
- **Duration:** ~25 min
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- **Task 1 — 派生纯函数 + 信号：** `derive_status_fields`（state_key/sub_stage + 免映射人类名：current_nodes 优先 / state_times 回退 / archived/init 容错降级）、`derive_status_events`（history[] 归一），皆纯函数缺字段降级不抛；`delivery.signals.work_item_synced` best-effort 事件位。
- **Task 2 — upsert 核心：** `WorkItemIdentity`(frozen) + `WorkItemService.upsert`，落 §13.1 步骤 1/2/3/6——`select_for_update` 三元组幂等收敛（origin 仅首次落，WIT-01）、显式 update_fields 白名单刷 mirror 结构性保护 enhanced/writeback（WIT-02）、回源失败/project 未配置 basic_fields facet 记 missing+error 不回滚（WIT-03）、成功写 last_synced_at + field_provenance + basic_fields=complete、best-effort 发信号。
- **Task 3 — 关系/状态：** `derive_relations_from_fields` → `WorkItemRelation.update_or_create`（unique_together 幂等），target 未落库占位 `target_external_id`、后续 upsert 反向回填 `target_work_item`（WIT-04）；状态变更先 append `WorkItemStatusEvent(pre/cur)` 后改 mirror、无变更不重复（WIT-05）；history[] 去重回填；relations facet 派生成功 complete、异常仅记 relations error 不掀翻 WorkItem。

## Task Commits
1. **Task 1: 派生纯函数 derivation.py + work_item.synced 信号** - `ff1dcd52` (feat)
2. **Task 2: WorkItemService.upsert 核心 — 幂等收敛 + mirror-only + facet SyncState** - `2bd11b23` (feat)
3. **Task 3: 关系派生持久化（占位/回填）+ 状态事件 append + relations facet** - `5c9b97e0` (feat)

## Files Created/Modified
- `server/delivery/services/derivation.py` - `derive_status_fields` / `derive_status_events`（纯函数，容错降级）
- `server/delivery/services/work_item_service.py` - `WorkItemIdentity` + `WorkItemService.upsert`（单一写入入口）
- `server/delivery/signals.py` - `work_item_synced = Signal()`
- `server/delivery/services/__init__.py` - re-export `WorkItemService` / `WorkItemIdentity`
- `server/tests/delivery/test_work_item_service.py` - 18 守护测试（8 纯函数 + 10 upsert，respx mock 回源）

## Decisions Made
- **关系目标匹配键**：按 `(feishu_project_key, work_item_id)` 而非加 `work_item_type`——容器型工作项真实 type 未知（DOMAIN §specifics），work_item_id 在 project 内唯一即可定位；未命中占位。
- **事务粒度**：`_get_or_create_locked` / `_refresh_mirror` / `_apply_relations` / 各 `_record_sync_state` 分别经 `sync_to_async` 包裹，自然形成独立事务边界——后续 facet 失败不回滚已落库的 WorkItem（§1.4 失败策略落地方式）。
- **测试隔离**：async ORM / `sync_to_async` 写入走独立连接，标准 `django_db` 主连接事务回滚不清理 → 跨测试 `Project.feishu_project_key` 唯一键冲突；改用 `django_db(transaction=True)`（与既有 `tests/workflows/test_trigger_sync.py` 同范式）。

## Deviations from Plan
None - plan executed exactly as written. 三个 task 严格按 §13.1 步骤落地；派生全程复用 Phase 27 `feishu_parsing`（仅新增 delivery 侧 `derive_status_fields`/`derive_status_events`，非 Phase 27 覆盖范围）。

## Known Stubs
- prd_body / tech_doc / comments facet 本 phase **有意**记 `missing`（不假装 complete）——正文摄取归 Phase 30（文档）、Phase 29（评论）。已在 CONTEXT Grey Area 4 锁定，非未完成项。
- `WorkItemService.upsert` 的真实调用方（REST manual by-ID 端点 / feishu webhook 接线 + INV-6 grep 守护）归 Plan 28-03；本 plan 仅产出 service + 纯函数 + 信号 + 守护测试（plan objective 明确）。

## Issues Encountered
- async DB 测试初见 `Project.feishu_project_key` 唯一约束跨测试冲突（async 写入逃逸主连接事务回滚）——经 `django_db(transaction=True)` 解决。
- 回填测试中 source 与 target 同 `type=story` 共用同一 query URL，respx 第二次 `.mock` 覆盖第一次——改用 `side_effect` 按请求 `work_item_ids` 分发响应。

## Verification Results
- `uv run pytest tests/delivery/test_work_item_service.py -q` → **18 passed**（8 纯函数 + 10 upsert）。
- `uv run pytest tests/delivery/ -q` → **25 passed**（含 28-01 模型层 7）。
- `uv run ruff format --check delivery/services/ delivery/signals.py tests/delivery/test_work_item_service.py` → all formatted；`ruff check delivery/ tests/delivery/` → All checks passed。
- 全程 respx mock 回源，pytest-socket 隔离零真实网络；未改 knowledge app（INV-3）；未新增第三方依赖。
- 预存在的 `tests/knowledge/test_triggers.py` 失败与本 plan 无关，按指示忽略。

## Threat Surface
计划 `<threat_model>` 全部 mitigate 落地：
- **T-28-04（Tampering）**：mirror 刷新仅 `_MIRROR_FIELDS` 显式 update_fields 白名单，friday_enhanced/writeback 结构性不在集合内（WIT-02 测试守护）。
- **T-28-05（DoS）**：`get_work_item` try/except + 各 facet 独立事务，回源失败落 SyncState.error 不整体回滚、缺料降配继续（WIT-03 测试守护）。
- **T-28-06（Repudiation）**：状态变更 append-only StatusEvent，先 append 后改 mirror（WIT-05 测试守护）。
- **T-28-07（Information Disclosure）**：`_safe_error` 截断 500 字符、复用 feishu 既有脱敏（body 截断、凭证不入日志/error）；WIT-03 测试断言 error 不含 token/secret。

未引入计划外安全敏感面（无新端点 / 新 schema / 新外部 IO）。

## Next Phase Readiness
- 单一写入入口就位，Plan 28-03 可在 manual by-ID REST 端点 + feishu webhook handler 中调 `WorkItemService.upsert`，并加 INV-6 grep 守护断言（无旁路 WorkItem.save/create）。
- 下游 phase（29/30/31/34）可在 upsert 落库的 canonical WorkItem 上扩 facet（comments/prd_body/tech_doc）与反查。

## Self-Check: PASSED
- 文件：`derivation.py` / `work_item_service.py` / `signals.py` / `services/__init__.py` / `test_work_item_service.py` 均 FOUND。
- 提交：`ff1dcd52` / `2bd11b23` / `5c9b97e0` 均存在于 git log。
- 测试：delivery 套件 25 passed；ruff format/check 全绿。

---
*Phase: 28-workitem-spine*
*Completed: 2026-06-15*
