# Change: 代码库 RAG 索引系统
## Why
当前 Friday 系统缺乏对代码仓库的语义理解能力。开发者在与 AI 交互时，AI 无法主动"理解"项目代码结构、函数定义和业务逻辑。通过引入基于向量索引的代码 RAG（Retrieval-Augmented Generation）系统，可以让 AI 在回答问题时检索相关代码片段，大幅提升代码问答的准确性和上下文相关性。
## What Changes
- **ADDED**: 新增 `code-rag` 能力模块，支持基于 LlamaIndex + Tree-sitter + Qdrant + BGE-Reranker 的代码索引与检索
- **ADDED**: 为仓库增加"新建索引"功能，支持将仓库代码向量化存储
- **ADDED**: 基于 Hash 的增量更新机制，避免全量重建索引
- **ADDED**: 支持多语言/多文件类型的 AST 级别代码切分（Vue、TypeScript、Go、Python、SCSS、CSS、SASS 等）
- **ADDED**: Docker Compose 集成 Qdrant 向量数据库服务
- **MODIFIED**: 扩展系统设置，新增向量索引相关配置项（Qdrant 服务地址、Embedding API、模型维度等）
- **ADDED**: 代码检索与重排序 API，支持 Hybrid Search + BGE-Reranker 精排
## Impact
- Affected specs: `code-rag` (新增), `django-architecture` (扩展系统设置), `docker-deployment` (新增 Qdrant 服务)
- Affected code:
 - `server/repositories/` - 新增索引触发逻辑
 - `server/system/` - 扩展 SettingKeys
 - `server/services/` - 新增 RAG 索引服务
 - `web/` - 新增索引管理 UI
 - `docker-compose.yml` - 新增 Qdrant 服务
- External dependencies:
 - Qdrant (向量数据库，Docker Compose 集成)
 - Embedding API (work item 远程服务)
 - Reranker API (BGE-Reranker 远程服务)
 - LlamaIndex
 - Tree-sitter
