<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import { computed, onMounted, shallowRef } from 'vue'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { mdTokensToPlainText, stripMarkdownSync } from '~/utils/markdownText'

// 行内 markdown 渲染：解析后逐字保留的功能点名/验收项常含 markdown 语法（**加粗**、`code`、
// 链接、标题/列表标记）。用 markdown-it 渲染（html:false 防 XSS）。inline=true 用 renderInline
// 不产生 <p> 包裹，适合单行标题；否则块级渲染。渲染器未就绪时降级为纯文本。
//
// plain=true 只取文字：`renderInline` 不解析块级语法，`#### 标题`、`- [ ] 项`这类前缀会
// 原样显示，树节点名用此模式剥成纯文本。
const props = withDefaults(defineProps<{ text?: string, inline?: boolean, plain?: boolean }>(), {
  text: '',
  inline: true,
  plain: false,
})

const md = shallowRef<MarkdownIt | null>(null)

onMounted(async () => {
  try {
    md.value = await getMarkdownRenderer()
  }
  catch {}
})

const html = computed(() => {
  const src = props.text ?? ''
  if (!md.value)
    return ''
  return props.inline ? md.value.renderInline(src) : md.value.render(src)
})

// 渲染器就绪前先用同步剥壳，避免 `####` 闪一帧后才消失。
const plainText = computed(() => {
  const src = props.text ?? ''
  return md.value ? mdTokensToPlainText(md.value, src) : stripMarkdownSync(src)
})
</script>

<template>
  <span v-if="plain">{{ plainText }}</span>
  <!-- 渲染器就绪前降级纯文本，避免闪烁；就绪后渲染 markdown。 -->
  <span v-else-if="!md">{{ text }}</span>
  <!-- eslint-disable-next-line vue/no-v-html — markdown-it 以 html:false 渲染，无 XSS 风险 -->
  <span
    v-else
    class="md-inline [&_code]:bg-muted [&_code]:px-1 [&_code]:rounded [&_code]:text-[0.9em] [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold [&_p]:inline [&_p]:m-0"
    v-html="html"
  />
</template>
