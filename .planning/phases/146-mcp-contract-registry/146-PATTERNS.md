# Phase 146: 契约注册表与生成目录 - Pattern Map

**Mapped:** 2026-09-14
**Files analyzed:** 22 个现有文件；推导 14 组新增/修改文件
**Analogs found:** 13 / 14
**Scope source:** `.planning/REQUIREMENTS.md` 的 PUB-01～PUB-06、`.planning/research/{SUMMARY,ARCHITECTURE,FEATURES,PITFALLS}.md`

## 结论先行

Phase 146 应采用以下单向依赖：

```text
Django declarative registry + DRF request/response serializers（唯一事实源）
  ├─ Django urlpatterns（运行时投影，不再手抄）
  ├─ server/contracts/mcp-tools.v1.json（生成）
  ├─ TOOL_SCHEMA_SNAPSHOT（迁移期生成投影）
  └─ mcp/src/generated/toolCatalog.ts（唯一生成路径）

server/contracts/mcp-tools.compat.v1.json（独立、人工审阅的兼容基线）
  └─ compatibility checker（只比较，不自动接受/回写 baseline）
```

必须保留的边界：

- registry 是 Django 侧的声明源，npm `tools.ts` 和 `TOOL_SCHEMA_SNAPSHOT` 都不能继续当事实源。
- request serializer 保留业务输入校验；新增 response serializer 承担完整 `outputSchema`，不能只记录响应键名。
- compatibility baseline 必须独立于 registry/generated manifest，禁止测试动态导入被测 registry 后“自证一致”。
- `task/core/knowledge_tools.py` 是容器内受限工具白名单，含没有 HTTP URL 的 `await_blueprint_context`，不能并入 public 55-tool registry。
- `task/core/agent_submit_mcp.py` 是容器回调协议，不是 public control plane，本相位不改。
- `server/contracts/graph-query.v1.json` 继续是 graph-query 领域契约；全局 MCP catalog 应引用/校验它，不能复制并产生第二份不同 schema。
- `mcp/src/server.ts` 的 confirmed handoff 安全落盘逻辑是用户当前未提交工作，生成器不得覆盖。

## 当前事实与漂移

- Django URL 面：55 个工具。
- npm stdio 面：43 个工具。
- npm 缺少 12 个：
  `approve_technical_blueprint`、`detect_changes`、`get_process`、`get_session_capture`、
  `graph_query`、`impact_analysis`、`list_processes`、`rename_preview`、
  `report_session_knowledge`、`request_technical_blueprint_changes`、
  `search_session_knowledge`、`trace_call_path`。
- `mcp/package.json` 版本是 `0.6.0`，`mcp/src/server.ts` 的 `SERVER_VERSION` 是 `0.2.0`。
- `server/tests/mcp_tools/test_mcp_package_alignment.py` 在 `mcp/` 缺失时 `pytest.skip`，不满足 PUB-03。
- 根 CI 的触发路径不含 `mcp/**`，且没有独立 npm MCP build/typecheck/test/check job。
- `server/tests/services/code_graph/test_query_contract_conformance.py` 引用
  `mcp/src/generated/graphQueryManifest.ts`，但当前 gitlink `28f95363...` 不含该文件和其生成脚本；规划时不能假设该既有生成链在当前 submodule commit 可执行。

## 未提交 mcp 工作清单（执行器必须保留）

`mcp` 子模块 gitlink 仍指向 `28f95363b8cb9f6944d2d75c51e873479e991a0d`，子模块内有且仅有以下 3 个已修改文件，共 `+101/-4`：

| 文件 | 当前未提交内容 | Phase 146 处理约束 |
|------|----------------|--------------------|
| `mcp/src/server.ts` | 新增 confirmed handoff 的 0700 目录、0600 临时文件、原子 rename、文件 SHA-256 与小摘要返回 | 必须保留；只在此基础上添加 `structuredContent`、机器错误码、manifest metadata |
| `mcp/src/tools.ts` | 工具数 42→43；新增 `get_confirmed_blueprint_handoff` schema 与 query annotation | 迁入 generated catalog 时必须完整保留该定义；不能用旧 42-tool 基线覆盖 |
| `mcp/tests/server.test.ts` | 断言 43 工具；新增 handoff 原样落盘且正文不进入模型摘要的测试 | 删除绝对数量断言时仍保留 handoff 行为测试和新工具可发现断言 |

仓库根其余未提交 planning/server/web 测试均与本 pattern map 无关，不得改动或纳入 Phase 146 提交。

## File Classification

| 新增/修改文件 | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `server/mcp_tools/registry.py` | registry/config | transform + request-response | `server/agents/tools/registry.py`、`server/workflows/nodes/registry.py` | role-match |
| `server/mcp_tools/schema.py`（或等价 converter） | utility | transform | `server/services/code_graph/query_manifest.py` | partial |
| `server/mcp_tools/serializers.py` | serializer | request-response | 文件内 `GraphQueryRequestSerializer` + `server/contracts/graph-query.v1.json` | role-match |
| `server/mcp_tools/urls.py` | route | request-response | 当前同文件 | exact |
| `server/mcp_tools/management/commands/generate_mcp_contracts.py` | codegen command | file-I/O + transform | `server/workflows/management/commands/export_node_spec.py`、`check_builtin_prompt_drift.py` | role-match |
| `server/contracts/mcp-tools.v1.json` | generated manifest | transform | `server/contracts/graph-query.v1.json` | exact |
| `server/contracts/mcp-tools.compat.v1.json` | compatibility baseline | batch/transform | graph benchmark policy + comparator | role-match |
| `server/mcp_tools/compatibility.py` | compatibility checker | transform | `server/codegraph/services/graph_bench_compare.py` | role-match |
| `mcp/src/generated/toolCatalog.ts` | generated config | request-response | `task/core/generated_graph_query_manifest.py` | exact |
| `mcp/src/tools.ts` | compatibility barrel/wrapper | transform | 当前同文件 | role-match |
| `mcp/src/server.ts` | stdio adapter | request-response + file-I/O | 当前同文件 | exact |
| `mcp/src/cli.ts` | CLI/doctor | request-response | 当前 `runDoctor` | exact |
| `server/tests/mcp_tools/test_contract_registry.py`、`test_contract_generation.py`、`test_contract_compatibility.py` | tests | transform + file-I/O | `test_query_contract_conformance.py`、`test_schema_snapshot.py`、graph comparator tests | exact |
| `mcp/tests/server.test.ts`（及 doctor 测试） | tests | request-response + file-I/O | 当前同文件 | exact |
| `.github/workflows/ci.yaml`、`mcp/.github/workflows/publish.yml` | CI/config | batch | 当前 workflows | exact |
| server catalog/version endpoint（具体文件待 planner 冻结） | controller/route | request-response | `server/accounts/urls_health.py` | partial |

## Pattern Assignments

### `server/mcp_tools/registry.py`（registry，transform/request-response）

**Analogs:** `server/agents/tools/registry.py`、`server/workflows/nodes/registry.py`

采用显式不可变 tool definition + 集中查询 API，避免从 `views.py` 反射猜契约。可复用 ToolRegistry 的“registry 返回独立集合和 schema projection”形态：

```python
# server/agents/tools/registry.py:67-93
@classmethod
def get_tool_schemas(
    cls, tool_names: list[str] | None = None
) -> list[dict[str, Any]]:
    if tool_names is not None:
        tools = [_tool_registry[name] for name in tool_names if name in _tool_registry]
    else:
        tools = list(_tool_registry.values())
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in tools
    ]
```

重复注册必须 fail-fast，不要沿用 NodeRegistry “warning 后覆盖”：

```python
# server/workflows/nodes/registry.py:70-89（仅借鉴集中注册；Phase 146 应强化为异常）
node_type = node_class.node_type
if node_type in cls._nodes:
    if cls._nodes[node_type] is node_class:
        return
cls._nodes[node_type] = node_class
```

每个 registry entry 至少显式包含：

- `name`
- `view`
- `request_serializer`
- `response_serializer`
- `description`
- `annotations`
- 稳定 route（建议由 name 确定为 `tools/{name}/`）
- 可选 contract/version metadata

annotations 不能从工具名前缀推断；审批、退回、apply 等必须显式声明风险语义。

### `server/mcp_tools/schema.py` 与 response serializers（utility/serializer，transform）

**Analogs:** `GraphQueryRequestSerializer`、`graph-query.v1.json`

DRF serializer 继续是字段类型、required、default、min/max、enum 的事实源：

```python
# server/mcp_tools/serializers.py:197-217
class GraphQueryRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    query = serializers.CharField(required=True, allow_blank=False, max_length=2000)
    branch = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    max_symbols = serializers.IntegerField(default=10, min_value=0, max_value=50)
    include_impact = serializers.BooleanField(default=False)
```

生成出的 JSON Schema 应保持 graph-query 已验证的结构：

```json
// server/contracts/graph-query.v1.json:30-42,92-100
{
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {},
    "required": []
  },
  "outputSchema": {
    "type": "object",
    "required": [],
    "properties": {}
  }
}
```

当前 `TOOL_SCHEMA_SNAPSHOT` 只有字段名数组，无法生成类型完整的 `outputSchema`。因此：

- request/response serializers 手写，保留业务校验。
- JSON Schema、snapshot 字段投影、manifest 与 TS 机械生成。
- 不从 view 返回样例猜 response schema。
- 不引入 zod/OpenAPI generator；使用已有 DRF/jsonschema 栈。

### `server/mcp_tools/urls.py`（route，request-response）

**Analog:** 当前 `server/mcp_tools/urls.py`

保留公开 URL 字面不变，但 `urlpatterns` 应由 registry 投影，消除 55 条手抄 import/path：

```python
# server/mcp_tools/urls.py:62-69（现有 URL 形状）
path(
    "tools/route_repositories/",
    RouteRepositoriesView.as_view(),
    name="mcp-tool-route-repositories",
)
```

生成/投影规则固定为：

- path: `tools/{tool.name}/`
- route name: `mcp-tool-{tool.name.replace("_", "-")}`
- view: registry 中的实际 `McpToolView` subclass

URL 集合测试仍应枚举真实 `urlpatterns`，但 expected 来自独立 generated manifest 文件，不应只与同一 Python 对象比较。

### `server/mcp_tools/management/commands/generate_mcp_contracts.py`（codegen，file-I/O）

**Analogs:** `export_node_spec.py`、`check_builtin_prompt_drift.py`

命令参数与退出语义沿用 Django management command：

```python
# server/workflows/management/commands/export_node_spec.py:29-48
class Command(BaseCommand):
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--check", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["check"]:
            if valid:
                self.stdout.write("OK")
            else:
                self.stderr.write("FAIL")
                sys.exit(1)
```

漂移/失败应采用 `CommandError` 非零退出，并按现行观测规范记录 started/completed/failed：

```python
# server/prompts/management/commands/check_builtin_prompt_drift.py:72-108
started = time.monotonic()
_safe_log("info", "builtin_prompt_drift_check_started", ...)
...
if drift:
    _safe_log("warning", "builtin_prompt_drift_check_completed",
              success=False, duration_ms=duration_ms, ...)
    raise CommandError(...)
```

生成器要求：

- 所有输出先在内存中确定性渲染。
- JSON 使用 UTF-8、`ensure_ascii=False`、稳定 key/order、结尾换行。
- `--check` 只比较预期 bytes 与磁盘 bytes，绝不写文件。
- 普通模式只写 generated 文件，不更新 compatibility baseline。
- 输出清晰列出 missing、extra、changed 文件。
- 日志只含路径、数量、hash、duration，不含 schema description/body。

### `server/contracts/mcp-tools.v1.json`（generated manifest，transform）

**Analog:** `server/contracts/graph-query.v1.json` + `query_manifest.py`

manifest hash 沿用“最终 canonical raw bytes 的 SHA-256”：

```python
# server/services/code_graph/query_manifest.py:15-24
@lru_cache(maxsize=1)
def graph_query_manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

@lru_cache(maxsize=1)
def graph_query_manifest_hash() -> str:
    return hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest()
```

全局 manifest 自身不能包含会改变自身 hash 的 `manifest_hash` 字段；hash 由 reader/build metadata 计算并对外返回。工具项应稳定按 name 排序，至少含 route、description、annotations、inputSchema、outputSchema。

### `server/contracts/mcp-tools.compat.v1.json` 与 compatibility checker（baseline/batch）

**Analogs:** `graph_bench_compare.py`、`compare_graph_bench.py`

compatibility checker 应是纯函数、零 I/O，命令负责读取和报告：

```python
# server/codegraph/services/graph_bench_compare.py:1-6,93-102
"""... comparator（纯函数、零 I/O）。"""

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

输入结构先做 exact-key/type/hash 校验，再比较语义；失败理由必须定位到
`tool/path/change_kind`。Phase 146 最低 breaking 集：

- 删除工具。
- 删除 input/output property。
- optional input 变 required 或新增 required。
- enum 值集合收窄。

建议同时将类型收窄、nullable→non-nullable、约束收紧列为 breaking；新增 optional 字段和 enum 扩展为 additive。

baseline 更新必须人工显式完成，不能在 checker/`--check` 中提供自动 accept。沿用现有纯比较器不写回保护：

```python
# server/tests/codegraph/test_graph_bench_closure.py:112-116
comparator_source = inspect.getsource(graph_bench_compare)
for forbidden in ("write_text(", "write_bytes(", "auto_update", "write_back"):
    assert forbidden not in comparator_source
```

### `mcp/src/generated/toolCatalog.ts` 与 `mcp/src/tools.ts`（generated config）

**Analog:** `task/core/generated_graph_query_manifest.py`

generated 文件必须有“禁止手改”头、嵌入 manifest hash，并导出完整定义：

```python
# task/core/generated_graph_query_manifest.py:1-9
"""由 ... 生成，禁止手改。"""
GRAPH_QUERY_MANIFEST_HASH = "..."
GRAPH_QUERY_MANIFEST = json.loads(r'''...''')
GRAPH_QUERY_TOOL_SCHEMA = {
    "name": GRAPH_QUERY_MANIFEST["name"],
    "description": GRAPH_QUERY_MANIFEST["description"],
    "input_schema": GRAPH_QUERY_MANIFEST["inputSchema"],
}
```

TS 生成物的唯一落盘路径固定为 `mcp/src/generated/toolCatalog.ts`；不得再生成
`mcp/src/generated/tools.ts`。`mcp/src/tools.ts` 只保留稳定类型/barrel re-export，不拥有任何
tool literal 或 annotations。TS 生成物应导出：

- `MCP_MANIFEST_HASH`
- `FRIDAY_TOOLS`（55 项）
- 每项 `name/title/description/inputSchema/outputSchema/annotations/route`

`mcp/src/tools.ts` 可保留为稳定 barrel re-export，或整体成为 generated 文件；不能保留一份并行手写 `TOOL_ANNOTATIONS`。当前未提交的 handoff tool 定义必须迁入 canonical registry 后再生成，不能丢失。

### `mcp/src/server.ts`（stdio adapter，request-response/file-I/O）

**Analog:** 当前同文件

保持 fail-closed known-tool 检查和 URL 构造，但 URL 应取 generated route：

```typescript
// mcp/src/server.ts:175-190
tools: FRIDAY_TOOLS.map(t => ({
  name: t.name,
  title: TOOL_ANNOTATIONS[t.name]?.title,
  description: t.description,
  inputSchema: t.inputSchema,
  annotations: TOOL_ANNOTATIONS[t.name],
}))
...
const known = FRIDAY_TOOLS.some(t => t.name === name)
if (!known)
  return textResult(`未知工具: ${name}`, true)
```

改造要求：

- `tools/list` 同时暴露 generated `outputSchema`。
- 成功调用返回现有 text content，并新增同一 JSON 对象的 `structuredContent`；两者不得分别组装。
- HTTP 业务错误解析 `error_code`，返回稳定机器字段并保留 `isError`；不能要求模型解析中文。
- 非 JSON、网络、timeout、auth、未知工具分别使用稳定 client-side error code。
- 继续不回显 PAT。
- 保留未提交 `persistConfirmedHandoff`：完整正文只落 0600 文件，structuredContent 只放摘要，不能把原始 body 放回模型。

### `mcp/src/cli.ts` doctor/version（CLI，request-response）

**Analog:** 当前 `runDoctor`

现有 doctor 已有注册状态、配置脱敏和健康检查：

```typescript
// mcp/src/cli.ts:150-179
async function runDoctor(): Promise<number> {
  const statuses = registrationStatus()
  ...
  console.log(`token: 已配置（${config.accessToken.length} 字符，不回显）`)
  const latency = await measureLatency(config.baseUrl)
  if (!latency.ok)
    return 1
  return 0
}
```

在此形态上增加 authenticated server catalog 请求，并打印：

- client package/server version。
- bundled client manifest hash。
- server version 与 manifest hash。
- missing-on-client、missing-on-server、changed-contract 工具名。

版本应从 `package.json` 生成/import，或有直接相等测试；不能再维护 `SERVER_VERSION` 字面量。server 当前 `/health` 只有 `status/service`，doctor 所需的版本/hash/catalog 应走独立受认证 endpoint，不把完整工具面塞进公开匿名 health。

### 测试（conformance/snapshot/compatibility/stdio）

**Analogs:** `test_query_contract_conformance.py`、`test_schema_snapshot.py`、`test_mcp_package_alignment.py`

跨消费面测试应计算独立来源的 byte/hash：

```python
# server/tests/services/code_graph/test_query_contract_conformance.py:52-68
expected_hash = graph_query_manifest_hash()
task_generated = runpy.run_path(...)
assert task_generated["GRAPH_QUERY_MANIFEST_HASH"] == expected_hash
assert task_generated["GRAPH_QUERY_MANIFEST"] == graph_query_manifest()
...
assert found.group(1) == expected_hash
```

保留 `test_schema_snapshot.py` 的独立字面量思想，但把大字面量迁为独立 compat baseline；禁止 expected 直接来自 registry：

```python
# server/tests/mcp_tools/test_schema_snapshot.py:7-9
# 刻意在测试里独立写一份字面量——从 serializers 导入同一个常量会让本守卫退化为自我比较
```

必须覆盖：

- registry、真实 urlpatterns、generated manifest、generated TS、真实 stdio `tools/list` 五面全量相等。
- 55 个工具无绝对“43/55 即正确”的唯一断言；集合和 manifest hash 才是主守卫。
- 12 个当前缺失工具均可 list/call。
- 每项 input/output schema 和 annotations 全等。
- 每个成功 fixture 的 `structuredContent` 通过对应 `outputSchema`。
- 删除工具/字段、新增 required/收窄 enum 各有独立失败测试。
- `mcp/` 不存在、未 checkout、generated file 缺失必须 fail，禁止 `pytest.skip`。
- `SERVER_VERSION == package.json.version`。
- doctor equal/missing/extra/changed/旧 server catalog 不可用路径。
- 保留 handoff 文件 mode/正文不内联/hash 可复算测试。

### CI 与 publish

**Analogs:** 根 `.github/workflows/ci.yaml`、`mcp/.github/workflows/publish.yml`

根 CI 已示范 submodule 必拉：

```yaml
# .github/workflows/ci.yaml:57-59
- uses: actions/checkout@v6
  with:
    submodules: recursive
```

Phase 146 应：

- 根 workflow 的 push/PR paths 增加 `mcp/**`、contract generator/manifest/baseline 路径。
- 新增 MCP job，按 submodule lockfile 的既有包管理器执行 frozen install、typecheck、test、build。
- server job 在 pytest 前执行 `generate_mcp_contracts --check`。
- 显式检查 `mcp/package.json` 存在且 submodule HEAD 可用，缺失直接非零。
- publish workflow 在 publish 前重复 generation/alignment/compatibility/version/doctor synthetic checks。
- 不沿用当前 publish 的 `npm install` + `npm@latest` 漂移做法；以 submodule 已提交 lockfile 和声明版本为准。

## Shared Patterns

### 稳定 hash

**Source:** `server/services/code_graph/query_manifest.py:15-24`

对最终落盘 canonical bytes 求 SHA-256；所有消费面比较同一个 hash，禁止对各自反序列化对象分别 hash。

### 薄 adapter

**Source:** `server/mcp_tools/views.py:1321-1384`

顺序固定为 `_begin` → serializer validate → canonical service → `run_id`/trace/record → Response。registry 只声明 transport contract，不吸收业务逻辑。

### 统一错误信封

**Source:** `server/mcp_tools/errors.py:10-15`

```python
return Response(
    {"error_code": error_code, "detail": detail},
    status=status_code,
)
```

Phase 146 可 additive 增加稳定字段，但旧 `error_code/detail` 必须保持。npm adapter 必须解析 `error_code`，不能只拼接 HTTP status 与 body 文本。

### 观测 best-effort

**Source:** `server/mcp_tools/views.py:1474-1493`、`check_builtin_prompt_drift.py:30-36`

新 catalog endpoint 和 generation command 使用 snake_case started/completed/failed、`category`、`component`、`duration_ms`、`initiated_by_user_id`；只记录工具数/hash/diff count，不记录 schema/description 正文。观测异常不得改变生成/校验结果。

### 子模块与 generated 文件硬失败

**Source:** `.github/workflows/ci.yaml:54-59`、`test_graph_bench_closure.py:126-135`

对齐守卫不得出现 `skip/xfail` 逃生口；`mcp/` 缺失是配置错误，不是可选环境。

## Files That Must Not Be Duplicated

| Canonical responsibility | 唯一保留位置 | 禁止复制到 |
|---|---|---|
| public MCP tool contract | `server/mcp_tools/registry.py` + serializers | npm handwritten arrays、测试字面 registry、docs |
| public URL naming | registry route projection | hooks/task/npm 各自拼另一套路由表 |
| graph-query domain schema | `server/contracts/graph-query.v1.json` | 全局 manifest 中手写第二份不同结构 |
| compatibility acceptance | `server/contracts/mcp-tools.compat.v1.json` | generated manifest、registry import、自更新测试 |
| stdio handoff persistence | `mcp/src/server.ts` 当前未提交 helper | generated catalog、Django view |
| container knowledge whitelist/quota | `task/core/knowledge_tools.py` | public npm registry |
| await pseudo-tool | `task/core/knowledge_tools.py` | Django URL/public catalog |
| container submit callback MCP | `task/core/agent_submit_mcp.py` | public control plane |
| HTTP auth/ledger/metrics | `McpToolView` | registry/generator/npm schema |

## No Analog Found

| 文件/能力 | Role | Data Flow | 原因 |
|---|---|---|---|
| DRF request/response serializer → 完整 JSON Schema 2020-12 converter | utility | transform | 当前仓只有 graph-query 单份手写 JSON Schema；没有覆盖 DRF field 全集、nullable/regex/list/dict 的通用 converter。应按实际 55 个 serializer 字段闭集实现并以 golden/round-trip 测试锁定，不扩成通用 OpenAPI 框架。 |

## Metadata

**Analog search scope:** `server/mcp_tools/`、`server/contracts/`、`server/agents/tools/`、`server/workflows/`、`server/codegraph/`、`task/core/`、`mcp/src/`、`mcp/tests/`、`server/tests/`、`.github/workflows/`

**Key analogs read:** 22

**Pattern extraction date:** 2026-09-14

