---
quick_id: 260913-g74
slug: git-filter-repo-public
status: complete
---

# 完成摘要

- 保留 `.planning/`、`.agents/`、`.claude/`、`.codex/`、`.cursor/` 的 Git 跟踪，确保 GSD 进度与工具同步。
- 将 GSD/Agent 工具中的个人绝对路径改为仓库相对路径，Codex hooks 改用 PATH 中的 `node`。
- 将 golden、测试、规划中的可识别业务语料改为通用功能专项样例，并保持章程匹配所需的子串关系。
- 当前树对个人根路径、内部域名、内部仓名、生产会话标识和旧业务词的扫描为零。
- `.env` 仍由 `.gitignore` 排除，当前和历史均未跟踪。

## 验证

- GSD `init.quick`：通过。
- Codex hooks JSON：通过解析。
- 前端受影响测试：6 files / 187 tests 通过。
- 后端重点匹配测试：3 files / 106 tests 通过。
- 后端扩展测试：997 通过、17 失败；失败中 15 项为存量 API/schema 或 fixture 基线问题，2 项已通过保持中性化子串关系修复。
- 全量后端测试：11,046 通过、83 失败，失败为当前仓库存量基线/环境问题。
