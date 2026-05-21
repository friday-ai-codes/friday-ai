/**
 * Quick Task：parts 协议双轨期 feature flag。
 *
 * localStorage key: `chat-parts-protocol`
 * - `'new'`（默认）→ 消费新 part_* 事件，忽略旧 text_delta / tool_use_* / thinking
 * - `'legacy'` → 消费旧事件路径（v25 行为），忽略 part_* 事件
 *
 * 设计决策见 PLAN §D3 SSE 双轨期 dispatch 策略：
 * - 后端无条件双发（避免运维耦合）
 * - 前端按设备级 localStorage 灰度
 * - QA 可在浏览器 console 跑 `localStorage.setItem('chat-parts-protocol', 'legacy')` 后刷新即可降级
 *
 * 双轨期持续 1 个 checkpoint（v26.1）后，v27 删除旧事件 + 删除本 composable + 删除 legacy hydrate path。
 */
export const CHAT_PARTS_PROTOCOL_KEY = 'chat-parts-protocol'
export type ChatPartsProtocol = 'new' | 'legacy'
/**
 * 读 localStorage 拿当前协议；非浏览器环境（SSR / vitest happy-dom 未注入）走默认 `'new'`。
 *
 * 每次调用都重新读 —— 不缓存。便于测试用 `localStorage.setItem` 即时切换；
 * 生产环境 SSE 事件分发热路径每个 event 读 1 次 localStorage，开销可忽略。
 */
export function getChatPartsProtocol: ChatPartsProtocol {
 if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
 return 'new'
 }
 try {
 const value = window.localStorage.getItem(CHAT_PARTS_PROTOCOL_KEY)
 return value === 'legacy' ? 'legacy': 'new'
 }
 catch {
 // safari private mode 等 localStorage 抛错 case：兜底默认值，不阻断 dispatch
 return 'new'
 }
}
/**
 * Composable 形式（保持与项目其它 composable 命名风格一致）。
 *
 * 注意：返回的不是 ref / reactive；protocol 通过函数实时读 localStorage。
 * 大部分场景调用方只在 dispatch 时 inline 调一次 `getChatPartsProtocol` 即可，
 * 这里提供命名 wrapper 让外部代码可读性更好。
 */
export function useChatPartsProtocol {
 return {
 /** 读取当前协议（每次调用都重新读 localStorage） */
 getProtocol: getChatPartsProtocol,
 }
}
