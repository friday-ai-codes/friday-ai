# Phase 145: Cursor / Claude Code 双宿主采集 - Research

**Researched:** 2026-08-28
**Domain:** IDE hook pairing → HTTP/MCP `report_session_knowledge` Capture writeback
**Confidence:** HIGH (official hook schemas + in-repo assets); MEDIUM (Cursor field-name variance across versions; TTL/lock defaults)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Claude Code 事件配对
- Claude Code 在 `UserPromptSubmit` 读取官方 stdin JSON 中的用户 prompt 与 session id，继续执行既有项目上下文召回，并把待配对问题以 `0600` 临时状态按 session 隔离保存；hook stdout 只输出需注入的上下文，不回显敏感状态。
- Claude Code 在 `Stop` 读取官方 `last_assistant_message` 作为答案来源，与同 session 最近未消费问题配对后调用 `report_session_knowledge`；不得抓 transcript、终端日志、内部 event stream 或隐藏 reasoning。
- Stop 不再以 `git diff --stat`/最近 commit 是否非空作为会话 Capture 前置条件；clean tree、纯解释、代码阅读与调试结论同样写回。既有 `report_project_knowledge` 变更总结路径保持原门闩与语义。
- 无问题、空/缺失 `last_assistant_message`、重复 Stop 或递归 hook 时安全跳过；成功提交后消费配对状态，失败保留有界可重试状态但永不阻塞宿主退出。

#### Cursor 事件配对
- Cursor 只接 `beforeSubmitPrompt` 与 `afterAgentResponse`：前者保存用户 prompt/session 对应关系，后者提取最终可见 assistant response 并回写；禁止使用 `stop` 事件替代 `afterAgentResponse`。
- 生成 `.cursor/hooks.json` 采用官方 `version: 1` 结构；installer 必须结构化读取并合并目标文件，保留未知顶级键、其他事件和用户已有 hook，只追加 Friday hook 且按稳定 command 标识去重。
- Cursor 事件字段通过兼容提取器读取，缺失 session id 时生成仅用于本次本地配对的稳定 fallback；无法可靠配对时跳过，不把前一会话答案错配给后一问题。
- Cursor 采集与 Claude Code 共用同一个 writeback helper/请求体构造，统一传递可得的 repository/git URL、branch、project、session、model/provider/token 与 `client=cursor|claude_code` 元数据。

#### 答案精华、安全与 fail-soft
- 上报答案只取用户可见的最终响应，做保守长度上限与空白规范化；不要求客户端再调用 LLM 总结，也不得从 thinking、tool trace、agent transcript 或 CoT 标签补内容。
- 客户端不负责价值 high/medium/low；原始可见答案进入 Capture 后由 Phase 143 Friday LLM 异步提炼。客户端禁止因自判“低价值”而丢弃。
- hook shell/helper 使用现有 `bash`、`git`、`curl` 与系统 `python3` 标准库能力；不新增 jq、Node package、Python package 或其他安装依赖，不把 PAT、问答正文或上游错误 body 写到 stdout/stderr/cache。
- 所有网络调用设置短连接/总超时并 fail-soft，HTTP 非 2xx、JSON 解析、文件锁、无 git 仓库或 MCP 不可用均返回成功宿主状态；本地敏感状态权限收紧、原子写入且有 TTL 清理。

#### 分发、兼容与验收
- `skills/hooks/hooks.json` 保留 Claude Code `SessionStart`、`UserPromptSubmit`、`Stop` 结构，在现有脚本上增量接线；`ide_hook_assets.py` 生成/检查的读写路径与实体 hooks 保持一致。
- `skills/lib/installer.mjs` 安装 Cursor 时 merge `.cursor/hooks.json` v1 而非覆盖；重复安装幂等，已有同类 Friday 条目升级为当前 command，非法 JSON 先保留原文件并给出可操作警告而非静默清空。
- 更新 friday/friday-dev 相关技能快照，明确每轮问答走 `report_session_knowledge`、项目交付总结仍走 `report_project_knowledge`；两工具职责不得在文案中合并。
- E2E fixture 覆盖 Claude 与 Cursor 各一次有改动和 clean-tree 会话、可见答案配对、失败网络、重复安装、已有自定义 Cursor hooks 合并及无 CoT/凭证泄漏；npm/server snapshot 继续作为工具可达前置门禁。

### Claude's Discretion
- 共用 helper 采用 shell + Python 文件、单个 Python 标准库脚本或现有 asset generator 模板由实现者决定，只要零新增依赖且两个宿主行为一致。
- 临时配对目录、TTL、答案长度上限与锁实现由实现者按跨平台可靠性决定；不得把原始问答落入仓库或长期保留。

### Deferred Ideas (OUT OF SCOPE)
- VS Code、JetBrains、Codex 等更多宿主自动采集留后续版本；现有 Codex 资产不因本 Phase 回退。
- 离线持久队列、跨设备 session 同步与失败 Capture 管理 UI 留后续版本。
- 客户端本地 LLM 摘要、CoT/工具轨迹采集和 transcript 上传明确不做。
- Capture 人工价值纠偏、升级为 `ProjectMemory` 草稿和管理后台不属于本 Phase。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SKILL-01 | Cursor 与 Claude Code 的 Friday skills/hooks 抽取本轮问题与可见答案精华并调用 `report_session_knowledge` | 共用 writeback helper POST `/api/mcp/tools/report_session_knowledge/`；必填 `question`/`answer`；`client=cursor\|claude_code` |
| SKILL-02 | 干净工作树 / 无 `diff --stat` 仍回写问答 Capture | Claude `Stop` 拆成两条路径：Capture **不**看 git；`report_project_knowledge` **保留**现有 empty-diff skip |
| SKILL-03 | Claude：`UserPromptSubmit` 缓存 + `Stop.last_assistant_message`；Cursor：`beforeSubmitPrompt` + `afterAgentResponse`；禁止 Claude 注入脚本进 Cursor `stop` | 官方 payload 已核；Cursor `stop` 无助手正文；`afterAgentThought`/`transcript_path` 禁用 |
| SKILL-04 | 不上报隐藏思维链；skills / HTTP fallback / `ide_hook_assets` / snapshot 守卫同一验收 | 答案只取 `last_assistant_message` 或 `text`；文档与资产交叉断言；扩展 `test_skills_snapshot_guard.py` |
| SKILL-05 | installer merge Cursor `hooks.json` `version: 1`；无 PAT / 接口失败 fail-soft 不阻断编码 | `installer.mjs` 结构化 merge；所有路径 `exit 0`；`failClosed` 不得为 true |
</phase_requirements>

## Summary

Phase 145 不改 Capture 服务端契约（Phase 141–144 已冻结）。工作是把两个宿主的**官方可见轮次事件**接到同一 HTTP writeback：Claude Code 用已有插件 hook 增量接线；Cursor 用 `hooks.json` v1 **合并安装**补齐 `beforeSubmitPrompt`/`afterAgentResponse`。当前最大缺口是 `skills/hooks/stop` 与 `ide_hook_assets._stop_writeback_script` 仍以 `git diff --stat` 为空则跳过，直接违反 SKILL-02。

Cursor 现有写路径资产把答案押在 `stop`（仅 `status`/`loop_count`）上，且 installer **不安装** Cursor hooks。本阶段必须：**采集走 `afterAgentResponse.text`**；**既有 `stop`+`report_project_knowledge` 可保留作交付变更沉淀，但不得当 Capture 答案源，也不得把 Claude `UserPromptSubmit` 注入脚本拷进 Cursor `stop`**。客户端不做价值分档、不读 transcript、不猜 `project_id`（Phase 144 默认分支第三源已禁止误绑）。

**Primary recommendation:** 抽一个零依赖的 `skills/hooks/lib/session_capture.py`（stdlib：json/os/tempfile/urllib），Claude `user-prompt-submit`/`stop` 与 Cursor before/after 共用配对+POST；`installer.mjs` 新增 `mergeCursorHooksJson`；`ide_hook_assets.py` 为 Cursor 增 before/after 资产并加守卫：Cursor 树零 `last_assistant_message`、零 `additionalContext` 注入、零 `afterAgentThought`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 本轮问题缓存 / 答案提取 | Browser / Client (IDE hooks) | — | 只有宿主 hook 看得到 prompt 与可见 final text |
| 配对状态（0600 临时文件） | OS user cache (`~/.cache/friday-skills`) | — | 不得进仓库；session 隔离；TTL |
| Capture 持久化 / 挂钩 / 评估 | API / Backend | Database | 已有 `report_session_knowledge` → `CaptureService` |
| Cursor `hooks.json` 合并安装 | Frontend tooling (`skills` installer, Node std `fs`) | — | 项目/用户配置，不是服务端生成覆盖 |
| 技能文案与 HTTP fallback | CDN / Static (skills 包文件) | API 契约文档 | snapshot 守卫保证工具名 ⊆ `TOOL_SCHEMA_SNAPSHOT` |
| 读路径上下文注入 | Claude Code hook stdout only | Cursor always-on rules + MCP | Cursor `beforeSubmitPrompt` **不能**注入；保持 Phase 86 |
| 项目交付记忆 | API `report_project_knowledge` | Claude/Cursor `Stop`/`stop` 仅 git-diff 路径 | MCP-04 零回归；与 Capture 分轨 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| 系统 `python3` | 本机 3.14.2 已装；hooks 只要求 3.x stdlib | JSON 解析、配对文件、urllib POST | 现 `user-prompt-submit`/`stop` 已用 [VERIFIED: skills/hooks] |
| `bash` + `git` + `curl` | 本机已有 | 包装 stdin、读 remote/branch、资产脚本兼容 | 现脚本同一集合；**禁止 jq** |
| Node.js `fs`（installer） | skills `engines.node >=20`；本机 v24.18.1 | merge `hooks.json` | 已有 `installer.mjs`；**禁止 axios/zod/node-fetch** [VERIFIED: skills/package.json 0.7.0] |
| Django MCP `report_session_knowledge` | Phase 142 冻结 | Capture 入口 | serializer 12 request 键；`question`/`answer` max_length=20000 [VERIFIED: server/mcp_tools/serializers.py] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest 9 + pytest-socket | `server/pyproject.toml` | hook fixture / 资产守卫 | mock `urlopen`；默认 `--disable-socket` |
| Node 内置 `node:test` | Node 18+ | installer merge 单测 | **不**新增 npm 依赖；skills 包目前无测试脚本 |
| `@friday-ai-codes/mcp` | 子模块已含 54 工具 | 技能显式调用兜底 | snapshot 前置门禁；hooks 走 HTTP 而非 stdio MCP |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 共用 Python helper | 两套纯 bash+curl | bash JSON 易碎；官方 payload 嵌套必须用 python3 |
| 项目级 `.friday/` 配对文件 | `~/.cache` | 会进 git / 云 agent 工作区泄漏问答；**禁止** |
| Cursor `stop` 抽答案 | `afterAgentResponse` | 官方 `stop` **没有**助手正文 [CITED: cursor.com/docs/hooks] |
| 读 `transcript_path` | `last_assistant_message` / `text` | Claude 官方：Stop 时 transcript 可能不含最终消息 [CITED: code.claude.com/docs/en/hooks] |

**Installation:** 本阶段 **零** `npm install` / `uv add`。

**Version verification:** `python3 --version` → 3.14.2；`node --version` → v24.18.1；`skills/package.json` → `0.7.0`。无新包，跳过 slopcheck 安装门。

## Package Legitimacy Audit

本阶段不引入外部包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | n/a | 无新依赖 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*未运行 slopcheck：无候选包。*

## Architecture Patterns

### System Architecture Diagram

```text
User prompt
    │
    ├─ Claude Code ── UserPromptSubmit (stdin JSON: prompt, session_id, cwd)
    │         ├─ cache pending Q (0600, ~/.cache/friday-skills/pair-*)
    │         └─ existing lookup_project_by_branch → stdout hookSpecificOutput.additionalContext
    │
    └─ Cursor ── beforeSubmitPrompt (stdin JSON: prompt + common conversation_id/generation_id/model)
              ├─ cache pending Q (same helper)
              └─ stdout {"continue": true} ONLY — never additionalContext

Visible assistant finish
    │
    ├─ Claude Code ── Stop (async): last_assistant_message, stop_hook_active, session_id
    │         ├─ if stop_hook_active or empty message or no pending Q → skip Capture
    │         ├─ pair latest unconsumed Q for session → POST report_session_knowledge (client=claude_code)
    │         └─ SEPARATE: if git diff --stat nonempty → existing report_project_knowledge (unchanged gate)
    │
    └─ Cursor ── afterAgentResponse: text (+ conversation_id/generation_id/model)
              ├─ NEVER afterAgentThought, NEVER stop, NEVER transcript_path
              └─ pair → same POST (client=cursor)

POST {FRIDAY_BASE_URL|FRIDAY_API_URL}/api/mcp/tools/report_session_knowledge/
  Bearer {FRIDAY_ACCESS_TOKEN|FRIDAY_PAT|~/.friday/config.json}
  body: question, answer, optional git_url, branch_name, session_id, response_model, provider, tokens, client
    │
    └─ CaptureService.persist (Phase 141) → durable eval (Phase 143)
         missing repo/project still accepted=true

Installer (Cursor only)
    read target .cursor/hooks.json → merge version:1 + Friday commands by stable id
    copy cursor hook scripts → .cursor/hooks/ (project) or ~/.cursor/hooks/ (user)
    invalid JSON → keep file + warn; never truncate to {}
```

### Recommended Project Structure

```
skills/hooks/
├── hooks.json                      # Claude plugin：SessionStart / UserPromptSubmit / Stop（事件名不变）
├── session-start                   # 保持；本阶段不改采集语义
├── user-prompt-submit              # 增量：缓存 prompt；stdout 仍只注入 lookup 上下文
├── stop                            # 拆轨：Capture 无 git 门闩 + 原 project knowledge 门闩
├── lib/session_capture.py          # 推荐：配对 + 精华截断 + POST + fail-soft
└── cursor/
    ├── hooks.json                  # 模板 version:1 beforeSubmitPrompt + afterAgentResponse（可选保留 stop 项目记忆）
    ├── before-submit-prompt
    └── after-agent-response
skills/lib/installer.mjs            # mergeCursorHooksJson + copy cursor hook files
skills/skills/friday/SKILL.md
skills/skills/friday-dev/SKILL.md + references/http-fallback.md
skills/skills/friday-memory/SKILL.md + references/http-fallback.md
server/initiatives/services/ide_hook_assets.py
server/tests/initiatives/test_ide_hook_assets.py
server/tests/mcp_tools/test_skills_snapshot_guard.py
server/tests/hooks/                 # Wave 0：stdin fixture → 断言 POST 体 / exit 0（新建）
skills/lib/cursor-hooks-merge.test.mjs   # Wave 0：node:test
```

`skills/` 是 git submodule（`https://github.com/friday-ai-codes/skills.git`）。实现须在子模块内提交；friday-ai 只更新 submodule pointer。Claude 插件已通过 `skills/.claude-plugin/plugin.json` `"hooks": "./hooks/hooks.json"` 分发，**不要**改官方事件名。

### Pattern 1: Compatible Cursor field extractor

**What:** 从同一 stdin JSON 按优先级取会话键与答案，缺字段不抛。
**When to use:** Cursor 文档：agent hook 公共字段是 `conversation_id` / `generation_id` / `model`；`sessionStart` 写明 `session_id` **等于** `conversation_id`。`beforeSubmitPrompt`/`afterAgentResponse` 专有字段分别是 `prompt` 与 `text`。[CITED: cursor.com/docs/hooks.md]

```python
# Source: https://cursor.com/docs/hooks.md (common schema + beforeSubmitPrompt + afterAgentResponse)
def session_key(event: dict) -> str:
    for k in ("conversation_id", "session_id"):
        v = str(event.get(k) or "").strip()
        if v:
            return v
    gen = str(event.get("generation_id") or "").strip()
    roots = event.get("workspace_roots") or []
    root = roots[0] if isinstance(roots, list) and roots else str(event.get("cwd") or "")
    if gen and root:
        return stable_hash(f"{root}\n{gen}")  # 仅本地配对，不跨会话复用
    return ""  # 无法可靠配对 → 调用方 skip

def visible_answer(event: dict) -> str:
    # Cursor afterAgentResponse
    text = event.get("text")
    if isinstance(text, str) and text.strip():
        return text
    # Claude Stop
    msg = event.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    return ""
```

配对键优先 `conversation_id`/`session_id` + `generation_id`（每轮用户消息变一次）。同会话 FIFO：`afterAgentResponse` 消费该 conversation 上**最近未消费**且 generation 匹配的 pending；generation 缺失则只允许「恰好一条 pending」否则 skip（防止错配）。

### Pattern 2: Dual-path Claude Stop

**What:** 一次 Stop 可做 Capture（无 git 条件）与 project knowledge（保留 empty-diff `fail_soft`）。
**When to use:** SKILL-02 + MCP-04。

现 `skills/hooks/stop` L77–81：`if not changes: fail_soft()` — **必须从 Capture 路径删除，保留在 project knowledge 路径。** `ide_hook_assets._stop_writeback_script` 在无 `recent or changes` 时打印空 content 并跳过 MEMORY POST — Codex/Claude 项目记忆行为保持；Cursor Capture **不得**复用该脚本当答案源。

### Pattern 3: Cursor hooks.json v1 merge

**What:** 结构化 merge，command 稳定标识去重。
**When to use:** installer 与（若下发完整文件）`ide_hook_assets` 提示文案。

官方模板 [CITED: cursor.com/docs/hooks.md]：

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [{ "command": ".cursor/hooks/friday-before-submit-prompt.sh", "timeout": 15 }],
    "afterAgentResponse": [{ "command": ".cursor/hooks/friday-after-agent-response.sh", "timeout": 15 }]
  }
}
```

稳定标识（推荐）：command 路径 basename ∈ `{friday-before-submit-prompt.sh, friday-after-agent-response.sh}`。替换 command/timeout，不删除用户其它条目。保留 `stop` 上用户或旧 Friday `friday-stop-writeback.sh`（项目记忆）。**不要**设 `failClosed: true`。

项目 hook 的 command 相对**仓库根**：`.cursor/hooks/...`。用户级 `~/.cursor/hooks.json` 的 command 相对 `~/.cursor/`：`./hooks/...` [CITED: cursor.com/docs/hooks.md]。installer 必须按 `--project` vs 全局写不同 command。

### Anti-Patterns to Avoid

- **用 Cursor `stop` 抽答案：** 入参只有 `status`/`loop_count`；`followup_message` 会再提交一轮用户消息，污染会话 [CITED: cursor.com/docs/hooks]。
- **订阅 `afterAgentThought`：** 官方字段就是 thinking 全文 — 直接违反 SKILL-04。
- **读 `transcript_path`：** Claude Stop 时文件可能不含最终消息；Cursor 同名字段指向完整 transcript。
- **Cursor `beforeSubmitPrompt` 输出 `additionalContext`：** 输出契约只有 `continue` / `user_message`。注入仍靠 rules + MCP（Phase 86）。
- **把 Claude `friday-context-inject.sh` 或 `hookSpecificOutput` 拷进 `.cursor/hooks/friday-stop-writeback.sh`。**
- **客户端 `lookup_project_by_branch` 把 `project_id` 填进 Capture：** Phase 144 已禁止默认分支第三源误绑；只传 `git_url` + `branch_name`，让服务端挂钩。
- **因「低价值」或 clean tree skip POST。**
- **覆盖整个 `hooks.json` 或非法 JSON 时写成 `{}`。**
- **stdout/stderr 打印 PAT、prompt、answer、上游 error body。**
- **新依赖 jq / axios / 本地 LLM。**
- **采信 `.planning/research/PITFALLS.md`「Cursor 只靠 skill、不要 hook」：** 已被本阶段 CONTEXT 锁定决策覆盖。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP JSON POST | 新 npm 客户端 | `urllib.request`（已有）或 `curl -m` | 超时+exit 0 已验证 |
| hooks.json merge | regex 拼接 | `JSON.parse` + 对象 merge | 保留未知键 |
| 凭证解析 | 新配置格式 | 现顺序：`FRIDAY_BASE_URL`+`ACCESS_TOKEN` → `FRIDAY_API_URL`+`PAT` → `~/.friday/config.json` | 与 mcp setup 一致 |
| git URL 归一 | 客户端猜 SSH/HTTPS | 原样传 `git remote get-url origin`；`CaptureService`+`normalize_git_url` | STORE-04 已落地 |
| 价值分档 | 客户端启发式 | Phase 143 evaluator | EVAL-01 |
| 离线队列 | sqlite/outbox | 有界 pending 文件 + TTL；失败不阻塞 | Deferred 明确不做持久队列 |
| CoT 剥离「智能解析」 | 解析内部 event stream | 只取官方可见字段；可选删除 `<thinking>…</thinking>` 块后若为空则 skip | 不从 CoT **补**内容 |

**Key insight:** 采集正确性几乎全在「用对官方字段 + 不要复用旧 git skip」。服务端已经 accept 无仓无项目。

## Common Pitfalls

### Pitfall 1: 复制 empty-diff skip 到 Capture
**What goes wrong:** 工具通了、账本空。  
**Why:** `skills/hooks/stop` 与 `_stop_writeback_script` 就是这么写的。  
**How to avoid:** 分函数；Capture 单测 fixture 工作树干净仍 POST。  
**Warning signs:** 测试只覆盖 dirty tree。

### Pitfall 2: Cursor session 键拿错导致串话
**What goes wrong:** 上一问的答案配到下一问。  
**Why:** 公共 schema 是 `conversation_id`，不是 Claude 的 `session_id`；`generation_id` 每轮变。  
**How to avoid:** 兼容提取器 + generation 匹配；不可靠则 skip。  
**Warning signs:** 只有 `session_id` 的 fixture 在 Cursor 路径失败。

### Pitfall 3: UserPromptSubmit 把缓存路径或 prompt 打进 additionalContext
**What goes wrong:** 密钥/问题进模型上下文与日志。  
**How to avoid:** stdout JSON 仅 lookup 注入；缓存 IO 全静默。  
**Warning signs:** hook 单测 stdout 含 `pair-` 或 Bearer。

### Pitfall 4: Claude Stop `stop_hook_active`
**What goes wrong:** 递归 Stop 重复上报或死循环。  
**Why:** 官方：`stop_hook_active=true` 表示已因 stop hook 继续 [CITED: code.claude.com/docs/en/hooks]。  
**How to avoid:** `true` 则跳过 Capture（也跳过会触发 follow-up 的逻辑；本阶段不要输出 block/continue）。  
**Warning signs:** 无该字段的防护。

### Pitfall 5: 安装器覆盖用户 hook
**What goes wrong:** 毁掉团队 `preToolUse` 安全 hook。  
**How to avoid:** merge + 非法 JSON 保留原文 + 警告。  
**Warning signs:** 测试只断言「文件等于模板」。

### Pitfall 6: 云 Agent / 无 PAT
**What goes wrong:** 项目 `.cursor/hooks.json` 在 Cloud agent 跑起来但没有 `~/.friday`。  
**How to avoid:** 缺 URL/token → exit 0（已有模式）。Cloud 不用用户级 hooks [CITED: cursor.com/docs/hooks.md]。  
**Warning signs:** 缺 PAT 时非零退出。

### Pitfall 7: 答案超过 serializer 20000
**What goes wrong:** HTTP 400，pending 永不消费。  
**How to avoid:** 客户端截断到 ≤16000 Unicode 字符（discretion 上限，须 < 20000）。空白-only → skip。  
**Warning signs:** 无截断测试。

### Pitfall 8: 文档只写新工具、旧工具语义被吞
**What goes wrong:** snapshot 守卫只检查 ⊆ snapshot，**不**检查职责分离。  
**How to avoid:** 在 `test_skills_snapshot_guard.py` 增加「两工具并列且禁止把 Capture 写成 project knowledge」的短语断言（该文件已有 friday-solution 风格的文档不变量；git 历史含用户向蓝图协议扩展）。

### Pitfall 9: pytest `--disable-socket`
**What goes wrong:** 真实 urllib 在 CI 红。  
**How to avoid:** `unittest.mock.patch("urllib.request.urlopen")`；不要打外网。

## Code Examples

### Claude UserPromptSubmit 输入 / 注入输出

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../00893aaf.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to calculate the factorial of a number"
}
```

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<lookup context only>"
  }
}
```

Source: https://code.claude.com/docs/en/hooks — UserPromptSubmit input / Add context. **禁止**解析 `transcript_path`。默认 command 超时 30s；现 lookup 8s，缓存写入必须同步且短。`hooks.json` 里 UserPromptSubmit 保持 `async: false`（要注入）；Stop 保持 `async: true`。

### Claude Stop 输入（答案权威字段）

```json
{
  "session_id": "abc123",
  "transcript_path": "...",
  "cwd": "/Users/...",
  "hook_event_name": "Stop",
  "stop_hook_active": false,
  "last_assistant_message": "I've completed the refactoring. Here's a summary...",
  "background_tasks": [],
  "session_crons": []
}
```

Source: https://code.claude.com/docs/en/hooks — Stop input. 中断不触发 Stop（走 StopFailure）；本阶段不接 StopFailure。空/缺 `last_assistant_message` → skip Capture。

### Cursor beforeSubmitPrompt / afterAgentResponse

```json
{ "prompt": "<user prompt text>", "attachments": [] }
```

```json
{ "continue": true }
```

```json
{ "text": "<assistant final text>" }
```

另加公共字段 `conversation_id`, `generation_id`, `model`, `model_id`, `workspace_roots`, `cursor_version`, `transcript_path`（忽略）, `user_email`（禁止日志）。Source: https://cursor.com/docs/hooks.md

### Phase 142 请求体（客户端必对齐）

```python
# Source: server/mcp_tools/serializers.py ReportSessionKnowledgeRequestSerializer
payload = {
    "question": question,          # required, non-blank, <=20000
    "answer": answer,              # required, visible essence only
    "git_url": git_url or "",      # optional; empty OK
    "branch_name": branch or "",   # optional; empty OK if not a git repo
    "session_id": session_key,
    "response_model": model or "",
    "provider": "",                # 不要猜；服务端空→unknown
    "input_tokens": "",
    "output_tokens": "",
    "client": "cursor",            # or claude_code
}
# 不要传 project_id / repository_id，除非将来有绝对可靠来源（本阶段不要 lookup）
```

凭证与现 hook 相同；`urllib.request.urlopen(..., timeout=10)`；非 2xx / URLError / JSON 错误 → 不消费 pending，exit 0。HTTP **200** 且可解析 `accepted`（缺省当成功）→ 删除/标记 pending 已消费。不要把响应 body 写入 cache。

### 配对文件（discretion 默认，供计划钉死）

| Item | Recommendation | Rationale |
|------|----------------|-----------|
| 目录 | `${XDG_CACHE_HOME:-~/.cache}/friday-skills/pairs/` | 与现 `ctx-`/`stop-` marker 同根 |
| 权限 | `0o700` 目录，`0o600` 文件 | CONTEXT 0600 |
| 文件名 | `pending-{session_hash}-{generation_or_seq}.json` | session 隔离 |
| 内容 | `{q, ts, client, generation_id}` **不含 token** | 失败可重试；TTL 后删除 |
| TTL | 24h | 不得长期保留问答 |
| 锁 | 同目录 `*.lock` + `os.replace` 原子写 | 并发 Stop/after 少见但要防 |
| 答案上限 | 16000 字符 + `strip()` | < 20000 |
| CoT | 若可见文本含 `<thinking>…</thinking>` / `<thought>…` 则**删除这些块**；不得用块内文本填补截断 | SKILL-04 |

无 git：`branch_name`/`git_url` 空字符串仍 POST（SKILL-02 / MCP-02）。

## State of the Art

| Old Approach (v0.16 Phase 86) | Current Approach (v0.25 Phase 145) | When Changed | Impact |
|-------------------------------|--------------------------------------|--------------|--------|
| Cursor 写路径 = `stop` + git 摘要 → `report_project_knowledge` | Capture = `afterAgentResponse`；project knowledge `stop` 可选保留 | 本阶段 | 必须改资产与测试断言 |
| Claude Stop 无 diff 则 skip | Capture 无 diff 仍 POST | 本阶段 | 改 `skills/hooks/stop` |
| installer 只拷 skills + friday.mdc | 另 merge Cursor hooks v1 | 本阶段 | `installer.mjs` 缺口 |
| PITFALLS「Cursor 不要 hook」 | CONTEXT 锁定自动配对 hook | discuss 2026-08-28 | 研究以 CONTEXT 为准 |

**Deprecated/outdated:**
- 把 Cursor `stop` 当问答采集点（官方无正文）。
- 用 `transcript_path` JSONL 当 Stop 答案（官方反对）。
- 客户端价值门槛 / 本地 LLM 摘要。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Cursor `beforeSubmitPrompt`/`afterAgentResponse` 始终带公共字段 `conversation_id`+`generation_id` | Pattern 1 | 需 fallback；已规定不可靠则 skip |
| A2 | `afterAgentResponse.text` 不含 hidden thinking（thinking 在 `afterAgentThought`） | SKILL-04 | 若混入则靠标签剥离；需 E2E 样例 |
| A3 | 答案客户端上限 16000、配对 TTL 24h | Discretion | 计划应写成任务常量，执行期可改 |
| A4 | 安装器默认写**项目级** `.cursor/hooks.json`（`--project`）与全局 `~/.cursor/hooks.json`（`-g`）两处按现有 scope 选择，不自动双写 | installer | 与现 skills 安装 scope 一致 [ASSUMED 产品默认] |

**已验证、无需用户确认：** 事件名、Cursor v1 schema、Claude `last_assistant_message`、serializer 键、无新依赖、不传 `project_id`。

## Resolved Open Questions

1. **RESOLVED — 保留 Cursor `stop` 项目记忆脚本**
   - What we know: CONTEXT 禁止用 `stop` **替代** `afterAgentResponse`，未要求删除项目记忆 stop。MCP-04 要零回归。
   - Resolution: **保留** `friday-stop-writeback.sh` + 现 git 门闩；Capture 完全走 afterAgentResponse。Cursor 资产可含 `stop`，但 stop 脚本不得含 `question` / `answer` / `last_assistant_message` / `report_session_knowledge`。

2. **RESOLVED — Claude `background_tasks` 非空时不延迟 Capture**
   - What we know: 官方用该数组区分「会话结束」vs「等后台唤醒」。
   - Resolution: **仍在本次 Stop 上报可见答案**（用户已看到最终回复）；不要等后台，避免丢轮。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| python3 | hook helper | ✓ | 3.14.2 | 缺失则现脚本已 `exit 0` |
| bash | hook wrappers | ✓ | /bin/bash | — |
| curl | 部分资产脚本 | ✓ | /usr/bin/curl | helper 用 urllib 可不依赖 curl |
| git | git_url/branch 可选 | ✓ | homebrew git | 无仓库仍 Capture |
| Node >=20 | installer merge 测试 | ✓ | v24.18.1 | — |
| jq | — | 禁止新增要求 | — | 不用 |
| slopcheck | 新包审计 | 未安装 | — | 无新包 |

**Missing dependencies with no fallback:** none  
**Missing dependencies with fallback:** slopcheck（不适用）

Step 2.6: 有外部 CLI，已探测。无阻塞。

## Validation Architecture

`workflow.nyquist_validation` = true。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9 + pytest-django + pytest-socket（server）；Node `node:test`（skills merge，无新包） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]`（`--disable-socket`）；skills 需 Wave 0 加 `"test": "node --test lib/*.test.mjs"` |
| Quick run command | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_request_keys_aligned -x --tb=short` |
| Full suite command | `cd server && uv run pytest tests/initiatives/test_ide_hook_assets.py tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_report_session_knowledge.py tests/hooks/ -q --tb=short` 以及 `cd mcp && npm test -- tests/server.test.ts` 以及 `cd skills && node --test lib/*.test.mjs` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SKILL-01 | Claude fixture：prompt+last_assistant_message → POST 含 question/answer/`client=claude_code` | unit | `uv run pytest tests/hooks/test_session_capture_hooks.py -x` | ❌ Wave 0 |
| SKILL-01 | Cursor fixture：prompt+text → 同 helper、`client=cursor` | unit | 同上 | ❌ Wave 0 |
| SKILL-02 | dirty 与 clean git tree 均 POST Capture；project knowledge 仅 dirty | unit | 同上 | ❌ Wave 0 |
| SKILL-03 | Cursor 资产无 `last_assistant_message`、无 UserPromptSubmit 注入、无 `afterAgentThought`；有 `beforeSubmitPrompt`+`afterAgentResponse`；stop 脚本无 `report_session_knowledge` | unit | `uv run pytest tests/initiatives/test_ide_hook_assets.py -x` | ✅ 需扩展 |
| SKILL-04 | 答案不含 thinking 块；stdout/stderr/cache 无 PAT/正文；skills+http-fallback 写明两工具分离 | unit | `test_skills_snapshot_guard.py` + hook tests | ✅ 部分（需扩展） |
| SKILL-05 | merge 保留自定义 hook；重复安装幂等；非法 JSON 不改文件；无 PAT exit 0；urlopen 抛错 exit 0 | unit | `node --test skills/lib/cursor-hooks-merge.test.mjs` + hook tests | ❌ Wave 0 |
| MCP-03 门禁 | 文档引用 `report_session_knowledge` ⊆ snapshot（已在 snapshot） | unit | `uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_mcp_package_alignment.py -x` | ✅ |
| MCP-04 | `report_project_knowledge` 测试零回归 | unit | `uv run pytest tests/mcp_tools/test_report_project_knowledge.py -x` | ✅ |

### Sampling Rate

- **Per task commit:** Quick run command
- **Per wave merge:** Full suite command
- **Phase gate:** Full suite green + `test_report_session_knowledge` 仍绿（不改服务端）后再 `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `server/tests/hooks/test_session_capture_hooks.py` — stdin JSON fixtures（Claude/Cursor × dirty/clean × 缺 PAT × 网络失败 × 重复 Stop × `stop_hook_active` × 空答案 × thinking 标签 × 无 git）
- [ ] `server/tests/hooks/conftest.py` — tmp_path 作 `XDG_CACHE_HOME`、patch urlopen
- [ ] `skills/lib/cursor-hooks-merge.test.mjs` — merge/幂等/非法 JSON/未知顶级键
- [ ] 扩展 `test_ide_hook_assets.py` — Cursor 采集事件与「无 Claude 注入进 stop」
- [ ] 扩展 `test_skills_snapshot_guard.py` — friday/friday-dev/friday-memory（及 http-fallback）必须同时出现 `report_session_knowledge` 与 `report_project_knowledge` 职责分离短语
- [ ] `skills/package.json` script `test` 调用 `node --test`（无新依赖）

现有 `test_write_path_cursor_stop_hook` 断言 `.cursor/hooks.json` 含 `stop` — **更新而非删除**：仍可含 `stop`（项目记忆），必须**另**含 `afterAgentResponse`。

## Security Domain

`security_enforcement` 启用（ASVS L1）。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | PAT/Bearer 已有解析；缺则 skip；不内嵌密钥 |
| V3 Session Management | no | 不发 Friday session cookie |
| V4 Access Control | yes (server) | 现 MCP 成员/仓权限；客户端不绕过 |
| V5 Input Validation | yes | 只 `json.loads` dict；prompt/answer 当数据不进 shell 展开；截断长度 |
| V6 Cryptography | no new | 不手写加密；文件权限 0600 |

### Known Threat Patterns for IDE hooks

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| PAT 进 stdout / 云日志 | Information Disclosure | 永不 print token；curl `-o /dev/null`；urllib 异常不附 body |
| 问答正文进仓库 | Information Disclosure | cache 仅 `~/.cache`；TTL；不写 `.cursor/` |
| Prompt 注入进 hook stdout | Tampering | Cursor beforeSubmit 不注入；Claude 注入仍仅 lookup 上下文 |
| `followup_message` 自动再问 | Elevation / DoS | Capture 路径不写 Cursor stop 输出 |
| `failClosed: true` 阻断编码 | Denial of Service | 禁止；默认 fail open |
| 命令注入 | Tampering | python 传 JSON 字符串 argv/stdin，不用 `eval`/`os.system(prompt)` |
| 错配泄漏他会话 | Information Disclosure | session+generation 配对；失败 skip |
| user_email 入账本 | Information Disclosure | 提取器忽略 `user_email` |
| CoT / transcript 上传 | Information Disclosure | 白名单字段；禁止读文件 transcript |

观测：本阶段**不新增** Django 入口或 LLM `call_source`。服务端 caller 事件已由 `ReportSessionKnowledgeView` 覆盖。客户端失败不得打 INFO 刷屏；静默 exit 0。

## Project Constraints (from .cursor/rules/)

来源：`.cursor/rules/observability-logging.mdc`（仓库内唯一 always-apply rule）。

- `structlog` kv 事件；不把变量拼进 message。本阶段客户端 hook **不要**引入 structlog；服务端不改则无需新事件。
- 脱敏不可绕过：PAT/问答/上游 body 不得进 hook 日志或 cache。
- 后台任务需 `initiated_by_user_id`：writeback 经用户 PAT 的 MCP，沿用 `request.user`。
- 观测 best-effort，不反噬：hook 永远 exit 0。
- 不新增运行时依赖（与 PROJECT / ROADMAP locked decisions 一致）。

GSD：实现前走 `/gsd-execute-phase`；本文件只研究不编码。

## Prior Phases (141–144) — what not to rebuild

| Phase | Status | Implication for 145 |
|-------|--------|---------------------|
| 141 | VERIFICATION passed | `CaptureService.persist`；空 session→`unspecified`；空标量→`unknown` |
| 142 | passed | POST 路径与 12 键契约冻结；`client` 只进 `ToolCallRecord` 不进 Capture 行 |
| 143 | passed | persist 后 durable eval；客户端不要等评估结果 |
| 144 | passed | **不要**用 lookup 的 `project_id` 回填 Capture；默认分支不误绑 |

## Sources

### Primary (HIGH confidence)

- https://cursor.com/docs/hooks.md — `version: 1`；`beforeSubmitPrompt` `{prompt,attachments}` → `{continue,user_message}`；`afterAgentResponse` `{text}`；`stop` `{status,loop_count}` + `followup_message`；`afterAgentThought` thinking；common `conversation_id`/`generation_id`/`transcript_path`；`session_id`≡`conversation_id` on sessionStart；cloud 只用项目 hooks；`failClosed` 默认 false
- https://code.claude.com/docs/en/hooks — UserPromptSubmit `{prompt,session_id}` + `hookSpecificOutput.additionalContext`；Stop `{last_assistant_message,stop_hook_active}`；勿用滞后 `transcript_path`；UserPromptSubmit 默认超时 30s；exit 2 会阻断 prompt
- `skills/hooks/{hooks.json,user-prompt-submit,stop,session-start}` — 现行 Claude 插件行为
- `server/initiatives/services/ide_hook_assets.py` + `server/tests/initiatives/test_ide_hook_assets.py`
- `skills/lib/installer.mjs` — 无 Cursor hooks merge（缺口）
- `server/mcp_tools/serializers.py` `ReportSessionKnowledgeRequestSerializer` + `TOOL_SCHEMA_SNAPSHOT`
- `mcp/src/tools.ts` `report_session_knowledge`
- `server/tests/mcp_tools/test_skills_snapshot_guard.py` — 文档 ⊆ snapshot + friday-solution 不变量模式
- `.planning/phases/141-capture/141-VERIFICATION.md` … `144-capture/144-VERIFICATION.md`
- `.planning/phases/145-cursor-claude-code/145-CONTEXT.md`

### Secondary (MEDIUM confidence)

- `.planning/research/STACK.md` / `FEATURES.md` — 与官方一致的采集点；installer 缺口
- `.planning/research/PITFALLS.md` — Cursor 注入限制仍正确；「不要 Cursor hook」已被 CONTEXT 覆盖

### Tertiary (LOW confidence)

- Cursor 各版本是否始终在 before/after 上填充 `generation_id` — 用兼容提取器降级

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，复用已验证 hook HTTP
- Architecture: HIGH — 官方 schema + 仓内接缝；MEDIUM — 配对 fallback 与是否保留 Cursor stop 记忆
- Pitfalls: HIGH — empty-diff、错配、merge 覆盖、CoT 字段均有官方或仓内证据

**Research date:** 2026-08-28  
**Valid until:** 2026-09-27（IDE hook schema 变化快；超 30 天应复核 cursor.com/docs/hooks）
