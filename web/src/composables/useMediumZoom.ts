/**
 * 会话图片「平滑点击放大」能力。
 *
 * 基于 medium-zoom（Medium 同款的平滑缩放）：
 * - `vMediumZoom` 指令：用于静态 `<img>`（如用户发送的图片缩略图），
 *   元素挂载时 attach、卸载时 detach，跟随 Vue 生命周期。
 * - `attachZoomWithin(root)`：扫描容器内所有 `img[data-zoomable]` 并挂载，
 *   用于 v-html 渲染的 Markdown 图片（指令无法作用于 v-html 内部节点）。
 *
 * 全局共享单个 zoom 实例：同一时刻只展开一张，背景遮罩统一。
 */
import type { Directive } from 'vue'
import mediumZoom from 'medium-zoom'

type ZoomInstance = ReturnType<typeof mediumZoom>

let _zoom: ZoomInstance | null = null

function getZoom(): ZoomInstance {
  if (!_zoom) {
    _zoom = mediumZoom({
      margin: 24,
      background: 'rgba(15, 23, 42, 0.88)',
      scrollOffset: 0,
    })
  }
  return _zoom
}

/** 指令：`v-medium-zoom` 挂到静态 `<img>` 上即可点击平滑放大。 */
export const vMediumZoom: Directive<HTMLImageElement> = {
  mounted(el) {
    getZoom().attach(el)
  },
  beforeUnmount(el) {
    try {
      getZoom().detach(el)
    }
    catch {
      // 实例已销毁/元素已移除，忽略
    }
  },
}

/**
 * 把容器内带 `data-zoomable` 标记的图片接入缩放（幂等：先 detach 再 attach）。
 * 适用于 Markdown v-html 渲染出的图片：在 onMounted / onUpdated 后调用。
 */
export function attachZoomWithin(root: HTMLElement | null): void {
  if (!root)
    return
  const imgs = root.querySelectorAll<HTMLImageElement>('img[data-zoomable]')
  if (imgs.length === 0)
    return
  const zoom = getZoom()
  zoom.detach(imgs)
  zoom.attach(imgs)
}
