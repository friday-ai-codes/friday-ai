<script setup lang="ts">
/**
 * 深度分析子代理集合的展示容器。
 *
 * - 单个：直接渲染一张 DeepAnalysisCard。
 * - 多个：顶部任务 tab + 横向 scroll-snap swiper + 左右箭头 + 序号计数。
 * 每个子代理拥有自己独立的工具调用 / 思考记录（第 1/2 点）。
 */
import type { DeepAnalysisSession } from '~/types/chat'
import DeepAnalysisCard from './DeepAnalysisCard.vue'
interface DeepItem {
 session: DeepAnalysisSession
 taskLabel: string
 status: 'running' | 'done'
}
const props = defineProps<{ items: DeepItem }>
const trackRef = ref<HTMLElement | null>(null)
const activeIndex = ref(0)
const isMulti = computed( => props.items.length > 1)
function goTo(i: number) {
 const clamped = Math.max(0, Math.min(i, props.items.length - 1))
 activeIndex.value = clamped
 const track = trackRef.value
 if (track)
 track.scrollTo({ left: clamped * track.clientWidth, behavior: 'smooth' })
}
let scrollRaf = 0
function onScroll {
 if (scrollRaf)
 return
 scrollRaf = requestAnimationFrame( => {
 scrollRaf = 0
 const track = trackRef.value
 if (!track || track.clientWidth === 0)
 return
 const idx = Math.round(track.scrollLeft / track.clientWidth)
 if (idx !== activeIndex.value)
 activeIndex.value = Math.max(0, Math.min(idx, props.items.length - 1))
 })
}
function onKeydown(e: KeyboardEvent) {
 if (e.key === 'ArrowLeft') {
 e.preventDefault
 goTo(activeIndex.value - 1)
 }
 else if (e.key === 'ArrowRight') {
 e.preventDefault
 goTo(activeIndex.value + 1)
 }
}
function tabLabel(item: DeepItem, i: number): string {
 const t = item.taskLabel || item.session.task_description || ''
 if (!t)
 return `子任务 ${i + 1}`
 return t.length > 14 ? `${t.slice(0, 14)}…`: t
}
</script>
<template>
 <!-- 单个：直接渲染 -->
 <DeepAnalysisCard
 v-if="!isMulti && items.length === 1":session="items[0].session":task-label="items[0].taskLabel":status="items[0].status"
 />
 <!-- 多个：swiper -->
 <div
 v-else-if="isMulti"
 class="dag"
 tabindex="0"
 role="group"
 aria-label="深度分析子任务"
 @keydown="onKeydown"
 >
 <div class="dag-bar">
 <span class="dag-bar-title">
 <span class="icon-[lucide--layers] text-[11px] text-primary" />
 深度分析 · {{ items.length }} 个子任务
 </span>
 <div class="dag-nav">
 <button
 type="button"
 class="dag-arrow":disabled="activeIndex === 0"
 aria-label="上一个深度分析"
 @click="goTo(activeIndex - 1)"
 >
 <span class="icon-[lucide--chevron-left] text-[13px]" />
 </button>
 <span class="dag-counter">{{ activeIndex + 1 }} / {{ items.length }}</span>
 <button
 type="button"
 class="dag-arrow":disabled="activeIndex === items.length - 1"
 aria-label="下一个深度分析"
 @click="goTo(activeIndex + 1)"
 >
 <span class="icon-[lucide--chevron-right] text-[13px]" />
 </button>
 </div>
 </div>
 <div class="dag-tabs">
 <button
 v-for="(item, i) in items":key="item.session.session_id || i"
 type="button"
 class="dag-tab":class="{ 'is-active': i === activeIndex }":title="item.taskLabel || item.session.task_description"
 @click="goTo(i)"
 >
 <span
 class="dag-tab-dot":class="item.status === 'running' ? 'dag-tab-dot--running': 'dag-tab-dot--done'"
 />
 <span class="dag-tab-text">{{ tabLabel(item, i) }}</span>
 </button>
 </div>
 <div ref="trackRef" class="dag-track" @scroll="onScroll">
 <div v-for="(item, i) in items":key="item.session.session_id || i" class="dag-slide">
 <DeepAnalysisCard:session="item.session":task-label="item.taskLabel":status="item.status"
 />
 </div>
 </div>
 </div>
</template>
<style scoped>
.dag {
 border-radius: 0.75rem;
 border: 1px solid hsl(214 32% 91% / 0.7);
 background: hsl(210 40% 98% / 0.4);
 padding: 0.5rem;
 display: flex;
 flex-direction: column;
 gap: 0.5rem;
 outline: none;
}
.dag:focus-visible {
 border-color: hsl(168 76% 42% / 0.45);
 box-shadow: 0 0 0 3px hsl(168 76% 42% / 0.12);
}
.dag-bar {
 display: flex;
 align-items: center;
 justify-content: space-between;
 gap: 0.5rem;
}
.dag-bar-title {
 display: inline-flex;
 align-items: center;
 gap: 0.375rem;
 font-size: 0.6875rem;
 font-weight: 600;
 color: hsl(215 28% 28%);
}
.dag-nav {
 display: inline-flex;
 align-items: center;
 gap: 0.25rem;
}
.dag-arrow {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 width: 1.5rem;
 height: 1.5rem;
 border-radius: 9999px;
 border: 1px solid hsl(214 32% 88% / 0.9);
 background: hsl(0 0% 100% / 0.8);
 color: hsl(215 16% 40%);
 cursor: pointer;
 transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.dag-arrow:hover:not(:disabled) {
 border-color: hsl(168 76% 42% / 0.4);
 background: hsl(168 76% 96% / 0.6);
 color: hsl(168 70% 30%);
}
.dag-arrow:disabled {
 opacity: 0.4;
 cursor: not-allowed;
}
.dag-counter {
 min-width: 2.5rem;
 text-align: center;
 font-size: 0.625rem;
 font-weight: 600;
 color: hsl(215 16% 45%);
 font-variant-numeric: tabular-nums;
}
.dag-tabs {
 display: flex;
 gap: 0.375rem;
 overflow-x: auto;
 padding-bottom: 0.125rem;
 scrollbar-width: thin;
}
.dag-tabs:-webkit-scrollbar {
 height: 4px;
}
.dag-tabs:-webkit-scrollbar-thumb {
 background: hsl(214 32% 86%);
 border-radius: 9999px;
}
.dag-tab {
 display: inline-flex;
 align-items: center;
 gap: 0.3125rem;
 flex-shrink: 0;
 padding: 0.1875rem 0.5rem;
 border-radius: 9999px;
 border: 1px solid hsl(214 32% 88% / 0.9);
 background: hsl(0 0% 100% / 0.7);
 font-size: 0.6875rem;
 color: hsl(215 16% 42%);
 cursor: pointer;
 transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
 font-family: inherit;
 max-width: 12rem;
}
.dag-tab:hover {
 border-color: hsl(168 76% 42% / 0.35);
}
.dag-tab.is-active {
 border-color: hsl(168 76% 42% / 0.55);
 background: hsl(168 76% 96%);
 color: hsl(168 70% 28%);
 font-weight: 600;
}
.dag-tab-dot {
 width: 5px;
 height: 5px;
 border-radius: 50%;
 flex-shrink: 0;
}
.dag-tab-dot--running {
 background: hsl(168 76% 42%);
 animation: dag-pulse 1.5s infinite;
}
.dag-tab-dot--done {
 background: hsl(142 71% 45%);
}
.dag-tab-text {
 overflow: hidden;
 text-overflow: ellipsis;
 white-space: nowrap;
}
.dag-track {
 display: flex;
 overflow-x: auto;
 scroll-snap-type: x mandatory;
 scrollbar-width: none;
 border-radius: 0.5rem;
}
.dag-track:-webkit-scrollbar {
 display: none;
}
.dag-slide {
 flex: 0 0 100%;
 width: 100%;
 min-width: 0;
 scroll-snap-align: start;
 /* 让相邻卡片不互相挤压，保留一点呼吸感 */
 padding-right: 1px;
}
@keyframes dag-pulse {
 0%, 100% {
 opacity: 1;
 }
 50% {
 opacity: 0.4;
 }
}
@media (prefers-reduced-motion: reduce) {
 .dag-track {
 scroll-behavior: auto;
 }
}
.dark .dag {
 border-color: hsl(214 32% 20% / 0.6);
 background: hsl(220 20% 12% / 0.35);
}
.dark .dag-arrow,
.dark .dag-tab {
 background: hsl(220 20% 16% / 0.8);
 border-color: hsl(214 32% 28% / 0.7);
 color: hsl(215 16% 70%);
}
</style>
