<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'

import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

interface Condition {
  field: string
  operator: string
  value: string
}

interface ConditionGroup {
  logic: 'and' | 'or'
  conditions: Condition[]
}

const props = defineProps<{
  modelValue: ConditionGroup
  availableFields?: Array<{ key: string, name: string, type?: string }>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: ConditionGroup): void
}>()

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

const conditions = computed(() => props.modelValue?.conditions || [])
const logic = computed(() => props.modelValue?.logic || 'and')

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

function addCondition() {
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
      <Select :model-value="logic" @update:model-value="updateLogic($event as 'and' | 'or')">
        <SelectTrigger size="sm" class="bg-background/50">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="and">
            所有
          </SelectItem>
          <SelectItem value="or">
            任一
          </SelectItem>
        </SelectContent>
      </Select>
      <Label class="text-sm text-muted-foreground">条件时继续</Label>
    </div>

    <!-- Condition rows -->
    <div class="space-y-3">
      <div
        v-for="(condition, index) in conditions"
        :key="index"
        class="flex items-start gap-2 p-3 rounded-xl bg-muted/30 border border-border/30"
      >
        <div class="flex-1 space-y-2">
          <div class="grid grid-cols-2 gap-2">
            <!-- Field selector -->
            <div>
              <Label class="text-xs text-muted-foreground mb-1 block">字段</Label>
              <Input
                v-if="!availableFields?.length"
                :model-value="condition.field"
                placeholder="字段名（如 status）"
                class="h-8 text-sm bg-background/50"
                @update:model-value="updateCondition(index, { field: $event as string })"
              />
              <Select
                v-else
                :model-value="condition.field"
                @update:model-value="updateCondition(index, { field: $event as string })"
              >
                <SelectTrigger size="sm" class="w-full bg-background/50">
                  <SelectValue placeholder="选择字段" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="field in availableFields" :key="field.key" :value="field.key">
                    {{ field.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <!-- Operator selector -->
            <div>
              <Label class="text-xs text-muted-foreground mb-1 block">条件</Label>
              <Select
                :model-value="condition.operator"
                @update:model-value="updateCondition(index, { operator: $event as string })"
              >
                <SelectTrigger size="sm" class="w-full bg-background/50">
                  <SelectValue placeholder="选择条件" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="op in operators" :key="op.value" :value="op.value">
                    {{ op.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <!-- Value input (hidden for is_empty/is_not_empty) -->
          <div v-if="!valueHiddenOperators.includes(condition.operator)">
            <Label class="text-xs text-muted-foreground mb-1 block">期望值</Label>
            <Input
              :model-value="condition.value"
              placeholder="期望值（支持变量如 {{node1.status}}）"
              class="h-8 text-sm bg-background/50"
              @update:model-value="updateCondition(index, { value: $event as string })"
            />
          </div>
        </div>

        <!-- Delete button -->
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 text-muted-foreground hover:text-destructive flex-shrink-0 mt-5"
          @click="removeCondition(index)"
        >
          <Trash2 class="w-4 h-4" />
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
      <Plus class="w-4 h-4 mr-1" />
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
