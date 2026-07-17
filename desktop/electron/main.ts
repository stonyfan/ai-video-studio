/**
 * Electron 主进程入口
 *
 * - 单实例锁（防重复启动）
 * - BrowserWindow 创建
 * - dev/prod 加载不同 URL
 * - 启动后恢复会话（如有 token，启动心跳）
 */
import { app, BrowserWindow, shell, Menu, protocol, net } from 'electron'
import * as path from 'path'

import { registerIpc } from './ipc'
import { authClient } from './auth'
import { workerRunner } from './worker'
import { updater } from './updater'
import { workerExists } from './paths'

/**
 * 解析打包后的资源路径。
 *
 * electron-vite 打包后 __dirname 在某些场景下为空字符串，
 * 用 app.getAppPath() 兜底（packaged 模式指向 app.asar 根）。
 */
function resolveAppPath(...segments: string[]): string {
  const base = (__dirname && __dirname.length > 0)
    ? __dirname
    : path.join(app.getAppPath(), 'out', 'main')
  return path.join(base, ...segments)
}

// 注册自定义 protocol（必须在 app ready 前）
// 用于 renderer 加载本地视频，绕过 file:// 的安全限制
protocol.registerSchemesAsPrivileged([
  { scheme: 'local-video', privileges: { stream: true, standard: true, supportFetchAPI: true } }
])

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
    // 注册 local-video protocol handler：读取本地文件返回 stream
    // URL 格式：local-video://video?path=<urlencoded 的绝对路径>
    protocol.handle('local-video', (request) => {
      const url = new URL(request.url)
      const filePath = url.searchParams.get('path')
      if (!filePath) {
        return new Response('missing path param', { status: 400 })
      }
      // 转发到 file:// 让 net.fetch 处理 Range 请求等
      return net.fetch(`file:///${filePath}`)
    })

    createWindow()
    registerIpc(mainWindow!)
    updater.setWindow(mainWindow)

    // 启动时检查 worker exe
    if (!workerExists()) {
      console.warn('[main] worker exe 不存在（dev 模式可能未构建，prod 模式安装失败）')
    }

    // 恢复会话（如有）
    authClient.resumeIfHasSession()

    // Phase 11：上报上次升级成功（fire-and-forget，不阻塞启动）
    // 在 updater.start() 之前调，确保只跑一次
    updater.reportUpgradeIfNeeded()

    // 自动更新检查（30s 后首次 + 24h 周期）
    updater.start()
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
    updater.stop()
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
      preload: resolveAppPath('..', 'preload', 'preload.js'),
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
    // dev 模式默认 docked devtools（贴右侧），按 F12 切换显隐
    mainWindow.webContents.openDevTools({ mode: 'right' })
  } else {
    mainWindow.loadFile(resolveAppPath('..', 'renderer', 'index.html'))
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
