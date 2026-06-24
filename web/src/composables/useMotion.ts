/**
 * 全站动效基础设施（GSAP + Lottie）。
 *
 * 统一约束：
 * - 所有动效遵循 prefers-reduced-motion，用户偏好减弱动效时直接跳过
 * - GSAP 动画一律通过 gsap.context(scope) 创建，选择器作用域限定在组件根内，
 *   卸载时 revert，防止动画作用到已卸载节点或别的组件
 * - Lottie 按需加载 lottie_light（仅 svg 渲染器），避免拖累首屏
 */
import type { AnimationItem } from 'lottie-web'
import type { Ref, WatchSource } from 'vue'
import { gsap } from 'gsap'
import { nextTick, onBeforeUnmount, onMounted, onUnmounted, watch } from 'vue'

export function usePrefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * 组件挂载后在 container 作用域内创建 GSAP 动画，卸载时自动 revert。
 * reduced-motion 时不创建任何动画（元素保持最终静态样式）。
 */
export function useGsapReveal(
  container: Ref<HTMLElement | null>,
  build: () => void,
): void {
  let ctx: gsap.Context | undefined
  onMounted(() => {
    if (!container.value || usePrefersReducedMotion())
      return
    ctx = gsap.context(build, container.value)
  })
  onUnmounted(() => {
    ctx?.revert()
  })
}

/**
 * 异步列表的行级入场 stagger：ready 变为 true（如 loading 结束）后，
 * 对 container 内匹配 selector 的元素做一次浮入动画。只播一次。
 */
export function useListReveal(
  container: Ref<HTMLElement | null>,
  selector: string,
  ready: WatchSource<boolean>,
  vars: gsap.TweenVars = {},
): void {
  let ctx: gsap.Context | undefined
  watch(ready, async (ok) => {
    if (!ok || ctx)
      return
    await nextTick()
    if (!container.value || usePrefersReducedMotion())
      return
    // 空列表（空态分支）直接跳过，避免 GSAP "target not found" 告警
    const targets = container.value.querySelectorAll(selector)
    if (targets.length === 0)
      return
    ctx = gsap.context(() => {
      gsap.from(targets, {
        y: 12,
        autoAlpha: 0,
        duration: 0.4,
        stagger: 0.06,
        ease: 'power2.out',
        // 动画结束清掉 inline style，避免与 hover 的 CSS transform/transition 冲突
        clearProps: 'all',
        ...vars,
      })
    }, container.value)
  }, { immediate: true })
  onUnmounted(() => {
    ctx?.revert()
  })
}

export interface UseLottieOptions {
  loop?: boolean
  speed?: number
}

/**
 * 在容器内循环播放 Lottie 动画（懒加载 lottie_light，svg 渲染）。
 * 容器 ref 支持条件渲染（v-if）：出现时加载、消失时销毁。
 * reduced-motion 时停在第一帧不播放。
 */
export function useLottie(
  container: Ref<HTMLElement | null>,
  animationData: Record<string, any>,
  options: UseLottieOptions = {},
): void {
  let anim: AnimationItem | null = null
  let disposed = false

  async function mount() {
    if (anim)
      return
    const { default: lottie } = await import('lottie-web/build/player/lottie_light')
    // 动态 import 期间容器可能已被销毁 / 重建，以最新 ref 为准
    if (disposed || anim || !container.value)
      return
    anim = lottie.loadAnimation({
      container: container.value,
      renderer: 'svg',
      loop: options.loop ?? true,
      autoplay: !usePrefersReducedMotion(),
      // lottie 会原地修改 animationData，传副本避免污染模块单例
      animationData: structuredClone(animationData),
    })
    if (options.speed)
      anim.setSpeed(options.speed)
  }

  watch(container, (el) => {
    if (el) {
      void mount()
    }
    else {
      anim?.destroy()
      anim = null
    }
  }, { immediate: true, flush: 'post' })

  onBeforeUnmount(() => {
    disposed = true
    anim?.destroy()
    anim = null
  })
}

/**
 * 按需（如 hover）从头播放一次的 Lottie 动画。
 *
 * 与 useLottie 不同：不循环、不自动播放，静止时停在第 0 帧（动画应把第 0
 * 帧设计成「静态形态」）。调用返回的 play() 才会从头播放一次。
 * lottie 异步懒加载，play() 早于加载完成时会标记 pending，加载后补播。
 * reduced-motion 时仍渲染静态第 0 帧，但 play() 不触发动画。
 */
export function useHoverLottie(
  container: Ref<HTMLElement | null>,
  animationData: Record<string, any>,
  options: Pick<UseLottieOptions, 'speed'> = {},
): { play: () => void } {
  let anim: AnimationItem | null = null
  let disposed = false
  let pendingPlay = false

  async function mount() {
    if (anim)
      return
    const { default: lottie } = await import('lottie-web/build/player/lottie_light')
    if (disposed || anim || !container.value)
      return
    anim = lottie.loadAnimation({
      container: container.value,
      renderer: 'svg',
      loop: false,
      autoplay: false,
      animationData: structuredClone(animationData),
    })
    if (options.speed)
      anim.setSpeed(options.speed)
    anim.goToAndStop(0, true)
    if (pendingPlay) {
      pendingPlay = false
      if (!usePrefersReducedMotion())
        anim.goToAndPlay(0, true)
    }
  }

  function play() {
    if (usePrefersReducedMotion())
      return
    if (anim)
      anim.goToAndPlay(0, true)
    else
      pendingPlay = true
  }

  watch(container, (el) => {
    if (el) {
      void mount()
    }
    else {
      anim?.destroy()
      anim = null
    }
  }, { immediate: true, flush: 'post' })

  onBeforeUnmount(() => {
    disposed = true
    anim?.destroy()
    anim = null
  })

  return { play }
}
