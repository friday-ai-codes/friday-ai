import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import DashboardSkillInstallTip from '~/components/dashboard/DashboardSkillInstallTip.vue'

const DISMISS_KEY = 'friday:skill-tip-dismissed'

function mountTip() {
  return mount(DashboardSkillInstallTip, {
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('dashboardSkillInstallTip', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('默认展示三步安装说明', () => {
    const wrapper = mountTip()
    expect(wrapper.find('[data-testid="skill-install-tip"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent')
    expect(wrapper.text()).toContain('访问令牌')
    expect(wrapper.text()).toContain('npx -y @friday-ai/mcp init')
  })

  it('init 命令的 base-url 动态使用当前实例地址', () => {
    const wrapper = mountTip()
    expect(wrapper.text()).toContain(`--base-url ${window.location.origin}`)
  })

  it('点击关闭后卡片隐藏并持久化到 localStorage', async () => {
    const wrapper = mountTip()
    await wrapper.find('[data-testid="skill-tip-dismiss"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="skill-install-tip"]').exists()).toBe(false)
    expect(localStorage.getItem(DISMISS_KEY)).toBe('true')
  })

  it('localStorage 已标记关闭时不渲染', () => {
    localStorage.setItem(DISMISS_KEY, 'true')
    const wrapper = mountTip()
    expect(wrapper.find('[data-testid="skill-install-tip"]').exists()).toBe(false)
  })
})
