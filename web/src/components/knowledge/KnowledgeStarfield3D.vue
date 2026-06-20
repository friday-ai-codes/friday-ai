<script setup lang="ts">
/**
 * 知识「星图」（真 3D：three.js + 3d-force-graph WebGL）
 *
 * 旋转星系观感：节点为「柔光星点」sprite（径向渐变贴图，无多边形棱角）+ 始终朝向镜头
 * 的文字标签（three-spritetext），标签悬于星点上方不遮挡。透明画布叠在 CSS 星云背景上，
 * 营造氛围。完整交互：
 * - 拖拽旋转（拖动即停止自转）
 * - 右键 / 双指平移中心轴
 * - 滚轮 / 双指缩放
 * - 点击节点 → 飞向该节点并弹出详情浮层
 * - 重置：回到初始全景并恢复自转
 */
import type { StarNode } from '~/composables/useKnowledgeCapabilities'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import SpriteText from 'three-spritetext'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  nodes: StarNode[]
  links: { source: string, target: string, color: string, flow: number }[]
  autoRotate?: boolean
}>(), {
  autoRotate: true,
})

const emit = defineEmits<{
  (e: 'open', node: StarNode): void
}>()

const container = ref<HTMLDivElement | null>(null)
const empty = ref(false)
const rotating = ref(false)
const selected = ref<StarNode | null>(null)

const GROUP_LABEL: Record<StarNode['group'], string> = {
  repo: '仓库',
  sub_app: '子应用',
  module: '模块',
  capability: '能力',
}
const GROUP_COLOR: Record<StarNode['group'], string> = {
  repo: '#818cf8',
  sub_app: '#c084fc',
  module: '#2dd4bf',
  capability: '#fbbf24',
}
const LABEL_HEIGHT: Record<StarNode['group'], number> = {
  repo: 5,
  sub_app: 3.4,
  module: 2.6,
  capability: 1.9,
}

let graph: any = null
let ro: ResizeObserver | null = null
let started = false
let reduceMotion = false
// 是否已完成「初始取景」。一旦用户点击节点 / 交互后置位，避免引擎收敛时再次 zoomToFit 把视角拉回
let fitted = false

function clip(text: string, max = 14): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

// ---------- 柔光星点贴图（按颜色缓存，仅 4 种层级色） ----------
const glowCache = new Map<string, THREE.Texture>()

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const v = h.length === 3
    ? h.split('').map(c => c + c).join('')
    : h
  return [
    Number.parseInt(v.slice(0, 2), 16),
    Number.parseInt(v.slice(2, 4), 16),
    Number.parseInt(v.slice(4, 6), 16),
  ]
}

function glowTexture(color: string): THREE.Texture {
  const cached = glowCache.get(color)
  if (cached)
    return cached
  const size = 128
  const cv = document.createElement('canvas')
  cv.width = cv.height = size
  const ctx = cv.getContext('2d')!
  const [r, g, b] = hexToRgb(color)
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  grad.addColorStop(0, `rgba(255,255,255,0.95)`)
  grad.addColorStop(0.18, `rgba(${r},${g},${b},0.95)`)
  grad.addColorStop(0.45, `rgba(${r},${g},${b},0.35)`)
  grad.addColorStop(1, `rgba(${r},${g},${b},0)`)
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(cv)
  tex.colorSpace = THREE.SRGBColorSpace
  glowCache.set(color, tex)
  return tex
}

// 星点核心半径（沿用旧球体的体量映射，保证层级大小层次）
function coreRadius(val: number): number {
  return 4.2 * Math.cbrt(val)
}

function applyData() {
  if (!graph)
    return
  graph.graphData({
    nodes: props.nodes.map(n => ({ ...n })),
    links: props.links.map(l => ({ ...l })),
  })
}

// 自转走 OrbitControls.autoRotate（绕相机轨道转），不旋转场景本身——
// 这样节点世界坐标恒等于 x/y/z，聚焦取景才不会跑偏。
function orbitControls(): any {
  return graph?.controls?.()
}

function stopAutoRotate() {
  const c = orbitControls()
  if (c)
    c.autoRotate = false
  rotating.value = false
}

function startAutoRotate() {
  if (reduceMotion)
    return
  const c = orbitControls()
  if (c) {
    c.autoRotateSpeed = 0.6
    c.autoRotate = true
  }
  rotating.value = true
}

function toggleRotate() {
  if (rotating.value)
    stopAutoRotate()
  else
    startAutoRotate()
}

function fitView(ms = 500, pad = 24) {
  graph?.zoomToFit(ms, pad)
  fitted = true
}

function resetView() {
  selected.value = null
  fitView(700, 30)
  // 回到“初始视图的感觉”：恢复自转
  if (props.autoRotate && !reduceMotion)
    startAutoRotate()
}

function focusNode(node: any) {
  if (!graph)
    return
  const x = node.x ?? 0
  const y = node.y ?? 0
  const z = node.z ?? 0
  const dist = Math.hypot(x, y, z)
  const camDist = 90 // 相机距节点的固定距离，保证节点居中且大小适中
  // lookAt 设为节点本身 → 节点始终居中；近原点节点用兜底方向避免相机落在原点
  if (dist < 1) {
    graph.cameraPosition({ x: 0, y: 0, z: camDist }, { x: 0, y: 0, z: 0 }, 800)
    return
  }
  const ratio = (dist + camDist) / dist
  graph.cameraPosition(
    { x: x * ratio, y: y * ratio, z: z * ratio },
    { x, y, z },
    800,
  )
}

function init(width: number, height: number) {
  if (!container.value)
    return
  started = true
  fitted = false

  graph = new ForceGraph3D(container.value, {
    controlType: 'orbit',
    rendererConfig: { alpha: true, antialias: true },
  })
    .backgroundColor('rgba(7,7,19,0)')
    .width(width)
    .height(height)
    .nodeThreeObject((n: any) => {
      const group = new THREE.Group()
      const radius = coreRadius(n.val ?? 2)

      // 柔光星点（径向渐变 sprite，无棱角）
      const mat = new THREE.SpriteMaterial({
        map: glowTexture(n.color),
        transparent: true,
        depthWrite: false,
        blending: THREE.NormalBlending,
      })
      const glow = new THREE.Sprite(mat)
      glow.scale.setScalar(radius * 2.6)
      group.add(glow)

      // 文字标签：悬于星点上方，避免压住节点
      const label: any = new SpriteText(clip(n.label))
      label.color = '#eef2ff'
      label.textHeight = LABEL_HEIGHT[n.group as StarNode['group']] ?? 2
      label.fontWeight = '600'
      label.strokeColor = 'rgba(7,7,19,0.95)'
      label.strokeWidth = 3
      label.material.depthWrite = false
      label.center.set(0.5, 0)
      label.position.set(0, radius * 1.5 + 1.5, 0)
      group.add(label)

      return group
    })
    .linkColor((l: any) => l.color)
    .linkWidth(0.5)
    .linkOpacity(0.35)
    .linkDirectionalParticles((l: any) => l.flow)
    .linkDirectionalParticleWidth(1.2)
    .linkDirectionalParticleSpeed(0.006)
    .warmupTicks(40)
    .cooldownTicks(120)
    .showNavInfo(false)
    .onNodeClick((n: any) => {
      stopAutoRotate()
      // 锁定取景，避免引擎收敛 / 兜底 fit 把聚焦拉回
      fitted = true
      selected.value = n as StarNode
      focusNode(n)
    })
    .onBackgroundClick(() => {
      selected.value = null
    })

  applyData()

  // 让布局更紧凑（减少“太空”观感）
  graph.d3Force('charge')?.strength(-55)
  const linkForce = graph.d3Force('link')
  linkForce?.distance?.(26)

  // 仅做一次初始取景；之后不再自动拉回
  graph.onEngineStop(() => {
    if (!fitted)
      fitView(500, 24)
  })
  // 兜底：引擎若长时间不停，也保证首屏取景一次
  window.setTimeout(() => {
    if (graph && !fitted)
      fitView(500, 24)
  }, 2600)

  // 用户开始拖拽/缩放/平移即停止自转
  const controls = graph.controls?.() as { addEventListener?: (t: string, cb: () => void) => void } | undefined
  controls?.addEventListener?.('start', stopAutoRotate)

  if (props.autoRotate && !reduceMotion)
    startAutoRotate()
}

function tryStart() {
  if (started || !container.value)
    return
  const w = container.value.clientWidth
  const h = container.value.clientHeight
  if (w > 0 && h > 0)
    init(w, h)
}

function setup() {
  reduceMotion = typeof window !== 'undefined'
    && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  empty.value = props.nodes.length === 0
  if (empty.value || !container.value)
    return

  ro = new ResizeObserver(() => {
    if (!container.value)
      return
    if (!started) {
      tryStart()
    }
    else if (graph) {
      graph.width(container.value.clientWidth)
      graph.height(container.value.clientHeight)
    }
  })
  ro.observe(container.value)
  tryStart()
}

function teardown() {
  stopAutoRotate()
  ro?.disconnect()
  ro = null
  if (graph) {
    graph._destructor?.()
    graph = null
  }
  started = false
}

function onOpen() {
  if (selected.value)
    emit('open', selected.value)
}

onMounted(setup)

watch(
  () => [props.nodes, props.links],
  () => {
    empty.value = props.nodes.length === 0
    selected.value = null
    if (started && graph) {
      fitted = false
      applyData()
    }
    else {
      tryStart()
    }
  },
  { deep: false },
)

onBeforeUnmount(teardown)
</script>

<template>
  <div class="starfield-root relative h-full w-full overflow-hidden">
    <div ref="container" class="relative z-10 h-full w-full" />

    <!-- 空态 -->
    <div
      v-if="empty"
      class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400"
    >
      暂无可展示的能力网络
    </div>

    <!-- 控制条 -->
    <div v-if="!empty" class="absolute bottom-3 right-3 z-20 flex flex-col gap-1.5">
      <button
        type="button"
        class="star-ctrl"
        :title="rotating ? '暂停自转' : '开始自转'"
        :aria-label="rotating ? '暂停自转' : '开始自转'"
        @click="toggleRotate"
      >
        <span :class="rotating ? 'icon-[lucide--pause]' : 'icon-[lucide--play]'" />
      </button>
      <button
        type="button"
        class="star-ctrl"
        title="重置视图"
        aria-label="重置视图"
        @click="resetView"
      >
        <span class="icon-[lucide--rotate-ccw]" />
      </button>
    </div>

    <!-- 节点详情浮层 -->
    <Transition name="detail">
      <aside
        v-if="selected"
        class="absolute right-3 top-3 z-30 flex max-h-[calc(100%-1.5rem)] w-[clamp(260px,44%,420px)] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0d0e22]/95 shadow-2xl backdrop-blur"
      >
        <header class="flex items-start gap-2 border-b border-white/8 px-4 py-3">
          <span
            class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
            :style="{ background: selected.color }"
          />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold leading-snug text-white" :title="selected.label">
              {{ selected.label }}
            </p>
            <div class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-white/45">
              <span
                class="rounded px-1.5 py-0.5 font-medium"
                :style="{ background: `${selected.color}22`, color: selected.color }"
              >
                {{ GROUP_LABEL[selected.group] }}
              </span>
              <span v-if="selected.repoName" class="inline-flex items-center gap-1">
                <span class="icon-[lucide--git-branch] text-[10px]" />{{ selected.repoName }}
              </span>
            </div>
          </div>
          <button
            type="button"
            class="shrink-0 rounded-md p-1 text-white/50 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="关闭"
            @click="selected = null"
          >
            <span class="icon-[lucide--x] text-sm" />
          </button>
        </header>

        <div class="min-h-0 flex-1 space-y-3.5 overflow-y-auto px-4 py-3 text-xs">
          <!-- 层级路径 -->
          <div v-if="selected.trail && selected.trail.length" class="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-white/45">
            <span class="icon-[lucide--folder-tree] mr-0.5 text-[11px] text-white/35" />
            <template v-for="(seg, i) in selected.trail" :key="i">
              <span v-if="i > 0" class="icon-[lucide--chevron-right] text-[10px] text-white/25" />
              <span>{{ seg }}</span>
            </template>
          </div>

          <!-- 统计 -->
          <div v-if="selected.group !== 'capability'" class="flex flex-wrap gap-2">
            <span class="inline-flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-white/60">
              <span class="icon-[lucide--list-tree] text-white/40" />
              {{ selected.children?.length ?? 0 }} 直接子项
            </span>
            <span v-if="selected.descendantCount" class="inline-flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-white/60">
              <span class="icon-[lucide--box] text-white/40" />
              {{ selected.descendantCount }} 个子孙节点
            </span>
          </div>

          <!-- 摘要 -->
          <div class="space-y-1">
            <p class="text-[11px] font-medium text-white/40">
              描述
            </p>
            <p v-if="selected.summary" class="leading-relaxed text-white/80">
              {{ selected.summary }}
            </p>
            <p v-else class="text-white/35">
              暂无描述
            </p>
          </div>

          <!-- 关键词（全部） -->
          <div v-if="selected.keywords && selected.keywords.length" class="space-y-1.5">
            <p class="text-[11px] font-medium text-white/40">
              关键词（{{ selected.keywords.length }}）
            </p>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="kw in selected.keywords"
                :key="kw"
                class="rounded-md bg-white/8 px-1.5 py-0.5 text-[11px] text-white/70"
              >
                {{ kw }}
              </span>
            </div>
          </div>

          <!-- 子项（全部） -->
          <div v-if="selected.children && selected.children.length" class="space-y-1.5">
            <p class="text-[11px] font-medium text-white/40">
              {{ selected.group === 'repo' ? '顶层模块' : '包含的子项' }}（{{ selected.children.length }}）
            </p>
            <ul class="space-y-1">
              <li
                v-for="(child, i) in selected.children"
                :key="`${child.title}-${i}`"
                class="flex items-center gap-1.5 text-[11px] text-white/70"
              >
                <span class="h-1.5 w-1.5 shrink-0 rounded-full" :style="{ background: GROUP_COLOR[child.group] }" />
                <span class="truncate" :title="child.title">{{ child.title }}</span>
              </li>
            </ul>
          </div>

          <!-- 目录范围（全部） -->
          <div v-if="selected.paths && selected.paths.length" class="space-y-1.5">
            <p class="text-[11px] font-medium text-white/40">
              目录范围（{{ selected.paths.length }}）
            </p>
            <ul class="space-y-0.5">
              <li
                v-for="p in selected.paths"
                :key="p"
                class="break-all font-mono text-[11px] text-white/55"
              >
                {{ p }}
              </li>
            </ul>
          </div>
        </div>

        <footer class="border-t border-white/8 px-4 py-2.5">
          <button
            type="button"
            class="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-500/90 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-500"
            @click="onOpen"
          >
            <span class="icon-[lucide--arrow-up-right]" />
            {{ selected.repoId && selected.group === 'repo' ? '打开仓库' : '在知识树查看' }}
          </button>
        </footer>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
/* 透明画布叠在 CSS 星云背景之上，营造深邃宇宙氛围 */
.starfield-root {
  background-color: #030208;
  background-image:
    /* 暗角（最上层，压暗四周强化纵深） */
    radial-gradient(125% 110% at 50% 48%, transparent 58%, rgba(0, 0, 0, 0.6) 100%),
    /* 彩色星云团 */ radial-gradient(38% 30% at 16% 18%, rgba(99, 102, 241, 0.3), transparent 70%),
    radial-gradient(42% 34% at 84% 24%, rgba(139, 92, 246, 0.24), transparent 72%),
    radial-gradient(46% 40% at 70% 84%, rgba(45, 212, 191, 0.16), transparent 74%),
    radial-gradient(30% 26% at 38% 64%, rgba(236, 72, 153, 0.12), transparent 70%),
    radial-gradient(34% 30% at 8% 78%, rgba(56, 189, 248, 0.12), transparent 72%),
    /* 顶部银河微光 */ radial-gradient(130% 80% at 50% -10%, rgba(49, 46, 129, 0.5), transparent 60%),
    /* 深空底色 */ radial-gradient(125% 125% at 50% 45%, #0a0a1e 0%, #06060f 52%, #030208 100%);
}

/* 两层星点（不同密度，营造纵深；reduce-motion 时停止闪烁） */
.starfield-root::before,
.starfield-root::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-repeat: repeat;
}

.starfield-root::before {
  background-image:
    radial-gradient(1.4px 1.4px at 12% 22%, rgba(255, 255, 255, 0.9), transparent),
    radial-gradient(1.2px 1.2px at 47% 67%, rgba(255, 255, 255, 0.7), transparent),
    radial-gradient(1.6px 1.6px at 78% 38%, rgba(199, 210, 254, 0.9), transparent),
    radial-gradient(1.2px 1.2px at 30% 85%, rgba(255, 255, 255, 0.6), transparent),
    radial-gradient(1.5px 1.5px at 88% 75%, rgba(255, 255, 255, 0.8), transparent),
    radial-gradient(1.3px 1.3px at 60% 12%, rgba(255, 255, 255, 0.7), transparent);
  background-size: 100% 100%;
  animation: starfield-twinkle 4s ease-in-out infinite;
}

.starfield-root::after {
  background-image:
    radial-gradient(1px 1px at 22% 52%, rgba(255, 255, 255, 0.5), transparent),
    radial-gradient(1px 1px at 63% 18%, rgba(255, 255, 255, 0.45), transparent),
    radial-gradient(1px 1px at 92% 48%, rgba(255, 255, 255, 0.5), transparent),
    radial-gradient(1px 1px at 8% 72%, rgba(255, 255, 255, 0.4), transparent),
    radial-gradient(1px 1px at 41% 33%, rgba(255, 255, 255, 0.4), transparent);
  background-size: 100% 100%;
  animation: starfield-twinkle 6s ease-in-out infinite reverse;
}

@keyframes starfield-twinkle {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .starfield-root::before,
  .starfield-root::after {
    animation: none;
  }
}

.star-ctrl {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgb(255 255 255 / 0.12);
  background: rgb(13 14 28 / 0.78);
  backdrop-filter: blur(8px);
  color: rgb(255 255 255 / 0.7);
  font-size: 14px;
  transition: all 0.15s ease;
}

.star-ctrl:hover {
  background: rgb(255 255 255 / 0.12);
  color: rgb(255 255 255 / 0.95);
  border-color: rgb(255 255 255 / 0.22);
}

.detail-enter-active,
.detail-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.detail-enter-from,
.detail-leave-to {
  opacity: 0;
  transform: translateX(8px);
}

@media (prefers-reduced-motion: reduce) {
  .detail-enter-active,
  .detail-leave-active {
    transition: none;
  }
}
</style>
