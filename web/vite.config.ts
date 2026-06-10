import { resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import TailwindCSS from '@tailwindcss/vite'
import Vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import VueI18n from 'unplugin-vue-i18n/vite'
import { VueRouterAutoImports } from 'unplugin-vue-router'
import VueRouter from 'unplugin-vue-router/vite'
import { defineConfig } from 'vite'
import Layouts from 'vite-plugin-vue-layouts'
import VueMacros from 'vue-macros/vite'
import pkg from './package.json'

const usePolling = process.env.VITE_USE_POLLING === 'true'

// https://vite.dev/config/
export default defineConfig({
  define: {
    // 优先取 CI 传入的发布版本（git tag，去掉 v 前缀）；本地开发回退到 package.json
    __APP_VERSION__: JSON.stringify((process.env.APP_VERSION || pkg.version).replace(/^v/, '')),
  },
  plugins: [
    VueMacros({
      betterDefine: false,
      plugins: {
        vue: Vue(),
        vueRouter: VueRouter({
          routesFolder: 'src/pages',
          dts: 'src/typed-router.d.ts',
        }),
      },
    }),
    // 路由必须在 Vue 插件之前

    // Tailwind CSS v4
    TailwindCSS(),

    // 布局系统
    Layouts({
      layoutsDirs: 'src/layouts',
      defaultLayout: 'default',
    }),

    // 自动导入 API
    AutoImport({
      imports: [
        'vue',
        'pinia',
        VueRouterAutoImports,
        '@vueuse/core',
        {
          'vue-i18n': ['useI18n'],
        },
      ],
      dts: 'src/auto-imports.d.ts',
      dirs: ['src/composables', 'src/stores'],
      vueTemplate: true,
    }),

    // 自动导入组件
    Components({
      dirs: ['src/components'],
      dts: 'src/components.d.ts',
      include: [/\.vue$/, /\.vue\?vue/],
    }),

    // 国际化
    VueI18n({
      include: [resolve(__dirname, 'src/locales/**')],
    }),
  ],

  resolve: {
    alias: {
      '~': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    host: '0.0.0.0',
    port: 10240,
    strictPort: true,
    open: true,
    watch: usePolling
      ? {
          usePolling: true,
          interval: 120,
        }
      : undefined,
    proxy: {
      '/api': {
        target: 'http://localhost:10241',
        changeOrigin: false,
        // SSE 长连接需要禁用任何缓冲 / 超时，否则 vite dev proxy 会 hold 住
        // text/event-stream 响应直到完整结束 — 进度帧永远到不了浏览器。
        // 设 timeout/proxyTimeout = 0 表示不限制。
        timeout: 0,
        proxyTimeout: 0,
        // ws: false 默认；selfHandleResponse: false 是默认值 = 走 streaming pass-through
      },
      '/ws': {
        target: 'http://localhost:10241',
        ws: true,
      },
    },
  },
})
