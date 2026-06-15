---
phase: 22-fail-closed
plan: 04
subsystem: api
tags: [exclusion, fail-closed, security, coding-container, env-injection, prune, fnmatch, regex]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: "22-01 单一匹配器 services.exclusion（is_excluded / build_matcher_for_repo / BUILTIN_GLOBAL_DEFAULTS / _resolve_effective_specs）"
provides:
  - "services.exclusion.serialize_rules_for_repo(repository_id) -> list[{pattern, rule_type}]（容器下传规则导出，绝不空）"
  - "两条编码派发路径下传 env_FRIDAY_TASK_EXCLUDE_PATTERNS（chat build_dispatch_metadata + workflow AICodingNode._run_repo_coding）"
  - "task/core/exclusion.py 容器侧轻量匹配器 + prune_excluded(workspace, rules) + ExclusionPruneError"
  - "TaskConfig.exclude_patterns（FRIDAY_TASK_EXCLUDE_PATTERNS JSON）"
  - "git_ops.setup() clone+checkout 后 prune（fail-closed，跳过 .git/）"
affects: [22-fail-closed Wave 2 enforcement, 23-purge, coding container runtime]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单一真相合并：matcher 与容器下传序列化共用 _resolve_effective_specs（无双份真相）"
    - "容器面默认 fail-closed：无条件下传有效规则（即便仅 builtin），不下传 = 容器裸奔"
    - "容器侧匹配器语义对齐 server（dir 前缀 / glob fnmatch full-string / regex fullmatch），task 包独立绝不 import server"
    - "prune fail-closed 失败模式：删除重试（chmod +w）→ 持久失败 raise → setup 失败传播"

key-files:
  created:
    - task/core/exclusion.py
    - task/tests/test_exclusion_prune.py
    - server/tests/chat/test_coding_exclusion_env.py
  modified:
    - server/services/exclusion.py
    - server/chat/coding_session_service.py
    - server/workflows/nodes/ai/coding.py
    - task/core/config.py
    - task/git_ops/operations.py

key-decisions:
  - "serialize_rules_for_repo 绝不返回空列表：异常/无配置时回退 BUILTIN_GLOBAL_DEFAULTS（容器默认安全）"
  - "_resolve_effective_specs 作为合并真相，_load_specs_from_db 保留为别名（兼容既有测试 patch）"
  - "prune 跳过任意层级 .git/ 目录（不下钻、不删除），保护 commit/push 元数据"
  - "持久删除失败 → ExclusionPruneError 致命传播（fail-closed），不允许 log-and-continue 残留可读文件"

requirements-completed: [EXCL-02]

# Metrics
duration: ~13min
completed: 2026-06-14
---

# Phase 22 Plan 04: 排除过滤延伸到编码容器面 Summary

**把排除过滤延伸到编码容器读取面：server 两条编码派发路径（chat `build_dispatch_metadata` + workflow `AICodingNode._run_repo_coding`）无条件下传有效排除规则经 `env_FRIDAY_TASK_EXCLUDE_PATTERNS` 注入；task 容器在 clone+checkout 后按规则物理删除工作树中被排除文件（跳过 `.git/`），删除持久失败时 fail-closed 抛错使 setup 失败——绝不让容器内 agent 看到被排除文件。**

## Performance

- **Duration:** ~13 min
- **Tasks:** 2（均 TDD：RED → GREEN）
- **Files:** 3 created + 5 modified

## Accomplishments

- **server 规则导出（单一真相）**：`services/exclusion.py` 将 `_load_specs_from_db` 重命名为 `_resolve_effective_specs`（保留别名兼容既有 patch），新增 `serialize_rules_for_repo(repository_id)` 复用同一合并逻辑导出 `[{pattern, rule_type}]`，异常/空时回退 `BUILTIN_GLOBAL_DEFAULTS`（**绝不空**）。
- **两路径无条件注入**：chat `build_dispatch_metadata`（env_metadata 构建末尾）与 workflow `AICodingNode._run_repo_coding`（inline `DispatchTask.metadata`，与 anthropic_env/tools_env 并列）均注入 `env_FRIDAY_TASK_EXCLUDE_PATTERNS`（json）。仅下传规则模式，不含任何凭证。
- **容器侧匹配器 + prune**：`task/core/exclusion.py` 轻量匹配器语义对齐 server（dir 相对根前缀 / glob `fnmatch.translate` full-string / regex fullmatch；归一/匹配异常保守判命中），`prune_excluded(workspace, rules)` os.walk 工作树删除命中文件、清理空目录、返回删除计数。无第三方依赖（仅 stdlib `fnmatch`/`re`，per T-22-SC accept）。
- **fail-closed 失败模式**：`_delete_with_retry` 首次失败 chmod +w 后重试（最多 3 次）；任一被排除文件持久删除失败 → `prune_excluded` 抛 `ExclusionPruneError`，`git_ops.setup` 不捕获使其传播 → setup 失败 → 任务 failed。绝不在被排除文件仍可读时让 setup 成功。
- **保护 git 元数据**：prune 在 os.walk 中剔除任意层级 `.git` 目录（不下钻、不删除），空目录清理亦跳过 `.git`。
- **TaskConfig 字段**：新增 `exclude_patterns: list[dict]`（pydantic-settings 自动从 `FRIDAY_TASK_EXCLUDE_PATTERNS` JSON 解析，与 `remote_tools` 同 idiom），默认空 → 向后兼容。

## Task Commits

1. **Task 1: server 导出有效规则 + 两路径注入 env**（TDD）
   - `dec139c81` (test, RED — ImportError serialize_rules_for_repo)
   - `08880763d` (feat, GREEN — serialize_rules_for_repo + 两路径注入)
2. **Task 2: 容器侧匹配器 + config + clone 后 prune（fail-closed）**（TDD）
   - `cc9daaea7` (test, RED — module core.exclusion 缺失)
   - `1c925c804` (feat, GREEN — prune_excluded + ExclusionPruneError + config + setup 接入)

_无 refactor 提交（两次 GREEN 一次到位）。_

## Files Created/Modified

- `server/services/exclusion.py` - `_resolve_effective_specs`（合并真相）+ `serialize_rules_for_repo`（导出，绝不空）+ `_load_specs_from_db` 兼容别名
- `server/chat/coding_session_service.py` - `build_dispatch_metadata` 注入 `env_FRIDAY_TASK_EXCLUDE_PATTERNS`
- `server/workflows/nodes/ai/coding.py` - `_run_repo_coding` inline metadata 注入同键（+ `import json`）
- `task/core/exclusion.py` - 容器侧匹配器 + `prune_excluded` + `ExclusionPruneError`（新建）
- `task/core/config.py` - `TaskConfig.exclude_patterns` 字段
- `task/git_ops/operations.py` - `setup()` clone+checkout 后调用 `prune_excluded`，propagate `ExclusionPruneError`
- `server/tests/chat/test_coding_exclusion_env.py` - 4 守卫（serialize + 两路径 env 注入）
- `task/tests/test_exclusion_prune.py` - 9 守卫（prune dir/glob/regex、.git 保留、config 解析、空规则、持久失败 raise、可恢复失败、setup 传播 + 成功 prune）

## Decisions Made

- **绝不空导出**：`serialize_rules_for_repo` 异常/无配置回退 builtin —— 不下传 = 容器面裸奔（T-22-14），故默认安全优先于"忠实反映空配置"。
- **合并真相单一化**：matcher（`build_matcher_for_repo`）与容器下传序列化共用 `_resolve_effective_specs`，避免双份合并逻辑漂移；`_load_specs_from_db` 别名保留使 22-01 既有 patch 测试不破。
- **task 包独立**：容器侧重写轻量匹配器而非 import server（task 与 server 是不同部署/包边界），但语义严格对齐（dir/glob/regex 与 22-01 一致）。
- **持久删除失败致命**：fail-closed 的核心修正（WARNING 3）——删除失败重试后仍失败则 raise，setup 失败，宁可任务失败也不残留可读被排除文件。

## Deviations from Plan

None - plan executed exactly as written（含修订符号名 `build_dispatch_metadata` / `_run_repo_coding`）。

注：为避免把 `coding.py` / `coding_session_service.py` 既有 ruff 格式漂移（与本 plan 无关）混入提交，未对这两个文件整体 `ruff format`（仅手写符合 ruff 风格的新增行，`ruff check` 全绿）；`exclusion.py` / `task/core/exclusion.py` 已 `ruff format`。

## Threat Model Coverage

| Threat ID | Mitigation 落地 |
|-----------|-----------------|
| T-22-13 | clone+checkout 后 `prune_excluded` 删净；`git_ops.setup` 必经路径调用（测试断言） |
| T-22-14 | chat + workflow 两路径均注入，各自测试断言含 `env_FRIDAY_TASK_EXCLUDE_PATTERNS` 且非空 |
| T-22-15 | prune 跳过任意层级 `.git/`（不下钻/不删/空目录清理跳过）；`test_git_dir_preserved` 断言元数据完整 |
| T-22-16 | 删除重试 → 持久失败 raise `ExclusionPruneError` 使 setup 失败；`test_persistent_delete_failure_*` 断言抛错且被排除文件不在成功路径残留 |
| T-22-SC | 仅用 stdlib `fnmatch`/`re`，不新增第三方包（accept） |

## Next Phase Readiness

- EXCL-02 第四个读取面（容器面）就绪：编码容器内 agent 不可见被排除文件，两条派发路径均下传规则，prune 不破坏 git。
- Plan 05（规则配置保存 API）规则变更后 server 侧 `invalidate_matcher_cache` 已有；容器下传走 dispatch 时点的有效规则快照（每次派发重新 serialize）。
- 存量派生数据清理仍留 Phase 23（本 plan 仅容器工作树读取面，不动既有 Qdrant/索引）。

## Self-Check: PASSED

- Files: server/services/exclusion.py / server/chat/coding_session_service.py / server/workflows/nodes/ai/coding.py / task/core/exclusion.py / task/core/config.py / task/git_ops/operations.py / task/tests/test_exclusion_prune.py / server/tests/chat/test_coding_exclusion_env.py — all FOUND.
- Commits: dec139c81 / 08880763d / cc9daaea7 / 1c925c804 — all FOUND.
- Tests: server 4 passed (test_coding_exclusion_env) + task 9 passed (test_exclusion_prune)；回归 server coding_session_service 15 + exclusion_matcher 18 + coding passthrough/remote_tool 20 + task config/git_ops/guard 30 全绿。
- grep: `EXCLUDE_PATTERNS` 同时出现于 coding_session_service.py 与 coding.py（两路径均注入）。

---
*Phase: 22-fail-closed*
*Completed: 2026-06-14*
