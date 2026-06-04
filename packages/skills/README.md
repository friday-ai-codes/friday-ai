# @friday-ai/skills
Friday AI skills for Codex.
## Install
Install every bundled Friday AI skill to Codex globally:
```bash
npx @friday-ai/skills
```
Equivalent explicit form:
```bash
npx @friday-ai/skills install
```
Install into the current project instead:
```bash
npx @friday-ai/skills install --project
```
Install one skill:
```bash
npx @friday-ai/skills install --skill friday-feishu-agent
```
List bundled skills:
```bash
npx @friday-ai/skills list
```
## Bundled Skills
- `friday-ai`: Friday AI setup, diagnosis, and workflow routing.
- `friday-codebase-agent`: repository coding workflows through Friday MCP tools.
- `friday-feishu-agent`: Feishu Project work item to technical plan, repo execution, PR/MR writeback, and learning cases.
## Publishing
Publish this package as a public scoped npm package:
```bash
cd packages/skills
npm publish --access public
```
The package includes a thin installer CLI that delegates to the public `skills` CLI using this package directory as a local skill catalog.
