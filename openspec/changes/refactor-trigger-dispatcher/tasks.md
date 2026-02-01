## 1. 基础设施
- 1.1 创建 `server/workflows/triggers/` 目录结构
- 1.2 实现 `context.py` - TriggerContext 数据类
- 1.3 实现 `registry.py` - TriggerHandlerRegistry 注册表
- 1.4 实现 `handlers/base.py` - TriggerHandler 基类
- 1.5 实现 `dispatcher.py` - TriggerDispatcher 调度器
## 2. Handler 实现
- 2.1 实现 `handlers/manual.py` - ManualHandler
- 2.2 实现 `handlers/webhook.py` - WebhookHandler
- 2.3 实现 `handlers/feishu.py` - FeishuEventHandler
## 3. 触发器节点重构
- 3.1 创建 `nodes/triggers/base.py` - BaseTriggerNode 基类
- 3.2 重构 `manual.py` 继承 BaseTriggerNode
- 3.3 重构 `webhook.py` 继承 BaseTriggerNode
- 3.4 重构 `feishu_event.py` 继承 BaseTriggerNode
## 4. View 层改造
- 4.1 改造 `WorkflowViewSet.execute` 使用 TriggerDispatcher
- 4.2 改造 `WebhookTriggerView` 使用 TriggerDispatcher
- 4.3 改造 `FeishuWebhookView` 使用 TriggerDispatcher
## 5. 清理与测试
- 5.1 抽取 `workflow_bridge` 审批逻辑到 `feishu/approval.py`
- 5.2 废弃 `workflow_bridge` 中已迁移的触发逻辑
- 5.3 编写单元测试
- 5.4 集成测试验证
