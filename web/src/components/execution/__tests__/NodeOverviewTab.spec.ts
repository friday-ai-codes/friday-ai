/**
 * NodeOverviewTab.spec.ts — OBS-01 结构化变量错误展示 + error_code RED 测试
 *
 * 契约（Phase 17/18 约定）：node 错误信息为「中文摘要 \n 末行 JSON」时，
 * 应 parse 出 summary（友好展示）与结构化 detail（reference/node），
 * 而非把整段 JSON 原文堆在一起；非 JSON 错误回退纯文本不抛错；
 * error_code 存在时应渲染错误码行。
 *
 * 当前组件直接渲染整段 error_message、无 error_code 行，故结构化/error_code
 * 断言为 RED，由 Wave 1/2（21-07）实现转绿；纯文本回退为 GREEN。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('~/components/workflow/editor/nodes/nodeVisuals', () => ({
  getNodeVisual: () => ({ icon: 'div', color: 'blue' }),
}))

vi.mock('~/components/workflow/editor/nodes/composables/useNodeStyle', () => ({
  useNodeStyle: () => ({ value: { iconBg: '', iconColor: '' } }),
}))

const NodeOverviewTab = (await import('../NodeOverviewTab.vue')).default

function makeNodeExecution(overrides: Record<string, any> = {}) {
  return {
    id: 'ne1',
    node: 'n1',
    node_name: 'N1',
    node_type: 'test',
    status: 'failed',
    input_data: {},
    output_data: {},
    error_message: '',
    error_traceback: '',
    attempt: 1,
    approval_data: {},
    container_id: '',
    container_logs: '',
    duration: 1,
    created_at: '2026-06-13T00:00:00Z',
    started_at: '2026-06-13T00:00:00Z',
    completed_at: '2026-06-13T00:00:01Z',
    sub_step_progress: null,
    logs: null,
    error_code: null,
    ...overrides,
  } as any
}

function mountTab(nodeExecution: Record<string, any>) {
  return mount(NodeOverviewTab, {
    props: { nodeExecution: nodeExecution as any },
    global: {
      stubs: {
        StatusBadge: { template: '<span class="status-badge-stub" />' },
        Badge: { template: '<span class="badge-stub"><slot /></span>' },
        ExecutionProviderSnapshot: { template: '<div class="provider-snapshot-stub" />' },
      },
    },
  })
}

describe('NodeOverviewTab — OBS-01 结构化错误展示', () => {
  it('test_structured_error_parsed', () => {
    const errorMessage = '变量解析失败\n{"reference":"nodes.n1.output","node":"n1"}'
    const wrapper = mountTab(makeNodeExecution({ error_message: errorMessage }))

    const text = wrapper.text()
    // 摘要应可见
    expect(text).toContain('变量解析失败')
    // 结构化引用值应被友好展示
    expect(text).toContain('nodes.n1.output')
    // RED：当前直接渲染整段 message，原始 JSON 串不应原样堆在错误块里
    expect(text).not.toContain('{"reference"')
  })

  it('test_plain_error_fallback', () => {
    const wrapper = mountTab(makeNodeExecution({ error_message: '普通错误无 JSON' }))
    // GREEN：非 JSON 错误回退纯文本展示、不抛错
    expect(wrapper.text()).toContain('普通错误无 JSON')
  })

  it('test_error_code_rendered', () => {
    const wrapper = mountTab(makeNodeExecution({
      error_message: '变量解析失败',
      error_code: 'VAR_RESOLUTION_FAILED',
    }))
    // RED：当前组件未渲染 error_code
    expect(wrapper.text()).toContain('VAR_RESOLUTION_FAILED')
  })
})
