---
phase: 103-container-integration
plan: "03"
subsystem: task
tags: [skills, docker, runtime-injection, agent-03]
requires: []
provides:
  - "task/scripts/sync_skills.py 幂等同步脚本（skills/skills/ → task/assets/skills/）"
  - "task/assets/skills/{friday-code,friday-memory} 提交入库的镜像物料"
  - "task/Dockerfile COPY assets/skills/ → /opt/friday/skills/"
  - "runner.py _inject_skills 运行时注入 {workspace}/.claude/skills/（同名不覆盖）"
affects: [task-image, container-agent-behavior]
tech-stack:
  added: []
  patterns: ["构建物料镜像拷贝 + hash 一致性测试防双源漂移", "best-effort 注入吞异常"]
key-files:
  created:
    - task/scripts/sync_skills.py
    - task/assets/skills/README.md
    - task/assets/skills/friday-code/ (SKILL.md + references/http-fallback.md)
    - task/assets/skills/friday-memory/ (SKILL.md + references/http-fallback.md)
    - task/tests/test_skills_injection.py
  modified:
    - task/Dockerfile
    - task/core/runner.py
decisions:
  - "sync 脚本用 Python 纯 stdlib（跨平台 + 与 hash 测试同语言）"
  - "assets 提交入库（不 .gitignore）：可重现构建 + hash 测试可跑"
  - "注入点在 git_ops.setup() 后、分支处理前——plan/execute/explore/repo_summary 各模式统一生效"
metrics:
  duration: "~6 分钟"
  completed: "2026-07-22"
---

# Phase 103 Plan 03: skills 同源注入 Summary

**一句话**：`skills/skills/{friday-code,friday-memory}`（git submodule，单一事实源）经幂等 Python 同步脚本拷入 `task/assets/skills/` 提交入库，Dockerfile COPY 到 `/opt/friday/skills/`，runner 运行时同名不覆盖地注入 `{workspace}/.claude/skills/`，经 executor 既有 `setting_sources=["project"]` 通道加载（零 executor 改动），sha256 逐文件一致性测试钉死双源漂移。

## 完成任务

| Task | 名称 | Commit | 关键文件 |
| ---- | ---- | ------ | -------- |
| 1 | 同步脚本 + assets 入库 + Dockerfile COPY | `4790e874` | task/scripts/sync_skills.py, task/assets/skills/**, task/Dockerfile |
| 2 | 运行时注入（同名不覆盖）+ hash 一致性测试 | `fb8994c7` | task/core/runner.py, task/tests/test_skills_injection.py |

## 实现要点

- **同步脚本**（`task/scripts/sync_skills.py`）：纯 stdlib；`SKILL_NAMES = ("friday-code", "friday-memory")`；目标存在先 rmtree 再 copytree（幂等，连跑两次验证通过）；源缺失（子模块未初始化）报错退出非 0；docstring 写明单一事实源与勿手工编辑。
- **Dockerfile**：runtime 阶段 adduser 之后、entrypoint COPY 之前追加 `COPY --chown=friday:friday assets/skills/ /opt/friday/skills/`，注释标注完整同源链路。
- **运行时注入**（`runner.py`）：模块级 `IMAGE_SKILLS_DIR = Path("/opt/friday/skills")`；`_inject_skills` 在 `git_ops.setup()` 成功后调用；源目录不存在 → `log.debug` 静默返回（本地 CLI / 旧镜像零回归）；逐子目录判断，目标同名已存在 → 跳过不覆盖（仓库自带优先）；全程 try/except 只 warning，绝不挂任务；日志记 injected/skipped 技能名列表（无敏感内容，`caller` 链路内低频事件）。
- **测试**（`task/tests/test_skills_injection.py`，6 测试）：
  - hash 一致性 ×2（参数化两技能）：向上逐级找仓库根，不可达 skip-with-reason；文件集合 + 逐文件 sha256 比对，失败信息提示重跑 sync 脚本。红绿已验证：人为篡改 assets 文件即红，restore 后绿。
  - 运行时注入 ×4：全量拷入 / 同名不覆盖（friday-code 预置保留、friday-memory 正常拷入）/ 源缺失静默跳过 / 内部异常吞掉只 warning。

## 验收结果

- `python3 task/scripts/sync_skills.py`（两次）✅ 幂等；同步后 `git status --porcelain task/assets/` 为空（无漂移）✅
- `cd task && uv run pytest tests/test_skills_injection.py -q` → 6 passed ✅
- `cd task && uv run pytest tests/ -q` → **206 passed, 3 skipped**（skip 为既有）✅ 零回归
- `grep "opt/friday/skills" task/Dockerfile task/core/runner.py` 两处路径一致 ✅
- ruff check 全过；新文件 ruff format 达标 ✅

## Deviations from Plan

**1. [说明性] skills/ 是 git submodule（102-03 已发现）**
- 计划的同步脚本本就只读取 `skills/skills/`，写入的 `task/assets/skills/` 在主仓库内——无需任何适配，仅在脚本错误提示中补充"请初始化子模块"指引。
- 非代码偏差，零影响。

**2. [范围外记录] `task/core/runner.py` 存在预存 ruff format 漂移**
- `ruff format --check` 对 runner.py 报 would-reformat，但 diff 全部位于本 plan 未触碰的既有代码段（`_load_resume_transcript`、`_run_commit_mode` 的 subprocess 调用等）；本 plan 新增的 `_inject_skills` 段格式达标。
- 按 scope boundary 不顺手修（避免与并行执行器 103-02 的 runner 周边文件产生无关 diff），记录待后续统一 format。

其余按计划原样执行。

## Threat Model 落实

| Threat | Mitigation | 落点 |
|--------|------------|------|
| T-103-10 双源漂移 | hash 一致性测试 + README 勿手工编辑 + 脚本单向同步 | test_skills_injection.py / assets/skills/README.md |
| T-103-11 注入覆盖仓库自带 skills | 同名跳过不覆盖 + 专项断言 | `_inject_skills` + test_inject_skips_existing_same_name |
| T-103-12 注入异常挂任务 | best-effort try/except + 吞异常断言 | `_inject_skills` + test_inject_swallows_exceptions |

## Known Stubs

无。

## Self-Check: PASSED

- task/scripts/sync_skills.py ✅ task/assets/skills/friday-code/SKILL.md ✅ task/assets/skills/friday-memory/SKILL.md ✅ task/tests/test_skills_injection.py ✅
- Commits `4790e874`、`fb8994c7` 均在 git log ✅
