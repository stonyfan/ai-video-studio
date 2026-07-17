/**
 * UpdaterClient — 静默下载 + 提示安装
 *
 * - 启动 30s 后调 backend `/updates/check`，带 `X-Device-FP` header
 * - 每 24h 复查一次
 * - 检测到新版本：
 *   - force_upgrade（必须升级到 target）：弹不可关闭 Modal 阻塞
 *   - current_deprecated（cur < min_supported）：弹不可关闭 Modal 阻塞
 *   - 普通：renderer 右下角通知"立即下载"按钮
 * - 用户点下载 → 写入 %TEMP%/ai-video-studio-setup-<ver>.exe，sha256 校验
 * - 下载完成 → 持久化到 config.update_cache，通知"立即安装"
 *
 * Phase 5 新增：
 * - X-Device-FP header（后端按 device_fp 命中灰度）
 * - grace 期判断：后端 release 已回滚但本地已下载 → grace_hours 内静默通知，超期清包
 * - 版本变化时清旧 cache（防止反复提示旧版本）
 *
 * 不用 electron-updater：我们的 backend 是自定义 API + NSIS 安装要 UAC，
 * electron-updater 的 latest.yml/GitHub 模型不匹配。
 */
import { app, BrowserWindow, shell } from 'electron'
import * as fs from 'fs'
import * as path from 'path'
import * as os from 'os'
import * as crypto from 'crypto'
import * as http from 'http'
import * as https from 'https'
import { URL } from 'url'

import { configStore } from './config'

const INITIAL_DELAY_MS = Number(process.env.UPDATE_CHECK_DELAY_MS ?? 30_000)
const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000  // 24h
const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000     // 10min 应足够 80MB
/** "稍后提醒"按钮的默认再次提示间隔（12h） */
const REMIND_LATER_INTERVAL_MS = 12 * 60 * 60 * 1000

interface UpdateCheckResult {
  has_update: boolean
  latest_version: string | null
  download_url: string | null
  sha256: string | null
  release_notes: string | null
  min_supported: string | null
  current_deprecated: boolean
  force_upgrade: boolean
  grace_hours: number | null
}

type UpdateState =
  | { status: 'idle' }
  | { status: 'available'; info: UpdateCheckResult }
  | { status: 'downloading'; info: UpdateCheckResult; progress: number }
  | { status: 'downloaded'; info: UpdateCheckResult; installerPath: string; downloadedAt: number }
  | { status: 'failed'; error: string }

class UpdaterClient {
  private win: BrowserWindow | null = null
  private timer: NodeJS.Timeout | null = null
  private state: UpdateState = { status: 'idle' }
  /** 下载中的 AbortController，用于取消 */
  private abort: AbortController | null = null
  /** "稍后提醒"的到期时间戳；null 表示未在推迟中 */
  private remindAfter: number | null = null

  setWindow(win: BrowserWindow | null): void {
    this.win = win
  }

  /** 启动定时检查（main.ts whenReady 调用） */
  start(): void {
    setTimeout(() => this.check().catch(() => {}), INITIAL_DELAY_MS)
    this.timer = setInterval(() => this.check().catch(() => {}), CHECK_INTERVAL_MS)
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    this.cancelDownload()
  }

  /** 主动触发一次检查（IPC 调用，比如 Settings 页"检查更新"按钮） */
  async check(): Promise<UpdateCheckResult | null> {
    const cfg = configStore.load()
    const url = new URL(`${cfg.backend_url}/updates/check`)
    url.searchParams.set('current_version', app.getVersion())
    url.searchParams.set('platform', 'windows')
    try {
      const r = await fetch(url.toString(), {
        method: 'GET',
        headers: { 'X-Device-FP': cfg.device_fp },
      })
      if (!r.ok) {
        console.warn(`[updater] check 非 2xx: ${r.status}`)
        return null
      }
      const info = (await r.json()) as UpdateCheckResult
      this.handleCheckResult(info)
      return info
    } catch (e) {
      console.warn('[updater] check 网络错误（忽略）:', e)
      return null
    }
  }

  private handleCheckResult(info: UpdateCheckResult): void {
    const cache = configStore.load().update_cache

    // === 后端告知"无可用更新" ===
    if (!info.has_update) {
      // 本地缓存的安装包版本就是当前已装版本 → 用户已经装好了，清 cache 进入 idle
      if (cache && cache.version === app.getVersion()) {
        this.clearCache()
        this.setState({ status: 'idle' })
        return
      }
      // 但本地缓存的安装包版本已不在 active 列表（被回滚） → grace 期判断
      if (cache) {
        const graceMs = (info.grace_hours ?? 24) * 3600_000
        const age = Date.now() - cache.downloaded_at
        if (age < graceMs) {
          // grace 期内：静默通知用户已下载的包仍可装
          this.send('update:downloaded', {
            installerPath: cache.installer_path,
            version: cache.version,
            inGrace: true,
          })
          this.setState({
            status: 'downloaded',
            info: {
              ...info,
              // 借用 cache 信息组装 info（让 install() 能工作）
              has_update: false,
              latest_version: cache.version,
              download_url: null,
              sha256: cache.sha256,
            },
            installerPath: cache.installer_path,
            downloadedAt: cache.downloaded_at,
          })
          return
        }
        // grace 超期 → 清掉旧包，重新进入 idle
        this.clearCache()
      }
      // 推迟期未到 → 不打扰
      if (this.remindAfter !== null && Date.now() < this.remindAfter) return
      this.setState({ status: 'idle' })
      return
    }

    // === 有新版本 ===
    // 版本变化 → 清旧 cache（防止反复提示旧版本）
    if (cache && cache.version !== info.latest_version) {
      this.clearCache()
    }

    // force_upgrade 或 current_deprecated：永远阻塞，无视 remindAfter
    if (info.force_upgrade) {
      this.setState({ status: 'available', info })
      this.send('update:force-upgrade', info)
      return
    }
    if (info.current_deprecated) {
      this.setState({ status: 'available', info })
      this.send('update:deprecated', info)
      return
    }

    // 推迟期未到 → 不打扰
    if (this.remindAfter !== null && Date.now() < this.remindAfter) return

    this.setState({ status: 'available', info })
    this.send('update:available', info)
  }

  /** 用户点"稍后提醒"：推迟 REMIND_LATER_INTERVAL_MS 后再提示 */
  remindLater(): void {
    this.remindAfter = Date.now() + REMIND_LATER_INTERVAL_MS
  }

  /** 用户从 renderer 触发下载 */
  async download(): Promise<void> {
    if (this.state.status !== 'available') return
    const info = this.state.info
    if (!info.download_url || !info.sha256) {
      this.setState({ status: 'failed', error: '后端未提供 download_url 或 sha256' })
      return
    }
    this.cancelDownload()
    this.abort = new AbortController()
    const installerPath = path.join(
      os.tmpdir(),
      `ai-video-studio-setup-${info.latest_version}.exe`
    )
    this.setState({ status: 'downloading', info, progress: 0 })

    try {
      await downloadToFile(resolveDownloadUrl(info.download_url), installerPath, {
        signal: this.abort.signal,
        onProgress: (p) => {
          if (this.state.status === 'downloading') {
            this.state.progress = p
            this.send('update:progress', { progress: p })
          }
        },
        timeoutMs: DOWNLOAD_TIMEOUT_MS,
      })
      // sha256 校验
      const actual = await sha256(installerPath)
      if (actual.toLowerCase() !== info.sha256.toLowerCase()) {
        fs.unlinkSync(installerPath)
        throw new Error(`sha256 不匹配：期望 ${info.sha256.slice(0, 12)}…，实际 ${actual.slice(0, 12)}…`)
      }
      const downloadedAt = Date.now()
      this.setState({ status: 'downloaded', info, installerPath, downloadedAt })
      // 持久化到 config（重启后 grace 期判断要用）
      configStore.update({
        update_cache: {
          version: info.latest_version!,
          installer_path: installerPath,
          downloaded_at: downloadedAt,
          sha256: info.sha256,
        }
      })
      this.send('update:downloaded', { installerPath, version: info.latest_version })
    } catch (e) {
      const err = e as Error
      this.setState({ status: 'failed', error: err.message })
      this.send('update:failed', { error: err.message })
    } finally {
      this.abort = null
    }
  }

  /** 用户点"立即安装"：shell 启动安装包 + 退出本程序 */
  install(): void {
    if (this.state.status !== 'downloaded') return
    const installerPath = this.state.installerPath
    const info = this.state.info

    // Phase 11：写 pending 标记，新版本首次启动时上报升级成功
    // 必须在 shell.openPath 之前写，因为 app.quit() 紧随其后
    if (info.latest_version) {
      configStore.update({
        pending_upgrade_report: {
          from_version: app.getVersion(),
          to_version: info.latest_version,
          timestamp: Date.now(),
        },
      })
    }

    // NSIS 安装程序接管，本进程退出
    shell.openPath(installerPath).then((ok) => {
      if (!ok) {
        this.send('update:failed', { error: '无法启动安装程序' })
        return
      }
      app.quit()
    })
  }

  /** Phase 11：新版本首次启动时调，上报上次升级成功（fire-and-forget）
   *
   * 流程：
   * 1. 读 config.pending_upgrade_report，没有就直接 return
   * 2. 立即清标记（防重复上报，即使下面请求失败也丢一次就算）
   * 3. POST /updates/report-upgrade（无鉴权，device_fp 兜底）
   * 4. 失败静默丢弃，不重试
   *
   * 在 main.ts 的 app.whenReady() 内调一次（在 updater.start() 前）。
   */
  async reportUpgradeIfNeeded(): Promise<void> {
    const cfg = configStore.load()
    const pending = cfg.pending_upgrade_report
    if (!pending) return

    // 立即清标记（防重复）
    configStore.update({ pending_upgrade_report: null })

    try {
      const r = await fetch(`${cfg.backend_url}/api/v1/updates/report-upgrade`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Device-FP': cfg.device_fp,
        },
        body: JSON.stringify({
          from_version: pending.from_version,
          to_version: pending.to_version,
        }),
      })
      if (!r.ok && r.status !== 204) {
        console.warn(`[updater] report-upgrade HTTP ${r.status} (drop)`)
      }
    } catch (e) {
      console.warn('[updater] report-upgrade failed (drop):', e)
    }
  }

  cancelDownload(): void {
    if (this.abort) {
      this.abort.abort()
      this.abort = null
    }
  }

  getState(): UpdateState {
    return this.state
  }

  private clearCache(): void {
    const cache = configStore.load().update_cache
    if (cache) {
      try { fs.unlinkSync(cache.installer_path) } catch {}
      configStore.update({ update_cache: null })
    }
  }

  private setState(s: UpdateState): void {
    this.state = s
  }

  private send(channel: string, payload: unknown): void {
    if (this.win && !this.win.isDestroyed()) {
      this.win.webContents.send(channel, payload)
    }
  }
}

/** 把后端的 download_url（相对路径 or 完整 URL）规整为可直接喂给 http.get 的 URL（encode 空格等不安全字符） */
function resolveDownloadUrl(downloadUrl: string): string {
  // 已是完整 URL：encode path 部分（保留 :// 和 query）
  if (/^https?:\/\//i.test(downloadUrl)) {
    const u = new URL(downloadUrl)
    u.pathname = u.pathname.split('/').map(encodeURIComponent).join('/')
    return u.toString()
  }
  // 相对路径：拼 backend_url
  const cfg = configStore.load()
  const u = new URL(downloadUrl, cfg.backend_url)
  u.pathname = u.pathname.split('/').map(encodeURIComponent).join('/')
  return u.toString()
}

/** 下载 URL 到本地文件，带进度 + 超时 + 可取消 */
function downloadToFile(url: string, dest: string, opts: {
  signal: AbortSignal
  onProgress: (percent: number) => void
  timeoutMs: number
}): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest)
    // 根据 URL 协议选择 client（dev 用 http，prod 用 https）
    const client = url.startsWith('https:') ? https : http
    const req = client.get(url, (res) => {
      // 处理重定向（S3/OSS 常见）
      if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close()
        fs.unlinkSync(dest)
        downloadToFile(res.headers.location, dest, opts).then(resolve, reject)
        return
      }
      if (res.statusCode !== 200) {
        file.close()
        fs.unlinkSync(dest)
        reject(new Error(`下载失败 HTTP ${res.statusCode}`))
        return
      }
      const total = parseInt(res.headers['content-length'] || '0', 10)
      let recv = 0
      res.on('data', (chunk: Buffer) => {
        recv += chunk.length
        if (total > 0) opts.onProgress(Math.floor(recv * 100 / total))
      })
      res.pipe(file)
      file.on('finish', () => file.close((err) => err ? reject(err) : resolve()))
    })
    req.on('error', (e) => {
      file.close()
      try { fs.unlinkSync(dest) } catch {}
      reject(e)
    })
    req.setTimeout(opts.timeoutMs, () => {
      req.destroy(new Error('下载超时'))
    })
    opts.signal.addEventListener('abort', () => {
      req.destroy(new Error('用户取消'))
    })
  })
}

function sha256(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256')
    const stream = fs.createReadStream(file)
    stream.on('data', (d) => hash.update(d))
    stream.on('end', () => resolve(hash.digest('hex')))
    stream.on('error', reject)
  })
}

export const updater = new UpdaterClient()
