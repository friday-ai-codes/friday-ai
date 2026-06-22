# Phase C Spike — django-async-backend & free-threading

**分支**：`spike/phase-c-async-orm-freethreading`
**日期**：2026-06-23
**栈基线**：Django 6.0.1 / psycopg 3.3.x / Python 3.14.2 / uv 0.11.8 / macos-aarch64

目的：用真实环境验证两条 Phase C 方向是否可行，产出 go/no-go 证据（**不进生产**）。

---

## Spike 1 — django-async-backend：🟢 GREEN（可进入更深 spike）

### 验证方法
隔离 venv（Python 3.14.2）：
```
uv pip install "django==6.0.1" "psycopg[binary]>=3,<4" django-async-backend
```

### 结果
- ✅ 解析干净：`django-async-backend==6.0.7` + `django==6.0.1` + `psycopg==3.3.4` 无冲突。
- ✅ 导入通过：`django_async_backend.db` / `.db.backends.postgresql` / `.db.transaction`
  / `.middleware` 全部 import OK。
- ✅ 关键 API 在位：`async_atomic`（callable）、`async_connections`（AsyncConnectionHandler）。

### 结论 & 下一步
与我们**精确的生产栈兼容**，可作为「目标 A」绞杀者载体（留在 Django，仅换 ORM 底座）。
未做：连真实 Postgres 的热点只读路径 benchmark（需起 PG，属下一步）。
⚠️ 仍**不进生产**：6.0.x 仍年轻、单一维护者、且是 Django 指导委员会口中的「外部验证通道」。
定位 = 热点路径 spike，不是默认引擎。

---

## Spike 2 — free-threading（no-GIL）：🔴 RED（暂不可行）

### 验证方法
freethreaded venv：`uv venv --python 3.14.2+freethreaded`（`sys._is_gil_enabled()==False` 确认）。
对每个重型原生依赖用 `uv pip install --only-binary=:all:` 探**是否存在 cp314t 预编译 wheel**。

### 结果（cp314t / macos-aarch64）

| 依赖 | ft wheel | 影响面 |
|---|---|---|
| psycopg[binary] | ❌ 无 | 数据库驱动（核心）|
| onnxruntime | ❌ 无 | fastembed/embedding（核心，且 ft 支持业界长期缺位）|
| grpcio | ❌ 无 | qdrant-client gRPC 传输 |
| tree-sitter / tree-sitter-python | ❌ 无 | 代码智能/AST |
| tokenizers | ❌ 无 | fastembed |
| mysqlclient | ❌ 无 | MySQL 驱动 |
| numpy | ✅ 有 | — |
| pydantic（pydantic-core）| ✅ 有 | — |
| cryptography | ✅ 有 | — |
| bcrypt | ✅ 有 | — |

### 结论
**全有或全无**：最关键的 5+ 个原生依赖（psycopg-binary、onnxruntime、grpcio、
tree-sitter、tokenizers）在 cp314t 下**无预编译 wheel**，无法直接组装出可运行的栈
（onnxruntime 的 free-threading 支持业界尚未到位，源码构建不现实）。

- Rust/PyO3 系（pydantic-core、cryptography、bcrypt）已就绪 ✅，印证趋势在好转。
- 但 IO 密集型系统开 no-GIL 收益本就有限（GIL 在 IO/网络等待时已释放），
  当前**风险（装不上/源码构建/扩展线程安全 bug）远大于收益**。

### cp313t 对照（3.13 free-threaded 出得更早，wheel 会更多吗？→ 否，反而更差）

同一矩阵在 `3.13+freethreaded`（3.13.13）下：

| 依赖 | cp314t | cp313t |
|---|---|---|
| psycopg[binary] | ❌ | ❌ |
| onnxruntime | ❌ | ❌ |
| grpcio | ❌ | ❌ |
| tree-sitter / -python | ❌ | ❌ |
| tokenizers | ❌ | ❌ |
| mysqlclient | ❌ | ❌ |
| cryptography | ✅ | ❌（313t 更差）|
| qdrant-client | （未测，因 grpcio 必失败）| ❌ |
| numpy / pydantic / bcrypt | ✅ | ✅ |

结论：**退回 3.13 拿不到任何好处** —— 核心阻塞依赖（psycopg/onnxruntime/grpcio/
tree-sitter/tokenizers）在 313t/314t 同样无 ft wheel，且 cryptography 在 313t 反而没有。
即「换 Python 版本」不是 free-threading 的杠杆，**杠杆在第三方 wheel**。

### 官方里程碑（PEP 703 三阶段 / PEP 779）

- **Phase I（3.13）**：free-threaded build 可用，但**实验性**。
- **Phase II（3.14，PEP 779 已 Final）**：**官方支持**，但仍是**可选非默认**构建
  （硬指标：单线程性能损失 ≤15%、内存 ≤20%）。
- **Phase III（未定版本）**：free-threaded 成为**默认** —— 尚无时间表，看社区与指标。

关键洞察：**CPython 自身已经领先你的依赖**（3.14 已 Phase II 官方支持）。真正卡住的
不是 CPython 里程碑，而是 onnxruntime/grpcio/psycopg/tree-sitter/tokenizers 的 ft wheel。
→ **watch list 应盯依赖，而非 CPython 版本**。

### 能不能自己构建 wheel？（cp314t 实测）

「有没有预编译 wheel」不等于「能不能用」。实测把阻塞依赖分成四类：

| 依赖 | 自建？ | ft 安全？ | 处置 |
|---|---|---|---|
| psycopg（纯 py，不带 [binary]）| 无需编译，直接装 | ✅ 导入后 GIL 仍关 | ✅ 去掉 `[binary]` 即可（慢一点；要快可编 psycopg-c）|
| tree-sitter（核心）| ✅ 源码构建 ~8s | ✅ 导入后 GIL 仍关 | ✅ 自建可用且 ft 安全 |
| tree-sitter-python（语法）| ❌ 构建出的是 **abi3** wheel | n/a | ❌ **abi3 与 ft 不兼容**，uv 直接拒；需上游发非 abi3 的 ft wheel 或改构建 |
| tokenizers | Rust/PyO3，需 cargo 工具链 | 近版 PyO3 支持 ft | △ 可建但需工具链 |
| grpcio | C++ 大型构建 | ft 支持仍 WIP | ❌ 绕开：qdrant 改用 HTTP 传输 |
| onnxruntime | C++ 超大构建（小时级）| ft 未支持 | ❌ 硬墙：改为独立进程 offload |
| mysqlclient | C 构建 | — | ➖ 丢弃（统一 Postgres）|

**致命前提（all-or-nothing）**：只要进程内**任何一个**已导入的 C 扩展未声明
`Py_mod_gil = Py_MOD_GIL_NOT_USED`，CPython 会**自动把 GIL 重新打开**（带 RuntimeWarning）→
全部努力归零。所以要审的不是这 7 个，而是 langchain/llama-index/claude-agent-sdk 的
**整棵传递依赖树**。

**结论**：能自建一部分（psycopg 纯/ tree-sitter 核心甚至 ft 安全），但 abi3 语法包 +
onnxruntime/grpcio 两堵墙 + 全依赖树审计 + 每次升级重建/自托管私有 wheel 的维护跑步机，
对一个 IO 密集系统的边际收益严重不划算。**比自建更划算的路 = 消除 + offload**：
psycopg 改纯 py、qdrant 改 HTTP、丢 mysqlclient、onnxruntime/embedding 拆独立进程；
剩下只有 tree-sitter 语法 + tokenizers 需要 ft 构建。即便如此，仍建议**搁置**。

### 重新评估触发条件（满足任一即重测）
- onnxruntime 发布 cp314t wheel（最大阻塞点），且
- psycopg + grpcio + tree-sitter 跟进 ft wheel。
- 备选：DB 驱动可改纯 Python `psycopg`（非 binary）绕开，但 onnxruntime/grpcio 仍是硬墙。

---

## 总体建议
- **django-async-backend**：继续推进（连 PG benchmark），作为「目标 A」绞杀者候选。
- **free-threading**：**搁置**，加入 watch list；待 onnxruntime ft wheel 落地再重测本矩阵。

## 复现
见同目录 `probe.sh`。
