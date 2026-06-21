---
title: 飞书集成
---

# 飞书集成

Friday 对飞书（Lark）的集成不只是发通知：项目空间、云文档、机器人卡片、回调处理和工作流节点全部打通。同时 Friday 不绑定飞书 —— 底层模型是「协作入口 + 工作流 + 代码智能 + Runner」，后续可以接入其他协作系统而不推翻主流程。

## 集成能力总览

| 集成面 | 已有能力 |
| --- | --- |
| 飞书项目 | 项目空间绑定、插件凭据、Webhook token、工作项详情、字段、关系、评论、状态流转和触发日志 |
| 飞书文档 | 识别文档链接，读取云文档，把飞书块转成 Markdown，也能把 Markdown 写回文档，支持表格、代码块和引用 |
| 飞书机器人 / IM | 发送文本和卡片、更新卡片、读取群聊历史、下载消息资源、检查或邀请机器人入群，处理群聊和私聊 |
| 飞书卡片回调 | 审批、方案确认、补充信息、代码审查、编码结果等卡片都有对应回调 |
| 工作流节点 | `feishu_event_trigger`、`fetch_work_item`、`wait_feishu_field`、`notify_feishu`、`fetch_group_chat`、`join_group_chat` 等节点可直接拖进工作流画布 |
| MCP / Agent 工具 | `get_feishu_work_item_context` 聚合工作项、关系、评论和文档；`create_feishu_technical_plan` 结合代码证据生成并写回方案 |

## 接入步骤

<FlowPipeline :steps="['创建自建应用', '配置事件回调', '在 Friday 中绑定', '授权检查']" />

### 1. 创建飞书企业自建应用

在[飞书开放平台](https://open.feishu.cn)创建企业自建应用，获取凭据：

| 凭据 | 获取位置 |
| --- | --- |
| App ID / App Secret | 应用详情 → 凭证与基础信息 |
| Encrypt Key | 事件订阅 → Encrypt Key |
| Verification Token | 事件订阅 → Verification Token |

### 2. 配置事件回调

把飞书应用的事件回调地址配置为：

```text
https://your-domain/api/feishu/webhook/
```

部署级校验开关（可选，见[环境变量参考](/deploy/configuration#飞书)）：`FEISHU_ENCRYPT_KEY`、`FEISHU_SIGNATURE_REQUIRED`。

### 3. 在 Friday 中绑定

在 Web 控制台的项目设置中绑定飞书项目空间、填入应用凭据，并按需配置文档目录、机器人与字段映射。应用凭据经 Fernet 加密存储在数据库中。

::: tip 获取飞书项目空间 ID
在飞书项目中打开目标空间，URL 中的标识即为空间 ID。例如 `https://project.feishu.cn/xxx/story/12345` 中的 `xxx`。
:::

### 4. 授权检查

确认飞书应用：

- 已被授权访问目标项目空间；
- 拥有目标字段的读写权限；
- 机器人已加入需要收发消息的群聊（也可由 `join_group_chat` 节点自动邀请）。

## 飞书事件触发器（专属端点）

`feishu_event_trigger` 是一个纯 Webhook 入口：**"何时触发"完全由飞书项目的自动化规则决定**，节点本身不再配置工作项类型、状态过滤、监听/排除空间等条件。

工作机制：

1. 在工作流画布上添加 `feishu_event_trigger` 节点并**保存工作流**，节点会获得一个专属端点：

   ```text
   https://your-domain/api/feishu/webhook/<token>/
   ```

   `<token>` 由服务端自动生成，可在节点配置面板中查看与复制。

2. 在飞书项目中新建自动化规则，配置触发器（例如「需求工作项状态由任意状态变更为 Sprint 计划」），并添加「Webhook」动作，URL 填上一步的专属端点地址。

3. 规则启用后，符合条件的事件会命中该端点并**直接触发对应工作流**，无需在 Friday 侧重复配置过滤条件。

::: tip 与旧版共享端点的关系
共享端点 `/api/feishu/webhook/`（无 token）仍然保留，用于向后兼容以及空间级副作用（工作项详情摄取、唤醒挂起的工作流等）。新建工作流推荐使用专属端点 URL。
:::

## 典型链路

<FlowPipeline :steps="['feishu_event_trigger', 'fetch_work_item', 'AI 技术方案写回飞书', 'wait_feishu_field 等待审核', 'AI 编码指派器', 'PR / MR 卡片回写']" />

各节点的具体配置项见[工作流指南](/guide/workflows)。

## 故障排查

| 现象 | 排查方向 |
| --- | --- |
| `飞书回填失败` / `FeishuAPIError` | 应用凭据是否正确；字段 Key 是否存在且有写入权限；应用是否被授权访问目标空间 |
| 事件不触发工作流 | 飞书自动化规则的 Webhook URL 是否填写为该工作流的专属端点（含 token）；规则是否已启用且触发条件命中；工作流是否已保存并启用；查看项目的触发日志 |
| 卡片按钮无响应 | 卡片回调地址配置；查看 `docker logs friday-server` 中的回调处理日志 |

## 下一步

<LinkCards>
  <LinkCard icon="🧩" title="工作流指南" desc="飞书相关节点的完整配置项" link="/guide/workflows" />
  <LinkCard icon="⚡" title="快速开始" desc="从部署到第一条工作流" link="/guide/quick-start" />
  <LinkCard icon="⚙️" title="环境变量参考" desc="FEISHU_ENCRYPT_KEY 等部署级配置" link="/deploy/configuration" />
</LinkCards>
