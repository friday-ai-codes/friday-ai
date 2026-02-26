import { computed, type ComputedRef } from 'vue'
export interface NodeStyleTokens {
 borderColor: string
 gradientFrom: string
 gradientTo: string
 iconBg: string
 ringColor: string
}
const CATEGORY_STYLES: Record<string, NodeStyleTokens> = {
 trigger: {
 borderColor: 'border-amber-500/50',
 gradientFrom: 'from-amber-500',
 gradientTo: 'to-orange-400',
 iconBg: 'from-amber-500/20 to-orange-400/10',
 ringColor: 'ring-amber-500/40',
 },
 action: {
 borderColor: 'border-emerald-500/50',
 gradientFrom: 'from-emerald-500',
 gradientTo: 'to-teal-400',
 iconBg: 'from-emerald-500/20 to-teal-400/10',
 ringColor: 'ring-emerald-500/40',
 },
 control: {
 borderColor: 'border-slate-500/50',
 gradientFrom: 'from-slate-500',
 gradientTo: 'to-gray-400',
 iconBg: 'from-slate-500/20 to-gray-400/10',
 ringColor: 'ring-slate-500/40',
 },
 integration: {
 borderColor: 'border-blue-500/50',
 gradientFrom: 'from-blue-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-blue-500/20 to-cyan-400/10',
 ringColor: 'ring-blue-500/40',
 },
 ai: {
 borderColor: 'border-violet-500/50',
 gradientFrom: 'from-violet-500',
 gradientTo: 'to-purple-400',
 iconBg: 'from-violet-500/20 to-purple-400/10',
 ringColor: 'ring-violet-500/40',
 },
}
const FALLBACK: NodeStyleTokens = {
 borderColor: 'border-gray-500/50',
 gradientFrom: 'from-gray-500',
 gradientTo: 'to-gray-400',
 iconBg: 'from-gray-500/20 to-gray-400/10',
 ringColor: 'ring-gray-500/40',
}
export function useNodeStyle(category: string): ComputedRef<NodeStyleTokens> {
 return computed( => CATEGORY_STYLES[category] ?? FALLBACK)
}
