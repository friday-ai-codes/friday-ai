/**
 * 跨环境 UUID v4 生成器。
 *
 * `crypto.randomUUID` 仅在安全上下文（HTTPS 或 localhost）可用；
 * 通过 HTTP + IP 访问时该方法不存在，会抛出
 * "crypto.randomUUID is not a function"。
 *
 * 降级顺序：
 *   1. crypto.randomUUID（安全上下文原生实现）
 *   2. crypto.getRandomValues（任意上下文均可用，手工拼装 v4）
 *   3. Math.random（极端兜底，无 crypto 时）
 */
export function randomUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function')
    return crypto.randomUUID()

  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0F) | 0x40
    bytes[8] = (bytes[8] & 0x3F) | 0x80
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0'))
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
  }

  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
