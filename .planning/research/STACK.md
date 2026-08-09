# Stack Research — v0.22.0 代码智能图分析升级（对标 GitNexus）

**Domain:** brownfield 增量（内存图服务 / impact·trace·detect_changes / 社区检测 + 模块摘要 / Semgrep taint 门禁 / volar·gopls 默认开启）
**Researched:** 2026-08-09
**Confidence:** HIGH（所有新依赖的版本与 Python 3.14 wheel 可用性均经 PyPI / 官方文档 / 官方 release notes 核实；性能数字为 MEDIUM——引用官方 benchmark 与第三方实测，未在本仓复现）

## 结论先行（TL;DR）

**本里程碑几乎零新增 Python 依赖。** 五个问题的裁决：

1. **图引擎：用已在依赖树的 networkx 3.6.1，不引入 rustworkx**。10万–100万边规模下 networkx 构建 + 反向 BFS 完全可用（图缓存后查询是毫秒–百毫秒级）；rustworkx 快 3–100 倍但**没有社区检测算法**（Louvain/Leiden 均为 open issue），引入它反而还得留着 networkx，两套图对象双倍内存。留 adapter seam，触发条件见下。
2. **社区检测：networkx 原生 `louvain_communities`（BSD，零新增依赖），不用 leidenalg**。leidenalg 是 **GPL-3.0**（python-igraph 是 GPL-2），本仓 MIT + 分发 Docker 镜像，GPL 传染风险不值得为边际质量提升买单；networkx 3.6 的 `leiden_communities` 只有 dispatch 接口、无默认实现（需 cugraph GPU backend），不可用。
3. **Semgrep：独立安装 CLI（`semgrep==1.172.*`，LGPL-2.1），subprocess 调用，绝不装进 server venv**。diff 扫描用 `semgrep scan --config <rulesets> --baseline-commit <merge-base> --json`。**CE（免费版）taint 只有单函数内分析**，跨函数/跨文件 taint 是付费 Pro 能力——门禁设计必须按 CE 能力上限收敛预期，Pro 留 opt-in 升级路径。
4. **内存图缓存 LRU：零新增依赖，纯 stdlib**（`collections.OrderedDict` + `threading.Lock`；失效走 `last_indexed_commit_sha` 水位比对，不是时间 TTL）。cachetools 不在依赖树，也不需要进来。
5. **volar/gopls 默认开启的真正前提是改 `server/Dockerfile`**：当前 `python:3.14-slim` 镜像**没有 Node 也没有 Go**，两个 kill-switch 打开了探针也会 fail-soft 回落 tree-sitter。需加 Node 22 LTS + `@vue/language-server`（v3.x）+ Go 工具链 + gopls（当前 v0.23.0）。

## Recommended Stack

### Core Technologies（图分析）

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| networkx | 3.6.1（已在 `uv.lock`，llama-index 传递依赖） | 内存图构建、反向 BFS（impact）、最短路（trace）、正向遍历（执行流）、Louvain 社区检测 | 零新增依赖；纯 Python wheel 天然兼容 Py3.14；API 覆盖本里程碑全部算法需求（`bfs_layers`/`shortest_path`/`descendants`/`louvain_communities`）；节点可用任意 hashable（直接挂 `symbol_id`），无 rustworkx 的整数索引映射负担 |
| Python stdlib（`collections.OrderedDict` + `threading.Lock` + `sys.getsizeof` 估算） | 3.14 | per `(repository, branch)` 图缓存的 LRU 逐出 + 并发保护 | 缓存条目少（个位数到几十个 repo 图）、逐出策略简单（LRU + commit sha 水位失效），引第三方 cache 库是过度设计；仓内已有同构先例（`node_check.py` 进程缓存、galaxy 文件缓存） |
| Semgrep CLI | 1.172.0（2026-07-28 发布；pip 包，LGPL-2.1-or-later） | MR diff 的 taint mode 安全门禁（买不是造，替代自研 PDG） | 唯一维护活跃、规则生态完整的开源 taint 引擎；`--baseline-commit` 原生支持 diff-aware 扫描；`--json` 结构化输出好接门禁 |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `networkx.algorithms.community.louvain_communities` | networkx 3.6.1 内置 | 社区发现（模块划分），社区落库后喂 LLM 生成模块摘要 | 传 `seed=<固定值>` 保证幂等（对齐本仓「路由幂等」纪律：同一图输入产同一分区，社区 ID 可复现） |
| `graphlib.TopologicalSorter`（stdlib） | 3.14 | 执行流正向追踪时的层级展开（如需要） | 仓内 v0.8.0 wave 分层已有使用先例，同构复用 |
| gopls | v0.23.0（2026-07 发布，BSD-3-Clause） | Go 符号抽取 LSP 后端（默认开启） | 现有 `go_check.py` 下界 v0.14 仍有效；镜像内 `go install golang.org/x/tools/gopls@latest` |
| @vue/language-server (volar) | v3.x（npm，MIT） | Vue/TS 符号抽取 LSP 后端（默认开启） | 现有 `node_check.py` 要求 Node ≥ 18（建议 22 LTS）；`npm i -g @vue/language-server`；tsdk 缺失时回落 volar 内置 typescript，可另装 `typescript` 提精度 |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `semgrep --validate` | 自定义 taint 规则 CI 校验 | 若沉淀本地规则文件（YAML），进 CI 防规则语法坏掉 |
| `pytest` 既有基线 | 图算法确定性测试 | 社区检测/impact 排序都要固定 seed + 稳定 tie-break（对齐 v0.19.0「先量化再比」纪律） |

## 五个问题的详细裁决

### 1. networkx vs rustworkx（10万–100万节点/边）

**结论：本里程碑用 networkx，不引 rustworkx。**

事实核查（HIGH confidence）：

- rustworkx 0.18.0（2026-06-18）**官方支持 Python 3.14**，且自 0.17.1 起用 Python Stable ABI（abi3）打 wheel，manylinux/macOS/Windows 全平台预编译，还发布了 3.14 free-threaded wheel——**wheel 可用性不是障碍**，无需本地 Rust 工具链。License 是 Apache-2.0，无合规问题。
- 性能：官方 JOSS 论文与 benchmark 称常见场景 3x–100x 提速（Dijkstra 1M 节点 ~85ms vs networkx ~4.5s），内存占用显著低于 networkx 的 per-object 开销。
- **关键短板：rustworkx 至今没有 Louvain/Leiden 社区检测**（Qiskit/rustworkx#1141 仍是 open issue，讨论中在等 petgraph 上游）。本里程碑恰恰需要社区检测 ⇒ 引入 rustworkx 也无法退役 networkx，结果是同一份图数据要在两套对象里各存一份。
- rustworkx 不是 drop-in：节点是整数索引，需要自己维护 `symbol_id ↔ index` 双向映射；API 按图类型显式分型（`digraph_*`）。

规模判断（MEDIUM confidence）：本仓单个 `(repository, branch)` 图的典型规模是 1万–20万符号节点 + 数十万边（`Symbol`/`CallEdge`/`ChunkEdge` 现状）。networkx 在此规模：

- **构图**：一次性成本，10万边约 1–3 秒、100万边约 10–30 秒——图缓存常驻内存后摊销为零，且构图发生在索引完成后的后台，不在请求路径。
- **查询**：反向 BFS（impact）与两点最短路（trace）是局部遍历，实际触达节点通常远小于全图，毫秒到百毫秒级；`louvain_communities` 在 10万边量级秒级完成，且属离线批处理（索引后跑一次落库）。
- **内存**：networkx 有向图 + 最小属性（只挂 id，正文留 SQL 反查）约 0.5–1 KB/边 ⇒ 100万边约 0.5–1 GB。**这是唯一真实风险点**，缓解手段：(a) 节点/边属性只存标量 id 不存对象；(b) LRU 上限按条目数（如 8 个图）+ 估算字节数双闸。

**升级触发条件（写进 adapter seam 注释）**：若生产出现单仓图 > 50 万边、或 impact 查询 p95 > 2s、或图缓存内存 > 2GB，先做「属性瘦身 + 邻接表预物化」，仍不够再评估 rustworkx——届时社区检测留 networkx（离线路径不敏感），只把 BFS/最短路热路径切 rustworkx。

### 2. 社区检测：networkx louvain vs leidenalg

**结论：`networkx.community.louvain_communities(G, seed=固定值)`，不引 leidenalg。**

事实核查（HIGH confidence）：

- networkx 3.6.1 的 `louvain_communities` 是**原生默认实现**（BSD-3-Clause），带 `seed`/`resolution`/`threshold` 参数。
- networkx 3.6 的 `leiden_communities` **没有默认实现**——文档明确「backend required」，目前唯一 backend 是 NVIDIA cugraph（GPU）。自托管 CPU 部署不可用。
- leidenalg 0.12.0（2026-05-24）打了 abi3 wheel（CPython ≥3.8 全平台），conda-forge 也有 cp314 构建——**技术上 Py3.14 可用**，但 leidenalg 是 **GPL-3.0**、其依赖 python-igraph 基于 igraph C 核心（GPL-2）。本仓是 **MIT license 且分发 Docker 镜像**（ghcr.io 预构建镜像），把 GPL 库打进分发物会给下游商用部署带来传染争议。
- 质量差异：Leiden 修复 Louvain 的「badly connected communities」问题、速度更快，这在**社区结构本身是最终产物**的学术场景重要；本里程碑社区只是 LLM 模块摘要的**粗分组输入**（摘要质量主要取决于 LLM 与提示词），Louvain 的分区质量完全够用。

工程纪律：`seed` 固定 + 社区成员按 `(symbol_id)` 排序后取 hash 作社区指纹，保证重跑幂等、落库可对账。

### 3. Semgrep 集成

**结论：独立二进制形态装 CLI（镜像构建期 `pip install semgrep==1.172.*` 到独立 venv 或 `uv tool install`），server 侧 subprocess 调用 + `--json` 解析。绝不把 semgrep 加进 `server/pyproject.toml`。**

事实核查（HIGH confidence，2026-08 现状）：

- **版本**：semgrep 1.172.0（2026-07-28），PyPI 包 `semgrep`，Python >=3.10，License **LGPL-2.1-or-later**（引擎）。周更节奏，锁 minor 即可。
- **为什么不进 server venv**：semgrep wheel 内嵌 OCaml 编译的 `semgrep-core` 二进制并携带自己的一批 Python 依赖 pin（click/rich/ruamel 等），与 server 的 90+ 依赖树合并是冲突温床；它只被 subprocess 调用，物理隔离（独立 venv / `uv tool` / 官方 docker image `semgrep/semgrep`）是标准做法。
- **taint 能力边界（设计门禁前必须认账）**：
  - Semgrep CE（Community Edition，免费开源）：`mode: taint` 规则可用，但**只做单函数内（intraprocedural）taint** + 单文件常量传播。
  - 跨函数（`--pro-intrafile`）与跨文件（`--pro` + 规则 `interfile: true`）taint 是 **Semgrep Code（付费 AppSec Platform）** 能力，需 `semgrep install-semgrep-pro`（专有二进制）+ 登录 token。
  - ⇒ **门禁的产品语义要按 CE 收敛**：「diff 内单函数 taint + 规则模式匹配」级别的安全检查，不承诺跨文件数据流追踪；配置面留 `SEMGREP_APP_TOKEN`（走既有 `ProviderCredential`/`SystemSetting` 加密存储约定，不走 env）作 Pro opt-in。
- **规则来源**：registry ruleset 推荐组合 `p/default`（平衡）+ 按语言补 `p/python` `p/golang` `p/typescript`；`p/security-audit` 偏审计（噪音更高），适合作可选严格档而非默认档。规则受 **Semgrep Rules License v1.0**：内部使用（含商用私有代码）免费无限制，仅当「把 registry 规则作为竞品服务出售」才触发限制——Friday AI 自托管场景安全，但因 Friday AI 本身是分发的产品，**建议默认在运行时按需拉取 registry（`--config p/...`）而不是把规则文件打包进镜像分发**，规避再分发争议；离线部署场景让用户自带规则目录。
- **diff 扫描推荐调用**：

  ```bash
  semgrep scan \
    --config p/default --config p/python --config p/golang \
    --baseline-commit "$(git merge-base <target_branch> HEAD)" \
    --json --metrics=off --timeout 30 --max-memory 4000
  ```

  注意：`--baseline-commit` 要求工作区是 git 目录、**无未暂存变更**、baseline hash 本地可达（浅克隆要 `fetch --deepen`）——门禁执行环境（编码任务容器 / server 本地镜像仓）需保证这三点。`semgrep ci` 是 AppSec Platform 配套命令，OSS 自托管场景用 `semgrep scan`。
  1.172.0 刚修了 baseline 扫描「规则失败时把整文件旧 finding 误报为新增」的 bug——**不要用更老的版本**。

### 4. 内存图缓存 LRU/TTL

**结论：零新增依赖，纯 stdlib。**（cachetools 不在 `uv.lock`，无需引入）

- 结构：`OrderedDict[(repo_id, branch), CachedGraph]` + `threading.Lock`；命中 `move_to_end`，超限 `popitem(last=False)`。
- **失效不是时间 TTL，是水位比对**：`CachedGraph` 记录构建时的 `last_indexed_commit_sha`，每次取用先对比仓库当前索引水位，不一致即重建——这与里程碑目标「挂 `last_indexed_commit_sha` 水位失效」一致，时间 TTL 反而会造成「没重索引也白白重建」或「重索引了还在用旧图」两头不讨好。可选加 `time.monotonic()` 兜底上限（如 24h）防水位字段异常时的极端 stale。
- `functools.lru_cache` 不适用：无法按 key 主动失效、无法容量按字节估算、装饰器形态与 async 入口（`sync_to_async` 包桥）不搭。
- 并发注意：图构建秒级–分钟级，锁内只做字典操作，构建放锁外 + per-key 构建中标记（防惊群重复构建）；构建线程走既有 `background_runner`/durable 约定并带 `initiated_by_user_id`。

### 5. volar/gopls 默认开启的运维前提

**结论：真正的前置是 `server/Dockerfile` 加运行时；代码侧探针与 fail-soft 回落已就绪，「默认开启」可以安全地实现为「kill-switch 默认翻开 + 探针失败自动回落 tree-sitter」。**

现状核查（读本仓代码，HIGH confidence）：

- `codegraph/lsp/node_check.py` 要求：`node` ≥ 18（建议 22 LTS）+ `vue-language-server` 在 PATH（`@vue/language-server` v3.x，npm 全局装）+ tsdk 三探针（缺失回落 volar 内置 typescript）。
- `codegraph/lsp/go_check.py` 要求：`gopls` ≥ v0.14（当前最新 v0.23.0，2026-07）+ **`go` ≥ 1.20 也必须在 PATH**——gopls 运行时要调 `go` 命令做包加载，光有 gopls 二进制不够。
- **当前 `server/Dockerfile`（`python:3.14-slim`）两样都没有** ⇒ 生产镜像里即使翻开 `VOLAR/GOPLS_BACKEND_ENABLED` 两个 kill-switch，探针必失败、全量回落 tree-sitter。「默认开启」在镜像不改的情况下是空话。

Dockerfile 增量（runtime stage）：

```dockerfile
# Node 22 LTS + volar（NodeSource 或 distro node；~180MB）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm i -g @vue/language-server typescript \
    && rm -rf /var/lib/apt/lists/*

# Go 工具链 + gopls（gopls 运行时依赖 go 命令；~330MB）
COPY --from=golang:1.25-bookworm /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"
RUN GOBIN=/usr/local/bin go install golang.org/x/tools/gopls@v0.23.0
```

运维注意（既有代码注释已声明）：volar 大插件链场景启动 60–90s、gopls 大仓 20–60s ⇒ 随默认开启同批把 `LSP_STARTUP_TIMEOUT_SECONDS=60` 写进 compose 默认 env；镜像体积预计 +400–550MB（Node ~180MB + Go 工具链 ~300MB + gopls ~50MB），发布说明要提。若体积敏感，备选方案是把 LSP 后端拆 sidecar 镜像——但那是架构改动，超出本里程碑「降低开启门槛」的范围，不推荐。

## Installation

```bash
# Python 侧：本里程碑零新增（networkx 3.6.1 已在 uv.lock）
# 如未来触发 rustworkx 升级条件：
# cd server && uv add "rustworkx>=0.18,<0.19"

# Semgrep：独立于 server venv（Dockerfile builder stage 或独立层）
python3 -m venv /opt/semgrep && /opt/semgrep/bin/pip install "semgrep==1.172.*" \
  && ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep
# （或 uv tool install "semgrep==1.172.*"）

# LSP 运行时（见上文 Dockerfile 增量）
npm i -g @vue/language-server typescript
go install golang.org/x/tools/gopls@v0.23.0
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| networkx（已有） | rustworkx 0.18.0 | 单仓图 > 50万边、impact p95 > 2s 或图缓存 > 2GB 且属性瘦身无效时，仅热路径（BFS/最短路）切换；社区检测仍留 networkx |
| `louvain_communities`(seed) | leidenalg 0.12.0 + python-igraph | 只有当社区质量本身成为用户可见产物且部署方接受 GPL 时；当前模块摘要场景不值得 |
| semgrep 独立 venv/binary | 官方 docker image `semgrep/semgrep` | 若门禁跑在编码任务容器外的独立 job 里，docker image 隔离更干净；但 server 进程内 subprocess 调本地二进制延迟更低 |
| stdlib OrderedDict LRU | cachetools `TTLCache`/`LRUCache` | 若未来缓存策略复杂化（多级、权重、per-entry TTL 混合）再考虑；现在引入是无谓依赖 |
| 镜像内置 Node/Go | LSP sidecar 容器 | k8s 大规模部署且镜像体积敏感时；需要新增跨容器 LSP 传输层，本里程碑不做 |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| leidenalg / python-igraph | GPL-3.0 / GPL-2 传染，本仓 MIT + 分发 Docker 镜像 | networkx `louvain_communities`（BSD） |
| networkx `leiden_communities` | 3.6 只有 dispatch 接口无默认实现，唯一 backend 是 cugraph（GPU） | 同上 |
| rustworkx（本里程碑） | 无社区检测（issue #1141 open），引入后仍需 networkx，双图对象双内存；性能瓶颈未被证实 | networkx + adapter seam + 明确升级触发条件 |
| graph-tool | 无 PyPI wheel，C++/boost 源码编译，Docker 构建成本爆炸 | networkx / rustworkx |
| semgrep 装进 server venv | 依赖 pin 冲突温床；semgrep 自带 OCaml core 二进制，本质是 CLI 工具不是库 | 独立 venv / `uv tool` / docker image + subprocess |
| semgrep join mode | 官方标注 experimental、不再积极维护 | CE taint mode（单函数）+ Pro opt-in |
| 自研 PDG/CFG 污点分析 | 里程碑显式 out of scope（买不是造） | Semgrep |
| `functools.lru_cache` 做图缓存 | 无法按 key 失效、无容量字节控制 | stdlib OrderedDict + 水位失效 |
| 时间 TTL 作为图缓存主失效机制 | 与索引水位脱节，两头不讨好 | `last_indexed_commit_sha` 水位比对（时间仅作兜底） |

## Stack Patterns by Variant

**If 部署方是离线/内网环境（拉不到 semgrep registry）：**
- 提供 `SEMGREP_RULES_DIR` 类设置指向本地规则目录（`--config <dir>`），门禁 fail-soft 降级为跳过并显式标注（对齐「降级必须可见」纪律）
- 因为 registry 拉取是运行时网络依赖，与本仓 fastembed 预置缓存同类问题

**If 用户购买了 Semgrep AppSec Platform：**
- `SEMGREP_APP_TOKEN` 经加密凭证存储注入，`semgrep install-semgrep-pro` 后门禁自动升级为跨函数 taint（`--pro-intrafile`）
- 门禁结果标注 engine 档位（ce / pro），报告可比

**If 生产图规模触发 rustworkx 升级条件：**
- 只替换 `GraphService` 内部热路径实现（BFS/最短路），对外 API 不变（这就是 adapter seam 的意义）
- `uv add "rustworkx>=0.18,<0.19"`（abi3 wheel，Py3.14 官方支持，无 Rust 工具链需求）

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| networkx 3.6.1 | Python 3.14 ✓ | 纯 Python wheel（`py3-none-any`），已在 `uv.lock` |
| rustworkx 0.18.0 | Python 3.14 ✓（官方声明 + abi3 wheel + free-threaded wheel） | 备选；Apache-2.0；`>=3.10` |
| semgrep 1.172.0 | Python >=3.10（含 3.14） | 独立安装，不与 server 依赖树合并，兼容性风险物理隔离 |
| leidenalg 0.12.0 | Python 3.14 ✓（abi3 wheel / conda-forge cp314） | 技术可用但 GPL-3.0，**license 否决** |
| gopls v0.23.0 | 需 `go` ≥ 1.20 在 PATH（仓内探针下界）；用 golang:1.25 工具链装 | BSD-3-Clause；`go_check.py` 宽松版本解析已兼容 |
| @vue/language-server 3.x | Node ≥ 18（建议 22 LTS） | `node_check.py` 下界 18；tsdk 缺失自动回落内置 typescript |

## Sources

- https://pypi.org/project/rustworkx/ + https://github.com/Qiskit/rustworkx/releases/tag/0.18.0 — 0.18.0（2026-06-18）官方支持 Py3.14、abi3 + free-threaded wheels（HIGH）
- https://www.rustworkx.org/release_notes.html — Stable ABI、Py3.10–3.14 测试范围（HIGH）
- https://github.com/Qiskit/rustworkx/issues/1141 — Louvain 仍为 open issue，rustworkx 无社区检测（HIGH）
- rustworkx JOSS paper (doi:10.21105/joss.03968) + https://www.rustworkx.org/benchmarks.html — 3x–100x 提速数字（MEDIUM，未本仓复现）
- https://networkx.org/documentation/stable/.../louvain_communities.html 与 .../leiden_communities.html — louvain 原生实现、leiden「backend required」（HIGH）
- https://pypi.org/project/leidenalg/ + https://github.com/vtraag/leidenalg — 0.12.0（2026-05-24）、GPL-3.0、abi3 wheel 矩阵（HIGH）
- https://pypi.org/project/semgrep/ + https://github.com/semgrep/semgrep/releases — 1.172.0（2026-07-28）、LGPL-2.1、baseline 扫描 bugfix（HIGH）
- https://semgrep.dev/docs/semgrep-pro-vs-oss + https://docs.semgrep.dev/writing-rules/data-flow/taint-mode/overview — CE 单函数 taint / Pro 跨函数跨文件边界、`--pro-intrafile`/`interfile: true`（HIGH）
- https://docs.semgrep.dev/faq/overview — Semgrep Rules License v1.0 边界（内部使用免费，出售竞品服务受限）（HIGH）
- https://docs.semgrep.dev/cli-reference + ci-environment-variables — `--baseline-commit` 语义与约束（git 目录、无 unstaged、hash 可达）（HIGH）
- https://go.dev/gopls/release/v0.23.0 + https://pkg.go.dev/golang.org/x/tools/gopls — gopls v0.23.0（2026-07）、BSD-3-Clause（HIGH）
- 本仓核实：`server/uv.lock`（networkx 3.6.1 在树、cachetools/igraph/rustworkx/semgrep 均不在）、`server/Dockerfile`（无 Node/Go）、`server/codegraph/lsp/node_check.py` / `go_check.py`（运行时下界与探针行为）、`LICENSE`（MIT）（HIGH）

---
*Stack research for: v0.22.0 代码智能图分析升级（对标 GitNexus）*
*Researched: 2026-08-09*
