---
phase: 143-eval
plan: "05"
subsystem: knowledge
tags: [django, ingestion, session-capture, redaction, knowledge-graph]

requires:
  - phase: 143-01
    provides: session_capture 精华投影 RED 契约
  - phase: 143-03
    provides: Capture 价值档位、摄取状态与评估精华字段
provides:
  - medium/high SessionCapture 到统一 DOCUMENT/session_capture 的精华-only normalizer
  - 无锚 Capture 事件保留与授权项目 REFERENCES 边
  - session_capture 惰性 source 注册和稳定 uuid5 natural key 文档
affects: [143-06, 144, delivery_knowledge, session capture retrieval]

tech-stack:
  added: []
  patterns:
    - IngestionEvent 精华-only 投影
    - 可选项目锚 REFERENCES 边
    - sampling 生命周期日志 best-effort

key-files:
  created:
    - server/knowledge/sources/session_capture.py
  modified:
    - server/knowledge/sources/__init__.py
    - server/knowledge/models.py

key-decisions:
  - "仅 ingest_pending、ingesting、ingested 状态的 medium/high Capture 可产生知识事件。"
  - "标题和正文都只来自再次脱敏的 distilled_essence，不回退到 question 或 answer。"
  - "无 project/repository 的中高价值 Capture 仍产生无边事件，项目存在时才建立 REFERENCES。"

patterns-established:
  - "SessionCapture normalizer payload 仅允许 capture_id、value_tier、repository_id、project_id 标量。"
  - "source normalizer 不调用 Memory writer、后台调度器、Qdrant 或 KnowledgeEntity writer。"

requirements-completed: [EVAL-03, EVAL-05, OBS-04]

duration: 6min
completed: 2026-08-28
---

# Phase 143 Plan 05: SessionCapture 精华知识投影 Summary

**中高价值 SessionCapture 现可通过既有 ingestion 内核稳定投影为脱敏 DOCUMENT，仅携带标量来源信息，并保留无项目锚事件。**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-28T10:41:16Z
- **Completed:** 2026-08-28T10:47:16Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 实现 medium/high 且处于摄取阶段的 Capture 精华-only normalizer，low、缺失、未就绪或空精华返回空事件。
- 原始 question/answer 不进入 content、title 或 payload；精华在跨向量边界前再次脱敏。
- 无项目 Capture 仍形成可恢复事件；已有项目时确保项目节点并添加 `REFERENCES` 出边。
- 注册 `session_capture` source_kind，并记录不改变 uuid5 公式的稳定 natural key。

## Task Commits

1. **Task 1: 实现 medium/high 精华-only normalizer** - `02f892631` (feat)
2. **Task 2: 注册 source_kind 与稳定 natural key** - `edc6d7350` (feat)

**Plan metadata:** pending docs commit after this SUMMARY

_TDD RED 契约由 Phase 143 Plan 01 提交 `ad18d950` 提供，本计划完成 GREEN 实现。_

## Files Created/Modified

- `server/knowledge/sources/session_capture.py` - 精华-only DOCUMENT normalizer、可选项目边和 sampling 生命周期。
- `server/knowledge/sources/__init__.py` - 惰性登记 `session_capture` normalizer。
- `server/knowledge/models.py` - 补充 SessionCapture UUID natural key 文档。

## Decisions Made

- legacy `evaluated` 与 `evaluated_low` 都不进入向量投影；只有摄取状态允许 normalizer 产事件。
- 无锚事件的 `space_id=None`、`edges=()`，不因 Phase 144 尚未开放读侧白名单而静默丢弃。
- `event_time` 优先使用 `evaluated_at`，兼容缺失值时使用 `updated_at`。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 首次组合测试与并发 Plan 04 争用同名 PostgreSQL `test_friday`，27 个断言通过、3 个用例在建库阶段报连接占用；并发任务结束后使用 `--reuse-db` 串行复跑，30 项全部通过。

## Verification

- `uv run pytest tests/knowledge/test_session_capture_source.py -q --tb=short --reuse-db`：8 passed。
- ingestion 选择集：30 passed。
- `uv run ruff check knowledge/sources/session_capture.py knowledge/sources/__init__.py knowledge/models.py`：通过。
- 静态扫描确认 normalizer 不含 `aschedule_ingestion`、Memory writer、Qdrant 或 KnowledgeEntity 直接写入。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- durable ingest worker 可直接调用统一 `ingest(IngestionRequest("session_capture", ...))`。
- Phase 144 可在读侧白名单中开放无锚或仓库/项目维度的 SessionCapture 实体。

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
