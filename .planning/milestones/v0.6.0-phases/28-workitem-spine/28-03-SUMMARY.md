---
phase: 28-workitem-spine
plan: 03
subsystem: api
tags: [django, adrf, delivery, work-item, rest, webhook, background-upsert, inv-guard, respx]

# Dependency graph
requires:
  - phase: 28-workitem-spine
    plan: 02
    provides: WorkItemService.upsert 单一写入入口 + WorkItemIdentity（INV-6 落库点）
  - phase: 28-workitem-spine
    plan: 01
    provides: canonical WorkItem / SyncState / Relation / StatusEvent 四模型
provides:
  - delivery 最小 REST（手动 upsert + 读取 WorkItem，adrf APIView，IsAuthenticated）
  - 飞书 webhook 工作项事件后台接线 WorkItemService.upsert(source=feishu_webhook)
  - INV-6 旁路写表 grep 守护测试（精确锚定，零误伤）
  - INV-3 投影保留守护（knowledge ingestion 不动 + delivery 不写 knowledge 模型）
  - 跨入口收敛集成测试（manual / feishu_webhook → 唯一 canonical，WIT-01）
affects: [29 评论事件流, 30 Document/REFERENCES, 31 Release 账本, 32 一键摄取, 34 反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "adrf APIView async post/get + IsAuthenticated；序列化反向查询经 sync_to_async(lambda: serializer.data)"
    - "webhook 只投三元组、正文后台拉：handler 紧随 aschedule_ingestion 后 run_in_background 调 upsert"
    - "INV-6 grep 守护：精确锚定 WorkItem.objects.<write> / WorkItem( 实例化，紧跟字符天然排除 WorkItemService( 等长符号"
    - "API/接线测试 transaction=True（async ORM 写走独立连接，与 28-02 同范式）"

key-files:
  created:
    - server/delivery/api/__init__.py
    - server/delivery/api/serializers.py
    - server/delivery/api/views.py
    - server/delivery/urls.py
    - server/tests/delivery/test_api.py
    - server/tests/delivery/test_entry_wiring.py
    - server/tests/delivery/test_inv6_guard.py
  modified:
    - server/friday/urls.py
    - server/feishu/views.py

key-decisions:
  - "REST upsert 恒返回 200（upsert 不回传 created 标记）；回源失败 fail-soft 仍返回当前行 + facet 完整度（不 500）"
  - "delivery upsert 投递经 FeishuWebhookView._schedule_delivery_upsert 复用方法，三 handler 统一接线；缺 work_item_id/type 跳过 + warning"
  - "INV-6 守护匹配写形态（.objects.create/get_or_create/update_or_create/bulk_create + WorkItem( 实例化 + WorkItem(...).save()），不用裸子串；排除 tests/migrations/models/service 自身"
  - "INV-3：feishu webhook 既有 knowledge ingestion 完全保留不动，delivery upsert 仅 ADD 在其后并存"

requirements-completed: [WIT-01, WIT-02]

# Metrics
duration: ~20min
completed: 2026-06-15
---

# Phase 28 Plan 03: REST + webhook 接线 + 不变量守护 Summary

**把 28-02 的 `WorkItemService.upsert` 接到两条真实入口：① 最小 delivery REST（手动按三元组 upsert + 读取 WorkItem，adrf APIView，`IsAuthenticated`，写端点经单一 upsert 无旁路 ORM 写）；② 飞书 webhook 三个工作项 handler 紧随既有 knowledge ingestion 后经 `run_in_background` 后台调 `upsert(source="feishu_webhook")`（保留投影，INV-3）。补 INV-6 旁路写表 grep 守护（精确锚定零误伤）、INV-3 投影保留守护、跨入口收敛集成测试；delivery 全套 38 passed、webhook 回归全绿。**

## Performance
- **Duration:** ~20 min
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files modified:** 9（7 created + 2 modified）

## Accomplishments
- **Task 1 — 最小 REST：** `WorkItemUpsertView.post`（校验三元组 → `await WorkItemService().upsert(source="manual")` → 序列化经 `sync_to_async`）+ `WorkItemDetailView.get`（按三元组 query params 只读已落库，不旁路 fetch，404 语义）；`WorkItemSerializer`（只读全字段 + 嵌套 `sync_states` per-facet 完整度概要）、`WorkItemUpsertRequestSerializer`（三元组必填、`work_item_id` 正整数 `min_value=1`）；`delivery/urls.py` 字面段 + `friday/urls.py` 挂载 `delivery/`。
- **Task 2 — webhook 接线：** `FeishuWebhookView._schedule_delivery_upsert`（lazy import delivery + background_runner 防循环；缺三元组跳过 + warning；`run_in_background` best-effort 脱离请求生命周期）；create/status/update 三 handler 在既有 `aschedule_ingestion` 之后接线（INV-3 保留投影）。跨入口收敛测试断言 manual / feishu_webhook 同三元组 → 唯一 canonical、origin 仅首次落（WIT-01）。
- **Task 3 — 不变量守护：** `test_inv6_guard.py` 纯源码扫描——INV-6 断言除 `delivery/services/work_item_service.py` 外无旁路 `WorkItem.objects.<write>`/实例化/`.save` 写表（精确锚定，命中报 文件:行），并断言唯一 writer 确含写表（守护有效性自证）；INV-3 断言 `feishu/views.py` 仍含 `aschedule_ingestion` 且 delivery app 不 import/写 knowledge 模型。

## Task Commits
1. **Task 1: 最小 delivery REST（手动 upsert + 读取）+ 路由挂接** - `6b72502d` (feat)
2. **Task 2: 飞书 webhook 接线后台 delivery upsert（保留 knowledge 投影）** - `a01b80fb` (feat)
3. **Task 3: INV-6 旁路写表 grep 守护 + INV-3 投影保留守护** - `c2976d00` (test)

## Files Created/Modified
- `server/delivery/api/__init__.py` - api 包标记
- `server/delivery/api/serializers.py` - `WorkItemSerializer`（read + 嵌套 sync_states）/ `WorkItemSyncStateSerializer` / `WorkItemUpsertRequestSerializer`（三元组校验）
- `server/delivery/api/views.py` - `WorkItemUpsertView` / `WorkItemDetailView`（adrf，IsAuthenticated，经单一 upsert）
- `server/delivery/urls.py` - `work-items/upsert/`、`work-items/` 字面段路由
- `server/friday/urls.py` - `api_patterns` 追加 `path("delivery/", include("delivery.urls"))`
- `server/feishu/views.py` - `_schedule_delivery_upsert` + create/status/update 三 handler 接线
- `server/tests/delivery/test_api.py` - 6 REST 测试（upsert/read/401/404/400）
- `server/tests/delivery/test_entry_wiring.py` - 3 接线测试（跨入口收敛 + handler 接线 + 不全跳过）
- `server/tests/delivery/test_inv6_guard.py` - 4 守护测试（INV-6 ×2 + INV-3 ×2）

## Decisions Made
- **REST 返回码**：upsert 恒 200（不回传 created 标记）；回源失败 fail-soft（28-02 已落 SyncState.error）仍返回当前 WorkItem + facet 完整度，不 500。
- **接线方法复用**：三 handler 抽出 `_schedule_delivery_upsert` 统一投递；webhook 主响应不 await upsert（best-effort 后台）。
- **INV-6 锚定精度**（plan-checker WARNING 落地）：匹配 `\bWorkItem\.objects\.(create|bulk_create|get_or_create|update_or_create)` + `\bWorkItem\s*\(` 实例化 + `WorkItem(...)\.save(`；`\s*\(` 紧跟天然排除 `WorkItemService(`/`WorkItemRelation(`/`WorkItemSyncState(`/`WorkItemStatusEvent(`/`WorkItemSerializer(`/`WorkItemIdentity(`，并跳过 `class WorkItem` 行；扫描排除 tests/ / migrations/ / delivery/models/ 与 service 自身——零误伤。
- **测试隔离**：触 DB 的 API / 收敛测试用 `transaction=True`（async ORM 写走独立连接，与 28-02 同范式）；handler 接线测试用 `SimpleNamespace` project + mock，不触 DB/网络。

## Deviations from Plan
None - plan executed exactly as written. 三 task 严格按 artifacts_produced 落地：REST 经单一 upsert（INV-6）、webhook ADD 在 ingestion 之后（INV-3 保留）、守护测试精确锚定。

## Known Stubs
None — 本 plan 仅接线既有 upsert + 加守护，无新增占位逻辑。`bitable_import`/`mr_reverse` 真实调用方按 CONTEXT 仍归 Phase 31/32（枚举与 upsert 入参 28-01/02 已就位），非本 plan 范围。

## Issues Encountered
- 工具环境波动：`uv run pytest` 偶发解析到 pyenv 3.12.4 / rootdir 漂移至 repo 根，导致 e2e fixtures 插件 import 失败；显式设置 working_directory 至 `server/` 后稳定使用项目 .venv（3.14.2 / pytest 9.0.2），全程绿。
- `tests/knowledge/test_triggers.py::TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once` 预存在失败（PR-created 分支投递，与本 plan webhook/delivery 接线无关），按 plan 指示忽略；同文件其余 43 passed。

## Verification Results
- `uv run pytest tests/delivery/ -q` → **38 passed**（test_models 7 + test_work_item_service 18 + test_api 6 + test_entry_wiring 3 + test_inv6_guard 4）。
- `uv run pytest tests/test_webhooks.py -q` → **8 passed, 1 xfailed**（webhook 接线未破坏既有触发/ingestion）。
- `uv run pytest tests/knowledge/test_triggers.py -q` → 43 passed, 1 failed（预存在、无关，已说明）。
- `uv run ruff format --check delivery/ tests/delivery/ feishu/views.py friday/urls.py` → 25 files already formatted；`ruff check` All checks passed。
- 全程 respx mock 回源 + pytest-socket 隔离零真实网络；未改 knowledge app（INV-3）；未新增第三方依赖。

## Threat Surface
计划 `<threat_model>` 全部 mitigate 落地：
- **T-28-08（EoP）**：delivery REST 两端点 `permission_classes=[IsAuthenticated]`；只读端点不旁路 fetch、写端点经单一 upsert（无直接 ORM 写）。未认证 → 401/403（测试守护）。
- **T-28-09（Tampering）**：INV-6 grep 守护测试断言 WorkItem 落库仅经 WorkItemService，旁路 `.objects.create`/`.save`/实例化即 fail（测试守护）。
- **T-28-10（Spoofing）**：复用既有 webhook token 校验（FeishuWebhookView）；delivery upsert 只取三元组、业务字段经 plugin token 后台权威回源，不信任 payload 值。
- **T-28-11（DoS）**：webhook 后台 upsert 经 `run_in_background` 脱离请求生命周期，主响应不阻塞；upsert 内部 fail-soft（28-02）。

未引入计划外安全敏感面（端点均 IsAuthenticated；无新 schema；webhook 回源 IO 沿用既有 client）。

## Next Phase Readiness
- 两条真实入口（manual REST / feishu webhook）已收敛到单一 upsert，INV-6/INV-3 守护就位。
- 下游 phase（29 评论 / 30 文档 / 31 Release / 34 反查）可在 canonical WorkItem 上扩 facet / 反查；REST 读端点已暴露 sync_states 完整度供前台呈现。

## Self-Check: PASSED
- 文件：`api/__init__.py` / `api/serializers.py` / `api/views.py` / `urls.py` / `test_api.py` / `test_entry_wiring.py` / `test_inv6_guard.py` 均 FOUND；`friday/urls.py` / `feishu/views.py` 已修改。
- 提交：`6b72502d` / `a01b80fb` / `c2976d00` 均存在于 git log。
- 测试：delivery 套件 38 passed；webhook 回归 8 passed/1 xfailed；ruff format/check 全绿。

---
*Phase: 28-workitem-spine*
*Completed: 2026-06-15*
