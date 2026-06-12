# Phase 17: 变量引用链路修复 - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳，用户授权全程 smart 决策)

<domain>
## Phase Boundary

用户在变量选择器里选中的引用，保存后执行时所选即所得——可解析则取到值，不可解析则显式报错指明原因。覆盖 VAR-01（short_id 保存同步/重写）、VAR-02（解析失败显式报错）、VAR-03（前端三入口引用格式统一）、VAR-04（嵌套路径 + 解析器专项测试）。

不在本阶段范围：引擎状态机（Phase 18）、保存校验（Phase 20）、IssuesPanel（Phase 20）、节点定义 SSOT（Phase 19）。

</domain>

<decisions>
## Implementation Decisions

### 解析失败语义（VAR-02 — 全里程碑语义地基，一次定对）
- 失败时机：节点执行前的模板渲染/输入收集阶段即失败（fail-fast），返回 `NodeResult(status="failed", error=...)`，不进入节点业务逻辑、不静默替换为空串
- 错误信息必须包含：完整模板片段、失败的引用路径、失败原因分类（节点 ID 不存在 / 字段不存在 / 未知前缀）、可用候选（可用节点 ID 列表或该节点输出的顶层字段 keys）
- 未知前缀（如 `{{foo.bar}}` 不属于 input/context/config/nodes/global/trigger/$）：显式报错，不再原样保留 `{{...}}` 字面量输出
- 字段路径缺失（节点存在但字段不存在）：报错指明"节点 X 输出中不存在字段 path Y"，废除 render 路径上默认空串回退
- 错误信息语言：中文（与项目后端约定一致），并以结构化字段（reference / reason / available）落入 NodeExecution.error_message，供 Phase 21 错误展示直接复用

### short_id 同步策略（VAR-01）
- bulk-update 保存时：客户端提供的 short_id 直接落库为权威值；服务端校验工作流内唯一性
- short_id 缺失或冲突时：服务端生成新 short_id，并同步重写该工作流所有节点 config 中引用旧 short_id 的 `{{nodes.<old>.*}}` 为新值——保证"保存成功 ⇒ 引用可解析"不变式
- 解析端兼容：`previous_outputs` 查找同时支持 short_id 与节点 UUID（归一化查找），存量工作流不回退
- 不做全局迁移脚本强制重写历史数据；靠保存路径收敛（下次保存即修复）

### 引用格式统一（VAR-03）
- 统一规范格式：`{{nodes.<short_id>.<field.path>}}`；VariablePicker、端口复制、SmartInput 三个入口全部生成该格式，禁止再生成 UUID 形式引用
- JSONPath 高级语法（`{{$...[...]}}`）保留现状不动，属于高级用法不在入口生成范围内
- `{{trigger.*}}`/`{{global.*}}` 等非节点前缀格式保持现有语法，三入口生成时也走统一的引用构造函数（前端单一 util，杜绝三处各写一遍）

### 嵌套路径与测试（VAR-04）
- `{{nodes.x.data.name}}` 点路径逐层下钻 dict；list 数字索引（`items.0.name`)顺带支持；中途非 dict/list 或键缺失 → 解析失败报错
- `render_template` 与 `get_template_value` 两个 API 行为一致（同一套解析核心），错误语义相同
- 专项单元测试覆盖：错误节点 ID（含大小写近似提示）、字段不存在、未知前缀、UUID vs short_id 双键、嵌套 dict/list 路径、单变量保类型（get_template_value）、多变量字符串渲染（render_template）

### Claude's Discretion
- 解析核心是否抽取独立模块（如 `workflows/engine/template_resolver.py`）还是留在 base.py 内重构——按改动面最小且可测性最好选择
- 错误信息具体文案措辞
- 前端引用构造 util 的文件位置与命名

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/nodes/base.py:341 render_template` / `:431 get_template_value` / `_resolve_jsonpath` / `_resolve_simple_path` — 现有解析器，节点 ID 不存在已抛 ValueError（含大小写提示），但未知前缀原样保留、字段缺失返回空串
- `server/workflows/migrations/0006_short_id_for_nodes_edges.py` — short_id 字段已存在于 Node/Edge 模型
- `server/workflows/api/views.py` / `serializers.py` — bulk-update 保存入口
- `web/src/components/workflow/VariablePicker.vue`、`smart-input/`（VariableNode.ts / VariableSuggestionList.vue）、`NodePortsDisplay.vue`（端口复制）— 三个引用生成入口

### Established Patterns
- 节点失败语义：`NodeResult(status="failed", error=...)` 不向引擎外抛异常（CONVENTIONS）
- 后端注释/错误文案中文；pytest + factory-boy 测试
- 前端工具函数置于 composables / utils，TS 严格类型

### Integration Points
- `previous_outputs` 字典的键由 scheduler 写入（scheduler.py 含 short_id 逻辑）——解析端双键兼容需检查写入侧
- Phase 18 的 `{{trigger.*}}` 注入、Phase 20 的引用校验、Phase 21 的错误展示都消费本阶段定稿的失败语义与错误结构

</code_context>

<specifics>
## Specific Ideas

- 错误结构化：error_message 人类可读 + 机器可读字段并存，避免 Phase 21 前端解析字符串
- "保存成功 ⇒ 引用可解析"作为本阶段核心不变式写进测试

</specifics>

<deferred>
## Deferred Ideas

- 历史工作流数据的一次性 short_id 引用迁移脚本（按需，保存路径已能收敛）
- JSONPath 语法的入口级支持（高级用法维持手写）

</deferred>

---

*Phase: 17-varref*
*Context gathered: 2026-06-12 via autonomous smart discuss*
