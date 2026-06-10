<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/public/logo-dark.svg">
    <img src="web/public/logo.svg" alt="Friday AI" width="420">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/friday-ai-codes/friday-ai/actions/workflows/ci.yaml">
    <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/friday-ai-codes/friday-ai/ci.yaml?branch=main&label=CI">
  </a>
  <a href="https://github.com/friday-ai-codes/friday-ai/actions/workflows/ci.yaml">
    <img alt="Unit Coverage" src="https://img.shields.io/badge/unit%20coverage-server%20%7C%20web%20%7C%20task-20a66a">
  </a>
  <a href="https://github.com/friday-ai-codes/friday-ai/releases">
    <img alt="Latest Release" src="https://img.shields.io/github/v/release/friday-ai-codes/friday-ai?include_prereleases&label=latest">
  </a>
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/friday-ai-codes/friday-ai">
  </a>
</p>

<p align="center">
  <a href="README.md">中文</a>
</p>

Friday AI is an open-source AI development automation platform. It connects requirements, collaboration systems, repositories, Graph RAG, approvals, Claude Code, and PR / MR delivery into a traceable workflow, so AI can move confirmed requirements toward reviewable code changes instead of only answering questions.

Friday already has deep Feishu integration across Feishu Project, Feishu Docs, Feishu bots, Feishu cards, and related automation nodes. It is not locked to Feishu: the core product is workflow orchestration, code intelligence, and auditable agent execution, so more collaboration entrypoints can be added later.

<p align="center">
  <a href="#what-it-is">What It Is</a>
  ·
  <a href="#how-it-works">How It Works</a>
  ·
  <a href="#what-it-can-do">What It Can Do</a>
  ·
  <a href="#agent-skill-and-code-indexing">Skill</a>
  ·
  <a href="#what-makes-graph-rag-different">Graph RAG</a>
  ·
  <a href="#quick-start">Quick Start</a>
  ·
  <a href="#docs">Docs</a>
</p>

---

## What It Is

Think of Friday AI as an automation workbench beside your engineering team.

It does not replace the PM, tech lead, or reviewer. It is also not a button that drops an agent into a repository and hopes for the best. Friday catches the requirement, pulls in documents and comments, gathers code evidence from the repository, prepares a technical plan, waits for human confirmation, and only then asks Claude Code to work inside a Runner-managed isolated environment.

After the work starts, Friday keeps the trail visible. Branches, commits, PRs / MRs, code review output, Feishu notifications, tool calls, retrieval evidence, model usage, and recovery points stay attached to the same execution record. The team does not get a vague “AI finished” message; it gets an engineering process that can be reviewed, questioned, and continued.

## How It Works

![Friday AI workflow](docs/public/readme/how-it-works.png)

A typical flow starts from a Feishu work item. Friday fetches fields, relations, comments, and linked documents. Graph RAG retrieves relevant files, symbols, call relationships, and cross-repository API clues from indexed repositories. AI generates a technical plan and writes it back to Feishu fields or docs. The team confirms through fields, cards, or chat. Runner then dispatches Claude Code for implementation, review, and branch preparation. Finally, PR / MR status, execution updates, and audit traces are written back to the collaboration surface.

## What It Can Do

| Scenario | Example | How Friday moves it forward |
| --- | --- | --- |
| Requirements enter from Feishu | A work item moves to “ready for development” and a requirement doc is linked in a comment. | Listen to the Feishu event, fetch work item context and docs, generate a plan, wait for approval, and dispatch coding work. |
| Plans need review first | A tech lead wants risks, affected areas, and test suggestions before any code changes. | Use Graph RAG to gather code evidence, generate a plan, write it back to Feishu, and wait for card or field confirmation. |
| Cross-repository API changes | A frontend page changes an API parameter while backend handlers, types, and tests live elsewhere. | Connect semantic retrieval, code graph expansion, and cross-repo API links to create a repository task matrix. |
| Ongoing group collaboration | Execution needs a missing field, screenshot, branch confirmation, or result notification. | Feishu bots send question cards, approval cards, review cards, and coding result updates in group or p2p chats. |
| Users ask the codebase directly | “Where does this payment callback enter?” or “Who calls this component?” | Friday Web Chat can call retrieval and code browsing tools over indexed repositories. |
| Agent Skill uses Friday as a backend | You code in Cursor / Claude Code / Codex and want the assistant to use Friday’s code index, Graph RAG, and execution tools. | Install the Skill with `npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent` and use `@friday-ai/mcp` for discovery, analysis, planning, execution, and MR creation. |
| AI code review | Claude Code has produced a branch and the team wants an automatic review plus a readable summary. | Workflows can run `ai_code_review`, then write review output, branch summaries, and PR / MR details back to Feishu. |

## Deep Feishu Integration, Not Feishu Lock-In

Friday integrates with Feishu at several levels. It is much more than notifications.

| Surface | Current capability |
| --- | --- |
| Feishu Project | Space binding, plugin credentials, webhook tokens, work item details, fields, relations, comments, status transitions, and trigger logs. |
| Feishu Docs | Detect document links, read cloud docs, convert Feishu blocks to Markdown, write Markdown back to docs, and handle tables, code blocks, and quotes. |
| Feishu Bot / IM | Send text and cards, update cards, read group history, download message resources, check or add the bot to chats, and handle group or p2p conversations. |
| Feishu card callbacks | Approval, plan confirmation, clarification, code review, and coding result cards all have callback handlers. |
| Feishu workflow nodes | `feishu_event_trigger`, `fetch_work_item`, `wait_feishu_field`, `notify_feishu`, `fetch_group_chat`, and `join_group_chat` can be placed directly into DAG workflows. |
| MCP / Agent tools | `get_feishu_work_item_context` aggregates work items, relations, comments, and docs; `create_feishu_technical_plan` combines that context with code evidence and writes a plan back. |

Feishu is the most polished collaboration entrypoint today. Underneath, Friday is still built as “collaboration entrypoint + workflow + code intelligence + Runner,” so adding other project-management, document, IM, or automation systems does not require replacing the main pipeline.

## Agent Skill and Code Indexing

Friday can act as a codebase backend for Cursor, Claude Code, Codex, and other agents. Once a repository is indexed by Friday, the agent no longer has to infer everything from the few files visible in the current local context.

Three steps to connect:

1. Install the Skill (auto-detects Claude Code, Cursor, Codex, and more):

   ```bash
   npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent
   ```

2. Create an Access Token: Friday Web console → Profile → Access Tokens → Create (the plaintext is shown only once).

3. Configure the connection (writes `~/.friday/config.json` and registers `@friday-ai/mcp` as an MCP server):

   ```bash
   npx -y @friday-ai/mcp init --base-url https://your-friday-host --token <your-access-token>
   ```

   Alternatively, just tell your IDE assistant to "set up Friday" after installing the Skill — it will ask for the host and token and finish the configuration and MCP registration for you.

The assistant can then use the same index for repository discovery, Graph RAG analysis, coding plans, plan revisions, remote execution, branch summaries, and MR creation. Web users get the visual workflow; local IDE users get callable code-intelligence tools. Both paths share the same evidence and audit trail. See the [Friday Codebase Agent guide](docs/guide/friday-codebase-agent.md).

## What Makes Graph RAG Different

Plain RAG, plain graphs, and Friday’s Graph RAG solve different parts of the problem.

| Type | What it is good at | What it tends to miss |
| --- | --- | --- |
| Plain RAG | Finds semantically similar text chunks. Good for documentation questions. | Call chains, imports, cross-file impact, and frontend/backend API links are often outside the nearest text chunks. |
| Plain graph | Shows relationships between symbols, files, calls, and dependencies. Good for structural navigation. | A graph alone does not understand the requirement, and it does not automatically compress evidence into useful model context. |
| Friday Graph RAG | Retrieves by semantic and keyword signals, then expands through one-hop / two-hop code graph edges and cross-repo API links. | It is not just graph visualization; it is built to give coding agents a better evidence set for real code changes. |

Friday indexing combines symbol parsing, Qdrant hybrid search, graph expansion, cross-repository API links, and token-budget control. The model receives a bundled context of requirement, files, symbols, neighboring chunks, and cross-repo clues instead of a loose pile of snippets.

## AI Providers, Chat, and Multimodal Models

Friday includes Web Chat, and the same model layer is used by workflows, technical plan generation, code analysis, and agent tools. You configure the relevant Provider key or service URL in the UI.

Current provider support:

| Provider | Use |
| --- | --- |
| Anthropic Claude | Claude models, Claude Code execution, planning, code analysis, and review. |
| OpenAI Responses API | OpenAI’s newer Responses API for chat, reasoning, and tool use. |
| OpenAI Chat Completions | Chat Completions compatible models and gateways. |
| Google Gemini | Gemini models, reasoning, and vision-capable workflows. |
| Ollama | Local or private models for internal experiments and lightweight use cases. |

Friday tracks model input modalities. The Web Chat image path is already implemented for PNG, JPEG, GIF, and WebP uploads. When the selected model supports vision input, Friday can send images as part of a multimodal message. Image, reasoning, streaming, and tool-calling support ultimately depends on the Provider and model you choose.

## Quick Start

You only need Docker, Docker Compose v2, and Git.

1. Initialize the local environment:

   ```bash
   scripts/setup.sh
   ```

   This prepares the local configuration and data directories. You do not need to build images yourself.

2. Start Friday:

   ```bash
   docker compose up -d
   ```

   Compose starts Web, Server, Runner, PostgreSQL, Redis, and Qdrant.

3. Open the Web app:

   | Surface | URL |
   | --- | --- |
   | Friday Web | <http://localhost:10240> |
   | API docs | <http://localhost:10240/docs> |

4. Configure an AI Provider:

   Add Anthropic, OpenAI, Gemini, or Ollama credentials in the UI. After this, Web Chat, technical plan generation, workflow AI nodes, and agent tools can call models.

5. Connect and index repositories:

   Connect GitHub / GitLab repositories, choose the default branch, and build the code index. Chat, Skill, Graph RAG, technical plans, and code execution all depend on this repository context.

6. Optional: connect Feishu:

   If your team uses Feishu, bind Feishu Project, Docs folders, bots, webhooks, and relevant fields. Requirements, approvals, notifications, and result writeback will then live in Feishu.

7. Run the first flow:

   Ask Friday Web Chat a question about an indexed repository, or trigger the full “plan -> human confirmation -> Claude Code execution -> PR / MR” pipeline from a Feishu work item or workflow template.

8. Optional: use the Friday Skill in your IDE:

   ```bash
   npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent
   ```

   Then create an Access Token on the Profile page and run `npx -y @friday-ai/mcp init` as shown on the dashboard. Cursor / Claude Code / Codex can then call Friday's code intelligence and execution tools directly.

## Docs

| Document | Covers |
| --- | --- |
| [Quick Start](docs/guide/quick-start.md) | Local deployment, first project setup, and workflow testing. |
| [Workflow Guide](docs/guide/workflows.md) | Workflow nodes, triggers, execution records, and debugging. |
| [Admin Guide](docs/guide/admin.md) | Users, permissions, OIDC, runners, and operational settings. |
| [Friday Codebase Agent](docs/guide/friday-codebase-agent.md) | Agent Skill, MCP server, Graph RAG analysis, and MR creation. |
| [Code Intelligence](docs/codegraph.md) | Graph RAG, cross-repo API links, Galaxy graph, and MCP tools. |
| [API Reference](docs/api/index.md) | REST API documentation. |
| [Task Runner](task/README.md) | Claude Agent SDK / Claude Code task container. |
| [Chinese README](README.md) | Chinese README. |

## License

Friday AI is released under the [MIT License](LICENSE).
