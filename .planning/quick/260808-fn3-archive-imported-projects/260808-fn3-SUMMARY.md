---
status: complete
---

# Quick Task 260808-fn3: 归档批量导入的历史项目并清理默认分支绑定 — Summary

**Date:** 2026-08-08
**Status:** complete

## 背景

260807 批量导入（ricelove feature 页 247 + 能力簇方案 284 + 上线记录表 1）把 532 个
历史项目全部落成模型默认状态「开发中」，并给每个关联仓库绑了
`repository.default_branch`（302×master / 76×feat/coding-agent-base / 4×main），
导致 `ProjectBranch` 的「分支→项目反查」失效（master 对应 ~300 个项目）。

## 执行结果（`cleanup_imported.py`，零错误）

| 项 | 数量 |
|---|---|
| 归档项目（developing → archived） | 532 |
| 删除分支绑定 | 377 |
| 错误 | 0 |

- 终态：`developing` 仅剩 3 个手工项目（高三提分专项 / 小学思维培优-刷题入口 / test1）；
  其余 532 个全部 `archived`（archived → developing 可逆，需要时可单独恢复）。
- 剩余绑定 6 条，全部属于真实项目：高三提分专项 4×`feat/coding-agent-base`、
  小学思维培优 1×真实 feature 分支 + 1×main。
- ⛔ 按用户确认，4 个 `default_branch=feat/coding-agent-base` 的仓库**未**改动。

## 口径

- 全走 service 层（INV-6）：`ProjectService.archive` / `ProjectBranchService.unbind`，
  审计与结构化日志归因到 admin（initiated_by_user_id）。
- 脚本幂等可重跑；报告落 `/tmp/friday-archive-imported-report.json`。
- 后续导入脚本的教训：历史数据导入应显式传 `status=archived`；拿不到真实 feature
  分支时不要退绑默认分支。
