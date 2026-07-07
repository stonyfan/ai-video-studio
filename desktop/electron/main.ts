/**
 * Electron 主进程入口
 *
 * - 单实例锁（防重复启动）
 * - BrowserWindow 创建
 * - dev/prod 加载不同 URL
 * - 启动后恢复会话（如有 token，启动心跳）
 */
import { app, BrowserWindow, shell, Menu } from 'electron'
import * as path from 'path'

import { registerIpc } from './ipc'
import { authClient } from './auth'
import { workerRunner } from './worker'
import { workerExists } from './paths'

// 单实例锁：第二次启动直接 focus 已有窗口
let mainWindow: BrowserWindow | null = null

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(() => {
    createWindow()
    registerIpc(mainWindow!)

    // 启动时检查 worker exe
    if (!workerExists()) {
      console.warn('[main] worker exe 不存在（dev 模式可能未构建，prod 模式安装失败）')
    }

    // 恢复会话（如有）
    if (authClient.resumeIfHasSession()) {
      console.log('[main] 恢复登录态')
    }
  })

  app.on('window-all-closed', () => {
    // macOS 习惯保留菜单，其它平台直接退出
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })

  app.on('before-quit', async () => {
    workerRunner.setWindow(null)
    authClient.stopHeartbeat()
  })
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    show: false,             // 防止白屏闪现
    backgroundColor: '#ffffff',
    title: 'AI Video Studio',
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false         // preload 需要 require
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()
  })

  // 外链在系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // dev: Vite dev server；prod: 打包后的 index.html
  if (process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'))
  }

  // 简化菜单（仅保留必要的）
  if (process.platform === 'darwin') {
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { role: 'appMenu' },
      { role: 'editMenu' },
      { role: 'viewMenu' },
      { role: 'windowMenu' }
    ]))
  } else {
    Menu.setApplicationMenu(null)   // Windows 默认无菜单
  }
}
