# graph_bench — v0.22 图查询能力冻结 gold 数据集

**用途：** 本目录是 Phase 133「同仓同 commit 基准与 v0.22 baseline」的可版本化冻结
gold 数据集，用于对**未修改的 v0.22 图查询能力**（Symbol / Process / resolved
edge / impact / trace）在同一仓库、同一 commit 上产出逐 case、逐桶的原始
baseline。数据集独立于被测 codegraph，是 ground truth；版本化入 git，任何改动
可审查 diff。

## 文件清单

| 文件 | 作用 |
|------|------|
| `manifest.json` | 数据集级身份：`gold_version` / `annotated_at_sha` / `repository` / `branch` / `splits` 三切分映射 / 防反导 `_doc` 声明 |
| `dev.json` | baseline 用 dev 切分 seed case |
| `locked_test.json` | baseline 用 locked test 切分 seed case |
| `holdout.json` | holdout 空壳（`{"cases": []}`），留 Phase 140 最终验收填充；**baseline 阶段 command 不读它** |
| `README.md` | 本文件：标注口径 / 分桶维度 / 防反导声明 / 水位对齐 / 扩容 runbook |

## 切分口径

- **baseline 只用 `dev` + `locked_test` 两个切分**；`holdout` 是空壳，留给
  Phase 140 最终验收，本阶段一律不读。
- 每条 case 的 `split` 字段必须与其所在文件一致（`dev.json` 内 `split="dev"`，
  `locked_test.json` 内 `split="locked_test"`），且 split 文件名与
  `manifest.splits` 映射一致。
- `gold_version` 随数据演进递增，便于 Phase 140 追溯。当前为 `"2"`：在真实
  baseline 首次冻结前，把 Python from-import seed 的旧 `from_import` 标记显式
  映射为 resolver canonical `import_alias`，并纳入 `re_export` / `component`。
  此映射不得由 candidate 结果反向修改。

## 标注口径

### 分桶维度（必填，闭集取值）

因 `Symbol`/`Endpoint` 模型无显式 `language`/`framework` 字段，四个分桶维度为
**必填标注字段**，由标注者显式填写，**不从被测图派生**（既保证分桶稳定，也强化
gold 独立于被测图）：

| 字段 | 闭集取值 | 含义 |
|------|----------|------|
| `language` | `python` / `typescript` / `javascript` / `go` | case 涉及代码的语言 |
| `framework` | `django` / `vue` / `gin` / `none` | 框架上下文；无显式框架时填 `none` |
| `entry_type` | `http_endpoint` / `process_entry` / `plain_symbol` | 入口类型：HTTP 端点 handler / 流程入口 / 普通符号 |
| `call_shape`（仅 edge gold） | `direct` / `member` / `import_alias` / `receiver` / `from_import` / `re_export` / `component` | 调用形态 |

越出闭集的取值会被 schema 校验（`validate_gold_case`）拒绝。

### gold 字段含义

| 字段 | 含义 |
|------|------|
| `case_id` / `split` / `query` | case 标识 / 所属切分 / 非空白自然语言 query |
| `expected_symbols[]` | NL→Symbol recall 的 gold：`{uid, file_path, start_line, name}` |
| `expected_processes[]` | NL→Process recall 的 gold：`{process_key, name}`（命中按 `process_key`/UID 精确匹配，禁止名称模糊命中） |
| `edge_golds[]` | resolved edge 的 gold：`{caller_uid, callee_uid, call_shape, evidence_file_line}` |
| `trace_golds[]` | trace 的 gold：`{source_uid, target_uid}` |
| `impact_golds[]` | impact 的 gold：`{seed_uid, expected_affected_uids: [...]}` |
| `protected` | 受保护桶标记（缺省 `false`）；受保护桶单列，不被 overall 提升抵消 |

`uid` 用稳定可读字符串（如 `py:app/urls.py::router`），在同一切分内自洽。不用
的指标维度给空列表。

## 防循环论证（防反导）声明

**resolved edge gold 来自独立 callsite 抽样的人工/规则标注，禁止从被测
codegraph 反向导出。** 具体约束：

- 每条 `edge_golds[]` 必须填 `call_shape` 与 `evidence_file_line`（形如
  `path/to/file.py:123`），作为**独立 callsite 标注的人工核验锚点**。
- **禁止**用被测图的调用边现值反向回填 gold——那等于让被测系统给自己打分
  （循环论证），会使 edge recall 恒为 1.0、baseline 失去意义。
- gold 全部独立标注、版本化入 git，改动可审查 diff；水位不一致即判 INVALID。

## 水位对齐（INVALID 前提）

`manifest.annotated_at_sha` 必须与评测目标仓按 `(repository, branch)` 取到的
`last_indexed_commit_sha` **一致**，否则 run 标 `INVALID` 并中止、不产出任何可
比较结论。当前 `annotated_at_sha` 为占位符，评测者运行真实 baseline 前必须以
目标仓实际 `last_indexed_commit_sha` 对齐并冻结。

## 扩容 runbook

1. **选定并冻结目标仓：** 选定一个已索引的目标仓，按其 `(repository, branch)`
   读取 `last_indexed_commit_sha`，把它填入 `manifest.annotated_at_sha` 与
   `repository` / `branch`，完成冻结（三方水位一致才能跑）。
2. **按 split 增加独立标注 case：** 在 `dev.json` / `locked_test.json` 内新增
   case，逐条独立标注 query、四个分桶维度与各指标 gold；resolved edge 走独立
   callsite 抽样并填 `evidence_file_line` 锚点，**绝不从被测图反导**。让每个
   受保护桶的样本数达到 `MIN_BUCKET_SAMPLES`（默认 3）。
3. **递增 `gold_version`：** 每次数据演进（增删 case、改标注、换冻结水位）递增
   `manifest.gold_version`，便于 Phase 140 同条件追溯。

**当前状态说明：** 现有 `dev.json` / `locked_test.json` 为**最小 seed 集**（各 3
条），仅用于让评测 harness 端到端可跑、覆盖全部指标路径与多个分桶。对真实冻结
仓的**完整独立标注**是评测者运行真实 baseline 前的后续动作，按上方 runbook 扩容。
