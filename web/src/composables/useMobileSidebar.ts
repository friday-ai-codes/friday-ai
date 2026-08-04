/**
 * 全局侧栏在 `< lg` 断点下的 off-canvas 开合状态（模块级单例）。
 *
 * 背景：AppSidebar 原先在所有宽度下都是 `sticky w-64/w-[72px]`，390px 手机上直接占掉
 * 约 3/4 视口宽，任何页面的内容都被挤成细条（蓝图审查页整页坍塌即由此而来）。
 * `< lg` 改为 fixed off-canvas 后，需要一个跨组件的开合状态：布局顶栏的汉堡按钮开，
 * 侧栏自身的遮罩点击 / 路由跳转关。
 *
 * 用模块级 ref 而不是 Pinia：这是纯 UI 瞬时态，无持久化、无跨页语义（对齐
 * `workflows` 等处的模块级单例惯例）。
 */

import { ref } from 'vue'

const mobileOpen = ref(false)

export function useMobileSidebar() {
  function open(): void {
    mobileOpen.value = true
  }
  function close(): void {
    mobileOpen.value = false
  }
  function toggle(): void {
    mobileOpen.value = !mobileOpen.value
  }
  return { mobileOpen, open, close, toggle }
}
