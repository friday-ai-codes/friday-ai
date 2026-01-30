# Design: 代码库 RAG 索引系统
## Context
Friday 是一个 AI 驱动的敏捷开发自动化系统。当前系统在执行任务时，AI 无法主动理解目标仓库的代码结构。本设计引入基于向量检索的代码 RAG 系统，让 AI 能够在回答问题和生成代码时检索相关上下文。
### Stakeholders
- 开发者：希望 AI 能理解项目代码，提供精准的代码问答
- 运维：需要管理向量数据库服务和模型资源
- 系统管理员：需要在系统设置中配置 RAG 相关参数
### Constraints
- 必须支持增量更新，避免每次全量重建索引
- 必须支持多语言代码（Vue/Go/TypeScript/Python）
- 向量数据库服务（Qdrant）作为外部依赖，需可配置
- Embedding 模型需支持本地部署或远程 API
## Goals / Non-Goals
### Goals
- 为仓库提供"新建索引"能力，将代码向量化存储到 Qdrant
- 实现基于文件 Hash 的增量更新机制
- 使用 Tree-sitter 进行 AST 级别的代码切分，保持语义完整
- 提供 Hybrid Search（语义 + 关键词）+ BGE-Reranker 的高精度检索
- 在系统设置中提供向量索引相关配置项
### Non-Goals
- 不支持多分支索引（仅 Master/Main 分支）
- 不实现实时同步（手动触发或定时任务）
- 不在本阶段集成到 AI 对话流程（检索 API 独立提供）
## Architecture Overview
```
┌─────────────────────────────────────────────────────────────────┐
│ Friday Backend │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────────┐ ┌─────────────────┐ │
│ │ Repository │───▶│ Indexing Job │───▶│ Qdrant │ │
│ │ Model │ │ (Background) │ │ Vector Store │ │
│ └─────────────┘ └────────┬────────┘ └─────────────────┘ │
│ │ ▲ │
│ ▼ │ │
│ ┌────────────────┐ │ │
│ │ Code Parser │ │ │
│ │ (Tree-sitter) │ │ │
│ └────────────────┘ │ │
│ │ │ │
│ ▼ │ │
│ ┌────────────────┐ │ │
│ │ Embedding │───────────────┘ │
│ │ (work item) │ │
│ └────────────────┘ │
│ │
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ Query Pipeline ││
│ │ ┌──────────┐ ┌──────────────┐ ┌──────────────────┐ ││
│ │ │ Query │──▶│ Hybrid Search│──▶│ BGE-Reranker │ ││
│ │ │ API │ │ (Dense+BM25) │ │ (Top-K Rerank) │ ││
│ │ └──────────┘ └──────────────┘ └──────────────────┘ ││
│ └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```
## Decisions
### Decision 1: 向量数据库选择 Qdrant
**选择**: Qdrant
**理由**:
- 原生支持 Hybrid Search（Dense + Sparse Vector）
- 支持 Payload 过滤（按 file_path、ref 等字段筛选）
- Rust 编写，性能优异
- 支持 Docker 部署，易于集成
**备选方案**:
- Milvus: 功能强大但部署复杂
- Pinecone: SaaS 方案，不适合私有化部署
- ChromaDB: 轻量但缺乏生产级特性
### Decision 2: Embedding 模型选择 work item (远程 API)
**选择**: `BAAI/bge-m3` 通过远程 API 调用
**理由**:
- 支持多语言（中英文代码注释）
- 支持长文本（8192 tokens）
- 支持 Dense + Sparse 双向量输出，配合 Hybrid Search
- 通过 API 调用，无需本地 GPU 资源
**部署方式**:
- 用户自行部署 Embedding API 服务（如 TEI、vLLM、Ollama 等）
- 系统通过配置的 API 地址调用
**备选方案**:
- OpenAI Ada-002: 效果好但需付费 API
- CodeBERT: 专为代码设计但长度限制严格
- Cohere Embed: 需外部 API
### Decision 3: 代码切分策略 - AST 级别切分
**选择**: Tree-sitter 基于 AST 的语法感知切分
**理由**:
- 保持代码语义完整（函数、类不会被截断）
- 支持多语言和多文件类型
- 可提取结构化元数据（函数名、类名）
**支持的文件类型**:
| 类型 | 扩展名 | 解析策略 |
|------|--------|----------|
| Go | .go | tree-sitter-go |
| TypeScript | .ts, .tsx | tree-sitter-typescript |
| JavaScript | .js, .jsx | tree-sitter-javascript |
| Python | .py | tree-sitter-python |
| Vue SFC | .vue | 分离 script/template，分别解析 |
| CSS | .css | tree-sitter-css |
| SCSS | .scss | tree-sitter-scss |
| SASS | .sass | 字符级切分（降级） |
| HTML | .html | tree-sitter-html |
| JSON | .json | tree-sitter-json |
| Markdown | .md | 按标题/段落切分 |
**实现细节**:
- Go/Python/TypeScript/JavaScript: 直接使用 Tree-sitter 解析
- Vue SFC: 先分离 `<script>` 和 `<template>`，分别处理
- CSS/SCSS: 按规则块切分
- 不支持的类型: 降级为字符级切分
### Decision 4: 增量更新策略 - 基于文件 Hash
**选择**: MD5/SHA256 文件 Hash 比对
**理由**:
- 实现简单，无需 Git 历史分析
- 准确识别变更文件
- 向量库 Payload 存储 Hash，便于比对
**流程**:
1. 扫描本地文件，计算 Hash
2. 查询 Qdrant 已存文件的 Hash
3. 差异计算：ADD / UPDATE / DELETE / SKIP
### Decision 5: 检索策略 - Hybrid Search + Rerank
**选择**: 两阶段检索
**阶段一 - 召回 (Recall)**:
- Qdrant Hybrid Search: Dense Vector + BM25 Sparse Vector
- Top-K = 30~50
**阶段二 - 精排 (Rerank)**:
- 使用 `BAAI/bge-reranker-large`
- 对 Query 与每个召回结果打分
- 返回 Top 5~10
**理由**:
- Hybrid Search 平衡语义相似和关键词匹配
- Reranker 解决"向量相似但逻辑无关"的误召回问题
## Data Model
### Repository 扩展
```python
# Repository model 新增字段
class Repository(models.Model):
 # ... existing fields ...
 # 索引状态
 index_status = models.CharField(
 max_length=20,
 choices=IndexStatus.choices,
 default=IndexStatus.NOT_INDEXED
 )
 last_indexed_at = models.DateTimeField(null=True, blank=True)
 index_error = models.TextField(null=True, blank=True)
class IndexStatus(models.TextChoices):
 NOT_INDEXED = "not_indexed", "未索引"
 INDEXING = "indexing", "索引中"
 INDEXED = "indexed", "已索引"
 FAILED = "failed", "索引失败"
```
### Qdrant Collection Schema
```json
{
 "collection_name": "code_index_{repository_id}",
 "vectors": {
 "dense": { "size": 1024, "distance": "Cosine" },
 "sparse": { "type": "sparse" }
 },
 "payload_schema": {
 "file_path": "keyword",
 "file_hash": "keyword",
 "language": "keyword",
 "node_type": "keyword",
 "context_header": "text",
 "ref": "keyword"
 }
}
```
### 系统设置扩展
```python
class SettingKeys:
 # ... existing keys ...
 # 向量索引设置
 QDRANT_URL = "qdrant_url"
 QDRANT_API_KEY = "qdrant_api_key"
 EMBEDDING_MODEL = "embedding_model"
 EMBEDDING_DIMENSION = "embedding_dimension"
 EMBEDDING_API_URL = "embedding_api_url"
 RERANKER_MODEL = "reranker_model"
 RERANKER_API_URL = "reranker_api_url"
```
## API Design
### 索引管理 API
```
POST /api/repositories/{id}/index/ # 触发索引
GET /api/repositories/{id}/index/status/ # 查询索引状态
DELETE /api/repositories/{id}/index/ # 删除索引
```
### 代码检索 API
```
POST /api/repositories/{id}/search/
{
 "query": "handleLogin 方法是怎么调用后端的",
 "top_k": 10,
 "filters": {
 "language": "typescript",
 "file_pattern": "src/components/**"
 }
}
```
## Risks / Trade-offs
| Risk | Impact | Mitigation |
|------|--------|------------|
| Qdrant 服务不可用 | 检索功能完全失效 | 系统设置中提供健康检查，前端显示服务状态 |
| Embedding 模型加载慢 | 首次索引延迟高 | 支持远程 API 模式，模型预加载 |
| 大型仓库索引耗时长 | 用户体验差 | 后台异步任务 + 进度显示 |
| Tree-sitter 不支持某些语言 | 部分文件无法精准切分 | 降级为字符级切分 |
## Migration Plan. **Phase**: 后端基础设施
 - 扩展 Repository 模型
 - 扩展 SystemSetting 配置项
 - 实现 Qdrant 客户端服务
2. **Phase**: 索引服务
 - 实现 Tree-sitter 解析器
 - 实现 Embedding 服务
 - 实现增量索引逻辑
3. **Phase**: 检索服务
 - 实现 Hybrid Search
 - 实现 Reranker 集成
 - 提供检索 API
4. **Phase**: 前端 UI
 - 仓库详情页添加索引操作
 - 系统设置页添加向量索引配置
 - 索引状态和进度展示
## Open Questions
1. **模型部署方式**: 是否需要支持 Ollama 或其他本地模型服务？
2. **定时同步**: 是否需要支持 Cron 定时增量同步？
3. **检索集成**: 检索结果如何集成到现有的 AI 对话流程？
