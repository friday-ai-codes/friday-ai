<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useI18n } from 'vue-i18n'

const asOfLocal = defineModel<string>('asOfLocal', { default: '' })
const includeSuperseded = defineModel<boolean>('includeSuperseded', { default: false })

const emit = defineEmits<{
  reset: []
}>()

const { t } = useI18n()

function onAsOfChange(value: string) {
  asOfLocal.value = value
}

function reset() {
  asOfLocal.value = ''
  emit('reset')
}
</script>

<template>
  <div class="card px-5 py-3 flex flex-wrap items-end gap-4">
    <div class="space-y-1">
      <Label for="as-of-input">{{ t('knowledge.entity.asOf.label') }}</Label>
      <Input
        id="as-of-input"
        type="datetime-local"
        :model-value="asOfLocal"
        :placeholder="t('knowledge.entity.asOf.placeholder')"
        @update:model-value="onAsOfChange"
      />
    </div>
    <div class="flex items-center gap-2 pb-1">
      <Checkbox id="include-superseded" v-model:checked="includeSuperseded" />
      <Label for="include-superseded">{{ t('knowledge.entity.includeSuperseded') }}</Label>
    </div>
    <Button variant="ghost" size="sm" @click="reset">
      {{ t('knowledge.entity.asOf.reset') }}
    </Button>
  </div>
</template>
