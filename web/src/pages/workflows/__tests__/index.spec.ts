import type { Workflow } from '~/stores/useWorkflowsStore'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

const pushMock = vi.fn()
const getMock = vi.fn()
const delMock = vi.fn()
const successMock = vi.fn()
const handleErrorMock = vi.fn()

const workflow: Workflow = {
  id: 'wf-1',
  name: '需求自动生成代码',
  description: 'desc',
  icon: '',
  project: 'p1',
  project_name: '项目',
  created_by: null,
  created_by_name: null,
  trigger_type: 'manual',
  trigger_config: {},
  is_active: true,
  is_template: false,
  max_concurrent_executions: 1,
  default_timeout: 300,
  metadata: {},
  nodes: [],
  edges: [],
  execution_count: 0,
  last_execution: null,
  created_at: '',
  updated_at: '',
}

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRouter: vi.fn(() => ({ push: pushMock })),
  }
})

vi.mock('~/api/client', () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    del: (...args: unknown[]) => delMock(...args),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    upload: vi.fn(),
  },
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: successMock,
    error: vi.fn(),
  }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({
    handleError: handleErrorMock,
  }),
}))

vi.mock('vue-final-modal', () => ({
  useModal: () => ({
    open: vi.fn(),
    close: vi.fn(),
  }),
}))

const PassthroughStub = defineComponent({
  template: '<div><slot /></div>',
})

const PageContainerStub = defineComponent({
  template: '<main><slot /></main>',
})

const WorkflowDataTableStub = defineComponent({
  props: {
    workflows: {
      type: Array,
      default: () => [],
    },
  },
  emits: ['click', 'execute', 'edit', 'requestDelete', 'toggleActive'],
  setup(props, { emit }) {
    return () => {
      const firstWorkflow = (props.workflows as Workflow[])[0]
      if (!firstWorkflow)
        return h('div', 'empty')

      return h('button', {
        class: 'request-delete',
        onClick: () => emit('requestDelete', firstWorkflow),
      }, 'open delete dialog')
    }
  },
})

const WorkflowsIndexPage = (await import('../index.vue')).default

function mountPage() {
  return mount(WorkflowsIndexPage, {
    attachTo: document.body,
    global: {
      stubs: {
        PageContainer: PageContainerStub,
        WorkflowDataTable: WorkflowDataTableStub,
        WorkflowEmptyState: PassthroughStub,
        WorkflowPageHeader: PassthroughStub,
      },
    },
  })
}

async function openDeleteDialog(wrapper: ReturnType<typeof mount>) {
  await flushPromises()
  await wrapper.find('.request-delete').trigger('click')
}

function getConfirmDeleteButton() {
  return Array.from(document.body.querySelectorAll('button'))
    .find(button => button.textContent?.trim() === '删除')
}

describe('/workflows index page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getMock.mockResolvedValue({ results: [workflow] })
    delMock.mockResolvedValue(undefined)
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('确认删除时调用删除接口并提示成功', async () => {
    const wrapper = mountPage()
    await openDeleteDialog(wrapper)

    expect(document.body.textContent).toContain('需求自动生成代码')

    const deleteButton = getConfirmDeleteButton()
    expect(deleteButton).toBeTruthy()
    deleteButton!.click()
    await flushPromises()

    expect(delMock).toHaveBeenCalledWith('/workflows/wf-1/')
    expect(successMock).toHaveBeenCalledWith('工作流已删除')
  })

  it('删除请求未完成时保留确认弹窗并展示删除中状态', async () => {
    let resolveDelete: (() => void) | undefined
    delMock.mockReturnValue(new Promise<void>((resolve) => {
      resolveDelete = resolve
    }))

    const wrapper = mountPage()
    await openDeleteDialog(wrapper)

    const deleteButton = getConfirmDeleteButton()
    expect(deleteButton).toBeTruthy()
    deleteButton!.click()
    await flushPromises()

    expect(delMock).toHaveBeenCalledWith('/workflows/wf-1/')
    expect(document.body.textContent).toContain('需求自动生成代码')
    expect(document.body.textContent).toContain('删除中')

    resolveDelete?.()
    await flushPromises()
  })
})
