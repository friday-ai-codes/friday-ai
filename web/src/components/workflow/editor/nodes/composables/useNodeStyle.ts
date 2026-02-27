import { computed, type ComputedRef } from 'vue'
import type { NodeColorKey } from '../nodeVisuals'
export interface NodeStyleTokens {
 borderColor: string
 gradientFrom: string
 gradientTo: string
 iconBg: string
 iconColor: string
 ringColor: string
}
const COLOR_STYLES: Record<NodeColorKey, NodeStyleTokens> = {
 blue: {
 borderColor: 'border-blue-500/50',
 gradientFrom: 'from-blue-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-blue-500/20 to-cyan-400/10',
 iconColor: 'text-blue-500',
 ringColor: 'ring-blue-500/40',
 },
 green: {
 borderColor: 'border-emerald-500/50',
 gradientFrom: 'from-emerald-500',
 gradientTo: 'to-teal-400',
 iconBg: 'from-emerald-500/20 to-teal-400/10',
 iconColor: 'text-emerald-500',
 ringColor: 'ring-emerald-500/40',
 },
 purple: {
 borderColor: 'border-violet-500/50',
 gradientFrom: 'from-violet-500',
 gradientTo: 'to-purple-400',
 iconBg: 'from-violet-500/20 to-purple-400/10',
 iconColor: 'text-violet-500',
 ringColor: 'ring-violet-500/40',
 },
 orange: {
 borderColor: 'border-amber-500/50',
 gradientFrom: 'from-amber-500',
 gradientTo: 'to-orange-400',
 iconBg: 'from-amber-500/20 to-orange-400/10',
 iconColor: 'text-amber-500',
 ringColor: 'ring-amber-500/40',
 },
}
const FALLBACK = COLOR_STYLES.blue
export function useNodeStyle(colorKey: string): ComputedRef<NodeStyleTokens> {
 return computed( => COLOR_STYLES[colorKey as NodeColorKey] ?? FALLBACK)
}
