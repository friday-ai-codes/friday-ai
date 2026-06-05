---
title: accounts API
---

# accounts

### GET `/api/accounts/users/`

**获取用户列表**

返回系统中所有用户的分页列表

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| page | query | integer | no | 页码 |
| page_size | query | integer | no | 每页数量 |

#### Responses

- **200**: 成功返回用户列表

```json
{
  "count": "integer",
  "results": ["object"]
}
```

---

### POST `/api/accounts/users/`

**创建用户**

创建新用户账户

#### Request Body

```json
{
  "username": "string",
  "email": "string",
  "password": "string"
}
```

#### Responses

- **201**: 用户创建成功

```json
{
  "id": "integer",
  "username": "string",
  "email": "string",
  "is_active": "boolean",
  "created_at": "string"
}
```
- **400**: 请求参数错误

---

### GET `/api/accounts/users/{id}/`

**获取用户详情**

#### Parameters

| Name | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| id | path | integer | yes | 用户 ID |

#### Responses

- **200**: 成功返回用户详情

```json
{
  "id": "integer",
  "username": "string",
  "email": "string",
  "is_active": "boolean",
  "created_at": "string"
}
```
- **404**: 用户不存在
