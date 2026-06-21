import { ref } from 'vue'

/**
 * 节点配置面板「节点说明」收起/展开偏好。
 *
 * 设计：模块级单例 ref —— 跨不同节点的配置面板共享同一偏好；持久化到
 * localStorage，跨会话记忆。默认展开（false）；用户收起后写入，下次默认收起。
 * （节点库的说明为常驻展示，不受此偏好控制。）
 */
const STORAGE_KEY = 'friday:workflow:node-desc-collapsed'

function readInitial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  }
  catch {
    return false
  }
}

// 模块级单例：跨配置面板 / 节点库所有实例共享同一收起状态
const collapsed = ref(readInitial())

export function useNodeDescriptionCollapse() {
  function toggle() {
    collapsed.value = !collapsed.value
    try {
      localStorage.setItem(STORAGE_KEY, collapsed.value ? '1' : '0')
    }
    catch {
      // localStorage 不可用时静默降级（仅当次会话生效）
    }
  }

  return { collapsed, toggle }
}
