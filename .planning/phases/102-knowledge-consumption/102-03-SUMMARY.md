---
phase: 102-knowledge-consumption
plan: 03
subsystem: mcp-contract-docs
tags: [mcp, snapshot, skills, guard-tests, unify-04]
requires:
  - "Phase 100：learning_case 检索已切向量版（语义定版依据）"
provides:
  - "TOOL_SCHEMA_SNAPSHOT 30 键（补 report_project_state）"
  - "注册==snapshot 集合防漏守卫测试"
  - "skills 文档工具名 ⊆ snapshot grep 守卫测试"
  - "friday-memory / friday-code SKILL.md 与新行为对齐"
affects:
  - "未来新增 MCP 工具：漏 snapshot 或文档写错工具名将 CI 红"
tech-stack:
  added: []
  patterns:
    - "契约防漏：urls 路由名集合 == snapshot 键集合双向差集断言"
    - "文档面守卫：反引号 + 动词前缀 token 抽取，允许集含 request/response 字段名防误报"
key-files:
  created:
    - server/tests/mcp_tools/test_skills_snapshot_guard.py
  modified:
    - server/mcp_tools/serializers.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - skills/skills/friday-memory/SKILL.md（skills 子模块）
    - skills/skills/friday-code/SKILL.md（skills 子模块）
decisions:
  - "skills 文档改动提交在 skills 子模块（e804acf），主仓提交指针更新（104fe3a1）"
  - "grep 守卫允许集 = snapshot 键集 ∪ 全部 request/response 字段名（create_document 等参数名不误报）"
metrics:
  duration: "~6 分钟"
  completed: "2026-07-22"
---

# Phase 102 Plan 03: 对外契约与 skills 文档对齐 Summary

TOOL_SCHEMA_SNAPSHOT 补 report_project_state 至 30 键并加两道 CI 防漏守卫（注册==snapshot 集合断言 + skills 文档工具名 grep 守卫），friday-memory/friday-code SKILL.md 与 Phase 100 向量检索语义及 reverse_lookup_requirements 路由对齐。

## Tasks

| Task | 内容 | Commit |
| --- | --- | --- |
| 1 | snapshot 补 report_project_state + 注册==snapshot 守卫 | 73c4dac6 |
| 2 | skills 文档工具名 ⊆ snapshot grep 守卫测试（新文件） | 65d5922e |
| 3 | friday-memory 向量语义改写 + friday-code 反查路由 | skills@e804acf + 主仓 104fe3a1（指针） |

## 验证结果

- `report_project_state` 契约执行时再次对照实现核实：request = `ReportProjectStateRequestSerializer` 字段序（project_id / branch_name / repository_id / apis）；response 键 `_skip`（views.py L3156-3163）与成功路径（L3271-3277）完全一致（applied / reason / results / total_applied / run_id）。
- `uv run pytest tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_skills_snapshot_guard.py -v`：**4 passed**。
- 守卫红化验证均已做并撤销：从 snapshot 删键令集合守卫红（负向脚本验证 30==30）；向 SKILL.md 写入 `search_nonexistent_thing` 令 grep 守卫红（逐文件列出越界 token）。
- `uv run ruff check mcp_tools/serializers.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_skills_snapshot_guard.py`：干净。
- `rg -n "收窄范围" skills/skills/friday-memory/SKILL.md`：零命中；`reverse_lookup_requirements` 在 friday-code 出现 2 处（步骤 + 模式判定行）。

## Deviations from Plan

### 调整

**1. [执行事实] skills/ 是 git 子模块，SKILL.md 改动分两处提交**
- **Found during:** Task 3 提交阶段（Task 2 红化验证撤销时发现外仓 `git checkout` 不认子模块路径）
- **处理:** 文档改动提交在 skills 子模块（e804acf，遵循子模块自身 Conventional Commits），主仓单独提交子模块指针更新（104fe3a1）
- **影响:** 无功能影响；发布 skills 文档需推送子模块远端（github.com/friday-ai-codes/skills）

其余任务按计划逐字执行，无功能性偏差。

## Deferred Issues

- `tests/mcp_tools/` 目录级 ruff 存在 2 个既有报错（`test_delivery_knowledge_tools.py` F401、`test_find_related_chunks.py` I001）——属并行 102-02 执行器文件面/既有问题，非本 plan 改动引入，按范围边界不修。

## Known Stubs

无——纯契约声明与文档改动，无运行时行为变更。

## Threat Flags

无新增安全面：T-102-09（snapshot 漂移）与 T-102-10（文档面漂移）的 mitigate 守卫均已落地为 CI 测试。

## Self-Check: PASSED

- server/tests/mcp_tools/test_skills_snapshot_guard.py：存在
- 提交 73c4dac6 / 65d5922e / 104fe3a1（主仓）、e804acf（skills 子模块）：均存在
- 4/4 目标测试通过
