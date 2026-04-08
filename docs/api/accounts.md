---
title: accounts API
---
# accounts
### GET `/api/accounts/users/`
**获取用户列表**
返回系统中所有用户的分页列表
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| page | query | integer | 否 | 页码 |
| page_size | query | integer | 否 | 每页数量 |
#### 响应
- **200**: 成功返回用户列表
```json
{
 "count": "integer",
 "results": [object]
}
```
---
### POST `/api/accounts/users/`
**创建用户**
创建新用户账户
#### 请求体
```json
{
 "username": "string",
 "email": "string",
 "password": "string"
}
```
#### 响应
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
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 用户 ID |
#### 响应
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
