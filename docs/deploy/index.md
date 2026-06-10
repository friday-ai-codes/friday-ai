---
title: 部署总览
---

# 部署总览

Friday AI 是自托管系统，提供三种部署方式。所有方式启动的都是同一套组件：Web（Nginx 代理）、Server（Django API）、Runner（Go 调度器）、PostgreSQL、Redis 和 Qdrant。

## 选型

<LinkCards>
  <LinkCard icon="🐳" title="Docker Compose" desc="快速体验、单机部署、中小团队生产环境（推荐）" link="/deploy/docker-compose" />
  <LinkCard icon="☸️" title="Helm / Kubernetes" desc="已有 K8s 集群、需要副本与探针管理的生产环境" link="/deploy/helm" />
  <LinkCard icon="🛠️" title="源码运行" desc="二次开发、贡献代码、调试" link="/deploy/source" />
</LinkCards>

## 系统要求

| 项目 | 要求 |
| --- | --- |
| CPU / 内存 | 建议 2 核 4 GB 起步；代码索引（Qdrant + 嵌入计算）对内存更敏感 |
| Docker | Docker Engine + Docker Compose v2（Runner 需要访问 `/var/run/docker.sock` 来启动任务容器） |
| 网络 | 可访问所选 AI Provider（Anthropic / OpenAI / Gemini）或内网 Ollama；可访问 GitHub / GitLab |
| 端口 | Web `10240`、API `10241`、Qdrant `6333/6334`、Redis `6379`（均可通过环境变量修改） |

## 预构建镜像

每次发布（`v*` tag）由 GitHub Actions 自动构建多架构镜像（amd64 / arm64）并推送到 GHCR：

| 镜像 | 用途 |
| --- | --- |
| `ghcr.io/friday-ai-codes/friday-ai/server` | Django 后端 |
| `ghcr.io/friday-ai-codes/friday-ai/web` | 前端 + Nginx 代理 |
| `ghcr.io/friday-ai-codes/friday-ai/runner` | Go Runner |
| `ghcr.io/friday-ai-codes/friday-ai/task` | 任务容器（Runner 按需拉取） |

Helm Chart 同步发布到 `oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday`。

## 部署后的第一件事

无论哪种方式，部署完成后打开 Web 界面都会进入**首启初始化向导**：

<FlowPipeline :steps="['设置管理员账号', '配置 AI Provider', '索引代码仓库', '绑定飞书（可选）']" />

1. 设置管理员账号（fail-closed 设计：仅当系统中没有 superuser 时向导可用）；
2. 配置 AI Provider（Anthropic / OpenAI / Gemini / Ollama 任一即可）；
3. 连接并索引代码仓库；
4. 可选：绑定飞书项目、机器人与 Webhook。

后续步骤见[快速开始](/guide/quick-start)。
