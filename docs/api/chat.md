---
title: chat API
---

# chat

### GET `/api/chat/conversations/`

**获取对话列表**

返回当前用户的所有 AI 对话记录

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| project | query | integer | no | 关联项目 ID |

#### Responses

- **200**: 成功返回对话列表

---

### POST `/api/chat/conversations/`

**创建对话**

开始一个新的 AI 对话

#### Request Body

```json
{
  "title": "string",
  "project": "integer"
}
```

#### Responses

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

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 对话 ID |

#### Responses

- **200**: 成功返回消息列表

---

### POST `/api/chat/conversations/{id}/messages/`

**发送消息**

向对话发送新消息并获取 AI 响应

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 对话 ID |

#### Request Body

```json
{
  "content": "string"
}
```

#### Responses

- **201**: 消息发送成功

```json
{
  "id": "integer",
  "role": "string",
  "content": "string",
  "created_at": "string"
}
```
