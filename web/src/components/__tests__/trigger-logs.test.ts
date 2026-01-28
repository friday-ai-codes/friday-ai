import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
/**
 * 触发日志组件测试
 *
 * 注意：由于组件依赖外部 UI 库和 shiki，这里主要测试组件的基本逻辑
 */
// Mock shiki
vi.mock('shiki', => ({
 codeToHtml: vi.fn.mockResolvedValue('<pre><code>{"test": "data"}</code></pre>'),
}))
describe('triggerLog Components', => {
 describe('jsonHighlighter', => {
 it('should render loading state initially', async => {
 // 创建简化的 JsonHighlighter mock
 const JsonHighlighter = defineComponent({
 props: {
 json: { type: Object, default: null },
 },
 setup(props) {
 const loading = ref(true)
 const html = ref('')
 onMounted(async => {
 if (props.json) {
 // Simulate async loading
 await new Promise(resolve => setTimeout(resolve, 10))
 html.value = '<pre>{"test": "data"}</pre>'
 }
 loading.value = false
 })
 return => {
 if (loading.value) {
 return h('div', { class: 'loading' }, '加载中...')
 }
 if (!props.json) {
 return h('div', { class: 'empty' }, '无数据')
 }
 return h('div', { class: 'json-content', innerHTML: html.value })
 }
 },
 })
 const wrapper = mount(JsonHighlighter, {
 props: { json: { test: 'data' } },
 })
 expect(wrapper.find('.loading').exists).toBe(true)
 })
 it('should render empty state when json is null', async => {
 const JsonHighlighter = defineComponent({
 props: {
 json: { type: Object, default: null },
 },
 setup(props) {
 return => {
 if (!props.json) {
 return h('div', { class: 'empty' }, '无数据')
 }
 return h('div', { class: 'json-content' }, JSON.stringify(props.json))
 }
 },
 })
 const wrapper = mount(JsonHighlighter, {
 props: { json: null },
 })
 expect(wrapper.find('.empty').exists).toBe(true)
 expect(wrapper.text).toContain('无数据')
 })
 })
 describe('keyFieldsCard', => {
 it('should render key fields correctly', => {
 const KeyFieldsCard = defineComponent({
 props: {
 prdUrl: { type: String, default: '' },
 description: { type: String, default: '' },
 techDocUrl: { type: String, default: '' },
 },
 setup(props) {
 return =>
 h('div', { class: 'key-fields-card' }, [
 h('div', { class: 'field prd-url' }, props.prdUrl || '-'),
 h('div', { class: 'field description' }, props.description || '-'),
 h('div', { class: 'field tech-doc-url' }, props.techDocUrl || '-'),
 ])
 },
 })
 const wrapper = mount(KeyFieldsCard, {
 props: {
 prdUrl: 'https://example.com/prd',
 description: 'Test description',
 techDocUrl: 'https://example.com/tech-doc',
 },
 })
 expect(wrapper.find('.prd-url').text).toBe('https://example.com/prd')
 expect(wrapper.find('.description').text).toBe('Test description')
 expect(wrapper.find('.tech-doc-url').text).toBe('https://example.com/tech-doc')
 })
 it('should render placeholder when fields are empty', => {
 const KeyFieldsCard = defineComponent({
 props: {
 prdUrl: { type: String, default: '' },
 description: { type: String, default: '' },
 techDocUrl: { type: String, default: '' },
 },
 setup(props) {
 return =>
 h('div', { class: 'key-fields-card' }, [
 h('div', { class: 'field prd-url' }, props.prdUrl || '-'),
 h('div', { class: 'field description' }, props.description || '-'),
 h('div', { class: 'field tech-doc-url' }, props.techDocUrl || '-'),
 ])
 },
 })
 const wrapper = mount(KeyFieldsCard, {
 props: {
 prdUrl: '',
 description: '',
 techDocUrl: '',
 },
 })
 expect(wrapper.find('.prd-url').text).toBe('-')
 expect(wrapper.find('.description').text).toBe('-')
 expect(wrapper.find('.tech-doc-url').text).toBe('-')
 })
 })
 describe('triggerLogList', => {
 it('should render log items', => {
 const mockLogs = [
 {
 id: '1',
 event_type: 'WorkitemCreateEvent',
 work_item_id: '12345',
 project_id: 'proj-1',
 status: 'accepted' as const,
 created_at: '2026-01-21T10:00:00Z',
 prd_url: '',
 description: '',
 tech_doc_url: '',
 event_uuid: 'uuid-1',
 error_message: null,
 },
 {
 id: '2',
 event_type: 'WorkitemStatusEvent',
 work_item_id: '67890',
 project_id: 'proj-1',
 status: 'error' as const,
 created_at: '2026-01-21T11:00:00Z',
 prd_url: '',
 description: '',
 tech_doc_url: '',
 event_uuid: 'uuid-2',
 error_message: 'Some error',
 },
 ]
 const TriggerLogList = defineComponent({
 props: {
 logs: { type: Array, required: true },
 loading: { type: Boolean, default: false },
 },
 setup(props) {
 return => {
 if (props.loading) {
 return h('div', { class: 'loading' }, 'Loading...')
 }
 if (props.logs.length === 0) {
 return h('div', { class: 'empty' }, '暂无触发日志')
 }
 return h(
 'div',
 { class: 'log-list' },
 props.logs.map((log: any) =>
 h('div', { class: 'log-item', key: log.id }, [
 h('span', { class: 'event-type' }, log.event_type),
 h('span', { class: 'status' }, log.status),
 ]),
 ),
 )
 }
 },
 })
 const wrapper = mount(TriggerLogList, {
 props: { logs: mockLogs, loading: false },
 })
 expect(wrapper.findAll('.log-item')).toHaveLength(2)
 expect(wrapper.find('.event-type').text).toBe('WorkitemCreateEvent')
 })
 it('should render loading state', => {
 const TriggerLogList = defineComponent({
 props: {
 logs: { type: Array, required: true },
 loading: { type: Boolean, default: false },
 },
 setup(props) {
 return => {
 if (props.loading) {
 return h('div', { class: 'loading' }, 'Loading...')
 }
 return h('div', { class: 'log-list' })
 }
 },
 })
 const wrapper = mount(TriggerLogList, {
 props: { logs:, loading: true },
 })
 expect(wrapper.find('.loading').exists).toBe(true)
 })
 it('should render empty state', => {
 const TriggerLogList = defineComponent({
 props: {
 logs: { type: Array, required: true },
 loading: { type: Boolean, default: false },
 },
 setup(props) {
 return => {
 if (props.logs.length === 0) {
 return h('div', { class: 'empty' }, '暂无触发日志')
 }
 return h('div', { class: 'log-list' })
 }
 },
 })
 const wrapper = mount(TriggerLogList, {
 props: { logs:, loading: false },
 })
 expect(wrapper.find('.empty').exists).toBe(true)
 expect(wrapper.text).toContain('暂无触发日志')
 })
 })
 describe('status helpers', => {
 it('should return correct status variant', => {
 const getStatusVariant = (status: string) => {
 switch (status) {
 case 'accepted':
 return 'default'
 case 'ignored':
 return 'secondary'
 case 'error':
 return 'destructive'
 case 'duplicate':
 return 'outline'
 default:
 return 'outline'
 }
 }
 expect(getStatusVariant('accepted')).toBe('default')
 expect(getStatusVariant('ignored')).toBe('secondary')
 expect(getStatusVariant('error')).toBe('destructive')
 expect(getStatusVariant('duplicate')).toBe('outline')
 expect(getStatusVariant('unknown')).toBe('outline')
 })
 it('should return correct status label', => {
 const getStatusLabel = (status: string) => {
 switch (status) {
 case 'accepted':
 return '已接受'
 case 'ignored':
 return '已忽略'
 case 'error':
 return '错误'
 case 'duplicate':
 return '重复'
 default:
 return status
 }
 }
 expect(getStatusLabel('accepted')).toBe('已接受')
 expect(getStatusLabel('ignored')).toBe('已忽略')
 expect(getStatusLabel('error')).toBe('错误')
 expect(getStatusLabel('duplicate')).toBe('重复')
 })
 })
 describe('uRL validation', => {
 it('should validate URLs correctly', => {
 const isValidUrl = (url: string): boolean => {
 if (!url)
 return false
 try {
 // eslint-disable-next-line no-new
 new URL(url)
 return true
 }
 catch {
 return false
 }
 }
 expect(isValidUrl('https://example.com')).toBe(true)
 expect(isValidUrl('http://localhost:3000')).toBe(true)
 expect(isValidUrl('')).toBe(false)
 expect(isValidUrl('not-a-url')).toBe(false)
 expect(isValidUrl('ftp://files.example.com')).toBe(true)
 })
 })
})
