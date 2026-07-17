/**
 * CurateRunner — spawn python scripts/curate_cli.py，按 worker.ts 同款模式
 *
 * 协议：stdout 每行一个 JSON
 *   {"type":"log","level":"...","msg":"..."}
 *   {"type":"progress","done":N,"todo":N,"stage":"...","msg":"..."}
 *   {"type":"data","data":{...}}              load-data 终态
 *   {"type":"result","result":{...}}          submit 终态
 *   {"type":"done"}                            build-previews 终态
 *   {"type":"error","message":"..."}           致命错误
 *
 * 事件（推到 renderer）：
 *   curate:log      { jobId, level, msg }
 *   curate:progress { jobId, done, todo, stage, msg }
 *
 * 调用：getData/buildPreviews/submit 都返回 Promise，resolve = 成功，reject = 失败。
 */
import { spawn, ChildProcess } from 'child_process'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'

import { jobsRoot } from './paths'
import { configStore } from './config'
import type { BrowserWindow } from 'electron'
import type { Provider } from './types'

// === 类型（与 desktop/src/api/curate.ts 共享） ====================

export interface CurateScene {
  id: string
  source_id: string
  start: number
  end: number
  creation_time: string
  action_type: string
  main_objects: string[]
  highlight_score: number
  visual_quality: number
  motion_score: number
  preview_path: string
  preview_ready: boolean
}

export interface CurateStage {
  id: string
  title: string
  scene_ids: string[]
  representative: string | null
  size: number
}

export interface CurateData {
  job_id: string
  input_dir: string
  target_duration_default: number
  stages: CurateStage[]
  scenes_by_id: Record<string, CurateScene>
  previews_ready: boolean
  auto_selected_ids: string[]
}

export interface CurateSelection {
  stage_id: string
  scene_ids: string[]
}

export interface CurateSubmitPayload {
  selections: CurateSelection[]
  target_duration: number
  brief: string
  provider: string
  llm_model: string
}

export interface RegeneratePayload {
  instruction: string
  target_duration: number
  provider: string
  llm_model: string
}

export interface CurateResultItem {
  order: number
  id: string
  cut_duration: number
  use_start: number
  use_end: number
  reason: string
}

export interface CurateResult {
  final_video: string
  narrative: string
  items: CurateResultItem[]
  total_duration: number
}

// === Python 路径 ==================================================

function projectRoot(): string {
  // dev: out/main/main.js 上溯 3 级
  return path.resolve(__dirname, '..', '..', '..')
}

function curateCliPath(): string {
  return path.join(projectRoot(), 'scripts', 'curate_cli.py')
}

function pythonExe(): string {
  // 优先项目 venv，找不到用系统 python
  const root = projectRoot()
  const candidates = [
    path.join(root, '.venv', 'Scripts', 'python.exe'),
    path.join(root, 'venv', 'Scripts', 'python.exe'),
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  return 'python'
}

// === Runner =======================================================

type MsgHandler = (msg: any) => void

class CurateRunner {
  private processes = new Map<string, ChildProcess>()   // jobId -> child
  private win: BrowserWindow | null = null

  setWindow(win: BrowserWindow | null): void {
    this.win = win
  }

  /** load-data：返回完整 CurateData */
  async getData(jobId: string, inputDir?: string): Promise<CurateData> {
    const args = ['load-data', '--job', jobId]
    if (inputDir) args.push('--input-dir', inputDir)
    const finalMsg = await this.run(jobId, args)
    if (finalMsg.type !== 'data') {
      throw new Error(`load-data 异常终态: ${JSON.stringify(finalMsg)}`)
    }
    return finalMsg.data as CurateData
  }

  /** build-previews：流式 progress，resolve 表示完成 */
  async buildPreviews(jobId: string): Promise<void> {
    const args = ['build-previews', '--job', jobId]
    const finalMsg = await this.run(jobId, args)
    if (finalMsg.type !== 'done') {
      throw new Error(`build-previews 异常终态: ${JSON.stringify(finalMsg)}`)
    }
  }

  /** submit：流式 progress，resolve = CurateResult */
  async submit(jobId: string, payload: CurateSubmitPayload, inputDir?: string): Promise<CurateResult> {
    const payloadPath = this.writePayload(jobId, payload)
    const args = ['submit', '--job', jobId, '--payload', payloadPath]
    if (inputDir) args.push('--input-dir', inputDir)
    try {
      const finalMsg = await this.run(jobId, args)
      if (finalMsg.type !== 'result') {
        throw new Error(`submit 异常终态: ${JSON.stringify(finalMsg)}`)
      }
      return finalMsg.result as CurateResult
    } finally {
      // 清理临时 payload
      try { fs.unlinkSync(payloadPath) } catch {}
    }
  }

  /** regenerate：基于当前 storyboard + 自然语言指令再编辑 */
  async regenerate(jobId: string, payload: RegeneratePayload, inputDir?: string): Promise<CurateResult> {
    const payloadPath = this.writePayload(jobId, payload)
    const args = ['regenerate', '--job', jobId, '--payload', payloadPath]
    if (inputDir) args.push('--input-dir', inputDir)
    try {
      const finalMsg = await this.run(jobId, args)
      if (finalMsg.type !== 'result') {
        throw new Error(`regenerate 异常终态: ${JSON.stringify(finalMsg)}`)
      }
      return finalMsg.result as CurateResult
    } finally {
      try { fs.unlinkSync(payloadPath) } catch {}
    }
  }

  cancel(jobId: string): boolean {
    const child = this.processes.get(jobId)
    if (!child) return false
    try {
      child.kill('SIGTERM')
      setTimeout(() => { if (!child.killed) child.kill('SIGKILL') }, 5000)
      return true
    } catch {
      return false
    }
  }

  // ---- 内部 ----

  private writePayload(jobId: string, payload: unknown): string {
    const tmp = path.join(os.tmpdir(), `curate_payload_${jobId}_${Date.now()}.json`)
    fs.writeFileSync(tmp, JSON.stringify(payload), 'utf-8')
    return tmp
  }

  private async run(jobId: string, args: string[]): Promise<any> {
    const cli = curateCliPath()
    if (!fs.existsSync(cli)) {
      throw new Error(`curate_cli.py 不存在: ${cli}`)
    }
    const py = pythonExe()
    const fullArgs = [cli, ...args]

    // 读 config，挑一个已配置的 provider 注入 env（参考 worker.ts 模式）
    const cfg = configStore.load()
    const providers: Provider[] = ['doubao-agent-plan', 'doubao', 'qwen-vl', 'glm']
    let picked: { provider: Provider; key: string; model?: string } | null = null
    for (const p of providers) {
      const pk = cfg.provider_keys[p]
      if (pk?.key) {
        picked = { provider: p, key: pk.key, model: pk.model }
        break
      }
    }
    if (!picked) {
      throw new Error('没有已配置的 provider key，请先到设置页配置（推荐 doubao-agent-plan）')
    }

    const curateEnv: Record<string, string> = {
      ARK_API_KEY: picked.key,         // DoubaoProvider 默认从 ARK_API_KEY 读
      WORKER_PROVIDER: picked.provider,
      WORKER_MODEL: picked.model || '',
    }
    // 兼容 qwen-vl / glm 的 env 变量名
    if (picked.provider === 'qwen-vl') {
      curateEnv.DASHSCOPE_API_KEY = picked.key
    } else if (picked.provider === 'glm') {
      curateEnv.ZHIPU_API_KEY = picked.key
    }

    return new Promise((resolve, reject) => {
      const child = spawn(py, fullArgs, {
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
          CURATE_JOBS_ROOT: jobsRoot(),
          ...curateEnv,
        },
        windowsHide: false,
      })
      this.processes.set(jobId, child)

      let buffer = ''
      let finalMsg: any = null
      let lastError: string | null = null

      const dispatchLine = (line: string) => {
        const trimmed = line.trim()
        if (!trimmed) return
        let msg: any
        try {
          msg = JSON.parse(trimmed)
        } catch {
          // 非 JSON 行直接当 log
          this.emit('curate:log', { jobId, level: 'info', msg: trimmed })
          return
        }
        switch (msg.type) {
          case 'log':
            this.emit('curate:log', { jobId, level: msg.level || 'info', msg: msg.msg })
            break
          case 'progress':
            this.emit('curate:progress', {
              jobId, done: msg.done || 0, todo: msg.todo || 0,
              stage: msg.stage || '', msg: msg.msg || '',
            })
            break
          case 'data':
          case 'result':
          case 'done':
            finalMsg = msg
            break
          case 'error':
            lastError = msg.message + (msg.traceback ? `\n${msg.traceback}` : '')
            break
        }
      }

      child.stdout?.on('data', (chunk: Buffer) => {
        buffer += chunk.toString('utf-8')
        const lines = buffer.split(/\r?\n/)
        buffer = lines.pop() || ''   // 最后一行不完整，留 buffer
        for (const line of lines) dispatchLine(line)
      })

      child.stderr?.on('data', (chunk: Buffer) => {
        const text = chunk.toString('utf-8')
        for (const line of text.split(/\r?\n/)) {
          if (line.trim()) {
            this.emit('curate:log', { jobId, level: 'warn', msg: line })
          }
        }
      })

      child.on('exit', (code) => {
        // flush buffer 里最后一行
        if (buffer.trim()) dispatchLine(buffer)
        this.processes.delete(jobId)
        if (code === 0 && finalMsg) {
          resolve(finalMsg)
        } else {
          reject(new Error(lastError || `curate 进程退出码 ${code}`))
        }
      })

      child.on('error', (err) => {
        this.processes.delete(jobId)
        reject(new Error(`spawn curate 失败: ${err.message}`))
      })
    })
  }

  private emit(channel: string, payload: unknown): void {
    if (this.win && !this.win.isDestroyed()) {
      this.win.webContents.send(channel, payload)
    }
  }
}

export const curateRunner = new CurateRunner()
