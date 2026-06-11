import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'

const pushMock = vi.fn()
const replaceMock = vi.fn()
const fetchSpacesMock = vi.fn()
const fetchWorkflowsMock = vi.fn()

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: vi.fn(() => ({ query: {} })),
    useRouter: vi.fn(() => ({ push: pushMock, replace: replaceMock })),
  }
})

vi.mock('@tanstack/vue-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/vue-query')>()
  return {
    ...actual,
    useQuery: vi.fn(({ queryKey }: { queryKey: string[] }) => {
      if (queryKey[0] === 'executions') {
        return {
          data: ref([
            {
              id: 'exec-1',
              workflow: 'wf-1',
              workflow_name: '飞书全链路自动化',
              status: 'failed',
              trigger_type: 'manual',
              duration: 71,
              created_at: '2026-03-27T12:25:26Z',
              node_executions: [],
            },
          ]),
          isLoading: ref(false),
          isFetching: ref(false),
        }
      }
      return {
        data: ref([]),
        isLoading: ref(false),
        isFetching: ref(false),
      }
    }),
  }
})

vi.mock('~/stores/spaces', () => ({
  useSpacesStore: () => ({
    spaces: [{ id: 'space-1', name: '默认空间' }],
    fetchSpaces: fetchSpacesMock,
  }),
}))

vi.mock('~/stores/useWorkflowsStore', () => ({
  useWorkflowsStore: () => ({
    workflows: [{ id: 'wf-1', name: '飞书全链路自动化', project_name: '默认空间' }],
    fetchWorkflows: fetchWorkflowsMock,
  }),
}))

vi.mock('~/api/client', () => ({
  default: {
    get: vi.fn(),
  },
}))

const PageContainerStub = defineComponent({
  template: '<main><slot /></main>',
})

const PageHeaderStub = defineComponent({
  props: ['title', 'description'],
  template: '<header><h1>{{ title }}</h1><p>{{ description }}</p><slot name="title-suffix" /><slot name="actions" /></header>',
})

const SelectStub = defineComponent({
  template: '<div><slot /></div>',
})

const ButtonStub = defineComponent({
  template: '<button><slot /></button>',
})

const DataTableStub = defineComponent({
  props: ['data', 'columns', 'tableId', 'loading', 'onRowClick'],
  setup(props, { slots }) {
    return () => {
      const firstRow = props.data?.[0]
      const statusColumn = props.columns?.find((c: any) => c.accessorKey === 'status')
      return h('section', { class: 'data-table-stub' }, [
        slots.filters?.(),
        firstRow && statusColumn?.cell
          ? h('div', { class: 'status-cell-stub' }, [
              statusColumn.cell({ row: { original: firstRow } }),
            ])
          : null,
      ])
    }
  },
})

const ExecutionsPage = (await import('../index.vue')).default

describe('/executions index page', () => {
  it('渲染轻量统计卡、筛选条和局部状态 pill', () => {
    const wrapper = mount(ExecutionsPage, {
      global: {
        stubs: {
          Button: ButtonStub,
          DataTable: DataTableStub,
          PageContainer: PageContainerStub,
          PageHeader: PageHeaderStub,
          Select: SelectStub,
          SelectContent: SelectStub,
          SelectItem: SelectStub,
          SelectTrigger: SelectStub,
          SelectValue: SelectStub,
        },
      },
    })

    expect(wrapper.findAll('.execution-stat-card')).toHaveLength(4)
    expect(wrapper.find('.executions-filter-strip').exists()).toBe(true)

    const statusPill = wrapper.find('.execution-status-pill')
    expect(statusPill.exists()).toBe(true)
    expect(statusPill.classes()).toContain('execution-status-pill--failed')
    expect(statusPill.text()).toContain('失败')
  })
})
