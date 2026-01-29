# Implementation Tasks
## 1. Docker 基础设施
### 1.1 Qdrant 服务集成
- 1.1.1 在 docker-compose.yml 添加 qdrant 服务定义
- 1.1.2 配置 Qdrant 数据持久化目录 `./data/qdrant`
- 1.1.3 配置 Qdrant 端口映射 (6333, 6334)
- 1.1.4 添加 Qdrant 健康检查配置
## 2. 后端数据模型
### 2.1 系统设置扩展
- 2.1.1 扩展 `server/system/models.py` SettingKeys，添加向量索引配置项：
 - QDRANT_URL
 - QDRANT_API_KEY
 - EMBEDDING_API_URL
 - EMBEDDING_MODEL
 - EMBEDDING_DIMENSION
 - RERANKER_API_URL
 - RERANKER_MODEL
- 2.1.2 扩展 ENCRYPTED_KEYS 包含 QDRANT_API_KEY
### 2.2 仓库模型扩展
- 2.2.1 扩展 `server/repositories/models.py` Repository 模型，添加：
 - index_status 字段（枚举：not_indexed/indexing/indexed/failed）
 - last_indexed_at 时间戳字段
 - index_error 文本字段
- 2.2.2 创建 IndexStatus 枚举类
- 2.2.3 生成并执行数据库迁移
## 3. 依赖管理
### 3.1 Python 依赖
- 3.1.1 添加依赖到 pyproject.toml：
 - llama-index
 - qdrant-client
 - llama-index-vector-stores-qdrant
 - tree-sitter
 - tree-sitter-go
 - tree-sitter-javascript
 - tree-sitter-python
 - tree-sitter-css
 - tree-sitter-html
 - tree-sitter-json
## 4. 索引服务实现
### 4.1 Qdrant 客户端服务
- 4.1.1 创建 `server/services/qdrant_client.py`
- 4.1.2 实现 Qdrant 连接（从 SystemSetting 读取配置）
- 4.1.3 实现 Collection 创建/删除逻辑
- 4.1.4 实现健康检查方法
### 4.2 代码解析服务
- 4.2.1 创建 `server/services/code_parser.py`
- 4.2.2 实现 Tree-sitter Go 解析器
- 4.2.3 实现 Tree-sitter TypeScript/JavaScript 解析器
- 4.2.4 实现 Tree-sitter Python 解析器
- 4.2.5 实现 Vue SFC 解析器（分离 script/template）
- 4.2.6 实现 Tree-sitter CSS/SCSS 解析器
- 4.2.7 实现 Tree-sitter HTML 解析器
- 4.2.8 实现 Markdown 切分器
- 4.2.9 实现字符级降级切分（不支持的类型）
- 4.2.10 实现上下文增强（context_header 拼接）
### 4.3 Embedding API 服务
- 4.3.1 创建 `server/services/embedding.py`
- 4.3.2 实现远程 Embedding API 调用
- 4.3.3 实现 Dense + Sparse 向量生成
- 4.3.4 实现批量 Embedding 生成
### 4.4 增量索引服务
- 4.4.1 创建 `server/services/indexer.py`
- 4.4.2 实现文件 Hash 计算 (MD5/SHA256)
- 4.4.3 实现本地文件扫描
- 4.4.4 实现 Qdrant 已存 Hash 查询
- 4.4.5 实现差异计算逻辑（ADD/UPDATE/DELETE/SKIP）
- 4.4.6 实现增量索引主流程
### 4.5 Git 克隆服务
- 4.5.1 扩展现有 Git 服务，支持克隆到临时目录
- 4.5.2 支持 Git 代理配置
## 5. 检索服务实现
### 5.1 Hybrid Search 服务
- 5.1.1 创建 `server/services/search.py`
- 5.1.2 实现 Query Embedding 生成（调用 Embedding API）
- 5.1.3 实现 Qdrant Hybrid Search 调用
- 5.1.4 实现过滤条件构建（language、file_pattern）
### 5.2 Reranker API 服务
- 5.2.1 创建 `server/services/reranker.py`
- 5.2.2 实现远程 Reranker API 调用
- 5.2.3 实现批量重排序逻辑
## 6. API 实现
### 6.1 索引管理 API
- 6.1.1 创建 `server/repositories/index_views.py`
- 6.1.2 实现 POST `/api/repositories/{id}/index/` - 触发索引
- 6.1.3 实现 GET `/api/repositories/{id}/index/status/` - 查询状态
- 6.1.4 实现 DELETE `/api/repositories/{id}/index/` - 删除索引
- 6.1.5 注册 URL 路由
### 6.2 代码搜索 API
- 6.2.1 实现 POST `/api/repositories/{id}/search/` - 语义搜索
- 6.2.2 实现请求参数验证（query、top_k、filters）
- 6.2.3 实现响应序列化
### 6.3 系统设置 API 扩展
- 6.3.1 实现 Qdrant 连接测试 API
- 6.3.2 实现 Embedding API 连接测试
## 7. 后台任务
### 7.1 索引任务
- 7.1.1 创建异步索引任务函数
- 7.1.2 实现任务进度更新
- 7.1.3 实现错误处理和状态更新
- 7.1.4 实现临时目录清理
## 8. 前端实现
### 8.1 系统设置页面
- 8.1.1 创建向量索引配置表单组件
- 8.1.2 实现 Qdrant 服务配置 UI
- 8.1.3 实现 Embedding API 配置 UI
- 8.1.4 实现 Reranker API 配置 UI
- 8.1.5 实现连接测试功能
- 8.1.6 集成到系统设置页面
### 8.2 仓库详情页
- 8.2.1 添加索引状态徽章组件
- 8.2.2 添加"新建索引"按钮
- 8.2.3 实现索引进度显示
- 8.2.4 实现索引失败错误提示
- 8.2.5 添加"重新索引"和"删除索引"操作
## 9. 测试
### 9.1 单元测试
- 9.1.1 测试文件 Hash 计算
- 9.1.2 测试代码解析器（各语言/文件类型）
- 9.1.3 测试增量索引逻辑
### 9.2 集成测试
- 9.2.1 测试索引 API 端点
- 9.2.2 测试搜索 API 端点
- 9.2.3 测试 Qdrant 集成
## 10. 文档
- 10.1 更新 API 文档（drf-spectacular）
- 10.2 添加向量索引配置说明到部署文档
- 10.3 添加 Embedding/Reranker API 部署指南
