# Design: 合并工作项触发日志
## Context
当前系统处理飞书 Webhook 事件时，会产生两种日志：
1. `WebhookLog` - 记录原始 Webhook 请求
2. `WorkItemLog` - 记录从飞书 API 获取的工作项详情
用户反馈在排查问题时需要在两个日志列表间切换，体验不佳。
## Goals / Non-Goals
**Goals:**
- 统一日志模型，将 Webhook 请求和工作项详情合并为「触发工作项日志」
- 前端提供良好的日志查看体验，支持 JSON 语法高亮
- 突出展示关键业务字段（需求文档链接、需求描述、技术方案文档链接）
**Non-Goals:**
- 不删除现有的 WebhookLog 和 WorkItemLog 模型（保持向后兼容）
- 不修改现有 API（新增 API）
## Decisions
### Decision 1: 新建 TriggerLog 模型而非合并现有模型
**选择:** 创建新的 `TriggerLog` 模型
**理由:**
- 保持向后兼容，不影响现有功能
- 清晰的职责划分：TriggerLog 专门记录「触发事件」的完整链路
- 未来可以独立演进
**替代方案:**
- 在 WebhookLog 中添加 work_item_response 字段 - 侵入性修改，耦合度高
- 使用外键关联 - 查询复杂，前端处理繁琐
### Decision 2: 使用 shiki 进行 JSON 语法高亮
**选择:** 使用 shiki 库
**理由:**
- 用户明确要求使用 shiki
- shiki 基于 VS Code 语法高亮引擎，效果优秀
- 支持多种主题，与现有 UI 风格匹配
**替代方案:**
- Prism.js - 更轻量但效果略差
- 原生 `<pre>` - 无高亮，体验差
### Decision 3: 原始数据懒加载
**选择:** 原始 JSON 数据通过独立 API 获取
**理由:**
- 原始数据体积较大（可能 10KB+）
- 列表页不需要原始数据
- 详情页默认折叠，展开时再加载
**API 设计:**
```
GET /api/logs/triggers/{id} # 返回摘要信息
GET /api/logs/triggers/{id}/raw # 返回完整原始 JSON
```
## Data Model
### TriggerLog 模型
```python
class TriggerLog(models.Model):
 # 基础信息
 created_at = models.DateTimeField(auto_now_add=True)
 project = models.ForeignKey(Project, on_delete=models.CASCADE)
 # Webhook 信息
 event_uuid = models.CharField(max_length=255, unique=True)
 event_type = models.CharField(max_length=100)
 webhook_raw_request = models.TextField # 原始 Webhook JSON
 # 工作项信息
 work_item_id = models.CharField(max_length=50)
 work_item_type = models.CharField(max_length=50)
 work_item_name = models.CharField(max_length=500)
 work_item_raw_response = models.TextField # 原始 API 响应 JSON
 # 提取的关键字段（便于列表展示和搜索）
 prd_url = models.URLField(blank=True) # field_bcff9b
 description = models.TextField(blank=True) # description
 tech_doc_url = models.URLField(blank=True) # field_3f6667
 # 状态
 status = models.CharField(max_length=20) # accepted, error, etc.
 error_message = models.TextField(blank=True)
```
## TypeScript Types
```typescript
/** 工作项字段的通用类型 */
interface WorkItemField {
 field_key: string;
 field_value: unknown;
 field_type_key: string;
 field_alias: string;
 help_description?: string;
}
/** 关键字段常量 */
const KEY_FIELDS = {
 /** 需求文档链接 */
 PRD_URL: 'field_bcff9b',
 /** 需求描述 */
 DESCRIPTION: 'description',
 /** 技术方案文档链接 */
 TECH_DOC_URL: 'field_3f6667',
} as const;
/** 触发日志列表项 */
interface TriggerLog {
 id: number;
 created_at: string;
 project_id: number;
 project_name: string;
 event_type: string;
 work_item_id: string;
 work_item_name: string;
 status: 'accepted' | 'error' | 'ignored';
 // 关键字段（提取后）
 prd_url: string | null;
 description: string | null;
 tech_doc_url: string | null;
}
/** 触发日志详情 */
interface TriggerLogDetail extends TriggerLog {
 event_uuid: string;
 work_item_type: string;
 error_message: string | null;
}
/** 原始数据响应 */
interface TriggerLogRaw {
 webhook_request: Record<string, unknown>;
 work_item_response: {
 err: Record<string, unknown>;
 err_code: number;
 err_msg: string;
 data: WorkItemData;
 };
}
/** 工作项数据 */
interface WorkItemData {
 id: number;
 name: string;
 template_type: string;
 pattern: string;
 work_item_type_key: string;
 work_item_status: Record<string, unknown>;
 fields: WorkItemField;
 // ... 其他字段
}
```
## UI 设计
### 日志列表页
- 表格展示：时间、项目、事件类型、工作项名称、状态
- 点击行跳转详情页
### 日志详情页
```
┌─────────────────────────────────────────────────┐
│ 触发日志详情 │
├─────────────────────────────────────────────────┤
│ 基本信息 │
│ ├─ 时间: 2026-01-21 10:30:00 │
│ ├─ 事件类型: WorkitemStatusEvent │
│ └─ 状态: accepted │
├─────────────────────────────────────────────────┤
│ 关键字段 [突出显示] │
│ ├─ 需求文档链接: https://... [复制] │
│ ├─ 需求描述: 修复所有响应式适配... │
│ └─ 技术方案文档链接: https://... [复制] │
├─────────────────────────────────────────────────┤
│ 原始数据 [折叠状态] │
│ ▶ Webhook 请求 [展开] │
│ ▶ 工作项详情 [展开] │
└─────────────────────────────────────────────────┘
```
### JSON 高亮展开效果
```typescript
// 使用 shiki
import { codeToHtml } from 'shiki';
const JsonHighlighter = ({ json }: { json: object }) => {
 const [html, setHtml] = useState('');
 useEffect( => {
 codeToHtml(JSON.stringify(json, null, 2), {
 lang: 'json',
 theme: 'github-dark'
 }).then(setHtml);
 }, [json]);
 return <div dangerouslySetInnerHTML={{ __html: html }} />;
};
```
## Risks / Trade-offs
| Risk | Mitigation |
|------|------------|
| 数据冗余（同时存储 WebhookLog 和 TriggerLog） | 初期保留双写，验证稳定后可迁移 |
| shiki 包体积较大（~2MB） | 使用动态导入，仅在展开原始数据时加载 |
| 字段 key（如 field_bcff9b）可能变化 | 在配置文件中定义，便于修改 |
## Open Questions
- 是否需要提供日志导出功能？
- 原始数据保留多长时间？（当前 WebhookLog 无自动清理）
