# Phase 113: Context Bus 与容器 MCP 面 - Research（事实文档）

**Researched:** 2026-07-30
**Domain:** 容器 MCP 工具面扩展 / 会话级共享上下文总线 / 等待-重派编排
**Confidence:** HIGH（全部事实经本仓源码定位，带 `文件:行号`；无外部检索依赖）
**Scope:** 严格限定 5 主题 + Pitfalls；不覆盖 RepoPlan schema / merge 装配（另文）

## Summary

本文档为 Phase 113 的 Blueprint Context Bus 与容器 MCP 扩面提供**可直接照抄的坐标**。三条硬结论：

1. **容器 MCP 扩工具是「三处对称新增」**：task 侧 `KNOWLEDGE_TOOL_SCHEMAS` 加一项 + server 侧 `views.py` 加一个 `McpToolView` 子类 + `urls.py` 加一条 path（外加 `serializers.py` 一个 RequestSerializer）。handler 工厂、鉴权、脱敏、配额、错误约定全部零改动复用。
2. **鉴权链不是「task token → session → user」**：`AccessTokenAuthentication` 直接返回 `(token.created_by, token)`，`request.user` 即 token 所有者；`session_id` 仅经 `X-Friday-Session-Id` 头传递、只做关联留痕。因此 Context Bus 的「只能写本会话」必须在 **view 层自己实现**（header session → `SubAgentSession.last_output.blueprint_session_id` → 与入参会话比对 + 用户成员校验），不存在框架层自动约束。
3. **短等待原语应走「容器侧有界轮询 MCP 读工具」而非服务端长轮询**：容器侧 httpx 硬上界 `timeout=60.0` 已封死长连接空间，且 `ask_user` 的轮询骨架（心跳保活 + deadline + 命中即返回 + 超时降级）可逐行复用，只把数据源从共享卷 `answer.json` 换成 `read_blueprint_context(since_seq=...)`。服务端零新增长连接、零 ASGI worker 占用。

**Primary recommendation:** 复用 `ask_user` 轮询骨架 + `read_blueprint_context` 增量拉取实现 `await_blueprint_context`；`BlueprintContextEntry.seq` 用「锁父 `ConvergenceSession` 行 + `Max("seq")+1` + `UniqueConstraint(session, seq)` 兜底」分配；总线沉淀只调 `MemoryService.create_draft` / `MemoryDistiller.distill_to_draft`，绝不碰 `append` / `confirm_draft`。

---

<user_constraints>
## User Constraints (from 113-CONTEXT.md)

### Locked Decisions（与本文档 5 主题相关的部分，逐字摘录）

- 新模型 `delivery.BlueprintContextEntry`：`convergence_session FK / project FK / key / kind(finding|api_surface|contract|decision|dependency_claim|question) / repository_id / content JSON / produced_by / seq(会话内单调) / status(active|superseded)`；**不复用 `ProjectMemory`**（那是项目级长期记忆、打包预算仅 30 条，高频调研写入会污染它）
- key 约定前缀：`repo:{id}.api_surface` / `contract:{name}` / `decision:{thread_id}` / `dependency:{from}->{to}`
- 容器实时读写：扩容器知识 MCP 白名单新增 `read_blueprint_context`（支持 key_prefix / kind / repository_id / since_seq 增量拉取）与 `report_blueprint_context`（服务端校验只能写本会话、内容过 `redact_secrets_in_text`）；写入即对所有并行容器可见（server-authoritative）
- 等待原语两档：
  - **短等待**：`await_blueprint_context(key_pattern, timeout)`——机制对齐既有 `ask_user` 先例（容器保持 RUNNING + 轮询），命中即返回，超时返回未命中由 agent 自行降级（记录假设 + 开澄清线程），绝不无限挂
  - **长等待**：容器以 `waiting_context` 结构化结果**退出**（携 partial 产物 id + 等待声明），编排层登记依赖，目标条目就绪后**重新派发**该仓容器（prompt 带 partial 引用续作）——复用 waiting_event + barrier 与 112 的增量派发白名单
- 第一道防线是 wave 预排：repo_plan 阶段按 API provider/consumer 关系预排波次（provider 仓先行），`await` 只兜预排不出来的动态依赖，避免退化成人人互等
- 死锁防护：编排层检测互相等待环（A 等 B、B 等 A）→ 立即判定并抛澄清由用户裁决，不靠超时兜底
- 沉淀：会话结束后有长期价值的条目走 distill 管道产 `ProjectMemory` 草案（人工 confirm 生效，遵守「AI 不覆盖人工」）
- 观测：总线条目读写记 `sampling`，waiter 登记/命中/超时与「谁在等谁」记 `caller` 事件（`component=process_runtime`，容器动作归属 dispatch 用户）并写 `ConvergenceSessionEvent`（blueprint_* 既有类型）
- `call_source` 复用 111 已注册的 `blueprint_repo_plan` / `blueprint_merge`，**不新增枚举值**

### Claude's Discretion

- 总线 key 命名细节、波次预排算法实现、测试组织自行决定，遵循 CONVENTIONS.md 与 111/112 已建立的 blueprint_* 模块风格。

### Deferred Ideas（OUT OF SCOPE）

- 总线条目的跨会话复用（当前仅会话级）→ 观察 distill 效果后再议
</user_constraints>

---

## 主题 1：容器 MCP 扩工具的确切做法

### 1.1 task 侧：白名单 + handler 工厂（`task/core/knowledge_tools.py`）

结构是「schema 声明表 + 一个 handler 工厂 + 一个 build 函数」，扩工具**只需往表里加一项**：

| 坐标 | 内容 |
|------|------|
| `task/core/knowledge_tools.py:44` | `KNOWLEDGE_MCP_SERVER_NAME = "friday-knowledge"` |
| `task/core/knowledge_tools.py:47` | `QUOTA_EXHAUSTED_TEXT`（配额用尽文案，不带 `is_error`） |
| `task/core/knowledge_tools.py:52` | `KNOWLEDGE_TOOL_SCHEMAS: list[dict[str, Any]]` —— 7 工具白名单，task 侧硬编码 |
| `task/core/knowledge_tools.py:238` | `_is_valid_knowledge_endpoint(endpoint)` —— scheme ∈ {http,https} 且有 netloc |
| `task/core/knowledge_tools.py:253` | `_make_knowledge_handler(tool_name, endpoint_base, user_token, session_id, quota, quota_counter)` |
| `task/core/knowledge_tools.py:374` | `build_knowledge_mcp_server(endpoint_base, user_token, session_id, quota)` |
| `task/core/knowledge_tools.py:436` | `knowledge_allowed_tools()` → `mcp__friday-knowledge__{name}` |

**完整工具定义模板**（`knowledge_tools.py:53-80`，`search_rag_chunks`，逐字）：

```python
{
    "name": "search_rag_chunks",
    "description": (
        "语义检索代码库：用自然语言问题召回相关代码片段（RAG）。"
        "适合「某功能在哪实现」「某概念相关代码」类问题。"
        "必须提供 repository_id / repository_ids，或设 all_repositories=true 跨仓检索。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言检索问题（必填）"},
            "repository_id": {"type": "string", "description": "单仓 UUID"},
            "repository_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "多仓 UUID 列表",
            },
            "all_repositories": {
                "type": "boolean",
                "description": "显式跨全部已索引仓检索",
            },
            "branch": {"type": "string", "description": "分支名（仅单仓时可指定）"},
            "top_k": {"type": "integer", "description": "返回条数上限（默认 30，最大 50）"},
            "max_tokens": {"type": "integer", "description": "结果 token 预算（默认 8000）"},
        },
        "required": ["query"],
    },
},
```

**handler HTTP 调用形状 + 鉴权头 + 错误处理约定**（`knowledge_tools.py:267-369`，逐条事实）：

| 行号 | 事实 |
|------|------|
| `:267` | `url = f"{endpoint_base.rstrip('/')}/api/mcp/tools/{tool_name}/"` —— **URL 由 tool_name 拼接，新工具零改动自动可达** |
| `:272-284` | 配额短路：`quota_counter[0] >= quota` → 直接返回文案，**不发 HTTP**；`== quota` 时只 warning 一次（计数器越界一格作哨兵） |
| `:285` | `quota_counter[0] += 1` —— 7 工具共享同一闭包计数器 |
| `:289-299` | `httpx.AsyncClient().post(url, json=args, headers={...}, timeout=60.0)`；**body 直接是业务参数 dict**（无 `{name, arguments}` 信封） |
| `:293-297` | 鉴权头三件套：`Authorization: Bearer {user_token}` / `X-Friday-Session-Id: {session_id}` / `Content-Type: application/json` |
| `:300-310` | `httpx.HTTPError` → `{"content":[...], "is_error": True}`，**不冒泡** |
| `:315-326` | 401/403 → 固定文案「知识工具不可用：令牌已失效或无权限」 |
| `:329-340` | 其余非 200 → **只回显 HTTP code，绝不回显响应体**（T-103-05） |
| `:345-360` | `resp.json()` 非 dict → 「响应解析失败：非 JSON 响应」（兜住反代 200 + text/html） |
| `:362-368` | `logger.info("knowledge_tool_called", tool=, status=, duration_ms=, quota_used=)` —— 只记这 4 个字段 |
| `:369` | 成功返回 `{"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}` |

**挂载点与空值短路**（`task/core/executor.py`）：

| 行号 | 事实 |
|------|------|
| `executor.py:136-141` | `build_knowledge_mcp_server(config.knowledge_endpoint, config.user_token, task_id, config.knowledge_quota)` |
| `executor.py:142-144` | 非 None → `mcp_servers[KNOWLEDGE_MCP_SERVER_NAME] = server` + `mounted_allowed.extend(knowledge_allowed_tools())` |
| `knowledge_tools.py:394-395` | **空值短路**：`if not endpoint_base or not user_token: return None`（三要素守门，存量任务零回归） |
| `knowledge_tools.py:399-406` | 端点非法 → 只记 scheme 的 warning + `return None`，绝不向不可信端点注入 PAT |
| `executor.py:149-150` | `if not mcp_servers: return {}, []`（options 不含 mcp_servers/allowed_tools，与现状逐字一致） |
| `executor.py:152-158` | ⚠️ **`allowed_tools` 是排他白名单**：remote/knowledge 任一挂载才并入 `_BUILTIN_CODING_TOOLS`；缺列会连带禁掉 Bash/Edit/Write（WR-02 前科） |

**`FRIDAY_TASK_*` 配置项清单**（`task/core/config.py`，`env_prefix="FRIDAY_TASK_"` 在 `:23`）：

| 字段 | env 键 | 默认 | 行号 |
|------|--------|------|------|
| `user_token` | `FRIDAY_TASK_USER_TOKEN` | `""` | `:86` |
| `tools_endpoint` | `FRIDAY_TASK_TOOLS_ENDPOINT` | `""` | `:90` |
| `remote_tools` | `FRIDAY_TASK_REMOTE_TOOLS`（JSON） | `[]` | `:94` |
| `knowledge_endpoint` | `FRIDAY_TASK_KNOWLEDGE_ENDPOINT`（裸 base，无路径） | `""` | `:101` |
| `knowledge_quota` | `FRIDAY_TASK_KNOWLEDGE_QUOTA` | `200` | `:108` |
| `exclude_patterns` | `FRIDAY_TASK_EXCLUDE_PATTERNS`（JSON） | `[]` | `:117` |
| `follow_openspec` | `FRIDAY_TASK_FOLLOW_OPENSPEC` | `False` | `:125` |
| `callback_url` | `FRIDAY_TASK_CALLBACK_URL` | `""` | `:131` |
| `commit_message` | `FRIDAY_TASK_COMMIT_MESSAGE` | — | `:164` |
| `max_turns` | `FRIDAY_TASK_MAX_TURNS` | `50` | `:80` |
| （非 TASK 前缀） | `FRIDAY_REPO_REFERENCE` / `FRIDAY_DEPS_CACHE_PATH` / `FRIDAY_DEPS_MANAGER` | — | `:174/:179/:184` |

派发侧注入（`server/services/process_runtime/blueprint_research_adapter.py`）：`:524` `env_FRIDAY_TASK_TOOLS_ENDPOINT = f"{base}/api/tools/execute/"`；`:526` `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT = base`（**裸 base**，task 侧自拼路径）；`:533` `env_FRIDAY_TASK_USER_TOKEN = await mint_task_token(...)`；`:449-450` 埋点只记 `has_user_token` / `has_knowledge_endpoint` 布尔。

### 1.2 server 侧：`api/mcp/tools/{name}/` 的 view 分发与新增位置

**分发方式：一 path 一 View 类，无动态 name 分发。** `server/mcp_tools/urls.py:41-127` 是显式 `urlpatterns` 列表，每条形如：

```python
path("tools/report_project_state/", ReportProjectStateView.as_view(), name="mcp-tool-report-project-state"),
```

新增一个工具须动 **4 个位置**（无第 5 处，无注册表）：

| # | 文件 | 动作 |
|---|------|------|
| 1 | `server/mcp_tools/serializers.py` | 新增 `ReadBlueprintContextRequestSerializer` / `ReportBlueprintContextRequestSerializer` |
| 2 | `server/mcp_tools/views.py` | 新增 `McpToolView` 子类（设 `tool_name`，实现 `post`） |
| 3 | `server/mcp_tools/urls.py:5-39` + `:41-127` | import + 追加一条 `path("tools/<name>/", …)` |
| 4 | `task/core/knowledge_tools.py:52` | `KNOWLEDGE_TOOL_SCHEMAS` 追加一项（自动进 `knowledge_allowed_tools()`） |

**View 模板**（`server/mcp_tools/views.py:3330-3364`，`ReportProjectStateView`——写类工具的现成范式，含 fail-soft 约定）：

```python
class ReportProjectStateView(McpToolView):
    tool_name = "report_project_state"                      # :3350

    async def post(self, request: Request) -> Response:      # :3352
        run, err = await self._begin(request)                # :3353
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            ReportProjectStateRequestSerializer, request      # :3357-3359
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()                     # :3363
        return await self._handle(run, request, input_data, started_at)
```

`_handle` 内的收尾（`:3377-3385`）：`await self._record(run, input_data=, output_data=, traces=[], started_at=)` 后 `Response(output_data, status=200)`；`:3387-3394` `_skip(reason)` 返回 `{"applied": False, "reason": ..., "run_id": str(run.run_id)}`——**全路径 fail-soft，任何异常 → 200 + applied=false，绝不 5xx**（因为 5xx 会被容器 handler `:329` 吞成「调用失败」文案，agent 拿不到原因）。

**基类能力**（`server/mcp_tools/views.py:235-339`）：

| 行号 | 成员 | 事实 |
|------|------|------|
| `:235` | `class McpToolView(APIView)` | adrf 异步 APIView（`from adrf.views import APIView`，`:12`） |
| `:238` | `authentication_classes` | `[AccessTokenAuthentication, CookieJWTAuthentication]` |
| `:239` | `permission_classes` | `[IsAuthenticated]` |
| `:240` | `tool_name` | 子类必设，进指标 `labels.call_source` 与 `ToolCallRecord.tool_name` |
| `:242-249` | `handle_exception` | `AuthenticationFailed/NotAuthenticated` → `error_response("authentication_failed", …, 401)` |
| `:251-265` | `_begin` | `bind_source(LogSource.MCP)` + `request.auth is None` 纵深防御 + `begin_interaction_run(request, source="mcp")` |
| `:267-281` | `_validate` | serializer `is_valid` 经 `sync_to_async`；失败 → `error_response("invalid_params", …, 400)` |
| `:283-322` | `_record` | `arecord_request_metric(source=mcp, route=f"mcp:{tool_name}", labels={call_source, run_id})` + `arecord_tool_call` + 逐条 `arecord_retrieval_trace` |
| `:324-339` | `_record_agent_decision` | `InteractionEvent.EventType.AGENT_DECISION` |

错误信封由 `server/mcp_tools/errors.py` 的 `error_response(code, detail, status_code=)` 产出 `{"error_code", "detail"}` + 4xx/5xx（`knowledge_tools.py:9` 已核实）。

### 1.3 鉴权链在哪一层（**关键纠偏**）

链路是 **token → owner(User)**，不是 token → session → user：

| 行号 | 事实 |
|------|------|
| `server/access_tokens/authentication.py:52` | `class AccessTokenAuthentication(BaseAuthentication)` |
| `:60` | `def authenticate(request) -> tuple[User, AccessToken] | None`（**同步方法**，DRF 认证层） |
| 前缀闸门 | 非 `Bearer ` / 非 `friday_pat_` 前缀 → `return None` 让行给 `CookieJWTAuthentication`，**绝不 raise**（raise 会吞掉后续 JWT 认证类） |
| 不存在 token | 只 warning `access_token_denied reason=not_found` + `AuthenticationFailed`，**不建 run**（防乱 token 灌爆审计表） |
| 吊销/过期 | `_record_denial(..., reason="revoked_or_expired")`（`:120`）+ `AuthenticationFailed` |
| owner 停用 | `_record_denial(..., reason="owner_inactive")`，fail-closed |
| `:103` | `return (token.created_by, token)` —— **`request.user` = token 所有者真实 User；`request.auth` = AccessToken 实例** |

task token 铸造与吊销（`server/access_tokens/services.py`）：`:32` `async def mint_task_token(user, session_id, timeout_seconds) -> str`；`:43` `expires_in = timedelta(seconds=timeout_seconds) + TASK_TOKEN_EXPIRY_MARGIN`（+10 分钟余量）；`:46` `name=f"task:{session_id}"`，`kind="task"`；`:67` `async def arevoke_task_tokens(session_id) -> int`（按 session 幂等吊销）。派发失败即刻主动吊销：`blueprint_research_adapter.py:434-440`。

**⇒ 对 Context Bus 的直接影响（必须在 view 层自建的三道校验）**：

1. **会话归属**：`X-Friday-Session-Id` 头（`knowledge_tools.py:295`）→ `SubAgentSession.objects.filter(session_id=...)` → `last_output["blueprint_session_id"]`（写入坐标 `blueprint_research_adapter.py:404-409`）→ 与入参 `convergence_session_id` 比对。**不可只信入参**（容器可伪造入参，但头里的 session_id 是派发时服务端自己写的，见 `executor.py:139` 传的是 `task_id`）。
2. **用户权限**：`request.user`（= token owner）对该 `ConvergenceSession.project` 的成员校验；`ConvergenceSession` 自带 `created_by`（`convergence_session.py:104`）与 `initiated_by_user_id`（`:112`）可作归因基准。
3. **写入脱敏**：`report_blueprint_context` 的 `content` 入库前过 `redact_secrets_in_text`（见 Pitfalls 第 2 条，JSON 需递归处理）。

---

## 主题 2：短等待原语可复用面

### 2.1 `ask_user` 完整链路（逐段坐标）

**容器侧轮询**（`task/core/question_loop.py`）：

| 行号 | 事实 |
|------|------|
| `:35` | `ASK_USER_MCP_SERVER_NAME = "friday-ask-user"` |
| `:38-39` | `DEFAULT_PROTOCOL_DIR = "/workspace/.friday"`；`ANSWER_FILENAME = "answer.json"` |
| `:42` | `class QuestionTimeout(Exception)` |
| `:46-56` | `_read_answer(path)`：`json.load` → 取 `data["answer"]`；`OSError/ValueError` → `""`（容错） |
| `:59-72` | `ask_user_and_wait(callback, question, *, options, context, code_snippet, default_option, timeout_minutes=10, protocol_dir, poll_interval_s=3.0, _now=None, _sleep=None)` —— `_now`/`_sleep` 可注入，单测无需真实 sleep |
| `:86-95` | ① `callback.report_question(...)`；失败仅 `log.warning("ask_user_report_question_failed")`，**不抛**（共享卷仍可回灌） |
| `:98` | `deadline = now() + max(0, timeout_minutes) * 60` |
| `:99-114` | ② 有界轮询：读 answer → 命中则 `os.remove(answer_path)`（防下一轮误读陈旧答案）+ `log.info("ask_user_answer_received", has_answer=True)` + return；未命中则 `callback.report_status(status="progress", message="等待人工回答中")` **心跳保活** → `await sleep(3.0)` |
| `:117-121` | ③ 超时：有 `default_option` → 返回之；否则 `raise QuestionTimeout`。**绝不无限等、绝不触发 replan** |
| `:124-163` | `_make_ask_user_handler`：缺 question → `is_error`；`QuestionTimeout` → 「未在限定时间内收到人工回答」+ `is_error`；兜底 `except Exception` → `is_error`（RTOOL-04 永不 raise） |
| `:184-206` | `build_ask_user_mcp_server(config, callback)`：`:192` 无 `config.callback_url` → `return None`（向后兼容）；`:195` `protocol_dir = os.environ.get("FRIDAY_PROTOCOL_DIR", DEFAULT_PROTOCOL_DIR)` |
| `executor.py:106-107` | extra 源挂载：**调用方需 builtin 时须自行列入 `extra_allowed_tools`**（ask_user 先例：`[*_BUILTIN_CODING_TOOLS, *ask_user_allowed_tools()]`） |

**协议常量与共享卷**（`server/services/protocols.py`）：`:4` 宿主机 `server/data/transfers/{session_id}/.friday/` ↔ 容器 `/workspace/.friday/`；`:17` `CONTAINER_PROTOCOL_DIR`；`:23-24` `QUESTION_FILE = "question.json"` / `ANSWER_FILE = "answer.json"`；`:103` `CallbackType.QUESTION = "question"`；`:143-150` `QuestionPayload{question, options, context, default_option, timeout_minutes=10}`；`:154-159` `AnswerPayload{question_id, answer, answered_at}`。

**HTTP 直达活容器链（比共享卷更快的第二通路）**：

| 行号 | 事实 |
|------|------|
| `runner/internal/docker/executor.go:90` | `answerEndpoint = fmt.Sprintf("http://host.docker.internal:%s/answer", bindings[0].HostPort)` |
| `runner/internal/ws/client.go:466-489` | `StartContainer` 返回 `answerEndpoint` → 随 `task_accepted` 上报 `{"task_id":…, "answer_endpoint":…}` |
| `server/runners/consumers.py:187-189` | `task_accepted` 取 `payload["answer_endpoint"]` → `_store_answer_endpoint(task_id, …)` |
| `server/runners/consumers.py:373-380` | 存入 `SubAgentSession.last_output["answer_endpoint"]`（`asave(update_fields=["last_output","updated_at"])`） |
| `server/runners/protocol.py:26` | `QUESTION_ANSWER = "question.answer"`（server→runner WS 信封类型） |
| `runner/internal/ws/client.go:440-453` | runner 收 `question.answer` → 读 `payload["answer_endpoint"]` → POST `{"answer": …}`；失败仅 `log.Warn("question_answer_forward_failed")` |
| `server/chat/container_suspend_service.py` 头注释 | 「`handle_container_answer_enhanced` 经 WS / HTTP 直达活容器，绝不重复起容器」 |
| `server/services/process_runtime/answer_resume.py:44+` | `aanswer_round_and_resume(clarification_or_id, answers, *, engine=None, clarification_service=None)` —— 入口无关的「写答案 → 续驱 engine」helper（INV-6：写入只经 `ClarificationService.answer_round`） |

### 2.2 若走「MCP 长轮询」服务端需要什么（以及为什么不建议）

服务端长轮询的硬约束（全部有坐标）：

1. **容器侧硬超时 60s**：`knowledge_tools.py:298` `timeout=60.0` 写死在 handler 工厂里，不接受 per-tool 覆盖。服务端单次响应必须 < 60s，否则容器侧 `httpx.HTTPError` → `is_error` 文案，等待语义丢失（`:300-310`）。改这个超时意味着**改 handler 工厂签名**，影响全部 7 个既有工具。
2. **ASGI worker 占用**：每个挂起的长轮询占一个 daphne/uvicorn 协程 + 一条上游 HTTP 连接。N 个并行容器同时 await ⇒ N 条常驻连接。本仓无 SSE/长轮询先例可参照（`api/mcp/tools/*` 全部是即时返回）。
3. **无「等待唤醒」基础设施**：DB 变更没有 pub/sub 通道（channels layer 只用于前端 WS 推送）；服务端长轮询只能自己在 view 里 `asyncio.sleep` 轮询 DB —— 与容器侧轮询等价，但把资源成本从容器搬到服务端。
4. **配额语义冲突**：一次长轮询算 1 次配额（`knowledge_tools.py:285`），看似省配额，但代价是服务端连接；容器侧轮询则会快速消耗共享的 200 配额（`config.py:108`）。

### 2.3 推荐实现路径与理由 ✅

**路径：容器侧有界轮询 + 复用 `read_blueprint_context`（不新增服务端等待端点）。**

```
await_blueprint_context(key_pattern, timeout_minutes)   # task 侧新增，进 knowledge_tools 白名单
  ├─ deadline = now() + timeout_minutes*60              # 骨架照抄 question_loop.py:98
  ├─ while now() < deadline:
  │    ├─ 调 read_blueprint_context(key_prefix=…, since_seq=last_seq)   # 复用同文件 handler 工厂
  │    ├─ 命中 key_pattern → return 条目（question_loop.py:100-108 形状）
  │    ├─ 更新 last_seq（增量幂等，避免重复拉全量）
  │    └─ await sleep(poll_interval_s)                  # 建议 5.0~10.0，非 ask_user 的 3.0
  └─ 超时 → return 「未命中」结构化结果（不是 is_error）  # 让 agent 自行降级：记假设 + 开澄清线程
```

**理由（逐条对应本仓事实）**：

- **零服务端新增面**：`read_blueprint_context` 本就要建（CONTEXT 锁定项），`await` 只是它的循环包装 —— 不需要第三个 view、不需要长连接、不需要动 handler 工厂的 60s 超时。
- **骨架已验证**：`question_loop.py:98-121` 的 deadline + 心跳 + 命中即返回 + 超时降级四要素已在生产链路跑通，且 `_now`/`_sleep` 注入点让单测无需真实 sleep（`:70-71`）——「命中/超时」两条断言可零成本证伪。
- **保活语义天然继承**：轮询期间容器持续跑（有 MCP HTTP 调用即有活动），`SubAgentSession` 保持 RUNNING；若需要显式心跳，`callback.report_status(status="progress")`（`:111`）可照抄，但**注意** `await_blueprint_context` 属 knowledge MCP（无 `callback` 依赖），若要心跳需额外把 callback 传进 handler 工厂 —— 建议**不传**，靠 HTTP 调用本身的活动性即可（避免为一个工具改公共工厂签名）。
- **超时不报错**：与 `ask_user` 不同，超时应返回**正常结果**（`{"hit": false, "waited_ms": …}`）而非 `is_error` —— CONTEXT 明确要求「超时返回未命中由 agent 自行降级」，`is_error` 会诱导模型重试而非降级。
- **参数建议**：`poll_interval_s` 默认 `5.0`（每轮 = 1 次 HTTP + 1 次 DB 查询，3s 太密）；`timeout_minutes` 默认 `3`、上界 `5`（短等待定位是「兜预排漏掉的动态依赖」，超过 5 分钟应该走长等待退出重派）；轮询调用**建议不计入或单独计入 `knowledge_quota`**（否则 5 分钟 ÷ 5s = 60 次，占掉 200 配额的 30%）。

---

## 主题 3：长等待与重派

### 3.1 容器以结构化结果退出的现有约定

**`last_output.source` 是回调路由的唯一依据**（不靠 `session_id` 命名）：

| 行号 | 事实 |
|------|------|
| `blueprint_research_adapter.py:57-58` | `BLUEPRINT_RESEARCH_SOURCE = "blueprint_research"`；模块内别名 `_BLUEPRINT_RESEARCH_SOURCE` |
| `blueprint_research_adapter.py:388` | `session_id = f"bp-research-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}"` —— **必带 uuid 后缀**（stale 重跑对同一 task 再派发会撞 UNIQUE） |
| `blueprint_research_adapter.py:392-396` | `AgentSession.metadata = {"source": …, "blueprint_session_id": str(session.id)}` |
| `blueprint_research_adapter.py:404-409` | `SubAgentSession.last_output = {"source": "blueprint_research", "blueprint_session_id", "research_task_id", "repository_id"}` |
| `blueprint_research_adapter.py:417-430` | `DispatchTask(task_id=session_id, task_type="plan", …, timeout=_RESEARCH_TIMEOUT, metadata=metadata)` |
| `blueprint_research_adapter.py:432-433` | `with use_call_source(CallSource.BLUEPRINT_REPO_RESEARCH): await dispatcher.dispatch(task)` |
| `blueprint_research_adapter.py:442-455` | `mark_running` + `logger.info("blueprint_repo_research_container_dispatched", …, initiated_by_user_id=, category="caller", component="process_runtime")` + `_emit_started` |

**112 的 callbacks 第三链形状**（`server/subagent/api/callbacks.py`）：

| 行号 | 事实 |
|------|------|
| `:1963-1968` | 段注释：PLAN 任务类型的**第三种**用途（前两种 `plan_research` / `repo_verify`），三者靠 `last_output.source` 互斥路由；业务表写入全部经 `ResearchService`（INV-6，本段零裸 ORM 写） |
| `:1971` | `_BLUEPRINT_RESEARCH_SOURCE = "blueprint_research"`（回调侧独立常量，与派发侧同值） |
| `:1972-1983` | 枚举白名单 `_BLUEPRINT_VERDICTS` / `_BLUEPRINT_ROLES`，反幻觉上界 `_BLUEPRINT_MAX_FINDINGS = 20` / `_BLUEPRINT_MAX_TEXT = 4000`，透传键 `_BLUEPRINT_PASSTHROUGH_LIST_KEYS` |
| `:1986-1996` | `_is_blueprint_research(session)`：`task_type == PLAN and isinstance(last_output, dict) and last_output.get("source") == "blueprint_research"` |
| `:1999-2006` | `_parse_blueprint_fitness(output)`：优先结构化透传（`output` 含 `fitness`），否则从 `output["text"]` 提 JSON 围栏 / 花括号跨度再 `json.loads`；**`verdict` 非法即判不可解析返回 None**（宁可失败重跑也不落编造结论）；`role_suggestion` 非法回落保守 `direct` |
| `:991-998` | 完成钩子：`if _is_blueprint_research(session): await _handle_blueprint_research_completion(...)`，异常仅 warning `blueprint_research_completion_callback_failed` |
| `:1075-1082` | 失败钩子：`_handle_blueprint_research_failure` → `mark_failed` + `blueprint.repo_research.failed` + barrier |
| `:2090-2115` | `_aload_blueprint_research_task(session)`：从 `last_output` 取 `research_task_id` / `blueprint_session_id` → 加载 task 与 `ConvergenceSession` |

**⇒ `waiting_context` 退出的推荐形状**：沿用 `source="blueprint_research"`（**不新增 source 值**，否则要改互斥路由判定），在容器 output 里加一个与 `fitness` 平级的 `waiting_context` 段：`{"waiting_context": {"keys": [...], "partial_plan_id": "...", "reason": "..."}}`，回调侧在 `_handle_blueprint_research_completion` 里先探测 `waiting_context` → 走「登记 waiter + 不判完成」分支，否则走既有 fitness 落库分支。理由：`_is_blueprint_research` 判定不动、第三链互斥性不破、token 吊销与 barrier 钩子全部零改动继承。

### 3.2 编排层如何登记依赖并触发重派

**barrier → 续驱**（`callbacks.py:2118-2145`）：

```
_trigger_blueprint_research_barrier(blueprint_session)
  ├─ :2125  session is None → 返回
  ├─ :2129  not await aall_research_tasks_terminal(session.id) → 返回（还有在途，不叫醒）
  ├─ :2132  from services.process_runtime import blueprint_resume
  ├─ :2135  logger.info("blueprint_research_barrier_reached", session_id=…)
  └─ :2142-2145  resume = getattr(blueprint_resume, "aresume_blueprint_session", None); await resume(session)
              # 续驱器未就位时静默 no-op，回调不受影响
```

**续驱面**（`server/services/process_runtime/blueprint_resume.py`）：

| 行号 | 函数 |
|------|------|
| `:59` | `adrive_blueprint_session_to_pause_or_terminal(...)` |
| `:74/:101` | 内部调 `aall_research_tasks_terminal(session.id)` |
| `:113` | `aresume_after_gate_action(...)` |
| `:154` | `aresume_blueprint_session(session, *, engine=None)` —— **112-04 的接线契约，函数名即契约** |
| `:168/:180` | 埋点 `blueprint_barrier_resume_completed` / `blueprint_barrier_resume_failed` |
| `:192` | `_ahas_open_blocking_blueprint_threads(session)`（needs_clarification 派生判据） |
| `:217` | `_amap_blueprint_status(session)` |

**增量派发白名单与单点串行**（`blueprint_research_adapter.py`）：

| 行号 | 事实 |
|------|------|
| `:66` | 注释：「既不重派已完成容器（重置进度、浪费额度、扰乱 barrier），也不为已处理仓重复合成」 |
| `:117-129` | `async def dispatch(self, session, *, force_deep_repository_ids: set[str] | None = None)`；`:129` `forced = {str(rid) for rid in (force_deep_repository_ids or set())}` |
| `:750` | 单仓定向补调研：`await self.dispatch(session, force_deep_repository_ids={repository_id})` |
| `:834` | 「barrier 收敛后的**单点串行**判定与轮次递增（P3 lost-update 的唯一缓解手段）」—— ⚠️ 已知 lost-update 风险面，waiter 状态若也放 `stage_state` 会叠加同一风险 |
| `:1103` | `_resolve_dispatch_user(session)` —— 容器动作的归属用户解析（观测规范要求） |

**⇒ 重派路径**：`waiting_context` 退出 → 回调登记 waiter（entry `kind="dependency_claim"`，见主题 4）→ 目标 key 的 `report_blueprint_context` 写入时检查 waiter 命中 → 命中即 `dispatch(session, force_deep_repository_ids={waiting_repo_id})`（复用 `:750` 的单仓定向通路，白名单 `:66` 自动跳过已完成仓）→ prompt 带 `partial_plan_id` 续作。环检测在**登记 waiter 时**做（此刻 waiter 全集已知），命中环 → 抛澄清线程，不 dispatch。

---

## 主题 4：模型与 migration

### 4.1 最新 migration 序号

`server/delivery/migrations/` 尾部：`0029_remove_clarification_affected_partials.py` → `0030_humantask.py` → **`0031_blueprint_models.py`**（当前最新）。
⇒ **本相位新增 migration 应为 `0032_*`**（如 `0032_blueprint_context_entry.py`），`dependencies = [("delivery", "0031_blueprint_models")]`。

`server/delivery/models/` 现有 21 个模块：`architect_merge / artifact / blueprint_reviewer / blueprint_thread / clarification / comment_event / convergence_session / convergence_session_event / document / human_task / ingest_run / relation / release / repo_coding_task / research_task / sdd_spec / sdd_spec_review / status_event / sync_state / work_item`（+ `__init__.py`）。新增 `blueprint_context_entry.py` 并在 `__init__.py` 导出（barrel 约定）。

### 4.2 索引建议

**现有风格**（照抄这两处）：

```python
# server/delivery/models/blueprint_thread.py:115-122
class Meta:
    db_table = "delivery_blueprint_thread"
    verbose_name = "蓝图澄清线程"
    verbose_name_plural = "蓝图澄清线程"
    indexes = [
        # confirm 守卫查询驱动：filter(artifact, status=open, blocking=True)
        models.Index(fields=["artifact", "status", "blocking"]),
    ]

# server/delivery/models/convergence_session_event.py:44-53（append-only 先例）
class Meta:
    db_table = "delivery_convergence_session_event"
    ordering = ["created_at"]
    indexes = [
        models.Index(fields=["session", "ts"]),
        models.Index(fields=["event"]),
    ]
```

迁移里索引名可省略（Django 自动生成，见 `0031_blueprint_models.py:74` `name='delivery_ar_artifac_3c2419_idx'`、`:112`）；唯一约束显式命名（`:107-109` `name="uq_blueprint_reviewer_artifact_user"`）。

**`BlueprintContextEntry` 建议**（按 CONTEXT 锁定的两类查询驱动）：

```python
class Meta:
    db_table = "delivery_blueprint_context_entry"
    verbose_name = "蓝图上下文总线条目"
    verbose_name_plural = "蓝图上下文总线条目"
    ordering = ["seq"]                       # 会话内单调序即读取序（append-only 语义）
    indexes = [
        # ① since_seq 增量拉取（await/read 轮询主路径，最高频）
        models.Index(fields=["convergence_session", "seq"]),
        # ② key 前缀查（repo:{id}.api_surface / contract:{name}）——
        #    startswith 走该复合索引左前缀；DB 端为 B-tree range scan
        models.Index(fields=["convergence_session", "key"]),
        # ③ kind + status 过滤（active 条目按类型取，环检测读 dependency_claim）
        models.Index(fields=["convergence_session", "kind", "status"]),
    ]
    constraints = [
        # seq 唯一性兜底（并发分配的最后一道防线，见 4.3）
        models.UniqueConstraint(
            fields=["convergence_session", "seq"],
            name="uq_blueprint_context_session_seq",
        ),
    ]
```

注意：`convergence_session` 放在每个复合索引的**最左列**，因为所有查询都必先按会话隔离（server-authoritative 的会话边界）。`repository_id` 不单独建索引 —— 它在 `kind` 过滤后基数已很低，全表扫会话切片即可；若实测慢再补 `["convergence_session","repository_id"]`。

### 4.3 `seq` 单调分配的并发安全做法

**本仓无 `Max("seq")` 的运行时先例**：`rg` 命中的 `aggregate(Max("version"))` 全部在 `server/prompts/migrations/*` 与 `server/prompts/builtin_contract.py`（单线程迁移/启动期，不构成并发先例）。

**delivery 层的既有并发范式是「行锁 + 条件唯一约束」**：
- `server/delivery/services/document_service.py`：`Document.objects.select_for_update().get(id=…)` / `select_for_update().get_or_create(...)`（按 `(feishu_tenant, external_ref)` 自然键）
- `server/delivery/services/release_service.py`：「复用 `select_for_update().get_or_create` + 31-01 条件唯一约束防并发重复」
- `server/delivery/services/sdd_spec_service.py`：`SddSpec.objects.select_for_update()`
- `server/mcp_tools/views.py:14` 已 import `IntegrityError, transaction`；`:15` 已 import `Max` —— 两个部件在 MCP view 层都是现成的

**推荐做法（锁父行，不锁子表）**：

```python
@sync_to_async
def _append_entry_locked(*, session_id, key, kind, ..., content) -> BlueprintContextEntry:
    with transaction.atomic():
        # 锁父 ConvergenceSession 行 —— 同会话的 seq 分配串行化；
        # 不用 select_for_update 锁子表（空集不产生 gap lock，MySQL 下不可靠）
        ConvergenceSession.objects.select_for_update().get(pk=session_id)
        next_seq = (
            BlueprintContextEntry.objects
            .filter(convergence_session_id=session_id)
            .aggregate(Max("seq"))["seq__max"] or 0
        ) + 1
        return BlueprintContextEntry.objects.create(
            convergence_session_id=session_id, seq=next_seq, key=key, kind=kind, ...
        )
```

理由与取舍：
- **锁父行而非子表**：`select_for_update()` 对空结果集不产生可靠 gap lock（MySQL/PostgreSQL 行为不一），锁 `ConvergenceSession` 单行是确定的串行点，且与 `blueprint_research_adapter.py:834` 已采用的「单点串行」思路同源。
- **`UniqueConstraint(session, seq)` 是兜底不是主手段**：捕获 `IntegrityError` 重试一次（views.py:14 已 import）；正常路径不应触发。
- **不用 DB 序列/`AutoField`**：CONTEXT 要求「会话内单调」，全局自增无法满足「`since_seq` 在会话内连续」的增量语义（跨会话空洞会让客户端无法判断是否漏读）。
- **写入必须收口于 service**（INV-6，`callbacks.py:1967` 明示「业务表写入全部经 ResearchService，本段零裸 ORM 写」）：新建 `BlueprintContextService`，view 与回调都只调它。

---

## 主题 5：distill 沉淀（`ProjectMemory` draft/confirm）

沉淀链路**必须**经草案 + 人工 confirm，绝不直写 active。三个可调入口（`server/initiatives/services/`）：

| 坐标 | 签名 | 语义 |
|------|------|------|
| `memory_service.py:338-371` | `async def create_draft(self, *, project_id, content: str, proposed_by=None, source_conversation_id=None, actor=None, initiated_by_user_id=None, _skip_member_check: bool = False) -> ProjectMemoryDraft` | 创建 pending 草稿。`:356` `redacted = redact_secrets_in_text(content or "")` **入库前脱敏不可绕过**；`:354-355` 非 `_skip_member_check` 且有 `proposed_by` → `_assert_member`；`:363-370` emit `ACTION_PROJECT_MEMORY_DRAFT_CREATED` |
| `memory_service.py:373-388` | `_create_draft_locked(*, project_id, content, proposed_by, source_conversation_id)`（`@sync_to_async`） | `ProjectMemoryDraft.objects.create(..., status=DraftStatus.PENDING)` |
| `memory_service.py:390-421` | `async def confirm_draft(self, *, draft_id, confirmer, actor=None, initiated_by_user_id=None) -> ProjectMemory` | **人工确认专用**。`:400-401` 非 PENDING → `raise MemoryStateError`；`:402` `_assert_member(draft.project_id, confirmer)` fail-closed；`:404-411` 复用 `append(_skip_member_check=True)` 入库；`:412` `_mark_draft_confirmed`（`:423-429` `select_for_update` + `transaction.atomic`）；`:413-420` emit `ACTION_PROJECT_MEMORY_DRAFT_CONFIRMED` |
| `memory_service.py:431-...` | `async def reject_draft(self, *, draft_id, actor=None, initiated_by_user_id=None) -> ProjectMemoryDraft` | 拒绝（status → rejected），成员校验 |
| `memory_distill.py:62-111` | `async def distill_to_draft(self, *, project_id, conversation_text: str, proposed_by, source_conversation_id=None, initiated_by_user_id=None) -> Any` | LLM 蒸馏产 pending 草稿。`:77-79` 成员校验 fail-closed（非成员 `raise MemoryPermissionError`）；`:82-92` LLM 无候选 / 输出 `NONE` → `return None`（埋点 `memory_distill_no_candidate`，`category="sampling"`）；`:95` 再 `redact_secrets_in_text`（双保险）；`:96-103` `MemoryService().create_draft(..., _skip_member_check=True)`；`:104-110` 埋点 `memory_distill_draft_created`，`category="caller"` |
| `memory_distill.py:122-...` | `async def distill_hook_writeback(self, *, text: str) -> str | None` | IDE hook 专用的 active 直写前精炼（**不适用**于总线沉淀 —— 它不产草案） |

**⇒ 总线沉淀的落法**：会话结束时把有长期价值的 `BlueprintContextEntry`（`kind ∈ {decision, contract, api_surface}` 且 `status=active`）拼成 `conversation_text` → 调 `MemoryDistiller().distill_to_draft(project_id=session.project_id, conversation_text=…, proposed_by=<dispatch 用户>, initiated_by_user_id=…)`。若不想经 LLM（条目本身已是结论文本），直接调 `MemoryService().create_draft(...)`。**绝不调** `append` / `record_hook_writeback` / `confirm_draft`（后者是人工动作的入口）。`proposed_by` 必须是真实项目成员 User，否则 `distill_to_draft:77-79` 会 fail-closed 抛错 —— 用 `blueprint_research_adapter.py:1103` 的 `_resolve_dispatch_user(session)` 解析。

---

## Pitfalls（必须在计划里各有一条对策）

### P1 容器 MCP 新工具的向后兼容 —— 老镜像没有新工具时不能崩

**事实基础**：`KNOWLEDGE_TOOL_SCHEMAS` 是 **task 侧硬编码**（`knowledge_tools.py:52` 注释「7 工具白名单（task 侧硬编码）」、`:391` 「白名单内建恒有」），**不从服务端下发**。所以：

- **老镜像 + 新服务端**：容器不知道新工具存在，只是不调 —— 天然安全。但若 prompt 写成「你**必须**先调 `await_blueprint_context`」，老镜像的 agent 会因工具不在 `allowed_tools` 白名单里而报错或幻觉调用。
  **对策**：prompt 措辞用条件式（「若 `await_blueprint_context` 工具可用，则…；否则记录假设并继续」），并在服务端派发时**不依赖**容器一定会写总线（缺条目走超时降级路径，与 P4 一致）。
- **新镜像 + 老服务端**：新工具 POST 到不存在的 path → 404 → `knowledge_tools.py:329-340` 只回显 `HTTP 404` + `is_error`，**handler 不 raise、容器不崩**（`:265` 「全路径 return-not-raise」）。这条路径已被现有约定兜住，无需额外工作。
- **`allowed_tools` 排他陷阱**：`executor.py:152-158` —— 新工具进 `knowledge_allowed_tools()` 后自动被并入，无需动 builtin 逻辑；但若把新工具做成 **extra 源**（像 `ask_user` 那样），就必须自带 `_BUILTIN_CODING_TOOLS`（`executor.py:106-107`），否则 Bash/Edit/Write 全被禁。**⇒ 结论：`read_/report_/await_blueprint_context` 三个都走 knowledge 白名单，不要走 extra 源。**

### P2 总线写入的脱敏点

- 脱敏函数：`server/common/logging.py:362` `def redact_secrets_in_text(text: str) -> str`（另有 `:69` `redact_credentials` 作为 structlog processor）。
- **入库前脱敏的正确位置是 service 层**，先例 `memory_service.py:356`（`create_draft` 内部）与 `memory_distill.py:95`（调用前）——**双保险**是本仓认可的做法。
- ⚠️ **`BlueprintContextEntry.content` 是 JSON dict，不是 str** —— `redact_secrets_in_text` 只吃字符串。直接 `redact_secrets_in_text(json.dumps(content))` 再 `loads` 会破坏结构且可能因脱敏替换产生非法 JSON。**必须递归遍历 dict/list，对每个字符串叶子单独调用**，并对 `key` 字段与容器传入的自由文本字段（`content.description` / `content.raw` 等）一并处理。
- 日志侧：`server/mcp_tools/views.py:2684` / `:3612` 的先例是 `error=redact_secrets_in_text(str(exc))[:500]` —— 异常文本入日志必须脱敏 + 截断。总线 view 的异常分支照抄。
- 容器侧对称约束：`knowledge_tools.py:12-18` —— PAT 只进 `Authorization` header；日志只记 `tool/status/duration_ms/quota_used`，**绝不记入参与响应明文**。`report_blueprint_context` 的 content 不得进容器侧日志。

### P3 环检测的数据来源：waiter 表 vs `stage_state`

两个候选的事实对比：

| 载体 | 坐标 | 优点 | 风险 |
|------|------|------|------|
| `ConvergenceSession.stage_state` JSON 袋 | `convergence_session.py:83` `stage_state = models.JSONField(default=dict)`；`:132-151` 便捷只读视图（`decomposition`/`routing`/`recall_context`/`classification`）；写入**恒经** `ConvergenceSessionService.transition(stage_state=)`（`:132` 注释） | 无新表；与 112 的 `stage_state["routing"]` 同源 | ⚠️ **单行 JSON 的 lost-update**：`blueprint_research_adapter.py:834` 已明示「P3 lost-update 的唯一缓解手段」是 barrier 后单点串行。并行容器高频登记/命中 waiter 会绕过那个串行点，必然丢写 |
| `BlueprintContextEntry(kind="dependency_claim")` 行 | CONTEXT 已把 `dependency_claim` 列入 `kind` 枚举；key 前缀 `dependency:{from}->{to}` 也已锁定 | 行级写入无 lost-update；环检测是纯函数读表（`filter(session, kind="dependency_claim", status="active")` 走建议索引 ③）；条目本身可被 115 时间线消费 | 需要 `status` 生命周期管理（命中/超时后置 `superseded`） |

**推荐：waiter 落 `BlueprintContextEntry(kind="dependency_claim")` 行，环检测纯函数读表。** `stage_state` 只存**汇总视图**（如 `stage_state["repo_plan"]["waves"]` 波次预排结果，写入频率低、经 `transition` 串行）。理由：并行容器的写入频率恰好是 `stage_state` 最不擅长的场景，而 `:834` 的既有缓解手段（单点串行）在这里不适用。

环检测实现：读全部 active `dependency_claim` → 建 `{from_repo: {to_repo,…}}` 有向图 → DFS/Tarjan 找环 → 命中即开 `BlueprintThread(kind=ai_clarification, blocking=True)` 抛用户裁决（CONTEXT：「不靠超时兜底」），并 emit `caller` 事件 + `ConvergenceSessionEvent`。

### P4 容器长轮询占用连接的风险与超时上界

- **容器侧硬上界 60s**：`knowledge_tools.py:298` `timeout=60.0`（写死在工厂里，全 7 工具共享）。任何服务端等待实现的单次响应必须 **< 60s**，且要留网络余量 ⇒ 实际可用 ≈ **≤ 25s**。
- **服务端长轮询的连接账**：每个挂起请求 = 1 个 ASGI 协程 + 1 条上游 TCP；N 个并行容器同时 await ⇒ N 条常驻。本仓 `api/mcp/tools/*` 全部是即时返回，无长轮询先例、无连接数上限配置面。
- **配额账**：`knowledge_quota` 默认 200（`config.py:108`），7 工具**共享一个闭包计数器**（`knowledge_tools.py:409` `quota_counter = [0]`）。3 分钟 ÷ 5s = 36 次轮询 ≈ 配额的 18%；若两次 await 就占掉 36%，正常调研工具会被挤爆（用尽后 `:284` 返回「请基于已有上下文继续」，等于静默降级）。
- **建议上界（写进计划的具体数值）**：
  - `await_blueprint_context` 的 `timeout_minutes` 默认 `3`、硬上界 `5`；超过即应改走长等待退出重派。
  - `poll_interval_s` 默认 `5.0`（不用 `ask_user` 的 `3.0` —— 那是读本地文件，这里是 HTTP + DB）。
  - 轮询调用**不计入或单独计入**共享配额（否则挤爆知识工具预算）；若无法单独计数，则把 `FRIDAY_TASK_KNOWLEDGE_QUOTA` 在 repo_plan 派发时提高（派发侧 metadata 注入即可，`blueprint_research_adapter.py:477-487` 的 `env_*` 写法）。
  - **不实现服务端长轮询**；若后续必须实现，单次挂起 ≤ 25s 且需显式并发上限。

### P5（附加）`X-Friday-Session-Id` 不是鉴权凭据

`knowledge_tools.py:386` 明示：`session_id` 经 header 下发，服务端「入 `InteractionRun.raw_request['task_session_id']` 供关联查询」—— 它是**关联键，不是权限凭据**。Context Bus 的会话隔离必须交叉验证（主题 1.3 的三道校验），不能仅凭 header 值信任容器声明的会话归属。

---

## Assumptions Log

| # | 假设 | 章节 | 若错的影响 |
|---|------|------|-----------|
| A1 | `report_blueprint_context` 的 `content` 递归脱敏需自建 helper（本仓无「JSON 递归脱敏」现成函数） | P2 | 若已存在（如 `redact_for_ledger` 的内部实现可复用）则省一个 helper；已确认 `common/logging.py` 只有 `redact_credentials`(`:69`) 与 `redact_secrets_in_text`(`:362`) 两个 `redact*` 顶层函数 |
| A2 | `knowledge_quota` 的 per-tool 单独计数需要改 handler 工厂签名（当前闭包计数器全局共享） | P4 | 若接受「不单独计数、改为提高总配额」则零改动 |
| A3 | `waiting_context` 复用 `source="blueprint_research"` 而非新增 source 值 | 3.1 | 若新增 source，则 `callbacks.py:1986` 的互斥判定与 `:991/:1075` 两个钩子都要加分支 |
| A4 | 环检测放在「登记 waiter 时」而非「定时扫描」 | P3 | 若改为定时扫描需要新增 apscheduler job（本仓有 `django-apscheduler` 先例，见 `container_suspend_service.py:80`） |

## Open Questions

1. **`await_blueprint_context` 是否单独计配额？**
   - 已知：7 工具共享 `quota_counter`（`knowledge_tools.py:409`），默认 200（`config.py:108`）。
   - 不清楚：repo_plan 阶段单容器的知识工具实际用量基线。
   - **推荐**：不改工厂签名，改为**派发时提高配额**（repo_plan 容器注入 `env_FRIDAY_TASK_KNOWLEDGE_QUOTA=400`），并让 `await` 的每轮轮询照常计数 —— 简单、无公共面改动、配额耗尽时的降级文案（`:284`）恰好也是「基于已有上下文继续」的正确行为。

2. **waiter 的 `status` 生命周期由谁推进？**
   - 已知：`BlueprintContextEntry.status ∈ {active, superseded}`（CONTEXT 锁定）。
   - **推荐**：`report_blueprint_context` 写入时同事务内把命中的 `dependency_claim` 置 `superseded` 并触发重派；超时无人满足的 waiter 由 barrier 续驱（`blueprint_resume.py:154`）时统一清理 —— 与既有 barrier 单点串行同源，不新增调度器。

3. **短等待的心跳是否必要？**
   - 已知：`ask_user` 靠 `callback.report_status`（`question_loop.py:111`）保活；但 knowledge MCP 的 handler 工厂**不持有 `callback`**（`knowledge_tools.py:253` 签名无 callback）。
   - **推荐**：不传 callback、不发显式心跳 —— 轮询本身每 5s 有一次 HTTP 出站，容器进程活跃；给公共工厂加 callback 参数的代价（影响 7 个既有工具）远大于收益。若实测出现「容器被判超时」，再单独为该工具走 extra 源挂载（届时按 `executor.py:106-107` 自带 builtin 白名单）。

## Sources

### Primary（HIGH — 本仓源码，全部带行号）

- `.planning/phases/113-2/113-CONTEXT.md`（锁定决策原文）
- `task/core/knowledge_tools.py`（44/47/52-235/238/253-371/374-433/436-440）
- `task/core/question_loop.py`（35-39/42/46-56/59-121/124-163/184-206/209-211）
- `task/core/executor.py`（88-161/106-107/136-144/149-161）
- `task/core/config.py`（23/80/86/90/94/101/108/117/125/131/164/174-185）
- `server/mcp_tools/urls.py`（5-39/41-127）
- `server/mcp_tools/views.py`（12-28/235-339/3330-3410）
- `server/mcp_tools/errors.py`（`error_response`，经 `knowledge_tools.py:9` 交叉确认）
- `server/access_tokens/authentication.py`（52/60/103/105/120）
- `server/access_tokens/services.py`（32/43/46/67）
- `server/services/protocols.py`（4/17/23-24/103/143-159）
- `server/services/process_runtime/blueprint_research_adapter.py`（57-58/66/117-129/365-456/458/477-487/504-506/524-533/750/834/1076/1103）
- `server/services/process_runtime/blueprint_resume.py`（44/59/74/101/113/154/168/180/192/205/217）
- `server/services/process_runtime/answer_resume.py`（1-60）
- `server/subagent/api/callbacks.py`（991-998/1075-1082/1963-2012/2090-2115/2118-2145）
- `server/runners/consumers.py`（187-189/373-380）
- `server/runners/protocol.py`（26）
- `runner/internal/ws/client.go`（75/440-453/466-489）
- `runner/internal/docker/executor.go`（26/88-93）
- `server/delivery/models/convergence_session.py`（30/41/51-116/118/132-151）
- `server/delivery/models/convergence_session_event.py`（21-57）
- `server/delivery/models/blueprint_thread.py`（115-122/152-155）
- `server/delivery/migrations/0031_blueprint_models.py`（17-112）
- `server/delivery/services/event_taxonomy.py`（39-54/122-145）
- `server/initiatives/services/memory_service.py`（338-388/390-429/431）
- `server/initiatives/services/memory_distill.py`（40-56/62-111/113-120/122）
- `server/common/logging.py`（69/362）
- `server/delivery/services/{document_service,release_service,sdd_spec_service}.py`（`select_for_update` 并发先例）

### Secondary（MEDIUM）

- `server/chat/container_suspend_service.py`（模块头注释 + 80/138/188/205/272 —— HTTP 直达活容器与 apscheduler 先例）
- `server/tests/test_milestone_e2e_learning_case.py`（350-363 —— 容器 URL 模板的三面 e2e 断言先例，可作新工具测试组织参照）

### Tertiary（LOW）

- 无。本文档未使用外部检索；所有结论均可在本仓复核。

## Metadata

**Confidence breakdown:**
- 容器 MCP 扩工具做法：**HIGH** —— 表驱动 + 4 处新增位置全部逐行核实
- 鉴权链：**HIGH** —— `authenticate` 返回值与 `_begin` 全链核实（含「不是 token→session→user」的纠偏）
- 短等待原语：**HIGH**（事实）/ **MEDIUM**（推荐路径）—— 60s 硬超时与配额共享是硬事实；轮询间隔/超时上界的具体数值是工程判断，无生产基线
- 长等待与重派：**HIGH** —— 第三链路由、barrier、增量白名单全部有坐标
- 模型与 migration：**HIGH**（序号/风格）/ **MEDIUM**（seq 分配）—— 无运行时 `Max("seq")` 先例，方案由 delivery 层 `select_for_update` 范式外推
- distill：**HIGH** —— 三个函数签名逐字核实

**Research date:** 2026-07-30
**Valid until:** 2026-08-29（内部代码事实，除本里程碑自身改动外不会漂移；若 111/112 后续有 hotfix 需复核 `blueprint_research_adapter.py` 与 `callbacks.py` 第三链坐标）
