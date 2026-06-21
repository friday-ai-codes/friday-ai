/**
 * 生成 URL 安全的飞书事件触发端点 token（前端版）。
 *
 * 与后端 `secrets.token_urlsafe(24)` 对齐：24 字节随机 → base64url（无填充），
 * 字符集 `[A-Za-z0-9_-]`，长度 32。用于飞书事件触发节点拖入画布时即时生成专属
 * 端点，无需等保存；后端在同步触发器时会校验并采纳合法且唯一的该 token。
 */
export function generateEndpointToken(): string {
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  let binary = ''
  for (const b of bytes) {
    binary += String.fromCharCode(b)
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}
