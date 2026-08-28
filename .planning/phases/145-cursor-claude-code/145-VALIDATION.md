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

默认 `addopts` 含 `--disable-socket`。Hook HTTP **必须** `unittest.mock.patch("urllib.request.urlopen")` 或等价可注入 transport，禁止打外网。无新运行时依赖：不 `uv add`、不 `npm install`、不要求 `jq`。

### Submodule vs parent 门禁

`skills/` 是独立仓库（`.gitmodules` → `https://github.com/friday-ai-codes/skills.git`）。测试命令必须按所有者拆开，禁止在父仓 `git add skills/...` 把脏子模块当文件提交。

| Owner | What to run | Where |
|-------|-------------|--------|
| **skills submodule** | `node --test lib/*.test.mjs`；包装器由父仓 pytest 用 `bash` 执行当前 checkout 的 `skills/hooks/*`（只读） | 先在 `skills/` 内提交；`package.json` `test` 脚本不得引入新 dependency |
| **friday-ai parent** | pytest：`tests/hooks/`、`tests/initiatives/test_ide_hook_assets.py`、`test_skills_snapshot_guard.py`、schema/alignment、`test_report_session_knowledge.py`、`test_report_project_knowledge.py` | 同一父仓 commit 必须同时含 `skills` gitlink SHA + server 资产/守卫；snapshot 读 checkout 下 `skills/skills/*` |
| **mcp submodule** | `npm test -- tests/server.test.ts` | 本阶段不改 12 键；只作工具可达前置。意外改 schema 则停并回 Phase 142 |

**禁止：**父仓先指向未 push 的 skills SHA；server 守卫依赖工作区未提交的子模块内容；把 `session_capture.py` 复制进 `server/` 当分发源。

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

- **After every task commit:** 该任务 `<automated>`（窄 pytest `-x` 或 `node --test` 单文件；禁止用 full suite 当 per-task 反馈）
- **After Wave 0:** 新 RED 文件 `--collect-only`；`cd skills && node --test lib/*.test.mjs`（script 落地后）；扩展后的 `test_ide_hook_assets.py` / `test_skills_snapshot_guard.py` 可 collect
- **After skills submodule commit:** 在 `skills/` 内 `node --test lib/*.test.mjs` 全绿，再更新父仓 gitlink
- **After parent wave merge:** Full suite command（server + mcp npm + skills node:test）
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

Plan 列在计划落地前按需求簇占位为 `01`。Wave `0` = tracer RED（文件可先不存在，标 ❌ W0）。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 145-01-01 | 01 | 0 | SKILL-01 | T-145-07 | Claude：`UserPromptSubmit.prompt` + `Stop.last_assistant_message` 配对后 POST，`question`/`answer` 非空、`client=claude_code`；不读 `transcript_path` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-01-02 | 01 | 0 | SKILL-01 | T-145-07 | Cursor：`beforeSubmitPrompt.prompt` + `afterAgentResponse.text` 走**同一** helper，`client=cursor`；session 优先 `conversation_id` 再 `session_id` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-01-03 | 01 | 0 | SKILL-01 | T-145-08 | 共用 POST 体：必填 `question`/`answer`；可选 `git_url`/`branch_name`/`session_id`/`response_model`/`client`；**不**传 `project_id`/`repository_id`/`user_email` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-02-01 | 01 | 0 | SKILL-02 | — | clean git tree（无 `diff --stat`）仍 POST Capture；无 git 仓时 `git_url`/`branch_name` 为空仍 POST | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-02-02 | 01 | 0 | SKILL-02 | — | dirty tree 仍 POST Capture；`report_project_knowledge` **仅** dirty 且保持原 empty-diff skip；Capture 路径不得调用 `fail_soft()` 提前退出整个 Stop | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-03-01 | 01 | 0 | SKILL-03 | T-145-04 / T-145-09 | Claude 资产保留 `UserPromptSubmit` + `Stop`；Stop 答案字段仅为 `last_assistant_message`；`stop_hook_active=true`、空答案、重复 Stop 不二次 POST | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py tests/initiatives/test_ide_hook_assets.py -x` | ❌ W0 / ✅ 需扩展 | ⬜ pending |
| 145-03-02 | 01 | 0 | SKILL-03 | T-145-04 | Cursor 配置含 `beforeSubmitPrompt` + `afterAgentResponse`；**无** `afterAgentThought`；Capture **不**用 `stop` | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-03-03 | 01 | 0 | SKILL-03 | T-145-03 / T-145-04 | Cursor `stop` / `friday-stop-writeback.sh` **无** `last_assistant_message`、`report_session_knowledge`、`hookSpecificOutput`、`additionalContext`（禁止 Claude inject 进 Cursor stop） | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-03-04 | 01 | 0 | SKILL-03 | T-145-03 | Cursor `beforeSubmitPrompt` stdout 不含 `additionalContext`；Claude UserPromptSubmit stdout 不含 pending 路径 / prompt / Bearer | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-04-01 | 01 | 0 | SKILL-04 | T-145-09 | 答案不含 thinking 块内容；`<thinking>`/`<thought>` 删除后若空则 skip POST；fixture 含 `transcript_path` 也不打开该文件；无 `afterAgentThought` 字段读取 | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-04-02 | 01 | 0 | SKILL-04 | T-145-01 / T-145-02 | stdout/stderr/cache **文件名**不含 PAT；stdout 不含 prompt/answer；pending 权限 `0600`；成功消费 pending，失败保留有界可重试 | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-04-03 | 01 | 0 | SKILL-04 | — | friday / friday-dev / friday-memory 主文 + http-fallback **同时**出现 `report_session_knowledge` 与 `report_project_knowledge`；写明 clean tree 仍收集问答、只取可见最终答案、不上传 transcript/CoT/凭证；两工具职责不合并 | unit | `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-04-04 | 01 | 0 | SKILL-04 | T-145-04 | `ide_hook_assets` 与实体 skills hooks **事件/字段/路径/安全不变量**对齐：Cursor 采集走 before/after；Claude 走 UserPromptSubmit/Stop；Capture 脚本含 `report_session_knowledge`、短 timeout、`exit 0`；**非** byte-for-byte 脚本拷贝 | unit | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 | ⬜ pending |
| 145-05-01 | 01 | 0 | SKILL-05 | T-145-10 | `mergeCursorHooksConfig`：`version: 1`；保留未知顶级键、用户 `beforeSubmitPrompt`/`stop`/其他事件；Friday basename 去重升级；重复安装 deepEqual；project vs global command 路径不同 | unit | `cd skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-05-02 | 01 | 0 | SKILL-05 | T-145-10 | 非法 JSON：原文件 bytes 不变 + 可操作 warning；**不**写 `{}` | unit | `cd skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-05-03 | 01 | 0 | SKILL-05 | T-145-01 / T-145-05 | 缺 PAT/URL、`urlopen` 超时/非 2xx/JSON 错误、文件锁失败 → 宿主 returncode 0；不消费 pending；无 `failClosed: true` | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ W0 | ⬜ pending |
| 145-05-04 | 01 | 0 | SKILL-05 | — | 无新依赖：`skills/package.json` / `server/pyproject.toml` / `mcp/package.json` 相对本阶段基线无新增 runtime dep；测试仅 `node:test` + pytest；hooks 只用 bash/git/curl/python3 stdlib | unit | `cd server && uv run pytest tests/hooks/test_session_capture_hooks.py tests/mcp_tools/test_skills_snapshot_guard.py -x && cd ../skills && node --test lib/*.test.mjs` | ❌ W0 | ⬜ pending |
| 145-06-01 | 01 | 0 | MCP-03 延续 | — | 文档引用 `report_session_knowledge` ⊆ `TOOL_SCHEMA_SNAPSHOT`；三面 12 键不变 | unit | `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot -x` | ✅ | ⬜ pending |
| 145-06-02 | 01 | 0 | MCP-04 | — | `report_project_knowledge` 零回归（empty-diff skip 仍在项目记忆路径） | unit | `cd server && uv run pytest tests/mcp_tools/test_report_project_knowledge.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Nyquist 连续性：上表无连续 3 个任务缺少 automated command。Wave 0 文件未落地前 File Exists=❌ W0，实现任务依赖这些 tracer。

---

## Wave 0 Requirements

- [ ] `server/tests/hooks/conftest.py` — `tmp_path` 作 `XDG_CACHE_HOME`；临时 git 仓（dirty/clean/无仓库）；`patch("urllib.request.urlopen")`；`subprocess.run(["bash", hook], input=json.dumps(event), env=..., capture_output=True)` 跑真实 wrapper
- [ ] `server/tests/hooks/test_session_capture_hooks.py` — stdin fixtures 覆盖：
  - Claude `UserPromptSubmit` + `Stop.last_assistant_message` → POST `client=claude_code`
  - Cursor `beforeSubmitPrompt` + `afterAgentResponse.text` → 同 helper、`client=cursor`
  - dirty **与** clean tree 均 POST Capture；仅 dirty 触发 project knowledge
  - 无 git、缺 PAT、网络失败、非法 stdin JSON、空/`missing` `last_assistant_message`/`text`、重复 Stop/after、`stop_hook_active=true`、generation 错配 / 多 pending 无 generation → skip 且 returncode 0
  - thinking 标签剥离；剥离后空白 skip；`transcript_path` 存在但不被读取
  - stdout/stderr 无 PAT/prompt/answer/上游 body；cache 文件名无 token
  - 成功消费 pending；失败保留 bounded pending + TTL
- [ ] `skills/lib/cursor-hooks-merge.test.mjs` — 空/缺失文件生成 v1；保留未知顶级键与用户 hooks；basename 去重与升级；两次安装幂等；project/global command 不同；非法 JSON bytes 不变 + warning；**无** `failClosed: true`
- [ ] `skills/package.json` — `"test": "node --test lib/*.test.mjs"`；**不**增加 `dependencies` / `devDependencies`
- [ ] 扩展 `server/tests/initiatives/test_ide_hook_assets.py` — Cursor 有 before/after（可保留 stop）；无 `afterAgentThought`；Cursor stop 无 Claude inject / `report_session_knowledge`；Capture 不以 `diff --stat` 为门闩；Codex 原断言零回归。更新（勿删除）现有 `test_write_path_cursor_stop_hook`：仍可含 `stop`，必须**另**含 `afterAgentResponse`
- [ ] 扩展 `server/tests/mcp_tools/test_skills_snapshot_guard.py` — friday / friday-dev / friday-memory（及 http-fallback）职责分离短语 + 工具 token ⊆ snapshot
- [ ] Framework install: 无 — 已有 pytest；Node `node:test` 随 Node ≥20；不装 jq/axios/vitest-in-skills

既有 `mcp_client` 不用于 hook 进程测试。会话 Capture 必须委托同一 `session_capture` helper，禁止 Claude/Cursor 各写一套 POST 体。

---

## Manual-Only Verifications

All phase behaviors have automated verification.

真实 IDE 点一次安装/一轮问答可作为执行后 smoke，**不是** Nyquist 门禁，不阻塞 `nyquist_compliant`。CONTEXT 所述 E2E fixture（Claude/Cursor × dirty/clean、失败网络、重复安装、自定义 hooks 合并、无 CoT/凭证泄漏）由上表 Wave 0 自动化覆盖。

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verification
- [ ] Wave 0 covers all missing references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s for per-task commands
- [ ] Submodule (`skills` node:test) and parent (pytest + gitlink) checks both green before phase gate
- [ ] `nyquist_compliant: true` set in frontmatter **only after** Wave 0 files exist and phase tasks are green（当前 draft / false）

**Approval:** pending
