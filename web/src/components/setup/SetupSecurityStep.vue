<script setup lang="ts">
import type { SecurityCheck } from '~/api/setup'
import { onMounted, ref } from 'vue'
import { getSecurityCheck } from '~/api/setup'
import { Button } from '~/components/ui/button'

const emit = defineEmits<{ continue: [] }>()
const { t } = useI18n()

const loading = ref(true)
const failed = ref(false)
const check = ref<SecurityCheck | null>(null)

// 后端风险 code → i18n key 映射（驼峰）
const RISK_I18N: Record<string, string> = {
  secret_key_default: 'setup.security.risk.secretKeyDefault',
  encryption_key_unset: 'setup.security.risk.encryptionKeyUnset',
  keys_not_independent: 'setup.security.risk.keysNotIndependent',
}

onMounted(async () => {
  try {
    check.value = await getSecurityCheck()
  }
  catch {
    // 非阻塞：读取失败仅作中性提示，仍允许继续
    failed.value = true
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="mb-6 text-center">
      <div class="inline-flex items-center justify-center p-3 mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
        <span class="icon-[lucide--shield-check] text-3xl text-primary" />
      </div>
      <h1 class="text-2xl font-bold text-foreground mb-1">
        {{ t('setup.security.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">
        {{ t('setup.security.subtitle') }}
      </p>
    </div>

    <div class="space-y-4">
      <!-- 校验中 -->
      <div
        v-if="loading"
        class="flex items-center gap-2.5 p-3 rounded-xl bg-muted/40 border border-border/50 text-muted-foreground"
      >
        <span class="icon-[lucide--loader-circle] text-base animate-spin flex-shrink-0" />
        <span class="text-sm">{{ t('setup.security.checking') }}</span>
      </div>

      <!-- 读取失败：中性提示，不阻塞 -->
      <div
        v-else-if="failed"
        class="flex items-start gap-2.5 p-3 rounded-xl bg-muted/40 border border-border/50 text-muted-foreground"
      >
        <span class="icon-[lucide--info] text-base flex-shrink-0 mt-0.5" />
        <span class="text-sm">{{ t('setup.security.unavailable') }}</span>
      </div>

      <!-- 全通过 -->
      <div
        v-else-if="check && check.secure"
        class="flex items-start gap-2.5 p-3 rounded-xl bg-primary/8 border border-primary/15 text-primary"
      >
        <span class="icon-[lucide--shield-check] text-base flex-shrink-0 mt-0.5" />
        <span class="text-sm">{{ t('setup.security.allClear') }}</span>
      </div>

      <!-- 有风险：amber 提示，逐条列出，仍允许继续 -->
      <div
        v-else-if="check"
        class="p-3 rounded-xl bg-amber-500/8 border border-amber-500/20 text-amber-600 space-y-2"
      >
        <div class="flex items-center gap-2 font-medium text-sm">
          <span class="icon-[lucide--alert-triangle] text-base flex-shrink-0" />
          {{ t('setup.security.riskTitle') }}
        </div>
        <ul class="space-y-1.5 pl-1">
          <li
            v-for="risk in check.risks"
            :key="risk.code"
            class="flex items-start gap-2 text-xs"
          >
            <span class="icon-[lucide--dot] text-base flex-shrink-0 -mt-0.5" />
            <span>{{ RISK_I18N[risk.code] ? t(RISK_I18N[risk.code]) : risk.code }}</span>
          </li>
        </ul>
      </div>

      <!-- 继续：任何校验结果下均可点击（非阻塞） -->
      <Button
        type="button"
        class="w-full h-10 text-sm font-semibold"
        @click="emit('continue')"
      >
        <span class="icon-[lucide--arrow-right] mr-2" />
        {{ t('setup.security.cta') }}
      </Button>
    </div>
  </div>
</template>
