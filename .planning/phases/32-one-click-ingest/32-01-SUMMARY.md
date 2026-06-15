---
phase: 32-one-click-ingest
plan: 01
subsystem: delivery
tags: [ingest, model, url-parsing, migration]
requires:
  - delivery.models（curated re-export 约定）
  - services.git_platform（extract_gitlab_url / extract_project_path / extract_github_owner_repo）
  - repositories.models.Repository / GitPlatform
  - delivery.services.work_item_service.WorkItemIdentity
provides:
  - delivery.models.IngestRun（+ default_steps）
  - delivery.services.ingest_parsing（parse_board_url / parse_mr_url / aresolve_repo_and_mr / BoardRef / MRRef）
  - delivery/migrations/0008_ingestrun.py
affects:
  - 32-02（编排：写 IngestRun + 消费解析 helper）
  - 32-03（前端：经 REST 状态端点轮询 IngestRun）
tech-stack:
  added: []
  patterns:
    - CleanupRun run-state 范式（UUID pk + Status TextChoices + JSONField + (-started_at) 索引）
    - 可调用 JSONField default（default_steps）避免可变默认共享
    - 复用 git_platform git URL 解析 helper（禁自写）
key-files:
  created:
    - server/delivery/models/ingest_run.py
    - server/delivery/services/ingest_parsing.py
    - server/delivery/migrations/0008_ingestrun.py
    - server/tests/delivery/test_ingest_parsing.py
    - server/tests/delivery/test_ingest_run_model.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/__init__.py
decisions:
  - "IngestRun.Status 仅 running/completed/failed（与 32-UI-SPEC RunStatus 严格对齐，无 none）"
  - "steps 固定形状 {work_item, document, mr_diff}，每步 {status, identifier, link, error}"
  - "parse_board_url 仅匹配标准 .../detail/{数字 id} 形态；容器型 URL 段不可靠 → None（PF-09）"
  - "aresolve_repo_and_mr 强制匹配已落库 Repository 才放行（T-32-01 SSRF 边界）"
metrics:
  duration: ~25m
  completed: 2026-06-15
---

# Phase 32 Plan 01: IngestRun 模型 + URL 解析 Summary

为一键摄取编排打地基：新增 `IngestRun` 持久化模型（承载工作项/文档/MR diff 三步结构化结果 + run 状态）与看板/MR URL 解析 helper（看板 URL → 飞书三元组身份；MR URL → 已落库 Repository + mr_iid，复用既有 git platform 解析 helper），均经 curated re-export 暴露供 32-02 编排消费。

## What Was Built

### Task 1 — IngestRun 模型 + 迁移（commit `1014f075`）
- `server/delivery/models/ingest_run.py`：`IngestRun(models.Model)` —— UUID pk、`Status` TextChoices（running/completed/failed）、`board_url`/`mr_url` 留痕、`steps` JSONField（可调用 `default_steps` 默认三步全 pending）、`project` FK（`projects.Project`, SET_NULL, related_name=`ingest_runs`）、`error`、`started_at`/`completed_at`/`updated_at`，`Meta` 含 `ordering=["-started_at"]` + `(-started_at)` 索引（db_table `delivery_ingest_run`）。
- 模块级 `default_steps()` 返回 `{work_item, document, mr_diff}`，每步 `{status, identifier, link, error}`。
- `delivery/models/__init__.py` curated re-export `IngestRun` / `default_steps`。
- `makemigrations delivery` 生成 `0008_ingestrun.py`（依赖 0007）。

### Task 2 — URL 解析 + Repository 匹配 helper + 单测（commit `205efb2d`）
- `server/delivery/services/ingest_parsing.py`：
  - `BoardRef`（frozen dataclass）+ `parse_board_url(url) -> BoardRef | None`：匹配飞书域 `https://{host}/{simple_name}/{url_type}/detail/{id}`，容忍尾部 query/fragment/斜杠；非飞书域/缺段/非数字 id/容器型不可靠形态 → None。
  - `MRRef`（frozen dataclass）+ `parse_mr_url(url) -> MRRef | None`：识别 GitLab `.../-/merge_requests/{iid}`（含嵌套组）与 GitHub `.../pull/{iid}`。
  - `aresolve_repo_and_mr(url) -> tuple[Repository, str] | None`（async）：`async for` 遍历 `Repository.objects`，复用 `extract_gitlab_url`/`extract_project_path`/`extract_github_owner_repo` 归一比对 host+path（去 `.git`/末尾斜杠、忽略大小写），命中返回 `(repo, iid)`，无匹配 → None。
- `delivery/services/__init__.py` 追加 5 个符号到 re-export + `__all__`。
- 单测：`test_ingest_parsing.py`（26 例：board 标准/容忍/larksuite/8 类 None/喂 WorkItemIdentity；MR GitLab/嵌套/GitHub/6 类 None；async 匹配 GitLab/GitHub/SSH 大小写/无匹配/非 MR）+ `test_ingest_run_model.py`（6 例：default_steps 形状/不共享、run 默认值、Status 枚举、steps 无损、排序）。

## Verification Results

- `makemigrations delivery --check --dry-run` → `No changes detected`（退出 0，无漂移）。
- `migrate delivery` → `Applying delivery.0008_ingestrun... OK`。
- 模型冒烟 → 打印 `running dict_keys(['work_item', 'document', 'mr_diff'])`。
- `pytest tests/delivery/test_ingest_parsing.py tests/delivery/test_ingest_run_model.py -q` → **32 passed**。
- `ruff check`（仅改动文件）→ All checks passed。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Model Compliance

- **T-32-01（SSRF/Tampering）**：`aresolve_repo_and_mr` 强制把 MR 解析结果匹配到已落库 Repository 才返回；无 fetch 任意用户 URL 的路径。解析仅抽标识符。
- **T-32-02（信息泄露）**：`IngestRun.error` / `steps[*].error` 为纯文本载体，docstring 标注「写入侧（32-02）负责脱敏」；本 plan 模型层不落任何不可信内容。
- **T-32-03**：本 plan 不暴露 REST 端点（归 32-02），不适用。
- 无新增 npm/pip/cargo 依赖。

## Self-Check: PASSED

- FOUND: server/delivery/models/ingest_run.py
- FOUND: server/delivery/services/ingest_parsing.py
- FOUND: server/delivery/migrations/0008_ingestrun.py
- FOUND: server/tests/delivery/test_ingest_parsing.py
- FOUND: server/tests/delivery/test_ingest_run_model.py
- FOUND commit: 1014f075
- FOUND commit: 205efb2d
