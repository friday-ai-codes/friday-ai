---
phase: quick-260728-ppb-start-feature-solution
plan: 01
status: complete
subsystem: prompts
tags: [prompt-center, builtin-drift, start_feature_solution, chat]
requires: [prompts migrations 0002/0009/0010, Prompt Center render_prompt]
provides: [0011 resync migration, check_builtin_prompt_drift, project context solution guidance]
affects: [prompts/, chat/config.py, deployed Prompt Center bodies]
tech-stack:
  added: []
  patterns: [idempotent builtin prompt resync migration, ops-only drift check CLI, REQUIRED_SLUGS lock]
key-files:
  created:
    - server/prompts/migrations/0011_resync_coding_guidance_feature_solution.py
    - server/prompts/builtin_contract.py
    - server/prompts/management/commands/check_builtin_prompt_drift.py
    - server/tests/test_resync_coding_guidance_feature_solution.py
    - server/tests/test_check_builtin_prompt_drift.py
    - server/tests/test_project_context_line.py
  modified:
    - server/tests/test_prompts_migration_contract.py
    - server/chat/config.py
decisions:
  - 根因是 Prompt Center DB active body 漂移，不是工具白名单缺失
  - 漂移防护走 management command，不进 render_prompt 热路径
  - 项目上下文行显式点名 start_feature_solution，补齐 coding_guidance 之前的引导缺口
metrics:
  duration: ~40min
  completed: 2026-07-28
---

# Quick Task 260728-ppb: start_feature_solution 漂移修复 Summary

修复项目级对话「生成技术方案」不走正式编排的真根因：已部署实例上 `chat.coding_guidance` 停在 2026-06-09 旧 seed（880 字符，不含 `start_feature_solution`），`render_prompt` 命中 DB 后 Python fallback 永不生效。

## 根因回顾

生产会话 `1cdb0436-5a99-4bc0-9db9-97569c46383d` 调查结论：

1. space「学习工具」有 30 个 indexed 仓库 → `start_feature_solution` **当时已在工具列表**。
2. 生产 `chat.coding_guidance` active v1 body 不含 `start_feature_solution`；本地字面量含该指令 → Prompt Center 漂移。
3. `_build_project_context_line` 只列只读工具，装配在 coding_guidance 之前，进一步诱导 LLM 读项目后自由写 markdown。
4. `delivery_convergence_session` 对该会话 0 行 → 未进 `process_runtime`。

## Task Commits

1. **Task A: 0011 resync migration** — `3fe21bc6` + `e80ee0dc`
2. **Task B: drift command + 单一契约来源** — `ea9cad59` + `420825f5`
3. **Task C: 项目级对话方案工具引导** — `4e205236`

## 改动要点

| 产物 | 作用 |
|------|------|
| `0011_resync_coding_guidance_feature_solution.py` | 幂等拉齐 `chat.coding_guidance` + `chat.strategy.default` active body |
| `prompts/builtin_contract.py` | `BUILTIN_CONTRACT_SLUGS` 单一来源；detect / resync；禁止顶层 import chat |
| `check_builtin_prompt_drift` | 生产可跑；零漂移 exit 0；有漂移非零；`--fix` append+切 active |
| `_build_project_context_line` | 点名 `start_feature_solution`；只读工具「不能替代方案产出」；三路分流 |

## 生产生效与验证

部署后：

```bash
cd server && uv run python manage.py migrate prompts
uv run python manage.py check_builtin_prompt_drift   # 期望 exit 0
```

或查 DB：`chat.coding_guidance` active body 须含 `start_feature_solution`。

**不要**在未 migrate 的本地默认库上把该命令 exit 0 当开发完成条件——缺 Prompt / 未应用 0011 时它本应非零。

## 明确未做（第二批）

- `task_category` 枚举化与服务端兜底路由
- 范围类 `ask_clarification` 护栏（引导改走 `start_feature_solution` 强制确认）
- 给「高三提分专项」补 `initiative_repo_association`（生产数据操作，另办）

## Deviations

- Executor 中途被打断；接续时发现 Task A 已提交、Task B 实现未提交、Task C 未开始。按计划完成 B/C 并补 SUMMARY。
- Task B 测试先于实现提交（`ea9cad59`），随后实现提交 `420825f5`；顺序与经典 TDD 一致，无功能偏差。
