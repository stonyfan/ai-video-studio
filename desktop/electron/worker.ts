/**
 * WorkerRunner — spawn video-worker.exe + 监听 progress.json + tail stdout
 *
 * 调用方式：
 *   video-worker.exe run -i <dir> -p douyin -d 30 --skip-auth --work-root <abs>
 *     --job-id <id>
 *
 * API key/model 通过 env WORKER_API_KEY/WORKER_MODEL 注入（不读 config.json）
 *
 * 事件（通过 webContents.send 推到 renderer）:
 *   - job:log        stdout/stderr 每行
 *   - job:progress   progress.json 改动
 *   - job:done       子进程退出 0 + result.json
 *   - job:failed     子进程退出 !=0 或异常
 */
import { spawn, ChildProcess } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import chokidar, { type FSWatcher } from 'chokidar'

import { workerExePath, jobsRoot } from './paths'
import { configStore } from './config'
import { promptSetClient } from './promptSet'
import type { BrowserWindow } from 'electron'
import type { JobOptions, JobProgress, JobResult, JobHandle, JobSummary } from './types'

class WorkerRunner {
  private processes = new Map<string, ChildProcess>()
  private watchers = new Map<string, FSWatcher>()
  private win: BrowserWindow | null = null

  setWindow(win: BrowserWindow | null): void {
    this.win = win
  }

  async startJob(opts: JobOptions): Promise<JobHandle> {
    const jobId = opts.job_id || `job_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
    const workRoot = jobsRoot()
    const exe = workerExePath()

    if (!fs.existsSync(exe)) {
      throw new Error(`worker exe 不存在: ${exe}`)
    }

    // 读 API key/model 注入 env
    const cfg = configStore.load()

    // 按 mode 构造 env：A=直连（需要本地 key），C=云端代理（用 JWT 调后端）
    const workerEnv: Record<string, string> = {
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
    }

    if (cfg.model_mode === 'C') {
      // C 模式：用 JWT 调后端 model_proxy
      if (!cfg.session_token) {
        throw new Error('C 模式需要登录态（session_token 为空，请先登录）')
      }
      // backend_url 形如 http://host:port/api/v1，proxy_base_url 取到 /api/v1 为止
      const backendBase = cfg.backend_url.replace(/\/api\/v1\/?$/, '/api/v1')
      workerEnv.WORKER_MODE = 'proxy'
      workerEnv.WORKER_AUTH_TOKEN = cfg.session_token
      workerEnv.WORKER_PROXY_BASE_URL = `${backendBase}/vision/${opts.provider}`
      // model 仍走 env（让用户能指定模型名）
      const providerCfg = cfg.provider_keys[opts.provider]
      if (providerCfg?.model) workerEnv.WORKER_MODEL = providerCfg.model
    } else {
      // A 模式：直连 provider
      const providerKey = cfg.provider_keys[opts.provider]
      if (!providerKey?.key) {
        throw new Error(`未配置 ${opts.provider} 的 API key（A 模式需要在设置页填写）`)
      }
      workerEnv.WORKER_API_KEY = providerKey.key
      workerEnv.WORKER_MODEL = providerKey.model || ''
    }

    const args = [
      'run',
      '-i', opts.input,
      '-p', opts.platform,
      '-s', opts.style,
      '-d', String(opts.duration),
      '--provider', opts.provider,
      '--orchestration-mode', opts.orchestration_mode || 'timeline',
      '--skill', opts.skill || 'auto',
      '--skip-auth',          // Electron 已保证登录态
      '--work-root', workRoot,
      '--job-id', jobId,
    ]
    if (opts.bgm) args.push('--bgm', opts.bgm)
    if (opts.skip_vision) args.push('--skip-vision')
    if (opts.skip_render) args.push('--skip-render')
    if (opts.resume) args.push('--resume')
    if (opts.variants && opts.variants > 1) args.push('--variants', String(opts.variants))

    // Phase 10: 注入 prompt 集路径 + signature（用于 resume 时校验）
    const { promptsPath, signature } = promptSetClient.resolveForWorker()
    args.push('--prompts-path', promptsPath)
    workerEnv.WORKER_PROMPTS_SIG = signature

    console.log(`[worker] mode=${cfg.model_mode} provider=${opts.provider} job=${jobId} prompts=${signature}`)

    const child = spawn(exe, args, {
      env: {
        ...process.env,
        ...workerEnv,
      },
      windowsHide: false,                // 显示子进程窗口（便于调试）
    })

    this.processes.set(jobId, child)

    // tail stdout
    child.stdout?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf-8')
      // 按行切，便于 UI 展示
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) {
          this.emit('job:log', { jobId, line })
        }
      }
    })

    // tail stderr（worker 把日志同时写 stdout + stderr，logger 配置如此）
    child.stderr?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf-8')
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) {
          this.emit('job:log', { jobId, line, level: 'warn' })
        }
      }
    })

    // chokidar 监听 progress.json
    const progressPath = this.progressPath(jobId)
    const watcher = chokidar.watch(progressPath, {
      awaitWriteFinish: { stabilityThreshold: 100, pollInterval: 50 },
      usePolling: true,                  // Windows 上 polling 比 native 更可靠
      interval: 500,
    })
    this.watchers.set(jobId, watcher)
    watcher.on('change', () => this.readProgress(jobId))
    watcher.on('add', () => this.readProgress(jobId))

    // 退出处理
    child.on('exit', async (code, signal) => {
      // 等待 result.json 落盘
      const result = await this.readResult(jobId)
      if (code === 0 && result?.status === 'completed') {
        this.emit('job:done', { jobId, result })
      } else {
        const errMsg = result?.error?.message || `进程退出码 ${code}`
        this.emit('job:failed', { jobId, code, message: errMsg, result })
      }
      this.cleanup(jobId)
    })

    child.on('error', (err) => {
      console.error(`[worker] ${jobId} spawn error:`, err)
      this.emit('job:failed', { jobId, code: -1, message: err.message })
      this.cleanup(jobId)
    })

    return { jobId, pid: child.pid ?? -1 }
  }

  cancel(jobId: string): boolean {
    const child = this.processes.get(jobId)
    if (!child) return false
    try {
      child.kill('SIGTERM')
      // Windows 上 SIGTERM 等价于 SIGKILL（强制终止）
      // 5 秒后还没退，再 kill
      setTimeout(() => {
        if (!child.killed) child.kill('SIGKILL')
      }, 5000)
      return true
    } catch (e) {
      console.error(`[worker] cancel ${jobId} 失败:`, e)
      return false
    }
  }

  /**
   * 续跑已存在的任务：读 logs/job_config.json，用同样的 job_id + --resume 启动
   * 已完成的中间产物（preprocess/scene/analyze）会被跳过。
   */
  async resumeJob(jobId: string): Promise<JobHandle> {
    const cfgPath = path.join(this.jobDir(jobId), 'logs', 'job_config.json')
    if (!fs.existsSync(cfgPath)) {
      throw new Error(`找不到任务配置: ${cfgPath}（旧版本任务不支持续跑）`)
    }
    const saved = JSON.parse(fs.readFileSync(cfgPath, 'utf-8')) as {
      input_path: string
      platform: string
      style: string
      target_duration: number
      bgm_path: string | null
      provider: string
      orchestration_mode?: 'timeline' | 'llm' | 'default'
    }
    const opts: JobOptions = {
      input: saved.input_path,
      platform: saved.platform as JobOptions['platform'],
      style: saved.style as JobOptions['style'],
      duration: saved.target_duration,
      provider: saved.provider as JobOptions['provider'],
      job_id: jobId,
      resume: true,
    }
    if (saved.orchestration_mode) opts.orchestration_mode = saved.orchestration_mode
    if (saved.bgm_path) opts.bgm = saved.bgm_path
    return this.startJob(opts)
  }

  listJobs(): JobSummary[] {
    const root = jobsRoot()
    if (!fs.existsSync(root)) return []
    const dirs = fs.readdirSync(root)
      .filter(name => fs.statSync(path.join(root, name)).isDirectory())
    return dirs.map(name => this.summarizeJob(name))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
  }

  getJobDetail(jobId: string): { result: JobResult | null; progress: JobProgress | null } {
    return {
      result: this.tryReadJson<JobResult>(this.resultPath(jobId)),
      progress: this.tryReadJson<JobProgress>(this.progressPath(jobId))
    }
  }

  private summarizeJob(jobId: string): JobSummary {
    const dir = this.jobDir(jobId)
    const stat = fs.statSync(dir)
    const result = this.tryReadJson<JobResult>(this.resultPath(jobId))
    const progress = this.tryReadJson<JobProgress>(this.progressPath(jobId))

    const status = result?.status || progress?.status || 'unknown'
    const createdAt = stat.mtime.toISOString().slice(0, 19).replace('T', ' ')
    return {
      job_id: jobId,
      status,
      created_at: createdAt,
      final_video: result?.final_video || null,
      error_message: result?.error?.message || null,
      duration_sec: result?.cost?.duration_sec || null
    }
  }

  private tryReadJson<T>(p: string): T | null {
    if (!fs.existsSync(p)) return null
    try {
      return JSON.parse(fs.readFileSync(p, 'utf-8')) as T
    } catch {
      return null
    }
  }

  openJobFolder(jobId: string): boolean {
    const dir = path.join(jobsRoot(), jobId)
    if (!fs.existsSync(dir)) return false
    // Windows 资源管理器打开
    spawn('explorer.exe', [dir], { detached: true, shell: false })
    return true
  }

  // ---- 内部 ----

  private jobDir(jobId: string): string {
    return path.join(jobsRoot(), jobId)
  }

  private progressPath(jobId: string): string {
    return path.join(this.jobDir(jobId), 'logs', 'progress.json')
  }

  private resultPath(jobId: string): string {
    return path.join(this.jobDir(jobId), 'logs', 'result.json')
  }

  private async readProgress(jobId: string): Promise<void> {
    try {
      const raw = await fs.promises.readFile(this.progressPath(jobId), 'utf-8')
      const data = JSON.parse(raw) as JobProgress
      this.emit('job:progress', { jobId, progress: data })
    } catch (e) {
      // 文件可能正在写入，忽略
    }
  }

  private async readResult(jobId: string): Promise<JobResult | null> {
    const p = this.resultPath(jobId)
    // 给文件系统一点时间
    for (let i = 0; i < 10; i++) {
      if (fs.existsSync(p)) break
      await new Promise(r => setTimeout(r, 200))
    }
    if (!fs.existsSync(p)) return null
    try {
      const raw = await fs.promises.readFile(p, 'utf-8')
      return JSON.parse(raw) as JobResult
    } catch (e) {
      console.error(`[worker] 读 result.json 失败:`, e)
      return null
    }
  }

  private cleanup(jobId: string): void {
    this.processes.delete(jobId)
    const w = this.watchers.get(jobId)
    if (w) {
      w.close().catch(() => {})
      this.watchers.delete(jobId)
    }
  }

  private emit(channel: string, payload: unknown): void {
    if (this.win && !this.win.isDestroyed()) {
      this.win.webContents.send(channel, payload)
    }
  }
}

export const workerRunner = new WorkerRunner()
