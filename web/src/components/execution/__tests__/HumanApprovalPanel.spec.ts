import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const approveNode = vi.fn()
const rejectNode = vi.fn()
const success = vi.fn()
const handleError = vi.fn()

vi.mock('~/stores/useExecutionsStore', () => ({
  useExecutionsStore: () => ({
    approveNode,
    rejectNode,
  }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError }),
}))

const HumanApprovalPanel = (await import('../HumanApprovalPanel.vue')).default

function makeNodeExecution(overrides: Record<string, any> = {}) {
  return {
    id: 'ne-approval',
    node: 'node-approval',
    node_name: '等待人工审批',
    node_type: 'human_approval',
    status: 'waiting_approval',
    input_data: {},
    output_data: {
      title: 'UAT approval',
      description: 'Please approve this execution.',
      display_data: { summary: 'ready' },
    },
    error_message: '',
    error_traceback: '',
    attempt: 1,
    approval_data: {},
    container_id: '',
    container_logs: '',
    duration: null,
    created_at: '2026-06-14T00:00:00Z',
    started_at: '2026-06-14T00:00:00Z',
    completed_at: null,
    sub_step_progress: null,
    logs: null,
    error_code: null,
    ...overrides,
  }
}

function mountPanel(nodeExecution = makeNodeExecution()) {
  return mount(HumanApprovalPanel, {
    props: { nodeExecution: nodeExecution as any },
    global: {
      stubs: {
        Badge: { template: '<span><slot /></span>' },
        Button: { template: '<button :disabled="$attrs.disabled"><slot /></button>' },
        Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' },
        DialogContent: { template: '<div><slot /></div>' },
        DialogDescription: { template: '<p><slot /></p>' },
        DialogFooter: { template: '<footer><slot /></footer>' },
        DialogHeader: { template: '<header><slot /></header>' },
        DialogTitle: { template: '<h2><slot /></h2>' },
        Separator: { template: '<hr>' },
        Textarea: { template: '<textarea />' },
      },
    },
  })
}

describe('HumanApprovalPanel', () => {
  beforeEach(() => {
    approveNode.mockReset().mockResolvedValue(undefined)
    rejectNode.mockReset().mockResolvedValue(undefined)
    success.mockReset()
    handleError.mockReset()
  })

  it('renders waiting approval data and approves through the execution store', async () => {
    const wrapper = mountPanel()

    expect(wrapper.text()).toContain('UAT approval')
    expect(wrapper.text()).toContain('Please approve this execution.')
    expect(wrapper.text()).toContain('ready')
    expect(wrapper.text()).toContain('待审批')

    const approveButton = wrapper.findAll('button').find(button => button.text().includes('通过'))
    expect(approveButton).toBeTruthy()

    await approveButton!.trigger('click')

    expect(approveNode).toHaveBeenCalledWith('ne-approval', '')
    expect(success).toHaveBeenCalledWith('审批已通过')
    expect(wrapper.emitted('actionComplete')).toHaveLength(1)
  })

  it('renders completed rejected result without action buttons', () => {
    const wrapper = mountPanel(makeNodeExecution({
      status: 'completed',
      output_data: {
        _next_handle: 'rejected',
        reject_reason: 'Needs changes',
      },
    }))

    expect(wrapper.text()).toContain('已拒绝')
    expect(wrapper.text()).toContain('Needs changes')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})
