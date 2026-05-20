/**
 * Phase：RepoMultiSelector.vue 单元测试。
 *
 * Open Question #3 决议：shadcn-vue Command 底层 cmdk-vue 依赖 DOM API
 * 在 jsdom 下不稳定，本 spec 使用 stub 替代真实 Command 渲染，专注组件
 * 业务语义（过滤 / 多选 / disabled / 上限 / 推荐预填 / confirm emit）。
 */
import type { RepoSelectableItem } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import RepoMultiSelector from '../RepoMultiSelector.vue'
function makeRepos(n: number): RepoSelectableItem {
 return Array.from({ length: n }, (_, i) => ({
 id: `r${i + 1}`,
 name: `repo-${i + 1}`,
 description: `描述 ${i + 1}`,
 }))
}
// --- stubs：shadcn-vue Command / Button / Checkbox / Badge / Tooltip ---
const StubCommand = defineComponent({
 name: 'Command',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'cmd' }, slots.default?.)
 },
})
const StubCommandInput = defineComponent({
 name: 'CommandInput',
 props: ['modelValue', 'placeholder'],
 emits: ['update:modelValue'],
 setup(props, { emit }) {
 return => h('input', {
 'data-test': 'cmd-input',
 'value': props.modelValue,
 'placeholder': props.placeholder,
 'onInput': (e: Event) =>
 emit('update:modelValue', (e.target as HTMLInputElement).value),
 })
 },
})
const StubCommandList = defineComponent({
 name: 'CommandList',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'cmd-list' }, slots.default?.)
 },
})
const StubCommandEmpty = defineComponent({
 name: 'CommandEmpty',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'cmd-empty' }, slots.default?.)
 },
})
const StubCommandGroup = defineComponent({
 name: 'CommandGroup',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'cmd-group' }, slots.default?.)
 },
})
const StubCommandItem = defineComponent({
 name: 'CommandItem',
 props: ['value', 'disabled'],
 emits: ['select'],
 setup(props, { slots, emit }) {
 return => h('div', {
 'data-test': 'cmd-item',
 'data-value': props.value,
 'data-disabled': props.disabled ? '1': '0',
 'onClick': => {
 if (!props.disabled)
 emit('select', props.value)
 },
 }, slots.default?.)
 },
})
const StubButton = defineComponent({
 name: 'Button',
 props: ['disabled'],
 emits: ['click'],
 setup(props, { slots, emit }) {
 return => h('button', {
 'data-test': 'btn',
 'disabled': props.disabled || false,
 'onClick': => emit('click'),
 }, slots.default?.)
 },
})
const StubCheckbox = defineComponent({
 name: 'Checkbox',
 props: ['modelValue', 'disabled'],
 setup(props) {
 return => h('input', {
 'type': 'checkbox',
 'data-test': 'cb',
 'checked': !!props.modelValue,
 'disabled': props.disabled || false,
 })
 },
})
const StubBadge = defineComponent({
 name: 'Badge',
 setup(_, { slots }) {
 return => h('span', { 'data-test': 'badge' }, slots.default?.)
 },
})
const StubTooltipProvider = defineComponent({
 name: 'TooltipProvider',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'tt-provider' }, slots.default?.)
 },
})
const StubTooltip = defineComponent({
 name: 'Tooltip',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'tt' }, slots.default?.)
 },
})
const StubTooltipTrigger = defineComponent({
 name: 'TooltipTrigger',
 setup(_, { slots }) {
 return => h('span', { 'data-test': 'tt-trigger' }, slots.default?.)
 },
})
const StubTooltipContent = defineComponent({
 name: 'TooltipContent',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'tt-content' }, slots.default?.)
 },
})
const globalStubs = {
 Command: StubCommand,
 CommandInput: StubCommandInput,
 CommandList: StubCommandList,
 CommandEmpty: StubCommandEmpty,
 CommandGroup: StubCommandGroup,
 CommandItem: StubCommandItem,
 Button: StubButton,
 Checkbox: StubCheckbox,
 Badge: StubBadge,
 TooltipProvider: StubTooltipProvider,
 Tooltip: StubTooltip,
 TooltipTrigger: StubTooltipTrigger,
 TooltipContent: StubTooltipContent,
}
function mountSelector(props: any) {
 return mount(RepoMultiSelector, {
 props,
 global: { stubs: globalStubs },
 })
}
describe('repoMultiSelector', => {
 it('renders all repositories from props', => {
 const repos = makeRepos(3)
 const wrapper = mountSelector({ repositories: repos, modelValue: })
 for (const r of repos)
 expect(wrapper.text).toContain(r.name)
 })
 it('emits update:modelValue when item clicked', async => {
 const repos = makeRepos(2)
 const wrapper = mountSelector({ repositories: repos, modelValue: })
 const items = wrapper.findAll('[data-test="cmd-item"]')
 await items[0].trigger('click')
 expect(wrapper.emitted('update:modelValue')).toBeTruthy
 expect(wrapper.emitted('update:modelValue')![0][0]).toContain('r1')
 })
 it('filters list when search input changes', async => {
 const repos: RepoSelectableItem = [
 { id: 'a', name: 'alpha' },
 { id: 'b', name: 'beta' },
 ]
 const wrapper = mountSelector({ repositories: repos, modelValue: })
 const input = wrapper.find('[data-test="cmd-input"]')
 await input.setValue('alpha')
 expect(wrapper.text).toContain('alpha')
 expect(wrapper.text).not.toContain('beta')
 })
 it('does not emit update:modelValue when disabled item clicked', async => {
 const repos = makeRepos(2)
 const wrapper = mountSelector({
 repositories: repos,
 modelValue:,
 disabledIds: ['r1'],
 })
 const items = wrapper.findAll('[data-test="cmd-item"]')
 await items[0].trigger('click')
 expect(wrapper.emitted('update:modelValue')).toBeFalsy
 })
 it('disables unselected items when modelValue.length reaches maxSelectable', => {
 const repos = makeRepos(5)
 const wrapper = mountSelector({
 repositories: repos,
 modelValue: ['r1', 'r2', 'r3'],
 maxSelectable: 3,
 })
 expect(wrapper.text).toContain('已达上限 3 个仓库')
 })
 it('emits confirm with current ids when 确认编码 clicked', async => {
 const repos = makeRepos(2)
 const wrapper = mountSelector({ repositories: repos, modelValue: ['r1'] })
 const buttons = wrapper.findAll('button')
 const btn = buttons.find(b => b.text.includes('确认编码'))
 expect(btn).toBeTruthy
 await btn!.trigger('click')
 expect(wrapper.emitted('confirm')).toBeTruthy
 expect(wrapper.emitted('confirm')![0][0]).toEqual(['r1'])
 })
 it('merges recommendedIds into modelValue on mount', => {
 const repos = makeRepos(3)
 const wrapper = mountSelector({
 repositories: repos,
 modelValue:,
 recommendedIds: ['r1', 'r2'],
 })
 const emits = wrapper.emitted('update:modelValue')
 expect(emits).toBeTruthy
 expect(emits![0][0]).toEqual(['r1', 'r2'])
 })
})
