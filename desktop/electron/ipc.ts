/**
 * IPC 注册中心 — ipcMain.handle 主进程接收 renderer 调用
 *
 * 通道命名：<scope>:<action>，对应 preload.ts 中 contextBridge 暴露的 api
 */
import { app, ipcMain, dialog, BrowserWindow } from 'electron'

import { authClient, getBackendUrl, getAllConfig } from './auth'
import { configStore } from './config'
import { workerRunner } from './worker'
import { updater } from './updater'
import { submitErrorReport } from './errorReport'
import { promptSetClient } from './promptSet'
import { curateRunner } from './curate'
import type { JobOptions, Provider } from './types'

export function registerIpc(win: BrowserWindow): void {
  // 让 worker/auth 持有 window 引用（用于 send 事件）
  authClient.setWindow(win)
  workerRunner.setWindow(win)
  updater.setWindow(win)

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

  ipcMain.handle('config:setModelMode',
    (_evt, args: { mode: 'A' | 'C' }) => {
      configStore.setModelMode(args.mode)
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

  ipcMain.handle('worker:resumeJob', async (_evt, args: { jobId: string }) => {
    try {
      return { ok: true as const, handle: await workerRunner.resumeJob(args.jobId) }
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

  ipcMain.handle('worker:getJobDetail', (_evt, args: { jobId: string }) => {
    return workerRunner.getJobDetail(args.jobId)
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

  // === updater ===
  ipcMain.handle('updater:check', async () => {
    const info = await updater.check()
    return info ?? null
  })
  ipcMain.handle('updater:download', async () => {
    await updater.download()
    return { ok: true }
  })
  ipcMain.handle('updater:install', () => {
    updater.install()
    return { ok: true }
  })
  ipcMain.handle('updater:getState', () => {
    return updater.getState()
  })
  ipcMain.handle('updater:remindLater', () => {
    updater.remindLater()
    return { ok: true }
  })

  // === error report ===
  ipcMain.handle('error-report:submit', async (_evt, args: { message: string; jobId?: string }) => {
    return submitErrorReport({ message: args.message, jobId: args.jobId })
  })

  // === prompt set ===
  ipcMain.handle('prompt-set:sync', async () => {
    return promptSetClient.sync()
  })

  ipcMain.handle('prompt-set:getState', () => {
    const cfg = configStore.load()
    return cfg.prompt_set_cache || null
  })

  ipcMain.handle('prompt-set:listOptions', async () => {
    return await promptSetClient.listOptions()
  })

  ipcMain.handle('prompt-set:select', async (_evt, promptSetId: number) => {
    await promptSetClient.select(promptSetId)
    return { ok: true }
  })

  // === curate (手动剪辑) — subprocess 模式 ===
  curateRunner.setWindow(win)

  ipcMain.handle('curate:getData', async (_evt, args: { jobId: string; inputDir?: string }) => {
    return curateRunner.getData(args.jobId, args.inputDir)
  })

  ipcMain.handle('curate:buildPreviews', async (_evt, args: { jobId: string }) => {
    return curateRunner.buildPreviews(args.jobId)
  })

  ipcMain.handle('curate:submit', async (
    _evt,
    args: { jobId: string; payload: unknown; inputDir?: string },
  ) => {
    return curateRunner.submit(
      args.jobId,
      args.payload as import('./curate').CurateSubmitPayload,
      args.inputDir,
    )
  })

  ipcMain.handle('curate:regenerate', async (
    _evt,
    args: { jobId: string; payload: unknown; inputDir?: string },
  ) => {
    return curateRunner.regenerate(
      args.jobId,
      args.payload as import('./curate').RegeneratePayload,
      args.inputDir,
    )
  })

  ipcMain.handle('curate:cancel', async (_evt, args: { jobId: string }) => {
    return curateRunner.cancel(args.jobId)
  })
}

export function unregisterIpc(): void {
  // Electron 不会自动清理 ipcMain.handle，重复注册会报错
  // 应用退出时不需要手动移除（进程会清理）
  // 此处保留接口给未来的 hot-reload 场景用
}
