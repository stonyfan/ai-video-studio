/**
 * IPC 注册中心 — ipcMain.handle 主进程接收 renderer 调用
 *
 * 通道命名：<scope>:<action>，对应 preload.ts 中 contextBridge 暴露的 api
 */
import { app, ipcMain, dialog, BrowserWindow } from 'electron'

import { authClient, getBackendUrl, getAllConfig } from './auth'
import { configStore } from './config'
import { workerRunner } from './worker'
import type { JobOptions, Provider } from './types'

export function registerIpc(win: BrowserWindow): void {
  // 让 worker/auth 持有 window 引用（用于 send 事件）
  authClient.setWindow(win)
  workerRunner.setWindow(win)

  // === auth ===
  ipcMain.handle('auth:login', async (_evt, args: { username: string; password: string }) => {
    return authClient.login(args.username, args.password)
  })

  ipcMain.handle('auth:logout', async () => {
    await authClient.logout()
    return { ok: true }
  })

  ipcMain.handle('auth:getCurrentUser', () => {
    return authClient.getCurrentUser()
  })

  // === config ===
  ipcMain.handle('config:getAll', () => {
    return getAllConfig()
  })

  ipcMain.handle('config:setBackendUrl', (_evt, args: { url: string }) => {
    configStore.setBackendUrl(args.url)
    return { ok: true }
  })

  ipcMain.handle('config:setProviderKey',
    (_evt, args: { provider: Provider; key: string; model?: string }) => {
      configStore.setProviderKey(args.provider, args.key, args.model)
      return { ok: true }
    })

  // === worker ===
  ipcMain.handle('worker:startJob', async (_evt, opts: JobOptions) => {
    try {
      return { ok: true as const, handle: await workerRunner.startJob(opts) }
    } catch (e) {
      const err = e as Error
      return { ok: false as const, error: err.message }
    }
  })

  ipcMain.handle('worker:cancel', (_evt, args: { jobId: string }) => {
    return workerRunner.cancel(args.jobId)
  })

  ipcMain.handle('worker:listJobs', () => {
    return workerRunner.listJobs()
  })

  ipcMain.handle('worker:openFolder', (_evt, args: { jobId: string }) => {
    return workerRunner.openJobFolder(args.jobId)
  })

  // === dialog ===
  ipcMain.handle('dialog:chooseFolder', async () => {
    const result = await dialog.showOpenDialog(win, {
      properties: ['openDirectory']
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  // === app ===
  ipcMain.handle('app:getVersion', () => app.getVersion())
  ipcMain.handle('app:getBackendUrl', () => getBackendUrl())
}

export function unregisterIpc(): void {
  // Electron 不会自动清理 ipcMain.handle，重复注册会报错
  // 应用退出时不需要手动移除（进程会清理）
  // 此处保留接口给未来的 hot-reload 场景用
}
