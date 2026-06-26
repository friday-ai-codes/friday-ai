# 89-04 SUMMARY — 固定格式分支名 + 卡片确认 + 逐仓建分支推送 + 绑项目（PLAN-04）

**Status:** ✅ 完成（milestone v0.16.0 Phase 89 收官 plan）
**Requirements:** PLAN-04
**Date:** 2026-06-27

## 交付内容

方案确认后逐仓**按固定格式分支名建分支推送** + **绑定 仓库↔分支↔项目**（写 `ProjectBranch`
经 `ProjectBranchService.bind(source=plan)`，Phase 85 seam），回接 IDE 闭环。分支名固定格式
`{type}/{yymmdd}.m-{项目跟踪id}.{项目名}[-{版本号}]`，AI 仅定 type/版本号 + server 权威拼装
+ 正则校验兜底 + 用户卡片确认。

## 新增文件

| 文件 | 作用 |
|------|------|
| `server/initiatives/services/branch_naming.py` | `build_branch_name`（server 权威拼装固定格式）+ `validate_branch_name`（正则）+ `generate_branch_name`（`use_call_source(BRANCH_NAMING)` LLM 仅定 type/版本号，失败兜底 feat） |
| `server/initiatives/services/branch_provision_service.py` | `BranchProvisionService.provision_and_bind`：逐仓建推（复用 CreateBranchNode local git + `aresolve_git_token` 注入 push URL）+ `ProjectBranchService.bind(source=PLAN, _skip_member_check)`；单仓 fail-soft；分支已存在幂等跳过 create |
| `server/feishu/cards/branch_confirm_card.py` | `build_branch_confirm_card`（逐仓建议分支名 + 确认/改 type/取消）+ `build_branch_done_card`（succeeded/failed + 回接 IDE 闭环提示） |
| `server/feishu/callbacks/branch_confirm_callback.py` | `@register_card_callback("branch_confirm_")` FSM：apply→provision_and_bind→approve；edit→重拼 round+1 保持 waiting；cancel→approve(cancelled) |
| `server/tests/initiatives/test_branch_naming.py` | 18 用例 |
| `server/tests/initiatives/test_branch_provision.py` | 5 用例 |
| `server/tests/feishu/test_branch_confirm_callback.py` | 12 用例 |

## 修改文件

- `server/feishu/urls.py`：import `branch_confirm_callback`（触发 `@register_card_callback` 注册）。
- `server/initiatives/services/__init__.py`：re-export `BranchProvisionService`。

## 分支名固定格式测试覆盖

- `build_branch_name(feat,260610,123456770019,高三提分专项,v1.0)` == `feat/260610.m-123456770019.高三提分专项-v1.0`（示例逐字一致）；
- 无版本号 → 省略 `-vX`；非法 type → 兜底 feat；`m-` 前缀去重；项目名段去空白/非法符号保留中文；版本号 `V2.3.1` 归一 `-v2.3.1`；
- `validate_branch_name`：示例 True；6 类非法名（type 非 conventional / 日期非 6 位 / 缺 m- / 段含空白 / 段含斜杠 / 空）全 False；
- `generate_branch_name`：LLM 定 type+版本号 server 拼；LLM 失败兜底 feat；change_type_override 跳过 LLM；项目名缺 → project.name 兜底；**id/日期 server 权威（LLM 改 id 不生效）**。

## 锁定决策落实

- **固定格式 server 权威 + AI propose + user confirm**：id/项目名/日期 server 拼，LLM 仅定 type/版本号，正则校验兜底 → 防格式漂移/注入（T-89-04-TAMPER）。
- **写收口 INV-6**：`ProjectBranch` 一律经 `ProjectBranchService.bind(source=BranchSource.PLAN)`，`test_project_branch_inv6_guard` 守护通过（无旁路写表）。
- **push token 注入 + 不入日志**：`aresolve_git_token` → `ssh_git_url_to_https` + `build_authenticated_git_url`（`oauth2:<token>@`）；日志仅 `has_git_token` 布尔（capture_logs 断言明文 token 不入日志，T-89-04-INFO）。
- **单仓 fail-soft + 幂等**：单仓建推/bind 失败隔离不阻断其余；分支已存在跳过 create 仅 bind；`bind` get_or_create 幂等。
- **观测/归因**：`branch_provision_started`/`branch_pushed`/`branch_bound`/`branch_provision_failed`/`branch_confirm_card_action`/`branch_naming_generated`（caller, component=initiatives, +duration_ms, initiated_by_user_id=callback.user_open_id / system）；异常 `redact_secrets_in_text` 脱敏；best-effort 不反噬。
- **回接 IDE 闭环**：终态卡提示绑定后分支可被 IDE rule/MCP 反查所属项目。

## 测试结果

```
tests/initiatives/test_branch_naming.py ......... (18 passed)
tests/initiatives/test_branch_provision.py ..... (5 passed)
tests/feishu/test_branch_confirm_callback.py ... (12 passed)
tests/initiatives/test_project_branch_inv6_guard.py .. (INV-6 守护通过)
tests/feishu （全量回归） 89 passed
ruff format/check + mypy（4 源文件）全绿
```

## Deferred（[ASSUMED]，记 89-UAT.md）

真机建分支推送（DATA_DIR 真仓 clone + git token + 远端可达）、push token 真鉴权落分支、远端已存在分支幂等、branch_naming 真 provider 产出质量 —— 单测以 seam/mock/respx 覆盖编排逻辑，真实 live-git/LLM 端到端 deferred。
