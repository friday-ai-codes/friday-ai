<script setup lang="ts">
/**
 * PromptEditor — Prompt 编辑抽屉主容器（Phase Plan 交付核心）
 *
 * 职责：
 * - 以 shadcn-vue Sheet 右侧抽屉承载 4-Tab 布局（基础信息 / 正文编辑 / 预览 / 版本历史）
 * - Sheet 宽度覆写 `sm:!max-w-3xl`，强制绕开 shadcn 默认 `sm:max-w-sm`
 * - 所有 TabsContent 均 `:force-mount="true"`，防止 CodeMirror 实例在 Tab 切换时被销毁
 * - editedBody / editedTitle / editedDescription / editedVariablesSchema 状态提升到本组件
 * 外层 ref，双保险即使 force-mount 未生效也不丢输入
 * - 脏检测（字节级比较当前编辑值 vs currentPrompt.active_version.body 等字段），
 * 保存按钮 disabled 当 !isDirty
 * - 保存流程：useConfirmDialog 二次确认 → store.updatePrompt(id, payload) → 成功 toast →
 * emit update:open=false 关闭抽屉
 * - 关闭拦截：dirty=true 时 useConfirmDialog destructive 二次确认，取消则强制
 * emit update:open=true 保持抽屉打开
 * - 创建模式（mode='create'）隐藏 版本历史 Tab，保存流程抛错让页面层走 store.createPrompt
 * （create 完整 payload 所需的 slug/category/scope 字段由页面层通过 store 直接调用）
 *
 * 上游依赖（Wave + Wave 全链路消费）：
 * - ~/stores/prompts:usePromptsStore 全部 state 与 actions
 * - ~/composables/useConfirmDialog / useToast / useErrorHandler
 * - ./PromptBodyEditor / PromptVariablePanel / PromptMetadataForm
 * / VariableSchemaEditor / PromptPreviewPanel / PromptVersionList
 *
 * 下游（Plan）：
 * - 系统级页面 `pages/admin/prompts/index.vue`
 * - 空间级页面 `pages/spaces/[id]/prompts.vue`
 * 两个页面将 import 本组件并通过 v-model:open 控制抽屉开合。
 */
import type { PromptDetail, PromptVersion, VariableSpec } from '~/types/prompts'
import { Button } from '~/components/ui/button'
import {
 Sheet,
 SheetContent,
 SheetDescription,
 SheetFooter,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
import {
 Tabs,
 TabsContent,
 TabsList,
 TabsTrigger,
} from '~/components/ui/tabs'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { usePromptsStore } from '~/stores/prompts'
import PromptBodyEditor from './PromptBodyEditor.vue'
import PromptMetadataForm from './PromptMetadataForm.vue'
import PromptPreviewPanel from './PromptPreviewPanel.vue'
import PromptVariablePanel from './PromptVariablePanel.vue'
import PromptVersionList from './PromptVersionList.vue'
import VariableSchemaEditor from './VariableSchemaEditor.vue'
const props = defineProps<{
 open: boolean
 mode: 'edit' | 'create'
 /** 空间级页面传入；系统级页面不传。当前组件仅透传给 store，不主动切换 project */
 spaceId?: string
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
}>
const store = usePromptsStore
const { confirm } = useConfirmDialog
const { success } = useToast
const { handleError } = useErrorHandler
// ============================================================================
// Store state 桥接
// ============================================================================
// store 在运行时会自动解包 ref，而单测中又可能直接注入 ref-like 对象。
// 这里统一兼容两种形态，避免 currentPrompt 为 null 时继续访问 null.value。
interface RefLike<T> { value: T }
function readStoreState<T>(state: T | RefLike<T>): T {
 if (state && typeof state === 'object' && 'value' in state) {
 return (state as RefLike<T>).value
 }
 return state as T
}
const currentPrompt = computed<PromptDetail | null>( =>
 readStoreState<PromptDetail | null>(store.currentPrompt as PromptDetail | null | RefLike<PromptDetail | null>),
)
const versionsList = computed<PromptVersion>( =>
 readStoreState<PromptVersion>(store.versions as PromptVersion | RefLike<PromptVersion>),
)
const isSaving = computed<boolean>( =>
 readStoreState<boolean>(store.saving as boolean | RefLike<boolean>),
)
// ============================================================================
// 可写字段本地状态（状态提升：所有 Tab 共享外层 ref，防止 Tab 切换丢失）
// ============================================================================
const activeTab = ref<'metadata' | 'body' | 'preview' | 'versions'>('metadata')
const editedTitle = ref<string>('')
const editedDescription = ref<string>('')
const editedBody = ref<string>('')
const editedVariablesSchema = ref<Record<string, VariableSpec>>({})
/**
 * 同步 currentPrompt → 本地编辑态。
 * 在 currentPrompt 加载完成、切换到其他 Prompt 或 create 模式重置时触发。
 */
watch(
 currentPrompt,
 (p) => {
 if (p) {
 editedTitle.value = p.title
 editedDescription.value = p.description
 editedBody.value = p.active_version?.body ?? ''
 editedVariablesSchema.value = { ...(p.active_version?.variables_schema ?? {}) }
 }
 else if (props.mode === 'create') {
 editedTitle.value = ''
 editedDescription.value = ''
 editedBody.value = ''
 editedVariablesSchema.value = {}
 }
 },
 { immediate: true },
)
// ============================================================================
// 脏检测（与 currentPrompt.active_version 字节级比较，对齐 契约）
//
// 系统内置 Prompt(is_builtin=true)的 title/description 受代码契约约束、
// 前端只读展示，不应参与脏检测——否则即使用户没有任何输入，按钮也可能因
// 表单 watch 触发的极早期同步差异被错误点亮。
// ============================================================================
const isDirty = computed<boolean>( => {
 if (props.mode === 'create') {
 return (
 editedTitle.value.trim !== ''
 || editedDescription.value.trim !== ''
 || editedBody.value.trim !== ''
 )
 }
 const p = currentPrompt.value
 if (!p)
 return false
 // 仅在非内置 Prompt 上比较 title/description（内置 Prompt 这两字段锁死）
 if (!p.is_builtin) {
 if (editedTitle.value !== p.title)
 return true
 if (editedDescription.value !== p.description)
 return true
 }
 if (editedBody.value !== (p.active_version?.body ?? ''))
 return true
 if (
 JSON.stringify(editedVariablesSchema.value)
 !== JSON.stringify(p.active_version?.variables_schema ?? {})
 ) {
 return true
 }
 return false
})
// ============================================================================
// 子组件事件 handlers
// ============================================================================
function onMetadataChange(values: { title: string, description: string }): void {
 editedTitle.value = values.title
 editedDescription.value = values.description
}
function onBodyChange(value: string): void {
 editedBody.value = value
}
function onSchemaChange(value: Record<string, VariableSpec>): void {
 editedVariablesSchema.value = value
}
function onSchemaParseError(_message: string): void {
 // 解析失败时保留旧值；错误提示由 VariableSchemaEditor 自身内联渲染
}
// ============================================================================
// 保存流程
// ============================================================================
async function handleSave: Promise<void> {
 if (!isDirty.value)
 return
 // 二次确认（work item §Copywriting "确认保存" AlertDialog）
 // TODO Plan：使用专用 Dialog 承载 change_note Input（useConfirmDialog 当前不支持 Input slot）
 const ok = await confirm({
 title: '确认保存',
 description: '保存后将自动追加版本快照。请在保存前确认变更内容。',
 confirmText: '确认保存',
 })
 if (!ok)
 return
 try {
 if (props.mode === 'create') {
 // create 完整 payload 需要 slug/category/scope 这些超出 PromptEditor 职责的字段。
 // 由页面层（Plan）在点击 "+ 新建 Prompt" 时直接构造 payload 调 store.createPrompt。
 // 本组件在 create 模式下仅承载表单交互，实际提交交给上层。
 throw new Error('创建模式请由页面层直接调用 store.createPrompt')
 }
 const p = currentPrompt.value
 if (!p)
 return
 // 内置 Prompt 的 title/description 锁死，不下发以避免后端契约值被前端覆盖。
 const payload: Parameters<typeof store.updatePrompt>[1] = p.is_builtin
 ? {
 body: editedBody.value,
 variables_schema: editedVariablesSchema.value,
 change_note: '',
 }: {
 title: editedTitle.value,
 description: editedDescription.value,
 body: editedBody.value,
 variables_schema: editedVariablesSchema.value,
 change_note: '',
 }
 await store.updatePrompt(p.id, payload)
 success('保存成功')
 emit('update:open', false)
 }
 catch (e) {
 handleError(e, '保存 Prompt')
 }
}
// ============================================================================
// 关闭拦截 —— 脏数据时二次确认
// ============================================================================
async function handleOpenChange(newOpen: boolean): Promise<void> {
 if (!newOpen && isDirty.value) {
 const ok = await confirm({
 title: '放弃未保存的更改？',
 description: '当前 Prompt 正文存在未保存的修改，关闭抽屉将丢失这些更改。',
 confirmText: '放弃更改',
 variant: 'destructive',
 })
 if (!ok) {
 // 拦截关闭：强制保持 open=true
 emit('update:open', true)
 return
 }
 }
 emit('update:open', newOpen)
 if (!newOpen) {
 // 关闭后清理 store 中 currentPrompt，重置 Tab 到默认
 store.clearCurrent
 activeTab.value = 'metadata'
 }
}
</script>
<template>
 <Sheet:open="open" @update:open="handleOpenChange">
 <SheetContent
 side="right"
 class="sm:max-w-3xl! w-full flex flex-col gap-0 bg-background"
 >
 <!-- Header：图标 + 标题 + slug code 标签 + dirty 指示 -->
 <SheetHeader class="border-b border-border/60 bg-card px-6 py-4 gap-1.5">
 <div class="flex items-start gap-3">
 <div class="shrink-0 mt-0.5 w-9 rounded-lg bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--file-text] text-primary text-lg" />
 </div>
 <div class="min-w-0 flex-1 space-y-1">
 <SheetTitle class="text-base font-semibold text-foreground leading-tight flex items-center gap-2">
 <span class="truncate">
 {{ mode === 'create' ? '新建 Prompt': (currentPrompt?.title ?? '加载中…') }}
 </span>
 <span
 v-if="isDirty"
 class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 font-medium"
 title="存在未保存修改"
 >
 未保存
 </span>
 </SheetTitle>
 <SheetDescription v-if="currentPrompt" class="text-xs">
 <code class="font-mono text-foreground/70 bg-muted px-1.5 py-0.5 rounded text-[11px]">
 {{ currentPrompt.slug }}
 </code>
 </SheetDescription>
 <SheetDescription v-else-if="mode === 'create'" class="text-xs text-muted-foreground">
 填写下方字段创建一个新的系统级 Prompt
 </SheetDescription>
 </div>
 </div>
 </SheetHeader>
 <Tabs
 v-model="activeTab"
 class="flex-1 flex flex-col overflow-hidden"
 >
 <div class="px-6 pt-3 pb-0 bg-card/60 border-b border-border/40">
 <TabsList class=" bg-muted/60">
 <TabsTrigger value="metadata" class="text-xs gap-1.5">
 <span class="icon-[lucide--info] text-sm" />
 基础信息
 </TabsTrigger>
 <TabsTrigger value="body" class="text-xs gap-1.5">
 <span class="icon-[lucide--file-code] text-sm" />
 正文编辑
 </TabsTrigger>
 <TabsTrigger value="preview" class="text-xs gap-1.5">
 <span class="icon-[lucide--eye] text-sm" />
 预览
 </TabsTrigger>
 <TabsTrigger v-if="mode === 'edit'" value="versions" class="text-xs gap-1.5">
 <span class="icon-[lucide--history] text-sm" />
 版本历史
 </TabsTrigger>
 </TabsList>
 </div>
 <!-- Tab 1：基础信息 -->
 <TabsContent
 value="metadata":force-mount="true"
 class="flex-1 overflow-auto px-6 py-5 space-y-5 data-[state=inactive]:hidden"
 >
 <PromptMetadataForm:prompt="currentPrompt":mode="mode"
 @update:values="onMetadataChange"
 />
 <VariableSchemaEditor:model-value="editedVariablesSchema"
 @update:model-value="onSchemaChange"
 @parse-error="onSchemaParseError"
 />
 </TabsContent>
 <!-- Tab 2：正文编辑 -->
 <TabsContent
 value="body":force-mount="true"
 class="flex-1 overflow-auto px-6 py-5 data-[state=inactive]:hidden"
 >
 <div class="space-y-3">
 <div class="flex items-center justify-between gap-2">
 <div>
 <h4 class="text-sm font-semibold text-foreground flex items-center gap-2">
 <span class="icon-[lucide--file-code] text-primary text-base" />
 Prompt 正文
 </h4>
 <p class="text-xs text-muted-foreground mt-0.5">
 支持 Jinja2 模板语法，使用 <code class="font-mono text-foreground bg-muted px-1 py-0.5 rounded text-[10px]">&#123;&#123;变量名&#125;&#125;</code> 插入占位符
 </p>
 </div>
 </div>
 <div class="grid grid-cols-[1fr_18rem] gap-4">
 <PromptBodyEditor:model-value="editedBody"
 @update:model-value="onBodyChange"
 />
 <PromptVariablePanel:body="editedBody":variables-schema="editedVariablesSchema"
 />
 </div>
 </div>
 </TabsContent>
 <!-- Tab 3：预览 -->
 <TabsContent
 value="preview":force-mount="true"
 class="flex-1 overflow-auto px-6 py-5 data-[state=inactive]:hidden"
 >
 <PromptPreviewPanel
 v-if="currentPrompt":prompt="currentPrompt":body="editedBody"
 />
 <div
 v-else
 class="rounded-xl border border-dashed border-border/60 bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground"
 >
 创建模式下不支持预览，请先保存后再切换至此处
 </div>
 </TabsContent>
 <!-- Tab 4：版本历史（仅 edit 模式渲染） -->
 <TabsContent
 v-if="mode === 'edit'"
 value="versions":force-mount="true"
 class="flex-1 overflow-auto px-6 py-5 data-[state=inactive]:hidden"
 >
 <PromptVersionList
 v-if="currentPrompt":prompt="currentPrompt":versions="versionsList"
 />
 </TabsContent>
 </Tabs>
 <SheetFooter class="mt-auto border-t border-border/60 bg-card px-6 py-3 flex-row items-center justify-between gap-2 sm:flex-row sm:justify-between sm:space-x-0">
 <span class="text-[11px] text-muted-foreground">
 <template v-if="isDirty">
 <span class="inline-block w-1.5 .5 rounded-full bg-amber-500 mr-1.5 align-middle" />
 存在未保存修改
 </template>
 <template v-else-if="mode === 'edit' && currentPrompt">
 <span class="inline-block w-1.5 .5 rounded-full bg-emerald-500 mr-1.5 align-middle" />
 已与服务器同步
 </template>
 </span>
 <div class="flex items-center gap-2">
 <Button variant="outline" @click="handleOpenChange(false)">
 取消
 </Button>
 <Button:disabled="!isDirty || isSaving":title="!isDirty ? '无变更': ''"
 @click="handleSave"
 >
 {{ isSaving ? '保存中…': '保存' }}
 </Button>
 </div>
 </SheetFooter>
 </SheetContent>
 </Sheet>
</template>
