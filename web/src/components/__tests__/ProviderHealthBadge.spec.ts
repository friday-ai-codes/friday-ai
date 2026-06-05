import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProviderHealthBadge from '~/components/providers/ProviderHealthBadge.vue'

describe('providerHealthBadge', () => {
  it('status=ok：显示"连接正常" + success variant + check-circle 图标', () => {
    const wrapper = mount(ProviderHealthBadge, {
      props: {
        status: 'ok',
        latencyMs: 120,
        lastCheckedAt: '2026-04-20T10:00:00Z',
      },
    })
    expect(wrapper.text()).toContain('连接正常')
    expect(wrapper.html()).toContain('icon-[lucide--check-circle]')
  })

  it('status=error：显示"连接失败" + destructive variant + alert-circle 图标', () => {
    const wrapper = mount(ProviderHealthBadge, {
      props: { status: 'error', lastError: '401 unauthorized' },
    })
    expect(wrapper.text()).toContain('连接失败')
    expect(wrapper.html()).toContain('icon-[lucide--alert-circle]')
  })

  it('status=unchecked（空串）：显示"未测试" + muted variant + help-circle 图标', () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: '' } })
    expect(wrapper.text()).toContain('未测试')
    expect(wrapper.html()).toContain('icon-[lucide--help-circle]')
  })

  it('status=testing：显示"测试中" + info variant + loader-2 spinning 图标', () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: 'testing' } })
    expect(wrapper.text()).toContain('测试中')
    expect(wrapper.html()).toContain('icon-[lucide--loader-2]')
    expect(wrapper.html()).toContain('animate-spin')
  })

  it('点击 badge 触发 emit("test")', async () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: '' } })
    await wrapper.find('[role="status"]').trigger('click')
    expect(wrapper.emitted('test')?.length).toBe(1)
  })

  it('testing 状态下点击不再 emit（防双击）', async () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: 'testing' } })
    await wrapper.find('[role="status"]').trigger('click')
    expect(wrapper.emitted('test')).toBeUndefined()
  })

  it('点击后 locked=true，500ms 内第二次点击不 emit', async () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: '' } })
    await wrapper.find('[role="status"]').trigger('click')
    await wrapper.find('[role="status"]').trigger('click')
    expect(wrapper.emitted('test')?.length).toBe(1)
  })

  it('具备 a11y 属性：role="status" + aria-live="polite"', () => {
    const wrapper = mount(ProviderHealthBadge, { props: { status: 'ok' } })
    const badge = wrapper.find('[role="status"]')
    expect(badge.exists()).toBe(true)
    expect(badge.attributes('aria-live')).toBe('polite')
  })
})
