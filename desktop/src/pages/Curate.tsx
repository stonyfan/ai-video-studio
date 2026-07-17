/**
 * 手动剪辑页 — 浏览 stages + 多选 scenes + 预览 + 提交 LLM 决策
 *
 * URL：/#/jobs/:jobId/curate?input_dir=<encoded>
 *
 * 流程（subprocess 模式）：
 * 1. mount → getData（首次触发 LLM 生成 stages，10-30s）
 * 2. data 返回 → 后台 buildPreviews（幂等，已就绪秒回）
 * 3. 用户勾选 + 填 brief + 提交
 * 4. submit Promise → 期间监听 curate:log / curate:progress
 * 5. resolve → 弹窗播放成片 + 显示 narrative
 */
import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import type { DragEvent as ReactDragEvent } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, InputNumber, Input, Space, Typography, Tag, Checkbox,
  Row, Col, Spin, Alert, Modal, Result, App, Skeleton, Empty,
} from 'antd'
import {
  ArrowLeftOutlined, ScissorOutlined, ReloadOutlined, HolderOutlined,
} from '@ant-design/icons'

import {
  curateApi, type CurateData, type CurateResult,
  type CurateLogEvent, type CurateProgressEvent,
} from '../api/curate'
import SceneCard from '../components/SceneCard'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

interface LogItem { level: string; msg: string }

export default function Curate() {
  const { jobId } = useParams<{ jobId: string }>()
  const [searchParams] = useSearchParams()
  const inputDir = searchParams.get('input_dir') || undefined
  const nav = useNavigate()
  const { message } = App.useApp()

  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<CurateData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [buildingPrev, setBuildingPrev] = useState(false)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [target, setTarget] = useState<number>(60)
  const [brief, setBrief] = useState('')

  // stage 拖拽重排：stageOrder 存 stage id 顺序，dragId 跟踪当前拖动的 stage id
  const [stageOrder, setStageOrder] = useState<string[]>([])
  const [dragId, setDragId] = useState<string | null>(null)

  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<CurateResult | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [logs, setLogs] = useState<LogItem[]>([])
  const [progress, setProgress] = useState<CurateProgressEvent | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const loadData = useCallback(async () => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    try {
      const d = await curateApi.getData(jobId, inputDir)
      setData(d)
      setTarget(Math.round(d.target_duration_default))
      setStageOrder(d.stages.map((s: { id: string }) => s.id))
      // 默认勾选：优先用 worker 自动成片实际选的段；fallback 到每个 stage 的 representative
      const initSel = new Set<string>(d.auto_selected_ids)
      if (initSel.size === 0) {
        for (const st of d.stages) {
          if (st.representative) initSel.add(st.representative)
        }
      }
      setSelected(initSel)
      // 后台刷预览（不阻塞 UI）
      if (!d.previews_ready) {
        setBuildingPrev(true)
        curateApi.buildPreviews(jobId).then(async () => {
          // 刷一遍 data，让 preview_ready 生效
          const d2 = await curateApi.getData(jobId, inputDir)
          setData(d2)
        }).catch(e => {
          message.warning(`预览生成失败: ${(e as Error).message}`)
        }).finally(() => setBuildingPrev(false))
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [jobId, inputDir, message])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 订阅 curate 事件（只对当前 jobId 感兴趣）
  useEffect(() => {
    if (!jobId) return
    const offLog = curateApi.onLog((p: CurateLogEvent) => {
      if (p.jobId !== jobId) return
      setLogs(prev => [...prev.slice(-500), { level: p.level, msg: p.msg }])
    })
    const offProg = curateApi.onProgress((p: CurateProgressEvent) => {
      if (p.jobId !== jobId) return
      setProgress(p)
    })
    return () => { offLog(); offProg() }
  }, [jobId])

  // 自动滚日志
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const toggleScene = useCallback((id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleStageAll = useCallback((sceneIds: string[]) => {
    setSelected(prev => {
      const next = new Set(prev)
      const allSelected = sceneIds.every(id => next.has(id))
      if (allSelected) {
        for (const id of sceneIds) next.delete(id)
      } else {
        for (const id of sceneIds) next.add(id)
      }
      return next
    })
  }, [])

  // stage 拖拽：HTML5 native drag-and-drop
  const onStageDragStart = (id: string) => setDragId(id)
  const onStageDragOver = (e: ReactDragEvent, overId: string) => {
    e.preventDefault()
    if (!dragId || dragId === overId) return
    setStageOrder(prev => {
      const from = prev.indexOf(dragId)
      const to = prev.indexOf(overId)
      if (from < 0 || to < 0) return prev
      const next = [...prev]
      next.splice(from, 1)
      next.splice(to, 0, dragId)
      return next
    })
  }
  const onStageDragEnd = () => setDragId(null)

  // 按 stageOrder 渲染；data.stages 用 id → stage 索引查
  const orderedStages = useMemo(() => {
    if (!data) return []
    const byId = new Map(data.stages.map(s => [s.id, s]))
    return stageOrder.map(id => byId.get(id)).filter((s): s is NonNullable<typeof s> => !!s)
  }, [data, stageOrder])

  const selectedCount = selected.size
  const selectedDur = useMemo(() => {
    if (!data) return 0
    let s = 0
    for (const id of selected) {
      const sc = data.scenes_by_id[id]
      if (sc) s += (sc.end - sc.start)
    }
    return s
  }, [selected, data])

  const canSubmit = selectedCount > 0 && !submitting

  const handleSubmit = async () => {
    if (!jobId || !data) return
    setSubmitting(true)
    setResult(null)
    setSubmitError(null)
    setLogs([])
    setProgress(null)
    try {
      const selections = orderedStages
        .map(st => ({
          stage_id: st.id,
          scene_ids: st.scene_ids.filter(id => selected.has(id)),
        }))
        .filter(s => s.scene_ids.length > 0)

      const r = await curateApi.submit(jobId, {
        selections,
        target_duration: target,
        brief,
        provider: 'doubao',
        llm_model: 'ep-20260712162006-kcfdm',
      }, inputDir)

      setResult(r)
      message.success('渲染完成')
    } catch (e) {
      const msg = (e as Error).message
      setSubmitError(msg)
      message.error(`渲染失败: ${msg}`)
    } finally {
      setSubmitting(false)
      setProgress(null)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav(-1)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>
          <ScissorOutlined /> 手动剪辑 · {jobId}
        </Title>
        {buildingPrev && <Tag icon={<Spin size="small" />} color="processing">生成预览中</Tag>}
      </Space>

      {/* 顶部控制条 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text>目标时长：</Text>
          <InputNumber
            min={10} max={180} step={5}
            value={target}
            onChange={v => setTarget(Number(v) || 60)}
            addonAfter="秒"
            style={{ width: 130 }}
            disabled={submitting}
          />
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading} disabled={submitting}>
            刷新
          </Button>
          <Text type="secondary">
            已勾选 <Text strong>{selectedCount}</Text> 段，
            可用素材时长 <Text strong>{selectedDur.toFixed(1)}</Text> 秒
          </Text>
        </Space>
      </Card>

      {error && (
        <Alert
          type="error" showIcon
          message="加载失败"
          description={error}
          style={{ marginBottom: 16 }}
          action={<Button size="small" onClick={loadData}>重试</Button>}
        />
      )}

      {loading && (
        <Card>
          <Skeleton active paragraph={{ rows: 8 }} />
          <Text type="secondary" style={{ marginTop: 16, display: 'block' }}>
            首次加载会调用 LLM 生成故事阶段（约 10-30 秒），并后台批量切预览视频（1-2 分钟）……
          </Text>
        </Card>
      )}

      {/* Stages 列表（横向 wrap，可拖拽重排） */}
      {!loading && data && (
        <>
          {data.stages.length === 0 && <Empty description="无故事阶段数据" />}
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
            <HolderOutlined /> 拖动 stage 卡片可重排顺序，提交时按你的顺序作为叙事主线
          </Paragraph>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
            {orderedStages.map((stage, idx) => {
              const sceneIds = stage.scene_ids
              const stageSelected = sceneIds.filter(id => selected.has(id))
              const allSelected = sceneIds.length > 0 && stageSelected.length === sceneIds.length
              const indeterminate = stageSelected.length > 0 && !allSelected

              return (
                <Card
                  key={stage.id}
                  size="small"
                  draggable={!submitting}
                  onDragStart={() => onStageDragStart(stage.id)}
                  onDragOver={(e) => onStageDragOver(e, stage.id)}
                  onDragEnd={onStageDragEnd}
                  style={{
                    flex: '1 1 420px',
                    minWidth: 360,
                    maxWidth: 760,
                    opacity: dragId === stage.id ? 0.4 : 1,
                    cursor: submitting ? 'default' : 'grab',
                    borderStyle: dragId === stage.id ? 'dashed' : 'solid',
                    borderColor: dragId === stage.id ? '#1677ff' : undefined,
                  }}
                  title={
                    <Space wrap>
                      <HolderOutlined style={{ cursor: 'grab', color: '#999' }} />
                      <Checkbox
                        indeterminate={indeterminate}
                        checked={allSelected}
                        onChange={() => toggleStageAll(sceneIds)}
                        onClick={e => e.stopPropagation()}
                        disabled={submitting}
                      />
                      <Tag color="purple">Stage {idx + 1}</Tag>
                      <Text strong>{stage.title}</Text>
                      <Tag>{stageSelected.length}/{sceneIds.length}</Tag>
                    </Space>
                  }
                >
                  <div style={{
                    maxHeight: 380,
                    overflowY: 'auto',
                    paddingRight: 4,
                  }}>
                    <Row gutter={[8, 8]}>
                      {sceneIds.map(id => {
                        const sc = data.scenes_by_id[id]
                        if (!sc) return null
                        return (
                          <Col key={id} xs={12} sm={12} md={8} lg={8} xl={6}>
                            <SceneCard
                              scene={sc}
                              selected={selected.has(id)}
                              isRepresentative={stage.representative === id}
                              onToggle={toggleScene}
                            />
                          </Col>
                        )
                      })}
                    </Row>
                  </div>
                  {sceneIds.length > 6 && (
                    <Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block', textAlign: 'center' }}>
                      共 {sceneIds.length} 段，区域内滚动查看更多
                    </Text>
                  )}
                </Card>
              )
            })}
          </div>
        </>
      )}

      {/* 底部 Brief + 提交 */}
      {!loading && data && (
        <Card title="提交剪辑" style={{ marginTop: 16 }}>
          <Paragraph type="secondary" style={{ fontSize: 12 }}>
            LLM 会<strong>只能用你勾选的段</strong>挑段、分配时长、排序、写一段叙事。
            可选填 brief 描述你的剪辑意图。
          </Paragraph>
          <TextArea
            value={brief}
            onChange={e => setBrief(e.target.value)}
            placeholder="可选：例如「白盘杏子开场 2 秒，中段倒酒 2 次不同角度，成品展示收尾」"
            rows={3}
            style={{ marginBottom: 12 }}
            disabled={submitting}
          />
          <Space>
            <Button
              type="primary" size="large"
              icon={<ScissorOutlined />}
              disabled={!canSubmit}
              loading={submitting}
              onClick={handleSubmit}
            >
              提交剪辑（{selectedCount} 段 → {target} 秒）
            </Button>
            {submitting && progress && (
              <Text type="secondary">
                [{progress.stage}] {progress.msg} ({progress.done}/{progress.todo})
              </Text>
            )}
          </Space>
        </Card>
      )}

      {/* 渲染结果弹窗 */}
      <Modal
        open={submitting || !!result || !!submitError}
        title="剪辑结果"
        footer={result ? [
          <Button key="again" onClick={() => { setResult(null); setSubmitError(null) }}>再剪一次</Button>,
          <Button key="back" type="primary" onClick={() => nav(-1)}>完成（已保存）</Button>,
        ] : (submitError ? [
          <Button key="retry" type="primary" onClick={() => { setSubmitError(null) }}>关闭</Button>,
        ] : null)}
        onCancel={() => {
          if (!submitting) { setResult(null); setSubmitError(null) }
        }}
        width={720}
        maskClosable={false}
        closable={!submitting}
      >
        {submitting && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Result
              icon={<Spin size="large" />}
              title="渲染中"
              subTitle={progress ? `[${progress.stage}] ${progress.msg}` : '已入队…'}
            />
            {/* 日志面板 */}
            <Card size="small" type="inner" styles={{ body: { padding: 0 } }}>
              <div ref={logRef} style={{
                background: '#1e1e1e',
                color: '#d4d4d4',
                padding: 12,
                height: 200,
                overflow: 'auto',
                fontFamily: 'Consolas, "Courier New", monospace',
                fontSize: 12,
                lineHeight: 1.5,
              }}>
                {logs.length === 0 ? (
                  <Text style={{ color: '#888' }}>(等待日志...)</Text>
                ) : (
                  logs.map((l, i) => (
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
          </Space>
        )}
        {submitError && !submitting && (
          <Result
            status="error"
            title="渲染失败"
            subTitle={<Text type="danger" style={{ whiteSpace: 'pre-wrap' }}>{submitError}</Text>}
          />
        )}
        {result && !submitting && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <video
              key={`v${result.total_duration}_${result.items.length}_${result.final_video}`}
              src={`local-video://video?path=${encodeURIComponent(result.final_video.replace(/\\/g, '/'))}&t=${result.total_duration}_${result.items.length}`}
              controls
              style={{ width: '100%', maxHeight: 400, background: '#000' }}
            />
            <Card size="small" type="inner" title="成片信息">
              <Space direction="vertical" size={4}>
                <Text>段数 <Text strong>{result.items.length}</Text> · 总时长 <Text strong>{result.total_duration.toFixed(1)}s</Text></Text>
                <Text type="secondary" copyable style={{ fontSize: 11, wordBreak: 'break-all' }}>
                  {result.final_video}
                </Text>
                <Text type="success" style={{ fontSize: 11 }}>已保存为 output/final.mp4（覆盖 worker 自动成片）</Text>
              </Space>
            </Card>
            {result.narrative && (
              <Card size="small" title="叙事描述" type="inner">
                <Paragraph>{result.narrative}</Paragraph>
              </Card>
            )}
            <Card size="small" title={`成片段数 ${result.items.length}（总时长 ${result.total_duration.toFixed(1)}s）`} type="inner">
              {result.items.map(it => (
                <div key={it.order} style={{ fontSize: 12, marginBottom: 4 }}>
                  <Text strong>{it.order}. {it.id}</Text>
                  <Text type="secondary"> [{it.use_start.toFixed(2)}-{it.use_end.toFixed(2)}] = {it.cut_duration.toFixed(2)}s</Text>
                  <Text type="secondary"> · {it.reason}</Text>
                </div>
              ))}
            </Card>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {result.final_video}
            </Text>
          </Space>
        )}
      </Modal>
    </div>
  )
}
