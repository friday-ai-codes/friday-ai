<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Command,
 CommandEmpty,
 CommandGroup,
 CommandInput,
 CommandItem,
 CommandList,
} from '~/components/ui/command'
import { Input } from '~/components/ui/input'
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from '~/components/ui/popover'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
// ============================================================================
// Types
// ============================================================================
interface Repository {
 id: string
 name: string
}
interface Props {
 modelValue: string // Array of repository IDs
 repositories: Repository // Available repositories
 placeholder?: string
 allowManualInput?: boolean
}
// ============================================================================
// Props & Emits
// ============================================================================
const props = withDefaults(defineProps<Props>, {
 placeholder: '选择仓库...',
 allowManualInput: true,
})
const emit = defineEmits<{
 (e: 'update:modelValue', value: string): void
}>
// ============================================================================
// State
// ============================================================================
const open = ref(false)
const inputMode = ref<'select' | 'manual'>('select')
const manualValue = ref('')
// Auto-switch to manual mode when no repositories available
watch(
 => props.repositories,
 (repos) => {
 if (repos.length === 0 && props.allowManualInput) {
 inputMode.value = 'manual'
 }
 },
 { immediate: true },
)
// ============================================================================
// Computed
// ============================================================================
// Get display info for selected repositories
const selectedItems = computed( => {
 return props.modelValue.map((id) => {
 const repo = props.repositories.find(r => r.id === id)
 return {
 id,
 // Show name if found in repositories, otherwise show the ID/variable directly
 displayName: repo?.name ?? id,
 isFromList: !!repo,
 }
 })
})
// Check if a repository ID is selected
function isSelected(id: string): boolean {
 return props.modelValue.includes(id)
}
// ============================================================================
// Actions
// ============================================================================
function toggleRepository(id: string) {
 const newValue = props.modelValue.includes(id)
 ? props.modelValue.filter(v => v !== id): [...props.modelValue, id]
 emit('update:modelValue', newValue)
}
function removeRepository(id: string) {
 emit('update:modelValue', props.modelValue.filter(v => v !== id))
}
function addManualValue {
 const trimmed = manualValue.value.trim
 if (trimmed && !props.modelValue.includes(trimmed)) {
 emit('update:modelValue', [...props.modelValue, trimmed])
 manualValue.value = ''
 }
}
function insertVariable(variable: string) {
 manualValue.value = variable
}
function handleManualKeydown(event: KeyboardEvent) {
 if (event.key === 'Enter') {
 event.preventDefault
 addManualValue
 }
}
</script>
<template>
 <div class="space-y-3">
 <!-- Selected tags display -->
 <div v-if="selectedItems.length" class="flex flex-wrap gap-1.5">
 <Badge
 v-for="item in selectedItems":key="item.id"
 variant="secondary"
 class="gap-1.5 bg-gradient-to-br from-primary/20 to-primary/10 pr-1"
 >
 <span class="icon-[lucide--git-branch] w-3 " />
 <span class="max-w-[150px] truncate">{{ item.displayName }}</span>
 <button
 type="button"
 class="ml-0.5 rounded-full .5 hover:bg-destructive/20 hover:text-destructive transition-colors"
 @click.stop="removeRepository(item.id)"
 >
 <span class="icon-[lucide--x] w-3 " />
 </button>
 </Badge>
 </div>
 <!-- Mode toggle (only if allowManualInput is true) -->
 <div v-if="allowManualInput" class="flex gap-2">
 <Button:variant="inputMode === 'select' ? 'default': 'outline'"
 size="sm"
 class=" text-xs"
 @click="inputMode = 'select'"
 >
 <span class="icon-[lucide--list] w-3.5 .5 mr-1" />
 从列表选择
 </Button>
 <Button:variant="inputMode === 'manual' ? 'default': 'outline'"
 size="sm"
 class=" text-xs"
 @click="inputMode = 'manual'"
 >
 <span class="icon-[lucide--edit-3] w-3.5 .5 mr-1" />
 手动输入
 </Button>
 </div>
 <!-- Selection mode: Dropdown selector -->
 <div v-if="inputMode === 'select'">
 <!-- Empty state when no repositories -->
 <div
 v-if="repositories.length === 0"
 class="rounded-lg border border-dashed border-border/50 bg-muted/30 text-center"
 >
 <span class="icon-[lucide--inbox] w-8 text-muted-foreground/50 mx-auto mb-2" />
 <p class="text-sm text-muted-foreground">
 暂无可用仓库
 </p>
 <p v-if="allowManualInput" class="text-xs text-muted-foreground/70 mt-1">
 请切换到手动输入模式
 </p>
 </div>
 <!-- Popover dropdown selector -->
 <Popover v-else v-model:open="open">
 <PopoverTrigger as-child>
 <Button
 variant="outline"
 class="w-full justify-between rounded-xl bg-card/50 backdrop-blur-sm border-border/50 hover:border-primary/30 transition-colors"
 >
 <span class="text-muted-foreground">{{ placeholder }}</span>
 <span class="icon-[lucide--chevrons-up-down] w-4 opacity-50" />
 </Button>
 </PopoverTrigger>
 <PopoverContent class="w-[var(--reka-popover-trigger-width)] " align="start">
 <Command>
 <CommandInput placeholder="搜索仓库..." />
 <CommandList>
 <CommandEmpty>未找到仓库</CommandEmpty>
 <CommandGroup>
 <CommandItem
 v-for="repo in repositories":key="repo.id":value="repo.name"
 class="cursor-pointer"
 @select.prevent="toggleRepository(repo.id)"
 >
 <span
 class="icon-[lucide--check] w-4 mr-2 transition-opacity":class="isSelected(repo.id) ? 'opacity-100': 'opacity-0'"
 />
 <span class="icon-[lucide--git-branch] w-4 mr-2 text-muted-foreground" />
 <span class="truncate">{{ repo.name }}</span>
 </CommandItem>
 </CommandGroup>
 </CommandList>
 </Command>
 </PopoverContent>
 </Popover>
 </div>
 <!-- Manual mode: Input + VariablePicker -->
 <div v-else class="space-y-2">
 <div class="flex gap-2">
 <Input
 v-model="manualValue"
 placeholder="仓库 ID 或 {{nodes.xxx.repository_id}}"
 class="flex-1 font-mono text-sm rounded-xl bg-card/50 backdrop-blur-sm border-border/50"
 @keydown="handleManualKeydown"
 />
 <VariablePicker @select="insertVariable" />
 <Button
 variant="outline"
 size="icon"
 class="shrink-0 rounded-xl":disabled="!manualValue.trim"
 @click="addManualValue"
 >
 <span class="icon-[lucide--plus] w-4 " />
 </Button>
 </div>
 <p class="text-xs text-muted-foreground">
 输入仓库 UUID 或使用模板变量，按 Enter 或点击 + 添加
 </p>
 </div>
 </div>
</template>
