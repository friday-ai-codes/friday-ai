---
phase: quick-260806-sif
plan: 01
status: complete
completed: 2026-08-06
commits:
  - c6472382 refactor(web): 移除项目资料面板的交付物版本轨区块
  - 98cb93c9 feat(server): 新蓝图创建时 supersede 同项目旧活跃蓝图
  - 50a14a82 style(server): 格式化蓝图 intake supersede 新增用例
  - b46710a9 feat(server): 蓝图确认后回流 provided HTTP 契约到项目 API 清单
---

# Quick Task 260806-sif Summary — 项目页与技术方案职责收敛

## 完成内容

### Task 1 — 移除项目页「交付物版本轨」区块（c6472382）
- `ProjectMaterialsPanel.vue` 删除 `ArtifactTimeline` 导入与用法（版本链/下游引用属于蓝图内部演进，不再在项目页摊开）。
- `ProjectBlueprintsCard.vue` 头注的 P-17 条目重叠告警改写为历史备注（重叠随版本轨移除而消解）。
- `ArtifactTimeline.vue` 组件保留（知识库 blueprints 页仍在用）。eslint 通过。

### Task 2 — 新蓝图创建时 supersede 同项目旧活跃蓝图（98cb93c9 + 50a14a82）
- `blueprint_intake.py` 新增 `_asupersede_previous_blueprints`，挂在 `aseed_blueprint_artifact` 的 `_amark_researching` 之后（best-effort 双层兜底）。
- 项目匹配在 Python 侧读 `current_version.content.meta.project_id`（照 `blueprint_list_views._aggregate` 范式）；状态白名单只转 researching/drafting/pending_review/confirmed 四态（转移表仅这四态有 → superseded 合法边）。
- 转移一律经 `BlueprintLifecycleService.transition`（INV-6）；单条失败吞掉继续。ORM 过滤经 `_STATUS_FIELD` 常量拼 kwarg，INV-6 字段级守卫零豁免。
- 事件：`blueprint_supersede_previous_completed`（caller，superseded_count/skipped_count/duration_ms）；4 个新用例（可转/不可转/跨项目/失败不阻断）。

### Task 3 — 蓝图 confirmed 后回流 provided HTTP 契约到项目 API 清单（b46710a9）
- `BlueprintLifecycleService.transition` 在 CAS 成功且 `to_status == CONFIRMED` 后 best-effort 调 `_async_state_apis_on_confirm`。
- DB 重读 current_version content；只取 `direction=provided` + `kind=http` + method/path 非空的契约；写入经 `ProjectDocService.upsert_state_api`（status=planned、source=agent、description=契约 name、`defer_materialize=True` 批量 + 结束合并调度一次物化）。
- get_or_create 语义：已存在同 (method, path) 条目不覆盖（现状优先、重复确认幂等）。
- 事件：`blueprint_confirm_state_api_synced` / `blueprint_confirm_state_api_sync_failed`（error 经 `redact_secrets_in_text`）。新测试文件 4 个用例。

## 验证

- `uv run pytest tests/services/process_runtime/test_blueprint_intake.py tests/delivery/test_blueprint_confirm_state_api_sync.py tests/delivery/test_blueprint_review_threads.py tests/delivery/test_blueprint_inv6_guard.py tests/delivery/test_blueprint_log_redaction_guard.py -q` → **73 passed**（因另一会话并发跑测试争用 `test_friday`，改用独立测试库 `DATABASE_URL=...friday_sif` 验证后已清理）。
- eslint（两个 warroom 组件）通过；ruff format 对新增用例已格式化（blueprint_intake.py 的 I001 为既有问题，未触碰）。

## 执行备注

- 原执行 agent 被中断，orchestrator 接手完成（Task 1 的工作区改动为其遗留，已核对无误后提交）。
- `blueprint_lifecycle_service.py` 上另有一处**不属于本任务**的在途改动（archived → drafting 转移边，stage-runner 工作流）——Task 3 提交采用按 hunk 选择性暂存，该改动原样留在工作区未被卷入。
- 工作树其余大量在途脏文件（blueprint stage runner 等）全程未触碰；三个代码提交均为逐文件 add。
