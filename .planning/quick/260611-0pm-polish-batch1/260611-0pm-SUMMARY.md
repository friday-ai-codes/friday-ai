---
status: complete
---

# Quick Task 260611-0pm: 打磨第 1 批 — 口径对齐 + 痕迹清洗 + 社区脚手架

## 完成内容

### Task 1: 全仓口径对齐（commit 6ed6bccf8）

- README.md / README.en.md：`--skill friday-codebase-agent`（已不存在）改为真实命令 `npx @friday-ai-codes/skills`；Quick Start 补 `git clone`
- `docs/integrations/skills.md`：内置 Skill 表从虚构的 3 个聚合 skill 改为真实的 12 个原子 skill，安装与路由说明同步重写
- `docs/guide/friday-codebase-agent.md`：删除不存在的 `gh skill install` 命令；`full_auto` 描述从飞书链路改为纯编码端到端；workflow 表对齐真实 skill 名
- `docs/integrations/mcp.md` / `docs/guide/introduction.md`：同步修正引用
- `server/README.md`：整体重写（Django 6.0→5.1+、SQLite→DATABASE_URL、去 emoji 分节、目录对齐现状）
- CONTRIBUTING.md / `docs/contributing/index.md`：commit 规范与 `scripts/check_commit_messages.sh` 对齐（允许 scope，类型补全为 11 种）

### Task 2: 过程痕迹清洗（commit 0c63f0de2，274 文件）

- 脚本化清除注释与 docstring 中的 `implementation:` / `work item:` / `per ...` 前缀标记（734 行；tokenize 定位，仅触碰注释与三引号 docstring，跳过运行时字符串与 migrations）
- 手工改写 `CONTEXT decisions`、"遗留至 v24.0" 等内部决策引用（graph_builder.py、codegraph/views.py、test_git_diff_index.py 等）
- **个人路径泄漏清理**：10+ 处 `/Users/zaneliu/Projects/acme/*` 硬编码默认值改走环境变量（`TS_SAMPLE_REPO` / `GO_GIN_SAMPLE_REPO` / `GO_SAMPLE_REPO` / `VUE_SAMPLE_REPO` / `STUDY_APP_REPO` / `VOLAR_TEST_REPO` / `GOPLS_TEST_REPO`），skipif 增加空值守卫（`Path("")` 即 `.` 会误判存在）；management commands 示例路径改为通用占位，`measure_go_call_completeness --repo-root` 改为必填
- 验证：全量 AST 语法检查 0 错误；相关测试 48 passed / 17 skipped（集成测试按预期 skip）；ruff 自动修复 9 处 import 排序

### Task 3: 社区脚手架（commit 7f0c43818）

- `.github/ISSUE_TEMPLATE/`：bug_report.yml（含部署方式/版本/日志字段）、feature_request.yml、config.yml（安全报告与文档站引导）
- `.github/PULL_REQUEST_TEMPLATE.md`：改动说明 + commit 规范检查清单
- `CODE_OF_CONDUCT.md`：Contributor Covenant v2.1 中文版

## 用户决策

- Star History 区块保留（用户选择）
- 开工前先把在途改动分 3 笔提交（docs 流程图 b966203dc、CI+README 徽标 0f725a115、dashboard 动效 d6da84658）

## 遗留（转后续任务）

- **P0-2b 深层痕迹**：约 900+ 行无冒号的 `work item` / `per contract` / `contract / contract` 中缀引用（原 phase ID 被泛化替换后的残迹），需按语义逐条改写，机械替换会破坏句子——建议独立任务处理
- skills / mcp 子模块内的清洗（P2-8）不在本批
- `chat/models.py` help_text 中的 `implementation：` 标记涉及 migration 同步，未动
