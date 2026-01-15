import { fileURLToPath } from 'node:url'
import { configDefaults, defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'
export default mergeConfig(
 viteConfig,
 defineConfig({
 test: {
 environment: 'happy-dom',
 exclude: [...configDefaults.exclude, 'tests/e2e/**'],
 root: fileURLToPath(new URL('./', import.meta.url)),
 include: ['src/**/*.{test,spec}.{js,ts}'],
 coverage: {
 provider: 'v8',
 reporter: ['text', 'json', 'html'],
 exclude: [
 'node_modules/',
 'src/**/*.d.ts',
 'src/main.ts',
 ],
 },
 },
 }),
)
