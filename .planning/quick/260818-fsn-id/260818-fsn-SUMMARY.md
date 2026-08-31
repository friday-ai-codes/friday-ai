---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# 260818-fsn — 蓝图确认门补调研刷新 + 仓库调研过程明细按仓分组直播

## 背景 / 问题

1. **确认门不刷新**：`repo_confirmation` 门已打开后若发生重调研，旧实现的 `open_gate` 直接短路、不重算快照；`blueprint_resume` 在「无待调研仓 + 门恒 open」的稳态下 advance 为 0——调研终态（failed→done）后没有任何路径再刷 `BlueprintThread.options`，用户在确认门看到的 `task_status` 永远停在陈旧的 `failed`。
2. **过程明细不可读**：`blueprint.repo_research.started` 串行展示，标题机械、暴露 `routed_confidence`/`repository_id`/`task_id`，且无法按仓看进度。

## 改动

### Task 1 — 确认门幂等刷新（后端）

- `blueprint_confirm_gate.py`：新增 `arefresh_open_gate_snapshot`（行锁读改写、幂等、保留人工裁决面）；`open_gate` 的「pending 短路」分支改为 refresh 后返回，快照随最新 `PartialPlan` 重算。
- `blueprint_resume.py`：短路前接线，触发确认门快照刷新。
- 新增 management command `repair_blueprint_confirm_gate`：按 `artifact-id` 定位 technical_blueprint 会话 + 打开的门 → 幂等刷新；`--dry-run` 只定位不写；结构化日志 `blueprint_confirm_gate_repair_*`（category=caller, component=process_runtime, initiated_by_user_id=system）。

### Task 2 — 轻量直播进度端点（后端）

- `GET .../blueprint/research-progress/`：cursor/tail（`after_log_id` 全局游标、`limit` clamp ≤50），按仓返回 `repository_id/name/task_status/run_status/latest_observable/log_cursor/recent_logs`；复用 `_log_row`/`_is_noise`/`redact_secrets_in_text` 脱敏，⛔ 不返回 transcript/CoT。避免 5s 全量 400-log 轮询。

### Task 3 — 过程明细文案/隐藏字段/按仓分组 + 直播接线（前端）

- `blueprintActivity.ts`：`NORMAL_UI_HIDDEN_PAYLOAD_KEYS`（`routed_confidence`/`repository_id`/`task_id`）从普通字段行隐去、raw JSON 折叠层仍保留；新增 `groupRepoResearchEvents` 按仓折卡（completed⇒done、failed 且其后无 completed⇒failed、否则 running）。
- `BlueprintStageStepper.vue`：`repo_research` 节点详情改为**按仓卡片**（仓名 + 状态徽标 + 调研理由 + 直播尾窗/占位 + 每仓「查看该仓明细」入口），其余节点仍走扁平事件列表。
- `useBlueprintLive.ts`：researching/live 时轮询 `research-progress`（非 research-detail），`refetchInterval` 单点约束不破；drawer 仍按需拉全量 detail。
- `zh-CN.json`：started → `调研 {repository_name} 仓库`，新增 researchState*/researchViewDetail/researchNoLive/researchReason/research.entry 文案。

## 验证

- 后端：`test_blueprint_confirm_gate.py` 35 passed、`test_blueprint_process_graph.py` 47 passed、`test_blueprint_doc_views.py` 74 passed。
- 前端：`blueprintActivity.spec.ts` / `stageStepper.spec.ts` / `useBlueprintLive.spec.ts` 共 48 passed。
- 存量修复：`python manage.py repair_blueprint_confirm_gate --artifact-id=7409c0d0-7fde-4bcf-8857-29e437610fc7` → `refreshed=True changed=5`，确认门快照不再残留旧 `failed`。

## 备注

- 工作树含其它相位（append-only charter 等）无关改动，本任务只动计划列出的文件，未 git commit。
- 观测均 best-effort、脱敏、system 归因。
