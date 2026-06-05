/**
 * useConversationFrozen composable 单元测试
 *
 * 历史背景：原 ChatHeader.spec 含 G/H/WAITING/I/J 5 个 pin-related
 * 用例。UX 重设计后 ChatHeader 删除凭证下拉与切换确认弹窗职责（迁移到 ChatInput
 * 接管），相应用例被裁剪。useConversationFrozen 已被 ChatInput 复用以接管原
 * frozen 装饰职责，本套保留 6 个组合用例（A/B/C/stopped/draft/响应式）继续守护
 * frozen 判定逻辑核心契约。
 */
import { describe, expect, it } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import { useConversationFrozen } from '~/composables/useConversationFrozen'

describe('useConversationFrozen', () => {
  it('a: status=completed → isFrozen=true, reason 含 "已完成"', () => {
    const status = ref<'completed'>('completed')
    const waiting = ref(false)
    const frozen = useConversationFrozen(status, waiting)
    expect(frozen.value.isFrozen).toBe(true)
    expect(frozen.value.reason).toContain('已完成')
  })

  it('b: status=running + waitingForInput=true → isFrozen=true, reason 含 "等待输入"', () => {
    const status = ref<'running'>('running')
    const waiting = ref(true)
    const frozen = useConversationFrozen(status, waiting)
    expect(frozen.value.isFrozen).toBe(true)
    expect(frozen.value.reason).toContain('等待输入')
  })

  it('c: status=running + waitingForInput=false → isFrozen=false, reason=""', () => {
    const status = ref<'running'>('running')
    const waiting = ref(false)
    const frozen = useConversationFrozen(status, waiting)
    expect(frozen.value.isFrozen).toBe(false)
    expect(frozen.value.reason).toBe('')
  })

  it('status=stopped / error 同样 frozen', () => {
    const status = ref<'stopped' | 'error'>('stopped')
    const frozen = useConversationFrozen(status, ref(false))
    expect(frozen.value.isFrozen).toBe(true)
    status.value = 'error'
    expect(frozen.value.isFrozen).toBe(true)
    expect(frozen.value.reason).toContain('异常')
  })

  it('status=draft → isFrozen=false', () => {
    const status = ref<'draft'>('draft')
    const frozen = useConversationFrozen(status, ref(false))
    expect(frozen.value.isFrozen).toBe(false)
  })

  it('响应式：status 从 running 切到 completed 后立即 frozen', async () => {
    const status = ref<'running' | 'completed'>('running')
    const frozen = useConversationFrozen(status, ref(false))
    const tracker = computed(() => frozen.value.isFrozen)
    expect(tracker.value).toBe(false)
    status.value = 'completed'
    await nextTick()
    expect(tracker.value).toBe(true)
  })
})
