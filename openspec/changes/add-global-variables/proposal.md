# Change: Add Global Variables System with Extraction Nodes
## Why
当前工作流系统虽然支持节点间数据传递，但缺乏明确的「全局变量」概念。用户在飞书工作项触发后，需要从工作项数据中提取关键字段（如需求文档、需求描述、技术方案链接等），并在后续多个节点中复用这些数据。现有的节点输出引用方式（`{{nodes.xxx.key}}`）不够直观，且缺乏统一的变量管理和元数据定义。
## What Changes
### 新增节点类型
1. **变量提取节点 (Variable Extractor)**
 - 从上游节点输出（JSON/YAML）中提取指定字段
 - 将提取的值注册为全局变量，支持配置 key、name、desc、required 等元数据
 - 支持多字段批量提取
2. **AI 变量提取节点 (AI Variable Extractor)**
 - 使用 AI 智能解析非结构化文本
 - 根据用户定义的变量描述，自动提取并映射到全局变量
### 全局变量系统
- 建立统一的全局变量存储机制
- 变量元数据：`key`（引用标识）、`name`（展示名称）、`desc`（描述）、`required`（是否必填）
- 支持 `{{ global.xxx }}` 模板语法在任意节点配置中引用
- 在执行上下文中自动注入所有已定义的全局变量
### 前端增强
- 新增变量提取节点配置面板
- 新增 AI 变量提取节点配置面板
- 在 Prompt 配置等输入框中支持变量自动补全
## Impact
- **Affected specs**: workflow-nodes (新增)
- **Affected code**:
 - Backend: `server/workflows/nodes/` (新增节点), `server/workflows/models/` (变量存储), `server/workflows/engine/` (上下文注入)
 - Frontend: `web/src/components/workflow/config/` (配置面板), `web/src/types/workflow/` (类型定义)
