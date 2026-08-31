---
phase: 145-cursor-claude-code
verified: 2026-08-31T06:58:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 1
human_verification:
  - test: "本机安装 Friday skills 后，在 Cursor 与 Claude Code 各做一轮问答，工作区保持 clean git tree"
    expected: "本轮问题与可见最终答案写入 SessionCapture；编码不被阻断；Cursor stop 不注入 Claude additionalContext"
    why_human: "真实宿主事件载荷、安装路径与控制台下载资产无法在本机 IDE 外端到端观测；PLAN 145-05 将其标为可选事后 smoke，非 Nyquist 门禁"
    result: deferred_advisory
    note: "自动化 6/6 已过；可选 IDE smoke 不阻断 Nyquist/阶段完成。里程碑收尾按用户「完全跑完」意图继续。"
---

# Phase 145: Cursor / Claude Code 双宿主采集 Verification Report

**Phase Goal:** Cursor 与 Claude Code 都能在不阻断编码的前提下自动抽取本轮问题和可见答案精华并回写 Capture
**Verified:** 2026-08-31T06:58:00Z
**Status:** passed
**Re-verification:** No — initial verification

自动化 must-have 全部 VERIFIED（6/6）。未发现 BLOCKER。可选真实 IDE smoke（非 Nyquist）记为 deferred_advisory，不阻断阶段完成。

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | Claude Code 经 `UserPromptSubmit` 缓存问题，并以 `Stop.last_assistant_message` 提取可见答案；Cursor 经 `beforeSubmitPrompt` 缓存、`afterAgentResponse.text` 配对 | ✓ VERIFIED | `skills/hooks/user-prompt-submit` 先调 `session_capture.py cache claude_code`；`skills/hooks/stop` 先 `submit claude_code`。Helper 对 `claude_code` 读 `last_assistant_message`、对 `cursor` 读 `text`。Cursor wrappers 只走 before/after。pytest `test_claude_user_prompt_submit_caches_prompt` / `test_claude_stop_posts_visible_answer_on_clean_tree` / `test_cursor_hooks_pair_visible_answer` 通过 |
| 2 | 工作区无 git 改动或没有 `diff --stat` 时，零散问答仍调用 `report_session_knowledge` | ✓ VERIFIED | `submit_visible_answer` 无 git-diff 门闩。`stop` 在 Capture 之后才对项目记忆做 empty-diff `fail_soft()`。`test_claude_stop_posts_visible_answer_on_clean_tree` 与 `test_claude_stop_preserves_project_memory_gate_on_dirty_tree`：clean/dirty/no_git 共 3 次 Capture，仅 dirty 一次 `report_project_knowledge` |
| 3 | 客户端只提交问题与可见答案精华，不上传隐藏思维链；skills、HTTP fallback、`ide_hook_assets` 与 snapshot 守卫一致 | ✓ VERIFIED | Helper 剥离 `<thinking>`/`<thought>`，从不打开 `transcript_path`。Cursor 事件含 `afterAgentThought` 时答案仍仅为 `text`。文档五份均含双工具 + clean tree + 可见最终答案 + transcript/隐藏思维链。`test_skills_snapshot_guard.py` 与 `test_ide_hook_assets.py` 通过 |
| 4 | 安装器可 merge Cursor `hooks.json`（`version: 1`）且不覆盖既有 hook；缺 PAT、接口失败或超时 fail-soft，不阻断编码 | ✓ VERIFIED | `mergeCursorHooksConfig` 保留未知顶级键、用户 `stop`/其他事件，按 command basename 去重升级，不设 `failClosed`。非法 JSON 原 bytes 不变。`_post` 缺凭证/`FORCE=timeout|http_error`/非 2xx 返回 False 且 `_main` 恒 exit 0。`node --test` 6 passed；`test_claude_stop_fail_soft_modes_keep_pending` 保留 3 条 pending |
| 5 | Claude Code 专属注入脚本不会被复制到 Cursor `stop`；两宿主 hook 资产与官方事件模型一致 | ✓ VERIFIED | `_claude_inject_script` 仅出现在 Claude 读路径 `friday-context-inject.sh`。Cursor 写路径 `friday-stop-writeback.sh` 无 `report_session_knowledge` / `last_assistant_message` / `hookSpecificOutput` / `additionalContext`。Cursor Capture 走 before/after；Claude Capture 为 UPS + Stop 实体脚本 + 隔离的 project-memory stop |
| 6 | `distributed_asset_parity=complete`：父仓 skills gitlink 为远端 advertised `origin/main` 可达的 `c3ed7bb` | ✓ VERIFIED | 本机复核：`git ls-tree HEAD skills` → `160000 commit c3ed7bb40b3774213f121f020e98d029aab10221`；`git -C skills ls-remote --heads origin` 的 `refs/heads/main` 同 SHA；`merge-base --is-ancestor` PASS。145-05-SUMMARY 声称与代码/远端一致 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `skills/hooks/lib/session_capture.py` | 共用配对/精华/POST/TTL/HTTP seam | ✓ VERIFIED | 328 行 stdlib；`cache_user_prompt` + `submit_visible_answer`；POST `/api/mcp/tools/report_session_knowledge/`；白名单键无 `project_id`/`user_email` |
| `skills/hooks/user-prompt-submit` | UPS 缓存 prompt 后 lookup | ✓ VERIFIED | cache 在 lookup 之前；stdout 仅 `hookSpecificOutput.additionalContext` |
| `skills/hooks/stop` | Capture 与 project-memory 分轨 | ✓ VERIFIED | Capture 先跑；`FRIDAY_STOP_WRITEBACK=0` 只跳过项目记忆；empty-diff 只跳过后者 |
| `skills/hooks/cursor/before-submit-prompt` | Cursor 问题缓存 | ✓ VERIFIED | `cache cursor`；stdout `{"continue":true}`；无 `additionalContext` |
| `skills/hooks/cursor/after-agent-response` | Cursor 可见答案 | ✓ VERIFIED | `submit cursor`；exit 0 |
| `skills/hooks/cursor/hooks.json` | v1 before/after | ✓ VERIFIED | 无 `afterAgentThought`；无 stop（安装器保留用户 stop） |
| `skills/lib/installer.mjs` | mergeCursorHooksConfig + 安装 | ✓ VERIFIED | 导出 merge/write；`installCursorHooks` 拷 wrapper + `.cursor/lib/session_capture.py`；`performInstall` 仅 cursor 调用 |
| `skills/skills/friday{,-dev,-memory}/**` | 双工具文案 | ✓ VERIFIED | 主文 + http-fallback 职责不合并 |
| `server/initiatives/services/ide_hook_assets.py` | by_path Capture 资产 | ✓ VERIFIED | Cursor before/after + 隔离 stop；Claude UPS/Stop Capture 实体文件 + settings 真实路径 |
| `server/tests/hooks/test_session_capture_hooks.py` | 行为合同 | ✓ VERIFIED | 10 个测试函数覆盖配对、clean-tree、fail-soft、CoT、泄漏 |
| `skills/lib/cursor-hooks-merge.test.mjs` | merge/幂等/非法 JSON | ✓ VERIFIED | 含 B-1 安装布局与 wrapper e2e pending |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `skills/hooks/stop` | `session_capture.py` | `submit claude_code` + `last_assistant_message` | WIRED | stop 第 24–25 行 |
| `session_capture.py` | `/api/mcp/tools/report_session_knowledge/` | urllib 或 `FRIDAY_CAPTURE_HTTP_RECORD` | WIRED | `_post`；pytest 记录到 JSONL |
| `cursor/after-agent-response` | `session_capture.py` | `submit cursor` | WIRED | `../lib/session_capture.py`；安装后 `.cursor/lib/` |
| `friday-ai-skills.mjs` | `installer.mjs` | `installCursorHooks` when `agent.id === 'cursor'` | WIRED | 第 138–139 行 |
| `ide_hook_assets.py` | Capture 不变量 | 内嵌脚本非 import skills | WIRED | `_session_capture_script`；测试 by_path 断言 |
| snapshot guard | `skills/skills` | gitlink checkout 文档 | WIRED | 当前 HEAD 即 `c3ed7bb` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `session_capture.py` | `body.question/answer` | pending JSON + `last_assistant_message`/`text` | RECORD seam 写入真实 POST body；非空断言 | ✓ FLOWING |
| Cursor/Claude wrappers | stdin event JSON | 宿主 hook stdin | pytest `run_hook` 注入官方字段 | ✓ FLOWING |
| `ide_hook_assets` write bundle | `files[].content` | `build_write_path_assets` | 生成器产出可执行脚本与 v1 JSON，非空 notes | ✓ FLOWING |
| skills 文档 | 工具名短语 | 手写 SKILL/http-fallback | snapshot 守卫闭集 | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Hook + assets + snapshot + 12 键 + MCP 回归 | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py tests/initiatives/test_ide_hook_assets.py tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_request_keys_aligned tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py -q --tb=short` | **82 passed** in 143s | ✓ PASS |
| Cursor hooks merge | `cd skills && node --test lib/*.test.mjs` | **6 passed** | ✓ PASS |
| skills gitlink ancestry | `git -C skills fetch` + `ls-remote --heads --tags origin` + `merge-base --is-ancestor` | child=`c3ed7bb40…` is `refs/heads/main` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| n/a | Phase 未声明 `scripts/*/tests/probe-*.sh` | — | SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| SKILL-01 | 145-01..03 | 抽取本轮问答并调用 `report_session_knowledge` | ✓ SATISFIED | 双宿主 wrappers + 共用 helper + pytest |
| SKILL-02 | 145-02 | clean tree 仍 Capture | ✓ SATISFIED | Capture 无 diff 门闩；项目记忆仍 empty-diff skip |
| SKILL-03 | 145-02/03/05 | Claude UPS+Stop；Cursor before/after；禁止 Claude 注入进 Cursor stop | ✓ SATISFIED | hooks.json 事件；ide_hook_assets by_path |
| SKILL-04 | 145-02/04/05 | 不上报 CoT；文档/HTTP/资产/snapshot 一致 | ✓ SATISFIED | strip thinking；snapshot required_terms；gitlink 文档面 |
| SKILL-05 | 145-03/02 | hooks.json v1 merge；缺 PAT/失败 fail-soft | ✓ SATISFIED | installer + node:test；FORCE/缺凭证 exit 0 |
| MCP-03 延续 | 145-05 | 12 键与 snapshot | ✓ SATISFIED | `test_report_session_knowledge_request_keys_aligned` + schema snapshot |
| MCP-04 | 145-05 | `report_project_knowledge` 零回归 | ✓ SATISFIED | 15 项在联合 pytest 中通过 |

无 REQUIREMENTS.md 映射到 Phase 145 却未被计划声明的孤儿需求。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 修改面无 `TBD`/`FIXME`/`XXX` | — | 无债务标记门 |
| `ide_hook_assets._session_capture_script` | ~437+ | 与 skills helper 逻辑复制而非 import | ℹ️ Info | PATTERNS 明确禁止 runtime import skills；靠测试锁不变量 |
| `ide_hook_assets._stop_writeback_script` | 370 | `git diff --stat` | ℹ️ Info | 仅 project-memory 路径；Capture 脚本不含此门闩 |
| Wave 0 SUMMARY | frontmatter | `requirements-completed: SKILL-01..05` 在仅有 RED 测试时声明 | ℹ️ Info | 后续 02–05 已实现；不构成当前缺口 |

**Inversion（未构成 FAIL）：** 服务端下载资产内嵌脚本没有 `FRIDAY_CAPTURE_HTTP_*` 测试缝，行为由字符串不变量测试覆盖而非 subprocess；与 skills 运行时路径分离是计划内的。`pending-*.json` 文件名用 session+generation+question 哈希，而非 PLAN 草稿中的 `pending-{session_hash}-{generation}`，仍 0600 且不含 token。

**Confirmation bias 抽查：** (1) 文档「clean tree」是短语守卫而非运行时；(2) `FORCE=timeout` 在发网前 `return False`，不抛真实 `TimeoutError`，但 fail-soft 与「不打外网」合同仍成立；(3) write API 测试 `test_endpoint_kind_write_returns_stop_hook` 只断言 blob 含项目记忆工具，Cursor before/after 由同文件的 `test_write_path_cursor_stop_hook` 覆盖。

### Human Verification Required

### 1. 真实 IDE 安装与 clean-tree 一轮问答

**Test:** 本机安装 Friday skills 后，在 Cursor 与 Claude Code 各做一轮问答，工作区保持干净 git 树。
**Expected:** 产生 SessionCapture；宿主不阻断；Cursor `stop` 不出现 Claude `additionalContext` 注入。
**Why human:** 官方 hook stdin 形状、用户已有 `hooks.json`、控制台下载资产落盘路径无法在 CI subprocess 中完全复现。VALIDATION 与 145-05 PLAN 将其标为可选 smoke，**不是** Nyquist 门禁。

### Gaps Summary

无自动化缺口。`distributed_asset_parity` 已在远端 `origin/main` = `c3ed7bb` 上核实。Phase 目标在代码与测试中成立；剩余仅真实宿主 smoke。

---

_Verified: 2026-08-31T06:58:00Z_
_Verifier: Claude (gsd-verifier)_
