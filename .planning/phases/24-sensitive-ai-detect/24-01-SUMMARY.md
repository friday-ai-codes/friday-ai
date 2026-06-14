---
phase: 24-sensitive-ai-detect
plan: 01
subsystem: database
tags: [django, sensitive-detection, secret-scanning, regex, entropy, upsert, exclusion]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: services.exclusion.BUILTIN_GLOBAL_DEFAULTS（敏感文件名基线）、normalize_rel_path、RepoExclusionRule.Source.AI_SUGGESTED
provides:
  - SensitiveFileSuggestion 模型（repo FK + path + severity/detector/status + 脱敏 reason + unique(repo,path)）
  - 迁移 0034（依赖 0033，仅 CreateModel）
  - services/sensitive_detect.py 确定性检测器（独立有界遍历 + 文件名启发式 + 内容密钥扫描 + 脱敏 reason + aupdate_or_create upsert）
  - detect_sensitive_files(repository_id, repo_path) async 入口
affects: [24-02 索引触发+LLM 增强, 24-03 REST API, 24-04 前端建议面板]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "确定性检测器：自走有界遍历（不复用扩展名白名单扫描），文件名启发式复用 BUILTIN_GLOBAL_DEFAULTS glob 基线"
    - "脱敏单一构造入口 _redact_reason(kind, line_no)：reason 只含类型+行号，从源头杜绝密钥本体泄漏"
    - "upsert 经 aupdate_or_create + dismissed-respect/real_secret-升级 状态机"

key-files:
  created:
    - server/services/sensitive_detect.py
    - server/repositories/migrations/0034_sensitive_file_suggestion.py
    - server/tests/services/test_sensitive_detect.py
  modified:
    - server/repositories/models.py

key-decisions:
  - "遍历跳过集仅含 .git/node_modules（结构性噪声）；.ssh/secrets 等 BUILTIN dir 默认**不**跳过——那恰是要识别的敏感目录（偏离 PLAN 措辞，Rule 1）"
  - "reason 由 _redact_reason 从『类型+行号』结构化构造，绝不回填命中文本/group 值（T-24-01）"
  - "content 命中即 real_secret；高熵串单独命中降为 likely_sensitive 且跳过注释行降噪"
  - "upsert 经 aupdate_or_create：dismissed 仅在升级为 real_secret 时重置 pending，accepted 保留不复扰"

patterns-established:
  - "敏感检测纯函数链：_walk_candidate_files → _classify_file（_filename_severity + _scan_content）→ _finalize → _upsert_suggestion"
  - "模块级编译正则集 _SECRET_PATTERNS（私钥/AWS/GitHub/Slack/通用赋值）+ 高熵 Shannon 熵判定"

requirements-completed: [EXCL-03]

# Metrics
duration: ~22min
completed: 2026-06-15
---

# Phase 24 Plan 01: 敏感文件确定性检测核心 Summary

**SensitiveFileSuggestion 模型 + 迁移 0034 + services/sensitive_detect.py 确定性检测器（独立有界遍历 + 文件名启发式复用 Phase 22 基线 + 内容密钥扫描 + 全程脱敏 reason + aupdate_or_create upsert）**

## Performance

- **Duration:** ~22 min
- **Completed:** 2026-06-15
- **Tasks:** 2（TDD：1 RED + 1 GREEN）
- **Files modified/created:** 4（1 改 + 3 新）

## Accomplishments
- `SensitiveFileSuggestion` 模型：repo FK、path、severity/detector/status 三组 TextChoices、脱敏 reason（docstring 声明绝不含密钥本体）、unique(repository, path)、(repository, status) 索引。
- 迁移 0034 依赖 0033，`makemigrations --check --dry-run` 报 No changes detected。
- 确定性检测器：自走有界遍历（跳过 .git/node_modules + 1MiB/二进制/符号链接），文件名启发式复用 `BUILTIN_GLOBAL_DEFAULTS` glob（basename + 大小写不敏感），内容扫描覆盖私钥块/AWS/GitHub/Slack token/通用密钥赋值/高熵串。
- 脱敏：`.env`(AWS key)/`id_rsa`(私钥)/`settings.json`(GitHub token) 判 real_secret，普通 config 不过度标记，reason 全程不含密钥本体（守护测试断言 value not in reason）。
- upsert 语义：同 path 幂等更新；dismissed 不复扰，real_secret 升级重新置 pending。

## Task Commits

1. **Task 1: SensitiveFileSuggestion 模型 + 迁移 0034** — `69c5a2c17` (feat)
2. **Task 2 RED: 检测器守护测试** — `8c8cbf93d` (test)
3. **Task 2 GREEN: 确定性检测器实现** — `851c88e6f` (feat)

_Note: Task 2 为 TDD（test → feat）；无需 refactor 提交。_

## Files Created/Modified
- `server/repositories/models.py` — 新增 `SensitiveFileSuggestion` 模型（含 Severity/Detector/Status 枚举）
- `server/repositories/migrations/0034_sensitive_file_suggestion.py` — 建表迁移（依赖 0033，仅 CreateModel）
- `server/services/sensitive_detect.py` — 确定性检测器 + `detect_sensitive_files` 入口 + `_upsert_suggestion`
- `server/tests/services/test_sensitive_detect.py` — 6 例守护测试（脱敏 + 不过度标记 + upsert/dismissed/升级）

## Decisions Made
- 见 frontmatter key-decisions。核心：遍历跳过集仅含结构性噪声目录；脱敏 reason 单一构造入口；real_secret 升级才打扰 dismissed。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 遍历跳过集不纳入 BUILTIN dir 默认（.ssh/secrets）**
- **Found during:** Task 2（检测器遍历实现）
- **Issue:** PLAN action 措辞要求遍历「跳过 BUILTIN_GLOBAL_DEFAULTS 中 rule_type=="dir" 的目录名」，但其中 `.ssh/`、`secrets/` 恰是要主动识别的敏感目录。跳过它们会让检测器漏掉 `secrets/app.pem` 等目标文件，直接与本 plan 的 behavior 守护测试（filename-only hit）冲突、并违背检测器目的。
- **Fix:** 将遍历跳过集 `_SKIP_DIRS` 收窄为 `{".git", "node_modules"}`（与敏感识别无关的结构性噪声），并在代码注释中如实记录该偏离与原因。
- **Files modified:** server/services/sensitive_detect.py
- **Verification:** `test_filename_only_hit_yields_heuristic_suggestion` 通过（`secrets/app.pem` 被命中为 heuristic/config_review）
- **Committed in:** 851c88e6f (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed（1 bug/正确性）
**Impact on plan:** 偏离仅修正 PLAN 措辞与 behavior 测试的内在冲突，更贴合检测器目的，无 scope creep。

## Issues Encountered
- ruff 对迁移文件 import 排序报错（I001）→ 调整 `import uuid` 与 `import django.db.models.deletion` 顺序后清零。
- PLAN verification 要求 `grep scan_directory` 为空，初版 docstring 含该字面提示 → 改写措辞避免字面 token，grep 已清空。

## Threat Surface Scan
本 plan 仅新增一张建议表与纯检测逻辑，无新网络端点/认证路径/信任边界 schema 变更。威胁缓解均落地：T-24-01（脱敏 reason，测试断言 value not in reason）、T-24-02（1MiB+二进制+结构性目录跳过）、T-24-03（只产 pending 建议，不建规则不删数据）、T-24-04（逐文件 try/except 隔离）。无新增威胁面。

## Next Phase Readiness
- `detect_sensitive_files(repository_id, repo_path)` 入口就绪，24-02 可在 `run_full_index` 末尾 best-effort 触发并叠加可选 LLM 二分类。
- `SensitiveFileSuggestion` 模型就绪，24-03 REST API（list/accept/dismiss）、24-04 前端面板可直接消费。

## Self-Check: PASSED

- Files: server/services/sensitive_detect.py, server/repositories/migrations/0034_sensitive_file_suggestion.py, server/tests/services/test_sensitive_detect.py, .planning/phases/24-sensitive-ai-detect/24-01-SUMMARY.md — all FOUND.
- Commits: 69c5a2c17, 8c8cbf93d, 851c88e6f — all FOUND.
- Tests: 6 passed（detector）+ exclusion matcher 27 passed（无回归）；ruff 0 错；`makemigrations --check` No changes detected；`grep scan_directory` 空。

---
*Phase: 24-sensitive-ai-detect*
*Completed: 2026-06-15*
