<script setup lang="ts">
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import Typography from '@tiptap/extension-typography'
import StarterKit from '@tiptap/starter-kit'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { common, createLowlight } from 'lowlight'
import BaseModal from '~/components/modal/BaseModal.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

const props = withDefaults(defineProps<Props>(), {
  placeholder: '请输入内容，支持 Markdown 语法...',
  height: undefined,
  minHeight: '200px',
  maxHeight: undefined,
  editable: true,
  stickyToolbar: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const lowlight = createLowlight(common)

interface Props {
  modelValue: string
  placeholder?: string
  /** 固定高度（与 minHeight/maxHeight 互斥） */
  height?: string
  /** 最小高度 */
  minHeight?: string
  /** 最大高度，超出后内容区滚动 */
  maxHeight?: string
  editable?: boolean
  /** 工具栏是否 sticky */
  stickyToolbar?: boolean
}

// 计算容器样式
const containerStyle = computed(() => {
  if (props.height) {
    return { minHeight: props.height }
  }
  return {
    minHeight: props.minHeight,
    maxHeight: props.maxHeight,
  }
})

// 计算内容区样式
const contentStyle = computed(() => {
  if (props.height) {
    return { minHeight: `calc(${props.height} - 48px)` }
  }
  if (props.maxHeight) {
    // 有最大高度时，内容区需要能滚动
    return { minHeight: props.minHeight ? `calc(${props.minHeight} - 48px)` : '152px' }
  }
  return { minHeight: props.minHeight ? `calc(${props.minHeight} - 48px)` : '152px' }
})

const editor = useEditor({
  content: props.modelValue,
  editable: props.editable,
  extensions: [
    StarterKit.configure({
      codeBlock: false,
    }),
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
    Link.configure({
      openOnClick: false,
      HTMLAttributes: {
        class: 'text-primary underline',
      },
    }),
    CodeBlockLowlight.configure({
      lowlight,
    }),
    TaskList,
    TaskItem.configure({
      nested: true,
    }),
    Typography,
  ],
  onUpdate: ({ editor }) => {
    emit('update:modelValue', editor.getHTML())
  },
})

// 链接输入弹窗
const linkDialogOpen = ref(false)
const linkUrl = ref('')

function openLinkDialog() {
  linkUrl.value = ''
  linkDialogOpen.value = true
}

function confirmLink() {
  if (linkUrl.value) {
    editor.value?.chain().focus().setLink({ href: linkUrl.value }).run()
  }
  linkDialogOpen.value = false
}

// 监听外部值变化
watch(() => props.modelValue, (value) => {
  if (editor.value && editor.value.getHTML() !== value) {
    editor.value.commands.setContent(value)
  }
})

// 监听 editable 变化
watch(() => props.editable, (editable) => {
  editor.value?.setEditable(editable)
})

onBeforeUnmount(() => {
  editor.value?.destroy()
})

// 工具栏按钮
function toggleBold() {
  editor.value?.chain().focus().toggleBold().run()
}
function toggleItalic() {
  editor.value?.chain().focus().toggleItalic().run()
}
function toggleStrike() {
  editor.value?.chain().focus().toggleStrike().run()
}
function toggleCode() {
  editor.value?.chain().focus().toggleCode().run()
}
function toggleHeading(level: 1 | 2 | 3) {
  editor.value?.chain().focus().toggleHeading({ level }).run()
}
function toggleBulletList() {
  editor.value?.chain().focus().toggleBulletList().run()
}
function toggleOrderedList() {
  editor.value?.chain().focus().toggleOrderedList().run()
}
function toggleTaskList() {
  editor.value?.chain().focus().toggleTaskList().run()
}
function toggleBlockquote() {
  editor.value?.chain().focus().toggleBlockquote().run()
}
function toggleCodeBlock() {
  editor.value?.chain().focus().toggleCodeBlock().run()
}
function setLink() {
  openLinkDialog()
}
function unsetLink() {
  editor.value?.chain().focus().unsetLink().run()
}
</script>

<template>
  <div class="tiptap-editor-wrapper rounded-xl border border-border bg-background overflow-hidden" :style="containerStyle">
    <!-- 工具栏 -->
    <TooltipProvider v-if="editable" :delay-duration="300">
      <div
        class="flex flex-wrap items-center gap-0.5 p-2 border-b border-border bg-muted/30"
        :class="{ 'sticky top-0 z-10': stickyToolbar }"
      >
        <!-- 标题 -->
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('heading', { level: 1 }) }"
              @click="toggleHeading(1)"
            >
              <span class="icon-[lucide--heading-1] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>标题 1</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('heading', { level: 2 }) }"
              @click="toggleHeading(2)"
            >
              <span class="icon-[lucide--heading-2] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>标题 2</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('heading', { level: 3 }) }"
              @click="toggleHeading(3)"
            >
              <span class="icon-[lucide--heading-3] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>标题 3</TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border mx-1" />

        <!-- 格式 -->
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('bold') }"
              @click="toggleBold"
            >
              <span class="icon-[lucide--bold] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>粗体</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('italic') }"
              @click="toggleItalic"
            >
              <span class="icon-[lucide--italic] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>斜体</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('strike') }"
              @click="toggleStrike"
            >
              <span class="icon-[lucide--strikethrough] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>删除线</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('code') }"
              @click="toggleCode"
            >
              <span class="icon-[lucide--code] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>行内代码</TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border mx-1" />

        <!-- 列表 -->
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('bulletList') }"
              @click="toggleBulletList"
            >
              <span class="icon-[lucide--list] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>无序列表</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('orderedList') }"
              @click="toggleOrderedList"
            >
              <span class="icon-[lucide--list-ordered] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>有序列表</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('taskList') }"
              @click="toggleTaskList"
            >
              <span class="icon-[lucide--list-checks] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>任务列表</TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border mx-1" />

        <!-- 块级 -->
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('blockquote') }"
              @click="toggleBlockquote"
            >
              <span class="icon-[lucide--quote] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>引用</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('codeBlock') }"
              @click="toggleCodeBlock"
            >
              <span class="icon-[lucide--file-code] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>代码块</TooltipContent>
        </Tooltip>

        <div class="w-px h-5 bg-border mx-1" />

        <!-- 链接 -->
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              type="button"
              class="toolbar-btn"
              :class="{ 'is-active': editor?.isActive('link') }"
              @click="editor?.isActive('link') ? unsetLink() : setLink()"
            >
              <span class="icon-[lucide--link] text-base" />
            </button>
          </TooltipTrigger>
          <TooltipContent>链接</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>

    <!-- 编辑区 -->
    <EditorContent :editor="editor" class="tiptap-content" :style="contentStyle" />

    <!-- 链接输入弹窗 -->
    <BaseModal
      v-model="linkDialogOpen"
      title="插入链接"
      size="sm"
    >
      <div class="space-y-4">
        <div class="space-y-2">
          <Label for="link-url">链接地址</Label>
          <Input
            id="link-url"
            v-model="linkUrl"
            placeholder="https://example.com"
            class="h-10"
            @keydown.enter="confirmLink"
          />
        </div>
      </div>

      <template #footer>
        <div class="flex justify-end gap-3 w-full">
          <Button variant="outline" @click="linkDialogOpen = false">
            取消
          </Button>
          <Button :disabled="!linkUrl" @click="confirmLink">
            确定
          </Button>
        </div>
      </template>
    </BaseModal>
  </div>
</template>

<style>
.tiptap-editor-wrapper {
  display: flex;
  flex-direction: column;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 0.375rem;
  color: hsl(var(--muted-foreground));
  transition: all 0.15s;
}

.toolbar-btn:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.toolbar-btn.is-active {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}

.tiptap-content {
  flex: 1;
  overflow-y: auto;
}

.tiptap-content .tiptap {
  padding: 1rem;
  outline: none;
  min-height: 100%;
}

.tiptap-content .tiptap p.is-editor-empty:first-child::before {
  content: attr(data-placeholder);
  float: left;
  color: hsl(var(--muted-foreground));
  pointer-events: none;
  height: 0;
}

/* 标题样式 */
.tiptap-content .tiptap h1 {
  font-size: 1.875rem;
  font-weight: 700;
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
  line-height: 1.2;
}

.tiptap-content .tiptap h2 {
  font-size: 1.5rem;
  font-weight: 600;
  margin-top: 1.25rem;
  margin-bottom: 0.5rem;
  line-height: 1.3;
}

.tiptap-content .tiptap h3 {
  font-size: 1.25rem;
  font-weight: 600;
  margin-top: 1rem;
  margin-bottom: 0.5rem;
  line-height: 1.4;
}

/* 段落 */
.tiptap-content .tiptap p {
  margin-bottom: 0.75rem;
  line-height: 1.6;
}

/* 列表 */
.tiptap-content .tiptap ul,
.tiptap-content .tiptap ol {
  padding-left: 1.5rem;
  margin-bottom: 0.75rem;
}

.tiptap-content .tiptap li {
  margin-bottom: 0.25rem;
}

.tiptap-content .tiptap ul {
  list-style-type: disc;
}

.tiptap-content .tiptap ol {
  list-style-type: decimal;
}

/* 任务列表 */
.tiptap-content .tiptap ul[data-type='taskList'] {
  list-style: none;
  padding-left: 0;
}

.tiptap-content .tiptap ul[data-type='taskList'] li {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}

.tiptap-content .tiptap ul[data-type='taskList'] li > label {
  flex-shrink: 0;
  margin-top: 0.25rem;
}

.tiptap-content .tiptap ul[data-type='taskList'] li > div {
  flex: 1;
}

/* 引用 */
.tiptap-content .tiptap blockquote {
  border-left: 3px solid hsl(var(--border));
  padding-left: 1rem;
  margin: 0.75rem 0;
  color: hsl(var(--muted-foreground));
}

/* 代码 */
.tiptap-content .tiptap code {
  background: hsl(var(--muted));
  padding: 0.2rem 0.4rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
  font-family: ui-monospace, monospace;
}

.tiptap-content .tiptap pre {
  background: hsl(var(--muted));
  border-radius: 0.5rem;
  padding: 1rem;
  margin: 0.75rem 0;
  overflow-x: auto;
}

.tiptap-content .tiptap pre code {
  background: none;
  padding: 0;
  font-size: 0.875rem;
}

/* 链接 */
.tiptap-content .tiptap a {
  color: hsl(var(--primary));
  text-decoration: underline;
}

/* 分隔线 */
.tiptap-content .tiptap hr {
  border: none;
  border-top: 1px solid hsl(var(--border));
  margin: 1.5rem 0;
}
</style>
