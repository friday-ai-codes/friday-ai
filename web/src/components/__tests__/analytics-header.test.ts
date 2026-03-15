import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AnalyticsPage from '~/pages/analytics/index.vue'
// Mock PageHeader and TimeRangeSelector
vi.mock('~/components/common/PageHeader.vue', => ({
 default: {
 name: 'PageHeader',
 props: ['icon', 'iconGradient', 'iconColor', 'title', 'description'],
 template: '<div class="page-header"><slot name="actions" /></div>',
 },
}))
vi.mock('~/components/analytics/TimeRangeSelector.vue', => ({
 default: {
 name: 'TimeRangeSelector',
 props: ['modelValue'],
 template: '<div class="time-range-selector" />',
 },
}))
describe('Analytics Page Header', => {
 const globalConfig = {
 stubs: {
 PageContainer: { template: '<div><slot /></div>' },
 KpiCards: true,
 TrendChart: true,
 DurationDistribution: true,
 TokenCostChart: true,
 NodePerformanceTable: true,
 },
 }
 it('should use PageHeader component with correct props', => {
 const wrapper = mount(AnalyticsPage, { global: globalConfig })
 const header = wrapper.findComponent({ name: 'PageHeader' })
 expect(header.exists).toBe(true)
 expect(header.props('icon')).toBe('lucide--bar-chart-3')
 expect(header.props('title')).toBe('执行分析')
 expect(header.props('description')).toBe('工作流执行健康状况、性能趋势和成本消耗')
 })
 it('should render TimeRangeSelector in #actions slot', => {
 const wrapper = mount(AnalyticsPage, { global: globalConfig })
 const header = wrapper.findComponent({ name: 'PageHeader' })
 const timeSelector = header.findComponent({ name: 'TimeRangeSelector' })
 expect(timeSelector.exists).toBe(true)
 })
})
