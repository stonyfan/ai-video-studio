/**
 * Step 2 冒烟测试页 — 验证 IPC 通路 + worker spawn + 事件
 * Step 3 会替换成正式的 Login/Dashboard/NewJob 等
 */
import { useEffect, useState } from 'react'

// window.api 由 preload 注入
declare global {
  interface Window {
    api: import('../electron/preload').Api
  }
}

interface LogLine {
  ts: string
  line: string
  level?: string
}

export default function App() {
  const [version, setVersion] = useState<string>('?')
  const [backendUrl, setBackendUrl] = useState<string>('?')
  const [config, setConfig] = useState<unknown>(null)
  const [inputDir, setInputDir] = useState<string>('')
  const [duration, setDuration] = useState<number>(10)
  const [logs, setLogs] = useState<LogLine[]>([])
  const [progress, setProgress] = useState<string>('(无)')
  const [status, setStatus] = useState<string>('idle')

  useEffect(() => {
    // 启动时拉基本信息
    window.api.app.getVersion().then(setVersion)
    window.api.app.getBackendUrl().then(setBackendUrl)
    window.api.config.getAll().then(setConfig)

    // 订阅 worker 事件
    const offProgress = window.api.worker.onProgress(p => {
      setProgress(`${p.progress && (p.progress as any).status} @ ${(p.progress as any).timestamp || ''}`)
    })
    const offLog = window.api.worker.onLog(p => {
      setLogs(prev => [...prev.slice(-200), {
        ts: new Date().toLocaleTimeString(),
        line: p.line,
        level: p.level
      }])
    })
    const offDone = window.api.worker.onDone(p => {
      setStatus(`done: ${p.result && (p.result as any).status}`)
    })
    const offFailed = window.api.worker.onFailed(p => {
      setStatus(`failed: ${p.message}`)
    })

    return () => { offProgress(); offLog(); offDone(); offFailed() }
  }, [])

  const chooseFolder = async () => {
    const dir = await window.api.dialog.chooseFolder()
    if (dir) setInputDir(dir)
  }

  const runSmokeJob = async () => {
    if (!inputDir) {
      alert('请先选素材目录')
      return
    }
    setLogs([])
    setStatus('starting...')
    const result = await window.api.worker.startJob({
      input: inputDir,
      platform: 'general',
      style: 'fast_cut',
      duration,
      provider: 'qwen-vl',
      skip_vision: true,        // 冒烟测试不调 AI
      skip_render: true,        // 跳过渲染，更快
    } as any)
    if (!(result as any).ok) {
      setStatus(`start 失败: ${(result as any).error}`)
    } else {
      setStatus(`running ${(result as any).handle.jobId}`)
    }
  }

  return (
    <div style={{ padding: 24, fontFamily: 'sans-serif' }}>
      <h1>AI Video Studio — Smoke Test</h1>
      <p>版本: {version} | 后端: {backendUrl}</p>
      <details>
        <summary>本地配置</summary>
        <pre style={{ background: '#f5f5f5', padding: 12, fontSize: 12 }}>
          {JSON.stringify(config, null, 2)}
        </pre>
      </details>

      <hr style={{ margin: '16px 0' }} />

      <h3>冒烟测试：跑一个 skip-vision + skip-render 的 job</h3>
      <div style={{ marginBottom: 8 }}>
        <button onClick={chooseFolder}>选素材目录</button>
        <span style={{ marginLeft: 8 }}>{inputDir || '(未选)'}</span>
      </div>
      <div style={{ marginBottom: 8 }}>
        时长:
        <input type="number" value={duration}
               onChange={e => setDuration(parseInt(e.target.value) || 10)}
               style={{ marginLeft: 8, width: 60 }} />
        <button onClick={runSmokeJob} style={{ marginLeft: 16 }}>开始</button>
      </div>

      <div style={{ marginTop: 16 }}>
        <strong>状态:</strong> {status}<br />
        <strong>进度:</strong> {progress}
      </div>

      <h4>日志</h4>
      <pre style={{
        background: '#1e1e1e', color: '#d4d4d4',
        padding: 12, height: 300, overflow: 'auto',
        fontSize: 11, fontFamily: 'Consolas, monospace'
      }}>
        {logs.map((l, i) => (
          <div key={i}>
            <span style={{ color: '#888' }}>[{l.ts}]</span>{' '}
            {l.line}
          </div>
        ))}
      </pre>
    </div>
  )
}
