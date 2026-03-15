import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatusBadge from '~/components/common/StatusBadge.vue'
describe('StatusBadge', => {
 it('should render running execution status with correct label', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'running' },
 })
 expect(wrapper.text).toContain('运行中')
 })
 it('should render completed execution status', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'completed' },
 })
 expect(wrapper.text).toContain('已完成')
 })
 it('should hide label when showLabel is false', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'running', showLabel: false },
 })
 expect(wrapper.text).not.toContain('运行中')
 })
 it('should hide icon when showIcon is false', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'running', showIcon: false },
 })
 // 图标 span 不应该存在
 const iconSpan = wrapper.findAll('span').filter(s => s.classes.some(c => c.includes('icon-[')))
 expect(iconSpan.length).toBe(0)
 })
 it('should apply sm size classes', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'running', size: 'sm' },
 })
 expect(wrapper.html).toContain('text-[10px]')
 })
 it('should apply lg size classes', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'running', size: 'lg' },
 })
 expect(wrapper.html).toContain('text-sm')
 })
 it('should render runner status', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'runner', status: 'online' },
 })
 expect(wrapper.text).toContain('在线')
 })
 it('should render fallback for unknown status', => {
 const wrapper = mount(StatusBadge, {
 props: { type: 'execution', status: 'some_unknown' },
 })
 expect(wrapper.text).toContain('some_unknown')
 })
})
