/**
 * ConfigStore — Electron 独占读写 %APPDATA%/ai-video-studio/config.json
 *
 * Worker 不直接读这个文件，所有配置通过 CLI args / env 注入。
 *
 * 写入策略：tmp + rename 原子替换（避免读到半截 JSON）
 */
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'
import * as crypto from 'crypto'

import { configJsonPath } from './paths'
import type { AppConfig } from './types'

const DEFAULT_CONFIG: AppConfig = {
  backend_url: 'http://localhost:8000/api/v1',
  device_fp: generateDeviceFp(),
  session_token: null,
  refresh_token: null,
  user: null,
  model_mode: 'A',
  provider_keys: {}
}

function generateDeviceFp(): string {
  // 与 worker auth_client 一致：sha256(node-system-machine)[:32]
  const raw = `${os.hostname()}-${os.platform()}-${os.arch()}`
  return crypto.createHash('sha256').update(raw, 'utf8').digest('hex').slice(0, 32)
}

class ConfigStore {
  private cache: AppConfig | null = null

  load(): AppConfig {
    if (this.cache) return this.cache
    const p = configJsonPath()
    if (!fs.existsSync(p)) {
      this.cache = { ...DEFAULT_CONFIG }
      this.save(this.cache)
      return this.cache
    }
    try {
      const raw = fs.readFileSync(p, 'utf-8')
      const parsed = JSON.parse(raw) as Partial<AppConfig>
      this.cache = { ...DEFAULT_CONFIG, ...parsed }
      // 兜底：device_fp 必须有
      if (!this.cache.device_fp) {
        this.cache.device_fp = generateDeviceFp()
      }
      return this.cache
    } catch (e) {
      console.error('[config] 解析失败，重置默认:', e)
      this.cache = { ...DEFAULT_CONFIG }
      this.save(this.cache)
      return this.cache
    }
  }

  save(cfg: AppConfig): void {
    const p = configJsonPath()
    fs.mkdirSync(path.dirname(p), { recursive: true })
    const tmp = `${p}.tmp`
    fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2), 'utf-8')
    fs.renameSync(tmp, p)
    this.cache = cfg
  }

  update(patch: Partial<AppConfig>): AppConfig {
    const cur = this.load()
    const next = { ...cur, ...patch }
    this.save(next)
    return next
  }

  /** 登录成功后更新会话 */
  setSession(token: string, refreshToken: string, user: AppConfig['user']): AppConfig {
    return this.update({
      session_token: token,
      refresh_token: refreshToken,
      user
    })
  }

  /** 清空会话 */
  clearSession(): AppConfig {
    return this.update({
      session_token: null,
      refresh_token: null,
      user: null
    })
  }

  setBackendUrl(url: string): AppConfig {
    return this.update({ backend_url: url })
  }

  setProviderKey(provider: keyof AppConfig['provider_keys'],
                 key: string, model?: string): AppConfig {
    const cur = this.load()
    const next = {
      ...cur,
      provider_keys: {
        ...cur.provider_keys,
        [provider]: { key, ...(model ? { model } : {}) }
      }
    }
    this.save(next)
    return next
  }

  setModelMode(mode: 'A' | 'C'): AppConfig {
    return this.update({ model_mode: mode })
  }
}

export const configStore = new ConfigStore()
