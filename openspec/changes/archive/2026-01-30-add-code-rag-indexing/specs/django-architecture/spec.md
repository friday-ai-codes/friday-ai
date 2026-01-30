# django-architecture Spec Delta
## MODIFIED Requirements
### Requirement: settings App 结构
settings App SHALL 负责系统级配置管理，包括向量索引相关配置。
#### Scenario: 模型定义
- **WHEN** 查看 settings App 模型
- **THEN** 包含 SystemSetting 模型
- **AND** 包含 SettingKeys 常量类
- **AND** SystemSetting 使用 `db_table = "system_settings"`
#### Scenario: SettingKeys 常量
- **WHEN** 查看 SettingKeys 类
- **THEN** 包含 Anthropic 相关配置项：
 - `ANTHROPIC_API_KEY`
 - `ANTHROPIC_BASE_URL`
 - `ANTHROPIC_MODEL`
- **AND** 包含 Git 代理配置项：
 - `GIT_HTTP_PROXY`
- **AND** 包含向量索引配置项：
 - `QDRANT_URL` - Qdrant 服务地址
 - `QDRANT_API_KEY` - Qdrant API 密钥（加密存储）
 - `EMBEDDING_MODEL` - Embedding 模型名称
 - `EMBEDDING_DIMENSION` - Embedding 向量维度
 - `EMBEDDING_API_URL` - Embedding 模型 API 地址（可选）
 - `RERANKER_MODEL` - Reranker 模型名称
 - `RERANKER_API_URL` - Reranker 模型 API 地址（可选）
#### Scenario: API 端点
- **WHEN** 管理系统配置
- **THEN** 使用 `/api/settings/` 前缀的 API
#### Scenario: 加密存储
- **WHEN** 存储敏感配置项（如 QDRANT_API_KEY）
- **THEN** 使用 FRIDAY_ENCRYPTION_KEY 加密存储
- **AND** API 返回时隐藏实际值
## ADDED Requirements
### Requirement: 向量索引系统设置界面
系统 SHALL 在系统设置页面提供向量索引配置入口。
#### Scenario: 配置 Qdrant 服务
- **WHEN** 用户访问系统设置的"向量索引"标签页
- **THEN** 显示 Qdrant 服务配置表单
- **AND** 包含 Qdrant URL 输入框
- **AND** 包含 Qdrant API Key 密码输入框
#### Scenario: 配置 Embedding 模型
- **WHEN** 用户配置 Embedding 模型
- **THEN** 可输入模型名称（默认 BAAI/bge-m3）
- **AND** 可输入向量维度（默认 1024）
- **AND** 可选配置远程 API 地址
#### Scenario: 配置 Reranker 模型
- **WHEN** 用户配置 Reranker 模型
- **THEN** 可输入模型名称（默认 BAAI/bge-reranker-large）
- **AND** 可选配置远程 API 地址
#### Scenario: 测试连接
- **WHEN** 用户点击"测试连接"按钮
- **THEN** 系统尝试连接 Qdrant 服务
- **AND** 返回连接成功或失败状态
### Requirement: repositories App 索引扩展
repositories App SHALL 支持仓库的向量索引状态跟踪。
#### Scenario: 模型扩展
- **WHEN** 查看 Repository 模型
- **THEN** 包含 index_status 字段（枚举：not_indexed/indexing/indexed/failed）
- **AND** 包含 last_indexed_at 时间戳字段
- **AND** 包含 index_error 文本字段
#### Scenario: API 扩展
- **WHEN** 管理仓库索引
- **THEN** 使用 `/api/repositories/{id}/index/` 前缀的 API
- **AND** 包括 POST（触发索引）、GET（查询状态）、DELETE（删除索引）方法
#### Scenario: 搜索 API
- **WHEN** 执行代码语义搜索
- **THEN** 使用 POST `/api/repositories/{id}/search/` 端点
- **AND** 请求体包含 query、top_k、filters 参数
- **AND** 返回匹配的代码片段列表
