/**
 * 首启向导进度持久化（刷新恢复）。
 *
 * 管理员创建成功后 needs_setup 即变为 false，若不记录进度，刷新页面会被路由守卫
 * 直接重定向到 /login（“直接进去了”）。这里把当前步骤写入 localStorage，使刷新后
 * 能恢复到对应步骤；引导完成（进入系统）时清除。
 *
 * 仅 provider / feishu / rag 三步算作「进行中可恢复」：admin 步由 needs_setup
 * 守卫负责（此时尚无 superuser，守卫本就会把用户带到 /setup）。
 */

export type SetupWizardStep = 'admin' | 'provider' | 'feishu' | 'rag'

const STORAGE_KEY = 'friday:setup:step'

const RESUMABLE: SetupWizardStep[] = ['provider', 'feishu', 'rag']

function readRaw(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  }
  catch {
    return null
  }
}

/** 读取已保存的引导步骤；非法值返回 null。 */
export function getSetupProgress(): SetupWizardStep | null {
  const v = readRaw()
  return v === 'admin' || v === 'provider' || v === 'feishu' || v === 'rag' ? v : null
}

/** 保存当前引导步骤。 */
export function setSetupProgress(step: SetupWizardStep): void {
  try {
    localStorage.setItem(STORAGE_KEY, step)
  }
  catch {
    // localStorage 不可用（隐私模式等）时静默降级：仅丢失刷新恢复能力，不影响向导本身
  }
}

/** 清除引导进度（引导完成或重新开始时调用）。 */
export function clearSetupProgress(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  }
  catch {
    // 同上，静默降级
  }
}

/**
 * 是否存在「进行中、可恢复」的引导进度。
 * 用于路由守卫：needs_setup=false 时，若引导仍在进行则允许停留在 /setup。
 */
export function hasResumableSetup(): boolean {
  const s = getSetupProgress()
  return s !== null && RESUMABLE.includes(s)
}
