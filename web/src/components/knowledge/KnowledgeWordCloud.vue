<script setup lang="ts">
/**
 * 知识词云（wordcloud2.js 真词云）
 *
 * 词条来自真实业务维度——能力 / 模块标题（title）与能力关键词（keyword），
 * 权重 = 出现频次 → 字号。采用 wordcloud2.js 的螺旋紧凑填充（带旋转），呈现经典
 * 词云观感；标题用品牌紫蓝、关键词用青绿，按权重在亮度上拉开层次。
 * canvas 按 devicePixelRatio 放大以保证高清。
 */
import type { CloudTerm } from '~/composables/useKnowledgeCapabilities'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import WordCloud from 'wordcloud'

const props = withDefaults(defineProps<{
  terms: CloudTerm[]
  /** 最多展示词条数 */
  max?: number
  /** 最小字号（px） */
  minSize?: number
  /** 最大字号（px） */
  maxSize?: number
}>(), {
  max: 80,
  minSize: 14,
  maxSize: 56,
})

const emit = defineEmits<{
  (e: 'pick', term: CloudTerm): void
}>()

const FONT_FAMILY = 'Inter, ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
const TITLE_HUES = [248, 256, 268]
const KEYWORD_HUES = [168, 190, 210]

function hashHue(text: string, palette: number[]): number {
  let h = 0
  for (let i = 0; i < text.length; i++)
    h = (h * 31 + text.charCodeAt(i)) >>> 0
  return palette[h % palette.length]
}

const container = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
let ro: ResizeObserver | null = null
let rafId = 0

function render() {
  const el = container.value
  const cv = canvas.value
  if (!el || !cv || !WordCloud.isSupported)
    return
  const w = el.clientWidth
  const h = el.clientHeight
  if (w < 2 || h < 2)
    return

  const sorted = [...props.terms].sort((a, b) => b.weight - a.weight).slice(0, props.max)
  if (!sorted.length) {
    const ctx = cv.getContext('2d')
    ctx?.clearRect(0, 0, cv.width, cv.height)
    return
  }

  const maxW = sorted[0].weight
  const minW = sorted[sorted.length - 1].weight
  const span = Math.max(1, maxW - minW)

  const termByText = new Map<string, CloudTerm>()
  const list: [string, number][] = sorted.map((t) => {
    termByText.set(t.text, t)
    return [t.text, t.weight]
  })

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  cv.width = Math.floor(w * dpr)
  cv.height = Math.floor(h * dpr)
  cv.style.width = `${w}px`
  cv.style.height = `${h}px`

  const fontPx = (weight: number) => {
    const norm = (weight - minW) / span
    return (props.minSize + norm * (props.maxSize - props.minSize)) * dpr
  }

  const colorFor = (word: string, weight: number) => {
    const term = termByText.get(word)
    const kind = term?.kind ?? 'keyword'
    const norm = (weight - minW) / span
    const hue = hashHue(word, kind === 'title' ? TITLE_HUES : KEYWORD_HUES)
    const sat = kind === 'title' ? 68 : 60
    const light = Math.round(58 - norm * 22)
    return `hsl(${hue} ${sat}% ${light}%)`
  }

  WordCloud(cv, {
    list,
    fontFamily: FONT_FAMILY,
    fontWeight: '600',
    gridSize: Math.round(6 * dpr),
    weightFactor: (weight: number) => fontPx(weight),
    color: (word: string, weight: string | number) => colorFor(word, Number(weight)),
    backgroundColor: 'transparent',
    rotateRatio: 0.45,
    rotationSteps: 2,
    minRotation: -Math.PI / 6,
    maxRotation: Math.PI / 6,
    drawOutOfBound: false,
    shrinkToFit: true,
    clearCanvas: true,
    click: (item: [string, number, ...unknown[]]) => {
      const term = termByText.get(item?.[0])
      if (term)
        emit('pick', term)
    },
  })
}

function scheduleRender() {
  cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(render)
}

onMounted(() => {
  ro = new ResizeObserver(scheduleRender)
  if (container.value)
    ro.observe(container.value)
  scheduleRender()
})

watch(() => props.terms, scheduleRender, { deep: false })

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  ro?.disconnect()
  ro = null
})
</script>

<template>
  <div ref="container" class="h-full w-full">
    <canvas ref="canvas" />
  </div>
</template>
