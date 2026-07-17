/**
 * AuthClient — Electron 主进程负责所有 HTTP 鉴权
 *
 * - 登录：POST /auth/login（拿 access_token + refresh_token）
 * - 心跳：POST /auth/heartbeat（每 60s）
 * - 自动刷新：access_token 1h 过期，遇 401 先用 refresh_token（30d）换新
 * - 失效回调：onInvalid（refresh 也失败 / license 403）
 *
 * Worker 不做 auth（skip_auth=True），由 Electron 保证。
 */
import type { BrowserWindow } from 'electron'
import { configStore } from './config'
import { promptSetClient } from './promptSet'
import type { LoginResponse, User, AppConfig } from './types'

const HEARTBEAT_INTERVAL_MS = 60_000

type InvalidReason = 'session_invalid' | 'license_expired' | 'logged_out_elsewhere'

export class AuthClient {
  private heartbeatTimer: NodeJS.Timeout | null = null
  private win: BrowserWindow | null = null
  /** 防止多次 401 并发触发重复 refresh */
  private refreshPromise: Promise<boolean> | null = null

  setWindow(win: BrowserWindow): void {
    this.win = win
  }

  private async post(path: string, body: unknown, withAuth = true): Promise<Response> {
    const cfg = configStore.load()
    const url = `${cfg.backend_url}${path}`
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (withAuth && cfg.session_token) {
      headers['Authorization'] = `Bearer ${cfg.session_token}`
    }
    return fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    })
  }

  /**
   * 用 refresh_token 换新的 access_token。
   * 成功返回 true 并写入 config；失败（refresh_token 也过期/被撤销）返回 false。
   */
  async refresh(): Promise<boolean> {
    if (this.refreshPromise) return this.refreshPromise
    this.refreshPromise = (async () => {
      const cfg = configStore.load()
      if (!cfg.refresh_token) return false
      try {
        const r = await this.post('/auth/refresh',
          { refresh_token: cfg.refresh_token }, false)
        if (!r.ok) {
          console.warn(`[auth] refresh 失败: ${r.status}`)
          return false
        }
        const data = (await r.json()) as { access_token: string; expires_in: number }
        configStore.update({ session_token: data.access_token })
        return true
      } catch (e) {
        console.warn('[auth] refresh 网络错误:', e)
        return false
      } finally {
        this.refreshPromise = null
      }
    })()
    return this.refreshPromise
  }

  async login(username: string, password: string): Promise<LoginResponse> {
    const cfg = configStore.load()
    const r = await this.post('/auth/login', {
      username,
      password,
      device_fp: cfg.device_fp,
      session_type: 'desktop',
    }, false)

    if (r.status === 401) throw new Error('用户名或密码错误')
    if (r.status === 403) {
      const body = await r.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || '账号已禁用或授权已过期')
    }
    if (!r.ok) {
      const body = await r.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `登录失败 (${r.status})`)
    }
    const data = (await r.json()) as LoginResponse
    configStore.setSession(data.access_token, data.refresh_token, data.user)
    this.startHeartbeat()
    // 后台拉 prompt 集（不阻塞登录返回）
    this.syncPrompts()
    return data
  }

  async logout(): Promise<void> {
    this.stopHeartbeat()
    try {
      await this.post('/auth/logout', {}, true)
    } catch (e) {
      console.warn('[auth] logout 请求失败（忽略）:', e)
    }
    configStore.clearSession()
  }

  /** 启动 60s 心跳；遇 401 先 refresh 再重试一次，refresh 也失败才回调 onInvalid */
  startHeartbeat(): void {
    this.stopHeartbeat()
    const tick = async () => {
      try {
        let r = await this.post('/auth/heartbeat', {}, true)
        if (r.status === 401) {
          // access_token 过期（最常见），先尝试 refresh
          const ok = await this.refresh()
          if (ok) {
            // 用新 token 重试一次
            r = await this.post('/auth/heartbeat', {}, true)
          }
          if (!ok || r.status === 401) {
            this.notifyInvalid('session_invalid')
            return
          }
        }
        if (r.status === 403) {
          this.notifyInvalid('license_expired')
          return
        }
        if (!r.ok) {
          console.warn(`[auth] heartbeat 非 2xx: ${r.status}`)
        }
        // 心跳成功 → piggyback 检查 prompt 集版本
        promptSetClient.heartbeatTick().catch(e => {
          console.warn('[auth] prompt 集版本检查失败（忽略）:', e)
        })
      } catch (e) {
        // 网络问题，不立即踢下线（可能是临时断网）
        console.warn('[auth] heartbeat 网络错误（不立即失效）:', e)
      }
    }
    // 启动后立刻发一次确认 session 还在
    tick()
    this.heartbeatTimer = setInterval(tick, HEARTBEAT_INTERVAL_MS)
  }

  stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private notifyInvalid(reason: InvalidReason): void {
    console.warn(`[auth] 会话失效: ${reason}`)
    configStore.clearSession()
    this.stopHeartbeat()
    if (this.win && !this.win.isDestroyed()) {
      const channel = reason === 'license_expired' ? 'auth:license-expired' : 'auth:session-invalid'
      this.win.webContents.send(channel, { reason })
    }
  }

  /** 应用启动时如果已有 token，恢复心跳 */
  resumeIfHasSession(): boolean {
    const cfg = configStore.load()
    if (cfg.session_token && cfg.user) {
      this.startHeartbeat()
      // 启动时也同步一次 prompt 集（admin 可能改了）
      this.syncPrompts()
      return true
    }
    return false
  }

  /** 后台拉 prompt 集（不阻塞登录返回；失败仅 warn） */
  private async syncPrompts(): Promise<void> {
    try {
      const r = await promptSetClient.sync()
      if (!r.ok) {
        console.warn('[auth] prompt 集 sync 失败:', r.error)
      }
    } catch (e) {
      console.warn('[auth] prompt 集 sync 异常:', e)
    }
  }

  getCurrentUser(): User | null {
    return configStore.load().user
  }
}

export const authClient = new AuthClient()

/** 透出 configStore 给 ipc.ts 用 */
export function getBackendUrl(): string {
  return configStore.load().backend_url
}

export function getAllConfig(): AppConfig {
  return configStore.load()
}
