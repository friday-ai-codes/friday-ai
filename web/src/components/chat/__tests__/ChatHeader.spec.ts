/**
 * useConversationFrozen composable 单元测试
 *
 * 产品决策（2026-07）：**任何状态都不冻结 Provider / 模型**，用户随时可切换到任意模型。
 * 本套用例守护"恒不冻结"契约——无论 completed/stopped/error/等待输入 均 isFrozen=false。
 */
import { describe, expect, it } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import type { ConversationStatus } from '~/composables/useConversationFrozen'
import { useConversationFrozen } from '~/composables/useConversationFrozen'

describe('useConversationFrozen（恒不冻结）', () => {
  it.each<ConversationStatus>([
    'draft',
    'running',
    'paused',
    'interrupted',
    'completed',
    'stopped',
    'error',
  ])('status=%s → isFrozen=false, reason=""', (s) => {
    const status = ref<ConversationStatus>(s)
    const frozen = useConversationFrozen(status, ref(false))
    expect(frozen.value.isFrozen).toBe(false)
    expect(frozen.value.reason).toBe('')
  })

  it('等待输入（waitingForInput=true）同样不冻结', () => {
    const status = ref<ConversationStatus>('running')
    const frozen = useConversationFrozen(status, ref(true))
    expect(frozen.value.isFrozen).toBe(false)
  })

  it('响应式：status 从 running 切到 completed 仍不冻结', async () => {
    const status = ref<ConversationStatus>('running')
    const frozen = useConversationFrozen(status, ref(false))
    const tracker = computed(() => frozen.value.isFrozen)
    expect(tracker.value).toBe(false)
    status.value = 'completed'
    await nextTick()
    expect(tracker.value).toBe(false)
  })
})
