# Phase 58 Research: 飞书原生流式卡片（CardKit streaming）

**Researched:** 2026-06-17
**Requirements:** CARD-01
**Goal answered:** "要把这个 phase 规划好，我需要知道什么？"
**Status:** Ready for planning

---

## TL;DR（规划前必读的一句话）

Phase 58 = 在 `FeishuIMClient`/`FeishuIMService` 新增一组 **CardKit v1 原生流式封装**（创建卡片实体 → interactive 消息引用 card_id 下发 → 全量文本 content PUT 增量推送 → settle 关流），`FeishuBotService.process_message` 的**流式段**新接入 `TEXT_DELTA` 把正文逐步推进同一张 CardKit 卡片；**既有 thinking 卡 + PATCH update_card + build_answer_card 路径完整保留**作为「降级通道 + 全部非流式分支（澄清/图片错误/waiting/空答案）」的承载面，CardKit 任一步失败 → fail-soft 切回该既有路径，答案/引用/usage 不丢。

**四个核心实证（已 READ + 官方文档验证）：**

1. **TEXT_DELTA 在 bot（role=developer）路径稳定发射**（F-1）：`chat_runner.py:829` 在每个 text content block 发 `AgentEvent(TEXT_DELTA, {"text","model","session_id"})` → `orchestration/graph.py:464` `writer({"type","data"})` 转 custom 事件 → `send_message_stream._run_graph:1349` 透传给消费方。**唯一吞掉 TEXT_DELTA 的场景是 `blocking_marker_seen`（deep_analysis 派单 → waiting 路径，graph.py:460）**，而 waiting 路径 bot 现已单独处理（poll fallback），不影响新接入。`event.data["text"]` 形状确认。
2. **CardKit 是「全量文本」推送，不是 delta**（F-3）：`PUT .../elements/{element_id}/content` 的 `content` 字段是**新的全量文本**（旧文本是新文本前缀 → 末尾打字机增量；否则全量上屏无动画）。⇒ bot 须本地累积 `body_so_far`，每次推**完整串**，不能只推增量片段。
3. **CardKit v1 端点 / 协议全部确认**（F-2）：创建 `POST /open-apis/cardkit/v1/cards`（`type:"card_json"` + `data`=转义的 schema 2.0 JSON，`config.streaming_mode=true`、`update_multi=true`）→ 返回 `data.card_id`；下发用 `POST /im/v1/messages` `msg_type=interactive` `content={"type":"card","data":{"card_id":...}}`；增量 `PUT /open-apis/cardkit/v1/cards/{card_id}/elements/{element_id}/content`（`{content, sequence(严格递增,int 1..2^31-1), uuid?}`）；收尾 `PATCH /open-apis/cardkit/v1/cards/{card_id}/settings`（`settings`=含 `config.streaming_mode:false` 的转义 JSON，带 `sequence`）。
4. **手写 httpx 而非 lark-oapi SDK**（D-1）：`lark-oapi>=1.5.2` 确有 cardkit v1 SDK，但本仓 IM 全链路是手写 httpx（`FeishuIMClient`），SDK 仅用于 websocket（`feishu/websocket_client.py`）。新方法复用 `get_tenant_access_token` 缓存 + httpx + tenacity 重试基建，与既有风格一致、可控、可 mock httpx 单测 → **手写 httpx**。

→ 规划落点：`feishu_im.py` 新增 `create_card_entity` / `send_card_entity` / `stream_card_content` / `settle_card_stream`（+ `FeishuIMService` 委托）；`bot/service.py` 流式段接 `TEXT_DELTA`；新增 `bot_cards.py` 的 schema-2.0 流式卡构造器；四层守护测试。**绝不改** `send_card`/`update_card`（PATCH）签名。

---

## 1. 需求锚点（逐字对齐 ROADMAP / REQUIREMENTS / CONTEXT）

- **CARD-01**：飞书机器人对话回复改走原生 CardKit 流式卡片（增量更新，替代现有 PATCH 全量替换），流式体验顺滑、无明显闪烁/全量重绘。
- **ROADMAP Phase 58 Success Criteria**：
  1. 机器人对话回复经原生 CardKit 流式接口增量更新（替代 PATCH 全量替换）；
  2. 流式过程无明显闪烁/全量重绘，体验顺滑；
  3. 流式失败/不支持时优雅降级到既有路径，对话回复不丢失。
- **STATE 约束**：i18n 默认中文（卡片文案）；fail-soft（任何 CardKit 异常 try/except + 结构化 warning，绝不冒泡成「无回复/报错卡」除非真实处理错误）。
- **Out of Scope**（CONTEXT）：卡片交互组件/按钮回调、多卡片编排（v2 OPENX-03）；自动建群（Phase 59）；chat Web 前端流式（已有）；富 markdown/代码块分块渲染优化（deferred）；真实租户 E2E 顺滑观感（人工验收 deferred）。

---

## 2. 关键事实清单（READ + 官方文档实证，不是推断）

### F-1：TEXT_DELTA 在 bot（role=developer）路径稳定发射 —— 实证发射链

发射链三段全部 READ 确认：

```829:834:server/agents/chat_runner.py
                            yield AgentEvent(
                                type=TEXT_DELTA,
                                data=_inject_metadata(
                                    {"text": text}, self._config.model, self._config.session_id
                                ),
                            )
```

```459:464:server/orchestration/graph.py
            should_forward = True
            if blocking_marker_seen and event.type in {THINKING, TEXT_DELTA, MESSAGE_COMPLETE}:
                should_forward = False

            if should_forward:
                writer({"type": event.type, "data": event.data})
```

`send_message_stream._run_graph`（`conversation_service.py:1349-1358`）把 `chunk["type"]=="custom"` 的 `event_data` 重建为 `AgentEvent` 投 queue，消费循环（line 1389-1406）`yield event`。

- **`TEXT_DELTA.data` 形状 = `{"text": str, "model": str, "session_id": str}`**（`_inject_metadata` 注入 model/session_id；契约由 `test_langchain_runner_core.py:501` / `test_sse_contract_langchain.py:128` 锁定）。bot 只需读 `event.data["text"]`。
- **唯一不发 TEXT_DELTA 的场景**：`blocking_marker_seen=True`（deep_analysis 工具返回 `__blocking_task__` 标记 → graph.py:456-461 起抑制 THINKING/TEXT_DELTA/MESSAGE_COMPLETE）。此路径 graph 进入 `phase="waiting"`，bot 已有独立分支（poll `_poll_final_answer_from_conversation` + `build_background_analysis_card`，service.py:311-336）。⇒ **新接 TEXT_DELTA 不会与 waiting 冲突**：waiting 路径根本没有 TEXT_DELTA，自然走既有非流式分支。
- **parts 双轨（P-1 关键坑）**：`chat_runner.py:851-858` 在 TEXT_DELTA **之后**还发 `PART_DELTA`（同一段文本）。`events.py:25-30` 注释明示「双轨期与旧 text_delta 共存，不替代」。⇒ **bot 只消费 `TEXT_DELTA`，绝不同时消费 `PART_DELTA`**，否则正文翻倍。

### F-2：CardKit v1 端点 / 鉴权 / 限频（官方文档实证 2026）

| 步骤 | 方法 + URL | 关键 body / 返回 | 限频 / 约束 |
|------|-----------|-----------------|-------------|
| ① 创建实体 | `POST /open-apis/cardkit/v1/cards` | `{"type":"card_json","data":"<schema2.0 JSON 转义字符串>","uuid?":"..."}` → 返回 `data.card_id` | 1000/min & 50/s；`tenant_access_token`；scope `cardkit:card:write`；实体有效期 **14 天**；**一个实体仅能发送一次**；不支持 `update_multi:false` |
| ② 下发 | `POST /im/v1/messages?receive_id_type=chat_id` | `msg_type="interactive"`，`content=json.dumps({"type":"card","data":{"card_id":card_id}})` → 返回 `message_id` | 复用既有 `send_message` |
| ③ 增量推文本 | `PUT /open-apis/cardkit/v1/cards/{card_id}/elements/{element_id}/content` | `{"content":"<全量文本>","sequence":<int 严格递增>,"uuid?":"..."}` | **1000/min & 50/s**（但见 P-3：单卡片 10/s 上限）|
| ④ 收尾 settle | `PATCH /open-apis/cardkit/v1/cards/{card_id}/settings` | `{"settings":"{\"config\":{\"streaming_mode\":false,\"update_multi\":true}}","sequence":<递增>,"uuid?":"..."}` | 1000/min & 50/s |

补充端点（备选终态用，见 D-3）：全量更新卡片实体 `PUT /open-apis/cardkit/v1/cards/{card_id}`；更新组件属性/新增组件 `.../elements`。

### F-3：`content` 是「全量文本」语义 + 文本元素约束（官方实证）

- `content` = **新的全量文本内容**。「若旧文本为新文本前缀子串 → 末尾打字机增量；若前缀不同 → 全量直接上屏无动画」。⇒ bot 累积 `body_so_far += delta` 每次推完整串（始终前缀递增 → 始终打字机）。
- 仅支持对 **普通文本元素（`tag:plain_text`）或富文本组件（`tag:markdown`）**做流式；卡片须 **JSON 2.0 结构**（`schema:"2.0"`）；元素须带开发者自定义 `element_id`（1~20 字符）。
- `content` 长度 1~100000；卡片体积 ≤ 30KB（超限 error 200860）。含代码块需去前后空格否则渲染失败。
- 选 **markdown 富文本元素**（与既有 `_markdown_block` 一致，支持 `**加粗**`/`---`/列表，能在单元素内表达 answer+引用+usage）。

### F-4：创建实体的 schema 2.0 流式卡 JSON（官方示例改写）

```json
{
  "schema": "2.0",
  "config": {
    "streaming_mode": true,
    "update_multi": true,
    "streaming_config": {
      "print_frequency_ms": {"default": 70, "android": 70, "ios": 70, "pc": 70},
      "print_step": {"default": 1, "android": 1, "ios": 1, "pc": 1},
      "print_strategy": "fast"
    }
  },
  "header": {"title": {"tag": "plain_text", "content": "Friday"}, "template": "blue"},
  "body": {"elements": [{"tag": "markdown", "content": "思考中...", "element_id": "md_body"}]}
}
```

创建时 `data` 须把上面 JSON **去注释、压缩、转义为字符串**（`json.dumps(card, ensure_ascii=False)`，与既有 `send_message` 一致）。

### F-5：CardKit 错误码（降级判定依据，官方实证）

| HTTP | code | 含义 | 降级动作 |
|------|------|------|---------|
| 400 | 99991672 / 权限类 | 租户未开通 cardkit / 无 `cardkit:card:write` scope（create 阶段） | **环境不支持 → 整段走既有 PATCH 路径** |
| 400 | 200740 | 卡片实体不存在 | 切既有路径 |
| 400 | 200750 | 实体已过期（>14 天） | 切既有路径 |
| 400 | 200850 | 流式更新超时自动关闭 | 重开 streaming_mode 或切既有路径 |
| 400 | 300309 | 流式模式为关闭状态 | 切既有路径 |
| 400 | 300317 | sequence 未严格递增 | **代码 bug 信号**（见 P-2）；切既有路径兜底 |
| 400 | 200770 | UUID 冲突 | 幂等重放命中，可忽略 |
| 400 | 200860 / 300302 | 卡片超 30KB / update_multi=false | 切既有路径 |

判定准则：**任一 CardKit API `code!=0` 或抛异常 → 结构化 warning + 设 `cardkit` 失效标记 + 走降级**（不区分具体 code，统一 fail-soft；code 仅用于日志诊断）。

### F-6：lark-oapi 现状（实证）

- `lark-oapi>=1.5.2` 在依赖（`pyproject.toml:25` / `uv.lock`），含 cardkit v1 SDK（`CreateCardRequest` / `ContentCardElementRequest` 等 builder）。
- 但本仓 **IM 全部手写 httpx**（`FeishuIMClient`：token 缓存 + `send_message`/`send_card`/`update_card`/`get_chat_history` + tenacity）。lark-oapi 仅用于 `feishu/websocket_client.py`（长连接事件）+ `run_feishu_client.py`。
- ⇒ 见 D-1：手写 httpx，复用既有基建，单测 mock httpx（与 `test_feishu_*` 范式一致）。

### F-7：既有 bot 流式段坐标（READ，本 phase 主改点）

`bot/service.py:259-376`：
- 立即 `send_card(build_thinking_card())` → `thinking_card_id`（line 129，**在 try 外，所有分支共用**）。
- 流式循环（line 270-300）：`TOOL_USE_START` → `update_card(thinking_card_id, build_streaming_card(tool_names))`（PATCH 全量替换）；`PHASE_TRANSITION` 收 phase/run_id/session_id/task_count；`MESSAGE_COMPLETE` 收 final_answer/usage/cost。**TEXT_DELTA 完全未消费**。
- 收尾：`extract_reference_summaries(session_id)` → `build_answer_card(...)` → `_replace_card(thinking_card_id → answer_card)`（line 362-376）。
- `_replace_card`（line 583-604）：fail-soft `update_card` 失败 → `send_card` 兜底（**降级范式现成**）。
- 非流式分支（澄清 line 146-200 / 图片错误 248-257 / waiting 311-336 / 空答案 338-352 / 异常 385-419）全部基于 `thinking_card_id` + `_replace_card`/`send_card`。

---

## 3. 核心决策（已自主拍板，无人值守，无遗留待裁决）

### D-1：手写 httpx 封装 CardKit（不用 lark-oapi SDK）

新方法加入 `FeishuIMClient`，复用 `get_tenant_access_token()` + `httpx.AsyncClient` + `data.get("code")==0` 判定 + structlog + tenacity（rate-limit 重试），与 `send_card`/`get_chat_history` 同构。**理由**：① 全仓 IM 手写 httpx，引入 SDK 调用风格割裂；② httpx mock 单测范式现成（`test_feishu_*`）；③ 端点/payload 已完全确认（F-2），SDK 不带来确定性收益。放置：直接进 `feishu_im.py`（与 `send_card`/`update_card` 同类）；不新建 `feishu_cardkit.py`（避免 token/client 基建重复）。

### D-2：降级架构 —— 既有路径完整保留为「承载面 + 降级通道」，CardKit 只增强 happy 正文流

**保留不动**：`build_thinking_card` 即时发卡（line 129）、所有非流式分支（澄清/图片错误/waiting/空答案/异常）、`_replace_card`/`update_card`/`send_card`/`build_answer_card`/`build_streaming_card` —— **零回归**。

**流式段改造**（仅 line 270-376）：
- 维护 `cardkit: _CardKitStream | None`（持 card_id / element_id / message_id / 单调 `sequence` 计数器），初始 `None`。
- **首个 `TEXT_DELTA` 到达时**惰性 `try: create_card_entity + send_card_entity` → 成功则 `cardkit=...`、`body=""`；失败 → `warning` + `cardkit=None`（标记失效，本轮不再尝试）。惰性创建的好处：纯工具/waiting/空答案轮次根本不产 TEXT_DELTA（F-1），不会平白多发一张流式卡。
- 每个 `TEXT_DELTA`：`body += event.data["text"]`；若 `cardkit` 有效 → 节流后 `try: stream_card_content(card_id, element_id, content=body, sequence=next())`；`except` → warning + `cardkit=None`（降级，本轮后续不再推）。
- `TOOL_USE_START`：**保持既有** `update_card(thinking_card_id, build_streaming_card(tool_names))`（PATCH，工具进度留在 thinking 卡）——见 D-4。
- `MESSAGE_COMPLETE` 收尾：
  - **CardKit 成功且有正文** → `try`: 最后一次 `stream_card_content(content=最终正文+引用+usage 的 markdown)` + `settle_card_stream`（streaming_mode=false）；并把 thinking 卡 `_replace_card` 成 `build_streaming_card`/精简态收口（避免「思考中」悬挂）。`except` → 降级（下条）。
  - **CardKit 不可用 / 收尾失败 / 无正文** → 完全走既有：`build_answer_card(...)` + `_replace_card(thinking_card_id → answer_card)`（**答案/引用/usage 不丢，Q6 推荐路径作为降级兜底**）。

**不变式**：无论 CardKit 是否启用，结束时恒有一条卡片承载最终答案（CardKit 流式卡 或 thinking→answer 卡）。`build_answer_card` 仍是降级与所有非流式分支的最终答案构造器，**逐字复用**。

### D-3：终态定版 —— 最终正文 content PUT（answer+引用+usage 单 markdown）+ settle，不依赖「全量更新实体」

CardKit 成功路径的终态用 **content PUT 推「最终完整 markdown」**（复用 `bot_cards` 的 `_reference_lines` + usage 行逻辑拼成单串：`**回答**\n{answer}\n\n---\n**已参考上下文**\n{refs}\n\n---\n💰 ...`），再 `settle`（streaming_mode=false）。**理由**：① content PUT 形状已 100% 确认（F-3），「全量更新卡片实体 PUT /cards/{card_id}」的 body 形状文档未逐字确认（避免不确定性，见 P-7）；② 单 markdown 元素即可表达 answer/引用/usage（`---` 渲染为 hr），无需 JSON 2.0 版 answer 卡构造器；③ 最小新增面。**备选**（planner 可选，非必需）：`PUT /cards/{card_id}` 全量替换为结构化 2.0 卡——表达力更强但需新 builder + 验证 body 形状，**默认不采用**。

### D-4：工具进度留在 thinking 卡（不并入 CardKit 流式卡的多元素）

`TOOL_USE_START` 进度继续走既有 `update_card(thinking_card_id, build_streaming_card)`（PATCH），**不**在 CardKit 卡内做多元素增量。**理由**：① CardKit content 流式按**单文本元素**（F-3）；多元素增量需 新增组件/更新组件 API + 额外 sequence 协同，复杂度与回归面陡增；② 现状工具进度在 thinking 卡已稳定（`test_tool_use_updates_streaming_card`），保留即零回归；③ UX 上「trace 卡（工具）+ 流式答案卡（正文）」分离清晰，类比 thinking/answer 分块。⇒ **答 Q5：保留前言（thinking 卡工具进度），不并入流式卡。** 不丢「正在调用 X 工具」可见性。

### D-5：sequence 单调计数器 + 推送节流

- `sequence`：`_CardKitStream` 内 `int` 计数器，**每次 CardKit 写操作（content PUT 与 settle PATCH 共享同一计数器）调用前 `+1`**（起始 1）。严格递增覆盖该卡所有 OpenAPI 写（F-2 ④ settle 也吃 sequence）。
- 节流：合并短 delta 减少 QPS。推荐 **时间阈值 ~250–300ms** 或 **累计字符阈值**（取先到者）触发一次 content PUT；首个 delta 与 `MESSAGE_COMPLETE` 终态强制 flush（保证起末不漏）。理由见 P-3（单卡片 10/s 上限）。节流阈值由 execute 定（the agent's Discretion），默认 300ms。

### D-6：`uuid` 幂等

每次 content PUT / settle 带 `uuid=uuid.uuid4().hex`（重试同批次防重复，对齐 tenacity 重试语义；200770 UUID 冲突视为已生效可忽略）。create 可选带 uuid。

### D-7：SystemSetting 开关 —— 不新增（纯靠 fail-soft）

不加 `SettingKeys` 原生流式开关。**理由**：fail-soft 降级已覆盖「环境不支持」（租户未开通 → create 报权限错 → 自动切既有路径，F-5）；加开关增 ProviderCredential/SystemSetting 面与测试面，收益低。⇒ 答 CONTEXT 末项：**不加开关**。（若 execute 阶段发现需手动 kill-switch，可低成本补，但非本 phase 必需。）

---

## 4. 推荐改动落点（给 plan 的最小可执行清单）

1. **`server/services/feishu_im.py`（新增方法，不改既有签名）**：
   - `FeishuIMClient.create_card_entity(card_json_2_0: dict, *, uuid: str = "") -> str`（POST `/cardkit/v1/cards`，body `{type:"card_json", data:json.dumps(card), uuid?}`，返回 `data.card_id`；`code!=0` 抛 `FeishuIMError`）。
   - `FeishuIMClient.send_card_entity(receive_id, receive_id_type, card_id) -> str`（复用 `send_message`，`msg_type="interactive"`，`content={"type":"card","data":{"card_id":card_id}}`，返回 message_id）。
   - `FeishuIMClient.stream_card_content(card_id, element_id, content, sequence, *, uuid="") -> bool`（PUT `.../elements/{element_id}/content`，body `{content, sequence, uuid?}`）。
   - `FeishuIMClient.settle_card_stream(card_id, sequence, *, uuid="") -> bool`（PATCH `.../settings`，`settings=json.dumps({"config":{"streaming_mode":False,"update_multi":True}})`）。
   - `FeishuIMService` 四个委托方法。
   - 复用 `get_tenant_access_token` / httpx / structlog；content PUT 可挂 tenacity rate-limit 重试（同 `send_card`，可选）。
2. **`server/feishu/cards/bot_cards.py`（新增 2.0 构造器 + 终态 markdown helper）**：
   - `build_streaming_card_v2(initial_text="思考中...", element_id="md_body") -> dict`（schema 2.0 + `config.streaming_mode/update_multi/streaming_config` + 单 markdown 元素带 element_id，见 F-4）。
   - `build_answer_markdown(answer, references, usage, matched_space_label) -> str`（复用 `_reference_lines` + usage 行，拼成终态单串；供 D-3 content PUT）。**不改** `build_answer_card`/`build_streaming_card`。
3. **`server/feishu/bot/service.py`（仅流式段 line 259-376）**：按 D-2/D-3/D-5 接 `TEXT_DELTA`；引入轻量 dataclass `_CardKitStream`（card_id/element_id/message_id/sequence）；惰性 create→stream→settle，全程 try/except fail-soft 切既有路径。`from agents.core.events import TEXT_DELTA` 新增 import。**非流式分支零改动。**
4. **零回归保护**：`send_card`/`update_card`/`build_answer_card`/`build_streaming_card`/`build_thinking_card`/所有非流式分支逐字不变；既有 `test_feishu_bot_*`/`test_feishu_bot_cards` 全绿。

---

## 5. Pitfalls / 约束（execute 时易踩）

- **P-1 parts 双轨**：`chat_runner` 在 TEXT_DELTA 后还发 `PART_DELTA`（同段文本，`events.py:25-30` 双轨共存不替代）。**bot 只消费 `TEXT_DELTA`**，绝不同时累积 `PART_DELTA`，否则正文翻倍。
- **P-2 sequence 严格递增（300317）**：同一卡片所有 OpenAPI 写（content PUT + settle PATCH）共享单调计数器，每次 `+1`。并发/重试乱序会触发 300317。tenacity 重试同一次推送须复用**同一 sequence + 同一 uuid**（幂等），不可重新 `+1`。
- **P-3 单卡片 10/s 上限 + 节流**：流式更新概览明示「单卡片实体 卡片/组件级 OpenAPI 频率上限 **10 次/秒**」（严于 content API 自身 50/s）。必须节流（D-5，~300ms/次 ≈ 3/s）合并 delta，否则高频 delta 触发限频 → 推送失败 → 降级。
- **P-4 content 是全量不是增量**（F-3）：每次推 `body_so_far` 完整串。误推单个 delta 会导致前缀不连续 → 全量上屏无打字机（闪烁，违背 Success Criteria 2）。
- **P-5 租户开通前提 = 降级信号**（F-5）：CardKit 需 `cardkit:card:write` scope + 租户开通；未开通 → create 阶段权限错。create 必须 try/except → fail-soft 切既有路径（**绝不冒泡成报错卡**）。零开通环境下行为 = 完全等同今天（零回归）。
- **P-6 实体一次性 + 14 天有效**（F-2）：一个 card_id 仅能 `send` 一次；每轮对话新建实体。不可跨轮复用 card_id。
- **P-7 终态不依赖未验证端点**：D-3 用 content PUT + settle（已确认）做终态；「全量更新实体 PUT /cards/{card_id}」body 形状文档未逐字确认 → **默认不用**；若 planner 选结构化 2.0 终态，须先 execute 阶段实测该端点 body。
- **P-8 client 7.20 以下兜底**：JSON 2.0 卡在 <7.20 客户端只显示标题 + 升级提示。这是飞书侧行为，本 phase 不处理；降级路径（既有 1.0 answer 卡）天然覆盖旧客户端 —— 故**保留既有 answer 卡路径有额外兼容价值**（D-2）。
- **P-9 fail-soft 边界**：CardKit 异常 try/except + 结构化 warning + 切既有路径；但**真实处理错误**（image error / empty answer / 异常分支）仍走既有 error 卡 —— 不能把这些误并入 CardKit 降级而吞掉。即「CardKit 失败」≠「处理失败」，两类分开。
- **P-10 token/httpx 复用**：CardKit 调用须经 `get_tenant_access_token()`（带缓存 + 提前 5min 刷新）；与创建实体的应用身份须一致（content API 限制：调用方 tenant_access_token 须 == 创建实体的应用，300311）。`FeishuIMClient` 单实例天然满足。
- **P-11 async / ruff 约定**：方法 `async def` + `httpx.AsyncClient`；line length 100、注释/docstring 中文、import 排序（ruff I）；与 `feishu_im.py` 既有风格一致。
- **P-12 卡片 ≤30KB（200860）**：超长答案的终态 markdown 须控量；`build_answer_card` 现有 references[:5] 截断逻辑同样适用于 D-3 终态串。

---

## 6. Validation Architecture（供 VALIDATION.md 生成 / nyquist 校验）

四层可验证测试架构，落 `server/tests/`（扩 `test_feishu_im.py` / `test_feishu_bot_pipeline.py`，新增可选 `test_feishu_cardkit.py`），mock 范式沿用既有 `test_feishu_bot_*`（`SimpleNamespace` im_service + `patch send_message_stream` + `AsyncMock`）。

### 6.1 CardKit httpx 封装纯形状单测（mock httpx）
- `create_card_entity` → 断言 POST `/cardkit/v1/cards`、body `type=card_json` + `data` 为转义 2.0 JSON（含 `streaming_mode:true`/`update_multi:true`/`element_id`）、返回 `card_id`。
- `send_card_entity` → 断言 `msg_type=interactive` + `content={"type":"card","data":{"card_id":...}}`。
- `stream_card_content` → 断言 PUT `.../elements/{element_id}/content`、body `{content(全量), sequence, uuid}`；**多次调用 sequence 严格递增**、`content` 为累积全量。
- `settle_card_stream` → 断言 PATCH `.../settings`、`settings` 含 `streaming_mode:false`、带 sequence。
- `code!=0` → 抛 `FeishuIMError`（降级判定基础）。
- **mock 点**：`patch httpx.AsyncClient`（或 respx），无 DB / 无 send_message_stream。

### 6.2 服务层流式集成测（mock send_message_stream 产 TEXT_DELTA + mock CardKit）
- fake stream 产 `TOOL_USE_START` + `TEXT_DELTA("你")` + `TEXT_DELTA("好")` + `MESSAGE_COMPLETE(final_answer="你好", usage)` → 断言：
  - 首个 TEXT_DELTA 触发 `create_card_entity` + `send_card_entity`（各 1 次）；
  - `stream_card_content` 按序被调，`content` 累积全量（"你"→"你好"），`sequence` 递增；
  - 终态 `stream_card_content`（answer+引用+usage markdown）+ `settle_card_stream` 各 1 次；
  - 工具进度仍 `update_card(thinking_card_id, ...)`（D-4 保留）；
  - 只消费 TEXT_DELTA，不因 PART_DELTA 翻倍（P-1，可在 fake stream 混入 PART_DELTA 断言被忽略）。
- **mock 点**：`patch send_message_stream`（async gen 产事件）+ im_service `SimpleNamespace` 带 `create_card_entity`/`send_card_entity`/`stream_card_content`/`settle_card_stream`=`AsyncMock`。

### 6.3 降级路径测（CardKit 失败 → 既有 PATCH 路径，答案不丢）
- create 抛错（模拟租户未开通，P-5）→ 断言：不再调 stream；最终走 `build_answer_card` + `_replace_card`（thinking_card_id），`result["status"]=="answered"`、引用/usage 在 answer 卡内。
- content PUT 中途抛错（P-3 限频）→ 断言 `cardkit` 标记失效、本轮后续不再推、终态降级出 answer 卡（答案不丢）。
- settle 抛错 → 断言终态仍以 answer 卡兜底。
- waiting / 空答案 / 图片错误分支注入 → 断言**完全走既有路径**（不创建 CardKit 实体，零新调用）。
- **mock 点**：`create_card_entity`=`AsyncMock(side_effect=FeishuIMError(...))` 等。

### 6.4 零回归 + 安全/fail-soft
- 既有 `test_feishu_bot_pipeline.py` / `test_feishu_bot_integration.py` / `test_feishu_bot_cards.py` 全绿（PATCH 路径、卡片构造、工具进度、p2p/群聊、welcome 不破）。
- `build_answer_card`/`build_streaming_card`/`build_thinking_card`/`send_card`/`update_card` 符号逐字不变（grep 断言或快照）。
- fail-soft：任一 CardKit 异常**不**冒泡成顶层 error / 不返回 `status=error`（除非真实处理错误，P-9）；结构化 warning 有 `card_id`/`code`。
- 真实飞书租户 E2E 顺滑观感 → **deferred**（人工验收，需真实应用，对齐既有飞书 E2E deferred 惯例）。

### Nyquist 采样覆盖矩阵（每个需求/约束 ≥1 可验证断言）
| 需求/约束 | 验证层 | 断言要点 |
|-----------|--------|----------|
| CARD-01（CardKit 增量替代 PATCH） | 6.2 | content PUT 按序累积全量、create+send 各 1 次 |
| Success #1（原生 CardKit 流式） | 6.1 + 6.2 | 端点/payload/sequence 形状正确 |
| Success #2（顺滑无重绘） | 6.1 + P-3/P-4 | content 全量前缀递增（打字机）、节流合并 |
| Success #3（降级不丢答案） | 6.3 | create/push/settle 失败 → answer 卡兜底 |
| TEXT_DELTA 实证（F-1） | 6.2 | 消费 `event.data["text"]` 累积 |
| parts 双轨（P-1） | 6.2 | 混入 PART_DELTA 不翻倍 |
| sequence 递增（P-2） | 6.1/6.2 | 多次写 sequence 严格 +1 |
| fail-soft（STATE 约束） | 6.3 + 6.4 | 异常不冒泡、warning 结构化 |
| 工具进度保留（D-4/Q5） | 6.2 | TOOL_USE_START 仍 update_card thinking 卡 |
| 零回归 | 6.4 | 既有 test_feishu_* 全绿、符号逐字不变 |
| i18n 中文 | 6.1/6.2 | 卡片文案/终态 markdown 为中文 |

---

## 7. Open Questions（plan 阶段已自主决断，无遗留）

- **OQ-1 SDK vs httpx** → D-1：手写 httpx（复用 FeishuIMClient 基建）。**已决。**
- **OQ-2 CardKit 端点/协议** → F-2/F-3/F-4：create POST /cards、send interactive card_id、content PUT 全量+sequence、settle PATCH settings。**已确认。**
- **OQ-3 终态定版方式** → D-3：content PUT 最终 markdown（answer+引用+usage）+ settle；全量更新实体为备选（默认不用，P-7）。**已决。**
- **OQ-4 工具进度并入 vs 前言** → D-4：保留 thinking 卡工具进度（不并入流式卡多元素）。**已决。**
- **OQ-5 降级架构** → D-2：既有路径为承载面 + 降级通道，CardKit 惰性增强 happy 正文流，全程 try/except fail-soft。**已决。**
- **OQ-6 SystemSetting 开关** → D-7：不加（纯 fail-soft）。**已决。**
- **OQ-7 TEXT_DELTA 接入坑** → P-1（parts 双轨只消费 TEXT_DELTA）+ F-1（waiting 路径不发 TEXT_DELTA，天然走既有分支）。**已厘清。**
- **OQ-8 节流/sequence/uuid 实现** → D-5/D-6（counter 共享、~300ms 节流、uuid 幂等）；阈值具体值 = the agent's Discretion。**已决（plan 可微调）。**

---

## RESEARCH COMPLETE

**核心发现**：Phase 58 在 `FeishuIMClient`/`FeishuIMService` 手写 httpx 新增 CardKit v1 四方法（create_card_entity / send_card_entity / stream_card_content / settle_card_stream，**端点/payload/sequence 已官方实证**：POST `/cardkit/v1/cards` 建实体→interactive `{"type":"card","data":{"card_id"}}` 下发→PUT `.../elements/{id}/content` **全量文本 + 严格递增 sequence** 增量→PATCH `.../settings` streaming_mode=false 收尾），`bot/service.py` 流式段新接 `TEXT_DELTA`（已实证 bot/developer 路径稳定发射 `event.data["text"]`，唯 deep_analysis waiting 路径不发、天然走既有分支；**parts 双轨只消费 TEXT_DELTA 防翻倍**）。降级架构（D-2）：既有 thinking 卡 + PATCH + `build_answer_card` 路径**完整保留**为承载面与降级通道，CardKit 惰性创建、全程 try/except fail-soft，任一步失败切回既有路径，答案/引用/usage 不丢（CARD-01 硬要求）；终态用 content PUT 最终 markdown + settle（D-3，避开未验证的全量更新实体端点）；工具进度留在 thinking 卡不并入流式卡（D-4）。给出 4 文件落点、12 条 pitfalls（parts 双轨/sequence 递增/单卡 10QPS 节流/content 全量非增量/租户开通降级/实体一次性/终态端点不确定/旧客户端兜底/fail-soft 边界/token 复用/30KB 限）、四层 Validation（httpx 形状单测 / 服务层流式集成 / 降级路径 / 零回归+安全），Nyquist 覆盖矩阵全需求映射。关键决策 D-1（httpx）/D-2（降级架构）/D-3（终态）/D-7（不加开关）均自主拍板，无遗留待裁决项；真实租户 E2E 顺滑观感记 deferred（人工验收）。
