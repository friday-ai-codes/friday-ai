<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/public/logo-dark.svg">
    <img src="web/public/logo.svg" alt="Friday AI" width="420">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/friday-ai-codes/friday-ai/actions/workflows/ci.yaml">
    <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/friday-ai-codes/friday-ai/ci.yaml?branch=main&label=CI&style=for-the-badge&logo=githubactions&logoColor=white&labelColor=1F1E1C">
  </a>
  <a href="https://codecov.io/gh/friday-ai-codes/friday-ai">
    <img alt="Coverage" src="https://img.shields.io/codecov/c/github/friday-ai-codes/friday-ai?style=for-the-badge&logo=codecov&logoColor=white&labelColor=1F1E1C&label=coverage">
  </a>
  <a href="https://github.com/friday-ai-codes/friday-ai/actions/workflows/ci.yaml">
    <img alt="E2E" src="https://img.shields.io/badge/E2E-Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white&labelColor=1F1E1C">
  </a>
  <a href="https://github.com/friday-ai-codes/friday-ai/releases">
    <img alt="Latest Release" src="https://img.shields.io/github/v/release/friday-ai-codes/friday-ai?include_prereleases&label=release&style=for-the-badge&logo=github&logoColor=white&labelColor=1F1E1C">
  </a>
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/friday-ai-codes/friday-ai?style=for-the-badge&labelColor=1F1E1C&color=20a66a">
  </a>
  <a href="https://github.com/friday-ai-codes/friday-ai/stargazers">
    <img alt="Stars" src="https://img.shields.io/github/stars/friday-ai-codes/friday-ai?style=for-the-badge&logo=github&logoColor=white&labelColor=1F1E1C&color=f5a623">
  </a>
</p>

<p align="center">
  <a href="README.md">中文</a>
</p>

Friday AI is an open-source AI development automation platform. In one sentence: **it turns requirements in Feishu into reviewable code PRs, automatically**.

When a requirement comes in, Friday reads it, digs through the codebase, and drafts a technical plan. After the team confirms the plan, it has AI write the code in an isolated environment, open a PR, and report every step back to Feishu. Humans make the calls; Friday does the legwork.

<p align="center">
  <a href="#what-problem-it-solves">What Problem It Solves</a>
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

## What Problem It Solves

Picture a scene that plays out in engineering teams every day:

A product manager creates a work item in Feishu Project — “add a coupon entry to the cart page” — attaches a requirement doc, and drags the status to “ready for development”. What happens next? Someone has to read the doc, dig through the code, estimate the scope, write a technical plan, then implement, open a PR, and find a reviewer. Every step waits on a person, and the information is scattered across docs, group chats, and the repository.

With Friday connected, the chain becomes:

1. Friday detects the status change and pulls the requirement description, comments, and linked documents;
2. It searches the indexed repositories for relevant files, functions, and call relationships;
3. It generates a technical plan and writes it back to Feishu fields or docs;
4. The tech lead reviews the plan and clicks “confirm” on a Feishu card;
5. Friday dispatches Claude Code to modify code, run code review, and prepare the branch inside an isolated container;
6. The PR link, review summary, and execution record are posted back to the Feishu group.

Humans stay at the checkpoints: plans need confirmation, code needs review. What Friday takes over is the grunt work in between — reading docs, digging through code, and relaying status updates.

Execution is not a black box either. Branches, commits, PRs / MRs, code review output, retrieval evidence, model usage, and recovery points are all recorded on the same trail. The team does not get a vague “AI finished” message; it gets an engineering process that can be reviewed, questioned, and continued.

Friday already integrates deeply with Feishu, but it is not built only for Feishu: the core is workflow orchestration, code intelligence, and auditable agent execution, so more collaboration entrypoints can be added later.

## Glossary

These terms come up throughout this document:

| Term | Meaning |
| --- | --- |
| PR / MR | Pull Request / Merge Request — a request to have code changes reviewed and merged. GitHub calls it a PR, GitLab calls it an MR. |
| Claude Code | Anthropic's AI coding tool. Friday uses it to actually write the code. |
| Graph RAG | Friday's code retrieval approach: find relevant code by semantics first, then follow call relationships to pull in upstream and downstream code. |
| Runner | Friday's task scheduler. It creates isolated Docker containers where all AI coding takes place. |
| Workflow | The visual orchestration of “trigger → fetch requirement → generate plan → wait for confirmation → write code → notify”, built by drag-and-drop in the web UI. |
| Agent Skill / MCP | The integration path that lets local AI assistants like Cursor and Claude Code call Friday's code index and execution capabilities. |

## How It Works

![Friday AI workflow](docs/public/readme/how-it-works.png)

The system has four parts: the Web console (dashboard, flow editor, chat), the Server (workflow engine and code intelligence), the Runner (schedules isolated containers), and the Task executor (runs Claude Code inside the container). Requirements enter from Feishu or the web and move along the workflow you composed; every node's inputs, outputs, model usage, and recovery points are recorded and can be revisited at any time.

## What It Can Do

| Scenario | Example | How Friday moves it forward |
| --- | --- | --- |
| Requirements enter from Feishu | A work item moves to “ready for development” and a requirement doc is linked in a comment. | Listen to the Feishu event, fetch work item context and docs, generate a plan, wait for approval, and dispatch coding work. |
| Plans need review first | A tech lead wants risks, affected areas, and test suggestions before any code changes. | Use Graph RAG to gather code evidence, generate a plan, write it back to Feishu, and wait for card or field confirmation. |
| Cross-repository API changes | A frontend page changes an API parameter while backend handlers, types, and tests live elsewhere. | Connect semantic retrieval, code graph expansion, and cross-repo API links to create a repository task matrix. |
| Ongoing group collaboration | Execution needs a missing field, screenshot, branch confirmation, or result notification. | Feishu bots send question cards, approval cards, review cards, and coding result updates in group or p2p chats. |
| Users ask the codebase directly | “Where does this payment callback enter?” or “Who calls this component?” | Friday Web Chat can call retrieval and code browsing tools over indexed repositories. |
| Agent Skill uses Friday as a backend | You code in Cursor / Claude Code / Codex and want the assistant to use Friday’s code index, Graph RAG, and execution tools. | Install the Skills with `npx @friday-ai-codes/skills` and use `@friday-ai-codes/mcp` for discovery, analysis, planning, execution, and MR creation. |
| AI code review | Claude Code has produced a branch and the team wants an automatic review plus a readable summary. | Workflows can run `ai_code_review`, then write review output, branch summaries, and PR / MR details back to Feishu. |

## Deep Feishu Integration, Not Feishu Lock-In

Friday integrates with Feishu at several levels. It is much more than notifications.

| Surface | Current capability |
| --- | --- |
| Feishu Project | Space binding, plugin credentials, webhook tokens, work item details, fields, relations, comments, status transitions, and trigger logs. |
| Feishu Docs | Detect document links, read cloud docs, convert Feishu blocks to Markdown, write Markdown back to docs, and handle tables, code blocks, and quotes. |
| Feishu Bot / IM | Send text and cards, update cards, read group history, download message resources, check or add the bot to chats, and handle group or p2p conversations. |
| Feishu card callbacks | Approval, plan confirmation, clarification, code review, and coding result cards all have callback handlers. |
| Feishu workflow nodes | `feishu_event_trigger`, `fetch_work_item`, `wait_feishu_field`, `notify_feishu`, `fetch_group_chat`, and `join_group_chat` can be dragged directly onto the workflow canvas. |
| MCP / Agent tools | `get_feishu_work_item_context` aggregates work items, relations, comments, and docs; `create_feishu_technical_plan` combines that context with code evidence and writes a plan back. |

Feishu is the most polished collaboration entrypoint today. Underneath, Friday is still built as “collaboration entrypoint + workflow + code intelligence + Runner,” so adding other project-management, document, IM, or automation systems does not require replacing the main pipeline.

## Agent Skill and Code Indexing

If you write code in Cursor / Claude Code / Codex, Friday can also serve as their codebase backend: once a repository is indexed in Friday, your local AI assistant can query code relationships across the entire repository (or several repositories), instead of guessing context from the few files open in the current window.

Three steps to connect:

1. Create an Access Token: Friday Web console → Profile → Access Tokens → Create (the plaintext is shown only once).

2. Configure the connection (interactive wizard: credentials → MCP registration → latency check → capability demo):

   ```bash
   npx -y @friday-ai-codes/mcp setup
   ```

3. Install the Skills (interactive wizard; auto-detects Claude Code, Cursor, Codex, and more; ships 4 skills covering requirement routing through MR creation):

   ```bash
   npx @friday-ai-codes/skills          # installs into the current project by default
   ```

   In interactive mode the installer also checks the connection config after installing, and hands off to the step-2 wizard if it is missing — either order closes the loop.

The assistant can then use the same index for repository discovery, Graph RAG analysis, coding plans, plan revisions, remote execution, branch summaries, and MR creation. Web users get the visual workflow; local IDE users get callable code-intelligence tools. Both paths share the same evidence and audit trail. See the [Friday Codebase Agent guide](docs/guide/friday-codebase-agent.md).

## What Makes Graph RAG Different

A quick primer on RAG: it is the common practice of “retrieve relevant content first, then let the model answer”, so the AI speaks from your code and docs instead of guessing from memory. But code is not like prose — a function's impact hides in its call chain, and “find similar text” alone often misses it.

Plain RAG, plain graphs, and Friday's Graph RAG solve different parts of the problem:

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

1. Clone the repository and initialize the local environment:

   ```bash
   git clone https://github.com/friday-ai-codes/friday-ai.git
   cd friday-ai
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

   Create an Access Token on the Profile page first, then connect with two commands (interactive wizards):

   ```bash
   npx -y @friday-ai-codes/mcp setup    # configure connection + register MCP + latency check
   npx @friday-ai-codes/skills          # install skills into the current project's agent config
   ```

   Cursor / Claude Code / Codex can then call Friday's code intelligence and execution tools directly.

## Docs

| Document | Covers |
| --- | --- |
| [Quick Start](docs/guide/quick-start.md) | Local deployment, first project setup, and workflow testing. |
| [Workflow Guide](docs/guide/workflows.md) | Workflow nodes, triggers, execution records, and debugging. |
| [Admin Guide](docs/guide/admin.md) | Users, permissions, OIDC, runners, and operational settings. |
| [Friday Codebase Agent](docs/guide/friday-codebase-agent.md) | Agent Skill, MCP server, Graph RAG analysis, and MR creation. |
| [Code Intelligence](docs/internals/code-intelligence.md) | Graph RAG, cross-repo API links, Galaxy graph, and MCP tools. |
| [Docs Site](https://friday-ai-codes.github.io/friday-ai/) | Full documentation site (deployment, internals, integrations, API). |
| [API Reference](docs/api/index.md) | REST API documentation. |
| [Task Runner](task/README.md) | Claude Agent SDK / Claude Code task container. |
| [Chinese README](README.md) | Chinese README. |

## Contributors

Thanks to everyone who has contributed — issues and PRs are always welcome.

<a href="https://github.com/friday-ai-codes/friday-ai/graphs/contributors">
  <img alt="Contributors" src="https://contrib.rocks/image?repo=friday-ai-codes/friday-ai" />
</a>

## Star History

<a href="https://www.star-history.com/#friday-ai-codes/friday-ai&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=friday-ai-codes/friday-ai&type=Date&theme=dark">
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=friday-ai-codes/friday-ai&type=Date">
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=friday-ai-codes/friday-ai&type=Date">
  </picture>
</a>

## License

Friday AI is released under the [MIT License](LICENSE).
