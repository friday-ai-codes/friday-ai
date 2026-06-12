/**
 * Analytics ECharts 浅色主题片段。
 *
 * 旧实现各图表内联了一套深色坐标轴配色（#374151 / #1f2937），在浅色界面上
 * 对比度失衡。此处统一为与 Tailwind slate 色板对齐的浅色样式，供各图表复用。
 */

export const axisLineStyle = { lineStyle: { color: 'rgba(148, 163, 184, 0.35)' } }

export const axisLabelStyle = { color: '#64748b', fontSize: 11 }

export const splitLineStyle = { lineStyle: { color: 'rgba(148, 163, 184, 0.18)', type: 'dashed' as const } }

export const tooltipStyle = {
  backgroundColor: 'rgba(255, 255, 255, 0.98)',
  borderColor: 'rgba(148, 163, 184, 0.35)',
  borderWidth: 1,
  padding: [8, 12] as [number, number],
  textStyle: { color: '#0f172a', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 16px rgba(15, 23, 42, 0.1); border-radius: 8px;',
}

export const legendTextStyle = { color: '#64748b', fontSize: 12 }

export const chartGrid = { left: '2%', right: '3%', top: 40, bottom: '3%', containLabel: true }
