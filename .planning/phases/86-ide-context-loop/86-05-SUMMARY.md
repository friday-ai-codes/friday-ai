# 86-05 SUMMARY —— 三家 stop hook 写路径资产（默认开启 + 静默 active 回写）

**Plan:** 86-05（Phase 86 IDE 上下文闭环，wave 3，HOOK-02/03 客户端半）
**Status:** ✅ Done
**Date:** 2026-06-27

## 交付物

### 新增方法 `build_write_path_assets(project, runtime)`（`server/initiatives/services/ide_hook_assets.py`）
与 `build_read_path_assets` 对称，返回 `{"runtime", "kind": "write", "files": [...], "notes"}`，三家 stop hook 写路径资产：

- **cursor**：`.cursor/hooks.json`（注册 `stop` 钩子）+ `.cursor/hooks/friday-stop-writeback.sh`。
- **claude_code**：`.claude/settings.json`（注册 `Stop` hook）+ `.claude/hooks/friday-stop-writeback.sh`。
- **codex**：仅产**可手动执行 / CI 兜底**的 `scripts/friday-stop-writeback.sh`，`notes` 标注「Codex 原生 hook 能力弱，按仅 MCP + rules 对待」（对齐 CONTEXT deferred）。

stop 脚本行为（默认开启 + 静默）：会话结束收集「本次上下文 + git 改动摘要」→ 调 `report_project_knowledge(writeback_mode="active", target="memory")` 直写 MEMORY；可选经 `FRIDAY_STATE_APIS_FILE` 提供结构化清单 → 调 `report_project_state` 回写 STATE。脚本不内嵌密钥（PAT 经 `FRIDAY_PAT` 环境变量），正文显式写明：① 三道兜底由服务端保证（质量门槛 / 脱敏 / 审计回滚）；② 绝不上报凭证/密钥/token；③ 无 PAT / 未绑项目 / 接口非 2xx / 任何异常 → 静默 `exit 0`，绝不弹窗或阻断编码（默认开关 `FRIDAY_STOP_WRITEBACK`，默认开启）。

### 端点 `kind=write` 下发（`server/initiatives/views.py` + `serializers.py`）
- `IdeHookAssetsQuerySerializer.kind` 扩 `["read", "write"]`（默认 `read`，向后兼容）。
- `ProjectIdeHookAssetsView` 按 `kind` 分流：`write` → `build_write_path_assets`，否则 `build_read_path_assets`。读权限口径不变（写路径资产是安装说明文本、不执行写，按项目读口径 fail-closed 下发；非成员 403）。

### cursor_rules 措辞同步 active（accepted deviation，`server/initiatives/services/cursor_rules.py`）
第 3 步「上报沉淀」由「落 **草稿** 人工确认入库」改为「经脱敏 + 质量门槛 + 审计可回滚后**直接写入生效（active）**，无需人工确认；非成员 / 无 PAT / 未绑项目静默跳过」，与 86-01 服务端行为一致。文件名 / frontmatter / 其余结构不变（前端 cursor-rules 端点不破）。

## 测试结果

`uv run pytest tests/initiatives/test_ide_hook_assets.py tests/initiatives/test_cursor_rules.py -q` → **32 passed**。

新增/改动用例：
- 写路径 cursor / claude_code / codex 资产内容（hooks.json/settings.json 注册 + 脚本含 `report_project_knowledge`(active) + `report_project_state` + `exit 0` + PAT 不内嵌）。
- 默认开启 + 静默 + 三道兜底 + 脱敏告诫（三家参数化）。
- 端点 `kind=write&runtime=cursor|claude_code|codex` 取写路径 bundle（200）；非法 `kind` → 400；非成员 → 403。
- cursor_rules active 措辞断言（含 `active` / `无需人工确认` / `审计可回滚` / `静默跳过`，无 `草稿`）。

`uv run ruff check`（6 个改动文件）→ All checks passed。

## LOCKED 决策落实
- stop hook 默认开启 + 静默 active 直写（user-authorized deviation 2026-06-26）✅
- 3-runtime 资产经同一 `ide-hook-assets` 端点 `kind=write` 下发 ✅
- 无 PAT / 未绑 / 失败 → 静默 exit 0，绝不 block 编码 ✅
- cursor_rules 措辞同步 active ✅
- 复用 86-01/03/04 端点 + ide_hook_assets.py（未重造）✅

## Deferred / Blockers
- Codex 原生 stop hook 自动注入：能力弱，本期仅产手动 / CI 脚本（CONTEXT deferred「Codex 原生 hook 按仅 MCP + rules 对待」）。
- STATE 结构化 API 清单的**自动提取**（从 diff 解析新增/改动 API）未做：脚本以 `FRIDAY_STATE_APIS_FILE` 显式提供为准，无文件则静默跳过 STATE 回写。
