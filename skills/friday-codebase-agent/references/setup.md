# Friday 配置与排障

## 配置解析优先级

`@friday-ai/mcp` 按以下顺序解析配置，env 与文件可混合（各字段独立取第一个非空值）：

1. 环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN`
2. 用户级配置文件 `~/.friday/config.json`：

```json
{
  "baseUrl": "https://friday.example.com",
  "accessToken": "<PAT>"
}
```

`baseUrl` 必须是 http/https，尾部斜杠会被自动去除。

## 创建访问令牌（PAT）

1. 登录 Friday Web 控制台（内网地址，默认端口 10240）。
2. 右上角头像 → 个人资料。
3. 「访问令牌」区域 → 创建令牌。
4. **明文只显示一次**，立即复制。服务端只存哈希，丢失只能重建。

令牌代表用户本人身份，所有工具调用都会以该用户名义记入 Friday 审计（Interaction Ledger）。

## init 命令详解

```bash
npx -y @friday-ai/mcp init --base-url <地址> --token <PAT>
```

行为：规范化地址 → 写 `~/.friday/config.json`（目录 0700、文件 0600）→ 请求 `{baseUrl}/health` 验证连通。

健康检查失败不会阻止写入（适配"先配置、后连 VPN"的场景），但要提醒用户确认网络可达。

验证当前配置（不回显令牌）：

```bash
npx -y @friday-ai/mcp doctor
```

## 各宿主 MCP 注册

### Claude Code

```bash
claude mcp add friday -- npx -y @friday-ai/mcp
# 校验
claude mcp list
```

### Cursor

项目级 `.cursor/mcp.json`（或全局 `~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "friday": {
      "command": "npx",
      "args": ["-y", "@friday-ai/mcp"]
    }
  }
}
```

写入后重载窗口（Cmd+Shift+P → Reload Window），在 MCP 设置面板确认 `friday` 状态为绿色。

### Codex

`~/.codex/config.toml`：

```toml
[mcp_servers.friday]
command = "npx"
args = ["-y", "@friday-ai/mcp"]
```

### 内网无法访问 npm registry 时

从源码本地构建并让 MCP 配置直指产物：

```bash
git clone https://github.com/friday-ai-codes/friday-ai.git
cd friday-ai/mcp && pnpm install && pnpm build
```

mcp.json 改为：

```json
{
  "mcpServers": {
    "friday": {
      "command": "node",
      "args": ["/绝对路径/friday-ai/mcp/dist/cli.js"]
    }
  }
}
```

## 排障表

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 工具返回"Friday MCP 未配置" | env 与配置文件都缺 | 跑 `init`；或检查 `~/.friday/config.json` 是否为合法 JSON |
| `init` 提示连通性异常 | 地址错误 / 未连 VPN / 端口未开 | 浏览器访问 `{baseUrl}/health` 验证；确认是 Web 端口（默认 10240）而非 API 裸端口 |
| 401 / 403 | 令牌失效、被吊销或粘贴不完整 | 重建 PAT，重跑 `init` |
| MCP 面板里 friday 启动失败 | npx 拉包失败（内网） | 用上方"从源码本地构建"方式 |
| 响应"不是 JSON" | baseUrl 指向了网关 / 登录门户 | 确认 baseUrl 是 Friday 本体地址，路径 `/api/mcp/tools/...` 可直达 |
| 仓库未索引 | 仓库刚接入未建索引 | Friday Web → 仓库页 → 建立索引，等待完成后重试 |
