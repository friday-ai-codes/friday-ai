---
phase: 14-triggers
plan: 05
subsystem: knowledge
tags: [ingest-04, feishu-trigger, work-item-snapshot, normalizer, webhook]
requires:
  - 14-01 sources 注册表 feishu_work_item 登记（落地前 ImportError 响亮失败）
  - 13-02 统一摄取管线（IngestionRequest / IngestionEvent / aschedule_ingestion）
  - 13-03 接线铁律（lazy import + 属性调用 + 异常全吞 + 只投 ID）+ work_item 锚三元组 source_id 契约
provides:
  - sources/feishu_work_item.py normalizer（三元组 → 全量快照单事件，取材全在后台）
  - feishu/views.py 三 handler（create/status/update）尾部接线投递 feishu_workitem_<event>
  - 13-03 轻量锚同 natural key 重摄升级为全量快照版本（版本翻转，预埋设计闭环）
affects:
  - Phase 15 检索（feishu 来源 work_item 全量快照入图，需求侧时间线素材齐备）
tech-stack:
  added: []
  patterns:
    - 文档拉取失败降级为不含正文段的快照 + warning（缺段不缺事件，13 范式延伸）
    - event_time 毫秒时间戳 → aware UTC + timezone.now() 兜底（Pitfall 6）
key-files:
  created:
    - server/knowledge/sources/feishu_work_item.py
  modified:
    - server/feishu/views.py
    - server/tests/knowledge/test_triggers.py
decisions:
  - description 已单独渲染进正文，自定义字段表里跳过 description 键（避免 rich text 原文重复）
  - event_time 时间字段候选序 updated_at → update_time → updated_time → created_at（首个可解析毫秒值）
  - _handle_workitem_update 补 work_item_type 局部变量（payload.get("work_item_type_key", "story")，与 create/status 取法一致）
  - doc client 构造失败（双文档同时不可用）单独 warning（knowledge_normalize_doc_client_unavailable），单文档失败各自 warning（knowledge_normalize_doc_fetch_failed）
metrics:
  duration: ~12min
  tasks: 2
  files: 3
completed: 2026-06-12
---

# Phase 14 Plan 05: 飞书三触发点接入（INGEST-04）Summary

飞书工作项创建/状态变更/字段更新三事件接入统一摄取管线：feishu_work_item normalizer 后台拉取全量快照（名称/描述/自定义字段/PRD 与技术方案文档正文/关联工作项，## 分段契合 chunker），webhook 路径只投三元组 ID 零取材，13-03 轻量锚同 key 重摄即升级为全量快照版本。

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | feishu_work_item 全量快照 normalizer + TestFeishuWorkItemNormalizer（fake 客户端） | e14ed4e5 (test) / 583b581b (feat) | knowledge/sources/feishu_work_item.py, tests/knowledge/test_triggers.py |
| 2 | feishu/views.py 三 handler 接线 + TestFeishuTriggers | 25af7c35 (test) / ba006453 (feat) | feishu/views.py, tests/knowledge/test_triggers.py |

## 交付物对照（must_haves）

- ✅ 三事件各投递一次且只投 ID：`("feishu_work_item", f"{project_key}:{type}:{id}", "feishu_workitem_create/status/update")`，缺 ID 早退零投递，接线处零 try/except 零取材（test_feishu_three_handlers_each_deliver_once / test_feishu_missing_id_zero_delivery）
- ✅ normalizer 全量快照：content 含名称、描述、`## 自定义字段`、`## PRD`、`## 技术方案`、`## 关联工作项` 各段，payload 含 status/work_item_type，project_id 非空（test_feishu_full_snapshot_single_event）
- ✅ 同 natural key 重摄升级：13-03 轻量锚先入图 → 全量快照重摄 → 同实体 v2（实体数不变、supersedes 版本链，test_feishu_same_key_reingest_upgrades_anchor_to_v2）
- ✅ event_time 恒 aware：毫秒时间戳 → 对应 UTC；字段缺失 → timezone.now() 兜底，双场景 tzinfo 断言（test_feishu_event_time_always_aware，Pitfall 6）
- ✅ 文档拉取失败降级：快照不含正文段 + warning 不 raise（test_feishu_doc_fetch_failure_degrades_to_snapshot_without_body）；run_in_background 抛错时三 handler 宿主流程仍成功（test_feishu_handlers_survive_runner_failure）

## Deviations from Plan

**1. [Rule 2 - Missing critical] _handle_workitem_update 补 work_item_type 局部变量**
- **Found during:** Task 2
- **Issue:** plan 假定三 handler 均有 `work_item_type` 局部变量，但 `_handle_workitem_update` 实际只有 `work_item_id` 与 `changed_fields`——缺它三元组拼不出来
- **Fix:** 按 create/status 同款取法补 `work_item_type = payload.get("work_item_type_key", "story")`（仍属 payload 字段读取，非取材）
- **Commit:** ba006453

**2. [Scope boundary] `ruff check feishu/` 全目录验证降级为只验改动文件**
- **Found during:** 整体 verification
- **Issue:** `feishu/bot/service.py` 存在既有 I001（最后改动为 open source release 提交，与本 plan 无关）
- **Fix:** 不修；登记 `deferred-items.md`；本 plan 改动文件（views.py / feishu_work_item.py / test_triggers.py）ruff check + format 全部通过

其余按计划逐字执行。

## 验收锚点（acceptance_criteria 自查）

- `rg "os.environ|FRIDAY_" knowledge/sources/feishu_work_item.py` 零命中（凭证只经 create_feishu_client_for_project / create_feishu_doc_client_for_project service 层）✅
- `rg -c "aschedule_ingestion" feishu/views.py` == 3（三 handler 各一，lazy import 形态不增计数）✅
- `rg "from knowledge.ingestion import" feishu/views.py` 零命中 ✅
- 接线三处零 try/except、零 get_work_item/文档调用（人工复核三处插入块：仅 f-string 拼 ID）✅
- Test 2 断言实体数不变（acount()==1）且 current_version==2 + supersedes 链（锚升级语义可证）✅
- Test 4 双场景 `event_time.tzinfo is not None`（require_aware 防线不触发）✅
- 全部外部调用各有独立降级路径：get_work_item 失败 → 空列表（Test 5 场景 2）；relations 失败 → 空关联列表事件照常（代码 try/except + warning）；单文档失败 → 缺段不缺事件（Test 3）✅

## Verification

- `uv run pytest tests/knowledge/ tests/feishu/ -x` → 192 passed, 1 deselected（既有零回归 + 本 plan 新增 8 用例；含 feishu 宿主套件）
- `uv run ruff check knowledge/sources/feishu_work_item.py feishu/views.py tests/knowledge/` + `ruff format --check` → 全部通过（feishu/bot/service.py 既有问题见 deferred-items.md）

## Known Stubs

None — normalizer 与三处接线全部数据通路已接通；14-01 注册表 `feishu_work_item` 行自本 plan 起指向真实模块（Phase 14 三 normalizer 全部落地）。

## Threat Flags

None — 未引入计划 threat_model 之外的新攻击面（T-14-17~21 缓解全部在测试断言内：接线位于 token 校验后的 handler、缺 ID 早退、零取材、project_id 恒带、event_time aware）。

## Self-Check: PASSED

- FOUND: server/knowledge/sources/feishu_work_item.py
- FOUND: server/tests/knowledge/test_triggers.py（TestFeishuWorkItemNormalizer + TestFeishuTriggers）
- FOUND: commit e14ed4e5 / 583b581b / 25af7c35 / ba006453
- tests green（tests/knowledge + tests/feishu → 192 passed）
