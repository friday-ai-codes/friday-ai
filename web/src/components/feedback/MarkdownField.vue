<script setup lang="ts">
/**
 * MarkdownField —— 编辑/预览双 Tab 的 Markdown 输入控件。
 *
 * 输入即原始 Markdown（存库），预览页用 markdown-it 实时渲染（复用
 * MarkdownRenderer）。支持飞书文档链接（markdown-it linkify 自动成链）。
 */
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { Textarea } from '~/components/ui/textarea'

const props = withDefaults(defineProps<{
  modelValue: string
  placeholder?: string
  minHeight?: string
}>(), {
  placeholder: '支持 Markdown 语法，可粘贴飞书文档链接…',
  minHeight: '160px',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'paste': [event: ClipboardEvent]
  'drop': [event: DragEvent]
}>()

const tab = ref<'edit' | 'preview'>('edit')

const value = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<template>
  <Tabs v-model="tab" class="w-full">
    <TabsList class="grid w-40 grid-cols-2">
      <TabsTrigger value="edit">
        编辑
      </TabsTrigger>
      <TabsTrigger value="preview">
        预览
      </TabsTrigger>
    </TabsList>

    <TabsContent value="edit" class="mt-2">
      <Textarea
        v-model="value"
        :placeholder="placeholder"
        :style="{ minHeight }"
        class="resize-y font-mono text-sm"
        @paste="emit('paste', $event)"
        @drop.prevent="emit('drop', $event)"
        @dragover.prevent
      />
    </TabsContent>

    <TabsContent value="preview" class="mt-2">
      <div
        class="rounded-md border border-border bg-muted/20 p-3 overflow-auto"
        :style="{ minHeight }"
      >
        <MarkdownRenderer v-if="value" :content="value" />
        <p v-else class="text-sm text-muted-foreground">
          暂无内容可预览
        </p>
      </div>
    </TabsContent>
  </Tabs>
</template>
