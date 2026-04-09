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
