# Phase 145: Cursor / Claude Code 双宿主采集 - Pattern Map

**Mapped:** 2026-08-28
**Files analyzed:** 18 个新增/修改落点
**Analogs found:** 17 / 18

## Ownership Boundary

### `skills/` 子模块：可分发运行时的唯一所有者

`skills/` 是独立 Git 仓库，来源由根仓 `.gitmodules` 明确：

```ini
[submodule "skills"]
	path = skills
	url = https://github.com/friday-ai-codes/skills.git
```

以下文件必须在 `skills` 子模块内实现、测试并先提交：

- `hooks/lib/session_capture.py`
- `hooks/user-prompt-submit`
- `hooks/stop`
- `hooks/hooks.json`
- `hooks/cursor/hooks.json`
- `hooks/cursor/before-submit-prompt`
- `hooks/cursor/after-agent-response`
- `lib/installer.mjs`
- `lib/cursor-hooks-merge.test.mjs`
- `package.json`
- `skills/friday/SKILL.md`
- `skills/friday-dev/SKILL.md`
- `skills/friday-dev/references/http-fallback.md`
- `skills/friday-memory/SKILL.md`
- `skills/friday-memory/references/http-fallback.md`

理由：`skills/package.json` 第 10–18 行把 `lib/`、`skills/`、`hooks/` 纳入 npm 发布包；这些文件是用户机器上实际执行的安装器、hook 与文档，不应由父仓 snapshot 反向生成。

### 父仓：服务端下载资产与跨面守卫的所有者

以下文件由 `friday-ai` 父仓拥有：

- `server/initiatives/services/ide_hook_assets.py`
- `server/tests/initiatives/test_ide_hook_assets.py`
- `server/tests/hooks/conftest.py`
- `server/tests/hooks/test_session_capture_hooks.py`
- `server/tests/mcp_tools/test_skills_snapshot_guard.py`
- `skills` gitlink 指针

`ide_hook_assets.py` 是项目级「复制/下载」资产生成器，允许携带项目 ID 与服务端环境变量约定；它不是 npm skills 文件的源。父仓测试可以读取当前 checkout 的 `skills/` 内容做契约守卫，但不得在运行时 import 或复制子模块源码。

### 禁止的所有权倒置

- 不在 `server/` 里创建 canonical `session_capture.py`，再要求 npm 包运行时回读父仓文件。
- 不让 `skills/lib/installer.mjs` import `server/initiatives/services/ide_hook_assets.py`。
- 不用 byte-for-byte snapshot 强绑两套脚本：skills 是通用无项目绑定资产，server 是 per-project 下载资产；应锁事件、字段、路径、安全不变量。
- 不在父仓直接提交 `skills/...` 文件而漏掉子模块 commit；父仓只能记录 gitlink SHA。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `skills/hooks/lib/session_capture.py` | utility | file-I/O + request-response | `skills/hooks/user-prompt-submit` + `skills/hooks/stop` | exact-composite |
| `skills/hooks/user-prompt-submit` | hook | event-driven | 当前同文件第 25–158 行 | exact |
| `skills/hooks/stop` | hook | event-driven | 当前同文件第 41–131 行 | exact |
| `skills/hooks/hooks.json` | config | event-driven | 当前同文件第 1–38 行 | exact |
| `skills/hooks/cursor/hooks.json` | config | event-driven | `server/.../ide_hook_assets.py` 第 436–448 行 | role-match |
| `skills/hooks/cursor/before-submit-prompt` | hook | event-driven | `skills/hooks/user-prompt-submit` | role-match |
| `skills/hooks/cursor/after-agent-response` | hook | event-driven | `skills/hooks/stop` | role-match |
| `skills/lib/installer.mjs` | installer/service | file-I/O | 当前同文件第 56–64、158–190 行 | exact |
| `skills/lib/cursor-hooks-merge.test.mjs` | test | file-I/O | 无现成 Node 测试 | none |
| `skills/package.json` | config | batch | 当前 scripts 第 32–35 行 | exact |
| `skills/skills/friday/SKILL.md` | docs | request-response | 当前第 75–85 行 | exact |
| `skills/skills/friday-dev/SKILL.md` | docs | request-response | 当前第 42–58 行 | exact |
| `skills/skills/friday-dev/references/http-fallback.md` | docs | request-response | 当前工具契约表第 29–48 行 | exact |
| `skills/skills/friday-memory/{SKILL.md,references/http-fallback.md}` | docs | request-response | friday-dev 同类文档 | role-match |
| `server/initiatives/services/ide_hook_assets.py` | service/provider | transform | 当前 `_claude_inject_script`、`_stop_writeback_script` | exact |
| `server/tests/initiatives/test_ide_hook_assets.py` | test | transform | 当前服务层资产断言第 49–181 行 | exact |
| `server/tests/hooks/{conftest.py,test_session_capture_hooks.py}` | test | event-driven + request-response | `server/tests/test_security_baseline.py` 第 17–34 行 | role-match |
| `server/tests/mcp_tools/test_skills_snapshot_guard.py` | snapshot test | file-I/O | 当前 friday-solution 文档不变量第 84–171 行 | exact |

## Pattern Assignments

### `skills/hooks/lib/session_capture.py`（utility，file-I/O + request-response）

**Analogs:** `skills/hooks/user-prompt-submit` 与 `skills/hooks/stop`

**零依赖与输入容错模式**（`user-prompt-submit` 第 27–51 行）：

```python
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

try:
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].strip() else {}
except Exception:
    event = {}
if not isinstance(event, dict):
    event = {}
```

**凭证解析顺序**（`user-prompt-submit` 第 55–67 行；`stop` 第 50–61 行相同）：

```python
base_url = os.environ.get("FRIDAY_BASE_URL") or os.environ.get("FRIDAY_API_URL") or ""
token = os.environ.get("FRIDAY_ACCESS_TOKEN") or os.environ.get("FRIDAY_PAT") or ""
if not base_url or not token:
    try:
        with open(os.path.expanduser("~/.friday/config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        base_url = base_url or str(cfg.get("baseUrl") or "")
        token = token or str(cfg.get("accessToken") or "")
    except Exception:
        pass
```

**HTTP fail-soft 模式**（`stop` 第 108–123 行）：

```python
req = urllib.request.Request(
    f"{base_url.rstrip('/')}/api/mcp/tools/report_project_knowledge/",
    data=payload,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=REPORT_TIMEOUT_SECONDS).read()
except Exception:
    fail_soft()
```

**需新增但应沿用的本地状态模式：**

- cache 根沿用 `${XDG_CACHE_HOME:-~/.cache}/friday-skills`（`user-prompt-submit` 第 80–85 行）。
- 文件名只含 session/generation 的 SHA-256 摘要，不含 prompt、token、git URL。
- 目录 `0o700`、pending 文件 `0o600`；写临时文件后 `os.replace`。
- 状态限定 24h TTL；每次读写顺手清理过期文件。
- 同 conversation 内按 generation 精确匹配；generation 缺失时只有恰好一个 pending 才可消费。
- POST 成功且响应 JSON `accepted` 缺省为真时消费；网络/解析/非 2xx 失败保留 bounded pending。
- `answer = normalize(strip_visible_thinking(answer))[:16000]`；只接受宿主白名单字段。

**服务端请求契约来源：** `server/mcp_tools/serializers.py` 第 831–855 行。`question`、`answer` 必填且各不超过 20000；可选字段为 `repository_id`、`git_url`、`branch_name`、`project_id`、`session_id`、`response_model`、`provider`、`input_tokens`、`output_tokens`、`client`。本阶段 helper 不传 `project_id`/`repository_id`，避免默认分支误绑。

### `skills/hooks/user-prompt-submit`（Claude UserPromptSubmit）

**Analog:** 当前同文件。

保留 shell wrapper：

```bash
set -u
[ "${FRIDAY_HOOKS_DISABLED:-0}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
stdin_json="$(cat 2>/dev/null || true)"
```

改造次序必须是：

1. 从官方字段 `prompt`、`session_id`、可选 `cwd` 写 pending。
2. pending 写失败只影响 Capture，不影响原 lookup。
3. 继续执行现有 branch lookup/cache。
4. stdout 仍只允许第 152–157 行的 Claude `hookSpecificOutput.additionalContext`。

**禁止：**把 pending 路径、prompt、token 或写入结果拼进 `additionalContext`。

### `skills/hooks/stop`（Claude Stop）

**Analog:** 当前同文件第 41–131 行。

拆成两个互不依赖的分支：

- Capture：`stop_hook_active=true`、空 `last_assistant_message`、无可靠 pending 时 skip；否则调用 shared helper。不得检查 git diff。
- Project memory：完整保留第 73–131 行的 branch、`diff --stat`、300 秒间隔、摘要指纹和 `report_project_knowledge` 语义。

当前第 77–81 行只属于 project memory：

```python
changes = "\n".join(git("-c", "core.quotepath=false", "diff", "--stat", "HEAD").splitlines()[-80:])
if not changes:
    fail_soft()
```

实现时不能继续用 `fail_soft()` 终止整个进程，应让它只 return/skip project-memory 分支，否则 clean-tree Capture 仍被误杀。

### `skills/hooks/hooks.json`（Claude 配置）

**Analog:** 当前文件第 1–38 行。

保持原官方事件和 async 语义：

- `SessionStart` → `session-start`，`async: false`
- `UserPromptSubmit` → `user-prompt-submit`，`async: false`
- `Stop` → `stop`，`async: true`

禁止改成 Cursor 风格扁平 command 数组，也禁止新增 transcript/Thought 事件。

### `skills/hooks/cursor/hooks.json` 与两个 Cursor wrapper

**Analog:** `server/initiatives/services/ide_hook_assets.py` 第 436–448 行提供 `version: 1` 外形；事件应升级为 Phase 145 锁定事件：

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [
      { "command": ".cursor/hooks/friday-before-submit-prompt.sh", "timeout": 15 }
    ],
    "afterAgentResponse": [
      { "command": ".cursor/hooks/friday-after-agent-response.sh", "timeout": 15 }
    ]
  }
}
```

项目级 command 使用 `.cursor/hooks/...`；用户级使用 `./hooks/...`。wrapper 复用 shared helper：

- `beforeSubmitPrompt` 只缓存 `prompt`，输出最多 `{"continue": true}`。
- `afterAgentResponse` 只读 `text`，配对后 POST，任何错误 `exit 0`。
- session key 优先 `conversation_id`、其次 `session_id`；fallback 必须同时有 workspace/cwd 与 `generation_id`，否则 skip。

### `skills/lib/installer.mjs`

**Analog:** 当前 installer 的纯 Node stdlib、导出函数、幂等写入模式。

Imports 延续第 18–30 行的 `node:fs` / `node:os` / `node:path`，新增原子替换所需 API，不引入 npm 包。

安装入口沿用 `performInstall` 第 130–159 行按 agent 循环；只在 `agent.id === "cursor"` 时复制 hook 文件并 merge hooks config。

建议导出纯函数：

```javascript
export function mergeCursorHooksConfig(existing, fridayEntries) {
  // preserve unknown top-level keys and all unrelated events
  // replace/append only stable Friday commands
}
```

稳定 Friday 标识为 command basename：

- `friday-before-submit-prompt.sh`
- `friday-after-agent-response.sh`

merge 规则：

- 只接受根对象；目标输出 `version: 1`。
- 保留未知顶级键、其他事件、用户 hook。
- 同 basename 条目替换成当前 scope command/timeout；不得重复 append。
- 保留既有 `stop`/`friday-stop-writeback.sh` project-memory hook。
- 非法 JSON：原文件原样保留，返回 warning 给安装器展示，不写 `{}`。
- 有效 JSON：同目录临时文件写完再 rename；重复安装内容不变。

**禁止复用 `cursorRuleBootstrap` 第 174–190 行的「文件存在即不动」策略。** `hooks.json` 必须结构化合并，不能把它当独占生成文件。

### `skills/lib/cursor-hooks-merge.test.mjs` 与 `skills/package.json`

skills 仓当前没有 Node 测试 analog；采用 Node 内置 `node:test` + `node:assert/strict`，临时目录隔离 `HOME`/cwd，不新增 dependency。

至少锁定：

- 空文件/不存在文件生成 v1。
- 保留未知顶级键。
- 保留用户 `beforeSubmitPrompt`、`stop` 与其他事件。
- 两次安装 deepEqual 且 Friday basename 各一条。
- project/global command 路径不同。
- 旧 Friday command 被升级。
- 非法 JSON 文件 bytes 不变且返回可操作 warning。

`package.json` scripts 延续第 32–35 行，只追加：

```json
"test": "node --test lib/*.test.mjs"
```

### skills 文档与 HTTP fallback

**Analogs:**

- `friday/SKILL.md` 第 75–85 行：分支环路总述。
- `friday-dev/SKILL.md` 第 42–58 行：收工工具与 HTTP 入口分开。
- `friday-dev/references/http-fallback.md` 第 29–34 行：工具契约表。
- `friday-memory/SKILL.md` 第 8–15 行：职责分层表。

文案必须显式并列两个职责：

- 每轮可见问答 → `report_session_knowledge` → SessionCapture；clean tree 也提交。
- 有 git 交付变更的项目总结 → `report_project_knowledge`；保留质量门槛与原有 diff 门闩。

HTTP fallback 增加 `/api/mcp/tools/report_session_knowledge/` 的 12 字段契约，标明 `question`/`answer` 必填、答案仅取可见 final、不得上传 transcript/CoT/凭证。不要把两个工具合成一个“记忆写回”概念。

### `server/initiatives/services/ide_hook_assets.py`

**Analogs:**

- `_claude_inject_script` 第 125–209 行：生成 shell、环境变量、curl 超时、stdout 注入。
- `_stop_writeback_script` 第 319–433 行：三宿主 project-memory/STATE 回写。
- `_cursor_stop_hooks_snippet` 第 436–448 行：Cursor v1 config shape。
- `build_write_path_assets` 第 470–563 行：按 runtime 返回 path/content/notes bundle。

实现应保留现有 `_stop_writeback_script` 为 project knowledge/STATE 路径，新增独立 session Capture helper/脚本生成器与 Cursor before/after snippets。Cursor bundle 可继续含 `stop`，但：

- `stop` 脚本不得出现 `last_assistant_message` 或 `report_session_knowledge`。
- `afterAgentResponse` 才能出现 session Capture。
- Cursor 任何脚本不得出现 Claude `hookSpecificOutput` / `additionalContext`。
- Codex 输出与语义保持不变。

服务端资产需生成与实体 hook 一致的相对路径，但不要读取 `skills/hooks/...` 文件作为运行时依赖。

### `server/tests/initiatives/test_ide_hook_assets.py`

**Analog:** 当前测试第 49–181 行以 `by_path` + `json.loads` 做精确资产断言。

沿用：

```python
bundle = build_write_path_assets(project, RUNTIME_CURSOR)
by_path = {f["path"]: f["content"] for f in bundle["files"]}
hooks = json.loads(by_path[".cursor/hooks.json"])
```

新增正向断言：

- Cursor 有 `beforeSubmitPrompt`、`afterAgentResponse`，可保留 `stop`。
- Claude 有 `UserPromptSubmit`、`Stop`。
- Capture 脚本包含 `report_session_knowledge`、短 timeout、`exit 0`。

新增负向断言：

- Cursor config 无 `afterAgentThought`。
- Cursor stop 无 `report_session_knowledge` / `last_assistant_message`。
- Cursor before/after 无 `hookSpecificOutput` / `additionalContext`。
- Claude/Cursor Capture 不以 `diff --stat` 为前置门闩。
- Codex assets 与原断言不变。

### `server/tests/hooks/conftest.py` 与 `test_session_capture_hooks.py`

**Closest executable-test analog:** `server/tests/test_security_baseline.py` 第 17–34 行：

```python
env = os.environ.copy()
env.update(extra_env)
return subprocess.run(
    [...],
    cwd=SERVER_DIR,
    env=env,
    capture_output=True,
    text=True,
    check=False,
)
```

本阶段测试用 `subprocess.run(["bash", hook], input=json.dumps(event), ...)` 执行真实 wrapper；`tmp_path` 设置 `XDG_CACHE_HOME`、临时 git 仓，并把 HTTP 指向本地受控 fixture 或把 helper 的 transport 抽成可直接 monkeypatch 的函数。由于 pytest 默认 `--disable-socket`，不得发真实网络。

fixture/测试矩阵：

- Claude prompt + Stop `last_assistant_message`。
- Cursor before `prompt` + after `text`。
- dirty 与 clean tree 均 POST Capture；仅 dirty 写 project knowledge。
- missing PAT、无 git、网络失败、非法 JSON、空 answer 全部 returncode 0。
- duplicate Stop/after 只消费一次。
- `stop_hook_active=true` 不写。
- generation 错配/多 pending 无 generation 时 skip。
- thinking 标签被删除，正文为空则 skip。
- stdout/stderr/cache 文件名不含 PAT；stdout 不含 prompt/answer。
- 成功后 pending 消费，失败后保留但 TTL/数量有界。

没有现成 hook E2E fixture，planner 应将这两个文件列为 Wave 0，不要把 `test_ide_hook_assets.py` 的字符串测试误当行为测试。

### `server/tests/mcp_tools/test_skills_snapshot_guard.py`

**Analog:** 第 84–171 行的 friday-solution 跨主文/HTTP fallback 不变量。

沿用 `documents` + `required_terms` + `missing` 聚合模式，覆盖：

- `friday/SKILL.md`
- `friday-dev/SKILL.md`
- `friday-dev/references/http-fallback.md`
- `friday-memory/SKILL.md`
- `friday-memory/references/http-fallback.md`

锁定每份适用文档同时包含：

- `report_session_knowledge`
- `report_project_knowledge`
- clean tree/无 git 改动仍收集问答
- 只取用户可见最终答案
- 不上传 transcript、隐藏思维链、凭证
- 两工具职责分离

现有第 64–81 行的「技能工具 token ⊆ `TOOL_SCHEMA_SNAPSHOT`」继续作为工具可达门禁；不要只依赖该 subset 测试，因为它不验证职责语义。

## Shared Patterns

### Fail-soft host lifecycle

**Sources:** `skills/hooks/user-prompt-submit` 第 16–17、41–42 行；`skills/hooks/stop` 第 13–14、37–38 行。

所有 hook 错误路径最终状态为 0。不得向 Cursor 返回 `failClosed: true`，不得向 Stop 输出 follow-up/block，不因 Capture 失败阻断原 project-memory 路径。

### Credential and HTTP handling

**Source:** `skills/hooks/user-prompt-submit` 第 55–67、102–114 行。

统一凭证优先级与 Bearer POST；短 timeout；异常不输出响应 body。问答正文仅进入 POST body 和 `0600` bounded pending，不进入 stdout/stderr、marker digest 内容或仓库。

### Optional repository anchoring

**Source:** `server/tests/mcp_tools/test_report_session_knowledge.py` 第 137–182 行。

服务端已锁定无挂钩、无法解析 repo、默认分支仍 `accepted=true`。客户端无 git 时仍应提交空 `git_url`/`branch_name`，不得先调 lookup 猜 `project_id`。

### Snapshot and package alignment

**Sources:**

- `test_skills_snapshot_guard.py` 第 64–81 行：skills 文档引用不越出 snapshot。
- `test_mcp_package_alignment.py` 第 59–97 行：npm MCP、serializer、snapshot 三面对齐。

Phase 145 不改服务端工具 schema；只扩文档不变量与 hook/asset 行为。若实现意外需要改 12 键契约，应停止并回到 Phase 142 契约讨论。

## Host-Specific Anti-Patterns

| Host | Anti-pattern | Required replacement |
|---|---|---|
| Cursor | 用 `stop` 读取答案 | 仅 `afterAgentResponse.text` |
| Cursor | 订阅 `afterAgentThought` | 完全不注册；不得采集 thinking |
| Cursor | 读取 `transcript_path` | 只取事件 `text` |
| Cursor | `beforeSubmitPrompt` 输出 `additionalContext` | 只缓存 prompt，输出 `{"continue": true}` 或静默成功 |
| Cursor | 把 Claude `hookSpecificOutput`/context inject 脚本复制过来 | 独立 Cursor wrapper + shared data helper |
| Cursor | 整文件覆盖 `.cursor/hooks.json` | JSON object merge，保留用户键与 hook |
| Cursor | 非法 JSON 时写 `{}` | 原文件不变 + 可操作 warning |
| Cursor | 用 command 全字符串去重 | 用稳定 Friday basename 识别并升级 scope path |
| Claude Code | 从 transcript 找 final answer | 只取 `Stop.last_assistant_message` |
| Claude Code | 忽略 `stop_hook_active` | 为真时 skip Capture，防递归重复 |
| Claude Code | 用 git diff 门闩 Capture | Capture 与 project-memory 分轨 |
| Claude Code | 把 pending 信息打印进注入 stdout | stdout 仅 lookup context |
| 两宿主 | 客户端判定 low value 后丢弃 | 全部可见有效问答进入 Capture，由 Phase 143 评估 |
| 两宿主 | 上报 CoT/tool trace/agent transcript | 字段白名单 + thinking 标签保守删除 |
| 两宿主 | 新增 jq/axios/zod/node-fetch/本地 LLM | Python/Node stdlib + bash/git/curl |
| 两宿主 | 无 git/PAT/网络失败时非零退出 | fail-soft return/exit 0 |

## Safe Atomic Commit Ordering

### 1. 先提交 `skills` 子模块

一个自洽子模块 commit 包含：

1. Wave 0：`lib/cursor-hooks-merge.test.mjs`、`package.json` test script。
2. shared helper、Claude 增量接线、Cursor hooks/template。
3. installer merge/copy。
4. friday/friday-dev/friday-memory 主文与 HTTP fallback。

在 `skills/` 内先跑 `node --test lib/*.test.mjs` 和 package dry-run。该 commit 必须独立存在于可拉取 remote；父仓不能先引用本地未推送 SHA。

### 2. 再提交父仓接入 commit

同一个父仓 commit 原子包含：

- `skills` gitlink 更新到步骤 1 的 SHA。
- `server/initiatives/services/ide_hook_assets.py`。
- `server/tests/initiatives/test_ide_hook_assets.py`。
- `server/tests/hooks/` 行为测试。
- `server/tests/mcp_tools/test_skills_snapshot_guard.py`。

原因：snapshot guard 读取父仓 checkout 下的 `skills/skills/*`。只提交 server 断言不更新 gitlink会在 CI 看到旧文档；只更新 gitlink不更新 server assets/tests会让两个分发面漂移。

### 3. 规划/验证文档单独提交

`145-PATTERNS.md`、后续 PLAN/SUMMARY/VALIDATION 可以独立 planning commit，不与生产实现混合。当前任务只创建本 pattern map，不创建生产 commit。

### 明确禁止的顺序

- 父仓先提交指向尚未 push 的 skills SHA。
- 在父仓 commit 中把子模块显示为 dirty，却只 `git add skills/...`。
- server snapshot tests 先落地并依赖工作区未提交的子模块内容。
- 把 skills 子模块源码复制到 server 后分别演进。

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `skills/lib/cursor-hooks-merge.test.mjs` | test | file-I/O | skills 仓当前没有 `*.test.mjs` 或 `node:test` 测试；采用 Node 标准库并以 installer 导出纯函数为 seam |

## Metadata

**Analog search scope:** `skills/hooks/`、`skills/lib/`、`skills/skills/friday*`、`server/initiatives/services/`、`server/tests/initiatives/`、`server/tests/mcp_tools/`、`server/tests/`

**Strong analog files read:** 17

**Pattern extraction date:** 2026-08-28

**Friday context trace:** `run_id=78f4e88a-16de-4652-8a0c-dac4cb34087a`；当前 `main` 的项目绑定与 Phase 145 无直接需求关联，因此仅采用其中已验证的 Phase 141–143 Capture 契约记忆，不采用其业务项目内容。
