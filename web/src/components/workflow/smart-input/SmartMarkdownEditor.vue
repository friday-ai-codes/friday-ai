<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import Bold from '@tiptap/extension-bold'
import BulletList from '@tiptap/extension-bullet-list'
import Code from '@tiptap/extension-code'
import CodeBlock from '@tiptap/extension-code-block'
import Document from '@tiptap/extension-document'
import Heading from '@tiptap/extension-heading'
import History from '@tiptap/extension-history'
import Italic from '@tiptap/extension-italic'
import ListItem from '@tiptap/extension-list-item'
import OrderedList from '@tiptap/extension-ordered-list'
import Paragraph from '@tiptap/extension-paragraph'
import Placeholder from '@tiptap/extension-placeholder'
import Strike from '@tiptap/extension-strike'
import Text from '@tiptap/extension-text'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { createVariableSuggestion, VariableNode } from './extensions'

interface Props {
  modelValue: string
  workflowNodes: WorkflowNode[]
  workflowEdges: WorkflowEdge[]
  currentNodeId: string
  placeholder?: string
  disabled?: boolean
  minRows?: number
  /** 是否显示工具栏 */
  showToolbar?: boolean
  /** 是否为精简模式（侧边栏用） */
  compact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: '',
  disabled: false,
  minRows: 4,
  showToolbar: true,
  compact: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'expand': []
}>()

// Design-time variables from upstream nodes
const workflowNodesRef = computed(() => props.workflowNodes)
const workflowEdgesRef = computed(() => props.workflowEdges)
const currentNodeIdRef = computed(() => props.currentNodeId)

const { designTimeVariables } = useDesignTimeVariables(
  workflowNodesRef,
  workflowEdgesRef,
  currentNodeIdRef,
)

// Track if we're updating from external source to prevent loops
const isUpdatingFromExternal = ref(false)

const editor = useEditor({
  extensions: [
    Document,
    Paragraph,
    Text,
    History,
    Bold,
    Italic,
    Strike,
    Code,
    CodeBlock,
    Heading.configure({ levels: [1, 2, 3] }),
    BulletList,
    OrderedList,
    ListItem,
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
    VariableNode,
    createVariableSuggestion({
      items: () => designTimeVariables.value,
    }),
  ],
  content: parseContent(props.modelValue),
  editable: !props.disabled,
  onUpdate: () => {
    if (!isUpdatingFromExternal.value) {
      emit('update:modelValue', serializeContent())
    }
  },
  editorProps: {
    attributes: {
      class: 'outline-none prose prose-sm dark:prose-invert max-w-none',
    },
  },
})

/**
 * Serialize editor content to string with {{path}} syntax
 */
function serializeContent(): string {
  if (!editor.value)
    return ''

  const doc = editor.value.getJSON()
  return serializeNode(doc)
}

/**
 * Recursively serialize TipTap node to markdown-like string
 */
function serializeNode(node: any, depth = 0, listIndex?: number): string {
  if (!node)
    return ''

  switch (node.type) {
    case 'doc':
      return (node.content || []).map((n: any) => serializeNode(n, depth)).join('\n')

    case 'paragraph':
      return serializeInlineContent(node.content || [])

    case 'heading': {
      const level = node.attrs?.level || 1
      const prefix = '#'.repeat(level)
      return `${prefix} ${serializeInlineContent(node.content || [])}`
    }

    case 'bulletList':
      return (node.content || []).map((n: any) => serializeNode(n, depth)).join('\n')

    case 'orderedList':
      return (node.content || []).map((n: any, i: number) => serializeNode(n, depth, i + 1)).join('\n')

    case 'listItem': {
      const prefix = typeof listIndex === 'number' ? `${listIndex}. ` : '- '
      const content = (node.content || []).map((n: any) => serializeNode(n, depth + 1)).join('\n')
      return `${prefix}${content}`
    }

    case 'codeBlock': {
      const code = serializeInlineContent(node.content || [])
      return `\`\`\`\n${code}\n\`\`\``
    }

    default:
      return serializeInlineContent(node.content || [])
  }
}

/**
 * Serialize inline content (text, bold, italic, code, variable)
 */
function serializeInlineContent(content: any[]): string {
  return content.map((node) => {
    if (node.type === 'text') {
      let text = node.text || ''
      const marks = node.marks || []

      for (const mark of marks) {
        switch (mark.type) {
          case 'bold':
            text = `**${text}**`
            break
          case 'italic':
            text = `*${text}*`
            break
          case 'code':
            text = `\`${text}\``
            break
          case 'strike':
            text = `~~${text}~~`
            break
        }
      }
      return text
    }
    else if (node.type === 'variable') {
      return `{{${node.attrs?.path || ''}}}`
    }
    return ''
  }).join('')
}

/**
 * Parse markdown-like string to editor content
 */
function parseContent(value: string): object {
  const lines = value.split('\n')
  const content: object[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Code block
    if (line.startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      content.push({
        type: 'codeBlock',
        content: [{ type: 'text', text: codeLines.join('\n') }],
      })
      i++
      continue
    }

    // Heading
    // eslint-disable-next-line regexp/no-super-linear-backtracking
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/)
    if (headingMatch) {
      content.push({
        type: 'heading',
        attrs: { level: headingMatch[1].length },
        content: parseInlineContent(headingMatch[2]),
      })
      i++
      continue
    }

    // Bullet list item
    if (/^[-*]\s+/.test(line)) {
      const listItems: object[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        const itemText = lines[i].replace(/^[-*]\s+/, '')
        listItems.push({
          type: 'listItem',
          content: [{ type: 'paragraph', content: parseInlineContent(itemText) }],
        })
        i++
      }
      content.push({ type: 'bulletList', content: listItems })
      continue
    }

    // Ordered list item
    if (/^\d+\.\s+/.test(line)) {
      const listItems: object[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        const itemText = lines[i].replace(/^\d+\.\s+/, '')
        listItems.push({
          type: 'listItem',
          content: [{ type: 'paragraph', content: parseInlineContent(itemText) }],
        })
        i++
      }
      content.push({ type: 'orderedList', content: listItems })
      continue
    }

    // Regular paragraph
    content.push({
      type: 'paragraph',
      content: line ? parseInlineContent(line) : undefined,
    })
    i++
  }

  return {
    type: 'doc',
    content: content.length > 0 ? content : [{ type: 'paragraph' }],
  }
}

/**
 * Parse inline markdown (bold, italic, code, variables)
 */
function parseInlineContent(text: string): object[] {
  const result: object[] = []
  // Combined regex for variables, bold, italic, code, strike
  const regex = /\{\{[^}]+\}\}|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|~~[^~]+~~/g
  let lastIndex = 0
  let match

  // eslint-disable-next-line no-cond-assign
  while ((match = regex.exec(text)) !== null) {
    // Add text before match
    if (match.index > lastIndex) {
      result.push({ type: 'text', text: text.slice(lastIndex, match.index) })
    }

    const matched = match[0]

    // Variable
    if (matched.startsWith('{{') && matched.endsWith('}}')) {
      const path = matched.slice(2, -2)
      const variable = designTimeVariables.value.find(v => v.path === path)
      result.push({
        type: 'variable',
        attrs: {
          path,
          label: variable?.label ?? path,
          nodeId: variable?.nodeId ?? '',
          outputName: variable?.key ?? '',
        },
      })
    }
    // Bold
    else if (matched.startsWith('**') && matched.endsWith('**')) {
      result.push({
        type: 'text',
        text: matched.slice(2, -2),
        marks: [{ type: 'bold' }],
      })
    }
    // Italic
    else if (matched.startsWith('*') && matched.endsWith('*')) {
      result.push({
        type: 'text',
        text: matched.slice(1, -1),
        marks: [{ type: 'italic' }],
      })
    }
    // Code
    else if (matched.startsWith('`') && matched.endsWith('`')) {
      result.push({
        type: 'text',
        text: matched.slice(1, -1),
        marks: [{ type: 'code' }],
      })
    }
    // Strike
    else if (matched.startsWith('~~') && matched.endsWith('~~')) {
      result.push({
        type: 'text',
        text: matched.slice(2, -2),
        marks: [{ type: 'strike' }],
      })
    }

    lastIndex = regex.lastIndex
  }

  // Add remaining text
  if (lastIndex < text.length) {
    result.push({ type: 'text', text: text.slice(lastIndex) })
  }

  return result.length > 0 ? result : []
}

// Toolbar actions
function toggleBold() {
  editor.value?.chain().focus().toggleBold().run()
}

function toggleItalic() {
  editor.value?.chain().focus().toggleItalic().run()
}

function toggleCode() {
  editor.value?.chain().focus().toggleCode().run()
}

function toggleBulletList() {
  editor.value?.chain().focus().toggleBulletList().run()
}

function toggleOrderedList() {
  editor.value?.chain().focus().toggleOrderedList().run()
}

function toggleCodeBlock() {
  editor.value?.chain().focus().toggleCodeBlock().run()
}

function setHeading(level: 1 | 2 | 3) {
  editor.value?.chain().focus().toggleHeading({ level }).run()
}

// Check active states
function isActive(name: string, attrs?: Record<string, any>) {
  return editor.value?.isActive(name, attrs) ?? false
}

// Sync external value changes to editor
watch(() => props.modelValue, (newValue) => {
  if (!editor.value)
    return

  const currentValue = serializeContent()
  if (newValue !== currentValue) {
    isUpdatingFromExternal.value = true
    editor.value.commands.setContent(parseContent(newValue))
    nextTick(() => {
      isUpdatingFromExternal.value = false
    })
  }
})

// Update editable state
watch(() => props.disabled, (disabled) => {
  editor.value?.setEditable(!disabled)
})

onBeforeUnmount(() => {
  editor.value?.destroy()
})

// Expose editor for parent component
defineExpose({
  editor,
  focus: () => editor.value?.commands.focus(),
})
</script>

<template>
  <div
    class="smart-markdown-editor rounded-lg border border-border/50 bg-background/50 overflow-hidden"
    :class="{ 'opacity-50 cursor-not-allowed': disabled }"
  >
    <!-- Toolbar -->
    <TooltipProvider v-if="showToolbar && !disabled" :delay-duration="300">
      <div
        class="flex items-center gap-0.5 px-2 py-1 border-b border-border/30 bg-muted/30"
      >
        <!-- Text formatting -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('bold') }"
              @click="toggleBold"
            >
              <span class="icon-[lucide--bold] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>粗体 (Ctrl+B)</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('italic') }"
              @click="toggleItalic"
            >
              <span class="icon-[lucide--italic] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>斜体 (Ctrl+I)</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('code') }"
              @click="toggleCode"
            >
              <span class="icon-[lucide--code] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>行内代码</TooltipContent>
        </Tooltip>

        <div class="w-px h-4 bg-border/50 mx-1" />

        <!-- Headings (compact mode only shows H1/H2) -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('heading', { level: 1 }) }"
              @click="setHeading(1)"
            >
              <span class="text-xs font-bold">H1</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>标题 1</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('heading', { level: 2 }) }"
              @click="setHeading(2)"
            >
              <span class="text-xs font-bold">H2</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>标题 2</TooltipContent>
        </Tooltip>
        <Tooltip v-if="!compact">
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('heading', { level: 3 }) }"
              @click="setHeading(3)"
            >
              <span class="text-xs font-bold">H3</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>标题 3</TooltipContent>
        </Tooltip>

        <div class="w-px h-4 bg-border/50 mx-1" />

        <!-- Lists -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('bulletList') }"
              @click="toggleBulletList"
            >
              <span class="icon-[lucide--list] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>无序列表</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('orderedList') }"
              @click="toggleOrderedList"
            >
              <span class="icon-[lucide--list-ordered] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>有序列表</TooltipContent>
        </Tooltip>

        <div class="w-px h-4 bg-border/50 mx-1" />

        <!-- Code block -->
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              :class="{ 'bg-accent': isActive('codeBlock') }"
              @click="toggleCodeBlock"
            >
              <span class="icon-[lucide--file-code] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>代码块</TooltipContent>
        </Tooltip>

        <!-- Expand button -->
        <div class="flex-1" />
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              @click="$emit('expand')"
            >
              <span class="icon-[lucide--maximize-2] w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>放大编辑</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>

    <!-- Editor content -->
    <div
      class="px-3 py-2 text-sm text-foreground overflow-y-auto"
      :class="compact ? 'max-h-40' : 'max-h-64'"
      :style="{ minHeight: `${minRows * 1.5}rem` }"
    >
      <EditorContent :editor="editor" />
    </div>

    <!-- Footer hint -->
    <div class="px-3 py-1.5 border-t border-border/30 bg-muted/20">
      <p v-pre class="text-[10px] text-muted-foreground">
        输入 <code class="bg-muted px-1 py-0.5 rounded text-primary">{{</code> 插入变量
      </p>
    </div>
  </div>
</template>

<style>
/* Prose styling overrides for the editor */
.smart-markdown-editor .ProseMirror {
  min-height: inherit;
}

.smart-markdown-editor .ProseMirror p {
  margin: 0.25em 0;
}

.smart-markdown-editor .ProseMirror h1,
.smart-markdown-editor .ProseMirror h2,
.smart-markdown-editor .ProseMirror h3 {
  margin: 0.5em 0 0.25em;
  font-weight: 600;
}

.smart-markdown-editor .ProseMirror h1 {
  font-size: 1.25em;
}

.smart-markdown-editor .ProseMirror h2 {
  font-size: 1.125em;
}

.smart-markdown-editor .ProseMirror h3 {
  font-size: 1em;
}

.smart-markdown-editor .ProseMirror ul,
.smart-markdown-editor .ProseMirror ol {
  padding-left: 1.25em;
  margin: 0.25em 0;
}

.smart-markdown-editor .ProseMirror code {
  background: var(--muted);
  padding: 0.1em 0.3em;
  border-radius: 0.25em;
  font-size: 0.9em;
}

.smart-markdown-editor .ProseMirror pre {
  background: var(--muted);
  padding: 0.75em 1em;
  border-radius: 0.375em;
  margin: 0.5em 0;
  overflow-x: auto;
}

.smart-markdown-editor .ProseMirror pre code {
  background: none;
  padding: 0;
}

/* Placeholder styling — 提高占位文字可读性（原 0.5 过淡看不清） */
.smart-markdown-editor .ProseMirror p.is-editor-empty:first-child::before {
  content: attr(data-placeholder);
  float: left;
  color: var(--color-muted-foreground);
  opacity: 0.8;
  pointer-events: none;
  height: 0;
}

/* 变量 chip 内文字不被 prose 的 code/链接样式干扰 */
.smart-markdown-editor .variable-chip-view code {
  background: none;
  padding: 0;
  color: inherit;
}
</style>
