<script setup lang="ts">
import type { SystemInfoResponse } from '~/api/system'
import { onMounted, ref } from 'vue'
import { getAllSettings, SettingKey, updateSetting } from '~/api/settings'
import {
  downloadSystemBackup,
  getSystemInfo,
  restoreSystemBackup,
} from '~/api/system'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { handleError } = useErrorHandler()
const { success, error: showError, info } = useToast()

// ============================================================================
// Host 配置
// ============================================================================

const hostValue = ref('')
const hostLoading = ref(true)
const hostSaving = ref(false)
const hostDirty = ref(false)

async function loadHost() {
  hostLoading.value = true
  try {
    const settings = await getAllSettings()
    const found = settings.find(s => s.key === SettingKey.SITE_HOST)
    hostValue.value = found?.value ?? ''
    hostDirty.value = false
  }
  catch (e) {
    handleError(e, '加载 Host 配置')
  }
  finally {
    hostLoading.value = false
  }
}

async function saveHost() {
  if (!hostValue.value.trim()) {
    info('Host 为空时将使用默认行为')
  }
  hostSaving.value = true
  try {
    await updateSetting(SettingKey.SITE_HOST, hostValue.value.trim())
    success('Host 配置已保存')
    hostDirty.value = false
  }
  catch (e) {
    handleError(e, '保存 Host 配置')
  }
  finally {
    hostSaving.value = false
  }
}

// ============================================================================
// 系统信息
// ============================================================================

const systemInfo = ref<SystemInfoResponse | null>(null)
const infoLoading = ref(true)

async function loadSystemInfo() {
  infoLoading.value = true
  try {
    systemInfo.value = await getSystemInfo()
  }
  catch (e) {
    handleError(e, '加载系统信息')
  }
  finally {
    infoLoading.value = false
  }
}

// ============================================================================
// 备份 / 恢复
// ============================================================================

const downloadingBackup = ref(false)
const restoreFile = ref<File | null>(null)
const restoring = ref(false)

async function handleDownloadBackup() {
  downloadingBackup.value = true
  try {
    const { blob, filename } = await downloadSystemBackup()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    success('备份下载已开始')
  }
  catch (e) {
    handleError(e, '下载备份')
  }
  finally {
    downloadingBackup.value = false
  }
}

function onRestoreFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  restoreFile.value = target.files?.[0] ?? null
}

async function handleRestore() {
  if (!restoreFile.value) {
    showError('请先选择备份文件')
    return
  }
  restoring.value = true
  try {
    const result = await restoreSystemBackup(restoreFile.value)
    success(
      result.restored_tables != null
        ? `数据库恢复成功，共恢复 ${result.restored_tables} 张表`
        : '数据库恢复成功',
    )
    restoreFile.value = null
    // 刷新页面以使用新数据库
    setTimeout(() => {
      window.location.reload()
    }, 1500)
  }
  catch (e) {
    handleError(e, '恢复备份')
  }
  finally {
    restoring.value = false
  }
}

// ============================================================================
// Lifecycle
// ============================================================================

onMounted(() => {
  void loadHost()
  void loadSystemInfo()
})
</script>

<template>
  <div class="space-y-6">
    <!-- 1. Host 配置 -->
    <div class="card overflow-hidden">
      <div class="flex items-center gap-3 p-6 border-b border-border/50">
        <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
          <span class="icon-[lucide--globe] text-2xl text-primary" />
        </div>
        <div class="flex-1">
          <h2 class="text-lg font-semibold">
            站点 Host
          </h2>
          <p class="text-sm text-muted-foreground">
            配置当前站点的访问地址，用于生成回调 URL、邮件链接等
          </p>
        </div>
      </div>

      <div class="p-6 space-y-4">
        <div v-if="hostLoading" class="flex items-center gap-2 text-muted-foreground">
          <span class="icon-[lucide--loader-circle] animate-spin" />
          加载中...
        </div>
        <div v-else class="space-y-3">
          <div class="space-y-2">
            <Label for="site-host">站点地址</Label>
            <div class="relative">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
              <Input
                id="site-host"
                v-model="hostValue"
                placeholder="https://friday.example.com"
                class="pl-10 h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                @input="hostDirty = true"
              />
            </div>
            <p class="text-xs text-muted-foreground">
              本系统的访问地址，用于生成第三方登录回调等链接。留空时自动使用当前访问地址。
            </p>
          </div>
          <div class="flex justify-end">
            <Button
              :disabled="hostSaving || !hostDirty"
              @click="saveHost"
            >
              <span v-if="hostSaving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--save] mr-2" />
              保存 Host
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 版本信息 -->
    <div class="card overflow-hidden">
      <div class="flex items-center gap-3 p-6 border-b border-border/50">
        <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
          <span class="icon-[lucide--git-branch] text-2xl text-emerald-500" />
        </div>
        <div class="flex-1">
          <h2 class="text-lg font-semibold">
            版本信息
          </h2>
          <p class="text-sm text-muted-foreground">
            当前运行版本与运行时环境
          </p>
        </div>
      </div>

      <div class="p-6">
        <div v-if="infoLoading" class="flex items-center gap-2 text-muted-foreground">
          <span class="icon-[lucide--loader-circle] animate-spin" />
          加载中...
        </div>
        <div v-else-if="systemInfo" class="space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="rounded-xl bg-muted/30 border border-border/30 p-4 text-center">
              <p class="text-2xl font-bold text-primary">
                {{ systemInfo.version.current }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Friday AI 版本
              </p>
            </div>
            <div class="rounded-xl bg-muted/30 border border-border/30 p-4 text-center">
              <p class="text-2xl font-bold text-foreground">
                {{ systemInfo.python_version }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Python
              </p>
            </div>
            <div class="rounded-xl bg-muted/30 border border-border/30 p-4 text-center">
              <p class="text-2xl font-bold text-foreground">
                {{ systemInfo.django_version }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Django
              </p>
            </div>
            <div class="rounded-xl bg-muted/30 border border-border/30 p-4 text-center">
              <p class="text-2xl font-bold text-foreground">
                {{ systemInfo.database.size }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                数据库大小
              </p>
            </div>
          </div>

          <div class="flex gap-3">
            <Button variant="outline" size="sm" as-child>
              <a href="/CHANGELOG.md" target="_blank" rel="noopener">
                <span class="icon-[lucide--file-text] mr-2" />
                查看更新日志
              </a>
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 数据备份 -->
    <div class="card overflow-hidden">
      <div class="flex items-center gap-3 p-6 border-b border-border/50">
        <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
          <span class="icon-[lucide--database-backup] text-2xl text-amber-500" />
        </div>
        <div class="flex-1">
          <h2 class="text-lg font-semibold">
            数据备份
          </h2>
          <p class="text-sm text-muted-foreground">
            备份或恢复数据库（含所有配置、凭证、对话记录）。按当前数据库引擎自动选择 pg_dump / mysqldump / SQLite 文件
          </p>
        </div>
      </div>

      <div class="p-6 space-y-6">
        <!-- 备份 -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium">
                下载备份
              </p>
              <p class="text-xs text-muted-foreground">
                导出当前数据库完整副本，包含所有数据与配置
              </p>
            </div>
            <Button
              variant="outline"
              :disabled="downloadingBackup"
              @click="handleDownloadBackup"
            >
              <span v-if="downloadingBackup" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--download] mr-2" />
              下载备份
            </Button>
          </div>
        </div>

        <div class="border-t border-border/50" />

        <!-- 恢复 -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium">
                恢复备份
              </p>
              <p class="text-xs text-muted-foreground">
                上传备份文件恢复数据库（.db / .dump / .sql）。恢复前会自动备份当前数据库。
              </p>
            </div>
          </div>

          <div class="rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2 flex items-start gap-2">
            <span class="icon-[lucide--alert-triangle] text-amber-500 mt-0.5 shrink-0" />
            <p class="text-xs text-amber-600 dark:text-amber-400">
              恢复操作将覆盖当前所有数据，请确认备份文件来源可靠。恢复成功后页面将自动刷新。
            </p>
          </div>

          <div class="flex items-center gap-3">
            <input
              type="file"
              accept=".db,.dump,.sql"
              class="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-primary/10 file:px-3 file:py-2 file:text-sm file:font-medium file:text-primary hover:file:bg-primary/20 cursor-pointer"
              @change="onRestoreFileChange"
            >
            <Button
              variant="default"
              :disabled="!restoreFile || restoring"
              @click="handleRestore"
            >
              <span v-if="restoring" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--upload] mr-2" />
              恢复备份
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
