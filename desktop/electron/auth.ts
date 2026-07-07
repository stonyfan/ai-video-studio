/**
 * AuthClient — Electron 主进程负责所有 HTTP 鉴权
 *
 * - 登录：POST /auth/login（拿 access_token + refresh_token）
 * - 心跳：POST /auth/heartbeat（每 60s）
 * - 失效回调：onInvalid（session 401 / license 403）
 *
 * Worker 不做 auth（skip_auth=True），由 Electron 保证。
 */
import type { BrowserWindow } from 'electron'
import { configStore } from './config'
import type { LoginResponse, User, AppConfig } from './types'

const HEARTBEAT_INTERVAL_MS = 60_000

type InvalidReason = 'session_invalid' | 'license_expired' | 'logged_out_elsewhere'

export class AuthClient {
  private heartbeatTimer: NodeJS.Timeout | null = null
  private win: BrowserWindow | null = null

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

  async login(username: string, password: string): Promise<LoginResponse> {
    const cfg = configStore.load()
    const r = await this.post('/auth/login', {
      username,
      password,
      device_fp: cfg.device_fp
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

  /** 启动 60s 心跳；首次失败立即触发回调 */
  startHeartbeat(): void {
    this.stopHeartbeat()
    const tick = async () => {
      try {
        const r = await this.post('/auth/heartbeat', {}, true)
        if (r.status === 401) {
          this.notifyInvalid('session_invalid')
          return
        }
        if (r.status === 403) {
          this.notifyInvalid('license_expired')
          return
        }
        if (!r.ok) {
          console.warn(`[auth] heartbeat 非 2xx: ${r.status}`)
        }
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
      return true
    }
    return false
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
