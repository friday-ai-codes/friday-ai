---
slug: repo-index-audit
date: 2026-08-10
status: in-progress
---

# 仓库索引覆盖审计 + study-course master 改动溯源

## 任务
1. 查 study-course 语义 RAG 只索引 2 文件/10 chunk 的原因（挂 feat/coding-agent-base 是预期）
2. 列出系统中所有"该索引却没索引"的仓（排除空仓、不活跃仓）
3. 查 study-course 在 master 分支的提交内容与改动目的（高三提分相关）

## 验证
- SQL 统计各仓 index_status / indexed_files_total / 分支
- GitLab master 提交历史
