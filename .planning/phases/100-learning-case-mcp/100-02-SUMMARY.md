---
phase: 100-learning-case-mcp
plan: 02
status: complete
date: 2026-07-15
---

# Phase 100 Plan 02: learning_case 入图（normalizer + 投递钩子 + 幂等重摄测试） Summary

**一句话**：`knowledge/sources/learning_case.py` 双事件 normalizer（work_item 锚 RELATES_TO + learning_case REFERENCES tech_plan，锚缺料降级单事件）+ `create_learning_case_from_technical_plan` 写库后经 `aschedule_ingestion` 投递（INV-6 唯一通路）+ 幂等重摄/版本翻转/边可见性自动化断言。

## What Was Built

### Task 1: knowledge/sources/learning_case.py normalizer

- `async def normalize(request) -> list[IngestionEvent]`，逐字沿用 `mcp_plan.py` 双事件锚模式：
  - **learning_case 主事件**：`kind=learning_case`、`origin=mcp`、`source_kind="learning_case"`、`source_id=str(case.id)`（100-01 natural key 规则表定版）；content 取 `embedding_text`（向量文本主料），为空回退 markdown 组装（`# title / ## 问题 / ## 根因 / ## 解法 / ## 结果` + repositories/files/tests 列表）；payload 摘要不复制全文（T-100-03）；`space_id` 取 `context.space_id` 优先、缺则 `technical_plan.space_id`；`repository_id=None`（案例跨仓）。
  - **REFERENCES 出边**：`technical_plan_id` 非空时挂 `EdgeSpec(REFERENCES, generate_entity_id("tech_plan", "mcp_technical_plan", ...))`——目标实体由 mcp_plan.py normalizer 负责入图，边阶段幂等，两端不齐仅 warning 不 raise。
  - **work_item 锚双事件**：锚料判定（context 非 None 且 feishu_project_key/work_item_type/work_item_id 三者齐备）→ `source_id` 三元组拼接（禁止自造锚格式）、轻量锚 content、锚出边 `EdgeSpec(RELATES_TO → learning_case)` **非 exclusive**（一个 work_item 可关联多条案例）；锚在前顺序约定。
  - 锚料缺失 → `knowledge_normalize_anchor_context_missing` warning + 单事件降级；源缺失 → `knowledge_normalize_source_missing` warning + `[]`。日志带 `component="knowledge"` / `category="sampling"`。

### Task 2: create_learning_case 投递钩子

- `server/mcp_tools/learning_case_service.py`：`McpLearningCase.objects.acreate(...)` 成功后、构造 output 之前投递 `IngestionRequest("learning_case", str(artifact.id), "mcp_learning_case_created")`；lazy import `knowledge.ingestion` 防循环（technical_plan_service.py L497 同款）；不传 `initiated_by_user_id`（MCP 链归因经 InteractionRun/ToolCallRecord 留痕，后台摄取记 system，与同域投递点口径一致）；`aschedule_ingestion` 内建 on_commit + 异常全吞，钩子处不再包 try/except（T-100-04）。
- 未动 `search_learning_cases`（100-04）/ payload 外形 / views.py。

### Task 3: 测试三组（server/tests/knowledge/test_learning_case_source.py）

- **TestNormalize**（4 用例）：锚料齐备双事件（三元组 source_id、RELATES_TO 非 exclusive、embedding_text 优先、REFERENCES 指向 tech_plan 派生 id）；embedding_text 为空 markdown 回退；`context=None` 单事件降级（space_id 回退 technical_plan、REFERENCES 不随锚缺席）；源缺失空列表 + warning。
- **TestTrigger**：monkeypatch `knowledge.ingestion.aschedule_ingestion` → 走 service 层 → 断言恰 1 条 `(learning_case, artifact.id, mcp_learning_case_created)`。
- **TestIdempotentReingest**：mock embedding/Qdrant 全链（`mock_embedding` fixture + ensure/upsert/tombstone/delete AsyncMock）；先摄 `mcp_technical_plan`（tech_plan + 共享 work_item 锚入图）再摄 learning_case → 实体恰 3（锚复用）；RELATES_TO / REFERENCES 活跃边（`invalid_at is None`）经 `KnowledgeEdge` 查询断言（criterion 1 边可见性）；第二次重摄实体/版本行数不变、`current_version == 1`（skipped 短路）、work_item 实体数不变（锚幂等）；修改 `embedding_text` 后第三次重摄 → `current_version == 2`、v2 `supersedes` v1、v1 `is_latest=False` 且 `invalid_at` 置位（ROADMAP 成功标准 4 前半）。

## Deviations from Plan

1. **[Rule 1 - Bug] event_time 改用 `case.updated_at`（plan 写的 `created_at` 会使版本翻转被 CHECK 约束拒绝）**
   - **Found during:** Task 3（TestIdempotentReingest 首跑失败）
   - **Issue:** `kversion_valid_range` CHECK 要求旧版本 `invalid_at > valid_at`；`created_at` 不随内容变更推进，重摄翻版时新 event_time == 旧 valid_at → IntegrityError（`knowledge_ingest_concurrent_conflict` 病理 skipped，版本永不翻转）。
   - **Fix:** 双事件 `event_time` 均取 `case.updated_at`（`coding_plan.py` 用 updated_at 同款先例），normalizer 内注释说明。
   - **Files modified:** `server/knowledge/sources/learning_case.py`
   - **Commit:** `bd854e58`
2. **[格式] `learning_case_service.py` 既有一行（L104 matrix 三元式）被 ruff format 一并格式化**：本 plan 触及文件按 ruff format 统一，diff 含 2 处与本次改动无关的既有格式修正（纯换行，无逻辑变化）。

## Verification Evidence

- Task 1/3 验证（新测试文件全量）：

  ```text
  ======================== 6 passed, 3 warnings in 23.47s ========================
  ```

- 整体验证（plan verification 组合）：

  ```text
  ======================= 8 passed, 12 warnings in 26.94s ========================
  ```

  （`tests/knowledge/test_learning_case_source.py` 6 用例 + `tests/mcp_tools/test_learning_cases.py` 既有 2 用例零回归。）

- `uv run ruff check` / `ruff format --check` 全部触及文件通过；无真实网络调用（pytest 全局 `--disable-socket` 未触发）。
- 并行纪律：未触碰 100-03 的文件（`views.py` / `work_item_execution_service.py` / `mcp_*.py` sources）；每次提交显式 `git add <paths>`。

## Commits

| Commit | 说明 |
| --- | --- |
| `bd854e58` | feat(knowledge): learning_case normalizer（work_item 锚双事件 + RELATES_TO/REFERENCES 边，100-02） |
| `04da3ac3` | feat(mcp_tools): create_learning_case 写库后经 aschedule_ingestion 投递摄取（KNOW-01，100-02） |
| `be7b0ea9` | test(knowledge): learning_case normalizer/触发投递/幂等重摄测试（100-02） |

## Known Stubs

无。存量案例回填（`backfill_learning_cases` 命令）与 `search_learning_cases` 读切换按 ROADMAP 归 100-04。

## Threat Flags

无新增安全面：T-100-03（content 只取 case 自身提炼字段，payload 摘要）/ T-100-04（投递 best-effort 不反噬主流程）/ T-100-05（锚格式唯一来源既有拼接，缺料降级不猜测）均按 threat model mitigate；零新依赖。

## Self-Check: PASSED

- `server/knowledge/sources/learning_case.py` — FOUND
- `server/mcp_tools/learning_case_service.py` aschedule_ingestion — FOUND
- `server/tests/knowledge/test_learning_case_source.py` — FOUND
- Commit `bd854e58` — FOUND
- Commit `04da3ac3` — FOUND
- Commit `be7b0ea9` — FOUND
