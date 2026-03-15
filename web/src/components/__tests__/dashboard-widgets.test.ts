import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardKpiCards from '~/components/dashboard/DashboardKpiCards.vue'
import DashboardQuickActions from '~/components/dashboard/DashboardQuickActions.vue'
import DashboardRecentActivity from '~/components/dashboard/DashboardRecentActivity.vue'
describe('DashboardKpiCards', => {
 const stats = [
 { title: '项目总数', value: 10, icon: 'lucide--folder-git-2', statIconClass: 'stat-icon-primary', link: '/projects' },
 { title: '执行总数', value: 25, icon: 'lucide--layers', statIconClass: 'stat-icon-violet', link: '/executions' },
 ]
 it('should render correct number of StatCard components', => {
 const wrapper = mount(DashboardKpiCards, {
 props: { stats, loading: false },
 global: { stubs: { StatCard: true, RouterLink: true } },
 })
 expect(wrapper.findAllComponents({ name: 'StatCard' })).toHaveLength(stats.length)
 })
 it('should pass loading prop to StatCard', => {
 const wrapper = mount(DashboardKpiCards, {
 props: { stats, loading: true },
 global: { stubs: { StatCard: true, RouterLink: true } },
 })
 const cards = wrapper.findAllComponents({ name: 'StatCard' })
 cards.forEach((card) => {
 expect(card.props('loading')).toBe(true)
 })
 })
})
describe('DashboardQuickActions', => {
 const actions = [
 { icon: 'lucide--plus', title: '新建项目', description: '创建新的开发项目', link: '/projects/new', iconBg: 'stat-icon-primary' },
 { icon: 'lucide--workflow', title: '工作流管理', description: '编排自动化流程', link: '/workflows', iconBg: 'stat-icon-violet' },
 { icon: 'lucide--play-circle', title: '执行监控', description: '查看运行状态', link: '/executions', iconBg: 'stat-icon-amber' },
 ]
 it('should render correct number of quick action items', => {
 const wrapper = mount(DashboardQuickActions, {
 props: { actions },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.findAll('router-link-stub')).toHaveLength(actions.length)
 })
 it('should display action titles', => {
 const wrapper = mount(DashboardQuickActions, {
 props: { actions },
 global: {
 stubs: { RouterLink: { template: '<a><slot /></a>' } },
 },
 })
 actions.forEach((action) => {
 expect(wrapper.text).toContain(action.title)
 })
 })
})
describe('DashboardRecentActivity', => {
 const executions = [
 {
 id: '1',
 workflow: 'w1',
 workflow_name: '测试工作流',
 task: null,
 status: 'completed',
 trigger_type: 'manual',
 triggered_by: null,
 triggered_by_name: null,
 trigger_data: {},
 trigger_log_id: null,
 resumed_from: null,
 workflow_definition: null,
 context: {},
 input_data: {},
 output_data: {},
 error_message: '',
 error_node_id: null,
 total_nodes: 3,
 completed_nodes: 3,
 failed_nodes: 0,
 skipped_nodes: 0,
 node_executions:,
 duration: 120,
 progress: 100,
 created_at: '2026-03-16T10:00:00Z',
 started_at: '2026-03-16T10:00:00Z',
 completed_at: '2026-03-16T10:02:00Z',
 timeout_at: null,
 },
 ]
 it('should show loading skeleton when loading is true', => {
 const wrapper = mount(DashboardRecentActivity, {
 props: { executions:, loading: true },
 global: { stubs: { RouterLink: true, StatusBadge: true } },
 })
 expect(wrapper.findAll('.animate-pulse').length).toBeGreaterThan(0)
 })
 it('should show empty state when no executions and not loading', => {
 const wrapper = mount(DashboardRecentActivity, {
 props: { executions:, loading: false },
 global: { stubs: { RouterLink: true, StatusBadge: true } },
 })
 expect(wrapper.text).toContain('暂无执行记录')
 })
 it('should render execution list when executions provided', => {
 const wrapper = mount(DashboardRecentActivity, {
 props: { executions, loading: false },
 global: {
 stubs: {
 RouterLink: { template: '<a><slot /></a>' },
 StatusBadge: true,
 },
 },
 })
 expect(wrapper.text).toContain('测试工作流')
 })
})
