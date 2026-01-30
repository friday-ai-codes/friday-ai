<script setup lang="ts">
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import Link from '@tiptap/extension-link'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import Typography from '@tiptap/extension-typography'
import StarterKit from '@tiptap/starter-kit'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { common, createLowlight } from 'lowlight'
const lowlight = createLowlight(common)
interface Props {
 content: string
 class?: string
}
const props = withDefaults(defineProps<Props>, {
 class: '',
})
const editor = useEditor({
 content: props.content,
 editable: false,
 extensions: [
 StarterKit.configure({
 codeBlock: false,
 }),
 Link.configure({
 openOnClick: true,
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
})
// 监听内容变化
watch( => props.content, (value) => {
 if (editor.value && editor.value.getHTML !== value) {
 editor.value.commands.setContent(value, false)
 }
})
onBeforeUnmount( => {
 editor.value?.destroy
})
</script>
<template>
 <div:class="['tiptap-preview', props.class]">
 <EditorContent:editor="editor" class="tiptap-preview-content" />
 </div>
</template>
<style>
.tiptap-preview-content .tiptap {
 outline: none;
}
/* 标题样式 */
.tiptap-preview-content .tiptap h1 {
 font-size: 1.875rem;
 font-weight: 700;
 margin-top: 1.5rem;
 margin-bottom: 0.75rem;
 line-height: 1.2;
}
.tiptap-preview-content .tiptap h1:first-child {
 margin-top: 0;
}
.tiptap-preview-content .tiptap h2 {
 font-size: 1.5rem;
 font-weight: 600;
 margin-top: 1.25rem;
 margin-bottom: 0.5rem;
 line-height: 1.3;
}
.tiptap-preview-content .tiptap h2:first-child {
 margin-top: 0;
}
.tiptap-preview-content .tiptap h3 {
 font-size: 1.25rem;
 font-weight: 600;
 margin-top: 1rem;
 margin-bottom: 0.5rem;
 line-height: 1.4;
}
.tiptap-preview-content .tiptap h3:first-child {
 margin-top: 0;
}
/* 段落 */
.tiptap-preview-content .tiptap p {
 margin-bottom: 0.75rem;
 line-height: 1.6;
}
.tiptap-preview-content .tiptap p:last-child {
 margin-bottom: 0;
}
/* 列表 */
.tiptap-preview-content .tiptap ul,
.tiptap-preview-content .tiptap ol {
 padding-left: 1.5rem;
 margin-bottom: 0.75rem;
}
.tiptap-preview-content .tiptap li {
 margin-bottom: 0.25rem;
}
.tiptap-preview-content .tiptap ul {
 list-style-type: disc;
}
.tiptap-preview-content .tiptap ol {
 list-style-type: decimal;
}
/* 任务列表 */
.tiptap-preview-content .tiptap ul[data-type="taskList"] {
 list-style: none;
 padding-left: 0;
}
.tiptap-preview-content .tiptap ul[data-type="taskList"] li {
 display: flex;
 align-items: flex-start;
 gap: 0.5rem;
}
.tiptap-preview-content .tiptap ul[data-type="taskList"] li > label {
 flex-shrink: 0;
 margin-top: 0.25rem;
}
.tiptap-preview-content .tiptap ul[data-type="taskList"] li > div {
 flex: 1;
}
/* 引用 */
.tiptap-preview-content .tiptap blockquote {
 border-left: 3px solid hsl(var(--border));
 padding-left: 1rem;
 margin: 0.75rem 0;
 color: hsl(var(--muted-foreground));
}
/* 代码 */
.tiptap-preview-content .tiptap code {
 background: hsl(var(--muted));
 padding: 0.2rem 0.4rem;
 border-radius: 0.25rem;
 font-size: 0.875em;
 font-family: ui-monospace, monospace;
}
.tiptap-preview-content .tiptap pre {
 background: hsl(var(--muted));
 border-radius: 0.5rem;
 padding: 1rem;
 margin: 0.75rem 0;
 overflow-x: auto;
}
.tiptap-preview-content .tiptap pre code {
 background: none;
 padding: 0;
 font-size: 0.875rem;
}
/* 链接 */
.tiptap-preview-content .tiptap a {
 color: hsl(var(--primary));
 text-decoration: underline;
}
/* 分隔线 */
.tiptap-preview-content .tiptap hr {
 border: none;
 border-top: 1px solid hsl(var(--border));
 margin: 1.5rem 0;
}
</style>
