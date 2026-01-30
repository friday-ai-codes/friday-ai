# code-rag Specification
## Purpose
TBD - created by archiving change add-code-rag-indexing. Update Purpose after archive.
## Requirements
### Requirement: 代码索引触发
系统 SHALL 允许用户为仓库触发代码索引操作。索引操作将仓库代码克隆到临时目录，解析并向量化存储到 Qdrant。
#### Scenario: 首次索引仓库
- **WHEN** 用户对未索引的仓库点击"新建索引"
- **THEN** 系统创建后台任务，克隆仓库到临时目录
- **AND** 使用配置的 Git 代理（如有）
- **AND** 将仓库状态设置为 "indexing"
- **AND** 完成后状态变为 "indexed"
#### Scenario: 重新索引仓库
- **WHEN** 用户对已索引的仓库点击"重新索引"
- **THEN** 系统执行增量更新，仅处理变更的文件
- **AND** 基于文件 Hash 比对识别 ADD/UPDATE/DELETE
#### Scenario: 索引失败处理
- **WHEN** 索引过程中发生错误
- **THEN** 仓库状态设置为 "failed"
- **AND** 错误信息存储在 index_error 字段
- **AND** 用户可查看失败原因并重试
### Requirement: AST 级别代码切分
系统 SHALL 使用 Tree-sitter 进行基于语法树的代码切分，保持代码语义完整性。支持多种编程语言和样式文件。
#### Scenario: Go 代码切分
- **WHEN** 解析 .go 文件
- **THEN** 使用 tree-sitter-go 解析 AST
- **AND** 按 func/struct/interface 边界切分
- **AND** 每个 Chunk 包含完整的函数或类型定义
#### Scenario: TypeScript 代码切分
- **WHEN** 解析 .ts/.tsx 文件
- **THEN** 使用 tree-sitter-typescript 解析 AST
- **AND** 按 function/class/interface 边界切分
#### Scenario: JavaScript 代码切分
- **WHEN** 解析 .js/.jsx 文件
- **THEN** 使用 tree-sitter-javascript 解析 AST
- **AND** 按 function/class 边界切分
#### Scenario: Python 代码切分
- **WHEN** 解析 .py 文件
- **THEN** 使用 tree-sitter-python 解析 AST
- **AND** 按 function/class 边界切分
#### Scenario: Vue SFC 代码切分
- **WHEN** 解析 .vue 文件
- **THEN** 先分离 `<template>` 和 `<script>` 部分
- **AND** Script 部分使用 TypeScript 解析器处理
- **AND** Template 部分按 DOM 结构切分
#### Scenario: CSS 样式切分
- **WHEN** 解析 .css 文件
- **THEN** 使用 tree-sitter-css 解析
- **AND** 按规则块切分
#### Scenario: SCSS 样式切分
- **WHEN** 解析 .scss 文件
- **THEN** 使用 tree-sitter-scss 解析
- **AND** 按规则块和嵌套结构切分
#### Scenario: SASS 样式切分
- **WHEN** 解析 .sass 文件
- **THEN** 降级为字符级切分
- **AND** 按缩进层级尽量保持语义完整
#### Scenario: HTML 文件切分
- **WHEN** 解析 .html 文件
- **THEN** 使用 tree-sitter-html 解析
- **AND** 按 DOM 元素结构切分
#### Scenario: Markdown 文件切分
- **WHEN** 解析 .md 文件
- **THEN** 按标题和段落边界切分
- **AND** 保持代码块完整
#### Scenario: 上下文增强
- **WHEN** 生成代码 Chunk
- **THEN** 每个 Chunk 的 Metadata 包含 file_path、file_hash、language
- **AND** context_header 拼接文件名和语言信息
- **AND** context_header 参与向量化以增强语义
#### Scenario: 不支持的文件类型
- **WHEN** 解析不支持 AST 解析的文件类型
- **THEN** 降级为字符级切分
- **AND** 按行数和字符数限制进行切分
### Requirement: 基于 Hash 的增量更新
系统 SHALL 基于文件 Hash 实现增量索引更新，避免全量重建。
#### Scenario: 检测新增文件
- **WHEN** 本地文件存在但 Qdrant 中无对应 file_path
- **THEN** 解析文件并生成向量
- **AND** Upsert 到 Qdrant
#### Scenario: 检测变更文件
- **WHEN** 本地文件 Hash 与 Qdrant 中存储的 file_hash 不一致
- **THEN** 删除该 file_path 的所有旧向量
- **AND** 重新解析并 Upsert 新向量
#### Scenario: 检测删除文件
- **WHEN** Qdrant 中存在 file_path 但本地文件不存在
- **THEN** 删除该 file_path 的所有向量
#### Scenario: 跳过未变更文件
- **WHEN** 本地文件 Hash 与 Qdrant 中一致
- **THEN** 跳过该文件，不进行任何操作
### Requirement: Hybrid Search 代码检索
系统 SHALL 提供混合检索能力，结合语义向量和关键词匹配。
#### Scenario: 执行代码搜索
- **WHEN** 用户提交搜索查询
- **THEN** 使用 work item 生成 Query 的 Dense 和 Sparse 向量
- **AND** 在 Qdrant 执行 Hybrid Search
- **AND** 返回 Top-K 候选结果
#### Scenario: 按语言过滤
- **WHEN** 搜索请求包含 language 过滤条件
- **THEN** 仅返回指定语言的代码片段
#### Scenario: 按文件路径过滤
- **WHEN** 搜索请求包含 file_pattern 过滤条件
- **THEN** 仅返回匹配路径模式的代码片段
### Requirement: BGE-Reranker 精排
系统 SHALL 使用 BGE-Reranker 对召回结果进行精排，提升检索准确率。
#### Scenario: 执行重排序
- **WHEN** Hybrid Search 返回 Top-30 候选结果
- **THEN** 使用 bge-reranker-large 计算 Query 与每个候选的相关性分数
- **AND** 按分数降序排列
- **AND** 返回 Top-5~10 最相关结果
#### Scenario: 过滤低相关结果
- **WHEN** Reranker 分数低于阈值
- **THEN** 该结果不包含在最终返回中
### Requirement: 索引状态管理
系统 SHALL 跟踪每个仓库的索引状态，提供状态查询接口。
#### Scenario: 查询索引状态
- **WHEN** 用户请求仓库索引状态
- **THEN** 返回当前状态（not_indexed/indexing/indexed/failed）
- **AND** 返回最后索引时间
- **AND** 如失败则返回错误信息
#### Scenario: 删除索引
- **WHEN** 用户请求删除仓库索引
- **THEN** 删除 Qdrant 中该仓库的 Collection
- **AND** 将仓库状态重置为 "not_indexed"
### Requirement: 索引管理 API
系统 SHALL 提供 RESTful API 管理仓库索引。
#### Scenario: 触发索引 API
- **WHEN** POST `/api/repositories/{id}/index/`
- **THEN** 启动后台索引任务
- **AND** 返回任务 ID 和初始状态
#### Scenario: 查询索引状态 API
- **WHEN** GET `/api/repositories/{id}/index/status/`
- **THEN** 返回索引状态详情
#### Scenario: 删除索引 API
- **WHEN** DELETE `/api/repositories/{id}/index/`
- **THEN** 删除索引并返回确认
### Requirement: 代码搜索 API
系统 SHALL 提供代码语义搜索 API。
#### Scenario: 执行搜索
- **WHEN** POST `/api/repositories/{id}/search/` with query body
- **THEN** 执行 Hybrid Search + Rerank
- **AND** 返回匹配的代码片段列表
- **AND** 每个结果包含 file_path、score、code_snippet、context_header
#### Scenario: 搜索未索引仓库
- **WHEN** 对未索引仓库执行搜索
- **THEN** 返回 400 错误，提示需先建立索引
### Requirement: 索引操作前端界面
系统 SHALL 在仓库详情页提供索引管理操作入口。
#### Scenario: 显示索引状态
- **WHEN** 用户访问仓库详情页
- **THEN** 显示当前索引状态徽章
- **AND** 显示最后索引时间（如有）
#### Scenario: 触发索引操作
- **WHEN** 用户点击"新建索引"按钮
- **THEN** 发送索引请求
- **AND** 显示索引进行中状态
- **AND** 完成后刷新状态显示
#### Scenario: 索引失败提示
- **WHEN** 索引状态为 failed
- **THEN** 显示错误提示
- **AND** 提供"重试"按钮
