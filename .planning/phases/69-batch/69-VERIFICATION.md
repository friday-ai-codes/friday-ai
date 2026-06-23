---
phase: 69
slug: batch
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 69 — Verification（批量加仓 + 全部更新索引）

## Goal-Backward Verification

**Phase Goal:** 支持经 CSV 批量导入数百仓库，并给超管一键「全部更新索引」，批量入队受 Phase 67 并发上限排队消费、不打爆资源。

## Checks

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | 超管在仓库列表页可见并点击「全部更新索引」批量入队全部未删除仓库（普通用户不可见/不可调用，IsSuperUser fail-closed） | ✅ | `ReindexAllView` `IsSuperUser`；前端按钮 `v-if="isAdmin"`；`test_reindex_all_forbidden_for_normal_user`(403) + `test_reindex_all_queues_non_deleted_repos` |
| 2 | 批量入队数百仓库受 CONCURRENCY_INDEX_MAX 排队消费，不一次性打爆 | ✅ | 复用 `_schedule_index`（Phase 67 索引槽位锁 lock=index-slot-{N}），超限原生 todo 排队；不另设限流 |
| 3 | 提供批量建仓能力（接受数组的批量接口），支持 CSV 导入数百仓库 | ✅ | `RepositoryBatchCreateView` 数组接口（上限 500）复用 `_acreate_repository_core`；前端 CSV 解析 → batchCreate；`test_batch_create_creates_multiple_repos` + 单项隔离 |
| 4 | 触发后前端给出「已排队 N 个」反馈 | ✅ | 列表页 `handleReindexAll` 成功 toast `已排队 N 个（跳过 M 个）`；CSV 导入 toast 成功/失败计数 |

## Result

**PASSED** — 4/4 success criteria 满足。后端 5 守护 + acreate 重构 31 测零回归；前端 eslint clean。真实数百仓库 CSV 导入与超管全量重索引端到端需真实环境人工验收（deferred，代码层 must-haves 全过）。
