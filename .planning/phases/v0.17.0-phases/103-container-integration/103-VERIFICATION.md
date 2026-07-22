---
phase: 103-container-integration
verified: 2026-07-22T06:54:18Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "真实容器端到端：runner 派发一个编码任务，容器内 agent 实际调用 friday-knowledge MCP 工具（如 search_rag_chunks）"
    expected: "工具返回真实检索结果；服务端 InteractionRun.raw_request.task_session_id 可按 session 关联查到该次调用；RequestMetric source=mcp 有对应行"
    why_human: "自动化验证只覆盖到进程内 mock/单测层；真实 HTTP 链路（容器网络→服务端认证→检索）需要跑起 runner + 服务端联调"
  - test: "真实镜像构建：docker build task/ 后容器内 /opt/friday/skills/{friday-code,friday-memory} 存在，任务 workspace 出现 .claude/skills/ 注入"
    expected: "镜像含两个 skill 目录且内容与 skills/skills/ 一致；运行时注入日志 skills_injected 可见"
    why_human: "Dockerfile COPY 与运行时注入的组合效果只有真实构建+运行才能确认（单测用 tmp_path 模拟）"
  - test: "行为性：容器内 agent 是否实际可见并遵循 friday-code / friday-memory skills（setting_sources=[project] 加载生效）"
    expected: "agent 输出体现 skill 指引（如按 friday-code 约定先查知识再动手）"
    why_human: "LLM 行为遵循性无法 grep 验证"
  - test: "终态吊销时效：真实任务完成后用容器 env 里的 token 再调 /api/mcp/tools/*"
    expected: "401/403，agent 收到「令牌已失效或无权限」固定文案，容器不崩"
    why_human: "吊销五点已有单测（HTTP/WS handler 直调），但真实回调时序与容器内 401 降级路径需集成环境确认"
---

# Phase 103: 编码容器集成 Verification Report

**Phase Goal:** 编码容器不再是"知识贫民区"——三条派发链路统一铸造任务级短 TTL token，容器内代理经进程内 SDK MCP server 主动查 Friday 知识，friday-code/friday-memory skills 同源注入容器，工作流派发对齐 `pack_project_context`。
**Verified:** 2026-07-22T06:54:18Z
**Status:** human_needed（自动化 5/5 全过，4 项需人工/集成环境确认）
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（ROADMAP 5 条 Success Criteria）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 三链派发铸造任务级短 TTL token（明文内存→env、DB sha256、expires=timeout+余量、终态吊销、PAT-02 不违反） | ✓ VERIFIED | `access_tokens/services.py` `mint_task_token`（`generate_pat()` 内存明文、`acreate` 只落 `hash_token`、`expires_at=now+timeout+10min`）；迁移 `0003_accesstoken_kind_session_id.py` 存在；chat 链 `chat/coding_session_service.py:417-445`（`task_type!="coding_commit"` mint→`env_FRIDAY_TASK_USER_TOKEN`）；MCP 链 `mcp_tools/execution_service.py:138,168`（`initiating_user`→`_create_bridge_session(created_by=)`，views.py:1588/2143 + work_item_execution_service.py:296/574 透传）；workflow 链 `workflows/nodes/ai/coding.py:1913-1921`（`_resolve_dispatch_user`→mint）。五点吊销真实存在：`subagent/api/callbacks.py:864,948` + `runners/consumers.py:427,505,810`（completed/failed×2 + 断连收敛）。死通道守门：`rg user_pat_plaintext\|_resolve_user_pat\|set_request_pat\|get_request_pat server/` 零命中。测试 `test_task_token_lifecycle.py` 等 45 passed |
| 2 | 容器代理可调 7 个白名单只读知识工具，日志+RetrievalTrace 经关联键可查，第七面排除回归 | ✓ VERIFIED | `task/core/knowledge_tools.py`（435 行实现）：`KNOWLEDGE_TOOL_SCHEMAS` 硬编码恰好 7 条（search_rag_chunks/grep_repository/get_repository_file/search_delivery_knowledge/search_learning_cases/search_project_context/lookup_project_by_branch）；handler return-not-raise 全路径（httpx.HTTPError 捕获、非 JSON 兜底）、`timeout=60.0`、非 200 不回显响应体、401/403 固定文案、日志只记 tool/status/duration_ms/quota_used；`X-Friday-Session-Id` 头下发→服务端 `interactions/entry.py:111-113` 写 `raw_request["task_session_id"]`。第七面回归测试 `server/tests/mcp_tools/test_container_knowledge_chain.py`（289 行，5 例：get_repository_file .env→404 file_excluded 无明文 / grep 剔除 .env / search_rag_chunks fail-closed 滤除 / 关联键双向）——实际运行通过 |
| 3 | env 三要素降级不挂 + allowed_tools 单一构造函数合并（Bash/Edit/Write 断言）+ 配额文案 + 无 friday_pat_ 泄漏 | ✓ VERIFIED | `build_knowledge_mcp_server`：endpoint/token 任一空→`return None`（knowledge_tools.py:388-389）；`executor.py:87 _build_tool_mounts` 为三源合并唯一收口点，无挂载返回 `({}, [])` 零回归，任一挂载即全量并入 `_BUILTIN_CODING_TOOLS`；WR-02 专项测试 `test_knowledge_alone_keeps_builtin_tools` / `test_three_sources_merge_union_with_builtin_no_dupes` 断言 Bash/Edit/Write 在列。配额闭包计数器 + `QUOTA_EXHAUSTED_TEXT`（agent 可理解、不带 is_error）。泄漏防线：chat `last_output.dispatch` 落库副本剔除 `env_FRIDAY_TASK_USER_TOKEN`（coding_session_service.py:479-481，103-01 发现的泄漏点已堵）；`rg friday_pat_ server/`（排除 tests/access_tokens）命中均为脱敏正则（redaction.py `_PAT_PATTERN`、common/logging.py）与注释，无明文拼接点；task 侧 233 passed 含降级/泄漏单测 |
| 4 | skills 同源注入（sync 脚本 + assets + Dockerfile COPY + 运行时同名不覆盖 + hash 一致性测试） | ✓ VERIFIED | `task/scripts/sync_skills.py` 存在；`task/assets/skills/{friday-code,friday-memory}/`（SKILL.md + references）已入库；`task/Dockerfile:69` `COPY --chown=friday:friday assets/skills/ /opt/friday/skills/`；`runner.py:171 _inject_skills`（源缺失 debug 静默、同名跳过不覆盖、全程吞异常只 warning，路径与 Dockerfile 一致）。hash 一致性测试实际执行且通过（非 skip）：`test_assets_match_source[friday-code/friday-memory] PASSED`——assets 与 `skills/skills/` 子模块逐文件 sha256 一致，双源无漂移；注入 4 例单测全过 |
| 5 | workflow 派发 prompt 含 pack_project_context 输出（(project,branch) 解析一次逐仓复用，与 chat 一致）+ 容器 MCP 入口纳入观测 | ✓ VERIFIED | 共享 helper `services/project_context_packer.py`（`prepend_project_context`/`aresolve_project_for_repo_branch`/`apack_dispatch_context` 均导出）；workflow `coding.py:535 _resolve_wave_project_contexts` 按 `packed_by_project[key]` 去重缓存（:589-593），`_run_repo_coding` prompt prepend + `env_FRIDAY_TASK_PROJECT_CONTEXT`（:1837-1840，镜像 chat 两件套）；chat 改调同一 helper（`_prepend_project_context` 私有版零残留）。复用断言 `await_count==1` 两处（test_coding_dispatch_project_context.py:317,425），6 例 + chat 上下文 13 passed。观测：`mcp_tools/views.py:293 _record` 每次工具调用写 `RequestMetric(source=mcp, route=mcp:{tool}, duration_ms, labels.call_source/run_id)`——QPS/错误率/时长三要素齐 |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/access_tokens/services.py` | mint/revoke 统一入口 | ✓ VERIFIED | 93 行实证实现，含 PAT-02 语义 docstring |
| `server/access_tokens/migrations/0003_accesstoken_kind_session_id.py` | kind/session_id 迁移 | ✓ VERIFIED | 存在；models.py 字段带 db_index |
| `task/core/knowledge_tools.py` | 7 工具白名单 MCP server | ✓ VERIFIED | 435 行，schemas/handler/守门/配额全实 |
| `task/core/executor.py::_build_tool_mounts` | allowed_tools 合并唯一收口 | ✓ VERIFIED | :87-155，`_execute_claude` :663 调用（WIRED） |
| `task/scripts/sync_skills.py` + `task/assets/skills/**` | 同源物料 | ✓ VERIFIED | 均存在，hash 测试证明与子模块一致 |
| `task/Dockerfile` COPY + `runner.py::_inject_skills` | 构建期+运行时注入 | ✓ VERIFIED | 路径两处一致 `/opt/friday/skills`；注入点在 `git_ops.setup()` 后（runner.py:103） |
| `server/services/project_context_packer.py` 三 helper | 派发链共享 | ✓ VERIFIED | `__all__` 导出；chat/workflow 双调用方（WIRED，workflow 不 import chat） |
| 测试文件 5 个（lifecycle/knowledge_tools/container_knowledge_chain/skills_injection/coding_dispatch_project_context） | 实测通过 | ✓ VERIFIED | 全部存在且本次验证实际运行通过 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| chat `dispatch_coding_task` | `mint_task_token` | coding_session_service.py:429 | WIRED | coding_commit 短路；user 不可解析降级 |
| MCP `ExecuteCodingPlanView`/`ExecuteWorkItemRepoTasksView` | 桥接 Conversation.created_by | views.py:1588/2143→execution_service.py:168 | WIRED | `initiating_user` 全链透传 |
| workflow `_run_repo_coding` | `mint_task_token` + KNOWLEDGE_ENDPOINT | coding.py:1912-1921→:1963 tools_env 注入 dispatch | WIRED | timeout 取 config，session_id=execution 维度 |
| 任务终态（HTTP callbacks + WS consumers ×5 点） | `arevoke_task_tokens` | callbacks.py:864,948 / consumers.py:427,505,810 | WIRED | service 吞异常 + WS 点再套 try/except |
| 容器 handler | 服务端 `/api/mcp/tools/<name>/` | httpx POST + Bearer + X-Friday-Session-Id（knowledge_tools.py:284-293） | WIRED | 服务端 entry.py:111 接收入 raw_request |
| `_build_tool_mounts` | `_execute_claude` options | executor.py:663 | WIRED | 散装 merge 已替换，收口点唯一 |
| Dockerfile `/opt/friday/skills` | workspace `.claude/skills/` | runner.py:103 `_inject_skills` | WIRED | 经 executor 既有 `setting_sources=["project"]` 加载 |
| `_dispatch_wave` | `apack_dispatch_context` | coding.py:650→:590（project 维度缓存） | WIRED | 结果传 `_run_repo_coding(project_context=)` prepend+env |

### Behavioral Spot-Checks（测试套件实际执行）

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| server 定向套件（lifecycle+remote_dispatch+access_tokens+subagent+workflow context+第七面） | `uv run pytest tests/test_task_token_lifecycle.py tests/test_remote_tool_dispatch.py tests/test_access_tokens.py tests/subagent tests/workflows/test_coding_dispatch_project_context.py tests/mcp_tools/test_container_knowledge_chain.py -q` | **45 passed** | ✓ PASS |
| chat 上下文一致 + coding_wave | `uv run pytest tests/chat/test_coding_dispatch_context.py tests/test_coding_wave.py -q` | **13 passed** | ✓ PASS |
| task 全量 | `cd task && uv run pytest tests/ -q` | **233 passed, 3 skipped**（skip 均为既有 FRIDAY_RUN_INTEGRATION_TESTS 集成钉，与本 phase 无关） | ✓ PASS |
| skills hash 一致性（防双源漂移） | `uv run pytest tests/test_skills_injection.py -v` | 6 passed，`test_assets_match_source[*]` 实际执行 PASSED（非 skip） | ✓ PASS |
| 死通道守门 | `rg "user_pat_plaintext\|_resolve_user_pat\|set_request_pat\|get_request_pat" server/` | 零命中 | ✓ PASS |
| friday_pat_ 泄漏面 | `rg "friday_pat_" server/`（排除 tests/access_tokens） | 命中均为脱敏正则/前缀闸门注释，无明文拼接点 | ✓ PASS |

注：用户指令中的已知烂尾失败（tests/knowledge/test_triggers.py ×3、test_plan_generation_node_still_works）不在本次运行的套件内，未触发。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| AGENT-01 | 103-01 | 任务级短 TTL token 三链覆盖 | ✓ SATISFIED | Truth 1 全部证据 |
| AGENT-02 | 103-02 | 容器知识 MCP 7 工具白名单 | ✓ SATISFIED | Truth 2/3 证据 + MCP 入口观测 |
| AGENT-03 | 103-03 | skills 同源注入 | ✓ SATISFIED | Truth 4 证据 |
| AGENT-04 | 103-04 | 工作流上下文对齐 | ✓ SATISFIED | Truth 5 证据 |

无 ORPHANED 需求（REQUIREMENTS.md 映射 Phase 103 的四条均被 plans 认领）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `server/workflows/nodes/ai/coding.py` | 1994 | `metadata={"placeholder": True}` | ℹ️ Info | 既有代码（main_session 必需 FK 缺失时的占位创建，非本 phase 引入的 stub），不影响目标 |

本 phase 触及文件无 TBD/FIXME/XXX 债务标记。SUMMARY 声明的 10 个提交（a8e9a49c/48f98efd/af02b945/17813002/9c815b2e/dcf073eb/4790e874/fb8994c7/81956173/113ac520）全部在 git log 中。

### Human Verification Required

#### 1. 真实容器端到端知识工具调用

**Test:** runner 派发一个编码任务，容器内 agent 实际调用 friday-knowledge MCP 工具（如 search_rag_chunks）
**Expected:** 工具返回真实检索结果；`InteractionRun.raw_request.task_session_id` 可按 session 关联查到；RequestMetric source=mcp 有对应行
**Why human:** 单测层 mock 了 HTTP/SDK；真实容器网络→服务端认证→检索链路需联调

#### 2. 真实镜像构建与 skills 注入

**Test:** `docker build task/` 后运行任务容器，检查 `/opt/friday/skills/` 与 workspace `.claude/skills/`
**Expected:** 镜像含 friday-code/friday-memory；注入日志 `skills_injected` 可见
**Why human:** Dockerfile COPY 效果只有真实构建能确认

#### 3. skills 行为遵循性

**Test:** 观察容器内 agent 是否实际遵循 friday-code / friday-memory skill 指引
**Expected:** agent 行为体现 skill 约定（先查知识再动手等）
**Why human:** LLM 行为无法 grep 验证

#### 4. 终态吊销时效

**Test:** 真实任务完成后用容器 env 中的 token 再调 `/api/mcp/tools/*`
**Expected:** 401/403，agent 收到固定降级文案，容器不崩
**Why human:** 真实回调时序与容器内 401 降级路径需集成环境

### Gaps Summary

无阻塞 gap。5 条 Success Criteria 全部在代码中找到实质实现且经测试套件实际运行验证（server 定向 58 passed、task 全量 233 passed / 3 skipped 均为既有集成钉）。SUMMARY 声明与代码实况一致，含 103-01 执行期发现并修复的 chat `last_output.dispatch` 落库泄漏点（副本剔除 token 键，代码 + 测试双确认）。剩余 4 项为需要真实容器/镜像/集成环境的人工验证项。

---

_Verified: 2026-07-22T06:54:18Z_
_Verifier: Claude (gsd-verifier)_
