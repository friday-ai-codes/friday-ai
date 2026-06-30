<script setup lang="ts">
import mermaid from 'mermaid'
import { onMounted, ref, watch } from 'vue'
import { VueFinalModal } from 'vue-final-modal'

// 流程图渲染：把 mermaid 源码渲染为 SVG；点击放大到全屏弹窗查看。渲染失败回退展示原始源码。
const props = defineProps<{ code: string }>()

let initialized = false
function ensureInit() {
  if (initialized)
    return
  const dark = document.documentElement.classList.contains('dark')
  mermaid.initialize({
    startOnLoad: false,
    theme: dark ? 'dark' : 'default',
    securityLevel: 'strict',
    flowchart: { useMaxWidth: true, htmlLabels: true },
  })
  initialized = true
}

const svg = ref('')
const error = ref(false)
let seq = 0

async function render() {
  const code = (props.code || '').trim()
  if (!code) {
    svg.value = ''
    error.value = false
    return
  }
  try {
    ensureInit()
    seq += 1
    const id = `mermaid-${Date.now()}-${seq}`
    const out = await mermaid.render(id, code)
    svg.value = out.svg
    error.value = false
  }
  catch {
    // 源码非法/不被 mermaid 识别 → 回退展示原文，不抛错。
    svg.value = ''
    error.value = true
  }
}

onMounted(render)
watch(() => props.code, render)

const zoomOpen = ref(false)
</script>

<template>
  <div class="rounded-lg border border-border/50 bg-muted/20 overflow-hidden">
    <div class="flex items-center justify-between px-2.5 py-1.5 border-b border-border/40 bg-muted/30">
      <span class="text-[11px] text-muted-foreground inline-flex items-center gap-1">
        <span class="icon-[lucide--workflow] text-[11px]" /> 流程图
      </span>
      <button
        v-if="svg"
        type="button"
        class="text-[11px] text-primary inline-flex items-center gap-1 hover:underline"
        @click="zoomOpen = true"
      >
        <span class="icon-[lucide--maximize-2] text-[11px]" /> 放大
      </button>
    </div>

    <div v-if="svg" class="p-3 overflow-x-auto [&_svg]:max-w-full [&_svg]:h-auto" v-html="svg" />
    <pre
      v-else
      class="p-3 text-xs font-mono text-muted-foreground whitespace-pre-wrap break-words"
    >{{ props.code }}</pre>
    <p v-if="error" class="px-3 pb-2 text-[11px] text-muted-foreground/70">
      （流程图源码暂无法渲染，已展示原文）
    </p>

    <VueFinalModal
      v-model="zoomOpen"
      class="flex justify-center items-center"
      content-class="bg-card rounded-2xl shadow-2xl border border-border/50 max-w-[92vw] max-h-[92vh] w-full flex flex-col"
      overlay-transition="vfm-fade"
      content-transition="vfm-zoom"
    >
      <header class="flex items-center justify-between px-5 py-3 border-b border-border/50">
        <span class="text-sm font-semibold inline-flex items-center gap-1.5">
          <span class="icon-[lucide--workflow]" /> 流程图
        </span>
        <button
          type="button"
          class="size-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
          aria-label="关闭"
          @click="zoomOpen = false"
        >
          <span class="icon-[lucide--x]" />
        </button>
      </header>
      <div class="flex-1 min-h-0 overflow-auto p-6 [&_svg]:max-w-none [&_svg]:h-auto" v-html="svg" />
    </VueFinalModal>
  </div>
</template>
