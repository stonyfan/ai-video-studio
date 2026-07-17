/**
 * 任务详情页 — 同时处理进行中 + 已完成 + 失败
 *
 * 进行中：7 阶段 Steps + 实时日志
 * 已完成：视频预览 + 打开目录
 * 失败：错误信息 + 日志链接
 */
import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Steps, Typography, Tag, Button, Space, Result, Empty,
  Alert, Progress, App, Tabs, Tooltip, Modal, Input, Row, Col
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  FolderOpenOutlined, ArrowLeftOutlined, ReloadOutlined,
  PlusOutlined, PlayCircleOutlined, BugOutlined, ScissorOutlined,
  EditOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { workerApi, errorReportApi, configApi } from '../api/client'
import { curateApi, type CurateResult, type CurateProgressEvent } from '../api/curate'
import type { JobResult, JobProgress, Provider } from '../../electron/types'

const { Title, Text, Paragraph } = Typography

// 7 阶段（与 worker job.py 的 logger.info("[N/7] xxx") 对应）
const STAGES = [
  { key: 'created', title: '已创建', idx: 0 },
  { key: 'preprocessed', title: '重编码', idx: 1 },
  { key: 'triplets_ready', title: '三联图', idx: 2 },
  { key: 'analyzed', title: 'AI 分析', idx: 3 },
  { key: 'planned', title: '编排', idx: 4 },
  { key: 'rendering', title: '渲染', idx: 5 },
  { key: 'completed', title: '完成', idx: 6 }
]

interface LogLine { ts: string; line: string; level?: string }

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const nav = useNavigate()
  const { message, modal } = App.useApp()
  const [progress, setProgress] = useState<JobProgress | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [logs, setLogs] = useState<LogLine[]>([])
  const [live, setLive] = useState(true)    // 是否还在跑
  const logRef = useRef<HTMLDivElement>(null)

  // 再编辑对话框状态
  const [regenOpen, setRegenOpen] = useState(false)
  const [regenInstruction, setRegenInstruction] = useState('')
  const [regenHistory, setRegenHistory] = useState<Array<{
    instruction: string; narrative?: string; error?: string; ts: string;
    final_video?: string | null
  }>>([])
  const [regenLoading, setRegenLoading] = useState(false)
  const [regenProgress, setRegenProgress] = useState<CurateProgressEvent | null>(null)
  const [regenLogs, setRegenLogs] = useState<Array<{ level: string; msg: string }>>([])
  const regenLogRef = useRef<HTMLDivElement>(null)

  // 初始加载（处理从 Dashboard 跳到已完成任务）
  useEffect(() => {
    if (!jobId) return
    workerApi.getJobDetail(jobId).then(d => {
      if (d.progress) setProgress(d.progress)
      if (d.result) {
        setResult(d.result)
        setLive(d.result.status !== 'completed' && d.result.status !== 'failed')
      }
    })
  }, [jobId])

  // 订阅实时事件
  useEffect(() => {
    if (!jobId) return
    const offP = workerApi.onProgress(p => {
      if (p.jobId !== jobId) return
      setProgress(p.progress as JobProgress)
    })
    const offL = workerApi.onLog(p => {
      if (p.jobId !== jobId) return
      setLogs(prev => [...prev.slice(-500), {
        ts: new Date().toLocaleTimeString(),
        line: p.line,
        level: p.level
      }])
    })
    const offD = workerApi.onDone(p => {
      if (p.jobId !== jobId) return
      setResult(p.result as JobResult)
      setLive(false)
      message.success('任务完成')
    })
    const offF = workerApi.onFailed(p => {
      if (p.jobId !== jobId) return
      setResult(p.result as JobResult || null)
      setLive(false)
      message.error(`任务失败: ${p.message}`)
    })
    return () => { offP(); offL(); offD(); offF() }
  }, [jobId])

  // 自动滚到底
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  // 订阅 curate 事件（再编辑用）
  useEffect(() => {
    if (!jobId) return
    const offLog = curateApi.onLog((p: { jobId: string; level: string; msg: string }) => {
      if (p.jobId !== jobId) return
      setRegenLogs(prev => [...prev.slice(-200), { level: p.level, msg: p.msg }])
    })
    const offProg = curateApi.onProgress((p: CurateProgressEvent) => {
      if (p.jobId !== jobId) return
      setRegenProgress(p)
    })
    return () => { offLog(); offProg() }
  }, [jobId])

  // regen 日志自动滚
  useEffect(() => {
    if (regenLogRef.current) regenLogRef.current.scrollTop = regenLogRef.current.scrollHeight
  }, [regenLogs])

  // 打开再编辑对话框：展示当前剪辑思路供参考，TextArea 留空给用户填修改要求
  const openRegenModal = () => {
    setRegenInstruction('')
    setRegenOpen(true)
  }

  const submitRegenerate = async () => {
    if (!jobId || !regenInstruction.trim()) return
    setRegenLoading(true)
    setRegenLogs([])
    setRegenProgress(null)
    const instruction = regenInstruction.trim()
    // 从 config 动态挑已配置的 provider（优先订阅套餐）
    const cfg = await configApi.getAll()
    const providers: Provider[] = ['doubao-agent-plan', 'doubao', 'qwen-vl', 'glm']
    const picked = providers.find(p => cfg.provider_keys[p]?.key) || 'doubao-agent-plan'
    const pickedModel = cfg.provider_keys[picked]?.model || 'ep-20260712162006-kcfdm'
    try {
      const r = await curateApi.regenerate(jobId, {
        instruction,
        target_duration: 0,  // 0 = 用原任务的 target_duration
        provider: picked,
        llm_model: pickedModel,
      }) as CurateResult
      // 后端按原 variants 数重跑了所有 final_v{i}.mp4，
      // 这里只记一条历史用于提示，真正展示靠刷新 variants 网格
      setRegenHistory(prev => [...prev, {
        instruction, narrative: r.narrative, ts: new Date().toLocaleTimeString(),
        final_video: r.final_video,
      }])
      setRegenInstruction('')
      message.success('再编辑完成，正在刷新视频…')
      // 重新拉取任务详情，让 variants 网格展示新的 final_v{i}.mp4
      const d = await workerApi.getJobDetail(jobId)
      if (d.result) setResult(d.result)
    } catch (e) {
      setRegenHistory(prev => [...prev, {
        instruction, error: (e as Error).message, ts: new Date().toLocaleTimeString(),
      }])
      message.error(`再编辑失败: ${(e as Error).message}`)
    } finally {
      setRegenLoading(false)
      setRegenProgress(null)
    }
  }

  if (!jobId) return <Empty description="无效的 job ID" />

  const cancel = async () => {
    await workerApi.cancel(jobId)
    message.info('已发送取消信号')
  }

  const openFolder = async () => {
    const ok = await workerApi.openFolder(jobId)
    if (!ok) message.warning('任务目录不存在')
  }

  const [reporting, setReporting] = useState(false)
  const reportError = () => {
    let messageText = ''
    modal.confirm({
      title: '上报错误',
      content: (
        <div style={{ marginTop: 8 }}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            将自动打包本任务的日志和系统信息一并发给管理员。请简要描述遇到的问题：
          </Typography.Paragraph>
          <input
            type="text"
            placeholder="例如：渲染阶段崩溃 / AI 分析无结果 / ..."
            style={{ width: '100%', padding: '6px 8px', border: '1px solid #d9d9d9', borderRadius: 4 }}
            onChange={e => { messageText = e.target.value }}
            autoFocus
          />
        </div>
      ),
      okText: '上报',
      cancelText: '取消',
      okButtonProps: { loading: reporting },
      onOk: async () => {
        if (!messageText.trim()) {
          message.warning('请填写问题描述')
          return Promise.reject()
        }
        setReporting(true)
        try {
          const r = await errorReportApi.submit(messageText.trim(), jobId)
          if (r.ok) {
            message.success(`已上报（#${r.id}）`)
          } else {
            message.error(r.error || '上报失败')
          }
        } finally {
          setReporting(false)
        }
      }
    })
  }

  // 当前阶段 idx
  const currentStageIdx = progress
    ? STAGES.find(s => s.key === progress.status)?.idx ?? 0
    : 0

  const isFailed = result?.status === 'failed' || progress?.status === 'failed'
  const isCompleted = result?.status === 'completed'

  // Steps 状态
  const stepStatus = (idx: number): 'wait' | 'process' | 'finish' | 'error' => {
    if (isFailed && idx === currentStageIdx) return 'error'
    if (idx < currentStageIdx) return 'finish'
    if (idx === currentStageIdx) return 'process'
    return 'wait'
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/')}>返回</Button>
        <Text code copyable>{jobId}</Text>
        {live && <Tag icon={<LoadingOutlined />} color="processing">进行中</Tag>}
        {isCompleted && <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>}
        {isFailed && <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
      </Space>

      <Card style={{ marginBottom: 16 }}>
        <Steps
          size="small"
          current={currentStageIdx}
          items={STAGES.map((s, i) => ({
            title: s.title,
            status: stepStatus(i)
          }))}
        />
      </Card>

      {result?.error && (
        <Alert
          type="error"
          message={`失败阶段: ${result.error.stage}`}
          description={result.error.message}
          showIcon
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" icon={<BugOutlined />} onClick={reportError}>
              上报错误
            </Button>
          }
        />
      )}

      <Tabs
        items={[
          {
            key: 'log',
            label: '实时日志',
            children: (
              <Card size="small" styles={{ body: { padding: 0 } }}>
                <div ref={logRef} style={{
                  background: '#1e1e1e',
                  color: '#d4d4d4',
                  padding: 12,
                  height: 360,
                  overflow: 'auto',
                  fontFamily: 'Consolas, "Courier New", monospace',
                  fontSize: 12,
                  lineHeight: 1.5
                }}>
                  {logs.length === 0 ? (
                    <Text style={{ color: '#888' }}>(等待日志...)</Text>
                  ) : (
                    logs.map((l, i) => (
                      <div key={i}>
                        <span style={{ color: '#888' }}>[{l.ts}]</span>{' '}
                        <span style={{
                          color: l.level === 'warn' ? '#ffaa00' :
                                 l.level === 'error' ? '#ff5555' : '#d4d4d4'
                        }}>{l.line}</span>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )
          },
          {
            key: 'history',
            label: '状态历史',
            children: (
              <Card size="small">
                {progress?.history?.length ? (
                  <Space direction="vertical">
                    {progress.history.map((h, i) => (
                      <Text key={i}>
                        <Tag>{h.status}</Tag>
                        <Text type="secondary">{h.ts}</Text>
                      </Text>
                    ))}
                  </Space>
                ) : <Text type="secondary">无</Text>}
              </Card>
            )
          }
        ]}
      />

      {isCompleted && result?.final_video && (
        <Card title={result.variants && result.variants.length > 1
          ? `结果（${result.variants.length} 个变体）`
          : '结果'} style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {result.variants && result.variants.length > 1 ? (
              <Row gutter={[16, 16]}>
                {result.variants.map(v => (
                  <Col xs={24} md={12} key={v.index}>
                    <Card
                      size="small"
                      title={
                        <Space>
                          <Tag color="blue">变体 {v.index}</Tag>
                          {v.style_hint
                            ? <Text type="secondary" style={{ fontSize: 12 }}>{v.style_hint.slice(0, 30)}</Text>
                            : <Text type="secondary" style={{ fontSize: 12 }}>默认平衡</Text>}
                        </Space>
                      }
                      type="inner"
                    >
                      {v.error ? (
                        <Result
                          status="error"
                          title="该变体生成失败"
                          subTitle={v.error}
                          style={{ padding: '12px 0' }}
                        />
                      ) : v.final_video ? (
                        <Space direction="vertical" style={{ width: '100%' }} size="small">
                          <video
                            src={`local-video://video?path=${encodeURIComponent(v.final_video.replace(/\\/g, '/'))}`}
                            controls
                            style={{ maxWidth: '100%', maxHeight: 320, background: '#000' }}
                          />
                          {v.narrative && (
                            <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
                              {v.narrative}
                            </Text>
                          )}
                          <Text type="secondary" style={{ fontSize: 10 }}>{v.final_video}</Text>
                        </Space>
                      ) : (
                        <Empty description="未生成视频" />
                      )}
                    </Card>
                  </Col>
                ))}
              </Row>
            ) : (
              <>
                <video
                  src={`local-video://video?path=${encodeURIComponent(result.final_video.replace(/\\/g, '/'))}`}
                  controls
                  style={{ maxWidth: '100%', maxHeight: 400, background: '#000' }}
                />
                {result.narrative && (
                  <Card size="small" type="inner" title="剪辑思路" style={{ background: '#fafafa' }}>
                    <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{result.narrative}</Paragraph>
                  </Card>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {result.final_video}
                </Text>
              </>
            )}
            <Space>
              <Button icon={<FolderOpenOutlined />} onClick={openFolder}>打开目录</Button>
              <Button icon={<ScissorOutlined />}
                      onClick={() => nav(`/jobs/${jobId}/curate`)}>手动剪辑</Button>
              <Button icon={<EditOutlined />} onClick={openRegenModal}>再次编辑</Button>
              <Button type="primary" icon={<PlusOutlined />}
                      onClick={() => nav('/jobs/new')}>新建任务</Button>
            </Space>
          </Space>
        </Card>
      )}

      {live && (
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Button danger onClick={cancel}>取消任务</Button>
        </div>
      )}

      {regenHistory.length > 0 && (
        <Card title={`再编辑历史（${regenHistory.length} 次）`}
              style={{ marginTop: 16 }}
              size="small">
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            {regenHistory.slice().reverse().map((h, i) => (
              <div key={i} style={{ fontSize: 12 }}>
                <Tag color={h.error ? 'red' : 'purple'}>{h.ts}</Tag>
                <Text strong> {(h.instruction || '').slice(0, 80)}</Text>
                {h.error ? (
                  <Text type="danger"> 失败：{h.error}</Text>
                ) : (
                  <Text type="secondary">
                    {' → '}{(h.narrative || '').slice(0, 100)}
                    {(h.narrative || '').length > 100 ? '...' : ''}
                  </Text>
                )}
              </div>
            ))}
            <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginBottom: 0, marginTop: 4 }}>
              每次再编辑会按原 variants 数重跑全部视频，新视频展示在上方结果网格。
            </Typography.Paragraph>
          </Space>
        </Card>
      )}

      {!live && !result?.final_video && (
        <Card style={{ marginTop: 16 }}>
          <Result
            status="warning"
            title="任务未生成最终视频"
            extra={
              <Space>
                <Button icon={<FolderOpenOutlined />} onClick={openFolder}>
                  查看任务日志
                </Button>
                <Button type="primary" icon={<BugOutlined />} onClick={reportError}>
                  上报错误
                </Button>
              </Space>
            }
          />
        </Card>
      )}

      {/* 自然语言再编辑对话框 */}
      <Modal
        open={regenOpen}
        title="自然语言再编辑"
        onCancel={() => { if (!regenLoading) setRegenOpen(false) }}
        width={720}
        footer={null}
        maskClosable={false}
        closable={!regenLoading}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
            用自然语言描述想要的调整。会按原任务的 variants 数重跑全部视频，把你的要求作为约束传给 LLM
            （例如「去掉晃动大的镜头」「整体压缩到 20 秒」「中段加慢镜头」）。
          </Typography.Paragraph>

          {(() => {
            const v0 = result?.variants?.[0]
            const curNarrative = v0?.narrative || result?.narrative
            const curHint = v0?.style_hint || ''
            if (!curNarrative && !curHint) return null
            return (
              <Card size="small" type="inner" title="当前 variant 1 的剪辑思路（仅供参考）"
                    styles={{ body: { padding: 8 } }}>
                {curHint && (
                  <div style={{ fontSize: 12, marginBottom: 4 }}>
                    <Typography.Text strong>风格：</Typography.Text>
                    <Typography.Text type="secondary"> {curHint}</Typography.Text>
                  </div>
                )}
                {curNarrative && (
                  <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: 0, whiteSpace: 'pre-wrap' }}>
                    {curNarrative}
                  </Typography.Paragraph>
                )}
              </Card>
            )
          })()}

          {regenHistory.length > 0 && (
            <Card size="small" title="编辑历史" type="inner">
              {regenHistory.map((h, i) => (
                <div key={i} style={{ marginBottom: 8, fontSize: 12 }}>
                  <Tag color="blue">{h.ts}</Tag>
                  <Typography.Text strong> {h.instruction}</Typography.Text>
                  {h.error ? (
                    <Typography.Text type="danger"> 失败：{h.error}</Typography.Text>
                  ) : (
                    <Typography.Text type="secondary">
                      {' → '}{(h.narrative || '').slice(0, 80)}
                      {(h.narrative || '').length > 80 ? '...' : ''}
                    </Typography.Text>
                  )}
                </div>
              ))}
            </Card>
          )}

          <Input.TextArea
            value={regenInstruction}
            onChange={e => setRegenInstruction(e.target.value)}
            placeholder="例如：把开头的酒瓶特写换成倒酒镜头 / 整体压缩到 30 秒 / 中段加一段慢镜头 / 加快节奏"
            rows={3}
            disabled={regenLoading}
            autoFocus
          />

          <Space>
            <Button
              type="primary"
              icon={<EditOutlined />}
              loading={regenLoading}
              disabled={!regenInstruction.trim()}
              onClick={submitRegenerate}
            >
              提交编辑
            </Button>
            {regenLoading && regenProgress && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                [{regenProgress.stage}] {regenProgress.msg} ({regenProgress.done}/{regenProgress.todo})
              </Typography.Text>
            )}
          </Space>

          {regenLoading && (
            <Card size="small" type="inner" styles={{ body: { padding: 0 } }}>
              <div ref={regenLogRef} style={{
                background: '#1e1e1e', color: '#d4d4d4', padding: 8,
                height: 160, overflow: 'auto',
                fontFamily: 'Consolas, "Courier New", monospace', fontSize: 11,
              }}>
                {regenLogs.length === 0 ? (
                  <Typography.Text style={{ color: '#888' }}>(等待日志...)</Typography.Text>
                ) : (
                  regenLogs.map((l, i) => (
                    <div key={i}>
                      <span style={{
                        color: l.level === 'warn' ? '#ffaa00' :
                               l.level === 'error' ? '#ff5555' : '#d4d4d4'
                      }}>{l.msg}</span>
                    </div>
                  ))
                )}
              </div>
            </Card>
          )}
        </Space>
      </Modal>
    </div>
  )
}
