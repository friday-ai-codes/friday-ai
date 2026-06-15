---
phase: 22-fail-closed
plan: 01
subsystem: api
tags: [exclusion, fail-closed, security, django-orm, structlog, fnmatch, regex]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: 22-CONTEXT.md 排除配置决策（D-01..D-04）、DOMAIN §9 安全边界与数据面矩阵
provides:
  - "RepoExclusionRule per-repo 排除规则模型（dir/glob/regex + source override 标记）"
  - "SettingKeys.CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS 全局默认单一源"
  - "services/exclusion.py 单一匹配器：ExclusionMatcher + is_excluded(repository_id, rel_path) 统一入口"
  - "BUILTIN_GLOBAL_DEFAULTS 开箱即用安全默认"
  - "fail-closed 归一/匹配 + fail-loud 非法 regex + exclusion.blocked 审计埋点"
affects: [22-fail-closed Wave 2 enforcement plans, 23-purge, scan_directory, MCP tools, RAG 检索, coding container]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单一事实源 + 单一匹配器：所有读取面只调 is_excluded，禁止各自另写过滤"
    - "失败模式二分：构造期 fail-loud（InvalidExclusionRuleError）/ 运行期 fail-closed（返回 True）"
    - "TTL monotonic 缓存 + invalidate（沿用 chat_tools._indexed_paths_cache idiom）"
    - "async ORM 经 sync_to_async（_load_specs_from_db）"

key-files:
  created:
    - server/services/exclusion.py
    - server/repositories/migrations/0032_repo_exclusion_rule.py
    - server/tests/services/test_exclusion_matcher.py
  modified:
    - server/repositories/models.py
    - server/system/models.py

key-decisions:
  - "dir 规则按相对仓库根前缀匹配（目录本身 + 子树），glob 用 fnmatch.translate 编译为 full-string 正则（跨 / 匹配，满足 *.pem 命中嵌套）"
  - "BUILTIN_GLOBAL_DEFAULTS 全部 source=global，per-repo 同 pattern + enabled=False 行作为关闭 override 标记"
  - "迁移文件名按 plan artifacts 规范改为 0032_repo_exclusion_rule.py（手写 CreateModel，仅建表不回填）"

patterns-established:
  - "排除判定唯一入口 services.exclusion.is_excluded —— Wave 2 plans 直接引用，不得另起炉灶"
  - "审计埋点统一事件名 exclusion.blocked（surface/repository_id/rel_path），运行期异常路径自动埋点"

requirements-completed: [EXCL-01, EXCL-02]

# Metrics
duration: 9min
completed: 2026-06-14
---

# Phase 22 Plan 01: 排除配置单一源 + 单一匹配器 Summary

**建立排除配置单一事实源（RepoExclusionRule + 全局默认 SystemSetting 键）与单一匹配器 `is_excluded(repository_id, rel_path)`：编译一次/复用、dir/glob/regex 三类规则、运行期 fail-closed、构造期非法 regex fail-loud，内置开箱即用安全默认。**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-14T08:16:00Z
- **Completed:** 2026-06-14T08:25:36Z
- **Tasks:** 2
- **Files modified:** 5（2 created services/migration + 1 test + 2 modified models）

## Accomplishments
- `RepoExclusionRule` 模型落地：FK Repository(CASCADE, related_name="exclusion_rules")、rule_type/source TextChoices、unique_together(repository, rule_type, pattern, source) + index(repository, enabled)。
- `SettingKeys.CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS` 复用既有 SystemSetting 键体系，承载全局默认 JSON 规则列表。
- 迁移 `0032_repo_exclusion_rule.py` 仅 CreateModel、依赖 0031、不回填（per D-04），`makemigrations --check` 干净。
- `services/exclusion.py` 单一匹配器：`ExclusionMatcher`（编译一次）、`normalize_rel_path`、`build_matcher_for_repo`（合并 builtin∪全局设置∪per-repo + global override + TTL 缓存）、`is_excluded` 统一入口、`log_exclusion_blocked` 审计埋点、`InvalidExclusionRuleError`。
- 18 个单测全绿，覆盖 dir/glob/regex 匹配、归一越界/绝对路径/运行期异常 fail-closed、非法 regex fail-loud、builtin 默认覆盖面、DB 合并 + global override + 缓存命中（ORM 仅查一次）。

## Task Commits

Each task was committed atomically:

1. **Task 1: RepoExclusionRule 模型 + 全局默认设置键 + 迁移** - `0fd29af1d` (feat)
2. **Task 2: ExclusionMatcher + 内置全局默认 + 单一匹配器（TDD）** - `df0e98778` (test, RED) → `064ebdcc0` (feat, GREEN)

_TDD: Task 2 走 RED（test 提交，模块缺失 → 收集失败）→ GREEN（feat 提交，18 passed）。无 refactor 提交（GREEN 一次到位）。_

## Files Created/Modified
- `server/services/exclusion.py` - 单一匹配器模块（matcher + 合并加载器 + 统一入口 + 审计埋点）
- `server/repositories/migrations/0032_repo_exclusion_rule.py` - RepoExclusionRule 建表迁移（仅建表）
- `server/tests/services/test_exclusion_matcher.py` - 18 个单测
- `server/repositories/models.py` - 新增 `RepoExclusionRule`
- `server/system/models.py` - 新增 `SettingKeys.CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS`

## Decisions Made
- **dir 匹配语义**：相对仓库根前缀（匹配目录本身 + 子树），与 plan/D-02 一致；不做"目录名任意层级匹配"（保持单一可预测口径，且 glob/`.ssh/` 等已覆盖嵌套密钥场景）。
- **glob 编译**：`re.compile(fnmatch.translate(pattern))` 大小写敏感、跨 `/` 匹配，使 `*.pem` 命中 `certs/x.pem`（满足 acceptance），`.env` 仅命中根 `.env`（full-string）。
- **override 语义**：per-repo `source=global & enabled=False` 行仅作"关闭某条全局默认"标记，从有效集合中剔除同 `(rule_type, pattern)`；其自身不作为规则加入。
- **迁移文件名**：Django 默认生成 `0032_repoexclusionrule.py`，按 plan artifacts 规范改名为 `0032_repo_exclusion_rule.py`（内容等价，手写 CreateModel）。

## Deviations from Plan

None - plan executed exactly as written.

（说明：迁移文件改名与"手写 CreateModel"属落地细节，非偏离；行为/schema 与 makemigrations 自动生成完全一致，`makemigrations --check --dry-run` 干净。）

## Issues Encountered
- 测试运行器解析：`uv run pytest` 在本机回落到 pyenv 全局 pytest 触发插件路径错误；改用项目 venv `server/.venv/bin/python -m pytest` 正常（rootdir=server，18 passed）。不影响交付物。

## User Setup Required
None - 无外部服务配置；既有部署升级后仅 builtin 全局默认 + SystemSetting 生效，向后兼容。

## Next Phase Readiness
- Wave 2 所有 enforcement plan 地基就绪：可直接 `from services.exclusion import is_excluded` 挂接索引扫描（PF-04 scan_directory）、MCP get_file/grep/rag、RAG 检索、agent/编码容器过滤。
- Plan 05（规则配置保存 API）可复用 `InvalidExclusionRuleError`（构造 ExclusionMatcher 校验非法 regex）与 `invalidate_matcher_cache`（规则变更后失效缓存）。
- 注意：本 plan 仅判定层，不改既有写入结构（per D-04）；存量派生数据清理留 Phase 23。

## Self-Check: PASSED

- Files: exclusion.py / 0032_repo_exclusion_rule.py / test_exclusion_matcher.py / 22-01-SUMMARY.md — all FOUND.
- Commits: 0fd29af1d / df0e98778 / 064ebdcc0 — all FOUND.
- Tests: 18 passed (`server/.venv/bin/python -m pytest tests/services/test_exclusion_matcher.py`).
- `makemigrations --check --dry-run repositories` — clean (No changes detected).
- `is_excluded` / `ExclusionMatcher` 仅 services/exclusion.py 单一实现。

---
*Phase: 22-fail-closed*
*Completed: 2026-06-14*
