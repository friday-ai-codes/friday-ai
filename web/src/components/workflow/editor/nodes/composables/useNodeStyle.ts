import type { ComputedRef } from 'vue'
import type { NodeColorKey } from '../nodeVisuals'
import { computed } from 'vue'
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
 borderColor: 'border-primary/50',
 gradientFrom: 'from-teal-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-primary/20 to-primary/10',
 iconColor: 'text-primary',
 ringColor: 'ring-primary/40',
 },
 green: {
 borderColor: 'border-primary/50',
 gradientFrom: 'from-teal-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-primary/20 to-primary/10',
 iconColor: 'text-primary',
 ringColor: 'ring-primary/40',
 },
 purple: {
 borderColor: 'border-primary/50',
 gradientFrom: 'from-teal-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-primary/20 to-primary/10',
 iconColor: 'text-primary',
 ringColor: 'ring-primary/40',
 },
 orange: {
 borderColor: 'border-primary/50',
 gradientFrom: 'from-teal-500',
 gradientTo: 'to-cyan-400',
 iconBg: 'from-primary/20 to-primary/10',
 iconColor: 'text-primary',
 ringColor: 'ring-primary/40',
 },
}
const FALLBACK = COLOR_STYLES.blue
export function useNodeStyle(colorKey: string): ComputedRef<NodeStyleTokens> {
 return computed( => COLOR_STYLES[colorKey as NodeColorKey] ?? FALLBACK)
}
