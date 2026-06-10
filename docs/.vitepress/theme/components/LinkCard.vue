<script setup lang="ts">
import { withBase } from 'vitepress'
import { computed } from 'vue'

const props = defineProps<{
  title: string
  desc?: string
  link: string
  /** emoji 图标 */
  icon?: string
}>()

const isExternal = computed(() => /^https?:\/\//.test(props.link))
const href = computed(() => (isExternal.value ? props.link : withBase(props.link)))
</script>

<template>
  <a
    class="link-card"
    :href="href"
    :target="isExternal ? '_blank' : undefined"
    :rel="isExternal ? 'noreferrer' : undefined"
  >
    <span v-if="icon" class="link-card-icon">{{ icon }}</span>
    <span class="link-card-body">
      <span class="link-card-title">
        {{ title }}
        <svg class="link-card-chevron" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path
            d="M9 6l6 6-6 6"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span v-if="desc" class="link-card-desc">{{ desc }}</span>
    </span>
  </a>
</template>

<style scoped>
.link-card {
  display: flex;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background: var(--vp-c-bg-soft);
  text-decoration: none !important;
  transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
}

.link-card:hover {
  border-color: var(--vp-c-brand-2);
  background: var(--vp-c-bg);
  box-shadow: 0 6px 20px rgba(20, 184, 166, 0.12);
}

.link-card-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--vp-c-brand-soft);
  font-size: 20px;
}

.link-card-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.link-card-title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 15px;
  font-weight: 600;
  color: var(--vp-c-text-1);
  line-height: 1.5;
}

.link-card-chevron {
  color: var(--vp-c-brand-1);
  transition: transform 0.25s;
}

.link-card:hover .link-card-chevron {
  transform: translateX(3px);
}

.link-card-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--vp-c-text-2);
}
</style>
