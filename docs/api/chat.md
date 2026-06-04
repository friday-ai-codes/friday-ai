---
title: chat API
---
# chat
### GET `/api/chat/conversations/`
**获取对话列表**
返回当前用户的所有 AI 对话记录
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| project | query | integer | 否 | 关联项目 ID |
#### 响应
- **200**: 成功返回对话列表
---
### POST `/api/chat/conversations/`
**创建对话**
开始一个新的 AI 对话
#### 请求体
```json
{
 "title": "string",
 "project": "integer"
}
```
#### 响应
- **201**: 对话创建成功
```json
{
 "id": "integer",
 "title": "string",
 "project": "integer",
 "created_at": "string"
}
```
---
### GET `/api/chat/conversations/{id}/messages/`
**获取对话消息列表**
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 对话 ID |
#### 响应
- **200**: 成功返回消息列表
---
### POST `/api/chat/conversations/{id}/messages/`
**发送消息**
向对话发送新消息并获取 AI 响应
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 对话 ID |
#### 请求体
```json
{
 "content": "string"
}
```
---
## 多模态图片输入
Friday 支持 Web Chat、飞书机器人和 OpenAI-compatible API 的图片分析输入。当前范围只包含图片，不包含视频、音频、图片编辑或图片生成。
### 支持格式与限制
| 项目 | 限制 |
| --- | --- |
| 格式 | PNG、JPEG、GIF、WebP |
| 大小 | 单张最大 10MB |
| 数量 | 每条 Web 消息最多 4 张 |
| Provider | 需要 provider 与模型都支持 vision |
不支持图片的 provider/model 会返回明确错误，不会静默丢弃图片。消息正文 `content` 仍然只保存文本；图片通过 `parts` 和受控 `storage_ref` 保存。
### POST `/api/chat/images/`
上传 Web Chat 图片，返回可用于 `input_parts` 的 `image` part。
#### 请求
`multipart/form-data`
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| image | file | 是 | PNG/JPEG/GIF/WebP 图片 |
#### 响应
```json
{
 "part": {
 "type": "image",
 "id": "p_abcd1234efgh",
 "index": 0,
 "mime_type": "image/png",
 "size_bytes": 12345,
 "storage_ref": "chat_images/...",
 "source_url": "/api/chat/images/....png/",
 "detail": "auto"
 }
}
```
### POST `/api/chat/conversations/{id}/stream/`
流式发送消息时可带 `input_parts`。有图片时允许 `content` 为空；Web 端会默认发送“请分析这张图片”作为文本意图。
```json
{
 "content": "请分析这张图片",
 "role": "developer",
 "input_parts": [
 { "type": "text", "id": "p_text", "index": 0, "text": "请分析这张图片", "state": "done" },
 { "type": "image", "id": "p_image", "index": 1, "mime_type": "image/png", "size_bytes": 12345, "storage_ref": "chat_images/...", "detail": "auto" }
 ]
}
```
### POST `/v1/chat/completions`
OpenAI-compatible 入口支持字符串 `content`，也支持 content parts 数组中的 `text` 与 `image_url`。
```json
{
 "model": "friday-default",
 "messages": [
 {
 "role": "user",
 "content": [
 { "type": "text", "text": "描述这张截图" },
 { "type": "image_url", "image_url": { "url": "data:image/png;base64,...", "detail": "low" } }
 ]
 }
 ]
}
```
RAG 检索 query 只从 `text` parts 提取，不会把图片 URL 或 JSON 当作检索文本。
#### 响应
- **201**: 消息发送成功
```json
{
 "id": "integer",
 "role": "string",
 "content": "string",
 "created_at": "string"
}
```
