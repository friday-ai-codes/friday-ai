import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FilterBar from '~/components/common/FilterBar.vue'
describe('FilterBar', => {
 it('should render slot content', => {
 const wrapper = mount(FilterBar, {
 slots: { default: '<input placeholder="搜索..." />' },
 })
 expect(wrapper.find('input').exists).toBe(true)
 })
 it('should show clear button when showClear is true', => {
 const wrapper = mount(FilterBar, {
 props: { showClear: true },
 })
 expect(wrapper.text).toContain('清除筛选')
 })
 it('should not show clear button when showClear is false', => {
 const wrapper = mount(FilterBar, {
 props: { showClear: false },
 })
 expect(wrapper.text).not.toContain('清除筛选')
 })
 it('should emit clear event when clear button is clicked', async => {
 const wrapper = mount(FilterBar, {
 props: { showClear: true },
 })
 await wrapper.find('button').trigger('click')
 expect(wrapper.emitted('clear')).toBeTruthy
 })
})
