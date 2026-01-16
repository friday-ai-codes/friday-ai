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
// https://vite.dev/config/
export default defineConfig({
 plugins: [
 // 路由必须在 Vue 插件之前
 VueRouter({
 routesFolder: 'src/pages',
 dts: 'src/typed-router.d.ts',
 }),
 Vue,
 // Tailwind CSS v4
 TailwindCSS,
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
 port: 3000,
 open: true,
 proxy: {
 '/api': {
 target: 'http://localhost:8000',
 changeOrigin: false,
 },
 },
 },
})
