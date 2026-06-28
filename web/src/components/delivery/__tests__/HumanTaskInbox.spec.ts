/**
 * HumanTaskInbox 守护测试（Chassis v2 · P8 Human Task Center）。
 *
 * 覆盖：
 *  - 统一收件箱聚合呈现（澄清 / 审批 / 失败反应 / 物化待办）。
 *  - 待答澄清内联作答 → 调 answerClarification 回流。
 *  - 物化待办处理 → 调 resolveHumanTask 回流。
 *  - 审批 / 失败反应仅呈现上下文（不越界驱动 workflows）。
 *  - 空态占位。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listHumanTasksMock = vi.fn()
const resolveHumanTaskMock = vi.fn()
const skipHumanTaskMock = vi.fn()
const answerClarificationMock = vi.fn()

vi.mock('~/api/humanTasks', () => ({
  listHumanTasks: (...a: unknown[]) => listHumanTasksMock(...a),
  resolveHumanTask: (...a: unknown[]) => resolveHumanTaskMock(...a),
  skipHumanTask: (...a: unknown[]) => skipHumanTaskMock(...a),
  answerClarification: (...a: unknown[]) => answerClarificationMock(...a),
}))

const HumanTaskInbox = (await import('../HumanTaskInbox.vue')).default

function clarificationTask() {
  return {
    id: 'clarification:c1',
    task_type: 'clarification',
    scope: 'process_session',
    subject_id: 'sess-1',
    status: 'open',
    source: 'projection',
    source_signal: 'clarification.asked',
    assignee_user_id: null,
    assignee_role: null,
    artifact_version_id: null,
    due_at: null,
    created_at: '2026-06-21T00:00:00Z',
    resolved_at: null,
    resolution: {},
    title: '用哪个鉴权方案？',
    detail: {
      clarification_id: 'c1',
      session_id: 'sess-1',
      round_no: 1,
      pending_count: 1,
      questions: [
        { id: 'q1', question: '用哪个鉴权方案？', qtype: 'single', options: ['JWT', 'Session'], recommended: ['JWT'] },
      ],
    },
  }
}

function approvalTask() {
  return {
    id: 'approval:ne1',
    task_type: 'approval',
    scope: 'workflow_execution',
    subject_id: 'exec-1',
    status: 'open',
    source: 'projection',
    source_signal: 'approval.requested',
    assignee_user_id: null,
    assignee_role: null,
    artifact_version_id: null,
    due_at: null,
    created_at: '2026-06-20T00:00:00Z',
    resolved_at: null,
    resolution: {},
    title: '审批节点',
    detail: { node_execution_id: 'ne1', workflow_execution_id: 'exec-1', workflow_name: '发布流程' },
  }
}

function riskAckTask() {
  return {
    id: 't-mat-1',
    task_type: 'risk_ack',
    scope: 'artifact',
    subject_id: 'art-1',
    status: 'open',
    source: 'materialized',
    source_signal: 'artifact.produced',
    assignee_user_id: null,
    assignee_role: null,
    artifact_version_id: null,
    due_at: null,
    created_at: '2026-06-19T00:00:00Z',
    resolved_at: null,
    resolution: {},
    title: '确认高风险变更',
    detail: {},
  }
}

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(HumanTaskInbox, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

describe('humanTaskInbox 统一待办', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listHumanTasksMock.mockResolvedValue([clarificationTask(), approvalTask(), riskAckTask()])
    resolveHumanTaskMock.mockResolvedValue({ id: 't-mat-1', status: 'done' })
    skipHumanTaskMock.mockResolvedValue({ id: 't-mat-1', status: 'skipped' })
    answerClarificationMock.mockResolvedValue({ clarification_id: 'c1', status: 'done' })
  })

  it('聚合呈现澄清 / 审批 / 物化待办', async () => {
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="human-task-clarification"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="human-task-approval"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="human-task-risk_ack"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="human-task-count"]').text()).toBe('3')
  })

  it('待答澄清内联作答 → 调 answerClarification 回流', async () => {
    const wrapper = mountComp()
    await flushPromises()
    // 选择 JWT
    const radio = wrapper.find('input[type="radio"][value="JWT"]')
    await radio.setValue()
    await wrapper.find('[data-testid="clarification-submit"]').trigger('click')
    await flushPromises()
    expect(answerClarificationMock).toHaveBeenCalledTimes(1)
    const [clarificationId, answers] = answerClarificationMock.mock.calls[0]
    expect(clarificationId).toBe('c1')
    expect(answers[0]).toMatchObject({ question_id: 'q1', selected: 'JWT' })
  })

  it('物化待办处理 → 调 resolveHumanTask', async () => {
    const wrapper = mountComp()
    await flushPromises()
    await wrapper.find('[data-testid="task-resolve"]').trigger('click')
    await flushPromises()
    expect(resolveHumanTaskMock).toHaveBeenCalledWith('t-mat-1', { via: 'inbox' })
  })

  it('物化待办跳过 → 调 skipHumanTask', async () => {
    const wrapper = mountComp()
    await flushPromises()
    await wrapper.find('[data-testid="task-skip"]').trigger('click')
    await flushPromises()
    expect(skipHumanTaskMock).toHaveBeenCalledWith('t-mat-1', '收件箱跳过')
  })

  it('审批仅呈现上下文（不越界驱动 workflows）', async () => {
    const wrapper = mountComp()
    await flushPromises()
    const approval = wrapper.find('[data-testid="human-task-approval"]')
    expect(approval.find('[data-testid="task-context"]').text()).toContain('发布流程')
    expect(approval.find('[data-testid="task-resolve"]').exists()).toBe(false)
  })

  it('空态：无待办显示占位', async () => {
    listHumanTasksMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="human-task-empty"]').exists()).toBe(true)
  })
})
