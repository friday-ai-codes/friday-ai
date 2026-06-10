<template>
  <div class="vp-steps">
    <slot />
  </div>
</template>

<style>
/* 非 scoped：需要作用到 slot 中由 markdown 渲染出的列表 */
.vp-steps > ol {
  list-style: none;
  counter-reset: vp-step;
  margin: 16px 0;
  padding-left: 0;
}

.vp-steps > ol > li {
  position: relative;
  counter-increment: vp-step;
  margin: 0;
  padding: 0 0 24px 48px;
}

.vp-steps > ol > li:last-child {
  padding-bottom: 4px;
}

/* 序号圆点 */
.vp-steps > ol > li::before {
  content: counter(vp-step);
  position: absolute;
  left: 0;
  top: -2px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--vp-c-brand-soft);
  border: 1px solid var(--vp-c-brand-2);
  color: var(--vp-c-brand-1);
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
}

/* 步骤之间的连接线 */
.vp-steps > ol > li:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 14.5px;
  top: 32px;
  bottom: 4px;
  width: 1px;
  background: var(--vp-c-divider);
}

.vp-steps > ol > li > p:first-child {
  margin-top: 0;
  font-weight: 600;
  color: var(--vp-c-text-1);
}
</style>
