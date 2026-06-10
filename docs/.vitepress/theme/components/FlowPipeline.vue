<script setup lang="ts">
defineProps<{
  /** 流水线步骤文案，按顺序渲染 */
  steps: string[]
}>()
</script>

<template>
  <div class="flow-pipeline">
    <template v-for="(step, i) in steps" :key="i">
      <span class="flow-step">
        <span class="flow-index">{{ i + 1 }}</span>
        {{ step }}
      </span>
      <svg
        v-if="i < steps.length - 1"
        class="flow-arrow"
        viewBox="0 0 24 24"
        width="16"
        height="16"
        aria-hidden="true"
      >
        <path
          d="M5 12h14m0 0l-6-6m6 6l-6 6"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </template>
  </div>
</template>

<style scoped>
.flow-pipeline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 20px 0;
  padding: 18px 16px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background:
    radial-gradient(120% 160% at 0% 0%, var(--vp-c-brand-soft) 0%, transparent 55%),
    var(--vp-c-bg-soft);
}

.flow-step {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px 6px 7px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 999px;
  background: var(--vp-c-bg);
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1.4;
  color: var(--vp-c-text-1);
  white-space: nowrap;
}

.flow-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  font-size: 11px;
  font-weight: 700;
}

.flow-arrow {
  flex-shrink: 0;
  color: var(--vp-c-brand-2);
}
</style>
