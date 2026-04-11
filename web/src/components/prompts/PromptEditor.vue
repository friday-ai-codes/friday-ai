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
 * - 项目级页面 `pages/projects/[id]/prompts.vue`
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
 /** 项目级页面传入；系统级页面不传。当前组件仅透传给 store，不主动切换 project */
 projectId?: string
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
// store 的 currentPrompt / versions / saving 在 Pinia setup-syntax 内部是 ref<T>。
// 这里通过 RefLike 断言统一运行时（Pinia 代理）与测试时（直接注入 ref）两种形态，
// 然后用 computed 产出 plain 局部变量供模板与脚本使用 —— Vue 模板自动解包机制
// 会把变量名结尾看似 Ref 的变量 unwrap，但 computed 的语义清晰、可读性更好。
interface RefLike<T> { value: T }
const storeCurrentPrompt = store.currentPrompt as unknown as RefLike<PromptDetail | null>
const storeVersions = store.versions as unknown as RefLike<PromptVersion>
const storeSaving = store.saving as unknown as RefLike<boolean>
const currentPrompt = computed<PromptDetail | null>( => storeCurrentPrompt.value)
const versionsList = computed<PromptVersion>( => storeVersions.value)
const isSaving = computed<boolean>( => storeSaving.value)
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
 if (editedTitle.value !== p.title)
 return true
 if (editedDescription.value !== p.description)
 return true
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
 await store.updatePrompt(p.id, {
 title: editedTitle.value,
 description: editedDescription.value,
 body: editedBody.value,
 variables_schema: editedVariablesSchema.value,
 change_note: '',
 })
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
 class="sm:!max-w-3xl w-full flex flex-col"
 >
 <SheetHeader>
 <SheetTitle>
 {{ mode === 'create' ? '新建 Prompt': (currentPrompt?.title ?? '加载中…') }}
 </SheetTitle>
 <SheetDescription v-if="currentPrompt">
 {{ currentPrompt.slug }}
 </SheetDescription>
 </SheetHeader>
 <Tabs
 v-model="activeTab"
 class="flex-1 flex flex-col overflow-hidden"
 >
 <TabsList>
 <TabsTrigger value="metadata">
 基础信息
 </TabsTrigger>
 <TabsTrigger value="body">
 正文编辑
 </TabsTrigger>
 <TabsTrigger value="preview">
 预览
 </TabsTrigger>
 <TabsTrigger v-if="mode === 'edit'" value="versions">
 版本历史
 </TabsTrigger>
 </TabsList>
 <!-- Tab 1：基础信息 -->
 <TabsContent
 value="metadata":force-mount="true"
 class="flex-1 overflow-auto py-4 space-y-4 data-[state=inactive]:hidden"
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
 class="flex-1 overflow-auto py-4 data-[state=inactive]:hidden"
 >
 <div class="grid grid-cols-[1fr_18rem] gap-4">
 <PromptBodyEditor:model-value="editedBody"
 @update:model-value="onBodyChange"
 />
 <PromptVariablePanel:body="editedBody":variables-schema="editedVariablesSchema"
 />
 </div>
 </TabsContent>
 <!-- Tab 3：预览 -->
 <TabsContent
 value="preview":force-mount="true"
 class="flex-1 overflow-auto py-4 data-[state=inactive]:hidden"
 >
 <PromptPreviewPanel
 v-if="currentPrompt":prompt="currentPrompt":body="editedBody"
 />
 </TabsContent>
 <!-- Tab 4：版本历史（仅 edit 模式渲染） -->
 <TabsContent
 v-if="mode === 'edit'"
 value="versions":force-mount="true"
 class="flex-1 overflow-auto py-4 data-[state=inactive]:hidden"
 >
 <PromptVersionList
 v-if="currentPrompt":prompt="currentPrompt":versions="versionsList"
 />
 </TabsContent>
 </Tabs>
 <SheetFooter class="mt-auto border-t border-border/50 pt-4">
 <Button variant="outline" @click="handleOpenChange(false)">
 取消
 </Button>
 <Button:disabled="!isDirty || isSaving":title="!isDirty ? '无变更': ''"
 @click="handleSave"
 >
 {{ isSaving ? '保存中…': '保存' }}
 </Button>
 </SheetFooter>
 </SheetContent>
 </Sheet>
</template>
