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
