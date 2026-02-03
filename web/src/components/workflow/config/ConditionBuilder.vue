<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
interface Condition {
 field: string
 operator: string
 value: string
}
interface ConditionGroup {
 logic: 'and' | 'or'
 conditions: Condition
}
const props = defineProps<{
 modelValue: ConditionGroup
 availableFields?: Array<{ key: string; name: string; type?: string }>
}>
const emit = defineEmits<{
 (e: 'update:modelValue', value: ConditionGroup): void
}>
const operators = [
 { value: 'eq', label: '等于' },
 { value: 'ne', label: '不等于' },
 { value: 'contains', label: '包含' },
 { value: 'not_contains', label: '不包含' },
 { value: 'is_empty', label: '为空' },
 { value: 'is_not_empty', label: '不为空' },
 { value: 'gt', label: '大于' },
 { value: 'gte', label: '大于等于' },
 { value: 'lt', label: '小于' },
 { value: 'lte', label: '小于等于' },
 { value: 'regex', label: '正则匹配' },
]
const valueHiddenOperators = ['is_empty', 'is_not_empty']
const conditions = computed( => props.modelValue?.conditions || )
const logic = computed( => props.modelValue?.logic || 'and')
function updateLogic(newLogic: 'and' | 'or') {
 emit('update:modelValue', {
 ...props.modelValue,
 logic: newLogic,
 })
}
function updateCondition(index: number, updates: Partial<Condition>) {
 const newConditions = [...conditions.value]
 newConditions[index] = { ...newConditions[index], ...updates }
 emit('update:modelValue', {
 ...props.modelValue,
 conditions: newConditions,
 })
}
function addCondition {
 emit('update:modelValue', {
 ...props.modelValue,
 conditions: [
 ...conditions.value,
 { field: '', operator: 'eq', value: '' },
 ],
 })
}
function removeCondition(index: number) {
 const newConditions = conditions.value.filter((_, i) => i !== index)
 emit('update:modelValue', {
 ...props.modelValue,
 conditions: newConditions,
 })
}
</script>
<template>
 <div class="space-y-4">
 <!-- Logic toggle -->
 <div class="flex items-center gap-2">
 <Label class="text-sm text-muted-foreground">满足</Label>
 <select:value="logic"
 class=" rounded-lg border border-border/50 bg-background/50 px-3 text-sm focus:border-primary/50 focus:outline-none transition-colors"
 @change="updateLogic(($event.target as HTMLSelectElement).value as 'and' | 'or')"
 >
 <option value="and">所有</option>
 <option value="or">任一</option>
 </select>
 <Label class="text-sm text-muted-foreground">条件时继续</Label>
 </div>
 <!-- Condition rows -->
 <div class="space-y-3">
 <div
 v-for="(condition, index) in conditions":key="index"
 class="flex items-start gap-2 rounded-xl bg-muted/30 border border-border/30"
 >
 <div class="flex-1 space-y-2">
 <div class="grid grid-cols-2 gap-2">
 <!-- Field selector -->
 <div>
 <Label class="text-xs text-muted-foreground mb-1 block">字段</Label>
 <Input
 v-if="!availableFields?.length":model-value="condition.field"
 placeholder="字段名（如 status）"
 class=" text-sm bg-background/50"
 @update:model-value="updateCondition(index, { field: $event as string })"
 />
 <select
 v-else:value="condition.field"
 class="w-full rounded-lg border border-border/50 bg-background/50 px-2 text-sm"
 @change="updateCondition(index, { field: ($event.target as HTMLSelectElement).value })"
 >
 <option value="">选择字段</option>
 <option v-for="field in availableFields":key="field.key":value="field.key">
 {{ field.name }}
 </option>
 </select>
 </div>
 <!-- Operator selector -->
 <div>
 <Label class="text-xs text-muted-foreground mb-1 block">条件</Label>
 <select:value="condition.operator"
 class="w-full rounded-lg border border-border/50 bg-background/50 px-2 text-sm"
 @change="updateCondition(index, { operator: ($event.target as HTMLSelectElement).value })"
 >
 <option v-for="op in operators":key="op.value":value="op.value">
 {{ op.label }}
 </option>
 </select>
 </div>
 </div>
 <!-- Value input (hidden for is_empty/is_not_empty) -->
 <div v-if="!valueHiddenOperators.includes(condition.operator)">
 <Label class="text-xs text-muted-foreground mb-1 block">期望值</Label>
 <Input:model-value="condition.value"
 placeholder="期望值（支持变量如 {{node1.status}}）"
 class=" text-sm bg-background/50"
 @update:model-value="updateCondition(index, { value: $event as string })"
 />
 </div>
 </div>
 <!-- Delete button -->
 <Button
 variant="ghost"
 size="icon"
 class=" w-8 text-muted-foreground hover:text-destructive flex-shrink-0 mt-5"
 @click="removeCondition(index)"
 >
 <Trash2 class="w-4 " />
 </Button>
 </div>
 </div>
 <!-- Add condition button -->
 <Button
 variant="outline"
 size="sm"
 class="w-full"
 @click="addCondition"
 >
 <Plus class="w-4 mr-1" />
 添加条件
 </Button>
 <!-- Empty state -->
 <div
 v-if="conditions.length === 0"
 class="text-center py-6 text-sm text-muted-foreground"
 >
 点击上方按钮添加等待条件
 </div>
 </div>
</template>
