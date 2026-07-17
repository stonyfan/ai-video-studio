/**
 * PromptSetClient — 拉取用户绑定的 prompt 集，缓存本地
 *
 * 流程：
 * 1. login/resume 后调 sync()：GET /prompts/me → 拿到 {id, version, content_yaml}
 * 2. 比对 cachedIdVersion（"<id>:<version>"），相同则跳过
 * 3. 写入 %APPDATA%/ai-video-studio/prompts/<id>_<version>.yaml（tmp + rename 原子）
 * 4. 清理同 id 的旧版本文件
 * 5. 持久化 last synced path 到 config.json
 *
 * 心跳 piggyback：每 N 次心跳查 /prompts/me/version，不同则触发完整 sync
 *
 * 失败策略：网络错误 → fallback 上次缓存；首次启动无缓存 + 后端不可达 → 由 worker.ts
 * 兜底传 bundled prompts.yaml。
 */
import * as fs from 'fs'
import * as path from 'path'
import { app } from 'electron'

import { configStore } from './config'
import { bundledPromptsPath } from './paths'
import type { PromptSetOption } from './types'

const PROMPTS_SUBDIR = 'prompts'

/** 心跳 piggyback 间隔（每 N 次心跳查一次版本） */
const VERSION_CHECK_EVERY_N_HEARTBEATS = 5

interface PromptSetResponse {
  id: number
  name: string
  version: number
  content_yaml: string
}

interface VersionResponse {
  id: number
  version: number
}

export interface PromptSetCache {
  id: number
  version: number
  path: string
}

export interface SyncResult {
  ok: boolean
  updated: boolean
  version?: number
  error?: string
}

class PromptSetClient {
  private heartbeatCounter = 0

  /** prompts 缓存目录：%APPDATA%/ai-video-studio/prompts/ */
  private promptsDir(): string {
    const p = path.join(app.getPath('userData'), PROMPTS_SUBDIR)
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true })
    return p
  }

  /** 上次同步的缓存路径（持久化在 config.json） */
  getCachedPath(): string | null {
    const cfg = configStore.load()
    const cache = cfg.prompt_set_cache
    if (!cache) return null
    // 校验文件还在（用户可能手动删过）
    if (!fs.existsSync(cache.path)) {
      // 清掉无效 cache
      configStore.update({ prompt_set_cache: null })
      return null
    }
    return cache.path
  }

  /** 完整 sync：GET /prompts/me → 写盘 */
  async sync(): Promise<SyncResult> {
    const cfg = configStore.load()
    if (!cfg.session_token) {
      return { ok: false, updated: false, error: '未登录' }
    }
    try {
      const r = await fetch(`${cfg.backend_url}/prompts/me`, {
        headers: { Authorization: `Bearer ${cfg.session_token}` },
      })
      if (r.status === 401 || r.status === 403) {
        // token 过期等：让上层（auth）走 refresh，sync 下次心跳再试
        return { ok: false, updated: false, error: `鉴权失败 ${r.status}` }
      }
      if (!r.ok) {
        return { ok: false, updated: false, error: `后端返回 ${r.status}` }
      }
      const data = (await r.json()) as PromptSetResponse
      const sig = `${data.id}:${data.version}`

      // 比对缓存
      const existing = cfg.prompt_set_cache
      if (existing && `${existing.id}:${existing.version}` === sig && fs.existsSync(existing.path)) {
        // 版本一致 + 文件还在 → 不重写
        return { ok: true, updated: false, version: data.version }
      }

      // 写盘：tmp + rename 原子
      const dir = this.promptsDir()
      const finalPath = path.join(dir, `${data.id}_${data.version}.yaml`)
      const tmpPath = `${finalPath}.tmp`
      fs.writeFileSync(tmpPath, data.content_yaml, 'utf8')
      fs.renameSync(tmpPath, finalPath)

      // 清理同 id 的旧版本文件
      const prefix = `${data.id}_`
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(prefix) && f !== `${data.id}_${data.version}.yaml` && f.endsWith('.yaml')) {
          try { fs.unlinkSync(path.join(dir, f)) } catch { /* ignore */ }
        }
      }

      // 持久化
      configStore.update({
        prompt_set_cache: {
          id: data.id,
          version: data.version,
          path: finalPath,
        },
      })

      console.log(`[promptSet] synced id=${data.id} v${data.version} → ${finalPath}`)
      return { ok: true, updated: true, version: data.version }
    } catch (e) {
      return { ok: false, updated: false, error: (e as Error).message }
    }
  }

  /** 心跳 piggyback：每 N 次心跳查版本，不同则触发完整 sync */
  async heartbeatTick(): Promise<SyncResult | null> {
    this.heartbeatCounter++
    if (this.heartbeatCounter % VERSION_CHECK_EVERY_N_HEARTBEATS !== 0) {
      return null
    }
    const cfg = configStore.load()
    if (!cfg.session_token) return null

    try {
      const r = await fetch(`${cfg.backend_url}/prompts/me/version`, {
        headers: { Authorization: `Bearer ${cfg.session_token}` },
      })
      if (!r.ok) return null
      const data = (await r.json()) as VersionResponse
      const existing = cfg.prompt_set_cache
      // 版本变化 或 首次没缓存 → 触发完整 sync
      if (!existing || existing.id !== data.id || existing.version !== data.version) {
        console.log(`[promptSet] 版本变化 (old=${
          existing ? `${existing.id}:v${existing.version}` : 'none'
        } new=${data.id}:v${data.version}) → sync`)
        return await this.sync()
      }
      return { ok: true, updated: false, version: data.version }
    } catch (e) {
      console.warn('[promptSet] heartbeat version check 失败（忽略）:', e)
      return null
    }
  }

  /** Phase 12：列出当前用户可切换的 prompt 集 */
  async listOptions(): Promise<PromptSetOption[]> {
    const cfg = configStore.load()
    const r = await fetch(`${cfg.backend_url}/prompts/me/options`, {
      headers: { Authorization: `Bearer ${cfg.session_token}` },
    })
    if (!r.ok) throw new Error(`listOptions HTTP ${r.status}`)
    return (await r.json()) as PromptSetOption[]
  }

  /** Phase 12：用户切换当前 prompt 集 → 后端更新 → 立即 sync 拉新 yaml */
  async select(promptSetId: number): Promise<void> {
    const cfg = configStore.load()
    const r = await fetch(`${cfg.backend_url}/prompts/me/select`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${cfg.session_token}`,
      },
      body: JSON.stringify({ prompt_set_id: promptSetId }),
    })
    if (!r.ok) {
      const err = await r.text()
      throw new Error(`select HTTP ${r.status}: ${err}`)
    }
    // 切换后立即 sync（拉新 yaml 到缓存）
    await this.sync()
  }

  /** worker spawn 时用：缓存路径 + signature（写 job_config.json 用） */
  resolveForWorker(): { promptsPath: string; signature: string } {
    const cache = configStore.load().prompt_set_cache
    if (cache && fs.existsSync(cache.path)) {
      return {
        promptsPath: cache.path,
        signature: `${cache.id}:${cache.version}`,
      }
    }
    // 兜底：bundled prompts.yaml（保证 worker 能跑）
    return {
      promptsPath: bundledPromptsPath(),
      signature: 'bundled',
    }
  }
}

export const promptSetClient = new PromptSetClient()
