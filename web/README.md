# Friday Web
Friday AI 开发自动化系统的 Web 前端应用。
## 技术栈
- **框架**: Vue 3 + TypeScript
- **构建**: Vite (rolldown-vite)
- **样式**: Tailwind CSS v4
- **UI 组件**: shadcn-vue
- **状态管理**: Pinia
- **路由**: Vue Router + unplugin-vue-router (文件路由)
- **国际化**: vue-i18n (预留能力)
- **测试**: Vitest (单元) + Playwright (E2E)
## 目录结构
```
web/
├── src/
│ ├── assets/ # 静态资源
│ ├── components/ # 全局组件
│ │ ├── ui/ # shadcn-vue 组件
│ │ └── __tests__/ # 组件测试
│ ├── composables/ # 组合式函数
│ ├── layouts/ # 布局组件
│ ├── lib/ # 工具函数
│ ├── locales/ # 国际化文件 (预留)
│ ├── pages/ # 页面 (文件路由)
│ ├── stores/ # Pinia stores
│ ├── styles/ # 全局样式
│ ├── types/ # TypeScript 类型
│ ├── App.vue # 根组件
│ └── main.ts # 应用入口
├── tests/
│ └── e2e/ # E2E 测试
├── components.json # shadcn-vue 配置
├── vite.config.ts # Vite 配置
├── vitest.config.ts # 单元测试配置
└── playwright.config.ts # E2E 测试配置
```
## 开发命令
```bash
# 安装依赖
pnpm install
# 启动开发服务器
pnpm dev
# 构建生产版本
pnpm build
# 预览生产构建
pnpm preview
# 运行单元测试
pnpm test:unit
# 运行 E2E 测试
pnpm test:e2e
# 运行 E2E 测试 (UI 模式)
pnpm test:e2e:ui
```
## 添加 shadcn-vue 组件
```bash
# 添加单个组件
npx shadcn-vue@latest add button
# 添加多个组件
npx shadcn-vue@latest add button input card
```
## 路径别名
项目使用 `~` 作为 `src` 目录的别名：
```typescript
// 导入组件
import Button from '~/components/ui/button/Button.vue'
// 导入工具函数
import { cn } from '~/lib/utils'
// 导入类型
import type { Task } from '~/types'
```
## 文件路由
页面文件位于 `src/pages/` 目录，自动生成路由：
```
src/pages/
├── index.vue → /
├── tasks/
│ ├── index.vue → /tasks
│ └── [id].vue → /tasks/:id
└── settings.vue → /settings
```
## 自动导入
以下 API 无需手动导入：
- Vue 核心 API: `ref`, `computed`, `watch`, `onMounted` 等
- VueUse 函数: `useDark`, `useStorage` 等
- Vue Router: `useRouter`, `useRoute` 等
- Pinia: `defineStore`, `storeToRefs` 等
- 项目 composables: `src/composables/` 下导出的函数
- 项目 stores: `src/stores/` 下导出的 store
## 依赖管理
项目使用 pnpm catalog 统一管理依赖版本。所有依赖版本定义在根目录的 `pnpm-workspace.yaml` 中：
```yaml
catalogs:
 default:
 vue: ^3.5.24
 # ... 其他依赖
```
在 `package.json` 中使用 `catalog:default` 引用版本：
```json
{
 "dependencies": {
 "vue": "catalog:default"
 }
}