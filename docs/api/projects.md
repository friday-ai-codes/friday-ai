---
title: projects API
---
# projects
### GET `/api/projects/`
**获取项目列表**
返回当前用户可见的所有项目
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| status | query | string | 否 | 项目状态过滤 |
#### 响应
- **200**: 成功返回项目列表
```json
{
 "count": "integer",
 "results": [object]
}
```
---
### POST `/api/projects/`
**创建项目**
创建新的自动化项目
#### 请求体
```json
{
 "name": "string",
 "description": "string"
}
```
#### 响应
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
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 项目 ID |
#### 响应
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
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 项目 ID |
#### 请求体
```json
{
 "name": "string",
 "description": "string"
}
```
#### 响应
- **200**: 项目更新成功
---
### DELETE `/api/projects/{id}/`
**删除项目**
#### 参数
| 名称 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| id | path | integer | 是 | 项目 ID |
#### 响应
- **204**: 项目删除成功
