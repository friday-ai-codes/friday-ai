import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatCard from '~/components/common/StatCard.vue'
describe('StatCard', => {
 it('should render title and value', => {
 const wrapper = mount(StatCard, {
 props: { title: '项目总数', value: 42, icon: 'lucide--folder-git-2' },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.text).toContain('项目总数')
 expect(wrapper.text).toContain('42')
 })
 it('should show loading state when loading is true', => {
 const wrapper = mount(StatCard, {
 props: { title: '项目总数', value: 42, icon: 'lucide--folder-git-2', loading: true },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.find('.animate-pulse').exists).toBe(true)
 expect(wrapper.text).not.toContain('42')
 })
 it('should render as RouterLink when to prop is provided', => {
 const wrapper = mount(StatCard, {
 props: { title: '项目总数', value: 42, icon: 'lucide--folder-git-2', to: '/projects' },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.find('router-link-stub').exists).toBe(true)
 })
 it('should render as div when no to prop', => {
 const wrapper = mount(StatCard, {
 props: { title: '项目总数', value: 42, icon: 'lucide--folder-git-2' },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.find('router-link-stub').exists).toBe(false)
 })
 it('should render trend when provided', => {
 const wrapper = mount(StatCard, {
 props: {
 title: '项目总数',
 value: 42,
 icon: 'lucide--folder-git-2',
 trend: { value: 12, direction: 'up' as const },
 },
 global: { stubs: { RouterLink: true } },
 })
 expect(wrapper.text).toContain('12%')
 })
})
