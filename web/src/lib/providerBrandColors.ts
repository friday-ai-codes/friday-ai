/**
 * Provider 品牌色 Token 文件（Phase Plan — ）
 *
 * 单一源真相：5 ProviderType × 3 字段 {bg, text, hex} 全覆盖。
 * 禁止在其他文件硬编码 Anthropic orange / OpenAI emerald / Gemini blue / Ollama slate
 * 的 Tailwind class 或 hex 值。
 *
 * 使用契约：
 * - TokenCostChart.vue 堆叠柱状图 itemStyle.color 从 .hex 注入
 * - KpiCards per-provider 卡片 icon 容器从 .bg / .text 注入
 * - ProviderHealthBadge / 其他 badge 组件按需引用
 *
 * 新增 Provider 时只改此文件，所有消费者自动更新。
 */
import type { ProviderType } from '~/types/providerCredential'
export interface ProviderBrandColor {
 bg: string // Tailwind 背景类（半透明，用于 badge / KPI 卡片背景片）
 text: string // Tailwind 文字类（深色，用于 badge 文字 / chart 图例文字）
 hex: string // 十六进制色值（ECharts itemStyle.color / 原生 canvas）
}
export const PROVIDER_BRAND_COLORS: Record<ProviderType, ProviderBrandColor> = {
 anthropic: { bg: 'bg-orange-500/20', text: 'text-orange-600', hex: '#f97316' },
 openai_responses: { bg: 'bg-emerald-500/20', text: 'text-emerald-600', hex: '#10b981' },
 openai_chat: { bg: 'bg-emerald-500/20', text: 'text-emerald-600', hex: '#10b981' },
 gemini: { bg: 'bg-blue-500/20', text: 'text-blue-600', hex: '#3b82f6' },
 ollama: { bg: 'bg-slate-500/20', text: 'text-slate-600', hex: '#64748b' },
}
/**
 * ECharts 堆叠柱状图用的 Provider 品牌 hex 数组（按字典序，与 堆叠顺序一致）。
 *
 * 顺序：anthropic → gemini → ollama → openai_chat → openai_responses
 */
export const PROVIDER_BRAND_HEX_ORDERED: string = [
 PROVIDER_BRAND_COLORS.anthropic.hex,
 PROVIDER_BRAND_COLORS.gemini.hex,
 PROVIDER_BRAND_COLORS.ollama.hex,
 PROVIDER_BRAND_COLORS.openai_chat.hex,
 PROVIDER_BRAND_COLORS.openai_responses.hex,
]
/** 未知 Provider 默认色（legacy data 或 Ollama 前置缺失场景 fallback）。 */
export const UNKNOWN_PROVIDER_COLOR: ProviderBrandColor = {
 bg: 'bg-slate-400/20',
 text: 'text-slate-500',
 hex: '#94a3b8',
}
/**
 * 获取 Provider 品牌色，未注册时回退到 unknown 灰。
 */
export function getProviderBrandColor(providerType: string | null | undefined): ProviderBrandColor {
 if (!providerType)
 return UNKNOWN_PROVIDER_COLOR
 return (PROVIDER_BRAND_COLORS as Record<string, ProviderBrandColor>)[providerType]
 ?? UNKNOWN_PROVIDER_COLOR
}
