/**
 * ECharts 按需引入配置。
 *
 * 使用 tree-shaking 控制包体积，仅引入实际使用的图表类型和组件。
 */
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
 GridComponent,
 TooltipComponent,
 LegendComponent,
 DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
// 注册 ECharts 组件
use([
 CanvasRenderer,
 LineChart,
 BarChart,
 GridComponent,
 TooltipComponent,
 LegendComponent,
 DataZoomComponent,
])
export { VChart }
