<script setup lang="ts">
export interface FlowDiagramNode {
  /** 节点标题 */
  title: string
  /** 副标题/描述，支持多行（数组） */
  desc?: string | string[]
  /** 右上角小徽标，如技术栈 */
  badge?: string
  /** 高亮节点（品牌色边框） */
  accent?: boolean
}

export interface FlowDiagramLayer {
  /** 同一层并排的节点 */
  nodes: FlowDiagramNode[]
  /** 指向下一层的箭头标注 */
  arrow?: string
  /** 双向箭头（默认单向向下） */
  bidirectional?: boolean
}

defineProps<{ layers: FlowDiagramLayer[] }>()

function descLines(desc?: string | string[]): string[] {
  if (!desc) return []
  return Array.isArray(desc) ? desc : [desc]
}
</script>

<template>
  <div class="flow-diagram">
    <template v-for="(layer, li) in layers" :key="li">
      <div class="fd-layer">
        <div
          v-for="(node, ni) in layer.nodes"
          :key="ni"
          class="fd-node"
          :class="{ 'fd-node-accent': node.accent }"
        >
          <div class="fd-node-head">
            <span class="fd-node-title">{{ node.title }}</span>
            <span v-if="node.badge" class="fd-node-badge">{{ node.badge }}</span>
          </div>
          <div v-if="descLines(node.desc).length" class="fd-node-desc">
            <span v-for="(line, di) in descLines(node.desc)" :key="di">{{ line }}</span>
          </div>
        </div>
      </div>

      <div v-if="li < layers.length - 1" class="fd-connector">
        <svg
          class="fd-arrow"
          :class="{ 'fd-arrow-bi': layer.bidirectional }"
          viewBox="0 0 24 36"
          width="18"
          height="28"
          aria-hidden="true"
        >
          <path
            v-if="layer.bidirectional"
            d="M12 3v30M12 3l-5 6m5-6l5 6M12 33l-5-6m5 6l5-6"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            v-else
            d="M12 2v28m0 0l-6-7m6 7l6-7"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span v-if="layer.arrow" class="fd-arrow-label">{{ layer.arrow }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.flow-diagram {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 24px 0;
  padding: 28px 20px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 14px;
  background:
    radial-gradient(110% 140% at 50% 0%, var(--vp-c-brand-soft) 0%, transparent 60%),
    var(--vp-c-bg-soft);
}

.fd-layer {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14px;
  width: 100%;
}

.fd-node {
  min-width: 200px;
  max-width: 340px;
  flex: 0 1 auto;
  padding: 12px 18px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 10px;
  background: var(--vp-c-bg);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  text-align: center;
  transition: border-color 0.25s, box-shadow 0.25s;
}

.fd-node:hover {
  border-color: var(--vp-c-brand-2);
  box-shadow: 0 4px 14px rgba(20, 184, 166, 0.14);
}

.fd-node-accent {
  border-color: var(--vp-c-brand-2);
  background: linear-gradient(180deg, var(--vp-c-brand-soft) 0%, var(--vp-c-bg) 70%);
}

.fd-node-head {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.fd-node-title {
  font-size: 14.5px;
  font-weight: 650;
  color: var(--vp-c-text-1);
  line-height: 1.5;
}

.fd-node-badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.7;
  white-space: nowrap;
}

.fd-node-desc {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-top: 4px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--vp-c-text-2);
}

.fd-connector {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.fd-arrow {
  color: var(--vp-c-brand-2);
}

.fd-arrow-label {
  padding: 2px 10px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 999px;
  background: var(--vp-c-bg);
  font-size: 12px;
  font-weight: 500;
  color: var(--vp-c-text-2);
  white-space: nowrap;
}

@media (max-width: 640px) {
  .fd-node {
    min-width: 0;
    width: 100%;
  }

  .fd-arrow-label {
    white-space: normal;
    text-align: center;
  }
}
</style>
