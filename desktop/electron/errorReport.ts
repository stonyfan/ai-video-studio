/**
 * 错误上报模块 — 主进程收集日志 + 打包 + 上传到后端
 *
 * 流程：
 * 1. 创建临时 staging 目录
 * 2. 收集：用户 message / 系统信息 / config（脱敏）/ job 日志（如有）
 * 3. 用 PowerShell Compress-Archive 打包为 zip（Windows 原生，无新依赖）
 * 4. multipart/form-data 上传到 /api/v1/error-reports
 * 5. 清理临时文件
 */
import { app } from 'electron'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'
import { spawn } from 'child_process'

import { configStore } from './config'
import { jobsRoot } from './paths'

export interface ErrorReportResult {
  ok: boolean
  id?: number
  error?: string
}

/** 调用方传参 */
export interface ErrorReportRequest {
  message: string
  jobId?: string
}

/**
 * 收集系统信息（脱敏：不包含任何 API key 明文）
 */
function buildSystemInfo(jobId?: string): string {
  const cfg = configStore.load()
  const providerKeysRedacted: Record<string, { has_key: boolean; model?: string }> = {}
  for (const [k, v] of Object.entries(cfg.provider_keys)) {
    providerKeysRedacted[k] = { has_key: !!v?.key, model: v?.model }
  }
  const info = {
    timestamp: new Date().toISOString(),
    app_version: app.getVersion(),
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome,
    platform: process.platform,
    arch: process.arch,
    os_release: os.release(),
    hostname: os.hostname(),
    job_id: jobId || null,
    model_mode: cfg.model_mode,
    backend_url: cfg.backend_url,
    user: cfg.user ? { id: cfg.user.id, username: cfg.user.username, role: cfg.user.role } : null,
    provider_keys: providerKeysRedacted,
  }
  return JSON.stringify(info, null, 2)
}

/**
 * 写出 staging 文件，返回 staging 目录路径
 */
function prepareStaging(req: ErrorReportRequest): string {
  const staging = fs.mkdtempSync(path.join(os.tmpdir(), 'err-report-'))
  // 1. 用户 message
  fs.writeFileSync(path.join(staging, 'message.txt'), req.message, 'utf-8')
  // 2. 系统信息
  fs.writeFileSync(path.join(staging, 'system_info.json'), buildSystemInfo(req.jobId), 'utf-8')
  // 3. job 日志（如有 jobId）
  if (req.jobId) {
    const jobDir = path.join(jobsRoot(), req.jobId)
    if (fs.existsSync(jobDir)) {
      // 拷贝整个 logs 子目录
      const logsSrc = path.join(jobDir, 'logs')
      const logsDst = path.join(staging, 'job_logs')
      if (fs.existsSync(logsSrc)) {
        copyDirSync(logsSrc, logsDst)
      }
      // 同时把 job_config.json 拷一份到根
      const jobCfgSrc = path.join(logsSrc, 'job_config.json')
      if (fs.existsSync(jobCfgSrc)) {
        fs.copyFileSync(jobCfgSrc, path.join(staging, 'job_config.json'))
      }
    }
  }
  return staging
}

function copyDirSync(src: string, dst: string): void {
  fs.mkdirSync(dst, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name)
    const d = path.join(dst, entry.name)
    if (entry.isDirectory()) {
      copyDirSync(s, d)
    } else if (entry.isFile()) {
      // 跳过太大的中间产物（视频片段等）— 只关心日志
      const stat = fs.statSync(s)
      if (stat.size <= 5 * 1024 * 1024 && !/\.(mp4|mov|mkv|avi|wav|mp3|aac|m4a)$/i.test(entry.name)) {
        fs.copyFileSync(s, d)
      }
    }
  }
}

/**
 * 用 PowerShell Compress-Archive 打包
 */
function zipStaging(staging: string, zipPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    // Compress-Archive -Path 'staging\*' -DestinationPath zip -Force
    const ps = spawn('powershell.exe', [
      '-NoProfile', '-NonInteractive', '-Command',
      `Compress-Archive -Path '${staging}\\*' -DestinationPath '${zipPath}' -Force`,
    ], { windowsHide: true })
    let stderr = ''
    ps.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString('utf-8') })
    ps.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`Compress-Archive 失败 (code=${code}): ${stderr}`))
    })
    ps.on('error', reject)
  })
}

/**
 * 上传到后端
 */
async function uploadZip(zipPath: string, req: ErrorReportRequest): Promise<ErrorReportResult> {
  const cfg = configStore.load()
  if (!cfg.session_token) {
    return { ok: false, error: '未登录（无 session_token）' }
  }
  const url = `${cfg.backend_url}/error-reports`
  const fileBuf = fs.readFileSync(zipPath)

  // 用 FormData + Blob 走 multipart/form-data
  const form = new FormData()
  form.append('message', req.message)
  if (req.jobId) form.append('job_id', req.jobId)
  form.append('client_version', app.getVersion())
  form.append('client_platform', process.platform)
  form.append('file', new Blob([fileBuf], { type: 'application/zip' }), 'report.zip')

  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${cfg.session_token}` },
    body: form,
  })
  if (r.status === 201) {
    const data = await r.json() as { id: number; ok: boolean }
    return { ok: true, id: data.id }
  }
  if (r.status === 401) {
    return { ok: false, error: '会话已失效，请重新登录后再上报' }
  }
  if (r.status === 413) {
    return { ok: false, error: '日志包过大（超过 20MB 限制）' }
  }
  let detail = ''
  try { detail = JSON.stringify(await r.json()) } catch { detail = r.statusText }
  return { ok: false, error: `上传失败 (${r.status}): ${detail}` }
}

/**
 * 主入口：收集 + 打包 + 上传 + 清理
 */
export async function submitErrorReport(req: ErrorReportRequest): Promise<ErrorReportResult> {
  if (!req.message || !req.message.trim()) {
    return { ok: false, error: '请填写问题描述' }
  }
  let staging: string | null = null
  let zipPath: string | null = null
  try {
    staging = prepareStaging(req)
    zipPath = path.join(os.tmpdir(), `err-report-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.zip`)
    await zipStaging(staging, zipPath)
    // 大小检查（与后端一致 20MB）
    const stat = fs.statSync(zipPath)
    if (stat.size > 20 * 1024 * 1024) {
      return { ok: false, error: `日志包过大（${(stat.size/1024/1024).toFixed(1)}MB > 20MB）` }
    }
    return await uploadZip(zipPath, req)
  } catch (e) {
    const err = e as Error
    console.error('[errorReport] 失败:', err)
    return { ok: false, error: err.message }
  } finally {
    // 清理临时文件
    if (staging) {
      try { fs.rmSync(staging, { recursive: true, force: true }) } catch {}
    }
    if (zipPath) {
      try { fs.rmSync(zipPath, { force: true }) } catch {}
    }
  }
}
