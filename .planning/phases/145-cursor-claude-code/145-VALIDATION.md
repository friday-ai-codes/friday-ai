---
phase: 145
slug: cursor-claude-code
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-28
---

# Phase 145 — Validation Strategy

> Cursor / Claude Code 双宿主会话采集的 Nyquist 合同。行为验收落在 IDE hook pairing → 共用 HTTP helper → `report_session_knowledge`；服务端 12 键契约冻结（Phase 142），本阶段不改 serializer。PLAN.md 落地后可改 Plan/Wave 列，**不得删除 Automated Command 或把行为改成仅人工**。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 + pytest-django + pytest-socket（`server/`，默认 `--disable-socket`）；Node 内置 `node:test` + `node:assert/strict`（`skills/` merge，**零新 npm 包**）；mcp 面既有 vitest（工具可达前置门禁） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]`；skills Wave 0 在 `skills/package.json` 增加 `"test": "node --test lib/*.test.mjs"`（无独立 vitest/jest config） |
| **Quick run command** | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_request_keys_aligned -x --tb=short` |
| **Hook behavior command** | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x --tb=short` |
| **Skills merge command** | `cd skills && node --test lib/*.test.mjs`（Wave 0 后等价于 `cd skills && npm test`） |
| **npm MCP command** | `cd mcp && npm test -- tests/server.test.ts` |
| **Full suite command** | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py tests/hooks/ -q --tb=short` 以及 `cd mcp && npm test -- tests/server.test.ts` 以及 `cd skills && node --test lib/*.test.mjs` |
| **Estimated runtime** | per-task hook/merge 窄跑 <30s；assets+snapshot quick <40s；phase full <120s（未实测，Wave 0 落地后填 Measured runtime） |

默认 `addopts` 含 `--disable-socket`。subprocess hook 使用确定性 stdlib 测试缝：`FRIDAY_CAPTURE_HTTP_RECORD=<path>` 记录成功请求；`FRIDAY_CAPTURE_HTTP_FORCE=timeout|http_error` 在发网前强制进入失败分支。未设置测试缝时才允许 `urllib.request.urlopen(timeout=10)`；测试禁止打外网。无新运行时依赖：不 `uv add`、不 `npm install`、不要求 `jq`。

### Submodule vs parent 门禁

`skills/` 是独立仓库（`.gitmodules` → `https://github.com/friday-ai-codes/skills.git`）。测试命令必须按所有者拆开，禁止在父仓 `git add skills/...` 把脏子模块当文件提交。

| Owner | What to run | Where |
|-------|-------------|--------|
| **skills submodule** | `node --test lib/*.test.mjs`；包装器由父仓 pytest 用 `bash` 执行当前 checkout 的 `skills/hooks/*`（只读） | 先在 `skills/` 内提交；`package.json` `test` 脚本不得引入新 dependency |
| **friday-ai parent** | pytest：`tests/hooks/`、`tests/initiatives/test_ide_hook_assets.py`、`test_skills_snapshot_guard.py`、schema/alignment、`test_report_session_knowledge.py`、`test_report_project_knowledge.py` | 145-01..04 禁止暂存 gitlink；145-05 仅在 child SHA 由 fetched remote advertised ref 可达后，父仓 commit 才同时含 `skills` gitlink + server 资产/守卫 |
| **mcp submodule** | `npm test -- tests/server.test.ts` | 本阶段不改 12 键；只作工具可达前置。意外改 schema 则停并回 Phase 142 |

**禁止：**145-01..04 在父仓执行 `git add skills`/`git add skills/...` 或暂存 gitlink；父仓指向未远端可达的 skills SHA；执行器自行 push（用户未授权）；server 守卫依赖工作区未提交的子模块内容；把 `session_capture.py` 复制进 `server/` 当分发源。

### Final distributed-asset operator gate

145-05 必须先 `git -C skills fetch origin --prune --tags`，再读取 `git -C skills ls-remote --heads --tags origin` 的 advertised tip SHA，并逐个用 `git -C skills merge-base --is-ancestor "$child_sha" "$tip_sha"` 验证 child SHA 可达。禁止用 `ls-remote` raw SHA pattern 充当证明。

若无 advertised ref 包含 child SHA：不暂存 gitlink、不 push，在 `145-05-SUMMARY.md` 标记 `distributed_asset_parity: blocked_on_skills_push`；不得声明 SKILL-04、ROADMAP SC3 或 Phase 145 complete。操作员将 child commit 推到远端 branch/tag 并回复后，执行器才重跑门禁。此门禁是最终真实 blocker，不因功能测试全绿而自动跳过。

### Shell / Python / Node 命令清单

```bash
# Python — 父仓行为 + 资产 + 文档守卫（--disable-socket 下 mock urlopen）
cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x --tb=short
cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x --tb=short
cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py -x --tb=short
cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py -x --tb=short

# Node — skills 子模块 merge（stdlib node:test，无新包）
cd skills && node --test lib/*.test.mjs

# Node — mcp 子模块工具可达（不扩大历史工具字段门禁）
cd mcp && npm test -- tests/server.test.ts

# Shell — 由 pytest subprocess 调用，不要单独作为 CI 入口
# bash skills/hooks/user-prompt-submit
# bash skills/hooks/stop
# bash skills/hooks/cursor/before-submit-prompt
# bash skills/hooks/cursor/after-agent-response
# python3 skills/hooks/lib/session_capture.py   # 或由 wrapper 传入 stdin JSON
```

Watch 模式禁止：不用 `pytest --looponfail`、`node --test --watch`、`vitest` 无 `run`。

---

## Sampling Rate

### Plan dependency waves

| Wave | Plan | Dependency / gate |
|------|------|-------------------|
| 0 | 145-01 | tracer RED；不得暂存父仓 skills gitlink |
| 1 | 145-02, 145-04 | 都只依赖 145-01；分别实现 helper/Claude 与 skills 文档，可并行；不得暂存父仓 gitlink |
| 2 | 145-03 | 依赖 145-01 + 145-02，共用 helper 后实现 Cursor/installer；不得暂存父仓 gitlink |
| 3 | 145-05 | 依赖 145-02 + 145-03 + 145-04；先产 server 资产，再等待 skills push 操作员门，最后才允许 gitlink |

- **After every task commit:** 该任务 `<automated>`（窄 pytest `-x` 或 `node --test` 单文件；禁止用 full suite 当 per-task 反馈）
- **After Wave 0:** 新 RED 文件 `--collect-only`；`cd skills && node --test lib/*.test.mjs`（script 落地后）；扩展后的 `test_ide_hook_assets.py` / `test_skills_snapshot_guard.py` 可 collect
- **After skills submodule commit (145-01..04):** 在 `skills/` 内 `node --test lib/*.test.mjs` 全绿；父仓 gitlink 保持未暂存
- **145-05 remote gate:** 仅 advertised-tip ancestry 证明 child SHA 远端可达后更新父仓 gitlink；否则标记 `blocked_on_skills_push`
- **After parent wave merge:** remote gate 已通过后再跑 Full suite command（server + mcp npm + skills node:test）
- **Before `$gsd-verify-work`:** Full suite 全绿；触及的生产 Python 过 ruff；`package.json` / `pyproject.toml` 无新 dependency
- **Max feedback latency:** 40 seconds（narrow per-task）；full 仅 phase gate

---

## Threat model (client / installer)

编号对应 RESEARCH Security Domain。服务端 IDOR/挂钩不在本阶段重复测（沿用 141–144）。

| ID | Pattern | Secure behavior under test |
|----|---------|----------------------------|
| T-145-01 | PAT 进 stdout/stderr/cache | 永不 print token；异常不附上游 body |
| T-145-02 | 问答正文进仓库 | pending 仅 `~/.cache`（`XDG_CACHE_HOME`）；TTL；不写 `.cursor/` / git |
| T-145-03 | Prompt 注入进 hook stdout | Cursor `beforeSubmitPrompt` 最多 `{"continue": true}`；Claude stdout 仅 lookup `additionalContext` |
| T-145-04 | 用 Cursor `stop` / `followup_message` 当答案源 | Capture 只走 `afterAgentResponse.text`；stop 脚本无 `report_session_knowledge` |
| T-145-05 | `failClosed: true` 阻断编码 | 禁止；所有路径宿主 exit 0 |
| T-145-06 | 命令注入 | JSON via stdin/argv；不用 `eval` / `os.system(prompt)` |
| T-145-07 | 错配泄漏他会话 | `conversation_id`/`session_id` + `generation_id`；不可靠则 skip |
| T-145-08 | `user_email` 入账本/日志 | 提取器忽略；POST 体无该键 |
| T-145-09 | CoT / `transcript_path` / `afterAgentThought` | 白名单字段；thinking 标签只删不补；不读 transcript 文件 |
| T-145-10 | 覆盖用户 `hooks.json` | 结构化 merge；非法 JSON 原文件不变 |

---

## Per-Task Verification Map

Plan/Wave 列标记行为的实现 owner；所有缺失测试仍由 145-01 / Wave 0 tracer 先创建（文件可先不存在，标 ❌ W0）。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 145-01-01 | 02 | 1 | SKILL-01 | T-145-07 | Claude：`UserPromptSubmit.prompt` + `Stop.last_assistant_message` 配对后 POST，`question`/`answer` 非空、`client=claude_code`；不读 `transcript_path` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_user_prompt_submit_caches_prompt tests/hooks/test_session_capture_hooks.py::test_claude_stop_posts_visible_answer_on_clean_tree -x` | ❌ W0 | ⬜ pending |
| 145-01-02 | 03 | 2 | SKILL-01 | T-145-07 | Cursor：`beforeSubmitPrompt.prompt` + `afterAgentResponse.text` 走**同一** helper，`client=cursor`；session 优先 `conversation_id` 再 `session_id` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_cursor_hooks_pair_visible_answer -x` | ❌ W0 | ⬜ pending |
| 145-01-03 | 02 | 1 | SKILL-01 | T-145-08 | 共用 POST 体：必填 `question`/`answer`；可选 `git_url`/`branch_name`/`session_id`/`response_model`/`client`；**不**传 `project_id`/`repository_id`/`user_email` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_helper_builds_shared_payload -x` | ❌ W0 | ⬜ pending |
| 145-02-01 | 02 | 1 | SKILL-02 | — | clean git tree（无 `diff --stat`）仍 POST Capture；无 git 仓时 `git_url`/`branch_name` 为空仍 POST | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_stop_posts_visible_answer_on_clean_tree -x` | ❌ W0 | ⬜ pending |
| 145-02-02 | 02 | 1 | SKILL-02 | — | dirty tree 仍 POST Capture；`report_project_knowledge` **仅** dirty 且保持原 empty-diff skip；Capture 路径不得调用 `fail_soft()` 提前退出整个 Stop | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_stop_preserves_project_memory_gate_on_dirty_tree -x` | ❌ W0 | ⬜ pending |
| 145-03-01 | 05 | 3 | SKILL-03 | T-145-04 / T-145-09 | Claude by_path 含真实 UserPromptSubmit-cache + Stop-Capture 脚本；答案字段仅 `last_assistant_message`；重复 Stop 不二次 POST | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_stop_posts_visible_answer_on_clean_tree tests/initiatives/test_ide_hook_assets.py -x` | ❌ W0 / ✅ 需扩展 | ⬜ pending |
| 145-03-02 | 05 | 3 | SKILL-03 | T-145-04 | Cursor 配置含 `beforeSubmitPrompt` + `afterAgentResponse`；**无** `afterAgentThought`；Capture **不**用 `stop` | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-03-03 | 05 | 3 | SKILL-03 | T-145-03 / T-145-04 | Cursor/Claude `friday-stop-writeback.sh` **无** `question`、`answer`、`last_assistant_message`、`report_session_knowledge`、`hookSpecificOutput`、`additionalContext` | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-03-04 | 03 | 2 | SKILL-03 | T-145-03 | Cursor `beforeSubmitPrompt` stdout 不含 `additionalContext`；Claude UserPromptSubmit stdout 不含 pending 路径 / prompt / Bearer | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_hook_outputs_do_not_leak_sensitive_values -x` | ❌ W0 | ⬜ pending |
| 145-04-01 | 02 | 1 | SKILL-04 | T-145-09 | 答案不含 thinking 块内容；`<thinking>`/`<thought>` 删除后若空则 skip POST；fixture 含 `transcript_path` 也不打开该文件；无 `afterAgentThought` 字段读取 | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_stop_strips_thinking_and_ignores_transcript -x` | ❌ W0 | ⬜ pending |
| 145-04-02 | 02 | 1 | SKILL-04 | T-145-01 / T-145-02 | stdout/stderr/cache **文件名**不含 PAT；stdout 不含 prompt/answer；pending 权限 `0600`；成功消费 pending，失败保留有界可重试 | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_hook_outputs_do_not_leak_sensitive_values tests/hooks/test_session_capture_hooks.py::test_claude_stop_fail_soft_modes_keep_pending -x` | ❌ W0 | ⬜ pending |
| 145-04-03 | 04 | 1 | SKILL-04 | — | friday / friday-dev / friday-memory 主文 + http-fallback **同时**出现 `report_session_knowledge` 与 `report_project_knowledge`；写明 clean tree 仍收集问答、只取可见最终答案、不上传 transcript/CoT/凭证；两工具职责不合并 | unit | `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-04-04 | 05 | 3 | SKILL-04 | T-145-04 | `ide_hook_assets` by_path 含 Cursor before/after 与 Claude UPS-cache/Stop-Capture 实体脚本；project-memory stop 隔离且无 Capture 字段 | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-05-01 | 03 | 2 | SKILL-05 | T-145-10 | `mergeCursorHooksConfig`：`version: 1`；保留未知顶级键、用户 `beforeSubmitPrompt`/`stop`/其他事件；Friday basename 去重升级；重复安装 deepEqual；project vs global command 路径不同 | unit | `cd skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-05-02 | 03 | 2 | SKILL-05 | T-145-10 | 非法 JSON：原文件 bytes 不变 + 可操作 warning；**不**写 `{}` | unit | `cd skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-05-03 | 02 | 1 | SKILL-05 | T-145-01 / T-145-05 | 缺 PAT/URL、`FRIDAY_CAPTURE_HTTP_FORCE=timeout/http_error`、JSON 错误、文件锁失败 → 不打外网、宿主 returncode 0、不消费 pending、无 `failClosed: true` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py::test_claude_stop_fail_soft_modes_keep_pending -x` | ❌ W0 | ⬜ pending |
| 145-05-04 | 05 | 3 | SKILL-05 | — | 无新依赖：`skills/package.json` / `server/pyproject.toml` / `mcp/package.json` 相对本阶段基线无新增 runtime dep；测试仅 `node:test` + pytest；hooks 只用 bash/git/curl/python3 stdlib | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py tests/mcp_tools/test_skills_snapshot_guard.py -x && cd ../skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-06-01 | 05 | 3 | MCP-03 延续 | — | 文档引用 `report_session_knowledge` ⊆ `TOOL_SCHEMA_SNAPSHOT`；三面 12 键不变 | unit | `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot -x` | ✅ | ⬜ pending |
| 145-06-02 | 05 | 3 | MCP-04 | — | `report_project_knowledge` 零回归（empty-diff skip 仍在项目记忆路径） | unit | `cd server && uv run pytest tests/mcp_tools/test_report_project_knowledge.py -x` | ✅ | ⬜ pending |
| 145-07-01 | 05 | 3 | SKILL-04 / SC3 | T-145-SC | skills child SHA 必须由 fetched remote advertised ref 可达；否则 distributed_asset_parity=blocked_on_skills_push，父仓不暂存 gitlink且 Phase 不完成 | operator + automated gate | 145-05 Task 2/3 advertised-tip ancestry check | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Nyquist 连续性：上表无连续 3 个任务缺少 automated command。Wave 0 文件未落地前 File Exists=❌ W0，实现任务依赖这些 tracer。

---

## Wave 0 Requirements

- [ ] `server/tests/hooks/conftest.py` — `tmp_path` 作 `XDG_CACHE_HOME`；临时 git 仓（dirty/clean/无仓库）；`FRIDAY_CAPTURE_HTTP_RECORD` 记录成功 POST；`FRIDAY_CAPTURE_HTTP_FORCE=timeout|http_error` 确定性失败且不发网；`subprocess.run(["bash", hook], input=json.dumps(event), env=..., capture_output=True)` 跑真实 wrapper
- [ ] `server/tests/hooks/test_session_capture_hooks.py` — stdin fixtures 覆盖：
  - Claude `UserPromptSubmit` + `Stop.last_assistant_message` → POST `client=claude_code`
  - Cursor `beforeSubmitPrompt` + `afterAgentResponse.text` → 同 helper、`client=cursor`
  - dirty **与** clean tree 均 POST Capture；仅 dirty 触发 project knowledge
  - 无 git、缺 PAT、force timeout、force http_error、非法 stdin JSON、空/`missing` `last_assistant_message`/`text`、重复 Stop/after、`stop_hook_active=true`、generation 错配 / 多 pending 无 generation → skip 且 returncode 0
  - thinking 标签剥离；剥离后空白 skip；`transcript_path` 存在但不被读取
  - stdout/stderr 无 PAT/prompt/answer/上游 body；cache 文件名无 token
  - 成功消费 pending；失败保留 bounded pending + TTL
- [ ] `skills/lib/cursor-hooks-merge.test.mjs` — 空/缺失文件生成 v1；保留未知顶级键与用户 hooks；basename 去重与升级；两次安装幂等；project/global command 不同；非法 JSON bytes 不变 + warning；**无** `failClosed: true`
- [ ] `skills/package.json` — `"test": "node --test lib/*.test.mjs"`；**不**增加 `dependencies` / `devDependencies`
- [ ] 扩展 `server/tests/initiatives/test_ide_hook_assets.py` — 用 `by_path` 断言 Cursor 有 before/after；Claude 真实含 `.claude/hooks/friday-session-capture-user-prompt-submit.sh` 与 `.claude/hooks/friday-session-capture-stop.sh`，settings 注册相同路径；Claude/Cursor `.cursor|.claude/hooks/friday-stop-writeback.sh` 仅 project memory/STATE 且无 `question`/`answer`/`last_assistant_message`/`report_session_knowledge`；无 `afterAgentThought`；Capture 不以 `diff --stat` 为门闩；Codex 零回归
- [ ] 扩展 `server/tests/mcp_tools/test_skills_snapshot_guard.py` — friday / friday-dev / friday-memory（及 http-fallback）职责分离短语 + 工具 token ⊆ snapshot
- [ ] Framework install: 无 — 已有 pytest；Node `node:test` 随 Node ≥20；不装 jq/axios/vitest-in-skills

既有 `mcp_client` 不用于 hook 进程测试。会话 Capture 必须委托同一 `session_capture` helper，禁止 Claude/Cursor 各写一套 POST 体。

---

## Manual-Only Verifications

除 skills child commit 发布到远端 ref 这一操作员动作外，所有功能行为均有自动化验证。

真实 IDE 点一次安装/一轮问答可作为执行后 smoke，**不是** Nyquist 门禁。skills push 是不同性质的分发可达性硬门：用户未授权执行器 push；未推送时 `distributed_asset_parity=blocked_on_skills_push`，不得将 `nyquist_compliant`、SKILL-04/SC3 或 Phase 145 标完成。CONTEXT 所述 E2E fixture由上表 Wave 0 自动化覆盖。

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verification
- [ ] Wave 0 covers all missing references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s for per-task commands
- [ ] 145-01..04 父仓未暂存 skills gitlink
- [ ] skills child SHA 经 fetch + advertised-tip ancestry 验证远端可达；否则 `distributed_asset_parity: blocked_on_skills_push`
- [ ] remote gate 通过后 submodule (`skills` node:test) 与 parent (pytest + gitlink) 均绿
- [ ] `nyquist_compliant: true` set in frontmatter **only after** Wave 0 files exist and phase tasks are green（当前 draft / false）

**Approval:** pending
