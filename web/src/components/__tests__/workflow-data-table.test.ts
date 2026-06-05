import type { Workflow } from '~/stores/useWorkflowsStore'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowDataTable from '../workflow/WorkflowDataTable.vue'

const workflow: Workflow = {
  id: 'wf-1',
  name: '测试工作流',
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

describe('workflowDataTable', () => {
  it('点击删除按钮时应发出 requestDelete 事件', async () => {
    const wrapper = mount(WorkflowDataTable, {
      props: {
        workflows: [workflow],
        loading: false,
      },
      global: {
        stubs: {
          TooltipProvider: { template: '<div><slot /></div>' },
          Tooltip: { template: '<div><slot /></div>' },
          TooltipTrigger: { template: '<div><slot /></div>' },
          TooltipContent: { template: '<div><slot /></div>' },
          Skeleton: { template: '<div />' },
          Switch: { template: '<button />' },
          Button: {
            template: '<button v-bind="$attrs" data-test="button" @click="$emit(\'click\', $event)"><slot /></button>',
          },
        },
      },
    })

    const deleteButton = wrapper.find('[title="删除工作流"]')
    expect(deleteButton.exists()).toBe(true)
    await deleteButton.trigger('click')

    const events = wrapper.emitted('requestDelete')
    expect(events).toBeTruthy()
    expect(events?.[0]?.[0]).toEqual(workflow)
  })
})
