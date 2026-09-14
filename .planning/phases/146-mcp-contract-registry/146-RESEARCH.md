# Phase 146: 契约注册表与生成目录 - Research

**Researched:** 2026-09-14
**Domain:** Django MCP 契约注册表、JSON Schema 生成、npm stdio 目录与兼容发布门禁
**Confidence:** HIGH

## Summary

当前公开面存在三类已复现漂移：Django URL 与 `TOOL_SCHEMA_SNAPSHOT` 有 55 个工具，npm
`FRIDAY_TOOLS` 只有 43 个；请求 serializer 与 snapshot 另有 2 组字段漂移；npm 自身测试仍可
29/29 通过，因为它只验证手写目录内部自洽。后端两个目标测试共 8 项，当前 5 项失败。
[VERIFIED: codebase inspection and targeted tests, 2026-09-14]

本阶段应把事实源收敛到 Django 侧显式 `McpToolContract` 注册表：每项绑定既有 view、请求
serializer、响应 serializer、描述、annotations 和固定 URL。注册表在运行时投影
`urlpatterns`，在构建时生成 canonical JSON manifest、兼容 snapshot 和 npm TypeScript
catalog；独立 compatibility baseline 不能由同一次生成覆盖。[RECOMMENDATION]

生成器必须是确定性的、无数据库依赖，并提供真正只读的 `--check`。npm 继续使用 bundled
catalog，不在每次 `tools/list` 时依赖网络；doctor 再用 PAT 拉取服务端 manifest 比对版本、
hash 和逐工具差异。所有成功 stdio 调用同时返回兼容的 JSON `TextContent` 和
`structuredContent`；错误继续 `isError: true`，但增加稳定机器码。[RECOMMENDATION]

**Primary recommendation:** 先冻结 55 工具的 canonical registry 与独立 baseline，再迁移
URL/snapshot/npm 三个投影；最后接入 structured results、doctor 和跨 submodule CI。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| 工具契约声明与 JSON Schema 派生 | API / Backend | — | DRF serializer 是实际请求校验边界，注册表应与它同仓。[VERIFIED: `server/mcp_tools/serializers.py`] |
| HTTP URL 投影 | API / Backend | — | 现有公开路径均为 `/api/mcp/tools/<name>/`。[VERIFIED: `server/friday/urls.py`, `server/mcp_tools/urls.py`] |
| npm `tools/list` catalog | Client / stdio adapter | API / Backend | stdio 需要离线 bundled catalog，但内容由服务端生成。[RECOMMENDATION] |
| `structuredContent` 与错误映射 | Client / stdio adapter | API / Backend | Django 返回 JSON；stdio adapter 负责映射 MCP `CallToolResult`。[CITED: https://modelcontextprotocol.io/specification/2025-06-18/server/tools] |
| manifest/hash/version 诊断 | API / Backend | Client / CLI | 服务端发布自身 manifest；doctor 比较 bundled 与 deployed 两份身份。[RECOMMENDATION] |
| breaking-change 判断 | Build / CI | API + Client | baseline 必须独立于被测注册表，避免生成物自证。[RECOMMENDATION] |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| PUB-01 | registry、HTTP URL、schema、annotations、stdio 同源 | `McpToolContract`、运行时 URL 投影、三份确定性生成物 |
| PUB-02 | 55 个服务端工具全部可由 npm 发现和调用 | 55/43 差集基线、generated catalog、stdio 集合测试 |
| PUB-03 | `mcp/` 缺失时 CI hard fail，`--check` 无漂移 | 独立 `mcp-contract-ci`、存在性断言、只读生成检查 |
| PUB-04 | baseline 识别删工具/字段、加 required、收窄 enum | 独立 JSON baseline 与递归 compatibility classifier |
| PUB-05 | npm 版本对齐，doctor 报告版本/hash/diff | `package.json` 单一 npm 版本源、manifest endpoint、doctor |
| PUB-06 | `outputSchema`、`structuredContent`、稳定机器码 | 响应 serializer、双通道成功结果、结构化错误 envelope |
</phase_requirements>

## Current-State Evidence

- `server/mcp_tools/views.py` 有 55 个非空 `tool_name`；`urls.py` 和
  `TOOL_SCHEMA_SNAPSHOT` 也各有 55 项。[VERIFIED: AST and source inspection]
- npm 只有 43 项，缺少：
  `approve_technical_blueprint`、`detect_changes`、`get_process`、
  `get_session_capture`、`graph_query`、`impact_analysis`、`list_processes`、
  `rename_preview`、`report_session_knowledge`、
  `request_technical_blueprint_changes`、`search_session_knowledge`、
  `trace_call_path`。[VERIFIED: set comparison of current files]
- serializer 相比 snapshot 多出
  `report_project_knowledge.{branch_name,repository_id,writeback_mode,target,distill}` 和
  `route_blueprint_repos.{space_id,team_id,primary_team}`。[VERIFIED: live DRF field audit]
- `mcp/src/server.ts` 的 `SERVER_VERSION='0.2.0'`，`mcp/package.json` 为 `0.6.0`。
  [VERIFIED: codebase]
- 当前 CI 的路径过滤不含 `mcp/**`，没有 npm MCP job；`server-ci` 虽递归 checkout
  submodule，但 alignment test 在 `mcp/` 缺失时调用 `pytest.skip`。[VERIFIED:
  `.github/workflows/ci.yaml`, `test_mcp_package_alignment.py`]
- `mcp` 是 git submodule；当前其 `src/server.ts`、`src/tools.ts`、
  `tests/server.test.ts` 有未提交的 confirmed handoff 文件持久化修改。[VERIFIED:
  `git ls-files --stage mcp`, `git -C mcp status/diff`]

## Project Constraints (from `.cursor/rules/`)

- 新/改 MCP 与 API 生命周期必须使用 `structlog` 结构化事件，事件名
  `*_started/completed/failed`，包含 `category`、`component`、`duration_ms`。
  [VERIFIED: `.cursor/rules/observability-logging.mdc`]
- MCP 是 caller 入口，必须保留 `user_id/request_id/source/trace_id` 和 `run_id` 关联；
  观测写入必须 best-effort。[VERIFIED: `.cursor/rules/observability-logging.mdc`]
- token、凭证、上游响应与异常文本不得明文记录；日志和 Ledger 分别走既有脱敏入口。
  [VERIFIED: `.cursor/rules/observability-logging.mdc`]
- 不新增运行时依赖；Node、pnpm、Python 和现有依赖主版本不调整。[VERIFIED: user scope and
  workspace dependency/toolchain rules]
- 修改 TypeScript 构建面后必须执行 typecheck、test 和可重复 build；CI 不得以 skip
  代替门禁。[VERIFIED: workspace build/test rule]

## Standard Stack

### Core

| Component | Current Version | Use |
|---|---:|---|
| Django / DRF serializers | Django 6.0.1 runtime；DRF existing lock | 注册表、请求/响应字段声明和实际输入校验。[VERIFIED: targeted pytest runtime, `server/uv.lock`] |
| `jsonschema` | 4.26.0 | 在测试与 compatibility validator 中校验 Draft 2020-12 schema；不新增包。[VERIFIED: `server/uv.lock`] |
| MCP TypeScript SDK | 1.29.0 | 现有 `Server`、`ListToolsRequestSchema`、`CallToolRequestSchema` 路径。[VERIFIED: `mcp/pnpm-lock.yaml`] |
| TypeScript / Vitest / tsdown | 5.9.3 / 4.1.8 / 0.22.2 | generated catalog 类型检查、stdio contract 测试和构建。[VERIFIED: `mcp/package.json`, lockfile] |
| Node built-ins | Node >=18 | `fetch`、SHA-256、文件持久化和 JSON；无需新增依赖。[VERIFIED: `mcp/package.json`] |

### Schema dialect

使用 JSON Schema Draft 2020-12，并在 manifest 顶层固定
`"$schema": "https://json-schema.org/draft/2020-12/schema"`。仓内已有
`BLUEPRINT_JSON_SCHEMA` 与 `Draft202012Validator` 实践。[VERIFIED:
`server/services/process_runtime/blueprint_schema.py`; CITED:
https://json-schema.org/draft/2020-12/json-schema-core.html]

MCP Tool 的 `inputSchema` 与 `outputSchema` 根节点必须是 object；若声明
`outputSchema`，成功结果必须提供与其一致的 `structuredContent`。为兼容旧客户端，还应把
同一 JSON 序列化到 text content。[CITED:
https://modelcontextprotocol.io/specification/2025-06-18/server/tools]

**Installation:** 无新增 Python/npm 依赖，不需要 Package Legitimacy Audit。

## Recommended Architecture

### Data flow

```text
DRF request/output serializers + tool metadata + existing view class
                              │
                              ▼
                    McpToolContract registry
                      │       │        │
             runtime │       │ build  │ build
                      ▼       ▼        ▼
             Django urlpatterns   canonical manifest JSON
                                      │
                         ┌────────────┼──────────────┐
                         ▼            ▼              ▼
                 generated snapshot  generated TS   manifest endpoint
                         │            catalog             │
                         ▼              │                 ▼
                server contract tests   └─ tools/list   doctor diff
                                     
independent compatibility baseline ── compare ── current canonical manifest
```

### Canonical registration model

在 `server/mcp_tools/registry.py` 定义冻结 dataclass：

```python
@dataclass(frozen=True, slots=True)
class McpToolContract:
    name: str
    view_class: type[APIView]
    request_serializer: type[serializers.Serializer]
    response_serializer: type[serializers.Serializer]
    description: str
    annotations: McpToolAnnotations
    endpoint: str | None = None
```

[RECOMMENDATION]

`endpoint` 缺省严格派生为 `/api/mcp/tools/{name}/`；只有迁移旧 URL 时才允许显式 override。
Django route name 派生为 `mcp-tool-{name.replace('_', '-')}`。初始化时拒绝重名、空描述、
缺 annotation、view 非 `McpToolView`、name 与旧格式不符。[RECOMMENDATION]

为避免 `views ↔ registry` 循环，`registry.py` 在 views 模块定义完成后引用 view classes；
`urls.py` 只 import registry 的 `build_tool_urlpatterns()`。`McpToolView` 在请求运行期按自身
class 从 registry 查 request serializer 和 tool name，不再让 55 个 `post()` 各自传一份
serializer。这样实际校验和生成 schema 使用同一 class。[RECOMMENDATION]

### DRF field → JSON Schema mapping

在 `server/mcp_tools/schema.py` 写纯函数 mapper，仅覆盖仓内实际字段类型：

| DRF field | JSON Schema |
|---|---|
| `CharField` / `RegexField` | string；映射 `minLength/maxLength/pattern` |
| `UUIDField` | string + `format: uuid` |
| `IntegerField` / `FloatField` | integer / number + min/max |
| `BooleanField` | boolean |
| `ChoiceField` | 按 choice 原始类型 + `enum` |
| `ListField` | array + 递归 `items` + `minItems/maxItems` |
| `DictField` / `JSONField` | object；未知嵌套保持开放 |
| `allow_null=True` | `type` 包含 `null` |
| 非 empty `default` | JSON-safe `default` |
| `field.required=True` | 加入父 object 的 `required` |

[VERIFIED: DRF field semantics at https://www.django-rest-framework.org/api-guide/fields/;
RECOMMENDATION: mapping]

输入 schema 第一阶段保持 `additionalProperties: true`，因为收紧为 false 会改变现有 HTTP
接受未知键的行为；可在未来 major baseline 中单独收紧。[RECOMMENDATION]

响应需要新增显式 `*ResponseSerializer`，不能从 `Response({...})` 的 Python AST 猜类型。
复杂嵌套对象先用 `JSONField`，但顶层 UUID、状态、计数、布尔、数组、hash 应准确建模。
所有现有 snapshot response keys 必须保留为 properties；只有每条 HTTP 200 路径都保证
存在的键才能列入 output `required`。[RECOMMENDATION]

### Generated artifacts

| File | Ownership | Content |
|---|---|---|
| `server/contracts/mcp-tools.v1.json` | generated | 55 工具完整 manifest、schema、annotations、endpoint；文件本身不含 manifest hash 或 runtime version |
| `server/mcp_tools/generated/schema_snapshot.py` | generated | 兼容导出的 request/response property key 列表 |
| `mcp/src/generated/toolCatalog.ts` | generated in submodule | `FRIDAY_TOOLS`、annotations、`CLIENT_MANIFEST_HASH` |
| `server/contracts/mcp-tools.compat.v1.json` | hand-reviewed baseline | 独立 compatibility 金标，生成器永不写 |

[RECOMMENDATION]

`server/mcp_tools/serializers.py` 暂时 re-export `TOOL_SCHEMA_SNAPSHOT`，保住现有 import；
新代码改从 generated module 读。`mcp/src/tools.ts` 变为类型与 generated exports 的薄层，
不再保存 700+ 行手写目录。[RECOMMENDATION]

manifest JSON 本身必须省略 `manifest_hash`、`generated_at`、server/client runtime version；
生成器以 UTF-8、sorted keys、紧凑 separators 和单个结尾换行写出 canonical bytes。
manifest hash 固定为**该已落盘文件精确 bytes**的 SHA-256，不再对反序列化对象二次
canonicalize。manifest API 与 npm doctor 必须读取/比较同一组 bytes 及其 hash；同一契约
跨平台和重复生成必须同 hash。[DECISION]

### Generator and `--check`

管理命令固定为：

```bash
cd server
uv run python manage.py generate_mcp_contracts
uv run python manage.py generate_mcp_contracts --check
```

[RECOMMENDATION]

普通模式先在内存生成全部文件，再逐文件原子替换；`--check` 只读取并比较，禁止写文件，
缺文件、内容漂移、`mcp/` 不存在、submodule 未 checkout 均以 `CommandError` 非零退出，并
打印文件名与精简 unified diff。生成内容禁止时间戳，避免干净树抖动。[RECOMMENDATION]

## URL and Snapshot Projection Strategy

1. 先用 characterization test 冻结当前 55 个 `(name, path, route_name, view_class)`。
   [RECOMMENDATION]
2. registry 录入同一集合，测试 registry 与旧 URL tuple 完全相等。[RECOMMENDATION]
3. `urls.py` 改为 manifest endpoint + `build_tool_urlpatterns()`；旧工具路径和 route name
   不变。[RECOMMENDATION]
4. 生成 snapshot property 列表并保留旧导入名；删除 900 行“源码再复制一次”的快照测试，
   由独立 compatibility baseline 承担防破坏职责。[RECOMMENDATION]
5. 对 2 组当前 serializer/snapshot 漂移采用 additive 修复：把 serializer 已接受字段加入
   canonical schema，不删除旧字段、不新增 required。[RECOMMENDATION]

## Compatibility Baseline and Breaking Rules

`mcp-tools.compat.v1.json` 首次应从修复后的 55 工具 manifest 审核后冻结，但它不是 generated
target。未来只有明确接受新 baseline 时人工运行单独的
`accept_mcp_contract_baseline` 命令；日常 generator 不得触碰它。[RECOMMENDATION]

compatibility classifier 递归比较 baseline → current：

| Change | Classification |
|---|---|
| 删除/重命名工具、endpoint 或旧 route | breaking |
| 删除 input/output property | breaking |
| optional → required；新增 required | breaking |
| enum 删除旧值（新 enum 不是旧 enum 的 superset） | breaking |
| 类型不再接受旧类型或旧 `null` | breaking |
| minimum/minLength/minItems 提高；maximum/maxLength/maxItems 降低 | breaking |
| 新增 pattern/format、`additionalProperties: true → false` | breaking |
| annotation 从只读变写、非破坏变破坏、幂等变非幂等、closed-world 变 open-world | breaking / publish block |
| 新增工具、optional property、enum 值，或放宽边界 | additive |
| description/title 修改 | documentation-only |
| default 修改 | behavioral-risk；要求显式 baseline review |

[RECOMMENDATION]

分类器必须有 table-driven 正反测试，尤其覆盖 PUB-04 明列的四类破坏。不要使用普通
deep-equality 代替兼容判断；additive 变化应允许 server-first 部署。[RECOMMENDATION]

## npm stdio Result Contract

### Successful calls

`ToolCallResult` 增加 `structuredContent?: Record<string, unknown>`。普通工具成功时：

```typescript
return {
  content: [{ type: 'text', text: JSON.stringify(body, null, 2) }],
  structuredContent: body,
}
```

[CITED: https://modelcontextprotocol.io/specification/2025-06-18/server/tools;
RECOMMENDATION: implementation]

调用前按 generated catalog 拒绝未知工具；响应后可在测试环境用 outputSchema 校验。
生产 adapter 不新增运行时 JSON Schema validator，以满足零新依赖并避免观测逻辑反噬调用。
[RECOMMENDATION]

### Confirmed handoff special case

不得覆盖用户当前未提交的 handoff 持久化实现。把它保留为 handwritten result adapter
（可从 `server.ts` 移到 `resultAdapters.ts`），generator 只写
`src/generated/toolCatalog.ts`。[RECOMMENDATION]

该工具应继续：目录 mode `0700`、文件 mode `0600`、临时文件后 rename、模型只收到摘要。
其 `structuredContent` 使用同一摘要对象，不放完整 `canonical_content/markdown`。
[VERIFIED: current uncommitted `mcp/src/server.ts`; RECOMMENDATION]

为了让 HTTP 原始响应和 stdio 本地摘要都符合一个 outputSchema，该工具 schema 的 properties
包含两组 additive 字段，required 只取共同稳定坐标：
`technical_plan_id/artifact_id/artifact_version_id/content_hash/current_status/
repository_task_count/run_id`；原始正文键与 `handoff_file/handoff_file_sha256/markdown_chars`
均为 optional。另在 manifest 加内部生成元数据 `resultAdapter:
"persist_confirmed_handoff"`，但不要把它当 MCP 标准 annotation。[RECOMMENDATION]

### Stable errors

Django 继续返回 `{error_code, detail}`。stdio 对非 2xx JSON 响应返回：

```json
{
  "isError": true,
  "structuredContent": {
    "error_code": "not_found",
    "http_status": 404,
    "retryable": false,
    "run_id": null
  }
}
```

并保留中文 text 供旧客户端显示。[RECOMMENDATION]

客户端自产错误固定为：
`mcp_config_missing`、`mcp_network_error`、`mcp_timeout`、
`mcp_authentication_failed`、`mcp_invalid_json`、`mcp_unknown_tool`、
`mcp_manifest_mismatch`。HTTP body 只解析 allowlisted 机器字段，不能把未脱敏的前 2000
字符直接回显。[RECOMMENDATION]

## Manifest Endpoint, Hash and Doctor

新增已认证 `GET /api/mcp/manifest/`，返回：

```json
{
  "server_version": "0.1.0",
  "contract_version": "mcp-tools/v1",
  "manifest_hash": "<sha256>",
  "manifest": {"tools": []}
}
```

[RECOMMENDATION]

`server_version` 从已安装 Django distribution `friday` 的 package metadata 读取；当前
`server/pyproject.toml` 是 `0.1.0`。它与 npm client version 是不同发布轴，不要求数值相等。
[VERIFIED: `server/pyproject.toml`; RECOMMENDATION]

npm `SERVER_VERSION` 必须直接从 `package.json.version` 导入/派生，而不是再保留字符串副本；
测试断言两者相等。当前 `0.2.0`/`0.6.0` 的错位因此消失。[RECOMMENDATION]

`doctor` 使用现有 config/PAT 请求 manifest，输出：

- npm/client version 与 bundled manifest hash；
- server version、contract version 与 deployed hash；
- `missing_on_client`、`missing_on_server`、`changed_tools`；
- compatibility 结论（compatible additive / incompatible / exact）；
- 401/403、404（实例太旧）、网络错误的稳定诊断。

[RECOMMENDATION]

hash 不同不应一律失败：仅 additive server changes 可 warning；缺客户端已有工具或 schema
breaking diff 才返回非零。若 endpoint 404，doctor 明确报告“server 不支持 manifest
diagnostics”，不能伪装成 hash 相同。[RECOMMENDATION]

## Migration Strategy

### Wave 1 — Freeze and characterize

- 保存现有 55 URL tuple、55 snapshot keys、npm 43/缺 12 集合和已有 required 字段 fixture。
- 将当前 handoff diff 视为输入，不 reset、不 checkout、不由 generator 覆盖。
- 建 55 工具 baseline 前先修复 2 组 additive snapshot 漂移。

[RECOMMENDATION]

### Wave 2 — Introduce registry without changing behavior

- 新增 registry、response serializers、schema mapper和 manifest builder。
- URL 仍先走旧列表；对拍 registry 输出与旧 URL/snapshot/npm metadata。
- 所有 55 个 view 改为通过 registry 获取 request serializer；每小批运行目标 tests。

[RECOMMENDATION]

### Wave 3 — Switch projections

- 切 `urls.py` 到 registry projection。
- 生成 canonical JSON、snapshot module 和 TS catalog。
- `tools.ts` 改薄 re-export；确认 handoff adapter 和测试仍在。

[RECOMMENDATION]

### Wave 4 — Protocol and release gates

- 加 `outputSchema`、`structuredContent`、错误机器码、manifest endpoint 和 doctor diff。
- 加 compatibility classifier、`--check`、mcp CI job 和 publish前相同门禁。
- 先部署兼容 server，再发布 bundled 55-tool npm package。

[RECOMMENDATION]

无需数据库 migration；这是代码/制品/发布顺序迁移。submodule 内先形成独立 commit，再由
父仓提交 gitlink，避免父仓指向不存在的 npm commit。[VERIFIED: mcp is a git submodule;
RECOMMENDATION]

## Exact File Plan

### Add

- `server/mcp_tools/registry.py`
- `server/mcp_tools/schema.py`
- `server/mcp_tools/response_serializers.py`
- `server/mcp_tools/manifest.py`
- `server/mcp_tools/management/__init__.py`
- `server/mcp_tools/management/commands/__init__.py`
- `server/mcp_tools/management/commands/generate_mcp_contracts.py`
- `server/mcp_tools/generated/__init__.py`
- `server/mcp_tools/generated/schema_snapshot.py` (generated)
- `server/contracts/mcp-tools.v1.json` (generated)
- `server/contracts/mcp-tools.compat.v1.json` (hand-reviewed)
- `server/tests/mcp_tools/test_contract_registry.py`
- `server/tests/mcp_tools/test_contract_generation.py`
- `server/tests/mcp_tools/test_contract_compatibility.py`
- `server/tests/mcp_tools/test_manifest_api.py`
- `mcp/src/generated/toolCatalog.ts` (generated)
- `mcp/src/resultAdapters.ts` (optional extraction preserving handoff)

### Modify

- `server/mcp_tools/views.py` — registry-backed request serializer/name；manifest GET view。
- `server/mcp_tools/urls.py` — manifest route + registry-generated tool routes。
- `server/mcp_tools/serializers.py` — remove handwritten snapshot body, compatibility re-export。
- `server/mcp_tools/errors.py` — stable error metadata only if kept transport-neutral.
- `server/tests/mcp_tools/test_schema_snapshot.py` — replace duplicated full literal with baseline tests.
- `server/tests/mcp_tools/test_mcp_package_alignment.py` — parse generated catalog/manifest; missing
  submodule is assertion failure, never skip.
- `mcp/src/tools.ts` — generated catalog re-export and shared types.
- `mcp/src/server.ts` — package-derived version、outputSchema、structuredContent、stable errors；
  preserve handoff persistence.
- `mcp/src/cli.ts` — doctor manifest/hash/version/diff.
- `mcp/tests/server.test.ts` — remove hardcoded 43；assert 55 set、output schema、structured results、
  handoff summary.
- `mcp/package.json` — version remains `0.6.0`; expose it as the only `SERVER_VERSION` source.
- `.github/workflows/ci.yaml` — include `mcp/**`; add contract job with recursive submodules.

[RECOMMENDATION]

## CI Design

新增 `mcp-contract-ci`，顺序固定：

```bash
test -f mcp/package.json
test -f mcp/src/generated/toolCatalog.ts
cd server && uv sync --locked --dev
uv run python manage.py generate_mcp_contracts --check
uv run pytest tests/mcp_tools/test_contract_registry.py \
  tests/mcp_tools/test_contract_generation.py \
  tests/mcp_tools/test_contract_compatibility.py \
  tests/mcp_tools/test_manifest_api.py \
  tests/mcp_tools/test_mcp_package_alignment.py -q
cd ../mcp
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

[RECOMMENDATION]

checkout 必须 `submodules: recursive`；步骤开头同时校验 `git submodule status mcp` 不以 `-`
开头。PR/push paths 加 `mcp/**`、`.gitmodules`、相关 contract 路径。server alignment test
删除两个 `pytest.skip` 分支。[RECOMMENDATION]

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Backend | pytest 9.0.2 + pytest-django 4.11.1。[VERIFIED: targeted test runtime] |
| npm | Vitest 4.1.8 + TypeScript 5.9.3。[VERIFIED: current package test/typecheck] |
| Quick backend | `cd server && uv run pytest tests/mcp_tools/test_contract_*.py tests/mcp_tools/test_mcp_package_alignment.py -q` |
| Quick npm | `cd mcp && pnpm test -- --run tests/server.test.ts && pnpm typecheck` |
| Phase gate | generator `--check` + targeted backend + npm typecheck/test/build + parent server suite |

### Requirement → Test Map

| Req | Test |
|---|---|
| PUB-01 | registry ↔ URL ↔ manifest ↔ generated TS deep equality |
| PUB-02 | exact 55-name set、12 historic gaps present、each URL callable through mocked stdio |
| PUB-03 | missing `mcp/` subprocess returns nonzero；dirty generated fixture makes `--check` nonzero |
| PUB-04 | parametrized delete tool/property/add required/narrow enum all rejected；additive cases accepted |
| PUB-05 | `SERVER_VERSION === packageJson.version`；doctor exact/additive/breaking/404/401 snapshots |
| PUB-06 | every catalog tool has outputSchema；representative HTTP success validates；stdio returns matching structuredContent；errors expose machine code |

[RECOMMENDATION]

### Required semantic tests

- 每个 request serializer 的 fields、required、enum、limits 与 generated input schema 对拍。
- 每个 output serializer 至少一个 representative success fixture；高变体工具覆盖所有 200
  分支。
- `Draft202012Validator.check_schema` 检查 110 个 input/output schema。
- 55 个工具的 annotations 全字段存在；mutation 不得误标 readOnly。
- handoff `structuredContent` 不含 marker 正文，文件 bytes 与 HTTP body 一致，hash 可复算。
- generator 连跑两次 bytes 完全一致，`--check` 前后 git worktree 不变。
- old URL/name/required fixture 完全保留；新增字段只能 additive。

[RECOMMENDATION]

### Wave 0 gaps

上述 `test_contract_*`、response serializers、独立 baseline 和 generated targets 当前均不存在，
应先建立测试与 fixture，再切换生产 projection。[VERIFIED: current file inventory]

## Observability Impact

registry/schema 生成器与 bundled `tools/list` 是离线纯函数，不应写 Interaction Ledger，也不应
产生逐工具 INFO 日志。[RECOMMENDATION]

新增 `GET /api/mcp/manifest/` 是 caller 入口，应有
`mcp_manifest_started/completed/failed`，`category="caller"`、
`component="mcp_tools"`、`duration_ms`、manifest hash、tool_count 和 HTTP status；禁止记录
PAT、manifest 正文或异常原文。指标/日志失败必须吞掉。[VERIFIED:
`.cursor/rules/observability-logging.mdc`; RECOMMENDATION]

现有 tool POST 继续走 `McpToolView._begin/_record` 和统一中间件，不新增 LLM、检索、队列或
后台任务，因此本阶段不需要新的 `call_source`、`RetrievalTrace`、queue gauge 或 DB
migration。[VERIFIED: current architecture; RECOMMENDATION]

npm doctor 是本地 CLI，不写服务端 Ledger 之外的敏感日志；输出只显示 token 长度、版本、
hash 和工具名差异，不显示 token 或响应正文。[RECOMMENDATION]

## Security Domain

### Applicable ASVS Categories

| Category | Applies | Control |
|---|---|---|
| V2 Authentication | yes | manifest endpoint 复用 `AccessTokenAuthentication`/JWT；stdio 不回显 PAT。[VERIFIED: existing MCP auth pattern] |
| V3 Session | limited | 保留现有 `X-Friday-Run-ID`；不新增 session storage。[VERIFIED: `mcp/src/server.ts`] |
| V4 Access Control | yes | registry 只改发现/路由，不绕过各 view 的权限；manifest 不暴露资源数据。[RECOMMENDATION] |
| V5 Input Validation | yes | DRF serializer 为执行时真源，JSON Schema 为公开投影。[VERIFIED: `McpToolView._validate`] |
| V6 Cryptography | yes | hash 使用 Node/Python stdlib SHA-256，不手写密码学。[RECOMMENDATION] |

### Threat controls

- 恶意工具名：只允许 registry 中的 `[a-z0-9_]+`，URL 和 stdio 都 fail-closed。
- schema poisoning：manifest 只来自代码生成并在 CI 对 baseline；不信运行时远端 schema
  覆盖 bundled catalog。
- 错误泄密：不再回显任意 `bodyText.slice(0, 2000)`；只提取 allowlisted machine fields。
- handoff 泄密：完整内容只落 mode 0600 文件，structuredContent 只给摘要。
- hash 混淆：明确 canonicalization 版本；hash 输入不含自身和运行时版本。

[RECOMMENDATION]

## Common Pitfalls

### Generated baseline self-validation

**Failure:** generator 同时重写 current manifest 和 compatibility baseline，删工具仍全绿。  
**Control:** baseline 独立、默认只读，accept 命令单独审阅。[RECOMMENDATION]

### Runtime URL import cycle

**Failure:** views import registry，registry 又 import views，Django startup 半初始化。  
**Control:** registry 只在 views 定义完成后引用 classes；view 运行时懒查 contract。
[RECOMMENDATION]

### Declaring strict output required too early

**Failure:** 某个合法 200 partial/degraded 分支缺字段，stdio 违反 outputSchema。  
**Control:** required 只含所有成功分支共同字段；用 fixtures 收紧，不凭 snapshot key 猜。
[RECOMMENDATION]

### Breaking handoff isolation

**Failure:** 通用 `structuredContent=raw body` 把完整蓝图重新送入模型上下文。  
**Control:** tool-specific handwritten adapter，generated metadata 只选择 adapter，不生成文件 IO。
[RECOMMENDATION]

### Dirty submodule overwrite

**Failure:** 首次生成直接重写 `tools.ts/server.ts`，丢失用户未提交 handoff 修改。  
**Control:** generator 仅拥有 `src/generated/toolCatalog.ts`；迁移前保存 diff，并运行 handoff
characterization test。[RECOMMENDATION]

### Hash churn

**Failure:** hash 包含时间戳、版本或不稳定 dict 顺序，每次 build 都漂移。  
**Control:**版本化 canonical JSON 算法和 golden hash test。[RECOMMENDATION]

## Don't Hand-Roll

| Problem | Don't Build | Use |
|---|---|---|
| 输入校验 | 第二套 TypeScript validator | 现有 DRF serializer |
| JSON Schema validation | 自写递归 validator | 已有 `jsonschema.Draft202012Validator` |
| hash | 自定义摘要算法 | stdlib SHA-256 |
| npm HTTP | axios/node-fetch | Node 内置 `fetch` |
| schema source | OpenAPI/Zod 第四份契约 | Django registry + generated catalog |
| submodule fallback | 缺目录时 skip | checkout hard fail |

[RECOMMENDATION]

## Plan Decomposition

### 146-01 — Canonical registry and schema model

- 新增 registry、response serializers、DRF→JSON Schema mapper。
- 冻结 55 名称/URL/required characterization；补 2 组 additive drift。
- 建独立 compatibility baseline 与 breaking classifier。
- Gate：registry 能生成合法 55-tool in-memory manifest，旧 URL/名称/required 不回退。

### 146-02 — Generated projections and URL cutover

- 新增 management command、canonical manifest、generated snapshot、generated TS。
- `urls.py` 切 registry projection，保留 serializer snapshot re-export。
- 实现确定性与 `--check`。
- Gate：重复生成 byte-identical；缺/脏任一 artifact 非零；Django reverse 全兼容。

### 146-03 — stdio structured contract and diagnostics

- npm 消费 generated catalog，补齐 12 工具，输出 outputSchema。
- 成功返回 structuredContent + text；错误返回稳定机器码。
- package-derived `SERVER_VERSION`；manifest endpoint + doctor version/hash/diff。
- 保护并测试 handoff 本地文件 adapter。
- Gate：55 tools/list；所有成功 fixture 可校验；doctor exact/additive/breaking 准确。

### 146-04 — CI and release hardening

- 新增 mcp contract job、`mcp/**` paths、recursive checkout 与 hard existence checks。
- 跑 backend targeted、npm install/typecheck/test/build、generator check。
- 把同一门禁接入 npm publish 前置步骤。
- Gate：故意移除 submodule、删工具/字段、加 required、收窄 enum 均明确失败。

[RECOMMENDATION]

## Environment Availability

| Dependency | Available | Version | Note |
|---|---:|---:|---|
| Python | yes | 3.14.2 | 满足 server `>=3.14`。[VERIFIED: local probe] |
| uv | yes | 0.12.0 | 当前 server 测试可运行。[VERIFIED: local probe] |
| Node | yes | 24.18.1 | 高于 npm `>=18`；CI 仍应使用仓库声明。[VERIFIED: local probe and package.json] |
| pnpm | yes | 10.30.3 | 当前 npm tests/typecheck 可运行。[VERIFIED: local probe] |
| mcp submodule | yes | `28f9536...` + dirty | 有 3 个未提交 handoff 相关文件。[VERIFIED: git probe] |

无外部服务依赖；本阶段测试不需要 Postgres、Redis、Qdrant、runner 或飞书。
[RECOMMENDATION]

## Assumptions Log

| # | Claim | Risk if Wrong |
|---|---|---|
| — | 无未验证事实性假设；所有新设计均标为 recommendation。 | — |

## Open Questions (RESOLVED)

1. **服务端软件版本的发布来源 — RESOLVED**
   - 当前可验证来源是 Python distribution `friday==0.1.0`，而里程碑版本是 v0.26.0。
     [VERIFIED: `server/pyproject.toml`, roadmap]
   - 决定：服务端软件版本固定来自 package/build metadata（已安装 Python distribution
     metadata），manifest registry 不维护第二份版本字面量；若未来发布系统改用统一 build
     metadata，只替换该单一 resolver，不在 registry 硬编码 git tag 或里程碑号。[DECISION]
2. **output required 的精确集合 — RESOLVED**
   - 当前 snapshot 只表示 property allowlist，不证明每个 200 分支必含所有键。
     [VERIFIED: snapshot structure and heterogeneous views]
   - 决定：Plan 01 先枚举每个工具的实际 HTTP 200 分支 fixture，再冻结 response serializer；
     `required` 只取该工具所有合法 200 fixture 的保守交集，禁止 blanket-all-fields。后续
     structuredContent 计划不得做 incompatible schema 修改；如 fixture 暴露遗漏，只允许
     additive correction，并必须重生成全部 generated artifacts、证明 compatibility baseline
     为 additive-only，且 baseline 继续保持 generator-read-only。[DECISION]

## Sources

### Primary (HIGH)

- `server/mcp_tools/serializers.py`, `urls.py`, `views.py`, `errors.py` — live 55-tool HTTP contract.
- `server/tests/mcp_tools/test_schema_snapshot.py`,
  `test_mcp_package_alignment.py` — current guards and skip weakness.
- `mcp/src/tools.ts`, `server.ts`, `cli.ts`, `mcp/tests/server.test.ts`,
  `mcp/package.json`, `mcp/pnpm-lock.yaml` — bundled 43-tool contract, versions, doctor and dirty handoff.
- `.github/workflows/ci.yaml`, `.gitmodules` — submodule checkout and missing npm job/path trigger.
- `server/contracts/graph-query.v1.json`,
  `server/services/code_graph/query_manifest.py` — existing manifest/hash precedent.
- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
  — outputSchema, structuredContent, compatibility text, annotations and error semantics.
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html)
  — selected dialect.
- [DRF serializer fields](https://www.django-rest-framework.org/api-guide/fields/)
  — required/default/null/length/list/choice field semantics.

### Secondary

- `.planning/research/SUMMARY.md`, `.planning/research/STACK.md`,
  `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md` — milestone synthesis,
  checked against live source.

## Metadata

**Confidence breakdown:**
- Current drift and test baseline: HIGH — directly reproduced.
- Registry/generation architecture: HIGH — follows current Django and graph-query manifest patterns.
- MCP result semantics: HIGH — official MCP specification.
- Per-tool output required sets: HIGH for planning — 已冻结“实际 200 fixtures + 保守 required
  交集 + 禁止 blanket-all-fields”的决策；具体字段值由 Plan 01 fixtures 机械确认。

**Research date:** 2026-09-14  
**Valid until:** 2026-10-14
