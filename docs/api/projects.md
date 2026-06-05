---
title: projects API
---

# projects

### GET `/api/projects/`

**获取项目列表**

返回当前用户可见的所有项目

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| status | query | string | no | 项目状态过滤 |

#### Responses

- **200**: 成功返回项目列表

```json
{
  "count": "integer",
  "results": ["object"]
}
```

---

### POST `/api/projects/`

**创建项目**

创建新的自动化项目

#### Request Body

```json
{
  "name": "string",
  "description": "string"
}
```

#### Responses

- **201**: 项目创建成功

```json
{
  "id": "integer",
  "name": "string",
  "description": "string",
  "status": "string",
  "owner": "object",
  "created_at": "string",
  "updated_at": "string"
}
```

---

### GET `/api/projects/{id}/`

**获取项目详情**

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 项目 ID |

#### Responses

- **200**: 成功返回项目详情

```json
{
  "id": "integer",
  "name": "string",
  "description": "string",
  "status": "string",
  "owner": "object",
  "created_at": "string",
  "updated_at": "string"
}
```

---

### PATCH `/api/projects/{id}/`

**更新项目**

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 项目 ID |

#### Request Body

```json
{
  "name": "string",
  "description": "string"
}
```

#### Responses

- **200**: 项目更新成功

---

### DELETE `/api/projects/{id}/`

**删除项目**

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 项目 ID |

#### Responses

- **204**: 项目删除成功
