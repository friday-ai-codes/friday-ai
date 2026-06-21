import type { Workflow } from '~/stores/useWorkflowsStore'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
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
  // 组件经 getNodeDefinition 读取 useNodeTypesStore（19-03 收敛到 store），
  // 渲染前必须激活 pinia；store 留空即可，节点芯片名/图标走 type 回退。
  beforeEach(() => {
    setActivePinia(createPinia())
  })

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

  it('渲染轻量工作流卡片结构', () => {
    const workflowWithSummary = {
      ...workflow,
      node_summary: [
        { id: 'n1', node_type: 'feishu_trigger', name: '飞书事件', position_x: 0, position_y: 0 },
        { id: 'n2', node_type: 'fetch_work_item', name: '获取工作项', position_x: 120, position_y: 80 },
      ],
      edge_summary: [
        { source_node_id: 'n1', target_node_id: 'n2' },
      ],
      node_count: 2,
    } as Workflow

    const wrapper = mount(WorkflowDataTable, {
      props: {
        workflows: [workflowWithSummary],
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

    expect(wrapper.find('.workflow-card').exists()).toBe(true)
    expect(wrapper.find('.workflow-preview').exists()).toBe(true)
    expect(wrapper.find('.workflow-node-chip').exists()).toBe(true)
    expect(wrapper.find('.workflow-card-actions').exists()).toBe(true)
    expect(wrapper.find('.workflow-execute-button').text()).toContain('执行')
  })

  it('限制节点标签数量并渲染等高卡片骨架', () => {
    const workflowWithManyNodeTypes = {
      ...workflow,
      description: '',
      node_summary: [
        { id: 'n1', node_type: 'feishu_trigger', name: '飞书事件', position_x: 0, position_y: 0 },
        { id: 'n2', node_type: 'fetch_work_item', name: '获取工作项', position_x: 120, position_y: 80 },
        { id: 'n3', node_type: 'ai_plan_generation', name: 'AI 方案生成', position_x: 240, position_y: 120 },
        { id: 'n4', node_type: 'human_approval', name: '方案审批', position_x: 360, position_y: 160 },
        { id: 'n5', node_type: 'ai_coding', name: 'AI 编码执行', position_x: 480, position_y: 200 },
        { id: 'n6', node_type: 'notify_feishu', name: '飞书通知', position_x: 600, position_y: 240 },
      ],
      node_count: 6,
    } as Workflow

    const wrapper = mount(WorkflowDataTable, {
      props: {
        workflows: [workflowWithManyNodeTypes],
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

    expect(wrapper.find('.workflow-card-shell').classes()).toContain('min-h-[220px]')
    expect(wrapper.find('.workflow-card-content').exists()).toBe(true)
    expect(wrapper.find('.workflow-card-description').exists()).toBe(true)
    expect(wrapper.find('.workflow-node-chip-row').exists()).toBe(true)
    expect(wrapper.findAll('.workflow-node-chip')).toHaveLength(4)
    expect(wrapper.find('.workflow-node-overflow').text()).toBe('+2')
  })
})
