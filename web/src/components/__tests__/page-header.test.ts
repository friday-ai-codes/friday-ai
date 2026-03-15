import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageHeader from '~/components/common/PageHeader.vue'
describe('PageHeader', => {
 it('should render title text', => {
 const wrapper = mount(PageHeader, {
 props: { icon: 'lucide--folder-git-2', title: '项目管理' },
 })
 expect(wrapper.text).toContain('项目管理')
 })
 it('should render description when provided', => {
 const wrapper = mount(PageHeader, {
 props: {
 icon: 'lucide--folder-git-2',
 title: '项目管理',
 description: '管理您的 Git 仓库项目',
 },
 })
 expect(wrapper.find('p').exists).toBe(true)
 expect(wrapper.text).toContain('管理您的 Git 仓库项目')
 })
 it('should not render description when not provided', => {
 const wrapper = mount(PageHeader, {
 props: { icon: 'lucide--folder-git-2', title: '项目管理' },
 })
 expect(wrapper.find('p').exists).toBe(false)
 })
 it('should render actions slot content', => {
 const wrapper = mount(PageHeader, {
 props: { icon: 'lucide--folder-git-2', title: '项目管理' },
 slots: { actions: '<button>新建</button>' },
 })
 expect(wrapper.text).toContain('新建')
 })
 it('should render title-suffix slot content', => {
 const wrapper = mount(PageHeader, {
 props: { icon: 'lucide--folder-git-2', title: '项目管理' },
 slots: { 'title-suffix': '<span class="badge">5</span>' },
 })
 expect(wrapper.find('.badge').exists).toBe(true)
 })
})
