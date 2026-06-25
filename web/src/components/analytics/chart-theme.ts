/**
 * Analytics ECharts 浅色主题片段。
 *
 * 旧实现各图表内联了一套深色坐标轴配色（#374151 / #1f2937），在浅色界面上
 * 对比度失衡。此处统一为与 Tailwind slate 色板对齐的浅色样式，供各图表复用。
 */

export const axisLineStyle = { lineStyle: { color: 'rgba(148, 163, 184, 0.35)' } }

export const axisLabelStyle = { color: '#64748b', fontSize: 11 }

export const splitLineStyle = { lineStyle: { color: 'rgba(148, 163, 184, 0.18)', type: 'dashed' as const } }

/*
 * tooltip 主题感知：ECharts 默认 tooltip 以 HTML DOM 渲染，内联样式中的 CSS 变量
 * 会在浏览器侧按当前主题（light/.dark）解析，因此直接引用 Tailwind 4 `@theme`
 * 暴露的设计令牌即可在明暗两套主题下保持对比度，无需在各图表内做主题分支。
 * 旧实现硬编码白底深字（white-on-light），在深色画布下对比度不足。
 */
export const tooltipStyle = {
  backgroundColor: 'var(--color-popover)',
  borderColor: 'var(--color-border)',
  borderWidth: 1,
  padding: [8, 12] as [number, number],
  textStyle: { color: 'var(--color-popover-foreground)', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 16px rgba(15, 23, 42, 0.18); border-radius: 8px;',
}

export const legendTextStyle = { color: '#64748b', fontSize: 12 }

export const chartGrid = { left: '2%', right: '3%', top: 40, bottom: '3%', containLabel: true }
