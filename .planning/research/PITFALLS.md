# Domain Pitfalls

**Domain:** 给既有多仓代码智能系统（tree-sitter 符号图 SQL 存储 + Qdrant RAG + MCP 工具面 + 增量索引/分支 overlay）叠加图分析能力（内存图服务 / impact / trace / detect_changes / 社区检测 + LLM 模块摘要 / 执行流 / rename_preview / Semgrep taint 门禁 / LSP 默认开启）
**Researched:** 2026-08-09
**Confidence:** HIGH（核心结论均有代码事实或官方文档/论文佐证；个别经验性阈值为 MEDIUM）

> 编号约定：本文的「Phase 建议」是功能相位名（roadmap 未定稿），映射到 v0.22.0 target features：**P-基座**=内存图服务、**P-impact**=impact/trace、**P-detect**=detect_changes、**P-社区**=社区检测+模块摘要、**P-执行流**=执行流追踪、**P-rename**=rename_preview、**P-semgrep**=Semgrep 门禁、**P-LSP**=解析精度提升。

## Critical Pitfalls

### Pitfall 1: 裸名调用边直接进 impact/trace ⇒ 假阳性灾难

**What goes wrong:**
`CallEdge` 的现实是：`callee_symbol` 可空、`callee_name` 是永远保留的裸名兜底（`server/codegraph/models.py` 明确注明「跨文件符号解析属 implementation+，留空待回填」）。如果 impact 反向 BFS 把「`callee_name == "save"`」这类裸名边当作真边扩散，任何一个叫 `save`/`get`/`run`/`handle` 的方法都会把全仓几百个同名符号拉进影响面。两跳之后影响面就是「整个仓库」，工具输出没人敢信，AI 编码代理拿着它做「改动安全吗」判断等于掷硬币。动态派发（duck typing）、装饰器/中间件间接调用（Django view decorator、DRF permission、workflow node registry 的 import 副作用注册）在 tree-sitter 层面根本没有边，构成对称的假阴性。

**Why it happens:**
tree-sitter 是语法级提取，没有类型信息；开发者急于让 impact「有结果」，把 `callee_name` 文本匹配当边用。而「结果很多」在 demo 里看起来像「功能很强」，上线后才发现精度崩了。

**How to avoid:**
1. **默认只走已解析边**：impact/trace 的图构建默认只吃 `callee_symbol IS NOT NULL` 的边 + `CrossRepoApiCall`（自带 `match_confidence` 1.0/0.7/0.4 分档，直接复用这套分层词表）。
2. **置信度是输出契约的一部分**：每个受影响节点带 `confidence: resolved | same_file_name_match | bare_name | cross_repo(0.4~1.0)`，MCP 返回按置信度分组渲染，让 LLM 消费方自己决定用哪一层——**不是二选一，是分层透出**。
3. **裸名边有条件启用**：`include_low_confidence=true` 参数显式开启，且裸名匹配至少加两道过滤：同文件/同目录优先、`callee_qualifier` 匹配（模型里已有该字段）、常见名黑名单（`get/set/run/save/init` 等出现次数超过阈值的名字直接不扩散）。
4. **控噪过度的对冲**：漏报靠「解析率指标」兜底——索引完成时统计 `callee_symbol` 回填率（per repo per language），低于阈值（如 Python <60%）时 impact 输出头部显式声明「本仓解析率 X%，结果偏保守」，而不是假装全知。rename_preview 的「图引用 + grep 兜底」模式就是这个思路的既有先例，impact 可给一个 `grep_supplement` 段但物理上与图结果分区。

**Warning signs:**
- impact 结果节点数随深度指数增长（depth=2 就 >500 节点）；
- 同一个查询里出现大量同名不同文件的目标；
- golden case（选 3-5 个人工核对过的符号）影响面对不上人工判断。

**Phase to address:** P-基座定边的准入词表与置信度枚举；P-impact 落分层输出 + golden case 回归测试。

---

### Pitfall 2: 多 worker 内存图缓存放大 + 构建风暴 + 失效窗口

**What goes wrong:**
三个叠加的坑：
1. **内存放大**：图缓存是进程内的（networkx 对象没法进 Redis）。helm 已支持 `gunicornWorkers>1`，每个 worker 各自缓存一份 `(repository, branch)` 图——10 万符号的仓一份图可能 500MB+（networkx 每节点/边是 Python dict，开销约为邻接表的 10-40 倍），4 worker 就是 4 份。生产 261 仓的实例上 LRU 容量若按「仓数」而不是「内存字节」算，OOM 是时间问题。
2. **构建风暴**：并发首查同一仓（AI 编码代理批量 impact、detect_changes 一次触发几十个符号查询）时无锁则 N 个请求各自从 DB 拉全量 Symbol/CallEdge 建图，DB 被打爆且内存瞬时 N 倍。
3. **不一致窗口**：增量索引提交后 `last_indexed_commit_sha` 前移，但已建好的图还是旧水位；若失效检查只在「建图时」做而不在「取图时」做，缓存命中路径会一直吐旧图。分支 overlay（`branch_name` 维度）再乘一倍缓存键空间。

**Why it happens:**
单 worker dev 环境下一切正常，问题只在多 worker/大仓/并发下爆发；networkx 的内存开销远超直觉；「按 mtime 失效」的直觉方案在增量索引这种异步写入面前有竞态。

**How to avoid:**
1. **按字节做 LRU**，不按条目数：建图后 `sys.getsizeof` 级估算（节点数 × 经验系数）计入预算，预算 env 可调（默认如 2GB/worker）；超预算逐出最久未用。超大仓（symbol 数超阈值）直接不进缓存、走「每查询按需子图」降级路径（从查询符号出发按深度限界拉边，DB 索引 `repository, callee_symbol` 已在）。
2. **single-flight 建图锁**：进程内 per-key asyncio lock（或线程锁，取决于建图跑在 `sync_to_async` 还是线程），首个请求建图、其余等待；跨 worker 不做分布式锁（代价大于收益，最坏是 worker 数份重复构建，可接受）。
3. **取图时校验水位**：每次命中缓存都比对 `Repository.last_indexed_commit_sha`（一次轻量 DB 读或短 TTL 本地缓存），不一致即丢弃重建。这正是既有 `GALAXY_CACHE` 的「数据签名失效」模式（`settings.py:858-861`），直接沿用同一套约定并同样留 `*_CACHE_ENABLED=False` 逃生舱。
4. **观测**：`gauge` 上报缓存条目数/估算字节/命中率/构建耗时（`category=sampling`），构建事件 `graph_build_started/completed/failed + duration_ms`（`category=caller` 首查归因用户）。

**Warning signs:**
- server 容器 RSS 在图工具上线后阶梯式上涨不回落；
- 日志出现同一 repo 短时间多条 `graph_build_started`；
- impact 结果引用了已被增量索引删除的符号（stale 图证据）。

**Phase to address:** P-基座（这是地基相位的核心验收项：字节 LRU + single-flight + 水位校验 + 大仓降级四件套必须同相位落齐，后续所有图工具都踩在它上面）。

---

### Pitfall 3: 社区检测结果漂移 ⇒ 模块摘要反复重生成、LLM 成本失控

**What goes wrong:**
Louvain/Leiden 都是随机贪心启发式，同一张图两次运行可产出不同划分；networkx 的 `louvain_communities` 甚至有「seed 相同但节点插入顺序不同结果就不同」的已证实行为（networkx issue #6655，官方以 wontfix 关闭）。如果每次重建索引都重跑社区检测并对「变了的社区」重生成 LLM 摘要，一个没实质变化的仓每晚重索引都会触发几十个模块摘要重生成——LLM 成本线性失血，且下游 RepoRouter 消费的模块描述天天变，路由稳定性（v0.19.0 拿命换来的幂等纪律）被上游污染。孤立节点/不连通子图是第二个坑：代码图天然有大量孤立符号（未被调用的工具函数、入口脚本），直接跑算法会产出上百个单节点「社区」，LLM 摘要生成会对着一个函数写一段废话。

**Why it happens:**
社区检测在论文/demo 里都是「一张图跑一次」，没人告诉你生产里是「同一张图每天重跑」的稳定性问题；单节点社区在小图 demo 里不出现。

**How to avoid:**
1. **算法选型**：用 Leiden（`leidenalg` 或 igraph）+ 固定 seed + 固定节点排序（按 symbol UUID 排序后建图），Leiden 在同 seed 下确定性且保证社区连通（Traag 2019）；若留在 networkx Louvain，必须自己做节点排序 + seed，且接受仍可能漂移。
2. **稳定性护栏**：新旧划分做相似度对账（ARI 或按社区成员 Jaccard 匹配），**只有成员集变化超过阈值（如 Jaccard < 0.8）的社区才重生成摘要**；未变社区沿用旧摘要（社区落库时带 `member_fingerprint = hash(sorted(symbol_ids))`，指纹不变直接跳过 LLM）。
3. **预处理**：只对「最大弱连通分量 + 规模 ≥ N（如 5 个符号）的分量」跑社区检测；孤立节点归入所在目录的兜底社区或标 `unclustered`，绝不给单节点社区发 LLM 摘要。
4. **成本闸门**：模块摘要生成走批量 + 每仓每次重建的摘要生成条数上限（env 可调），赋独立 `call_source` 便于在 `ModelUsageRecord` 里单独看成本曲线。

**Warning signs:**
- `ModelUsageRecord` 里模块摘要 call_source 的 token 曲线与索引频率同形；
- 同一仓两次重建后社区数量/命名大幅变动；
- 社区列表里出现大量 size=1 的社区。

**Phase to address:** P-社区（指纹跳过 + 稳定性对账是该相位的需求级验收，不是优化项）；算法选型在 P-社区开工前的 research 定夺。

---

### Pitfall 4: 执行流/impact 遍历爆炸——递归环、扇出、async 断链

**What goes wrong:**
以 `Endpoint` 为入口正向展开调用链：递归/相互递归成环则 naive DFS 不终止；一个 Django view 调 service 层再进 ORM/工具函数，扇出很快到几万节点（尤其裸名边混入时）；`async` 任务派发（durable queue、`background_runner`、channels consumer、workflow 节点 dispatch）在静态调用图上是断的——`aemit`/`sync_to_async`/信号/回调处链路中断，执行流画一半，用户以为链路只有这么长，比不画更误导。

**Why it happens:**
图遍历的终止条件、预算控制是「第二天才想起来」的需求；异步断链是静态分析的原理性极限，但产品呈现上不标注就成了隐性谎言。

**How to avoid:**
1. **三重预算硬上限**：max_depth（默认 6-8）、max_nodes（默认 500）、max_fanout_per_node（如 50，超过则截断并标 `truncated: fanout`）；visited set 防环（环检测到时在输出里显式标 `cycle` 而非静默跳过——递归本身是有价值的信息）。
2. **结果分页/摘要化**：MCP 工具返回超预算时给「截断说明 + 按置信度/深度取 top-N」，绝不吐几万节点撑爆 LLM 上下文。
3. **断链显式标注**：识别已知断链模式（`sync_to_async`、`defer_task`、`.delay(`、channel `group_send`、workflow node dispatch）在链路末端标 `boundary: async_dispatch`，让消费方知道「这里之后是另一个执行域」，而不是链路终点。第一版不必跨过边界，标出来就赢了。
4. **Process 模型存摘要不存全图**：落库的执行流存「入口 + 主干路径 + 统计」，不存全展开节点集（否则大仓一个 endpoint 一行几 MB JSON）。

**Warning signs:**
- 执行流查询 p99 耗时随仓库大小超线性增长；
- 单条 Process 记录 JSON 超过几百 KB；
- 用户反馈「这个接口明明会发任务/推 WS，执行流里没有」。

**Phase to address:** P-执行流（预算与环处理），断链标注词表可在 P-impact 先定（impact 反向遍历同样需要）。

---

### Pitfall 5: detect_changes 行号错位与 diff 噪声

**What goes wrong:**
detect_changes = git diff 行区间 × Symbol 行区间求交。三个错位源：
1. **快照错位**：Symbol 的行号来自 `last_indexed_commit_sha` 时刻，而 diff 若以工作树/MR HEAD 计算，两个 commit 之间的无关提交早已把行号推移——交出来的符号根本不是改的那个。
2. **重命名文件**：git 默认把 rename 输出成 delete+add，旧路径符号全部命中「被删」、新路径零符号命中（索引里还没有新路径），一次 rename 误报满屏。
3. **格式化大 diff**：一次 prettier/ruff format 改动 200 个文件，逐符号 impact 批量展开后输出淹没真实变更，且触发 Pitfall 2 的构建风暴（几十个仓的图同时首建）。

**How to avoid:**
1. **diff 锚定索引水位**：强制 `git diff <last_indexed_commit_sha>...<target>` 做基线（v0.6.0 「MR diff commit 锚定 + 不假设 master」已是同款纪律）；若 `last_indexed_commit_sha` 落后 target 太多（如 >200 commits），先声明 stale 并建议触发增量索引，而不是硬算。
2. **rename 检测开启**：`git diff -M`（或 GitPython `find_renames`），rename 对按「旧路径符号 → 新路径」映射而非 delete+add 两次告警。
3. **噪声压制**：diff hunk 只有空白/import 顺序变化的（可用启发式：strip 后相同）降级为 `formatting_only`；单次 detect_changes 受影响符号数超过阈值（如 100）时切换为「文件级摘要 + 明确说明未逐符号展开」，不做批量 impact。
4. **接入点顺序**：先接「编码任务提交前自查」（容器内、有明确 base commit），后接「MR 描述生成」（异步、可容忍慢），不要一开始就挂到同步 API 上。

**Warning signs:**
- detect_changes 报告的符号行号与当前文件对不上；
- rename PR 的报告里同一逻辑符号同时出现在「删除」列表且新文件无匹配；
- 一次 format commit 触发的 impact 调用数量激增（观测 `RequestMetric`）。

**Phase to address:** P-detect（锚定 + rename 是功能正确性，第一批落）；噪声压制阈值可 env 化后续调。

---

### Pitfall 6: Semgrep 门禁被自己杀死——误报疲劳、耗时阻塞、baseline 漂移

**What goes wrong:**
安全门禁的死法高度一致：初版全量规则 + 全仓扫描 + 硬阻断 ⇒ 误报淹没 + MR 等 10 分钟 ⇒ 两周内被开发者要求关掉 ⇒ 门禁名存实亡。具体机制：不做 diff-aware 时 Semgrep 会把存量历史问题全algia到每个 MR 头上；taint mode 规则在大文件上单规则默认 5s 超时（`SEMGREP_TIMEOUT`），规则多时扫描分钟级；自维护规则集没人认领后 rules 与框架版本脱节，误报率单调上升；baseline（比较基准）若取 target 分支 HEAD 而不是 merge-base，别人先合入的代码会算到你头上。

**How to avoid:**
1. **只扫 diff、只报增量**：`SEMGREP_BASELINE_COMMIT` 设为 merge-base（官方明确建议），只对「本 MR 新引入」的 finding 发声（Semgrep 官方 diff-aware 语义）。
2. **分级不硬断**：finding 分 `blocking`（高置信 taint 规则白名单，如 SQL 注入/命令注入的核心几条）与 `advisory`（其余全部只评论不拦）；第一个月全部 advisory 跑观察期，误报率有数据后再提级。这与本仓 AI 审查「超界是待人审不是失败」的既有决策（v0.20.0 Phase 114）同一哲学。
3. **异步不阻塞**：扫描挂在 MR 创建后的异步任务（durable queue 已有 `maintenance`/独立队列基建），结果回填 MR 评论/检查项，不在 PR 创建同步路径上等待；超时 fail-open + 显式标注「扫描未完成」（安全门禁 fail-open 是有意识的产品决策，需在方案里写明理由：阻塞交付的门禁会被整体关闭，净安全收益为负）。
4. **规则集治理**：起步用官方 registry 精选 pack（p/python、p/django 等）而非自写；自定义规则每条带 owner 与误报申诉出口（`nosemgrep` + 理由注释，接入审计）。

**Warning signs:**
- MR 上 Semgrep 评论条数中位数 >5；
- 开发者批量加 `nosemgrep` 无理由；
- 扫描 p50 耗时 >2min 或出现「等扫描才能合并」抱怨。

**Phase to address:** P-semgrep（diff-aware + advisory 起步 + 异步化是同相位必选项，不可拆）；blocking 白名单提级是相位交付后的运营动作。

---

### Pitfall 7: LSP 默认开启拖垮索引管线

**What goes wrong:**
本仓 settings 里已经写着教训：gopls 被回落 tree_sitter 的原因就是「冷启动慢」（`settings.py:838-842`），volar 大插件链场景启动 60-90s（`settings.py:902-904` advisory）。默认开启后：每仓索引多付 20-90s 冷启动；gopls 对大仓稳态内存数百 MB 且分析器（staticcheck 类）可到 GB 级（golang/go#45457）；LSP server 是子进程，索引任务异常退出时不清理就进程泄漏，几轮索引后容器里挂着一排僵尸 `gopls serve`；容器镜像若缺 Node（volar 需要）或 Go toolchain（gopls 需要 `go list`），启动直接失败——fail 方式若是抛异常而不是回落，整条索引管线崩。

**How to avoid:**
1. **fail-soft 回落是硬约束**：LSP 后端启动失败/超时/崩溃一律回落 TreeSitterBackend 并记 `lsp_backend_degraded` 事件（现有 kill-switch 机制在 `codegraph/apps.py::ready()`，保留并细化到 per-language 运行时降级，不只是启动期开关）。
2. **启动前探测**：索引 worker 启动时探测 `node --version`/`gopls version` 可用性，缺运行时的语言直接静默走 tree_sitter 并在仓库索引详情里透出「LSP 未启用：缺 X 运行时」——用户可见但不报错。
3. **进程生命周期收口**：LSP 子进程绑定索引任务生命周期（context manager / finally kill + `psutil` 兜底清扫孤儿），每次索引结束上报 `lsp_process_reaped` 计数；设 per-process 内存上限观测（gopls >1GB 自动写 debug zip 的行为可作为告警信号源）。
4. **默认开启分两步**：先把「开启门槛」降到 per-repo/per-language 设置 + 探测通过自动启用（本里程碑），全局默认开启等冷启动摊销（LSP 常驻 daemon 或跨索引复用 session）验证后再做——gopls 文件缓存使二次启动显著变快，值得让 mirror 目录稳定以吃到这个缓存。

**Warning signs:**
- 索引耗时 p50 在 LSP 开启后翻倍以上；
- 容器内 `ps` 出现多个无父 gopls/vue-language-server；
- server RSS 与并发索引数强相关地上涨。

**Phase to address:** P-LSP（探测 + fail-soft + 进程收口三件套）；建议 P-LSP 排在 P-基座之后、且不与 P-社区/P-执行流并行上线（同时引入两个内存大户会让 OOM 归因困难）。

---

### Pitfall 8: 图分析工具面越权与 exclusion 漏接

**What goes wrong:**
新增 8+ 个 MCP/对话工具，每个都是一条新的数据出口。两类事故：
1. **权限旁路**：图查询按 `repository_id` 直查 Symbol/CallEdge，跳过仓库可见性校验——现状 `RepositoryPermission` 本来就是「任意登录用户可读任意存在仓库」（PROJECT.md 已列为平台级欠债），图工具若再把跨仓 impact（穿 `CrossRepoApiCall` 边界）做出来，一个低权用户能沿边遍历读到他从未被授权仓库的符号名/文件路径/行号——比 RAG 泄漏更结构化。
2. **exclusion 漏接**：v0.5.0 的 fail-closed 纪律是「被排除文件六面不可见」，但图数据是索引期写入的——若排除规则在索引之后添加，Symbol/CallEdge 里还躺着被排除文件的符号；`purge_file` 清五面，图分析工具作为新读取面必须把 `is_excluded` 运行期拦截接上（`mcp_tools/views.py` 已有统一 matcher 入口模式可抄），否则 impact 结果会把已排除的敏感文件路径吐回给 LLM。另外高频图查询（AI 代理一次任务几百次 impact）若逐条 INFO 落 `RetrievalTrace`/系统日志，会刷爆日志表。

**How to avoid:**
1. **工具入口统一鉴权装饰**：所有图工具走与既有 MCP 工具同一鉴权/仓库解析入口（PAT fail-closed），跨仓遍历时对每个「穿出去」的仓库做同样校验，未授权仓在结果里整仓折叠为 `redacted_repository`（保留「有影响」的事实但不泄内容）——即便当前权限模型宽松，接口形状先按 fail-closed 设计，等仓库级 ACL 落地时零改动。
2. **exclusion 双保险**：读路径全部过 `is_excluded`（运行期 fail-closed，与 grep 工具同款）；同时把 Symbol/CallEdge/Endpoint 纳入 `purge_file` 的清理面（从五面变六面），补对账命令。
3. **日志纪律**：图查询归 `sampling` 类（高频内部步骤），只有工具级调用（一次 MCP invoke）记 `caller` 事件 + `RetrievalTrace`；BFS 内部逐节点绝不 INFO。`RetrievalTrace` 记「查询符号 + 结果计数 + 置信度分布」，不整体复制结果集。

**Warning signs:**
- 图工具响应里出现 exclusion 规则覆盖的路径（写一条回归测试常驻）；
- `RetrievalTrace`/SystemLogEntry 表增速在图工具上线后跳变；
- 跨仓 impact 返回了请求用户无仓库记录的 repo 名。

**Phase to address:** P-基座（鉴权/exclusion 拦截做进图服务读取层，让所有上层工具天然继承——这是「单一匹配器」纪律的直接延伸）；purge 六面扩展可单独小相位或并入 P-基座。

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 裸名边默认参与 impact | 结果「丰富」、demo 好看 | 精度崩塌、工具信任破产 | never（只能作显式 opt-in 分层） |
| 图缓存按条目数 LRU | 实现简单 | 大仓 OOM、多 worker 放大 | 仅单 worker dev；生产必须按字节 |
| 每次重建全量重跑社区+摘要 | 逻辑简单无状态 | LLM 成本失控、路由输入漂移 | never（指纹跳过是必需品） |
| detect_changes 用工作树 diff 不锚定索引水位 | 少一次 rev 解析 | 行号错位、符号误命中 | never |
| Semgrep 全量规则同步阻断 | 「安全感」 | 门禁两周内被关闭 | never（advisory 起步） |
| LSP 失败抛异常不回落 | 错误显眼好排查 | 一个缺 Node 的容器拖崩整条索引管线 | never（fail-soft + 可见降级标注） |
| 执行流存全展开节点集 | 查询时不用重算 | 单行 MB 级 JSON、表膨胀 | 仅节点数 < 阈值的小图 |
| 图工具各自写权限/exclusion 过滤 | 各相位可并行 | 必有一个漏接（六面纪律破口） | never（读取层统一收口） |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| networkx | 把全仓图当常驻对象随意复制（`subgraph().copy()` 链）| 视图（`subgraph` 不 copy）+ 按需子图；大仓不建全图 |
| networkx Louvain | 信任 `seed` 参数保证可复现 | 节点排序 + seed 仍可能漂移（issue #6655 wontfix）；生产用 Leiden 固定 seed |
| Semgrep CI | baseline 取 target HEAD | 取 merge-base（官方 `SEMGREP_BASELINE_COMMIT` 建议）；否则别人的合入算你头上 |
| Semgrep taint | 无超时预算跑全规则 | `SEMGREP_TIMEOUT` 显式设定 + 精选 pack；超时 fail-open 标注 |
| gopls | 当普通子进程即起即用 | 冷启动 20-60s + 首轮 workspace load 内存峰值；探测→超时→回落三段式，复用 mirror 目录吃文件缓存 |
| volar | 假设容器有 Node/tsdk | `node_check.discover_tsdk()`（已有）失败必须静默降级 tree_sitter |
| git diff | 默认参数处理 rename | `-M`/find_renames 开启，rename 对做符号映射 |
| MCP 工具面 | 新工具自带一套过滤逻辑 | 复用 `mcp_tools/views.py` 的统一 matcher 入口 + `RetrievalTrace` 约定 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 全仓图进程内缓存 × N worker | RSS 阶梯上涨不回落 | 字节预算 LRU + 大仓降级按需子图 | 单仓 symbol >10 万 或 worker ≥4 |
| 并发首查建图无锁 | DB 查询尖峰 + 内存瞬时数倍 | per-key single-flight | detect_changes 批量触发时（一次 MR 几十仓）|
| BFS 无预算 | p99 秒级→分钟级 | depth/nodes/fanout 三重上限 + 截断标注 | 裸名边混入后任何中型仓 |
| 社区检测在请求路径同步跑 | 图工具偶发超长响应 | 社区检测只在索引后异步任务跑，结果落库供查询 | 仓 >1 万符号 |
| 逐节点写 RetrievalTrace/INFO | 日志表增速跳变 | 工具级 caller 事件 + 内部 sampling/debug | AI 代理批量调用（单任务数百次查询）|
| LSP 每仓每次索引冷启动 | 索引时长翻倍 | 探测缓存 + mirror 目录稳定复用 LSP 文件缓存 | 仓数 >50 的夜间批量重索引 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| 跨仓 impact 穿边不复核目标仓权限 | 结构化泄漏未授权仓的符号/路径/行号 | 每穿一仓复核；未授权整仓折叠 `redacted_repository` |
| 图读取面不接 `is_excluded` | 已排除敏感文件路径经 impact 回流 LLM | 读取层统一 matcher 拦截 + 常驻回归测试 |
| Symbol/CallEdge 不进 purge 面 | 敏感清理后图里仍有残留 | `purge_file` 扩到六面 + 对账命令 |
| Semgrep finding 原文含密钥片段直接落库/回评 | taint 规则命中处代码片段可能含凭证 | finding snippet 过 `redact_secrets_in_text` 再落库/外发 |
| rename_preview 输出未过 exclusion | grep 兜底扫到排除文件 | grep 兜底走既有已拦截的 grep 工具路径，不另起裸 grep |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| impact 不带置信度一锅端 | 用户/LLM 无法区分真影响与同名噪声 | 按 resolved/bare_name/cross_repo 分组渲染 |
| 执行流断链处静默终止 | 「链路就这么长」的错误结论 | `boundary: async_dispatch` 显式标注 |
| detect_changes 对 format diff 满屏输出 | 真实变更被淹没 | formatting_only 降级 + 超阈值文件级摘要 |
| Semgrep 硬阻断无申诉出口 | 开发者绕过或要求关门禁 | advisory 起步 + nosemgrep 带理由 + 分级提级 |
| 图结果 stale 不声明 | 用户按旧图做决策 | 输出头部带 `as_of: <commit_sha>` 水位声明 |

## "Looks Done But Isn't" Checklist

- [ ] **impact/trace：** 常缺「解析率声明 + 置信度分层」——验证：对 golden 符号集核对影响面精度，输出含 confidence 与 as_of 字段
- [ ] **内存图服务：** 常缺「取图时水位校验」——验证：增量索引后立即查询，结果不含已删符号
- [ ] **社区摘要：** 常缺「指纹跳过」——验证：无变更重建索引两次，LLM 调用数为 0
- [ ] **执行流：** 常缺「环与截断标注」——验证：构造相互递归用例，输出含 cycle 标注且终止
- [ ] **detect_changes：** 常缺「rename 处理」——验证：纯 rename PR 不产生删除+新增双列表
- [ ] **Semgrep：** 常缺「异步化」——验证：扫描超时时 MR 创建不被阻塞且带「未完成」标注
- [ ] **LSP：** 常缺「孤儿进程清扫」——验证：kill 索引任务后容器内无残留 gopls/vue-language-server
- [ ] **全部图工具：** 常缺 exclusion 拦截——验证：排除规则覆盖文件出现在任何图工具输出即测试失败

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 假阳性灾难已上线 | MEDIUM | 加 confidence 字段默认过滤 bare_name（接口向后兼容加参不破坏）；补 golden 回归 |
| 图缓存 OOM | LOW | 逃生舱 env 关缓存走按需子图（照 GALAXY_CACHE_ENABLED 模式预留）；再按字节预算修 |
| 社区漂移已烧钱 | LOW | 立即上指纹跳过 + 每仓摘要条数上限；历史摘要不回滚 |
| Semgrep 门禁被关 | HIGH | 信任重建最贵：清零规则重新 advisory 观察期，用误报率数据逐条提级 |
| 图工具泄漏排除文件 | MEDIUM | 走 v0.5.0 敏感清理流程 purge + 补六面拦截 + 审计事件回查暴露范围 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 裸名边假阳性 | P-基座（边准入）+ P-impact（分层输出） | golden 符号集精度回归 + confidence 字段快照测试 |
| 缓存放大/风暴/不一致 | P-基座 | 并发首查压测单次建图；索引后即查无 stale；RSS 预算内 |
| 社区漂移/LLM 成本 | P-社区 | 无变更重建 LLM 调用数 0；ARI/Jaccard 对账日志 |
| 遍历爆炸/断链 | P-执行流（P-impact 先定断链词表） | 递归用例终止 + cycle 标注；max_nodes 截断测试 |
| detect_changes 错位 | P-detect | rename PR 用例；stale 水位声明用例 |
| Semgrep 门禁死亡螺旋 | P-semgrep | 异步化 + advisory 默认的配置断言；扫描超时 fail-open 用例 |
| LSP 拖垮索引 | P-LSP | 缺运行时容器索引成功且标注降级；孤儿进程清扫测试 |
| 越权/exclusion 漏接/日志刷爆 | P-基座（读取层收口） | 排除文件出现即败的常驻回归；跨仓 redacted 用例；日志分类抽查 |

## Sources

- 本仓代码事实（HIGH）：`server/codegraph/models.py`（CallEdge 裸名兜底/callee_symbol 可空/CrossRepoApiCall match_confidence 分档）、`server/friday/settings.py:837-930`（gopls 因冷启动慢已回落、volar 启动 60-90s advisory、GALAXY_CACHE 签名失效先例）、`server/mcp_tools/views.py`（统一 exclusion matcher + RetrievalTrace 约定）、`deploy/helm/friday/`（gunicornWorkers 多 worker 形态）、`.planning/PROJECT.md`（RepositoryPermission 欠债、v0.5.0 六面纪律、v0.19.0 路由幂等纪律）
- Traag, Waltman & van Eck, "From Louvain to Leiden: guaranteeing well-connected communities", Sci Rep 9, 5233 (2019)（HIGH — Louvain 最多 25% 社区连接不良/16% 不连通；Leiden 保证连通）
- networkx issue #6655 "Louvain is non-deterministic given seed"（HIGH — 官方 wontfix，节点顺序影响结果）；networkx `louvain_communities` 文档（seed 语义）
- Semgrep 官方文档：diff-aware scanning / `SEMGREP_BASELINE_COMMIT` merge-base 建议 / `SEMGREP_TIMEOUT` 默认每规则 5s / blocking vs monitor 分级（HIGH）
- Go 官方博客 "Scaling gopls for the growing Go ecosystem" + golang/go#45457、#72919（HIGH — gopls 内存特征、文件缓存二次启动加速、staticcheck 类分析器 GB 级内存）；gopls troubleshooting/daemon 文档（>1GB 自动 debug dump、共享 daemon 模式）
- 经验性阈值（MEDIUM，需相位内实测校准）：networkx 内存放大系数、depth/nodes/fanout 默认值、Jaccard 0.8、解析率 60%

---
*Pitfalls research for: v0.22.0 代码智能图分析升级（对标 GitNexus）*
*Researched: 2026-08-09*
